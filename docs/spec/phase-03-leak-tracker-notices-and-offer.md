# Phase 03 — Notice feed, Service status, Removal offer

**Objective.** The owner's confirmed Notices reach the Removal service every day, the service maps them to Agency Creators only through the owner's Removal client mapping and serves each Creator's Service status and Removal track, and the drill-in shows that track, the stale banner and one calm Removal offer under the 06 and 09-amended rules.

## Problem Statement
After Phase 1 an Agency sees its Leaks go live, cached and gone, but it cannot tell its Removal work from natural decay. The Notices that explain a gone Leak live in several ledgers on the service owner's laptop. Some of those ledgers overwrite themselves, and none of them can be reached from the server. A Creator who is already a Removal client looks the same as one who is not. Nothing in the CRM says that the owner's removal business exists, and a pitch built from notice activity alone would offer removals to Creators the service already works for, or tell an ex-client the work is still running. A pitch with no rules would also nag Team Leaders, overclaim ("we removed 80 %"), or put a Creator's handle into a chat link.

## Solution
A daily exporter on the owner's laptop reads every Notice ledger read-only, keeps only confirmed sends per channel, and pushes them, along with later decisions, to the Removal service as content-addressed events using the Ingest key. A full replay each run heals any missed day. The owner links sources to Removal clients, and Removal clients to Agency Creators, with a CLI inside the service. That CLI also sets each Creator's Service status. Nothing is ever matched by handle. For each Creator the Tracker API then serves its Service status, the time of the last completed ingest, and Removal track counts derived from the Leak event log and the notice store. Each Leak also carries its own Notice lines. In the CRM the drill-in shows one Removal area:
- `none`: a Removal offer.
- `pending`: "Removal starting".
- `active`: the Removal track, or "No notices filed yet".
- `former`: the past track plus an offer.
- `unknown`: an offer only while the Notice feed is fresh; otherwise nothing.

Every state carries "Notices updated <time>". When the last ingest is more than 48 h old, a stale banner replaces the counts. The Removal offer is a single drill-in card that only an Owner or Admin sees. It leads with the first true angle from the Agency's own counts and has a "Message {brand}" link that carries no handle. A "Not now" snoozes it agency-wide for 7 days, and the Agency Owner can hide every offer from Settings › Preferences. The Leak roster gains a Removal column and a Gone-after-notice column. Phase 4's Demo tracker seeds every state with a disabled button and no egress; until then the demo keeps the tracker off.

## User Stories
Notice feed (Laptop leak tools)
1. As the service owner, I want one exporter command to read every Notice ledger read-only, so that no tool's own state is ever changed by the feed.
2. As the service owner, I want the exporter to run daily at 13:00 under launchd at nice 10, so that the feed needs no manual step and never slows my laptop.
3. As the service owner, I want a run missed while the laptop slept to run after wake and replay every ledger in full, so that downtime catches up without a cursor.
4. As the service owner, I want only confirmed sends to count, per the channel table below, so that a draft, a failed form or a bare form mark is never shown as a Notice.
5. As the service owner, I want a form-extension row whose recipient is a host or registrar contact pushed as channel `host`, so that host notices are not mislabelled as site notices.
6. As the service owner, I want the Google filer's rows counted only with a report id, and on a partial success only the URLs with per-URL evidence, so that a URL Google never received is never a Notice.
7. As the service owner, I want only the laptop tools' own manual stamps imported, never the rows they themselves imported from other ledgers, so that one filing is not pushed twice under two sources.
8. As the service owner, I want each event's id to be sha256 over (source tool, channel, url, filing ref, kind, outcome), with the source client always inside the filing ref, so that a replay adds nothing, a later decision is a new event, and two clients filing the same URL stay two events.
9. As the service owner, I want a self-overwriting ledger to add an event only when a row's outcome changes, so that overwritten history is not re-imported as new each day.
10. As the service owner, I want an unknown filing time pushed as null, with the run time as `observed_at`, so that no date is invented.
11. As the service owner, I want a dry run that prints counts per tool, channel and kind, and the dropped rows per reason, and sends nothing, so that I can check a ledger change before it reaches the service.
12. As the service owner, I want a run that fails mid-push, or finds a configured ledger missing or unreadable, to exit non-zero and leave the feed's freshness untouched, so that a half run never looks current.

Ingest and mapping (Removal service repo)
13. As the service owner, I want the ingest route to accept only the Ingest key and every Tracker route to refuse it, so that an Agency key can never write Notices and the laptop key can read no Agency's data.
14. As the service owner, I want the service to recompute each event's id and url key and reject mismatches by index, so that drift between the two url-key copies shows up at once instead of splitting Leaks.
15. As the service owner, I want the feed marked updated only when every batch of a run, through its final one, has arrived once and every one of its events has been counted, so that "Notices updated" means a whole replay landed and a resent batch is not counted twice.
16. As the service owner, I want duplicates across tools kept as separate events, so that the timeline shows every filing and the page groups them by (channel, url key, day).
17. As the service owner, I want a Notice for a URL not yet discovered to be kept by url key and to show on the Leak the day it appears, so that pre-discovery filings are not lost.
18. As the service owner, I want events from an unmapped source client withheld, counted per source client and listed by the CLI but never stored, so that an ambiguous row never reaches an Agency and no Notice of a non-client is kept.
19. As the service owner, I want to link a (tool, source client) to a Removal client, mark a source client ignored (its stored events deleted, its later ones withheld), and refuse a second link without `--replace`, so that each source client maps to exactly one Removal client and the store keeps only Notices of linked clients.
20. As the service owner, I want to link a Removal client to a Leak watch (by `watch_id`) with a Service status and change that status later, so that the Agency's view follows my client book, not notice activity.
21. As the service owner, I want a list of watches showing each one's tenant, account and Leak identity, so that I can map by looking, while the CLI itself never guesses from a handle.
22. As the service owner, I want a fixed mapping to change what every Agency sees at the next read, so that a wrong link never stays visible on the wrong Agency.
23. As an Agency, I want a deleted Leak watch to stop showing Notices at once, and a re-enrolled Creator (a new `watch_id`) to start with no Removal client link, so that Notices no longer show for a Creator I removed and a late delete retry can never unlink the new watch.

