# Dynamic auto-load cap 2–4
Type: grilling
Status: resolved 2026-11-26
Blocked by: 

What decides how many pages (2, 3 or 4) the chat list loads without a user scroll/click, per view? Candidate signals: visible rows already fill the panel / reach a target, Split Inbox or owe-reply filter yield, a recent 429 or OF budget pressure on that Creator, search (exempt?). Must be a pure predicate in app/components/chat/fanListPaging.ts with a vitest table; must hold even before the Split Inbox group resolves. Note: maxPages:4 is a trap (next offset = allPages.length*limit).

## Answer
- **Where the deep pages come from.** The unattended loader that pages without a limit is the rAF autofill at `FanList.tsx:716-733`. Its only bound is 10 bursts (`fanListPaging.ts:9,41`), so it can go up to 11 pages (offset 250). The relay already applies the chatter's Split Inbox filter on the server (`server.py:2583`), so a split chatter's panel stays short and autofill keeps firing. The group/owe fill is already limited to 4 pages or 8 rows (`FanList.tsx:374-376`), but only after the group resolves (`fillActive` needs `inbox.group`, `:373`).
- **Rule.** This generalises the existing fill stop rule to every unattended loader, with a floor of 2. Add to `app/components/chat/fanListPaging.ts`:
  ```ts
  export const AUTO_PAGES_FLOOR = 2;
  export const AUTO_TARGET_ROWS = 8;            // = OWE_REPLY_TARGET (FanList.tsx:77)
  export { CHAT_AUTO_PAGES_MAX } from "@/lib/chatsCache"; // = 4, shared with 02
  export function mayAutoPage(a: { pagesLoaded: number; visibleRows: number; query: string }): boolean {
    if (a.query) return true;                           // search exempt
    if (a.pagesLoaded < AUTO_PAGES_FLOOR) return true;  // page 2 always allowed (DOM overflow still gates)
    return a.pagesLoaded < CHAT_AUTO_PAGES_MAX && a.visibleRows < AUTO_TARGET_ROWS;
  }
  ```
  So the list loads 2 pages, goes to 3 or 4 only while fewer than 8 rows are visible, and never goes past 4.
- **Wiring.**
  - Add `if (!mayAutoPage({ pagesLoaded: q.pages?.length ?? 0, visibleRows: rows.length, query })) return;` to the autofill effect after `:721`, and add `q.pages?.length` to its deps.
  - `rows` is the relay-filtered list, plus the group filter when the group is known (`:366-369`). The predicate never reads group state, so the cap holds before the Split group resolves.
  - Keep `AUTOFILL_MAX_BURSTS` as the bound for search (YAGNI: no reducer change).
  - Leave the fill path alone: its rule (`:374-376`) already equals the predicate.
- **429s.** No new per-Creator 429 memory. A failed page already stops both loaders on that list: autofill returns on `!q.isSuccess` (`:717`) and fill stops on `q.isError` (`:376`).
- **Past the cap.** The existing "Load more conversations" button already appears when `hasMore` is true and nothing is loading (`:758-763,898-899`). Do not use `maxPages`, because the next offset is `allPages.length*limit` (`useChatList.ts:529-530`).

Vitest table in `fanListPaging.test.ts` (`mayAutoPage`):

| pagesLoaded | visibleRows | query | expect | note |
|---|---|---|---|---|
| 0 | 0 | "" | true | |
| 1 | 25 | "" | true | floor |
| 2 | 7 | "" | true | |
| 2 | 8 | "" | false | |
| 3 | 0 | "" | true | |
| 3 | 7 | "" | true | |
| 4 | 0 | "" | false | ceiling |
| 6 | 0 | "" | false | cached deep list |
| 4 | 0 | "anna" | true | search |
| 3 | 2 | "" | true | group unresolved, sparse relay rows |

Rung: 2 for the range and the search exemption (owner; `fanListPaging.ts:37-39` and `FanList.tsx:695` already exempt search). 3 for the target of 8 and the extend rule, taken from the fill precedent (`FanList.tsx:77-78,374-376`). 1 for the root cause.

ASSUMPTION: a target of 8 visible rows is "enough" for every view. This is overturned if tagged logs (ticket 05) show chatters clicking Load more right after 2 pages on most hops.
ASSUMPTION: no cross-list 429 memory is needed. This is overturned if tagged logs show autofill 429s at offset 50/75 on the busy Creator.

Evidence: `FanList.tsx:77-78`, `:366-376`, `:716-733`, `:758-763`; `fanListPaging.ts:9,37-43`; `useChatList.ts:529-530,594`; `server.py:2583`; `useInboxGroup.ts:18-30`.

## Reconciled (Codex Astra phase 2: reject → rewritten)
- accept (blocker): one auto budget for EVERY automatic next-page path. `loadMore(caller)` in useChatList is the single choke point: automatic callers (autofill, IO without a fresh scroll, mirror attach, fill) pass only if `mayAutoPage` allows; explicit callers (Load more click, fresh scroll event) get exactly one page each. `userScrolled` resets after each page lands, so one old scroll can't chain pages.
- accept (major): `visibleRows` = rows actually rendered (`sortedDisplayRows`, after Online/group filters), not `rows.length`; raw scan limit (100 scanned rows, summed across Creators) stays separate from fetched-page depth (per Creator).
- accept (major): whenever capped with `hasMore`, show a one-page "Load more" — including zero-match Owe; drop the "+200 rows" allowance.
- accept (major): import `CHAT_AUTO_PAGES_MAX`, don't re-export.
- partial: search keeps auto-scanning (owner listed search as explicit intent) but under the same 4-page budget; past it, one page per click.
**Final rule:** load up to 2 pages; 3rd and 4th only while fewer than 8 rows are visibly shown; never more than 4 automatically; beyond that one page per click/fresh scroll.
ASSUMPTION: 8 visible rows = "enough" (house precedent OWE_REPLY_TARGET). Overturned by tagged logs showing Load more clicks right after 2 pages on most hops. Falls: 01, 04 limits.
ASSUMPTION: search under the 4-page budget is acceptable. Overturned if search misses matches chatters expect.
