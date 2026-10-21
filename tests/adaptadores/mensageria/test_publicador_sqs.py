"""Testes do adaptador SQS sem rede."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date
from decimal import Decimal

from app.adaptadores.mensageria.publicador_sqs import PublicadorSqs


class ClienteSqsFake:
    def __init__(self):
        self.mensagens: list[dict] = []

    def get_queue_url(self, QueueName):  # noqa: N802 - assinatura igual ao boto3
        return {"QueueUrl": f"https://sqs.local/{QueueName}"}

    def send_message(self, **kwargs):
        self.mensagens.append(kwargs)


def test_publica_fundamentos_com_schema_version_do_contrato():
    cliente = ClienteSqsFake()
    publicador = PublicadorSqs(cliente, "sqs-fundamentos-atualizados", logging.getLogger("teste"))

    publicador.publicar_fundamentos_atualizados(["WEGE3", "PETR4", "PETR4"])

    [mensagem] = cliente.mensagens
    payload = json.loads(mensagem["MessageBody"])
    assert payload == {
        "schemaVersion": "1.0",
        "evento": "FUNDAMENTOS_ATUALIZADOS",
        "simbolos": ["PETR4", "WEGE3"],
    }


def test_publica_comunicados_sem_sobrescrever_schema_version():
    cliente = ClienteSqsFake()
    publicador = PublicadorSqs(cliente, "sqs-comunicados-publicados", logging.getLogger("teste"))
    evento = {
        "schemaVersion": "1.0",
        "evento": "COMUNICADOS_PUBLICADOS",
        "simbolo": "PETR4",
        "protocolos": ["123"],
    }

    publicador.publicar_comunicados([evento])

    [mensagem] = cliente.mensagens
    assert json.loads(mensagem["MessageBody"]) == evento


# ──────────────────────────── publicar_series_historicas ───────────────────────


def _candle(dia: date, fechamento=Decimal("58.21")) -> dict:
    return {
        "data_pregao": dia,
        "fechamento": fechamento,
        "abertura": Decimal("58.10"),
        "maxima": Decimal("59.00"),
        "minima": Decimal("57.50"),
        "volume": 12345678,
    }


def test_series_historicas_schema_ctr02():
    """Payload deve seguir CTR-02: schemaVersion, dedupKey SHA-256 64 hex, results[0].data.historicalDataPrice."""
    cliente = ClienteSqsFake()
    pub = PublicadorSqs(cliente, "sqs-registrar-series-historicas", logging.getLogger("t"))
    dia = date(2026, 10, 20)

    pub.publicar_series_historicas("PETR4", [_candle(dia)])

    [msg] = cliente.mensagens
    payload = json.loads(msg["MessageBody"])
    assert payload["schemaVersion"] == "1.0"
    assert len(payload["dedupKey"]) == 64
    assert all(c in "0123456789abcdef" for c in payload["dedupKey"])
    [result] = payload["results"]
    assert result["symbol"] == "PETR4"
    [candle] = result["data"]["historicalDataPrice"]
    assert candle["close"] == 58.21
    assert candle["open"] == 58.10
    assert candle["high"] == 59.00
    assert candle["low"] == 57.50
    assert candle["volume"] == 12345678
    assert isinstance(candle["date"], int)


def test_series_historicas_epoch_brt():
    """date deve ser Unix epoch de 00:00 BRT (03:00 UTC) do pregao."""
    from datetime import datetime, timezone, timedelta

    cliente = ClienteSqsFake()
    pub = PublicadorSqs(cliente, "fila", logging.getLogger("t"))
    dia = date(2026, 10, 20)

    pub.publicar_series_historicas("PETR4", [_candle(dia)])

    payload = json.loads(cliente.mensagens[0]["MessageBody"])
    candle_date = payload["results"][0]["data"]["historicalDataPrice"][0]["date"]
    esperado = int(datetime(2026, 10, 20, tzinfo=timezone(timedelta(hours=-3))).timestamp())
    assert candle_date == esperado


def test_series_historicas_chunk_respeita_limite_sqs():
    """Historico longo deve gerar multiplas mensagens com chunks de _MAX_CANDLES_POR_CHUNK."""
    cliente = ClienteSqsFake()
    pub = PublicadorSqs(cliente, "fila", logging.getLogger("t"))
    max_chunk = PublicadorSqs._MAX_CANDLES_POR_CHUNK
    n_candles = max_chunk + 1  # deve gerar 2 mensagens
    candles = [_candle(date(2026, 1, i % 28 + 1)) for i in range(n_candles)]

    pub.publicar_series_historicas("PETR4", candles)

    assert len(cliente.mensagens) == 2
    payload_1 = json.loads(cliente.mensagens[0]["MessageBody"])
    payload_2 = json.loads(cliente.mensagens[1]["MessageBody"])
    assert len(payload_1["results"][0]["data"]["historicalDataPrice"]) == max_chunk
    assert len(payload_2["results"][0]["data"]["historicalDataPrice"]) == 1
    # dedup keys diferentes entre chunks
    assert payload_1["dedupKey"] != payload_2["dedupKey"]


def test_series_historicas_vazio_nao_publica():
    cliente = ClienteSqsFake()
    pub = PublicadorSqs(cliente, "fila", logging.getLogger("t"))
    pub.publicar_series_historicas("PETR4", [])
    assert cliente.mensagens == []


# ──────────────────────────── publicar_cotacoes_ativos ─────────────────────────


def test_cotacoes_ativos_schema_ctr01():
    """Payload deve seguir CTR-01: schemaVersion, dedupKey, symbol, regularMarketPrice, regularMarketTime."""
    cliente = ClienteSqsFake()
    pub = PublicadorSqs(cliente, "tratar-ativos", logging.getLogger("t"))
    dia = date(2026, 10, 20)

    pub.publicar_cotacoes_ativos([{
        "simbolo": "PETR4",
        "data_pregao": dia,
        "fechamento": Decimal("58.21"),
        "abertura": Decimal("58.10"),
        "maxima": Decimal("59.00"),
        "minima": Decimal("57.50"),
        "volume": 12345678,
    }])

    [msg] = cliente.mensagens
    payload = json.loads(msg["MessageBody"])
    assert payload["schemaVersion"] == "1.0"
    assert len(payload["dedupKey"]) == 64
    assert payload["symbol"] == "PETR4"
    assert payload["regularMarketPrice"] == 58.21
    assert "2026-10-20" in payload["regularMarketTime"]
    assert payload["regularMarketOpen"] == 58.10
    assert payload["regularMarketDayHigh"] == 59.00
    assert payload["regularMarketDayLow"] == 57.50
    assert payload["regularMarketVolume"] == 12345678


def test_cotacoes_ativos_dedup_key_por_simbolo_data():
    """dedupKey de (simbolo, data) distintos deve ser diferente; mesmo par deve ser igual."""
    cliente = ClienteSqsFake()
    pub = PublicadorSqs(cliente, "fila", logging.getLogger("t"))

    pub.publicar_cotacoes_ativos([
        {"simbolo": "PETR4", "data_pregao": date(2026, 10, 20), "fechamento": Decimal("58.21"),
         "abertura": None, "maxima": None, "minima": None, "volume": None},
        {"simbolo": "VALE3", "data_pregao": date(2026, 10, 20), "fechamento": Decimal("60.00"),
         "abertura": None, "maxima": None, "minima": None, "volume": None},
    ])
    pub.publicar_cotacoes_ativos([
        {"simbolo": "PETR4", "data_pregao": date(2026, 10, 20), "fechamento": Decimal("58.21"),
         "abertura": None, "maxima": None, "minima": None, "volume": None},
    ])

    keys = [json.loads(m["MessageBody"])["dedupKey"] for m in cliente.mensagens]
    assert keys[0] != keys[1]  # PETR4 vs VALE3
    assert keys[0] == keys[2]  # mesmo (PETR4, 2026-10-20)


def test_cotacoes_ativos_retorna_contagem():
    cliente = ClienteSqsFake()
    pub = PublicadorSqs(cliente, "fila", logging.getLogger("t"))

    n = pub.publicar_cotacoes_ativos([
        {"simbolo": "PETR4", "data_pregao": date(2026, 10, i), "fechamento": Decimal("58.21"),
         "abertura": None, "maxima": None, "minima": None, "volume": None}
        for i in range(1, 6)
    ])

    assert n == 5


def test_cotacoes_ativos_vazio_retorna_zero():
    cliente = ClienteSqsFake()
    pub = PublicadorSqs(cliente, "fila", logging.getLogger("t"))
    assert pub.publicar_cotacoes_ativos([]) == 0
    assert cliente.mensagens == []
