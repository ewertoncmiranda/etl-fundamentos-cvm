import json
import urllib.error
from datetime import date
from decimal import Decimal
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from app.adaptadores.bcb.ifdata import ClienteIfData, montar_indicadores
from app.adaptadores.cvm.cache_local import CacheDeArquivos
from app.adaptadores.cvm.cliente_http import Assinatura
from app.excecoes.excecoes import FonteIndisponivel, PacoteInvalido


def _cad(cnpj='00.000.000/0001-91', codigo='C1', periodo='202606'):
    return {'CodInst': codigo, 'Data': periodo, 'CnpjInstituicaoLider': cnpj,
            'CodConglomeradoPrudencial': codigo, 'CodConglomeradoFinanceiro': codigo}


def _valor(nome, saldo, periodo='202606', codigo='C1', tipo=1):
    return {'CodInst': codigo, 'AnoMes': periodo, 'TipoInstituicao': tipo,
            'NomeColuna': nome, 'Saldo': saldo, 'NumeroRelatorio': '1'}


def test_mapeia_rotulos_reais_sem_confundir_basileia_ampla_e_capital_monetario():
    valores = [_valor('Índice de Basileia \n(n) = (e) / (j)', '0.15'),
               _valor('Índice de Basileia Amplo \n(o)', '0.99'),
               _valor('Índice de Capital Principal \n(l) = (a) / (j)', '0.12'),
               _valor('Capital Principal para Comparação com RWA \n(a)', '100000'),
               _valor('Ativo Total', '1000.123456789'),
               _valor('Patrimônio Líquido', '200'),
               _valor('Carteira de Crédito', '800'), _valor('Inadimplência', '0.03')]
    item = montar_indicadores([_cad()], valores, 202606)[('00000000000191', date(2026, 6, 30))]
    assert item.basileia == Decimal('0.15')
    assert item.capital_principal == Decimal('100000')
    assert item.indice_capital_principal == Decimal('0.12')
    assert item.ativo_total == Decimal('1000.123456789')
    assert item.patrimonio_liquido == Decimal('200')
    assert item.carteira_credito == Decimal('800')
    assert item.inadimplencia == Decimal('0.03')
    assert item.roe is None
    assert item.ausentes == ('roe',)


def test_join_preserva_raiz_cnpj_e_escopo_e_nao_trata_conglomerado_como_cnpj():
    valores = [_valor('Ativo Total', '100'), _valor('Ativo Total', '900', tipo=2),
               _valor('Ativo Total', '400', codigo='outra')]
    resultado = montar_indicadores([_cad('12345678')], valores, 202606)
    assert resultado[('12345678', date(2026, 6, 30))].ativo_total == Decimal(100)
    assert montar_indicadores([_cad('', codigo='C1')], valores, 202606) == {}
    assert montar_indicadores([_cad(periodo='202603')], valores, 202606) == {}
    individual = montar_indicadores([_cad('', codigo='1234567')],
                                   [_valor('Ativo Total', '10', codigo='1234567', tipo=3)],
                                   202606, 3)
    assert ('01234567', date(2026, 6, 30)) in individual


@pytest.mark.parametrize('periodo', [202601, 202613, 202600])
def test_rejeita_data_nao_trimestral(periodo):
    with pytest.raises(ValueError, match='trimestral'):
        montar_indicadores([], [], periodo)


def test_roe_ttm_de_junho_usa_dois_semestres_e_pl_medio():
    valores = [_valor('Lucro Líquido', '12'), _valor('Patrimônio Líquido', '120'),
               _valor('Lucro Líquido', '8', '202512'),
               _valor('Patrimônio Líquido', '80', '202506')]
    item = next(iter(montar_indicadores([_cad()], valores, 202606).values()))
    assert item.roe == Decimal('0.2')


@pytest.mark.parametrize('periodo,sem1,sem2,homologo', [
    ('202609', '202606', '202512', '202509'),
    ('202603', '202512', '202506', '202503'),
])
def test_roe_ttm_marco_setembro_subtrai_acumulado_homologo(periodo, sem1, sem2, homologo):
    valores = [_valor('Lucro Líquido', '6', periodo),
               _valor('Patrimônio Líquido', '120', periodo),
               _valor('Lucro Líquido', '12', sem1), _valor('Lucro Líquido', '8', sem2),
               _valor('Lucro Líquido', '4', homologo),
               _valor('Patrimônio Líquido', '80', homologo)]
    item = next(iter(montar_indicadores([_cad(periodo=periodo)], valores, int(periodo)).values()))
    assert item.roe == Decimal('0.22')


def test_rejeita_conflito_de_saldo_cnpj_e_saldo_nao_finito():
    with pytest.raises(PacoteInvalido, match='ambiguo'):
        montar_indicadores([_cad()], [_valor('Ativo Total', '1'),
                                    _valor('Ativo Total', '2')], 202606)
    with pytest.raises(PacoteInvalido, match='univoco'):
        montar_indicadores([_cad(), _cad('11111111')], [], 202606)
    with pytest.raises(PacoteInvalido, match='nao finito'):
        montar_indicadores([_cad()], [_valor('Ativo Total', 'NaN')], 202606)
    item = next(iter(montar_indicadores([_cad()], [_valor('Ativo Total', None)], 202606).values()))
    assert item.ativo_total is None


