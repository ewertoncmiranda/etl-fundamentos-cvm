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

from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.adaptadores.persistencia.entidade.entidades import (
    ComposicaoCapitalEntity,
    ComunicadoCvmEntity,
    CotacaoB3DiariaEntity,
    EmpresaEntity,
    ExecucaoEntity,
    FatoContabilEntity,
    IndicadorFundamentalistaEntity,
    OpcaoB3DiariaEntity,
    ProventoContabilEntity,
    TickerEntity,
)
from app.dominio.comunicado import Comunicado
from app.dominio.identidade import Identidade
from app.dominio.modelo import (
    STATUS_SUCESSO,
    ComposicaoCapital,
    Empresa,
    Indicadores,
    LinhaContabil,
    Ticker,
)
from app.dominio.provento import RegistroProvento
from app.dominio.serie_historica import CandleB3, OpcaoB3
from app.dominio.texto import normalizar
from app.dominio.validacao_acoes import conferir_acoes

# Grava em blocos para nao montar um INSERT gigante nem estourar max_allowed_packet
TAMANHO_DO_LOTE = 500


def _em_lotes(itens: Sequence[Any], tamanho: int = TAMANHO_DO_LOTE):
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

    # Mesma regra do universo do backtest (gerar-insights app/validacao/
    # universo.py, infra#TASK-31): >= 200 pregoes e volume medio >= R$ 5 mi/dia
    # em algum ano, sem units (11) nem BDRs (31-39) fora da ativo_identidade.
    PREGOES_MINIMOS = 200
    LIQUIDEZ_MINIMA = 5_000_000

    def listar_simbolos_liquidos(self, db: Any) -> list[str]:
        """Todo codigo que entrou no universo do backtest em algum ano, com os
        monitorados - e quem precisa de balanco para o backtest amplo."""
        from sqlalchemy import text

        resultado = db.execute(
            text(
                "SELECT DISTINCT t.simbolo FROM ("
                "  SELECT simbolo, YEAR(data_pregao) ano, COUNT(*) n, AVG(volume_financeiro) vol"
                "  FROM cotacao_b3_diaria GROUP BY simbolo, YEAR(data_pregao)"
                ") t WHERE t.n >= :pregoes AND t.vol >= :liquidez AND t.simbolo NOT LIKE '%11' "
                "AND (t.simbolo NOT REGEXP '3[1-9]$' "
                "     OR t.simbolo IN (SELECT simbolo FROM ativo_identidade)) "
                "UNION SELECT simbolo FROM ativo_monitorado WHERE ativo = TRUE"
            ),
            {"pregoes": self.PREGOES_MINIMOS, "liquidez": self.LIQUIDEZ_MINIMA},
        )
        return sorted(linha[0].strip().upper() for linha in resultado if linha[0])


class RepositorioIdentidadeSql:
    """Le ativo_identidade (curadoria de tickers renomeados, infra V6)."""

    def identidades(self, db: Any) -> dict[str, Identidade]:
        from sqlalchemy import text

        linhas = db.execute(
            text(
                "SELECT simbolo, simbolo_canonico, cnpj, continuidade_preco "
                "FROM ativo_identidade"
            )
        )
        return {
            simbolo: Identidade(simbolo, canonico, cnpj, bool(continuidade))
            for simbolo, canonico, cnpj, continuidade in linhas
        }


class RepositorioCadastroSql:
    def salvar_empresas(self, db: Any, empresas: Sequence[Empresa]) -> int:
        registros = [
            {
                "cnpj": e.cnpj,
                "cd_cvm": e.cd_cvm,
                "denominacao": e.denominacao or e.cnpj,
                "setor": e.setor,
                "plano_contas": e.plano_contas,
                "situacao_registro": e.situacao_registro,
                "data_constituicao": e.data_constituicao,
                "uf_municipio": e.uf_municipio,
            }
            for e in empresas
        ]
        return _upsert(
            db,
            EmpresaEntity,
            registros,
            (
                "cd_cvm", "denominacao", "setor", "plano_contas",
                "situacao_registro", "data_constituicao", "uf_municipio",
            ),
        )

    def salvar_tickers(self, db: Any, tickers: Sequence[Ticker]) -> int:
        registros = [
            {
                "simbolo": t.simbolo,
                "cnpj": t.cnpj,
                "tipo_valor_mobiliario": t.tipo_valor_mobiliario,
                "isin": t.isin,
                "mercado": t.mercado,
                "ativo": True,
            }
            for t in tickers
        ]
        return _upsert(
            db,
            TickerEntity,
            registros,
            ("cnpj", "tipo_valor_mobiliario", "isin", "mercado", "ativo"),
        )

    def cnpjs_por_simbolo(self, db: Any, simbolos: Sequence[str]) -> dict[str, str]:
        if not simbolos:
            return {}
        consulta = select(TickerEntity.simbolo, TickerEntity.cnpj).where(
            TickerEntity.simbolo.in_([s.strip().upper() for s in simbolos])
        )
        return {simbolo: cnpj for simbolo, cnpj in db.execute(consulta)}


