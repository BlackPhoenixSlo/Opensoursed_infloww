# Phase 1a — Service registry and safe session ingest

**Objective.** Every per-Platform branch in `service/` asks the Platform registry instead of comparing a key, OnlyFans runs today's code on the default path, and a Fansly session is written only after its identity is proven and its account id is not already another Platform's Creator.

## Problem Statement
Fansly reached the Relay as 29 `"fansly"` / `is_fansly` branches across 17 files, so a second Platform means finding and copying every one, and missing one silently runs OnlyFans code on the wrong account. The Fansly session route writes the blob and the account meta before it knows the token works, and answers ok with `name: null` when `me()` fails: the owner sees a linked Creator that cannot read anything. Account directories are keyed by bare id, so a session from one Platform can land on a Creator of another and flip its Platform. Nobody has written down how Fansly was actually built, so site #2 would repeat its 80 days of field-meaning fixes.

## Solution
One registry module lists OnlyFans and Fansly. Client, Live connection, eviction, revenue tick, send check and API error come from the entry's Backend module; OnlyFans has none and keeps today's path. Policies Fansly cannot meet are named Lacks flags. A source scan fails the suite on a new Platform-key comparison outside the registry's files, and dispatch tests prove OnlyFans still gets OnlyFans objects. Linking a Fansly Creator now refuses a token that does not authenticate as the claimed account, and refuses an id that already belongs to another Platform, writing nothing either way. A Platform recipe doc beside `docs/platforms.md` gives site #2 its steps, the owner's action order and the Trap list.

## User Stories
1. As a developer adding a Platform, I want one registry entry and one Backend module to cover Relay dispatch, so that I don't hunt 29 branches.
2. As the owner, I want every OnlyFans Creator to behave exactly as today, so that the refactor can't regress the paying path.
3. As a developer, I want an account with no `platform`, `"onlyfans"`, or an unknown key to resolve to OnlyFans in every registry dispatch, so that old and hand-edited meta keep working (the three untouched item-7 filters keep excluding unknown keys, as today).
4. As a developer, I want `_load_client`, the executor's `_make_client`, the WS pump, the revenue lane (`transaction_ingest.run_one_tick`, `purchase_poll.run_fast_tick`) to pick their object through the registry, so that a new Platform is wired by its entry.
5. As a developer, I want `client_pool.evict` to drop the cached client of every registered Backend module, so that a re-capture never leaves a stale Shim.
6. As a chatter, I want a Fansly write the Shim refuses to answer 502 with `{"ok": false, "error": "fansly", "detail": …}` on the very first request, so that the reason reaches the UI.
7. As a developer, I want the startup loop to register each Backend module's API error, so that a new Platform's errors map the same way without a server edit.
8. As a developer, I want each per-Platform policy as its own Lacks flag (`FOCUS`, `REFERRALS`, `WALL_MEDIA`, `SERVER_SCHEDULE`, `NEAR_SCHEDULE_MEDIA`, `HISTORY_UNREAD_GATE`, `UNREAD_TOTAL`, `SHARED_REFRESH`), so that a Platform opts out of one policy without dragging others.
9. As the owner, I want free follow to be an opt-in flag true only for Fansly, so that a new Platform never skips the follow price check by default.
10. As a chatter, I want a long-delay Fansly schedule still checked by the Backend module's send check, and a short-delay one with media or price still refused, so that a deferred send never fails silently.
11. As a chatter, I want a Fansly Creator with only `fansly_session.json` to count as having a session in the switcher, roster and active-account fallback, so that linking doesn't hide it.
12. As a developer, I want the push-preference filter to accept exactly the registered keys and the pump log to print the entry's label, so that neither hard-codes Fansly.
13. As a developer, I want OnlyFans-only implementations (live window, daily stats, sign rules, link prewarm, vault collect, screens) to stay plain checks that compare against OnlyFans, so that they aren't dressed up as features another Platform could have.
14. As a developer, I want a test that fails on a `"fansly"` literal or a `FANSLY` comparison anywhere in `service/` outside the allowlist, so that the next branch is caught in review time, not production.
15. As a developer, I want dispatch tests that drive the real entry points with missing and explicit OnlyFans meta and assert the OnlyFans object is used, so that a table test can't pass while dispatch breaks.
16. As a developer, I want the same entry points driven with Fansly meta to reach the Backend module, so that the registry is proven in both directions.
17. As a developer, I want `test_fansly_revenue.py` to patch the registry instead of `is_fansly`, so that the revenue lane is tested through the seam it uses.
18. As Phase 1b, I want the registry to enumerate its registered Backend modules, each exporting its `Shim` class, and the API-error handler to answer the exception's `status_code` (502 when absent), so that the Capability test can loop every one and a typed 501 needs no server edit.
19. As Phase 1c, I want the registry's Platform keys and Lacks flag names importable as plain strings, so that the Drift test can read them.
20. As the owner linking a Fansly Creator, I want a token whose `me()` fails to be refused with the reason, so that I relink now instead of finding a dead Creator later.
21. As the owner, I want a blob whose `me()` id differs from its `accountId` refused, so that a paste from the wrong tab can't attach to the wrong Creator.
22. As the owner, I want a refused link to leave no directory, session file or meta behind, so that a failed attempt changes nothing.
23. As the owner, I want relinking an existing Fansly Creator to keep working and its running Live connection to restart on the new token, so that an expired session is fixed in one paste.
24. As the owner, I want a Fansly session for an id that is already an OnlyFans Creator refused with 409, and the reverse (an OnlyFans capture landing on a Fansly Creator) refused too, so that no Creator's Platform is ever overwritten.
25. As the developer of site #2, I want a recipe doc with the 11 steps and their checks, the owner's action order, the Trap list and the bounded "one entry" claim, so that I know what to do, what it proves, and which edits sit outside the registry.

