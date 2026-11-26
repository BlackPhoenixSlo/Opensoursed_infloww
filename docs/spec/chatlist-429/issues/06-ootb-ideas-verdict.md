# Out-of-the-box ideas: needed or not
Type: research
Status: resolved 2026-11-26
Blocked by: 

For each idea decide needed-now / later-if-X / drop, with evidence: (a) scrape_chats backoff or chatter budget reserve after a user-lane 429; (b) scrape_chats writes list pages into relay_cache as cache warmer; (c) keep the chatter's last 2–3 Creator lists mounted hidden; (d) merged my-Creators unread-first view for Split Inbox chatters; (e) serve Split Inbox pages from local chats mirror; (f) fail-fast on offset>0 pages. Owner wants to know if any are relevant after the bundle.

## Answer
Five of the six ideas aren't worth building now. Two already exist in some form, two should be dropped, and two should wait for a measurable trigger. None is needed now: the approved bundle goes after the measured cause, which is automatic deep-page loads on the busiest Creator.

The finding that matters most: the background scrape (scrape_chats) runs completely outside the per-Creator 429 machinery. It is never paced and never waits on a Creator's 429 gate. So if idea (a) is ever needed, the smallest form is to run scrape_chats through the existing pacer rather than build a new reserve.

| # | Idea | Verdict | Why | Evidence | Rung |
|---|---|---|---|---|---|
| a | scrape_chats backoff / chatter budget reserve | **later-if:** after the bundle ships, tagged list 429s at offset <100 still give up ≥2/h on one Creator over 2 sweeps. Fix then = wrap scrape_chats in `of_pacing.walk(kind="scrape_chats")`, no new reserve | A partial reserve exists: user reads already beat background walks after a 429, and user requests keep reserved concurrency slots. scrape_chats is outside both: it isn't a walk, so it's never paced and never held by the gate. Its only brake is stopping after 5 failures in a row | `of_pacing.py:26-28` (sends, then reads, then walks), `:46`, `:227-229` (outside a walk = unpaced), `:250` (walks queue last); `server.py:1546-1551` (user slots); `scrape_chats.py:710-716` (direct `client.list_chats`), `:814`, `:834`; no `of_pacing.walk` call in scrape_chats or automation_executor (grep) | 1 for the facts, 4+5 for the trigger |
| b | scrape_chats warms relay_cache with list pages | **drop** | The cache keys can never match. Scrape asks limit=50 with full user data and steps offset by OF's ~10-row pages; the app asks limit=25 at multiples of 25 for a page the relay assembles from several OF calls. Even with matching keys, sweeps run every 4 h and a cache entry lives 10 min plus 10 min stale | `scrape_chats.py:713-716`, `:732`; `screenBundle.ts:8` (page size 25); `server.py:2566` (cache key); `chats_page.py` ~L94-98 (loops OF calls per page); `server.py:2465-2466`; `sweep_cadence.py:20` | 1 |
| c | Keep last 2–3 Creator lists mounted hidden | **drop** | The query cache already keeps hopped-from lists. Each mounted list runs its own head-page poll timer, so 2–3 hidden lists means 2–3 times the polling on the same busy Creators. The prior debate also traced the deep offsets partly to cached deep pages replaying on hop-back, which this would make worse | `providers.tsx:81-82` (stale 3 d, kept 7 d), `useChatList.ts:383-398` (head poll per mounted list), `:542-549`; `decision.md` (sources) | 1 |
| d | Merged my-Creators unread-first view for Split Inbox chatters | **already-exists** | The "All Models" scope merges every Creator the chatter can read, and the Unread chip filters it. Each Creator's page still gets the Split Inbox filter on the relay. The Creator tabs can also sort by unread | `ScopeContext.tsx:13`, `useChatList.ts:505`, `:327-354`; `FanListFilters.tsx:150`; `server.py:2583`; `useCreatorTabs.ts:27` | 1 |
| e | Split Inbox pages served from the local chats mirror | **later-if:** after the bundle, a Split Inbox group still can't fill 4 pages (group stays "filling" or empty), or clicked deep pages 429 ≥1/h on one Creator | It partly exists already: there is a mirror endpoint with the Split Inbox filter, but the app uses it only as a cold-start placeholder. Serving whole pages from it needs a freshness design first. The mirror is only updated from fresh plain-view OF reads, and unread state can lag | `server.py:2353-2357`; `FanList.tsx:338-344` (`useRecentChatsLocal`, placeholder only while loading); `server.py:2557-2559` (mirror update rule) | 1 for the facts, 5 for the trigger |
| f | Fail-fast on offset>0 pages | **later-if:** the caller tag shows click-driven offset>0 list reads still waiting the full read budget or failing with 502, ≥1/day | After the bundle, deep pages only load on a click. But a clicked page can still sit up to 45 s at the 429 gate before failing. The map already defers this | `of_pacing.py:106` (45 s read budget), `:353`; map "Not yet specified" | 1 for the facts, 4 for the trigger (reversible, data comes from ticket 05) |

