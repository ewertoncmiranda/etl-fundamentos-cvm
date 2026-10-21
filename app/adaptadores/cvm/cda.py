"""Leitor do CDA (composicao da carteira de fundos) da CVM - so acoes.

Le em streaming `cda_fi_BLC_4_{AAAAMM}.csv` filtrando TP_APLIC == "Ações" e
junta o PL de `cda_fi_PL_{AAAAMM}.csv`. Arquivos CONFID sao ignorados.
FII (DEC-FONTES-2) fica fora. Sem banco: leitor puro.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from app.adaptadores.cvm.leitor_pacote import LeitorDePacoteCvm

TP_APLIC_ACOES = "Ações"


@dataclass(frozen=True)
class PosicaoFundoAcao:
    competencia: date
    cnpj_fundo: str
    simbolo: str
    isin: str
    quantidade: Decimal
    valor_mercado: Decimal
    pl_fundo: Decimal | None


@dataclass(frozen=True)
class FluxoAtivo:
    simbolo: str
    fundos: int
    quantidade: Decimal
    variacao_quantidade: Decimal
    fundos_entraram: int
    fundos_sairam: int


def nome_pacote(competencia: str) -> str:
    return f"cda_fi_{competencia}.zip"


def so_digitos(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj or "")


def _decimal(texto: str | None) -> Decimal | None:
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        return Decimal(texto)
    except InvalidOperation:
        return None


def _data(texto: str | None) -> date | None:
    try:
        return date.fromisoformat((texto or "").strip()[:10])
    except ValueError:
        return None


def ler_cda_acoes(conteudo: bytes, competencia: str) -> Iterator[PosicaoFundoAcao]:
    """Gera as posicoes em acoes do mes `competencia` (AAAAMM), linha a linha.

    So o bloco 4 e o PL sao abertos; CONFID e demais blocos nunca sao lidos.
    """
    with LeitorDePacoteCvm(conteudo, nome_pacote(competencia)) as pacote:
        pl: dict[str, Decimal | None] = {}
        arquivo_pl = f"cda_fi_PL_{competencia}.csv"
        if pacote.tem(arquivo_pl):
            for l in pacote.linhas(arquivo_pl):
                pl[so_digitos(l.get("CNPJ_FUNDO_CLASSE") or "")] = _decimal(l.get("VL_PATRIM_LIQ"))

        for l in pacote.linhas(f"cda_fi_BLC_4_{competencia}.csv"):
            if (l.get("TP_APLIC") or "").strip() != TP_APLIC_ACOES:
                continue
            simbolo = (l.get("CD_ATIVO") or "").strip().upper()
            dt = _data(l.get("DT_COMPTC"))
            if not simbolo or dt is None:
                continue
            cnpj = so_digitos(l.get("CNPJ_FUNDO_CLASSE") or "")
            yield PosicaoFundoAcao(
                competencia=dt,
                cnpj_fundo=cnpj,
                simbolo=simbolo,
                isin=(l.get("CD_ISIN") or "").strip(),
                quantidade=_decimal(l.get("QT_POS_FINAL")) or Decimal(0),
                valor_mercado=_decimal(l.get("VL_MERC_POS_FINAL")) or Decimal(0),
                pl_fundo=pl.get(cnpj),
            )


def _por_simbolo(posicoes: Iterable[PosicaoFundoAcao]) -> dict[str, dict[str, Decimal]]:
    saida: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for p in posicoes:
        saida[p.simbolo][p.cnpj_fundo] += p.quantidade
    return saida


def fluxo_por_ativo(
    atual: Iterable[PosicaoFundoAcao], anterior: Iterable[PosicaoFundoAcao]
) -> dict[str, FluxoAtivo]:
    """Por simbolo: fundos, quantidade total, variacao e fundos que entraram/sairam."""
    agora, antes = _por_simbolo(atual), _por_simbolo(anterior)
    resultado: dict[str, FluxoAtivo] = {}
    for simbolo in agora.keys() | antes.keys():
        a, b = agora.get(simbolo, {}), antes.get(simbolo, {})
        total = sum(a.values(), Decimal(0))
        resultado[simbolo] = FluxoAtivo(
            simbolo=simbolo,
            fundos=len(a),
            quantidade=total,
            variacao_quantidade=total - sum(b.values(), Decimal(0)),
            fundos_entraram=len(a.keys() - b.keys()),
            fundos_sairam=len(b.keys() - a.keys()),
        )
    return resultado
