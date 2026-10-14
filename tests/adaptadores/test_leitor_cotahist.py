from decimal import Decimal

import pytest

from app.adaptadores.b3.leitor_cotahist import LeitorCotahist
from app.dominio.serie_historica import resumir_validacao_opcoes


def _linha_cotahist(simbolo: str = "PETR4", mercado: str = "010", nome_resumido: str = "") -> str:
    linha = [" "] * 245

    def preencher(inicio: int, fim: int, valor: str) -> None:
        largura = fim - inicio
        linha[inicio:fim] = list(valor.rjust(largura, "0")[:largura])

    preencher(0, 2, "01")
    preencher(2, 10, "20260925")
    preencher(10, 12, "02")
    linha[12:24] = list(simbolo.ljust(12))
    preencher(24, 27, mercado)
    # NOMRES (pos 28-39, 1-based = 27:39 0-based)
    if nome_resumido:
        linha[27:39] = list(nome_resumido.ljust(12)[:12])
    preencher(56, 69, "4880")
    preencher(69, 82, "4887")
    preencher(82, 95, "4792")
    preencher(108, 121, "4799")
    preencher(147, 152, "39788")
    preencher(152, 170, "34440400")
    preencher(170, 188, "166083977300")
    return "".join(linha)


def test_parseia_posicoes_e_centavos_do_registro_real():
    candles = LeitorCotahist().ler_linhas([_linha_cotahist()], {"PETR4"})

    assert len(candles) == 1
    candle = candles[0]
    assert candle.simbolo == "PETR4"
    assert candle.data_pregao.isoformat() == "2026-09-25"
    assert candle.abertura == Decimal("48.80")
    assert candle.maxima == Decimal("48.87")
    assert candle.minima == Decimal("47.92")
    assert candle.fechamento == Decimal("47.99")
    assert candle.numero_negocios == 39788
    assert candle.volume == 34440400
    assert candle.volume_financeiro == Decimal("1660839773")


def test_candle_nome_resumido_preenchido():
    linhas = [_linha_cotahist(nome_resumido="PETROBRAS PN")]
    candle = LeitorCotahist().ler_linhas(linhas, {"PETR4"})[0]
    assert candle.nome_resumido == "PETROBRAS PN"


def test_candle_nome_resumido_vazio_retorna_none():
    candle = LeitorCotahist().ler_linhas([_linha_cotahist()], {"PETR4"})[0]
    assert candle.nome_resumido is None


def test_filtra_ticker_fora_do_universo_e_mercado_fracionario():
    leitor = LeitorCotahist()
    assert leitor.ler_linhas([_linha_cotahist("VALE3")], {"PETR4"}) == []
    assert leitor.ler_linhas([_linha_cotahist(mercado="020")], {"PETR4"}) == []


def _com(linha: str, inicio: int, fim: int, valor: str, alinhar_esquerda: bool = False) -> str:
    largura = fim - inicio
    campo = valor.ljust(largura) if alinhar_esquerda else valor.rjust(largura, "0")
    return linha[:inicio] + campo[:largura] + linha[fim:]


def _linha_opcao(
    simbolo: str = "PETRA32",
    mercado: str = "070",
    bdi: str = "00",
    vencimento: str = "20261120",
    strike_centavos: str = "3200",
    indice_correcao: str = "0",
    melhor_oferta_compra: str = "",
    melhor_oferta_venda: str = "",
) -> str:
    linha = _linha_cotahist(simbolo)
    linha = _com(linha, 10, 12, bdi)
    linha = _com(linha, 24, 27, mercado)
    linha = _com(linha, 188, 201, strike_centavos)
    # INDOPC (pos 202, 1-based = pos 201, 0-based): 1 char
    linha = _com(linha, 201, 202, indice_correcao)
    linha = _com(linha, 202, 210, vencimento)
    if melhor_oferta_compra:
        linha = _com(linha, 121, 134, melhor_oferta_compra)
    if melhor_oferta_venda:
        linha = _com(linha, 134, 147, melhor_oferta_venda)
    return linha


