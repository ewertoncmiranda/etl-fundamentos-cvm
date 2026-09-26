from __future__ import annotations

from dataclasses import dataclass, field
from logging import Logger

from app.dominio.modelo import STATUS_PULADO, STATUS_SUCESSO
from app.portas.fonte_series import FonteDeSeries
from app.portas.repositorios import RepositorioExecucao, RepositorioSeries, RepositorioUniverso

FONTE_COTAHIST = "B3_COTAHIST"


@dataclass
class ResultadoSeries:
    anos_processados: list[int] = field(default_factory=list)
    anos_pulados: list[int] = field(default_factory=list)
    candles_gravados: int = 0


class CarregarSeriesHistoricas:
    def __init__(
        self,
        fonte: FonteDeSeries,
        unidade_de_trabalho,
        repositorio_universo: RepositorioUniverso,
        repositorio_series: RepositorioSeries,
        repositorio_execucao: RepositorioExecucao,
        logger: Logger,
    ):
        self._fonte = fonte
        self._uow = unidade_de_trabalho
        self._universo = repositorio_universo
        self._series = repositorio_series
        self._execucao = repositorio_execucao
        self._logger = logger

    def executar(
        self, anos: list[int], simbolos_pedidos: list[str] | None = None
    ) -> ResultadoSeries:
        resultado = ResultadoSeries()
        simbolos = self._resolver_universo(simbolos_pedidos)
        if not simbolos:
            self._logger.warning("Nenhum ativo monitorado para carregar do COTAHIST.")
            return resultado

        for ano in sorted(anos):
            arquivo = f"COTAHIST_A{ano}.ZIP"
            assinatura = self._fonte.assinatura(ano)
            with self._uow.transacao() as db:
                etag_anterior = self._execucao.etag_da_ultima_execucao(
                    db, FONTE_COTAHIST, str(ano), arquivo
                )
            if assinatura.inalterado_em_relacao_a(etag_anterior):
                with self._uow.transacao() as db:
                    self._execucao.registrar(
                        db, FONTE_COTAHIST, str(ano), arquivo, STATUS_PULADO,
                        etag=assinatura.etag,
                        last_modified=assinatura.last_modified,
                        tamanho_bytes=assinatura.tamanho_bytes,
                    )
                resultado.anos_pulados.append(ano)
                continue

            candles = self._fonte.candles(ano, set(simbolos))
            with self._uow.transacao() as db:
                gravados = self._series.salvar_candles_b3(db, candles)
                self._execucao.registrar(
                    db, FONTE_COTAHIST, str(ano), arquivo, STATUS_SUCESSO,
                    etag=assinatura.etag,
                    last_modified=assinatura.last_modified,
                    tamanho_bytes=assinatura.tamanho_bytes,
                    linhas_carregadas=gravados,
                )
            resultado.anos_processados.append(ano)
            resultado.candles_gravados += gravados
            self._logger.info("COTAHIST %s: %d candles B3 brutos gravados", ano, gravados)
        return resultado

    def _resolver_universo(self, simbolos_pedidos: list[str] | None) -> list[str]:
        if simbolos_pedidos:
            return sorted({s.strip().upper() for s in simbolos_pedidos if s.strip()})
        with self._uow.transacao() as db:
            return self._universo.listar_simbolos_monitorados(db)