## Implementation Decisions
- **Owns.** New `platforms` module. Modified: `fansly_backend`, `server` (startup error loop, `_load_client`, `_ws_pump_for_account`, the two schedule gates), `automation_executor._make_client`, `client_pool.evict`, `transaction_ingest`, `purchase_poll`, `automations.scrape_chats`, `automations.auto_follow`, `unread_total`, `of_stats_api`, `shared_refresher`, `vault_sends_api`, `push_api`, `accounts`, `accounts_admin_api`, `session_bootstrap`, `remote_login` (collision check before `bind_proxy`), `fansly_revenue` (its docstring's stale `is_fansly` pointer only), and the item-7 plain checks `of_live_window`, `of_stats_daily`, `screens_api`. New doc: the Platform recipe. Tests listed under Testing Decisions.
- **Interfaces.** `platforms` exposes:
  ```python
  class Lack(str, Enum): FOCUS = "FOCUS"; REFERRALS = "REFERRALS"; ...   # value == name, eight members:
                         # WALL_MEDIA SERVER_SCHEDULE NEAR_SCHEDULE_MEDIA HISTORY_UNREAD_GATE UNREAD_TOTAL SHARED_REFRESH
  @dataclass(frozen=True)
  class Platform: key: str; label: str; session_file: str
                  backend: ModuleType | None; lacks: frozenset[Lack]; free_follow: bool = False
  ONLYFANS = Platform("onlyfans", "OF", "latest.json", None, frozenset())
  FANSLY   = Platform("fansly", "Fansly", fansly_backend.SESSION_FILENAME, fansly_backend, <all eight>, free_follow=True)
  ALL: tuple[Platform, ...]; KEYS: tuple[str, ...]; SESSION_FILES: tuple[str, ...]
  def get(key: str | None) -> Platform          # unknown / None -> ONLYFANS
  def for_account(aid: str) -> Platform          # get(accounts.get_platform(aid)), looked up at call time
  def backends() -> tuple[ModuleType, ...]       # every non-None backend, in ALL order
  ```
  `for_account` resolves `accounts.get_platform` as a module attribute at call time so existing monkeypatches keep working (`test_ws_pump_evict.py:35`).
- **Backend module contract** (Fansly's is `fansly_backend`): `get_client(aid)`, `drop(aid | None)`, `ws(client)` (returns the Live connection, `FanslyWebSocket`), `async revenue_tick(aid) -> TickResult` (wraps `fansly_revenue.run_one_tick`), `check_sendable(**kw)` (the Shim's), `APIError` (`FanslyAPIError`), `Shim` (`FanslyShimClient`, for Phase 1b's Capability test). `is_fansly` is deleted; it has no callers left.
- **Revenue lock stays with the callers.** `transaction_ingest.run_one_tick` and `purchase_poll.run_fast_tick` keep holding `transaction_ingest._tick_locks[aid]` around `backend.revenue_tick` and keep their own result translation (`_tick_result(...)` / the fast-tick dict), as today (`transaction_ingest.py:1349-1365`, `purchase_poll.py:64-68`); `revenue_tick` takes no lock.
- **Dispatch map** (ticket 01's table, against today's code): `_load_client` and `_make_client` → `backend.get_client`, else `client_pool.get`; pump → `backend.ws(client)`, else `OFWebSocket`, log uses `label`; both revenue lanes → `backend.revenue_tick`, else the ledger code; `evict` → after its `only=` early return, guarded `import platforms`, `drop` on each of `backends()`; the server's long-delay schedule gate → `Lack.SERVER_SCHEDULE` then `backend.check_sendable`, catching `backend.APIError`; short-delay attachment/price refusal → `Lack.NEAR_SCHEDULE_MEDIA`; scrape unread gate → `HISTORY_UNREAD_GATE`; `unread_total` both checks → `UNREAD_TOTAL`; referrals → `REFERRALS`; shared refresher → `SHARED_REFRESH`; wall media → `WALL_MEDIA`; auto-follow → `free_follow`; `push_api` → `KEYS`; `accounts` session probes → `SESSION_FILES`, `latest.json` stays the OnlyFans pointer.
- **OnlyFans default path.** Every branch reads `p = platforms.for_account(aid)` and takes today's OnlyFans code when `p.backend is None` or the flag is absent. No OnlyFans code moves.
- **Item-7 plain checks** that compare against `"fansly"` today (`of_live_window`, `of_stats_daily`, `screens_api`) compare `platforms.for_account(aid) is not platforms.ONLYFANS` (screens: `platforms.get(a.get("platform"))`), so an unknown key keeps reading as OnlyFans there. `sign_rules:101`, `link_prewarm:162`, `vault_collect:166` compare raw meta to `"onlyfans"` and so already exclude unknown keys; ticket 01 item 7 keeps them untouched and that exclusion stays.
- **Startup error mapping.** The eager imports stay (`server`, `transaction_ingest`, `purchase_poll`, `scrape_chats`). The server loops `ALL`; for each entry with a backend it registers `backend.APIError` → `getattr(exc, "status_code", 502)` with `{"ok": false, "error": p.key, "detail": str(exc)}`. `FanslyAPIError` carries no `status_code` today (`fansly_client.py:75-80`), so Fansly's status and body bytes are unchanged; Phase 1b's 501 subclasses ride the same handler.
- **`fansly/` stays a sibling package**, put on `sys.path` by `fansly_backend`.
- **Session ingest, Fansly route** (`POST /admin/session/fansly`, request body unchanged). Order: (1) `account_dir(accountId)` validates the id (bad id → 400); (2) collision check; (3) `fansly_backend.identify(session)` builds an unpooled Shim client from the blob with `path=None` (so `FanslySession.save` is a no-op, `fansly_client.py:126-129`), calls `ensure_device_id()` when the blob has no `device_id` (the body allows it, `accounts_admin_api.py:182`; signed calls need it, `fansly_client.py:196-197`), then `me()`; any raise → 400 with the error text, an empty id or one other than `accountId` → 400; (4) collision check again (narrows the window across the network call); (5) only then mkdir, write `fansly_session.json` (0600) carrying any fetched `device_id`/`device_id_ts`, `upsert_account(platform=FANSLY.key, name=…)`, make active, then `post_bootstrap_hooks(aid)` instead of today's bare `drop` + sync/link: it evicts (via `client_pool.evict` → each backend's `drop`), clears the dead-session pause, loads through `_load_client`, restarts the pump (a running `FanslyWebSocket` holds its client object, `server.py:1256-1258`, so without the restart a relink keeps the stale token) and syncs + links. Success answer unchanged: `{"ok": true, "account_id", "platform": "fansly", "name"}`. Detail never echoes the token.
- **Collision check.** `accounts.ensure_platform(aid, key)` raises `accounts.PlatformCollision` when the account already exists on another Platform: its meta's Platform via `platforms.get`, or, with no meta, the Platform whose session file is in the directory. A missing directory or the same Platform passes. The Fansly route maps it to 409; `session_bootstrap.persist_session` calls it with `ONLYFANS.key` before its mkdir and `/admin/session/bootstrap` maps it to 409 instead of today's catch-all 500. The Browserbase login (`remote_login.py:889-904`) binds the proxy to the captured `uid` before it persists, so it calls `ensure_platform(uid, ONLYFANS.key)` before `bind_proxy` and fails the job with the collision reason; a refused capture changes no proxy binding. It fires only where today's code would overwrite another Platform's Creator: `ensure_platform` only reads (meta, then the directory listing), raises nothing but `PlatformCollision` (an unreadable meta counts as no meta), and passes a fresh id, an OnlyFans meta, an unknown key and a directory holding only `latest.json`/`session_*.json`, so with no collision both OnlyFans writers run today's code unchanged.
- **Schema.** None. Account meta keeps `platform` as written today; no migration.
- **Contracts.** Unchanged: both session routes' request and success shapes, the 502 body, push preference keys. New: 400 on unproven Fansly identity, 409 `PlatformCollision` on both session routes, both carrying `detail`. The app's Fansly card already renders status + body on failure.
- **Platform recipe doc** beside `docs/platforms.md`, one pointer line added there: ticket 06's 11-step table (steps 0–10, check and model per step), the owner's action order (item 6), the Trap list (unread source, purchase visibility, id width, time units, money units), the bounded claim (one entry + one Backend module covers Relay dispatch only; capture route, `/img` allowlist, extension host matches, the app Platform table and the `Dockerfile` runtime-file `COPY` list (`Dockerfile:74-75` names five Fansly files) are separate edits), what a site copies vs imports (item 2), and what stays parked until site #2's capture (signer, socket envelope, money codes, its Lacks flags, account-id prefixing, popup layout).
- **Order of work** (ticket 01's slices): `platforms` + scan and dispatch tests red → client / socket / drop / error seams → revenue lane → Lacks flags + free follow → session files + push keys → session ingest → recipe doc → full `scripts/run-tests.sh`.

## Testing Decisions
Three seams, each a public interface; nothing added to `service/` for tests.
- **Registry surface + source scan** — `service/tests/test_platform_registry.py`. Table cases on `get`/`for_account` (missing, `"onlyfans"`, `"fansly"`, unknown → right entry), `KEYS`, `SESSION_FILES`, `backends()` is `(fansly_backend,)`, every Backend module exposes the seven contract names, `Lack` members' values equal their names. Scan: `ast` over every `service/**/*.py` except `service/tests/`; fails on a string constant equal to `fansly` (case-insensitive), any `FANSLY` reference, or a `Compare` node with a `get_platform(...)` call as an operand (so `get_platform(a) != "onlyfans"` can't bypass it, while raw reads such as `push_send.py:161`'s `to_thread(accounts.get_platform, aid)` stay legal), outside `platforms.py`, `accounts.py` (definer), `fansly_backend.py`, `fansly_revenue.py`, `accounts_admin_api.py`, `automations/_outbound_guard.py` (banned-word list), and the item-7 files for OnlyFans comparisons. Prints `file:line` per hit.
- **Real dispatch entry points** — `service/tests/test_platform_dispatch.py`. With meta absent, `platform: "onlyfans"`, and unknown key: `server._load_client`, `automation_executor._make_client` return the `client_pool` client; `_ws_pump_for_account` builds `OFWebSocket`; `transaction_ingest.run_one_tick` and `purchase_poll.run_fast_tick` run the ledger path and never call `revenue_tick`. With Fansly meta each reaches `fansly_backend` (module functions monkeypatched). `client_pool.evict` calls `drop` on each backend, including a fake third entry patched into `platforms.ALL` (so a hard-coded Fansly drop fails), and still returns early when `only=` loses. Two concurrent Fansly revenue ticks serialize on `_tick_locks[aid]`. The first request after import to a real Shim write route whose Shim raises `FanslyAPIError` answers the 502 body above; an exception carrying `status_code = 501` answers 501. `POST /api/of/v2/scheduled-sends` on Fansly with media or price → 400; the long-delay schedule route on Fansly calls `check_sendable` before enqueue (a refusal → 400, no `scheduled_jobs` row); both on OnlyFans reach today's path. Existing tests that patch `is_fansly` or swap `sys.modules["fansly_backend"]` retarget to the registry: `test_fansly_revenue.py:126,398,417,519,579-582`, `test_fast_poll_tiers.py:116-130`, `test_automation_executor.py:1543-1549`, `test_scheduled_send.py:306-317` (the eager registry holds the original module, so the swap must patch `platforms.FANSLY`'s backend instead).
- **Session ingest** — `service/tests/test_session_ingest_identity.py`, under `_harness`, with all four `accounts` path settings redirected to a temp root before `server` is imported (precedent `_agency_fixtures.py:51-63`; `_harness` binds the DB only and `server` runs `migrate_legacy()` at import, `server.py:244`). `identify` itself: a real Shim with its `_request` replaced by a recorder — a blob without `device_id` fetches `/device/id` before `/account/me`, and no file appears. `TestClient` on `POST /admin/session/fansly` with `fansly_backend.identify` monkeypatched: `me()` raises → 400, nothing on disk; id mismatch → 400, nothing on disk; existing OnlyFans Creator with the same id → 409, its meta and files byte-identical; success → file 0600 + meta `platform: "fansly"`, `post_bootstrap_hooks` called once with the id, and the Creator in `list_accounts()` with `has_session`; relink of a Fansly Creator → 200 and the pump restarted. `TestClient` on `POST /admin/session/bootstrap` with a curl whose `user-id` is a Fansly Creator's id → 409, directory untouched; the same route on a fresh id and on an existing OnlyFans id answers and writes as it does without the check (status, body, files, meta), and `ensure_platform` on a corrupt `meta.json` passes. `remote_login`'s capture step with that id → job error, `bind_proxy` never called.
- Every new test file runs as a script and exits non-zero on failure, like `test_ws_pump_evict.py` (the runner executes files directly, `scripts/run_tests_parallel.py:45-49`; a bare `def test_*` runs nothing).
- OnlyFans behaviour held by the full `scripts/run-tests.sh` (unchanged OnlyFans suites green).

Prior art: `test_ws_pump_evict.py` (pump driven with fakes, `get_platform` patched), `test_fansly_ws_pump.py`, `test_fansly_revenue.py`, `test_background_reads_peek.py` (`ast` source scan), `test_accounts_freshness.py` (`TestClient` on admin routes).

## Acceptance
```sh
set -e
cd repo
PY=$PWD/venv/bin/python
test -f service/platforms.py
nice -n 10 $PY service/tests/test_platform_registry.py
nice -n 10 $PY service/tests/test_platform_dispatch.py
nice -n 10 $PY service/tests/test_session_ingest_identity.py
for t in fansly_revenue fansly_ws_pump fansly_unsupported_writes fansly_cancel_scheduled_route ws_pump_evict route_order audit_credential_scrub fast_poll_tiers automation_executor scheduled_send; do nice -n 10 $PY service/tests/test_$t.py || exit 1; done
! grep -rn --include='*.py' 'is_fansly' service fansly
! grep -n 'fansly_session.json' service/accounts.py
test -f docs/platform-recipe.md && grep -q 'platform-recipe.md' docs/platforms.md
grep -qi 'trap list' docs/platform-recipe.md && grep -q 'Relay dispatch' docs/platform-recipe.md
grep -qi 'action order' docs/platform-recipe.md
test "$(grep -cE '^\| *(10|[0-9]) *\|' docs/platform-recipe.md)" -ge 11
for w in 'unread source' 'purchase visibility' 'id width' 'time units' 'money units'; do grep -qi "$w" docs/platform-recipe.md; done
nice -n 10 scripts/run-tests.sh
# owner-run after merge (calls fansly.com; agents never run it): local relay on a temp accounts dir (never service/chatterly.db, never prod), nice 10: paste a Fansly blob with a junk token in Add creator -> 400 shown in the card, no new dir under sessions/accounts/; paste the owner's real blob -> Creator listed with its name
```

## Depends on
None — first Phase; 1b, 1c and 1d build on it.

## Out of Scope
- Capability test generalisation and its runner entry: Phase 1b; 1a only exposes `backends()`.
- Gating Unsupported/Blocked Shim methods, money changes: Phase 1b.
- App Platform table, `can`/`useCan`, the Fansly card's `name: null` wording: Phase 1c (the card already shows refusals).
- OnlyFans identity-before-write: OnlyFans ingest derives its id from the signed capture, and the owner froze OnlyFans behaviour.
- Account-id prefixing: parked until site #2's ids are seen (ticket 06 item 5).
- Shim split, shared Shim core: rejected (ADR-0053).
- Capture-rig host parameterisation: waits for site #2 (ticket 06 item 4).
- Capture route, `/img` allowlist, login extension hosts for a new Platform: separate edits, named in the recipe.
- A loud failure on unknown `meta.platform`: ticket 01 keeps the OnlyFans fallback.
- Cross-Agency relink rules (which owner may replace whose session or gain a link): pre-existing and shared with the OnlyFans bootstrap; identity proof now limits it to whoever holds the Creator's valid token.
- A lock across concurrent captures of one id: the re-check after `identify` narrows it; a real cross-Platform id clash waits for site #2's ids (ticket 06 item 5).
- Session discovery for a directory with a session blob but no `meta.json` (`_initialise_account_from_sessions` reads `session_*.json` only): the Fansly route always writes meta; unchanged.
- Passing the re-link row's expected id from the app: Phase 1c's card.
- Slop run: owner constraint.

## Further Notes
- ASSUMPTION: Lacks flags are a `str` `Enum` whose values equal their names (rung 5: a typo fails at import, and Phase 1c's Drift test reads plain strings via `Lack.X == "X"`); overturned if 1c needs a separate name list.
- ASSUMPTION: the `Shim` export and the handler's `status_code` read land here; 1b and 1c only consume them (coordinator ruling on shared ownership, rung 5: two lines that keep Fansly's 502 bytes); overturned if 1b's owner wants them in its own diff.
- ASSUMPTION: the Fansly route reuses `post_bootstrap_hooks` (rung 3: the OnlyFans and Browserbase writers share it, `accounts_admin_api.py:167`, `remote_login.py:910`); overturned if clearing the dead-session pause misfires on Fansly.
- ASSUMPTION: `accounts` imports `platforms` at call time inside its two session probes, breaking the `accounts → platforms → fansly_backend → accounts` cycle (rung 3, call-time imports as at `server.py:1916`); overturned if `platforms` stops importing Backend modules eagerly.
- ASSUMPTION: `identify(session)` lives on `fansly_backend` only, not in the Backend module contract (rung 5; ticket 01 item 9 keeps the session route site-specific); overturned when site #2's route wants a shared ingest.
- ASSUMPTION: 400 for unproven identity, 409 for collision (rung 3: the session routes already 400 bad input); overturned if the app needs distinct codes.
- ASSUMPTION: the collision check also guards the OnlyFans writers `persist_session` and the Browserbase capture, kept only because it reads, raises nothing else and fires only where today's code would overwrite another Platform's Creator (rung 4; a no-collision test pins today's outcome); overturned if the owner wants OnlyFans ingest strictly byte-identical even on a collision, or if that test shows any no-collision change.
- ASSUMPTION: the scan also bans comparisons on a `get_platform(...)` call outside `platforms`/`accounts`, so `get_platform(a) != "onlyfans"` can't bypass it, while raw reads stay legal (rung 4, narrower than a blanket call ban and beyond ticket 01 item 11's wording); overturned if a raw-read caller turns into a branch.
- ASSUMPTION: `automations/_outbound_guard.py` joins the scan allowlist; its `"fansly"` is a banned outbound word, not a Platform branch (rung 1: `_outbound_guard.py:24`).
- ASSUMPTION: the recipe doc is `docs/platform-recipe.md` with a pointer line in `docs/platforms.md` (rung 5; CONTEXT.md says "beside `docs/platforms.md`"); overturned if the owner renames `docs/platforms.md` first.
- ASSUMPTION: `shared_refresher.py:274` keeps its own flag `SHARED_REFRESH` (carried from ticket 01); overturned if its cause is found.

## Review
codex, 2026-11-24. Blind call (B, 10 findings) and draft call (D, 12 findings; first draft run was killed, rerun completed rc 0). Each was checked against the code.

- B1 Collision in both directions, before any mutation, including Browserbase — **accept**: `remote_login.py:889-904` binds the proxy before `persist_session`, so `ensure_platform` now runs before `bind_proxy`. The concurrency half is **partial**: there is a re-check after `identify`, and a lock is Out of Scope.
- B2 Prove identity with a pathless, unpooled client, so a failure preserves prior state — **accept** (already specced). `FanslySession.save` no-ops with `path=None` (`fansly_client.py:126-129`), and the empty-id → 400 case was added.
- B3 Who may re-link which Creator (tenant gate reads query/path, not body) — **partial**: the behaviour is pre-existing and shared with the OnlyFans bootstrap, and the plan never asked for it. It is now named in Out of Scope. Passing the row's expected id is 1c's card.
- B4 Success must mean a usable Creator and a pump on the new credentials — **accept**: the route now calls `post_bootstrap_hooks`. `FanslyWebSocket` holds its client (`server.py:1256-1258`), so a relink without a restart kept the stale token. The sync/link failure still answering ok is shared with the OnlyFans path: **reject** for this Phase.
- B5 Test at the real route with isolated session root and DB, set before `server` import — **accept**: `_harness` isolates the DB only. The accounts paths are now redirected per `_agency_fixtures.py:51-63`, and a real-Shim `identify` seam was added.
- B6 Three viable cuts — **reject**: ticket 01 binds the registry plus Backend module cut and ADR-0053 binds the OnlyFans default path; this is informational.
- B7 Unknown metadata: dispatch → OnlyFans, but `sign_rules` excludes it — **partial**: confirmed (`sign_rules.py:101`, `link_prewarm.py:162`, `vault_collect.py:166`). Ticket 01 item 7 keeps them untouched, so story 3 and the item-7 decision now say the exclusion stays. The table test pins all four cases.
- B8 Drive Fansly through the dispatch consumers (502 body, eviction, shared lock, both schedule gates) — **accept**: added the lock-serialization case, the first-request real-route 502 case and both schedule-route cases. The lock now stays explicitly with the callers.
- B9 Literal scan would flag the outbound word list; the capability check belongs to 1b — **reject**: `_outbound_guard.py` is already allowlisted, and the capability check is already 1b's (Out of Scope).
- B10 Falsify with a third Backend module; the Dockerfile copies five named files — **partial**: a fake third entry is added to the eviction test and the `Dockerfile` COPY list is named in the recipe's bounded claim. A full third Shim rehearsal is site #2's step 6.
- D1 Concurrent captures can claim the id during `me()` — **partial**: same as B1. The re-check after `identify` narrows the window; a lock is YAGNI until site #2's ids exist.
- D2 Identity probe drops blobs without `device_id` — **accept**: `identify` calls `ensure_device_id()` when it is missing (`accounts_admin_api.py:182`, `fansly_client.py:196-197`), the written blob keeps the fetched id, and a recorder test pins the order.
- D3 Reverse guard comes after a proxy write; no 409 route test — **accept**: same fix as B1, plus `TestClient` cases on `/admin/session/bootstrap` → 409 and on the remote_login capture step.
- D4 Acceptance exits 0 after failed checks; a bare `def test_*` runs nothing — **accept**: added `set -e`, and new tests must run as scripts that exit non-zero.
- D5 Deleting `is_fansly` breaks unported suites — **accept**: confirmed in `test_fast_poll_tiers.py:116-130`, `test_automation_executor.py:1543-1549` and `test_scheduled_send.py:306-317`. All are now retargeted and added to the Acceptance loop.
- D6 Scan misses the raw `"onlyfans"` comparisons, and the blanket `get_platform` ban overreaches — **partial**: the "hold no literal" wording is fixed and those three stay untouched per ticket 01 item 7. The ban is narrowed to comparisons on a `get_platform(...)` call, so `push_send.py:161`'s raw read stays legal.
- D7 Both schedule gates can regress with green Acceptance — **accept**: POST-level cases added for both routes on Fansly and OnlyFans.
- D8 A blob-only directory without meta stays invisible — **reject**: the Fansly route always writes meta, and `_initialise_account_from_sessions` reading only `session_*.json` is pre-existing. Named in Out of Scope.
- D9 Backend tests pass with Fansly hard-coded — **accept**: a fake third `ALL` entry covers eviction, and the 502 case drives a real route whose Shim raises on the first request.
- D10 Story 19 promises labels 1c never reads, and the `Shim` export is 1b's — **partial**: the sibling facts say 1c reads keys and Lack names as plain strings, so `Lack` is now a `str` Enum and story 19 is reworded. The `Shim` export and the `status_code` handler move into 1a's contract because 1b needs them. 1b's "additive" line is gone: 1b now only consumes both (Six hats White 1).
- D11 Depends on omits the live-proof prerequisite; the probe calls fansly.com — **partial**: the manual line is now owner-run after merge and agents never run it (floor 2). Offline proof is the mocked-`identify` route tests, and Depends on stays None.
- D12 A two-line recipe passes the greps — **accept**: added greps for the 11 step rows, the owner's action order and all five trap names.

### Six hats
Plan review, 2026-11-24 (`multi-platform-p1-plan-review.md`). Shared parts follow the coordinator's one-owner table there.
- White 1 (`Shim` export and `status_code` handler claimed by 1a, 1b and 1c) — **accept**: 1a owns both; 1b and 1c now only consume them. No change here beyond the ASSUMPTION's wording.
- White 2 (card `name: null` wording and the relink's expected id handed to a 1c card that owned no change) — **accept**: 1c now owns the card change; Out of Scope lines here stand.
- Yellow 1 (default path, AST scan, fake third backend, identity before writing) — **accept**, no change.
- Green 3, collision check only on the Fansly route — **partial**: kept on `persist_session` and the Browserbase capture, but only because it reads, raises nothing but `PlatformCollision` and fires only where today's code would overwrite another Platform's Creator; that condition is now written into Collision check, and a no-collision `/admin/session/bootstrap` test pins today's status, body and files. Dropping it would leave an OnlyFans capture free to flip a Fansly Creator, which ticket 06 item 5 names as a hole to close.
