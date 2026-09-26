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


class TickerEntity(MixinCarimbo, Base):
    __tablename__ = "cvm_ticker"

    simbolo: Mapped[str] = mapped_column(String(10), primary_key=True)
    cnpj: Mapped[str] = mapped_column(String(20), nullable=False)
    tipo_valor_mobiliario: Mapped[str | None] = mapped_column(String(60))
    mercado: Mapped[str | None] = mapped_column(String(40))
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


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

    lucro_liquido: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    patrimonio_liquido: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    lucro_liquido_controlador: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    participacao_nao_controladores: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    receita_liquida: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    ebit: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    divida_bruta: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    caixa_equivalentes: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    fluxo_caixa_operacional: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    capex: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    acoes_ex_tesouraria: Mapped[int | None] = mapped_column(BigInteger)

    lpa: Mapped[Numeric | None] = mapped_column(Numeric(18, 6))
    vpa: Mapped[Numeric | None] = mapped_column(Numeric(18, 6))
    roe: Mapped[Numeric | None] = mapped_column(Numeric(10, 4))
    roic: Mapped[Numeric | None] = mapped_column(Numeric(10, 4))
    margem_liquida: Mapped[Numeric | None] = mapped_column(Numeric(10, 4))
    divida_liquida: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))
    fluxo_caixa_livre: Mapped[Numeric | None] = mapped_column(Numeric(24, 2))

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
    linhas_carregadas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mensagem_erro: Mapped[str | None] = mapped_column(Text)
    iniciado_em: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    finalizado_em: Mapped[DateTime | None] = mapped_column(DateTime)
