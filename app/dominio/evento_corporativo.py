"""Desdobramento, grupamento e bonificacao inferidos (plano LAC, L2). Puro.

O FRE aberto nao tem tabela de desdobramentos, e o COTAHIST nao traz a
proporcao - so marca o dia ex no ESPECI. Tres evidencias, cada uma de uma
fonte:

1. Data (COTAHIST): primeiro pregao de uma sequencia com marca societaria.
   Layout oficial da B3 (SeriesHistoricas_Layout, rev. 02 de 05/10/2020):
   EB ex-bonificacao, EG ex-grupamento; combinadas (EDB, EJB, EBG...)
   tambem valem. EX nao esta na tabela, mas aparece nos dados em
   desdobramentos (VIVT3 em 15/04/2025, 1:2) misturado a proventos - entra
   como candidato e a proporcao do capital decide. A B3 nao tem marca de
   desdobramento: na pratica ele vem como EB (BBAS3 em 16/04/2024, 1:2).
2. Proporcao (CVM): acoes na composicao de capital posterior / anterior.
   Composicao anual (DFP): emissao ou recompra no mesmo ano desloca a
   razao, por isso ela e aproximada pela fracao simples mais proxima e so
   vale se ficar a menos de TOLERANCIA_CAPITAL dela.
3. Preco (COTAHIST): fechamento anterior / abertura do dia ex, que entra
   na confianca.

Salto de preco sem marca NAO vira evento: e queda real (AMER3 em 01/2023).
Dois eventos no mesmo ano (RCSL3 em 2026: EB em marco, EG em outubro)
misturam as razoes e saem rejeitados - correcao via origem MANUAL.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction

TIPO_DESDOBRAMENTO = "DESDOBRAMENTO"
TIPO_GRUPAMENTO = "GRUPAMENTO"
TIPO_BONIFICACAO = "BONIFICACAO"
ORIGEM_INFERIDA = "INFERIDO_CVM_COTAHIST"

# Letras da marca ex que indicam evento societario (ver docstring).
LETRAS_SOCIETARIAS = frozenset("BGX")

# Abaixo de 3:2 a variacao e bonificacao (percentual); acima, desdobramento.
LIMIAR_DESDOBRAMENTO = 1.5
LIMIAR_SO_INTEIROS = 3
# Menor bonificacao reconhecida (5%); abaixo disso, ruido do capital anual.
MENOR_EVENTO = Fraction(105, 100)
MENOR_EVENTO_INVERSO = 1 / MENOR_EVENTO
TOLERANCIA_CAPITAL = 0.05
TOLERANCIA_CAPITAL_DESDOBRAMENTO = 0.10
TOLERANCIA_PRECO_ALTA = 0.03
TOLERANCIA_PRECO_MEDIA = 0.10
FRACAO_MINIMA_DO_MOVIMENTO = 0.5
CONFIANCA_ALTA = Decimal("1.0")
CONFIANCA_MEDIA = Decimal("0.8")


@dataclass(frozen=True)
class PregaoMarcado:
    simbolo: str
    data: date
    marca_ex: str | None
    fechamento_anterior: Decimal | None
    abertura: Decimal | None
    # Marca do pregao anterior do mesmo simbolo: diz se este e o primeiro
    # dia da sequencia sem precisar carregar a serie inteira.
    marca_anterior: str | None = None


@dataclass(frozen=True)
class Composicao:
    dt_refer: date
    total: int
    ordinarias: int = 0
    preferenciais: int = 0

    def da_especie(self, simbolo: str) -> int:
        """ON para final 3, PN para 4/5/6; sem a especie (DFP ate 2019 ou
        carga anterior a TASK-E12), o total."""
        final = simbolo[4:]
        if final == "3" and self.ordinarias:
            return self.ordinarias
        if final in ("4", "5", "6") and self.preferenciais:
            return self.preferenciais
        return self.total


@dataclass(frozen=True)
class Candidato:
    simbolo: str
    data: date
    marca_ex: str
    razao_preco: float | None


@dataclass(frozen=True)
class EventoInferido:
    simbolo: str
    cnpj: str
    data_efeito: date
    tipo: str
    fator_acoes: Fraction
    confianca: Decimal
    evidencia: dict


@dataclass(frozen=True)
class Rejeicao:
    simbolo: str
    data: date
    marca_ex: str
    motivo: str


def e_societaria(marca: str | None) -> bool:
    if not marca:
        return False
    return any(letra in LETRAS_SOCIETARIAS for letra in marca[1:])


def e_acao(simbolo: str) -> bool:
    """Acao ON/PN (final 3 a 6). Units (11), BDRs e recibos ficam de fora."""
    return len(simbolo) == 5 and simbolo[4] in "3456"


def candidatos(pregoes: Iterable[PregaoMarcado]) -> list[Candidato]:
    """Primeiro pregao de cada sequencia com marca societaria.

    Varios dias seguidos com a marca sao um evento so (RCSL3: EB em 10 e
    11/03/2026): o dia so conta se o pregao anterior nao tinha marca.
    """
    return [
        Candidato(
            simbolo=p.simbolo,
            data=p.data,
            marca_ex=p.marca_ex or "",
            razao_preco=_razao(p.fechamento_anterior, p.abertura),
        )
        for p in pregoes
        if e_acao(p.simbolo) and e_societaria(p.marca_ex) and not e_societaria(p.marca_anterior)
    ]


def fracao_simples(razao: float) -> Fraction:
    """A proporcao que uma assembleia aprovaria perto de `razao`.

    Desdobramento e grupamento (a partir de 3:2) sao inteiros (2:1, 10:1,
    125:1 da PDGR3) ou, abaixo de 3:1, meios (3:2, 5:2); bonificacao e
    percentual inteiro
    (5%, 10%, 33%). A fracao "mais proxima" com denominador livre inventa
    proporcoes (21/19, 199/20) a partir do ruido do capital anual.
    """
    if razao <= 0:
        raise ValueError("razao de acoes precisa ser positiva")
    if razao < 1:
        return 1 / fracao_simples(1 / razao)
    if razao >= LIMIAR_SO_INTEIROS:
        return Fraction(round(razao))
    if razao >= LIMIAR_DESDOBRAMENTO:
        return Fraction(round(razao * 2), 2)
    return 1 + Fraction(round((razao - 1) * 100), 100)


def inferir(
    candidato: Candidato,
    cnpj: str,
    composicoes: Sequence[Composicao],
) -> EventoInferido | Rejeicao:
    """Casa a marca com a variacao do capital entre a DFP anterior e a
    posterior ao dia ex; o preco do dia ex da a confianca."""
    antes = max(
        (c for c in composicoes if c.dt_refer < candidato.data),
        key=lambda c: c.dt_refer, default=None,
    )
    depois = min(
        (c for c in composicoes if c.dt_refer >= candidato.data),
        key=lambda c: c.dt_refer, default=None,
    )
    if antes is None or depois is None:
        return _rejeitar(candidato, "sem composicao de capital antes e depois do dia ex")
    acoes_antes = antes.da_especie(candidato.simbolo)
    acoes_depois = depois.da_especie(candidato.simbolo)
    if acoes_antes <= 0 or acoes_depois <= 0:
        return _rejeitar(candidato, "composicao de capital sem quantidade de acoes")

    razao_capital = acoes_depois / acoes_antes
    fator = fracao_simples(razao_capital)
    tolerancia_capital = TOLERANCIA_CAPITAL
    preco = candidato.razao_preco
    if (
        preco
        and _e_desdobramento_ou_grupamento(razao_capital)
        and _e_desdobramento_ou_grupamento(preco)
        and (preco > 1) == (razao_capital > 1)
    ):
        # Desdobramento grande no mesmo ano de um follow-on (MGLU3 2019:
        # 1:8, capital 8,52): o capital sozinho escolhe a proporcao errada.
        # A media geometrica com o preco do dia ex acerta, e o capital pode
        # se afastar mais dela.
        fator = fracao_simples(math.sqrt(razao_capital * preco))
        tolerancia_capital = TOLERANCIA_CAPITAL_DESDOBRAMENTO
    if MENOR_EVENTO_INVERSO < fator < MENOR_EVENTO:
        # Emissao ou recompra no ano mexe o capital em poucos %, e o ruido
        # do preco num dia (3%) confirmaria qualquer coisa nessa faixa.
        return _rejeitar(
            candidato, f"capital quase estavel (razao {razao_capital:.4f}): provento, nao evento"
        )
    if abs(razao_capital / float(fator) - 1) > tolerancia_capital:
        return _rejeitar(
            candidato,
            f"razao do capital {razao_capital:.4f} longe de fracao simples ({fator})",
        )

    confianca = _confianca(candidato.razao_preco, fator)
    if confianca is None:
        return _rejeitar(
            candidato,
            f"preco do dia ex nao confirma: razao {candidato.razao_preco} x fator {fator}",
        )
    return EventoInferido(
        simbolo=candidato.simbolo,
        cnpj=cnpj,
        data_efeito=candidato.data,
        tipo=_tipo(fator),
        fator_acoes=fator,
        confianca=confianca,
        evidencia={
            "marca_ex": candidato.marca_ex,
            "composicao_antes": {"dt_refer": antes.dt_refer.isoformat(), "acoes": acoes_antes},
            "composicao_depois": {"dt_refer": depois.dt_refer.isoformat(), "acoes": acoes_depois},
            "razao_capital": round(razao_capital, 6),
            "razao_preco": candidato.razao_preco,
            "fator": f"{fator.numerator}/{fator.denominator}",
        },
    )


def _confianca(razao_preco: float | None, fator: Fraction) -> Decimal | None:
    """Alta: preco a ate 3% do fator. Media (so desdobramento e grupamento):
    ate 10%, desde que o preco tenha andado ao menos metade do movimento,
    no mesmo sentido (MGLU3 2019: 1:8 com preco 7,75)."""
    if razao_preco is None or razao_preco <= 0:
        return None
    desvio = abs(razao_preco / float(fator) - 1)
    if desvio <= TOLERANCIA_PRECO_ALTA:
        return CONFIANCA_ALTA
    # Bonificacao so com o preco a 3%: o capital anual mistura a
    # bonificacao com outros aumentos do ano (BBDC4 2016: preco 1,109,
    # capital 1,21), e entre os dois o preco do dia ex e a evidencia limpa.
    if not _e_desdobramento_ou_grupamento(float(fator)):
        return None
    capturado = math.log(razao_preco) / math.log(float(fator))
    if desvio <= TOLERANCIA_PRECO_MEDIA and capturado >= FRACAO_MINIMA_DO_MOVIMENTO:
        return CONFIANCA_MEDIA
    return None


def _e_desdobramento_ou_grupamento(razao: float) -> bool:
    return razao >= LIMIAR_DESDOBRAMENTO or razao <= 1 / LIMIAR_DESDOBRAMENTO


def _tipo(fator: Fraction) -> str:
    if fator < 1:
        return TIPO_GRUPAMENTO
    # A partir de 3:2 e desdobramento; abaixo, bonificacao percentual.
    return TIPO_DESDOBRAMENTO if fator >= LIMIAR_DESDOBRAMENTO else TIPO_BONIFICACAO


def _razao(anterior: Decimal | None, abertura: Decimal | None) -> float | None:
    if not anterior or not abertura:
        return None
    return round(float(anterior) / float(abertura), 6)


def _rejeitar(candidato: Candidato, motivo: str) -> Rejeicao:
    return Rejeicao(candidato.simbolo, candidato.data, candidato.marca_ex, motivo)


def um_por_intervalo(
    eventos: Sequence[EventoInferido],
) -> tuple[list[EventoInferido], list[Rejeicao]]:
    """Uma variacao de capital explica um evento so por simbolo.

    ITSA4 em 2018: EX em fevereiro e EDB em junho, ambos casando com a mesma
    razao do capital (dez/2017 -> dez/2018). Gravar os dois ajustaria o
    preco duas vezes. Fica o de maior confianca e, no empate, o de preco
    mais perto do fator; os outros saem com o motivo.
    """
    grupos: dict[tuple, list[EventoInferido]] = {}
    for evento in eventos:
        chave = (
            evento.simbolo,
            evento.evidencia["composicao_antes"]["dt_refer"],
            evento.evidencia["composicao_depois"]["dt_refer"],
        )
        grupos.setdefault(chave, []).append(evento)

    mantidos: list[EventoInferido] = []
    descartados: list[Rejeicao] = []
    for grupo in grupos.values():
        melhor = max(grupo, key=_qualidade)
        mantidos.append(melhor)
        descartados.extend(
            Rejeicao(
                e.simbolo, e.data_efeito, e.evidencia["marca_ex"],
                f"outro candidato explica a mesma variacao de capital ({melhor.data_efeito})",
            )
            for e in grupo
            if e is not melhor
        )
    return sorted(mantidos, key=lambda e: (e.simbolo, e.data_efeito)), descartados


def _qualidade(evento: EventoInferido) -> tuple[Decimal, float]:
    preco = evento.evidencia.get("razao_preco") or 0.0
    desvio = abs(preco / float(evento.fator_acoes) - 1) if preco else 1.0
    return evento.confianca, -desvio
