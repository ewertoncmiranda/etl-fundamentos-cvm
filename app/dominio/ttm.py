"""Combina DFP e ITR sem confundir fluxo acumulado com trimestre isolado."""

from __future__ import annotations

from datetime import date, timedelta

from app.dominio.modelo import (
    BPA,
    BPP,
    DFC_MD,
    DFC_MI,
    DRE,
    DVA,
    TIPO_DOC_TTM,
    DocumentoContabil,
    LinhaContabil,
)
from app.dominio.texto import normalizar

# DVA e fluxo: proventos dos ultimos 12 meses (plano LAC, L1). A DMPL fica
# fora do TTM: a mesma conta aparece em varias colunas e a chave colidiria.
DEMONSTRACOES_DE_FLUXO = (DRE, DFC_MI, DFC_MD, DVA)
DEMONSTRACOES_DE_ESTOQUE = (BPA, BPP)


def _chave(linha: LinhaContabil) -> tuple[str, str]:
    return linha.cd_conta, normalizar(linha.ds_conta)


class MontadorTtm:
    def montar(
        self,
        dfp_anterior: DocumentoContabil,
        itr_atual: DocumentoContabil,
        itr_anterior: DocumentoContabil,
    ) -> DocumentoContabil:
        if itr_atual.cnpj != itr_anterior.cnpj or itr_atual.cnpj != dfp_anterior.cnpj:
            raise ValueError("DFP e ITRs do TTM precisam pertencer ao mesmo CNPJ")
        if (
            itr_atual.dt_fim_exerc.month,
            itr_atual.dt_fim_exerc.day,
        ) != (itr_anterior.dt_fim_exerc.month, itr_anterior.dt_fim_exerc.day):
            raise ValueError("ITR atual e anterior precisam representar o mesmo corte do ano")

        linhas: dict[str, tuple[LinhaContabil, ...]] = {}
        for demonstracao in DEMONSTRACOES_DE_ESTOQUE:
            linhas[demonstracao] = itr_atual.da_demonstracao(demonstracao)
        for demonstracao in DEMONSTRACOES_DE_FLUXO:
            linhas[demonstracao] = tuple(
                self._combinar_fluxo(
                    dfp_anterior.da_demonstracao(demonstracao),
                    itr_atual.da_demonstracao(demonstracao),
                    itr_anterior.da_demonstracao(demonstracao),
                    itr_atual.dt_fim_exerc,
                )
            )

        return DocumentoContabil(
            cnpj=itr_atual.cnpj,
            tipo_doc=TIPO_DOC_TTM,
            grupo=itr_atual.grupo,
            versao=max(dfp_anterior.versao, itr_atual.versao, itr_anterior.versao),
            dt_refer=itr_atual.dt_refer,
            dt_fim_exerc=itr_atual.dt_fim_exerc,
            linhas=linhas,
        )

    def _combinar_fluxo(
        self,
        anual: tuple[LinhaContabil, ...],
        acumulado_atual: tuple[LinhaContabil, ...],
        acumulado_anterior: tuple[LinhaContabil, ...],
        fim: date,
    ) -> list[LinhaContabil]:
        mapa_anual = {_chave(linha): linha for linha in anual}
        mapa_anterior = {_chave(linha): linha for linha in acumulado_anterior}
        try:
            corte_anterior = fim.replace(year=fim.year - 1)
        except ValueError:  # 29/02 não existe no ano anterior.
            corte_anterior = date(fim.year - 1, 2, 28)
        inicio = corte_anterior + timedelta(days=1)
        saida = []
        for atual in acumulado_atual:
            chave = _chave(atual)
            linha_anual = mapa_anual.get(chave)
            linha_anterior = mapa_anterior.get(chave)
            if linha_anual is None or linha_anterior is None:
                continue
            saida.append(
                LinhaContabil(
                    cd_conta=atual.cd_conta,
                    ds_conta=atual.ds_conta,
                    vl_conta=linha_anual.vl_conta + atual.vl_conta - linha_anterior.vl_conta,
                    conta_fixa=atual.conta_fixa,
                    demonstracao=atual.demonstracao,
                    dt_ini_exerc=inicio,
                    dt_fim_exerc=fim,
                )
            )
        return saida
