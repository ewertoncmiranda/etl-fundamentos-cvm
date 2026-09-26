"""Porta de saida de eventos."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class PublicadorDeEventos(Protocol):
    def publicar_fundamentos_atualizados(self, simbolos: Sequence[str]) -> None:
        """Avisa o gerar-insights de quais simbolos tiveram fundamentos novos."""
        ...


class PublicadorDeComunicados(Protocol):
    def publicar_comunicados(self, eventos: Sequence[dict]) -> None:
        """Uma mensagem por ticker com documentos novos (contrato CTR-09)."""
        ...
