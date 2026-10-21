# Phase 02 — Shifts, time tracking and the Dashboard shift cards

**Objective.** One Relay-backed feature reads and writes Shifts and Clock events in one Agency: the Shift schedule at `/employees/shifts`, clock in and out for a Chatter session, the Timesheet, and the Dashboard's "My shifts" and "Current clocked-in employees" cards, all on the same router and under the same Agency isolation.

## Problem Statement

An agency owner has no way to plan who works which Creator when. The "Shift schedule" sidebar item opens a "not built yet" page. Chatters cannot clock in or out, so nobody can tell who is working right now, how many hours anyone worked, or whether a planned Shift was actually worked. The Time tracking Panel in Settings saves an auto clock-out and a reminder policy, and the Sales Panel saves "Multiple employees per shift", but nothing reads either of them, so both Panels say "not applied yet". The Dashboard lacks the two shift cards that Infloww shows.

## Solution

- **Owners.** The owner opens Employees › Shift schedule and sees a week calendar. They can move between weeks, filter by Employee or Creator, and create Shifts in a "Shifts" window. A Shift has a start and end, one or more Creators and Employees, an optional weekly repeat, and an end date or "Never". Owners can edit or cancel a Shift there. A ⚙️ "Shift Settings" dialog sets whether several Employees may work the same Creator at the same time. Below the calendar, a Shift history shows each Employee's and each Creator's scheduled Shifts, Shifts worked, hours and Recorded earnings for the week. Recorded earnings are labelled so nobody mistakes them for payroll.
- **Chatters.** Once the agency turns time tracking on, a chatter can clock in and out on a Creator from the avatar menu or the Dashboard's "My shifts" card. They get an in-app reminder when an assigned Shift has started and they have not clocked in. A clock-in that is left open is closed automatically by the stored auto clock-out policy.
- **Dashboard.** Owners see "Current clocked-in employees". Chatters see their own Shifts and their open Clock event.

## User Stories

Shift schedule (owner)
1. As an owner, I want "Shift schedule" in the Employees menu to open a working page instead of "not built yet", so that I can plan my team.
2. As an owner, I want a week calendar that starts on Monday and shows each day's Shift occurrences with time, Employees and Creators, so that I see the week at a glance.
3. As an owner, I want previous and next week arrows and a "This week" button, so that I can move through the schedule and jump back.
4. As an owner, I want Employee and Creator filters and a "Reset" button, so that I can look at one person's or one Creator's week.
5. As an owner, I want "Create shift(s)" to open a "Shifts" window in which "+ Add Shift" adds rows, so that I can create several Shifts in one go.
6. As an owner, I want to set each Shift's start and end, its Creators and its Employees, so that the plan names who works what.
7. As an owner, I want a weekly repeat by weekday, with "Repeat Ends" set to "Never" or a date, so that I don't re-enter the same week every week.
8. As an owner, I want "OK" to save every row and to show, per row, why the server refused it, so that one bad row does not lose the others.
9. As an owner, I want to open an existing Shift from the calendar and edit it, so that I can fix the plan.
10. As an owner, I want 🗑️ on an existing Shift to cancel it after a confirmation, keeping it in the history, so that a mistake can be traced.
11. As an owner, I want a Shift to keep the timezone it was created in, so that a repeating 09:00 Shift stays at 09:00 local time across daylight-saving changes.
12. As an owner, I want ⚙️ "Shift Settings" with "Allow multiple employees to work on the same shift for the assigned Creator", so that I decide whether one Creator may be double-staffed.
13. As an owner, I want Shift Settings and the Sales Panel to show the same stored value, so that there is one setting and not two.
14. As an owner, I want a Shift that double-staffs a Creator to be refused while that setting is off, with a message naming the clash, so that the rule holds.
15. As an owner, I want a Shift history under the calendar with Scheduled Shifts, Shifts Worked, scheduled hours, worked hours and Recorded earnings per Employee and per Creator for the week shown, so that I can compare plan and reality.
16. As an owner, I want the earnings column labelled "Recorded earnings" with a note that it is not payroll, so that nobody believes the app pays employees.
17. As an owner, I want to correct a chatter's clock-in or clock-out time, and to close one they left open, and have it recorded as my Owner edit, so that the hours are right and the change is traceable.
18. As an owner, I want my session to act as the Agency, so that I never clock in as an Employee by accident.

Clock in and out (chatter)
19. As a chatter, I want "Clock in and out" in the avatar menu, so that I can start and stop my time from any page.
20. As a chatter, I want to pick the Creator I am clocking in on, from the Creators I can access, so that my time is tied to the right Creator.
21. As a chatter, I want a clock-in during an assigned Shift to attach to that Shift automatically, so that "Shifts worked" counts it.
22. As a chatter, I want a clock-in outside any Shift to be allowed and recorded without a Shift, so that unplanned work still counts.
23. As a chatter, I want a second clock-in while I am already clocked in to be refused with "already clocked in", so that I cannot hold two open Clock events in one Agency.
24. As a chatter, I want a clock-out with nothing open, or on an event that is not mine, to be refused, so that invalid clock-outs cannot happen.
25. As a chatter, I want a clear "Time tracking is off for your agency" message when the agency has not turned it on, so that I know why I can't clock in.
26. As a chatter linked to two agencies, I want clocking in on a Creator to file the time under that Creator's agency, so that each agency sees only its own time.
27. As a chatter, I want an in-app reminder toast when an assigned Shift has started and I haven't clocked in, if my agency turned the reminder on, so that I don't forget.
28. As a chatter, I want an open clock-in that I forgot to be closed automatically after the configured minutes, so that my hours don't run on overnight.

