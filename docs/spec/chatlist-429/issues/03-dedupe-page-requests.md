# Dedupe page requests
Type: grilling
Status: resolved 2026-11-26
Blocked by: 

Same-second identical page requests (3–4 per page per hop). Which paths cause them and what is the minimal fix: fetchNextPage({cancelRefetch:false}) in useChatList loadMore, cancelRefetch:false on the warm-up invalidate (useCreatorWarmUp), anything else (duplicate observers/prefetch)? Most dupes are relay-cache hits; decide whether it is worth it for OF budget vs UI correctness.

## Answer
**Decision:** ship the client dedupe, two `cancelRefetch: false` call sites plus a guard change. It saves almost no OF budget: the relay already merges identical in-flight reads (singleflight) and caches each page for 600 s. The gain is UI correctness:
- no cancelled walks that restart from offset 0;
- no dropped next pages;
- one 502 per held key instead of 3–4;
- fewer lane slots used.

The owner chose dedupe, so it ships either way.

**Root mechanism.** These calls cancel any fetch in flight and start again, because `cancelRefetch` defaults to true:
- `fetchNextPage`
- `invalidateQueries` / `refetchQueries`
- `q.refetch`

For lists other than search, the queryFn never passes the abort signal on. So the cancelled HTTP request still reaches the relay, and the restarted fetch asks for the same pages again.

**Every path that can send a same-key page request while another is in flight:**

| # | Path | Duplicates today? | Fix |
|---|---|---|---|
| P1 | `loadMore` → `fetchNextPage()`. Callers: owe/group fill (FanList.tsx:649-653), IO sentinel (:683-697), autofill rAF (:716-733), Load more click (:763), keep scanning (:909), mirror scroll (ofMirrorData.ts:357). Guards only check `isFetchingNextPage`, which is false during a refetch walk. Fill + IO + rAF can also fire in one frame before the re-render. | Yes: cancels a walk or a next page and asks again | **Covered** |
| P2 | Warm-up invalidate (useCreatorWarmUp.ts:25-27). Hover (CreatorTabs.tsx:128) and pick (:72) both chain `.then` on the same `refreshOne` promise (useRosterCounts.ts:99-100), so two invalidates fire back to back and the second cancels the first's walk. Together with the prefetch or mount walk, that gives 3 identical offset-0 requests in the same second (inferred; fits the "3–4 per page per hop" in the log). | Yes | **Covered** |
| P3 | `prefetchModelChatList` (useChatList.ts:367). `fetchQuery` calls `query.fetch` without `cancelRefetch`, so it joins the fetch in flight (queryClient.ts:364-368, query.ts:411-419). | No | Nothing to do |
| P4 | Observer mount or key change calls `#executeFetch()` with no options, so it joins too (queryObserver.ts:100,190). | No | Nothing to do |
| P5 | Head poll `fetchHead` (useChatList.ts:405-420). Checks for idle only at start; it runs outside the query cache, so a walk starting meanwhile can send offset 0 twice. The relay merges it. | Rarely, offset 0 only (not the page that gets 429s) | **Not covered.** Ticket 02 owns the shared head refresh |
| P6 | Broad `["chats"]` invalidates after user writes (useFanListMarkRead.ts:47, ChatActionsMenu.tsx:54/65/100, FanListBulkBar.tsx:78/94, AvatarMenu.tsx:150, ofMirrorChats.ts:594, ofMirrorMessageMenu.ts:346/364, ofMirrorChat.ts:478) | Only on chatter actions, not in the hop pattern | **Not covered** |
| P7 | `retry: 1` (providers.tsx:84). Runs one after the other, and the relay's 429 hold answers it. | No | **Not covered** |
| P8 | OF mirror list uses limit 20 (ofMirrorDataQueries.ts:158), FanList uses 25 (screenBundle.ts:8), so they are different keys on the client and the relay (server.py:2522). Other tabs and devices are merged only by the relay singleflight. | No | Nothing to do |

