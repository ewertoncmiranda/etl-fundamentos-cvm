import http.client
import io
import json
import socket
import threading
from email.message import Message
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import app.servidor as servidor_mod
from app.aplicacao.executar_carga import ErroRequisicao
from app.servidor import _ler_corpo, criar_handler


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
    def __init__(self):
        self.recebidos = []

    def disparar(self, dados):
        self.recebidos.append(dados)
        return 202, {"id": "abc", "status": "PENDENTE", "tipo": dados["tipo"]}


def _servidor(token="segredo", orquestrador=None):
    servidor = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        criar_handler(orquestrador or OrquestradorFake(), RepositorioFake(), token),
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


def _post_cru(servidor, corpo_cru, headers_extra=b"Transfer-Encoding: chunked\r\n"):
    # Escreve a requisição à mão para controlar exatamente os bytes do chunked.
    with socket.create_connection(("127.0.0.1", servidor.server_port), timeout=5) as conexao:
        conexao.sendall(
            b"POST /cargas HTTP/1.1\r\nHost: x\r\nX-ETL-Token: segredo\r\n"
            + b"Content-Type: application/json\r\nConnection: close\r\n"
            + headers_extra + b"\r\n" + corpo_cru
        )
        resposta = http.client.HTTPResponse(conexao)
        resposta.begin()
        return resposta.status, json.loads(resposta.read())


def test_post_chunked_chega_ao_orquestrador():
    orquestrador = OrquestradorFake()
    servidor = _servidor(orquestrador=orquestrador)
    try:
        conexao = http.client.HTTPConnection("127.0.0.1", servidor.server_port, timeout=5)
        partes = iter([b'{"tipo": ', b'"ROTINA"}'])
        conexao.request(
            "POST", "/cargas", body=partes, encode_chunked=True,
            headers={"X-ETL-Token": "segredo", "Content-Type": "application/json"},
        )
        resposta = conexao.getresponse()
        assert resposta.status == 202
        assert json.loads(resposta.read())["tipo"] == "ROTINA"
        assert orquestrador.recebidos == [{"tipo": "ROTINA"}]
        conexao.close()
    finally:
        servidor.shutdown()
        servidor.server_close()


def test_post_chunked_cru_com_extensao_trailer_e_varias_codificacoes():
    orquestrador = OrquestradorFake()
    servidor = _servidor(orquestrador=orquestrador)
    try:
        corpo = b'5;ext=1\r\n{"tip\r\nd\r\no": "ROTINA"}\r\n0\r\nX-Fim: 1\r\n\r\n'
        status, resposta = _post_cru(
            servidor, corpo, b"Transfer-Encoding: gzip, Chunked\r\n"
        )
        assert status == 202
        assert resposta["tipo"] == "ROTINA"
        assert orquestrador.recebidos == [{"tipo": "ROTINA"}]
    finally:
        servidor.shutdown()
        servidor.server_close()


def test_post_chunked_tamanho_hex_invalido_retorna_400():
    servidor = _servidor()
    try:
        status, corpo = _post_cru(servidor, b"zz\r\n{}\r\n0\r\n\r\n")
        assert status == 400
        assert "chunk" in corpo["erro"]
    finally:
        servidor.shutdown()
        servidor.server_close()


def test_post_chunked_acima_do_limite_retorna_400(monkeypatch):
    monkeypatch.setattr(servidor_mod, "MAX_BODY", 10)
    servidor = _servidor()
    try:
        status, corpo = _post_cru(servidor, b'8\r\n{"tipo":\r\n8\r\n"ROTINA"\r\n0\r\n\r\n')
        assert status == 400
        assert corpo["erro"] == "tamanho do corpo inválido"
    finally:
        servidor.shutdown()
        servidor.server_close()


def test_post_sem_content_length_nem_chunked_retorna_400():
    servidor = _servidor()
    try:
        status, corpo = _post_cru(servidor, b"", b"")
        assert status == 400
        assert corpo["erro"] == "tamanho do corpo inválido"
    finally:
        servidor.shutdown()
        servidor.server_close()


def _headers(**valores):
    headers = Message()
    for nome, valor in valores.items():
        headers[nome.replace("_", "-")] = valor
    return headers


def test_ler_corpo_content_length_le_exatamente_o_tamanho():
    rfile = io.BytesIO(b'{"a": 1}resto')
    assert _ler_corpo(_headers(Content_Length="8"), rfile) == b'{"a": 1}'


@pytest.mark.parametrize(
    "corpo",
    [
        b"0\r\n\r\n",  # corpo vazio
        b"-1\r\nx\r\n0\r\n\r\n",  # hex inválido
        b"\r\n",  # linha de tamanho vazia
        b"5\r\nabc",  # chunk truncado
        b"3\r\nabcXY0\r\n\r\n",  # falta CRLF após os dados
        b"3\r\nabc\r\n0\r\n",  # trailer sem linha vazia final
    ],
)
def test_ler_corpo_chunked_invalido_gera_erro(corpo):
    with pytest.raises(ErroRequisicao):
        _ler_corpo(_headers(Transfer_Encoding="chunked"), io.BytesIO(corpo))


@pytest.mark.parametrize("tamanho", [None, "0", "abc", "1000001"])
def test_ler_corpo_content_length_invalido_gera_erro(tamanho):
    headers = _headers() if tamanho is None else _headers(Content_Length=tamanho)
    with pytest.raises(ErroRequisicao, match="tamanho do corpo inválido"):
        _ler_corpo(headers, io.BytesIO(b"{}"))