Dashboard
29. As a chatter, I want a "My shifts" card with today's and the next seven days' Shift occurrences, my open Clock event with its elapsed time, and a Clock in or Clock out button, so that the Dashboard is where my day starts.
30. As an owner, I want the "My shifts" card to say that owner sessions act as the agency and to link to the Shift schedule, so that the card is never empty without a reason.
31. As an owner, I want a "Current clocked-in employees" card listing who is clocked in, on which Creator, since when, and in which Shift or none, so that I see who is working now.
32. As a chatter, I want the "Current clocked-in employees" card hidden, so that I see only my own time.
33. As an owner or a chatter, I want both cards to say "Time tracking is off" (owners also get a link to Settings › Time tracking) when it is off, so that an empty card is explained.

Settings consumers
34. As an owner, I want the Time tracking Panel to drop "not applied yet" now that its three fields take effect, so that the Panel tells the truth.
35. As an owner, I want the Sales Panel to say that only "Multiple employees per shift" is applied so far, so that I don't assume the attribution radios already take effect.
36. As an owner whose blobs were saved while they were inert, I want odd stored values (a non-number for minutes, a missing key) to fall back to the Panel defaults, not break clocking, so that the upgrade is safe.

Tenancy, audit and safety
37. As an owner, I want any request for another agency's Shift, Clock event or Creator to be refused, so that agencies in one Deployment never see each other's schedules.
38. As a signed-out caller, I want every shifts endpoint to answer 401, so that nothing is readable without a session.
39. As a chatter, I want every owner-only shifts endpoint to answer 403, so that I can't edit the schedule.
40. As an owner, I want every create, edit, cancel, clock-in, clock-out, auto clock-out and Owner edit written to the audit history with who did it and what changed, so that the history is safe to rely on.
41. As an operator, I want the migration to have a working downgrade, so that a bad release can be rolled back.
42. As an operator, I want two simultaneous clock-ins from one chatter to leave exactly one open Clock event, so that a double click or two tabs cannot corrupt the data.

## Implementation Decisions

- **Owns.**
  - Relay: a new router module `shifts_api` (registered in `server`), three new models in `db.models` (`Shift`, `ShiftAssignment`, `ClockEvent`) and one Alembic revision after `0066_split_inbox`.
  - App: the page at `/employees/shifts`, a new `components/shifts/` folder (`ShiftSchedule`, `ShiftsWindow`, `ShiftSettingsDialog`, `ShiftHistory`), two Dashboard cards in `components/home/` (`MyShiftsCard`, `ClockedInCard`) placed on the home page, a `ClockDialog` opened from the top bar's `AvatarMenu` (`components/shell/TopBar.tsx`, not the Fan menu in `components/chat/AvatarMenu.tsx`), a shifts client in `lib/shifts` (types and react-query hooks), the `nav` entry, a reminder source in `NotificationToaster`, and the notes on `TimeTrackingTab` and `SalesSettingsTab`.
  - Docs: the `docs/routes.md` Shift schedule row, and the Parity matrix rows for §3.8 "Shift schedule" and the §3.1 shift cards.
- **Reuses, unchanged.** Phase 1's `agency_context(*, account_id=None)` and its two-agency test fixture, `assert_account_owned`, the `actions` table, `user_settings` rows (read directly, no HTTP hop), the `per_employee_revenue_with_attribution` view that stats already reads, `useSettingsBlob`, `renderWithProviders`/`jsonRes`.

- **Schema.** Every table is agency-scoped through `agency_user_id`, which comes from `users.id`. The ORM models declare the same indexes as the migration, because deploys run `init_db()` (create_all plus the additive catch-up), not `alembic upgrade` (`service/tests/test_automation_queue_indexes.py` docstring).

  ```
  shifts            id PK, agency_user_id FK users ON DELETE CASCADE NOT NULL,
                    start_utc, end_utc NOT NULL (first occurrence; end > start, length <= 24 h),
                    tz TEXT NOT NULL (IANA name),
                    repeat_days TEXT NULL  (JSON list of ISO weekdays 1..7 in tz; NULL = no repeat),
                    repeat_until DATE NULL (last local date in tz, inclusive; NULL = "Never"),
                    status TEXT NOT NULL CHECK IN ('scheduled','cancelled'),
                    created_by TEXT NOT NULL ('owner:<users.id>'), created_at, updated_at, cancelled_at NULL
                    INDEX (agency_user_id, start_utc)
  shift_assignments shift_id FK shifts ON DELETE CASCADE, employee_id FK employees ON DELETE CASCADE,
                    account_id FK accounts ON DELETE CASCADE; PK (shift_id, employee_id, account_id)
                    INDEX (employee_id), INDEX (account_id)
  clock_events      id PK, agency_user_id FK users ON DELETE CASCADE NOT NULL,
                    employee_id FK employees ON DELETE SET NULL NULL, account_id FK accounts ON DELETE SET NULL NULL,
                    shift_id FK shifts ON DELETE SET NULL NULL,
                    in_utc NOT NULL, out_utc NULL (NULL = open; out > in),
                    close_reason TEXT NULL CHECK IN ('manual','auto','owner_edit')
                    UNIQUE INDEX (employee_id) WHERE out_utc IS NULL     -- one open Clock event per Employee
                    INDEX (agency_user_id, in_utc), INDEX (account_id, in_utc)
  ```

  ASSUMPTION: `clock_events` carries `agency_user_id`, which the plan's column list leaves out. Without it, "clocked-in now" and the Timesheet would have to reach the Agency through `employees.user_id`, and that link is lost when an Employee is deleted (SET NULL). Rung 5. Overturned if the owner wants a deleted Employee's time dropped instead, which would make it CASCADE.

  ASSUMPTION: a Shift with E Employees and C Creators stores E×C `shift_assignments` rows, one per (Employee, Creator) pair. This is the plan's "shift × employee × account", taken literally. Rung 2. Overturned by evidence that Infloww pairs Employees and Creators selectively inside one Shift.

  The plan's index on `(employee_id, out_utc IS NULL)` is folded into the partial unique index, which serves the same lookup. The migration's `downgrade()` drops the three tables in reverse order. Recovery path: downgrade loses only shift and clock data, and nothing else reads it.

  ASSUMPTION: Shifts and Clock events are kept until their Agency is deleted. Their audit rows in `actions` follow the existing 90-day `ACTIONS_RETAIN_S` sweep (`service/server.py`). Rung 3. Overturned if the owner wants the edit history kept longer than other audit rows.

