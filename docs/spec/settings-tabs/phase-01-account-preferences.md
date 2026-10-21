# Phase 01 — Your Account, Your Preferences

**Objective.** `/settings/account` and `/settings/preferences` render Infloww-shaped Panels instead of `NotBuiltYet`, save their Settings blobs `account` and `preferences` whole through the Load gate, and render every unbacked control Not wired.

## Measured gap table

Dashboard bundle values are from `~/Downloads/infloww-remote-web/index.9fc9db54.css` (read with grep; selector cited, nothing copied but the value). Rows marked † are measured but not in the plan's Ground-truth table, so each is used under the `ASSUMPTION:` in Further Notes.

| Ground-truth selector → value | Ours today (`file:line`) | Gap | Change |
|---|---|---|---|
| route `/settings/account`, `/settings/preferences` | `app/app/settings/[tab]/page.tsx:16` renders `NotBuiltYet`; `app/lib/nav.ts:159-160` (`nb()`) | no Panel | register `YourAccountTab`, `PreferencesTab` in `SETTINGS_PANELS` (Phase 0); `nb()` stays (Phase 5 removes it) |
| `._personal-info-wrap_rxwf7_132` padding 24px; `._title_rxwf7_137` 14px/500 `--tc-T1`, pb 16px; `._table-wrap_rxwf7_143` mb 40px | none | no sections | Phase 0 `Section` for "Personal", "Agency info", and the preference sections |
| `._personal-item_rxwf7_146` mb 30px; `._personal-item-title_rxwf7_155` 14px/400 `--tc-T3`, mb 8px | none | no fields | Phase 0 `Field` for every labelled control |
| `._personal-avatar_rxwf7_192` 140x140, radius 8px, overflow hidden, centred | `app/components/ui/AccountAvatarPicture.tsx:20` is a Creator avatar (needs `AccountMeta`, fetches the OF avatar); initials precedent `app/components/NotificationBell.tsx:469` | no Agency avatar | an initials box 140x140 radius 8 inside the tab; upload is a `NotWired` control |
| `._personal-input_rxwf7_237` width 448px, radius 8px (`._personal-item-content_rxwf7_230`), border `--tc-L1` | `app/components/ui/primitives.tsx:62` `Input` (`w-full`, `rounded-lg` = 8px) | width | Phase 0 `FieldInput` inside `Field` (448px), border `--if-line` |
| `._disabled-input_rxwf7_242` 448px, border `--tc-L1`, bg `--tc-B-th` | none | read-only Username | read-only `FieldInput`, bg `--if-input-disabled` |
| † `._persinal-text_rxwf7_253` margin 0 10px, line-height 32px | none | gap before "Edit" | "Edit" sits 10px right of the Username input |
| † `._personal-item-timezone_rxwf7_176` 14px/400 `--tc-T3`, pt 8px, mb 8px | none | Report time zone description | description line under the "Report time zone" label |
| selects (no measured selector beyond `._personal-input` width) | house native `<select>`, `app/components/settings/RestrictionsTab.tsx:118` | no 448px select | native `<select>` at the `Field` input width |
| `--tc-*` colours (`:root`) | Phase 0 `--if-*` block | none here | read `--if-*` only, never `--tc-*` |

## Problem Statement
An Agency owner who opens Your Account or Your Preferences sees "not built yet". They cannot see which login they are using, give their agency a name, or record the report time zone, time zone, week start day and language Infloww asks for.

## Solution
Your Account shows a Personal section (initials picture, read-only Username from `GET /auth/me`) and an Agency info section (initials picture, editable Agency Name) and saves the agency name. Your Preferences shows four selects and saves all four values together. Both Panels render Phase 0's `NotAppliedYet` ("Saved for your organization; not applied yet."). Picture upload and Username "Edit" are visible but Not wired.

