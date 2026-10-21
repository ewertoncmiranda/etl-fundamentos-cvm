# FONTES-ETL-5 — IMPLEMENTADO (2026-10-20)

Leitor das taxas do Tesouro Direto (NTN-B), a partir do CSV aberto do Tesouro Transparente.

## Entregue
- **`app/adaptadores/tesouro/leitor_tesouro.py`:**
  - `ler_csv(conteudo, desde=None)`, função pura. Lida com o formato do arquivo: `;`, latin-1, vírgula decimal, ponto de milhar e datas dd/mm/aaaa. Linhas com tipo ou data quebrados são descartadas.
  - `ntnb_referencia(taxas, data_base=None)`: escolhe a NTN-B ("Tesouro IPCA+" ou "... com Juros Semestrais") com vencimento mais perto de 5 anos (DEC-FONTES-3), usando a taxa de compra.
- **`app/adaptadores/tesouro/fonte_tesouro.py`:** `FonteTesouro` no mesmo padrão da `FonteB3`. Usa `ClienteHttpCvm` (HEAD/ETag com retry) e `CacheDeArquivos`. A URL do recurso CKAN foi conferida em 2026-10-20: o servidor devolve ETag e Last-Modified.
- **`tests/adaptadores/test_tesouro.py`:** 5 casos.

## Evidência
- `pytest tests/adaptadores/test_tesouro.py`: 5 passaram. A suíte completa do ETL também passou.
- O arquivo real (cerca de 14,6 MB) gerou 177.434 linhas. A NTN-B de referência em 15/10/2026 é a **Tesouro IPCA+ com Juros Semestrais 15/08/2032, com juro real de 6,79% a.a.**

## Desvios
- Não grava no banco nem vira etapa. Ambos ficam para FONTES-ETL-8, depois da V45 com a tabela `titulo_publico_taxa`.
- O arquivo traz todo o histórico desde 2002; o parâmetro `desde` corta o que não interessa.
