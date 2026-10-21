"""Regras puras das fontes publicas da V45: validacao, truncagem e hash_linha.

Nada aqui toca banco ou rede. Cada `motivo_*` devolve None quando o registro
pode ser gravado ou o motivo do descarte (que vira ALERTA na etapa).
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from decimal import Decimal

SEPARADOR = "\x1f"


def so_digitos(valor: str | None) -> str:
    return re.sub(r"\D", "", valor or "")


def cnpj14(valor: str | None) -> str | None:
    digitos = so_digitos(valor)
    return digitos if len(digitos) == 14 else None


def cortar(texto: str | None, tamanho: int) -> str | None:
    """Texto sem espacos nas pontas, limitado ao tamanho da coluna; vazio vira None."""
    limpo = (texto or "").strip()
    return limpo[:tamanho] if limpo else None


def cabe(valor: Decimal | None, inteiros: int) -> bool:
    """True se o valor cabe num DECIMAL com `inteiros` digitos antes da virgula."""
    return valor is None or abs(valor) < Decimal(10) ** inteiros


def _parte(valor, escala: int = 0) -> str:
    if valor is None:
        return ""
    if isinstance(valor, Decimal):
        return format(valor.quantize(Decimal(1).scaleb(-escala)), "f")
    if isinstance(valor, date):
        return valor.isoformat()
    return str(valor).strip()


def hash_linha(*partes) -> str:
    """SHA-256 hex (64 caracteres) das partes, separadas por U+001F.

    None vira vazio; Decimal e quantizado na escala da coluna (passe
    `(valor, escala)`), data vai em ISO. Mesmo conteudo gera sempre o mesmo hash.
    """
    texto = SEPARADOR.join(
        _parte(*p) if isinstance(p, tuple) else _parte(p) for p in partes
    )
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def hash_negociacao(
    tipo_empresa, tipo_cargo, tipo_movimentacao, tipo_operacao, tipo_ativo,
    caracteristica, data_movimentacao, quantidade, preco_unitario, volume,
) -> str:
    """Colunas de conteudo do VLMO (valores ja truncados como serao gravados).

    Fora do hash: cnpj, data_referencia e versao (ja na chave unica) e
    data_entrega (metadado que pode chegar depois, nao identifica a linha)."""
    return hash_linha(
        tipo_empresa, tipo_cargo, tipo_movimentacao, tipo_operacao, tipo_ativo,
        caracteristica, data_movimentacao,
        (quantidade, 6), (preco_unitario, 6), (volume, 2),
    )


def hash_divida(
    tipo, identificacao, data_emissao, data_vencimento, quantidade, valor,
    saldo_devedor, conversivel,
) -> str:
    """Colunas de conteudo da divida por valor mobiliario do FRE."""
    return hash_linha(
        tipo, identificacao, data_emissao, data_vencimento,
        (quantidade, 6), (valor, 2), (saldo_devedor, 2), conversivel,
    )


def texto_conversivel(valor: bool | None) -> str | None:
    return None if valor is None else ("Sim" if valor else "Nao")


def motivo_taxa(t) -> str | None:
    if not (t.tipo or "").strip():
        return "TITULO_SEM_TIPO"
    if len(t.tipo.strip()) > 60:
        return "TIPO_LONGO"
    if not (cabe(t.taxa_compra, 5) and cabe(t.taxa_venda, 5)):
        return "TAXA_FORA_DA_FAIXA"
    if not (cabe(t.pu_compra, 10) and cabe(t.pu_venda, 10) and cabe(t.pu_base, 10)):
        return "PU_FORA_DA_FAIXA"
    return None


def motivo_auditor(a) -> str | None:
    if cnpj14(a.cnpj) is None:
        return "CNPJ_COMPANHIA_INVALIDO"
    if a.dt_referencia is None:
        return "SEM_DATA_REFERENCIA"
    if cnpj14(a.cnpj_auditor) is None:
        return "CNPJ_AUDITOR_INVALIDO"
    if a.dt_inicio_contratacao is None:
        return "SEM_DATA_INICIO"
    return None


def motivo_negociacao(n) -> str | None:
    if cnpj14(n.cnpj) is None:
        return "CNPJ_INVALIDO"
    if not (cabe(n.quantidade, 16) and cabe(n.preco_unitario, 16) and cabe(n.volume, 20)):
        return "VALOR_FORA_DA_FAIXA"
    return None


def motivo_divida(d) -> str | None:
    if cnpj14(d.cnpj) is None:
        return "CNPJ_INVALIDO"
    if d.dt_referencia is None:
        return "SEM_DATA_REFERENCIA"
    if not (cabe(d.quantidade, 16) and cabe(d.valor, 20) and cabe(d.saldo_devedor, 20)):
        return "VALOR_FORA_DA_FAIXA"
    return None


def motivo_posicao(p) -> str | None:
    if cnpj14(p.cnpj_fundo) is None:
        return "CNPJ_FUNDO_INVALIDO"
    if len(p.simbolo) > 12:
        return "SIMBOLO_LONGO"
    if len(p.isin or "") > 12:
        return "ISIN_LONGO"
    if not (cabe(p.quantidade, 16) and cabe(p.valor_mercado, 20) and cabe(p.pl_fundo, 20)):
        return "VALOR_FORA_DA_FAIXA"
    return None


MERCADOS_PERMITIDOS = frozenset({"012", "013", "017", "020", "030", "050", "060"})


def motivo_mercado(n) -> str | None:
    """Negocio de outro mercado do COTAHIST (negociacao_b3_diaria)."""
    if n.mercado not in MERCADOS_PERMITIDOS:
        return "TPMERC_FORA_DO_CONTRATO"
    if not n.simbolo or len(n.simbolo) > 12:
        return "SIMBOLO_INVALIDO"
    if not (
        cabe(n.preco_exercicio, 10) and cabe(n.abertura, 10) and cabe(n.maxima, 10)
        and cabe(n.minima, 10) and cabe(n.fechamento, 10) and cabe(n.preco_medio, 10)
        and cabe(n.melhor_oferta_compra, 10) and cabe(n.melhor_oferta_venda, 10)
        and cabe(n.volume_financeiro, 20)
    ):
        return "PRECO_FORA_DA_FAIXA"
    return None
