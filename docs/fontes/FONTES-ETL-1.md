# FONTES-ETL-1 — IMPLEMENTADO (2026-10-20)

Inventário dos pacotes abertos da CVM, feito com os arquivos reais baixados em 2026-10-20 de `https://dados.cvm.gov.br/dados/`. Todos são CSV `;` em latin-1. Este documento fecha as colunas da V45 (CONS-INFRA-1).

## Resumo e impacto no plano

| Conjunto | Arquivo | Tamanho | Serve para | Situação |
|---|---|---|---|---|
| Cadastro | `CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv` | 1,5 MB, 2.678 cias | Situação, setor, auditor | **OK** |
| VLMO | `CIA_ABERTA/DOC/VLMO/DADOS/vlmo_cia_aberta_{ano}.zip` | 0,8 MB/ano | Negociação de administradores e controladores | **OK** (`_con_` tem as movimentações) |
| FRE | `CIA_ABERTA/DOC/FRE/DADOS/fre_cia_aberta_{ano}.zip` | 8,5 MB/ano | Auditor (histórico e substituição), dívida em valores mobiliários, distribuição do capital | **Parcial**: ver desvios |
| CDA | `FI/DOC/CDA/DADOS/cda_fi_{AAAAMM}.zip` | 13 MB/mês | Posição de fundos em ações | **OK** (bloco 4) |
| Informe FII | `FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano}.zip` | 1,5 MB/ano | FII | OK, depende de DEC-FONTES-2 |

### Desvios em relação ao plano (decidir antes da V45)

1. **O FRE aberto não tem tabela de recompras nem de política de dividendos.** As 40 tabelas do pacote de 2025 não trazem programa de recompra, ações em tesouraria nem política de distribuição.
   - **Recompras:** a fonte confiável é o **BPP da DFP/ITR, que o ETL já carrega**, na conta "Ações em Tesouraria", dentro do patrimônio líquido. A variação entre trimestres mostra a recompra executada. Proposta: a FONTES-ETL-4 passa a calcular isso dos dados já gravados, e a tabela `cvm_recompra` sai da V45.
   - **VLMO não serve para recompras:** as linhas com `Tipo_Cargo` vazio (262) são saldos e movimentos da "Companhia/Controladora" sem padrão de tesouraria. Só 126 linhas citam tesouraria ou recompra na descrição livre.
   - **Política de dividendos:** não é estruturada. A sustentabilidade do dividendo usa payout e fluxo de caixa da DFP, que já existem. A tabela `cvm_politica_dividendos` sai da V45.
2. **Dívida:** o FRE tem `outro_valor_mobiliario` (debêntures, notas comerciais, CRI e outros), com vencimento e `Saldo_Devedor`. Cobre só dívida em valores mobiliários, não empréstimos bancários. Para o total, continua valendo o BPP da DFP. `cvm_divida_vencimento` é mantida, restrita a valores mobiliários.
3. **Auditor:** o FRE tem `fre_cia_aberta_auditor` com datas de contratação e o campo `Justificativa_Substituicao`, melhor que o par `CNPJ_AUDITOR`/`AUDITOR` do cadastro, que só traz o atual. Na maioria das linhas a justificativa vem como "Não aplicável", "N/A" ou equivalente; é preciso tratar como vazio.

## Cadastro — `cad_cia_aberta.csv`

Colunas úteis: `CNPJ_CIA`, `DENOM_SOCIAL`, `DENOM_COMERC`, `CD_CVM`, `SIT` (ATIVO 756, CANCELADA 1.914, "SUSPENSO(A) - DECISÃO ADM" 8), `DT_INI_SIT`, `DT_CANCEL`, `MOTIVO_CANCEL`, `SETOR_ATIV` (texto livre da CVM; por exemplo, "Energia Elétrica" tem 117), `TP_MERC`, `CATEG_REG`, `SIT_EMISSOR`, `DT_INI_SIT_EMISSOR`, `CONTROLE_ACIONARIO`, `CNPJ_AUDITOR`, `AUDITOR`.

É um arquivo único, sem histórico; a troca de auditor vem do FRE.

## VLMO — `vlmo_cia_aberta_con_{ano}.csv` (63.195 linhas em 2025)

Colunas: `CNPJ_Companhia`, `Nome_Companhia`, `Data_Referencia` (mês), `Versao`, `Tipo_Empresa` (Companhia, Controladora, Controlada), `Empresa`, `Tipo_Cargo`, `Tipo_Movimentacao`, `Descricao_Movimentacao`, `Tipo_Operacao` (Crédito, Débito), `Tipo_Ativo`, `Caracteristica_Valor_Mobiliario`, `Intermediario`, `Data_Movimentacao`, `Quantidade`, `Preco_Unitario`, `Volume`.

| Coluna | Valores e contagem |
|---|---|
| `Tipo_Cargo` | Conselho de Administração ou Vinculado 21.597; Diretor ou Vinculado 17.799; Controlador ou Vinculado 17.079; Conselho Fiscal 4.214; Órgão Estatutário 2.244; vazio 262 |
| `Tipo_Movimentacao` | Saldo Inicial 36.795; Venda à vista 8.098; Compra à vista 7.085; Outras Entradas; empréstimo (locador); Desdobramento/bonificação; Posse; Ações de plano de remuneração; Compra a termo |
| `Tipo_Ativo` | Ações 47.889; opções; debêntures; Units 2.353; e outros |

