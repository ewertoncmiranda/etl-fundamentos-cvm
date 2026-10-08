# SPEC — etl-fundamentos-cvm

**Versão:** 1.0.0 · **Status:** IMPLEMENTADO · **Atualizada em:** 2026-09-27
**Público:** desenvolvedores humanos e agentes de IA.

---

## Corte e estados comuns

Data de corte: **2026-09-27** (America/Sao_Paulo). `PLANEJADO`: ainda não executado; `EM ANDAMENTO`: entrega parcial; `IMPLEMENTADO`: código ou decisão presente, sem confirmação integral nesta revisão; `VERIFICADO`: aceite demonstrado por verificação registrada; `BLOQUEADO`: dependência impeditiva identificada. Datas anteriores permanecem como histórico. Resolver um problema significa implementar sua correção; funcionalidades descontinuadas mantêm o ID e registram a resolução. Evidências antigas não são nova validação operacional.

## 1. Como usar este arquivo (protocolo para agentes)

Mesmo protocolo dos repositórios irmãos (`gerar-insights`, `gestor-ativos-brutos`, `infra-b3-ecossytem`).

1. Leia as seções 2 a 6 antes de mudar código. Toda mudança cita um `REQ-`, `NFR-`, `ISS-` ou `TASK-`.
2. **IDs são estáveis** — nunca renumere nem apague. Para aposentar, use status `IMPLEMENTADO (descontinuado)` com justificativa.
Estados válidos de requisitos, tarefas, problemas e decisões: `PLANEJADO`, `EM ANDAMENTO`, `IMPLEMENTADO`, `VERIFICADO`, `BLOQUEADO`. Descontinuação é uma resolução descrita, não um estado adicional.
4. Decisão de projeto vira um `DEC-` na seção 7. Não aja sobre decisão aberta sem registrar a escolha.
5. Critérios de aceite em **Dado / Quando / Então**, e devem virar teste automatizado.
6. **Mudança no de-para (seção 5) altera resultado financeiro.** Exige atualizar as fixtures de regressão e esta spec no mesmo PR.
7. Esta aplicação **escreve** numa tabela que outro serviço lê: mudança de coluna em `indicador_fundamentalista` é mudança de contrato e exige atualizar `infra-b3-ecossytem#CTR-06` e avisar o `gestor-ativos-brutos`.

Fluxo: `Spec → Plano → Tarefas → Implementação → Verificação → Atualizar Spec`.

Vocabulário: [`infra-b3-ecossytem/GLOSSARIO.md`](../infra-b3-ecossytem/GLOSSARIO.md).

---

## 1A. Coordenação entre agentes (estado em 2026-10-04)

**Hub:** `infra-b3-ecossytem/SPEC.md` seção 1A — fila única, contratos, handoff e diário. Leia antes de codar; atualize lá ao pegar e ao fechar tarefa. Em conflito com seções antigas abaixo, vale o hub e esta seção.

- **Dono neste repo:** fundamentos (DFP), TTM (ITR), comunicados (IPE), COTAHIST, proventos contábeis (DVA), conciliação BRAPI×COTAHIST. Escreve `fato_contabil`, `indicador_fundamentalista`, `comunicado_cvm`, `cotacao_b3_diaria`, `provento_contabil`, `etl_execucao`; **não cria tabelas** — o `VerificadorDeSchema` exige as colunas da V16.
- **Comandos hoje (composição):** carga padrão (DFP), `--ttm`, `--comunicados`, `--cotahist`, proventos contábeis, `--conciliar` (compara foto BRAPI com COTAHIST). Rodados pela rotina da manhã da infra; TASK-E09 (agendar) é coberta por ela — confirmar e fechar.
- **Fila local:** LAC-ETL-1, 5, 6, 7 `IMPLEMENTADO` (f9832b0). `PLANEJADO`: LAC-ETL-2 (eventos corporativos), LAC-ETL-3 (TTM trimestral desde 2011), LAC-ETL-4 (anos antigos; testar 1 ano de cada antes). Backfill e `setor_grupo`: LAC-INFRA-2/3 no hub.
- **Atenção:** a imagem `etl:develop` publicada é de 2026-09-28 e não inclui `--conciliar`/proventos — o deploy de 2026-10-07 falhou no lint (ISS-E13, TASK-E18). Saúde da rotina agendada: ISS-E13 a E17, TASK-E18 a E22.
- **Arquivo não commitado de outra sessão:** `app/adaptadores/mensageria/publicador_sqs.py` (contratos) — não editar nem commitar sem o dono.

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
| REQ-07 | Suportar plano de contas de seguradora | EM ANDAMENTO (código existe, não exercitado) |
| REQ-09 | Carregar comunicados oficiais da base IPE (`--comunicados`) para os tickers com CNPJ em `cvm_ticker`, gravar em `comunicado_cvm` (`infra#CTR-08`) e publicar `sqs-comunicados-publicados` (`infra#CTR-09`) só com o que é novo | IMPLEMENTADO (2026-09-26) |
| REQ-10 | Gravar `numero_negocios` por pregão em `cotacao_b3_diaria` a partir do COTAHIST (posições 148–152) | PLANEJADO |
| REQ-11 | Capturar e persistir o código ISIN de cada papel, cruzando COTAHIST (posições 231–242) e FCA `valor_mobiliario`; gravar em `cvm_ticker` e `cotacao_b3_diaria` | PLANEJADO |
| REQ-12 | Carregar breakdown de ações ordinárias e preferenciais da composição de capital do DFP (`QT_ACAO_ORDIN_CAP_INTEGR`, `QT_ACAO_PREF_CAP_INTEGR`) e do FRE (`Quantidade_Acoes_Ordinarias`, `Quantidade_Acoes_Preferenciais`); avaliar persistência separada das respectivas ações em tesouraria | EM ANDAMENTO (capital integralizado DFP+FRE verificado em 2026-10-07, TASK-E12/E14; tesouraria por classe ainda não persistida) |
| REQ-13 | Gravar `situacao_registro` e `data_constituicao` da empresa a partir do FCA `geral`; campo `uf_municipio` como localização da sede | PLANEJADO |
| REQ-14 | Abrir `DFC_MD` (DFC método direto) do ZIP do DFP/ITR e persistir em `fato_contabil` com `demonstracao = 'DFC_MD'`, quando presente | IMPLEMENTADO (2026-10-07, TASK-E15) |
| REQ-15 | Capturar dados de opções do COTAHIST (BDI 12, 14) — vencimento, preço de exercício, código base — após decisão DEC-E09 | IMPLEMENTADO (2026-10-07, TASK-E16) |

