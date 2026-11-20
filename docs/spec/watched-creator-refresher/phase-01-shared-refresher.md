# Phase 01 — Shared refresher

Plan: `.scratch/watched-creator-refresher/goal.md` (D1–D5, D8–D10, netting rule, Phase 1, Q1 verdict). ADR-0042 (this
Phase), ADR-0044 (netting), ADR-0031 (View lease, App-open warm). Study: `.scratch/all-models-of-budget/REPORT.md` on
`study/all-models-of-budget` (§2, §3, row 5). Labels: m = measured, i = inferred, g = guess. Rung = the ladder rung
that decided it. Glossary: CONTEXT.md "Shared Creator freshness", "Fetch diet".

**Objective.** With the Knob on, the Relay reads each Open-tab Creator that is no Dead session at most once per Cycle
for every Employee and tab, keeps one per-Creator snapshot (Last refresh `at`, Cycle, Live connection state, values),
hands it to every tab at first paint, on reconnect and on change, and the App-open warm nets against the same Last
refresh.

## Problem Statement

A chatter under All Models sees numbers that age on their own tab's clock. Each tab reads its Creators' counts itself:
a later open costs 62–92 OF calls at 10 Creators (m, study §2) and ~230–370 at 50 (i), because the App-open warm only
reuses a Creator for 30 s (`service/app_open_warm.py:73`) and one 10-Creator warm takes 38 s (m). Three chatters on
the same Creators pay three times for what is one truth. The bell under All Models sums whatever counts this tab
happens to hold (`app/hooks/useOfNotifCount.ts:80-90`, PR #879): an unleased Creator's count moves only on its next
`creator_warmed` (`app/lib/ofReadGate.ts:5-8`). Nothing in the Relay knows, per Creator, when it last confirmed what
tabs show, so no tab can say how old a number is, and Phase 2 has no whole-inbox Unread total to seed from.

## Solution

One Relay loop, the Shared refresher, off by default. It watches who has a tab open (live Event stream subscribers and
the Creators they may see), skips Dead sessions, and for each such Creator makes one small read per Cycle: every
~120 s while the Creator holds a View lease, every ~10 min otherwise, never more often than once a minute. Reads go
through the same per-exit gate as the App-open warm, at background priority, spread out, backing off on 429. A Creator
the warm just read waits for its next slot; a Creator the refresher read within its Cycle makes the warm answer
`reused`. Each tab gets a per-Creator snapshot (when the Relay last confirmed it, its Cycle, whether its Live
connection is up, down or a Dead session, and the values other Phases hang on it) on first paint from the accounts
lists (owner's and chatter's), a new `creator_refreshed` event when anything in it changes, and the confirmation time
on a stream `ping` every 20 s even on a busy stream. The one read is `/users/me`; the bell may take its count from it
once the owner's bell-pair check passes (Knob, off). Cost: ~9.5 OF calls/min at 50 Creators with 10 on screen, ~12/min
with Phase 2's reads, inside D8's ~14 (set budget below; i/g), a new Cost group, one Baseline run re-pin after deploy.
Phases 2 and 3 build only on `### Contract (frozen for Phases 2 and 3)`.

## User Stories

1. As an owner, I want the refresher off unless its Knob is set, so that deploying the code changes nothing until I
   turn it on.
2. As an owner, I want turning the Knob off to restore today's warm, bell and event behaviour exactly, so that the
   kill switch is a full undo.
3. As the Relay, I want an Open-tab Creator to be one some live app tab's Event stream may see (its clamp), so that
   Creators nobody has open cost nothing (D1).
4. As an owner running the desktop notifier, I want its always-on `/events` stream not to make every Creator Open-tab,
   so that the refresher does not run around the clock for a window nobody looks at.
5. As the Relay, I want an unclamped subscriber (the anonymous escape hatch) to contribute no Open-tab Creator, so that
   a test or script stream never widens the set.
6. As the Relay, I want Watchers never Open-tab, so that fan accounts are never refreshed.
7. As the Relay, I want a Dead session, a deactivated Creator or one with no session never read, so that it is never
   chased (D2).
8. As a chatter, I want a Dead-session Creator still to carry a Live connection state of "dead" in its snapshot, so
   that Phase 3 can mark it.
9. As the Relay, I want a refresher read that answers a dead-session error to flag the Creator itself (no request is
   in flight, so `_proxy` cannot), so that its next tick skips it.
10. As a chatter, I want a Creator I have on screen (View lease) refreshed every lease cycle (~120 s), so that what I
    look at is at most ~2 minutes old (D3).
11. As a chatter, I want every other Creator my tabs can see refreshed every tab cycle (~10 min), so that switching to
    it shows bounded-stale truth (D3).
12. As an owner, I want no Creator read by the refresher more than once per 60 s whatever the Knobs say, so that a bad
    Knob cannot hammer OF (D3).
13. As an owner, I want a Creator read once per Cycle however many chatters and tabs see it, so that cost is flat in
    chatters (D4).
14. As the Relay, I want at most one refresher read per Creator in flight, so that a slow read is never doubled.
15. As the Relay, I want the refresher's reads to share the App-open warm's per-exit queue, so that warm and refresher
    never burst one proxy exit together.
16. As the Relay, I want a queued refresh absorbed by a queued warm of the same Creator, so that one Creator is never
    queued twice on its exit.
17. As the Relay, I want the refresher's reads at background priority on the Creator's background lane, so that a
    click never waits on it.
18. As the Relay, I want a 429 to hold the whole exit for OF's asked wait and to push that Creator's next try up the
    Backoff ladder, so that a hot proxy cools down.
19. As the Relay, I want Creators' slots to drift apart instead of firing together, so that reads spread evenly over
    the Cycle.
20. As the Relay, I want a restart's first reads spread over the first minute, so that a deploy with tabs reconnecting
    is no burst.
21. As the Relay, I want a refresher job that hangs past a deadline to release its exit, so that one stuck Creator
    cannot stall the warm queue for every other Creator on that proxy.
22. As a chatter, I want a Creator the refresher read within its Cycle to make my open's warm `reused`, so that a later
    open costs about what an in-window open costs (netting rule, ADR-0044).
23. As the Relay, I want a Creator the warm just read to wait for its next slot, so that warm and refresher never read
    the same Creator twice in one Cycle (ADR-0044).
24. As the Relay, I want one Last refresh per Creator, written by whichever of the warm or the refresher landed, so
    that there are not two clocks.
25. As the Relay, I want the warm, while the refresher is on, to read `/users/me` too, so that a warm is a full Last
    refresh and the snapshot's values never age past a Cycle because the warm skipped one.
26. As a chatter, with `SHARED_REFRESHER_BELL=me`, I want the bell under All Models to show each Creator's
    notification count as of its last Cycle, so that it is current without my tab reading it.
27. As Phase 2, I want the Cycle to read `/users/me` through the OF client, so that my own client observer sees the
    body and the Unread total costs no extra call (Q1 polling fallback).
28. As Phase 2, I want an open values slot in the snapshot, so that I can publish the Unread total with no event of my
    own.
29. As Phase 2, I want a thread-safe way to say a value changed without a read, so that a read flip or a DM can move
    it from any thread.
30. As Phase 2, I want every page-0 window read (Cycle or warm) to go through one hook I can register, at the
    refresher's Caller kind and pacing, so that I can diff it.
31. As the Relay, I want the chats window re-read only when the Live connection is down or reconnected since the
    window's last read (or a values contributor asks), so that the list is not polled for what the Live connection
    brings.
32. As the Relay, I want to publish a Creator's snapshot only when its values, Live connection state or Cycle changed,
    or when it first becomes tracked, so that tabs are not churned (D5).
33. As Phase 3, I want the snapshot's `at` to reach every tab even when nothing changed, so that the data age is right.
34. As Phase 3, I want the Live connection state to reach every tab when the socket drops with no read, so that the
    "no live connection" mark is timely.
35. As Phase 3, I want `at`, `cycle_s`, `live`, `live_since` and the Relay's `now` at first paint, for an owner and a
    chatter alike, so that the first screen shows age and marks before any event.
36. As a tab that reconnects, I want the events I missed replayed and a full refetch on `resync`, so that my snapshot
    is never silently old.
37. As a tab, I want a newer snapshot never overwritten by an older one (persisted cache, late answer), and a
    Creator whose accounts row lost `freshness` dropped from my store, so that freshness only moves forward and a
    switch-off brings back today's screen.
38. As a tab, I want `creator_refreshed` not to re-read the rail's money lists or arm unleased reads, so that the event
    adds no OF call.
39. As a tab, I want a refresher-covered Creator's notification count not polled by age, so that my tab stops paying
    for a count the Relay already reads.
40. As an owner, I want the refresher's calls in their own Caller kind and Cost group, not `purchases_money`, so that
    the sanctioned add is visible and cannot hide a purchases-poll regression (D8).
41. As an owner, I want the re-pin of the Baseline run written as a runbook, so that I can run it after deploy.
42. As an owner, I want a WATCH.md line and a check that rates the refresher's calls against D8 for 3 days, so that
    a runaway is caught while the Baseline run rebuilds.
43. As an owner, I want the whole set's calls/min at 10, 30 and 50 Creators in one table against D8's ~14/min, so
    that the default provably fits and every costlier option is a Knob I turn on.
44. As an owner, I want the bell's switch to `/users/me` gated on my own bell-pair check (0 Relay calls), so that the
    bell never takes an unproven number.
45. As an owner on 8 vCPU / 31 GB, I want the loop's CPU, memory and fan-out stated at 50 Creators and several
    chatters, so that it fits D9.
46. As an owner, I want all refresher state in Relay memory, so that there is no migration and a restart rebuilds it.
47. As a developer, I want the scheduling decision a pure function with table tests, so that tiers, floor, netting,
    skips and back-off are proven without a Relay.
48. As a developer, I want the tab-side snapshot a pure reducer with vitest tables, so that seeding, events and
    heartbeats compose without coupled `useState`s (CLAUDE.md).
49. As a developer, I want the slop scenario to name the metrics that prove flat cost in chatters, staleness within a
    Cycle and the open-after-reuse drop, so that a run (owner opt-in) can falsify the Phase.
50. As an owner, I want refresher reads to stop within a tick once the last tab closes, and a queued job to re-check
    at its turn that its Creator is still tracked, readable and not refreshed meanwhile, so that nothing is read for
    nobody.
51. As Phase 3, I want a cache hit or a discarded write-back never to move `at`, so that the age never claims a
    confirmation OF did not give.
52. As the inbox's first paint, with `SHARED_REFRESHER_BELL=me`, I want a covered Creator's bell count served from
    the snapshot, so that an open does not pay one count read per Creator.

## Implementation Decisions

- **Owns.**
  - Relay: new `shared_refresher_decide` (pure) and `shared_refresher` (shell: loop, state, reads, publish,
    accessors); `app_open_warm` (one public entry for refresher jobs on its per-exit gate, the shared Last refresh in
    its reuse decision, the extra `/users/me` read); `events` (`open_tab_accounts()`, the app-tab mark on a
    subscriber, the `fresh` ping on its own 20 s timer); `events_decide` (`creator_refreshed` in `SSE_TYPES`, `ANY_SCOPE_TYPES`,
    `COALESCE`); `events_wire` (ping carries `fresh`); `server` (the refresher's reads helper beside
    `app_open_warm_reads`, a background priority class for requestless refresher reads, the `/events` route passes
    the app-tab mark, loop start/stop below the test-mode guard); `accounts_admin_api` (`/admin/accounts` rows gain
    `freshness`); `chatters` (`/chatter/me/accounts` rows gain `freshness`); `screens_api` (the inbox bundle's
    `notificationCounts` for a covered Creator from the snapshot).
  - App: new `lib/creatorFreshness.ts` (pure reducer) and `hooks/useCreatorFreshness.ts` (reader); `useAccounts`
    (seed), `useAccountStateEvents` (`creator_refreshed`), `lib/events.ts` (ping `fresh`), `lib/ofReadGate.ts` and
    `hooks/useOfNotifCount.ts` (count gate for covered Creators).
  - Sweep: `scripts/proxy-health/of_calls.py` (`OF_COST_GROUPS` entry), `scripts/proxy-health/watch.py` (one Watch
    check).
  - Slop (after `fix/bg-lane-money-deadlock` lands the scenario): `2026-11-20-all-models-shared-inbox` gains the
    metrics, checks and fault under Testing Decisions.

- **Interfaces** (Phase 1's own; what Phases 2 and 3 may use is `### Contract (frozen for Phases 2 and 3)` below).
  - `shared_refresher_decide` (stdlib only, no clock, no I/O):
    - `cycle_s(leased: bool, aid, knobs) -> float`: the Creator's own period, `max(FLOOR_S, tier × (1 − SPREAD ×
      h(aid)))`, tier = lease or tab cycle, `h` a stable hash in [0, 1), `SPREAD` 0.1, `FLOOR_S` 60 (constants, not
      Knobs). This period is the Creator's Cycle everywhere: published `cycle_s`, the warm's reuse window, staleness.
    - `plan(state, inputs, knobs) -> (state', effects)`. Inputs per tick: `now`, `tracked` (Open-tab Creators),
      `readable` (tracked ∩ live ids, OF platform), `leased`, `ws_since` (Creator → socket connected-at or None, on
      the same monotonic clock as `last` and `window_at`), `dead`, `warm_pending`, `in_flight`. Effects: `Read(aid)`,
      `Publish(aid)`. A Creator is due when it is readable, not in flight, not warm-pending, not held by back-off, and
      `now >= due_at(...)`. `tracked` empty → no effect but `Publish` of `live` flips.
    - `due_at(last, cycle, aid, first_seen) -> float`: `last + cycle`; never read (`last` None): `first_seen + h(aid) ×
      FLOOR_S`. `last` = Last refresh; a failed attempt holds the Creator ≥ `FLOOR_S` (`after_read`), so refresher
      attempts, ok or not, are never under `FLOOR_S` apart (the floor governs attempts, not only successes).
    - `after_read(state, aid, outcome, now, asked_wait) -> state'`: ok writes Last refresh and clears the ladder;
      failure keeps `at`, holds the Creator `max(FLOOR_S, purchase_poll_decide.ladder_s(n))`.
    - `window_due(window_at, ws_since, asked) -> bool`: the socket down now, or connected after `window_at` (the
      window's own last read, `accounts_admin_api._chats_window_fetched_at`), or a contributor asked. No window held
      (`window_at` None) is not due: an open then reads page 0 itself, a cache miss as today. Asked in the job after
      `/users/me` landed, not at plan time.
    - `live_of(aid, ws_since, dead, pumped) -> "up" | "down" | "dead" | None` and `changed(prev, next) -> bool`:
      Contract 2 and 3.
    - `values_of(me_body, bell) -> dict`: `{"notif_count": notificationsCount}` when `bell == "me"`, else `{}`.
  - `shared_refresher` (shell):
    - `ENABLED`, read once at import; `start()` / `stop()` from the server's lifecycle when enabled.
    - `note_refresh(aid, me_body, at)`: the warm's landed `/users/me` writes the one Last refresh, `at` = its ask time;
      a cache hit or a discarded write-back (`relay_cache` latest-wins) writes none.
    - `last_refresh(aid) -> float | None`, `cycle_for(aid) -> float`: what the warm's reuse decision reads.
    - `snapshot_rows(account_ids) -> {aid: Freshness}`: both accounts lists and the inbox bundle;
      `heartbeat(accounts) -> {aid: at}`.
    - `register`, `note_values`, `set_window_reader`, `window_read`: Contract 8 and 9.
  - `app_open_warm`: `refresh(aid, run)` enqueues a refresher job on the Creator's exit (one entry per Creator; a warm
    absorbs it); `pending(aid) -> bool`. With the refresher on, `reuse_decision` (from `fix/all-models-open-cost`)
    takes `warmed_age` = age of the shared Last refresh, `fresh_s` = the Creator's Cycle and `ws_kept` = True (the
    window invariant under Netting replaces the socket test). Off: unchanged.
  - `events.open_tab_accounts() -> frozenset[str]`: the union of the clamps of live subscribers marked as app tabs.
  - App `lib/creatorFreshness.ts`: `reduce(state, action)`; `Action = { type: "seeded", rows, now, receivedAt } |
    { type: "refreshed", body, receivedAt } | { type: "confirmed", fresh, now, receivedAt } | { type:
    "identityChanged" }`; `of(state, aid) -> Freshness | null`; `covers(state, aid) -> boolean` (a held
    `values.notif_count`). Rules: Contract 5 and 6. State in the React Query entry `["creator-freshness",
    principalId]` via `setQueryData`; not persisted.
