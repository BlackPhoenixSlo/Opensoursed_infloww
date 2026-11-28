# Leak tracker — weekly cadence with manual refresh, and blurred previews

**Objective.** A connected Creator is scanned once on connect, then once a week on its Weekly slot, and again whenever an Owner or Admin presses "Refresh now" (at most once a day per Creator). The page's day view becomes a week view. Google image and video previews ship on by default, blurred until the viewer clicks a tile.

Amends Phase 2 (`docs/spec/phase-02-leak-tracker-discovery-and-budget.md`: daily lanes, Today strip, previews) and Phase 1's daily pass. Owner decisions 2026-11-28 (rung 2), recorded in `docs/spec/plan-review-leak-tracker.md`:

1. The paid Google lane is on for every tenant. The service drops `TRACKER_PAID_TENANTS`. Creds, caps and the breaker stay.
2. "Update on connect, then update models once a week or manual." The daily pass becomes weekly, and a manual refresh is added. The 00:00–04:00 `pending` window is superseded.
3. Previews have the legal go. Images are blurred by default, and the viewer clicks to unblur.
4. Confirmed defaults: profanity in the take captions OK; reddit = `forum` scene; more than 20 listings → partial OK; the `came_back_30d` ASSUMPTION OK.
5. The offer video is live (`/v1/me` `video`: `duration_s` 56.94, `has_poster` true, cues google 10, google_images 14.81, x 17.96, forum 21.47, mega 24.88, end 34.77). Goldens unchanged.

Not specified here (in flight on another branch): the tracker is on by default for every Agency, every connected Creator is auto-tracked, and the consent checkbox is gone. "Connect" below means that auto-track push, and the existing seed runs on it.

## User stories

Cadence
1. As an Agency owner, I want a Creator scanned as soon as it is connected, so that the page has data from day one. (Exists: the seed.)
2. As the owner of the Removal service, I want every lane to run once a week on the watch's Weekly slot and never daily, so that paid Google loads for every tenant fit the caps.
3. As an Owner or Admin, I want a "Refresh now" button on a Creator, so that I can see fresh results without waiting for its scan day.
4. As the owner, I want a refresh to be refused for 24 hours after any scan of that Creator starts, with the time it frees up, so that a button cannot spend more than one scan per Creator per day.
5. As a Team Leader, I want the strip above the roster to sum the last 7 days, not today, so that a quiet day between scans does not read as nothing found.
6. As a Team Leader, I want "Checking…" only while a scan is actually due or running, so that the marker means something.
7. As a Team Leader, I want the coverage section to say each Creator is checked weekly and on refresh, so that I do not expect daily changes.
8. As the owner, I want a link to read Gone only after two dead probes, confirmed the next day, so that weekly scans do not slow Gone to two weeks.

Previews
9. As a Team Leader, I want media Leaks shown as Google preview tiles by default, so that I see what Google Images shows.
10. As a Team Leader, I want each tile blurred until I click it, and blurred again when the Creator, the Agency or SFW changes or when I leave, so that explicit images never show unasked.
11. As the owner, I want `LEAK_TRACKER_PREVIEWS` kept as a kill switch that is on by default, so that previews can be turned off in one place.
12. As a Team Leader, I want the disclaimer to say that previews stay blurred until I click them, so that the rule is read once.

## Slice A — weekly cadence and manual refresh

### Service slice A

Removal service repo. Tickets 81, 82, 83.

