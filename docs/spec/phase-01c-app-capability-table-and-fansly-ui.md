# Phase 01c — App capability table and Fansly UI

**Objective.** The app learns each Platform and its Capabilities from one Platform table that a Drift test holds to each Shim, a Fansly Creator's screens render only controls its Platform can back, the 12 placeholder Fansly Manager rows are gone, and setup lists Platforms from the table; OnlyFans screens are unchanged.

## Problem Statement
A chatter on a Fansly Thread sees OnlyFans controls the Fansly Shim cannot back: Pin, Mark unread, Restrict, Block, Search, Gallery, vault Remove, mass-message launchers, Special offers, the native templates list and the Pinned / With Tips / Priority / folder chips. Clicking them does nothing, shows "0 matches" for a search never run, filters nothing, or reports a success that did not happen. The Fansly sidebar holds 12 "not built yet" placeholder pages. Setup, the Platform switch and the account types hardcode exactly two Platforms, so a third site means edits scattered across a dozen files with nothing to say which were missed. A chatter's roster rows carry no `platform` (`service/chatters.py:368-383`, `useAccounts.ts:79-95`), so any Platform gate reads a chatter's Fansly Creator as OnlyFans. The Fansly login card still tells the owner the Relay keeps a session whose `me()` failed (`FanslyPasteSessionCard.tsx:138-139`), which Phase 1a ends, and a relink from a Fansly row accepts a blob for any other Fansly account.

## Solution
One static Platform table in the app names each Platform, its label and the Capabilities it lacks. Every gated control asks `useCan(accountId, cap)` (or `can(platform, cap)` for a loaded Creator) and is not rendered when the answer is no, including while the Creator's Platform is still unknown, so nothing flashes on a Fansly Thread. Its read is gated inside the read's own query hook, so no caller sends it. A Relay-side Drift test fails whenever the table and a Shim disagree, using the same refusal rule as the Relay's Side-effect gate. The Fansly sidebar keeps only its built pages. Setup, the switcher's unread buckets, the Creators table and its Platform filter read the table, so adding a Platform starts with one table row, and the type system flags the login card and nav entry it still needs.

