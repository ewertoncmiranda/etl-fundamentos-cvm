"""Recompra executada a partir do BPP (DFP/ITR) que o ETL ja grava em fato_contabil.

A conta e "Acoes em Tesouraria", conta fixa (ST_CONTA_FIXA = S) do patrimonio
liquido. Na DFP 2025 (BPP consolidado) ela aparece em dois lugares, que somados
dao o saldo:
  - geral:        2.03.02.05 (Reservas de Capital) e 2.03.04.09 (Reservas de Lucros)
  - bancos:       2.07.01.02.05 e 2.07.01.04.09
  - seguradoras:  2.08.02.05 e 2.08.04.09
Por isso a identificacao e por conta fixa + descricao normalizada no grupo 2,
e nao por um codigo unico.

Sinal: o saldo e redutor do PL e vem NEGATIVO.
  variacao = saldo_fim - saldo_inicio
  variacao < 0 -> tesouraria cresceu -> recompra executada (recompra = -variacao)
  variacao > 0 -> saida da tesouraria (cancelamento, alienacao, entrega a plano)
O valor e contabil (custo de aquisicao, em R$), nao quantidade de acoes. Um
cancelamento no mesmo periodo de uma recompra compensa parte dela (valor liquido).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.dominio.modelo import BPP, LinhaContabil
from app.dominio.texto import normalizar

DESCRICAO_TESOURARIA = "acoes em tesouraria"


@dataclass(frozen=True)
class VariacaoTesouraria:
    dt_inicio: date
    dt_fim: date
    saldo_inicio: Decimal
    saldo_fim: Decimal
    variacao: Decimal  # saldo_fim - saldo_inicio; negativo = recompra
    recompra: Decimal  # max(0, -variacao)


def e_conta_tesouraria(cd_conta: str, ds_conta: str, conta_fixa: bool) -> bool:
    return (
        conta_fixa
        and cd_conta.startswith("2.")
        and normalizar(ds_conta) == DESCRICAO_TESOURARIA
    )


def series_tesouraria(linhas: Iterable[LinhaContabil]) -> dict[date, Decimal]:
    """Saldo de acoes em tesouraria por data de balanco (soma das contas fixas do BPP).

    Espera linhas de uma unica companhia e de um unico grupo (consolidado ou individual).
    """
    saida: dict[date, Decimal] = {}
    for lin in linhas:
        if lin.demonstracao != BPP:
            continue
        if not e_conta_tesouraria(lin.cd_conta, lin.ds_conta, lin.conta_fixa):
            continue
        saida[lin.dt_fim_exerc] = saida.get(lin.dt_fim_exerc, Decimal(0)) + lin.vl_conta
    return dict(sorted(saida.items()))


def recompra_executada(series_tesouraria: dict[date, Decimal]) -> list[VariacaoTesouraria]:
    """Variacao do saldo de tesouraria entre balancos consecutivos, em ordem de data."""
    datas = sorted(series_tesouraria)
    saida: list[VariacaoTesouraria] = []
    for ini, fim in zip(datas, datas[1:]):
        a, b = series_tesouraria[ini], series_tesouraria[fim]
        variacao = b - a
        saida.append(VariacaoTesouraria(ini, fim, a, b, variacao, max(Decimal(0), -variacao)))
    return saida
