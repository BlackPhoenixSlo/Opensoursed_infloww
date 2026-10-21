# Phase 05 — Remaining confirmed parity gaps, ranked

**Objective.** The eight evidence-backed gaps the plan ranks are closed in rank order on the Relay data that already exists (or that Phases 2 and 4 add), each one's Parity matrix row is re-graded, and every surface the plan parks stays unbuilt, with its reason and a concrete question for the human.

## Problem Statement

After the merge (Phase 0), shifts (Phase 2) and applied Settings (Phase 4), an agency owner still finds places where Inflowwww falls short of Infloww, even though the data to close them is already in the Relay:

- Manage employees is a bare table. It has no All / Activated / Deactivated views, no "By Creator" or "By role" filter, no groups, no batch actions and no shift history, although `Employee.is_active`, Creator access (`EmployeeAccountAccess`) and the Phase 2 Timesheet all exist.
- Employee reports does not show the "Clocked hours" that Phase 2 now records, and has no way to export them.
- There is no Sales records page, although every sale and its attribution sits in `transactions` and the `per_employee_revenue_with_attribution` view, and a manual reassign path exists. That path checks neither the sale's Agency nor the Employee's Agency (`service/server.py:10338-10380`).
- No Employee groups or Organization Chart exist, so Phase 4's "Self and subordinates" Data scope has nothing to read.
- The Notifications bell has no full page.
- The Dashboard and Fan reports show Inflowwww-only blocks that are not labelled as such, so a reviewer cannot tell an improvement from a mismatch.
- Nobody has written down whether Smart lists and Auto-follow match Infloww's rules and safety limits.

The owner also wants to know, without guessing, why Free trial links, Profile promotion, Leaderboard, Referrals, other platforms, Idle mode and Help center are still not there.

## Solution

Eight ranked items, each landing on its own and re-grading its row in `docs/infloww-parity-matrix.md`:

1. **Employees surface.** Manage employees gains a views rail (All employees / Activated / Deactivated), filters (By employee / By Creator / By status / By role, plus Reset), the columns Employee, Assigned Creators, Role, Status and Actions, a "More" menu with Deactivate (and Delete shown as Not wired), Batch actions (Batch edit roles, Assign, and Batch edit group once item 4 lands), and the shift history columns Total Earnings, Scheduled Shifts and Shifts Worked from Phase 2's Timesheet.
2. **Clocked hours.** Employee reports gains a "Clocked hours" section fed by Phase 2's Timesheet rollup (`group=employee`), with Infloww's platform notice and an "Export" that downloads CSV. Of Infloww's four views only "Total by employee" is built; the other three are shown Not wired.
3. **Sales records.** A new page at `/analytics/sales-records`, listed under Analytics, shows one row per sale with its attribution Rule and who assigned it, plus filters, CSV export and "Reassign". Reassign goes through the existing override route, which gains Agency checks and an audit row.
4. **Employee groups and Organization Chart.** An agency-scoped group tree with an Organization Chart tab at `/employees/org-chart`, an "Employee groups" rail and a Group column on Manage employees, "Batch edit group", and a subtree helper that Phase 4's "Self and subordinates" Data scope reads.
5. **Notifications page.** A `/notifications` page with Infloww's eight tabs, on the same Relay source as the bell. Tips stays Not wired until connectors ticket 31 settles its `type`.
6. **Dashboard reclassification.** The Dashboard's "Earnings by channel" block, the only clone-only card actually rendered, carries the "Inflowwww extra" label. Nothing is removed.
7. **Fan reports.** The Fan data panel is labelled as an Inflowwww extra. The plan's other two "ours" panels, cohorts and spend distribution, are not rendered anywhere (`grep -rliE "cohort|spend distribution|spendDistribution" app/app app/components` finds nothing), so the matrix records them as absent instead of labelling them. The retention table is not built, because the database does not hold per-Fan subscription history.
8. **Growth checks.** Smart lists' rules and Auto-follow's limits and stop control are confirmed against the code and written into the matrix. The non-Infloww Auto-follow actions are labelled.
9. **Creators tenancy check** (added by the six-hats review from the roadmap's Creators line, not the plan's ranked list). One matrix row and one negative Relay test, using Phase 1's two-Agency fixture, show that Creator linking and proxy data stay inside their Agency. Nothing is built. A failing case becomes a ticket and a `Question:` line, not a fix in this item.

## User Stories

Employees surface (item 1)

1. As an owner, I want "All employees", "Activated" and "Deactivated" views on Manage employees, so that I can see who is on the team now and who has left.
2. As an owner, I want a "More" menu on each Employee row with "Deactivate", so that I can remove someone's access without losing their history.
3. As an owner, I want to re-activate a deactivated Employee from the same menu, so that a mistaken deactivation is undone in one click.
4. As an owner, I want "Delete" in the More menu shown disabled with the tooltip "not wired", so that I am never told an Employee was erased when their audit history is in fact kept.
5. As an owner, I want an "Assigned Creators" column, so that I can see which Creators each Employee may work without opening each row.
6. As an owner, I want a "By Creator" filter, so that I can list everyone who can work one Creator.
7. As an owner, I want a "Role" column and a "By role" filter that read the role assignments from Role Settings, so that the role shown is the same one Role enforcement uses.
8. As an owner, I want "By employee" (name search), "By status" (Activated / Deactivated) and "Reset", so that I can narrow and clear the list as in Infloww.
9. As an owner, I want "Batch actions" with "Batch edit roles", so that I can give several selected Employees one role in a single save.
10. As an owner, I want "Batch actions" with "Assign", so that I can grant several selected Employees access to the same Creators at once.
11. As an owner, I want the shift history columns Total Earnings, Scheduled Shifts and Shifts Worked on each row, from the same Timesheet as the Shift schedule, so that I can judge attendance without leaving the page.
12. As an owner, I want Total Earnings explained as Recorded earnings and not pay, so that nobody reads it as payroll.
13. As a chatter, I want Manage employees to keep refusing me at the Relay, not only in the menu, so that team data stays with the owner.

