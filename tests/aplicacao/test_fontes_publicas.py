"""Etapas TESOURO, CVM_VLMO, CVM_FRE e CVM_CDA: catalogo, status e idempotencia.

Sem rede e sem banco: fontes falsas e repositorio em memoria com as mesmas
chaves unicas da V45.
"""

from __future__ import annotations

import io
import logging
import zipfile
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

import pytest

from app.adaptadores.cvm.cliente_http import Assinatura
from app.adaptadores.cvm.fonte_pacotes import ArquivoAusente
from app.adaptadores.tesouro.leitor_tesouro import TaxaTituloPublico
from app.aplicacao.carregar_fontes_publicas import (
    CarregarCda,
    CarregarFre,
    CarregarTesouro,
    CarregarVlmo,
    competencias_cda,
)
from app.aplicacao.executar_carga import (
    CATALOGO_ETAPAS,
    ETAPAS_ROTINA,
    OrquestradorCargas,
    validar_pedido,
)
from app.aplicacao.resumo_etapa import resumir_etapa
from app.dominio.fontes_publicas import (
    cnpj14,
    hash_divida,
    hash_negociacao,
)
from app.excecoes.excecoes import FonteIndisponivel

NOVAS = ("TESOURO", "CVM_VLMO", "CVM_FRE", "CVM_CDA")
HOJE = date(2026, 10, 20)
LOG = logging.getLogger("teste")
CIA = "00.000.000/0001-91"


# ---------------------------------------------------------------- fakes

class UowFake:
    @contextmanager
    def transacao(self):
        yield object()


class ExecucaoFake:
    def __init__(self):
        self.registros = []

    def etag_da_ultima_execucao(self, _db, fonte, competencia, arquivo):
        for r in reversed(self.registros):
            if r["chave"] == (fonte, competencia, arquivo) and r["status"] == "SUCESSO":
                return r["etag"]
        return None

    def registrar(self, _db, fonte, competencia, arquivo, status, etag=None, **_):
        self.registros.append(
            {"chave": (fonte, competencia, arquivo), "status": status, "etag": etag}
        )


class RepoFake:
    def __init__(self):
        self.taxas, self.auditores, self.negociacoes = {}, {}, {}
        self.dividas, self.posicoes = {}, {}

    def salvar_taxas_tesouro(self, _db, taxas):
        for t in taxas:
            self.taxas[(t.tipo, t.vencimento, t.data_base)] = t
        return len(taxas)

    def salvar_auditores(self, _db, auditores):
        for a in auditores:
            self.auditores[(cnpj14(a.cnpj), a.dt_referencia, cnpj14(a.cnpj_auditor),
                            a.dt_inicio_contratacao)] = a
        return len(auditores)

    def salvar_negociacoes(self, _db, negs):
        for n in negs:
            h = hash_negociacao(n.tipo_empresa, n.tipo_cargo, n.tipo_movimentacao,
                                n.tipo_operacao, n.tipo_ativo, n.caracteristica,
                                n.data_movimentacao, n.quantidade, n.preco_unitario, n.volume)
            self.negociacoes[(n.cnpj, n.data_referencia, n.versao, h)] = n
        return len(negs)

    def contar_negociacoes(self, _db):
        return len(self.negociacoes)

    def salvar_dividas(self, _db, dividas):
        for d in dividas:
            h = hash_divida(d.tipo, d.identificacao, d.dt_emissao, d.dt_vencimento,
                            d.quantidade, d.valor, d.saldo_devedor, d.conversivel)
            self.dividas[(cnpj14(d.cnpj), d.dt_referencia, d.versao, h)] = d
        return len(dividas)

    def salvar_posicoes_fundo(self, _db, posicoes):
        for p in posicoes:
            self.posicoes[(p.competencia.replace(day=1), p.cnpj_fundo, p.simbolo)] = p
        return len(posicoes)


def montar(classe, fonte, **kw):
    repo, execucao = RepoFake(), ExecucaoFake()
    caso = classe(fonte, UowFake(), repo, execucao, LOG, **kw)
    return caso, repo, execucao


# ---------------------------------------------------------------- catalogo

def test_catalogo_e_rotina_incluem_as_etapas_novas():
    for etapa in NOVAS:
        assert etapa in CATALOGO_ETAPAS
        assert etapa in ETAPAS_ROTINA


