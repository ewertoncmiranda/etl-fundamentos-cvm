"""Escolha entre consolidado e individual no DFP."""

from __future__ import annotations

import logging
from datetime import date

from app.adaptadores.cvm.fonte_cvm import FonteCvm
from app.adaptadores.cvm.normalizador import NormalizadorDeLinhas
from app.dominio.modelo import DRE, GRUPO_CONSOLIDADO, GRUPO_INDIVIDUAL
from tests.conftest import PERIODO, linha

TIM = "02.421.421/0001-11"
WEG = "84.429.695/0001-11"
ITUB = "60.872.504/0001-23"


def _dados(*linhas):
    return {
        "versao": 1,
        "dt_refer": PERIODO,
        "dt_fim_exerc": PERIODO,
        "linhas": {DRE: list(linhas)},
    }


def _fonte(por_grupo: dict[str, dict[str, dict]]) -> tuple[FonteCvm, list]:
    pedidos: list = []
    fonte = FonteCvm(None, None, None, logging.getLogger("teste"))  # type: ignore[arg-type]

    def demonstracoes(ano, cnpjs, grupo):
        pedidos.append((grupo, set(cnpjs)))
        return {c: d for c, d in por_grupo[grupo].items() if c in cnpjs}

    fonte._demonstracoes = demonstracoes  # type: ignore[method-assign]
    return fonte, pedidos


class TestEscolhaDoGrupo:

    def test_consolidado_todo_zerado_cai_para_o_individual(self):
        # TIM 2024: consolidado entregue com todas as contas em 0
        fonte, _ = _fonte(
            {
                GRUPO_CONSOLIDADO: {
                    TIM: _dados(linha("3.11", "Lucro/Prejuízo Consolidado do Período", "0", DRE)),
                    WEG: _dados(linha("3.11", "Lucro/Prejuízo Consolidado do Período", "1", DRE)),
                },
                GRUPO_INDIVIDUAL: {
                    TIM: _dados(linha("3.11", "Lucro/Prejuízo do Período", "3153881000", DRE)),
                    WEG: _dados(linha("3.11", "Lucro/Prejuízo do Período", "2", DRE)),
                },
            }
        )

        documentos = {d.cnpj: d for d in fonte.documentos(2024, {TIM, WEG})}

        assert documentos[TIM].grupo == GRUPO_INDIVIDUAL
        assert documentos[TIM].da_demonstracao(DRE)[0].vl_conta == 3153881000
        assert documentos[WEG].grupo == GRUPO_CONSOLIDADO

    def test_todos_os_grupos_entrega_os_dois_menos_os_zerados(self):
        fonte, _ = _fonte(
            {
                GRUPO_CONSOLIDADO: {
                    TIM: _dados(linha("3.11", "Lucro/Prejuízo Consolidado do Período", "0", DRE)),
                    WEG: _dados(linha("3.11", "Lucro/Prejuízo Consolidado do Período", "1", DRE)),
                },
                GRUPO_INDIVIDUAL: {
                    TIM: _dados(linha("3.11", "Lucro/Prejuízo do Período", "3", DRE)),
                    WEG: _dados(linha("3.11", "Lucro/Prejuízo do Período", "2", DRE)),
                },
            }
        )

        documentos = fonte.documentos(2024, {TIM, WEG}, todos_os_grupos=True)

        assert sorted((d.cnpj, d.grupo) for d in documentos) == [
            (TIM, GRUPO_INDIVIDUAL),
            (WEG, GRUPO_CONSOLIDADO),
            (WEG, GRUPO_INDIVIDUAL),
        ]

    def test_consolidado_preenchido_nao_busca_individual(self):
        fonte, pedidos = _fonte(
            {
                GRUPO_CONSOLIDADO: {
                    WEG: _dados(linha("3.11", "Lucro/Prejuízo Consolidado do Período", "1", DRE)),
                },
                GRUPO_INDIVIDUAL: {},
            }
        )

        list(fonte.documentos(2025, {WEG}))

        assert (GRUPO_INDIVIDUAL, {WEG}) not in pedidos


