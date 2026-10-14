"""Proventos por periodo a partir da DVA (plano LAC, L1).

A DVA da CVM traz, em "Remuneracao de Capitais Proprios", o JCP (7.08.04.01)
e os dividendos (7.08.04.02) do periodo. E a unica fonte historica de
proventos dentro de COTAHIST+CVM: a B3 so devolve os ultimos ~12 meses por
evento. O valor e por periodo, nao por evento - a data ex sai do COTAHIST
(marca_ex) e quem reparte o trimestre entre elas e o gerar-insights.

Modulo puro: recebe DocumentoContabil, devolve ProventoPeriodo.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.dominio.modelo import DVA, DocumentoContabil
from app.dominio.plano_contas.regra import RegraConta
from app.dominio.plano_contas.resolvedor import ResolvedorDeContas

REGRA_JCP = RegraConta(
    metrica="jcp",
    demonstracao=DVA,
    rotulos=("juros sobre o capital proprio",),
    codigos=("7.08.04.01",),
)
REGRA_DIVIDENDOS = RegraConta(
    metrica="dividendos",
    demonstracao=DVA,
    rotulos=("dividendos",),
    codigos=("7.08.04.02",),
)


@dataclass(frozen=True)
class Acumulado:
    """JCP e dividendos acumulados no exercicio ate dt_fim (como a CVM publica)."""

    tipo_doc: str
    versao: int
    dt_ini: date
    dt_fim: date
    jcp: Decimal | None
    dividendos: Decimal | None


@dataclass(frozen=True)
class ProventoPeriodo:
    """Proventos de um periodo isolado (trimestre, ou o ano quando so ha DFP)."""

    tipo_doc: str
    versao: int
    dt_ini: date
    dt_fim: date
    jcp: Decimal | None
    dividendos: Decimal | None
    motivo: str = ""


def acumulado_do_documento(
    documento: DocumentoContabil, resolvedor: ResolvedorDeContas
) -> Acumulado | None:
    """None quando o documento nao tem DVA nenhuma (nao e zero: e ausencia).

    Conta de proventos ausente numa DVA presente vale 0: a companhia
    publicou a DVA e nao distribuiu aquilo no periodo.
    """
    linhas = documento.da_demonstracao(DVA)
    if not linhas:
        return None
    jcp = resolvedor.resolver(REGRA_JCP, linhas).valor
    dividendos = resolvedor.resolver(REGRA_DIVIDENDOS, linhas).valor
    return Acumulado(
        tipo_doc=documento.tipo_doc,
        versao=documento.versao,
        dt_ini=min(linha.dt_ini_exerc for linha in linhas),
        dt_fim=documento.dt_fim_exerc,
        jcp=jcp if jcp is not None else Decimal(0),
        dividendos=dividendos if dividendos is not None else Decimal(0),
    )


def isolar_periodos(
    itrs: Sequence[Acumulado], dfp: Acumulado | None
) -> list[ProventoPeriodo]:
    """Tira de cada acumulado o acumulado anterior do mesmo exercicio.

    ITR e DFP vem acumulados desde o inicio do exercicio: o 2o trimestre
    isolado e o acumulado de junho menos o de marco, e o ultimo periodo e a
    DFP menos o ultimo ITR. Faltando um trimestre, o periodo seguinte cobre
    os dois (dt_ini recua) - a soma continua certa. Diferenca negativa e
    reapresentacao: o periodo fica sem valor, com o motivo.
    """
    acumulados = sorted(itrs, key=lambda a: a.dt_fim)
    if dfp is not None:
        acumulados = [a for a in acumulados if a.dt_fim < dfp.dt_fim] + [dfp]

    periodos: list[ProventoPeriodo] = []
    anterior: Acumulado | None = None
    for atual in acumulados:
        inicio = atual.dt_ini if anterior is None else anterior.dt_fim + timedelta(days=1)
        jcp = _diferenca(atual.jcp, anterior.jcp if anterior else Decimal(0))
        dividendos = _diferenca(atual.dividendos, anterior.dividendos if anterior else Decimal(0))
        motivo = ""
        if (jcp is not None and jcp < 0) or (dividendos is not None and dividendos < 0):
            motivo = "acumulado menor que o do periodo anterior (reapresentacao); sem valor"
            jcp = dividendos = None
        periodos.append(
            ProventoPeriodo(
                tipo_doc=atual.tipo_doc,
                versao=atual.versao,
                dt_ini=inicio,
                dt_fim=atual.dt_fim,
                jcp=jcp,
                dividendos=dividendos,
                motivo=motivo,
            )
        )
        anterior = atual
    return periodos


def _diferenca(atual: Decimal | None, anterior: Decimal | None) -> Decimal | None:
    if atual is None or anterior is None:
        return None
    return atual - anterior


def por_acao(periodo: ProventoPeriodo, acoes: int | None) -> Decimal | None:
    if not acoes or periodo.jcp is None or periodo.dividendos is None:
        return None
    return (periodo.jcp + periodo.dividendos) / Decimal(acoes)



@dataclass(frozen=True)
class RegistroProvento:
    """O que vai para provento_contabil: o periodo com empresa, entrega e acoes."""

    cnpj: str
    periodo: ProventoPeriodo
    data_entrega: date | None
    acoes_ex_tesouraria: int | None
    grupo: str

    @property
    def por_acao(self) -> Decimal | None:
        return por_acao(self.periodo, self.acoes_ex_tesouraria)

    def cobertura(self) -> dict:
        cobertura: dict = {"grupo": self.grupo}
        if self.periodo.motivo:
            cobertura["motivo"] = self.periodo.motivo
        if self.acoes_ex_tesouraria is None:
            cobertura["por_acao"] = "sem composicao de capital para o CNPJ"
        return cobertura
