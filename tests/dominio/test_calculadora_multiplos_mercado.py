"""Testes da CalculadoraMultiplosMercado (I4 e I7)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.dominio.calculo.calculadora_multiplos_mercado import (
    CalculadoraMultiplosMercado,
    InsumoMercado,
    _ev_ebitda,
    _pl,
)

PERIODO = date(2025, 12, 31)


def _insumo(
    simbolo="WEGE3",
    lpa=Decimal("1.52"),
    ebitda=Decimal("9500000000"),
    divida_liquida=Decimal("-1705676000"),
    acoes=4_195_695_973,
    cnae="2819-3/99",
) -> InsumoMercado:
    return InsumoMercado(
        simbolo=simbolo,
        periodo=PERIODO,
        lpa=lpa,
        ebitda=ebitda,
        divida_liquida=divida_liquida,
        acoes_ex_tesouraria=acoes,
        cnae=cnae,
    )


class TestFuncoesAuxiliares:

    def test_pl_calcula_preco_sobre_lpa(self):
        assert _pl(Decimal("30.40"), Decimal("1.52")) == Decimal("20.00")

    def test_pl_none_quando_lpa_zero(self):
        assert _pl(Decimal("30"), Decimal("0")) is None

    def test_pl_none_quando_lpa_negativo(self):
        assert _pl(Decimal("30"), Decimal("-1")) is None

    def test_pl_none_quando_preco_ausente(self):
        assert _pl(None, Decimal("1.52")) is None

    def test_ev_ebitda_calcula_multiplo(self):
        # market_cap = 30 * 100 = 3000; divida_liq = 200; ev = 3200; ebitda = 400
        resultado = _ev_ebitda(
            Decimal("30"), 100, Decimal("200"), Decimal("400")
        )
        assert resultado == Decimal("8.00")

    def test_ev_ebitda_subtrai_caixa_liquido(self):
        # divida_liquida negativa = caixa liquido (WEG); reduce EV
        resultado = _ev_ebitda(
            Decimal("30"), 100, Decimal("-100"), Decimal("400")
        )
        # ev = 3000 - 100 = 2900; ev/ebitda = 7.25
        assert resultado == Decimal("7.25")

    def test_ev_ebitda_none_quando_ebitda_zero(self):
        assert _ev_ebitda(Decimal("30"), 100, Decimal("0"), Decimal("0")) is None

    def test_ev_ebitda_none_sem_preco(self):
        assert _ev_ebitda(None, 100, Decimal("0"), Decimal("400")) is None


class TestCalculadoraMultiplosMercado:

    def test_calcula_pl_e_ev_ebitda(self):
        insumo = _insumo(simbolo="WEGE3", lpa=Decimal("1.52"), ebitda=Decimal("9500000000"))
        precos = {"WEGE3": Decimal("30.40")}

        metricas = CalculadoraMultiplosMercado().calcular([insumo], precos)

        assert len(metricas) == 1
        m = metricas[0]
        assert m.pl == Decimal("20.00")
        assert m.ev_ebitda is not None
        assert m.ev_ebitda > 0

    def test_pl_none_sem_preco(self):
        insumo = _insumo(simbolo="PETR4")
        metricas = CalculadoraMultiplosMercado().calcular([insumo], {})

        assert metricas[0].pl is None
        assert metricas[0].ev_ebitda is None

    def test_pl_setorial_mediana_com_dois_do_mesmo_setor(self):
        i1 = _insumo(simbolo="WEGE3", lpa=Decimal("2"), cnae="2819-3/99")
        i2 = _insumo(simbolo="ROMI3", lpa=Decimal("4"), cnae="2819-3/99")
        precos = {
            "WEGE3": Decimal("30"),  # P/L = 15
            "ROMI3": Decimal("20"),  # P/L = 5
        }

        metricas = CalculadoraMultiplosMercado().calcular([i1, i2], precos)

        # mediana de [15, 5] = 10
        assert metricas[0].pl_setorial_mediana == Decimal("10.00")
        assert metricas[1].pl_setorial_mediana == Decimal("10.00")

    def test_pl_setorial_mediana_none_com_setor_unico(self):
        insumo = _insumo(simbolo="WEGE3", lpa=Decimal("2"), cnae="2819-3/99")
        precos = {"WEGE3": Decimal("30")}

        metricas = CalculadoraMultiplosMercado().calcular([insumo], precos)

        assert metricas[0].pl_setorial_mediana is None

    def test_pl_setorial_nao_mistura_cnaes_diferentes(self):
        i1 = _insumo(simbolo="WEGE3", lpa=Decimal("2"), cnae="2819-3/99")
        i2 = _insumo(simbolo="PETR4", lpa=Decimal("4"), cnae="0600-0/01")
        precos = {"WEGE3": Decimal("30"), "PETR4": Decimal("20")}

        metricas = CalculadoraMultiplosMercado().calcular([i1, i2], precos)

        # setores diferentes — nenhum tem 2 empresas no mesmo CNAE[:4]
        assert metricas[0].pl_setorial_mediana is None
        assert metricas[1].pl_setorial_mediana is None

    def test_pl_setorial_none_quando_cnae_ausente(self):
        i1 = _insumo(simbolo="WEGE3", lpa=Decimal("2"), cnae=None)
        i2 = _insumo(simbolo="ROMI3", lpa=Decimal("4"), cnae=None)
        precos = {"WEGE3": Decimal("30"), "ROMI3": Decimal("20")}

        metricas = CalculadoraMultiplosMercado().calcular([i1, i2], precos)

        assert metricas[0].pl_setorial_mediana is None
        assert metricas[1].pl_setorial_mediana is None
