# Phase 03 — Share for Share inside this deployment's agencies

**Objective.** An owner can opt a Creator into Share for Share, find opted-in Creators of every Agency in this Deployment through Discovery, send and answer S4S requests, and see the resulting S4S slots on a monthly S4S schedule. Discovery is the only read that crosses Agency isolation (ADR-0011), and every slot posts only on its own Creator's account, behind a live-posting flag that is off by default.

## Problem Statement

An owner running two to five Agencies on one Inflowwww Deployment has no way to cross-promote Creators. The three Share for Share entries in the sidebar ("Discover creators", "Requests", "S4S schedule") open the "not built yet" placeholder. The inventory (`docs/infloww-screens.md` §3.6) still says "we dropped it", and the roadmap overturns that. The Relay answers 403 for any Creator outside the caller's Agency, which is correct everywhere else. It also means one Agency cannot even learn that another Agency's Creator would welcome a shoutout swap. Owners arrange swaps by hand, outside the app. Nothing shows which swaps were agreed, when each post goes up, or whether it came down after 24 hours.

## Solution

Share for Share is rebuilt as a consent-based network bounded by the shared database.

- **S4S Setting.** Each owner opts in Creator by Creator (off by default). For each Creator the owner sets Discovery Page Visibility and a Daily limit of 1, 2 or 3, edits the display fields, and keeps up to 20 S4S posts, one of them marked "Set as Primary Post".
- **Discover creators.** Lists the S4S projection of every opted-in, visible Creator in this Deployment, the owner's own Agency included, and nothing else. A line on the page says that only agencies on this Inflowwww deployment appear. When no other Creator has opted in, the page shows an honest empty state.
- **Requests.** Received and Sent tabs. The owner sends a request from one of their own Creators for a proposed time, and the receiving owner answers Accept, Skip or Decline. The sender can cancel while the request is pending.
- **S4S schedule.** A monthly calendar of the owner's own Creators' S4S slots, with the statuses "Will be posted shortly", "In progress", "Completed" and "Canceled".

On Accept, each side gets one slot. In each slot the side's own Creator posts the partner's caption with an @mention of the partner. The posted text ends with Infloww's `#advertisement` tag. The post is removed 24 hours later through the existing Auto Post path. Live posting is on by default; if the Deployment's operator turns it off, no slot reaches OnlyFans. The schedule says so, and such a slot ends as "Canceled" with the reason "live posting off".

## User Stories

