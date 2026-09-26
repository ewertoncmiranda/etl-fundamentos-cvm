"""Localiza a conta de uma metrica dentro de uma demonstracao.

Duas estrategias intercambiaveis atras de um Protocol, tentadas em ordem:

  1. rotulo  - DS_CONTA normalizada entre as contas com ST_CONTA_FIXA='S'
  2. codigo  - CD_CONTA, so como desempate quando o rotulo nao aparece

O resolvedor nao sabe qual e qual: recebe a lista e tenta uma a uma. Estrategia
nova entra sem alterar o resolvedor.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol

from app.dominio.modelo import ContaResolvida, LinhaContabil
from app.dominio.plano_contas.regra import RegraConta
from app.dominio.texto import normalizar


class EstrategiaDeResolucao(Protocol):
    """Uma forma de achar as linhas que correspondem a uma regra."""

    nome: str

    def localizar(
        self, regra: RegraConta, linhas: Sequence[LinhaContabil]
    ) -> list[LinhaContabil]:
        ...


def _somente_sinteticas(achadas: Sequence[LinhaContabil]) -> list[LinhaContabil]:
    """Descarta conta que seja descendente de outra ja achada.

    O mesmo rotulo aparece na sintetica e nas filhas (2.01.04 'Emprestimos e
    Financiamentos' e 2.01.04.01 idem). Somar as duas dobra a divida.
    """
    return [
        linha
        for linha in achadas
        if not any(
            outra.cd_conta != linha.cd_conta and linha.e_descendente_de(outra)
            for outra in achadas
        )
    ]


class ResolucaoPorRotulo:
    """Casa a DS_CONTA normalizada, restrita as contas padronizadas pela CVM."""

    nome = "rotulo"

    def localizar(
        self, regra: RegraConta, linhas: Sequence[LinhaContabil]
    ) -> list[LinhaContabil]:
        fixas = [linha for linha in linhas if linha.conta_fixa]
        for rotulo in regra.rotulos:
            achadas = [linha for linha in fixas if normalizar(linha.ds_conta) == rotulo]
            if achadas:
                return achadas
        return []


class ResolucaoPorCodigo:
    """Desempate por CD_CONTA, para quando a companhia nao usa o rotulo padrao."""

    nome = "codigo"

    def localizar(
        self, regra: RegraConta, linhas: Sequence[LinhaContabil]
    ) -> list[LinhaContabil]:
        return [linha for linha in linhas if linha.cd_conta in regra.codigos]


ESTRATEGIAS_PADRAO: tuple[EstrategiaDeResolucao, ...] = (
    ResolucaoPorRotulo(),
    ResolucaoPorCodigo(),
)


class ResolvedorDeContas:
    def __init__(self, estrategias: Sequence[EstrategiaDeResolucao] | None = None):
        self._estrategias = tuple(estrategias or ESTRATEGIAS_PADRAO)

    def resolver(
        self, regra: RegraConta, linhas: Sequence[LinhaContabil]
    ) -> ContaResolvida:
        for estrategia in self._estrategias:
            achadas = estrategia.localizar(regra, linhas)
            if not achadas:
                continue

            if regra.somar:
                sinteticas = _somente_sinteticas(achadas)
                return ContaResolvida(
                    metrica=regra.metrica,
                    valor=sum((s.vl_conta for s in sinteticas), Decimal(0)),
                    estrategia=estrategia.nome,
                    cd_conta="+".join(sorted(s.cd_conta for s in sinteticas)),
                    ds_conta=sinteticas[0].ds_conta,
                    motivo=self._motivo(estrategia, regra),
                )

            # sem somar: a conta de menor profundidade e a sintetica correta
            escolhida = min(achadas, key=lambda c: (c.profundidade, c.cd_conta))
            return ContaResolvida(
                metrica=regra.metrica,
                valor=escolhida.vl_conta,
                estrategia=estrategia.nome,
                cd_conta=escolhida.cd_conta,
                ds_conta=escolhida.ds_conta,
                motivo=self._motivo(estrategia, regra),
            )

        return ContaResolvida(
            metrica=regra.metrica,
            valor=None,
            estrategia="ausente",
            motivo=(
                f"nenhum rotulo nem codigo {regra.codigos} em {regra.demonstracao}"
            ),
        )

    @staticmethod
    def _motivo(estrategia: EstrategiaDeResolucao, regra: RegraConta) -> str:
        if estrategia.nome == "codigo":
            return "rotulo nao encontrado; caiu para CD_CONTA"
        return ""
