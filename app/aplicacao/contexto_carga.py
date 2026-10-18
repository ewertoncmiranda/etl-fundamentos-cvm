"""Contexto local da carga que originou os registros de arquivo do ETL."""

from contextvars import ContextVar, Token

_CARGA_ID: ContextVar[str | None] = ContextVar("carga_execucao_id", default=None)


def carga_atual() -> str | None:
    return _CARGA_ID.get()


def definir_carga_atual(carga_id: str) -> Token:
    return _CARGA_ID.set(carga_id)


def restaurar_carga_atual(token: Token) -> None:
    _CARGA_ID.reset(token)
