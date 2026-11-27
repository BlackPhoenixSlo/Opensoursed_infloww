# Phase 01 — Leak tracker AE tracer: watch, seed, daily probes, roster

**Objective.** On AE, an Agency owner who holds a Tracker key can enrol 3–5 Creators with a consented Leak identity, see each one's seeded Leaks on `/creators/leaks` with a Leak pill and "last checked" that the Removal service's Daily scan Origin probes refresh every UTC day, and delete a Leak watch through a tombstone, after which the service purges it 30 days from the delete request. Every other target stays dark, and the tracer reports probe flap rate and seed precision.

## Problem Statement
An agency today learns about a leaked Creator only when a fan or the Creator says so, then searches by hand, once, and has no memory of what it found: it cannot tell a link that is still up from one that went down, or one that came back. The owner's Removal service can search, but only as a one-off Quick scan with one shared partner key, one 10-per-hour bucket and results anyone holding the slug can read, so it cannot serve several agencies or keep anything per Creator. Nobody has measured whether a daily probe of a known link is stable enough to call it gone, or how many Quick scan hits are really the Creator, and every later Phase's numbers rest on those two.

## Solution
A new item **Leak tracker** appears under Creators, after Custom proxy, only where the deployment, the Agency and the role allow it. The owner pastes the agency's Tracker key once on an owner-only card. Then the owner or an Admin picks "Track a Creator", confirms the handle (read from the live session and marked verified, or typed and marked unverified), adds a display name, up to 5 aliases and optional Instagram and X, ticks the consent box, and saves. The page has the Inflowwww look used elsewhere. Creator names run down the left in the house Creator column, as on Scripts, with the "All Models" tag at the top, selected by default. All Models shows every Creator's Leaks in one list that has a Creator column. Picking a Creator shows that Creator's Leaks in the main pane; there is no side panel. On a phone the column becomes the house Creator dropdown. Within minutes a newly enrolled Creator's entry reads "Found on first scan · N", taken from a Quick scan of the handle. From the next morning, every known link that can be probed is fetched once a day. Each link shows Live, Cached, Gone, Listed or Not checked yet, with a "Came back" badge when a gone link returns, and the Creator's header shows a "last checked" time. The first time each person opens the results, a dialog says they are automated bot scrapes that may be wrong, and that the removal team personally checks every leak before any removal. Tracking can be paused, and deleting a Creator stops it at once and removes the data at the service within 30 days. If the service is down, the page says when it last checked and never makes up a state. The demo keeps the tracker off and never connects out.

## User Stories
1. As the owner, I want the Leak tracker to stay off unless `LEAK_TRACKER_URL` is set and the `LEAK_TRACKER_ENABLED` switch is on, so that no deployment sends a handle anywhere by accident.
2. As the owner, I want the System switches panel to be able to force `LEAK_TRACKER_ENABLED` off but never on, so that a database row cannot turn tracking on where the env did not.
3. As the owner, I want the Agency flag `leak_tracker` read for the active Agency only, so that one Agency's opt-in never turns the tracker on for another through the multi-agency `all` merge.
4. As an Agency owner, I want every `/admin/leaks` route to answer 404 when the Deployment switch, the flag, the key (on every route except setup and key) or the role check fails, so that a hidden page cannot be reached by URL.
5. As a Chatter or Creator role, I want the Leak tracker hidden from my nav and refused by the Relay, so that tracking data stays with the people managing Creators.
6. As a Team Leader, I want the page in my default permissions (in an Agency that has saved its own Team Leader role, the owner ticks the page in the role editor), so that I can see which of my Creators' links are up without asking the owner.
7. As an Agency owner whose agency has roles switched off, I want that never to widen the Leak tracker to every employee, so that turning enforcement off does not leak tracking to Chatters.
8. As an Agency owner, I want the nav item to appear only when `/settings/applied` reports `flags.leak_tracker` true, which needs the Deployment switch, the stored flag and the session's role gate, so that the link never leads to a 404 and an employee session that passes the role gate sees it even though the rest of the Creators group stays hidden from it.
9. As an Agency owner with no Tracker key, I want the page to show only a setup card where I can paste the key, so that I connect once and nothing else pretends to work.
10. As a Team Leader in an agency with no key, I want a single line saying the agency owner has not connected the removal service, so that I know who to ask.
11. As an Agency owner, I want the key checked against `GET /v1/me` before it is stored, refused with a reason if the service rejects it, and refused whenever it belongs to a different Tracker tenant than the one the Agency is bound to, so that a typo never sits there as a broken key and a key swap never strands a watch or a pending delete.
12. As an Agency owner, I want the stored key masked on the card and never sent to the browser in full, so that a shoulder-surfer or a screenshot cannot take it.
13. As an Agency owner, I want the Tracker key kept out of the LLM key list, out of the agency keys form and out of the AI keys tab, so that it is never mistaken for, or billed as, a model key.
14. As an Agency owner whose key the service revoked, I want the page to say "Key no longer valid" and offer the key card, so that I know why the page is empty.
15. As the owner or an Admin, I want every Creator my session can see listed in the Leak roster, with untracked ones marked "Not tracked" and their drill-in offering "Track this Creator", so that enrolment starts from Creators I already manage.
16. As the owner or an Admin enrolling an OnlyFans Creator with a live session, I want the handle and display name filled from the live `me()` and the handle marked verified, so that I search for the right account.
17. As the owner or an Admin enrolling a Creator with no live session or no live identity source (Fansly today), I want to type the handle and see it marked unverified, so that the page is honest about what it searches for.
18. As the owner or an Admin, I want to add up to 5 aliases of at least 4 characters, none a common word from the blocked list and none equal to the handle, so that a weak alias cannot flood the results later.
19. As the owner or an Admin, I want optional Instagram and X handles checked against each site's handle shape, so that a pasted URL or a typo is caught before saving.
20. As the owner or an Admin, I want Save disabled until the form is valid and, on a first enrolment, the consent box is ticked, so that no Creator is tracked without consent.
21. As the owner or an Admin, I want the consent box to read the disclosure with the Removal service's brand from `/v1/me` (and "the removal service" when it gives none), so that I know exactly what leaves the CRM and for how long.
22. As the owner, I want who consented and when stored with the Leak watch, so that the attestation can be shown later.
23. As the owner or an Admin, I want a saved identity kept locally even if the service is down, and pushed by the next sync, so that enrolment never waits on the service.
24. As the owner, I want one Leak watch per (Agency, Creator) and no two Leak watches in an Agency on the same Platform handle, so that two Agencies tracking one Creator never share rows and one Agency never tracks the same handle twice.
25. Moved to Phase 4 (its story 49): the rename rule and its one-time note.
26. As the owner, I want the CRM to mint each Leak watch's `watch_id` before any call, so that a tombstone always names the exact watch and a late retry can never hit a Creator added again.
27. As the owner or an Admin, I want a Tracking switch per Creator that pauses scanning and keeps every row, so that I can stop a Creator without losing history.
28. As the owner, I want a watch reported paused when its Creator is switched off, its Agency flag is off, or the Creator is deactivated, so that no scan runs for a Creator the agency stopped using.
29. Moved to Phase 4 (its story 50): the kill switch pushing paused. Here a Deployment switch that reads off makes the watch sync send nothing.
30. As the owner or an Admin, I want "Delete" in a Creator's drill-in to tell me tracking stops now and the service removes the data within 30 days, and to ask me to confirm, so that a delete is never a misclick.
31. As the owner, I want a delete to write a Leak watch tombstone before it drops the row, and a Relay job to retry `DELETE /v1/watches/{watch_id}` until it gets a 2xx, so that a service outage cannot strand a watch.
32. As the owner, I want Creator Remove to tombstone every Agency's Leak watch for that Creator, and an Agency unlink to tombstone only that Agency's, so that the service never keeps tracking a Creator the CRM forgot.
33. Moved to Phase 4 (its story 51): orphan-watch logging.
34. As a Team Leader, I want the Leak roster and the All Models list to cover only the Creators my session can see, so that the tracker does not widen my Creator scope.
35. As a Team Leader, I want the Leak roster to be the house Creator column on the left, with the All Models tag on top and one entry per Creator. Each entry shows one count line: Leaks up now and New today, or "Found on first scan · N", "Not checked yet", "Paused since <date>" or "Not tracked". A Creator's drill-in header shows Up now (with a cached count), Gone, Listed, New today, Tracking on or "Paused since <date>", and Last checked (or the next check time). So that I can scan many Creators at a glance in the look I already know.
36. As a Team Leader on a phone, I want the house Creator dropdown, with All Models on top, in place of the column, and the Leak lists as stacked rows with no sideways scroll, so that I can check the tracker away from my desk.
37. As a Team Leader, I want to pick a Creator in the Leak roster (or open `?open=<account_id>`) to get that Creator's drill-in in the main pane, never a side panel or sheet, and to pick All Models to go back, so that I can share a link to one Creator.
38. As a Team Leader, I want the drill-in to list each Leak with its Leak site, Leak kind icon, title, Leak pill, Came back badge, first seen date and a short timeline of its events, so that I can see what happened to each link.
39. As a Team Leader, I want a pills legend beside both Leak lists (All Models and drill-in), so that Cached and Listed are explained where they appear.
40. As a Team Leader, I want each Leak's URL to open in a new tab with no referrer, so that a pirate site never learns it was opened from our CRM.
41. As a Team Leader, I want no thumbnails or media in this Phase's tracker, and the CRM never storing leaked content in any Phase, so that the tracer stays text-only. (Phase 2's Google view adds view-time previews behind a switch that is off by default; Phase 2 stories 47-57.)
42. As a Team Leader, I want a Creator whose first scan has not finished to show "Not checked yet" and the next check, and a first scan's Leaks to read "Found on first scan" rather than "new", so that a fresh enrolment does not look like a leak spike.
43. As a Team Leader, I want the page, when the service is unreachable, to show the last good copy marked "last checked <time>" or, with none, the local Creators marked not reachable, so that the page never invents a state.
44. As the owner, I want the Removal service to keep a Tracker tenant per Agency and issue keys under it with an owner CLI that prints the key once and stores only its hash, so that a leaked database never yields a key.
45. As the owner, I want the Tracker API to authenticate with `Authorization: Bearer <key>` only and to answer 401 for unknown or revoked keys, so that a key never sits in a URL or a log line, while the Quick scan keeps its `?key=`.
46. As the owner, I want every Tracker API read and write scoped to the key's Tracker tenant, so that one Agency can never read another's watches or Leaks by guessing an id.
47. As the owner, I want a per-tenant Creator limit (default 5, set by the CLI) to refuse a new watch with `creator_cap`, so that the tracer cannot grow past its pilot before Phase 2's caps exist.
48. As the owner, I want a new watch seeded by one private run of the Quick scan's candidate step (its Google search and Mega lookup, with no share row, profile, media or alias discovery), so that enrolment costs at most one scan and never writes a tracked Creator into the public Quick scan tables.
49. As the owner, I want the seed to admit as a Leak only a result that passes the host rules and whose URL names the handle or a strong alias (or, for Mega, whose aggregator match came from the handle or a strong alias, never a name), keep title-only results as hidden Pending hits, and record each Leak's Leak source and `seen` event, so that the page starts with confirmed links only.
50. As the owner, I want a Leak keyed by the shared URL key rules (the fragment kept for link-only hosts), its Leak site set to the registrable domain, and its Leak kind set from the host rules, so that the same link never shows twice and Mega, Telegram and file-host links are Listed, never probed.
51. As the owner, I want the service to Origin probe every probe-able Leak of every unpaused watch at most once per UTC day, through restarts and the first probe after a seed, fetching each URL key once even when several tenants track it, so that the daily cost stays at plain HTTP and one day can never yield two dead probes.
52. As the owner, I want a probe to classify 404, 410 or a removal page as dead, a block page as blocked, a 200 as live and anything else as unknown, using the rules the laptop leak tools already use, so that the service and the tools agree.
53. As the owner, I want Origin status to turn `gone` only after 2 dead probes in a row, blocked and unknown neither breaking nor extending the streak, and to turn back `live` on the next live probe, so that one bad fetch never calls a link gone.
54. As the owner, I want routine probes to overwrite one Probe state row per Leak and only an Origin status change to append a Leak event, so that history stays small and honest.
55. As the owner, I want each watch's Daily scan recorded per UTC day with its start, finish and outcome, so that "last checked" and next-check are facts, not guesses.
56. As the owner, I want a watch paused by the CRM to get no new seed or probes while every row stays readable, and running work to finish, so that a pause is safe at any moment.
57. As the owner, I want `DELETE /v1/watches/{watch_id}?requested_at=` to hide the watch from every read at once, stop its scans, record `purge_after` 30 days after the CRM's original request (clamped to the watch's life), remember an id it has not seen yet so a late first PUT of it is refused, and answer 204 even when repeated, so that the CRM's retries are safe.
58. As the owner, I want tracker data in its own database, apart from the Quick scan tables, so that Quick scan retention never touches it and a purge can remove everything.
59. As the owner, I want `tracker report` to print, per tenant, plain counts: probes run, first-dead observations, flaps (a single dead probe followed by live), the flap rate with its denominator, and the admitted and pending seed counts, so that I can read the 2-probe rule and seed precision as numbers.
60. Moved to Phase 4 (its story 52): the Demo tracker. Here the demo ships with the tracker off, its write routes locked, and a test proving no tracker call leaves the box.
61. As the owner, I want `leak-check.sh` to refuse a public replay that carries the Removal service's brand or domain, a private leak-stack repo name or path, or a Tracker key, so that the private service never leaks through public-sync.
62. As the owner, I want the CRM's tracker copy, docs and code to name only "the removal service", so that the public tree stays generic.
63. As the owner, I want the service to purge a deleted watch, its Leak identity and every row keyed by its `watch_id` once `purge_after` passes, on a daily job and on demand with `tracker_cli purge`, so that the 30-day promise holds from the first AE delete and never waits on a later Phase.
64. As the owner, I want deleting an agency user to tombstone and land every Leak watch delete of that Agency before the user row goes, and to be refused while any of them is still pending, so that the user cascade never drops the Tracker key a pending DELETE needs.
65. As the owner, I want each dead run's first dead probe time kept as `dead_since` on Probe state and copied onto the gone event, so that later Phases can date a gone spell from the day it started.
66. As a Team Leader, I want All Models selected when I open the page, showing the Leaks of every tracked Creator my session can see in one list, newest first seen first, with a Creator column and the drill-in's pill, Came back, link and no-media rules, so that I see the whole Agency before I pick one Creator.
67. As anyone who can see the Leak tracker's results, I want a Leak disclaimer dialog the first time I open them. It says the results are automated bot scrapes of Google, Mega and pirate sites, that some may be wrong, and that {brand} (or "the removal team") personally checks every leak before any removal. So that I never take a listed link for a confirmed leak.
68. As that person, I want "Got it" (or closing the dialog any other way) to dismiss it for me for good in that browser, with no Relay call, so that it informs me once and never nags.
69. As a demo visitor, I want the same Leak disclaimer with no demo or role exception, so that the demo shows what a client sees. Phase 4's Demo tracker is what turns the demo page on.

