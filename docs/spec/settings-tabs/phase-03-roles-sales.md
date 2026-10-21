# Phase 03 — Role Settings, Sales Settings

**Objective.** `/settings/roles` and `/settings/sales` render Infloww-shaped Panels that read and write the `roles` and `sales` Settings blobs, with Permission roles, Data scope, per-Employee assignment and Sales attribution all saved and marked Not applied yet.

## Measured gap table

Ground truth is the plan's table (rung 1, Dashboard bundle `index.9fc9db54.css`, re-grepped this run). Rows marked `ASSUMPTION` are bundle values the plan's table does not carry.

| Ground-truth selector → value | Ours today (`file:line`) | Gap | Change |
|---|---|---|---|
| `._about-header_rxwf7_9` (and `._role-header_1r0jx_36`, same values) → Panel header 48px, margin 0 24px, bottom border `--tc-L1`, title 16px/500 | `app/app/settings/[tab]/page.tsx:16` renders `NotBuiltYet` for both hrefs | no Panel | Both tabs use Phase 0's `SettingsPanel` header; "+ Add Role" sits at its right end (bundle: `role-header` children are the title and `AddRole`) |
| `._personal-info-wrap_rxwf7_132` / `._title_rxwf7_137` / `._table-wrap_rxwf7_143` → body padding 24px; section title 14px/500 `--tc-T1`, pb 16px; section gap 40px | `page.tsx:16` | none | `Section` for "Roles", "Employee roles", the Sales toggles and "Earnings types and attribution rules" |
| `._personal-item_rxwf7_146`, `._personal-item-title_rxwf7_155`, `._personal-input_rxwf7_237` → field mb 30px, label 14px/400 `--tc-T3` mb 8px, input 448px radius 8px border `--tc-L1` | none (no modal exists) | none | `Field` for "Role Name" and "Description" in the role modal |
| `._switch-theme_rxwf7_303` → toggle row 72px, padding 0 16px, radius 4px, border `--tc-L1`; title 14px, desc 12px `--tc-T3` | none | none | `ToggleRow` ×3 on Sales |
| `._tab-item_rxwf7_88`, `._tab-item-active_rxwf7_99` → row 64px; active `--tc-M1` on `--tc-M-B` | `app/components/settings/SettingsNav.tsx:28` (`h-10`, `bg-bg-elev-1`) | Phase 0 fixes | none here; the walk asserts it on both hrefs |
| `:root` → `--tc-M1` #3467ff, `--tc-L1` #e6e6e6, `--tc-D1` #ff7c71, `--tc-T3` #999999 | none | none | checked radios, the Permission editor's active tab and Submit read `--if-accent`; table borders `--if-line`; the not-applied note `--if-fg-3` |
| `._learn-more_1t0kc_5` → `#de6d46`, 14px strong, margin-left 8px | none | none | not rendered: the plan hides it until a docs page exists |
| `body{font-family:"RobotoRegular",…}` / Suisse Int'l | `--font-sans` | font | none: recorded visual gap (Constraints) |

ASSUMPTION: `._edit-modal-wrap_1r0jx_49` padding 20px 20px 1px; `._tabble-content_1r0jx_77` margin 24px 24px 0; `._table-title_1r0jx_83` 16px/500 `--tc-T1` mb 16px; `._table-wrap_1r0jx_89` mb 32px. These are used for the Permission editor's group titles and blocks and the modal body because the plan's table has no row for them. Overturned if a Phase 0 token or the plan's table names other values.

## Problem Statement
An Agency opening Role Settings or Sales Settings sees a "not built yet" placeholder. It cannot define who may see which pages, give an Employee a Permission role, or record how sales are credited, as it could in Infloww.

## Solution
Role Settings lists the Permission roles: Owner and Admin are built in, and the Agency adds its own; every role offers "Edit" and "Set Permissions", and no role is deleted. The Permission editor lists every app page under "Operations", "Growth" and "OF Manager", one radio per page, plus a Data scope. Every Employee gets a role select. Sales Settings has three toggles and the attribution radios. Both Panels save to their Settings blob and say "Saved for your organization; not applied yet."

