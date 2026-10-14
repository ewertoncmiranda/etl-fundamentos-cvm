"""Repositorio do mart de indicadores."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.adaptadores.persistencia.entidade.entidades import (
    IndicadorFundamentalistaEntity,
)
from app.adaptadores.persistencia.repositorios import RepositorioIndicadorSql


class _ResultadoFake:
    def __init__(self, entidades):
        self._entidades = entidades

    def scalars(self):
        return self

    def all(self):
        return self._entidades


class _DbFake:
    def __init__(self, entidades):
        self.entidades = entidades
        self.consulta = None

    def execute(self, consulta):
        self.consulta = consulta
        return _ResultadoFake(self.entidades)


def _indicador(simbolo: str, periodo: date, tipo_periodo: str = "ANUAL"):
    return IndicadorFundamentalistaEntity(
        simbolo=simbolo,
        cnpj="00.000.000/0001-00",
        periodo=periodo,
        tipo_periodo=tipo_periodo,
        tipo_doc="DFP",
        grupo="con",
        versao_cvm=1,
        plano_contas="GERAL",
        lpa=Decimal("1.23"),
        cobertura_json={"lpa": {"estrategia": "teste"}},
        fonte="CVM",
    )


def test_historico_de_indicadores_devolve_modelo_de_dominio():
    db = _DbFake([_indicador("WEGE3", date(2024, 12, 31))])

    historico = RepositorioIndicadorSql().historico(db, "wege3")

    assert len(historico) == 1
    assert historico[0].simbolo == "WEGE3"
    assert historico[0].periodo == date(2024, 12, 31)
    assert historico[0].lpa == Decimal("1.23")
    assert historico[0].cobertura["lpa"]["estrategia"] == "teste"


def test_historico_de_indicadores_filtra_tipo_periodo_e_limite():
    db = _DbFake([_indicador("WEGE3", date(2024, 12, 31), "TTM")])

    RepositorioIndicadorSql().historico(db, "wege3", tipo_periodo="TTM", limite=12)

    consulta_sql = str(db.consulta.compile(compile_kwargs={"literal_binds": True}))
    assert "WEGE3" in consulta_sql
    assert "TTM" in consulta_sql
    assert "LIMIT 12" in consulta_sql
    assert "ORDER BY" in consulta_sql
