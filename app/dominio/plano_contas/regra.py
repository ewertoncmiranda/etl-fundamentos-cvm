"""A regra que diz como localizar uma metrica dentro de uma demonstracao."""

from __future__ import annotations

from dataclasses import dataclass

from app.dominio.modelo import TODOS_OS_PLANOS
from app.dominio.texto import normalizar


@dataclass(frozen=True)
class RegraConta:
    """Onde procurar uma metrica, e em quais planos de conta ela faz sentido.

    `rotulos` vem em ordem de prioridade e sao normalizados na construcao.
    `codigos` e o desempate, usado so quando nenhum rotulo aparece.
    `somar` vale para metricas compostas por mais de uma conta (divida bruta =
    circulante + nao circulante).
    """

    metrica: str
    demonstracao: str
    rotulos: tuple[str, ...] = ()
    codigos: tuple[str, ...] = ()
    planos: tuple[str, ...] = TODOS_OS_PLANOS
    somar: bool = False
    observacao: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "rotulos", tuple(normalizar(r) for r in self.rotulos))

    def vale_para(self, plano: str) -> bool:
        return plano in self.planos
