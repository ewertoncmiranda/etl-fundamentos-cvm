"""Calcula P/L (I4) e EV/EBITDA (I7) a partir de preco de mercado + contabilidade.

Separado da CalculadoraIndicadores por proposito: esses multiplos dependem
de cotacao de bolsa, que nao vem do DFP/ITR. O dominio contabil e calculado
sem rede; estes multiplos so sao possiveis depois que a serie historica ja
foi carregada no banco.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, DivisionByZero, InvalidOperation


@dataclass(frozen=True)
class InsumoMercado:
    """Dados contabeis necessarios para calcular multiplos de mercado."""

    simbolo: str
    periodo: date
    lpa: Decimal | None
    ebitda: Decimal | None
    divida_liquida: Decimal | None
    acoes_ex_tesouraria: int | None
    cnae: str | None


@dataclass(frozen=True)
class MetricaMercado:
    """Resultado do calculo de multiplos para uma empresa num periodo."""

    simbolo: str
    periodo: date
    # I7: EV/EBITDA — (market_cap + divida_liquida) / ebitda
    pl: Decimal | None
    ev_ebitda: Decimal | None
    # I4: mediana do P/L das empresas do mesmo setor CNAE (classe 4 digitos)
    pl_setorial_mediana: Decimal | None


def _pl(preco: Decimal | None, lpa: Decimal | None) -> Decimal | None:
    if preco is None or lpa is None or lpa <= 0:
        return None
    try:
        return (Decimal(preco) / Decimal(lpa)).quantize(Decimal("0.01"))
    except (DivisionByZero, InvalidOperation, ZeroDivisionError):
        return None


def _ev_ebitda(
    preco: Decimal | None,
    acoes: int | None,
    divida_liquida: Decimal | None,
    ebitda: Decimal | None,
) -> Decimal | None:
    if preco is None or acoes is None or ebitda is None or ebitda <= 0:
        return None
    try:
        market_cap = Decimal(str(preco)) * Decimal(str(acoes))
        dl = Decimal(str(divida_liquida)) if divida_liquida is not None else Decimal(0)
        ev = market_cap + dl
        return (ev / Decimal(str(ebitda))).quantize(Decimal("0.01"))
    except (DivisionByZero, InvalidOperation, ZeroDivisionError):
        return None


class CalculadoraMultiplosMercado:
    """Sem estado e sem I/O: entra lista de insumos + precos, sai lista de metricas."""

    def calcular(
        self,
        insumos: list[InsumoMercado],
        precos: dict[str, Decimal],
    ) -> list[MetricaMercado]:
        # Pass 1: P/L e EV/EBITDA por empresa; acumula P/L por setor CNAE
        parciais: list[dict] = []
        pl_por_cnae: dict[str, list[Decimal]] = {}

        for insumo in insumos:
            preco = precos.get(insumo.simbolo)
            pl = _pl(preco, insumo.lpa)
            ev = _ev_ebitda(preco, insumo.acoes_ex_tesouraria, insumo.divida_liquida, insumo.ebitda)

            parciais.append({"insumo": insumo, "pl": pl, "ev_ebitda": ev})

            if pl is not None and insumo.cnae and len(insumo.cnae) >= 4:
                pl_por_cnae.setdefault(insumo.cnae[:4], []).append(pl)

        # Pass 2: mediana setorial (minimo 2 empresas para ser representativa)
        resultados = []
        for p in parciais:
            insumo = p["insumo"]
            chave = insumo.cnae[:4] if insumo.cnae and len(insumo.cnae) >= 4 else None
            valores = pl_por_cnae.get(chave, []) if chave else []
            mediana = (
                Decimal(str(statistics.median(float(v) for v in valores))).quantize(
                    Decimal("0.01")
                )
                if len(valores) >= 2
                else None
            )
            resultados.append(
                MetricaMercado(
                    simbolo=insumo.simbolo,
                    periodo=insumo.periodo,
                    pl=p["pl"],
                    ev_ebitda=p["ev_ebitda"],
                    pl_setorial_mediana=mediana,
                )
            )

        return resultados
