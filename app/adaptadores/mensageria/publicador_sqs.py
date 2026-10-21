"""Publica eventos de carga no SQS.

Uma instancia por fila: sqs-fundamentos-atualizados (fundamentos),
sqs-comunicados-publicados (comunicados da base IPE) ou
sqs-registrar-series-historicas (trigger diario para o gerar-insights).

Falha em publicar nao derruba a carga: o dado ja esta no banco e o consumidor
pode ler de la. Por isso o erro e registrado e engolido de proposito.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from logging import Logger


class PublicadorSqs:
    def __init__(self, cliente_sqs, nome_da_fila: str, logger: Logger):
        self._cliente = cliente_sqs
        self._nome_da_fila = nome_da_fila
        self._logger = logger
        self._url: str | None = None

    def _garantir_fila(self) -> str | None:
        if self._url:
            return self._url
        try:
            self._url = self._cliente.get_queue_url(QueueName=self._nome_da_fila)["QueueUrl"]
        except Exception:
            try:
                self._url = self._cliente.create_queue(QueueName=self._nome_da_fila)["QueueUrl"]
            except Exception as erro:
                self._logger.error("Nao foi possivel obter a fila %s: %s", self._nome_da_fila, erro)
                return None
        return self._url

    def publicar_fundamentos_atualizados(self, simbolos: Sequence[str]) -> None:
        if not simbolos:
            return

        url = self._garantir_fila()
        if not url:
            return

        corpo = json.dumps(
            {
                "schemaVersion": "1.0",
                "evento": "FUNDAMENTOS_ATUALIZADOS",
                "simbolos": sorted(set(simbolos)),
            }
        )
        try:
            self._cliente.send_message(QueueUrl=url, MessageBody=corpo)
            self._logger.info("Publicado evento de fundamentos para %d simbolos", len(simbolos))
        except Exception as erro:
            # O dado ja esta no banco; o evento e so uma notificacao.
            self._logger.error("Falha ao publicar evento (dado ja persistido): %s", erro)

    # SQS limit is 256KB; each candle is ~100 bytes so chunks of 1500 stay safely under
    _MAX_CANDLES_POR_CHUNK = 1500

    def publicar_series_historicas(self, simbolo: str, candles: Sequence[dict]) -> None:
        """Publica serie historica de um simbolo em sqs-registrar-series-historicas.

        Cada dict em candles deve ter: data_pregao (date), fechamento (Decimal),
        e opcionais abertura, maxima, minima, volume.

        Contrato CTR-02 (contracts/series_historicas.schema.json, schemaVersion 1.0).
        Historicos longos sao divididos em chunks de _MAX_CANDLES_POR_CHUNK para
        respeitar o limite de 256KB por mensagem SQS.
        """
        if not candles:
            return

        url = self._garantir_fila()
        if not url:
            return

        BRT = timezone(timedelta(hours=-3))
        historico = []
        for c in candles:
            dp: date = c["data_pregao"]
            epoch = int(datetime(dp.year, dp.month, dp.day, tzinfo=BRT).timestamp())
            entrada: dict = {"date": epoch, "close": float(c["fechamento"])}
            if c.get("abertura") is not None:
                entrada["open"] = float(c["abertura"])
            if c.get("maxima") is not None:
                entrada["high"] = float(c["maxima"])
            if c.get("minima") is not None:
                entrada["low"] = float(c["minima"])
            if c.get("volume") is not None:
                entrada["volume"] = int(c["volume"])
            historico.append(entrada)

        chunks = [
            historico[i : i + self._MAX_CANDLES_POR_CHUNK]
            for i in range(0, len(historico), self._MAX_CANDLES_POR_CHUNK)
        ]
        enviados = 0
        for chunk in chunks:
            results = [{"symbol": simbolo, "data": {"historicalDataPrice": chunk}}]
            dedup_key = hashlib.sha256(
                json.dumps(results, sort_keys=True).encode()
            ).hexdigest()
            corpo = json.dumps({"schemaVersion": "1.0", "dedupKey": dedup_key, "results": results})
            try:
                self._cliente.send_message(QueueUrl=url, MessageBody=corpo)
                enviados += len(chunk)
            except Exception as erro:
                self._logger.error(
                    "Falha ao publicar chunk de serie historica de %s (dado ja persistido): %s",
                    simbolo, erro,
                )
        if enviados:
            self._logger.debug(
                "Publicado serie historica de %s (%d candles em %d mensagem(ns))",
                simbolo, enviados, len(chunks),
            )

    def publicar_cotacoes_ativos(self, candles_por_dia: Sequence[dict]) -> int:
        """Publica snapshots de fechamento em tratar-ativos (CTR-01 / ativos.schema.json).

        Cada dict deve ter: simbolo (str), data_pregao (date), fechamento (Decimal),
        e opcionais abertura, maxima, minima, volume.

        O regularMarketTime e definido como 18:00 BRT (21:00 UTC) do dia de pregao.
        Retorna o numero de mensagens publicadas com sucesso.
        """
        if not candles_por_dia:
            return 0

        url = self._garantir_fila()
        if not url:
            return 0

        BRT = timezone(timedelta(hours=-3))
        enviados = 0
        for candle in candles_por_dia:
            dp: date = candle["data_pregao"]
            market_time = datetime(dp.year, dp.month, dp.day, 18, 0, 0, tzinfo=BRT).isoformat()
            simbolo: str = candle["simbolo"]
            preco = float(candle["fechamento"])
            dedup_key = hashlib.sha256(
                f"{simbolo}:{dp.isoformat()}".encode()
            ).hexdigest()
            corpo: dict = {
                "schemaVersion": "1.0",
                "dedupKey": dedup_key,
                "symbol": simbolo,
                "regularMarketPrice": preco,
                "regularMarketTime": market_time,
            }
            if candle.get("abertura") is not None:
                corpo["regularMarketOpen"] = float(candle["abertura"])
            if candle.get("maxima") is not None:
                corpo["regularMarketDayHigh"] = float(candle["maxima"])
            if candle.get("minima") is not None:
                corpo["regularMarketDayLow"] = float(candle["minima"])
            if candle.get("volume") is not None:
                corpo["regularMarketVolume"] = int(candle["volume"])
            try:
                self._cliente.send_message(QueueUrl=url, MessageBody=json.dumps(corpo))
                enviados += 1
            except Exception as erro:
                self._logger.error(
                    "Falha ao publicar cotacao de %s em %s: %s", simbolo, dp, erro
                )
        return enviados

    def publicar_comunicados(self, eventos: Sequence[dict]) -> None:
        if not eventos:
            return

        url = self._garantir_fila()
        if not url:
            return

        publicados = 0
        for evento in eventos:
            try:
                self._cliente.send_message(
                    QueueUrl=url,
                    MessageBody=json.dumps(evento, default=str),
                )
                publicados += 1
            except Exception as erro:
                self._logger.error(
                    "Falha ao publicar comunicados de %s (dado ja persistido): %s",
                    evento.get("simbolo"),
                    erro,
                )
        self._logger.info("Publicados eventos de comunicados para %d ticker(s)", publicados)