- **Schema.** None. All state in Relay memory (ADR-0042, plan "in-memory state"); a restart forgets it, the first
  reads after it are spread over `FLOOR_S`.

- **Open-tab Creator.** `events._Sub` gains `tab: bool`, set by the `/events` route for a stream marked `lease=1` (the
  app, `app/lib/eventBusReducer.ts:163`) or, unmarked, sent by a browser page (a Referer: `legacy_stream_ids`'
  Referer test, `service/view_lease.py:100-107`, without its exclusion of marked streams).
  `open_tab_accounts()` = union of `sub.accounts` over subscribers with `tab` and `accounts` not None, minus
  `account_registry.is_watcher`. `tracked` = that set. `readable` = `tracked` ∩ `transaction_ingest.live_account_ids()`
  (`service/transaction_ingest.py:1577-1588`: drops dead, deactivated, no session), OF platform only.
  - Edges. Recomputed every tick from live subscribers: the last tab closing empties `tracked` within one tick, and a
    queued job re-checks at its turn (Pacing). An `assignment_changed` or `sessions_revoked` ends the stream
    (`events_decide.ENDS_STREAM`), so a revoked clamp leaves `tracked` and the reconnect brings the new one. A View
    lease without a tab stream (a stream between reconnects) tracks nothing; a lease only picks the tier. A Creator
    re-entering `tracked` keeps its Last refresh (no burst read) and is published once. The purchases poll's own
    cadence is untouched by any of this.
  - The desktop notifier opens `/events?scope=all` unmarked and with no Referer, always on (`desktop/main.js:950`).
    Counting it would make every Creator of its owner Open-tab around the clock. Excluded here; needs-human (Review):
    D1's "a live `/events` subscriber who can see the Creator" read literally includes it.
  - ASSUMPTION: Fansly Creators are tracked for `live` = null but never read (rung 5; `of_ws.connected_since` has no
    stamp for Fansly, `service/of_ws.py:288-292`, and the count / me shims are unverified); overturned if the Fansly
    shim answers both reads.
  - Hidden browser tabs keep their stream (`app/lib/events.ts:124,150`), so they count. D1 says "a live `/events`
    subscriber" (rung 2).

