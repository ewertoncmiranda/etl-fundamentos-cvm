"""Le o CSV aberto de precos e taxas do Tesouro Direto (Tesouro Transparente).

Arquivo unico com todo o historico desde 2002 (~15 MB, ~180 mil linhas),
';' e latin-1, decimais com virgula e datas dd/mm/aaaa:
Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;
PU Compra Manha;PU Venda Manha;PU Base Manha

A NTN-B ("Tesouro IPCA+" e "... com Juros Semestrais") paga juro real: e o
custo de oportunidade contra o qual o earnings yield de uma acao e comparado
(FONTES-GES-1) e o Y do Graham ajustado.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

TIPOS_JURO_REAL = frozenset({"Tesouro IPCA+", "Tesouro IPCA+ com Juros Semestrais"})
# DEC-FONTES-3: a referencia e a NTN-B com prazo mais perto de 5 anos, duration
# comparavel ao horizonte de uma acao.
PRAZO_REFERENCIA_ANOS = 5


@dataclass(frozen=True)
class TaxaTituloPublico:
    tipo: str
    vencimento: date
    data_base: date
    taxa_compra: Decimal | None
    taxa_venda: Decimal | None
    pu_compra: Decimal | None
    pu_venda: Decimal | None
    pu_base: Decimal | None

    @property
    def juro_real(self) -> bool:
        return self.tipo in TIPOS_JURO_REAL


def ler_csv(conteudo: bytes, desde: date | None = None) -> list[TaxaTituloPublico]:
    """Linhas validas do CSV; linha com data ou tipo quebrado e descartada.

    desde: corta o historico antigo (o arquivo traz desde 2002)."""
    leitor = csv.DictReader(io.StringIO(conteudo.decode("latin-1")), delimiter=";")
    taxas = []
    for linha in leitor:
        tipo = (linha.get("Tipo Titulo") or "").strip()
        vencimento = _data(linha.get("Data Vencimento"))
        data_base = _data(linha.get("Data Base"))
        if not tipo or vencimento is None or data_base is None:
            continue
        if desde is not None and data_base < desde:
            continue
        taxas.append(
            TaxaTituloPublico(
                tipo=tipo,
                vencimento=vencimento,
                data_base=data_base,
                taxa_compra=_decimal(linha.get("Taxa Compra Manha")),
                taxa_venda=_decimal(linha.get("Taxa Venda Manha")),
                pu_compra=_decimal(linha.get("PU Compra Manha")),
                pu_venda=_decimal(linha.get("PU Venda Manha")),
                pu_base=_decimal(linha.get("PU Base Manha")),
            )
        )
    return taxas


def ntnb_referencia(
    taxas: list[TaxaTituloPublico], data_base: date | None = None
) -> TaxaTituloPublico | None:
    """NTN-B do dia com vencimento mais perto de PRAZO_REFERENCIA_ANOS.

    Sem data_base, usa a data mais recente que tenha NTN-B com taxa. Usa a
    taxa de compra (o que o investidor recebe); titulo sem taxa nao conta."""
    candidatas = [t for t in taxas if t.juro_real and t.taxa_compra is not None]
    if data_base is None:
        if not candidatas:
            return None
        data_base = max(t.data_base for t in candidatas)
    do_dia = [t for t in candidatas if t.data_base == data_base]
    if not do_dia:
        return None
    alvo = date(data_base.year + PRAZO_REFERENCIA_ANOS, data_base.month, min(data_base.day, 28))
    return min(do_dia, key=lambda t: (abs((t.vencimento - alvo).days), t.vencimento))


def _data(texto: str | None) -> date | None:
    try:
        return datetime.strptime((texto or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _decimal(texto: str | None) -> Decimal | None:
    bruto = (texto or "").strip().replace(".", "").replace(",", ".")
    if not bruto:
        return None
    try:
        return Decimal(bruto)
    except InvalidOperation:
        return None
