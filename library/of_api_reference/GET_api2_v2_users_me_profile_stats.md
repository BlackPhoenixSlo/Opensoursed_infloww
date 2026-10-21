# GET /api2/v2/users/me/profile/stats

**Category:** users
**Total hits:** 13 across 1 session(s)

**Hit by context:**
- `{tier:paid}`: 13

## Used by Chatterly
- `service/of_client.py:1103`

## UI surfaces
_(no click correlation)_

## Pages observed
_(no page URLs)_

## Samples

| Kind | Session | Status | Size |
|---|---|---|---:|
| first_success | `01KS860BJSP7J2223EM1W449VP` | 200 | 4575 |
| largest | `01KS860BJSP7J2223EM1W449VP` | 200 | 4575 |
| latest_distinct_shape | `01KS860BJSP7J2223EM1W449VP` | 200 | 3057 |
| smallest | `01KS860BJSP7J2223EM1W449VP` | 200 | 633 |

## Response shape
- Always present (≥99% of 13 hits): `hasStats`, `isAvailable`
- Sometimes: `chart`, `topCountries`, `topDurationUsers`, `total`
