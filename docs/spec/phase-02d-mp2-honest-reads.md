# Phase 02d — Honest reads + UI

**Objective.** Every Fansly read and screen this Phase touches shows only what the evidence supports. An unsent Fansly message leaves the open Thread by its string id. Typing never posts without a group and never floods the wire. Mark-read, the lifecycle toggles, the new-fans KPI and fan activity refuse or show "—" instead of a fake success. The welcome editor warns about Fansly's native welcome. Autoreply and welcome lanes have proven verdicts on both Platforms. The app's platform branches are rows in one table, checked against the registry.

## Problem Statement
A Fansly Creator's screens and automations still say things nobody has observed:
- **Unsent messages stay on screen.** A fan or Creator unsends a Fansly message and it stays in the open Thread. The socket's delete event (service 5, type 10) is dropped by the translator. The Shim's `/message` page keeps rows with a truthy `deletedAt`. The app has no per-message delete event at all, only span bounding, and a contiguous `[A,B] → [A]` still leaves `B`.
- **Typing floods the wire or goes nowhere.** The shared hold re-emits typing every 2.5 s, and each re-emit is a signed, proxied REST call. For a fan with no Thread, `_as_group_id` returns the fan's account id, so typing is POSTed under the wrong key. It also rescans up to five pages on every re-emit.
- **The bell's mark-read reaches a bundle-only write** that has never been sent.
- **The lifecycle editor lets an owner switch on expiry, expired and resubscribe messages** that Phase 02c refuses at run time. The owner gets a green toggle that never sends.
- **The dashboard's new-fans KPI and the inbox fan-activity feed** call reads that Phase 02c makes refuse. Cached bundle values and a 30-minute IndexedDB copy can still show a stale 0.
- **The welcome editor says "OnlyFans' welcome message"** on a Fansly Creator and gives no hint that Fansly's own welcome rule may send a second welcome.
- **Unproven verdicts.** Nothing proves that autoreply and the Spanish welcome give the same visible text on both Platforms. Nothing proves that a 3003 + 15016 pair welcomes once, that welcome follow-ups reuse the Thread, or what `send_followup` does for a paying fan with no group.
- **Platform branches are scattered.** The Add/Edit Creator flow, switcher, accounts table, gate and Browserbase card each branch on `=== "fansly"`. A third Platform would silently get OnlyFans or Fansly behaviour, and an unknown stored key renders as OnlyFans.

