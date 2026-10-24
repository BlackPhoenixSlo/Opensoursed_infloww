# A soak harness runs the real relay against a fake OnlyFans on loopback

**Status: accepted** (2026-10-23; phase 1, the fast profile). The relay's only production change is two environment seams; with them unset it behaves as before.

`scripts/soak.sh fast` starts the relay as the Dockerfile ships it and points it at a fake OnlyFans (`soak/fake_of`, a Starlette app) served on loopback. It then plays a short scenario as OF would and checks what the relay stores, serves and announces. The scenario is one creator: a fan DMs, the operator reads and replies, a fan tips, a PPV is sent and bought, the ledger lists both, and the operator goes offline and comes back. Each feature is one Python file, `soak/features/<x>.py`, with an `ORDER` and `async def scenario(ctx)`. There is no scenario DSL. The fake is out of process from the relay's point of view: the relay's client (curl_cffi with chrome impersonation, and `websockets`) cannot be mocked in process, so the fake is a real HTTP and WS server, run in the harness's event loop.

The seams:

- `OF_API_ORIGIN` (`service/of_origin.py`, read by `service/of_client.py`). When set, the API base, the `/hash` URL, the absolute-path URL builder and the 2313.js chunk URL (`service/session_bootstrap.py`) all derive from it. It must be a bare loopback origin (`127.0.0.1`, `localhost` or `::1`, no userinfo or path; it is rebuilt from scheme, host and port); anything else raises at import, so a relay can never be pointed at a third party by environment.
- `OF_API_LOG_PATH` (`service/server.py`), so a run's API log goes to its own dir instead of `/tmp/of-api.log`.

There are no tick-interval environment variables. Where the fast profile needs a slow loop now, it calls the relay's existing on-demand routes, such as `POST /admin/ingest/transactions/{id}/run`.

One loop had no such route: the subscriber-roster crawl (`lifecycle_messages.refresh_roster`, 25 min TTL), which is the only way the relay learns an expiry or a renew-off. Phase 2 adds `POST /admin/roster/{account_id}/crawl`, modelled on the ledger run route: it runs the same crawl under the same per-account lock with `force=True`, which skips the TTL, and answers the crawl's stats. Nothing calls it on its own; with no caller the relay behaves as before.

Isolation: each run copies the Dockerfile's COPY set, filtered by `.dockerignore`, into a temp dir. The relay gets a fresh SQLite, every `/tmp` default moved into the run dir, no LLM keys and no proxies, and a dead `HTTPS_PROXY`. The runner binds both loopback sockets and hands the relay its socket with `uvicorn --fd`.

The fake publishes signing rules drawn from the run's seed, in a chunk shaped like OF's. The relay's own `derive_rules_from_chunk` has to recover them, and the fake verifies every signed request against an independent implementation. Responses are templated from the captured fixtures in `app/lib/__fixtures__/of`, with the world's values swapped in. A request the fake has no route for is a 404, and the report lists it as unmodelled.

The checker only reads:

- SQLite opened read-only;
- relay HTTP called the way the app's hooks call it, never `refresh=1` (a refresh would heal the defects a probe is looking for);
- the `/events` SSE stream.

Presence is an explicit scenario step. The one harness write to the relay's DB is `operator_offline`, which ages every principal's `last_seen_at` past the 600 s window; HTTP probes are blocked while it lasts. Only the 30 s purchase fast poll is presence-gated; the ledger supervisor is not.

Every expectation is keyed by a check id from the failure-point catalogue, `soak/coverage.py` (public ids only), and the report prints how many of them a run exercised; a key with any other id is refused. A final `HARNESS:signatures` expectation fails the run if the fake saw any badly signed request or WS auth failure. Today's code is red on known defects, so `soak/profiles.py` holds a known-red registry: an entry fails without failing the run, and an entry that passes is reported as `FIXED (remove from known_red)`. Phase 1 is done when the fast profile exits 0 with only registered known-reds failing. On 2026-10-23 that was 29 pass (two of them HARNESS preconditions) and 3 known-red: the WS tip path never announcing the transaction; a replayed frame bumping unread again; and, found by the harness, `provider_event_id` stored NULL for every OF frame, so `event_inbox` does not dedupe a replay.

The fake is not an oracle. Derived values (spend, gross and net) are hand-written literals in the feature, not computed by the fake from the relay's code. The claim a green run makes is scoped to "given OF behaves as captured in the fixtures, captured 2026-10-17..2026-10-18" (`soak/README.md`).

Ids come from one module, `soak/ids.py`: 18 digits starting `900`, so they cannot be confused with a real account. A unit test rejects any other run of six or more digits under `soak/`. Core `soak/` names no private feature and cites only public files, so it runs in the public tree; private features add their own files under `soak/features/`.

## Consequences

- curl_cffi's chrome profile sends `Upgrade: h2c` on plain http, and uvicorn's httptools parser then drops the request body. The fake therefore runs on h11. Production is unaffected: the relay only speaks https to OF.
- The `900…` ids sit above 2^53 and above the relay's synthetic id bands (from 5e15), unlike production's ten-digit ids. Phase-1 paths do not compare against those bands, but a feature that does must account for it.
- Cadence-bound behaviour (600 s cooldowns, the 25 min roster crawl, the 600 s chats cache) is not covered by the fast profile.

## Considered Options

- **A YAML scenario DSL.** Rejected for phase 1: one Python file per feature is smaller and debuggable.
- **In-process mocks (respx or monkeypatched clients).** Rejected: they cannot intercept curl_cffi or `websockets`, and would not exercise the relay's real client.
- **Clock scaling, fault injection, several seeds, a request census.** Deferred: none is needed to prove the fast, WS- and HTTP-driven paths.
- **Tick-interval environment variables.** Rejected: the existing on-demand routes reach the same code without a second production seam per loop.
- **Probes that refresh from OF.** Rejected: `refresh=1` reconciles from OF and would hide the very drift a probe checks for.
- **Running the app (Next.js, a browser) too.** Deferred: the checker calls the relay as the app's hooks do.
