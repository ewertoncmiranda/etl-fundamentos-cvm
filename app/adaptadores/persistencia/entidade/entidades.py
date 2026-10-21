"""Mapeamento ORM das tabelas CVM.

O schema e de fora (infra-b3-ecossytem/mysql-init/1 - schema.sql) - este app
nao cria nem altera tabela. As entidades sao um espelho e precisam bater
coluna a coluna com aquele DDL.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base propria deste app.

    Fica aqui, e nao no modulo de config, para que importar uma entidade nao
    arraste a configuracao de banco junto.
    """


class MixinCarimbo:
    criado_em: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    atualizado_em: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EmpresaEntity(MixinCarimbo, Base):
    __tablename__ = "cvm_empresa"

    cnpj: Mapped[str] = mapped_column(String(20), primary_key=True)
    cd_cvm: Mapped[str | None] = mapped_column(String(10))
    denominacao: Mapped[str] = mapped_column(String(200), nullable=False)
    setor: Mapped[str | None] = mapped_column(String(60))
    plano_contas: Mapped[str] = mapped_column(String(20), nullable=False, default="GERAL")
    cnae: Mapped[str | None] = mapped_column(String(7))
    grupo_economico: Mapped[str | None] = mapped_column(String(200))
    situacao_registro: Mapped[str | None] = mapped_column(String(30))
    data_constituicao: Mapped[Date | None] = mapped_column(Date)
    uf_municipio: Mapped[str | None] = mapped_column(String(2))


class TickerEntity(MixinCarimbo, Base):
    __tablename__ = "cvm_ticker"

    simbolo: Mapped[str] = mapped_column(String(10), primary_key=True)
    cnpj: Mapped[str] = mapped_column(String(20), nullable=False)
    tipo_valor_mobiliario: Mapped[str | None] = mapped_column(String(60))
    isin: Mapped[str | None] = mapped_column(String(12))
    mercado: Mapped[str | None] = mapped_column(String(40))
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    free_float: Mapped[Numeric | None] = mapped_column(Numeric(6, 2))