def selecionar_para_gravar(
    recebidos: Sequence[Comunicado], versoes_gravadas: dict[str, int]
) -> list[Comunicado]:
    """O que e novo (protocolo desconhecido) ou reapresentado (versao maior).

    Funcao pura, fora do repositorio, para a regra ser testada sem banco.
    """
    return [
        c
        for c in recebidos
        if c.protocolo_cvm not in versoes_gravadas
        or c.versao > versoes_gravadas[c.protocolo_cvm]
    ]


class RepositorioComunicadoSql:
    """Le as versoes ja gravadas e so escreve o que mudou.

    Ler antes de escrever, aqui, nao e o read-then-write criticado no topo do
    modulo: e uma consulta por lote (nao por linha), feita pelo unico escritor
    da tabela, e serve para saber o que e novo - informacao que o
    ON DUPLICATE KEY UPDATE sozinho nao devolve.
    """

    COLUNAS_ATUALIZAVEIS = (
        "protocolo_entrega",
        "versao",
        "cnpj",
        "codigo_cvm",
        "categoria",
        "categoria_original",
        "tipo",
        "especie",
        "assunto",
        "data_referencia",
        "data_entrega",
        "link_download",
    )

    def salvar(self, db: Any, comunicados: Sequence[Comunicado]) -> list[Comunicado]:
        if not comunicados:
            return []

        versoes_gravadas: dict[str, int] = {}
        protocolos = [c.protocolo_cvm for c in comunicados]
        for lote in _em_lotes(protocolos):
            consulta = select(
                ComunicadoCvmEntity.protocolo_cvm, ComunicadoCvmEntity.versao
            ).where(ComunicadoCvmEntity.protocolo_cvm.in_(lote))
            versoes_gravadas.update({p: v for p, v in db.execute(consulta)})

        a_gravar = selecionar_para_gravar(comunicados, versoes_gravadas)
        registros = [
            {
                "protocolo_cvm": c.protocolo_cvm,
                "protocolo_entrega": c.protocolo_entrega,
                "versao": c.versao,
                "cnpj": c.cnpj,
                "codigo_cvm": c.codigo_cvm,
                "categoria": c.categoria,
                "categoria_original": c.categoria_original,
                "tipo": c.tipo,
                "especie": c.especie,
                "assunto": c.assunto,
                "data_referencia": c.data_referencia,
                "data_entrega": c.data_entrega,
                "link_download": c.link_download,
            }
            for c in a_gravar
        ]
        _upsert(db, ComunicadoCvmEntity, registros, self.COLUNAS_ATUALIZAVEIS)
        return a_gravar


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
                "coluna_df": linha.coluna_df,
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
            "qt_acao_ordinaria": capital.qt_acao_ordinaria,
            "qt_acao_preferencial": capital.qt_acao_preferencial,
            "qt_acao_ex_tesouraria": capital.acoes_ex_tesouraria,
            "qt_acao_total": capital.acoes_ex_tesouraria,
        }
        _upsert(
            db,
            ComposicaoCapitalEntity,
            [registro],
            (
                "qt_acao_ordinaria", "qt_acao_preferencial",
                "qt_acao_ex_tesouraria", "qt_acao_total", "versao",
            ),
        )


