"""Testes do normalizador: as quatro armadilhas dos CSVs da CVM."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.adaptadores.cvm.normalizador import NormalizadorDeLinhas
from app.dominio.modelo import DRE


def linha_crua(**sobrescritas) -> dict[str, str]:
    base = {
        "CNPJ_CIA": "84.429.695/0001-11",
        "DT_REFER": "2025-12-31",
        "VERSAO": "1",
        "ESCALA_MOEDA": "MIL",
        "ORDEM_EXERC": "ÚLTIMO",
        "DT_INI_EXERC": "2025-01-01",
        "DT_FIM_EXERC": "2025-12-31",
        "CD_CONTA": "3.11",
        "DS_CONTA": "Lucro/Prejuízo Consolidado do Período",
        "VL_CONTA": "6775958.0000000000",
        "ST_CONTA_FIXA": "S",
    }
    base.update(sobrescritas)
    return base


class TestNormalizadorDeLinhas:

    def test_escala_mil_vira_reais(self):
        convertida = NormalizadorDeLinhas().converter(linha_crua(), DRE)

        assert convertida.vl_conta == Decimal("6775958000.0000000000")

    def test_escala_unidade_nao_multiplica(self):
        convertida = NormalizadorDeLinhas().converter(
            linha_crua(ESCALA_MOEDA="UNIDADE", VL_CONTA="42"), DRE
        )

        assert convertida.vl_conta == Decimal("42")

    def test_penultimo_exercicio_e_descartado(self):
        """Sem esse filtro cada conta entra duas vezes e o exercicio duplica."""
        convertida = NormalizadorDeLinhas().converter(
            linha_crua(ORDEM_EXERC="PENÚLTIMO"), DRE
        )

        assert convertida is None

    def test_conta_de_balanco_sem_periodo_inicial_recebe_o_final(self):
        """BPA e BPP nao tem DT_INI_EXERC; NULL na chave unica faria o MySQL
        tratar linhas iguais como distintas."""
        convertida = NormalizadorDeLinhas().converter(linha_crua(DT_INI_EXERC=""), DRE)

        assert convertida.dt_ini_exerc == date(2025, 12, 31)
        assert convertida.dt_ini_exerc == convertida.dt_fim_exerc

    def test_st_conta_fixa_vira_booleano(self):
        fixa = NormalizadorDeLinhas().converter(linha_crua(ST_CONTA_FIXA="S"), DRE)
        livre = NormalizadorDeLinhas().converter(linha_crua(ST_CONTA_FIXA="N"), DRE)

        assert fixa.conta_fixa is True
        assert livre.conta_fixa is False

    def test_valor_vazio_descarta_a_linha(self):
        assert NormalizadorDeLinhas().converter(linha_crua(VL_CONTA=""), DRE) is None

    def test_valor_nao_numerico_descarta_a_linha(self):
        assert NormalizadorDeLinhas().converter(linha_crua(VL_CONTA="n/d"), DRE) is None

    def test_versao_invalida_vira_zero_em_vez_de_estourar(self):
        assert NormalizadorDeLinhas().versao(linha_crua(VERSAO="")) == 0