- **Interfaces: the Relay router, prefix `/admin/shifts`.**
  - Every handler starts from Phase 1's `agency_context`, called inline as `await agency_context(account_id=...)` with the request's `account_id` where the endpoint takes one (clock-in, `?account_id` filters), else `await agency_context()`. It takes no `request` (Phase 1 Contracts and its signature ASSUMPTION; settled by the six-hats review).
  - Check order: 401 (no principal, even with `ALLOW_ANONYMOUS_ADMIN`), then 403 (wrong role for the endpoint), 404 (an id from another Agency or a missing id), 422 (invalid body) and 409 (a state conflict).
  - Times on the wire are ISO-8601 UTC strings ending in `Z`, and money is integer cents.

  | Method and path | Who | Does |
  |---|---|---|
  | `GET /admin/shifts?from&to&employee_id?&account_id?` | owner, Master | Shift occurrences that intersect [from, to). The range is at most 42 days (422 beyond). Cancelled Shifts are left out. Each item is `{shift_id, occurrence_start, occurrence_end, tz, repeat_days, repeat_until, employees[{id, display_name}], accounts[{id, display_name}]}` |
  | `POST /admin/shifts` | owner, Master | Creates a Shift from `{start_utc, end_utc, tz, repeat_days?, repeat_until?, employee_ids[≥1], account_ids[≥1]}` and returns it |
  | `PATCH /admin/shifts/{id}` | owner, Master | Replaces the editable fields of the whole series. A cancelled Shift is 409. Clock events are never rewritten by it: an open one stays open, and its Shift link is recomputed on read (Further Notes) |
  | `POST /admin/shifts/{id}/cancel` | owner, Master | Sets `status=cancelled` and `cancelled_at`. Cancelling twice is 409. Open Clock events linked to it stay open |
  | `GET /admin/shifts/me` | chatter | `{accounts[{account_id, display_name, time_tracking_enabled, clock_in_reminder}], occurrences[] (now to now+8 days), open_clocks[], reminder: occurrence or null}`. `accounts` is the chatter's accessible Creators, each with its own Agency's time-tracking flags. Only the caller's own Mirror Employee rows are returned, each item carrying its `account_id` |
  | `POST /admin/shifts/clock-in` | chatter | `{account_id, shift_id?}` returns the open Clock event |
  | `POST /admin/shifts/clock-out` | chatter | `{clock_event_id}` returns the closed event with `close_reason=manual` |
  | `GET /admin/shifts/clocked-in` | owner, Master | The Agency's open Clock events: `{clock_event_id, employee, account, in_utc, shift_id}` |
  | `PATCH /admin/shifts/clock-events/{id}` | owner, Master | An Owner edit of `{in_utc?, out_utc?}`. Closing an open event sets `close_reason=owner_edit` |
  | `GET /admin/shifts/timesheet?from&to&group=employee\|account` | owner, Master | Timesheet rows `{key, display_name, scheduled_shifts, shifts_worked, scheduled_minutes, worked_minutes, recorded_earnings_cents, open_now}` |

  The shared contract that the app's `lib/shifts` types mirror is `ShiftOccurrence`, `ClockEvent`, `TimesheetRow` and `MyShifts`.

- **Agency scope.**
  - Owner and Master sessions act on their own Agency only.
  - A Chatter session acts as the Mirror Employee of the Agency that owns the named account (Phase 1). `account_id` passes `assert_account_owned`.
  - Every `employee_id` and `account_id` in a body must belong to the Shift's Agency (`employees.user_id` and the owner's `user_accounts`), or the request gets 422. This also stops a Master from mixing two Agencies in one Shift.
  - A Shift id or Clock event id from another Agency is 404.

  `GET /admin/shifts/me` resolves the Agency once per accessible account, with the same rule as `agency_context`, and returns only the caller's own Mirror Employee rows in each. No Agency's data reaches another Agency, so this is not the cross-agency read that ADR-0011 reserves for S4S Discovery. Time-tracking flags are per Agency, so they are reported per account, never merged.

  ASSUMPTION: one `me` call that covers every Agency the chatter is linked to, instead of one call per named account. Rung 5: the Dashboard card shows the chatter's whole day, and each row is already reachable account by account. Overturned if the owner reads Phase 1's "the request names the agency through an account" as forbidding the union, in which case `me` takes a required `account_id`.

  ASSUMPTION: a Master gets no cross-agency read or write of schedules here. Rung 4: reading every Agency's schedule is additive later. Overturned if the owner wants a Master view of every Agency's schedule.

- **Occurrence rule.**
  - A Shift's first occurrence is `[start_utc, end_utc)`.
  - With `repeat_days`, every local date in `tz` from the start's local date through `repeat_until` (or with no end for "Never") whose ISO weekday is in `repeat_days`, plus the start's own weekday, gets an occurrence. Each occurrence starts at the start's local wall-clock time and lasts the same wall-clock length, computed with `zoneinfo` (house precedent: `service/automations/rhythm.py`) and converted to UTC.
  - DST: a wall time that does not exist (spring forward) resolves with `fold=0`, and a repeated one (fall back) takes the first instant. So an occurrence's real length can differ by an hour on a transition day.
  - Occurrences are expanded at read time over the requested range and never stored.
  - An unknown `tz` is 422.

  ASSUMPTION: an edit or cancel always applies to the whole series. There is no single-occurrence exception. Rung 5: the Inventory (§3.8) shows only "OK" and 🗑️. Overturned by evidence of a per-occurrence edit.

  ASSUMPTION: 🗑️ cancels a Shift (soft) and never deletes the row. Rung 2: the roadmap asks for "safe edit/cancel history". Overturned if the owner wants a hard delete for Shifts created by mistake.

