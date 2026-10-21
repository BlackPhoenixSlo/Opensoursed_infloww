# Phase 05 — Billing, Your Balance, About Inflowwww

**Objective.** The three remaining unbuilt Settings tabs (Billing, Your Balance, About Inflowwww; `SETTINGS_TABS` rows 5, 6 and 11) render real Panels, so no Settings tab is unbuilt: `NotBuiltYet` is gone from the Settings route and no non-legacy `SETTINGS_TABS` entry is `notBuilt`.

## Measured gap table

Ground truth is the plan's table (rung 2) and the Dashboard bundle `index.9fc9db54.css`, read with grep only. Values measured here but not in the plan's table are marked ASSUMPTION.

| Ground-truth selector → value | Ours (`file:line`) | Gap | Change |
|---|---|---|---|
| `._about-header_rxwf7_9` / `._billing-header_6tj53_47`: 48px, margin 0 24px, bottom border `--tc-L1`, text 16px/500 (plan row "Page header") | `app/app/settings/[tab]/page.tsx:16` renders `NotBuiltYet` | no Panel header | Each tab uses Phase 0's `SettingsPanel` Panel header: "Billing", "Your Balance", "About" (§3.10 row 11 [CL] "About") |
| `._personal-info-wrap_rxwf7_132` padding 24px; `._title_rxwf7_137` 14px/500 `--tc-T1`; `._table-wrap_rxwf7_143` gap 40px | same | none | Billing and Your Balance are built from `Section` |
| `._about-logo_rxwf7_31 img` 88x88px, margin-bottom 24px | none (no logo asset in `app/public/`; the app's brand is the text wordmark, `app/components/shell/TopBar.tsx:66-69`) | no logo | 88x88 logo, 24px below |
| `._join-beta-wrap_rxwf7_40` 760px, padding 16px, radius 4px | none | the beta box | Not built (plan: no beta box) |
| `._about-wrap_rxwf7_25` flex, centred both ways; `._about-logo_rxwf7_31>div` margin-bottom 32px; `._about-version_rxwf7_37` colour `--tc-T1` | none | not centred, no version line | About content is centred in the Panel; the version line uses `--if-fg`; 32px between the version line and the links |
| `._billing-tabs-wrap_6tj53_60` padding 0 24px; `._billing-table_6tj53_29 .ant-table-cell` 13px | none | no subtabs, no table | Subtab strip padding 0 24px; invoice table cells 13px |
| `._translation-item_rxwf7_369` border `--tc-L1`, radius 8px, padding 24px, title 14px/600 (plan row "Bordered card") | none | no cards | The Billing plan card and the four balance cards use this card |
| `._balance-amount-text_1dq9x_21` 14px/500 `--tc-T2`; `._balance-amount_1dq9x_13` 32px/600 | none | no amounts | Balance card label 14px/500 `--if-fg-2`, amount 32px/600 `--if-fg` |
| Version: `app/package.json:3` `"0.1.0"`, already shown by `app/components/shell/Sidebar.tsx:32,158` | none in Settings | no version | "Version {version}", imported as in `Sidebar.tsx:32` |
| `/download` → `public/download.html` (`app/next.config.ts:180`), linked by a plain `<a>` in `app/app/settings/layout.tsx:11-21` | none in About | no link | "Desktop app" link, plain `<a href="/download">` |
| Licence: `LICENSE:1` "MIT License" | none | no link | "MIT License" link |
| `SETTINGS_TABS` entries built with `nb()` (plan cites `nav.ts:159-169`; observed `app/lib/nav.ts:160-170`) | `app/lib/nav.ts:160-170` | all 11 `notBuilt` | Plain `{label, href}` objects, the six Blob tabs keeping Phase 0's `chatterHidden: true`; the `nb` helper itself stays (still used at `nav.ts:113-115,147`) |

ASSUMPTION: the `_about-wrap_rxwf7_25` centring, the 32px gap, the `--tc-T1` version colour, the `6tj53` subtab padding and 13px cells, and the `1dq9x` amount type are measured in the Dashboard bundle but are not in the plan's table; `1dq9x` is not tied to the Settings route in the bundle and may be the wallet top-up screen. Overturned if Phase 6's parity review attributes these selectors elsewhere.
ASSUMPTION: the plan card and the balance cards take the "Bordered card (translation)" geometry, the only bordered card in the plan's table. Overturned if a Billing or Balance card selector is found in `rxwf7`.

## Problem Statement

An Agency owner who opens Billing, Your Balance or About Inflowwww sees a "not built yet" placeholder, so Settings looks unfinished and does not match Infloww's layout. The OF referral earnings the Relay already serves cannot be seen in Settings, and the app's version and licence are only a footer line.

## Solution

Billing shows Infloww's layout with honest content: Inflowwww is self-hosted and free, there are no invoices, and every payment action is visibly not wired. Your Balance shows the selected Creator's Referral balance and referral payouts, and in All-Creators scope asks for a model instead of fetching. About shows a logo, the version from `app/package.json`, and links to the desktop app and the licence. With these three, every Settings tab is built and the unbuilt marker is removed.

## User Stories

1. As an Agency owner, I want the Billing tab to open a Panel headed "Billing", so that it matches Infloww's layout.
2. As an Agency owner, I want subtabs "Infloww subscription" and "AI Copilot" on Billing, so that the layout matches Infloww's.
3. As an Agency owner, I want a plan card reading "Inflowwww — self-hosted, free" under "Infloww subscription", so that I know there is nothing to pay.
4. As an Agency owner, I want "Pricing plans", "Update card", "Cancel subscription", "Billing information" and "Make a Payment" shown disabled with the tooltip "not wired", so that I can see what is missing and nothing fakes success.
5. As an Agency owner, I want an invoice table whose empty state reads "No invoices", so that I can see there is no billing history.
6. As an Agency owner, I want Billing to make no request at all, so that a static page never reads or writes the backend.
7. As an Agency owner in Single-Creator scope, I want Your Balance to show four cards (Total earnings, Available to withdraw, Pending earnings, Withdrawn) from the Relay's referral balance for that Creator, so that I can see the Creator's Referral balance.
8. As an Agency owner in Single-Creator scope, I want the Creator's referral payouts listed under the cards, so that I can see what was paid out.
9. As an Agency owner, I want a card whose value the Relay did not return to show "—", so that a missing number is never shown as 0.
10. As an Agency owner in All-Creators scope, I want Your Balance to say "Select a model to see its balance" and fetch nothing, so that a per-Creator figure is never shown for all Creators.
11. As an Agency owner, I want the About Inflowwww tab to show an 88px logo and "Version {version}" read from `app/package.json`, so that I can tell which build I run.
12. As an Agency owner, I want About to link to "Desktop app" (`/download`) and to the licence, so that I can get the desktop app and read the terms.
13. As an Agency owner, I want About to show no beta box and no build hash, so that nothing promises a programme or data we do not have.
14. As an Agency owner, I want no Settings tab to show the "not built yet" placeholder, so that Settings is complete.
15. As a maintainer, I want `nav.test.ts` to fail if a non-legacy `SETTINGS_TABS` entry is `notBuilt`, so that an unbuilt tab cannot return.
16. As a maintainer, I want vitest seams `BillingTab.test.tsx`, `BalanceTab.test.tsx` and `AboutTab.test.tsx`, so that each Panel's behaviour is pinned.
17. As a maintainer, I want the Settings walk to show the four synthetic cards on Your Balance in scope `model:acc1` and record no write on any of the three tabs, so that the Phase is accepted on the real page.
18. As a maintainer, I want `docs/screenshots/settings-billing.png`, `settings-balance.png` and `settings-about.png` committed after the Visual loop, so that the result is on record.

## Implementation Decisions

- **Owns.** New `BillingTab`, `BalanceTab`, `AboutTab` under `app/components/settings/`, with their three tests; their entries in `SETTINGS_PANELS`; the Settings `[tab]` route (drops `NotBuiltYet`); `SETTINGS_TABS` in `app/lib/nav.ts` (drops `nb()` on the 11 Settings tabs); one case in `app/lib/nav.test.ts`; the Phase 5 checks in `scripts/settings-check/walk.py` and its mock data; three PNGs in `docs/screenshots/`.
- **Interfaces.** Each tab is a client component with no props, mapped by the full href (`"/settings/billing"`, `"/settings/balance"`, `"/settings/about"`) in `SETTINGS_PANELS` (Phase 0; Cross-spec decision (b)). They are built only from Phase 0's `SettingsPanel` parts (Panel header, `Section`, `NotWired`) and read only `--if-*` Infloww tokens (ADR-0009). The `[tab]` route renders `SETTINGS_PANELS[href]` for a non-legacy tab and `notFound()` when an href has no Panel. The `NotBuiltYet` component stays, because other routes still use it.
- **Schema.** None — no Blob tab here: `billing`, `balance` and `about` stay off the `/admin/settings` allow-list (ADR-0007), and none of these Panels shows the "not applied yet" note (ADR-0008), because none stores anything.
- **Contracts.** Your Balance reads two existing Relay routes, unchanged (`service/server.py:6926,6931`), through `relay.get(path, { accountId })`, which sends `X-Account-Id` (`app/lib/relay.ts:58`), as the OF mirror does (`app/lib/ofMirrorData.ts:634`):
  - `GET /api/of/v2/payments/referrals/balance` — observed response field `referralEarnings` (`library/of_api_reference/GET_api2_v2_payments_referrals_balance.md`). Card map: Total earnings ← `referralEarnings`; Available to withdraw ← `availableEarnings`; Pending earnings ← `pendingEarnings`; Withdrawn ← `withdrawnEarnings`. A key that is absent or not a number shows "—"; a number shows as USD with two decimals.
  - `GET /api/of/v2/payouts/requests/referral?limit=10` → `{list, marker}`. Each item is the existing `Payout` shape (`app/lib/ofMirrorFeeds.ts:428-436`). Table: Date / Amount / Status, showing `state` as-is. An empty list shows "No payouts".
- Scope comes from `useScope()` (`app/contexts/ScopeContext.tsx:36`). Both queries are `enabled` only when `accountId` is set, so All-Creators scope sends no request; `ScopeProvider` starts at `{kind:"all"}` before it reads localStorage (`app/contexts/ScopeContext.tsx:56`), so the first render fetches nothing either. Both query keys include `accountId` (as `app/lib/ofMirrorData.ts:633`), so switching model never shows the previous Creator's figures. While loading, and when a query fails, the cards show "—"; a failed query also shows the Relay error text under the cards.
- ASSUMPTION: Your Balance is not `chatterHidden` and adds no Relay gate; a chatter linked to a Creator can already read every `/api/of/v2` route for it (`service/server.py:1354-1363`), and the plan asks for no access change. Overturned if the human wants referral earnings owner-only (then `chatterHidden` in `nav.ts` plus a server check).
- Billing has no subtab route: the subtab is local state. "Infloww subscription" shows the plan card with the four `NotWired` actions, then the invoice table (Invoice / Period / Amount / Status, empty "No invoices"), with `NotWired` "Make a Payment" above it. "AI Copilot" shows the same empty invoice table.
- About: the 88x88 logo is a tile drawn from the "Inflowwww" wordmark (no new asset). The version line is "Version {version}", imported from `@/package.json` as `Sidebar.tsx:32` does. "Desktop app" is a plain `<a href="/download">`, as in `layout.tsx`. "MIT License" links to `LICENSE` on the main branch of the public repo that `Landing.tsx:207` already links (the implementer reuses that URL; this spec does not copy it), with `target="_blank" rel="noopener noreferrer"`.
- ASSUMPTION: the three card keys besides `referralEarnings` are not observed (the only captured response is 22 bytes with `referralEarnings` alone). They are named here so the cards have one map; live they render "—" until OF sends them. Overturned by a captured balance response with more fields.
- ASSUMPTION: amounts are dollars (not cents), shown with `toLocaleString("en-US", {style:"currency", currency:"USD"})` as in `app/components/home/CompetitorReports.tsx:96`. Overturned if a live capture shows cents.
- ASSUMPTION: payouts take `limit=10` (the route's default), with no paging, and Status shows the raw `state`. Overturned if Phase 6 wants the OF mirror's "Payout has been processed" wording.
- ASSUMPTION: the AI Copilot subtab shows only the empty invoice table; §3.10 names the subtab and nothing in it. Overturned by a help-center source for its content.
- ASSUMPTION: the invoice columns are Invoice / Period / Amount / Status (`._period_6tj53_29` hints at Period; statuses from §3.10 row 5). Overturned by a Billing capture.
- ASSUMPTION: the logo is a wordmark tile, because the app ships no logo image (rung 5: no new asset). Overturned if a logo asset is added.
- ASSUMPTION: the licence link targets the repo `Landing.tsx:207` links to (rung 3). Overturned if the public repo moves.
- ASSUMPTION: an href with no Panel gives `notFound()` (rung 5), so removing `NotBuiltYet` leaves no placeholder path. Overturned if the human wants a visible fallback.

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

- `BillingTab.test.tsx`: both subtabs render; all five actions are disabled with the "not wired" tooltip; the invoice table shows "No invoices"; a `fetch` spy is never called.
- `BalanceTab.test.tsx` (`renderWithProviders`, `useScope` mocked as `app/components/assistant/AssistantWidget.test.tsx:37` does, Relay mocked at `fetch`): Single-Creator scope with a synthetic balance of four amounts shows four cards with their values, requests exactly `GET /api/of/v2/payments/referrals/balance` and `GET /api/of/v2/payouts/requests/referral?limit=10`, each with `X-Account-Id`; switching the mocked scope to a second account shows that account's values, not the first's; a balance missing `pendingEarnings` shows "—" on that card; payouts render rows, or "No payouts"; All-Creators scope shows "Select a model to see its balance" and `fetch` is never called.
- `AboutTab.test.tsx`: the text "Version " plus `version` imported from `@/package.json`; the logo is 88px; links to `/download` and the licence; no "beta" text.
- `nav.test.ts`: a case beside the OF Manager one (`:78-83`): `SETTINGS_TABS.filter((t) => !t.legacy && t.notBuilt)` equals `[]`; and the six Blob tabs still carry `chatterHidden` (Phase 0's decision survives the `nb()` removal).
- Settings walk (`walk.py`): with `chatterly:scope = model:acc1` set by an init script (as `scripts/of-mirror-check/settings_values.py:34`), Your Balance shows the four synthetic cards from the mocked balance (for example 120.00 / 80.00 / 25.00 / 15.00). Your Balance in that scope also shows the synthetic payout row; with scope `all` it shows "Select a model to see its balance" and records no request to either referral route. Billing, Your Balance and About record an empty Write list. Every one of the 11 non-legacy tabs must render `[data-settings="panel-header"]` with no 404 (with `NotBuiltYet` gone, an unmapped tab would `notFound()` instead of showing the marker, so the marker check alone no longer catches it). Its existing `NotBuiltYet`-marker failure now has no Phase 0 allowance left for these three tabs.
- Prior art: `app/lib/nav.test.ts:78-83`; `app/components/assistant/AssistantWidget.test.tsx` (scope mock); `scripts/of-mirror-check/settings_values.py` (scope init script, mocked Relay).

## Acceptance

```sh
set -e
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run components/settings/BillingTab.test.tsx components/settings/BalanceTab.test.tsx components/settings/AboutTab.test.tsx lib/nav.test.ts
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
./venv/bin/python service/tests/test_settings_api.py
! grep -rn NotBuiltYet app/app/settings || exit 1
! sed -n '/^export const SETTINGS_TABS/,/^];/p' app/lib/nav.ts | grep -n 'nb(' || exit 1
(cd app && npx next dev --webpack -p 3091 >/tmp/settings-dev.log 2>&1 &)
until curl -sf -o /dev/null http://localhost:3091/settings/about; do sleep 2; done
rm -rf /tmp/settings-shots
python3 -I scripts/settings-check/walk.py
pkill -f "next dev --webpack -p 3091" || true
# copy this walk's PNGs (Cross-spec decisions (e), (f))
for t in billing balance about; do cp "/tmp/settings-shots/settings-$t.png" docs/screenshots/; test -s "docs/screenshots/settings-$t.png"; done
scripts/settings-check/export-check.sh   # the plan's throwaway-tree recipe, scoped to lines this effort added (hits inherited from before the effort base are reported, not failed)
# manual: the implementer Reads /tmp/settings-shots/settings-{billing,balance,about}.png, runs the Visual loop (up to three rounds), records the rest as VISUAL GAP:
```

## Depends on

- Phase 0: `SettingsPanel` parts (Panel header, `Section`, `NotWired`), the `--if-*` Infloww tokens, `SETTINGS_PANELS` in the `[tab]` route, and `walk.py` with its mocked Relay (including the referral balance and payouts) and Write list.
- Phases 1–4: their Panels must be registered in `SETTINGS_PANELS` before `NotBuiltYet` and the `nb()` calls are removed (plan: "When this Phase ends"), or those tabs would `notFound()`; the walk's per-tab Panel-header check is what fails then. (The `nav.test.ts` case depends only on the `nb()` removal.)

## Out of Scope

- Payment, invoices, wallet top-up, and "Pay with Wallet" / "Credit Card" / "Bank Transfer" flows: no backend (§3.10 row 5), and `NotWired` covers the entry points.
- "Request withdrawal" and any other Balance action: the plan lists none, and the Relay has no withdrawal route.
- An agency-wide balance summed over Creators: the Referral balance is per Creator (glossary), and the plan wants no fetch in All-Creators scope.
- The beta box and a build hash: excluded by the plan.
- A logo asset, Suisse Int'l font: no new asset; the font is a recorded visual gap (Constraints).
- A `nav.test.ts` check that every Settings href has a `SETTINGS_PANELS` entry: the plan asks only for the `notBuilt` case, and the Settings walk's per-tab Panel-header check fails on an unmapped tab.
- Removing the `nb` helper or `NotBuiltYet` component: other routes still use them (`nav.ts:113-115,147`; `app/app/help-center/page.tsx`).
- `docs/settings-parity.md` and the sign-off: Phase 6.

## Further Notes

- Each ASSUMPTION is stated where it is decided, above.
- The plan's `nav.ts:159-169` is one line off the file today (`:160-170`); the decision ("drop `nb()` from the 11 Settings tabs") is unchanged.

## Review

Reviewer: codex (blind call, then draft call), 2026-10-13.

Blind call:
- B1 Phases 0–4 not landed, so removing `NotBuiltYet` is unsafe (`[tab]/page.tsx:8-16`, `nav.ts:160-170`) — **reject**: Phases run in order and Depends on already requires Phases 0–4; the current checkout is the pre-Phase-0 state by design.
- B2 Billing alternatives (omit the invoice table, wire real billing) — **reject**: the plan's Phase 5 Decisions fix the static Billing with an empty invoice table and `NotWired` actions (rung 2).
- B3 Your Balance could read `/api/of/v2/payouts/balances` instead (`server.py:5848`) — **reject**: the plan names the referral balance and payouts routes (rung 2); the glossary's Referral balance is per Creator.
- B4 the 88px logo is ungrounded and ADR-0001 forbids Infloww's logo — **reject**: the spec already draws an Inflowwww wordmark tile, no Infloww asset.
- B5 placeholder removal needs every non-legacy tab mapped — **accept**: with `NotBuiltYet` gone an unmapped tab would `notFound()` and the marker check would not see it; the walk now requires `[data-settings="panel-header"]` on all 11 tabs, and Out of Scope and Depends on say so.
- B6 Your Balance is visible to chatters and the Relay lets a linked chatter read it (`nav.ts:159-170,182-190`, `server.py:1354-1363`) — **partial**: no new gate (plan asks for none; the same access already covers every `/api/of/v2` route), recorded as an ASSUMPTION naming what would overturn it.
- B7 Balance data behaviour unspecified (mapping, format, paging, loading, error, scope change) — **partial**: mapping, USD format, `limit=10` and error text were already decided; added loading → "—" and `accountId` in both query keys so a model switch never shows stale figures.
- B8 scope hydration could fire a premature request (`ScopeContext.tsx:55-69`) — **partial**: rejected as a bug (the provider starts at `all`, so `enabled` blocks the first render), but the reason is now written into Implementation Decisions.
- B9 Billing invoice columns and "Billing information" undefined — **reject**: columns are decided (flagged ASSUMPTION) and "Billing information" is a `NotWired` action per the plan.
- B10 the seam should assert both GET paths, `X-Account-Id`, no stale data, and an owner/chatter service check — **partial**: `BalanceTab.test.tsx` now asserts both exact paths with `X-Account-Id` and a scope switch; the service check is rejected (no service change in this Phase, see B6).
- B11 the four-field mapping is unproven (`infloww-screens.md:482`) — **reject**: already an ASSUMPTION with its overturning evidence (a captured response); a missing key renders "—", never a wrong number.

Draft call:
- D1 "the last three Settings tabs" is false; they are rows 5, 6, 11 (`nav.ts:164`) — **accept**: Objective now says the three remaining unbuilt tabs, rows 5, 6 and 11.
- D2 the `nav.test.ts` case does not depend on Phases 1–4 — **accept**: Depends on rewritten; the case depends only on dropping `nb()`, the Panel registrations are what the walk checks.
- D3 Acceptance passes with payouts broken — **partial**: `BalanceTab.test.tsx` (in the Acceptance vitest line) already covers rows and "No payouts"; the walk now also requires the synthetic payout row.
- D4 About acceptance checks only the version — **reject**: that is the plan's Acceptance; this spec's `AboutTab.test.tsx` also pins the 88px logo, both links and no "beta" text, and runs in the Acceptance block.
- D5 no-fetch in All-Creators scope is not a walk check — **partial**: the unit test already pins it; the walk now also checks scope `all` sends no request to either referral route.

No finding was left unanswered by evidence; no needs-human line.

### Six hats

Six hats report (`.scratch/settings-tabs/SIX-HATS.md`), 2026-10-13, reconciled by the plan reviewer. Cross-spec items (a)–(f) are decided under Implementation Decisions, "Cross-spec decisions".
- White, "three of the four balance keys never seen in a real response" (phase-05:68) — **reject** as a change: already ASSUMPTION, and a missing key renders "—", never a wrong number; listed in plan-review Open questions.
- Black (a), "no `set -e`; negated checks never fail" (phase-05:88,94,95) — **accept**: `set -e` added; both `!` lines end `|| exit 1`.
- Black (b), "`SETTINGS_PANELS[href]` against Phase 0's last segment" (phase-05:59) — **accept**: Interfaces names the three full-href keys.
- Black, "only Balance considers Chatter access" (phase-05:65) — **accept** (knock-on of Phase 0's decision): the six Blob tabs keep `chatterHidden: true` when `nb()` is dropped, and the `nav.test.ts` case asserts it; Your Balance stays visible under its own ASSUMPTION.
- Black (e)/(f) — **accept** (knock-on): the block had no `cp`; it now clears `/tmp/settings-shots` before the walk and copies the three PNGs from it.
- Green, "`notFound()` fallback beyond the plan" (phase-05:75) — **partial**: kept (rung 5: once plan:286 removes `NotBuiltYet`, an unmapped href needs some answer, and a 404 is the smallest); listed in Open questions.
- Green, "external GitHub licence link" (phase-05:67) — **partial**: kept (plan:284-285 asks for a licence link, rung 2; the target follows `Landing.tsx:207`, rung 3); listed in Open questions. Reviewer finding: the line spelled out a real account handle in the URL; it now points at the existing link instead of copying it.