## User Stories
1. As an Agency owner, I want `/settings/roles` to render the Role Settings Panel, not a placeholder, so that the tab works.
2. As an Agency owner, I want a Roles table with columns Name / Description / Operations (plan wording), so that I can see every Permission role at a glance.
3. As an Agency owner, I want Owner and Admin listed first even when nothing is stored, so that the built-ins always exist.
4. As an Agency owner, I want Owner and Admin's names locked and no row to offer Delete, so that I cannot remove or rename the built-ins.
5. As an Agency owner, I want "+ Add Role" to open a modal with "Role Name", "Description" and "Submit", so that I can create a role.
6. As an Agency owner, I want Submit disabled while Role Name is blank or repeats an existing name (case-insensitive), so that roles stay distinct.
7. As an Agency owner, I want Submit to save the whole `roles` blob once and close the modal, so that the new role persists.
8. As an Agency owner, I want "Edit" to open the same modal pre-filled, so that I can change a custom role's name or any role's description.
9. As an Agency owner, I want the Operations column to offer exactly "Edit" and "Set Permissions", so that no role and no assignment is ever destroyed by this Panel.
10. As an Agency owner, I want "Set Permissions" to replace the list with the Permission editor and a "Back", so that I edit one role at a time as in Infloww.
11. As an Agency owner, I want the editor's tabs "Operations" / "Growth" / "OF Manager", so that pages are grouped as in Infloww.
12. As an Agency owner, I want the editor's pages to be derived from the `SIDEBAR` groups, so that a nav change shows up without editing the editor.
13. As an Agency owner, I want one radio per page that I can switch on and off, so that I grant or deny each page.
14. As an Agency owner, I want a Data scope of "All data" / "Self and subordinates" / "Data about self", so that I set each role's reach.
15. As an Agency owner, I want the editor's "Save" to send the whole `roles` blob with every derived page keyed by href, so that the stored permissions are explicit.
16. As an Agency owner, I want "Back" without Save to discard the editor's changes and send nothing, so that browsing is safe.
17. As an Agency owner, I want an "Employee roles" section listing my active Employees, each with a role select, so that I can give each one a Permission role.
18. As an Agency owner, I want the selects staged and committed by one Save, so that a run of changes is one write.
19. As an Agency owner, I want an Employee with no assignment to show "No role", so that unassigned is visible.
20. As an Agency owner, I want assignments for Employees not listed (disabled, deleted) kept on save, so that saving never silently drops data.
21. As an Agency owner, I want Submit, both Saves and the selects disabled until the blob loads, with Retry on a failed load, so that a failed load can never send a sparse blob (Load gate).
22. As an Agency owner, I want `/settings/sales` to render three toggles: "Exclude welcome messages", "Exclude the 20% OnlyFans fee", "Multiple employees per shift".
23. As an Agency owner, I want Messages attribution as radios Shift schedule / Message sender / Converters.
24. As an Agency owner, I want Posts and Tips attribution as radios Shift schedule / Converters.
25. As an Agency owner, I want Subscriptions, Streams & Referrals shown as Shift schedule with a chatter opt-in checkbox, so that it matches Infloww's rule.
26. As an Agency owner, I want one Save that sends the full `sales` object, so that no key is lost.
27. As an Agency owner, I want both Panels to say "Saved for your organization; not applied yet.", so that I do not think roles or attribution are enforced (ADR-0008).
28. As an Agency owner, I want no "Learn more" link while no docs page exists, so that nothing points nowhere.
29. As a phone user, I want both Panels usable at 390px with no horizontal overflow, so that Settings works on a phone.
30. As a maintainer, I want the walk to record exactly the Phase 3 Write list, so that the wiring is proven on the wire.

