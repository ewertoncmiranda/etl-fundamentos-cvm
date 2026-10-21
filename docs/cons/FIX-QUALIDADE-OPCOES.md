# FIX-QUALIDADE-OPCOES — IMPLEMENTADO

## Entregue

A consulta de cadeias por ativo em app/aplicacao/qualidade_opcoes.py agora declara COUNT(*) AS total. A ordenação ORDER BY total DESC, ativo_objeto permanece, com desempate determinístico pelo ativo. Corrige o erro MySQL1054 registrado na carga0e0a0b70-a12e-48d5-a2c9-8bcbb44b1691.

A etapa QUALIDADE_OPCOES continua apenas avaliando opções já armazenadas e registrando suas métricas. Não importa opções, não altera seus registros e não exige migration. Nenhum comando ou flag novo.

## Evidência

O novo teste executa a consulta gerada por avaliar em SQLite na memória, com nove registros sintéticos; não é uma cópia do SQL nem um fake que aceita qualquer consulta agrupada. Antes da correção: sqlite3.OperationalError: no such column: total. Depois: teste passou. Verifica contagem, ordenação decrescente, desempate alfabético, filtro de pregão e ativo não nulo, vencimentos/strikes somente válidos e strikes ausentes.

32 testes passaram: qualidade, execução controlada de cargas, séries históricas de opções, identidade de opções e servidor HTTP. Sem MySQL, rede externa ou alterações nos containers.

## Desvios e publicação

Uma branch feature-fix-qualidade-opcoes e vários commits. Após merge e publicação da imagem ETL corrigida, a etapa pode ser reexecutada no painel. Não foi disparada nova carga nem atualizada a stack nesta correção.
