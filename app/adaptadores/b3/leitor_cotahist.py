"""Parser do COTAHIST: registro fixo de 245 caracteres, latin-1."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from decimal import Decimal

from app.dominio.serie_historica import CandleB3, OpcaoB3

TAMANHO_REGISTRO = 245
TIPO_COTACAO = "01"

# Candles vista (lote padrao)
MERCADO_LOTE_PADRAO = "010"
BDI_LOTE_PADRAO = "02"

# Opcoes: BDI 12=call, 14=put; TPMERC 070=compra, 080=venda
BDI_CALL = "12"
BDI_PUT = "14"
MERCADOS_OPCOES = {"070", "080"}


def _inteiro(texto: str) -> int:
    texto = texto.strip()
    return int(texto) if texto else 0


def _decimal_centavos(texto: str) -> Decimal:
    return Decimal(_inteiro(texto)) / Decimal(100)


def _decimal_centavos_ou_none(texto: str) -> Decimal | None:
    v = _inteiro(texto)
    return Decimal(v) / Decimal(100) if v else None


def _inteiro_ou_none(texto: str) -> int | None:
    v = _inteiro(texto)
    return v if v else None


class LeitorCotahist:
    def ler_zip(self, conteudo: bytes, simbolos: set[str]) -> list[CandleB3]:
        simbolos_normalizados = {s.strip().upper() for s in simbolos}
        with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
            nomes = [nome for nome in pacote.namelist() if nome.upper().endswith(".TXT")]
            if len(nomes) != 1:
                raise ValueError(f"COTAHIST deve conter um TXT; encontrados: {len(nomes)}")
            texto = pacote.read(nomes[0]).decode("latin-1")
        return self.ler_linhas(texto.splitlines(), simbolos_normalizados)

    def ler_linhas(self, linhas: list[str], simbolos: set[str]) -> list[CandleB3]:
        resultado: list[CandleB3] = []
        for numero, linha in enumerate(linhas, start=1):
            if linha[:2] != TIPO_COTACAO:
                continue
            if len(linha) != TAMANHO_REGISTRO:
                raise ValueError(
                    f"Registro COTAHIST {numero} tem {len(linha)} caracteres; esperado 245"
                )
            simbolo = linha[12:24].strip().upper()
            if simbolo not in simbolos:
                continue
            if linha[24:27] != MERCADO_LOTE_PADRAO or linha[10:12] != BDI_LOTE_PADRAO:
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
                    nome_resumido=linha[27:39].strip() or None,
                    moeda_referencia=linha[52:56].strip() or "BRL",
                )
            )
        return resultado

    def ler_zip_opcoes(self, conteudo: bytes, simbolos: set[str]) -> list[OpcaoB3]:
        simbolos_normalizados = {s.strip().upper() for s in simbolos}
        with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
            nomes = [nome for nome in pacote.namelist() if nome.upper().endswith(".TXT")]
            if len(nomes) != 1:
                raise ValueError(f"COTAHIST deve conter um TXT; encontrados: {len(nomes)}")
            texto = pacote.read(nomes[0]).decode("latin-1")
        return self.ler_opcoes_linhas(texto.splitlines(), simbolos_normalizados)

    def ler_opcoes_linhas(self, linhas: list[str], simbolos: set[str]) -> list[OpcaoB3]:
        """Extrai cotacoes de opcoes do COTAHIST.

        Filtra por BDI 12 (call) e 14 (put), que correspondem a TPMERC 070/080.
        indice_correcao (C1): "0"=sem correcao, "1"=SELIC, "2"=IGP-M.
        """
        resultado: list[OpcaoB3] = []
        for numero, linha in enumerate(linhas, start=1):
            if linha[:2] != TIPO_COTACAO:
                continue
            if len(linha) != TAMANHO_REGISTRO:
                raise ValueError(
                    f"Registro COTAHIST {numero} tem {len(linha)} caracteres; esperado 245"
                )
            bdi = linha[10:12]
            if bdi not in (BDI_CALL, BDI_PUT):
                continue
            if linha[24:27] not in MERCADOS_OPCOES:
                continue
            simbolo = linha[12:24].strip().upper()
            if simbolo not in simbolos:
                continue
            dataven_str = linha[202:210]
            try:
                data_vencimento = datetime.strptime(dataven_str, "%Y%m%d").date()
            except ValueError:
                continue
            resultado.append(
                OpcaoB3(
                    simbolo=simbolo,
                    bdi=bdi,
                    data_pregao=datetime.strptime(linha[2:10], "%Y%m%d").date(),
                    data_vencimento=data_vencimento,
                    preco_exercicio=_decimal_centavos(linha[188:201]),
                    abertura=_decimal_centavos_ou_none(linha[56:69]),
                    maxima=_decimal_centavos_ou_none(linha[69:82]),
                    minima=_decimal_centavos_ou_none(linha[82:95]),
                    fechamento=_decimal_centavos_ou_none(linha[108:121]),
                    preco_medio=_decimal_centavos_ou_none(linha[95:108]),
                    volume=_inteiro_ou_none(linha[152:170]),
                    numero_negocios=_inteiro_ou_none(linha[147:152]),
                    volume_financeiro=_decimal_centavos_ou_none(linha[170:188]),
                    fator_cotacao=_inteiro(linha[210:217]) or 1,
                    isin=linha[230:242].strip() or None,
                    ativo_objeto=None,
                    tipo_opcao="CALL" if bdi == BDI_CALL else "PUT",
                    status_validacao="VALIDA",
                    motivo_rejeicao=None,
                    indice_correcao=linha[201:202].strip() or None,
                    melhor_oferta_compra=_decimal_centavos_ou_none(linha[121:134]),
                    melhor_oferta_venda=_decimal_centavos_ou_none(linha[134:147]),
                )
            )
        return resultado
