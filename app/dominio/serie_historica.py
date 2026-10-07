"""Modelo puro de uma cotação diária da B3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class CandleB3:
    """Precos ja divididos pelo fator de cotacao (FATCOT): R$ por acao."""

    simbolo: str
    data_pregao: date
    abertura: Decimal
    maxima: Decimal
    minima: Decimal
    fechamento: Decimal
    volume: int
    numero_negocios: int
    volume_financeiro: Decimal
    # ESPECI cru ("ON  EB", "PN  EJ N2") e o sufixo de dia ex, quando ha.
    especificacao: str | None = None
    marca_ex: str | None = None
    fator_cotacao: int = 1
    preco_medio: Decimal | None = None
    melhor_oferta_compra: Decimal | None = None
    melhor_oferta_venda: Decimal | None = None
    isin: str | None = None