class _ClienteFalso:
    def __init__(self, etag: str | None):
        self.etag = etag
        self.heads = 0
        self.downloads = 0

    def assinatura(self, caminho):
        from app.adaptadores.cvm.cliente_http import Assinatura

        self.heads += 1
        return Assinatura(etag=self.etag, last_modified=None, tamanho_bytes=None)

    def baixar(self, caminho):
        self.downloads += 1
        return f"novo-{self.etag}".encode()


def _fonte_com_cache(tmp_path, etag):
    from datetime import date

    from app.adaptadores.cvm.cache_local import CacheDeArquivos

    cliente = _ClienteFalso(etag)
    cache = CacheDeArquivos(tmp_path)
    fonte = FonteCvm(
        cliente, cache, None, logging.getLogger("teste"),  # type: ignore[arg-type]
        hoje=lambda: date(2026, 10, 7),
    )
    return fonte, cliente, cache


class TestCacheDoAnoAberto:

    def test_ano_corrente_republicado_baixa_de_novo(self, tmp_path):
        fonte, cliente, cache = _fonte_com_cache(tmp_path, '"v2"')
        cache.gravar("itr_cia_aberta_2026.zip", b"velho", '"v1"')

        fonte.assinatura("ITR", 2026)  # a carga decide processar
        conteudo = fonte._conteudo("ITR", 2026)

        assert conteudo == b'novo-"v2"'
        assert cache.etag_de("itr_cia_aberta_2026.zip") == '"v2"'
        assert cliente.heads == 1  # o download reaproveita o HEAD da carga

    def test_ano_corrente_com_mesmo_etag_usa_o_cache(self, tmp_path):
        fonte, cliente, cache = _fonte_com_cache(tmp_path, '"v1"')
        cache.gravar("dfp_cia_aberta_2025.zip", b"igual", '"v1"')

        assert fonte._conteudo("DFP", 2025) == b"igual"
        assert cliente.downloads == 0

    def test_copia_antiga_sem_etag_gravado_e_baixada_uma_vez(self, tmp_path):
        fonte, cliente, cache = _fonte_com_cache(tmp_path, '"v1"')
        cache.gravar("fre_cia_aberta_2026.zip", b"sem-marca")

        fonte._conteudo("FRE", 2026)
        fonte._conteudo("FRE", 2026)

        assert cliente.downloads == 1

    def test_ano_fechado_nem_consulta_a_cvm(self, tmp_path):
        fonte, cliente, cache = _fonte_com_cache(tmp_path, '"v2"')
        cache.gravar("dfp_cia_aberta_2023.zip", b"fechado")

        assert fonte._conteudo("DFP", 2023) == b"fechado"
        assert cliente.heads == 0 and cliente.downloads == 0

    def test_cvm_sem_etag_mantem_a_copia(self, tmp_path):
        fonte, cliente, cache = _fonte_com_cache(tmp_path, None)
        cache.gravar("itr_cia_aberta_2026.zip", b"velho", '"v1"')

        assert fonte._conteudo("ITR", 2026) == b"velho"
        assert cliente.downloads == 0


class TestSoAcumulado:

    def _linha(self, inicio, valor):
        from datetime import date
        from decimal import Decimal

        from app.dominio.modelo import LinhaContabil

        return LinhaContabil(
            cd_conta="3.11", ds_conta="Lucro", vl_conta=Decimal(valor), conta_fixa=True,
            demonstracao=DRE, dt_ini_exerc=inicio, dt_fim_exerc=date(2025, 12, 31),
        )

    def test_ano_civil_fica_com_o_acumulado_desde_janeiro(self):
        from datetime import date

        from app.adaptadores.cvm.fonte_cvm import _so_acumulado

        linhas = [self._linha(date(2025, 10, 1), "3"), self._linha(date(2025, 1, 1), "9")]

        assert [linha.vl_conta for linha in _so_acumulado(linhas)] == [9]

    def test_exercicio_de_abril_fica_com_o_acumulado_desde_abril(self):
        # RAIZ4, ITR de dezembro: trimestre out-dez e acumulado abr-dez.
        # O filtro antigo (1o/1) descartava os dois e a empresa ficava sem TTM.
        from datetime import date

        from app.adaptadores.cvm.fonte_cvm import _so_acumulado

        linhas = [self._linha(date(2025, 10, 1), "3"), self._linha(date(2025, 4, 1), "7")]

        assert [linha.vl_conta for linha in _so_acumulado(linhas)] == [7]


