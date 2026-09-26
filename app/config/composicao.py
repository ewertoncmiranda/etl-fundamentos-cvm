"""Composition root: o unico lugar do app que conhece classes concretas.

Todo o resto recebe dependencia por construtor e conversa com Protocols. Se
amanha a fonte deixar de ser a CVM ou o banco deixar de ser MySQL, e aqui que
se troca - e so aqui.
"""

from __future__ import annotations

from logging import Logger

import boto3

from app.adaptadores.cvm.cache_local import CacheDeArquivos
from app.adaptadores.cvm.cliente_http import ClienteHttpCvm
from app.adaptadores.cvm.fonte_cvm import FonteCvm
from app.adaptadores.cvm.normalizador import NormalizadorDeLinhas
from app.adaptadores.mensageria.publicador_sqs import PublicadorSqs
from app.adaptadores.persistencia.repositorios import (
    RepositorioCadastroSql,
    RepositorioExecucaoSql,
    RepositorioFatoContabilSql,
    RepositorioIndicadorSql,
    RepositorioUniversoSql,
)
from app.adaptadores.persistencia.unidade_de_trabalho import UnidadeDeTrabalho
from app.aplicacao.carregar_fundamentos import CarregarFundamentos
from app.config.database_config import ConfiguracaoDeBanco
from app.config.settings import Settings
from app.dominio.calculo.calculadora_indicadores import CalculadoraIndicadores
from app.dominio.montador_indicadores import MontadorDeIndicadores
from app.dominio.plano_contas.classificador import ClassificadorDePlano
from app.dominio.plano_contas.resolvedor import ResolvedorDeContas


def montar_caso_de_uso(settings: Settings, logger: Logger) -> CarregarFundamentos:
    banco = ConfiguracaoDeBanco(settings.database_url, logger)
    banco.aguardar_banco()

    fonte = FonteCvm(
        cliente=ClienteHttpCvm(settings.cvm_base_url, logger, settings.http_timeout),
        cache=CacheDeArquivos(settings.cvm_cache_dir),
        normalizador=NormalizadorDeLinhas(),
        logger=logger,
    )

    montador = MontadorDeIndicadores(
        classificador=ClassificadorDePlano(),
        resolvedor=ResolvedorDeContas(),
        calculadora=CalculadoraIndicadores(),
    )

    return CarregarFundamentos(
        fonte=fonte,
        unidade_de_trabalho=UnidadeDeTrabalho(banco.fabrica_de_sessao),
        repositorio_universo=RepositorioUniversoSql(),
        repositorio_cadastro=RepositorioCadastroSql(),
        repositorio_fato=RepositorioFatoContabilSql(),
        repositorio_indicador=RepositorioIndicadorSql(),
        repositorio_execucao=RepositorioExecucaoSql(logger),
        montador=montador,
        publicador=_montar_publicador(settings, logger),
        logger=logger,
    )


def _montar_publicador(settings: Settings, logger: Logger) -> PublicadorSqs:
    cliente = boto3.client(
        "sqs",
        endpoint_url=settings.localstack_endpoint,
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    return PublicadorSqs(cliente, settings.fila_fundamentos, logger)
