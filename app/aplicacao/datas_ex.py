"""Eventos implícitos de preços brutos; não equivalem a proventos declarados.

Letras do ESPECI: B bonificação, D dividendo, G grupamento, J juros,
R rendimento, S subscrição (layout público B3, revisão 02/2020).
X e letras desconhecidas permanecem OUTRO, sem inferir evento oficial.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

TIPOS_EX = {
    "B": "BONIFICACAO", "D": "DIVIDENDO", "G": "GRUPAMENTO",
    "J": "JCP", "R": "RENDIMENTO", "S": "SUBSCRICAO",
}


class CandleEx(Protocol):
    @property
    def simbolo(self) -> str: ...

    @property
    def data_pregao(self) -> date: ...

    @property
    def abertura(self) -> Decimal | None: ...

    @property
    def fechamento(self) -> Decimal | None: ...

    @property
    def marca_ex(self) -> str | None: ...


@dataclass(frozen=True)
class DataEx:
    simbolo: str
    data: date
    marca_ex: str
    tipos: tuple[str, ...]
    data_anterior: date | None
    ajuste_implicito: Decimal | None
    ajuste_percentual: Decimal | None


def classificar_marca_ex(marca: str | None) -> tuple[str, ...]:
    """Uma classificação por letra, na ordem original, sem duplicatas.

    Aceita a marca já extraída do ESPECI. Não descarta marcas futuras que o
    regex atual do leitor ainda não reconhece: essas letras viram OUTRO.
    """
    marca = (marca or "").strip().upper()
    if not marca:
        return ()
    if not marca.startswith("E") or len(marca) == 1:
        return ("OUTRO",)
    return tuple(dict.fromkeys(TIPOS_EX.get(letra, "OUTRO") for letra in marca[1:]))


def calcular_datas_ex(candles: Sequence[CandleEx]) -> list[DataEx]:
    """Ordena por símbolo/data e compara pregões consecutivos do mesmo ativo.

    Percentual em pontos percentuais: 100 * ajuste / fechamento anterior.
    Sem preço anterior/abertura, ajuste é None; denominador não positivo não
    produz percentual. Não consulta calendário nem preenche pregões ausentes.
    Duplicatas símbolo/data são rejeitadas para evitar resultado arbitrário.
    """
    anteriores: dict[str, CandleEx] = {}
    resultado = []
    for candle in sorted(candles, key=lambda c: (c.simbolo, c.data_pregao)):
        anterior = anteriores.get(candle.simbolo)
        if anterior and anterior.data_pregao == candle.data_pregao:
            raise ValueError(f"Candle duplicado: {candle.simbolo} {candle.data_pregao}")
        marca = (candle.marca_ex or "").strip().upper()
        if marca:
            fechamento = anterior.fechamento if anterior else None
            ajuste = (
                fechamento - candle.abertura
                if fechamento is not None and candle.abertura is not None else None
            )
            percentual = (
                ajuste / fechamento * Decimal(100)
                if ajuste is not None and fechamento is not None and fechamento > 0 else None
            )
            resultado.append(DataEx(
                candle.simbolo, candle.data_pregao, marca, classificar_marca_ex(marca),
                anterior.data_pregao if anterior else None, ajuste, percentual,
            ))
        anteriores[candle.simbolo] = candle
    return resultado
