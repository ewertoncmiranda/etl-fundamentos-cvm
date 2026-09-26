"""Logger idempotente.

Diferente do repo irmao, chamar duas vezes nao adiciona handler de novo
(gerar-insights#ISS-08, que duplica toda linha de log), e o nivel vem das
Settings em vez de ficar fixo em INFO.
"""

from __future__ import annotations

import logging
import sys

NOME = "etl-fundamentos-cvm"
FORMATO = "%(asctime)s %(levelname)s %(name)s - %(message)s"


def configurar_logger(nivel: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(NOME)
    logger.setLevel(getattr(logging, nivel.upper(), logging.INFO))

    # idempotencia: so instala o handler na primeira chamada
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(FORMATO))
        logger.addHandler(handler)

    logger.propagate = False
    return logger
