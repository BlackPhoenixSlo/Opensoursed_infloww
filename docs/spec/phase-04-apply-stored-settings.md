# Phase 04 — Apply the stored Settings

**Objective.** The `account`, `preferences`, `roles`, `sales`, `time-tracking` and `messaging` Settings blobs are validated by the Relay on write and Applied field by field by the screens and Relay routes they describe. Permission roles are enforced only under the per-Agency Role enforcement switch, and Security, Billing and Balance actions stay Not wired.

## Problem Statement

An Agency owner has filled in Settings that look like Infloww's: a report time zone, a week start, Permission roles with assignments, Sales attribution rules, an AI translation switch and a translator prompt. None of it does anything. Every Blob tab's Panel says "Saved for your organization; not applied yet." (ADR-0008). A chatter whose role should keep them out of Creators or Analytics can still call those Relay routes. Employee reports still credit sales by the Relay's one built-in rule, whatever Sales Settings says, and include welcome-message sales and the OnlyFans fee whatever the toggles say. The top bar shows the browser's time zone rather than the Agency's, and report day boundaries fall at UTC midnight. A chatter keeps "Use translation" even when the owner has switched AI translation off. The Relay also stores any JSON object it is given, so a malformed blob would reach these consumers unchecked once they start reading it.

## Solution

The Relay checks every Blob tab write against that tab's schema, stamps it with `version: 1`, and answers 400 with the offending field's path when a value is wrong. One Relay read, the Applied settings, tells any session (owner, chatter or Master) what applies to it: the Agency's time zones and week start, whether AI translation is allowed, and which pages its Permission role grants. The top bar, reports, the Shift schedule, the sidebar and the Composer read it. The Relay itself applies the same values on the routes it owns:

- Report day boundaries in the report time zone.
- Sales attribution rules and the two exclusion toggles in Employee reports and the Timesheet, in the read path only.
- The translation gate and the translator prompt on `/admin/translate`.
- Role enforcement on every Relay route behind a page the Permission editor lists.

Role enforcement is a switch on Role Settings, "Enforce role permissions", off by default. Owner sessions and the Master are never checked against a role. Each Panel's "not applied yet" note now names only the fields that are still not applied, and disappears where none are left. Values saved before this Phase are applied as stored, with no migration and no reset (ADR-0012).

## User Stories

Validation and versioning

1. As an Agency owner, I want a Settings save with a wrong value (an unknown time zone, a minutes value of 0, an attribution option that does not exist) refused with a message naming the field, so that a typo never reaches a screen or Relay route that acts on it.
2. As an Agency owner, I want a partial blob (one that is missing keys) accepted, so that saves keep working exactly as the Panels send them today (ADR-0007's whole-blob replace).
3. As an Agency owner, I want keys the schema does not know kept as they are, so that a save never fails or loses data because of a key an older or newer Panel wrote.
4. As an Agency owner, I want every stored blob to carry `version: 1`, so that a later schema change can tell old blobs from new ones.
5. As an Agency owner, I want a save without `version` stamped as version 1 and a save with any other version refused, so that an older app build keeps saving and a blob from an unknown future version is never misread.
6. As an Agency owner, I want a Permission role assignment that names a role which does not exist refused, so that no Employee is assigned to nothing. The built-in `owner` and `admin` ids always count as existing.
7. As an Agency owner, I want role ids and role names (compared case-insensitively) to be unique, so that an assignment always means one role.
8. As an Agency owner, I want a value saved before this Phase that would now fail validation treated as absent (its default applies) rather than as an error on every page, so that one bad old field cannot break the app. The next save of that Panel then shows the field's error.
9. As an Agency owner, I want the existing 401 → 404 → 413 → 400 check order kept, so that the Panel's error handling does not change.

Applied settings read

10. As any signed-in session, I want one Relay read that returns what applies to me (time zones, week start, whether AI translation is allowed, Role enforcement state and my granted pages), so that every screen agrees with the Relay.
11. As a chatter, I want that read to work for my session, unlike `/admin/settings/{tab}`, which still answers 401, so that my top bar, sidebar and Composer follow my Agency's Settings without exposing the Agency's other Settings to me.
12. As a chatter, I want that read never to include another Employee's role, the roles list or the translator prompt, so that I see only what applies to me.
13. As a chatter linked to more than one Agency, I want the read to follow the Agency of the Creator in my scope, and, with no single Creator in scope, to return no time-zone override, allow translation only if every linked Agency allows it, and grant a page if any linked Agency grants it, so that I am never shown a page or tool none of my Agencies allow.
14. As an Agency owner, I want the Applied settings to refresh as soon as I save any Blob tab, so that my change shows without a reload.
15. As a session from another Agency, I want the read to answer only for my own Agency, so that no Agency learns another's Settings (Agency isolation).
16. As a caller with no session, I want a 401, so that the read leaks nothing.

Preferences

17. As an Agency owner or Employee, I want the top bar's time-zone label (and the Messages Pro Window header's, which reuses it) to show the UTC offset of the Agency's regular time zone, so that it matches Infloww's "regular time zone ... on the Manager".
18. As an Agency owner or Employee, I want report date ranges (`from` and `to` on the Analytics reports) to start and end at midnight in the Agency's report time zone, so that "yesterday" means the Agency's yesterday.
19. As an Agency owner or Employee, I want "by day" report buckets cut at the report time zone's midnight, so that a late-evening sale lands on the right day.
20. As an Agency owner or Employee, I want the Shift schedule week, its "This week" filter and the Dashboard "My shifts" week to start on the Agency's week start day, so that the calendar reads the way the Agency plans.
21. Cut by the six-hats review (YAGNI): the reports' "This week" preset. See Out of Scope and the week-start ASSUMPTION.
22. As an Agency owner whose Agency never saved Preferences, I want the browser's own time zone and a Monday week start, so that nothing changes for me until I choose.
23. As an Agency owner, I want the Your Preferences Panel to show the note only for Language, which stays not applied, so that I can tell which choices take effect.

