"""Fala HTTP com a CVM. So isso.

O HEAD antes do GET e o que evita rebaixar 45 MB por ano toda semana: se o
ETag nao mudou desde a ultima execucao com sucesso, nao ha o que buscar.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from logging import Logger
from time import sleep

from app.excecoes.excecoes import FonteIndisponivel

USER_AGENT = "etl-fundamentos-cvm/1.0 (+dados abertos CVM)"
CODIGOS_HTTP_TRANSITORIOS = {429}
ESPERAS_RETRY_PADRAO = (5.0, 15.0)


@dataclass(frozen=True)
class Assinatura:
    """A identidade de um arquivo remoto, sem baixar o conteudo."""

    etag: str | None
    last_modified: str | None
    tamanho_bytes: int | None

    def inalterado_em_relacao_a(self, etag_anterior: str | None) -> bool:
        return bool(self.etag and etag_anterior and self.etag == etag_anterior)


class ClienteHttpCvm:
    def __init__(
        self,
        base_url: str,
        logger: Logger,
        timeout: int = 180,
        esperas_retry: tuple[float, ...] = ESPERAS_RETRY_PADRAO,
        dormir: Callable[[float], None] = sleep,
    ):
        self._base_url = base_url.rstrip("/")
        self._logger = logger
        self._timeout = timeout
        self._esperas_retry = esperas_retry
        self._dormir = dormir

    def url_de(self, caminho: str) -> str:
        return f"{self._base_url}/{caminho.lstrip('/')}"

    def assinatura(self, caminho: str) -> Assinatura:
        url = self.url_de(caminho)
        requisicao = urllib.request.Request(
            url, method="HEAD", headers={"User-Agent": USER_AGENT}
        )
        with self._abrir_com_retry(requisicao, "HEAD", url) as resposta:
            cabecalhos = resposta.headers
            tamanho = cabecalhos.get("Content-Length")
            return Assinatura(
                etag=cabecalhos.get("ETag"),
                last_modified=cabecalhos.get("Last-Modified"),
                tamanho_bytes=int(tamanho) if tamanho else None,
            )

    def baixar(self, caminho: str) -> bytes:
        url = self.url_de(caminho)
        self._logger.info("Baixando %s", url)
        requisicao = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with self._abrir_com_retry(requisicao, "GET", url) as resposta:
            return resposta.read()

    def _abrir_com_retry(self, requisicao: urllib.request.Request, metodo: str, url: str):
        total_de_tentativas = len(self._esperas_retry) + 1
        for tentativa in range(1, total_de_tentativas + 1):
            try:
                return urllib.request.urlopen(requisicao, timeout=self._timeout)
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as erro:
                if (
                    not _erro_transitorio(erro)
                    or tentativa == total_de_tentativas
                ):
                    raise FonteIndisponivel(f"{metodo} falhou em {url}: {erro}") from erro

                espera = self._esperas_retry[tentativa - 1]
                self._logger.warning(
                    "%s falhou em %s (tentativa %d/%d): %s; nova tentativa em %.0f s",
                    metodo,
                    url,
                    tentativa,
                    total_de_tentativas,
                    erro,
                    espera,
                )
                if espera > 0:
                    self._dormir(espera)

        raise FonteIndisponivel(f"{metodo} falhou em {url}")


def _erro_transitorio(erro: BaseException) -> bool:
    if isinstance(erro, urllib.error.HTTPError):
        return erro.code in CODIGOS_HTTP_TRANSITORIOS or 500 <= erro.code <= 599
    return isinstance(erro, urllib.error.URLError | TimeoutError | OSError)
