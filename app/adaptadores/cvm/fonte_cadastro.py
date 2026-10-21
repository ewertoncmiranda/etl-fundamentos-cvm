"""Cadastro de companhias abertas com a decisao de ETag fora do leitor.

`LeitorCadastroCvm` do Codex sempre faz HEAD+cache; aqui a assinatura fica
exposta para o caso de uso registrar PULADO sem baixar nem reler o arquivo.
"""

from __future__ import annotations

from app.adaptadores.cvm.cache_local import CacheDeArquivos
from app.adaptadores.cvm.cadastro import CAMINHO_CADASTRO, CadastroCvm, ler_cadastro
from app.adaptadores.cvm.cliente_http import Assinatura, ClienteHttpCvm

NOME = "cad_cia_aberta.csv"


class FonteCadastroCvm:
    nome_arquivo = NOME

    def __init__(self, cliente: ClienteHttpCvm, cache: CacheDeArquivos):
        self._cliente = cliente
        self._cache = cache
        self._assinatura: Assinatura | None = None

    def assinatura(self) -> Assinatura:
        self._assinatura = self._cliente.assinatura(CAMINHO_CADASTRO)
        return self._assinatura

    def cadastro(self) -> dict[str, CadastroCvm]:
        conteudo = self._cliente.baixar(CAMINHO_CADASTRO)
        cadastro = ler_cadastro(conteudo)
        self._cache.gravar(NOME, conteudo, self._assinatura.etag if self._assinatura else None)
        return cadastro
