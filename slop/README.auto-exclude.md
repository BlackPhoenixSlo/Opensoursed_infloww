# slop/: Auto_Exclude past OF's 20k paging backstop

A Creator's Auto_Exclude list past OF's 20k paging backstop (`service/audiences.py` `ensure_exclude_list`,
`service/auto_exclude_decide.py`): every list-audience send still excludes its whole contact guard but syncs only
the ids its mirror lacks; stale members go in a background refresh, single-flight per Creator, one short
`broadcast_lock` hold per batch; a list under the backstop keeps the crawl + adds + removes on every send. The
harness, its knobs and its rules are in `README.md`; this file is only what this flow adds. The scenario's
docstring is its spec (drive, oracles, bypasses).

## Layout

| Path | Role |
|---|---|
| `seed/auto_exclude_guard.py` | `seed(w, creators, sizes, refused)`: per Creator with list size `sizes[aid]`, by SQL as a 1:1 send leaves them: `guard` fans (one outbound message 10-240 min ago and its `chats` row, inside the 6 h window), of them `refused` ids OF will not list, `stale` members (last message days ago), `open` fans (never messaged); `members` (the pre-made Auto_Exclude, exactly `n` ids) and `roster` (OF's fans) for the relay part. Deterministic (`w.rng("auto_exclude_guard")`); output in `w.data["auto_exclude_guard"]`. |
| `lib/auto_exclude_relay.py` | Its relay part: methods on `lib/automation_relay.py`'s offline walker (`WALKER_MIXINS`), each the walker's own answer unless the run wrote `auto-exclude.json` and armed it (`POST /__slop/auto-exclude/arm`), then only for the Creators it names: the fans roster, list pages after `page_ms`, adds / removes after `add_ms` (a `refuse` id is OF's 403), `send_mass_message` accepting after `accept_ms` with recipients = roster minus the excluded lists' members at accept. The Auto_Exclude is pre-made at arm. `server._load_client` answers the lane's client for an armed Creator (the composer and the automations share one OF account). Journal `auto-exclude.jsonl` (`read_journal`): `send`, `refresh_begin` / `refresh_end`, `add`, `hold`, `drop`; `POST /__slop/auto-exclude/drop` (OF's side drops members), `GET /__slop/auto-exclude` (counters), `/members?account_id=`. |
| `lib/auto_exclude_faults.py` | The check names and its faults (below), each patching `service/audiences.py`, `auto_exclude_decide.py` or `mass_queue_api.py` by module attribute inside the relay. |
| `scenarios/2026-11-03-auto-exclude-25k.py` | The scenario. |

## Scenarios

- `2026-11-03-auto-exclude-25k`: `agency_inbox` plus `seed/auto_exclude_guard`: big Creators (SCALES
  `auto_exclude_big_creators`) with a pre-made Auto_Exclude of `--ae_members=` (SCALES `auto_exclude_members`, past
  20k) and one control Creator (the last; `--ae_control_members=`, SCALES `auto_exclude_control_members`, under it).
  One cold send per Creator (`/__slop/run-automation`); then `--users` list-audience sends (`user_lists ["fans"]`,
  churn ids in `excluded_users`) enqueued through the real `POST /admin/automation/enqueue` at seeded offsets over
  the load window (`LOAD_S_PER_SEND` per send, at least `LOAD_S_MIN`), one driver per Creator claiming them (`/__slop/run-automation {claim: true}`). Racing them, composer
  blast pairs per Creator (`max(MANUAL_PAIRS_MIN, users // MANUAL_USERS_PER_PAIR)`), each the real `POST
  /api/of/v2/messages/queue` with the guard windows and `MANUAL_K` picks in `excluded_users`. Once the first big
  Creator's first refresh ended, `DROP_N` guard members are dropped on OF's side; after the load drains each big
  Creator settles (quiet, one send, its refresh awaited, OF's list read). Checks (`lib/auto_exclude_faults.py`):
  `NO_EXCLUDED_SENT`, `SEND_LATENCY` (budget: big Creators' enqueue -> OF accept p95 within `SEND_P95_S` and vs the
  control's), `CONVERGES`, `SINGLE_FLIGHT`, `EXTERNAL_READD`, `SMALL_EXACT`, `MANUAL_NO_EXCLUDED_SENT`; p95 vs the
  last green run over the control's enqueue -> accept, `POST /admin/automation/enqueue` and the composer's queue
  route, all in the scenario. Faults: `auto-exclude-refresh-blocks-send` (default; the send runs the refresh
  inline; targets `SEND_LATENCY`), `auto-exclude-remove-unlocked` (`NO_EXCLUDED_SENT`),
  `auto-exclude-refresh-skips-readd` (`EXTERNAL_READD`), `auto-exclude-readds-whole-guard` (`SEND_LATENCY`),
  `auto-exclude-manual-lock-early` (the composer releases `broadcast_lock` after the sync, pre-W24;
  `MANUAL_NO_EXCLUDED_SENT`). No UI.
