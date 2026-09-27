"""Parser do COTAHIST: registro fixo de 245 caracteres, latin-1."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from decimal import Decimal

from app.dominio.serie_historica import CandleB3

TAMANHO_REGISTRO = 245
TIPO_COTACAO = "01"
MERCADO_LOTE_PADRAO = "010"
BDI_LOTE_PADRAO = "02"
# BDR (ex.: JBSS32, o BDR da JBS N.V. que substituiu a JBSS3) vem com BDI
# 35 no mercado a vista de lote padrao - visto no COTAHIST_A2026.
BDI_BDR = "35"
BDIS_ACEITOS = {BDI_LOTE_PADRAO, BDI_BDR}


def _inteiro(texto: str) -> int:
    texto = texto.strip()
    return int(texto) if texto else 0


def _decimal_centavos(texto: str) -> Decimal:
    return Decimal(_inteiro(texto)) / Decimal(100)


class LeitorCotahist:
    def ler_zip(self, conteudo: bytes, simbolos: set[str] | None = None) -> list[CandleB3]:
        """simbolos=None: universo amplo, sem filtro de simbolo - so BDI 02
        (acoes de lote padrao), sem BDR (TASK-59). Com simbolos, so esses,
        aceitando tambem BDI 35/BDR (uso pontual, ex.: --simbolo explicito)."""
        simbolos_normalizados = None if simbolos is None else {s.strip().upper() for s in simbolos}
        with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
            nomes = [nome for nome in pacote.namelist() if nome.upper().endswith(".TXT")]
            if len(nomes) != 1:
                raise ValueError(f"COTAHIST deve conter um TXT; encontrados: {len(nomes)}")
            texto = pacote.read(nomes[0]).decode("latin-1")
        return self.ler_linhas(texto.splitlines(), simbolos_normalizados)

    def ler_linhas(self, linhas: list[str], simbolos: set[str] | None = None) -> list[CandleB3]:
        # Sem simbolos (universo amplo): so BDI 02 (acoes) - BDR (BDI 35) e
        # papel estrangeiro sem balanco na CVM, so entra quando pedido
        # explicitamente (ex.: JBSS32 via --simbolo/ativo_identidade).
        bdis_aceitos = BDIS_ACEITOS if simbolos is not None else {BDI_LOTE_PADRAO}
        resultado: list[CandleB3] = []
        for numero, linha in enumerate(linhas, start=1):
            if linha[:2] != TIPO_COTACAO:
                continue
            if len(linha) != TAMANHO_REGISTRO:
                raise ValueError(
                    f"Registro COTAHIST {numero} tem {len(linha)} caracteres; esperado 245"
                )
            simbolo = linha[12:24].strip().upper()
            if simbolos is not None and simbolo not in simbolos:
                continue
            if linha[24:27] != MERCADO_LOTE_PADRAO or linha[10:12] not in bdis_aceitos:
                continue
            resultado.append(
                CandleB3(
                    simbolo=simbolo,
                    data_pregao=datetime.strptime(linha[2:10], "%Y%m%d").date(),
                    abertura=_decimal_centavos(linha[56:69]),
                    maxima=_decimal_centavos(linha[69:82]),
                    minima=_decimal_centavos(linha[82:95]),
                    fechamento=_decimal_centavos(linha[108:121]),
                    numero_negocios=_inteiro(linha[147:152]),
                    volume=_inteiro(linha[152:170]),
                    volume_financeiro=_decimal_centavos(linha[170:188]),
                )
            )
        return resultado