def test_parcial_aceita_as_etapas_novas_na_ordem_do_catalogo():
    pedido = validar_pedido({"tipo": "PARCIAL", "etapas": ["CVM_CDA", "TESOURO"]})
    assert pedido.etapas == ("TESOURO", "CVM_CDA")


def test_rotina_resolve_anos_das_etapas_novas():
    orq = OrquestradorCargas(None, {})
    anos = orq._resolver_execucao(validar_pedido({"tipo": "ROTINA"}))
    assert all(etapa in anos for etapa in NOVAS)
    assert len(anos["CVM_VLMO"]) == 2  # ano corrente e anterior
    assert len(anos["CVM_FRE"]) == 1


def test_main_expoe_um_callback_para_cada_etapa_do_catalogo():
    from app.config.settings import Settings
    from main import criar_catalogo_etapas

    catalogo = criar_catalogo_etapas(Settings(), LOG)
    assert set(catalogo) == set(CATALOGO_ETAPAS)


# ---------------------------------------------------------------- Tesouro

def _taxa(tipo="Tesouro IPCA+", base=date(2026, 10, 15), taxa="7.40"):
    return TaxaTituloPublico(tipo, date(2029, 5, 15), base, Decimal(taxa), Decimal("7.5"),
                             Decimal("3500"), Decimal("3490"), Decimal("3490"))


class TesouroFake:
    def __init__(self, etag="e1", taxas=None, erro=None):
        self.etag, self.erro, self.downloads = etag, erro, 0
        self.lista = [_taxa(), _taxa(base=date(2026, 10, 14))] if taxas is None else taxas

    def assinatura(self):
        if self.erro:
            raise self.erro
        return Assinatura(self.etag, None, 10)

    def taxas(self, desde=None, usar_cache=False):
        self.downloads += 1
        return list(self.lista)


def test_tesouro_grava_e_segunda_execucao_com_mesmo_etag_nao_baixa():
    fonte = TesouroFake()
    caso, repo, _ = montar(CarregarTesouro, fonte)
    r1 = caso.executar()
    assert resumir_etapa("TESOURO", r1).status == "SUCESSO"
    assert len(repo.taxas) == 2 and fonte.downloads == 1
    r2 = caso.executar()
    assert resumir_etapa("TESOURO", r2).status == "SEM_MUDANCA"
    assert fonte.downloads == 1


def test_tesouro_forcar_regrava_sem_duplicar():
    caso, repo, _ = montar(CarregarTesouro, TesouroFake())
    caso.executar()
    caso.executar(forcar=True)
    assert len(repo.taxas) == 2


def test_tesouro_alerta_quando_descarta_registro():
    fonte = TesouroFake(taxas=[_taxa(), _taxa(tipo=""), _taxa(taxa="999999")])
    caso, repo, _ = montar(CarregarTesouro, fonte)
    resumo = resumir_etapa("TESOURO", caso.executar())
    assert resumo.status == "ALERTA"
    assert len(repo.taxas) == 1
    assert resumo.metricas["rejeitados"] == 2


def test_tesouro_falha_em_erro_de_fonte_e_registra_erro():
    caso, _, execucao = montar(CarregarTesouro, TesouroFake(erro=FonteIndisponivel("HEAD 503")))
    with pytest.raises(FonteIndisponivel) as exc:
        caso.executar()
    resumo = resumir_etapa("TESOURO", None, exc.value)
    assert resumo.status == "FALHA"
    assert execucao.registros[-1]["status"] == "ERRO"


def test_tesouro_csv_vazio_e_falha():
    caso, _, _ = montar(CarregarTesouro, TesouroFake(taxas=[]))
    with pytest.raises(Exception, match="sem linhas"):
        caso.executar()


# ---------------------------------------------------------------- pacotes falsos

