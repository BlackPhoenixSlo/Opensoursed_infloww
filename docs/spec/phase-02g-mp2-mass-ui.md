# Phase 02g — Mass UI

**Objective.** A Fansly Creator holding a Live-check grant for a mass method gets a lit mass composer (and only she does, and only the controls her grants cover), and her scheduled broadcasts appear in the Scheduled tab beside OnlyFans rows with exact string ids and a cancel that reaches the broadcast cancel, while the Fansly Manager's Scheduled page keeps showing posts only. This is ticket 14 slice F (plan Phase 02g; 14 item 12; 11 item 1).

## Problem Statement
After Phase 02f the Relay can send, schedule and cancel one Fansly text broadcast to one include list, but only behind a Live-check grant and only through the Relay's mass route. The owner can't reach that path from the app. The app's Platform table says Fansly lacks `mass_message`, so every mass launcher, the composer's Creator chips, a forced launch and the New menu stay dark for every Fansly Creator, including the one the owner granted. A scheduled Fansly broadcast doesn't show in the Scheduled tab either. Fansly's `schedules()` returns posts only. Even if it returned broadcasts, `useScheduledMessages` turns each id into a JavaScript number, which rounds Fansly snowflake ids above 2^53 (`Number("900546198725955584") === Number("900546198725955585")`, measured). The cancel would then name a different row, or no row. Merging broadcasts into `schedules()` today would also put chat rows on the Fansly Manager's "Scheduled posts" page, whose Cancel calls the post cancel. So the owner's three Live checks for mass writes (schedule then cancel, schedule then let it fire, send once) can't be run from the UI the way a chatter would use it.

## Solution
The Relay reports, per Creator on the owner's account list, which Live-check methods are granted to her: a method appears when 02a's `live_check_methods(aid)` lists it and `is_live_check_name(platform, method)` holds. The app keeps its static Platform table (ADR-0054) and lights a lacked Capability for that Creator only when a granted method maps to it. Each control is shown only when its own method is granted (ADR-0056): Broadcast needs `send_mass_message`, the schedule field needs `schedule_mass_message`, Cancel on a broadcast row needs `cancel_scheduled_mass_message`. Launch modes no Fansly Branch can send (online fans, Priority, All models) stay hidden. Every other Fansly Creator and every chatter view stay as they are.

