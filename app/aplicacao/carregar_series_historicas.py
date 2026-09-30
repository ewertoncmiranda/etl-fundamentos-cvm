from __future__ import annotations

from dataclasses import dataclass, field
from logging import Logger

from app.dominio.identidade import codigos_negociados
from app.dominio.modelo import STATUS_PULADO, STATUS_SUCESSO
from app.portas.fonte_series import FonteDeSeries
from app.portas.repositorios import RepositorioExecucao, RepositorioSeries

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
        repositorio_series: RepositorioSeries,
        repositorio_execucao: RepositorioExecucao,
        logger: Logger,
        repositorio_identidade=None,
        verificador_de_schema=None,
        nome_do_banco: str | None = None,
    ):
        self._fonte = fonte
        self._uow = unidade_de_trabalho
        self._series = repositorio_series
        self._execucao = repositorio_execucao
        self._logger = logger
        self._identidade = repositorio_identidade
        self._verificador = verificador_de_schema
        self._nome_do_banco = nome_do_banco

    def executar(
        self,
        anos: list[int],
        simbolos_pedidos: list[str] | None = None,
        forcar: bool = False,
    ) -> ResultadoSeries:
        resultado = ResultadoSeries()
        if self._verificador is not None:
            with self._uow.transacao() as db:
                self._verificador.conferir(db, self._nome_do_banco)
        simbolos = self._resolver_universo(simbolos_pedidos)
        if simbolos is None:
            self._logger.info(
                "COTAHIST: universo amplo, sem filtro de simbolo - todo lote padrao/BDR do arquivo"
            )
        else:
            self._logger.info("COTAHIST: %d codigos (com os antigos) - %s", len(simbolos), simbolos)

        for ano in sorted(anos):
            arquivo = f"COTAHIST_A{ano}.ZIP"
            assinatura = self._fonte.assinatura(ano)
            with self._uow.transacao() as db:
                etag_anterior = self._execucao.etag_da_ultima_execucao(
                    db, FONTE_COTAHIST, str(ano), arquivo
                )
            if not forcar and assinatura.inalterado_em_relacao_a(etag_anterior):
                with self._uow.transacao() as db:
                    self._execucao.registrar(
                        db, FONTE_COTAHIST, str(ano), arquivo, STATUS_PULADO,
                        etag=assinatura.etag,
                        last_modified=assinatura.last_modified,
                        tamanho_bytes=assinatura.tamanho_bytes,
                    )
                resultado.anos_pulados.append(ano)
                continue

            from datetime import date

            candles = self._fonte.candles(
                ano, None if simbolos is None else set(simbolos), usar_cache=ano < date.today().year
            )
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

    def _resolver_universo(self, simbolos_pedidos: list[str] | None) -> list[str] | None:
        """None = universo amplo (TASK-59): sem lista pre-definida, o proprio
        COTAHIST e a fonte de quais simbolos negociaram naquele ano - e por
        isso que nao ha bloqueio de deslistada aqui, diferente do
        ativo_monitorado (que so tem o que esta sendo acompanhado hoje)."""
        if not simbolos_pedidos:
            return None
        simbolos = sorted({s.strip().upper() for s in simbolos_pedidos if s.strip()})
        if self._identidade is not None:
            with self._uow.transacao() as db:
                simbolos = sorted(codigos_negociados(simbolos, self._identidade.identidades(db)))
        return simbolos
