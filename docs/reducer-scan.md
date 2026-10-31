# Reducer scan — 2026-10-29 (closed 2026-10-30)

Rule: `CLAUDE.md` "State logic".
Baseline: no test calls a reducer directly.
Key: **did** = commit/PR that built the reducer; **rwl** = 2-round review-loop PR(s) (structure + correctness);
`+#N` = leftover-fix PR (itself review-looped).
#7 (all of Tier 2 in one branch) closed unmerged: superseded by the per-item PRs below.

## Tier 1 — bugs found, do first
All 8 built in one unreviewed commit on main, 7f2604fcd ("8 bugs fixed"); each then got its own rwl PR.
| # | Where | State | Bug / smell | Action union | Did · rwl |
|---|---|---|---|---|---|
| 1 | `app/components/compose/MassMessageComposer.tsx` → `massMessageReducer.ts` | was 30 useState, reset() chained 26 setters, 2 mount-skip refs | validation written 3× and differing (now one `validateMass`; dead compose-into-rule mode gone); free template kept old price+lock; all-models reset the audience twice; closing unmounts the form | `field\|appendText\|toggleInclude\|…\|gifSendsFailed` + `validateMass`, `confirmPrompt`, `buildMassBody`, `gifOnlyForm` | 7f2604fcd · rwl #11 · +#51 (fan-out lock/retry, Mass split, delegates to `audienceReducer`) |
| 2 | `app/components/compose/PostComposer.tsx` | 13 useState | same free-template bug; all-models on doesn't clear price → "paid post needs an image" | same shape as #1 + shared `applyTemplate` / `previewIdsFor` in `lib/composeDraft.ts` | 7f2604fcd · rwl #13 · +#51 |
| 3 | `app/components/chat/Composer.tsx` | submit clears 10 setters, restores 10 on failure | `previewCountTouchedRef` written 6×, never read; `lockText` leaks from one PPV send to the next | `composerDraft` reducer + `composerView` | 7f2604fcd · rwl #9 · +#42 (refused schedule survives chat switch, `priceInput.ts`), +#51 (one `canBeFreePreview`) |
| 4 | `app/app/group/page.tsx` | `slots` written in 6 places + `slotsRef` | ack read right after setSlots (could lie → overflow tab); dup check `===` on mixed ids | `slotsReducer` `hydrate\|add\|replace\|remove\|dropHeldBy`, ack decided in reducer | 7f2604fcd · rwl #8 |
| 5 | `app/components/messages/CustomsTab.tsx` | openKey, ctx, brief, order, pulling, copied | race: row A's fetches land in row B's pane; copy-handoff copies wrong brief | `customsPaneReducer`, per-open `seq` | 7f2604fcd · rwl #10 · +#36 |
| 6 | `app/components/vault/VaultDuplicatesModal.tsx` | threshold, deselected, confirming, busy, progress, error, result | threshold change keeps `confirming` → "Yes, remove" acts on an unreviewed scan; OF has no undo | `duplicatesReducer` — confirm freezes ids, pure `hidePayload` | 7f2604fcd · rwl #12 · +#50, +#65 (partial-batch count) |
| 7 | `app/components/settings/NudgeOnlineTab.tsx` | 10 states, save() chains 4 | hydrate effect wipes unsaved edits on refetch | `nudgeOnlineReducer` (+ `account` action, per-account save) | 7f2604fcd · rwl #18 · +#39 |
| 8 | `app/app/admin/manage/page.tsx` | refresh() sets 5 in sequence | `loaded = keys(keyStatus)>0` conflates empty with failed | `manageReducer` `refreshStart\|refreshSettled\|…` + `seq` | 7f2604fcd · rwl #6 · +#48 (master gate, server `require_master`) |

