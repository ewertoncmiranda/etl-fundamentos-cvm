"""Entrypoint do ETL de fundamentos da CVM.

Job em lote, não serviço: carrega, reporta e encerra. O agendamento fica fora
(cron do host ou GitHub Actions).

    python main.py                      # Carrega TUDO: COTAHIST + fundamentos + TTM +
                                        # comunicados + proventos + eventos (últimos 5 anos)
    python main.py --rotina             # Rotina diária agendada (ano atual + anterior)
    python main.py --ano 2023           # Restringe o "carrega tudo" a um ano específico
    python main.py --simbolo WEGE3      # Restringe a um ticker
    python main.py --forcar             # Reprocessa mesmo sem mudança de ETag
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

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
from app.config.config_logger import configurar_logger
from app.config.settings import Settings, carregar_env
from app.dominio.comunicado import CATEGORIAS_PADRAO

ANOS_HISTORICO = 5


def analisar_argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ETL de fundamentos da CVM")
    parser.add_argument(
        "--rotina",
        action="store_true",
        help="rotina diária agendada: comunicados, fundamentos, TTM e COTAHIST do ano atual",
    )
    parser.add_argument(
        "--ano",
        type=int,
        action="append",
        dest="anos",
        help="restringe a carga a este ano; repetível. Padrão (sem --rotina): últimos 5 anos",
    )
    parser.add_argument(
        "--simbolo",
        action="append",
        dest="simbolos",
        help="restringe a estes tickers; repetível. Padrão: todos os monitorados",
    )
    parser.add_argument(
        "--forcar",
        action="store_true",
        help="reprocessa mesmo com ETag inalterado",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    argumentos = analisar_argumentos(argv)

    carregar_env()
    settings = Settings.do_ambiente()
    logger = configurar_logger(settings.log_level)

    if argumentos.rotina:
        return _rotina(argumentos, settings, logger)

    return _carregar_tudo(argumentos, settings, logger)


# ---------------------------------------------------------------------------
# Rotina diária
# ---------------------------------------------------------------------------

def _rotina(argumentos: argparse.Namespace, settings: Settings, logger) -> int:
    """Etapas do dia em sequência; uma falha não derruba as outras."""
    ano = date.today().year
    simbolos = argumentos.simbolos
    forcar = argumentos.forcar
    etapas = [
        ("comunicados (IPE)", lambda: _carregar_comunicados(
            [ano - 1, ano], simbolos, None, forcar, settings, logger)),
        ("fundamentos (DFP)", lambda: _codigo_da_carga(
            montar_caso_de_uso(settings, logger).executar(
                [ano - 1, ano], simbolos, forcar, universo_backtest=not simbolos))),
        ("últimos 12 meses (TTM)", lambda: _sem_erro(
            montar_carga_ttm(settings, logger).executar(
                [ano], simbolos, forcar, universo_backtest=not simbolos))),
        ("preço oficial (COTAHIST)", lambda: _sem_erro(
            montar_carga_de_series(settings, logger).executar([ano], simbolos, forcar))
            or _liquidez_depois_do_cotahist(settings, logger)),
        ("proventos (DVA)", lambda: _sem_erro(
            montar_carga_proventos(settings, logger).executar(
                [ano - 1, ano], simbolos, universo_backtest=not simbolos))),
        ("checagens de qualidade", montar_checagens(settings, logger)),
    ]
    falhas = []
    for nome, etapa in etapas:
        logger.info("Rotina | início: %s", nome)
        try:
            codigo = etapa()
        except Exception as erro:
            logger.error("Rotina | %s abortou: %s", nome, erro, exc_info=True)
            codigo = 1
        if codigo:
            falhas.append(nome)
    if falhas:
        logger.error("Rotina concluída com falha em: %s", ", ".join(falhas))
        return 1
    logger.info("Rotina concluída sem falhas")
    return 0


# ---------------------------------------------------------------------------
# Carga completa (padrão, sem flags)
# ---------------------------------------------------------------------------

def _carregar_tudo(argumentos: argparse.Namespace, settings: Settings, logger) -> int:
    """Carrega tudo: COTAHIST + fundamentos + TTM + comunicados + proventos +
    eventos corporativos para os últimos ANOS_HISTORICO anos."""
    hoje = date.today()
    anos = argumentos.anos or list(range(hoje.year - ANOS_HISTORICO, hoje.year + 1))
    simbolos = argumentos.simbolos
    forcar = argumentos.forcar
    universo_backtest = not simbolos

    logger.info(
        "Carga completa | anos=%s | simbolos=%s | forcar=%s",
        anos, simbolos or "todos", forcar,
    )

    etapas = [
        ("COTAHIST (série histórica)", lambda: _sem_erro(
            montar_carga_de_series(settings, logger).executar(anos, simbolos, forcar))
            or _liquidez_depois_do_cotahist(settings, logger)),
        ("fundamentos (DFP)", lambda: _codigo_da_carga(
            montar_caso_de_uso(settings, logger).executar(
                anos, simbolos, forcar, universo_backtest))),
        ("últimos 12 meses (TTM)", lambda: _sem_erro(
            montar_carga_ttm(settings, logger).executar(
                anos, simbolos, forcar, universo_backtest))),
        ("comunicados (IPE)", lambda: _carregar_comunicados(
            anos, simbolos, None, forcar or bool(simbolos), settings, logger)),
        ("proventos (DVA)", lambda: _sem_erro(
            montar_carga_proventos(settings, logger).executar(
                anos, simbolos, universo_backtest))),
        ("eventos corporativos", lambda: _sem_erro(
            montar_eventos_corporativos(settings, logger).executar(None))),
        ("checagens de qualidade", montar_checagens(settings, logger)),
    ]

    falhas = []
    for nome, etapa in etapas:
        logger.info("Carga completa | início: %s", nome)
        try:
            codigo = etapa()
        except Exception as erro:
            logger.error("Carga completa | %s abortou: %s", nome, erro, exc_info=True)
            codigo = 1
        if codigo:
            falhas.append(nome)

    if falhas:
        logger.error("Carga completa concluída com falha em: %s", ", ".join(falhas))
        return 1
    logger.info("Carga completa concluída sem falhas")
    return 0


# ---------------------------------------------------------------------------
# Helpers compartilhados
# ---------------------------------------------------------------------------

def _liquidez_depois_do_cotahist(settings: Settings, logger) -> int:
    try:
        resultado = montar_liquidez(settings, logger).executar()
    except Exception as erro:
        logger.error("Liquidez (OPR) falhou: %s", erro, exc_info=True)
        return 1
    if resultado.pregoes:
        logger.info(
            "Liquidez | pregões=%d (%s..%s) | linhas=%d",
            len(resultado.pregoes), resultado.pregoes[0], resultado.pregoes[-1],
            resultado.gravados,
        )
    try:
        montar_prontidao(settings, logger)()
    except Exception as erro:
        logger.error("Prontidão (OPR) falhou: %s", erro, exc_info=True)
        return 1
    try:
        montar_qualidade_opcoes(settings, logger)()
    except Exception as erro:
        logger.error("Qualidade opções falhou: %s", erro, exc_info=True)
    return 0


def _carregar_comunicados(anos, simbolos, categorias, forcar, settings, logger) -> int:
    cats = categorias or list(CATEGORIAS_PADRAO)
    try:
        resultado = montar_carga_de_comunicados(settings, logger).executar(
            anos, simbolos, cats, forcar
        )
    except Exception as erro:
        logger.critical("Comunicados abortados: %s", erro, exc_info=True)
        return 1
    logger.info(
        "Comunicados | processados=%s | lidos=%d | gravados=%d",
        resultado.anos_processados,
        resultado.documentos_lidos,
        resultado.documentos_gravados,
    )
    for mensagem in resultado.erros:
        logger.error("Erro comunicados: %s", mensagem)
    return 1 if resultado.erros else 0


def _sem_erro(_resultado) -> int:
    return 0


def _codigo_da_carga(resultado) -> int:
    for mensagem in resultado.erros:
        logging.getLogger("etl-fundamentos-cvm").error("Erro na carga: %s", mensagem)
    return 1 if resultado.erros else 0


if __name__ == "__main__":
    sys.exit(main())
