"""Escolha entre consolidado e individual no DFP."""

from __future__ import annotations

import logging

from app.adaptadores.cvm.fonte_cvm import FonteCvm
from app.dominio.modelo import DRE, GRUPO_CONSOLIDADO, GRUPO_INDIVIDUAL
from tests.conftest import PERIODO, linha

TIM = "02.421.421/0001-11"
WEG = "84.429.695/0001-11"


def _dados(*linhas):
    return {
        "versao": 1,
        "dt_refer": PERIODO,
        "dt_fim_exerc": PERIODO,
        "linhas": {DRE: list(linhas)},
    }


def _fonte(por_grupo: dict[str, dict[str, dict]]) -> tuple[FonteCvm, list]:
    pedidos: list = []
    fonte = FonteCvm(None, None, None, logging.getLogger("teste"))  # type: ignore[arg-type]

    def demonstracoes(ano, cnpjs, grupo):
        pedidos.append((grupo, set(cnpjs)))
        return {c: d for c, d in por_grupo[grupo].items() if c in cnpjs}

    fonte._demonstracoes = demonstracoes  # type: ignore[method-assign]
    return fonte, pedidos


class TestEscolhaDoGrupo:

    def test_consolidado_todo_zerado_cai_para_o_individual(self):
        # TIM 2024: consolidado entregue com todas as contas em 0
        fonte, _ = _fonte(
            {
                GRUPO_CONSOLIDADO: {
                    TIM: _dados(linha("3.11", "Lucro/Prejuízo Consolidado do Período", "0", DRE)),
                    WEG: _dados(linha("3.11", "Lucro/Prejuízo Consolidado do Período", "1", DRE)),
                },
                GRUPO_INDIVIDUAL: {
                    TIM: _dados(linha("3.11", "Lucro/Prejuízo do Período", "3153881000", DRE)),
                    WEG: _dados(linha("3.11", "Lucro/Prejuízo do Período", "2", DRE)),
                },
            }
        )

        documentos = {d.cnpj: d for d in fonte.documentos(2024, {TIM, WEG})}

        assert documentos[TIM].grupo == GRUPO_INDIVIDUAL
        assert documentos[TIM].da_demonstracao(DRE)[0].vl_conta == 3153881000
        assert documentos[WEG].grupo == GRUPO_CONSOLIDADO

    def test_consolidado_preenchido_nao_busca_individual(self):
        fonte, pedidos = _fonte(
            {
                GRUPO_CONSOLIDADO: {
                    WEG: _dados(linha("3.11", "Lucro/Prejuízo Consolidado do Período", "1", DRE)),
                },
                GRUPO_INDIVIDUAL: {},
            }
        )

        list(fonte.documentos(2025, {WEG}))

        assert (GRUPO_INDIVIDUAL, {WEG}) not in pedidos
