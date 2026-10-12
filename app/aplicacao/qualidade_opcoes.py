"""Qualidade da cadeia de opcoes na execucao do COTAHIST (OPT-ETL-4).

Roda junto da prontidao, ao fim da carga do COTAHIST (start unico, DEC-AGT-1). Mede o que ficou
gravado em `opcao_b3_diaria` (V30: `status_validacao`, `motivo_rejeicao`, `ativo_objeto`) e registra
em `etl_execucao` a fonte QUALIDADE_OPCOES com as metricas minimas do Plano OPT em JSON
(`mensagem_erro`). Status SUCESSO = ultimo pregao com cadeia valida e sem legado nao validado;
INCOMPLETO caso contrario. So mede: nao bloqueia o operacional nem altera dado.
"""

from __future__ import annotations

import json
from logging import Logger

from sqlalchemy import text

FONTE_QUALIDADE_OPCOES = "QUALIDADE_OPCOES"
VALIDA = "VALIDA"
VENCIMENTO_SENTINELA = "9999-12-31"
TOP = 10


def _tem_validacao(db) -> bool:
    return bool(db.execute(text(
        "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() "
        "AND table_name = 'opcao_b3_diaria' AND column_name = 'status_validacao'")).scalar())


def _totais(db, filtro: str, params: dict) -> dict:
    linha = db.execute(text(
        "SELECT COUNT(*) AS total, "
        "SUM(status_validacao = 'VALIDA') AS validos, "
        "SUM(status_validacao = 'LEGADO_NAO_VALIDADO') AS legado, "
        "SUM(data_vencimento = :sentinela) AS venc9999, "
        "COUNT(DISTINCT CASE WHEN status_validacao = 'VALIDA' THEN ativo_objeto END) AS ativos "
        f"FROM opcao_b3_diaria {filtro}"), {"sentinela": VENCIMENTO_SENTINELA, **params}).mappings().one()
    total, validos = int(linha["total"] or 0), int(linha["validos"] or 0)
    return {"totalRegistrosOpcoes": total, "registrosValidos": validos,
            "registrosInvalidos": total - validos, "registrosLegadoNaoValidado": int(linha["legado"] or 0),
            "registrosVencimento9999": int(linha["venc9999"] or 0), "ativosComCadeia": int(linha["ativos"] or 0)}


def avaliar(db) -> dict | None:
    pregao = db.execute(text("SELECT MAX(data_pregao) FROM opcao_b3_diaria")).scalar()
    if pregao is None:
        return None
    if not _tem_validacao(db):
        return {"dataPregao": pregao.isoformat(), "estado": "SEM_VALIDACAO_NO_SCHEMA", "pronto": False}
    ultimo = _totais(db, "WHERE data_pregao = :d", {"d": pregao})
    motivos = [{"status": s, "motivo": m or "SEM_MOTIVO", "registros": int(n)} for s, m, n in db.execute(text(
        "SELECT status_validacao, motivo_rejeicao, COUNT(*) AS n FROM opcao_b3_diaria "
        "WHERE data_pregao = :d AND status_validacao <> 'VALIDA' "
        "GROUP BY status_validacao, motivo_rejeicao ORDER BY n DESC LIMIT :t"), {"d": pregao, "t": TOP})]
    prefixos = [{"prefixo": p, "registros": int(n)} for p, n in db.execute(text(
        "SELECT LEFT(simbolo, 4) AS p, COUNT(*) AS n FROM opcao_b3_diaria "
        "WHERE data_pregao = :d AND status_validacao <> 'VALIDA' GROUP BY p ORDER BY n DESC LIMIT :t"),
        {"d": pregao, "t": TOP})]
    pronto = ultimo["ativosComCadeia"] > 0 and ultimo["registrosLegadoNaoValidado"] == 0
    return {"dataPregao": pregao.isoformat(), "estado": "CADEIA_VALIDA" if pronto else "SEM_CADEIA_VALIDA",
            "pronto": pronto, "ultimoPregao": ultimo, "historico": _totais(db, "", {}),
            "motivosPrincipais": motivos, "prefixosSuspeitos": prefixos}


def registrar_qualidade_opcoes(uow, execucao, logger: Logger) -> dict | None:
    with uow.transacao() as db:
        metricas = avaliar(db)
        if metricas is None:
            return None
        execucao.registrar(
            db, FONTE_QUALIDADE_OPCOES, metricas["dataPregao"], "opcao_b3_diaria",
            "SUCESSO" if metricas["pronto"] else "INCOMPLETO",
            linhas_carregadas=metricas.get("ultimoPregao", {}).get("registrosValidos", 0),
            mensagem_erro=json.dumps(metricas, ensure_ascii=False))
    ultimo = metricas.get("ultimoPregao", {})
    logger.info("Qualidade opcoes %s: %s | validos=%s | invalidos=%s | legado=%s | ativos_com_cadeia=%s",
                metricas["dataPregao"], metricas["estado"], ultimo.get("registrosValidos"),
                ultimo.get("registrosInvalidos"), ultimo.get("registrosLegadoNaoValidado"),
                ultimo.get("ativosComCadeia"))
    return metricas