## Implementation Decisions
- **Owns.** `RoleSettingsTab`, `PermissionEditor`, `SalesSettingsTab` (new, under the settings components), their entries in `SETTINGS_PANELS` (keyed `"/settings/roles"` and `"/settings/sales"`), the Phase 3 scenarios in the Settings walk, and `docs/screenshots/settings-roles.png` / `settings-sales.png`. It renders Phase 0's `NotAppliedYet` Panel part; it adds no part of its own.
- **Interfaces.**
  - `RoleSettingsTab()` and `SalesSettingsTab()` take no props: each reads its blob through `useSettingsBlob("roles" | "sales")` and the roster through `useRoster({ includeDisabled: false })`.
  - `PermissionEditor({ role, onSave, onBack, canSave })` edits one Permission role's `permissions` and `scope`.
  - `permissionTabs(sidebar = SIDEBAR)` is a pure export returning `[{ tab: "Operations" | "Growth" | "OF Manager", groups: [{ title, pages: [{ label, href }] }] }]`. "Growth" and "OF Manager" are those `SIDEBAR` groups' children. "Operations" is every other non-divider, non-`legacy` `SIDEBAR` link, top-level links first under the title "General", then each remaining group under its own label, in nav order.
- **Schema.** None. The blobs live in Phase 0's `user_settings` (ADR-0007). Shapes, the contract between Panel and tests:
  ```ts
  type Scope = "all" | "subordinates" | "self";
  interface PermissionRole { id: string; name: string; description: string; permissions: Record<string, boolean>; scope: Scope }
  interface RolesBlob { roles: PermissionRole[]; assignments: Record<string, string> } // employee_id -> role id
  interface SalesBlob { exclude_welcome: boolean; exclude_of_fee: boolean; multi_employee_shift: boolean;
    attribution: { messages: "shift" | "sender" | "converters"; posts_tips: "shift" | "converters"; subscriptions_chatter_opt_in: boolean } }
  ```
- **Contracts.** `GET /admin/settings/roles|sales` → `{tab, config}`; `PUT` sends the full object. No other route: no roles column, no change to `/admin/employees`.
- Built-ins: id `owner` and `admin`, name locked, every derived href `true`, scope `all`; they are prepended on load when missing. A new role starts with every href `false` and scope `self`. Its id is `role-` plus a base-36 timestamp.
- A save spreads the loaded blob first, so unknown keys and stale hrefs survive (ADR-0007 Consequences).
- Defaults when `sales` is `{}`: all toggles `false`, both radios `shift`, opt-in `false`.
- The table, select and radios are plain elements styled with `--if-*`, the modal is `@radix-ui/react-dialog`, and the Permission editor's tabs are buttons.
ASSUMPTION: "Operations" = every `SIDEBAR` page outside the Growth and OF Manager groups, legacy and `SIDEBAR_FOOTER` excluded (rung 5); overturned if the human or a bundle `menuCodes` map assigns pages otherwise.
ASSUMPTION: "one radio per page" is a checkbox drawn as a radio circle, because a lone native radio cannot be cleared (rung 5); overturned if the human wants an allow/deny radio pair.
ASSUMPTION: Scope values `all` / `subordinates` / `self` and the `sales` key names other than `attribution.messages == "sender"` are coined here (rung 6); overturned by a later consumer's contract.
ASSUMPTION: Built-ins keep editable description and permissions, locked name; new roles start deny-all with scope `self` (rung 4: least privilege is cheaper to undo); overturned if the human wants Owner fully locked.
ASSUMPTION: No role gets "Delete" (rung 2: the plan's Operations column lists only "Edit" and "Set Permissions"; rung 4: deleting a role would also have to delete its assignments). A mistaken custom role is renamed via Edit. Overturned if the human wants custom-role deletion, in which case it removes the role's assignments in the same PUT; the bundle has `._open-delete-role_1r0jx_52`.
ASSUMPTION: Submit and the editor's Save commit at once; the assignment selects are staged behind their own `SaveRow` (rung 3 house Save pattern, rung 1 Infloww modal Submit); overturned if the walk's "exactly one PUT" needs another flow.
ASSUMPTION: Assignments sit in an "Employee roles" Panel section of Role Settings, active Employees only (plan says "each employee's role is a select", not where); overturned if the human wants them on Manage employees.
ASSUMPTION: Modal titles "Add Role" / "Edit Role", the option "No role", the opt-in label "Opt in to chatters" and the "General" group title are not measured (rung 6).
ASSUMPTION: the not-applied note renders as one 12px `--if-fg-3` line under each Panel header (rung 5).

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
- Seams: the three components through `renderWithProviders` (`app/test-utils.tsx:30`), relay mocked at `fetch`, asserting the PUT bodies and the DOM. Plus the Settings walk on the wire.
- `RoleSettingsTab.test.tsx` covers:
  - empty blob → Owner and Admin listed first, no row has a Delete action, each row has exactly "Edit" and "Set Permissions";
  - "Saved for your organization; not applied yet." is in the document;
  - add "Alpha Role" → one PUT with all three roles;
  - duplicate name (case-insensitive) keeps Submit disabled;
  - Edit on a stored custom role → modal pre-filled → change its name and description → Submit → one PUT where that role keeps its id and carries the new values; Edit on Owner → Role Name disabled;
  - Set Permissions → toggle → Save → the PUT carries the href `false` and the scope;
  - stored blob with an assignment for an Employee id absent from the active roster and an unknown top-level key → assign "Beta Two" → Save → the PUT holds Beta Two's assignment, the absent Employee's assignment and the unknown key;
  - failed load → "+ Add Role", the assignment selects and Save are disabled, "Retry" is shown, and no PUT goes on the wire; Retry with a good response enables them.
- `PermissionEditor.test.tsx`: tab labels are exactly the three; asserted against hrefs collected from `SIDEBAR` in the test itself (not through `permissionTabs`): the union of the three tabs' hrefs is every non-divider, non-legacy `SIDEBAR` href, each exactly once, and Growth and OF Manager hold exactly those groups' child hrefs; a fake `SIDEBAR` with one added Growth child and one added top-level link shows them under Growth and under Operations' "General"; Back sends nothing.
- `SalesSettingsTab.test.tsx`: the radio matrix (3 / 2 / opt-in), each toggle, the not-applied sentence, and a Save sending every key with `attribution.messages == "sender"` after clicking Message sender.
- Settings walk: this Phase appends to Phase 0's `SCENARIOS` a roles scenario (add "Synthetic Role", Submit, then reload `/settings/roles` and require the "Synthetic Role" row, which proves the round trip through the mock's stored body) and a sales scenario (click "Message sender", Save). Both require the not-applied sentence on the page.
- Prior art: `app/lib/nav.test.ts:77-82` (derive from `SIDEBAR`), `app/components/settings/stickySave.test.tsx` (Load gate), `scripts/of-mirror-check/writes.py` (Write list).
- Visual loop: Read both PNGs, diff against the gap table, fix and re-run up to three rounds; leftovers become `VISUAL GAP:` lines in the ticket.

