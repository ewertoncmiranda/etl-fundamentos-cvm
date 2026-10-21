from __future__ import annotations

from datetime import date

from app.adaptadores.cvm.cache_local import CacheDeArquivos
from app.adaptadores.cvm.cliente_http import Assinatura, ClienteHttpCvm
from app.adaptadores.tesouro.leitor_tesouro import TaxaTituloPublico, ler_csv

# Recurso "Taxas dos Titulos Ofertados pelo Tesouro Direto" no CKAN do Tesouro
# Transparente; conferido em 2026-10-20 (HEAD com ETag e Last-Modified).
URL_BASE = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/"
    "df56aa42-484a-4a59-8184-7676580c81e3/resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download"
)
ARQUIVO = "precotaxatesourodireto.csv"


class FonteTesouro:
    """Mesma semantica da FonteB3: HEAD/ETag decide se baixa; cache guarda o
    ultimo arquivo para reprocessar sem rede."""

    def __init__(self, cliente: ClienteHttpCvm, cache: CacheDeArquivos):
        self._cliente = cliente
        self._cache = cache

    def assinatura(self) -> Assinatura:
        return self._cliente.assinatura(ARQUIVO)

    def taxas(self, desde: date | None = None, usar_cache: bool = False) -> list[TaxaTituloPublico]:
        if usar_cache and self._cache.tem(ARQUIVO):
            conteudo = self._cache.ler(ARQUIVO)
        else:
            conteudo = self._cliente.baixar(ARQUIVO)
            self._cache.gravar(ARQUIVO, conteudo)
        return ler_csv(conteudo, desde)
