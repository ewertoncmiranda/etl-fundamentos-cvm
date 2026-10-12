"""Checagens de qualidade de dados (TASK-39).

Seis regras que detectam anomalias nos dados gravados pelo ETL e registram
resultados em `checagem_dados` (infra V29). Nao travam a carga: ERRO indica
problema que compromete a leitura; AVISO e anomalia leve.

Se a tabela ainda nao existir no banco (ambiente sem V29), loga aviso e
retorna sem gravar — o ETL continua normalmente.
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

from sqlalchemy import text

_LOG = logging.getLogger("etl-fundamentos-cvm")

ERRO = "ERRO"
AVISO = "AVISO"

# --------------------------------------------------------------------------- #
# Checagem 1 — LUCRO_ZERO_COM_RECEITA                                         #
# --------------------------------------------------------------------------- #

TIPO_LUCRO_ZERO = "LUCRO_ZERO_COM_RECEITA"


def checar_lucro_zero_com_receita(db) -> list[dict]:
    """Empresa com receita > 0 e lucro_liquido = 0 exato. ERRO."""
    sql = text(
        """
        SELECT simbolo, periodo
        FROM indicador_fundamentalista
        WHERE receita_liquida > 0
          AND lucro_liquido = 0
        ORDER BY simbolo, periodo
        """
    )
    rows = db.execute(sql).fetchall()
    return [
        {
            "tipo": TIPO_LUCRO_ZERO,
            "simbolo": r.simbolo,
            "descricao": (
                f"Receita positiva no periodo {r.periodo} com lucro_liquido = 0 exato; "
                "possivel conta nao mapeada ou dado corrompido"
            ),
            "severidade": ERRO,
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# Checagem 2 — LPA_FORA_MEDIANA                                               #
# --------------------------------------------------------------------------- #

TIPO_LPA_MEDIANA = "LPA_FORA_MEDIANA"


def checar_lpa_fora_mediana(db) -> list[dict]:
    """LPA > 10x ou < 0.1x a mediana do universo (tipo_periodo='ANUAL'). AVISO."""
    sql = text(
        """
        SELECT simbolo, periodo, lpa
        FROM indicador_fundamentalista
        WHERE lpa IS NOT NULL AND tipo_periodo = 'ANUAL'
        ORDER BY simbolo, periodo
        """
    )
    rows = db.execute(sql).fetchall()
    if not rows:
        return []

    lpas = [float(r.lpa) for r in rows if r.lpa is not None]
    if len(lpas) < 3:
        return []

    mediana = statistics.median(lpas)
    if mediana == 0:
        return []

    limite_sup = 10.0 * abs(mediana)
    limite_inf = 0.1 * abs(mediana)

    achados = []
    for r in rows:
        lpa = float(r.lpa)
        if abs(lpa) > limite_sup or (lpa != 0 and abs(lpa) < limite_inf):
            achados.append(
                {
                    "tipo": TIPO_LPA_MEDIANA,
                    "simbolo": r.simbolo,
                    "descricao": (
                        f"LPA={lpa:.4f} no periodo {r.periodo} fora da faixa "
                        f"[{limite_inf:.4f}, {limite_sup:.4f}] (mediana={mediana:.4f}); "
                        "possivel inconsistencia no numero de acoes ou no lucro"
                    ),
                    "severidade": AVISO,
                }
            )
    return achados


# --------------------------------------------------------------------------- #
# Checagem 3 — BALANCO_SEM_DATA_ENTREGA                                       #
# --------------------------------------------------------------------------- #

TIPO_BALANCO_SEM_DATA = "BALANCO_SEM_DATA_ENTREGA"


def checar_balanco_sem_data_entrega(db) -> list[dict]:
    """Indicador sem data_entrega preenchida — fica fora do backtest. AVISO."""
    sql = text(
        """
        SELECT simbolo, periodo, tipo_periodo
        FROM indicador_fundamentalista
        WHERE data_entrega IS NULL
        ORDER BY simbolo, periodo
        """
    )
    rows = db.execute(sql).fetchall()
    return [
        {
            "tipo": TIPO_BALANCO_SEM_DATA,
            "simbolo": r.simbolo,
            "descricao": (
                f"Indicador do periodo {r.periodo} ({r.tipo_periodo}) sem data_entrega; "
                "sera excluido do backtest point-in-time"
            ),
            "severidade": AVISO,
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# Checagem 4 — SALTO_SEM_EVENTO                                               #
# --------------------------------------------------------------------------- #

TIPO_SALTO_SEM_EVENTO = "SALTO_SEM_EVENTO"


def checar_salto_sem_evento(db) -> list[dict]:
    """Cotacao sobe ou cai > 50 % num unico pregao sem evento corporativo. ERRO."""
    sql = text(
        """
        SELECT c.simbolo,
               c.data_pregao,
               prev.fechamento AS fech_anterior,
               c.fechamento    AS fech_atual,
               ROUND((c.fechamento - prev.fechamento) / prev.fechamento * 100, 2)
                   AS variacao_pct
        FROM cotacao_b3_diaria c
        JOIN cotacao_b3_diaria prev
            ON prev.simbolo = c.simbolo
        JOIN (
            SELECT simbolo,
                   data_pregao,
                   LAG(data_pregao) OVER (PARTITION BY simbolo ORDER BY data_pregao)
                       AS data_anterior
            FROM cotacao_b3_diaria
        ) par
            ON par.simbolo = c.simbolo
           AND par.data_pregao = c.data_pregao
           AND prev.data_pregao = par.data_anterior
        WHERE prev.fechamento > 0
          AND c.fechamento > 0
          AND ABS((c.fechamento - prev.fechamento) / prev.fechamento) > 0.50
          AND NOT EXISTS (
              SELECT 1 FROM evento_corporativo e
              WHERE e.simbolo = c.simbolo
                AND e.data_efeito = c.data_pregao
          )
        ORDER BY c.simbolo, c.data_pregao
        """
    )
    rows = db.execute(sql).fetchall()
    return [
        {
            "tipo": TIPO_SALTO_SEM_EVENTO,
            "simbolo": r.simbolo,
            "descricao": (
                f"Variacao de {r.variacao_pct}% no pregao {r.data_pregao} sem evento "
                f"corporativo registrado (anterior={float(r.fech_anterior):.4f}, "
                f"atual={float(r.fech_atual):.4f})"
            ),
            "severidade": ERRO,
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# Checagem 5 — PAPEL_SEM_CNPJ                                                 #
# --------------------------------------------------------------------------- #

TIPO_PAPEL_SEM_CNPJ = "PAPEL_SEM_CNPJ"


def checar_papel_sem_cnpj(db) -> list[dict]:
    """Ativo na ativo_identidade sem CNPJ preenchido. AVISO."""
    sql = text(
        """
        SELECT simbolo
        FROM ativo_identidade
        WHERE cnpj IS NULL
        ORDER BY simbolo
        """
    )
    rows = db.execute(sql).fetchall()
    return [
        {
            "tipo": TIPO_PAPEL_SEM_CNPJ,
            "simbolo": r.simbolo,
            "descricao": (
                f"Ativo {r.simbolo} cadastrado em ativo_identidade sem CNPJ; "
                "fundamentos e comunicados nao serao vinculados"
            ),
            "severidade": AVISO,
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# Checagem 6 — BRAPI_COTAHIST_DIVERGENCIA                                     #
# --------------------------------------------------------------------------- #

TIPO_BRAPI_DIVERGENCIA = "BRAPI_COTAHIST_DIVERGENCIA"


def checar_brapi_cotahist_divergencia(db) -> list[dict]:
    """Cotacao BRAPI difere > 5 % da cotacao COTAHIST para a mesma data/papel. AVISO.

    Usa a view vw_conciliacao_preco (infra V15). Se a view nao existir
    (ambiente sem V15), retorna lista vazia e loga aviso.
    """
    sql_check = text(
        "SELECT COUNT(*) FROM information_schema.views "
        "WHERE table_schema = DATABASE() "
        "AND table_name = 'vw_conciliacao_preco'"
    )
    existe = db.execute(sql_check).scalar()
    if not existe:
        _LOG.warning(
            "BRAPI_COTAHIST_DIVERGENCIA: view vw_conciliacao_preco nao existe "
            "(infra < V15); checagem ignorada"
        )
        return []

    sql = text(
        """
        SELECT simbolo, data_pregao, fech_brapi, fech_b3, dif_fechamento_pct
        FROM vw_conciliacao_preco
        WHERE fech_b3 IS NOT NULL
          AND fech_brapi IS NOT NULL
          AND ABS(dif_fechamento_pct) > 5
        ORDER BY simbolo, data_pregao
        """
    )
    rows = db.execute(sql).fetchall()
    return [
        {
            "tipo": TIPO_BRAPI_DIVERGENCIA,
            "simbolo": r.simbolo,
            "descricao": (
                f"Fechamento BRAPI={float(r.fech_brapi):.4f} difere "
                f"{float(r.dif_fechamento_pct):.2f}% do COTAHIST={float(r.fech_b3):.4f} "
                f"em {r.data_pregao}"
            ),
            "severidade": AVISO,
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# Persistencia                                                                 #
# --------------------------------------------------------------------------- #

_TODOS_OS_TIPOS = [
    TIPO_LUCRO_ZERO,
    TIPO_LPA_MEDIANA,
    TIPO_BALANCO_SEM_DATA,
    TIPO_SALTO_SEM_EVENTO,
    TIPO_PAPEL_SEM_CNPJ,
    TIPO_BRAPI_DIVERGENCIA,
]


def _tabela_existe(db) -> bool:
    sql = text(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = DATABASE() "
        "AND table_name = 'checagem_dados'"
    )
    return bool(db.execute(sql).scalar())


def marcar_resolvidos(db, tipo: str) -> int:
    """Marca como resolvidos todos os registros pendentes do tipo dado.

    Retorna a quantidade de linhas atualizadas.
    """
    sql = text(
        "UPDATE checagem_dados "
        "SET resolvido_em = NOW() "
        "WHERE tipo = :tipo AND resolvido_em IS NULL"
    )
    result = db.execute(sql, {"tipo": tipo})
    return result.rowcount


def _inserir_achados(db, achados: list[dict]) -> int:
    if not achados:
        return 0
    sql = text(
        "INSERT INTO checagem_dados (tipo, simbolo, descricao, severidade) "
        "VALUES (:tipo, :simbolo, :descricao, :severidade)"
    )
    db.execute(sql, achados)
    return len(achados)


_CHECAGENS = [
    checar_lucro_zero_com_receita,
    checar_lpa_fora_mediana,
    checar_balanco_sem_data_entrega,
    checar_salto_sem_evento,
    checar_papel_sem_cnpj,
    checar_brapi_cotahist_divergencia,
]

_TIPO_POR_FUNCAO: dict[Any, str] = {
    checar_lucro_zero_com_receita: TIPO_LUCRO_ZERO,
    checar_lpa_fora_mediana: TIPO_LPA_MEDIANA,
    checar_balanco_sem_data_entrega: TIPO_BALANCO_SEM_DATA,
    checar_salto_sem_evento: TIPO_SALTO_SEM_EVENTO,
    checar_papel_sem_cnpj: TIPO_PAPEL_SEM_CNPJ,
    checar_brapi_cotahist_divergencia: TIPO_BRAPI_DIVERGENCIA,
}


def executar_todas(db) -> dict[str, int]:
    """Executa as 6 checagens, marca pendentes como resolvidos e persiste.

    Retorna um dict {tipo: quantidade_gravada}.

    Se a tabela checagem_dados nao existir (ambiente sem V29), loga aviso
    e retorna dict vazio sem travar o ETL.
    """
    if not _tabela_existe(db):
        _LOG.warning(
            "checagem_dados: tabela nao encontrada (infra < V29); "
            "checagens de qualidade ignoradas"
        )
        return {}

    resultado: dict[str, int] = {}
    for fn in _CHECAGENS:
        tipo = _TIPO_POR_FUNCAO[fn]
        try:
            achados = fn(db)
            resolvidos = marcar_resolvidos(db, tipo)
            gravados = _inserir_achados(db, achados)
            resultado[tipo] = gravados
            if resolvidos or gravados:
                _LOG.info(
                    "Checagem %s: %d resolvido(s), %d novo(s)",
                    tipo, resolvidos, gravados,
                )
            else:
                _LOG.debug("Checagem %s: sem ocorrencias", tipo)
        except Exception as exc:  # noqa: BLE001
            _LOG.error("Checagem %s falhou: %s", tipo, exc, exc_info=True)
            resultado[tipo] = 0

    return resultado
