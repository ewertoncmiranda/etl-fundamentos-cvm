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
    DRE,
    GRUPO_CONSOLIDADO,
    GRUPO_INDIVIDUAL,
    PLANO_FINANCEIRO,
    PLANO_GERAL,
    TIPO_DOC_DFP,
    ComposicaoCapital,
    DocumentoContabil,
)
from app.dominio.montador_indicadores import MontadorDeIndicadores
from app.dominio.plano_contas.classificador import ClassificadorDePlano
from app.dominio.plano_contas.resolvedor import ResolvedorDeContas
from tests.conftest import linha

PERIODO = date(2025, 12, 31)
ACOES_WEGE3 = 4_195_695_973


def montador() -> MontadorDeIndicadores:
    return MontadorDeIndicadores(
        classificador=ClassificadorDePlano(),
        resolvedor=ResolvedorDeContas(),
        calculadora=CalculadoraIndicadores(),
    )


def documento(
    linhas, cnpj="84.429.695/0001-11", grupo=GRUPO_CONSOLIDADO
) -> DocumentoContabil:
    return DocumentoContabil(
        cnpj=cnpj,
        tipo_doc=TIPO_DOC_DFP,
        grupo=grupo,
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

    def test_contas_de_qualidade_no_plano_geral(self, linhas_wege3):
        indicadores = montador().montar("WEGE3", documento(linhas_wege3), capital())

        assert indicadores.ativo_circulante == Decimal("26910845000")
        # O fixture da WEG nao tem Ativo Total nem Resultado Bruto: ficam
        # nulos com o motivo, nunca 0.
        assert indicadores.ativo_total is None
        assert indicadores.cobertura["ativo_total"]["estrategia"] == "ausente"
        assert indicadores.lucro_bruto is None

    def test_banco_nao_recebe_contas_de_circulante(self, linhas_banco):
        indicadores = montador().montar("BBAS3", documento(linhas_banco), None)

        assert indicadores.ativo_circulante is None
        assert indicadores.passivo_circulante is None
        assert indicadores.lucro_bruto is None
        assert indicadores.cobertura["ativo_circulante"]["estrategia"] == "nao-aplicavel"

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


def dre_resultado(total: str, controlador: str | None, minoritarios: str | None):
    """So o bloco 3.11 da DRE, no formato do consolidado."""
    linhas = [linha("3.11", "Lucro/Prejuízo Consolidado do Período", total, DRE)]
    if controlador is not None:
        linhas.append(
            linha("3.11.01", "Atribuído a Sócios da Empresa Controladora", controlador, DRE)
        )
    if minoritarios is not None:
        linhas.append(
            linha("3.11.02", "Atribuído a Sócios Não Controladores", minoritarios, DRE)
        )
    return {DRE: tuple(linhas)}


class TestLucroZerado:
    """Lucro exatamente 0 e conta nao preenchida - nunca vai ao mart como 0."""

    def test_tims3_2022_divisao_zerada_usa_o_lucro_total(self):
        # DFP 2022 consolidado da TIM: 3.11 preenchido, 3.11.01 e 3.11.02 em 0
        linhas = dre_resultado("1670755000", "0", "0")

        indicadores = montador().montar("TIMS3", documento(linhas), capital(2_420_804_398))

        assert indicadores.lucro_liquido == Decimal("1670755000")
        assert indicadores.lucro_liquido_controlador == Decimal("1670755000")
        assert round(indicadores.lpa, 2) == Decimal("0.69")
        cobertura = indicadores.cobertura["lucro_liquido_controlador"]
        assert cobertura["estrategia"] == "lucro-total"
        assert cobertura["cd_conta"] == "3.11"

    def test_divisao_inconsistente_fica_nula_com_motivo(self):
        # LREN3 2016: lucro inteiro declarado em nao controladores
        linhas = dre_resultado("625058000", "0", "625058000")

        indicadores = montador().montar("LREN3", documento(linhas), capital())

        assert indicadores.lucro_liquido == Decimal("625058000")
        assert indicadores.lucro_liquido_controlador is None
        assert indicadores.lpa is None
        assert indicadores.cobertura["lucro_liquido_controlador"]["estrategia"] == (
            "inconsistente"
        )

    def test_ecor3_2021_controlador_sai_da_identidade(self):
        # 3.11.01 em 0, mas 3.11.02 preenchido: 3.11.01 = 3.11 - 3.11.02
        linhas = dre_resultado("367262000", "0", "-4780000")

        indicadores = montador().montar("ECOR3", documento(linhas), capital())

        assert indicadores.lucro_liquido_controlador == Decimal("372042000")
        cobertura = indicadores.cobertura["lucro_liquido_controlador"]
        assert cobertura["estrategia"] == "derivada"
        assert cobertura["cd_conta"] == "3.11-3.11.02"

    def test_dre_toda_zerada_nao_grava_zero(self):
        linhas = dre_resultado("0", "0", "0")

        indicadores = montador().montar("TIMS3", documento(linhas), capital())

        assert indicadores.lucro_liquido is None
        assert indicadores.lucro_liquido_controlador is None
        assert indicadores.lpa is None
        assert indicadores.cobertura["lucro_liquido"]["estrategia"] == "zerada"
        assert indicadores.cobertura["lucro_liquido_controlador"]["estrategia"] == "zerada"

    def test_individual_sem_3_11_01_atribui_o_lucro_ao_controlador(self):
        linhas = {DRE: (linha("3.11", "Lucro/Prejuízo do Período", "2957174000", DRE),)}

        indicadores = montador().montar(
            "TIMS3", documento(linhas, grupo=GRUPO_INDIVIDUAL), capital()
        )

        assert indicadores.lucro_liquido_controlador == Decimal("2957174000")
        assert indicadores.cobertura["lucro_liquido_controlador"]["estrategia"] == (
            "lucro-total"
        )

    def test_consolidado_preenchido_nao_e_alterado(self, linhas_wege3):
        indicadores = montador().montar("WEGE3", documento(linhas_wege3), capital())

        assert indicadores.lucro_liquido_controlador == Decimal("6376219000")
        assert indicadores.cobertura["lucro_liquido_controlador"]["estrategia"] == "rotulo"


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