def _cliente(tmp_path, baixar, tamanho=10000):
    http = Mock()
    http.assinatura.return_value = Assinatura('v1', None, None)
    http.baixar.side_effect = baixar
    return ClienteIfData(http, CacheDeArquivos(tmp_path), tamanho), http


def test_cliente_relatorios_paginacao_skip_etag_e_republicacao(tmp_path):
    linhas = [{'NumeroRelatorio': '1', 'NomeRelatorio': 'Resumo'},
              {'NumeroRelatorio': '5', 'NomeRelatorio': 'Informações de Capital'}]

    def baixar(caminho):
        inicio = int(parse_qs(urlsplit(caminho).query).get('$skip', ['0'])[0])
        return json.dumps({'value': linhas[inicio:inicio + 1]}).encode()

    cliente, http = _cliente(tmp_path, baixar, tamanho=1)
    assert cliente.relatorios() == {'1': 'Resumo', '5': 'Informações de Capital'}
    assert cliente.relatorios()['1'] == 'Resumo'
    assert http.baixar.call_count == 3
    http.assinatura.return_value = Assinatura('v2', None, None)
    cliente.relatorios()
    assert http.baixar.call_count == 6


def test_cliente_ler_busca_cadastro_capital_e_historico_sem_ticker(tmp_path):
    caminhos = []

    def baixar(caminho):
        caminhos.append(caminho)
        if caminho.startswith('IfDataCadastro'):
            linhas = [_cad()]
        elif 'AnoMes=202606' in caminho and "Relatorio='5'" in caminho:
            linhas = [_valor('Índice de Capital Principal', '0.1')]
        elif 'AnoMes=202606' in caminho:
            linhas = [_valor('Ativo Total', '1000'), _valor('Lucro Líquido', '12'),
                      _valor('Patrimônio Líquido', '120')]
        elif 'AnoMes=202512' in caminho:
            linhas = [_valor('Lucro Líquido', '8', '202512')]
        else:
            linhas = [_valor('Patrimônio Líquido', '80', '202506')]
        return json.dumps({'value': linhas}).encode()

    cliente, _ = _cliente(tmp_path, baixar)
    item = next(iter(cliente.ler(202606).values()))
    assert item.indice_capital_principal == Decimal('0.1')
    assert item.roe == Decimal('0.2')
    assert len(caminhos) == 5


def test_nextlink_valida_origem_e_ciclo(tmp_path):
    cliente, _ = _cliente(tmp_path, lambda _: json.dumps({
        'value': [], '@odata.nextLink': 'https://fora.exemplo/dados',
    }).encode())
    with pytest.raises(PacoteInvalido, match='fora do servico'):
        cliente.relatorios()


def test_nextlink_seguido_e_conteudo_repetido_rejeitado(tmp_path):
    paginas = iter([
        {'value': [{'NumeroRelatorio': '1', 'NomeRelatorio': 'Resumo'}],
         '@odata.nextLink': 'ListaDeRelatorio()?pagina=2'},
        {'value': [{'NumeroRelatorio': '5', 'NomeRelatorio': 'Informações de Capital'}]},
    ])
    cliente, _ = _cliente(tmp_path, lambda _: json.dumps(next(paginas)).encode())
    assert len(cliente.relatorios()) == 2
    cliente, _ = _cliente(tmp_path / 'ciclo', lambda _: b'{"value": [{"NumeroRelatorio": "1"}]}',
                         tamanho=1)
    with pytest.raises(PacoteInvalido, match='repetiu conteudo'):
        cliente.relatorios()


def test_roe_dezembro_e_pl_nao_positivo(tmp_path):
    valores = [_valor('Lucro Líquido', '10', '202512'),
               _valor('Patrimônio Líquido', '100', '202512'),
               _valor('Lucro Líquido', '10', '202506'),
               _valor('Patrimônio Líquido', '100', '202412')]
    item = next(iter(montar_indicadores([_cad(periodo='202512')], valores, 202512).values()))
    assert item.roe == Decimal('0.2')
    valores[1]['Saldo'] = '-100'
    assert next(iter(montar_indicadores([_cad(periodo='202512')], valores, 202512)
                     .values())).roe is None


def test_head_nao_suportado_baixa_mas_erro_de_rede_nao_vira_vazio(tmp_path):
    cliente, http = _cliente(tmp_path, lambda _: b'{"value": []}')
    erro = FonteIndisponivel('HEAD 405')
    erro.__cause__ = urllib.error.HTTPError('https://exemplo', 405, 'HEAD', {}, None)
    http.assinatura.side_effect = erro
    assert cliente.relatorios() == {}
    http.assinatura.side_effect = FonteIndisponivel('rede indisponivel')
    with pytest.raises(FonteIndisponivel):
        cliente.relatorios()
