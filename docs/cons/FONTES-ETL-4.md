# FONTES-ETL-4 — IMPLEMENTADO (2026-10-20)

## Entregue

- `app/adaptadores/cvm/fre_estendido.py` — `LeitorFreEstendido(conteudo, ano)` sobre `fre_cia_aberta_{ano}.zip`, reaproveitando `LeitorDePacoteCvm`. Vale só a última `Versao` por (`CNPJ_Companhia`, `Data_Referencia`).
  - `auditores()` (`fre_cia_aberta_auditor`): auditor, CNPJ, início e fim da contratação, justificativa de substituição e razão apresentada. "Não aplicável", "N/A", "Não se aplica", "Não houve substituição..." e equivalentes viram `None` (`texto_ou_vazio`).
  - `troca_recente_de_auditor(auditores, cnpj, hoje, meses=24)`: é troca quando um contrato começa dentro da janela e havia outro auditor (por CNPJ ou nome) contratado antes, ou quando a justificativa está preenchida.
  - `dividas_valor_mobiliario()` (`fre_cia_aberta_outro_valor_mobiliario`): tipo, identificação, emissão, vencimento, quantidade, valor, saldo devedor e conversível (`Sim`/`Não`/vazio vira `True`/`False`/`None`).
  - `vencimentos_por_ano(dividas, cnpj)`: saldo devedor somado por ano de vencimento.
  - `distribuicao_capital()` (`fre_cia_aberta_distribuicao_capital`): acionistas PF, PJ e institucionais, ações em circulação e os % ON, PN e total em circulação.
- `app/aplicacao/recompras.py` — funções puras sobre o BPP que o ETL já grava (`LinhaContabil` / `fato_contabil`):
  - `series_tesouraria(linhas)`: saldo por `dt_fim_exerc`, somando as contas **fixas** do grupo 2 cuja descrição normalizada é "acoes em tesouraria".
  - `recompra_executada(series)`: lista de `VariacaoTesouraria(dt_inicio, dt_fim, saldo_inicio, saldo_fim, variacao, recompra)`.
  - **Sinal:** o saldo é redutor do PL e vem negativo; `variacao = saldo_fim - saldo_inicio`. Com `variacao < 0` houve recompra (`recompra = -variacao`); com `variacao > 0`, houve cancelamento, alienação ou entrega a plano, e `recompra = 0`. O valor está em R$ ao custo, não em quantidade de ações.

## Evidência

- Conta confirmada no `dfp_cia_aberta_2025.zip` (BPP consolidado), baixado de dados.cvm.gov.br. "Ações em Tesouraria" é conta fixa em dois pontos do PL:

  | Plano | Contas |
  |---|---|
  | Geral | `2.03.02.05` e `2.03.04.09` (860 linhas cada; 262 e 82 negativas) |
  | Bancos | `2.07.01.02.05` e `2.07.01.04.09` |
  | Seguradoras | `2.08.02.05` e `2.08.04.09` |

  As contas não fixas com textos parecidos, como "Resultado na Alienação de Ações em Tesouraria", ficam de fora. 181 companhias têm saldo diferente de zero no último exercício. Aplicada a função à amostra, 440 companhias têm série e 69 tiveram recompra entre 2024 e 2025.
- Amostra real FRE 2025:

  | Tabela | Resultado |
  |---|---|
  | Auditores | 1.097 linhas, 698 companhias; 492 justificativas preenchidas depois da limpeza (707 sem o tratamento de prefixo) |
  | Troca nos últimos 24 meses (a 2026-10-20) | 216 companhias |
  | Dívidas | 2.726 linhas (o inventário cita 2.735; a diferença é a deduplicação por versão), todas com vencimento e saldo; 98 conversíveis |
  | Distribuição de capital | 700 linhas, todas com % total em circulação |

- Testes: `tests/adaptadores/test_fre_estendido.py` (7) e `tests/aplicacao/test_recompras.py` (3), com CSVs sintéticos em zip em memória. `python -m pytest -q tests` passa inteiro: 272 testes.

## Desvios

1. Nenhum arquivo proibido foi tocado. O leitor e as funções **não estão ligados** à carga (`executar_carga.py`/`main.py`) nem à persistência; isso fica para a tarefa da V45.
2. **Recompras vêm do BPP, não do FRE**, que não as publica (ver FONTES-ETL-1). A conta não tem código único: muda conforme o plano (2.03, 2.07 ou 2.08) e se divide entre reservas de capital e de lucros. Por isso a identificação é por conta fixa e descrição, e o saldo é a soma das contas.
3. A recompra é **líquida por período**: um cancelamento no mesmo trimestre esconde parte da recompra. A série deve ser de um só grupo (consolidado ou individual) e de uma só companhia.
4. "Não aplicável" também é tratado como vazio quando vem seguido de explicação ("Não aplicável, tendo em vista que..."). Em poucos casos isso pode descartar uma justificativa real; a troca ainda é detectada pela mudança de auditor.
5. `Razao_Apresentada` recebe a mesma limpeza da justificativa.