## Solution
- **Unsent messages.** The Fansly socket turns a type-10 delete frame into a new neutral Relay event, `chat_message_deleted`, carrying the string message id and `fan_id`, so split-inbox narrowing sees the fan. The Relay drops that chat's cached history pages. The Shim drops deleted rows from message pages. The app evicts that id from the Thread's cache and remembers it, so a stale or in-flight page cannot bring it back. OnlyFans keeps its span eviction.
- **Typing.** It is throttled to one POST per group per 5 s, reserved before the POST so overlapping calls send once. It is never sent when no group resolves, and never creates a group. Group lookups are cached (hit for good, miss for the hold's life: it lapses after 5 s with no typing call for that fan).
- **Mark-read.** `notifications_read` becomes Blocked, and the mark-read route refuses 501 with zero requests. The app gains a `notifications_read` Capability: Fansly Creators get no bell-open POST, are left out of "Mark all read", and the button is hidden when no Creator in scope has it (ADR-0056).
- **Lifecycle editor.** The lifecycle config API refuses a paid lifecycle kind on Fansly whose merged state is on, but still saves "off", even with a discount and no readable price. Its GET returns the reason, and the editor's toggle is disabled with that reason but can still be switched off. This is the free-page refusal pattern that already exists.
- **New fans and fan activity.** These are capability-gated in the app. Fansly Creators get "—" and no request, even when the cache holds an old value.
- **Welcome editor.** On Fansly it names the Platform and shows the native-welcome warning. The "after native welcome" toggle is disabled with off-recovery.
- **Verdicts.** Executor-level tests on the Stateful fake prove the autoreply, welcome and follow-up lanes, in both executor modes: positive sends with `OI_CELL_MAP` unset, and the measured Cell-mode outcome (`no_anchor` for autoreply and `send_followup`, a claim for welcome) pinned. Their Verdict and parity rows land with them.
- **Platform table.** The app's `PLATFORMS` rows carry `logo`, `relink`, `loginDefault`, `extensionFormId`, `sessionPrompt` and `bindsProxy`. Every component reads the row. An unregistered key renders as "Unknown platform" with no gated controls. The drift test checks the new fields against the registry.

## User Stories
1. As a chatter with a Fansly Thread open, I want a message the fan unsends to disappear from the Thread at once, so that I never reply to text the fan took back.
2. As a chatter, I want a message I (or another chatter) unsent on Fansly to disappear from every open copy of that Thread, so that all screens agree.
3. As a chatter, I want an unsent message gone after a reload, a load-older within the Relay's 5-minute history cache, and a head page that was in flight when the delete arrived, so that no refetch brings it back.
4. As a chatter, I want eviction to remove exactly the unsent message and no neighbour, so that a `[A,B]` page that loses `B` shows `[A]` and an `[A,B]` page that loses `A` shows `[B]`.
5. As a chatter on OnlyFans, I want message removal to keep working exactly as today, so that the Fansly event costs me nothing.
6. As the Relay, I want a delete frame I have already seen to be ignored, and one whose fan I cannot resolve dropped, so that a replayed frame does not emit twice and no frame skips split-inbox narrowing.
7. As a fan on Fansly, I want to see "typing" only for a reply that will really be sent, at a sane pace, so that the Creator looks human.
8. As the owner, I want at most one typing POST per Fansly group every 5 s, even when two calls overlap, so that the 2.5 s hold does not double the signed, proxied calls.
9. As the owner, I want zero typing POSTs to a fan with no Thread, and no Thread created by typing, so that typing never goes to an account id or opens a chat.
10. As the owner, I want a found group remembered for the Shim's life and a miss remembered for the hold's life, so that an unresolved fan costs one scan per hold, not five pages every 2.5 s, and a fan whose Thread the send path creates is found at once.
11. As the owner, I want the bell's "mark notifications read" refused on Fansly with zero Fansly requests, so that a write nobody has captured is never sent.
12. As a chatter on a Fansly Creator, I want the Notifications panel to keep its counts with no mark-read control or POST for Fansly, and "Mark all read" in a mixed scope to mark only the OnlyFans Creators and still clear the badges, so that a refused write never shows as a failure.
13. As an owner on OnlyFans, I want mark-read to work exactly as today, so that the gate costs nothing.
14. As an owner on a Fansly Creator, I want the expiry, expired and resubscribe toggles disabled with "not on this platform", so that I never switch on a message that will never send.
15. As an owner who switched one of those on before this change, I want to still be able to switch it off and save, even when the rule holds a discount and the price lookup fails, so that a legacy rule has a way out.
16. As an owner, I want the config API itself to refuse any save for those kinds on Fansly whose merged state is on (501 with the `platform_lacks:` reason), including a partial body that omits `enabled` over a stored on, so that a stale tab or a script cannot store it.
17. As an owner, I want the birthday message and every OnlyFans lifecycle kind unchanged, so that only unobserved cases refuse.
18. As an owner on a Fansly Creator, I want the dashboard's new-fans KPI and the LTV it feeds to show "—" without a request, even when IndexedDB or the screen bundle cached a number, so that I never read a stale or fake 0.
19. As a chatter on a Fansly Creator, I want the fan-activity feed skipped in both the Fan List and the Fan Drawer (no per-account transactions call), so that neither waits on a refused read.
20. As a chatter in a mixed OnlyFans + Fansly scope, I want OnlyFans new fans and fan activity unchanged, so that one Fansly Creator does not blank the others.
21. As an owner editing the welcome on a Fansly Creator, I want the warning "Fansly's own welcome message can't be checked — turn it off in Fansly, or both will send.", so that I know a double welcome is possible.
22. As an owner on Fansly, I want the "after the native welcome" toggle disabled with its reason and the copy to name Fansly instead of "OnlyFans'", so that the screen never claims a check we cannot make.
23. As an owner whose Fansly rule has "after native welcome" stored on, I want to switch it off and save, so that the run-time refusal from Phase 02c can be cleared.
24. As an owner on OnlyFans, I want the welcome editor unchanged, so that the Fansly copy never leaks.
25. As the owner, I want proof that one Fansly autoreply turn (executor not in Cell mode) sends the same visible text as on OnlyFans, with each transport's own payload (wrapped `text` to `/chats/{id}/messages`, `content` to `/message`), so that the shared chain is proven on the Fansly wire.
27. As the owner, I want a banned word to give zero sends and a leak to give the canned deflection on both Platforms, so that the guard holds everywhere.
28. As the owner, I want the parity doc to carry the 🟡 row "OnlyFans word list applied; Fansly's list not captured", so that the word-guard choice is recorded, not hidden.
29. As the owner, I want a fan who follows (3003), one who starts a free trial (15016), and one with both, each to get exactly one welcome, one group and one `WelcomeSent`, with zero on the next tick, and the verdict row to say "page one of `/notifications` only", so that each trigger works alone, two never mean two welcomes, and the coverage gap is stated.
30. As the owner, I want an accepted welcome whose response was lost (Cell mode) to leave one upstream message and a persisted `uncertain` claim, and a fresh-Shim retry over the same fake state to send nothing and create no group, so that a retry never doubles.
31. As the owner, I want a welcome follow-up to land in the same Thread and stop when the fan replies, so that follow-ups behave like OnlyFans.
32. As the owner, I want `send_followup` (not Cell mode) to send once to an anchored paying Fansly fan and to record the measured outcome for a paying fan with no group, and the Cell-mode `no_anchor` refusal pinned on both Platforms, so that each case is a stated verdict, not a silent `{}`.
33. As the owner, I want each of these lanes to update KIND_VERDICTS and the parity rows (with Provenance and Coverage) in this PR, so that the verdict table never lags the code.
34. As the owner adding a Creator, I want the Add Creator flow to take its logo, default login method, extension form id and session prompt from the Platform row, and its submit button to target that row's form, so that a new Platform cannot silently reuse Fansly's form.
35. As the owner editing a Creator, I want the relink and session copy from the row, so that the Edit Creator modal says the right thing per Platform.
36. As the owner, I want the switcher, accounts table, Platform gate and Browserbase login card to read the row, including whether login binds a proxy, so that status copy matches what the Relay really does.
37. As the owner, I want a Creator whose stored platform key is not registered to render as "Unknown platform" with no gated controls, so that it never looks like OnlyFans.
38. As a chatter whose browser stored a stale platform preference, I want it to fall back to OnlyFans as today, so that an old preference never locks the app.
39. As an agent adding Platform #3, I want the drift test to fail when an app row's fields or `bindsProxy` disagree with the registry, and a vitest scan to fail on a literal `=== "<key>"` Platform branch in components, so that a missing row field is caught before merge.
40. As the owner, I want Add Creator and Edit Creator screenshots for OnlyFans and Fansly, so that I can see that the table change kept both flows.
41. As the owner, I want verify-app `--fansly` desktop and phone screenshots (trigger and settled) of the lifecycle editor, the welcome editor, the dashboard KPI and an unsent message leaving a Thread, each with the API response, so that every UI change is proven on the real path.
42. As the owner, I want every refusal this Phase adds to appear in the Lift table with its lift, so that I know what capture or purchase would turn each one back on.
43. As a chatter in a split inbox, I want a delete for a fan I am not granted never to reach my tab, so that unsend events leak no message or fan id.
44. As a chatter scrolling back, I want a history page whose rows were all unsent to still lead to older messages, so that one unsent burst does not end the Thread's history.

## Implementation Decisions
- **Owns.**
  - Relay and Fansly:
    - Fansly socket (`FanslyWebSocket`): typing throttle, group gate and miss cache, plus type-10 translation.
    - Shim: message page `deletedAt` drop; `_as_group_id` hit caching; `notifications_read` marker.
    - Relay events allow-list (`events_decide.SSE_TYPES`) and the `get_messages_tail` cache drop on delete.
    - The notifications mark-read route (in `server.py`); the bell and Notifications page mark-read controls.
    - The lifecycle config API.
  - App:
    - The Thread message cache (`useChatMessages`) and inbox realtime listeners.
    - `lib/platform.ts` (shared with the mirror thread).
    - Lifecycle form reducer and editor.
    - Delayed welcome form reducer and editor.
    - Stats hooks (`useOfNewFans`) and the KPI grid; the fan-activity hook (`useFanActivity`).
    - The components listed in 09 C: PlatformSwitcher, EditCreatorModal, addCreatorWizard, AccountsTable, AddCreatorModal, PlatformGate, BrowserbaseLoginCard.
  - Tests and docs:
    - The drift test; the Platform-branch scan in `app/lib/platform.test.ts` (bans `=== "<key>"` / `== "<key>"` for registered keys in `app/components` outside an allowlist).
    - KIND_VERDICTS rows; the parity doc and its Lift table rows.
- **Interfaces.**
  - **`FanslyWebSocket.send_typing(fan_id) -> bool`.**
    - Resolves the group without minting one. No group gives False with zero requests.
    - The 5 s slot for a group is reserved before the POST, under a lock, so overlapping calls give one POST; a failed POST frees the slot. Within 5 s of a reserved slot it returns True with zero requests.
    - Lookup order: the Shim's cached hit (`_fan_to_group`, no scan) first, then the socket's miss cache, then one scan. A Thread the send path creates is therefore found even while a miss is cached.
    - A miss is remembered per fan inside the socket and lapses after 5 s with no typing call for that fan (two re-emit intervals), which is the hold's life (ticket 08 item 3b). A later hold re-scans once. The Shim is a process-wide singleton, so a permanent miss there would hide a Thread created later.
  - **Shim `_as_group_id`.**
    - A scan hit also writes `_fan_to_group`, so the next lookup skips the scan.
    - A miss keeps today's return value for existing send callers. Typing must not use that fallback: the socket asks for a "group or None" read added beside it. The send path keeps `_group_for_send`'s minting.
  - **Shim message page** (`of_messages_page` and the shapes it feeds): rows with a truthy `deletedAt` are dropped before paging, and `hasMore` still reflects the raw page. When every raw row is deleted and the raw page has more, `get_messages` fetches the next raw page before the lowest raw id, at most 3 extra pages, so the app always gets a cursor while one exists.
  - **Shim `notifications_read`** carries the neutral `platform_blocked` marker (from Phase 02a), reason "bundle-only, never sent". The method body stays, for the lift.
  - **Mark-read route.** It calls `refuse_if_platform_lacks(aid, "notifications_read", "mark notifications read")` before the client call. OnlyFans is unchanged.
  - **Mark-read UI.** `CAPABILITIES` gains `notifications_read` (Fansly lacks it). The bell's once-per-open mark-read skips an account without it; `markAll` receives only ids with it, so its success clears the arrival badges; the "Mark all read" buttons are hidden when no id in scope has it.
  - **Lifecycle config API.**
    - GET adds `refusal: string | null`. It is non-null on Fansly for expiry, expired and resubscribe, and the value is the `platform_lacks:<lack>` reason.
    - PUT for those kinds on Fansly gives 501 with that reason when the merged state (`{**stored, **clean}`) is enabled, checked before any rule write. A partial body omitting `enabled` over a stored on is refused.
    - A save whose merged state is off skips `_check_discounts` and the free-page price check, so off-recovery never needs a price read. OnlyFans keeps today's order for on saves.
    - The kind→Lack map is 02c's `lifecycle_messages.LIFECYCLE_LACKS` (02c owns it, D7); the GET and PUT read it, and the reason comes from 02a's `platforms.lack_reason`.
  - **App `platform.ts`.**
    - Each row gains `logo`, `relink`, `loginDefault`, `extensionFormId`, `sessionPrompt` (an explicit `"none"` allowed) and `bindsProxy`.
    - `CAPABILITIES` gains `subscriber_chart`, `fan_activity`, `native_welcome` and `notifications_read`, and the Fansly row lacks all four.
    - The drift test's row parser is widened for the new fields; a parse that finds no rows fails.
    - `accountPlatform` keeps the missing-key → OnlyFans fallback. A non-empty unregistered key returns an `"unknown"` sentinel: `PLATFORM_NAME` gives "Unknown platform", `can()` is false for every capability, and no row lookup yields controls. Stale browser preferences (`parse`) still fall back to OnlyFans.
  - **Chat cache.** The Thread cache is one flat list per `["messages", accountId, fanId]` (`useChatMessages.ts:169-170`). A pure `evictMessage(list, id)` drops one message by `String(id)`. On `chat_message_deleted` the listener applies it to that Thread's key and adds the id to a bounded per-account tombstone set; `mergeTopPage`, `mergeOlderPage` and `select` filter tombstoned ids, so an in-flight head page or a cached older page cannot restore it. A page emptied only by tombstones still advances the cursor from the raw page.
  - **Lifecycle form.** `LifecycleRules.refusal` is fed from the GET refusal, or from the existing free-page refusal when that one is null. The existing rule stays: `refused` blocks submit only while enabled, and the switch is disabled unless it is currently on.
  - **Delayed welcome form.**
    - A new `nativeWelcomeRefusal: string | null` input disables the after-native-welcome switch unless it is stored on.
    - `canSubmit` refuses `afterOf: true` while the refusal is set.
    - `buildPayload` is unchanged.
    - The editor shows the warning and the copy names `PLATFORM_NAME[platform]`.
  - **Stats and activity hooks.** `useOfNewFans` and the bundle `newFans` mapping return null for any account where `can(platform, "subscriber_chart")` is false, with no fetch and the cached value ignored, so the free card's KPI and its LTV show "—". The paid card's New subs and LTV read `m.new_subs_count` (`PerModelKpiGrid.tsx:186,265-269`), not the refused read, and stay. `useFanActivity` filters out accounts without `fan_activity` before building queries; it is the one gate for FanList and FanDrawer (`FanDrawer.tsx:62-63`).
- **Schema.** None. No table, column or migration.
- **Contracts.**
  - New Relay event `chat_message_deleted`. It is in SSE_TYPES, scoped like `api2_chat_message`, and the frame is keyed by its first key:
    ```ts
    { chat_message_deleted: { id: string; fan_id: string }, __account_id: string }
    ```
    The ids are strings (Fansly ids exceed 2^53). `fan_id` is the key `frame_fan_id` reads for non-`api2_chat_message` events (`events_decide.py:94-112`), so `split_inbox.narrow` drops it for a chatter not granted that fan (`split_inbox.py:365-366`).
  - Mark-read on Fansly: 501 `{"detail": "mark notifications read: not on this platform"}` (the existing `refuse_if_platform_lacks` shape).
  - Lifecycle config GET: `{account_id, kind, config, defaults, refusal}`. PUT refusal: 501 with the `platform_lacks:` reason.
  - The welcome warning text is the one fixed by ticket 13, verbatim.
- **Type-10 mapping.** The translator maps service 5 / type 10 to `chat_message_deleted`. The frame carries the whole deleted message object (`RECIPES.md:398`): `id`, and the fan is `senderId` when it is not the Creator, else the Shim's `_group_to_fan[groupId]`. The `_seen` ring dedupes on the message id. A frame without a message id or a resolvable fan is dropped and nothing is emitted. On emit the Relay calls `relay_cache.invalidate("get_messages_tail", aid, match=chat)` for that fan's chat.
- **Ordering inside the PR:**
  1. Shim and socket edits (one PR holds every `fansly_ws.py` change for Phase 2: 03 item 5 and 08 S1).
  2. Route and config API.
  3. App table and components.
  4. Verdict tests.
- **Coordination.**
  - Before the Shim edit, read the mirror log (M1).
  - `platform.ts` and Shim edits are announced to the mirror thread.
  - After merge, send the sha (M3).
  - `nav.ts` is untouched.
  - The single-platform gates in FuButton and FanslyManagerPage stay as they are.
- **Lift table rows this PR adds or updates:**
  - `notifications_read` Blocked → §6.10 pair plus read-back.
  - Fansly app capabilities `subscriber_chart` / `fan_activity` / `native_welcome` / `notifications_read` → the Shim reason each mirrors.
  - The lifecycle config refusals reuse Phase 02c's `platform_lacks:renewal_state|lapse_detection|return_detection` rows and add "config API + editor" to Where it refuses.
- **OnlyFans controls.** Every shared change runs an OnlyFans twin: span eviction unchanged, mark-read 200, lifecycle toggles saveable, KPI and activity fetched, welcome copy unchanged, the Add/Edit Creator flow unchanged.

## Testing Decisions
Seams, highest first:
1. **`automation_executor.run_once` over the real Shim and the Stateful fake** (from Phase 02a). This covers stories 25-27 and 29-33. Each test asserts:
   - the persisted `AutomationRun` status and reason, and the job disposition;
   - exact provider calls (`/group`, `/message`, typing POSTs);
   - business rows (`WelcomeSent`, follow-up jobs);
   - a second tick or a fresh-Shim retry for repeat and undo.

   The LLM is stubbed and typing is enabled explicitly, because the harness disables it in test mode. KIND_VERDICTS rows are asserted through Phase 02a's harness.

   Executor mode is explicit per test, because `run_once` returns `no_anchor` for autoreply and `send_followup` in Cell mode before any provider call (`automation_executor.py:627-636`, `send_ops.cells()`). Measured: a claimed job opens a run recorded `skipped`/`no_anchor`, the job ends `done`, and the result carries that run's id; with no job to claim no run opens:
   - positive autoreply and `send_followup` lanes run with `OI_CELL_MAP` unset;
   - a Cell-mode twin pins `{"status":"skipped","reason":"no_anchor","run_id":<the persisted run>}`, the run row `skipped`/`no_anchor`, the job `done` and zero provider calls, on both Platforms;
   - welcome's lost response runs in Cell mode: one upstream `/message`, the claim persisted `uncertain` (`send_ops.py:334-341`), and the fresh-Shim retry gives zero `/message` and zero `/group`;
   - welcome triggers: 3003 alone, 15016 alone, and both, each through the real Shim's `notifications`; plus a partial page (trigger past `limit`) and a second tick.

   Mutation check (one per harness, D6): letting typing mint a group must turn a test red.
2. **The FastAPI app via its test client** (stories 11, 13, 16, 17):
   - mark-read 501 on Fansly, with a recorder showing zero Shim `_request` calls, and 200 on OnlyFans;
   - lifecycle PUT on/off per kind and Platform, with the rule-row delta; off with a discount while `subscribe_price_cents` fails (200); a partial body omitting `enabled` over a stored on (501);
   - GET `refusal` (`kind=expiry_message`);
   - a scrubbed type-10 frame through the socket into `events.publish`, then the SSE fan-out with `split_inbox.narrow` for one granted and one denied chatter: granted receives it, denied receives nothing; the `get_messages_tail` entry for that chat is gone.
3. **The `FanslyWebSocket` public surface** (stories 6-10, plus the type-10 half of 1-2). It is driven by `_frame(service_id, event)` with a fake client. Tests assert:
   - the emitted event, by string id;
   - dedupe;
   - throttle timing, using an injected clock;
   - hit and miss scan counts;
   - zero POSTs without a group;
   - two overlapping calls give one POST;
   - a miss, then the send path creating the Thread, then typing hits with no scan;
   - the miss lapsing after a 5 s gap and a new hold re-scanning once.

   The type-10 fixture is built from the RECIPES shape (whole message object), not the type-2 `READ_RECEIPT` fixture (`test_ws_translate.py:69-71`).

   The Shim shape test covers the `deletedAt` drop and the all-deleted page walking to the next raw page.
4. **App pure modules under vitest:**
   - `evictMessage` table: `[A,B]` minus B, minus A, missing id, numeric vs string id, other Thread untouched;
   - the realtime listener evicting and tombstoning; a stale head response resolving after eviction; an older page (cached) containing the id; an all-tombstoned older page still advancing the cursor;
   - the bell skipping the open-time POST and `markAll` receiving only OnlyFans ids in a mixed scope, with badges cleared; the button hidden in a Fansly-only scope;
   - the `platform.ts` table: unknown key, missing key, stale preference;
   - lifecycleForm and delayedWelcomeForm reducer rows: refusal on, stored on, off-recovery, OnlyFans control;
   - the KPI null gate with a seeded stale 0 and a warm bundle value, asserting the settled free card (KPI and LTV "—") and the paid card;
   - the fan-activity account filter in a mixed scope, through FanList and FanDrawer;
   - the wizard default method per row, and the Add Creator submit button's `form` equal to the row's `extensionFormId`.

   The drift test covers the new row fields, the new capabilities in CAP_METHODS (`subscriber_chart`→`subscribers_chart`, `fan_activity`→`transactions`, `native_welcome`→`my_settings`, `notifications_read`→`notifications_read`), `bindsProxy` against `bind_login_proxy`, and fails on an empty row parse. The Platform-branch scan in `lib/platform.test.ts` fails on a seeded `=== "fansly"` in a scratch component string and passes on the allowlist.
5. **verify-app `--fansly`** (stories 40-41). It drives the running app:
   - desktop and phone screenshots of trigger and settled states;
   - `api` responses as the side effect;
   - the unsent-message proof uses `drive.py sse --type chat_message_deleted` into an open Nova Thread. This mocks the browser's events route (`drive.py:397-402`), so it proves only the app half; Relay delivery and narrowing are proven at seam 2.

Prior art:
- Socket and Shim: `fansly/test_ws_translate.py` (`_FakeClient`, `_frame`), `fansly/test_shim_shapes.py`.
- Relay and executor:
  - mark-read and SSE: `service/tests/test_notifications_mark_read.py`, `test_chat_read_changed_sse.py`, `test_events_decide.py`;
  - lifecycle: `test_lifecycle_messages.py`;
  - senders and guard: `test_autoreply.py`, `test_outbound_word_guard.py`, `test_send_welcome.py`, `test_send_followup.py`;
  - typing and socket pump: `test_typing_indicator.py`, `test_full_ai_live_typing.py`, `test_fansly_ws_pump.py`;
  - Fansly gates, drift, screens: `test_fansly_automation_gates.py`, `test_platform_table_drift.py`, `test_screens_api.py`.
- App:
  - `lib/platform.test.ts`;
  - growth forms and editor: `lifecycleForm.test.ts`, `delayedWelcomeForm.test.ts`, `LifecycleMessageEditor.test.ts`;
  - hooks: `useChatMessages.test.tsx`, `useInboxRealtime.test.ts`;
  - stats and setup: `PerModelKpiGrid.test.tsx`, `addCreatorWizard.test.ts`, `AccountsTable.test.tsx`, `BrowserbaseLoginCard.test.tsx`;
  - bell: `NotificationBell.test.tsx`. New in this PR: `AddCreatorModal.test.tsx`, `FanDrawer.test.tsx`.

## Acceptance
```sh
set -e
cd "$(git rev-parse --show-toplevel)"
nice -n 10 venv/bin/python scripts/run_tests_parallel.py fansly test_ws_translate -j 8
nice -n 10 venv/bin/python scripts/run_tests_parallel.py fansly test_shim_shapes -j 8
nice -n 10 venv/bin/python fansly/test_lift_table.py
for t in test_notifications_mark_read test_lifecycle_messages test_chat_read_changed_sse test_events_decide \
         test_autoreply test_outbound_word_guard test_send_welcome test_send_followup test_typing_indicator \
         test_full_ai_live_typing test_fansly_ws_pump test_fansly_automation_gates test_platform_table_drift \
         test_platform_kind_verdicts test_screens_api; do
  nice -n 10 venv/bin/python scripts/run_tests_parallel.py service/tests "$t" -j 8
done
(cd app && nice -n 10 pnpm exec vitest run lib/platform.test.ts components/growth/lifecycleForm.test.ts \
  components/growth/delayedWelcomeForm.test.ts components/growth/LifecycleMessageEditor.test.ts \
  hooks/useChatMessages.test.tsx hooks/useInboxRealtime.test.ts components/stats/PerModelKpiGrid.test.tsx \
  components/setup/addCreatorWizard.test.ts components/setup/AddCreatorModal.test.tsx \
  components/NotificationBell.test.tsx components/chat/FanDrawer.test.tsx)
grep -q 'chat_message_deleted' service/events_decide.py
if grep -rnE '=== "fansly"|== "fansly"' app/components/setup app/components/shell/PlatformSwitcher.tsx app/components/shell/PlatformGate.tsx | grep -v "\.test\."; then exit 1; fi
grep -q "Fansly's list not captured" fansly/FANSLY_PARITY_STATUS.md
venv/bin/python scripts/comment_budget.py --check
heads="$(PYTHONPATH=. venv/bin/alembic -c service/db/migrations/alembic.ini heads)"
test "$(printf '%s\n' "$heads" | grep -c '(head)')" -eq 1
nice -n 10 scripts/run-tests.sh
(cd app && nice -n 10 pnpm test:run)
export VERIFY_APP_RUN=mp2-02d
nice -n 10 scripts/verify-app/drive.py up --fansly
scripts/verify-app/drive.py login --as owner
scripts/verify-app/drive.py api "/admin/lifecycle-message-config?account_id=900539700124344320&kind=expiry_message" | grep -q 'platform_lacks:'
scripts/verify-app/drive.py goto "/growth/smart-messages?tab=automated"
# manual: select Creator Nova Reyes and open the Expiry editor if the route does not land on it
scripts/verify-app/drive.py screenshot --path 02d-lifecycle-fansly.png
scripts/verify-app/drive.py screenshot --phone --path 02d-lifecycle-fansly-phone.png --text "not on this platform"
# manual: open the Welcome editor for Nova Reyes
scripts/verify-app/drive.py screenshot --path 02d-welcome-fansly.png
scripts/verify-app/drive.py screenshot --phone --path 02d-welcome-fansly-phone.png --text "Fansly's own welcome message"
scripts/verify-app/drive.py goto "/"
scripts/verify-app/drive.py screenshot --path 02d-kpi-fansly.png
scripts/verify-app/drive.py screenshot --phone --path 02d-kpi-fansly-phone.png
scripts/verify-app/drive.py reads --match subscribers/chart | grep -q '"count": 0'
scripts/verify-app/drive.py goto "/messages-pro/900539700124344320"
# manual: open Miles B.'s Thread, note one message id, then queue its delete
scripts/verify-app/drive.py sse --type chat_message_deleted --json '{"chat_message_deleted":{"id":"<msg id>","fan_id":"<fan id>"},"__account_id":"900539700124344320"}'
scripts/verify-app/drive.py screenshot --path 02d-unsent-settled.png
scripts/verify-app/drive.py screenshot --phone --path 02d-unsent-settled-phone.png
scripts/verify-app/drive.py goto "/creators"
# manual: open Add Creator, pick Fansly then OnlyFans; open Edit Creator for Nova Reyes and for one OnlyFans Creator
scripts/verify-app/drive.py screenshot --path 02d-add-creator-fansly.png
scripts/verify-app/drive.py screenshot --path 02d-add-creator-onlyfans.png
scripts/verify-app/drive.py screenshot --phone --path 02d-edit-creator-fansly-phone.png
scripts/verify-app/drive.py down
# manual: owner's post-deploy DM Live check on the Proof fan (welcome, follow-up, autoreply, typing shows and clears) — does not block merge
```

## Depends on
- **Phase 02a:**
  - the grant API (`live_check`, `live_check_targets`, `PLATFORM_LIVE_CHECK` `fan=` grammar);
  - `platforms.lack_reason`;
  - the neutral markers (`platform_blocked` used here);
  - `UnknownPlatform` and the `platform_unknown:` refusal on the Relay side (02d adds the app half);
  - `send_refusal` and the Shim's validate-before-group (13 B's zero-extra-group retry relies on it);
  - the KIND_VERDICTS harness and the Stateful fake;
  - the new `Lack` members (`RENEWAL_STATE`, `LAPSE_DETECTION`, `RETURN_DETECTION`);
  - `fansly/test_lift_table.py` and the Lift table section.
