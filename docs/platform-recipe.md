# Platform recipe

How a new Platform (site #2 onward) joins the Relay. Terms follow `CONTEXT.md` → Platforms; decisions in ADR-0053 to ADR-0057.

## What one entry buys

One Platform registry entry plus one Backend module covers **Relay dispatch** only: client, Live connection, eviction, revenue tick, send check, API error and Lacks flags. OnlyFans has no Backend module; its empty slot is the default path.

These are separate edits, each owned by a step below:

- capture route (`service/accounts_admin_api.py`, Fansly's is `POST /admin/session/fansly`)
- `/img` host allowlist (`service/img_api.py`)
- login extension host matches and interceptor (`loginExtensionMulti/manifest.json`, `fansly_interceptor.js`, `fansly_bridge.js`)
- the app Platform table (`PLATFORMS` in `app/lib/platform.ts`)
- the `Dockerfile` runtime-file `COPY` list (Fansly's names five `fansly/*.py` files; never the whole folder)

## Registry contract

`service/platforms.py`:

- `Platform(key, label, session_file, backend, lacks, free_follow=False)`, frozen
- `Lack`, a `str` Enum, value == name: `FOCUS`, `REFERRALS`, `WALL_MEDIA`, `SERVER_SCHEDULE`, `NEAR_SCHEDULE_MEDIA`, `HISTORY_UNREAD_GATE`, `UNREAD_TOTAL`, `SHARED_REFRESH`
- `ONLYFANS`, `FANSLY`; `ALL`, `KEYS`, `SESSION_FILES`
- `get(key)` (unknown or `None` → `ONLYFANS`), `for_account(aid)`, `backends()`

A caller reads `p = platforms.for_account(aid)` and runs today's OnlyFans code when `p.backend is None` or the Lack is absent. Never compare a Platform key outside the registry's files. The source scan (`scan()` in `service/tests/test_platform_registry.py`) only catches the keys and entry names it lists, Fansly's today, so it covers a new Platform only once step 6 extends it.

Backend module contract (`service/fansly_backend.py` is the model):

- `get_client(aid)` — cached Shim client; `FileNotFoundError` when no session is captured
- `drop(aid | None)` — evict one or all; `client_pool.evict` calls every backend's
- `ws(client)` — the Live connection
- `async revenue_tick(aid) -> TickResult` — takes no lock; callers hold `transaction_ingest._tick_locks[aid]`
- `check_sendable(**kw)` — the Shim's send check
- `APIError` — registered by the server's startup loop over `ALL`
- `Shim` — the Shim class, for the Capability test

Fansly's entry reads its `session_file` from `fansly_backend.SESSION_FILENAME`; that constant is a convention, not part of the contract.

## Steps

A step is done when its check passes.

| # | Step | Check | Model |
|---|---|---|---|
| 0 | Triage: logged-out look at signing headers, anti-bot challenge, JSON API host, websocket | scorecard row per site | Sonnet medium |
| 1 | Owner: creator + fan accounts, two Chrome profiles on two ports | both account ids print before any capture | owner, Sonnet |
| 2 | Auth / signer | signer reproduces every captured request; authenticated identity GET returns the creator | Opus; Fable consulted |
| 3 | Free capture loop → recipes doc | every row proven or ruled out with evidence | Sonnet medium |
| 4 | Shim | shape tests on scrubbed fixtures; Capability test passes | Opus |
| 5 | Websocket | recorded-frame translate test and pump test: one persisted inbound row, one automation trigger | Opus |
| 6 | Registry entry + Backend module; `Dockerfile` runtime `COPY` names the new Shim package files | `scan()` flags the new key and entry name; the new Backend module (plus any revenue or route file) is on `ALLOWED`; the registry test's hard-coded `ALL` / `KEYS` / `SESSION_FILES` / `backends()` / `free_follow` asserts name the new entry; registry, dispatch and scan tests pass; `scripts/run-tests.sh`; the image imports the Backend module | Opus |
| 7 | Session capture: extension hosts + interceptor, relay route, app login card, wizard entry | identity proven before anything is written; cross-Platform id collision rejected (409); link and relink through the real modal | Opus, Sonnet screenshots |
| 8 | `/img` host allowlist | avatar 200, unlisted host refused | Opus |
| 9 | App Platform table + Capabilities | vitest + Platform switch screenshot | Opus |
| 10 | Paid capture + revenue lane | each Proof purchase reconciled to its receipt: kind, amount, currency, buyer; one row across websocket + poll + restart; free actions bank nothing | owner, Opus |

Step 2 and the capture rig: `fansly/capture/start_chrome.sh` already takes `PORT` + `PROFILE`; host parameterisation waits for site #2.

Step 7's route follows Fansly's order: validate id → collision check → prove identity on an unpooled, pathless client → collision check again → only then write session (0600) + meta and run `post_bootstrap_hooks`. Unproven identity → 400, collision → 409, nothing written either way.

## Owner's action order

One Capture session per Platform, creator side recorded before and after each action:

1. tier + payment method
2. follow
3. DMs, typing, read both ways
4. free media
5. list create / add / members / rename / delete
6. block + unblock
7. username search
8. one paid sub (not a gift code)
9. one-person broadcast: one send, one schedule + cancel
10. one chat PPV at minimum price
11. one chat tip
12. optional post tip and post unlock
13. auto-renew off

Free actions (1–7) turn Blocked methods into built or Unsupported ones. Paid actions (8–12) are Proof purchases: a money code joins the Banking set only after one (ADR-0055).

## Trap list

Fields whose names lie. Fansly's cost was here, not in the build. Each site's recipes doc carries its own row per trap:

- **Unread source** — which field the creator's unread state really comes from, and whether the creator reading marks it. Most of Fansly's later fixes were read/unread meaning.
- **Purchase visibility** — what the creator side can see of a purchase. Fansly has no creator-side sales ledger; its one money signal is a notification row (`service/fansly_revenue.py`), gross only, refunds invisible.
- **Id width** — ids above 2^53 lose digits in the browser's `JSON.parse`. Fansly snowflakes do; every id leaves the Shim as a string.
- **Time units** — seconds vs milliseconds vs fractional seconds, per field. Fansly mixes millisecond ints with a seconds-with-fraction `createdAt` (`fansly/STATIC_VALUES.md`).
- **Money units** — dollars vs cents vs thousandths, per field. Fansly's `accountMediaPrice` is 1/1000 dollar.

## Copy vs import

- **Copy:** the `fansly/` layout (client, signer, Shim, websocket, capture tooling) and `service/fansly_backend.py` as the Backend module template, plus the Unsupported / Blocked method markers (`fansly_unsupported` / `fansly_blocked` in `fansly/fansly_shim.py`) until they move to neutral names. One whole Shim per Platform; never split into shared parts (ADR-0053).
- **Import:** `service/of_shapes.py` readers, the outbound word guard (`_guard_outbound` in `service/of_client.py`; Fansly's local copy also flattens its HTML and stays local).

## Parked until site #2's capture

Signer, socket envelope, money codes, its Lacks flags, account-id prefixing, popup layout, neutral names for the Unsupported / Blocked markers. Decide each from that site's capture, not from Fansly's.
