from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from app.aplicacao.datas_ex import calcular_datas_ex, classificar_marca_ex


@dataclass(frozen=True)
class Candle:
    simbolo: str
    data_pregao: date
    abertura: Decimal | None
    fechamento: Decimal | None
    marca_ex: str | None = None


@pytest.mark.parametrize(('marca', 'tipos'), [
    ('EB', ('BONIFICACAO',)), ('ED', ('DIVIDENDO',)), ('EG', ('GRUPAMENTO',)),
    ('EJ', ('JCP',)), ('ER', ('RENDIMENTO',)), ('ES', ('SUBSCRICAO',)),
    ('EX', ('OUTRO',)), ('EZ', ('OUTRO',)), ('EDJ', ('DIVIDENDO', 'JCP')),
    ('EDB', ('DIVIDENDO', 'BONIFICACAO')), ('EJS', ('JCP', 'SUBSCRICAO')),
    ('EDZ', ('DIVIDENDO', 'OUTRO')), ('eddd', ('DIVIDENDO',)),
    ('', ()), (None, ()), ('NM', ('OUTRO',)), ('E', ('OUTRO',)),
])
def test_tipos_e_combinacoes(marca, tipos):
    assert classificar_marca_ex(marca) == tipos


def test_ordena_sem_mutar_isola_simbolos_e_usa_ultimo_pregao_inclusive_fim_de_semana():
    sexta, segunda = date(2026, 10, 16), date(2026, 10, 19)
    entrada = [
        Candle('PETR4', segunda, Decimal('48'), Decimal('49'), 'EDJ'),
        Candle('VALE3', sexta, Decimal('100'), Decimal('100')),
        Candle('PETR4', sexta, Decimal('50'), Decimal('50')),
    ]
    original = entrada.copy()
    (evento,) = calcular_datas_ex(entrada)
    assert entrada == original
    assert evento.data_anterior == sexta
    assert evento.ajuste_implicito == Decimal('2')
    assert evento.ajuste_percentual == Decimal('4')
    assert evento.tipos == ('DIVIDENDO', 'JCP')


def test_primeiro_ex_nao_inventa_preco_anterior_e_gap_negativo_e_preservado():
    candles = [Candle('X', date(2026, 1, 1), Decimal('10'), Decimal('10'), 'EB'),
               Candle('X', date(2026, 1, 2), Decimal('12'), Decimal('12'), 'ED')]
    primeiro, segundo = calcular_datas_ex(candles)
    assert primeiro.ajuste_implicito is None
    assert primeiro.ajuste_percentual is None
    assert segundo.ajuste_implicito == Decimal('-2')
    assert segundo.ajuste_percentual == Decimal('-20')


@pytest.mark.parametrize('fechamento,abertura', [(None, Decimal(1)), (Decimal(1), None),
                                               (Decimal(0), Decimal(1))])
def test_precos_ausentes_e_denominador_zero(fechamento, abertura):
    candles = [Candle('X', date(2026, 1, 1), None, fechamento),
               Candle('X', date(2026, 1, 2), abertura, None, 'EX')]
    (evento,) = calcular_datas_ex(candles)
    assert evento.ajuste_percentual is None


def test_duplicata_rejeitada_e_lista_vazia():
    assert calcular_datas_ex([]) == []
    candle = Candle('X', date(2026, 1, 1), None, None)
    with pytest.raises(ValueError, match='duplicado'):
        calcular_datas_ex([candle, candle])
