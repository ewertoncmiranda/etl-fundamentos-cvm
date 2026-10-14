from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from app.dominio.evento_corporativo import Composicao, EventoInferido, PregaoMarcado


class RepositorioEventoCorporativo(Protocol):
    """Le marcas ex e capital ja carregados; grava evento_corporativo (V16)."""

    def pregoes(self, db: Any, anos: Sequence[int] | None) -> list[PregaoMarcado]:
        """Pregoes com marca societaria, com marca e fechamento do pregao
        anterior - dos anos pedidos, ou de todos."""
        ...

    def composicoes(self, db: Any) -> dict[str, list[Composicao]]:
        """cnpj -> composicoes de capital (DFP), em qualquer ordem."""
        ...

    def cnpj_por_simbolo(self, db: Any) -> dict[str, str]:
        ...

    def substituir(
        self, db: Any, eventos: Sequence[EventoInferido], anos: Sequence[int] | None
    ) -> int:
        ...
