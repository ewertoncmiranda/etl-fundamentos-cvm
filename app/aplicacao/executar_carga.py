"""Orquestrador único para cargas ROTINA, COMPLETA e PARCIAL."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import date

from app.aplicacao.contexto_carga import definir_carga_atual, restaurar_carga_atual
from app.aplicacao.resumo_etapa import resumir_etapa

CATALOGO_ETAPAS = (
    "COTAHIST", "LIQUIDEZ", "PRONTIDAO", "QUALIDADE_OPCOES", "CONCILIACAO",
    "DFP", "TTM", "IPE", "DVA", "TESOURO", "CVM_CADASTRO", "IFDATA", "CVM_VLMO", "CVM_FRE", "CVM_CDA",
    "EVENTOS", "CHECAGENS",
)
ETAPAS_ROTINA = tuple(e for e in CATALOGO_ETAPAS if e != "EVENTOS")
TIPOS = {"ROTINA", "COMPLETA", "PARCIAL"}
SOLICITANTES = {"ROTINA_MANHA", "PAINEL", "API"}


class ErroRequisicao(ValueError):
    pass


@dataclass(frozen=True)
class PedidoCarga:
    tipo: str
    solicitada_por: str
    anos: tuple[int, ...]
    simbolos: tuple[str, ...]
    etapas: tuple[str, ...]
    forcar: bool

    def parametros(self) -> dict:
        return {
            "anos": list(self.anos), "simbolos": list(self.simbolos),
            "etapas": list(self.etapas), "forcar": self.forcar,
        }


def validar_pedido(dados: dict) -> PedidoCarga:
    if not isinstance(dados, dict):
        raise ErroRequisicao("O corpo deve ser um objeto JSON")
    tipo = str(dados.get("tipo", "")).upper()
    solicitante = str(dados.get("solicitada_por", "API")).upper()
    if tipo not in TIPOS:
        raise ErroRequisicao("tipo deve ser ROTINA, COMPLETA ou PARCIAL")
    if solicitante not in SOLICITANTES:
        raise ErroRequisicao("solicitada_por deve ser ROTINA_MANHA, PAINEL ou API")
    anos = _lista_anos(dados.get("anos", []))
    simbolos = _lista_simbolos(dados.get("simbolos", []))
    etapas = _lista_etapas(dados.get("etapas"))
    forcar = dados.get("forcar", False)
    if not isinstance(forcar, bool):
        raise ErroRequisicao("forcar deve ser booleano")
    if tipo == "PARCIAL" and not etapas:
        raise ErroRequisicao("PARCIAL exige pelo menos uma etapa")
    if tipo != "PARCIAL" and dados.get("etapas"):
        raise ErroRequisicao("etapas só pode ser informado para PARCIAL")
    return PedidoCarga(tipo, solicitante, tuple(anos), tuple(simbolos), tuple(etapas), forcar)


def _lista_anos(valor) -> list[int]:
    if valor is None:
        return []
    if not isinstance(valor, list) or len(valor) > 30:
        raise ErroRequisicao("anos deve ser uma lista com até 30 anos")
    ano_atual = date.today().year
    if any(
        not isinstance(a, int) or isinstance(a, bool) or a < 1900 or a > ano_atual
        for a in valor
    ):
        raise ErroRequisicao("anos contém ano inválido")
    return sorted(set(valor))


def _lista_simbolos(valor) -> list[str]:
    if valor is None:
        return []
    if not isinstance(valor, list) or len(valor) > 500:
        raise ErroRequisicao("simbolos deve ser uma lista com até 500 ativos")
    saida = []
    for item in valor:
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > 20:
            raise ErroRequisicao("símbolo inválido")
        saida.append(item.strip().upper())
    return sorted(set(saida))


def _lista_etapas(valor) -> list[str]:
    if valor is None:
        return []
    if not isinstance(valor, list) or not valor:
        raise ErroRequisicao("etapas deve ser uma lista não vazia")
    etapas = [str(x).upper() for x in valor]
    desconhecidas = sorted(set(etapas) - set(CATALOGO_ETAPAS))
    if desconhecidas:
        raise ErroRequisicao(f"etapa(s) não reconhecida(s): {', '.join(desconhecidas)}")
    return [e for e in CATALOGO_ETAPAS if e in set(etapas)]


class OrquestradorCargas:
    def __init__(self, repositorio, catalogo: dict[str, Callable], versao: str | None = None):
        self._repo = repositorio
        self._catalogo = catalogo
        self._versao = versao

    def disparar(self, dados: dict) -> tuple[int, dict]:
        pedido = validar_pedido(dados)
        carga_id = str(uuid.uuid4())
        pronto = threading.Event()
        resposta: dict = {}
        thread = threading.Thread(
            target=self._executar_thread,
            args=(carga_id, pedido, pronto, resposta),
            name=f"carga-{carga_id[:8]}", daemon=True,
        )
        thread.start()
        if not pronto.wait(timeout=60):
            return 503, {"erro": "Não foi possível iniciar a carga dentro do prazo"}
        return resposta["status"], resposta["corpo"]

    def _executar_thread(self, carga_id, pedido, pronto, resposta) -> None:
        lock = None
        token = None
        aceito = False
        try:
            lock = self._repo.adquirir_lock()
            if lock is None:
                atual = None
                for _ in range(10):
                    atual = self._repo.em_andamento()
                    if atual:
                        break
                    time.sleep(0.1)
                resposta.update(
                    status=409,
                    corpo={"execucao_em_andamento": atual["id"] if atual else None},
                )
                pronto.set()
                return
            anos_por_etapa = self._resolver_execucao(pedido)
            parametros = pedido.parametros()
            parametros["anos"] = sorted({ano for anos in anos_por_etapa.values() for ano in anos})
            parametros["etapas"] = [etapa for etapa in CATALOGO_ETAPAS if etapa in anos_por_etapa]
            self._repo.criar(carga_id, pedido.tipo, pedido.solicitada_por,
                             parametros, self._versao)
            self._repo.iniciar(carga_id)
            token = definir_carga_atual(carga_id)
            aceito = True
            resposta.update(status=202, corpo={"id": carga_id, "status": "PENDENTE"})
            pronto.set()
            etapas = [etapa for etapa in CATALOGO_ETAPAS if etapa in anos_por_etapa]
            resultados = []
            for ordem, etapa in enumerate(etapas, start=1):
                self._repo.iniciar_etapa(carga_id, ordem, etapa)
                erro = None
                resultado = None
                try:
                    resultado = self._catalogo[etapa](
                        anos_por_etapa[etapa], list(pedido.simbolos) or None, pedido.forcar
                    )
                except Exception as excecao:  # etapa isolada para as seguintes seguirem
                    erro = excecao
                resumo = resumir_etapa(etapa, resultado, erro)
                if resumo.alertas:
                    for alerta in resumo.alertas:
                        logging.getLogger("etl-fundamentos-cvm").warning("%s: %s", etapa, alerta)
                if resumo.erros:
                    for mensagem in resumo.erros:
                        logging.getLogger("etl-fundamentos-cvm").error("%s: %s", etapa, mensagem)
                self._repo.finalizar_etapa(carga_id, etapa, resumo)
                resultados.append(resumo.status)
            falhas = resultados.count("FALHA")
            alertas = resultados.count("ALERTA")
            ok = sum(1 for status in resultados if status in {"SUCESSO", "SEM_MUDANCA", "PULADA"})
            status = normalizar_status_final(resultados)
            self._repo.finalizar(carga_id, status, None, ok, alertas, falhas)
            logging.getLogger("etl-fundamentos-cvm").info(
                "Carga %s concluída: %s | ok=%d alerta=%d falha=%d",
                carga_id, status, ok, alertas, falhas,
            )
        except Exception as erro:
            if aceito:
                with suppress(Exception):
                    self._repo.falha_antes_das_etapas(carga_id, str(erro))
            else:
                resposta.update(status=503, corpo={"erro": str(erro)})
                pronto.set()
        finally:
            if token is not None:
                restaurar_carga_atual(token)
            if lock is not None:
                self._repo.liberar_lock(lock)

    def _resolver_execucao(self, pedido: PedidoCarga) -> dict[str, list[int]]:
        hoje = date.today().year
        if pedido.tipo == "ROTINA":
            return {
                etapa: sorted({hoje - 1, hoje})
                if etapa in {"DFP", "IPE", "DVA", "CVM_VLMO"} else [hoje]
                for etapa in ETAPAS_ROTINA
            }
        if pedido.tipo == "PARCIAL":
            anos = list(pedido.anos) or [hoje]
            etapas = pedido.etapas
        else:
            anos = list(pedido.anos) or list(range(hoje - 5, hoje + 1))
            etapas = CATALOGO_ETAPAS
        return {etapa: anos for etapa in etapas}


def normalizar_status_final(statuses: list[str]) -> str:
    falhas = statuses.count("FALHA")
    alertas = statuses.count("ALERTA")
    if not statuses or falhas == len(statuses):
        return "FALHA"
    if falhas:
        return "SUCESSO_PARCIAL"
    if alertas:
        return "SUCESSO_COM_ALERTA"
    return "SUCESSO"
