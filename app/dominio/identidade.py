"""Identidade estavel do ativo quando o ticker muda de codigo.

O FCA sozinho nao liga ticker a CNPJ de forma confiavel: a Eletrobras virou
AXIA3 e o FCA ainda diz ELET3; a CSN aparece com o codigo "4030" e a Marfrig
com "ADR". A tabela ativo_identidade (curadoria, infra V6) diz qual e o
codigo canonico de cada empresa e qual CNPJ usar; o FCA cobre o resto.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.dominio.modelo import Ticker


@dataclass(frozen=True)
class Identidade:
    simbolo: str
    simbolo_canonico: str
    cnpj: str | None
    continuidade_preco: bool


def resolver_tickers(
    simbolos: list[str],
    tickers_fca: dict[str, Ticker],
    identidades: dict[str, Identidade],
    cnpjs_conhecidos: dict[str, str] | None = None,
) -> tuple[dict[str, Ticker], list[str]]:
    """simbolo pedido -> Ticker com o CNPJ certo, e os que ficaram sem CNPJ.

    Ordem: curadoria (resolve renomeacao e codigo sujo do FCA), depois o
    proprio FCA, depois um codigo antigo do mesmo papel que o FCA conheca
    (o FCA de 2019 so conhece ELET3, nunca AXIA3), e por fim o CNPJ ja
    gravado em cvm_ticker - o FCA de 2016/2017 nao traz o ticker da maioria
    das empresas, mas o CNPJ de um ticker nao muda.
    """
    resolvidos: dict[str, Ticker] = {}
    ausentes: list[str] = []
    for simbolo in simbolos:
        do_fca = tickers_fca.get(simbolo)
        identidade = identidades.get(simbolo)
        if identidade and identidade.cnpj:
            resolvidos[simbolo] = Ticker(
                simbolo=simbolo,
                cnpj=identidade.cnpj,
                tipo_valor_mobiliario=do_fca.tipo_valor_mobiliario if do_fca else "Curadoria",
                mercado="Bolsa",
            )
            continue
        if do_fca:
            resolvidos[simbolo] = do_fca
            continue
        antigo = next(
            (
                tickers_fca[i.simbolo]
                for i in identidades.values()
                if i.simbolo_canonico == simbolo
                and i.simbolo != simbolo
                and i.continuidade_preco
                and i.simbolo in tickers_fca
            ),
            None,
        )
        if antigo:
            resolvidos[simbolo] = Ticker(
                simbolo=simbolo,
                cnpj=antigo.cnpj,
                tipo_valor_mobiliario=antigo.tipo_valor_mobiliario,
                mercado="Bolsa",
            )
        elif cnpjs_conhecidos and simbolo in cnpjs_conhecidos:
            resolvidos[simbolo] = Ticker(
                simbolo=simbolo, cnpj=cnpjs_conhecidos[simbolo], mercado="Bolsa"
            )
        else:
            ausentes.append(simbolo)
    return resolvidos, ausentes


def codigos_negociados(simbolos: list[str], identidades: dict[str, Identidade]) -> set[str]:
    """Canonicos + codigos antigos do mesmo papel: o que procurar no COTAHIST.

    Em 2020 a Eletrobras negociava como ELET3; sem o alias, o backtest da AXIA3
    comecaria em 2025.
    """
    codigos = set(simbolos)
    for identidade in identidades.values():
        if identidade.simbolo_canonico in codigos and identidade.continuidade_preco:
            codigos.add(identidade.simbolo)
    return codigos
