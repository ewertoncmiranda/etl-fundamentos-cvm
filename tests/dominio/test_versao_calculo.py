"""ETag com a versao do calculo: arquivo igual so e pulado se ja foi processado pelo calculo atual."""

from __future__ import annotations

from app.dominio.versao_calculo import VERSOES_CALCULO, arquivo_inalterado, etag_com_versao


def test_fonte_com_calculo_grava_etag_com_a_versao():
    assert etag_com_versao("CVM_DFP", "abc") == f"abc#calc{VERSOES_CALCULO['CVM_DFP']}"
    assert etag_com_versao("CVM_TTM", "abc") == f"abc#calc{VERSOES_CALCULO['CVM_TTM']}"


def test_fonte_sem_calculo_e_etag_vazio_ficam_como_estao():
    assert etag_com_versao("CVM_IPE", "abc") == "abc"
    assert etag_com_versao("CVM_DFP", None) is None
    assert etag_com_versao("CVM_DFP", "") == ""


def test_so_pula_mesmo_arquivo_processado_pela_versao_atual():
    atual = etag_com_versao("CVM_DFP", "abc")
    assert arquivo_inalterado("CVM_DFP", "abc", atual)
    assert not arquivo_inalterado("CVM_DFP", "abc", "abc"), "ETag cru = versao antiga do calculo"
    assert not arquivo_inalterado("CVM_DFP", "abc", "abc#calc1")
    assert not arquivo_inalterado("CVM_DFP", "xyz", atual), "arquivo mudou na origem"
    assert not arquivo_inalterado("CVM_DFP", None, atual), "sem ETag nunca e inalterado"
    assert not arquivo_inalterado("CVM_DFP", "abc", None)
