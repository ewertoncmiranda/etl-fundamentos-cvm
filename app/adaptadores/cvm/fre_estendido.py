"""Leitor das tabelas extras do FRE (fre_cia_aberta_{ano}.zip).

Cobre auditor, outros valores mobiliarios (divida) e distribuicao de capital.
Segue o padrao de `_free_float_do_fre`: so a ultima `Versao` vale, aqui por
(CNPJ_Companhia, Data_Referencia). O FRE nao traz recompras nem politica de
dividendos (ver docs/cons/FONTES-ETL-4.md).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from app.adaptadores.cvm.leitor_pacote import LeitorDePacoteCvm
from app.dominio.texto import normalizar

# Textos que a CVM usa como "sem justificativa" (comparados ja normalizados).
_VAZIOS = {
    "",
    "nao aplicavel",
    "n/a",
    "na",
    "n.a",
    "nao se aplica",
    "-",
    "--",
    "nenhum",
    "nenhuma",
    "inexistente",
    "nao ha",
    "nao houve",
    "nao houve substituicao",
}

# Frases que comecam assim so dizem que nao houve troca ("Nao aplicavel, pois
# nao houve substituicao...", "Nao houve substituicao dos auditores...").
_PREFIXO_VAZIO = re.compile(
    r"^(nao aplicavel|nao se aplica|n/a|nao houve (a |qualquer )?substituicao)"
)


@dataclass(frozen=True)
class Auditor:
    cnpj: str
    dt_referencia: date | None
    versao: int
    auditor: str
    cnpj_auditor: str
    dt_inicio_contratacao: date | None
    dt_fim_contratacao: date | None
    justificativa_substituicao: str | None
    razao_apresentada: str | None


@dataclass(frozen=True)
class DividaValorMobiliario:
    cnpj: str
    dt_referencia: date | None
    versao: int
    tipo: str
    identificacao: str
    dt_emissao: date | None
    dt_vencimento: date | None
    quantidade: Decimal | None
    valor: Decimal | None
    saldo_devedor: Decimal | None
    conversivel: bool | None


@dataclass(frozen=True)
class DistribuicaoCapital:
    cnpj: str
    dt_referencia: date | None
    versao: int
    acionistas_pf: int | None
    acionistas_pj: int | None
    acionistas_institucionais: int | None
    qt_acoes_circulacao: int | None
    pct_ordinarias_circulacao: Decimal | None
    pct_preferenciais_circulacao: Decimal | None
    pct_total_circulacao: Decimal | None


class LeitorFreEstendido:
    def __init__(self, conteudo: bytes, ano: int):
        self._conteudo = conteudo
        self._ano = ano

    def _ultimas(self, tabela: str) -> Iterator[dict[str, str]]:
        """Linhas da tabela so da ultima Versao por (CNPJ, Data_Referencia)."""
        arquivo = f"fre_cia_aberta_{tabela}_{self._ano}.csv"
        grupos: dict[tuple[str, str], tuple[int, list[dict[str, str]]]] = {}
        with LeitorDePacoteCvm(self._conteudo, f"fre_cia_aberta_{self._ano}.zip") as leitor:
            if not leitor.tem(arquivo):
                return
            for linha in leitor.linhas(arquivo):
                cnpj = _txt(linha.get("CNPJ_Companhia"))
                if not cnpj:
                    continue
                chave = (cnpj, _txt(linha.get("Data_Referencia")))
                versao = _int(linha.get("Versao")) or 0
                atual = grupos.get(chave)
                if atual is None or versao > atual[0]:
                    grupos[chave] = (versao, [linha])
                elif versao == atual[0]:
                    atual[1].append(linha)
        for _versao, linhas in grupos.values():
            yield from linhas

    def auditores(self) -> list[Auditor]:
        return [
            Auditor(
                cnpj=_txt(lin.get("CNPJ_Companhia")),
                dt_referencia=_data(lin.get("Data_Referencia")),
                versao=_int(lin.get("Versao")) or 0,
                auditor=_txt(lin.get("Auditor")),
                cnpj_auditor=_txt(lin.get("CNPJ_Auditor")),
                dt_inicio_contratacao=_data(lin.get("Data_Inicio_Contratacao")),
                dt_fim_contratacao=_data(lin.get("Data_Fim_Contratacao")),
                justificativa_substituicao=texto_ou_vazio(lin.get("Justificativa_Substituicao")),
                razao_apresentada=texto_ou_vazio(lin.get("Razao_Apresentada")),
            )
            for lin in self._ultimas("auditor")
        ]

    def dividas_valor_mobiliario(self) -> list[DividaValorMobiliario]:
        return [
            DividaValorMobiliario(
                cnpj=_txt(lin.get("CNPJ_Companhia")),
                dt_referencia=_data(lin.get("Data_Referencia")),
                versao=_int(lin.get("Versao")) or 0,
                tipo=_txt(lin.get("Valor_Mobiliario")),
                identificacao=_txt(lin.get("Identificacao_Valor_Mobiliario")),
                dt_emissao=_data(lin.get("Data_Emissao")),
                dt_vencimento=_data(lin.get("Data_Vencimento")),
                quantidade=_dec(lin.get("Quantidade")),
                valor=_dec(lin.get("Valor")),
                saldo_devedor=_dec(lin.get("Saldo_Devedor")),
                conversivel=_sim_nao(lin.get("Conversibilidade")),
            )
            for lin in self._ultimas("outro_valor_mobiliario")
        ]

    def distribuicao_capital(self) -> list[DistribuicaoCapital]:
        return [
            DistribuicaoCapital(
                cnpj=_txt(lin.get("CNPJ_Companhia")),
                dt_referencia=_data(lin.get("Data_Referencia")),
                versao=_int(lin.get("Versao")) or 0,
                acionistas_pf=_int(lin.get("Quantidade_Acionistas_PF")),
                acionistas_pj=_int(lin.get("Quantidade_Acionistas_PJ")),
                acionistas_institucionais=_int(
                    lin.get("Quantidade_Acionistas_Investidores_Institucionais")
                ),
                qt_acoes_circulacao=_int(lin.get("Quantidade_Total_Acoes_Circulacao")),
                pct_ordinarias_circulacao=_dec(lin.get("Percentual_Acoes_Ordinarias_Circulacao")),
                pct_preferenciais_circulacao=_dec(
                    lin.get("Percentual_Acoes_Preferenciais_Circulacao")
                ),
                pct_total_circulacao=_dec(lin.get("Percentual_Total_Acoes_Circulacao")),
            )
            for lin in self._ultimas("distribuicao_capital")
        ]


# ---------------------------------------------------------------- funcoes puras


def troca_recente_de_auditor(
    auditores: Iterable[Auditor], cnpj: str, hoje: date, meses: int = 24
) -> bool:
    """True se a companhia trocou de auditor nos ultimos `meses`.

    Troca = um contrato com inicio dentro da janela e (a) um auditor diferente
    (por CNPJ, ou nome se nao houver CNPJ) contratado antes, ou (b) justificativa
    de substituicao preenchida (ja sem "Nao aplicavel"/"N/A").
    """
    limite = _meses_atras(hoje, meses)
    da_cia = [a for a in auditores if a.cnpj == cnpj and a.dt_inicio_contratacao is not None]
    for novo in da_cia:
        inicio = novo.dt_inicio_contratacao
        assert inicio is not None
        if not (limite <= inicio <= hoje):
            continue
        if novo.justificativa_substituicao:
            return True
        for antigo in da_cia:
            assert antigo.dt_inicio_contratacao is not None
            if antigo.dt_inicio_contratacao < inicio and _id_auditor(antigo) != _id_auditor(novo):
                return True
    return False


def vencimentos_por_ano(
    dividas: Iterable[DividaValorMobiliario], cnpj: str
) -> dict[int, Decimal]:
    """Saldo devedor somado por ano de vencimento (sem vencimento ou saldo: ignorado)."""
    saida: dict[int, Decimal] = {}
    for d in dividas:
        if d.cnpj != cnpj or d.dt_vencimento is None or d.saldo_devedor is None:
            continue
        ano = d.dt_vencimento.year
        saida[ano] = saida.get(ano, Decimal(0)) + d.saldo_devedor
    return dict(sorted(saida.items()))


def texto_ou_vazio(valor: str | None) -> str | None:
    """Texto livre do FRE, ou None quando e so 'Nao aplicavel', 'N/A' e afins."""
    texto = _txt(valor)
    chave = normalizar(texto).rstrip(".").strip()
    return None if chave in _VAZIOS or _PREFIXO_VAZIO.match(chave) else texto


# ---------------------------------------------------------------- auxiliares


def _id_auditor(a: Auditor) -> str:
    return "".join(c for c in a.cnpj_auditor if c.isdigit()) or normalizar(a.auditor)


def _meses_atras(hoje: date, meses: int) -> date:
    total = hoje.year * 12 + hoje.month - 1 - meses
    ano, mes0 = divmod(total, 12)
    mes = mes0 + 1
    ultimo = 29 if mes == 2 else 30 if mes in (4, 6, 9, 11) else 31
    if mes == 2 and not (ano % 4 == 0 and (ano % 100 != 0 or ano % 400 == 0)):
        ultimo = 28
    return date(ano, mes, min(hoje.day, ultimo))


def _txt(valor: str | None) -> str:
    return (valor or "").strip()


def _int(valor: str | None) -> int | None:
    d = _dec(valor)
    return int(d) if d is not None else None


def _dec(valor: str | None) -> Decimal | None:
    texto = _txt(valor).replace(",", ".")
    if not texto:
        return None
    try:
        return Decimal(texto)
    except InvalidOperation:
        return None


def _data(valor: str | None) -> date | None:
    try:
        return date.fromisoformat(_txt(valor)[:10])
    except ValueError:
        return None


def _sim_nao(valor: str | None) -> bool | None:
    n = normalizar(valor)
    if n.startswith("sim"):
        return True
    if n.startswith("nao"):
        return False
    return None
