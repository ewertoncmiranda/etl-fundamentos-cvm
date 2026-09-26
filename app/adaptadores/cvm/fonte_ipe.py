"""Implementacao de FonteDeComunicados sobre a base IPE da CVM.

IPE = Informacoes Periodicas e Eventuais: um ZIP por ano com um unico CSV
(latin-1, ';') listando todo documento eventual entregue pelas companhias -
fato relevante, comunicado, aviso aos acionistas, ata... com o link oficial
de download no RAD.

Diferente dos pacotes contabeis, o arquivo muda toda semana. Por isso aqui o
download e sempre feito quando o caso de uso decide processar (o ETag ja
mudou); o cache so guarda a copia para inspecao e para reprocessar offline.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import date, datetime
from logging import Logger

from app.adaptadores.cvm.cache_local import CacheDeArquivos
from app.adaptadores.cvm.cliente_http import Assinatura, ClienteHttpCvm
from app.adaptadores.cvm.leitor_pacote import LeitorDePacoteCvm
from app.dominio.comunicado import (
    Comunicado,
    classificar_categoria,
    extrair_protocolo,
    versao_mais_recente,
)
from app.excecoes.excecoes import PacoteInvalido

# Sem estas colunas nao ha como montar um comunicado. Conferir antes de ler
# transforma uma mudanca de layout da CVM em erro explicito, em vez de
# milhares de linhas silenciosamente descartadas.
COLUNAS_OBRIGATORIAS = (
    "CNPJ_Companhia",
    "Categoria",
    "Data_Entrega",
    "Versao",
    "Link_Download",
)


def caminho_do_ipe(ano: int) -> str:
    return f"IPE/DADOS/ipe_cia_aberta_{ano}.zip"


def nome_do_csv(ano: int) -> str:
    return f"ipe_cia_aberta_{ano}.csv"


class FonteIpe:
    def __init__(self, cliente: ClienteHttpCvm, cache: CacheDeArquivos, logger: Logger):
        self._cliente = cliente
        self._cache = cache
        self._logger = logger

    def assinatura(self, ano: int) -> Assinatura:
        return self._cliente.assinatura(caminho_do_ipe(ano))

    def comunicados(
        self, ano: int, cnpjs: set[str], categorias: Collection[str]
    ) -> list[Comunicado]:
        if not cnpjs:
            return []

        caminho = caminho_do_ipe(ano)
        conteudo = self._cliente.baixar(caminho)
        self._cache.gravar(caminho.rsplit("/", 1)[-1], conteudo)

        return ler_comunicados(
            LeitorDePacoteCvm(conteudo, nome_para_erro=f"IPE {ano}"),
            nome_do_csv(ano),
            cnpjs,
            set(categorias),
            self._logger,
        )


def ler_comunicados(
    leitor: LeitorDePacoteCvm,
    arquivo: str,
    cnpjs: set[str],
    categorias: set[str],
    logger: Logger,
) -> list[Comunicado]:
    """Separado da classe para poder ser testado com um ZIP montado em memoria."""
    encontrados: list[Comunicado] = []
    sem_protocolo = 0

    with leitor:
        linhas = leitor.linhas(arquivo)
        for numero, linha in enumerate(linhas):
            if numero == 0:
                _conferir_colunas(linha, arquivo)

            cnpj = (linha.get("CNPJ_Companhia") or "").strip()
            if cnpj not in cnpjs:
                continue

            categoria = classificar_categoria(linha.get("Categoria"))
            if categoria not in categorias:
                continue

            link = (linha.get("Link_Download") or "").strip()
            protocolo = extrair_protocolo(link)
            data_entrega = _data(linha.get("Data_Entrega"))
            if not protocolo or data_entrega is None:
                sem_protocolo += 1
                continue

            encontrados.append(
                Comunicado(
                    protocolo_cvm=protocolo,
                    versao=_inteiro(linha.get("Versao"), padrao=1),
                    cnpj=cnpj,
                    categoria=categoria,
                    categoria_original=(linha.get("Categoria") or "").strip()[:200],
                    data_entrega=data_entrega,
                    link_download=link[:300],
                    protocolo_entrega=_texto(linha.get("Protocolo_Entrega"), 40),
                    codigo_cvm=_texto(linha.get("Codigo_CVM"), 10),
                    tipo=_texto(linha.get("Tipo"), 120),
                    especie=_texto(linha.get("Especie"), 120),
                    assunto=_texto(linha.get("Assunto")),
                    data_referencia=_data(linha.get("Data_Referencia")),
                )
            )

    if sem_protocolo:
        logger.warning(
            "%s: %d linha(s) sem numProtocolo no link ou sem data de entrega; ignoradas",
            arquivo,
            sem_protocolo,
        )
    return versao_mais_recente(encontrados)


def _conferir_colunas(linha: dict[str, str], arquivo: str) -> None:
    faltando = [c for c in COLUNAS_OBRIGATORIAS if c not in linha]
    if faltando:
        raise PacoteInvalido(
            f"{arquivo} mudou de layout: faltam as colunas {', '.join(faltando)}"
        )


def _texto(valor: str | None, limite: int | None = None) -> str | None:
    limpo = (valor or "").strip()
    if not limpo:
        return None
    return limpo[:limite] if limite else limpo


def _inteiro(valor: str | None, padrao: int) -> int:
    try:
        return int((valor or "").strip())
    except ValueError:
        return padrao


def _data(valor: str | None) -> date | None:
    try:
        return datetime.strptime((valor or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None
