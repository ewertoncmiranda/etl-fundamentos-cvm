"""Servidor HTTP interno e start único del ETL."""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from app.adaptadores.persistencia.repositorio_carga import RepositorioCargaSql
from app.aplicacao.executar_carga import ErroRequisicao, OrquestradorCargas
from app.config.config_logger import configurar_logger
from app.config.database_config import ConfiguracaoDeBanco
from app.config.settings import Settings, carregar_env
from main import criar_catalogo_etapas

MAX_BODY = 1_000_000


def criar_handler(orquestrador, repositorio, token: str | None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ETL-Cargas/1.0"

        def do_GET(self):
            if not self._autorizado():
                return
            rota = urlparse(self.path)
            if rota.path == "/saude":
                try:
                    atual = repositorio.em_andamento()
                    self._json(200, {"status": "ok", "execucao_em_andamento": atual})
                except Exception:
                    self._json(503, {"status": "indisponivel"})
                return
            if rota.path == "/cargas/ultimas":
                self._responder(lambda: self._json(200, repositorio.ultimas()))
                return
            if rota.path == "/cargas":
                query = parse_qs(rota.query)
                limite = _int_query(query.get("limite", ["50"])[0], 50, 1, 200)
                status = query.get("status", [None])[0]
                self._responder(lambda: self._json(200, repositorio.listar(limite, status)))
                return
            encontrado = re.fullmatch(r"/cargas/([0-9a-fA-F-]{36})", rota.path)
            if encontrado:
                self._responder(lambda: self._buscar(encontrado.group(1)))
                return
            self._json(404, {"erro": "rota não encontrada"})

        def do_POST(self):
            if not self._autorizado():
                return
            if urlparse(self.path).path != "/cargas":
                self._json(404, {"erro": "rota não encontrada"})
                return
            try:
                tamanho = int(self.headers.get("Content-Length", "0"))
                if tamanho < 1 or tamanho > MAX_BODY:
                    raise ErroRequisicao("tamanho do corpo inválido")
                dados = json.loads(self.rfile.read(tamanho))
                status, corpo = orquestrador.disparar(dados)
                self._json(status, corpo)
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._json(400, {"erro": "JSON inválido"})
            except ErroRequisicao as erro:
                self._json(400, {"erro": str(erro)})
            except Exception:
                logging.getLogger("etl-fundamentos-cvm").exception("Falha ao aceitar carga")
                self._json(503, {"erro": "serviço de cargas indisponível"})

        def _buscar(self, carga_id):
            resultado = repositorio.obter(carga_id)
            if resultado is None:
                self._json(404, {"erro": "carga não encontrada"})
            else:
                self._json(200, resultado)

        def _responder(self, operacao):
            try:
                operacao()
            except Exception:
                logging.getLogger("etl-fundamentos-cvm").exception("Falha de leitura da API")
                self._json(503, {"erro": "serviço de cargas indisponível"})

        def _autorizado(self):
            if token is None or token == "":
                return True
            recebido = self.headers.get("X-ETL-Token", "")
            if hmac.compare_digest(recebido, token):
                return True
            self._json(401, {"erro": "não autorizado"})
            return False

        def _json(self, status, corpo):
            conteudo = json.dumps(corpo, ensure_ascii=False, default=_json_default).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(conteudo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(conteudo)

        def log_message(self, formato, *args):
            logging.getLogger("etl-fundamentos-cvm.http").info(
                "%s - %s", self.address_string(), formato % args
            )

    return Handler


def _json_default(valor):
    if hasattr(valor, "isoformat"):
        return valor.isoformat()
    return str(valor)


def _int_query(valor, padrao, minimo, maximo):
    try:
        return max(minimo, min(int(valor), maximo))
    except (TypeError, ValueError):
        return padrao


def criar_servidor(settings: Settings | None = None, logger=None):
    settings = settings or Settings.do_ambiente()
    logger = logger or logging.getLogger("etl-fundamentos-cvm")
    banco = ConfiguracaoDeBanco(
        settings.database_url, logger, f"{settings.db_host}:{settings.db_port}"
    )
    banco.aguardar_banco()
    repositorio = RepositorioCargaSql(banco.engine)
    repositorio.verificar_schema()
    lock = repositorio.adquirir_lock()
    if lock is None:
        raise RuntimeError("Outra instância do ETL já possui o lock de execução")
    try:
        interrompidas = repositorio.marcar_orfas_interrompidas()
    finally:
        repositorio.liberar_lock(lock)
    if interrompidas:
        logger.warning("Cargas órfãs marcadas como INTERROMPIDA: %d", interrompidas)
    versao = os.getenv("ETL_VERSAO")
    if versao and len(versao) > 40:
        logger.warning("ETL_VERSAO excede 40 caracteres; será truncada")
        versao = versao[:40]
    orquestrador = OrquestradorCargas(
        repositorio, criar_catalogo_etapas(settings, logger), versao
    )
    host = os.getenv("ETL_HTTP_HOST", "0.0.0.0")
    porta = _int_query(os.getenv("ETL_HTTP_PORT", "8080"), 8080, 1, 65535)
    servidor = ThreadingHTTPServer((host, porta), criar_handler(
        orquestrador, repositorio, os.getenv("ETL_TOKEN")
    ))
    servidor.daemon_threads = True
    return servidor


def main() -> int:
    carregar_env()
    settings = Settings.do_ambiente()
    logger = configurar_logger(settings.log_level)
    if sys.argv[1:]:
        logger.error("Argumentos CLI foram removidos; dispare cargas por POST /cargas")
        return 2
    servidor = criar_servidor(settings, logger)
    logger.info("Servidor de cargas ETL escutando em %s:%s", *servidor.server_address)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        logger.info("Encerrando servidor de cargas ETL")
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
