"""Guarda os ZIPs baixados em disco. So isso.

Vive num volume (cvm_cache) para sobreviver a recriacao do container. Junto
com o ETag em etl_execucao, uma execucao semanal sem novidade nao baixa nada.
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

    def gravar(self, nome: str, conteudo: bytes) -> Path:
        self._diretorio.mkdir(parents=True, exist_ok=True)
        caminho = self.caminho_de(nome)
        # grava em temporario e renomeia: um download interrompido nao deixa
        # arquivo truncado passando por valido no cache
        temporario = caminho.with_suffix(caminho.suffix + ".parcial")
        temporario.write_bytes(conteudo)
        temporario.replace(caminho)
        return caminho
