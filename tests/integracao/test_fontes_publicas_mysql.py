"""Integracao opcional dos repositorios da V45 contra um MySQL descartavel.

Roda so com ETL8_MYSQL_URL apontando para um banco com V1..V45 aplicadas, p.ex.
mysql+pymysql://root:<senha>@127.0.0.1:3305/v45_etl8 . Sem a variavel, pula.
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.adaptadores.cvm.cda import PosicaoFundoAcao, fluxo_por_ativo
from app.adaptadores.cvm.fre_estendido import Auditor, DividaValorMobiliario
from app.adaptadores.cvm.vlmo import NegociacaoAdministrador
from app.adaptadores.persistencia.entidade.entidades import (
    CvmAuditorEntity,
    CvmDividaValorMobiliarioEntity,
    CvmNegociacaoAdministradorEntity,
    FundoPosicaoAcaoEntity,
    TituloPublicoTaxaEntity,
)
from app.adaptadores.persistencia.repositorios import RepositorioFontesPublicasSql
from app.adaptadores.tesouro.leitor_tesouro import TaxaTituloPublico

URL = os.getenv("ETL8_MYSQL_URL")
pytestmark = pytest.mark.skipif(not URL, reason="ETL8_MYSQL_URL nao definida")

CNPJ = "00000000000191"


@pytest.fixture()
def db():
    engine = create_engine(URL)
    with Session(engine) as sessao:
        yield sessao
        sessao.rollback()
    engine.dispose()


def _conta(db, entidade) -> int:
    return db.execute(select(func.count()).select_from(entidade)).scalar_one()


def _neg(versao=1, qtd="100", **kw):
    base = dict(
        cnpj=CNPJ, nome_companhia="X", data_referencia=date(2026, 1, 1), versao=versao,
        data_entrega=date(2026, 2, 1), tipo_empresa="Companhia", empresa="X",
        tipo_cargo="Diretor", tipo_movimentacao="Compra à vista", descricao_movimentacao="",
        tipo_operacao="Crédito", tipo_ativo="Ações", caracteristica="ON", intermediario="",
        data_movimentacao=date(2026, 1, 10), quantidade=Decimal(qtd),
        preco_unitario=Decimal("10.5"), volume=Decimal("1050"),
    )
    base.update(kw)
    return NegociacaoAdministrador(**base)


def test_tesouro_upsert_idempotente(db):
    repo = RepositorioFontesPublicasSql()
    t = TaxaTituloPublico("Tesouro IPCA+", date(2029, 5, 15), date(2026, 10, 15),
                          Decimal("7.4"), Decimal("7.52"), Decimal("3512.1"), None, None)
    repo.salvar_taxas_tesouro(db, [t])
    repo.salvar_taxas_tesouro(db, [t])
    assert _conta(db, TituloPublicoTaxaEntity) == 1
    novo = TaxaTituloPublico(t.tipo, t.vencimento, t.data_base, Decimal("7.9"), None, None,
                             None, None)
    repo.salvar_taxas_tesouro(db, [novo])
    linha = db.execute(select(TituloPublicoTaxaEntity)).scalar_one()
    assert linha.taxa_compra == Decimal("7.9000") and _conta(db, TituloPublicoTaxaEntity) == 1


def test_vlmo_idempotente_hash_e_reapresentacao_substitui_versao_antiga(db):
    repo = RepositorioFontesPublicasSql()
    v1 = [_neg(1), _neg(1, qtd="200")]
    repo.salvar_negociacoes(db, v1)
    repo.salvar_negociacoes(db, v1)
    assert _conta(db, CvmNegociacaoAdministradorEntity) == 2
    assert repo.contar_negociacoes(db) == 2
    hashes = db.execute(select(CvmNegociacaoAdministradorEntity.hash_linha)).scalars().all()
    assert len(set(hashes)) == 2 and all(len(h) == 64 for h in hashes)
    repo.salvar_negociacoes(db, [_neg(2)])
    versoes = db.execute(select(CvmNegociacaoAdministradorEntity.versao)).scalars().all()
    assert versoes == [2]


def test_fre_auditor_e_divida_idempotentes(db):
    repo = RepositorioFontesPublicasSql()
    a = Auditor("00.000.000/0001-91", date(2026, 12, 31), 1, "KPMG", "61.562.112/0001-20",
                date(2020, 1, 1), None, None, None)
    d = DividaValorMobiliario("00.000.000/0001-91", date(2026, 12, 31), 1, "Debênture", "D1",
                              date(2020, 1, 1), date(2030, 1, 1), Decimal("10"),
                              Decimal("1000"), Decimal("900"), False)
    for _ in range(2):
        repo.salvar_auditores(db, [a])
        repo.salvar_dividas(db, [d])
    assert _conta(db, CvmAuditorEntity) == 1 and _conta(db, CvmDividaValorMobiliarioEntity) == 1
    assert db.execute(select(CvmDividaValorMobiliarioEntity.conversivel)).scalar_one() == "Nao"


def test_cda_idempotente_e_alimenta_fluxo_por_ativo(db):
    repo = RepositorioFontesPublicasSql()

    def pos(dia, fundo, qtd):
        return PosicaoFundoAcao(dia, fundo, "ITUB3", "BRITUBACNOR0", Decimal(qtd),
                                Decimal("1000"), Decimal("5000000"))

    ago = [pos(date(2026, 8, 31), "00102322000141", "100")]
    set_ = [pos(date(2026, 9, 30), "00102322000141", "150"),
            pos(date(2026, 9, 30), "11111111000111", "50")]
    for _ in range(2):
        repo.salvar_posicoes_fundo(db, ago)
        repo.salvar_posicoes_fundo(db, set_)
    assert _conta(db, FundoPosicaoAcaoEntity) == 3
    atual = repo.listar_posicoes_fundo(db, date(2026, 9, 15))
    anterior = repo.listar_posicoes_fundo(db, date(2026, 8, 1))
    fluxo = fluxo_por_ativo(atual, anterior)["ITUB3"]
    assert (fluxo.fundos, fluxo.quantidade, fluxo.variacao_quantidade) == (
        2, Decimal("200"), Decimal("100")
    )
    assert fluxo.fundos_entraram == 1 and fluxo.fundos_sairam == 0


# ------------------------------------------------------------ parte 2

def test_cadastro_ifdata_upsert_e_ligacao_com_ticker(db):
    from sqlalchemy import text

    from app.adaptadores.bcb.ifdata import IndicadoresIfData
    from app.adaptadores.cvm.cadastro import CadastroCvm
    from app.adaptadores.persistencia.entidade.entidades import (
        BancoIndicadorTrimestralEntity,
        CvmCadastroEntity,
    )

    repo = RepositorioFontesPublicasSql()
    c = CadastroCvm(CNPJ, "Ativo", date(2020, 1, 1), "Bancos", "KPMG", "57755217000129")
    for _ in range(2):
        repo.salvar_cadastros(db, [c])
    assert _conta(db, CvmCadastroEntity) == 1
    repo.salvar_cadastros(db, [CadastroCvm(CNPJ, "Ativo", None, "Bancos", "DELOITTE",
                                           "49928567000111")])
    anteriores, snapshot = repo.cadastros_gravados(db)
    assert anteriores[CNPJ].auditor == "DELOITTE" and snapshot is not None

    db.execute(text(
        "INSERT INTO cvm_empresa (cnpj, denominacao, plano_contas) VALUES (:c, 'BANCO X', 'GERAL')"
    ), {"c": CNPJ})
    db.execute(text("INSERT INTO cvm_ticker (simbolo, cnpj, ativo) VALUES "
                    "('BANC4', :c, 1), ('BANC3', :c, 1)"), {"c": CNPJ})
    assert repo.tickers_por_cnpj(db) == {CNPJ: "BANC3"}

    i = IndicadoresIfData(CNPJ, date(2026, 6, 30), "1", 1, basileia=Decimal("0.1712"),
                          roe=Decimal("0.21"), ativo_total=Decimal("1000"))
    for _ in range(2):
        repo.salvar_indicadores_banco(db, [(i, CNPJ, "BANC3")])
    linha = db.execute(select(BancoIndicadorTrimestralEntity)).scalar_one()
    assert linha.simbolo == "BANC3" and linha.ativo_total == Decimal("1000000.00")


def _cotacao(db, simbolo, dia, marca=None, abertura="10", fechamento="10"):
    from sqlalchemy import text

    db.execute(text(
        "INSERT INTO cotacao_b3_diaria (simbolo, data_pregao, marca_ex, abertura, fechamento, "
        "maxima, minima, fator_cotacao) VALUES (:s, :d, :m, :a, :f, :f, :a, 1)"
    ), {"s": simbolo, "d": dia, "m": marca, "a": abertura, "f": fechamento})


def test_datas_ex_primeiro_pregao_da_sequencia_no_mysql(db):
    from datetime import timedelta

    from app.adaptadores.persistencia.entidade.entidades import DataExB3Entity
    from app.aplicacao.datas_ex_b3 import VERSAO_CALCULO, montar_datas_ex

    repo = RepositorioFontesPublicasSql()
    dia = date(2026, 8, 20)
    for k in range(10):  # 20..29/08, 8 pregoes com marca a partir do 24
        d = dia + timedelta(days=k)
        if d.weekday() >= 5:
            continue
        marca = "EDJ" if d >= date(2026, 8, 24) else None
        _cotacao(db, "PETR4", d, marca, "42.6" if marca else "44.3", "44.3" if not marca else "42.8")
    linhas = repo.linhas_com_marca_ex(db, date(2026, 1, 1))
    assert len(linhas) >= 5
    eventos = montar_datas_ex(linhas)
    assert len(eventos) == 1 and eventos[0].data_ex == date(2026, 8, 24)
    assert eventos[0].fechamento_anterior == Decimal("44.3000")
    for _ in range(2):
        repo.salvar_datas_ex(db, eventos, VERSAO_CALCULO)
    linha = db.execute(select(DataExB3Entity)).scalar_one()
    assert (linha.tipo, linha.marca, linha.valor_declarado) == ("DIVIDENDO", "EDJ", None)
    assert linha.ajuste_implicito == Decimal("1.7000")


def test_negociacao_b3_diaria_upsert_idempotente(db):
    from app.adaptadores.b3.leitor_cotahist import NegocioMercadoB3
    from app.adaptadores.persistencia.entidade.entidades import NegociacaoB3DiariaEntity

    repo = RepositorioFontesPublicasSql()
    n = NegocioMercadoB3(
        "PETR4F", "PETR4", "020", date(2026, 1, 5), "BRPETRACNPR6", None, None, None, None,
        None, Decimal("30.1"), Decimal("31"), Decimal("30"), Decimal("30.5"), None, None, None,
        5, 100, Decimal("3050"), 1,
    )
    for _ in range(2):
        repo.salvar_negociacoes_mercado(db, [n])
    assert _conta(db, NegociacaoB3DiariaEntity) == 1 and repo.contar_negociacoes_mercado(db) == 1
