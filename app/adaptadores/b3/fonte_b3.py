from __future__ import annotations

from app.adaptadores.b3.cliente_http_b3 import ClienteHttpB3
from app.adaptadores.b3.leitor_cotahist import LeitorCotahist
from app.adaptadores.cvm.cache_local import CacheDeArquivos
from app.adaptadores.cvm.cliente_http import Assinatura
from app.dominio.serie_historica import CandleB3, OpcaoB3


class FonteB3:
    def __init__(self, cliente: ClienteHttpB3, cache: CacheDeArquivos, leitor: LeitorCotahist):
        self._cliente = cliente
        self._cache = cache
        self._leitor = leitor

    @staticmethod
    def caminho(ano: int) -> str:
        return f"COTAHIST_A{ano}.ZIP"

    def assinatura(self, ano: int) -> Assinatura:
        return self._cliente.assinatura(self.caminho(ano))

    def candles(
        self, ano: int, simbolos: set[str] | None, usar_cache: bool = False
    ) -> list[CandleB3]:
        """usar_cache: ano fechado nao muda; so o ano corrente precisa baixar
        de novo (~90 MB por arquivo). simbolos=None: universo amplo (TASK-59)."""
        nome = self.caminho(ano)
        if usar_cache and self._cache.tem(nome):
            conteudo = self._cache.ler(nome)
        else:
            conteudo = self._cliente.baixar(nome)
            self._cache.gravar(nome, conteudo)
        return self._leitor.ler_zip(conteudo, simbolos)

    def opcoes(self, ano: int, usar_cache: bool = False) -> list[OpcaoB3]:
        """BDI 12 (calls) e 14 (puts) do COTAHIST; reutiliza o cache do ano."""
        nome = self.caminho(ano)
        if usar_cache and self._cache.tem(nome):
            conteudo = self._cache.ler(nome)
        else:
            conteudo = self._cliente.baixar(nome)
            self._cache.gravar(nome, conteudo)
        return self._leitor.ler_opcoes_zip(conteudo)
