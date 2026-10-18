from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date

from app.adaptadores.cvm.cliente_http import Assinatura
from app.aplicacao.carregar_series_historicas import (
    FONTE_COTAHIST,
    FONTE_COTAHIST_OPCOES,
    CarregarSeriesHistoricas,
)
from app.dominio.modelo import STATUS_ERRO


class UowFake:
    @contextmanager
    def transacao(self):
        yield object()


class FonteFake:
    def __init__(self, assinatura, falhar_opcoes=False):
        self._assinatura = assinatura
        self._falhar_opcoes = falhar_opcoes
        self.anos_candles = []
        self.anos_opcoes = []

    def assinatura(self, ano):
        return self._assinatura

    def candles(self, ano, simbolos, usar_cache=False):
        self.anos_candles.append(ano)
        return []

    def opcoes(self, ano, usar_cache=False):
        self.anos_opcoes.append(ano)
        if self._falhar_opcoes:
            raise OSError("arquivo de opções indisponível")
        return []


class ExecucaoFake:
    def __init__(self, etags=None):
        self.etags = etags or {}
        self.registros = []

    def etag_da_ultima_execucao(self, db, fonte, competencia, arquivo):
        return self.etags.get((fonte, competencia))

    def registrar(self, db, fonte, competencia, arquivo, status, **kwargs):
        self.registros.append((fonte, competencia, status, kwargs))


class RepositorioSeriesFake:
    def salvar_candles_b3(self, db, candles):
        return 2

    def atualizar_isin_dos_tickers(self, db):
        return 0


class RepositorioOpcaoFake:
    def __init__(self, recompor=False):
        self.recompor = recompor
        self.salvos = []
        self.invalidacoes = []

    def precisa_recomposicao(self, db, desde):
        return self.recompor

    def salvar_opcoes_b3(self, db, opcoes):
        self.salvos.append(list(opcoes))
        return len(opcoes)

    def invalidar_legado_residual(self, db, ano):
        self.invalidacoes.append(ano)
        return 0


def montar(fonte, execucao, repositorio_opcao):
    return CarregarSeriesHistoricas(
        fonte=fonte,
        unidade_de_trabalho=UowFake(),
        repositorio_series=RepositorioSeriesFake(),
        repositorio_execucao=execucao,
        logger=logging.getLogger("teste-cotahist-opcoes"),
        fonte_opcoes=fonte,
        repositorio_opcao=repositorio_opcao,
    )


def test_etag_dos_candles_nao_impede_conferir_etapa_de_opcoes():
    ano = date.today().year
    fonte = FonteFake(Assinatura("etag-atual", None, 100))
    execucao = ExecucaoFake({(FONTE_COTAHIST, str(ano)): "etag-atual"})
    opcoes = RepositorioOpcaoFake(recompor=False)

    resultado = montar(fonte, execucao, opcoes).executar([ano])

    assert resultado.anos_pulados == [ano]
    assert fonte.anos_candles == []
    assert fonte.anos_opcoes == [ano]
    assert opcoes.salvos == [[]]
    assert any(fonte_nome == FONTE_COTAHIST_OPCOES and status == "SUCESSO"
               for fonte_nome, _, status, _ in execucao.registros)


def test_tabela_vazia_recompoe_janela_sem_comando_manual():
    ano = date.today().year
    fonte = FonteFake(Assinatura("etag-atual", None, 100))
    execucao = ExecucaoFake({(FONTE_COTAHIST, str(ano)): "etag-atual"})
    opcoes = RepositorioOpcaoFake(recompor=True)

    montar(fonte, execucao, opcoes).executar([ano])

    janela = list(range(ano - 5, ano + 1))
    assert fonte.anos_opcoes == janela
    assert opcoes.invalidacoes == janela


def test_falha_de_opcoes_nao_mascara_candles_carregados():
    ano = date.today().year
    fonte = FonteFake(Assinatura("etag-novo", None, 100), falhar_opcoes=True)
    execucao = ExecucaoFake()
    opcoes = RepositorioOpcaoFake(recompor=False)

    resultado = montar(fonte, execucao, opcoes).executar([ano])

    assert resultado.anos_processados == [ano]
    assert resultado.candles_gravados == 2
    assert len(resultado.erros_opcoes) == 1
    assert any(fonte_nome == FONTE_COTAHIST_OPCOES and status == STATUS_ERRO
               for fonte_nome, _, status, _ in execucao.registros)
