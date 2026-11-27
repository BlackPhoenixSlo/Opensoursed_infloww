# Phase 02h — Docs + handoff

**Objective.** Sites #2..#10 have a Triage scorecard and a recipe that points to it, the Fansly docs say only what the evidence shows (`destinationTax` unknown, §6.10 and P1–P4 listed, stale sweep table marked, stats and payout reads described as refused), the Lift table is finished with no `owner:` placeholder or unresolved Branch, and agency-scale-out has been told what Phase 2 does and does not give its Fanvue tickets.

## Problem Statement
The owner wants Fanvue, MYM, privacy.com.br and about ten sites in total, but nothing in the repo says how to judge which comes next, what an agent may look at before accounts exist, or how to record what it saw. Recipe step 0 says "scorecard row per site" and no scorecard exists. On Fansly, the docs still overstate: `RECIPES.md` calls `destinationTax:2000` a 20 % fee when gross 3000 − net 2400 = 600; `CAPTURE_TODO.md` lists three Proof purchases where four are needed and has no row for the free notification-paging capture; the parity doc's 2026-09-02 sweep table lists `tip_reward`, `tip_request` and `reengage_buyers`, which are not registered kinds; and the notifications route's Query description names filter values (`'tips'`, `'subscribes'`) no caller sends. Each earlier Phase 2 PR adds its own Lift table rows, but nothing checks at the end that every refusal names a concrete lift and that no Verdict still reads `owner:NN`. Agency-scale-out's Fanvue tickets 62, 81, 94 and 106 wait on "MP Phase 2 merged", and Phase 2 builds no Fanvue code, so without a note they would start on a false premise.

## Solution
A new `docs/platform-triage.md` holds the scorecard: one row per candidate site, every cell carrying a Triage mark (O, D, OC, P, U), all U today, plus the limits for the separate network-allowed triage run, the eligibility and ranking rule, and the evidence format. Recipe step 0 points to it, and the recipe names the evidence bar, Live check and Lift table a new Platform follows. The Fansly docs are corrected in place. `fansly/test_lift_table.py` gains its final checks: one row per Reason, every "Lifted by" built from the fixed vocabulary, every capture section, Proof purchase and evidence path it cites exists, and no Fansly Verdict is `owner:NN`. The dependency correction is committed in this effort's map; after merge it is sent to the agency-scale-out thread with the merge sha, and Phase 02h is not closed until that send is recorded. OnlyFans behaviour does not change; the one code-file edit is a description string.

