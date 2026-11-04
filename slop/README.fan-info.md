# slop/: The fan-info sweep

The fan-info sweep (`automations.gen_info`, Automation 02, its persist plan the pure
`automations/gen_info_plan.py` `plan_persist`) at volume: every Creator's rule run at once by the owner's Run now,
every profiled fan checked against his seed. The harness, its knobs and its rules are in `README.md`; this file is
only what this flow adds. The scenario's docstring is its spec (flow, bypasses).

## Layout

| Path | Role |
|---|---|
| `seed/fan_info_history.py` | `seed(w, creators, per_creator)`: per Creator `per_creator` fans by SQL as the WS pump and the chat scrape leave them (a `fans` row, 10-16 inbound lines among a few outbound, the `chats` row; `spend_cents` 0), past gen_info's 8-message gate. Three roles by index: `manual` (an operator-pinned `language`, `language_source='manual'`, the extract detecting another), `keep` (a month-old `fan_profiles` row whose extract comes back empty), `plain` (never profiled). Each extract carries the fan's own marker; display names `fi-<creator>-<fan>` are unique per Creator x fan (`display_name`), the fake's only handle on which fan. |
| `lib/fan_info_relay.py` | Its relay part (no `OF` class). DeepSeek: an `ANSWERS` entry on `lib/automation_relay.py`'s loopback fake answering gen_info's profile prompt with the named fan's extract from `$DEMO_SHOTS_TMP/fan-info-extracts.json` (`write_extracts`), counted `deepseek:gen_info`; any other gen_info prompt is recorded and passed on. OF: gen_info's drawer push (`set_fan_custom_name` / `set_fan_note`) kept on the lane's client (`WALKER_MIXINS`). Inert without the file. `GET /__slop/fan-info/calls`: every prompt and push, in arrival order. |
| `lib/fan_info_faults.py` | The check names and its faults (below), each patching a `gen_info_plan` attribute (SystemExit when it is gone). |
| `scenarios/2026-11-02-fan-info-sweep.py` | The scenario. |

## Scenarios

- `2026-11-02-fan-info-sweep`: `agency_inbox` plus `seed/fan_info_history` (`--fans=` per Creator, SCALES
  `fan_info_fans`), the Agency's dummy DeepSeek key through `PUT /admin/my-llm-keys`, one gen_info rule per Creator
  (every 24 h, `limit` 200, its last job an hour ago) by SQL; the real supervisor runs (`SLOP_SUPERVISOR=1`).
  `--users` owner tabs open fans' drawers (`GET /admin/fans/{creator}/{fan}`, think time `THINK_S`) from before the
  press until every run is done; the owner presses Run now on every rule at once (`POST
  /admin/automation-rules/{id}/run-now`); each Creator's `automation_runs` row is awaited; then every seeded fan's
  drawer is read once more. Checks (`lib/fan_info_faults.py`): `PIN` (a manual fan keeps his language and source,
  DB and drawer), `KEEP` (a keep fan's stored nickname / short_bio / bullet_points / original_name survive an empty
  extract), `OWN` (every fan's facts carry his own marker, DB and drawer agree, one Fan note push per fan naming
  only his marker), `COUNTS` (one ok run per Creator, its stats vs the SQL oracle, one model call per seeded fan,
  rows written == generated == done `grok_calls`); budgets (Run now -> run done p95 per Creator, drawer read p95,
  both vs the last green run) are the scenario's. `SLOP_LIVE=1`: every check SKIPs. Faults:
  `gen-info-manual-language-overwritten` (default; `MANUAL_LANGUAGE_SOURCES` emptied; targets `PIN`),
  `gen-info-facts-cross-fan` (`plan_persist` reuses the previous fan's facts; `OWN`). No UI.
