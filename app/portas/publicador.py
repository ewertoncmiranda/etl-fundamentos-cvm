"""Porta de saida de eventos."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class PublicadorDeEventos(Protocol):
    def publicar_fundamentos_atualizados(self, simbolos: Sequence[str]) -> None:
        """Avisa o gerar-insights de quais simbolos tiveram fundamentos novos."""
        ...