1. As an owner, I want each of my Creators to start opted out of S4S, so that nothing about a Creator is visible to other Agencies until I choose.
2. As an owner, I want to opt one Creator in or out from the S4S Setting panel, so that consent is per Creator, not per Agency.
3. As an owner, I want a Discovery Page Visibility switch per Creator, so that an opted-in Creator can keep its existing requests and slots without being listed in Discovery.
4. As an owner, I want to set a Creator's Daily limit to 1, 2 or 3, so that no Creator is booked for more S4S slots per day than I allow.
5. As an owner, I want to edit the display name, @username and avatar URL shown to partners, prefilled from the Creator's nickname, so that I decide exactly what other Agencies see.
6. As an owner, I want to create, edit and delete S4S posts (caption up to 5000 characters), up to 20 per Creator, so that I keep a set of promo texts ready.
7. As an owner, I want to mark one S4S post per Creator as the Primary post, so that Discovery and requests show the text I chose.
8. As an owner, I want the "Add from Vault" media control shown but marked Not wired, so that I know media is not carried across accounts rather than finding it silently missing.
9. As an owner, I want Discover creators to list opted-in, visible Creators from every Agency in this Deployment, my own included, so that I can find partners.
10. As an owner, I want each Discovery card to show only display name, @username, avatar, the Primary post's caption, Daily limit and opt-in state, so that no Agency learns fan data, earnings, proxy, notes or credentials.
11. As an owner, I want to filter Discovery by name or @username, so that I can find a known partner quickly.
12. As an owner, I want the Discovery page to say that only agencies on this Inflowwww deployment appear here, so that I never mistake it for a public directory.
13. As an owner on a Deployment where no other Creator has opted in, I want an honest empty state, so that I know the list is empty because nobody has opted in, not because something failed.
14. As an owner, I want to send an S4S request from one of my opted-in Creators to a Discovery card for a proposed date and time, so that the partner can agree to a concrete slot.
15. As an owner, I want the request to fix both captions at the moment I send it, so that each side agrees to the exact text it will post.
16. As an owner, I want a request refused when either Creator lacks a Primary post, is not opted in, or is already full for that day, so that no request is accepted that cannot be honoured.
17. As an owner, I want at most one open request between the same two Creators in the same direction, so that partners are not spammed.
18. As an owner, I want a Received tab with Accept, Skip and Decline on each pending request, so that I answer requests the way Infloww does.
19. As an owner, I want Skip to hide a request from my Received tab without telling the sender, so that I can pass quietly.
20. As an owner, I want a Sent tab showing each request's status, so that I see what partners did with my requests.
21. As an owner, I want to cancel my own pending request, so that I can withdraw it before it is answered.
22. As an owner, I want a pending request whose proposed time has passed to show as expired and no longer be acceptable, so that no slot is created in the past.
23. As an owner, I want Accept to create one S4S slot for my Creator and one for the partner's Creator at the agreed time, so that the swap is reciprocal.
24. As an owner, I want each S4S slot posted only by its own Creator on its own OnlyFans account, so that no Agency ever operates another Agency's account.
25. As an owner, I want the posted text to be the partner's Primary caption plus an @mention of the partner, so that the promo is useful without media.
26. As an owner, I want each S4S post removed 24 hours after it is posted, so that the reference behaviour is preserved.
27. As an owner, I want a monthly S4S schedule of my own Creators' slots with "Will be posted shortly", "In progress", "Completed" and "Canceled", so that I can see where each swap stands.
28. As an owner, I want a slot that failed to post shown as "Failed" with its reason, so that a failure is never shown as done.
29. As an owner, I want to cancel my own Creator's future slot, so that I can withdraw consent before it posts.
30. As an owner, I want opting a Creator out to cancel its pending requests and its future slots, while already published posts still come down at their 24-hour removal, so that opting out takes effect at once without leaving posts up.
31. As an owner, I want a request or slot whose Creator has left every Agency, or whose Agency was deleted, to stop showing as live and to be skipped at run time, so that a departed Creator is never posted for.
32. As the Deployment operator, I want live posting on unless I set the flag off, so that accepted S4S post without an extra deploy step, and I can still stop every S4S post with one variable.
33. As an owner while live posting is off, I want the schedule to say so, and each slot that comes due to end as "Canceled" with reason "live posting off", so that I am never told a post went up when it did not.
34. As an owner, I want every consequential S4S action (opt-in change, request sent, answered or cancelled, slot cancelled, slot posted or failed) recorded in the audit history, so that a dispute between Agencies can be settled from the record.
35. As an owner, I want any S4S route naming another Agency's Creator answered 403, and any request or slot I am not a party to answered 404, so that I cannot read or change another Agency's S4S data.
36. As a chatter, I want the Share for Share section hidden and its routes refused, so that S4S stays an owner decision until role permissions say otherwise.
37. As an unauthenticated caller, I want every S4S route to answer 401, so that nothing about any Creator leaks without a session.
38. As an owner, I want S4S posting caps and expiry to be only those confirmed by the help articles (20 posts per Creator, 5000 characters, a Daily limit of 1 to 3, removal after 24h), so that nothing guessed is enforced.
39. As a maintainer, I want the S4S tables added by a reversible migration with indexes and constraints that `init_db()` also creates on an existing database, so that the schema reaches every box and can be rolled back.
40. As a maintainer, I want `docs/routes.md`, the inventory's §3.6 and the parity matrix's S4S rows to describe the built feature, so that the docs match the code.

## Implementation Decisions

- **Owns.**
  - Relay: a new router module `s4s_api` (prefix `/admin/s4s`) and a new automation `s4s_post`, auto-imported by the automations package like the others. New models `S4SProfile`, `S4SPost`, `S4SRequest` and `S4SSlot` (table `s4s_schedule`) go in the models module, with one Alembic migration.
  - App: a new client module `lib/s4s` (types and fetch calls through the existing relay helper) and new components under `components/s4s/`: Discover creators, Requests, S4S schedule and the S4S Setting panel. The `share-for-share/[section]` page switches on the section. The Share for Share group in the nav module loses its three `nb()` stubs and gains `chatterHidden`.
  - Docs: the `docs/routes.md` S4S rows, `docs/infloww-screens.md` §3.6, and the S4S rows of `docs/infloww-parity-matrix.md` (Phase 0 creates the matrix).