## User Stories
1. As the owner, I want one scorecard of candidate sites, so that I can pick site #2 from evidence, not memory.
2. As the owner, I want nine rows (Fanvue, MYM, privacy.com.br, LoyalFans, FanCentro, ManyVids, Just for Fans, Fanfix, Passes), in triage order Fanvue first, then my other named sites, then the rest, so that the sites I named are looked at first.
3. As the owner, I want every scorecard cell to carry a Triage mark (O seen logged out, D public doc with URL and date, OC owner-confirmed, P asked and pending, U unknown), so that I can tell seen from guessed.
4. As the owner, I want training-knowledge remarks kept as T notes that never count as a mark, so that a model's recollection never passes for evidence.
5. As the owner, I want the step-0 columns (signing headers, challenge and where it fires, API host and style, websocket), cost columns (official creator API with access requirements and covered operations, login method, creator DMs and mass messages, creator-side sales visibility, currency and language) and gate columns (accounts/KYC, roster demand, Infloww lists it, terms text), so that a row answers what site #2 would cost.
6. As the owner, I want id, time and money units left out of the scorecard (U until recipe step 3), so that the trap list is filled from a capture, not from a landing page.
7. As the owner, I want every row shipped all-U, so that nothing in the first version claims an observation this effort could not make (no network).
8. As the owner, I want the limits for the later triage run written into the doc (logged out only; no signup, form submit or captcha; stop at the first challenge and record page and point; only landing, login, one public creator profile, public help and developer docs; request hosts and header names, never values; nothing under any `capture/out/`), so that the run I invoke cannot drift into a login or a leak.
9. As the owner, I want a site eligible only when DMs exist (D or O), accounts are possible (OC) and no challenge fired on the in-scope pages (O), so that an ineligible site never gets ranked.
10. As the owner, I want eligible sites ranked by roster demand (OC), then by an evidenced integration route only, with unseen creator traffic counted unknown, and "insufficient evidence" written when none is eligible, so that the doc never picks for me.
11. As the owner, I want ties and the final pick left to me, stated in the doc, so that site #2 is my decision.
12. As the owner, I want the doc's open questions (official-API site: whole Shim or an API client behind the Backend contract; account-id prefixing parked through step 3; Fanvue being site #2 or #3 is naming only), so that the pick meeting starts from them.
13. As an agent following the recipe, I want step 0's check to point at `docs/platform-triage.md`, so that I know where the row goes and what marks it may carry.
14. As an agent following the recipe, I want it to name ADR-0069 (what a Grade allows), ADR-0070 (Live check in two PRs), the Verdict table and a per-Platform Lift table, so that site #2 inherits Fansly's evidence rules instead of re-deciding them.
15. As an agent, I want no stub registry row, Backend or Shim for any new site, so that the dummy-key and unknown-key checks from Phase 02a keep failing loudly as designed.
16. As the owner, I want the "Coming soon" mym and Fanvue rows in the Platform switcher unchanged, so that nothing on screen moves before a site lands.
17. As an operator reading Fansly money, I want `RECIPES.md` to call `destinationTax` unknown (gross 3000, net 2400, `destinationTax` 2000 do not reconcile), so that nobody computes net or fee from it.
18. As the owner, I want `CAPTURE_TODO.md` §6 to list P1–P4 (chat PPV, paid sub not a gift code or 15016 trial, chat tip, paid post unlock), each with what it must show and what it closes, and P2's lifecycle steps P2a–P2d, with P2b–P2d marked as later, separate observations (renewal off, lapse, resubscribe) and P4 marked as required before 2007 drives follow-ups, so that every lift that needs money is listed and none is promised from one session.
19. As the owner, I want §6.10 (free: the Proof fan likes enough to pass one notification page, creator scrolls; then one mark-read pair with read-back) with what it records (cursor, ordering, termination) and what it closes (notification catch-up, `notifications_read`), so that the free capture that lifts two Blocked items is on the list.
20. As the owner, I want §6.7–6.9 kept as the dated record of the 2026-11-26 blocked attempt and pointed at P1–P3, so that the history and the plan do not disagree.
21. As the owner, I want 2008, 32007, 45012 and post tips marked "not bought: no automation reads them", so that nobody spends on them.
22. As a reader of the parity doc, I want the 2026-09-02 sweep table marked stale (it ran on the live relay, lists three unregistered kinds, predates the Side-effect gate) with a link to the Verdict table, so that I read the current verdicts.
23. As a reader of the parity doc, I want the Phase 1b Blocked tables to point at the Lift table as the current list, so that two lists cannot disagree silently.
24. As an API user, I want the notifications route's `type` description to list the filter values callers actually send, so that `'tips'` and `'subscribes'` stop being advertised.
25. As the owner, I want every Lift table row's "Lifted by" to be `Never`, `code-only`, or an ordered ` + `-joined list of a `CAPTURE_TODO.md` section (`§N.M`), a Proof purchase (P1–P4, P2a–P2d), `code-fix` (a code change that ships with the lift, e.g. P2c's empty-roster fix) and `PLATFORM_LIVE_CHECK=<aid>:<method>[:target]`, so that a lift needing capture, fix and Live check says all three.
26. As the owner, I want every cited `§N.M` and P-number to exist in `CAPTURE_TODO.md`, every Grade + evidence citation's file path to exist, and each Reason to appear in exactly one row, so that a lift never points at nothing and two rows cannot disagree.
27. As the owner, I want every row's Owner action and Follow-up PR filled (a PR reference once lifted, `pending <what>` before, `none` for Never), with no `owner:`, `TBD` or empty cell, so that the table is finished, not drafted.
28. As the owner, I want the drift test to fail if any Fansly Verdict is still `owner:NN`, so that Phase 2 cannot close with a lane no ticket resolved.
29. As agency-scale-out, I want a handoff note saying Phase 2 builds no Fanvue code, and listing my real prerequisites (a Fanvue registry row with a Backend, Fanvue session move/restore, a persisted automation hold, bound-proxy preflight, admission for 94 and 106), and asking me to re-key those tickets off "MP Phase 2 merged", so that they do not start on it alone.
30. As agency-scale-out, I want that note by message, never as an edit to my files, so that my thread owns its map.
31. As the mirror thread, I want the merge sha of the PR that edits `RECIPES.md` (M3), so that I rebase on it.
32. As a reader of the parity doc, I want the payouts/stats row and the stats and payout rows of the Automation surface table to say what 02c made them (transactions, payout requests and payout balances Blocked, `subscribers_chart` refused, `earnings_chart` Blocked with no earnings read), and the RECIPES earnings section to say the capture backs no read yet (07 D), so that no doc says payouts are built or honestly empty.
33. As the owner, I want 02h's PR to say in its body which owner actions remain (Live checks, P1–P4 billing address, §6.10, triage run, roster counts, terms rulings, the pick), so that one place lists what is mine.