Clocked hours (item 2)

14. As an owner, I want a "Clocked hours" section in Employee reports, showing per Employee the scheduled shifts, shifts worked, clocked hours and Recorded earnings for the chosen date range, so that I can review time worked next to sales.
15. As an owner, I want Infloww's view picker with "Total by employee" working and "Total creators by day (daily) by employee", "Total by creator by employee" and "By creator by day by employee" shown Not wired, so that no view shows numbers the rollup cannot produce.
16. As an owner, I want the notice "Clocked hours are not differentiated by platform.", so that I know OnlyFans and Fansly hours are not split.
17. As an owner, I want "Export" to download the visible Clocked hours as CSV, so that I can take them into a spreadsheet.
18. As an owner, I want an honest empty state when time tracking is off or nothing was clocked, so that zero hours are not mistaken for a broken report.

Sales records (item 3)

19. As an owner, I want a "Sales records" page under Analytics listing every sale with Date & time, Employee, Creator, Fan, Earnings, Gross revenue, Net revenue, Type, Rule, Assigned by and Status, so that I can audit how each sale was credited.
20. As an owner, I want to filter by Creator, Employees (and groups once item 4 lands), Sales types and Date (day / week / month / custom), so that I can find one sale quickly.
21. As an owner, I want "Show unassigned sales", so that I can find sales that no Employee has been credited with.
22. As an owner, I want "Reassign" on a row to pick another Employee of my Agency, or clear the assignment, so that I can correct attribution.
23. As an owner, I want "Assigned by" to show "Auto" for rule-based attribution and the person who reassigned it for a manual one, so that I can see who changed what.
24. As an owner, I want every reassign recorded in the audit history with the old and new Employee, so that a consequential change can be traced.
25. As an owner, I want "Load 50 more" paging and "Export CSV" of the whole filtered set, so that long periods stay fast and still export completely.
26. As an owner, I want the "Creator tag" filter shown as Not wired, because Creators carry no tags, so that its absence is explicit.
27. As an owner of one Agency, I want a reassign naming another Agency's sale or Employee to fail, so that no Agency can move another's credit.
28. As a chatter, I want Reassign refused at the Relay, so that only the owner corrects attribution.
29. As a chatter under Role enforcement, I want Sales records narrowed to my Data scope (self, self and subordinates, or all), so that I see only what my role allows.
30. As a reviewer, I want the matrix to record Sales records' sidebar placement as "unverified" and to note the Clone's "Sales records" tab in Employee reports, so that the placement is not claimed as Infloww's.

Employee groups and Organization Chart (item 4)

31. As an owner, I want an Organization Chart tab next to Employees on Manage employees, at `/employees/org-chart`, showing my Agency as the root and its groups as a tree, so that I can see how the team is organised.
32. As an owner, I want ⋮ on the Agency or a group to offer "Add sub-group", opening "Add Group Settings" with a group name and "Submit", so that I can build the tree as in Infloww.
33. As an owner, I want ⋮ on a group to offer "Delete group" only when it has no sub-groups and no Employees, so that nobody is silently orphaned.
34. As an owner, I want an "Employee groups" rail on Manage employees that filters the list to one group, so that I can work one team at a time.
35. As an owner, I want a Group column and "Batch edit group" for the selected Employees, so that I can place several people at once.
36. As an owner, I want group names to be unique among siblings, so that the chart stays readable.
37. As an owner, I want a new group's parent to be a group of my own Agency (or the Agency root), so that the tree stays whole.
38. As an owner whose Employee has the "Self and subordinates" Data scope under Role enforcement, I want that Employee to see their own data and that of Employees in the groups below theirs, so that team leads can supervise their team.
39. As an owner of one Agency, I want another Agency's groups to be invisible and untouchable (404), so that the org chart stays private.

Notifications page (item 5)

40. As an Employee, I want a full Notifications page at `/notifications` with "Back", "Notifications", the section "OnlyFans notifications" and the tabs All / Subscriptions / Purchases / Tips / Comments / Mentions / Likes / Messages, so that I can read past notifications at full width.
41. As an Employee, I want the page to read the same Relay source and Creator scope as the bell, so that both show the same notifications.
42. As an Employee, I want the Tips tab shown as Not wired until its OnlyFans `type` value is settled, so that it never shows the wrong items.
43. As an Employee, I want "Mark all read" and the gear shown as Not wired, so that nothing pretends to change OnlyFans state.
44. As an Employee, I want the top bar bell's panel to link to the full page, so that I can reach it.

Dashboard and Fan reports (items 6–7)

45. As a reviewer, I want the Dashboard's "Earnings by channel" block titled with the "Inflowwww extra" tooltip, so that I can tell it is ours.
46. As a reviewer, I want the matrix to record that "Fans & subscriptions", "Daily earnings", "Creators overview" and the free-trial banner exist only in the Clone and are not rendered, so that nothing fake is rebuilt.
47. As a reviewer, I want Fan reports' Fan data panel labelled "Inflowwww extra", so that it is not taken for Infloww's report.
48. As an owner, I want the missing retention table recorded with its reason (no per-Fan subscription history) and a question, so that I know what data would unblock it.

