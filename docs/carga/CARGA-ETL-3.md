# CARGA-ETL-3 — API HTTP interna

**Status:** implementado.

`app/servidor.py` fornece `POST /cargas` (202/409), `GET /cargas/{id}`, `GET /cargas?limite=&status=`, `GET /cargas/ultimas` e `GET /saude`. A execução é assíncrona; o token opcional `ETL_TOKEN` é comparado pelo cabeçalho `X-ETL-Token`. Erros de corpo/validação retornam 400, ausência 404 e indisponibilidade 503.

**Testes:** `tests/adaptadores/test_servidor_cargas.py` cobre autenticação, disparo, leitura e 404.
