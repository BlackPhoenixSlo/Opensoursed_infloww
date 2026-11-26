**Measured (owner’s production trace)** — 29 of 39 relay holds occurred at offsets 100/125. That identifies where requests failed. It does not identify which caller issued them or how many duplicate requests reached OF. **Inferred** below covers causes, alternatives, and tradeoffs from static review of `ecacca3ed`, including callers available in Git outside the sparse worktree.

### 01 · What should drive the dynamic 2–4-page cap?

| Alternative | Pros | Cons | Evidence file:line |
|---|---|---|---|
| Visible demand. Start with a two-page ceiling. Admit page 3, then 4, while a visible panel still underfills or Split/Owe has fewer than eight matches. | Uses existing viewport and match signals. Can stop after page 1 when satisfied. | Sparse groups repeatedly qualify for four. Count fetched pages per Creator, since Split filters rows *after* scanning and All Models merges accounts. | `FanList.tsx:370–378,716–730` · `server.py:2582–2584` · `useChatList.ts:325–355` |
| Engagement. Allow page 3 after sustained foreground dwell and page 4 after a user reaches the bottom. | Cheap on short hops. Adapts to an engaged chatter. | Dwell thresholds need measurement. `scrollIntoView` can generate the same scroll signal as a person. | `FanList.tsx:267–278,670–696` |
| Creator pressure, alone or combined with demand. Allow up to four when healthy, three under moderate pressure, two after recent throttling. | Two chatters can get different budgets on a busy and a quiet Creator. | Relay cache hits can hide pressure from the browser. A 429 on page 5 arrives too late to protect that hop. | `server.py:2497–2505` · `of_pacing.py:342–383` |

- **Missing requirements** — Define budget reset on group/chip/search changes, acceptable sparse-group fill, and which signals admit pages 3/4. Count offset 0 as page 1. Apply the ceiling to every automatic path, including search. Define one explicit action per deeper page, including zero-match Owe. Today search bypasses the row cap, a cap click extends it by 200 rows, and zero-match Owe hides “keep scanning.” `fanListPaging.ts:26–52` · `FanList.tsx:758–763,900–913`
- **Falsifiers** — Tagged traces put offsets 100/125 on replay or explicit clicks, or show pages 3/4 add few visible matches and rarely precede a selection. Either finding weakens the case for changing autofill alone.

### 02 · How can hop-back avoid replay while preserving unread and counts?

| Alternative | Pros | Cons | Evidence file:line |
|---|---|---|---|
| Keep cached tails for display and counts. On return or warm-up, refresh page 0 only using the existing head-replacement path. | Preserves All rows and same-session Unread coverage without fetching the tail. | Must cover stale mount, hover prefetch, post-bust invalidation and manual refresh. A refreshed head plus an old terminal tail can have gaps when ranks move. | `useChatList.ts:359–379,405–419,524–541,584–588` · `useCreatorWarmUp.ts:21–27` |
| Trim inactive query data to a prefix before any new observer or prefetch, and trim legacy IndexedDB data before restore completes. Slice `pages` and `pageParams` together, preserving `updatedAt`. | Bounds both same-tab and restored replay. Reuses the provider’s restore hook. | All-based fallback counts can fall. Preserve their source separately if exact parity is required. An Unread exemption still needs head-only reactivation. Late in-flight writes must respect the trim. | `providers.tsx:37–39,80–84,156–174` · `useChatList.ts:529–537` · `FanList.tsx:410–430,478–487` |
| Separate the live head from explicitly fetched tail pages keyed by offset. | Head invalidation cannot rewalk the tail. Explicit pages remain available. | More work for live patches, ordering, terminal-page proof, and count subscribers. | `useChatList.ts:483–490,568–580` · `chatsCache.ts:243–257,510–517` |

- **Missing requirements** — Decide how long cached tails and fallback counts may be stale. Preserve the existing Unread proof: terminal page, current session, stamped pages, no partial result, five-minute expiry off-chip. A cap must never manufacture `hasMore=false`, which also enables whole-Creator mark-all-read. `chatsCache.ts:243–265` · `FanList.tsx:606–616`
- **Falsifiers** — Restore six cached pages and separately hop back after the 30-second stale interval with warm-up enabled. Any unclicked deep GET disproves replay prevention. A newly “complete” partial Unread view, changed fallback badge on identical data, or broadened mark-all-read disproves correctness.

### 03 · What could cause same-second duplicates, and what is the smallest dedupe?

