"""Caso de uso: desdobramentos, grupamentos e bonificacoes (plano LAC, L2).

Le so o que outras cargas ja gravaram - marcas ex do COTAHIST e composicao
de capital da DFP - e grava evento_corporativo. Idempotente (upsert por
simbolo, data e tipo); correcao MANUAL nunca e sobrescrita. Evento sem
confianca suficiente nao e gravado: vai para o log, para revisao.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from logging import Logger

from app.dominio.evento_corporativo import (
    EventoInferido,
    Rejeicao,
    candidatos,
    inferir,
    um_por_intervalo,
)
from app.dominio.modelo import STATUS_SUCESSO
from app.portas.evento_corporativo import RepositorioEventoCorporativo
from app.portas.repositorios import RepositorioExecucao

FONTE_EVENTOS = "EVENTOS_CORPORATIVOS"


@dataclass
class ResultadoEventos:
    candidatos: int = 0
    gravados: int = 0
    rejeicoes: list[Rejeicao] = field(default_factory=list)

    def motivos(self) -> Counter:
        return Counter(r.motivo.split(" (")[0].split(":")[0] for r in self.rejeicoes)


class InferirEventosCorporativos:
    def __init__(
        self,
        unidade_de_trabalho,
        repositorio: RepositorioEventoCorporativo,
        repositorio_execucao: RepositorioExecucao,
        logger: Logger,
    ):
        self._uow = unidade_de_trabalho
        self._repositorio = repositorio
        self._execucao = repositorio_execucao
        self._logger = logger

    def executar(self, anos: list[int] | None = None) -> ResultadoEventos:
        resultado = ResultadoEventos()
        with self._uow.transacao() as db:
            pregoes = self._repositorio.pregoes(db, anos)
            composicoes = self._repositorio.composicoes(db)
            cnpj_de = self._repositorio.cnpj_por_simbolo(db)

        eventos: list[EventoInferido] = []
        for candidato in candidatos(pregoes):
            resultado.candidatos += 1
            cnpj = cnpj_de.get(candidato.simbolo)
            if cnpj is None:
                resultado.rejeicoes.append(
                    Rejeicao(candidato.simbolo, candidato.data, candidato.marca_ex, "sem CNPJ")
                )
                continue
            saida = inferir(candidato, cnpj, composicoes.get(cnpj, []))
            if isinstance(saida, Rejeicao):
                resultado.rejeicoes.append(saida)
            else:
                eventos.append(saida)
        eventos, duplicados = um_por_intervalo(eventos)
        resultado.rejeicoes.extend(duplicados)

        for rejeicao in resultado.rejeicoes:
            self._logger.debug(
                "Evento descartado | %s %s %s | %s",
                rejeicao.simbolo, rejeicao.data, rejeicao.marca_ex, rejeicao.motivo,
            )
        for evento in eventos:
            self._logger.info(
                "Evento | %s %s %s %s confianca=%s",
                evento.simbolo, evento.data_efeito, evento.tipo,
                evento.evidencia["fator"], evento.confianca,
            )

        competencia = f"{min(anos)}-{max(anos)}" if anos else "todos"
        with self._uow.transacao() as db:
            resultado.gravados = self._repositorio.substituir(db, eventos, anos)
            self._execucao.registrar(
                db, FONTE_EVENTOS, competencia, "cotahist+dfp", STATUS_SUCESSO,
                linhas_carregadas=resultado.gravados,
            )
        return resultado
