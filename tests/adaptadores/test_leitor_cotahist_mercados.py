import io
import zipfile
from decimal import Decimal

import pytest

from app.adaptadores.b3.leitor_cotahist import LeitorCotahist
from tests.adaptadores.test_leitor_cotahist import _com, _linha_cotahist


@pytest.mark.parametrize('mercado', ['012', '013', '017', '020', '030'])
def test_mercados_campos_e_escalas_independentes(mercado):
    linha = _linha_cotahist('PETR4F', mercado=mercado)
    for inicio, fim, valor in [(49, 52, '030'), (95, 108, '4800'),
                               (121, 134, '4798'), (134, 147, '4802'),
                               (188, 201, '3200'), (201, 202, '1'),
                               (210, 217, '1000'), (217, 230, '123456789'),
                               (242, 245, '007')]:
        linha = _com(linha, inicio, fim, valor)
    linha = _com(linha, 230, 242, 'BRPETRACNPR6', True)
    (item,) = LeitorCotahist().ler_mercados_linhas([linha])
    assert item.mercado == mercado
    assert item.prazo_termo == 30
    assert item.indice_correcao == '1'
    assert item.numero_distribuicao == 7
    assert item.preco_exercicio == Decimal('32')
    assert item.preco_exercicio_pontos == Decimal('123.456789')
    assert item.preco_medio == Decimal('0.048')
    assert item.melhor_oferta_compra == Decimal('0.04798')
    assert item.melhor_oferta_venda == Decimal('0.04802')
    assert item.volume_financeiro == Decimal('1660839773')
    assert item.volume == 34440400


def test_isin_tem_prioridade_e_independe_da_ordem_do_arquivo():
    vista = _com(_linha_cotahist('BASE3'), 230, 242, 'BRBASEACNOR1', True)
    fracao = _com(_linha_cotahist('OUTRO4F', '020'), 230, 242, 'BRBASEACNOR1', True)
    leitor = LeitorCotahist()
    assert leitor.ler_mercados_linhas([fracao, vista])[0].simbolo_base == 'BASE3'
    mapeado = leitor.ler_mercados_linhas([fracao], {'BRBASEACNOR1': 'MAPA3'})
    assert mapeado[0].simbolo_base == 'MAPA3'
    # Uma cotação antiga com o mesmo ISIN não prova o ticker atual.
    vista_antiga = _com(vista, 2, 10, '20200101')
    assert leitor.ler_mercados_linhas([fracao, vista_antiga])[0].simbolo_base == 'OUTRO4'


@pytest.mark.parametrize('simbolo,mercado,base', [
    ('PETR4F', '020', 'PETR4'), ('PETR4T', '030', 'PETR4'),
    ('PETR4', '017', None), ('PETRA32', '012', None), ('PETR4F', '030', None),
])
def test_fallback_limitado_e_ausencias(simbolo, mercado, base):
    (item,) = LeitorCotahist().ler_mercados_linhas([_linha_cotahist(simbolo, mercado)])
    assert item.simbolo_base == base
    assert item.prazo_termo is None
    assert item.preco_exercicio_pontos is None
    assert item.melhor_oferta_compra is None
    assert item.preco_medio is None


def test_zip_e_filtro_preservam_leitores_anteriores():
    linhas = [_linha_cotahist(), _linha_cotahist('PETR4F', '020'),
              _linha_cotahist('PETRA32', '070')]
    leitor = LeitorCotahist()
    assert len(leitor.ler_linhas(linhas)) == 1
    assert len(leitor.ler_opcoes_linhas(linhas)) == 1
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, 'w') as pacote:
            pacote.writestr('COTAHIST.TXT', '\n'.join(linhas).encode('latin-1'))
        assert leitor.ler_mercados_zip(buffer.getvalue()) == leitor.ler_mercados_linhas(linhas)
    with pytest.raises(ValueError, match='245'):
        leitor.ler_mercados_linhas([linhas[1][:-1]])
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, 'w') as pacote:
            pacote.writestr('outro.csv', '')
        with pytest.raises(ValueError, match='um TXT'):
            leitor.ler_mercados_zip(buffer.getvalue())
