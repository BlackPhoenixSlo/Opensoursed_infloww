# slop/: mass-data, mass-user tests against the real app

A slop test seeds a large synthetic world, sets many simulated users loose on the
real relay and the real UI, and checks invariants. It answers "does this work in
practice, at volume" rather than "does this unit behave". All of it lives in this
folder. Each task adds to it, so later tasks reuse earlier seeders and actors.

```sh
slop/run --list
slop/run inbox                                   # any substring of a scenario name
slop/run inbox --scale=medium --users=200        # bigger world, 200 concurrent users
slop/run inbox --break                           # break-it-once: green baseline, then the fault
slop/run inbox --break --baseline=slop/evidence/<run-dir>   # reuse a no-fault run (same knobs)
slop/run inbox --rate=20                         # open loop: 20 frames/s per Creator
slop/run all --no-ui                             # every scenario, skip next dev/Playwright
slop/run inbox --set per_fan=20 --seed=7         # scenario params, another deterministic world
slop/run big-model --dms-per-min=50,100,200       # any --knob=value is a scenario param too
slop/run big-model --profile                      # + per-stage stack profile of the relay
slop/run big-model --break --fault=access-log-writer-spin-waits --baseline=slop/evidence/<run-dir>
                                                 # break-it-once with another fault than the scenario's
```

Needs the repo's `venv/` (FastAPI, uvicorn, httpx, Playwright with Chromium) and
`node` with `app/node_modules` for UI scenarios. Exit code: 0 every scenario passed
(SKIP is not a pass, but not a failure), 1 a check failed, 3 infra (the stack did not
come up, or the scenario crashed). With `--break`: 0 CAUGHT, 1 NOT CAUGHT, 3 INCONCLUSIVE.

## Break-it-once

Each fault in `lib/faults.py` patches one product function and names the checks it
`targets`. `--break` runs a no-fault baseline (or reads `--baseline <run-dir>`, which
must have the same scenario, scale, users, seed, UI and params), then the fault run.
CAUGHT only if every targeted check went PASS -> FAIL. Any other check that changed is
printed as noise and catches nothing (a p95 miss or a flaky screen is not a catch).
INCONCLUSIVE: either run hit infra, the baseline is not green on a target, a target
was skipped, or a target name matches no check. The verdict is appended to the fault
run's `summary.txt` and written to its `break.json`.

## Layout