**Schedule (ticket 81).**
- The paid Google lane runs for every tenant: drop `TRACKER_PAID_TENANTS` and its gate. Browserbase creds, `TRACKER_UNCAPPED_TENANTS`, the global daily cap, the tenant monthly cap and the breaker are unchanged.
- A *scan* is one run of every lane for one watch, in this order: Origin probe, Mega lookup, listing recheck, full Google pass, registry crawl. Every paid call is reserved as today. A scan has a trigger: `seed` (connect, unchanged), `weekly` or `refresh`. `daily_scans` keeps one row per (watch_id, UTC day) and gains `trigger TEXT` (additive). The one-row-per-day key holds because scans of one watch start at least 24 h apart (below).
- The scheduler tick (every 60 s, unchanged) starts a `weekly` scan, from `TRACKER_DAILY_AT` (default 04:00 UTC), for each unpaused, undeleted, seeded watch whose `weekly_slot` is today's weekday, unless a scan of that watch started in the last 24 h. A skipped slot reads that earlier scan as the week's.
- The Google fresh pass is retired. Its past-day query is covered by the weekly full pass. It is no longer run, reserved or listed in `lanes`. `run_fresh_batch` and its admission term go.
- Cap carry is unchanged. Full-pass queries cut by `cap_global` run once the next UTC day, then wait for the next slot. An unfinished registry crawl also continues the next day.
- Dead-streak confirm. A `url_key` whose latest settled probe was its first dead one is probed once more at the next UTC day's `TRACKER_DAILY_AT` tick. This is probe only: no other lane, no `lane_day` row and no reservation (it costs $0). The 2-dead rule, the `dead_since` rules and "one fetch per url_key per UTC day" are unchanged.
- Admission: `projected[d]` = Σ `plan_loads` of the watches whose slot is `d`. The "1 fresh load per watch per day" term goes. Refresh loads are not planned; reservations trim them like any carry.
- `next_check_at` = the next `weekly` scan start: the watch's next slot weekday at `TRACKER_DAILY_AT`, or today's if today is the slot day and the scan has not started. With a carry pending, it is the carry day.
- `lanes`: five items (no `google_fresh`), each `cadence: "weekly"`. `next_attempt_on` is the next slot day, or the carry or continue day.

**Refresh route (ticket 82).**
- `POST /v1/watches/{watch_id}/refresh`, Tracker key, no body (any body ignored). Checks, first match wins:
  1. Bad or revoked key → 401 (existing shape).
  2. Unknown id, or another tenant's → 404 `{"error": "not_found"}` (existing shape).
  3. Deleted → 410 `{"error": "watch_deleted"}` (existing shape).
  4. Paused → 409 `{"error": "watch_paused"}`.
  5. A scan of the watch is queued or running (including an unfinished seed) → 202 with that scan's `queued_at`. Idempotent; nothing new is queued.
  6. The last scan of the watch, of any trigger, started less than 24 h ago → 429 `{"error": "refresh_cooldown", "retry_after_s": <int, ceil seconds to next_refresh_at>, "next_refresh_at": "<UTC ISO Z>"}` with header `Retry-After: <retry_after_s>`. The existing per-key `{"error": "rate_limited"}` 429 is separate and unchanged.
  7. Otherwise, store the request (it survives a restart) and answer 202 `{"watch_id": "...", "queued_at": "<UTC ISO Z>", "next_refresh_at": "<queued_at + 24 h>"}`.
- The scheduler starts a queued refresh on its next tick, at any hour (no `TRACKER_DAILY_AT` wait), as a `refresh` scan of every lane under the normal reservations. A cap cut reads `partial`, with lanes `waiting` on budget. The cooldown is not refunded.
- Cooldown: `REFRESH_COOLDOWN_H = 24`, a constant measured from the start of the watch's last scan (seed, weekly or refresh).
- Creator reads (`GET /v1/creators` items and `GET /v1/creators/{id}`) add `next_refresh_at: "<UTC ISO Z>" | null`. It is null while the watch is paused. Otherwise it is the last scan start + 24 h, which may be in the past (refresh available now).
- Logs: counts and ids only, never the key or handle.

