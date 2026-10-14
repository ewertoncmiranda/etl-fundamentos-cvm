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
    OpcaoB3DiariaEntity,
    SerieHistoricaEntity,
    TickerEntity,
)
from app.dominio.calculo.calculadora_multiplos_mercado import InsumoMercado, MetricaMercado
from app.dominio.modelo import (
    STATUS_SUCESSO,
    ComposicaoCapital,
    Empresa,
    Indicadores,
    LinhaContabil,
    Ticker,
)
from app.dominio.serie_historica import CandleB3, OpcaoB3
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
                "cnae": e.cnae,
                "grupo_economico": e.grupo_economico,
            }
            for e in empresas
        ]
        return _upsert(
            db,
            EmpresaEntity,
            registros,
            ("cd_cvm", "denominacao", "setor", "plano_contas", "cnae", "grupo_economico"),
        )

    def salvar_tickers(self, db: Any, tickers: Sequence[Ticker]) -> int:
        registros = [
            {
                "simbolo": t.simbolo,
                "cnpj": t.cnpj,
                "tipo_valor_mobiliario": t.tipo_valor_mobiliario,
                "mercado": t.mercado,
                "ativo": True,
                "free_float": t.free_float,
            }
            for t in tickers
        ]
        return _upsert(
            db,
            TickerEntity,
            registros,
            ("cnpj", "tipo_valor_mobiliario", "mercado", "ativo", "free_float"),
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
        "resultado_financeiro",
        "passivo_nao_circulante",
        "impostos_dva",
        "estoques",
        "contas_a_receber",
        "despesas_pessoal",
        "depreciacao_amortizacao",
        "ativo_circulante",
        "passivo_circulante",
        "lpa",
        "vpa",
        "roe",
        "roic",
        "margem_liquida",
        "divida_liquida",
        "fluxo_caixa_livre",
        "ebitda",
        "cobertura_juros",
        "liquidez_corrente",
        "liquidez_seca",
        "dso",
        "graham_number",
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
                "resultado_financeiro": i.resultado_financeiro,
                "passivo_nao_circulante": i.passivo_nao_circulante,
                "impostos_dva": i.impostos_dva,
                "estoques": i.estoques,
                "contas_a_receber": i.contas_a_receber,
                "despesas_pessoal": i.despesas_pessoal,
                "depreciacao_amortizacao": i.depreciacao_amortizacao,
                "ativo_circulante": i.ativo_circulante,
                "passivo_circulante": i.passivo_circulante,
                "lpa": i.lpa,
                "vpa": i.vpa,
                "roe": i.roe,
                "roic": i.roic,
                "margem_liquida": i.margem_liquida,
                "divida_liquida": i.divida_liquida,
                "fluxo_caixa_livre": i.fluxo_caixa_livre,
                "ebitda": i.ebitda,
                "cobertura_juros": i.cobertura_juros,
                "liquidez_corrente": i.liquidez_corrente,
                "liquidez_seca": i.liquidez_seca,
                "dso": i.dso,
                "graham_number": i.graham_number,
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


class RepositorioSeriesSql:
    def salvar_candles_b3(self, db: Any, candles: Sequence[CandleB3]) -> int:
        registros = [
            {
                "simbolo": candle.simbolo,
                "data_pregao": candle.data_pregao,
                "intervalo": "1d",
                "range_usado": "1y",
                "abertura": candle.abertura,
                "maxima": candle.maxima,
                "minima": candle.minima,
                "fechamento": candle.fechamento,
                "fechamento_ajustado": None,
                "volume": candle.volume,
                "fonte": "B3",
                "detalhes_json": {
                    "preco_ajustado": False,
                    "numero_negocios": candle.numero_negocios,
                    "volume_financeiro": str(candle.volume_financeiro),
                    "moeda_referencia": candle.moeda_referencia,
                },
            }
            for candle in candles
        ]
        return _upsert(
            db,
            SerieHistoricaEntity,
            registros,
            (
                "range_usado", "abertura", "maxima", "minima", "fechamento",
                "fechamento_ajustado", "volume", "fonte", "detalhes_json",
            ),
        )


class RepositorioOpcaoSql:
    """Grava cotacoes diarias de opcoes da B3 (tabela opcao_b3_diaria).

    indice_correcao (C1/Phase-0) e gravado apenas se a coluna ja existe no DB
    (migracao V36 pode estar atrasada em relacao ao deploy do ETL).
    """

    _COLUNAS_FIXAS = (
        "bdi",
        "data_vencimento",
        "preco_exercicio",
        "abertura",
        "maxima",
        "minima",
        "fechamento",
        "preco_medio",
        "volume",
        "numero_negocios",
        "volume_financeiro",
        "fator_cotacao",
        "isin",
        "ativo_objeto",
        "tipo_opcao",
        "status_validacao",
        "motivo_rejeicao",
    )
    _COLUNAS_OPCIONAIS = ("indice_correcao", "melhor_oferta_compra", "melhor_oferta_venda")

    def _colunas_existentes(self, db: Any) -> set[str]:
        from sqlalchemy import text

        resultado = db.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'opcao_b3_diaria'"
            )
        )
        return {r[0] for r in resultado}

    def salvar_opcoes(self, db: Any, opcoes: Sequence[OpcaoB3]) -> int:
        if not opcoes:
            return 0
        colunas_db = self._colunas_existentes(db)
        tem_opt = {c for c in self._COLUNAS_OPCIONAIS if c in colunas_db}

        registros = []
        for o in opcoes:
            reg: dict[str, Any] = {
                "simbolo": o.simbolo,
                "bdi": o.bdi,
                "data_pregao": o.data_pregao,
                "data_vencimento": o.data_vencimento,
                "preco_exercicio": o.preco_exercicio,
                "abertura": o.abertura,
                "maxima": o.maxima,
                "minima": o.minima,
                "fechamento": o.fechamento,
                "preco_medio": o.preco_medio,
                "volume": o.volume,
                "numero_negocios": o.numero_negocios,
                "volume_financeiro": o.volume_financeiro,
                "fator_cotacao": o.fator_cotacao,
                "isin": o.isin,
                "ativo_objeto": o.ativo_objeto,
                "tipo_opcao": o.tipo_opcao,
                "status_validacao": o.status_validacao,
                "motivo_rejeicao": o.motivo_rejeicao,
            }
            for col in tem_opt:
                reg[col] = getattr(o, col, None)
            registros.append(reg)

        colunas_atualizar = list(self._COLUNAS_FIXAS) + sorted(tem_opt)
        return _upsert(db, OpcaoB3DiariaEntity, registros, colunas_atualizar)