Role enforcement

24. As an Agency owner, I want a switch "Enforce role permissions" on Role Settings, off by default, so that roles I saved while they did nothing cannot lock my team out on upgrade day (ADR-0012).
25. As an Agency owner turning the switch on, I want to be told how many active Employees have no role and will be refused every page, and to confirm, so that I do not lock anyone out by accident.
26. As an Agency owner, I want switching enforcement off to restore everyone's access at once, so that I always have a rollback.
27. As an Agency owner, I want my own session, and the Master, never checked against a Permission role, so that the person who manages roles can never lock themselves out.
28. As a chatter in an Agency with enforcement on, I want any Relay call behind a page my role denies refused with 403 "Your role does not allow <page label>", so that denial happens at the server, not only through hidden buttons.
29. As a chatter in an Agency with enforcement off, I want every route to behave exactly as before this Phase, so that the switch is the only thing that changes access.
30. As a chatter with no role assigned in an Agency with enforcement on, I want to be refused every page-mapped route, so that enforcement has no unassigned hole.
31. As a chatter, I want a Relay route that serves no listed page (sign-in, `/chatter/me`, shared infrastructure) left alone by enforcement, so that I can still sign in and see why I am refused.
32. As a chatter, I want a route that serves two pages (for example the chats routes behind Messages Pro and Messages Basic) allowed when my role grants either page, so that granting one page never breaks it through a shared route.
33. As a chatter, I want the sidebar and the Permission-gated Settings tabs to hide pages my role denies, using the same granted-pages answer the Relay enforces, so that I am not shown links that will fail.
34. As a chatter who opens a denied page by URL, I want a plain "Your role does not allow this page" panel instead of a page full of failed loads, so that I know why.
35. As an Agency owner, I want a page added to the nav after a role was saved to be denied for that custom role until I grant it, so that an upgrade never widens a role silently.
36. As an Agency owner, I want an Employee whose role's Data scope is "Data about self" to see only their own row in Employee reports, so that Data scope means something at the server. (The Timesheet and "clocked-in now" stay owner and Master only, Phase 2, so no scoped session reaches them.)
37. As an Agency owner, I want "Self and subordinates" treated as "Data about self" until employee groups exist (Phase 5), so that it never reaches more data than intended.
38. As an Agency owner, I want an enforcement denial to leave no side effect: no write, no OnlyFans call, so that a refused request is harmless.
39. As an Agency owner, I want every Role Settings save, including flipping the switch, recorded in the existing `actions` audit history, so that I can see who changed access and when.
40. As an Agency owner, I want the Role Settings note to say "Saved for your organization; not enforced until Enforce role permissions is on." while the switch is off and nothing while it is on, so that the Panel states what is true.

Sales attribution

