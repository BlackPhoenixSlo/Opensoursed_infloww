# Phase 03 — Creator reports matches the bundle

**Objective.** `/analytics/creator-reports` renders the Overview / Creator performance tabs, the filter bar and every section exactly as the Layout capture `docs/infloww-layouts/analytics-creator-reports.md` records them, wired to the relay's existing per-Creator reads or marked Not wired. Ingest health and every other non-bundle element stay reachable under the "Inflowwww extra" label, and the Parity matrix row `3.4 Creator reports` moves off `unverified`.

## Problem Statement

An owner or chatter who knows Infloww opens Analytics → Creator reports and does not recognise the page. The page is the generic report shell (`StatsReport`, view `creator`). It has a title and blurb, an "All messages…" link, a 7d/30d/custom picker, a Refresh button, a grid of per-model KPI cards and an Ingest health strip. Infloww shows a page header, two tabs ("Overview" and "Creator performance"), a filter bar (date range, Creator tag, Creator, Show net earnings, Reset) and named sections: Earnings summary, Growth rate, Earnings trends, Earnings by channel, Earnings breakdown, Creator statistics, and on the performance tab Earnings growth, Earnings breakdowns, Earnings heatmap and Chargebacks (Inventory §3.4, `docs/infloww-screens.md:268`). The last sign-off graded the row `unverified` because none of these sections exist on the route (`docs/infloww-parity-matrix.md:181`).

Much of that layout already exists in the wrong place. The Dashboard embeds `CompetitorReports` (`app/components/home/CompetitorReports.tsx`), a ~1300-line "Creator Reports" card with Overview / Creator performance tabs, Earnings summary, Earnings trends, Creator statistics, Custom metrics and Export CSV. It also fakes two things. Net earnings is gross × 0.8 (`NET_RATIO`), and "Refunded" is a hard-coded `$0`. Its window is the browser's days, not the Agency's report time zone.

## Solution

The Creator reports route shows Infloww's page, as the Layout capture records it. The header and tabs come first, then the filter bar, then the sections of whichever tab is selected, with every label, order, column, empty state, spacing value and colour taken from the capture. The body is the existing `CompetitorReports` card, rebuilt against the capture and moved onto this route, so Creator reports and the Dashboard embed share one module. The window comes from the shared report range, in the Agency's report time zone. "Show net earnings" reads Inflowwww's real net (`include_net`, OF's own post-fee figure), not a ratio. A section or filter with no relay read behind it (Creator tag, Platform fee, VAT collected, Refunds, Chargebacks, and any other the capture names) renders with the house Not wired marker. It never shows a made-up number. Earnings by channel is one of Infloww's sections (Inventory §3.4, C[H276166]), so it sits where the capture puts it. Ingest health, the "All messages…" link and the per-model KPI cards stay one click away in the page's "Inflowwww extras" overflow (or wherever the capture leaves room), each labelled "Inflowwww extra". Before the ticket closes, the page is rechecked against the bundle with REA, and the matrix row is regraded with the Route walk shot beside the REA capture.

## User Stories

