"""Porta de entrada dos comunicados oficiais (base IPE da CVM)."""

from __future__ import annotations

from collections.abc import Collection
from typing import Protocol

from app.dominio.comunicado import Comunicado
from app.portas.fonte_documentos import AssinaturaDeArquivo


class FonteDeComunicados(Protocol):
    def assinatura(self, ano: int) -> AssinaturaDeArquivo:
        """ETag do arquivo anual, sem baixar. Igual ao da ultima carga: pula."""
        ...

    def comunicados(
        self, ano: int, cnpjs: set[str], categorias: Collection[str]
    ) -> list[Comunicado]:
        """Documentos do ano das companhias e categorias pedidas.

        Ja deduplicados: um por protocolo, na versao mais recente.
        """
        ...