class _LeitorFalso:
    def __init__(self, arquivo, linhas):
        self._arquivo = arquivo
        self._linhas = linhas

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def tem(self, arquivo):
        return arquivo == self._arquivo

    def linhas(self, arquivo):
        assert arquivo == self._arquivo
        yield from self._linhas


class TestComposicaoCapitalFre:

    def test_le_breakdown_do_dfp_pelos_nomes_reais_das_colunas(self):
        arquivo = "dfp_cia_aberta_composicao_capital_2025.csv"
        linhas = [
            {
                "CNPJ_CIA": ITUB,
                "DT_REFER": "2025-12-31",
                "VERSAO": "2",
                "QT_ACAO_ORDIN_CAP_INTEGR": "5617743",
                "QT_ACAO_PREF_CAP_INTEGR": "5409126",
                "QT_ACAO_TOTAL_CAP_INTEGR": "11026869",
                "QT_ACAO_TOTAL_TESOURO": "345",
            }
        ]
        fonte = FonteCvm(
            None, None, NormalizadorDeLinhas(), logging.getLogger("teste")  # type: ignore[arg-type]
        )
        fonte._leitor = lambda *_: _LeitorFalso(arquivo, linhas)  # type: ignore[method-assign]

        capital = fonte._composicao_do_dfp(2025, {ITUB})[ITUB]

        assert capital["qt_acao_ordinaria"] == 5_617_743
        assert capital["qt_acao_preferencial"] == 5_409_126

    def test_le_fre_por_classe_e_mantem_apenas_a_maior_versao(self):
        arquivo = "fre_cia_aberta_capital_social_2025.csv"
        linhas = [
            {
                "CNPJ_Companhia": WEG,
                "Tipo_Capital": "Capital Integralizado",
                "Quantidade_Total_Acoes": "100",
                "Quantidade_Acoes_Ordinarias": "70",
                "Quantidade_Acoes_Preferenciais": "30",
                "Versao": "1",
            },
            {
                "CNPJ_Companhia": WEG,
                "Tipo_Capital": "Capital Integralizado",
                "Quantidade_Total_Acoes": "120",
                "Quantidade_Acoes_Ordinarias": "80",
                "Quantidade_Acoes_Preferenciais": "40",
                "Versao": "2",
            },
        ]
        fonte = FonteCvm(None, None, None, logging.getLogger("teste"))  # type: ignore[arg-type]
        fonte._leitor = lambda *_: _LeitorFalso(arquivo, linhas)  # type: ignore[method-assign]

        assert fonte._capital_do_fre(2025, {WEG}) == {
            WEG: {
                "versao": 2,
                "total": 120,
                "qt_acao_ordinaria": 80,
                "qt_acao_preferencial": 40,
            }
        }

    def test_aceite_itub4_fre_autoritativo_bate_com_dfp_apos_escala(self):
        fonte = FonteCvm(None, None, None, logging.getLogger("teste"))  # type: ignore[arg-type]
        fonte._composicao_do_dfp = lambda *_: {  # type: ignore[method-assign]
            ITUB: {
                "versao": 2,
                "dt_refer": date(2025, 12, 31),
                "total": 11_026_869,
                "tesouraria": 345,
                "qt_acao_ordinaria": 5_617_743,
                "qt_acao_preferencial": 5_409_126,
            }
        }
        fonte._capital_do_fre = lambda *_: {  # type: ignore[method-assign]
            ITUB: {
                "versao": 13,
                "total": 11_026_869_192,
                "qt_acao_ordinaria": 5_617_742_977,
                "qt_acao_preferencial": 5_409_126_215,
            }
        }

        capital = fonte.composicoes_de_capital(2025, {ITUB})[ITUB]

        assert capital.escala_aplicada == 1000
        assert capital.qt_acao_ordinaria == 5_617_742_977
        assert capital.qt_acao_preferencial == 5_409_126_215
        assert abs(capital.qt_acao_ordinaria - 5_617_743 * 1000) < 1000
        assert abs(capital.qt_acao_preferencial - 5_409_126 * 1000) < 1000

    def test_fre_e_autoritativo_para_on_pn_e_dfp_completa_classe_ausente(self):
        fonte = FonteCvm(None, None, None, logging.getLogger("teste"))  # type: ignore[arg-type]
        fonte._composicao_do_dfp = lambda *_: {  # type: ignore[method-assign]
            WEG: {
                "versao": 1,
                "dt_refer": date(2025, 12, 31),
                "total": 5_000_000,
                "tesouraria": 10_000,
                "qt_acao_ordinaria": 3_000_000,
                "qt_acao_preferencial": 2_000_000,
            },
            TIM: {
                "versao": 1,
                "dt_refer": date(2025, 12, 31),
                "total": 1_000,
                "tesouraria": 10,
                "qt_acao_ordinaria": 900,
                "qt_acao_preferencial": 100,
            },
        }
        fonte._capital_do_fre = lambda *_: {  # type: ignore[method-assign]
            WEG: {
                "versao": 1,
                "total": 5_000_000_000,
                "qt_acao_ordinaria": 3_100_000_000,
                "qt_acao_preferencial": 1_900_000_000,
            },
            TIM: {
                "versao": 1,
                "total": 1_000_000,
                "qt_acao_ordinaria": 1_000_000,
            },
        }

        capitais = fonte.composicoes_de_capital(2025, {WEG, TIM})

        assert capitais[WEG].qt_acao_ordinaria == 3_100_000_000
        assert capitais[WEG].qt_acao_preferencial == 1_900_000_000
        assert capitais[WEG].acoes_ex_tesouraria == 4_990_000_000
        assert capitais[TIM].qt_acao_ordinaria == 1_000_000
        assert capitais[TIM].qt_acao_preferencial == 100_000

    def test_zero_explicito_no_fre_nao_herda_valor_do_dfp(self):
        fonte = FonteCvm(None, None, None, logging.getLogger("teste"))  # type: ignore[arg-type]
        fonte._composicao_do_dfp = lambda *_: {  # type: ignore[method-assign]
            WEG: {
                "versao": 1,
                "dt_refer": date(2025, 12, 31),
                "total": 100,
                "tesouraria": 0,
                "qt_acao_ordinaria": 100,
                "qt_acao_preferencial": 10,
            }
        }
        fonte._capital_do_fre = lambda *_: {  # type: ignore[method-assign]
            WEG: {
                "versao": 1,
                "total": 100,
                "qt_acao_ordinaria": 100,
                "qt_acao_preferencial": 0,
            }
        }

        capital = fonte.composicoes_de_capital(2025, {WEG})[WEG]

        assert capital.qt_acao_ordinaria == 100
        assert capital.qt_acao_preferencial == 0

    def test_fre_sem_dfp_preserva_o_breakdown_on_pn(self):
        fonte = FonteCvm(None, None, None, logging.getLogger("teste"))  # type: ignore[arg-type]
        fonte._composicao_do_dfp = lambda *_: {}  # type: ignore[method-assign]
        fonte._capital_do_fre = lambda *_: {  # type: ignore[method-assign]
            WEG: {
                "versao": 1,
                "total": 120,
                "qt_acao_ordinaria": 80,
                "qt_acao_preferencial": 40,
            }
        }

        capital = fonte.composicoes_de_capital(2025, {WEG})[WEG]

        assert capital.fonte == "FRE_SEM_TESOURARIA"
        assert capital.acoes_ex_tesouraria == 120
        assert capital.qt_acao_ordinaria == 80
        assert capital.qt_acao_preferencial == 40
