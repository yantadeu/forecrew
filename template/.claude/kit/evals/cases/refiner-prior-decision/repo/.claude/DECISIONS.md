# Decisions

## money-in-cents
- **Tags**: data
- **Decision**: every amount is stored as integer cents (orders.total, order_items.price); never floats or decimals in reais.
- **Why**: float addition gave totals off by a cent (0.30000000000000004).
- **Cost if wrong**: every money column and report needs a migration; rounding errors reach invoices.
- **From**: EVAL-6, 2026-11-20.
