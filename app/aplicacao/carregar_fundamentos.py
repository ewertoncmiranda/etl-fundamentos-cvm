"""Caso de uso: carregar fundamentos da CVM para os ativos monitorados.

Depende so de portas - nada aqui sabe que existe MySQL, HTTP ou ZIP. Quem
escolhe as implementacoes concretas e o composition root em main.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from logging import Logger

from app.dominio.identidade import resolver_tickers
from app.dominio.modelo import STATUS_ERRO, STATUS_PULADO, STATUS_SUCESSO, Empresa, Ticker
from app.dominio.montador_indicadores import MontadorDeIndicadores
from app.excecoes.excecoes import ErroPermanente, ErroTransitorio
from app.portas.fonte_documentos import FonteDeDocumentos
from app.portas.publicador import PublicadorDeEventos
from app.portas.repositorios import (
    RepositorioCadastro,
    RepositorioExecucao,
    RepositorioFatoContabil,
    RepositorioIndicador,
    RepositorioUniverso,
)

FONTE_DFP = "CVM_DFP"


@dataclass
class ResultadoDaCarga:
    anos_processados: list[int] = field(default_factory=list)
    anos_pulados: list[int] = field(default_factory=list)
    simbolos_atualizados: list[str] = field(default_factory=list)
    linhas_landing: int = 0
    indicadores_gravados: int = 0
    erros: list[str] = field(default_factory=list)

    @property
    def sucesso(self) -> bool:
        return not self.erros


class CarregarFundamentos:
    def __init__(
        self,
        fonte: FonteDeDocumentos,
        unidade_de_trabalho,
        repositorio_universo: RepositorioUniverso,
        repositorio_cadastro: RepositorioCadastro,
        repositorio_fato: RepositorioFatoContabil,
        repositorio_indicador: RepositorioIndicador,
        repositorio_execucao: RepositorioExecucao,
        verificador_de_schema,
        nome_do_banco: str,
        montador: MontadorDeIndicadores,
        publicador: PublicadorDeEventos,
        logger: Logger,
        repositorio_identidade=None,
    ):
        self._fonte = fonte
        self._uow = unidade_de_trabalho
        self._universo = repositorio_universo
        self._cadastro = repositorio_cadastro
        self._fato = repositorio_fato
        self._indicador = repositorio_indicador
        self._execucao = repositorio_execucao
        self._verificador = verificador_de_schema
        self._nome_do_banco = nome_do_banco
        self._montador = montador
        self._publicador = publicador
        self._logger = logger
        self._identidade = repositorio_identidade
        self._forcar = False

    def executar(
        self,
        anos: list[int],
        simbolos_pedidos: list[str] | None = None,
        forcar: bool = False,
    ) -> ResultadoDaCarga:
        """forcar: processa mesmo com ETag igual - necessario quando o universo
        ou a curadoria de identidade mudou e o arquivo da CVM nao."""
        resultado = ResultadoDaCarga()
        self._forcar = forcar

        # Falha cedo e com instrucao, em vez de estourar no primeiro INSERT
        with self._uow.transacao() as db:
            self._verificador.conferir(db, self._nome_do_banco)

        simbolos = self._resolver_universo(simbolos_pedidos)
        if not simbolos:
            self._logger.warning(
                "Nenhum ativo monitorado. Registre um com "
                "POST /ativos/registrar/{ticker} no gestor-ativos-brutos."
            )
            return resultado

        self._logger.info("Universo: %d simbolos - %s", len(simbolos), ", ".join(simbolos))

        for ano in sorted(anos):
            try:
                self._processar_ano(ano, simbolos, resultado)
            except ErroTransitorio as erro:
                # Pode dar certo na proxima execucao: registra e segue os outros anos
                self._logger.error("Ano %s falhou por causa transitoria: %s", ano, erro)
                resultado.erros.append(f"{ano}: {erro}")
                self._registrar(ano, STATUS_ERRO, mensagem=str(erro))
            except ErroPermanente as erro:
                self._logger.error("Ano %s tem problema permanente: %s", ano, erro)
                resultado.erros.append(f"{ano}: {erro}")
                self._registrar(ano, STATUS_ERRO, mensagem=str(erro))

        self._conferir_acoes(sorted(set(resultado.simbolos_atualizados)))

        if resultado.simbolos_atualizados:
            self._publicador.publicar_fundamentos_atualizados(
                sorted(set(resultado.simbolos_atualizados))
            )

        return resultado

    def _resolver_universo(self, simbolos_pedidos: list[str] | None) -> list[str]:
        if simbolos_pedidos:
            return [s.strip().upper() for s in simbolos_pedidos if s.strip()]
        with self._uow.transacao() as db:
            return self._universo.listar_simbolos_monitorados(db)

    def _processar_ano(self, ano: int, simbolos: list[str], resultado: ResultadoDaCarga) -> None:
        competencia = str(ano)
        arquivo = f"dfp_cia_aberta_{ano}.zip"

        assinatura = self._fonte.assinatura("DFP", ano)
        with self._uow.transacao() as db:
            etag_anterior = self._execucao.etag_da_ultima_execucao(
                db, FONTE_DFP, competencia, arquivo
            )

        if not self._forcar and assinatura.inalterado_em_relacao_a(etag_anterior):
            self._logger.info("DFP %s inalterado (ETag igual); pulando", ano)
            resultado.anos_pulados.append(ano)
            self._registrar(ano, STATUS_PULADO, assinatura=assinatura)
            return

        with self._uow.transacao() as db:
            conhecidos = self._cadastro.cnpjs_por_simbolo(db, simbolos)
        selecionados, ausentes = resolver_tickers(
            simbolos, self._fonte.tickers(ano), self._identidades(), conhecidos
        )
        if ausentes:
            self._logger.warning("Sem ticker no FCA %s: %s", ano, ", ".join(ausentes))
        if not selecionados:
            resultado.anos_pulados.append(ano)
            self._registrar(ano, STATUS_PULADO, assinatura=assinatura)
            return

        cnpjs = {t.cnpj for t in selecionados.values()}
        cnpj_para_simbolos: dict[str, list[str]] = {}
        for simbolo, ticker in selecionados.items():
            cnpj_para_simbolos.setdefault(ticker.cnpj, []).append(simbolo)

        empresas = self._fonte.empresas(ano)
        capitais = self._fonte.composicoes_de_capital(ano, cnpjs)
        entregas = self._fonte.datas_de_entrega("DFP", ano, cnpjs)

        linhas_gravadas = 0
        indicadores_do_ano = []

        with self._uow.transacao() as db:
            self._cadastro.salvar_empresas(
                db,
                [empresas.get(c) or _empresa_minima(c, selecionados) for c in cnpjs],
            )
            self._cadastro.salvar_tickers(db, list(selecionados.values()))

            for documento in self._fonte.documentos(ano, cnpjs):
                todas_as_linhas = [
                    linha
                    for linhas in documento.linhas.values()
                    for linha in linhas
                ]
                linhas_gravadas += self._fato.salvar_linhas(
                    db,
                    cnpj=documento.cnpj,
                    tipo_doc=documento.tipo_doc,
                    grupo=documento.grupo,
                    versao=documento.versao,
                    dt_refer=documento.dt_refer,
                    linhas=todas_as_linhas,
                )

                capital = capitais.get(documento.cnpj)
                if capital:
                    self._fato.salvar_composicao(db, capital, documento.tipo_doc)

                entrega = data_de_entrega(
                    entregas, documento.cnpj, documento.dt_refer, documento.versao
                )
                if entrega is None:
                    self._logger.warning(
                        "DFP %s sem DT_RECEB para %s (%s v%s): fica fora do backtest",
                        ano, documento.cnpj, documento.dt_refer, documento.versao,
                    )
                for simbolo in cnpj_para_simbolos.get(documento.cnpj, []):
                    indicadores_do_ano.append(
                        replace(
                            self._montador.montar(simbolo, documento, capital),
                            data_entrega=entrega,
                        )
                    )

            if indicadores_do_ano:
                self._indicador.salvar(db, indicadores_do_ano)

            self._execucao.registrar(
                db,
                fonte=FONTE_DFP,
                competencia=competencia,
                arquivo=arquivo,
                status=STATUS_SUCESSO,
                etag=assinatura.etag,
                last_modified=assinatura.last_modified,
                tamanho_bytes=assinatura.tamanho_bytes,
                linhas_carregadas=linhas_gravadas,
            )

        resultado.anos_processados.append(ano)
        resultado.linhas_landing += linhas_gravadas
        resultado.indicadores_gravados += len(indicadores_do_ano)
        resultado.simbolos_atualizados.extend(i.simbolo for i in indicadores_do_ano)
        self._logger.info(
            "Ano %s: %d linhas na landing, %d indicadores",
            ano,
            linhas_gravadas,
            len(indicadores_do_ano),
        )

    def _conferir_acoes(self, simbolos: list[str]) -> None:
        conferir = getattr(self._indicador, "conferir_acoes", None)
        if not simbolos or conferir is None:
            return
        with self._uow.transacao() as db:
            for linha in conferir(db, simbolos):
                self._logger.warning("Quantidade de acoes corrigida: %s", linha)

    def _identidades(self):
        if self._identidade is None:
            return {}
        with self._uow.transacao() as db:
            return self._identidade.identidades(db)

    def _registrar(
        self,
        ano: int,
        status: str,
        assinatura=None,
        mensagem: str | None = None,
    ) -> None:
        try:
            with self._uow.transacao() as db:
                self._execucao.registrar(
                    db,
                    fonte=FONTE_DFP,
                    competencia=str(ano),
                    arquivo=f"dfp_cia_aberta_{ano}.zip",
                    status=status,
                    etag=getattr(assinatura, "etag", None),
                    last_modified=getattr(assinatura, "last_modified", None),
                    tamanho_bytes=getattr(assinatura, "tamanho_bytes", None),
                    mensagem_erro=mensagem,
                )
        except Exception as erro:
            self._logger.error("Falha ao registrar execucao do ano %s: %s", ano, erro)


def data_de_entrega(
    entregas: dict[tuple[str, date, int], date], cnpj: str, referencia: date, versao: int
) -> date | None:
    """DT_RECEB da versao usada; sem ela, a entrega mais tardia da mesma
    referencia - na duvida o dado fica publico depois, nunca antes."""
    exata = entregas.get((cnpj, referencia, versao))
    if exata:
        return exata
    candidatas = [d for (c, r, _), d in entregas.items() if c == cnpj and r == referencia]
    return max(candidatas) if candidatas else None


def _empresa_minima(cnpj: str, selecionados: dict[str, Ticker]) -> Empresa:
    denominacao = next(
        (t.simbolo for t in selecionados.values() if t.cnpj == cnpj), cnpj
    )
    return Empresa(cnpj=cnpj, denominacao=denominacao)