def test_marca_ex_vem_do_especi_e_campos_novos_sao_lidos():
    # RCSL3 em 10-03-2026: "ON  EB" no ESPECI (ex-bonificacao).
    linha = _com(_linha_cotahist("RCSL3"), 39, 49, "ON  EB", alinhar_esquerda=True)
    linha = _com(linha, 95, 108, "4850")   # PREMED
    linha = _com(linha, 121, 134, "4798")  # PREOFC
    linha = _com(linha, 134, 147, "4800")  # PREOFV

    (candle,) = LeitorCotahist().ler_linhas([linha], {"RCSL3"})

    assert candle.especificacao == "ON  EB"
    assert candle.marca_ex == "EB"
    assert candle.fator_cotacao == 1
    assert candle.preco_medio == Decimal("48.50")
    assert candle.melhor_oferta_compra == Decimal("47.98")
    assert candle.melhor_oferta_venda == Decimal("48.00")


def test_segmento_de_listagem_nao_e_marca_ex():
    linha = _com(_linha_cotahist(), 39, 49, "PN  EJ N2", alinhar_esquerda=True)
    assert LeitorCotahist().ler_linhas([linha], {"PETR4"})[0].marca_ex == "EJ"

    linha = _com(_linha_cotahist(), 39, 49, "ON      NM", alinhar_esquerda=True)
    assert LeitorCotahist().ler_linhas([linha], {"PETR4"})[0].marca_ex is None


def test_fatcot_divide_os_precos_por_acao():
    # GOLL54 vem cotada por lote de 1.000 (FATCOT 0001000).
    linha = _com(_linha_cotahist("GOLL54"), 210, 217, "1000")

    (candle,) = LeitorCotahist().ler_linhas([linha], {"GOLL54"})

    assert candle.fator_cotacao == 1000
    assert candle.fechamento == Decimal("47.99") / 1000
    assert candle.abertura == Decimal("48.80") / 1000
    # Volume financeiro e o total negociado em R$: nao depende do lote.
    assert candle.volume_financeiro == Decimal("1660839773")
    # Ofertas zeradas no registro viram nulo, nao 0.
    assert candle.melhor_oferta_compra is None


def test_rejeita_registro_de_cotacao_com_largura_incorreta():
    with pytest.raises(ValueError, match="245"):
        LeitorCotahist().ler_linhas([_linha_cotahist()[:-1]], {"PETR4"})


# --- opcoes: C1/C2 ---

def test_indice_correcao_preenchido_e_lido():
    (o,) = LeitorCotahist().ler_opcoes_linhas([_linha_opcao(indice_correcao="1")])
    assert o.status_validacao == "VALIDA"
    assert o.indice_correcao == "1"


def test_indice_correcao_vazio_retorna_none():
    (o,) = LeitorCotahist().ler_opcoes_linhas([_linha_opcao(indice_correcao=" ")])
    assert o.indice_correcao is None


def test_parseia_bid_ask_opcao():
    (o,) = LeitorCotahist().ler_opcoes_linhas(
        [_linha_opcao(melhor_oferta_compra="2190", melhor_oferta_venda="2210")]
    )
    assert o.melhor_oferta_compra == Decimal("21.90")
    assert o.melhor_oferta_venda == Decimal("22.10")


def test_bid_ask_zerado_retorna_none():
    (o,) = LeitorCotahist().ler_opcoes_linhas([_linha_opcao()])
    assert o.melhor_oferta_compra is None
    assert o.melhor_oferta_venda is None


# --- opcoes: validacao TPMERC ---