| Path | Role |
|---|---|
| `run` | The single entrypoint (bash, then `lib/cli.py`). |
| `lib/stack.py` | A throwaway stack for each scenario: the relay on a temp SQLite DB, plus `next dev` if the scenario has UI. Uses free loopback ports and restores `app/tsconfig.json` and `next-env.d.ts` on exit. |
| `lib/relay.py` | Runs `scripts/demo-shots/relay_guarded.py` (network guards, redirected secrets and sessions, `CHATTERLY_TEST_MODE`), starts the production persist worker, adds loopback-only `/__slop/*` hooks (below) and answers OnlyFans' side of `OFClient.send_message` (and `get_messages` from `of-truth.jsonl`). Applies `SLOP_FAULT`. |
| `lib/faults.py` | Break-it-once faults: each patches a real product function inside the throwaway relay and lists the check names it `targets`. |
| `lib/procmon.py` | Relay CPU and RSS every 1 s, each interval tagged with `rec.stage`: the whole process from `ps` (its process group; passes 100% when executor threads run SQLite outside the GIL) and the event-loop thread alone from `GET /__slop/loop-cpu` (`time.thread_time()`; the one-core ceiling). Writes `resources.json`, a per-stage table in `summary.txt` (process CPU mean / p95 / max %, 100% = one core; cores; loop CPU mean / p95; RSS max / end) and, when the scenario sets `CPU_BUDGET_PCT`, the budget check `relay process CPU mean <= N% of one core in every stage`. With `--profile`, tells the relay's sampler the stage and saves `profile-<stage>.txt` (loop thread and other threads: top self functions or SQL statements, self lines, cumulative), `profile-<stage>-{loop,threads}.collapsed` (flamegraph input) and `profile.json`; `summary.txt` gets the top 10 of the peak-CPU stage. |
| `lib/client.py` | Timed HTTP client. Every actor call is recorded (route, status, latency), so the stock invariants need no extra code. Set `ctx.rec.stage` to also keep calls per load stage (`ctx.rec.summary(stage)`); `ctx.rec.timeline` keeps every call with its end time. Idle keep-alive connections are reused only under 2 s (`KEEPALIVE_EXPIRY_S`): httpx's 5 s default equals uvicorn's and gets requests reset after a relay stall. |
| `lib/report.py` | Invariants, metrics and the evidence writer. `ctx.check(..., budget=True)` labels a latency budget (a miss is still FAIL); `ctx.check(name, None)` or `ctx.skip(name, reason)` records SKIP (no samples, `--no-ui`), shown and never a pass. `ctx.note(...)` adds lines (e.g. a per-stage table) to `summary.txt`. |
| `lib/cli.py` | Discovers scenarios, handles the knobs, adds the stock invariants, and runs the break-it-once logic. |
| `seed/` | One seeder per entity: `agency` (real `POST /auth/register`, `n` Agencies), `creators` (optional owner per Creator), `fans` (one size, or a size per Creator), `threads`. Sizes come from `seed.SCALES`. |
| `seed/profiles/` | Named world shapes that only compose seeders: `agency_inbox`, `multi_agency_big_models` (5 Agencies, 20 Creators, 3 big). |
| `actors/` | Simulated people: `fan_dm` (fans DMing: `serial`, the pump's shape, one frame in flight per Creator, optional `rate`; `burst`, many in flight per Creator; or open-loop `Paced` DMs/minute with tips, PPV purchases and typing), `chatter` (head page, thread, mark read, reply), `manager` (SSE listener with arrival times, plus inbox reads), `ui` (signed-in Chromium, screenshots; `owner_tabs` + `PROBE_JS` for SSE receipt/handler time, long tasks, heap, rows, marker text). |
| `scenarios/` | One file per feature or task: `YYYY-MM-DD-<feature-slug>.py`. |
| `evidence/` | Gitignored. One folder per run, with `latest` pointing at the newest. |

## How a run works

1. `lib/stack.py` boots the guarded relay on a fresh temp DB (and `next dev` if `UI = True`).
2. The scenario calls `ctx.build("<profile>")`. The profile composes seeders. The owner
   is registered through the real API, and bulk rows are written into the temp DB
   (50k fans with about 120k messages take about 3 s).
3. Actors hit the real endpoints with `--users` concurrency: `/events` SSE,
   `/admin/chats/recent`, `/admin/messages/...`, and the Next app in Chromium.
4. The scenario calls `ctx.check(name, ok, **detail)` for its invariants. The stock
   invariants are added automatically: no 5xx or transport error on any actor call,
   and no unexpected Traceback in `relay.log`.
5. `evidence/<UTCstamp>-<scenario>[-baseline|-break]-<rand4>/` gets `summary.txt`, `invariants.json`,
   `metrics.json`, `http.json` (per route: n, 4xx, 5xx, p50, p95), `relay.log`,
   `next.log`, `relay-offhost-refused.jsonl`, `resources.json` (relay CPU/RSS per stage),
   `screenshots/*.png` and, with `--profile`, `profile-*`. `params` in
   `metrics.json` records the knobs plus `git_sha` and `git_dirty`.

The relay is ready when `/livez` answers below 500 (`/health` is 503 without an OF
account, which a slop stack never has); `next dev` when `/login` does.

## What is bypassed or faked

- **Bulk seeding is SQL.** Only the owner (`POST /auth/register`) goes through the API;
  Creators, fans, threads and history are inserted straight into the temp DB.
- **The hook replaces the pump.** OnlyFans is never reached, so a fan's DM enters at
  `POST /__slop/of-ws-frame`, which calls `server._broadcast_event(frame)`, the call
  the per-account pump makes (`service/server.py`, `async for event in ws.events():
  await _broadcast_event(event)`). The pump is serial per account, so
  `fan_dm.serial` keeps one frame in flight per Creator. The hook's own POST latency
  is not a product number: budget end to end instead (frame handed to the relay ->
  message on `/events`). Everything after the hook is production code: the
  `event_inbox` persist worker, the transcoder (`messages`, `fans`,
  `chats.unread_count`) and the SSE fan-out.
- **Outbound sends are patched.** `OFClient.send_message` answers like OF (below).
- **One OF read is faked, on request.** When a scenario writes OnlyFans' side of the
  record to `$DEMO_SHOTS_TMP/of-truth.jsonl` (`ctx.stack.tmp`), the chat scrape's
  `get_messages` pages it (below); `automation_executor._make_client` falls back to the
  same offline client. No file: the read fails as before.
- **`/api/of/*` is held in the browser.** OF-live reads never answer (below).

`GET /__slop/loop-cpu` answers `time.thread_time()` from the event-loop thread (polled
once a second) plus the DB pool counters (`db`: connections opened/closed, checked out
now and peak since the last poll, checkouts, and `nested` = a checkout by a task that
already holds one, with its service/ frames); procmon adds them, the relay's thread
count and the host's 1-min load as `threads dbPeak dbOpen nested hostLd` columns (per second in
`resources.json`, with `req_n` / `req_max_ms` of the actor calls that ended in that second). `--profile` adds `/__slop/profile` and two samplers inside the relay
process (`lib/relay.py` `_Sampler`; not py-spy, which needs root on macOS): a SIGALRM
itimer that samples the loop thread where it stands, and a thread that reads the other
threads' stacks (aiosqlite workers labelled with their SQL; wall time, lock waits
included). They share the GIL, cost the relay some CPU and guess idle from the leaf
frame, so compare CPU numbers only between runs with the same `--profile` setting
(`--baseline` refuses a mismatch).

