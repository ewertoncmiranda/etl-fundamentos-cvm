"""Implementacao de FonteDeDocumentos sobre os dados abertos da CVM.

Costura cliente HTTP, cache, leitor de ZIP e normalizador. Nao decide nada de
negocio: classificar plano de contas, resolver conta e calcular indicador sao
responsabilidade do dominio.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from logging import Logger

from app.adaptadores.cvm.cache_local import CacheDeArquivos
from app.adaptadores.cvm.cliente_http import Assinatura, ClienteHttpCvm
from app.adaptadores.cvm.leitor_pacote import LeitorDePacoteCvm
from app.adaptadores.cvm.normalizador import NormalizadorDeLinhas
from app.dominio.modelo import (
    BPA,
    BPP,
    DFC_MI,
    DRE,
    GRUPO_CONSOLIDADO,
    GRUPO_INDIVIDUAL,
    TIPO_DOC_DFP,
    TIPO_DOC_ITR,
    ComposicaoCapital,
    DocumentoContabil,
    Empresa,
    Ticker,
)
from app.dominio.texto import normalizar
from app.excecoes.excecoes import FonteIndisponivel

# Nome interno da demonstracao -> sufixo do arquivo da CVM
SUFIXO_DEMONSTRACAO = {BPA: "BPA", BPP: "BPP", DRE: "DRE", DFC_MI: "DFC_MI"}

PACOTE_DFP = "DFP"
PACOTE_FCA = "FCA"
PACOTE_FRE = "FRE"
PACOTE_ITR = "ITR"

# Divergencia entre FRE e DFP nesta faixa significa unidade diferente
# (milhares x unidades), nao emissao de acoes entre as datas.
FAIXA_ESCALA_MILHAR = (500, 2000)


def caminho_do_pacote(tipo: str, ano: int) -> str:
    nome = {
        PACOTE_DFP: f"dfp_cia_aberta_{ano}.zip",
        PACOTE_FCA: f"fca_cia_aberta_{ano}.zip",
        PACOTE_FRE: f"fre_cia_aberta_{ano}.zip",
        PACOTE_ITR: f"itr_cia_aberta_{ano}.zip",
    }[tipo]
    return f"{tipo}/DADOS/{nome}"


class FonteCvm:
    def __init__(
        self,
        cliente: ClienteHttpCvm,
        cache: CacheDeArquivos,
        normalizador: NormalizadorDeLinhas,
        logger: Logger,
    ):
        self._cliente = cliente
        self._cache = cache
        self._normalizador = normalizador
        self._logger = logger

    # --- pacotes -----------------------------------------------------------

    def assinatura(self, tipo: str, ano: int) -> Assinatura:
        """Com a CVM fora do ar (ou limitando requisicoes) e o arquivo em
        cache, segue com o cache em vez de abortar: assinatura sem ETag nunca
        e "inalterada", entao o ETag antigo nao e sobrescrito por um falso."""
        caminho = caminho_do_pacote(tipo, ano)
        try:
            return self._cliente.assinatura(caminho)
        except FonteIndisponivel as erro:
            nome = caminho.rsplit("/", 1)[-1]
            if not self._cache.tem(nome):
                raise
            self._logger.warning("CVM indisponivel (%s); usando %s do cache", erro, nome)
            return Assinatura(etag=None, last_modified=None, tamanho_bytes=None)

    def _conteudo(self, tipo: str, ano: int, forcar_download: bool = False) -> bytes:
        caminho = caminho_do_pacote(tipo, ano)
        nome = caminho.rsplit("/", 1)[-1]

        if not forcar_download and self._cache.tem(nome):
            self._logger.debug("Usando %s do cache", nome)
            return self._cache.ler(nome)

        conteudo = self._cliente.baixar(caminho)
        self._cache.gravar(nome, conteudo)
        return conteudo

    def _leitor(self, tipo: str, ano: int, forcar_download: bool = False) -> LeitorDePacoteCvm:
        return LeitorDePacoteCvm(
            self._conteudo(tipo, ano, forcar_download), nome_para_erro=f"{tipo} {ano}"
        )

    # --- cadastro (FCA) ----------------------------------------------------

    def tickers(self, ano: int) -> dict[str, Ticker]:
        arquivo = f"fca_cia_aberta_valor_mobiliario_{ano}.csv"
        saida: dict[str, Ticker] = {}
        with self._leitor(PACOTE_FCA, ano) as leitor:
            for linha in leitor.linhas(arquivo):
                simbolo = (linha.get("Codigo_Negociacao") or "").strip().upper()
                if not simbolo or (linha.get("Mercado") or "").strip() != "Bolsa":
                    continue
                saida[simbolo] = Ticker(
                    simbolo=simbolo,
                    cnpj=(linha.get("CNPJ_Companhia") or "").strip(),
                    tipo_valor_mobiliario=(linha.get("Valor_Mobiliario") or "").strip(),
                    mercado="Bolsa",
                )
        return saida

    def empresas(self, ano: int) -> dict[str, Empresa]:
        arquivo = f"fca_cia_aberta_geral_{ano}.csv"
        saida: dict[str, Empresa] = {}
        with self._leitor(PACOTE_FCA, ano) as leitor:
            if not leitor.tem(arquivo):
                return saida
            for linha in leitor.linhas(arquivo):
                cnpj = (linha.get("CNPJ_Companhia") or "").strip()
                if not cnpj:
                    continue
                saida[cnpj] = Empresa(
                    cnpj=cnpj,
                    denominacao=(linha.get("Nome_Empresarial") or "").strip(),
                    cd_cvm=(linha.get("Codigo_CVM") or "").strip() or None,
                    setor=(linha.get("Setor_Atividade") or "").strip() or None,
                )
        return saida

    # --- data de entrega (point-in-time) ------------------------------------

    def datas_de_entrega(
        self, tipo: str, ano: int, cnpjs: set[str]
    ) -> dict[tuple[str, date, int], date]:
        """(cnpj, dt_refer, versao) -> DT_RECEB, do arquivo-indice do pacote.

        As demonstracoes nao trazem a data de entrega; so o indice
        (dfp_cia_aberta_{ano}.csv / itr_cia_aberta_{ano}.csv) traz. Cada
        versao tem a sua: uma reapresentacao so ficou publica na entrega dela.
        """
        arquivo = f"{tipo.lower()}_cia_aberta_{ano}.csv"
        saida: dict[tuple[str, date, int], date] = {}
        with self._leitor(tipo, ano) as leitor:
            if not leitor.tem(arquivo):
                self._logger.warning("%s %s sem indice de entregas (%s)", tipo, ano, arquivo)
                return saida
            for linha in leitor.linhas(arquivo):
                cnpj = (linha.get("CNPJ_CIA") or "").strip()
                if cnpj not in cnpjs:
                    continue
                try:
                    referencia = datetime.strptime(linha["DT_REFER"].strip(), "%Y-%m-%d").date()
                    recebido = datetime.strptime(linha["DT_RECEB"].strip(), "%Y-%m-%d").date()
                except (KeyError, ValueError, AttributeError):
                    continue
                saida[(cnpj, referencia, _inteiro(linha.get("VERSAO")))] = recebido
        return saida

    # --- demonstracoes (DFP) ----------------------------------------------

    def documentos(self, ano: int, cnpjs: set[str]) -> Iterable[DocumentoContabil]:
        """Consolidado quando existe; individual como fallback.

        434 companhias publicam DRE consolidada contra 665 com capital
        registrado - quem nao tem controlada so publica individual.

        Consolidado com todas as contas em 0 conta como ausente: e formulario
        entregue sem preencher (TIM 2024), e o numero real esta no individual.
        """
        consolidado = {
            cnpj: documento
            for cnpj, documento in self._documentos_dfp(
                ano, cnpjs, GRUPO_CONSOLIDADO
            ).items()
            if not documento.zerado
        }
        faltantes = cnpjs - set(consolidado)
        individual = self._documentos_dfp(ano, faltantes, GRUPO_INDIVIDUAL)

        yield from consolidado.values()
        yield from individual.values()

    def _documentos_dfp(
        self, ano: int, cnpjs: set[str], grupo: str
    ) -> dict[str, DocumentoContabil]:
        return {
            cnpj: DocumentoContabil(
                cnpj=cnpj,
                tipo_doc=TIPO_DOC_DFP,
                grupo=grupo,
                versao=dados["versao"],
                dt_refer=dados["dt_refer"],
                dt_fim_exerc=dados["dt_fim_exerc"],
                linhas={k: tuple(v) for k, v in dados["linhas"].items()},
            )
            for cnpj, dados in self._demonstracoes(ano, cnpjs, grupo).items()
        }

    def _demonstracoes(self, ano: int, cnpjs: set[str], grupo: str) -> dict[str, dict]:
        if not cnpjs:
            return {}

        acumulado: dict[str, dict] = {}
        with self._leitor(PACOTE_DFP, ano) as leitor:
            for demonstracao, sufixo in SUFIXO_DEMONSTRACAO.items():
                arquivo = f"dfp_cia_aberta_{sufixo}_{grupo}_{ano}.csv"
                if not leitor.tem(arquivo):
                    continue
                for linha_crua in leitor.linhas(arquivo):
                    cnpj = (linha_crua.get("CNPJ_CIA") or "").strip()
                    if cnpj not in cnpjs:
                        continue

                    convertida = self._normalizador.converter(linha_crua, demonstracao)
                    if convertida is None:
                        continue

                    versao = self._normalizador.versao(linha_crua)
                    registro = acumulado.setdefault(
                        cnpj,
                        {
                            "versao": -1,
                            "dt_refer": convertida.dt_fim_exerc,
                            "dt_fim_exerc": convertida.dt_fim_exerc,
                            "linhas": {},
                        },
                    )

                    # reapresentacao: versao maior descarta tudo o que veio antes
                    if versao < registro["versao"]:
                        continue
                    if versao > registro["versao"]:
                        registro["versao"] = versao
                        registro["linhas"] = {}

                    registro["linhas"].setdefault(demonstracao, []).append(convertida)
                    registro["dt_fim_exerc"] = convertida.dt_fim_exerc

        return {cnpj: dados for cnpj, dados in acumulado.items() if dados["linhas"]}

    def documentos_itr(self, ano: int, cnpjs: set[str]) -> Iterable[DocumentoContabil]:
        consolidado = self._demonstracoes_itr(ano, cnpjs, GRUPO_CONSOLIDADO)
        cnpjs_com_consolidado = {cnpj for cnpj, _ in consolidado}
        individual = self._demonstracoes_itr(
            ano, cnpjs - cnpjs_com_consolidado, GRUPO_INDIVIDUAL
        )
        for grupo, mapa in ((GRUPO_CONSOLIDADO, consolidado), (GRUPO_INDIVIDUAL, individual)):
            for (cnpj, _), dados in sorted(mapa.items(), key=lambda item: item[0][1]):
                yield DocumentoContabil(
                    cnpj=cnpj,
                    tipo_doc=TIPO_DOC_ITR,
                    grupo=grupo,
                    versao=dados["versao"],
                    dt_refer=dados["dt_refer"],
                    dt_fim_exerc=dados["dt_fim_exerc"],
                    linhas={k: tuple(v) for k, v in dados["linhas"].items()},
                )

    def _demonstracoes_itr(
        self, ano: int, cnpjs: set[str], grupo: str
    ) -> dict[tuple[str, date], dict]:
        acumulado: dict[tuple[str, date], dict] = {}
        if not cnpjs:
            return acumulado
        with self._leitor(PACOTE_ITR, ano) as leitor:
            for demonstracao, sufixo in SUFIXO_DEMONSTRACAO.items():
                arquivo = f"itr_cia_aberta_{sufixo}_{grupo}_{ano}.csv"
                if not leitor.tem(arquivo):
                    continue
                for linha_crua in leitor.linhas(arquivo):
                    cnpj = (linha_crua.get("CNPJ_CIA") or "").strip()
                    if cnpj not in cnpjs:
                        continue
                    convertida = self._normalizador.converter(linha_crua, demonstracao)
                    if convertida is None:
                        continue
                    referencia = _data_ou_hoje(linha_crua.get("DT_REFER"))
                    # DRE do ITR pode trazer no mesmo arquivo o trimestre isolado
                    # e o acumulado no ano. TTM usa o acumulado iniciado em 1º/1;
                    # misturar os dois produz contas duplicadas e um resultado
                    # silenciosamente errado.
                    if (
                        demonstracao in (DRE, DFC_MI)
                        and convertida.dt_ini_exerc != date(referencia.year, 1, 1)
                    ):
                        continue
                    chave = (cnpj, referencia)
                    versao = self._normalizador.versao(linha_crua)
                    registro = acumulado.setdefault(
                        chave,
                        {
                            "versao": -1,
                            "dt_refer": referencia,
                            "dt_fim_exerc": convertida.dt_fim_exerc,
                            "linhas": {},
                        },
                    )
                    if versao < registro["versao"]:
                        continue
                    if versao > registro["versao"]:
                        registro["versao"] = versao
                        registro["linhas"] = {}
                    registro["linhas"].setdefault(demonstracao, []).append(convertida)
        return {chave: dados for chave, dados in acumulado.items() if dados["linhas"]}

    # --- quantidade de acoes (DFP + FRE) ----------------------------------

    def composicoes_de_capital(
        self, ano: int, cnpjs: set[str]
    ) -> dict[str, ComposicaoCapital]:
        """Resolve o denominador de LPA e VPA.

        A composicao do DFP nao tem unidade padronizada: a WEG declara
        4.197.317.998 acoes (unidades) e a VALE declara 4.539.007 (milhares) no
        mesmo campo. Usar o numero cru joga o LPA 1000x fora em silencio.

        O FRE traz a mesma informacao com unidade consistente em 'Capital
        Integralizado' e e a fonte autoritativa; o DFP fica so com as acoes em
        tesouraria, reescaladas pelo fator detectado entre as duas fontes.
        """
        dfp = self._composicao_do_dfp(ano, cnpjs)
        fre = self._capital_do_fre(ano, cnpjs)

        saida: dict[str, ComposicaoCapital] = {}
        for cnpj, bruto in dfp.items():
            total_dfp = bruto["total"]
            tesouraria = bruto["tesouraria"]
            total_fre = fre.get(cnpj, 0)

            if total_fre and total_dfp:
                divergencia = total_fre / total_dfp
                dentro_da_faixa = (
                    FAIXA_ESCALA_MILHAR[0] <= divergencia <= FAIXA_ESCALA_MILHAR[1]
                )
                escala = 1000 if dentro_da_faixa else 1
                saida[cnpj] = ComposicaoCapital(
                    cnpj=cnpj,
                    dt_refer=bruto["dt_refer"],
                    acoes_ex_tesouraria=total_fre - tesouraria * escala,
                    fonte="FRE",
                    escala_aplicada=escala,
                    divergencia_fre_dfp=round(divergencia, 3),
                )
            elif total_dfp:
                saida[cnpj] = ComposicaoCapital(
                    cnpj=cnpj,
                    dt_refer=bruto["dt_refer"],
                    acoes_ex_tesouraria=total_dfp - tesouraria,
                    fonte="DFP",
                )

        # Os DFP ate 2019 nao trazem o arquivo de composicao do capital (a CVM
        # passou a publica-lo em 2020); sem isto o LPA desses anos sai nulo e o
        # backtest perde metade do periodo. O FRE do mesmo ano tem o total de
        # acoes; a tesouraria fica sem desconto (em geral < 5% do capital), o
        # que a `fonte` registra para quem ler a cobertura.
        for cnpj, total_fre in fre.items():
            if cnpj not in saida and total_fre:
                saida[cnpj] = ComposicaoCapital(
                    cnpj=cnpj,
                    dt_refer=date(ano, 12, 31),
                    acoes_ex_tesouraria=total_fre,
                    fonte="FRE_SEM_TESOURARIA",
                )
        return saida

    def _composicao_do_dfp(self, ano: int, cnpjs: set[str]) -> dict[str, dict]:
        arquivo = f"dfp_cia_aberta_composicao_capital_{ano}.csv"
        saida: dict[str, dict] = {}
        with self._leitor(PACOTE_DFP, ano) as leitor:
            if not leitor.tem(arquivo):
                return saida
            for linha in leitor.linhas(arquivo):
                cnpj = (linha.get("CNPJ_CIA") or "").strip()
                if cnpj not in cnpjs:
                    continue
                versao = self._normalizador.versao(linha)
                anterior = saida.get(cnpj)
                if anterior and anterior["versao"] > versao:
                    continue
                saida[cnpj] = {
                    "versao": versao,
                    "dt_refer": _data_ou_hoje(linha.get("DT_REFER")),
                    "total": _inteiro(linha.get("QT_ACAO_TOTAL_CAP_INTEGR")),
                    "tesouraria": _inteiro(linha.get("QT_ACAO_TOTAL_TESOURO")),
                }
        return saida

    def _capital_do_fre(self, ano: int, cnpjs: set[str]) -> dict[str, int]:
        arquivo = f"fre_cia_aberta_capital_social_{ano}.csv"
        saida: dict[str, dict] = {}
        try:
            leitor = self._leitor(PACOTE_FRE, ano)
        except Exception as erro:  # FRE ausente nao impede a carga
            self._logger.warning("FRE %s indisponivel (%s); usando so o DFP", ano, erro)
            return {}

        with leitor:
            if not leitor.tem(arquivo):
                return {}
            for linha in leitor.linhas(arquivo):
                if normalizar(linha.get("Tipo_Capital")) != "capital integralizado":
                    continue
                cnpj = (linha.get("CNPJ_Companhia") or "").strip()
                if cnpj not in cnpjs:
                    continue
                versao = _inteiro(linha.get("Versao"))
                anterior = saida.get(cnpj)
                if anterior and anterior["versao"] > versao:
                    continue
                saida[cnpj] = {
                    "versao": versao,
                    "total": _inteiro(linha.get("Quantidade_Total_Acoes")),
                }
        return {cnpj: dados["total"] for cnpj, dados in saida.items()}


def _inteiro(valor: str | None) -> int:
    try:
        return int((valor or "0").strip() or 0)
    except ValueError:
        return 0


def _data_ou_hoje(valor: str | None) -> date:
    try:
        return datetime.strptime((valor or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return date.today()
