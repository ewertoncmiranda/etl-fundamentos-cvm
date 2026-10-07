"""Caso de uso de comunicados, com fakes de todas as portas."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date

import pytest

from app.adaptadores.cvm.cliente_http import Assinatura
from app.aplicacao.carregar_comunicados import CarregarComunicados, montar_eventos
from app.dominio.comunicado import FATO_RELEVANTE, PROVENTOS, Comunicado
from app.excecoes.excecoes import ErroPermanente, FonteIndisponivel

CNPJ_PETROBRAS = "33.000.167/0001-01"
CNPJ_WEG = "84.429.695/0001-11"


def comunicado(protocolo: str, cnpj: str = CNPJ_PETROBRAS, **outros) -> Comunicado:
    base = dict(
        protocolo_cvm=protocolo,
        versao=1,
        cnpj=cnpj,
        categoria=FATO_RELEVANTE,
        categoria_original="Fato Relevante",
        data_entrega=date(2026, 9, 19),
        link_download=f"https://x/?numProtocolo={protocolo}",
    )
    base.update(outros)
    return Comunicado(**base)


class _UnidadeDeTrabalhoFake:
    @contextmanager
    def transacao(self):
        yield object()


class _FonteFake:
    def __init__(self, comunicados, assinatura=None, erro_no_ano=None):
        self._comunicados = comunicados
        self._assinatura = assinatura or Assinatura("etag-novo", None, 100)
        self._erro_no_ano = erro_no_ano
        self.pedidos: list[tuple[int, set[str], set[str]]] = []

    def assinatura(self, ano):
        if ano == self._erro_no_ano:
            raise FonteIndisponivel("CVM fora do ar")
        return self._assinatura

    def comunicados(self, ano, cnpjs, categorias):
        self.pedidos.append((ano, set(cnpjs), set(categorias)))
        return list(self._comunicados)


class _UniversoFake:
    def __init__(self, simbolos):
        self._simbolos = simbolos

    def listar_simbolos_monitorados(self, db):
        return list(self._simbolos)


class _TickersFake:
    MAPA = {"PETR4": CNPJ_PETROBRAS, "PETR3": CNPJ_PETROBRAS, "WEGE3": CNPJ_WEG}

    def cnpjs_por_simbolo(self, db, simbolos):
        return {s: self.MAPA[s] for s in simbolos if s in self.MAPA}


class _RepositorioComunicadoFake:
    """Simula o banco: segunda gravacao do mesmo protocolo nao e novidade."""

    def __init__(self):
        self.versoes: dict[str, int] = {}

    def salvar(self, db, comunicados):
        novos = [
            c for c in comunicados if c.versao > self.versoes.get(c.protocolo_cvm, 0)
        ]
        self.versoes.update({c.protocolo_cvm: c.versao for c in novos})
        return novos


class _ExecucaoFake:
    def __init__(self, etag_anterior=None):
        self._etag_anterior = etag_anterior
        self.registros: list[dict] = []

    def etag_da_ultima_execucao(self, db, fonte, competencia, arquivo):
        return self._etag_anterior

    def registrar(self, db, **kwargs):
        self.registros.append(kwargs)


class _VerificadorFake:
    def __init__(self, faltando=None):
        self.faltando = faltando or []

    def conferir(self, db, nome_do_banco):
        if self.faltando:
            raise ErroPermanente(f"faltam tabelas: {', '.join(self.faltando)}")


class _PublicadorFake:
    def __init__(self):
        self.eventos: list[dict] = []

    def publicar_comunicados(self, eventos):
        self.eventos.extend(eventos)


def montar(
    fonte,
    simbolos=("PETR4",),
    repositorio=None,
    execucao=None,
    publicador=None,
    verificador=None,
):
    return CarregarComunicados(
        fonte=fonte,
        unidade_de_trabalho=_UnidadeDeTrabalhoFake(),
        repositorio_universo=_UniversoFake(simbolos),
        consulta_de_tickers=_TickersFake(),
        repositorio_comunicado=repositorio or _RepositorioComunicadoFake(),
        repositorio_execucao=execucao or _ExecucaoFake(),
        verificador_de_schema=verificador or _VerificadorFake(),
        nome_do_banco="minha_base",
        publicador=publicador or _PublicadorFake(),
        logger=logging.getLogger("teste"),
    )


class TestCarregarComunicados:

    def test_carga_grava_registra_execucao_e_publica_evento(self):
        execucao = _ExecucaoFake()
        publicador = _PublicadorFake()
        caso = montar(
            _FonteFake([comunicado("1"), comunicado("2", categoria=PROVENTOS)]),
            execucao=execucao,
            publicador=publicador,
        )

        resultado = caso.executar([2026])

        assert resultado.sucesso
        assert resultado.documentos_gravados == 2
        assert execucao.registros[-1]["status"] == "SUCESSO"
        assert execucao.registros[-1]["fonte"] == "CVM_IPE"
        assert execucao.registros[-1]["linhas_carregadas"] == 2
        [evento] = publicador.eventos
        assert evento["simbolo"] == "PETR4"
        assert evento["protocolos"] == ["1", "2"]
        assert evento["categorias"] == [FATO_RELEVANTE, PROVENTOS]

    def test_pede_a_fonte_so_os_cnpjs_do_universo(self):
        fonte = _FonteFake([])
        montar(fonte, simbolos=["PETR4", "WEGE3"]).executar([2026])

        assert fonte.pedidos[0][1] == {CNPJ_PETROBRAS, CNPJ_WEG}

    def test_segunda_execucao_forcada_nao_regrava_nem_republica(self):
        """Idempotencia: mesmo arquivo, mesmo banco -> nada novo."""
        repositorio = _RepositorioComunicadoFake()
        publicador = _PublicadorFake()
        fonte = _FonteFake([comunicado("1")])

        montar(fonte, repositorio=repositorio, publicador=publicador).executar([2026])
        segunda = montar(
            fonte, repositorio=repositorio, publicador=publicador
        ).executar([2026], forcar=True)

        assert segunda.documentos_lidos == 1
        assert segunda.documentos_gravados == 0
        assert len(publicador.eventos) == 1

    def test_etag_igual_pula_sem_baixar(self):
        fonte = _FonteFake([comunicado("1")], Assinatura("mesmo", None, 1))
        execucao = _ExecucaoFake(etag_anterior="mesmo")

        resultado = montar(fonte, execucao=execucao).executar([2026])

        assert resultado.anos_pulados == [2026]
        assert fonte.pedidos == []
        assert execucao.registros[-1]["status"] == "PULADO"

    def test_forcar_ignora_etag_igual(self):
        fonte = _FonteFake([comunicado("1")], Assinatura("mesmo", None, 1))

        resultado = montar(fonte, execucao=_ExecucaoFake("mesmo")).executar(
            [2026], forcar=True
        )

        assert resultado.anos_processados == [2026]

    def test_falha_num_ano_registra_erro_e_segue_os_outros(self):
        execucao = _ExecucaoFake()
        resultado = montar(
            _FonteFake([comunicado("1")], erro_no_ano=2025), execucao=execucao
        ).executar([2025, 2026])

        assert resultado.anos_processados == [2026]
        assert not resultado.sucesso
        assert any(r["status"] == "ERRO" for r in execucao.registros)

    def test_simbolo_sem_cnpj_em_cvm_ticker_nao_derruba(self):
        fonte = _FonteFake([comunicado("1")])
        resultado = montar(fonte, simbolos=["XPTO3"]).executar([2026])

        assert resultado.sucesso
        assert fonte.pedidos == []

    def test_schema_faltando_aborta_antes_de_baixar(self):
        fonte = _FonteFake([comunicado("1")])
        caso = montar(fonte, verificador=_VerificadorFake(["comunicado_cvm"]))

        with pytest.raises(ErroPermanente, match="comunicado_cvm"):
            caso.executar([2026])
        assert fonte.pedidos == []


class TestMontarEventos:

    def test_um_evento_por_ticker_monitorado_da_mesma_empresa(self):
        """PETR3 e PETR4 sao a mesma companhia: quem consome pensa em ticker."""
        eventos = montar_eventos(
            [comunicado("1")], {"PETR3": CNPJ_PETROBRAS, "PETR4": CNPJ_PETROBRAS}
        )

        assert [e["simbolo"] for e in eventos] == ["PETR3", "PETR4"]
        assert all(e["schemaVersion"] == "1.0" for e in eventos)

    def test_ticker_sem_novidade_nao_gera_evento(self):
        eventos = montar_eventos(
            [comunicado("1")], {"PETR4": CNPJ_PETROBRAS, "WEGE3": CNPJ_WEG}
        )

        assert [e["simbolo"] for e in eventos] == ["PETR4"]

    def test_data_entrega_maxima_no_evento(self):
        eventos = montar_eventos(
            [
                comunicado("1", data_entrega=date(2026, 9, 1)),
                comunicado("2", data_entrega=date(2026, 9, 19)),
            ],
            {"PETR4": CNPJ_PETROBRAS},
        )

        assert eventos[0]["dataEntregaMax"] == "2026-09-19"
