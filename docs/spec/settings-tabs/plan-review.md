# Plan review — settings-tabs

Plan: `docs/plans/settings-tabs.md` (binding). Specs: `docs/spec/settings-tabs/phase-00` … `phase-06`. Reviewed 2026-10-13 by the plan reviewer after the per-spec adversary reviews (codex) and the six-hats report (`.scratch/settings-tabs/SIX-HATS.md`). Each spec's `## Review` ends with a `### Six hats` subsection; each spec's Implementation Decisions ends with the same "Cross-spec decisions" list (a)–(f), word for word.

## Workstreams

| Wave | Phase | Spec | Depends on |
|---|---|---|---|
| 1 | 0 — shell, tokens, settings blob | `phase-00-shell-tokens-blob.md` | none |
| 2 | 1 — Your Account, Your Preferences | `phase-01-account-preferences.md` | 0 |
| 2 | 2 — Security (organization), Security (personal) | `phase-02-security.md` | 0 |
| 2 | 3 — Role Settings, Sales Settings | `phase-03-roles-sales.md` | 0 |
| 2 | 4 — Time tracking, Messaging settings | `phase-04-time-tracking-messaging.md` | 0 |
| 3 | 5 — Billing, Your Balance, About | `phase-05-billing-balance-about.md` | 0, 1, 2, 3, 4 |
| 4 | 6 — sign-off | `phase-06-sign-off.md` | 0, 1, 2, 3, 4, 5 |

