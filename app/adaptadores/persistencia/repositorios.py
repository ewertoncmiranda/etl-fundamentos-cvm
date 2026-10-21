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
from datetime import date, datetime, timedelta
from decimal import Decimal
from logging import Logger
from typing import Any

from sqlalchemy import and_, bindparam, delete, func, or_, select, text
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.adaptadores.persistencia.entidade.entidades import (
    ComposicaoCapitalEntity,
    BancoIndicadorTrimestralEntity,
    ComunicadoCvmEntity,
    CotacaoB3DiariaEntity,
    DataExB3Entity,
    CvmAuditorEntity,
    CvmCadastroEntity,
    CvmDividaValorMobiliarioEntity,
    CvmNegociacaoAdministradorEntity,
    EmpresaEntity,
    ExecucaoEntity,
    FatoContabilEntity,
    FundoPosicaoAcaoEntity,
    IndicadorFundamentalistaEntity,
    NegociacaoB3DiariaEntity,
    OpcaoB3DiariaEntity,
    ProventoContabilEntity,
    SerieHistoricaEntity,
    TickerEntity,
    TituloPublicoTaxaEntity,
)
from app.adaptadores.cvm.cda import PosicaoFundoAcao
from app.aplicacao.contexto_carga import carga_atual
from app.dominio.calculo.calculadora_multiplos_mercado import InsumoMercado, MetricaMercado
from app.dominio.comunicado import Comunicado
from app.dominio.fontes_publicas import (
    cnpj14,
    cortar,
    hash_divida,
    hash_negociacao,
    texto_conversivel,
)
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
                "cnae": e.cnae,
                "grupo_economico": e.grupo_economico,
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
                "cnae", "grupo_economico",
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
                "free_float": t.free_float,
            }
            for t in tickers
        ]
        return _upsert(
            db,
            TickerEntity,
            registros,
            ("cnpj", "tipo_valor_mobiliario", "isin", "mercado", "ativo", "free_float"),
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
    COLUNAS_OPT_VALIDACAO = (
        "ativo_objeto",
        "tipo_opcao",
        "status_validacao",
        "motivo_rejeicao",
    )
    # C1/C2: adicionadas por V36/V37; opcionais ate a migracao chegar
    COLUNAS_OPT_EXTRAS = ("indice_correcao", "melhor_oferta_compra", "melhor_oferta_venda")

    def precisa_recomposicao(self, db: Any, desde: date) -> bool:
        """Detecta tabela vazia ou registros legados/inconsistentes na janela recente."""
        total = int(db.execute(
            text("SELECT COUNT(*) FROM opcao_b3_diaria WHERE data_pregao >= :desde"),
            {"desde": desde},
        ).scalar() or 0)
        if total == 0:
            return True

        colunas = self._colunas_opcionais_existentes(db)
        if not set(self.COLUNAS_OPT_VALIDACAO).issubset(colunas):
            return False

        suspeitos = int(db.execute(
            text(
                "SELECT COUNT(*) FROM opcao_b3_diaria WHERE data_pregao >= :desde AND ("
                "status_validacao = 'LEGADO_NAO_VALIDADO' OR ("
                "status_validacao = 'VALIDA' AND (data_vencimento = '9999-12-31' "
                "OR preco_exercicio <= 0 OR ativo_objeto IS NULL OR ativo_objeto = '' "
                "OR tipo_opcao IS NULL OR tipo_opcao NOT IN ('CALL', 'PUT'))))"
            ),
            {"desde": desde},
        ).scalar() or 0)
        return suspeitos > 0

    def invalidar_legado_residual(self, db: Any, ano: int) -> int:
        """Mantém não encontrados no COTAHIST, mas impede que sejam operacionais."""
        colunas = self._colunas_opcionais_existentes(db)
        if not set(self.COLUNAS_OPT_VALIDACAO).issubset(colunas):
            return 0

        inicio, fim = date(ano, 1, 1), date(ano + 1, 1, 1)
        resultado = db.execute(
            text(
                "UPDATE opcao_b3_diaria SET motivo_rejeicao = CASE "
                "WHEN status_validacao = 'LEGADO_NAO_VALIDADO' "
                "THEN 'legado_nao_encontrado_no_cotahist' "
                "ELSE 'registro_preexistente_inconsistente' END, "
                "status_validacao = 'INVALIDA' "
                "WHERE data_pregao >= :inicio AND data_pregao < :fim AND ("
                "status_validacao = 'LEGADO_NAO_VALIDADO' OR ("
                "status_validacao = 'VALIDA' AND (data_vencimento = '9999-12-31' "
                "OR preco_exercicio <= 0 OR ativo_objeto IS NULL OR ativo_objeto = '' "
                "OR tipo_opcao IS NULL OR tipo_opcao NOT IN ('CALL', 'PUT'))))"
            ),
            {"inicio": inicio, "fim": fim},
        )
        return int(resultado.rowcount or 0)

    def _colunas_opcionais_existentes(self, db: Any) -> set[str]:
        """Colunas de validação/extras podem faltar em banco anterior às migrations.

        Enquanto a migration nao chega, invalidos ficam fora do INSERT para a
        tabela antiga nao continuar contaminada. Quando as colunas existem, o
        ETL passa a preservar motivo estruturado sem mudar o start unico.
        """
        todas = list(self.COLUNAS_OPT_VALIDACAO) + list(self.COLUNAS_OPT_EXTRAS)
        try:
            schema = db.execute(text("SELECT DATABASE()")).scalar()
            if not schema:
                return set()
            linhas = db.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = 'opcao_b3_diaria' "
                    "AND column_name IN :colunas"
                ).bindparams(bindparam("colunas", expanding=True)),
                {"schema": schema, "colunas": todas},
            )
            return {linha[0] for linha in linhas}
        except Exception:
            return set()

    def salvar_opcoes_b3(self, db: Any, opcoes: Sequence[OpcaoB3]) -> int:
        colunas_opcionais = self._colunas_opcionais_existentes(db)
        schema_com_validacao = set(self.COLUNAS_OPT_VALIDACAO).issubset(colunas_opcionais)
        opcoes_para_gravar = list(opcoes) if schema_com_validacao else [
            o for o in opcoes if o.status_validacao == "VALIDA"
        ]
        registros = []
        for o in opcoes_para_gravar:
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
            }
            if schema_com_validacao:
                reg.update({
                    "ativo_objeto": o.ativo_objeto,
                    "tipo_opcao": o.tipo_opcao,
                    "status_validacao": o.status_validacao,
                    "motivo_rejeicao": o.motivo_rejeicao,
                })
            for col in self.COLUNAS_OPT_EXTRAS:
                if col in colunas_opcionais:
                    reg[col] = getattr(o, col, None)
            registros.append(reg)
        colunas_atualizaveis = [
            "bdi", "data_vencimento", "preco_exercicio",
            "abertura", "maxima", "minima", "fechamento", "preco_medio",
            "volume", "numero_negocios", "volume_financeiro",
            "fator_cotacao", "isin",
        ]
        if schema_com_validacao:
            colunas_atualizaveis.extend(self.COLUNAS_OPT_VALIDACAO)
        for col in self.COLUNAS_OPT_EXTRAS:
            if col in colunas_opcionais:
                colunas_atualizaveis.append(col)
        return _upsert(
            db,
            OpcaoB3DiariaEntity,
            registros,
            tuple(colunas_atualizaveis),
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
                carga_execucao_id=carga_atual(),
                linhas_carregadas=linhas_carregadas,
                mensagem_erro=mensagem_erro,
                finalizado_em=datetime.now(),
            )
        )


