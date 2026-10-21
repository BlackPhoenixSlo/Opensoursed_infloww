# Phase 02 — Security (organization), Security (personal)

**Objective.** `/settings/security-org` and `/settings/security-personal` render Infloww-shaped Panels built from Phase 0's `SettingsPanel` parts: the org Panel lists the Agency's Employees with a Not wired 2FA switch, the personal Panel shows the current session and signs out through `POST /auth/logout`, and neither Panel stores anything.

## Gap table (measured)

Ground truth is the plan's table (Dashboard bundle, CSS module `rxwf7`), re-read with `grep -o` on `index.9fc9db54.css`. A `grep -oE '_(secur|2fa|tfa|session|device)…_rxwf7_'` finds no security-specific selector in the module, so every security-only value below is an `ASSUMPTION:` (see Further Notes).

| Ground-truth selector / value | Ours today (`file:line`) | Gap | Change |
|---|---|---|---|
| `._account-wrap_rxwf7_118 ._header_rxwf7_121`: 48px, margin 0 24px, bottom border `--tc-L1`, 16px/500 | `app/app/settings/[tab]/page.tsx:16` renders `NotBuiltYet` for both hrefs | no Panel | Phase 0 Panel header titled "Security (organization)" / "Security (personal)" (labels from `app/lib/nav.ts:161-162`) |
| `._personal-info-wrap_rxwf7_132` padding 24px; `._title_rxwf7_137` 14px/500 `--tc-T1`, padding-bottom 16px; `._table-wrap_rxwf7_143` gap 40px | none | no sections | Phase 0 `Section` for every group below |
| `._switch-theme_rxwf7_303`: height 72px, padding 0 16px, radius 4px, 1px `--tc-L1`; `._title_rxwf7_137` 14px `--tc-T1`; `._desc_rxwf7_321` 12px `--tc-T3` | none | no 2FA switch | Phase 0 `ToggleRow` "Two-factor authentication", its switch wrapped in `NotWired` |
| `._personal-item_rxwf7_146` margin-bottom 30px; `._personal-item-title_rxwf7_155` 14px/400 `--tc-T3`, margin-bottom 8px | none | no username field | Phase 0 `Field` "Username" in the Current session card |
| `._disabled-input_rxwf7_242`: 448px, border `--tc-L1`, bg `--tc-B-th`, text `--tc-T1` | none | — | the username renders as a read-only 448px input |
| `._translation-item_rxwf7_369`: 1px `--tc-L1`, radius 8px, margin 24px, padding 24px; title 14px/600; tip 12px/20px `--tc-T2` | none | no card | Current session card takes this geometry (ASSUMPTION A3) |
| Colours `--tc-*` (light) / §1.4 [PAL] (dark) | Phase 0 `--if-*` block | — | both Panels read only `--if-*` tokens (ADR-0009) |
| Employee roster: `GET /admin/employees` (`service/employees.py:95`) id, display_name, is_active, no 2FA, no last login | `app/hooks/useRoster.ts:44` (same cache as `EmployeeContext.tsx:80`) | no table | Employee table: Name / 2FA status / Last login / Operations |
| Disabled Employee greyed | `app/components/settings/EmployeesTab.tsx:140` `opacity-60` | — | same treatment (ASSUMPTION A5) |
| `POST /auth/logout` clears every principal cookie (`service/auth.py:555-560`) | `app/contexts/UserContext.tsx:308-320` `logout()` posts `{}`, wipes caches, `location.replace("/")`; used by `app/components/shell/TopBar.tsx:102` | no Settings caller | "Sign out" calls `useUser().logout` |
| Font `RobotoRegular` / Suisse Int'l | `--font-sans` | licensed font | VISUAL GAP: font (plan Constraints) |

## Problem Statement
An Agency opening either Security tab sees "Not built yet". It cannot see which Employees it has from the security angle, cannot tell that Inflowwww has no 2FA, and has no Settings-side way to end its own session.

## Solution
Security (organization) shows Infloww's "Two-factor authentication" switch, disabled with the tooltip "not wired", above an Employees table that lists the Agency's roster with "—" for 2FA status and Last login and a Not wired "Reset". Security (personal) shows a Current session card with the signed-in username and a working "Sign out", plus Not wired "Change password" and "Enable 2FA". Neither Panel saves anything, so neither has a Save row or the "not applied yet" note.