Service status and Removal track (Tracker API + CRM)
24. As a Team Leader, I want the roster's Removal column to read Active, Pending or —, so that I can see at a glance which Creators the service works on.
25. As a Team Leader, I want the roster's Gone-after-notice column to read "N of M" for active and former Creators while the feed is fresh, and — otherwise, so that the roster never shows stale or non-client counts.
26. As a Team Leader viewing an active Creator, I want "N of M noticed Leaks gone", "Gone, no notice on file", Delisted and "live after notice" as counts, so that I see what happened without any rate or credit claim.
27. As a Team Leader, I want "Gone after notice" to count a Leak only when the first dead Origin probe of its current gone spell came after its first Notice, once per Leak, and "Gone, no notice on file" to count only gone Leaks with no Notice at all, so that natural decay is never shown as the service's work and a noticed Leak is never labelled un-noticed.
28. As a Team Leader, I want Delisted only from a Google decision imported as a Notice outcome, so that a Google miss never reads as a delisting.
29. As a Team Leader, I want each noticed Leak row to show its Notice lines, grouped by channel and day, plus "live N days after notice" or Delisted, so that I can follow one link's removal.
30. As a Team Leader viewing an active Creator with no Notices, I want "No notices filed yet", so that an empty track is not mistaken for a broken one.
31. As a Team Leader viewing a pending Creator, I want "Removal starting" and no offer, so that a Creator being onboarded is not pitched.
32. As a Team Leader viewing a former Creator, I want the past track read-only, with no Notice after the end date, so that history stays truthful after a cancellation.
33. As a Team Leader viewing a none Creator, I want no Removal track at all, so that the page never implies work that is not happening.
34. As a Team Leader, I want "Notices updated <time>" in every Removal area state that shows anything, so that I know how fresh the Notice side is.
35. As a Team Leader, I want a stale banner in place of the Removal track counts when the last completed ingest is more than 48 h old or has never happened, so that old counts never pass for fresh ones.
36. As a Team Leader viewing an unknown Creator while the feed is stale, I want the whole Removal area hidden, so that an unconfirmed status neither pitches nor claims.

Removal offer (CRM)
37. As an Agency Owner or Admin, I want one Removal offer card in the drill-in, under the stats, for a Creator whose Service status is `none` or `former`, or `unknown` with a fresh feed, so that the offer reaches the people who decide.
38. As a Team Leader or Chatter, I want never to see the offer, enforced by the Relay, so that the page stays a work tool for me.
39. As an Agency Owner or Admin, I want no offer before the Creator's first Daily scan is complete, so that the card never speaks before there is data.
40. As an Agency Owner or Admin, I want the offer's lead line to be the first angle that applies: came back in 30 days, gone at origin but still in Google, up 30 days or more, new this week, then any Visible Leaks, so that it reads as a fact about my Creator.
41. As an Agency Owner or Admin with no Visible Leaks, I want a quiet line, "No live leaks found. {brand} also handles removals if you need them.", that still links to the contact, so that a clean result is not turned into a scare.
42. As an Agency Owner, I want the offer to show counts only, with no percentage, price, revenue estimate, competitor price or cadence promise, so that it stays honest.
43. As an Agency Owner, I want "Message {brand}" to open the service's `contact_url` as given, with the prefill text the service put in it, in a new tab with no referrer and with nothing about the Creator or the tracker added, so that I choose what to share.
44. As an Agency Owner or Admin, I want "Not now" to hide the card for that Creator for 7 days for the whole Agency, and new findings not to reset it, so that one dismissal holds.
45. As an Agency Owner, I want a "Hide removal offers" switch in Settings › Preferences, off by default, that only I can change, so that the Agency can opt out of the offer completely.
46. As an Agency member linked to two Agencies, I want the hide setting and snooze read for the active Agency only, so that one Agency's choice never decides another's.
47. As an Agency Owner, I want no card when the Tracker API sends no brand or no valid https `contact_url`, so that a self-hosted install without an offer never shows a broken one.
48. As a Team Leader, I want the Today strip and the bell to carry no offer, so that the offer has one place.

Demo
49. Built by Phase 4 (its story 48) on the Demo tracker: seeded Creators for every Removal area state and every offer angle.
50. Built by Phase 4 (its story 48) on the Demo tracker: the demo's "Message" button disabled and no tracker or contact request. Until then the demo keeps the tracker off.

## Implementation Decisions
- **Owns.**
  - *Laptop leak tools*:
    - a new exporter module (`noticepush`) and its CLI subcommand `notices push [--dry-run]`;
    - one per-ledger reader for each row of the channel table below, reusing the tools' existing filings readers and `url_key` where one exists;
    - an ops script and a launchd agent template beside the tools' existing daily agents, plus an install flag on the tools' launchd installer.
  - *Removal service repo*:
    - a new tracker notices module: the ingest handler, the notice store and the Removal track derivation;
    - a new tracker mapping CLI;
    - modified, both from Phase 1: the Tracker API module (`/v1/me`, the creator reads and the leak reads gain fields, the ingest route is added) and Phase 1's `tracker_purge.WATCH_TABLES`, which gains `client_watches`. `dead_since` on Probe state and on the gone event is Phase 1's; this Phase only reads it.
  - *CRM, this repo*:
    - a new Relay module `leak_removal`, which holds the pure Removal area and offer decisions;
    - modified: Phase 1's Leak tracker Relay module (drill-in and roster reads, plus one new snooze route), `settings_schema` and `settings_api` (one preference), and `db.models` (`leak_watch.offer_snoozed_until`);
    - new app components: the drill-in Removal area, the Removal offer card, and a pure copy table for the offer copy;
    - modified app code: Phase 1's Leak roster and drill-in, `PreferencesTab`, and `appliedSettings`;
    - in `demo/`: nothing in this Phase. Phase 4 builds the Demo section below with its Demo tracker, seed and boot patch.
