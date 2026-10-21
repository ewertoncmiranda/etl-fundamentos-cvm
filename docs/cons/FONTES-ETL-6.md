# FONTES-ETL-6

Status: **IMPLEMENTADO** (2026-10-20).

## Entregue

- Branch `feature-cons-fontes-etl-6`, worktree `.worktrees/fontes-etl-6`, criada de `origin/develop` (`7231713`).
- `ClienteIfData` recebe `ClienteHttpCvm` configurado com `URL_IFDATA` e `CacheDeArquivos`; pagina por nextLink ou top/skip, mantém precisão Decimal e cache HEAD/ETag por página. HEAD 405/501 permite GET; outros erros propagam.
- `montar_indicadores` é pura. Resultado por `(CNPJ ou raiz, data_base)` com instituição/escopo, Basileia, capital principal em valor, índice de capital principal em campo separado, inadimplência, ROE, ativo, PL, carteira de crédito e lista de ausências.
- ROE = lucro TTM / média entre PL atual e PL de 12 meses antes. Lucros semestrais respeitam junho/dezembro; março/setembro subtraem o acumulado homólogo. Histórico/PL insuficiente resulta em `None`.
- Valores monetários preservam unidade publicada (R$ mil); índices de capital e ROE são razões (0,15 representa 15%). Sem associação a ticker.

## Evidência

Conferidos ao vivo em 2026-10-20:

- [Serviço OData](https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata/) e [metadata](https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata/$metadata).
- [ListaDeRelatorio](https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata/ListaDeRelatorio()?$format=json): **1 = Resumo**, **5 = Informações de Capital**. Também confirma Ativo (2), Passivo (3), Demonstração de Resultado (4) e relatórios de crédito.
- Schema: `IfDataCadastro(AnoMes)`; `IfDataValores(AnoMes,TipoInstituicao,Relatorio)`; `CodInst`, `AnoMes`, `NomeColuna`, `Saldo`, `CnpjInstituicaoLider`, códigos de conglomerado.
- Rótulos e convenção semestral conferidos também no [IF.data oficial](https://www3.bcb.gov.br/ifdata/index2024.html) e em seus metadados públicos: [info202412.json](https://www3.bcb.gov.br/ifdata/rest/arquivos?nomeArquivo=ifdata/202412/info202412.json). O índice de Basileia amplo não é confundido com Basileia; valor e índice de capital principal são distintos.
- Suíte pytest: **276 passaram, 1 externo desmarcado**. **15 testes sintéticos** cobrem precisão, datas, CNPJ, escopo, conflitos, os quatro trimestres do ROE, ausências, cache, paginação e falhas HTTP. Ruff e mypy do módulo passaram.

## Desvios

- Serviço e nomes de relatório confirmados, mas as consultas OData de cadastro/valores retornaram **HTTP 500** nas datas-base tentadas (202309, 202312, 202406, 202412, 202503, 202606), inclusive com aliases OData. Não houve validação de uma coleta completa ao vivo; testes de transporte usam respostas sintéticas baseadas no schema oficial.
- CNPJ de oito dígitos permanece raiz, sem completar filial/dígitos verificadores. Código de conglomerado não é aceito como CNPJ; vínculos ambíguos são rejeitados.
- Nenhum ROE anual é inventado por multiplicação de um trimestre; histórico insuficiente fica ausente. Dados da fonte não disponíveis ficam `None`, com nome em `ausentes`.
- Sem banco, ticker, etapa de carga, migration ou CLI nova. Integração posterior pertence a FONTES-ETL-8.