class RepositorioIndicadorSql:
    COLUNAS_ATUALIZAVEIS = (
        "cnpj",
        "lucro_liquido",
        "patrimonio_liquido",
        "ativo_total",
        "ativo_circulante",
        "passivo_circulante",
        "lucro_bruto",
        "lucro_liquido_controlador",
        "participacao_nao_controladores",
        "receita_liquida",
        "ebit",
        "divida_bruta",
        "caixa_equivalentes",
        "fluxo_caixa_operacional",
        "fco_bruto",
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
        "data_entrega",
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
                "ativo_total": i.ativo_total,
                "ativo_circulante": i.ativo_circulante,
                "passivo_circulante": i.passivo_circulante,
                "lucro_bruto": i.lucro_bruto,
                "lucro_liquido_controlador": i.lucro_liquido_controlador,
                "participacao_nao_controladores": i.participacao_nao_controladores,
                "receita_liquida": i.receita_liquida,
                "ebit": i.ebit,
                "divida_bruta": i.divida_bruta,
                "caixa_equivalentes": i.caixa_equivalentes,
                "fluxo_caixa_operacional": i.fluxo_caixa_operacional,
                "fco_bruto": i.fco_bruto,
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
                "data_entrega": i.data_entrega,
            }
            for i in indicadores
        ]
        return _upsert(db, IndicadorFundamentalistaEntity, registros, self.COLUNAS_ATUALIZAVEIS)

    def historico(
        self,
        db: Any,
        simbolo: str,
        tipo_periodo: str | None = None,
        limite: int | None = None,
    ) -> list[Indicadores]:
        """Le a serie do mart em ordem cronologica para API, painel e backtests."""

        consulta = (
            select(IndicadorFundamentalistaEntity)
            .where(IndicadorFundamentalistaEntity.simbolo == simbolo.strip().upper())
            .order_by(
                IndicadorFundamentalistaEntity.periodo.asc(),
                IndicadorFundamentalistaEntity.tipo_periodo.asc(),
            )
        )
        if tipo_periodo:
            consulta = consulta.where(
                IndicadorFundamentalistaEntity.tipo_periodo == tipo_periodo
            )
        if limite:
            consulta = consulta.limit(limite)

        resultado = db.execute(consulta)
        entidades = resultado.scalars().all()
        return [_indicador_da_entidade(entidade) for entidade in entidades]

    def conferir_acoes(self, db: Any, simbolos: Sequence[str]) -> list[str]:
        """Aplica dominio/validacao_acoes.py sobre a serie gravada de cada
        simbolo e devolve o que corrigiu ou anulou, para o log da carga."""
        from sqlalchemy import text

        if not simbolos:
            return []
        linhas = db.execute(
            text(
                "SELECT simbolo, periodo, tipo_periodo, acoes_ex_tesouraria "
                "FROM indicador_fundamentalista "
                "WHERE simbolo IN :s AND acoes_ex_tesouraria IS NOT NULL"
            ).bindparams(bindparam("s", expanding=True)),
            {"s": list(simbolos)},
        )
        por_simbolo: dict[str, dict[str, list]] = {}
        for simbolo, periodo, tipo, acoes in linhas:
            grupo = por_simbolo.setdefault(simbolo, {"anuais": [], "outros": []})
            if tipo == "ANUAL":
                grupo["anuais"].append((periodo, int(acoes)))
            else:
                grupo["outros"].append((periodo, tipo, int(acoes)))

        relatorio = []
        for simbolo, grupo in por_simbolo.items():
            for c in conferir_acoes(grupo["anuais"], grupo["outros"]):
                chave = {"s": simbolo, "p": c.periodo, "t": c.tipo_periodo, "m": c.motivo}
                if c.fator is None:
                    db.execute(
                        text(
                            "UPDATE indicador_fundamentalista SET lpa = NULL, vpa = NULL, "
                            "cobertura_json = JSON_SET(COALESCE(cobertura_json, JSON_OBJECT()), "
                            "'$.validacao_acoes', :m) "
                            "WHERE simbolo = :s AND periodo = :p AND tipo_periodo = :t"
                        ),
                        chave,
                    )
                else:
                    db.execute(
                        text(
                            "UPDATE indicador_fundamentalista SET "
                            "acoes_ex_tesouraria = ROUND(acoes_ex_tesouraria * :f), "
                            "lpa = lpa / :f, "
                            "vpa = vpa / :f, cobertura_json = JSON_SET(COALESCE(cobertura_json, "
                            "JSON_OBJECT()), '$.validacao_acoes', :m) "
                            "WHERE simbolo = :s AND periodo = :p AND tipo_periodo = :t"
                        ),
                        {**chave, "f": c.fator},
                    )
                relatorio.append(f"{simbolo} {c.periodo} {c.tipo_periodo}: {c.motivo}")
        return relatorio


def _indicador_da_entidade(entidade: IndicadorFundamentalistaEntity) -> Indicadores:
    return Indicadores(
        simbolo=entidade.simbolo,
        cnpj=entidade.cnpj,
        periodo=entidade.periodo,
        tipo_periodo=entidade.tipo_periodo,
        tipo_doc=entidade.tipo_doc,
        grupo=entidade.grupo,
        versao_cvm=entidade.versao_cvm,
        plano_contas=entidade.plano_contas,
        lucro_liquido=entidade.lucro_liquido,
        patrimonio_liquido=entidade.patrimonio_liquido,
        ativo_total=entidade.ativo_total,
        ativo_circulante=entidade.ativo_circulante,
        passivo_circulante=entidade.passivo_circulante,
        lucro_bruto=entidade.lucro_bruto,
        lucro_liquido_controlador=entidade.lucro_liquido_controlador,
        participacao_nao_controladores=entidade.participacao_nao_controladores,
        receita_liquida=entidade.receita_liquida,
        ebit=entidade.ebit,
        divida_bruta=entidade.divida_bruta,
        caixa_equivalentes=entidade.caixa_equivalentes,
        fluxo_caixa_operacional=entidade.fluxo_caixa_operacional,
        fco_bruto=entidade.fco_bruto,
        capex=entidade.capex,
        acoes_ex_tesouraria=entidade.acoes_ex_tesouraria,
        lpa=entidade.lpa,
        vpa=entidade.vpa,
        roe=entidade.roe,
        roic=entidade.roic,
        margem_liquida=entidade.margem_liquida,
        divida_liquida=entidade.divida_liquida,
        fluxo_caixa_livre=entidade.fluxo_caixa_livre,
        data_entrega=entidade.data_entrega,
        fonte=entidade.fonte,
        cobertura=entidade.cobertura_json or {},
    )


