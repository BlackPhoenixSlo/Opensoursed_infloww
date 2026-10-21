# Phase 04 — Time tracking, Messaging settings

**Objective.** `/settings/time-tracking` and `/settings/messaging` render Infloww-shaped Panels that read and write the `time-tracking` and `messaging` Settings blobs, show "Saved for your organization; not applied yet.", and leave `/admin/translate` untouched.

## Measured gap table

Ground truth is the plan's table (rung 2) plus Dashboard bundle reads (`grep` / `python3 -I` on `~/Downloads/infloww-remote-web/index.9fc9db54.css` and `index.9f50f370.js`, rung 1). Our side today: both tabs are `nb()` (`app/lib/nav.ts:168-169`) and render `NotBuiltYet` (`app/app/settings/[tab]/page.tsx:16`).

| Ground truth (selector → value) | Ours (`file:line`) | Gap | Change |
|---|---|---|---|
| `._about-header_rxwf7_9` → Panel header 48px, title 16px/500 | `[tab]/page.tsx:16` NotBuiltYet | no Panel | Both tabs render inside Phase 0's `SettingsPanel` (header + 24px body) |
| Time tracking's bundle component (`ClockSetting`) puts "Edit", and in edit mode "Cancel" + "Save" (primary), in the `about-header` row (bundle JS, rung 1) | none | no actions | Edit / Cancel / Save sit on the right of the Panel header |
| `._translation-item_rxwf7_369` → border `--tc-L1`, radius 8px, margin 24px, padding 24px; title 14px/600 `--tc-T1`; tip 12px/20px `--tc-T2` (the bundle's Time tracking uses this card three times) | none | no cards | Time tracking = three bordered cards on `--if-line`, `--if-fg`, `--if-fg-2` |
| `._translation-item-input_rxwf7_408` disabled input bg `--tc-T-disable` | `app/components/ui/primitives.tsx:62` `Input` (app tokens) | value not in table | Disabled input bg = `--if-input-disabled` (`--tc-B-th` #fafafa). ASSUMPTION: `--tc-T-disable` is not in the table, so Phase 0's slot stands in; overturned by a measured `--tc-T-disable` row. |
| Bundle `InputInteger` min 1, max 999, margin `0 8px`, inline in "…clocked out after [n] minute(s) of inactivity" | `primitives.tsx:62` `Input type=number` | none built | `Input type="number"` min 1 step 1, inline, 8px side margins. ASSUMPTION: max 999 and an 80px width are not in the table; overturned by a measured width or a plan line on the maximum. |
| `._translation-item-content_1cat4_4` → padding 12px 16px, radius 12px, bg `--surface-level-00-emphasis-00`, margin-top 16px | none | no card, no token | Messaging cards use these, with a new `--if-card-bg` Infloww token. ASSUMPTION: its values (light `rgba(0,0,0,.055)` from `.theme-light`, dark `rgba(255,255,255,.055)` from `.theme-dark`) are measured but not in the table; overturned by a table row. |
| `._translation-item-title_1cat4_10` → flex, space-between, margin-bottom `--sizing-named-micro` 8px; `-title-left` gap `--sizing-named-mini`; `._btn-wrap_1cat4_21` gap 8px | none | no title row | Title row: icon + title left, control right, 8px below. ASSUMPTION: `--sizing-named-mini` = 12px is not in the table. |
| `._messaging-setting-wrap_1cat4_1` → padding 16px 0 | Phase 0 Panel body 24px | value not in table | ASSUMPTION: keep Phase 0's 24px Panel body padding. |
| Bundle messaging Panel: card 1 = translate icon + title + `HBSwitch` + caption; card 2 = edit icon + title + three buttons + caption + `HBRcTextArea autoSize` | `SwitchTrack.tsx:14` (app colours), `primitives.tsx:82` `Textarea` (11px mono) | colours, font size | Switch = the drawing Phase 0's `ToggleRow` uses; prompt `Textarea` overridden to 14px `--font-sans`, `--if-line` border, 6 rows. ASSUMPTION: no textarea size is in the table, and auto-size is dropped. |
| Font: Infloww body `RobotoRegular` / Suisse Int'l | `globals.css:41` `--font-sans` | font | None; this is the recorded VISUAL GAP (Constraints). |
| `/admin/translate` reads no config (`service/translate_api.py:222`) | same | none | None; it must still read no Settings blob. |

## Problem Statement
An Agency opening Time tracking or Messaging settings sees "not built yet". It cannot record its clock-out policy, its clock-in reminder, whether AI translation is enabled, or its AI Translator prompt the way Infloww lets it.

## Solution
Time tracking opens on a read view with "Edit". Edit turns on the enable toggle, "Auto clock out time" (whole minutes, at least 1) and the clock-in reminder, with "Save" / "Cancel". Messaging settings shows an "AI translation" card with the organization switch, and an "AI Translator prompt" card with "Edit" › textarea › "Save". Both save to their Settings blob and say the values are Not applied yet.

## User Stories
1. As an Agency, I want `/settings/time-tracking` to show a Time tracking Panel instead of `NotBuiltYet`, so that the tab is real.
2. As an Agency, I want the Panel to open read-only, with the stored values shown in disabled controls and "Edit" in the Panel header, so that I cannot change policy by accident.
3. As an Agency, I want "Edit" to stay disabled until the `time-tracking` blob has loaded, so that I never edit defaults over values I could not see (Load gate).
4. As an Agency, I want Edit to enable the "Enable time tracking" toggle, the "Auto clock out time" minutes field and the "Clock-in reminder" control, and to swap "Edit" for "Cancel" and "Save".
5. As an Agency, I want 0, an empty field, a negative or a fraction rejected with "Enter at least 1 minute." and Save disabled, so that no invalid minutes are sent.
6. As an Agency, I want Save to send exactly `PUT /admin/settings/time-tracking {enabled, auto_clock_out_minutes, clock_in_reminder}` and then return to the read view showing the saved values.
7. As an Agency, I want Cancel to restore the loaded values, return to the read view and send nothing.
8. As an Agency, I want a failed load to leave Save disabled with no PUT on the wire, so that a sparse blob never replaces mine.
9. As an Agency, I want a failed save to keep me in edit mode with the error shown, so that nothing pretends it saved.
10. As an Agency, I want `/settings/messaging` to show the Messaging settings Panel in `1cat4` card geometry.
11. As an Agency, I want an "AI translation" card with a switch named "Enable AI translation in Messages Pro for employees in your organization", reflecting the stored `ai_translation`.
12. As an Agency, I want flipping that switch to save at once as `PUT /admin/settings/messaging {ai_translation, prompt}` with the stored prompt, disabled until the blob loads and while the save runs, and flipped back with an error if the save fails.
13. As an Agency, I want an "AI Translator prompt" card showing the stored prompt (or "No prompt set"), with "Edit" that opens a textarea plus "Cancel" and "Save".
14. As an Agency, I want prompt Save to send `PUT /admin/settings/messaging {ai_translation, prompt}` with the stored toggle value and my text, and prompt Cancel to restore the stored text and send nothing.
15. As an Agency, I want both Panels to say "Saved for your organization; not applied yet." (ADR-0008), so that I know nothing clocks anyone out and no LLM translates yet.
16. As the operator, I want `/admin/translate` to keep translating through Google with no prompt and no read of the `messaging` blob.
17. As a developer, I want both Panels registered in `SETTINGS_PANELS`, so that the routing seam is the one Phase 0 built.
18. As a developer, I want `TimeTrackingTab.test.tsx` and `MessagingSettingsTab.test.tsx` to assert on the wire through a mocked `fetch`.
19. As a reviewer, I want `walk.py` to record exactly the Write lists named under Acceptance, at 1440x900 and 390x844, with no overflow and no console error.
20. As a reviewer, I want the final `docs/screenshots/settings-time-tracking.png` and `settings-messaging.png` committed after the Visual loop, with any remaining difference written as `VISUAL GAP:`.

## Implementation Decisions
- **Owns.** `TimeTrackingTab` and `MessagingSettingsTab` (new, under `app/components/settings/`), with their two vitest files; their two entries in `SETTINGS_PANELS`; the `--if-card-bg` Infloww token (light and dark) in the `--if-*` block; this Phase's flows and expected Write list in the Settings walk; the two committed PNGs.
- **Interfaces.** Both tabs are prop-less default exports that read their blob through Phase 0's `useSettingsBlob("time-tracking", TIME_TRACKING_DEFAULTS)` / `useSettingsBlob("messaging", MESSAGING_DEFAULTS)` → `{value, set, reset, loaded, save}`. Because `save.onSave` PUTs the hook's whole `value` as it stands when it runs, a Save never runs in the same handler as its `set`: the handler sets the change plus a pending flag, and an effect calls `save.onSave()` once the change is in `value`. `SETTINGS_PANELS` gains `"/settings/time-tracking"` and `"/settings/messaging"` (full hrefs, Cross-spec decision (b)). The blob shapes are the contract between Panel and tests (ADR-0007):
  ```ts
  type TimeTrackingBlob = { enabled: boolean; auto_clock_out_minutes: number; clock_in_reminder: boolean };
  type MessagingBlob    = { ai_translation: boolean; prompt: string };
  ```
- **Schema.** None — `user_settings` and the `time-tracking` / `messaging` allow-list come from Phase 0.
- **Contracts.** `GET /admin/settings/{tab}` → `{tab, config}`; `PUT` sends the full object for the tab, exactly the keys above. No other route is called. `/admin/translate` is not changed.
- A missing key is shown as its default, through the hook's `defaults` merge: `enabled:false`, `auto_clock_out_minutes:60`, `clock_in_reminder:false`, `ai_translation:false`, `prompt:""`. A stored key of the wrong type is not coerced: only this Panel writes the blob (ADR-0007), and a stored minutes value that fails validation shows the error and blocks Save like a typed one.
  ASSUMPTION: the defaults are not in the Dashboard bundle or the plan (rung 5; 60 keeps the walk's "30" a real change). Overturned by a measured Infloww default.
- Time tracking's Save is a `SaveRow` (label "Save") in the Panel header, with `canSave` = blob loaded ∧ minutes valid. Cancel and Edit are secondary `Button`s beside it. All three go in Phase 0's `SettingsPanel({title, actions?, children})` `actions` slot, so this Phase changes no shared part. The header placement follows the bundle's `ClockSetting` (rung 1). On success (`save.saved`) the Panel returns to the read view. On failure it stays in edit mode with `save.error` shown.
- Time tracking cards: "Enable time tracking" + toggle (tip "Track your team's work hours with clock in and clock out."), "Auto clock out time" + "Users are clocked out after [n] minute(s) of inactivity.", "Clock-in reminder" + toggle.
  ASSUMPTION: the toggle label is the bundle's, and the reminder's label and its boolean type are a guess. The plan names the key but not the type (rung 5). Overturned by H300963 text that shows a non-boolean reminder.
- The Messaging switch saves on flip with no Save button, as the bundle's `HBSwitch` card has none. The prompt draft lives in the card's local state and reaches the hook (`set({prompt})`) only on prompt Save, so the hook's `value` is always the stored blob plus at most one change, and a switch flip never sends an unsaved draft. The switch is disabled until `loaded` and while `save.saving`. A failed flip calls `reset()`, which flips it back, and shows `save.error`.
  ASSUMPTION: save-on-flip goes around `SaveRow` (rung 1 for the shape, rung 3 for the gate). Overturned if the human wants a Save for the switch.
- The prompt card's Cancel is inferred from the bundle's three buttons (default, primary, default).
  ASSUMPTION: Cancel exists; overturned by a bundle read that shows only "Edit" and "Save".
- The "not applied yet" note is Phase 0's `NotAppliedYet` part, placed once under each Panel header.
  ASSUMPTION: placement (rung 5).

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
- **Seams.** (1) The vitest component seam: each tab rendered with `renderWithProviders` (`app/test-utils.tsx:30`), relay mocked at `fetch`, and assertions on requests and visible text only. (2) The Settings walk for the Write list and the computed-style rules.
- `TimeTrackingTab.test.tsx` covers:
  - 0, empty, -5 and 1.5 minutes (one `it.each`) are each rejected: "Enter at least 1 minute." shown, Save disabled, and no PUT after a click.
  - Cancel restores the loaded values and sends nothing.
  - Edit → 30 → Save PUTs exactly the three keys.
  - Controls are disabled before Edit.
  - After a failed load, Edit and Save are disabled and no PUT goes out.
  - An empty blob (`{}`) shows 60 in the minutes field; Edit → Save PUTs the three defaults.
  - A 500 on the PUT keeps edit mode ("Save" still shown) with the error text, after exactly one PUT.
  - "Saved for your organization; not applied yet." is shown.
- `MessagingSettingsTab.test.tsx` covers:
  - The toggle PUTs `{ai_translation:true, prompt:<stored>}`.
  - With an unsaved prompt draft typed, a toggle flip PUTs the stored prompt, not the draft.
  - A 500 on the toggle PUT flips the switch back and shows the error.
  - The switch is disabled before the blob loads.
  - Edit → "synthetic prompt" → Save PUTs `{ai_translation:<stored>, prompt:"synthetic prompt"}`.
  - Prompt Cancel sends nothing.
  - After a failed load, no PUT goes out.
  - No request reaches `/admin/translate`.
  - "Saved for your organization; not applied yet." is shown.
- **Prior art.** `stickySave.test.tsx` (the Load gate asserted on the wire), `settingsBlob.test.ts` (Phase 0), `scripts/of-mirror-check/writes.py:44,58` (Write list recording).

## Acceptance
```sh
set -e
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
./venv/bin/python service/tests/test_settings_api.py   # venv = <main checkout>/venv, symlinked for the run
test -f app/components/settings/TimeTrackingTab.test.tsx
test -f app/components/settings/MessagingSettingsTab.test.tsx
grep -qE "TimeTrackingTab" "app/app/settings/[tab]/page.tsx"
grep -qE "MessagingSettingsTab" "app/app/settings/[tab]/page.tsx"
# /admin/translate unchanged and blind to the blob
git diff --quiet main... -- service/translate_api.py
if grep -nE "user_settings|UserSetting|settings_api|admin/settings" service/translate_api.py; then exit 1; fi
# Settings walk. It asserts this Phase's Write list:
#   time-tracking: Edit → 30 → Save ⇒ exactly one PUT /admin/settings/time-tracking {"enabled":…,"auto_clock_out_minutes":30,"clock_in_reminder":…}
#   time-tracking: Edit → Cancel ⇒ nothing recorded
#   messaging: Edit → "synthetic prompt" → Save ⇒ PUT /admin/settings/messaging whose prompt == "synthetic prompt"
(cd app && npx next dev --webpack -p 3091 >/tmp/settings-dev.log 2>&1 &)
for i in $(seq 1 90); do curl -sf -o /dev/null http://localhost:3091/settings/messaging && break; sleep 2; done
rm -rf /tmp/settings-shots
python3 -I scripts/settings-check/walk.py --allow-unbuilt account,preferences,security-org,security-personal,billing,balance,roles,sales,about   # every non-legacy tab but this Phase's own (Cross-spec decision (c))
pkill -f "next dev --webpack -p 3091" || true
# manual (implementer): Visual loop. Read /tmp/settings-shots/settings-{time-tracking,messaging}.png, diff them against the gap table, fix, re-run (≤3 rounds), write the rest as VISUAL GAP:
# copy this walk's PNGs (Cross-spec decisions (e), (f))
cp /tmp/settings-shots/settings-time-tracking.png /tmp/settings-shots/settings-messaging.png docs/screenshots/
test -s docs/screenshots/settings-time-tracking.png && test -s docs/screenshots/settings-messaging.png
# the plan's export recipe, widened to uncommitted and untracked files (`git diff main...` lists only committed changes)
scripts/settings-check/export-check.sh   # the plan's throwaway-tree recipe, scoped to lines this effort added (hits inherited from before the effort base are reported, not failed)
```

## Depends on
- Phase 0 provides:
  - the `--if-*` block
  - the `SettingsPanel` parts: `SettingsPanel({title, actions?, children})`, `ToggleRow`'s switch, `NotAppliedYet`
  - `useSettingsBlob(tab, defaults)` → `{value, set, reset, loaded, save}` with the `SaveRow` Load gate
  - the `SETTINGS_PANELS` record
  - `user_settings` and `/admin/settings/{tab}` with `time-tracking` and `messaging` on the allow-list
  - `walk.py` with its mocks, Write-list recorder, `SCENARIOS` list (this Phase appends its three flows) and `--allow-unbuilt`
- No other Phase: Phases 1–3 may land before or after this one (Cross-spec decision (c)); the walk's fixed `--allow-unbuilt` list covers every other non-legacy tab.

## Out of Scope
- Applying any value: no auto clock-out, no reminder, no LLM translation, no prompt reaching `/admin/translate`. These are Not applied yet (ADR-0008); each is its own project.
- The bundle's "Enable clock in and clock out for" platform checkboxes. The plan does not list them, and we have no clock-in surface.
- The 36-language picker and AI Copilot. They are not in the plan's Phase 4 Decisions.
- Owner/Admin-only editing. There are no enforced Permission roles (ADR-0008).
- Server-side validation of minutes. The server does not validate blob keys (ADR-0007), so the 1-minute floor is the Panel's.
- A walk flow for the Messaging switch. The plan's Write list does not name one, and vitest covers it.
- Removing `nb()` and `NotBuiltYet` (Phase 5), and the parity doc (Phase 6).

## Further Notes
Every open question is decided inline above and flagged ASSUMPTION:. The bundle's UI strings are used only as labels, and no handle or name from it is copied.

## Review

Reviewer: codex (`codex exec`, reasoning effort high, read-only sparse workspace), 2026-10-13. Blind call B, then draft call D.

- B1 (alternatives: build the clock-out and translation behaviour, or defer the Phase) — **reject**: the plan's Phase 4 Decisions say `/admin/translate` does not read the blob (`docs/plans/settings-tabs.md:258-261`), and ADR-0008 decides that Settings apply nothing. Both are binding (rung 2).
- B2 (the "not applied yet" note is never asserted) — **accept**: both vitest files now assert the ADR-0008 sentence, and the note is Phase 0's `NotAppliedYet` part instead of a local line.
- B3 (defaults, maximum, reminder type, prompt validation, 36 languages undefined) — **partial**: the defaults, the reminder type and the 36-language picker were already decided inline (ASSUMPTION lines, Out of Scope). The maximum and prompt length stay undecided: the server's 64 KB cap (Phase 0) is the only prompt limit, and nothing reads either value (ADR-0008).
- B4 (owner-only editing is implicit) — **reject**: Out of Scope already excludes it, because there are no enforced Permission roles (ADR-0008), and every `/admin/settings` call needs a session (`service/tenant_keys_api.py:35-42` pattern).
- B5 (no coverage of an empty blob, untouched fields, failed load) — **accept**: an empty-blob case is added (60 shown, then the defaults PUT). Failed load was already covered. Time tracking PUTs all three keys, so no key is left untouched.
- B6 (test at Panel → API → persisted blob, plus the service tests) — **reject**: the spec already runs `test_settings_api.py` (Phase 0's round-trip and isolation cases) and tests at the `fetch` seam. A consumer seam is excluded by ADR-0008.
- B7 (falsifiers: a runtime consumer of either blob, or a per-Employee policy) — **reject**: codex's own grep finds no consumer (only `app/lib/nav.ts:168`), and per-Agency keying is ADR-0007's decision.
- D1 (empty, negative and fractional minutes, failed save and a failed switch flip are untested) — **accept**: an `it.each` covers 0, empty, -5 and 1.5. New cases: a failed Time tracking save stays in edit mode with the error after one PUT; a failed flip reverts the switch and shows the error; the switch is disabled before load. The failure behaviour is now written in Implementation Decisions (`save.error`, `reset()`).
- D2 (note not asserted) — **accept**: same as B2.
- D3 (`test -s` does not prove the PNGs are the Visual loop's output, or that they are committed) — **partial**: each PNG must now also be newer than its Panel component (`-nt`). Committing is the coordinator's job in this run (HEADER: implementers never commit), so no Acceptance line can check it. A byte `cmp` against the re-run walk was rejected as flaky.
- D4 (the export recipe skips uncommitted and untracked files) — **accept**: observed in a scratch repo, where `git diff --name-only main...` printed nothing and `git ls-files --others --exclude-standard` printed `new.txt`. The plan's recipe is kept and widened with `git diff HEAD` and `git ls-files --others --exclude-standard`. This checks more than the plan asked, never less.
- D5 (prompt Cancel goes beyond the plan) — **reject**: the bundle's prompt card has three buttons (default, primary, default; rung 1, already flagged ASSUMPTION). An edit mode with no exit would trap the user, and Cancel sends nothing, so it adds no write.
- D6 (the header actions slot is an unplanned shared change) — **accept**: Phase 0's spec already defines `SettingsPanel({title, actions?, children})` (`docs/spec/settings-tabs/phase-00-shell-tokens-blob.md:78`). This Phase now uses it as is, the "adds one if absent" clause and its ASSUMPTION are dropped, and Depends on names the slot.
- D7 (Phase 0's parts are absent in this checkout) — **reject**: Phase 0 is a planned prerequisite, already listed under Depends on.
- Reconciler (while checking D6 against Phase 0's spec) — **accept**: `useSettingsBlob` takes `(tab, defaults)` and its `onSave` PUTs the whole current `value` (`phase-00…md:79`). The spec now passes defaults and keeps the prompt draft in local state, so a flip never sends it. A save runs after its `set` lands. A test pins the flip-during-draft case.
- Reconciler — **accept**: Phase 0's walk fails on any unbuilt tab not named in `--allow-unbuilt` (`phase-00…md:102,105`). Phase 5's three tabs are still `nb()` here, so the walk line now passes `--allow-unbuilt billing,balance,about` (ASSUMPTION: plan order).

### Six hats

Six hats report (`.scratch/settings-tabs/SIX-HATS.md`), 2026-10-13, reconciled by the plan reviewer. Cross-spec items (a)–(f) are decided under Implementation Decisions, "Cross-spec decisions".
- Black (c), "Phase 4 assumes plan order" (phase-04:133-134) — **accept**: the plan-order ASSUMPTION is dropped; `--allow-unbuilt` is now every non-legacy tab but `time-tracking` and `messaging`, and Depends on names only Phase 0.
- Black (f), "Phase 4 rejects `cmp`, Phases 1 and 6 depend on it" (phase-04:161) — **accept**: the set now follows this Phase's rejection; the `-nt` mtime lines are replaced by `rm -rf /tmp/settings-shots` before the walk and a `cp` of both PNGs after it (a `cp` would make `-nt` vacuous). This completes Review D3.
- Black (b), key form (phase-04:53) — **accept**, no change: the full href is now the set's form.
- Green, "the switch that saves on flip" (phase-04:65-66) — **partial**: kept (rung 1: the bundle's `HBSwitch` card has no Save; already ASSUMPTION); listed in plan-review Open questions.
- Green, "the prompt Cancel" (phase-04:67-68) — **partial**: kept (rung 1: the bundle's three buttons; already ASSUMPTION; sends nothing); listed in Open questions.
