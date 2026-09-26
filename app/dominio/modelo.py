"""Modelo de dominio do ETL de fundamentos.

Puro de proposito: nada aqui importa SQLAlchemy, requests, boto3 ou zipfile.
E o que permite testar o de-para sem banco, sem rede e sem arquivo - os testes
montam LinhaContabil na mao.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

# Planos de contas distintos identificados nos dados da CVM. O mesmo CD_CONTA
# significa coisas diferentes em cada um, por isso o de-para consulta o plano
# antes de mapear receita, EBIT e margens.
PLANO_GERAL = "GERAL"
PLANO_FINANCEIRO = "FINANCEIRO"
PLANO_SEGURADORA = "SEGURADORA"

TODOS_OS_PLANOS = (PLANO_GERAL, PLANO_FINANCEIRO, PLANO_SEGURADORA)

# Demonstracoes que o ETL carrega.
BPA = "BPA"
BPP = "BPP"
DRE = "DRE"
DFC_MI = "DFC_MI"

TIPO_DOC_DFP = "DFP"
TIPO_DOC_ITR = "ITR"
TIPO_DOC_TTM = "TTM"

GRUPO_CONSOLIDADO = "con"
GRUPO_INDIVIDUAL = "ind"

# Status de uma execucao do ETL. Vocabulario de negocio, nao detalhe de
# persistencia - por isso mora aqui e nao no adaptador, senao a camada de
# aplicacao precisaria importar SQLAlchemy so para citar "SUCESSO".
STATUS_SUCESSO = "SUCESSO"
STATUS_PULADO = "PULADO"
STATUS_ERRO = "ERRO"
STATUS_EM_ANDAMENTO = "EM_ANDAMENTO"


@dataclass(frozen=True)
class LinhaContabil:
    """Uma conta de uma demonstracao, ja normalizada pela camada de adaptador.

    Quando chega aqui ja passou por: filtro ORDEM_EXERC='ULTIMO', selecao da
    maior VERSAO e conversao de ESCALA_MOEDA para reais. O dominio confia
    nisso e nao refaz nenhuma dessas checagens.
    """

    cd_conta: str
    ds_conta: str
    vl_conta: Decimal
    conta_fixa: bool
    demonstracao: str
    dt_ini_exerc: date
    dt_fim_exerc: date

    def e_descendente_de(self, outra: LinhaContabil) -> bool:
        """2.01.04.01 e descendente de 2.01.04; 2.01.05 nao e."""
        return self.cd_conta.startswith(outra.cd_conta + ".")

    @property
    def profundidade(self) -> int:
        return self.cd_conta.count(".")


@dataclass(frozen=True)
class Empresa:
    cnpj: str
    denominacao: str
    cd_cvm: str | None = None
    setor: str | None = None
    plano_contas: str = PLANO_GERAL


@dataclass(frozen=True)
class Ticker:
    simbolo: str
    cnpj: str
    tipo_valor_mobiliario: str | None = None
    mercado: str | None = None


@dataclass(frozen=True)
class ComposicaoCapital:
    """Quantidade de acoes, resolvida pelo adaptador.

    A composicao do DFP nao tem unidade padronizada (a WEG declara unidades, a
    VALE declara milhares no mesmo campo), entao o adaptador cruza com o FRE e
    entrega aqui o numero ja corrigido, com a procedencia junto.
    """

    cnpj: str
    dt_refer: date
    acoes_ex_tesouraria: int
    fonte: str
    escala_aplicada: int = 1
    divergencia_fre_dfp: float | None = None


@dataclass(frozen=True)
class DocumentoContabil:
    """As demonstracoes de uma companhia num periodo."""

    cnpj: str
    tipo_doc: str
    grupo: str
    versao: int
    dt_refer: date
    dt_fim_exerc: date
    linhas: dict[str, tuple[LinhaContabil, ...]] = field(default_factory=dict)

    def da_demonstracao(self, demonstracao: str) -> tuple[LinhaContabil, ...]:
        return self.linhas.get(demonstracao, ())

    @property
    def vazio(self) -> bool:
        return not any(self.linhas.values())


@dataclass(frozen=True)
class ContaResolvida:
    """Resultado de uma resolucao, com a procedencia que vai no cobertura_json."""

    metrica: str
    valor: Decimal | None
    estrategia: str
    cd_conta: str | None = None
    ds_conta: str | None = None
    motivo: str = ""

    @property
    def ausente(self) -> bool:
        return self.valor is None


@dataclass(frozen=True)
class Indicadores:
    """O que o ETL grava em indicador_fundamentalista.

    Metrica que o plano de contas da companhia nao comporta fica None de
    proposito e a razao vai em `cobertura` - ausencia explicita e melhor que
    numero errado.
    """

    simbolo: str
    cnpj: str
    periodo: date
    tipo_periodo: str
    tipo_doc: str
    grupo: str
    versao_cvm: int
    plano_contas: str

    # insumos
    lucro_liquido: Decimal | None = None
    patrimonio_liquido: Decimal | None = None
    # LPA, VPA e ROE sao calculados sobre a parcela do controlador, que e a
    # convencao das referencias de mercado. Sem isso a WEG sai com ROE 36,5%
    # contra 33,2% do Fundamentus - diferenca de participacao de terceiros.
    lucro_liquido_controlador: Decimal | None = None
    participacao_nao_controladores: Decimal | None = None
    receita_liquida: Decimal | None = None
    ebit: Decimal | None = None
    divida_bruta: Decimal | None = None
    caixa_equivalentes: Decimal | None = None
    fluxo_caixa_operacional: Decimal | None = None
    capex: Decimal | None = None
    acoes_ex_tesouraria: int | None = None

    # derivados
    lpa: Decimal | None = None
    vpa: Decimal | None = None
    roe: Decimal | None = None
    roic: Decimal | None = None
    margem_liquida: Decimal | None = None
    divida_liquida: Decimal | None = None
    fluxo_caixa_livre: Decimal | None = None

    # DT_RECEB da CVM: quando esta versao do documento ficou publica. E a
    # data que o backtest usa para nao enxergar balanco antes da hora.
    data_entrega: date | None = None

    fonte: str = "CVM"
    cobertura: dict = field(default_factory=dict)
