"""Leitura de vw_conciliacao_preco (infra V15)."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text

from app.dominio.conciliacao import FONTE_CONCILIACAO, PENDENTE, LinhaConciliacao

VIEW = "vw_conciliacao_preco"


class RepositorioConciliacaoSql:
    def disponivel(self, db: Any) -> bool:
        return bool(
            db.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.views "
                    "WHERE table_schema = DATABASE() AND table_name = :view"
                ),
                {"view": VIEW},
            ).scalar()
        )

    def pregoes_a_conciliar(self, db: Any) -> list[date]:
        # Um pregao so entra quando nenhum par esta PENDENTE (o COTAHIST dele
        # ja chegou) e depois do ultimo ja conciliado - reprocessar um dia e
        # com --data.
        resultado = db.execute(
            text(
                f"SELECT data_pregao FROM {VIEW} "
                "GROUP BY data_pregao "
                "HAVING SUM(divergencia = :pendente) = 0 "
                "AND data_pregao > COALESCE("
                "  (SELECT MAX(STR_TO_DATE(competencia, '%Y-%m-%d')) FROM etl_execucao "
                "   WHERE fonte = :fonte), '1900-01-01') "
                "ORDER BY data_pregao"
            ),
            {"pendente": PENDENTE, "fonte": FONTE_CONCILIACAO},
        )
        return [linha[0] for linha in resultado]

    def linhas(self, db: Any, data_pregao: date) -> list[LinhaConciliacao]:
        resultado = db.execute(
            text(
                "SELECT simbolo, data_pregao, divergencia, severidade, dif_fechamento_pct, "
                f"idade_dado_min FROM {VIEW} WHERE data_pregao = :dia ORDER BY simbolo"
            ),
            {"dia": data_pregao},
        )
        return [
            LinhaConciliacao(
                simbolo=linha[0],
                data_pregao=linha[1],
                divergencia=linha[2],
                severidade=linha[3],
                dif_fechamento_pct=linha[4],
                idade_dado_min=linha[5],
            )
            for linha in resultado
        ]
