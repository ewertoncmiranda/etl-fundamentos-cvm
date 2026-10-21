"""Datas ex gravaveis em data_ex_b3, a partir de cotacao_b3_diaria.

Usa `calcular_datas_ex` (datas_ex.py) para o ajuste implicito e aplica por cima
a regra dos dados reais: o COTAHIST repete a marca ex por ~8 pregoes seguidos,
entao o dia ex e so o PRIMEIRO pregao da sequencia. Regra IDENTICA a do gestor
(ServicoDatasEx.primeiroDiaDeCadaJanela): por simbolo, em ordem de data, uma
linha com marca continua a sequencia se a linha com marca imediatamente
anterior tem a MESMA marca e esta a no maximo 5 dias corridos; marcas
diferentes intercaladas abrem eventos separados.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from logging import Logger

from app.aplicacao.datas_ex import DataEx, calcular_datas_ex
from app.dominio.modelo import STATUS_SUCESSO

VERSAO_CALCULO = "PRIMEIRO_PREGAO_V1"
FONTE_DATAS_EX = "DATAS_EX_B3"
JANELA_MAXIMA_DIAS = 5
ANO_INICIAL = 2016

_TIPO_POR_LETRA = {
    "B": "BONIFICACAO", "D": "DIVIDENDO", "G": "GRUPAMENTO", "J": "JCP",
    "R": "RENDIMENTO", "S": "SUBSCRICAO", "X": "DESDOBRAMENTO",
}


def tipo_da_marca(marca: str | None) -> str:
    """Mesmo mapa do gestor: primeira letra reconhecida depois do E; senao OUTRO."""
    for letra in (marca or "").strip().upper()[1:]:
        if letra in _TIPO_POR_LETRA:
            return _TIPO_POR_LETRA[letra]
    return "OUTRO"


@dataclass(frozen=True)
class LinhaMarcada:
    """Pregao com marca_ex e o pregao imediatamente anterior do mesmo simbolo."""

    simbolo: str
    data_pregao: date
    marca_ex: str
    abertura: Decimal | None
    fechamento: Decimal | None
    data_anterior: date | None
    fechamento_anterior: Decimal | None


@dataclass(frozen=True)
class DataExGravavel:
    simbolo: str
    data_ex: date
    marca: str
    tipo: str
    fechamento_anterior: Decimal | None
    abertura_ex: Decimal | None
    ajuste_implicito: Decimal | None
    ajuste_percentual: Decimal | None


def primeiro_pregao_de_cada_sequencia(eventos: Sequence[DataEx]) -> list[DataEx]:
    """Aplica a regra acima. Aceita a saida de `calcular_datas_ex`."""
    saida: list[DataEx] = []
    anterior: DataEx | None = None
    for evento in sorted(eventos, key=lambda e: (e.simbolo, e.data)):
        continua = (
            anterior is not None
            and anterior.simbolo == evento.simbolo
            and anterior.marca_ex == evento.marca_ex
            and (evento.data - anterior.data).days <= JANELA_MAXIMA_DIAS
        )
        if not continua:
            saida.append(evento)
        anterior = evento
    return saida


class _Candle:
    __slots__ = ("simbolo", "data_pregao", "abertura", "fechamento", "marca_ex")

    def __init__(self, simbolo, data_pregao, abertura, fechamento, marca_ex):
        self.simbolo, self.data_pregao = simbolo, data_pregao
        self.abertura, self.fechamento, self.marca_ex = abertura, fechamento, marca_ex


def montar_datas_ex(linhas: Sequence[LinhaMarcada]) -> list[DataExGravavel]:
    """Das linhas marcadas (com o pregao anterior) as datas ex a gravar."""
    marcadas = {(l.simbolo, l.data_pregao): l for l in linhas}
    candles = [
        _Candle(l.simbolo, l.data_pregao, l.abertura, l.fechamento, l.marca_ex) for l in linhas
    ]
    anteriores = set()
    for l in linhas:
        chave = (l.simbolo, l.data_anterior)
        if l.data_anterior and chave not in marcadas and chave not in anteriores:
            anteriores.add(chave)
            candles.append(_Candle(l.simbolo, l.data_anterior, None, l.fechamento_anterior, None))
    resultado = []
    for evento in primeiro_pregao_de_cada_sequencia(calcular_datas_ex(candles)):
        linha = marcadas[(evento.simbolo, evento.data)]
        resultado.append(DataExGravavel(
            evento.simbolo, evento.data, evento.marca_ex, tipo_da_marca(evento.marca_ex),
            linha.fechamento_anterior, linha.abertura, evento.ajuste_implicito,
            evento.ajuste_percentual,
        ))
    return resultado


@dataclass
class ResultadoDatasEx:
    gravados: int = 0
    rejeicoes: list[dict] = field(default_factory=list)


class CarregarDatasEx:
    def __init__(self, unidade_de_trabalho, repositorio, repositorio_execucao, logger: Logger):
        self._uow = unidade_de_trabalho
        self._repo = repositorio
        self._execucao = repositorio_execucao
        self._logger = logger

    def executar(self, anos: list[int] | None = None) -> ResultadoDatasEx:
        resultado = ResultadoDatasEx()
        with self._uow.transacao() as db:
            vazia = self._repo.contar_datas_ex(db) == 0
            desde = date(min(anos), 1, 1) if anos and not vazia else date(ANO_INICIAL, 1, 1)
            linhas = self._repo.linhas_com_marca_ex(db, desde)
        validas = []
        for l in linhas:
            if len(l.marca_ex) > 4:
                resultado.rejeicoes.append({"motivo": "MARCA_LONGA", "origem": l.simbolo})
            else:
                validas.append(l)
        eventos = montar_datas_ex(validas)
        with self._uow.transacao() as db:
            resultado.gravados = self._repo.salvar_datas_ex(db, eventos, VERSAO_CALCULO)
            self._execucao.registrar(
                db, FONTE_DATAS_EX, f"{desde.year}+", "cotacao_b3_diaria", STATUS_SUCESSO,
                linhas_carregadas=resultado.gravados,
            )
        self._logger.info("Datas ex: %d gravadas desde %s (%d descartadas)",
                          resultado.gravados, desde, len(resultado.rejeicoes))
        return resultado


@dataclass
class ResultadoEventosEDatasEx:
    candidatos: int = 0
    gravados: int = 0
    rejeicoes: list = field(default_factory=list)
    datas_ex_gravadas: int = 0
    datas_ex_descartadas: list[dict] = field(default_factory=list)
    erros: list[str] = field(default_factory=list)


class EventosEDatasEx:
    """Etapa EVENTOS: eventos corporativos inferidos + datas ex. Falha nas datas
    ex nao desfaz os eventos ja gravados; vira erro (FALHA) no resumo."""

    def __init__(self, eventos, datas_ex: CarregarDatasEx, logger: Logger):
        self._eventos = eventos
        self._datas_ex = datas_ex
        self._logger = logger

    def executar(self, anos: list[int] | None = None) -> ResultadoEventosEDatasEx:
        base = self._eventos.executar(anos)
        r = ResultadoEventosEDatasEx(base.candidatos, base.gravados, base.rejeicoes)
        try:
            datas = self._datas_ex.executar(anos)
            r.datas_ex_gravadas = datas.gravados
            r.datas_ex_descartadas = datas.rejeicoes
        except Exception as erro:
            self._logger.error("Datas ex: %s", erro, exc_info=True)
            r.erros.append(f"DATAS_EX: {erro}")
        return r