## User Stories
1. As an Agency owner, I want `/settings/account` to render the Your Account Panel instead of `NotBuiltYet`, so that the tab is usable.
2. As an Agency owner, I want a "Personal" Panel section with a 140px initials picture of my username, so that the layout matches Infloww.
3. As an Agency owner, I want the picture's upload control disabled with the "not wired" tooltip, so that I am never told an upload succeeded when nothing stores it.
4. As an Agency owner, I want my Username shown read-only from `GET /auth/me`, so that I can see which login I am in.
5. As an Agency owner, I want the Username "Edit" button disabled with the "not wired" tooltip, because there is no rename route.
6. As an Agency owner, I want an "Agency info" Panel section with its own 140px initials picture (upload Not wired), so that it matches Infloww's two pictures.
7. As an Agency owner, I want to type an "Agency Name" and Save it to the `account` Settings blob as `{agency_name}`, so that it is kept for my organization.
8. As an Agency owner, I want the saved Agency Name shown again when I reload, so that I can trust it was stored.
9. As an Agency owner, I want Save disabled until the `account` blob has loaded, so that a failed load never overwrites a stored name (Load gate).
10. As an Agency owner, I want nothing on Your Account to call `/api/of/v2/users/me`, so that a Creator's OnlyFans profile is never changed by an agency setting.
11. As an Agency owner, I want `/settings/preferences` to render the Your Preferences Panel, so that the tab is usable.
12. As an Agency owner, I want a "Report time zone" select with the description "Your preferred time zone for Creator and fan reports", so that I know what it governs.
13. As an Agency owner, I want a "Time zone" select, so that I can record my regular time zone.
14. As an Agency owner, I want both zone selects to list `Intl.supportedValuesOf("timeZone")`, plus the stored zone when this browser's list lacks it, so that every IANA zone the browser knows is offered without a new dependency and a stored zone is never silently replaced by the first option.
15. As an Agency owner, I want a "Week start day" select with Monday and Sunday, so that I can choose how weeks start.
16. As an Agency owner, I want a "Language Settings" select with English and Spanish, so that the choice matches Infloww's.
17. As an Agency owner, I want Save to send all four keys `{report_tz, tz, week_start, language}` together (plus any other stored key), even when I changed one, so that the whole blob is replaced, never thinned.
18. As an Agency owner, I want Save on Your Preferences behind the same Load gate, so that a failed load cannot save defaults over my values.
19. As an Agency owner, I want both Panels to say "Saved for your organization; not applied yet.", so that I know nothing reads these values yet (ADR-0008).
20. As a maintainer, I want both tabs registered in `SETTINGS_PANELS`, so that the routes map in one place.
21. As a maintainer, I want the Settings walk to record exactly `PUT /admin/settings/account {"agency_name":"Synthetic Agency"}` and a `PUT /admin/settings/preferences` carrying `"week_start":"sunday"` plus the other three keys, so that the Write list proves the wiring.
22. As a maintainer, I want `docs/screenshots/settings-account.png` and `settings-preferences.png` committed after the Visual loop, so that the result is reviewable.
23. As an Agency owner, I want a Save to keep every key already in a Settings blob that this Panel does not show, so that a later Phase or version never loses data to this one.

