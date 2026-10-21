"""Leitor do VLMO (negociacao de administradores e controladores) da CVM.

Le `vlmo_cia_aberta_con_{ano}.csv` (movimentacoes) e o indice
`vlmo_cia_aberta_{ano}.csv` (Data_Entrega). So a ultima versao de cada
(CNPJ, Data_Referencia) e mantida. Sem banco: leitor puro.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from app.adaptadores.cvm.leitor_pacote import LeitorDePacoteCvm

COMPRA_A_VISTA = "Compra à vista"
VENDA_A_VISTA = "Venda à vista"
COMPRA_A_TERMO = "Compra à termo"
SINAL_POR_MOVIMENTACAO = {COMPRA_A_VISTA: 1, COMPRA_A_TERMO: 1, VENDA_A_VISTA: -1}
ATIVOS_DE_MERCADO = frozenset({"Ações", "Units"})


@dataclass(frozen=True)
class NegociacaoAdministrador:
    cnpj: str
    nome_companhia: str
    data_referencia: date
    versao: int
    data_entrega: date | None
    tipo_empresa: str
    empresa: str
    tipo_cargo: str
    tipo_movimentacao: str
    descricao_movimentacao: str
    tipo_operacao: str
    tipo_ativo: str
    caracteristica: str
    intermediario: str
    data_movimentacao: date | None
    quantidade: Decimal
    preco_unitario: Decimal | None
    volume: Decimal | None


@dataclass(frozen=True)
class CompraLiquida:
    quantidade: Decimal
    volume: Decimal | None


def nome_pacote(ano: int) -> str:
    return f"vlmo_cia_aberta_{ano}.zip"


def so_digitos(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj or "")


def _data(texto: str | None) -> date | None:
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        return date.fromisoformat(texto[:10])
    except ValueError:
        return None


def _decimal(texto: str | None) -> Decimal | None:
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        return Decimal(texto)
    except InvalidOperation:
        return None


def _positivo(valor: Decimal | None) -> Decimal | None:
    return valor if valor is not None and valor > 0 else None


def _texto(linha: dict[str, str], coluna: str) -> str:
    return (linha.get(coluna) or "").strip()


def ler_vlmo(conteudo: bytes, ano: int) -> list[NegociacaoAdministrador]:
    """Le o pacote anual e devolve so a ultima versao por (CNPJ, Data_Referencia)."""
    with LeitorDePacoteCvm(conteudo, nome_pacote(ano)) as pacote:
        entregas: dict[tuple[str, date, int], date | None] = {}
        indice = f"vlmo_cia_aberta_{ano}.csv"
        if pacote.tem(indice):
            for l in pacote.linhas(indice):
                ref = _data(l.get("Data_Referencia"))
                if ref is None:
                    continue
                chave = (so_digitos(_texto(l, "CNPJ_Companhia")), ref, int(l.get("Versao") or 0))
                entregas[chave] = _data(l.get("Data_Entrega"))

        por_chave: dict[tuple[str, date], list[NegociacaoAdministrador]] = {}
        versao_max: dict[tuple[str, date], int] = {}
        for l in pacote.linhas(f"vlmo_cia_aberta_con_{ano}.csv"):
            ref = _data(l.get("Data_Referencia"))
            if ref is None:
                continue
            cnpj = so_digitos(_texto(l, "CNPJ_Companhia"))
            versao = int(l.get("Versao") or 0)
            chave = (cnpj, ref)
            atual = versao_max.get(chave, -1)
            if versao < atual:
                continue
            if versao > atual:
                versao_max[chave] = versao
                por_chave[chave] = []
            por_chave[chave].append(
                NegociacaoAdministrador(
                    cnpj=cnpj,
                    nome_companhia=_texto(l, "Nome_Companhia"),
                    data_referencia=ref,
                    versao=versao,
                    data_entrega=entregas.get((cnpj, ref, versao)),
                    tipo_empresa=_texto(l, "Tipo_Empresa"),
                    empresa=_texto(l, "Empresa"),
                    tipo_cargo=_texto(l, "Tipo_Cargo"),
                    tipo_movimentacao=_texto(l, "Tipo_Movimentacao"),
                    descricao_movimentacao=_texto(l, "Descricao_Movimentacao"),
                    tipo_operacao=_texto(l, "Tipo_Operacao"),
                    tipo_ativo=_texto(l, "Tipo_Ativo"),
                    caracteristica=_texto(l, "Caracteristica_Valor_Mobiliario"),
                    intermediario=_texto(l, "Intermediario"),
                    data_movimentacao=_data(l.get("Data_Movimentacao")),
                    quantidade=_decimal(l.get("Quantidade")) or Decimal(0),
                    preco_unitario=_positivo(_decimal(l.get("Preco_Unitario"))),
                    volume=_positivo(_decimal(l.get("Volume"))),
                )
            )
    return [n for lista in por_chave.values() for n in lista]


def e_decisao_de_mercado(n: NegociacaoAdministrador) -> bool:
    return n.tipo_movimentacao in SINAL_POR_MOVIMENTACAO and n.tipo_ativo in ATIVOS_DE_MERCADO


def compra_liquida(
    negociacoes: Iterable[NegociacaoAdministrador], cnpj: str, desde: date, ate: date
) -> dict[str, CompraLiquida]:
    """Quantidade liquida (compras - vendas) e volume, por Tipo_Cargo, no periodo.

    O periodo usa Data_Movimentacao (ou Data_Referencia se vazia), inclusivo.
    Volume so e somado quando informado (> 0); fica None se nenhuma linha tiver.
    """
    alvo = so_digitos(cnpj)
    qtd: dict[str, Decimal] = defaultdict(Decimal)
    vol: dict[str, Decimal | None] = {}
    for n in negociacoes:
        if n.cnpj != alvo or not e_decisao_de_mercado(n):
            continue
        dia = n.data_movimentacao or n.data_referencia
        if not (desde <= dia <= ate):
            continue
        sinal = SINAL_POR_MOVIMENTACAO[n.tipo_movimentacao]
        qtd[n.tipo_cargo] += sinal * n.quantidade
        vol.setdefault(n.tipo_cargo, None)
        if n.volume is not None:
            vol[n.tipo_cargo] = (vol[n.tipo_cargo] or Decimal(0)) + sinal * n.volume
    return {cargo: CompraLiquida(qtd[cargo], vol[cargo]) for cargo in qtd}