## Tier 2 — tangled state, no known bug
Each PR below built the reducer and ran its own rwl in the same PR, unless a separate rwl is named.
- `automations/FunnelEditor.tsx` + `ReadyMadePanel.tsx` raw JSON → `lib/rawJsonReducer.ts`, `lib/funnelDraft.ts` (raw steps go through `toWire`) — #15 · +#38 (shared `parseJsonObjectOr`).
- `growth/ScriptsPage.tsx` → `scriptsPageState.ts` — #14 · +#38 (rename prompt as data, failed remove keeps tick).
- `vault/VaultManagePanel.tsx` → `vaultItemEditorReducer.ts` + `vaultBrowseReducer.ts` — #34 (port of #7 batch 2), slop #35. **No rwl** on these two reducers.
- `chat/VaultPicker.tsx` + `FanDrawer.tsx` `VideoScrubThumb` → `app/hooks/useHoverPreview.ts` — #34, slop #35 · rwl #37 · +#53 (`VaultTile` onto the same hook).
- `growth/AutoReplyPage.tsx` → `autoReplyForm.ts` + `automations/humanStyle.ts` `dropSaved` — #16 · +#46 (`{draft,sent}`, `useHumanStyle`/`<HumanStyleBlock>`, GetToKnowFans `getToKnowFansForm.ts`), +#65 (`usePageSave` edit/save).
- `vault/VaultImportCard.tsx` → `importPickReducer.ts` — #26.
- `employees/EmployeeAccess.tsx` → `employeeAccessState.ts` — #31 · +#48 (partial access save surfaced).
- `employees/EmployeeModals.tsx` → pure `buildEmployeeRequest` — #31.
- `setup/AddCreatorModal.tsx` → `addCreatorWizard.ts` (steps carry `accountId`) — #23.
- `settings/EmployeesTab.tsx` → `openModal` union — #31 · +#48 (`employeesModalReducer`: batch + resent-invite in the same union).
- `setup/PasteCurlCard.tsx` → `pasteCurl.ts` — #23.
- `growth/PriorityMass.tsx` + `automations/FunnelLaunchPanel.tsx` → `audience/audienceReducer.ts` — #19 · +#51 (Mass composer embeds it).
- `growth/LinksListFrame.tsx` `useFrameFilters` → `pagedFilters.ts` (now `app/hooks/`) — #22 · +#37 (AccountsTable), +#53 (`usePagedRows` clamp). Not done: Links/Promotion/Tracking still clamp in render (#53 O-a).
- `vault/VaultFolderRail.tsx` → `vaultFolderOrder.ts` — #25 · +#50 (reload shows new order), +#65 (sort label saved in `sortOfFolders`). Not done: label read back from OF (`SORT_READ_NOT_WIRED`).
- `compose/PremadeComposer.tsx` → `premadeRows.ts` — #25. Not done: partial fan-out has no retry/lock (owner call, #51).
- `chat/FanList.tsx` → `fanListPaging.ts` — #33 · +#50.
- `NotificationBell.tsx` → `notificationBellReducer.ts` — #33 · +#50.
- Small: `GifPicker`, `SmartListEditor` — #32 · +#38. `ClockRecordsModal` (clock-out ≤ clock-in refused), `ChatSurface` (drawer only), `MessagesPro` — #24. `CompetitorReports` `CreatorReportsCard` — **won't fix** (#24: each of 12 states owned by one control, none gates another).

## Non-React (pure transition fn + effects list, Python/TS)
All 10 built in #17 (`reducers-service`, no rwl in it); rwl per item:
1. `service/automations/send_followup.py` → `send_followup_decide.py` — #17 · rwl #44 (no nudge over a mid-tick reply); slop split #64.
2. `service/proxy_health.py` → `proxy_health_decide.py`; effects now `Watch|Unwatch|Announce|Failover|Log` — #17 · rwl #20 (matrix) · +#41 (ADR 0030 confirm rule), +#59 (watch claim in decide, no unwatched gap).
3. `app/lib/events.ts` → `eventBusReducer.ts` — #17 · rwl #27 · +#41.
4. `service/server.py` pump reconcile → `pump_reconcile.py` — #17 · rwl #28 · +#47 (restart backoff).
5. `app/contexts/UserContext.tsx` → `userSessionReducer.ts` — #17 · rwl #29.
6. `service/run_slot.py` → `run_slot_decide.py` — #17 · rwl #45.
7. `service/events.py` → `events_decide.py` — #17 · rwl #30 · +#47 (persist worker → `events_persist.py`); open #60 (routing/classifiers, `events_wire.py`).
8. `service/automation_executor.py` → `dispatch_plan.py` — #17 · rwl #45; open #61 (`job_queue.py` + `run_decide.py`).
9. `reply_mass_funnel.py` → `funnel_decide.py` — #17 · rwl #44.
10. `service/of_ws.py` → `of_ws_decide.py` — #17 · rwl #30. **Won't fix**: "reset backoff on a good frame" / "dead after N auth failures" — HEAD has neither; adding = behaviour change, owner call.

## Done 2026-10-30
1. Every Tier 1, Tier 2 and Non-React item but `CreatorReportsCard` is a pure reducer/decide with vitest/script tables, most with a slop check + fault (not: setup wizard, GifPicker, raw JSON — real-path run or unit only); 8 scan bugs fixed in 7f2604fcd; 44 merged PRs in #6–#65 ran the 2-round review loop and closed their leftovers.
2. Reviews found ~124 more behaviour bugs, all fixed (hand count of bullets listed as fixed bugs in those 44 PR bodies, 6 of them mobile gestures #21/#49; structure/test/polish items and unfixed open findings excluded; ±10 on judgment).
3. Biggest: paid mass/post re-sent to models that already succeeded (#11, #13, #51); customs Pull re-fired a paid brief (#10, #36); `/admin/users` leaked every agency's users to any owner (#48); proxy left unwatched after an error (#59); follow-up nudged a fan who just replied (#44).
4. Won't fix / not done: `CreatorReportsCard` (no gating), `of_ws` backoff reset (owner call), vault sort label read-back from OF (not wired), Premade partial fan-out retry (owner call), VaultManagePanel reducers never review-looped (#34).
5. Still open (W9, unmerged): #60 events routing, #61 job queue; chat `composerDraft` keeps its own free-preview copy (#51 follow-up).