- **Channel table** (the exporter's authority). Only confirmed sends become `sent` events. Decisions become `decision` events.

  | Channel | Ledger (generic) | What counts |
  |---|---|---|
  | `site` | the notice mailer's site-notice send ledger | every row |
  | `site` | the form extension's send log | rows with status `ok`, a message id and a `urls` list; a row whose `to` the extension's own registrar check classes as a registrar contact becomes `host`; `attempting`, `blocked` and `fail` lines and form marks with no URLs are dropped |
  | `site`, `google_dmca`, `google_outdated` | the laptop tools' send ledger | only stamps with the hand-filed or export source, never `import:*` rows; the stamp's form picks the channel (`google` → `google_dmca`, `outdated` → `google_outdated`, `links` → `site`); `bing` stamps are dropped |
  | `host` | the notice mailer's host-notice send ledger | every row |
  | `google_dmca` | the Google filer's filed log | URL rows whose notice id joins a receipt line in the filer's ledger with a `report_id`, `submitted` true and outcome `success`; every URL of a `partial` notice is dropped, because the filer keeps no per-URL acceptance |
  | `google_dmca` | the notice mailer's DMCA ledger (self-overwriting) | every row as `sent`; the row's normalised status as a `decision` when it is `approved`, `denied` or `duplicate` |
  | `google_outdated` | the notice mailer's outdated-content ledger (ages entries out) | every row as `sent`; the row's normalised status as a `decision` when it is `approved` or `denied` |

  The `src` values are `mailer`, `form_ext`, `google_filer` and `stamp`. Decision outcomes are normalised by the laptop tools' existing status reader ("duplicate" anywhere wins, then denied, approved, pending), so the vocabulary is `approved`, `denied`, `duplicate`, `pending`. A `sent` event has outcome null.
- **Filing time.** A reader takes `at` from the row's own filing time (the filer's `ts`, the mailer's `first_seen` or `requested` date, the stamp's `at`). It never falls back to the ledger file's modification time, which the tools' existing reader does; a row with no time of its own sends `at: null`.
- **Source client.** A reader takes `src_client` from the row's own client field (the extension's `client`, the stamp's `client_id`, the filer's notice stage). A ledger keyed only by URL (the DMCA and outdated-content ledgers, and any mailer ledger without a client field) resolves it by url key against the laptop tools' client-scoped findings and send ledger: exactly one client id gives that id; none or several sends `src_client: null`, which the service withholds. The outdated-content ledger's own name-token attribution is never used, since it matches by handle.
- **Event id.** `id` = lowercase hex sha256 of the compact UTF-8 JSON array `[src, channel, url, filing_ref, kind, outcome]`, with nulls written as JSON `null`. `filing_ref` is never null: it is `"<src_client>/<native ref>"`, where the native ref is the filer's report id, the extension's message id, or empty for a ledger without one, and `src_client` is written as `-` when unresolved. So the plan's six fields stay, and two source clients filing the same URL never share an id. A self-overwriting ledger is diffed through this id: replaying an unchanged row yields the same id, and a changed outcome yields a new one. The exporter keeps no local state.
- **Exporter failure.** A configured ledger that is missing, unreadable or malformed stops the run before its first batch, with a non-zero exit, so nothing moves `notices_updated_at`. A run that finds zero events still pushes one final batch with `total: 0`, which completes it.
- **Ingest contract** (`POST /v1/notices/ingest`, Removal service).
  - Auth: the Tracker API's auth header, carrying the Ingest key. The service holds only the key's sha256, in its env.
  - Body, at most 500 events and 1 MB (413 over):
    ```
    {run_id: uuid, seq: int, final: bool, total?: int,
     events: [{id, kind: "sent"|"decision", channel: "site"|"host"|"google_dmca"|"google_outdated",
               url, key, src, src_client, filing_ref: str|null, at: iso|null, observed_at: iso, outcome: str|null}]}
    ```
    `total` is required when `final` is true. `seq` starts at 0.
  - Answer: `{accepted, duplicate, withheld, rejected: [{index, reason}], complete: bool}`. Every event of a batch lands in exactly one of the four.
  - Writes are insert-or-ignore on `id`, so the first `observed_at` stays. Withheld events are counted per (src, src_client) in `source_counts` and not stored: ticket 10 keeps no Notice of a non-client, and the next full replay stores them once their source is linked.
  - Each (run_id, seq) is recorded once with its event count. A batch resent under a seq already recorded is stored idempotently and adds nothing to the run's count.
  - `complete` turns true, and `notices_updated_at` moves to that time, only once the `final` batch has arrived, every seq from 0 to the final seq is recorded, and the recorded counts sum to `total`.
  - An event with a recomputed id or key that does not match, a bad enum, or a `decision` with no outcome is rejected and counted.
- **Notice store** (Removal service tracker DB, never the Quick scan tables).
  ```
  notice_events(id PK, kind, channel, url, url_key, src, src_client, filing_ref, at, observed_at, outcome, received_at)
    index (src, src_client, url_key)
  source_links(src, src_client, removal_client NULL, ignored BOOL, PK(src, src_client))
  removal_clients(id PK, label)                       -- label is the owner's, never served to a tenant
  client_watches(watch_id PK, removal_client, service_status, status_since)
  ingest_runs(run_id PK, final_seq NULL, total NULL, finished_at NULL)
  ingest_batches(run_id, seq, n, PK(run_id, seq))
  source_counts(src, src_client, run_id, withheld, PK(src, src_client))
  ```
  - Withheld = events whose (src, src_client) has no `source_links` row, whose `src_client` is null, or whose source is ignored.
  - Ignoring a source client deletes its stored events at once; later ones are withheld like an unmapped source's. Events of linked sources are the owner's case records under the owner's own retention (ticket 10), and no tracker clock deletes them.
  - `client_watches` is keyed by `watch_id`, as ADR-0071 keys everything in the service. A watch with no `client_watches` row has Service status `none`.
- **Notices join at read time.** A Leak's `notice` and `notice_outcome` entries are not copied into per-Leak rows. The read builds them by joining on url key: from the watch to `client_watches`, to the Removal client, to its linked, non-ignored sources, to `notice_events`. So pre-discovery attach and a mapping fix cost nothing, and the notice store is itself append-only; the Leak event log stays the append-only record of what was observed, and the mapping only decides which Agency may see a Notice. The leak read serves the joined entries inside each Leak's `events` list as `notice` and `notice_outcome` events, the ADR-0070 types, as well as in the grouped `notices` lines.
- **Notice time** = `at`, or `observed_at` when `at` is null. For a `former` link, an event whose Notice time is after `status_since` is left out, so an undated row first imported after the cancellation is left out too: the track never claims a Notice it cannot date before the end.
- **Removal track derivation** (service, per Leak watch, confirmed Leaks, any kind). These counts are served only for `active` and `former`; for every other status the field is null. A Leak's current Origin status is the one its Leak event log derives, whichever lane wrote it (a Phase 2 Mega `deleted` pack is gone; absence from results never is).
  - `noticed`: Leaks with at least one `sent` Notice.
  - `gone_after_notice`: noticed Leaks that are currently gone and whose current gone event's `dead_since` (the first dead probe of that gone spell) comes after the first Notice time.
  - `gone_no_notice`: currently gone Leaks with no `sent` Notice at all.
  - A noticed, currently gone Leak whose gone event has no `dead_since`, or whose `dead_since` is not after the first Notice, is in neither gone count; it stays in `noticed`, so "N of M" never overclaims and "no notice on file" is never wrong.
  - `delisted`: Leaks with a `google_dmca` or `google_outdated` decision `approved`.
  - `live_after_notice`: noticed Leaks whose current Origin status is live.
- **Offer counts** (service, every status, confirmed Leaks):
  - `visible`: Visible Leaks;
  - `came_back_30d`: Leaks with a came-back event in the last 30 UTC days;
  - `cached`: Leaks gone at origin and seen in Google (from Phase 1's seed visibility until Phase 2's Google pass refreshes it);
  - `live_30d`: Leaks live at origin with `first_seen_at` 30 or more days ago;
  - `new_7d`: Leaks first seen in the last 7 UTC days, not counting "Found on first scan". It reads 0 until Phase 2's discovery lanes land, since Phase 1 only seeds.
