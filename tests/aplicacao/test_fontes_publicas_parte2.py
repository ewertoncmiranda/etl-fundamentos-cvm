"""Parte 2 da FONTES-ETL-8: CVM_CADASTRO, IFDATA, datas ex (EVENTOS) e mercados do COTAHIST.

Sem rede e sem banco.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

import pytest

from app.adaptadores.b3.leitor_cotahist import NegocioMercadoB3
from app.adaptadores.bcb.ifdata import IndicadoresIfData
from app.adaptadores.cvm.cadastro import CadastroCvm
from app.adaptadores.cvm.cliente_http import Assinatura
from app.aplicacao.carregar_fontes_publicas import (
    CarregarCadastro,
    CarregarIfData,
    trimestres_recentes,
)
from app.aplicacao.carregar_series_historicas import (
    FONTE_COTAHIST_MERCADOS,
    CarregarSeriesHistoricas,
)
from app.aplicacao.datas_ex_b3 import (
    CarregarDatasEx,
    EventosEDatasEx,
    LinhaMarcada,
    montar_datas_ex,
    tipo_da_marca,
)
from app.aplicacao.executar_carga import CATALOGO_ETAPAS, ETAPAS_ROTINA
from app.aplicacao.resumo_etapa import resumir_etapa
from app.excecoes.excecoes import FonteIndisponivel
from tests.aplicacao.test_fontes_publicas import ExecucaoFake, UowFake, montar

LOG = logging.getLogger("teste2")
HOJE = date(2026, 10, 20)
BANCO = "60872504000123"
OUTRO_BANCO = "11111111000111"


def test_catalogo_e_rotina_incluem_cadastro_e_ifdata():
    for etapa in ("CVM_CADASTRO", "IFDATA"):
        assert etapa in CATALOGO_ETAPAS and etapa in ETAPAS_ROTINA


# ---------------------------------------------------------------- cadastro

def _cad(cnpj=BANCO, auditor="KPMG", cnpj_aud="57755217000129"):
    return CadastroCvm(cnpj, "Ativo", date(2020, 1, 1), "Bancos", auditor, cnpj_aud)


class CadastroFonteFake:
    nome_arquivo = "cad_cia_aberta.csv"

    def __init__(self, dados, etag="c1", erro=None):
        self.dados, self.etag, self.erro, self.downloads = dados, etag, erro, 0

    def assinatura(self):
        if self.erro:
            raise self.erro
        return Assinatura(self.etag, None, 1)

    def cadastro(self):
        self.downloads += 1
        return dict(self.dados)


class RepoCadastro:
    def __init__(self):
        self.tabela = {}
        self.snapshot = date(2026, 10, 13)

    def cadastros_gravados(self, _db):
        return dict(self.tabela), (self.snapshot if self.tabela else None)

    def salvar_cadastros(self, _db, cadastros):
        for c in cadastros:
            self.tabela[c.cnpj] = c
        return len(cadastros)


def _caso_cadastro(fonte):
    repo, execucao = RepoCadastro(), ExecucaoFake()
    return CarregarCadastro(fonte, UowFake(), repo, execucao, LOG, hoje=lambda: HOJE), repo


def test_cadastro_sucesso_depois_sem_mudanca_e_forcar_idempotente():
    fonte = CadastroFonteFake({BANCO: _cad(), OUTRO_BANCO: _cad(OUTRO_BANCO)})
    caso, repo = _caso_cadastro(fonte)
    assert resumir_etapa("CVM_CADASTRO", caso.executar()).status == "SUCESSO"
    assert resumir_etapa("CVM_CADASTRO", caso.executar()).status == "SEM_MUDANCA"
    assert fonte.downloads == 1
    caso.executar(forcar=True)
    assert len(repo.tabela) == 2


def test_cadastro_troca_de_auditor_vira_alerta():
    fonte = CadastroFonteFake({BANCO: _cad()})
    caso, repo = _caso_cadastro(fonte)
    caso.executar()
    fonte.dados = {BANCO: _cad(auditor="DELOITTE", cnpj_aud="49928567000111")}
    fonte.etag = "c2"
    r = caso.executar()
    resumo = resumir_etapa("CVM_CADASTRO", r)
    assert resumo.status == "ALERTA" and r.trocas_auditor == [BANCO]
    assert "troca de auditor" in resumo.alertas[0]
    # na carga seguinte o retrato ja e o novo: sem alerta
    fonte.etag = "c3"
    assert resumir_etapa("CVM_CADASTRO", caso.executar()).status == "SUCESSO"


def test_cadastro_falha_em_erro_de_fonte():
    caso, _ = _caso_cadastro(CadastroFonteFake({}, erro=FonteIndisponivel("503")))
    with pytest.raises(FonteIndisponivel) as exc:
        caso.executar()
    assert resumir_etapa("CVM_CADASTRO", None, exc.value).status == "FALHA"


# ---------------------------------------------------------------- IFDATA

def _ind(cnpj, **kw):
    base = dict(cnpj=cnpj, data_base=date(2026, 6, 30), cod_inst="1", tipo_instituicao=1,
                basileia=Decimal("0.17"), roe=Decimal("0.2"), ativo_total=Decimal("1000"))
    base.update(kw)
    return IndicadoresIfData(**base)


class IfDataFake:
    def __init__(self, por_trimestre=None, erro=None):
        self.por_trimestre = por_trimestre or {}
        self.erro, self.chamadas = erro, []

    def ler(self, ano_mes, tipo_instituicao=1):
        self.chamadas.append(ano_mes)
        if self.erro:
            raise self.erro
        return self.por_trimestre.get(ano_mes, {})


class RepoIf:
    def __init__(self, tickers=None):
        self.tickers = tickers if tickers is not None else {BANCO: "BBDC3"}
        self.linhas = {}

    def tickers_por_cnpj(self, _db):
        return self.tickers

    def salvar_indicadores_banco(self, _db, indicadores):
        for i, cnpj, simbolo in indicadores:
            self.linhas[(cnpj, i.data_base)] = (i, simbolo)
        return len(indicadores)


def _caso_if(fonte, repo=None):
    repo = repo or RepoIf()
    return CarregarIfData(fonte, UowFake(), repo, ExecucaoFake(), LOG, hoje=lambda: HOJE), repo


def test_trimestres_recentes():
    assert trimestres_recentes(HOJE, 3) == [202609, 202606, 202603]


def test_ifdata_liga_ticker_pelo_cnpj_e_raiz_so_com_cnpj_unico():
    dados = {
        (BANCO, date(2026, 6, 30)): _ind(BANCO),
        ("60872504", date(2026, 6, 30)): _ind("60872504", cod_inst="2"),   # raiz do mesmo CNPJ
        ("99999999", date(2026, 6, 30)): _ind("99999999", cod_inst="3"),   # raiz sem ticker
        (OUTRO_BANCO, date(2026, 6, 30)): _ind(OUTRO_BANCO, cod_inst="4"),  # sem ticker
    }
    fonte = IfDataFake({202606: dados, 202603: {(BANCO, date(2026, 3, 31)): _ind(
        BANCO, data_base=date(2026, 3, 31))}, 202512: {}, 202509: {}})
    caso, repo = _caso_if(fonte)
    r = caso.executar()
    assert resumir_etapa("IFDATA", r).status in {"SUCESSO", "FALHA"}
    assert repo.linhas[(BANCO, date(2026, 6, 30))][1] == "BBDC3"
    assert repo.linhas[(OUTRO_BANCO, date(2026, 6, 30))][1] is None
    assert r.sem_vinculo == 1


def test_ifdata_segunda_execucao_nao_chama_a_fonte_e_e_sem_mudanca():
    fonte = IfDataFake({
        ano_mes: {(BANCO, date(2026, 6, 30)): _ind(BANCO)}
        for ano_mes in (202609, 202606, 202603, 202512)
    })
    caso, _ = _caso_if(fonte)
    # o trimestre 202609 e recente e vazio de verdade? aqui tem dados: tudo grava
    assert resumir_etapa("IFDATA", caso.executar()).status == "SUCESSO"
    antes = len(fonte.chamadas)
    r2 = caso.executar()
    assert resumir_etapa("IFDATA", r2).status == "SEM_MUDANCA"
    assert len(fonte.chamadas) == antes


def test_ifdata_alerta_com_valor_fora_da_faixa():
    ruim = _ind(BANCO, roe=Decimal("9999999"))
    fonte = IfDataFake({ano_mes: {(BANCO, date(2026, 6, 30)): ruim}
                        for ano_mes in (202609, 202606, 202603, 202512)})
    caso, repo = _caso_if(fonte)
    assert resumir_etapa("IFDATA", caso.executar()).status == "ALERTA"
    assert not repo.linhas


def test_ifdata_erro_de_fonte_em_trimestre_antigo_e_falha_mas_recente_aguarda():
    fonte = IfDataFake(erro=FonteIndisponivel("HTTP 500"))
    caso, _ = _caso_if(fonte)
    r = caso.executar()
    assert resumir_etapa("IFDATA", r).status == "FALHA"
    # 202609 (20 dias) e 202606 (112 dias) ainda estao na janela de publicacao;
    # 202603 e 202512 ja deveriam estar publicados
    assert r.aguardando == ["202609", "202606"] and len(r.erros) == 2


def test_ifdata_so_trimestre_recente_indisponivel_e_sem_mudanca():
    fonte = IfDataFake(erro=FonteIndisponivel("HTTP 500"))
    caso, _ = _caso_if(fonte)
    caso._execucao.registros.extend(
        {"chave": ("IFDATA", str(a), f"ifdata_{a}"), "status": "SUCESSO", "etag": f"ifdata:{a}"}
        for a in (202606, 202603, 202512)
    )
    r = caso.executar()
    assert resumir_etapa("IFDATA", r).status == "SEM_MUDANCA"


# ---------------------------------------------------------------- datas ex

def _linha(simbolo, dia, marca, abertura="10", fech="10", ant_dia=None, ant_fech="11"):
    return LinhaMarcada(simbolo, dia, marca, Decimal(abertura), Decimal(fech), ant_dia,
                        Decimal(ant_fech) if ant_dia else None)


def test_sequencia_de_8_pregoes_com_a_mesma_marca_vira_um_so_evento_no_primeiro_dia():
    dias = [date(2026, 8, 24), date(2026, 8, 25), date(2026, 8, 26), date(2026, 8, 27),
            date(2026, 8, 28), date(2026, 8, 31), date(2026, 9, 1), date(2026, 9, 2)]
    linhas = [_linha("PETR4", dias[0], "EDJ", "42.6", "42.7", date(2026, 8, 21), "44.3")]
    linhas += [_linha("PETR4", d, "EDJ", "42.7", "42.8", dias[i], "42.7")
               for i, d in enumerate(dias[1:])]
    eventos = montar_datas_ex(linhas)
    assert len(eventos) == 1
    e = eventos[0]
    assert (e.data_ex, e.marca, e.tipo) == (date(2026, 8, 24), "EDJ", "DIVIDENDO")
    assert e.fechamento_anterior == Decimal("44.3") and e.abertura_ex == Decimal("42.6")
    assert e.ajuste_implicito == Decimal("1.7")
    assert e.ajuste_percentual.quantize(Decimal("0.0001")) == Decimal("3.8375")


def test_mesma_marca_com_intervalo_maior_que_5_dias_abre_novo_evento():
    linhas = [
        _linha("VALE3", date(2026, 3, 2), "EJ", ant_dia=date(2026, 2, 27)),
        _linha("VALE3", date(2026, 3, 7), "EJ", ant_dia=date(2026, 3, 6)),   # 5 dias: continua
        _linha("VALE3", date(2026, 3, 13), "EJ", ant_dia=date(2026, 3, 12)),  # 6 dias: novo
    ]
    assert [e.data_ex for e in montar_datas_ex(linhas)] == [date(2026, 3, 2), date(2026, 3, 13)]


def test_marcas_diferentes_intercaladas_sao_eventos_separados_e_simbolos_nao_se_misturam():
    linhas = [
        _linha("ITUB4", date(2026, 5, 4), "EJ", ant_dia=date(2026, 5, 1)),
        _linha("ITUB4", date(2026, 5, 5), "ED", ant_dia=date(2026, 5, 4)),
        _linha("ITUB4", date(2026, 5, 6), "EJ", ant_dia=date(2026, 5, 5)),
        _linha("BBAS3", date(2026, 5, 5), "EJ", ant_dia=date(2026, 5, 4)),
    ]
    eventos = montar_datas_ex(linhas)
    assert [(e.simbolo, e.data_ex, e.marca) for e in eventos] == [
        ("BBAS3", date(2026, 5, 5), "EJ"),
        ("ITUB4", date(2026, 5, 4), "EJ"),
        ("ITUB4", date(2026, 5, 5), "ED"),
        ("ITUB4", date(2026, 5, 6), "EJ"),
    ]


def test_tipo_da_marca_igual_ao_gestor():
    assert [tipo_da_marca(m) for m in ("ED", "EJ", "ER", "EB", "EG", "ES", "EX", "EDJ", "ERJ",
                                       "E", "", None, "EZ")] == [
        "DIVIDENDO", "JCP", "RENDIMENTO", "BONIFICACAO", "GRUPAMENTO", "SUBSCRICAO",
        "DESDOBRAMENTO", "DIVIDENDO", "RENDIMENTO", "OUTRO", "OUTRO", "OUTRO", "OUTRO"]


class RepoDatasEx:
    def __init__(self, linhas):
        self.linhas, self.tabela = linhas, {}

    def contar_datas_ex(self, _db):
        return len(self.tabela)

    def linhas_com_marca_ex(self, _db, desde):
        self.desde = desde
        return self.linhas

    def salvar_datas_ex(self, _db, eventos, versao):
        for e in eventos:
            self.tabela[(e.simbolo, e.data_ex, e.marca)] = e
        return len(eventos)


def test_carregar_datas_ex_idempotente_e_alerta_com_marca_invalida():
    ok = _linha("PETR4", date(2026, 8, 24), "EDJ", ant_dia=date(2026, 8, 21))
    ruim = _linha("PETR4", date(2026, 9, 24), "EXXXX", ant_dia=date(2026, 9, 21))
    repo = RepoDatasEx([ok, ruim])
    caso = CarregarDatasEx(UowFake(), repo, ExecucaoFake(), LOG)
    r = caso.executar([2026])
    assert r.gravados == 1 and len(r.rejeicoes) == 1
    assert repo.desde == date(2016, 1, 1)  # tabela vazia na primeira vez
    caso.executar([2026])
    assert len(repo.tabela) == 1
    assert repo.desde == date(2026, 1, 1)


class EventosFake:
    def executar(self, anos=None):
        from app.aplicacao.inferir_eventos_corporativos import ResultadoEventos
        return ResultadoEventos(candidatos=3, gravados=1)


def test_eventos_com_datas_ex_status():
    ok = _linha("PETR4", date(2026, 8, 24), "EDJ", ant_dia=date(2026, 8, 21))
    caso = CarregarDatasEx(UowFake(), RepoDatasEx([ok]), ExecucaoFake(), LOG)
    r = EventosEDatasEx(EventosFake(), caso, LOG).executar([2026])
    assert resumir_etapa("EVENTOS", r).status == "SUCESSO" and r.datas_ex_gravadas == 1

    ruim = _linha("PETR4", date(2026, 9, 24), "EXXXX", ant_dia=date(2026, 9, 21))
    caso2 = CarregarDatasEx(UowFake(), RepoDatasEx([ruim]), ExecucaoFake(), LOG)
    r2 = EventosEDatasEx(EventosFake(), caso2, LOG).executar([2026])
    assert resumir_etapa("EVENTOS", r2).status == "ALERTA"

    class Quebra(RepoDatasEx):
        def linhas_com_marca_ex(self, _db, desde):
            raise OSError("banco fora")

    caso3 = CarregarDatasEx(UowFake(), Quebra([]), ExecucaoFake(), LOG)
    r3 = EventosEDatasEx(EventosFake(), caso3, LOG).executar([2026])
    assert resumir_etapa("EVENTOS", r3).status == "FALHA" and r3.gravados == 1


# ---------------------------------------------------------------- mercados do COTAHIST

def _neg(simbolo="PETRA10", mercado="012", dia=date(2026, 1, 5), **kw):
    base = dict(
        simbolo=simbolo, simbolo_base="PETR4", mercado=mercado, data_pregao=dia, isin="BRPETR",
        prazo_termo=None, indice_correcao=None, numero_distribuicao=None,
        preco_exercicio=None, preco_exercicio_pontos=None, abertura=Decimal("1"),
        maxima=Decimal("2"), minima=Decimal("1"), fechamento=Decimal("2"),
        preco_medio=None, melhor_oferta_compra=None, melhor_oferta_venda=None,
        numero_negocios=3, volume=10, volume_financeiro=Decimal("20"), fator_cotacao=1,
    )
    base.update(kw)
    return NegocioMercadoB3(**base)


class FonteMercados:
    def __init__(self, etag="m1", negocios=None):
        self.etag, self.negocios, self.anos = etag, negocios or [_neg()], []

    def assinatura(self, ano):
        return Assinatura(self.etag, None, 1)

    def candles(self, ano, simbolos, usar_cache=False):
        return []

    def mercados(self, ano, usar_cache=False):
        self.anos.append(ano)
        return list(self.negocios)


class RepoSeries:
    def salvar_candles_b3(self, db, candles):
        return 1

    def atualizar_isin_dos_tickers(self, db):
        return 0


class RepoMercados:
    def __init__(self):
        self.tabela = {}

    def contar_negociacoes_mercado(self, _db):
        return len(self.tabela)

    def salvar_negociacoes_mercado(self, _db, negocios):
        for n in negocios:
            self.tabela[(n.simbolo, n.data_pregao, n.mercado)] = n
        return len(negocios)


def _cotahist(fonte):
    repo, execucao = RepoMercados(), ExecucaoFake()
    caso = CarregarSeriesHistoricas(
        fonte=fonte, unidade_de_trabalho=UowFake(), repositorio_series=RepoSeries(),
        repositorio_execucao=execucao, logger=LOG,
        fonte_mercados=fonte, repositorio_mercados=repo,
    )
    return caso, repo, execucao


def test_mercados_recompoe_desde_2016_com_tabela_vazia_e_depois_fica_sem_mudanca():
    ano = date.today().year
    fonte = FonteMercados()
    caso, repo, execucao = _cotahist(fonte)
    r = caso.executar([ano])
    assert r.mercados_recompostos and fonte.anos == list(range(2016, ano + 1))
    assert resumir_etapa("COTAHIST", r).status == "SUCESSO"
    assert any(k[0] == FONTE_COTAHIST_MERCADOS for k in
               (rg["chave"] for rg in execucao.registros))
    fonte.anos.clear()
    # o ExecucaoFake de tests.aplicacao guarda por chave: a trilha propria sera respeitada
    r2 = caso.executar([ano])
    assert not r2.mercados_recompostos and fonte.anos == []
    assert resumir_etapa("COTAHIST", r2).status == "SEM_MUDANCA"


def test_mercados_alerta_com_negocio_descartado_e_falha_em_erro():
    ano = date.today().year
    fonte = FonteMercados(negocios=[_neg(), _neg("SIMBOLO_MUITO_LONGO_X", "012")])
    caso, repo, _ = _cotahist(fonte)
    r = caso.executar([ano])
    assert resumir_etapa("COTAHIST", r).status == "ALERTA" and len(repo.tabela) == 1

    class Quebra(FonteMercados):
        def mercados(self, ano, usar_cache=False):
            raise OSError("zip corrompido")

    caso2, _, _ = _cotahist(Quebra())
    r2 = caso2.executar([ano])
    resumo = resumir_etapa("COTAHIST", r2)
    assert resumo.status == "FALHA" and "mercados" in resumo.erros[0]
