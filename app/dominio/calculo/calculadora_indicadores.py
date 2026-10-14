"""Deriva os indicadores a partir dos insumos ja resolvidos.

Regra que atravessa o modulo: faltou insumo, a derivada e None. Nada e
estimado, nada vira zero por conveniencia.
"""

from __future__ import annotations

import math
from decimal import Decimal, DivisionByZero, InvalidOperation

# Aliquota nominal de IR + CSLL. Usada como fallback quando impostos_dva nao
# esta disponivel (plano financeiro, dado ausente). I3 usa a taxa efetiva real
# calculada a partir do DVA quando possivel.
ALIQUOTA_NOMINAL = Decimal("0.34")

CEM = Decimal(100)


def _divide(numerador: Decimal | None, denominador: Decimal | int | None) -> Decimal | None:
    if numerador is None or not denominador:
        return None
    try:
        return Decimal(numerador) / Decimal(denominador)
    except (DivisionByZero, InvalidOperation, ZeroDivisionError):
        return None


def _percentual(numerador: Decimal | None, denominador: Decimal | None) -> Decimal | None:
    resultado = _divide(numerador, denominador)
    return None if resultado is None else resultado * CEM


class CalculadoraIndicadores:
    """Sem estado e sem I/O: entra dict de insumos, sai dict de derivados."""

    def __init__(self, aliquota: Decimal = ALIQUOTA_NOMINAL):
        self._aliquota = aliquota

    def calcular(
        self,
        insumos: dict[str, Decimal | None],
        acoes_ex_tesouraria: int | None = None,
    ) -> dict[str, Decimal | None]:
        lucro = insumos.get("lucro_liquido")
        lucro_ctrl = insumos.get("lucro_liquido_controlador")
        pl = insumos.get("patrimonio_liquido")
        minoritarios = insumos.get("participacao_nao_controladores") or Decimal(0)
        receita = insumos.get("receita_liquida")
        ebit = insumos.get("ebit")
        da = insumos.get("depreciacao_amortizacao")
        divida = insumos.get("divida_bruta")
        caixa = insumos.get("caixa_equivalentes")
        fco = insumos.get("fluxo_caixa_operacional")
        fci = insumos.get("fluxo_caixa_investimento")
        resultado_financeiro = insumos.get("resultado_financeiro")
        impostos_dva = insumos.get("impostos_dva")
        ativo_circ = insumos.get("ativo_circulante")
        passivo_circ = insumos.get("passivo_circulante")
        estoques = insumos.get("estoques")
        contas_receber = insumos.get("contas_a_receber")
        acoes = acoes_ex_tesouraria

        # Visao do controlador: e o que as referencias de mercado publicam.
        # Sem ela a WEG sai com ROE 36,5% contra 33,2% do Fundamentus.
        pl_controlador = None if pl is None else Decimal(pl) - Decimal(minoritarios)

        lpa = _divide(lucro_ctrl, acoes)
        vpa = _divide(pl_controlador, acoes)

        derivados: dict[str, Decimal | None] = {
            "lpa": lpa,
            "vpa": vpa,
            "roe": _percentual(lucro_ctrl, pl_controlador),
            "margem_liquida": _percentual(lucro, receita),
            "roic": self._roic(ebit, pl_controlador, divida, caixa, impostos_dva, lucro),
            "divida_liquida": (
                None if divida is None or caixa is None else Decimal(divida) - Decimal(caixa)
            ),
            # FCL usa o total de investimento como proxy porque capex nao e
            # extraivel da CVM; fci ja vem negativo.
            "fluxo_caixa_livre": (
                None if fco is None or fci is None else Decimal(fco) + Decimal(fci)
            ),
            # D&A vem positivo da DFC_MI (ajuste de nao-caixa adicionado de volta)
            "ebitda": (
                None if ebit is None or da is None else Decimal(ebit) + Decimal(da)
            ),
            # I1: cobertura de juros — so faz sentido quando RF e negativo (despesa liquida)
            "cobertura_juros": (
                None
                if ebit is None or resultado_financeiro is None or Decimal(resultado_financeiro) >= 0
                else _divide(Decimal(ebit), abs(Decimal(resultado_financeiro)))
            ),
            # I5: liquidez_corrente e liquidez_seca (excluem estoques)
            "liquidez_corrente": _divide(ativo_circ, passivo_circ),
            "liquidez_seca": (
                None
                if ativo_circ is None or estoques is None or passivo_circ is None
                else _divide(Decimal(ativo_circ) - Decimal(estoques), passivo_circ)
            ),
            # I6: DSO em dias
            "dso": (
                None
                if contas_receber is None or not receita
                else _divide(Decimal(365) * Decimal(contas_receber), receita)
            ),
            # I8: Graham Number — valor intrinseco classico; invalido para LPA/VPA negativos
            "graham_number": _graham_number(lpa, vpa),
        }
        return derivados

    def _roic(
        self,
        ebit: Decimal | None,
        pl_controlador: Decimal | None,
        divida: Decimal | None,
        caixa: Decimal | None,
        impostos_dva: Decimal | None = None,
        lucro_liquido: Decimal | None = None,
    ) -> Decimal | None:
        if ebit is None or pl_controlador is None or divida is None or caixa is None:
            return None
        # I3: aliquota efetiva a partir do DVA quando disponivel; fallback nominal
        aliquota = self._aliquota
        if impostos_dva is not None and lucro_liquido is not None and lucro_liquido > 0:
            impostos = abs(Decimal(impostos_dva))
            lucro_antes = Decimal(lucro_liquido) + impostos
            if lucro_antes > 0:
                aliquota = min(Decimal("0.99"), impostos / lucro_antes)
        capital_investido = Decimal(pl_controlador) + Decimal(divida) - Decimal(caixa)
        nopat = Decimal(ebit) * (Decimal(1) - aliquota)
        return _percentual(nopat, capital_investido)


def _graham_number(lpa: Decimal | None, vpa: Decimal | None) -> Decimal | None:
    if lpa is None or vpa is None or lpa <= 0 or vpa <= 0:
        return None
    try:
        valor = math.sqrt(float(Decimal("22.5") * Decimal(lpa) * Decimal(vpa)))
        return Decimal(str(valor)).quantize(Decimal("0.0001"))
    except (ValueError, ArithmeticError):
        return None