class RepositorioFontesPublicasSql:
    """Tabelas da V45 alimentadas por fontes publicas (FONTES-ETL-8).

    Todos os `salvar_*` sao upserts pela chave unica da tabela: rodar duas vezes
    o mesmo conteudo nao duplica nem altera a contagem. Registros duplicados
    dentro da mesma chamada sao fundidos (o ultimo vale)."""

    # -- Tesouro -----------------------------------------------------------

    def salvar_taxas_tesouro(self, db: Any, taxas: Sequence[Any]) -> int:
        linhas = {
            (t.tipo.strip(), t.vencimento, t.data_base): {
                "tipo": t.tipo.strip(), "vencimento": t.vencimento, "data_base": t.data_base,
                "taxa_compra": t.taxa_compra, "taxa_venda": t.taxa_venda,
                "pu_compra": t.pu_compra, "pu_venda": t.pu_venda, "pu_base": t.pu_base,
            }
            for t in taxas
        }
        return _upsert(
            db, TituloPublicoTaxaEntity, list(linhas.values()),
            ("taxa_compra", "taxa_venda", "pu_compra", "pu_venda", "pu_base"),
        )

    # -- FRE ---------------------------------------------------------------

    def salvar_auditores(self, db: Any, auditores: Sequence[Any]) -> int:
        linhas = {}
        for a in auditores:
            cnpj, cnpj_auditor = cnpj14(a.cnpj), cnpj14(a.cnpj_auditor)
            chave = (cnpj, a.dt_referencia, cnpj_auditor, a.dt_inicio_contratacao)
            linhas[chave] = {
                "cnpj": cnpj, "data_referencia": a.dt_referencia, "versao": a.versao,
                "cnpj_auditor": cnpj_auditor, "auditor": cortar(a.auditor, 200),
                "data_inicio": a.dt_inicio_contratacao, "data_fim": a.dt_fim_contratacao,
                "justificativa_substituicao": a.justificativa_substituicao,
            }
        return _upsert(
            db, CvmAuditorEntity, list(linhas.values()),
            ("versao", "auditor", "data_fim", "justificativa_substituicao"),
        )

    def salvar_dividas(self, db: Any, dividas: Sequence[Any]) -> int:
        linhas = {}
        for d in dividas:
            tipo, ident = cortar(d.tipo, 100), cortar(d.identificacao, 200)
            conversivel = texto_conversivel(d.conversivel)
            hash_ = hash_divida(
                tipo, ident, d.dt_emissao, d.dt_vencimento, d.quantidade, d.valor,
                d.saldo_devedor, conversivel,
            )
            linhas[(cnpj14(d.cnpj), d.dt_referencia, d.versao, hash_)] = {
                "cnpj": cnpj14(d.cnpj), "data_referencia": d.dt_referencia, "versao": d.versao,
                "tipo": tipo, "identificacao": ident, "data_emissao": d.dt_emissao,
                "data_vencimento": d.dt_vencimento, "quantidade": d.quantidade,
                "valor": d.valor, "saldo_devedor": d.saldo_devedor,
                "conversivel": conversivel, "hash_linha": hash_,
            }
        lista = list(linhas.values())
        total = _upsert(db, CvmDividaValorMobiliarioEntity, lista, ("hash_linha",))
        self._remover_versoes_antigas(db, CvmDividaValorMobiliarioEntity, lista)
        return total

    # -- VLMO --------------------------------------------------------------

    def salvar_negociacoes(self, db: Any, negociacoes: Sequence[Any]) -> int:
        linhas = {}
        for n in negociacoes:
            campos = (
                cortar(n.tipo_empresa, 60), cortar(n.tipo_cargo, 120),
                cortar(n.tipo_movimentacao, 120), cortar(n.tipo_operacao, 60),
                cortar(n.tipo_ativo, 60), cortar(n.caracteristica, 120),
            )
            hash_ = hash_negociacao(
                *campos, n.data_movimentacao, n.quantidade, n.preco_unitario, n.volume
            )
            linhas[(cnpj14(n.cnpj), n.data_referencia, n.versao, hash_)] = {
                "cnpj": cnpj14(n.cnpj), "data_referencia": n.data_referencia,
                "versao": n.versao, "data_entrega": n.data_entrega,
                "tipo_empresa": campos[0], "tipo_cargo": campos[1],
                "tipo_movimentacao": campos[2], "tipo_operacao": campos[3],
                "tipo_ativo": campos[4], "caracteristica": campos[5],
                "data_movimentacao": n.data_movimentacao, "quantidade": n.quantidade,
                "preco_unitario": n.preco_unitario, "volume": n.volume,
                "hash_linha": hash_,
            }
        lista = list(linhas.values())
        total = _upsert(db, CvmNegociacaoAdministradorEntity, lista, ("data_entrega",))
        self._remover_versoes_antigas(db, CvmNegociacaoAdministradorEntity, lista)
        return total

    def contar_negociacoes(self, db: Any) -> int:
        return db.execute(
            select(func.count()).select_from(CvmNegociacaoAdministradorEntity)
        ).scalar_one()

    @staticmethod
    def _remover_versoes_antigas(db: Any, entidade: type, linhas: Sequence[dict]) -> None:
        """Uma reapresentacao (versao maior) substitui a anterior: sem isto as
        duas versoes ficariam na tabela e a compra liquida contaria em dobro."""
        maior: dict[tuple, int] = {}
        for linha in linhas:
            chave = (linha["cnpj"], linha["data_referencia"])
            maior[chave] = max(maior.get(chave, 0), linha["versao"])
        pares = list(maior.items())
        for lote in _em_lotes(pares, 200):
            db.execute(
                delete(entidade).where(
                    or_(*[
                        and_(
                            entidade.cnpj == cnpj, entidade.data_referencia == ref,
                            entidade.versao < versao,
                        )
                        for (cnpj, ref), versao in lote
                    ])
                )
            )

    # -- CDA ---------------------------------------------------------------

    def salvar_posicoes_fundo(self, db: Any, posicoes: Sequence[Any]) -> int:
        linhas = {}
        for p in posicoes:
            competencia = p.competencia.replace(day=1)
            chave = (competencia, cnpj14(p.cnpj_fundo), p.simbolo)
            linhas[chave] = {
                "competencia": competencia, "cnpj_fundo": cnpj14(p.cnpj_fundo),
                "simbolo": p.simbolo, "isin": cortar(p.isin, 12),
                "quantidade": p.quantidade, "valor_mercado": p.valor_mercado,
                "pl_fundo": p.pl_fundo,
            }
        return _upsert(
            db, FundoPosicaoAcaoEntity, list(linhas.values()),
            ("isin", "quantidade", "valor_mercado", "pl_fundo"),
        )

    def listar_posicoes_fundo(self, db: Any, competencia: date) -> list[PosicaoFundoAcao]:
        """Posicoes de um mes (primeiro dia), prontas para `fluxo_por_ativo`."""
        consulta = select(FundoPosicaoAcaoEntity).where(
            FundoPosicaoAcaoEntity.competencia == competencia.replace(day=1)
        )
        return [
            PosicaoFundoAcao(
                competencia=e.competencia, cnpj_fundo=e.cnpj_fundo, simbolo=e.simbolo,
                isin=e.isin or "", quantidade=e.quantidade or Decimal(0),
                valor_mercado=e.valor_mercado or Decimal(0), pl_fundo=e.pl_fundo,
            )
            for e in db.execute(consulta).scalars()
        ]

    # -- cadastro CVM ------------------------------------------------------

    def salvar_cadastros(self, db: Any, cadastros: Sequence[Any]) -> int:
        """Upsert por cnpj das colunas que o leitor traz; codigo_cvm, denominacao e
        as demais colunas da V45 nao sao tocadas (o CSV lido nao as fornece)."""
        linhas = {
            cnpj14(c.cnpj): {
                "cnpj": cnpj14(c.cnpj), "situacao": cortar(c.situacao, 40),
                "data_situacao": c.data_situacao, "setor_cvm": cortar(c.setor, 120),
                "cnpj_auditor": cnpj14(c.cnpj_auditor), "auditor": cortar(c.auditor, 200),
            }
            for c in cadastros
        }
        return _upsert(
            db, CvmCadastroEntity, list(linhas.values()),
            ("situacao", "data_situacao", "setor_cvm", "cnpj_auditor", "auditor"),
        )

    def cadastros_gravados(self, db: Any) -> tuple[dict[str, Any], date | None]:
        """Retrato anterior (para detectar troca de auditor) e a data dele."""
        from app.adaptadores.cvm.cadastro import CadastroCvm

        linhas = db.execute(select(CvmCadastroEntity)).scalars().all()
        retrato = {
            e.cnpj: CadastroCvm(
                e.cnpj, e.situacao, e.data_situacao, e.setor_cvm, e.auditor, e.cnpj_auditor
            )
            for e in linhas
        }
        datas = [e.atualizado_em.date() for e in linhas if e.atualizado_em]
        return retrato, (max(datas) if datas else None)

    # -- IF.data -----------------------------------------------------------

    def tickers_por_cnpj(self, db: Any) -> dict[str, str]:
        """CNPJ (14 digitos) -> ticker ativo de menor ordem alfabetica (ITUB3 antes de
        ITUB4); sem ticker o CNPJ nao aparece."""
        saida: dict[str, str] = {}
        consulta = (
            select(TickerEntity.cnpj, TickerEntity.simbolo)
            .where(TickerEntity.ativo.is_(True)).order_by(TickerEntity.simbolo)
        )
        for cnpj, simbolo in db.execute(consulta):
            chave = cnpj14(cnpj)
            if chave and chave not in saida:
                saida[chave] = simbolo
        return saida

    def salvar_indicadores_banco(self, db: Any, indicadores: Sequence[Any]) -> int:
        """`indicadores`: pares (IndicadoresIfData, cnpj14, simbolo|None). Valores
        monetarios do IF.data (R$ mil) sao gravados em R$."""
        mil = Decimal(1000)

        def reais(v):
            return None if v is None else v * mil

        linhas = {}
        for i, cnpj, simbolo in indicadores:
            linhas[(cnpj, i.data_base)] = {
                "cnpj": cnpj, "simbolo": simbolo, "data_base": i.data_base,
                "basileia": i.basileia, "indice_capital_principal": i.indice_capital_principal,
                "inadimplencia": i.inadimplencia, "roe": i.roe,
                "ativo_total": reais(i.ativo_total),
                "patrimonio_liquido": reais(i.patrimonio_liquido),
                "carteira_credito": reais(i.carteira_credito), "origem": "IFDATA",
            }
        return _upsert(
            db, BancoIndicadorTrimestralEntity, list(linhas.values()),
            ("simbolo", "basileia", "indice_capital_principal", "inadimplencia", "roe",
             "ativo_total", "patrimonio_liquido", "carteira_credito"),
        )

    # -- datas ex ----------------------------------------------------------

    def contar_datas_ex(self, db: Any) -> int:
        return db.execute(select(func.count()).select_from(DataExB3Entity)).scalar_one()

    def linhas_com_marca_ex(self, db: Any, desde: date) -> list[Any]:
        from app.aplicacao.datas_ex_b3 import LinhaMarcada

        consulta = text(
            "SELECT simbolo, data_pregao, marca_ex, abertura, fechamento, data_anterior, "
            "fechamento_anterior FROM ("
            " SELECT simbolo, data_pregao, marca_ex, abertura, fechamento,"
            "  LAG(data_pregao) OVER (PARTITION BY simbolo ORDER BY data_pregao) data_anterior,"
            "  LAG(fechamento) OVER (PARTITION BY simbolo ORDER BY data_pregao)"
            "   fechamento_anterior"
            " FROM cotacao_b3_diaria WHERE data_pregao >= :janela) t "
            "WHERE marca_ex IS NOT NULL AND TRIM(marca_ex) <> '' AND data_pregao >= :desde "
            "ORDER BY simbolo, data_pregao"
        )
        parametros = {"janela": desde - timedelta(days=15), "desde": desde}
        return [
            LinhaMarcada(r[0], r[1], r[2].strip().upper(), r[3], r[4], r[5], r[6])
            for r in db.execute(consulta, parametros)
        ]

    def salvar_datas_ex(self, db: Any, eventos: Sequence[Any], versao: str) -> int:
        linhas = {
            (e.simbolo, e.data_ex, e.marca): {
                "simbolo": e.simbolo, "data_ex": e.data_ex, "marca": e.marca, "tipo": e.tipo,
                "fechamento_anterior": e.fechamento_anterior, "abertura_ex": e.abertura_ex,
                "ajuste_implicito": e.ajuste_implicito, "ajuste_percentual": e.ajuste_percentual,
                "versao_calculo": versao,
            }
            for e in eventos
        }
        # valor_declarado e origem_valor ficam fora: o gestor junta com proventos
        return _upsert(
            db, DataExB3Entity, list(linhas.values()),
            ("tipo", "fechamento_anterior", "abertura_ex", "ajuste_implicito",
             "ajuste_percentual", "versao_calculo"),
        )

    # -- demais mercados do COTAHIST ---------------------------------------

    def contar_negociacoes_mercado(self, db: Any) -> int:
        return db.execute(select(func.count()).select_from(NegociacaoB3DiariaEntity)).scalar_one()

    def salvar_negociacoes_mercado(self, db: Any, negocios: Sequence[Any]) -> int:
        linhas = {}
        for n in negocios:
            linhas[(n.simbolo, n.data_pregao, n.mercado)] = {
                "simbolo": n.simbolo, "simbolo_base": n.simbolo_base,
                "data_pregao": n.data_pregao, "tpmerc": n.mercado,
                "prazo_termo_dias": n.prazo_termo, "indice_correcao": n.indice_correcao,
                # opcao sobre indice informa o exercicio em pontos, nao em centavos
                "preco_exercicio": (
                    n.preco_exercicio if n.preco_exercicio is not None
                    else n.preco_exercicio_pontos
                ),
                "abertura": n.abertura, "maxima": n.maxima, "minima": n.minima,
                "fechamento": n.fechamento, "preco_medio": n.preco_medio,
                "melhor_oferta_compra": n.melhor_oferta_compra,
                "melhor_oferta_venda": n.melhor_oferta_venda, "volume": n.volume,
                "numero_negocios": n.numero_negocios, "volume_financeiro": n.volume_financeiro,
                "fator_cotacao": n.fator_cotacao, "isin": n.isin,
                "dismes": n.numero_distribuicao,
            }
        return _upsert(
            db, NegociacaoB3DiariaEntity, list(linhas.values()),
            ("simbolo_base", "prazo_termo_dias", "indice_correcao", "preco_exercicio",
             "abertura", "maxima", "minima", "fechamento", "preco_medio",
             "melhor_oferta_compra", "melhor_oferta_venda", "volume", "numero_negocios",
             "volume_financeiro", "fator_cotacao", "isin", "dismes"),
        )