1. As an owner, I want `/analytics/creator-reports` to open on a page header titled the way the Layout capture records it, so that the page reads as Infloww's Creator reports.
2. As an owner, I want the "Overview" and "Creator performance" tabs in the capture's order, style and position, so that I switch views the way I do in Infloww.
3. As an owner, I want the Overview tab selected on first load when the capture says so, so that the landing view matches Infloww.
4. As an owner, I want a `?tab=` link to open that tab, the way `useTabParam` seeds a tab on the pages that already use it, so that a reload or a shared link opens the same tab. The report pages keep their date range in component state (`useReportRange`), and that does not change here.
5. As an owner, I want the filter bar with the capture's controls in the capture's order (date range, Creator tag, Creator, Show net earnings, Reset), so that filtering works like Infloww.
6. As an owner, I want the date range to send the Agency's report time zone midnights, as every report page does today, so that Creator reports and Employee reports count the same days.
7. As an owner, I want the "Creator" filter to list the Agency's own Creators and narrow every section to the ones I pick, so that I can read one Creator or several.
8. As an owner, I want "Show net earnings" to switch every money figure that has a net read to OF's own net (`net_cents`), with a disclosed count when some rows have no net. A figure with no net read shows the Not wired marker while net is on: each per-kind money column of Creator statistics, Pending, LTV and ARPU, since `/admin/stats/per-model` gives net only as a per-Creator total. That way net is never an estimate.
9. As an owner, I want "Reset" to put every filter back to its default, so that I can start over in one click.
10. As an owner, I want "Creator tag" shown disabled with `title="not wired"`, because Inflowwww has no Creator tags, so that I see the control without being misled.
11. As an owner, I want the Overview's "Earnings summary" with the capture's tiles and labels, filled from the relay's revenue-by-kind read, so that the totals match Infloww's breakdown.
12. As an owner, I want "Growth rate" as the capture lays it out, computed from the same revenue read over the selected window and the window before it, or Not wired if the capture's definition needs data the relay lacks, so that no growth figure is invented.
13. As an owner, I want "Earnings trends" with the capture's Hour / Day / Week / Month switch, so that I bucket earnings like Infloww. A bucket the relay cannot serve (Hour, since `/admin/stats/revenue` groups by day only) is disabled with the Not wired marker.
14. As an owner, I want "Earnings breakdown" (the pie) and "Earnings by channel" with the capture's labels and positions, so that I see each channel's share as Infloww shows it.
15. As an owner, I want the breakdown rows the capture lists (Gross earnings, Platform fee, VAT collected, Chargeback ratio, Refunds, Net earnings), each filled from an existing read or marked Not wired, so that every row is either true or plainly unbacked.
16. As an owner, I want "Creator statistics" with the capture's metric tiles, table columns, customisable metrics, "Hide $0 creators" and "Export CSV" on whichever tab the capture shows them (the Clone puts the last two on Creator performance, `analytics-creator-reports.html:509`, `:516`), so that the table and export behave like Infloww.
17. As an owner, I want any metric tile that today shows a constant (the hard-coded "Refunded $0") to be either wired or Not wired, so that no tile shows a fake zero.
18. As an owner, I want the "Creator performance" tab's sections (Earnings growth, Earnings breakdowns, Earnings heatmap, Chargebacks, and whatever else the capture records) laid out as captured, each wired to an existing per-Creator read or Not wired, so that the second tab is Infloww's too.
19. As an owner, I want empty, loading and error states worded and placed as the capture records them, so that an Agency with no sales sees Infloww's empty state.
20. As an owner, I want Ingest health still reachable from this page, behind an "Inflowwww extra" tab or overflow entry, so that I can still check transaction ingest and re-sync or pause an account.
21. As an owner, I want the "All messages…" link and the per-model KPI cards kept behind the "Inflowwww extra" label rather than removed, so that nothing Inflowwww had is lost (ADR-0003).
22. As an owner, I want the Refresh control placed and styled as the capture's header control, so that re-fetching stays where Infloww puts it.
23. As a chatter whose role grants Creator reports, I want every read on the page to answer 200, so that the rebuilt page works for me as the old one did.
24. As a chatter whose role lacks Creator reports and the Dashboard, I want the page's reads refused as they are today, so that a role still limits what I see.
25. As an owner of Agency A, I want Creator reports to show only Agency A's Creators and money, so that no other Agency's data ever appears.
26. As a phone user, I want the page usable at 390×844 with no sideways scroll, so that the Parity matrix's Phone cell stays `intentionally improved`.
27. As a reviewer, I want every difference from the Layout capture to carry the "Inflowwww extra" label, so that I reject unlabelled drift.
28. As a reviewer, I want the page's recheck record (`.scratch/infloww-parity-round-2/rechecks/analytics-creator-reports.md`) to show a REA recheck of the page against the bundle, and the Route walk shot beside the REA capture, before it closes, so that the regrade has evidence.
29. As the Phase 6 signer, I want the recheck record to propose the `3.4 Creator reports` matrix row with that evidence, and every kept extra listed under its Labelled improvements, so that Phase 6 regrades and signs from it.
30. As a maintainer, I want `docs/routes.md` to name the module that now renders Creator reports, so that the route table stays true.

## Implementation Decisions