**Changes**
1. useChatList.ts:597: `loadMore: () => q.fetchNextPage({ cancelRefetch: false })`. This joins any fetch in flight (query.ts:411-419). Ticket 05 adds the caller argument here.
2. useCreatorWarmUp.ts:26: `qc.invalidateQueries({ queryKey, predicate: warmUpMayRefetch }, { cancelRefetch: false })`. Keep the predicate: without it a joined fetchMore leaves the key invalidated, and the next mount replays it.
3. FanList.tsx:
   - fill effect (:651) and autofill (:718): change the guard `q.isFetchingMore` to `q.isFetching`, and add `q.isFetching` to their deps;
   - IO callback (:686): check `qRef.current.isFetching`, and add `q.isFetching` to the IO effect deps (:705), so the observer is rebuilt after a walk lands and fires its first intersect;
   - without this, a load that joins a walk is dropped: the owe fill stalls when the walk returns the same `scanned`, and a user parked at the bottom never gets the next page.

**Test rows (vitest)**
- useCreatorWarmUp.test.ts `warmUpAfter` table: add an `asked: number[]` column (offsets the queryFn received after the warm-up started).
  - Change row `"plain refetch in flight"` to `[0,25], reread false`, asked `[]`, since it now joins the walk.
  - New row `"two invalidates back to back (hover+pick)"`: asked `[0,25]` exactly once.
  - The other rows keep their offsets.
- useChatList.test.tsx, new describe "loadMore joins the fetch in flight":
  - two `loadMore()` in the same tick → one request at offset 25;
  - `loadMore` during a stale replay of 3 cached pages → asked `0,25,50` once each, no restart from 0;
  - `loadMore` while a next page is in flight → no second offset-25 request.
- FanList.test.tsx:
  - sentinel intersecting during a replay walk → exactly one next-page request after the walk lands;
  - owe fill with an unchanged `scanned` still fires after the walk.

Rung: 1 for the paths and library semantics; 2 for doing it at all ("dedupe page requests").
ASSUMPTION: OF budget gain ≈ 0, because concurrent duplicates hit the relay singleflight and cache. Overturned if the ticket 05 tags show `of_calls>0` on duplicate same-second same-offset lines.
ASSUMPTION: losing the warm-up "snap to the badge rows" when it joins a walk is acceptable. The `?bust=` refreshes the badge window (limit `_ROSTER_SCAN_MAX`, a different key), not the 25-row page, so the snap was already approximate. Overturned by a badge-vs-list mismatch report after deploy.
ASSUMPTION: P6 is rare. Overturned if ticket 05 shows many `replay` lines right after mark-read.

Evidence: useChatList.ts:536-537,597,367,405-420; useCreatorWarmUp.ts:13-14,25-27; CreatorTabs.tsx:72,128; useRosterCounts.ts:99-100; FanList.tsx:649-653,683-705,716-733,759-763,909; ofMirrorData.ts:173,357; query-core 5.100.11 query.ts:404-420, queryObserver.ts:100,190,326-328, queryClient.ts:317-321,364-368, infiniteQueryObserver.ts:112-120,156; server.py:2465-2466,2522,2552,2565; relay_coalesce.py:11.

## Reconciled (Codex Astra phase 2: accept-with-fixes)
- accept (major, measured): with `cancelRefetch:false` a click during a 3-page replay never asks the next page. Fix: an explicit click during a replay queues one continuation that runs when the replay settles (scoped to the current list); a failed page needs a new click (no auto retry loop from the sentinel).
- accept (major): roster bust shares the 25-row head key; hover + pick coalesce into ONE post-bust head refresh; include the All Models hop invalidate (`usePickAllModels.ts`).
- accept (major): OF saving is unmeasured → labelled inferred; measured via 05 (leaders by priority + of_calls), poll overlap in tests.
**Final:** loadMore joins in-flight fetches (`cancelRefetch:false`) + queued explicit continuation; warm-up hover/pick/All-Models coalesced into one post-bust head refresh.