`GET /__slop/stats`: `received` (hook frames), `processed` (`transcode()` returned;
`manager.quiesce` waits on it), `transcoded` (a canonical writer returned and none
raised: successes only, so a dropped or failed frame shows as `processed - transcoded`),
`persist_drops`, `queue_depth`. `POST /__slop/telemetry-flush`: the product's
`service/db/write_telemetry.py` JSON line now (reason `flush`, as on shutdown), so a scenario reads
every count back from `relay.log`. All `/__slop/*` hooks exist only in `lib/relay.py`, never in
`service/`.

In the browser, `/api/of/*` (OF-live reads) is held pending. Screens therefore show
what the relay's own DB serves, such as the Fan List's local seed. Every other
off-host request is aborted and counted.

The same holds outbound: a chatter's reply (`POST /api/of/v2/chats/{fan}/messages`)
reaches OnlyFans through `OFClient.send_message`, which `lib/relay.py` answers with
the new message (id, text, createdAt), as OF would. Every other OF call still fails
as before, except `get_messages` when the scenario wrote `of-truth.jsonl` (lines
`{account_id, fan_id, message}`; paged newest first with `before_id`, `hasMore`, as OF
does). That is the read behind the chat scrape and `POST
/admin/messages/{aid}/{fan}/rescrape-now`. The attribution row, unread clear and
`chat_responded` after it are product code. The `/__slop/*` hooks write no `actions`
audit row (the real pump has no HTTP request around a frame).

`ctx.stack.crash_relay()` SIGKILLs the relay's process group (no shutdown hook runs,
as in an OOM kill) and returns the epoch time; `ctx.stack.start_relay()` (blocking:
`asyncio.to_thread`) starts it again on the same DB, port and env, appending to
`relay.log`. Open `Http` pools die with it: `ctx.owner.share()` afresh after.

