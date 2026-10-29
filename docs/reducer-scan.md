# Reducer scan — 2026-10-29

Rule: `CLAUDE.md` "State logic".
Baseline: no test calls a reducer directly.

## Tier 1 — bugs found, do first
| # | Where | State | Bug / smell | Action union |
|---|---|---|---|---|
| 1 | `app/components/compose/MassMessageComposer.tsx` 108-184, 339-534, 585-650 | 30 useState, reset() chains 26 setters, 2 mount-skip refs | validation written 3× (useInRule / mutationFn / disabled) and they differ; free template keeps old price+lock; all-models resets audience twice | `field{k,v}\|toggleInclude\|toggleExclude\|cycleSystem\|setAccount\|setAllModels\|seedMassExclude\|pickTemplate\|progress\|results\|reset` + pure `validateMass`, `buildMassBody` |
| 2 | `app/components/compose/PostComposer.tsx` 70-251 | 13 useState | same free-template bug; all-models on doesn't clear price → "paid post needs an image" | same shape as #1 + shared `applyTemplate` / `previewIdsFor` in lib (also used by `chat/Composer.tsx`) |
| 3 | `app/components/chat/Composer.tsx` 174-430, 537-690 | submit clears 10 setters, restores 10 on failure | `previewCountTouchedRef` written 6×, never read; `lockText` leaks from one PPV send to the next | `pickTemplate\|pickVault\|removeAttachment\|setPrice\|setPreviewCount\|schedule\|setGifs\|setTags\|clearPpv\|sent\|restore` + `buildSendArgs`, `canSend` |
| 4 | `app/app/group/page.tsx` 168-372 | `slots` written in 6 places + `slotsRef` | `accepted` read right after setSlots updater (ack may lie → overflow tab); dup check uses `===` on mixed number/string ids while remove uses `sameUserId` | `hydrate\|add\|replace\|remove\|dropHeldBy` + pure `addSlot(cur, sel)→{slots,accepted}` |
| 5 | `app/components/messages/CustomsTab.tsx` 246-353 | openKey, ctx, brief, order, pulling, copied | race: 3 fetches for row A land in row B's pane; copy-handoff copies wrong brief | `open{key}\|close\|ctx{key}\|brief{key}\|order{key}\|…` — reducer drops replies whose key ≠ open |
| 6 | `app/components/vault/VaultDuplicatesModal.tsx` 126-397 | threshold, deselected, confirming, busy, progress, error, result | threshold change keeps `confirming` on → "Yes, remove" acts on an unreviewed scan; OF has no undo | `threshold\|toggle\|toggleSet\|confirm\|cancel\|hideStart\|progress\|hideOk\|hideFail` — confirm freezes selectedIds |
| 7 | `app/components/settings/NudgeOnlineTab.tsx` 143-301 | 10 states, save() chains 4 | hydrate effect wipes unsaved edits on refetch | `hydrate\|field\|slots\|jsonDraft\|applyJson\|saveStart\|saveOk\|saveErr\|runMsg\|toggleModel\|seedModels` |
| 8 | `app/app/admin/manage/page.tsx` 60-127 | refresh() sets 5 in sequence | `loaded = keys(keyStatus)>0` conflates empty with failed | `refreshStart\|refreshDone\|refreshFailed\|liveOnly\|togglePane` |

