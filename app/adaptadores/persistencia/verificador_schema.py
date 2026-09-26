"""Confere que as tabelas existem antes de comecar a carga.

Sem isso, a primeira consulta estoura um traceback de SQLAlchemy que nao diz
o que fazer. O schema e criado por `infra-b3-ecossytem/mysql-init`, que o
MySQL so executa na primeira criacao do volume - entao banco que ja existia
antes das tabelas da CVM simplesmente nao as tem (infra#ISS-03), e esse e o
modo de falha mais provavel na pratica.
"""

from __future__ import annotations

from collections.abc import Sequence
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


class VerificadorDeSchema:
    def __init__(self, tabelas: Sequence[str] = TABELAS_OBRIGATORIAS):
        self._tabelas = tuple(tabelas)

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

    @staticmethod
    def _mensagem(faltando: Sequence[str], nome_do_banco: str) -> str:
        return "\n".join(
            [
                f"O banco '{nome_do_banco}' nao tem {len(faltando)} tabela(s) "
                "necessaria(s):",
                *(f"  - {t}" for t in faltando),
                "",
                "O schema fica em infra-b3-ecossytem/mysql-init/1 - schema.sql, e o",
                "MySQL so executa esse diretorio na PRIMEIRA criacao do volume. Um",
                "banco criado antes destas tabelas nao as recebe sozinho.",
                "",
                "Aplicar sem perder dado (o script e todo CREATE TABLE IF NOT EXISTS,",
                "entao nao mexe no que ja existe):",
                "",
                "  docker exec -i mysql mysql -uspring -pspring123 minha_base \\",
                "      < 'infra-b3-ecossytem/mysql-init/1 - schema.sql'",
                "",
                "Ou recriar o volume do zero, o que APAGA historico_acoes,",
                "insight_acao e serie_historica:",
                "",
                "  docker compose down && docker volume rm infra-b3-ecossytem_mysql_data",
            ]
        )