- **Owns.**
  - `CompetitorReports` (the "Creator Reports" card, `app/components/home`). It is rebuilt against the Layout capture and becomes the Creator reports body. Its path and default export stay, so the Dashboard's dynamic import keeps working.
  - `StatsReport`, view `creator` only. Its header for this view follows the capture. Its body becomes `CompetitorReports`. Ingest health and "All messages…" move into the extras overflow. The `employee` and `fan` views are untouched.
  - The Creator reports page entry (`app/app/analytics/creator-reports/page.tsx`), which is unchanged unless the capture's page title differs from today's metadata.
  - `useStats` gains nothing new. `usePerModel` is reused, and the revenue reads already inside `CompetitorReports` gain `include_net=true`.
  - The relay page map in `service/permissions.py` (the Creator reports entry) and its test `service/tests/test_role_enforcement.py`.
  - The Route walk's mock (`/tmp/route-walk-src/walk.py`, never committed), which gains one synthetic Creator so the populated page is shot.
  - The `docs/routes.md` Creator reports line, and the Phase 3 section of `.scratch/infloww-parity-round-2/rechecks/analytics-creator-reports.md` (Phase 0's recheck record contract), which proposes row `3.4 Creator reports` (see Further Notes). It does not edit the matrix.
- **Interfaces.**
  - `CompetitorReports` reads its window from `useReportRange()` (the shared report range: preset, from/to, `fromIso`/`toIso` in the report time zone, `ready`) instead of its own `Date` state. It holds back its queries until `ready`, as `StatsReport` does. It keeps its no-props default export.
  - The tab stays in component state. It is seeded once on mount from `?tab=` by the house hook `useTabParam` (`app/hooks/useTabParam.ts`), which reads `window.location` in an effect, so no `useSearchParams` and no `<Suspense>` boundary is needed. A tab click writes the value back with `history.replaceState`, the same write Phase 1 uses for `?window=`. Values are `overview` | `performance`, matching the bundle's own tab keys (`index.9f50f370.js` near offset 13634517, `E==="performance"`). The Dashboard embed shares this behaviour. `/` uses `?window=`, not `?tab=`, so the two keys never collide.
  - Net/gross becomes a boolean "Show net earnings". When it is on, money figures use `net_cents` from `GET /admin/stats/revenue?include_net=true`: the day and kind queries, plus `by_kind=true` for Earnings by channel. The Creator statistics Total column uses `per_model.total_net_revenue_cents`. Per-kind money columns, Pending, LTV and ARPU have no net read: `per_model.revenue_by_kind` is gross only (`service/stats.py:1320`, `:1365-1367`). While net is on, they render the Not wired marker, and the CSV export writes them empty under a `net` header note. `NET_RATIO` is deleted.
  - The Not wired marker is the house one: `disabled` plus `title="not wired"`. Labels come from `EXTRA_LABEL` / `EXTRAS_OVERFLOW_LABEL` (`app/lib/openinflowwwwExtras.ts`).
- **Schema.** None. No table, column or migration. Every figure comes from reads that exist today.
- **Contracts.**
  - Reads used, all existing: `GET /admin/stats/revenue` (`group_by=day|kind`, `account_id`, `from`, `to`, `include_net`, `by_kind`); `GET /admin/stats/per-model`; `GET /admin/ingest/transactions/health` and its run/pause/resume actions (Ingest health, unchanged); the OF subscriber-count reads `PerModelKpiGrid` already makes.
  - No new relay route, and no request body is guessed (ADR-0005).
  - Page map change: the Creator reports entry in `PAGE_MAP` gains `/admin/stats/revenue`, which today only the Dashboard `/` lists (`service/permissions.py:156-158`, `:188-190`). Without it, a chatter whose role grants Creator reports but not the Dashboard gets a 403 on the Overview's every money read. `route_pages("/admin/stats/revenue")` then reads `("/", "/analytics/creator-reports")`. The `SHARED_ONLY` entry for Creator reports stays, because every Creator reports route is still shared with another page.
  - Identity and Agency isolation are unchanged. They come from the server-side session and the account isolation gate (`clamp_account_filter`, `_account_isolation_middleware`). The page sends `account_id` only as a filter the relay clamps.
- **Layout source.** `docs/infloww-layouts/analytics-creator-reports.md`, written by Phase 0, is the only layout input. `ui-redesign/infloww-exact/analytics-creator-reports.html` is secondary and is consulted only where the capture is silent, and where it is silent and the Clone is too, the element is ours and labelled. The capture wins every disagreement (ADR-0013). Each control gets the Inventory §3.4 `C[…]` tag in a code comment, as the house does.
- **What is ours on this page.** Ingest health, "All messages…", the per-model KPI cards (`PerModelKpiGrid`) and the 7d/30d preset shortcuts. Each one that the capture does not show goes into one `EXTRAS_OVERFLOW_LABEL` overflow in the page header, or into an extra tab after Infloww's two, whichever the capture leaves room for. It never displaces an Infloww element (ADR-0003). The floating chat bubble at the foot of `CompetitorReports` is kept only if the capture shows it. Earnings by channel is not ours. The Inventory lists it among Infloww's sections (`docs/infloww-screens.md:268`, C[H276166]) and the Clone draws it (`analytics-creator-reports.html:477-479`). Its `title={EXTRA_LABEL}` (`CompetitorReports.tsx:447`) and the test that pins that title (`CompetitorReports.test.tsx:21`) are removed, unless the capture lacks the section.
- **Not wired, by default.** These have no relay read and stay Not wired unless the capture's definition matches an existing read: Creator tag; Platform fee and VAT collected (the relay stores gross and OF's net, not the fee and VAT apart); Refunds and Chargebacks (`TRACKED_STATUSES` drops reversals from every stats read); Chargeback ratio, because its one existing read, `GET /api/of/v2/payouts/chargebacks/ratio` (`app/lib/ofMirrorMoney.ts:31`, the OF Manager Statistics page's), is OF's fixed last 30 days (`ofMirrorMoney.ts:11`). It does not follow the page's date range, and it would be a live OF call per Creator; the Hour bucket of Earnings trends; Earnings heatmap if it needs hour-of-day data.
- **Dashboard.** `CompetitorReports` is still imported by `app/app/page.tsx`. This Phase changes what the module renders, but not whether or where the Dashboard mounts it. That is Phase 1's call (plan: Phase 1 owns `/`).

## Testing Decisions

- **Seam 1 (the one that carries the Phase): the rendered Creator reports page, through vitest.** Render `StatsReport` with `view="creator"` inside a `QueryClientProvider`, with `relay.get` mocked by path. The tests assert external behaviour only:
  - The capture's header, the two tabs in order, and the filter controls in order.
  - The Overview sections and the Creator performance sections by their verbatim capture labels.
  - Switching tabs updates `?tab=`.
  - Turning on "Show net earnings" sends `include_net=true` and renders the net figure from the mock. Creator statistics' per-kind money cells then carry the Not wired marker, and Total shows the mock's `total_net_revenue_cents`.
  - A seeded `?tab=performance` opens Creator performance, and a bogus value opens Overview.
  - "Earnings by channel" renders among the Overview sections, in the capture's order, with no "Inflowwww extra" title (unless the capture lacks it).
  - Every Not wired control is `disabled` with `title="not wired"`, and no tile renders a constant `$0` when the mock has none.
  - Ingest health is reachable through the element labelled "Inflowwww extra" or "Inflowwww extras".
  - The date range sends report-time-zone midnights.
  - The empty state, with a mock that has no Creator.
- **Existing tests that ride on the creator view.** `StatsReport.test.tsx:91-157` uses `view="creator"` only as a vehicle for the shared date range. It asserts the per-model `from`/`to`, the "To date" input, and the 7d/30d/Custom presets. Those cases move to `view="employee"`, which uses the same `useReportRange`, so they keep guarding the other views. The creator view gets its own report-zone case through the revenue read. `CompetitorReports.test.tsx:21`, the "Earnings by channel is an extra" case, is replaced by the capture-label assertion.
- **Seam 2: the relay page map, through `service/tests/test_role_enforcement.py`.** One case: a chatter whose role grants only Creator reports gets 200 on `GET /admin/stats/revenue`, and a role granting neither page gets 403. The existing shared-route case extends to the revenue route. Agency isolation of the reads is already proven by `service/tests/test_account_isolation_gate.py` and `test_stats_revenue.py` (`case_account_filter`, `case_include_net_sums_of_net`, `case_per_model_net_reconciles`). They are run, not extended, because no relay route changes.
- **Not a test seam but a close gate:** the REA recheck against the bundle, and the Route walk shot at 1440×900 and 390×844, light and dark.
- **Prior art.**
  - `app/components/stats/StatsReport.test.tsx`: relay mocked by path, the report-time-zone date assertions, the "no notice on Creator reports" case.
  - `app/components/home/CompetitorReports.test.tsx`: the "Inflowwww extra" title assertion.
  - `app/components/home/ShiftCards.test.tsx`.
  - `service/tests/test_role_enforcement.py`: `case_a_route_shared_by_two_pages_is_allowed_when_either_is_granted`.

## Acceptance

```sh
cd <repo>
# input exists (Phase 0)
test -s docs/infloww-layouts/analytics-creator-reports.md
# effort suite: typecheck, lint, vitest
sh .scratch/infloww-parity-round-2/suite.sh
# the page's own tests
env ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run components/stats/StatsReport.test.tsx components/home/CompetitorReports.test.tsx --testTimeout=20000
# relay: page map, reads and isolation (mocked, no live OF)
./venv/bin/python service/tests/test_role_enforcement.py
./venv/bin/python service/tests/test_stats_revenue.py
./venv/bin/python service/tests/test_account_isolation_gate.py
# no estimated net, no fake Refunded tile
! grep -n -F "NET_RATIO" app/components/home/CompetitorReports.tsx
! grep -n -F 'fmtUsd(0)' app/components/home/CompetitorReports.tsx
# Creator reports may read revenue
(cd service/tests && ../../venv/bin/python -I -c 'import sys; sys.path[:0]=[".", ".."]; import _harness, permissions; p = permissions.route_pages("/admin/stats/revenue"); assert "/analytics/creator-reports" in p, p')
# routes doc names the new body
grep -n -F "/analytics/creator-reports" docs/routes.md | grep -F "CompetitorReports"
# the recheck record carries this Phase's differences and a proposed row off unverified (Phase 6 alone edits the matrix)
R=$(sed -n '/^## Phase 3 /,/^## Phase /p' .scratch/infloww-parity-round-2/rechecks/analytics-creator-reports.md)
echo "$R" | grep -q '^### Differences'
echo "$R" | sed -n '/^### Matrix row/,/^### /p' | grep -F '3.4 Creator reports' | grep -qE '(matched|intentionally improved|not wired)'
# manual: serve the bundle (python3 -I -m http.server --bind 127.0.0.1 <port> --directory ~/Downloads/infloww-remote-web, from a directory outside it) and recheck /analytics/creator-reports on 127.0.0.1:3001 against it with REA (capture_web_screenshot / compare_web_screenshots, or the chunk map plus grep -F); every difference is labelled "Inflowwww extra" or fixed, in the recheck record's Differences
# manual: Route walk (/tmp/route-walk-src/walk.py, recreated from the previous plan's ticket 41 if /tmp was cleared) with one synthetic Creator in its mock; analytics-creator-reports shots at 1440x900 and 390x844 pass, beside the REA capture
```

## Depends on

- **Phase 0.** It provides `docs/infloww-layouts/analytics-creator-reports.md`, the Layout capture this Phase transcribes, and a green baseline on the current `main` tip. Nothing in this Phase starts before the capture exists.
- **Not an order dependency, a file overlap with Phase 1.** This Phase owns `CompetitorReports`' insides. Phase 1 owns `/`, the Dashboard entry of `PAGE_MAP` and its `test_role_enforcement.py` cases; it places and labels `CompetitorReports` as a black box and mocks it in its page test (`phase-01-dashboard.md`, Owns, Existing blocks, Depends on), so a rebuilt module changes nothing Phase 1 asserts. This Phase edits only the Creator reports entry of the same two files. Either may land first; `PAGE_MAP` and test edits merge in wave order and label order within a wave, so Phase 1's land first and this Phase rebases on them (plan-review, Workstreams).

## Out of Scope

- New relay reads for Creator tag, Platform fee, VAT, Refunds, Chargebacks or hourly buckets. The plan says "Not wired where no read exists". They become Not wired controls, not tickets.
- Per-tab permissions (Infloww gates each tab with `CreatorReports_Overview` / `CreatorReports_CreatorsPerformance`). Our roles grant whole pages (ADR-0012 page map), and a per-tab grant would be a new permission surface the plan does not ask for.
- Whether the Dashboard keeps embedding `CompetitorReports`. That is Phase 1's decision.
- Editing the Clone page `analytics-creator-reports.html`. Phase 0 fixes Clone pages where they disagree with the capture.
- Renaming or moving `CompetitorReports`. A rename changes no behaviour and would collide with Phase 1's edits to the Dashboard import (YAGNI).
- The Employee reports and Fan reports views of `StatsReport`. They are not among the eight pages.
- Live OnlyFans reads or writes in any test. Mocked relay only, per the plan.

## Further Notes

ASSUMPTION: the Creator reports body is the existing `CompetitorReports` module, rebuilt against the capture, rather than a new module beside it. Rung 5: it already has the two tabs, Earnings summary, Earnings trends, Creator statistics, Custom metrics and Export CSV, so a second copy would be new surface. This is overturned if Phase 1 removes `CompetitorReports` from the Dashboard and the reviewer wants it moved to `app/components/analytics/`. That is a later rename only.

ASSUMPTION: because the module is shared, the Dashboard embed changes with it: report-time-zone window, real net, Not wired tiles. Rung 4: one module is cheaper to undo than two diverging ones, and Phase 1's own decision is that KPI numbers run at the Agency's report time zone. This is overturned if Phase 1's spec freezes the embed as it is. Then `CompetitorReports` takes a `variant` prop.

ASSUMPTION: "Show net earnings" uses the relay's `include_net` (OF's own `net_cents`) and not the old × 0.8. Rung 2: the plan says "any KPI the relay cannot compute is Not wired, not invented", and a fixed ratio is an invented number. This is overturned if the capture defines net as a configurable fee rate the Agency sets.