- **Tracker API additions** (contract to the Relay). Unknown fields are ignored, and a field the Relay does not recognise reads as absent.
  - `GET /v1/me`: adds `notices_updated_at` (iso, or null). `brand` and `contact_url` are Phase 1's; this Phase adds the rule that the service's env `contact_url` carries the generic prefill ("Hi, I'd like help with removals for one of my creators") and no tenant, watch or Creator data, checked by the service test.
  - The creator reads (list and one): add `service_status`, `service_status_since`, `removal` (the five counts, or null), `offer_counts` and `first_daily_at` (the finish time of the watch's first `daily_scans` row with outcome `ok` or Phase 2's `partial`, or null).
  - The leak read: adds to each Leak, for `active` and `former` only, `notices: [{channel, day, n, outcome}]` (grouped by channel, url key and day), `first_notice_at`, `gone_after_notice`, `delisted`, and the joined `notice` and `notice_outcome` entries in `events`.
  - Watch delete: changes nothing in `client_watches`. Phase 1 hides the deleted watch from every read at once, so its Notices stop showing; the row stays until Phase 1's purge removes it through `WATCH_TABLES`. Notices are kept by linked source, not by watch, so the purge touches none. A re-enrolment has a new `watch_id` and no row.
- **Tracker mapping CLI** (owner-run inside the service container). It is the only writer of `source_links`, `removal_clients` and `client_watches`. It never matches by handle.
  - `sources`: each (src, src_client) with its link, ignored or withheld state and its event counts.
  - `withheld`: the withheld counts of the last run per (src, src_client); no URL is shown, since withheld events are not stored.
  - `client add <label>`.
  - `link-source <src> <src_client> <client>` and `ignore-source <src> <src_client>`.
  - `watches`: watch_id, tenant, account, platform, handle and display name for each live watch.
  - `link-watch <client> <watch_id> --status pending|active|former|unknown`.
  - `status <watch_id> <status>`: moves `status_since`.
  - `unlink-watch <watch_id>`.
  - A second link for an existing key is refused unless `--replace` is given.
- **Removal area decision** (Relay `leak_removal.removal_view`, pure). The inputs are Service status, `notices_updated_at`, now and the `removal` counts. Fresh means `notices_updated_at` is set and no more than 48 h old.

  | Service status | Fresh feed | Stale or never |
  |---|---|---|
  | `none` | offer; no track | offer; no track |
  | `unknown` | offer; no track | nothing at all |
  | `pending` | "Removal starting" | "Removal starting" |
  | `active` | track, or "No notices filed yet" when `noticed` is 0 | stale banner in place of the counts |
  | `former` | past track + offer | stale banner in place of the past counts + offer |

  A missing or unrecognised status reads as `unknown`. "Notices updated <time>" shows in every row except "nothing at all".
- **Offer decision** (Relay `leak_removal.removal_offer`, pure). It returns null unless every one of these holds:
  - the table above says offer;
  - the viewer is the Owner session, or a chatter whose assigned role id is `admin` in the active Agency's applied roles blob;
  - the Creator's `first_daily_at` is set (a missing field reads as not done);
  - the active Agency's `preferences.hide_removal_offers` is not true;
  - `leak_watch.offer_snoozed_until` is null or already past;
  - `/v1/me` gave a non-empty `brand` (at most 40 characters) and an absolute https `contact_url` (at most 512 characters).

  When it holds, it returns `{brand, contact_url | null, angle, n}`. `angle` is `clean` whenever `visible` is 0, checked first, so a Leak that came back and is gone again never turns a clean result into a pitch (06). Otherwise it is the first non-zero of `came_back`, `cached`, `live_30d`, `new_week`, then `visible`. `contact_url` is null when the demo has turned contact off.
- **Drill-in and roster payloads** (Relay to app). The drill-in gains `removal: {status, view, notices_updated_at, stale, counts | null}` and `offer: … | null`. Each roster row gains `service_status`, plus `noticed` and `gone_after_notice` (null unless active or former with a fresh feed).
- **Snooze route.** `POST /admin/leaks/watches/{account_id}/offer-snooze` with `{snoozed: true}` → `{offer_snoozed_until}`. It sets the active Agency's `leak_watch.offer_snoozed_until` to now + 7 days; there is no un-snooze. It sits behind Phase 1's Tracker gates and path rule (404) and is Owner or Admin only (403). Once the drill-in is reopened, a snoozed Creator simply has no card (06). Under `/watches/*` it falls in Phase 1's demo LOCKED rule.
- **Hide setting.** `hide_removal_offers` is added to the `preferences` tab, after the `hide_trial_popup` precedent. It is written only through the existing owner-session `PUT` of that tab. The Relay reads it from the active Agency's applied preferences, never through the `all` merge. `PreferencesTab` shows the toggle only when the active Agency's `leak_tracker` flag is on.
- **Copy** (app, generic, brand from runtime).
  - Card: the eyebrow is `{brand}` and the heading is "Removal help".
  - Lead lines, one per angle:
    - "{n} leaks came back in the last 30 days."
    - "{n} leaks are gone from the site but still show in Google."
    - "{n} leaks have been up for 30 days or more."
    - "{n} new leaks this week."
    - "{n} leaks are up right now."
  - Second line: "{brand} files removal notices and follows them up."
  - Buttons: "Message {brand}" and "Not now". After a snooze the card is replaced by "Removal offer hidden until <date>."
  - The clean line is the one quoted in story 41.
  - The link is `target=_blank rel="noopener noreferrer" referrerPolicy="no-referrer"`, and the app adds no query string.
  - Notice lines are labelled by channel: "Notice sent · site", "· host", "· Google DMCA", "· Google outdated".
- **Schema (CRM).** `leak_watch.offer_snoozed_until DATETIME NULL`. The boot's additive-column pass adds it (`service/db/engine.py:255-280`). There is no migration.
- **Demo.** Built by Phase 4 with its Demo tracker (moved from Phase 1); this is what it must serve for this Phase.
  - The Demo tracker fixture gains a fake brand, a `.invalid` `contact_url`, a fresh `notices_updated_at`, and one Creator per state: none with each angle, none clean, unknown, pending, active with Notices, active with zero Notices, and former.
  - The seed snoozes one Creator.
  - The demo boot swaps `leak_removal.CONTACT_ENABLED` to False through `demo.patch.swap`, so `contact_url` is null and the button renders disabled. The snooze route is LOCKED by Phase 1's `/admin/leaks/watches/*` rule, so "Not now" renders disabled too, and the seeded snoozed Creator shows no card.
