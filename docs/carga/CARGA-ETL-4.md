# CARGA-ETL-4 — serviço como start único

**Status:** implementado; build Docker e verificação de saúde no compose não executados nesta sessão.

O `Dockerfile` inicia `python -m app.servidor`; `main.py` agora apenas compõe as etapas e encaminha ao servidor, sem argparse ou flags de carga. `AGENTS.md` documenta o endpoint como entrada única e proíbe comandos manuais por CLI. A versão opcional `ETL_VERSAO` é limitada aos 40 caracteres do schema.

**Validação local:** compileall, Ruff direcionado e suíte pytest completa passaram. Nenhuma carga real foi disparada.
