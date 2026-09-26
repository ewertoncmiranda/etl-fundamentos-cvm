# SPEC — etl-fundamentos-cvm

**Versão:** 1.0.0 · **Status:** Ativa · **Atualizada em:** 2026-09-26
**Público:** desenvolvedores humanos e agentes de IA.

---

## 1. Como usar este arquivo (protocolo para agentes)

Mesmo protocolo dos repositórios irmãos (`gerar-insights`, `gestor-ativos-brutos`, `infra-b3-ecossytem`).

1. Leia as seções 2 a 6 antes de mudar código. Toda mudança cita um `REQ-`, `NFR-`, `ISS-` ou `TASK-`.
2. **IDs são estáveis** — nunca renumere nem apague. Para aposentar, use status `DESCARTADO` com justificativa.
3. Status válidos: `ABERTO`, `EM_ANDAMENTO`, `BLOQUEADO`, `CONCLUIDO`, `DESCARTADO` para tarefas e problemas; `IMPLEMENTADO`, `PARCIAL`, `PLANEJADO` para requisitos.
4. Decisão de projeto vira um `DEC-` na seção 7. Não aja sobre decisão aberta sem registrar a escolha.
5. Critérios de aceite em **Dado / Quando / Então**, e devem virar teste automatizado.
6. **Mudança no de-para (seção 5) altera resultado financeiro.** Exige atualizar as fixtures de regressão e esta spec no mesmo PR.
7. Esta aplicação **escreve** numa tabela que outro serviço lê: mudança de coluna em `indicador_fundamentalista` é mudança de contrato e exige atualizar `infra-b3-ecossytem#CTR-06` e avisar o `gestor-ativos-brutos`.

Fluxo: `Spec → Plano → Tarefas → Implementação → Verificação → Atualizar Spec`.

Vocabulário: [`infra-b3-ecossytem/GLOSSARIO.md`](../infra-b3-ecossytem/GLOSSARIO.md).

---

## 2. Visão do produto

Job em lote que carrega fundamentos contábeis dos dados abertos da CVM no MySQL do ecossistema, cobrindo o que o plano gratuito da BRAPI cobra: ROE, ROIC, margens, dívida líquida e fluxo de caixa livre.

Não é serviço: roda, grava e encerra. Agendamento fica fora do container.

### 2.1 Fluxo

```
ativo_monitorado  ──> universo de tickers
        │
        v
CVM (HTTPS) ──> FCA (ticker→CNPJ) ──> DFP (demonstrações) ──> FRE (nº de ações)
        │
        v
fato_contabil (landing, whitelist de contas)
        │
        v
indicador_fundamentalista (mart)  ──> sqs-fundamentos-atualizados
```

---

## 3. Arquitetura

Hexagonal, com dependências apontando para dentro. `dominio/` e `aplicacao/` não importam SQLAlchemy, `boto3`, `urllib` nem `zipfile`.

| Camada | Pacote | Responsabilidade |
|---|---|---|
| Domínio | `app/dominio/` | Modelo, catálogo de regras, classificador de plano, resolvedor, calculadora. Puro |
| Portas | `app/portas/` | `Protocol`s: fonte de documentos, 5 repositórios, publicador, relógio |
| Adaptadores | `app/adaptadores/` | CVM (HTTP, cache, ZIP/CSV, normalização), persistência, mensageria |
| Aplicação | `app/aplicacao/` | `CarregarFundamentos`, único caso de uso |
| Composição | `app/config/composicao.py` | Composition root: o único módulo que conhece classes concretas |

DI por construtor com argumentos **obrigatórios**. `Settings` é instanciado uma vez em `main.py`.

---

## 4. Contratos de dados