Phase 0 is the critical path: every later Phase needs its parts, hook, route and walk. Wave 2 Phases share three files (`[tab]/page.tsx`, `walk.py`'s `SCENARIOS`, `docs/screenshots/`), each by appending only its own entries, so they land in any order (Cross-spec decision (c)).

## Landing order

One owner per thing two Phases both touch.
- Acceptance shell rules, (a): every Phase. Each block starts with `set -e`; every `! cmd` is written `! cmd || exit 1`.
- `SETTINGS_PANELS`, (b): Phase 0 owns the record, keyed by the full href `"/settings/<tab>"` (plan:154); Phases 1–5 each add only their own entries.
- Landing order and `--allow-unbuilt`, (c): Phase 0 owns the flag. Phases 1–4 land in any order after Phase 0 and pass a fixed list of every non-legacy tab but their own; Phase 0 passes `all`; Phases 5 and 6 pass none.
- Write-list checks, (d): each of Phases 1–4 owns the writes to its own paths and selects them by path; Phase 6 alone asserts the whole Write list (the union).
- PNG sets, (e): only the eleven 1440 `docs/screenshots/settings-<tab>.png` are committed, never a `-390` one. Phase 0 commits all eleven; Phases 1–5 overwrite their own; Phase 6 refreshes all eleven.
- PNG freshness, (f): no `cmp` anywhere. Each committing Acceptance clears `/tmp/settings-shots`, walks, and copies in the same block.
- `NotAppliedYet` part and its sentence: Phase 0. Phases 1, 3 and 4 render it; Phases 2 and 5 do not.
- `SettingsPanel`'s `actions` slot: Phase 0. Phase 3 (+ Add Role) and Phase 4 (Edit / Cancel / Save) use it; no later Phase changes a shared part.
- `--if-*` block: Phase 0. Phase 4 adds one token, `--if-card-bg`.
- Walk (`walk.py`, mocks, report, `SCENARIOS`): Phase 0. Phases 1–4 append their scenarios; Phase 5 adds the Balance scope checks, its mock data and the per-tab Panel-header check; Phase 6 edits nothing.
- `SETTINGS_TABS` in `nav.ts`: Phase 0 (icons, `chatterHidden` on the six Blob tabs); Phase 5 (drops `nb()`, keeps both).
- `NotBuiltYet` removal and the `nav.test.ts` "no notBuilt" case: Phase 5.
- Blob allow-list, `user_settings`, migration, `test_settings_api.py`: Phase 0; no later Phase changes them.
- `docs/settings-parity.md`, the plan-decided `VISUAL GAP:` lines (font, two-column grid and the rest), and `docs/routes.md`'s Settings row: Phase 6.

## Adversary

- Phase 0 (`phase-00`): codex; 6 accepted, 1 partial, 9 rejected; needs-human none.
- Phase 1 (`phase-01`): codex; 9 accepted, 2 partial, 7 rejected, plus 4 reconciler cross-check accepts against Phase 0; needs-human none.
- Phase 2 (`phase-02`): codex; 5 accepted, 1 partial, 8 rejected; needs-human none.
- Phase 3 (`phase-03`): codex; 8 accepted, 3 partial, 3 rejected, plus 1 reconciler accept; needs-human none.
- Phase 4 (`phase-04`): codex; 6 accepted, 2 partial, 6 rejected, plus 2 reconciler accepts; needs-human none.
- Phase 5 (`phase-05`): codex; 3 accepted, 6 partial, 7 rejected; needs-human none.
- Phase 6 (`phase-06`): codex; 7 accepted, 6 partial, 10 rejected, plus 1 reconciler accept; needs-human none.

## Six hats

Lines for the bullets about the set as a whole. Bullets about one spec are reconciled in that spec's `### Six hats`.
- White, "the set follows the plan's cut; nobody has checked one spec against another" — **accept**: this pass is that check. It found the six Blue items, a dangling `docs/routes.md` hand-off (now Phase 6's) and a real account handle in Phase 5's licence URL (removed).
- Red, "each spec is strong alone; the drift shows only side by side" — **accept**: drift is settled once in Cross-spec decisions (a)–(f) and in Landing order.
- Black, "the specs contradict each other" (key, landing order, `cmp`) — **accept**: decided as (b), (c) and (f), word for word in every spec.
- Yellow, "safety rules are consistent" (Load gate, unknown keys kept, one Not applied yet and Not wired wording) — **reject** (no change asked): kept as is.
- Yellow, "the backend stays small" (one table, one route pair, an allow-list) — **reject** (no change asked): kept as is; the Chatter decision adds no route.
- Yellow, "verification is real" (light literals, per-Phase and union Write lists, the consumer gate G18) — **reject** (no change asked): kept; (d) makes the per-Phase checks order-proof.
- Green, "do less in Phases 3–5" (the list as a whole) — **partial**: every feature is kept and listed under Open questions with its basis; none is removed silently.
- Blue, "one reconcile pass across specs before ticketing", items 1–6 — **accept**: (a) through (f).
- Blue, "then add the two-column grid gap, a migration-chain check and one Chatter decision" — **accept**: grid in Phases 0, 1 and 6; `alembic heads` in Phase 0; the six Blob tabs `chatterHidden` in Phases 0 and 5.
- Blue, "then list the features beyond the plan for the human" — **accept**: under Open questions; none needs the human alone, since each is decided by rung 1, 2, 3 or 5 and is cheap to remove.
- Recommendation, "one cross-spec consistency pass before any ticket" — **accept**: done; the Tickets brief binds tickets to Landing order.

## Cut (YAGNI)

- Any consumer or enforcement of stored values (Permission roles, Data scope, Sales attribution, preferences, agency name, auto clock-out, reminder, LLM translation, the prompt): ADR-0008. (Phases 0, 1, 3, 4, 6)
- Per-field routes, a roles table, a role column on `employees`, key validation inside a blob, server-side minutes validation: ADR-0007. (Phases 0, 3, 4)
- Pruning stale hrefs or assignments: ADR-0007 Consequences accept them. (Phase 3)
- Loading "Suisse Int'l" or RobotoRegular, and a logo asset: licensed or no asset; the font is a `VISUAL GAP:`. (Phases 0, 5, 6)
- A dark-theme literal pass or dark screenshot: the dark values are sampled, not measured. (Phases 0, 1)
- Infloww's 5/16 Tab list step below 576px: the strip stays below `md`. (Phase 0)
- Picture upload and Username rename: no endpoint; Not wired. (Phase 1)
- Spanish UI and §3.10 row 2's clone hints (weekly-report day, display mode, platform sync): stored only / not in the plan's field list. (Phase 1)
- 2FA enrollment, enforcement and reset; a sessions list; password change; a real Last login: no route, or `last_seen_at` is the Agency's. (Phase 2)
- Owner/Admin-only access to a Settings tab: Permission roles are Not applied yet. (Phases 2, 4)
- Chatter sign-out from Security (personal): stays in the avatar menu. (Phase 2)
- A Save row, a blob or the Not applied yet note on Security, Billing, Your Balance, About: they store nothing. (Phases 2, 5)
- The "Learn more" link and its `#de6d46` token: hidden until a docs page exists. (Phase 3)
- Infloww's named permissions, the example roles Manager / Chatter / Assistant, role editing on Manage employees, the Sales read/edit box with take-effect time, and Settings / Help center pages in the editor: the plan fixes one radio per page, two built-ins and a form with Save. (Phase 3)
- Time tracking's platform checkboxes, the 36-language picker and AI Copilot settings: not in the plan's Phase 4 Decisions. (Phase 4)
- A walk flow for the Messaging switch: the plan names no write for it; vitest covers it. (Phase 4)
- Payments, invoices, wallet top-up, "Request withdrawal", an agency-wide balance: no backend; the Referral balance is per Creator. (Phase 5)
- The About beta box and build hash: excluded by the plan. (Phase 5)
- A `nav.test.ts` check that every href has a Panel: the walk's per-tab Panel-header check covers it. (Phase 5)
- Removing the `nb` helper or the `NotBuiltYet` component: other routes still use them. (Phase 5)
- Restoring `docs/NEXT_SESSION_SETTINGS_UI.md`: deleted in `b07a433d`; the corrections live in the parity doc. (Phase 6)
- Committing `settings-report.json` or any `-390` PNG; pixel-diffing PNGs against a reference: the plan asks for eleven PNGs and a read-and-record loop. (Phases 0, 6)
- Byte comparison (`cmp`) of PNGs across walks: unobserved stability; freshness holds by construction. (Phases 1, 4, 6; six hats)
- The parity doc's `Graded at` line, the Not wired line-shape regex and the code-count lower bound: moved to a reviewer checklist. (Phase 6; six hats)
- Fixing a red gate in sign-off: the owning Phase's ticket fixes it. (Phase 6)
- The Legacy tabs, `scripts/ui-shots.sh`, the Messages Pro parity doc: out of the effort. (Phases 0, 6)

## Not yet specified

- plan:43, Radii row (`--ui-radius-small` 12px, `--ui-radius-medium` 16px, `--surface-01-radius` 12px): no spec makes them Infloww tokens or uses them. Phase 4's 12px card radius comes from `1cat4`, and Phase 0's radii come from `rxwf7`. Falls to the Visual loop if a Panel shows one.
- plan:44, the `hb-design` type sizes (`--typography-text-body2-base` 14px/1.14, `-body1-base` 16px/1.25, `-heading3-strong` 24px): no spec maps them. Only the font family is a recorded gap, and Phase 0's type tokens come from `rxwf7`.

## Open questions

Every `ASSUMPTION:` across the specs, sharpest first: those that touch stored data, money shown or what every Panel looks like, then layout guesses. Each says what falls if it is wrong.

1. Phase 5: balance amounts are dollars, not cents. If wrong, Your Balance shows figures 100x off, a wrong number on screen.
2. Phase 5: three of the four balance keys (`availableEarnings`, `pendingEarnings`, `withdrawnEarnings`) are named without being observed. If wrong, those three cards stay "—" live; the map changes.
3. Phase 3: Scope values `all` / `subordinates` / `self` and the `sales` key names are coined here. If wrong, the first consumer must migrate stored blobs (ADR-0008 Consequences).
4. Phase 3: new roles start deny-all, scope `self`; built-ins keep editable description and permissions, locked name. If wrong, stored roles carry a policy the human did not intend once a consumer reads them.
5. Phase 3: "one radio per page" is a checkbox drawn as a radio circle. If wrong, the editor needs an allow/deny pair and the stored `permissions` shape may change.
6. Phase 3: "Operations" = every `SIDEBAR` page outside Growth and OF Manager, legacy and footer excluded. If wrong, the editor's tabs and stored hrefs regroup.
7. Phase 3: no role gets Delete. If wrong, a delete path that also removes assignments in the same PUT is added.
8. Phase 3: Submit and the editor's Save commit at once; assignment selects are staged behind their own `SaveRow`. If wrong, the walk's "exactly one PUT" changes.
9. Phase 3: assignments sit in an "Employee roles" section, active Employees only. If wrong, they move to Manage employees.
10. ADR-0008 / Phase 1: every Blob tab shows the Not applied yet note, not only the three the plan names. If wrong, Preferences, Time tracking and Your Account drop the note.
11. Phase 0: "left list 18.75% at 1440" is read as the measured container rule (25% with the app Sidebar open, 18.75% collapsed). If wrong, the container query becomes a viewport media query and every PNG changes.
12. Phase 0: dark slot mapping (canvas, side panel, selected, emphasis → `--if-*` slots) is ours. Dark is the app's default theme. If wrong, every Settings colour in dark changes.
13. Phase 0: the six Blob tabs are `chatterHidden` (rung 3, `nav.ts:10-11`). If wrong, Chatters see six Panels stuck in a failed load (the Load gate still blocks any write).
14. Phase 5: Your Balance is not `chatterHidden` and adds no Relay gate. If wrong, `nav.ts` and a server check change.
15. Cross-spec (c): Phases 1–4 land in any order with fixed `--allow-unbuilt` lists. If wrong (plan order wanted), each list shrinks to the tabs still unbuilt, and walks catch regressions in earlier tabs sooner.
16. Cross-spec (f): PNG byte-stability across walks is unobserved, so no `cmp`. If two walks prove byte-identical, Phase 6 may add a `cmp` gate.
17. Phase 0: migration `20261013_0100`, revision `0065_user_settings`, parent `0064_user_llm_keys`. If another effort lands `0065` first, the `alembic heads` line goes red and the migration is renumbered.
18. Phase 6: Base is `206b58fe^` and no other effort lands on this branch. If wrong, G9–G12 go red on another effort's commits.
19. Phase 6: the parity doc's truth (Not wired completeness, evidence cells) is a reviewer checklist, not a gate. If wrong, a missed `NotWired` control ships unlisted; restore the count gate.
20. Phase 6: `docs/NEXT_SESSION_SETTINGS_UI.md` stays deleted; its §3 replacement is the parity doc's Backend corrections. If wrong, a stub is restored at that path.
21. Phase 6: the walk report is `settings-report.json` with `writes` as `[method, path, body]`. If wrong, step 10's reader is renamed.
22. Phase 6: one walk performs each Phase's action once (390 pass only renders). If wrong, each write's count doubles.
23. Phase 6: Phases 0–5 leave ticket files in `.scratch/settings-tabs/issues/`. If wrong, the glob in step 12 moves.
24. Phase 6: ticket gap lines begin with `VISUAL GAP:`. If wrong, step 12's carry-over grep misses gaps.
25. Phase 6: the plan's own departures (strip, "Desktop app", hidden Learn more, no beta box, Tab area height, unused grid) are `VISUAL GAP:` lines. If wrong, the gap list shrinks to measured differences.
26. Phase 6: the parity table has six columns, keyed by slug, last. If wrong, step 12's awk changes.
27. Phase 6: a red gate is reported, not fixed. If wrong, sign-off tickets get fix rights.
28. Phase 4: defaults `enabled:false`, minutes 60, reminder `false`, translation `false`, prompt `""`. If wrong, an empty blob shows other values.
29. Phase 4: the clock-in reminder is a boolean. If wrong, the `time-tracking` blob shape changes.
30. Phase 4: the Messaging switch saves on flip, around `SaveRow`. If wrong, a Save is added for it (also a beyond-plan feature, below).
31. Phase 4: the prompt card has Cancel. If wrong, Cancel is removed (also below).
32. Phase 4: unmeasured values (`--tc-T-disable` → `--if-input-disabled`, minutes max 999 and 80px width, `--if-card-bg` from `.theme-*`, `--sizing-named-mini` 12px, Panel padding 24px kept, textarea 6 rows with no auto-size, note placement). If wrong, Visual loop diffs.
33. Phase 1: `language` stored as `"en"` / `"es"`, `week_start` lowercase. If wrong, a consumer needs another encoding.
34. Phase 1: empty-blob defaults are the browser's zone, Monday, English. If wrong, other defaults show.
35. Phase 1: a stored zone missing from `Intl` is kept as an extra option. If wrong, stored zones are validated.
36. Phase 1: Agency Name has no length or empty-value check. If wrong, a limit is added.
37. Phase 1: the Agency info picture shows the Agency Name's initials; the avatar is a local initials box; selects are native `<select>` at 448px; each preference is its own row (grid unused, a `VISUAL GAP:`); the † measured values are used. If wrong, Visual loop changes.
38. Phase 1: the test wraps `UserProvider` with `/auth/me` stubbed; the walk interface is Phase 0's. If wrong, the test seam changes.
39. Phase 2 A4: Sign out uses `useUser().logout`, wiping caches and going to `/`. If wrong, Sign out stays on Settings.
40. Phase 2 A5: the roster hides chatter mirrors and greys disabled rows. If wrong, mirrors are listed.
41. Phase 2 A1–A3: table geometry, copy and the session card's Geometry are borrowed, not measured. If wrong, Visual loop changes.
42. Phase 2 A6–A7: the walk interface is Phase 0's; disabled controls are clicked with `force=True`. If wrong, the walk asserts differently.
43. Phase 5: an href with no Panel gives `notFound()` (also below). If wrong, a visible fallback replaces it.
44. Phase 5: the licence link targets the repo `Landing.tsx:207` links (also below). If wrong, the link moves.
45. Phase 5: payouts take `limit=10` with raw `state`; AI Copilot shows only the empty table; invoice columns Invoice / Period / Amount / Status; the logo is a wordmark tile; the `6tj53` / `1dq9x` / About values and the bordered-card geometry are used. If wrong, Visual loop or copy changes.
46. Phase 0: the ✕ falls back to `/` with no history. If wrong, another target.
47. Phase 0: below `md` the page scrolls and the strip keeps its classes. If wrong, a fixed-height phone layout.
48. Phase 0: ✕ is a 16px lucide `X` in `--if-fg-3`; row icons are 20px with the listed lucide names; `FieldInput` is 32px high and the switch 44×22px; the Panel header uses the `SETTINGS_TABS` label. If wrong, Visual loop changes.
49. Phase 0: `NotAppliedYet` is a Panel part though the plan's list omits it. If wrong, Phases inline the sentence.
50. Phase 0: `--allow-unbuilt` takes a list; the 390 PNG carries a `-390` suffix. If wrong, the flag or the name changes.
51. Phase 0: the blob store has no read cache or polling. If wrong, a Panel needing live updates adds one.
52. Phase 3: unmeasured `1r0jx` modal and editor values, modal titles, "No role", "Opt in to chatters", "General", the 12px note line. If wrong, Visual loop changes.

Features beyond the plan's Decisions (six hats Green), kept and flagged, none removed:
- Phase 3, Edit on built-in roles (name locked): plan:225 gives every row "Edit" and protects built-ins only from deletion (rung 2). If unwanted, Edit is hidden on Owner and Admin.
- Phase 3, Retry on a failed load: the house `RetryLoad` (`StickySaveBar.tsx:204`, rung 3). If unwanted, the gate note alone remains.
- Phase 3, duplicate-name validation (case-insensitive) on Submit: rung 5. It never writes. If unwanted, Submit allows duplicates.
- Phase 4, the Messaging switch saves on flip: rung 1, the bundle's switch card has no Save. If unwanted, add a Save.
- Phase 4, the prompt card's Cancel: rung 1, the bundle's three buttons. If unwanted, remove it (it sends nothing).
- Phase 5, `notFound()` for an href with no Panel: rung 5, once plan:286 removes `NotBuiltYet`. If unwanted, a visible fallback.
- Phase 5, the external licence link on GitHub: plan:284-285 asks for a licence link (rung 2), with the target from `Landing.tsx:207` (rung 3). If unwanted, link a local copy.

## Needs the human

- Phase 0: none.
- Phase 1: none.
- Phase 2: none.
- Phase 3: none.
- Phase 4: none.
- Phase 5: none.
- Phase 6: none.
