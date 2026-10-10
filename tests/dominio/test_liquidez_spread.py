"""OPR-ETL-2: spread cotado (ofertas) e spread estimado por maxima/minima (Corwin-Schultz)."""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal as D

from app.dominio.liquidez import PregaoAtivo, calcular, spread_corwin_schultz

INICIO = date(2026, 1, 5)
MERCADO = [INICIO + timedelta(days=i) for i in range(70)]


def pregao(dia: date, fech: float, amplitude: float, ofertas: bool = True, spread_cotado: float = 0.001) -> PregaoAtivo:
    """Pregao sintetico: faixa simetrica de `amplitude` (fracao) em torno do fechamento."""
    alta, baixa = fech * (1 + amplitude / 2), fech * (1 - amplitude / 2)
    compra = D(str(round(fech * (1 - spread_cotado / 2), 6))) if ofertas else None
    venda = D(str(round(fech * (1 + spread_cotado / 2), 6))) if ofertas else None
    return PregaoAtivo(dia, D(str(fech)), D(str(round(alta, 6))), D(str(round(baixa, 6))), D(str(fech)),
                       D(str(fech)), compra, venda, D("10000000"), 1000)


def serie(amplitude: float, ofertas: bool = True) -> list[PregaoAtivo]:
    return [pregao(d, 50.0, amplitude, ofertas) for d in MERCADO]


def test_corwin_schultz_sem_amplitude_da_zero():
    a = pregao(MERCADO[0], 50, 0.0)
    b = pregao(MERCADO[1], 50, 0.0)
    assert spread_corwin_schultz(a, b) == 0.0


def test_corwin_schultz_bate_com_a_formula_do_artigo():
    a, b = pregao(MERCADO[0], 50, 0.02), pregao(MERCADO[1], 50, 0.02)
    h, l = 50 * 1.01, 50 * 0.99
    beta = 2 * math.log(h / l) ** 2
    gamma = math.log(h / l) ** 2
    k = 3 - 2 * math.sqrt(2)
    alfa = (math.sqrt(2 * beta) - math.sqrt(beta)) / k - math.sqrt(gamma / k)
    esperado = max(0.0, 2 * (math.exp(alfa) - 1) / (1 + math.exp(alfa)))
    assert math.isclose(spread_corwin_schultz(a, b), esperado, rel_tol=1e-6)
    assert esperado > 0


def test_gap_noturno_nao_vira_spread():
    """Dia seguinte inteiro acima do fechamento anterior: a faixa e deslocada, nao soma o gap."""
    a = pregao(MERCADO[0], 50, 0.01)
    b_sem_gap = pregao(MERCADO[1], 50, 0.01)
    b_com_gap = pregao(MERCADO[1], 55, 0.01)  # abriu 10% acima
    sem, com = spread_corwin_schultz(a, b_sem_gap), spread_corwin_schultz(a, b_com_gap)
    assert com is not None and com < 0.05  # sem o ajuste, o gap de 10% viraria "spread"
    assert com <= sem + 1e-9  # o gap nao aumenta o spread estimado


def test_dado_invalido_nao_estima():
    ruim = PregaoAtivo(MERCADO[1], None, None, None, None, None, None, None, None, None)
    assert spread_corwin_schultz(pregao(MERCADO[0], 50, 0.01), ruim) is None


def test_sem_ofertas_spread_cotado_nulo_com_motivo_e_estimado_presente():
    m = calcular("ILIQ3", MERCADO[-1], MERCADO, serie(0.03, ofertas=False))
    assert m.spread_mediano_63d is None
    assert m.motivos_ausencia["spread_mediano_63d"].startswith("ofertas_em_0_dias")
    assert m.spread_estimado_63d is not None and m.spread_estimado_63d > 0
    assert "spread_estimado_63d" not in m.motivos_ausencia


def test_com_ofertas_os_dois_spreads_existem():
    m = calcular("LIQD3", MERCADO[-1], MERCADO, serie(0.01))
    assert m.spread_mediano_63d == D("0.00100000")
    assert m.spread_estimado_63d is not None


def test_ativo_pouco_liquido_tem_spread_estimado_maior():
    liquido = calcular("LIQD3", MERCADO[-1], MERCADO, serie(0.01))
    iliquido = calcular("ILIQ3", MERCADO[-1], MERCADO, serie(0.04, ofertas=False))
    assert iliquido.spread_estimado_63d > liquido.spread_estimado_63d


def test_poucos_pares_deixa_estimado_nulo_com_motivo():
    # negociou so em 15 dos 63 pregoes: 14 pares, abaixo do minimo de 20
    esparsa = [pregao(d, 50, 0.02) for d in MERCADO[:7]] + [pregao(d, 50, 0.02) for d in MERCADO[-15:]]
    m = calcular("RARO3", MERCADO[-1], MERCADO, esparsa)
    assert m.spread_estimado_63d is None
    assert m.motivos_ausencia["spread_estimado_63d"] == "pares_alta_baixa_14_minimo_20"


def test_historico_curto_deixa_os_dois_nulos():
    m = calcular("NOVO3", MERCADO[-1], MERCADO, serie(0.02)[-10:])
    assert m.spread_mediano_63d is None and m.spread_estimado_63d is None
    assert m.motivos_ausencia["spread_estimado_63d"] == "historico_insuficiente"
