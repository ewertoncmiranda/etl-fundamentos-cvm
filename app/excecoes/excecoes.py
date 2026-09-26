"""Hierarquia de excecoes do ETL.

Diferente do repo irmao, onde a hierarquia existe e nunca e usada, aqui a
divisao permanente/transitorio e o que o fluxo de fato consulta para decidir
entre abortar e tentar de novo.
"""

from __future__ import annotations


class ErroEtl(Exception):
    """Base de tudo que este app levanta por conta propria."""


class ErroPermanente(ErroEtl):
    """Nao adianta repetir: arquivo malformado, conta faltando, CNPJ invalido.

    Registra, pula o item e segue para o proximo.
    """


class ErroTransitorio(ErroEtl):
    """Pode dar certo depois: rede fora, banco indisponivel, 503 da CVM."""


class FonteIndisponivel(ErroTransitorio):
    """A CVM nao respondeu ou devolveu erro de servidor."""


class PacoteInvalido(ErroPermanente):
    """O ZIP baixou mas nao tem o CSV esperado dentro."""
