from __future__ import annotations

from dataclasses import dataclass, field, replace
from logging import Logger

from app.aplicacao.carregar_fundamentos import data_de_entrega
from app.dominio.identidade import resolver_tickers
from app.dominio.modelo import STATUS_PULADO, STATUS_SUCESSO, DocumentoContabil, Empresa
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
        self, anos: list[int], simbolos_pedidos: list[str] | None = None, forcar: bool = False
    ) -> ResultadoTtm:
        resultado = ResultadoTtm()
        self._forcar = forcar
        simbolos = self._resolver_universo(simbolos_pedidos)
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
        dfps = {documento.cnpj: documento for documento in self._fonte.documentos(ano - 1, cnpjs)}
        itr_atual = self._mais_recentes(self._fonte.documentos_itr(ano, cnpjs))
        itr_anterior = self._por_mes_dia(self._fonte.documentos_itr(ano - 1, cnpjs))
        capitais = self._fonte.composicoes_de_capital(ano - 1, cnpjs)
        empresas = self._fonte.empresas(ano) or self._fonte.empresas(ano - 1)
        entregas = self._fonte.datas_de_entrega("ITR", ano, cnpjs)

        documentos_ttm: dict[str, DocumentoContabil] = {}
        entregas_ttm: dict = {}
        for cnpj, atual in itr_atual.items():
            anterior = itr_anterior.get((cnpj, atual.dt_fim_exerc.month, atual.dt_fim_exerc.day))
            anual = dfps.get(cnpj)
            if anual is None or anterior is None:
                self._logger.warning("TTM %s sem trio completo para o CNPJ %s", ano, cnpj)
                continue
            documentos_ttm[cnpj] = self._ttm.montar(anual, atual, anterior)
            # O TTM fica publico junto com o ITR mais recente que o compoe.
            entregas_ttm[cnpj] = data_de_entrega(entregas, cnpj, atual.dt_refer, atual.versao)

        indicadores = []
        with self._uow.transacao() as db:
            self._cadastro.salvar_empresas(
                db, [empresas.get(cnpj) or Empresa(cnpj=cnpj, denominacao=cnpj) for cnpj in cnpjs]
            )
            self._cadastro.salvar_tickers(db, list(selecionados.values()))
            for simbolo, ticker in selecionados.items():
                documento = documentos_ttm.get(ticker.cnpj)
                if documento is None:
                    continue
                for linhas in documento.linhas.values():
                    self._fato.salvar_linhas(
                        db, documento.cnpj, documento.tipo_doc, documento.grupo,
                        documento.versao, documento.dt_refer, linhas,
                    )
                indicadores.append(
                    replace(
                        self._montador.montar(simbolo, documento, capitais.get(ticker.cnpj)),
                        data_entrega=entregas_ttm.get(ticker.cnpj),
                    )
                )
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

    def _resolver_universo(self, simbolos_pedidos: list[str] | None) -> list[str]:
        if simbolos_pedidos:
            return sorted({s.strip().upper() for s in simbolos_pedidos if s.strip()})
        with self._uow.transacao() as db:
            return self._universo.listar_simbolos_monitorados(db)

    @staticmethod
    def _mais_recentes(documentos) -> dict[str, DocumentoContabil]:
        saida: dict[str, DocumentoContabil] = {}
        for documento in documentos:
            anterior = saida.get(documento.cnpj)
            if anterior is None or documento.dt_fim_exerc > anterior.dt_fim_exerc:
                saida[documento.cnpj] = documento
        return saida

    @staticmethod
    def _por_mes_dia(documentos) -> dict[tuple[str, int, int], DocumentoContabil]:
        return {
            (doc.cnpj, doc.dt_fim_exerc.month, doc.dt_fim_exerc.day): doc
            for doc in documentos
        }
