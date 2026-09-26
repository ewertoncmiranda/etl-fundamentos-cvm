"""Configuracao por variavel de ambiente.

Instanciada UMA vez, no main.py, e passada adiante. Nenhuma classe deste app
chama Settings() por conta propria - e o que evita a acoplagem escondida
catalogada em gerar-insights#ISS-10.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

AMBIENTES_CONTEINER = {"docker", "container", "compose"}


def carregar_env(raiz: Path | None = None) -> None:
    """Le o .env indicado por ENV_FILE. Chamado so pelo main."""
    arquivo = os.getenv("ENV_FILE", ".env.local")
    base = raiz or Path(__file__).resolve().parents[2]
    caminho = Path(arquivo)
    if not caminho.is_absolute():
        candidatos = [base / caminho, base / "env" / caminho.name]
        caminho = next((c for c in candidatos if c.exists()), candidatos[0])
    load_dotenv(caminho, override=False)


def _inteiro(nome: str, padrao: int) -> int:
    valor = os.getenv(nome)
    if valor is None or valor.strip() == "":
        return padrao
    try:
        return int(valor)
    except ValueError:
        return padrao


def _anos(valor: str) -> list[int]:
    """Aceita '2019-2025' ou '2023,2024,2025'."""
    valor = (valor or "").strip()
    if not valor:
        return []
    if "-" in valor and "," not in valor:
        inicio, _, fim = valor.partition("-")
        return list(range(int(inicio), int(fim) + 1))
    return [int(parte) for parte in valor.split(",") if parte.strip()]


@dataclass(frozen=True)
class Settings:
    ambiente: str = "local"
    db_driver: str = "mysql+pymysql"
    db_host: str = "localhost"
    db_port: int = 3305
    db_user: str = "spring"
    db_password: str = "spring123"
    db_name: str = "minha_base"

    localstack_endpoint: str = "http://localhost:4566"
    aws_region: str = "sa-east-1"
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    fila_fundamentos: str = "sqs-fundamentos-atualizados"

    cvm_base_url: str = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC"
    cvm_cache_dir: Path = Path("./cache")
    anos: list[int] = field(default_factory=list)

    log_level: str = "INFO"
    http_timeout: int = 180

    @property
    def em_conteiner(self) -> bool:
        return self.ambiente in AMBIENTES_CONTEINER

    @property
    def database_url(self) -> str:
        usuario = quote_plus(self.db_user)
        senha = quote_plus(self.db_password)
        return (
            f"{self.db_driver}://{usuario}:{senha}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @classmethod
    def do_ambiente(cls) -> Settings:
        ambiente = os.getenv("ENVIRONMENT", "local").lower()
        em_conteiner = ambiente in AMBIENTES_CONTEINER

        return cls(
            ambiente=ambiente,
            db_driver=os.getenv("DB_DRIVER", "mysql+pymysql"),
            db_host=os.getenv("DB_HOST", "mysql" if em_conteiner else "localhost"),
            db_port=_inteiro("DB_PORT", 3306 if em_conteiner else 3305),
            db_user=os.getenv("DB_USER", "spring"),
            db_password=os.getenv("DB_PASS", "spring123"),
            db_name=os.getenv("DB_NAME", "minha_base"),
            localstack_endpoint=os.getenv(
                "LOCALSTACK_ENDPOINT",
                "http://localstack:4566" if em_conteiner else "http://localhost:4566",
            ),
            aws_region=os.getenv("AWS_REGION", "sa-east-1"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
            fila_fundamentos=os.getenv("FUNDAMENTOS_QUEUE_NAME", "sqs-fundamentos-atualizados"),
            cvm_base_url=os.getenv(
                "CVM_BASE_URL", "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC"
            ),
            cvm_cache_dir=Path(
                os.getenv("CVM_CACHE_DIR", "/var/cache/cvm" if em_conteiner else "./cache")
            ),
            anos=_anos(os.getenv("CVM_ANOS", "2024-2025")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            http_timeout=_inteiro("HTTP_TIMEOUT", 180),
        )
