from datetime import date
from decimal import Decimal

import pytest

from app.dominio.modelo import (
    BPA,
    DRE,
    TIPO_DOC_DFP,
    TIPO_DOC_ITR,
    DocumentoContabil,
    LinhaContabil,
)
from app.dominio.ttm import MontadorTtm


def _linha(valor: str, demonstracao: str, fim: date) -> LinhaContabil:
    return LinhaContabil(
        cd_conta="3.11" if demonstracao == DRE else "1.01",
        ds_conta="Lucro Líquido" if demonstracao == DRE else "Ativo Circulante",
        vl_conta=Decimal(valor),
        conta_fixa=True,
        demonstracao=demonstracao,
        dt_ini_exerc=date(fim.year, 1, 1),
        dt_fim_exerc=fim,
    )


def _documento(tipo: str, fim: date, dre: str, ativo: str = "500") -> DocumentoContabil:
    return DocumentoContabil(
        cnpj="00.000.000/0001-00",
        tipo_doc=tipo,
        grupo="con",
        versao=1,
        dt_refer=fim,
        dt_fim_exerc=fim,
        linhas={DRE: (_linha(dre, DRE, fim),), BPA: (_linha(ativo, BPA, fim),)},
    )


def test_ttm_soma_anual_mais_itr_atual_menos_itr_comparavel():
    documento = MontadorTtm().montar(
        _documento(TIPO_DOC_DFP, date(2025, 12, 31), "100"),
        _documento(TIPO_DOC_ITR, date(2026, 9, 30), "80", ativo="700"),
        _documento(TIPO_DOC_ITR, date(2025, 9, 30), "60", ativo="600"),
    )

    assert documento.tipo_doc == "TTM"
    assert documento.da_demonstracao(DRE)[0].vl_conta == Decimal("120")
    assert documento.da_demonstracao(BPA)[0].vl_conta == Decimal("700")


def test_ttm_rejeita_itr_de_cortes_incomparaveis():
    with pytest.raises(ValueError, match="mesmo corte"):
        MontadorTtm().montar(
            _documento(TIPO_DOC_DFP, date(2025, 12, 31), "100"),
            _documento(TIPO_DOC_ITR, date(2026, 9, 30), "80"),
            _documento(TIPO_DOC_ITR, date(2025, 6, 30), "40"),
        )