41. As an Agency owner, I want Employee reports to credit each sale by the rule Sales Settings sets for its revenue kind (Messages; Posts and Tips; Subscriptions, Streams & Referrals), so that the figures follow my organization's sales settings.
42. As an Agency owner, I want "Converters" to credit a sale the way the Relay credits it today (the linked message's sender, else the 7-day lookback), so that the familiar figure has a name.
43. As an Agency owner, I want "Message sender" to credit only the sender of the message the sale is linked to, with no lookback, and to leave an unlinked sale Unattributed, so that the stricter rule is visibly stricter.
44. As an Agency owner, I want "Shift schedule" to credit a sale to the Employees with an open Clock event on that Creator at the moment of the sale, so that shift workers get credit for their shift.
45. As an Agency owner with "Multiple employees per shift" on, I want a sale made while several Employees were clocked in on the Creator split evenly between them, so that no one gets the whole sale and none of it is lost.
46. As an Agency owner whose time tracking is off, I want "Shift schedule" to fall back to "Converters", with the report saying "Shift schedule needs Time tracking on; credited by Converters.", so that turning these settings on never empties every Employee's figures.
47. As an Agency owner, I want "Opt in to chatters" off to leave subscription, stream and referral revenue Unattributed in Employee reports (as today), and on to credit it by Shift schedule, so that the opt-in does what it says.
48. As an Agency owner, I want a manual "attribute" override on a transaction to win over every rule, so that a correction I made by hand is never undone by a setting.
49. As an Agency owner, I want "Exclude welcome messages" on to leave out sales linked to welcome automation messages, so that Employees are not credited for the automatic welcome.
50. As an Agency owner, I want "Exclude the 20% OnlyFans fee" on to show each credited sale net of OnlyFans' fee, so that figures match what the Agency receives.
51. As an Agency owner, I want the same rules applied to the Timesheet's Recorded earnings, so that Employee reports and the Shift history agree.
52. As an Agency owner, I want the stored attribution rows (`messages.sent_by_employee_id`, `transactions.attributed_employee_id`) never rewritten by a setting, so that switching a rule back restores the old figures exactly.
53. As the Master viewing several Agencies, I want each Creator's sales credited by its own Agency's rules, so that one Agency's settings never change another's figures.
54. As an Agency owner, I want Employee reports to show Infloww's notice "The sales data is based on your organization's sales settings." with a "View sales settings" link, so that the rule in force is discoverable.
55. As an Agency owner, I want the Sales Settings note removed, because every field on it is now applied, with a line under the radios saying that Shift schedule credits sales only while Time tracking is on.

Messaging

56. As an Agency owner, I want the AI translation switch off to disable a chatter's "Use translation" switch in the Composer and the Chat header's 🌐 toggle, with the tooltip "Turned off by your organization", so that the policy is visible where it bites.
57. As an Agency owner, I want `/admin/translate` to answer 403 "Turned off by your organization" to a chatter session while AI translation is off, so that the policy is enforced at the server.
58. As an Agency owner, I want my own session's translation never refused, so that I can still read foreign-language chats while auditing them.
59. As an Agency owner whose Agency never saved Messaging settings, I want translation to stay available as it is today, so that upgrading does not silently take a working feature away. The Panel's default shows the switch on to match.
60. As an Agency owner who wrote an AI Translator prompt, I want chat translations for my Creators to follow it, so that the prompt does what the Panel says.
61. As an Agency owner, I want translations made with my prompt kept apart from plain translations in the cache, so that changing or clearing the prompt never serves stale prompt-made text.
62. As an Agency owner, I want prompt translation charged to my Agency's own LLM key under the existing daily soft cap, and plain translation used whenever the key is missing, the cap is reached or the model fails, so that translation never stops working and never spends someone else's money.
63. As an Agency owner, I want the Messaging settings note removed, because both fields are now applied.

Time tracking and account

64. As an Agency owner, I want the `time-tracking` blob validated like every other Blob tab, so that the policy Phase 2 applies cannot be saved malformed.
65. As an Agency owner, I want the Your Account note kept, because the Agency name still has no consumer, so that the Panel does not claim more than is true.

Things that stay as they are

66. As an Agency owner, I want 2FA, password change, sessions, picture upload, Billing, invoices, wallet top-up, withdrawal and Your Balance payouts to stay Not wired, so that nothing presents a fake success.
67. As a developer, I want ADR-0008 marked "superseded in part by ADR-0012" and the glossary's Permission role and Not applied yet entries updated, so that the docs match the code.

## Implementation Decisions

- **Owns.**
  - Relay: the Settings router (`settings_api`): per-tab schemas, versioning, the Applied settings read.
  - Relay: a new Permissions module (`permissions`): Role enforcement, the page-to-route map, `require_permission`, Data scope.
  - Relay: a new Sales attribution read module (`sales_attribution`), which credits sales under the Agency's rules.
  - Relay: the stats router (`stats`): the Employee report and report-time-zone day bounds.
  - Relay: the translate router (`translate_api`): the gate and the prompt tier.
  - Relay: Phase 2's shifts router, only for the Timesheet's Recorded earnings.
  - Relay: the server's middleware registration.
  - App: `settingsBlob`, a new `appliedSettings` hook, `nav`, the shell Sidebar, the top bar `TimeZoneLabel` and a denied-page panel in the shell.
  - App: the Settings Panels `PreferencesTab`, `RoleSettingsTab`, `SalesSettingsTab` and `MessagingSettingsTab`, plus `SettingsPanel`'s `NotAppliedYet`.
  - App: the Composer's `TranslatePopover`, the Chat header translate toggle and `useTranslations`.
  - App: the stats `DateRangePicker` and `StatsReport`.
  - App: Phase 2's Shift schedule and "My shifts" card, for week start only.
  - Docs: ADR-0008's status line, `CONTEXT.md` (Permission role, Not applied yet, Applied), `docs/settings-parity.md`'s rows for the applied fields.

- **Interfaces.**
  - Settings router: `PUT /admin/settings/{tab}` validates, then stamps `version`. `GET /admin/settings/{tab}` is unchanged, and still answers 401 to a chatter. New `GET /admin/settings/applied` is declared before `/{tab}` so that it is never read as a tab name. A pure `parse_blob(tab, raw) -> (blob, errors)` is the one place a schema lives, and every consumer reads a stored blob through `applied_blob(agency_user_id, tab)`, which drops invalid fields to their defaults.
  - Permissions: `require_permission(ctx, page_href)` raises 403 for a denied Employee. A middleware runs the check for chatter sessions on every route in the page map, so handlers are not decorated one by one. `granted_pages(ctx) -> set[str] | None` (None means every page) feeds both the Applied settings read and the middleware. `data_scope(ctx) -> "all" | "self"` is read by employee-keyed reports.
  - The plan wrote `require_permission(page, op)`. It takes no `op`, because a stored permission is one boolean per page (`PermissionRole.permissions: Record<href, boolean>`, the Permission editor's shape), so a granted page grants both reading and writing.
  - Sales attribution: `credited_sales(account_ids, start, end) -> rows(employee_id | None, account_id, kind, amount_cents)`. It applies each account's Agency's `sales` blob, and `per_employee` and the Timesheet are its only callers.
  - App: `useAppliedSettings()` returns the read below, and React Query invalidates it on every Blob tab save. `NavFilter` gains `grantedPages: Set<string> | null`, `chatterHidden` stays as it is (UI hygiene), and the role filter is added beside it. `NotAppliedYet` takes the names of the fields still not applied and renders nothing when given none.

- **Schema.** No table, column or migration. The Role enforcement switch is a key in the `roles` Settings blob (ADR-0007: Permission roles live in that blob). The blob shapes, every key optional and unknown keys kept:

  ```ts
  account:         { version: 1; agency_name: string /* ≤128 */ }
  preferences:     { version: 1; tz: IANAZone; report_tz: IANAZone; week_start: "monday"|"sunday"; language: "en"|"es" }
  roles:           { version: 1; enforce: boolean;
                     roles: { id: string; name: string /* ≤64, unique ci */; description: string /* ≤256 */;
                              permissions: Record<string, boolean>; scope: "all"|"subordinates"|"self" }[] /* ≤100, ids unique */;
                     assignments: Record<string /* Employee id */, string /* role id, or "owner"/"admin" */> }
  sales:           { version: 1; exclude_welcome: boolean; exclude_of_fee: boolean; multi_employee_shift: boolean;
                     attribution: { messages: "shift"|"sender"|"converters"; posts_tips: "shift"|"converters";
                                    subscriptions_chatter_opt_in: boolean } }
  "time-tracking": { version: 1; enabled: boolean; auto_clock_out_minutes: int /* 1..1440 */; clock_in_reminder: boolean }
  messaging:       { version: 1; ai_translation: boolean; prompt: string /* ≤2000 */ }
  ```

  IANA zones are checked against the Relay's `zoneinfo.available_timezones()`.

- **Contracts.**
  - `PUT /admin/settings/{tab}` 400 body: `{"detail": "<tab>.<dotted.path>: <reason>"}` for the first failing field, after the existing 401 → 404 → 413 checks.
  - `GET /admin/settings/applied` → `{ preferences: { tz: string|null, report_tz: string|null, week_start: "monday"|"sunday" }, messaging: { ai_translation: boolean }, permissions: { enforced: boolean, pages: string[]|null, scope: "all"|"self" } }`. `null` zones mean "use the browser's", and `pages: null` means every page. The Agency is taken from Phase 1's Agency context; a chatter names it through the Creator in scope (`X-Account-Id`, checked by `assert_account_owned`).
  - An enforcement denial is `403 {"detail": "Your role does not allow <page label>"}`.
  - A refused translation is `403 {"detail": "Turned off by your organization"}`.
  - The `/admin/translate` request body is unchanged. The prompt tier is chosen by the Relay from the session and `X-Account-Id`, never from the body.
  - Report `from`/`to` stay `YYYY-MM-DD` strings. Only their meaning changes: midnight in the report time zone, not UTC.

- **Role enforcement.**
  - The Agency is the one named by Phase 1's Agency context, and the Employee is that context's Mirror Employee, looked up in `assignments` by its id.
  - Owner sessions, the Master and requests with no chatter session are never checked.
  - With enforcement off, the middleware does nothing.
  - With enforcement on, a mapped route is allowed when any page it serves is granted by the Employee's role, and a missing page key means denied. An Employee with no assignment, or an assignment to a role id the blob does not hold, is refused every mapped route. Unmapped routes pass.
  - A chatter request that names no single Agency is checked against every linked Agency with enforcement on, and refused if any of them denies the page.
  - The check runs before the handler, so a denial never writes and never calls OnlyFans.

- **The page map.** One table in the Permissions module, from each nav page href that the Permission editor lists (`PAGE_HREFS`: the non-legacy `SIDEBAR` links) to the Relay path prefixes that page calls. A page that calls no route of its own maps to an empty list explicitly. The ticket builds it by reading each page's relay calls. Owner-only prefixes that already refuse chatters (`_CHATTER_BLOCKED_ADMIN_PREFIXES`) need no entry. Every other Relay route is classified: it falls under a page-map prefix, or it is listed in an explicit `UNMAPPED` table in the same module with a one-line reason (sign-in, `/chatter/me`, health, shared infrastructure). A route in neither place fails the Relay test suite, so a new route can never slip past enforcement by being forgotten.

- **Data scope.** Applied only under enforcement, and only to employee-keyed reads:
  - `GET /admin/stats/per-employee` returns only the caller's own Employee row when the scope is not "all".
  - Phase 2's Timesheet and "clocked-in now" are not scoped here. Phase 2 makes both owner and Master only (403 for a chatter), and owners and the Master bypass role checks, so no session that Data scope narrows can reach them. Opening them to chatters is a later additive change that would apply Data scope at the same time (six-hats review; Phase 2's `ClockedInCard` ASSUMPTION says the same).
  - "subordinates" reads as "self" until Phase 5's employee groups exist.

- **Sales attribution rules**, per transaction, in this order:
  1. A manual `attributed_employee_id` wins.
  2. Otherwise the kind's rule applies:
     - **Converters** is the existing `per_employee_revenue_with_attribution` view's answer.
     - **Message sender** is the view's answer only when the sale has a linked `message_id`, else Unattributed.
     - **Shift schedule** credits the Employees with an open Clock event on that Creator at `occurred_at`. With several of them, the sale is split evenly in whole cents, the remainder going to the lowest Employee id; with none, it is Unattributed.
  3. Shift schedule is replaced by Converters while the Agency's `time-tracking.enabled` is false.
  - Kinds map to rules as follows:
    - Messages: `ppv`, `ppv_message`, and `tip` with a `message_id`.
    - Posts and Tips: `ppv_post`, `tip_post`, and `tip` without a `message_id`.
    - Subscriptions, Streams & Referrals: `subscription`, `rebill`, `ppv_stream`, `tip_stream`, `referral`. With the opt-in off they stay Unattributed, as today; with it on they are credited by Shift schedule.
  - Every other kind keeps today's view answer.
  - `exclude_welcome` drops sales whose linked message's `automation_kind` is `send_welcome`, `welcome` or `welcome_chatter_for_info`.
  - `exclude_of_fee` uses `net_cents` where it is present, else `amount_cents × 0.8` rounded down.
  - Nothing is written.

- **Report time zone.** `stats._parse_date` turns a date-only bound into the UTC instant of that midnight in the caller's Agency's `report_tz`. A chatter with no single Agency, or an Agency with no `report_tz`, keeps today's UTC midnight. Day buckets use that zone's UTC offset at the window's end.

- **Translation.**
  - The gate reads the named Agency's `messaging.ai_translation`. A never-stored blob or key counts as `true`, and the Messaging Panel's default becomes `true` to match.
  - The Composer and Chat header switches are disabled while the gate is false, and `useTranslations` sends nothing while the effective mode (the local mode AND the gate) is off. The Employee's stored local mode (`useTranslateMode`'s localStorage value) is kept untouched while the gate is off, so it returns as it was when the owner switches AI translation back on.
  - With a non-empty prompt and a single Creator in scope, cache misses go through the existing `llm_client.chat` (purpose `translate`, the Creator's `account_id`, which also selects the Agency's own key and soft cap), with the prompt as the system instruction, and are cached under a key that includes the prompt's digest. Without a prompt, or on any LLM failure, gtx serves as today.
  - Owner sessions are never refused, but they get the prompt tier too.

