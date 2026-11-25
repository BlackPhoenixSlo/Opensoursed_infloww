# Phase 01d — Messages Pro combined

**Objective.** Messages Pro lists every Platform's Creators in one window, reads each Creator's Platform from the Creator, keeps Fan and message ids exact, and never offers a send that mixes Platforms, while every other surface keeps today's Platform behaviour.

## Problem Statement
A chatter working OnlyFans and Fansly Creators has to flip the sidebar's Platform switch to reach the other inbox. There is only one inbox: `/inbox` redirects to `/messages-pro`. Messages Pro also takes "which Platform" from the switch, not from the Creator. Open a Fansly Thread while the switch says OnlyFans and the composer offers OnlyFans rich text, and load-older picks its cursor by OnlyFans rules. Fansly ids are snowflakes past 2^53. Three load-older cursor paths, the head-settled check, the local history seed (`/admin/messages` and its client), the cold inbox seed and list-add pass them through `Number` or emit them as JSON numbers. They round to a Fan or message that does not exist. Once one list mixes Platforms, that rounding can be reached from OnlyFans mode. Switching Platform from the main window also writes the shared `chatterly:scope` key, which wipes the window's saved Creator.

## Solution
The Messages Pro window (Pop-out window, phone, Deep link) lists OnlyFans and Fansly Creators together. A Platform badge marks each non-OnlyFans Creator on its Creator tab, in the Creator picker, in the phone scope select and in the composer's pickers. Inside the window, every per-Platform behaviour reads the Creator's own Platform. Ids are kept in the shape the wire sent, from the Relay's seeds to the browser's cursors. The mass composer sends to one Platform at a time, and switching its sender to another Platform turns rich text into plain text. Fan List filters a Platform cannot honour return no rows for that Platform's Creators, in All scope and on one Creator. They never return unfiltered rows. The main window's Platform switch still drives the pages that follow it today. Its scope fix-up stays in memory, so it never clears the window's saved Creator. 1c's seeded Fansly Creator (`--fansly`, 18-digit ids) gets local chats and a chatter grant, so all of this can be proven locally.

## User Stories
1. As a chatter, I want Messages Pro to list my OnlyFans and Fansly Creators together, so that I work both without touching the Platform switch.
2. As a chatter, I want the phone layout and Deep links to list the same combined Creators, so that every way into Messages Pro agrees.
3. As a chatter, I want every page outside Messages Pro to keep its Platform behaviour (Dashboard, OF Manager and Growth follow the switch; setup keeps its own Platform filter), so that only Messages Pro changes.
4. As a chatter, I want a Platform badge beside a Fansly Creator's name on the Creator tab and in the Creator picker row, so that I know which site I am chatting on.
5. As a chatter on a phone, I want that badge in the phone scope select, so that the phone tells Creators apart the same way.
6. As a chatter composing a mass message, I want the badge in the composer's account picker and chips, so that I know where it goes.
7. As a chatter, I want OnlyFans Creators to carry no badge and Fan rows to keep their Creator colour dot, so that the common case looks as it does today.
8. As a chatter, I want a Fansly Thread to drop OnlyFans rich text even while the switch says OnlyFans, so that I never send markup Fansly shows as literal text.
9. As a chatter, I want an OnlyFans Thread, and an All-models OnlyFans composer, to keep rich text even while the switch says Fansly, so that switching never takes a tool away from me.
10. As a chatter, I want scrolling back in a Fansly Thread to page from the real oldest message, through OnlyFans and the local history seed, so that history loads instead of stalling or skipping.
11. As a chatter, I want scrolling back in an OnlyFans Thread to skip ledger tip and mass placeholder rows exactly as today, so that OnlyFans paging does not change.
12. As a chatter, I want a Fansly Fan from the cold inbox seed to open the right Thread, so that a first paint never points at a Fan who does not exist.
13. As a chatter, I want adding Fansly users to a list to send and check their exact ids, so that a successful add is never reported as failed and a rounded echo is never reported as added.
14. As a chatter (employee login), I want the combined window to list my granted Fansly Creator with her badge and Fansly behaviour, read from the roster `platform` 1c adds, so that the window works the same for me as for the owner.
15. As a chatter, I want the mass composer's All-models pick to cover only the Creators on the composer's Platform, so that one send never spans two sites.
16. As a chatter, I want the composer's multi-Creator chips to list only that Platform's Creators, so that I cannot build a mixed send by hand.
17. As a chatter, I want a Fansly Creator to stay out of the mass composer while Fansly broadcast is unproven, so that no fan-out reports a skipped Fansly send as sent.
18. As a chatter, I want switching the composer's sender to another Platform to turn my formatted text into plain text, so that no hidden markup goes out in the payload (held by a reducer table: no second Platform has `mass_message` yet, so the switch is unreachable on the real path).
19. As a chatter, I want the With Tips, Priority, folder and Pinned filters to show no Fansly rows, never unfiltered ones, so that a filter always means what it says.
20. As a chatter, I want Unread to keep working for Fansly Creators, so that the filter the Shim honours stays usable.
21. As an owner, I want switching Platform in the main window to leave the Creator saved in Messages Pro alone, so that the window does not lose its place.
22. As an owner, I want the main window to drop a saved Creator from the other Platform to All for this page only, so that the main shell stays consistent without writing anything.
23. As a chatter, I want the window's Post button to open New post listing only OnlyFans Creators in its column and phone select, so that a Fansly Creator is not offered as an OnlyFans poster.
25. As a developer, I want 1c's seeded Fansly Creator to gain local chats and a chatter grant, so that the combined window, badges and id handling can be proven on a throwaway stack.
26. As the owner, I want a one-time check on a real Fansly session (mixed list, a Fansly Thread opened while the switch says OnlyFans, scroll back), so that the fake Creator is not the only proof.

