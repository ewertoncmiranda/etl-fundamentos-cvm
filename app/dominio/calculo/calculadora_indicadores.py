"""Deriva os indicadores a partir dos insumos ja resolvidos.

Regra que atravessa o modulo: faltou insumo, a derivada e None. Nada e
estimado, nada vira zero por conveniencia.
"""

from __future__ import annotations

from decimal import Decimal, DivisionByZero, InvalidOperation

# Aliquota nominal de IR + CSLL. A efetiva exigiria a linha de tributos, que
# nao e estavel entre planos de conta. Documentado como limitacao: o ROIC e o
# indicador mais fraco do conjunto justamente por isso.
ALIQUOTA_NOMINAL = Decimal("0.34")
CONVENCAO_ROIC = (
    "NOPAT nominal / capital investido do controlador; "
    "capital investido = PL controlador + divida bruta - caixa"
)

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
    """Sem estado e sem I/O: entra dict de insumos, sai dict de derivados.

    ROIC segue a convencao interna `CONVENCAO_ROIC`: NOPAT calculado com
    aliquota nominal sobre EBIT e capital investido pela visao do controlador.
    Bancos e seguradoras nao recebem ROIC porque EBIT/divida operacional nao
    sao comparaveis nesses planos.
    """

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
        divida = insumos.get("divida_bruta")
        caixa = insumos.get("caixa_equivalentes")
        fco = insumos.get("fluxo_caixa_operacional")
        fci = insumos.get("fluxo_caixa_investimento")
        acoes = acoes_ex_tesouraria

        # Visao do controlador: e o que as referencias de mercado publicam.
        # Sem ela a WEG sai com ROE 36,5% contra 33,2% do Fundamentus.
        pl_controlador = None if pl is None else Decimal(pl) - Decimal(minoritarios)

        derivados: dict[str, Decimal | None] = {
            "lpa": _divide(lucro_ctrl, acoes),
            "vpa": _divide(pl_controlador, acoes),
            "roe": _percentual(lucro_ctrl, pl_controlador),
            "margem_liquida": _percentual(lucro, receita),
            "roic": self._roic(ebit, pl_controlador, divida, caixa),
            "divida_liquida": (
                None if divida is None or caixa is None else Decimal(divida) - Decimal(caixa)
            ),
            # FCL usa o total de investimento como proxy porque capex nao e
            # extraivel da CVM; fci ja vem negativo.
            "fluxo_caixa_livre": (
                None if fco is None or fci is None else Decimal(fco) + Decimal(fci)
            ),
        }
        return derivados

    def _roic(
        self,
        ebit: Decimal | None,
        pl_controlador: Decimal | None,
        divida: Decimal | None,
        caixa: Decimal | None,
    ) -> Decimal | None:
        capital_investido = capital_investido_controlador(
            pl_controlador, divida, caixa
        )
        if ebit is None or capital_investido is None:
            return None
        nopat = Decimal(ebit) * (Decimal(1) - self._aliquota)
        return _percentual(nopat, capital_investido)


def capital_investido_controlador(
    pl_controlador: Decimal | None,
    divida_bruta: Decimal | None,
    caixa_equivalentes: Decimal | None,
) -> Decimal | None:
    """Base do ROIC definida pela SPEC: PL controlador + divida - caixa."""

    if pl_controlador is None or divida_bruta is None or caixa_equivalentes is None:
        return None
    return Decimal(pl_controlador) + Decimal(divida_bruta) - Decimal(caixa_equivalentes)
