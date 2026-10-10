"""ativo_liquidez_diaria (infra V23 + V24, Plano OPR): leitura do COTAHIST ja carregado e gravacao das
metricas. Nenhum download: tudo vem de `cotacao_b3_diaria`.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import bindparam, text

from app.dominio.liquidez import MetricaLiquidez, PregaoAtivo

COLUNAS = (
    "volume_financeiro_medio_21d", "volume_financeiro_medio_63d", "negocios_medio_63d",
    "presenca_63d", "spread_mediano_63d", "spread_estimado_63d", "atr14", "volatilidade_63d", "percentil_volatilidade",
    "dias_sem_preco_63d", "ajuste_serie", "versao_calculo",
)


class RepositorioLiquidezSql:
    def pregoes_mercado(self, db: Any, ate: date | None = None) -> list[date]:
        """Todos os pregoes do mercado (datas distintas do COTAHIST), crescente, ate `ate`."""
        filtro, parametros = ("WHERE data_pregao <= :ate", {"ate": ate}) if ate else ("", {})
        comando = text(
            "SELECT DISTINCT data_pregao "
            f"FROM cotacao_b3_diaria {filtro} "
            "ORDER BY data_pregao"
        )
        return [d for (d,) in db.execute(comando, parametros)]

    def ultima_data_calculada(self, db: Any) -> date | None:
        return db.execute(text("SELECT MAX(data_pregao) FROM ativo_liquidez_diaria")).scalar()

    def series(
        self, db: Any, de: date, ate: date, simbolos: Sequence[str] | None = None
    ) -> dict[str, list[PregaoAtivo]]:
        """Pregoes de cada ativo entre `de` e `ate` (inclusive), crescente por data."""
        filtro, parametros = "", {"de": de, "ate": ate}
        if simbolos:
            filtro = "AND simbolo IN :simbolos"
            parametros["simbolos"] = [s.upper() for s in simbolos]
        comando = text(
            "SELECT simbolo, data_pregao, abertura, maxima, minima, fechamento, preco_medio, "
            "melhor_oferta_compra, melhor_oferta_venda, volume_financeiro, numero_negocios "
            f"FROM cotacao_b3_diaria WHERE data_pregao BETWEEN :de AND :ate {filtro} "
            "ORDER BY simbolo, data_pregao"
        )
        if simbolos:
            comando = comando.bindparams(bindparam("simbolos", expanding=True))
        saida: dict[str, list[PregaoAtivo]] = defaultdict(list)
        for linha in db.execute(comando, parametros):
            simbolo, *campos = linha
            saida[simbolo].append(PregaoAtivo(*campos))
        return dict(saida)

    def gravar(self, db: Any, metricas: Sequence[MetricaLiquidez]) -> int:
        """Upsert por (simbolo, data_pregao): recarregar o mesmo pregao substitui, nao duplica."""
        if not metricas:
            return 0
        colunas = ("simbolo", "data_pregao", *COLUNAS, "motivos_ausencia_json")
        atualizar = ", ".join(f"{c} = VALUES({c})" for c in (*COLUNAS, "motivos_ausencia_json"))
        comando = text(
            f"INSERT INTO ativo_liquidez_diaria ({', '.join(colunas)}) "
            f"VALUES ({', '.join(':' + c for c in colunas)}) "
            f"ON DUPLICATE KEY UPDATE {atualizar}"
        )
        db.execute(comando, [
            {
                "simbolo": m.simbolo,
                "data_pregao": m.data_pregao,
                **{c: getattr(m, c) for c in COLUNAS},
                "motivos_ausencia_json": (
                    json.dumps(m.motivos_ausencia)
                    if m.motivos_ausencia
                    else None
                ),
            }
            for m in metricas
        ])
        return len(metricas)
