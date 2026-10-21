# Phase 06 — sign-off

**Objective.** All eleven Settings tabs are built, every Constraints gate and every Phase's Acceptance is green in one run on one commit, the Settings walk exits 0 at 1440x900 and 390x844 with a Write list equal to the union of the Phase 1–4 lists, the eleven `docs/screenshots/settings-<tab>.png` are committed, and `docs/settings-parity.md` records per Settings tab what is wired, what is Not wired and every `VISUAL GAP:`, the font included.

## Gap table (gates)

This Phase builds no UI, so its measured table is the list of gates: each plan line, the check that proves it, and the Acceptance step that runs it. "Base" is `206b58fe^`, the commit before this effort's scaffolding (`git log 206b58fe^..HEAD` lists only settings-tabs commits today).

| # | Plan line (source) | Check that proves it | Acceptance step |
|---|---|---|---|
| G1 | Ground truth 1: all 11 tabs built with `nb()` today, `page.tsx:16` renders `NotBuiltYet` | `grep -rn NotBuiltYet app/app/settings` is empty; Phase 5's `nav.test.ts` case (no non-legacy `SETTINGS_TABS` entry is `notBuilt`) runs inside vitest | 1, 4 |
| G2 | Constraints: typecheck | `pnpm -C app typecheck` exits 0 | 2 |
| G3 | Constraints: lint, 0 errors | `pnpm -C app lint` exits 0 (warnings allowed) | 2 |
| G4 | Constraints: vitest for each new component; every Phase's named test file | the 15 test files named in Phases 0–5 are tracked and each holds an `it(`/`test(` case, then `ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run` exits 0 (vitest passes with no tests, so existence is checked first) | 3, 4 |
| G5 | Constraints + Phase 0: settings API | `./venv/bin/python service/tests/test_settings_api.py` exits 0 | 5 |
| G6 | Constraints: check-public-export on a throwaway tree | `scripts/settings-check/export-check.sh` exits 0 (the plan's throwaway-tree recipe; only lines this effort added fail) | 6 |
| G7 | Constraints: `--if-*` read only by the Settings components this plan creates (ADR-0009) | no file under `app/` (skipping `node_modules`, `.next`) outside `app/app/globals.css` and `app/components/settings/` contains `--if-`; the Legacy files under `app/components/settings/` are held unchanged by G12 | 7 |
| G8 | Constraints: font stays `--font-sans` | the diff from Base touches no `--font-sans` line in `globals.css` | 7 |
| G9 | Constraints: nothing outside `app/`, `docs/`, `service/`, `scripts/settings-check/` changes | every path changed since Base is under those, `.scratch/settings-tabs/`, `CONTEXT.md` or `.claude/agents/` (floor 1's design files) | 8 |
| G10 | Constraints: no backend deletions | no file under `service/` deleted since Base, and no removed route decorator line in the `service/` diff | 8 |
| G11 | Constraints: no new dependency | `app/package.json` and the lockfiles are unchanged since Base | 8 |
| G12 | Plan intro + HEADER: the four Legacy tabs stay as they are | `LegacySettingsTab.tsx` and the four tabs it imports (`AuditTab`, `LanesTab`, `RestrictionsTab`, `TransferTab`; `LegacySettingsTab.tsx:6-9`) are unchanged since Base | 8 |
| G13 | Check loop + Phase 6: walk exit 0, all 11 tabs, both sizes | `python3 -I scripts/settings-check/walk.py` against `next dev --webpack -p 3091` exits 0 and leaves 11 `settings-<tab>.png` in `/tmp/settings-shots/` | 9 |
| G14 | Phase 6: Write list = union of Phases 1–4 | the report's writes are exactly the seven below, once each, each body passing its Phase's predicate | 10 |
| G15 | Phase 6 + Check loop step 3: 11 PNGs committed | step 11 copies this run's eleven `/tmp/settings-shots/settings-<tab>.png` over `docs/screenshots/`, each is tracked, and no `-390` PNG is in `docs/screenshots/` (Cross-spec decisions (e), (f)) | 11 |
| G16 | Phase 6: `docs/settings-parity.md` | step 12: the evidence sentence; sections in order; exactly 11 rows, one per known slug; each Blob row names `/admin/settings/<tab>` and "not applied yet"; the plan's eleven Not wired controls present; the Ground truth 5 anchors in Backend corrections; the font gap; every ticket `VISUAL GAP:` under `## Visual gaps`, with ticket files present | 12 |
| G17 | Phase 6: `NEXT_SESSION_SETTINGS_UI.md` §3 replaced, with the Ground truth 5 corrections | the file is absent (deleted in `b07a433d`, an ancestor of HEAD) and the corrections and the plan pointer live in the parity doc's "Backend corrections" section; if the file has been restored, it must point at the plan and the parity doc | 12 |
| G18 | Constraints + ADR-0008: stored settings are not consumed elsewhere | no line added since Base outside the blob's own files (`app/components/settings/`, `app/lib/settingsBlob*`, `service/settings_api.py`, `service/db/models.py`, `service/db/migrations/`, `service/server.py`, `service/tests/test_settings_api.py`) mentions `admin/settings`, `UserSetting` or `user_settings` | 8 |

The union (G14), from each Phase's walk Acceptance; Phases 0 and 5 add no write, and Phase 2's 2FA click and Phase 4's Cancel add none:

| Phase | Method, path | Body predicate |
|---|---|---|
| 1 | `PUT /admin/settings/account` | equals `{"agency_name":"Synthetic Agency"}` |
| 1 | `PUT /admin/settings/preferences` | keys are exactly `report_tz, tz, week_start, language`; `week_start == "sunday"` |
| 2 | `POST /auth/logout` | equals `{}` (Phase 2 Contracts) |
| 3 | `PUT /admin/settings/roles` | `roles[].name` contains Owner, Admin, Synthetic Role |
| 3 | `PUT /admin/settings/sales` | `attribution.messages == "sender"` |
| 4 | `PUT /admin/settings/time-tracking` | keys are exactly `enabled, auto_clock_out_minutes, clock_in_reminder`; minutes `== 30` |
| 4 | `PUT /admin/settings/messaging` | `prompt` contains "synthetic prompt" |

## Problem Statement

After Phases 0–5 each Settings tab has passed its own Acceptance, on its own commit. Nobody has yet shown that they all hold together on the final tree: a later Phase can break an earlier walk step, add a write that an earlier Phase forbade, or leave a stale screenshot. A reader also has nowhere to see, tab by tab, how close Inflowwww's Settings is to Infloww's: which controls really save, which are Not wired, what is Not applied yet, and which visual differences were accepted. The draft backend wiring that misled the plan (`docs/NEXT_SESSION_SETTINGS_UI.md` §3: "roles" on employees, Your Account on `/api/of/v2/users/me`) has no recorded correction.

## Solution

One run, one commit: every gate in the table above goes green, and the Settings walk produces the eleven final PNGs, which are committed. A new `docs/settings-parity.md` grades each Settings tab against its Dashboard bundle evidence, lists every Not wired control and every `VISUAL GAP:`, and carries the Ground truth 5 corrections with a pointer to the plan, because the draft that would have held them has already been deleted.

## User Stories

1. As an Agency owner, I want no Settings tab to show "Not built yet", so that every Settings tab is a real page.
2. As a maintainer, I want typecheck, lint (0 errors), vitest and the settings API test green on the final tree, so that the effort ends on a working build.
3. As a maintainer, I want every Phase's named component test to exist before vitest runs, so that a missing file cannot pass as zero tests.
4. As a maintainer, I want the check-public-export run on the throwaway tree, exactly as the plan writes it, to exit 0, so that no real name, id or home path rides along with this effort.
5. As a maintainer, I want proof that only the Settings components read `--if-*` and that the font token was not touched, so that ADR-0009's departure from ADR-0001 stays inside Settings.
6. As a maintainer, I want proof that nothing outside `app/`, `docs/`, `service/`, `scripts/settings-check/` (plus the effort's design files) changed, that no backend file or route was deleted, that no dependency was added and that the four Legacy tabs are byte-identical, so that the Constraints held for the whole run.
7. As a maintainer, I want the Settings walk to exit 0 over all eleven Settings tabs at 1440x900 and at 390x844, so that geometry, tokens, console errors and overflow are checked on the final tree, not per Phase.
8. As a maintainer, I want the walk's Write list to equal the seven writes of Phases 1–4, once each, with each body matching its Phase's predicate, so that no Phase's write was lost and no read-only tab (Security, Billing, Your Balance, About, a Cancel, the 2FA switch) started writing.
9. As a reviewer, I want the eleven final `settings-<tab>.png` from that walk committed under `docs/screenshots/`, so that the recorded look matches the signed-off tree.
10. As a reviewer, I want `docs/settings-parity.md` to have one row per Settings tab with its Ground-truth evidence (Dashboard bundle selectors, §3.10 row and `C[H…]` refs), its component, what is wired, what is Not wired and its visual gaps, so that I can judge parity per tab.
11. As a reviewer, I want each Blob tab's row to say its values are Not applied yet (ADR-0008), so that nobody mistakes a saved value for an enforced one.
12. As a reviewer, I want every Not wired control listed with its tab and the missing backend, at least the plan's eleven (Your Account: picture upload, username Edit; Security (organization): Two-factor authentication, Reset; Security (personal): Change password, Enable 2FA; Billing: Pricing plans, Update card, Cancel subscription, Billing information, Make a Payment) plus any other `NotWired` use found in the code, so that the gap list is complete.
13. As a reviewer, I want every `VISUAL GAP:` line from the Phase 0–5 tickets carried verbatim, plus the gaps the plan itself decided, so that the accepted differences are in one place.
14. As a reviewer, I want the font recorded as a `VISUAL GAP:`: Settings stays on `--font-sans`, while Infloww uses "RobotoRegular" for Settings and the licensed "Suisse Int'l" for its `hb-design` parts, so that the most visible difference is not silent.
15. As a future planner, I want the Ground truth 5 corrections (no role field on `/admin/employees`; `/api/of/v2/users/me` is the OF model's profile, not the Agency account; no rename, password, sessions or 2FA route; referral balance and payouts are per Creator; `/admin/translate` has no prompt or config; no attribution config route, `/admin/lanes` is concurrency; version from `app/package.json`) next to a pointer to `docs/plans/settings-tabs.md` and the parity doc, so that the deleted draft's wrong wiring is not revived.
16. As the coordinator, I want a red gate reported with its failing output and owning Phase instead of patched here, so that the sign-off stays a verification and each fix lands in its Phase's ticket.

## Implementation Decisions

- **Owns.** `docs/settings-parity.md` (new), the eleven `docs/screenshots/settings-<tab>.png` (copied from the final walk), and the Settings row of `docs/routes.md` (`:33` says the eleven tabs "are stubs"; Phase 0's Out of Scope hands it here), rewritten to say they are built Panels. No code. Phase 6 runs the gates; it does not edit a component, a test, the walk or the service.
- **Interfaces.** None in code. The parity doc's format is the interface its Acceptance checks:
  - First, one sentence containing "no Settings screenshot": parity is graded against Dashboard bundle selectors and the help-center reconstruction, since no real Infloww Settings screenshot exists (Ground truth 4). Then sections in this order: `## Backend corrections`, `## Not wired`, `## Visual gaps`, `## Parity table` last (house precedent: `docs/spec/phase-07-ours-kept-marked.md` Acceptance for `docs/messages-pro-parity.md`).
  - `## Backend corrections`: the Ground truth 5 list and a pointer to `docs/plans/settings-tabs.md`. Each correction is named by its anchor: `/admin/employees`, `/api/of/v2/users/me`, the missing `password` and `2FA` routes, `referrals/balance`, `/admin/translate`, `/admin/lanes`, `app/package.json`.
  - `## Not wired`: one line per control, ``- `<tab>` — <control>: <missing backend>.`` with `<tab>` the href's last segment; every `- ` line in the section has that shape.
  - `## Visual gaps`: one line per gap, beginning `VISUAL GAP:`. It carries every ticket `VISUAL GAP:` line verbatim, the font gap, and the plan-decided differences: the Tab list is a strip below `md` where Infloww keeps a 5/16 column, the "Desktop app" link sits in the Settings header, Sales hides "Learn more" until a docs page exists, About has no beta box or build hash, the Tab area height is computed from our top bar rather than Infloww's 52px root header, and the measured two-column field grid `repeat(2,350px)` (plan:34) is not used, every field being its own row.
  - `## Parity table`: header `| Tab | Ground-truth evidence | Component | Wired | Not wired | Visual gap |`, eleven rows keyed by tab slug (`account`, `preferences`, `security-org`, `security-personal`, `billing`, `balance`, `roles`, `sales`, `time-tracking`, `messaging`, `about`). Every cell is filled (`none` when empty), no `|` inside a cell. The six Blob tabs' Wired cell names `/admin/settings/<tab>` and its blob keys and says "not applied yet".
- **Schema.** None — no table or field changes.
- **Contracts.** Read-only uses of Phase 0's walk: it runs as `python3 -I scripts/settings-check/walk.py` with `PORT` (default 3091), writes `/tmp/settings-shots/settings-<tab>.png` and `/tmp/settings-shots/settings-report.json`, and the report holds the Write list.
- The `docs/NEXT_SESSION_SETTINGS_UI.md` §3 replacement is the parity doc's "Backend corrections" section, because the file was deleted in `b07a433d` (`git show b07a433d --stat`: `docs/NEXT_SESSION_SETTINGS_UI.md | 103 ---`) and no tracked file but the plan links to it. Phase 6 does not recreate it; if a human restores it, Acceptance step 12 requires it to point at the plan and the parity doc, which is the plan's literal Decision.
- The committed PNGs are this run's walk `settings-<tab>.png` files, copied unchanged by Acceptance step 11 (Cross-spec decision (f): no byte comparison with another walk); the report JSON and the `-390` PNGs are not committed.
- The Not wired list is built from the plan's eleven controls and from the code's not-wired uses (`<NotWired` and the `notWired` prop of `ToggleRow`, Phase 0 Interfaces) in non-test files under `app/components/settings` outside the `SettingsPanel` module. Any extra control found in the code is added to the list too. Acceptance checks the plan's eleven; completeness against the code is on the reviewer checklist (Testing Decisions).
- A red gate stops the run and the EXIT trap prints its step and owner (story 16). Every negated check ends in `|| exit 1`, because `set -e` ignores a command inverted with `!` (`bash -c 'set -eu; ! true; echo reached'` prints `reached`).

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

- The one seam is the Acceptance block below. It runs every gate on the final tree. Existing seams it calls: Phase 0's Settings walk (Write list, computed styles, PNGs), the vitest suite (each Phase's component tests and `nav.test.ts`), `service/tests/test_settings_api.py`, and `scripts/check-public-export.sh`. The parity doc is checked by an awk pass over its sections.
- No new test files: what this Phase adds is a document plus the gates' combined verdict.
- Reviewer checklist (manual, not gated; six hats Green): every `<NotWired` / `notWired` use in non-test files under `app/components/settings` appears in `## Not wired`; each Not wired line names its missing backend; each Parity table row's evidence and component cells are true of the code the walk ran on.
- Prior art: `docs/spec/phase-07-ours-kept-marked.md` Acceptance (parity-doc awk check, table last); `scripts/of-mirror-check/writes.py:44-47` (recorded writes as `(method, path, body)`); `.scratch/settings-tabs/suite.sh` (the four suite gates).

## Acceptance

```sh
set -eu
cd "$(git rev-parse --show-toplevel)"
BASE=206b58fe^
TABS="account preferences security-org security-personal billing balance roles sales time-tracking messaging about"
# A red gate stops here and names its step and owner (story 16). `set -e` ignores a command inverted
# with `!`, so every negated check ends in `|| exit 1`.
STEP=setup
trap 'rc=$?; pkill -f "next dev --webpack -p 3091" || true; [ "$rc" -eq 0 ] || echo "RED at step $STEP" >&2' EXIT

# 1. No unbuilt Settings tab.
STEP="1 NotBuiltYet (owner: Phase 5)"
! grep -rn NotBuiltYet app/app/settings || exit 1

# 2–5. Suite gates. Each Phase's named test exists and holds a case first (vitest passes with no tests).
STEP="2 typecheck (owner: the Phase that owns the failing file)"
pnpm -C app typecheck
STEP="3 lint (owner: the Phase that owns the failing file)"
pnpm -C app lint
STEP="4 named tests + vitest (owner: the Phase that names the test file)"
for f in SettingsShell.test.tsx settingsBlob.test.ts YourAccountTab.test.tsx PreferencesTab.test.tsx \
  SecurityOrgTab.test.tsx SecurityPersonalTab.test.tsx RoleSettingsTab.test.tsx PermissionEditor.test.tsx \
  SalesSettingsTab.test.tsx TimeTrackingTab.test.tsx MessagingSettingsTab.test.tsx BillingTab.test.tsx \
  BalanceTab.test.tsx AboutTab.test.tsx nav.test.ts; do
  p=$(git ls-files | grep -m1 "^app/.*/$f\$") || { echo "missing test: $f"; exit 1; }
  grep -qE '(^|[^A-Za-z])(it|test)\(' "$p" || { echo "no test case in: $p"; exit 1; }
done
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
STEP="5 settings API (owner: Phase 0)"
./venv/bin/python service/tests/test_settings_api.py

# 6. check-public-export on a throwaway tree (plan, Constraints), scoped to lines this effort added.
STEP="6 check-public-export (owner: the Phase that touched the flagged file)"
scripts/settings-check/export-check.sh   # the plan's throwaway-tree recipe, scoped to lines this effort added (hits inherited from before the effort base are reported, not failed)

# 7. --if-* only in globals.css and the Settings components; --font-sans untouched.
STEP="7 --if-* scope / --font-sans (owner: Phase 0, or the flagged file's Phase)"
! grep -rlE --exclude-dir=node_modules --exclude-dir=.next -- '--if-[a-z]' app | grep -v -e '^app/app/globals.css$' -e '^app/components/settings/' || exit 1
! git diff "$BASE" -- app/app/globals.css | grep -E '^[-+].*--font-sans' || exit 1

# 8. Scope, no backend deletion, no dependency, Legacy tabs untouched, stored settings consumed nowhere else.
STEP="8 scope / deletion / dependency / Legacy / consumers (owner: the flagged path's Phase)"
! git diff --name-only "$BASE" | grep -vE '^(app/|docs/|service/|scripts/settings-check/|\.scratch/settings-tabs/|CONTEXT\.md$|\.claude/agents/)' || exit 1
test -z "$(git diff --name-only --diff-filter=D "$BASE" -- service)"
! git diff "$BASE" -- service | grep -E '^-[[:space:]]*@[A-Za-z_]+\.(get|post|put|patch|delete)\(' || exit 1
git diff --quiet "$BASE" -- app/package.json app/pnpm-lock.yaml pnpm-lock.yaml
git diff --quiet "$BASE" -- app/components/settings/LegacySettingsTab.tsx app/components/settings/AuditTab.tsx \
  app/components/settings/LanesTab.tsx app/components/settings/RestrictionsTab.tsx app/components/settings/TransferTab.tsx
! git diff "$BASE" -- app ':!app/components/settings' ':!app/lib/settingsBlob.ts' ':!app/lib/settingsBlob.test.ts' \
  | grep -E '^\+.*admin/settings' || exit 1
! git diff "$BASE" -- service ':!service/settings_api.py' ':!service/db/models.py' ':!service/db/migrations' \
  ':!service/server.py' ':!service/tests/test_settings_api.py' | grep -E '^\+.*(UserSetting|user_settings|admin/settings)' || exit 1

# 9. Settings walk on all 11 tabs at 1440x900 and 390x844 (the walk's own exit code).
STEP="9 Settings walk (owner: the Phase of the failing tab, from the report's failures)"
rm -rf /tmp/settings-shots
(cd app && exec npx next dev --webpack -p 3091) >/tmp/settings-next.log 2>&1 &
for i in $(seq 90); do curl -sf -o /dev/null http://localhost:3091/settings/account && break; sleep 2; done
python3 -I scripts/settings-check/walk.py
for t in $TABS; do test -s "/tmp/settings-shots/settings-$t.png"; done

# 10. Write list == union of the Phase 1–4 lists, once each.
STEP="10 Write list (owner: the Phase of the missing, extra or bad write)"
python3 -I - /tmp/settings-shots/settings-report.json <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
w = [tuple(x) if isinstance(x, list) else (x["method"], x["path"], x.get("body")) for x in r["writes"]]
want = {
    ("PUT", "/admin/settings/account"): lambda b: b == {"agency_name": "Synthetic Agency"},
    ("PUT", "/admin/settings/preferences"): lambda b: set(b) == {"report_tz", "tz", "week_start", "language"} and b["week_start"] == "sunday",
    ("POST", "/auth/logout"): lambda b: b == {},
    ("PUT", "/admin/settings/roles"): lambda b: {"Owner", "Admin", "Synthetic Role"} <= {x["name"] for x in b["roles"]},
    ("PUT", "/admin/settings/sales"): lambda b: b["attribution"]["messages"] == "sender",
    ("PUT", "/admin/settings/time-tracking"): lambda b: set(b) == {"enabled", "auto_clock_out_minutes", "clock_in_reminder"} and b["auto_clock_out_minutes"] == 30,
    ("PUT", "/admin/settings/messaging"): lambda b: "synthetic prompt" in str(b.get("prompt")),
}
got = sorted((m, p) for m, p, _ in w)
assert got == sorted(want), f"Write list {got} != {sorted(want)}"
for m, p, b in w:
    assert want[(m, p)](b), f"bad body: {m} {p} {b}"
print("Write list OK:", len(w))
PY
# manual: Read each /tmp/settings-shots/settings-<tab>.png against the Ground-truth table; anything left after the Phases' three rounds is a VISUAL GAP: line in the parity doc.

# 11. The 11 PNGs are this walk's, copied over the committed ones (Cross-spec decisions (e), (f)); the coordinator commits them.
STEP="11 committed PNGs (owner: Phase 6)"
for t in $TABS; do
  cp "/tmp/settings-shots/settings-$t.png" docs/screenshots/
  git ls-files --error-unmatch "docs/screenshots/settings-$t.png" >/dev/null
done
test -z "$(ls docs/screenshots | grep -e '-390\.png$')"

# 12. Parity doc: evidence basis, sections in order, table last, exactly 11 rows,
# Blob rows, Not wired list, Ground truth 5 anchors, the font gap, every ticket VISUAL GAP: carried.
STEP="12 parity doc (owner: Phase 6)"
doc=docs/settings-parity.md
if [ -e docs/NEXT_SESSION_SETTINGS_UI.md ]; then
  grep -qF 'docs/plans/settings-tabs.md' docs/NEXT_SESSION_SETTINGS_UI.md
  grep -qF 'docs/settings-parity.md' docs/NEXT_SESSION_SETTINGS_UI.md
fi
grep -qF 'no Settings screenshot' "$doc"
test "$(grep '^## ' "$doc" | tr '\n' ';')" = '## Backend corrections;## Not wired;## Visual gaps;## Parity table;'
sed -n '/^## Backend corrections/,/^## /p' "$doc" > /tmp/settings-corrections.txt
for k in docs/plans/settings-tabs.md /admin/employees /api/of/v2/users/me password 2FA referrals/balance \
  /admin/translate /admin/lanes app/package.json; do
  grep -qF -- "$k" /tmp/settings-corrections.txt || { echo "Backend corrections misses: $k"; exit 1; }
done
awk -v tabs="$TABS" -v blob="account preferences roles sales time-tracking messaging" -F'|' '
  BEGIN { nt = split(tabs, T, " "); nb = split(blob, B, " ")
          for (i = 1; i <= nt; i++) known[T[i]] = 1; for (i = 1; i <= nb; i++) isblob[B[i]] = 1 }
  /^## / { sec = $0; next }
  sec == "## Parity table" && /^\|/ && !/^\| *Tab *\|/ && !/^\|[-: |]+\|$/ {
    n++
    if (NF != 8) { print "bad row: " $0; bad = 1; next }
    for (i = 2; i <= 7; i++) { c[i] = $i; gsub(/^ +| +$/, "", c[i]); if (c[i] == "") { print "empty cell: " $0; bad = 1 } }
    t = c[2]; gsub(/`/, "", t)
    if (!(t in known)) { print "unknown tab: " t; bad = 1 }
    if (t in rows) { print "duplicate row: " t; bad = 1 }
    rows[t] = 1
    if ((t in isblob) && (tolower(c[5]) !~ /not applied yet/ || index(c[5], "/admin/settings/" t) == 0)) { print "Blob row without route or not applied yet: " t; bad = 1 }
  }
  END { if (n != nt) { print "Parity table rows: " n; bad = 1 }
        for (i = 1; i <= nt; i++) if (!(T[i] in rows)) { print "Parity table misses: " T[i]; bad = 1 }; exit bad }' "$doc"
sed -n '/^## Not wired/,/^## /p' "$doc" | grep '^- ' > /tmp/settings-notwired.txt
while IFS=: read -r t c; do grep -qF -- "- \`$t\` — $c" /tmp/settings-notwired.txt || { echo "Not wired misses: $t $c"; exit 1; }; done <<'EOF2'
account:Edit
account:Upload
security-org:Two-factor authentication
security-org:Reset
security-personal:Change password
security-personal:Enable 2FA
billing:Pricing plans
billing:Update card
billing:Cancel subscription
billing:Billing information
billing:Make a Payment
EOF2
sed -n '/^## Visual gaps/,/^## /p' "$doc" > /tmp/settings-gaps.txt
grep '^VISUAL GAP:' /tmp/settings-gaps.txt | grep -F 'Suisse Int' | grep -qF -- '--font-sans'
! grep -n '/settings/\[tab\].*are stubs' docs/routes.md || exit 1
set -- .scratch/settings-tabs/issues/*.md
test -e "$1" || { echo "no ticket files in .scratch/settings-tabs/issues/"; exit 1; }
grep -hE '^(- )?VISUAL GAP: ' "$@" | sed -E 's/^(- )?//' | sort -u |
  while IFS= read -r g; do grep -qxF -- "$g" /tmp/settings-gaps.txt || { echo "parity doc misses: $g"; exit 1; }; done
STEP=done
echo "Phase 6 sign-off: all gates green"
```

## Depends on

- Phase 0: the `--if-*` block, the shell, `SettingsPanel` (`NotWired`), `useSettingsBlob`, `user_settings` with `/admin/settings/{tab}`, `test_settings_api.py` and the Settings walk with its Write list and report.
- Phases 1–4: their tabs, component tests, walk actions and Write lists (the union in G14).
- Phase 5: Billing, Your Balance and About, and the removal of `NotBuiltYet` and `nb()` with its `nav.test.ts` case.
- All tickets of Phases 0–5 landed, with their `VISUAL GAP:` lines in `.scratch/settings-tabs/issues/`.

## Out of Scope

- Fixing a red gate: the fix belongs in the owning Phase's ticket. This Phase reports and stops.
- Restoring `docs/NEXT_SESSION_SETTINGS_UI.md` as a stub: the file is already deleted, so a restored file would only bring back a dead runbook.
- Committing `settings-report.json` or 390x844 shots: the plan asks only for the eleven `settings-<tab>.png`.
- Pixel-diffing the committed PNGs against a reference: the plan's visual check is the read-and-record loop, and the Dashboard bundle has no Settings screenshot (Ground truth 4).
- Any consumer of a Settings blob, any enforcement, and loading Suisse Int'l (ADR-0008, ADR-0009, Constraints).
- The Legacy tabs, `scripts/ui-shots.sh` and the Messages Pro parity doc.

## Further Notes

ASSUMPTION: `docs/NEXT_SESSION_SETTINGS_UI.md` was deleted in `b07a433d`, an ancestor of HEAD, so the "§3 replacement" becomes the parity doc's "Backend corrections" section (the Ground truth 5 corrections plus the plan pointer), and the file is not recreated (rung 4/5). Overturned if the human wants a stub restored at that path.
ASSUMPTION: the parity table has six columns (Tab, Ground-truth evidence, Component, Wired, Not wired, Visual gap), keyed by tab slug, with the table last; "wired / not wired / visual gap" is read as three columns, not a single status (rung 3, from the `messages-pro-parity.md` check in `docs/spec/phase-07-ours-kept-marked.md`). Overturned if Phase 0's spec or the human prefers a single status column.
ASSUMPTION: the walk report is `/tmp/settings-shots/settings-report.json` with a top-level `writes` list whose entries are `[method, path, body]` or `{method, path, body}` (rung 5; the plan names the file and the tuple, not the key; Phase 0's spec writes `{tabs, writes, failures}` with `[method, path, json body]` entries, which matches). Overturned if Phase 0 lands another key: rename it in step 10.
ASSUMPTION: Phases 0–5 leave at least one ticket file in `.scratch/settings-tabs/issues/`, so an empty directory means the tickets did not land and step 12 goes red (rung 5). Overturned if the coordinator keeps tickets elsewhere; then point the glob there.
ASSUMPTION: the parity doc's truth (Not wired completeness against the code, evidence and component cells) is a reviewer checklist, not a gate; Acceptance gates only its structure and the plan's literal lists (rung 5, six hats Green: plan:301-302 names the doc's content, plan:307-309 no doc check). Overturned if an unreviewed sign-off ships a parity doc that misses a `NotWired` control; then restore the code-count gate.
ASSUMPTION: one walk run performs each Phase's action once (at 1440x900; the 390x844 pass only renders), so each of the seven writes appears exactly once (rung 5). Overturned if Phases 0–4 repeat actions at 390x844; then the count per write doubles.
ASSUMPTION: the effort's Base is `206b58fe^`, and no other effort lands on this branch after it (rung 1 for today's log, rung 5 for the future). Overturned if another effort's commits interleave; then G9–G12 diff only this effort's commits.
ASSUMPTION: a red gate is reported with its output and owning Phase, not fixed here (rung 5). Overturned if the coordinator gives sign-off tickets fix rights.
ASSUMPTION: ticket gap lines begin a line with `VISUAL GAP:` (optionally after `- `), so instruction text that only mentions the phrase is not carried (rung 3, from `.scratch/messages-pro-parity/issues/*`). Overturned if the Phase tickets record gaps another way.
ASSUMPTION: the plan's own departures (strip below `md`, the "Desktop app" link, the hidden "Learn more", no beta box or build hash on About, the Tab area height from our top bar, the unused two-column field grid) are listed as `VISUAL GAP:` lines beside the font (rung 5). Overturned if the human counts only measured differences as visual gaps.

## Review

Reviewer: codex (blind call, then draft call), 2026-10-13. Plus one finding from the reconciler.

Blind call:
- B1 partial — "the as-written sign-off supports only a bounded claim; no real Settings screenshot exists": the plan's sign-off shape is binding (plan:296-309), so the alternatives are not taken, but the parity doc now states its evidence basis in a sentence with "no Settings screenshot" (Interfaces; step 12 greps it).
- B2 reject — "auth cases (Chatter, impersonation) missing": Phase 0 owns `test_settings_api.py` and covers a Chatter session → 401 and records impersonation as refused by the session middleware (`auth.py:144-151`; Phase 0 spec, Review B5); Phase 6 re-runs it (G5).
- B3 reject — "load/save/retry error contract missing": Phase 0's `settingsBlob.test.ts` asserts the failed load, the sparse-PUT block and the failed refetch; Phase 6 re-runs it inside vitest (G4).
- B4 reject — "no keyboard/assistive-tech acceptance": the plan asks for none (plan:111-129, 296-309); YAGNI. Phase 0 already sets `aria-current` on the active row.
- B5 reject — "a wrong token value passes token-equality checks": Phase 0's walk has a light pass asserting the measured literals (rgb(52, 103, 255) etc.), which step 9 re-runs.
- B6 reject — "no intermediate viewport": the plan names 1440x900 and 390x844 only (plan:115-118, 307-309); a binding constraint.
- B7 reject — "gate outputs not attached to the parity record": the plan asks for no log artifact; `Graded at` plus a re-runnable Acceptance is enough (YAGNI).
- B8 reject — "test at two seams, walk and service route": already the spec's design (G5 runs `test_settings_api.py`, G13/G14 the walk).
- B9 reject — "`NotBuiltYet` and `nb()` still in `page.tsx:16`, `nav.ts:158-174`; walk, parity doc and settings API absent": expected before Phases 0–5 land; that is the Depends on, and step 1 plus steps 4–5 and 9 go red until they do.
- B10 accept — "a consumer of a blob would falsify ADR-0008": no gate checked the Constraint "not consumed elsewhere". Added G18 and step 8's two diff greps for `admin/settings` / `UserSetting` / `user_settings` outside the blob's own files.
- B11 reject — "cross-Agency read/write would falsify the ownership model": Phase 0's test case "two Agencies isolated" covers it; Phase 6 re-runs it (G5).

Draft call:
- D1 accept — "`Graded at` cannot name the commit that contains the doc, and the check never ties it to the walked tree": `Graded at` is now HEAD or an ancestor that differs from the tree only in the parity doc and the PNGs; step 12 checks `merge-base --is-ancestor` and the diff.
- D2 accept — "stale committed PNGs pass": step 11 now `cmp`s each committed PNG with this run's walk output (byte-stability flagged as an ASSUMPTION).
- D3 accept — "VISUAL GAP: check passes on an empty glob and matches anywhere in the doc": step 12 fails when `.scratch/settings-tabs/issues/` holds no ticket file (today it holds none, `ls .scratch/settings-tabs/issues` is empty) and matches only inside `## Visual gaps`.
- D4 partial — "awk allows duplicate/unknown rows and unvalidated cells": now exactly 11 rows, no duplicate, no unknown slug, and each Blob row must name `/admin/settings/<tab>` and "not applied yet" (smoke-tested under bash: a duplicated `roles` row goes red). Whether evidence/component cells are true stays the reviewer's judgment; text cannot be graded by awk.
- D5 partial — "Not wired completeness and the missing-backend part are unchecked": every `- ` line must match ``- `<tab>` — <control>: <backend>.`` and the list must be no shorter than the code's `<NotWired`/`notWired` uses; a count is a lower bound, not a one-to-one match (ASSUMPTION).
- D6 partial — "a tracked empty test file passes": step 4 now also requires an `it(`/`test(` call in each file. The tests' substance is each owning Phase's Acceptance, not Phase 6's.
- D7 partial — "token gate under-scans and over-allows": the scan now covers all of `app/` (skipping `node_modules`, `.next`). Over-allow rejected: the plan's own Phase 0 restyles the pre-existing `SettingsNav.tsx` with `--if-*` (Phase 0 spec, Owns), and the Legacy files in the same directory are held byte-identical by G12.
- D8 reject — "scope gate allows `.scratch/settings-tabs/`, `CONTEXT.md`, `.claude/agents/`, which the plan does not": the run's floor 1 (HEADER) names exactly these as the design files this run writes, and the floors outrank the plan; `git diff --name-only 206b58fe^ HEAD` already lists `.scratch/settings-tabs/*` and `CONTEXT.md`, so dropping them would turn G9 red on the effort's own design commits.
- D9 accept — "logout predicate `lambda b: True` contradicts 'none'": Phase 2's Contracts send `{}` (phase-02 spec, Contracts and Seam 3); union row and predicate are now `b == {}`.
- D10 accept — "Ground truth 5 check covers two fragments": step 12 now requires every correction's anchor (`/admin/employees`, `/api/of/v2/users/me`, `password`, `2FA`, `referrals/balance`, `/admin/translate`, `/admin/lanes`, `app/package.json`) and the plan pointer inside `## Backend corrections`.
- D11 partial — "moving §3's replacement into the parity doc is a different deliverable": the target file is gone (`git show --stat b07a433d`: `docs/NEXT_SESSION_SETTINGS_UI.md | 103 ---`), so the corrections stay in the parity doc; but the hard `test ! -e` that forbade the plan's literal artifact is removed, and if the file is restored step 12 requires it to point at the plan and the parity doc.
- D12 accept — "a red gate reports neither output tagging nor owning Phase": every step sets `STEP` with its owner and the EXIT trap prints `RED at step …`.

Reconciler:
- R1 accept — every `! cmd` check (steps 1, 7, 8) was a no-op: `set -e` ignores a command inverted with `!` (`bash -c 'set -eu; ! true; echo reached'` prints `reached`), so the Acceptance would have passed with `NotBuiltYet` still present. Each negated check now ends in `|| exit 1`.

### Six hats

Six hats report (`.scratch/settings-tabs/SIX-HATS.md`), 2026-10-13, reconciled by the plan reviewer. Cross-spec items (a)–(f) are decided under Implementation Decisions, "Cross-spec decisions".
- White, "no Infloww Settings capture exists" (phase-06:73) — **reject** as a change: the parity doc already states its evidence basis ("no Settings screenshot").
- White, "the two-column grid is missing from the plan-decided gaps" (phase-06:76) — **accept**: added to `## Visual gaps`' plan-decided list and to its ASSUMPTION.
- Red, "a 150-line shell program checking Markdown with awk" (phase-06:93-246), with Green, "keep G1–G15 and G18, make the awk validator and `Graded at` a reviewer checklist" (phase-06:193-243) — **partial**: G1–G15 and G18 stay; step 12 keeps only checks that map onto the plan's words (plan:301-304: eleven rows, Blob rows "not applied yet", the plan's eleven Not wired controls, the font gap, every ticket `VISUAL GAP:`, the Backend corrections, section order); the `Graded at` line and its ancestry check, the Not wired line-shape regex and the code-count lower bound move to a reviewer checklist (Testing Decisions), rung 5, flagged ASSUMPTION. Supersedes Review D1 and the count part of D5.
- Black (f), "Phase 6 depends on `cmp`" (phase-06:181,269) — **accept**: step 11 copies this run's eleven PNGs over `docs/screenshots/` and checks they are tracked; the byte-stability ASSUMPTION is removed. Supersedes Review D2: freshness now holds by construction.
- Black (e), "11 stale `-390` files left in `docs/screenshots/`" (phase-06:259,177-183) — **accept**: Phase 0 no longer commits any; step 11 fails on a `-390` PNG in `docs/screenshots/`.
- Black (a) — **accept**, no change: this block is the model for Cross-spec decision (a).
- Plan reviewer finding (not a six-hats bullet): Phase 0 (Out of Scope) and Phase 2 (Out of Scope) hand `docs/routes.md`'s Settings row to this Phase, which did not take it; `docs/routes.md:33` still calls the tabs stubs. **accept**: Owns now includes the row, and step 12 fails while it says "are stubs" (rung 5, a one-line doc fix).
