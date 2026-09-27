"""Entrypoint do ETL de fundamentos da CVM.

Job em lote, nao servico: carrega, reporta e encerra. O agendamento fica fora
(cron do host ou GitHub Actions) - container dormindo e um scheduler ruim.

    python main.py                      # anos de CVM_ANOS, ativos monitorados
    python main.py --ano 2025
    python main.py --simbolo WEGE3 --simbolo PETR4
    python main.py --comunicados        # base IPE: ano atual e o anterior
    python main.py --comunicados --forcar --categoria ASSEMBLEIA
    python main.py --rotina             # tudo do dia: IPE, DFP, TTM e COTAHIST

O --rotina e o comando padrao do servico no docker compose: e o que roda
ao clicar em "play" no container pelo Docker Desktop, sem argumento nem
variavel nenhuma.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from app.config.composicao import (
    montar_carga_de_comunicados,
    montar_carga_de_series,
    montar_carga_ttm,
    montar_caso_de_uso,
)
from app.config.config_logger import configurar_logger
from app.config.settings import Settings, carregar_env
from app.dominio.comunicado import CATEGORIAS, CATEGORIAS_PADRAO


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
        "--universo-backtest",
        action="store_true",
        help="com a carga de fundamentos: balancos de todo o universo do backtest "
        "(acoes liquidas de cada ano no COTAHIST), nao so dos monitorados",
    )
    parser.add_argument(
        "--rotina",
        action="store_true",
        help="carga do dia inteira: comunicados, DFP do ano anterior e do atual, "
        "TTM e COTAHIST do ano atual (ignora --ano)",
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
    parser.add_argument(
        "--comunicados",
        action="store_true",
        help="carrega os comunicados oficiais da base IPE (fato relevante, proventos...)",
    )
    parser.add_argument(
        "--categoria",
        action="append",
        dest="categorias",
        choices=sorted(set(CATEGORIAS.values())),
        help="com --comunicados: categoria a carregar; repetivel. Padrao: "
        + ", ".join(CATEGORIAS_PADRAO),
    )
    parser.add_argument(
        "--forcar",
        action="store_true",
        help="processa mesmo com ETag igual (universo, curadoria ou categorias mudaram)",
    )
    return parser.parse_args(argv)


def anos_de_comunicados(hoje: date) -> list[int]:
    """Ano atual e o anterior: em janeiro o arquivo do ano novo ainda esta quase
    vazio, e so o atual deixaria a linha do tempo em branco."""
    return [hoje.year - 1, hoje.year]


def main(argv: list[str] | None = None) -> int:
    argumentos = analisar_argumentos(argv)

    carregar_env()
    settings = Settings.do_ambiente()
    logger = configurar_logger(settings.log_level)

    if argumentos.rotina:
        return _rotina(argumentos, settings, logger)

    if argumentos.comunicados:
        return _carregar_comunicados(argumentos, settings, logger)

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
                anos, argumentos.simbolos, argumentos.forcar
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
                anos, argumentos.simbolos, argumentos.forcar
            )
            logger.info(
                "Carga TTM concluida | processados=%s | pulados=%s | indicadores=%d",
                resultado_ttm.anos_processados,
                resultado_ttm.anos_pulados,
                resultado_ttm.indicadores_gravados,
            )
            return 0
        caso_de_uso = montar_caso_de_uso(settings, logger)
        resultado = caso_de_uso.executar(
            anos, argumentos.simbolos, argumentos.forcar, argumentos.universo_backtest
        )
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
        for mensagem in resultado.erros:
            logger.error("Erro na carga: %s", mensagem)
        return 1

    return 0


def _rotina(argumentos: argparse.Namespace, settings: Settings, logger) -> int:
    """As quatro cargas em sequencia, cada uma isolada: uma falha (CVM fora
    do ar, por exemplo) nao impede as outras e so muda o codigo de saida.
    Sem novidade na origem, cada carga custa uma requisicao HEAD (ETag)."""
    ano = date.today().year
    simbolos = argumentos.simbolos
    forcar = argumentos.forcar
    etapas = [
        ("comunicados (IPE)", lambda: _carregar_comunicados(
            argparse.Namespace(anos=None, simbolos=simbolos, categorias=None, forcar=forcar),
            settings, logger)),
        ("fundamentos (DFP)", lambda: _codigo_da_carga(
            montar_caso_de_uso(settings, logger).executar([ano - 1, ano], simbolos, forcar))),
        ("ultimos 12 meses (TTM)", lambda: _sem_erro(
            montar_carga_ttm(settings, logger).executar([ano], simbolos, forcar))),
        ("preco oficial (COTAHIST)", lambda: _sem_erro(
            montar_carga_de_series(settings, logger).executar([ano], simbolos, forcar))),
    ]
    falhas = []
    for nome, etapa in etapas:
        logger.info("Rotina | inicio: %s", nome)
        try:
            codigo = etapa()
        except Exception as erro:
            logger.error("Rotina | %s abortou: %s", nome, erro, exc_info=True)
            codigo = 1
        if codigo:
            falhas.append(nome)
    if falhas:
        logger.error("Rotina concluida com falha em: %s", ", ".join(falhas))
        return 1
    logger.info("Rotina concluida sem falhas")
    return 0


def _sem_erro(_resultado) -> int:
    """TTM e COTAHIST nao acumulam erro: falha neles vira excecao."""
    return 0


def _codigo_da_carga(resultado) -> int:
    for mensagem in resultado.erros:
        logging.getLogger("etl-fundamentos-cvm").error("Erro na carga: %s", mensagem)
    return 1 if resultado.erros else 0


def _carregar_comunicados(argumentos: argparse.Namespace, settings: Settings, logger) -> int:
    anos = argumentos.anos or anos_de_comunicados(date.today())
    categorias = argumentos.categorias or list(CATEGORIAS_PADRAO)
    # Pedir simbolo explicito e sinal de recorte novo: o ETag nao mudou, mas
    # esses tickers talvez nunca tenham sido carregados.
    forcar = argumentos.forcar or bool(argumentos.simbolos)

    logger.info(
        "Iniciando carga de comunicados | anos=%s | categorias=%s | forcar=%s",
        anos,
        categorias,
        forcar,
    )
    try:
        resultado = montar_carga_de_comunicados(settings, logger).executar(
            anos, argumentos.simbolos, categorias, forcar
        )
    except Exception as erro:
        logger.critical("Carga de comunicados abortada: %s", erro, exc_info=True)
        return 1

    logger.info(
        "Carga de comunicados concluida | processados=%s | pulados=%s | lidos=%d | "
        "gravados=%d | tickers com novidade=%s",
        resultado.anos_processados,
        resultado.anos_pulados,
        resultado.documentos_lidos,
        resultado.documentos_gravados,
        resultado.simbolos_com_novidade,
    )
    for mensagem in resultado.erros:
        logger.error("Erro na carga de comunicados: %s", mensagem)
    return 1 if resultado.erros else 0


if __name__ == "__main__":
    sys.exit(main())