- **Not modified.** The Auto Post automation, the unsend automation, `assert_account_owned` and the account isolation middleware are all left unchanged. `s4s_post` calls Auto Post's public `run` and reads back the `local_post_id` and `delete_at` it already returns.
- **Interfaces.**
  - `s4s_api` resolves every request through Phase 1's Agency context. No session is 401. A Chatter session is 403. An Owner session and a Master both proceed. Any own-Creator id in a path or body passes `assert_account_owned`.
  - `s4s_post.run(account_id, {slot_id}, run_id)` loads the slot. It does nothing when the slot is `posted`, `canceled` or `failed`. A slot found in `posting` was interrupted mid-post by an earlier attempt (the executor retries a raised job), so it is marked `failed` with reason `interrupted_mid_post` and never posted again. It marks a `scheduled` slot `canceled` with a reason when live posting is off, when the poster or the partner is no longer opted in, when either has no Agency, or (`missed`) when the run comes 24 hours or more after `slot_at`. Otherwise it moves the slot from `scheduled` to `posting` with a status-guarded update, commits, and only then calls Auto Post with `{"posts": [{"text", "hours_to_live": 24}]}` on the poster's own account. On success it records `post_id`, `of_post_id`, `posted_at` and `remove_at`. On an error result it records `failed` with the reason.
  - The live-posting flag is a Relay environment variable `S4S_LIVE_POSTING` (default on; `0`/`false`/`no`/`off` turns it off). It is read on every call, never captured at import (precedent: `ALLOW_ANONYMOUS_ADMIN` in the auth module), and reported to the app as `live_posting` in the profiles response.
- **Schema.** One Alembic migration whose `down_revision` is the single head when it lands (`0066_split_inbox` today; Phase 2 may land its own migration first). Its `downgrade()` drops the four tables, and that is the documented recovery path: only S4S data is lost. Every foreign key to `accounts` is `ON DELETE CASCADE`, so deleting a Creator deletes its S4S rows. The tables are added through `Base.metadata`, so `init_db()`'s additive catch-up creates them on an existing database.

  ```
  s4s_profiles   id PK, account_id UNIQUE FK, opted_in bool NOT NULL default false,
                 discovery_visible bool NOT NULL default true,
                 daily_limit int NOT NULL default 1 CHECK 1..3,
                 display_name ≤64, username ≤64, avatar_url NULL, created_at, updated_at
  s4s_posts      id PK, account_id FK, caption text NOT NULL CHECK length ≤5000,
                 is_primary bool NOT NULL default false, created_at, updated_at
                 UNIQUE (account_id) WHERE is_primary            -- one Primary post
                 ≤20 rows per account_id: enforced by the API (409)
  s4s_requests   id PK, from_account_id FK, to_account_id FK, CHECK from <> to,
                 slot_at (UTC), from_caption, to_caption (snapshots),
                 from_projection_json, to_projection_json (snapshots taken at send),
                 status pending|accepted|declined|skipped|cancelled|expired,
                 cancel_reason NULL, created_at, answered_at NULL
                 UNIQUE (from_account_id, to_account_id) WHERE status IN (pending, skipped)
                 INDEX (to_account_id, status), INDEX (from_account_id, status)
  s4s_schedule   id PK, request_id FK CASCADE, poster_account_id FK, partner_account_id FK,
                 text, slot_at (UTC), status scheduled|posting|posted|canceled|failed,
                 reason NULL, job_id NULL, post_id NULL FK posts SET NULL,
                 of_post_id NULL, posted_at NULL, remove_at NULL
                 INDEX (poster_account_id, slot_at)
  ```

  Retention: S4S rows are kept until their Creator is deleted. They hold no fan data. Audit rows follow the existing `actions` retention.
