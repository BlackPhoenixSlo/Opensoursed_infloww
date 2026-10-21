# Phase 01 — Dashboard matches the bundle

**Objective.** `/` reads like the Layout capture `docs/infloww-layouts/dashboard.md`: a KPI header with period tabs, wired to the Relay's existing report reads at the Agency's report time zone, sits over the existing shift cards. A REA recheck against the Dashboard bundle finds no difference that lacks an "Inflowwww extra" label, and the page's recheck record (`.scratch/infloww-parity-round-2/rechecks/dashboard.md`, Phase 1 section) proposes, for Phase 6 to apply, the Parity matrix row §3.1 with the grade the matrix's grading rules give it: `matched` or `intentionally improved` when no Not wired tile remains, `not wired` while one does (Referrals today). This Phase does not edit the matrix.

## Problem Statement

An agency owner who opens Inflowwww's Dashboard does not see Infloww's Dashboard. Infloww opens on an earnings KPI header: a time zone label, a Net earnings / Gross earnings switch, the Yesterday / Today / This week / This month period tabs, Total earnings, a split by channel and Employee sales (Inventory §3.1). Ours opens with a developer strip ("Chatting as … switch", "+ Add Model", a raw `scope:` code). That strip repeats what the top bar already has. Below it come a 30-day Total revenue chart, an embedded "Creator Reports" block, and an "Inflowwww is live" status card left over from an early build phase. The previous sign-off graded §3.1 `unverified` because there is no KPI header and no period tabs (`docs/infloww-parity-matrix.md`, row 3.1). The layout it was measured against was the Clone, which is hand-made and only Medium confidence. An owner moving over from Infloww has to learn a second dashboard to answer "how much did we make today".

## Solution

The owner opens `/` and sees Infloww's Dashboard as the Dashboard bundle renders it. The control set, labels, order and spacing come from `docs/infloww-layouts/dashboard.md`; colours stay the house theme tokens and App accent (ADR-0010), and each colour the capture records that differs is listed in the difference list as an ADR-0010 colour, not as an unlabelled difference. That file is the only layout input. The Clone's `dashboard.html` is secondary, and Phase 0 already corrected it against the bundle. Clicking a period tab changes the window and puts it in the URL (`?window=today`), so a link reopens the same view. Every figure is a number the Relay already computes, counted in days of the Agency's report time zone. A figure the Relay cannot compute shows as a Not wired tile: disabled, with the tooltip "not wired", and never a made-up number. The "My shifts" and "Current clocked-in employees" cards stay. They sit where the bundle places its equivalents, or, if the bundle has none, below the header with the "Inflowwww extra" label. Every other Inflowwww block that remains on the page carries that label. Before the work closes, someone rechecks the page against the bundle with REA, and a reviewer rejects any difference that has no label.

## User Stories

