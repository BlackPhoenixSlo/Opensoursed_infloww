# Trim cached deep pages
Type: grilling
Status: resolved 2026-11-26
Blocked by: 01

Cached chat-list queries (persisted, 7-day gcTime) replay every cached page on hop-back (stale mount, prefetchModelChatList, warm-up invalidate). Trim to what, when, and with what guards? Constraints from review: trimming to head page breaks completeUnreadView + chip counts; skip active key and keys with a next-page fetch in flight; persisted copy must also be trimmed (dehydrate) or CACHE_BUSTER bumped.

## Answer
- **Trim to 4 pages**, not to the head page. Trimming to the head would make `completeUnreadView` return null for any Unread list longer than 25 rows (`chatsCache.ts:247-248`) and would cut chip counts (`FanList.tsx:413-417`).
- **Pure helpers in `app/lib/chatsCache.ts`:**
  ```ts
  export const CHAT_AUTO_PAGES_MAX = 4;
  export function trimChatPages<T>(d: InfiniteData<T> | undefined, keep = CHAT_AUTO_PAGES_MAX): InfiniteData<T> | undefined
  // returns d itself when no-op; else { pages: slice(0,keep), pageParams: slice(0,keep) }
  export function shouldTrimChats(q: { key0: unknown; observers: number; fetchStatus: string; pages: number }): boolean
  // key0==="chats" && observers===0 && fetchStatus==="idle" && pages>CHAT_AUTO_PAGES_MAX
  ```
  `pageParams` must be sliced together with `pages`. The kept page 4 still has `hasMore: true`, so the next offset is 100 and stays correct (`useChatList.ts:529-530`).
- **When to trim.**
  1. **On restore.** Extend `trimRestored` (`providers.tsx:157-169`) to loop over `["chats"]` queries as well, keeping `updatedAt` (precedent: `:164`). This runs before observers are told (`:171-174`), so lists persisted by old bundles are fixed. No `CACHE_BUSTER` bump, which would throw away all persisted threads and lists; the threads precedent trims instead of bumping (`:170`).
  2. **On leave.** Add a subscriber to the existing `queryCache.subscribe` (`:117`). On `observerRemoved` or `updated` for a `["chats"]` query, `setTimeout(0)`, then re-check `shouldTrimChats` and call `setQueryData(trimmed, { updatedAt })`. Wrap it in the existing `trimming` flag so the trim does not count as a use in the MRU ranking (`:116-118`).
- **Guards.**
  - Never trim a list that has an observer (the active view, including a StrictMode remount, which the deferred re-check covers).
  - Never trim while `fetchStatus` is not idle (same reason as `warmUpMayRefetch`, `useCreatorWarmUp.ts:13-15`). When that fetch settles it fires `updated`, and the list is trimmed then.
  - The persisted copy is handled with no dehydrate hook: inactive lists are already trimmed in memory, and an active deep list that gets persisted is trimmed on the next restore.
- **What this fixes.** A stale mount, `prefetchModelChatList` (`useChatList.ts:359-380`) and the warm-up invalidate (`useCreatorWarmUp.ts:25-27`) can each replay at most offsets 0–75.

Vitest table (`chatsCache.test.ts`), `trimChatPages`:

| input | keep | expect |
|---|---|---|
| undefined | 4 | undefined |
| 1 page | 4 | same reference |
| 4 pages | 4 | same reference |
| 5 pages | 4 | 4 pages |
| 6 pages, pageParams [0..125] | 4 | 4 pages, pageParams [0,25,50,75], last page `hasMore: true` |

`shouldTrimChats`:

| key0 | observers | fetchStatus | pages | expect | note |
|---|---|---|---|---|---|
| chats | 0 | idle | 6 | true | |
| chats | 1 | idle | 6 | false | active |
| chats | 0 | fetching | 6 | false | in flight |
| chats | 0 | paused | 6 | false | |
| chats | 0 | idle | 4 | false | |
| messages | 0 | idle | 6 | false | |

One QueryClient test: add an observer, remove it, flush timers, and assert the list now has 4 pages and the same `dataUpdatedAt`.

Rung: 3 (`trimRestored`/`trimThread` precedent and the `warmUpMayRefetch` guard) plus 1 for the constraints (`chatsCache.ts:243-257`, `providers.tsx:38,82`).

ASSUMPTION: losing explicitly loaded rows 101+ after leaving a list is acceptable (owner: deeper pages only on explicit action). This is overturned if chatters complain about scroll depth lost on hop-back.
ASSUMPTION: trimming search and mirror (20-row) lists to 4 pages too is harmless.

Evidence: `providers.tsx:28,37-38,82,116-125,157-174`; `threadCache.ts:89-102`; `chatsCache.ts:228-258`; `useChatList.ts:359-380,524-540`; `useCreatorWarmUp.ts:13-27`; `FanList.tsx:413-417`.

## Reconciled (Codex Astra phase 2: accept-with-fixes → reframed)
- accept (major): trimming breaks the Unread completeness proof and fallback counts (cache-event subscribers, not observers).
- accept (major): a deferred leave-trim can't bound a walk already started; restore-only trim leaves deep copies on disk.
- accept (major, measured): `setQueryData` trim clears `isInvalidated`.
**Final decision (code judo):** don't trim data; cap the replay walk at fetch start. In useChatList's queryFn, when the fetch is a refetch (not `fetchMore`) and `offset >= CHAT_AUTO_PAGES_MAX*limit`, return the cached page for that offset with no network call. Pages 1–4 refresh; deeper cached pages stay as they were (old stamp → Unread proof simply not claimed complete, counts unchanged, invalidation state untouched). Covers stale mount, prefetch, warm-up invalidate, persisted restores — every replay path goes through the queryFn.
ASSUMPTION (rung 5, not adversary-reviewed): serving a cached deep page during replay is safe for row order (rank shifts may duplicate a fan across page 4/5; existing dedupe by fan id in shareChatPages to be confirmed). Overturned by a duplicate-row test. Falls: 02.
