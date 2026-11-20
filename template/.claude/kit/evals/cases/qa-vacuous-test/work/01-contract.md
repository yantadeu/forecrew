Status: DONE

## The request in one sentence
Apply 10% off to orders of 100 or more.

## How it is proven
- AC-001: discount(100) == 90, unit test.
- AC-002: discount(99.99) == 99.99, unit test.

## What stays out
Coupons.

## Where it touches
pricing.py

## What can fail silently
- The boundary at exactly 100 uses > instead of >=, and no test checks 100 itself.

## Sources read
- none registered