- **Laptop config.** The service base URL and the Ingest key come from the tools' existing out-of-git config or the environment, and are never written into the repo. The launchd agent runs `nice -n 10` and logs to the tools' log directory.

## Testing Decisions
One seam per repo, plus the app render, joined by one end-to-end contract run (real exporter → real ingest → real Tracker reads → their recorded responses replayed into the CRM Relay test), so the three repos cannot drift apart while each suite stays green. Each seam drives a public interface with fakes at the wire, and nothing in `service/` exists only for tests.
- **CRM Relay** — `service/tests/test_leak_removal_offer.py`, a script that exits non-zero on failure. It uses `TestClient` on Phase 1's drill-in and roster reads and on the snooze route, with Phase 1's in-process fake Tracker API serving table-driven `/v1/me` and creator payloads. Cases:
  - every row of the Removal area table at 47 h, 49 h and never;
  - a missing status reads as `unknown`;
  - the angle order, and `clean`, including `came_back_30d` 1 with `visible` 0 giving `clean`;
  - Owner gets an offer, Admin gets one, Team Leader and Chatter get null;
  - `first_daily_at` null or absent gives null;
  - the hide preference on the active Agency hides it, and the same preference on the viewer's other Agency does not (two-Agency chatter);
  - snooze gives null, the snoozed row's time is checked, a Team Leader snooze answers 403, a snooze still holds after the fake serves new Leaks and higher counts, and the same Creator in a second Agency keeps its card;
  - gates off gives 404;
  - a non-https, overlong or missing `contact_url` or brand gives null;
  - `removal.counts` is null when stale;
  - roster columns per status, and neither the roster rows nor any Today strip payload carry an `offer` key;
  - when `LEAK_CONTRACT` names a file, the fake serves the real `/v1/me`, creator and leak responses recorded by the Removal service repo's end-to-end test, and the drill-in shows the expected view and counts from them.

  `service/tests/test_settings_api.py` gains `hide_removal_offers`: it parses as a bool and refuses a chatter `PUT`.
