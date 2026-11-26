# Caller tag and prod proof
Type: grilling
Status: resolved 2026-11-26
Blocked by: 

Tag each chat-list request with its caller (autofill | replay | scroll | loadmore | poll | warmup | prefetch | search) and log it in the relay so attribution is measured. Decide header name, where it is set in app/hooks/useChatList.ts fetchPage, relay log line, and the post-deploy proof (WATCH.md check in scripts/proxy-health/watch.py or reuse of_429_absorbed).

## Answer
**Header: `X-List-Caller`.** It follows the house pattern of `X-Priority` and `X-Account-Id` (relay.ts:89-91). Relay and app are same-origin (`RELAY_BASE = ""`, relay.ts:12), so no CORS change is needed.

**Values (closed set).** `mount | replay | warmup | prefetch | poll | autofill | fill | scroll | loadmore | search | refresh`. I added three to the ticket's list:
- `fill`: owe/group fill, which is not the same as viewport autofill;
- `mount`: cold page 0;
- `refresh`: manual refresh, otherwise counted as replay.

**App side**
- New `app/lib/chatListCaller.ts`: `type ListCaller` plus a pure `listCaller({ query, refresh, fetchMore, pending, warming, offset, cached })`. Rules, first match wins:
  1. `query` → `search`
  2. `refresh` → `refresh`
  3. `fetchMore` → `pending ?? "scroll"`
  4. `warming` → `warmup`
  5. `offset > 0 || cached` → `replay`
  6. otherwise `mount`
- Vitest table: one row per rule, plus a `fetchMore` row with no pending caller.
- `useChatList`:
  - `callerRef = useRef<ListCaller | null>(null)`;
  - `loadMore(caller)` sets the ref, then calls `fetchNextPage({ cancelRefetch: false })` (ticket 03);
  - the queryFn (:531) reads `fetchMore` from `qc.getQueryState(queryKey)?.fetchMeta?.fetchMore`. The queryFn `direction` is `forward` for walks too (infiniteQueryBehavior.ts:62), so it cannot tell them apart;
  - `cached` = query data has pages; `warming` = a module `Set` of key hashes that useCreatorWarmUp.ts:26 fills before its invalidate and clears when it settles.
- `fetchHead` (:560) passes `poll`; the `prefetchModelChatList` queryFn (:370) passes `prefetch`.
- `fetchPage` (:281) takes a `caller` option and passes it in the `relay.get` ctx at :313 and :328. On the All Models fan-out every account gets the same caller.
- `RelayContext` gains `caller?: string`; `buildHeaders` sets `X-List-Caller`.
- `loadMore` caller arguments:

| Call site | Caller |
|---|---|
| FanList.tsx:652 | `fill` |
| FanList.tsx:696 | `scroll` |
| FanList.tsx:730 | `autofill` |
| FanList.tsx:763, :909 | `loadmore` |
| ofMirrorData.ts:357 | `scroll` |

**Relay side**
- server.py: `_current_list_caller()` reads `x-list-caller` from `_request_ctx` (:538), the same way `_current_priority` does (:1848). Values outside the set become `other`; no header becomes `-` (old bundles).
- `list_chats` sets `t["offset"] = offset` inside `with _of_read_timing("chats", aid) as t` (:2564).
- `_of_read_timing` (:2064) appends `caller=%s offset=%s` to the end of the existing line, with `offset=-` for other routes. That is one line per request with no new log volume, and it already carries `status` and `of_calls` (0 = served from cache or a merged in-flight read).
- The hold line (:2550) becomes `list_chats 429 hold account=%s offset=%s caller=%s for %.1fs`.
- Update together:
  - `_FIELDS` in service/tests/test_of_read_timing.py:97, plus rows: header → `caller=scroll`, bogus value → `other`, missing → `-`, chats → `offset=100`;
  - README "OF read timing line" (README.md:506-507).

