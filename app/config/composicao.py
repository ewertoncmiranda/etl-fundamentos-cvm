"""Composition root: o unico lugar do app que conhece classes concretas."""

from __future__ import annotations

from logging import Logger

import boto3

from app.adaptadores.b3.cliente_http_b3 import ClienteHttpB3
from app.adaptadores.b3.fonte_b3 import FonteB3
from app.adaptadores.b3.leitor_cotahist import LeitorCotahist
from app.adaptadores.cvm.cache_local import CacheDeArquivos
from app.adaptadores.cvm.cliente_http import ClienteHttpCvm
from app.adaptadores.cvm.fonte_cvm import FonteCvm
from app.adaptadores.cvm.fonte_ipe import FonteIpe
from app.adaptadores.cvm.normalizador import NormalizadorDeLinhas
from app.adaptadores.mensageria.publicador_sqs import PublicadorSqs
from app.adaptadores.persistencia.repositorio_conciliacao import RepositorioConciliacaoSql
from app.adaptadores.persistencia.repositorio_evento_corporativo import (
    RepositorioEventoCorporativoSql,
)
from app.adaptadores.persistencia.repositorios import (
    RepositorioCadastroSql,
    RepositorioComunicadoSql,
    RepositorioExecucaoSql,
    RepositorioFatoContabilSql,
    RepositorioIdentidadeSql,
    RepositorioIndicadorSql,
    RepositorioMetricasMercadoSql,
    RepositorioOpcaoSql,
    RepositorioProventoSql,
    RepositorioSeriesSql,
    RepositorioUniversoSql,
)
from app.adaptadores.persistencia.unidade_de_trabalho import UnidadeDeTrabalho
from app.adaptadores.persistencia.verificador_schema import (
    COLUNAS_V16_COTAHIST,
    COLUNAS_V16_FUNDAMENTOS,
    VerificadorDeSchema,
)
from app.aplicacao.atualizar_metricas_mercado import AtualizarMetricasMercado
from app.aplicacao.calcular_liquidez import CalcularLiquidez
from app.aplicacao.carregar_comunicados import CarregarComunicados
from app.aplicacao.carregar_fundamentos import CarregarFundamentos
from app.aplicacao.carregar_proventos import CarregarProventosContabeis
from app.aplicacao.carregar_series_historicas import CarregarSeriesHistoricas
from app.aplicacao.carregar_ttm import CarregarTtm
from app.aplicacao.conciliar_precos import ConciliarPrecos
from app.aplicacao.inferir_eventos_corporativos import InferirEventosCorporativos
from app.config.database_config import ConfiguracaoDeBanco
from app.config.settings import Settings
from app.dominio.calculo.calculadora_indicadores import CalculadoraIndicadores
from app.dominio.calculo.calculadora_multiplos_mercado import CalculadoraMultiplosMercado
from app.dominio.montador_indicadores import MontadorDeIndicadores
from app.dominio.plano_contas.classificador import ClassificadorDePlano
from app.dominio.plano_contas.resolvedor import ResolvedorDeContas
from app.dominio.ttm import MontadorTtm


def montar_caso_de_uso(settings: Settings, logger: Logger) -> CarregarFundamentos:
    banco = _montar_banco(settings, logger)
    return CarregarFundamentos(
        fonte=_montar_fonte_cvm(settings, logger),
        unidade_de_trabalho=UnidadeDeTrabalho(banco.fabrica_de_sessao),
        repositorio_universo=RepositorioUniversoSql(),
        repositorio_cadastro=RepositorioCadastroSql(),
        repositorio_fato=RepositorioFatoContabilSql(),
        repositorio_indicador=RepositorioIndicadorSql(),
        repositorio_execucao=RepositorioExecucaoSql(logger),
        verificador_de_schema=VerificadorDeSchema(colunas=COLUNAS_V16_FUNDAMENTOS),
        nome_do_banco=settings.db_name,
        montador=_montar_indicadores(),
        publicador=_montar_publicador(settings, logger),
        logger=logger,
        atualizador_mercado=_montar_metricas_mercado(banco, logger),
        repositorio_identidade=RepositorioIdentidadeSql(),
    )


