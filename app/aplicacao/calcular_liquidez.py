"""Caso de uso: liquidez diaria por ativo (Plano OPR, OPR-ETL-1, DEC-OPR-1).

Le so o COTAHIST ja carregado e grava `ativo_liquidez_diaria` (infra V23). Idempotente: upsert
por (simbolo, data_pregao). Sem datas explicitas, calcula os pregoes do mercado posteriores ao
ultimo ja calculado (na primeira vez, os ultimos HISTORICO_INICIAL pregoes). Roda dentro da carga
do COTAHIST (start unico, AGENTS.md); desde/data ficam para uso interno.
O processamento e por mes, para o backfill nao trazer o COTAHIST inteiro para a memoria.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import date
from logging import Logger

from app.dominio.liquidez import (
    JANELA_ATR,
    JANELA_LONGA,
    VERSAO_CALCULO,
    MetricaLiquidez,
    calcular,
    preencher_percentis,
)
from app.dominio.modelo import STATUS_SUCESSO
from app.portas.repositorios import RepositorioExecucao

FONTE_LIQUIDEZ = "LIQUIDEZ"
# Folga antes da janela: 63 pregoes de media + o ATR do ativo que nao negocia todo dia.
PREGOES_DE_FOLGA = JANELA_LONGA + 3 * JANELA_ATR
# Tabela vazia: calcula ~6 meses de pregoes, para o diario operacional ja ter janela de 63d.
HISTORICO_INICIAL = 126


@dataclass
class ResultadoLiquidez:
    pregoes: list[date] = field(default_factory=list)
    gravados: int = 0
    com_63d: int = 0


class CalcularLiquidez:
    def __init__(self, unidade_de_trabalho, repositorio, repositorio_execucao: RepositorioExecucao,
                 logger: Logger):
        self._uow = unidade_de_trabalho
        self._repositorio = repositorio
        self._execucao = repositorio_execucao
        self._logger = logger

    def _datas_alvo(self, db, mercado: list[date], desde: date | None, ate: date | None,
                    data: date | None) -> list[date]:
        if data:
            return [data] if data in set(mercado) else []
        fim = bisect_right(mercado, ate) if ate else len(mercado)
        if desde:
            return mercado[bisect_left(mercado, desde):fim]
        ultima = self._repositorio.ultima_data_calculada(db)
        if ultima is None:  # primeira carga: historico inicial, sem comando de backfill
            return mercado[max(0, fim - HISTORICO_INICIAL):fim]
        novos = mercado[bisect_right(mercado, ultima):fim]
        # Calculo mudou de versao (ex.: ajuste por evento, OPR-ETL-3): refaz o historico recente sozinho.
        antigos = self._repositorio.datas_com_versao_antiga(
            db, VERSAO_CALCULO, mercado[max(0, fim - HISTORICO_INICIAL)])
        return sorted(set(antigos) | set(novos))

    def executar(self, desde: date | None = None, ate: date | None = None, data: date | None = None,
                 simbolos: list[str] | None = None) -> ResultadoLiquidez:
        resultado = ResultadoLiquidez()
        with self._uow.transacao() as db:
            mercado = self._repositorio.pregoes_mercado(db, ate)
            alvos = self._datas_alvo(db, mercado, desde, ate, data)
        if not alvos:
            self._logger.info("Liquidez: nenhum pregao novo para calcular")
            return resultado

        meses: dict[tuple[int, int], list[date]] = {}
        for d in alvos:
            meses.setdefault((d.year, d.month), []).append(d)

        for datas in meses.values():
            inicio = mercado[max(0, bisect_left(mercado, datas[0]) - PREGOES_DE_FOLGA)]
            with self._uow.transacao() as db:
                series = self._repositorio.series(db, inicio, datas[-1], simbolos)
                eventos = self._repositorio.eventos_corporativos(db, datas[-1])
            datas_por_ativo = {s: [p.data for p in serie] for s, serie in series.items()}
            for d in datas:
                janela_inicio = mercado[max(0, bisect_left(mercado, d) - PREGOES_DE_FOLGA)]
                metricas: list[MetricaLiquidez] = []
                for simbolo, serie in series.items():
                    dias = datas_por_ativo[simbolo]
                    recorte = serie[bisect_left(dias, janela_inicio):bisect_right(dias, d)]
                    m = calcular(simbolo, d, mercado, recorte, eventos.get(simbolo)) if recorte else None
                    if m is not None:
                        metricas.append(m)
                preencher_percentis(metricas)
                with self._uow.transacao() as db:
                    resultado.gravados += self._repositorio.gravar(db, metricas)
                resultado.com_63d += sum(
                    1
                    for m in metricas
                    if m.volume_financeiro_medio_63d is not None
                )
                resultado.pregoes.append(d)
                self._logger.info("Liquidez | %s | ativos=%d", d, len(metricas))

        # etl_execucao.competencia tem 10 caracteres: o pregao mais recente calculado (o intervalo vai no log).
        competencia = str(resultado.pregoes[-1])
        with self._uow.transacao() as db:
            self._execucao.registrar(db, FONTE_LIQUIDEZ, competencia, "cotahist", STATUS_SUCESSO,
                                     linhas_carregadas=resultado.gravados)
        return resultado
