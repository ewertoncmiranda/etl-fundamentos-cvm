# FONTES-ETL-2

Status: **IMPLEMENTADO** (2026-10-20).

## Entregue

- Branch `feature-cons-fontes-etl-2`, worktree `.worktrees/fontes-etl-2`, criada de `origin/develop` (`7231713`).
- `ler_cadastro(bytes)` devolve cadastro por CNPJ normalizado, situação/data, setor, auditor e CNPJ do auditor.
- `LeitorCadastroCvm` reutiliza `ClienteHttpCvm`, `CacheDeArquivos` e as constantes de encoding/delimitador do leitor de pacotes. HEAD/ETag evita GET repetido; sem ETag, baixa novamente.
- `troca_auditor_recente` é pura: compara snapshots do mesmo CNPJ; exige evidência temporal para afirmar troca recente. Nunca trata primeiro cadastro ou auditor ausente como troca.

## Evidência

- Cabeçalho real consultado em 2026-10-20: [CSV CVM](https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv).
- Colunas usadas: `CNPJ_CIA`, `SIT`, `DT_INI_SIT`, `SETOR_ATIV`, `CNPJ_AUDITOR`, `AUDITOR` (latin-1, `;`).
- Suíte pytest: **265 passaram, 1 externo desmarcado**. Testes novos: **4**, com CSV sintético e HTTP mockado. Ruff e mypy do módulo passaram.
- Cobertura: acentos, delimitador em campo citado, ausências, cabeçalho inválido, comparação de auditores, janela temporal e cache/republicação.

## Desvios

- **A fonte não contém data de início do auditor.** `data_inicio_auditor` é `None`; `DT_INI_RESP` é data do responsável e não é usada como substituto.
- Sem data de contratação nem snapshot anterior dentro da janela, a recência retorna `None` (indeterminada). Pode receber data conhecida no record; não busca FRE fora do escopo autorizado.
- Sem banco, integração ao catálogo, migration, CLI ou alterações nos arquivos compartilhados. Integração pertence a FONTES-ETL-8.
