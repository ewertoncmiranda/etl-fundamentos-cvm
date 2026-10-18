from dataclasses import dataclass

from app.aplicacao.resumo_etapa import resumir_etapa


@dataclass
class ResultadoCandle:
    anos_processados: list[int]
    anos_pulados: list[int]
    candles_por_ano: dict[int, int]
    candles_gravados: int
    opcoes_gravadas: int = 0
    erros_opcoes: list[str] | None = None


def test_cotahist_falha_se_um_ano_processado_nao_gravou_candles():
    resultado = ResultadoCandle([2025, 2026], [], {2025: 10, 2026: 0}, 10)

    resumo = resumir_etapa("COTAHIST", resultado)

    assert resumo.status == "FALHA"
    assert "2026" in resumo.erros[0]


def test_cotahist_sem_mudanca_quando_todos_os_anos_foram_pulados():
    resumo = resumir_etapa("COTAHIST", ResultadoCandle([], [2025], {}, 0))

    assert resumo.status == "SEM_MUDANCA"


def test_erro_de_opcoes_na_carga_cotahist_e_falha_da_etapa():
    resultado = ResultadoCandle([2025], [], {2025: 8}, 8, erros_opcoes=["sem fonte"])

    assert resumir_etapa("COTAHIST", resultado).status == "FALHA"


def test_ttm_com_ano_processado_sem_indicadores_gera_alerta():
    @dataclass
    class Resultado:
        anos_processados: list[int]
        anos_pulados: list[int]
        indicadores_gravados: int

    resumo = resumir_etapa("TTM", Resultado([2026], [], 0))

    assert resumo.status == "ALERTA"
    assert resumo.alertas


def test_excecao_da_etapa_vira_falha_serializavel():
    resumo = resumir_etapa("DFP", erro=RuntimeError("fonte indisponível"))

    assert resumo.status == "FALHA"
    assert resumo.erros == ["fonte indisponível"]
