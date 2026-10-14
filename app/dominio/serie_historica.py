"""Modelo puro de cotacoes diarias da B3 (candles e opcoes)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class CandleB3:
    """Precos ja divididos pelo fator de cotacao (FATCOT): R$ por acao."""

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
    # C4: MODREF pos 53-56 (1-based). Moeda de referencia da cotacao.
    # "USD " = BDR; "BRL " = ativo denominado em reais. Padrao "BRL".
    moeda_referencia: str = "BRL"
    # ESPECI cru ("ON  EB", "PN  EJ N2") e o sufixo de dia ex, quando ha.
    especificacao: str | None = None
    marca_ex: str | None = None
    fator_cotacao: int = 1
    preco_medio: Decimal | None = None
    melhor_oferta_compra: Decimal | None = None
    melhor_oferta_venda: Decimal | None = None
    isin: str | None = None


@dataclass(frozen=True)
class OpcaoB3:
    """Cotacao diaria de opcao da B3 no COTAHIST.

    A classificacao correta vem do tipo de mercado (TPMERC 070/080), nao do
    CODBDI isolado. Campos de validacao ficam opcionais para compatibilidade
    com bancos que ainda nao receberam a migration OPT-INFRA-1.
    """

    simbolo: str
    bdi: str
    data_pregao: date
    data_vencimento: date
    preco_exercicio: Decimal
    abertura: Decimal
    maxima: Decimal
    minima: Decimal
    fechamento: Decimal
    volume: int
    numero_negocios: int
    volume_financeiro: Decimal
    isin: str | None = None
    fator_cotacao: int = 1
    preco_medio: Decimal | None = None
    ativo_objeto: str | None = None
    tipo_opcao: str | None = None
    status_validacao: str = "VALIDA"
    motivo_rejeicao: str | None = None
    # C1 Phase-0: INDOPC pos 202 (1-based), 1 char
    indice_correcao: str | None = None
    # C2 Phase-2: PREOFC/PREOFV pos 122-134 / 135-147 (1-based)
    melhor_oferta_compra: Decimal | None = None
    melhor_oferta_venda: Decimal | None = None


def resumir_validacao_opcoes(opcoes: list[OpcaoB3]) -> dict[str, Any]:
    """Resumo deterministico da qualidade da cadeia de opcoes lida do COTAHIST."""
    motivos: dict[str, int] = {}
    prefixos: dict[str, int] = {}
    ativos_validos = set()
    vencimento_9999 = 0
    validos = 0
    for opcao in opcoes:
        if opcao.status_validacao == "VALIDA":
            validos += 1
            if opcao.ativo_objeto:
                ativos_validos.add(opcao.ativo_objeto)
            continue
        motivo = opcao.motivo_rejeicao or "motivo_ausente"
        motivos[motivo] = motivos.get(motivo, 0) + 1
        prefixo = opcao.simbolo[:4]
        prefixos[prefixo] = prefixos.get(prefixo, 0) + 1
        if opcao.data_vencimento == date(9999, 12, 31):
            vencimento_9999 += 1
    return {
        "total": len(opcoes),
        "validos": validos,
        "invalidos": len(opcoes) - validos,
        "vencimento_9999": vencimento_9999,
        "ativos_com_cadeia": sorted(ativos_validos),
        "motivos": dict(sorted(motivos.items())),
        "prefixos_suspeitos": dict(
            sorted(prefixos.items(), key=lambda item: (-item[1], item[0]))[:10]
        ),
    }