- **Contracts.** These are Relay routes, all JSON. Foreign Creators are only ever referred to by S4S profile id, never by account id, so a foreign account id never appears in a path, a query or a response. That keeps the isolation middleware's 403 intact for every other route.
  - `GET /admin/s4s/profiles` returns `{live_posting, profiles: [{account_id, profile_id, opted_in, discovery_visible, daily_limit, display_name, username, avatar_url, posts: [{id, caption, is_primary}]}]}`. It lists the caller's own Creators only. A Creator with no row is shown with defaults (opted out), and no row is written on read.
  - `PUT /admin/s4s/profiles/{account_id}` takes `{opted_in?, discovery_visible?, daily_limit?, display_name?, username?, avatar_url?}`. It upserts the row. A change from opted in to opted out runs the opt-out cascade.
  - `POST /admin/s4s/profiles/{account_id}/posts` takes `{caption}`. `PATCH` and `DELETE /admin/s4s/profiles/{account_id}/posts/{post_id}` edit or remove a post. `POST …/posts/{post_id}/primary` moves the Primary mark.
  - `GET /admin/s4s/discover?q=` returns `[{profile_id, display_name, username, avatar_url, primary_caption, daily_limit, opted_in, own_agency}]`. These keys are the S4S projection plus `own_agency` (true for the caller's own Creators), and no others. The list holds opted-in, `discovery_visible` Creators that have a Primary post and at least one `user_accounts` row, capped at 200, sorted by display name.
  - `POST /admin/s4s/requests` takes `{from_account_id, to_profile_id, slot_at}`. It answers 201 with the request.
  - `GET /admin/s4s/requests?box=received|sent` returns `[{id, box, status, slot_at, from: projection, to: projection, created_at, answered_at}]`. A skipped request is absent from the receiver's box and shows as `pending` in the sender's box. `from` and `to` are the projection snapshots stored on the request at send time, never a live read of the other Agency's profile, so Discovery stays the only live cross-agency read (ADR-0011). The sender's snapshot is what it chose to show by sending; the receiver's is the Discovery card the sender saw.
  - `POST /admin/s4s/requests/{id}/accept|skip|decline` is for the receiver only. `POST /admin/s4s/requests/{id}/cancel` is for the sender only, and works on a request that is `pending` or `skipped` (both show as pending to the sender).
  - `GET /admin/s4s/schedule?from&to` returns the caller's own Creators' slots with `from` <= `slot_at` < `to` (ISO-8601 instants with a zone, at most 42 days apart; the app sends its local month's first and next-first instants, as the Shift schedule sends its local week; a missing or malformed range is 422, parsed by `shifts_api._parse_range`) with `{id, slot_at, status, display_status, reason, partner: projection, remove_at}`. `partner` is the request's stored snapshot of the partner, not a live read.
  - `POST /admin/s4s/slots/{id}/cancel` cancels the caller's own slot while it is `scheduled`.
  - Status codes: 401 when there is no session. 403 for a Chatter session, or for naming a Creator outside the caller's Agency (from `assert_account_owned` and the middleware). 404 for a request, slot, profile id or post the caller is not a party to, or that does not exist; the two are indistinguishable. 400 for a malformed body, a caption over 5000 characters, `daily_limit` outside 1–3, or a request to the caller's own `from_account_id`. 409 for the 21st post, an open request between the same pair, a past `slot_at`, a missing Primary post, an opted-out party, or a full Daily limit on either side. 409 also covers answering a request that is no longer pending, which includes one that expired.
- **Lifecycle.**
  - A request is `pending` until answered. From `pending` the receiver moves it to `accepted`, `declined` or `skipped`. From `pending` or `skipped` it moves to `cancelled` by the sender or the opt-out cascade, or to `expired`. Expiry is applied lazily on any S4S read or write, once `slot_at` has passed.
  - Every transition is a status-guarded update (`UPDATE … WHERE id = ? AND status IN (…)`), and a zero row count answers 409. So of two simultaneous answers, or an answer racing a cancel, exactly one wins. Accept runs its guarded update first, then the Daily limit and opt-in re-checks, then the slot inserts, all in one transaction; a failed re-check rolls the whole accept back with 409. This is the same lazy pattern as Phase 2's Auto clock-out, with no scheduler.
  - Accept re-checks both Daily limits and both opt-ins. It then creates two slots in one transaction. Slot one is posted by `to_account` with `from_caption` plus `@from.username`. Slot two is posted by `from_account` with `to_caption` plus `@to.username`. Both are at `slot_at`. One `s4s_post` job is enqueued for each slot on its poster's account through the executor's `enqueue_job`, with `run_at=slot_at` (the executor's default `run_at` is now, `service/automation_executor.py` `enqueue_job`).
  - The Daily limit counts a poster's slots that are not canceled and fall on the same UTC day as `slot_at`.
  - The opt-out cascade writes only the opting-out Creator's own rows: its pending and skipped requests (sent and received) become `cancelled` (reason `opted_out`), and its own future `scheduled` slots become `canceled` (reason `opted_out`). The partner's paired slot is never written by the other Agency's action. It is shown as "Canceled" with reason `partner_opted_out`, derived on read while the partner is opted out, and its own `s4s_post` run cancels it at `slot_at` (the run-time opt-in check above). Posted slots are left for their 24h removal.
  - Cancelling a slot cancels only the caller's own slot.
- **Order of work.** The roadmap says "implement tenancy before discovery UI". So the models, the `s4s_api` routes and the cross-agency cases in `test_s4s_api.py` land green before any `components/s4s/` page calls them. The plan's ADR step is already done: ADR-0011 records the one exception, so this Phase writes no new ADR.
- **Display status.** `scheduled` shows as "Will be posted shortly", and `posting` as "In progress". `posted` shows as "In progress" while the linked `posts` row is `posted`, and as "Completed" once the unsend automation has set it to `deleted`. `canceled` shows as "Canceled" with its reason. `failed` shows as "Failed" with its reason, with the tooltip "Inflowwww extra" (ADR-0003 labelling) because Infloww has no such status. The calendar renders in the app's selected timezone.
- **Audit.** Each consequential action writes one `actions` row: `account_id` is the caller's Creator, `employee_id` is null for an Owner session, and `action` is one of `s4s.profile_update`, `s4s.request_send`, `s4s.request_accept`, `s4s.request_skip`, `s4s.request_decline`, `s4s.request_cancel`, `s4s.request_expire`, `s4s.slot_cancel`, `s4s.slot_post` or `s4s.slot_fail`. `payload_json` carries `agency_user_id` and the S4S row ids, never fan data.
- **UI.**
  - The three routes are `/share-for-share/discover-creators`, `/share-for-share/requests` and `/share-for-share/schedule`. An unknown section gives a 404. Each page header has an "S4S Setting" button that opens the S4S Setting panel as a drawer, built from the shared Settings Panel parts (`Card`, `ToggleRow`, `Switch`, `SettingsTable`). It adds no fourth nav entry.
  - Discovery always shows the line "Only agencies on this Inflowwww deployment appear here." When the list is empty, or holds only the caller's own Creators, it also shows: "No other agency on this deployment has opted a Creator into Share for Share yet."
  - The post editor shows "Add from Vault" disabled with a Not wired note.
  - The schedule shows a banner whenever `live_posting` is false: "Live posting is off on this deployment. Slots are planned, but nothing is posted to OnlyFans."

## Testing Decisions

There are two seams, both at the highest public interface.

1. **Relay HTTP seam: the `/admin/s4s` routes through the FastAPI app**, in the plain-assert script `service/tests/test_s4s_api.py` and its siblings `service/tests/test_s4s_requests.py` (the request lifecycle, ticket 17), `service/tests/test_s4s_schedule.py` (the schedule, slot cancel, opt-out cascade and departed-Creator cases, ticket 18) and `service/tests/test_s4s_post.py` (the `s4s_post` automation with the of-client faked, ticket 19), split so no test file passes 1,000 lines and sharing seeders through `service/tests/_s4s_fixtures.py`. It runs on the throwaway `_harness` database and Phase 1's two-agency fixture: two Agencies, each with an owner, a chatter and a Creator, plus a third Creator added for limit cases. It asserts external behaviour only:
   - Isolation and projection: Discovery's key set equals the projection exactly; no account id appears anywhere in the Discovery or request JSON; Creators that are opted out, not visible, without a Primary post or without an Agency are absent; the own Agency's Creators are included and flagged.
   - Cross-agency negatives: 403 on `PUT /admin/s4s/profiles/{other agency's account}` and on its posts, and 404 when one Agency accepts, cancels or reads another Agency's request or slot as a non-party.
   - Codes: 401 with no session and 403 for a Chatter on every route.
   - The full lifecycle, including the skip asymmetry, lazy expiry, the duplicate-pair 409, the Daily limit 409, the 20-post and 5000-character limits, and the single Primary post.
   - Accept creates two slots on the two posters' own accounts and enqueues two `s4s_post` jobs. The test reads `scheduled_jobs`, with the executor not running.
   - The opt-out cascade: the opting-out Creator's own requests and slots are cancelled, the partner's slot row is unchanged in the database but reads as "Canceled" / `partner_opted_out`, and its `s4s_post` run cancels it with zero post calls.
   - Story 31: remove a Creator's last `user_accounts` row, and separately delete its Agency; the Creator leaves Discovery, its requests and slots stop reading as live, and `s4s_post.run` on its slot (as poster and as partner) ends `canceled` with zero post calls.
   - Races and transitions: a second answer to an answered request, an accept after a cancel, and a sender cancel of a skipped request.
   - Audit rows are written.
   - Publishing: it runs `s4s_post.run` directly with the of-client post call patched to a fake, as `test_auto_posts.py` does. With `S4S_LIVE_POSTING=0` the slot ends `canceled` / "live posting off" and the fake records zero calls. With the flag unset or `1` it records one call on the poster's own account with caption plus @mention plus a last `#advertisement` line, and a 24h `unsend_messages` job is queued with the poster's `account_id`. A slot left in `posting` ends `failed` / `interrupted_mid_post` on the next run with zero calls, and a run 24h or more after `slot_at` ends `canceled` / `missed` with zero calls. The accept test asserts each queued `s4s_post` job's `run_at` equals `slot_at`.
   - Migration reach: drop the four tables, re-run `init_db()`, and the tables and the partial unique indexes are back (precedent `test_automation_queue_indexes.py`).
   - Migration reversibility: on the harness's temp database only (`-x url=` set to the harness file, never the `alembic.ini` default), `alembic upgrade head`, then `downgrade` to the S4S migration's own `down_revision` (read from its file, never `-1`) removes the four S4S tables and leaves every older table, then `upgrade head` restores them. Phase 5's migrations may land on top of this one (Phase 3 depends only on Phase 1), so a relative step would undo the wrong revision (six-hats review).

   No live OnlyFans call is possible: the of-client is patched, and the flag defaults off.
2. **App component seam: the S4S pages rendered with a mocked relay fetch**, vitest under `components/s4s/` (precedent: the Settings tab tests such as `TimeTrackingTab.test.tsx` and `BillingTab.test.tsx`).
   - It asserts the deployment-bounded explainer and the empty-state copy, that cards render only projection fields, the Received/Sent tabs and their buttons, the four Infloww status labels plus "Failed", the live-posting-off banner, and the Not wired media control.
   - `nav.test.ts` gains: the Share for Share group has no `notBuilt` child, and all three children are `chatterHidden`.

Prior art: `test_settings_api.py` (session-driven route tests, chatter 401/403), `test_account_isolation_gate.py` (cross-agency 403), `test_auto_posts.py` (a fake of-client for posting and the queued delete), `test_automation_queue_indexes.py` (the `init_db()` catch-up), `nav.test.ts`, and the Settings tab vitest files.

## Acceptance

```sh
cd <repo>
./venv/bin/python service/tests/test_s4s_api.py
./venv/bin/python service/tests/test_s4s_requests.py
./venv/bin/python service/tests/test_s4s_schedule.py
./venv/bin/python service/tests/test_s4s_post.py
./venv/bin/python service/tests/test_auto_posts.py
./venv/bin/python service/tests/test_account_isolation_gate.py
./venv/bin/python service/tests/test_settings_api.py
./venv/bin/python -m py_compile service/s4s_api.py service/s4s_requests_api.py service/s4s_schedule_api.py service/automations/s4s_post.py service/db/migrations/versions/*s4s*.py
test "$(PYTHONPATH=. ./venv/bin/alembic -c service/db/migrations/alembic.ini heads 2>/dev/null | wc -l | tr -d ' ')" = 1
! grep -nE 'nb\("(Discover creators|Requests|S4S schedule)"' app/lib/nav.ts
! grep -n 'NotBuiltYetRoute' app/app/share-for-share/\[section\]/page.tsx
! grep -n 'we dropped it' docs/infloww-screens.md
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
# manual: with two owner logins on a local stack, opt a Creator in on each and walk Discover → request → Accept → schedule at 1440×900 and 390×844, light and dark (PNGs under /tmp only).
# manual: live posting is on by default; set S4S_LIVE_POSTING=0 on the relay to stop every S4S post.
```

## Depends on

- **Phase 0** provides the merged tree, which holds the Settings Panel parts, the nav module with `nb()`, `docs/infloww-parity-matrix.md` and the corrected docs.
- **Phase 1** provides the Agency context helper, which answers Owner, Chatter or Master from the session alone, and the reusable two-agency test fixture that every cross-agency negative case here uses.

Phase 3 is independent of Phase 2. The only shared point is the Alembic head: whichever migration lands second chains onto the other.

## Out of Scope

- Any cross-deployment or public directory, and Infloww's app.infloww.com S4S community. The roadmap forbids both, and ADR-0011 rejects them.
- Importing, scraping or fabricating Creators. The roadmap says to use existing records only.
- Media on S4S posts. Vault media ids belong to one OnlyFans account, and no known body moves media between accounts. The control is shown as Not wired. Superseded by ADR-0015 (W7): media is now copied by its own Creator's session and uploaded by the poster's.
- Operating, or posting on, another Agency's account. ADR-0011 forbids it.
- Fan data of any kind in S4S. It is outside the projection.
- Analytics on S4S performance. The plan lists it as out of scope.
- Chatter or Employee access to S4S. That waits until Phase 4's role permissions grant it.
- Turning live posting on, and any live OnlyFans test. Floor 2 applies, and connectors ticket 06 stays parked for the human.
- A recurring or multi-slot request. The reference shows single scheduled posts, and YAGNI.
- Notifications to the partner owner on a new request. Nothing in the plan asks for them; the Received tab is the inbox.

## Further Notes

ASSUMPTION: the S4S projection is display name, @username, avatar URL, the Primary post's caption, Daily limit and opt-in state, plus a derived `own_agency` flag that reveals only whether the Creator is the caller's own. Rung 2 (ADR-0011 and the plan's field list). Overturned by the owner's own field list, which changes only the projection.

ASSUMPTION: the display fields are entered by the owner in the S4S Setting panel and prefilled from the Creator's nickname. The database holds no @username or avatar for a Creator (`grep -n avatar service/db/models.py` finds only the fan-level columns; the accounts registry meta has nickname only). Rung 5. Overturned if a cached OF identity for the Creator becomes available on the Relay.

ASSUMPTION: foreign Creators are referred to by S4S profile id, never by account id, so the isolation middleware's numeric-segment 403 is never bypassed or loosened. Rung 4. Overturned by nothing in the plan. It is a way to satisfy ADR-0011 without touching the middleware.

ASSUMPTION: Share for Share is owner-only. Chatters get 403, and the nav entries are `chatterHidden`. Rung 3: the Growth links are `chatterHidden`, and `settings_api` refuses Chatter sessions. Overturned when Phase 4's role permissions grant S4S to an Employee role.

ASSUMPTION: a Master session is treated like an Owner session. It passes `assert_account_owned` for any Creator, as everywhere else in the Relay, and it sees the same projection in Discovery, never more. Rung 3. Overturned by the owner wanting S4S closed to the Master.

ASSUMPTION: S4S is reciprocal. Accept creates one slot per side at the request's `slot_at`. The sender consents to its own slot by sending, and the receiver consents by accepting. Both captions are fixed at send time, so each side agrees to the exact text it posts. Rung 4, and the plan's "requested, accepted and scheduled". Overturned by evidence that Infloww's S4S is one-directional.

ASSUMPTION: a request carries one proposed `slot_at`. The Daily limit counts the poster's non-canceled slots on that UTC day. Rung 5. Overturned by evidence of Infloww's request form (the inventory records only the Accept/Skip/Decline buttons).

ASSUMPTION: the request lifecycle is the plan's: skip hides from the receiver only, cancel by the sender only. Added here is `expired`, set lazily once `slot_at` passes, so that no past slot can be accepted. Rung 4. Overturned by the owner's lifecycle; the plan lists this under Needs the human.

ASSUMPTION: opting out cancels only the Creator's own requests and slots. The partner's paired slot reads as "Canceled" (`partner_opted_out`) and is cancelled by its own run at `slot_at`, so no Agency's action writes a row of another Agency's Creator (plan: "scope every … write to the authenticated agency and creator IDs"). Rung 2 plus rung 4. Overturned by the owner's disable policy (Needs the human).

ASSUMPTION: a request stores both projections at send time, and Requests and the schedule show those snapshots, never a live read of the partner's profile. Rung 2 (ADR-0011: exactly one cross-agency read). Overturned by an ADR-0011 amendment allowing a live partner read for parties to a request.

ASSUMPTION: a slot whose run comes 24 hours or more after `slot_at` (executor down) is cancelled as `missed`, and a slot interrupted mid-post is marked `failed` and never re-posted. Rung 4: a missing promo is cheaper to undo than a duplicate or a day-late one. Overturned by an owner preference for late posting.

ASSUMPTION: posting runs through a thin `s4s_post` automation that is queued at accept time and checks the flag, both opt-ins and the slot status at run time. When a slot comes due with the flag off, it is cancelled ("live posting off") rather than held. Rung 5 (it reuses the executor and Auto Post, with no new scheduler) and rung 4 (honest status). Overturned if the owner wants held slots posted later once the flag is turned on.

ASSUMPTION: the live-posting flag is a Deployment-wide Relay environment variable, `S4S_LIVE_POSTING`, default on (changed from off at the owner's request, 2026-10-18), not a per-Agency setting. Rung 3: `ALLOW_ANONYMOUS_ADMIN` and `OF_COTAG_ENABLED` are environment flags read per call. Overturned by a request for per-Agency control.

ASSUMPTION: "Failed" is shown as an Inflowwww extra status beside Infloww's four. Rung 4 (a failed post is never shown as Completed). Overturned by evidence of how Infloww shows a failed S4S post.

ASSUMPTION: S4S rows are kept until their Creator is deleted, with no separate retention window. Rung 5: they hold no fan data and are a few rows per swap. Overturned by an owner retention policy.

ASSUMPTION: the "S4S Setting" panel is a drawer opened from each S4S page header, not a fourth sidebar entry. Rung 2: `docs/infloww-screens.md` §3.6 lists three menu items, and the help center's "S4S Setting" is marked possibly newer (G). Overturned by evidence of a menu entry.

Note (rung 1): the isolation middleware treats any 5–12 digit path segment as a candidate account id (`service/server.py`, `_account_isolation_middleware`). An S4S request or slot id of that length that equals another Agency's account id would be refused 403. With a handful of Agencies the ids stay small for years. No change is made.

## Review

Reviewer: codex (gpt, `model_reasoning_effort=high`), 2026-10-16. Raw outputs: `.scratch/infloww-parity-next-steps/review/phase-03-blind.md`, `phase-03-draft.md`.

Blind call:
- B1 Alternatives (keep S4S dropped, own-agency only, cross-deployment directory, network first with posting off): **reject**. The plan's roadmap decisions and ADR-0011 bind the deployment-local network, and the spec already ships posting off.
- B2 Who may consent (Owner vs Chatter, Chatter account union via `service/chatters.py`, Master): **reject**. Already decided: Chatter 403 on every route, Master as Owner, both flagged ASSUMPTION. The union only widens `assert_account_owned` for Chatters, who never reach S4S.
- B3 Consent shape (opt-in vs visibility, preview, cached withdrawal): **reject**. Separate switches are stories 2–3, the owner sees its own card in Discovery (`own_agency`), and nothing is cached: Discovery is a live query.
- B4 Request rules (duplicates, re-requests, simultaneous answers, Primary post edits, day boundary, whose limit): **partial**. Duplicates, snapshots, UTC day and both-side limits were already decided. Accepted the race: every transition is now a status-guarded update with 409 on zero rows, and Accept guards first, then re-checks, in one transaction (Lifecycle).
- B5 Schema lacks constraints, indexes, audit, retention, downgrade: **reject**. The spec's Schema, Audit and retention lines cover each.
- B6 Publishing failure semantics (retries, missed jobs, partial success): **accept**. The executor retries a raised job (`service/automation_executor.py` `_mark_job_failure`), so a run that dies after posting would re-post. Added the `posting` claim state, `failed` / `interrupted_mid_post` on a retry, and `canceled` / `missed` at 24h past `slot_at`, with tests.
- B7 Delete route takes only a post id, so the posting account must be bound: **partial**. S4S never calls the delete route; Auto Post enqueues `unsend_messages` on the poster's own `account_id` (`service/automations/auto_posts.py:272`). The test now asserts that `account_id`.
- B8 Test seam at the Relay S4S API with a disposable DB: **reject** (agreement). That is seam 1. A multi-agency Chatter is covered by the Chatter 403 cases.
- B9 Falsifiers (agency population, owner consent to fields, newer reference, live post check, missing `service/db` in the workspace): **reject**. Population needs live data (floor 2); fields and lifecycle are already Needs the human in the plan; no newer reference exists locally; live posting is flag-gated; `service/db/models.py` exists at 4c9c7160 (`git show 4c9c7160:service/db/models.py` succeeds) and was only outside the sparse workspace.

Draft call:
- D1 Accept enqueues jobs that run immediately (`enqueue_job` defaults `run_at` to now, `service/automation_executor.py`): **accept**. Jobs now enqueue with `run_at=slot_at`, and the accept test asserts it.
- D2 Requests and schedule return partner projections, a second cross-agency read against ADR-0011: **accept**. The request stores both projections at send; Requests and the schedule return only those snapshots, never a live read. New ASSUMPTION line.
- D3 Opt-out cascade writes the partner Agency's slot: **accept**. The cascade now writes only the opting-out Creator's own rows; the partner slot reads as "Canceled" / `partner_opted_out` and its own run cancels it. ASSUMPTION rewritten.
- D4 Skipped vs sender cancel is contradictory: **accept**. Sender cancel and expiry apply to `pending` and `skipped`; receiver answers apply to `pending` only.
- D5 Story 31 has no test: **accept**. Added cases for a Creator with no `user_accounts` row and a deleted Agency, at the HTTP and `s4s_post` seams.
- D6 Acceptance does not prove the migration reverses: **accept**. `test_s4s_api.py` now runs upgrade, `downgrade -1`, upgrade on the harness temp database via `-x url=`.

needs-human: none beyond the plan's existing S4S policy entry (fields, lifecycle, disable behaviour), which this spec still proceeds on by ASSUMPTION.

### Six hats

Six-hats report, 2026-10-16 (`.scratch/infloww-parity-next-steps/review/six-hats.md`), reconciled as the Adversary brief does.

- Red (phase-03), four tables, a posting automation and a lifecycle built before anyone approved the policy: **reject on constraint**. Plan Phase 3 Work binds the tables, the router and Auto Post publishing behind an off flag. The plan's Needs the human already lists the S4S policy, with "Phase 3 proceeds on its ASSUMPTION lines until vetoed".
- Green (phase-03), ship profiles, Discovery and Requests, and defer the `s4s_post` automation until connectors ticket 06 clears: **reject**. Rung 2: plan Phase 3 Work says "Publishing reuses the Auto Post path … Both actions are behind a flag that is off by default. Acceptance uses mocked relay tests only." The flag already keeps it inert until ticket 06.
- Black (phase-05 `downgrade -2` assumes no newer migration, while Phase 3 can land in any order): **accept** on this side too. The reversibility test now downgrades to the S4S migration's own `down_revision`, not `-1`, so it holds whether Phase 5 lands before or after.
- Yellow (status-guarded writes, `interrupted_mid_post` prevents double posts, Discovery serves snapshots): **accept**, no change.
