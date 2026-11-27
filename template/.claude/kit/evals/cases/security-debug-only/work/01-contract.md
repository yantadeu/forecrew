Status: DONE

## The request in one sentence
Log payment requests and add a local-only config endpoint.

## How it is proven
- AC-001: a request to /payments produces one info log line, unit test.
- AC-002: /debug/config answers 200 with APP_DEBUG=1 and 404 without it, unit test.

## What stays out
Log shipping.

## Where it touches
app.py

## What can fail silently
- The debug route registered in production.

## Sources read
- none registered