- **Notes.** `NotAppliedYet` becomes field-scoped. What each Panel shows:

  | Panel | Note |
  |---|---|
  | Your Account | the whole Panel (Agency name) |
  | Your Preferences | "Language" |
  | Role Settings | the not-enforced sentence while the switch is off |
  | Sales Settings | no note |
  | Messaging settings | no note |
  | Time tracking | Phase 2 owns it |

## Testing Decisions

Two seams, both already in the repo.

- **The Relay over HTTP with real sessions.** This follows `test_settings_api.py`: `_harness`, a temp DB and a TestClient that logs in through `/auth/login` and the chatter login, with Phase 1's two-Agency fixture for the cross-Agency cases. Every Relay story is asserted as a status code and a response body.
  - Validation and versioning: each tab's bad-value 400 with its path, partial blobs, unknown keys kept, the version stamp, a future version refused, the check order unchanged. A blob written straight into `user_settings` with one invalid field (bypassing the PUT) is read by the Applied settings read and by a report with that field at its default, and the next PUT of that blob answers 400 naming the field.
  - The Applied settings read: owner, chatter, two-Agency chatter, cross-Agency, 401.
  - Role enforcement in both states for the same chatter and route: a denied GET, a denied PUT that writes nothing, a shared route, an unmapped route, an unassigned Employee, owner and Master bypass, switching off restores access.
  - Data scope on per-employee stats, with a "self" and a "subordinates" role. A chatter under enforcement with an "all" scope still gets 403 from Phase 2's Timesheet and "clocked-in now", which stay owner and Master only.
  - A Role Settings PUT that flips `enforce` leaves one `actions` row for that path.
  - Route classification: every route in `server.app.routes` falls under a page-map prefix, `_CHATTER_BLOCKED_ADMIN_PREFIXES` or `UNMAPPED`. Then, for every page in the map with a non-empty entry, one of its routes is called by a chatter whose role lacks only that page, and must answer 403.
  - The translate gate: a chatter refused, an owner allowed, a never-stored blob allowed. The prompt tier uses a patched `llm_client.chat`, house style: a prompt-made answer, the gtx fallback on `LLMCapExceeded`, and cache separation. gtx is patched so no network call is made.
  - Each attribution rule and toggle through `GET /admin/stats/per-employee`, on seeded messages, transactions and Clock events, including the time-tracking-off fallback, the even split, the manual override, the Master's mixed Agencies, and a before/after check that no attribution row changed.
  - Report day bounds in a non-UTC `report_tz`, and a "by day" report whose sale at 23:30 local time (the next UTC day) lands in the local day's bucket.

  A drift check in the same suite reads the nav's page hrefs out of `app/lib/nav.ts` and fails when a Permission-editor page has no entry in the page map.
