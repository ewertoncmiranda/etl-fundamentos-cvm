"""FCA geral e enderecos: situacao do registro e UF da sede (REQ-13)."""

from __future__ import annotations

import logging

from app.adaptadores.cvm.fonte_cvm import FonteCvm

ATIVA = "11.111.111/0001-11"
CANCELADA = "22.222.222/0001-22"
SEDE = "Endereço da Sede"

GERAL = [
    {"CNPJ_Companhia": ATIVA, "Nome_Empresarial": "ATIVA SA", "Codigo_CVM": "1",
     "Setor_Atividade": "Bancos", "Situacao_Registro_CVM": "Ativo",
     "Data_Constituicao": "1990-05-04"},
    {"CNPJ_Companhia": CANCELADA, "Nome_Empresarial": "CANCELADA SA", "Codigo_CVM": "2",
     "Setor_Atividade": "", "Situacao_Registro_CVM": "Cancelado",
     "Data_Constituicao": "nao-e-data"},
]
ENDERECOS = [
    {"CNPJ_Companhia": ATIVA, "Versao": "1", "Tipo_Endereco": SEDE, "Sigla_UF": "DF"},
    {"CNPJ_Companhia": ATIVA, "Versao": "2", "Tipo_Endereco": SEDE, "Sigla_UF": "sp"},
    {"CNPJ_Companhia": ATIVA, "Versao": "3", "Tipo_Endereco": "Endereço Correspondência",
     "Sigla_UF": "RJ"},
    {"CNPJ_Companhia": CANCELADA, "Versao": "1", "Tipo_Endereco": SEDE, "Sigla_UF": ""},
]


class _Leitor:
    def __init__(self, arquivos: dict[str, list[dict[str, str]]]):
        self._arquivos = arquivos

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def tem(self, nome: str) -> bool:
        return nome in self._arquivos

    def linhas(self, nome: str):
        yield from self._arquivos[nome]


def _fonte(arquivos: dict[str, list[dict[str, str]]]) -> FonteCvm:
    fonte = FonteCvm(None, None, None, logging.getLogger("teste"))  # type: ignore[arg-type]
    fonte._leitor = lambda tipo, ano, forcar_download=False: _Leitor(arquivos)  # type: ignore[method-assign]
    return fonte


def test_situacao_vem_da_coluna_real_e_cancelada_fica_distinguivel():
    empresas = _fonte({"fca_cia_aberta_geral_2025.csv": GERAL}).empresas(2025)
    assert empresas[ATIVA].situacao_registro == "Ativo"
    assert empresas[CANCELADA].situacao_registro == "Cancelado"
    assert empresas[ATIVA].data_constituicao.year == 1990
    assert empresas[CANCELADA].data_constituicao is None


def test_uf_da_sede_usa_a_versao_mais_nova_e_ignora_outros_enderecos():
    empresas = _fonte({
        "fca_cia_aberta_geral_2025.csv": GERAL,
        "fca_cia_aberta_endereco_2025.csv": ENDERECOS,
    }).empresas(2025)
    assert empresas[ATIVA].uf_municipio == "SP"
    assert empresas[CANCELADA].uf_municipio is None


def test_sem_arquivo_de_enderecos_a_uf_fica_nula_sem_erro():
    empresas = _fonte({"fca_cia_aberta_geral_2025.csv": GERAL}).empresas(2025)
    assert all(e.uf_municipio is None for e in empresas.values())
