from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from logging import Logger

from app.dominio.fontes_publicas import motivo_mercado
from app.dominio.identidade import canonizar_opcoes, codigos_negociados
from app.dominio.modelo import STATUS_PULADO, STATUS_SUCESSO
from app.dominio.serie_historica import resumir_validacao_opcoes
from app.portas.fonte_series import FonteDeOpcoes, FonteDeSeries
from app.portas.repositorios import RepositorioExecucao, RepositorioOpcao, RepositorioSeries

FONTE_COTAHIST = "B3_COTAHIST"
FONTE_COTAHIST_OPCOES = "B3_COTAHIST_OPCOES"
FONTE_COTAHIST_MERCADOS = "B3_COTAHIST_MERCADOS"
MERCADOS_DESDE = 2016
JANELA_RECOMPOSICAO_OPCOES_ANOS = 5


@dataclass
class ResultadoSeries:
    anos_processados: list[int] = field(default_factory=list)
    anos_pulados: list[int] = field(default_factory=list)
    candles_por_ano: dict[int, int] = field(default_factory=dict)
    candles_gravados: int = 0
    opcoes_gravadas: int = 0
    erros_opcoes: list[str] = field(default_factory=list)
    mercados_gravados: int = 0
    mercados_processados: list[int] = field(default_factory=list)
    erros_mercados: list[str] = field(default_factory=list)
    rejeicoes: list[dict] = field(default_factory=list)
    mercados_recompostos: bool = False