**Regras para o leitor (FONTES-ETL-3):**
- Considerar só `Compra à vista`, `Venda à vista` e `Compra à termo`, com `Tipo_Ativo` em Ações ou Units.
- **Ignorar** saldo inicial, empréstimo, plano de remuneração, posse, desligamento e bonificação: não são decisão de mercado.
- `Volume` e `Preco_Unitario` vêm zerados em parte das linhas (só 19.866 têm volume > 0). Quantidade é a medida principal; volume é complementar.
- A versão mais recente prevalece por (`CNPJ_Companhia`, `Data_Referencia`).
- O arquivo índice `vlmo_cia_aberta_{ano}.csv` traz a `Data_Entrega`, que é a data point-in-time do sinal.

## FRE — tabelas úteis (pacote 2025, 40 arquivos)

| Tabela | Linhas | Colunas usadas |
|---|---|---|
| `fre_cia_aberta_auditor` | 1.097 | `CNPJ_Companhia`, `Data_Referencia`, `Versao`, `Auditor`, `CNPJ_Auditor`, `Data_Inicio_Contratacao`, `Data_Fim_Contratacao`, `Justificativa_Substituicao`, `Razao_Apresentada` |
| `fre_cia_aberta_outro_valor_mobiliario` | 2.735 | `Valor_Mobiliario` (Debêntures 2.106, Nota Comercial 258, CRI 232 e outros), `Identificacao_Valor_Mobiliario`, `Data_Emissao`, `Data_Vencimento`, `Quantidade`, `Valor`, `Saldo_Devedor`, `Conversibilidade`, `Resgatavel` |
| `fre_cia_aberta_distribuicao_capital` | 700 | Acionistas PF/PJ/institucionais e ações em circulação (free float). Complementa o `_free_float_do_fre` existente |
| `fre_cia_aberta_capital_social` | 2.402 | Já usada pelo ETL |
| `fre_cia_aberta_acionista_significativo` | — | Já usada pelo ETL |

Outras tabelas do pacote, fora do escopo: remuneração, empregados, comitês, partes relacionadas, posição acionária e diversidade.

## CDA — `cda_fi_BLC_4_{AAAAMM}.csv` (129.356 linhas em 09/2026)

Colunas: `TP_FUNDO_CLASSE`, `CNPJ_FUNDO_CLASSE`, `DENOM_SOCIAL`, `DT_COMPTC`, `TP_APLIC`, `TP_ATIVO`, `EMISSOR_LIGADO`, `TP_NEGOC`, `QT_VENDA_NEGOC`, `VL_VENDA_NEGOC`, `QT_AQUIS_NEGOC`, `VL_AQUIS_NEGOC`, `QT_POS_FINAL`, `VL_MERC_POS_FINAL`, `VL_CUSTO_POS_FINAL`, `DT_CONFID_APLIC`, `CD_ATIVO` (ticker, por exemplo ITUB3), `DS_ATIVO`, `CD_ISIN`, `DT_INI_VIGENCIA`, `DT_FIM_VIGENCIA`.

**Filtro:** manter `TP_APLIC = "Ações"` (11.902 linhas). Descartar debêntures (107 mil linhas), empréstimo de ações e opções. O ticker vem pronto em `CD_ATIVO` e o ISIN permite conferir. `cda_fi_PL` traz o PL de cada fundo, que dá a participação da ação na carteira. Posições confidenciais (`*_CONFID_*`) ficam de fora.

## Informe mensal FII (13.678 linhas/ano em cada tabela)

- `inf_mensal_fii_geral`: `CNPJ_Fundo_Classe`, `Data_Referencia`, `Versao`, `Data_Entrega`, `Nome_Fundo_Classe`, `Codigo_ISIN`, `Quantidade_Cotas_Emitidas`, `Mandato`, `Segmento_Atuacao`, `Tipo_Gestao`, `Mercado_Negociacao_Bolsa`.
- `inf_mensal_fii_complemento`: número de cotistas por tipo.
- `inf_mensal_fii_ativo_passivo`: composição do ativo e do passivo.

Usar só se DEC-FONTES-2 incluir FIIs.

## Colunas finais para a V45 (CONS-INFRA-1)

- **`cvm_cadastro`**: cnpj PK, codigo_cvm, denominacao, situacao, data_situacao, data_cancelamento, motivo_cancelamento, setor_cvm, situacao_emissor, controle_acionario, cnpj_auditor, auditor, atualizado_em.
- **`cvm_auditor`** (do FRE; substitui o histórico de auditor no cadastro): cnpj, data_referencia, versao, cnpj_auditor, auditor, data_inicio, data_fim, justificativa_substituicao. Chave única (cnpj, data_referencia, cnpj_auditor, data_inicio).
- **`cvm_negociacao_administrador`**: cnpj, data_referencia, versao, data_entrega, tipo_empresa, tipo_cargo, tipo_movimentacao, tipo_operacao, tipo_ativo, caracteristica, data_movimentacao, quantidade, preco_unitario, volume.
- **`cvm_divida_valor_mobiliario`** (renomeada de `cvm_divida_vencimento`): cnpj, data_referencia, versao, tipo, identificacao, data_emissao, data_vencimento, quantidade, valor, saldo_devedor, conversivel.
- **`fundo_posicao_acao`**: competencia, cnpj_fundo, simbolo, isin, quantidade, valor_mercado, pl_fundo. Chave única (competencia, cnpj_fundo, simbolo).
- **`fii_informe_mensal`**: só com DEC-FONTES-2.
- **Saem da V45:** `cvm_recompra` e `cvm_politica_dividendos` (desvio 1).
