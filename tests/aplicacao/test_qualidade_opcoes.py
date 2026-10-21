from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date

from app.aplicacao.qualidade_opcoes import avaliar


class ResultadoFake:
    def __init__(self, scalar=None, mapping=None, rows=()):
        self._scalar = scalar
        self._mapping = mapping
        self._rows = list(rows)

    def scalar(self):
        return self._scalar

    def mappings(self):
        return self

    def one(self):
        return self._mapping

    def __iter__(self):
        return iter(self._rows)


class DbQualidadeFake:
    def execute(self, query, params=None):
        sql = str(query)
        if "SELECT MAX(data_pregao)" in sql:
            return ResultadoFake(scalar=date(2026, 10, 16))
        if "information_schema.columns" in sql:
            return ResultadoFake(scalar=1)
        if "COUNT(DISTINCT CASE WHEN status_validacao = 'VALIDA' THEN ativo_objeto" in sql:
            return ResultadoFake(mapping={
                "total": 2,
                "validos": 1,
                "legado": 0,
                "venc9999": 0,
                "ativos": 1,
            })
        if "GROUP BY status_validacao, motivo_rejeicao" in sql:
            return ResultadoFake(rows=[("INVALIDA", "strike_invalido", 1)])
        if "GROUP BY p ORDER BY n DESC" in sql:
            return ResultadoFake(rows=[("ABCD", 1)])
        if "GROUP BY ativo_objeto" in sql:
            return ResultadoFake(rows=[("PETR", 2, 1, 1, 25.0, 35.0)])
        raise AssertionError(f"Consulta inesperada no teste: {sql}")


def test_qualidade_inclui_cobertura_por_pregao_e_ativo_objeto():
    metricas = avaliar(DbQualidadeFake())

    assert metricas["dataPregao"] == "2026-10-16"
    assert metricas["pronto"] is True
    assert metricas["cadeiasPorAtivoObjeto"] == [{
        "ativoObjeto": "PETR",
        "total": 2,
        "validas": 1,
        "invalidas": 1,
        "vencimentos": 1,
        "precoExercicioMinimo": "25.0",
        "precoExercicioMaximo": "35.0",
    }]
    assert metricas["motivosPrincipais"] == [{
        "status": "INVALIDA", "motivo": "strike_invalido", "registros": 1,
    }]


def test_consulta_real_de_cadeias_ordena_total_e_desempata_por_ativo():
    # Executa o SQL produzido por avaliar, não uma cópia, com dados sintéticos.
    # Sem conexão com MySQL, rede ou persistência em disco.
    with closing(sqlite3.connect(":memory:")) as conexao:
        conexao.execute("""
            CREATE TABLE opcao_b3_diaria (
                data_pregao TEXT, ativo_objeto TEXT, status_validacao TEXT,
                data_vencimento TEXT, preco_exercicio REAL
            )
        """)
        conexao.executemany("INSERT INTO opcao_b3_diaria VALUES (?, ?, ?, ?, ?)", [
            ("2026-10-16", "VALE", "VALIDA", "2026-11-20", 60),
            ("2026-10-16", "VALE", "VALIDA", "2026-12-18", 65),
            ("2026-10-16", "VALE", "INVALIDA", "9999-12-31", -1),
            ("2026-10-16", "PETR", "VALIDA", "2026-11-20", 30),
            ("2026-10-16", "PETR", "INVALIDA", "9999-12-31", 0),
            ("2026-10-16", "ABCD", "INVALIDA", "9999-12-31", 0),
            ("2026-10-16", "ABCD", "INVALIDA", "9999-12-31", 0),
            ("2026-10-15", "ANTIGO", "VALIDA", "2026-11-20", 1),
            ("2026-10-16", None, "VALIDA", "2026-11-20", 1),
        ])

        class DbComAgregacaoReal(DbQualidadeFake):
            def execute(self, query, params=None):
                if "GROUP BY ativo_objeto" in str(query):
                    return ResultadoFake(rows=conexao.execute(
                        str(query), {"d": params["d"].isoformat()}
                    ).fetchall())
                return super().execute(query, params)

        cadeias = avaliar(DbComAgregacaoReal())["cadeiasPorAtivoObjeto"]

    assert [c["ativoObjeto"] for c in cadeias] == ["VALE", "ABCD", "PETR"]
    assert [c["total"] for c in cadeias] == [3, 2, 2]
    assert cadeias[0]["validas"] == 2
    assert cadeias[0]["invalidas"] == 1
    assert cadeias[0]["vencimentos"] == 2
    assert cadeias[0]["precoExercicioMinimo"] == "60.0"
    assert cadeias[0]["precoExercicioMaximo"] == "65.0"
    assert cadeias[1]["validas"] == 0
    assert cadeias[1]["precoExercicioMinimo"] is None
    assert cadeias[1]["precoExercicioMaximo"] is None
