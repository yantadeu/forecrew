Status: DONE

## The request in one sentence
Order totals are exact.
## How it is proven
- AC-001: unit test sums three items of 10 cents and expects 30.
## What stays out
Currency conversion.
## Where it touches
orders.py
## What can fail silently
- a float sneaks back through a new column
## Sources read
no prior work
