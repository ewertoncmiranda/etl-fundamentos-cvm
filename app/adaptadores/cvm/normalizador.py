"""Aplica as regras de normalizacao da CVM sobre as linhas cruas. So isso.

Sao quatro armadilhas verificadas nos CSVs reais, e todas produzem numero
errado em silencio se ignoradas:

  1. ORDEM_EXERC traz 'ULTIMO' e 'PENULTIMO' na mesma conta -> duplica o exercicio
  2. VERSAO existe por reapresentacao -> so a maior vale
  3. ESCALA_MOEDA='MIL' -> multiplicar por 1000, senao o ROE sai 1000x errado
  4. BPA/BPP nao tem DT_INI_EXERC -> recebe DT_FIM_EXERC, para a chave nao ter nulo
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.dominio.modelo import LinhaContabil
from app.dominio.texto import normalizar

ORDEM_ULTIMO = normalizar("ÚLTIMO")

ESCALAS = {"MIL": 1000, "UNIDADE": 1}


def _data(valor: str | None) -> date | None:
    if not valor:
        return None
    try:
        return datetime.strptime(valor.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _decimal(valor: str | None, fator: int) -> Decimal | None:
    if valor is None or valor.strip() == "":
        return None
    try:
        return Decimal(valor.strip()) * fator
    except InvalidOperation:
        return None


class NormalizadorDeLinhas:
    """Converte uma linha crua do CSV em LinhaContabil, ou None se descartada."""

    def e_exercicio_corrente(self, linha: dict[str, str]) -> bool:
        return normalizar(linha.get("ORDEM_EXERC")) == ORDEM_ULTIMO

    def versao(self, linha: dict[str, str]) -> int:
        try:
            return int(linha.get("VERSAO") or 0)
        except ValueError:
            return 0

    def fator_de_escala(self, linha: dict[str, str]) -> int:
        return ESCALAS.get((linha.get("ESCALA_MOEDA") or "").strip().upper(), 1)

    def converter(self, linha: dict[str, str], demonstracao: str) -> LinhaContabil | None:
        if not self.e_exercicio_corrente(linha):
            return None

        dt_fim = _data(linha.get("DT_FIM_EXERC"))
        if dt_fim is None:
            return None

        valor = _decimal(linha.get("VL_CONTA"), self.fator_de_escala(linha))
        if valor is None:
            return None

        # BPA e BPP nao tem periodo inicial; usar o final mantem a chave unica
        # deterministica em vez de deixar NULL, que o MySQL trata como distinto
        dt_ini = _data(linha.get("DT_INI_EXERC")) or dt_fim

        return LinhaContabil(
            cd_conta=(linha.get("CD_CONTA") or "").strip(),
            ds_conta=(linha.get("DS_CONTA") or "").strip(),
            vl_conta=valor,
            conta_fixa=(linha.get("ST_CONTA_FIXA") or "").strip().upper() == "S",
            demonstracao=demonstracao,
            dt_ini_exerc=dt_ini,
            dt_fim_exerc=dt_fim,
        )
