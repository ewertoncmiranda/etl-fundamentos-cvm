"""Liquidez e microestrutura por ativo e pregao (Plano OPR, OPR-ETL-1; DEC-OPR-1).

Puro: recebe os pregoes do mercado e a serie do ativo ja carregados (COTAHIST) e devolve as
metricas brutas de `ativo_liquidez_diaria`. Quem classifica a faixa (ALTA/MEDIA/INSUFICIENTE) e
decide e o gerar-insights. Regras (SPEC do ETL, "Metricas fixadas"):

- so pregoes ATE a data de referencia (inclusive): nada olha o futuro;
- medias de 21/63 pregoes contam os pregoes do MERCADO: dia sem negocio no ativo entra como 0;
- ativo listado ha menos de 63 pregoes do mercado: metricas de 63d sao None com motivo, nunca
  parciais; ausente e None com motivo, nunca 0.
"""

from __future__ import annotations

import math
import statistics
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

VERSAO_CALCULO = "LIQ-2026.10.10-1"
JANELA_CURTA, JANELA_LONGA, JANELA_ATR = 21, 63, 14
MINIMO_DIAS_SPREAD = 20
MINIMO_RETORNOS_VOL = 42  # 2/3 da janela: menos que isso, a volatilidade nao diz nada
DIAS_UTEIS_ANO = 252
AJUSTE_BRUTA = "BRUTA"

HISTORICO_INSUFICIENTE = "historico_insuficiente"


@dataclass(frozen=True)
class PregaoAtivo:
    data: date
    abertura: Decimal | None
    maxima: Decimal | None
    minima: Decimal | None
    fechamento: Decimal | None
    preco_medio: Decimal | None
    melhor_compra: Decimal | None
    melhor_venda: Decimal | None
    volume_financeiro: Decimal | None
    numero_negocios: int | None


@dataclass
class MetricaLiquidez:
    simbolo: str
    data_pregao: date
    volume_financeiro_medio_21d: Decimal | None = None
    volume_financeiro_medio_63d: Decimal | None = None
    negocios_medio_63d: Decimal | None = None
    presenca_63d: Decimal | None = None
    spread_mediano_63d: Decimal | None = None
    atr14: Decimal | None = None
    volatilidade_63d: Decimal | None = None
    percentil_volatilidade: Decimal | None = None
    dias_sem_preco_63d: int | None = None
    ajuste_serie: str = AJUSTE_BRUTA
    motivos_ausencia: dict[str, str] = field(default_factory=dict)
    versao_calculo: str = VERSAO_CALCULO


def _d(valor: float | Decimal | int, casas: int) -> Decimal:
    return Decimal(str(valor)).quantize(Decimal(1).scaleb(-casas))


def _ausente(m: MetricaLiquidez, coluna: str, motivo: str) -> None:
    setattr(m, coluna, None)
    m.motivos_ausencia[coluna] = motivo


