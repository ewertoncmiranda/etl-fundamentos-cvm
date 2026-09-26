"""Regressao ponta a ponta do dominio, contra numeros reais do DFP 2025.

Os valores esperados sao os que o prototipo produziu e que foram conferidos
contra o Fundamentus. Se um deles mudar, o de-para mudou de resultado - nao e
refatoracao, e mudanca de comportamento.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.dominio.calculo.calculadora_indicadores import CalculadoraIndicadores
from app.dominio.modelo import (
    GRUPO_CONSOLIDADO,
    PLANO_FINANCEIRO,
    PLANO_GERAL,
    TIPO_DOC_DFP,
    ComposicaoCapital,
    DocumentoContabil,
)
from app.dominio.montador_indicadores import MontadorDeIndicadores
from app.dominio.plano_contas.classificador import ClassificadorDePlano
from app.dominio.plano_contas.resolvedor import ResolvedorDeContas

PERIODO = date(2025, 12, 31)
ACOES_WEGE3 = 4_195_695_973


def montador() -> MontadorDeIndicadores:
    return MontadorDeIndicadores(
        classificador=ClassificadorDePlano(),
        resolvedor=ResolvedorDeContas(),
        calculadora=CalculadoraIndicadores(),
    )


def documento(linhas, cnpj="84.429.695/0001-11") -> DocumentoContabil:
    return DocumentoContabil(
        cnpj=cnpj,
        tipo_doc=TIPO_DOC_DFP,
        grupo=GRUPO_CONSOLIDADO,
        versao=1,
        dt_refer=PERIODO,
        dt_fim_exerc=PERIODO,
        linhas=linhas,
    )


def capital(acoes=ACOES_WEGE3) -> ComposicaoCapital:
    return ComposicaoCapital(
        cnpj="84.429.695/0001-11",
        dt_refer=PERIODO,
        acoes_ex_tesouraria=acoes,
        fonte="FRE",
    )


class TestMontadorDeIndicadores:

    def test_wege3_reproduz_os_numeros_conferidos(self, linhas_wege3):
        indicadores = montador().montar("WEGE3", documento(linhas_wege3), capital())

        assert indicadores.plano_contas == PLANO_GERAL
        assert indicadores.lucro_liquido == Decimal("6775958000")
        assert indicadores.lucro_liquido_controlador == Decimal("6376219000")
        assert indicadores.divida_bruta == Decimal("4590822000")
        # divida liquida negativa = caixa liquido, que e o caso da WEG
        assert indicadores.divida_liquida == Decimal("-1705676000")
        assert round(indicadores.lpa, 4) == Decimal("1.5197")
        assert round(indicadores.vpa, 4) == Decimal("4.1512")
        assert round(indicadores.roe, 2) == Decimal("36.61")
        assert round(indicadores.margem_liquida, 2) == Decimal("16.61")

    def test_banco_nao_recebe_margem_nem_ebit_inventados(self, linhas_banco):
        """No plano FINANCEIRO, 3.01 e receita de intermediacao e 3.05 e lucro
        antes dos tributos. Mapear como receita e EBIT daria numero plausivel
        e errado - por isso a metrica fica nula, com a razao registrada."""
        indicadores = montador().montar("BBAS3", documento(linhas_banco), None)

        assert indicadores.plano_contas == PLANO_FINANCEIRO
        assert indicadores.receita_liquida is None
        assert indicadores.ebit is None
        assert indicadores.margem_liquida is None
        assert indicadores.roic is None
        assert indicadores.cobertura["ebit"]["estrategia"] == "nao-aplicavel"
        assert "nao EBIT" in indicadores.cobertura["ebit"]["motivo"]

    def test_banco_ainda_calcula_o_que_o_plano_comporta(self, linhas_banco):
        indicadores = montador().montar("BBAS3", documento(linhas_banco), None)

        assert indicadores.lucro_liquido == Decimal("16781938000")
        assert indicadores.patrimonio_liquido == Decimal("193567416000")

    def test_sem_composicao_de_capital_nao_ha_lpa_nem_vpa(self, linhas_wege3):
        indicadores = montador().montar("WEGE3", documento(linhas_wege3), None)

        assert indicadores.lpa is None
        assert indicadores.vpa is None
        # ROE nao depende de quantidade de acoes, entao segue existindo
        assert indicadores.roe is not None
        assert indicadores.cobertura["acoes_ex_tesouraria"]["estrategia"] == "ausente"

    def test_capex_e_sempre_declarado_como_nao_extraivel(self, linhas_wege3):
        indicadores = montador().montar("WEGE3", documento(linhas_wege3), capital())

        assert indicadores.capex is None
        assert indicadores.cobertura["capex"]["estrategia"] == "nao-extraivel"

    def test_reescala_de_acoes_fica_registrada_na_cobertura(self, linhas_wege3):
        cap = ComposicaoCapital(
            cnpj="x",
            dt_refer=PERIODO,
            acoes_ex_tesouraria=4_439_159_764,
            fonte="FRE",
            escala_aplicada=1000,
            divergencia_fre_dfp=978.0,
        )

        indicadores = montador().montar("VALE3", documento(linhas_wege3), cap)

        assert "reescalado x1000" in indicadores.cobertura["acoes_ex_tesouraria"]["motivo"]

    def test_tipo_periodo_segue_o_tipo_do_documento(self, linhas_wege3):
        indicadores = montador().montar("WEGE3", documento(linhas_wege3), capital())

        assert indicadores.tipo_periodo == "ANUAL"
        assert indicadores.periodo == PERIODO


class TestCalculadoraIndicadores:

    def test_divisao_por_zero_devolve_none_em_vez_de_estourar(self):
        derivados = CalculadoraIndicadores().calcular(
            {"lucro_liquido_controlador": Decimal("100")}, acoes_ex_tesouraria=0
        )

        assert derivados["lpa"] is None

    def test_insumo_faltando_nao_vira_zero(self):
        derivados = CalculadoraIndicadores().calcular({"lucro_liquido": Decimal("100")})

        assert derivados["margem_liquida"] is None
        assert derivados["divida_liquida"] is None
        assert derivados["roic"] is None

    def test_prejuizo_produz_indicador_negativo_nao_nulo(self):
        derivados = CalculadoraIndicadores().calcular(
            {
                "lucro_liquido_controlador": Decimal("-500"),
                "patrimonio_liquido": Decimal("1000"),
            },
            acoes_ex_tesouraria=100,
        )

        assert derivados["lpa"] == Decimal("-5")
        assert derivados["roe"] == Decimal("-50")

    def test_fcl_soma_operacional_com_investimento_negativo(self):
        derivados = CalculadoraIndicadores().calcular(
            {
                "fluxo_caixa_operacional": Decimal("1000"),
                "fluxo_caixa_investimento": Decimal("-400"),
            }
        )

        assert derivados["fluxo_caixa_livre"] == Decimal("600")