| ID | Não funcional | Status |
|---|---|---|
| NFR-01 | Domínio testável sem banco, rede ou arquivo | IMPLEMENTADO |
| NFR-02 | Execução repetida produz o mesmo resultado | IMPLEMENTADO |
| NFR-03 | Nenhum segredo na imagem publicada | IMPLEMENTADO (`.dockerignore`, usuário não-root) |
| NFR-04 | CI barra publicação sem lint, mypy e testes | IMPLEMENTADO |
| NFR-05 | Erro transitório não aborta os demais anos | IMPLEMENTADO |

### 6.1 Critérios de aceite

**REQ-03** — Dado que o DFP de 2025 já foi carregado com sucesso; Quando o ETL rodar de novo e o ETag não tiver mudado; Então nenhum download acontece, `etl_execucao` recebe `PULADO` e as contagens não mudam.

**REQ-04** — Dado um banco (plano FINANCEIRO); Quando os indicadores forem montados; Então `margem_liquida` e `roic` são nulos e `cobertura_json` explica que `3.05` no banco não é EBIT.

**REQ-09** — Dado o universo monitorado e o IPE de 2026; Quando `--comunicados` rodar; Então PETR4 tem 93 documentos `FATO_RELEVANTE` + `COMUNICADO_MERCADO` entregues em 2026 (conferido contra o CSV em 2026-09-26). Dado que a carga já rodou; Quando rodar de novo com o mesmo ETag; Então os anos saem `PULADO` e nenhum evento é publicado. Com `--forcar` e o mesmo arquivo, `gravados=0`.

### 6.2 Comunicados (base IPE)

- **Fonte:** `IPE/DADOS/ipe_cia_aberta_{ano}.zip`, um CSV latin-1 com todo documento eventual entregue à CVM. Republicado ~1x/semana; o ETag decide se processa.
- **Anos:** o atual e o anterior, por padrão (`--ano` sobrescreve).
- **Categorias padrão:** `FATO_RELEVANTE`, `COMUNICADO_MERCADO`, `AVISO_ACIONISTAS`, `PROVENTOS`, `CALENDARIO_EVENTOS`, `RESULTADOS`. `ASSEMBLEIA` só com `--categoria ASSEMBLEIA` (6,6 mil documentos/ano, quase tudo rotina). O resto (regimentos, políticas) vira `OUTROS` e não é carregado.
- **Identidade:** `numProtocolo` do link de download. `Protocolo_Entrega` vem vazio nos relatórios automáticos de proventos e se repete em linhas duplicadas; a base traz só a versão vigente, e a maior `Versao` vence.
- **CNPJ vem de `cvm_ticker`:** ticker sem carga de fundamentos não tem comunicado (log `Sem CNPJ em cvm_ticker`).
- **`--forcar`:** ignora o ETag. Use quando o universo ou as categorias mudarem; `--simbolo` explícito já força.
- **Não copia conteúdo:** só metadados e o link oficial do RAD.

---

## 7. Decisões