Fansly's `schedules()` adds the Creator's scheduled broadcasts (Phase 02e's `scheduled_messages` read) as `type: "chat"` rows with string ids, sorted with the posts by date. A failed broadcast read keeps the posts and marks the response `incomplete`, so the Fansly Manager's posts page (already filtered to posts by the mirror thread) never breaks, while the Scheduled tab shows the account's load error. `useScheduledMessages` keeps ids as strings end to end (the Scheduled tab, `ScheduledTab` at `/growth/smart-messages?tab=scheduled`, which the plan calls Settings), so its Cancel sends that exact id with the row's type to the Phase 02f typed cancel, and a refused cancel shows the Relay's reason. OnlyFans rows, OnlyFans cancels and every ungranted Creator behave exactly as before.

## User Stories
1. As the owner, I want a Fansly Creator I granted `send_mass_message` to show as a mass sender in the composer with Broadcast enabled, so that I can run the send-once Live check from the app.
2. As the owner, I want the composer's schedule field shown for a Fansly Creator only when I granted her `schedule_mass_message`, so that I can run the schedule Live checks and never see a schedule control the Relay will refuse.
3. As the owner, I want every Fansly Creator without a grant to stay dark in the composer, the chips, a forced launch and the New menu, so that no ungranted Creator can be picked.
4. As the owner, I want a grant to light only the account it names, never every Creator on that Platform, so that one Live check can't widen to my other Fansly Creators.
5. As the owner, I want the Relay's `/admin/accounts` row to list the Live-check methods granted to that Creator, so that the app never guesses from the Platform alone.
6. As the owner, I want a Creator with no grant to have no such field on her row, so that today's response shape is unchanged for her.
7. As the owner, I want an OnlyFans Creator's row and composer unchanged whatever `PLATFORM_LIVE_CHECK` holds, so that the OnlyFans path can't regress.
8. As the owner, I want a grant entry for an account I don't own never reported on my list, so that the field can't leak another Agency's grants.
9. As a chatter, I want my roster (`/chatter/me/accounts`) to carry no grant field, so that a Live check stays owner-only and a chatter's composer stays dark for Fansly.
10. As the owner, I want All models hidden on a Fansly composer, so that I can't start a fan-out that has no custom-list picker and so can't meet the one-include-list Branch.
11. As the owner, I want a forced or saved launch of a Fansly Creator to need her own grant (`canAccount`), so that a retry or deep link can't target an ungranted Creator.
12. As the owner, I want the chat list's New menu to offer "Mass message" when a Creator in scope holds a mass grant, and "Message online fans" only when every in-scope Creator can mass message on her Platform, so that I never launch a mode the Relay refuses.
13. As the owner, I want the growth Create-message pop-up to show the OF-standard mass card for a granted Fansly Creator, and Priority and online fans only where the Platform supports mass messages, so that every launcher agrees.
14. As the owner, I want the grant check to go through one literal app map (granted Live-check method → the Capability it lights), so that no component branches on Fansly.
15. As a developer, I want the map's three method names pinned in `platform.test`, so that a renamed Relay method fails a test without generic drift machinery.
16. As the owner, I want the Fansly Creator's lit composer to show the Relay's `platform_lacks:send_mass_message:<branch>` reason when I add something the one eligible Branch refuses (a price, media, an exclude list), so that a refusal shows up instead of failing silently.
17. As the owner, I want my scheduled Fansly broadcast listed in the Scheduled tab with its time and text, its Audience shown as "?" because the read carries no list, so that I can see it before it fires without the UI claiming an audience it didn't read.
18. As the owner, I want a broadcast id above 2^53 kept digit for digit from the Shim to the cancel request, so that Cancel names the row I clicked.
19. As the owner, I want Cancel on a Fansly broadcast row to send that row's type (`chat`) with its string id, so that the Relay dispatches the broadcast cancel, not the post cancel.
20. As the owner, I want Cancel on an OnlyFans row to make exactly the request it makes today, apart from the `type` Phase 02f adds, so that OnlyFans cancel is unchanged.
21. As the owner, I want Fansly posts and broadcasts in one `schedules()` response, sorted by scheduled time, so that both Scheduled screens read one source.
22. As the owner, I want the Fansly Manager's Scheduled posts page to keep listing only posts, and to keep listing them when the broadcast read fails, so that its "Cancel post" never fires at a broadcast and a broadcast error never hides posts.
23. As the owner, I want a cancelled (status 3) or unknown-status broadcast left out of the list, as Phase 02e's read does, so that a cancelled send isn't offered again.
24. As the owner, I want a failed or malformed broadcast read to show the Scheduled tab's load error for that account (posts kept, `incomplete: true`), so that a partial list never looks complete.
25. As the owner, I want `hasMore` on the merged response to be true when the broadcast read says more exist, so that the list never claims to be complete when it isn't.
26. As the owner, I want the per-fan Scheduled chip in a chat to keep working with string ids, so that an OnlyFans single-fan scheduled send still shows and cancels.
27. As the owner, I want a Fansly broadcast (list-addressed, no `userIds`) left out of the per-fan Scheduled chip, so that the chip counts only sends to that one fan.
28. As the owner, I want the Cancel button's busy state matched on account and id, so that two Creators' rows with the same id don't both spin.
29. As the owner, I want desktop and phone screenshots of the lit composer and of the Scheduled tab holding a Fansly broadcast row, plus the `/admin/accounts` response and the recorded DELETE with its query, so that the Phase is proven on the real path.
30. As the owner, I want the three mass-write Live checks to run after this PR, on a local Relay, so that the Relay sha they record is the one with the UI.
31. As an engineer, I want the row mapping from `/schedules` to Scheduled rows to be one pure function with a vitest table, so that the id and type rules are tested without rendering.
32. As the owner, I want the parity doc's Scheduled and mass-composer rows updated in this PR, so that the doc matches the code.
33. As the mirror thread, I want 02g to wait for our posts-only filter on the Fansly Manager's Scheduled page and to message us before touching the shared Platform table, the Shim and the Nova seed, so that our page never shows broadcast rows.
34. As the owner, I want Cancel hidden on a Fansly broadcast row unless that Creator holds `cancel_scheduled_mass_message`, so that a row I can't cancel offers no Cancel.
35. As the owner, I want a refused cancel (for example `platform_lacks:cancel_scheduled_mass_message:audience_unknown`) shown in the Scheduled tab with the Relay's reason, so that a refusal never looks like nothing happened.
36. As the owner, I want a broadcast whose list the Relay can't resolve to refuse its cancel with zero writes, never cancel by id alone, so that the audience gate holds for cancel too.
37. As the owner, I want the standing `MASSdmEXCLUDE` list not pre-selected on a Fansly composer, so that the Relay doesn't read a policy default as a list I chose to exclude.

## Implementation Decisions
- **Owns.**
  - Relay: `accounts_admin_api` (`GET /admin/accounts` row field over 02a's `live_check_methods`).
  - Shim: `fansly_shim` `FanslyShimClient.schedules()` (merges in broadcasts).
  - App:
    - `lib/platform` (`LIVE_CHECK_LIGHTS`, `canAccount`, `liveCheck`);
    - `lib/relayTypes` (`AccountMeta.live_check`, `OFScheduledMessage.id: string`);
    - `hooks/useCan`;
    - `hooks/useScheduledMessages` (pure row mapping split into a `scheduledRows` module beside it, plus string-id cancel);
    - `components/compose/massSenders`;
    - `components/compose/massMessageReducer` (`validateMass` context only; no new state);
    - `components/compose/MassMessageComposer` (call sites: All models, schedule field, Broadcast, exclude seed);
    - `components/chat/FanListHeader` (New menu);
    - `components/growth/CreateMessagePopUp` (cards through `useCan`);
    - `components/settings/ScheduledTab` (per-row Cancel visibility, cancel error);
    - `components/chat/ScheduledForChat`.
  - Proof tooling: `scripts/demo-shots/fansly_nova.py` (Nova answers `/api/of/v2/schedules` through its Shim, raw payload gains one scheduled post and one scheduled broadcast; an M1 point); `scripts/verify-app/drive.py` (`of-writes` records gain `url` with the query, as `reads` already do, `drive.py:407`).
  - Docs: `fansly/FANSLY_PARITY_STATUS` rows.
- **Interfaces.**
  - Relay row field = `sorted(m for m in side_effect_gate.live_check_methods(aid) if side_effect_gate.is_live_check_name(platform, m))` for a Platform with a Backend (02a's grant API; 02g adds no grant reader).
    - A Platform with no Backend (OnlyFans) yields empty whatever the env holds; the var unset yields empty. 02a reads the env on every call.
    - It reports grants only; it authorizes nothing (the target and audience checks stay at the caller, 02a/02f).
  - `GET /admin/accounts`: each Creator row in `accounts` may carry `live_check: list[str]` (granted method names).
    - Present only when non-empty (precedent: `freshness`, `proxy_bad_reason`, `accounts_admin_api.py:232-235`).
    - Never on `watchers`. Never on `/chatter/me/accounts` (`FlatAccountDTO` unchanged; owner-only per 00 item 6).
  - App `LIVE_CHECK_LIGHTS: Readonly<Record<string, Capability | null>> = { send_mass_message: "mass_message", schedule_mass_message: "mass_message", cancel_scheduled_mass_message: null }`: a literal three-entry map; `null` lights only its own control (Cancel). Granted names not in it (lanes) light nothing.
  - App `liveCheck(a: Pick<AccountMeta, "live_check">, method: string): boolean`.
  - App `canAccount(a: Pick<AccountMeta, "platform" | "live_check">, cap): boolean` = `can(accountPlatform(a), cap) || Object.entries(LIVE_CHECK_LIGHTS).some(([m, c]) => c === cap && liveCheck(a, m))`.
    - `can(platform, cap)` and `PLATFORMS` stay as they are (Fansly still lacks `mass_message`).
    - `useCan` and `useCanOrFallback` use `canAccount` when the Creator's row is found, and fall back to `can(platform)` while the roster loads (D7 unchanged).
  - `massSenders(accounts, platform)` keeps accounts of `platform` that pass `canAccount(a, "mass_message")`.
  - `massSendFrom`'s forced-launch check takes the launch Creator's row (its `canAccount`), not her Platform alone.
  - **Per-control rule** (composer, only when `!can(platform, "mass_message")`, i.e. lit by a Live check):
    - All models hidden.
    - Schedule field shown only with `liveCheck(a, "schedule_mass_message")`.
    - `validateMass` context gains `{ sendNow: boolean; schedule: boolean }` (both true off the Live-check path): no schedule set and `!sendNow` → invalid ("Schedule it: this Creator's Live check covers scheduling only"); schedule set and `!schedule` can't happen (field hidden) and is invalid if it does.
    - The `seedExclude` call passes `listId: null`.
  - Launchers:
    - New menu: "Mass message" when any in-scope Creator passes `canAccount(a, "mass_message")`; "Message online fans" only when every in-scope Platform passes `can(p, "mass_message")`.
    - CreateMessagePopUp: OF-standard card on `useCan`; Priority and online cards on `can(platform, "mass_message")`.
  - `scheduledRows(resp, accountId): { rows: OFScheduledMessage[]; incomplete: boolean }` is pure.
    - It keeps `type === "chat"` rows whose `entity.id` is a non-empty string of digits or a finite number, and turns the id into a string without going through `Number`.
    - The other fields map as today. `incomplete` = `resp.incomplete === true`.
  - `useScheduledMessages` throws for an account whose `scheduledRows` is `incomplete` (the tab's existing load error and Retry, `ScheduledTab.tsx:64-69`).
  - `OFScheduledMessage.id` becomes `string`.
  - `useCancelScheduled` (02f gives it `{ id, accountId, type }`) takes `id: string`, URL-encodes it, and exposes its error; the tab renders a `role="alert"` with `refusalText(error)` (precedent `useVaultSweep.ts:173`).
  - The Scheduled tab shows Cancel on a Fansly `chat` row only when that Creator passes `liveCheck(a, "cancel_scheduled_mass_message")`; OnlyFans rows and Fansly post rows keep today's Cancel. Its busy check matches `accountId` and `id`.
  - `FanslyShimClient.schedules(**kw)` returns `{"list": [...posts, ...broadcasts], "hasMore": bool}` and, on a failed or malformed broadcast read, `{"list": [...posts], "hasMore": bool, "incomplete": true}`.
    - Each broadcast row: `{"id": str, "type": "chat", "publishDateTime": iso, "entity": {"id": str, "text": str, "userIds": [], "userLists": [], "groups": [], "price": 0, "mediaCount": 0, "lockedText": false}}`.
    - The entity values come from 02e's `scheduled_messages` rows (`{id, text, scheduledDate}`; status 1 only). 02e emits no list (Unseen), so `userLists` and `groups` stay empty and the Audience cell reads "?" (`ScheduledTab.tsx:131-137`).
    - Post rows are unchanged. `hasMore` = the broadcast read's `hasMore` (posts are one full page today).
    - The broadcast read is called with `limit` from the caller (default 50) and `offset=0`.
    - ASSUMPTION: a broadcast read error keeps posts and sets `incomplete` (rung 4, additive key; posts on the mirror's page survive). Falls if the mirror wants the Manager page to show the incomplete state; then it reads the same key.
- **Schema.** None. No table, no migration (11 item 5 ASSUMPTION holds).
- **Contracts.**
  - The `/admin/accounts` field `live_check` is new and additive.
  - The Fansly `/api/of/v2/schedules` response gains `type: "chat"` rows and an optional `incomplete`.
  - The cancel request, its audience resolution (`scheduled_broadcast_audience`) and its `:audience_unknown` fail-closed refusal are Phase 02f's, unchanged here. 02g never cancels by id without the Relay's audience check.
  - The composer's POST and the Relay's grant, Branch and Contact-guard checks are Phase 02f's, unchanged here.
  - The app never decides authorization. `live_check` only decides whether a control is shown (ADR-0056); the Relay's `side_effect_gate.live_check` at the caller still refuses an ungranted method or audience (ADR-0070).
- **Composer controls.**
  - Inside a lit Fansly composer, price, media, exclude lists, funnel, locked text, tags and GIFs stay visible. The Relay refuses each with its Branch reason, and the composer shows it through the existing fan-out result error.
  - ASSUMPTION (rung 5; the composer is an owner Live-check tool until the Lift PR; plan item 12 names only the lighting). Falls if the owner wants them hidden; then each becomes a Capability Fansly lacks, with Drift rows.
- **Exclude seed.**
  - On a Live-check-lit Fansly composer the standing exclude list isn't seeded (`seedExclude` with `listId: null`), so the body carries no `excluded_user_lists` the owner didn't choose (14 item 3 refuses "explicit user-chosen exclude lists").
  - ASSUMPTION: the standing exclusion on Fansly is the Relay's job (02f's Contact-guard intersection and the grant's one-fan list), not the composer's (rung 4). Falls if 02f's `excl_set` omits `MASSdmEXCLUDE` members; then 02f adds them to the intersection, not 02g.
- **File rules (11 item 1).**
  - This PR is the only P2 PR open that edits `fansly_shim.py`. It doesn't touch `platforms.py` or `server.py`.
  - Verdict rows don't change: no new refusal reason, so the Lift table and KIND_VERDICTS are unchanged. The parity rows for Scheduled and the mass composer move here.
- **Mirror points (11 item 5).**
  - M2 first: send the request for the posts-only `FanslyScheduled` filter (rows with `type === "post"` only, and posts kept when `incomplete` is set), then wait for it to merge and record its sha as `MIRROR_FILTER_SHA` (`FanslyScheduled.tsx:38` reads `list` whole today).
  - M1 before the Shim edit, `app/lib/platform.ts` and the Nova fixture edit: read the mirror log.
  - M3 after merge: send the merge sha.
- **Reducer rule.** No new joint state: `canAccount`, `liveCheck` and `scheduledRows` are pure, `validateMass` gains context only, so no reducer is added.

## Testing Decisions
- **Relay route seam:** `service/tests/test_live_check_capabilities` (new, plain script, house `_harness` style).
  - The row field as a table over the env value (02a's parser): unset; this account plus a marked method plus `fan=`; a bare entry (inert); another account; an unmarked method; a malformed entry; an OnlyFans account with a mass grant (empty).
  - `GET /admin/accounts` through the `TestClient`, as in `test_chatter_roster_platform`:
    - a granted Fansly Creator carries `live_check: ["schedule_mass_message", "send_mass_message"]`;
    - an ungranted Fansly Creator and every OnlyFans Creator have no field (OnlyFans control);
    - a watcher has none; `/chatter/me/accounts` has none.
- **Merged schedules and typed cancel seam:** extend `service/tests/test_fansly_cancel_scheduled_route`, through the `TestClient` (HTTP), not handler calls. It drives the real Shim over 02a's Stateful fake, which holds one scheduled post, two scheduled broadcasts with adjacent ids above 2^53 (one whose `groupId` maps through `groups[]` to the granted one-fan list, one whose `groupId` maps to none), one status-3 broadcast and one unknown-status broadcast.
  - `GET /api/of/v2/schedules` returns posts and broadcasts sorted by time, with exact string ids and `type`. Status 3 and the unknown status are dropped.
  - A malformed broadcast page returns the post with `incomplete: true` and no chat row.
  - With all three grants: `DELETE` with each row's own `type` and `id` reaches the fake as `POST /post/scheduled/<id>/cancel` for the post and `POST /message/broadcast/scheduled/<id>/cancel` for the mapped broadcast, digit for digit, and the read-back no longer lists the row.
  - Repeat: a second `DELETE` of the cancelled broadcast answers 501 `:audience_unknown` with zero writes.
  - Refusals, zero writes each (membership GETs allowed): the unmapped broadcast → 501 `platform_lacks:cancel_scheduled_mass_message:audience_unknown`; no cancel grant → 501 `platform_lacks:cancel_scheduled_mass_message`.
  - OnlyFans control: the OF fake's `/schedules` and cancel requests are byte-identical to today's.
  - Prior art: this file's snowflake case; `fansly/test_har_replay` for comparing body values.
- **Shim shape:** one case in `fansly/test_shim_shapes` for the merged row shape (all ids are `str`, `type` ∈ {post, chat}, `hasMore` is bool, `incomplete` absent or true), over the 02e `_source` fixture extended with a post row.
- **App (vitest):**
  - `scheduledRows` (new table): mixed post/chat input, ids `"900546198725955584"` and `"900546198725955585"` that stay distinct, numeric OnlyFans ids turned into strings, a non-digit id dropped, a missing entity dropped, `incomplete` passed through.
  - `platform.test` adds `canAccount` and `liveCheck`: a grant lights a lacked Capability, never touches others, a cancel-only grant lights no composer, OnlyFans unchanged; `LIVE_CHECK_LIGHTS` equals the three-entry literal.
  - `massSenders.test` adds a granted Fansly Creator, an ungranted one and a forced launch of each.
  - `useCan.test` adds an owner row with `live_check`, and a chatter row that stays dark.
  - `massMessageReducer.test` adds the `validateMass` table: send-only, schedule-only, both, neither.
  - Screen-level, rendered with the real hooks and only the `relay` transport mocked (not the hooks):
    - `ScheduledTab.test`: a mixed OnlyFans + Fansly response; the Fansly broadcast row with the cancel grant → Cancel → `relay.delete` called with `/api/of/v2/messages/queue/900546198725955585?type=chat` and the Fansly `accountId`; without the grant no Cancel on that row; a 501 refusal renders the alert with its reason; `incomplete` renders the load error; busy matches account and id.
    - `MassMessageComposer.test`: a granted Fansly roster shows Nova's chip, hides All models, hides the schedule field without `schedule_mass_message`, sends no `excluded_user_lists`; an ungranted roster shows no Fansly chip.
    - `FanList.test` (holds the New menu cases today) and a new `CreateMessagePopUp.test`: granted Fansly scope offers Mass message only (no online, no Priority); OnlyFans scope unchanged.
  - Prior art: `massSenders.test.ts`, `ScheduledTab.test.tsx`, `useCan.test.tsx`.
- **Real path (verify-app `--fansly`):**
  - Browser `/api/*` traffic is answered by the fixture router (`capture.py:103-111`, `fansly_nova.py:145-170`) and non-GET `/api/*` never reaches the Relay; `/admin/accounts` does reach the Relay. So verify-app proves the lit UI, the Nova schedules row and the recorded DELETE; the provider cancel is proven by the TestClient seam above.
  - Stack: `up --fansly` with `PLATFORM_LIVE_CHECK=<nova>:send_mass_message:fan=<fan>,<nova>:schedule_mass_message:fan=<fan>,<nova>:cancel_scheduled_mass_message:fan=<fan>` (02a grammar; bare entries are inert).
  - Screenshots, desktop and phone, trigger and settled: the composer with Nova selectable; the Scheduled tab with her broadcast row; the cancel confirm and its settled state; the Fansly Manager Scheduled page listing the post only.
  - Side effects: `drive.py api /admin/accounts` shows `live_check` on Nova only; `drive.py of-writes` records the `DELETE` whose `url` carries the exact string id and `type=chat`.
  - ASSUMPTION: the Relay started by `drive.py up` inherits the caller's env (`drive.py:126` copies `os.environ`). Falls if it doesn't; then `up` gains a pass-through flag.

## Acceptance
```sh
set -e
git fetch -q origin main
git merge --no-edit origin/main
: "${MIRROR_FILTER_SHA:?set from the mirror's M2 reply}"
git merge-base --is-ancestor "$MIRROR_FILTER_SHA" HEAD   # mirror posts-only filter merged (M2)
venv/bin/python service/tests/test_live_check_capabilities.py
venv/bin/python service/tests/test_fansly_cancel_scheduled_route.py
venv/bin/python service/tests/test_platform_table_drift.py
venv/bin/python service/tests/test_chatter_roster_platform.py
venv/bin/python fansly/test_shim_shapes.py
venv/bin/python fansly/test_lift_table.py
(cd app && pnpm exec vitest run hooks/scheduledRows.test.ts lib/platform.test.ts hooks/useCan.test.tsx components/compose/massSenders.test.ts components/compose/massMessageReducer.test.ts components/compose/MassMessageComposer.test.tsx components/settings/ScheduledTab.test.tsx components/chat/FanList.test.tsx components/growth/CreateMessagePopUp.test.tsx)
python3 scripts/comment_budget.py --check
test "$(PYTHONPATH=. nice -n 10 venv/bin/alembic -c service/db/migrations/alembic.ini heads | grep -c head)" = 1
nice -n 10 scripts/run-tests.sh
(cd app && nice -n 10 pnpm test:run)
NOVA_ID=900539700124344320   # scripts/demo-shots/fansly_nova.py ACCOUNT
NOVA_FAN=900539700124344321  # scripts/demo-shots/fansly_nova.py FAN
nice -n 10 env PLATFORM_LIVE_CHECK="$NOVA_ID:send_mass_message:fan=$NOVA_FAN,$NOVA_ID:schedule_mass_message:fan=$NOVA_FAN,$NOVA_ID:cancel_scheduled_mass_message:fan=$NOVA_FAN" python3 scripts/verify-app/drive.py up --fansly
python3 scripts/verify-app/drive.py api /admin/accounts | grep -q '"live_check"'
python3 scripts/verify-app/drive.py login --as owner
python3 scripts/verify-app/drive.py goto '/growth/smart-messages?tab=scheduled'
python3 scripts/verify-app/drive.py screenshot --path scheduled-fansly-row.png
python3 scripts/verify-app/drive.py click --role button --name "Cancel"
python3 scripts/verify-app/drive.py click --role button --name "Cancel send"
python3 scripts/verify-app/drive.py screenshot --path scheduled-cancel-settled.png
python3 scripts/verify-app/drive.py of-writes | grep -q 'messages/queue/[0-9]\{18,\}?type=chat'
python3 scripts/verify-app/drive.py down
# manual: verify-app screenshots (composer lit for Nova, the Scheduled tab with her broadcast row, cancel confirm + settled, Fansly Manager Scheduled posts only), desktop + phone, linked in the PR.
# manual: owner, after merge, on a local Relay with PLATFORM_LIVE_CHECK=<owner aid>:send_mass_message:fan=<Proof fan id>,<owner aid>:schedule_mass_message:fan=<Proof fan id>,<owner aid>:cancel_scheduled_mass_message:fan=<Proof fan id> on a list holding only the Proof fan: schedule +1 h and cancel from the Scheduled tab (fan sees nothing); schedule +10 min and let fire (one message); send once (one message, run ok, queue_id null).
```

## Depends on
- **Phase 02a.** It provides:
  - the grant API: `live_check_methods`, `is_live_check_name`, `live_check`, the `fan=` grammar of `PLATFORM_LIVE_CHECK`;
  - the `platform_live_check` Shim marker;
  - the Stateful fake;
  - the KIND_VERDICTS harness and Lift-table drift test, which must stay green.
- **Phase 02e.** It provides:
  - `FanslyShimClient.scheduled_messages` (status 1, `{id, text, scheduledDate}`, string ids, local slicing, `hasMore`);
  - the `mass_history` Capability row in the Drift map;
  - Nova's broadcast GETs.
- **Phase 02f.** It provides:
  - the grant-checked `send_mass_message` and `schedule_mass_message` Relay paths, both marked `platform_live_check`;
  - the Branch and Contact-guard refusals;
  - `cancel_scheduled_mass_message` (marked), `scheduled_broadcast_audience`, the `:audience_unknown` fail-closed refusal and `DELETE /messages/queue/{id}?type=` dispatch;
  - the Scheduled tab cancel `type` param (`useCancelScheduled` `{id, accountId, type}`).
  - ASSUMPTION: 02f lands the `type` param with numeric ids and 02g only turns them into strings. Falls if 02f left the `type` param out; then 02g adds it here.
- **Mirror thread (`feat/fansly-mirror`).** It provides the posts-only filter on `FanslyScheduled.tsx`. That filter hasn't been planned yet: `git grep` on `feat/fansly-mirror` finds no such ticket. So 02g's first act is M2, then it waits.
- Linear PR order (D8): 02a-1 → 02a-2 → 02b → 02c → 02d → 02e → 02f → 02h → **02g**. 02g is last and mirror-gated; 02h and its deploy do not wait for it (D5).

## Out of Scope
- Media, price, preview, exclude-list, recipient, online-only and funnel broadcasts. They are refused at the Relay by 02f (14 item 3) and need a capture first.
- `edit_queued_message`. It stays Blocked (14 item 13), so the Scheduled tab gets no Edit on Fansly rows.
- Unsending a fired Fansly broadcast. `unsend_mass_message` stays Blocked (02e), and the Mass tab keeps Unsend disabled on Fansly.
- A chatter-side grant. The Live check is owner-only (00 item 6).
- Showing a broadcast's list in the Audience cell. 02e's read carries none; a per-row `scheduled_broadcast_audience` read isn't added for a label.
- Delivery-time membership of a scheduled broadcast (a fan added to the list after scheduling). 14 item 4 holds parity with OnlyFans; a snapshot list is 02f's call if it falls.
- Removing `mass_message` from Fansly's lacks. That is the Lift PR after the owner's Live checks (ADR-0070, PR 2), not this one.
- A UI toggle for grants. The grant is an env var (ADR-0070).
- Any Fansly Manager page change. The mirror thread owns it.
- Deploy from this PR. 02g ships in the first deploy after it merges; Phase 2's deploy after 02h does not wait for it (D5).
- Generic Live-check drift machinery (`LIVE_CHECK_LIGHTS` against `CAP_METHODS` in the Drift test). Cut (D6): three literal entries pinned in `platform.test`.
- Cell mode. 02f refuses it, and agency-scale-out owns it.

## Further Notes
- Ship:
  - branch `feat/mp2-02g-mass-ui`;
  - one PR;
  - merge when green after the merge-train check (`git worktree list` for `merge-*`, `gh pr list --state merged --limit 10`, wait 15 min after any merge);
  - no deploy from this PR.
- The relay call-site ledger needs no new line: the scheduled calls pass `accountId`, so the Front door routes them.
- The Live-check order on the owner's stack is: grant, schedule +1 h, cancel, then schedule +10 min, then send once. After the passes, 02h or a Lift PR records `Live check <date>, Relay <sha>` per method.
- ASSUMPTION: Fansly's scheduled-post read stays a single full page (`hasMore: false` today, `fansly_shim.py:1466-1481`). Falls if posts page; then the merged `hasMore` ORs both reads.

## Review
Reviewer: codex (blind + draft), 2026-11-27
- P1-1 Alternatives (per-Creator send/schedule/cancel availability; no global flip; `/messages/queue` fallback if the mirror slips) — **partial**: per-method availability accepted (Solution, per-control rule, stories 1-2, 34); global flip already out; the `/messages/queue` fallback rejected, 14 item 12 binds the `schedules()` merge after the mirror filter.
- P1-2 Missing requirements (rosters, launchers, picker, submit; send grant exposing online/Priority/schedule/cancel; MASSDMEXCLUDE seed; refused-cancel display) — **partial**: launchers, picker, submit, per-control hiding, no Fansly seed and the cancel alert accepted (stories 10-13, 34-35, 37); chatter roster stays without the field, 00 item 6 makes the Live check owner-only.
- P1-3 Test seam (drive composer + both Scheduled screens through Relay HTTP into a stateful fake) — **partial**: TestClient HTTP route seam and screen-level vitest with only `relay` mocked accepted; a browser → Relay → fake path doesn't exist (verify-app fixture-answers `/api/*`, `capture.py:103-111`, `fansly_nova.py:145-170`), so the provider call stays on the TestClient seam.
- P1-4a Falsifier: `Number` collapses adjacent snowflakes — **accept**: measured, string ids end to end (Problem, `scheduledRows` table).
- P1-4b Falsifier: unlinked `groupId` must refuse cancel — **accept**: same as P2-2.
- P1-4c Falsifier: list membership changed after scheduling widens delivery — **reject** for 02g: 14 item 4 ASSUMPTION binds (membership at delivery, parity) and the lane is 02f's; noted in Out of Scope.
- P2-1 Acceptance grants lack targets, no cancel grant, `of-writes` drops the query — **accept**: measured (02a contract line 67, `drive.py:397-406`); grants carry `:<fan>`, cancel grant added, `of-writes` records `url`, grep matches id + `type=chat`.
- P2-2 Cancel-by-id fallback breaks the audience gate — **accept**: 02f E fails closed `:audience_unknown` and 02e emits only `{id, text, scheduledDate}`; fallback removed, `userLists` empty, refusal + zero writes tested, 02f `scheduled_broadcast_audience` named in Depends on.
- P2-3 One grant exposes unsupported controls (schedule, online fans, Priority) — **accept**: any-method lighting dropped; per-method controls and launcher modes (ADR-0056, `FanListHeader.tsx:24-27`, `CreateMessagePopUp.tsx:149-154`).
- P2-4 Capability helper has no runtime input (Relay `lacks` are policy flags) — **accept**: verified `platforms.py:12-37`; Relay reports granted marked methods, the app maps them through `LIVE_CHECK_LIGHTS`; `CAPABILITY_METHODS` move dropped.
- P2-5 All models / retry unusable; MASSDMEXCLUDE seed serialized as explicit — **partial**: All models hidden on Fansly (`AudiencePanel.tsx:44` hides lists under All models), no seed on Fansly; the standing exclusion is left to 02f's Contact-guard intersection (ASSUMPTION), since 02g can't edit the send path.
- P2-6 Seams pass with broken UI wiring — **partial**: as P1-3.
- P2-7 Raising out of `schedules()` breaks the Manager's posts; M2 grep is a literal — **accept**: posts kept with `incomplete: true` (`FanslyScheduled.tsx:23-46` errors the whole page today); M2 check is the mirror sha's ancestry, plus a Manager screenshot.
- P2-8 Acceptance omits merge gates — **partial**: main merge, one alembic head and explicit `pnpm test:run` added (11 item 3; `run-tests.sh:52-57` skips vitest when not installed); repeat added (second cancel refuses, zero writes); a `run_once` executor proof doesn't apply, 02g adds no kind or runner path.

Plan review (six hats + coordinator D1–D8), 2026-11-27:
- White [02a,02b,02c,02f,02g], four grant shapes — **accept** (D1). `_live_check_methods` deleted; the row field reads 02a's `live_check_methods` filtered by `is_live_check_name`; grants use `fan=`. The import-cycle reason for a private reader is 02a's to solve (the gate already classifies Shim names).
- Black [02g,02h], Phase 2 deploy hangs on the mirror — **accept** (D5). 02g is last in the order, 02h no longer depends on it, 02g ships in the next deploy after it merges; Out of Scope and Depends on rewritten.
- Yellow [02e,02g], string snowflake ids — **accept**. Kept: `OFScheduledMessage.id: string`, never through `Number`.
- Green [02f,02g,02h,plan], decouple deploy — **accept** (D5).
- Blue [02b,02c,02d,02f,02g], cite 02a's names — **accept**.
- D6 `LIVE_CHECK_LIGHTS` — **accept**. Literal three-entry method → Capability map; the Drift-test assertion and its Owns line removed; stories 14–15 rewritten; pinned in `platform.test`.
- D8 linear order — **accept**.
Counts: accept 7 · partial 0 · reject 0 · needs-human 0.
