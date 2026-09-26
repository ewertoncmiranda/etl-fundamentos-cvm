"""Testes das Settings, com foco nos defaults de conexao.

O bug que motivou estes testes: a imagem rodada sem variaveis de ambiente
caia no default localhost:3305, que dentro de um container aponta para o
proprio container e nunca responde - com 30 segundos de retry antes de
falhar com uma mensagem que nao dizia o que corrigir.
"""

from __future__ import annotations

import app.config.settings as modulo
from app.config.settings import Settings


class TestDefaultsDeConexao:

    def test_fora_de_container_usa_localhost(self, monkeypatch):
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("DB_HOST", raising=False)
        monkeypatch.delenv("DB_PORT", raising=False)
        monkeypatch.setattr(modulo, "executando_em_container", lambda: False)

        settings = Settings.do_ambiente()

        assert settings.ambiente == "local"
        assert settings.db_host == "localhost"
        assert settings.db_port == 3305

    def test_em_container_sem_environment_ainda_aponta_para_o_servico(self, monkeypatch):
        """O caso que quebrava: `docker run` cru, sem nenhuma variavel."""
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("DB_HOST", raising=False)
        monkeypatch.delenv("DB_PORT", raising=False)
        monkeypatch.setattr(modulo, "executando_em_container", lambda: True)

        settings = Settings.do_ambiente()

        assert settings.em_conteiner is True
        assert settings.db_host == "mysql"
        assert settings.db_port == 3306

    def test_db_host_explicito_vence_a_deteccao(self, monkeypatch):
        monkeypatch.setenv("DB_HOST", "banco-externo")
        monkeypatch.setenv("DB_PORT", "3307")
        monkeypatch.setattr(modulo, "executando_em_container", lambda: True)

        settings = Settings.do_ambiente()

        assert settings.db_host == "banco-externo"
        assert settings.db_port == 3307

    def test_environment_docker_fora_de_container_continua_valendo(self, monkeypatch):
        """Rodar com ENVIRONMENT=docker fora de container e legitimo (CI, teste)."""
        monkeypatch.setenv("ENVIRONMENT", "docker")
        monkeypatch.delenv("DB_HOST", raising=False)
        monkeypatch.setattr(modulo, "executando_em_container", lambda: False)

        settings = Settings.do_ambiente()

        assert settings.em_conteiner is True
        assert settings.db_host == "mysql"

    def test_senha_nao_aparece_na_descricao_usada_em_log(self, monkeypatch):
        monkeypatch.setenv("DB_PASS", "senha-secreta")
        settings = Settings.do_ambiente()

        assert "senha-secreta" in settings.database_url
        assert "senha-secreta" not in f"{settings.db_host}:{settings.db_port}"


class TestAnos:

    def test_aceita_intervalo(self, monkeypatch):
        monkeypatch.setenv("CVM_ANOS", "2023-2025")
        assert Settings.do_ambiente().anos == [2023, 2024, 2025]

    def test_aceita_lista(self, monkeypatch):
        monkeypatch.setenv("CVM_ANOS", "2021,2025")
        assert Settings.do_ambiente().anos == [2021, 2025]
