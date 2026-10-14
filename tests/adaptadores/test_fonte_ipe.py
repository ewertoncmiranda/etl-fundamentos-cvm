"""Leitura do CSV da base IPE, com um ZIP montado em memoria.

As linhas imitam o arquivo real de 2026 - inclusive o que ele tem de
estranho: latin-1, Protocolo_Entrega vazio em relatorio de proventos, linha
repetida e reapresentacao.
"""

from __future__ import annotations

import io
import logging
import zipfile
from datetime import date

import pytest

from app.adaptadores.cvm.fonte_ipe import FonteIpe, ler_comunicados
from app.adaptadores.cvm.leitor_pacote import LeitorDePacoteCvm
from app.dominio.comunicado import CATEGORIAS_PADRAO, FATO_RELEVANTE, PROVENTOS
from app.excecoes.excecoes import PacoteInvalido

CNPJ_PETROBRAS = "33.000.167/0001-01"
CNPJ_OUTRA = "11.111.111/0001-11"
CABECALHO = (
    "CNPJ_Companhia;Nome_Companhia;Codigo_CVM;Data_Referencia;Categoria;Tipo;Especie;"
    "Assunto;Data_Entrega;Tipo_Apresentacao;Protocolo_Entrega;Versao;Link_Download"
)


def link(protocolo: int, versao: int = 1) -> str:
    return (
        "https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?Tela=ext&descTipo=IPE"
        f"&CodigoInstituicao=1&numProtocolo={protocolo}&numSequencia={protocolo + 7}"
        f"&numVersao={versao}"
    )


def linha_csv(
    categoria="Fato Relevante",
    cnpj=CNPJ_PETROBRAS,
    assunto="Petrobras informa sobre adesão à nova subvenção econômica",
    protocolo=1569745,
    versao=1,
    protocolo_entrega="009512IPE190920260106790786-74",
    data_entrega="2026-09-19",
) -> str:
    return ";".join(
        [
            cnpj, "PETROLEO BRASILEIRO S.A. PETROBRAS", "9512", "2026-09-19",
            categoria, "", "", assunto, data_entrega, "AP - Apresentação",
            protocolo_entrega, str(versao), link(protocolo, versao),
        ]
    )


def zip_ipe(linhas: list[str], cabecalho: str = CABECALHO, ano: int = 2026) -> bytes:
    conteudo = "\r\n".join([cabecalho, *linhas]) + "\r\n"
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w") as arquivo:
        arquivo.writestr(f"ipe_cia_aberta_{ano}.csv", conteudo.encode("latin-1"))
    return saida.getvalue()


def ler(linhas: list[str], categorias=CATEGORIAS_PADRAO, cabecalho: str = CABECALHO):
    return ler_comunicados(
        LeitorDePacoteCvm(zip_ipe(linhas, cabecalho)),
        "ipe_cia_aberta_2026.csv",
        {CNPJ_PETROBRAS},
        set(categorias),
        logging.getLogger("teste"),
    )


class TestLerComunicados:

    def test_linha_real_vira_comunicado_completo(self):
        [comunicado] = ler([linha_csv()])

        assert comunicado.protocolo_cvm == "1569745"
        assert comunicado.categoria == FATO_RELEVANTE
        assert comunicado.categoria_original == "Fato Relevante"
        assert comunicado.assunto == "Petrobras informa sobre adesão à nova subvenção econômica"
        assert comunicado.data_entrega == date(2026, 9, 19)
        assert comunicado.codigo_cvm == "9512"
        assert comunicado.link_download.endswith("numVersao=1")

    def test_acentos_latin1_sobrevivem(self):
        [comunicado] = ler([linha_csv(categoria="Relatório Proventos")])

        assert comunicado.categoria == PROVENTOS
        assert comunicado.categoria_original == "Relatório Proventos"

    def test_filtra_cnpj_fora_do_universo(self):
        assert ler([linha_csv(cnpj=CNPJ_OUTRA)]) == []

    def test_filtra_categoria_fora_do_pedido(self):
        """Assembleia e regimento interno nao entram por padrao."""
        linhas = [
            linha_csv(categoria="Assembleia", protocolo=1),
            linha_csv(categoria="Regimento Interno da Diretoria", protocolo=2),
        ]
        assert ler(linhas) == []

    def test_protocolo_entrega_vazio_nao_impede_a_carga(self):
        """Relatorio de proventos automatico: 501 linhas assim em 2026."""
        [comunicado] = ler(
            [linha_csv(categoria="Relatório Proventos", protocolo_entrega="", assunto="")]
        )

        assert comunicado.protocolo_cvm == "1569745"
        assert comunicado.protocolo_entrega is None
        assert comunicado.assunto is None

    def test_linha_repetida_e_reapresentacao_viram_um_documento(self):
        linhas = [
            linha_csv(protocolo=50, versao=1, assunto="v1"),
            linha_csv(protocolo=50, versao=1, assunto="v1"),
            linha_csv(protocolo=50, versao=2, assunto="v2"),
        ]
        [comunicado] = ler(linhas)

        assert (comunicado.versao, comunicado.assunto) == (2, "v2")

    def test_linha_sem_data_de_entrega_e_ignorada(self):
        assert ler([linha_csv(data_entrega="")]) == []

    def test_layout_novo_sem_coluna_obrigatoria_falha_explicito(self):
        cabecalho = CABECALHO.replace("Link_Download", "Link")
        with pytest.raises(PacoteInvalido, match="Link_Download"):
            ler([linha_csv()], cabecalho=cabecalho)


class _ClienteFake:
    def __init__(self, conteudo: bytes):
        self._conteudo = conteudo
        self.baixados: list[str] = []

    def assinatura(self, caminho):
        raise AssertionError("nao usado")

    def baixar(self, caminho):
        self.baixados.append(caminho)
        return self._conteudo


class _CacheFake:
    def __init__(self):
        self.gravados: dict[str, bytes] = {}

    def gravar(self, nome, conteudo):
        self.gravados[nome] = conteudo


class TestFonteIpe:

    def test_baixa_o_arquivo_do_ano_e_guarda_copia(self):
        cliente = _ClienteFake(zip_ipe([linha_csv()]))
        cache = _CacheFake()
        fonte = FonteIpe(cliente, cache, logging.getLogger("teste"))

        comunicados = fonte.comunicados(2026, {CNPJ_PETROBRAS}, CATEGORIAS_PADRAO)

        assert cliente.baixados == ["IPE/DADOS/ipe_cia_aberta_2026.zip"]
        assert "ipe_cia_aberta_2026.zip" in cache.gravados
        assert len(comunicados) == 1

    def test_sem_cnpj_nao_baixa_nada(self):
        cliente = _ClienteFake(b"")
        fonte = FonteIpe(cliente, _CacheFake(), logging.getLogger("teste"))

        assert fonte.comunicados(2026, set(), CATEGORIAS_PADRAO) == []
        assert cliente.baixados == []