## Acceptance
```sh
set -eu
cd "$(git rev-parse --show-toplevel)"
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run components/settings/RoleSettingsTab.test.tsx components/settings/PermissionEditor.test.tsx components/settings/SalesSettingsTab.test.tsx
./venv/bin/python service/tests/test_settings_api.py
(cd app && exec npx next dev --webpack -p 3091) >/tmp/settings-dev.log 2>&1 &
DEV=$!; trap 'kill $DEV 2>/dev/null || true' EXIT
for i in $(seq 90); do curl -sf -o /dev/null http://localhost:3091/settings/roles && break; sleep 2; done
rm -rf /tmp/settings-shots
python3 -I scripts/settings-check/walk.py --allow-unbuilt account,preferences,security-org,security-personal,billing,balance,time-tracking,messaging,about
python3 -I - <<'PY'
import json
r = json.load(open("/tmp/settings-shots/settings-report.json"))
w = [tuple(x) for x in r["writes"]]
roles = [x for x in w if x[1] == "/admin/settings/roles"]
assert len(roles) == 1 and roles[0][0] == "PUT", roles
assert sorted(x["name"] for x in roles[0][2]["roles"]) == ["Admin", "Owner", "Synthetic Role"], roles
sales = [x for x in w if x[1] == "/admin/settings/sales"]
assert len(sales) == 1 and sales[0][0] == "PUT" and sales[0][2]["attribution"]["messages"] == "sender", sales
PY
cp /tmp/settings-shots/settings-roles.png /tmp/settings-shots/settings-sales.png docs/screenshots/
test -s docs/screenshots/settings-roles.png && test -s docs/screenshots/settings-sales.png
scripts/settings-check/export-check.sh   # the plan's throwaway-tree recipe, scoped to lines this effort added (hits inherited from before the effort base are reported, not failed)
# manual: the implementer has Read both PNGs and recorded every remaining VISUAL GAP: in the ticket
```
Phase 0's spec (`phase-00-shell-tokens-blob.md:105-106`) stores the Write list as `writes`, a list of `[method, path, json body]`, and gives `walk.py` `--allow-unbuilt <tab>,…`.
The walk allows exactly the non-Phase-3 non-legacy tabs as unbuilt, a fixed list never edited at landing, so the line passes whatever order Phases 1, 2 and 4 land in; the Python check selects writes by path (Cross-spec decisions (c), (d)).