def montar_carga_de_series(settings: Settings, logger: Logger) -> CarregarSeriesHistoricas:
    banco = _montar_banco(settings, logger)
    fonte_b3 = FonteB3(
        cliente=ClienteHttpB3(settings.b3_base_url, logger, settings.http_timeout),
        cache=CacheDeArquivos(settings.b3_cache_dir),
        leitor=LeitorCotahist(),
    )
    return CarregarSeriesHistoricas(
        fonte=fonte_b3,
        unidade_de_trabalho=UnidadeDeTrabalho(banco.fabrica_de_sessao),
        repositorio_series=RepositorioSeriesSql(),
        repositorio_execucao=RepositorioExecucaoSql(logger),
        logger=logger,
        atualizador_mercado=_montar_metricas_mercado(banco, logger),
        repositorio_identidade=RepositorioIdentidadeSql(),
        verificador_de_schema=VerificadorDeSchema(
            ("cotacao_b3_diaria", "opcao_b3_diaria", "etl_execucao"),
            colunas=COLUNAS_V16_COTAHIST,
        ),
        nome_do_banco=settings.db_name,
        fonte_opcoes=fonte_b3,
        repositorio_opcao=RepositorioOpcaoSql(),
    )


def montar_carga_ttm(settings: Settings, logger: Logger) -> CarregarTtm:
    banco = _montar_banco(settings, logger)
    return CarregarTtm(
        fonte=_montar_fonte_cvm(settings, logger),
        unidade_de_trabalho=UnidadeDeTrabalho(banco.fabrica_de_sessao),
        repositorio_universo=RepositorioUniversoSql(),
        repositorio_cadastro=RepositorioCadastroSql(),
        repositorio_fato=RepositorioFatoContabilSql(),
        repositorio_indicador=RepositorioIndicadorSql(),
        repositorio_execucao=RepositorioExecucaoSql(logger),
        montador_ttm=MontadorTtm(),
        montador_indicadores=_montar_indicadores(),
        logger=logger,
        repositorio_identidade=RepositorioIdentidadeSql(),
    )


def montar_carga_de_comunicados(settings: Settings, logger: Logger) -> CarregarComunicados:
    banco = _montar_banco(settings, logger)
    return CarregarComunicados(
        fonte=FonteIpe(
            cliente=ClienteHttpCvm(settings.cvm_base_url, logger, settings.http_timeout),
            cache=CacheDeArquivos(settings.cvm_cache_dir),
            logger=logger,
        ),
        unidade_de_trabalho=UnidadeDeTrabalho(banco.fabrica_de_sessao),
        repositorio_universo=RepositorioUniversoSql(),
        consulta_de_tickers=RepositorioCadastroSql(),
        repositorio_comunicado=RepositorioComunicadoSql(),
        repositorio_execucao=RepositorioExecucaoSql(logger),
        # So o que esta carga le e escreve: comunicados nao dependem das
        # tabelas contabeis, e exigi-las aqui bloquearia sem motivo.
        verificador_de_schema=VerificadorDeSchema(
            ("ativo_monitorado", "cvm_ticker", "etl_execucao", "comunicado_cvm")
        ),
        nome_do_banco=settings.db_name,
        publicador=_montar_publicador(settings, logger, settings.fila_comunicados),
        logger=logger,
    )


def montar_carga_proventos(settings: Settings, logger: Logger) -> CarregarProventosContabeis:
    banco = _montar_banco(settings, logger)
    return CarregarProventosContabeis(
        fonte=_montar_fonte_cvm(settings, logger),
        unidade_de_trabalho=UnidadeDeTrabalho(banco.fabrica_de_sessao),
        repositorio_universo=RepositorioUniversoSql(),
        repositorio_cadastro=RepositorioCadastroSql(),
        repositorio_provento=RepositorioProventoSql(),
        repositorio_execucao=RepositorioExecucaoSql(logger),
        logger=logger,
        repositorio_identidade=RepositorioIdentidadeSql(),
        verificador_de_schema=VerificadorDeSchema(
            ("cvm_ticker", "etl_execucao", "provento_contabil"),
            colunas={"provento_contabil": COLUNAS_V16_FUNDAMENTOS["provento_contabil"]},
        ),
        nome_do_banco=settings.db_name,
    )


