"""Cliente HTTP da CVM: retry so para falha transitoria."""

from __future__ import annotations

import logging
import urllib.error

import pytest

from app.adaptadores.cvm.cliente_http import ClienteHttpCvm
from app.excecoes.excecoes import FonteIndisponivel


class _RespostaFake:
    def __init__(self, conteudo: bytes = b"ok"):
        self.headers = {
            "ETag": '"v1"',
            "Last-Modified": "Wed, 07 Oct 2026 10:00:00 GMT",
            "Content-Length": str(len(conteudo)),
        }
        self._conteudo = conteudo

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._conteudo


def _erro_http(codigo: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://dados.cvm.gov.br/arquivo.zip",
        codigo,
        f"HTTP {codigo}",
        hdrs={},
        fp=None,
    )


def test_assinatura_repete_erro_transitorio_e_devolve_cabecalhos(monkeypatch, caplog):
    chamadas = []
    respostas = [_erro_http(520), _RespostaFake()]

    def urlopen(requisicao, timeout):
        chamadas.append((requisicao.get_method(), timeout))
        resposta = respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    esperas = []
    cliente = ClienteHttpCvm(
        "https://dados.cvm.gov.br",
        logging.getLogger("teste"),
        timeout=10,
        esperas_retry=(0,),
        dormir=esperas.append,
    )

    with caplog.at_level(logging.WARNING):
        assinatura = cliente.assinatura("arquivo.zip")

    assert assinatura.etag == '"v1"'
    assert assinatura.tamanho_bytes == 2
    assert chamadas == [("HEAD", 10), ("HEAD", 10)]
    assert esperas == []
    assert "nova tentativa" in caplog.text


def test_baixar_repete_timeout_e_devolve_conteudo(monkeypatch):
    respostas = [TimeoutError("tempo esgotado"), _RespostaFake(b"zip")]

    def urlopen(_requisicao, timeout):
        resposta = respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    esperas = []
    cliente = ClienteHttpCvm(
        "https://dados.cvm.gov.br",
        logging.getLogger("teste"),
        esperas_retry=(0,),
        dormir=esperas.append,
    )

    assert cliente.baixar("arquivo.zip") == b"zip"


def test_erro_404_nao_tem_retry(monkeypatch):
    chamadas = 0

    def urlopen(_requisicao, timeout):
        nonlocal chamadas
        chamadas += 1
        raise _erro_http(404)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    cliente = ClienteHttpCvm(
        "https://dados.cvm.gov.br",
        logging.getLogger("teste"),
        esperas_retry=(0, 0),
    )

    with pytest.raises(FonteIndisponivel, match="HEAD falhou"):
        cliente.assinatura("ausente.zip")

    assert chamadas == 1


def test_esgota_tentativas_transitorias(monkeypatch):
    chamadas = 0
    esperas = []

    def urlopen(_requisicao, timeout):
        nonlocal chamadas
        chamadas += 1
        raise urllib.error.URLError("fora do ar")

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    cliente = ClienteHttpCvm(
        "https://dados.cvm.gov.br",
        logging.getLogger("teste"),
        esperas_retry=(0, 0),
        dormir=esperas.append,
    )

    with pytest.raises(FonteIndisponivel, match="GET falhou"):
        cliente.baixar("arquivo.zip")

    assert chamadas == 3
