# Phase 04 — Creators pages match the bundle, extension kept in front

**Objective.** `/creators` leads with the creator table from the Layout capture `docs/infloww-layouts/creators-manage.md`, and its Add creator flow opens with the browser extension's Paste cURL path. `/creators/proxy` shows the columns of `docs/infloww-layouts/creators-proxy.md`, the egress table and an Add action that holds the paste box. Every difference from either capture is Not wired or labelled "Inflowwww extra", and both §3.7 rows are regraded against REA.

## Problem Statement

An agency owner who knows Infloww opens Creators › Manage creators and sees a different page. Infloww leads with a table of Creators: filters, a "Total: N creators" footer, and an "Add creator" button that opens a modal (Inventory §3.7; the bundle's `CreatorManagement` component, `index.9f50f370.js` offset 12502733, route `/admin/creators` at offset 16914062). Ours leads with three capture forms stacked as cards: Paste cURL, Direct login and Fansly paste session. Below them come a five-column "Accounts" table (Account, user_id, Status, Last used, Actions) and four key cards. None of this is labelled as ours (matrix row "3.7 Manage creators", Remaining gap).

Custom proxy has the same problem. Infloww shows "Manage your custom proxies" with "+ Add new proxy" and a paged proxy table. The bundle's `Index$l` component (offset 12517099, route `/admin/creators/proxy`) reads `fetchCustomProxyList` with page size 10, and its columns open with label, host and port. Ours shows a "Proxies" card with a manual form and a bulk paste box that are always visible. Its columns (Label, Host, Bound to, Egress / verified, Actions) are not Infloww's, and it has no Creator egress view (matrix row "3.7 Custom proxy").

The owner still wants the extension in front. Signing a Creator in through the Chatterly Login Capture extension (Paste cURL) is how most Creators get linked. A redesign that buried it, or that dropped the extension probe the Route walk allows for, would break the thing that works.

## Solution

**Manage creators.** The page reads like `creators-manage.md`, in this order: the page title, the filter bar, the creator table with the capture's columns, the footer with the total and "Per page", and the capture's primary button "Add creator".

- **Add creator** opens the capture's modal. Its first section is the extension path: the existing Paste cURL card with its "Extension installed" / "Install Chrome Extension" line. Direct login (email and password) and the Fansly paste session come after it. All three are labelled "Inflowwww extra" because the owner put them there. The capture's own Add creator controls come after our three sections, each mapped to the section that performs it or Not wired. Putting the extension path ahead of Infloww's own first step is the owner's exception to ADR-0003's "no extra may displace an Infloww element", and the recheck record names it as such.
- **The extension probe** still runs once when the page mounts, exactly as today. The Route walk's single `CONSOLE_ALLOW` line still matches it, and the Add flow reads the result the probe already got.
- **Row actions** go in the capture's "⋮" menu. "Delete" is wired to today's delete. "Deactivate" is Not wired, because the Relay has no deactivate. Rename, Mark default and Refresh session are Inflowwww extras in the same menu. Each recovery action the capture holds ("Link account - need to reenter password", "Log in to account via OnlyFans/Login+", "+ Link Creator Account", Inventory §3.7) opens the Add creator modal at the section that performs it, or is Not wired. Login+ is Infloww's phone app, so it is Not wired.
- **The key cards** (agency keys, managed agency keys, and the house keys at Setup → Keys) stay on the page, below the table footer, inside one collapsed disclosure named `EXTRAS_OVERFLOW_LABEL` ("Inflowwww extras"), as Phases 2 and 3 do with their extras. **The drift banner** renders, only while a model is stale, directly below the footer and outside the disclosure, titled with `EXTRA_LABEL`, because a stale-revision alert hidden in a closed disclosure fails its purpose. Neither is moved to another route.

**Custom proxy.** The page reads like `creators-proxy.md`: "Manage your custom proxies", "+ Add new proxy", and the proxy table with the capture's columns, its "No data" empty state and its paging.

- **"+ Add new proxy"** opens the capture's add modal, with its fields (host, port, type, and username and password where the capture shows them). The registry keys a proxy by label, which Infloww's modal has no field for, so the label defaults to `host:port`, as the bulk paste labels its rows, and stays editable in a field titled with `EXTRA_LABEL`. The bulk paste box sits inside that modal as an "Inflowwww extra" section.
- **The egress table** comes below. It has one row per Creator: Creator, Creator ID, Egress (the bound proxy's verified IP, or "No custom proxy"), Session, and a Test action. It is built from the same `GET /admin/proxies` read the page already makes. If the capture has no such table, it is labelled "Inflowwww extra".

Before a ticket closes, both pages are rechecked against the bundle with REA. Each ticket writes a recheck record that lists every difference, and each difference is Not wired, labelled, or fixed.

## User Stories

Manage creators: table first

1. As an agency owner, I want `/creators` to open on the creator table, so that I see my Creators before any setup form, as in Infloww.
2. As an agency owner, I want the table's columns, their order and their header labels to be exactly those of `creators-manage.md`, so that the page reads like Infloww's Manage creators.
3. As an agency owner, I want each row to show the Creator's nickname, platform name, Creator ID and bound proxy in the capture's cells, filled from the reads the page already makes (`GET /admin/accounts`, `GET /admin/proxies`, `GET /health?all_accounts=1`), so that no new Relay call is needed to fill the table.
4. As an agency owner, I want each row's connectivity shown with the capture's status labels ("Connected", "Disconnected", "Pending connection", "Not connected", and any other label the capture holds), mapped from our live health and dead-session states, with a flagged dead session outranking the live probe as it does today, so that I read Infloww's words for our probe results and a paused Creator never reads "Connected".
5. As an agency owner, I want a paused Creator's row to keep naming its repair (the dead-session badge with re-link or re-capture), so that the redesign does not hide why automations stopped.
6. As an agency owner, I want the capture's footer, "Total: N creators" and "Per page" 10 / 25 / 50, to page the table on the client, so that a long roster is browsable as in Infloww.
7. As an agency owner, I want the capture's empty state when I have no Creators, with "Add creator" reachable from it, so that a new agency knows the first step.

Manage creators: filters

8. As an agency owner, I want the capture's search box (Creator name or id) to filter the table as I type, so that I can find one Creator fast.
8a. As an agency owner, I want the proxy filter, if the capture holds one (the Clone's "Any proxy"), wired to each Creator's bound proxy, so that I can list every Creator behind one proxy.
9. As an agency owner, I want the platform filter wired to each Creator's platform (OnlyFans or Fansly), so that I can split the roster by platform.
10. As an agency owner, I want the connectivity filter wired to the same status the row shows, so that I can list every Disconnected Creator at once.
11. As an agency owner, I want the assigned-employee filter wired to Employees' Creator access from `GET /admin/employees`, so that I can see whose Creators are whose.
12. As an agency owner, I want filters that need data the Relay does not hold (Creator tags, account status Activated / Deactivated) shown disabled with the tooltip "not wired", so that nothing pretends to filter.
13. As an agency owner, I want "Reset" to clear every filter, so that I get back to the full list in one click.

Manage creators: Add flow, extension in front

14. As an agency owner, I want "Add creator" to be the capture's primary button, placed where the capture puts it, so that adding a Creator starts where Infloww users look.
15. As an agency owner, I want the Add creator modal to open on the browser-extension path (Paste cURL, with the extension's installed or install line), so that the way most Creators are linked is the first thing I see.
16. As an agency owner, I want Direct login (email and password, no extension) second and the Fansly paste session third in the same modal, so that every way of linking a Creator is still reachable from one place.
17. As an agency owner, I want each of those three sections to carry the "Inflowwww extra" label, so that a reviewer can tell an owner-chosen difference from a mismatch.
18. As an agency owner, I want the capture's own Add creator controls (Creator name, platform, link, "Next" and any others the capture records) either mapped to the path that performs them or shown Not wired, so that the modal never fakes a step our Relay does not do.
18a. As an agency owner, I want each recovery action the capture holds ("Link account - need to reenter password", "+ Link Creator Account", "Log in to account via OnlyFans/Login+") to open the Add creator modal at the section that performs it, or to be Not wired, so that a broken Creator's repair starts from Infloww's words.
19. As an agency owner, I want a successful capture or login to close nothing I am still reading and to refresh the table, as the cards do today, so that the new Creator appears in the list.
20. As an agency owner on a phone, I want "Add creator" to open the same modal, showing the one existing line that session capture is desktop-only, so that I am told why instead of meeting a dead button.

Manage creators: the probe and the walk

21. As the owner, I want the extension probe to stay the same fetch of the same URL, run once when the Manage creators page mounts, so that the Route walk's `CONSOLE_ALLOW` line still matches it and stays in the walk.
22. As the owner, I want the Add flow to read the result the page-mount probe already got, without probing again, so that opening the modal adds no second console message.

Manage creators: row actions and extras

23. As an agency owner, I want the capture's row action menu ("⋮") with "Delete" wired to today's delete (with its confirm and full cache eviction), so that removing a Creator works as before.
24. As an agency owner, I want "Deactivate" in that menu shown disabled with "not wired", so that I am never told a Creator was deactivated when the Relay cannot do it.
25. As an agency owner, I want Rename, Mark default and Refresh session kept in the same menu, each labelled "Inflowwww extra", so that nothing I use today is lost.
26. As an agency owner, I want the agency keys card, the managed agency keys card (Master only) and the house keys card (Master only) kept on `/creators` below the table inside one collapsed "Inflowwww extras" disclosure, and the drift banner shown below the footer while a model is stale, so that keys stay where Setup → Keys has always been and a stale revision is never hidden.

Custom proxy

27. As an agency owner, I want `/creators/proxy` to show the capture's title, "+ Add new proxy" and the proxy table with its columns, order and labels, so that it reads like Infloww's Custom proxy.
28. As an agency owner, I want each proxy row's cells (label, host, port, type, Creator, proxy status, actions, as the capture names them) filled from `GET /admin/proxies`, so that the registry is still the only source.
29. As an agency owner, I want the proxy status cell to come from the stored verification (`verified_ip`, `verified_at`) and the latest test, mapped to the capture's status labels, so that I can tell at a glance which proxy works.
30. As an agency owner, I want the capture's "No data" empty state and its paging (page size 10), so that the empty and the long lists look like Infloww's.
31. As an agency owner, I want "+ Add new proxy" to open the capture's add modal with its fields, with the label defaulting to `host:port` in an "Inflowwww extra" field, saving through today's upsert and its duplicate-label guard, so that adding one proxy works as in Infloww.
32. As an agency owner, I want the bulk paste box (one proxy per line, with its scheme) inside that Add modal, labelled "Inflowwww extra", with its "Added N" and per-line errors kept, so that pasting many proxies is still one step.
33. As an agency owner, I want Bind, Unbind, Test and Remove kept as row actions, mapped to the capture's actions where it has them and labelled "Inflowwww extra" where it does not, with the shared-egress warning kept, so that nothing I use today is lost.
34. As an agency owner, I want a Creator egress table below the proxy table, one row per Creator: Creator, Creator ID, Egress (the bound proxy's verified IP, or "No custom proxy"), Session (has session or not), and a Test action, so that I see which IP each Creator talks to OnlyFans from.
35. As an agency owner, I want the egress table built from the same `GET /admin/proxies` response the page already reads, so that it adds no Relay read and no new tenancy surface.
36. As an agency owner, I want the egress table labelled "Inflowwww extra" unless `creators-proxy.md` records it, so that the review rule holds either way.

Tenancy and roles

37. As an agency owner, I want both pages to show only my Agency's Creators and proxies, so that no other Agency's nickname, id, host or password ever renders or reaches my browser. `test_creators_tenancy.py` proves this today for `GET /admin/proxies` and the assign, and `test_employee_list.py` for `GET /admin/employees`.
37a. As an agency owner, I want `GET /health?all_accounts=1`, which feeds the connectivity column, to answer only for my Agency's Creators and never to carry a proxy URL, so that the table's own read does not hand me another Agency's Creator names, OnlyFans ids or proxy passwords. Today it returns every account on the Relay to every caller, with `proxy.url` holding the proxy's username and password (`service/server.py` `_health_all_accounts`, `_probe_account_blocking`; `service/proxies.py` `proxy_url`), and `/health` sits outside the `/admin/*` isolation gate and is rewritten to the public host (`app/next.config.ts:115`).
38. As a chatter, I want `/creators` to behave as the page map in `service/permissions.py` says today, and `/admin/proxies` to keep refusing me, so that the redesign changes no permission.
39. As a maintainer, I want any new Relay read or write a ticket adds for these pages to get its own negative case in `test_creators_tenancy.py`, so that Agency isolation is proven, not assumed.
40. As a maintainer, I want every test that touches the proxy registry to use a `tempfile.mkdtemp` copy, so that the real registry file is never read or written.

Evidence and review

41. As a reviewer, I want each ticket to recheck its page against the bundle with REA before it closes, and to record the check in `.scratch/infloww-parity-round-2/rechecks/<page>.md`, so that "matches the bundle" is evidence and not a claim.
42. As a reviewer, I want that record to list every difference between our page and its Layout capture, each marked Not wired, "Inflowwww extra" (with where the label renders) or fixed, so that I can reject any unlabelled difference.
43. As a reviewer, I want both §3.7 rows proposed in the recheck records, with the Route walk shots beside the Layout captures (and the Clone shots), so that Phase 6's grade rests on the bundle.
44. As a maintainer, I want the effort suite to run the Creators relay tests (`creators_tenancy`, `proxy_paste`, `role_enforcement`, `direct_login`, `employee_list`, `health_all_accounts`), so that a later Phase cannot break these pages unnoticed.

## Implementation Decisions

- **Owns.**
  - The Manage creators page (`app/app/creators/page.tsx`) and the Custom proxy page (`app/app/creators/proxy/page.tsx`).
  - The creator table (today `AccountsTable`, in `components/setup`).
  - `ProxiesTable`.
  - `PasteCurlCard`, but only for where its probe runs and how its result reaches the card.
  - New presentational pieces: the creator filter bar, the Add creator modal, the Add new proxy modal and the Creator egress table, all in `components/setup` beside the cards they wrap.
  - The suite (`.scratch/infloww-parity-round-2/suite.sh`), for the relay step.
  - The recheck records under `.scratch/infloww-parity-round-2/rechecks/`.
  - The proposed §3.7 rows, under `### Matrix row` in the recheck records. This Phase does not edit the Parity matrix.
  - The `?all_accounts=1` branch of `GET /health` in `service/server.py`, only for the clamp in Contracts (story 37a).
- **Order.** The `/health?all_accounts=1` clamp is this Phase's first ticket: a prefactor that needs no Layout capture, with its own relay test (`test_health_all_accounts.py`) and suite step, landable as soon as it is green, before Phase 0 finishes (coordinator ruling 4, 2026-10-17). The page tickets follow it and need the captures.
- **Interfaces.**
  - **The extension probe** becomes a small hook in `components/setup` that the Manage creators page calls once on mount. It keeps the fetch, URL, method and cache option `PasteCurlCard` uses today, and its result is `null` (checking), `true` or `false`. `PasteCurlCard` takes the result as a required `extInstalled` prop and no longer probes, so the probe has one fetch site. The page is the card's only host: `grep -rlF PasteCurlCard app --exclude-dir=node_modules` lists the page, the card, and two files that name it only in comments (`FanslyPasteSessionCard.tsx:4`, `useRemoteLoginJob.ts:11`).
  - **The creator table** takes its rows from the existing queries and does its filtering and paging on the client. Filter state stays in the component, not the URL.
  - **`ProxiesTable`** keeps its queries and mutations. Its form and paste box move into the Add new proxy modal. The egress table is a pure view over the `ProxiesResp` the table already holds: proxies' `assigned_account_ids`, `verified_ip` and `verified_at`, and `accounts` with `has_session`.
  - **Not wired controls** use the house marker: `disabled` plus `title="not wired"`.
  - **Extras** use `EXTRA_LABEL` from `app/lib/openinflowwwwExtras.ts` as the tooltip, and as the heading text where a whole section is ours.
- **Schema.** None. No table, migration or registry field changes. The proxy registry and the account registry keep their shapes.
- **Contracts.**
  - **Relay routes.** None are added. One is changed: `GET /health?all_accounts=1` keeps its shape and its coalesced fan-out, and after the fan-out returns it keeps only the rows whose `account_id` is in the caller's `account_ids`: an owner's, or a chatter's union, as `_resolve_account_id` checks them (`service/server.py:1382-1392`), and as `admin_proxies_list` already filters its `accounts`. Every row loses `proxy.url`, which no UI reads (`grep -rnF 'proxy.url' app/components app/hooks app/lib` and `grep -rnF 'proxy?.url'` over the same paths are empty) and which carries the proxy's username and password. A caller with neither principal gets 401, as `/admin/*` does. The single-account `/health` branch is unchanged. The pages read `GET /admin/accounts`, `GET /health?all_accounts=1`, `GET /admin/proxies` and `GET /admin/employees`. They write through `PATCH` and `DELETE /admin/accounts/{id}`, `POST /admin/accounts/active`, `POST /admin/session/refresh`, `POST /admin/reload-session`, `POST /admin/automation/enqueue` (the opt-in onboarding), the session bootstrap, direct-login and Fansly routes, `POST /admin/proxies`, `POST /admin/proxies/bulk`, `DELETE /admin/proxies/{label}`, `POST /admin/proxies/assign`, `POST /admin/proxies/{label}/unbind` and `POST /admin/proxies/{label}/test`, all exactly as today. On `/creators`, `GET /admin/proxies` is read under one query key, not today's two (`["proxies", "list"]` in `PasteCurlCard`, `["proxies"]` in `ProxiesTable`).
  - **The probe's console message.** Its exact text, the key of the Route walk's `CONSOLE_ALLOW`, is a contract with the walk and must not change.
  - **Routes.** `/creators` and `/creators/proxy` keep their paths and their nav labels ("Manage creators", "Custom proxy"). `/setup` keeps redirecting to `/creators`. `docs/routes.md` needs no edit.
- **Layout source.** Labels, order, columns, filters, buttons, empty states, spacing and colours come from the two Layout captures. The Clone pages (`creators-manage.html`, `creators-proxy.html`) are secondary, and the Inventory §3.7 decides which controls exist. A capture value the page does not follow is a difference, and the recheck record must account for it.
- **Colours.** Colours come from the app's existing tokens, as on the other round-2 pages. A colour difference from the capture is recorded in the recheck record against ADR-0001's and ADR-0010's rule (Infloww's Geometry, our colours), not hidden.
- **Connectivity mapping.**
  - a flagged dead session (`session_dead_at`) → "Disconnected", with its repair badge beside it. It outranks every branch below, as it does today (`AccountsTable.tsx`, "A flagged session OUTRANKS the live probe").
  - live → "Connected"
  - probing or still probing → "Pending connection"
  - down or error → "Disconnected"
  - no session → "Not connected"
  - the health read itself failed or was refused → the cell shows "—" with the error as its title, and the connectivity filter is disabled with "not wired". It never reads "Pending connection" forever.
  - "2FA required" and "ID verification" are login-job states, not stored Creator states: they stay filter options that match no row
- **Mobile.** The table and "Add creator" render at every width. The capture forms stay desktop-only, as today, and the modal shows the page's existing desktop-only line on phones.
- **Chatter sessions.** These are handled as today. Where a read the page uses refuses the session (`GET /admin/employees` for a chatter, `GET /admin/proxies`), the control fed by it renders disabled with "not wired" instead of an error.

## Testing Decisions

The seams are the two pages rendered whole, with the Relay client mocked, and the Relay routes they call. Tests check what an owner sees and what is sent, never component internals.

- **Manage creators page** (vitest, `app/app/creators/page.test.tsx`, Relay client mocked as in `AccountsTable.test.tsx`). The cases:
  - The table renders before any capture form, and its column headers equal the capture's list. The expected list carries the capture's Item IDs in a comment, so the recheck record can match each header to its source.
  - The search, platform, connectivity, employee and (if the capture has it) proxy filters narrow the rows. A dead-session Creator whose probe is live shows "Disconnected" and matches the Disconnected filter. A failed health read leaves the cells "—" and the connectivity filter disabled. Tag and account status are disabled with `title="not wired"`. Reset clears.
  - The footer total and per-page paging work.
  - "Add creator" opens the modal, and its first section is the Paste cURL section. Direct login and Fansly follow, each titled with `EXTRA_LABEL`.
  - The probe's `fetch` is called once on page mount with the unchanged URL, and opening the modal does not call it again.
  - "Delete" posts the delete. "Deactivate" is disabled with "not wired". Rename, Mark default and Refresh session carry `EXTRA_LABEL`.
  - The key cards sit inside the collapsed `EXTRAS_OVERFLOW_LABEL` disclosure, below the footer. The drift banner shows below the footer only while a model is stale. The Master-only cards are absent for a non-Master.
  - A chatter session, with `GET /admin/employees` and `GET /admin/proxies` answering 403, renders the table, with the employee filter and the proxy cells disabled with "not wired", and no error banner.
  - Each recovery action the capture holds opens the modal at its section, or is disabled with "not wired".
- **Custom proxy page** (vitest, `app/app/creators/proxy/page.test.tsx`). The cases:
  - The headers equal the capture's list, and the "No data" state shows on an empty registry.
  - Paging shows 10 per page.
  - "+ Add new proxy" opens the modal, whose label field defaults to `host:port`, which saves through `POST /admin/proxies` and refuses a duplicate label.
  - The paste box inside the modal posts to `/admin/proxies/bulk` and shows "Added N" and the line errors.
  - The egress table lists one row per Creator, showing the bound proxy's `verified_ip` or "No custom proxy", and its Test posts `/admin/proxies/{label}/test`.
  - Every extra carries `EXTRA_LABEL`.
- **Existing component tests stay green.** `AccountsTable.test.tsx` (cache eviction, the paused badge, Refresh session), `ProxiesTable.test.tsx` (paste) and `DirectLoginCard.test.tsx` are edited only where the moved markup changes a query. Their assertions on behaviour stay.
- **Relay** (`./venv/bin/python service/tests/test_*.py`, mocked, no live OnlyFans, registry on a `mkdtemp` copy):
  - `test_creators_tenancy.py` and `test_proxy_paste.py` run unchanged.
  - `test_role_enforcement.py` (page map) and `test_direct_login.py` run unchanged.
  - A new read or write gets a negative two-Agency case in `test_creators_tenancy.py`.
  - The `/health?all_accounts=1` clamp gets one there: Owner B's answer holds none of A's Creator ids or nicknames and no row has `proxy.url`, Owner A's answer holds A's Creator (the positive control), and a signed-out caller gets 401. `test_employee_list.py` runs unchanged. `test_health_all_accounts.py` keeps every assertion, but its two cases that go through the route as a signed-out caller (`server.health(None, True)` in the coalesced-retry case, and `client.get("/health?all_accounts=1")` in `case_the_endpoint_still_never_raises_500`) sign in an owner of their fleet first, with the `_agency_fixtures` login the tenancy tests use. Under the clamp, a signed-out caller would get 401 there.
- **Walk.** The Route walk (`/tmp/route-walk-src/walk.py`, never committed) walks both routes in four views. Its `report.json` shows the probe message on `/creators`'s `console_allowed` list, which proves the probe still runs on mount, and no other console error.
- **Prior art.** `app/components/setup/AccountsTable.test.tsx`, `ProxiesTable.test.tsx` and `DirectLoginCard.test.tsx` (Relay client mocking), `app/app/employees/shifts/page.test.tsx` (page-level render), `app/app/messages-pro/extras.test.tsx` (the `EXTRA_LABEL` audit), and `service/tests/test_creators_tenancy.py` (two-Agency negatives on a `mkdtemp` registry).

## Acceptance

```sh
set -e
cd "$(git rev-parse --show-toplevel)"
# inputs from Phase 0
test -s docs/infloww-layouts/creators-manage.md
test -s docs/infloww-layouts/creators-proxy.md
# effort suite (typecheck, lint, vitest; the relay step lists the Creators tests)
sh .scratch/infloww-parity-round-2/suite.sh
for t in creators_tenancy proxy_paste role_enforcement direct_login employee_list health_all_accounts; do
  grep -qF "$t" .scratch/infloww-parity-round-2/suite.sh
  ./venv/bin/python "service/tests/test_$t.py"
done
# the page seams exist and pass on their own
test -f app/app/creators/page.test.tsx
test -f app/app/creators/proxy/page.test.tsx
env ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run app/creators components/setup --testTimeout=20000
# the probe is unchanged and its walk allowance is kept
grep -rqF 'chrome-extension://${EXTENSION_ID}/icons/icon16.png' app/components/setup
grep -qF 'chrome-extension://anjjmiahkfondbhahocpkehjjabkommc/icons/icon16.png' /tmp/route-walk-src/walk.py
# extras are labelled with the house constant
grep -rqF 'EXTRA_LABEL' app/app/creators app/components/setup
# REA recheck records: every difference accounted for
for p in creators-manage creators-proxy; do
  f=.scratch/infloww-parity-round-2/rechecks/$p.md
  test -s "$f"
  grep -qF 'Inflowwww extra' "$f"
  R=$(sed -n '/^## Phase 4 /,/^## Phase /p' "$f")
  # the proposed row cites the page's Layout capture (Phase 6 alone edits the matrix)
  echo "$R" | sed -n '/^### Matrix row/,/^### /p' | grep -qF "docs/infloww-layouts/$p.md" || { echo "no proposed row in $f"; exit 1; }
  # `! cmd` never trips `set -e` (POSIX), so the negative check exits explicitly
  if grep -qi 'unlabelled' "$f"; then echo "unlabelled difference in $f"; exit 1; fi
done
# Route walk against the running dev server (manual: start `pnpm -C app dev` on 127.0.0.1:3001 first)
curl -sf -o /dev/null http://127.0.0.1:3001/creators
PORT=3001 ROUTE_WALK_OUT=/tmp/route-walk-p04 ./venv/bin/python -I /tmp/route-walk-src/walk.py
python3 -I -c '
import json
r = {x["route"]: x for x in json.load(open("/tmp/route-walk-p04/report.json"))["routes"]}
assert any("chrome-extension://" in e for e in r["/creators"]["console_allowed"]), "probe no longer runs on mount"
assert r["/creators/proxy"]["shots"], "proxy page not walked"
'
# manual: compare /tmp/route-walk-p04/creators-*.png and creators-proxy-*.png with the two Layout captures and the Clone shots; PNGs stay under /tmp
```

## Depends on

- **Phase 0.** It provides `docs/infloww-layouts/creators-manage.md` and `creators-proxy.md`, the Layout captures that are this Phase's input. It also provides the baseline record on the current tip (`.scratch/infloww-parity-round-2/baseline.md`) and the recheck record contract. The `/health` prefactor ticket (Order) does not depend on Phase 0.

## Out of Scope

- **A Creator deactivate, Creator tags, or an account-status field in the Relay.** The bundle shows them, but the Relay cannot do them. The plan makes such controls Not wired, not tickets.
- **The single-account `/health` branch.** It also answers outside the `/admin/*` isolation gate, but no page this Phase owns calls it, and unauthenticated callers may rely on bare `/health` (the start, reload and Caddy scripts probe it with no credentials). It is needs-human (N1).
- **A new Relay read for the egress table.** The existing `GET /admin/proxies` already carries every cell (YAGNI).
- **Moving the key cards to another route, such as Settings.** Setup → Keys is where the plan's other Phases point owners for keys, and the plan does not ask for a move.
- **Changing how sessions are captured, how direct login signs in, or how proxies are probed.** The plan says to move the existing cards, not rewrite them. The memory's refusal line on signing and TLS circumvention also stands.
- **Deleting or rewording the `CONSOLE_ALLOW` line, or moving the probe off mount.** The owner said to keep both.
- **Editing the Clone pages.** Phase 0 fixes the Clone where the bundle disagrees. A mismatch found here goes in the recheck record for the coordinator.
- **Committing walk PNGs, the bundle or any REA output beyond the Markdown records.** Floor 2 and ADR-0013 forbid it.
- **Live login, session capture or proxy tests against OnlyFans or a real proxy.** Mocked tests only, per the plan's product requirements.
- **The Add creator modal's image and gender fields as a stored Creator profile.** No Relay field holds them, so they are Not wired if the capture shows them.

## Further Notes

- The probe moves into a page-level hook, and the Add flow reads that hook's result.
  ASSUMPTION: "probe unchanged" (plan Phase 4, Work 1) means the same fetch of the same URL with the same console message on page load. It does not mean the same file. A probe inside a modal that has not opened would no longer run on load, which would orphan the walk's allowance that the owner chose to keep (rung 4: an optional prop, and other hosts of the card are unchanged). Overturned if the owner wants the probe to run only when the Add flow opens. The `CONSOLE_ALLOW` line would then be orphaned, and only the owner can drop it.
- The three connect paths are ordered Paste cURL, then Direct login, then Fansly, and each is labelled "Inflowwww extra" inside the capture's Add creator modal.
  ASSUMPTION: "the extension in front" (plan, owner decision) puts the extension path first in the Add flow, not on the page above the table, because the plan's Goal says the page "leads with the creator table" (rung 2 for the order, rung 5 for the rest). Overturned if the owner wants an extension status line in the page head as well.
- Each control in the bundle's own Add creator modal is mapped to an existing path where one performs it, or else rendered Not wired.
  ASSUMPTION: no capture step is dropped, because the plan's rule is "a bundle control with no relay behind it is Not wired" (rung 3, from the Growth Phase's wording and the house Not wired state). Overturned if the capture shows the modal is only a launcher for a desktop-app login that has no counterpart here. The modal then holds only our three sections, and the recheck record says so.
- The connectivity labels are mapped from our health states as listed under Implementation Decisions.
  ASSUMPTION: the mapping is ours, because the bundle's status codes come from Infloww's own backend (rung 5). Overturned by a capture that pins each label to a condition we can read.
- The Tag and Account status filters, and the "Deactivate" action, are Not wired.
  ASSUMPTION: rung 1 shows no Creator tag or deactivate field. `service/accounts.py` has no tag field, and `POST /admin/accounts/active` sets the default Creator, not a deactivated state. Overturned if a ticket finds such a field.
- The egress table's unbound Creators show "No custom proxy".
  ASSUMPTION: Infloww's "each creator gets a unique automatic proxy" (Inventory §3.7) has no Inflowwww counterpart, because an unbound Creator egresses from the Relay host (rung 5). Overturned if the owner wants the Relay's own egress IP shown, which would need a new read.
- Recheck records live at `.scratch/infloww-parity-round-2/rechecks/<page>.md`. Each holds three things: the REA tools run (with the bundle served on 127.0.0.1), a difference table (capture value, ours, and the disposition Not wired / "Inflowwww extra" at <where> / fixed), and a `### Matrix row` with the proposed cells, all inside this Phase's `## Phase 4 — <date> at <sha>` section (Phase 0's recheck record contract).
  ASSUMPTION: the effort directory is the place, because the Layout captures belong to Phase 0 and the plan names no recheck file (rung 5; the coordinator made it the round's one recheck location, 2026-10-17). Overturned if the owner wants the recheck appended to the capture.
- This Phase never edits the matrix. The proposed rows stay in the recheck records, and Phase 6 alone applies them.
  ASSUMPTION: one regrade, by Phase 6, from the recheck records (coordinator ruling 2, 2026-10-17, adopting six-hats 13; rung 4, since the matrix holds the owner's uncommitted Sign-off and Phase 6 regrades every row anyway). Overturned once the owner commits the matrix and wants each Phase to regrade its own rows.
- Where a Layout capture records a label only as an i18n key without its English text, the Inventory §3.7's label stands in, and the recheck record tags it.
  ASSUMPTION: the bundle's Creators components call the translator with keys such as `creators0239` and `creators0172`. Only some carry a `defaultValue` (rung 1: `index.9f50f370.js` offsets 12517099 and 7175982; rung 5 for the fallback). Overturned when Phase 0's capture resolves every key.
- `GET /health?all_accounts=1` is clamped to the caller's Creators and loses `proxy.url` in this Phase's first ticket, although the plan names no Relay change here.
  ASSUMPTION: the clamp lands first, as a prefactor, without a capture (coordinator ruling 4; rung 4, a leak of proxy credentials is the costlier thing to leave open, and the clamp changes no page). Overturned if the owner wants it shipped as a separate security change outside this round.
  ASSUMPTION: the plan's binding "backend tenancy and permission checks ship with the UI" (rung 2) covers a read the rebuilt table depends on, and the clamp copies `admin_proxies_list`'s filter (rung 3). The 401 for a signed-out caller follows `/admin/*` and `test_creators_tenancy.py`'s signed-out case (rung 3). Overturned if an unauthenticated monitor depends on `?all_accounts=1`, in which case the signed-out answer becomes an empty `accounts` list instead.
- A flagged dead session maps to "Disconnected", and a failed health read shows "—" with the connectivity filter Not wired.
  ASSUMPTION: today's table lets the flag outrank the probe (rung 3, `AccountsTable.tsx`). "—" is ours, because no capture label means "we could not ask" (rung 5). Overturned by a capture label for an unknown state.
- The key cards sit in a collapsed "Inflowwww extras" disclosure, and the drift banner stays visible below the footer while a model is stale.
  ASSUMPTION: the plan's product requirement puts non-automation extras in an Extras overflow (ADR-0003), and Phases 2 and 3 use one overflow per page (rung 3). The banner is an alert, so it stays outside, below every Infloww element (rung 4). Overturned if the reviewer wants the banner inside the disclosure too.
- The Add new proxy label defaults to `host:port`.
  ASSUMPTION: the bulk paste already labels rows this way (`ProxiesTable.test.tsx`, `label: "1.1.1.1:8000"`) (rung 3). Overturned if the capture records a label field.
- `PasteCurlCard`'s `extInstalled` prop is required and the card no longer probes.
  ASSUMPTION: rung 1 shows the page is the card's only host, so the optional prop and its fallback probe would be a second fetch site for no caller (rung 5). Overturned if a ticket adds a second host.
- Glossary terms this Phase uses that CONTEXT.md lacks: **Layout capture** (already pending in `.scratch/infloww-parity-round-2/glossary-pending.md`), **Route walk** and **Extension probe**. They are reported to the coordinator, not written here.

## Review

weaker (devils-advocate), 2026-10-17. codex was unusable: the preflight `codex login status` said "Logged in using ChatGPT", but both calls died with `ERROR: Your access token could not be refreshed because your refresh token was revoked` (exit 1, no output file). The fallback ran the devils-advocate persona (`.claude/agents/devils-advocate.md`) on the same two prompts, confined to the workspace. The run header forbids sub-agents, so the spec's author ran the persona itself. The blind pass therefore is blind by instruction, not by structure. Bundle offsets and `docs/infloww-layouts/*` were unavailable to both passes and are unverified. Repo files outside the workspace (`service/server.py`, `app/next.config.ts`) were read only to reconcile findings.

Blind call (alternatives, missing requirements, seam, falsifier):

- B1 **reject** — Alternatives (capture cards kept on the page above the table, or a separate `/creators/add` route instead of a modal). The plan's Phase 4 Work 1 already decides that Add creator opens the existing cards. The decision is the plan's, not this run's.
- B2 **accept** — Missing requirement: `GET /health?all_accounts=1`, the connectivity column's source, returns every account on the Relay to every caller. It carries nickname, OnlyFans name and id, and `proxy.url` with username and password (`service/server.py:1958-1959`, `1979-2017`; `service/proxies.py:116-123`). It sits outside the isolation gate, which only checks `/admin/` and `/api/of/` (`server.py:357-360`), it is exempt from the share-token gate (`server.py:527`), and it is rewritten to the public host (`app/next.config.ts:115`). The plan says "Backend tenancy and permission checks ship with the UI". Rewritten in story 37a, Owns, Contracts › Relay routes, Testing › Relay, and Further Notes.
- B3 **accept** — The Inventory's recovery actions ("Link account - need to reenter password", "Log in to account via OnlyFans/Login+", "+ Link Creator Account", `docs/infloww-screens.md` §3.7 modals) were unmapped. Rewritten in Solution › Row actions and story 18a, with a page test.
- B4 **partial** — The proxy filter ("Any proxy") appears only in the Clone's filter bar (`docs/infloww-screens.md` §3.7, marked [CL]), not in the help-center filter list. It is added only if the capture has one (story 8a).
- B5 **accept** — Seam: page-level vitest with the Relay client mocked is right, but story 38 (chatter) had no case. A chatter case was added to Testing.
- B6 **accept** — Falsifier: if the capture's Add creator is a multi-step flow (Creator name, Gender, "Next", platform, link; Inventory §3.7), our three sections either come first, displacing Infloww's first step against ADR-0003, or come after it. The spec left the order open. It now puts our sections first under the owner's binding "extension in front", records that as the owner's exception to ADR-0003, and puts the capture's own controls after them.

Draft call (where the spec is wrong):

- D1 **accept** — The Acceptance line `! grep -qi 'unlabelled' "$f"` can never fail. `sh -c 'set -e; ! true; echo still'` prints `still` (POSIX: `!` exempts the command from `-e`). Replaced with an explicit `if grep …; then exit 1; fi`.
- D2 **accept** — The connectivity mapping let a dead session sit beside its probe label, so a paused Creator could read "Connected", and the Disconnected filter would miss it. Today the flag outranks the probe (`app/components/setup/AccountsTable.tsx:218-232`). The mapping now sends a flagged dead session to "Disconnected" with its repair badge (story 4, Connectivity mapping, page test).
- D3 **accept** — The mapping had no branch for a failed or refused health read. `AccountsTable.tsx:202-204` renders "probing…" whenever `health` is absent, so under the new mapping every row would read "Pending connection" forever. The cell now shows "—" with the error as its title, and the connectivity filter is Not wired.
- D4 **partial** — The plan's product requirement and ADR-0003 put non-automation extras in an Extras overflow, and Phases 2 and 3 use one per page (`phase-02-growth-pages.md:65`, `phase-03-creator-reports.md:70`), but the spec kept the key cards as visible cards. The key cards now sit in one collapsed `EXTRAS_OVERFLOW_LABEL` disclosure. The drift banner is rejected from the overflow: it is an alert, so it stays visible below the footer while a model is stale (Further Notes ASSUMPTION).
- D5 **accept** — The optional `extInstalled` prop, with a fallback probe "so any other host is unchanged", is YAGNI. `grep -rlF PasteCurlCard app` shows the page is its only host. The prop is now required and the probe has one fetch site.
- D6 **accept** — Infloww's Add proxy modal has hostname/IPv4, port and "Add proxy", with no label (`docs/infloww-screens.md` §3.7). But the upsert and its duplicate guard key on label (`ProxiesTable.tsx:7-8`, `115-118`), so the spec could not be built as written. The label now defaults to `host:port`, the bulk paste's own labels (`ProxiesTable.test.tsx:37`), in an `EXTRA_LABEL` field.
- D7 **accept** — Story 37 overstated the evidence. `test_creators_tenancy.py` covers only `GET /admin/proxies`, the assign and the signed-out 401 (lines 9-14, 63-70, 113-121). `GET /admin/employees` is proven by `test_employee_list.py:7-9`, and nothing proves `/health?all_accounts=1`. Story 37 was rewritten, and `employee_list` and `health_all_accounts` joined the suite list (story 44, Acceptance). Both pass today (`./venv/bin/python service/tests/test_{health_all_accounts,employee_list}.py`: exit 0, "all cases passed"). Because of B2, two route-level cases in `test_health_all_accounts.py` (`:257`, `:296-302`) must sign in first, and Testing says so.
- D8 **accept** — The "exactly as today" write list left out `POST /admin/session/refresh` (`AccountsTable.tsx:184`), `POST /admin/reload-session` and `POST /admin/automation/enqueue` (`PasteCurlCard.tsx:95-110`). It also missed that `/creators` reads `GET /admin/proxies` under two query keys (`PasteCurlCard.tsx:81` vs `ProxiesTable.tsx:61`). The list is completed, and one key is required.
- D9 **partial** — The header-equality tests hard-code the implementer's reading of the capture, so they would pass while the page drifts from it. A machine check against the Markdown capture is too fragile to keep. Instead, the expected lists cite the capture's Item IDs, which Phase 0 gives every item (`phase-00-baseline-layout-capture.md:13`), so the recheck record can audit them.
- D10 **reject** — The in-place matrix regrade is skipped whenever the owner's matrix edits are uncommitted, and `git diff --quiet -- docs/infloww-parity-matrix.md` exits 1 right now. That is deliberate: the run header forbids touching the file, and Phase 6 applies the recheck record's `## Matrix row`.
- D11 **reject** — The probe-literal grep would pass if the page never called the hook. But the vitest "fetch once on page mount" case and the walk's `console_allowed` assertion both fail in that case, so the Phase cannot pass broken.
- D12 **reject** — Depends on misses `/tmp/route-walk-src/walk.py`, which comes from the previous plan's ticket 41. But Phase 0 owns rerunning the walk and recreating it if `/tmp` was cleared (`phase-00-baseline-layout-capture.md:79`), so the dependency on Phase 0 covers it.

needs-human:

- N1 — The single-account `GET /health` (no `all_accounts`) is reachable through the public rewrite (`app/next.config.ts:115`) and skipped by the share-token gate (`server.py:527`). For a caller with neither an owner nor a chatter principal, `_resolve_account_id` applies no ownership check (`server.py:1382-1392`). `_health_one` then returns the account's OnlyFans name and id, its proxy URL with credentials, and its egress IP (`server.py:2020-2050`). Position A: fix it with B2's clamp, by adding a 401 when neither principal is present. Position B: leave it out of Phase 4, because no page this Phase owns calls it, and fix it in its own ticket. What settles it is the owner's call on scope, plus one signed-out `curl -s 'http://127.0.0.1:3001/health'` on a dev tree that has a captured session. That run is not made here, because the session would be real. Added 2026-10-17 (coordinator ruling 4): kept needs-human and out of this Phase. Callers may rely on the unauthenticated answer: `scripts/start.sh:47,87` and `scripts/reload.sh:85` probe bare `/health` with `curl -fsS` (a 401 would fail them), `scripts/setup-caddy.sh:166` accepts 200 or 401, and `scripts/diag.sh:69` reads it; no hit in `desktop/` or the login extensions (grep, 2026-10-17), but a built desktop app or a deployed extension may still call it. Any fix must keep bare liveness answering and gate only the per-account body.

Six hats (2026-10-17, `.scratch/infloww-parity-round-2/review/six-hats.md`):
- SH6 **accept.** The `all_accounts` clamp is now the first ticket, a prefactor with no capture dependency (Owns, Order, Depends on, ASSUMPTION).
- SH9 **accept.** This spec's recheck location is now the round's only one; the record's heading becomes `### Matrix row` inside a `## Phase 4` section (Phase 0's contract).
- SH13 **accept.** No matrix edit and no Acceptance line on the matrix file; the proposed rows stay in the recheck records (story 43, Owns, Acceptance, Further Notes). D10's reject is superseded: the matrix write is dropped, not deferred.
- SH15(d) **partial.** The `all_accounts` branch lands first, as asked. The single-account branch is not folded in: unauthenticated callers may rely on it (N1, addendum), so it stays needs-human.
