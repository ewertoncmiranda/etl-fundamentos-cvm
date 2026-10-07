"""Escolha entre consolidado e individual no DFP."""

from __future__ import annotations

import logging

from app.adaptadores.cvm.fonte_cvm import FonteCvm
from app.dominio.modelo import DRE, GRUPO_CONSOLIDADO, GRUPO_INDIVIDUAL
from tests.conftest import PERIODO, linha

TIM = "02.421.421/0001-11"
WEG = "84.429.695/0001-11"


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
