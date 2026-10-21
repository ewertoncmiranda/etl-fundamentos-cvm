"""Leitor do VLMO: versoes, Data_Entrega, acentos latin-1 e compra liquida."""

from __future__ import annotations

import io
import zipfile
from datetime import date
from decimal import Decimal

import pytest

from app.adaptadores.cvm.vlmo import compra_liquida, ler_vlmo
from app.excecoes.excecoes import PacoteInvalido

ANO = 2025
CAB_CON = (
    "CNPJ_Companhia;Nome_Companhia;Data_Referencia;Versao;Tipo_Empresa;Empresa;Tipo_Cargo;"
    "Tipo_Movimentacao;Descricao_Movimentacao;Tipo_Operacao;Tipo_Ativo;"
    "Caracteristica_Valor_Mobiliario;Intermediario;Data_Movimentacao;Quantidade;Preco_Unitario;Volume"
)
CAB_IDX = "CNPJ_Companhia;Nome_Companhia;Data_Referencia;Versao;Data_Entrega"
CNPJ = "00.000.000/0001-91"
DIR = "Diretor ou Vinculado"
CTRL = "Controlador ou Vinculado"


def _con(versao, cargo, mov, ativo, qtd, vol="", dia="2025-01-10", ref="2025-01-01", cnpj=CNPJ):
    op = "Débito" if mov.startswith("Venda") else "Crédito"
    return f"{cnpj};BANCO;{ref};{versao};Companhia;BANCO;{cargo};{mov};;{op};{ativo};ON;;{dia};{qtd};;{vol}"


def _zip(con, idx=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"vlmo_cia_aberta_con_{ANO}.csv", "\n".join([CAB_CON, *con]).encode("latin-1"))
        z.writestr(f"vlmo_cia_aberta_{ANO}.csv", "\n".join([CAB_IDX, *idx]).encode("latin-1"))
    return buf.getvalue()


def test_mantem_so_ultima_versao_e_data_entrega():
    conteudo = _zip(
        [
            _con(1, DIR, "Compra à vista", "Ações", 100),
            _con(2, DIR, "Compra à vista", "Ações", 300),
            _con(1, DIR, "Venda à vista", "Ações", 5, ref="2025-02-01"),
        ],
        [f"{CNPJ};BANCO;2025-01-01;1;2025-02-05", f"{CNPJ};BANCO;2025-01-01;2;2025-02-11"],
    )
    negs = ler_vlmo(conteudo, ANO)
    jan = [n for n in negs if n.data_referencia == date(2025, 1, 1)]
    assert [(n.versao, n.quantidade) for n in jan] == [(2, Decimal(300))]
    assert jan[0].data_entrega == date(2025, 2, 11)
    assert jan[0].cnpj == "00000000000191"
    fev = [n for n in negs if n.data_referencia == date(2025, 2, 1)]
    assert fev[0].data_entrega is None


def test_acentos_latin1_preservados():
    negs = ler_vlmo(_zip([_con(1, "Órgão Estatutário", "Venda à vista", "Ações", 1)]), ANO)
    assert negs[0].tipo_cargo == "Órgão Estatutário"
    assert negs[0].tipo_operacao == "Débito"
    assert negs[0].tipo_ativo == "Ações"


def test_volume_zero_vira_none():
    negs = ler_vlmo(_zip([_con(1, DIR, "Compra à vista", "Ações", 1, vol="0.0000000000")]), ANO)
    assert negs[0].volume is None


def test_compra_liquida_filtra_e_agrupa_por_cargo():
    negs = ler_vlmo(
        _zip(
            [
                _con(1, DIR, "Compra à vista", "Ações", 100, vol="1000"),
                _con(1, DIR, "Venda à vista", "Units", 30, vol="400"),
                _con(1, DIR, "Compra à termo", "Ações", 10),
                _con(1, DIR, "Saldo Inicial", "Ações", 99999),
                _con(1, DIR, "Ações de plano de remuneração", "Ações", 50),
                _con(1, DIR, "Contratação de empréstimo (locador)", "Ações", 50),
                _con(1, DIR, "Posse", "Ações", 50),
                _con(1, DIR, "Desligamento/saída", "Ações", 50),
                _con(1, DIR, "Desdobramento/bonificação", "Ações", 50),
                _con(1, DIR, "Compra à vista", "Opção de Compra", 50),
                _con(1, CTRL, "Venda à vista", "Ações", 20),
                _con(1, CTRL, "Compra à vista", "Ações", 7, dia="2025-03-01"),
                _con(1, DIR, "Compra à vista", "Ações", 7, cnpj="11.111.111/0001-11"),
            ]
        ),
        ANO,
    )
    r = compra_liquida(negs, "00000000000191", date(2025, 1, 1), date(2025, 1, 31))
    assert r[DIR].quantidade == Decimal(80)
    assert r[DIR].volume == Decimal(600)
    assert r[CTRL].quantidade == Decimal(-20)
    assert r[CTRL].volume is None
    assert set(r) == {DIR, CTRL}


def test_zip_invalido():
    with pytest.raises(PacoteInvalido):
        ler_vlmo(b"nao e zip", ANO)
