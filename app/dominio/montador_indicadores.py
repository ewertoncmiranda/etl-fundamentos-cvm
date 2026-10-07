"""Junta classificacao, resolucao e calculo num unico Indicadores.

E o servico de dominio: recebe um DocumentoContabil e a composicao de capital
(ambos ja normalizados pelo adaptador) e devolve o registro pronto para o mart,
com a procedencia de cada metrica no cobertura.
"""

from __future__ import annotations

from decimal import Decimal

from app.dominio.calculo.calculadora_indicadores import CalculadoraIndicadores
from app.dominio.modelo import (
    DRE,
    GRUPO_INDIVIDUAL,
    TIPO_DOC_DFP,
    TIPO_DOC_TTM,
    ComposicaoCapital,
    DocumentoContabil,
    Indicadores,
)
from app.dominio.plano_contas.catalogo import (
    LUCRO_NAO_CONTROLADORES,
    METRICAS_NAO_EXTRAIVEIS,
    regras_do_plano,
    regras_fora_do_plano,
)
from app.dominio.plano_contas.classificador import ClassificadorDePlano
from app.dominio.plano_contas.resolvedor import ResolvedorDeContas

TIPO_PERIODO_ANUAL = "ANUAL"
TIPO_PERIODO_TRIMESTRAL = "TRIMESTRAL"
TIPO_PERIODO_TTM = "TTM"


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
        self._conciliar_lucro(documento, insumos, cobertura)

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
            tipo_periodo=(TIPO_PERIODO_ANUAL if documento.tipo_doc == TIPO_DOC_DFP else
                          TIPO_PERIODO_TTM if documento.tipo_doc == TIPO_DOC_TTM else
                          TIPO_PERIODO_TRIMESTRAL),
            tipo_doc=documento.tipo_doc,
            grupo=documento.grupo,
            versao_cvm=documento.versao,
            plano_contas=plano,
            lucro_liquido=insumos.get("lucro_liquido"),
            patrimonio_liquido=insumos.get("patrimonio_liquido"),
            ativo_total=insumos.get("ativo_total"),
            ativo_circulante=insumos.get("ativo_circulante"),
            passivo_circulante=insumos.get("passivo_circulante"),
            lucro_bruto=insumos.get("lucro_bruto"),
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

    def _conciliar_lucro(
        self,
        documento: DocumentoContabil,
        insumos: dict[str, Decimal | None],
        cobertura: dict[str, dict],
    ) -> None:
        """Lucro exatamente 0 e conta nao preenchida, nao resultado apurado.

        A CVM exige a linha 3.11.01, mas nao que a companhia a preencha: a TIM
        de 2022 traz 3.11 = 1,67 bi com 3.11.01 e 3.11.02 em 0. Gravar esse 0
        derruba LPA e ROE em silencio. Quando da para recuperar, recupera; senao
        fica None com o motivo.
        """
        total = insumos.get("lucro_liquido")
        controlador = insumos.get("lucro_liquido_controlador")
        cd_total = cobertura.get("lucro_liquido", {}).get("cd_conta")

        if total == 0:
            insumos["lucro_liquido"] = total = None
            cobertura["lucro_liquido"].update(
                estrategia="zerada",
                motivo=f"conta {cd_total} veio 0; tratada como nao preenchida",
            )

        if controlador is None and total is not None and (
            documento.grupo == GRUPO_INDIVIDUAL
        ):
            # Na individual nao ha 3.11.01: o lucro do periodo e da controladora.
            self._controlador_pelo_total(
                insumos, cobertura, total, cd_total,
                "demonstracao individual: lucro do periodo e todo do controlador",
            )
            return

        if controlador != 0:
            return

        if total is None:
            insumos["lucro_liquido_controlador"] = None
            cobertura["lucro_liquido_controlador"].update(
                estrategia="zerada",
                motivo="parcela do controlador e lucro total vieram 0 ou ausentes",
            )
            return

        minoritarios = self._resolvedor.resolver(
            LUCRO_NAO_CONTROLADORES, documento.da_demonstracao(DRE)
        ).valor
        if not minoritarios:
            self._controlador_pelo_total(
                insumos, cobertura, total, cd_total,
                "parcela do controlador e dos nao controladores vieram 0; "
                "divisao nao preenchida, usa o lucro total",
            )
            return

        # 3.11 = 3.11.01 + 3.11.02: com os nao controladores preenchidos, a
        # parcela do controlador sai da identidade (ECOR3 2021: 367 mi de total,
        # -4,8 mi de nao controladores, 3.11.01 em 0).
        derivado = total - minoritarios
        if derivado != 0:
            insumos["lucro_liquido_controlador"] = derivado
            cobertura["lucro_liquido_controlador"] = {
                "estrategia": "derivada",
                "cd_conta": f"{cd_total}-3.11.02",
                "motivo": (
                    "parcela do controlador veio 0; calculada como lucro total "
                    "menos nao controladores"
                ),
            }
            return

        # Nao controladores = total (LREN3 2016 poe o lucro todo ali): a
        # identidade daria 0 e nao da para saber qual das duas contas esta certa.
        insumos["lucro_liquido_controlador"] = None
        cobertura["lucro_liquido_controlador"].update(
            estrategia="inconsistente",
            motivo=(
                f"parcela do controlador veio 0 com nao controladores = "
                f"{minoritarios} e total = {total}; divisao nao confiavel"
            ),
        )

    @staticmethod
    def _controlador_pelo_total(
        insumos: dict[str, Decimal | None],
        cobertura: dict[str, dict],
        total: Decimal,
        cd_total: str | None,
        motivo: str,
    ) -> None:
        insumos["lucro_liquido_controlador"] = total
        cobertura["lucro_liquido_controlador"] = {
            "estrategia": "lucro-total",
            "cd_conta": cd_total,
            "motivo": motivo,
        }

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
