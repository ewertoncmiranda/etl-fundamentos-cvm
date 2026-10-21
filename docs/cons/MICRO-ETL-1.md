# MICRO-ETL-1

Status: **IMPLEMENTADO** (2026-10-20).

## Entregue

- Branch `feature-cons-micro-etl-1`, worktree `.worktrees/micro-etl-1`, criada de `origin/develop` (`7231713`).
- `classificar_marca_ex`: EB=BONIFICACAO, ED=DIVIDENDO, EG=GRUPAMENTO, EJ=JCP, ER=RENDIMENTO, ES=SUBSCRICAO. Combinações preservam a ordem, sem repetir tipos. EX/letras desconhecidas = OUTRO.
- `calcular_datas_ex` aceita candles compatíveis com `CandleB3` (`simbolo`, `data_pregao`, `abertura`, `fechamento`, `marca_ex`), ordena sem mutar entrada e compara pregões observados do mesmo símbolo.
- Ajuste implícito = fechamento anterior − abertura ex; percentual = 100 × ajuste / fechamento anterior, em pontos percentuais. Valores negativos são preservados. Ausência de preço impede ajuste; denominador não positivo impede percentual.

## Evidência

- Mapa validado no [layout oficial B3, revisão 02/2020](https://www.b3.com.br/data/files/33/67/B9/50/D84057102C784E47AC094EA8/SeriesHistoricas_Layout.pdf), tabela ESPECI. O regex `_MARCA_EX` existente não foi alterado.
- Suíte pytest: **284 passaram, 1 externo desmarcado**. **23 testes novos** cobrem letras/combinações, desconhecidos, ordenação, isolamento de símbolos, fim de semana, primeiro dia ex, preços ausentes, zero, gap negativo e duplicatas.
- Ruff e mypy do módulo passaram. Nenhum banco ou rede nos testes novos.

## Desvios

- EX permanece OUTRO porque não há um tipo específico validado para X no layout consultado; nenhuma inferência de desdobramento é feita.
- Sem calendário ou acesso a banco: “pregão anterior” significa último candle fornecido do mesmo símbolo. O chamador deve fornecer a série completa desejada. Duplicatas símbolo/data são rejeitadas.
- Ajuste de preço bruto é evidência implícita, não valor declarado de provento. Integração à etapa EVENTOS pertence a FONTES-ETL-8.
