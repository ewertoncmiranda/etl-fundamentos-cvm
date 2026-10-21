"""IF.data OData v1: cadastro + relatórios Resumo (1) e Capital (5).

Saldo é preservado na unidade publicada: valores monetários em R$ mil,
índices de capital em razão (0.15 = 15%). CNPJ de oito dígitos é raiz, nunca
é completado artificialmente para 14. ROE é TTM / PL médio de 12 meses;
não anualizamos o lucro semestral por simples multiplicação.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import re
import unicodedata
import urllib.error
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode, urljoin

from app.adaptadores.cvm.cache_local import CacheDeArquivos
from app.adaptadores.cvm.cliente_http import ClienteHttpCvm
from app.excecoes.excecoes import FonteIndisponivel, PacoteInvalido

URL_IFDATA = "https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata/"
RELATORIOS = {"1": "Resumo", "5": "Informações de Capital"}
_CAMPOS = {
    "ativo total": "ativo_total",
    "patrimonio liquido": "patrimonio_liquido",
    "carteira de credito classificada": "carteira_credito",
    "carteira de credito": "carteira_credito",
    "indice de basileia": "basileia",
    "indice de capital principal": "indice_capital_principal",
    "capital principal para comparacao com rwa": "capital_principal",
    "capital principal": "capital_principal",
    "inadimplencia": "inadimplencia",
    "roe": "roe",
    "retorno sobre o patrimonio liquido": "roe",
    "lucro liquido": "lucro_liquido",
}


@dataclass(frozen=True)
class IndicadoresIfData:
    cnpj: str
    data_base: date
    cod_inst: str
    tipo_instituicao: int
    basileia: Decimal | None = None
    capital_principal: Decimal | None = None
    inadimplencia: Decimal | None = None
    roe: Decimal | None = None
    ativo_total: Decimal | None = None
    patrimonio_liquido: Decimal | None = None
    carteira_credito: Decimal | None = None
    indice_capital_principal: Decimal | None = None
    ausentes: tuple[str, ...] = ()


def _trimestre(ano_mes: int) -> date:
    ano, mes = divmod(ano_mes, 100)
    if mes not in (3, 6, 9, 12):
        raise ValueError("Data-base IF.data deve ser trimestral (AAAAMM)")
    return date(ano, mes, calendar.monthrange(ano, mes)[1])


def _nome(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.split(r"\s*\n|\s*\([a-z]\)", texto, maxsplit=1)[0].strip()


def _identificador_cnpj(texto: Any) -> str | None:
    texto = str(texto or "").strip()
    if not re.fullmatch(r"[\d./-]+", texto):
        return None
    digitos = re.sub(r"\D", "", texto)
    if not digitos or set(digitos) == {"0"}:
        return None
    if 1 <= len(digitos) <= 8:
        return digitos.zfill(8)
    return digitos if len(digitos) == 14 else None


def _saldos(
    valores: Iterable[dict[str, Any]], tipo: int,
) -> dict[tuple[str, date], dict[str, Decimal | None]]:
    resultado: dict[tuple[str, date], dict[str, Decimal | None]] = {}
    for linha in valores:
        if int(linha["TipoInstituicao"]) != tipo:
            continue
        campo = _CAMPOS.get(_nome(linha["NomeColuna"]))
        if campo is None:
            continue
        chave = (str(linha["CodInst"]), _trimestre(int(linha["AnoMes"])))
        saldo = linha.get("Saldo")
        valor = Decimal(str(saldo)) if saldo is not None else None
        if valor is not None and not valor.is_finite():
            raise PacoteInvalido("IF.data retornou saldo nao finito")
        campos = resultado.setdefault(chave, {})
        if (
            campo in campos and campos[campo] is not None
            and valor is not None and campos[campo] != valor
        ):
            raise PacoteInvalido(f"IF.data ambiguo para {chave}: {campo}")
        if valor is not None or campo not in campos:
            campos[campo] = valor
    return resultado


def _roe_ttm(
    cod_inst: str, dia: date, saldos: dict[tuple[str, date], dict[str, Decimal | None]],
) -> Decimal | None:
    def valor(ano: int, mes: int, campo: str) -> Decimal | None:
        return saldos.get((cod_inst, _trimestre(ano * 100 + mes)), {}).get(campo)

    atual = valor(dia.year, dia.month, "lucro_liquido")
    pl_atual = valor(dia.year, dia.month, "patrimonio_liquido")
    pl_anterior = valor(dia.year - 1, dia.month, "patrimonio_liquido")
    if dia.month in (6, 12):
        anterior = valor(dia.year - (dia.month == 6), 12 if dia.month == 6 else 6,
                         "lucro_liquido")
        lucro = atual + anterior if atual is not None and anterior is not None else None
    else:
        sem1 = valor(dia.year if dia.month == 9 else dia.year - 1,
                     6 if dia.month == 9 else 12, "lucro_liquido")
        sem2 = valor(dia.year - 1, 12 if dia.month == 9 else 6, "lucro_liquido")
        comparavel = valor(dia.year - 1, dia.month, "lucro_liquido")
        lucro = (
            atual + sem1 + sem2 - comparavel
            if atual is not None and sem1 is not None and sem2 is not None
            and comparavel is not None else None
        )
    if lucro is None or pl_atual is None or pl_anterior is None:
        return None
    medio = (pl_atual + pl_anterior) / 2
    return lucro / medio if medio > 0 else None


def montar_indicadores(
    cadastro: Iterable[dict[str, Any]], valores: Iterable[dict[str, Any]],
    ano_mes: int, tipo_instituicao: int = 1,
) -> dict[tuple[str, date], IndicadoresIfData]:
    """Liga CodInst ao CNPJ/raiz, sempre dentro da mesma data-base e escopo.

    Valores de datas anteriores podem completar ROE TTM, mas não substituem
    cadastro atual nem preenchem indicadores ausentes do trimestre pedido.
    """
    dia = _trimestre(ano_mes)
    if tipo_instituicao not in (1, 2, 3):
        raise ValueError("TipoInstituicao deve ser 1, 2 ou 3")
    saldos = _saldos(valores, tipo_instituicao)
    vinculos: dict[str, str] = {}
    for linha in cadastro:
        if str(linha["Data"]) != str(ano_mes):
            continue
        cod_inst = str(linha["CodInst"])
        cnpj = _identificador_cnpj(linha.get("CnpjInstituicaoLider"))
        if cnpj is None:
            cnpj = _identificador_cnpj(cod_inst)
        if cnpj is None:
            continue  # Código de conglomerado não é CNPJ.
        codigo = cod_inst
        if tipo_instituicao in (1, 2):
            campo = (
                "CodConglomeradoPrudencial" if tipo_instituicao == 1
                else "CodConglomeradoFinanceiro"
            )
            codigo = str(linha.get(campo) or cod_inst)
        if codigo in vinculos and vinculos[codigo] != cnpj:
            raise PacoteInvalido(f"IF.data sem CNPJ lider univoco para {codigo}")
        vinculos[codigo] = cnpj
    resultado: dict[tuple[str, date], IndicadoresIfData] = {}
    campos_saida = ("basileia", "capital_principal", "inadimplencia", "roe", "ativo_total",
                    "patrimonio_liquido", "carteira_credito", "indice_capital_principal")
    for cod_inst, cnpj in vinculos.items():
        campos = saldos.get((cod_inst, dia))
        if campos is None:
            continue
        dados = {campo: campos.get(campo) for campo in campos_saida}
        if dados["roe"] is None:
            dados["roe"] = _roe_ttm(cod_inst, dia, saldos)
        registro = IndicadoresIfData(
            cnpj, dia, cod_inst, tipo_instituicao,
            basileia=dados["basileia"], capital_principal=dados["capital_principal"],
            inadimplencia=dados["inadimplencia"], roe=dados["roe"],
            ativo_total=dados["ativo_total"], patrimonio_liquido=dados["patrimonio_liquido"],
            carteira_credito=dados["carteira_credito"],
            indice_capital_principal=dados["indice_capital_principal"],
        )
        registro = replace(registro, ausentes=tuple(c for c in campos_saida if dados[c] is None))
        chave = (cnpj, dia)
        if chave in resultado and resultado[chave] != registro:
            raise PacoteInvalido(f"Mais de uma instituicao para {cnpj} em {dia}")
        resultado[chave] = registro
    return resultado


class ClienteIfData:
    """ClienteHttpCvm injetado com base URL_IFDATA; cache de páginas por ETag."""

    def __init__(
        self, cliente: ClienteHttpCvm, cache: CacheDeArquivos, tamanho_pagina: int = 10000,
    ):
        if tamanho_pagina <= 0:
            raise ValueError("tamanho_pagina deve ser positivo")
        self._cliente = cliente
        self._cache = cache
        self._tamanho_pagina = tamanho_pagina

    def _pagina(self, caminho: str) -> dict[str, Any]:
        nome = f"ifdata_{hashlib.sha256(caminho.encode()).hexdigest()}.json"
        assinatura = None
        try:
            assinatura = self._cliente.assinatura(caminho)
        except FonteIndisponivel as erro:
            if not isinstance(erro.__cause__, urllib.error.HTTPError):
                raise
            if erro.__cause__.code not in (405, 501):
                raise
        if assinatura and self._cache.tem(nome) and assinatura.inalterado_em_relacao_a(
            self._cache.etag_de(nome)
        ):
            conteudo = self._cache.ler(nome)
        else:
            conteudo = self._cliente.baixar(caminho)
        pagina = json.loads(conteudo, parse_float=Decimal)
        if not isinstance(pagina, dict) or not isinstance(pagina.get("value"), list):
            raise PacoteInvalido("IF.data sem lista value na resposta OData")
        self._cache.gravar(nome, conteudo, assinatura.etag if assinatura else None)
        return pagina

    def _listar(self, funcao: str) -> list[dict[str, Any]]:
        resultado = []
        caminho = funcao + "?" + urlencode({"$format": "json", "$top": self._tamanho_pagina})
        visitados = set()
        conteudos = set()
        while caminho:
            if caminho in visitados:
                raise PacoteInvalido("IF.data repetiu pagina OData")
            visitados.add(caminho)
            pagina = self._pagina(caminho)
            identidade = json.dumps(pagina["value"], sort_keys=True, default=str)
            if pagina["value"] and identidade in conteudos:
                raise PacoteInvalido("IF.data repetiu conteudo de pagina OData")
            conteudos.add(identidade)
            resultado.extend(pagina["value"])
            proxima = pagina.get("@odata.nextLink")
            if proxima:
                absoluta = urljoin(URL_IFDATA, proxima)
                if not absoluta.startswith(URL_IFDATA):
                    raise PacoteInvalido("IF.data retornou nextLink fora do servico")
                caminho = absoluta[len(URL_IFDATA):]
            elif len(pagina["value"]) == self._tamanho_pagina:
                caminho = funcao + "?" + urlencode({
                    "$format": "json", "$top": self._tamanho_pagina, "$skip": len(resultado),
                })
            else:
                caminho = ""
        return resultado

    def relatorios(self) -> dict[str, str]:
        return {
            r["NumeroRelatorio"]: r["NomeRelatorio"] for r in self._listar("ListaDeRelatorio()")
        }

    def ler(
        self, ano_mes: int, tipo_instituicao: int = 1,
    ) -> dict[tuple[str, date], IndicadoresIfData]:
        dia = _trimestre(ano_mes)
        if tipo_instituicao not in (1, 2, 3):
            raise ValueError("TipoInstituicao deve ser 1, 2 ou 3")
        cadastro = self._listar(f"IfDataCadastro(AnoMes={ano_mes})")
        valores = []
        # Compara os dois semestres completos e o trimestre homólogo para ROE.
        periodos = {ano_mes, (dia.year - 1) * 100 + dia.month}
        if dia.month in (3, 6):
            periodos.add((dia.year - 1) * 100 + 12)
            if dia.month == 3:
                periodos.add((dia.year - 1) * 100 + 6)
        else:
            periodos.add(dia.year * 100 + 6)
            if dia.month == 9:
                periodos.add((dia.year - 1) * 100 + 12)
        for periodo in sorted(periodos):
            for relatorio in (("1", "5") if periodo == ano_mes else ("1",)):
                valores.extend(self._listar(
                    f"IfDataValores(AnoMes={periodo},TipoInstituicao={tipo_instituicao},"
                    f"Relatorio='{relatorio}')"
                ))
        return montar_indicadores(cadastro, valores, ano_mes, tipo_instituicao)
