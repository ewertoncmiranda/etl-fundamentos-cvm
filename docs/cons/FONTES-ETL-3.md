# FONTES-ETL-3 — IMPLEMENTADO (2026-10-20)

## Entregue
- `app/adaptadores/cvm/vlmo.py`: `ler_vlmo(conteudo, ano)` lê `vlmo_cia_aberta_con_{ano}.csv` e o índice `vlmo_cia_aberta_{ano}.csv` (Data_Entrega por CNPJ, Data_Referencia e Versao) via `LeitorDePacoteCvm` (latin-1, `;`). Mantém só a última versão por (CNPJ, Data_Referencia). CNPJ só com dígitos.
- Dataclass `NegociacaoAdministrador` com as colunas do inventário mais `data_entrega`; `Volume`/`Preco_Unitario` zerados viram `None`.
- Função pura `compra_liquida(negociacoes, cnpj, desde, ate)`: só Compra à vista, Venda à vista e Compra à termo com Tipo_Ativo Ações ou Units; devolve `{Tipo_Cargo: CompraLiquida(quantidade, volume)}` (venda negativa; volume `None` quando nenhuma linha do cargo tem volume).
- `tests/adaptadores/test_vlmo.py`: versões, Data_Entrega, acentos latin-1, volume zero, filtros e agrupamento por cargo.

## Evidência
- `python -m pytest -q tests`: suíte completa verde.
- Zip real 2025: 55.926 linhas após manter a última versão (de 63.195), todas com Data_Entrega; 13.162 decisões de mercado (Venda à vista 6.743, Compra à vista 6.186, Compra à termo 233), 12.691 com volume > 0.

## Desvios
- O período de `compra_liquida` usa `Data_Movimentacao` (cai para `Data_Referencia` se vazia), intervalo inclusivo.
- `Venda à termo` (66 linhas) não entra, conforme a regra do inventário.
- O leitor recebe os bytes do zip; download e cache (`cliente_http`/`cache_local`) ficam para quem orquestrar a carga.
