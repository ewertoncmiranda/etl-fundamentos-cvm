"""Testes do adaptador SQS sem rede."""

from __future__ import annotations

import json
import logging

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
