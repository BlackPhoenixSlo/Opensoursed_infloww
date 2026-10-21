# Plan review — OF Manager connectors

Plan: `docs/plans/of-manager-connectors.md` (a human document, not edited by this run). Specs: `docs/spec/of-manager-connectors/phase-00..06-*.md`. Six-hats source: `.scratch/of-manager-connectors/SIX-HATS.md`. Date: 2026-10-12.

## Workstreams

| Wave | Phase | Spec | Depends on |
|---|---|---|---|
| 1 | 0 — New post: text, schedule, Co-tags | `phase-00-new-post-text-schedule-tags.md` | None |
| 1 | 5 — OF settings writes with Known bodies | `phase-05-settings-writes.md` | None (uses Phase 0's exports if present) |
| 2 | 1 — Media from the vault | `phase-01-vault-media.md` | 0 |
| 2 | 3 — Add to story | `phase-03-add-to-story.md` | 0 |
| 2 | 4 — Real data pages | `phase-04-real-data-pages.md` | 0 |
| 3 | 2 — Upload from disk | `phase-02-upload-from-disk.md` | 0, 1 |
| 4 | 6 — No silent control | `phase-06-no-silent-control.md` | 0, 1, 2, 3, 4, 5 |

Waves show what can be built in parallel. Landing still follows the plan's Phase order (see Landing order).

## Adversary

- Phase 0 — codex: 4 accepted, 4 partial, 6 rejected; no needs-human.
- Phase 1 — codex: 6 accepted, 4 partial, 4 rejected (1 Depends-on check, no finding); no needs-human.
- Phase 2 — codex: 11 accepted, 2 partial, 1 rejected; no needs-human.
- Phase 3 — codex: 5 accepted, 3 partial, 6 rejected (1 Depends-on check, no finding); no needs-human.
- Phase 4 — codex: 5 accepted, 4 partial, 7 rejected; 1 needs-human (Tips tab `type`: `tipped` vs `tip`).
- Phase 5 — codex: 4 accepted, 4 partial, 3 rejected; 1 needs-human (`expired_at = localIso(now + N days)`).
- Phase 6 — codex: 7 accepted, 2 partial, 6 rejected; no needs-human.

## Six hats

Bullets about one or more specs are reconciled in each spec's `## Review → ### Six hats`:
- Phase 0: White departure 1, Red "heavy", Black duplication, Black `data-oi-wired`, Black dedupe, Green "Phase 4 first".
- Phase 1: White departure 5, White thumbnail allowlist.
- Phase 2: Black "Add media" two ways, Black duplicate media id.
- Phase 3: White departure 4, Black duplication.
- Phase 4: White departure 2, White guessed fields, Red templates, Black duplication, Green drop borrowed templates, Green drop `state-list-view`.
- Phase 5: White departure 3, Red circular trial link, Black key paths, Black `expired_at`, Black trial body, Black duplication, Green trial read-only.
- Phase 6: Black duplication, Black key paths, Black `data-oi-wired`, Green fallback first.

Bullets about the set as a whole:
- White, "the specs depart from the plan's wording in five places": **accept** as fact. The plan is not edited (it is the human's). The five departures are listed under Open questions so the human can update the wording.
- White, "live checks are spread over the specs, and no single list collects them": **accept**. They are collected under Needs the human below.
- White, "six controls send live writes and no spec puts them behind a flag": **accept** as fact. The flag itself is rejected (see the Green flag line).
- Yellow, write safety is tight (Known bodies only, mocked checks, write allow-list): **accept**, no change.
- Yellow, no committed mirror page is edited, and recaptures fail loudly: **accept**, no change.
- Yellow, each departure is recorded as an ASSUMPTION with its overturn: **accept**, no change. They are gathered under Open questions.
- Green, reorder so Phase 6's fallback comes first and Phases 0–5 drop their read-only handlers: **reject** the reorder, **partial** on the goal. The Phase order is the user's and is not re-opened. The plan puts the fallback in the sign-off Phase (plan:247-255), and that Phase's acceptance needs every Phase 0–5 check (plan:264-266), so the plan does not allow landing it early. The duplication is removed at the other end instead: Phase 6 now deletes each per-Phase read-only handler its fallback covers, and tests that a toggle flips back once (phase-06 Owns, Testing).
- Green, run Phase 4 before Phase 0: **reject**. This is the user's order, and Phase 4 depends on Phase 0's `note`/`READ_ONLY` exports (phase-04 Depends on).
- Green, put all live writes behind one default-off flag: **reject**. The plan's goal is that controls write through the Relay (plan:3-6), and each Phase's acceptance expects the write with no flag. That is a constraint, and rung 4 only decides choices. House precedent (rung 3) agrees: the mirror's existing writes (profile Save, stream form) and `PostComposer` ship with no flag (`grep -n -i flag app/lib/ofMirrorWrites.ts app/components/compose/PostComposer.tsx` finds nothing). ADR-0003's flag gates Inflowwww extras that Infloww lacks, not writes. The gates that remain are Single-Creator scope, an operator click and Known bodies.
- Blue, "the coordinator updates the plan's wording to match the five departures": **reject** the edit, **accept** the record. The plan is a human document that this run does not edit. The departures are listed under Open questions for the human.
- Blue, collect every needs-human and unverified-live item into one parked list: **accept**. See Needs the human.
- Blue, assign one owner for `data-oi-wired` and the `ofMirrorWrites` key changes, and fix the phase order before anyone builds: **accept** the owners, which are decided under Landing order. The order stays the plan's, which already satisfies every Depends on.
- Recommendation (fallback first, Phase 4 before Phase 0, trial link read-only until confirmed live): **partial**. The first two are rejected as reorders, and the fallback's duplication is removed at Phase 6 instead. The trial link stays wired on plan:66 and is parked as needs-human, because only the human can override the plan.

## Cut (YAGNI)

- **Price control, paid posts and `previews`** (Phases 0, 1, 2): the capture has no price control, and a paid page refuses priced posts (server.py:7506).
- **Labels, Save for Later, poll, quiz, expiration, target, format, voice and video writes** (Phase 0): no Known body (ADR-0005). They are read-only.
- **The tag dialog's search, Sort, "Release form" tab, "Invite new user", row "More" menus and `search=` paging** (Phase 0): no Known body and not named. The first 50 rows match the capture's 50.
- **Tag-row avatars through `/img`** (Phase 0): the rows keep the grey placeholder.
- **Refreshing profile or queue data after posting** (Phase 0): Phase 4's Data parts own those pages.
- **An All-Creators fan-out post** (Phase 0): writes happen only in Single-Creator scope.
- **Editing, deleting or pinning posts, and deleting stories** (Phases 0, 3): excluded by the plan's constraint.
- **Vault folder rows and folder filtering, type tabs, sort and "Retry" in the vault dialog** (Phase 1): not named. Folder rows would leave the composer.
- **Server-side vault search (`query=`) and paging past 24** (Phase 1): the plan says client-side, and the Vault page shows the same 24.
- **Removing a thumb from the composer strip** (Phases 1, 2): unpicking in the dialog does it, and no plan line asks for it.
- **A warning for a hidden dedupe hit** (Phase 2): the plan names only `ready:false` and errors as note cases.
- **Several files per pick, a progress bar, video poster frames, drag-and-drop** (Phase 2): the plan says one file per pick, the disabled Post is the in-flight signal, and drag-and-drop is not a captured control.
- **Waiting for OF's transcoder or polling the vault** (Phase 2): the Relay's `send_with` claim is what the post body takes.
- **Reusing the stories upload route for posts** (Phase 2): the plan says no.
- **Any Relay, `of_client` or `relay.ts` change** (Phases 2, 3, 5): the routes, methods and types exist, and the plan adds none.
- **Story caption, @mention and question overlays, video stories, story from vault or URL** (Phase 3): plan YAGNI. The Relay documents image stories.
- **Create highlight, Story archive, Go live and the other non-own strip tiles as writes** (Phase 3): no write method. They show the Read-only note.
- **Hiding the vault copy a story upload leaves, and showing current stories in the strip** (Phase 3): not asked for, and no Data part.
- **Queue streams tab, queue month navigation, marking calendar days with items** (Phase 4): no stream source in the plan, and no captured markup.
- **Notification tabs Likes, Purchases, Promotions, Tags, OnlyFans** (Phase 4): the plan keeps their examples.
- **Statements index, Earning Statistics, Chargebacks, balance boxes, referral balance** (Phase 4): not named.
- **Profile tab counts, Photo/Video sub-tabs, sidebar media strip, label tabs, paging beyond the first page** (Phase 4): not named. The plan asks for the shown rows only.
- **Video play buttons, durations, post prices, locks, poll and quiz bodies inside posts** (Phase 4): not in the captured post template.
- **Row writes: unbookmark, mark-read, withdraw, list create, like, comment, add-to-list** (Phase 4): no Known body. They are read-only.
- **Promotion "Start campaign" write and its discount out-of-range note** (Phase 5): the captured modal has no discount input, and `_PromoBody.discount` is required. The plan's own rule keeps the modal read-only.
- **Bundle Save, subscription price Save, row kebab deletes** (Phase 5): the Relay needs `price`, there is no price write method, and the rows have no real ids.
- **All other settings toggles** (`/users/me/settings`, notification, security, story, streaming) (Phase 5): no Known body.
- **Tracking link `code`, showing the created link in the list, live help-text updates, selectable promotion dropdowns** (Phase 5): no field or Data part, the help text is cosmetic, and the modal is read-only.
- **Inert `#` links, text inputs, selects and editors in `dead.py`, video-player controls, pages outside the plan's `dead.py` list, keyboard-only tests** (Phase 6): the plan's control definition excludes them, or the fallback still covers them.
- **Disabling or restyling unwired controls, and a shared JS helper for the mark** (Phase 6): ADR-0005 keeps OF's look, and the attribute literal is the whole contract.

## Not yet specified

No plan line is wholly uncovered. These plan lines are covered only in part, by a measured departure:
- plan:118 — "date and time fields are parsed with `parseDate`/`parseTime`". The capture has no such fields. Phase 0 uses the calendar day plus `parseTime`.
- plan:143-144 — "every `<img>` src is `/img?u=...`". Phase 1 keeps the Relay's `_thumb` when present.
- plan:207-208 — notification types `tips`/`subscribes`/`comments`/`mentions`. Phase 4 sends `tipped`/`subscribed`/`commented`/`mentioned`.
- plan:213-214 — "each Part's field mapping is a measured table". Several Phase 4 fields are guessed (evidence blocked: needs live Relay responses).
- plan:233-235, 241-244 — the promotion "Start campaign" body, the out-of-range discount collector and "exactly the three bodies". The modal is read-only, so the check asserts two bodies.
- plan:192-194 — "Create highlight" on `home` and `new-post`. It exists only on `profile`.

## Open questions

The five measured departures, for the human to bring the plan's wording in line (the plan file is not edited):
1. The schedule dialog has no date or time fields, so `parseDate` is unused (phase-00 Further Notes; plan:118). If wrong (a recapture shows typed fields), `collectSchedule` switches to `parseDate` on them.
2. Notification types are `tipped`/`subscribed`/`commented`/`mentioned`, not the plan's plurals (phase-04 Further Notes; plan:207-208). If wrong, every filtered tab 400s and stays on examples.
3. The promotion modal is read-only, so `settings_writes.py` asserts two bodies, not three (phase-05 Further Notes; plan:67, 233-245). If wrong (a discount input exists on an uncaptured tab), the promotion write and its discount note are unbuilt work.
4. "Create highlight" exists only on `profile` (phase-03 Further Notes; plan:192-194). If wrong, `story.py` checks the wrong page.
5. Vault tiles keep the Relay's `_thumb` src instead of a strict `/img?` (phase-01 Further Notes; plan:143-144). If wrong, `tileThumb` must skip `_thumb` in the dialog.

Every ASSUMPTION in the specs, sharpest first:
1. Phase 5 — the trial-link body is Known as the plan states (plan:66; ADR-0005 does not count as rung 2). If wrong: a live trial link is created with a body OF may reject or misread, and the trial modal moves to `READ_ONLY_SUBMITS`, taking the picker and the `expired_at` mapping with it.
2. Phase 5 — `expired_at = localIso(now + N×24h)`. If wrong: trial links on live accounts expire at the wrong moment, and expirations other than "No expiration" become read-only.
3. Phase 0 — no dedupe key on `POST /posts`. If wrong (ambiguous failures are common): retries post twice on a live account, and the Relay needs a dedupe key in its own Phase.
4. Phase 2 — a `hidden` dedupe hit is attached with no warning. If wrong: the post fails or publishes invisible media, and a hidden hit must get a red note and not be attached.
5. Phase 4 (evidence blocked) — the field names for payout requests, notifications `isRead`, bookmark `author`, and saved-for-later `text`/`mediaCount` follow other payloads. If wrong: those fields render empty on live data, though `feeds.py` still passes.
6. Phase 4 — the Tips tab sends `tipped`. If wrong: the Tips tab 400s and stays on examples, and NotificationBell's `tip` is the one to keep.
7. Phase 4 — `queue/state-tab-messages` uses `/messages/queue` (plan constraint) despite stale data for newer sends. If wrong: the messages tab shows stale or empty rows, and it moves to `/schedules` chat items.
8. Phase 5 / Phase 6 — Phase 5 owns the `ofMirrorWrites` key change (full path for `bindWrites` and `SUBMITS`, settings-relative `WRITABLE`). If wrong (Phase 5 lands without it): Phase 6 must make it, and `profile/state-more-menu` collides with `WRITABLE.profile`.
9. Phase 6 — the fallback and the widened change path also run in All-Creators scope. If wrong: the existing "leaves an unmapped toggle alone" test must stay, and the All-Creators pass of `dead.py` checks only "no write".
10. Phase 6 — checkboxes reach the Read-only note through the change path, not the click fallback. If wrong (a captured checkbox fires no `change`): it stays silent and `dead.py` fails.
11. Phase 5 — the trial dropdowns become pickable by showing OF's hidden `v-menu__content`. If wrong: every trial link goes out at the captured 10/7/7, and the dropdowns read as fake controls.
12. Phase 5 — the selected value is read from the `aria-selected` option, because the scrubber fakes visible numbers. If wrong: sent counts or days differ from what the operator sees.
13. Phase 5 — "No limits" and the month durations have no Known value and are read-only. If wrong: those trial links could be created but are refused.
14. Phase 4 — templates are borrowed from other captured pages, and queue items are built from OF's stylesheet classes. If wrong (a recapture moves them): bookmarks, referrals and queue lose their rows. Vitest fails loudly.
15. Phase 4 — month view items show in a copy of the list view's agenda block under the calendar. If wrong: the month view looks non-OF, and it needs a capture with events.
16. Phase 4 — `queue/state-list-view` is wired (plan `queue/*`). If wrong: one extra page is wired, removable by its `DATA_PAGES` key.
17. Phase 4 — the shown month comes from the captured header, not today. If wrong: the queue shows October 2026 items forever, until month navigation exists.
18. Phase 4 — notification icons other than `subscribed` and `tip` are removed. If wrong: rows lose an icon OF would show.
19. Phase 4 — the posts' `id` comes from `/users/me` (plan), not the account id. If wrong: one extra request is made where `useOfIdentity` has not run.
20. Phase 0 — the composer summary line ("Scheduled for … · Tagged: … · Clear") is new UI the plan does not name (plan:90-91). If wrong: the operator cannot see or undo a schedule before posting, and OF's own chip must be captured.
21. Phase 0 — the calendar is re-rendered at runtime for the current month. If wrong: only the captured October 2026 days are wired.
22. Phase 0 — the time tab is made `contenteditable`. If wrong: OF's time picker must be captured and wired.
23. Phase 0 — the Post draft is stored only in Single-Creator scope. If wrong: text typed in All-Creators scope is lost on a State page.
24. Phase 0 — a checked Example tag row gives `READ_ONLY` and flips back. If wrong: an error note is wanted instead.
25. Phase 0 — the tag row id is `user.id ?? id`. If wrong: Co-tags carry the wrong OF user id.
26. Phase 0 — text is trimmed, and empty keys are omitted, not `null`. If wrong: the Relay's defaults differ from PostComposer's body.
27. Phase 0 — Wired controls carry `data-oi-wired` early, and Phase 6 owns the contract. If wrong (Phase 6 picks another marker): Phases 0–3 re-mark.
28. Phase 0 — the tag list is `limit=50&offset=0`. If wrong: creators past 50 cannot be tagged.
29. Phase 0 — `textOf` is exported, not copied. If wrong: nothing material.
30. Phase 1 — the composer's attached-media strip is 64px thumbs above `.b-make-post__actions` (the plan's flagged decision). If wrong: OF's real strip must be captured.
31. Phase 1 — the selected mark is OF's `selected` class on the tile and its `.checkbox-item`. If wrong: picks show no mark, though the draft is still right.
32. Phase 1 — `_thumb` is kept (departure 5 above).
33. Phase 1 — search matches the date label plus `_ai` description and tags. If wrong: live OF tiles are searchable by date only.
34. Phase 1 — draft `thumbs` is index-aligned with `media_files`. If wrong: thumbs mismatch the media after mixed picks.
35. Phase 1 — `picked` reaches `applyData` through `MirrorData`. If wrong: selection is lost on a data refresh.
36. Phase 2 — the "Add media" copies on `new-post/state-*` are left to the fallback. If wrong (`dead.py` can click them): they get the same wiring.
37. Phase 2 — Post stays disabled while uploads are in flight, through a counter, and media merge in completion order. If wrong: concurrent uploads attach out of pick order.
38. Phase 2 — the upload thumb is a top-window `blob:` URL with a grey-square fallback. If wrong: thumbs vanish after a reload, though media stay attached.
39. Phase 2 — the refusal note reads `Could not upload: <note>`. If wrong: wording only.
40. Phase 3 — a non-image file is refused client-side. If wrong (the Relay accepts video stories): video stories are blocked needlessly.
41. Phase 3 — non-own story tiles show the Read-only note rather than navigating. If wrong: "Go live" and "Create new trial link" should be links.
42. Phase 3 — non-own tiles show the note in All-Creators scope too. If wrong: Phase 6 must own All-Creators behaviour.
43. Phase 3 — binding is selector-keyed on every page. If wrong: State page dialogs should block the strip.
44. Phase 3 — the story code is its own `useOfStory` hook. If wrong: structure only.
45. Phase 3 — the check's scope is `model:1`, so `X-Account-Id: 1`. If wrong: the check's header assert changes.
46. Phase 5 — read-only submit buttons show `READ_ONLY` in All-Creators scope. If wrong: they should show `SELECT_MODEL`.
47. Phase 5 — `scheduleStream` is folded into a generic `submit(path, body)`. If wrong: naming only. The behaviour is the same.
48. Phase 6 — `dead.py` accepts a note, a file chooser or a markup change from Wired controls. If wrong: some Wired control's response goes undetected and fails falsely.
49. Phase 6 — the mark-check selectors are the plan's measured ones, and a spec's own selector wins. If wrong: a false missing-mark failure.
50. Phase 6 — `dead.py` mocks one tag row and one vault item. If wrong: the mark check runs only in the All-Creators pass.
51. Phase 6 — `dead.py` has no runtime budget. If wrong: it needs a page filter like `render.py`.

## Needs the human

- **Phase 0:** the live check of one immediate post and one scheduled post with a Co-tag (unverified live, floor 2). Also the double-post risk: whether ambiguous failures on `POST /posts` are common enough to justify a Relay dedupe key.
- **Phase 1:** whether real vault CDN URLs pass `proxy_image`'s host allowlist (server.py:3287-3297). This is unverified live.
- **Phase 2:** whether OnlyFans accepts a post with a duplicate `mediaFiles` id (a dedupe hit appends one). Also whether a `hidden` dedupe hit posts visibly. Both need one live post.
- **Phase 3:** one live image story upload. The route is unverified live from this run.
- **Phase 4 (needs-human, codex):** the Tips tab `type`. Run one live `GET /api/of/v2/users/notifications?type=tipped` and one `?type=tip` for a Creator with tips; the one that returns tip rows wins, and NotificationBell follows. Also recorded Relay responses for the guessed fields (payout `invoice`/`state`/`reason`, notifications `isRead`, bookmark `author`, saved-for-later `text`/`mediaCount`).
- **Phase 5 (needs-human, codex):** `expired_at = localIso(now + N days)` for "Offer expiration: N days". This is settled by OnlyFans's JS for the trial modal or by a live capture of one create. Interim: computed. If ruled a guess, expirations other than "No expiration" become read-only.
- **Phase 5 (circular rung 2):** whether the trial-link write ships at all. Its only rung-2 support is the plan's table (plan:66). ADR-0005 was written by this run and cannot be rung 2, and its own Known-body test (live-confirmed or read from OF's JS) is unmet for `create_trial_link`. The Green hat proposes keeping the modal read-only until it is confirmed live. If the human agrees, the modal moves to `READ_ONLY_SUBMITS`, and the dropdown picker and the `expired_at` mapping are dropped.
- **Phase 6:** none.

