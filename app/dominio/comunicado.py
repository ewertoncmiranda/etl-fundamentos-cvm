"""Comunicados oficiais das companhias abertas (base IPE da CVM).

Modulo puro: sem I/O. Concentra as tres decisoes de negocio da carga:

  1. quais categorias interessam (o IPE tem ~60, a maioria regimento interno
     e politica de governanca que nao informa nada a quem acompanha a acao);
  2. qual e a identidade de um documento - o numProtocolo do link, e nao o
     Protocolo_Entrega, que vem vazio nos relatorios automaticos de proventos;
  3. qual versao vence quando o mesmo documento aparece de novo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from app.dominio.texto import normalizar

FATO_RELEVANTE = "FATO_RELEVANTE"
COMUNICADO_MERCADO = "COMUNICADO_MERCADO"
AVISO_ACIONISTAS = "AVISO_ACIONISTAS"
PROVENTOS = "PROVENTOS"
CALENDARIO_EVENTOS = "CALENDARIO_EVENTOS"
RESULTADOS = "RESULTADOS"
ASSEMBLEIA = "ASSEMBLEIA"
OUTROS = "OUTROS"

# Texto da coluna Categoria, ja normalizado (sem acento, minusculo) -> slug.
# Comparar normalizado protege contra a CVM trocar acentuacao ou caixa.
CATEGORIAS: dict[str, str] = {
    "fato relevante": FATO_RELEVANTE,
    "comunicado ao mercado": COMUNICADO_MERCADO,
    "aviso aos acionistas": AVISO_ACIONISTAS,
    "relatorio proventos": PROVENTOS,
    "calendario de eventos corporativos": CALENDARIO_EVENTOS,
    "dados economico-financeiros": RESULTADOS,
    "assembleia": ASSEMBLEIA,
}

# Carregadas quando ninguem pede outra coisa. Assembleia fica de fora: e a
# categoria mais volumosa (6,6 mil documentos em 2026, quase tudo ata e
# edital de rotina) e afogaria os fatos relevantes na linha do tempo.
CATEGORIAS_PADRAO: tuple[str, ...] = (
    FATO_RELEVANTE,
    COMUNICADO_MERCADO,
    AVISO_ACIONISTAS,
    PROVENTOS,
    CALENDARIO_EVENTOS,
    RESULTADOS,
)

_NUM_PROTOCOLO = re.compile(r"[?&]numProtocolo=(\d+)")


@dataclass(frozen=True)
class Comunicado:
    protocolo_cvm: str
    versao: int
    cnpj: str
    categoria: str
    categoria_original: str
    data_entrega: date
    link_download: str
    protocolo_entrega: str | None = None
    codigo_cvm: str | None = None
    tipo: str | None = None
    especie: str | None = None
    assunto: str | None = None
    data_referencia: date | None = None


def classificar_categoria(texto: str | None) -> str:
    """Categoria crua do CSV -> slug; o que nao estiver no mapa vira OUTROS."""
    return CATEGORIAS.get(normalizar(texto), OUTROS)


def extrair_protocolo(link_download: str | None) -> str | None:
    """numProtocolo do link do RAD - a identidade estavel do documento.

    Na base de 2026 ele esta presente em todas as 34.884 linhas e nunca
    aparece com duas versoes, ao contrario do Protocolo_Entrega.
    """
    if not link_download:
        return None
    encontrado = _NUM_PROTOCOLO.search(link_download)
    return encontrado.group(1) if encontrado else None


def versao_mais_recente(comunicados: list[Comunicado]) -> list[Comunicado]:
    """Um comunicado por protocolo, ficando a maior versao.

    Tambem elimina as linhas repetidas que a propria CVM publica (122 no
    arquivo de 2026, identicas ate no link).
    """
    por_protocolo: dict[str, Comunicado] = {}
    for comunicado in comunicados:
        atual = por_protocolo.get(comunicado.protocolo_cvm)
        if atual is None or comunicado.versao > atual.versao:
            por_protocolo[comunicado.protocolo_cvm] = comunicado
    return list(por_protocolo.values())
