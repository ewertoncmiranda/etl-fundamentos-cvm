"""Recompra executada a partir das contas de tesouraria do BPP."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.aplicacao.recompras import recompra_executada, series_tesouraria
from app.dominio.modelo import BPA, BPP, LinhaContabil

T1, T2, T3 = date(2025, 3, 31), date(2025, 6, 30), date(2025, 9, 30)


def _l(cd, ds, vl, dt, fixa=True, dem=BPP):
    return LinhaContabil(cd, ds, Decimal(vl), fixa, dem, dt, dt)


def test_series_soma_contas_fixas_e_ignora_outras():
    linhas = [
        _l("2.03.02.05", "Ações em Tesouraria", "-100", T1),
        _l("2.03.04.09", "Ações em Tesouraria", "-20", T1),
        _l("2.07.01.02.05", "Ações em  tesouraria", "-5", T2),
        _l("2.03.02.07", "Resultado na Alienação de Ações em Tesouraria", "-999", T1, fixa=False),
        _l("2.03.01.02", "Ações em Tesouraria", "-999", T1, fixa=False),
        _l("1.01", "Ações em Tesouraria", "-999", T1, dem=BPA),
    ]
    assert series_tesouraria(linhas) == {T1: Decimal("-120"), T2: Decimal("-5")}


def test_recompra_sinal():
    variacoes = recompra_executada({T3: Decimal("-80"), T1: Decimal("-100"), T2: Decimal("-150")})
    assert [(v.dt_inicio, v.dt_fim) for v in variacoes] == [(T1, T2), (T2, T3)]
    # saldo mais negativo = recompra
    assert variacoes[0].variacao == Decimal("-50")
    assert variacoes[0].recompra == Decimal("50")
    # saldo menos negativo = cancelamento/alienacao, sem recompra
    assert variacoes[1].variacao == Decimal("70")
    assert variacoes[1].recompra == Decimal("0")


def test_serie_curta():
    assert recompra_executada({}) == []
    assert recompra_executada({T1: Decimal("-1")}) == []
