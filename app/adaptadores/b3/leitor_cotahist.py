"""Parser do COTAHIST: registro fixo de 245 caracteres, latin-1.

Posicoes (1-based) do layout oficial da B3: ESPECI 40-49, PREABE 57-69,
PREMAX 70-82, PREMIN 83-95, PREMED 96-108, PREULT 109-121, PREOFC 122-134,
PREOFV 135-147, TOTNEG 148-152, QUATOT 153-170, VOLTOT 171-188,
PTOEXE 189-201, DATVEN 203-210, FATCOT 211-217.
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal

from app.dominio.serie_historica import CandleB3, OpcaoB3

TAMANHO_REGISTRO = 245
TIPO_COTACAO = "01"

# Candles vista (lote padrao)
MERCADO_LOTE_PADRAO = "010"
BDI_LOTE_PADRAO = "02"
# BDR (ex.: JBSS32, o BDR da JBS N.V. que substituiu a JBSS3) vem com BDI
# 35 no mercado a vista de lote padrao - visto no COTAHIST_A2026.
BDI_BDR = "35"
BDIS_ACEITOS = {BDI_LOTE_PADRAO, BDI_BDR}
BDIS_OPCAO_LEGADO = {"12", "14"}
MERCADO_OPCAO_COMPRA = "070"
MERCADO_OPCAO_VENDA = "080"
MERCADOS_OPCAO = {MERCADO_OPCAO_COMPRA, MERCADO_OPCAO_VENDA}
TIPO_CALL = "CALL"
TIPO_PUT = "PUT"
MESES_CALL = set("ABCDEFGHIJKL")
MESES_PUT = set("MNOPQRSTUVWX")
VENCIMENTO_SENTINELA = date(9999, 12, 31)

# CODBDI 12/14 foi usado no legado como pista para localizar registros
# suspeitos; nao determina tipo e nao e fonte de verdade de CALL/PUT.


def _inteiro(texto: str) -> int:
    texto = texto.strip()
    return int(texto) if texto else 0


def _decimal_centavos(texto: str) -> Decimal:
    return Decimal(_inteiro(texto)) / Decimal(100)


# Sufixo do ESPECI no dia ex: EJ (ex-JCP), ED (ex-dividendo), EB
# (ex-bonificacao), ES (ex-subscricao), EG, EX, ER e combinacoes (EDJ, EDB,
# EJS...). Visto no COTAHIST_A2026: 481 EJ, 253 ED, 24 EG, 22 EB no BDI 02.
_MARCA_EX = re.compile(r"^E[BDGJRSX]{1,3}$")


def _marca_ex(especificacao: str) -> str | None:
    for token in especificacao.split():
        if _MARCA_EX.match(token):
            return token
    return None


def _preco(texto: str, fator: int) -> Decimal:
    """R$ por acao: o COTAHIST cota alguns papeis por lote (FATCOT 1.000 na
    GOLL54, 1.000.000 na AZUL53); sem dividir, o preco sai multiplicado."""
    valor = _decimal_centavos(texto)
    return valor / fator if fator > 1 else valor


def _preco_ou_nulo(texto: str, fator: int) -> Decimal | None:
    return _preco(texto, fator) if _inteiro(texto) else None


def _tipo_opcao_do_mercado(mercado: str) -> str | None:
    if mercado == MERCADO_OPCAO_COMPRA:
        return TIPO_CALL
    if mercado == MERCADO_OPCAO_VENDA:
        return TIPO_PUT
    return None


def _ativo_objeto_do_simbolo(simbolo: str, tipo_opcao: str | None) -> tuple[str | None, str | None]:
    """Deriva o ativo-objeto pelo padrao atual dos codigos de opcoes B3.

    Ex.: PETRA32 -> PETR (CALL), PETRM32 -> PETR (PUT), B3SAA... -> B3SA.
    Nao tenta inferir ETF/FII ou codigo sem letra mensal: esses registros
    recebem motivo estruturado e nao entram como cadeia valida.
    """
    if len(simbolo) < 5:
        return None, "simbolo_sem_padrao_opcao"
    letra_mes = simbolo[4]
    if letra_mes in MESES_CALL:
        tipo_do_codigo = TIPO_CALL
    elif letra_mes in MESES_PUT:
        tipo_do_codigo = TIPO_PUT
    else:
        return None, "simbolo_sem_padrao_opcao"
    if tipo_opcao is not None and tipo_do_codigo != tipo_opcao:
        return None, "tipo_incompativel_com_codigo"
    ativo = simbolo[:4]
    if not re.fullmatch(r"[A-Z0-9]{4}", ativo):
        return None, "ativo_objeto_ausente"
    return ativo, None


def _validar_opcao(
    *,
    simbolo: str,
    mercado: str,
    vencimento: date | None,
    preco_exercicio: Decimal,
) -> tuple[str, str | None, str | None, str | None]:
    tipo_opcao = _tipo_opcao_do_mercado(mercado)
    if tipo_opcao is None:
        return "INVALIDA", None, None, "mercado_nao_opcao"
    if vencimento is None:
        return "INVALIDA", None, tipo_opcao, "vencimento_invalido"
    if vencimento == VENCIMENTO_SENTINELA:
        return "INVALIDA", None, tipo_opcao, "vencimento_sentinela_9999"
    if preco_exercicio <= 0:
        return "INVALIDA", None, tipo_opcao, "preco_exercicio_invalido"
    ativo_objeto, motivo = _ativo_objeto_do_simbolo(simbolo, tipo_opcao)
    if motivo:
        return "INVALIDA", ativo_objeto, tipo_opcao, motivo
    return "VALIDA", ativo_objeto, tipo_opcao, None


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
            fator = max(_inteiro(linha[210:217]), 1)
            especificacao = linha[39:49].strip()
            isin = linha[230:242].strip() or None
            resultado.append(
                CandleB3(
                    simbolo=simbolo,
                    data_pregao=datetime.strptime(linha[2:10], "%Y%m%d").date(),
                    abertura=_preco(linha[56:69], fator),
                    maxima=_preco(linha[69:82], fator),
                    minima=_preco(linha[82:95], fator),
                    fechamento=_preco(linha[108:121], fator),
                    numero_negocios=_inteiro(linha[147:152]),
                    volume=_inteiro(linha[152:170]),
                    volume_financeiro=_decimal_centavos(linha[170:188]),
                    nome_resumido=linha[27:39].strip() or None,
                    moeda_referencia=linha[52:56].strip() or "BRL",
                    especificacao=especificacao or None,
                    marca_ex=_marca_ex(especificacao),
                    fator_cotacao=fator,
                    preco_medio=_preco_ou_nulo(linha[95:108], fator),
                    melhor_oferta_compra=_preco_ou_nulo(linha[121:134], fator),
                    melhor_oferta_venda=_preco_ou_nulo(linha[134:147], fator),
                    isin=isin,
                )
            )
        return resultado

    def ler_opcoes_zip(self, conteudo: bytes) -> list[OpcaoB3]:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
            nomes = [nome for nome in pacote.namelist() if nome.upper().endswith(".TXT")]
            if len(nomes) != 1:
                raise ValueError(f"COTAHIST deve conter um TXT; encontrados: {len(nomes)}")
            texto = pacote.read(nomes[0]).decode("latin-1")
        return self.ler_opcoes_linhas(texto.splitlines())

    def ler_opcoes_linhas(self, linhas: list[str]) -> list[OpcaoB3]:
        """Registros de opcoes reais do COTAHIST.

        PTOEXE (posicoes 189-201, 1-based): preco de exercicio em centavos,
        mesmo formato dos demais precos. Nao divide por FATCOT — o exercicio
        e por acao, nao por lote.
        DATVEN (posicoes 203-210, 1-based): data de vencimento YYYYMMDD.

        A classificacao correta usa TPMERC (posicoes 25-27): 070=CALL,
        080=PUT. CODBDI 12/14 foi mantido apenas para capturar registros
        legados suspeitos e marca-los como invalidos quando o schema de
        validacao existir; em schema antigo, o repositorio persiste so validos.
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
            mercado = linha[24:27]
            if mercado not in MERCADOS_OPCAO and bdi not in BDIS_OPCAO_LEGADO:
                continue
            data_vencimento_str = linha[202:210].strip()
            try:
                data_vencimento = datetime.strptime(data_vencimento_str, "%Y%m%d").date()
            except ValueError:
                data_vencimento = None
            fator = max(_inteiro(linha[210:217]), 1)
            simbolo = linha[12:24].strip().upper()
            preco_exercicio = _decimal_centavos(linha[188:201])
            status, ativo_objeto, tipo_opcao, motivo = _validar_opcao(
                simbolo=simbolo,
                mercado=mercado,
                vencimento=data_vencimento,
                preco_exercicio=preco_exercicio,
            )
            resultado.append(
                OpcaoB3(
                    simbolo=simbolo,
                    bdi=bdi,
                    data_pregao=datetime.strptime(linha[2:10], "%Y%m%d").date(),
                    data_vencimento=data_vencimento or VENCIMENTO_SENTINELA,
                    preco_exercicio=preco_exercicio,
                    abertura=_preco(linha[56:69], fator),
                    maxima=_preco(linha[69:82], fator),
                    minima=_preco(linha[82:95], fator),
                    fechamento=_preco(linha[108:121], fator),
                    numero_negocios=_inteiro(linha[147:152]),
                    volume=_inteiro(linha[152:170]),
                    volume_financeiro=_decimal_centavos(linha[170:188]),
                    isin=linha[230:242].strip() or None,
                    fator_cotacao=fator,
                    preco_medio=_preco_ou_nulo(linha[95:108], fator),
                    ativo_objeto=ativo_objeto,
                    tipo_opcao=tipo_opcao,
                    status_validacao=status,
                    motivo_rejeicao=motivo,
                    indice_correcao=linha[201:202].strip() or None,
                    melhor_oferta_compra=_preco_ou_nulo(linha[121:134], fator),
                    melhor_oferta_venda=_preco_ou_nulo(linha[134:147], fator),
                )
            )
        return resultado
