"""Plano de seguradora com rotulos reais do DFP 2025 (REQ-07, TASK-E02, ISS-E05)."""

from __future__ import annotations

from datetime import date

from app.dominio.modelo import (
    DRE,
    GRUPO_CONSOLIDADO,
    PLANO_GERAL,
    PLANO_SEGURADORA,
    DocumentoContabil,
)
from app.dominio.plano_contas.classificador import ClassificadorDePlano
from tests.conftest import PERIODO, linha


def _documento(*linhas) -> DocumentoContabil:
    return DocumentoContabil(
        cnpj="17.344.597/0001-94",
        tipo_doc="DFP",
        grupo=GRUPO_CONSOLIDADO,
        versao=1,
        dt_refer=PERIODO,
        dt_fim_exerc=date(2025, 12, 31),
        linhas={DRE: tuple(linhas)},
    )


def test_dre_ifrs17_da_bb_seguridade_e_seguradora():
    # Rotulos e contas do DRE consolidado da BBSE3 no DFP 2025 (conferidos no arquivo da CVM).
    documento = _documento(
        linha("3.01", "Receitas das Atividades Seguradoras/Resseguradoras", "0", DRE),
        linha("3.02", "Despesas da Atividade Seguradora/Resseguradora", "0", DRE),
        linha("3.05", "Outras Receitas e Despesas Operacionais", "4812035000", DRE),
        linha("3.07", "Resultado Antes do Resultado Financeiro e dos Tributos", "9865768000", DRE),
        linha("3.13", "Lucro/Prejuízo Consolidado do Período", "9017329000", DRE),
    )
    assert ClassificadorDePlano().classificar(documento) == PLANO_SEGURADORA


def test_dre_pre_ifrs17_continua_seguradora():
    documento = _documento(linha("3.01", "Receitas de Prêmios de Seguros", "100", DRE))
    assert ClassificadorDePlano().classificar(documento) == PLANO_SEGURADORA


def test_empresa_comum_nao_vira_seguradora():
    documento = _documento(
        linha("3.01", "Receita de Venda de Bens e/ou Serviços", "40804110000", DRE),
        linha("3.05", "Resultado Antes do Resultado Financeiro e dos Tributos", "7998741000", DRE),
    )
    assert ClassificadorDePlano().classificar(documento) == PLANO_GERAL
