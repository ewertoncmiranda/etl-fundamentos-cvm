# AGENTS.md — etl-fundamentos-cvm

Instruções para agentes de código (Claude, Codex, outros). O plano e o backlog estão em `SPEC.md`; a coordenação entre repositórios, no hub `infra-b3-ecossytem/SPEC.md` (seção 1A).

## Start único deste repositório — serviço CARGA

O container sobe `python -m app.servidor` como serviço interno do compose. `POST /cargas` aceita `ROTINA`, `COMPLETA` ou `PARCIAL`; a rotina da manhã e o gestor são clientes HTTP. O painel fala somente com o gestor. Nenhum consumidor chama o ETL por CLI nem acessa o banco diretamente. A liquidez continua como etapa da execução controlada e o histórico inicial se preenche sozinho.

## Regra: start único, sem ferramentas de linha de comando não pedidas (DEC-AGT-1, 2026-10-10)

Decisão do usuário. Vale para qualquer agente (Claude, Codex, outros) e prevalece sobre planos antigos dos SPECs.

1. **Toda feature roda a partir do serviço HTTP do compose.** `python -m app.servidor` é o entrypoint do container, não um comando manual de operação. Nada de "agora rode `python -m ...`" ou "use uma flag" para o usuário fazer à mão.
2. **Não criar comando, flag, subcomando, script avulso ou `__main__` que ninguém pediu** — inclusive para inspeção, diagnóstico, conferência ou backfill. Conferir é papel de teste ou de tela/endpoint de leitura que já existe.
3. **Feature nova entra numa etapa que o start único já executa** (de preferência dentro de uma etapa existente). Precisa de histórico na primeira execução? A própria etapa preenche sozinha quando a tabela está vazia — sem comando de backfill.
4. Na dúvida, perguntar antes de expor um comando.

### Casos em que manter um ponto de entrada é necessário

| Caso | Por quê | Exemplo |
|---|---|---|
| O próprio start único do serviço | É o que sobe/roda o serviço | `python -m app.servidor` no container do compose |
| Etapa chamada pelo orquestrador único (rotina da manhã) | O orquestrador isola cada etapa; não é para uso manual | `infra/scripts/cargas-etl.ps1` chama `POST /cargas` e acompanha a execução |
| Migração de schema | Roda no start da stack; Flyway é o único dono do schema | serviço `db-migrate` |
| Registro das tarefas agendadas e backup | O agendador do Windows precisa de um alvo | `registrar-rotinas.ps1`, `backup-mysql.ps1` |
| Recuperação histórica que já existia, quando o usuário pedir | Exceção herdada; feature nova se recupera sozinha no primeiro start | `backfill-historico.ps1` |
| Passo manual único com internet, documentado | Não pode rodar na rede interna | perfil `ia-pull` (baixar modelo do Ollama) |

Fora desses casos, o ponto de entrada deve ser removido ou incorporado ao start único.
