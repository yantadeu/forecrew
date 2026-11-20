# EVAL-2 Monthly totals ignore refunds

Lane: Light

## Purpose
Refunds stop inflating the monthly totals.

## Acceptance criteria
- AC-001: A transaction with a negative amount reduces the merchant's monthly total.
- AC-002: A merchant whose refunds equal its sales appears with a total of 0, not omitted.

## Decisions from the interview
- Refunds are transactions with a negative amount; there is no separate refund type.

## Clarifications

## Out of scope
- Currency conversion.