def montar_eventos_corporativos(
    settings: Settings, logger: Logger
) -> InferirEventosCorporativos:
    banco = _montar_banco(settings, logger)
    return InferirEventosCorporativos(
        unidade_de_trabalho=UnidadeDeTrabalho(banco.fabrica_de_sessao),
        repositorio=RepositorioEventoCorporativoSql(),
        repositorio_execucao=RepositorioExecucaoSql(logger),
        logger=logger,
    )


def montar_liquidez(settings: Settings, logger: Logger) -> CalcularLiquidez:
    from app.adaptadores.persistencia.repositorio_liquidez import (
        RepositorioLiquidezSql,  # noqa: PLC0415
    )

    banco = _montar_banco(settings, logger)
    return CalcularLiquidez(
        unidade_de_trabalho=UnidadeDeTrabalho(banco.fabrica_de_sessao),
        repositorio=RepositorioLiquidezSql(),
        repositorio_execucao=RepositorioExecucaoSql(logger),
        logger=logger,
    )


def montar_prontidao(settings: Settings, logger: Logger):
    """OPR-ETL-4/5: auditoria e prontidao do pregao; apos SUCESSO dispara gerar-insights via SQS."""
    from app.aplicacao.prontidao_operacional import registrar_prontidao  # noqa: PLC0415

    banco = _montar_banco(settings, logger)
    uow = UnidadeDeTrabalho(banco.fabrica_de_sessao)
    publicador_series = _montar_publicador(settings, logger, settings.fila_series_historicas)
    publicador_ativos = _montar_publicador(settings, logger, settings.fila_tratar_ativos)

    def executar():
        resultado = registrar_prontidao(uow, RepositorioExecucaoSql(logger), logger)
        if resultado and resultado.pronto:
            _publicar_series_historicas(uow, resultado.data_pregao, publicador_series, logger)
            _publicar_cotacoes_ativos(uow, publicador_ativos, logger)
        return resultado

    return executar


def montar_qualidade_opcoes(settings: Settings, logger: Logger):
    """OPT-ETL-4: metricas de qualidade da cadeia de opcoes, depois da carga do COTAHIST."""
    from app.aplicacao.qualidade_opcoes import registrar_qualidade_opcoes  # noqa: PLC0415

    banco = _montar_banco(settings, logger)
    return lambda: registrar_qualidade_opcoes(
        UnidadeDeTrabalho(banco.fabrica_de_sessao), RepositorioExecucaoSql(logger), logger)


def montar_checagens(settings: Settings, logger: Logger):
    """TASK-39: checagens de qualidade de dados ao fim de cada carga completa."""
    from app.checagens.checagem_dados import executar_todas  # noqa: PLC0415

    uow = UnidadeDeTrabalho(_montar_banco(settings, logger).fabrica_de_sessao)

    def _executar() -> dict[str, int]:
        with uow.transacao() as db:
            resultado = executar_todas(db)
        total = sum(resultado.values())
        if total:
            logger.info("Checagens de qualidade: %d ocorrencia(s) gravada(s)", total)
        return resultado

    return _executar


def montar_conciliacao(settings: Settings, logger: Logger) -> ConciliarPrecos:
    banco = _montar_banco(settings, logger)
    return ConciliarPrecos(
        unidade_de_trabalho=UnidadeDeTrabalho(banco.fabrica_de_sessao),
        repositorio=RepositorioConciliacaoSql(),
        repositorio_execucao=RepositorioExecucaoSql(logger),
        logger=logger,
    )


def _montar_metricas_mercado(banco, logger: Logger) -> AtualizarMetricasMercado:
    return AtualizarMetricasMercado(
        unidade_de_trabalho=UnidadeDeTrabalho(banco.fabrica_de_sessao),
        repositorio=RepositorioMetricasMercadoSql(),
        calculadora=CalculadoraMultiplosMercado(),
        logger=logger,
    )


