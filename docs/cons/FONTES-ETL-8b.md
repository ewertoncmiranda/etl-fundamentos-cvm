# FONTES-ETL-8 (parte 2) — IMPLEMENTADO (2026-10-21)

## Entregue
- Copiados sem alteracao (somente leitura nas worktrees do Codex): `cadastro.py`, `bcb/ifdata.py`, `datas_ex.py`, `leitor_cotahist.py` (diff contra develop: so linhas adicionadas, 103) e os testes.
- Entidades e repositorio (upsert idempotente): `cvm_cadastro` (por cnpj), `banco_indicador_trimestral` (cnpj, data_base), `data_ex_b3` (simbolo, data_ex, marca), `negociacao_b3_diaria` (simbolo, data_pregao, tpmerc).
- `CVM_CADASTRO`: ETag do arquivo unico; troca de auditor entre o retrato gravado e o novo (via `troca_auditor_recente`) vira ALERTA. ROTINA a cada execucao, mas so baixa com ETag novo.
- `IFDATA`: ultimos 4 trimestres ainda nao gravados; liga ao ticker pelo CNPJ de `cvm_ticker` (primeiro ticker ativo em ordem alfabetica; `simbolo` NULL sem ticker; raiz de 8 digitos so vira CNPJ quando um unico CNPJ de `cvm_ticker` comeca por ela). Valores monetarios gravados em R$ (IF.data publica R$ mil); indices como razao (0,17 = 17%).
- Datas ex dentro de `EVENTOS` (`app/aplicacao/datas_ex_b3.py`): usa `calcular_datas_ex` e aplica a regra dos dados reais, identica a do gestor (`primeiroDiaDeCadaJanela`): so o primeiro pregao da sequencia, ate 5 dias corridos desde a linha com marca anterior e mesma marca; marcas diferentes intercaladas sao eventos separados. `datas_ex.py` do Codex NAO cobre a regra (emite toda linha com marca), por isso a regra ficou na funcao de ligacao. Tipo da marca pelo mapa do gestor (X = DESDOBRAMENTO). `valor_declarado` e `origem_valor` NULL. `versao_calculo` = `PRIMEIRO_PREGAO_V1`.
- Mercados do COTAHIST dentro de `COTAHIST`: trilha de ETag `B3_COTAHIST_MERCADOS`, `ler_mercados_zip`, upsert em `negociacao_b3_diaria`; tabela vazia recompoe desde 2016.
- Status: SEM_MUDANCA (ETag igual / nada novo), ALERTA (descartes, troca de auditor), FALHA (erro de fonte; erro de datas ex ou de mercados nao desfaz o que ja foi gravado).

## Evidencia
- `python -m pytest -q tests`: verde.
- Integracao MySQL (`ETL8_MYSQL_URL`, base descartavel `v45_etl8b` com V1..V45, apagada ao fim; `minha_base` intocado): 7 testes passaram (parte 1 e 2).
- IF.data ao vivo (2026-10-21): `ListaDeRelatorio()` responde 200, mas `IfDataCadastro` e `IfDataValores` retornam HTTP 500 ("Erro desconhecido") para 202312, 202412, 202512 e 202606, com `$format`, `$top` ou parametros `@`. Sem chave de API.

## Desvios
- IFDATA nao foi validado ao vivo: o OData do BCB esta devolvendo 500 nas consultas de dados. Enquanto isso o trimestre com mais de 150 dias sem dados vira FALHA (trimestres mais novos contam como aguardando). Alternativa existente, nao implementada (fora do leitor do Codex): `https://www3.bcb.gov.br/ifdata/rest/arquivos?nomeArquivo=ifdata/AAAAMM/...` responde 200.
- `cvm_cadastro`: o leitor so traz situacao, data da situacao, setor, auditor e CNPJ do auditor; `codigo_cvm`, `denominacao` e demais colunas da V45 nao sao preenchidas.
- IF.data: so TipoInstituicao 1 (conglomerado prudencial); instituicoes sem CNPJ resolvivel para a base ficam de fora (contadas em `sem_vinculo`).
- Mercados: `codbdi`, `especificacao` e `data_vencimento` ficam NULL (o leitor nao os fornece); `preco_exercicio` usa os pontos quando nao ha preco em centavos.
- Editados fora da lista: `fonte_b3.py` (metodo `mercados`), `composicao.py` (liga mercados ao COTAHIST e exige `negociacao_b3_diaria` no verificador de schema), `carregar_series_historicas.py`.
