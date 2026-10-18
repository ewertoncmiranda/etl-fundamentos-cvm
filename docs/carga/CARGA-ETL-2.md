# CARGA-ETL-2 — orquestrador e registro

**Status:** implementado; integração ao MySQL migrado depende de V44 disponível no ambiente.

`app/aplicacao/executar_carga.py` centraliza `ROTINA`, `COMPLETA` e `PARCIAL`, catálogo e isolamento das etapas. `RepositorioCargaSql` persiste execução/etapas, mantém lock `GET_LOCK`, conta estados finais e recupera execuções órfãs no início do serviço. O `ContextVar` de carga associa registros `etl_execucao` ao ID pai. A migration continua sob responsabilidade da Infra; o serviço recusa iniciar sem o schema V44.

**Testes:** `tests/aplicacao/test_executar_carga.py` cobre validação, ordem/janela, disparo aceito e conflito concorrente. Não foi feita carga produtiva nem atualização manual do banco.
