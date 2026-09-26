"""Porta de entrada de dados contabeis.

Uma implementacao nova (outra fonte, outro ano, um mock) entra sem tocar no
caso de uso - e o ponto de extensao mais provavel do sistema.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from app.dominio.modelo import ComposicaoCapital, DocumentoContabil, Empresa, Ticker


class AssinaturaDeArquivo(Protocol):
    """Somente leitura: a implementacao concreta e um dataclass congelado."""

    @property
    def etag(self) -> str | None:
        ...

    @property
    def last_modified(self) -> str | None:
        ...

    @property
    def tamanho_bytes(self) -> int | None:
        ...

    def inalterado_em_relacao_a(self, etag_anterior: str | None) -> bool:
        ...


class FonteDeDocumentos(Protocol):
    def assinatura(self, tipo: str, ano: int) -> AssinaturaDeArquivo:
        """Identidade do arquivo remoto sem baixar o conteudo (ETag).

        E o que permite pular a carga quando nada mudou na origem.
        """
        ...

    def tickers(self, ano: int) -> dict[str, Ticker]:
        """simbolo -> Ticker, para ligar WEGE3 ao CNPJ."""
        ...

    def empresas(self, ano: int) -> dict[str, Empresa]:
        """cnpj -> Empresa."""
        ...

    def documentos(self, ano: int, cnpjs: set[str]) -> Iterable[DocumentoContabil]:
        """As demonstracoes das companhias pedidas, ja normalizadas."""
        ...

    def composicoes_de_capital(self, ano: int, cnpjs: set[str]) -> dict[str, ComposicaoCapital]:
        """cnpj -> quantidade de acoes ex-tesouraria, com a unidade ja corrigida."""
        ...
