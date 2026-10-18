"""Composition de alto nível das etapas do ETL.

O único ponto de entrada operacional é o servidor HTTP em ``app.servidor``.
Este módulo fornece as funções de cada etapa ao orquestrador, sem criar uma
segunda CLI ou um caminho de execução paralelo.
"""

from __future__ import annotations

from logging import Logger

from app.config.composicao import (
    montar_carga_de_comunicados,
    montar_carga_de_series,
    montar_carga_proventos,
    montar_carga_ttm,
    montar_caso_de_uso,
    montar_checagens,
    montar_conciliacao,
    montar_eventos_corporativos,
    montar_liquidez,
    montar_prontidao,
    montar_qualidade_opcoes,
)
from app.config.settings import Settings
from app.dominio.comunicado import CATEGORIAS_PADRAO


def criar_catalogo_etapas(settings: Settings, logger: Logger) -> dict:
    """Monta callbacks independentes; falha de uma etapa não impede as demais."""
    def cotahist(anos, simbolos, forcar):
        return montar_carga_de_series(settings, logger).executar(anos, simbolos, forcar)

    def liquidez(_anos, _simbolos, _forcar):
        return montar_liquidez(settings, logger).executar()

    def prontidao(_anos, _simbolos, _forcar):
        return montar_prontidao(settings, logger)()

    def qualidade_opcoes(_anos, _simbolos, _forcar):
        return montar_qualidade_opcoes(settings, logger)()

    def conciliacao(_anos, _simbolos, _forcar):
        return montar_conciliacao(settings, logger).executar()

    def dfp(anos, simbolos, forcar):
        return montar_caso_de_uso(settings, logger).executar(
            anos, simbolos, forcar, universo_backtest=not simbolos
        )

    def ttm(anos, simbolos, forcar):
        return montar_carga_ttm(settings, logger).executar(
            anos, simbolos, forcar, universo_backtest=not simbolos
        )

    def ipe(anos, simbolos, forcar):
        return montar_carga_de_comunicados(settings, logger).executar(
            anos, simbolos, CATEGORIAS_PADRAO, forcar or bool(simbolos)
        )

    def dva(anos, simbolos, _forcar):
        return montar_carga_proventos(settings, logger).executar(
            anos, simbolos, universo_backtest=not simbolos
        )

    def eventos(anos, _simbolos, _forcar):
        return montar_eventos_corporativos(settings, logger).executar(anos or None)

    def checagens(_anos, _simbolos, _forcar):
        return montar_checagens(settings, logger)()

    return {
        "COTAHIST": cotahist,
        "LIQUIDEZ": liquidez,
        "PRONTIDAO": prontidao,
        "QUALIDADE_OPCOES": qualidade_opcoes,
        "CONCILIACAO": conciliacao,
        "DFP": dfp,
        "TTM": ttm,
        "IPE": ipe,
        "DVA": dva,
        "EVENTOS": eventos,
        "CHECAGENS": checagens,
    }


def main() -> int:
    from app.servidor import main as iniciar_servidor

    return iniciar_servidor()


if __name__ == "__main__":
    raise SystemExit(main())