ASSUMPTION: Platform fee and VAT collected are Not wired, not derived as gross − net. Rung 4: gross − net mixes OF's fee and VAT into one figure, so labelling it either would be wrong. This is overturned if the capture shows only a combined "fees" row.

ASSUMPTION: a `?tab=` link seeds the tab through `useTabParam`, and a click writes the value back with `history.replaceState`. Rung 3: `useTabParam` is the house way to open a tabbed page from a link (`app/hooks/useTabParam.ts`, used by `ReadyMadePanel`), and Phase 1 writes `?window=` the same way. The report pages do not keep their date range in the URL (`useReportRange` is `useState`), so the earlier claim that they keep state there was wrong. This is overturned if the capture shows the bundle keeps it in memory only and the reviewer counts the URL as a difference. It does not render, so it is not a layout difference.

ASSUMPTION: the Creator reports entry of `PAGE_MAP` gains `/admin/stats/revenue`. Rung 1: `service/permissions.py:188-190` lacks it while the rebuilt Overview reads it, so, with enforcement on, a Creator-reports-only chatter would get 403. This is overturned if the owner wants Creator reports money reads tied to the Dashboard grant.

ASSUMPTION: this Phase makes no edit to `docs/infloww-parity-matrix.md`. Its proposed `3.4 Creator reports` row and Labelled improvements lines go into its section of `.scratch/infloww-parity-round-2/rechecks/analytics-creator-reports.md`, and Phase 6 alone regrades the matrix (coordinator ruling 2, 2026-10-17, adopting six-hats 13; rung 4, since the matrix holds the owner's uncommitted Sign-off and Phase 6 regrades every row anyway). Overturned once the owner commits the matrix and wants each Phase to regrade its own row.

ASSUMPTION: while "Show net earnings" is on, the Creator statistics per-kind money columns, Pending, LTV and ARPU render Not wired, and only Total switches to `total_net_revenue_cents`. Rung 5: the alternative is one `group_by=kind&include_net=true` call per visible Creator, an N-call fan-out. A `per_model` net-by-kind field is the other option, and that is a relay change this Phase does not make. This is overturned if the owner accepts the fan-out, or if a later plan adds net by kind to `/admin/stats/per-model`.

ASSUMPTION: Chargeback ratio stays Not wired even though `GET /api/of/v2/payouts/chargebacks/ratio` exists. Rung 4: that figure is OF's fixed last 30 days, so it would contradict the page's date range, and wiring it means a live OF call per Creator plus a new `PAGE_MAP` entry. This is overturned if the capture shows Infloww's ratio as a fixed 30-day figure too.

ASSUMPTION: the Net earnings row shows `net_cents` with no VAT deduction (`service/stats.py:227`, "VAT is tracked separately and NOT deducted"). It carries a one-line disclosure, because the VAT collected row above it is Not wired and the rows will not sum. Rung 4: disclosure is additive. This is overturned if the capture defines Net earnings as after VAT. Then the row is Not wired.

ASSUMPTION: the target grade is `intentionally improved`, because Ingest health, "All messages…" and the per-model KPI cards are labelled extras. If any capture section stays Not wired, the grade is `not wired`. Rung 3: the matrix header's status definitions. This is overturned by Phase 6's regrade.

ASSUMPTION: the Route walk's mock gains one synthetic Creator ("Creator A", no real name) answering `/admin/stats/per-model` and `/admin/stats/revenue`, so the populated page is shot. Rung 5: the last regrade noted "the walk's mock has no Creator, so the populated report is graded from code". The walk lives in `/tmp` and is never committed. This is overturned if Phase 6 adds a shared populated fixture instead.

ASSUMPTION (evidence blocked): the section list above comes from the Inventory and the Clone, because the Layout capture does not exist yet (Phase 0 writes it). One bundle grep confirms the two tabs and a `CreatorFilter` component (`index.9f50f370.js`, near offset 13634517). Every story that names a section binds to the capture's own list: a section the capture lacks is dropped, or kept labelled, and a section the capture adds is built or Not wired. This is overturned by the capture itself.

## Review

weaker (devils-advocate), 2026-10-17. Codex preflight passed (`codex login status`: "Logged in using ChatGPT"). The blind call then failed postflight, exiting 1 with no output file and the log reading "ERROR: You've hit your usage limit … try again at Nov 11th, 2026". The fallback persona could not run as a separate agent, because this run's header forbids spawning sub-agents. So the spec's adversary agent ran the devils-advocate brief itself, confined to the review workspace (plus `docs/spec/infloww-parity-round-2/phase-01-dashboard.md` and `git status` in the repo). It had already read the draft, so the first call was **not structurally blind**. Weigh these findings as one reviewer's, not as an independent second model's. The Infloww bundle was not in the workspace, so no claim about it (`index.9f50f370.js` offsets) was checked.

Call 1 (alternatives, missing requirements, seam, falsifiers):

- **accept.** Earnings by channel is an Infloww section, not ours. Inventory §3.4 lists it among the sections cited C[H276166] (`docs/infloww-screens.md:268`). The Clone draws it (`ui-redesign/infloww-exact/analytics-creator-reports.html:477-479`). Its "probably ours" comment (`CompetitorReports.tsx:446`) quotes text the Inventory row does not carry. Problem Statement, Solution, stories 14 and 21, "What is ours", Testing and the grade ASSUMPTION are rewritten so that it sits where the capture puts it.
- **accept.** Story 4's claim that "the other report pages keep their state" in the URL is false. `app/hooks/useReportRange.ts:17-18` holds the range in `useState`, and Phase 1's spec says so too (`phase-01-dashboard.md:146`). The house hook for `?tab=` is `useTabParam` (`app/hooks/useTabParam.ts:21`). It is mount-only and reads `window.location`, so it needs no Suspense. Story 4, Interfaces and the tab ASSUMPTION are rewritten to use it.
- **accept.** "Every money figure switches to net" cannot be met for Creator statistics. `/admin/stats/per-model` gives gross `revenue_by_kind` and net only as `total_net_revenue_cents` (`service/stats.py:1320-1341`, `:1365-1367`). The table's per-kind money columns (`CompetitorReports.tsx:37-80`) then have no net read. Story 8, Interfaces, Seam 1 and a new ASSUMPTION make them Not wired while net is on.
- **partial.** A Chargeback ratio read does exist: `/api/of/v2/payouts/chargebacks/ratio` (`app/lib/ofMirrorMoney.ts:31`, mapped under OF Manager Statistics, `service/permissions.py:177-179`). So the "no relay read" reason was wrong, and it is corrected. The decision stays Not wired, because the read is OF's fixed last 30 days (`ofMirrorMoney.ts:11`) and is a live OF call per Creator. A new ASSUMPTION names what would overturn this.
- **accept.** The existing `StatsReport.test.tsx:91-157` cases use `view="creator"` as the vehicle for the shared date range. They assert the per-model `from`/`to`, "To date" and the 7d/30d/Custom presets, and the rebuild moves all three, so the cases would break. Testing Decisions now moves them to `view="employee"` and replaces `CompetitorReports.test.tsx:21`.
- **partial.** Relay net is "gross - fee; VAT is tracked separately and NOT deducted" (`service/stats.py:227`), so Net earnings will not reconcile with a breakdown that lists VAT collected above it. Net stays `net_cents`, with a disclosure line, and is Not wired if the capture defines net after VAT (new ASSUMPTION). The reviewer's alternative, deriving VAT, is rejected: no read separates it.
- **partial.** Alternative module: Phase 1 places `CompetitorReports` "without changing its insides" (`phase-01-dashboard.md:53`, `:139`), so reusing it here changes the Dashboard embed. Reuse is kept (rung 5, the existing ASSUMPTION), and the overlap is now recorded under Depends on. It is not made an order dependency, because Phase 1's text bounds only its own edits.

Call 2 (the draft):

- **accept.** The Acceptance matrix line contradicted the spec's own ASSUMPTION and the header. `git status --short docs/infloww-parity-matrix.md` returns ` M docs/infloww-parity-matrix.md` today, so the line would fail, or it would force an edit of an owner file. It is now conditional on `git diff --quiet`, with the ticket carrying the row otherwise.
- **accept.** The Acceptance runs no `next build`. `suite.sh` is typecheck, lint and vitest only. A `useSearchParams` reading of the old Interfaces would pass every line yet need a Suspense boundary, as `app/app/analytics/message-dashboard/page.tsx:78-83` had to add. Resolved by the `useTabParam` rewrite rather than a new build step (smallest fix).
- **partial.** `! grep -F 'fmtUsd(0)'` is brittle: a literal `"$0.00"` or `fmtUsd(0 * x)` passes it. It is kept as a cheap guard. The Seam 1 assertion ("no tile renders a constant `$0` when the mock has none") is the real gate.
- **partial.** Depends on was missing the file overlap with Phase 1 (`service/permissions.py` `PAGE_MAP`, `service/tests/test_role_enforcement.py`; `phase-01-dashboard.md:53`). It is added as a rebase note. It is not a dependency, because the two edit different entries.
- **accept.** Story 16 placed "Hide $0 creators" and "Export CSV" under the Overview's Creator statistics. The Clone has them on Creator performance (`analytics-creator-reports.html:509`, `:516`). The story now binds placement to the capture and cites the Clone.
- **reject.** The suspicion that `service/permissions.py:156-158` / `:188-190` and the test names `case_account_filter`, `case_include_net_sums_of_net`, `case_per_model_net_reconciles` and `case_a_route_shared_by_two_pages_is_allowed_when_either_is_granted` were stale. Every one exists at the cited place (`service/tests/test_stats_revenue.py:192`, `:265`, `:300`; `test_role_enforcement.py:176`).

Six hats (2026-10-17, `.scratch/infloww-parity-round-2/review/six-hats.md`):
- SH7 **accept** (no change here). The target grade `intentionally improved` follows the matrix header; Phase 6's gate is fixed to accept it.
- SH9 **accept.** Coordinator ruling 5: this Phase owns `CompetitorReports`' insides, and Phase 1 treats the module as a black box, so the two Depends on lines now agree (no order dependency; Phase 1 does not assert the module's insides). `PAGE_MAP`: this Phase adds only the Creator reports entry's route, merged in wave order. The recheck goes to one place, the recheck record, not the ticket.
- SH13 **accept.** No matrix edit and no Acceptance line on the matrix file; the proposed row goes to the recheck record (story 29, Owns, Acceptance, ASSUMPTION).

needs-human: none. Every material objection was settled by a file read. The weaker review label itself is the open item: rerun `codex exec` on this spec once the codex quota resets (Nov 11th, 2026) if an independent second model is wanted.
