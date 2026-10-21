"""Composition root das fontes publicas da V45 (FONTES-ETL-8).

Fica fora de `composicao.py` para nao disputar o arquivo com as demais cargas.
"""

from __future__ import annotations

from logging import Logger

from app.adaptadores.bcb.ifdata import URL_IFDATA, ClienteIfData
from app.adaptadores.cvm.cache_local import CacheDeArquivos
from app.adaptadores.cvm.cliente_http import ClienteHttpCvm
from app.adaptadores.cvm.fonte_cadastro import FonteCadastroCvm
from app.adaptadores.cvm.fonte_pacotes import FontePacotesCvm
from app.adaptadores.persistencia.repositorios import (
    RepositorioExecucaoSql,
    RepositorioFontesPublicasSql,
)
from app.adaptadores.persistencia.unidade_de_trabalho import UnidadeDeTrabalho
from app.adaptadores.persistencia.verificador_schema import VerificadorDeSchema
from app.adaptadores.tesouro.fonte_tesouro import URL_BASE as URL_TESOURO
from app.adaptadores.tesouro.fonte_tesouro import FonteTesouro
from app.aplicacao.carregar_fontes_publicas import (
    CarregarCadastro,
    CarregarIfData,
    CarregarCda,
    CarregarFre,
    CarregarTesouro,
    CarregarVlmo,
)
from app.aplicacao.datas_ex_b3 import CarregarDatasEx, EventosEDatasEx
from app.config.composicao import _montar_banco, montar_eventos_corporativos
from app.config.settings import Settings


def _comum(settings: Settings, logger: Logger, tabelas: tuple[str, ...]):
    banco = _montar_banco(settings, logger)
    uow = UnidadeDeTrabalho(banco.fabrica_de_sessao)
    # confere o contrato V45 antes de qualquer download
    with uow.transacao() as db:
        VerificadorDeSchema((*tabelas, "etl_execucao")).conferir(db, settings.db_name)
    return uow, RepositorioFontesPublicasSql(), RepositorioExecucaoSql(logger)


def _pacotes(settings: Settings, logger: Logger) -> FontePacotesCvm:
    return FontePacotesCvm(
        ClienteHttpCvm(settings.cvm_base_url, logger, settings.http_timeout),
        ClienteHttpCvm(settings.cvm_fi_cda_base_url, logger, settings.http_timeout),
        CacheDeArquivos(settings.cvm_cache_dir),
        logger,
    )


def montar_carga_tesouro(settings: Settings, logger: Logger) -> CarregarTesouro:
    uow, repo, execucao = _comum(settings, logger, ("titulo_publico_taxa",))
    fonte = FonteTesouro(
        ClienteHttpCvm(URL_TESOURO, logger, settings.http_timeout),
        CacheDeArquivos(settings.cvm_cache_dir / "tesouro"),
    )
    return CarregarTesouro(fonte, uow, repo, execucao, logger)


def montar_carga_vlmo(settings: Settings, logger: Logger) -> CarregarVlmo:
    uow, repo, execucao = _comum(settings, logger, ("cvm_negociacao_administrador",))
    return CarregarVlmo(_pacotes(settings, logger), uow, repo, execucao, logger)


def montar_carga_fre(settings: Settings, logger: Logger) -> CarregarFre:
    uow, repo, execucao = _comum(
        settings, logger, ("cvm_auditor", "cvm_divida_valor_mobiliario")
    )
    return CarregarFre(_pacotes(settings, logger), uow, repo, execucao, logger)


def montar_carga_cda(settings: Settings, logger: Logger) -> CarregarCda:
    uow, repo, execucao = _comum(settings, logger, ("fundo_posicao_acao",))
    return CarregarCda(_pacotes(settings, logger), uow, repo, execucao, logger)


def montar_carga_cadastro(settings: Settings, logger: Logger) -> CarregarCadastro:
    uow, repo, execucao = _comum(settings, logger, ("cvm_cadastro",))
    fonte = FonteCadastroCvm(
        ClienteHttpCvm(settings.cvm_base_url, logger, settings.http_timeout),
        CacheDeArquivos(settings.cvm_cache_dir),
    )
    return CarregarCadastro(fonte, uow, repo, execucao, logger)


def montar_carga_ifdata(settings: Settings, logger: Logger) -> CarregarIfData:
    uow, repo, execucao = _comum(
        settings, logger, ("banco_indicador_trimestral", "cvm_ticker")
    )
    fonte = ClienteIfData(
        ClienteHttpCvm(URL_IFDATA, logger, settings.http_timeout),
        CacheDeArquivos(settings.cvm_cache_dir / "ifdata"),
    )
    return CarregarIfData(fonte, uow, repo, execucao, logger)


def montar_eventos_e_datas_ex(settings: Settings, logger: Logger) -> EventosEDatasEx:
    uow, repo, execucao = _comum(settings, logger, ("data_ex_b3", "cotacao_b3_diaria"))
    datas_ex = CarregarDatasEx(uow, repo, execucao, logger)
    return EventosEDatasEx(montar_eventos_corporativos(settings, logger), datas_ex, logger)