## Tier 2 — tangled state, no known bug
- `app/components/automations/FunnelEditor.tsx` 188-499 — step editor + raw-JSON mode (raw steps cast unchecked, skip `toWire` validation). Same raw-mode code in `ReadyMadePanel.tsx` 500-553 → one shared `rawJsonReducer`.
- `app/components/growth/ScriptsPage.tsx` 578-1120 — 22 useState; "clear selection on navigate" hand-applied ~6×; deleteEntry/renameEntry jump selection.
- `app/components/vault/VaultManagePanel.tsx` — (a) `VaultItemEditor` 1224-1463: baseline `init` moves under the user's edits; (b) panel: `selected` not cleared on folder/type/query change; `loadMoreRef`/`canLoadRef` mirror state.
- `app/components/chat/VaultPicker.tsx` 586-815 + `FanDrawer.tsx` `VideoScrubThumb` 1896-2080 — 11 hover/scrub states, ref + useLayoutEffect hack, ETA formula copy-pasted → one `useHoverPreview`.
- `app/components/growth/AutoReplyPage.tsx` 122-352 — 14 fields; `draftFromConfig` / `buildPayload` round-trip table.
- `app/components/vault/VaultImportCard.tsx` 251-932 — picked/selected/details three maps keyed by File.
- `app/components/employees/EmployeeAccess.tsx` 45-127 — seeding in render with 4 setters; "edit clears savedAt" written 3×.
- `app/components/employees/EmployeeModals.tsx` 207-305 — `buildEmployeeRequest(form)→{method,path,body}` per signIn mode.
- `app/components/setup/AddCreatorModal.tsx` 102-294 — wizard with `accountId!`; make step carry its data.
- `app/components/settings/EmployeesTab.tsx` 221-290 — five modal states "at most one open", unenforced.
- `app/components/setup/PasteCurlCard.tsx` 69-222 — validate / buildBootstrapBody pure.
- `app/components/growth/PriorityMass.tsx` 65-235 + `automations/FunnelLaunchPanel.tsx` 49-289 — include/exclude mutual-exclusion written twice → shared `audienceReducer`.
- `app/components/growth/LinksListFrame.tsx` `useFrameFilters` 600-626 — `setX; setPage(1)` by hand, copied in TrackingLinksTab, PromotionTab, AutoFollowList.
- `app/components/vault/VaultFolderRail.tsx` 214-556 — `customizeOrder === (localOrder!==null)`; drag splice pure.
- `app/components/compose/PremadeComposer.tsx` 319-475 — row updaters already reducer cases; `rowToItem` closes over state.
- `app/components/chat/FanList.tsx` 697-864 — paging state reset by 3 effects with different deps.
- `app/components/NotificationBell.tsx` 343-425 — `openRef` copy, `wasOpenRef`, badge reset effect.
- Small: `GifPicker`, `SmartListEditor` (preview count stale after rule edit; `between` lacks value2 check), `CompetitorReports` `CreatorReportsCard`, `ClockRecordsModal` (no clock-out > clock-in check), `ChatSurface`, `MessagesPro`.

## Non-React (pure transition fn + effects list, Python/TS)
1. `service/automations/send_followup.py` 658-923 — per-fan phase machine interleaved with DB/LLM/send. `decide(entry, ev, thresholds)→[entry', Wait|Complete|Cooldown|Send]`.
2. `service/proxy_health.py` 131-327 — down/recheck/failover across 4 methods + threads. Events `CallOk|CallErr|ConfirmResult|RecheckDue|RecheckResult|Gone|FailedOver`, effects `StartWatcher|Announce|Failover|Sleep`.
3. `app/lib/events.ts` 81-370 — EventBus backoff/pause/stale/hot-rate. `SetScope|Pause|Resume|Opened|Errored|Frame|RetryFired|StaleTick|Flush`.
4. `service/server.py` 1047-1244 — pump reconcile: `reconcile(withSession, deactivated, parked, pumps)→[Start|Stop|Restart]`.
5. `app/contexts/UserContext.tsx` 178-381 — boot vs revalidate net-error rules implicit.
6. `service/run_slot.py` 137-285 — SlotPool priority/fairness against futures.
7. `service/events.py` 136-160, 598-684 — SSE batching/replay ring.
8. `service/automation_executor.py` 1155-1236, 2285-2340 — dispatch plan.
9. `service/automations/reply_mass_funnel.py` ~880-1090 — funnel status.
10. `service/of_ws.py` 109-216 — reconnect/backoff/session-dead (no direct tests).

## Suggested order
1. Shared `applyTemplate` + `previewIdsFor` in `app/lib`, then Mass / Post / Composer reducers (#1-3) — fixes the free-template bug in all three.
2. `group/page.tsx` (#4), `CustomsTab` race (#5), `VaultDuplicatesModal` (#6) — each a small, isolated win with a real bug.
3. NudgeOnline, admin/manage, then the shared `audienceReducer`, `rawJsonReducer`, `useFrameFilters`, `useHoverPreview`.
4. Service side: `send_followup` decide(), `proxy_health`, `events.ts`.
Each item: reducer in `.ts`/`.py` next to the code, vitest/pytest table, then prove on the real path (slop scenario for compose/send paths).
