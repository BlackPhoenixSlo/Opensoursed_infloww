# slop/: Scheduled send once

A chatter's scheduled DM goes to OnlyFans once, never twice: a send OF may have taken is never retried, whether
its answer never came or the relay died after OF took it (`run_decide.outcome`, the boot heal's
`one_shot_family`; parked `error`, "may have sent"). The harness, its knobs and its rules are in `README.md`; this
file is only what this flow adds. The scenario's docstring is its spec (phases, the open owner question,
bypasses).

## Layout

| Path | Role |
|---|---|
| `lib/send_once_relay.py` | OnlyFans' side of a 1:1 send, only while a scenario writes `$DEMO_SHOTS_TMP/of-send-once.json` (`{fans: {"<account>:<fan>": "stall" \| "hang" \| "refuse_once"}, stall_s, hang_s}`, read on every send): `_OfflineOF.send_message` answers the first time OF sees a text by its fan's behaviour (`stall`: OF takes it, then curl's ReadTimeout after `stall_s`; `hang`: OF takes it, the call blocks `hang_s`; `refuse_once`: the proxy refuses the CONNECT, OF never saw it), any other fan as OF does. OF's record `of-send-once.jsonl` (`refused`, `accepted`, `returned` lines, one O_APPEND write each, so it outlives a SIGKILL); `read_journal(tmp)` reads it. Raised errors start `SLOP_MARK`. |
| `lib/send_once_faults.py` | The check names and the fault `send-once-retries-after-accept` (`run_decide.ONE_SHOT_KINDS` emptied: the pre-fix lane). |
| `scenarios/2026-10-31-scheduled-send-once.py` | The scenario. |

## Scenarios

- `2026-10-31-scheduled-send-once`: `agency_inbox`; the real supervisor runs (`SLOP_SUPERVISOR=1`, its boot heal
  is the orphan path) and `/__slop/automation-tick` adds passes. `--users` chatters schedule due-now DMs through
  the composer route (`POST /api/of/v2/scheduled-sends`, X-Account-Id), round-robin over the Creators' fans, and
  each keeps the chat's ghost-bubble list open (`GET /api/of/v2/scheduled-sends?fan_id=`, every 2 s). Phase A,
  per Creator: 2 stall, 1 refuse_once, 1 plain. Phase B: 2 hang per Creator; once every run slot holds a send OF
  took and has not answered, the relay is SIGKILLed, OF answers normally, the relay restarts on the same DB and
  the boot heal's `reconciled_orphans` line is awaited. Checks: `ONCE` ("OF holds exactly 1 message per job"),
  `SETTLED`, `PARKED`, `REFUSED` (`lib/send_once_faults.py`), and the scenario's own "SIGKILL landed with every
  running send taken by OF and unanswered (>= one per run slot)"; budgets: `POST` / `GET
  /api/of/v2/scheduled-sends` p95 and schedule -> OF took it p95 (plain, phase A), all in the scenario, also vs
  the last green run. Fault: `send-once-retries-after-accept` (default; targets `ONCE`). No knobs of its own: the
  per-Creator plan is fixed, load scales by `--users` and the profile's Creators.
