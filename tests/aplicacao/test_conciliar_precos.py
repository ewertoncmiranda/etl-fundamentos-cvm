"""Conciliacao BRAPI x COTAHIST: regra do dia e registro em etl_execucao."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

from app.aplicacao.conciliar_precos import ConciliarPrecos
from app.dominio.conciliacao import (
    DIVERGENTE_PRECO,
    DIVERGENTE_VOLUME,
    FONTE_CONCILIACAO,
    GRAVE,
    OK,
    SEM_B3,
    SEM_BRAPI,
    LinhaConciliacao,
    resumir,
)
from app.dominio.modelo import STATUS_ERRO, STATUS_SUCESSO

DIA = date(2026, 9, 29)


def linhas(*codigos: str, graves: tuple[str, ...] = ()) -> list[LinhaConciliacao]:
    return [
        LinhaConciliacao(
            simbolo=f"ATV{i}",
            data_pregao=DIA,
            divergencia=codigo,
            severidade=GRAVE if f"ATV{i}" in graves else None,
        )
        for i, codigo in enumerate(codigos)
    ]


class TestResumo:

    def test_dia_limpo_nao_alerta(self):
        resumo = resumir(DIA, linhas(*[OK] * 30))

        assert resumo.comparaveis == 30
        assert resumo.divergentes == 0
        assert not resumo.alerta

    def test_um_grave_basta_para_alertar(self):
        resumo = resumir(DIA, linhas(*[OK] * 99, DIVERGENTE_PRECO, graves=("ATV99",)))

        assert resumo.alerta
        assert "GRAVE: ATV99" in resumo.mensagem()

    def test_divergencia_leve_acima_de_2_por_cento_alerta(self):
        resumo = resumir(DIA, linhas(*[OK] * 30, *[DIVERGENTE_PRECO] * 1))

        assert resumo.taxa_divergencia_preco > Decimal("0.02")
        assert resumo.alerta

    def test_sem_brapi_e_sem_b3_nao_contam_como_comparaveis(self):
        # Falha de captura nao e divergencia da fonte: fica fora da taxa.
        resumo = resumir(DIA, linhas(*[OK] * 50, SEM_BRAPI, SEM_B3, DIVERGENTE_VOLUME))

        assert resumo.comparaveis == 51
        assert resumo.divergentes == 1
        assert not resumo.alerta


class RepositorioFake:
    def __init__(self, disponivel=True, pregoes=(), por_dia=None):
        self._disponivel = disponivel
        self._pregoes = list(pregoes)
        self._por_dia = por_dia or {}

    def disponivel(self, db):
        return self._disponivel

    def pregoes_a_conciliar(self, db):
        return self._pregoes

    def linhas(self, db, data_pregao):
        return self._por_dia.get(data_pregao, [])


class ExecucaoFake:
    def __init__(self):
        self.registros = []

    def registrar(self, db, fonte, competencia, arquivo, status, **extras):
        self.registros.append((fonte, competencia, status, extras))


class UowFake:
    @contextmanager
    def transacao(self):
        yield object()


def caso(repositorio) -> tuple[ConciliarPrecos, ExecucaoFake]:
    execucao = ExecucaoFake()
    return ConciliarPrecos(UowFake(), repositorio, execucao, logging.getLogger("teste")), execucao


class TestConciliarPrecos:

    def test_antes_da_v15_so_avisa(self):
        uc, execucao = caso(RepositorioFake(disponivel=False))

        resultado = uc.executar()

        assert not resultado.disponivel
        assert not resultado.alerta
        assert execucao.registros == []

    def test_registra_um_veredito_por_pregao(self):
        outro = date(2026, 9, 30)
        uc, execucao = caso(
            RepositorioFake(
                pregoes=[DIA, outro],
                por_dia={
                    DIA: linhas(OK, OK),
                    outro: linhas(OK, DIVERGENTE_PRECO, graves=("ATV1",)),
                },
            )
        )

        resultado = uc.executar()

        assert resultado.alerta
        assert [(f, c, s) for f, c, s, _ in execucao.registros] == [
            (FONTE_CONCILIACAO, "2026-09-29", STATUS_SUCESSO),
            (FONTE_CONCILIACAO, "2026-09-30", STATUS_ERRO),
        ]
        assert execucao.registros[1][3]["linhas_carregadas"] == 1

    def test_data_explicita_ignora_a_lista_de_pendentes(self):
        uc, execucao = caso(RepositorioFake(pregoes=[], por_dia={DIA: linhas(OK)}))

        uc.executar(DIA)

        assert [c for _, c, _, _ in execucao.registros] == ["2026-09-29"]

    def test_pregao_sem_foto_nao_registra(self):
        uc, execucao = caso(RepositorioFake(pregoes=[DIA], por_dia={}))

        resultado = uc.executar()

        assert resultado.resumos == []
        assert execucao.registros == []
