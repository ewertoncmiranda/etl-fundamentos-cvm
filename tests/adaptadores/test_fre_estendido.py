"""Leitor do FRE estendido com CSVs sinteticos em zip em memoria."""

from __future__ import annotations

import io
import zipfile
from datetime import date
from decimal import Decimal

from app.adaptadores.cvm.fre_estendido import (
    Auditor,
    LeitorFreEstendido,
    texto_ou_vazio,
    troca_recente_de_auditor,
    vencimentos_por_ano,
)

CIA = "00.000.000/0001-91"
OUTRA = "11.111.111/0001-11"


def _csv(cabecalho: list[str], linhas: list[list[str]]) -> bytes:
    texto = "\n".join(";".join(l) for l in [cabecalho, *linhas]) + "\n"
    return texto.encode("latin-1")


def _zip(arquivos: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nome, conteudo in arquivos.items():
            z.writestr(f"fre_cia_aberta_{nome}_2025.csv", conteudo)
    return buf.getvalue()


AUD_COLS = [
    "CNPJ_Companhia", "Data_Referencia", "Versao", "Auditor", "CNPJ_Auditor",
    "Data_Inicio_Contratacao", "Data_Fim_Contratacao", "Justificativa_Substituicao",
    "Razao_Apresentada",
]


def _leitor_auditor() -> LeitorFreEstendido:
    linhas = [
        # versao 1 deve ser descartada
        [CIA, "2025-12-31", "1", "VELHA", "1", "2010-01-01", "", "", ""],
        [CIA, "2025-12-31", "2", "DELOITTE", "49928567000111", "2019-02-27", "2024-03-01", "Não aplicável", "N/A"],
        [CIA, "2025-12-31", "2", "KPMG", "57755217000129", "2024-03-20", "", "Não aplicável.", "n/a"],
        [OUTRA, "2025-12-31", "3", "EY", "61366936000125", "2015-01-01", "", "Rodízio obrigatório", "-"],
    ]
    return LeitorFreEstendido(_zip({"auditor": _csv(AUD_COLS, linhas)}), 2025)


def test_auditores_ultima_versao_e_vazios():
    auditores = _leitor_auditor().auditores()
    assert len(auditores) == 3
    assert {a.auditor for a in auditores if a.cnpj == CIA} == {"DELOITTE", "KPMG"}
    kpmg = next(a for a in auditores if a.auditor == "KPMG")
    assert kpmg.justificativa_substituicao is None
    assert kpmg.razao_apresentada is None
    assert kpmg.dt_inicio_contratacao == date(2024, 3, 20)
    ey = next(a for a in auditores if a.auditor == "EY")
    assert ey.justificativa_substituicao == "Rodízio obrigatório"


def test_texto_ou_vazio():
    for vazio in ["Não aplicável", "NÃO APLICÁVEL.", "N/A", "n/a", "NA", "Não se aplica", "", None, " - ",
                  "Não aplicável, tendo em vista que não houve substituição",
                  "Não houve substituição dos auditores independentes"]:
        assert texto_ou_vazio(vazio) is None
    assert texto_ou_vazio("Fim do contrato") == "Fim do contrato"


def test_troca_recente_de_auditor():
    auditores = _leitor_auditor().auditores()
    assert troca_recente_de_auditor(auditores, CIA, date(2025, 12, 31))
    assert not troca_recente_de_auditor(auditores, CIA, date(2026, 6, 1), meses=12)
    assert not troca_recente_de_auditor(auditores, OUTRA, date(2025, 12, 31))
    assert not troca_recente_de_auditor(auditores, "inexistente", date(2025, 12, 31))


def test_troca_por_justificativa_sem_auditor_anterior():
    a = Auditor(CIA, None, 1, "X", "1", date(2025, 1, 1), None, "Rodízio", None)
    assert troca_recente_de_auditor([a], CIA, date(2025, 6, 1))


DIV_COLS = [
    "CNPJ_Companhia", "Data_Referencia", "Versao", "Valor_Mobiliario",
    "Identificacao_Valor_Mobiliario", "Data_Emissao", "Data_Vencimento", "Quantidade",
    "Valor", "Saldo_Devedor", "Conversibilidade",
]


def test_dividas_e_vencimentos_por_ano():
    linhas = [
        [CIA, "2025-12-31", "2", "Debêntures", "1a emissão", "2019-11-15", "2029-11-15", "1250000", "1250000000.00", "1066524000.00", "Não"],
        [CIA, "2025-12-31", "2", "Nota Comercial", "NC", "2024-01-01", "2029-01-10", "10", "100.00", "50.50", "Sim"],
        [CIA, "2025-12-31", "2", "CRI", "CRI", "2024-01-01", "2031-01-10", "10", "100.00", "", ""],
        [CIA, "2025-12-31", "1", "Debêntures", "antiga", "2010-01-01", "2026-01-01", "1", "1", "999", ""],
        [OUTRA, "2025-12-31", "1", "Debêntures", "x", "2020-01-01", "2029-01-01", "1", "1", "7", ""],
    ]
    dividas = LeitorFreEstendido(_zip({"outro_valor_mobiliario": _csv(DIV_COLS, linhas)}), 2025).dividas_valor_mobiliario()
    assert len(dividas) == 4
    deb = next(d for d in dividas if d.identificacao == "1a emissão")
    assert deb.tipo == "Debêntures"
    assert deb.dt_vencimento == date(2029, 11, 15)
    assert deb.quantidade == Decimal("1250000")
    assert deb.saldo_devedor == Decimal("1066524000.00")
    assert deb.conversivel is False
    assert next(d for d in dividas if d.tipo == "Nota Comercial").conversivel is True
    assert vencimentos_por_ano(dividas, CIA) == {2029: Decimal("1066524050.50")}


def test_distribuicao_capital():
    cols = [
        "CNPJ_Companhia", "Data_Referencia", "Versao", "Quantidade_Acionistas_PF",
        "Quantidade_Acionistas_PJ", "Quantidade_Acionistas_Investidores_Institucionais",
        "Quantidade_Total_Acoes_Circulacao", "Percentual_Acoes_Ordinarias_Circulacao",
        "Percentual_Acoes_Preferenciais_Circulacao", "Percentual_Total_Acoes_Circulacao",
    ]
    linhas = [[CIA, "2025-12-31", "22", "1492490", "15317", "1196", "2842496541", "49.600000", "0.000000", "49.600000"]]
    (d,) = LeitorFreEstendido(_zip({"distribuicao_capital": _csv(cols, linhas)}), 2025).distribuicao_capital()
    assert (d.acionistas_pf, d.acionistas_pj, d.acionistas_institucionais) == (1492490, 15317, 1196)
    assert d.qt_acoes_circulacao == 2842496541
    assert d.pct_total_circulacao == Decimal("49.6")


def test_tabela_ausente_devolve_vazio():
    leitor = LeitorFreEstendido(_zip({}), 2025)
    assert leitor.auditores() == []
    assert leitor.distribuicao_capital() == []
