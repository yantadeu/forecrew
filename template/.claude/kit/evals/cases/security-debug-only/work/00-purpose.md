# EVAL-8 Trace payment requests

Lane: Light

## Purpose
Support needs to trace payment requests, and developers want to see the loaded config locally.

## Acceptance criteria
- AC-001: Every POST /payments request is logged at info level so support can trace it.
- AC-002: With APP_DEBUG=1, GET /debug/config returns the loaded configuration.

## Decisions from the interview

## Clarifications

## Out of scope
Log shipping.