- **App components under vitest.** This follows the existing Panel tests and `nav.test.ts`. It covers:
  - The field-scoped notes on each Panel.
  - The Role Settings switch and its confirm count.
  - The nav filter with granted pages, and the denied-page panel.
  - The Composer and Chat header switches disabled with the tooltip, and no translate request sent while disabled.
  - The top bar label from a stored zone.
  - The Shift schedule week, its "This week" filter and the Dashboard "My shifts" week, each starting on Sunday for a Sunday-start Agency.
  - The Applied settings refetched after a Blob tab save, with no reload.
  - The Sales report notice and its fallback line.

  Each test mocks `relay` the way the existing tests do.

Prior art: `service/tests/test_settings_api.py`, `test_chatter_access.py`, `test_account_isolation_gate.py`, `test_automation_attribution.py`; `app/components/settings/MessagingSettingsTab.test.tsx`, `RoleSettingsTab.test.tsx`, `SalesSettingsTab.test.tsx`, `PreferencesTab.test.tsx`, `app/lib/nav.test.ts`, `app/lib/settingsBlob.test.ts`.

## Acceptance

```sh
cd "$(git rev-parse --show-toplevel)"
./venv/bin/python service/tests/test_settings_api.py
./venv/bin/python service/tests/test_applied_settings.py
./venv/bin/python service/tests/test_sales_attribution_rules.py
./venv/bin/python service/tests/test_chatter_access.py
./venv/bin/python service/tests/test_account_isolation_gate.py
./venv/bin/python service/tests/test_automation_attribution.py
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
sh .scratch/settings-tabs/suite.sh
# Only Your Account, Your Preferences and Role Settings may still render the "not applied yet" note
test "$(grep -l 'NotAppliedYet' app/components/settings/*Tab.tsx | grep -v test | sort | tr '\n' ' ')" = "app/components/settings/PreferencesTab.tsx app/components/settings/RoleSettingsTab.tsx app/components/settings/YourAccountTab.tsx "
grep -q 'superseded in part by ADR-0012' docs/adr/0008-settings-stored-not-applied.md
# the glossary's Permission role and Not applied yet entries name ADR-0012
for t in 'Permission role' 'Not applied yet'; do awk -v t="**$t**:" 'index($0,t)==1{f=1} f&&/^$/{exit} f' CONTEXT.md | grep -q 'ADR-0012' || exit 1; done
# manual: python3 scripts/settings-check/walk.py at 1440x900 and 390x844, light and dark; the Role Settings switch and the Composer's disabled translate switch fit with no overflow (PNGs under /tmp only)
```

