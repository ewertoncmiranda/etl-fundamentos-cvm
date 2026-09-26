from decimal import Decimal

import pytest

from app.adaptadores.b3.leitor_cotahist import LeitorCotahist


def _linha_cotahist(simbolo: str = "PETR4", mercado: str = "010") -> str:
    linha = [" "] * 245

    def preencher(inicio: int, fim: int, valor: str) -> None:
        largura = fim - inicio
        linha[inicio:fim] = list(valor.rjust(largura, "0")[:largura])

    preencher(0, 2, "01")
    preencher(2, 10, "20260925")
    preencher(10, 12, "02")
    linha[12:24] = list(simbolo.ljust(12))
    preencher(24, 27, mercado)
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


def test_filtra_ticker_fora_do_universo_e_mercado_fracionario():
    leitor = LeitorCotahist()
    assert leitor.ler_linhas([_linha_cotahist("VALE3")], {"PETR4"}) == []
    assert leitor.ler_linhas([_linha_cotahist(mercado="020")], {"PETR4"}) == []


def test_rejeita_registro_de_cotacao_com_largura_incorreta():
    with pytest.raises(ValueError, match="245"):
        LeitorCotahist().ler_linhas([_linha_cotahist()[:-1]], {"PETR4"})