| Alternative | Pros | Cons | Evidence file:line |
|---|---|---|---|
| Join concurrent `fetchNextPage` calls with `cancelRefetch:false`. Group fill, intersection observer and animation-frame autofill can all see the same rendered `isFetchingMore=false`. | One change at their common entry point, including button clicks. The existing stable callback already addresses observer recreation. | Covers one in-flight query. A head refetch already in progress can absorb a click, so verify that an explicit next page still lands. | `FanList.tsx:310–320,649–653,683–696,716–732` · `useChatList.ts:597` |
| Coalesce hover and click warm-up per Creator and refresh only the head after the roster bust. | Targets a second path: hover and selection both call `warm`, which starts prefetch and then invalidates the Creator prefix after the bust. | A completed hover read and a subsequent intentional freshness check are distinct. Suppressing the latter can make badge and list disagree. | `CreatorTabs.tsx:69–73,128` · `useCreatorWarmUp.ts:12–27` · `useRosterCounts.ts:95–106` |
| Join identical in-flight page reads at transport level if duplicates cross query keys or consumers. | Can catch model and merged-view requests for the same Creator/page. | Key by principal, Creator, offset, limit, order, filters and refresh semantics. Preserve cancellation and priority. Relay coalescing already lets background join user-led work, but protects users from waiting on a background leader. | `useChatList.ts:288–296,310–330` · `relay_coalesce.py:45–53` · `relay_cache.py:180–196` |

- **Missing requirements** — Capture trigger, full normalized key, start/end, retry, relay leader/joiner and OF dispatch. A single relay page can make several legitimate OF reads at advancing offsets. `chats_page.py:93–103,111–116`
- **Falsifiers** — Distinct keys, sequential attempts after settlement, or one OF leader serving all arrivals disprove duplicate *concurrent OF work*. Repeated same-key starts from one loader after joining would disprove the proposed minimal fix.

### 04 · What should the relay refuse, and how long should it wait?

| Alternative | Pros | Cons | Evidence file:line |
|---|---|---|---|
| Client enforces its dynamic cap. Relay enforces the four-page maximum: absent explicit intent, refuse `offset >= 4 × limit` before fetching. | Stateless backstop. At limit 25, offset 75 is eligible and 100 requires a click. | Cannot enforce a particular client’s two- or three-page cap. A cutoff hardcoded at offset 100 breaks other limits. | `server.py:2508–2526` · `useChatList.ts:524–535` |
| Send bounded `autoPages=2..4` and per-request `intent=auto/explicit`. Validate depth at relay entry and propagate intent through the inbox bundle. Return a typed, non-retryable “explicit action required” result. | Enforces the selected ceiling on direct and bundled paths. Keeps a policy refusal distinct from exhaustion and throttling. | Client intent is advisory. Define legacy defaults and whether deep cache hits may be served. Keep intent outside the data/coalescing key. | `server.py:2522–2533,2563–2583` · `screenBundle.ts:75–80` · `screens_api.py:293–315` |
| On a real 429, serve a held copy if available. Otherwise fail immediately or allow a short list-specific wait, e.g. 2–5 seconds total, then return a retryable throttle with retry timing. | Bounds chatter wait while respecting the Creator’s upstream cooldown. | Fast failure loses some recoverable reads. The page negative cache already clamps to **1–5 s**. The separate GET gate has a **45 s** budget and `_proxy` maps upstream 429 to 502. Changing cache TTL alone cannot fix the stall. | `chats_page.py:12–32` · `of_pacing.py:103–109,350–369` · `server.py:1979–1980,1996–2011,2497–2505` |

- **Missing requirements** — Set the wait ceiling and retry behavior end to end. Inventory includes OF Mirror’s automatic next page, mass-recipient picker at limit 50, and `/admin/screens/inbox` calling the handler directly. Roster bust shares the page-0 cache through the assembler. Scrape calls `client.list_chats` directly and bypasses the route guard. `ofMirrorData.ts:344–357` · `ofMirrorMass.ts:75` · `accounts_admin_api.py:319–337` · `scrape_chats.py:706–717`
- **Falsifiers** — A denied auto request starts an OF read or stale refresh, one explicit click authorizes later automatic pages, or a cold throttled list still waits ~40 seconds. Exercise both direct and bundled callers and verify page-0 badge folding.

### 05 · How should caller attribution and post-deploy proof work?

