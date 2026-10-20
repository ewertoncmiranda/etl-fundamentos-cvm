# MICRO-ETL-2

Status: **IMPLEMENTADO** (2026-10-20).

## Entregue

- Branch `feature-cons-micro-etl-2`, worktree `.worktrees/micro-etl-2`, criada de `origin/develop` (`7231713`).
- Acrescentados record imutável `NegocioMercadoB3` e métodos `ler_mercados_linhas`/`ler_mercados_zip` no leitor existente.
- TPMERC 012 exercício call, 013 exercício put, 017 leilão, 020 fracionário, 030 termo; campos de preço, quantidade, financeiro, negócios, ISIN, FATCOT, PRAZOT, INDOPC, DISMES, PREEXE e PTOEXE.
- `simbolo_base` usa ISIN compartilhado com mercado 010 no mesmo pregão, independentemente da ordem das linhas, ou mapa ISIN fornecido pelo chamador. Fallback de F/T é limitado a fracionário/termo. Sem evidência, base é `None`.

## Evidência

- [Layout oficial B3](https://www.b3.com.br/data/files/33/67/B9/50/D84057102C784E47AC094EA8/SeriesHistoricas_Layout.pdf) conferido ao vivo: PRAZOT 50–52; INDOPC 202; DISMES 243–245; **PREEXE 189–201 (duas casas)** e **PTOEXE 218–230 (seis casas)**. Ambos preservados separadamente, sem dividir pelo FATCOT.
- Suíte pytest: **273 passaram, 1 externo desmarcado**. **12 testes novos** e **20 testes existentes do leitor**, todos passaram. Fixtures `_linha_cotahist`/`_com` existentes reutilizadas.
- Comparação automatizada das ASTs confirmou preservação integral dos quatro métodos existentes (`ler_zip`, `ler_linhas`, `ler_opcoes_zip`, `ler_opcoes_linhas`). Ruff passou.

## Desvios

- Nenhuma mudança de comportamento nos leitores existentes. ISIN identifica o papel, mas não fornece sozinho o ticker; associação exige cotação de referência ou mapa explícito.
- Cotações antigas com mesmo ISIN não determinam o ticker atual. ISIN ambíguo no mesmo pregão não escolhe um ticker arbitrariamente.
- Sem banco, persistência, catálogo ou CLI; integração à COTAHIST pertence a FONTES-ETL-8.