class RepositorioSeriesSql:
    """COTAHIST vai para cotacao_b3_diaria, nao para serie_historica: la ficam
    as velas da BRAPI, e a checagem cruzada de preco precisa das duas fontes
    lado a lado (a chave simbolo+data sobrescreveria uma com a outra)."""

    def salvar_candles_b3(self, db: Any, candles: Sequence[CandleB3]) -> int:
        registros = [
            {
                "simbolo": candle.simbolo,
                "data_pregao": candle.data_pregao,
                "abertura": candle.abertura,
                "maxima": candle.maxima,
                "minima": candle.minima,
                "fechamento": candle.fechamento,
                "volume": candle.volume,
                "numero_negocios": candle.numero_negocios,
                "volume_financeiro": candle.volume_financeiro,
                "isin": candle.isin,
                "especificacao": candle.especificacao,
                "marca_ex": candle.marca_ex,
                "fator_cotacao": candle.fator_cotacao,
                "preco_medio": candle.preco_medio,
                "melhor_oferta_compra": candle.melhor_oferta_compra,
                "melhor_oferta_venda": candle.melhor_oferta_venda,
            }
            for candle in candles
        ]
        return _upsert(
            db,
            CotacaoB3DiariaEntity,
            registros,
            (
                "abertura", "maxima", "minima", "fechamento", "volume",
                "numero_negocios", "volume_financeiro", "isin", "especificacao", "marca_ex",
                "fator_cotacao", "preco_medio", "melhor_oferta_compra", "melhor_oferta_venda",
            ),
        )


    def atualizar_isin_dos_tickers(self, db: Any) -> int:
        """O FCA (valor_mobiliario) nao traz ISIN: o do cvm_ticker vem do pregao mais recente
        do mesmo codigo de negociacao no COTAHIST. So muda quem esta nulo ou diferente."""
        resultado = db.execute(
            text(
                "UPDATE cvm_ticker t "
                "JOIN (SELECT c.simbolo, c.isin FROM cotacao_b3_diaria c "
                "      JOIN (SELECT simbolo, MAX(data_pregao) AS ultimo FROM cotacao_b3_diaria "
                "            WHERE isin IS NOT NULL AND isin <> '' GROUP BY simbolo) u "
                "        ON u.simbolo = c.simbolo AND u.ultimo = c.data_pregao "
                "      WHERE c.isin IS NOT NULL AND c.isin <> '') x ON x.simbolo = t.simbolo "
                "SET t.isin = x.isin "
                "WHERE t.isin IS NULL OR t.isin <> x.isin"
            )
        )
        return int(resultado.rowcount or 0)


class RepositorioOpcaoSql:
    def salvar_opcoes_b3(self, db: Any, opcoes: Sequence[OpcaoB3]) -> int:
        registros = [
            {
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
            }
            for o in opcoes
        ]
        return _upsert(
            db,
            OpcaoB3DiariaEntity,
            registros,
            (
                "bdi", "data_vencimento", "preco_exercicio",
                "abertura", "maxima", "minima", "fechamento", "preco_medio",
                "volume", "numero_negocios", "volume_financeiro",
                "fator_cotacao", "isin",
            ),
        )


class RepositorioProventoSql:
    """provento_contabil (infra V16): um periodo por (cnpj, tipo_doc, fim)."""

    def salvar(self, db: Any, registros: Sequence[RegistroProvento]) -> int:
        linhas = [
            {
                "cnpj": r.cnpj,
                "tipo_doc": r.periodo.tipo_doc,
                "dt_ini_exerc": r.periodo.dt_ini,
                "dt_fim_exerc": r.periodo.dt_fim,
                "versao": r.periodo.versao,
                "data_entrega": r.data_entrega,
                "jcp": r.periodo.jcp,
                "dividendos": r.periodo.dividendos,
                "acoes_ex_tesouraria": r.acoes_ex_tesouraria,
                "por_acao": r.por_acao,
                "origem": "CVM_DVA",
                "cobertura_json": r.cobertura(),
            }
            for r in registros
        ]
        return _upsert(
            db,
            ProventoContabilEntity,
            linhas,
            (
                "dt_ini_exerc", "versao", "data_entrega", "jcp", "dividendos",
                "acoes_ex_tesouraria", "por_acao", "cobertura_json",
            ),
        )


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
