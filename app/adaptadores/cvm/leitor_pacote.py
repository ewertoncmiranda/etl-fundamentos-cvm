"""Abre o ZIP da CVM e decodifica os CSVs. So isso.

Os arquivos vem em latin-1 com delimitador ';' - ler como UTF-8 transforma
'Patrimônio Líquido' em lixo e o de-para para de casar por rotulo.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterator

from app.excecoes.excecoes import PacoteInvalido

ENCODING_CVM = "latin-1"
DELIMITADOR_CVM = ";"


class LeitorDePacoteCvm:
    def __init__(self, conteudo: bytes, nome_para_erro: str = "pacote"):
        self._nome = nome_para_erro
        try:
            self._zip = zipfile.ZipFile(io.BytesIO(conteudo))
        except zipfile.BadZipFile as erro:
            raise PacoteInvalido(f"{nome_para_erro} nao e um ZIP valido: {erro}") from erro

    def arquivos(self) -> list[str]:
        return self._zip.namelist()

    def tem(self, nome_csv: str) -> bool:
        return nome_csv in self._zip.namelist()

    def linhas(self, nome_csv: str) -> Iterator[dict[str, str]]:
        if not self.tem(nome_csv):
            raise PacoteInvalido(f"{self._nome} nao contem {nome_csv}")

        with self._zip.open(nome_csv) as bruto:
            texto = io.TextIOWrapper(bruto, encoding=ENCODING_CVM, newline="")
            leitor = csv.DictReader(texto, delimiter=DELIMITADOR_CVM)
            yield from leitor

    def fechar(self) -> None:
        self._zip.close()

    def __enter__(self) -> LeitorDePacoteCvm:
        return self

    def __exit__(self, *_: object) -> None:
        self.fechar()