Growth checks (item 8)

49. As a reviewer, I want the matrix to list Smart lists' rule fields against Infloww's two editor types ("Segment by total spend" with include-expired, and "New fans" by days subscribed), naming each missing rule, so that the gap is known.
50. As a reviewer, I want the matrix to confirm Auto-follow's per-run cap, the zero-cap and switch-off stop controls, dry-run by default and its test, so that the roadmap's "limits and a safe stop control" condition is met by evidence.
51. As a reviewer, I want Auto-follow's like and ping actions labelled "Inflowwww extra", because Infloww only follows expired fans, so that the improvement is visible.

Parked surfaces and the matrix

52. As the owner, I want each parked surface (Free trial links "Create link", Profile promotion "Start campaign", Leaderboard, Referrals, the Fansly / mym / Fanvue selector, Idle mode, the update prompt, Help center content) to keep its matrix row with its reason and one concrete question, so that I know what would unblock it.
53. As the owner, I want the matrix to record both Leaderboard placements in the evidence (top bar in v5.7.14, Analytics in the help center) as unverified, without choosing one, so that the source disagreement is not hidden.
54. As a reviewer, I want each item to update its Parity matrix row and `docs/routes.md` when it lands, so that Phase 6 starts from current grades.
55. As an Agency, I want every endpoint this Phase adds to answer 401 to unauthenticated callers and 403/404 across Agencies, so that Agency isolation holds.

Creators tenancy check (item 9)

56. As an Agency owner, I want another Agency's owner to see none of my proxies or Creator nicknames in `GET /admin/proxies`, and to be refused when assigning a proxy to my Creator through `POST /admin/proxies/assign`, so that the roadmap's "account linking and sensitive proxy data respect tenancy" is shown by a test, not assumed.
57. As a reviewer, I want a matrix row "Creators: linking and proxy tenancy" that cites that test and records the result, so that the roadmap's Creators check is visible in the sign-off.

## Implementation Decisions

- **Owns.**
  - Relay: `employees` (its list response), a new router `employee_groups_api`, `stats` (the Sales records read), the existing manual attribute route in `server`, `db.models` (`EmployeeGroup`, `Employee.group_id`) and its additive catch-up, Phase 4's `permissions` (the `subordinates` resolution only) and two Alembic migrations.
  - App: `ManageEmployees` and `EmployeesTab`, a new `OrgChart`, `StatsReport`'s employee view (a new `ClockedHoursCard`), a new `SalesRecords` page, a new `NotificationsPage`, `NotificationBell` (shared source exported, "See all" link), `CompetitorReports` (one label), `UserDataTab` (one label), `AutoFollowTab` (labels) and `nav` (the Sales records entry).
  - Docs: `docs/infloww-parity-matrix.md` (rows only) and `docs/routes.md` (rows only).
