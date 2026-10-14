"""Proventos por periodo a partir da DVA (plano LAC, L1)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.aplicacao.carregar_proventos import escolher_grupo
from app.dominio.modelo import (
    DRE,
    DVA,
    GRUPO_CONSOLIDADO,
    GRUPO_INDIVIDUAL,
    TIPO_DOC_DFP,
    TIPO_DOC_ITR,
    DocumentoContabil,
    LinhaContabil,
)
from app.dominio.plano_contas.resolvedor import ResolvedorDeContas
from app.dominio.provento import (
    Acumulado,
    ProventoPeriodo,
    acumulado_do_documento,
    isolar_periodos,
    por_acao,
)

WEG = "84.429.695/0001-11"


def dva(fim: date, jcp: str | None, dividendos: str | None) -> tuple[LinhaContabil, ...]:
    def linha(cd: str, ds: str, valor: str) -> LinhaContabil:
        return LinhaContabil(
            cd_conta=cd, ds_conta=ds, vl_conta=Decimal(valor), conta_fixa=True,
            demonstracao=DVA, dt_ini_exerc=date(fim.year, 1, 1), dt_fim_exerc=fim,
        )

    linhas = [linha("7.08.04", "Remuneração de Capitais Próprios", "6318763000")]
    if jcp is not None:
        linhas.append(linha("7.08.04.01", "Juros sobre o Capital Próprio", jcp))
    if dividendos is not None:
        linhas.append(linha("7.08.04.02", "Dividendos", dividendos))
    return tuple(linhas)


def documento(
    tipo: str, fim: date, linhas_dva, grupo: str = GRUPO_CONSOLIDADO
) -> DocumentoContabil:
    linhas = {DVA: linhas_dva} if linhas_dva is not None else {DRE: ()}
    return DocumentoContabil(
        cnpj=WEG, tipo_doc=tipo, grupo=grupo, versao=1,
        dt_refer=fim, dt_fim_exerc=fim, linhas=linhas,
    )


def acumulado(tipo: str, fim: date, jcp: str, dividendos: str) -> Acumulado:
    return Acumulado(
        tipo_doc=tipo, versao=1, dt_ini=date(fim.year, 1, 1), dt_fim=fim,
        jcp=Decimal(jcp), dividendos=Decimal(dividendos),
    )


class TestAcumuladoDoDocumento:

    def test_weg_dfp_2024_valores_da_cvm(self):
        # dfp_cia_aberta_DVA_con_2024.csv, WEG, conferido em 30-09-2026.
        fim = date(2024, 12, 31)
        doc = documento(TIPO_DOC_DFP, fim, dva(fim, "1134258000", "2056668000"))

        a = acumulado_do_documento(doc, ResolvedorDeContas())

        assert a.jcp == Decimal("1134258000")
        assert a.dividendos == Decimal("2056668000")

    def test_dva_publicada_sem_a_conta_vale_zero(self):
        doc = documento(TIPO_DOC_DFP, date(2024, 12, 31), dva(date(2024, 12, 31), None, "10"))

        a = acumulado_do_documento(doc, ResolvedorDeContas())

        assert a.jcp == Decimal(0)
        assert a.dividendos == Decimal("10")

    def test_sem_dva_e_ausencia_nao_zero(self):
        doc = documento(TIPO_DOC_DFP, date(2024, 12, 31), None)

        assert acumulado_do_documento(doc, ResolvedorDeContas()) is None


class TestIsolarPeriodos:

    def test_trimestres_isolados_e_quarto_pela_dfp(self):
        itrs = [
            acumulado(TIPO_DOC_ITR, date(2024, 3, 31), "100", "0"),
            acumulado(TIPO_DOC_ITR, date(2024, 6, 30), "250", "400"),
            acumulado(TIPO_DOC_ITR, date(2024, 9, 30), "300", "400"),
        ]
        dfp = acumulado(TIPO_DOC_DFP, date(2024, 12, 31), "500", "900")

        periodos = isolar_periodos(itrs, dfp)

        assert [(p.dt_ini, p.dt_fim, p.jcp, p.dividendos) for p in periodos] == [
            (date(2024, 1, 1), date(2024, 3, 31), Decimal("100"), Decimal("0")),
            (date(2024, 4, 1), date(2024, 6, 30), Decimal("150"), Decimal("400")),
            (date(2024, 7, 1), date(2024, 9, 30), Decimal("50"), Decimal("0")),
            (date(2024, 10, 1), date(2024, 12, 31), Decimal("200"), Decimal("500")),
        ]
        assert periodos[-1].tipo_doc == TIPO_DOC_DFP

    def test_trimestre_faltando_o_seguinte_cobre_os_dois(self):
        itrs = [
            acumulado(TIPO_DOC_ITR, date(2024, 3, 31), "100", "0"),
            acumulado(TIPO_DOC_ITR, date(2024, 9, 30), "300", "0"),
        ]

        periodos = isolar_periodos(itrs, None)

        assert (periodos[1].dt_ini, periodos[1].jcp) == (date(2024, 4, 1), Decimal("200"))

    def test_so_dfp_vira_o_ano_inteiro(self):
        periodos = isolar_periodos([], acumulado(TIPO_DOC_DFP, date(2024, 12, 31), "500", "900"))

        assert [(p.dt_ini, p.dt_fim) for p in periodos] == [(date(2024, 1, 1), date(2024, 12, 31))]

    def test_reapresentacao_fica_sem_valor_com_motivo(self):
        itrs = [
            acumulado(TIPO_DOC_ITR, date(2024, 3, 31), "100", "0"),
            acumulado(TIPO_DOC_ITR, date(2024, 6, 30), "80", "0"),
        ]

        periodos = isolar_periodos(itrs, None)

        assert periodos[1].jcp is None and periodos[1].dividendos is None
        assert "reapresentacao" in periodos[1].motivo


class TestPorAcao:

    def test_soma_jcp_e_dividendos_sobre_acoes(self):
        periodo = ProventoPeriodo(
            TIPO_DOC_DFP, 1, date(2024, 1, 1), date(2024, 12, 31), Decimal("30"), Decimal("70")
        )

        assert por_acao(periodo, 50) == Decimal("2")
        assert por_acao(periodo, None) is None


class TestEscolherGrupo:

    def test_dfp_consolidada_vence(self):
        dfps = [documento(TIPO_DOC_DFP, date(2024, 12, 31), (), GRUPO_CONSOLIDADO),
                documento(TIPO_DOC_DFP, date(2024, 12, 31), (), GRUPO_INDIVIDUAL)]

        assert escolher_grupo(WEG, dfps, []) == GRUPO_CONSOLIDADO

    def test_sem_dfp_grupo_com_mais_itrs(self):
        itrs = [documento(TIPO_DOC_ITR, date(2026, 3, 31), (), GRUPO_INDIVIDUAL),
                documento(TIPO_DOC_ITR, date(2026, 6, 30), (), GRUPO_INDIVIDUAL),
                documento(TIPO_DOC_ITR, date(2026, 6, 30), (), GRUPO_CONSOLIDADO)]

        assert escolher_grupo(WEG, [], itrs) == GRUPO_INDIVIDUAL

    def test_sem_documento_nenhum(self):
        assert escolher_grupo(WEG, [], []) is None
