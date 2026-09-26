"""Junta classificacao, resolucao e calculo num unico Indicadores.

E o servico de dominio: recebe um DocumentoContabil e a composicao de capital
(ambos ja normalizados pelo adaptador) e devolve o registro pronto para o mart,
com a procedencia de cada metrica no cobertura.
"""

from __future__ import annotations

from decimal import Decimal

from app.dominio.calculo.calculadora_indicadores import CalculadoraIndicadores
from app.dominio.modelo import (
    TIPO_DOC_DFP,
    ComposicaoCapital,
    DocumentoContabil,
    Indicadores,
)
from app.dominio.plano_contas.catalogo import (
    METRICAS_NAO_EXTRAIVEIS,
    regras_do_plano,
    regras_fora_do_plano,
)
from app.dominio.plano_contas.classificador import ClassificadorDePlano
from app.dominio.plano_contas.resolvedor import ResolvedorDeContas

TIPO_PERIODO_ANUAL = "ANUAL"
TIPO_PERIODO_TRIMESTRAL = "TRIMESTRAL"


class MontadorDeIndicadores:
    def __init__(
        self,
        classificador: ClassificadorDePlano,
        resolvedor: ResolvedorDeContas,
        calculadora: CalculadoraIndicadores,
    ):
        self._classificador = classificador
        self._resolvedor = resolvedor
        self._calculadora = calculadora

    def montar(
        self,
        simbolo: str,
        documento: DocumentoContabil,
        capital: ComposicaoCapital | None,
    ) -> Indicadores:
        plano = self._classificador.classificar(documento)

        insumos: dict[str, Decimal | None] = {}
        cobertura: dict[str, dict] = {}

        for regra in regras_do_plano(plano):
            achado = self._resolvedor.resolver(
                regra, documento.da_demonstracao(regra.demonstracao)
            )
            insumos[regra.metrica] = achado.valor
            cobertura[regra.metrica] = {
                "estrategia": achado.estrategia,
                "cd_conta": achado.cd_conta,
                "motivo": achado.motivo,
            }

        # Metricas do catalogo que este plano de contas nao comporta: None de
        # proposito, com a razao. Ausencia explicita e melhor que numero errado.
        for regra in regras_fora_do_plano(plano):
            insumos.setdefault(regra.metrica, None)
            cobertura[regra.metrica] = {
                "estrategia": "nao-aplicavel",
                "cd_conta": None,
                "motivo": f"plano {plano}: {regra.observacao or 'sem equivalente'}",
            }

        for metrica, razao in METRICAS_NAO_EXTRAIVEIS.items():
            insumos.setdefault(metrica, None)
            cobertura[metrica] = {
                "estrategia": "nao-extraivel",
                "cd_conta": None,
                "motivo": razao,
            }

        acoes = capital.acoes_ex_tesouraria if capital else None
        cobertura["acoes_ex_tesouraria"] = self._cobertura_do_capital(capital)

        derivados = self._calculadora.calcular(insumos, acoes)

        return Indicadores(
            simbolo=simbolo,
            cnpj=documento.cnpj,
            periodo=documento.dt_fim_exerc,
            tipo_periodo=(
                TIPO_PERIODO_ANUAL
                if documento.tipo_doc == TIPO_DOC_DFP
                else TIPO_PERIODO_TRIMESTRAL
            ),
            tipo_doc=documento.tipo_doc,
            grupo=documento.grupo,
            versao_cvm=documento.versao,
            plano_contas=plano,
            lucro_liquido=insumos.get("lucro_liquido"),
            patrimonio_liquido=insumos.get("patrimonio_liquido"),
            lucro_liquido_controlador=insumos.get("lucro_liquido_controlador"),
            participacao_nao_controladores=insumos.get("participacao_nao_controladores"),
            receita_liquida=insumos.get("receita_liquida"),
            ebit=insumos.get("ebit"),
            divida_bruta=insumos.get("divida_bruta"),
            caixa_equivalentes=insumos.get("caixa_equivalentes"),
            fluxo_caixa_operacional=insumos.get("fluxo_caixa_operacional"),
            capex=insumos.get("capex"),
            acoes_ex_tesouraria=acoes,
            lpa=derivados["lpa"],
            vpa=derivados["vpa"],
            roe=derivados["roe"],
            roic=derivados["roic"],
            margem_liquida=derivados["margem_liquida"],
            divida_liquida=derivados["divida_liquida"],
            fluxo_caixa_livre=derivados["fluxo_caixa_livre"],
            cobertura=cobertura,
        )

    @staticmethod
    def _cobertura_do_capital(capital: ComposicaoCapital | None) -> dict:
        if capital is None:
            return {
                "estrategia": "ausente",
                "cd_conta": None,
                "motivo": "sem composicao de capital para o CNPJ",
            }
        motivo = ""
        if capital.escala_aplicada != 1:
            motivo = (
                f"DFP reescalado x{capital.escala_aplicada} "
                f"(FRE/DFP={capital.divergencia_fre_dfp})"
            )
        return {
            "estrategia": f"fonte:{capital.fonte}",
            "cd_conta": None,
            "motivo": motivo,
        }
