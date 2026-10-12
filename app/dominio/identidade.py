"""Identidade estavel do ativo quando o ticker muda de codigo.

O FCA sozinho nao liga ticker a CNPJ de forma confiavel: a Eletrobras virou
AXIA3 e o FCA ainda diz ELET3; a CSN aparece com o codigo "4030" e a Marfrig
com "ADR". A tabela ativo_identidade (curadoria, infra V6) diz qual e o
codigo canonico de cada empresa e qual CNPJ usar; o FCA cobre o resto.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.dominio.modelo import Ticker
from app.dominio.serie_historica import OpcaoB3


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


def canonizar_ativo_objeto_opcao(
    ativo_objeto: str | None,
    identidades: dict[str, Identidade],
) -> str | None:
    """Converte o prefixo de opcao para o prefixo canonico quando ha curadoria.

    O COTAHIST traz o codigo negociado no dia. Para opcoes antigas de empresas
    renomeadas, o prefixo tambem pode ser antigo (ex.: BVMF -> B3SA). A tabela
    `ativo_identidade` guarda essa ponte por ticker (`BVMF3 -> B3SA3`); aqui
    usamos so os quatro primeiros caracteres para alimentar `ativo_objeto`.
    """
    if not ativo_objeto:
        return None
    raiz = ativo_objeto.strip().upper()[:4]
    if len(raiz) != 4:
        return raiz or None
    for identidade in identidades.values():
        if (
            identidade.continuidade_preco
            and identidade.simbolo.strip().upper().startswith(raiz)
            and identidade.simbolo_canonico
        ):
            return identidade.simbolo_canonico.strip().upper()[:4]
    return raiz


def canonizar_opcoes(
    opcoes: list[OpcaoB3],
    identidades: dict[str, Identidade],
) -> list[OpcaoB3]:
    """Retorna opcoes com `ativo_objeto` canonico, preservando o simbolo negociado."""
    if not identidades:
        return opcoes
    saida: list[OpcaoB3] = []
    for opcao in opcoes:
        canonico = canonizar_ativo_objeto_opcao(opcao.ativo_objeto, identidades)
        ativo_atual = opcao.ativo_objeto.strip().upper() if opcao.ativo_objeto else None
        if canonico == ativo_atual:
            saida.append(opcao)
        else:
            saida.append(replace(opcao, ativo_objeto=canonico))
    return saida
