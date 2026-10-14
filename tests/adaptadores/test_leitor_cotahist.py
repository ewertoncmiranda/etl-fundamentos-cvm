from decimal import Decimal

import pytest

from app.adaptadores.b3.leitor_cotahist import LeitorCotahist


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


def _linha_opcao(
    simbolo: str = "PETRA225",
    bdi: str = "12",
    indice_correcao: str = "0",
) -> str:
    """Monta registro COTAHIST de opcao (245 chars)."""
    linha = [" "] * 245

    def preencher(inicio: int, fim: int, valor: str) -> None:
        largura = fim - inicio
        linha[inicio:fim] = list(valor.rjust(largura, "0")[:largura])

    preencher(0, 2, "01")
    preencher(2, 10, "20260925")
    preencher(10, 12, bdi)
    linha[12:24] = list(simbolo.ljust(12))
    # TPMERC: 070=call, 080=put (pos 25-27, 1-based = 24:27 0-based)
    tpmerc = "070" if bdi == "12" else "080"
    preencher(24, 27, tpmerc)
    # abertura, maxima, minima, preco_medio (zeros = None no dominio)
    # fechamento
    preencher(108, 121, "2200")     # R$22,00
    # preco_exercicio (pos 189-201, 1-based = 188:201)
    preencher(188, 201, "2250")     # R$22,50
    # INDOPC (pos 202, 1-based = 201:202)
    linha[201] = indice_correcao
    # data_vencimento (pos 203-210, 1-based = 202:210)
    linha[202:210] = list("20260919")
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


def test_rejeita_registro_de_cotacao_com_largura_incorreta():
    with pytest.raises(ValueError, match="245"):
        LeitorCotahist().ler_linhas([_linha_cotahist()[:-1]], {"PETR4"})


# --- opcoes ---

def test_parseia_opcao_call_com_indice_correcao():
    linha = _linha_opcao(simbolo="PETRA225", bdi="12", indice_correcao="1")
    opcoes = LeitorCotahist().ler_opcoes_linhas([linha], {"PETRA225"})

    assert len(opcoes) == 1
    o = opcoes[0]
    assert o.simbolo == "PETRA225"
    assert o.bdi == "12"
    assert o.tipo_opcao == "CALL"
    assert o.preco_exercicio == Decimal("22.50")
    assert o.fechamento == Decimal("22.00")
    assert o.data_vencimento.isoformat() == "2026-09-19"
    assert o.indice_correcao == "1"
    assert o.status_validacao == "VALIDA"


def test_parseia_opcao_put():
    linha = _linha_opcao(simbolo="PETRA225", bdi="14", indice_correcao="0")
    opcoes = LeitorCotahist().ler_opcoes_linhas([linha], {"PETRA225"})

    assert len(opcoes) == 1
    assert opcoes[0].tipo_opcao == "PUT"
    assert opcoes[0].bdi == "14"
    assert opcoes[0].indice_correcao == "0"


def test_opcao_indice_correcao_vazio_retorna_none():
    linha = _linha_opcao(indice_correcao=" ")
    opcoes = LeitorCotahist().ler_opcoes_linhas([linha], {"PETRA225"})
    assert opcoes[0].indice_correcao is None


def test_candle_nao_aparece_como_opcao():
    linhas = [_linha_cotahist()]
    assert LeitorCotahist().ler_opcoes_linhas(linhas, {"PETR4"}) == []


def test_opcao_filtrada_fora_do_universo():
    linha = _linha_opcao(simbolo="VALED225")
    assert LeitorCotahist().ler_opcoes_linhas([linha], {"PETRA225"}) == []