- **App** — `app/components/leaks/RemovalArea.test.tsx` (vitest render, using Phase 1's leaks component folder) with fixture payloads:
  - each view's text;
  - a noticed Leak row's Notice lines grouped by channel and day, with "live N days after notice" and Delisted;
  - the stale banner in place of counts;
  - the angle sentences from the copy table;
  - no `%` or currency sign in any rendered copy;
  - the link has `href` equal to `contact_url` exactly, plus `rel` and `referrerPolicy`;
  - a null `contact_url` gives a disabled button;
  - "Not now" posts `{snoozed: true}` and shows the hidden-until line with no Undo.

  `PreferencesTab.test.tsx` checks that the toggle appears only with the `leak_tracker` flag.
- **Demo** — Phase 1's `demo/tests/test_leak_tracker_off.py` stays green with the snooze route locked. Phase 4's `demo/tests/test_fake_tracker.py` carries the walk over every seeded Creator's drill-in, asserting each expected view and angle, no outbound request, and `offer.contact_url` null.
- **Removal service repo** — `app/tests/test_tracker_notices.py` (pytest), using the Tracker API over a real local server, as the existing scan API tests do, and the mapping CLI as a function entry. Cases:
  - Ingest key versus Tracker key on both kinds of route;
  - id and key mismatch rejected by index;
  - replay adds nothing;
  - a changed outcome is a new event;
  - a run with no `final`, a short count, or a missing middle seq leaves `notices_updated_at` alone; a resent seq 0 does not count twice; a run with withheld events completes; an empty run with `total: 0` completes;
  - unmapped and null-client events are withheld, counted in `source_counts` and not stored, then stored and served by the first replay after `link-source`;
  - `ignore-source` deletes the source's stored events and withholds later ones; a second `link-source` or `link-watch` without `--replace` is refused; `status` moves `status_since`; `watches` lists every live watch with its `watch_id`;
  - two `sent` events from two sources for one URL on one day stay two rows and are served as one grouped line with `n` 2;
  - pre-discovery attach (Notice first, Leak later);
  - a mapping fix moves the Notices off the wrong tenant;
  - the former cutoff, including an undated event first observed after `status_since`;
  - the five Removal track counts, including `dead_since` before or after the Notice, a comeback then a second gone spell, a noticed gone Leak with no `dead_since` (in neither gone count), a Mega `deleted` Leak counted gone, and Delisted only from `approved`;
  - the leak read's `events` carry the joined `notice` and `notice_outcome` entries;
  - the offer counts and `first_daily_at`;
  - `/v1/me` `contact_url` equals the env value and carries the generic prefill;
  - watch delete hides the watch's Notices at once and leaves `client_watches`; a re-enrolment with a new `watch_id` has status `none`, and a late DELETE of the old id leaves the new watch's link alone;
  - two tenants never see each other's Notices.
- **End-to-end contract** — `app/tests/test_tracker_notices_e2e.py` in the Removal service repo, skipped unless `LEAK_TOOLS_REPO` and `LEAK_TOOLS_CLI` are set. It starts the real local server on a temporary tracker DB, runs the real exporter (`notices push`, with its ledger paths pointed at the laptop tools' fictional fixture ledgers and its base URL at the local server), links the sources and one watch with the mapping CLI, then reads `/v1/me`, the creator read and the leak read with a Tracker key. It asserts the expected counts and Notice lines, runs the exporter again and asserts nothing changed, and writes the three responses to `$LEAK_CONTRACT_OUT` for the CRM Relay test.
- **Laptop leak tools** — `tests/test_noticepush.py` (pytest) over fictional fixture ledgers. Cases:
  - each channel-table row's keep and drop rule, including `ok` with no message id, a form mark, a registrar recipient, a filed URL whose notice has no receipt or no report id, a `partial` notice dropped whole, imported versus hand stamps, and each stamp form's channel (and `bing` dropped);
  - ids stable across two runs;
  - two source clients filing one URL with no native ref get two ids;
  - a changed snapshot status yields exactly one new id;
  - null `at`, never the ledger's mtime;
  - `src_client` from the row's own field, and for a URL-keyed ledger from exactly one client's findings, null for none or two;
  - a missing or malformed configured ledger exits non-zero before any push;
  - the dry-run summary, including withheld-to-be (null `src_client`) counts per ledger;
  - a push to a local stub receiver: batches of at most 500, `final` with the right `total`, and a non-zero exit when the stub fails a batch.

Prior art:
- CRM: `service/tests/test_s4s_api.py` (`TestClient`, agency fixtures), `service/tests/test_settings_api.py`, `service/tests/test_agency_notifications.py`, `app/components/AgencyNotifications.test.tsx`, `app/app/creators/proxy/page.test.tsx`, `demo/tests/test_routes.py`.
- Removal service repo: `app/tests/test_scan_api.py` with its upstream stub.
- Laptop leak tools: `tests/test_sentlog.py` and its fakes module.

## Acceptance
```sh
set -e
ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"
PY=${PY:-$ROOT/venv/bin/python}
: "${REMOVAL_REPO:?set to the Removal service repo checkout}"
: "${LEAK_TOOLS_REPO:?set to the laptop leak tools checkout}"
: "${LEAK_TOOLS_CLI:?set to the laptop leak tools CLI command}"
export LEAK_TOOLS_REPO LEAK_TOOLS_CLI
export LEAK_CONTRACT_OUT=$(mktemp -d)/contract.json
(cd "$LEAK_TOOLS_REPO" && nice -n 10 uv run pytest -q tests/test_noticepush.py)
(cd "$REMOVAL_REPO" && nice -n 10 python3 -m pytest -q app/tests/test_tracker_notices.py && nice -n 10 python3 -m pytest -q app/tests)
(cd "$REMOVAL_REPO" && nice -n 10 python3 -m pytest -q app/tests/test_tracker_notices_e2e.py)
test -s "$LEAK_CONTRACT_OUT"
grep -q '"notices_updated_at"' "$LEAK_CONTRACT_OUT"
LEAK_CONTRACT=$LEAK_CONTRACT_OUT nice -n 10 $PY service/tests/test_leak_removal_offer.py
nice -n 10 $PY service/tests/test_settings_api.py
grep -q '"hide_removal_offers"' service/settings_schema.py
grep -q 'offer_snoozed_until' service/db/models.py
(cd app && nice -n 10 pnpm exec vitest run components/leaks/RemovalArea.test.tsx components/settings/PreferencesTab.test.tsx)
nice -n 10 $PY -m pytest -q demo/tests
nice -n 10 scripts/run-tests.sh
# manual: owner runs `notices push --dry-run` on the real ledgers and reconciles 10 recent filings they remember against its per-ledger counts (kept, dropped by reason, null src_client); material gaps park the feed before any Agency sees counts
# manual: owner installs the launchd agent with the tools' installer flag, confirms one 13:00 run, then on the service: `sources` lists every source client, `withheld` is empty after linking, `/v1/me` notices_updated_at is today
# manual: owner maps 1-2 AE Creators (one active, one none) and checks on AE: active drill-in shows the track with "Notices updated", none shows the offer to Owner only, "Message" opens the chat with no handle in the URL, "Not now" hides it for 7 days
```

## Depends on
- **Phase 1** provides:
  - the Tracker API with tenants, Tracker keys, its header auth, `watch_id`-keyed watches, the Leak event log, Probe state, `daily_scans`, `dead_since` on Probe state and on the gone event, the creator and leak reads, watch delete that hides at once, and the watch purge with its `WATCH_TABLES` hook;
  - `/v1/me` with `brand` and `contact_url`;
  - seed-time Google visibility, which feeds `cached`;
  - the CRM's `leak_watch`, the Tracker gates, the `/admin/leaks/watches/{account_id}` path rule and its demo LOCKED rule, the Leak tracker Relay module with its in-process fake Tracker API, the Leak roster and drill-in, and the demo's tracker-off test (`demo/tests/test_leak_tracker_off.py`).
- **Phase 2** provides the Google pass, full discovery, the Mega `deleted` → gone rule and the Today strip. Until it lands, `new_week` reads 0, `cached` rests on seed visibility, and the no-offer check on the Today strip has no strip to test. Phase 3 does not wait for it.
- **Phase 4** builds on this Phase's Removal track for the bell's "gone after notice". The `client_watches` purge is Phase 1's hook, and Notice retention is this Phase's own (withheld and ignored events are never kept).

## Out of Scope
- Filing Notices from the CRM: takedown stays in the owner's tools (map out of scope).
- An in-app removal request (`POST /v1/removal-requests`): 06 chose a chat link.
- A Bing channel: there is no ledger for it (09).
- Recovering history that self-overwriting ledgers already lost: it cannot be recovered; the import starts at its first run (09).
- Backups, tenant offboarding and key revoke: Phase 4. The watch purge clock: Phase 1. Retention of linked sources' Notices: the owner's own (ticket 10).
- The `leak_daily` bell row, which carries no offer anyway: Phase 4.
- Twin: the tracker is off there (Phase 4) and its offer is owner sign-off (needs-human); no Twin-specific switch (YAGNI).
- app.inflowwww.com and self-hosted enablement: Phase 4. The offer already needs a `contact_url` from the service.
- A per-Creator offer mute beyond snooze, and per-viewer snooze: 06 fixed the 7-day agency-wide snooze.
- An Undo for the snooze: parked until after the pilot (Fable round 3); 06 does not state it.
- The demo's Removal area and offer states: Phase 4, with the Demo tracker.
- An export of Notices: the CSV export was cut from v1 (10 amended).
- Price, revenue loss and competitor prices on the card: banned by 06.
- Running the exporter more than once a day, or pulling from the laptop: ADR-0072.
- Public-sync leak-check rules for this Phase's copy: Phase 1 adds the rules and Phase 4 verifies them. This Phase adds no brand to git.
- Slop run: this Phase sends nothing in bulk and has no concurrency path; the owner rule says no slop by default.

## Further Notes
ASSUMPTION: Notice entries of the Leak event log are served by a read-time join through the current Removal client mapping, not copied into per-Leak rows (rung 4: a wrong mapping disappears at the next read, and pre-discovery attach needs no job). Overturned if ADR-0070 is read as requiring physical copies; then an attach job copies them, and a mapping fix needs compensating events.
ASSUMPTION: a self-overwriting ledger's "diff" is the content-addressed id (rung 5: no exporter state, and a full replay heals). An outcome that changes A→B→A does not append A again. Overturned if the owner needs every flip.
ASSUMPTION: `src` values are generic (`mailer`, `form_ext`, `google_filer`, `stamp`) so that no private tool name enters the public contract (rung 4). Overturned if the owner wants the tools' own names, which would have to stay out of docs/.
ASSUMPTION: the feed counts as updated only on a complete run (every seq once, counts summing to `total`), and rejected and withheld rows count toward completeness (rung 4: one bad or unmapped row must not keep the feed stale forever; the exporter still exits non-zero on a rejection). Overturned if the owner wants any rejected row to block freshness.
ASSUMPTION: the service sends `contact_url` with its generic prefill already in it, and the app appends nothing (rung 5: the service knows its chat's link format). Overturned if the owner wants the CRM to own the prefill, in which case the app adds the 06 text.
ASSUMPTION: `unknown` is a status only the owner sets in the CLI, and any missing or unrecognised value reads as `unknown` in the Relay. With no mapping row the status is `none` (rung 5). Overturned if the service should infer `unknown`, for example for withheld rows near a watch.
ASSUMPTION: "Gone after notice" uses Phase 1's `dead_since` on Probe state (the first dead probe of the current dead run), copied onto the gone event; a noticed gone Leak without it, or with it before the first Notice, is in neither gone count (rung 4: never overclaim, never mislabel). After a comeback, the current gone spell decides. Overturned if the owner wants a Leak first gone before its Notice never to count even after a comeback.
ASSUMPTION: a Leak of any kind counts as gone when its event log says gone, including Phase 2's Mega `deleted` rule; absence from results never makes it gone (rung 2: ticket 01 and Phase 2's Mega lane). Overturned if the owner wants link-only Leaks kept out of the Removal track.
ASSUMPTION: Delisted = a `google_dmca` or `google_outdated` decision with outcome `approved` (rung 3: the tools' existing status vocabulary). Overturned if Google's "outdated" approvals mean something else.
ASSUMPTION: a stale feed replaces only the counts. Per-Leak Notice lines stay, dated (rung 5, reading "instead of fresh counts" literally). Overturned if the owner wants the lines hidden too.
ASSUMPTION: an offer with Visible Leaks but none of the four angles uses a fifth line, "{n} leaks are up right now." (rung 5). Overturned by owner copy.
ASSUMPTION: Admin = an assigned role id `admin` in the active Agency's applied roles blob, whether or not role enforcement is on (rung 3: the `permissions` assignment lookup). Overturned if Admin should follow enforcement.
ASSUMPTION: "Hide removal offers" lives in Settings › Preferences as `hide_removal_offers` (rung 3: the `hide_trial_popup` precedent, owner-only `PUT`). Overturned if the owner wants it on the tracker page.
ASSUMPTION: the demo disables contact by swapping a Relay module constant through `demo.patch.swap` (rung 3: the demo's existing swap precedent). Overturned if the Demo tracker should instead send no `contact_url` and an explicit preview flag.
ASSUMPTION: "on delete, the agency link is removed" (ticket 10) is met by Phase 1 hiding the deleted watch at once; the `watch_id`-keyed `client_watches` row stays until Phase 1's purge removes it through `WATCH_TABLES`, and a re-enrolment (new `watch_id`) needs the owner to re-link (rung 4: survives the 30-day undo and a late DELETE retry). Overturned if "removed" must mean the row is deleted at the request; then delete it by `watch_id` at the DELETE.
ASSUMPTION: two source clients' filings of one URL stay apart by putting `src_client` inside `filing_ref`, keeping the plan's six hashed fields (rung 4: smallest change to ticket 09's id). Overturned if the owner prefers `src_client` as a seventh hashed field.
ASSUMPTION: a URL-keyed ledger (DMCA, outdated content) gets its source client from the laptop tools' client-scoped findings by exact url key, one client or withheld (rung 5: no handle matching, ticket 09). Overturned if those ledgers gain a client field, or if most of their rows come back withheld in the dry-run reconciliation.
ASSUMPTION: the Google filer's `stage` is its source client id, and its URL rows join the filer's ledger by notice id to get `report_id` (rung 1: gfile.py writes `id` on both lines, `report_id` only on the ledger line). Overturned if `stage` is not one client.
ASSUMPTION: every URL of a `partial` Google notice is dropped, since the filer records no per-URL acceptance (rung 4: ticket 09's "only URLs with per-URL evidence" admits none today). Overturned if the filer's evidence folder holds a per-URL accepted list worth parsing.
ASSUMPTION: the form extension's `host` class is its own registrar check on `to`; hosting-provider abuse desks it does not class stay `site` (rung 3). Overturned if the extension gains a host classifier.
ASSUMPTION: laptop-tools stamps with form `links` count as `site`, and `bing` stamps are dropped (rung 2: no Bing channel, ticket 09). Overturned if `links` means a non-site form.
ASSUMPTION: the outdated-content ledger yields `approved`/`denied` decisions, which Delisted needs (rung 1: outdated_ledger.py keeps Pending/Approved/Denied per row). Overturned if Google's "outdated" approval does not mean delisted.
ASSUMPTION: a missing, unreadable or malformed configured ledger aborts the whole run (rung 4: a stale banner is honest, a silently shrunken replay is not). Overturned if one broken tool should not stall the others' freshness.
ASSUMPTION: the snooze route sits at `/admin/leaks/watches/{account_id}/offer-snooze` so Phase 1's path rule and demo LOCKED rule cover it (rung 3: Phase 1's `/watches/*` writes). Overturned if the demo should let visitors snooze.
ASSUMPTION: the end-to-end contract test lives in the Removal service repo and follows Phase 1's e2e convention (Seam 6): it skips without the laptop tools checkout, writes its output file when it runs, and the Acceptance block refuses the skip by requiring that file (rung 3, Phase 1's convention). Overturned if CI cannot hold both checkouts, then it runs only on the owner's laptop.
ASSUMPTION: a "non-client" in ticket 10's "Notices for non-clients are not kept" is a source client the owner has not linked to a Removal client, or has ignored; a linked source is in the owner's client book whatever its watches' Service status (rung 5). Overturned if the owner means Service status `active` or `former` only; then the ingest also withholds events of clients with no such watch.

ASSUMPTION: withheld events are counted, not stored, so a newly linked source's Notices appear at the next daily replay instead of at once (rung 2 for not keeping them, ticket 10; rung 5 for relying on the full replay). Overturned if the owner needs a link to show its Notices immediately; then the owner runs the exporter by hand after linking.

ASSUMPTION: `first_daily_at` counts a `partial` Daily scan as a first daily scan, since its probe pass ran (rung 4: a Creator capped every day otherwise never gets an offer). Overturned if the owner wants the offer held until a full-coverage day.

ASSUMPTION: the Ingest key lives as a sha256 in the service env, with one key for the owner (rung 5). Overturned when a second ingest source appears.

## Review

Reviewer: codex, 2026-11-27. Blind call (B) before the spec, draft call (D) on it.

- B1 accept: the Google filer has no per-URL receipt; URL rows now count only by joining a `success` ledger receipt with `report_id` on notice id, and `partial` notices drop whole (Channel table).
- B2 accept: two source clients filing one URL would collapse; `filing_ref` is now `"<src_client>/<native ref>"` and never null (Event id).
- B3 reject: shipping service status and the offer apart from notice history re-orders the plan's Phases (map.md); status already comes from the CLI, not from notices.
- B4 accept: stamp forms were misclassified; `google`/`outdated`/`links` map to google_dmca/google_outdated/site, `bing` dropped, `import:*` sources excluded (Channel table).
- B5 partial: the email ledgers' writer sits outside the extracts, so their format is read from the readers only; kept, flagged by the host-class ASSUMPTION and the end-to-end contract test.
- B6 partial: attach scope by alias or image-vs-page URL is not adopted; the exact url key inside the mapped client is the rule (Store and derivation), aliases left to Phase 2 discovery.
- B7 partial: mapping fixes stay read-time joins with the CLI as the sole mapping writer; the replay-restores-deleted-link case is closed by keying on `watch_id` (D6).
- B8 accept: `dead_since` is the current gone spell's first dead probe; a noticed Leak gone before its Notice or without `dead_since` is in neither count (Derivation).
- B9 accept: Delisted needs decisions; DMCA rows map approved/denied/duplicate and outdated rows approved/denied, normalised by the laptop tool's status rules (Channel table).
- B10 accept: freshness edge cases (empty run, resent batch, missing ledger) now specified: total 0 completes, (run_id, seq) idempotent, failure aborts before the first batch (Ingest contract).
- B11 partial: first-daily-scan gate accepted (`first_daily_at`); fifth-line copy already covered; Cell routing and CTA safety are partial: the service test checks the generic prefill, routing binds Phase 1 (below).
- B12 accept: the seam is real ledger bytes through to the tenant read; new end-to-end contract test plus the Relay test reading its output (Testing, Acceptance).
- B13 partial: the falsifier is reconciling receipts; a manual reconcile-10-filings step was added, not an automated one, since it needs the owner's real ledgers (floor 2).
- B14 reject: "the operator may not keep pending and active current" contradicts ticket 06, where the owner sets service status by hand.
- D1 accept: completion counting was loose; complete now means final arrived, every seq 0..final once, buckets summing to `total` (Ingest contract).
- D2 accept: same fix as B2.
- D3 accept: same fix as B1; the join key is the notice id on both gfile lines.
- D4 accept: URL-keyed ledgers have no client field; source client resolves by url key to exactly one client in the tools' findings, else withheld; host = the extension's registrar check (new ASSUMPTIONs).
- D5 partial: file-mtime fallback for filing time is banned (null instead); the former cutoff keeps the conservative rule and also excludes undated events first seen after `status_since`.
- D6 accept: a late DELETE could unlink a re-enrolled watch, and Phase 4 needs the mapping at purge; `client_watches` is keyed by `watch_id`, untouched by delete, removed by the Phase 4 purge.
- D7 partial: ADR-0070's append-only log is kept by making ignore non-destructive (events stay, never served) and serving notice/notice_outcome in `events`; the read-time join stays rather than writing derived rows.
- D8 accept: gone-after-notice attribution fixed (D8 = B8) and Phase 2's Mega `deleted` counts as gone; the "link-only never gone" rule removed.
- D9 accept: came_back with visible 0 now picks `clean` first whenever visible is 0 (Offer).
- D10 accept: first-daily input added (`first_daily_at`); brand, contact_url and cached are taken from Phase 1, the Today strip from Phase 2 (Depends on).
- D11 partial: persistent Undo was unasked scope; Undo kept only on the line shown right after "Not now".
- D12 accept: Acceptance could pass with three repos disagreeing; it now requires the contract file to exist and carry `notices_updated_at`, then the Relay test reads it.
- D13 accept: stories 16, 19–21, 29, 44, 46 and 48 gained test cases in the Relay, app, Removal service and laptop suites.
- D14 accept: the demo snooze route was unclassified; moved to `/admin/leaks/watches/{account_id}/offer-snooze`, under Phase 1's demo LOCKED rule, and renders disabled in the demo.

Cross-Phase:
- Binds Phase 1: when Cell routing for `/admin/leaks` lands, its account-path patterns must include `leaks/watches` so the snooze route routes by account (B11).
- Binds Phase 1: Probe state gains `dead_since`, copied onto gone events; owned here unless Phase 1 already records the first dead probe (B8/D8).
- Binds Phase 4: the purge deletes `client_watches` rows by `watch_id` after reading their status, and retention covers ignored and withheld Notices (D6, D7).

Counts: 18 accept, 8 partial, 2 reject, 0 needs-human.

Cross-Phase lines above, applied in the plan review: the `dead_since` line is now Phase 1's (Phase 1 Review, cross-Phase from P3); the Cell-routing line is recorded under Phase 4's cell-mode ASSUMPTION, not as a Phase 1 requirement; the purge line is met by Phase 1's `WATCH_TABLES` hook, and retention is decided here (Six hats 6, 7).

### Six hats
One six-hats pass over the four specs, 2026-11-27. Bullets touching this Phase:
- 6 (Phase 4 says Phase 3 drops `client_watches` at delete; Phase 3 keeps it for the purge) — **accept**: the row stays until Phase 1's purge removes it through `WATCH_TABLES`. It no longer needs reading first, because Notices are kept by linked source, not by watch.
- 7 (nobody owns "Notices for non-clients are not kept" or withheld/ignored retention) — **accept**: this Phase owns it. Withheld events are counted, not stored; ignoring deletes a source's stored events; linked sources' Notices are the owner's case records. This overturns D7's non-destructive ignore: ticket 10 is rung 2, ADR-0070's append-only rule covers the Leak event log, and the notice store is a replayable copy of the owner's ledgers.
- 10 (`dead_since` into Phase 1) — **accept**: Owns, Depends on and the `dead_since` ASSUMPTION now read Phase 1's field.
- 13 (`first_daily_at` counts only `ok`) — **accept**: it counts `ok` or `partial` (Tracker API additions, new ASSUMPTION).
- 16 (the Cell-routing ask on Phase 1 is moot) — **accept**: moved under Phase 4's cell-mode ASSUMPTION.
Counts: 5 accept, 0 partial, 0 reject.


### Fable round 3 (2026-11-27)
- C1 (e2e skip convention differs between Phases) — **accept**: the contract-test ASSUMPTION now refers to Phase 1's convention (Seam 6): skip without the other checkout, write the output file when run, and Acceptance requires the file, which this block already does.
- Sizing (Demo tracker leaves Phase 1) — **accept**: the Demo section, stories 49–50, the `demo/` Owns line, the demo seam and Depends on now say Phase 4 builds the demo states on its Demo tracker; this Phase keeps Phase 1's tracker-off test green.
- Cut 5 (Hide setting and snooze Undo) — **partial**: Hide stays (ticket 06 states it) and the 7-day agency-wide snooze stays (06); Undo is cut and parked because 06 does not state it (story 44, Snooze route `{snoozed: true}` only, card copy, both tests, Out of Scope; the Undo ASSUMPTION is removed).
- C2, C3, C4, cuts 1–4 and 6 — not this Phase's.
