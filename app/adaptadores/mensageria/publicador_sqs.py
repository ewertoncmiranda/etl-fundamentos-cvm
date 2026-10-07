"""Publica eventos de carga no SQS.

Uma instancia por fila: sqs-fundamentos-atualizados (fundamentos) ou
sqs-comunicados-publicados (comunicados da base IPE).

Falha em publicar nao derruba a carga: o dado ja esta no banco e o consumidor
pode ler de la. Por isso o erro e registrado e engolido de proposito.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
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

        corpo = json.dumps({"schemaVersion": "1.0", "evento": "FUNDAMENTOS_ATUALIZADOS", "simbolos": sorted(set(simbolos))})
        try:
            self._cliente.send_message(QueueUrl=url, MessageBody=corpo)
            self._logger.info("Publicado evento de fundamentos para %d simbolos", len(simbolos))
        except Exception as erro:
            # O dado ja esta no banco; o evento e so uma notificacao.
            self._logger.error("Falha ao publicar evento (dado ja persistido): %s", erro)

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
                    QueueUrl=url, MessageBody=json.dumps({**evento, "schemaVersion": "1.0"}, default=str)
                )
                publicados += 1
            except Exception as erro:
                self._logger.error(
                    "Falha ao publicar comunicados de %s (dado ja persistido): %s",
                    evento.get("simbolo"),
                    erro,
                )
        self._logger.info("Publicados eventos de comunicados para %d ticker(s)", publicados)