class CarregarSeriesHistoricas:
    def __init__(
        self,
        fonte: FonteDeSeries,
        unidade_de_trabalho,
        repositorio_series: RepositorioSeries,
        repositorio_execucao: RepositorioExecucao,
        logger: Logger,
        atualizador_mercado=None,
        repositorio_identidade=None,
        verificador_de_schema=None,
        nome_do_banco: str | None = None,
        fonte_opcoes: FonteDeOpcoes | None = None,
        repositorio_opcao: RepositorioOpcao | None = None,
        fonte_mercados=None,
        repositorio_mercados=None,
    ):
        self._fonte = fonte
        self._uow = unidade_de_trabalho
        self._series = repositorio_series
        self._execucao = repositorio_execucao
        self._logger = logger
        self._atualizador = atualizador_mercado
        self._identidade = repositorio_identidade
        self._verificador = verificador_de_schema
        self._nome_do_banco = nome_do_banco
        self._fonte_opcoes = fonte_opcoes
        self._opcao = repositorio_opcao
        self._fonte_mercados = fonte_mercados
        self._mercados = repositorio_mercados

    def executar(
        self,
        anos: list[int],
        simbolos_pedidos: list[str] | None = None,
        forcar: bool = False,
    ) -> ResultadoSeries:
        resultado = ResultadoSeries()
        if self._verificador is not None:
            with self._uow.transacao() as db:
                self._verificador.conferir(db, self._nome_do_banco)
        simbolos = self._resolver_universo(simbolos_pedidos)
        if simbolos is None:
            self._logger.info(
                "COTAHIST: universo amplo, sem filtro de simbolo - todo lote padrao/BDR do arquivo"
            )
        else:
            self._logger.info("COTAHIST: %d codigos (com os antigos) - %s", len(simbolos), simbolos)

        ano_referencia = max(anos) if anos else date.today().year
        ano_inicio_recomposicao = ano_referencia - JANELA_RECOMPOSICAO_OPCOES_ANOS
        precisa_recompor_opcoes = False
        if self._fonte_opcoes is not None and self._opcao is not None:
            with self._uow.transacao() as db:
                precisa_recompor_opcoes = self._opcao.precisa_recomposicao(
                    db, date(ano_inicio_recomposicao, 1, 1)
                )
            if precisa_recompor_opcoes:
                self._logger.warning(
                    "COTAHIST opções: tabela vazia ou com registros legados/inconsistentes; "
                    "recompondo %d..%d pela rotina existente",
                    ano_inicio_recomposicao,
                    ano_referencia,
                )

        assinaturas = {}
        for ano in sorted(anos):
            arquivo = f"COTAHIST_A{ano}.ZIP"
            assinatura = self._fonte.assinatura(ano)
            assinaturas[ano] = assinatura
            with self._uow.transacao() as db:
                etag_anterior = self._execucao.etag_da_ultima_execucao(
                    db, FONTE_COTAHIST, str(ano), arquivo
                )
            if not forcar and assinatura.inalterado_em_relacao_a(etag_anterior):
                with self._uow.transacao() as db:
                    self._execucao.registrar(
                        db, FONTE_COTAHIST, str(ano), arquivo, STATUS_PULADO,
                        etag=assinatura.etag,
                        last_modified=assinatura.last_modified,
                        tamanho_bytes=assinatura.tamanho_bytes,
                    )
                resultado.anos_pulados.append(ano)
                continue

            candles = self._fonte.candles(
                ano, None if simbolos is None else set(simbolos), usar_cache=ano < date.today().year
            )
            with self._uow.transacao() as db:
                gravados = self._series.salvar_candles_b3(db, candles)
                isins = self._series.atualizar_isin_dos_tickers(db)
                self._execucao.registrar(
                    db, FONTE_COTAHIST, str(ano), arquivo, STATUS_SUCESSO,
                    etag=assinatura.etag,
                    last_modified=assinatura.last_modified,
                    tamanho_bytes=assinatura.tamanho_bytes,
                    linhas_carregadas=gravados,
                )
            resultado.anos_processados.append(ano)
            resultado.candles_por_ano[ano] = gravados
            resultado.candles_gravados += gravados
            self._logger.info("COTAHIST %s: %d candles B3 brutos gravados", ano, gravados)
            if isins:
                self._logger.info("COTAHIST %s: ISIN atualizado em %d tickers", ano, isins)

            if self._atualizador and simbolos:
                try:
                    self._atualizador.executar([ano], simbolos)
                except Exception as erro:
                    self._logger.warning("Multiplos de mercado pos-COTAHIST %s: %s", ano, erro)

        if self._fonte_opcoes is not None and self._opcao is not None:
            # Sempre conferir os anos solicitados na etapa independente: um
            # candle com ETag inalterado não prova que a carga de opções daquele
            # arquivo foi concluída. O ETag próprio de opções evita downloads
            # redundantes; recomposição amplia a janela automaticamente.
            anos_opcoes = (
                set(range(ano_inicio_recomposicao, ano_referencia + 1))
                if precisa_recompor_opcoes
                else set(anos)
            )
            self._carregar_opcoes(
                sorted(anos_opcoes), assinaturas, forcar or precisa_recompor_opcoes,
                precisa_recompor_opcoes, resultado,
            )
        if self._fonte_mercados is not None and self._mercados is not None:
            self._carregar_mercados(anos, assinaturas, forcar, ano_referencia, resultado)
        return resultado

    def _carregar_mercados(
        self,
        anos: list[int],
        assinaturas: dict[int, object],
        forcar: bool,
        ano_referencia: int,
        resultado: ResultadoSeries,
    ) -> None:
        """Demais mercados (negociacao_b3_diaria) com trilha de ETag propria, no modelo
        das opcoes. Tabela vazia recompoe desde MERCADOS_DESDE. Falha aqui nao desfaz
        os candles: vira erro (FALHA) no resumo."""
        with self._uow.transacao() as db:
            vazia = self._mercados.contar_negociacoes_mercado(db) == 0
        if vazia:
            anos = list(range(MERCADOS_DESDE, ano_referencia + 1))
            forcar = True
            resultado.mercados_recompostos = True
            self._logger.warning("COTAHIST mercados: tabela vazia; recompondo %d..%d",
                                 anos[0], anos[-1])
        for ano in sorted(set(anos)):
            arquivo = f"COTAHIST_A{ano}.ZIP"
            try:
                assinatura = assinaturas.get(ano) or self._fonte.assinatura(ano)
                with self._uow.transacao() as db:
                    etag_anterior = self._execucao.etag_da_ultima_execucao(
                        db, FONTE_COTAHIST_MERCADOS, str(ano), arquivo
                    )
                if not forcar and assinatura.inalterado_em_relacao_a(etag_anterior):
                    self._logger.info("COTAHIST mercados %s: ETag inalterado; pulado", ano)
                    continue
                negocios = self._fonte_mercados.mercados(ano, usar_cache=ano < date.today().year)
                boas = []
                for n in negocios:
                    motivo = motivo_mercado(n)
                    if motivo is None:
                        boas.append(n)
                    else:
                        resultado.rejeicoes.append({"motivo": motivo, "origem": f"mercados {ano}"})
                with self._uow.transacao() as db:
                    gravadas = self._mercados.salvar_negociacoes_mercado(db, boas)
                    self._execucao.registrar(
                        db, FONTE_COTAHIST_MERCADOS, str(ano), arquivo, STATUS_SUCESSO,
                        etag=assinatura.etag, last_modified=assinatura.last_modified,
                        tamanho_bytes=assinatura.tamanho_bytes, linhas_carregadas=gravadas,
                    )
                resultado.mercados_processados.append(ano)
                resultado.mercados_gravados += gravadas
                self._logger.info("COTAHIST mercados %s: %d gravados", ano, gravadas)
            except Exception as erro:
                mensagem = f"COTAHIST mercados {ano}: {erro}"
                resultado.erros_mercados.append(mensagem)
                self._logger.error("%s", mensagem, exc_info=True)
                try:
                    with self._uow.transacao() as db:
                        self._execucao.registrar(
                            db, FONTE_COTAHIST_MERCADOS, str(ano), arquivo, "ERRO",
                            mensagem_erro=str(erro)[:1000],
                        )
                except Exception:
                    self._logger.error("COTAHIST mercados %s: falha ao registrar erro", ano,
                                       exc_info=True)

    def _carregar_opcoes(
        self,
        anos: list[int],
        assinaturas: dict[int, object],
        forcar: bool,
        recomposicao: bool,
        resultado: ResultadoSeries,
    ) -> None:
        """Carrega opções de forma independente do ETag/candle à vista.

        A falha desta etapa fica registrada separadamente e não desfaz nem
        transforma em falha os candles já confirmados pela unidade de trabalho.
        """
        for ano in anos:
            arquivo = f"COTAHIST_A{ano}.ZIP"
            try:
                assinatura = assinaturas.get(ano) or self._fonte.assinatura(ano)
                with self._uow.transacao() as db:
                    etag_anterior = self._execucao.etag_da_ultima_execucao(
                        db, FONTE_COTAHIST_OPCOES, str(ano), arquivo
                    )
                if not forcar and assinatura.inalterado_em_relacao_a(etag_anterior):
                    self._logger.info("COTAHIST opções %s: ETag inalterado; etapa pulada", ano)
                    continue

                opcoes = self._fonte_opcoes.opcoes(
                    ano, usar_cache=ano < date.today().year
                )
                if self._identidade is not None:
                    with self._uow.transacao() as db:
                        opcoes = canonizar_opcoes(opcoes, self._identidade.identidades(db))
                resumo = resumir_validacao_opcoes(opcoes)
                with self._uow.transacao() as db:
                    gravadas = self._opcao.salvar_opcoes_b3(db, opcoes)
                    if recomposicao:
                        self._opcao.invalidar_legado_residual(db, ano)
                    self._execucao.registrar(
                        db, FONTE_COTAHIST_OPCOES, str(ano), arquivo, STATUS_SUCESSO,
                        etag=assinatura.etag,
                        last_modified=assinatura.last_modified,
                        tamanho_bytes=assinatura.tamanho_bytes,
                        linhas_carregadas=gravadas,
                        mensagem_erro=json.dumps(resumo, ensure_ascii=False),
                    )
                resultado.opcoes_gravadas += gravadas
                self._logger.info(
                    "COTAHIST opções %s: %d gravadas | lidas=%d | válidas=%d | "
                    "inválidas=%d | motivos=%s",
                    ano, gravadas, resumo["total"], resumo["validos"],
                    resumo["invalidos"], resumo["motivos"],
                )
            except Exception as erro:
                mensagem = f"COTAHIST opções {ano}: {erro}"
                resultado.erros_opcoes.append(mensagem)
                self._logger.error("%s", mensagem, exc_info=True)
                try:
                    assinatura = assinaturas.get(ano) or self._fonte.assinatura(ano)
                    with self._uow.transacao() as db:
                        self._execucao.registrar(
                            db, FONTE_COTAHIST_OPCOES, str(ano), arquivo, "ERRO",
                            etag=assinatura.etag,
                            last_modified=assinatura.last_modified,
                            tamanho_bytes=assinatura.tamanho_bytes,
                            mensagem_erro=str(erro)[:1000],
                        )
                except Exception:
                    self._logger.error(
                        "COTAHIST opções %s: não foi possível registrar a falha no banco",
                        ano, exc_info=True,
                    )

    def _resolver_universo(self, simbolos_pedidos: list[str] | None) -> list[str] | None:
        """None = universo amplo (TASK-59): sem lista pre-definida, o proprio
        COTAHIST e a fonte de quais simbolos negociaram naquele ano - e por
        isso que nao ha bloqueio de deslistada aqui, diferente do
        ativo_monitorado (que so tem o que esta sendo acompanhado hoje)."""
        if not simbolos_pedidos:
            return None
        simbolos = sorted({s.strip().upper() for s in simbolos_pedidos if s.strip()})
        if self._identidade is not None:
            with self._uow.transacao() as db:
                simbolos = sorted(codigos_negociados(simbolos, self._identidade.identidades(db)))
        return simbolos
