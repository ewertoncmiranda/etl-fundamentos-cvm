"""Eventos corporativos inferidos de marca ex + capital + preco (LAC-ETL-2)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from fractions import Fraction

from app.dominio.evento_corporativo import (
    CONFIANCA_ALTA,
    CONFIANCA_MEDIA,
    TIPO_BONIFICACAO,
    TIPO_DESDOBRAMENTO,
    TIPO_GRUPAMENTO,
    Candidato,
    Composicao,
    EventoInferido,
    PregaoMarcado,
    Rejeicao,
    candidatos,
    e_societaria,
    fracao_simples,
    inferir,
    um_por_intervalo,
)

CNPJ = "00.000.000/0001-91"


def pregao(simbolo, dia, marca, anterior="10", abertura="10", marca_anterior=None) -> PregaoMarcado:
    return PregaoMarcado(simbolo, dia, marca, Decimal(anterior), Decimal(abertura), marca_anterior)


def capital(ano: int, total: int, on: int = 0, pn: int = 0) -> Composicao:
    return Composicao(date(ano, 12, 31), total, on, pn)


class TestMarcas:

    def test_marcas_societarias_do_layout_e_ex(self):
        assert all(e_societaria(m) for m in ("EB", "EG", "EX", "EDB", "EJB", "EBG", "EGS"))

    def test_proventos_e_subscricao_nao_sao_societarias(self):
        assert not any(e_societaria(m) for m in ("ED", "EJ", "EDJ", "ER", "ES", "EDR", None))


class TestCandidatos:

    def test_varios_dias_marcados_sao_um_evento_so(self):
        # RCSL3: EB em 10 e 11/03/2026
        saida = candidatos([
            pregao("RCSL3", date(2026, 3, 10), "EB", "3.06", "0.82"),
            pregao("RCSL3", date(2026, 3, 11), "EB", marca_anterior="EB"),
        ])

        assert [(c.simbolo, c.data) for c in saida] == [("RCSL3", date(2026, 3, 10))]
        assert saida[0].razao_preco == round(3.06 / 0.82, 6)

    def test_marca_de_provento_e_unit_nao_entram(self):
        saida = candidatos([
            pregao("PETR4", date(2026, 6, 3), "EJ"),
            pregao("RNEW11", date(2025, 6, 3), "EG"),
        ])

        assert saida == []

    def test_marca_no_primeiro_dia_de_outro_simbolo_conta(self):
        saida = candidatos([
            pregao("AAAA3", date(2026, 1, 2), "EB"),
            pregao("BBBB3", date(2026, 1, 2), "EB"),
        ])

        assert [c.simbolo for c in saida] == ["AAAA3", "BBBB3"]


class TestFracao:

    def test_desdobramento_grupamento_e_bonificacao(self):
        assert fracao_simples(2.003) == 2
        assert fracao_simples(0.1004) == Fraction(1, 10)
        assert fracao_simples(1.0998) == Fraction(11, 10)
        assert fracao_simples(1 / 125.2) == Fraction(1, 125)
        assert fracao_simples(1.103) == Fraction(11, 10)
        assert fracao_simples(1.497) == Fraction(3, 2)

    def test_emissao_de_1_por_cento_no_ano_nao_vira_bonificacao(self):
        rejeicao = inferir(
            Candidato("BBAS3", date(2025, 6, 4), "EX", 0.997),
            CNPJ,
            [capital(2024, 1000), capital(2025, 1012)],
        )

        assert isinstance(rejeicao, Rejeicao)


class TestInferir:

    def _candidato(self, simbolo, dia, marca, razao_preco):
        return Candidato(simbolo, dia, marca, razao_preco)

    def test_desdobramento_bbas3_2024(self):
        # BB: desdobramento 1:2 com efeito em 16/04/2024, marcado EB
        evento = inferir(
            self._candidato("BBAS3", date(2024, 4, 16), "EB", 2.0),
            CNPJ,
            [capital(2023, 2_865_417_020), capital(2024, 5_730_834_040)],
        )

        assert isinstance(evento, EventoInferido)
        assert evento.tipo == TIPO_DESDOBRAMENTO
        assert evento.fator_acoes == 2
        assert evento.confianca == CONFIANCA_ALTA
        assert evento.evidencia["composicao_antes"]["dt_refer"] == "2023-12-31"

    def test_grupamento_mglu3_2024(self):
        evento = inferir(
            self._candidato("MGLU3", date(2024, 5, 27), "EG", 1.32 / 12.83),
            CNPJ,
            [capital(2023, 6_740_000_000), capital(2024, 674_000_000)],
        )

        assert isinstance(evento, EventoInferido)
        assert evento.tipo == TIPO_GRUPAMENTO
        assert evento.fator_acoes == Fraction(1, 10)

    def test_bonificacao_de_10_por_cento_com_emissao_pequena_no_ano(self):
        # 10% de bonificacao + 0,3% de emissao: capital 1.103, fracao 11/10.
        # (Com 1% de emissao, 1.111, a fracao seria 10/9 - erro de 1%,
        # aceito: o capital da CVM e a fonte da proporcao.)
        evento = inferir(
            self._candidato("ITSA4", date(2025, 12, 19), "EB", 1.10),
            CNPJ,
            [capital(2024, 1_000_000, pn=600_000), capital(2025, 1_103_000, pn=661_800)],
        )

        assert isinstance(evento, EventoInferido)
        assert evento.tipo == TIPO_BONIFICACAO
        assert evento.fator_acoes == Fraction(11, 10)
        assert evento.evidencia["composicao_antes"]["acoes"] == 600_000  # PN, nao o total

    def test_bonificacao_com_capital_misturado_rejeita(self):
        # BBDC4 2016: bonificacao de 10% (preco 1,109) e outro aumento no
        # ano; o capital (1,21) nao serve de proporcao
        rejeicao = inferir(
            self._candidato("BBDC4", date(2016, 4, 18), "EB", 1.108846),
            CNPJ,
            [capital(2015, 5_048_728_847), capital(2016, 6_108_961_905)],
        )

        assert isinstance(rejeicao, Rejeicao)

    def test_preco_a_8_por_cento_da_confianca_media(self):
        evento = inferir(
            self._candidato("AAAA3", date(2025, 5, 2), "EB", 2.16),
            CNPJ,
            [capital(2024, 100), capital(2025, 200)],
        )

        assert isinstance(evento, EventoInferido)
        assert evento.confianca == CONFIANCA_MEDIA

    def test_ex_com_capital_estavel_e_provento(self):
        # EX em ITSA4 com razao 1.065 e capital igual: nao e evento
        rejeicao = inferir(
            self._candidato("ITSA4", date(2025, 2, 18), "EX", 1.065),
            CNPJ,
            [capital(2024, 100), capital(2025, 100)],
        )

        assert isinstance(rejeicao, Rejeicao)
        assert "quase estavel" in rejeicao.motivo

    def test_dois_eventos_no_ano_rejeitam(self):
        # RCSL3 2026: bonificacao em marco e grupamento 4:1 em outubro
        rejeicao = inferir(
            self._candidato("RCSL3", date(2026, 3, 10), "EB", 3.73),
            CNPJ,
            [capital(2025, 1000), capital(2026, 935)],
        )

        assert isinstance(rejeicao, Rejeicao)

    def test_preco_que_nao_confirma_rejeita(self):
        rejeicao = inferir(
            self._candidato("AAAA3", date(2025, 5, 2), "EB", 1.0),
            CNPJ,
            [capital(2024, 100), capital(2025, 200)],
        )

        assert isinstance(rejeicao, Rejeicao)
        assert "preco" in rejeicao.motivo

    def test_ano_corrente_sem_dfp_posterior_fica_de_fora(self):
        rejeicao = inferir(
            self._candidato("VIVT3", date(2026, 4, 15), "EX", 2.0),
            CNPJ,
            [capital(2025, 100)],
        )

        assert isinstance(rejeicao, Rejeicao)
        assert "antes e depois" in rejeicao.motivo


class TestUmPorIntervalo:

    def test_itsa4_2018_dois_candidatos_para_a_mesma_variacao(self):
        composicoes = [capital(2017, 1000, pn=600), capital(2018, 1125, pn=675)]
        fevereiro = inferir(Candidato("ITSA4", date(2018, 2, 23), "EX", 1.047), CNPJ, composicoes)
        junho = inferir(Candidato("ITSA4", date(2018, 6, 1), "EDB", 1.13), CNPJ, composicoes)
        assert isinstance(junho, EventoInferido)

        mantidos, descartados = um_por_intervalo(
            [e for e in (fevereiro, junho) if isinstance(e, EventoInferido)]
        )

        assert [e.data_efeito for e in mantidos] == [date(2018, 6, 1)]
        assert all("mesma variacao" in d.motivo for d in descartados)

    def test_mglu3_2019_desdobramento_com_follow_on_no_ano(self):
        # 1:8 em 06/08/2019; capital 8,52 (follow-on no mesmo ano), preco 7,75
        evento = inferir(
            Candidato("MGLU3", date(2019, 8, 6), "EB", 7.754987),
            CNPJ,
            [capital(2018, 190_000_000), capital(2019, 1_619_690_000)],
        )

        assert isinstance(evento, EventoInferido)
        assert evento.fator_acoes == 8

    def test_bonificacao_com_preco_parado_nao_confirma(self):
        # MGLU3 12/2025: capital +5%, preco 1,015 - ruido, nao evento
        rejeicao = inferir(
            Candidato("MGLU3", date(2025, 12, 30), "EB", 1.015201),
            CNPJ,
            [capital(2024, 1000), capital(2025, 1052)],
        )

        assert isinstance(rejeicao, Rejeicao)
