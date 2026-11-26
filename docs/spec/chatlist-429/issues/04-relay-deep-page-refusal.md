# Relay refuses deep pages without a click
Type: grilling
Status: resolved 2026-11-26
Blocked by: 01, 05

Relay /api/of/v2/chats: refuse offsets beyond the auto cap unless the request is explicit (user scroll / Load more / search). Contract: param or header name, response shape (hasMore true + capped flag? 200 empty?), hard limit (4 pages = offset ≥100?), interplay with client dynamic cap, old tabs, other callers of the route (badges, roster-counts, scrape). Also: short 429 hold length (current 1 s; owner: 30 s too long) — keep, or tie to OF retry_after capped small?

## Answer
- **Rule, in `service/chats_page.py`:**
  ```python
  DEEP_OFFSET_MIN = 100
  EXPLICIT_CALLERS = frozenset({"scroll", "loadmore", "search"})
  def deep_page_refused(offset: int, query: str | None, caller: str | None) -> bool:
      return offset >= DEEP_OFFSET_MIN and not query and (caller or "").lower() not in EXPLICIT_CALLERS
  ```
  100 = 4 × 25 rows. It matches `OWE_REPLY_SCAN_CAP` (`FanList.tsx:78`) and the client ceiling (offset 75 or less).
- **Header.** Reuse ticket 05's `X-List-Caller`: one header for both attribution and permission. It is read with a `_current_list_caller()` modelled on `_current_priority()` (`server.py:1848-1852`). It must be a header, not a query param: a param would break the screen-bundle `exactly()` match (`screenBundle.ts:77-79`). The relay cache key ignores headers either way.
- **Route.** At the top of `list_chats` (`server.py:2520`), before the cache, coalesce and OF: if refused, log `list_chats deep page refused account=%s offset=%s caller=%s` and raise `HTTPException(428, "Reload the page to load older chats.")`.
- **Why 428 and not a 200 with an empty page:**
  - An empty page added to `pages` shifts every later offset (`useChatList.ts:529-530`), and `hasMore: false` shrinks the list.
  - With 428, a failed fetch or refetch leaves the cached pages alone (r2-astra: measured, all six pages kept), autofill stops (`FanList.tsx:717`) and fill stops (`:376`).
  - A fake 429 was rejected because it would pollute the 429 metrics ticket 05 uses as proof.
- **Client changes.**
  - `isDeepRefused(e)` (status 428) in `relay.ts`. In `FanList.tsx:839`, hide the banner for it when rows exist.
  - Explicit deep reads skip the screen bundle: `relay.ts:222` does `screenRead` only when the caller is not explicit. Bundle inner requests forward only `x-account-id`/`x-priority` (`screens_api.py:71-84`), so through the bundle an untagged deep All Models read is refused and a tagged one would lose its tag.
  - Mirror chats (`ofMirrorData.ts:344-372`, 20-row pages) are tagged `scroll` only from the scroll listener. Their unattended fill gets refused from offset 100 (page 6).
- **Effect of tickets 01 and 02.** The new client never sends an unattended request at offset 100 or more. The relay rule is the backstop for old tabs, replays of an active list deeper than 4 pages (tagged `replay`, so they fail without harm and keep their rows), and bugs.
- **Old tabs** send no header, so they are refused at offset 100 and above even on a real scroll. They keep their rows and show "Reload…" until they reload. Zero OF calls.
- **Other callers are unaffected.**
  - The badge reads call `OFClient` directly (`badge_reads.py:506`).
  - The roster window is offset 0 (`server.py:2524-2527`).
  - The accounts admin call assembles directly (`accounts_admin_api.py:323`).
  - Mass fans has no offset (`ofMirrorMass.ts:75`).
  - The screens inbox bundle is covered by the inner request context (`screens_api.py:107,312-314`).
- **429 hold: keep as is.** It already follows OF's `retry_after`, clamped to 1–5 s (`chats_page.py:16-17,27-33`; `of_pacing.py:197-202`; `server.py:2547-2550`). The measured 1.0 s is simply OF's "allow 1 seconds". There is also an in-page retry of 2 s or less (`chats_page.py:13`).

Pytest table (`service/tests/test_chats_429_hold.py` or a new `test_chats_deep_refusal.py`), `deep_page_refused(offset, query, caller)`:

| offset | query | caller | expect |
|---|---|---|---|
| 0 | None | None | False |
| 75 | None | None | False |
| 99 | None | None | False |
| 100 | None | None | True |
| 125 | None | autofill | True |
| 100 | None | replay | True |
| 100 | "" | None | True |
| 100 | None | scroll | False |
| 100 | None | loadmore | False |
| 100 | None | LOADMORE | False |
| 100 | None | search | False |
| 100 | "anna" | None | False |

Route tests:
- Untagged offset=100 gives 428, the OF stub is never called, and the relay cache is untouched.
- `/admin/screens/inbox?cursor=100` gives that read status 428.

Vitest: an explicit deep read skips `screenRead`.

Rung: 2 (owner: refuse page 5 and up without a click; no long hold). 1 for the callers and the hold (cited). 3 for the header pattern (`X-Priority`: `relay.ts:91`, `server.py:1848-1852`).

ASSUMPTION: a flat 100-row limit, whatever the `limit`, rather than page index. This is overturned if the owner meant page 5 for 20-row mirror pages (offset 80).
ASSUMPTION: refuse before the cache, even when a fresh relay copy is cached. This is overturned if tagged logs show many refused requests that the cache could have served.
ASSUMPTION: 04 also depends on 05's header. The map lists it as blocked by 01 only, and should add "blocked by 05".
ASSUMPTION: old tabs showing "Reload…" is acceptable.

Evidence: `server.py:2494-2584,1848-1852`; `chats_page.py:13-42`; `of_pacing.py:197-202`; `screens_api.py:71-84,103-123,293-315`; `screenBundle.ts:42-46,75-79,214-243`; `relay.ts:86-97,140-156,209-243`; `useChatList.ts:296,524-540`; `ofMirrorData.ts:173-176,344-372`; `FanList.tsx:78,717,839`.

## Reconciled (Codex Astra phase 2: reject → rewritten)
- accept (blocker): limit is `offset >= 4*limit` (page 5 at any page size), not offset 100.
- accept (blocker): permission is a separate intent header `X-List-Intent: explicit`, set only by click / fresh-scroll handlers for that one page; `X-List-Caller` stays attribution only (search/scroll tags never grant permission).
- accept (blocker, measured): a 428 inside the All Models fan-out committed a partial terminal page (`hasNextPage=false`). Fix: fan-out treats a policy refusal as a page error (no partial commit); `retry` disabled for 428.
- accept (blocker, measured): the real stall is the 45 s GET gate (~40 s seen), not the 1–5 s hold. Chat-list reads get a short total wait budget (≤5 s across gate, in-page retry, client retry), then a fast "OnlyFans busy, try again" with rows kept; the Creator's cooldown is untouched.
**Final:** relay refuses `offset >= 4*limit` without `X-List-Intent: explicit` (428, before cache/OF, logged inside read timing); fan-out-safe; chat-list wait ≤5 s.
ASSUMPTION: 5 s wait budget (owner: 30 s too long). Overturned if explicit deep clicks fail often under the short budget. Falls: 04, 05 thresholds.
ASSUMPTION: old tabs (no header) see "reload to load older chats" on deep scroll until they reload.