- **Tiers, Cycle, floor.** Lease cycle when `view_lease.is_leased(aid)` (`service/view_lease.py:140`), else tab cycle.
  Knobs `SHARED_REFRESHER_LEASE_CYCLE_S` (120) and `SHARED_REFRESHER_TAB_CYCLE_S` (600, never below the lease cycle),
  both clamped to `FLOOR_S` 60. Each Creator's Cycle is its own period, 0.9–1.0 × the tier (`cycle_s`), so "once per
  Cycle" and "fresh within its Cycle" use one number: the scheduler never reads a Creator inside the period it
  publishes and the warm honours. Staleness stays within one Cycle plus queue wait. Never under 60 s.
  ASSUMPTION: `SPREAD` 0.1 (periods differ per Creator, so slots drift apart; mean cost +5 %, i) (rung 5); overturned
  if slop shows slots still bunched on one exit.

- **Loop.** One asyncio task, tick 5 s (a constant), started in the server's startup below the test-mode guard
  (`service/server.py:1636-1646`, with the other network loops) and stopped at shutdown. Each tick:
  `open_tab_accounts()`, `live_account_ids()`,
  `view_lease.leased_ids()`, `of_ws.connected_since` per tracked Creator, `app_open_warm.pending`; then `plan`; then
  each `Read` becomes `app_open_warm.refresh(aid, job)` and each `Publish` a `creator_refreshed`. A Creator whose socket
  drops is seen within one tick (5 s) and published with no read (Phase 3's need). Phase 3 owns any display debounce.
  ASSUMPTION: tick 5 s (g); overturned if the tick's DB reads (`live_account_ids` reads the dead map and deactivated set)
  show in relay CPU.

- **A Cycle's reads** (one background walk, `of_pacing.walk(aid, "shared_refresher", run)`, so Caller kind
  `walk:shared_refresher`. Pages paced 1 s per Creator with one 429 retry, `service/of_pacing.py:200-222`. Each read
  goes through the route's own `relay_cache` entry and coalesce key, as `app_open_warm_reads` does via `_warm_fetch`,
  `service/server.py:4209-4238`, with `bypass=True`: the Cycle's reads are counted as real reads in the budget, and a
  cache hit has no read time, so it could not confirm anything (rung 1: `relay_cache` entries hold `(value,
  expires_at)` only, `service/relay_cache.py:300-306`). `at` = the job's ask time, and moves only when every read
  landed and its write-back was kept (`peek_fresh` after the read finds it); a discarded write-back (an invalidation
  landed meanwhile, latest-wins) leaves `at` and the values unchanged, and the Creator is due again after `FLOOR_S`.
  - Background, really. Requestless reads are classed `user` for coalescing and admission today
    (`server._current_priority` → "user" outside a request, `service/server.py:2537-2545,2519-2520`), so a click's
    read could join a refresher flight that waits on the background lane. The reads helper sets a context flag that
    makes `_current_priority()` answer "background" inside the refresher's walk (coalesce class, `_bg_admission`), and
    runs the window read too under `_priority_lane_background(aid)` (`rewarm_roster_count` takes no lane today,
    `service/accounts_admin_api.py:430-442,594-605`). Rung 1.
  - Dead session. `_proxy` flags a Dead session only when it resolves the account from a request
    (`service/server.py:2637-2643,2680-2688`), and `rewarm_roster_count` skips the route handler that flags it
    (`service/accounts_admin_api.py:540-552`). So the reads helper itself checks a failed read's
    `account_health.is_session_dead_error(exc.__cause__ or exc)` and calls `account_health.mark_session_dead(aid,
    reason)` (plus `_invalidate_client`), as `accounts_admin_api.py:545-549` does. Rung 1.
  1. `/users/me`, every Cycle: `chatMessagesCount` (Phase 2's observer takes it in the OF client, Contract 8) and
     `notificationsCount`. Rung 1: the only OF read carrying a chat counter beside a notification counter
     (`app/lib/__fixtures__/of/avatar-menu-me.json`, `app/lib/ofMe.ts:34-37`). It also primes the `users_me` entry that
     tabs' profile reads hit (60 s TTL, `service/server.py:3038-3039`).
  2. Only when `window_due` (asked after read 1): the chats window through `window_read(aid)` (Contract 9; 25 rows =
     3 calls typical at OF's 10-row cap, ≤ 5 + 1 retry, `service/chats_page.py:129-134`). It rewarms the Fan List's
     page 0 and the roster count.
  - Decision: 1 read per Cycle by default (D8: the set's table, Contract 12). `/users/notifications/count` (the bell's
    `all`, `service/server.py:4131-4148`) is not read: on the lease tier it adds ~5/min at 50 and pushes the set over
    D8 (i). Not built (YAGNI); the bell takes `notificationsCount` instead once proven (Bell, below).
  - Dead session: flagged by the reads helper (above); the next tick's `readable` drops the Creator, `live` = "dead",
    `cycle_s` null, published.

- **Bell (Knob `SHARED_REFRESHER_BELL`, `0` default | `me`).** `0`: the bell as today (an unleased Creator's count
  already moves only on its `creator_warmed`, `app/lib/ofReadGate.ts:5-8`, so nothing regresses). `me`: `values.notif_count`
  = the Cycle's `notificationsCount`, 0 added calls; the inbox bundle answers a covered Creator's
  `notificationCounts` from the snapshot (`service/screens_api.py:396-397` reads `/count` per Creator per first paint
  today); the tab's count gate and bell writes (Tab side) apply. `covers` = a held `notif_count`.
  ASSUMPTION (evidence blocked): `notificationsCount` equals `/count`'s `all` (g: OF's left-nav and All-tab unread
  notification counts). Gate: the owner's bell-pair check (Acceptance, 0 Relay calls); `me` stays off until it passes.

- **Pacing and back-off.** Jobs ride `app_open_warm`'s per-exit queue (`service/app_open_warm.py:9-13,201-256`): one
  Creator at a time per exit, `APP_OPEN_WARM_GAP_S` after the last read there, exits in parallel. One entry per
  Creator: a queued warm absorbs a refresh (the warm reads more), and a queued refresh never displaces a warm.
  - At its turn a refresh job re-checks, as a lease-gain job does (`service/app_open_warm.py:178-181`): still tracked,
    still in `live_account_ids()`, and no Last refresh landed since it was planned; else it is dropped unread. A warm
    that arrives while a refresh is in flight (popped, so not absorbed) queues behind it as today; its `/users/me`
    then still bypasses (Netting) and the window is re-read: a residual double read only when an open meets a slot
    (g, rare), accepted (rung 5).
  - 429. A 429 that `of_pacing`'s one retry absorbed held the exit already: the job slept OF's wait on it. A 429 that
    still fails the job: the wait comes from the error's cause (`_proxy` raises `HTTPException(...) from` the
    `OFAPIError`, whose response keeps `Retry-After`; `of_pacing.upstream(exc.__cause__)` then `asked_wait(header,
    allow_s(body))`, `service/of_pacing.py:133-175`), else `FLOOR_S`. The exit's `free_at` moves to now + that
    wait, because 429s follow the proxy IP (m, `service/of_pacing.py:49-55`). The Creator is held `max(60,
    ladder_s(n))` (30 s doubling to 900 s, `service/purchase_poll_decide.py:127-129`). Other failures: the ladder
    only. `at` is not moved, so the age shows.
    ASSUMPTION: the purchases poll's ladder is reused for the Creator hold (rung 3); overturned if the sweep shows
    refresher 429s clustering per Creator, not per exit.
  - Deadline. The walk runs as its own task; the exit worker waits on it with `asyncio.wait({task}, timeout=30)`, never
    `wait_for` (which would cancel the walk and lose its result, `service/relay_coalesce.py:149-170` keeps only the
    upstream flight alive). On timeout the exit is released and logged `shared_refresher_job_timeout`; the task keeps
    running, the Creator stays in flight, and the task's done-callback applies its result. The next job on that exit
    may then overlap the hung call: accepted, a hung read is a dead proxy's, and holding the exit stalls every other
    Creator on it.
    ASSUMPTION: 30 s (g); overturned if a healthy job takes longer in the sweep's log.

- **Netting with the App-open warm (ADR-0044).** One Last refresh per Creator, kept in `shared_refresher`.
  - The warm's landed `/users/me` calls `note_refresh`. With the refresher on, the warm reads `/users/me` too,
    bypassing the cache (as the refresher), so a warm is a full, true Last refresh (else a warm would push the
    refresher's next `/users/me` a Cycle past the last one, or stamp a cached body as new).
  - What a Last refresh certifies. The warm reads more than the refresher (feed, chats window, two money lists, count:
    `service/app_open_warm.py:33-41`, `service/server.py:4221-4238`), so "reused" must not rest on reads the refresher
    skipped. The invariant: at every Last refresh the chats window was read either in that job or since the socket
    last connected (`window_due` on the window's own read time, above), so a held window is WS-kept or fresh, and
    one past its list TTL (600 s + SWR) is re-read by the open's own page-0 read, as on an in-window open; the feed
    is the purchases poll's (every live Creator at ≤ `purchase_poll_decide.SLOW_S`, 300 s); the money lists are 30 s
    entries a tab re-reads through the shared cache when it shows them. Rung 1 on those reads.
  - The warm answers per ADR-0044: `reused` when the Last refresh is within the Creator's Cycle. Mapped onto the
    sibling's `reuse_decision` (`fix/all-models-open-cost`, `service/app_open_warm.py:163-174` there, seen at
    a99c91eeb): `warmed_age` = age of the Last refresh, `fresh_s` = the Creator's Cycle, `ws_kept` = True; its other
    branches stand (`pending` → `reused`, under `REUSE_S` → `reused`, a failure under `REUSE_S` → `skip`, else
    `start`). A socket that drops after the Last refresh leaves the window short of DMs until the next slot (≤ one
    Cycle): ADR-0044's stated cost ("fresh within its Cycle").
  - The refresher plans from Last refresh, and `warm_pending` Creators are never due.
  - Assumed of `fix/all-models-open-cost` (seen in its worktree at a99c91eeb, not merged): that signature,
    `FRESH_S` = min(Knob, 300 roster TTL, `PURCHASES_POLL_SLOW_S`) (`:81-82` there), and `users_me` cached under
    `relay_cache` key `("users_me",)` with a `max_age` reader. Phase 1 feeds that decision; it does not fork it.
    With the refresher on, `fresh_s` is the Creator's Cycle (up to 600 s), past the sibling's 300 s cap; the window
    invariant above is what makes that safe.
    ASSUMPTION: the sibling lands first with that signature (in flight); overturned if it changes it, then only the
    argument mapping changes.
  - The warm's extra `/users/me` is +1 read per started warm in `walk:app_open_warm` (`purchases_money`). Opens already
    read `/users/me` per Creator (study §2: 0–10 per later open), and those now hit the primed entry (net ≈ 0, i).
    ASSUMPTION: rung 5; overturned if the sweep shows `walk:app_open_warm` rising after deploy.

- **Change detection.** Per Creator the shell keeps the last published `Freshness`; `changed` is Contract 3 (a lease
  gain or loss changes the Cycle Phase 3 measures against). A landed Cycle with identical values moves `at` and
  publishes nothing; the `fresh` ping carries `at`.

- **Tab side.**
  - `useAccounts` dispatches `seeded` with each network answer (Contract 4–6). `lib/events.ts` dispatches `confirmed`
    from each ping's `fresh`.
  - `useAccountStateEvents` handles `creator_refreshed`: it dispatches `refreshed`, then (bell `me`) writes the store's
    `values.notif_count` (after the reducer, so an older event the reducer rejected writes nothing) into
    `["of-notif-count", aid]` (`setQueryData`, as `creator_warmed` does, `useAccountStateEvents.ts:197-204`). It never
    calls `armRead` and never invalidates `notif-list` (rung 1, above).
  - `useAccounts`' `seeded` writes each covered Creator's `notif_count` into `["of-notif-count", aid]` the same way,
    so the All Models bell (it sums those entries, `app/hooks/useOfNotifCount.ts:85-89`) shows the seed. One helper
    does both writes: "store → bell entry for these Creators".
  - Count gate: `useOfNotifCount` uses `once` (no age refetch) for a Creator `covers` says is fed, even when leased.
    Its value arrives by event, its first paint by the seed's `notif_count`.
    ASSUMPTION: rung 5, the smallest change that removes the tab's count poll; overturned if a scoped bell must stay
    fresher than the lease cycle.
  - No component gains state; the bell UI is unchanged.

- **Knobs** (read once in `shared_refresher`, `env_knob.env_float` like every other): Contract 11. `SHARED_REFRESHER`
  0 = off (default; rung 4): no loop, no field, no event, no ping field, the warm on the sibling's rule, the client
  unchanged (nothing `covers`).

- **Caller kind and Cost group.** Caller kind `walk:shared_refresher` (precedent: `walk:app_open_warm`,
  `service/app_open_warm.py:33,173`). New Cost group `"shared_refresher": ["walk:shared_refresher"]` in
  `of_calls.OF_COST_GROUPS` (`scripts/proxy-health/of_calls.py:23-32`). Phase 2's window reads land here too.
  - Why not `purchases_money`: D8 names a new caller group (rung 2). And on numbers it would hide: the sweep of
    2026-11-20T12:41Z rates `purchases_money` at 487.3/h against a pinned 1,469.6/h (m). +~730/h (12.1/min, g) lands at
    ~1,220/h, under the ×1.25 trip (1,837/h): the sanctioned add would vanish into the diet's savings and mask a later
    purchases-poll rise (i).
  - As its own group with baseline 0 it trips `of_calls_vs_baseline` on its first rated run (`n > 1.25 × 0` and
    `n − 0 ≥ 5/h`, `of_calls.py:605-607`). Hence the re-pin.

- **Machine cost** at 50 Creators, ~30 tabs (D9: 8 vCPU / 31 GB).
  - Tick: a union over ≤ 30 clamps of ≤ 50 ids plus `plan` over ≤ 50 Creators, under 1 ms (g), plus 2 small DB reads
    per 5 s (i).
  - Reads: ≤ 0.3/s, ≤ 1 worker thread per exit at once (5–10, i). Events: ≤ 10 per min plus `live` flips; deliveries
    ≤ 10 × 30 tabs = 5/s (i). Nightly `chatter-crowd` held 20 chatters at stream p95 6.8 ms, CPU ≤ 8 % (m).
  - Heartbeat `fresh`: ≤ 50 × ~30 B per tab per 20 s ≈ 2 KB/s total (i). Memory ≤ 50 KB (g). CPU under 1 % of one core
    (g; the run 1 relay mean was 1.2 % of a core with 10 Creators and 3 tabs, m).

### Contract (frozen for Phases 2 and 3)

Phases 2 and 3 build only on this section; changing it changes all three specs. Knob off: none of it exists.

1. **Snapshot `Freshness`**, one shape on the accounts rows, the event and the tab store:
   ```
   { account_id: str,
     boot: int,               // epoch ms the Relay process started
     seq: int,                // per Creator per boot, +1 on every publish
     now: int,                // epoch ms, Relay clock at send time (the tab's skew reference)
     at: int | null,          // epoch ms, Relay clock: Last refresh; null: none since boot
     cycle_s: int | null,     // the Creator's Cycle; null: not read (Dead session, no pump, not OF, not tracked)
     live: "up" | "down" | "dead" | null,
     live_since: int | null,  // epoch ms the Relay's 5 s tick first saw `live` take its current value
     values: { notif_count?: int,                          // only with SHARED_REFRESHER_BELL=me
               unread_total?: { n: int, at: int } | null } } // Phase 2; key present iff UNREAD_TOTAL on; null: none yet
   ```
   `at` moves only when a `/users/me` read (the Cycle's, or the warm's with the refresher on) landed from OF and its
   write-back was kept (A Cycle's reads), so every `at` is a `/users/me` confirmation. A slot's `at` is that value's
   own confirmation time; a tab ages a slot from `max(at, slot.at)`.
2. **`live`** (`live_of`): "dead" while the Creator is in the Dead-session map; null when no OF socket is expected
   (not OF; tracked but not in `live_account_ids()`: deactivated, no session), never "down"; else "up" while
   `of_ws.connected_since(aid)` is set (from the pump's auth frame, `service/of_ws.py:169,181,288-292`), "down" when
   not. `live_since` restarts on each change the tick sees; an "up" shorter than one tick is not seen.
3. **Event `creator_refreshed`**: `{"creator_refreshed": Freshness, "__account_id": aid}`. Relay-minted
   (`events.publish`), in `SSE_TYPES` and `ANY_SCOPE_TYPES` (every tab whose clamp holds the Creator, as
   `creator_warmed`, `service/events_decide.py:283-294`), `COALESCE["creator_refreshed"] = "account_id"`
   (`events_decide.py:84`). Published when `changed` (values with each slot compared without its `at`, `live` or
   `cycle_s` differ) and when a Creator enters `tracked`; `at` or a slot's `at` alone is no change. Each publish bumps
   `seq`. Not persisted: `events.publish` fans out and writes the replay ring only (`service/events.py:235-271,402`);
   Web Push ignores it (`service/push_send.py:104`).
   Rung 1, a new type, not `creator_warmed`: that consumer re-reads the cached `notif-list` money lists and arms the
   Creator's unleased reads (`app/hooks/useAccountStateEvents.ts:184-208`, `app/lib/ofReadGate.ts:5-10`), up to 2
   cold reads per Creator per Cycle per tab (i). `creator_refreshed` never calls `armRead` or invalidates `notif-list`.
4. **First paint.** `/admin/accounts` rows and `/chatter/me/accounts` rows (`chatters.FlatAccountDTO`; the chatter
   answer is a bare list, `service/chatters.py:566`, so `now` sits in each row) gain `freshness` for every Creator in
   the answer (`cycle_s` null when not tracked); 0 OF calls. A chatter-only session never reads `/admin/accounts`
   (`app/hooks/useAccounts.ts:71-90`, `service/screens_api.py:267-274`). `useAccounts` keeps the field through the
   chatter normalization (`useAccounts.ts:97-113`) and seeds the store from network answers only, never the persisted
   copy. ASSUMPTION: the accounts lists are the carrier (rung 3: `session_dead_at`, `proxy_down` ride them,
   `service/accounts_admin_api.py:285-292`); overturned if a screen showing Creator data paints before they answer,
   then the inbox bundle gains the same field.
5. **Order (tab reducer).** Per Creator the held snapshot is replaced by a delivery (seed or event) whose
   `(boot, seq)` is not lower, compared as a pair; a higher `boot` replaces whole (a restart forgets). Within a boot
   `at` and every slot's `at` take the max of held and delivered, so a late seed never rolls `at` back.
6. **Eviction.** A network accounts answer (incl. after `resync`) drops every held Creator whose row has no
   `freshness` or is absent; `identityChanged` clears all. A tab open across a switch-off (Knob off + restart) returns
   to today's screen.
7. **Ping.** With the Knob on every stream `ping` carries `fresh: {aid: at}` for the tracked Creators in that
   subscriber's clamp, on its own 20 s timer, frames or not (today's ping fires only after 20 s with no frame,
   `last_beat` resets per frame, `service/events.py:636-639,655`). It moves `at` forward only; slot `at`s do not ride
   it (rule 1's `max`). No ring entry, no event, 0 OF calls.
   ASSUMPTION: D5's "publish only on change" means no event for a Cycle that changed nothing, and the confirmation
   rides the ping (rung 2 reading of D5 with D7); overturned if the owner allows one event per Cycle, then every
   landed Cycle publishes and the ping field goes.
   Reconnect: a missed `creator_refreshed` replays from the account ring; a `resync` refetches the accounts lists
   (`app/hooks/useAccountStateEvents.ts:215`). ASSUMPTION: a change between a tab's accounts answer and its first
   stream connect (no cursor, no replay, `service/events_decide.py:378-384`) waits for the Creator's next change, `at`
   still arriving by ping (rung 5; `creator_warmed` has the same gap); overturned if Phase 3's shots show a stale
   value with a fresh age, then each new stream gets one `creator_refreshed` per tracked Creator after `: connected`.
8. **Contributors.** `register(name, contributor)`: `snapshot(aid) -> JSON | None`, published under `values[name]`,
   and optionally `window_due(aid) -> bool`. Phase 1 hands contributors no OF body: one that needs `/users/me`
   observes it in the OF client (Phase 2), which runs synchronously inside the read (`service/of_client.py:785-798`),
   so the Cycle's `window_due`, asked after read 1, sees a drift that read found. `note_values(aid)` may be called from
   any thread: it schedules the re-read and publish on the Relay loop with `loop.call_soon_threadsafe` (as
   `events.publish`, `service/events.py:415`). A contributor guards its state with a `threading.Lock`, held briefly.
9. **Window-read hook.** `set_window_reader(fn)` (one reader: Phase 2's); `window_read(aid)` calls it, else
   `accounts_admin_api.rewarm_roster_count` (`:594-605`). With the refresher on, both the Cycle (when `window_due`;
   in the refresher's walk and background lane) and the App-open warm's step 2 (`server.app_open_warm_reads`,
   `service/server.py:4229`, its own walk) read the window only through it. The refresher reads it at most once per
   Creator per Cycle, whatever asked.
10. **No pump** (deactivated, no session): `live` null, `cycle_s` null, never read, never "down" (rule 2).
11. **Knobs** (slop may set any): `SHARED_REFRESHER` (0 | 1), `SHARED_REFRESHER_LEASE_CYCLE_S` (120),
    `SHARED_REFRESHER_TAB_CYCLE_S` (600, never below the lease cycle; both clamp to 60), `SHARED_REFRESHER_BELL`
    (`0` | `me`), Phase 2's `UNREAD_TOTAL` (0 | 1, honoured only with `SHARED_REFRESHER=1`). The scenario may also
    set the sibling's `APP_OPEN_WARM_FRESH_S` (ASSUMPTION, `fix/all-models-open-cost` `service/app_open_warm.py:82`).
    Constants: `FLOOR_S` 60, tick 5 s, `SPREAD` 0.1, job deadline 30 s, ping 20 s.
12. **Budget, the set's one table** (default Knobs; Phases 2 and 3 point here). Mix: L = min(C, 10) leased, the rest
    on the tab cycle (study §3, g). Creator-Cycles/min = (0.5 L + 0.1 (C − L)) × 1.05 (`SPREAD`, i) = 5.3 / 7.4 / 9.5
    at 10 / 30 / 50 Creators. D8 envelope scaled by the same mix: 14 × (0.5 L + 0.1 (C − L)) / 9 = 7.8 / 10.9 / 14.
    Every row lands in `walk:shared_refresher`, Cost group `shared_refresher`; gross attempts, 429 retries included.

    | Row | Phase | Per Creator | calls/min at 10 / 30 / 50 | Label |
    |---|---|---|---|---|
    | `/users/me` every Cycle | 1 | 1 per Cycle | 5.3 / 7.4 / 9.5 | i (mix g) |
    | window read after a socket gap | 1 | 3 calls × ~0.5 gaps/h | 0.3 / 0.8 / 1.3 | g |
    | window read on downward drift (none yet this Cycle) | 2 | 3 calls × ~0.5 drifts/h | 0.3 / 0.8 / 1.3 | g |
    | Unread total confirmations | 2 | 0 (observed reads) | 0 / 0 / 0 | i |
    | data age, No-live-connection mark | 3 | 0 | 0 / 0 / 0 | i |
    | **Total, default** | | | **5.9 / 9.0 / 12.1** (D8 envelope 7.8 / 10.9 / 14) | g |
    | ceiling: a window read every Cycle (sockets down, drift every Cycle) | 1+2 | +3 per Cycle | 21 / 30 / 38 | i |
    | every Creator leased (L = C), no window reads | 1 | | 5.3 / 15.8 / 26.3 | i |

    Per day at 50: 17.4k Open-tab around the clock, ~11.6k at 16 h/day (g), inside D8's 13k–20k. Off-by-default and
    not-built options, each over D8 unless noted: `SHARED_REFRESHER_BELL=me` +0 (same read); lease cycle 60 s
    +5.3/min at 50 (i); a `/count` read on the lease tier (not built) +5.3/min (i); the desktop notifier as a tab
    (needs-human) +5.3/min around the clock (i). Elsewhere, not in this group: the warm's `/users/me`, +1 per started
    warm in `walk:app_open_warm` (opens already read it, net ≈ 0, i; ASSUMPTION, overturned if the sweep shows that
    kind rising); tabs' re-reads of lists Phase 2 drops (route kinds, g). Nets against (i): later opens' warm reads
    (AE `walk:app_open_warm` 67.4/h, m; slop 22–39 per open, m → ~0 within a Cycle), tabs' roster-count window re-reads
    after a socket gap, part of `/users/me` (AE route 30.9/h, m), with bell `me` tabs' count polls (AE 15.8/h, m). On
    AE today (19 Creators, 10 on screen) the default adds ~430/h gross (g).
    ASSUMPTION: the gap and drift rates (g; no AE number); overturned by the Watch check or the sweep's
    `walk:shared_refresher` rate per Creator after deploy, then window reads on the tab cycle go behind a Knob.

## Testing Decisions

- **Seams** (highest first; the first two carry the Phase):
  1. `shared_refresher_decide`: table tests (`service/tests/test_shared_refresher_decide.py`, house plain-assert with
     `_harness`). Rows:
     - tier and floor: Knob 10 → 60; tab < lease → lease.
     - `cycle_s` per Creator in [0.9 × tier, tier], ≥ 60, stable per `aid`.
     - due: just warmed → next slot, not now; Last refresh within its `cycle_s` → not due; at `last + cycle_s` → due.
     - first read spread inside `FLOOR_S`.
     - skips: not tracked; tracked but Dead (no Read, `live` dead, `cycle_s` None); warm-pending; in flight; Fansly.
     - `tracked` empty → no Read (the last tab closed).
     - one Read per Creator whatever the subscriber count (flat in N).
     - back-off: 429 → hold `max(60, ladder)`, reset on ok; a failed attempt never followed by another under 60 s.
     - `window_due`: socket down; reconnected after `window_at`; contributor asked → true; no window held, or none
       of these → false.
     - `changed`: `at` alone, a slot's `at` alone false; values, `live`, `cycle_s` true; first track true.
     - `live_of`: dead map → "dead"; tracked, not readable (deactivated, no session) → None, never "down"; Fansly →
       None; socket set → "up", unset → "down".
     - `values_of` per bell mode on the fixture body.
  2. App `lib/creatorFreshness.ts`: vitest tables (`creatorFreshness.test.ts`; template
     `app/components/chat/fanDrawerForm.ts` + test).
     - `(boot, seq)`: a late seed loses to a newer event; an equal pair keeps the higher `at` and slot `at`; a new
       `boot` replaces whole. Heartbeat moves `at` forward only.
     - eviction: a seed row without `freshness`, or a Creator missing from the answer, drops it; `identityChanged`
       clears.
     - `covers` true only with a held `notif_count`.
  3. Shell tests where behaviour crosses modules:
     - `test_shared_refresher_netting.py`: warm `reused` inside the Creator's Cycle, `started` past it (socket up or
       down alike, ADR-0044); the refresher not due after a warm; the warm reads `/users/me`, bypassing the cache, only
       when on; a warm whose write-back was discarded writes no Last refresh; the warm's step 2 goes through
       `window_read`.
     - `test_shared_refresher_open_tab.py`: `open_tab_accounts` counts `lease=1` / Referer streams and drops unclamped
       and watcher; empty after the last stream unsubscribes.
     - `test_shared_refresher_reads.py` (the server's reads helper over a stubbed client, existing harness): a
       dead-session error from `/users/me` and from the window marks the Creator dead (no request in flight); a
       terminal 429 with `Retry-After` moves the exit's `free_at` by it; a discarded write-back (invalidate during the
       fetch) leaves `at`; reads run with `_current_priority()` = "background"; a `window_due` raised by a client
       observer during read 1 adds the window in the same job, through a registered reader; `note_values` from a
       worker thread publishes once on the loop.
     - `test_shared_refresher_lifecycle.py`: with `SHARED_REFRESHER=1` reloaded, `start()` plus one tab subscriber
       on a live Creator → one job on its exit and one `creator_refreshed` within two ticks (stubbed reads helper);
       `stop()` ends the task; the startup hook calls `start` only when `ENABLED`.
     - `test_events_any_scope.py`: `creator_refreshed` reaches a model-scoped subscriber for another Creator in its
       clamp, never past it.
     - `test_events_fresh_ping.py`: a stream fed a frame every 5 s for 60 s still yields ≥ 2 `ping`s carrying `fresh`
       when on; none carries `fresh` when off.
     - `test_events_decide.py`: the type sets and `COALESCE`.
     - `test_accounts_freshness.py`: `/admin/accounts` and `/chatter/me/accounts` rows carry `freshness` (with `now`,
       `boot`, `seq`) when on, none when off; with bell `me` the inbox bundle's `notificationCounts` for a covered
       Creator makes 0 OF calls.
     - `test_app_open_warm.py`: the gate's refresh job, absorption by a warm, at-turn drop (untracked, dead, refreshed
       meanwhile), exit hold on 429, job deadline releases the exit without cancelling the walk and applies its late
       result.
     Prior art: `test_app_open_warm.py`, `test_view_lease.py`, `test_purchase_poll_decide.py`,
     `test_events_any_scope.py`.
  4. App hooks: `useAccountStateEvents.test.tsx` (`creator_refreshed`: no `armRead`, no `notif-list` invalidation;
     with a held `notif_count` it writes the count, and a newer seed then older event keeps the seed's), `useAccounts
     .test.tsx` (`freshness` kept on owner and chatter rows; seed → `of-notif-count` entries when covered),
     `useOfNotifCount.test.tsx` and `ofReadGate.test.ts` (covered → `once`).
  5. Sweep: `scripts/proxy-health/test_watch.py` for the new check, `test_summarize.py` for the Cost group's rating.
  No test hook in `service/` (CLAUDE.md): tests drive the pure module, the shells through their public functions and the
  routes through the existing harness.

- **Slop `2026-11-20-all-models-shared-inbox`** (opt-in; shipped by `fix/bg-lane-money-deadlock`). Budget: one
  green run + one `--break` per slice, each under 15 min (plan-review "Recommended build order"). The scenario gains:
  - `RELAY_ENV` `SHARED_REFRESHER=1`, `SHARED_REFRESHER_LEASE_CYCLE_S=60`, `SHARED_REFRESHER_TAB_CYCLE_S=60` (both at
    the floor, so a phase sees whole Cycles), `IDLE_S` 90 → 120.
  - A phase `idle_one_tab` after `idle`: B and C close their tabs, A alone for `IDLE_S`. Per-Creator cost must not
    move with the tab count.
  - A phase `open_after_cycle` after `idle_one_tab`: a fourth tab D opens. The last warm is then > 240 s old, past
    every Creator's 60 s Cycle, so only the refresher's Last refresh can make D's warm `reused` (with the refresher on,
    the warm's window is the Cycle, not the sibling's `FRESH_S`); `open_after_reuse` (≈31.5 s after phase 1, scenario
    line 537) cannot isolate Phase 1.
  - A phase `no_tab` (30 s): every tab closed.
  - Sampling of `GET /admin/accounts` `freshness` every 5 s in both idle phases.
  - One fault (slop/README "Break-it-once"): `refresher-per-subscriber` → `REFRESHER_FLAT_IN_N` (the D4 claim): the
    shell runs one job per tab subscriber per Creator, each with its own queue entry and `bypass` (else the one-entry
    queue and the cache would collapse the copies). Never-due and no-netting are caught by the decide table and
    `test_shared_refresher_netting.py`.
  - Runtime +~210 s (i: +30 `IDLE_S`, +120 `idle_one_tab`, +30 D's open, +30 `no_tab`) on 396–483 s (m).
    ASSUMPTION (rung 5); overturned if the owner keeps the scenario frozen, then the metrics live in a sibling scenario.

  | Metric | From | To | Label |
  |---|---|---|---|
  | `of_budget_idle.by_caller["walk:shared_refresher"]` per Creator per min, `idle` (3 tabs) vs `idle_one_tab` (1 tab), new metric `idle_refresher_per_creator_min {n3, n1}` | absent | both in [0.8, 1.2] (a refresher that reads nothing fails), `n3 − n1` ≤ 0.25 (check `REFRESHER_FLAT_IN_N`) | i |
  | new `refresh_staleness {max_s, per_creator, cycle_s}`: max(now − `at`) over the samples | absent | `max_s` ≤ `cycle_s` + 10 s queue wait (check `REFRESH_WITHIN_CYCLE`) | i |
  | new `of_budget_open_after_cycle {total, by_caller}` and D's `warm_answers` | absent | every Creator `reused`, `by_caller["walk:app_open_warm"]` = 0, `total` ≤ 30 (i: 7 thread prefetch + ≤ 2 money lists per on-screen Creator; check `OPEN_AFTER_CYCLE_REUSED`, netting slice) | i |
  | new `refresher_calls_no_tab` | absent | 0 after the first tick of `no_tab` (check `REFRESHER_STOPS_WITHOUT_TABS`) | i |
  | `idle_calls_per_min.max_per_creator` | 2.67 (m) | ≤ 3.7 (i: + 1 read/min at the 60 s floor) | i |
  | `IDLE_BUDGET`, `SECOND_OPEN_SHARED` | pass | pass (`IDLE_MAX_PER_CREATOR_MIN` 15, scenario line 138; the docstring's sum gains +1 per 60 s) | i |

- **UI.** None: Phase 1 changes no component (the bell's number changes source, not look). Screenshots are Phase 3's.
  The side-effect proofs are the Relay answers: a `creator_refreshed` frame on the stream and `/admin/accounts`
  `freshness` in the scenario's samples.

## Acceptance

```sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
scripts/run-tests.sh shared_refresher
scripts/run-tests.sh app_open_warm
scripts/run-tests.sh events_any_scope
scripts/run-tests.sh events_fresh_ping
scripts/run-tests.sh events_decide
scripts/run-tests.sh accounts_freshness
venv/bin/python scripts/run_tests_parallel.py --pytest scripts/proxy-health -j 8
(cd app && pnpm exec vitest related --run lib/creatorFreshness.ts lib/ofReadGate.ts lib/events.ts hooks/useAccountStateEvents.ts hooks/useOfNotifCount.ts hooks/useAccounts.ts)
pnpm -C app typecheck
pnpm -C app lint
grep -n '"creator_refreshed"' service/events_decide.py
grep -n '"shared_refresher": \["walk:shared_refresher"\]' scripts/proxy-health/of_calls.py
grep -n '"shared_refresher_budget"' scripts/proxy-health/watch.py
grep -n 'shared_refresher.start' service/server.py
(cd service && env -u SHARED_REFRESHER ../venv/bin/python -c "import shared_refresher as s; assert not s.ENABLED")
scripts/run-tests.sh
# manual: owner opt-in (slop, needs fix/bg-lane-money-deadlock merged), per slice 1 green + 1 --break, each < 15 min:
# manual:   nice -n 10 slop/run 2026-11-20-all-models-shared-inbox --scale=small
# manual:   nice -n 10 slop/run 2026-11-20-all-models-shared-inbox --scale=small --break --fault=refresher-per-subscriber --baseline=slop/evidence/<the green folder>   -> CAUGHT REFRESHER_FLAT_IN_N
# manual: owner turns it on in AE (SHARED_REFRESHER=1 in the AE compose override), deploys (ae-deploy); not part of this Phase's run
# manual: Baseline run re-pin, right after that deploy and before the next 4 h sweep (repo ~/proxy-health-data, runs ae/runs/):
# manual:   1. newest=$(ls ~/proxy-health-data/ae/runs/*.json | tail -1); keep a copy: git -C ~/proxy-health-data log is the record
# manual:   2. remove the pinned baseline and its history so the next run anchors after the deploy:
# manual:      python3 -I -c "import json,sys;p=sys.argv[1];d=json.load(open(p));d.pop('of_calls_baseline',None);d.pop('of_calls_hist',None);json.dump(d,open(p,'w'),indent=1)" "$newest"
# manual:      (keeping of_calls_hist would anchor up to 26 h before the deploy and blend pre-deploy rates into the pin)
# manual:   3. git -C ~/proxy-health-data commit -am "of_calls: re-pin Baseline run after shared refresher deploy"
# manual:   4. next sweep reads of_calls.state first ("anchor stored"); 6 rated runs over >= 24 h later (~28 h at 4 h cadence) it pins;
# manual:      until then of_calls_vs_baseline answers ok "baseline building k/6"; ship no other OF-call change in that window
# manual:   5. check: jq '.of_calls.baseline_state, (.of_calls_baseline.caller|has("walk:shared_refresher"))' "$(ls ~/proxy-health-data/ae/runs/*.json | tail -1)"  -> "pinned", true
# manual: after deploy append to the sweep's WATCH.md (dates of the deploy day):
# manual:   - shared-refresher-budget | added YYYY-MM-DD | expires +3d | shared_refresher_budget | <PR url>
# manual:   - shared-refresher-of-calls | added YYYY-MM-DD | expires +3d | of_calls_vs_baseline | <PR url>   (meaningful once the re-pin pins, ~28 h; the set's only of_calls_vs_baseline line)
# manual: bell-pair check (owner, own OF web session, devtools Network, 0 Relay calls), gates SHARED_REFRESHER_BELL=me:
# manual:   for 2-3 Creators, OF web's own GET /api2/v2/users/me `notificationsCount` = its GET /api2/v2/users/notifications/count `all`, on load, after a new notification and after reading notifications
```

The Watch check `shared_refresher_budget` (watch.py, same PR, since no existing check fits). Over the rated interval
(since the previous sweep, `of_calls.caller` / `.account`, `scripts/proxy-health/of_calls.py:454-460,520-527`):
`watch` when `walk:shared_refresher` calls/h exceeds 1.25 × D8's envelope (Contract 12) for the live Creator count,
1.25 × 60 × 14 × (0.5 × min(n, 10) + 0.1 × max(0, n − 10)) / 9 with n = `account` keys with calls_h > 0 (all
callers: the sweep has no per-caller-per-Creator split), i.e. ~1,050/h at 50, ~820/h at 30, ~580/h at 10 (i); or its
429/h exceeds 1. `ok` otherwise; `unknown` when the block is not rated. ×1.25 is `of_calls_vs_baseline`'s own trip
(`of_calls.py:34`). Phase 2 adds one condition to it (its Post-deploy watch).
ASSUMPTION: those bounds (rung 3 for ×1.25; the mix g); overturned if the first 3 days sit far below them, then they
tighten.

## Depends on

- **No other Phase.** Phases 2 and 3 depend on this one through `### Contract (frozen for Phases 2 and 3)` only.
- **In flight, nets against (assumed as seen in their worktrees off 18699cc5b, not merged):**
  - `fix/all-models-open-cost` (a99c91eeb): `reuse_decision` and `FRESH_S` in `app_open_warm`, `users_me` cached
    with `max_age`, payouts at 900 s. Phase 1 feeds its decision with the shared Last refresh (Netting). Must land
    before the Netting slice (stories 22–25); the rest of the Phase ships without it.
  - `fix/bg-lane-money-deadlock` (7d55eafab, 823710c38): ships the slop scenario Phase 1's proof extends. A dependency
    of the proof only: its lane fix is for parallel children of one request, and the refresher is sequential and
    requestless, so the runtime does not need it.
- **Not a dependency:** `fix/reply-reaches-other-chatters` adds `chat_responded` to `ANY_SCOPE_TYPES`, the set this
  Phase also edits: a merge collision, nothing Phase 1 calls.
- **ASSUMPTION:** each sibling keeps the interface cited (in flight, rung 1 on their worktrees); overturned by their
  merged code, then the mapping changes, not the design.

## Out of Scope

- The WS counter frame as a source for any value (Q1 parked; a later flag-gated upgrade behind the owner's check).
- Q1's Step B log line in `of_ws._refresh_auth` (the plan's later ticket). Using that reconnect read as a free
  refresh: it changes `of_ws`, and a reconnect is no schedule.
- Reading the rail's money lists in a Cycle: +2 reads per Creator per Cycle (36/min at 50, i). The lists change on
  money events the Live connection brings, and a tab re-reads an expired one through the shared cache.
- A `/users/notifications/count` read in the Cycle (lease tier only: +5.3/min at 50, over D8, i) and a Relay
  bell-pair log line: the bell waits for the owner's 0-call check and `SHARED_REFRESHER_BELL=me`.
- Refreshing Creators nobody has open, and variants A / A' / B (ADR-0042, rejected).
- Fansly reads (live = null only).
- Persisting refresher state across restarts (plan: in-memory).
- A Setting flag (Knob only until the sweep data says otherwise, house rule).
- Unread total semantics and the badge (Phase 2). Data age and "no live connection" display, debounce and screenshots
  (Phase 3).
- Removing tabs' `/users/me` and money-list reads beyond the cache they now share (study rows 6, 7: separate work).
- Deploy, turning the Knob on in AE, running the re-pin (a human, after deploy: plan "Not in this plan").

## Further Notes

- ASSUMPTION: Open-tab counts only app-tab streams (`lease=1` or a Referer) (rung 4: excluding is the cheaper,
  reversible side; rung 1 for the desktop stream at `desktop/main.js:950`); needs-human in Review, since D1 read
  literally counts the desktop notifier. Overturned by the owner's answer; then `tab` is any clamped stream.
- ASSUMPTION: the leased mix L = min(C, 10) behind every budget cell (g, the study's); overturned by the sweep's
  `walk:shared_refresher` rate per Creator after deploy.
- ASSUMPTION: `window_due` triggers on a socket gap since the window's own last read, not only on a socket down now
  (rung 5: frames during a gap are lost either way, and Netting needs the window invariant); overturned if the
  window reads show in the sweep above ~3/min at 50.
- The re-pin blinds `of_calls_vs_baseline` for every Cost group for ~28 h (i). Seeding a guessed
  `walk:shared_refresher` rate into the pinned baseline would avoid that, but it makes a measured reference part guess.
  Rejected (rung 4: the rebuild is the sweep's own rule, README "OF calls").

## Review

Reviewer: `codex` (exec, read-only, reasoning high), 2026-11-20. Call 1 blind (B1–B11), call 2 on the draft (D1–D20).
Each finding checked against source; file:line is the evidence.

- B1 **accept** — a me+count Last refresh cannot certify the warm's wider read set (feed, window, money lists:
  `service/app_open_warm.py:33-41`, `service/server.py:4221-4238`). Rewrote Netting "What a Last refresh certifies" and
  `window_due` on the window's own read time, so the window is read whenever not WS-kept.
- B2 **partial** — both contracts were already specced (2 reads default, `BELL_FROM_ME`). Took the "prove across
  arrivals and mark-read" part: bell-pair gate rewritten (no persistent mismatch).
- B3 **accept** — cost follows the lease union (`view_lease.leased_ids` has no cap, `service/view_lease.py:134-141`).
  Added the worst-case row (50/min all leased) and gross-attempt note to the budget.
- B4 **partial** — clamped app-tab streams already were the eligibility test. Added membership edges (last close,
  `ENDS_STREAM` revocation `service/events_decide.py:261`, lease without stream, re-entry) under Open-tab Creator.
- B5 **partial** — same as D4 (cache hit) and D1 (no-cursor stream); taken there. The seed/stream race is flagged
  ASSUMPTION, not closed.
- B6 **accept** — at-turn re-check added (Pacing); floor now governs attempts (`due_at`, `after_read`). 401 strictness
  is `account_health.is_session_dead_error`'s (`service/account_health.py:51-60`), reused as is.
- B7 **accept** — the inbox bundle reads `/count` per Creator each first paint (`service/screens_api.py:396-397`).
  Covered Creators now answer from the snapshot (Contracts "Inbox bundle count", story 52).
- B8 **reject** — row-level clears from a total are Phase 2's (plan Phase 2; ADR-0043). Phase 1 only carries values.
- B9 **partial** — real relay + fake OF + SSE is the slop scenario (opt-in, D10); added a lifecycle shell test and a
  startup grep. Startup placement below the test-mode guard (`service/server.py:1636-1646`) stated.
- B10 **accept** — `open_after_reuse` runs ≈31.5 s after phase 1 (scenario `:537`), inside the sibling's own reuse
  (`FRESH_S` 300, sibling `:81-82`), so it cannot attribute anything to Phase 1. Added `open_after_cycle` past
  `FRESH_S`. The "fixed leases" part is moot: both Cycles sit at the 60 s floor in the scenario.
- B11 **partial** — falsifiers mostly present; added `REFRESHER_STOPS_WITHOUT_TABS` (`no_tab` phase) and a nonzero
  floor on the flat-in-N metric.
- D1 **accept** — chatters read `/chatter/me/accounts` (`app/hooks/useAccounts.ts:71-90`); the bundle answers no
  accounts for them (`service/screens_api.py:267-274`). Both lists now carry `freshness` (with `now`).
- D2 **accept** — `due_at` at 0.9 × Cycle read inside the advertised Cycle. The per-Creator period is now the Cycle
  (`cycle_s`), used by scheduler, warm and staleness alike.
- D3 **accept** — the draft added a socket condition ADR-0044 does not have and misstated the sibling (`reused` under
  `REUSE_S` regardless, `skip` on failure: sibling `service/app_open_warm.py:163-174`). Now ADR-literal, with the
  sibling's other branches kept and the window invariant replacing the socket test.
- D4 **accept** — `relay_cache` entries keep no read time (`service/relay_cache.py:300-306`). Refresher reads (and the
  warm's me/count when on) bypass; `at` moves only on a kept write-back.
- D5 **partial** — the popped-job race is real (`service/app_open_warm.py:201-216`): at-turn re-check added. A warm
  queued behind an in-flight refresh still re-reads the window: residual, accepted (its me/count are cheap reads of
  the same moment); flagged rung 5.
- D6 **accept** — `_proxy` flags dead only with a request (`service/server.py:2637-2643,2680-2688`);
  `rewarm_roster_count` skips the flagging handler (`service/accounts_admin_api.py:540-552,594-605`). The reads helper
  flags itself; test added.
- D7 **partial** — a retried 429 already held the exit (the job slept OF's wait). The terminal 429's header survives
  on `exc.__cause__` (`_proxy` raises `from e`); wait now taken from it via `of_pacing.upstream` / `asked_wait`.
- D8 **accept** — `wait_for` cancels the walk. Now `asyncio.wait` with timeout; the task's callback applies the late
  result.
- D9 **accept** — requestless reads are classed `user` (`service/server.py:2537-2545,2519-2520`); the window read takes
  no lane. Refresher walk now answers "background" and laned.
- D10 **accept** — event writes the store's (post-reducer) count; the seed writes bell entries too; hook tests added.
- D11 **accept** — `last_beat` resets on every frame (`service/events.py:636-639,655`). `fresh` ping on its own timer;
  test added.
- D12 **accept** — `window_due` now asked after `on_users_me` in the same job.
- D13 **accept** — `set -euo pipefail`, lifecycle test, startup grep added to Acceptance.
- D14 **accept** — CAUGHT needs every target red (`slop/README.md` "Break-it-once"). One fault per check; the
  per-subscriber fault bypasses queue and cache; flat-in-N gets a nonzero floor.
- D15 **accept** — `OPEN_AFTER_CYCLE_REUSED` check added (see B10).
- D16 **accept** — `of_calls.account` is per-interval, all callers (`of_calls.py:106-125,454-460`). Bound now 1.5 × the
  D8 envelope for n live Creators (~1,620/h at 50).
- D17 **needs-human** — D1 ("a live `/events` subscriber who can see the Creator") read literally counts the desktop
  notifier's always-on `/events?scope=all` stream (`desktop/main.js:950`); the spec excludes it as nobody's screen.
  Include: its owner's Creators stay on the tab cycle 24/7, +10/min at 50 (i), ~22k/day with chatters' hours (i),
  over D8's 20k. Exclude (kept, rung 4): cheaper, reversible. Settles it: the owner's word on whether the desktop
  notifier is "watching".
- D18 **partial** — the Knob stays (plan's budget note asks how to reach one read); the 95 % gate was wrong for a
  bell contract and is replaced by "no persistent mismatch".
- D19 **accept** — `events.publish` does not persist (`service/events.py:235-271,402`). Claim fixed.
- D20 **accept** — reply-reaches is a merge collision, not a dependency; bg-lane is a proof dependency, not runtime.
  Depends on rewritten.

### Six hats (2026-11-20)

Report `/tmp/wcr/sixhats.md` (31 bullets, set-wide); lines for the bullets touching this spec. Set-level ones and the
tally: `plan-review.md` "Six hats".

- 2 **accept** — bell pair never recorded side by side, leased mix a guess (Contract 12 labels it g): both stay
  open; the bell pair moves to a 0-call owner check (Acceptance), no Relay log.
- 3 **accept** — `fix/all-models-open-cost` was a whole-Phase runtime dependency; it only gates Netting (stories
  22–25), Depends on rewritten. The scenario dependency stands.
- 7 **accept** — nobody summed the set against D8. Contract 12 is the set's one table; Phases 2 and 3 point at it.
- 9 **accept** — `changed` compared whole `values`, so Phase 2's moving `at` would publish every confirmation.
  Contract 3: a slot is compared without its `at`.
- 10 **accept** — two tab stores, and `at`-ordering lets a late equal-`at` seed overwrite a newer push. Contract 1/5:
  `boot`/`seq` on the envelope, one store, `(boot, seq)` order, `at`s by max.
- 11 **accept** — `on_users_me` duplicated Phase 2's client observer (`service/of_client.py:785-798` sees every fetch).
  Contract 8/9: no body hand-off; `window_due` asked after read 1; one window reader hook for Cycle and warm.
  Raw `values.chat_messages_count` dropped (this spec's own overturn clause fired).
- 13 **accept** — (a) no eviction row: Contract 6; (b) a no-pump Creator read "down" (`live_of` lacked the input,
  `service/transaction_ingest.py:1577-1588` drops it from `readable`): Contract 2/10, decide-table row.
- 14 **accept** — `note_values` thread-safety unstated while Phase 2 calls it from `of_client` threads: Contract 8,
  `call_soon_threadsafe` (precedent `service/events.py:415`); test row.
- 15 **accept** — 18/min default + window + drift ≈ 21–23 at 50, and the Watch bound (1.5 × own 2-read envelope ≈
  27/min) could never see a D8 overrun. Default is now 1 read: set total ~12.1/min (g, Contract 12); Watch bound =
  1.25 × D8 envelope (~1,050/h at 50).
- 18 **accept** — 1 green + 3 `--break` broke the 2-run cap. One fault (`refresher-per-subscriber`); never-due and
  no-netting go to the decide table and netting shell test; runtime +~210 s (i).
- 19 **accept** — no change; the ≤ 30 open total now sits on `open_after_cycle` (Netting slice).
- 22 **partial** — per-tier reads and `covers` on a held `notif_count` taken. Its 14.0/min (+5 % spread) leaves no
  room for window and drift reads, which the study's ~14 already held (REPORT §3 variant C: 1 count read + "unread
  list only when the WS state is in doubt"). So no `/count` read by default; bell via Knob `me` (0 calls) after the
  owner's check; a lease-tier `/count` read is listed, not built (Out of Scope).
- 24 **partial** — the bell-pair log is cut (owner's devtools check replaces it); `BELL_FROM_ME` becomes
  `SHARED_REFRESHER_BELL` (`0` | `me`), kept because it is the only in-budget way to carry the plan's bell count.
- 25 **accept** — Watch check re-derived from D8 (×1.25); the set keeps one `of_calls_vs_baseline` WATCH line (this
  spec's); Phase 2's drift folds into `shared_refresher_budget`.
- 26 **accept** — one fault kept (D4); netting and never-due to tables.
- 28 **accept** — no change: desktop notifier stays excluded, needs-human (D17); with 1 read it costs +5.3/min at 50
  around the clock (i), still over D8.
