"""Caso de uso: proventos por periodo a partir da DVA (plano LAC, L1).

Por ano: DFP e ITRs da companhia, sempre do MESMO grupo (consolidado ou
individual - misturar soma perimetros diferentes, a mesma licao do TTM de
2026-09-28), acumulados isolados em trimestres e gravados em
provento_contabil com a data de entrega. Reaproveita os ZIPs do cache.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from logging import Logger

from app.aplicacao.carregar_fundamentos import data_de_entrega
from app.dominio.identidade import resolver_tickers
from app.dominio.modelo import (
    GRUPO_CONSOLIDADO,
    STATUS_SUCESSO,
    DocumentoContabil,
)
from app.dominio.plano_contas.resolvedor import ResolvedorDeContas
from app.dominio.provento import RegistroProvento, acumulado_do_documento, isolar_periodos
from app.portas.fonte_documentos import FonteDeDocumentos
from app.portas.provento import RepositorioProvento
from app.portas.repositorios import (
    RepositorioCadastro,
    RepositorioExecucao,
    RepositorioUniverso,
)

FONTE_PROVENTOS = "CVM_DVA"


@dataclass
class ResultadoProventos:
    anos_processados: list[int] = field(default_factory=list)
    periodos_gravados: int = 0
    empresas_sem_dva: list[str] = field(default_factory=list)


class CarregarProventosContabeis:
    def __init__(
        self,
        fonte: FonteDeDocumentos,
        unidade_de_trabalho,
        repositorio_universo: RepositorioUniverso,
        repositorio_cadastro: RepositorioCadastro,
        repositorio_provento: RepositorioProvento,
        repositorio_execucao: RepositorioExecucao,
        logger: Logger,
        repositorio_identidade=None,
        verificador_de_schema=None,
        nome_do_banco: str | None = None,
        resolvedor: ResolvedorDeContas | None = None,
    ):
        self._fonte = fonte
        self._uow = unidade_de_trabalho
        self._universo = repositorio_universo
        self._cadastro = repositorio_cadastro
        self._proventos = repositorio_provento
        self._execucao = repositorio_execucao
        self._logger = logger
        self._identidade = repositorio_identidade
        self._verificador = verificador_de_schema
        self._nome_do_banco = nome_do_banco
        self._resolvedor = resolvedor or ResolvedorDeContas()

    def executar(
        self,
        anos: list[int],
        simbolos_pedidos: list[str] | None = None,
        universo_backtest: bool = False,
    ) -> ResultadoProventos:
        resultado = ResultadoProventos()
        with self._uow.transacao() as db:
            if self._verificador is not None:
                self._verificador.conferir(db, self._nome_do_banco)
            simbolos = self._resolver_universo(db, simbolos_pedidos, universo_backtest)
        if not simbolos:
            self._logger.warning("Proventos: universo vazio; nada a fazer")
            return resultado
        for ano in sorted(anos):
            self._processar_ano(ano, simbolos, resultado)
        return resultado

    def _resolver_universo(
        self, db, simbolos_pedidos: list[str] | None, universo_backtest: bool
    ) -> list[str]:
        if simbolos_pedidos:
            return sorted({s.strip().upper() for s in simbolos_pedidos if s.strip()})
        if universo_backtest:
            return self._universo.listar_simbolos_liquidos(db)
        return self._universo.listar_simbolos_monitorados(db)

    def _processar_ano(self, ano: int, simbolos: list[str], resultado: ResultadoProventos) -> None:
        with self._uow.transacao() as db:
            conhecidos = self._cadastro.cnpjs_por_simbolo(db, simbolos)
            identidades = self._identidade.identidades(db) if self._identidade else {}
        tickers = self._fonte.tickers(ano) or self._fonte.tickers(ano - 1)
        selecionados, _ = resolver_tickers(simbolos, tickers, identidades, conhecidos)
        cnpjs = {t.cnpj for t in selecionados.values()}
        if not cnpjs:
            return

        dfps = list(self._fonte.documentos(ano, cnpjs, todos_os_grupos=True))
        itrs = list(self._fonte.documentos_itr(ano, cnpjs))
        # Acoes do DFP do ano (as mesmas do LPA); no ano corrente, sem DFP
        # ainda, as do ano anterior. Declarado em cobertura_json.
        capitais = self._fonte.composicoes_de_capital(ano, cnpjs)
        if not capitais:
            capitais = self._fonte.composicoes_de_capital(ano - 1, cnpjs)
        entregas = {
            **self._fonte.datas_de_entrega("DFP", ano, cnpjs),
            **self._fonte.datas_de_entrega("ITR", ano, cnpjs),
        }

        registros: list[RegistroProvento] = []
        for cnpj in sorted(cnpjs):
            grupo = escolher_grupo(cnpj, dfps, itrs)
            if grupo is None:
                continue
            dfp = next((d for d in dfps if d.cnpj == cnpj and d.grupo == grupo), None)
            itrs_do_grupo = [d for d in itrs if d.cnpj == cnpj and d.grupo == grupo]
            documentos = {d.dt_fim_exerc: d for d in itrs_do_grupo + ([dfp] if dfp else [])}

            acumulado_dfp = acumulado_do_documento(dfp, self._resolvedor) if dfp else None
            acumulados_itr = [
                a for a in (acumulado_do_documento(d, self._resolvedor) for d in itrs_do_grupo) if a
            ]
            if acumulado_dfp is None and not acumulados_itr:
                resultado.empresas_sem_dva.append(cnpj)
                continue

            capital = capitais.get(cnpj)
            for periodo in isolar_periodos(acumulados_itr, acumulado_dfp):
                documento = documentos[periodo.dt_fim]
                registros.append(
                    RegistroProvento(
                        cnpj=cnpj,
                        periodo=periodo,
                        data_entrega=data_de_entrega(
                            entregas, cnpj, documento.dt_refer, documento.versao
                        ),
                        acoes_ex_tesouraria=capital.acoes_ex_tesouraria if capital else None,
                        grupo=grupo,
                    )
                )

        with self._uow.transacao() as db:
            gravados = self._proventos.salvar(db, registros)
            self._execucao.registrar(
                db, FONTE_PROVENTOS, str(ano), f"dfp+itr {ano}", STATUS_SUCESSO,
                linhas_carregadas=gravados,
            )
        resultado.anos_processados.append(ano)
        resultado.periodos_gravados += gravados
        self._logger.info(
            "Proventos %s: %d periodo(s) de %d empresa(s); %d sem DVA",
            ano, gravados, len(cnpjs), len(resultado.empresas_sem_dva),
        )


def escolher_grupo(
    cnpj: str, dfps: Iterable[DocumentoContabil], itrs: Iterable[DocumentoContabil]
) -> str | None:
    """O grupo da DFP (a fonte já prefere o consolidado preenchido); sem DFP,
    o grupo com mais ITRs no ano, consolidado no empate."""
    grupos_dfp = {d.grupo for d in dfps if d.cnpj == cnpj}
    if grupos_dfp:
        return GRUPO_CONSOLIDADO if GRUPO_CONSOLIDADO in grupos_dfp else next(iter(grupos_dfp))
    contagem: dict[str, int] = {}
    for d in itrs:
        if d.cnpj == cnpj:
            contagem[d.grupo] = contagem.get(d.grupo, 0) + 1
    if not contagem:
        return None
    return max(contagem, key=lambda g: (contagem[g], g == GRUPO_CONSOLIDADO))
