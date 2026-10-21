"""Normaliza resultados de casos de uso para o contrato de controle de cargas."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass


ETAPAS_FONTES_PUBLICAS = frozenset(
    {"TESOURO", "CVM_VLMO", "CVM_FRE", "CVM_CDA", "CVM_CADASTRO", "IFDATA"}
)


@dataclass(frozen=True)
class ResumoEtapa:
    status: str
    metricas: dict
    alertas: list[str]
    erros: list[str]


def resumir_etapa(etapa: str, resultado=None, erro: Exception | None = None) -> ResumoEtapa:
    """Converte o retorno heterogêneo das cargas num resultado persistível."""
    if erro is not None:
        return ResumoEtapa("FALHA", {}, [], [str(erro)])

    valores = _valores(resultado)
    alertas: list[str] = []
    erros: list[str] = []
    status = "SUCESSO"

    if etapa == "COTAHIST":
        erros = list(valores.get("erros_opcoes") or []) + list(
            valores.get("erros_mercados") or []
        )
        anos_processados = valores.get("anos_processados", [])
        candles = valores.get("candles_gravados", 0)
        por_ano = valores.get("candles_por_ano", {})
        anos_vazios = [ano for ano in anos_processados if int(por_ano.get(ano, 0)) == 0]
        if not erros and anos_vazios:
            erros.append(f"COTAHIST processou ano(s) sem candles: {anos_vazios}")
        elif not erros and anos_processados and not por_ano and candles == 0:
            erros.append("COTAHIST processou ano(s), mas gravou zero candles")
        if erros:
            status = "FALHA"
        elif valores.get("rejeicoes"):
            status = "ALERTA"
            alertas.append(
                f"COTAHIST: {len(valores['rejeicoes'])} negocio(s) de outros mercados descartado(s)"
            )
        elif not anos_processados and valores.get("anos_pulados") and not valores.get(
            "mercados_processados"
        ):
            status = "SEM_MUDANCA"
    elif etapa in {"TTM", "DVA"}:
        processados = valores.get("anos_processados", [])
        pulados = valores.get("anos_pulados", [])
        gravados = valores.get("indicadores_gravados", 0) if etapa == "TTM" else valores.get(
            "periodos_gravados", 0
        )
        if processados and gravados == 0:
            status = "ALERTA"
            alertas.append(f"{etapa}: ano(s) processado(s), mas nenhum registro foi gravado")
        elif not processados and pulados:
            status = "SEM_MUDANCA"
    elif etapa in {"DFP", "IPE"}:
        erros = list(valores.get("erros", []))
        if erros:
            status = "FALHA"
        elif valores.get("anos_pulados") and not valores.get("anos_processados"):
            status = "SEM_MUDANCA"
    elif etapa in ETAPAS_FONTES_PUBLICAS:
        status, alertas, erros = _status_fonte_publica(etapa, valores)
    elif etapa == "EVENTOS":
        erros = list(valores.get("erros") or [])
        if erros:
            status = "FALHA"
        elif valores.get("datas_ex_descartadas"):
            status = "ALERTA"
            alertas.append(
                f"EVENTOS: {len(valores['datas_ex_descartadas'])} data(s) ex descartada(s)"
            )
        rejeicoes = valores.get("rejeicoes", [])
        metricas = {
            "candidatos": valores.get("candidatos", 0),
            "gravados": valores.get("gravados", 0),
            "rejeitados": len(rejeicoes),
            "rejeitados_por_motivo": _contar_motivos(rejeicoes),
        }
        if "datas_ex_gravadas" in valores:
            metricas["datas_ex_gravadas"] = valores["datas_ex_gravadas"]
            metricas["datas_ex_descartadas"] = len(valores["datas_ex_descartadas"])
        return ResumoEtapa(status, metricas, alertas, erros)
    elif etapa == "CONCILIACAO":
        resumos_obj = getattr(resultado, "resumos", [])
        falhas_graves = [r.mensagem() for r in resumos_obj if r.graves]
        alertas_conciliacao = [r.mensagem() for r in resumos_obj if r.alerta and not r.graves]
        if falhas_graves:
            status, erros = "FALHA", falhas_graves
        elif alertas_conciliacao:
            status, alertas = "ALERTA", alertas_conciliacao
        elif not valores.get("disponivel", True):
            status = "PULADA"
            alertas.append("View de conciliação ainda não disponível")
    elif etapa == "PRONTIDAO":
        if isinstance(resultado, dict):
            valores = resultado
        if valores and not valores.get("pronto", True):
            status = "ALERTA"
            alertas.append("Prontidão operacional incompleta")
    elif etapa == "QUALIDADE_OPCOES":
        if resultado is None:
            status = "SEM_MUDANCA"
        elif isinstance(resultado, dict) and not resultado.get("pronto", True):
            status = "ALERTA"
            alertas.append("Cadeia de opções sem registros válidos suficientes")
    elif etapa in {"LIQUIDEZ", "PRONTIDAO", "QUALIDADE_OPCOES"}:
        if isinstance(resultado, dict):
            if resultado.get("status") == "ERRO":
                status = "FALHA"
                erros = [str(resultado.get("mensagem", "Falha na etapa"))]
            else:
                status = "SUCESSO"
        elif isinstance(resultado, int) and resultado != 0:
            status, erros = "FALHA", [f"Etapa retornou código {resultado}"]
        elif (
            etapa == "LIQUIDEZ"
            and resultado is not None
            and not getattr(resultado, "pregoes", [])
        ):
            status = "SEM_MUDANCA"
    elif etapa == "CHECAGENS" and isinstance(resultado, dict):
        valores = {"ocorrencias": sum(resultado.values()), "por_tipo": resultado}

    if etapa in {"LIQUIDEZ", "PRONTIDAO", "QUALIDADE_OPCOES", "CHECAGENS"}:
        metricas = valores
    else:
        metricas = _metricas_comuns(valores)
    return ResumoEtapa(status, metricas, alertas, erros)


def _status_fonte_publica(etapa: str, valores: dict) -> tuple[str, list[str], list[str]]:
    """FALHA se houve erro de fonte; ALERTA se algum registro foi descartado;
    SEM_MUDANCA se nada foi baixado porque o ETag nao mudou; senao SUCESSO."""
    erros = list(valores.get("erros") or [])
    if erros:
        return "FALHA", [], erros
    alertas = list(valores.get("alertas") or [])
    descartados = len(valores.get("rejeicoes") or [])
    if descartados:
        motivos = _contar_motivos(valores["rejeicoes"])
        alertas.append(f"{etapa}: {descartados} registro(s) descartado(s) {motivos}")
    if alertas:
        return "ALERTA", alertas, []
    if not valores.get("itens_processados") and valores.get("itens_pulados"):
        return "SEM_MUDANCA", [], []
    return "SUCESSO", [], []


def _valores(resultado) -> dict:
    if resultado is None:
        return {}
    if isinstance(resultado, dict):
        return dict(resultado)
    if is_dataclass(resultado):
        return asdict(resultado)
    return {"resultado": resultado}


def _metricas_comuns(valores: dict) -> dict:
    excluir = {"erros", "erros_opcoes", "rejeicoes", "simbolos_com_novidade"}
    metricas = {k: v for k, v in valores.items() if k not in excluir}
    metricas["rejeitados"] = len(valores.get("rejeicoes", []))
    metricas["rejeitados_por_motivo"] = _contar_motivos(valores.get("rejeicoes", []))
    if valores.get("erros_opcoes"):
        metricas["erros_opcoes"] = list(valores["erros_opcoes"])
    return metricas


def _contar_motivos(rejeicoes) -> dict[str, int]:
    motivos: dict[str, int] = {}
    for rejeicao in rejeicoes:
        motivo = getattr(rejeicao, "motivo", None)
        if motivo is None and isinstance(rejeicao, dict):
            motivo = rejeicao.get("motivo")
        chave = str(motivo or "SEM_MOTIVO").split(" (")[0].split(":")[0]
        motivos[chave] = motivos.get(chave, 0) + 1
    return motivos
