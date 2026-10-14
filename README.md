# etl-fundamentos-cvm

Job em lote que carrega fundamentos contábeis dos **dados abertos da CVM** para o MySQL do ecossistema B3, cobrindo exatamente o que o plano gratuito da BRAPI não entrega: ROE, ROIC, margens, dívida líquida e fluxo de caixa livre.

Roda, reporta e encerra — não é serviço. O agendamento fica fora (cron do host ou GitHub Actions); container dormindo é um scheduler ruim.

```bash
docker compose --profile etl run --rm etl-fundamentos-cvm    # no compose da infra
python main.py                                               # local
python main.py --ano 2025 --simbolo WEGE3
```

## Por que ele existe

Os dados da CVM são gratuitos e oficiais, mas chegam como ZIP de CSV em latin-1, um arquivo por ano com todas as companhias abertas. Não são consumíveis direto, e três armadilhas produzem número errado **em silêncio** se ignoradas:

| Armadilha | Consequência de ignorar |
|---|---|
| `CD_CONTA` não é estável entre companhias | PL é `2.03` na WEG, `2.07` no BBAS3, `2.08` no ITUB4 — e `2.03` no BBAS3 é "Provisões" |
| `3.05` muda de significado por setor | É EBIT na WEG e "lucro antes dos tributos" em banco |
| `QT_ACAO` não tem unidade padronizada | WEG declara unidades, VALE declara milhares: LPA 1000x errado |

A chave estável é o par `ST_CONTA_FIXA='S'` + `DS_CONTA`: a CVM padroniza a **descrição** das contas obrigatórias mesmo quando a posição muda. É isso que `app/dominio/plano_contas/` implementa, com `CD_CONTA` só como desempate.

O denominador de LPA e VPA vem do FRE (`capital_social`, tipo "Capital Integralizado"), que tem unidade consistente; a composição do DFP fica só com as ações em tesouraria, reescaladas pelo fator detectado entre as duas fontes.

## Arquitetura

Camadas com dependência apontando para dentro. Nada em `dominio/` ou `aplicacao/` importa SQLAlchemy, `boto3`, `urllib` ou `zipfile`.

```
main.py                      composition root: so instancia e injeta
app/
  dominio/                   PURO - zero I/O. Testavel sem banco, rede ou arquivo
    modelo.py                LinhaContabil, DocumentoContabil, Indicadores
    plano_contas/            catalogo de regras, classificador, resolvedor
    calculo/                 derivacao dos indicadores
    montador_indicadores.py  servico de dominio que junta as tres coisas
  portas/                    Protocols - o que aplicacao e dominio conhecem
  adaptadores/
    cvm/                     HTTP, cache, ZIP/CSV, normalizacao
    persistencia/            entidades, repositorios, unidade de trabalho
    mensageria/              publicacao em SQS
  aplicacao/                 caso de uso, orquestra as portas
```

Cada letra de SOLID tem endereço aqui:

- **SRP** — `ClienteHttpCvm` só fala HTTP; `LeitorDePacoteCvm` só abre ZIP; `NormalizadorDeLinhas` só aplica `ÚLTIMO`/`VERSAO`/`ESCALA`; `ResolvedorDeContas` só localiza conta.
- **OCP** — métrica nova é uma `RegraConta` a mais em `catalogo.py`, sem tocar no resolvedor.
- **LSP** — `ResolucaoPorRotulo` e `ResolucaoPorCodigo` são intercambiáveis atrás de um Protocol; o resolvedor tenta em ordem sem saber qual é qual.
- **ISP** — quatro portas de repositório pequenas; quem só lê o universo não depende da porta de escrita.
- **DIP** — `CarregarFundamentos` recebe portas no construtor; concretos só em `app/config/composicao.py`.

DI é por construtor, com argumentos **obrigatórios** — sem `x or ClasseConcreta()`, que torna a injeção opcional e reacopla pelo default. `Settings` é instanciado uma vez em `main.py` e passado adiante; nenhuma classe o constrói por conta própria.

## Persistência

Duas camadas, e só a segunda é contrato de leitura:

```
CVM (ZIP/CSV) ──> fato_contabil ──> indicador_fundamentalista ──> gestor-ativos-brutos
                  (landing cru)     (mart derivado)                (único leitor)
```

A landing guarda as contas cruas já normalizadas, **só da whitelist** que o de-para usa: no DFP 2025 isso reduz 240.472 linhas para 4.785 (2,0%), e para 101 linhas quando restrito a 10 tickers. Mantê-la permite recalcular o mart quando o de-para mudar, sem rebaixar nada.