## Landing order

The plan's Phase order already satisfies every Depends on, and it is binding:

1. Phase 0 — New post: text, schedule, Co-tags (creates `ofMirrorPost`, exports `note`/`READ_ONLY`/`SELECT_MODEL`/`textOf`).
2. Phase 1 — Media from the vault (needs 0).
3. Phase 2 — Upload from disk (needs 0, 1).
4. Phase 3 — Add to story (needs 0).
5. Phase 4 — Real data pages (needs 0).
6. Phase 5 — OF settings writes (no hard dependency; must land before 6).
7. Phase 6 — No silent control (needs 0–5; last).

One-owner decisions, made before anyone builds:
- **`data-oi-wired`: owner Phase 6.** Phase 6 defines the contract, skips marked targets in the fallback, checks marks in `dead.py`, and adds any mark a binder misses. Phases 0–3 set the mark at bind time on their own Wired controls only. Example rows and read-only handlers are never marked, so Phase 4's row actions are unmarked. Phase 5's submit buttons are marked by `bindWrites` when Phase 6 lands.
ASSUMPTION: rung 2. The plan names the mark only in Phase 6 (plan:253). Early marking by Phases 0–3 is rung 4 (additive). Overturned if the human assigns the mark to each Phase's own acceptance.
- **`ofMirrorWrites` key change: owner Phase 5.** Phase 5 makes `bindWrites` take the full Mirror path, keys `SUBMITS` by it, and looks up `WRITABLE` (settings-relative) only for `settings/` paths after stripping the prefix and any `/state-*` suffix. Phase 6 widens binding to every page on those keys and changes none.
ASSUMPTION: rung 2 for the order (the plan puts the `SUBMITS` rework in Phase 5, before Phase 6), then rung 5 for a single owner. Overturned if Phase 5 lands without it, in which case Phase 6 makes it.
- **Per-Phase read-only handlers: removed by Phase 6.** Phases 0, 3 and 4 ship their read-only handlers (the plan names them, and their checks assert them). Phase 6 deletes each one its fallback or change path duplicates, and proves a toggle flips back once. `READ_ONLY_SUBMITS` stays, because it must prevent a native submit.
ASSUMPTION: rung 5 (one code path per control), forced by rung 1: reading both specs shows that a label checkbox would flip twice. Overturned if the human prefers each Phase's handler to stay and Phase 6's change path to skip it by a marker.
