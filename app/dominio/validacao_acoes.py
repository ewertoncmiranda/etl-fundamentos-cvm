"""Checagem da quantidade de acoes entre anos da mesma empresa.

A quantidade de acoes e o denominador de LPA e VPA, e a CVM nao a entrega
com unidade confiavel: o DFP da VALE declara milhares em alguns anos e
unidades em outros, e quando o FRE do ano falta nao ha com o que cruzar
(VALE3 2023 saiu com LPA de R$ 9.288). Um ano so nao revela o erro; a serie
da empresa revela.

Duas regras, de proposito conservadoras:
  - fator entre 500 e 2000 contra a mediana da empresa: e unidade (milhar),
    nao evento societario - nenhum desdobramento e de 1000 para 1. Corrige.
  - pico isolado: o ano difere 5x ou mais dos DOIS vizinhos, que concordam
    entre si. Desdobramento persiste nos anos seguintes; pico isolado e dado
    ruim. Nao da para saber o valor certo, entao anula LPA e VPA.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import median

FAIXA_MILHAR = (500, 2000)
FATOR_PICO = 5.0
CONCORDANCIA_VIZINHOS = 1.5


@dataclass(frozen=True)
class Correcao:
    periodo: date
    tipo_periodo: str
    fator: float | None  # multiplica a quantidade de acoes; None = anular LPA/VPA
    motivo: str


def conferir_acoes(
    anuais: list[tuple[date, int]], outros: list[tuple[date, str, int]] | None = None
) -> list[Correcao]:
    """anuais: (periodo, acoes) dos balancos anuais; outros: (periodo, tipo, acoes)
    de TTM/trimestrais, conferidos so pela regra da unidade."""
    serie = sorted((p, a) for p, a in anuais if a and a > 0)
    if len(serie) < 3:
        return []
    referencia = median(a for _, a in serie)
    correcoes: list[Correcao] = []

    def unidade(periodo: date, tipo: str, acoes: int) -> Correcao | None:
        razao = referencia / acoes
        if FAIXA_MILHAR[0] <= razao <= FAIXA_MILHAR[1]:
            return Correcao(
                periodo, tipo, 1000.0, f"acoes em milhar (mediana/ano={razao:.0f}); x1000"
            )
        if FAIXA_MILHAR[0] <= 1 / razao <= FAIXA_MILHAR[1]:
            return Correcao(
                periodo, tipo, 0.001, f"acoes 1000x acima da mediana ({1 / razao:.0f}); /1000"
            )
        return None

    corrigidos: dict[date, float] = {}
    for periodo, acoes in serie:
        correcao = unidade(periodo, "ANUAL", acoes)
        if correcao:
            correcoes.append(correcao)
            corrigidos[periodo] = acoes * (correcao.fator or 1)

    ajustada = [(p, corrigidos.get(p, a)) for p, a in serie]
    for i in range(1, len(ajustada) - 1):
        (_, antes), (periodo, atual), (_, depois) = ajustada[i - 1], ajustada[i], ajustada[i + 1]
        vizinhos_concordam = max(antes, depois) / min(antes, depois) <= CONCORDANCIA_VIZINHOS
        distante = min(
            max(atual, antes) / min(atual, antes), max(atual, depois) / min(atual, depois)
        )
        if vizinhos_concordam and distante >= FATOR_PICO and periodo not in corrigidos:
            correcoes.append(
                Correcao(
                    periodo,
                    "ANUAL",
                    None,
                    f"quantidade de acoes isolada ({distante:.1f}x os vizinhos)",
                )
            )

    for periodo, tipo, acoes in outros or []:
        if acoes and acoes > 0:
            correcao = unidade(periodo, tipo, acoes)
            if correcao:
                correcoes.append(correcao)
    return correcoes
