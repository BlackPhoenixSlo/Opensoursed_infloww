# slop/: Chat media through `/img`

Chat media through the relay's `/img` OF-CDN proxy (`service/img_api.py`: disk cache, the IMG_FETCH lane, the
in-slot re-read that collapses a cold-pane herd, by-hash) at volume, many owner tabs opening the same chats at once.
The harness, its knobs and its rules are in `README.md`; this file is only what this flow adds. The scenario's
docstring is its spec (phases, the closed #172 threadpool finding with its runs, bypasses).

## Layout

| Path | Role |
|---|---|
| `seed/chat_media.py` | `seed(w, n_assets)`: about `n_assets` CDN assets (each photo a thumb + its full source), 3-6 photos per chat in 1-3 messages in existing threads, with their `message_media` rows by SQL as the transcoder and `reconcile_rest_media` leave them. Chats `fresh` (signed until `w.now` + 6 h) or `stale` (~10% of photos, Policy expired); fresh photos ~15% on `public.onlyfans.com` (img_api's direct lane), the rest on synthetic signed `cdn2/cdn3.onlyfans.com` URLs; max(2, photos // 25) signed sources > 2 MiB (never disk-cached). `rotate(w, data)`: OF re-signed every fresh signed URL (same host + path, new Policy / Signature). Output in `w.data["chat_media"]`. |
| `lib/img_relay.py` | OnlyFans' media CDN at its wire (`OF` joins `_OfflineOF`'s bases). Inert until the run wrote `of-cdn.json` and armed it (`arm_run`, `POST /__slop/img/arm`; 409 without the file or under `SLOP_LIVE=1`): a loopback fake CDN in the relay process (seeded bytes after `latency_s`; a signed host's missing or expired Policy is 403 AccessDenied), `curl_cffi.requests.Session.request` wrapped so a seeded CDN host goes to the fake (both `/img` lanes), `img_api._IMG_CACHE_DIR` re-pointed into the run's temp dir; `arm_run(..., pictures=True)` serves real pictures (PNG) instead of noise; per Creator a curl_cffi session with synthetic cookies and `creator_headers`. `GET /__slop/img/calls?since=&until=` (every call: key, cookie, OF headers, status, `inflight`), `/stats`. |
| `lib/img_faults.py` | The check names and its faults (below), each patching a product module attribute inside the relay. |
| `scenarios/2026-11-02-img-chat-media.py` | The scenario; its `KNOWN_RED`. |

## Scenarios

- `2026-11-02-img-chat-media`: `agency_inbox` plus `seed/chat_media` (`--img_assets=`, SCALES `img_chat_assets`),
  `lib/img_relay.py` armed with every asset. Each `--users` tab (one owner session's pool) opens its chats like the
  app (`GET /admin/messages/{creator}/{fan}`) and fetches every photo's thumb and full source as MediaTile does
  (`/img?u=&account_id=`, no header, `TAB_CONC` at a time); fresh chats split into the probe's and the herd's, each
  herd chat opened by many tabs at once. Phases, each ended once the img_fetch lane is back to 0 busy: cold (empty
  disk cache), warm, rotated (`chat_media.rotate`), stale (`users // STALE_USERS_DIV` tabs, every signature
  expired), probe-miss and probe-hit (one quiet tab, one fetch at a time), by-hash (each > 2 MiB source with
  `X-Account-Id`, then `/img/by-hash/<h>`). Checks (`lib/img_faults.py`): `BYTES`, `CDN_COLLAPSE` (per cacheable
  asset <= the lane's cap, not == 1), `COLD_HERD` (cold and stale: no `/img` 5xx but the lane's 503, `/admin/streams`
  polled every `STREAMS_POLL_S` under `COLD_HERD_STREAMS_MS`), `WARM_HIT`, `MAX_INFLIGHT`, `BIG`, `DIRECT`,
  `EXPIRED`, `LANE_DRAINED`, `REJECTED`, `BY_HASH`, `NO_OFFHOST`; `TILE_HASH` (a MediaTile-shaped miss answers
  `X-Img-Hash`) is `KNOWN_RED` (SKIP with this run's result). Budgets: the quiet probe's cacheable tiles cold
  (`MISS_P95_MS`) and warm (`HIT_P95_MS`), both vs the last green run; the herd's p95s are metrics only
  (`herd_p95_ms`). `SLOP_LIVE=1`: every check SKIPs. Faults: `img-cache-never-hits` (default;
  `_img_cache_lookup` always misses; targets `WARM_HIT`, `CDN_COLLAPSE`), `img-cache-key-keeps-signature` (the
  cache key is the whole signed URL; `WARM_HIT`), `img-fetch-lane-unbounded` (IMG_FETCH admits everything;
  `MAX_INFLIGHT`), `img-fetch-on-pool-tokens` (the #172 cycle back; `COLD_HERD`, at `--scale=medium --users=200`).
  No UI.