def test_opcao_real_usa_tipo_de_mercado_e_deriva_ativo_objeto():
    call, put = LeitorCotahist().ler_opcoes_linhas([
        _linha_opcao("PETRA32", mercado="070", bdi="00"),
        _linha_opcao("PETRM32", mercado="080", bdi="00"),
    ])

    assert call.status_validacao == "VALIDA"
    assert call.tipo_opcao == "CALL"
    assert call.ativo_objeto == "PETR"
    assert call.preco_exercicio == Decimal("32")
    assert call.data_vencimento.isoformat() == "2026-11-20"
    assert put.status_validacao == "VALIDA"
    assert put.tipo_opcao == "PUT"
    assert put.ativo_objeto == "PETR"


def test_bdi_12_ou_14_sem_mercado_de_opcao_vira_invalida_e_nao_cadeia():
    # BDI 12/14 isolado contaminava a tabela com ETF/FII e vencimento 9999.
    (registro,) = LeitorCotahist().ler_opcoes_linhas([
        _linha_opcao("BOVA11", mercado="010", bdi="12", vencimento="99991231"),
    ])

    assert registro.status_validacao == "INVALIDA"
    assert registro.motivo_rejeicao == "mercado_nao_opcao"
    assert registro.ativo_objeto is None
    assert registro.tipo_opcao is None


def test_rejeita_opcao_com_vencimento_sentinela_ou_strike_zero():
    vencimento_9999, strike_zero = LeitorCotahist().ler_opcoes_linhas([
        _linha_opcao("PETRA32", mercado="070", vencimento="99991231"),
        _linha_opcao("PETRA32", mercado="070", strike_centavos="0"),
    ])

    assert vencimento_9999.status_validacao == "INVALIDA"
    assert vencimento_9999.motivo_rejeicao == "vencimento_sentinela_9999"
    assert strike_zero.status_validacao == "INVALIDA"
    assert strike_zero.motivo_rejeicao == "preco_exercicio_invalido"


def test_rejeita_mercado_de_opcao_com_simbolo_sem_padrao_de_opcao():
    (registro,) = LeitorCotahist().ler_opcoes_linhas([
        _linha_opcao("HGRE11", mercado="070", vencimento="20261120", strike_centavos="10000"),
    ])

    assert registro.status_validacao == "INVALIDA"
    assert registro.motivo_rejeicao == "simbolo_sem_padrao_opcao"


def test_resume_validacao_de_opcoes_por_motivo_e_prefixo():
    opcoes = LeitorCotahist().ler_opcoes_linhas([
        _linha_opcao("PETRA32", mercado="070"),
        _linha_opcao("BOVA11", mercado="010", bdi="12", vencimento="99991231"),
        _linha_opcao("HGRE11", mercado="070"),
    ])

    resumo = resumir_validacao_opcoes(opcoes)

    assert resumo["total"] == 3
    assert resumo["validos"] == 1
    assert resumo["invalidos"] == 2
    assert resumo["vencimento_9999"] == 1
    assert resumo["ativos_com_cadeia"] == ["PETR"]
    assert resumo["motivos"] == {
        "mercado_nao_opcao": 1,
        "simbolo_sem_padrao_opcao": 1,
    }
    assert resumo["prefixos_suspeitos"] == {"BOVA": 1, "HGRE": 1}


# --- C4: moeda_referencia (MODREF pos 53-56, 1-based) ---

def _linha_cotahist_com_modref(modref: str) -> str:
    linha = list(_linha_cotahist())
    # MODREF: pos 53-56 (1-based) = indices 52:56 (0-based), 4 chars
    linha[52:56] = list(modref.ljust(4)[:4])
    return "".join(linha)


def test_candle_moeda_referencia_usd_para_bdr():
    linhas = [_linha_cotahist_com_modref("USD ")]
    candle = LeitorCotahist().ler_linhas(linhas, {"PETR4"})[0]
    assert candle.moeda_referencia == "USD"


def test_candle_moeda_referencia_padrao_brl():
    candle = LeitorCotahist().ler_linhas([_linha_cotahist()], {"PETR4"})[0]
    assert candle.moeda_referencia == "BRL"
