from __future__ import annotations

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
