"""Caso de uso: enriquecer indicadores com multiplos de mercado (I4 e I7).

Roda apos CarregarFundamentos ter gravado os indicadores contabeis E apos
CarregarSeriesHistoricas ter gravado as cotacoes COTAHIST. Se a serie nao
estiver disponivel ainda (ex.: primeiro deploy do ano), os multiplos ficam
NULL — serao preenchidos quando a serie for carregada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from logging import Logger

from app.dominio.calculo.calculadora_multiplos_mercado import CalculadoraMultiplosMercado
from app.portas.repositorios import RepositorioMetricasMercado


@dataclass
class ResultadoMetricas:
    anos_processados: list[int] = field(default_factory=list)
    metricas_atualizadas: int = 0
    erros: list[str] = field(default_factory=list)

    @property
    def sucesso(self) -> bool:
        return not self.erros


class AtualizarMetricasMercado:
    def __init__(
        self,
        unidade_de_trabalho,
        repositorio: RepositorioMetricasMercado,
        calculadora: CalculadoraMultiplosMercado,
        logger: Logger,
    ):
        self._uow = unidade_de_trabalho
        self._repo = repositorio
        self._calc = calculadora
        self._logger = logger

    def executar(
        self,
        anos: list[int],
        simbolos: list[str],
    ) -> ResultadoMetricas:
        resultado = ResultadoMetricas()

        for ano in sorted(anos):
            try:
                self._processar_ano(ano, simbolos, resultado)
            except Exception as erro:
                msg = f"Metricas de mercado {ano}: {erro}"
                self._logger.warning(msg)
                resultado.erros.append(msg)

        return resultado

    def _processar_ano(
        self,
        ano: int,
        simbolos: list[str],
        resultado: ResultadoMetricas,
    ) -> None:
        with self._uow.transacao() as db:
            insumos = self._repo.buscar_insumos_de_mercado(db, simbolos, ano)

        if not insumos:
            self._logger.debug("Nenhum insumo de mercado para %s", ano)
            return

        # Datas de referencia distintas no ano (normalmente 31/12, mas ITR usa outras)
        datas = {i.periodo for i in insumos}
        precos: dict = {}
        for data_ref in datas:
            simbolos_na_data = [i.simbolo for i in insumos if i.periodo == data_ref]
            with self._uow.transacao() as db:
                precos_data = self._repo.buscar_precos_na_data(db, simbolos_na_data, data_ref)
            precos.update(precos_data)

        if not precos:
            self._logger.debug("Sem cotacoes B3 para o ano %s; multiplos ficam NULL", ano)
            return

        metricas = self._calc.calcular(insumos, precos)

        with self._uow.transacao() as db:
            atualizados = self._repo.atualizar_metricas_mercado(db, metricas)

        resultado.anos_processados.append(ano)
        resultado.metricas_atualizadas += atualizados
        self._logger.info(
            "Metricas de mercado %s: %d multiplos atualizados (%d com preco de %d insumos)",
            ano,
            atualizados,
            len(precos),
            len(insumos),
        )
