from __future__ import annotations

from logging import Logger

from app.adaptadores.cvm.cliente_http import ClienteHttpCvm


class ClienteHttpB3(ClienteHttpCvm):
    """Cliente HTTP com a mesma semântica de HEAD/ETag usada pela CVM."""

    def __init__(self, base_url: str, logger: Logger, timeout: int = 180):
        super().__init__(base_url, logger, timeout)
