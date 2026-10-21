# FONTES-ETL-8 (parte 1) — IMPLEMENTADO (2026-10-20)

## Entregue
- Entidades V45 em `entidades.py` e `RepositorioFontesPublicasSql` (upsert pela chave unica de cada tabela): `titulo_publico_taxa`, `cvm_auditor`, `cvm_negociacao_administrador`, `cvm_divida_valor_mobiliario` (`hash_linha`), `fundo_posicao_acao` (+ `listar_posicoes_fundo` para `fluxo_por_ativo`).
- `hash_linha` (`app/dominio/fontes_publicas.py`): SHA-256 hex das colunas de conteudo, separadas por U+001F, None vazio, Decimal na escala da coluna, data ISO. Fora do hash: cnpj, data_referencia, versao (chave) e data_entrega.
- Etapas `TESOURO`, `CVM_VLMO`, `CVM_FRE`, `CVM_CDA` em `CATALOGO_ETAPAS` e `ETAPAS_ROTINA`, com `Resultado*` e ramo em `resumo_etapa`: SEM_MUDANCA (ETag igual), ALERTA (registro descartado), FALHA (erro de fonte).
- VLMO: ano corrente e anterior; tabela vazia recompoe 2018+ (forcado). FRE: auditor e divida. CDA: 24 meses, do mais novo ao mais velho; meses com mais de 3 e ja carregados nao fazem nem HEAD.
- `fonte_pacotes.py` (HEAD/ETag/cache), `app/config/composicao_fontes.py`, setting `cvm_fi_cda_base_url`. Sem flags de CLI.

## Evidencia
- `python -m pytest -q tests`: verde (integracao pulada sem variavel).
- `tests/integracao/test_fontes_publicas_mysql.py` (ETL8_MYSQL_URL): 4 testes passaram no banco descartavel `v45_etl8` (V1..V45), depois apagado. `minha_base` intocado.

## Desvios
- Recompras do BPP: sem tabela na V45; so o calculo (`recompras.py`) segue exposto, nada persistido.
- VLMO/divida: linhas identicas dentro da mesma versao colapsam (hash). Reapresentacao (versao maior) apaga as versoes antigas da mesma (cnpj, referencia).
- Ano corrente sem arquivo na CVM (404) conta como pulado, nao erro; CDA sem nenhum arquivo em 24 meses e FALHA.
- Competencia do CDA gravada como dia 1; linhas do mesmo fundo/ativo somadas.
- Editados fora da lista: `resumo_etapa.py` (ramo novo), `settings.py` (campo novo). Montagem em `composicao_fontes.py` para nao conflitar com `composicao.py`.
- Nenhum leitor copiado foi modificado.

## Falta para a parte 2
CADASTRO (`cvm_cadastro`), IFDATA (`banco_indicador_trimestral`), datas ex (`data_ex_b3`) e mercados (`negociacao_b3_diaria`): leitores, entidades, repositorios, etapas.
