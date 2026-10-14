"""Caso de uso: carregar os comunicados oficiais (base IPE da CVM).

Mesmo esqueleto de CarregarFundamentos - confere schema, resolve o universo,
pula ano cujo arquivo nao mudou (ETag), grava numa transacao por ano e
publica evento so do que e novo. Depende apenas de portas.

Diferenca importante: o CNPJ de cada ticker vem de cvm_ticker, que a carga de
fundamentos mantem. Ticker que ainda nao passou por ela nao tem comunicado -
e o log diz isso, em vez de o ticker simplesmente sumir.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from logging import Logger

from app.dominio.comunicado import CATEGORIAS_PADRAO, Comunicado
from app.dominio.modelo import STATUS_ERRO, STATUS_PULADO, STATUS_SUCESSO
from app.excecoes.excecoes import ErroPermanente, ErroTransitorio
from app.portas.fonte_comunicados import FonteDeComunicados
from app.portas.publicador import PublicadorDeComunicados
from app.portas.repositorios import (
    ConsultaDeTickers,
    RepositorioComunicado,
    RepositorioExecucao,
    RepositorioUniverso,
)

FONTE_IPE = "CVM_IPE"
EVENTO_COMUNICADOS = "COMUNICADOS_PUBLICADOS"


def arquivo_do_ano(ano: int) -> str:
    return f"ipe_cia_aberta_{ano}.zip"


@dataclass
class ResultadoDaCargaDeComunicados:
    anos_processados: list[int] = field(default_factory=list)
    anos_pulados: list[int] = field(default_factory=list)
    documentos_lidos: int = 0
    documentos_gravados: int = 0
    simbolos_com_novidade: list[str] = field(default_factory=list)
    erros: list[str] = field(default_factory=list)

    @property
    def sucesso(self) -> bool:
        return not self.erros


class CarregarComunicados:
    def __init__(
        self,
        fonte: FonteDeComunicados,
        unidade_de_trabalho,
        repositorio_universo: RepositorioUniverso,
        consulta_de_tickers: ConsultaDeTickers,
        repositorio_comunicado: RepositorioComunicado,
        repositorio_execucao: RepositorioExecucao,
        verificador_de_schema,
        nome_do_banco: str,
        publicador: PublicadorDeComunicados,
        logger: Logger,
    ):
        self._fonte = fonte
        self._uow = unidade_de_trabalho
        self._universo = repositorio_universo
        self._tickers = consulta_de_tickers
        self._comunicados = repositorio_comunicado
        self._execucao = repositorio_execucao
        self._verificador = verificador_de_schema
        self._nome_do_banco = nome_do_banco
        self._publicador = publicador
        self._logger = logger

    def executar(
        self,
        anos: list[int],
        simbolos_pedidos: list[str] | None = None,
        categorias: Collection[str] = CATEGORIAS_PADRAO,
        forcar: bool = False,
    ) -> ResultadoDaCargaDeComunicados:
        """`forcar` ignora o ETag. Serve quando o universo ou as categorias
        mudaram: o arquivo da CVM e o mesmo, mas o recorte pedido nao."""
        resultado = ResultadoDaCargaDeComunicados()

        with self._uow.transacao() as db:
            self._verificador.conferir(db, self._nome_do_banco)

        simbolo_para_cnpj = self._resolver_universo(simbolos_pedidos)
        if not simbolo_para_cnpj:
            return resultado

        cnpjs = set(simbolo_para_cnpj.values())
        novos: list[Comunicado] = []

        for ano in sorted(anos):
            try:
                novos.extend(
                    self._processar_ano(ano, cnpjs, set(categorias), forcar, resultado)
                )
            except (ErroTransitorio, ErroPermanente) as erro:
                self._logger.error("Comunicados %s falharam: %s", ano, erro)
                resultado.erros.append(f"{ano}: {erro}")
                self._registrar(ano, STATUS_ERRO, mensagem=str(erro))

        eventos = montar_eventos(novos, simbolo_para_cnpj)
        resultado.simbolos_com_novidade = [e["simbolo"] for e in eventos]
        self._publicador.publicar_comunicados(eventos)
        return resultado

    def _resolver_universo(self, simbolos_pedidos: list[str] | None) -> dict[str, str]:
        with self._uow.transacao() as db:
            if simbolos_pedidos:
                simbolos = [s.strip().upper() for s in simbolos_pedidos if s.strip()]
            else:
                simbolos = self._universo.listar_simbolos_monitorados(db)
            if not simbolos:
                self._logger.warning(
                    "Nenhum ativo monitorado. Registre um com "
                    "POST /ativos/registrar/{ticker} no gestor-ativos-brutos."
                )
                return {}
            mapa = self._tickers.cnpjs_por_simbolo(db, simbolos)

        sem_cnpj = sorted(set(simbolos) - set(mapa))
        if sem_cnpj:
            self._logger.warning(
                "Sem CNPJ em cvm_ticker (rode antes a carga de fundamentos): %s",
                ", ".join(sem_cnpj),
            )
        self._logger.info(
            "Universo de comunicados: %d simbolo(s), %d companhia(s)",
            len(mapa),
            len(set(mapa.values())),
        )
        return mapa

    def _processar_ano(
        self,
        ano: int,
        cnpjs: set[str],
        categorias: set[str],
        forcar: bool,
        resultado: ResultadoDaCargaDeComunicados,
    ) -> list[Comunicado]:
        competencia = str(ano)
        arquivo = arquivo_do_ano(ano)

        assinatura = self._fonte.assinatura(ano)
        if not forcar:
            with self._uow.transacao() as db:
                etag_anterior = self._execucao.etag_da_ultima_execucao(
                    db, FONTE_IPE, competencia, arquivo
                )
            if assinatura.inalterado_em_relacao_a(etag_anterior):
                self._logger.info("IPE %s inalterado (ETag igual); pulando", ano)
                resultado.anos_pulados.append(ano)
                self._registrar(ano, STATUS_PULADO, assinatura=assinatura)
                return []

        lidos = self._fonte.comunicados(ano, cnpjs, categorias)
        with self._uow.transacao() as db:
            gravados = self._comunicados.salvar(db, lidos)
            self._execucao.registrar(
                db,
                fonte=FONTE_IPE,
                competencia=competencia,
                arquivo=arquivo,
                status=STATUS_SUCESSO,
                etag=assinatura.etag,
                last_modified=assinatura.last_modified,
                tamanho_bytes=assinatura.tamanho_bytes,
                linhas_carregadas=len(gravados),
            )

        resultado.anos_processados.append(ano)
        resultado.documentos_lidos += len(lidos)
        resultado.documentos_gravados += len(gravados)
        self._logger.info(
            "IPE %s: %d documento(s) no recorte, %d novo(s) ou reapresentado(s)",
            ano,
            len(lidos),
            len(gravados),
        )
        return gravados

    def _registrar(
        self, ano: int, status: str, assinatura=None, mensagem: str | None = None
    ) -> None:
        try:
            with self._uow.transacao() as db:
                self._execucao.registrar(
                    db,
                    fonte=FONTE_IPE,
                    competencia=str(ano),
                    arquivo=arquivo_do_ano(ano),
                    status=status,
                    etag=getattr(assinatura, "etag", None),
                    last_modified=getattr(assinatura, "last_modified", None),
                    tamanho_bytes=getattr(assinatura, "tamanho_bytes", None),
                    mensagem_erro=mensagem,
                )
        except Exception as erro:
            self._logger.error("Falha ao registrar execucao do IPE %s: %s", ano, erro)


def montar_eventos(
    novos: Sequence[Comunicado], simbolo_para_cnpj: dict[str, str]
) -> list[dict]:
    """Um evento por ticker (contrato CTR-09).

    Uma companhia com dois tickers monitorados (PETR3 e PETR4) gera dois
    eventos: quem consome pensa em ticker, nao em CNPJ.
    """
    por_cnpj: dict[str, list[Comunicado]] = defaultdict(list)
    for comunicado in novos:
        por_cnpj[comunicado.cnpj].append(comunicado)

    eventos = []
    for simbolo, cnpj in sorted(simbolo_para_cnpj.items()):
        documentos = por_cnpj.get(cnpj)
        if not documentos:
            continue
        eventos.append(
            {
                "schemaVersion": "1.0",
                "evento": EVENTO_COMUNICADOS,
                "simbolo": simbolo,
                "cnpj": cnpj,
                "protocolos": sorted(d.protocolo_cvm for d in documentos),
                "categorias": sorted({d.categoria for d in documentos}),
                "dataEntregaMax": max(d.data_entrega for d in documentos).isoformat(),
            }
        )
    return eventos
