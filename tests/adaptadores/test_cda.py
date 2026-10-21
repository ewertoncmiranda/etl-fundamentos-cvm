"""Leitor do CDA: filtro de acoes, PL, CONFID ignorado e fluxo por ativo."""

from __future__ import annotations

import io
import zipfile
from datetime import date
from decimal import Decimal

from app.adaptadores.cvm.cda import PosicaoFundoAcao, fluxo_por_ativo, ler_cda_acoes

COMP = "202609"
CAB4 = (
    "TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;DENOM_SOCIAL;DT_COMPTC;TP_APLIC;TP_ATIVO;EMISSOR_LIGADO;"
    "TP_NEGOC;QT_VENDA_NEGOC;VL_VENDA_NEGOC;QT_AQUIS_NEGOC;VL_AQUIS_NEGOC;QT_POS_FINAL;"
    "VL_MERC_POS_FINAL;VL_CUSTO_POS_FINAL;DT_CONFID_APLIC;CD_ATIVO;DS_ATIVO;CD_ISIN;"
    "DT_INI_VIGENCIA;DT_FIM_VIGENCIA"
)
CAB_PL = "TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;DENOM_SOCIAL;DT_COMPTC;VL_PATRIM_LIQ"


def _b4(cnpj, aplic, ativo, qt, vl):
    return f"FIF;{cnpj};FUNDO AÇÕES;2026-09-30;{aplic};Ação ordinária;N;;0;0;0;0;{qt};{vl};0;;{ativo};X;BR{ativo};;"


def _zip(b4, pl, extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"cda_fi_BLC_4_{COMP}.csv", "\n".join([CAB4, *b4]).encode("latin-1"))
        z.writestr(f"cda_fi_PL_{COMP}.csv", "\n".join([CAB_PL, *pl]).encode("latin-1"))
        for nome, txt in (extra or {}).items():
            z.writestr(nome, txt.encode("latin-1"))
    return buf.getvalue()


def test_filtra_acoes_e_junta_pl():
    conteudo = _zip(
        [
            _b4("00.102.322/0001-41", "Ações", "itub3", "100", "3500.5"),
            _b4("00.102.322/0001-41", "Debêntures", "ABCD11", "1", "1"),
            _b4("00.102.322/0001-41", "Empréstimo de ações", "PETR4", "1", "1"),
            _b4("22.222.222/0001-22", "Ações", "PETR4", "10", "300"),
        ],
        ["FIF;00.102.322/0001-41;F;2026-09-30;1000000.25"],
        {f"cda_fi_CONFID_{COMP}.csv": "lixo;sem;cabecalho\n"},
    )
    pos = list(ler_cda_acoes(conteudo, COMP))
    assert [(p.cnpj_fundo, p.simbolo) for p in pos] == [
        ("00102322000141", "ITUB3"),
        ("22222222000122", "PETR4"),
    ]
    assert pos[0] == PosicaoFundoAcao(
        date(2026, 9, 30), "00102322000141", "ITUB3", "BRitub3",
        Decimal(100), Decimal("3500.5"), Decimal("1000000.25"),
    )
    assert pos[1].pl_fundo is None


def _p(cnpj, simbolo, qt):
    return PosicaoFundoAcao(date(2026, 9, 30), cnpj, simbolo, "", Decimal(qt), Decimal(0), None)


def test_fluxo_por_ativo():
    atual = [_p("A", "ITUB3", 100), _p("B", "ITUB3", 50), _p("B", "ITUB3", 5), _p("A", "WEGE3", 1)]
    anterior = [_p("A", "ITUB3", 80), _p("C", "ITUB3", 40), _p("C", "PETR4", 9)]
    f = fluxo_por_ativo(atual, anterior)
    assert (f["ITUB3"].fundos, f["ITUB3"].quantidade, f["ITUB3"].variacao_quantidade) == (2, 155, 35)
    assert (f["ITUB3"].fundos_entraram, f["ITUB3"].fundos_sairam) == (1, 1)
    assert (f["WEGE3"].fundos_entraram, f["WEGE3"].variacao_quantidade) == (1, 1)
    assert (f["PETR4"].fundos, f["PETR4"].fundos_sairam, f["PETR4"].variacao_quantidade) == (0, 1, -9)
