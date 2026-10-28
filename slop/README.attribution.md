# slop/: Sales attribution (tips, PPV)

Who Employee reports and Sales records credit for a fan's TIP and PPV, in the slop harness. The harness, its knobs
and its rules are in `README.md`; this file is only what this flow adds. Its files: `lib/attribution_relay.py`
(OnlyFans' payouts ledger; module docstring), `lib/attribution_faults.py` (faults and the check names they target),
`seed/sales_touches.py`, `scenarios/2026-10-27-sales-attribution-tips-ppv.py` (its docstring is the spec).
`actors/focus.Chatter.reply(price=)` sends a PPV through the real send route.

## Layout

| Path | Role |
|---|---|
| `lib/attribution_relay` | OF's `/payouts/transactions` (what `transaction_ingest.run_one_tick` pages) read from `<tmp>/of-ledger.jsonl`, appended while the run goes on; `GET /__slop/ledger` counts the pages served. No file: the read fails as before |
| `seed/sales_touches` | `seed()`: outbound rows in the past as the product writes them (a human 1:1 send, an Automation send, a mass send with its `mass_runs` row); `employees()`: each chatter's mirror Employee (read, or written when missing) and the Automation sentinel (written as migration 0011 does when the DB lacks it) |

## Scenarios

- `2026-10-27-sales-attribution-tips-ppv`: `agency_inbox` plus `--users` chatters (own logins, 2 Creators each).
  Sales settings go through the real route: Converters / Converters, the Converters window 1 h
  (`attribution.converters_window_seconds`), Time tracking off. In each episode the Creator's chatters reply,
  then the fan pays: a ledger-only chat tip, a WS tip frame (its ledger twin comes later), a WS PPV unlock, or a
  ledger "Payment for message". Sometimes another chatter replies after the PPV or after the payment. Ledger
  scans (`POST /admin/ingest/transactions/{aid}/run`) and the owner's report reads run alongside. Specials on
  Creator 0 use SQL touches in the past: the 1 h window +-60 s, the 3 h 30 min window +-60 s, and Automation or
  mass after (or instead of) a human; one live special has A send a PPV and B reply before the unlock. Credit
  is read through `GET /admin/stats/sales-records` and `/admin/stats/per-employee`, then re-read after each
  settings change: the window at 3 h 30 min (read back by `GET /admin/settings/sales`), fee excluded, Message
  sender, Shift with Time tracking off, and a change saved effective now. With UI, the Sales settings page saves
  3 h 30 min in its hours and minutes fields (screenshots `trigger-sales-converters-window`,
  `settled-sales-converters-window-saved`). Faults: `converters-first-chatter` (default),
  `converters-counts-automation`, `converters-window-ignored`, `chatter-send-unstamped`.

## Rules the run asserts (Infloww's Converters, 2026-10-27)

- Every kind (message PPV, WS chat tip, ledger-only tip, post purchase or tip): the last human chatter's 1:1 send
  to the fan at or before the sale, within the window, else Unattributed (`tx_rollup.converter_lookback` stores
  the candidate, `sales_attribution.credit` applies the window). Automation's sends and mass sends are never a
  touch. A PPV's sender is not credited for being its sender.
- Message sender: a sale linked to a message credits that message's sender (a WS tip is linked to the fan's own
  message: nobody). A ledger-only tip has no message, so it is Posts and tips and keeps Converters.
- Shift schedule with Time tracking off still falls back to Converters, with the fallback line (not this flow's
  change).

## Declared bypasses (beyond README.md's)

- The ledger is a file, and a scan runs only when POSTed (the supervisor is off under `CHATTERLY_TEST_MODE`).
- Past touches (hours ago), Automation and mass sends are SQL rows in the product's shape. Mirror Employees and the
  Automation sentinel are SQL rows written before any send. A fresh `create_all` DB has no Automation row,
  because only alembic migration 0011 writes it.
- A WS tip's ledger twin is appended only after the pump is quiet. WS-unlocked PPVs get no ledger twin
  (`_ENABLE_PPV_FINGERPRINT` is False, so a twin would count twice).
- The send route's p95 budget (1500 ms) is a stress budget at ~100 sends/s. `chatter-crowd` owns the
  realistic 750 ms.
