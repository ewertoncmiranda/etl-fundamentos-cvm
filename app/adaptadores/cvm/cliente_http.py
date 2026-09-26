"""Fala HTTP com a CVM. So isso.

O HEAD antes do GET e o que evita rebaixar 45 MB por ano toda semana: se o
ETag nao mudou desde a ultima execucao com sucesso, nao ha o que buscar.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from logging import Logger

from app.excecoes.excecoes import FonteIndisponivel

USER_AGENT = "etl-fundamentos-cvm/1.0 (+dados abertos CVM)"


@dataclass(frozen=True)
class Assinatura:
    """A identidade de um arquivo remoto, sem baixar o conteudo."""

    etag: str | None
    last_modified: str | None
    tamanho_bytes: int | None

    def inalterado_em_relacao_a(self, etag_anterior: str | None) -> bool:
        return bool(self.etag and etag_anterior and self.etag == etag_anterior)


class ClienteHttpCvm:
    def __init__(self, base_url: str, logger: Logger, timeout: int = 180):
        self._base_url = base_url.rstrip("/")
        self._logger = logger
        self._timeout = timeout

    def url_de(self, caminho: str) -> str:
        return f"{self._base_url}/{caminho.lstrip('/')}"

    def assinatura(self, caminho: str) -> Assinatura:
        url = self.url_de(caminho)
        requisicao = urllib.request.Request(
            url, method="HEAD", headers={"User-Agent": USER_AGENT}
        )
        try:
            with urllib.request.urlopen(requisicao, timeout=self._timeout) as resposta:
                cabecalhos = resposta.headers
                tamanho = cabecalhos.get("Content-Length")
                return Assinatura(
                    etag=cabecalhos.get("ETag"),
                    last_modified=cabecalhos.get("Last-Modified"),
                    tamanho_bytes=int(tamanho) if tamanho else None,
                )
        except (urllib.error.URLError, TimeoutError, OSError) as erro:
            raise FonteIndisponivel(f"HEAD falhou em {url}: {erro}") from erro

    def baixar(self, caminho: str) -> bytes:
        url = self.url_de(caminho)
        self._logger.info("Baixando %s", url)
        requisicao = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(requisicao, timeout=self._timeout) as resposta:
                return resposta.read()
        except (urllib.error.URLError, TimeoutError, OSError) as erro:
            raise FonteIndisponivel(f"GET falhou em {url}: {erro}") from erro