- **Overlap rule (`sales.multi_employee_shift`).**
  - When the stored value is not literally `true`, a create or edit gets 409 `{detail, clashes[{shift_id, occurrence_start, account_id}]}` in either case:
    - the Shift itself puts more than one Employee on one Creator;
    - any of its occurrences overlaps a non-cancelled occurrence of another Shift on the same Creator.
  - Overlaps are checked over the intersection of both series, capped at 53 weeks after the later start. Fifty-three weeks covers a full DST cycle, and both rules repeat weekly.
  - When the value is `true`, overlaps are allowed.
  - The rule is checked only on writes. Shifts that overlapped before the setting was turned off are left alone.

  ASSUMPTION: the 53-week cap and the write-only check are rungs 5 and 4. Overturned if the owner wants turning the setting off to flag existing clashes.

- **Clock rules.**
  - *Settings.* Write-side schema validation with a `version` key (ADR-0012) is Phase 4's work (plan, Phase 4 › Work, "Server-side blob validation"). Until then this Phase reads leniently, as below, which is ADR-0012's "applied as stored" for odd values. The `time-tracking` blob is read at request time. `enabled` counts only when it is literally `true`. `auto_clock_out_minutes` is used when it is an integer of 1 or more, and is otherwise 60. `clock_in_reminder` counts only when it is literally `true`. These defaults match `TimeTrackingTab`'s `DEFAULTS`. When `enabled` is not true, clock-in gets 409 "time tracking is off" (clock-out still closes an open event: Amended by w4-a). Reads still answer, so the cards can explain themselves.
  - *Who clocks.* Owner and Master sessions clock on the owner's own Employee row (Amended by w4-a); `GET /me` stays chatter-only (403). An inactive Mirror Employee gets 403 on clock-in.
  - *Clock-in.* A clock-in when an open event exists is 409 "already clocked in". The partial unique index backs this, so a concurrent second insert that slips past the pre-check raises IntegrityError, and that maps to the same 409, never a 500. Without `shift_id`, the server attaches the occurrence that contains now and is assigned to this Employee on this account, if there is one. When several do (possible while `multi_employee_shift` is on), it takes the earliest `occurrence_start`, then the lowest `shift_id`. An explicit `shift_id` must be such an occurrence, or the request gets 422.
  - *Clock-out.* `clock_event_id` must be the caller's own open event. Someone else's event is 404, and an already-closed one is 409.
  - *Owner edit.* The new interval needs `in < out ≤ now`. It must not overlap another Clock event of the same Employee (409).
- **Auto clock-out (lazy).** At the start of every `/admin/shifts` request, the caller's Agencies' open Clock events are swept. An event is closed with `close_reason=auto` and `out_utc = deadline` once now ≥ deadline, where:
  - with a Shift, the deadline is the occurrence end plus `auto_clock_out_minutes`;
  - without one, it is the last activity plus `auto_clock_out_minutes`, where last activity = max(`in_utc`, the latest `actions.at` for that `employee_id`).

  Writing the deadline, not the moment of the sweep, means the result does not depend on when anyone next opened the app. The plan's ASSUMPTION (rung 5, no scheduler) stands. The sweep runs even when time tracking is off, so a policy switched off mid-shift still closes what it opened.