## Depends on

- **Phase 0**: the Merged tree, which carries the Settings tabs, `settings_api`, `useSettingsBlob`, ADR-0007 and ADR-0008.
- **Phase 1**: the Agency context (which Agency, which Mirror Employee, owner or Master, from the session alone, with a chatter's Agency named through a Creator it may access), and the two-Agency test fixture with an owner, a chatter and a Creator in each Agency.
- **Phase 2**:
  - Clock events, which the Shift schedule attribution rule reads.
  - The Timesheet and its Recorded earnings, to which the rules are applied.
  - The Shift schedule and "My shifts" week, which take the week start.
  - The Time tracking Panel's note and the `time-tracking` and `multi_employee_shift` consumers, which Phase 2 owns and this Phase only validates and reads (`time-tracking.enabled` for the Shift schedule fallback), never rebuilds.

## Out of Scope

- 2FA enrollment and reset, password change, session listing and revocation, picture upload, Billing and invoices, wallet top-up and withdrawal, and Your Balance payouts. All stay Not wired, because no auth or billing backend exists (plan; roadmap "keep these unavailable").
- Language Settings (English/Spanish UI translation). The plan cuts it, and there is no UI translation layer.
- Rewriting historical attribution rows. ADR-0012 limits attribution to the read path.
- Showing the Agency name. Infloww shows it on the Leaderboard, which Phase 5 parks, and as the Organization Chart's root, which Phase 5 item 4 owns. With no consumer in this Phase, its note stays and `account` is only validated.
- Per-operation permissions (view and edit apart). The stored role has one boolean per page, and inventing a second level is a schema the Permission editor cannot set.
- Employee groups and a real "Self and subordinates" scope. Phase 5 item 4 owns them.
- A Deployment-wide kill switch for Role enforcement. The per-Agency switch already rolls back, and owners always bypass it, so an owner can always reach it.
- A `roles` table or a role column on `employees`. ADR-0007's YAGNI still holds, and per-request blob reads are enough at 2 to 5 Agencies.
- A "This week" preset in the reports' date range picker. It was invented with no Inventory evidence, and the six-hats review cut it (YAGNI). The week start applies to the Shift schedule and "My shifts" only.
- Applying the regular time zone to message timestamps or other times. The inventory names only the top bar label (§1.2, H262077).
- Auditing enforcement denials as `actions` rows. The existing audit middleware records 2xx mutations, and a refused request changes nothing.

## Further Notes

ASSUMPTION: unknown keys inside a blob are kept, not refused. Rung 4: a strict schema would make every later save of a blob that holds a stray key fail with 400, a lock-out of the Panel, whereas keeping the key loses nothing. Overturned if the owner wants strict blobs, which needs a one-off clean of stored blobs first.

ASSUMPTION: a save without `version` is stamped 1, and any other version is refused. Rung 4: older app builds keep saving during a rolling upgrade. Overturned if the owner wants the client to own the version.

ASSUMPTION: the new length and range bounds are agency_name 128, role name 64, description 256, 100 roles, prompt 2000 characters and auto clock-out 1 to 1440 minutes. Rung 6 within the existing 64 KB body cap, since the Panels set only the minutes' lower bound. Overturned by Infloww evidence of other limits.

ASSUMPTION: a stored field that fails validation is applied as its default and shown unchanged in its Panel until the next save. Rung 4: no read path can break on old data. Overturned if the owner wants invalid stored blobs reported on load.

ASSUMPTION: the Role enforcement switch is a key (`enforce`) in the `roles` blob rather than a column or table. Rung 3 (ADR-0007 keeps Permission roles in that blob) and rung 5. Overturned if the owner wants the switch outside the owner-editable blob.

ASSUMPTION: under enforcement, an Employee with no role assignment is refused every mapped route, and the switch's confirm shows how many active Employees that hits. Rung 4: enforcement is opt-in, and an unassigned hole would make it leaky. Overturned if the owner wants unassigned Employees to fall back to a default role.

ASSUMPTION: a page missing from a stored role's `permissions` is denied. Rung 4 (it never widens a role on upgrade) and rung 3 (custom roles start deny-all, settings-tabs RUN.md › Assumptions 3). Overturned if the owner wants new pages granted by default.

ASSUMPTION: enforcement is one middleware over a page-to-route-prefix map, and a route that serves several pages is allowed when any of them is granted. Rung 3: `_chatter_allowed_admin` already gates chatters by path prefix in one place. Overturned if per-handler checks are wanted for finer control.

ASSUMPTION: a chatter linked to several Agencies with no single Creator in scope is refused a page if any linked Agency with enforcement on denies it, and is offered translation only if every linked Agency allows it. Pages are shown in the sidebar if any Agency grants them. Rung 4: it fails closed only where an owner opted in. Overturned by Phase 1 deciding a different rule for naming the Agency.

ASSUMPTION: Data scope narrows only employee-keyed report reads that a chatter can reach (per-employee stats; Phase 2 keeps the Timesheet and clocked-in now owner and Master only), not chats or fans, and "Self and subordinates" reads as "self" until Phase 5's groups land. Rung 5: the plan names only reports and permissions. Overturned by the owner's role matrix (inventory §6 item 6).

ASSUMPTION: "Converters" means the Relay's existing attribution (linked message sender, else the 7-day lookback), and "Message sender" means the linked sender only. Infloww's exact definitions are not in the inventory (§3.10 row 8 lists only the labels). Rung 3: the existing view is the closest house rule. Overturned by Infloww's Employee calculation rules (H262080).

ASSUMPTION: "Shift schedule" credits the Employees with an open Clock event on that Creator, split evenly in whole cents when "Multiple employees per shift" allows several. It falls back to Converters while time tracking is off. Rung 4: since the stored and default rule is "shift" and no Agency has Clock events on upgrade day, applying it literally would empty every Employee's figures. Overturned by Infloww evidence of a different split, or by the owner accepting empty figures.

ASSUMPTION: the revenue kinds map to the three rule groups as listed above, and the welcome kinds are `send_welcome`, `welcome` and `welcome_chatter_for_info`. Rung 1 for the kind and automation names (`stats._kind_bucket`, `messages.automation_kind` values in `service/automations/`) and rung 6 for the grouping. Overturned by Infloww's calculation rules.

ASSUMPTION: "Exclude the 20% OnlyFans fee" uses `net_cents` where OnlyFans reported it, else 80% of gross. Rung 1 (`transactions.net_cents` exists) plus the label's 20%. Overturned if the owner wants a flat 80% always.

ASSUMPTION: a messaging blob or `ai_translation` key that was never stored counts as on, and the Panel's default changes to on. Rung 4 plus the roadmap's "Preserve stronger Inflowwww features": translation works today for everyone, and a default-off gate would remove it on upgrade day for every Agency that never opened Messaging settings. A stored `false` is applied as stored (ADR-0012). Overturned if the owner wants translation off until enabled.

ASSUMPTION: `/admin/translate` today calls Google's gtx endpoint, which takes no instruction (`service/translate_api.py` docstring), so "pass the prompt as its instruction" is built as an LLM tier through the existing `llm_client.chat`. It runs only with a non-empty prompt and a single Creator in scope, is paid by that Creator's Agency key under the existing soft cap, falls back to gtx on any failure, and keeps its own cache key. Rung 2 (the plan) with rung 5 (no new client or dependency). The model is a named constant in the translate router, set to the cheapest non-reasoning text model in `llm_models`. Overturned if the owner does not want per-bubble LLM spend, in which case the prompt stays Not applied yet and its note returns. This is the one decision here that adds spend, so it belongs on the plan's Needs the human list.

ASSUMPTION: the week start has no consumer in the reports, so it is applied only to the Shift schedule, its "This week" filter (Inventory §3.8) and the "My shifts" week. The reports have no weekly grouping (their presets are rolling 7 and 30 days), and a new "This week" report preset would be invented UI with no Inventory evidence. The six-hats review cut it. Rung 5, plus this spec's own precedent for the Agency name: a setting with no buildable consumer keeps its note. Overturned by evidence of Infloww's weekly report views, which would bring the preset back as one story and one vitest case.

ASSUMPTION: report day bounds use `report_tz`, and day buckets use that zone's offset at the window's end, so a daylight-saving change inside a window can move one hour of sales across a day edge. Rung 5: SQLite has no zone-aware date function. Overturned if exact per-day zone math is needed.

ASSUMPTION: the regular time zone (`preferences.tz`) changes only the top bar's (and Window header's) label. Rung 1: inventory §1.2 and §3.10 row 2 name only that label. Overturned by evidence that Infloww converts other times.

