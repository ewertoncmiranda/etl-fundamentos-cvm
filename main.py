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
    montar_liquidez,
    montar_prontidao,
    montar_qualidade_opcoes,
)
from app.config.composicao_fontes import (
    montar_carga_cadastro,
    montar_carga_ifdata,
    montar_eventos_e_datas_ex,
    montar_carga_cda,
    montar_carga_fre,
    montar_carga_tesouro,
    montar_carga_vlmo,
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

    def tesouro(_anos, _simbolos, forcar):
        return montar_carga_tesouro(settings, logger).executar(forcar)

    def cvm_cadastro(_anos, _simbolos, forcar):
        return montar_carga_cadastro(settings, logger).executar(forcar)

    def ifdata(_anos, _simbolos, forcar):
        return montar_carga_ifdata(settings, logger).executar(forcar)

    def cvm_vlmo(anos, _simbolos, forcar):
        return montar_carga_vlmo(settings, logger).executar(anos, forcar)

    def cvm_fre(anos, _simbolos, forcar):
        return montar_carga_fre(settings, logger).executar(anos, forcar)

    def cvm_cda(_anos, _simbolos, forcar):
        return montar_carga_cda(settings, logger).executar(forcar)

    def eventos(anos, _simbolos, _forcar):
        return montar_eventos_e_datas_ex(settings, logger).executar(anos or None)

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
        "TESOURO": tesouro,
        "CVM_CADASTRO": cvm_cadastro,
        "IFDATA": ifdata,
        "CVM_VLMO": cvm_vlmo,
        "CVM_FRE": cvm_fre,
        "CVM_CDA": cvm_cda,
        "EVENTOS": eventos,
        "CHECAGENS": checagens,
    }


def main() -> int:
    from app.servidor import main as iniciar_servidor

    return iniciar_servidor()


if __name__ == "__main__":
    raise SystemExit(main())