| ID | Recurso | Direção | Conteúdo |
|---|---|---|---|
| CTR-E01 | MySQL `indicador_fundamentalista` | escreve | Mart. Contrato canônico em `infra#CTR-06` |
| CTR-E02 | MySQL `fato_contabil` | escreve | Landing interna. **Não** é contrato de leitura |
| CTR-E03 | MySQL `ativo_monitorado` | lê | Universo de tickers, populado pelo `gestor` |
| CTR-E04 | SQS `sqs-fundamentos-atualizados` | publica | `{evento, simbolos[]}`. Falha ao publicar não aborta a carga |
| CTR-E05 | CVM Dados Abertos | lê | DFP, FCA, FRE. ZIP de CSV latin-1, delimitador `;` |

---

## 5. Regras de negócio

### 5.1 Normalização (adaptador)

| Regra | Razão |
|---|---|
| Só `ORDEM_EXERC='ÚLTIMO'` | `PENÚLTIMO` duplicaria o exercício |
| Maior `VERSAO` por competência | Reapresentações |
| `ESCALA_MOEDA='MIL'` × 1000 | Senão o ROE sai 1000x errado |
| `DT_INI_EXERC` ausente recebe `DT_FIM_EXERC` | NULL na chave única é tratado como distinto pelo MySQL |

### 5.2 De-para (domínio)

`CD_CONTA` **não** é estável entre companhias. Verificado no DFP 2025: PL é `2.03` na WEG, `2.07` no BBAS3 e `2.08` no ITUB4 — e `2.03` no BBAS3 é "Provisões". A chave estável é `ST_CONTA_FIXA='S'` + `DS_CONTA` normalizada, com `CD_CONTA` só como desempate.

Contas somadas descartam descendentes: `2.01.04` e `2.01.04.01` têm o mesmo rótulo, e somar as duas dobra a dívida.

Métrica que o plano de contas não comporta é `NULL` **de propósito**, com a razão em `cobertura_json`.

### 5.3 Quantidade de ações

`QT_ACAO` do DFP não tem unidade padronizada (WEG em unidades, VALE em milhares). O total vem do FRE (`Capital Integralizado`); o DFP entra só com a tesouraria, reescalada pelo fator detectado entre as fontes.

### 5.4 Derivados

LPA, VPA e ROE usam a parcela do **controlador** — convenção das referências de mercado. ROIC usa alíquota nominal de 34%.

---

## 6. Requisitos

| ID | Requisito | Status |
|---|---|---|
| REQ-01 | Carregar DFP dos tickers de `ativo_monitorado` | IMPLEMENTADO |
| REQ-02 | Persistir landing e mart, com upsert idempotente | IMPLEMENTADO |
| REQ-03 | Pular download quando o ETag da CVM não mudou | IMPLEMENTADO |
| REQ-04 | Declarar métrica ausente com a razão | IMPLEMENTADO |
| REQ-05 | Publicar evento de fundamentos atualizados | IMPLEMENTADO |
| REQ-06 | Carregar ITR e derivar TTM | IMPLEMENTADO (2026-09-26) |
| REQ-08 | Carregar série diária bruta do COTAHIST/B3 apenas para ativos monitorados | IMPLEMENTADO (2026-09-26) |
| REQ-07 | Suportar plano de contas de seguradora | PARCIAL (código existe, não exercitado) |

| ID | Não funcional | Status |
|---|---|---|
| NFR-01 | Domínio testável sem banco, rede ou arquivo | ATENDIDO |
| NFR-02 | Execução repetida produz o mesmo resultado | ATENDIDO |
| NFR-03 | Nenhum segredo na imagem publicada | ATENDIDO (`.dockerignore`, usuário não-root) |
| NFR-04 | CI barra publicação sem lint, mypy e testes | ATENDIDO |
| NFR-05 | Erro transitório não aborta os demais anos | ATENDIDO |

### 6.1 Critérios de aceite

**REQ-03** — Dado que o DFP de 2025 já foi carregado com sucesso; Quando o ETL rodar de novo e o ETag não tiver mudado; Então nenhum download acontece, `etl_execucao` recebe `PULADO` e as contagens não mudam.

