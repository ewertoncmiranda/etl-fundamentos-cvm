"""Caso de uso: conciliar a foto da BRAPI com o COTAHIST e registrar o veredito.

Roda na rotina da manha, depois da carga do COTAHIST. Cada pregao conciliado
vira uma linha em etl_execucao (fonte CONCILIACAO_BRAPI_B3), que a aba Saude
dos dados ja le. O codigo de saida so sinaliza alerta; o dado e a view.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from logging import Logger

from app.dominio.conciliacao import FONTE_CONCILIACAO, ResumoConciliacao, resumir
from app.dominio.modelo import STATUS_ERRO, STATUS_SUCESSO
from app.portas.conciliacao import RepositorioConciliacao
from app.portas.repositorios import RepositorioExecucao

ARQUIVO = "vw_conciliacao_preco"


@dataclass
class ResultadoConciliacao:
    disponivel: bool = True
    resumos: list[ResumoConciliacao] = field(default_factory=list)

    @property
    def alerta(self) -> bool:
        return any(r.alerta for r in self.resumos)


class ConciliarPrecos:
    def __init__(
        self,
        unidade_de_trabalho,
        repositorio: RepositorioConciliacao,
        repositorio_execucao: RepositorioExecucao,
        logger: Logger,
    ):
        self._uow = unidade_de_trabalho
        self._repo = repositorio
        self._execucao = repositorio_execucao
        self._logger = logger

    def executar(self, data_pregao: date | None = None) -> ResultadoConciliacao:
        resultado = ResultadoConciliacao()
        with self._uow.transacao() as db:
            if not self._repo.disponivel(db):
                self._logger.warning(
                    "Conciliacao: %s ainda nao existe (infra V15); nada a fazer", ARQUIVO
                )
                resultado.disponivel = False
                return resultado
            pregoes = [data_pregao] if data_pregao else self._repo.pregoes_a_conciliar(db)

        for dia in pregoes:
            with self._uow.transacao() as db:
                linhas = self._repo.linhas(db, dia)
                if not linhas:
                    self._logger.info("Conciliacao %s: sem foto da BRAPI nesse pregao", dia)
                    continue
                resumo = resumir(dia, linhas)
                self._execucao.registrar(
                    db, FONTE_CONCILIACAO, dia.isoformat(), ARQUIVO,
                    STATUS_ERRO if resumo.alerta else STATUS_SUCESSO,
                    linhas_carregadas=resumo.divergentes,
                    mensagem_erro=resumo.mensagem(),
                )
            nivel = self._logger.warning if resumo.alerta else self._logger.info
            nivel("Conciliacao %s", resumo.mensagem())
            resultado.resumos.append(resumo)
        return resultado
