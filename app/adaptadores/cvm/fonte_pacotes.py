"""Download com ETag e cache dos pacotes VLMO, FRE e CDA da CVM.

Mesma semantica da FonteCvm: o HEAD (assinatura) decide se ha novidade; a copia
em cache so e reaproveitada se o ETag gravado ao lado bate com o atual.
VLMO e FRE ficam sob `cvm_base_url` (CIA_ABERTA/DOC); o CDA, em outra arvore
(FI/DOC/CDA/DADOS), por isso o segundo cliente.
"""

from __future__ import annotations

import urllib.error
from logging import Logger

from app.adaptadores.cvm.cache_local import CacheDeArquivos
from app.adaptadores.cvm.cliente_http import Assinatura, ClienteHttpCvm
from app.excecoes.excecoes import FonteIndisponivel


class ArquivoAusente(FonteIndisponivel):
    """A CVM respondeu 404: o arquivo daquele periodo ainda nao foi publicado."""


class FontePacotesCvm:
    def __init__(
        self,
        cliente_cia_aberta: ClienteHttpCvm,
        cliente_fundos: ClienteHttpCvm,
        cache: CacheDeArquivos,
        logger: Logger,
    ):
        self._cia = cliente_cia_aberta
        self._fundos = cliente_fundos
        self._cache = cache
        self._logger = logger
        self._assinaturas: dict[str, Assinatura] = {}

    # --- nomes -----------------------------------------------------------

    @staticmethod
    def nome_vlmo(ano: int) -> str:
        return f"vlmo_cia_aberta_{ano}.zip"

    @staticmethod
    def nome_fre(ano: int) -> str:
        return f"fre_cia_aberta_{ano}.zip"

    @staticmethod
    def nome_cda(competencia: str) -> str:
        return f"cda_fi_{competencia}.zip"

    # --- API publica -----------------------------------------------------

    def assinatura_vlmo(self, ano: int) -> Assinatura:
        return self._assinatura(self._cia, f"VLMO/DADOS/{self.nome_vlmo(ano)}")

    def vlmo(self, ano: int) -> bytes:
        return self._conteudo(self._cia, f"VLMO/DADOS/{self.nome_vlmo(ano)}")

    def assinatura_fre(self, ano: int) -> Assinatura:
        return self._assinatura(self._cia, f"FRE/DADOS/{self.nome_fre(ano)}")

    def fre(self, ano: int) -> bytes:
        return self._conteudo(self._cia, f"FRE/DADOS/{self.nome_fre(ano)}")

    def assinatura_cda(self, competencia: str) -> Assinatura:
        return self._assinatura(self._fundos, self.nome_cda(competencia))

    def cda(self, competencia: str) -> bytes:
        return self._conteudo(self._fundos, self.nome_cda(competencia))

    # --- internos --------------------------------------------------------

    def _assinatura(self, cliente: ClienteHttpCvm, caminho: str) -> Assinatura:
        chave = cliente.url_de(caminho)
        if chave not in self._assinaturas:
            try:
                self._assinaturas[chave] = cliente.assinatura(caminho)
            except FonteIndisponivel as erro:
                causa = erro.__cause__
                if isinstance(causa, urllib.error.HTTPError) and causa.code == 404:
                    raise ArquivoAusente(str(erro)) from erro
                raise
        return self._assinaturas[chave]

    def _conteudo(self, cliente: ClienteHttpCvm, caminho: str) -> bytes:
        nome = caminho.rsplit("/", 1)[-1]
        assinatura = self._assinatura(cliente, caminho)
        if self._cache.tem(nome) and (
            assinatura.etag is None or assinatura.etag == self._cache.etag_de(nome)
        ):
            self._logger.debug("Usando %s do cache", nome)
            return self._cache.ler(nome)
        conteudo = cliente.baixar(caminho)
        self._cache.gravar(nome, conteudo, assinatura.etag)
        return conteudo