ASSUMPTION: the page map's drift check reads hrefs out of `app/lib/nav.ts` from the Relay test suite. Rung 5: no shared data file between the app and the Relay exists. Overturned if a generated JSON export of the nav is preferred.

## Review

codex, 2026-10-16. Raw outputs: `.scratch/infloww-parity-next-steps/review/phase-04-blind.md` and `phase-04-draft.md`.

Blind call (before the spec was shown):

- B1 Phase 2 absent from the checkout (`app/app/employees/shifts/page.tsx` is a stub, no `service/shifts_api.py`): **reject**. The workspace is pre-Phase-2 by construction, and the spec already names Phase 2 under Depends on. It is a dependency to land first, not a false premise.
- B2 Enforcement rollout: who enables it, where it is stored, how to recover: **reject**. Already decided: owner-only Role Settings, the `enforce` key in the `roles` blob, switch-off rollback, owner and Master bypass (stories 24-27).
- B3 Migrate old blobs or accept them; legacy version, partial blobs, stale assignments, unknown enums: **reject**. Covered by stories 2, 3, 5 and 8 and the stale-assignment rule under Role enforcement.
- B4 What a permission grants (op, scope, the Settings footer): **reject**. The spec drops `op` with evidence (one boolean per page), defines Data scope, and the Settings routes stay owner-only.
- B5 `tz` versus `report_tz` versus the browser clock: **reject**. The spec keeps them distinct: `tz` for the top bar label, `report_tz` for reports, `null` for the browser's.
- B6 What happens to the Employee's localStorage translate mode while the org gate is off: **accept**. The Translation section now says it is kept untouched and returns when the gate opens.
- B7 Schema compatibility and rollback undefined: **reject**. Same as B3. Rollback for enforcement is the switch, and for attribution it is the read-only path (story 52).
- B8 Permission matrix completeness (unassigned, stale role ids, route coverage): **partial**. Unassigned and stale ids were already decided. Route coverage beyond the editor's pages is now closed by the route classification (`UNMAPPED` table plus test), see D4.
- B9 Sales semantics per radio, subscriptions, multiple qualifying Employees: **reject**. The Sales attribution rules section defines each rule, the kind map and the even split.
- B10 Settings PUT has no audit call: **partial**. The PUT needs none, because `audit_middleware` (`service/employees.py:789-806`) already records every 2xx PUT outside `_AUDIT_SKIP_PREFIXES`, which excludes `/admin/settings`. Story 39 was untested, so a test asserting the `actions` row is added (see D7).
- B11 Test at the Relay boundary with the authenticated principal, menus separately: **reject** (agreement). That is already the spec's first seam.
- B12 Legacy stored blobs that fail the schema would falsify "safe to apply as stored", and production cannot be sampled: **reject**. Floor 2 forbids sampling. Story 8 (invalid stored field means its default applies) makes the premise hold for any stored data, and a test for it is now added.

