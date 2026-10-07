"""evento_corporativo (infra V16, plano LAC L2): leitura das evidencias ja
carregadas (cotacao_b3_diaria e cvm_composicao_capital) e gravacao dos
eventos inferidos. Nenhum download: tudo vem de cargas anteriores.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, BigInteger, Date, Numeric, String, UniqueConstraint, case, text
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Mapped, mapped_column

from app.adaptadores.persistencia.entidade.entidades import Base, MixinCarimbo
from app.dominio.evento_corporativo import (
    ORIGEM_INFERIDA,
    Composicao,
    EventoInferido,
    PregaoMarcado,
)


class EventoCorporativoEntity(MixinCarimbo, Base):
    """`fator_preco` e coluna gerada (1 / fator_acoes): fora do mapeamento,
    para o INSERT nunca tentar grava-la."""

    __tablename__ = "evento_corporativo"
    __table_args__ = (
        UniqueConstraint("simbolo", "data_efeito", "tipo", name="uq_evento_corporativo"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    simbolo: Mapped[str] = mapped_column(String(12), nullable=False)
    cnpj: Mapped[str | None] = mapped_column(String(20))
    data_efeito: Mapped[Date] = mapped_column(Date, nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    fator_acoes: Mapped[Numeric] = mapped_column(Numeric(20, 10), nullable=False)
    origem: Mapped[str] = mapped_column(String(30), nullable=False)
    confianca: Mapped[Numeric | None] = mapped_column(Numeric(5, 4))
    evidencia_json: Mapped[dict | None] = mapped_column(JSON)


class RepositorioEventoCorporativoSql:
    def pregoes(self, db: Any, anos: Sequence[int] | None) -> list[PregaoMarcado]:
        """So os pregoes com marca societaria (B, G ou X depois do E), com a
        marca e o fechamento do pregao anterior calculados no banco - a serie
        inteira (1,3 mi de linhas) nao precisa vir para a memoria."""
        filtro = ""
        parametros: dict = {}
        if anos:
            filtro = "AND YEAR(data_pregao) BETWEEN :inicio AND :fim"
            parametros = {"inicio": min(anos), "fim": max(anos)}
        linhas = db.execute(
            text(
                "SELECT simbolo, data_pregao, marca_ex, abertura, fechamento_anterior, "
                "marca_anterior FROM ("
                " SELECT simbolo, data_pregao, marca_ex, abertura,"
                " LAG(fechamento) OVER w AS fechamento_anterior,"
                " LAG(marca_ex) OVER w AS marca_anterior"
                " FROM cotacao_b3_diaria"
                " WINDOW w AS (PARTITION BY simbolo ORDER BY data_pregao)"
                ") serie "
                f"WHERE marca_ex REGEXP '^E.*[BGX]' {filtro} "
                "ORDER BY simbolo, data_pregao"
            ),
            parametros,
        )
        return [
            PregaoMarcado(simbolo, dia, marca, _decimal(anterior), _decimal(abertura), marca_ant)
            for simbolo, dia, marca, abertura, anterior, marca_ant in linhas
        ]

    def composicoes(self, db: Any) -> dict[str, list[Composicao]]:
        saida: dict[str, list[Composicao]] = defaultdict(list)
        for cnpj, dt_refer, total, ordinarias, preferenciais in db.execute(
            text(
                "SELECT cnpj, dt_refer, qt_acao_total, qt_acao_ordinaria, qt_acao_preferencial "
                "FROM cvm_composicao_capital WHERE tipo_doc = 'DFP'"
            )
        ):
            saida[cnpj].append(
                Composicao(dt_refer, int(total or 0), int(ordinarias or 0), int(preferenciais or 0))
            )
        return dict(saida)

    def cnpj_por_simbolo(self, db: Any) -> dict[str, str]:
        # Indicador primeiro (tickers antigos que sairam do FCA), cvm_ticker
        # por cima (cadastro atual).
        mapa = {
            s: c for s, c in db.execute(
                text("SELECT DISTINCT simbolo, cnpj FROM indicador_fundamentalista")
            )
        }
        mapa.update({s: c for s, c in db.execute(text("SELECT simbolo, cnpj FROM cvm_ticker"))})
        # Curadoria (V6) por ultimo: corrige o que o FCA traz errado (CSNA3).
        mapa.update({
            s: c for s, c in db.execute(
                text("SELECT simbolo, cnpj FROM ativo_identidade WHERE cnpj IS NOT NULL")
            )
        })
        return mapa

    def substituir(
        self, db: Any, eventos: Sequence[EventoInferido], anos: Sequence[int] | None
    ) -> int:
        """Troca os eventos INFERIDOS do escopo (anos pedidos, ou todos) pelos
        desta rodada: o que a regra deixou de reconhecer sai do banco.
        MANUAL nunca e apagado nem sobrescrito."""
        filtro = ""
        parametros: dict = {"origem": ORIGEM_INFERIDA}
        if anos:
            filtro = " AND YEAR(data_efeito) BETWEEN :inicio AND :fim"
            parametros.update(inicio=min(anos), fim=max(anos))
        db.execute(
            text(f"DELETE FROM evento_corporativo WHERE origem = :origem{filtro}"), parametros
        )
        if not eventos:
            return 0
        linhas = [
            {
                "simbolo": e.simbolo,
                "cnpj": e.cnpj,
                "data_efeito": e.data_efeito,
                "tipo": e.tipo,
                "fator_acoes": (
                    Decimal(e.fator_acoes.numerator) / Decimal(e.fator_acoes.denominator)
                ),
                "origem": ORIGEM_INFERIDA,
                "confianca": e.confianca,
                "evidencia_json": e.evidencia,
            }
            for e in eventos
        ]
        comando = mysql_insert(EventoCorporativoEntity).values(linhas)
        # Correcao MANUAL nunca e sobrescrita pela inferencia.
        manual = EventoCorporativoEntity.origem == "MANUAL"
        comando = comando.on_duplicate_key_update(
            **{
                coluna: case(
                    (manual, getattr(EventoCorporativoEntity, coluna)),
                    else_=comando.inserted[coluna],
                )
                for coluna in ("cnpj", "fator_acoes", "confianca", "evidencia_json")
            }
        )
        db.execute(comando)
        return len(linhas)


def _decimal(valor) -> Decimal | None:
    return None if valor is None else Decimal(str(valor))