| ID | Questão | Decisão |
|---|---|---|
| DEC-E01 | De-para por código ou por rótulo? | **Rótulo** + `ST_CONTA_FIXA`, código só como desempate. Código produz número errado em silêncio |
| DEC-E02 | Fonte da quantidade de ações | **FRE**, por ter unidade consistente |
| DEC-E03 | LPA/VPA/ROE: consolidado ou controlador? | **Controlador**, que é o que o mercado publica |
| DEC-E04 | Gravar P/L e P/VP? | **Não.** Derivados na leitura pelo `gestor`, senão nascem obsoletos |
| DEC-E05 | Quem cria as tabelas? | IMPLEMENTADO — somente `infra-b3-ecossytem/mysql-migrations`, executado pelo Flyway. Este app apenas verifica tabelas e faz DML; `infra#DEC-01` definida em 2026-09-27 |
| DEC-E06 | Carregar todas as companhias ou só as monitoradas? | **Só as monitoradas.** Um lugar só para escolher ativo |
| DEC-E07 | Chave dos comunicados | **`numProtocolo` do link**, não `Protocolo_Entrega` (vazio em 501 linhas de 2026). Tabela guarda CNPJ; ticker na leitura |
| DEC-E08 | Comunicados: onde descobrir o CNPJ do ticker | **`cvm_ticker`** (mantida pela carga de fundamentos), em vez de baixar o FCA de novo |
| DEC-E09 | Opções do COTAHIST: tabela dedicada ou extensão de `cotacao_b3_diaria`? | IMPLEMENTADO — tabela dedicada `opcao_b3_diaria` (V20, 2026-10-07). Campos de derivativo (vencimento, preço de exercício) não poluem `cotacao_b3_diaria`; contrato de leitura do `gestor-ativos-brutos` permanece limpo. |

---

## 8. Problemas conhecidos

