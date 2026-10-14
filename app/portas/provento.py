"""Porta de gravacao dos proventos por periodo (plano LAC, L1)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from app.dominio.provento import RegistroProvento


class RepositorioProvento(Protocol):
    def salvar(self, db: Any, registros: Sequence[RegistroProvento]) -> int:
        ...
