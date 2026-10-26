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
| `lib/relay.py` | Runs `scripts/demo-shots/relay_guarded.py` (network guards, redirected secrets and sessions, `CHATTERLY_TEST_MODE`), starts the production persist worker, adds loopback-only `/__slop/*` hooks (below) and answers OnlyFans' side of `OFClient.send_message` (and `get_messages` from `of-truth.jsonl`). Passes `UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN` (5, as the Dockerfile) to uvicorn. Applies `SLOP_FAULT`. |
| `lib/browserbase.py` | The outside world of a served Browserbase login, on loopback: `World(tmp, accounts={email: uid}, otp=, password=, chromium=, autosubmit={email})` runs Browserbase's API (`POST /v1/sessions` launches a fresh local Chromium and answers its CDP URL as `connectUrl`; `/debug` answers a live-view stand-in page that shows that Chromium's tab; release stops it) and OnlyFans' site over a self-signed TLS server (login form, "Signing in…" for `SIGNIN_MS`, 2FA prompt with a decoy first form, "Verifying…" with no field for `VERIFY_MS` after a code, `/my/chats/` with a signed request and a stand-in of OF's signing module, `/api2/v2/users/me`). Every page carries a hidden reCAPTCHA frame (served from the fake site). An `autosubmit` account's 2FA field sends its form itself on the last digit. Chromium maps `onlyfans.com` to the fake site and every other host to NOTFOUND. Records `calls`, `logins`, `otp_tries`, `otp_sends` (code and how it was sent: `click`, `enter` or `auto`), `decoys`, `captcha_frames`, `sessions`. |
| `lib/of_wire.py` | OnlyFans' API at its wire, on loopback (`FakeOF`, a stdlib `ThreadingHTTPServer` in the harness process, a thread per request): what the relay's REAL `OFClient` (curl_cffi, signed headers) reaches when a scenario sets `OF_WIRE = True`. `lib/cli.py` starts it and points the relay's `OF_API_ORIGIN` (the product's loopback-only seam, ADR 0024) at it. Answers the hash CDN, the signing chunk (`/static/prod/f/<rev>/2313.js`, `lib/browserbase.py`'s synthetic one, so a paste-curl `POST /admin/session/bootstrap` derives its rules), `GET /api2/v2/users/me` (with the WS ticket, `wsUrl` + `wsAuthToken`) and `POST /api2/v2/chats/{fan}/messages` (kept per Creator, in order); any other path is a counted 404 (`unmodelled`). Serves OF's chat WebSocket too (`websockets`, its own thread and loop): `{"act":"connect"}` is answered `{"connected":true,"v":"5.4.0"}` as OF does, then nothing is pushed; `ws_connects` records each connect, `drop_ws(ids)` ends those Creators' sockets (the pump reconnects through `/users/me`). `set_otp(ids)` makes those Creators' every `/api2/` call answer 400 with OF's code-101 `otpState` body. Records every call (`calls`: time, Creator, route, status) in arrival order. |
| `lib/faults.py` | Break-it-once faults: each patches a real product function inside the throwaway relay and lists the check names it `targets`. A fault with `browser=` (JS) is instead an init script in every page `actors/ui` opens, for a bug in the app's browser code; with `desktop=` (JS), code the Electron wrapper of `actors/notif_click` runs before `desktop/main.js`, for a bug in the desktop app. |
| `lib/procmon.py` | Relay CPU and RSS every 1 s, each interval tagged with `rec.stage`: the whole process from `ps` (its process group; passes 100% when executor threads run SQLite outside the GIL) and the event-loop thread alone from `GET /__slop/loop-cpu` (`time.thread_time()`; the one-core ceiling). Writes `resources.json`, a per-stage table in `summary.txt` (process CPU mean / p95 / max %, 100% = one core; cores; loop CPU mean / p95; RSS max / end) and, when the scenario sets `CPU_BUDGET_PCT`, the budget check `relay process CPU mean <= N% of one core in every stage`. With `--profile`, tells the relay's sampler the stage and saves `profile-<stage>.txt` (loop thread and other threads: top self functions or SQL statements, self lines, cumulative), `profile-<stage>-{loop,threads}.collapsed` (flamegraph input) and `profile.json`; `summary.txt` gets the top 10 of the peak-CPU stage. |
| `lib/client.py` | Timed HTTP client. Every actor call is recorded (route, status, latency), so the stock invariants need no extra code. Set `ctx.rec.stage` to also keep calls per load stage (`ctx.rec.summary(stage)`); `ctx.rec.timeline` keeps every call with its end time. Idle keep-alive connections are reused only under 2 s (`KEEPALIVE_EXPIRY_S`): httpx's 5 s default equals uvicorn's and gets requests reset after a relay stall. |
| `lib/report.py` | Invariants, metrics and the evidence writer. `ctx.check(..., budget=True)` labels a latency budget (a miss is still FAIL); `ctx.check(name, None)` or `ctx.skip(name, reason)` records SKIP (no samples, `--no-ui`), shown and never a pass. `ctx.note(...)` adds lines (e.g. a per-stage table) to `summary.txt`. |
| `lib/cli.py` | Discovers scenarios, handles the knobs, adds the stock invariants, and runs the break-it-once logic. `OF_WIRE = True` starts `lib/of_wire.py` for the run (`ctx.of_wire`) and sets the relay's `OF_API_ORIGIN` to it. `EXPECTED_TRACEBACKS = ((marker, text), ...)`: a relay Traceback whose preceding log line holds `marker` and whose exception line holds `text` is the product logging an error the scenario provokes on purpose, not an unexpected one. |
| `seed/` | One seeder per entity: `agency` (real `POST /auth/register`, `n` Agencies), `creators` (optional owner per Creator), `fans` (one size, or a size per Creator), `threads`, `of_sessions` (a captured session file per Creator, `session_wire.json` in the bootstrap's shape with `lib/browserbase.py`'s synthetic signing rules, and `latest.json` pointed at it, so the relay builds a REAL `OFClient`; only for an `OF_WIRE` run). Sizes come from `seed.SCALES`. |
| `seed/profiles/` | Named world shapes that only compose seeders: `agency_inbox`, `multi_agency_big_models` (5 Agencies, 20 Creators, 3 big). |
| `actors/` | Simulated people: `fan_dm` (fans DMing: `serial`, the pump's shape, one frame in flight per Creator, optional `rate`; `burst`, many in flight per Creator; or open-loop `Paced` DMs/minute with tips, PPV purchases and typing), `chatter` (head page, thread, mark read, reply), `manager` (SSE listener with arrival times; `states=(types)` also keeps those `state` events as (type, fields, `__account_id`), batch frames unwrapped; `ended` if the stream died; plus inbox reads), `ui` (signed-in Chromium, screenshots; `owner_browser(..., scale=2)` for a zoomed crop; `owner_tabs` + `PROBE_JS` for SSE receipt/handler time, long tasks, heap, rows, marker text), `notif_click` (the owner clicking a fan DM's notification from each place it shows, in headless Chromium and in the real Electron app (temp userData, never the user's profile; SKIP without the binary); each click must leave one Messages Pro window, never reloaded, with a Fan that had no tab now active, stored and its chat open; its bypasses are in the module docstring). |
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
- **OnlyFans at its wire (`OF_WIRE = True`).** The relay's real `OFClient` (curl_cffi,
  the product's signing, its own error handling) talks to `lib/of_wire.py` through the
  product's `OF_API_ORIGIN` seam; `seed/of_sessions` writes each Creator's session file.
  curl_cffi then refuses every non-loopback host (as for the Browserbase hook). Declared:
  the `Sign` / `Time` / `X-Hash` headers are only checked to be present, never verified;
  the hash CDN always answers; 50 ms per call is a guess at OF's latency; the code-101
  body's `message` text is a guess (its `otpState` / `strong` payload is what OF web's
  bundle reads). `POST /__slop/automation-tick` runs one
  `automation_executor._drain_due_jobs_once()` pass and waits for every task it spawned
  (and the dead-session probe): it stands in for the supervisor's 30 s cadence; the claim,
  the run slots, `run_once` and the per-account 11 s write spacing are the product's.
  The WS pumps run as well, against the fake's socket: `_run_ui_safe` no-ops
  `server._start_account_pump`, and an `OF_WIRE` relay points it at the product's own
  `_do_start_account_pump` on the relay loop (declared), so a re-capture's
  `_restart_account_pump` starts a real pump. `POST /__slop/pump-supervise` runs one
  `server._reconcile_pumps()` pass (the pump supervisor's body; its 15 s cadence is the
  bypass) and answers each pump's state; `GET /__slop/pumps` answers the states alone.

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
every count back from `relay.log`. `POST /__slop/browserbase {api, chunk_url_tpl[, job_window_s]}` points
`remote_login.BROWSERBASE_API` and `session_bootstrap.CHUNK_URL_TPL` at a `lib/browserbase.py`
World, sets dummy `BROWSERBASE_API_KEY` / `BROWSERBASE_PROJECT_ID`, and makes curl_cffi (which
bypasses the socket guard) refuse every non-loopback host. All `/__slop/*` hooks exist only in
`lib/relay.py`, never in `service/`. `job_window_s` shortens `remote_login.JOB_WINDOW_S` for
the jobs started next (time compression; the hook without it restores the default).

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

`POST /__slop/automation-tick` (`OF_WIRE` runs) drains the due scheduled jobs once, as the
supervisor's loop does every 30 s, and answers when every job it spawned (and the dead-session
probe) has finished: `{spawned, ms}`.

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
  inbox, and Messages Pro shows the burst (screenshot). Then `actors/notif_click`: a
  click on a fan DM's notification (toast in the main window and in Messages Pro, top
  bar bell row, /notifications row, OS notification; the same minus the page row in the
  desktop app) opens that Fan as a Fan tab in the one Messages Pro window, taken in
  place, never reloading it (screenshots of each trigger and settled window, `notif-click.json`;
  `--set desktop=0` skips Electron). Budgets: e2e p95 (frame -> `/events`),
  `/admin/chats/recent` and `/admin/messages` p95. Faults: `transcoder-drops-1-in-10`
  (targets the thread and unread checks); `--fault=notif-click-opens-browser-tab` (the
  links' old browser-tab target, an open that misses the Messages Pro window, and the
  desktop app's old window rule; targets all nine click checks).
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
- `2026-10-25-browserbase-otp-login`: Add creator > Browserbase login when OnlyFans asks
  for a 2FA code. One owner, four logins against `lib/browserbase.py`, every OnlyFans page
  carrying a hidden reCAPTCHA frame and the 2FA page a decoy first form. API: the job stops
  in state `otp` with a live view, a wrong code via `POST /admin/login/remote/{id}/otp` is
  "being checked" (a second code meanwhile is 409), then comes back as rejected as soon as
  the prompt is back (inside `OTP_VERIFY_S`, never a fresh ask) with the job still on the
  prompt, the right code signs in; `accounts` + `user_accounts` rows, `GET /admin/accounts`,
  the session files; 409 for a finished job, 400 for a malformed code or body, never
  echoed. AUTO: a 2FA field that sends its form itself on the last digit: a wrong code is
  rejected (never "couldn't type"), the right one signs in. LATE: a job with an 80 s window
  (the hook's `job_window_s`): a code after its deadline is 404, the expired-job answer, and
  never reaches OnlyFans. With UI, the card (screenshots `card-otp-prompt`,
  `card-otp-pasted`, `card-otp-rejected`, `card-otp-linked`): "1234-5678" pasted from the
  clipboard is the 8-digit code (wrong: rejected on the card), then the right code links
  the account (job status, `user_accounts` row). Also: no status ever says `challenge`
  (and the hidden frame did load); OnlyFans' 2FA field got exactly the submitted codes in
  order, each sent with the 2FA form's own VERIFY button (or by the field itself), the
  decoy never; every Browserbase session released; no code (wrong or right, any login) or
  password in any status, `relay.log` or `next.log`. A flow, not a volume one: `--users`
  and `--scale` change nothing. Bypasses: Browserbase is a local Chromium per session
  behind a fake API (no Browserbase proxies, no captcha solving); the live view is a
  stand-in page of CDP screenshots; OnlyFans is a loopback TLS site (self-signed, Chromium
  told to ignore certificate errors) whose signing chunk is synthetic (the relay derives
  and verifies its rules with the real `of_signer`) and whose page-side signing module is a
  stand-in the login extension's interceptor captures; `CHUNK_URL_TPL` redirected to it;
  the LATE job's window is compressed. Fault `otp-code-never-consumed` (the job never reads
  the code) turns only the code checks (API, AUTO and card) red;
  `--fault=challenge-counts-hidden-frames` (the pre-fix challenge check: any captcha frame
  counts, on screen or not) turns only the "no status says challenge" check red.
- `2026-10-25-session-health-otp`: OnlyFans asks a connected login for a 2FA code (HTTP 400,
  code 101, `payload.otpState`). Real `OFClient`s talk to `lib/of_wire.py` (`OF_WIRE`), 5
  Agencies and 20 Creators (each with a healthy `account_health` row from an earlier,
  recovered episode, by SQL), and every Creator's real WS pump runs on the fake's socket
  (`/__slop/pump-supervise` after each tick); `--users` operators each schedule sends (`POST
  /api/of/v2/scheduled-sends`, due at once) for their Agency's Creators, round-robin, and
  `/__slop/automation-tick` drains them. Phase A: every pump connected, every send delivered.
  Then OF asks Creators 3 (Agency 0, the UI owner's), 5 and 9 (Agency 1) and a fourth Agency 1
  Creator with no automations (the reader) for a code, and ends the three's sockets: their
  pumps reconnect through `/users/me` while 12 concurrent inbox reads each (`GET
  /api/of/v2/chats`, half in one burst at the flip, half spread over the pump's 1 s
  reconnect) meet the same 101; the reader's
  socket stays up, so only its one inbox read can flag it. Phase B schedules a second round
  once all four are flagged, for at least 20 s after the flip. Phase C: OF takes the logins
  again and each owner re-captures each Creator through the real `POST
  /admin/session/bootstrap` (paste-curl: a signed `/users/me` curl under the synthetic signing
  material, whose chunk the fake serves). Checks: `account_health` holds exactly those four,
  reason `otp_required`; one `session_dead` notification per owner per 2FA Creator though
  many callers met the 101 at once, its `href` opening Browserbase login, no other owner
  notified (DB and `GET /admin/agency-notifications`); each affected owner's `/events`
  carried the notification and the pause, no other owner's did; every concurrent read
  answered 502 with OF's 400; the reader is flagged by its read alone (`via=proxy` in the
  relay log, no automation rows); per 2FA Creator at most two `/users/me` over the window (the
  pump's reconnect, the probe's; the old loop makes five), no reconnect, its pump exited and
  stayed parked through the supervisor passes; after detection a 2FA Creator runs nothing (no
  run row, no send, no OF call but the probe's `/users/me`) and its sends stay pending; every
  healthy Creator's send reached OF once, in fire-time order (among sends already
  scheduled when its previous send went out: operators post while ticks drain), with its
  outbound row;
  untouched Agencies deliver everything; `/admin/accounts` shows each owner its 2FA Creators
  paused. Recovery: every bootstrap 200 and every flag cleared; every parked send reached OF
  exactly once in fire-time order with its outbound row; no second notification; each pump
  reconnected and runs. Budgets per phase (the tick's p95 includes the real 11 s per-account
  write spacing). The reads' 502s go to their own recorder (declared: they are the expected
  answer, checked, not the stock no-5xx check's). With UI: the bell's Agency row "<Creator>
  needs a 2FA code" (screenshot `trigger-bell-2fa-row`) closes the bell and opens Creators
  with the Link creator modal's Browserbase login section focused, and the row is read
  (`settled-browserbase-login`); the Creator's row shows "automations paused" naming
  Browserbase login (`settled-creators-badge`); a UI step that cannot complete is that
  check's FAIL with a `failed-ui-step-N` picture. The owner's notification has no external
  channel (no email, Telegram or push exists in `service/`): its wire is `/events` plus the
  feed, both checked. Fault `otp-state-not-session-dead` (the classifier's 101 branch off)
  turns red the health, notification, `/events`, reader, WS pump, pause and `/admin/accounts`
  checks and the three UI checks. Fault `session-dead-claim-not-atomic` (the read-then-write
  flip, under which a Creator's simultaneous callers each notify) turns red the
  notification and `/events` checks.
- `2026-10-26-runtime-switches`: Settings > System > Runtime switches, the master flipping
  the relay's env kill switches and caps (`service/runtime_switches.py`). Storm: `--users`
  concurrent `PUT /admin/system/switches/{env}` with the founder admin password (the stack's
  `ADMIN_PASSWORD`), half W7_WEBHOOK_DISPATCH_DISABLED (true / false mixed), half
  SMART_LIST_MAX_ACTIVE (1..50); checks every PUT 200, the relay's cache (GET's override and
  effective value) equal to the stored `runtime_switches` row, one `actions` audit row per
  200, the cap reaching `GET /admin/smart-lists` and refusing the activation past it (cap =
  active + 2: 200, 200, 409), and clear leaving no row. Then W7 from the UI (password typed,
  the row's toggle on, then off again, which clears the override; the same PUTs with `--no-ui`): fans of Creator 0 DM it through the hook,
  no dispatch job while it is on, exactly one per fan once cleared, every DM in its thread.
  Screenshots switches-before, switch-w7-on, switch-w7-cleared. Budget: PUT p95 under the
  storm, p95 vs the last green run. Bypasses: the master role is `users.is_admin` set by SQL
  (operators set it so; no API), Creator 0's webhook config and its enabled
  `welcome_chatter_for_info` rule are SQL rows, and a dispatch is counted as its pending
  `scheduled_jobs` row (no supervisor runs in a slop stack). Fault
  `runtime-switch-env-bypass` (`_global_kill_switch` reads the env directly) turns only the
  "no dispatch while on" check red.
- `2026-10-26-fan-list-chips`: Messages Pro's Fan List after ADR-0003's 2026-10-26
  amendment (UI only, `agency_inbox`). Per Creator, fans DM and tip through the hook (serial
  per Creator), then a chatter opens unread chats without replying (`POST .../mark-read`), so
  they are read and owed. The owner, in Chromium at 1470x915 (a 400px pane), checks the chips
  on screen in order (All, Owe reply, Pinned, Unread, With Tips, the pinned lists, Priority)
  with no "+" and no "✎ Lists"; the Unread and Owe reply counts equal those of the chats the
  Fan List loaded, Owe reply's in amber whether or not it is on; Owe reply lists exactly the
  owed chats, and owe dots show only while it is on; an extra sort turns the sort button blue,
  names it and moves the menu's ✓, with unread rows first; the choice is in localStorage
  (`chatterly:chat-sort-mode`) and survives a reload; the pencil ("Pin lists as chips") shows
  only for one Creator with an OF list and opens the folder picker, where a pin is one write
  that adds the list's chip; the filter row keeps one line at 400px and the sort menu opens
  inside the pane under its button; no console error and no 5xx from the app or relay. It also shoots 2x crops and the 320px phone view. Bypasses: OF's `/chats` is answered
  in the browser from the relay's own view (`/admin/chats/recent` plus each thread's last
  message); OF's chat lists (`GET /chats/folders`) and the pin write (`PATCH
  /lists/{id}/pin-chat`) are faked at the browser's wire; failed loads of URLs the harness
  aborts are not counted as console errors. Fault `fan-list-owe-reply-last-sort-never-active`
  (a browser init script: Owe reply laid out last, where the "+" sat, and the sort button
  never pressed or blue) turns only the chip-order and sort-active checks red.