**REQ-04** — Dado um banco (plano FINANCEIRO); Quando os indicadores forem montados; Então `margem_liquida` e `roic` são nulos e `cobertura_json` explica que `3.05` no banco não é EBIT.

---

## 7. Decisões

| ID | Questão | Decisão |
|---|---|---|
| DEC-E01 | De-para por código ou por rótulo? | **Rótulo** + `ST_CONTA_FIXA`, código só como desempate. Código produz número errado em silêncio |
| DEC-E02 | Fonte da quantidade de ações | **FRE**, por ter unidade consistente |
| DEC-E03 | LPA/VPA/ROE: consolidado ou controlador? | **Controlador**, que é o que o mercado publica |
| DEC-E04 | Gravar P/L e P/VP? | **Não.** Derivados na leitura pelo `gestor`, senão nascem obsoletos |
| DEC-E05 | Quem cria as tabelas? | `infra-b3-ecossytem/mysql-init`. Este app não faz DDL. Herda `infra#DEC-01`, que segue ABERTO |
| DEC-E06 | Carregar todas as companhias ou só as monitoradas? | **Só as monitoradas.** Um lugar só para escolher ativo |

---

## 8. Problemas conhecidos

| ID | Sev. | Problema | Status |
|---|---|---|---|
| ISS-E01 | Alto | Sem TTM: só exercício fechado. Trocar a base do LPA move o número 40%+ em empresa volátil, então o Graham **não** deve consumir estes dados ainda | CONCLUIDO (2026-09-26: DFP + ITR atual − ITR comparável) |
| ISS-E02 | Médio | `capex` não é extraível (contas `6.02.xx` são texto livre). FCL usa investimento total como proxy | ABERTO |
| ISS-E03 | Médio | ROIC usa alíquota nominal e definição própria de capital investido; diverge do Fundamentus (31,3% × 24,3% na WEG) | ABERTO |
| ISS-E04 | Médio | `RENT3` diverge 43,8% do Fundamentus sem explicação; a DRE extraída fecha internamente | ABERTO |
| ISS-E05 | Baixo | `PLANO_SEGURADORA` não exercitado com dado real | ABERTO |
| ISS-E06 | Baixo | Ticker de companhia sem DFP consolidada cai para individual sem sinalizar na resposta | ABERTO |

---

## 9. Tarefas

| ID | Tarefa | Depende | Status |
|---|---|---|---|
| TASK-E01 | Carregar ITR e derivar TTM (DRE do ITR é acumulada no ano; trimestre sai por subtração) | REQ-06 | CONCLUIDO (2026-09-26) |
| TASK-E07 | Ingerir COTAHIST anual com ETag, filtro de ativos monitorados e upsert em `serie_historica` | REQ-08 | CONCLUIDO (2026-09-26) |
| TASK-E02 | Fixture de seguradora e validação do plano | ISS-E05 | ABERTO |
| TASK-E03 | Investigar a divergência de `RENT3` | ISS-E04 | ABERTO |
| TASK-E04 | Expor série histórica de indicadores | — | ABERTO |
| TASK-E05 | Integrar proventos (dividendos, JCP) da B3 | — | ABERTO |
| TASK-E06 | Fixar convenção de ROIC e documentá-la | ISS-E03 | ABERTO |

---

## 10. Verificação

```bash
pytest tests/ -m "not externo"    # domínio puro
ruff check app tests main.py
mypy app
pytest -m externo -s              # confronto com o Fundamentus, sob demanda

docker compose --profile etl run --rm etl-fundamentos-cvm
```

Regressão de referência (WEGE3, DFP 2025): LPA 1,5197 · VPA 4,1512 · ROE 36,61% · margem 16,61% · dívida líquida −1,71 bi.

---

## 11. Aviso regulatório

Este serviço produz **indicador contábil**, não rótulo de decisão. Ver `gerar-insights#ISS-F6` sobre a Res. CVM 20/2021: nada aqui deve ser apresentado como recomendação de investimento.
