"""Descobre qual plano de contas a companhia usa.

Banco, seguradora e empresa comum publicam planos diferentes, e o mesmo
CD_CONTA muda de significado entre eles. A classificacao e feita pela propria
estrutura do balanco - os rotulos padronizados que so existem num dos planos -
em vez do setor declarado, que nem sempre vem preenchido no FCA.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.dominio.modelo import (
    BPP,
    DRE,
    PLANO_FINANCEIRO,
    PLANO_GERAL,
    PLANO_SEGURADORA,
    DocumentoContabil,
)
from app.dominio.texto import normalizar

PISTAS_FINANCEIRO: tuple[str, ...] = (
    "receitas de intermediacao financeira",
    "passivos financeiros ao custo amortizado",
    "resultado bruto de intermediacao financeira",
)

PISTAS_SEGURADORA: tuple[str, ...] = (
    "receitas de premios de seguros",
    "provisoes tecnicas",
    "sinistros ocorridos",
    # Rotulo do DRE no padrao IFRS 17 (DFP a partir de 2023; BBSE3 e IRBR3 no DFP 2025).
    "receitas das atividades seguradoras/resseguradoras",
)


class ClassificadorDePlano:
    def __init__(
        self,
        pistas_financeiro: Sequence[str] = PISTAS_FINANCEIRO,
        pistas_seguradora: Sequence[str] = PISTAS_SEGURADORA,
    ):
        self._financeiro = tuple(normalizar(p) for p in pistas_financeiro)
        self._seguradora = tuple(normalizar(p) for p in pistas_seguradora)

    def classificar(self, documento: DocumentoContabil) -> str:
        rotulos = {
            normalizar(linha.ds_conta)
            for demonstracao in (DRE, BPP)
            for linha in documento.da_demonstracao(demonstracao)
        }

        # seguradora antes de financeiro: uma seguradora pode ter as duas pistas
        if any(pista in rotulos for pista in self._seguradora):
            return PLANO_SEGURADORA
        if any(pista in rotulos for pista in self._financeiro):
            return PLANO_FINANCEIRO
        return PLANO_GERAL
