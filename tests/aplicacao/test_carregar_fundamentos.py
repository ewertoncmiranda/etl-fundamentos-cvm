"""Testes do caso de uso, com fakes de todas as portas.

Nenhum banco, nenhuma rede. Os fakes conformam aos Protocols das portas, que e
a diferenca em relacao ao repo irmao: se a porta mudar, o type check acusa.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date

import pytest

from app.adaptadores.cvm.cliente_http import Assinatura
from app.aplicacao.carregar_fundamentos import CarregarFundamentos
from app.dominio.calculo.calculadora_indicadores import CalculadoraIndicadores
from app.dominio.modelo import (
    GRUPO_CONSOLIDADO,
    TIPO_DOC_DFP,
    ComposicaoCapital,
    DocumentoContabil,
    Empresa,
    Ticker,
)
from app.dominio.montador_indicadores import MontadorDeIndicadores
from app.dominio.plano_contas.classificador import ClassificadorDePlano
from app.dominio.plano_contas.resolvedor import ResolvedorDeContas
from app.excecoes.excecoes import ErroPermanente

PERIODO = date(2025, 12, 31)
CNPJ_WEG = "84.429.695/0001-11"


class _UnidadeDeTrabalhoFake:
    def __init__(self):
        self.commits = 0

    @contextmanager
    def transacao(self):
        yield object()
        self.commits += 1


class _FonteFake:
    def __init__(self, linhas, assinatura=None, com_capital=True):
        self._linhas = linhas
        self._assinatura = assinatura or Assinatura("etag-novo", None, 100)
        self._com_capital = com_capital
        self.documentos_pedidos: list[set[str]] = []

    def assinatura(self, tipo, ano):
        return self._assinatura

    def tickers(self, ano):
        return {"WEGE3": Ticker(simbolo="WEGE3", cnpj=CNPJ_WEG, mercado="Bolsa")}

    def empresas(self, ano):
        return {CNPJ_WEG: Empresa(cnpj=CNPJ_WEG, denominacao="WEG S.A.")}

    def documentos(self, ano, cnpjs):
        self.documentos_pedidos.append(set(cnpjs))
        yield DocumentoContabil(
            cnpj=CNPJ_WEG,
            tipo_doc=TIPO_DOC_DFP,
            grupo=GRUPO_CONSOLIDADO,
            versao=1,
            dt_refer=PERIODO,
            dt_fim_exerc=PERIODO,
            linhas=self._linhas,
        )

    def datas_de_entrega(self, tipo, ano, cnpjs):
        return {}

    def composicoes_de_capital(self, ano, cnpjs):
        if not self._com_capital:
            return {}
        return {
            CNPJ_WEG: ComposicaoCapital(
                cnpj=CNPJ_WEG,
                dt_refer=PERIODO,
                acoes_ex_tesouraria=4_195_695_973,
                fonte="FRE",
            )
        }


class _RepositorioUniversoFake:
    def __init__(self, simbolos):
        self._simbolos = simbolos

    def listar_simbolos_monitorados(self, db):
        return list(self._simbolos)


class _RepositorioCadastroFake:
    def __init__(self):
        self.empresas = []
        self.tickers = []

    def salvar_empresas(self, db, empresas):
        self.empresas.extend(empresas)
        return len(empresas)

    def salvar_tickers(self, db, tickers):
        self.tickers.extend(tickers)
        return len(tickers)

    def cnpjs_por_simbolo(self, db, simbolos):
        return {}


class _RepositorioFatoFake:
    def __init__(self):
        self.linhas = []
        self.composicoes = []

    def salvar_linhas(self, db, cnpj, tipo_doc, grupo, versao, dt_refer, linhas):
        self.linhas.extend(linhas)
        return len(linhas)

    def salvar_composicao(self, db, capital, tipo_doc):
        self.composicoes.append(capital)


class _RepositorioIndicadorFake:
    def __init__(self):
        self.gravados = []

    def salvar(self, db, indicadores):
        self.gravados.extend(indicadores)
        return len(indicadores)


class _RepositorioExecucaoFake:
    def __init__(self, etag_anterior=None):
        self._etag_anterior = etag_anterior
        self.registros = []

    def etag_da_ultima_execucao(self, db, fonte, competencia, arquivo):
        return self._etag_anterior

    def registrar(self, db, **kwargs):
        self.registros.append(kwargs)


class _VerificadorFake:
    """Por padrao o schema esta ok; o teste que importa injeta um que reclama."""

    def __init__(self, faltando=None):
        self.faltando = faltando or []
        self.conferido = False

    def conferir(self, db, nome_do_banco):
        self.conferido = True
        if self.faltando:
            raise ErroPermanente(f"faltam tabelas: {', '.join(self.faltando)}")


class _PublicadorFake:
    def __init__(self):
        self.publicados = []

    def publicar_fundamentos_atualizados(self, simbolos):
        self.publicados.append(list(simbolos))


def montar(fonte, universo, execucao, indicador=None, publicador=None, verificador=None):
    return CarregarFundamentos(
        fonte=fonte,
        unidade_de_trabalho=_UnidadeDeTrabalhoFake(),
        repositorio_universo=universo,
        repositorio_cadastro=_RepositorioCadastroFake(),
        repositorio_fato=_RepositorioFatoFake(),
        repositorio_indicador=indicador or _RepositorioIndicadorFake(),
        repositorio_execucao=execucao,
        verificador_de_schema=verificador or _VerificadorFake(),
        nome_do_banco="minha_base",
        montador=MontadorDeIndicadores(
            ClassificadorDePlano(), ResolvedorDeContas(), CalculadoraIndicadores()
        ),
        publicador=publicador or _PublicadorFake(),
        logger=logging.getLogger("teste"),
    )


class TestCarregarFundamentos:

    def test_carga_grava_indicador_e_publica_evento(self, linhas_wege3):
        indicador = _RepositorioIndicadorFake()
        publicador = _PublicadorFake()
        caso = montar(
            _FonteFake(linhas_wege3),
            _RepositorioUniversoFake(["WEGE3"]),
            _RepositorioExecucaoFake(),
            indicador,
            publicador,
        )

        resultado = caso.executar([2025])

        assert resultado.sucesso
        assert resultado.anos_processados == [2025]
        assert len(indicador.gravados) == 1
        assert indicador.gravados[0].simbolo == "WEGE3"
        assert publicador.publicados == [["WEGE3"]]

    def test_etag_igual_pula_o_ano_sem_baixar_nada(self, linhas_wege3):
        """O mecanismo que faz uma execucao semanal sem novidade custar 3 HEAD."""
        fonte = _FonteFake(linhas_wege3, Assinatura("etag-igual", None, 100))
        execucao = _RepositorioExecucaoFake(etag_anterior="etag-igual")
        indicador = _RepositorioIndicadorFake()

        resultado = montar(
            fonte, _RepositorioUniversoFake(["WEGE3"]), execucao, indicador
        ).executar([2025])

        assert resultado.anos_pulados == [2025]
        assert resultado.anos_processados == []
        assert fonte.documentos_pedidos == []
        assert indicador.gravados == []
        assert execucao.registros[-1]["status"] == "PULADO"

    def test_etag_diferente_reprocessa(self, linhas_wege3):
        fonte = _FonteFake(linhas_wege3, Assinatura("etag-novo", None, 100))
        execucao = _RepositorioExecucaoFake(etag_anterior="etag-antigo")

        resultado = montar(fonte, _RepositorioUniversoFake(["WEGE3"]), execucao).executar([2025])

        assert resultado.anos_processados == [2025]

    def test_universo_vazio_nao_processa_e_nao_quebra(self, linhas_wege3):
        resultado = montar(
            _FonteFake(linhas_wege3),
            _RepositorioUniversoFake([]),
            _RepositorioExecucaoFake(),
        ).executar([2025])

        assert resultado.sucesso
        assert resultado.indicadores_gravados == 0

    def test_simbolo_explicito_ignora_o_universo_do_banco(self, linhas_wege3):
        universo = _RepositorioUniversoFake(["PETR4"])
        indicador = _RepositorioIndicadorFake()

        montar(
            _FonteFake(linhas_wege3), universo, _RepositorioExecucaoFake(), indicador
        ).executar([2025], simbolos_pedidos=["wege3"])

        assert [i.simbolo for i in indicador.gravados] == ["WEGE3"]

    def test_ticker_sem_correspondencia_no_fca_nao_derruba_a_carga(self, linhas_wege3):
        resultado = montar(
            _FonteFake(linhas_wege3),
            _RepositorioUniversoFake(["INEXISTENTE11"]),
            _RepositorioExecucaoFake(),
        ).executar([2025])

        assert resultado.sucesso
        assert resultado.anos_pulados == [2025]

    def test_sem_indicador_novo_nao_publica_evento(self, linhas_wege3):
        publicador = _PublicadorFake()

        montar(
            _FonteFake(linhas_wege3),
            _RepositorioUniversoFake([]),
            _RepositorioExecucaoFake(),
            publicador=publicador,
        ).executar([2025])

        assert publicador.publicados == []


class TestPreCondicaoDeSchema:

    def test_tabela_faltando_aborta_antes_de_baixar_qualquer_coisa(self, linhas_wege3):
        """O modo de falha real: mysql-init so roda na primeira criacao do
        volume, entao banco que ja existia antes nao tem as tabelas da CVM
        (infra#ISS-03). Antes disso a falha so aparecia no primeiro INSERT,
        como traceback de SQLAlchemy."""
        fonte = _FonteFake(linhas_wege3)
        verificador = _VerificadorFake(faltando=["etl_execucao"])
        caso = montar(
            fonte,
            _RepositorioUniversoFake(["WEGE3"]),
            _RepositorioExecucaoFake(),
            verificador=verificador,
        )

        with pytest.raises(ErroPermanente, match="etl_execucao"):
            caso.executar([2025])

        assert fonte.documentos_pedidos == []

    def test_schema_ok_segue_a_carga(self, linhas_wege3):
        verificador = _VerificadorFake()

        resultado = montar(
            _FonteFake(linhas_wege3),
            _RepositorioUniversoFake(["WEGE3"]),
            _RepositorioExecucaoFake(),
            verificador=verificador,
        ).executar([2025])

        assert verificador.conferido is True
        assert resultado.sucesso