def calcular(
    simbolo: str,
    data_ref: date,
    pregoes_mercado: list[date],
    serie: list[PregaoAtivo],
) -> MetricaLiquidez | None:
    """Metricas do ativo em `data_ref`. `pregoes_mercado` e `serie` em ordem crescente de data.

    None quando o ativo nao negociou em nenhum dos ultimos 63 pregoes (nao ha o que medir).
    """
    fim = bisect_right(pregoes_mercado, data_ref)
    if fim == 0:
        return None
    janela63 = pregoes_mercado[max(0, fim - JANELA_LONGA):fim]
    janela21 = pregoes_mercado[max(0, fim - JANELA_CURTA):fim]
    corte = bisect_right([p.data for p in serie], data_ref)
    serie = serie[:corte]  # nada depois da data de referencia
    if not serie:
        return None
    por_dia = {p.data: p for p in serie}
    if not any(d in por_dia for d in janela63):
        return None

    m = MetricaLiquidez(simbolo, data_ref)
    historico_ok = len(janela63) == JANELA_LONGA and serie[0].data <= janela63[0]

    def financeiro(d: date) -> Decimal:
        p = por_dia.get(d)
        return (p.volume_financeiro or Decimal(0)) if p else Decimal(0)

    # 21d precisa de 21 pregoes do mercado e do ativo listado no inicio da janela.
    if len(janela21) == JANELA_CURTA and serie[0].data <= janela21[0]:
        m.volume_financeiro_medio_21d = _d(sum(map(financeiro, janela21)) / JANELA_CURTA, 2)
    else:
        _ausente(m, "volume_financeiro_medio_21d", HISTORICO_INSUFICIENTE)

    if historico_ok:
        presentes = [d for d in janela63 if d in por_dia]
        m.volume_financeiro_medio_63d = _d(sum(map(financeiro, janela63)) / JANELA_LONGA, 2)
        m.negocios_medio_63d = _d(
            Decimal(sum((por_dia[d].numero_negocios or 0) for d in presentes)) / JANELA_LONGA, 2)
        m.presenca_63d = _d(Decimal(len(presentes)) / JANELA_LONGA, 8)
        m.dias_sem_preco_63d = sum(
            1 for d in janela63 if d not in por_dia or por_dia[d].fechamento is None)
        _spread(m, [por_dia[d] for d in presentes])
        _volatilidade(m, [por_dia[d] for d in presentes])
    else:
        for coluna in ("volume_financeiro_medio_63d", "negocios_medio_63d", "presenca_63d",
                       "dias_sem_preco_63d", "spread_mediano_63d", "volatilidade_63d"):
            _ausente(m, coluna, HISTORICO_INSUFICIENTE)

    _atr(m, serie)
    return m


def _spread(m: MetricaLiquidez, pregoes: list[PregaoAtivo]) -> None:
    valores = [
        (p.melhor_venda - p.melhor_compra) / p.preco_medio
        for p in pregoes
        if p.melhor_venda and p.melhor_compra and p.preco_medio and p.preco_medio > 0
        and p.melhor_venda >= p.melhor_compra
    ]
    if len(valores) < MINIMO_DIAS_SPREAD:
        _ausente(
            m,
            "spread_mediano_63d",
            f"ofertas_em_{len(valores)}_dias_minimo_{MINIMO_DIAS_SPREAD}",
        )
        return
    m.spread_mediano_63d = _d(statistics.median(valores), 8)


def _volatilidade(m: MetricaLiquidez, pregoes: list[PregaoAtivo]) -> None:
    fech = [float(p.fechamento) for p in pregoes if p.fechamento and p.fechamento > 0]
    retornos = [math.log(b / a) for a, b in zip(fech, fech[1:], strict=False)]
    if len(retornos) < MINIMO_RETORNOS_VOL:
        _ausente(m, "volatilidade_63d", f"retornos_{len(retornos)}_minimo_{MINIMO_RETORNOS_VOL}")
        return
    m.volatilidade_63d = _d(statistics.stdev(retornos) * math.sqrt(DIAS_UTEIS_ANO), 8)


def _atr(m: MetricaLiquidez, serie: list[PregaoAtivo]) -> None:
    """True range medio dos ultimos 14 pregoes do proprio ativo (precisa do fechamento anterior)."""
    validos = [p for p in serie if p.maxima is not None and p.minima is not None and p.fechamento]
    if len(validos) < JANELA_ATR + 1:
        _ausente(m, "atr14", HISTORICO_INSUFICIENTE)
        return
    ultimos = validos[-(JANELA_ATR + 1):]
    faixas = [
        max(atual.maxima - atual.minima, abs(atual.maxima - ant.fechamento),
            abs(atual.minima - ant.fechamento))
        for ant, atual in zip(ultimos, ultimos[1:], strict=False)
    ]
    m.atr14 = _d(sum(faixas) / JANELA_ATR, 6)


def preencher_percentis(metricas: list[MetricaLiquidez]) -> None:
    """Percentil da volatilidade no universo do mesmo pregao.

    Mede a fracao do universo com volatilidade menor ou igual a do ativo.
    """
    com_vol = sorted(m.volatilidade_63d for m in metricas if m.volatilidade_63d is not None)
    total = len(com_vol)
    for m in metricas:
        if m.volatilidade_63d is None:
            _ausente(m, "percentil_volatilidade", "sem_volatilidade")
        elif total:
            posicao = Decimal(bisect_right(com_vol, m.volatilidade_63d))
            m.percentil_volatilidade = _d(posicao / total, 8)