def _publicar_cotacoes_ativos(uow, publicador, logger) -> None:
    """Publica snapshots de fechamento em tratar-ativos para os ultimos 90 dias.

    Cada (simbolo, data_pregao) vira uma mensagem no formato CTR-01 (ativos.schema.json).
    O gerar-insights usa o regularMarketTime para identificar o pregao e avaliar sinais.
    90 dias cobre a janela de avaliacao do gerar-insights e garante catchup de pregoes
    que ficaram sem trigger apos a migracao para COTAHIST.
    """
    from sqlalchemy import text  # noqa: PLC0415

    try:
        with uow.transacao() as db:
            linhas = db.execute(text(
                "SELECT c.simbolo, c.data_pregao, c.abertura, c.maxima, c.minima, "
                "       c.fechamento, c.volume "
                "FROM cotacao_b3_diaria c "
                "JOIN ativo_monitorado m ON m.simbolo = c.simbolo "
                "WHERE m.ativo = 1 AND c.fechamento IS NOT NULL "
                "  AND c.data_pregao >= DATE_SUB(CURDATE(), INTERVAL 90 DAY) "
                "ORDER BY c.data_pregao, c.simbolo"
            )).all()

        candles = [
            {
                "simbolo": r.simbolo,
                "data_pregao": r.data_pregao,
                "abertura": r.abertura,
                "maxima": r.maxima,
                "minima": r.minima,
                "fechamento": r.fechamento,
                "volume": r.volume,
            }
            for r in linhas
        ]

        enviados = publicador.publicar_cotacoes_ativos(candles)
        logger.info(
            "Cotacoes publicadas em tratar-ativos: %d mensagem(ns) para %d ativo(s)",
            enviados, len({c["simbolo"] for c in candles}),
        )
    except Exception as erro:
        logger.error("Falha ao publicar cotacoes em tratar-ativos (dado ja persistido): %s", erro)


def _publicar_series_historicas(uow, data_pregao, publicador, logger) -> None:
    """Publica candles dos ativos monitorados em sqs-registrar-series-historicas (CTR-02).

    Envia todos os pregoes disponiveis em cotacao_b3_diaria para cada ativo
    monitorado ativo, um simbolo por mensagem. O gerar-insights faz upsert por
    candle e ignora reentregas via dedup_key; enviar o historico completo garante
    que pregoes passados sem trigger tambem sejam processados.
    """
    from sqlalchemy import text  # noqa: PLC0415

    try:
        with uow.transacao() as db:
            linhas = db.execute(text(
                "SELECT c.simbolo, c.data_pregao, c.abertura, c.maxima, c.minima, "
                "       c.fechamento, c.volume "
                "FROM cotacao_b3_diaria c "
                "JOIN ativo_monitorado m ON m.simbolo = c.simbolo "
                "WHERE m.ativo = 1 AND c.fechamento IS NOT NULL "
                "ORDER BY c.simbolo, c.data_pregao"
            )).all()

        por_simbolo: dict[str, list] = {}
        for row in linhas:
            por_simbolo.setdefault(row.simbolo, []).append({
                "data_pregao": row.data_pregao,
                "abertura": row.abertura,
                "maxima": row.maxima,
                "minima": row.minima,
                "fechamento": row.fechamento,
                "volume": row.volume,
            })

        for simbolo, candles in por_simbolo.items():
            publicador.publicar_series_historicas(simbolo, candles)

        logger.info(
            "Series historicas publicadas para %d ativo(s) monitorados (pregao %s)",
            len(por_simbolo), data_pregao,
        )
    except Exception as erro:
        # Falha nao derruba a carga: dado ja esta no banco.
        logger.error("Falha ao publicar series historicas (dado ja persistido): %s", erro)


def _montar_banco(settings: Settings, logger: Logger) -> ConfiguracaoDeBanco:
    banco = ConfiguracaoDeBanco(
        settings.database_url, logger, f"{settings.db_host}:{settings.db_port}"
    )
    banco.aguardar_banco()
    return banco


def _montar_fonte_cvm(settings: Settings, logger: Logger) -> FonteCvm:
    return FonteCvm(
        cliente=ClienteHttpCvm(settings.cvm_base_url, logger, settings.http_timeout),
        cache=CacheDeArquivos(settings.cvm_cache_dir),
        normalizador=NormalizadorDeLinhas(),
        logger=logger,
    )


def _montar_indicadores() -> MontadorDeIndicadores:
    return MontadorDeIndicadores(
        classificador=ClassificadorDePlano(),
        resolvedor=ResolvedorDeContas(),
        calculadora=CalculadoraIndicadores(),
    )


def _montar_publicador(
    settings: Settings, logger: Logger, nome_da_fila: str | None = None
) -> PublicadorSqs:
    cliente = boto3.client(
        "sqs",
        endpoint_url=settings.localstack_endpoint,
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    return PublicadorSqs(cliente, nome_da_fila or settings.fila_fundamentos, logger)
