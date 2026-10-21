"""Cadastro aberto CVM: CSV latin-1; não contém data de início do auditor.

DT_INI_RESP pertence ao responsável pelo cadastro, não ao auditor. A ausência
de data é preservada; comparar snapshots detecta troca, mas não inventa início.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, timedelta

from app.adaptadores.cvm.cache_local import CacheDeArquivos
from app.adaptadores.cvm.cliente_http import ClienteHttpCvm
from app.adaptadores.cvm.leitor_pacote import DELIMITADOR_CVM, ENCODING_CVM
from app.excecoes.excecoes import PacoteInvalido

CAMINHO_CADASTRO = "CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"


@dataclass(frozen=True)
class CadastroCvm:
    cnpj: str
    situacao: str | None
    data_situacao: date | None
    setor: str | None
    auditor: str | None
    cnpj_auditor: str | None
    data_inicio_auditor: date | None = None


def ler_cadastro(conteudo: bytes) -> dict[str, CadastroCvm]:
    leitor = csv.DictReader(
        io.StringIO(conteudo.decode(ENCODING_CVM), newline=""), delimiter=DELIMITADOR_CVM
    )
    obrigatorias = {"CNPJ_CIA", "SIT", "DT_INI_SIT", "SETOR_ATIV", "AUDITOR", "CNPJ_AUDITOR"}
    if not obrigatorias.issubset(leitor.fieldnames or []):
        raise PacoteInvalido("Cadastro CVM sem as colunas obrigatorias")
    resultado = {}
    for linha in leitor:
        cnpj = re.sub(r"\D", "", linha["CNPJ_CIA"] or "")
        if not cnpj:
            continue
        if len(cnpj) != 14:
            raise PacoteInvalido(f"CNPJ invalido no cadastro CVM: {cnpj}")
        texto_data = (linha["DT_INI_SIT"] or "").strip()
        resultado[cnpj] = CadastroCvm(
            cnpj=cnpj,
            situacao=(linha["SIT"] or "").strip() or None,
            data_situacao=date.fromisoformat(texto_data) if texto_data else None,
            setor=(linha["SETOR_ATIV"] or "").strip() or None,
            auditor=(linha["AUDITOR"] or "").strip() or None,
            cnpj_auditor=re.sub(r"\D", "", linha["CNPJ_AUDITOR"] or "") or None,
        )
    return resultado


def troca_auditor_recente(
    atual: CadastroCvm,
    anterior: CadastroCvm | None,
    referencia: date,
    dias: int = 365,
    data_snapshot_anterior: date | None = None,
) -> bool | None:
    """True: troca na janela; False: sem troca; None: evidência insuficiente.

    Snapshot anterior dentro da janela prova troca recente sem atribuir data
    exata ao início. Primeiro cadastro/ausência de auditor não prova troca.
    """
    if dias < 0:
        raise ValueError("dias deve ser nao negativo")
    if anterior is None:
        return None
    if anterior.cnpj != atual.cnpj:
        raise ValueError("Snapshots devem pertencer ao mesmo CNPJ")
    if data_snapshot_anterior and data_snapshot_anterior > referencia:
        raise ValueError("Snapshot anterior nao pode estar no futuro")
    if anterior.cnpj_auditor and atual.cnpj_auditor:
        antes, depois = anterior.cnpj_auditor, atual.cnpj_auditor
    else:
        antes = (anterior.auditor or "").strip().casefold()
        depois = (atual.auditor or "").strip().casefold()
    if not antes or not depois:
        return None
    if antes == depois:
        return False
    inicio = atual.data_inicio_auditor
    limite = referencia - timedelta(days=dias)
    if inicio is not None:
        return limite <= inicio <= referencia
    if data_snapshot_anterior is not None and limite <= data_snapshot_anterior <= referencia:
        return True
    return None


class LeitorCadastroCvm:
    def __init__(self, cliente: ClienteHttpCvm, cache: CacheDeArquivos):
        self._cliente = cliente
        self._cache = cache

    def ler(self) -> dict[str, CadastroCvm]:
        nome = "cad_cia_aberta.csv"
        assinatura = self._cliente.assinatura(CAMINHO_CADASTRO)
        if self._cache.tem(nome) and assinatura.inalterado_em_relacao_a(self._cache.etag_de(nome)):
            return ler_cadastro(self._cache.ler(nome))
        conteudo = self._cliente.baixar(CAMINHO_CADASTRO)
        cadastro = ler_cadastro(conteudo)
        self._cache.gravar(nome, conteudo, assinatura.etag)
        return cadastro