- **Clock-in reminder.**
  - `GET /admin/shifts/me` returns `reminder` when four things hold: time tracking is on, `clock_in_reminder` is on, an assigned occurrence contains now, and that Employee has no open event.
  - The app polls `me` every 60 s (chatter sessions only).
  - `NotificationToaster` shows one toast per (shift_id, occurrence_start), keyed in `localStorage`. It reads "Your shift on <Creator> has started." and has a "Clock in" action that opens `ClockDialog`.
  - There is no email, push or OnlyFans send (the plan's ASSUMPTION).

- **Timesheet.** For [from, to), which the app sends as the viewed week in the browser's timezone, converted to UTC. An occurrence or Clock event that crosses a range edge counts once and is clipped:
  - `scheduled_shifts` counts the assigned occurrences.
  - `shifts_worked` counts the occurrences overlapped by a Clock event of an assigned Employee on that Creator.
  - `scheduled_minutes` and `worked_minutes` are real elapsed minutes clipped to the range. An open event counts up to now and sets `open_now`.
  - `recorded_earnings_cents` sums `amount_cents` from `per_employee_revenue_with_attribution` where `sent_by_employee_id` and `account_id` match the Clock event and `occurred_at` falls inside the worked interval.
  - There is no payroll field.
  - Phase 4 later applies the Sales exclusions to this read path. Here the figures are gross as stored.

- **Audit.**
  - Each write appends one `actions` row with `action` ∈ {`shift.create`, `shift.edit`, `shift.cancel`, `clock.in`, `clock.out`, `clock.auto_out`, `clock.owner_edit`}.
  - `target_type` is `shift` or `clock_event`, and `target_id` is the row id.
  - `account_id` is the event's account, or the Shift's first account.
  - `employee_id` is the acting Mirror Employee, or NULL for an owner or the sweep.
  - `payload_json` is `{actor: "owner:<id>" | "employee:<id>" | "system", before, after}`.
  - These rows sit beside the generic row that the audit middleware already writes for every mutating request. That middleware is not changed.

  ASSUMPTION: edit history is read through the existing audit views. No new history screen is built. Rung 5. Overturned by a request for a per-Shift history panel.

- **App.**
  - `nav`: the `nb("Shift schedule", …)` entry becomes a plain link. The Employees group stays `chatterHidden`.
  - The page renders `ShiftSchedule`. A Chatter session that reaches it by URL gets "Only the agency owner manages the Shift schedule."
  - The calendar uses the browser's timezone and starts on Monday. Phase 4 later applies the `preferences` week start and timezone.
  - The Shifts window defaults a new row's `tz` to the browser's timezone and shows the Shift's `tz` beside its times when it differs from the viewer's.
  - `ShiftSettingsDialog` reads and writes the `sales` blob through `useSettingsBlob("sales")`, changing only `multi_employee_shift` and keeping the other keys (ADR-0007 whole-blob replace). It stores nothing of its own.
  - `ShiftHistory` defaults to group by Employee and can switch to group by Creator. The earnings column header is "Recorded earnings", with the tooltip "Infloww calls this Total Earnings. Earnings already credited during worked time; not payroll."
  - Cards: `MyShiftsCard` and `ClockedInCard` go on the home page above the revenue charts. `ClockedInCard` renders only for a User session. Both poll every 60 s. Each card shows a loading line while its first request is in flight and an error line with Retry when it fails, the same pattern as `useSettingsBlob`'s Load gate.
  - `AvatarMenu` gains "Clock in and out" for Chatter sessions only. It opens `ClockDialog`, which offers a Creator picker built from the chatter's accessible accounts and Clock in, or shows the open event and Clock out.
  - Settings notes: `TimeTrackingTab` drops "Saved for your organization; not applied yet.". `SalesSettingsTab`'s note becomes "Saved for your organization; only "Multiple employees per shift" is applied yet." Phase 4 later removes it field by field.

  ASSUMPTION: the Sales note wording is new copy, rung 5. Overturned by Phase 4's per-field note design.

  ASSUMPTION: `ClockedInCard` is shown to owners and the Master only, and the endpoint is 403 for chatters. Rung 4: it exposes the least, and showing it more widely is additive. The same holds for the Timesheet. Phase 4 keeps both owner and Master only: it does not open them to chatters, so its Data scope never applies to them (settled by the six-hats review, both specs). Overturned by the owner wanting chatters to see either one, or by evidence that Infloww shows it to every Employee. Opening them would be a later additive change that applies Data scope at the same time.

  - Assignment access: a create or edit that pairs a Mirror Employee with a Creator its chatter cannot access gets 422 naming the pair. Access is the same per-owner allowlist that feeds the chatter's `account_ids` and `assert_account_owned` (`service/chatters.py:214-229`), so every assigned pair can be clocked. An Employee with no chatter login may be assigned; it cannot clock in, and its occurrences count as scheduled, not worked.

  ASSUMPTION: refusing an assignment the chatter cannot clock, rather than allowing it. Rung 4: loosening the check later is additive, while allowing it now creates Shifts that reminders and "Shifts worked" can never satisfy. Overturned by Phase 4's Data scope, if it decouples clocking from Creator access.

## Testing Decisions

The Phase has two seams. Both are the highest one available, and both already exist.

1. **Relay HTTP seam.** Three plain-assert scripts on `_harness`, one seam: `service/tests/test_shifts_api.py` holds the
   Shift schedule cases (create, edit, cancel, repeats, overlap, storage), `service/tests/test_clock_api.py` holds
   the clock cases (clock-in and clock-out, the my-shifts read, the clock audit rows), seeding its own chatters, and
   `service/tests/test_timesheet_api.py` holds the Timesheet cases. The clock and Timesheet scripts share their
   seeders through `service/tests/_clock_fixtures.py`.
   - They drive `/admin/shifts/*` through `_harness.make_client()` with real cookie sessions from `/auth/login`, against the temp DB.
   - They use Phase 1's two-agency fixture: an owner, a chatter and a Creator in each Agency.
   - Assertions are on status codes, response bodies and the rows the endpoints leave behind (`shifts`, `clock_events`, `actions`). Internals are never asserted.

   Cases:
   - 401 for every endpoint, even with `ALLOW_ANONYMOUS_ADMIN=1`; 403 for a chatter on owner endpoints and for an owner on clock endpoints.
   - Cross-agency 404 or 422 for every id and every body reference, in both directions.
   - A chatter linked to both Agencies files time under the account's Agency.
   - Create, edit and cancel round trips, each with its audit row and actor.
   - An assignment whose chatter is restricted from the Creator (422), and one with no chatter login (200).
   - `GET /admin/shifts/me` for a chatter in both Agencies, with time tracking on in one and off in the other: per-account flags, and no other Employee's rows.
   - Repeating occurrences across `America/New_York` spring forward and fall back (gap and fold), and `repeat_until`, read back through `GET` in the transition weeks.
   - Overlap: 409 with `multi_employee_shift` off or absent, 200 with it on, including a repeating series that clashes in a later week.
   - Clock-in that auto-attaches to the assigned occurrence containing now, the earliest-start tie-break between two such occurrences, an explicit `shift_id` that is not assigned (422), and a clock-in outside any Shift (no link).
   - Clock-in with time tracking off (409), with a stored non-number for minutes (clocking still works), a duplicate clock-in (409), and two clock-ins fired concurrently from two threads (exactly one 200 and one open row).
   - An invalid clock-out (none open, someone else's, already closed).
   - Abandoned events, swept lazily with `out_utc` equal to the deadline, both with a Shift and without one (using last activity), and with a stored non-number for minutes (the default of 60 is used); seeded with past timestamps so no clock is mocked.
   - An Owner edit, and an Owner edit that overlaps (409).
   - The `clock.in`, `clock.out`, `clock.auto_out` and `clock.owner_edit` audit rows, with their actor (`employee:<id>`, `system`, `owner:<id>`).
   - Timesheet figures, including Recorded earnings from seeded `transactions` and `messages` rows inside and outside a worked interval.
   - A migration case that runs the revision's `upgrade()` and `downgrade()` through Alembic `Operations` on a fresh temp SQLite file, never the harness DB or any real one, and asserts the tables and the partial unique index appear and disappear.
   - An `init_db()` catch-up case: drop the three tables from the harness DB, re-run `init_db()`, and assert they return with their indexes (the `test_automation_queue_indexes.py` pattern).

   Prior art: `service/tests/test_settings_api.py` and `test_split_inbox_api.py` (cookie sessions through the harness client), `test_account_isolation_gate.py` (cross-tenant negatives) and `test_automation_queue_indexes.py` (the `init_db` catch-up).

2. **App fetch seam.** Vitest renders components with `renderWithProviders`, and `fetch` is mocked by URL with `jsonRes`, so every assertion is about the wire and the rendered text.
   - `components/shifts/ShiftSchedule.test.tsx`: the week query's `from`/`to`, week navigation and "This week", the filters and Reset, the "Shifts" window posting one request per row and showing a per-row 409/422 message, edit, cancel after confirmation, a Shift Settings save that sends the whole `sales` blob with only `multi_employee_shift` changed, the "Recorded earnings" header and its tooltip, and the chatter message.
   - `app/employees/shifts/page.test.tsx`: the route module itself renders `ShiftSchedule` (the week query fires), so the page cannot pass while it mounts nothing.
   - `components/home/ShiftCards.test.tsx`: both cards for owner and chatter sessions, the owner's "owner sessions act as the agency" text and its Shift schedule link, the time-tracking-off states, `ClockedInCard` absent for chatters, Clock in and Clock out through `ClockDialog` from the card and from `AvatarMenu`, and the menu item absent for owners.
   - Additions to the existing `NotificationToaster.test.tsx` (the reminder toast appears once per occurrence, and its "Clock in" action opens `ClockDialog`), `TimeTrackingTab.test.tsx` (no "not applied yet") and `SalesSettingsTab.test.tsx` (the new note).
   - `lib/nav.test.ts` stays as it is and keeps passing, because the Shift schedule is no longer `notBuilt`.

   Prior art: `components/settings/TimeTrackingTab.test.tsx` (fetch mocked by URL), `components/NotificationToaster.test.tsx`, `contexts/UserContext.test.tsx`.

A visual walk of `/employees/shifts` and `/` with the existing harnesses is a manual step (below). It is not a seam.

## Acceptance

```sh
set -e
cd "$(git rev-parse --show-toplevel)"

# The route is built, not stubbed
# (`! cmd` does not trip `set -e`, so each negative check exits explicitly)
test -s app/app/employees/shifts/page.tsx
if grep -q 'NotBuiltYetRoute' app/app/employees/shifts/page.tsx; then echo "shifts page still a stub" >&2; exit 1; fi
grep -q 'ShiftSchedule' app/app/employees/shifts/page.tsx
if grep -q 'nb("Shift schedule"' app/lib/nav.ts; then echo "nav still marks Shift schedule not built" >&2; exit 1; fi
if grep -qE '^\| Employees > Shift schedule.*\| stub \|' docs/routes.md; then echo "routes.md still says stub" >&2; exit 1; fi
test -s service/shifts_api.py
ls service/db/migrations/versions/ | grep -q shifts

# Relay: the shifts router, migration, tenancy, DST, overlaps, audit; then the clock rules and their audit
./venv/bin/python service/tests/test_shifts_api.py
./venv/bin/python service/tests/test_clock_api.py
./venv/bin/python service/tests/test_timesheet_api.py
./venv/bin/python service/tests/test_settings_api.py
./venv/bin/python service/tests/test_account_isolation_gate.py

# App
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run \
  app/employees/shifts/page.test.tsx \
  components/shifts/ShiftSchedule.test.tsx components/home/ShiftCards.test.tsx \
  components/NotificationToaster.test.tsx components/settings/TimeTrackingTab.test.tsx \
  components/settings/SalesSettingsTab.test.tsx lib/nav.test.ts
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run

# manual: walk /employees/shifts and / at 1440x900 and 390x844, light and dark, with scripts/ui-shots.sh or
# scripts/settings-check/walk.py; PNGs under /tmp only; grade the §3.8 Shift schedule and §3.1 shift-card rows
# of docs/infloww-parity-matrix.md and record their Inventory version.
```

## Depends on

- **Phase 0.** The Merged tree: the `time-tracking` and `sales` Blob tabs, `useSettingsBlob`, the Settings Panels, `NotificationToaster`, `AvatarMenu` and `nav`, all on `main`. Also `docs/infloww-parity-matrix.md`, whose shift rows this Phase grades.
- **Phase 1.** `agency_context(*, account_id=None)`, which gives the Agency, Mirror Employee, owner or Master from the session alone, including a chatter linked to more than one Agency naming the Agency through an account. Also the two-agency plain-assert fixture and the 401 rule for unauthenticated callers on new endpoints.

## Out of Scope

- **Payroll, pay rates and payouts to Employees.** The roadmap forbids claiming to pay employees, so the Timesheet shows Recorded earnings only.
- **Applying the Sales attribution radios, `exclude_welcome` and `exclude_of_fee` to the Timesheet.** Phase 4 owns this, and here the figures are gross as stored.
- **Employee reports "Clocked hours" and its export.** Phase 5 item 2 owns this, fed by this Timesheet.
- **The Shift history columns on the Employees page.** Phase 5 item 1 owns this. Here the history sits on the Shift schedule page.
- **Permission roles gating the shifts endpoints, and the `preferences` week start and timezone.** Phase 4 owns both. Until then the calendar starts on Monday and uses the browser timezone.
- **Platform split of hours.** Infloww itself says "Clocked hours are not differentiated by platform".
- **Native desktop, email or push notifications, and any OnlyFans send.** The reminder is in-app only (floor 2 and the plan).
- **A scheduler or background job for Auto clock-out.** The plan forbids a new scheduler, so the sweep is lazy.
- **Repeat kinds other than weekly, and single-occurrence exceptions.** The Inventory shows only weekly repeats (YAGNI).
- **Owners clocking in as themselves.** No owner-to-Employee link exists (Phase 1's ASSUMPTION).
- **Owners creating a Clock event for someone from scratch.** This is not in the plan or the Inventory. Owner edit covers corrections.
- **A per-Shift history screen.** Audit rows are readable through the existing audit views.
- **A Master view of every Agency's schedule.** This is additive later (ASSUMPTION above).

## Further Notes

Every open question below was decided by the ladder and is flagged.

ASSUMPTION: the endpoints live under `/admin/shifts` rather than `/api/shifts`. Rung 3: every agency-scoped Relay router in this repo uses `/admin/*` (`settings_api`, `employees`, `split_inbox`). Overturned by a routing convention that the Phase 0 matrix records.

ASSUMPTION: `zoneinfo` needs no new dependency in the Relay image. Rung 3: `service/automations/rhythm.py` already uses `ZoneInfo` in production on `python:3.13-slim`. Overturned if a test run shows `ZoneInfoNotFoundError`. In that case adding `tzdata` to `requirements.txt` is a new dependency, which parks the ticket with the exact `pip install tzdata` command for the human.

ASSUMPTION: a Shift's length is capped at 24 hours, and a range read at 42 days. Rung 5: these bound occurrence expansion and the overlap check, and the Inventory shows no multi-day Shift. Overturned by evidence of longer Shifts.

ASSUMPTION: a Clock event's Shift link is recomputed from the Shift's current rule when the Timesheet and the sweep run. No occurrence snapshot is stored. Rung 5. Overturned if editing a Shift after it was worked must leave past "Shifts worked" untouched, which would need an `occurrence_start_utc` column on `clock_events`.

ASSUMPTION: "My shifts" shows today plus the next seven days. Rung 6: the Inventory gives no range, so this was a coin flip. Overturned by evidence of Infloww's range.

The plan's other ASSUMPTION lines for this Phase are adopted as written: the lazy Auto clock-out, the in-app reminder through `NotificationToaster`, "Clock in and out" in the avatar menu (Inventory §1.2 marks the placement G, so the matrix records it as unverified), the card titles "My shifts" and "Current clocked-in employees" (from the `.myshifts` and `.clocked` CSS classes), and weekly repeats expanded at read time in the Shift's own `tz`.

## Amended by w4-a

The w4-a time tracker (`.scratch/wave-prompts/w4-a-time-tracker.md`, branch `time-tracker-clock`) aligns the clock with Infloww's (bundle `ClockInOrOut`, `ClockSetting`, `ClockInModal`). Where it disagrees with the text above, it wins:

- **The Creator-less clock.** `POST /admin/shifts/clock-in` takes no Creator: the event is agency-wide (`account_id` NULL), attached to the Employee's earliest Shift occurrence on any Creator. A chatter in two Agencies still names a Creator (`clock-status` `reason: "pick_creator"`, `ClockDialog`). The top bar's Clock button replaces the avatar menu's "Clock in and out".
- **Where an agency-wide event counts.** It is on a Creator only inside the occurrences of its Agency's live Shifts that assign its Employee to that Creator, merged per Creator; time outside every such occurrence is on no Creator. `shift_time.creator_spans` is that one linkage, and every figure reads it:
  - Shifts worked: an occurrence counts as worked for an Employee and Creator it assigns when that Employee's time on that Creator overlaps it.
  - Worked minutes: per Employee, the whole event (rounded up to the minute, as Infloww's tooltip says); per Creator, only the event's time on that Creator.
  - Recorded earnings: a credited sale counts when it falls in its Employee's time on its Creator.
  - Shift schedule attribution: an agency-wide event credits a sale on a Creator only while its Employee holds that Creator in an occurrence that contains the sale.

  This overrides the w4-a prompt's step 5, which put an agency-wide event's earnings and Shift schedule credit on any Creator. Read that way, two Employees clocked in agency-wide split a sale on either one's Creator. The Timesheet's per-Creator rule wins, for consistency (review F2).
- **The role gate.** The `time-tracking` blob gains `role_ids` ("Enable clock in and clock out for"). An Employee with no role cannot clock in. Amended by w5-a (below): a missing key allows nobody.
- **The inactivity-only sweep.** Auto clock-out closes an event `auto_clock_out_minutes` (now 10 when never saved) after its last sign of life: `max(in_utc, last_seen_utc, latest action)`, with `last_seen_utc` (revision `0075_clock_last_seen`) renewed by `POST /admin/shifts/clock-heartbeat` after real input. The Shift end no longer matters. The Timesheet's `worked_minutes` rounds up, as Infloww's tooltip says.
- **The Auto clock out notices.** The top bar (and Messages Pro, which has none) says Infloww's "You have been clocked out due to inactivity" once for an event it saw open, or "You have been clocked out as your internet connection was lost." when the tab's network attempts (heartbeats and status reads) had failed with no success since, the first at or before the close. This overturns the w4-a prompt's "There is no separate 'internet connection was lost' message", at the owner's request. The Relay's sweep still does the closing either way.
- **Clock-out while tracking is off.** Clock-out closes the caller's own open event even when time tracking is off or its Employee is inactive: closing writes no new time, and a refusal would leave the event open for the sweep to close later, counting more time. `POST /admin/shifts/clock-heartbeat` renews no event of an Agency whose time tracking is off, so an event left open then is auto clocked out.
- **Owners clocking.** An owner, or the Master, clocks in on its own Employee row (`owner:<uid>`) when the Owner role is ticked; this replaces the Out of Scope line "Owners clocking in as themselves". Owners read one Employee's Clock events (`GET /admin/shifts/clock-events`) in Employee reports' Clocked hours modal, where the Owner edit has its app control.

## Amended by w5-a

Checked against the live Infloww app (2026-10-19, `.scratch/infloww-live/`); the owner chose "make it look like Infloww" for all three:

- **A never-saved role list is all unticked.** Infloww's ClockSetting shows every role unticked until the list is saved, so a missing `role_ids` lets nobody clock in (owner included); the Panel shows every box unticked and its first save writes the ticked list. Clock-out still closes an open event. An Agency with tracking on and no saved list stops clocking in until an owner saves the list.
- **Team Leader, Chatter and Creator are built-in roles** beside Owner and Admin (`settings_schema.BUILT_IN_ROLE_DEFAULTS`, `app/lib/roles.ts`): listed in Role Settings, the role selects and the role gate, never deletable or renamed. Unstored, Team Leader grants the Manager preset's pages with scope "Self and subordinates", Chatter the chatting pages (scope self), Creator the content pages (scope self); a stored copy wins, so an Agency already holding the old Chatter preset (id `chatter`) keeps it. The Chatter preset is no longer seeded; Manager and VA still are.
- **Auto clock out is 1 to 999 minutes** (Infloww's InputInteger max), in the Panel and the Relay (was 1440).

codex, 2026-10-16. Raw outputs: `.scratch/infloww-parity-next-steps/review/phase-02-blind.md` and `phase-02-draft.md`.

Blind call (before the spec was shown):
- B1 Store occurrences instead of weekly rules — **reject**: the plan's ASSUMPTION (expanded at read time) is a constraint, and the Inventory shows only weekly repeats.
- B2 Scheduler instead of the lazy sweep — **reject**: the plan forbids a new scheduler. The spec writes `out_utc = deadline`, so the figures do not depend on when the sweep runs.
- B3 "Last activity" undefined — **reject**: the spec defines it as max(`in_utc`, latest `actions.at` for the Employee).
- B4 One Creator per Clock event versus several — **reject**: the glossary defines a Clock event as one Employee on one Creator (CONTEXT.md, Shifts and time tracking).
- B5 `agency_context` is absent from the source — **reject**: it is Phase 1's deliverable, and Phase 1 is listed under Depends on.
- B6 Clock-to-shift matching underspecified — **partial**: clock-in outside a Shift and the Employee-and-Creator match were already decided. Accepted the gap of choosing between several matching occurrences: the earliest start wins, then the lowest id (Clock rules), with a test.
- B7 Effect of edits on open or past Clock events — **partial**: cancel and the recomputed link were already decided. Accepted that PATCH never rewrites Clock events, now stated in the endpoint table.
- B8 ADR-0012 schema validation — **partial**, same as D2.
- B9 Recorded earnings source unnamed — **reject**: the spec names `per_employee_revenue_with_attribution` (`service/stats.py:49`) and the join columns, and leaves attribution rules to Phase 4.
- B10 Timezone of week navigation and rollup bounds — **partial**: the calendar was already the browser timezone. Accepted that the Timesheet range is the viewed browser week in UTC, with edge-crossing items clipped.
- B11 Avatar menu placement, card loading and error states — **accept**: `AvatarMenu` now names `components/shell/TopBar.tsx`, because `components/chat/AvatarMenu.tsx` is the Fan menu (its header comment). The cards get loading and error-with-Retry lines.
- B12 Test at the Relay HTTP seam, with a separate migration check — **reject** as a finding: the Testing Decisions already do both.
- B13 Falsifiers (ambiguous multi-agency chatter, no traffic, other repeat kinds, unjoinable earnings) — **reject** as findings: each is already a flagged ASSUMPTION or a named test (story 26, the sweep cases, the Timesheet earnings case).

Draft call (spec shown):
- D1 `GET /me` across every Agency breaks the Agency boundary — **partial**: a single `time_tracking` object merged across Agencies was wrong, and is now per account. The union stays, limited to the caller's own Mirror Employee rows. It moves no Agency's data to another Agency, so ADR-0011 is not touched. Flagged as an ASSUMPTION with its overturn (a required `account_id`), and tested.
- D2 ADR-0012 write validation missing — **partial**: the plan assigns server-side blob validation to Phase 4 (plan, Phase 4 › Work). Phase 2 states this and reads leniently, which is ADR-0012's "applied as stored".
- D3 An assigned Creator can be unclockable — **accept**: `chatters.py:214-229` applies per-owner allowlists, so a restricted chatter could be assigned a Creator it cannot clock. Assignment now refuses such pairs with 422. The old rung-4 ASSUMPTION is replaced, and the case is tested.
- D4 Behaviours with no named test — **accept**: added auto-attach and tie-break, the clock audit rows, the reminder's "Clock in" action and the owner card's text and link.
- D5 Acceptance passes with a broken route — **accept**: added `grep -q 'ShiftSchedule'` on the page and a route-level `app/employees/shifts/page.test.tsx` (precedent: `app/app/messages-pro/page.render.test.tsx`).
- D6 `docs/infloww-parity-matrix.md` is absent — **reject**: Phase 0 creates it (plan, Phase 0 › Work item 3), and Phase 0 is a listed dependency. Its absence before Phase 0 lands is expected.

### Six hats

Six-hats report, 2026-10-16 (`.scratch/infloww-parity-next-steps/review/six-hats.md`), reconciled as the Adversary brief does.

- Black (phase-01/02), `agency_context(request)` versus Phase 1's `agency_context(*, account_id=None)`: **accept**. Rewritten to Phase 1's form in Reuses, the router's first Interfaces bullet and Depends on. Every handler calls it inline with the request's `account_id` where it has one.
- Black (phase-02/04), Phase 4 applies Data scope to the Timesheet and "clocked-in now", which this spec makes owner and Master only: **accept**. This spec's side stands: both stay owner and Master only, 403 for a chatter. Phase 4 drops Data scope on them, so its scope code is not unreachable. Rung 4: the least exposure, and opening later is additive. Rung 5: the plan never asks for Data scope on the Timesheet. The `ClockedInCard` ASSUMPTION now says so and covers the Timesheet too.
- Yellow (reversible migration with `init_db()` catch-up, lazy auto clock-out writing the deadline): **accept**, no change.
