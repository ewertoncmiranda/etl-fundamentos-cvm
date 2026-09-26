"""Fabrica de sessao SQLAlchemy.

O construtor e barato de proposito: nao conecta, nao bloqueia, nao levanta.
Conectar e esperar o banco ficam em metodos separados, para o objeto poder
ser criado em teste sem MySQL por perto - ao contrario do repo irmao, onde
ConfigDatabase.__init__ bloqueia ate 30 s de rede.
"""

from __future__ import annotations

import time
from logging import Logger

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import executando_em_container
from app.excecoes.excecoes import ErroTransitorio


class ConfiguracaoDeBanco:
    def __init__(self, database_url: str, logger: Logger, descricao: str = ""):
        self._url = database_url
        self._logger = logger
        # host:port em texto, so para a mensagem de erro - a URL completa tem
        # senha e nao pode ir para o log
        self._descricao = descricao or "o banco configurado"
        self._engine: Engine | None = None
        self._fabrica: sessionmaker[Session] | None = None

    def conectar(self) -> None:
        self._engine = create_engine(
            self._url, pool_pre_ping=True, pool_recycle=3600, echo=False
        )
        self._fabrica = sessionmaker(
            bind=self._engine, autocommit=False, autoflush=False, class_=Session
        )

    def aguardar_banco(self, tentativas: int = 3, intervalo: int = 10) -> None:
        if self._engine is None:
            self.conectar()
        assert self._engine is not None  # conectar() sempre popula

        for tentativa in range(1, tentativas + 1):
            try:
                with self._engine.connect() as conexao:
                    conexao.execute(text("SELECT 1"))
                return
            except OperationalError as erro:
                if tentativa == tentativas:
                    raise ErroTransitorio(self._diagnostico(tentativas, erro)) from erro
                self._logger.warning(
                    "MySQL indisponivel (tentativa %d/%d); aguardando %ds",
                    tentativa,
                    tentativas,
                    intervalo,
                )
                time.sleep(intervalo)

    def _diagnostico(self, tentativas: int, erro: Exception) -> str:
        """Mensagem que diz o que corrigir, nao so que falhou.

        O caso mais comum e a imagem rodada sem as variaveis de ambiente: os
        defaults apontam para localhost, que dentro de um container e o
        proprio container.
        """
        linhas = [
            f"MySQL em {self._descricao} nao respondeu apos {tentativas} tentativas.",
            f"Causa: {erro}",
        ]

        if executando_em_container() and "localhost" in self._descricao:
            linhas += [
                "",
                "Dentro de um container, localhost e o proprio container - nunca",
                "vai haver MySQL ai. Provavelmente a imagem foi executada sem as",
                "variaveis de ambiente. Rode pelo compose:",
                "",
                "  docker compose --profile etl run --rm etl-fundamentos-cvm",
                "",
                "ou passe DB_HOST explicitamente:",
                "",
                "  docker run --rm --network <rede> -e DB_HOST=mysql \\",
                "      ewertonmiranda/etl-fundamentos-cvm",
            ]
        elif executando_em_container():
            linhas += [
                "",
                "Confira se o container esta na mesma rede do MySQL e se o servico",
                "ja passou pelo healthcheck.",
            ]

        return "\n".join(linhas)

    @property
    def fabrica_de_sessao(self):
        if self._fabrica is None:
            self.conectar()
        return self._fabrica
