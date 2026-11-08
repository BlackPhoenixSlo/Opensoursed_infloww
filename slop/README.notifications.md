# slop/: The Agency owner's notification feed at volume

The owner's notification feed (`service/notifications_api.py`: `GET /admin/agency-notifications?limit&offset`,
`POST /read-all`, `POST /{id}/read`, the `tick` sweep, the owner's `agency_notifications` SSE count). The
harness, its knobs and its rules are in `README.md`; this file is only what this flow adds. The scenario's
docstring is its spec (phases, load, bypasses).

## Layout

| Path | Role |
|---|---|
| `lib/notifications_relay.py` | `POST /__slop/notifications-tick {now?}`: one `notifications_api.tick(now)` pass (missed clock-ins, retention prune; looked up at call time), `now` standing in for the clock; answers `{filed, ms}`. In production only `server._periodic` runs it (every 5 min, skipped under `CHATTERLY_TEST_MODE`). Inert (404) unless the scenario wrote `$DEMO_SHOTS_TMP/notifications-tick.json`. |
| `lib/notifications_faults.py` | The check names, `READ_ALL_LAG_S` (the read-all fault's re-run delay, which the scenario's wait is coupled to) and its faults (below), each patching a `notifications_api` attribute looked up at call time. |
| `seed/agency_notifications_bulk.py` | `n` owner rows in one SQL insert, shaped as `notify` files them (`role_changed`, `employee_deactivated`, `message_unsent`, `session_dead`), read and unread, aged 1 min to 120 days, in filings that share one `created_at` (ties ordered by id), plus three boundary rows at `w.now - retention` -1 s / 0 / +1 s. No `clock_in_missed` (each needs a Shift; the sweep files those for real). `w.data["agency_notifications_bulk"]`: ids and the boundary ids. |
| `scenarios/2026-11-01-notifications-feed-volume.py` | The scenario; its `_State` (the seeded feed and every session's plan). |
| `lib/consent_faults.py` | The consent scenario's check names and faults. |
| `scenarios/2026-11-08-consent-required-notice.py` | The pinned `consent_required` row (`service/consent_notices.py`, `notifications_api.PINNED_KINDS`) and the shell's ConsentBanner. |

## Scenarios

- `2026-11-01-notifications-feed-volume`: `agency_inbox` plus `seed/agency_notifications` (one session_dead per
  Creator) and `seed/agency_notifications_bulk`; through the real routes 3 owner-made logins, 4 plain Employees,
  time tracking on. `min(--users, 10)` owner SSE streams listen throughout. 1, page: every `--users` session opens
  the bell, clicks one unread row, and takes its share of every page at sizes 30 / 50 / 100 / 200 on a frozen feed.
  2, prune: one sweep at the seed's `now`, then a running Shift and a sweep that files its missed clock-in. 3,
  read: Mark all read / one row / reopen while a filer files for real (role toggles, deactivate + reactivate, a
  Shift, sweeps); after a barrier every session's Mark all read, then one filing each that must stay unread. 4, UI:
  /notifications and the bell (screenshots `notifications-page`, `bell-trigger`, `bell-agency-open`,
  `bell-agency-settled`); side effect SQL and API unread 0. Checks (`lib/notifications_faults.py`): `PAGED`,
  `READ_ONE`, `CLICK_SYNC`, `PRUNED`, `PRUNE_PUSHED` (a prune-only sweep pushes the
  new count to each Agency it pruned unread rows of), `LATER_UNREAD`, `BADGE`, `UI_FEED`; budget `p95 GET /admin/agency-notifications`, plus GET,
  `POST read-all` and `POST /:id/read` p95 vs the last green run, all in the scenario. Faults:
  `read-all-marks-later-rows` (default; targets `LATER_UNREAD`), `notif-page-skips-offset` (`PAGED`),
  `notif-prune-ignores-retention` (`PRUNED`), `notif-prune-not-pushed` (`PRUNE_PUSHED`). Knob: `--notif_rows=` bulk rows (SCALES `notifications_feed_rows`).
- `2026-11-08-consent-required-notice` (`OF_WIRE`, UI, volume): `agency_inbox` with captured sessions and pumps up;
  `lib/of_wire.py`'s `consent` refuses REF's media sends (400 Consent not accepted) during `--sends=` (FLOW_SIZES
  `consent_sends`) media sends over every Creator's fans at `--users`; ME flagged through /users/me (law AL) on its
  pump's reconnect; each pinned row's read 409 and read-all; the owner's browser desktop + phone portrait (banner,
  View, Agency tab: `trigger-desktop`, `trigger-phone`); then REF approved (reconnect), ME's accepted media send,
  REF refused again and deleted from Creators; browser again (`settled-desktop`, `settled-phone`). Checks
  (`lib/consent_faults.py`): `FLAGGED_ONCE`, `SENDS_KEPT`, `FLAGGED_BY_ME`, `NOT_DISMISSABLE`, `UI_TRIGGER`,
  `CLEARED_BY_ME`, `CLEARED_BY_SEND`, `CLEARED_BY_REMOVAL`, `UI_SETTLED`; budget p95 of the send route, plus vs the
  last green run. Faults: `consent-send-ok-not-clearing` (default; `CLEARED_BY_SEND`), `consent-pinned-readable`
  (`NOT_DISMISSABLE`). Side effect: `rows.json` (the SQL rows after each step).