1. As an agency owner, I want `/` to open on the KPI header the bundle shows, so that the Dashboard I know from Infloww is the first thing I see.
2. As an agency owner, I want every header label verbatim from the Layout capture, so that I find "Total earnings", "Net earnings" and "Gross earnings" under the words I already know.
3. As an agency owner, I want the header's controls in the capture's order and spacing, so that the page is laid out like Infloww and not like an approximation of it.
4. As an agency owner, I want the period tabs the capture records (the Inventory lists Yesterday / Today / This week / This month), so that I can switch the window in one click.
5. As an agency owner, I want the selected period in the URL as `?window=<period>`, so that a reload, a bookmark or a shared link reopens the same window.
6. As an agency owner, I want a missing or unknown `?window=` value to open the capture's default period (Today when the capture records none), so that a stale link never shows an empty or broken header.
7. As an agency owner, I want Yesterday, Today, This week and This month cut at midnight in my Agency's report time zone, so that the Dashboard agrees to the cent with Creator reports and Employee reports for the same days.
8. As an agency owner, I want This week to start on my Agency's week start (Settings › Your Preferences), so that the Dashboard's week matches the "My shifts" week and the Shift schedule.
9. As an agency owner, I want the header's time zone label (the Inventory shows "UTC-10:00") to show my Agency's report time zone, so that I know which day boundaries the figures use.
10. As an agency owner with no report time zone saved, I want the label and the windows to use the default the reports already use, so that the Dashboard and the reports never disagree.
11. As an agency owner, I want the Net earnings / Gross earnings switch to toggle every money tile, so that I can see what OnlyFans pays out or what fans paid.
12. As an agency owner, I want Net to be OnlyFans's own post-fee figure, and to be told when some of the window's sales have no net figure yet, so that I never read gross labelled as net.
13. As an agency owner, I want Total earnings for the selected window, so that I see the headline figure at a glance.
14. As an agency owner, I want the channel split the capture shows (the Inventory lists Subscriptions / Posts / Messages / Tips / Referrals / Streams), each filled from the sales kinds the Relay records, so that I see where the money came from.
15. As an agency owner, I want a channel the Relay records no sales kind for (Referrals today) to show as a Not wired tile, so that a zero never pretends to be a measurement.
16. As an agency owner, I want Employee sales for the selected window, credited the way Sales Settings decides, so that the Dashboard's ranking matches Employee reports.
17. As an agency owner, I want every other KPI the capture shows and the Relay cannot compute to be a Not wired tile in its place, so that the layout matches without fake numbers.
18. As an agency owner, I want each tile's loading, empty and error states to be the ones the capture records (or the house's loading line and Retry where the capture records none), so that a slow Relay never shows a stale or zero figure as current.
19. As an agency owner, I want "My shifts" and "Current clocked-in employees" kept and placed where the bundle puts its equivalents, so that clocking in still happens from the Dashboard.
20. As an agency owner, if the bundle has no place for a shift card, I want that card below the KPI header and labelled "Inflowwww extra", so that I can tell our additions from Infloww's.
21. As an agency owner, I want the 30-day Total revenue chart and the embedded Creator Reports block either placed as the capture's equivalent block or kept below the header inside an "Inflowwww extra" labelled section, so that nothing I rely on disappears and nothing unlabelled breaks the layout.
22. As an agency owner, I want the developer strip ("Chatting as … switch", "+ Add Model", `scope:`) and the "Inflowwww is live" status card gone from `/`, so that the page shows only Infloww's layout and labelled extras. Each of them is already reachable from the top bar, the avatar menu or `/creators`.
23. As a chatter, I want `/` to show the same header with only the Creators my session can see, so that I see my own numbers and never another Agency's.
24. As a chatter under Role enforcement whose role grants the Dashboard, I want every read the header makes to be allowed, so that the page never half-loads behind a 403.
25. As an owner of one Agency, I want no Dashboard read to include another Agency's Creators, sales or Employees, so that Agency isolation holds on the Dashboard as it does on the reports.
26. As a signed-out visitor, I want every Dashboard read refused, so that no earnings figure leaks without a session.
27. As an agency owner on a phone (390x844), I want the header to keep the capture's order, wrapping as the bundle's CSS does or, where the bundle has no phone layout, as the house phone layout does, so that the Dashboard works on my phone.
28. As an agency owner in light or dark theme, I want the header in the house theme colours with the App accent (ADR-0010), so that the Dashboard looks like every other Inflowwww screen outside Messages Pro in both themes the walk checks.
29. As a reviewer, I want each header control to cite its capture line (chunk or CSS file and offset) and its Inventory §3.1 tag, so that every transcribed value can be traced back to its source.
30. As a reviewer, I want every difference between `/` and the bundle that has no "Inflowwww extra" label to be a rejection, so that parity is enforced rather than argued.
31. As a reviewer, I want the ticket to recheck the page against the bundle with REA before close, and to record the result next to the walk shots, so that the grade rests on fresh evidence.
32. As the Phase 6 signer, I want the §3.1 row regraded with the walk shot beside the REA capture and `clone-dashboard.png`, so that Phase 6 can check the grade without redoing the work.
33. As a developer, I want vitest to pin the header's tabs, tiles and Not wired tiles, and the `?window=` round trip, so that a refactor cannot silently drift the layout.
34. As a developer, I want a relay test proving Agency isolation on the exact reads the Dashboard makes, so that a future change to a report endpoint cannot leak across Agencies through the Dashboard.
35. As the maintainer, I want no new Relay endpoint, table or sending path, so that the Dashboard is a view over reads that already exist.

## Implementation Decisions

