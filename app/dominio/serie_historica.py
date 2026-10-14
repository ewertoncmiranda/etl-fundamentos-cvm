"""Modelo puro de cotacoes diarias da B3 (candles e opcoes)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class CandleB3:
    simbolo: str
    data_pregao: date
    abertura: Decimal
    maxima: Decimal
    minima: Decimal
    fechamento: Decimal
    volume: int
    numero_negocios: int
    volume_financeiro: Decimal
    # C3: NOMRES pos 28-39 (1-based). Util como fallback de nome para
    # instrumentos sem cadastro CVM (CRIs, FIIs recentes, BDRs).
    nome_resumido: str | None = None


@dataclass(frozen=True)
class OpcaoB3:
    """Cotacao diaria de uma opcao da B3, lida do COTAHIST.

    Todos os campos opcionais sao None quando ausentes no registro, nunca zero.
    indice_correcao (C1/Phase-0): "0"=sem correcao, "1"=SELIC, "2"=IGP-M.
    Opcoes com indice != "0" tem strike que muda diariamente; gravar sem
    este campo produz break-even incorreto em silencio.
    """

    simbolo: str
    bdi: str              # "12"=call, "14"=put (COTAHIST pos 11-12)
    data_pregao: date
    data_vencimento: date
    preco_exercicio: Decimal
    abertura: Decimal | None
    maxima: Decimal | None
    minima: Decimal | None
    fechamento: Decimal | None
    preco_medio: Decimal | None
    volume: int | None
    numero_negocios: int | None
    volume_financeiro: Decimal | None
    fator_cotacao: int
    isin: str | None
    ativo_objeto: str | None       # ticker do subjacente (preenchido pela validacao)
    tipo_opcao: str | None         # "CALL" ou "PUT"
    status_validacao: str          # "VALIDA", "REJEITADA", "INCOMPLETA"
    motivo_rejeicao: str | None
    # C1 Phase-0: INDOPC pos 202 (1-based), 1 char
    indice_correcao: str | None = None
