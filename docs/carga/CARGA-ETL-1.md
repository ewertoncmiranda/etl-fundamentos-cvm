# CARGA-ETL-1 — resumo confiável por etapa

**Status:** implementado.

`app/aplicacao/resumo_etapa.py` normaliza resultados de COTAHIST, DFP, TTM, IPE, DVA, eventos, liquidez, prontidão, qualidade de opções, conciliação e checagens nos estados e campos do contrato V44. COTAHIST falha quando opções retornam erro ou um ano processado grava zero candles; TTM/DVA emitem alerta quando processam sem gravar; ETag sem mudança vira `SEM_MUDANCA`. `ResultadoSeries` inclui contagem de candles por ano para aplicar essa regra sem inferência global.

**Testes:** `tests/aplicacao/test_resumo_etapa.py` cobre sucesso/sem mudança, ano sem candles, falha de opções, zero registros em TTM e exceção.
