"""Versao do calculo gravada junto com o ETag em etl_execucao.

O ETag so diz se o arquivo da CVM mudou. Quando o ETL passa a extrair ou
calcular algo novo (ex.: D&A, estoques, EBITDA, liquidez e DSO das V36-V39), o
arquivo continua igual e a carga seguia pulando: as linhas ja gravadas nunca
recebiam os campos novos. Com a versao junto do ETag, subir a versao aqui faz a
proxima carga reprocessar cada arquivo uma vez, sozinha (DEC-AGT-1), sem
precisar de `forcar`.

Suba a versao da fonte sempre que mudar o que ela extrai ou calcula.
"""

from __future__ import annotations

# 1 (implicita): ETag cru, gravado antes desta versao.
# 2: insumos e derivados das V36-V39 (D&A, estoques, contas a receber,
#    resultado financeiro, EBITDA, cobertura de juros, liquidez, DSO).
VERSOES_CALCULO = {
    "CVM_DFP": 2,
    "CVM_TTM": 2,
}
SEPARADOR = "#calc"


def etag_com_versao(fonte: str, etag: str | None) -> str | None:
    """ETag a gravar em etl_execucao: o do arquivo mais a versao do calculo da fonte."""
    versao = VERSOES_CALCULO.get(fonte)
    if not etag or versao is None:
        return etag
    return f"{etag}{SEPARADOR}{versao}"


def arquivo_inalterado(fonte: str, etag_atual: str | None, etag_gravado: str | None) -> bool:
    """Pode pular: mesmo arquivo na origem E processado pela versao atual do calculo."""
    esperado = etag_com_versao(fonte, etag_atual)
    return bool(esperado and etag_gravado and esperado == etag_gravado)