- **Interfaces.**
  - `GET /admin/employees` gains `account_ids` (the Employee's Creator access, `null` for "all Creators") on each row in item 1, and `group_id` in item 4, when the column exists. Both are additive; existing callers ignore the new fields.
  - `employee_groups_api`, all owner session or Master, built on Phase 1's Agency context:
    - `GET /admin/employee-groups` returns `{groups:[{id,name,parent_id,employee_count}]}`.
    - `POST /admin/employee-groups {name, parent_id|null}`.
    - `DELETE /admin/employee-groups/{id}` answers 409 when the group has sub-groups or Employees.
    - `PUT /admin/employee-groups/members {group_id|null, employee_ids[]}` (Batch edit group).
    - A Python helper `subtree_employee_ids(agency_user_id, employee_id) -> set[int]` for Phase 4's Data scope.
  - `GET /admin/stats/sales-records`:
    - Query: `from`, `to`, `account_id*`, `employee_id*`, `group_id`, `kind*`, `unassigned_only`, `before_id`, `limit` (default 50) and `format=csv`.
    - Returns `{rows:[{tx_id, occurred_at, employee_id|null, employee_name, account_id, fan_id|null, fan_label, earnings_cents, gross_cents, net_cents|null, kind, rule, assigned_by, status}], next_before_id}`.
    - With `format=csv` it streams `text/csv` with the 50k-row cap and an `X-Row-Count` header (house precedent: `/admin/paid-messages`, `service/messages.py:835`).
  - `POST /admin/ingest/transactions/{tx_id}/attribute` keeps its body `{employee_id|null}` and response. It now:
    - requires an owner session or the Master (otherwise 403);
    - checks the sale's Creator with `assert_account_owned`, answering 404 for another Agency's sale;
    - rejects an Employee outside that Creator's Agency with 400;
    - writes one `actions` row: `action="sales.reassign"`, `target_type="transaction"`, `target_id=<tx_id>`, and a payload holding the old and new `employee_id`. The audit middleware's generic row for the POST (`service/employees.py:789-831`, mounted at `service/server.py:64`) is still written, as for every POST; the route is not added to `_AUDIT_SKIP_PREFIXES`. "Assigned by" reads only `sales.reassign` rows, so the generic row never counts twice.
  - No new Relay endpoint is added for Clocked hours or Notifications. Clocked hours reads Phase 2's Timesheet rollup, and Notifications reads `GET /api/of/v2/users/notifications`.
- **Schema.**
  - Migration A, item 4: a new table plus one column. Its `downgrade()` drops both.
    ```
    employee_groups(id PK, agency_user_id TEXT NOT NULL, parent_id INT NULL → employee_groups.id,
                    name TEXT NOT NULL (1–64 chars), created_at)
      UNIQUE(agency_user_id, parent_id, name); INDEX(agency_user_id)
    employees.group_id INT NULL   -- application-level FK, like chatter_id; NULL = no group
    ```
  - Migration B, item 3: a revision of `per_employee_revenue_with_attribution` that adds two columns to every UNION branch, `tx_id` and `rule`. `rule` takes `manual` (the override is set), `message` (credited by the message's sender), `tip_lookback` (a standalone tip matched by the 7-day lookback) or `unassigned` (the employee is NULL). The existing columns are untouched. `downgrade()` restores the definition from `20260710_0200_attr_view_orphan_rows`. Stored rows are never rewritten.
  - Each migration's `down_revision` is whatever single head exists when it is written, after the migrations of Phases 2–4. File slugs: `<stamp>_attr_view_sales_records.py` (Migration B, item 3) and `<stamp>_employee_groups.py` (Migration A, item 4).
  - Deploys run `init_db()` (create_all plus the additive catch-up), not `alembic upgrade` (Phase 2 spec, Schema). So `EmployeeGroup` and `Employee.group_id` are declared on the ORM models with the migration's index, and `employees.group_id` is added to the additive catch-up. The view revision exists only as a migration, like its predecessors.
- **Contracts.**
  - The Notifications page and the bell share one exported tab list (the bell's `FILTERS`) and one path builder. The Tips entry is flagged `notWired` on the page only. The bell's own behaviour does not change (Messages Pro is signed off).
  - The roles blob `assignments` is written by "Batch edit roles" through the existing `PUT /admin/settings/roles`, as a whole-blob replace that keeps every other key (ADR-0007). Phase 4's server-side validation applies to it.
  - "Assign" writes through the existing `PUT /admin/employees/{id}/access`, once per selected Employee.
  - Each Phase 5 route sits on Phase 1's Agency context. Unauthenticated callers get 401, and a cross-Agency id gets 404.
- **Placement.**
  - Sales records is a new child of the Analytics group in `nav`, so Phase 4's Permission editor lists it automatically (it reads `SIDEBAR`).
  - Organization Chart is a tab on Manage employees and not a sidebar entry. It sits beside Employees and, as an Inflowwww extra, Chatters. Its permission is Manage employees'.
  - `/notifications` has no sidebar entry and is reached from the top bar bell.
- **Data scope.**
  - With Role enforcement on, Sales records and Clocked hours narrow their rows by the Data scope that Phase 4's permission check resolves for a chatter: `self` is the Mirror Employee, `subordinates` is `subtree_employee_ids` and `all` is the whole Agency.
  - Phase 4 resolves `subordinates` as `self` until groups exist (Phase 4 spec, Data scope). Item 4 switches that resolution to `subtree_employee_ids` in Phase 4's `permissions` module, which this Phase therefore also owns for that one line. The Timesheet stays owner and Master only (Phase 2), so it has no Data scope to extend (six-hats review).
  - With Role enforcement off, they keep the current Employee reports scope.
  - Owner sessions and the Master always see the whole Agency (Phase 4 / ADR-0012).
- **CSV.** Clocked hours exports on the client from the already-fetched rollup, because the rollup is one row per Employee. The house precedent is the client-side CSV in `CompetitorReports`. Sales records exports on the server, because its rows are paged. No xlsx.
- **Labels.** Every Inflowwww-only block this Phase labels uses `EXTRA_LABEL` from `app/lib/openinflowwwwExtras.ts` as its title tooltip (ADR-0003).
- **Rank order.** Items land in the order 1→8, then item 9. A ticket for item *n* may start before item *n−1* closes only where the two touch no shared module. Items 1 and 4 share `ManageEmployees`, and item 4's Batch edit group and group filter extend item 1's toolbar. The ticketing step may cut this spec into sub-phases 5.1–5.8 along the item numbers.

ASSUMPTION: Delete in the More menu is Not wired and the existing soft-disable stays the only removal. Rung 4: a hard delete loses audit history. Overturned if the owner wants a hard delete, which needs its own retention decision.

ASSUMPTION: Batch actions are built even though the plan's item 1 does not list them, because the plan's Baseline row names "no … batch actions" as part of the gap and they are confirmed C[H262104]. Rung 5: they reuse existing writes and add no endpoint. Overturned if the owner cuts them.

ASSUMPTION: item 9, the Creators tenancy check, is folded into this Phase as one matrix row and one negative Relay test, although the plan's ranked list leaves it out. The roadmap asks to "verify that account linking and sensitive proxy data respect tenancy" (`nestStepsInflowCopy.txt:233-234`), the six-hats review found no Phase covering it, and the check is cheap: `/admin/proxies` already filters by `user_id` (`service/server.py:8826-8850`), and Phase 1's fixture supplies both Agencies. Rung 5. It lands last, after item 8, and touches no other item's module. Overturned if the owner wants the Creators surface specced whole in a later plan, in which case the test stays as that plan's first case.

ASSUMPTION: the shift history columns cover the current calendar month in the Agency's timezone (Phase 4 preferences). Rung 6: Infloww's range is not in the Inventory. Overturned by evidence of Infloww's range.

ASSUMPTION: Clocked hours builds only "Total by employee" of Infloww's four views (H262078). Phase 2's Timesheet groups by `employee` or by `account`, never by the pair or by day (Phase 2 spec, `GET /admin/shifts/timesheet?group=employee|account`), so the other three are Not wired. The card shows the rollup's minutes as hours and does no other arithmetic; range, timezone and open-clock handling are the rollup's. Rung 5. Overturned when the Timesheet gains a pair or by-day grouping.

ASSUMPTION: the full platform notice is unknown (the Inventory quotes "Clocked hours are not differentiated by platform…"), so the shown text is that prefix ending in a full stop. Rung 5. Overturned by the full Infloww text.

ASSUMPTION: Reassign is owner or Master only, even under Role enforcement. Rung 4: reassigning credit is a consequential write and the Permission editor has no per-action grant. Overturned by the owner granting it to a role.

ASSUMPTION: "Assigned by" is read from the latest `sales.reassign` audit row for the sale: the actor Employee's name, or "Owner" for an owner session. It shows "Auto" when the rule is not `manual`. A manual override that predates this Phase and has no audit row shows "Manual". Rung 1: `actions` holds `employee_id`, `target_id` and `payload_json` (`service/db/models.py:226-236`). Overturned if the owner wants a dedicated column.

ASSUMPTION: Sales records gets its rows from a view revision that adds `tx_id` and `rule`, not from a second copy of the attribution logic. Rung 3: the view has been revised by migration several times (`20260522_1300`, `20260620_0200`, `20260710_0200`), and one definition of attribution is the reason it exists. Overturned if a reader selects the view positionally (`SELECT *`), which a grep at ticket time must rule out.

ASSUMPTION: "Self and subordinates" means the Employee plus every Employee in a strict descendant group of the Employee's own group. Peers in the same group are excluded, and an Employee with no group sees only themself. Rung 6: the Inventory gives no definition. Overturned by the owner's definition.

ASSUMPTION: Organization Chart offers Add sub-group (confirmed) and Delete for empty groups (Rung 4: the undo of an add). It offers no rename, no drag-move and no parent change, so no write can create a cycle and none is tested. Overturned by evidence of Infloww's other ⋮ items, which would add a move route with its cycle check.

ASSUMPTION: Organization Chart is a tab, not a left panel on Employees. The inventory records both readings of H262104 (`docs/infloww-screens.md:67`), so the matrix records the placement as "unverified". Rung 6. Overturned by a capture of Infloww's Manage employees.

ASSUMPTION: `/notifications` is a page reached from a "See all" link in the top bar bell's panel. The bell's click still opens the panel. Rung 4: it leaves the signed-off bell's behaviour unchanged. Overturned if the owner wants the bell to navigate straight to the page.

ASSUMPTION: the Notifications page reuses the bell's fetch (20 per type, 50 merged; `app/components/NotificationBell.tsx:83`, `:230`) and its error and empty states. A single-type tab adds "Load more" by advancing the `offset` the bell already sends (`:83`); "All" stays the merged 50. Rung 3: the bell's own request shape. Overturned if the feed ignores `offset`, in which case "Load more" is Not wired.

ASSUMPTION: the Notifications page's "Mark all read" and gear are Not wired, because the Relay has no mark-read endpoint (`service/server.py:5364-5430` holds only GETs). Rung 1. Overturned when a known body exists.

## Testing Decisions

Behaviour is tested at the highest seams that exist: the Relay over HTTP with the temp-DB harness, and each page component in vitest with the Relay mocked. Nothing touches live OnlyFans or a real database.

- **Relay, `service/tests/test_employee_groups.py`.** Uses `_harness` and Phase 1's two-Agency fixture. It covers:
  - group create, list, unique sibling names, the parent check (a parent from another Agency or a missing id is 404), and the 409 on deleting a non-empty group;
  - the `init_db()` catch-up adding `employees.group_id` and `employee_groups` to a harness DB that lacks them;
  - Batch edit group;
  - `GET /admin/employees` carrying `group_id` and `account_ids`;
  - `subtree_employee_ids` on a three-level tree;
  - the cross-Agency 404s on every route, the chatter 403s and the unauthenticated 401s.
- **Relay, `service/tests/test_sales_records.py`.** Uses `_harness`, Phase 1's fixture and seeded `transactions`, `messages` and `employees`. It covers:
  - each `rule` value appearing on the right sale;
  - the filters, `unassigned_only`, paging by `before_id`, and the CSV header and `X-Row-Count`;
  - reassign and clear, each writing exactly one `sales.reassign` action, with "Assigned by" reflecting it and the middleware's generic row not counted;
  - reassign refused across Agencies (another Agency's sale is 404, another Agency's Employee is 400) and for a chatter (403);
  - Data scope narrowing with Role enforcement on and off.
- **Relay, `service/tests/test_creators_tenancy.py`** (item 9). Uses `_harness` and Phase 1's two-Agency fixture. Owner B's `GET /admin/proxies` holds none of Agency A's proxies (the `user_id` filter, `service/server.py:8826-8850`) and none of A's Creator nicknames in `accounts` or `assigned_accounts`. Owner B's `POST /admin/proxies/assign` naming A's Creator is refused (403 or 404) and writes nothing. The proxy registry file is pointed at a temp path, as `test_proxy_paste.py` does.
- **Migrations.** An upgrade → downgrade → upgrade round trip of both migrations against a throwaway SQLite file. The path is passed with `-x url=`; the default URL is never used. The downgrade target is the `down_revision` of item 3's view migration (the older of the two, rank order), read from its file, never `-N`. That makes the check hold whatever lands on top later, Phase 3's S4S migration included.
- **App, vitest:**
  - `ManageEmployees.test.tsx`: the views, the filters, the Role column read from the roles blob, Deactivate and re-activate, Delete Not wired, Batch edit roles sending one whole-blob PUT that keeps the other keys, Assign, and the shift history columns from a mocked Timesheet.
  - `OrgChart.test.tsx`: the tree, Add sub-group, and Delete enabled only on empty groups.
  - `ClockedHoursCard.test.tsx`: the request to `/admin/shifts/timesheet` with `group=employee` and the chosen range, the notice, the three Not wired views, the empty state, and Export producing the expected CSV text.
  - `SalesRecords.test.tsx`: the columns, the filters, Creator tag Not wired, Reassign, and Load 50 more.
  - `NotificationsPage.test.tsx`: the eight tabs, Tips / Mark all read / gear Not wired, and that the page and the bell issue the same request (path and Creator scope) for the same tab.
  - `NotificationBell` test: the panel's "See all" link points at `/notifications` and the bell's click still opens the panel.
  - `nav.test.ts`: Sales records under Analytics.
  - Label assertions for "Earnings by channel", Fan data and the Auto-follow extras, with the title `Inflowwww extra`.
- **Phase 2's rollup.** `test_shifts_api.py` runs in this Phase's Acceptance, because Clocked hours and the shift history columns read its Timesheet; the card tests mock it.
- **Item 8 and the parked rows** are documentation. Their check is the matrix rows themselves, plus the existing `test_smart_lists.py` and `test_auto_follow.py` staying green.

Prior art: `service/tests/test_settings_api.py` (the harness, owner/chatter seeding and the 401/403 ladder), `test_account_isolation_gate.py` and `test_chatter_access.py` (cross-Agency denials), `test_smart_lists.py`, `test_auto_follow.py`; `app/components/settings/RoleSettingsTab.test.tsx` (whole-blob PUT assertions), `app/components/chat/FanInsights.test.tsx` (Inflowwww extra titles), `app/lib/nav.test.ts`; the CSV precedents in `service/messages.py:835` and `app/components/home/CompetitorReports.tsx:992`.

## Acceptance

```sh
set -e
cd "$(git rev-parse --show-toplevel)"
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
./venv/bin/python service/tests/test_employee_groups.py
./venv/bin/python service/tests/test_sales_records.py
./venv/bin/python service/tests/test_shifts_api.py
./venv/bin/python service/tests/test_settings_api.py
./venv/bin/python service/tests/test_creators_tenancy.py
./venv/bin/python service/tests/test_account_isolation_gate.py
./venv/bin/python service/tests/test_chatter_access.py
./venv/bin/python service/tests/test_smart_lists.py
./venv/bin/python service/tests/test_auto_follow.py
# migrations reversible, on a throwaway file only (never the default URL)
rm -f /tmp/phase05-mig.db
A="./venv/bin/alembic -c service/db/migrations/alembic.ini -x url=sqlite:////tmp/phase05-mig.db"
PYTHONPATH=service $A upgrade head
BASE=$(sed -n "s/^down_revision[^=]*= *['\"]\([^'\"]*\)['\"].*/\1/p" service/db/migrations/versions/*_attr_view_sales_records.py)
test -n "$BASE"
PYTHONPATH=service $A downgrade "$BASE"
python3 -I -c 'import sqlite3; c=sqlite3.connect("/tmp/phase05-mig.db"); assert not c.execute("select 1 from sqlite_master where name=\"employee_groups\"").fetchone()'
PYTHONPATH=service $A upgrade head
rm -f /tmp/phase05-mig.db
# placement and docs
grep -q '"/analytics/sales-records"' app/lib/nav.ts
test -f app/app/analytics/sales-records/page.tsx
test -f app/app/employees/org-chart/page.tsx
test -f app/app/notifications/page.tsx
for s in sales-records org-chart /notifications Leaderboard Referrals "Free trial links" "Profile promotion" "Idle mode" "Help center" Fansly; do
  grep -q -- "$s" docs/infloww-parity-matrix.md
done
# item 8 decisions, not only keywords
for s in "include-expired" "days subscribed" "dry-run" "Inflowwww extra" "unverified"; do
  grep -q -- "$s" docs/infloww-parity-matrix.md
done
test "$(grep -c 'Question:' docs/infloww-parity-matrix.md)" -ge 8   # one per parked row
grep -q "sales-records" docs/routes.md
grep -q "org-chart" docs/routes.md
# manual: walk /employees, /employees/org-chart, /analytics/employee-reports, /analytics/sales-records and /notifications at 1440x900 and 390x844, light and dark, with scripts/ui-shots.sh; PNGs under /tmp only
```

## Depends on

- **Phase 0** brings the Merged tree, which provides `EXTRA_LABEL`, the Settings blobs, `RoleSettingsTab` / `PermissionEditor`, the of-manager-connectors parked tickets, and `docs/infloww-parity-matrix.md`, whose rows this Phase re-grades.
- **Phase 1** provides the Agency context helper and the two-Agency negative-test fixture that every new route and test uses.
- **Phase 2** provides the Timesheet rollup endpoint (the shift history columns in item 1, and item 2) and time-tracking's on/off state for item 2's empty state.
- **Phase 4** provides role resolution from `assignments` (item 1's Role column and filter), `require_permission` with its Data scope (items 3 and 4), Role enforcement, and server-side validation of the roles blob that Batch edit roles writes.
- Phase 3 is not needed.

## Out of Scope

From the plan, parked with a reason and one concrete question each:

- **Free trial links "Create link".** Connectors tickets 38 and 46 are parked on the unknown `expired_at` body, and the roadmap forbids inventing expiration fields. *Question: will you run the live capture of OnlyFans' trial-link create request on a test account so that its body is known?*
- **Profile promotion "Start campaign".** There is no known body (connectors RUN.md Assumption 1). *Question: same capture request, for the promotion create call.*
- **Leaderboard.** It is graded intentionally different, because global and country rankings need Infloww's customer base. The matrix records both placements as unverified. *Question: do you want an agency-internal leaderboard, labelled as an Inflowwww improvement?*
- **Referrals.** This is Infloww's own partner program, and Your Balance already shows the per-Creator OnlyFans referral cards. *Question: is anything from Infloww's Referral Program wanted inside one Deployment?*
- **The platform selector for Fansly / mym / Fanvue.** Only OnlyFans is inventoried (Inventory §6 item 13). *Question: can you supply captures of the other platforms' sidebars?*
- **Idle mode and the update prompt.** Idle mode was cut in messages-pro-parity, and the update prompt exists only in the desktop app. *Question: is an idle lock wanted in the web app at all?*
- **Help center content.** *Question: should the help link point at the public docs or stay a stub?*

The plan's own Out of scope: guessed OnlyFans bodies, live OnlyFans checks, a new analytics service, rebuilding Smart Messages, Scripts or Vault Pro (done), and removing any Inflowwww-only workflow.

Cut here (YAGNI):

- **xlsx export.** It would need a new dependency; CSV only, as the plan says.
- **The Fan reports retention table.** Not built because the data is not held: subscription rebills have `fan_id` NULL (`service/db/models.py:679`), and `fans` keeps only the current subscription (`subscribed_at`, `subscription_expires_at`, `subscription_status`, `:410-412`). *Question: should the ingest start storing per-Fan subscription periods so that retention can be computed?*
- **Fan reports' "New fans" and "Total fans" charts, Employee reports' Overview / Employee performance / Chatting statistics tabs, Message dashboard filters, Creators' unlabelled clone extras, and Sensitive Words / AI Copilot.** These are Baseline "partly" rows outside the plan's ranked list. The matrix carries each gap for a later plan.
- **New Smart list rules** ("New fans" by days subscribed, the include-expired option). Item 8 asks for a check and a list. Building them is a new ticket.
- **"+ Add employee" Email, Phone, Role and Group fields.** Employees have no email or phone column and no invite flow. Role and group are set after creation through Batch actions.
- **"Performance (all-time)"** (Inventory marks it [CL ?], unconfirmed), **the Creator tag filter** (no tag field on `accounts`), and group rename or drag-move.
- **Any change to the bell's own click behaviour, and the Tips `type` value.** Ticket 31 stays parked.

## Further Notes

Every open question is decided above and flagged ASSUMPTION at the decision. Three more:

ASSUMPTION: the Relay test files are named per router (`test_employee_groups.py`, `test_sales_records.py`) rather than one Phase file. Rung 3: `test_settings_api.py` and `test_smart_lists.py` are per router. Overturned if the ticketing step merges them.

ASSUMPTION: groups live in a new router file mounted on the existing Relay app rather than inside `service/employees.py`. Rung 3: per-feature routers such as `settings_api.py` and `smart_lists_api.py`. Overturned if a reviewer prefers the employees module.

ASSUMPTION: the Acceptance block downgrades to the `down_revision` of item 3's view migration, read from the file `*_attr_view_sales_records.py`, instead of `downgrade -2`. Phase 3 depends only on Phase 1 and may land after this Phase, so a relative step count could undo the wrong migration (six-hats review). Downgrading below Phase 5's base also undoes anything stacked on top, and the following `upgrade head` restores it. Rung 4. The file slugs `_attr_view_sales_records` and `_employee_groups` are this spec's names, rung 6. Overturned if the ticket names the migrations differently, in which case the glob follows the ticket.

## Review

codex (gpt, `model_reasoning_effort=high`, read-only sparse worktree), 2026-10-16. Raw: `.scratch/infloww-parity-next-steps/review/phase-05-blind.md`, `phase-05-draft.md`.

Blind call:

- B1 Phase 2 and Phase 4 are not in the checkout (`app/app/employees/shifts/page.tsx` is a stub, `service/settings_api.py:7` says inert) — **reject**: the workspace is the pre-Phase tree by construction; Depends on names both, and Phase 5 tickets cannot start before they land.
- B2 a dependency-first order instead of rank order — **reject**: rank order is a plan constraint (plan ASSUMPTION "items 1–8 are built in rank order"); Depends on already gates on Phases 2 and 4.
- B3 "By Creator" could mean access or shift assignment; "By role" before enforcement — **reject**: story 6 and Interfaces fix it as Creator access (`account_ids`), and the Role column reads `assignments` whether or not enforcement is on.
- B4 Clocked hours has no metric contract (range, timezone, open clocks, rounding) — **partial**: the card now does no arithmetic beyond minutes to hours and inherits all of these from Phase 2's rollup (Clocked hours ASSUMPTION).
- B5 Sales records as a tab in Employee reports instead of a route — **reject**: the plan fixes `/analytics/sales-records` and "unverified" placement (plan item 3); story 30 records the tab.
- B6 group cardinality and tree behaviour undefined — **reject**: Schema gives one parent per group and one group per Employee (`employees.group_id`), and Interfaces define delete rules.
- B7 reassign needs cross-Agency and audit tests — **reject**: already in Interfaces and `test_sales_records.py`.
- B8 Notifications needs paging, errors, empty states and a mark-read decision — **accept**: new ASSUMPTION on paging through the bell's existing `offset` (`NotificationBell.tsx:83`) and its error/empty states; Mark all read was already Not wired.
- B9 replace the Dashboard's joke report block — **reject**: plan item 6 says nothing is removed.
- B10 retention metric needs a definition — **reject**: the table is not built (Out of Scope, no per-Fan history).
- B11 Growth changes only where a gap is documented — **reject**: item 8 already builds nothing.
- B12 binding requirements (reversible migrations, indexes, audit) not carried into acceptance — **partial**: added the `init_db()` catch-up for the new table and column (deploys do not run alembic, Phase 2 spec Schema) and its test; audit of group writes comes from the existing middleware on every POST/PUT/DELETE (`service/employees.py:789`).
- B13 Organization Chart placement is disputed in the inventory (`docs/infloww-screens.md:67`) — **accept**: new ASSUMPTION; the matrix records it "unverified".
- B14 Relay as the primary seam — **reject**: Testing Decisions already put every permission and write at the Relay over HTTP.
- B15 the ranking has no comparative scores — **reject**: the rank is the plan's, not this spec's.

Draft call:

- D1 the audit middleware also writes a generic row for the attribute POST (`service/employees.py:789-831`, `service/server.py:64`), so "writes one `actions` row" is false — **accept**: Interfaces now say both rows exist, the route is not skipped (rung 4, no change to existing audit), and "Assigned by" reads only `sales.reassign`; the test asserts exactly one such row.
- D2 the cycle story has no operation that can cause a cycle — **accept**: story 37 replaced by a same-Agency parent check; the cycle test is dropped and the Org Chart ASSUMPTION says why.
- D3 item 7 labels only Fan data, but the plan names cohorts and spend distribution too (plan:273) — **partial**: those panels do not exist (grep finds none), so item 7 now records them as absent in the matrix instead of labelling nothing.
- D4 Clocked hours tests pass with Phase 2 broken — **accept**: `test_shifts_api.py` added to Acceptance and the card test asserts the Timesheet request. While checking, Phase 2's Timesheet groups only by `employee` or `account`, so "Total by creator by employee" was unbuildable; it is now Not wired with the other two views (story 15, ASSUMPTION).
- D5 no test that page and bell share source and scope — **accept**: the page test compares the two requests per tab, and a bell test covers "See all".
- D6 Acceptance greps keywords, not decisions — **accept**: added greps for the Smart lists rule names, dry-run, the extra label, "unverified", and at least eight `Question:` lines.
- D7 Batch actions and re-activation are scope the ranked item does not list — **reject**: the plan's Baseline names "no … batch actions" as the gap, and the run rule is that work the plan needs but did not list is specced and flagged (existing ASSUMPTION); re-activation is the existing PATCH the UI already sends (`app/components/settings/EmployeesTab.tsx:35`).
- D8 item 1 returns `group_id` before item 4 creates it — **accept**: `account_ids` lands with item 1, `group_id` with item 4.
- D9 no false dependency found — **accept** (no change).

### Six hats

Six-hats report, 2026-10-16 (`.scratch/infloww-parity-next-steps/review/six-hats.md`), reconciled as the Adversary brief does.

- Black (phase-05:159), Phase 5 edits Phase 4's permissions module: **reject**. Rung 2: plan Phase 5 item 4 says "'Self and subordinates' data scope in Phase 4's permissions reads it". Implementation Decisions already confine that ownership to one line. The sentence about Timesheet scoping is corrected, because the Timesheet now carries no Data scope (Phase 2 / Phase 4 reconcile).
- Black (phase-05:307), `downgrade -2` assumes no newer migration while Phase 3 can land in any order: **accept**. Acceptance now downgrades to the `down_revision` of item 3's view migration, read from its file. The ASSUMPTION is rewritten, and the migration file slugs are fixed in Implementation Decisions.
- Green (phase-05), drop the Batch actions (phase-05:168): **reject**. Rung 2: the plan's Baseline row for Employees reads "no groups, batch actions or deactivate view" (plan:69), and Phase 5's Goal is to close the gaps the Baseline marks. The existing ASSUMPTION flags it. It reuses existing writes and adds no endpoint.
- Green (phase-05), drop the view-revision migration (phase-05:145): **reject**. Plan item 3 needs a per-sale Reassign, which needs a transaction id on every attribution row. `service/attribution.py` exposes no per-transaction read (`grep -n '^def \|^async def ' service/attribution.py`). The view is the house's single definition of attribution and has been revised by migration three times before (rung 3). Its `downgrade()` restores the predecessor (rung 4).
- Green / White (Set gaps), add a small Creators/proxy tenancy check (one matrix row plus a negative test) to Phase 5: **accept**, rung 5. It becomes item 9, with stories 56–57, `test_creators_tenancy.py`, an Acceptance line and an ASSUMPTION. It is cheap because `GET /admin/proxies` already filters by `user_id` (`service/server.py:8826-8850`) and Phase 1's fixture supplies both Agencies. Churn/LTV is not folded in: it needs per-Fan subscription history this spec already finds missing. It goes to the plan review's Not yet specified.