## Depends on
Phase 0 provides: `SettingsPanel` (header, `Section`, `Field`, `ToggleRow`, `NotWired`, `NotAppliedYet`); `useSettingsBlob` with the `configLoaded` gate wired to `SaveRow`; `SETTINGS_PANELS`; the `--if-*` tokens; `user_settings` and `/admin/settings/{tab}` with `roles` and `sales` allowed; `test_settings_api.py`; `walk.py` with the `/admin/employees` and settings mocks, `SCENARIOS` and `--allow-unbuilt`.
Existing code (not Phase 0): `SaveRow` (`app/components/settings/StickySaveBar.tsx:218`); `useRoster` (`app/hooks/useRoster.ts:44`, `includeDisabled` option, chatter mirrors excluded by default).

## Out of Scope
- Enforcing Permission roles or Data scope, and crediting sales by attribution: ADR-0008, Not applied yet.
- A roles table or a role column on `employees`: ADR-0007.
- The "Learn more" link and its `#de6d46` token: hidden until a docs page exists (plan). Not built at all: YAGNI.
- Infloww's named permissions ("View media statistics", Spending power, Chargeback visibility, Split Inbox, AI Copilot): the plan fixes one radio per page.
- Example roles Manager / Chatter / Assistant: the plan builds in only Owner and Admin.
- Role editing on Manage employees ("Batch edit roles", the Role column, the Add employee Role field): §3.8, not this plan.
- Sales' read/edit box, take-effect time and cool-down seen in the bundle (`SalesBoxComponent`): the plan asks for a form with Save.
- Pruning stale hrefs or assignments: ADR-0007 Consequences accept them.
- Settings and Help center pages in the editor: `SIDEBAR_FOOTER` is not a `SIDEBAR` group.

## Further Notes
- Every ASSUMPTION: above is decided. Nothing is open.
- Built-ins stay listed even if a stored blob omits them, so a corrupted blob cannot lose them (rung 4).
- The existing manual sale attribution (`service/server.py:10394`, `GET /admin/ingest/transactions/sales-needing-attribution`, and the assign endpoint after it) is untouched and does not read the `sales` blob; Sales Settings stays Not applied yet (ADR-0008).

## Review
Reviewer: codex (blind call, then draft call), 2026-10-13. The workspace lacked `app/hooks/`, so claims about `useRoster` were checked against this tree.

Blind call:
- B1 Alternatives: build enforced roles and attribution, or disable the inert controls. **reject**: the plan's Constraints (`docs/plans/settings-tabs.md:86-87`) and ADR-0008 fix "stored, not applied". This is a constraint, not a choice.
- B2 The plan does not map Infloww's named permissions to hrefs, and `SIDEBAR` has no "Operations" group. **reject**: already decided. Named permissions are Out of Scope because the plan fixes one radio per page, and "Operations" is the flagged derivation ASSUMPTION in Implementation Decisions.
- B3 Role lifecycle is undefined: editable built-ins, deletion, duplicates, which Employees can be assigned. **reject**: already covered by stories 4, 6, 9, 17 and 20 and the Built-ins decision. Deletion was then removed (see D3).
- B4 The Sales fields have no defined meaning, defaults or opt-in key. **partial**: defaults and the key `subscriptions_chatter_opt_in` are already in Schema and "Defaults when `sales` is `{}`". Under ADR-0008 the meaning belongs to a future consumer, and that ASSUMPTION already says so.
- B5 Test the Panel ↔ blob round trip, because a mock alone proves no persistence. **accept**: the walk's roles scenario now reloads `/settings/roles` and requires "Synthetic Role" from the mock's stored body. `test_settings_api.py` (round trip, user isolation) is already in Acceptance.
- B6 The premise "no sales attribution" is too broad, since manual attribution exists (`service/server.py:10394`). **partial**: the spec never claimed there was none. Further Notes now records that the endpoint is untouched and does not read the `sales` blob (grep: no reader of `settings/roles|sales` in `service/*.py`).

