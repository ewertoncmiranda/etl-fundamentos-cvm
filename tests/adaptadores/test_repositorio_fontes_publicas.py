"""hash_linha estavel e SQL dos upserts da V45 (compilado para MySQL, sem banco)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.dialects import mysql

from app.adaptadores.cvm.fre_estendido import DividaValorMobiliario
from app.adaptadores.cvm.vlmo import NegociacaoAdministrador
from app.adaptadores.persistencia.repositorios import RepositorioFontesPublicasSql
from app.dominio.fontes_publicas import hash_divida, hash_linha, hash_negociacao


class DbFake:
    def __init__(self):
        self.comandos = []

    def execute(self, comando):
        self.comandos.append(str(comando.compile(dialect=mysql.dialect())))


def _neg(**kw):
    base = dict(
        cnpj="00000000000191", nome_companhia="X", data_referencia=date(2026, 1, 1), versao=1,
        data_entrega=None, tipo_empresa="Companhia", empresa="X", tipo_cargo="Diretor",
        tipo_movimentacao="Compra à vista", descricao_movimentacao="", tipo_operacao="Crédito",
        tipo_ativo="Ações", caracteristica="ON", intermediario="",
        data_movimentacao=date(2026, 1, 10), quantidade=Decimal("100"),
        preco_unitario=Decimal("10"), volume=Decimal("1000"),
    )
    base.update(kw)
    return NegociacaoAdministrador(**base)


def _hash(n):
    return hash_negociacao(n.tipo_empresa, n.tipo_cargo, n.tipo_movimentacao, n.tipo_operacao,
                           n.tipo_ativo, n.caracteristica, n.data_movimentacao, n.quantidade,
                           n.preco_unitario, n.volume)


def test_hash_linha_e_sha256_hex_de_64_caracteres_e_valor_conhecido():
    h = hash_linha("a", None, date(2026, 1, 2), (Decimal("1.5"), 2))
    assert len(h) == 64 and h == h.lower()
    import hashlib
    assert h == hashlib.sha256("a\x1f\x1f2026-01-02\x1f1.50".encode()).hexdigest()


def test_hash_negociacao_estavel_e_insensivel_a_escala_decimal_e_a_data_entrega():
    a = _neg(quantidade=Decimal("100"), volume=Decimal("1000.0"))
    b = _neg(quantidade=Decimal("100.000000"), volume=Decimal("1000.00"),
             data_entrega=date(2026, 2, 1), nome_companhia="OUTRO NOME")
    assert _hash(a) == _hash(b)


def test_hash_negociacao_muda_com_qualquer_coluna_de_conteudo():
    base = _hash(_neg())
    for variacao in (
        dict(tipo_cargo="Conselho"), dict(quantidade=Decimal("101")),
        dict(data_movimentacao=date(2026, 1, 11)), dict(preco_unitario=None),
        dict(tipo_movimentacao="Venda à vista"), dict(caracteristica="PN"),
    ):
        assert _hash(_neg(**variacao)) != base


def test_hash_divida_distingue_none_de_zero():
    a = hash_divida("Deb", "X", None, None, None, None, Decimal("0"), "Sim")
    b = hash_divida("Deb", "X", None, None, None, None, None, "Sim")
    assert a != b


def test_upserts_usam_on_duplicate_key_update_e_fundem_chaves_repetidas():
    db, repo = DbFake(), RepositorioFontesPublicasSql()
    n = _neg()
    assert repo.salvar_negociacoes(db, [n, n, _neg(versao=2)]) == 2  # duplicata fundida
    insercao = db.comandos[0]
    assert "INSERT INTO cvm_negociacao_administrador" in insercao
    assert "ON DUPLICATE KEY UPDATE" in insercao
    # depois do upsert, versoes antigas da mesma (cnpj, referencia) saem
    assert db.comandos[1].startswith("DELETE FROM cvm_negociacao_administrador")


def test_divida_grava_cnpj_so_digitos_e_conversivel_texto():
    db, repo = DbFake(), RepositorioFontesPublicasSql()
    d = DividaValorMobiliario("00.000.000/0001-91", date(2026, 1, 1), 1, "Debênture", "D1",
                              None, date(2030, 1, 1), None, None, Decimal("5"), True)
    assert repo.salvar_dividas(db, [d]) == 1
    assert "INSERT INTO cvm_divida_valor_mobiliario" in db.comandos[0]