## Implementation Decisions
- **Owns.** CRM repo (this tree):
  - New `leak_tracker` (Relay): Tracker gates, Tracker API client, local read cache, watch sync job, tombstone job, the paused-bit rule, and `drop_watches` for the Remove and unlink hooks.
  - New `leak_tracker_api` (Relay): the `/admin/leaks` router.
  - `db.models` plus one Alembic revision: `LeakWatch` and `LeakWatchTombstone`.
  - `runtime_switches`: `LEAK_TRACKER_ENABLED`.
  - `settings_schema`: `leak_tracker` added to `FLAGS`, and `/creators/leaks` added to the Team Leader defaults.
  - `settings_api`: the effective flag.
  - `permissions`: the `/creators/leaks` page entry, `/admin/leaks` in `UNMAPPED`, and `leak_page_granted` (read through `leak_tracker.page_on`).
  - `tenant_keys`: the non-LLM provider id `leak_tracker`.
  - `accounts_admin_api.admin_accounts_remove`, `auth.admin_revoke_user_account` and `auth.admin_delete_user`, which call `leak_tracker.drop_watches` (the user delete also calls `leak_tracker.land_tombstones`, see CRM jobs).
  - `server`: two `_periodic` registrations.
  - `docker-compose.yml`: the relay's `environment:` passes `LEAK_TRACKER_URL` and `LEAK_TRACKER_ENABLED` through (`${…:-}`, empty by default), so an AE `.env` or override can reach the Relay.
  - `tenant_keys_api`: its LLM key writes refuse the provider `leak_tracker`.
  - App: the `/creators/leaks` page on `PageFrame` with `creators` (the house `CreatorRail` → `CreatorColumn`, as `growth/ScriptsPage.tsx` uses it, with `all: {pick, label: "All Models"}`), new `components/leaks/LeakTracker` (All Models list, drill-in, setup card, delete dialog), new `components/leaks/LeakDisclaimer` (the first-open `IfModal`), `components/of-manager/CreatorColumn` (an optional per-entry count line, passed like the S4S variant's `marks`), `components/leaks/IdentityForm` with the reducer `leakIdentityForm.ts`, `components/leaks/leakView.ts` (pure label and time helpers), `lib/nav` (Creators group item; the group's `chatterHidden` moves onto its two existing children, so the group draws for an employee session only when the Leak tracker item survives), `lib/roles` (Team Leader), `lib/appliedSettings` (`FeatureFlag` gains `leak_tracker`), `components/settings/PermissionEditor` (page href).
  - Demo: `demo/routes` LOCKED entries for every `/admin/leaks` write route, and new `demo/tests/test_leak_tracker_off.py`. The tracker stays off in the demo; Phase 4 adds the Demo tracker.
  - Ops: `.claude/skills/public-sync/leak-check.sh` rules (an ops path that never replays, so the brand may sit there literally).
