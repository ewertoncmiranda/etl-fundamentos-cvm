"""Persistência das execuções orquestradas (migration V44)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

LOCK_CARGAS = "etl_fundamentos_carga_unica"


def agora_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class RepositorioCargaSql:
    def __init__(self, engine: Engine):
        self._engine = engine

    def verificar_schema(self) -> None:
        with self._engine.connect() as db:
            presentes = db.execute(text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE() "
                "AND table_name IN ('carga_execucao', 'carga_etapa', 'vw_carga_ultima')"
            )).scalar_one()
            coluna = db.execute(text(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'etl_execucao' "
                "AND column_name = 'carga_execucao_id'"
            )).scalar_one()
        if presentes != 3 or not coluna:
            raise RuntimeError("Controle de cargas indisponível: aplique a migration V44")

    def adquirir_lock(self):
        conexao = self._engine.connect()
        try:
            adquirido = conexao.execute(
                text("SELECT GET_LOCK(:nome, 0)"), {"nome": LOCK_CARGAS}
            ).scalar_one()
            if adquirido == 1:
                return conexao
        except Exception:
            conexao.close()
            raise
        conexao.close()
        return None

    def liberar_lock(self, conexao) -> None:
        try:
            conexao.execute(text("SELECT RELEASE_LOCK(:nome)"), {"nome": LOCK_CARGAS})
        finally:
            conexao.close()

    def marcar_orfas_interrompidas(self) -> int:
        agora = agora_utc()
        with self._engine.begin() as db:
            resultado = db.execute(text(
                "UPDATE carga_execucao SET status = 'INTERROMPIDA', "
                "finalizada_em = :agora, atualizada_em = :agora, "
                "mensagem_erro = COALESCE(mensagem_erro, "
                "'Processo interrompido antes da conclusão'), "
                "duracao_ms = TIMESTAMPDIFF(MICROSECOND, iniciada_em, :agora) DIV 1000 "
                "WHERE status IN ('PENDENTE', 'EXECUTANDO')"
            ), {"agora": agora})
            db.execute(text(
                "UPDATE carga_etapa SET status = 'FALHA', finalizada_em = :agora, "
                "duracao_ms = TIMESTAMPDIFF(MICROSECOND, iniciada_em, :agora) DIV 1000, "
                "erros_json = JSON_ARRAY('Execução interrompida') "
                "WHERE status = 'EXECUTANDO' AND execucao_id IN "
                "(SELECT id FROM carga_execucao WHERE status = 'INTERROMPIDA')"
            ), {"agora": agora})
        return resultado.rowcount or 0

    def criar(self, carga_id: str, tipo: str, solicitada_por: str, parametros: dict,
              versao: str | None) -> None:
        with self._engine.begin() as db:
            db.execute(text(
                "INSERT INTO carga_execucao "
                "(id, tipo, solicitada_por, parametros_json, status, versao_etl, criada_em) "
                "VALUES (:id, :tipo, :solicitada_por, :parametros, 'PENDENTE', :versao, :agora)"
            ), {
                "id": carga_id, "tipo": tipo, "solicitada_por": solicitada_por,
                "parametros": json.dumps(parametros, ensure_ascii=False), "versao": versao,
                "agora": agora_utc(),
            })

    def iniciar(self, carga_id: str) -> None:
        with self._engine.begin() as db:
            db.execute(text(
                "UPDATE carga_execucao SET status = 'EXECUTANDO', iniciada_em = :agora, "
                "atualizada_em = :agora WHERE id = :id"
            ), {"id": carga_id, "agora": agora_utc()})

    def iniciar_etapa(self, carga_id: str, ordem: int, etapa: str) -> None:
        with self._engine.begin() as db:
            db.execute(text(
                "INSERT INTO carga_etapa (execucao_id, ordem, etapa, status, iniciada_em) "
                "VALUES (:id, :ordem, :etapa, 'EXECUTANDO', :agora)"
            ), {"id": carga_id, "ordem": ordem, "etapa": etapa, "agora": agora_utc()})

    def finalizar_etapa(self, carga_id: str, etapa: str, resumo) -> None:
        agora = agora_utc()
        with self._engine.begin() as db:
            db.execute(text(
                "UPDATE carga_etapa SET status = :status, finalizada_em = :agora, "
                "duracao_ms = TIMESTAMPDIFF(MICROSECOND, iniciada_em, :agora) DIV 1000, "
                "metricas_json = :metricas, alertas_json = :alertas, erros_json = :erros "
                "WHERE execucao_id = :id AND etapa = :etapa"
            ), {
                "id": carga_id, "etapa": etapa, "status": resumo.status, "agora": agora,
                "metricas": _json(resumo.metricas), "alertas": _json(resumo.alertas),
                "erros": _json(resumo.erros),
            })

    def finalizar(self, carga_id: str, status: str, mensagem: str | None,
                  ok: int, alerta: int, falha: int) -> None:
        agora = agora_utc()
        with self._engine.begin() as db:
            db.execute(text(
                "UPDATE carga_execucao SET status = :status, finalizada_em = :agora, "
                "atualizada_em = :agora, duracao_ms = "
                "TIMESTAMPDIFF(MICROSECOND, iniciada_em, :agora) DIV 1000, "
                "etapas_ok = :ok, etapas_alerta = :alerta, etapas_falha = :falha, "
                "mensagem_erro = :mensagem WHERE id = :id"
            ), {
                "id": carga_id, "status": status, "agora": agora, "ok": ok,
                "alerta": alerta, "falha": falha, "mensagem": mensagem,
            })

    def falha_antes_das_etapas(self, carga_id: str, erro: str) -> None:
        self.finalizar(carga_id, "FALHA", erro, 0, 0, 0)

    def em_andamento(self) -> dict | None:
        with self._engine.connect() as db:
            row = db.execute(text(
                "SELECT id, tipo, status, criada_em FROM carga_execucao "
                "WHERE status IN ('PENDENTE', 'EXECUTANDO') ORDER BY criada_em DESC LIMIT 1"
            )).mappings().first()
        return _row(row) if row else None

    def obter(self, carga_id: str) -> dict | None:
        with self._engine.connect() as db:
            row = db.execute(text("SELECT * FROM carga_execucao WHERE id = :id"),
                             {"id": carga_id}).mappings().first()
            if not row:
                return None
            etapas = db.execute(text(
                "SELECT etapa, ordem, status, iniciada_em, finalizada_em, duracao_ms, "
                "metricas_json, alertas_json, erros_json FROM carga_etapa "
                "WHERE execucao_id = :id ORDER BY ordem"
            ), {"id": carga_id}).mappings().all()
            arquivos = db.execute(text(
                "SELECT fonte, competencia, arquivo, etag, linhas_carregadas, status "
                "FROM etl_execucao WHERE carga_execucao_id = :id ORDER BY id"
            ), {"id": carga_id}).mappings().all()
        resultado = _execucao(row)
        resultado["etapas"] = [_etapa(e) for e in etapas]
        resultado["arquivos"] = [_row(a) for a in arquivos]
        return resultado

    def listar(self, limite: int = 50, status: str | None = None) -> list[dict]:
        limite = max(1, min(int(limite), 200))
        clausula = " WHERE status = :status" if status else ""
        params = {"limite": limite}
        if status:
            params["status"] = status
        with self._engine.connect() as db:
            rows = db.execute(text(
                "SELECT * FROM carga_execucao" + clausula +
                " ORDER BY criada_em DESC LIMIT :limite"
            ), params).mappings().all()
        return [_execucao(row) for row in rows]

    def ultimas(self) -> list[dict]:
        with self._engine.connect() as db:
            rows = db.execute(text("SELECT * FROM vw_carga_ultima ORDER BY etapa")).mappings().all()
        return [_row(row) for row in rows]


def _json(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False, default=_default_json)


def _default_json(valor):
    if hasattr(valor, "isoformat"):
        return valor.isoformat()
    return str(valor)


def _row(row) -> dict:
    return {
        k: v.isoformat(sep=" ") if isinstance(v, datetime)
        else v.isoformat() if isinstance(v, date)
        else v
        for k, v in row.items()
    }


def _decodificar(valor):
    if isinstance(valor, str):
        try:
            return json.loads(valor)
        except ValueError:
            return valor
    return valor


def _execucao(row) -> dict:
    dados = _row(row)
    dados["parametros"] = _decodificar(dados.pop("parametros_json", None))
    return dados


def _etapa(row) -> dict:
    dados = _row(row)
    dados["metricas"] = _decodificar(dados.pop("metricas_json", None)) or {}
    dados["alertas"] = _decodificar(dados.pop("alertas_json", None)) or []
    dados["erros"] = _decodificar(dados.pop("erros_json", None)) or []
    return dados
