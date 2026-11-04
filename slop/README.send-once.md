# slop/: Scheduled send once

A chatter's scheduled DM goes to OnlyFans once, never twice: a send OF may have taken is never retried, whether
its answer never came or the relay died after OF took it (`run_decide.outcome`, the boot heal's
`one_shot_family`; parked `error`, "may have sent"). The harness, its knobs and its rules are in `README.md`; this
file is only what this flow adds, plus the KILL phase two drip senders share (below). The scenario's docstring is its spec (phases, the open owner question,
bypasses).

## Layout

| Path | Role |
|---|---|
| `lib/send_once_relay.py` | OnlyFans' side of a 1:1 send, only while a scenario writes `$DEMO_SHOTS_TMP/of-send-once.json` (`{fans: {"<account>:<fan>": "stall" \| "hang" \| "refuse_once" \| "echo_5xx"}, stall_s, hang_s}`, read on every send): `_OfflineOF.send_message` answers the first time OF sees a text by its fan's behaviour (`stall`: OF takes it, then curl's ReadTimeout after `stall_s`; `hang`: OF takes it, the call blocks `hang_s`; `refuse_once`: the proxy refuses the CONNECT, OF never saw it; `echo_5xx`: OF takes it, then a 502 whose text echoes OF's rate-limit refusal), any other fan as OF does. Opt-in `first_key: fan_text` (lines that repeat across fans): "first time" per (account, fan, text), and `4xx_after_first`, `noid_4xx_after_first`, `hang_after_first` (the KILL phase, below). OF's record `of-send-once.jsonl` (`refused`, `rejected`, `accepted`, `returned` lines, one O_APPEND write each, so it outlives a SIGKILL); `read_journal(tmp)` reads it. Raised errors start `SLOP_MARK`. |
| `lib/send_once_faults.py` | The check names and its faults (below). |
| `lib/send_marker_kill.py` | The KILL phase's driver (`Kill`), shared by the scenarios that kill a sender mid-step; each keeps its seeding, OF modes and checks. |
| `lib/send_marker_faults.py` | The KILL phases' check names and faults (each in its scenario's entry), patching names the product looks up at call time in the relay. |
| `scenarios/2026-10-31-scheduled-send-once.py` | The scenario. |

## Scenarios

- `2026-10-31-scheduled-send-once`: `agency_inbox`; the real supervisor runs (`SLOP_SUPERVISOR=1`, its boot heal
  is the orphan path) and `/__slop/automation-tick` adds passes. `--users` chatters schedule due-now DMs through
  the composer route (`POST /api/of/v2/scheduled-sends`, X-Account-Id), round-robin over the Creators' fans, and
  each keeps the chat's ghost-bubble list open (`GET /api/of/v2/scheduled-sends?fan_id=`, every 2 s). Phase A,
  per Creator: 2 stall, 1 refuse_once, 1 plain. Phase B: 2 hang per Creator; once every run slot holds a send OF
  took and has not answered, the relay is SIGKILLed, OF answers normally, the relay restarts on the same DB and
  the boot heal's `reconciled_orphans` line is awaited. Phase C, per Creator: one ECHO send OF takes and answers
  with a 502 echoing its rate-limit text. Checks: `ONCE` ("OF holds exactly 1 message per job"),
  `SETTLED`, `PARKED`, `REFUSED`, `ECHO_5XX` (each ECHO send one OF message, job error "may have sent", never
  resent) (`lib/send_once_faults.py`), and the scenario's own "SIGKILL landed with every
  running send taken by OF and unanswered (>= one per run slot)"; budgets: `POST` / `GET
  /api/of/v2/scheduled-sends` p95 and schedule -> OF took it p95 (plain, phase A), all in the scenario, also vs
  the last green run. Faults: `send-once-retries-after-accept` (default; `run_decide.ONE_SHOT_KINDS` emptied: the pre-fix
  lane; targets `ONCE`, `ECHO_5XX`), `rate-limit-text-sniff` (`of_write.is_rate_limited` on the text alone, the
  pre-fix gate; `ECHO_5XX`, `ONCE`). No knobs of its own: the
  per-Creator plan is fixed, load scales by `--users` and the profile's Creators.

## The KILL phase (follow-up drip, house funnel)

Send once for the drip senders (`service/automations/send_marker_decide.py`): a nudge or funnel step killed
mid-send is never auto-resent, it is listed "may not have sent" and the user retries it. `2026-10-30-followup-drip`
(`README.followup.md`) and `2026-10-30-house-funnel-walk` (`README.funnel.md`) end on it, on the first 4 Creators
(the 4 run slots; each entry lists its own fans, checks and faults). OF's side is `lib/send_once_relay.py` with
`first_key: fan_text`; ticks until each hung fan's text is taken and unanswered, SIGKILL, restart on the same DB
(`lib/send_marker_kill.py`); then the scenario's own ticks, the owner's `GET /admin/unconfirmed-sends`, one `POST
/admin/unconfirmed-sends/retry` per hung fan, one more tick. Relay modes per role: the drip's KILL fans `hang`; the
funnel's `kill` `hang` (`hang_after_first` for the landed fan), `partial` `4xx_after_first`,
`partial_noid` `noid_4xx_after_first`. Bypasses: the dead holder's `fan_lease` rows expired and the retried fans'
send rest nulled by SQL.