## Implementation Decisions
- **Owns.** New `YourAccountTab` and `PreferencesTab` under `app/components/settings/`; two entries in Phase 0's `SETTINGS_PANELS`, keyed `"/settings/account"` and `"/settings/preferences"`; the Phase 1 actions and expected Write list in `scripts/settings-check/walk.py`; the two screenshots.
- **Interfaces.** Both tabs take no props. Each reads its blob through Phase 0's `useSettingsBlob<T>(tab, defaults)` → `{value, set, reset, loaded, save}` and builds only from Phase 0's `SettingsPanel` parts (`SettingsPanel`, `Section`, `Field`, `FieldInput`, `NotWired`, `NotAppliedYet`) and `<SaveRow {...blob.save} />` (the hook's `save.canSave = loaded` is the Load gate). `YourAccountTab` also reads `useUser().user?.username ?? ""` (`UserContext`; `user` is nullable, `UserContext.tsx:74`; house precedent `TransferTab.tsx:51`), which comes from `GET /auth/me`; it adds no fetch of its own. `UserProvider` is already mounted app-wide in `app/components/providers.tsx`, so the runtime needs nothing new.
- **Schema.** None — Phase 0's `user_settings` table holds both blobs; the server does not validate keys inside a blob (ADR-0007).
- **Contracts.** Blob shapes (the Panel-to-test contract of ADR-0007):
  - `account`: `{ agency_name: string }`
  - `preferences`: `{ report_tz: string /* IANA */, tz: string /* IANA */, week_start: "monday" | "sunday", language: "en" | "es" }`
  - Save sends Phase 0's `value = {...defaults, ...stored, ...edits}`, so keys this Phase does not know survive (full object per Phase 0). `account` defaults are `{agency_name: ""}`; `preferences` defaults are listed below. The PUT body is therefore exactly `{agency_name}` / exactly the four keys only when the stored blob holds no other key.
- Your Account layout: Panel header "Your Account"; Section "Personal": Field "Picture" (initials box + `NotWired` upload), Field "Username" (read-only input, "Edit" as `NotWired`); Section "Agency info": Field "Picture" (initials of the Agency Name, falling back to the username), Field "Agency Name" (448px input); then the Not applied yet note and `SaveRow`.
- Your Preferences layout: Panel header "Your Preferences"; Field "Report time zone" with its description; Field "Time zone"; Field "Week start day"; Section "Language Settings" with one select (English / Spanish); then the Not applied yet note and `SaveRow`.
- Defaults when the blob is `{}`: both zones = `Intl.DateTimeFormat().resolvedOptions().timeZone`, `week_start` = `"monday"`, `language` = `"en"`.
- A zone select whose stored value is not in `Intl.supportedValuesOf("timeZone")` lists that value as an extra option, so it stays selected and is saved back unchanged.
- Colours and Geometry come only from `--if-*` Infloww tokens (ADR-0009); font stays `--font-sans`.
- The Legacy tabs, `nav.ts` and the backend are untouched.

### Cross-spec decisions

Stated word for word in every Phase spec of this effort; `docs/spec/settings-tabs/plan-review.md` `## Landing order` names each one's owner.
- (a) Every Acceptance block starts with `set -e` (flags a block already sets stay), and every negated check is written `! cmd || exit 1`, because `set -e` ignores a command inverted with `!` (`bash -c 'set -eu; ! true; echo reached'` prints `reached`).
- (b) `SETTINGS_PANELS` is keyed by the full href, `"/settings/<tab>"` (plan:154 "maps each href"); the `[tab]` page looks a tab up as `` `/settings/${tab}` ``.
- (c) Phases 1–4 land in any order after Phase 0, Phase 5 after all four, Phase 6 last. Each of Phases 1–4 runs the walk with `--allow-unbuilt` set to exactly the non-legacy Settings tabs other than its own, a fixed list never edited at landing; Phase 0 passes `--allow-unbuilt all`; Phases 5 and 6 pass none. A Phase never allows its own tabs, which is how plan:175 "unbuilt panels allowed in Phase 0 only" is read.
  ASSUMPTION: rung 4 (no Phase can block on another's order); overturned if the coordinator fixes plan order and wants every walk to catch a regression in an earlier Phase's tab, in which case each list shrinks to the tabs still unbuilt in plan order.
- (d) A Phase's report check selects the writes to its own paths (`[x for x in writes if x[1] == path]`) and asserts on those; a walk scenario checks only the slice of the Write list it caused; only Phase 6 asserts the whole Write list (the union).
- (e) Only the eleven 1440x900 `docs/screenshots/settings-<tab>.png` are ever committed, never a `-390` PNG (plan:129, plan:309). Phase 0 commits all eleven (the shell), each of Phases 1–5 overwrites its own tabs' PNGs, and Phase 6 refreshes all eleven from its final walk.
- (f) No Acceptance compares a PNG byte for byte (`cmp`) with another walk's. An Acceptance that commits PNGs runs `rm -rf /tmp/settings-shots` before its walk and copies its PNGs from that walk to `docs/screenshots/` in the same block, so the copied files are this run's by construction.
  ASSUMPTION: byte-stability of two walks on one commit is unobserved (rung 4/5); overturned if two walks on one commit are shown byte-identical, which would allow a `cmp` gate in Phase 6.

## Testing Decisions
- Seams: the two components, rendered with `renderWithProviders` (`app/test-utils.tsx:30`) and the Relay mocked at `fetch` (plan Constraint). `YourAccountTab.test.tsx` wraps it in `UserProvider` so `/auth/me` is served by the same fetch stub.
  - `YourAccountTab.test.tsx`: username from the stubbed `/auth/me` is shown read-only and as the Personal picture's initials; "Edit" and both uploads are disabled with "not wired"; with an empty stored blob, typing "Synthetic Agency" and Save sends one PUT to `/admin/settings/account` with body exactly `{"agency_name":"Synthetic Agency"}` and the Agency info picture shows its initials; a stored `{"agency_name":"Beta Two"}` pre-fills the input (story 8); a stored `{"agency_name":"Beta Two","extra":1}` edited and saved sends a body that still carries `"extra":1` (story 23); with a failed GET Save is disabled and no PUT goes out; no request to `/api/of/v2/users/me`.
  - `PreferencesTab.test.tsx`: four labelled controls and the description render; the zone selects offer `Intl.supportedValuesOf("timeZone")`; Week start day offers exactly Monday and Sunday, Language exactly English and Spanish; with an empty stored blob, choosing Sunday and Save sends one PUT to `/admin/settings/preferences` whose body has exactly the four keys with `week_start: "sunday"`; a stored blob pre-fills the selects; a stored blob with an extra key and a zone outside the `Intl` list saves both back unchanged; failed GET keeps Save disabled.
  - Both: the "Saved for your organization; not applied yet." text is present (rendered by `NotAppliedYet`).
- Settings walk: Phase 1 appends two entries to Phase 0's `SCENARIOS` (`(tab, name, run(page), want_writes)`): on `account` fill Agency Name "Synthetic Agency" and Save, want exactly `[PUT /admin/settings/account {"agency_name":"Synthetic Agency"}]`; on `preferences` choose Sunday and Save, want one `PUT /admin/settings/preferences` whose body has exactly the keys `{report_tz, tz, week_start, language}` with `week_start == "sunday"` (the in-memory mock starts empty). Among the run's writes, those to `/admin/settings/account` and `/admin/settings/preferences` are exactly these two, in that order; other Phases' scenarios may add writes to other paths (Cross-spec decision (d)).
- Visual loop: Read `/tmp/settings-shots/settings-account.png` and `settings-preferences.png`, list diffs against the gap table (position, size, label, order, missing element), fix, re-run; three rounds, then each remaining diff is written into the ticket as `VISUAL GAP:`. Copy the final PNGs to `docs/screenshots/`.
- Prior art: `app/contexts/UserContext.test.tsx` (fetch stub + `UserProvider`), `app/components/settings/stickySave.test.tsx` (Load gate), `scripts/of-mirror-check/writes.py:44,58` (Write list assertions).

## Acceptance
Run as one script; every line must exit 0.
```sh
set -euo pipefail
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run components/settings/YourAccountTab.test.tsx components/settings/PreferencesTab.test.tsx
./venv/bin/python service/tests/test_settings_api.py
! grep -rn "api/of/v2/users/me" app/components/settings/YourAccountTab.tsx app/components/settings/PreferencesTab.tsx || exit 1
grep -q "NotAppliedYet" app/components/settings/YourAccountTab.tsx
grep -q "NotAppliedYet" app/components/settings/PreferencesTab.tsx
# walk: start the dev server, run the Settings walk, stop the server (fixed list: every non-legacy tab but this Phase's own, Cross-spec decision (c))
(cd app && npx next dev --webpack -p 3091 >/tmp/settings-dev.log 2>&1 &) ; until curl -sf -o /dev/null http://localhost:3091/settings/account; do sleep 2; done
rm -rf /tmp/settings-shots
python3 -I scripts/settings-check/walk.py --allow-unbuilt security-org,security-personal,billing,balance,roles,sales,time-tracking,messaging,about
python3 -I -c 'import json; r=json.load(open("/tmp/settings-shots/settings-report.json")); assert r["failures"]==[], r; w=[x for x in r["writes"] if x[1] in ("/admin/settings/account","/admin/settings/preferences")]; assert [x[:2] for x in w]==[["PUT","/admin/settings/account"],["PUT","/admin/settings/preferences"]], w; assert w[0][2]=={"agency_name":"Synthetic Agency"}, w; assert set(w[1][2])=={"report_tz","tz","week_start","language"} and w[1][2]["week_start"]=="sunday", w'
pkill -f "next dev --webpack -p 3091"
# copy this walk's PNGs (Cross-spec decisions (e), (f): no cmp against another walk)
cp /tmp/settings-shots/settings-account.png /tmp/settings-shots/settings-preferences.png docs/screenshots/
git ls-files --error-unmatch docs/screenshots/settings-account.png docs/screenshots/settings-preferences.png
scripts/settings-check/export-check.sh   # the plan's throwaway-tree recipe, scoped to lines this effort added (hits inherited from before the effort base are reported, not failed)
# manual: the implementer Read both PNGs over up to three Visual loop rounds and recorded any VISUAL GAP: in the ticket
```

## Depends on
- Phase 0 — the Settings header and Tab list shell, `--if-*` Infloww tokens, `SettingsPanel` parts (`SettingsPanel`, `Section`, `Field`, `FieldInput`, `NotWired`, `NotAppliedYet`), `useSettingsBlob(tab, defaults)` with its `save` for `SaveRow` (the Load gate), the `SETTINGS_PANELS` record, `GET/PUT /admin/settings/{tab}` with `account` and `preferences` on the allow-list, `test_settings_api.py`, and `walk.py` with `--allow-unbuilt`, `SCENARIOS` and `settings-report.json`.
- Existing — `UserProvider` mounted in `app/components/providers.tsx` (for `useUser`).

## Out of Scope
- Picture upload and storage — no Relay endpoint; Not wired (ADR-0008).
- Username rename — no rename route (plan Ground truth 5); "Edit" is Not wired.
- Any consumer of the agency name (Infloww's Leaderboard) or of the preferences (report time zone, top-bar clock, week start, UI language) — plan: "No consumer yet".
- Spanish translation of the UI — the Language value is stored only.
- Clone hints in §3.10 row 2 (weekly-report start day, display mode, platform sync) — `[CL ?]`, not in the plan's Phase 1 field list.
- `/api/of/v2/users/me` — that is the Creator's OF profile, not the Agency account.
- Removing `nb()` / `NotBuiltYet` — Phase 5.
- Dark-theme screenshot — the walk's dark coverage is not a Phase 1 line.

## Further Notes
- ASSUMPTION: the † measured values (`._persinal-text_rxwf7_253` 10px gap, `._personal-item-timezone_rxwf7_176` description 14px `--tc-T3` pt 8 mb 8) are used though they sit outside the plan's table (rung 1 measurement, flagged by the plan's rule); overturned if the plan table is amended otherwise.
- ASSUMPTION: the Agency info picture shows the Agency Name's initials, falling back to the username (rung 5); overturned if Infloww's picture is shown to mirror the Personal one.
- ASSUMPTION: the avatar is a small initials box inside `YourAccountTab`, not `AccountAvatarPicture`, which is Creator-only and fetches an OF avatar (rung 3/5, `AccountAvatarPicture.tsx:20`, `NotificationBell.tsx:469`); overturned if a shared user-avatar component appears.
- ASSUMPTION: `language` is stored as `"en"` / `"es"`, `week_start` as lowercase `"monday"` / `"sunday"` (the latter rung 2 from the walk line; the former rung 6); overturned by a consumer needing another encoding.
- ASSUMPTION: defaults for an empty blob are the browser's zone, Monday and English (rung 5); overturned by a stored default elsewhere.
- ASSUMPTION: selects are the house native `<select>` (rung 3, `RestrictionsTab.tsx:118`) at the 448px `Field` width; overturned if Phase 0's `SettingsPanel` ships a select part.
- ASSUMPTION: each preference sits in its own `Field` row; the measured two-column `._personal-item-row_rxwf7_325` grid is not used (rung 5, no evidence which fields it pairs), and since no other Phase uses it either, it is recorded as `VISUAL GAP: the two-column field grid repeat(2,350px) is not used; every field is its own row` in this Phase's ticket and in Phase 6's parity doc; overturned by a Visual loop diff showing paired fields.
- ASSUMPTION: Agency Name is sent as typed, with no length or empty-value validation (rung 5); overturned if the help center (H262101) states a limit.
- ASSUMPTION: both Panels show the Not applied yet note (Phase 0's `NotAppliedYet`), following ADR-0008's own ASSUMPTION that every Blob tab shows it; overturned with that ADR.
- ASSUMPTION: a stored zone missing from this browser's `Intl.supportedValuesOf("timeZone")` is kept as an extra option rather than replaced (rung 4, keeping a value is cheaper to undo than overwriting it); overturned if the plan wants stored zones validated.
- ASSUMPTION: `YourAccountTab.test.tsx` wraps the tab in `UserProvider` with `/auth/me` from the fetch stub rather than mocking `useUser` (rung 3, `UserContext.test.tsx`); overturned if Phase 0 adds a user seam to `renderWithProviders`.
- ASSUMPTION: the walk interface is Phase 0's spec (`walk.py [--allow-unbuilt all|<tab>,…]`, `SCENARIOS`, `settings-report.json`, dev server already on :3091); the Acceptance allows exactly the non-Phase-1 non-legacy tabs as unbuilt, a fixed list, so it passes in any landing order (Cross-spec decision (c)). Overturned by a different Phase 0 walk interface.

## Review
Reviewer: codex (blind call, then draft call; both exit 0, outputs non-empty) — 2026-10-13.

Blind call:
- B1 reject — per-Employee or browser-local preferences: ADR-0007 keys every Blob tab by `users.id`, the Agency, and the plan names blob `preferences` (rung 2).
- B2 reject — reuse the Creator's `AccountAiConfig.timezone`: the plan says "No consumer yet"; the spec keeps Agency keys separate and wires nothing to Creators.
- B3 reject — agency name as a `users` column or omitted: ADR-0007 rejects per-field columns; the plan names blob `account` `{agency_name}`.
- B4 reject — structured per-field routes: ADR-0007's Considered Options already rejects them.
- B5 accept — plan's Phase 1 Acceptance omits the ADR-0008 note: the spec already required it (story 19, tests); now pinned to Phase 0's `NotAppliedYet` part and checked per file.
- B6 accept — Leaderboard / top-bar consumers documented in §3.10: already deferred in Out of Scope; `grep -rln "agency_name\|report_tz\|week_start" app service` returns nothing, so no consumer exists today.
- B7 accept — no test that unknown blob keys survive a Save: story 23 added; both component tests now seed an extra key and assert it is in the PUT.
- B8 reject — Chatter / impersonation cases: the route and its auth are Phase 0's (`_require_user()` 401s a Chatter session, `tenant_keys_api.py:9-14`; impersonation is read-only in the session middleware); a fetch-mocked Panel test cannot prove either.
- B9 accept — a stored zone missing from the browser's `Intl` list, and Language's effect: a stored zone is now kept as an extra option (Implementation Decisions, story 14, test); Language is stored only (Out of Scope, unchanged).
- B10 accept — seam is the browser walk on writes plus service tests: matches the spec (component tests, Phase 1 `SCENARIOS`, `test_settings_api.py`); no change.
- B11 partial — falsify "no consumer" by grepping the keys: run above (empty) and recorded here; no Acceptance line added, since a consumer belongs to a later plan (ADR-0008 Consequences).
- B12 reject — saved values activate silently under a future consumer: ADR-0008 Consequences assigns that to the consumer's plan.
- B13 reject — screenshots do not prove Settings pixels: the plan's Ground truth 3 makes the bundle the pixel source (binding); differences become `VISUAL GAP:` lines.
- B14 accept — "all tabs are stubs" premise: verified at `app/lib/nav.ts:159-160` (`nb()`); no change.

Draft call:
- D1 accept — exact-body assertions contradict whole-blob merging: Contracts now say the body is exact only for an empty stored blob (Phase 0's `value = {...defaults, ...stored, ...edits}`); tests and walk state the empty mock; extra-key survival tested.
- D2 accept — stories 2, 6, 8, 15, 16 had no assertion: tests now cover both initials pictures, stored-name prefill, the Monday/Sunday and English/Spanish option sets.
- D3 accept — Acceptance would pass after an earlier failure, and PNGs were not tied to the run: block now runs under `set -euo pipefail`, asserts `settings-report.json` writes and failures, and `cmp`s the committed PNGs against `/tmp/settings-shots/`.
- D4 partial — Depends on omits `UserProvider`: it is mounted in `app/components/providers.tsx` (outside the reviewer's workspace, so its grep missed it); added as an existing dependency, and the tab now reads the nullable `user?.username ?? ""` (`UserContext.tsx:74`, precedent `TransferTab.tsx:51`).

Cross-check against the Phase 0 spec (adversary, rung 1; the reviewer could not see `docs/spec/`):
- X1 accept — Interfaces named `useSettingsBlob(tab)` and a hand-wired `canSave`; Phase 0 ships `useSettingsBlob(tab, defaults)` and `<SaveRow {...blob.save} />`; rewritten.
- X2 accept — the Acceptance grep for the literal sentence would fail once the tabs use Phase 0's `NotAppliedYet`; replaced with a per-file `NotAppliedYet` grep.
- X3 accept — `walk.py` with no arguments fails on the nine still-unbuilt tabs (Phase 0 allows unbuilt only via `--allow-unbuilt`); Acceptance passes the list as Phase 2's spec does, and the walk scenarios go into `SCENARIOS`.
- X4 accept — inputs use Phase 0's `FieldInput`, not `primitives.tsx` `Input`; gap table rows updated.

No needs-human.

### Six hats

Six hats report (`.scratch/settings-tabs/SIX-HATS.md`), 2026-10-13, reconciled by the plan reviewer. Cross-spec items (a)–(f) are decided under Implementation Decisions, "Cross-spec decisions".
- White, "no Phase builds the two-column grid; Phase 1 declines it" (phase-01:122) — **accept**: the ASSUMPTION now records `VISUAL GAP: the two-column field grid repeat(2,350px) is not used; every field is its own row` for this Phase's ticket and Phase 6's parity doc.
- Black (a), "`! grep` never fails" (phase-01:86) — **accept**: the line ends `|| exit 1`.
- Black (c)/(d), "exact two-write check goes red when Phase 2's or 3's writes are in `SCENARIOS`" (phase-01:92,127) — **accept**: the report check selects the writes to `/admin/settings/account` and `/admin/settings/preferences` by path; Testing Decisions and the walk ASSUMPTION rewritten; the `--allow-unbuilt` list is fixed and no longer edited at landing.
- Black (f), "Phase 1 depends on `cmp`" (phase-01:94) — **accept**: the `cmp` lines are replaced by `rm -rf /tmp/settings-shots` before the walk and a `cp` of both PNGs after it; this supersedes the `cmp` part of Review D3.
- Blue 4, "filter writes by path as Phase 3 does" — **accept**: same edit.
- Green, "fix plan order and drop the any-order list" (phase-01:91) — **reject**: one assumption was chosen for the set, any order with fixed lists (Cross-spec decision (c), rung 4: no Phase blocks on another's order); this Phase's list is unchanged.