class RepositorioMetricasMercadoSql:
    """Le insumos contabeis + cotacoes e grava P/L (I4) e EV/EBITDA (I7).

    As tres queries usam bindparam(expanding=True) para IN dinamico, que e a
    forma correta no SQLAlchemy 2 com dialeto MySQL.
    """

    def buscar_insumos_de_mercado(
        self, db: Any, simbolos: list[str], ano: int
    ) -> list[InsumoMercado]:
        from decimal import Decimal as _D

        from sqlalchemy import bindparam, text

        resultado = db.execute(
            text(
                "SELECT i.simbolo, i.periodo, i.lpa, i.ebitda, i.divida_liquida, "
                "i.acoes_ex_tesouraria, e.cnae "
                "FROM indicador_fundamentalista i "
                "LEFT JOIN cvm_empresa e ON i.cnpj = e.cnpj "
                "WHERE i.simbolo IN :simbolos "
                "AND YEAR(i.periodo) = :ano "
                "AND i.tipo_periodo = 'ANUAL'"
            ).bindparams(bindparam("simbolos", expanding=True)),
            {"simbolos": list(simbolos), "ano": ano},
        )
        return [
            InsumoMercado(
                simbolo=row[0],
                periodo=row[1],
                lpa=_D(str(row[2])) if row[2] is not None else None,
                ebitda=_D(str(row[3])) if row[3] is not None else None,
                divida_liquida=_D(str(row[4])) if row[4] is not None else None,
                acoes_ex_tesouraria=int(row[5]) if row[5] is not None else None,
                cnae=row[6],
            )
            for row in resultado
        ]

    def buscar_precos_na_data(
        self, db: Any, simbolos: list[str], data_referencia: Any
    ) -> dict[str, Any]:
        from decimal import Decimal as _D

        from sqlalchemy import bindparam, text

        resultado = db.execute(
            text(
                "SELECT s1.simbolo, s1.fechamento "
                "FROM serie_historica s1 "
                "INNER JOIN ("
                "    SELECT simbolo, MAX(data_pregao) AS ultima_data "
                "    FROM serie_historica "
                "    WHERE simbolo IN :simbolos "
                "    AND data_pregao <= :data_ref "
                "    AND fechamento IS NOT NULL "
                "    GROUP BY simbolo"
                ") s2 ON s1.simbolo = s2.simbolo AND s1.data_pregao = s2.ultima_data"
            ).bindparams(bindparam("simbolos", expanding=True)),
            {"simbolos": list(simbolos), "data_ref": data_referencia},
        )
        return {row[0]: _D(str(row[1])) for row in resultado}

    def atualizar_metricas_mercado(self, db: Any, metricas: list[MetricaMercado]) -> int:
        from sqlalchemy import text

        total = 0
        for m in metricas:
            if m.pl is None and m.ev_ebitda is None and m.pl_setorial_mediana is None:
                continue
            db.execute(
                text(
                    "UPDATE indicador_fundamentalista "
                    "SET pl = :pl, ev_ebitda = :ev, pl_setorial_mediana = :pl_set "
                    "WHERE simbolo = :simbolo AND periodo = :periodo"
                ),
                {
                    "pl": float(m.pl) if m.pl is not None else None,
                    "ev": float(m.ev_ebitda) if m.ev_ebitda is not None else None,
                    "pl_set": (
                        float(m.pl_setorial_mediana)
                        if m.pl_setorial_mediana is not None
                        else None
                    ),
                    "simbolo": m.simbolo,
                    "periodo": m.periodo,
                },
            )
            total += 1
        return total


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
