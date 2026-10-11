"""Prontidao diaria do operacional (OPR-ETL-5) e auditoria de ponto no tempo (OPR-ETL-4).

Roda ao fim da carga do COTAHIST, depois da liquidez (start unico, DEC-AGT-1). Para o ultimo pregao
do mercado registra em `etl_execucao` a fonte PRONTIDAO_OPR com status SUCESSO ou INCOMPLETO e as
checagens em JSON (`mensagem_erro`). O diario operacional (gerar-insights) so processa pregao com
prontidao SUCESSO.

Checagens:
- cotahist_completo: ativos no pregao >= 80% da mediana dos 20 pregoes anteriores;
- liquidez_calculada: linhas de `ativo_liquidez_diaria` no pregao, na versao atual do calculo,
  para >= 95% dos ativos com cotacao;
- ponto_no_tempo: nenhum fundamento com `data_entrega` antes do fim do periodo. Linha assim (dado
  trocado na CVM) tem a entrega anulada aqui mesmo — fica fora do operacional, nunca entra cedo;
- cargas_sem_erro: a ultima execucao de DFP, TTM, DVA (proventos) e eventos corporativos nao e ERRO.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import date
from logging import Logger

from sqlalchemy import text

from app.dominio.liquidez import VERSAO_CALCULO

FONTE_PRONTIDAO = "PRONTIDAO_OPR"
PRONTO, INCOMPLETO = "SUCESSO", "INCOMPLETO"
FONTES_CRITICAS = ("CVM_DFP", "CVM_TTM", "CVM_DVA", "EVENTOS_CORPORATIVOS")
MINIMO_COTAHIST = 0.80
MINIMO_LIQUIDEZ = 0.95


@dataclass
class Prontidao:
    data_pregao: date | None
    pronto: bool = False
    checagens: dict = field(default_factory=dict)


def auditar_ponto_no_tempo(db) -> dict:
    """Anula a entrega impossivel (antes do fim do periodo) e devolve a contagem (OPR-ETL-4)."""
    corrigidas = db.execute(text(
        "UPDATE indicador_fundamentalista SET data_entrega = NULL "
        "WHERE data_entrega IS NOT NULL AND data_entrega < periodo")).rowcount
    sem_entrega = db.execute(text(
        "SELECT COUNT(*) FROM indicador_fundamentalista WHERE data_entrega IS NULL")).scalar()
    return {"ok": True, "entregas_impossiveis_anuladas": int(corrigidas or 0),
            "sem_data_entrega_fora_do_operacional": int(sem_entrega or 0)}


def avaliar(db) -> Prontidao:
    pregoes = [d for (d,) in db.execute(text(
        "SELECT DISTINCT data_pregao FROM cotacao_b3_diaria ORDER BY data_pregao DESC LIMIT 21"))]
    if not pregoes:
        return Prontidao(None)
    alvo = pregoes[0]
    contagem = dict(db.execute(text(
        "SELECT data_pregao, COUNT(*) FROM cotacao_b3_diaria WHERE data_pregao >= :d GROUP BY data_pregao"),
        {"d": pregoes[-1]}).all())
    hoje = int(contagem.get(alvo, 0))
    referencia = statistics.median([contagem[d] for d in pregoes[1:]]) if len(pregoes) > 1 else hoje
    liquidez = int(db.execute(text(
        "SELECT COUNT(*) FROM ativo_liquidez_diaria WHERE data_pregao = :d AND versao_calculo = :v"),
        {"d": alvo, "v": VERSAO_CALCULO}).scalar() or 0)
    ultimas = {}
    for fonte in FONTES_CRITICAS:
        status = db.execute(text(
            "SELECT status FROM etl_execucao WHERE fonte = :f ORDER BY iniciado_em DESC, id DESC LIMIT 1"),
            {"f": fonte}).scalar()
        ultimas[fonte] = status
    checagens = {
        "cotahist_completo": {"ok": hoje >= MINIMO_COTAHIST * referencia, "ativos": hoje,
                              "mediana_20_pregoes": referencia},
        "liquidez_calculada": {"ok": hoje > 0 and liquidez >= MINIMO_LIQUIDEZ * hoje, "linhas": liquidez,
                               "versao": VERSAO_CALCULO},
        "ponto_no_tempo": auditar_ponto_no_tempo(db),
        "cargas_sem_erro": {"ok": all(s != "ERRO" for s in ultimas.values()), "ultimas": ultimas},
    }
    return Prontidao(alvo, all(c["ok"] for c in checagens.values()), checagens)


def registrar_prontidao(uow, execucao, logger: Logger) -> Prontidao:
    with uow.transacao() as db:
        resultado = avaliar(db)
        if resultado.data_pregao is None:
            return resultado
        execucao.registrar(
            db, FONTE_PRONTIDAO, resultado.data_pregao.isoformat(), "checagens",
            PRONTO if resultado.pronto else INCOMPLETO,
            linhas_carregadas=sum(1 for c in resultado.checagens.values() if c["ok"]),
            mensagem_erro=json.dumps(resultado.checagens, ensure_ascii=False, default=str))
    falhas = [k for k, c in resultado.checagens.items() if not c["ok"]]
    if falhas:
        logger.warning("Prontidao operacional %s INCOMPLETA: %s", resultado.data_pregao, ", ".join(falhas))
    else:
        logger.info("Prontidao operacional %s: pronta", resultado.data_pregao)
    return resultado