Upgrade path: when a fake OnlyFans that speaks the WS protocol
exists, `actors/fan_dm.py` sends through it instead, and the real pump consumes the
frame. Scenarios do not change.

## How a task adds to this (the compounding rule)

1. **Reuse first.** Read `seed/`, `seed/profiles/` and `actors/`. Compose what
   exists. Add a seeder only for an entity no seeder writes yet, and an actor only for
   a behaviour no actor performs.
2. **New seeder:** `seed/<entity>.py` with `seed(w, ...)`. It takes sizes from
   `w.size[...]` (add the key to all three `SCALES`), draws randomness only from
   `w.rng("<entity>")`, stores its output in `w.data["<entity>"]`, and returns it.
   Never shift another seeder's RNG stream.
3. **New profile** only when no shape fits: `seed/profiles/<shape>.py`, with
   `async def build(w)` composing seeders.
4. **New scenario:** `scenarios/<YYYY-MM-DD>-<feature-slug>.py`, dated the day the
   feature lands so it maps to git history. It defines
   `PROFILE`, `UI`, `FAULT`, its numeric budgets (e.g. `E2E_P95_MS`, `P95_MS`), and
   `async def run(ctx)`. Assert invariants (counts match, nothing dropped, ordering),
   not snapshots; budgets are `budget=True` checks. With no samples, or with
   `--no-ui` for a UI check, `ctx.skip` it rather than passing it. A UI scenario
   takes at least one screenshot with `ui.shot`.
5. **New fault:** add it to `lib/faults.py` with the exact check names it `targets`.
   It patches the product function whose bug class the scenario claims to catch.
   Then run `slop/run <slug> --break`. The task is not done until it prints `CAUGHT`.
6. Run `--scale=small` while iterating, then `--scale=medium --users=200` before you
   call it done. Quote the evidence folder.

`ctx` gives a scenario: `ctx.build(profile)`, `ctx.world` (`.data`, `.rng`, `.sql()`),
`ctx.owner` (signed-in `Http`; `.share(limits=N)` for another pool on the same session),
`ctx.check`, `ctx.skip`, `ctx.metric`, `ctx.param(key, default)` (from `--set`), `ctx.scale`, `ctx.users`,
`ctx.seed`, `ctx.relay`, `ctx.app` (None without UI), `ctx.out` (the evidence dir) and
`ctx.rec` (the HTTP recorder).

## Scales

| `--scale` | Creators | Fans | Big Creator fans | Threads | History per thread |
|---|---|---|---|---|---|
| small | 3 | 150 | 2,000 | ~60% | 4 |
| medium | 10 | 5,000 | 10,000 | ~50% | 6 |
| huge | 10 | 50,000 | 50,000 | ~40% | 6 |

"Big Creator fans" is per big Creator (`multi_agency_big_models`: 3 big + 17 normal
Creators at `fans_per_creator` each).

## Safety

Every run uses a temp DB, a temp `sessions/` and a redirected secret store. The relay
refuses every non-loopback socket and DNS lookup (`relay_guarded.py`), `next dev`
runs under `fetch-guard.cjs`, and Chromium resolves no name except localhost. Nothing
reads or writes `service/chatterly.db`, real sessions, prod or any remote. The
`/__slop/*` hooks are loopback-only and exist only in this wrapper.

## Scenarios

- `2026-10-23-inbox-unread-fan-burst`: `--users` fans DM their Creators, sent the
  pump's way (one frame in flight per Creator, all Creators at once; `--rate=N` for
  open loop, with scheduled vs achieved rate and lag in `metrics.json` `pump`), while
  the manager watches `/events` and the inbox. The checks: every DM is accepted,
  there are zero persist drops, every DM reaches SSE, every DM is in its thread,
  `unreadMessagesCount` equals seeded plus sent, the burst fans head their Creator's
  inbox, and Messages Pro shows the burst (screenshot). Budgets: e2e p95 (frame ->
  `/events`), `/admin/chats/recent` and `/admin/messages` p95. Fault:
  `transcoder-drops-1-in-10` (targets the thread and unread checks).
