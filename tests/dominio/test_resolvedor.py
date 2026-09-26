"""Testes do resolvedor de contas - a peca mais delicada do de-para."""

from __future__ import annotations

from decimal import Decimal

from app.dominio.modelo import BPP, DRE
from app.dominio.plano_contas.regra import RegraConta
from app.dominio.plano_contas.resolvedor import (
    ResolucaoPorCodigo,
    ResolucaoPorRotulo,
    ResolvedorDeContas,
)
from tests.conftest import linha

REGRA_PL = RegraConta(
    metrica="patrimonio_liquido",
    demonstracao=BPP,
    rotulos=("patrimonio liquido consolidado",),
    codigos=("2.03",),
)

REGRA_DIVIDA = RegraConta(
    metrica="divida_bruta",
    demonstracao=BPP,
    rotulos=("emprestimos e financiamentos",),
    codigos=("2.01.04", "2.02.01"),
    somar=True,
)


class TestResolvedorDeContas:

    def test_acha_pl_pelo_rotulo_mesmo_com_codigo_diferente(self, linhas_banco):
        """No BBAS3 o PL esta em 2.07, nao em 2.03 - e 2.03 e 'Provisoes'.

        Este e o caso que derruba qualquer de-para baseado em codigo.
        """
        resolvido = ResolvedorDeContas().resolver(REGRA_PL, linhas_banco[BPP])

        assert resolvido.valor == Decimal("193567416000")
        assert resolvido.cd_conta == "2.07"
        assert resolvido.estrategia == "rotulo"

    def test_acha_pl_no_codigo_padrao_quando_a_empresa_usa_2_03(self, linhas_wege3):
        resolvido = ResolvedorDeContas().resolver(REGRA_PL, linhas_wege3[BPP])

        assert resolvido.valor == Decimal("18553364000")
        assert resolvido.cd_conta == "2.03"

    def test_divida_soma_circulante_e_nao_circulante(self, linhas_wege3):
        resolvido = ResolvedorDeContas().resolver(REGRA_DIVIDA, linhas_wege3[BPP])

        assert resolvido.valor == Decimal("4590822000")
        assert resolvido.cd_conta == "2.01.04+2.02.01"

    def test_divida_nao_soma_conta_sintetica_com_a_filha(self):
        """O mesmo rotulo aparece em 2.01.04 e 2.01.04.01; somar as duas dobra
        a divida. Foi um bug real, achado pelo modo --detalhe do prototipo."""
        linhas = (
            linha("2.01.04", "Empréstimos e Financiamentos", "3549314000", BPP),
            linha("2.01.04.01", "Empréstimos e Financiamentos", "3549314000", BPP),
            linha("2.02.01", "Empréstimos e Financiamentos", "1041508000", BPP),
        )

        resolvido = ResolvedorDeContas().resolver(REGRA_DIVIDA, linhas)

        assert resolvido.valor == Decimal("4590822000")
        assert "2.01.04.01" not in (resolvido.cd_conta or "")

    def test_ignora_conta_nao_padronizada_na_busca_por_rotulo(self):
        """ST_CONTA_FIXA='N' e texto livre da companhia; nao serve de chave."""
        linhas = (
            linha("2.09", "Patrimônio Líquido Consolidado", "999", BPP, conta_fixa=False),
        )

        resolvido = ResolvedorDeContas().resolver(REGRA_PL, linhas)

        assert resolvido.valor is None
        assert resolvido.estrategia == "ausente"

    def test_cai_para_o_codigo_quando_o_rotulo_nao_bate(self):
        linhas = (linha("2.03", "Patrimônio Líquido (outro nome)", "500", BPP),)

        resolvido = ResolvedorDeContas().resolver(REGRA_PL, linhas)

        assert resolvido.valor == Decimal("500")
        assert resolvido.estrategia == "codigo"
        assert "caiu para CD_CONTA" in resolvido.motivo

    def test_sem_linha_nenhuma_devolve_ausente_com_motivo(self):
        resolvido = ResolvedorDeContas().resolver(REGRA_PL, ())

        assert resolvido.ausente
        assert resolvido.estrategia == "ausente"
        assert "BPP" in resolvido.motivo

    def test_escolhe_a_conta_mais_sintetica_quando_ha_varias(self):
        regra = RegraConta(
            metrica="lucro_liquido",
            demonstracao=DRE,
            rotulos=("lucro",),
            codigos=("3.11",),
        )
        linhas = (
            linha("3.11.01.02", "Lucro", "1", DRE),
            linha("3.11", "Lucro", "100", DRE),
        )

        resolvido = ResolvedorDeContas().resolver(regra, linhas)

        assert resolvido.cd_conta == "3.11"

    def test_ordem_das_estrategias_e_respeitada(self, linhas_wege3):
        """Invertendo a ordem, o codigo ganha do rotulo - prova que o
        resolvedor so delega e nao tem preferencia embutida."""
        resolvedor = ResolvedorDeContas([ResolucaoPorCodigo(), ResolucaoPorRotulo()])

        resolvido = resolvedor.resolver(REGRA_PL, linhas_wege3[BPP])

        assert resolvido.estrategia == "codigo"
