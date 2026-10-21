# GET /api2/v2/payouts/transactions

**Category:** payments
**Total hits:** 14 across 1 session(s)

**Hit by context:**
- `{tier:paid}`: 14

## Used by Chatterly
- `service/server.py:576`
- `service/of_client.py:793`
- `service/transaction_ingest.py:2`
- `service/db/migrations/versions/20260522_1208_phase_f_transaction_ingest.py:8`

## UI surfaces
_(no click correlation)_

## Pages observed
_(no page URLs)_

## Samples

| Kind | Session | Status | Size |
|---|---|---|---:|
| first_success | `01KS860BJSP7J2223EM1W449VP` | 200 | 3177 |
| largest | `01KS860BJSP7J2223EM1W449VP` | 200 | 3177 |
| latest_distinct_shape | `01KS860BJSP7J2223EM1W449VP` | 200 | 47 |
| smallest | `01KS860BJSP7J2223EM1W449VP` | 200 | 47 |

## Response shape
- Always present (≥99% of 14 hits): `hasMore`, `list`, `marker`
- Sometimes: `nextMarker`