| Alternative | Pros | Cons | Evidence file:line |
|---|---|---|---|
| Tag each logical request with an allowlisted origin and trigger: mount/replay, group fill, viewport, scroll, click, warm, poll, refresh, Mirror. Carry tags as metadata through direct and bundled reads. | Measures why the client asked. A header preserves the exact query parameters used for bundle matching. | Bundle fan-out must propagate tags internally. Report unknown callers and joined triggers separately. Priority alone conflates several triggers. | `useChatList.ts:280–305,560–566` · `screenBundle.ts:42–46,75–80` · `screens_api.py:309–315` |
| Attribute actual OF dispatches using the existing caller counter. Pair this with relay events for hit, join, stale serve, gate wait, status and offset. | Separates browser demand, relay work and OF quota. Existing counters already distinguish automation and upstream 429. | Counter path normalization drops query parameters. Caller totals alone cannot establish depth or hop causality. One coalesced leader owns the physical fetch. | `of_call_counter.py:68–94,108–115` · `automation_executor.py:575` · `server.py:2543–2553` |
| Register a targeted `watch.py` check alongside OF-call and user-p95 baselines. Compare matched busy-Creator windows with similar hop volume and scrape traffic. | Tests whether chatter loads improve under the workload that failed. | Aggregate improvement can hide the busy Creator. Require observed hops, explicit deep clicks and tag coverage before reporting a pass. | `watch.py:488–493,841–858,1343–1346,1390–1399` |

- **Missing requirements** — Define observation window, minimum hops, coverage, wait ceiling and badge tolerance. Per Creator, report automatic over-cap requests/hop, duplicate leaders/key, OF calls and 429s/hour, failed loads/hop, p95 wait, and explicit deep-page success. Compare with the supplied 29/39 holds and 48 failures in ~4 hours.
- **Falsifiers** — Any automatic over-cap dispatch, repeated identical OF leaders, wait above ceiling, failed explicit continuation, or badge drift defeats the corresponding claim. Zero observed hops or missing tags makes the check inconclusive.

### 06 · Which follow-ups would still have a case after the bundle?

| Alternative | Pros | Cons | Evidence file:line |
|---|---|---|---|
| Scrape backoff on repeated 429, or reserve a per-Creator call budget during chatter activity. | Addresses residual background contention even if the UI cap works. | Backoff reacts after throttling. A reserve can delay history. The existing sweep time budget starts **after** list discovery and does not reserve calls. | `scrape_chats.py:706–717,748–773,808–816` · `of_pacing.py:111,152–158` |
| Use already-fetched scrape rows to warm exact relay pages. | Saves a later OF read when Creator, order, offset, shape and freshness match. | Scrape requests full users and advances by returned length. Partial or stale windows could poison the badge fold. Benefit depends on overlap with actual cache misses. | `scrape_chats.py:713–735` · `accounts_admin_api.py:241–249,319–337` |
| Keep recent Creator lists mounted but hidden. | Preserves scroll position and avoids remount-triggered reads. | Hidden panels retain observers. CSS hiding stops viewport autofill but does not disable group fill, polling or invalidation. | `FanList.tsx:649–653,722–730` · `useChatList.ts:396–410,425–430,566` |
| Merged “my Creators” Unread view. | Can eliminate hops when the actual task is finding the next unread chat. | Fan-out can increase OF calls. Needs assignment scope, Split isolation, stable ordering and partial-failure semantics. | `useChatList.ts:325–355,479–489` · `split_inbox.py:204–230` |
| Page Split Inbox from the local mirror. | Can serve deep group pages without OF when the mirror is sufficiently complete. | Current local endpoint is a seed. It limits before group filtering and lacks a cursor or stable tie-break. Unread drift and phantom rows are documented. | `server.py:2312–2333,2349–2357` · `accounts_admin_api.py:241–243` |
| Fail fast on throttled `offset>0`, keeping page 0 eligible for short recovery. | Preserves visible rows and avoids queuing pagination behind a closed gate. | Offset 25 is an ordinary second page. Blanket refusal breaks healthy pagination. Gate-aware fast failure still needs an explicit retry path. | `server.py:2528–2553` · `of_pacing.py:350–384` · `FanList.tsx:839–842` |

- **Missing requirements** — Establish residual failures after the bundle, scrape freshness target, useful warm-cache overlap, hidden-tab traffic allowance, demand for cross-Creator triage, mirror coverage/lag, and acceptable explicit-page retry latency.
- **Falsifiers** — Busy-hour success under sustained scrape weakens the reserve case. Few matching misses weaken warming. No remount penalty weakens hidden mounts. Unchanged hop counts weaken merging. Group/order/unread mismatches defeat mirror paging. Fast, successful tail reads under the short wait weaken blanket fail-fast.

Ship: PR n/a · merged no (read-only review) · deployed n/a