"""Portas de persistencia.

Quatro interfaces pequenas em vez de uma gorda: o caso de uso que so le o
universo nao precisa depender da porta de escrita do mart.

Convencao herdada do gerar-insights e que vale manter: a Session entra como
parametro de metodo, nunca e guardada no repositorio. E o que torna os testes
possiveis sem banco.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any, Protocol

from app.dominio.comunicado import Comunicado
from app.dominio.modelo import (
    ComposicaoCapital,
    Empresa,
    Indicadores,
    LinhaContabil,
    Ticker,
)
from app.dominio.serie_historica import CandleB3, OpcaoB3


class RepositorioUniverso(Protocol):
    """Quais tickers carregar. Le ativo_monitorado, populada pelo gestor."""

    def listar_simbolos_monitorados(self, db: Any) -> list[str]:
        ...

    def listar_simbolos_liquidos(self, db: Any) -> list[str]:
        """Universo do backtest amplo (infra#TASK-31) mais os monitorados."""
        ...


class RepositorioCadastro(Protocol):
    """Empresas e tickers vindos do FCA."""

    def salvar_empresas(self, db: Any, empresas: Sequence[Empresa]) -> int:
        ...

    def salvar_tickers(self, db: Any, tickers: Sequence[Ticker]) -> int:
        ...

    def cnpjs_por_simbolo(self, db: Any, simbolos: Sequence[str]) -> dict[str, str]:
        ...


class RepositorioFatoContabil(Protocol):
    """Landing das contas cruas ja normalizadas."""

    def salvar_linhas(
        self,
        db: Any,
        cnpj: str,
        tipo_doc: str,
        grupo: str,
        versao: int,
        dt_refer: date,
        linhas: Sequence[LinhaContabil],
    ) -> int:
        ...

    def salvar_composicao(self, db: Any, capital: ComposicaoCapital, tipo_doc: str) -> None:
        ...


class RepositorioIndicador(Protocol):
    """Mart. Unico contrato de leitura para as aplicacoes."""

    def salvar(self, db: Any, indicadores: Sequence[Indicadores]) -> int:
        ...

    def conferir_acoes(self, db: Any, simbolos: Sequence[str]) -> list[str]:
        """Corrige unidade/pico da quantidade de acoes na serie gravada."""
        ...


class RepositorioSeries(Protocol):
    def salvar_candles_b3(self, db: Any, candles: Sequence[CandleB3]) -> int:
        ...

    def atualizar_isin_dos_tickers(self, db: Any) -> int:
        """Copia o ISIN mais recente de cada papel (COTAHIST) para cvm_ticker (o FCA nao traz)."""
        ...


class RepositorioOpcao(Protocol):
    def salvar_opcoes_b3(self, db: Any, opcoes: Sequence[OpcaoB3]) -> int:
        ...


class ConsultaDeTickers(Protocol):
    """Leitura de cvm_ticker, que a carga de fundamentos mantem a partir do FCA."""

    def cnpjs_por_simbolo(self, db: Any, simbolos: Sequence[str]) -> dict[str, str]:
        """simbolo -> cnpj, so para os simbolos que existem em cvm_ticker."""
        ...


class RepositorioComunicado(Protocol):
    """Comunicados da base IPE (comunicado_cvm)."""

    def salvar(self, db: Any, comunicados: Sequence[Comunicado]) -> list[Comunicado]:
        """Grava o que e novo ou reapresentado e devolve exatamente isso.

        Documento ja gravado na mesma versao (ou mais nova) nao conta: e o que
        permite publicar evento so do que mudou de fato.
        """
        ...


class RepositorioExecucao(Protocol):
    """Log das execucoes e memoria dos ETags, para pular download sem novidade."""

    def etag_da_ultima_execucao(
        self, db: Any, fonte: str, competencia: str, arquivo: str
    ) -> str | None:
        ...

    def registrar(
        self,
        db: Any,
        fonte: str,
        competencia: str,
        arquivo: str,
        status: str,
        etag: str | None = None,
        last_modified: str | None = None,
        tamanho_bytes: int | None = None,
        linhas_carregadas: int = 0,
        mensagem_erro: str | None = None,
    ) -> None:
        ...