class FatoContabilEntity(MixinCarimbo, Base):
    __tablename__ = "fato_contabil"
    __table_args__ = (
        UniqueConstraint(
            "cnpj",
            "tipo_doc",
            "grupo",
            "demonstracao",
            "dt_fim_exerc",
            "dt_ini_exerc",
            "cd_conta",
            "coluna_df",
            name="uq_fato_contabil",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cnpj: Mapped[str] = mapped_column(String(20), nullable=False)
    tipo_doc: Mapped[str] = mapped_column(String(5), nullable=False)
    grupo: Mapped[str] = mapped_column(String(3), nullable=False)
    demonstracao: Mapped[str] = mapped_column(String(10), nullable=False)
    dt_refer: Mapped[Date] = mapped_column(Date, nullable=False)
    dt_ini_exerc: Mapped[Date] = mapped_column(Date, nullable=False)
    dt_fim_exerc: Mapped[Date] = mapped_column(Date, nullable=False)
    versao: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    cd_conta: Mapped[str] = mapped_column(String(20), nullable=False)
    # infra V16: coluna da DMPL; '' nas demais demonstracoes.
    coluna_df: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    ds_conta: Mapped[str | None] = mapped_column(String(200))
    vl_conta: Mapped[Numeric] = mapped_column(Numeric(24, 2), nullable=False)
    conta_fixa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ds_conta_norm: Mapped[str | None] = mapped_column(String(200))


class ComposicaoCapitalEntity(MixinCarimbo, Base):
    __tablename__ = "cvm_composicao_capital"
    __table_args__ = (
        UniqueConstraint("cnpj", "dt_refer", "tipo_doc", name="uq_cvm_composicao_capital"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cnpj: Mapped[str] = mapped_column(String(20), nullable=False)
    dt_refer: Mapped[Date] = mapped_column(Date, nullable=False)
    tipo_doc: Mapped[str] = mapped_column(String(5), nullable=False)
    versao: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    qt_acao_ordinaria: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    qt_acao_preferencial: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    qt_acao_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    qt_acao_tesouraria: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    qt_acao_ex_tesouraria: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class IndicadorFundamentalistaEntity(MixinCarimbo, Base):
    __tablename__ = "indicador_fundamentalista"
    __table_args__ = (
        UniqueConstraint(
            "simbolo", "periodo", "tipo_periodo", name="uq_indicador_fundamentalista"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    simbolo: Mapped[str] = mapped_column(String(10), nullable=False)
    cnpj: Mapped[str] = mapped_column(String(20), nullable=False)
    periodo: Mapped[Date] = mapped_column(Date, nullable=False)
    tipo_periodo: Mapped[str] = mapped_column(String(12), nullable=False, default="ANUAL")
    data_entrega: Mapped[Date | None] = mapped_column(Date)

    lucro_liquido: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    patrimonio_liquido: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    # infra V16 (plano LAC, L6)
    ativo_total: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    ativo_circulante: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    passivo_circulante: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    lucro_bruto: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    lucro_liquido_controlador: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    participacao_nao_controladores: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    receita_liquida: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    ebit: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    divida_bruta: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    caixa_equivalentes: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    fluxo_caixa_operacional: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    fco_bruto: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    capex: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    acoes_ex_tesouraria: Mapped[int | None] = mapped_column(BigInteger)
    resultado_financeiro: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    passivo_nao_circulante: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    impostos_dva: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    estoques: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    contas_a_receber: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    despesas_pessoal: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    depreciacao_amortizacao: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))

    lpa: Mapped[Numeric | None] = mapped_column(Numeric(18, 6))
    vpa: Mapped[Numeric | None] = mapped_column(Numeric(18, 6))
    roe: Mapped[Numeric | None] = mapped_column(Numeric(10, 4))
    roic: Mapped[Numeric | None] = mapped_column(Numeric(10, 4))
    margem_liquida: Mapped[Numeric | None] = mapped_column(Numeric(10, 4))
    divida_liquida: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    fluxo_caixa_livre: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    ebitda: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    cobertura_juros: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    liquidez_corrente: Mapped[Numeric | None] = mapped_column(Numeric(10, 4))
    liquidez_seca: Mapped[Numeric | None] = mapped_column(Numeric(10, 4))
    dso: Mapped[Numeric | None] = mapped_column(Numeric(10, 2))
    graham_number: Mapped[Numeric | None] = mapped_column(Numeric(18, 6))
    # I7/I4: multiplos de mercado — populados por AtualizarMetricasMercado, nao
    # pelo fluxo contabil; ficam NULL ate que a serie historica esteja disponivel
    pl: Mapped[Numeric | None] = mapped_column(Numeric(10, 2))
    ev_ebitda: Mapped[Numeric | None] = mapped_column(Numeric(10, 2))
    pl_setorial_mediana: Mapped[Numeric | None] = mapped_column(Numeric(10, 2))

    fonte: Mapped[str] = mapped_column(String(20), nullable=False, default="CVM")
    tipo_doc: Mapped[str] = mapped_column(String(5), nullable=False)
    grupo: Mapped[str] = mapped_column(String(3), nullable=False, default="con")
    versao_cvm: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    plano_contas: Mapped[str] = mapped_column(String(20), nullable=False, default="GERAL")
    cobertura_json: Mapped[dict | None] = mapped_column(JSON)


class ExecucaoEntity(Base):
    __tablename__ = "etl_execucao"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fonte: Mapped[str] = mapped_column(String(40), nullable=False)
    competencia: Mapped[str] = mapped_column(String(10), nullable=False)
    arquivo: Mapped[str] = mapped_column(String(200), nullable=False)
    etag: Mapped[str | None] = mapped_column(String(200))
    last_modified: Mapped[str | None] = mapped_column(String(80))
    tamanho_bytes: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    carga_execucao_id: Mapped[str | None] = mapped_column(String(36))
    linhas_carregadas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mensagem_erro: Mapped[str | None] = mapped_column(Text)
    iniciado_em: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    finalizado_em: Mapped[DateTime | None] = mapped_column(DateTime)


class ComunicadoCvmEntity(MixinCarimbo, Base):
    """Espelho de comunicado_cvm (mysql-migrations/V3__comunicados_cvm.sql)."""

    __tablename__ = "comunicado_cvm"
    __table_args__ = (
        UniqueConstraint("protocolo_cvm", name="uq_comunicado_cvm_protocolo"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    protocolo_cvm: Mapped[str] = mapped_column(String(20), nullable=False)
    protocolo_entrega: Mapped[str | None] = mapped_column(String(40))
    versao: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    cnpj: Mapped[str] = mapped_column(String(20), nullable=False)
    codigo_cvm: Mapped[str | None] = mapped_column(String(10))
    categoria: Mapped[str] = mapped_column(String(40), nullable=False)
    categoria_original: Mapped[str] = mapped_column(String(200), nullable=False)
    tipo: Mapped[str | None] = mapped_column(String(120))
    especie: Mapped[str | None] = mapped_column(String(120))
    assunto: Mapped[str | None] = mapped_column(Text)
    data_referencia: Mapped[Date | None] = mapped_column(Date)
    data_entrega: Mapped[Date] = mapped_column(Date, nullable=False)
    link_download: Mapped[str] = mapped_column(String(300), nullable=False)


class SerieHistoricaEntity(MixinCarimbo, Base):
    __tablename__ = "serie_historica"
    __table_args__ = (
        UniqueConstraint("simbolo", "data_pregao", "intervalo", name="uq_serie_historica_dia"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    simbolo: Mapped[str] = mapped_column(String(10), nullable=False)
    data_pregao: Mapped[Date] = mapped_column(Date, nullable=False)
    intervalo: Mapped[str] = mapped_column(String(10), nullable=False, default="1d")
    range_usado: Mapped[str | None] = mapped_column(String(10))
    abertura: Mapped[Numeric | None] = mapped_column(Numeric(12, 4))
    maxima: Mapped[Numeric | None] = mapped_column(Numeric(12, 4))
    minima: Mapped[Numeric | None] = mapped_column(Numeric(12, 4))
    fechamento: Mapped[Numeric | None] = mapped_column(Numeric(12, 4))
    fechamento_ajustado: Mapped[Numeric | None] = mapped_column(Numeric(12, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    fonte: Mapped[str] = mapped_column(String(30), nullable=False, default="B3")
    detalhes_json: Mapped[dict | None] = mapped_column(JSON)


class CotacaoB3DiariaEntity(MixinCarimbo, Base):
    """COTAHIST oficial da B3, codigo como negociado no dia (infra V6)."""

    __tablename__ = "cotacao_b3_diaria"
    __table_args__ = (
        UniqueConstraint("simbolo", "data_pregao", name="uq_cotacao_b3_diaria"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    simbolo: Mapped[str] = mapped_column(String(12), nullable=False)
    # infra V16 (plano LAC): ESPECI, marca de dia ex, FATCOT, VWAP e ofertas.
    especificacao: Mapped[str | None] = mapped_column(String(10))
    marca_ex: Mapped[str | None] = mapped_column(String(4))
    fator_cotacao: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    data_pregao: Mapped[Date] = mapped_column(Date, nullable=False)
    abertura: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    maxima: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    minima: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    fechamento: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    preco_medio: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    melhor_oferta_compra: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    melhor_oferta_venda: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    numero_negocios: Mapped[int | None] = mapped_column(Integer)
    volume_financeiro: Mapped[Numeric | None] = mapped_column(Numeric(22, 2))
    isin: Mapped[str | None] = mapped_column(String(12))


class OpcaoB3DiariaEntity(MixinCarimbo, Base):
    """Cotacoes diarias de opcoes da B3, do COTAHIST (infra V20 + OPT-INFRA-1)."""

    __tablename__ = "opcao_b3_diaria"
    __table_args__ = (
        UniqueConstraint("simbolo", "data_pregao", name="uq_opcao_b3_diaria"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    simbolo: Mapped[str] = mapped_column(String(12), nullable=False)
    bdi: Mapped[str] = mapped_column(String(2), nullable=False)
    data_pregao: Mapped[Date] = mapped_column(Date, nullable=False)
    data_vencimento: Mapped[Date] = mapped_column(Date, nullable=False)
    preco_exercicio: Mapped[Numeric] = mapped_column(Numeric(14, 4), nullable=False)
    abertura: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    maxima: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    minima: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    fechamento: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    preco_medio: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    numero_negocios: Mapped[int | None] = mapped_column(Integer)
    volume_financeiro: Mapped[Numeric | None] = mapped_column(Numeric(22, 2))
    fator_cotacao: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    isin: Mapped[str | None] = mapped_column(String(12))
    ativo_objeto: Mapped[str | None] = mapped_column(String(12))
    tipo_opcao: Mapped[str | None] = mapped_column(String(4))
    status_validacao: Mapped[str | None] = mapped_column(String(20))
    motivo_rejeicao: Mapped[str | None] = mapped_column(String(80))
    # C1 Phase-0: adicionado por V36 — coluna opcional ate a migracao ser aplicada
    indice_correcao: Mapped[str | None] = mapped_column(String(1))
    # C2 Phase-2: adicionado por V37 — colunas opcionais ate a migracao ser aplicada
    melhor_oferta_compra: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    melhor_oferta_venda: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))


class ProventoContabilEntity(MixinCarimbo, Base):
    """JCP e dividendos por periodo, da DVA (infra V16, plano LAC L1).

    `total` e coluna gerada no banco: fica fora do mapeamento de proposito,
    para o INSERT nunca tentar grava-la.
    """

    __tablename__ = "provento_contabil"
    __table_args__ = (
        UniqueConstraint("cnpj", "tipo_doc", "dt_fim_exerc", name="uq_provento_contabil"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cnpj: Mapped[str] = mapped_column(String(20), nullable=False)
    tipo_doc: Mapped[str] = mapped_column(String(5), nullable=False)
    dt_ini_exerc: Mapped[Date] = mapped_column(Date, nullable=False)
    dt_fim_exerc: Mapped[Date] = mapped_column(Date, nullable=False)
    versao: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    data_entrega: Mapped[Date | None] = mapped_column(Date)
    jcp: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    dividendos: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    acoes_ex_tesouraria: Mapped[int | None] = mapped_column(BigInteger)
    por_acao: Mapped[Numeric | None] = mapped_column(Numeric(18, 8))
    origem: Mapped[str] = mapped_column(String(20), nullable=False, default="CVM_DVA")
    cobertura_json: Mapped[dict | None] = mapped_column(JSON)


# --- V45 (CONS-INFRA-1): fontes publicas ---------------------------------


class TituloPublicoTaxaEntity(MixinCarimbo, Base):
    """Taxas e PUs do Tesouro Direto (V45 titulo_publico_taxa)."""

    __tablename__ = "titulo_publico_taxa"
    __table_args__ = (
        UniqueConstraint("tipo", "vencimento", "data_base", name="uq_titulo_publico_taxa"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tipo: Mapped[str] = mapped_column(String(60), nullable=False)
    vencimento: Mapped[Date] = mapped_column(Date, nullable=False)
    data_base: Mapped[Date] = mapped_column(Date, nullable=False)
    taxa_compra: Mapped[Numeric | None] = mapped_column(Numeric(9, 4))
    taxa_venda: Mapped[Numeric | None] = mapped_column(Numeric(9, 4))
    pu_compra: Mapped[Numeric | None] = mapped_column(Numeric(16, 6))
    pu_venda: Mapped[Numeric | None] = mapped_column(Numeric(16, 6))
    pu_base: Mapped[Numeric | None] = mapped_column(Numeric(16, 6))


class CvmAuditorEntity(MixinCarimbo, Base):
    """Auditores do FRE (V45 cvm_auditor)."""

    __tablename__ = "cvm_auditor"
    __table_args__ = (
        UniqueConstraint(
            "cnpj", "data_referencia", "cnpj_auditor", "data_inicio", name="uq_cvm_auditor"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cnpj: Mapped[str] = mapped_column(String(14), nullable=False)
    data_referencia: Mapped[Date] = mapped_column(Date, nullable=False)
    versao: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    cnpj_auditor: Mapped[str] = mapped_column(String(14), nullable=False)
    auditor: Mapped[str | None] = mapped_column(String(200))
    data_inicio: Mapped[Date] = mapped_column(Date, nullable=False)
    data_fim: Mapped[Date | None] = mapped_column(Date)
    justificativa_substituicao: Mapped[str | None] = mapped_column(Text)


class CvmNegociacaoAdministradorEntity(Base):
    """VLMO (V45 cvm_negociacao_administrador); a tabela nao tem atualizado_em."""

    __tablename__ = "cvm_negociacao_administrador"
    __table_args__ = (
        UniqueConstraint(
            "cnpj", "data_referencia", "versao", "hash_linha",
            name="uq_cvm_negociacao_administrador",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cnpj: Mapped[str] = mapped_column(String(14), nullable=False)
    data_referencia: Mapped[Date] = mapped_column(Date, nullable=False)
    versao: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    data_entrega: Mapped[Date | None] = mapped_column(Date)
    tipo_empresa: Mapped[str | None] = mapped_column(String(60))
    tipo_cargo: Mapped[str | None] = mapped_column(String(120))
    tipo_movimentacao: Mapped[str | None] = mapped_column(String(120))
    tipo_operacao: Mapped[str | None] = mapped_column(String(60))
    tipo_ativo: Mapped[str | None] = mapped_column(String(60))
    caracteristica: Mapped[str | None] = mapped_column(String(120))
    data_movimentacao: Mapped[Date | None] = mapped_column(Date)
    quantidade: Mapped[Numeric | None] = mapped_column(Numeric(22, 6))
    preco_unitario: Mapped[Numeric | None] = mapped_column(Numeric(22, 6))
    volume: Mapped[Numeric | None] = mapped_column(Numeric(22, 2))
    hash_linha: Mapped[str] = mapped_column(String(64), nullable=False)
    criado_em: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class CvmDividaValorMobiliarioEntity(Base):
    """FRE outros valores mobiliarios (V45 cvm_divida_valor_mobiliario)."""

    __tablename__ = "cvm_divida_valor_mobiliario"
    __table_args__ = (
        UniqueConstraint(
            "cnpj", "data_referencia", "versao", "hash_linha",
            name="uq_cvm_divida_valor_mobiliario",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cnpj: Mapped[str] = mapped_column(String(14), nullable=False)
    data_referencia: Mapped[Date] = mapped_column(Date, nullable=False)
    versao: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    tipo: Mapped[str | None] = mapped_column(String(100))
    identificacao: Mapped[str | None] = mapped_column(String(200))
    data_emissao: Mapped[Date | None] = mapped_column(Date)
    data_vencimento: Mapped[Date | None] = mapped_column(Date)
    quantidade: Mapped[Numeric | None] = mapped_column(Numeric(22, 6))
    valor: Mapped[Numeric | None] = mapped_column(Numeric(22, 2))
    saldo_devedor: Mapped[Numeric | None] = mapped_column(Numeric(22, 2))
    conversivel: Mapped[str | None] = mapped_column(String(10))
    hash_linha: Mapped[str] = mapped_column(String(64), nullable=False)
    criado_em: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class FundoPosicaoAcaoEntity(MixinCarimbo, Base):
    """CDA, so acoes (V45 fundo_posicao_acao); competencia = primeiro dia do mes."""

    __tablename__ = "fundo_posicao_acao"
    __table_args__ = (
        UniqueConstraint("competencia", "cnpj_fundo", "simbolo", name="uq_fundo_posicao_acao"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    competencia: Mapped[Date] = mapped_column(Date, nullable=False)
    cnpj_fundo: Mapped[str] = mapped_column(String(14), nullable=False)
    simbolo: Mapped[str] = mapped_column(String(12), nullable=False)
    isin: Mapped[str | None] = mapped_column(String(12))
    quantidade: Mapped[Numeric | None] = mapped_column(Numeric(22, 6))
    valor_mercado: Mapped[Numeric | None] = mapped_column(Numeric(22, 2))
    pl_fundo: Mapped[Numeric | None] = mapped_column(Numeric(22, 2))


# --- V45, parte 2: cadastro, IF.data, datas ex e demais mercados -----------


class CvmCadastroEntity(Base):
    """cad_cia_aberta (V45 cvm_cadastro); so atualizado_em, sem criado_em."""

    __tablename__ = "cvm_cadastro"

    cnpj: Mapped[str] = mapped_column(String(14), primary_key=True)
    codigo_cvm: Mapped[str | None] = mapped_column(String(10))
    denominacao: Mapped[str | None] = mapped_column(String(200))
    situacao: Mapped[str | None] = mapped_column(String(40))
    data_situacao: Mapped[Date | None] = mapped_column(Date)
    data_cancelamento: Mapped[Date | None] = mapped_column(Date)
    motivo_cancelamento: Mapped[str | None] = mapped_column(String(200))
    setor_cvm: Mapped[str | None] = mapped_column(String(120))
    situacao_emissor: Mapped[str | None] = mapped_column(String(60))
    controle_acionario: Mapped[str | None] = mapped_column(String(40))
    cnpj_auditor: Mapped[str | None] = mapped_column(String(14))
    auditor: Mapped[str | None] = mapped_column(String(200))
    atualizado_em: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BancoIndicadorTrimestralEntity(MixinCarimbo, Base):
    __tablename__ = "banco_indicador_trimestral"
    __table_args__ = (
        UniqueConstraint("cnpj", "data_base", name="uq_banco_indicador_trimestral"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cnpj: Mapped[str] = mapped_column(String(14), nullable=False)
    simbolo: Mapped[str | None] = mapped_column(String(12))
    data_base: Mapped[Date] = mapped_column(Date, nullable=False)
    basileia: Mapped[Numeric | None] = mapped_column(Numeric(9, 4))
    indice_capital_principal: Mapped[Numeric | None] = mapped_column(Numeric(9, 4))
    inadimplencia: Mapped[Numeric | None] = mapped_column(Numeric(9, 4))
    roe: Mapped[Numeric | None] = mapped_column(Numeric(9, 4))
    ativo_total: Mapped[Numeric | None] = mapped_column(Numeric(22, 2))
    patrimonio_liquido: Mapped[Numeric | None] = mapped_column(Numeric(22, 2))
    carteira_credito: Mapped[Numeric | None] = mapped_column(Numeric(22, 2))
    origem: Mapped[str] = mapped_column(String(20), nullable=False, default="IFDATA")


class DataExB3Entity(MixinCarimbo, Base):
    __tablename__ = "data_ex_b3"
    __table_args__ = (
        UniqueConstraint("simbolo", "data_ex", "marca", name="uq_data_ex_b3"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    simbolo: Mapped[str] = mapped_column(String(12), nullable=False)
    data_ex: Mapped[Date] = mapped_column(Date, nullable=False)
    marca: Mapped[str] = mapped_column(String(4), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    fechamento_anterior: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    abertura_ex: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    ajuste_implicito: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    ajuste_percentual: Mapped[Numeric | None] = mapped_column(Numeric(9, 4))
    valor_declarado: Mapped[Numeric | None] = mapped_column(Numeric(14, 6))
    origem_valor: Mapped[str | None] = mapped_column(String(30))
    versao_calculo: Mapped[str] = mapped_column(String(20), nullable=False)


class NegociacaoB3DiariaEntity(MixinCarimbo, Base):
    __tablename__ = "negociacao_b3_diaria"
    __table_args__ = (
        UniqueConstraint("simbolo", "data_pregao", "tpmerc", name="uq_negociacao_b3_diaria"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    simbolo: Mapped[str] = mapped_column(String(12), nullable=False)
    simbolo_base: Mapped[str | None] = mapped_column(String(12))
    data_pregao: Mapped[Date] = mapped_column(Date, nullable=False)
    tpmerc: Mapped[str] = mapped_column(String(3), nullable=False)
    codbdi: Mapped[str | None] = mapped_column(String(2))
    especificacao: Mapped[str | None] = mapped_column(String(10))
    prazo_termo_dias: Mapped[int | None] = mapped_column(Integer)
    indice_correcao: Mapped[str | None] = mapped_column(String(1))
    preco_exercicio: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    data_vencimento: Mapped[Date | None] = mapped_column(Date)
    abertura: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    maxima: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    minima: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    fechamento: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    preco_medio: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    melhor_oferta_compra: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    melhor_oferta_venda: Mapped[Numeric | None] = mapped_column(Numeric(14, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    numero_negocios: Mapped[int | None] = mapped_column(Integer)
    volume_financeiro: Mapped[Numeric | None] = mapped_column(Numeric(22, 2))
    fator_cotacao: Mapped[int | None] = mapped_column(Integer)
    isin: Mapped[str | None] = mapped_column(String(12))
    dismes: Mapped[int | None] = mapped_column(SmallInteger)
