"""Entrypoint do ETL de fundamentos da CVM.

Job em lote, nao servico: carrega, reporta e encerra. O agendamento fica fora
(cron do host ou GitHub Actions) - container dormindo e um scheduler ruim.

    python main.py                      # anos de CVM_ANOS, ativos monitorados
    python main.py --ano 2025
    python main.py --simbolo WEGE3 --simbolo PETR4
"""

from __future__ import annotations

import argparse
import sys

from app.config.composicao import montar_carga_de_series, montar_carga_ttm, montar_caso_de_uso
from app.config.config_logger import configurar_logger
from app.config.settings import Settings, carregar_env


def analisar_argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ETL de fundamentos da CVM")
    parser.add_argument(
        "--ano",
        type=int,
        action="append",
        dest="anos",
        help="ano a carregar; repetivel. Padrao: CVM_ANOS",
    )
    parser.add_argument(
        "--cotahist",
        action="store_true",
        help="carrega serie historica anual bruta da B3 em vez dos fundamentos CVM",
    )
    parser.add_argument(
        "--ttm",
        action="store_true",
        help="deriva os ultimos doze meses combinando DFP e ITR acumulados",
    )
    parser.add_argument(
        "--simbolo",
        action="append",
        dest="simbolos",
        help="restringe a estes tickers; repetivel. Padrao: ativo_monitorado",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    argumentos = analisar_argumentos(argv)

    carregar_env()
    settings = Settings.do_ambiente()
    logger = configurar_logger(settings.log_level)

    anos = argumentos.anos or settings.anos
    if not anos:
        logger.critical("Nenhum ano definido. Use --ano ou a variavel CVM_ANOS.")
        return 2

    logger.info(
        "Iniciando carga | anos=%s | ambiente=%s | cache=%s",
        anos,
        settings.ambiente,
        settings.cvm_cache_dir,
    )

    try:
        if argumentos.cotahist:
            resultado_series = montar_carga_de_series(settings, logger).executar(
                anos, argumentos.simbolos
            )
            logger.info(
                "Carga COTAHIST concluida | processados=%s | pulados=%s | candles=%d",
                resultado_series.anos_processados,
                resultado_series.anos_pulados,
                resultado_series.candles_gravados,
            )
            return 0
        if argumentos.ttm:
            resultado_ttm = montar_carga_ttm(settings, logger).executar(
                anos, argumentos.simbolos
            )
            logger.info(
                "Carga TTM concluida | processados=%s | pulados=%s | indicadores=%d",
                resultado_ttm.anos_processados,
                resultado_ttm.anos_pulados,
                resultado_ttm.indicadores_gravados,
            )
            return 0
        caso_de_uso = montar_caso_de_uso(settings, logger)
        resultado = caso_de_uso.executar(anos, argumentos.simbolos)
    except Exception as erro:
        logger.critical("Carga abortada: %s", erro, exc_info=True)
        return 1

    logger.info(
        "Carga concluida | processados=%s | pulados=%s | landing=%d linhas | "
        "indicadores=%d | simbolos=%d",
        resultado.anos_processados,
        resultado.anos_pulados,
        resultado.linhas_landing,
        resultado.indicadores_gravados,
        len(set(resultado.simbolos_atualizados)),
    )

    if resultado.erros:
        for erro in resultado.erros:
            logger.error("Erro na carga: %s", erro)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
