"""Conciliacao do fechamento da BRAPI (foto das 17:40) com o COTAHIST oficial.

A classificacao linha a linha (OK, DIVERGENTE_PRECO...) mora na view
vw_conciliacao_preco (infra V15): mudar a tolerancia la reclassifica o
historico inteiro. Aqui fica so a regra do dia - quando o conjunto merece
alerta - que e o que decide o codigo de saida do job.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

FONTE_CONCILIACAO = "CONCILIACAO_BRAPI_B3"

OK = "OK"
DIVERGENTE_PRECO = "DIVERGENTE_PRECO"
DIVERGENTE_VOLUME = "DIVERGENTE_VOLUME"
SEM_BRAPI = "SEM_BRAPI"
SEM_B3 = "SEM_B3"
PENDENTE = "PENDENTE"
GRAVE = "GRAVE"

# Acima disto o dia inteiro e suspeito, nao um ativo isolado.
TAXA_MAXIMA_DIVERGENCIA_PRECO = Decimal("0.02")


@dataclass(frozen=True)
class LinhaConciliacao:
    simbolo: str
    data_pregao: date
    divergencia: str
    severidade: str | None = None
    dif_fechamento_pct: Decimal | None = None
    idade_dado_min: int | None = None


@dataclass(frozen=True)
class ResumoConciliacao:
    data_pregao: date
    contagem: dict[str, int]
    graves: tuple[str, ...]

    @property
    def comparaveis(self) -> int:
        """Pares com os dois lados presentes: so neles a divergencia diz algo da fonte."""
        return sum(self.contagem.get(c, 0) for c in (OK, DIVERGENTE_PRECO, DIVERGENTE_VOLUME))

    @property
    def divergentes(self) -> int:
        return self.contagem.get(DIVERGENTE_PRECO, 0) + self.contagem.get(DIVERGENTE_VOLUME, 0)

    @property
    def taxa_divergencia_preco(self) -> Decimal:
        if not self.comparaveis:
            return Decimal(0)
        return Decimal(self.contagem.get(DIVERGENTE_PRECO, 0)) / Decimal(self.comparaveis)

    @property
    def alerta(self) -> bool:
        return bool(self.graves) or self.taxa_divergencia_preco > TAXA_MAXIMA_DIVERGENCIA_PRECO

    def mensagem(self) -> str:
        partes = [f"{codigo}={self.contagem[codigo]}" for codigo in sorted(self.contagem)]
        texto = (
            f"{self.data_pregao}: {', '.join(partes)} | "
            f"divergencia de preco {self.taxa_divergencia_preco * 100:.2f}% de {self.comparaveis}"
        )
        if self.graves:
            texto += f" | GRAVE: {', '.join(self.graves)}"
        return texto


def resumir(data_pregao: date, linhas: list[LinhaConciliacao]) -> ResumoConciliacao:
    return ResumoConciliacao(
        data_pregao=data_pregao,
        contagem=dict(Counter(linha.divergencia for linha in linhas)),
        graves=tuple(sorted(linha.simbolo for linha in linhas if linha.severidade == GRAVE)),
    )
