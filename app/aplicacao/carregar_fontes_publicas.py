"""Casos de uso das fontes publicas da V45 (FONTES-ETL-8, parte 1).

Tesouro, VLMO, FRE (auditor e divida) e CDA. Todos seguem o mesmo contrato com
o orquestrador:

  - o ETag (HEAD) decide se ha o que baixar; sem mudanca registra PULADO e o
    resultado so tem `itens_pulados` -> SEM_MUDANCA;
  - registro descartado por validacao vai para `rejeicoes` -> ALERTA;
  - erro de fonte/arquivo vai para `erros` (ou sobe, no caso de fonte unica)
    -> FALHA.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from logging import Logger

from app.adaptadores.cvm.cda import PosicaoFundoAcao, ler_cda_acoes
from app.adaptadores.cvm.fonte_pacotes import ArquivoAusente
from app.adaptadores.cvm.fre_estendido import LeitorFreEstendido
from app.adaptadores.cvm.vlmo import ler_vlmo
from app.adaptadores.tesouro.fonte_tesouro import ARQUIVO
from app.dominio.fontes_publicas import (
    motivo_auditor,
    motivo_divida,
    motivo_negociacao,
    motivo_posicao,
    motivo_taxa,
)
from app.dominio.modelo import STATUS_ERRO, STATUS_PULADO, STATUS_SUCESSO
from app.excecoes.excecoes import ErroPermanente

FONTE_TESOURO = "TESOURO_TAXAS"
FONTE_VLMO = "CVM_VLMO"
FONTE_FRE = "CVM_FRE"
FONTE_CDA = "CVM_CDA"

TESOURO_DESDE = date(2016, 1, 1)
VLMO_RECOMPOSICAO_DESDE = 2018
CDA_MESES = 24
# Meses mais antigos que isto, ja carregados com sucesso, nao fazem nem HEAD
# (a CVM so republica o CDA recente).
CDA_MESES_REVISAVEIS = 3


@dataclass
class ResultadoFonte:
    """Base comum: o `resumo_etapa` le estes campos."""

    itens_processados: list[str] = field(default_factory=list)
    itens_pulados: list[str] = field(default_factory=list)
    gravados: int = 0
    rejeicoes: list[dict] = field(default_factory=list)
    erros: list[str] = field(default_factory=list)


@dataclass
class ResultadoTesouro(ResultadoFonte):
    pass


@dataclass
class ResultadoVlmo(ResultadoFonte):
    recomposicao: bool = False


@dataclass
class ResultadoFre(ResultadoFonte):
    auditores_gravados: int = 0
    dividas_gravadas: int = 0


@dataclass
class ResultadoCda(ResultadoFonte):
    competencia_mais_recente: str | None = None
    sem_arquivo: list[str] = field(default_factory=list)


def _separar(registros, validar, origem: str, rejeicoes: list[dict]) -> list:
    boas = []
    for registro in registros:
        motivo = validar(registro)
        if motivo is None:
            boas.append(registro)
        else:
            rejeicoes.append({"motivo": motivo, "origem": origem})
    return boas


class _Base:
    def __init__(self, fonte, unidade_de_trabalho, repositorio, repositorio_execucao,
                 logger: Logger):
        self._fonte = fonte
        self._uow = unidade_de_trabalho
        self._repo = repositorio
        self._execucao = repositorio_execucao
        self._logger = logger

    def _etag_anterior(self, fonte: str, competencia: str, arquivo: str) -> str | None:
        with self._uow.transacao() as db:
            return self._execucao.etag_da_ultima_execucao(db, fonte, competencia, arquivo)

    def _registrar(self, fonte, competencia, arquivo, status, assinatura=None, linhas=0,
                   erro: str | None = None) -> None:
        with self._uow.transacao() as db:
            self._execucao.registrar(
                db, fonte, competencia, arquivo, status,
                etag=getattr(assinatura, "etag", None),
                last_modified=getattr(assinatura, "last_modified", None),
                tamanho_bytes=getattr(assinatura, "tamanho_bytes", None),
                linhas_carregadas=linhas, mensagem_erro=erro,
            )

    def _registrar_erro(self, fonte, competencia, arquivo, erro: Exception) -> None:
        try:
            self._registrar(fonte, competencia, arquivo, STATUS_ERRO, erro=str(erro)[:1000])
        except Exception:
            self._logger.error("%s %s: nao foi possivel registrar a falha", fonte, competencia,
                               exc_info=True)


class CarregarTesouro(_Base):
    """CSV unico do Tesouro Transparente: baixa so se o ETag mudou."""

    def executar(self, forcar: bool = False, desde: date = TESOURO_DESDE) -> ResultadoTesouro:
        resultado = ResultadoTesouro()
        competencia = "CSV"
        try:
            assinatura = self._fonte.assinatura()
            if not forcar and assinatura.inalterado_em_relacao_a(
                self._etag_anterior(FONTE_TESOURO, competencia, ARQUIVO)
            ):
                self._registrar(FONTE_TESOURO, competencia, ARQUIVO, STATUS_PULADO, assinatura)
                resultado.itens_pulados.append(ARQUIVO)
                return resultado
            taxas = self._fonte.taxas(desde)
            if not taxas:
                raise ErroPermanente(f"CSV do Tesouro sem linhas validas desde {desde}")
            boas = _separar(taxas, motivo_taxa, ARQUIVO, resultado.rejeicoes)
            with self._uow.transacao() as db:
                gravadas = self._repo.salvar_taxas_tesouro(db, boas)
                self._execucao.registrar(
                    db, FONTE_TESOURO, competencia, ARQUIVO, STATUS_SUCESSO,
                    etag=assinatura.etag, last_modified=assinatura.last_modified,
                    tamanho_bytes=assinatura.tamanho_bytes, linhas_carregadas=gravadas,
                )
        except Exception as erro:
            self._registrar_erro(FONTE_TESOURO, competencia, ARQUIVO, erro)
            raise
        resultado.itens_processados.append(ARQUIVO)
        resultado.gravados = gravadas
        self._logger.info("Tesouro: %d taxas gravadas; %d descartadas",
                          gravadas, len(resultado.rejeicoes))
        return resultado


class _BasePorAno(_Base):
    """Esqueleto de VLMO e FRE: um pacote por ano, falha isolada por ano."""

    fonte_nome = ""

    def _ano(self, ano: int, forcar: bool, hoje_ano: int, resultado: ResultadoFonte,
             nome_arquivo: str, assinar, ler_e_gravar) -> None:
        try:
            assinatura = assinar(ano)
            if not forcar and assinatura.inalterado_em_relacao_a(
                self._etag_anterior(self.fonte_nome, str(ano), nome_arquivo)
            ):
                self._registrar(self.fonte_nome, str(ano), nome_arquivo, STATUS_PULADO,
                                assinatura)
                resultado.itens_pulados.append(str(ano))
                return
            with self._uow.transacao() as db:
                gravadas = ler_e_gravar(db, ano)
                self._execucao.registrar(
                    db, self.fonte_nome, str(ano), nome_arquivo, STATUS_SUCESSO,
                    etag=assinatura.etag, last_modified=assinatura.last_modified,
                    tamanho_bytes=assinatura.tamanho_bytes, linhas_carregadas=gravadas,
                )
            resultado.itens_processados.append(str(ano))
            resultado.gravados += gravadas
        except ArquivoAusente as erro:
            if ano >= hoje_ano:
                # o arquivo do ano corrente so existe depois da primeira entrega
                self._logger.info("%s %s ainda nao publicado pela CVM", self.fonte_nome, ano)
                resultado.itens_pulados.append(str(ano))
            else:
                self._falha(resultado, ano, nome_arquivo, erro)
        except Exception as erro:
            self._falha(resultado, ano, nome_arquivo, erro)

    def _falha(self, resultado, ano, nome_arquivo, erro: Exception) -> None:
        mensagem = f"{self.fonte_nome} {ano}: {erro}"
        resultado.erros.append(mensagem)
        self._logger.error("%s", mensagem, exc_info=True)
        self._registrar_erro(self.fonte_nome, str(ano), nome_arquivo, erro)


class CarregarVlmo(_BasePorAno):
    fonte_nome = FONTE_VLMO

    def __init__(self, *args, hoje=date.today, **kwargs):
        super().__init__(*args, **kwargs)
        self._hoje = hoje

    def executar(self, anos: list[int], forcar: bool = False) -> ResultadoVlmo:
        resultado = ResultadoVlmo()
        hoje = self._hoje()
        with self._uow.transacao() as db:
            vazia = self._repo.contar_negociacoes(db) == 0
        if vazia:
            anos = list(range(VLMO_RECOMPOSICAO_DESDE, hoje.year + 1))
            forcar = True
            resultado.recomposicao = True
            self._logger.warning(
                "VLMO: tabela vazia; recompondo %d..%d", anos[0], anos[-1]
            )

        def ler_e_gravar(db, ano: int) -> int:
            negociacoes = ler_vlmo(self._fonte.vlmo(ano), ano)
            boas = _separar(negociacoes, motivo_negociacao, f"VLMO {ano}", resultado.rejeicoes)
            return self._repo.salvar_negociacoes(db, boas)

        for ano in sorted(set(anos)):
            self._ano(ano, forcar, hoje.year, resultado, self._fonte.nome_vlmo(ano),
                      self._fonte.assinatura_vlmo, ler_e_gravar)
        self._logger.info("VLMO: anos %s; %d linhas; %d descartadas; %d erro(s)",
                          resultado.itens_processados, resultado.gravados,
                          len(resultado.rejeicoes), len(resultado.erros))
        return resultado


class CarregarFre(_BasePorAno):
    """Auditor e divida do FRE. Recompras vem do BPP (app/aplicacao/recompras.py)
    e nao tem tabela na V45: aqui nao se persiste."""

    fonte_nome = FONTE_FRE

    def __init__(self, *args, hoje=date.today, **kwargs):
        super().__init__(*args, **kwargs)
        self._hoje = hoje

    def executar(self, anos: list[int], forcar: bool = False) -> ResultadoFre:
        resultado = ResultadoFre()

        def ler_e_gravar(db, ano: int) -> int:
            leitor = LeitorFreEstendido(self._fonte.fre(ano), ano)
            auditores = _separar(leitor.auditores(), motivo_auditor, f"FRE {ano} auditor",
                                 resultado.rejeicoes)
            dividas = _separar(leitor.dividas_valor_mobiliario(), motivo_divida,
                               f"FRE {ano} divida", resultado.rejeicoes)
            a = self._repo.salvar_auditores(db, auditores)
            d = self._repo.salvar_dividas(db, dividas)
            resultado.auditores_gravados += a
            resultado.dividas_gravadas += d
            return a + d

        for ano in sorted(set(anos)):
            self._ano(ano, forcar, self._hoje().year, resultado, self._fonte.nome_fre(ano),
                      self._fonte.assinatura_fre, ler_e_gravar)
        self._logger.info("FRE: anos %s; auditores=%d dividas=%d; %d descartados; %d erro(s)",
                          resultado.itens_processados, resultado.auditores_gravados,
                          resultado.dividas_gravadas, len(resultado.rejeicoes),
                          len(resultado.erros))
        return resultado


def competencias_cda(hoje: date, meses: int = CDA_MESES) -> list[str]:
    """AAAAMM dos ultimos `meses` meses (incluindo o corrente), do mais novo ao mais velho."""
    saida = []
    total = hoje.year * 12 + hoje.month - 1
    for deslocamento in range(meses):
        ano, mes0 = divmod(total - deslocamento, 12)
        saida.append(f"{ano}{mes0 + 1:02d}")
    return saida


def _agregar_posicoes(posicoes) -> list[PosicaoFundoAcao]:
    """Linhas repetidas do mesmo fundo/ativo no mes (custodias diferentes) somam;
    a chave unica da tabela e (competencia, fundo, simbolo)."""
    soma: dict[tuple, PosicaoFundoAcao] = {}
    for p in posicoes:
        chave = (p.competencia.replace(day=1), p.cnpj_fundo, p.simbolo)
        atual = soma.get(chave)
        soma[chave] = p if atual is None else PosicaoFundoAcao(
            competencia=atual.competencia, cnpj_fundo=atual.cnpj_fundo, simbolo=atual.simbolo,
            isin=atual.isin or p.isin, quantidade=atual.quantidade + p.quantidade,
            valor_mercado=atual.valor_mercado + p.valor_mercado,
            pl_fundo=atual.pl_fundo if atual.pl_fundo is not None else p.pl_fundo,
        )
    return list(soma.values())


class CarregarCda(_Base):
    """Posicao de fundos em acoes dos ultimos 24 meses, do mais novo ao mais velho
    (se a carga for interrompida, o mes recente e o anterior ja estao gravados,
    que e o que `fluxo_por_ativo` precisa)."""

    def __init__(self, *args, hoje=date.today, meses: int = CDA_MESES, **kwargs):
        super().__init__(*args, **kwargs)
        self._hoje = hoje
        self._meses = meses

    def executar(self, forcar: bool = False) -> ResultadoCda:
        resultado = ResultadoCda()
        hoje = self._hoje()
        limite_revisao = competencias_cda(hoje, CDA_MESES_REVISAVEIS)[-1]
        for competencia in competencias_cda(hoje, self._meses):
            arquivo = self._fonte.nome_cda(competencia)
            try:
                anterior = self._etag_anterior(FONTE_CDA, competencia, arquivo)
                if not forcar and anterior and competencia < limite_revisao:
                    resultado.itens_pulados.append(competencia)
                    continue
                assinatura = self._fonte.assinatura_cda(competencia)
                if not forcar and assinatura.inalterado_em_relacao_a(anterior):
                    self._registrar(FONTE_CDA, competencia, arquivo, STATUS_PULADO, assinatura)
                    resultado.itens_pulados.append(competencia)
                    continue
                posicoes = ler_cda_acoes(self._fonte.cda(competencia), competencia)
                boas = _separar(_agregar_posicoes(posicoes), motivo_posicao,
                                f"CDA {competencia}", resultado.rejeicoes)
                with self._uow.transacao() as db:
                    gravadas = self._repo.salvar_posicoes_fundo(db, boas)
                    self._execucao.registrar(
                        db, FONTE_CDA, competencia, arquivo, STATUS_SUCESSO,
                        etag=assinatura.etag, last_modified=assinatura.last_modified,
                        tamanho_bytes=assinatura.tamanho_bytes, linhas_carregadas=gravadas,
                    )
                resultado.itens_processados.append(competencia)
                resultado.gravados += gravadas
            except ArquivoAusente:
                resultado.sem_arquivo.append(competencia)
            except Exception as erro:
                mensagem = f"{FONTE_CDA} {competencia}: {erro}"
                resultado.erros.append(mensagem)
                self._logger.error("%s", mensagem, exc_info=True)
                self._registrar_erro(FONTE_CDA, competencia, arquivo, erro)
        disponiveis = resultado.itens_processados + resultado.itens_pulados
        if not disponiveis and not resultado.erros:
            resultado.erros.append("CDA: nenhum arquivo publicado nos ultimos "
                                   f"{self._meses} meses")
        if disponiveis:
            resultado.competencia_mais_recente = max(disponiveis)
        self._logger.info("CDA: processados %s; %d posicoes; %d descartadas; %d erro(s)",
                          resultado.itens_processados, resultado.gravados,
                          len(resultado.rejeicoes), len(resultado.erros))
        return resultado



# ---------------------------------------------------------------- parte 2

FONTE_CADASTRO = "CVM_CADASTRO"
FONTE_IFDATA = "IFDATA"
IFDATA_ATRASO_PUBLICACAO_DIAS = 150
IFDATA_TRIMESTRES = 4


@dataclass
class ResultadoCadastro(ResultadoFonte):
    trocas_auditor: list[str] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)


@dataclass
class ResultadoIfData(ResultadoFonte):
    sem_vinculo: int = 0
    aguardando: list[str] = field(default_factory=list)


class CarregarCadastro(_Base):
    """cad_cia_aberta (retrato atual, ~1,5 MB): so baixa se o ETag mudou.
    Troca de auditor entre o retrato gravado e o novo vira alerta."""

    def __init__(self, *args, hoje=date.today, **kwargs):
        super().__init__(*args, **kwargs)
        self._hoje = hoje

    def executar(self, forcar: bool = False) -> ResultadoCadastro:
        from app.adaptadores.cvm.cadastro import troca_auditor_recente
        from app.dominio.fontes_publicas import cnpj14

        resultado = ResultadoCadastro()
        arquivo = self._fonte.nome_arquivo
        try:
            assinatura = self._fonte.assinatura()
            if not forcar and assinatura.inalterado_em_relacao_a(
                self._etag_anterior(FONTE_CADASTRO, "ATUAL", arquivo)
            ):
                self._registrar(FONTE_CADASTRO, "ATUAL", arquivo, STATUS_PULADO, assinatura)
                resultado.itens_pulados.append(arquivo)
                return resultado
            novos = self._fonte.cadastro()
            boas = []
            for cadastro in novos.values():
                if cnpj14(cadastro.cnpj) is None:
                    resultado.rejeicoes.append({"motivo": "CNPJ_INVALIDO", "origem": arquivo})
                else:
                    boas.append(cadastro)
            with self._uow.transacao() as db:
                anteriores, data_anterior = self._repo.cadastros_gravados(db)
                hoje = self._hoje()
                for atual in boas:
                    if troca_auditor_recente(
                        atual, anteriores.get(atual.cnpj), hoje,
                        data_snapshot_anterior=data_anterior,
                    ):
                        resultado.trocas_auditor.append(atual.cnpj)
                gravados = self._repo.salvar_cadastros(db, boas)
                self._execucao.registrar(
                    db, FONTE_CADASTRO, "ATUAL", arquivo, STATUS_SUCESSO,
                    etag=assinatura.etag, last_modified=assinatura.last_modified,
                    tamanho_bytes=assinatura.tamanho_bytes, linhas_carregadas=gravados,
                )
        except Exception as erro:
            self._registrar_erro(FONTE_CADASTRO, "ATUAL", arquivo, erro)
            raise
        resultado.itens_processados.append(arquivo)
        resultado.gravados = gravados
        if resultado.trocas_auditor:
            resultado.alertas.append(
                f"CVM_CADASTRO: troca de auditor em {len(resultado.trocas_auditor)} "
                f"companhia(s): {', '.join(sorted(resultado.trocas_auditor)[:10])}"
            )
        self._logger.info("Cadastro CVM: %d gravados; %d troca(s) de auditor",
                          gravados, len(resultado.trocas_auditor))
        return resultado


def _fim_de_trimestre(ano: int, trimestre: int) -> date:
    import calendar

    mes = trimestre * 3
    return date(ano, mes, calendar.monthrange(ano, mes)[1])


def trimestres_recentes(hoje: date, quantidade: int = IFDATA_TRIMESTRES) -> list[int]:
    """AAAAMM dos ultimos fins de trimestre ja encerrados, do mais novo ao mais velho."""
    saida = []
    ano, tri = hoje.year, (hoje.month - 1) // 3 + 1
    while len(saida) < quantidade:
        fim = _fim_de_trimestre(ano, tri)
        if fim < hoje:
            saida.append(fim.year * 100 + fim.month)
        tri -= 1
        if tri == 0:
            ano, tri = ano - 1, 4
    return saida


class CarregarIfData(_Base):
    """Indicadores trimestrais de bancos. Tenta os trimestres recentes ainda nao
    gravados; trimestre que a fonte nao entrega e e mais novo que o atraso
    normal de publicacao conta como aguardando (nao e erro)."""

    def __init__(self, *args, hoje=date.today, **kwargs):
        super().__init__(*args, **kwargs)
        self._hoje = hoje

    def executar(self, forcar: bool = False) -> ResultadoIfData:
        resultado = ResultadoIfData()
        hoje = self._hoje()
        for ano_mes in trimestres_recentes(hoje):
            arquivo = f"ifdata_{ano_mes}"
            if not forcar and self._etag_anterior(FONTE_IFDATA, str(ano_mes), arquivo):
                resultado.itens_pulados.append(str(ano_mes))
                continue
            novo = (hoje - _fim_de_trimestre(ano_mes // 100, (ano_mes % 100) // 3)).days
            recente = novo < IFDATA_ATRASO_PUBLICACAO_DIAS
            try:
                indicadores = self._fonte.ler(ano_mes)
                if not indicadores:
                    raise ErroPermanente(f"IF.data sem indicadores em {ano_mes}")
                with self._uow.transacao() as db:
                    por_cnpj = self._repo.tickers_por_cnpj(db)
                    boas = self._ligar(indicadores.values(), por_cnpj, resultado, ano_mes)
                    gravados = self._repo.salvar_indicadores_banco(db, boas)
                    self._execucao.registrar(
                        db, FONTE_IFDATA, str(ano_mes), arquivo, STATUS_SUCESSO,
                        etag=f"ifdata:{ano_mes}", linhas_carregadas=gravados,
                    )
                resultado.itens_processados.append(str(ano_mes))
                resultado.gravados += gravados
            except Exception as erro:
                if recente:
                    self._logger.info("IF.data %s ainda indisponivel: %s", ano_mes, erro)
                    resultado.aguardando.append(str(ano_mes))
                    resultado.itens_pulados.append(str(ano_mes))
                    continue
                mensagem = f"{FONTE_IFDATA} {ano_mes}: {erro}"
                resultado.erros.append(mensagem)
                self._logger.error("%s", mensagem, exc_info=True)
                self._registrar_erro(FONTE_IFDATA, str(ano_mes), arquivo, erro)
        self._logger.info("IF.data: %s; %d gravados; %d sem vinculo; %d erro(s)",
                          resultado.itens_processados, resultado.gravados,
                          resultado.sem_vinculo, len(resultado.erros))
        return resultado

    def _ligar(self, indicadores, por_cnpj: dict[str, str], resultado, ano_mes):
        """Instituicao -> (indicador, cnpj de 14 digitos, ticker ou None).

        CNPJ de 14 digitos entra como veio; raiz de 8 so vira CNPJ quando um unico
        CNPJ de cvm_ticker comeca por ela (nunca se completa filial)."""
        from app.dominio.fontes_publicas import cabe

        saida = []
        for i in indicadores:
            if len(i.cnpj) == 14:
                cnpj = i.cnpj
            else:
                candidatos = {c for c in por_cnpj if c.startswith(i.cnpj)}
                if len(candidatos) != 1:
                    resultado.sem_vinculo += 1
                    continue
                cnpj = next(iter(candidatos))
            if not (cabe(i.basileia, 5) and cabe(i.indice_capital_principal, 5)
                    and cabe(i.inadimplencia, 5) and cabe(i.roe, 5)
                    and cabe(i.ativo_total, 16) and cabe(i.patrimonio_liquido, 16)
                    and cabe(i.carteira_credito, 16)):
                resultado.rejeicoes.append({"motivo": "VALOR_FORA_DA_FAIXA", "origem": cnpj})
                continue
            saida.append((i, cnpj, por_cnpj.get(cnpj)))
        return saida