## User Stories
1. As an Agency owner, I want `/settings/security-org` to render a real Panel instead of `NotBuiltYet`, so that the tab matches Infloww's Settings.
2. As an Agency owner, I want a Panel header reading "Security (organization)" at Infloww's 48px Geometry, so that the tab looks like Infloww's.
3. As an Agency owner, I want a "Two-factor authentication" toggle row (72px, title and description) that is disabled with the tooltip "not wired", so that I can see Infloww's control and know Inflowwww cannot enforce 2FA.
4. As an Agency owner, I want clicking that toggle to change nothing and send nothing, so that a security setting never claims a protection that does not exist (ADR-0008).
5. As an Agency owner, I want an Employees table with columns Name / 2FA status / Last login / Operations, filled from `GET /admin/employees`, so that I see the same roster as everywhere else in the app.
6. As an Agency owner, I want 2FA status and Last login to read "—", so that the table never invents data the Relay does not have.
7. As an Agency owner, I want each row's "Reset" to be Not wired, so that I am not misled into thinking a 2FA reset happened.
8. As an Agency owner, I want disabled Employees greyed (and marked `aria-disabled`), so that I can tell them from active ones, as on the Employees page.
9. As an Agency owner, I want an empty roster to show a single "No employees" row and a failed roster load to show an error line, so that the table never silently looks empty.
10. As an Agency owner, I want `/settings/security-personal` to render a Panel headed "Security (personal)", so that the tab is built.
11. As an Agency owner, I want a "Current session" card showing my username from `/auth/me` in a read-only 448px field, so that I know which login I am looking at.
12. As an Agency owner, I want "Sign out" in that card to end my session through `POST /auth/logout` and land me on `/`, exactly as the avatar menu does, so that both exits behave the same.
13. As an Agency owner, I want "Change password" and "Enable 2FA" shown disabled with the tooltip "not wired", so that I see Infloww's controls without a fake success.
14. As an Agency owner, I want neither Security tab to read or write `/admin/settings/{tab}`, so that nothing is stored for tabs that are not Blob tabs.
15. As an Agency owner on a phone (390x844), I want both Panels to fit the strip layout without horizontal page overflow, the Employees table scrolling inside its own box.
16. As an Agency owner in dark theme, I want both Panels to take the dark `--if-*` palette, so that they match the rest of Settings.
17. As the implementer, I want both Panels registered in `SETTINGS_PANELS` under `"/settings/security-org"` and `"/settings/security-personal"`, so that `[tab]/page.tsx` renders them and every other unmapped tab still shows `NotBuiltYet`.
18. As the implementer, I want the Settings walk to assert the org table names, an empty Write list on the org tab, and exactly `POST /auth/logout {}` on the personal tab, so that the Phase is accepted on observed requests.
19. As a reviewer, I want `docs/screenshots/settings-security-org.png` and `settings-security-personal.png` (synthetic data) committed after the Visual loop, so that the result is on record.

