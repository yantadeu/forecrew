Status: DONE

## What changed
- app.py: create_payment() logs the request headers at info (AC-001).
- app.py: /debug/config, registered only when APP_DEBUG=1 (AC-002). deploy/prod.env sets APP_DEBUG=0.

## Build and tests
pytest: 3 passed.

## Not covered by the contract
Nothing.
