"""Escolha do trio DFP + ITR atual + ITR anterior que compoe o TTM."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.aplicacao.carregar_ttm import escolher_trios
from app.dominio.modelo import (
    DRE,
    GRUPO_CONSOLIDADO,
    GRUPO_INDIVIDUAL,
    TIPO_DOC_DFP,
    TIPO_DOC_ITR,
    DocumentoContabil,
    LinhaContabil,
)
from app.dominio.ttm import MontadorTtm

TIM = "02.421.421/0001-11"
ROTULO = {
    GRUPO_CONSOLIDADO: "Lucro/Prejuízo Consolidado do Período",
    GRUPO_INDIVIDUAL: "Lucro/Prejuízo do Período",
}


def doc(tipo: str, grupo: str, inicio: date, fim: date, lucro: str) -> DocumentoContabil:
    return DocumentoContabil(
        cnpj=TIM,
        tipo_doc=tipo,
        grupo=grupo,
        versao=1,
        dt_refer=fim,
        dt_fim_exerc=fim,
        linhas={
            DRE: (
                LinhaContabil(
                    cd_conta="3.11",
                    ds_conta=ROTULO[grupo],
                    vl_conta=Decimal(lucro),
                    conta_fixa=True,
                    demonstracao=DRE,
                    dt_ini_exerc=inicio,
                    dt_fim_exerc=fim,
                ),
            )
        },
    )


def dfp(grupo: str, lucro: str) -> DocumentoContabil:
    return doc(TIPO_DOC_DFP, grupo, date(2025, 1, 1), date(2025, 12, 31), lucro)


def itr(grupo: str, ano: int, lucro: str, mes: int = 6, dia: int = 30) -> DocumentoContabil:
    return doc(TIPO_DOC_ITR, grupo, date(ano, 1, 1), date(ano, mes, dia), lucro)


class TestEscolherTrios:

    def test_tims3_2026_nao_mistura_consolidado_com_individual(self):
        # TIM: ITR 2026 nos dois grupos, mas ITR 2025 e DFP 2025 so individual
        trios = escolher_trios(
            [dfp(GRUPO_INDIVIDUAL, "4311984000")],
            [itr(GRUPO_CONSOLIDADO, 2026, "1786664000"), itr(GRUPO_INDIVIDUAL, 2026, "1786664000")],
            [itr(GRUPO_INDIVIDUAL, 2025, "1773008000")],
        )

        anual, atual, anterior = trios[TIM]
        assert {anual.grupo, atual.grupo, anterior.grupo} == {GRUPO_INDIVIDUAL}

        ttm = MontadorTtm().montar(anual, atual, anterior)
        (lucro,) = ttm.da_demonstracao(DRE)
        assert lucro.vl_conta == Decimal("4325640000")

    def test_empate_prefere_o_consolidado(self):
        trios = escolher_trios(
            [dfp(GRUPO_CONSOLIDADO, "10"), dfp(GRUPO_INDIVIDUAL, "20")],
            [itr(GRUPO_CONSOLIDADO, 2026, "1"), itr(GRUPO_INDIVIDUAL, 2026, "2")],
            [itr(GRUPO_CONSOLIDADO, 2025, "1"), itr(GRUPO_INDIVIDUAL, 2025, "2")],
        )

        assert trios[TIM][1].grupo == GRUPO_CONSOLIDADO

    def test_corte_mais_recente_vence_o_grupo(self):
        trios = escolher_trios(
            [dfp(GRUPO_CONSOLIDADO, "10"), dfp(GRUPO_INDIVIDUAL, "20")],
            [itr(GRUPO_CONSOLIDADO, 2026, "1", 3, 31), itr(GRUPO_INDIVIDUAL, 2026, "2")],
            [itr(GRUPO_CONSOLIDADO, 2025, "1", 3, 31), itr(GRUPO_INDIVIDUAL, 2025, "2")],
        )

        assert trios[TIM][1].grupo == GRUPO_INDIVIDUAL
        assert trios[TIM][1].dt_fim_exerc == date(2026, 6, 30)

    def test_sem_trio_completo_num_grupo_so_nao_ha_ttm(self):
        trios = escolher_trios(
            [dfp(GRUPO_INDIVIDUAL, "10")],
            [itr(GRUPO_CONSOLIDADO, 2026, "1")],
            [itr(GRUPO_INDIVIDUAL, 2025, "1")],
        )

        assert trios == {}