O schema é de fora — `infra-b3-ecossytem/mysql-init/1 - schema.sql`. Este app não cria nem altera tabela.

### Idempotência

Rodar duas vezes produz o mesmo resultado. Três mecanismos:

1. **`HEAD` antes de `GET`** — `ETag` gravado em `etl_execucao`; igual ao da última carga bem-sucedida, pula o ano inteiro. Uma execução semanal sem novidade custa 3 requisições HEAD.
2. **Cache em volume** (`cvm_cache:/var/cache/cvm`) — ZIPs sobrevivem à recriação do container.
3. **`INSERT ... ON DUPLICATE KEY UPDATE`** em lote, com guarda de versão.

Commit acontece **só** na unidade de trabalho. Repositório faz `add`/`execute` e nada mais.

## Quais ativos são carregados

O universo vem de `ativo_monitorado`, a mesma tabela que o `gestor-ativos-brutos` popula via `POST /ativos/registrar/{ticker}`. Um lugar só para escolher ativo, não dois.

O download é sempre do arquivo anual inteiro — a CVM não tem endpoint por ticker. O filtro acontece na carga.

## Configuração

Tudo por variável de ambiente; veja `.env.example`. As que importam:

| Variável | Padrão | Para quê |
|---|---|---|
| `CVM_ANOS` | `2024-2025` | Aceita `2019-2025` ou `2023,2024` |
| `CVM_CACHE_DIR` | `./cache` (local), `/var/cache/cvm` (container) | Onde os ZIPs ficam |
| `DB_*` | MySQL do ecossistema | Destino |
| `FUNDAMENTOS_QUEUE_NAME` | `sqs-fundamentos-atualizados` | Evento de carga concluída |
| `COMUNICADOS_QUEUE_NAME` | `sqs-comunicados-publicados` | Evento de comunicados novos (`--comunicados`) |

## Comunicados oficiais (base IPE)

```bash
python main.py --comunicados                          # ano atual e anterior, categorias padrão
python main.py --comunicados --categoria ASSEMBLEIA   # inclui atas e editais
python main.py --comunicados --forcar                 # ignora o ETag (universo mudou)
```

Carrega fatos relevantes, comunicados ao mercado, avisos aos acionistas, proventos, calendário de eventos e divulgação de resultados da base IPE da CVM em `comunicado_cvm`. Só metadados e o link oficial do documento: o conteúdo não é copiado. O CNPJ de cada ticker vem de `cvm_ticker`, então rode a carga de fundamentos antes. Regras em `SPEC.md` § 6.2.

## Desenvolvimento

```bash
pip install -r requirements-dev.txt
pytest tests/ -m "not externo"    # dominio puro, sem banco nem rede
ruff check app tests main.py
mypy app
pytest -m externo -s              # confronto com o Fundamentus, sob demanda
```

O CI roda lint, mypy e testes **antes** de publicar imagem — `feature**` abre PR para `develop`, `main`/`develop` publicam no Docker Hub.

## Limitações conhecidas

- **`capex` não é extraível.** As contas `6.02.xx` são `ST_CONTA_FIXA='N'`, texto livre por companhia. O FCL usa o total de investimento como proxy, declarado como tal no `cobertura_json`.
- **ROIC é o indicador mais fraco.** Usa alíquota nominal de 34%; a efetiva exigiria a linha de tributos, que não é estável entre planos. A definição de capital investido também é convenção — damos 31,3% na WEG contra 24,3% do Fundamentus, e nenhuma das duas é "a" certa.
- **Só exercício fechado, sem TTM.** O Fundamentus publica 12 meses móveis. Em empresa de lucro volátil isso sozinho move o LPA mais de 40%. Enquanto o TTM a partir do ITR não existir, estes números **não devem** alimentar o Graham do `gerar-insights`.
- **Seguradoras não foram exercitadas.** `PLANO_SEGURADORA` existe no código mas nenhum ticker testado caiu nele.
- **`RENT3` diverge 43,8% do Fundamentus** por comparação metodológica: o terceiro publica referência TTM, enquanto o ETL usa exercício fechado/entrega CVM para manter rastreabilidade temporal. A DRE extraída fecha internamente (`3.09` = `3.11`, sem operação descontinuada), então a extração é fiel ao arquivo.

Métrica que o plano de contas da companhia não comporta fica **nula de propósito**, com a razão no `cobertura_json` — ausência explícita é melhor que número errado.

## Aviso

Material informativo, não recomendação de investimento.
