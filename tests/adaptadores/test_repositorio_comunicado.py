"""Regra de 'o que gravar' do repositorio de comunicados, sem banco."""

from __future__ import annotations

from datetime import date

from app.adaptadores.persistencia.repositorios import selecionar_para_gravar
from app.dominio.comunicado import FATO_RELEVANTE, Comunicado


def comunicado(protocolo: str, versao: int = 1) -> Comunicado:
    return Comunicado(
        protocolo_cvm=protocolo,
        versao=versao,
        cnpj="33.000.167/0001-01",
        categoria=FATO_RELEVANTE,
        categoria_original="Fato Relevante",
        data_entrega=date(2026, 9, 19),
        link_download=f"https://x/?numProtocolo={protocolo}",
    )


class TestSelecionarParaGravar:

    def test_protocolo_desconhecido_e_novo(self):
        assert selecionar_para_gravar([comunicado("1")], {}) == [comunicado("1")]

    def test_mesma_versao_ja_gravada_nao_e_novidade(self):
        """E o que torna a carga idempotente e o evento fiel ao que mudou."""
        assert selecionar_para_gravar([comunicado("1")], {"1": 1}) == []

    def test_reapresentacao_e_gravada(self):
        assert selecionar_para_gravar([comunicado("1", 2)], {"1": 1}) == [comunicado("1", 2)]

    def test_versao_mais_antiga_que_a_gravada_e_ignorada(self):
        assert selecionar_para_gravar([comunicado("1", 1)], {"1": 3}) == []