- **Owns.** Removal service repo (built there, specified here): new `tracker_db` (its own SQLite file), `tracker_api` (the `/v1/` handler joined to the existing request handler's dispatch), `tracker_seed`, `tracker_probe` (Origin probe and Probe state, with the laptop leak tools' status mapping, blocked-page detection, removal-page markers and `url_key` copied in under the repo's vendoring convention), `tracker_scheduler` (a daemon thread like the retention loop), `tracker_purge` and `tracker_cli`. The laptop leak tools are only a source of copied rules in this Phase; nothing is built in them.
- **Interfaces (CRM Relay).** Every route is under `/admin/leaks` and first runs `leak_tracker.require_gates(need_key=…)`, which answers 404 when any gate fails:
  - `GET /setup` (no key needed) → `{key: "missing"|"set"|"invalid", masked: str|null (owner only), is_owner, can_write, brand: str|null}`.
  - `PUT /key` (owner session only, no key needed) `{key}` → checks with `/v1/me` and stores only on 200; 422 "Key not accepted" on 401; 503 on unreachable, nothing stored. The first accepted key binds the Agency to its `tenant_id` in `leak_tracker_tenant`. A later key whose `/v1/me` names another tenant is always refused with 422 "Key belongs to another tracker account"; the binding never moves in this Phase (Phase 4 adds the one rebind rule). An empty key clears it, refused with 409 while a tombstone of that Agency is pending.
  - `GET /roster` → `{rows: [...], untracked: [{account_id, name}], stale: bool, fetched_at}`. Rows merge local `leak_watch` with `/v1/creators`. The app builds the Leak roster from `rows` plus `untracked`.
  - `GET /all?cursor=` → `{leaks: [{account_id, …}], next_cursor, stale, fetched_at}`. This is the All Models list. It calls `/v1/leaks` with the `watch_id` of every `leak_watch` whose Creator the session can see, maps each `watch_id` back to its `account_id`, and makes no call when that set is empty.
  - `GET /watches/{account_id}` → `{tracked, identity, suggested, synced, leaks, next_cursor, stale}`. For a Creator not tracked yet, `suggested` holds the live `me()` handle and name, marked verified, or is empty, marked unverified.
  - `PUT /watches/{account_id}` (Owner/Admin) takes the identity and `consent` (required true on create) → `{synced: bool}`. 409 when another row in the Agency has that Platform handle.
  - `POST /watches/{account_id}/tracking` (Owner/Admin) `{on}`.
  - `DELETE /watches/{account_id}` (Owner/Admin) writes the tombstone, then drops the row and wakes the tombstone job.
  - The `account_id` in the path must be a Creator of the resolved Agency that the session can see, or the route answers 404.
- **Interfaces (CRM gates).** The four gates are evaluated in this order:
  1. Deployment: `LEAK_TRACKER_URL` set (https, or loopback http only under tests or demo) and `runtime_switches.on("LEAK_TRACKER_ENABLED")`. The switch is `off_only`, default off, parsed truthy.
  2. Agency: exactly one Agency context resolves for the request (several → 404), and its stored `flags.leak_tracker` is true.
  3. Key: a `leak_tracker` key is stored for that Agency.
  4. Role: `permissions.leak_page_granted`, read through `leak_tracker.page_on`. An owner session passes. An employee passes only if its role is the built-in Owner or Admin, or its role's permissions grant `/creators/leaks` (the Team Leader default does). A missing role, or `enforce: false`, never grants it.
  - Writes also need the owner session or the Owner/Admin role. `PUT /key` needs the owner session.
- **Interfaces (CRM settings).** `/settings/applied` reports `flags.leak_tracker` as gate 1 AND gate 2 AND gate 4 for this session (not gate 3, so a keyless Agency still reaches the setup card or the Team Leader line). `_merged` reports it false. The nav item reads only this flag, never `permissions.pages`, because a `pages: null` session (enforcement off) would otherwise show a link the Relay refuses. The Team Leader default reaches only Agencies with no saved Team Leader role object (`permissions._role`); elsewhere the owner grants the page in the role editor. The flag is written through the existing `flags` settings tab, as `fansly_manager` is: no new toggle UI.
- **Interfaces (CRM jobs).** Both jobs make no call while `LEAK_TRACKER_URL` is unset, and both skip Agencies with no key.
  - `leak-watch-sync`: hourly, first run at 60 s. It pushes rows whose identity was never pushed (`synced_at` null) or whose computed paused bit differs from `synced_paused`, and every row once per UTC day. It does not refresh identities from `me()` and does not list `/v1/creators` (Phase 4 adds the rename rule and orphan logging). Any call answered 410 `watch_deleted` (the sync's PUT or a drill-in read) deletes that `leak_watch` row with no tombstone, so the Creator shows as not tracked and a re-enrol mints a new `watch_id`.
  - `leak-watch-tombstones`: every 10 minutes. It retries each tombstone, deletes it on a 2xx, and otherwise bumps `attempts` and stores `last_error`.
  - Computed paused = `not on` OR the Agency flag is off OR the Creator is deactivated. While the switch reads off (env unset or DB forced off), the sync job makes no call at all, so the kill switch never creates a watch or sends an identity; pushing paused on the kill switch is Phase 4's. The tombstone job still lands DELETEs while the URL is set.
  - The tombstone job sends each DELETE with the Agency's current key only while that key's tenant equals the tombstone's `tenant_id`; otherwise it keeps the tombstone with `last_error: tenant_mismatch`.
  - Agency-user delete (`auth.admin_delete_user`, the only `delete(User)` in `service/`, `service/auth.py:699`): before the user row goes, `drop_watches` tombstones every `leak_watch` of that Agency, then `land_tombstones(agency_user_id)` runs the tombstone job for that Agency inline, one DELETE each with a 15 s timeout. If any tombstone of the Agency is left, the route answers 409 "Leak watch deletes are still pending at the removal service; try again later" and deletes nothing more, so the key and the binding stay for the regular job. Otherwise the user delete goes ahead, and the cascade drops the key and `leak_tracker_tenant`.
- **Interfaces (CRM read cache).** `leak_tracker` keeps the last good response of each read per (Agency, path) in process memory. When the service is unreachable or answers 5xx, it serves that copy with `stale: true` and its `fetched_at`; with no copy, the roster lists local rows with `reachable: false`. A key save drops every cached copy of that Agency, and a delete drops that watch from them. The UI shows the row's `last_checked_at`, never `fetched_at`, as "last checked". A 401 from the service marks the Agency's key `invalid` until a new key is saved.
- **Interfaces (CRM app).**
  - `leakIdentityForm.ts` exports `INITIAL_FORM`, the `Action` union (`adopt`, `edit`, `addAlias`, `removeAlias`, `setConsent`, `saveFailed`), `leakIdentityFormReducer`, `validate`, `canSubmit` and `buildPayload`.
  - `validate` checks:
    - the handle: OnlyFans/Fansly shape, 2–64 characters `[A-Za-z0-9_.-]`;
    - aliases: at most 5, each 4–64 characters, never in `BANNED_ALIASES`, case-insensitively distinct and different from the handle;
    - Instagram: 1–30 characters `[A-Za-z0-9_.]`;
    - X: 1–15 characters `[A-Za-z0-9_]`;
    - the display name: at most 64 characters.
  - Consent is required when `tracked` is false. A verified handle is read-only in the form; clearing it to type another makes it unverified.
  - `leakView.ts` maps pills to labels, and times to "Today 06:12" / "Next check tonight" in the viewer's zone.
- **Schema (CRM).**
  ```
  leak_watch(id pk, agency_user_id → users.id CASCADE, account_id → accounts.id CASCADE, watch_id text unique not null,
             on bool default 1, platform text, username text, verified bool, display_name text(64),
             aliases_json text default '[]', instagram text null, x text null,
             consent_at datetime not null, consent_by text not null,
             synced_at datetime null, synced_paused bool null, created_at, updated_at,
             unique(agency_user_id, account_id), unique(agency_user_id, platform, username))
  leak_watch_tombstone(watch_id text pk, agency_user_id text not null, account_id text not null, tenant_id text not null,
                       requested_at datetime not null, attempts int default 0, last_error text null)
  leak_tracker_tenant(agency_user_id pk → users.id CASCADE, tenant_id text not null, bound_at datetime not null)
  ```
  `agency_user_id` and `tenant_id` on the tombstone pick the key for the DELETE and check it still names the same tenant; `account_id` lets Phase 4's re-enrol find it. Phase 4 adds `leak_watch.identity_note` as an additive column. The Tracker key is a `user_llm_keys` row with provider `leak_tracker`. That provider id is accepted by `tenant_keys.get_key`/`set_keys` through a separate constant and is never in `TENANT_KEY_PROVIDERS`, the key overview or the LLM forms.
- **Schema (Removal service, its own `tracker_db` file).**
  ```
  tenants(tenant_id pk, label, creators_max int default 5, created_at)
  tenant_keys(key_hash pk sha256, tenant_id, issued_at, revoked_at null)
  watches(watch_id pk, tenant_id, account_id, platform, username, verified, display_name, aliases_json, instagram, x,
          paused, paused_at null, created_at, updated_at, seeded_at null, deleted_at null, purge_after null)
          unique(tenant_id, account_id) where deleted_at is null
  leaks(leak_id pk, watch_id, url_key, url, leak_site, kind, title, created_at, unique(watch_id, url_key))
  leak_events(id pk, leak_id, at, type, data_json)          -- append-only; P1 types: seen{source, first_scan}, status{from,to,dead_since}, google_seen
  probe_state(leak_id pk, last_probe_at, last_live_at null, consecutive_dead, last_status, origin_status, probes, first_dead, flaps, dead_since null)
  deleted_ids(watch_id pk, tenant_id, deleted_at)          -- an unseen id that was deleted, or a purged watch; kept while the tenant row exists
  pending_hits(watch_id, url_key, url, title, source, seen_at, unique(watch_id, url_key))
  daily_scans(watch_id, day, started_at, finished_at null, outcome, primary key(watch_id, day))
  ```
  Derived fields (`first_seen_at`, `last_up_at`, `gone_at`, `came_back_at`, `gone_count`) are computed from `leak_events` and `probe_state`, never stored.
- **Contracts (Tracker API v1).** All requests are JSON over HTTPS with `Authorization: Bearer <key>`. There is no CORS on `/v1/`. Unknown body fields are ignored, and readers ignore unknown response fields, so later Phases only add fields. 401 means an unknown or revoked key; 422 a validation failure with `{error, field}`.
  - `GET /v1/me` → `{tenant_id, label, brand: str|null, contact_url: str|null, creators_max, creators_used}`. The brand and the URL come from the service's env, never from the CRM's git.
  - `PUT /v1/watches/{watch_id}` `{account_id, platform, username, verified, display_name, aliases, instagram, x, paused}` → `{watch_id, created, seeded}`. It creates the watch or updates it. 409 `{error: "account_taken", watch_id}` when another live watch holds (tenant, account_id). 409 `{error: "creator_cap", creators_max}`. A PUT, and every read naming a watch_id that is deleted, purged or in `deleted_ids`, answers 410 `{error: "watch_deleted"}`. This is the one status for a deleted id; later Phases refer to it. A PUT never revives a deleted id; Phase 4's restore works by re-enrolment of the account.
  - `DELETE /v1/watches/{watch_id}?requested_at=<ISO>` → 204 for any id in or outside the tenant, repeated or not. `purge_after` = `requested_at` + 30 days, where `requested_at` is clamped to lie between the watch's `created_at` and now, and taken as now when absent. This is the one clamp rule; later Phases refer to it. An id no tenant holds is written to `deleted_ids` for the caller's tenant, so a later PUT of it answers 410; an id another tenant holds is a no-op.
  - `GET /v1/creators` → `{as_of, creators: [{watch_id, account_id, paused, paused_since, seeded, last_checked_at, next_check_at, counts: {live, cached, gone, listed, not_checked, new_today, found_on_first_scan, came_back_30d}}]}`.
  - `GET /v1/creators/{watch_id}` → that one row.
  - `GET /v1/leaks?watch_id=…&watch_id=…&cursor=&limit=` (1–500 ids, limit ≤ 200; otherwise 422) → `{leaks: [{watch_id, …the per-watch leak fields except `events`}], next_cursor}`, newest `first_seen_at` first, then `leak_id`. It lists Leaks of the named live watches of the key's tenant only. Unlike every other read, it skips a deleted, purged, unseen or foreign id instead of answering 410, because one stale id must not blank the All Models list; the per-watch reads and the sync still answer 410.
  - `GET /v1/creators/{watch_id}/leaks?cursor=&limit=` (limit ≤ 200) → `{leaks: [{leak_id, url, leak_site, kind, sources, title, pill, came_back, found_on_first_scan, first_seen_at, last_up_at, last_probe_at, origin_status, events: [{at, type, data}]}], next_cursor}`.
  - `pill` is the service's single derivation: one of `live`, `cached`, `gone`, `listed`, `not_checked`.
- **Contracts (key format).** `ltk_` followed by 40 base62 characters. `leak-check.sh` matches `ltk_[A-Za-z0-9]{32,}` under the `secret` rule.
- **Pill rule (service).**
  - A link-only Kind is `listed`, unless its last origin-status change is to `gone`; then the rules below read it as gone (Phase 2's Mega `deleted` rule writes such changes, `phase-02-leak-tracker-discovery-and-budget.md` Mega lookup; nothing in this Phase does).
  - With no settled probe yet, the pill is `not_checked`.
  - `gone` with Google visibility seen is `cached`.
  - `gone` is `gone`; `live` is `live`.
  - `blocked` and `unknown` keep the last settled pill, or `not_checked` when there is none.
  - The Came back badge shows while the pill is `live` and a `status{gone→live}` event is in the last 30 days.
  - In this Phase, Google visibility comes only from the seed, so a Google-seeded Leak that dies reads Cached until Phase 2's Google pass runs.
- **Seed (service).**
  1. On create, `tracker_seed` runs the Quick scan's candidate step in-process, factored out of the Quick scan handler: the wide Google search over the handle and the watch's aliases and the Mega aggregator lookup, without SSE, outside the partner bucket, with alias discovery off and no names passed to the aggregator. It writes no Quick scan row or share slug and runs no profile, avatar or media step. It reads no earlier Quick scan: stored rows keep one URL per host and at most 80 results, so they are not a Leak source.
  2. Leaks are built from the per-URL items, not the per-host summary rows: Google items become `google_web` / `page` (or the host rules' link-only Kind) with a `google_seen` event; Mega items become `mega_index` / `mega`. No Phase 1 Leak has Leak source `site_search`.
  3. A Google item is admitted only when it passes the host rules (official and excluded hosts are never Leaks) and its URL contains the handle or a strong alias (at least 5 characters), compared case-insensitively with `_`, `.` and `-` removed; a needle shorter than 4 characters after that admits nothing. A Mega item is admitted only when its aggregator match came from the handle or a strong alias. Title-only results go to `pending_hits`. The display name never admits anything.
  4. The seed opens that UTC day's `daily_scans` row and runs its first probe pass under it, so a watch enrolled after `TRACKER_DAILY_AT` is not probed again that day. `seeded_at` is set even when the scan found nothing.
  5. A failed seed (including the Google search being unavailable) leaves the watch `not_checked`, finishes the day's row `failed`, and is retried by the next daily pass.
- **Daily pass (service).**
  - `tracker_scheduler` wakes every minute. After `TRACKER_DAILY_AT` (default 04:00 UTC), it starts a `daily_scans` row for each unpaused, undeleted watch that has none for the day; for a watch with no `seeded_at` it runs the seed first. It probes each distinct `url_key` once, writes `probe_state` and status events, and finishes the row with outcome `ok` or `failed`.
  - A restart resumes rows that have no `finished_at`. A `url_key` already fetched that UTC day is never fetched again; its result applies to every Leak with that key.
  - A probe is a GET over http or https only, at most 8 concurrent per host, 15 s in all, at most 5 redirects, at most 256 KB of body read. It refuses loopback, private, link-local and the service's own addresses, checked after DNS and on every redirect, and records such a Leak `unknown`.
  - `next_check_at` is the next `TRACKER_DAILY_AT`.
  - `dead_since` is set to the probe time when `consecutive_dead` goes from 0 to 1 and cleared by a live probe; blocked and unknown probes leave it. The `status{to: gone}` event copies it into `data.dead_since`.
- **Purge (service).**
  - `tracker_purge.run(now) -> {watches, deleted_ids, errors}` runs once per UTC day from `tracker_scheduler`, and on demand from `tracker_cli purge [--dry-run]`. It is idempotent and batched like the Quick scan's retention loop; a row that fails is logged, skipped and retried on the next run.
  - A watch purges when `deleted_at` is set and now ≥ `purge_after`. In one transaction per watch it deletes the watch row (its Leak identity) and every row keyed by its `watch_id`: `leaks` with their `leak_events` and `probe_state`, `pending_hits` and `daily_scans`, then every table on `tracker_purge.WATCH_TABLES`, a list of (table, column) pairs that later Phases extend with their own watch-keyed tables. It writes the `watch_id` to `deleted_ids` with `deleted_at` = now, so a late PUT still answers 410.
  - `deleted_ids` rows are never pruned while their tenant row exists: they hold only opaque CRM-minted ids, no Creator data, so a reinstated tenant's sync still meets 410 and cannot re-create a purged watch.
  - It never touches the Quick scan tables or the tenant rows.
- **Measures.**
  - `tracker_cli report` prints plain counts per tenant: watches, Leaks by pill, probes, first-dead observations, flaps, the flap rate as flaps / first-dead observations with a settled next probe (both numbers printed), and seed counts (admitted, pending). No bound and no sample file.
  - Seed precision: the owner counts the real Leaks among every admitted Leak on the AE drill-ins and records real / admitted.
  - The ticket's line is a measured flap rate under about 2 % (ticket 02). The tracer records the counts with their denominators, not a verdict: the 2-probe rule and the seed rule hold as defaults, and `report` keeps counting through Phase 2's pilot, which reads them again.
  - The CLI also covers `tenant add <label>`, `tenant cap <tenant_id> <n>` and `key issue <tenant_id>` (prints the key once) and `purge [--dry-run]` (prints what is due, then purges it unless `--dry-run`).
- **Copy.** UI copy says "removal service" and takes `{brand}` from `/setup` where shown. The consent text is ticket 10's disclosure verbatim, with `{brand}` filled in, or "the removal service" when no brand comes back.
- **Page layout (wayfinder ticket 08, owner 2026-11-27).**
  - Left: the Leak roster, the house Creator column. All Models is on top and is the default selection. Below it come the session's Creators, tracked and untracked, each with the story 35 count line.
  - Main pane, All Models: the combined Leak list (story 66) with columns Creator, Leak site, Leak kind icon, title, Leak pill with Came back, and first seen. Each row's Creator name selects that Creator. Phase 2 puts the Today strip above it.
  - Main pane, one Creator: the drill-in, with the header counts (story 35), Tracking switch, Delete, the Leak list with timelines, and the legend. For an untracked Creator it shows "Track this Creator" (Owner/Admin) or "Not tracked" (Team Leader). Phase 3 adds the Removal area here.
  - `?open=<account_id>` selects a Creator, and picking All Models clears it. An `open` value outside the session's Creators falls back to All Models.
  - Phone: `CreatorRail`'s own pattern, the `IfCreatorSelect` dropdown with All Models on top in place of the column. The lists become stacked rows.
  - No side panel, sheet or roster table. Prototype: variant D (`.scratch/leak-tracker/prototype/inflowwww.html`).
  - Selection is the one URL value `open`. The disclaimer and the delete dialog are each a single boolean (`useState`), so the page has no coupled state that needs a reducer (repo CLAUDE.md rule).
- **Leak disclaimer (app only).**
  - `LeakDisclaimer` opens an `IfModal` on the first render of the tracker's results view (key `set`) for a person whose dismissal is not stored. It never opens on the setup card or the Team Leader no-key line, and it does not open before `useEmployeeKey()` resolves.
  - Copy (generic in git):
    - Title: "These results are automated".
    - Body: "Every link here was found by bots that scrape Google, Mega and pirate sites. Some may be wrong or not about this Creator. {brand} personally checks every leak before any removal starts."
    - `{brand}` comes from `/setup`, or "The removal team" when null.
    - One button: "Got it".
  - Any close (Got it, Esc, the overlay, the close icon) writes `localStorage["chatterly:leak_disclaimer_seen:<employee key>"] = "1"`. It makes no Relay call. A storage error leaves the dialog to show on the next open.
  - No role, Agency or demo exception.
- **Demo.**
  - The demo keeps the tracker off: `LEAK_TRACKER_URL` unset, `flags.leak_tracker` false, no key. Every `/admin/leaks` route answers 404 from gate 1.
  - `PUT /admin/leaks/key`, `PUT|POST|DELETE /admin/leaks/watches/*` are LOCKED anyway, because `test_routes.py` fails on an unclassified write route. The demo never runs the two jobs.
  - Phase 4 adds the Demo tracker (fixtures, seed rows, every pill state).
- **Leak-check.**
  - New rule `removal service`: the brand and its domain (literal, in the ops-only script), the private leak-stack repo names and their home paths.
  - The `secret` rule gains the key prefix.
  - Levels: `fail` for public, `report` for AE (whose tree carries `.scratch`), `off` for strip.

## Testing Decisions
- **Seam 1 — the Relay's `/admin/leaks` HTTP surface.** These are plain service test scripts (`_harness`, `_agency_fixtures`) driving the FastAPI app, with the Tracker API faked by an `httpx.MockTransport` that records calls.
  - `test_leak_tracker_gates`: each gate off answers 404 on every route; the `all` merge never enables it; the role table (owner, Admin, Team Leader, Chatter, Creator, a custom role with and without the page, enforcement off); setup and key exempt from gate 3; the applied flag.
  - `test_leak_tracker_api` also covers `GET /all`: it passes only the session-visible watches' ids, maps `watch_id` to `account_id`, makes no call for an empty set, and serves a stale copy.
  - `test_leak_tracker_api`: key check-then-store, masked status, 401 → invalid; a second key of another tenant refused with 422 even with no watch or tombstone; a drill-in read answered 410 drops the row with no tombstone; clearing the key refused while a tombstone is pending; enrol with and without consent, with `consent_by`/`consent_at` stored; the disclosure brand from `/v1/me` and the fallback; verified versus unverified suggestion; 409 on a duplicate handle; save while the service is down → `synced: false`; the roster merge; a Team Leader's roster lists only the Creators the session can see; stale-cache and not-reachable reads, and the cache dropped on key save and delete; the path `account_id` outside the Agency → 404.
  - `test_leak_watch_sync`: pushes only dirty rows or a changed paused bit, then the daily full push; paused for toggle off, flag off and deactivated; a switch that reads off makes no sync call while a pending tombstone still lands; a PUT answered 410 drops the row with no tombstone and the Creator reads not tracked; the daily pass makes no `me()` call and no `/v1/creators` call; no call at all with the URL unset.
  - `test_leak_watch_tombstone`: the tombstone exists before the row drops; retries until 2xx; the DELETE carries the original `requested_at`; a tenant mismatch keeps the tombstone; Remove fans out to every Agency; unlink touches one Agency; a late retry names the old `watch_id` after a re-enrol; an agency-user delete tombstones and lands every watch first, and answers 409 with the user, key and binding kept while one is pending.
  - `test_llm_tenant_keys` gains: the LLM key write routes refuse provider `leak_tracker`, and the key overview never lists it.
  - Prior art: `test_llm_tenant_keys.py` (MockTransport, key rows), `test_s4s_api.py` (`_every_route` refusal sweep, identity copy), `test_agency_notifications.py`, `test_role_enforcement.py` (route tables).
- **Seam 2 — the pure reducer** `leakIdentityForm.ts`, with vitest tables in `leakIdentityForm.test.ts` (house rule; template `fanDrawerForm.ts` and its test): validation per field, the alias limit and banned words, consent gating `canSubmit` on create only, and the `buildPayload` shape. `leakView.test.ts` covers the label and time helpers.
- **Seam 3 — the page,** `app/app/creators/leaks/page.test.tsx`, with the relay mocked as in `app/app/creators/proxy/page.test.tsx`: the setup card for the owner versus the Team Leader line; the Leak roster as the Creator column with All Models on top and selected by default, entry count lines (including "Not tracked"), and the All Models list's Creator column; picking a Creator, and `?open=`, showing its drill-in in the main pane (no dialog or sheet role), with an `open` outside scope falling back to All Models; at phone width, the Creator dropdown with All Models in place of the column and no horizontal overflow; pills and legend; links with `rel="noreferrer noopener"` and `target="_blank"`; the stale banner; the delete dialog calling DELETE. `lib/nav.test.ts` covers the item's placement, flag and permission. `components/leaks/LeakDisclaimer.test.tsx` (prior art: `VaultProPage.test.tsx`'s `vaultProOnboarding` cases) covers: the dialog on first open of the results view with the brand and with the fallback; none on the setup card; Got it and Esc each store the per-Employee key and the dialog stays shut on remount; another Employee key still sees it; no fetch on dismiss; a throwing `localStorage` still renders the page. There is no Relay test for the flag, because it never reaches the Relay. A component test covers it, since it is a single boolean and gets no reducer.
- **Seam 4 — the demo,** `demo/tests/test_leak_tracker_off.py` (pytest, prior art `test_guards.py`): it boots the demo relay with guards and asserts `flags.leak_tracker` reads false in `/settings/applied`, every `/admin/leaks` route answers 404, `relay.refused["count"]` did not move, every `/admin/leaks` write is `routes.locked`, and neither tracker job is registered. `test_routes.py` already fails on an unclassified write route.
- **Seam 5 — the Tracker API over HTTP,** in the Removal service repo (`app/tests/test_tracker_api.py`, `test_tracker_probe.py`, `test_tracker_seed.py`, run with pytest). A stub fetcher and the existing upstream and leak-index stubs stand in for the network, and each test gets a temp `TRACKER_DB`.
  - Coverage: Bearer auth, 401 and revoked; tenant isolation (tenant A's key cannot read B's watch, and a DELETE of B's id is a no-op 204); `creator_cap`; `account_taken`; 410 `watch_deleted` on a PUT or read of a deleted id, and on a first PUT after a DELETE of an unseen id; the seed admission rule (host rules, short needle, Mega match source) and pending hits; the seed writes no Quick scan row; a failed seed retried by the next daily pass; a post-04:00 enrolment probed once that day; a restart mid-pass fetches no url_key twice; the 2-dead rule with blocked or unknown in between; removal-page markers read dead; probe bounds (private address, redirect count, body size); came back; flap counting and the report's plain counts with their denominator; one fetch per url_key across tenants; a paused watch skipped and `paused_since` set; DELETE hides at once and sets `purge_after` from `requested_at`, clamped to the watch's life; `dead_since` set on the first dead probe, kept through blocked, cleared by live, and copied onto the gone event; a link-only Leak with a `gone` status change reads Gone; `GET /v1/leaks` orders by newest first seen, pages by cursor, refuses 0 or over 500 ids with 422, and skips another tenant's, a deleted and an unseen id without a 410; the purge (`test_tracker_purge.py`) at 29 and 31 days removes the watch and every watch-keyed row, writes its id to `deleted_ids`, leaves Quick scan rows and other watches alone, keeps every `deleted_ids` row (a PUT of the purged id at day 61 still answers 410), and `purge --dry-run` deletes nothing.
  - Prior art: `test_scan_api.py`, `test_scan_reuse.py`, `test_retention.py`.
- **Seam 6 — one local tracer across both repos,** `service/tests/test_leak_tracker_e2e.py`: it starts the Removal service's tracker from `$REMOVAL_REPO` on loopback with a temp `TRACKER_DB` and its stub fetcher and upstreams, issues a key through `tracker_cli`, points the Relay at it, and drives enrol → seed → a daily pass at a controlled UTC day → roster row with a Leak pill and `last_checked_at` advanced → delete → the service's `/v1/creators` no longer lists it. No network leaves the box. It writes its outcome as JSON to `$LEAK_E2E_OUT`.
  - Convention, stated once here (later Phases refer to it): the file sits in the `test_*.py` glob that `scripts/run_tests_parallel.py` runs from `scripts/run-tests.sh`, so with `$REMOVAL_REPO` unset or missing it prints `SKIP  REMOVAL_REPO not set` and exits 0, as `test_cpu_limit_merge.py` skips without PyYAML. Acceptance sets both variables and checks that `$LEAK_E2E_OUT` is non-empty, so a skip there fails.
- Leak-check is tested by feeding `--diff` a synthetic diff; each forbidden value must exit 1 naming its rule, and a clean control must exit 0.

## Acceptance
```sh
set -e
cd "$(git rev-parse --show-toplevel)"
PY=$PWD/venv/bin/python
: "${REMOVAL_BRAND:?set to the Removal service brand (never commit it)}"
: "${REMOVAL_DOMAIN:?set to the Removal service domain (never commit it)}"
: "${REMOVAL_REPO:?set to the Removal service repo checkout}"
export REMOVAL_REPO
export LEAK_E2E_OUT="$(mktemp -d)/e2e.json"
scan() { printf 'diff --git a/x.md b/x.md\n+++ b/x.md\n@@ -0,0 +1 @@\n+%s\n' "$1" | LEAK_PROFILE=public .claude/skills/public-sync/leak-check.sh --diff 2>&1; }
refuses() { rc=0; out=$(scan "$2") || rc=$?; [ "$rc" -eq 1 ] && grep -qF "$1" <<<"$out" || { echo "leak-check let through ($1), exit $rc"; exit 1; }; }
for t in leak_tracker_gates leak_tracker_api leak_watch_sync leak_watch_tombstone leak_tracker_e2e role_enforcement settings_api applied_settings llm_tenant_keys; do nice -n 10 "$PY" service/tests/test_$t.py; done
test -s "$LEAK_E2E_OUT"
(cd app && nice -n 10 pnpm exec vitest related --run components/leaks/leakIdentityForm.ts components/leaks/leakView.ts components/leaks/LeakTracker.tsx components/leaks/LeakDisclaimer.tsx components/of-manager/CreatorColumn.tsx app/creators/leaks/page.tsx lib/nav.ts lib/roles.ts)
nice -n 10 "$PY" -m pytest -q demo/tests/test_leak_tracker_off.py demo/tests/test_routes.py
refuses secret "ltk_$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 40)"
refuses "removal service" "$REMOVAL_BRAND"
refuses "removal service" "https://$REMOVAL_DOMAIN/v1/me"
refuses "removal service" "$(basename "$REMOVAL_REPO")"
refuses "removal service" "$REMOVAL_REPO/app/main.py"
scan "the removal service checked 3 links" >/dev/null
if git grep -qiF -e "$REMOVAL_BRAND" -e "$REMOVAL_DOMAIN" -- app service docs CONTEXT.md; then echo "brand or domain in tree"; exit 1; fi
grep -q 'LEAK_TRACKER_URL: "${LEAK_TRACKER_URL:-}"' docker-compose.yml
grep -q 'LEAK_TRACKER_ENABLED: "${LEAK_TRACKER_ENABLED:-}"' docker-compose.yml
(cd "$REMOVAL_REPO" && nice -n 10 python3 -m pytest -q app/tests/test_tracker_api.py app/tests/test_tracker_probe.py app/tests/test_tracker_seed.py app/tests/test_tracker_purge.py && python3 tools/check.py)
nice -n 10 scripts/run-tests.sh
# manual: owner deploys the Removal service, runs `tracker_cli tenant add` + `key issue` for the AE Agency, sets LEAK_TRACKER_URL + LEAK_TRACKER_ENABLED=1 in the AE override or `.env` (passed through by docker-compose.yml), sets the AE Agency's flags.leak_tracker, pastes the key on the card. Pass: the card reads "set" with a masked key.
# manual: owner, then a Team Leader, open /creators/leaks on AE for the first time. Pass: each sees the Leak disclaimer once, Got it closes it, a reload does not show it again; the Creator column lists the Creators with All Models on top and selected, and the main pane shows the combined list.
# manual: owner enrols 3-5 AE Creators. Pass: within 15 minutes each row shows "Found on first scan · N" (N may be 0); after the next 04:00 UTC each row's Last checked is that day and at least one row has a non-Listed pill.
# manual: owner enrols and deletes one extra Creator. Pass: the row leaves the page at once, and after the tombstone job `GET /v1/creators` with the AE key no longer lists its watch_id.
# manual: the day after that delete, owner runs `tracker_cli purge --dry-run`. Pass: nothing is due, and the deleted watch's `purge_after` is its request time plus 30 days.
# manual: after 7 UTC days the owner runs `tracker_cli report`, counts the real Leaks among every admitted Leak on the AE All Models list, and records for Phase 2 the flap rate with its observation count and seed precision as real / admitted.
# manual: owner checks app.inflowwww.com, a self-hosted build and Twin show no Leak tracker nav item and /admin/leaks/setup answers 404
```

## Depends on
None among Phases: this is the first. Outside the plan's Phases it needs a deployed Removal service serving Tracker API v1, a tenant and key issued for the AE Agency, and the two env vars set in AE's override or `.env` (manual lines in Acceptance). Phase 2 (discovery lanes, budget, judge), Phase 3 (notices, service status, offer) and Phase 4 (bell, offboarding and backup roll-off, public enablement) build on its Tracker API, `leak_watch`, gates and page.

## Out of Scope
- The Google fresh pass, the Mega lookup, the listing recheck, the Weekly slot, the registry crawl, the Leak judge, Load reservations, the waitlist, `scan_partial`, `coverage_reduced`, per-Leak-lane last success and next attempt, the Today strip, the lane coverage display and alias lanes: Phase 2. Reason: plan line "Phase 2 — Discovery lanes, budget, judge". This Phase's `creators_max` is only a stop until then.
- The Notice feed, the exporter, Removal client mappings, Service status, the Removal track, the Removal offer, `leak_watch.offer_snoozed_until` and the stale banner: Phase 3.
- The `leak_daily` bell row, backup roll-off, tenant offboarding and reinstatement, key revoke, enabling app.inflowwww.com, self-hosted opt-in, Twin, and public-sync verification: Phase 4. The watch purge is this Phase's (Purge), so the 30-day promise holds from the first delete.
- The rename rule and `identity_note`, the kill switch pushing paused, orphan-watch logging, the key rebind for an empty Agency and the Demo tracker: Phase 4 (moved by Fable round 3 to size this Phase for one tracer).
- A confidence bound on the flap rate and CSV label samples: parked until after the pilot (Fable round 3); ticket 02 asks only for a measured rate.
- The 30-day "Up now" sparkline (prototype C; variant D has none) is named in no Phase, so this Phase leaves it out rather than invent a trend source. Reason: the plan says "minimal roster".
- Undoing a delete inside the 30 days: ticket 10 keeps the undo and Phase 4 adopts a deleted watch's history on re-enrolment inside the window; this Phase hides the row at once and purges it at day 30.
- The CSV export, pause reasons, the same-person link, suggested-alias chips and the Serper fallback: cut from v1 (Fable round 2).
- A live Fansly handle source: not yet specified (map). Fansly handles are typed and unverified.
- Thumbnails and media: not in this Phase; Phase 2's Google view passes previews through at view time, stores none, behind `LEAK_TRACKER_PREVIEWS` (off by default). Page bodies and any fetch of a Leak's page from the CRM: never (tickets 08, 10, 11).
- Filing notices from the CRM, billing and entitlement, and a one-off "scan now" UX: map out of scope.
- A per-Creator mute and nav badges: ticket 07.
- Routing `/admin/leaks` in Cell mode: the AE tracer runs one Relay. This is unowned in the plan.

## Further Notes
Ticket slices, in order:
- **Slice A (AE-visible):** gates, the key card and tenant binding, enrol `PUT`, the seed, the Leak roster with All Models and the drill-in, the Leak disclaimer, the demo-off test and the leak-check rules. Leak-check sits here because deploy-all pushes the tree public as soon as anything lands.
- **Slice B:** the daily pass, Origin probes, `dead_since` and `tracker_cli report`.
- **Slice C:** delete, the tombstone job, the purge with `deleted_ids`, the 410 drop, and the agency-user-delete 409.
- Seam 6 (the cross-repo tracer) closes slice C.

ASSUMPTION: the CRM mints `watch_id` (uuid4) and the service stores it; rung 4 (a tombstone always has the id, even when the first push failed). Overturned if the service must mint ids; then the CRM needs a pending-create state and an account-keyed delete.

ASSUMPTION: the tombstone carries `agency_user_id`, `account_id` and `tenant_id` beside (watch_id, requested_at), named after the house column `agency_user_id`; rung 3 (models' naming, Phase 4's tombstone shape). Overturned if keys become deployment-wide.

ASSUMPTION: the first accepted key binds the Agency to its Tracker tenant, a key of another tenant is always refused here (the rebind for an empty Agency moves to Phase 4), and clearing the key is refused while a tombstone is pending; rung 4 (a swap would otherwise drop deletes silently) and rung 5 (Fable round 3 sizing). Overturned if an AE Agency must move tenants during the tracer; then Phase 4's rebind ships early.

ASSUMPTION: a DELETE of an id the service never saw is remembered in `deleted_ids` for the caller's tenant, and no `deleted_ids` row is pruned while its tenant row exists, so a late first PUT or a reinstated tenant's sync always meets 410; rung 4 (keeping opaque ids is reversible, pruning them is not). Overturned if `deleted_ids` grows large enough to matter; then rows older than the tenant's last sync are pruned.

ASSUMPTION: a 410 `watch_deleted` is the one status for a deleted, purged or unseen-deleted id, on PUT and reads alike, and the CRM answers it by deleting the `leak_watch` row with no tombstone, so the Creator shows as not tracked; rung 5 (one status, one handler), rung 4 for the drop (the service already deleted the watch, and re-enrol mints a new id). Overturned if the owner wants the row kept and marked; then a `deleted_at_service` state is added.

ASSUMPTION: `service/tests/test_leak_tracker_e2e.py` prints SKIP and exits 0 when `$REMOVAL_REPO` is absent, and writes `$LEAK_E2E_OUT` when it runs, which Acceptance checks; rung 3 (`service/tests/test_cpu_limit_merge.py:11` skips the same way; `scripts/run_tests_parallel.py` globs `test_*.py`). Overturned if the house moves cross-repo tests out of `service/tests`.

ASSUMPTION: enrol, edit, Tracking and Delete are Owner/Admin only, and Team Leaders read. Rung 4: the consent attestation sends data off the box. Overturned if the owner wants Team Leaders to manage watches; then it falls to the write-role check only.

ASSUMPTION: the role gate fails closed. It ignores `enforce: false` and needs the built-in Owner/Admin role or an explicit `/creators/leaks` grant. Rung 3 (`opt_in_granted` fails closed) plus rung 4. Overturned if the owner wants the tracker to follow the agency's enforcement switch.

ASSUMPTION: a request that resolves to more than one Agency context answers 404, never a merge; rung 4 on the "never through the `all` merge" rule. Overturned when a multi-agency employee needs the page; then it needs an Agency picker.

ASSUMPTION: the roster lists only the Creators the session's Creator switcher shows; rung 3 (scope precedent). Overturned if Team Leaders should see every Agency Creator.

ASSUMPTION: the Leak roster lists untracked Creators too ("Not tracked"), so enrolment starts from picking one, which replaces the separate "Track a Creator" list; rung 3 (the house Creator column lists the session's Creators on every page). Overturned if the owner wants only tracked Creators on the left; then a "Track a Creator" button returns above the column.

ASSUMPTION: the glossary keeps "Leak roster" (now the left Creator column) and "drill-in" (now the one-Creator main pane) rather than renaming them, so Phases 2–4 and the tickets stay valid; rung 5. Overturned if the old words mislead builders; then rename across every leak-tracker spec.

ASSUMPTION: the All Models list comes from one new tenant read, `GET /v1/leaks` with the session's `watch_id` set, and not from the Relay fanning out per watch; rung 5 for the one call that still scales past the pilot, and it is additive under v1's rule that later work only adds. It skips stale ids instead of answering 410. Overturned if the service would rather not add a read; then the Relay fans out `/v1/creators/{id}/leaks` and merges, which is fine at 5 Creators.

ASSUMPTION: the Leak disclaimer's dismissal lives in browser storage under the Employee key, not on the Relay. Rung 3: the Relay has no per-person seen flag, since `user_settings` is per agency user, not per Employee; seen-once precedents are `components/vault/VaultTour.tsx` and ADR-0047. Rung 4: no table, route or demo LOCKED entry. Overturned if the owner wants it once per person across browsers; then a per-person Relay flag replaces it.

ASSUMPTION: the disclaimer shows on the first open of the results view, not on the setup card, and any close counts as seen; rung 2 for the trigger (owner: "When opening for first time reports"), rung 5 for one close path. Overturned if the owner wants it before the key is set, or only "Got it" to count.

ASSUMPTION: the nav reads only the effective flag (Deployment switch AND stored flag AND the session's role gate) from `/settings/applied`, the flag has no new UI toggle, and `chatterHidden` moves from the Creators group to its two existing children; rung 3 (`fansly_manager`) plus rung 4. Overturned if the owner wants a settings toggle (additive), or if moving `chatterHidden` changes what an employee sees today (it must not).

ASSUMPTION: a key is stored only after `/v1/me` answers 200; rung 4. Overturned if owners must paste a key while the service is down.

ASSUMPTION: the read cache is the last good response per (Agency, path) in process memory, with no TTL, dropped on key save and on delete; rung 5 ("at most a short read cache"). Overturned if a restart showing "not reachable" proves confusing; then it moves to a DB row.

ASSUMPTION: the sync runs hourly, so a pause reaches the service within about an hour; rung 5. Overturned if the owner needs an instant pause; then the toggle route pushes inline as well.

ASSUMPTION: a Deployment switch that reads off makes the sync send nothing, while the tombstone job still lands DELETEs; pushing paused on the kill switch, the rename rule, orphan logging and the Demo tracker move to Phase 4; rung 5 (Fable round 3 sizing). Overturned if the tracer needs the kill switch to stop spend at the service; then Phase 4's paused push ships early, or the owner pauses the tenant there.

ASSUMPTION: Phase 1 ships as three ticket slices (A AE-visible with leak-check, B probes and report, C delete and purge) in that order; rung 5. Overturned if slice C must land before AE enrols anyone; then C moves ahead of B.

ASSUMPTION: a per-tenant `creators_max` (default 5) refuses new watches until Phase 2's reservations exist; rung 4. Overturned when Phase 2 lands its Creator cap.

ASSUMPTION: the seed runs the Quick scan's candidate step privately (its current Google search and Mega lookup, no share row, profile, media or alias discovery) and never reuses a stored Quick scan, for at most 5 Creators per tenant; rung 2 ("enable-time seed from the existing quick scan") for the source, rung 5 for cutting the rest. Overturned if that shared daily Google allowance cannot spare it; then the seed waits for Phase 2's Google pass.

ASSUMPTION: a seed hit is admitted when its URL contains the handle or a strong alias after removing `_`, `.` and `-` (case-insensitive), and title-only hits wait as Pending hits for Phase 2's judge; rung 2 (ticket 02 "shown = confirmed only", ticket 05 admission) for the rule, and rung 5 for the normalisation. Overturned by the measured seed precision.

ASSUMPTION: a needle shorter than 4 characters after normalising admits nothing, the host rules run before admission, and a Mega item needs a handle or strong-alias match; rung 4. Overturned by the measured seed precision or by a pilot Creator with a 2–3 character handle.

ASSUMPTION: a probe follows at most 5 redirects, reads at most 256 KB, and refuses loopback, private and link-local addresses after DNS and on each redirect; rung 4. Overturned if real Leak hosts need more redirects or bytes to show their removal page.

ASSUMPTION: blocked and unknown probes neither break nor extend the dead streak, and keep the last settled pill; rung 4. Overturned by the flap measurement.

ASSUMPTION: the report prints plain counts with denominators and no confidence bound or sample file, and seed precision is counted by the owner over every admitted Leak on the drill-ins; rung 2 (ticket 02 asks only "measured flap rate under ~2%"; the plan says "Measures: probe flap rate, seed precision") plus rung 5. Overturned if Phase 2's pilot needs a bound to decide the 2-probe rule; then the bound and sampling come back from the parked list.

ASSUMPTION: the watch purge ships here with a `WATCH_TABLES` hook that later Phases extend; rung 2 for the need (ticket 10: purge 30 days after the request, and this Phase's AE delete starts the clock), rung 5 for the hook. Overturned if a later Phase's watch-keyed table cannot be purged by `watch_id` alone; then it registers its own step.

ASSUMPTION: a purged watch's id goes into `deleted_ids` and stays while the tenant row exists; rung 4 (a late or reinstated PUT still meets 410, and only opaque ids are kept). Overturned if the ids must go with Creator data at day 30; then the CRM's 410 drop must run before the purge instead.

ASSUMPTION: the DELETE's `requested_at` is clamped between the watch's `created_at` and now; rung 4 (a client clock can neither delay the purge nor date it before the watch existed). Overturned if the service must not trust a client time at all; then outage delay is disclosed instead.

ASSUMPTION: an agency-user delete lands its Leak watch deletes inline and is refused with 409 while one stays pending, rather than copying the key into the tombstone; rung 4 (a refusal is undone by retrying, a second copy of a secret is not), on rung 1 facts (`service/auth.py:699` is the only `delete(User)`; the key row and `leak_watch` cascade from `users`). Overturned if an admin must delete a user while the removal service is down; then the tombstone carries the key ciphertext.

ASSUMPTION: `dead_since` is the first dead probe of the current dead run, kept through blocked and unknown probes and cleared by a live one; rung 4 (a gone spell is dated from its start, never from a later probe). Overturned if the owner wants a blocked probe to break the run.

ASSUMPTION: the tracer's counts decide nothing on their own, so both defaults hold and counting carries on through Phase 2's pilot; rung 4. Overturned if the 7-day report already shows a flap rate well over 2 % on many observations; then the 2-probe rule is revisited before Phase 2.

ASSUMPTION: the relay's compose `environment:` passes `LEAK_TRACKER_URL` and `LEAK_TRACKER_ENABLED` through with empty defaults; rung 3 (the relay lists its env vars explicitly). Overturned if AE already injects env another way.

ASSUMPTION: Came back shows for 30 days after a gone→live change while the Leak is Live; rung 3 (ticket 06's 30-day came-back angle). Overturned if the owner wants it permanent.

ASSUMPTION: one daily probe pass at `TRACKER_DAILY_AT` 04:00 UTC for every watch; rung 5. Overturned when Phase 2 spreads load by Weekly slot.

ASSUMPTION: the Tracker key format is `ltk_` plus 40 base62 characters; rung 5. Overturned if the service already has a key format; then the leak-check pattern follows it.

ASSUMPTION: the brand rule's level is `report` (not `fail`) for the AE profile, because AE ships private main with `.scratch`; rung 3 (AE's level table). Overturned if AE's tree must also be brand-free.

## Review
Reviewer: `codex` (blind call, then draft call), 2026-11-27. Both calls exited 0 and were verified against the source before reconciling. Counts: 12 accept, 10 partial, 1 reject, 0 needs-human.

Blind call:
- B1 (a fresh seed through the Quick scan handler runs alias and profile enrichment, media, and writes a public share row). **accept**: the seed is now a private candidate step factored out of the handler, with no share row, profile, media or alias discovery (Seed 1, story 48).
- B2 (Quick scan output is lossy: one row per host, 80 results, a name-only Mega match counts). **accept**: Leaks come from per-URL items, Mega needs a handle or strong-alias match, `site_search` dropped, no reuse of stored scans (Seed 1–3).
- B3 (key bootstrap, roster scope, multi-agency, Cell mode, nav hides Creators from chatter sessions). **partial**: bootstrap (setup and key skip gate 3), multi-agency 404, roster scope and Cell mode were already decided; the nav finding was real (`chatterHidden` on the Creators group hides the item from every employee session), fixed in Owns (`lib/nav`) and the settings interface.
- B4 (reconciliation: lost reply, unlink vs Remove, original request clock, undo and purge owner). **partial**: the CRM-minted `watch_id` already survives a lost reply, and unlink/Remove were already split; the request clock is now carried (`?requested_at=`), and undo/purge are answered under D4.
- B5 (daily and pill semantics, probe bounds, removal-page coverage). **accept**: at most one fetch per `url_key` per UTC day through restarts and the seed's first probe, bounded probes, and removal-page markers in Seam 5 (Daily pass).
- B6 (`--filter-paths` keeps `plan/map.md` and `ext/`). **reject**: those paths exist only in the review workspace's layout; this repo keeps planning under `.scratch/`, which the public profile strips (the same run showed `.scratch/review/file.md` stripped).
- B7 (test at the Relay → Tracker boundary with real handlers and a controlled clock). **partial**: Seam 6 now drives the real Relay against the real tracker on loopback; the two-tenant and lost-reply cases stay in Seams 1 and 5, where they are cheaper, and the demo's refusal counter already counts attempted connections.
- B8 (seed precision can pass by admitting almost nothing). **accept**: the report also samples Pending hits, and the pass line is fixed before labelling (Measures).
- B9 (flap rate needs a denominator and a bound). **accept**: the report prints first-dead observations and the one-sided 95 % upper bound (Measures).

Draft call:
- D1 (failed seeds never retry; a post-04:00 enrolment can get two dead probes on day one). **accept**: the daily pass seeds unseeded watches first, and the seed's first probe opens that day's `daily_scans` row (Seed 4–5, Daily pass).
- D2 (a key of another tenant silently loses deletes; clearing the key strands retries). **accept**: `leak_tracker_tenant` moves into this Phase, `PUT /key` refuses another tenant's key, the tombstone carries `tenant_id`, and clearing the key is refused while a tombstone is pending (Interfaces, Schema).
- D3 (a DELETE before the first PUT lets a late create land). **accept**: an unseen id is remembered in `deleted_ids`, so a late PUT answers 410 (Contracts, Schema).
- D4 (the 30-day promise, the late clock, the false "no restore path"). **partial**: `requested_at` now rides on the DELETE and the Out of Scope line is corrected; the purge job is this Phase's (Purge; moved here by six-hats 11).
- D5 (the off switch can still create watches and send identities; pause-agency call). **partial**: a switch that reads off now sends paused only for rows the service already holds (Interfaces, story 29); the pause-agency call is rejected because ticket 10's amendment cut pause reasons and the service knows only the paused bit.
- D6 (nav and Relay disagree with enforcement off; saved roles override the Team Leader default). **accept**: the applied flag is gates 1, 2 and 4 for the session and the nav reads only it; the saved-role limit is written into the settings interface and story 6.
- D7 (cache has no TTL or invalidation; `fetched_at` vs `last_checked_at`; no pause time; no last-live time). **partial**: cache dropped on key save and delete, the UI shows `last_checked_at`, `paused_since` and `last_live_at` added; the TTL is rejected because the copy is served only when the service is unreachable and always says how old it is.
- D8 (reuse key, invented provenance, unstated CSE use, empty normalised needle). **accept**: no reuse, no `site_search`, CSE use named in Seed 1, host rules and a 4-character needle floor in Seed 3.
- D9 (orphan deletion is destructive after a snapshot restore). **accept**: orphans are logged and never tombstoned (story 33, jobs, Further Notes).
- D10 (Depends on is only Phase ordering; env cannot reach the AE Relay; ticket 08 pending). **partial**: Owns gains the compose pass-through and Depends on lists the external prerequisites; Depends on stays None as Phase ordering, and ticket 08's open detail is UI polish that does not block the tracer.
- D11 (`!` lines are ignored by `set -e`; brand literal versus ADR 0074). **partial**: Acceptance now checks exit 1 plus the rule name for the key, brand, domain, repo name and repo path, and exit 0 for a clean control; the literal stays, because ADR 0074 covers shipped trees and the script is an ops path that never replays, and it already holds real names and hosts literally (house precedent).
- D12 (the demo test passes while config writes stay open). **partial**: Seam 4 now asserts every `/admin/leaks` write is locked and neither job is registered; locking the generic flags tab is rejected, since the path lock cannot split the flags blob, the nightly reset restores it, and the transport is in-process with zero egress either way.
- D13 (stories with no seam: roster scope, consent actor/time, disclosure text, LLM key routes, service recovery and CLI). **accept**: each is now a named assertion in Seams 1 and 5 and `test_llm_tenant_keys`.
- D14 (no end-to-end pass condition). **partial**: Seam 6 adds the local cross-repo tracer and each manual AE line now has a pass condition; the AE run itself stays manual because nothing in this run may touch AE.

Cross-Phase (binds Phase 4, `phase-04-leak-tracker-bell-purge-public.md`; not edited here):
- `leak_tracker_tenant` and the key's tenant check now ship in Phase 1; Phase 4 builds on them instead of creating them.
- `DELETE /v1/watches/{id}?requested_at=` is Phase 1's contract; Phase 4 only adds the purge that reads `purge_after`.
- The tombstone already carries `agency_user_id`, `account_id` and `tenant_id`.
- Phase 4 names `POST /v1/watches` as Phase 1's enrol; Phase 1's enrol is `PUT /v1/watches/{watch_id}` with a CRM-minted id, and a deleted id answers 410, so restore must match (tenant, account_id) on a PUT with a new id.
- Phase 4's purge must run within 30 days of the first AE delete (ASSUMPTION below). Superseded in the plan review: the watch purge moved into this Phase (Six hats 11).

### Owner answers (2026-11-27)
- Ticket 08: D1 (Creator column, All Models default, drill-in in the main pane, house phone dropdown) applied in Solution, stories 15, 34–37, 39 and 66, Interfaces (`GET /all`, `/v1/leaks`), Page layout, Seams 1, 3 and 5, and Acceptance. D3 (Leak disclaimer) applied in stories 67–69, Leak disclaimer, Seam 3 and Acceptance. D2 is Phase 3's.

### Owner answers (2026-11-27, visuals)
- Wayfinder tickets 11-14 (Google previews, before/after sliders, the Start removal popup video, explicit-content rules) land in Phases 2 and 3. This Phase stays the text-only tracer: story 41 and Out of Scope now say so, and nothing else here changes. The Leak disclaimer's preview line and its versioned seen key are Phase 2's.
- Open question from ticket 14's adversary (A3): the read cache keeps the last good response per (Agency, path); a served copy must be filtered to the viewer's Creator grants on every serve, as the live read is. Recorded in the plan review, not changed here.

Cross-Phase lines other specs bind to this Phase (applied in the plan review, 2026-11-27):
- cross-Phase from P2 (a link-only Leak whose last status is `gone` reads Gone) — **accept**: Pill rule, first line.
- cross-Phase from P2 (`! printf … | leak-check.sh --diff` lines fail open) — **accept, already applied**: Acceptance uses `refuses()`, which checks exit 1 and the rule name; no `! cmd` line is left.
- cross-Phase from P3 (Cell routing for `/admin/leaks` must include `leaks/watches`) — **reject** as a requirement here: this Phase leaves Cell routing unowned (Out of Scope) and Phase 4 keeps the tracker off in cell mode, so the pattern is recorded under Phase 4's cell-mode ASSUMPTION for whichever spec routes it.
- cross-Phase from P3 (Probe state gains `dead_since`, copied onto gone events) — **accept**: Schema, Daily pass, story 65.
- cross-Phase from P4 (B5c: an agency-user delete cascades `leak_watch` and the key with no tombstone) — **accept**: story 64 and the user-delete rule under CRM jobs.
- cross-Phase from P4 (B6b: the seed's Quick scan store is slug-addressed) — **accept, already applied**: the seed writes no share row and reads no stored scan (Seed 1, codex B1).

### Six hats
One six-hats pass over the four specs, 2026-11-27. Bullets touching this Phase:
- 1 (one rebind rule) — **accept**: a foreign tenant is refused with 422 while the Agency has a watch or a tombstone and rebinds when it has neither, stated once in `PUT /key` and story 11; Phase 4 refers to it.
- 2 (one clamp rule) — **accept**: `requested_at` clamped between `created_at` and now, now when absent (Contracts, DELETE); Phase 4 refers to it.
- 3 (`identity_note` has no column) — **accept**: `leak_watch.identity_note` (Schema), used by the rename note (story 25) and Phase 4's restore note.
- 9 (link-only Gone) — **accept**: see cross-Phase from P2.
- 10 (`dead_since` here) — **accept**: without it every gone spell before Phase 3 lands falls out of both gone counts; see cross-Phase from P3.
- 11 (purge here) — **accept**: `tracker_purge` with its daily run, `tracker_cli purge [--dry-run]`, `deleted_ids` pruning and the `WATCH_TABLES` hook (Purge, story 63, Seam 5, Acceptance); the "Phase 4 ships within 30 days" ASSUMPTION is gone.
- 12 (user delete) — **accept**: see cross-Phase from P4.
- 15 (expected counts) — **accept**: Measures states the 149-observation floor, the likely inconclusive result, and that the defaults hold while counting carries into Phase 2's pilot.
- 16 (Cell-routing ask) — **accept**: see cross-Phase from P3; not a requirement here.
Counts: 9 accept, 0 partial, 0 reject. Cross-Phase: 5 accept (2 already applied), 1 reject.

### Fable round 3 (2026-11-27)
- C1 (e2e test sits in the `test_*.py` glob with no skip, while Phase 3 skips) — **accept**: Seam 6 states the convention once (SKIP and exit 0 without `$REMOVAL_REPO`, else write `$LEAK_E2E_OUT`); Acceptance exports both and runs `test -s "$LEAK_E2E_OUT"`.
- C2 (D4 still says the purge stays in Phase 4) — **accept**: D4 now says the purge is this Phase's.
- C3 (rename note owner after the move) — **accept**: `identity_note` and the rename rule move to Phase 4 as an additive column; this Phase's schema drops it.
- C4 (410 versus Phase 4's 404 `watch_purged`; pruned `deleted_ids` let a reinstated tenant re-create watches) — **accept**: 410 `watch_deleted` is the one status for PUT and reads (Contracts); `deleted_ids` is kept while the tenant row exists (Purge); the CRM drops the row with no tombstone on a 410 (CRM jobs); Seam 5 checks day 61.
- Sizing (Phase 1 too big for one tracer) — **accept**: three ticket slices (Further Notes); stories 25, 29, 33 and 60 and the rebind move to Phase 4 (its stories 49–52 and 23); the kill switch here sends nothing; the demo keeps the tracker off with `demo/tests/test_leak_tracker_off.py`.
- Cut 3 (95 % bound and CSV sampling) — **accept**: ticket 02 says only "measured flap rate under ~2%"; the report prints plain counts with denominators and the owner counts precision on the drill-ins (story 59, Measures, Seam 5, Acceptance).
- Cut 1 (offboard, reinstate, adoption-restore), cut 2 (four-target report), cut 4 (waitlist), cut 5 (Hide, snooze Undo), cut 6 (`?day=`) — not this Phase's; see Phases 2–4.