## Implementation Decisions
- **Owns.** New `SecurityOrgTab` and `SecurityPersonalTab` under `app/components/settings/`; their two `SETTINGS_PANELS` entries; their vitest files; the security entries appended to the Settings walk's `SCENARIOS` list (Phase 0's interface); the two committed PNGs.
- **Interfaces.** Each Panel is a prop-less client component. `SecurityOrgTab` reads the roster via `useRoster()` (defaults: disabled rows included, chatter mirrors excluded). `SecurityPersonalTab` reads `useUser().user.username` and calls `useUser().logout`. `SETTINGS_PANELS` gains two keys, `"/settings/security-org"` and `"/settings/security-personal"` (full hrefs, Cross-spec decision (b)); nothing else in it changes.
- **Schema.** None — no Blob tab for either (plan Phase 2); the `user_settings` allow-list stays at the six Blob tabs, so `/admin/settings/security-*` stays 404.
- **Contracts.** Reads: `GET /auth/me`, `GET /admin/employees?include_disabled=true`. One write: `POST /auth/logout` with body `{}` (`UserContext.tsx:309`), response ignored (best effort), then `location.replace("/")`. No other non-GET request from either Panel.
- Org Panel: `Section` (no title) holding the `ToggleRow` "Two-factor authentication" with description "Require every employee in your organization to use two-factor authentication" (A2); its switch shows off, is wrapped in `NotWired`, and has no state or handler. Then `Section` "Employees" with the four-column table: Name = color dot + `display_name`; 2FA status "—"; Last login "—"; Operations = `NotWired` "Reset". Rows follow the roster order (`created_at`).
- Personal Panel: `Section` "Current session" holding the bordered card (A3): `Field` "Username" (read-only input, value `username`, "—" if absent) and a "Sign out" button (house `Button`, A4) that disables itself while the POST is in flight. Then `Section` "Password" with `NotWired` "Change password", and `Section` "Two-factor authentication" with `NotWired` "Enable 2FA".
- Under impersonation `/auth/me` returns the impersonated user (`auth.py:567-572`) and the card shows that name; "Sign out" clears every principal cookie, the same as the avatar menu (rung 2/1: plan + `auth.py:557-560`).
- No `SaveRow`, no `useSettingsBlob`, no "Saved for your organization; not applied yet." note: these Panels store nothing (ADR-0008 applies the note to Blob tabs only).
- The Employees table sits in an `overflow-x-auto` box; the Panels add no fixed width beyond Phase 0's parts.

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
- **Seam 1 — `SecurityOrgTab.test.tsx`** (`renderWithProviders` from `app/test-utils.tsx:30` wrapping `UserProvider`, relay mocked at `fetch`; `/auth/me` → synthetic user, `/admin/employees` → "Alpha One", "Beta Two", "Gamma Three" with Gamma `is_active:false`). Asserts: exactly 3 body rows by name; "—" in both 2FA status and Last login cells; Gamma's row `aria-disabled="true"`; the 2FA switch disabled with tooltip "not wired" and `aria-checked="false"`; the table's parent box carries `overflow-x-auto`; every "Reset" disabled with "not wired"; clicking the switch and a Reset sends no non-GET `fetch` and no request to `/admin/settings/`. Two more cases: `/admin/employees` → `{"employees": []}` renders exactly one body row "No employees"; `/admin/employees` → 400 renders the error line and no body row (400, not 5xx, because `useRoster` retries 5xx, `app/hooks/useRoster.ts:59-63`).
- **Seam 2 — `SecurityPersonalTab.test.tsx`** (same harness, `window.location.replace` stubbed). Asserts: the username from `/auth/me` is shown; "Change password" and "Enable 2FA" disabled with "not wired"; clicking "Sign out" sends exactly one `POST /auth/logout` with body `{}`, calls `location.replace("/")`, and leaves the `queryClient` returned by `renderWithProviders` empty after a seeded `["employees","all"]` entry (proves the click went through `useUser().logout`'s `wipeIdentityCaches`, `UserContext.tsx:139-149,307-320`, not a bare POST); no request to `/admin/settings/`.
- **Seam 3 — Settings walk** (`scripts/settings-check/walk.py`, Phase 0's; this Phase appends `(tab, name, run, want_writes)` entries to its `SCENARIOS`): `security-org` must show "Alpha One", "Beta Two", "Gamma Three"; a forced click on the 2FA switch and on "Reset" leaves the tab's Write list `[]`. `security-personal`: forced clicks on "Change password" and "Enable 2FA" record nothing, then "Sign out" makes the Write list exactly `[("POST", "/auth/logout", {})]`; the mock answers `{"ok": true}`. Sign out runs last for that tab (it ends the session). At 390x844 the Employees table's box has computed `overflow-x: auto` and the document has no horizontal overflow (Phase 0's check), so a clipped table fails. Geometry checks are Phase 0's (64px row, 18.75% list, 48px header, active colour); both tabs pass at 1440x900 and 390x844.
- **Visual loop.** Read `/tmp/settings-shots/settings-security-org.png` and `-security-personal.png`, list diffs against the Gap table rows (position, size, label, order, missing element), fix, re-run walk; at most three rounds, then each remaining diff is a `VISUAL GAP:` line in the ticket. Known up front: VISUAL GAP: font; no Infloww screenshot of either tab exists (plan Ground truth 4), so the comparison is against measured values only.
- Prior art: `app/contexts/UserContext.test.tsx` (UserProvider + fetch mock), `app/components/settings/stickySave.test.tsx`, `scripts/of-mirror-check/writes.py:44,58` (Write list assertion).

## Acceptance
```sh
set -e
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run components/settings/SecurityOrgTab.test.tsx components/settings/SecurityPersonalTab.test.tsx
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
./venv/bin/python service/tests/test_settings_api.py
(cd app && npx next dev --webpack -p 3091 >/tmp/settings-dev.log 2>&1 &)
for i in $(seq 1 90); do curl -sf -o /dev/null http://localhost:3091/settings/security-org && break; sleep 2; done
rm -rf /tmp/settings-shots
python3 -I scripts/settings-check/walk.py --allow-unbuilt account,preferences,billing,balance,roles,sales,time-tracking,messaging,about
pkill -f "next dev --webpack -p 3091" || true
# manual: Visual loop (Read both PNGs, up to three rounds), then:
cp /tmp/settings-shots/settings-security-org.png /tmp/settings-shots/settings-security-personal.png docs/screenshots/
test -s docs/screenshots/settings-security-org.png && test -s docs/screenshots/settings-security-personal.png
! grep -rn "useSettingsBlob\|/admin/settings" app/components/settings/SecurityOrgTab.tsx app/components/settings/SecurityPersonalTab.tsx || exit 1
scripts/settings-check/export-check.sh   # the plan's throwaway-tree recipe, scoped to lines this effort added (hits inherited from before the effort base are reported, not failed)
```

## Depends on
- Phase 0: `--if-*` tokens, the Settings header and Tab list, `SettingsPanel` parts (Panel header, `Section`, `Field`, `ToggleRow`, `NotWired`), the `SETTINGS_PANELS` record in `[tab]/page.tsx`, the six-tab blob allow-list (security tabs absent), and `walk.py` with its mock of `/auth/me`, `/admin/employees` and its Write list recording.

## Out of Scope
- 2FA enrollment, TOTP QR, enforcement, per-Employee reset: no Relay route (plan Constraints "no 2FA").
- A sessions list or "sign out other sessions": one sliding cookie session, no sessions route (Constraints).
- Real Last login: `users.last_seen_at` is the Agency's, not the Employee's; the plan fixes "—".
- Password change: no route (Ground truth 5).
- Restricting Security (organization) to Owner/Admin: Permission roles are Not applied yet (ADR-0008).
- Chatter-only sessions: Settings is reached from an Agency session; chatter sign-out stays in the avatar menu.
- Removing `nb()` for the two hrefs and `docs/routes.md`'s "stubs" wording: Phase 5 and Phase 6 own the end state.
- A Save row, a blob, or the "not applied yet" note: nothing is stored (plan "No blob tab for either").

## Further Notes
- ASSUMPTION A1: the bundle has no security-specific `rxwf7` selectors, so the Employees table's row height, cell padding and header style are not measured; rows are 48px with a 1px `--if-line` bottom border and header text 14px `--if-fg-3`, borrowing the measured header height and label style. Overturned by a measured Infloww security-table selector.
- ASSUMPTION A2: the toggle description and the section titles "Employees", "Current session", "Password", "Two-factor authentication" are ours (personal fields are `G` in §3.10). Overturned by Infloww copy for these tabs.
- ASSUMPTION A3: the Current session card uses the bordered-card (`._translation-item_rxwf7_369`) Geometry, the only measured card in `rxwf7`. Overturned by a measured security card.
- ASSUMPTION A4: "Sign out" is the house `Button` (secondary) and calls `useUser().logout` (rung 3, `TopBar.tsx:102`), so it also wipes caches and hard-navigates to `/`. Overturned if the human wants Sign out to stay on Settings.
- ASSUMPTION A5: the roster is `useRoster()` with its defaults, so chatter-mirror rows are hidden, and disabled rows use `opacity-60` (rung 3, `EmployeesTab.tsx:140`). Overturned if the human wants mirrors listed.
- ASSUMPTION A6: the walk interface is Phase 0's spec (`walk.py [--allow-unbuilt all|<tab>,…]`, `SCENARIOS` list); the Acceptance allows exactly the non-security non-legacy tabs as unbuilt, a fixed list never edited at landing, so the line passes whatever order Phases 1, 3 and 4 land in (Cross-spec decision (c)). Overturned by a different Phase 0 walk interface or a fixed landing order.
- ASSUMPTION A7: the walk clicks disabled controls with `force=True` so "clicking the 2FA toggle records no write" exercises the control rather than timing out. Overturned if Phase 0's walk asserts disabled controls differently.

## Review
Reviewer: codex (blind call + draft call, `model_reasoning_effort=high`), 2026-10-13.

Blind call:
- B1 reject (no defect claimed) — Alternative "parity shell, unsupported controls disabled" is the plan's Phase 2 Decisions and ADR-0008; the spec already takes it.
- B2 reject — Alternative "make 2FA/password/sessions functional": plan Constraints say no 2FA and no new auth surface (plan Phase 2 Decisions; `service/db/models.py` has no Employee credential fields); stays in Out of Scope.
- B3 reject — "Who may use the org toggle (Owner/Admin)": already Out of Scope; Employees have no role column, `is_admin` is the founder flag (`service/auth.py:489-505`), and the toggle is `NotWired` for everyone so no one can change it.
- B4 reject — "Current session under impersonation / must use `UserContext.logout`": already decided (impersonation bullet in Implementation Decisions; A4 uses `useUser().logout`).
- B5 reject — "Which roster rows: chatter mirrors, disabled": already decided by A5 (`useRoster` defaults: disabled included, mirrors excluded, `app/hooks/useRoster.ts:44-71`).
- B6 reject — "Say the Last-login dash means not tracked": plan fixes "—" and Out of Scope records why (`users.last_seen_at` is the Agency's); explanatory copy is scope the plan did not ask for.
- B7 accept — Loading/empty/error states need tests: merged with D2 below.
- B8 partial — "Test logout against the real contract (cache wipe, navigation)": Seam 2 now asserts the query cache is emptied, proving the `useUser().logout` path; a separate impersonation test is rejected, the logout path is the same code for both principals (`service/auth.py:555-560`).
- B9 reject (no defect claimed) — Falsifiers (an Employee session model, a real Infloww security capture) are the overturn conditions already written into Out of Scope and A2/A3.

Draft call:
- D1 accept — Walk invocation contradicted Phase 0's interface (`--allow-unbuilt`, `SCENARIOS`; phase-00 spec Testing Decisions) and the plan's "unbuilt allowed in Phase 0 only": Acceptance now passes `--allow-unbuilt` with every non-security tab, Owns and Seam 3 name `SCENARIOS`, A6 rewritten.
- D2 accept — Story 9 (empty roster, failed load) had no seam: Seam 1 adds a `[]` case ("No employees") and a 400 case (error line; 400 because `useRoster` retries 5xx, `useRoster.ts:59-63`).
- D3 accept — "switch shows off" was unasserted: Seam 1 asserts `aria-checked="false"`.
- D4 accept — Story 15 table scroll was unchecked: Seam 1 asserts the `overflow-x-auto` box, Seam 3 asserts computed `overflow-x: auto` at 390x844.
- D5 reject — "Acceptance does not enforce the visual review or the commit": reading a PNG and judging diffs is the plan's manual step 2 (plan Check loop) and cannot be a shell assertion; the `cp` runs straight after the walk under `set -e`, so the PNGs are not stale; committing belongs to the coordinator.

### Six hats

Six hats report (`.scratch/settings-tabs/SIX-HATS.md`), 2026-10-13, reconciled by the plan reviewer. Cross-spec items (a)–(f) are decided under Implementation Decisions, "Cross-spec decisions".
- Black (a), "`! grep` never fails" (phase-02:83) — **accept**: the line ends `|| exit 1`.
- Black (c), "Phases 1–3 say any order, Phase 4 assumes plan order" (phase-02:106) — **accept**: A6 rewritten; the list is fixed (every non-legacy tab but this Phase's two) and never edited at landing.
- Black (b), key form (story 17 named `security-org`, `security-personal`) — **accept**: story 17 and Interfaces now use the full hrefs.
- Black (f) — **accept** (knock-on): the block clears `/tmp/settings-shots` before the walk; its `cp` already runs in the same block.
- Green, "drop the any-order list" (phase-02:78) — **reject**: Cross-spec decision (c) keeps any order with fixed lists (rung 4).
