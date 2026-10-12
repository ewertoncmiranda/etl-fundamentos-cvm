from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.dominio.identidade import Identidade, canonizar_ativo_objeto_opcao, canonizar_opcoes
from app.dominio.serie_historica import OpcaoB3


def _opcao(ativo_objeto: str | None = "BVMF") -> OpcaoB3:
    return OpcaoB3(
        simbolo="BVMFA10",
        bdi="00",
        data_pregao=date(2026, 1, 2),
        data_vencimento=date(2026, 2, 20),
        preco_exercicio=Decimal("10"),
        abertura=Decimal("1"),
        maxima=Decimal("1"),
        minima=Decimal("1"),
        fechamento=Decimal("1"),
        volume=1,
        numero_negocios=1,
        volume_financeiro=Decimal("1"),
        ativo_objeto=ativo_objeto,
        tipo_opcao="CALL",
        status_validacao="VALIDA",
    )


def test_canoniza_ativo_objeto_de_opcao_pelo_alias_de_identidade():
    identidades = {
        "BVMF3": Identidade(
            simbolo="BVMF3",
            simbolo_canonico="B3SA3",
            cnpj="09.346.601/0001-25",
            continuidade_preco=True,
        )
    }

    assert canonizar_ativo_objeto_opcao("BVMF", identidades) == "B3SA"
    assert canonizar_ativo_objeto_opcao("PETR", identidades) == "PETR"


def test_canonizar_opcoes_preserva_simbolo_negociado_e_atualiza_ativo_objeto():
    identidades = {
        "BVMF3": Identidade(
            simbolo="BVMF3",
            simbolo_canonico="B3SA3",
            cnpj="09.346.601/0001-25",
            continuidade_preco=True,
        )
    }

    (opcao,) = canonizar_opcoes([_opcao()], identidades)

    assert opcao.simbolo == "BVMFA10"
    assert opcao.ativo_objeto == "B3SA"
    assert opcao.status_validacao == "VALIDA"


def test_canonizar_opcoes_mantem_ativo_objeto_ausente():
    (opcao,) = canonizar_opcoes([_opcao(None)], {})

    assert opcao.ativo_objeto is None
