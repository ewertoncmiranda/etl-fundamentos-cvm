"""Porta de tempo, para deixar datas testaveis."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Relogio(Protocol):
    def agora(self) -> datetime:
        ...


class RelogioDoSistema:
    def agora(self) -> datetime:
        return datetime.now()
