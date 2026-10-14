"""Guarda os ZIPs baixados em disco. So isso.

Vive num volume (cvm_cache) para sobreviver a recriacao do container. Junto
com o ETag em etl_execucao, uma execucao semanal sem novidade nao baixa nada.
Cada ZIP tem ao lado um `<nome>.etag` com o ETag da copia: e por ele que a
fonte sabe que a CVM republicou o arquivo e a copia ficou velha.
"""

from __future__ import annotations

from pathlib import Path


class CacheDeArquivos:
    def __init__(self, diretorio: Path | str):
        self._diretorio = Path(diretorio)

    def caminho_de(self, nome: str) -> Path:
        return self._diretorio / Path(nome).name

    def tem(self, nome: str) -> bool:
        caminho = self.caminho_de(nome)
        return caminho.exists() and caminho.stat().st_size > 0

    def ler(self, nome: str) -> bytes:
        return self.caminho_de(nome).read_bytes()

    def etag_de(self, nome: str) -> str | None:
        """ETag da copia em disco, ou None se ela foi gravada sem (cache antigo)."""
        marca = self._marca_de(nome)
        if not marca.exists():
            return None
        return marca.read_text(encoding="utf-8").strip() or None

    def gravar(self, nome: str, conteudo: bytes, etag: str | None = None) -> Path:
        self._diretorio.mkdir(parents=True, exist_ok=True)
        caminho = self.caminho_de(nome)
        # grava em temporario e renomeia: um download interrompido nao deixa
        # arquivo truncado passando por valido no cache
        temporario = caminho.with_suffix(caminho.suffix + ".parcial")
        temporario.write_bytes(conteudo)
        temporario.replace(caminho)
        marca = self._marca_de(nome)
        if etag:
            marca.write_text(etag, encoding="utf-8")
        elif marca.exists():
            marca.unlink()
        return caminho

    def _marca_de(self, nome: str) -> Path:
        caminho = self.caminho_de(nome)
        return caminho.with_suffix(caminho.suffix + ".etag")
