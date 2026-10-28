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
SLOP_PY=/usr/local/bin/python slop/run ...       # another Python for the relay
slop/run all --timeout=600                       # wall clock per scenario run (default 1800 s, 0 = none)
```

Needs the repo's `venv/` (FastAPI, uvicorn, httpx, Playwright with Chromium) and
`node` with `app/node_modules` for UI scenarios (`web/node_modules` for fleet-200's
landing build). In a linked worktree (`git worktree add`), `slop/run` links each one
it lacks to the main checkout's on the first call (`slop/run --list` is enough), so
`venv/bin/python` for service tests works there too. Exit code: 0 every scenario passed
(SKIP is not a pass, but not a failure), 1 a check failed, 3 infra (the stack did not
come up, the scenario crashed, or it ran past `--timeout`). With `--break`: 0 CAUGHT,
1 NOT CAUGHT, 3 INCONCLUSIVE.

`--timeout` bounds each scenario run from stack start to teardown (a hung browser
close or teardown included). Past it, SIGALRM cancels the scenario, its finally blocks
and the stack's teardown run, the run is INFRA (`scenario finished within --timeout`
FAIL, summary written), and the next scenario starts.

## Break-it-once

Each fault in `lib/faults.py` patches one product function and names the checks it
`targets`. `--break` runs a no-fault baseline (or reads `--baseline <run-dir>`, which
must have the same scenario, scale, users, seed, UI and params), then the fault run.
CAUGHT only if every targeted check went PASS -> FAIL. Any other check that changed is
printed as noise and catches nothing (a p95 miss or a flaky screen is not a catch).
INCONCLUSIVE: either run hit infra, the baseline is not green on a target, a target
was skipped, or a target name matches no check. The verdict is appended to the fault
run's `summary.txt` and written to its `break.json`.

A client fault (`Fault(None, targets, browser=((regex, replacement), ...))`) breaks the
app's own code the same way, in flight and never in the repo: `actors/ui.py` routes every
`/_next/static/**.js` the browser loads, applies the rewrites to the unminified module
`next dev` serves, and counts the matches (`browser_fault_hits` in `metrics.json`, and
`browser_fault_files`: the files the rewrites hit, each with its matches summed over every
load of it). A run where a rewrite matched nothing is INFRA (a stale pattern, or `--no-ui`),
so it can never read as NOT CAUGHT; so is one whose matches landed in any number of distinct
files but the fault's `browser_files` (default 1): the pattern must stay unique to the
module it breaks, or a red check could be another module's. Declared: only the fault run
routes the JS through the harness (fetched, rewritten, served), so its page loads are a
little slower; a file the page dropped mid-load is aborted, never served unpatched. A check
that runs the app's own TypeScript in node (`lib/app_ts.py`) gets the same rewrites on the
modules it loads, so a client fault can be caught without a browser too: those matches count
toward `browser_fault_hits`, the modules they hit are `app_ts_fault_files`, and they too must
land in 0 or exactly `browser_files` modules.

The load must not depend on the fault: actors pick what to do from the seed, not from
what the faulted route answered, else the fault also changes the load and a latency
budget goes red as noise.

## Layout

| Path | Role |
|---|---|
| `run` | The single entrypoint (bash, then `lib/cli.py`). |
| `lib/stack.py` | A throwaway stack for each scenario: the relay on a temp SQLite DB, plus `next dev` if the scenario has UI. Uses free loopback ports and restores `app/tsconfig.json` and `next-env.d.ts` on exit (a file that did not exist before the run is deleted, not restored; a run without `next dev` touches neither). Points `TYPESAFE_BASE_URL` at the relay's loopback fake (a flow's relay part serves it, and points the DeepSeek provider at its own); `SLOP_LIVE=1` instead passes the caller's `TYPESAFE_API_KEY` / `DEEPSEEK_API_KEY` and allows only `api.typesafe.ai` and `api.deepseek.com` off-host. `shards=N` (a fleet): N relays, each with its own temp dir (`sNN/`: DB, sessions, off-host log), port, process group and SESSION_SECRET, logs `relay-sNN.log`; `next dev` only on the scenario's `APPS` shard indexes (`next-sNN.log`), or on its `UI_APPS` when the run has UI. `boxes={name: (shard indexes)}` (a scenario's `BOXES`, with `SHARDS_PER_BOX`) lays the shards out as the boxes do: `<box>/shards/sNN/` with `data/chatterly.db`, `service/` (sessions, secrets, off-host log) and a `.env` with the session secrets, as `oi-backup` reads them. `kill_group(pid)` SIGKILLs any process group it started; `stop_relay(i, grace_s)` stops relay `i` as `docker stop` does (SIGTERM to its group, SIGKILL past the grace) and returns when it exited and how long it took. A scenario's `RELAY_ENV` dict is added to every relay's env (lib/cli.py). `relay_cmd()`, `relay_env_of(i)`, `spawn(cmd, env, log)` and `wait_ready(...)` start another relay (another box's) the stack still reaps and collects off-host logs from. `SLOP_PY` picks the relay's Python. `app_mode="prod"` (a scenario's `APP_MODE`, one shard) serves the app as production does instead: `next build --turbopack` into `app/.next/slop-prod` against this run's relay (the rewrites bake `RELAY_URL` in; ~15 s, `next-build.log`), then `next start`; the build's edits to `tsconfig.json` / `next-env.d.ts` are put back at once. In a worktree, Turbopack refuses `slop/run --list`'s symlinked `app/node_modules`: the run stops and names the fix (an APFS clone, `cp -cR`). A stack with `next dev` takes an exclusive per-checkout lock (`app/.next/slop.lock`, flock): a second one refuses with INFRA and names the holder, since both would share `app/.next/slop*` and rewrite `app/tsconfig.json`. |
| `lib/relay.py` | Runs `scripts/demo-shots/relay_guarded.py` (network guards, redirected secrets and sessions, `CHATTERLY_TEST_MODE`), starts the production persist worker, adds loopback-only `/__slop/*` hooks (below) and answers OnlyFans' side of `OFClient.send_message` (and `get_messages` from `of-truth.jsonl`; OF Statistics' `earnings_chart` / `my_profile_stats` / `subscribers_chart` from `of-statistics.json`, each read 0.3 s, counted as `of_earnings_reads`; `me()` from `of-me.json`). `POST /__slop/of-stats-tick` runs one `of_stats_daily` pass now. A flow's relay part, `lib/<flow>_relay.py` when present, adds to the offline OnlyFans (its `OF` class joins `_OfflineOF`'s bases) and wires its own hooks (`wire(app, loopback, relay)`, at the end of `_wire`). `SLOP_SUPERVISOR=1` starts the real automation supervisor (`CHATTERLY_TEST_MODE` skips it otherwise). Passes `UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN` (5, as the Dockerfile) to uvicorn. Applies `SLOP_FAULT`. `relay_guarded.py` points the proxy registry (`proxies.REGISTRY_PATH`) at the temp dir's `proxies.json`, so a proxy added through `/admin/proxies` never touches the checkout's; `POST /__slop/proxy-pool {text}` runs the startup's own `proxies.sync_pool` (the fake proxies' ports exist only once the relay is up) and evicts the pooled clients; under `OF_WIRE` it points `proxies.TRACE_URL` (the proxy probe's Cloudflare trace) at `lib/of_wire.py`'s `/cdn-cgi/trace`. |
| `lib/of_wire.py` | OnlyFans' API at its wire, on loopback (`FakeOF`, a stdlib `ThreadingHTTPServer` in the harness process, a thread per request): what the relay's REAL `OFClient` (curl_cffi, signed headers) reaches when a scenario sets `OF_WIRE = True`. `lib/cli.py` starts it and points the relay's `OF_API_ORIGIN` (the product's loopback-only seam, ADR 0024) at it. Answers the hash CDN, the signing chunk (`/static/prod/f/<rev>/2313.js`, `lib/browserbase.py`'s synthetic one, so a paste-curl `POST /admin/session/bootstrap` derives its rules), `GET /api2/v2/users/me` (with the WS ticket, `wsUrl` + `wsAuthToken`), `GET /api2/v2/chats` (empty), `GET /api2/v2/users/notifications/count` (all zero), the Dashboard's per-Creator reads `GET /api2/v2/subscriptions/count/all`, `subscriptions/subscribers/chart`, `payouts/referrals/chart` and `users/notifications` (empty or zero; subscriber counts from the Creator id) and `POST /api2/v2/chats/{fan}/messages` (kept per Creator, in order), and Cloudflare's `GET /cdn-cgi/trace` (the proxy probe's, through the fake proxy to loopback, never 1.1.1.1); any other path is a counted 404 (`unmodelled`). The module docstring is the route table. Serves OF's chat WebSocket too (`websockets`, its own thread and loop): `{"act":"connect"}` is answered `{"connected":true,"v":"5.4.0"}` as OF does, then nothing is pushed; `ws_connects` records each connect, `drop_ws(ids)` ends those Creators' sockets (the pump reconnects through `/users/me`). `set_otp(ids)` makes those Creators' every `/api2/` call answer 400 with OF's code-101 `otpState` body. Every `/api2/` call waits `latency_s`, plus `extra_s[creator]` for that Creator (a slow proxy, e.g. retries on CONNECT 403). Records every call (`calls`: time, Creator, route, status) in arrival order. |
| `lib/proxy_wire.py` | A Creator's proxy at its wire, on loopback (`ProxyWire`, a SOCKS5 server, a thread per connection): bound through the product's own `POST /admin/proxies` + `/admin/proxies/assign`, it tunnels the relay's REAL `OFClient` to `lib/of_wire.py`. `kill()` ends the open tunnels and answers each later CONNECT, after `refuse_s` (0.33 s, measured from prod's `proxy_error_retry` gaps), with SOCKS5 reply 0x02, which curl_cffi raises as `ProxyError` like prod's CONNECT 403, so the product's retry, proxy_health and 502 run unchanged. `revive()` lets CONNECTs through again. Records every CONNECT (`connects`: t, alive, dest; the probe's trace CONNECTs too, which the relay logs as `proxy_probe`). A pool of them is synced through `POST /__slop/proxy-pool` (`lib/relay.py`). Declared: SOCKS5, not HTTP CONNECT (curl tunnels only an https target through an HTTP proxy, and the fake OF is http). |
| `lib/wan.py` | A phone's way to the app, all on loopback: `WanEdge(stack, rtt_ms)` puts nghttpx (TLS, HTTP/2, as Traefik) in front of the stack's app and a `DelayProxy` (each byte held half the RTT each way, order kept; a new connection one RTT before its first byte) in front of that, so a fresh connection pays connect + TLS 1.3 + request = 3 RTTs, as a live deployment measured. `edge.url` is `https://localhost:<port>`; launch Chromium with `edge.chrome_args` (the per-run self-signed cert's SPKI pinned), not `ignore_https_errors`: Chromium caches nothing from an origin with a certificate error. Bandwidth and CPU are Chromium's throttling (CDP); no loss, no TCP slow start. Edge access log `edge-access.log`. |
| `lib/browserbase.py` | The outside world of a served Browserbase login, on loopback: `World(tmp, accounts={email: uid}, otp=, password=, chromium=, autosubmit={email})` runs Browserbase's API (`POST /v1/sessions` launches a fresh local Chromium and answers its CDP URL as `connectUrl`; `/debug` answers a live-view stand-in page that shows that Chromium's tab; release stops it) and OnlyFans' site over a self-signed TLS server (login form, "Signing in…" for `SIGNIN_MS`, 2FA prompt with a decoy first form, "Verifying…" with no field for `VERIFY_MS` after a code, `/my/chats/` with a signed request and a stand-in of OF's signing module, `/api2/v2/users/me`). Every page carries a hidden reCAPTCHA frame (served from the fake site). An `autosubmit` account's 2FA field sends its form itself on the last digit. Chromium maps `onlyfans.com` to the fake site and every other host to NOTFOUND. Records `calls`, `logins`, `otp_tries`, `otp_sends` (code and how it was sent: `click`, `enter` or `auto`), `decoys`, `captcha_frames`, `sessions`. `paste_curl(uid, rev)` is the curl the owner copies from DevTools for a Creator (the body of `POST /admin/session/bootstrap`). |
| `lib/app_ts.py` | The app's own TypeScript in node, for a check that rests on client logic (`app/lib/`, `app/hooks/`), also in a `--no-ui` run: `await run(ctx, script, payload)` starts `node lib/app_ts.mjs`, which loads the app's modules through vite's SSR loader (vitest's vite, the app's `@/` alias, no config) and calls `script`'s `run(load, input)` with the JSON `payload`; it returns the script's JSON output. The run's client fault rewrites the modules as they load (above). About 0.5 s per call; its vite cache goes to the run's temp dir. |
| `lib/faults.py` | Break-it-once faults: each patches a real product function inside the throwaway relay (or, `browser=`, the app's served JS in the browser actor) and lists the check names it `targets`. A flow's own faults live in `lib/<flow>_faults.py` (`register(Fault)` returns them by name) and join `FAULTS` when the module is present; a name defined twice stops the run. A fault with `browser_js=` (JS) is instead an init script in every page `actors/ui` opens, for a bug in the app's browser code; with `desktop=` (JS), code the Electron wrapper of `actors/notif_click` runs before `desktop/main.js`, for a bug in the desktop app. |
| `lib/procmon.py` | Relay CPU and RSS every 1 s, each interval tagged with `rec.stage`: the whole process from `ps` (its process group; passes 100% when executor threads run SQLite outside the GIL; read from `/proc` where `ps` is missing, e.g. inside the relay image calibrate.sh uses) and the event-loop thread alone from `GET /__slop/loop-cpu` (`time.thread_time()`; the one-core ceiling). `follow(pgid, relay_http)` switches it to a relay's new process (a shard that moved boxes). Writes `resources.json`, a per-stage table in `summary.txt` (process CPU mean / p95 / max %, 100% = one core; cores; loop CPU mean / p95; RSS max / end) and, when the scenario sets `CPU_BUDGET_PCT`, the budget check `relay process CPU mean <= N% of one core in every stage`. Pool columns: `spills` (the pool's own counter) and the pool-wait p95 / max (time inside the pool's checkout, a histogram from `lib/relay.py` with half-open buckets: bucket 100 is [75,100) ms, and the p95 is that exclusive upper bound); with `POOL_GATE = {"spills": 0, "wait_p95_ms": 100}` the scenario gets the decision-5 pool gate check. Every gate site calls one predicate, `pool_bent(spills, wait_p95_ms, gate)`: bent on a spill or a p95 bucket over 100 (bucket 100 holds "< 100 ms"; no checkout timed passes). Per stage it also counts the `/__slop/loop-cpu` polls: `polls` (attempted), `polls_lost` (raised or non-200: the relay may have reset its histogram, so those waits are gone) and `pool_missing` (answered without the wait histogram or the spill counter); a scenario treats any lost or missing poll as no pool data (chatter-crowd: `nodata`, INFRA). Each `resources.json` interval also carries its span, `t_pre` / `t_post` (epoch s) and `mono_pre` / `mono_post` (monotonic s), taken just before the first sample's reads and just after the last's, and the loop thread's run-queue numbers from the relay's `sched`: `q_run_delay_ms` (time runnable but waiting for a CPU) and `q_slices` (timeslices), schedstat deltas, `null` off Linux, context only (never gated). A fleet run has one monitor per shard (`resources-sNN.json`, one table, the CPU budget over every shard). With `--profile`, tells the relay's sampler the stage and saves `profile-<stage>.txt` (loop thread and other threads: top self functions or SQL statements, self lines, cumulative), `profile-<stage>-{loop,threads}.collapsed` (flamegraph input) and `profile.json`; `summary.txt` gets the top 10 of the peak-CPU stage. |
| `lib/client.py` | Timed HTTP client. Every actor call is recorded (route, status, latency), so the stock invariants need no extra code. Set `ctx.rec.stage` to also keep calls per load stage (`ctx.rec.summary(stage)`); `ctx.rec.timeline` keeps every call with its end time. Idle keep-alive connections are reused only under 2 s (`KEEPALIVE_EXPIRY_S`): httpx's 5 s default equals uvicorn's and gets requests reset after a relay stall. |
| `lib/report.py` | Invariants, metrics and the evidence writer. `ctx.check(..., budget=True)` labels a latency budget (a miss is still FAIL); `ctx.check(name, None)` or `ctx.skip(name, reason)` records SKIP (no samples, `--no-ui`), shown and never a pass. `ctx.note(...)` adds lines (e.g. a per-stage table) to `summary.txt`. |
| `lib/cli.py` | Discovers scenarios, handles the knobs, adds the stock invariants, and runs the break-it-once logic. A scenario that crashes leaves `scenario-traceback.txt`. `OF_WIRE = True` starts `lib/of_wire.py` for the run (`ctx.of_wire`) and sets the relay's `OF_API_ORIGIN` to it. `EXPECTED_TRACEBACKS = ((marker, text), ...)`: a relay Traceback whose preceding log line holds `marker` and whose exception line holds `text` is the product logging an error the scenario provokes on purpose, not an unexpected one. |
| `seed/` | One seeder per entity: `agency` (real `POST /auth/register`, `n` Agencies), `creators` (optional owner per Creator), `fans` (one size, or a size per Creator), `threads`, `chatters` (employees via the real `POST /admin/chatters/invite` + `POST /chatter/register`; `account_ids=` per username is the invite's Employee setup, the Creators that chatter may work), `earnings` (OF Statistics' daily net per Creator and category in `<tmp>/of-statistics.json`, plus the `transactions` rows the ledger caught: a trickle before the Creator was connected, most of it since, some sales today; `accounts.created_at` = the connection day), `of_sessions` (a captured session file per Creator, `session_wire.json` in the bootstrap's shape with `lib/browserbase.py`'s synthetic signing rules, and `latest.json` pointed at it, so the relay builds a REAL `OFClient`; only for an `OF_WIRE` run). Sizes come from `seed.SCALES`. A World's `stream` gives a fleet shard its own RNG streams and `user_prefix` its own usernames. |
| `seed/profiles/` | Named world shapes that only compose seeders: `agency_inbox`, `multi_agency_big_models` (5 Agencies, 20 Creators, 3 big), `one_agency` (one relay: one Agency with 50 Creators, 9 big, plus a neighbour Agency with 1 Creator and no chatters). |
| `actors/` | Simulated people: `fan_dm` (fans DMing: `serial`, the pump's shape, one frame in flight per Creator, optional `rate`; `say`, given lines per fan, serial per Creator; `burst`, many in flight per Creator; or open-loop `Paced` DMs/minute with tips, PPV purchases and typing), `chatter` (head page, thread, mark read, reply; `Crowd`: employee mode, each chatter its own `POST /chatter/login` cookie, own `/events` stream and the request pattern of a real chatter tab (tab open, chat open, send, 60 s polls, perflog), human-paced, only its assigned Creators), `manager` (SSE listener with arrival times, each chat message's (account, fan) and every event's `__account_id`; `states=(types)` also keeps those `state` events as (type, fields, `__account_id`), batch frames unwrapped; ready on the stream's first body line, the subscriber is registered by then; `ended` if the stream died; plus inbox reads), `ui` (signed-in Chromium, screenshots; `owner_browser(..., through=, send=)` lets exact `/api/of/` paths or compiled GET path patterns, and the chat send, through to the relay; `close_popup(opener, pop)` closes a window the page opened, its held `/api/of/` reads aborted first (Chromium lets paused requests through when their page closes); `touch=True` is a phone's context (touch input, mobile viewport) and `swipe(page, x0, y0, x1, y1, cancel=, before_end=, via=)` one finger as Chromium touch input (CDP); `chatter_tab` signs in as a chatter and lets its chat send through; `owner_tabs` + `PROBE_JS` for SSE receipt/handler time, long tasks, heap, rows, marker text), `reports` (owners reading the Dashboard's earnings card and Creator reports' Overview with the app's own report reads, human think time), `notif_click` (the owner clicking a fan DM's notification from each place it shows, in headless Chromium and in the real Electron app (temp userData, never the user's profile; SKIP without the binary); each click must leave one Messages Pro window, never reloaded, with a Fan that had no tab now active, stored and its chat open; its bypasses are in the module docstring). `fan_dm.serial(..., ids=)` shares one message-id counter across calls; `phase=` staggers each Creator's open-loop start; `stop=` (an Event) ends an open-ended flood and `out=` receives records as they are sent. |
| `scenarios/` | One file per feature or task: `YYYY-MM-DD-<feature-slug>.py`. |
| `README.<flow>.md` | A flow kept in files of its own (its relay part, faults, seeders, actors, scenarios) documents them there, beside this one. |
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
  same offline client. No file: the read fails as before. Likewise OF Statistics'
  earnings / profile / subscriber charts from `of-statistics.json` (latency 0.3 s, a
  guess); `POST /__slop/of-stats-tick` runs one `of_stats_daily.tick(pause_s=0)` pass,
  bypassing the hourly timer, the 300 s boot grace and the pause between reads.
- **`/api/of/*` is held in the browser.** OF-live reads never answer (below).
- **A Creator's proxy at its wire (`lib/proxy_wire.py`, Layout above).** A SOCKS5 proxy
  on loopback, not OF's HTTP CONNECT; a killed one refuses the way prod's dead proxies do,
  so the product's retry, `proxy_health` and 502 run unchanged. A scenario's `RELAY_ENV`
  (`lib/stack.py`) may set `PROXY_RECHECK_S=2`: the recheck cadence and confirm gap
  compressed 10x, the state machine the same code.
- **Automations run on demand.** `POST /__slop/run-automation {account_id, kind,
  payload}` runs `automations.run_once` under the real run-slot pool (operator=False),
  so a scenario ticks an automation `kind` when it wants instead of the scheduler's cadence.
  With `claim: true` (no payload) `run_once` claims the earliest due `scheduled_jobs` row of
  the kind and runs its payload, as the supervisor's run does (`no_job` when none): only the
  cadence is bypassed. Every `get_messages` call reaching the fake OF is counted per chat
  (`of_get_messages` at `GET /__slop/fake/calls`).
- **OnlyFans at its wire (`OF_WIRE = True`).** The relay's real `OFClient` (curl_cffi,
  the product's signing, its own error handling) talks to `lib/of_wire.py` through the
  product's `OF_API_ORIGIN` seam; `seed/of_sessions` writes each Creator's session file.
  No flow's offline automation client is installed then, and curl_cffi refuses every non-loopback host
  (as for the Browserbase hook). Declared: the `Sign` / `Time` / `X-Hash` headers are only
  checked to be present, never verified; the hash CDN always answers; 50 ms per call is a
  guess at OF's latency; the code-101 body's `message` text is a guess (its `otpState` /
  `strong` payload is what OF web's bundle reads). `POST /__slop/automation-tick` runs one
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
already holds one, with its service/ frames; `wait`: the pool-wait histogram since the last
poll, half-open buckets `ms < b`, so bucket 100 = [75,100) ms; a wait of exactly 100 ms lands in the next bucket) and `sched`: the loop thread's `/proc/thread-self/schedstat` (on-CPU ns, run-queue wait ns, timeslices; cumulative, `null` off Linux). Two harness-side faults act
here, never in service/: `loop-cpu-polls-dropped` answers every 4th poll 503, and
`pool-wait-floor-80ms` records every pool wait as at least 80 ms without sleeping; procmon adds them, the relay's thread
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

Upgrade path: when the fake OnlyFans designed in `.scratch/soak-test/03-system-design.md`
exists, `actors/fan_dm.py` sends through it instead, and the real pump consumes the
frame. Scenarios do not change.

**p95 vs the last green run** (stock): a scenario that sets `P95_VS_LAST = (r, a)` and records
metric `p95_vs_last_green` ({key: ms}) gets `p95 within rx (+ams) of the last green run`, against
the newest earlier run of the same scenario with the same knobs, no fault, no infra and every check
pass/skip (named in `summary.txt`). The first such run is the baseline (SKIP). With
`P95_VS_LAST_MIN_N = n` the scenario also records metric `p95_vs_last_green_n` ({key: samples}): a key
is compared only when both runs have >= n samples (the others are listed as skipped in the check and
`summary.txt`), and an earlier run without that metric is not a candidate.

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
5. **New fault:** add it to `lib/faults.py` (a flow kept in files of its own: its
   `lib/<flow>_faults.py`) with the exact check names it `targets`.
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

A flow with a `README.<flow>.md` lists its scenarios there.

- Sales attribution of tips and PPV (`2026-10-27-sales-attribution-tips-ppv`, Converters' window):
  `README.attribution.md`.

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
  browser holds a live tab per page in `TABS` (All Models inbox, 2 popouts, Group). Checks:
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
- `2026-10-25-creator-earnings-of-truth`: Dashboard and Creator reports money against
  OnlyFans Statistics. `seed/earnings` writes OF's daily net per Creator for
  `--set history_days=` (130) and the ledger rows the DB caught (a trickle before the
  Creator was connected `--set connected_days=` (9) ago, most since, some today).
  Before the history job: API checks and, with UI, the Dashboard (This month) and
  Creator reports (Last 30 days) screenshots. Then `--users` owners (`actors/reports`)
  read the reports while `POST /__slop/of-stats-tick` runs job passes until the history
  is in, and again after. Checks: reads per pass bounded, 400 days stored per Creator,
  the last pass reads nothing; before the history, unknown days are reported
  (`history_missing_days`) and growth shows "-"; after, totals by kind, every trend day
  and each Creator's net == OF's complete days + today's ledger, the prior window
  (growth) is OF's with no unknown day, a window older than OF's kept history says its
  days are unknown, Employee sales unchanged, net/gross 0.8; UI totals == API; p95 per
  route vs the budget and the last green run. Every money check reads max(OF, ledger)
  per Creator, UTC day and category. Two seeded disagreements: "DB sale not erased by
  OF zero day" (OF charts $0 on a day the ledger holds a pending $14 PPV message, as on
  app.inflowwww.com 2026-10-21; API and, with UI, Creator reports / Creator performance
  on that day, screenshots `creator-*-zero-day-*`) and a sale at 23:30 UTC-7 read with
  the report zone America/Los_Angeles (on its local day once, not again on OF's next
  UTC day). The fake answers as OF measured 2026-10-25: every asked category, zero or
  not, PPV messages under `chat_messages`, a `total`. Bypasses: OF Statistics faked from
  `of-statistics.json` (0.3 s per read, a guess), the job's timer and boot grace via the
  tick hook, owners go straight to the relay. Faults: `of-zero-erases-db-sale` (the
  scenario's: OF's day replaces the ledger's, as shipped in f96535be0) and
  `reports-ignore-of-earnings` (the ledger-only reports) turn only their checks red.
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
  never pressed or blue) turns only the chip-order and sort-active checks red. Search: on one
  Creator the owner types a Fan's name 100 ms a key (a guess at a fast typist); the `/chats`
  requests carrying a `query` (counted at the browser's wire, where `/chats` is answered) must
  be exactly one, for the box's text, and the rows its matches (screenshots of the typed box
  and the settled list). Fault `fan-search-every-keystroke` (`browser=`: FanList's debounce
  timer at 0 ms, as before 2026-10-28) turns only the search check red.
- `2026-10-26-mobile-gestures`: the owner on a phone (390x844, `owner_browser(touch=True)`,
  swipes as Chromium touch input via `ui.swipe`, CDP `Input.dispatchTouchEvent`). Dashboard:
  a vertical drag, a swipe from the OS edge zone (x < 24px) and a drag that turns vertical
  then ends sideways open nothing, a swipe right
  from mid-screen opens the nav menu (URL unchanged), a swipe left closes it. Messages Pro:
  no menu swipe; opening a chat adds one same-URL history entry (`useChatBackEntry`), back
  returns to the Fan List still on Messages Pro and a second back leaves; Forward onto
  that entry stays on it (unmarked, no bounce) and the next Forward reaches the later page; a cancelled
  sideways swipe leaves the Thread pinned ("Jumping to latest") and a vertical drag releases
  it; the Thread's swipe right returns to the Fan List through that entry; Fan insights'
  swipe right closes only Fan insights; a reload with a chat open lands on the Fan List with
  no chat entry left. Desktop (1600px, touch input): nothing opens or closes, no history
  entry. No 5xx from the relay. No volume, so no budget (settle times are metrics). Bypasses:
  no phone OS, so iOS's / Android's own edge-back is not in the loop (`history.back()` stands
  in for it; the edge-zone check proves only that the page ignores such a touch); `/api/of/*`
  held. Fault `mobile-chat-no-history-entry` (client: no `pushState` when a chat opens) turns
  only the three checks of that entry red (back, Forward, the Thread swipe through it);
  `mobile-chat-forward-bounce` (Forward onto the entry goes back again) only Forward;
  `mobile-swipe-ignores-turn` (a sideways lock ignores a later vertical move and the scroll)
  only the turned drag.
- `2026-10-28-scoped-reads-fanout`: the shell's per-Creator scoped reads fired all at once now
  that `app/lib/relay.ts` sends them `cache: "no-store"` (the phone-load work). One Agency, 50
  Creators with captured sessions, OnlyFans on `lib/of_wire.py` (`OF_WIRE`, 400 ms a call,
  `--set of_ms=`). `--users` clients, at most 5 (`--set clients=`; `--users` above 5 still
  runs 5), each its own pool on the owner's session, fire at once on a cold relay `users/me`, the Fan List's first `chats` page
  and `notifications/count` for every Creator; then the relay is restarted and one client
  reads the same set Chrome's old way (each URL Creator after Creator). The checks: every
  call answered 200, each `users/me` is the asked Creator's, OnlyFans saw exactly one call per
  Creator per read in the burst (single-flight), `lib/of_wire.py` saw only signed calls it
  models; per-read p95 (recorder stages `burst` / `serial`) and per-client wall in
  `metrics.json`; budget: burst p95 vs the last green run. The cap of 5 hides a measured relay
  cliff between 10 and 20 cold clients: 10 pass
  (`20261028T072716Z-2026-10-28-scoped-reads-fanout-c663`), 20 leave 1725-2045 of 3000 reads
  past the client's 30 s timeout (`…-0f18`, `…-d1a7`, and `…-6729` started on a quiet host),
  in the relay's threads and DB pool, not OnlyFans (single-flight held); `--set clients=20`
  reproduces it. Even at 5 every read waits in the DB pool (p95 1 s of the ~2 s read p95).
  `--scale` does not change this scenario (the reads never touch the seeded fans). Bypasses: the clients are httpx pools with every request in
  flight (HTTP/2's shape, the worst case), not browsers; OF's chat list and bell are empty;
  the 400 ms is a guess at OF behind a residential proxy. Fault
  `relay-cache-no-single-flight` (each relay_cache miss its own lock) turns only the
  single-flight check red.
- `2026-10-28-dead-proxy-interactive-reads`: a Creator's proxy (`lib/proxy_wire.py`) dies
  while people read 5 Creators through it: interactive reads 502 within 1500 ms after 2
  tries, background reads keep the 5-try retry, only the latter count toward bad and no
  confirm probe runs inside the blip. Checks, bypasses and faults
  (`interactive-reads-full-proxy-retry`, `interactive-failures-counted`,
  `relay-cache-failure-not-shared`): the scenario's docstring.
- `2026-10-28-proxy-failover`: an Inflowwww pool proxy dies under 12 bound Creators
  (docs/adr/0030): surfaced, confirmed, its Creators moved to a healthy pool proxy within
  30 s (`PROXY_RECHECK_S=2`), a login during the outage bound once to a healthy one, no
  send duplicated; revived, it takes the next Creator; all dead, nobody moves and a login
  is still saved and bound. Checks, timeline, bypasses and faults
  (`proxy-failover-never-moves`, `proxy-recheck-never-runs`,
  `pool-assign-drops-unanswered-login`): the scenario's docstring.
- `2026-10-28-dashboard-load`: the owner opens the Dashboard on a phone ~190 ms from the
  host (production build behind `lib/wan.py`, OnlyFans on `lib/of_wire.py`): Total
  earnings paints from the saved snapshot before any answer and never waits on OF, the
  session-less Creator's card reads no OF. Checks (incl. the saved-Total and offline-card
  checks), budgets, bypasses and faults (`dashboard-total-waits-of-reads`,
  `dashboard-total-not-saved`, `dashboard-offline-creator-reads-of`): the scenario's
  docstring.
