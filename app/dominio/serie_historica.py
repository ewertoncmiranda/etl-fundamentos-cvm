"""Modelo puro de uma cotação diária da B3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class CandleB3:
    simbolo: str
    data_pregao: date
    abertura: Decimal
    maxima: Decimal
    minima: Decimal
    fechamento: Decimal
    volume: int
    numero_negocios: int
    volume_financeiro: Decimal