- `2026-10-24-big-model-dm-flood`: 5 Agencies, 20 Creators, 3 big (2k/10k/50k fans).
  Fans DM at an open-loop rate per big Creator ramped through stages
  (`--dms-per-min=50,100,200`, each `--stage-s`; normal Creators 5/min; tips,
  PPV purchases, typing), `--users` chatters work the inbox, and the owner's
  browser holds 4 live tabs (All Models inbox, 2 popouts, Group). Checks:
  nothing dropped (event_inbox, messages, each Agency's /events, the inbox tab),
  no cross-Agency leak, per-thread order on every stream, no `resync` overflow,
  unread per thread, one ledger row per tip/purchase, one row per reply; budgets
  per stage for relay p95, SSE lag, marker DM -> rendered in its open popout/group
  thread and -> All Models list row, long tasks/min, heap, with a per-stage table
  in `summary.txt`, plus relay process CPU mean <= `CPU_BUDGET_PCT` (80% of one core) per stage.
  A crashed tab is recorded (stage), never a crashed run. Fault:
  `sse-fanout-reorders-within-thread`; `--fault=access-log-writer-spin-waits` proves the CPU check.
  When stages are >= 60 s (medium), stage 2 SIGSTOPs the relay for 2 s (a starved VPS) and
  checks the 30 s after SIGCONT: CPU <= 300% every second and p95 <= 750 ms, i.e. no SQLite
  connection storm. That storm (6/10 medium runs before; 3-11 cores, p95 1-6 s) was the
  unbounded pool overflow opening one connection per waiting session; `service/db/engine.py`
  now holds `pool_size` connections FIFO and spills one only after a 2 s wait. Fault
  `db-pool-unbounded-overflow` puts the old pool back (`--break --fault=db-pool-unbounded-overflow`).
  Production write telemetry (`service/db/write_telemetry.py`, one JSON line a minute in the relay
  log): after a forced flush the scenario reads every line back from `relay.log` and checks they came
  every 60 s (+-5), that frames and per-Creator DMs sum to what was injected, and that every drop
  counter is 0; `summary.txt` gets its per-writer table (txns, wait/hold p95, lock-held seconds).
  `CHATTERLY_WRITE_TELEMETRY_S=0 slop/run big-model ...` turns it off (checks SKIP) for an overhead A/B.
  Fault `write-telemetry-misses-1-in-50-dms` (`--break --fault=write-telemetry-misses-1-in-50-dms`).
  OF-cache writer (`service/db/of_writer.py`, group commit for OF-sourced rows): every op
  committed and no persist / transcode transaction outside its batches; mark-read <= 1.05 and
  reply <= 2.05 write transactions per call (`READ_TXNS_MAX`, `REPLY_TXNS_MAX`); `summary.txt`
  gets batches, coalesced ops, flush / op-age p95. Fault `of-writer-per-op-txns`.
- `2026-10-24-dm-flood-relay-crash`: a fan DM flood (`fan_dm.serial`, `--rate` frames/s per
  Creator, default 5) during which the relay is SIGKILLed, stays down 2 s while fans keep
  writing, and restarts on the same DB. Then every DM sent goes into `of-truth.jsonl` and
  `rescrape-now` runs per thread. Checks: loss is bounded (every DM the relay took more than
  `LOSS_WINDOW_MS` = 1 s before the kill is in its thread), rescrape-now ok, after it every DM
  is in its thread, none twice; metric `crash_loss` measures what was lost and how close to the
  kill. Bypass: the fan pump has its own Recorder, so frames sent into the outage (transport
  errors) are counted in metric `pump`, not the stock no-5xx check. Fault
  `of-writer-holds-batches-3s` (a writer that waits instead of flushing as soon as work exists).