Session scope: the chatter roster gains `platform` in this Phase (a one-field Relay DTO change plus the app's row mapping), so every story below holds for a chatter as well as the owner, and no gate fails open between this Phase and 1d. The Fansly login card stops promising a kept dead session and, on a relink, refuses a blob for another account before it is sent.

## User Stories
1. As a chatter on a Fansly Thread, I want no Pin / Unpin action on bubbles and no Pinned bar, so that I never pin into nothing.
2. As a chatter on a Fansly Thread, I want no Mark unread in the Thread header, so that I do not think the fan was flagged.
3. As a chatter on a Fansly Thread, I want no Restrict and no Block in the chat actions menu, so that I never trigger a fake moderation action.
4. As a chatter on a Fansly Thread, I want no in-Thread Search, so that I never read "0 matches" for a search that never ran.
5. As a chatter on a Fansly Thread, I want no Gallery button in the Thread header or Fan List header and no media sections in the Fan drawer, so that I am not shown an empty gallery as if the fan sent nothing.
6. As a manager in Vault pro on a Fansly Creator, I want no Remove in the selection bar or the manage panel, so that nothing reads as removed when Fansly kept it.
7. As a manager in Fansly mode, I want no mass-message rows in the Fan List header's New menu (its Post row stays), so that I never open a broadcast Fansly would skip.
8. As a manager composing a mass message, I want Fansly Creators left out of the sender list, the All-models chips, the scope auto-seed and the Smart Messages seed, so that no send path can start from a Creator whose send would be skipped.
9. As a chatter on a Fansly fan's avatar menu, I want no Special offers row, so that I never promise a discount that cannot be set.
10. As a chatter opening the template picker on a Fansly Thread, I want my local Scripts and no OnlyFans native template read, so that the picker loads what exists.
11. As a chatter in a Fansly-only scope, I want no Pinned, With Tips, Unread with tips, Priority or folder chips, so that every chip filters something.
12. As a chatter in a scope mixing Platforms, I want a chip shown when any Creator in scope has its Capability, so that OnlyFans filters still work there.
13. As a chatter whose scope change hides the chip I had selected, I want the filter reset to All before the list is requested, so that I am not left on an invisible filter and no request carries it.
14. As a chatter on any Thread, I want the All, Owe reply, Unread and Scheduled chips kept, so that working filters and cancellable relay-queued sends stay.
15. As a chatter whose Creator list is still loading, I want gated controls absent until the Creator's Platform is known, so that Fansly Threads never flash OnlyFans controls.
16. As a user of an OnlyFans Creator saved before the `platform` field existed, I want it treated as OnlyFans, so that its controls stay.
17. As a composer user on a Fansly Creator, I want no rich-text toolbar, so that OnlyFans markup never reaches Fansly; in OnlyFans All-models mode the toolbar stays.
18. As a user in Fansly mode, I want the Fansly Manager group to list only Scheduled Posts, Lists, Notifications and Earning Statistics, so that the sidebar has no placeholder pages.
19. As a user opening an old `/fansly-manager/<placeholder>` URL, I want a 404, so that dead pages do not pretend to exist.
20. As a user with the `fansly_manager` flag off, I want the Fansly Manager group gone and the Platform switch to land on Scripts, so that switching never lands on a blank page.
21. As the assistant's command prepass, I want navigation candidates without placeholder rows, so that "open Settings" never targets a dead Fansly page.
22. As an owner adding a Creator, I want the wizard's Platform choice and its "first Platform not yet linked" default to come from the table, so that a new Platform appears without wizard edits.
23. As an owner on the Creators table, I want Platform labels and the Platform filter options read from the table, so that each Creator's Platform reads correctly.
24. As a user of the Platform switch, I want per-Platform unread built from the table, so that a third Platform gets a bucket with no edit there.
25. As an owner, I want the mym and Fanvue "Coming soon" rows kept in the switcher, so that the teasers stay.
26. As a developer adding a Platform, I want the Platform type derived from the table and its login card and nav entry required by the types, so that one table row plus the cards the compiler names is the whole app edit.
27. As a developer changing a Shim, I want the Drift test to fail when a Capability's methods and the table disagree, so that the app never shows a control the Shim cannot back, or hides one it can.
28. As a developer, I want the Drift test to fail when a Capability is neither mapped to Shim methods nor listed as app-only, so that a new Capability cannot skip the check.
29. As a developer, I want the Drift test to fail when the table's keys differ from the Platform registry's, so that app and Relay name the same Platforms.
30. As the owner, I want proof on the real path: both Threads screenshotted on a seeded stack and zero requests to the gated routes from the Fansly Thread, so that "hidden" is shown, not claimed.
31. As a chatter (employee login), I want my roster to carry each Creator's Platform, so that my Fansly Creators' controls hide exactly as the owner's do.
32. As the owner linking a Fansly Creator, I want a refused link to show the Relay's reason and a success never to say the session was kept without a name, so that the card matches what the Relay did.
33. As the owner relinking a Fansly row, I want a pasted blob whose `accountId` is not that row's refused before any request, so that a paste from the wrong tab never adds a second Creator.

## Implementation Decisions
- **Owns.** Platform table module (`app/lib/platform.ts`) and its new test; relay account type (`relayTypes`); nav (`app/lib/nav.ts`, its test), the Fansly Manager route and `NotBuiltYet` (deleted), assistant prepass; the gated read hooks `useChatPinned`, `useFanChatMedia`, `useChatFolders` (both exports), `useTemplates`, and `ChatSearch`'s read; the gated components of ticket 02 item 6 (bubble actions, Pinned bar, Thread header extras, chat actions menu, Thread header, Fan List header, Fan drawer, vault selection bar and manage panel, account picker, All-models chips (`IncludeModelsChips`), mass composer, Smart Messages page and create pop-up, avatar menu, template picker, Fan List filters and Fan List), `useOfRichAllowed` and its All-models callers (`MassMessageComposer`, `PostComposer`); setup (add-Creator wizard and modal, Creators table, Creator filter bar and `creatorRowFilter`, `EditCreatorModal`, `FanslyPasteSessionCard` and the Fansly row's relink entry in `AccountsTable`), Platform switch; a Fan List chip helper and the one mass-sender helper (`massSenders.ts` beside `MassMessageComposer`), each a pure `.ts`; the chatter roster `platform` field (Relay `chatters` flat roster DTO, `useAccounts`' chatter row mapping); the Relay-side Drift test; the verify-app seed's one Fansly Creator (behind `--fansly`, fixed ids, fixtures).
- **Interfaces.** The Platform table module exports:
  ```ts
  export const CAPABILITIES = ["pin_message", "mark_unread", "restrict", "block", "chat_search", "chat_media",
    "vault_remove", "mass_message", "discount", "native_templates", "filter_tips", "filter_priority",
    "filter_folders", "rich_text"] as const;
  export type Capability = (typeof CAPABILITIES)[number];
  export const PLATFORMS = [
    { key: "onlyfans", label: "OnlyFans", lacks: [] },
    { key: "fansly", label: "Fansly", lacks: [/* all 14 today */] },
  ] as const satisfies readonly { key: string; label: string; lacks: readonly Capability[] }[];
  export type Platform = (typeof PLATFORMS)[number]["key"];
  can(platform: Platform | null, cap: Capability): boolean       // null -> false
  useAccountPlatform(accountId: string | null | undefined): Platform | null
  useCan(accountId: string | null | undefined, cap: Capability): boolean
  ```
  `PLATFORM_NAME`, the stored-switch parse and `accountPlatform` derive from `PLATFORMS`; `accountPlatform` maps a missing or unknown key to `onlyfans`. `useAccountPlatform` reads the Creator list `useAccounts` already serves (owner list, or a chatter's roster rows) from cache and never fetches; a Creator absent from it is `null`. `useOfRichAllowed(accountId)` becomes `useCan(accountId, "rich_text")`, the one rule for every caller (1d adds none). An All-models composer never passes `null`: the mass composer passes `massSenders(accounts, platform)[0]`, the post composer its first `usePlatformAccounts()` row, so OnlyFans All-models keeps its toolbar and an empty sender list shows none.
  ```ts
  massSenders(accounts: readonly RelayAccount[], platform: Platform): RelayAccount[]
  // keeps accounts with accountPlatform(a) === platform and can(platform, "mass_message"); input order kept
  ```
  In this Phase `platform` is the sidebar's `usePlatform()`; Phase 1d passes the window composer's Platform instead and adds no second helper.
- **Schema.** None.
- **Contracts.** `GET /chatter/me/accounts` rows gain `platform: str`, read through `accounts.get_platform` (`"onlyfans"` for a legacy account); the app's chatter row mapping copies it. The Fansly card's request body is unchanged; a relink entry passes the row's id to the card as `expectedAccountId`. The relay account type's `platform` widens to `string | null`; every reader goes through `accountPlatform`, never `platform ?? "onlyfans"` (the Creators table's `AccountCell` today indexes its label map that way). The Platform table's text is a contract with the Drift test: `CAPABILITIES` and each `PLATFORMS` row are written as string-literal arrays the test reads with a regex, one row per Platform, as `test_role_enforcement.py` reads `nav.ts`.
- **Gating rule.** A control whose Capability is missing is not rendered: no disabled state, no tooltip (ADR-0056). Its read is gated in the query hook itself: `useChatPinned` (`pin_message`), `useFanChatMedia` (`chat_media`), `useChatFolders` / `useAllChatFolders` (`filter_folders`), `useTemplates` (`native_templates`) AND their `enabled` with `useCan(accountId, cap)`, and `ChatSearch` sends nothing without `chat_search`. So every caller is covered, including `ChatSurface`'s pinned slice, the Fan drawer's open/retry/paging, OF Manager's mirror, `FolderPicker`, `FanListBulkBar` and the Templates tab. Thread-level controls use `useCan` with the Thread's Creator. Lists of loaded Creators (sender list, Smart Messages seed, chip scope) filter with `can(accountPlatform(a), cap)`.
- **Mass message.** One pure `massSenders(accounts, platform)` (Interfaces) keeps that Platform's Creators with `mass_message`. `AccountPicker`, `IncludeModelsChips` and `MassMessageComposer` (its `activeAccounts`, hence `includedTargets` and `sendFrom`) read it instead of `usePlatformAccounts` directly. The picker's auto-seed seeds only an eligible id (a scoped Fansly Creator seeds the first eligible one, or none). A forced (`forcedAccountId`) or saved id outside the set is not a sender: `sendFrom` excludes it, so `validateMass` refuses with no sender. The Smart Messages page and create pop-up seed from `massSenders`. The Fan List header's New menu shows its two composer rows when any Creator in scope can; its Post row is not a mass message and stays. Filtering the senders, not only the launchers, is the decision (ticket 02 item 6).
- **Fan List chips.** A pure Fan List chip helper takes the Platforms in scope, `tipsEnabled` and the pinned folder ids, and returns the visible chip set plus the active filter to keep (unchanged if visible, else All). Pinned needs `pin_message` (ticket 02 item 6 gates the Pinned chip; the Shim ignores `filter=pinned`, `fansly_shim.py:1172-1174`), With Tips needs `filter_tips`, Unread with tips needs `filter_tips` and `tipsEnabled`, Priority needs `filter_priority`, a folder chip needs `filter_folders` and its id among the pinned folders, the "Pin lists as chips" pencil needs `filter_folders`. All, Owe reply, Unread and Scheduled always show. Fan List computes the effective filter from the helper during render and builds `serverFilter` / `serverListId` from it, so no request carries a hidden filter; one effect writes it back to `active`, replacing today's two reset effects. `active` stays the only state, so the reducer rule does not apply. The folder reads run only when the single scoped Creator can `filter_folders` (in the hook, above).
- **Nav.** The 12 `notBuilt` rows, the `notBuilt` field, `NotBuiltYet` and its test, the prepass `notBuilt` check and the `nav.test.ts` placeholder cases go. The four flagged pages keep `flag: "fansly_manager"` and their `permission` aliases. The Fansly Manager route renders a built link and calls `notFound()` for anything else. `firstPage("fansly")` resolves to `/growth/scripts`. `PLATFORM_NAV` stays a `Record<Platform, NavNode[]>`, so a new table row fails typecheck until it has a sidebar.
- **Setup.** The wizard's `Platform` and `PLATFORM_LABEL` come from the table. The wizard default is the first `PLATFORMS` key not in `linked`. The modal's Platform choices map `PLATFORMS`; its "link the other" button offers any unlinked key. Login cards stay per Platform in a `Record<Platform, …>`, so a missing card is a type error. The Creators table labels (via `accountPlatform`) and the filter bar's Platform options read the table. The switcher's unread buckets come from `PLATFORMS`; mym and Fanvue stay as cosmetic "Coming soon" rows (ticket 02 item 9).
- **Drift test** (Relay side, `service/tests/test_platform_table_drift.py`, a house plain-assert script: `_harness` first, `_harness.run()` last, as `test_role_enforcement.py`; `run_tests_parallel.py` runs `service/tests` files as plain Python, so a pytest-only file would pass without running). It reads `CAPABILITIES` and `PLATFORMS` from the Platform table's text and holds one map from Capability to OnlyFans-client method names:
  `pin_message`→`pin_message`,`unpin_message`,`get_pinned_messages`; `mark_unread`→`mark_chat_unread`; `restrict`→`restrict_user`,`unrestrict_user`; `block`→`block_user`,`unblock_user`; `chat_search`→`search_chat`; `chat_media`→`chat_media`; `vault_remove`→`hide_vault_media`; `mass_message`→`send_mass_message`,`mass_message_history`; `discount`→`set_subscription_discount`; `native_templates`→`message_templates`.
  It also holds an app-only set: `rich_text`, `filter_tips`, `filter_priority`, `filter_folders`. It asserts:
  - the map and the app-only set partition `CAPABILITIES`;
  - every mapped name is an `OFClient` attribute;
  - the table's keys equal the registry's keys;
  - OnlyFans lacks nothing;
  - for each other registered Platform's Backend module, on its `Shim` class, a mapped Capability is in `lacks` exactly when `side_effect_gate.refusal(Shim, name)` is non-None for every mapped method (1b's rule: missing or carrying either marker), so the app's hide and the Relay's 501 come from one predicate.

  It fails on zero parsed rows, so a format change cannot pass it vacuously. It joins `scripts/run-tests.sh` through the `service/tests` glob.
- **Fansly card.** On success the card shows the id and the name when present, and drops the `accountInfoError` line for `name: null` (1a no longer keeps a session whose `me()` failed). A 400 (identity unproven) shows `FANSLY_T.accountInfoError` and a 409 (the id is another Platform's Creator) `FANSLY_T.loginFailed`, each with the Relay's `detail`; the card's error path already renders status and body. With `expectedAccountId` set (the Fansly row's relink entry, `AccountsTable.tsx:607-612`, passes it through `onLinkAt`), a blob whose `accountId` differs is refused in the card with no request.
- **Seed.** The verify-app dataset gains one Fansly Creator behind an opt-in flag: `drive.py up --fansly` seeds a 21st Creator, "Nova Reyes", meta `platform: "fansly"`, account id `950839700124344320`, one Fan `950839700124344321`, message ids from `950839700124344400` up (all 18 digits, past 2^53), and fixture answers in the Shim's shape (string ids) for her `/api/of/*` reads (chat list, Thread messages, vault). Doctor expects 21 Creators with the flag and 20 without (`drive.py:244` today checks 20). Without the flag the stack is today's. Phase 1d adds only SQLite chats and messages for her and a grant to the seeded chatter, under the same flag.

## Testing Decisions
Seams, highest first:
- **verify-app real path** (the proof seam for every gated control). Throwaway stack with `--fansly`, as owner. Fansly checks run first in the session, because `reads` counts are cumulative:
  1. Open a Thread on Nova Reyes. Desktop and phone screenshots, plus an ARIA snapshot showing no Pin, Mark unread, Restrict, Block, Search, Gallery, Pinned or tip/priority chips. Open the bubble menu, the chat actions menu, the avatar menu and the template picker, and snapshot each (no Pin, Restrict, Block, Special offers; Scripts listed). `reads --match` for `/chats/$FFAN/pinned`, `/chats/$FFAN/media`, `/chats/$FFAN/messages/search`, `/messages/templates`, `/chats/folders`: each 0.
  2. Vault pro on Nova Reyes: select one item, screenshot the selection bar and manage panel (no Remove). Open Growth > Smart Messages create and the Fan List New menu: screenshot (no Nova Reyes sender; no mass rows in Fansly mode, Post row present).
  3. Switch to OnlyFans, open an OnlyFans Creator's Thread, open the template picker and run an in-Thread search. Same controls present; `/pinned`, `/messages/templates`, `/messages/search` reads each above 0, which proves the probe sees them. The composer sender list in All-models shows the Aa toolbar.
  4. `of-writes` count 0. `api /fansly-manager/home` status 404. Screenshot the Fansly sidebar.
- **`can` / `useCan` / `useAccountPlatform`**: a vitest table in the Platform table module's new test. Rows cover:
  - every Platform × Capability;
  - a `null` Platform;
  - a missing or unknown `platform`;
  - an absent account, which reads `null`, so `useCan` is false;
  - a chatter roster row with no `platform`, which reads OnlyFans.
- **Gated read hooks**: one vitest table over `useChatPinned`, `useFanChatMedia`, `useChatFolders`, `useAllChatFolders`, `useTemplates`: a Fansly account and an absent account send no request; an OnlyFans account sends one.
- **Fan List chip helper**: a vitest table over scope Platform sets × `tipsEnabled` × pinned folder ids × active filter (hidden active → All, unpinned folder → All, OnlyFans visibility unchanged).
- **Mass-sender helper**: a vitest table over `massSenders(accounts, platform)`: Fansly dropped, OnlyFans kept, legacy no-`platform` kept, a forced Fansly id yields no sender, `platform: "fansly"` yields none while Fansly lacks `mass_message`, a mixed list with `platform: "onlyfans"` keeps only OnlyFans, and the All-models rich-text read follows its first row.
- **Chatter roster** (Relay, prior art `service/tests/test_chatter_roster_color.py`): `GET /chatter/me/accounts` carries `platform: "fansly"` for a granted Fansly Creator and `"onlyfans"` for a legacy one. Vitest (prior art `useAccounts.test.tsx`): the chatter row mapping copies it, and `useCan` on a chatter's Fansly row is false for every Fansly-lacked Capability.
- **Fansly card** (prior art `components/setup/fanslyLogin.test.tsx`): success with `name: null` shows no `accountInfoError` line; a 400 and a 409 show their wording with `detail`; with `expectedAccountId` a blob for another id sends no request and shows the refusal, a matching blob posts as today.
- **Nav**: `nav.test.ts` asserts the Fansly links are exactly the four flagged pages plus Scripts, Message pro and Vault pro, that the group vanishes with the flag off, and that `firstPage("fansly")` is `/growth/scripts`.
- **Setup**: `addCreatorWizard.test.ts` rows for the first-unlinked default from the table.
- **Drift test**: the script above. A mutation check during build (drop one Fansly `lacks` entry, then add a mapped method to a stub copy) must turn it red.
- Existing tests updated, not added: `FanListFilters.test.tsx`, `PlatformSwitcher.test.tsx`, `BubbleActions.test.ts`.

Prior art: `service/tests/test_role_enforcement.py` (reads `nav.ts`, plain-assert harness), `fansly/test_fansly_capability.py` (marker reading), `app/components/chat/fanDrawerForm.test.ts` (vitest tables), `app/lib/nav.test.ts`.

## Acceptance
```sh
set -euo pipefail
cd repo
for t in platform_table_drift role_enforcement chatter_roster fansly; do scripts/run-tests.sh "$t"; done
(cd app && pnpm exec vitest related --run lib/platform.ts lib/nav.ts components/chat/FanList.tsx \
  components/compose/MassMessageComposer.tsx components/compose/massSenders.ts hooks/useChatPinned.ts \
  hooks/useAccounts.ts components/setup/addCreatorWizard.ts components/setup/FanslyPasteSessionCard.tsx)
(cd app && pnpm exec tsc --noEmit)
! grep -rn "notBuilt\|NotBuiltYet" app/lib app/components app/app
! grep -rn --exclude='*.test.*' '"onlyfans" | "fansly"' app/lib app/components
! grep -rn --exclude='*.test.*' 'platform ?? "onlyfans"' app/lib app/components app/hooks
scripts/run-tests.sh
D=scripts/verify-app/drive.py
cnt() { $D reads --match "$1" | venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["count"])'; }
nice -n 10 $D up --fansly && $D doctor
$D login --as owner
FFAN=950839700124344321   # the seeded Fansly Fan (Seed)
# manual: switch Platform to Fansly, open Nova Reyes's Thread in Messages Pro; open bubble, actions, avatar menus and the template picker
$D screenshot --path fansly-thread.png && $D screenshot --phone --path fansly-thread-phone.png && $D snapshot --path fansly-thread.yml
[ "$(cnt "/chats/$FFAN/messages")" -gt 0 ] || { echo "Fansly Thread never opened"; exit 1; }
for m in "/chats/$FFAN/pinned" "/chats/$FFAN/media" "/chats/$FFAN/messages/search" /messages/templates /chats/folders; do
  [ "$(cnt "$m")" -eq 0 ] || { echo "read sent: $m"; exit 1; }; done
# manual: Vault pro selection on Nova Reyes; Smart Messages create; Fan List New menu
$D screenshot --path fansly-vault.png && $D screenshot --path fansly-new-menu.png
# manual: switch to OnlyFans, open an OnlyFans Creator's Thread, open the template picker, run an in-Thread search
$D screenshot --path of-thread.png && $D screenshot --phone --path of-thread-phone.png
for m in /pinned /messages/templates /messages/search; do [ "$(cnt "$m")" -gt 0 ] || { echo "probe blind: $m"; exit 1; }; done
[ "$($D of-writes | venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["count"])')" -eq 0 ]
[ "$($D api /fansly-manager/home | venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["status"])')" -eq 404 ]
$D down
[ -z "$(git status --short app/tsconfig.json)" ]
```

## Depends on
- **1a**: the Platform registry's keys (`platforms.KEYS`), its Backend modules and each module's `Shim` export (`fansly_backend.Shim`, 1a's contract). The Drift test imports all three. The identity 400 and collision 409 the Fansly card words.
- **1b**: `side_effect_gate.refusal`, which accepts the `Shim` class (1b's Side-effect gate) and which the Drift test calls on it. The three unmarked cases marked: `chat_media` (Blocked), `send_mass_message` (Blocked, gated), `mass_message_history` (Blocked, raises). The gap verdicts for `block_user`, `restrict_user`, `search_chat`, `set_subscription_discount` and `message_templates`, each missing or marked. The Relay Side-effect gates (vault remove, mass send, restrict, discount): hiding here is not the guard.

## Out of Scope
- Relay Side-effect gates and the Capability test: Phase 1b.
- The real-path chatter proof: Phase 1d, which adds the seeded chatter's grant to Nova Reyes; here the roster field is proven by the Relay test and the vitest rows.
- Hiding Bulk Delete: not in ticket 02 item 6's control list; 1b's 501 on `delete_chat` is its guard.
- A Relay-side expected-id check on relink: the card's pre-send check needs no route change (1a keeps the request body).
- `AllPlatformsContext`, Platform badge, combined Messages Pro, per-Creator filter fan-out returning no rows for a Platform that cannot honour a filter, the window's Post button roster: Phase 1d.
- A Relay-served catalog: rejected (ADR-0054).
- Disable-with-reason states: rejected (ADR-0056).
- Building any of the 12 placeholder pages: dropped (ticket 02 item 7).
- A `scheduled_messages` Capability: removed by the ticket; the Scheduled chip is left alone.
- The Thread header's not-wired "Pinned chat" icon: not wired on OnlyFans either, so not a Platform gap.
- mym / Fanvue as Platforms: teasers only.
- Per-component render tests for each gated control: verify-app covers the real path, the read hooks have their own table; YAGNI.
- A slop run: owner constraint.

## Further Notes
ASSUMPTION: `filter_tips`, `filter_priority` and `filter_folders` are app-only in the Drift test beside `rich_text`, because they back `list_chats` arguments and `chat_folders`'s unmarked empty stub, not markable methods, and mapping `filter_folders`→`chat_folders` would need a marker 1b does not add (rung 5). Known blind spot: the test cannot tell when the Shim starts honouring these filters, so the table may hide a working filter. Overturned if the Shim grows per-filter markers or 1b marks `chat_folders`.
ASSUMPTION: 1c owns the verify-app seed's Fansly Creator (ids, fixtures, `--fansly`, 21/20 doctor) and 1d only adds her SQLite chats and the chatter grant, though the plan lists the seed under 1d, because 1c lands first and ticket 02's gating proof needs her (coordinator ruling on shared ownership, rung 5). Overturned if 1d lands first; then 1d builds this seed unchanged.
ASSUMPTION: the seed sits behind the opt-in `--fansly` flag rather than always on (rung 4: default off leaves every other verify-app recipe and the 20-Creator doctor untouched); overturned if the owner wants her in every stack, then the doctor expects 21.
ASSUMPTION: the seed ids `950839700124344320` / `…321` / `…400` and the name "Nova Reyes" are a coin flip (rung 6), moved from 1d; overturned by nothing that matters beyond staying 18 digits and past 2^53.
ASSUMPTION: the chatter roster `platform` field, the one `massSenders(accounts, platform)` helper, the single `useOfRichAllowed` rule and the Fansly card wording and relink check are this Phase's (coordinator ruling on shared ownership, rung 5); overturned if the owner reassigns them, then 1d takes the lines verbatim.
ASSUMPTION: the chatter roster reads Platform through `accounts.get_platform`, which already defaults to OnlyFans (rung 3), moved from 1d; overturned if 1a's registry exposes a different per-account read, which then replaces it.
ASSUMPTION: opening the seeded Thread keeps her 18-digit string Fan id (1d's exact-id fixes are cursors, head-settled, the cold seed and list-add, none on the open path; rung 5, unmeasured); overturned if the `/chats/$FFAN/messages` check reads 0, then 1d's exact-id slice, which can run in parallel, lands before this proof.
ASSUMPTION: the relink's expected id is checked in the card before sending, not by the Relay (rung 4: no route contract change); overturned if a non-card caller relinks, then the route takes an `expected_account_id`.
ASSUMPTION: "1a flag names" means the registry's Platform keys, which the Drift test checks the table against (rung 5). Overturned if 1a names something else the table must mirror.
ASSUMPTION: `useAccountPlatform` reads cache only and never fetches, as `useOfRichAllowed` does today (rung 3). Overturned if a provider-less host needs a fetch.
ASSUMPTION: the Drift test's map names OnlyFans-client methods, the names the Shim answers to, and checks each one exists on `OFClient` (rung 3, `fansly/test_fansly_capability.py`). Overturned if 1a's Backend module exposes a different contract.
ASSUMPTION: the Pinned chip is gated by `pin_message`, as ticket 02 item 6's table places it, though it filters pinned chats rather than pinned messages (rung 2). Overturned if Fansly gains chat pinning without message pinning; then it gets its own Capability.

## Review
codex, 2026-11-24. Blind call 9 findings (B1–B9), draft call 12 (D1–D12).
- B1 **partial** — roster lacks `platform` (`service/chatters.py:368-383`, `useAccounts.ts:79-95`): true, but ticket 05 item 4 puts the field in 1d; added the Session scope paragraph and moved the chatter case to 1d. Cache invalidation is 1d's. Superseded by Six hats Black 3: the field is now this Phase's.
- B2 **reject** — "every mapped method missing or marked" is ticket 02 item 2's rule; no code shows it failing: all three pin methods are marked (`fansly_shim.py:2343,2923,2927`). The argument-level filter half is answered under D9.
- B3 **accept** — Pinned chip gated by `pin_message` (ticket 02 item 6; Shim ignores `filter=pinned`, `fansly_shim.py:1172-1174`); effective filter computed in render before `serverFilter` (`FanList.tsx:276-293`). Per-Creator fan-out rule left to 1d (ticket 05 item 8).
- B4 **accept** — `ChatSurface.tsx:607` reads pins outside the Pinned bar, FanDrawer reads media on open: reads now gated inside the query hooks, which also covers retries, paging and other callers.
- B5 **accept** — sender set built in several places (`AccountPicker.tsx:31-43`, `IncludeModelsChips.tsx:25`, `MassMessageComposer.tsx:88,168`): one `massSenders` helper, eligible-only auto-seed, forced id excluded; Post row kept (`FanListHeader.tsx:43`). Priority mass part rejected: no Priority mass launcher is in ticket 02's control list.
- B6 **reject** — re-opens ADR-0054 / ticket 02 item 1 (static table); no evidence of a split-commit deployment.
- B7 **partial** — OF Manager mirror reads pins and gallery (`ofMirrorData.ts:240-246`): covered by hook-level gating; its roster is 1d (ticket 05 item 10). `AccountsTable.tsx:170` `?? "onlyfans"` accepted: readers go through `accountPlatform`, plus an Acceptance grep (five such readers today: `AccountsTable.tsx:170,456,637`, `creatorRowFilter.ts:37`, `EditCreatorModal.tsx:48`, now owned).
- B8 **partial** — added menu-open steps and per-hook gate table; chatter sessions are 1d; Relay handler tests are 1b's; per-gate mutation beyond the Drift test rejected (YAGNI, owner).
- B9 **reject** — describes the sparse review workspace, not the spec; the real tree has `scripts/verify-app/drive.py`.
- D1 **partial** — same as B1; stories kept, scope paragraph and Out of Scope now say chatter cases land in 1d. Superseded by Six hats Black 3.
- D2 **accept** — `IncludeModelsChips` added to Owns and fed by `massSenders`; forced / auto-seeded ids checked.
- D3 **accept** — Pinned chip now gated; Problem, stories 11 and 14 updated.
- D4 **accept** — `reads` / `of-writes` return `ok:true` at any count (`drive.py:465,477`) and `goto` has no status (`:413`): Acceptance now `set -euo pipefail`, asserts counts, checks 404 via `api` (which returns `status`). The `cd` path is the real repo, kept.
- D5 **accept** — `/media` matches vault reads, templates and search need opening: Fan-scoped matches (`/chats/$FFAN/…`), Fansly first, menus and picker opened, OnlyFans search run.
- D6 **accept** — Vault pro selection, Smart Messages create and New menu added to the real-path steps; mass-sender vitest table added.
- D7 **accept** — `MassMessageComposer.tsx:125` passes `null` in All-models: `useOfRichAllowed(null)` now reads the sidebar Platform's capability.
- D8 **accept** — helper inputs now include `tipsEnabled` and pinned folder ids (`FanListFilters.tsx:214`, `FanList.tsx:274-285`).
- D9 **partial** — true that `chat_folders` is an unmarked stub (`fansly_shim.py:1225-1230`), but mapping it needs a 1b marker 1b does not add; kept app-only, blind spot stated in the ASSUMPTION.
- D10 **accept** — `run_tests_parallel.py:45` runs `service/tests` as plain Python: Drift test is a `_harness` plain-assert script; the Acceptance loop uses `scripts/run-tests.sh <pattern>`, not `--pytest`.
- D11 **accept** — `Shim` export is 1b's (`phase-01b…md:63`), not 1a's: Depends on moved; discount gate added; predicate now 1b's `side_effect_gate.refusal`. The `Shim` half is superseded by Six hats White 1: the export is 1a's.
- D12 **accept** — seed owned twice (plan 1d, this spec): 1c builds it in 1d's exact shape (`phase-01d…md:60`) so 1d's spec still holds; ASSUMPTION updated. Superseded by Six hats Black 1: this Phase owns the seed outright.

### Six hats
Plan review, 2026-11-24 (`multi-platform-p1-plan-review.md`). Shared parts follow the coordinator's one-owner table there.
- White 1 (Depends on and D11 said the `Shim` export and handler were 1b's) — **accept**: Depends on now names 1a for the registry, Backend modules and `Shim`, and 1b for `refusal` only.
- White 2 (card `name: null` wording and relink expected id handed here by 1a, owned by nobody) — **accept**: Fansly card bullet, stories 32-33, tests; the expected id is checked in the card before sending (ASSUMPTION).
- Black 1 (seed owned twice; flag, doctor count and id digits disagree) — **accept**: this Phase owns the seed behind opt-in `--fansly` (rung 4), with 1d's fixed 18-digit ids and the fixtures; doctor 21 with the flag, 20 without; 1d only adds SQLite chats and the chatter grant and passes `--fansly`.
- Black 2 (`FFAN=...` literal makes the zero-read checks pass without testing) — **accept**: `FFAN` is the seeded Fan's real id, and a `/chats/$FFAN/messages` count above 0 now proves her Thread was opened before the zero checks count.
- Black 3 (gates fail open for chatters until 1d; roster field in the wrong Phase) — **accept**: the roster `platform` field (Relay DTO plus row mapping) moved here; Session scope, story 31, Contracts, a Relay test and vitest rows; the Out of Scope line is gone.
- Black 4 (`refusal(Shim, name)` on a class, unpromised) — **accept**: 1b's Side-effect gate now promises a class or an instance and tests both; the ASSUMPTION here is removed.
- Yellow 2 (one predicate drives hide and 501) — **accept**, no change.
- Green 1 (two sender helpers over one list) — **accept**: one `massSenders(accounts, platform)` here; 1d passes its composer Platform and only wires `useMassSend`.
- Green 2 (`useOfRichAllowed(null)` path built here, thrown away by 1d) — **accept**: 1d's rule written once here: All-models callers pass their first sender, never `null`; `PostComposer`'s read joined Owns.
