"""Confere que as tabelas existem antes de comecar a carga.

Sem isso, a primeira consulta estoura um traceback de SQLAlchemy que nao diz
o que fazer. O schema e criado pela infra via Flyway/db-migrate; este ETL nao
cria nem atualiza tabelas, apenas valida se o banco esta no contrato esperado.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import text

from app.excecoes.excecoes import ErroPermanente

TABELAS_OBRIGATORIAS: tuple[str, ...] = (
    "ativo_monitorado",
    "cvm_empresa",
    "cvm_ticker",
    "cvm_composicao_capital",
    "fato_contabil",
    "indicador_fundamentalista",
    "etl_execucao",
)


# Colunas e tabelas da infra V16 (plano LAC) que o codigo grava. O ETL novo
# rodando num banco sem a V16 para aqui, com o que fazer, em vez de estourar
# um erro de SQL no meio da carga.
COLUNAS_V16_FUNDAMENTOS: dict[str, tuple[str, ...]] = {
    "fato_contabil": ("coluna_df",),
    "indicador_fundamentalista": (
        "ativo_total", "ativo_circulante", "passivo_circulante", "lucro_bruto",
    ),
    "provento_contabil": ("jcp", "dividendos", "por_acao"),
    "evento_corporativo": ("fator_acoes",),
}
COLUNAS_V16_COTAHIST: dict[str, tuple[str, ...]] = {
    "cotacao_b3_diaria": (
        "especificacao", "marca_ex", "fator_cotacao", "preco_medio",
        "melhor_oferta_compra", "melhor_oferta_venda",
    ),
}


class VerificadorDeSchema:
    def __init__(
        self,
        tabelas: Sequence[str] = TABELAS_OBRIGATORIAS,
        colunas: Mapping[str, Sequence[str]] | None = None,
    ):
        self._tabelas = tuple(tabelas)
        self._colunas = {t: tuple(c) for t, c in (colunas or {}).items()}

    def conferir(self, db: Any, nome_do_banco: str) -> None:
        """Compara em Python em vez de montar um IN na query.

        Sao poucas dezenas de tabelas no schema; simplicidade vale mais que a
        micro-otimizacao de filtrar no banco.
        """
        consulta = text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = :schema"
        )
        existentes = {
            linha[0] for linha in db.execute(consulta, {"schema": nome_do_banco})
        }
        faltando = [t for t in self._tabelas if t not in existentes]

        if faltando:
            raise ErroPermanente(self._mensagem(faltando, nome_do_banco))

        if self._colunas:
            colunas_faltando = self._colunas_faltando(db, nome_do_banco)
            if colunas_faltando:
                raise ErroPermanente(self._mensagem_colunas(colunas_faltando, nome_do_banco))

    def _colunas_faltando(self, db: Any, nome_do_banco: str) -> list[str]:
        consulta = text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = :schema"
        )
        existentes = {
            (linha[0], linha[1]) for linha in db.execute(consulta, {"schema": nome_do_banco})
        }
        return [
            f"{tabela}.{coluna}"
            for tabela, colunas in self._colunas.items()
            for coluna in colunas
            if (tabela, coluna) not in existentes
        ]

    @staticmethod
    def _mensagem_colunas(faltando: Sequence[str], nome_do_banco: str) -> str:
        return "\n".join(
            [
                f"O banco '{nome_do_banco}' nao tem {len(faltando)} coluna(s) que este ETL grava:",
                *(f"  - {c}" for c in faltando),
                "",
                "Essas colunas pertencem as migrations da infra (Flyway/db-migrate).",
                "Aplique as migrations pelo compose da infra antes de rodar o ETL:",
                "",
                "  docker compose -f docker-compose-local.yml up db-migrate",
            ]
        )

    @staticmethod
    def _mensagem(faltando: Sequence[str], nome_do_banco: str) -> str:
        return "\n".join(
            [
                f"O banco '{nome_do_banco}' nao tem {len(faltando)} tabela(s) "
                "necessaria(s):",
                *(f"  - {t}" for t in faltando),
                "",
                "O schema fica nas migrations do infra-b3-ecossytem e deve ser",
                "aplicado pela infra via Flyway/db-migrate. Este ETL nao executa",
                "migration nem cria tabelas automaticamente.",
                "",
                "Aplicar as migrations sem apagar dados:",
                "",
                "  docker compose -f docker-compose-local.yml up db-migrate",
                "",
                "Evite recriar o volume: isso apaga historico_acoes, insight_acao",
                "e serie_historica.",
                "",
            ]
        )
