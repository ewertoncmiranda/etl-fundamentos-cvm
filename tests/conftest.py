"""Fixtures compartilhadas.

Tudo aqui e puro: nenhum teste do dominio toca banco, rede ou arquivo. Os
fakes sao escritos a mao e injetados por construtor, como no repo irmao, mas
conformando aos Protocols das portas - assim nao derivam em silencio quando a
porta muda.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.dominio.modelo import BPA, BPP, DFC_MI, DRE, LinhaContabil

PERIODO = date(2025, 12, 31)


def linha(
    cd_conta: str,
    ds_conta: str,
    valor: str,
    demonstracao: str,
    conta_fixa: bool = True,
) -> LinhaContabil:
    """Atalho para montar LinhaContabil em teste."""
    return LinhaContabil(
        cd_conta=cd_conta,
        ds_conta=ds_conta,
        vl_conta=Decimal(valor),
        conta_fixa=conta_fixa,
        demonstracao=demonstracao,
        dt_ini_exerc=date(2025, 1, 1),
        dt_fim_exerc=PERIODO,
    )


@pytest.fixture
def linhas_wege3() -> dict[str, tuple[LinhaContabil, ...]]:
    """Os numeros reais da WEG no DFP 2025, ja em reais.

    Servem de regressao: qualquer mudanca no de-para que altere estes valores
    esta mudando resultado de verdade, nao refatorando.
    """
    return {
        DRE: (
            linha("3.01", "Receita de Venda de Bens e/ou Serviços", "40804110000", DRE),
            linha(
                "3.05",
                "Resultado Antes do Resultado Financeiro e dos Tributos",
                "7998741000",
                DRE,
            ),
            linha("3.11", "Lucro/Prejuízo Consolidado do Período", "6775958000", DRE),
            linha("3.11.01", "Atribuído a Sócios da Empresa Controladora", "6376219000", DRE),
            linha("3.11.02", "Atribuído a Sócios Não Controladores", "399739000", DRE),
        ),
        BPP: (
            linha("2.01.04", "Empréstimos e Financiamentos", "3549314000", BPP),
            linha("2.02.01", "Empréstimos e Financiamentos", "1041508000", BPP),
            linha("2.03", "Patrimônio Líquido Consolidado", "18553364000", BPP),
            linha("2.03.09", "Participação dos Acionistas Não Controladores", "1136179000", BPP),
        ),
        BPA: (
            linha("1.01", "Ativo Circulante", "26910845000", BPA),
            linha("1.01.01", "Caixa e Equivalentes de Caixa", "6296498000", BPA),
        ),
        DFC_MI: (
            linha("6.01", "Caixa Líquido Atividades Operacionais", "6450000000", DFC_MI),
            linha("6.02", "Caixa Líquido Atividades de Investimento", "-2910810000", DFC_MI),
        ),
    }


@pytest.fixture
def linhas_banco() -> dict[str, tuple[LinhaContabil, ...]]:
    """Plano FINANCEIRO, com os numeros do BBAS3.

    O ponto do fixture: aqui 3.05 NAO e EBIT e 2.03 NAO e patrimonio liquido.
    """
    return {
        DRE: (
            linha("3.01", "Receitas de Intermediação Financeira", "319462104000", DRE),
            linha("3.05", "Resultado antes dos Tributos sobre o Lucro", "5613636000", DRE),
            linha("3.11", "Lucro ou Prejuízo Líquido Consolidado do Período", "16781938000", DRE),
        ),
        BPP: (
            linha("2.02", "Passivos Financeiros ao Custo Amortizado", "2149846333000", BPP),
            linha("2.03", "Provisões", "38689885000", BPP),
            linha("2.07", "Patrimônio Líquido Consolidado", "193567416000", BPP),
        ),
        BPA: (linha("1.01", "Caixa e Equivalentes de Caixa", "59635525000", BPA),),
        DFC_MI: (linha("6.01", "Caixa Líquido das Atividades Operacionais", "1000000000", DFC_MI),),
    }