- **Phase 02c:**
  - `lifecycle_messages.LIFECYCLE_LACKS` and the lifecycle sweep `platform_lacks:<lack>` gates (05 B's API refusal reads the same map);
  - `subscribers_chart` and `transactions` refusing at the Relay (07 B is their app half);
  - the `followed` notification type and the `send_welcome` Fansly trigger reading `followed` + 15016 (13 B's 3003 + 15016 proof);
  - the raw `hasMore` on Shim `notifications` (06 D), which the welcome partial-page test reads;
  - the toggle-on `platform_lacks:my_settings` refusal (13 E's editor is its UI);
  - refusal-before-typing (08 S4 builds on it).
- Linear PR order (D8): 02a-1 → 02a-2 → 02b → 02c → **02d** → 02e → 02f → 02h → 02g.

## Out of Scope
- **`pnpm typecheck` in `scripts/run-tests.sh`.** Cut (D6): `tsc` state on main is unmeasured here; the vitest scan and drift test cover story 39.
- **`isOnline` from `lastSeenAt` (03 item 1).** It belongs to Phase 02c; 02d does not touch `of_user`.
- **The DB `Message` row for an unsent Fansly message** (soft-delete flag, reply-guard effects). Nothing in the plan asks for it, and the Shim drop plus live eviction is all 03 item 5 requires. YAGNI.
- **Typing before a first message** (no group yet). Ticket 08 parks it under Fog and ticket 13 does not build it, so typing stays silent until a group exists.
- **Measuring Fansly's real outbound typing cadence and clear.** That needs a capture, which agents never take, so only the 5 s constant falls on a capture.
- **Lifting `notifications_read`.** It needs owner capture §6.10.
- **Notification counts, the `followed` type and raw `hasMore`.** They belong to 06 D (Phase 02c).
- **The lifecycle Shim status sets and roster completeness (05 C)** belong to Phase 02b. **`expired_over_days` (05 D)** belongs to Phase 02c.
- **The referrals `unavailable` fix (07 C)** belongs to Phase 02c. **The Shim refusals and bundle 501s (07 A)** belong to Phase 02c, and **the parity doc wording (07 D)** to Phase 02h.
- **Refusal-before-typing (08 S2)** belongs to Phase 02c.
- **The Shim validate-before-group (13 F)** belongs to Phase 02a. **The toggle-on run-time refusal (13 A)** belongs to Phase 02c.
- **Native welcome-rule read and writes (13 items 4, 5).** The read needs a scrubbed fixture, and the writes are mirror-owned.
- **A word list specific to Fansly (08 item 2).** No capture exists; the 🟡 row records the choice.
- **09 items 1-5, 7 and 8** belong to Phase 02a or are parked by the ticket. This Phase adds no generic `/admin/session/{key}` and no scaffold script.
- **`nav.ts`, FuButton and FanslyManagerPage** stay single-platform; they are mirror-owned or deliberate feature gates.
- **Deploy.** It runs after Phase 02h merges, per ticket 11.

## Further Notes
- ASSUMPTION: the new neutral event name is `chat_message_deleted`, and the app evicts it across the Creator's cached Threads. This is rung 3 (the `chat_typing` / `chat_read_changed` naming). The ticket assumed an existing OnlyFans handler, and none exists (measured: no per-message delete in `useChatMessages.ts` or `events_decide.SSE_TYPES`), so 02d adds one as the ticket's fallback prescribes. Overturned if Phase 02a or the mirror names a delete event first; only the string falls.
- ASSUMPTION: the type-10 message object carries `id`, `groupId` and `senderId` like the type-1 message (`RECIPES.md:398` says "the whole deleted message object"; field names from the type-1 fixture in `test_ws_translate.py`). This run did not open fansly/capture/out/. Overturned by a scrubbed type-10 fixture; then only the field mapping changes.
- ASSUMPTION: "the hold's life" (ticket 08 item 3b) is approximated in the socket as a sliding 5 s idle gap per fan, because the socket cannot see the hold (rung 3 of the binding Answer's intent + rung 4). A hold's quiet or think phase longer than 5 s costs one extra scan. Overturned if the hold passes a hold id to `emit_typing`; then the miss keys on it.
- ASSUMPTION: the 5 s throttle constant is ticket 08's, from ~5 s inbound announce frames. Overturned by a capture of the Creator's own typing POSTs; the constant falls.
- ASSUMPTION: app capabilities `subscriber_chart`, `fan_activity` and `native_welcome` map to Shim methods `subscribers_chart`, `transactions` and `my_settings` in the drift test (rung 3: the existing CAP_METHODS pattern). Overturned if the drift test cannot express a method that refuses with `returns=None`; then `native_welcome` goes to APP_ONLY.
- ASSUMPTION: the unknown-key sentinel `"unknown"` lives only in the app (not in `PLATFORMS`), so the drift test's table-keys-equal-registry check still holds. Overturned if Phase 02a's ADR-0068 wording requires the app row; then the drift parser skips it.
- `pnpm typecheck` is not added to `scripts/run-tests.sh` (D6, Cut); the vitest Platform-branch scan carries story 39 instead.
- ASSUMPTION: ticket 13 item 9 reads `no_anchor` as a no-group outcome. Measured: it fires for every autoreply and `send_followup` in Cell mode, grouped or not, and never outside it (`automation_executor.py:119,538-540`). So the Verdict rows split by mode: Cell mode → declared `no_anchor` lane on both Platforms (the ticket's verdict text, kept); non-Cell → measured on the Stateful fake (expected: the send path mints one group and sends once, as `_group_for_send` does). Neither is `{}`. Which mode prod runs is not observable here (floor 2). Overturned by the test result; only the Verdict row text changes.
- Measured (was an ASSUMPTION that no `AutomationRun` opens): in Cell mode a claimed autoreply or `send_followup` job opens one `AutomationRun` recorded `skipped`/`no_anchor`, the job ends `done`, and the return carries its `run_id`; only with no job to claim does no run open (`automation_executor.py:627-636`). Same on both Platforms; 02d pins it and does not change it (rung 4).
- ASSUMPTION: the app tombstone set holds at most 500 ids per account for the tab's life (rung 5); after a reload the Shim drop and the Relay cache drop cover story 3. Overturned by a reload within the 5-minute cache on a tab that never saw the event, on another Relay worker; then the cache drop must be shared.
- ASSUMPTION: the Shim walks at most 3 extra raw pages past an all-deleted page (rung 5). Overturned by a Thread with a longer unsent run; only the constant falls.
- ASSUMPTION: the paid card's `m.new_subs_count` on Fansly comes from Relay DB rows, not from `subscribers_chart` or `transactions`, so 07 B leaves it (rung 1 for the read path `PerModelKpiGrid.tsx:186`; its Fansly source is inferred). Overturned if its source is a refused read; then the paid KPI and LTV gate too.
- ASSUMPTION: the verify-app route steps marked `# manual:` (Creator pick, editor open, Thread pick) are clicks a worker performs with `drive.py click`. Their exact targets are not fixed here because the seed's ids are runtime data. Overturned by a deep-link route; the manual lines become commands.
- ASSUMPTION: the lifecycle editor's disabled reason reuses the GET refusal string, and the free-page refusal applies only when that string is null. This is rung 3 (`useFreePageRefusal` precedent). Overturned if both should show; then the reducer takes a list.

## Review
Reviewer: codex (blind + draft), 2026-11-27
- Blind 1, Cell mode falsifies autoreply/`send_followup` positive lanes; lost welcome needs `uncertain` claim — **accept**. Measured `automation_executor.py:119,538-540`, `send_ops.py:320-321,334-341`. Testing seam 1 gains explicit modes; stories 25, 30, 32 rewritten.
- Blind 2, unsend needs a new consumer, type-10 fixture, Relay replay, split-inbox, stale page — **accept**. `useUnsendMessage.ts:42-45` evicts only the initiating tab; `test_ws_translate.py:69-71` is type 2; `RECIPES.md:398` type 10 = whole message. Contract, tombstones, Relay test and fixture rule rewritten.
- Blind 3, welcome partial-feed verdict, each code alone, second tick — **accept**. `fansly_shim.py:1306-1324` slices one raw page by offset; `send_welcome.py:609-634`. Story 29 + seam 1 + Depends on (06 D).
- Blind 4, typing strict resolver, miss-then-thread, simultaneous emits — **accept**. `fansly_shim.py:2011` falls back to the input; `fansly_ws.py:52-61` has no lock. Lookup order, reserve-before-POST, sliding miss.
- Blind 5, gate before cache reuse, paid card, both activity consumers — **partial**. Warm-bundle seed, settled free card + LTV, FanList + FanDrawer accepted. Paid card's New subs/LTV read `m.new_subs_count` (`PerModelKpiGrid.tsx:186,265-269`), not a refused read: kept, ASSUMPTION added. Bundle per-read 501 is 07 A (Phase 02c).
- Blind 6, lifecycle off-recovery with price failure, hide mark-read, 09 C submit target — **accept**. `lifecycle_message_config_api.py:155-160`, `NotificationBell.tsx:311-315`, `AddCreatorModal.tsx:277-278`. Lifecycle API, Mark-read UI, submit-target test.
- Draft blocker 1, delete delivery bypasses split-inbox grants; acceptance bypasses Relay — **accept**. `events_decide.py:111` reads `fan_id`; `split_inbox.py:365-366` passes `None`; `drive.py:397-402` mocks the events route. Contract → `fan_id` + `__account_id`, unresolved fan dropped, Relay-level narrowing test; verify-app labelled app-half only.
- Draft major 2, deleted rows return via in-flight/cached pages; all-deleted page ends history — **accept**. `useChatMessages.ts:169-170` merges into prev; `server.py:2824-2830` 300 s cache; `useChatMessages.ts:240-246` stops when not progressed. Tombstones, `relay_cache.invalidate`, Shim walk; stories 3, 44.
- Draft blocker 3, explicit modes; 13 D needs plan correction — **partial**. Modes accepted (as blind 1). Ticket 13 item 9's premise is factually wrong (measured), so rows split by mode, Cell keeps the ticket's `no_anchor` verdict, non-Cell is measured; ASSUMPTION instead of re-opening the ticket. Validate-before-group is no longer cited as the retry proof; the Cell claim is.
- Draft major 4, welcome dedup passes with one trigger broken — **accept**. Each code alone + both, plus the "ignoring either code" mutation.
- Draft major 5, lifecycle off-recovery fails on discount price check; partial update inherits stored on — **accept**. `lifecycle_message_config_api.py:155-158` checks before merge, `:163` merges. Gate on merged state; off skips price checks; story 15, 16.
- Draft major 6, concurrent typing POSTs; socket-wide 120 s miss breaks ticket 08's hold lifetime — **accept**. Binding Answer `08-fansly-ai-chatter.md` item 3b says "for the hold's life"; 120 s TTL replaced by a sliding 5 s idle gap, slot reserved under a lock.
- Draft major 7, mark-read stays actionable against ADR-0056 — **accept**. `NotificationsPage.tsx:69-71` keeps badges on any failure; `NotificationBell.tsx:478-487`. `notifications_read` app Capability added; Out of Scope bullet removed; story 12 rewritten.
- Draft major 8, KPI and setup checks miss consumers; reads logger only counts — **partial**. `drive.py:576-579` returns `count`: acceptance now asserts 0; submit-target test added. Paid card kept (as blind 5).
- Draft blocker 9, acceptance: `kind=expiry` 422, `!` grep and Alembic guards pass broken — **accept**. `lifecycle_message_config_api.py:40-43`, `lifecycle_messages.py:41`. `kind=expiry_message`, `if grep …; then exit 1; fi`, heads counted on captured output with `-eq 1`.

Counts: accept 12, partial 3, reject 0, needs-human 0.

Plan review (six hats + coordinator D1–D8), 2026-11-27:
- White [02c,02d], kind→Lack map rebuilt "if 02c exposes none" — **accept**. 02d imports 02c's `LIFECYCLE_LACKS` (D7); the fallback ASSUMPTION is deleted.
- Blue [02b,02c,02d,02f,02g], cite 02a's names — **accept**. Depends on cites `live_check`, `live_check_targets`, the `fan=` grammar and `platforms.lack_reason`.
- D6 `pnpm typecheck` — **accept**. Not added to run-tests.sh; the tsc ASSUMPTION becomes the vitest Platform-branch scan decision; Acceptance lines removed; Cut recorded in Out of Scope.
- D6 mutations — **accept**. Five harness mutations cut to one (typing mints a group); the other four behaviours stay as plain positive/negative tests.
- D8 linear order — **accept**. Line added to Depends on.
- Real handle in the manual line replaced with "the Proof fan" — **accept**.
Counts: accept 6 · partial 0 · reject 0 · needs-human 0.
