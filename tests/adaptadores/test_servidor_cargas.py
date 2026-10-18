import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.servidor import criar_handler


class RepositorioFake:
    def em_andamento(self):
        return None

    def ultimas(self):
        return [{"etapa": "DFP", "ultimo_status": "SUCESSO"}]

    def listar(self, limite, status):
        return [{"limite": limite, "status": status}]

    def obter(self, carga_id):
        return {"id": carga_id} if carga_id == "12345678-1234-1234-1234-123456789abc" else None


class OrquestradorFake:
    def disparar(self, dados):
        return 202, {"id": "abc", "status": "PENDENTE", "tipo": dados["tipo"]}


def _servidor(token="segredo"):
    servidor = ThreadingHTTPServer(
        ("127.0.0.1", 0), criar_handler(OrquestradorFake(), RepositorioFake(), token)
    )
    thread = threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    return servidor


def _request(servidor, path, token=None, data=None):
    headers = {}
    if token:
        headers["X-ETL-Token"] = token
    body = None if data is None else json.dumps(data).encode()
    req = Request(f"http://127.0.0.1:{servidor.server_port}{path}", data=body, headers=headers)
    try:
        with urlopen(req) as resposta:
            return resposta.status, json.loads(resposta.read())
    except HTTPError as erro:
        return erro.code, json.loads(erro.read())


def test_api_exige_token_quando_configurado():
    servidor = _servidor()
    try:
        assert _request(servidor, "/saude")[0] == 401
        assert _request(servidor, "/saude", token="segredo")[0] == 200
    finally:
        servidor.shutdown()
        servidor.server_close()


def test_get_ultimas_e_post_cargas_seguem_contrato():
    servidor = _servidor()
    try:
        assert _request(servidor, "/cargas/ultimas", token="segredo")[1][0]["etapa"] == "DFP"
        status, corpo = _request(
            servidor, "/cargas", token="segredo", data={"tipo": "ROTINA"}
        )
        assert status == 202
        assert corpo == {"id": "abc", "status": "PENDENTE", "tipo": "ROTINA"}
    finally:
        servidor.shutdown()
        servidor.server_close()


def test_execucao_inexistente_retorna_404():
    servidor = _servidor()
    try:
        status, _ = _request(
            servidor, "/cargas/00000000-0000-0000-0000-000000000000", token="segredo"
        )
        assert status == 404
    finally:
        servidor.shutdown()
        servidor.server_close()