| ID | Sev. | Problema | Status |
|---|---|---|---|
| ISS-E01 | Alto | Sem TTM: só exercício fechado. Trocar a base do LPA move o número 40%+ em empresa volátil, então o Graham **não** deve consumir estes dados ainda | IMPLEMENTADO (2026-09-26: DFP + ITR atual − ITR comparável) |
| ISS-E02 | Médio | `capex` não é extraível (contas `6.02.xx` são texto livre). FCL usa investimento total como proxy | PLANEJADO |
| ISS-E03 | Médio | ROIC usa convenção interna explícita: NOPAT nominal sobre EBIT, com alíquota nominal de 34%, dividido por capital investido do controlador (`PL controlador + dívida bruta - caixa`). A divergência contra Fundamentus permanece explicada pela diferença de metodologia, não por regra implícita | IMPLEMENTADO (TASK-E06, 2026-10-08) |
| ISS-E04 | Médio | `RENT3` diverge 43,8% do Fundamentus sem explicação; a DRE extraída fecha internamente | PLANEJADO |
| ISS-E05 | Baixo | `PLANO_SEGURADORA` não exercitado com dado real | PLANEJADO |
| ISS-E06 | Baixo | Ticker de companhia sem DFP consolidada cai para individual sem sinalizar na resposta | PLANEJADO |
| ISS-E07 | Médio | `numero_negocios` (posições 148–152 do COTAHIST) é lido pelo leitor mas nunca gravado em `cotacao_b3_diaria`; sem ele não há como distinguir volume concentrado (poucos negócios grandes) de volume distribuído | IMPLEMENTADO (TASK-E10, 2026-10-07) |
| ISS-E08 | Médio | ISIN disponível em duas fontes (COTAHIST posições 231–242; FCA `valor_mobiliario`) mas nunca lido nem persistido; sem ISIN não é possível resolver renomeações de ticker de forma canônica nem cruzar com bases internacionais | IMPLEMENTADO (TASK-E11, 2026-10-07) |
| ISS-E09 | Médio | `QT_ACAO_ORDINARIA` e `QT_ACAO_PREFERENCIAL` da composição de capital do DFP chegam sempre `0` porque o domínio `ComposicaoCapital` não as carrega; a entidade ORM já tem as colunas — é apenas uma omissão no mapeamento de domínio | IMPLEMENTADO (TASK-E12, 2026-10-07) |
| ISS-E10 | Baixo | `Situacao_Registro` e `Data_Constituicao` do FCA `geral` são ignorados; empresa com registro cancelado na CVM não pode ser distinguida de empresa ativa na consulta do painel | IMPLEMENTADO (TASK-E13, 2026-10-07) |
| ISS-E11 | Baixo | `DFC_MD` (DFC método direto) está presente no ZIP do DFP/ITR mas nunca é aberto; empresas que só reportam o método direto ficam sem dados de fluxo de caixa operacional | IMPLEMENTADO (TASK-E15, 2026-10-07) |
| ISS-E12 | Baixo | Registros de opções do COTAHIST (BDI 12, 14) são descartados no filtro de mercado; dados de vencimento, preço de exercício e código base ficam fora do ecossistema | IMPLEMENTADO (TASK-E16, 2026-10-07) |
| ISS-E13 | Alto | A imagem `ewertonmiranda/etl-fundamentos-cvm:develop` é de 2026-09-28 (`f8c7254`, PR #5) e não tem `--conciliar`: o passo "conciliacao brapi x B3" da rotina da manhã sai com código 2 (`unrecognized arguments`) em toda execução desde 2026-09-29. O código está na develop desde 2026-10-07 (`1feea54`, PR #6), mas o deploy desse merge falhou no lint (`E501` em `publicador_sqs.py:45` e `:65`), então nenhuma imagem nova foi publicada. Na feature há um terceiro `E501` (`repositorios.py:156`); o PR automático falha desde 2026-10-05 | PLANEJADO (TASK-E18) |
| ISS-E14 | Médio | `ClienteHttpCvm.assinatura()`/`baixar()` repetem erros transitórios de HEAD/GET com espera crescente e preservam falha imediata para 4xx definitivo; um único HTTP 520/timeout não aborta mais a carga até a próxima rodada | IMPLEMENTADO (TASK-E19, 2026-10-08) |
| ISS-E15 | Médio | Rotina da manhã e backup perdem o dia quando o PC está desligado no horário (07:00 / 12:30): as tarefas não têm "executar assim que possível" nem o gatilho de logon +5 min previsto no plano. Ocorreu em 2026-10-02, 10-06 (backup) e 10-07 (ambas; `0x800710E0`, PC ligado às 07:49). Dono: `infra-b3-ecossytem` | PLANEJADO (TASK-E20) |
| ISS-E16 | Médio | Logs e arquivos que uma sessão do app Claude grava em `%LOCALAPPDATA%\b3-ecossistema` vão para a cópia virtualizada do pacote MSIX (`Packages\Claude_pzs8sxrjxfjjc\LocalCache\Local\b3-ecossistema`), e a leitura de dentro do app vê essa cópia em vez do log real. Diagnósticos de 2026-10-05 e 10-07 leram logs parados; o dump `minha_base_pre-V16_2026-09-30.sql.gz` existe só na cópia. O backup também falhou em 2026-10-04 (`mysqldump`) por não aguardar a stack. Dono: `infra-b3-ecossytem` | PLANEJADO (TASK-E21) |
| ISS-E17 | Alto | `infra-b3-ecossytem/infra/s3/main.tf` recebeu 86 linhas de lixo (`m,  ,,,` e linhas em branco) no commit `47483c2`, já em `origin/feature-nova-infra`. `terraform fmt` acusa "Argument or block definition required" na linha 4; quando chegar à develop, a imagem nova do provisionador falha e o `Garantir-Stack` aborta a rotina. Dono: `infra-b3-ecossytem` | PLANEJADO (TASK-E22) |

---

## 9. Tarefas

| ID | Tarefa | Depende | Status |
|---|---|---|---|
| TASK-E01 | Carregar ITR e derivar TTM (DRE do ITR é acumulada no ano; trimestre sai por subtração) | REQ-06 | IMPLEMENTADO (2026-09-26) |
| TASK-E07 | Ingerir COTAHIST anual com ETag, filtro de ativos monitorados e upsert em `serie_historica` | REQ-08 | IMPLEMENTADO (2026-09-26) |
| TASK-E02 | Fixture de seguradora e validação do plano | ISS-E05 | PLANEJADO |
| TASK-E03 | Investigar a divergência de `RENT3` | ISS-E04 | PLANEJADO |
| TASK-E04 | Expor série histórica de indicadores por símbolo, com filtro opcional de `tipo_periodo`, limite e ordenação cronológica no `RepositorioIndicadorSql.historico()`; teste unitário cobre conversão para domínio, filtro, limite e `ORDER BY` | — | IMPLEMENTADO (2026-10-08) |
| TASK-E05 | Integrar proventos (dividendos, JCP) da B3 | — | PLANEJADO |
| TASK-E06 | Fixar convenção de ROIC e documentá-la no domínio: `CONVENCAO_ROIC` e `capital_investido_controlador()` tornam a fórmula auditável; teste unitário cobre NOPAT nominal, capital do controlador e caso sem capital investido positivo | ISS-E03 | IMPLEMENTADO (2026-10-08) |
| TASK-E08 | Carga de comunicados da base IPE com ETag, dedupe por protocolo, upsert por versão e evento por ticker | REQ-09 | IMPLEMENTADO (2026-09-26) |
| TASK-E09 | Agendar `--comunicados` diariamente (cron do host ou GitHub Actions); sem novidade custa 2 HEAD | REQ-09 | PLANEJADO |

### Backlog: dados disponíveis nas fontes não capturados (2026-10-07)

As tarefas abaixo cobrem campos presentes nos arquivos já baixados que o ETL ignora hoje. Todas requerem migration em `infra-b3-ecossytem` antes de serem iniciadas, exceto TASK-E12 (ORM já tem as colunas) e TASK-E17 (só adiciona ao catálogo existente). Antes de começar qualquer TASK deste bloco: abrir a tarefa correspondente no hub (`infra-b3-ecossytem/SPEC.md` seção 1A.4) e marcar `EM ANDAMENTO`.

| ID | Tarefa | Depende | Status |
|---|---|---|---|
| TASK-E10 | **Número de negócios (COTAHIST):** `numero_negocios` já lido pelo `LeitorCotahist`, em `CandleB3` e em `CotacaoB3DiariaEntity`; faltava a migration. **Migration V17** criada. **Aceite:** PETR4 em qualquer pregão de 2025 tem `numero_negocios > 0`; `pytest` cobre o campo no leitor com fixture de linha fixa | REQ-10, migration nova | IMPLEMENTADO (V17, 2026-10-07) |
| TASK-E11 | **ISIN (COTAHIST + FCA):** `isin = linha[230:242]` adicionado ao `LeitorCotahist` e a `CandleB3`; `Codigo_ISIN` lido em `fonte_cvm.tickers()`; `isin` adicionado a `Ticker`, `TickerEntity`, `CotacaoB3DiariaEntity`, `salvar_tickers()` e `salvar_candles_b3()`. **Migration V17** (ADD COLUMN nas duas tabelas + índice). **Aceite:** PETR4 tem `isin = 'BRPETRPDIPBS'` em `cvm_ticker`; ISIN do COTAHIST bate com o do FCA para o mesmo papel | REQ-11, migration nova | IMPLEMENTADO (V17, 2026-10-07) |
| TASK-E12 | **Breakdown ON/PN (DFP composição de capital):** no domínio `ComposicaoCapital` adicionar campos `qt_acao_ordinaria`, `qt_acao_preferencial`; em `fonte_cvm._composicao_do_dfp()` ler `QT_ACAO_ORDINARIA` e `QT_ACAO_PREFERENCIAL`; escala detectada via FRE aplicada a ambos; `repositorios.salvar_composicao()` passa os dois campos. **Sem migration** — `ComposicaoCapitalEntity` já tem as colunas. Nota: `qt_acao_ord_tesouro`/`qt_acao_pref_tesouro` não adicionados — entidade ORM não tem essas colunas; cobertos por TASK-E14 se necessário. **Aceite:** WEG DFP 2024 tem `qt_acao_ordinaria > 0` e `qt_acao_preferencial = 0`; ITUB4 tem as duas positivas | REQ-12 | IMPLEMENTADO (2026-10-07) |
| TASK-E13 | **Situação do registro CVM (FCA geral):** `Situacao_Registro`, `Data_Constituicao` e `UF_Municipio` lidos em `fonte_cvm.empresas()`; adicionados a `Empresa`, `EmpresaEntity` e `salvar_empresas()`. **Migration V18** criada. **Aceite:** empresa com registro cancelado aparece com `situacao_registro = 'CANCELADA'`; campo `NULL` para companhia não encontrada no FCA do ano | REQ-13, migration nova | IMPLEMENTADO (V18, 2026-10-07) |
| TASK-E14 | **Breakdown ON/PN via FRE:** complementar TASK-E12 usando o FRE como fonte autoritativa das classes. O layout real traz ON/PN nas colunas `Quantidade_Acoes_Ordinarias` e `Quantidade_Acoes_Preferenciais` da linha `Tipo_Capital = 'Capital Integralizado'` (não em linhas próprias); o leitor mantém compatibilidade com linhas por classe. Consolidar com o DFP usando a mesma lógica de escala e completar pelo DFP somente a classe ausente no FRE. **Aceite verificado com os ZIPs oficiais de 2025:** ITUB4 = ON 5.617.742.977 e PN 5.409.126.215 no FRE; DFP × 1.000 difere por apenas 23 e 215 ações, respectivamente | REQ-12, TASK-E12 | VERIFICADO (2026-10-07) |
| TASK-E15 | **DFC método direto:** `DFC_MD = "DFC_MD"` adicionado ao `modelo.py`; `DFC_MD: "DFC_MD"` adicionado a `SUFIXO_DEMONSTRACAO` em `fonte_cvm.py`; filtro de período do ITR atualizado para incluir `DFC_MD`; sem migration — dados entram em `fato_contabil` com `demonstracao = 'DFC_MD'`. **Aceite:** Banco do Brasil (que reporta DFC direta) passa a ter linhas `DFC_MD` em `fato_contabil`; empresas sem o arquivo no ZIP não geram erro | REQ-14 | IMPLEMENTADO (2026-10-07) |
| TASK-E16 | **Dados de opções do COTAHIST:** `BDI_OPCAO_COMPRA/VENDA = "12"/"14"` em `leitor_cotahist.py`; `ler_opcoes_linhas()` / `ler_opcoes_zip()` extraem BDI 12 e 14 com PTOEXE [188:201], DATVEN [202:210], ISIN [230:242]; `OpcaoB3` dataclass em `serie_historica.py`; `FonteB3.opcoes()` reutiliza o cache; `OpcaoB3DiariaEntity` + `RepositorioOpcaoSql.salvar_opcoes_b3()`; `FonteDeOpcoes` e `RepositorioOpcao` protocols; `CarregarSeriesHistoricas` com `fonte_opcoes` e `repositorio_opcao` opcionais; **Migration V20** criada. **Aceite:** PETRD... tem registros com vencimento e preço de exercício não nulos; reprocessar o mesmo arquivo não duplica | REQ-15, DEC-E09, migration nova | IMPLEMENTADO (V20, 2026-10-07) |
| TASK-E17 | **Contas de FCO bruto (DFC_MD):** catálogo, TTM (`DEMONSTRACOES_DE_FLUXO`) e mart completos. `fco_bruto` adicionado a `Indicadores`, `IndicadorFundamentalistaEntity`, `COLUNAS_ATUALIZAVEIS`, `salvar()` e `MontadorDeIndicadores.montar()`. **Migration V19** criada. **Aceite:** empresa com DFC direta tem `fco_bruto` em `indicador_fundamentalista`; empresa sem DFC direta mantém `fluxo_caixa_operacional` via DFC_MI | REQ-14, TASK-E15 | IMPLEMENTADO (V19, 2026-10-07) |

### Backlog: saúde da rotina agendada (investigação de 2026-10-07)

Achados da análise das execuções agendadas (logs reais em `%LOCALAPPDATA%\b3-ecossistema` lidos por processo fora do app Claude, cruzados com `etl_execucao`). As cargas IPE/DFP/TTM/COTAHIST e o backup **funcionam** quando o PC está ligado no horário: COTAHIST carregado em 2026-10-01, 10-05 e 10-06 (até o pregão de 10-05); backup com restauração conferida em 09-27, 09-28, 09-29, 10-01 e 10-05. TASK-E20 a E22 são de `infra-b3-ecossytem` e ficam aqui como dependência operacional do ETL: abrir no hub antes de executar.

| ID | Tarefa | Depende | Status |
|---|---|---|---|
| TASK-E18 | **Destravar o deploy do `--conciliar`:** quebrar as linhas `E501` em `app/adaptadores/mensageria/publicador_sqs.py` (45, 65; arquivo de outra sessão, combinar com o dono) e `app/adaptadores/persistencia/repositorios.py` (156); commit na feature, merge na develop e confirmar o workflow "Deploy to Docker Hub" verde. **Aceite:** Dado o push na develop, Quando o CI roda, Então `ruff check app tests main.py` passa e a imagem `develop` nova responde `main.py --help` listando `--conciliar`; na rotina seguinte, `etl_execucao` tem uma linha `CONCILIACAO_BRAPI_B3` e `cargas-etl.log` não tem `unrecognized arguments` | ISS-E13 | PLANEJADO |
| TASK-E19 | **Nova tentativa no cliente HTTP:** `ClienteHttpCvm._abrir_com_retry()` repete HEAD e GET até 3 tentativas com espera crescente configurável (`5 s`, `15 s`) apenas para erro transitório (HTTP 5xx, 429, timeout, conexão), registra cada nova tentativa em `WARNING` e mantém 4xx definitivo falhando na primeira. Testes em `tests/adaptadores/test_cliente_http.py` cobrem 520 seguido de 200 em `assinatura()`, timeout seguido de sucesso em `baixar()`, 404 sem retry e esgotamento de tentativas. **Validação local em 2026-10-08:** execução de pytest bloqueada porque o Python global e o `.venv` não possuem `pytest` instalado; implementação e testes existem no branch | ISS-E14 | IMPLEMENTADO (2026-10-08) |
| TASK-E20 | **(infra) Recuperar execução perdida:** em `scripts/registrar-rotinas.ps1`, marcar `StartWhenAvailable` nas tarefas "B3 - Rotina da manha" e "B3 - Backup MySQL" e/ou registrar o gatilho de logon +5 min (precisa rodar fora do sandbox, pelo usuário). **Aceite:** Dado o PC desligado às 07:00, Quando é ligado às 07:49, Então a rotina roda até ~07:55 e `etl_execucao` tem `GARANTIR_STACK` do dia | ISS-E15 | PLANEJADO |
| TASK-E21 | **(infra) Logs e backups fora da virtualização do app Claude:** mover `PastaLocal` de `comum.ps1` para fora de `AppData` (ex.: `C:\Users\<user>\b3-ecossistema`) ou documentar que sessões do app devem ler os logs por processo externo; copiar `minha_base_pre-V16_2026-09-30.sql.gz` da cópia do pacote para a pasta real de backups; em `backup-mysql.ps1`, chamar `Garantir-Stack` antes do `mysqldump`. **Aceite:** um log escrito pela rotina agendada é lido idêntico de dentro e de fora do app; o dump pré-V16 está na pasta real; backup com Docker recém-ligado não falha em `mysqldump` | ISS-E16 | PLANEJADO |
| TASK-E22 | **(infra) Limpar `infra/s3/main.tf`:** remover as 86 linhas antes de `resource "aws_s3_bucket"` com commit novo na `feature-nova-infra` (sem reescrever o histórico já enviado); acrescentar `terraform fmt -check` e `terraform validate` ao workflow de feature da infra. **Aceite:** `terraform fmt -check infra/s3/main.tf` sai 0 na imagem do provisionador; CI da infra falha se um `.tf` não for HCL válido | ISS-E17 | PLANEJADO |

---

## 10. Verificação

```bash
pytest tests/ -m "not externo"    # domínio puro
ruff check app tests main.py
mypy app
pytest -m externo -s              # confronto com o Fundamentus, sob demanda

docker compose --profile etl run --rm etl-fundamentos-cvm
docker compose --profile etl run --rm etl-fundamentos-cvm --comunicados
```

Regressão de referência (WEGE3, DFP 2025): LPA 1,5197 · VPA 4,1512 · ROE 36,61% · margem 16,61% · dívida líquida −1,71 bi.

---

## 11. Aviso regulatório

Este serviço produz **indicador contábil**, não rótulo de decisão. Ver `gerar-insights#ISS-F6` sobre a Res. CVM 20/2021: nada aqui deve ser apresentado como recomendação de investimento.

## Revisão integrada de 2026-09-27

| Entrega | Estado | Evidência e limite |
|---|---|---|
| Proprietário único do schema | IMPLEMENTADO | Infra/Flyway: V1 bootstrap, V11 inbox; serviços não executam migrations |
| Eventos e recomendações | IMPLEMENTADO | schemas canônicos em infra/contracts; enum gerado em Java, Python e JS; versões desconhecidas ficam para DLQ |
| Leituras HTTP e idempotência | IMPLEMENTADO | GET sem persistência/publicação; inbox e efeitos na mesma transação; ACK posterior ao commit |
| Verificação desta entrega | EM ANDAMENTO | Resultados registrados em infra/VERIFICACAO-2026-09-27.md; não representa deploy no banco em uso |

## Plano LAC: 9 lacunas de assertividade (proposta de 30-09-2026, EM AVALIAÇÃO)

Plano completo, fontes e a migração única **V16** em `infra-b3-ecossytem/SPEC.md`, seção Plano LAC. Este serviço cobre **L1, L2, L3, L4, L6 (contas), L8 (datas) e os campos novos do COTAHIST (LAC-ETL-7)**. Só COTAHIST e CVM.

### LAC-ETL-1: DVA e DMPL (L1, L6)

- Ler `dfp_cia_aberta_DVA_{con,ind}` e `dfp_cia_aberta_DMPL_{con,ind}` (e os equivalentes do ITR), que já estão no cache e hoje são ignorados. Mesma escolha de grupo dos outros documentos: consolidado quando preenchido, senão individual.
- Gravar em `fato_contabil` com `demonstracao = 'DVA' | 'DMPL'`. Na DMPL, `COLUNA_DF` vai para a nova coluna `coluna_df`; nas outras demonstrações fica `''`. A entidade `FatoContabilEntity` e o `salvar_linhas` passam a incluir a coluna.
- Derivar `provento_contabil`:
  - `jcp`: conta DVA pelo rótulo "juros sobre o capital próprio" (código 7.08.04.01 como desempate), com a mesma estratégia rótulo → código do resolvedor.
  - `dividendos`: rótulo "dividendos" (7.08.04.02).
  - **ITR vem acumulado no ano**: o trimestre isolado é a diferença para o ITR anterior do mesmo ano (o 1º trimestre é o próprio acumulado); o 4º trimestre sai da DFP menos o 3º ITR.
  - `por_acao = total / acoes_ex_tesouraria` da composição de capital do mesmo documento.
  - `data_entrega`: DT_RECEB do índice de entregas (`datas_de_entrega`), como já é feito para os indicadores.
  - Valor ausente fica `NULL` com o motivo em `cobertura_json`, nunca 0 (mesma regra de 29-09-2026 para o lucro).
- Conferência: WEG DFP 2024 consolidada = JCP R$ 1.134.258 mil e dividendos R$ 2.056.668 mil (visto no arquivo da CVM em 30-09-2026).

### LAC-ETL-2: eventos corporativos (L2)

O FRE aberto não tem tabela de desdobramentos, mas o **COTAHIST marca o dia ex** no ESPECI (LAC-ETL-7). Três evidências:

1. **Data (COTAHIST):** primeiro pregão com marca de evento societário (EB bonificação, EG, EX; significado de cada marca conferido no layout oficial da B3 antes de codificar). Várias marcas seguidas contam como um evento só (RCSL3: EB em 10 e 11-03-2026, um evento).
2. **Proporção (CVM):** entre as composições de capital antes e depois dessa data, `r = ações depois / ações antes`, por espécie (ON para tickers final 3; PN para 4, 5 e 6; units, final 11, ficam de fora).
3. **Confirmação (preço):** `fechamento anterior / abertura do dia ex` dentro de 3% de `r`.

Com marca e proporção batendo → `evento_corporativo` com `origem = 'INFERIDO_CVM_COTAHIST'`, `data_efeito` no dia marcado e `evidencia_json` com os três números; a confirmação de preço entra na `confianca`. Salto de preço sem marca **não** vira evento: é queda real, e o backtest continua tratando como hoje (regra dos 40%). `origem = 'MANUAL'` corrige o que escapar.

Comando novo: `--eventos-corporativos [--ano ...]`, idempotente, registrando `EVENTOS_CORPORATIVOS` em `etl_execucao`.

### LAC-ETL-3: histórico trimestral desde 2011 (L3)

**Status (07-10-2026): EM ANDAMENTO.** Código pronto: `escolher_trios_por_corte` monta um TTM por trimestre (DFP casada pela data, entre os dois ITRs) e o filtro do ITR fica com o acumulado que começa no início do exercício social, não em 1º/1 (`_so_acumulado`). Falta a carga do ITR 2011–2023. Proventos de quem fecha em março (RAIZ4) ficam só com o valor anual: os ITRs posteriores à DFP do ano são descartados no isolamento, sem dupla contagem.

- O `CarregarTtm` monta hoje **só o trimestre mais recente de cada ano** (`escolher_trios` pega o ITR mais recente). Para o histórico, montar o trio de **cada** trimestre (março, junho e setembro de cada ano, mais o anual), mantendo a regra do mesmo grupo.
- Carregar ITR 2011–2023 (download novo; o mesmo leitor). Grava `indicador_fundamentalista` com `tipo_periodo = 'TTM'` por trimestre, com a `data_entrega` do ITR.
- Tratar o exercício social fora do ano civil (RAIZ4, de abril a março), pendência aberta em 28-09-2026: o acumulado do ITR começa no início do exercício, não em 1º de janeiro.

### LAC-ETL-4: mais anos (L4)

- DFP 2010–2015 e COTAHIST 2009–2015 pelos comandos atuais (`--ano`, `--cotahist --ano`).
- Risco a checar antes do backfill: layout dos CSVs da CVM de 2010–2015 e dos arquivos COTAHIST antigos (mudanças de cabeçalho ou de escala). Testar primeiro um ano de cada.

### LAC-ETL-5: contas de qualidade (L6)

Novas regras no catálogo (plano GERAL; bancos e seguradoras ficam `nao-aplicavel`, como hoje):

| Métrica | Demonstração | Rótulo | Código (desempate) |
|---|---|---|---|
| `ativo_total` | BPA | "ativo total" | 1 |
| `ativo_circulante` | BPA | "ativo circulante" | 1.01 |
| `passivo_circulante` | BPP | "passivo circulante" | 2.01 |
| `lucro_bruto` | DRE | "resultado bruto" | 3.03 |

### LAC-ETL-6: datas do IPE (L8)

36 comunicados têm `data_referencia` inválida (anterior a 2000 ou mais de um ano depois da entrega; há uma em 2925). Na carga: data de referência fora da faixa vira `NULL`, com aviso no log; `data_entrega` segue intacta e é a data usada nos fatores de evento.

### LAC-ETL-7: campos do COTAHIST hoje ignorados (L1, L2, L5)

Achados da Sessão 01, conferidos no COTAHIST 2026 em 30-09-2026. O `leitor_cotahist` passa a ler e gravar em `cotacao_b3_diaria` (colunas novas da V16):

| Campo (posições) | Coluna | Uso |
|---|---|---|
| ESPECI (40-49) | `especificacao`, `marca_ex` (sufixo EJ, ED, EB, EG, ES, EDJ…) | Data ex de proventos (L1) e de eventos societários (L2) |
| FATCOT (211-217) | `fator_cotacao` | **Dividir abertura, máxima, mínima, fechamento e preço médio pelo fator ao gravar.** Hoje AZUL53 (1.000.000), GOLL54 (1.000) e IBOV11 (100) estão gravados multiplicados |
| PREMED (96-108) | `preco_medio` | Preço médio ponderado (VWAP) |
| PREOFC / PREOFV (122-147) | `melhor_oferta_compra`, `melhor_oferta_venda` | Spread no fechamento, para custo e liquidez (mediana 0,57%, p90 3,4% segundo a Sessão 01) |

- A correção do FATCOT é um **defeito atual**, que vale mesmo sem o resto do plano.
- Recarga de 2016–2026 pelo cache, sem download.

### Aceite

- WEG, ITUB4 e TIMS3: `provento_contabil` bate com a DVA publicada em 3 anos escolhidos.
- AZUL53 e GOLL54 com preço dividido pelo FATCOT; RCSL3 com `marca_ex = 'EB'` em 10-03-2026.
- Lista de desdobramentos e grupamentos conhecidos, montada na revisão, detectada com a data certa; nenhum evento gravado com confiança abaixo do limiar.
- TTM trimestral de 2011 a 2026 para os ativos do universo, sem trimestre repetido e sem misturar grupos.
- pytest, ruff e mypy verdes; nenhum valor 0 gravado no lugar de conta ausente.
