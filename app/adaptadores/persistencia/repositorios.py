"""Repositorios SQLAlchemy.

Duas regras seguidas a risca, ambas corrigindo problemas catalogados no repo
irmao (gerar-insights#ISS-01 e #ISS-02):

  1. A Session entra como parametro, nunca e guardada. E o que permite testar
     sem banco.
  2. Repositorio NAO da commit. O commit acontece so na unidade de trabalho -
     do contrario uma falha no meio deixa metade da carga gravada.

Os upserts usam INSERT ... ON DUPLICATE KEY UPDATE do dialeto MySQL, em lote,
em vez do read-then-write que o repo irmao faz (N+1 e sujeito a corrida).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from logging import Logger
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.adaptadores.persistencia.entidade.entidades import (
    ComposicaoCapitalEntity,
    EmpresaEntity,
    ExecucaoEntity,
    FatoContabilEntity,
    IndicadorFundamentalistaEntity,
    TickerEntity,
)
from app.dominio.modelo import (
    STATUS_SUCESSO,
    ComposicaoCapital,
    Empresa,
    Indicadores,
    LinhaContabil,
    Ticker,
)
from app.dominio.texto import normalizar

# Grava em blocos para nao montar um INSERT gigante nem estourar max_allowed_packet
TAMANHO_DO_LOTE = 500


def _em_lotes(itens: Sequence[dict], tamanho: int = TAMANHO_DO_LOTE):
    for inicio in range(0, len(itens), tamanho):
        yield itens[inicio : inicio + tamanho]


def _upsert(
    db: Any,
    entidade: type,
    registros: Sequence[dict],
    colunas_a_atualizar: Sequence[str],
) -> int:
    if not registros:
        return 0
    total = 0
    for lote in _em_lotes(list(registros)):
        comando = mysql_insert(entidade).values(lote)
        comando = comando.on_duplicate_key_update(
            **{coluna: comando.inserted[coluna] for coluna in colunas_a_atualizar}
        )
        db.execute(comando)
        total += len(lote)
    return total


class RepositorioUniversoSql:
    """Le o universo de ativo_monitorado - a mesma tabela que o gestor popula
    via POST /ativos/registrar/{ativo}. Um lugar so para escolher ativo."""

    def listar_simbolos_monitorados(self, db: Any) -> list[str]:
        from sqlalchemy import text

        resultado = db.execute(
            text(
                "SELECT simbolo FROM ativo_monitorado WHERE ativo = TRUE ORDER BY simbolo"
            )
        )
        return [linha[0].strip().upper() for linha in resultado if linha[0]]


class RepositorioCadastroSql:
    def salvar_empresas(self, db: Any, empresas: Sequence[Empresa]) -> int:
        registros = [
            {
                "cnpj": e.cnpj,
                "cd_cvm": e.cd_cvm,
                "denominacao": e.denominacao or e.cnpj,
                "setor": e.setor,
                "plano_contas": e.plano_contas,
            }
            for e in empresas
        ]
        return _upsert(
            db,
            EmpresaEntity,
            registros,
            ("cd_cvm", "denominacao", "setor", "plano_contas"),
        )

    def salvar_tickers(self, db: Any, tickers: Sequence[Ticker]) -> int:
        registros = [
            {
                "simbolo": t.simbolo,
                "cnpj": t.cnpj,
                "tipo_valor_mobiliario": t.tipo_valor_mobiliario,
                "mercado": t.mercado,
                "ativo": True,
            }
            for t in tickers
        ]
        return _upsert(
            db,
            TickerEntity,
            registros,
            ("cnpj", "tipo_valor_mobiliario", "mercado", "ativo"),
        )


class RepositorioFatoContabilSql:
    def salvar_linhas(
        self,
        db: Any,
        cnpj: str,
        tipo_doc: str,
        grupo: str,
        versao: int,
        dt_refer: date,
        linhas: Sequence[LinhaContabil],
    ) -> int:
        registros = [
            {
                "cnpj": cnpj,
                "tipo_doc": tipo_doc,
                "grupo": grupo,
                "demonstracao": linha.demonstracao,
                "dt_refer": dt_refer,
                "dt_ini_exerc": linha.dt_ini_exerc,
                "dt_fim_exerc": linha.dt_fim_exerc,
                "versao": versao,
                "cd_conta": linha.cd_conta,
                "ds_conta": linha.ds_conta[:200] if linha.ds_conta else None,
                "vl_conta": linha.vl_conta,
                "conta_fixa": linha.conta_fixa,
                "ds_conta_norm": normalizar(linha.ds_conta)[:200],
            }
            for linha in linhas
        ]
        return _upsert(
            db,
            FatoContabilEntity,
            registros,
            ("ds_conta", "vl_conta", "conta_fixa", "ds_conta_norm", "versao", "dt_refer"),
        )

    def salvar_composicao(self, db: Any, capital: ComposicaoCapital, tipo_doc: str) -> None:
        registro = {
            "cnpj": capital.cnpj,
            "dt_refer": capital.dt_refer,
            "tipo_doc": tipo_doc,
            "versao": 1,
            "qt_acao_ex_tesouraria": capital.acoes_ex_tesouraria,
            "qt_acao_total": capital.acoes_ex_tesouraria,
        }
        _upsert(
            db,
            ComposicaoCapitalEntity,
            [registro],
            ("qt_acao_ex_tesouraria", "qt_acao_total", "versao"),
        )


class RepositorioIndicadorSql:
    COLUNAS_ATUALIZAVEIS = (
        "cnpj",
        "lucro_liquido",
        "patrimonio_liquido",
        "lucro_liquido_controlador",
        "participacao_nao_controladores",
        "receita_liquida",
        "ebit",
        "divida_bruta",
        "caixa_equivalentes",
        "fluxo_caixa_operacional",
        "capex",
        "acoes_ex_tesouraria",
        "lpa",
        "vpa",
        "roe",
        "roic",
        "margem_liquida",
        "divida_liquida",
        "fluxo_caixa_livre",
        "fonte",
        "tipo_doc",
        "grupo",
        "versao_cvm",
        "plano_contas",
        "cobertura_json",
    )

    def salvar(self, db: Any, indicadores: Sequence[Indicadores]) -> int:
        registros = [
            {
                "simbolo": i.simbolo,
                "cnpj": i.cnpj,
                "periodo": i.periodo,
                "tipo_periodo": i.tipo_periodo,
                "lucro_liquido": i.lucro_liquido,
                "patrimonio_liquido": i.patrimonio_liquido,
                "lucro_liquido_controlador": i.lucro_liquido_controlador,
                "participacao_nao_controladores": i.participacao_nao_controladores,
                "receita_liquida": i.receita_liquida,
                "ebit": i.ebit,
                "divida_bruta": i.divida_bruta,
                "caixa_equivalentes": i.caixa_equivalentes,
                "fluxo_caixa_operacional": i.fluxo_caixa_operacional,
                "capex": i.capex,
                "acoes_ex_tesouraria": i.acoes_ex_tesouraria,
                "lpa": i.lpa,
                "vpa": i.vpa,
                "roe": i.roe,
                "roic": i.roic,
                "margem_liquida": i.margem_liquida,
                "divida_liquida": i.divida_liquida,
                "fluxo_caixa_livre": i.fluxo_caixa_livre,
                "fonte": i.fonte,
                "tipo_doc": i.tipo_doc,
                "grupo": i.grupo,
                "versao_cvm": i.versao_cvm,
                "plano_contas": i.plano_contas,
                "cobertura_json": i.cobertura,
            }
            for i in indicadores
        ]
        return _upsert(db, IndicadorFundamentalistaEntity, registros, self.COLUNAS_ATUALIZAVEIS)


class RepositorioExecucaoSql:
    """Log append-only. Guarda o ETag da ultima carga bem-sucedida de cada
    arquivo, que e o que permite pular o download quando nada mudou."""

    def __init__(self, logger: Logger):
        self._logger = logger

    def etag_da_ultima_execucao(
        self, db: Any, fonte: str, competencia: str, arquivo: str
    ) -> str | None:
        consulta = (
            select(ExecucaoEntity.etag)
            .where(
                ExecucaoEntity.fonte == fonte,
                ExecucaoEntity.competencia == competencia,
                ExecucaoEntity.arquivo == arquivo,
                ExecucaoEntity.status == STATUS_SUCESSO,
            )
            .order_by(ExecucaoEntity.finalizado_em.desc())
            .limit(1)
        )
        return db.execute(consulta).scalar_one_or_none()

    def registrar(
        self,
        db: Any,
        fonte: str,
        competencia: str,
        arquivo: str,
        status: str,
        etag: str | None = None,
        last_modified: str | None = None,
        tamanho_bytes: int | None = None,
        linhas_carregadas: int = 0,
        mensagem_erro: str | None = None,
    ) -> None:
        db.add(
            ExecucaoEntity(
                fonte=fonte,
                competencia=competencia,
                arquivo=arquivo,
                etag=etag,
                last_modified=last_modified,
                tamanho_bytes=tamanho_bytes,
                status=status,
                linhas_carregadas=linhas_carregadas,
                mensagem_erro=mensagem_erro,
                finalizado_em=datetime.now(),
            )
        )
