"""Unidade de trabalho: o unico lugar que da commit.

Os repositorios so fazem add/execute. Isso corrige o problema catalogado como
gerar-insights#ISS-01, onde repositorios commitam por conta propria e uma
falha no meio da carga deixa metade gravada.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any


class UnidadeDeTrabalho:
    def __init__(self, fabrica_de_sessao: Callable[[], Any]):
        self._fabrica = fabrica_de_sessao

    @contextmanager
    def transacao(self) -> Iterator[Any]:
        sessao = self._fabrica()
        try:
            yield sessao
            sessao.commit()
        except Exception:
            sessao.rollback()
            raise
        finally:
            sessao.close()
