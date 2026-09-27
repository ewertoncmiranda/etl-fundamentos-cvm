"""Catalogo de regras: o de-para entre contas da CVM e metricas do mart.

Metrica nova e uma RegraConta a mais aqui, sem tocar no resolvedor.

Todos os rotulos foram lidos dos CSVs reais do DFP 2025, nao inventados. O
problema que este catalogo resolve: CD_CONTA nao e estavel entre companhias.

    Patrimonio Liquido Consolidado -> 2.03 na WEG, 2.07 no BBAS3, 2.08 no ITUB4
    Conta 3.05  -> EBIT na WEG, lucro antes dos tributos no BBAS3
    Conta 1.01  -> Ativo Circulante na WEG, Caixa e Equivalentes no BBAS3

Mapear por codigo produz numero errado em silencio, que e pior que numero
ausente. A chave estavel e o par (ST_CONTA_FIXA='S', DS_CONTA): a CVM
padroniza a descricao das contas obrigatorias mesmo quando a posicao muda.
"""

from __future__ import annotations

from app.dominio.modelo import BPA, BPP, DFC_MI, DRE, PLANO_GERAL
from app.dominio.plano_contas.regra import RegraConta

# --- estaveis nos tres planos ----------------------------------------------

_ESTAVEIS = (
    RegraConta(
        metrica="lucro_liquido",
        demonstracao=DRE,
        rotulos=(
            "lucro/prejuizo consolidado do periodo",
            "lucro ou prejuizo liquido consolidado do periodo",
            "lucro/prejuizo do periodo",
            "lucro ou prejuizo liquido do periodo",
        ),
        codigos=("3.11",),
        observacao="3.11 coincide em GERAL e FINANCEIRO, mas quem manda e o rotulo",
    ),
    RegraConta(
        metrica="patrimonio_liquido",
        demonstracao=BPP,
        rotulos=("patrimonio liquido consolidado", "patrimonio liquido"),
        codigos=("2.03",),
        observacao="codigo varia: 2.03 WEGE3, 2.07 BBAS3, 2.08 ITUB4",
    ),
    RegraConta(
        metrica="lucro_liquido_controlador",
        demonstracao=DRE,
        rotulos=("atribuido a socios da empresa controladora",),
        codigos=("3.11.01",),
        observacao="parcela do lucro que cabe ao acionista da propria companhia",
    ),
    RegraConta(
        metrica="participacao_nao_controladores",
        demonstracao=BPP,
        rotulos=("participacao dos acionistas nao controladores",),
        codigos=("2.03.09",),
        observacao="subtraida do PL consolidado para chegar ao PL do controlador",
    ),
    RegraConta(
        metrica="caixa_equivalentes",
        demonstracao=BPA,
        rotulos=("caixa e equivalentes de caixa",),
        codigos=("1.01.01",),
        observacao="no plano FINANCEIRO o mesmo rotulo aparece em 1.01",
    ),
    RegraConta(
        metrica="fluxo_caixa_operacional",
        demonstracao=DFC_MI,
        rotulos=(
            "caixa liquido atividades operacionais",
            "caixa liquido das atividades operacionais",
        ),
        codigos=("6.01",),
        observacao="a DFC e a unica demonstracao com posicao estavel entre planos",
    ),
    RegraConta(
        metrica="fluxo_caixa_investimento",
        demonstracao=DFC_MI,
        rotulos=(
            "caixa liquido atividades de investimento",
            "caixa liquido das atividades de investimento",
        ),
        codigos=("6.02",),
    ),
)

# --- exclusivas do plano GERAL ---------------------------------------------
# No plano FINANCEIRO estas contas existem com o mesmo codigo mas significado
# diferente, entao a regra e restrita por plano de proposito.

_SO_GERAL = (
    RegraConta(
        metrica="receita_liquida",
        demonstracao=DRE,
        rotulos=("receita de venda de bens e/ou servicos",),
        codigos=("3.01",),
        planos=(PLANO_GERAL,),
        observacao="3.01 no banco e Receitas de Intermediacao Financeira",
    ),
    RegraConta(
        metrica="ebit",
        demonstracao=DRE,
        rotulos=("resultado antes do resultado financeiro e dos tributos",),
        codigos=("3.05",),
        planos=(PLANO_GERAL,),
        observacao="3.05 no banco e Resultado antes dos Tributos, nao EBIT",
    ),
    RegraConta(
        metrica="divida_bruta",
        demonstracao=BPP,
        rotulos=("emprestimos e financiamentos",),
        codigos=("2.01.04", "2.02.01"),
        planos=(PLANO_GERAL,),
        somar=True,
        observacao="circulante + nao circulante; banco nao tem divida nesse sentido",
    ),
)

REGRAS: tuple[RegraConta, ...] = _ESTAVEIS + _SO_GERAL

# Auxiliar, fora de REGRAS: nao vira coluna do mart. So serve para conferir a
# divisao 3.11.01/3.11.02 quando a parcela do controlador vem zerada.
LUCRO_NAO_CONTROLADORES = RegraConta(
    metrica="lucro_nao_controladores",
    demonstracao=DRE,
    rotulos=("atribuido a socios nao controladores",),
    codigos=("3.11.02",),
)

# Metricas derivadas e os insumos de que dependem. Faltou insumo, a derivada
# nao e calculada - nunca estimada.
DERIVADAS: dict[str, tuple[str, ...]] = {
    "lpa": ("lucro_liquido_controlador", "acoes_ex_tesouraria"),
    "vpa": ("patrimonio_liquido", "acoes_ex_tesouraria"),
    "roe": ("lucro_liquido_controlador", "patrimonio_liquido"),
    "roic": ("ebit", "patrimonio_liquido", "divida_bruta", "caixa_equivalentes"),
    "margem_liquida": ("lucro_liquido", "receita_liquida"),
    "divida_liquida": ("divida_bruta", "caixa_equivalentes"),
    "fluxo_caixa_livre": ("fluxo_caixa_operacional", "fluxo_caixa_investimento"),
}

# capex nao e extraivel: as contas 6.02.xx sao ST_CONTA_FIXA='N', ou seja texto
# livre por companhia ("Imobilizado", "Aquisicao de participacao societaria").
# Fica None e o FCL usa o total de investimento como proxy, declarado como tal.
METRICAS_NAO_EXTRAIVEIS: dict[str, str] = {
    "capex": "contas 6.02.xx sao texto livre (ST_CONTA_FIXA=N), sem padronizacao",
}


def regras_do_plano(plano: str) -> tuple[RegraConta, ...]:
    return tuple(r for r in REGRAS if r.vale_para(plano))


def regras_fora_do_plano(plano: str) -> tuple[RegraConta, ...]:
    return tuple(r for r in REGRAS if not r.vale_para(plano))