## Implementation Decisions
- **Owns.**
  - `docs/platform-triage.md` (new).
  - `docs/platform-recipe.md`: step 0 check cell, one short evidence-and-lifts paragraph, and any ADR-0068 line 02a left behind (unknown key → OnlyFans, hand-extended key scan, Fansly-named or "parked" marker names).
  - `fansly/capture/RECIPES.md`: the `destinationTax` sentence in the PPV section.
  - `fansly/capture/CAPTURE_TODO.md` §6: row 6.10, the P1–P4 table, a pointer line on 6.7–6.9.
  - `fansly/FANSLY_PARITY_STATUS.md`: stale note on "Automation sweep 2026-09-02", pointer line under "Phase 1b verdicts", the 07 D rows (story 32), and finishing the `## Lift table` rows earlier Phases added.
  - `fansly/capture/RECIPES.md`: the 07 D note in the earnings section (capture kept, no read built; ticket 07 item 2 supersedes 06 item 3's `earnings_stats()`, which 06 itself drops as slice C).
  - `fansly/test_lift_table.py`: the final checks.
  - The notifications route's `type` Query description in the server module.
  - `.scratch/multi-platform-p2/map.md`: the dependency-correction line (pre-merge; no sha).
- **Interfaces.** None change. `test_lift_table.py` stays a plain script run by `scripts/run-tests.sh`'s Fansly section; it exits non-zero on any failed check.
- **Schema.** None.
- **Contracts.**
  - Triage mark per cell: `<mark> <evidence>`. O: page and request host or header name (never a value). D: URL and `YYYY-MM-DD`. OC: `owner YYYY-MM-DD`. P: who was asked and `YYYY-MM-DD`. U: bare. T remarks go in a Notes column and are never parsed as a mark.
  - Lift table "Lifted by" grammar as in story 25; one row per Reason. Follow-up PR: `#<n>` or a PR URL, `pending <trigger>`, or `none`.
  - Map line (in the PR): `agency-scale-out handoff: Phase 2 builds no Fanvue code; 62/81/94/106 need <the five prerequisites>; send after merge`.
  - Handoff message (orchestrator, `t3_thread_send`, after merge): one paragraph with the merge sha, "Phase 2 merged; it builds no Fanvue code", the five prerequisites from 10 item 7 with their ticket numbers, a request to re-key 62/81/94/106 off "MP Phase 2 merged", and a pointer to `docs/platform-triage.md`. Delivery is recorded in the orchestrator's run report (thread, date, sha, send result), not by a further commit. No thread found or the send fails → Phase 02h stays open and the run reports it as a block with the message text; parking text in the map is not delivery.
- The triage doc lives in its own file, not a recipe section (10 item 6).
- The notifications description lists exactly the values the app sends to that route today (`ofMirrorFeedsNotifications.ts` feeds and the `FanslyNotifications.tsx` tabs; `all` = no filter) plus `followed` (added on Fansly by 02c's 06 D), each quoted as `'x'`. OnlyFans accepts what it accepted before; only the string changes.
- The `destinationTax` correction rewrites the one sentence; the frame block above it stays verbatim (it is evidence).
- The Lift table rows themselves come from 02a–02f (02g adds no new reason and lands after 02h, D5). 02h does not add rows for new reasons; it resolves cells. A row that cannot be resolved without code (an `owner:NN` Verdict, a reason with no owner) is a block, reported with the Phase that owns it, and 02h does not merge until that Phase's fix lands.
- File rules (11 item 1): 02h is the last Phase, so its `server.py` edit has no concurrent writer; it still runs the merge-train check before merge.
- Deploy is not this Phase's work (header floor 1). After 02h merges, the orchestrator deploys AE (ae-deploy) and public + app (public-sync), Twin excluded, without waiting for 02g or the mirror (D5), and adds WATCH.md lines once `client/main` contains Phase 2, per 11 item 4.

## Testing Decisions
- One seam: `fansly/test_lift_table.py` (built by 02a as the drift test). 02h adds checks on what it already parses: (a) each Reason appears in exactly one row (02a's set equality stays); (b) every "Lifted by" parses under story 25's grammar and every `§N.M` / P-number resolves to a row in `CAPTURE_TODO.md`; (c) every Grade + evidence citation's file path exists in the tree; (d) no Owner action or Follow-up PR cell is empty, `owner:` or `TBD`; (e) no Fansly entry of `KIND_VERDICTS` is `owner:NN`. Checks (a)–(d) are plain assertions on the real table. One mutation self-check (D6): an in-memory copy of the `KIND_VERDICTS` mapping (not the Markdown) with one Fansly entry set to `owner:NN` must fail (e).
- The triage doc, recipe pointer, RECIPES and CAPTURE_TODO edits are prose; the Acceptance block checks them, the scorecard by parsing its table (nine rows in order, header width, every non-Notes cell exactly `U`). No new test file (YAGNI; nothing reads these docs).
- The description string has no unit test; Acceptance compares it with the app callers' values, and the full suites prove nothing else in the server module moved.
- All checks run on the merge candidate (main merged in).
- Prior art: `service/tests/test_platform_table_drift.py` (parses a doc table against code), `service/tests/test_platform_capability.py` (prints counts, fails on misses), `fansly/test_lift_table.py` (02a).

## Acceptance
```sh
set -eu
PY=${PY:-venv/bin/python}
no() { if grep -q "$@"; then echo "forbidden: $*"; exit 1; fi; }
git merge-base --is-ancestor origin/main HEAD
test -f docs/platform-triage.md
grep -q 'docs/platform-triage.md' docs/platform-recipe.md
grep -q 'ADR-0069' docs/platform-recipe.md
grep -q 'ADR-0070' docs/platform-recipe.md
no 'fansly_unsupported\|fansly_blocked' docs/platform-recipe.md
no 'unknown or `None` → `ONLYFANS`' docs/platform-recipe.md
"$PY" - <<'EOF'
sites = ["Fanvue", "MYM", "privacy.com.br", "LoyalFans", "FanCentro", "ManyVids", "Just for Fans", "Fanfix", "Passes"]
lines = open("docs/platform-triage.md").read().splitlines()
hdr = next(l for l in lines if l.startswith("| Site "))
cols = [c.strip() for c in hdr.strip("|").split("|")]
assert cols[-1] == "Notes", cols
rows = [[c.strip() for c in l.strip("|").split("|")] for l in lines if l.startswith("| ") and l.split("|")[1].strip() in sites]
assert [r[0] for r in rows] == sites, [r[0] for r in rows]
for r in rows:
    assert len(r) == len(cols), r[0]
    assert all(c == "U" for c in r[1:-1]), r[0]
EOF
grep -qi 'stop at the first challenge' docs/platform-triage.md
grep -qi 'insufficient evidence' docs/platform-triage.md
grep -n 'destinationTax' fansly/capture/RECIPES.md | grep -qi unknown
no 'destinationTax` is Fansly.s cut' fansly/capture/RECIPES.md
grep -q '^| 6.10 |' fansly/capture/CAPTURE_TODO.md
for p in P1 P2 P3 P4 P2a P2b P2c P2d; do grep -q "| $p |" fansly/capture/CAPTURE_TODO.md; done
grep -q '^## Lift table' fansly/FANSLY_PARITY_STATUS.md
grep -q 'test_platform_kind_verdicts' fansly/FANSLY_PARITY_STATUS.md
no 'payout_requests (honest empty)' fansly/FANSLY_PARITY_STATUS.md
"$PY" - <<'EOF'
import re
src = open("service/server.py").read()
m = re.search(r'"/api/of/v2/users/notifications"\)\n.*?type: str \| None = Query\(None, description="([^"]*)"', src, re.S)
desc = set(re.findall(r"'([a-z_]+)'", m.group(1)))
sent = set(re.findall(r"type=([a-z_]+)", open("app/lib/ofMirrorFeedsNotifications.ts").read()))
tab = re.search(r"type Tab = ([^;]+);", open("app/components/fansly-manager/FanslyNotifications.tsx").read()).group(1)
sent |= set(re.findall(r'"([a-z_]+)"', tab)) | {"followed"}
assert desc == sent, (sorted(desc), sorted(sent))
EOF
nice -n 10 "$PY" fansly/test_lift_table.py
test "$(PYTHONPATH=. nice -n 10 venv/bin/alembic -c service/db/migrations/alembic.ini heads | grep -c head)" = 1
"$PY" scripts/comment_budget.py --check
nice -n 10 scripts/run-tests.sh
(cd app && nice -n 10 pnpm test:run)
grep -q 'agency-scale-out handoff: Phase 2 builds no Fanvue code' .scratch/multi-platform-p2/map.md
# manual, closes the Phase: orchestrator sends the handoff (merge sha) to the agency-scale-out thread and the M3 sha to the mirror thread (t3_thread_send); the run report records thread, date, sha, send result; a failed or impossible send keeps 02h open
# manual: orchestrator deploys AE + public (Twin excluded) after 02h merges and adds WATCH.md lines
# manual: owner runs the network-allowed triage run, gives roster counts and terms rulings, picks site #2
```

## Depends on
- 02a: `fansly/test_lift_table.py`, the `## Lift table` section, the `Lack` members, the recipe's ADR-0068 edits (neutral markers, unknown key refuses, registry-built scan), ADR-0068.
- 02c: 07 A's Shim refusals (story 32 describes them); the `fully_backfilled` change also covers scan rows already stamped `true` (a seeded legacy Fansly row reads not-backfilled in the status API). If 02c lands without that, 02h reports it as a 02c block.
ASSUMPTION: 02c owns the legacy-row case (06 item 4 says "stops stamping", silent on old rows; 02c:173 treats the flag as display only). Overturned if 02c's spec claims it or no Fansly scan row exists on any target (unknown: 11 Needs the human).
- 02b–02f (D5; not 02g): every Lift table row and Verdict their lanes add or change, with no `owner:NN` left for a lane they own; 02c's `followed` notification type (named in the description); 02d's `notifications_read` Blocked row (cites §6.10); 02e/02f's mass rows.
- Mirror thread: none directly; M1 applies if it edited RECIPES or CAPTURE_TODO since 02f (read its log, rebase).
- Linear PR order (D8): 02a-1 → 02a-2 → 02b → 02c → 02d → 02e → 02f → **02h** → 02g.

## Out of Scope
- Network triage of any site: header floor 2 and 10 item 1; it is its own owner-invoked run.
- Any second site's registry row, Backend, Shim or stub: 10 item 6 and 09 items 4–5 (a backendless row must fail).
- Editing agency-scale-out's files: 10 item 7, message only.
- Landing copy that says Fanvue and MYM are unsupported (`web/src/switch-to-openinflowwww.njk`): owed only when a site lands (10 fog).
- A reconciliation of earnings totals against banked rows: 06 item 3, deferred until comparable buckets are evidenced.
- New Lift table reasons or code fixes for an unresolved lane: owned by the Phase that owns the lane.
- Deploy, WATCH.md lines, rwl window: header floor 1; orchestrator after merge.
- A test for the triage doc's shape: no reader of it exists (YAGNI); Acceptance greps cover it.

## Further Notes
ASSUMPTION: the handoff message is sent after 02h merges, not at PR open, because the tickets wait on "MP Phase 2 merged" (rung 4: a message about a merged state cannot be wrong after merge). Overturned if the owner wants it earlier; only timing falls.
ASSUMPTION: the orchestrator finds the agency-scale-out thread by `t3_thread_search` on "agency-scale-out" (rung 5); no thread found → 02h stays open and is reported as a block with the message text.
ASSUMPTION: O evidence and the triage run's findings are written into the scorecard cells, not a separate evidence folder (rung 5); overturned if the run needs raw notes, then a `.scratch/` folder, never `capture/out/`.
ASSUMPTION: the recipe gains pointer lines to ADR-0069, ADR-0070, the Verdict table and a per-Platform Lift table, because the plan's goal promises a ready path via the recipe (rung 5); overturned if the owner wants the recipe Fansly-free; only that paragraph falls.
ASSUMPTION: the Phase 1b Blocked tables stay as a dated record with one pointer to the Lift table instead of being deleted (rung 4); overturned if the owner wants one list; then they are removed in a later docs PR.
ASSUMPTION: Follow-up PR reads `pending <trigger>` for rows not yet lifted, and that is not an `owner:` placeholder (rung 5; 11 item 2 bans `owner:` only); overturned if the owner wants every row lifted before Phase 2 closes, which Live checks and P1–P4 make impossible offline.
ASSUMPTION: the final checks live in `fansly/test_lift_table.py` rather than a new file, since it already reads the table and `KIND_VERDICTS` (rung 3 + 5); overturned if 02a builds it without reading `KIND_VERDICTS`, then 02h adds that read.
ASSUMPTION (evidence blocked): no venv in this tree to run the current suites; Acceptance assumes `venv/bin/python` as `scripts/run-tests.sh` does. Overturned by `PY=`.

## Review
Reviewer: codex (blind + draft), 2026-11-27

Blind call (P1):
- Alternatives (inline recipe section, API-backed client): **reject** — ticket 10 item 6 binds a separate file; the API-client question is already an open question (story 12).
- Recipe still teaches unknown-key fallback, hand-extended scan, Fansly markers (`platform-recipe.md:24,26,94,99`): **partial** — 02a owns the recipe's ADR-0068 edits (02a Owns, 02a:122); 02h fixes any leftover in its recipe edit, Acceptance greps two of them, patch regenerated.
- 06 D only partly indexed, 07 D omitted, `earnings_stats()` conflict, legacy `fully_backfilled` rows: **partial** — 06 D sits whole in 02c (02c:171); 07 D accepted into Owns + story 32 (02d:279 assigns it here); docs follow 07 item 2 (06 drops slice C itself); legacy rows → Depends on 02c with ASSUMPTION.
- Handoff seam, acknowledgment + receiving-side Fanvue drill: **partial** — message now asks them to re-key 62/81/94/106 and delivery is recorded; a required ack or their drill rejected: 10 item 7 is message only, their map is theirs.
- Docs acceptance seam (integrated checkout; branch-suffix, duplicate, evidence, `owner:` mutations; Query vs filters): **accept** — Testing (a)–(e) negatives, merge-base check, Query compare script.
- Falsifiers (gated branch persisting `ok`; official-API site behind a challenged webpage; terms gate): **reject** — the first is the KIND_VERDICTS harness's job (12 a, 02a); eligibility gates bind (10 item 5) and terms stay an owner ruling, not a gate; official-API handling is already an open question.

Draft call (P2):
- Blocker, Acceptance masks failures: **accept** — `set -eu`, `no()` helper, no `!` or `&&` lines (bash exempts both from errexit).
- Blocker, handoff can vanish at closure / PR cannot hold its own sha / parking fallback: **accept** — map line is the pre-merge correction only; sha + send result go in the run report; a failed or impossible send keeps 02h open.
- Major, lift contract drops required steps, one-session promise, P4 prerequisite: **accept** — story 25 grammar (` + `-joined, `code-fix` token), story 18 rewritten (`05:25-30`, `06:27-29`).
- Major, lift-table proof misses duplicates, evidence, Verdict mutation: **accept** — checks (a), (c), (e), with a `KIND_VERDICTS` copy as the mutation target.
- Major, stats documentation has no owner: **accept** — 07 D in Owns + story 32; `FANSLY_PARITY_STATUS.md:82` "payout_requests (honest empty)" grepped out.
- Major, legacy scan rows still claim completion (`fansly_revenue.py:116`, `tx_ingest_admin_api.py:112`): **partial** — real, but the code is 02c's; Depends on + ASSUMPTION, 02h reports a 02c block if missing.
- Major, scorecard checks accept empty evidence: **accept** — table parse (order, width, all-U) replaces the count grep.
- Major, merge-candidate proof incomplete: **accept** — merge-base check, one alembic head (house form, 02b:134), strip-regen regeneration (11 item 3).
- Minor, Query grep weak: **accept** — description set compared with app callers (`ofMirrorFeedsNotifications.ts:19-26`, `FanslyNotifications.tsx:12`) + `followed`.

Plan review (six hats + coordinator D1–D8), 2026-11-27:
- Yellow [02a,02h], Lift-table drift test + KIND_VERDICTS make every refusal auditable — **accept**. Kept; (a)–(e) stay as checks.
- Black [02g,02h], deploy hangs on the mirror — **accept** (D5). Depends on is 02a–02f; the post-02h deploy does not wait for 02g; M1 window is "since 02f".
- Green [02f,02g,02h,plan], decouple deploy — **accept** (D5).
- D6 one mutation self-check per harness — **accept**. Five seeded-bad copies cut to the `KIND_VERDICTS` `owner:NN` one; (a)–(d) run on the real table.
- D8 linear order — **accept**.
- Real handle in story 19 replaced with "the Proof fan" — **accept**.
Counts: accept 6 · partial 0 · reject 0 · needs-human 0.
