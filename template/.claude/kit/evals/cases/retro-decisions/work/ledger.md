# Ledger: EVAL-6

Base: none

- Ruling: amounts are stored as integer cents in orders.total and order_items.price, never as floats | why: float addition gave 0.30000000000000004 | cost if wrong: every money column and report would need a migration
- Ruling: named the test fixture tmp_orders | why: it is dropped after the test | cost if wrong: none
