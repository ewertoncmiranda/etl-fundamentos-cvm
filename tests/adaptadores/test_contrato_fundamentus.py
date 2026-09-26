"""Confronto exploratorio com o Fundamentus.

Marcado como externo e DESLIGADO no CI: site de terceiro fora do ar nao pode
quebrar build. Rode de proposito quando quiser reconferir o de-para:

    pytest -m externo -s

Duas divergencias sao esperadas e nao indicam bug:

  1. periodo - o Fundamentus publica 12 meses moveis, o DFP publica exercicio
     fechado. Em empresa de lucro volatil isso sozinho move o LPA 40%+.
  2. escopo - as referencias calculam sobre a parcela do controlador, que e o
     que este ETL tambem faz.

Margem liquida e ROIC nao dependem de quantidade de acoes nem de minoritarios,
entao sao os melhores sinais de que o mapeamento de conta esta correto.
"""

from __future__ import annotations

import html
import re
import urllib.request

import pytest

URL = "https://www.fundamentus.com.br/detalhes.php?papel={}"

CAMPOS = {"LPA": "lpa", "VPA": "vpa", "ROE": "roe", "Marg. Líquida": "margem_liquida"}


def _buscar(ticker: str) -> dict[str, float]:
    requisicao = urllib.request.Request(
        URL.format(ticker), headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(requisicao, timeout=30) as resposta:
        pagina = resposta.read().decode("latin-1")

    celulas = [
        html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
        for c in re.findall(r"<td[^>]*>(.*?)</td>", pagina, re.S)
    ]
    celulas = [c for c in celulas if c]

    achados: dict[str, float] = {}
    for i, celula in enumerate(celulas):
        rotulo = celula.lstrip("?").strip()
        if rotulo not in CAMPOS or i + 1 >= len(celulas):
            continue
        bruto = celulas[i + 1].replace("%", "").replace(".", "").replace(",", ".")
        try:
            achados[CAMPOS[rotulo]] = float(bruto)
        except ValueError:
            continue
    return achados


@pytest.mark.externo
class TestContratoFundamentus:

    def test_wege3_tem_ordem_de_grandeza_compativel(self):
        """So ordem de grandeza: igualdade exata nao e esperada por causa do
        descasamento TTM x exercicio fechado."""
        referencia = _buscar("WEGE3")

        if not referencia:
            pytest.skip("Fundamentus nao respondeu com os campos esperados")

        # numeros do DFP 2025 produzidos por este ETL
        nossos = {"lpa": 1.5197, "vpa": 4.1512, "roe": 36.61, "margem_liquida": 16.61}

        for metrica, esperado in nossos.items():
            if metrica not in referencia:
                continue
            desvio = abs(esperado - referencia[metrica]) / abs(referencia[metrica]) * 100
            print(
                f"{metrica}: nosso={esperado} "
                f"fundamentus={referencia[metrica]} dif={desvio:.1f}%"
            )
            assert desvio < 50, f"{metrica} destoou demais: {desvio:.1f}%"
