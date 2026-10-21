# FONTES-ETL-7 — IMPLEMENTADO (2026-10-20)

## Entregue
- `app/adaptadores/cvm/cda.py`: `ler_cda_acoes(conteudo, AAAAMM)` gera em streaming `PosicaoFundoAcao` só de `cda_fi_BLC_4_{AAAAMM}.csv` com `TP_APLIC == "Ações"`, juntando `pl_fundo` de `cda_fi_PL_{AAAAMM}.csv`. CONFID e demais blocos nunca são abertos. CNPJ só com dígitos; símbolo em maiúsculas.
- Função pura `fluxo_por_ativo(atual, anterior)`: por símbolo, número de fundos, quantidade total, variação da quantidade e fundos que entraram/saíram.
- `tests/adaptadores/test_cda.py`: filtro de TP_APLIC, PL ausente, CONFID presente no zip, fluxo com entradas e saídas.
- FII (DEC-FONTES-2) fora.

## Evidência
- `python -m pytest -q tests`: suíte completa verde.
- Zip real 09/2026: 11.902 posições em ações (bate com o inventário), 733 fundos, 282 símbolos, todas com PL; leitura em ~2,5 s. Maior presença: VALE3 (249 fundos), PETR4 (234).

## Desvios
- Linhas de ações sem `CD_ATIVO` ou `DT_COMPTC` válidos são descartadas (nenhuma no zip real).
- Posições do mesmo fundo e símbolo em mais de uma linha são somadas no fluxo.
- O leitor recebe os bytes do zip; download e cache ficam para quem orquestrar a carga.
