"""Normalizacao de texto para comparar descricoes de conta."""

from __future__ import annotations

import re
import unicodedata


def normalizar(texto: str | None) -> str:
    """Reduz uma DS_CONTA a uma forma comparavel.

    Remove acentos (os CSVs da CVM vem em latin-1), caixa, pontuacao de borda
    e espacos repetidos:

        'Patrimônio Líquido  Consolidado' -> 'patrimonio liquido consolidado'
    """
    if not texto:
        return ""
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    limpo = re.sub(r"\s+", " ", sem_acento).strip().lower()
    return limpo.strip(" .:-")
