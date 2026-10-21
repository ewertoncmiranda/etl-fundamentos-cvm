from dataclasses import replace
from datetime import date
from unittest.mock import Mock

import pytest

from app.adaptadores.cvm.cache_local import CacheDeArquivos
from app.adaptadores.cvm.cadastro import (
    CadastroCvm,
    LeitorCadastroCvm,
    ler_cadastro,
    troca_auditor_recente,
)
from app.adaptadores.cvm.cliente_http import Assinatura
from app.excecoes.excecoes import PacoteInvalido

CSV = (
    'CNPJ_CIA;SIT;DT_INI_SIT;SETOR_ATIV;CNPJ_AUDITOR;AUDITOR;DT_INI_RESP\r\n'
    '00.000.000/0001-91;ATIVO;2020-01-02;Bancos;11.111.111/0001-11;'
    '"Auditoria; Açores";2026-01-01\r\n'
).encode('latin-1')


def test_cabecalho_real_latin1_cnpj_e_data_do_responsavel_nao_e_do_auditor():
    item = ler_cadastro(CSV)['00000000000191']
    assert item.situacao == 'ATIVO'
    assert item.data_situacao == date(2020, 1, 2)
    assert item.setor == 'Bancos'
    assert item.auditor == 'Auditoria; Açores'
    assert item.cnpj_auditor == '11111111000111'
    assert item.data_inicio_auditor is None


def test_ausentes_nao_viram_datas_ou_auditores_inventados():
    csv = b'CNPJ_CIA;SIT;DT_INI_SIT;SETOR_ATIV;CNPJ_AUDITOR;AUDITOR\n00000000000191;;;;;\n'
    item = ler_cadastro(csv)['00000000000191']
    assert item == CadastroCvm('00000000000191', None, None, None, None, None)
    with pytest.raises(PacoteInvalido):
        ler_cadastro(b'CNPJ_CIA;SIT\n')


def test_troca_recente_exige_evidencia_e_nao_confunde_primeiro_registro():
    anterior = ler_cadastro(CSV)['00000000000191']
    atual = replace(anterior, auditor='Outra', cnpj_auditor='22222222000122')
    hoje = date(2026, 10, 20)
    assert troca_auditor_recente(atual, anterior, hoje) is None
    assert troca_auditor_recente(atual, None, hoje) is None
    assert troca_auditor_recente(atual, anterior, hoje,
                                data_snapshot_anterior=date(2026, 1, 1)) is True
    assert troca_auditor_recente(atual, anterior, hoje,
                                data_snapshot_anterior=date(2020, 1, 1)) is None
    assert troca_auditor_recente(anterior, anterior, hoje) is False
    assert troca_auditor_recente(replace(anterior, cnpj_auditor=None), anterior, hoje) is False
    assert troca_auditor_recente(replace(atual, data_inicio_auditor=date(2020, 1, 1)),
                                anterior, hoje) is False
    assert troca_auditor_recente(replace(atual, data_inicio_auditor=hoje),
                                anterior, hoje) is True
    with pytest.raises(ValueError):
        troca_auditor_recente(replace(atual, cnpj='outro'), anterior, hoje)


def test_head_etag_reutiliza_cache_e_republicacao_baixa(tmp_path):
    cliente = Mock()
    cliente.assinatura.return_value = Assinatura('v1', None, None)
    cliente.baixar.return_value = CSV
    leitor = LeitorCadastroCvm(cliente, CacheDeArquivos(tmp_path))
    assert leitor.ler() == leitor.ler()
    assert cliente.assinatura.call_count == 2
    assert cliente.baixar.call_count == 1
    cliente.assinatura.return_value = Assinatura('v2', None, None)
    leitor.ler()
    assert cliente.baixar.call_count == 2
    cliente.assinatura.return_value = Assinatura(None, None, None)
    leitor.ler()
    assert cliente.baixar.call_count == 3