**`this_week` replaces `today` (ticket 83).**
- On both Creator reads, the `today` object is replaced by `this_week: {since, state, new, first_scan, came_back, gone}`:
  - `since` = UTC day today − 6, so the window is the 7 UTC days ending today (as `as_of`).
  - `new` = Leaks whose `first_seen_at` day is in the window, not first-scan. That equals `offer_counts.new_7d`.
  - `first_scan` = Leaks first seen in the window with `found_on_first_scan`.
  - `came_back` and `gone` = Leaks with a status change in the window to live from gone, or to gone.
  - `state` (first match wins): `paused` if the watch is paused; `pending` if a scan is queued or running, or if today is the slot day and its scan has not started yet and was not skipped; else the outcome of the latest finished scan in the window: `complete`, `partial` or `coverage_reduced` (same mapping as today's `day_state`); else `pending` if no scan has ever finished; else `complete` (the window holds no scan because the last one is older than 7 days — this happens only right before a slot day).
- `counts.new_today` stays in the shape (the CRM validates it) with unchanged meaning; the CRM stops showing it.
- `pending` no longer means "before 04:00 UTC with no finished row". The 00:00–04:00 window is gone.

**Golden JSON changes (the service updates them; the CRM copies them verbatim into `service/tests/fixtures/leak_tracker_v1/`).**
- `creators.json`, `creator_one.json`, `creator_one_coverage.json`, `creator_one_coverage_paused.json`: `today` → `this_week` as above; add `next_refresh_at` (null on the paused Rowan item); `next_check_at` moves to each watch's next slot day.
- `creator_one*.json` `lanes`: `google_fresh` removed; every `cadence` is `"weekly"`; `next_attempt_on` is the slot day.
- New `refresh_queued.json` (POST, 202, body above), `refresh_running.json` (POST during a scan, 202, the earlier `queued_at`), `err_429_refresh_cooldown.json` and `err_409_watch_paused.json`. The goldens carry no headers, so `Retry-After` is asserted in `test_tracker_api.py`.
- `me.json`, `me_video.json`, `leaks*.json`, `creator_leaks*.json` and `put_*.json`: unchanged by this slice.

**Acceptance (service).**
- [ ] A tick on a watch's slot weekday after `TRACKER_DAILY_AT` runs all five lanes once. A tick on any other weekday runs none for it, except carries, continues and dead-streak confirms.
- [ ] A watch seeded or refreshed in the last 24 h skips its slot scan, and its `lanes` show that scan.
- [ ] A tenant not on any list runs the paid Google lane, with reservations, caps and the breaker holding (stub request count = `used` units).
- [ ] No `google_fresh` load is reserved or made, and the lane is absent from `lanes`.
- [ ] A first dead probe gets exactly one probe the next day and can settle Gone. No other lane or reservation runs.
- [ ] Refresh: 202 then a scan on the next tick at 13:00 UTC. A second POST during it gives 202 with the same `queued_at`. A POST 23 h after the start gives 429 with `retry_after_s` ≈ 3600, a matching `Retry-After` and `next_refresh_at`. At 24 h it gives 202. Paused → 409; deleted → 410; another tenant's id → 404 with nothing queued.
- [ ] A queued refresh survives a service restart.
- [ ] A refresh that hits `cap_tenant_month` finishes `partial`, with lanes `waiting`/`cap_tenant_month`.
- [ ] `this_week` across a seed day, a slot day before and after the scan, a queued refresh, a paused watch and a capped scan. `pending` is never derived from the clock alone.
- [ ] Admission's `projected[d]` excludes fresh loads (existing `test_tracker_admission` cases updated).

### CRM slice A

This repo. Tickets 84, 85.

**Relay (ticket 84).**
- New `POST /admin/leaks/watches/{account_id}/refresh` in `service/leak_tracker_api.py`. The checks run before egress, in order:
  1. `require_gates(need_key=True)`.
  2. `account_id` in `_creators(ctx)`, else 404.
  3. `g.can_write`, else 403 `WRITERS_ONLY` (the tracking switch precedent).
  4. A local `leak_watch` row, else 404.
  5. `admission` set → 409 "This Creator is on the waitlist".
  6. `on` false → 409 "Tracking is off for this Creator".
- It calls the service with the row's `watch_id`:
  - 202 → 200 `{queued_at, next_refresh_at}`, and the Agency's read cache is dropped (the key-save precedent), so the next roster or drill-in read shows `pending`.
  - 429 `refresh_cooldown` → 429 `{detail: "Refreshed recently", next_refresh_at}` with `Retry-After` copied.
  - 429 `rate_limited` → 429 `{detail: "Try again shortly", next_refresh_at: null}`.
  - 409 `watch_paused` → 409 "Tracking is off for this Creator".
  - 401 → Phase 1's key-invalid handling (409 `KEY_INVALID`).
  - 410 → Phase 1's drop-the-row handling, then 404.
  - Unreachable or 5xx → 503.
- Reads: `_today` becomes `_this_week` (key `this_week`, `since` str, `state` in `DAY_STATES`, the four ints). `get_roster` and `_detail_of` pass `this_week` and `next_refresh_at` (str or null, added to `SERVICE_FIELDS` and to `_shaped`'s nullable-string check, so a pre-change service still reads). `UNKNOWN` gains `this_week: None, next_refresh_at: None` and drops `today`. `LANES` drops `google_fresh`.
- Tests: `service/tests/test_leak_tracker_discovery.py` gets the refresh cases: gate order with no egress for a Team Leader, another Agency's Creator, a waitlisted row or an off row; the 202 mapping with the cache dropped; the 429 mapping with `Retry-After`; the 401 and 410 handling; and `this_week` pass-through from the copied goldens.

**App (ticket 85).**
- `leakRefresh.ts` beside the drill-in: a pure `refreshReducer(state, action)` with a typed `Action` union (`load {nextRefreshAt, pending}`, `send`, `queued {nextRefreshAt}`, `cooldown {nextRefreshAt}`, `fail {message}`), plus a pure `refreshView(state, now, tz) -> {label, disabled, note}`. Vitest table in `leakRefresh.test.ts`, template `app/components/chat/fanDrawerForm.ts`. The component only dispatches. A Creator change dispatches `load` from the drill-in read.
- Drill-in header, writers only (`can_write` from the existing setup read), on a tracked, unpaused, non-waitlisted Creator: a "Refresh now" button.
  - It is enabled when `next_refresh_at` is null or past and `this_week.state` is not `pending`.
  - Sending: disabled, "Refreshing…".
  - Queued or `pending`: disabled, "Checking…", and the drill-in is read again.
  - Cooldown: disabled, "Next refresh <when(next_refresh_at)>", with the note "One refresh per Creator every 24 hours".
  - Error: enabled, with the detail inline.
  - Team Leaders see no button.
- The strip: `todayStrip`/`todayLine` become `weekStrip`/`weekLine` over `this_week`. The text is "{new} new this week · {cameBack} came back · {gone} gone · checked {checked} of {total}", plus "· {partial} partial" and "· {firstRun} found on first scans" when non-zero. `checked` counts `state === "complete"`. `LeakTodayStrip.tsx` → `LeakWeekStrip.tsx`, `aria-label="This week"`.
- Roster and header: `dayMarker`/`rosterChips` read `this_week.state` (labels unchanged; `pending` = "Checking…"). The "New today" cell becomes "New this week" = `this_week.new`, and `entryNote` reads "{n} new this week". The `counts.new_today` fallback is removed.
- Coverage: `LANE_ORDER`, `LaneName` and `LANE_LABEL` drop `google_fresh`. `FRESHNESS` = "Each Creator is checked once a week on its scan day, and again when an Owner or Admin presses Refresh now (at most once a day). Images, videos and new sites show after the next check."
- Tests: `leakCoverage.test.ts` (week sums, markers over every state), `leakView.test.ts` (New this week, entry note), `leakRefresh.test.ts`, and `app/creators/leaks/page.test.tsx`. The page test renders the strip, the button in each state at desktop and phone widths, and no button for a Team Leader.

**Acceptance (CRM).**
- [ ] A Team Leader's, another Agency's, a waitlisted or an off Creator's refresh makes no upstream call.
- [ ] 202 → 200 and the next roster read is fresh (not cached), showing "Checking…".
- [ ] 429 → the button reads "Next refresh <time>", disabled, with `Retry-After` passed through.
- [ ] The strip reads "new this week" from the copied goldens. With a pre-change service (no `this_week`) it is hidden and the roster still loads.
- [ ] Coverage shows five rows, with no "Google (past day)".
- [ ] `refreshReducer` table covers every action from every state. `tsc`, `comment_budget.py --check` and `cell_scope_scan.py --check` are green.

## Slice B — previews on by default, blurred until clicked

Tickets 70–73 (amended). They are unblocked: the legal go is given, and ticket 28 (media Leaks) is ready.

### Service slice B

Removal service repo. Ticket 70, after 28.

- As ticket 70 specifies (`thumb_url`/`thumb_query_id` from the weekly full pass, the `preview` field, `preview_only=1`, the `/thumb` route with its fetch-time checks), with one change: the service's `TRACKER_PREVIEWS` is **on by default**, and `TRACKER_PREVIEWS=0` turns it off. Off, `preview` is null everywhere and `/thumb` answers 404.
- `preview: {vertical: "images" | "videos", seen_at} | null` on every item of `/v1/creators/{id}/leaks` and `/v1/leaks`. `creator_one.preview_leak.preview` stays null (the popup preview is a page Leak).
- Golden JSON changes: `leaks.json`, `leaks_page2.json`, `creator_leaks.json` and `creator_leaks_visibility.json` gain `preview` on every item (null for the page and Mega items). One new media Leak fixture (`kind: "media"`, source `google_images`, a non-null `preview`) appears in `creator_leaks.json`. New `leaks_preview_only.json` (`?watch_id=…&preview_only=1&limit=12`, media items only, newest `seen_at` first). The thumb route is binary, so it gets no golden; `test_tracker_preview.py` asserts it.

**Acceptance (service).** Ticket 70's list, plus: with `TRACKER_PREVIEWS` unset, a media Leak with an allowlisted `thumb_url` and visibility true has a non-null `preview`; with `TRACKER_PREVIEWS=0` it is null and `/thumb` answers 404.

### CRM slice B

This repo. Tickets 71, 72, 73.

- `LEAK_TRACKER_PREVIEWS` (ticket 71): a `runtime_switches` bool, **default on**, parsed with `_not_off` (the `S4S_LIVE_POSTING` precedent). Env `0`/`off` or an in-app force-off turns it off. Off: `preview` is dropped from reads, `/thumb` and `/all?preview=1` answer 404, and the Google view shows text tiles. Everything else in ticket 71 is unchanged (gates and grant before egress, no caller URL, streamed, `private, no-store`, `nosniff`, 401/410 handling, counts-only logs).
- Blur by default, click to unblur (ticket 72). This replaces the page-level "Reveal previews" button.
  - Each tile's image is a `<button aria-pressed="false" aria-label="Unblur preview">` over the lazy image at `blur-md`. A click unblurs that tile only (`aria-pressed="true"`, label "Blur preview"), and a second click blurs it again.
  - The reveal is a per-tile `useState` boolean, never stored. The grid and the All Models strip are keyed by `agency · Creator · sfw`, so every tile blurs again on a Creator, Agency or SFW change and on leaving.
  - The tile's site and title text is the outbound link, like its list row, so a click on the image never navigates.
  - SFW on: a placeholder, no `<img>`, no button.
  - `thumbState(sfwOn, previewsOn, revealed)` is unchanged and is now called per tile.
- The disclaimer line (ticket 73), shown while the switch is on: "Google previews are automated search matches. They can be explicit or show someone else. They stay blurred until you click one, and this app keeps no copy." Seen key: `chatterly:leak_disclaimer_seen:v2:<employee key>`. Because the switch is on by default, everyone who dismissed the v1 text sees the dialog once more.

**Acceptance (CRM).** Tickets 71–73's lists, with these changes:
- [ ] With the switch unset, previews read on and the thumb route streams.
- [ ] Clicking one tile unblurs only that tile. A second click blurs it.
- [ ] A Creator, Agency or SFW change re-blurs every tile.
- [ ] Clicking the image does not navigate; the title link does.
- [ ] SFW on renders no `<img>` and makes no thumb request.
- [ ] The disclaimer reads "until you click one".

## Downstream amendments

- Superseded by 81/83/85: ticket 11 ("checked once each UTC day"), 20's Today strip and day markers, 26's daily fresh pass, and Phase 2's FRESHNESS copy and "New today" cell. Their shipped code is changed by those tickets, not reopened.
- Not yet built, each with an amendment line and a "Blocked by: 85" edge:
  - Ticket 49: the Demo tracker serves `this_week`, `next_refresh_at`, five weekly lanes and a refresh answer.
  - Ticket 51: keeps one row per UTC day with news. News now lands only on scan days. A date is `complete` when every scan that started that day finished, and a day with no scan files nothing.
  - Ticket 55: the link swaps the This week strip for "On <d MMM>: …".

## Tickets

| # | Title | Repo | Blocked by |
|---|---|---|---|
| 81 | Every scan runs on the Weekly slot, the paid lane is on for every tenant, and the fresh pass retires | service | 23, 27 |
| 82 | `POST /v1/watches/{id}/refresh` queues one scan with a 24 h cooldown | service | 81 |
| 83 | Creator reads carry `this_week`, `next_refresh_at` and the new `pending` | service | 81, 82 |
| 84 | The Relay's refresh route and the `this_week` pass-through | CRM | 83 |
| 85 | Refresh now button, This week strip, roster and coverage copy | CRM | 84 |
| 70–73 | Previews (amended: default on, click to unblur) | both | as before |

## ASSUMPTIONs

- ASSUMPTION: the Google fresh pass retires rather than running weekly (rung 5: a weekly past-day query adds nothing to the weekly full pass). Overturned if the pilot shows the full pass misses results the fresh query finds; then `google_fresh` runs inside each scan with a past-week window.
- ASSUMPTION: all lanes, including the $0 Origin probe, Mega lookup and listing recheck, run weekly (rung 2: "update models once a week"). The exception is the $0 dead-streak confirm probe the next day (rung 4: keeps Gone at about a day after the second probe instead of two weeks). Overturned if the owner wants the free lanes kept daily.
- ASSUMPTION: the cooldown is 24 h from the start of the last scan of any trigger, and the slot scan is skipped within 24 h of another scan (rung 5: one rule caps a Creator at one scan a day, at most about the old daily spend). Overturned by pilot cost figures or an owner-named interval.
- ASSUMPTION: a cap-cut refresh still uses the cooldown (rung 5). Overturned if Owners complain; then a refresh with zero lanes run refunds it.
- ASSUMPTION: `today` is replaced by `this_week` instead of shipping both (rung 1: the CRM's `_today` turns a missing block into null and `todayStrip` hides on all-null, so the old CRM degrades to no strip and the roster still loads; observed in `service/leak_tracker_api.py` and `app/components/leaks/leakCoverage.ts`). Overturned if a deploy gap must keep the strip; then the service emits both for one release.
- ASSUMPTION: refresh is writers only, Owner and Admin (rung 3: the tracking switch's `can_write` gate; it spends paid loads). Overturned if the owner wants Team Leaders to refresh.
- ASSUMPTION: per-Creator refresh only, no "Refresh all" (rung 5). Overturned on an owner ask; then the relay loops the granted watches and reports each 429.
- ASSUMPTION: click to unblur is per tile, replacing ticket 72's page-level Reveal (rung 2: "the user clicks to unblur"). Overturned if the owner wants one button for the page back.
- ASSUMPTION: `LEAK_TRACKER_PREVIEWS` and `TRACKER_PREVIEWS` default on, kept as kill switches (rung 2: the legal go plus blur by default; rung 3: default-on `_not_off` switches). Overturned if the owner wants previews opt-in per deployment.
- ASSUMPTION: the v2 disclaimer is shown once more to everyone, since previews are on by default (ticket 73's existing rule). Overturned if a second dialog is judged worse than missing the line.

## Out of scope

- Consent, default-on tracking and auto-track (another branch).
- Any change to the seed, the judge, the registry crawl's content, or the Notice feed.
- Per-tenant refresh caps beyond the existing paid-load caps.