**Prod proof.** `of_429_absorbed` does not fit: it counts every OF client 429 including background `scrape_chats` (watch.py:488-493) and has no offset or caller. So add a new check in the same PR, `chatlist_deep_auto`, in scripts/proxy-health/watch.py.
- **Log ERE:** `of_read_timing route=chats .*(status=(429|5[0-9][0-9])|offset=[1-9][0-9][0-9])|list_chats 429 hold` (POSIX, no backslash, no `/`).
- **Counts:**
  - `deep_auto` = route=chats lines with offset ≥ 100 and a caller in {mount, replay, warmup, prefetch, poll, autofill, fill};
  - `fail` = route=chats lines with status 429 or 5xx;
  - `holds` = hold lines, split by caller;
  - deep pages from `scroll/loadmore/search/refresh` and untagged `-` go in the detail only (old tabs until reload).
- **States:**
  - **alert** if `fail` > 6/h or `holds` > 4.5/h, which is half the 11-25 baseline (48 failed loads and 39 holds over about 4.3 h), using the `_rate_state` pattern;
  - **watch** if `deep_auto` ≥ 1 or `fail` > 1/h;
  - **ok** otherwise.
- **Detail:** `deep_auto N (by caller), fails N (x/h), holds N by caller, untagged deep N, explicit deep N`.
- **Register it the four ways README:488-502 requires:**
  - function `_w_chatlist_deep_auto` plus constants `CHATLIST_DEEP_OFFSET=100`, `CHATLIST_FAIL_WATCH_PER_H=1.0`, `CHATLIST_FAIL_ALERT_PER_H=6.0`, `CHATLIST_HOLD_ALERT_PER_H=4.5`;
  - a `WATCH_CHECKS` entry;
  - a README table row and a `watch:chatlist_deep_auto` runbook line;
  - `test_watch.py::test_watch_check_states` rows: ok / watch (one replay at 100) / alert (fails over 6/h) / untagged-only = ok.
- **WATCH.md line after the AE deploy:** `- chatlist-429-deep-auto | added <deploy date> | expires +3d | chatlist_deep_auto | <PR url>`

Rung: 2 for the WATCH line and a new check ("no fitting check → add one in same PR"); 3 for the header name (decision.md (d) plus the X-Priority precedent) and for reusing `of_read_timing`; 1 for the baseline numbers behind the thresholds (map.md Notes); 5 for the extra caller values.
ASSUMPTION: the `of_read_timing` line keeps its field order with the two fields appended at the end, and only its own test parses it. Overturned if a collector in oi-proxy-health parses it strictly (grep found only the test and README).
ASSUMPTION: the 5xx/429 set leaves out 401/403 from disconnected models (memory: skip disconnected). Overturned if relay list 502s turn out to wrap 401s.
ASSUMPTION: the `warming` Set is worth about 6 lines. If ticket 02 replaces the warm-up invalidate with a head refresh, drop `warmup` and tag that refresh `poll`.

Evidence: relay.ts:12,64-71,86-91; useChatList.ts:281-314,328,370-373,531-538,560-564,597; FanList.tsx:652,696,730,763,909; ofMirrorData.ts:357; useCreatorWarmUp.ts:26; infiniteQueryBehavior.ts:22,62; server.py:538,1848-1852,2038-2072,2522,2550,2564; test_of_read_timing.py:86-100; watch.py:477-493,1270-1290; README.md:379-410,486-512; WATCH.md:1-3; map.md Notes.

## Reconciled (Codex Astra phase 2: reject → rewritten)
- accept (blocker): capture the initiating trigger on the actual fetch (fetchMeta), not a mutable ref; query mode ≠ click intent; unknown defaults to `auto`, never `scroll`; FanList's stable wrapper forwards the caller.
- accept (major): carry caller (and intent) through `bundleGet` → screens inner read; log bundle-prefetch and joined reads distinctly.
- accept (blocker): refusal is logged inside `_of_read_timing` (with limit, caller, intent, outcome, upstream status); check uses `4*limit` (mirror page 5 = offset 80); a window with too few tagged busy-Creator hops reports `unknown`, not ok; upstream session failures (401-wrapped 502s) excluded.
- accept (minor): `of_429_absorbed` counts only gate retry/gave-up lines — reuse it for scrape side, new `chatlist_deep_auto` for list outcomes.
**Final:** `X-List-Caller` (attribution) + `X-List-Intent` (permission, from 04); new watch check `chatlist_deep_auto` + WATCH.md line on deploy.
