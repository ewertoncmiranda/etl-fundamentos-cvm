"""Porta de leitura da conciliacao BRAPI x COTAHIST."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from app.dominio.conciliacao import LinhaConciliacao


class RepositorioConciliacao(Protocol):
    def disponivel(self, db: Any) -> bool:
        """A view da V15 existe? Antes dela, o job so avisa e sai."""
        ...

    def pregoes_a_conciliar(self, db: Any) -> list[date]:
        """Pregoes ja resolvidos (sem PENDENTE) e ainda nao conciliados."""
        ...

    def linhas(self, db: Any, data_pregao: date) -> list[LinhaConciliacao]:
        ...