- **Owns.** The Home page (`/`, `app/app/page.tsx`); a new Dashboard header module in `components/home` (KPI header: time zone label, Net/Gross switch, period tabs, tiles); the period-window helper added to `lib/dateRange`; the Dashboard entry of the page map in `service/permissions.py`; placement and labelling of `ShiftCards`, `TotalRevenueChart` and `CompetitorReports` on the page (their insides are not this Phase's; `CompetitorReports`' insides are Phase 3's, and this Phase treats the module as a black box); a new relay test for the Dashboard's reads; one `step` line in `.scratch/infloww-parity-round-2/suite.sh`; a `clone-dashboard` output and flow in `scripts/ui-shots.sh` and its `docs/screenshots/clone-dashboard.png`; and the Phase 1 section of `.scratch/infloww-parity-round-2/rechecks/dashboard.md` (Phase 0's recheck record contract), which proposes the §3.1 row under the rule below.
- **Input.** `docs/infloww-layouts/dashboard.md` (Phase 0) is the only layout input. Where it is silent the Inventory §3.1 decides which controls exist. "Silent" means the capture says it could not render or read that region; a control missing from a region the capture did read is absent from the bundle, is not built even though the Inventory lists it (every §3.1 header entry is `[CL]`, Clone-sourced: `docs/infloww-screens.md` §3.1), and is recorded as an omission. Where both are silent the control is not built. The Clone `ui-redesign/infloww-exact/dashboard.html` is read only to cross-check, and where it disagrees with the capture the capture wins (ADR-0013). A capture value the ticket finds wrong while rechecking is reported against Phase 0's file, not overridden in code.
- **Interfaces.**
  - Dashboard header module: one component with no props beyond the page's context. It owns the period, the Net/Gross mode and the tiles. A **control catalogue** lives next to it: one typed constant listing each header control in capture order with its verbatim label, its kind (tab, switch, tile, label), its source (capture line, which cites chunk or CSS file and offset), its Inventory tag (`[CL]`, `C[GAP]`, …), and whether it is wired or Not wired. The component renders from the catalogue, and the test asserts the rendered tree against it, and the catalogue against the capture file (see Testing Decisions), so a catalogue typed from memory fails. Precedent: the extras catalogue in `lib/openinflowwwwExtras` and its audit test. The catalogue is how "the `C[…]` tags on every control" is kept: there are no per-element comments to drift out of date.
  - Period window: `lib/dateRange` gains one function that maps a period (the capture's tab ids, e.g. `yesterday | today | this_week | this_month`) plus the report time zone plus the week start to `[from, to]` instants. It reuses `daysAgoISO`, `monthRange` and `toLocalIso`, and is exported for the test.
  - URL: the page reads `?window=` once on mount, the way `useTabParam` seeds a tab, and a tab click replaces the query without adding a history entry. An unknown value falls back to the capture's default tab, or `today` when the capture records no default.
  - Settings: the report time zone and week start come from the Applied settings (`useAppliedSettings`, `useWeekStart`). Like `useReportRange`, the header waits for them before it fires a read.
- **Schema.** None. No table, column or migration.
- **Contracts.** Every read already exists and stays byte-identical. Each tile names the one read it uses:
  - Total earnings and the channel tiles: `GET /admin/stats/revenue?from&to&group_by=kind`, plus `include_net=true` in Net mode (`net_cents`, `net_missing_count`). The report time zone is applied by `_report_zone` on the Relay, and the app sends instants already cut in that zone.
  - Employee sales: `GET /admin/stats/per-employee?from&to` (Sales Settings crediting, the "Unattributed" bucket included).
  - Any tile backed by a read not named here is Not wired, unless that read is already in the Dashboard's page-map entry (`/admin/stats/per-model`, `/admin/shifts/clocked-in`, `/api/of/v2/subscriptions/count`, `/api/of/v2/subscriptions/subscribers`, `_ME`).
  - The page-map entry for `/` gains `/admin/stats/per-employee` (story 24). `test_role_enforcement.py` holds no copy of the map (it reads `permissions.PAGE_MAP`), so it needs no edit; it stays in Acceptance to prove the map still covers every route and that Employee reports keeps routes of its own (`SHARED_ONLY` unchanged).
  - No request body is guessed (ADR-0005). No OnlyFans write is added.
- **Channel mapping.** The Relay's sales kinds (`transaction_ingest.KIND_CATALOG`) map to the capture's channels as follows, and the mapping is written once, in the header module:
  - Subscriptions = `subscription` + `rebill`.
  - Messages = `ppv_message` + `custom`.
  - Posts = `ppv_post`.
  - Tips = `tip` + `tip_post`.
  - Streams = `ppv_stream` + `tip_stream`.
  - Referrals: no kind, so Not wired.
  - `unknown` (a statement line `KIND_CATALOG` does not classify, `transaction_ingest.py:221`, stored and counted as before) and any kind not named above count in Total earnings and in no channel tile. The channel tiles can therefore sum to less than Total earnings, and the header never states or implies that they add up.
  - A channel the capture does not show is not built.
- **Existing blocks.**
  - The shift cards move to the capture's position for its "My shifts" and clocked-in blocks (the bundle carries both strings), else below the header with the `EXTRA_LABEL` title.
  - `TotalRevenueChart` and `CompetitorReports` are matched to a capture block where one exists (e.g. the Total earnings chart, Employee sales). Otherwise they sit below the header in one section titled with `EXTRA_LABEL`, with their lazy loading (`next/dynamic`, `ssr:false`) kept. `CompetitorReports` is a black box here: Phase 3 owns its insides (its Net control, its window and its Net figure; Phase 3 removes today's "Net earnings (×0.8)" estimate). The header's switch does not drive it, the header's Net is only `net_cents`, and the recheck record lists whatever second Net control the module renders when the recheck runs as part of that labelled extra.
  - The developer strip and the "Inflowwww is live" card are removed from `/`. Employee switch and scope are in the top bar and avatar menu, the Relay status is the top bar's badge, and "+ Add Model" is `/creators`. The stale "Phase B replaces this" comment goes with them.
- **Not wired** is the house state: `disabled` with `title="not wired"`, never a zero or a placeholder figure (CONTEXT.md "Not wired").
- **Scope.** The header is Agency-wide (Inventory §3.1 "an agency-wide earnings and team snapshot") and does not follow the top bar's ScopeSwitcher, as `TotalRevenueChart` does not today: picking one Creator in the top bar leaves the header's reads unchanged.
- **Identity.** Every read rides the server-side session. No Agency, Employee or account id is taken from the client to widen a read. The header sends no `account_id`, so `clamp_account_filter` scopes it to the session's Creators.
- **REA recheck (close gate).** Before the ticket closes, it serves the bundle on 127.0.0.1 exactly as Phase 0 does (`python3 -I -m http.server --bind 127.0.0.1 <port> --directory ~/Downloads/infloww-remote-web`, started outside the bundle) and renders the bundle's Dashboard with REA (`inspect_web_page`, `capture_web_screenshot`). It shoots `/` on the dev server `127.0.0.1:3001` with a mocked Relay at 1440x900 and 390x844, light and dark, and compares the two (REA `compare_web_screenshots`, plus a control-by-control read against the capture). The ticket records the differences in its recheck section's `### Differences`. Each entry is fixed, labelled "Inflowwww extra", or recorded as an omission with its reason. Anything else is a review rejection. If the bundle will not render, the recheck is the capture's chunk and CSS citations read against the built page, and the ticket says so.
- **Evidence placement.** REA shots of the bundle stay under `/tmp`, uncommitted, as the walk shots do. The committed evidence is the capture file and the recheck record. `docs/screenshots/clone-dashboard.png` is a 1440x900 shot of the Clone's `dashboard.html` (as Phase 0 left it), made the way `clone-messages-pro.png` is: a `clone-dashboard` entry in `scripts/ui-shots.sh`'s `OUTPUTS` and a flow with `origin: RELAY` on `/infloww/dashboard.html` (`scripts/ui-shots.sh:30-31`, `:1366-1369`), so Phase 6 regenerates it instead of trusting a one-off file.
- **Matrix row proposal.** The recheck section's `### Matrix row` gives the §3.1 row's cells for Phase 6 to apply (same `§` id, same 11 cells); this Phase does not edit the matrix (coordinator ruling, 2026-10-17). Visual evidence names the walk shots, the REA recheck and `clone-dashboard.png`, and drops `app-dashboard.png` and `phone-dashboard.png` unless they are re-shot from the new page (no script regenerates them). Data source and Read/write name the reads above. Remaining gap lists only labelled extras, Not wired tiles, ADR-0010 colours and recorded omissions. The Matrix status follows the matrix's grading rules (plan, owner decisions: "the Parity matrix's grading rules decide `matched`"): `not wired` while any tile is Not wired (house precedent: §3.4 Sales records, §3.8 Manage employees, §3.9 Notifications), else `intentionally improved` when labelled extras remain, else `matched`. Inventory version gains `v5.7.20` (the bundle).

## Testing Decisions

Two seams. A good test here reads the rendered page and the wire, never component internals.

1. **The Home page, rendered** (vitest, jsdom; `app/app/page.render.test.tsx`). `/` is mounted through `renderWithProviders` with `fetch` mocked by URL, so the assertions are about the rendered text and the requests sent. It checks:
   - the header's tabs, switch and tiles in catalogue order with verbatim labels;
   - Not wired tiles disabled with `title="not wired"`;
   - a tab click writes `?window=` and fires `/admin/stats/revenue` with the period's `from`/`to` cut in a fixture report time zone and week start;
   - a seeded `?window=` opens that tab, and a bogus one opens the default;
   - Net mode sends `include_net=true` and shows the missing-net disclosure;
   - the shift cards render in their decided place, and each "Inflowwww extra" section carries `EXTRA_LABEL`; `CompetitorReports` is mocked (`vi.mock`) to a stub, so the test asserts only where and under which label it is placed, never what it renders;
   - the developer strip and status card are absent;
   - with a single-Creator scope in the top bar, the header's reads still carry no `account_id`;
   - a channel fixture with `unknown` and `ppv_message` rows shows the `unknown` cents in Total earnings and in no channel tile;
   - the control catalogue against the capture: the test reads `docs/infloww-layouts/dashboard.md` from disk and asserts that each catalogue entry's verbatim label and its cited source (chunk or CSS file and offset) occur in that file.

   The period-window function gets table cases in the same file (a zone west of UTC, a week start of Sunday, a month boundary). Prior art: `components/home/ShiftCards.test.tsx` (URL-mocked fetch, sessions), `app/analytics/message-dashboard/page.render.test.tsx` (page-level render, `?tab=` seeding), `components/stats/StatsReport.test.tsx` (report-zone `from`/`to`).
2. **The Relay, over HTTP** (`service/tests/test_dashboard_reads.py`, house `case_` runner, `_harness` temp DB, `_agency_fixtures` two-Agency fixture, OnlyFans client faked). Each case calls the exact query strings the header sends. The cases:
   - Agency A's owner sees only A's sales in revenue-by-kind, net and per-employee;
   - Agency B's owner sees none of A's;
   - a chatter linked to A sees only A's Creators;
   - a signed-out call is 401;
   - the window the header sends selects the zone's day: with a fixture report time zone west of UTC, sales seeded one minute either side of that zone's midnight are split between `yesterday` and `today` by the exact UTC instants the period-window function produces for them. (The header sends `Z` instants, so `_parse_date`'s bare-date zone path, `stats.py:126-133`, is not on its path and is not what this case tests.)

   `test_role_enforcement.py` keeps proving the page map follows the nav, now with `per-employee` in the Dashboard entry. Prior art: `service/tests/test_applied_settings.py` (report zone cases), `test_sales_records.py` (two-Agency isolation), `test_stats_revenue.py` (response contract).

No live OnlyFans call, and no real creator, fan or account name in any fixture.

## Acceptance

```sh
cd <repo>
test -s docs/infloww-layouts/dashboard.md
pnpm -C app exec vitest run app/page.render.test.tsx components/home --testTimeout=20000
./venv/bin/python service/tests/test_dashboard_reads.py
./venv/bin/python service/tests/test_role_enforcement.py
./venv/bin/python service/tests/test_stats_revenue.py
./venv/bin/python service/tests/test_applied_settings.py
grep -F 'dashboard_reads' .scratch/infloww-parity-round-2/suite.sh
sh .scratch/infloww-parity-round-2/suite.sh
test -s docs/screenshots/clone-dashboard.png
! grep -F 'Inflowwww is live' app/app/page.tsx
R=$(sed -n '/^## Phase 1 /,/^## Phase /p' .scratch/infloww-parity-round-2/rechecks/dashboard.md)
echo "$R" | grep -q '^### Differences'
echo "$R" | sed -n '/^### Matrix row/,/^### /p' | grep -E '(matched|intentionally improved|not wired)' | grep -F 'v5.7.20' | grep -qF 'clone-dashboard.png'
grep -F 'clone-dashboard' scripts/ui-shots.sh
# manual: REA recheck: render the bundle's Dashboard (127.0.0.1) and /, both on 127.0.0.1:3001 with a mocked Relay, at 1440x900 and 390x844, light and dark; every difference is fixed, labelled "Inflowwww extra", or recorded as an omission in the recheck record's Differences.
# manual: reviewer checks the recheck record's Differences against the capture and rejects any unlabelled difference.
```

## Depends on

- **Phase 0.** It provides `docs/infloww-layouts/dashboard.md`, the Layout capture this Phase transcribes (component tree, verbatim labels, tab order, tiles, empty states, spacing and colours with chunk and CSS citations). It also corrects the Clone `dashboard.html` against the bundle, gives the recipe for serving the bundle on 127.0.0.1 with REA, and leaves a green baseline on the merged tree. No ticket of this Phase starts before the capture exists.
- **Not an order dependency: Phase 3.** Phase 3 owns `CompetitorReports`' insides and may change what it renders on `/` (its window, its Net). This Phase treats the module as a black box: it places and labels it, and its page test mocks it, so either Phase may land first and neither rebases the other's module. Both add one entry's routes to `PAGE_MAP` (this Phase the `/` entry, Phase 3 the Creator reports entry); they merge in wave order and label order within a wave, so Phase 1's lands first and Phase 3 rebases on it (plan-review, Workstreams).

## Out of Scope

- New Relay endpoints, tables or KPIs computed in the app from raw rows: a KPI with no existing read is Not wired (plan, Phase 1 decisions).
- A Referrals or other channel feed: no sales kind exists for it, and building ingest is a separate plan.
- The free-trial banner: a self-hosted deployment has no trial, and the Inventory says not to rebuild it. If the capture shows it, it is recorded as an omission.
- The Clone-only cards "Fans & subscriptions", "Daily earnings" and "Creators overview" ([CL ?], probably ours): they are built only if the capture shows them, never from the Clone alone.
- Rewriting `TotalRevenueChart`, `CompetitorReports` or `ShiftCards` internals: they are only placed and labelled. `CompetitorReports`' internals are Phase 3's.
- Any edit to the Parity matrix, its `Labelled improvements` section included: Phase 6 alone edits it, from the recheck records of Phases 1–5 and 2b.
- Committing REA shots of the bundle or any bundle file (floors).
- Changing `clamp_account_filter`'s signed-out back-compat or any auth behaviour.

## Further Notes

ASSUMPTION: the reports pages do not keep their window in the URL (`hooks/useReportRange.ts` holds it in state). The Dashboard therefore follows the plan's `?window=` literally and borrows `useTabParam`'s read-on-mount seeding, and writes the URL on click (rung 3 for the seeding, rung 5 for the write). Overturned if the owner wants the reports pages to share `?window=` too.

ASSUMPTION: the channel mapping above (stream tips under Streams, `custom` under Messages, Referrals Not wired) follows OnlyFans's statement categories as the Relay's kinds name them (rung 5). Overturned by the capture's own channel definitions or by the owner.

ASSUMPTION: Employee sales reads `/admin/stats/per-employee`, which joins the Dashboard's page-map entry, so a chatter under Role enforcement whose role grants only the Dashboard can load it. The read's own `clamp_account_filter` and Data scope still bound what the chatter sees (rung 3: each page lists the routes it calls). Overturned if the owner wants Employee sales hidden from chatters, in which case the tile is owner-only.

ASSUMPTION: the "Phase 2 cards" in the plan's goal are the previous plan's Phase 2 shift cards, "My shifts" and "Current clocked-in employees" (`components/home/ShiftCards.tsx`, spec `docs/spec/phase-02-shifts-time-tracking.md`). No other Phase 2 card renders on `/` (rung 1: `app/app/page.tsx`). Overturned if the plan meant cards from this plan's Phase 2.

ASSUMPTION: removing the developer strip and the status card deletes no feature. Each of their controls already has a home (top bar, avatar menu, `/creators`), observed in `components/shell/TopBar.tsx`. ADR-0003's "keep every extra" covers features, not leftover build-phase prose (rung 5). Overturned if the owner wants them kept as a labelled extra.

ASSUMPTION: an Infloww element this deployment cannot have (free-trial banner, billing upsell) is recorded as an omission with its reason, and does not count as an unlabelled difference. The "Inflowwww extra" label marks what we add, not what we leave out (rung 4). Overturned if the owner wants omissions labelled on the page too.

ASSUMPTION: `docs/screenshots/clone-dashboard.png` does not exist yet (rung 1: `find . -name 'clone-*.png'` finds only `clone-messages-pro.png`). This Phase makes it a `scripts/ui-shots.sh` output as `clone-messages-pro.png` is (rung 3, `scripts/ui-shots.sh:30-31`, `:1366-1369`; revised in review from a one-off shot). The temp relay serving `/infloww/dashboard.html` the way it serves `messages.html` is ASSUMPTION (evidence blocked: `service/server.py` was outside the review workspace; `ui-shots.sh:1366` cites `server.py:10550-10552`). Overturned if that route serves only `messages.html`, in which case the flow serves the Clone on 127.0.0.1 itself.

ASSUMPTION: the Dashboard keeps the house theme colours and App accent, and the capture's colours are recorded, not copied (rung 2: ADR-0010 keeps the App accent "on every other screen" outside Messages Pro, and the plan's Phase 1 Work 1 transcribes "tabs, KPI tiles, labels, order, spacing", no colours; ADR-0013 names layout truth and does not amend ADR-0010). Revised in review from "colours come from the capture". Overturned if the owner extends Infloww colours to the Dashboard, which needs an ADR-0010 amendment first.

ASSUMPTION: §3.1 is graded `not wired` while the Referrals tile (or any other) is Not wired, although the plan's Phase 1 goal reads "`matched` or lists only tagged, labelled improvements" (rung 2: the plan's owner decision that the matrix's grading rules decide `matched`, and the rule's own text, `docs/infloww-parity-matrix.md` header "`not wired`: we show the surface, but named controls or reads are not backed"; rung 3 for the precedent rows). Overturned if the owner reads a Not wired tile as an acceptable omission for `matched`.

ASSUMPTION: the header is Agency-wide and ignores the top bar's Creator scope (rung 1 for the Inventory's "agency-wide", rung 3 for `TotalRevenueChart`). Overturned if the owner wants the Dashboard to follow the ScopeSwitcher, in which case the header sends the scoped `account_id`.

ASSUMPTION: with no default period in the capture, the default is Today (rung 5: the Problem Statement's "how much did we make today"). Overturned by the capture.

ASSUMPTION: `CompetitorReports` is a black box to this Phase: placed, labelled, mocked in the page test, never edited. Its insides, including today's ×0.8 Net estimate, are Phase 3's, which rebuilds them (coordinator ruling 5, 2026-10-17; rung 5, one owner per module). Overturned if the owner wants the Dashboard embed frozen as it is; then Phase 3 adds a `variant` prop (Phase 3's ASSUMPTION) and this Phase mounts the frozen variant.

ASSUMPTION: this Phase makes no edit to `docs/infloww-parity-matrix.md`. Its proposed §3.1 row goes under `### Matrix row` in `.scratch/infloww-parity-round-2/rechecks/dashboard.md`, and Phase 6 alone regrades the matrix (coordinator ruling 2, 2026-10-17, adopting six-hats 13; rung 4, since the matrix holds the owner's uncommitted Sign-off and Phase 6 regrades every row anyway). Overturned once the owner commits the matrix and wants each Phase to regrade its own row.

ASSUMPTION: a signed-out call to the Dashboard's reads is already 401 (the house auth gate, `test_account_isolation_gate.py`'s 401 case). If the new test finds otherwise, the ticket records it and parks, and does not change auth (rung 4). Overturned by the test.

## Review

weaker (devils-advocate), 2026-10-17. Codex was tried first. It is authenticated (`codex login status`: "Logged in using ChatGPT"), but the blind call exited 1 after 94,087 tokens with "You've hit your usage limit … try again at Nov 11th, 2026" and wrote no output file, so it failed postflight and the draft call was never sent. The fallback ran the devils-advocate persona (`.claude/agents/devils-advocate.md`) in-process, confined to the review workspace, because the run's HEADER forbids spawning sub-agents. Its "blind" call was not structurally blind: this reviewer had already read the spec. The Infloww bundle and `docs/infloww-layouts/dashboard.md` were not in the workspace, so no bundle claim was checked. A codex rerun once the quota resets would strengthen this review.

Blind call (alternatives, missing requirements, seam, falsifiers):
1. **reject**: alternative "grow `CompetitorReports` into the header" (it already has a Net/Gross dropdown, period bucketing and "Earnings by channel"). Its Net is invented (`NET_RATIO = 0.8`, `components/home/CompetitorReports.tsx:25`, `:169`, `:392`), its periods are day/week/month buckets and not the capture's tabs, and it sends one revenue request per Creator (`app/app/page.tsx` comment above `CompetitorReports`). A new header over the two existing reads is the smaller change.
2. **accept** (Input rewritten): falsifier. Every §3.1 header control in the Inventory is `[CL]`, so it comes from the Clone (`docs/infloww-screens.md` §3.1, "Header: … [CL]"), and "where the capture is silent the Inventory decides" would rebuild Clone controls the bundle lacks. "Silent" now means the capture could not read a region. A control missing from a region the capture did read is absent from the bundle, is not built, and is recorded as an omission.
3. **accept** (Channel mapping and a vitest case added): missing requirement. Ingest stores rows it cannot classify as kind `unknown` (`service/transaction_ingest.py:221`, `:754`). Revenue sums every tracked kind (`service/stats.py:246-256`), so the channel tiles cannot add up to Total earnings. The spec now says where `unknown` goes and that the header never implies the tiles add up.
4. **partial** (Scope decision, ASSUMPTION and a vitest case added): missing requirement. The top bar's `ScopeSwitcher` shows on every page (`components/shell/TopBar.tsx:64`), and `/admin/stats/revenue` filters only on its `account_id` query (`stats.py:241`). With no `account_id`, a single-Creator scope would show silently Agency-wide figures. Kept Agency-wide per the Inventory's "agency-wide earnings and team snapshot", but now stated and tested. Not taken: following the scope, because the Inventory says the opposite.
5. **reject**: seam. Stories 3, 27 and 28 (spacing, phone, themes) have no automated test. The plan makes the REA recheck the gate (Phase 1 Work 5), and Phase 6's Route walk already shoots `/` at 390x844 and fails on sideways scroll (`docs/infloww-parity-matrix.md` header, "Phone"). A pixel test is scope the plan did not ask for.

Draft call (where the spec is wrong):
6. **accept** (Acceptance rewritten): the old matrix grep would pass while §3.1 is still `unverified`. The row's last cell, Phone, already reads `| intentionally improved |`. Run on the current row, `grep -E '^\| 3\.1 \|' docs/infloww-parity-matrix.md | grep -E '\| (matched|intentionally improved) \|'` matches. The check is now an `awk` on the Matrix status cell (`$9`), Inventory version (`$10`) and Visual evidence (`$4`). It exits 1 on the current row and 0 on a regraded test copy.
7. **accept** (Objective, Matrix edit rule and Acceptance rewritten): the spec required `matched`/`intentionally improved` while building a Not wired Referrals tile. The plan's owner decisions say the matrix's grading rules decide `matched`, and those rules define `not wired` as "named controls or reads are not backed" (matrix header). House precedent: the §3.4 Sales records, §3.8 Manage employees and §3.9 Notifications ASSUMPTIONs. The grade now follows that rule.
8. **accept** (Solution, stories 3 and 28, and an ASSUMPTION rewritten): "colours come from the capture" contradicts ADR-0010, which keeps the App accent "on every other screen" outside Messages Pro. The plan's Phase 1 Work 1 transcribes "tabs, KPI tiles, labels, order, spacing", with no colours. Capture colours are now recorded as ADR-0010 differences, not copied.
9. **accept** (Interfaces and Testing rewritten): the vitest catalogue check is circular. The ticket writes both the catalogue and the test, so a catalogue typed from memory passes. The test now reads `docs/infloww-layouts/dashboard.md` and asserts each catalogue label and its cited source occur in that file.
10. **accept** (relay case rewritten): the "report time zone cuts the day" relay case tests nothing the header uses. `toLocalIso` sends `Z` instants (`app/lib/dateRange.ts:79-86`), and `_parse_date` applies the zone only to bare dates (`service/stats.py:126-133`). The case now seeds sales either side of a west-of-UTC midnight and queries with the instants the period function produces.
11. **accept** (Owns and Contracts rewritten): "`test_role_enforcement.py`'s copy of the map follows it" is false. The test holds no copy; it reads `permissions.PAGE_MAP` (`service/tests/test_role_enforcement.py:82`, `:278`, `:314`). Adding `per-employee` to `/` leaves Employee reports with routes of its own (`attribution-coverage`, `per-automation`, `service/permissions.py:191-194`), so `SHARED_ONLY` does not change. The test needs no edit and stays in Acceptance.
12. **accept** (Evidence placement, Owns and an ASSUMPTION rewritten): the one-off `clone-dashboard.png` was justified at rung 5, but rung 3 settles it first. The shot it says it follows, `clone-messages-pro.png`, is a `scripts/ui-shots.sh` output (`:30-31`, `:1366-1369`) that the harness deletes and regenerates. The Clone shot is now a ui-shots flow. Whether the temp relay serves `dashboard.html` is ASSUMPTION (evidence blocked: `server.py` was outside the workspace).
13. **partial** (Matrix edit rule): the regraded row would keep citing `app-dashboard.png` and `phone-dashboard.png` (matrix row 3.1), which no script in `scripts/` regenerates (`grep -rn app-dashboard scripts` finds nothing). They are dropped unless re-shot. Not taken: adding a ui-shots flow for them, since the walk shots and the REA recheck already carry the visual evidence.
14. **partial** (Existing blocks and an ASSUMPTION added): `CompetitorReports` stays on `/` with its own Net/Gross dropdown and its "Net earnings (×0.8)" estimate (`CompetitorReports.tsx:392`). The page would then show two Net controls and two different Net figures. Its internals stay out of scope, but the spec now says the header's switch does not drive it, the header's Net is only `net_cents`, and the difference list records the estimate. Not taken: removing it from `/`, because story 21 and ADR-0003 keep extras.
15. **partial** (story 6 and URL rewritten): falling back to "the capture's default tab" has no rule for when the capture records no default, and the Inventory names none (`docs/infloww-screens.md` §3.1). The fallback is now Today, flagged ASSUMPTION.
16. **reject**: "a signed-out Dashboard read is global". `clamp_account_filter` returns `None` for an unauthenticated caller (`service/auth.py:343-344`). But `_harness.make_client()` is `TestClient(server.app)` with its middleware (`service/tests/_harness.py:88-102`), and that middleware 401s anonymous `/admin/*` (`test_account_isolation_gate.py` case 12). The spec's 401 case and its parking ASSUMPTION already cover this.
17. **reject**: "Depends on is missing Phase 3, since `CompetitorReports` embeds a Creator Reports clone". This Phase only places that block and does not change it, and Phase 3 rebuilds `/analytics/creator-reports`, not `components/home`. Neither Phase reads the other's output.

Six hats (2026-10-17, `.scratch/infloww-parity-round-2/review/six-hats.md`):
- SH7 **accept** (no change here). The Matrix row proposal already follows the matrix header (`not wired`, else `intentionally improved` with labelled extras, else `matched`); Phase 6's gate is fixed to accept it.
- SH9 **accept.** Item 17's reject is superseded by coordinator ruling 5: Phase 3 owns `CompetitorReports`' insides and this Phase treats it as a black box (Owns, Existing blocks, seam 1 mocks it, Out of Scope, Depends on, ASSUMPTION). The ×0.8 specifics are dropped from this spec. `PAGE_MAP`: this Phase adds only the `/` entry's route, merged in wave order.
- SH12 **accept** (no change). §3.1 stays `not wired` while a tile is Not wired.
- SH13 **accept.** No matrix edit; the row goes to the recheck record (Objective, Owns, Matrix row proposal, Acceptance, Out of Scope, ASSUMPTION).
- SH15(e) **partial.** True: if the capture lacks a Referrals tile, the Input rule drops it and §3.1 may grade above `not wired`. Nothing is decided in advance; story 15 and the Referrals ASSUMPTION already apply only "if the capture shows it".

No needs-human: every material objection was settled by ADR, plan or code text.
