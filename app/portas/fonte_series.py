from __future__ import annotations

from typing import Protocol

from app.adaptadores.cvm.cliente_http import Assinatura
from app.dominio.serie_historica import CandleB3


class FonteDeSeries(Protocol):
    def assinatura(self, ano: int) -> Assinatura: ...

    def candles(
        self, ano: int, simbolos: set[str] | None, usar_cache: bool = False
    ) -> list[CandleB3]: ...