Draft call:
- D1 The "not applied yet" sentence has no acceptance check. **accept**: both component tests and both walk scenarios now require it. The Panel also uses Phase 0's `NotAppliedYet` part (`phase-00-shell-tokens-blob.md:77,100`) instead of coining `NotAppliedNote`.
- D2 Depends on falsely lists `useRoster` as a Phase 0 deliverable. **partial**: the hook already exists (`app/hooks/useRoster.ts:44`, with an `includeDisabled` option), so nobody needs to own it. Depends on now names it as existing code.
- D2b `SaveRow` is existing code, not a Phase 0 artifact. **accept**: Depends on now cites `StickySaveBar.tsx:218`. Phase 0 supplies the `configLoaded` gate wiring.
- D3 Deleting custom roles, and their assignments, is scope the plan never asked for. **accept**: the plan's Operations column is "Edit", "Set Permissions" (`docs/plans/settings-tabs.md:225`), and rung 4 favours not destroying assignment data. Story 9, the Solution, the gap table and the Delete ASSUMPTION are rewritten, and the test asserts that no row offers Delete.
- D4 Story 8 (Edit) has no test. **accept**: added a test for the pre-filled Edit (name and description change, id kept, one PUT) and for the Owner name being locked.
- D5 The preservation test does not prove that an absent Employee's assignment survives. **accept**: the test now seeds an assignment for an Employee id absent from the active roster, plus an unknown top-level key, and asserts both are in the PUT.
- D6 The Load gate test checks only "no PUT". **accept**: it now asserts that "+ Add Role", the selects and Save are disabled, that "Retry" is shown, and that a successful Retry re-enables them.
- D7 Comparing the editor to `permissionTabs(SIDEBAR)` is circular. **accept**: the test now collects hrefs from `SIDEBAR` itself, asserts each appears exactly once and that the Growth and OF Manager groups match exactly, and adds a fake top-level link that must land under Operations' "General".

Own finding during reconcile:
- R1 The Acceptance ran `walk.py` with no flags, so it would fail on any other tab still unbuilt at landing (`phase-00-shell-tokens-blob.md:101,104`). **accept**: it now passes `--allow-unbuilt` with every non-Phase-3 tab, following the `phase-02-security.md:78,106` precedent.

needs-human: none.

### Six hats

Six hats report (`.scratch/settings-tabs/SIX-HATS.md`), 2026-10-13, reconciled by the plan reviewer. Cross-spec items (a)–(f) are decided under Implementation Decisions, "Cross-spec decisions".
- Black (c), "any-order lists edited at landing" (phase-03:135) — **accept**: the list is fixed and never edited; the local ASSUMPTION is replaced by Cross-spec decision (c).
- Black (b), key form — **accept**: Owns names the keys `"/settings/roles"` and `"/settings/sales"`.
- Blue 4, "Phase 3 filters writes by path" (phase-03:123) — **accept**, no change: this block is the model for Cross-spec decision (d).
- Black (f) — **accept** (knock-on): the block clears `/tmp/settings-shots` before the walk; its `cp` already runs in the same block.
- Green, "Edit modal for built-ins beyond the plan" (phase-03:34) — **partial**: kept; plan:225 gives every row "Edit" and protects built-ins only from deletion, so Edit on Owner and Admin (name locked) is rung 2. Listed in plan-review Open questions.
- Green, "Retry on a failed load beyond the plan" (phase-03:49) — **partial**: kept; it is the house `RetryLoad` (`app/components/settings/StickySaveBar.tsx:204`), rung 3, no new part. Listed in Open questions.
- Green, "duplicate-name validation beyond the plan" (phase-03:34) — **partial**: kept (rung 5: it only disables Submit and never writes, so it is cheap to remove); listed in Open questions.
- Green, "drop the any-order list" (phase-03:118) — **reject**: Cross-spec decision (c) (rung 4).
