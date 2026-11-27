# Phase 4 — Leak tracker: bell, purge, public enablement

**Objective.** An Agency owner gets one dated `leak_daily` row in the existing agency bell for each UTC day with Leak news, a deleted Leak watch can be undone for 30 days before Phase 1's purge removes it (backups roll off 30 days later), an offboarded Tracker tenant ends the same way, Tracker keys are replaced and revoked under a stable Tracker tenant, and every Deployment ships the Leak tracker in the state the owner chose: AE on, app.inflowwww.com off until the owner flips it, self-hosted opt-in, the demo on the Demo tracker, Twin off.

## Problem Statement
After Phases 1–3 the Leak tracker page shows each Creator's Leaks, but an Agency owner only learns about a new or returning Leak by opening the page. The bell they already watch says nothing. In cell mode the bell feed cannot be routed at all: the Front door's Control-cell allowlist names `/admin/notifications`, a path no Relay route serves, while the bell calls `/admin/agency-notifications`. Without a Cell or account hint, `relay.ts` refuses that call. Phase 1 purges a deleted watch 30 days after the request but never revives a deleted `watch_id`, so the plan's 30-day undo has no path. Nothing ends an offboarded Tracker tenant. Nothing keeps a backup from holding purged data for good. The consent attestation promises both. The Removal service owner can issue a second key (Phase 1) but cannot revoke the old one. Public replay carries the tracker code to app.inflowwww.com, self-hosted installs, the demo and Twin. No step proves it arrives off, and no step lets the owner turn it on where they want.

## Solution
A Relay job runs hourly on the single Relay. For each gated Agency it asks the Tracker API for the last three completed UTC days. It files one `leak_daily` row per day with news, for example "Leaks on 27 Nov: 3 new (2 creators) · 1 came back · 2 gone after notice — as of 06:00 UTC". A day with a failed or capped Daily scan files nothing. The row is deduped by `leak_daily:<date>` and links to `/creators/leaks?day=<date>`, where the Today strip shows that day's counts. The bell lists the row like any other, under its own kind switch. Both the row and the switch disappear while the tracker is gated off, and bulk read and dismiss leave hidden rows alone. The Front door allowlist names the real feed path, so the bell routes to the Control cell; that fix is its own slice with no tracker dependency. The Leak tracker itself stays off in cell mode until a spec routes `/admin/leaks`.

In the Removal service, Phase 1's daily purge job gains two things:
- It removes each offboarded Tracker tenant's watches, through Phase 1's per-watch purge, and its keys 30 days after offboarding, keeping only tenant-level totals.
- It deletes tracker backup files older than 30 days.

Notices are untouched: Phase 3 keeps only linked sources' Notices, by source client, as the owner's case records, and Phase 1's purge drops `client_watches` through its `WATCH_TABLES` hook.

Re-enrolling the same Creator within the window adopts the deleted watch's history under the new `watch_id`. The old id stays deleted, so a late DELETE retry still names a watch that no longer matters (ADR-0071).