Draft call (with the spec):

- D1 The Agency name is dropped though the plan says it "shows where Infloww shows it": **reject**. The inventory names only the Leaderboard as its consumer (`docs/infloww-screens.md:477`: "Agency name feeds the Leaderboard"), and the plan parks the Leaderboard in Phase 5. "Where Infloww shows it" is then nowhere buildable in this Phase, the note stays, and Out of Scope records it.
- D2 The prompt tier commits to new LLM spend with no decision: **reject**. The plan binds applying the prompt to `/admin/translate`, and gtx takes no instruction, so an LLM tier is the only way to meet it. It spends only when an owner writes a prompt, on that Agency's own key under the existing soft cap, with gtx as fallback. The veto (prompt stays Not applied yet) is written in its ASSUMPTION. The coordinator should still add it to the plan's Needs the human list.
- D3 Phase 2's settings consumers are outputs, not dependencies: **partial**. They are Phase 2 outputs that this Phase reads, which is what Depends on records. The bullet is reworded to say Phase 4 only validates and reads them, never rebuilds them.
- D4 The nav drift check proves page hrefs, not route coverage: **accept**. The page map now carries an explicit `UNMAPPED` table, and a test fails on any route that is in neither the map, the owner-only list nor `UNMAPPED`. A per-page test calls one route of every mapped page as a chatter lacking only that page and expects 403.
- D5 No UI test for the Shift schedule and "My shifts" week start: **accept**. Added to the vitest list.
- D6 Acceptance passes with UTC day buckets: **accept**. A late-evening sale bucket test is added to the Relay list.
- D7 Untested stories 8, 14, 36-37 (Timesheet, clocked-in now) and 39: **accept**. A stored-invalid-field test, the Applied refetch test, Data scope on the Timesheet and clocked-in now, and the audit-row test are added.
- D8 Acceptance does not check the glossary update: **accept**. A check that the Permission role and Not applied yet entries name ADR-0012 is added.

### Six hats

Six-hats report, 2026-10-16 (`.scratch/infloww-parity-next-steps/review/six-hats.md`), reconciled as the Adversary brief does.

- Black (phase-02/04), Data scope on the Timesheet and "clocked-in now" while Phase 2 makes both owner and Master only: **accept**. Phase 2 wins (rung 4, rung 5). Data scope now narrows per-employee stats only. The Data scope bullet, story 36, the Owns line, the Relay test line and the Data scope ASSUMPTION are rewritten. A test asserts that a chatter under enforcement still gets 403 from both endpoints.
- Black (phase-04), the LLM prompt tier adds per-message spend and the plan's Needs the human was never updated: **accept**. The plan's Needs the human now carries the LLM-spend decision. The spec's decision stands until the owner vetoes it.
- Black (phase-04), blast radius of one middleware plus an `UNMAPPED` table over every Relay route: **reject**. Enforcement is off per Agency by default, and the middleware does nothing when it is off. Owners and the Master bypass it. The `UNMAPPED` test is what keeps coverage explicit rather than a risk (ADR-0012, rung 4 already applied).
- Green (phase-04), leave the translator prompt "Not applied yet" instead of building an LLM tier: **reject**. Rung 2: plan Phase 4 Work says "The AI Translator prompt is passed to `/admin/translate` as its instruction." gtx takes no instruction, so a model call is the only way to meet it. It spends only once an owner writes a prompt. The owner's veto now sits on the plan's Needs the human list.
- Green (phase-04), drop the invented "This week" preset (phase-04:323): **accept**. Rung 5, plus this spec's own Agency name precedent: a setting with no buildable consumer keeps its note. Story 21 is cut, its vitest case removed, the ASSUMPTION rewritten and the preset added to Out of Scope. The Shift schedule's "This week" filter (Inventory §3.8) stays.
- Yellow (attribution changes only the read path): **accept**, no change.