**How often 429s happen outside deep pages** (measured, local sweep notes):
- In the 11-25 incident, 29 of 39 list holds were at offset 100/125 and 4 were at offset 0. The other 6 offsets aren't broken out. The brief says "33 of 39" where the map says 29, so treat the remainder as about 6–10.
- On 11-24 the same pattern showed a second chatter on other Creators (429s at offsets 110–125), so the deep-page source repeats.
- 429s on the separate focus/queue route ran at 10–19/h on 11-22 and 11-23. That route isn't the chat list and none of these ideas touch it.
- In quieter windows (11-25 12:16 and 19:40 sweeps) only about 2 reads/h gave up. That's the baseline idea (a) would have to beat.
- Sources: `INCIDENTS.md:208, 243, 256, 261, 291, 294` and `IDEAS.md:6` (`chats-route-429-burst`).

The unbreakable dependency is that ticket 05 (caller tag) must ship before (a), (e) or (f) can ever trigger. Without it, auto, scroll and click loads can't be told apart in the relay log.

**Assumptions:**
- ASSUMPTION (a, rung 4): scrape_chats is what eats the busy Creator's OF budget, as the map says ("mostly background scrape_chats"). That came from a log read, not a per-caller count. A per-caller OF call count for that Creator showing scrape_chats under half its calls would overturn it, and with it the walk-wrap fix.
- ASSUMPTION (a): pacing scrape_chats at 1 s per page fits its 900 s sweep budget. A sweep that hits `scrape_sweep_budget` more often after the wrap would overturn it.
- ASSUMPTION (d, inferred): `accounts` in `useChatList.ts:505` is limited to the chatter's assigned Creators. If a Split Inbox chatter's "All Models" shows Creators they aren't assigned to, the verdict becomes "exists, needs scoping".
- ASSUMPTION (e, rung 5): mirror freshness is good enough for a fallback page. Owner-visible stale unread rows in a seed-served list would overturn it.
- ASSUMPTION (all triggers, rung 4): the thresholds (≥2/h, ≥1/h, ≥1/day) are my picks, sized from the quiet-window baseline above. Owner tolerance for "OnlyFans is busy" would override them.

I made no edits; this is plan-only.

Ship: n/a (decision ticket, no code)

## Reconciled (Codex Astra phase 2: accept-with-fixes)
| Idea | Final verdict |
|---|---|
| a scrape backoff / chatter reserve | later — only if per-Creator scrape contention is measured after the bundle (existing OF counters; sweep already sleeps 0.3 s/chat) |
| b scrape warms relay cache | drop |
| c keep hidden lists mounted | drop (hidden panels still poll + fill) |
| d merged my-Creators unread view | already exists: All Models + "Spend + unread on top" sort — no build |
| e Split Inbox pages from local mirror | later — only if mirror coverage/freshness holds and groups stay empty after the bundle |
| f fail-fast | folded into 04 as the ≤5 s chat-list wait; no blanket fail-fast |
- accept (major): caller causality of the 11-25 deep pages stays inferred until 05 ships.