## Implementation Decisions
- **Owns.** App: `lib/platform` (the `AllPlatformsContext`), `useAccounts` (`usePlatformAccounts`, `useOfManagerAccounts`), `AppShell` (window branch), `PlatformGate`'s `PlatformSync`, `useChatMessages` (cursor paths, head-settled), `useChatMessagesLocal` (seed rows, `fetchOlderSeed`), `ChatSurface` (seeded load-older), `useChatList` (filter fan-out and single-Creator read), `ofMirrorCollections` (list-add), `CreatorTabs`, `ScopeSelect`, `AccountPicker`, `IncludeModelsChips`, `MassMessageComposer`, `massMessageReducer` and `useMassSend` (wired to 1c's `massSenders`), `OfManagerChrome` (`OneCreator`, the `?account=` pick). Relay: the `/admin/chats/recent` handler in `server`, and `messages`' `/admin/messages` row shape. Stack: `scripts/demo-shots` seed additions under 1c's `--fansly` (her SQLite chats and messages, the chatter grant), and the verify-app recipe `features/messages-pro.md`. Not owned: the chatter roster `platform` field, `massSenders`, `useOfRichAllowed` and its All-models callers (all 1c's).
- **Interfaces.**
  - `AllPlatformsContext: React.Context<boolean>`, false by default. The window branch provides true. `usePlatformAccounts()` returns the unfiltered active list under it and keeps today's switch filter everywhere else.
  - 1c's `useAccountPlatform(accountId)` and `useCan(accountId, "rich_text")` are the per-Creator reads. 1d adds no second lookup. Chatter rows reach them through the roster `platform` field 1c adds.
  - `useOfRichAllowed` and its All-models rule are 1c's (first sender, never `null`). In the window the mass composer's first sender is `massSenders(accounts, composerPlatform)[0]`, so an All-models OnlyFans composer keeps rich text in the window and outside it.
  - `PlatformSync` stays in the main shell only. There it reconciles a mismatched scope on the first account-list answer (new) and on every switch it already hears through `onPlatformChange` (which includes another tab's write, `platform.ts:68-73`), with `setScope({kind:"all"}, {persist:false})`. No new listener. The route-driven switch is unchanged.
  - The mass composer state gains `platform: Platform | null`. `setAccount` carries the picked account's Platform. If that Platform differs from the state's, the reducer converts `text` to plain (the `ofPlainText` rule) together with today's account reset. Ticket 05 item 6 binds this, but while only OnlyFans has `mass_message` no real path reaches it, so it is held by a reducer table only. 1c's `massSenders(accounts, platform)` with the state's Platform gives the All-models targets and the chip list.
- **Schema.** None.
- **Contracts.**
  - `GET /admin/chats/recent` emits `withUser.id` and `lastMessage.id` through `events.js_safe_id`: a number while JS holds it exactly, else the decimal string. OnlyFans ids are below 2^53, so their bytes do not change.
  - `GET /admin/messages/{account}/{fan}` emits each row's `message_id` and `fan_id`, and `next_before_id`, through `events.js_safe_id`. `before_id` already parses as an int, so a decimal string query value works unchanged.
  - List-add (`POST /api/of/v2/lists/users`, built Fansly-side by 1b) sends each id via `lib/fanId`'s parse rule (a number while safe, else the string) and checks the echo with `sameUserId`, never `Number`.
- **Window scope.** Every `/messages-pro` URL is the window branch (ADR-0002, amended 2026-10-18), so a single provider covers the Pop-out window, phone and Deep links. `/inbox` already lands there.
- **Platform per Creator.** In the window, no code path reads `getPlatform()` or `usePlatform()` to decide a Creator's behaviour. `useChatMessages`'s synthetic-band test (`MASS_PLACEHOLDER_MIN`) applies to a numeric id in the band, with no Platform read. A string id is never synthetic. So a cold Fansly Thread (string ids) still finds its cursor, and an OnlyFans Thread skips the band exactly as today, whatever the switch says.
- **Exact ids.** All three cursor paths (the fetched-oldest ref, the prefetch head map, the cache fallback) and both head-settled checks hold the message id as `FanId` in the shape the wire sent. They take the minimum with `compareFanIds`, match with `sameUserId`, and never call `Number` on an id. `olderCursor()` returns `FanId | null`. `fetchOlderSeed` takes a `FanId` cursor. `LocalMessageRow.message_id` is a `FanId`, and `mapRows`' positive-id guard and band test follow the rule above. This is a precondition for item 1, not a follow-up (ticket 05 item 7). The house helpers `lib/fanId` and `events.js_safe_id` do the work, and no new helper is added (rung 3).
- **No mixed sends.** In the window, the mass composer's sender is one Platform: the picked sender's, else the scope Creator's, else OnlyFans. All-models, the chips, the confirmation count and `useMassSend`'s per-Creator POSTs (first send and retry) all draw from the same `massSenders(accounts, platform)` list, never from the raw roster. A preseeded or stale sender id outside that list is dropped before any POST. Fansly senders stay out entirely while 1c's `mass_message` Capability is in Fansly's `lacks`. The Relay's Side-effect gate (1b) is the second guard.
ASSUMPTION: with scope All and no pick, the composer starts on OnlyFans (rung 3, the CONTEXT default for a missing Platform). Overturned if the owner wants the switch's Platform.
- **Filters.** Tips, Unread with tips, Priority and folder filters need `filter_tips`, `filter_priority` and `filter_folders` (1c). The Pinned filter needs `pin_message`, because the Shim maps only `unread` (`fansly_shim.py:1160-1182`); 1c hides the Pinned chip without `pin_message`, so this covers a filter already active or set by URL. When the filter's Capability is absent for a Creator's Platform, `useChatList` skips the read for that Creator and contributes no rows. This holds in the All-scope fan-out and in the single-Creator read, where it returns an empty page. Chip visibility stays 1c's rule.
- **Badge.** `PlatformLogo` goes beside a non-OnlyFans Creator's name on the Creator tab and the picker row, in the phone scope select, and in the composer's account picker and chips. Not on Fan rows or the Thread header (ADR-0057 ASSUMPTION).
- **Post button.** New post lives in OF Manager, an OnlyFans route, so the route-driven switch makes the switch OnlyFans on arrival (`platformOfPath`). `useOfManagerAccounts` and `OneCreator` read `usePlatformAccounts` instead of `useActiveAccounts`, so the creator column, the phone select and the stand-in pick list only OnlyFans Creators. A `?account=` naming a Creator outside that list is not applied. Watchers stay as today.
- **Fake Fansly Creator.** 1c owns her (Nova Reyes, `--fansly`, account `900839700124344320`, Fan `900839700124344321`, message ids from `900839700124344400`, 18 digits, past 2^53, Shim-shaped fixtures, 21/20 doctor). 1d adds, under the same flag, her chats and messages in SQLite for the cold inbox seed and the local history seed, and a grant to the seeded chatter login. The doctor count is unchanged.

## Testing Decisions
Seams, highest first. Tests check what a user or caller sees, never internals.
- **The window tree** (`app/messages-pro` render tests, prior art `windowed.test.tsx`, which renders the real Thread, and `AppShell.test.tsx`): with a mixed owner list and the switch on OnlyFans, the window lists both Creators, the Fansly tab carries the badge and the OnlyFans tab does not, the Fansly Thread shows no rich-text control and the OnlyFans Thread does. The same holds for a chatter roster with a granted Fansly Creator, a legacy OnlyFans row and a watcher. The main shell still lists only the switch's Platform. The window branch does not mount `PlatformSync`.
- **PlatformSync** (prior art `PlatformSwitcher.test.tsx`): a saved Creator from the other Platform drops to All in memory on load and on a switch, and `localStorage["chatterly:scope"]` and the boot cookie keep their earlier value.
- **`useAccounts`** (prior art `useAccounts.test.tsx`): `usePlatformAccounts` is filtered without the context and unfiltered with it, for owner and chatter rows. `useOfManagerAccounts` under the OnlyFans switch has no Fansly Creator.
- **Load-older** (prior art `useChatMessages.test.tsx`): for each start, fetched head, prefetch head and cache-only, a Fansly Thread with 18-digit string ids sends the exact `before_id` string on two successive pages, with the Platform resolved and unresolved, under both switch values, and `headSettled` turns true from a string prefetch head. An OnlyFans page with a 5e15 placeholder and a 6e15 tip row still skips both. `ChatSurface`'s seeded load-older passes the same string cursor to `/admin/messages` (prior art `useChatMessagesLocal.test.ts`), and `mapRows` keeps string-id rows.
- **Composer** (vitest tables, prior art `massMessageReducer.test.ts`, `MassMessageComposer.test.tsx`): a `setAccount` across Platforms gives plain text and the same-Platform one keeps it. `massSenders(accounts, composerPlatform)` feeds All-models and chips on a mixed list. An All-models OnlyFans composer keeps the rich-text control. `useMassSend`, given a mixed roster and a preseeded Fansly id, POSTs only for same-Platform OnlyFans ids. A Fansly sender is never a target while `mass_message` is lacked.
- **Filters** (prior art `FanList.test.tsx`, `useChatList.test.tsx`): With Tips and Pinned in All scope make zero Fansly requests and show zero Fansly rows. Pinned scoped to the Fansly Creator makes no request and shows an empty list. Unread still fetches for Fansly.
- **List-add** (prior art `ofMirrorCollections.test.ts`): the POST body carries the literal 18-digit string. Its exact echo counts as added. An echo that differs but rounds to the same `Number` counts as failed.
- **Post handoff** (prior art `OfManagerChrome` tests): with the scope a Fansly Creator saved in Messages Pro, New post's column and phone select list only OnlyFans Creators, the stand-in is an OnlyFans Creator, and `?account=<fansly id>` is not applied.
- **Relay** (pytest via `scripts/run-tests.sh`, prior art `test_sse_bridge.py`'s inbox-seed cases, the `/admin/messages` tests): `/admin/chats/recent` and `/admin/messages` return an 18-digit fan and message id as a string, a 9-digit one as a number, and a string `next_before_id` for a Fansly page.
- **Real path** (verify-app): desktop and phone screenshots of the combined window, the Creator picker open, a Deep link to the Fansly Creator, and her Thread opened while the switch says OnlyFans, then scrolled back. The same window as the seeded chatter. Side-effect checks: `/admin/chats/recent` and `/admin/messages` carry her exact ids, `/chatter/me/accounts` carries her `platform` (1c's field, read here), and an All-models mass send driven through the window's composer leaves `of-writes` with mass POSTs only for OnlyFans account ids.

## Acceptance
```sh
set -euo pipefail
(cd app && pnpm exec vitest related --run lib/platform.ts hooks/useAccounts.ts \
  hooks/useChatMessages.ts hooks/useChatMessagesLocal.ts hooks/useChatList.ts components/chat/ChatSurface.tsx \
  components/shell/AppShell.tsx components/shell/PlatformGate.tsx components/compose/massMessageReducer.ts \
  components/compose/useMassSend.ts components/chat/CreatorTabs.tsx components/of-manager/OfManagerChrome.tsx \
  lib/ofMirrorCollections.ts)
(cd app && pnpm test:run)
scripts/run-tests.sh
! grep -rn 'getPlatform() === "fansly"' app/hooks app/components app/lib --include='*.ts' --include='*.tsx'
D=scripts/verify-app/drive.py
A=900839700124344320 F=900839700124344321
nice -n 10 $D up --fansly && $D doctor
$D goto /messages-pro && $D wait --text "Nova" && $D screenshot --path combined.png
$D screenshot --phone --path combined-phone.png
$D goto "/messages-pro/$A" && $D wait --text "Nova" && $D screenshot --path deep-link.png
$D api '/admin/chats/recent?limit=100' | venv/bin/python -I -c 'import json,sys; b=json.load(sys.stdin)["body"]["list"]; \
  r=[x for x in b if x["__accountId"]=="'$A'"]; assert r and all(x["withUser"]["id"]=="'$F'" and isinstance(x["lastMessage"]["id"],str) for x in r)'
$D api "/admin/messages/$A/$F?limit=30" | venv/bin/python -I -c 'import json,sys; m=json.load(sys.stdin)["body"]["messages"]; \
  assert m and all(isinstance(x["message_id"],str) and len(x["message_id"])==18 for x in m)'
# recipe (features/messages-pro.md): open her Thread with the switch on OnlyFans, scroll back, screenshot;
# open the Creator picker, screenshot; send an All-models mass message from the window's composer
$D of-writes   # read: mass-message POSTs carry only OnlyFans account ids, none for $A
$D login --as chatter && $D api /chatter/me/accounts | venv/bin/python -I -c 'import json,sys; \
  r=[x for x in json.load(sys.stdin)["body"] if x["account_id"]=="'$A'"]; assert r and r[0]["platform"]=="fansly"'
$D goto /messages-pro && $D wait --text "Nova" && $D screenshot --path chatter-combined.png
$D down
# manual: owner, on a real Fansly session: mixed Creator list, a Fansly Thread opened while the switch says OnlyFans, scroll back
```

## Depends on
- **1c** provides the `PLATFORMS` table, `can`/`useCan`, `useAccountPlatform`, the one `useOfRichAllowed` rule, `massSenders(accounts, platform)`, the chatter roster `platform` field, the Fan List chip helper, and the seed's one Fansly Creator (`--fansly`, fixed ids, fixtures, doctor). Exact ids (cursor paths, head-settled, `useChatMessagesLocal`, list-add) and the two Relay `js_safe_id` changes need nothing from 1c and may run in parallel with it; only the window, composer and real-path proof wait for 1c. It also hides Fansly senders and filter chips whose Capability is lacked. 1d reads those Capabilities (`mass_message`, `filter_tips`, `filter_priority`, `filter_folders`, `pin_message`, `rich_text`) and does not define them.
- **1b** provides Fansly list-add (`add_users_to_lists`, string echo) that story 13 exercises, the mass-send Side-effect gate that backs the composer's one-Platform rule, and the `delete_chat` 501 that Bulk Delete meets on a Fansly chat.

## Out of Scope
- Badges on Fan rows and the Thread header: ADR-0057 leaves them off. The owner can ask.
- A faster Fansly cold load. Fansly rows keep waiting on the OnlyFans inbox bundle (`screenBundle`) unless measured slow (ticket 05 item 11).
- Remembered tabs and chat cache keys: already keyed by account id with string ids (ticket 05 item 12).
- Mixed-Platform mass sends, and Fansly broadcast itself: rejected by ADR-0057. Fansly broadcast waits on its Capability.
- Bulk Delete on a Fansly chat: 1b marks `delete_chat` Unsupported and gates its route to 501 before any side effect; 1d does not change it.
- The cold-seed and kept-previous-rows paint while a filtered read is in flight. Both are platform-neutral today and dissolve when the read lands.
- Combined lists on any surface outside Messages Pro: owner scope.
- Defining Capabilities, the Drift test and relay Side-effect gates: 1b and 1c.
- The chatter roster `platform` field: 1c.
- A new `storage`-event reconcile path or test: ticket 05 item 3 asks for an in-memory reconcile on load; another tab's switch already reaches `PlatformSync` through `onPlatformChange`.

## Further Notes
ASSUMPTION: 1d's share of the shared parts is wiring only (it passes the composer's Platform to 1c's `massSenders`, wires `useMassSend` to it, passes `--fansly` and adds SQLite chats and the chatter grant), and 1c owns the helper, the rich-text rule, the roster field and the seed (coordinator ruling on shared ownership, rung 5). Overturned if the owner reassigns a part, then this spec takes 1c's lines verbatim.
ASSUMPTION: the `/admin/chats/recent` and `/admin/messages` fixes use `js_safe_id` for every Platform instead of branching on Platform (rung 5). OnlyFans output is byte-identical because its ids stay below 2^53. Overturned by an OnlyFans id at or past 2^53.
ASSUMPTION: a Fansly message id is always a string past 2^53, so the band rule "a string id is never synthetic" needs no Platform read for an unresolved Thread (rung 1 for current snowflakes, ~9.5e17; rung 5 for the rule). Overturned by a Fansly id delivered as a JSON number or below 2^53.

## Review
codex, 2026-11-24. Blind call (B1–B10), draft call (D1–D12). Each finding was checked against the code before its verdict.
- D2 Acceptance exits green after failures, `limit=200` 422s (`server.py:3283` `le=100`), and the assertion takes any long id: **accept**. Added `set -euo pipefail`, `limit=100`, and asserts on her exact fan id and string last-message id.
- D3 / B3 the local history seed rounds: `/admin/messages` emits ints (`messages.py:61-64`), `fetchOlderSeed(beforeId: number)` (`useChatMessagesLocal.ts:154`), and `mapRows` drops non-numbers (`:217`): **accept**. `/admin/messages` joins Contracts, `useChatMessagesLocal` and `ChatSurface` join Owns, and the Exact ids and Load-older tests cover it.
- D4 paging test misses paths, `headSettled` uses `Number(m.id) === head` (`useChatMessages.ts:220,509`), and unresolved-as-OnlyFans rejects every Fansly id on a cache start (`:386`): **accept**. The band rule became "numeric below 2^53 only, a string is never synthetic", which drops the old ASSUMPTION. Head-settled is now owned, and the test runs every start × resolved/unresolved × two pages.
- D5 the no-mixed-send proof never sends, and `useMassSend` sources targets apart from the picker: **accept**. One `samePlatformSenders` list feeds picker, chips, confirm, send and retry, and stale ids are dropped. A `useMassSend` test and a real-path All-models send checked in `of-writes` were added. The list is now 1c's `massSenders(accounts, platform)` (Six hats Green 1).
- D6 / B5 filters: Pinned's Capability is `pin_message` and the chip always shows (1c), and the single-Creator read bypasses the fan-out (`useChatList.ts:403`): **accept** for both, now in Filters and its test. Seed and kept-previous-rows flash: **partial**. That is platform-neutral today (`FanList.tsx:331,379`), so it was moved to Out of Scope.
- D7 / B8 the Post fix misses the real roster (`Chrome` reads `useOfManagerAccounts`, `OfManagerChrome.tsx:201`), the route forces the switch to OnlyFans (`nav.ts:337`), and `?account=` goes unchecked: **accept**. Post button was rewritten, story 23 now says OnlyFans, and a Post handoff test was added.
- D8 rich text: 1c owns the `useCan` rewrite, and null for All-models (`MassMessageComposer.tsx:126`, `PostComposer.tsx:89`) would drop OnlyFans rich text: **accept**. All-models callers pass their first same-Platform account, story 9 was widened, and a test was added. 1d's own rich-text rewrite was removed.
- D9 setup does not follow the switch (`AccountsTable.tsx:345-355` full list, own filter): **accept**. Story 3 now reads "keeps its Platform behaviour".
- D10 Depends on misses 1b (list-add, mass gate): **accept**. 1b and 1a were added. I also checked the sibling 1c spec, which already defines `useAccountPlatform` (`phase-01c…:57`), owns `useOfRichAllowed` and adds the seeded Fansly Creator (`:78,143`). So 1d's duplicate lookup, the `--fansly` flag and the 20/21 doctor rule were removed, and 1d now extends 1c's Creator. The flag half is superseded by Six hats Black 1: 1c keeps `--fansly` and 1d passes it.
- D11 the list-add test can bless rounding (`ofMirrorCollections.ts:617-625` `Number` both sides): **accept**. The test now checks the literal outgoing string and rejects a rounding echo.
- D12 the browser script never reaches picker, deep link, chatter or the cold-seed click: **partial**. Added the deep link, the picker, a chatter login with `/chatter/me/accounts` and a screenshot, and a scroll-back. The cold-seed Fan click stays a recipe step. Its proof is the exact-id assert on `/admin/chats/recent` plus the Relay test.
- B2 composer needs one eligible set end to end and a pre-side-effect reject: **accept** (merged with D5). The Relay reject is 1b's gate.
- B4 chatter roster wire contract and normalisation (granted, legacy, watcher): **partial**. The window tree and Relay tests now cover granted Fansly, legacy and watcher. Ungranted rows never reach a chatter (`chatters.py` grant filter), so no case is needed.
- B6 Bulk Delete on a mixed selection reaches a Shim with no `delete_chat`: **partial**. Verified (`grep delete_chat fansly/*.py` finds nothing; `server.py:5722` route). It errors rather than faking success and is reachable in Fansly mode today, so it went to Out of Scope as a 1b/1c gap item. Now 1b's (Six hats White 2).
- B7 a route-level provider in `messages-pro/layout.tsx` as an alternative, and split route switching from reconciliation: **partial**. The provider site is decision 05 item 2 (AppShell window branch) and binds. The `storage`-event reconcile was added to PlatformSync and its test. Superseded by Six hats Green 3: Out of Scope.
- B9 test through the real Thread plus a Relay route test, with headers and cursors asserted: **partial**. `windowed.test.tsx` is already the named seam. Exact cursor and header asserts now sit in Load-older and Composer. No new harness was added.
- B10 falsify the premise by timing baseline against candidate: **reject**. The combined window is the owner's call (decision 05 item 1, rung 2), and cold-load timing is ticket 05 item 11's "only if measured slow", already in Out of Scope.

### Six hats
Plan review, 2026-11-24 (`multi-platform-p1-plan-review.md`). Shared parts follow the coordinator's one-owner table there.
- White 1 (Filters said 1c keeps the Pinned chip always shown; 1c gates it on `pin_message`) — **accept**: Filters now says 1c hides the chip and the read gate covers a filter already active.
- White 2 (Bulk Delete handed to "1b and 1c", in neither) — **accept**: 1b marks `delete_chat` and gates its route; Out of Scope and Depends on point there.
- Black 1 (seed owned twice; `$D up` with no flag; "19-digit" tests against 18-digit ids) — **accept**: 1c owns the seed behind `--fansly`; Acceptance runs `up --fansly`; every test says 18-digit, matching the ids and the `len(...)==18` assert; 1d adds only SQLite chats and the chatter grant.
- Black 3 (roster `platform` field in the wrong Phase) — **accept**: moved to 1c; story 14, Owns, Contracts, the `useAccounts` and Relay test rows now read 1c's field instead of adding it.
- Yellow 2 (exact ids close a reachable rounding bug) — **accept**, no change.
- Green 1 (two sender helpers; plain-text switch unreachable while Fansly lacks `mass_message`) — **accept**: `samePlatformSenders` removed, 1d passes the composer's Platform to 1c's `massSenders` and wires `useMassSend`; the reducer's `platform` field and plain-text conversion stay, held by a reducer table only (ticket 05 item 6 binds), story 18 says so.
- Green 2 (1c's `null` path thrown away here) — **accept**: the rule is written once in 1c; this spec only names the window's first sender. `PostComposer` left Owns.
- Green 3, drop the `storage`-event reconcile — **partial**: no new listener or test row, now Out of Scope (ticket 05 item 3 says on load); a switch from another tab still reconciles with `persist:false` because `onPlatformChange` already fires on it (`platform.ts:68-73`).
- Green 3, run exact ids and Relay changes in parallel with 1c — **accept**: Depends on says so; Workstreams shows it.