The owner replaces a key by issuing a new one (Phase 1's `key issue`) and revoking the old one when they choose, and offboards tenants and reinstates them. All of this runs from the Removal service's CLI, and the service enforces it on reads, dispatch and scheduling. The CRM:
- shows "Key no longer valid" for any refused key (Phase 1's state, now also on the bell job);
- adds the one rebind rule (moved from Phase 1): another tenant's key rebinds an Agency with no watch and no tombstone; a replacement key names the same tenant, so it always passes;
- keeps Phase 1's 410 drop for a deleted or purged watch.

This Phase also takes the pieces Fable round 3 moved out of Phase 1: the rename rule with `identity_note`, the kill switch pushing paused, orphan-watch logging, and the Demo tracker that the demo, and Phases 2 and 3's demo sections, run on.

The README tells self-hosters how to opt in, without the brand or a hostname. The public-sync skill gains the owner-flip runbook. The deploy-all selftest plants prove the brand, domain, private repo names and key prefix rules catch. deploy-all's `live.py` checks Twin's gate after every run and goes red if it is on.

## User Stories
1. As an Agency owner, I want one bell row per UTC day that had Leak news, so that I learn about new and returning Leaks without opening the page.
2. As an Agency owner, I want the row to read "Leaks on <d MMM>: N new (M creators) · K came back · G gone after notice — as of HH:MM UTC" with zero parts left out, so that it says only what happened.
3. As an Agency owner, I want no row on a day with no news, so that the bell stays quiet on clean days.
4. As an Agency owner, I want "new" to count only confirmed Leaks first seen that UTC day and never a watch's "Found on first scan" Leaks, so that enrolling a Creator does not flood the bell.
5. As an Agency owner, I want "gone after notice" to count a Leak only when its first dead probe came after its first Notice, and only for Creators the removal service works for, so that the row agrees with the Removal track on the page.
6. As an Agency owner, I want "gone, no notice on file", Notice-sent and Delisted events left out of the row, so that the row carries only news I act on.
7. As an Agency owner, I want clicking the row to open `/creators/leaks?day=<date>` with the Today strip showing that date's counts, so that I see the numbers the row counted.
8. As an Agency owner, I want the row to be a snapshot "as of" its filing time, so that a Leak found later shows on the page under its own `first_seen_at` day and never rewrites a row I already read.
9. As an Agency owner, I want a day whose Daily scans had not all ended by 00:30 UTC the next day filed then with "(partial check)", so that a slow day still reaches me and says so.
10. As an Agency owner, I want days the Relay missed while down to be filed when it comes back, at most 3 days back, so that downtime never drops news.
11. As an Agency owner, I want a Relay restart never to file a day twice, so that dedupe on `leak_daily:<date>` holds across restarts.
12. As an Agency owner, I want no bell row for a day on which a Daily scan failed or was capped, even when that day found Leaks, so that failures stay on the page (Phase 2's lane coverage) instead of a half-true row in the bell.
13. As the Removal service owner, I want a day on which Daily scans failed outright written as one line to the service log by the daily pass, so that a broken scanner reaches me and not the Agencies.
14. As an Agency owner, I want a "Daily leak news" switch among my bell kind switches, on by default, so that I can turn the row off like any other kind.
15. As an Agency owner whose tracker is gated off, I want no `leak_daily` rows in my feed, unread count or live badge, no switch for it, and no read-all or clear-all touching those rows, so that a disabled feature leaves no trace in the bell.
16. As an Agency owner who turns the tracker back on, I want my earlier `leak_daily` rows visible again until the normal 90-day feed expiry, so that switching off hid them rather than deleted them.
17. As a Team Leader or chatter, I want no `leak_daily` row in my bell, so that the bell stays owner-only as every agency notification is.
18. As an Agency owner in cell mode, I want the bell feed and its read and dismiss calls routed to the Control cell, so that the bell works once the Agency runs on Cells. (An independent slice: the Front door fix needs no tracker code.)
19. As an operator, I want the Leak tracker off while cell mode is on, so that no bell row links to a page the Front door cannot route.
20. As an Agency owner whose Tracker key was revoked, I want the page and my key card to say "Key no longer valid" and the bell job to skip my Agency, so that I know to ask for a new key and nothing fails silently.
21. As an Agency owner, I want a replacement key the Removal service issued for my Tracker tenant to keep every Leak watch and its history once I paste it, so that a key change is invisible apart from the paste.
22. Met by Phase 1 (story 11): a foreign tenant's key is refused; story 23 narrows that to Agencies with a watch or a tombstone.
23. (moved from Phase 1, story 11) As an Agency owner whose Agency has no Leak watch and no tombstone, I want a key of another Tracker tenant stored and the binding moved to it, and refused with 422 while any watch or tombstone exists, so that an empty Agency can switch accounts and a key swap never strands a watch or a pending delete.
24. Dropped: Phase 1 binds on the first accepted key, so no Agency is unbound when this Phase lands.
25. As the Removal service owner, I want to replace a key by running Phase 1's `tracker key issue <tenant>` and later `tracker key revoke <old prefix>`, so that I choose the overlap, routinely or at once after a leak, with no extra command.
26. As the Removal service owner, I want `tracker key revoke <key prefix>` to refuse that key on every read at once, so that one bad key ends without touching the tenant.
27. As the Removal service owner, I want a tenant with no valid key to get no new Daily scans, its queued-but-unstarted work dropped at dispatch, and its running work left to finish, so that revocation is enforced on reads, worker dispatch and scheduling.
28. As the Removal service owner, I want the Ingest key to keep working on Notice ingest and stay refused on every tenant route, so that key enforcement does not break Phase 3's feed.
29. As the Removal service owner, I want `tracker tenant offboard <tenant>` to revoke every key, pause every watch and start a 30-day purge clock, so that offboarding is one command.
30. As the Removal service owner, I want `tracker tenant reinstate <tenant>` before the 30 days are up to clear the clock, issue a new key and resume every watch the CRM has not paused, so that an offboarding mistake is reversible.
31. As the Removal service owner, I want a reinstate at or after day 30, whether or not the purge has run yet, to purge first and give the same Tracker tenant back with no watches, so that the deadline can't be dodged and the tenant id stays stable for the CRM binding.
32. As a Creator whose Agency deleted their Leak watch, I want Phase 1's purge to still remove everything keyed by the old `watch_id` after an adoption moved part of it, so that the consent attestation's promise holds.
33. Met by Phase 1: the clock starts at the clamped `requested_at` of the delete click.
34. As the Removal service owner, I want the tenant purge to leave Notices alone, as Phase 1's watch purge does, so that my case records stay and the owner's daily ledger replay never re-inserts something the purge deleted.
35. As the Removal service owner, I want an offboarded tenant's watches purged 30 days after offboarding and its keys deleted, with only tenant-level usage and spend totals and no handles kept, so that offboarding ends in the same state as a delete.
36. As the Removal service owner, I want the purge job to delete tracker backup files older than 30 days, and a re-run after any backup restore to purge again, so that purged data leaves the backups within 30 days and a restore can't bring it back for good.
37. As the Removal service owner, I want the tenant purge to reuse Phase 1's per-watch purge, so it runs in batches, skips a row that fails and retries it next run, and never touches Quick scan tables, so that one bad row never blocks it and free-scan retention stays separate.
38. As an Agency owner who re-enables a Creator within 30 days of deleting their Leak watch, I want the earlier history adopted by the new watch and a one-time note "Earlier history restored (deleted <d MMM>)", so that a delete made by mistake can be undone by turning tracking back on.
39. As an Agency owner who re-enables a Creator while the old delete has not reached the service yet, I want the new watch to wait for that delete and then adopt the history, with no error shown, so that an outage never loses the undo or the delete.
40. Met by Phase 1: a deleted or purged watch answers 410 `watch_deleted`, and the CRM drops the row with no tombstone, so the Creator shows as not tracked.
41. As the owner, I want app.inflowwww.com to run the tracker only after I set its URL and switch in the host's env and recreate the relay, following a runbook, so that public goes on by my flip and no timer.
42. Met by Phase 1: the relay's compose block names both tracker env vars with empty defaults.
43. As a self-hosting operator, I want a README section that says the tracker is off and how to opt in with the URL and key the removal service gives me, and what data that sends, so that I can enable it knowingly, without the brand or a hostname in the repo.
44. As the owner, I want the deploy-all selftest to plant the brand, its domain, each private leak-stack repo name and path, and a Tracker-key-shaped string, and see each CAUGHT under the public profile, so that a public-sync can't leak them.
45. Parked until after the pilot (Fable round 3): the four-target tracker report. Ticket 03 asks only that Twin stay off, which story 46 covers.
46. As the owner, I want deploy-all's `live.py` to check Twin's Deployment gate on every run, including when Twin needed no deploy, and go red when it reads on, so that Twin stays off until I sign off its integration and Removal offer.
47. As the owner, I want the demo's Daily-news row to come from the Demo tracker's fixtures, with `demo/tests/test_fake_tracker.py` running the bell job and seeing no outbound request, so that the demo shows the bell row without calling the real service.
48. As a developer, I want the Demo tracker to answer every Tracker API shape Phases 1–4 define, including Phase 2's lanes and Today strip and Phase 3's Notices and Service status, and this Phase's daily, restore, 410 and key-refusal shapes, so that one fake serves the demo and every CRM test.
49. (moved from Phase 1, story 25) As the owner, I want a live rename on OnlyFans to make the old handle alias #1 (dropping the newest manual alias when 5 are saved, with a note kept in `identity_note` and shown once in the form), and a failed refresh to keep the last good copy, so that a rename never loses coverage.
50. (moved from Phase 1, story 29) As the owner, I want a Deployment switch that reads off while `LEAK_TRACKER_URL` is set to push paused, and nothing else, to every Leak watch the service already holds, so that a kill switch also stops spend without sending or creating anything.
51. (moved from Phase 1, story 33) As the owner, I want the daily sync to report, never delete, any watch the service lists that the CRM has neither as a row nor as a tombstone, so that a row lost outside these paths is seen without a restored CRM snapshot deleting watches that still belong to the Agency.
52. (moved from Phase 1, story 60) As the owner, I want the demo to run the Leak tracker on fixtures from a Demo tracker with every trigger state seeded, its config writes locked, and a test proving no tracker call leaves the box, so that the demo never contacts the Removal service.

## Implementation Decisions
- **Owns (this repo, the CRM).**
  - `notifications_api`: one visibility predicate for the `leak_daily` kind, used by the list, the unread count (so every push) and every read and dismiss path, plus `hidden_kinds` on the list response.
  - A new Relay module `leak_daily`: the hourly job and the row builder.
  - `server` startup: the job, started under the Cell job guard.
  - The Cell scope table: an agency-scope job row `leak-daily`.
  - `settings_schema`: `leak_daily` added to `NOTIFICATION_KINDS`.
  - `AgencyNotifications`: the label, plus a kind switch hidden when the feed lists `leak_daily` in `hidden_kinds`.
  - The two Front door allowlist mirrors, `cellRoute` and `deploy/fleet/fleet.py`, plus the relay call-site ledger entries they reclassify: an independent slice, its own ticket and PR.
  - Phase 1's Deployment gate: off while cell mode is on.
  - The Leak tracker page and a Relay route `GET /admin/leaks/daily?day=`: `?day=` on Phase 2's Today strip.
  - Phase 1's Tracker API client and watch sync: `restored_from` handling, the `account_taken` wait, and the pieces moved from Phase 1: the rename rule, the kill switch pushing paused, and orphan-watch logging. Key refusal, the 410 drop and `requested_at` are Phase 1's.
  - Phase 1's `PUT /admin/leaks/key`: the one rebind rule (moved from Phase 1).
  - `leak_watch.identity_note` (moved from Phase 1): an additive nullable column through the boot's additive-column pass (`service/db/engine.py:255-280`), as Phase 3's `offer_snoozed_until` is.
  - The Demo tracker (moved from Phase 1): new `demo/fake_tracker`, serving the Tracker API from fixtures through an in-process transport swapped into `leak_tracker`'s client, and its install in `demo/relay` with `LEAK_TRACKER_URL` a `.invalid` placeholder. Seed rows set the flag and a fake key for the demo Agency and cover every pill, Came back, Found on first scan, Not checked yet, Paused, key-invalid, and the Phase 2 and 3 shapes those Phases' demo sections show. New `demo/tests/test_fake_tracker.py` takes over from Phase 1's `demo/tests/test_leak_tracker_off.py`.
  - `README` (self-host opt-in).
  - The public-sync skill (the owner-flip runbook) and deploy-all (selftest plants, plus the Twin check in `live.py`).
- **Owns (the Removal service repo).**
  - The Tracker API's `GET /v1/daily`, plus additions to `DELETE /v1/watches/{id}`, Phase 1's `PUT /v1/watches/{watch_id}`, `GET /v1/me` and the shared 401 shape.
  - Key enforcement on Phase 1's `tenant_keys`.
  - The owner CLI subcommands `tracker key revoke` and `tracker tenant offboard|reinstate`.
  - The tenant purge and backup roll-off, added to Phase 1's `tracker_purge`.
  - The failed-day log line.
- **Owns (the Laptop leak tools).** None.
- **Interfaces (CRM).**
  - `leak_daily.tick(now)` files and returns the number of rows filed. It is started by `server` through the existing `_periodic` helper, hourly, `first_after_s` short, only when `not cells or cell_mode.runs_job("leak-daily")` (the clock-in-missed precedent). While cell mode is on, the gate keeps it filing nothing.
  - `leak_daily.row_text(day) -> str | None`. It returns None when nothing counted is non-zero, or when the day is failed or capped. It is pure and table-tested.
  - `leak_tracker.tracker_on(agency_id) -> bool` is the feed's cheap gate predicate: Phase 1's Deployment gate on (which now also needs cell mode off), the Agency's `leak_tracker` flag on (read for that Agency, never through the `all` merge), and a Tracker key stored. It never calls the network. The name belongs to Phase 1's module if it already has one.
  - `notifications_api` builds one predicate, "kind is not `leak_daily` or `tracker_on`", and applies it in `list_notifications`, `_unread`, read-all, dismiss-all (with or without `up_to_id`), and single read and dismiss, which answer 404 for a hidden row. The list response gains `hidden_kinds: ["leak_daily"]` while it is false.
  - `AgencyKindSwitches` omits every kind in the feed's `hidden_kinds`, so the switch and the rows share one gate.
  - `GET /admin/leaks/daily?day=YYYY-MM-DD` (Phase 1's gates and role) returns that one day from `/v1/daily`. The Today strip shows it as "On <d MMM>: …" in place of today's sums when `?day=` is set; the roster is unchanged.
- **Interfaces (Removal service).**
  - Phase 1's `tracker_purge.run(now)` result gains `tenants` and `backups`. It stays daily and idempotent; `tracker_cli purge [--dry-run]` covers both.
  - Every tenant route under `/v1/` resolves its key to a tenant through Phase 1's `tenant_keys`. An unknown or revoked key, or an offboarded tenant, gets 401. `POST /v1/notices/ingest` keeps Phase 3's Ingest-key check and is the one exception; the Ingest key stays refused on every tenant route.
  - The scheduler skips tenants with no valid key, and worker dispatch drops queued work for them. Work already running finishes and writes.
- **Schema (CRM).**
  - `leak_tracker_tenant` and `leak_watch_tombstone` are Phase 1's, unchanged.
  - `leak_watch.identity_note text null` (moved from Phase 1) holds a one-time note for the identity form, the rename note or the restore note, shown once and cleared by the next save.
  - `agency_notifications` gets no change; only a new `kind` value.
  - `preferences.notifications.leak_daily` is a bool, default on.
- **Schema (Removal service).**
  - Phase 1's `tenant_keys` gains `prefix` (shown in the CLI).
  - Phase 1's `tenants` gains `offboarded_at` (nullable).
  - Phase 1's `watches` gains `adopted_by` (nullable watch_id) beside `deleted_at` and `purge_after`.
  - Usage and spend counters stay keyed by tenant only (Phase 2's `tracker_usage`).
  - Tracker tables stay apart from the Quick scan tables.
- **Contracts (Tracker API, header-keyed).**
  - `GET /v1/me` → `{tenant_id, brand?, contact_url?, …}`. `tenant_id` is already required by Phase 1.
  - `GET /v1/daily?from=YYYY-MM-DD&to=YYYY-MM-DD` (at most 7 days) → `{as_of, days: [{date, complete, failed, capped, new_leaks, new_creators, came_back, gone_after_notice}]}`.
    - `complete` means every `daily_scans` row scheduled for that date has ended, `ok`, Phase 2's `partial`, or `failed`.
    - `failed` counts that date's Daily scans whose outcome is `failed`.
    - `capped` is true when any of the tenant's watches has a `lane_day` row for that date (Phase 2's watch-scoped `scan_partial`) whose `reason` is `cap_global`, `cap_tenant_month` or `judge_cap`. Other reasons do not set it.
    - `new_leaks` counts confirmed Leaks whose `first_seen_at` falls on that date, excluding Leaks whose `seen` event has `first_scan` true. `new_creators` is the distinct watches among them.
    - `came_back` counts origin-status changes from gone to live on that date.
    - `gone_after_notice` counts Leaks whose gone status-change event falls on that date and whose `dead_since` comes after their first Notice time, only for watches whose Service status is `active` or `former`. It is Phase 3's Removal track rule, dated by the gone event. Each Leak counts once.
    - Deleted watches never count.
  - `DELETE /v1/watches/{watch_id}?requested_at=<ISO>` is Phase 1's, with its one clamp rule; this Phase adds nothing to it.
  - Phase 1's `PUT /v1/watches/{watch_id}`, when it would create a watch for a (tenant, account_id) that has a deleted watch whose `purge_after` is still ahead, adopts it. In one transaction it moves that watch's Leaks, Leak event log, Probe state, Pending hits, Daily scans, `lane_state`, `lane_day` and `load_reservation` rows to the new `watch_id`, sets the old watch's `adopted_by`, and answers `restored_from: <the old delete request ISO>`. Otherwise `restored_from: null`. The old id stays deleted: Phase 1's 410 still answers a PUT on it, and a DELETE on it is a 204 no-op. Phase 2's admission rules treat an adoption as a create, so the new watch gets fresh `weekly_slot` and `plan_loads`, and the old row's `carry_json` is not carried.
  - A PUT or read of a deleted or purged watch is Phase 1's 410 `watch_deleted`; this Phase adds no status for it.
  - Every refused key → 401 `{error: "key_invalid"}`, one shape for unknown, revoked and offboarded, so nothing about other tenants leaks.
- **Contracts (bell row).**
  - kind `leak_daily`, `account_id` null.
  - `dedupe_key` is `leak_daily:<YYYY-MM-DD>`.
  - `data` is `{href: "/creators/leaks?day=<date>", date, new_leaks, new_creators, came_back, gone_after_notice, partial, as_of}`. That is counts and the internal link only, with no names or URLs. The existing pane already links rows through `data.href`.
- **Job rule.**
  - Each hour, for each Agency that passes `tracker_on` and has the `leak_daily` preference on, the job takes the dates from today−3 to today−1 that have no `leak_daily:<date>` row, in one `/v1/daily` call.
  - It files a date when `complete` is true, or when the time is at or past 00:30 UTC on the day after the date. A date that was not complete is filed with " (partial check)".
  - It files nothing when `failed` > 0, when `capped` is true, or when `row_text` is None.
  - A 401 skips the Agency for the tick. A 5xx or timeout skips the Agency and logs. No row is ever written from a failed call.
  - Clean, failed and capped days are re-asked hourly until they leave the 3-day window. That costs 1 call per Agency per hour.
- **Failed-day log (Removal service).** The daily pass logs one warning line, `"<n> daily scans failed on <date>"`, for yesterday when any Daily scan failed outright. The line has no handles. No table, no env var, no sender.
- **Tenant binding (CRM).** This Phase adds the one rebind rule to Phase 1's `PUT /key` (moved from Phase 1): a key whose `/v1/me` names another tenant is refused with 422 "Key belongs to another tracker account" while the Agency has any `leak_watch` or `leak_watch_tombstone` row; with neither, it is stored and the binding moves to the new tenant. A key from `key issue` for the same tenant names the same `tenant_id`, so a replacement always passes.
- **Watch sync additions (CRM, moved from Phase 1).**
  - Rename rule: on the sync's daily pass, an OnlyFans watch with a live session refreshes its identity from `me()`. A changed handle makes the old one alias #1, dropping the newest manual alias when 5 are saved, and sets `identity_note`; a failed refresh keeps the last good copy.
  - Kill switch: while `LEAK_TRACKER_URL` is set and the switch reads off, the sync sends paused only for rows with `synced_at` set, never a row that was never pushed, so it never creates a watch or sends a new identity.
  - Orphans: on the daily pass the sync lists `/v1/creators` per Agency and logs each unknown `watch_id` (count per Agency, no handles); it never tombstones one.
- **Key refusal (CRM).**
  - Any 401 from the Tracker API sets the Agency's tracker read state to "Key no longer valid". The page and the owner card show it. The key status stays masked.
  - The tombstone retry job keeps its normal cadence on 401, and succeeds once a valid key is saved.
- **Restore (CRM).**
  - The enable path is Phase 1's, unchanged: it mints a fresh `watch_id`, saves locally, and the watch sync pushes it.
  - When the push answers `restored_from`, the sync sets `identity_note` to "Earlier history restored (deleted <d MMM>)", shown once and cleared on the next save, as the rename note is (story 49, moved from Phase 1).
  - When the push answers 409 `account_taken` naming a `watch_id` that has a tombstone in this Agency, the sync leaves the row unsynced with no error. The tombstone job lands the DELETE first, and the next sync adopts.
- **Purged watch (CRM).** Phase 1's 410 drop covers it: a 410 `watch_deleted` deletes that Agency's `leak_watch` row and writes no tombstone, because the watch is already gone at the source.
- **Purge rule (Removal service).** The watch purge is Phase 1's (`purge_after`, `WATCH_TABLES`, `deleted_ids`). An adopted watch has only its own row left for it. For a tenant, when now ≥ `offboarded_at` + 30 days:
  - Each of its watches goes through Phase 1's per-watch purge, which also drops its `client_watches` row through the hook.
  - It touches no Notice: Phase 3 keeps only linked sources' Notices, by source client, as the owner's case records.
  - It deletes the tenant's keys and keeps the tenant row and `tracker_usage` totals.
  - `tracker tenant reinstate` before `offboarded_at` + 30 days clears the clock. At or after it, reinstate runs that tenant's purge first, then issues a key to the empty tenant.
  - Because the rule reads stored `purge_after` and `offboarded_at`, a run after any backup restore purges again.
- **Backup roll-off (Removal service).** The purge job deletes files in `TRACKER_BACKUP_DIR` older than 30 days. If the dir is unset, there is nothing to roll off. This Phase adds no backup.
- **Front door fix (independent slice).** It touches no tracker code and can ship before Phase 1.
  - In both `CONTROL_PATHS` mirrors, `/admin/notifications` and `/admin/notifications/*` become `/admin/agency-notifications` and `/admin/agency-notifications/*`.
  - The bell's four ledger entries in the relay call-site ledger now classify as routed.
  - The existing drift test keeps the two mirrors equal, and `cellRoute.test.ts` names the real paths so both lists can't be wrong together.
- **Per-target rollout.**
  - AE: on, from Phase 1.
  - app.inflowwww.com: the owner sets both env vars in the host's untracked env and recreates the relay. The public-sync skill holds that runbook. Keys go out per Agency on request, through Phase 1's owner issue CLI.
  - Self-hosted: README opt-in; keys only when the owner issues them.
  - Demo: the Demo tracker (moved from Phase 1), config locked.
  - Twin: off.
  - `live.py`, in deploy-all's after phase on every run, reads the gate inside Twin's relay and fails when it reads on, including when Twin needed no deploy. Other targets get no tracker check; the owner's flip is the authority there, and the four-target report is parked (Fable round 3).
- **Copy.** Every string in git is generic ("removal service"). The bell row names no brand.

## Testing Decisions
- **Seam 1 (CRM, the main one): the Relay's HTTP surface with the Demo tracker as the Tracker API.** One test file drives `leak_daily.tick(now)` at fixed clocks and asserts through `GET /admin/agency-notifications` as the owner. The fixtures cover:
  - a complete day with news;
  - a clean day;
  - a failed day and a capped day, each with positive counts, filing nothing;
  - an incomplete day before and after 00:30 UTC;
  - three missed days;
  - a restart, which runs tick twice;
  - a 401 and a 5xx;
  - the `leak_daily` preference off: no Tracker call;
  - the tracker gated off: rows hidden from the list, unread and push, `hidden_kinds` set, a single dismiss answering 404, and dismiss-all with a newer visible row leaving the hidden row undismissed; then shown again after it turns back on;
  - cell mode on: the gate reads off and nothing files;
  - a chatter and a second Agency seeing nothing.

  The same seam drives `GET /admin/leaks/daily?day=`, the bell job skipping an Agency on 401, the watch sync's restore (`restored_from` sets `identity_note`; `account_taken` with a tombstone waits silently, then adopts after the DELETE lands). The moved pieces extend Phase 1's `test_leak_watch_sync` (the rename rule and its `identity_note` cleared by the next save, a failed refresh keeping the last copy, the kill switch pushing paused only for synced rows, an orphan logged and never tombstoned) and `test_leak_tracker_api` (another tenant's key refused while a watch or tombstone exists, and stored with the binding moved when neither does). A startup test asserts `server` registers the `leak-daily` periodic with cells off and not on a data cell. `leak_daily.row_text` gets a table test: zero parts dropped, the partial suffix, failed or capped gives None, all-zero gives None.
- **Seam 2 (CRM app): vitest on the existing `AgencyNotifications` test**, covering the label, the switch hidden by `hidden_kinds`, and a `leak_daily` row linking to its `href`. The leaks page test covers the Today strip under `?day=`. `cellRoute.test.ts` asserts `routeOf("/admin/agency-notifications?limit=30")`, `/admin/agency-notifications/read-all` and `/admin/agency-notifications/17/dismiss` are `control`, and the drift with `fleet.py` still holds. The relay call-site ledger test passes.
- **Seam 3 (Removal service): its HTTP Handler on a temp DB**, as its retention test does:
  - `/v1/daily` counts on a seeded event log, including `failed`, `capped`, and `gone_after_notice` with `dead_since` before and after the Notice and a non-client watch;
  - an offboarded tenant purged at 29 and 31 days through Phase 1's per-watch purge, with `lane_day`, `load_reservation` and `client_watches` rows gone and keys deleted;
  - Notices untouched by a tenant purge, and an ingest replay afterwards inserting nothing new;
  - backup files pruned;
  - Quick scan rows untouched;
  - adoption on PUT inside and outside the window, moving `lane_day` and `load_reservation` rows; after it, PUT on the old id 410 and DELETE on it 204 with the new watch intact;
  - a second `key issue` for the tenant keeping its watches, then `key revoke` of the old prefix;
  - revoke, with queued work for that tenant dropped at dispatch;
  - the Ingest key accepted on ingest and refused on a tenant route;
  - offboard, reinstate inside the window, at day 30 before the sweeper has run, and after the purge;
  - the scheduler skipping keyless tenants;
  - the failed-day log line, with no handle in it.
- **Seam 4 (deploy):**
  - The deploy-all selftest plants.
  - A unit test of `live.py`'s Twin check: on is red, off is green, also when Twin needed no deploy.
- **Seam 5 (demo):** `demo/tests/test_fake_tracker.py` (pytest, prior art `test_fake_llm.py`, `test_guards.py`), taking over from Phase 1's `test_leak_tracker_off.py`: it boots the demo relay with guards, calls every `/admin/leaks` GET and asserts the fixture answered, runs `leak_daily.tick` and asserts the fixture `leak_daily` row, asserts every `/admin/leaks` write is `routes.locked` and refused and that neither tracker job is registered, and sees `relay.refused["count"]` unchanged.
- **Prior art.** The agency-notifications test (filing, dedupe, owner-only, unread push), `cellRoute.test.ts` (mirror drift), the Removal service's retention test (batched purge on a real Handler), the deploy-all selftest plants, .

## Acceptance
```sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
for t in leak_daily leak_tracker_keys leak_tracker_restore leak_watch_sync leak_tracker_api agency_notifications; do nice -n 10 venv/bin/python service/tests/test_$t.py; done
(cd app && nice -n 10 pnpm exec vitest run components/AgencyNotifications.test.tsx lib/cellRoute.test.ts lib/relayCallSites.test.ts)
grep -q '"/admin/agency-notifications", "/admin/agency-notifications/\*"' app/lib/cellRoute.ts
grep -q '"/admin/agency-notifications", "/admin/agency-notifications/\*"' deploy/fleet/fleet.py
test -r app/lib/cellRoute.ts && test -r deploy/fleet/fleet.py
if grep -q '"/admin/notifications"' app/lib/cellRoute.ts deploy/fleet/fleet.py; then echo 'stale /admin/notifications in the allowlist'; exit 1; fi
nice -n 10 venv/bin/python -m pytest -q demo/tests/test_fake_tracker.py demo/tests/test_routes.py
nice -n 10 venv/bin/python .claude/skills/deploy-all/test_live_tracker.py
nice -n 10 scripts/run-tests.sh
: "${REMOVAL_REPO:?set to the Removal service repo checkout}"
(cd "$REMOVAL_REPO" && nice -n 10 python3 -m pytest -q app/tests/test_tracker_daily.py app/tests/test_tracker_purge.py app/tests/test_tracker_keys.py app/tests/test_tracker_restore.py && nice -n 10 python3 -m pytest -q app/tests && python3 tools/check.py)
# manual: SELFTEST_FORCE=1 deploy-all dry-run selftest on a fresh run: every new tracker plant CAUGHT under public, selftest rc=0
# manual: deploy-all dry run with Phases 1-4 on main: public gate clean (leak-check --tree HEAD), demo --check green incl. `demo/tests/test_fake_tracker.py`, twin.sh check green
# manual: verify-app on the seeded stack: owner bell shows a fixture leak_daily row, click lands on /creators/leaks?day=<date> with that day's strip; screenshots of both plus the feed response
# manual: after a real deploy-all: live.py's Twin check passes; the demo bell shows its fixture leak_daily row
# manual: owner flip on app.inflowwww.com per the public-sync runbook, then an Agency with an issued key sees its page on app.inflowwww.com
# manual: on AE, after one UTC day with news, the owner bell shows one leak_daily row linking to /creators/leaks?day=<date>
```
The `# manual` lines are not run by the block; the Phase is not accepted until each has its evidence.

## Depends on
- **Phase 1:**
  - the Tracker gates and their nav read, and the Deployment gate this Phase extends;
  - the `leak_tracker` key card and the owner issue CLI;
  - the Tracker tenant, `tenant_keys` and header auth, with `tenant_id` on `/v1/me`;
  - `leak_watch` with its CRM-minted `watch_id`, the watch sync and its 410 drop, `PUT /v1/watches/{watch_id}` with its `account_taken` and 410 `watch_deleted` answers, and the tombstone with its retry job, written by all four delete triggers (per-Creator delete, Creator Remove fan-out, Agency unlink, agency-user delete);
  - `leak_tracker_tenant` with its always-refuse key check (this Phase adds the rebind), the key-refusal state, and the compose pass-through of both tracker env vars;
  - the delete endpoint with its `requested_at` clamp, and `tracker_purge` with `WATCH_TABLES` and `deleted_ids`;
  - `dead_since` on Probe state and on the gone event;
  - `daily_scans` with outcomes `ok` and `failed`;
  - origin-status change events;
  - the demo's locked `/admin/leaks` write routes and `demo/tests/test_leak_tracker_off.py`;
  - the leak-check rules.
- **Phase 2:** confirmed Leaks (the Leak judge), `first_scan` on `seen`, `lane_day` with its cap reasons (the watch-scoped `scan_partial`), `daily_scans` outcome `partial`, `lane_state`, `load_reservation`, `tracker_usage`, the admission rules, and the Today strip that `?day=` scopes.
- **Phase 3:** the Ingest key and its route, the Removal track's `gone_after_notice` rule, Service status, `client_watches` on Phase 1's `WATCH_TABLES`, and Notice retention (linked sources only).

## Out of Scope
- Telegram, email, OS push or any other new channel: the CRM has no agency sender (ticket 07).
- A sidebar badge: `NavLink` has no badge field (ticket 07).
- A per-Creator mute: the Creator toggle already stops scans (ticket 07).
- The failed-day bell row: cut in Fable round 2. Failures show on the page (Phase 2) and in the service log.
- An ops webhook, `ops_alerts`, a `key rotate` command, key expiry and a 7-day overlap: cut in the plan review (six-hats 17). A log line and issue-then-revoke cover them.
- The watch purge, the `requested_at` clamp, the tenant binding and the compose pass-through: Phase 1.
- The CSV export: cut in Fable round 2.
- Pause reasons: cut in Fable round 2. The CRM sends one paused bit (Phase 1).
- The delete triggers themselves: Phase 1, per ADR-0071's delete half.
- Routing `/admin/leaks` in cell mode: the tracker is off there; left unowned, as in Phase 1.
- A list of a past day's Leaks under `?day=`: the strip shows counts only.
- Re-linking a restored Creator's Service status: Phase 3 makes the owner re-link it.
- Creating tracker backups: none exist today and the plan asks only for roll-off.
- Turning Twin on: needs the owner's sign-off on integration and Removal offer.
- Naming the brand in public copy: owner call, ADR-0069.
- A timer for the public flip: owner flip only (ticket 03).
- Measuring caps and cost: Phase 2's pilot.
- The four-target tracker report in `live.py`: parked until after the pilot (Fable round 3); ticket 03 asks only that Twin stay off.

## Further Notes
Evidence (rung 1):
- The Front door allowlist names `/admin/notifications` while the only notifications router serves `/admin/agency-notifications` (`grep -rn '/admin/notifications' service app/lib deploy`). The Cell scope table already marks the feed agency scope with "writes go to the control Cell".
- `routeOf` returns null for `/admin/leaks/*` and `/admin/settings/preferences` (adversary run of `app/lib/cellRoute.ts:34-42`), and Phase 1 leaves `/admin/leaks` Cell routing unowned.
- Bulk dismiss filters only by owner, kind not pinned and `up_to_id` (`service/notifications_api.py:415-442`), so a hidden kind needs the shared predicate.
- Phase 1's PUT answers 410 on a deleted id and the plan's undo starts at the delete request (ticket 10, lines 27 and 61).
- Phase 3 Notices live by source client and are replayed from the owner's full ledger daily, so a purge that deleted them would be undone by the next replay.
- The Removal service's deploy script backs up code, not the data volume, and the service has no alert sender (grep for alert, telegram and webhook senders).

ASSUMPTION: the `leak_daily` job runs only on the single Relay or the Control cell, guarded like clock-in-missed (rung 3). Overturned if agency notifications move to data cells.
ASSUMPTION: the Leak tracker is off while cell mode is on, because Phase 1 left `/admin/leaks` Cell routing unowned and a bell row must not link to an unroutable page (rung 4). Overturned when a spec routes `/admin/leaks` in cell mode; that spec's account-path patterns must include `leaks/watches` so Phase 3's snooze route routes by account (Phase 3 B11, six-hats 16).
ASSUMPTION: the feed's gate predicate checks key presence, not live key validity, so the bell never calls the network to render (rung 5). Overturned if revoked-key Agencies must lose their old rows at once.
ASSUMPTION: row text drops zero parts and states times in UTC, after the clock-in-missed text that names its zone (rung 3). Overturned by an owner copy call.
ASSUMPTION: `?day=` shows that date's counts in the Today strip from `/v1/daily`, with no Leak list query (rung 5). Overturned if the owner wants the day's Leaks listed; that adds a filter to the leaks read.
ASSUMPTION: a capped day is one with a cap-reason `lane_day` row on any watch, and a failed day one with any failed Daily scan; lane failures that only reduce coverage still file (rung 2 for "capped or failed day files nothing", rung 5 for the reading). Overturned if the owner wants news filed through a partly failed day.
ASSUMPTION: the job skips an Agency whose `leak_daily` preference is off, so turning it back on files only days still inside the 3-day window (rung 5). Overturned if muted days must be backfilled further.
ASSUMPTION: a key change is Phase 1's `key issue` then this Phase's `key revoke`, with no `key rotate` command and no `expires_at`; the overlap is however long the owner waits (rung 5; the cut itself is rung 2, coordinator on six-hats 17). Overturned if keys must expire on their own or an Agency must be told a date.
ASSUMPTION: a tenant whose keys are all revoked stops scanning but starts no purge clock until offboarded (rung 4). Overturned if revoking the last key should offboard.
ASSUMPTION: the 30-day undo is automatic adoption on re-enrol of the same (tenant, account), not a separate button or owner request (rung 5). Overturned if an agency must be able to start fresh inside the window; that adds a "start fresh" flag to the PUT.
ASSUMPTION: adoption moves the history to the CRM's new `watch_id` instead of reviving the old one, so Phase 1's never-revive rule and ADR-0071's late-retry guarantee hold unchanged (rung 3). Overturned by none known.
ASSUMPTION (evidence blocked): there is no tracker DB backup in the Removal service today, so roll-off is the purge job pruning `TRACKER_BACKUP_DIR` (rung 5). Only the deploy script and compose were read; a host cron or provider snapshot outside the repo would overturn it, and it must then keep at most 30 days. See needs-human in Review.
ASSUMPTION: a failed Daily-scan day is one warning line in the service log from the daily pass, with no dedupe table, so a restart may log it twice (rung 2 for log-only, coordinator on six-hats 17; rung 5 for no dedupe). Overturned if the owner wants a push channel; then the fleet's `ALERT_WEBHOOK_URL` pattern is the precedent.
ASSUMPTION: all four delete triggers and their tombstones are Phase 1's (ADR-0071's delete half plus the agency-user delete), while this Phase owns the selftest plants for Phase 1's leak-check rules (rung 5, the plan's "public-sync verification"). Overturned if Phase 1 ships the plants; then user story 44 is done.
ASSUMPTION: the tenant purge loops Phase 1's per-watch purge over the tenant's watches instead of its own delete (rung 5). Overturned if a tenant with many watches makes the daily pass too slow; then it batches by tenant.
ASSUMPTION: an adopted watch gets fresh `weekly_slot` and `plan_loads` from Phase 2's admission and drops the old `carry_json`, while its `lane_state`, `lane_day` and `load_reservation` rows move (rung 5). Overturned if a restored Creator must keep their weekly slot or carried queries.
ASSUMPTION: `live.py` checks only Twin's gate and goes red when it reads on; the four-target report is parked (rung 2 for the scope, ticket 03 says only "Twin: off"; rung 4 for the red). Overturned if the owner wants every target's tracker state reported, or when the owner signs off Twin.
ASSUMPTION: a deleted or purged watch answers Phase 1's 410 `watch_deleted` and the CRM drops the row with no tombstone; no 404 `watch_purged` exists (rung 5, one status). Overturned if the CRM must tell purged from deleted; then a field in the 410 body says which.
ASSUMPTION: the Demo tracker, moved here from Phase 1, runs in-process as both the demo's Tracker API and the CRM tests' fake, and serves Phase 2 and 3 shapes so their demo sections are built on it here (rung 3, one fake for demo and tests; rung 5 for the move). Overturned if Phase 2 or 3 demo work must ship before this Phase; then the Demo tracker moves to the earliest of them.
ASSUMPTION: the rebind for an empty Agency, moved from Phase 1, refuses a foreign tenant while the Agency has any Leak watch or tombstone and rebinds when it has neither (rung 4: a swap would otherwise drop deletes silently; an empty Agency has nothing to strand). Overturned if an Agency with watches must move tenants; then a migrate-tenant path carries its watches and pending tombstones over.
ASSUMPTION: a Deployment switch that reads off with the URL set sends paused, and only for watches the service already holds (moved from Phase 1; rung 4, stops spend and creates nothing). Overturned if "off" must mean zero egress; then the service keeps scanning until the owner pauses the tenant.
ASSUMPTION: the daily sync logs orphan watches the service lists but the CRM lacks and never deletes them (moved from Phase 1; rung 4, a restored CRM snapshot must not delete live watches). Overturned if orphans pile up; then an owner-confirmed cleanup is added.
ASSUMPTION: `identity_note` is one nullable text column, added here by the boot's additive-column pass, shown once and cleared by the next save, shared by the rename and restore notes (rung 3 for the column, Phase 3's `offer_snoozed_until`; rung 5 for one column). Overturned if both notes must show at once; then it becomes a list.

## Review
codex, 2026-11-27 (two calls: blind, then draft; `codex exec` read-only, high effort, both exit 0).

Blind call:
- B1 one visibility rule for list, unread, push, single and bulk read/dismiss — **accept**: one predicate in `notifications_api`, `hidden_kinds` on the list (Interfaces, stories 15, seam 1).
- B2 who polls and writes in cell mode, and the link target unroutable — **accept**: the tracker is off in cell mode (Phase 1's Deployment gate extended); the job guard stays (story 19, ASSUMPTION).
- B3 kind switch reads a separate route (`/admin/settings/preferences`, also unroutable in cell mode) — **partial**: the switch now follows the feed's `hidden_kinds`; the preferences route's cell routing is a generic pre-existing gap, not this Phase's.
- B4 daily contract: completeness, `as_of`, day attribution of gone-after-notice — **accept**: dated by the gone event, Phase 3's `dead_since` rule (Contracts).
- B4b re-enabling the preference backfills muted days? — **accept**: the job skips muted Agencies; re-enable files days still in the 3-day window (ASSUMPTION).
- B4c dated link must show the requested day — **accept**: `GET /admin/leaks/daily?day=` feeds the strip.
- B5 an outage-delayed DELETE must honour the original request time — **accept**: `requested_at` sets `purge_after`, clamped (story 33).
- B5b undo vs re-enrol, rotation vs offboarding — **accept**: adoption design (Restore, Contracts); rotation keeps the tenant, offboarding has its own clock.
- B5c Agency-user deletion cascades keys and `leak_watch` without tombstones, so the service keeps tracking — **partial, cross-Phase (binds Phase 1)**: ADR-0071 lists three triggers and user deletion is not one; Phase 1 should tombstone (or DELETE synchronously while the key still exists) before the user cascade. Here, offboarding the tenant is the backstop.
- B5d in-flight writes, replayed Notices and backup restores recreating purged data — **accept**: deleted watches run no scans, Notices are outside the purge, and the stored-clock rule re-purges after a restore (story 36).
- B6 the public path filter admits `plan/`, `ext/`, leak specs and ADR 0068 — **reject**: `plan/` and `ext/` are the review workspace's layout; in the repo the plan lives under `.scratch/`, stripped by `OPS_PATHS`, and the Removal service repo is not in this tree. The leak specs and ADRs are written public-safe by design, and the selftest plants (story 44) guard the brand.
- B6b the seed's Quick scan store is slug-addressed — **reject, cross-Phase (binds Phase 1)**: the seed is Phase 1's.
- B6c no rollout threshold from AE measurements — **reject**: ticket 03 makes the owner's flip the authority, with no timer or threshold.
- B7 seams: browser → Front door → Relay with a fake Tracker API — **partial**: seam 1 stays the Relay HTTP surface; a verify-app manual line with screenshots is added; `cellRoute.test.ts` now names the real bell paths so both lists can't be wrong together.
- B8 falsifier: an old DELETE touching the new watch — **accept**: by construction under adoption (new id), tested in seam 3.

Draft call:
- D1 `/v1/` key rule rejects Phase 3's Ingest key — **accept**: ingest is the one exception; Ingest key refused on tenant routes (story 28, seam 3).
- D2 restore names `POST /v1/watches` and revives an id Phase 1 retires, contradicting ADR-0071 and Phase 1's offline enrolment — **accept**: replaced by adoption on Phase 1's `PUT` with the CRM's fresh id; enable path unchanged; `restored_since`, the 200 DELETE body and the tombstone schema change are gone.
- D2b automatic revival is an added product decision — **reject**: ticket 10's amendment keeps "a 30-day undo" and names no other mechanism; automatic adoption stays flagged as an ASSUMPTION.
- D3 an undelivered DELETE plus re-enrol loses the delete — **accept**: `account_taken` with a tombstone waits silently; the DELETE lands, then adoption (story 39, seam 1).
- D4 `/v1/daily` cannot enforce the failed/capped-day rule — **accept**: `failed` and `capped` fields, the job files nothing on either (story 12, seam 1 and 3).
- D5 gone-after-notice compares the wrong timestamp — **accept**: Phase 3's `dead_since` rule, active/former only (story 5).
- D6 Notice purge needs a mapping Phase 3 already dropped, and replay would undo it — **accept**: the purge touches no Notice (story 34, seam 3 with a replay).
- D7 purge misses `daily_scans`, `lane_state`, `load_reservation`; reinstate at day 30 before the sweeper — **accept**: both (stories 31–32, seam 3).
- D8 bell link fails in cell mode and Phase 2 has no past-day read — **accept**: tracker off in cell mode, `GET /admin/leaks/daily?day=` (see B2, B4c).
- D9 clear-all can dismiss hidden rows; the switch uses a key-blind nav read — **accept**: see B1.
- D10 Agencies keyed before this Phase are unbound — **accept**: the bell job backfills the binding (story 24).
- D10b 7-day overlap and empty-Agency rebind are added policy — **reject**: the plan names rotation and revocation but not their timing; both stay flagged ASSUMPTIONs with what overturns them.
- D11 seams pass without startup registration, dispatch-after-revoke, webhook dedupe or the demo running the job — **accept**: startup test, dispatch case, `ops_alerts`, seam 5.
- D12 backup test proves fixture cleanup only; real backup locations never inventoried — **needs-human**: the spec says the repo holds no tracker DB backup, so `TRACKER_BACKUP_DIR` roll-off is the whole job; codex says host backups were never checked. Settled by the owner confirming the Removal service host has no cron, provider snapshot or volume backup of the tracker DB, or naming it with its retention (a host read, out of bounds for this run).
- D13 Acceptance exits green after failures; negative grep passes on unreadable files; story 42 promises four targets; the Twin step is skipped on "needs deploy: no" — **accept**: `set -euo pipefail`, `test -r` guards, manual lines declared blocking, `live.py` reports all four on every run (stories 45–46).

Superseded in the plan review (below): D10's backfill (story 24 dropped), D10b's 7-day overlap (issue then revoke), D11's `ops_alerts` and webhook (log line), B5's clamp and D13's compose part (Phase 1's now).

Cross-Phase lines other specs bind to this Phase (applied in the plan review, 2026-11-27):
- cross-Phase from P1 (`leak_tracker_tenant` and the tenant check ship in Phase 1) — **accept**: Schema (CRM) and Tenant binding refer to Phase 1; no re-creation, no backfill.
- cross-Phase from P1 (`DELETE ?requested_at=` is Phase 1's) — **accept**: Contracts refer to Phase 1's clamp; story 33 met there.
- cross-Phase from P1 (the tombstone already carries `agency_user_id`, `account_id`, `tenant_id`) — **accept**: Schema (CRM) says unchanged.
- cross-Phase from P1 (restore must match (tenant, account_id) on a PUT with a new id) — **accept, already applied**: D2's adoption on `PUT`.
- cross-Phase from P1 (purge within 30 days of the first AE delete) — **accept, moot**: the watch purge is Phase 1's (six-hats 11).
- cross-Phase from P2 (`complete` and partial-day reads come from `lane_day` and `daily_scans.outcome = partial`) — **accept**: Contracts `complete` and `capped`.
- cross-Phase from P3 (the purge deletes `client_watches` after reading status; retention of ignored and withheld Notices) — **partial**: `client_watches` goes through Phase 1's `WATCH_TABLES` hook with no status read, because Phase 3 now keeps Notices by linked source; retention is Phase 3's own (withheld and ignored events are never kept).
Cross-Phase counts: 6 accept (1 already applied, 1 moot), 1 partial.

### Six hats
One six-hats pass over the four specs, 2026-11-27. Bullets touching this Phase:
- 1 (stop re-creating `leak_tracker_tenant`, drop the backfill, one rebind rule) — **accept**: Schema (CRM), Job rule, Tenant binding and stories 22–24 refer to Phase 1's rule (422); the 409 variant is gone.
- 2 (stale Problem Statement; DELETE `requested_at` and compose ownership) — **accept**: Problem Statement rewritten; Owns, Contracts and story 42 point to Phase 1 and the compose and clamp ASSUMPTIONs are gone; one clamp rule, Phase 1's.
- 3 (`identity_note` has no column) — **accept**: Phase 1's `leak_watch.identity_note`; Schema and Depends on updated.
- 4 (`first_run` → `seen.first_scan`) — **accept**: Contracts `new_leaks`, Depends on.
- 5 (`capped` reads `lane_day.reason`; `complete` accepts `partial`) — **accept**: Contracts; ADR-0070 and CONTEXT amended in the same pass.
- 6 (`client_watches` at delete vs purge) — **accept**: Solution and Purge rule drop it through Phase 1's hook.
- 7 (who owns "Notices for non-clients are not kept") — **accept**: Phase 3 owns it; this Phase's purges touch no Notice (also set-level, plan review).
- 8 (adoption and purge lists; `weekly_slot`, `plan_loads`, `carry_json`) — **accept**: adoption moves `lane_day` and `load_reservation`; slot and loads set afresh by admission, carry dropped (ASSUMPTION); `deleted_ids` is Phase 1's purge.
- 10 (`dead_since` in Phase 1) — **accept**: Depends on.
- 14 (`! grep` fails open; `cd` and `nice -n 10`) — **accept**: Acceptance.
- 17 (cut unasked work) — **partial**: the Front door fix stays here as its own independent slice (Owns, story 18); the webhook becomes a log line; the 7-day overlap and `key rotate` go (issue then revoke, rung 5); the four-target deploy-all report stays report-only with Twin red, by coordinator decision, instead of a Twin-only check.
Counts: 10 accept, 1 partial, 0 reject. Bullet 20 is set-level (plan review, Needs the human).

### Fable round 3 (2026-11-27)
- C3 (restore note says "as Phase 2's note is") — **accept**: it reads "as the rename note is (story 49, moved from Phase 1)", and `identity_note` is now this Phase's additive column (Owns, Schema), on the house's additive-column pass (`service/db/engine.py:255-280`), as Phase 3's `offer_snoozed_until` is.
- C4 (this Phase's 404 `watch_purged` contradicts Phase 1's 410) — **accept**: Phase 1's 410 `watch_deleted` is the one status (Contracts, Purged watch); story 40 is met by Phase 1; the 404 ASSUMPTION is replaced; Phase 1 keeps `deleted_ids` while the tenant row exists, so a reinstated tenant's sync cannot re-create a purged watch.
- Sizing (move pieces out of Phase 1) — **accept**: stories 49–52 and 23 carry the rename rule, the kill switch pushing paused, orphan logging, the Demo tracker and the rebind; Owns, Tenant binding, Watch sync additions, Seams 1 and 5, Acceptance (`leak_watch_sync`, `leak_tracker_api`, `demo/tests/test_fake_tracker.py`) and the copied ASSUMPTIONs follow.
- Cut 1 (tenant offboard and reinstate, adoption-restore) — **reject**: ticket 10 states the tenant offboard with a 30-day purge and reinstatement by a new key, and the 30-day undo; the plan's Phase 4 names the purge jobs "per 10".
- Cut 2 (deploy-all four-target report) — **accept**: ticket 03 says only "Twin: off", so `live.py` checks Twin's gate and goes red when it is on (story 45 parked, story 46, Per-target, Seam 4, manual lines).
- Cut 6 (`?day=` route) — **reject**: ticket 07 links the row to `/creators/leaks?day=<date>`; it stays counts-only.
- C1, C2, cuts 3–5 — not this Phase's.
