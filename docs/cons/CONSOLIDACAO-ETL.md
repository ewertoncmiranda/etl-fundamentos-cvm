# Consolidação do ETL — 2026-10-21

Status: **IMPLEMENTADO**.

## Entregue

Branch única: `feature-consolidacao-etl`, criada de `origin/develop` em `7231713`. Os commits dos sete PRs foram preservados por merges, sem reescrita de histórico.

| PR substituído | Entrega |
|---|---|
| #21 | ETag associado à versão do cálculo |
| #22 | FONTES-ETL-2 — cadastro CVM |
| #23 | FONTES-ETL-6 — IF.data |
| #24 | MICRO-ETL-1 — datas ex |
| #25 | MICRO-ETL-2 — outros mercados COTAHIST |
| #26 | FONTES-ETL-1..8 — leitores e etapas das fontes públicas |
| #27 | Especificações CONS |

Os merges não produziram conflitos textuais. As cópias dos leitores presentes no PR #26 coincidiram com as implementações dos PRs individuais e foram reunidas sem duplicação.

## Evidência e limites

- Os sete PRs estão reunidos no histórico da branch única.
- Antes da instrução para interromper as validações, o pytest executado passou com 385 testes, sete testes MySQL pulados e um externo desmarcado. Nenhum banco foi acessado.
- Por instrução posterior do usuário, não foram feitas novas validações. Os ajustes de lint não commitados foram desfeitos; esta entrega preserva o código das branches de origem.
- Continuam valendo as limitações já documentadas nas entregas, inclusive a indisponibilidade das consultas de dados IF.data.

## Regra permanente

**UMA FEATURE, UMA BRANCH E VÁRIOS COMMITS. NUNCA CRIAR BRANCH POR TAREFA.**

Regra registrada no `AGENTS.md` versionado do ETL e no `C:/Users/User/projetos/AGENTS.md`. Os PRs individuais são substituídos pelo PR único da consolidação. As branches antigas são preservadas para rastreabilidade.
