from datetime import date
from decimal import Decimal

from app.adaptadores.tesouro.fonte_tesouro import ARQUIVO, FonteTesouro
from app.adaptadores.tesouro.leitor_tesouro import ler_csv, ntnb_referencia

CABECALHO = (
    "Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;"
    "PU Compra Manha;PU Venda Manha;PU Base Manha\n"
)


def _csv(*linhas: str) -> bytes:
    return (CABECALHO + "\n".join(linhas) + "\n").encode("latin-1")


AMOSTRA = _csv(
    "Tesouro Selic;01/03/2027;15/10/2026;0,01;0,02;20097,80;20086,80;20086,80",
    "Tesouro IPCA+;15/05/2029;15/10/2026;7,40;7,52;3.512,10;3.500,00;3.500,00",
    "Tesouro IPCA+ com Juros Semestrais;15/08/2032;15/10/2026;7,10;7,22;4.300,55;4.290,00;4.290,00",
    "Tesouro IPCA+;15/05/2045;15/10/2026;6,80;6,92;1.200,00;1.190,00;1.190,00",
    "Tesouro IPCA+;15/05/2029;14/10/2026;7,35;7,47;3.515,00;3.503,00;3.503,00",
    "Tesouro IPCA+;15/05/2035;13/10/2026;;;;;",
)


def test_le_decimais_com_virgula_milhar_com_ponto_e_datas_brasileiras():
    taxas = ler_csv(AMOSTRA)
    assert len(taxas) == 6
    ntnb = taxas[1]
    assert ntnb.tipo == "Tesouro IPCA+"
    assert ntnb.vencimento == date(2029, 5, 15)
    assert ntnb.data_base == date(2026, 10, 15)
    assert ntnb.taxa_compra == Decimal("7.40")
    assert ntnb.pu_compra == Decimal("3512.10")
    assert ntnb.juro_real and not taxas[0].juro_real
    vazia = taxas[5]
    assert vazia.taxa_compra is None and vazia.pu_base is None


def test_linha_quebrada_e_corte_por_data_ficam_de_fora():
    conteudo = _csv(
        "Tesouro IPCA+;data ruim;15/10/2026;7,40;7,52;1;1;1",
        ";15/05/2029;15/10/2026;7,40;7,52;1;1;1",
        "Tesouro IPCA+;15/05/2029;15/10/2015;5,00;5,10;1;1;1",
        "Tesouro IPCA+;15/05/2029;15/10/2026;7,40;7,52;1;1;1",
    )
    assert len(ler_csv(conteudo)) == 2
    assert [t.data_base for t in ler_csv(conteudo, desde=date(2020, 1, 1))] == [date(2026, 10, 15)]


def test_referencia_e_a_ntnb_mais_perto_de_5_anos_na_data_mais_recente():
    referencia = ntnb_referencia(ler_csv(AMOSTRA))
    # alvo 15/10/2031: 2032-08 (~10 meses) ganha de 2029-05 (~2,4 anos) e 2045.
    assert referencia.vencimento == date(2032, 8, 15)
    assert referencia.taxa_compra == Decimal("7.10")


def test_referencia_em_data_especifica_e_sem_ntnb_com_taxa():
    taxas = ler_csv(AMOSTRA)
    assert ntnb_referencia(taxas, date(2026, 10, 14)).taxa_compra == Decimal("7.35")
    assert ntnb_referencia(taxas, date(2026, 10, 13)) is None
    assert ntnb_referencia(ler_csv(_csv("Tesouro Selic;01/03/2027;15/10/2026;0,01;0,02;1;1;1"))) is None


class _ClienteFalso:
    def __init__(self):
        self.baixados = 0

    def baixar(self, caminho):
        assert caminho == ARQUIVO
        self.baixados += 1
        return AMOSTRA


def test_fonte_baixa_grava_cache_e_reusa_quando_pedido(tmp_path):
    from app.adaptadores.cvm.cache_local import CacheDeArquivos

    cliente, cache = _ClienteFalso(), CacheDeArquivos(tmp_path)
    fonte = FonteTesouro(cliente, cache)
    assert len(fonte.taxas()) == 6
    assert cache.tem(ARQUIVO)
    assert len(fonte.taxas(usar_cache=True)) == 6
    assert cliente.baixados == 1
