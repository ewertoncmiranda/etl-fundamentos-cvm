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
from app.adaptadores.persistencia.repositorios import (
    RepositorioCadastroSql,
    RepositorioComunicadoSql,
    RepositorioExecucaoSql,
    RepositorioFatoContabilSql,
    RepositorioIdentidadeSql,
    RepositorioIndicadorSql,
    RepositorioSeriesSql,
    RepositorioUniversoSql,
)
from app.adaptadores.persistencia.unidade_de_trabalho import UnidadeDeTrabalho
from app.adaptadores.persistencia.verificador_schema import VerificadorDeSchema
from app.aplicacao.carregar_comunicados import CarregarComunicados
from app.aplicacao.carregar_fundamentos import CarregarFundamentos
from app.aplicacao.carregar_series_historicas import CarregarSeriesHistoricas
from app.aplicacao.carregar_ttm import CarregarTtm
from app.config.database_config import ConfiguracaoDeBanco
from app.config.settings import Settings
from app.dominio.calculo.calculadora_indicadores import CalculadoraIndicadores
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
        verificador_de_schema=VerificadorDeSchema(),
        nome_do_banco=settings.db_name,
        montador=_montar_indicadores(),
        publicador=_montar_publicador(settings, logger),
        logger=logger,
        repositorio_identidade=RepositorioIdentidadeSql(),
    )


def montar_carga_de_series(settings: Settings, logger: Logger) -> CarregarSeriesHistoricas:
    banco = _montar_banco(settings, logger)
    return CarregarSeriesHistoricas(
        fonte=FonteB3(
            cliente=ClienteHttpB3(settings.b3_base_url, logger, settings.http_timeout),
            cache=CacheDeArquivos(settings.b3_cache_dir),
            leitor=LeitorCotahist(),
        ),
        unidade_de_trabalho=UnidadeDeTrabalho(banco.fabrica_de_sessao),
        repositorio_universo=RepositorioUniversoSql(),
        repositorio_series=RepositorioSeriesSql(),
        repositorio_execucao=RepositorioExecucaoSql(logger),
        logger=logger,
        repositorio_identidade=RepositorioIdentidadeSql(),
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
