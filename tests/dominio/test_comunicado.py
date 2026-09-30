"""Regras puras dos comunicados: categoria, identidade e versao."""

from __future__ import annotations

from datetime import date

from app.dominio.comunicado import (
    ASSEMBLEIA,
    CATEGORIAS_PADRAO,
    FATO_RELEVANTE,
    OUTROS,
    PROVENTOS,
    RESULTADOS,
    Comunicado,
    classificar_categoria,
    data_referencia_plausivel,
    extrair_protocolo,
    versao_mais_recente,
)

LINK_PETROBRAS = (
    "https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?Tela=ext&descTipo=IPE"
    "&CodigoInstituicao=1&numProtocolo=1569745&numSequencia=1094451&numVersao=1"
)


def comunicado(protocolo: str = "1", versao: int = 1, **outros) -> Comunicado:
    base = dict(
        protocolo_cvm=protocolo,
        versao=versao,
        cnpj="33.000.167/0001-01",
        categoria=FATO_RELEVANTE,
        categoria_original="Fato Relevante",
        data_entrega=date(2026, 9, 19),
        link_download=LINK_PETROBRAS,
    )
    base.update(outros)
    return Comunicado(**base)


class TestClassificarCategoria:

    def test_categorias_com_acento_casam_normalizadas(self):
        """O CSV vem em latin-1; o mapa compara sem acento e sem caixa."""
        assert classificar_categoria("Relatório Proventos") == PROVENTOS
        assert classificar_categoria("Dados Econômico-Financeiros") == RESULTADOS
        assert classificar_categoria("  FATO RELEVANTE ") == FATO_RELEVANTE

    def test_categoria_desconhecida_vira_outros(self):
        assert classificar_categoria("Regimento Interno da Diretoria") == OUTROS
        assert classificar_categoria(None) == OUTROS

    def test_assembleia_existe_mas_fica_fora_do_padrao(self):
        assert classificar_categoria("Assembleia") == ASSEMBLEIA
        assert ASSEMBLEIA not in CATEGORIAS_PADRAO


class TestExtrairProtocolo:

    def test_le_num_protocolo_do_link(self):
        assert extrair_protocolo(LINK_PETROBRAS) == "1569745"

    def test_nao_confunde_com_outros_parametros(self):
        """numSequencia e numVersao tambem sao numeros no mesmo link."""
        link = "https://x/?numSequencia=9&numVersao=2&numProtocolo=77"
        assert extrair_protocolo(link) == "77"

    def test_link_ausente_ou_sem_protocolo(self):
        assert extrair_protocolo(None) is None
        assert extrair_protocolo("https://www.rad.cvm.gov.br/ENET/") is None


class TestVersaoMaisRecente:

    def test_reapresentacao_substitui_a_versao_anterior(self):
        resultado = versao_mais_recente(
            [comunicado("10", 1, assunto="v1"), comunicado("10", 2, assunto="v2")]
        )
        assert [c.assunto for c in resultado] == ["v2"]

    def test_versao_antiga_chegando_depois_nao_sobrescreve(self):
        resultado = versao_mais_recente(
            [comunicado("10", 3, assunto="v3"), comunicado("10", 2, assunto="v2")]
        )
        assert [c.versao for c in resultado] == [3]

    def test_linhas_identicas_repetidas_viram_uma(self):
        """A propria CVM repete 122 linhas no arquivo de 2026."""
        assert len(versao_mais_recente([comunicado("10"), comunicado("10")])) == 1

    def test_protocolos_diferentes_convivem(self):
        assert len(versao_mais_recente([comunicado("10"), comunicado("11")])) == 2


class TestDataReferenciaPlausivel:

    def test_mantem_data_normal_e_evento_anunciado_com_antecedencia(self):
        entrega = date(2026, 9, 1)
        assert data_referencia_plausivel(date(2026, 8, 15), entrega) == date(2026, 8, 15)
        assert data_referencia_plausivel(date(2027, 3, 1), entrega) == date(2027, 3, 1)

    def test_descarta_digitacao_errada(self):
        # Visto no IPE: 2925-11-06.
        assert data_referencia_plausivel(date(2925, 11, 6), date(2025, 11, 6)) is None
        assert data_referencia_plausivel(date(1900, 1, 1), date(2025, 11, 6)) is None

    def test_ausente_continua_ausente(self):
        assert data_referencia_plausivel(None, date(2026, 9, 1)) is None