class PacotesFake:
    def __init__(self, etag="p1"):
        self.etag = etag
        self.vlmo_zips, self.fre_zips, self.cda_zips = {}, {}, {}
        self.erros = {}
        self.baixados = []

    nome_vlmo = staticmethod(lambda ano: f"vlmo_cia_aberta_{ano}.zip")
    nome_fre = staticmethod(lambda ano: f"fre_cia_aberta_{ano}.zip")
    nome_cda = staticmethod(lambda comp: f"cda_fi_{comp}.zip")

    def _assinar(self, chave, zips):
        if chave in self.erros:
            raise self.erros[chave]
        if chave not in zips:
            raise ArquivoAusente(f"404 {chave}")
        return Assinatura(self.etag, None, 1)

    def assinatura_vlmo(self, ano):
        return self._assinar(ano, self.vlmo_zips)

    def assinatura_fre(self, ano):
        return self._assinar(ano, self.fre_zips)

    def assinatura_cda(self, comp):
        return self._assinar(comp, self.cda_zips)

    def vlmo(self, ano):
        self.baixados.append(("vlmo", ano))
        return self.vlmo_zips[ano]

    def fre(self, ano):
        self.baixados.append(("fre", ano))
        return self.fre_zips[ano]

    def cda(self, comp):
        self.baixados.append(("cda", comp))
        return self.cda_zips[comp]


