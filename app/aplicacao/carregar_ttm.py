from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import date
from logging import Logger

from app.aplicacao.carregar_fundamentos import data_de_entrega
from app.dominio.identidade import resolver_tickers
from app.dominio.modelo import (
    GRUPO_CONSOLIDADO,
    STATUS_PULADO,
    STATUS_SUCESSO,
    DocumentoContabil,
    Empresa,
)
from app.dominio.montador_indicadores import MontadorDeIndicadores
from app.dominio.ttm import MontadorTtm
from app.portas.fonte_documentos import FonteDeDocumentos
from app.portas.repositorios import (
    RepositorioCadastro,
    RepositorioExecucao,
    RepositorioFatoContabil,
    RepositorioIndicador,
    RepositorioUniverso,
)

FONTE_TTM = "CVM_TTM"


@dataclass
class ResultadoTtm:
    anos_processados: list[int] = field(default_factory=list)
    anos_pulados: list[int] = field(default_factory=list)
    indicadores_gravados: int = 0


class CarregarTtm:
    def __init__(
        self,
        fonte: FonteDeDocumentos,
        unidade_de_trabalho,
        repositorio_universo: RepositorioUniverso,
        repositorio_cadastro: RepositorioCadastro,
        repositorio_fato: RepositorioFatoContabil,
        repositorio_indicador: RepositorioIndicador,
        repositorio_execucao: RepositorioExecucao,
        montador_ttm: MontadorTtm,
        montador_indicadores: MontadorDeIndicadores,
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
        self._ttm = montador_ttm
        self._montador = montador_indicadores
        self._logger = logger
        self._identidade = repositorio_identidade
        self._forcar = False

    def executar(
        self,
        anos: list[int],
        simbolos_pedidos: list[str] | None = None,
        forcar: bool = False,
        universo_backtest: bool = False,
    ) -> ResultadoTtm:
        """universo_backtest: TTM de todo papel liquido de algum ano do
        COTAHIST, nao so dos monitorados - o mesmo universo da DFP e dos
        proventos, para a serie historica (plano LAC, L3)."""
        resultado = ResultadoTtm()
        self._forcar = forcar
        simbolos = self._resolver_universo(simbolos_pedidos, universo_backtest)
        for ano in sorted(anos):
            self._processar_ano(ano, simbolos, resultado)
        if resultado.indicadores_gravados:
            with self._uow.transacao() as db:
                for linha in self._indicador.conferir_acoes(db, simbolos):
                    self._logger.warning("Quantidade de acoes corrigida: %s", linha)
        return resultado

    def _processar_ano(self, ano: int, simbolos: list[str], resultado: ResultadoTtm) -> None:
        arquivo = f"itr_cia_aberta_{ano}.zip"
        assinatura = self._fonte.assinatura("ITR", ano)
        with self._uow.transacao() as db:
            etag = self._execucao.etag_da_ultima_execucao(db, FONTE_TTM, str(ano), arquivo)
        if not self._forcar and assinatura.inalterado_em_relacao_a(etag):
            with self._uow.transacao() as db:
                self._execucao.registrar(
                    db, FONTE_TTM, str(ano), arquivo, STATUS_PULADO, etag=assinatura.etag
                )
            resultado.anos_pulados.append(ano)
            return

        tickers = self._fonte.tickers(ano)
        if not tickers:
            tickers = self._fonte.tickers(ano - 1)
        identidades = {}
        if self._identidade is not None:
            with self._uow.transacao() as db:
                identidades = self._identidade.identidades(db)
        selecionados, ausentes = resolver_tickers(simbolos, tickers, identidades)
        if ausentes:
            self._logger.warning("TTM %s sem CNPJ para: %s", ano, ", ".join(ausentes))
        cnpjs = {ticker.cnpj for ticker in selecionados.values()}
        itrs_atuais = list(self._fonte.documentos_itr(ano, cnpjs))
        # DFP dos dois anos: quem fecha o exercicio em marco (RAIZ4) usa a do
        # proprio ano; o escolher_trios_por_corte casa pela data.
        dfps = [
            *self._fonte.documentos(ano - 1, cnpjs, todos_os_grupos=True),
            *self._fonte.documentos(ano, cnpjs, todos_os_grupos=True),
        ]
        trios = escolher_trios_por_corte(
            dfps, itrs_atuais, self._fonte.documentos_itr(ano - 1, cnpjs)
        )
        capitais = self._fonte.composicoes_de_capital(ano - 1, cnpjs)
        empresas = self._fonte.empresas(ano) or self._fonte.empresas(ano - 1)
        entregas = self._fonte.datas_de_entrega("ITR", ano, cnpjs)

        # Todos os trimestres do ano, nao so o mais recente: serie historica
        # de TTM (plano LAC, L3). Cada um com a entrega do ITR que o fecha.
        documentos_ttm: dict[str, list[DocumentoContabil]] = {}
        entregas_ttm: dict[tuple[str, date], date | None] = {}
        com_trio = {cnpj for cnpj, _ in trios}
        for cnpj in sorted({itr.cnpj for itr in itrs_atuais} - com_trio):
            self._logger.warning("TTM %s sem trio completo para o CNPJ %s", ano, cnpj)
        for (cnpj, corte), (anual, atual, anterior) in sorted(trios.items()):
            documentos_ttm.setdefault(cnpj, []).append(self._ttm.montar(anual, atual, anterior))
            # O TTM fica publico junto com o ITR mais recente que o compoe.
            entregas_ttm[(cnpj, corte)] = data_de_entrega(
                entregas, cnpj, atual.dt_refer, atual.versao
            )

        indicadores = []
        with self._uow.transacao() as db:
            self._cadastro.salvar_empresas(
                db, [empresas.get(cnpj) or Empresa(cnpj=cnpj, denominacao=cnpj) for cnpj in cnpjs]
            )
            self._cadastro.salvar_tickers(db, list(selecionados.values()))
            gravados: set[str] = set()
            for simbolo, ticker in selecionados.items():
                for documento in documentos_ttm.get(ticker.cnpj, []):
                    # ON e PN da mesma companhia: os fatos sao os mesmos.
                    if ticker.cnpj not in gravados:
                        for linhas in documento.linhas.values():
                            self._fato.salvar_linhas(
                                db, documento.cnpj, documento.tipo_doc, documento.grupo,
                                documento.versao, documento.dt_refer, linhas,
                            )
                    indicadores.append(
                        replace(
                            self._montador.montar(simbolo, documento, capitais.get(ticker.cnpj)),
                            data_entrega=entregas_ttm.get((ticker.cnpj, documento.dt_fim_exerc)),
                        )
                    )
                gravados.add(ticker.cnpj)
            if indicadores:
                self._indicador.salvar(db, indicadores)
            self._execucao.registrar(
                db, FONTE_TTM, str(ano), arquivo, STATUS_SUCESSO,
                etag=assinatura.etag,
                last_modified=assinatura.last_modified,
                tamanho_bytes=assinatura.tamanho_bytes,
                linhas_carregadas=len(indicadores),
            )
        resultado.anos_processados.append(ano)
        resultado.indicadores_gravados += len(indicadores)

    def _resolver_universo(
        self, simbolos_pedidos: list[str] | None, universo_backtest: bool = False
    ) -> list[str]:
        if simbolos_pedidos:
            return sorted({s.strip().upper() for s in simbolos_pedidos if s.strip()})
        with self._uow.transacao() as db:
            if universo_backtest:
                return self._universo.listar_simbolos_liquidos(db)
            return self._universo.listar_simbolos_monitorados(db)



Trio = tuple[DocumentoContabil, DocumentoContabil, DocumentoContabil]


def escolher_trios_por_corte(
    dfps: Iterable[DocumentoContabil],
    itrs_atuais: Iterable[DocumentoContabil],
    itrs_anteriores: Iterable[DocumentoContabil],
) -> dict[tuple[str, date], Trio]:
    """(cnpj, corte) -> (DFP, ITR atual, ITR anterior), todos do mesmo grupo.

    Um trio por trimestre (marco, junho e setembro de cada ano), para a serie
    historica de TTM. A DFP do trio e o exercicio encerrado entre os dois
    ITRs: dezembro do ano anterior no ano civil, marco do proprio ano para
    quem fecha em marco (RAIZ4) - por isso `dfps` traz os dois anos.

    Misturar grupos soma perimetros diferentes e, pior, descarta em silencio
    as contas cujo rotulo muda ("Lucro/Prejuizo Consolidado do Periodo" x
    "Lucro/Prejuizo do Periodo"). No mesmo corte, vale o consolidado.
    """
    dfps_por_grupo: dict[tuple[str, str], list[DocumentoContabil]] = {}
    for d in dfps:
        dfps_por_grupo.setdefault((d.cnpj, d.grupo), []).append(d)
    anteriores = {
        (d.cnpj, d.grupo, d.dt_fim_exerc.month, d.dt_fim_exerc.day): d
        for d in itrs_anteriores
    }
    saida: dict[tuple[str, date], Trio] = {}
    for atual in itrs_atuais:
        anterior = anteriores.get(
            (atual.cnpj, atual.grupo, atual.dt_fim_exerc.month, atual.dt_fim_exerc.day)
        )
        if anterior is None:
            continue
        anual = max(
            (
                d for d in dfps_por_grupo.get((atual.cnpj, atual.grupo), [])
                if anterior.dt_fim_exerc < d.dt_fim_exerc < atual.dt_fim_exerc
            ),
            key=lambda d: d.dt_fim_exerc,
            default=None,
        )
        if anual is None:
            continue
        chave = (atual.cnpj, atual.dt_fim_exerc)
        escolhido = saida.get(chave)
        if escolhido is None or _preferencia(atual) > _preferencia(escolhido[1]):
            saida[chave] = (anual, atual, anterior)
    return saida


def escolher_trios(
    dfps: Iterable[DocumentoContabil],
    itrs_atuais: Iterable[DocumentoContabil],
    itrs_anteriores: Iterable[DocumentoContabil],
) -> dict[str, Trio]:
    """cnpj -> o trio do corte mais recente (no empate, o consolidado)."""
    saida: dict[str, Trio] = {}
    for (cnpj, _), trio in escolher_trios_por_corte(dfps, itrs_atuais, itrs_anteriores).items():
        escolhido = saida.get(cnpj)
        if escolhido is None or _preferencia(trio[1]) > _preferencia(escolhido[1]):
            saida[cnpj] = trio
    return saida


def _preferencia(itr: DocumentoContabil) -> tuple[date, bool]:
    return itr.dt_fim_exerc, itr.grupo == GRUPO_CONSOLIDADO
