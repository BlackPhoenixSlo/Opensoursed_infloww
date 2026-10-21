# GET /api2/v2/payouts/balances

**Category:** other
**Total hits:** 7 across 1 session(s)

**Hit by context:**
- `{tier:paid}`: 7

## Used by Chatterly
- `service/of_client.py:705`

## UI surfaces
_(no click correlation)_

## Pages observed
_(no page URLs)_

## Samples

| Kind | Session | Status | Size |
|---|---|---|---:|
| first_success | `01KS860BJSP7J2223EM1W449VP` | 200 | 308 |
| largest | `01KS860BJSP7J2223EM1W449VP` | 200 | 308 |
| latest_distinct_shape | `01KS860BJSP7J2223EM1W449VP` | 200 | 308 |
| smallest | `01KS860BJSP7J2223EM1W449VP` | 200 | 308 |

## Response shape
- Always present (≥99% of 7 hits): `currency`, `manualPayoutPendingDays`, `maxPayoutSumm`, `minPayoutSumm`, `payoutAvailable`, `payoutPending`, `withdrawalPeriod`, `withdrawalPeriodOptions`
- Sometimes: _(none)_