def _zip(arquivos: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nome, texto in arquivos.items():
            z.writestr(nome, texto.encode("latin-1"))
    return buf.getvalue()


# ---------------------------------------------------------------- VLMO

CAB_CON = (
    "CNPJ_Companhia;Nome_Companhia;Data_Referencia;Versao;Tipo_Empresa;Empresa;Tipo_Cargo;"
    "Tipo_Movimentacao;Descricao_Movimentacao;Tipo_Operacao;Tipo_Ativo;"
    "Caracteristica_Valor_Mobiliario;Intermediario;Data_Movimentacao;Quantidade;Preco_Unitario;Volume"
)
CAB_IDX = "CNPJ_Companhia;Nome_Companhia;Data_Referencia;Versao;Data_Entrega"


def _vlmo_zip(ano, cnpjs=(CIA,)):
    linhas = [
        f"{c};BANCO;{ano}-01-01;1;Companhia;BANCO;Diretor;Compra à vista;;Crédito;Ações;ON;;"
        f"{ano}-01-10;100;10;1000"
        for c in cnpjs
    ]
    return _zip({
        f"vlmo_cia_aberta_con_{ano}.csv": "\n".join([CAB_CON, *linhas]),
        f"vlmo_cia_aberta_{ano}.csv": "\n".join([CAB_IDX, f"{cnpjs[0]};BANCO;{ano}-01-01;1;{ano}-02-01"]),
    })


def test_vlmo_tabela_vazia_recompoe_de_2018_e_depois_fica_sem_mudanca():
    fonte = PacotesFake()
    fonte.vlmo_zips = {a: _vlmo_zip(a) for a in range(2018, 2027)}
    caso, repo, _ = montar(CarregarVlmo, fonte, hoje=lambda: HOJE)

    r1 = caso.executar([2025, 2026])
    assert r1.recomposicao and r1.itens_processados == [str(a) for a in range(2018, 2027)]
    assert resumir_etapa("CVM_VLMO", r1).status == "SUCESSO"
    assert len(repo.negociacoes) == 9

    r2 = caso.executar([2025, 2026])
    assert not r2.recomposicao
    assert resumir_etapa("CVM_VLMO", r2).status == "SEM_MUDANCA"
    assert len(fonte.baixados) == 9  # nada novo baixado


def test_vlmo_forcar_e_idempotente():
    fonte = PacotesFake()
    fonte.vlmo_zips = {a: _vlmo_zip(a) for a in range(2018, 2027)}
    caso, repo, _ = montar(CarregarVlmo, fonte, hoje=lambda: HOJE)
    caso.executar([2026])
    antes = len(repo.negociacoes)
    caso.executar([2025, 2026], forcar=True)
    assert len(repo.negociacoes) == antes


def test_vlmo_alerta_com_cnpj_invalido_descartado():
    fonte = PacotesFake()
    fonte.vlmo_zips = {a: _vlmo_zip(a) for a in range(2018, 2027)}
    fonte.vlmo_zips[2026] = _vlmo_zip(2026, (CIA, "123"))
    caso, repo, _ = montar(CarregarVlmo, fonte, hoje=lambda: HOJE)
    caso.executar([2026])  # recomposicao
    fonte.etag = "novo"
    r = caso.executar([2026])
    resumo = resumir_etapa("CVM_VLMO", r)
    assert resumo.status == "ALERTA" and resumo.metricas["rejeitados"] == 1


def test_vlmo_falha_isolada_por_ano_e_ano_corrente_ausente_nao_e_erro():
    fonte = PacotesFake()
    fonte.vlmo_zips = {2025: _vlmo_zip(2025)}  # 2026 ainda nao publicado
    caso, _, _ = montar(CarregarVlmo, fonte, hoje=lambda: HOJE)
    ok = caso.executar([2025, 2026])
    # tabela vazia: recompoe 2018..2026; anos antigos ausentes sao erro, 2026 nao
    assert any("2018" in e for e in ok.erros) and not any("2026" in e for e in ok.erros)
    assert resumir_etapa("CVM_VLMO", ok).status == "FALHA"
    assert ok.itens_processados == ["2025"]

    fonte2 = PacotesFake()
    fonte2.vlmo_zips = {2025: _vlmo_zip(2025)}
    fonte2.erros = {2026: FonteIndisponivel("503")}
    caso2, repo2, _ = montar(CarregarVlmo, fonte2, hoje=lambda: HOJE)
    repo2.negociacoes[("x",)] = object()  # tabela nao vazia: sem recomposicao
    r = caso2.executar([2025, 2026])
    assert r.itens_processados == ["2025"] and len(r.erros) == 1
    assert resumir_etapa("CVM_VLMO", r).status == "FALHA"


# ---------------------------------------------------------------- FRE

AUD_COLS = ("CNPJ_Companhia;Data_Referencia;Versao;Auditor;CNPJ_Auditor;"
            "Data_Inicio_Contratacao;Data_Fim_Contratacao;Justificativa_Substituicao;"
            "Razao_Apresentada")
DIV_COLS = ("CNPJ_Companhia;Data_Referencia;Versao;Valor_Mobiliario;"
            "Identificacao_Valor_Mobiliario;Data_Emissao;Data_Vencimento;Quantidade;Valor;"
            "Saldo_Devedor;Conversibilidade")


def _fre_zip(ano, cnpj_auditor="61.562.112/0001-20"):
    return _zip({
        f"fre_cia_aberta_auditor_{ano}.csv": "\n".join([
            AUD_COLS,
            f"{CIA};{ano}-12-31;1;KPMG;{cnpj_auditor};2020-01-01;;N/A;",
        ]),
        f"fre_cia_aberta_outro_valor_mobiliario_{ano}.csv": "\n".join([
            DIV_COLS,
            f"{CIA};{ano}-12-31;1;Debênture;DEB1;2020-01-01;2030-01-01;10;1000;900;Não",
        ]),
    })


def test_fre_grava_auditor_e_divida_e_pula_com_mesmo_etag():
    fonte = PacotesFake()
    fonte.fre_zips = {2026: _fre_zip(2026)}
    caso, repo, _ = montar(CarregarFre, fonte, hoje=lambda: HOJE)
    r1 = caso.executar([2026])
    assert resumir_etapa("CVM_FRE", r1).status == "SUCESSO"
    assert (r1.auditores_gravados, r1.dividas_gravadas) == (1, 1)
    r2 = caso.executar([2026])
    assert resumir_etapa("CVM_FRE", r2).status == "SEM_MUDANCA"
    caso.executar([2026], forcar=True)
    assert len(repo.auditores) == 1 and len(repo.dividas) == 1


def test_fre_alerta_quando_descarta_e_falha_quando_fonte_cai():
    fonte = PacotesFake()
    fonte.fre_zips = {2026: _fre_zip(2026, cnpj_auditor="")}
    caso, repo, _ = montar(CarregarFre, fonte, hoje=lambda: HOJE)
    r = caso.executar([2026])
    assert resumir_etapa("CVM_FRE", r).status == "ALERTA" and not repo.auditores

    fonte.erros = {2026: FonteIndisponivel("HEAD 503")}
    caso2, _, execucao = montar(CarregarFre, fonte, hoje=lambda: HOJE)
    r2 = caso2.executar([2026])
    assert resumir_etapa("CVM_FRE", r2).status == "FALHA"
    assert execucao.registros[-1]["status"] == "ERRO"


def test_fre_ano_corrente_ainda_nao_publicado_e_sem_mudanca_nao_falha():
    caso, _, _ = montar(CarregarFre, PacotesFake(), hoje=lambda: HOJE)
    assert resumir_etapa("CVM_FRE", caso.executar([2026])).status == "SEM_MUDANCA"


# ---------------------------------------------------------------- CDA

CAB4 = ("TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;DENOM_SOCIAL;DT_COMPTC;TP_APLIC;TP_ATIVO;"
        "EMISSOR_LIGADO;TP_NEGOC;QT_VENDA_NEGOC;VL_VENDA_NEGOC;QT_AQUIS_NEGOC;VL_AQUIS_NEGOC;"
        "QT_POS_FINAL;VL_MERC_POS_FINAL;VL_CUSTO_POS_FINAL;DT_CONFID_APLIC;CD_ATIVO;DS_ATIVO;"
        "CD_ISIN;DT_INI_VIGENCIA;DT_FIM_VIGENCIA")
CAB_PL = "TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;DENOM_SOCIAL;DT_COMPTC;VL_PATRIM_LIQ"


def _cda_zip(comp, fundos=("00.102.322/0001-41",)):
    dt = f"{comp[:4]}-{comp[4:]}-28"
    b4 = [
        f"FIF;{f};FUNDO;{dt};Ações;Ação;N;;0;0;0;0;100;3500;0;;ITUB3;X;BRITUB;;"
        for f in fundos
    ]
    pl = [f"FIF;{f};FUNDO;{dt};1000000" for f in fundos]
    return _zip({
        f"cda_fi_BLC_4_{comp}.csv": "\n".join([CAB4, *b4]),
        f"cda_fi_PL_{comp}.csv": "\n".join([CAB_PL, *pl]),
    })


def test_competencias_cda_sao_24_meses_do_mais_novo_ao_mais_velho():
    comps = competencias_cda(HOJE)
    assert len(comps) == 24 and comps[0] == "202610" and comps[-1] == "202411"


def test_cda_guarda_mes_recente_e_anterior_e_so_rebaixa_com_etag_novo():
    fonte = PacotesFake()
    fonte.cda_zips = {"202609": _cda_zip("202609"), "202608": _cda_zip("202608")}
    caso, repo, _ = montar(CarregarCda, fonte, hoje=lambda: HOJE)
    r1 = caso.executar()
    assert resumir_etapa("CVM_CDA", r1).status == "SUCESSO"
    assert r1.itens_processados == ["202609", "202608"]
    assert sorted(k[0] for k in repo.posicoes) == [date(2026, 8, 1), date(2026, 9, 1)]
    assert r1.competencia_mais_recente == "202609"

    r2 = caso.executar()
    assert resumir_etapa("CVM_CDA", r2).status == "SEM_MUDANCA"
    assert len(fonte.baixados) == 2

    caso.executar(forcar=True)
    assert len(repo.posicoes) == 2


def test_cda_alerta_com_fundo_de_cnpj_invalido_e_falha_sem_nenhum_arquivo():
    fonte = PacotesFake()
    fonte.cda_zips = {"202609": _cda_zip("202609", ("00.102.322/0001-41", "123"))}
    caso, repo, _ = montar(CarregarCda, fonte, hoje=lambda: HOJE)
    r = caso.executar()
    assert resumir_etapa("CVM_CDA", r).status == "ALERTA" and len(repo.posicoes) == 1

    vazio, _, _ = montar(CarregarCda, PacotesFake(), hoje=lambda: HOJE)
    assert resumir_etapa("CVM_CDA", vazio.executar()).status == "FALHA"


def test_cda_erro_de_fonte_num_mes_e_falha_mas_nao_impede_os_outros():
    fonte = PacotesFake()
    fonte.cda_zips = {"202608": _cda_zip("202608")}
    fonte.erros = {"202609": FonteIndisponivel("503")}
    caso, repo, _ = montar(CarregarCda, fonte, hoje=lambda: HOJE)
    r = caso.executar()
    assert resumir_etapa("CVM_CDA", r).status == "FALHA"
    assert r.itens_processados == ["202608"] and len(repo.posicoes) == 1
