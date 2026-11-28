# Plan review: Leak tracker, Phases 1–4

Reviews the leak-tracker plan (four Phases) and its four specs on 2026-11-27:
- `docs/spec/phase-01-leak-tracker-ae-tracer.md`
- `docs/spec/phase-02-leak-tracker-discovery-and-budget.md`
- `docs/spec/phase-03-leak-tracker-notices-and-offer.md`
- `docs/spec/phase-04-leak-tracker-bell-purge-public.md`

Inputs: one codex review per spec (blind call, then draft call); one six-hats pass over the set (20 bullets); coordinator rulings on bullets 1, 10, 11, 17 and 20. Spec-level bullets are reconciled in each spec's `## Review` under `### Six hats`, and cross-Phase lines in the spec they bind. This file holds the set-level lines.

ASSUMPTION: this file is `plan-review-leak-tracker.md`, not `plan-review.md`, which belongs to another effort (rung 3, the per-effort `plan-review-promo-preempt.md`). Overturned if the coordinator wants one shared file.

## Workstreams

| Wave | Phase | Spec | Depends on |
|---|---|---|---|
| 1 | 1 AE tracer, three slices in order: A AE-visible (gates, key, enrol, seed, roster, demo-off test, leak-check), B daily probes, `dead_since`, report, C delete, tombstones, watch purge, 410 drop | `phase-01-leak-tracker-ae-tracer.md` (Further Notes, Ticket slices) | none |
| 1 | 4 slice: Front door allowlist fix (`/admin/agency-notifications` in both `CONTROL_PATHS` mirrors) | `phase-04-leak-tracker-bell-purge-public.md` (Front door fix, story 18) | none; touches no tracker code |
| 2 | 2 Discovery lanes, budget, judge | `phase-02-leak-tracker-discovery-and-budget.md` | Phase 1 |
| 2 | 3 Notice feed, Service status, Removal offer | `phase-03-leak-tracker-notices-and-offer.md` | Phase 1 (Phase 2 for discovery counts in the offer angles) |
| 3 | 4 Bell, tenant offboarding, backups, key revoke, public enablement, plus the pieces moved from Phase 1 in Fable round 3: rename rule, paused push on the kill switch, orphan logging, Demo tracker, empty-Agency rebind | `phase-04-leak-tracker-bell-purge-public.md` | Phases 1–3 |

## Public-first wave order (owner 2026-11-27)

Owner, rung 2: "I want it live on inflowwww" — the target is the public app.inflowwww.com, not only the AE pilot. Phase 4's public flip (ticket 64) is pulled forward; everything not on the route to a working public deploy trails it. Fable round 4 (2026-11-27) shaped the cut; the build map `.scratch/leak-tracker-build/map.md` carries the same table.

| Wave | Tickets | Why here |
|---|---|---|
| 0 | 01, 02, 46; this re-plan; Phase 2 proxies-off fix | Leak-check must land before any tracker code rides a deploy-all; 46 touches no tracker code |
| 1 CRM slice A | 04 (+47), 05, 06, 08, 69, 65, 66 | Page, gates, key, enrol, drill-in, disclaimer; selftest + Twin red before the first deploy carrying 04 |
| 1 Service S1 | 03, tracker DB + `/v1` (me, creators, leaks, PUT/DELETE watch), seed (07 service side), golden `/v1` JSON both sides test against, service deploy runbook (HTTPS host, `tracker_cli` tenant + key) | Freezes the contract before the CRM depends on it |
| 2 P1 slices B, C | 07, 09, 10, 11, 12, 13, 14, 15, 16, 17 | Daily probes, delete, tombstones, purge, cross-repo tracer; 12 before the first real scan |
| 3 P2 lanes | 18, 19, 20, 21, 22, 23, 25, 26, 27 | Mega, listing recheck, Google fresh + weekly (Browserbase, proxies off), budget, Today strip |
| 4 P3 offer path | 41 (Service status `none` branch only), 42, 43, 74 (no Taken down until notices), 75, 76, 80 | Contact-only offer and the Start removal popup; the service reads carry `service_status: none` until 38 |
| 5 Public flip | 64, public-sync, deploy-all, env on the public host | `LEAK_TRACKER_ENABLED` + `LEAK_TRACKER_URL` set on app.inflowwww.com only; Twin and the demo stay off |
| Trail | 24, 28–40, 44, 45, 48–63, 67, 68, 70–73 (previews, legal go), 77–79 | After the flip. Deadlines: 60 before any key goes to a third-party Agency; 57 before the kill switch is relied on to stop spend |

ASSUMPTION: 42 and 76 render on the `none` branch with no Notice feed (ticket 42's own `none`/`former`/`unknown` rule), so the notice chain 33–40 trails the flip. Overturned if the owner wants Removal track counts live at the flip; then 33–41 move into wave 4.

Owner 2026-11-28, rung 2: "turn all true by default for all if they connect a model they get tracked, all consent is ok its all accessible on google" — `leak_tracker` defaults on (only an explicit `false` turns it off), an instance `LEAK_TRACKER_KEY` stands in for Agencies with no own key, every connected OnlyFans Creator is auto-tracked (`consent_by` `auto:owner-default`) unless the Agency deleted or turned it off, and the per-Creator consent box is gone.

ASSUMPTION: Changing LEAK_TRACKER_KEY to another tracker account is not supported in place; instance-bound watches would need a manual move.

## Adversary

- Phase 1: codex — 12 accept, 10 partial, 1 reject, 0 needs-human. Six hats 9 accept. Cross-Phase 5 accept, 1 reject.
- Phase 2: codex — 13 accept, 8 partial, 8 reject, 0 needs-human. Six hats 4 accept.
- Phase 3: codex — 18 accept, 8 partial, 2 reject, 0 needs-human. Six hats 5 accept.
- Phase 4: codex — 21 accept, 3 partial, 5 reject, 1 needs-human (D12, backup inventory). Six hats 10 accept, 1 partial. Cross-Phase 6 accept, 1 partial.
- Visuals (wayfinder tickets 11–14, 2026-11-27): codex — 40 accept, 15 partial, 1 reject (cutting the popup and imagery contradicts the owner's ask), 1 needs-human (legal go for previews).

## Six hats

Per bullet, across the specs it touches (spec lines carry the detail):
- 1 rebind rule — **accept** (P1, P4), superseded in Fable round 3: the rule now lives in Phase 4 (story 23), and Phase 1 always refuses a foreign tenant. Original line: one rule, Phase 1's. A foreign tenant gets 422 while the Agency has any watch or tombstone, and the binding moves when it has neither. Phase 4 refers to it and drops the backfill.
- 2 stale Phase 4 claims, one clamp — **accept** (P1, P4).
- 3 `identity_note` column — **accept** (P1, P2, P4), superseded in Fable round 3: it is a Phase 4 additive column with the rename note.
- 4 `first_run` → `seen.first_scan` — **accept** (P4).
- 5 `capped`/`complete` from `lane_day` — **accept** (P4). ADR-0075 and the CONTEXT Leak event log are amended so that `scan_partial` is a watch-scoped `lane_day` row.
- 6 `client_watches` at purge — **accept** (P3, P4): it joins Phase 1's `WATCH_TABLES`.
- 7 Notices for non-clients — **accept** (P3, P4, set). Phase 3 owns Notice retention:
  - withheld events are counted, not stored;
  - ignoring a source deletes its stored events;
  - linked sources' Notices are the owner's case records.
  - No purge in any Phase touches a Notice, so the daily full replay can't undo a purge.
- 8 adoption and purge lists — **accept** (P4).
- 9 link-only Gone pill — **accept** (P1).
- 10 `dead_since` into Phase 1 — **accept** (P1, P3, P4).
- 11 watch purge into Phase 1 — **accept** (P1, P2, set):
  - Phase 1 now has `tracker_purge`, `tracker_cli purge [--dry-run]`, `deleted_ids` pruning and the `WATCH_TABLES` hook.
  - Phase 4 keeps backup roll-off, tenant offboarding, key revoke, the bell and public enablement.
  - This matches the plan's own Phase 1 line ("delete endpoint with 30-day purge").
- 12 agency-user delete — **accept** (P1): the tombstones land inline, and the delete answers 409 while any is pending.
- 13 `first_daily_at` counts `partial` — **accept** (P2, P3).
- 14 `! grep`, `cd`, `nice` — **accept** (P4).
- 15 expected sample counts — **accept** (P1), superseded in Fable round 3: the report prints plain counts with no bound; the defaults hold until Phase 2's pilot.
- 16 Cell-routing ask — **accept** (P1, P3): it goes under Phase 4's cell-mode ASSUMPTION.
- 17 cut unasked work — **partial** (P4, set):
  - the Front door fix stays in Phase 4 as its own independent slice;
  - the webhook becomes a log line;
  - the 7-day overlap and `key rotate` go, because rotation is issue then revoke (rung 5);
  - deploy-all stays a four-target report that goes red only on Twin (coordinator), not a Twin-only check. Superseded in Fable round 3: `live.py` checks only Twin's gate.
- 18 seed never reuses a stored Quick scan — **accept** (P2).
- 19 drifted glossary — **accept** (set). In CONTEXT's Leak tracker group:
  - Leak watch is keyed by `agency_user_id`;
  - the tombstone lists its 7 columns;
  - Probe state lists `first_dead`, `flaps`, `last_live_at` and `dead_since`;
  - the Purge line names Phase 1;
  - **withheld** is added.
- 20 owner items — **accept** (set): see Needs the human. Twin sign-off is covered by Twin staying off (Phase 4 deploy-all red).

Counts: 19 accept, 1 partial, 0 reject.

## Fable round 3

Fable advisory on 2026-11-27. Each spec reconciles it under `### Fable round 3 (2026-11-27)` in its `## Review`.
- C1 e2e test convention — **accept** (P1, P3): it prints SKIP and exits 0 without `$REMOVAL_REPO`, and writes `$LEAK_E2E_OUT` when it runs. Acceptance exports the variable and checks `test -s`. Phase 3 refers to the convention.
- C2 D4 says the purge is Phase 4's — **accept** (P1): D4 now says Phase 1's.
- C3 `identity_note` and the rename note — **accept** (P1, P2, P4): both move to Phase 4, with the column added by the boot's additive-column pass.
- C4 404 `watch_purged` against 410 — **accept** (P1, P4): a 410 `watch_deleted` is the one status on PUT and reads, the CRM drops the row with no tombstone, and `deleted_ids` stays while the tenant row exists.
- Phase 1 sizing — **accept** (P1, P2, P3, P4):
  - Phase 1 ships as three slices: A AE-visible with leak-check, B probes and report, C delete and purge.
  - The rename rule, the paused push on the kill switch, orphan logging, the Demo tracker and the empty-Agency rebind move to Phase 4 (stories 49–52 and 23).
  - In Phase 1 the demo keeps the tracker off (`demo/tests/test_leak_tracker_off.py`).
- Cut 1 offboard/reinstate and adoption-restore — **reject** (P4): ticket 10 states both.
- Cut 2 four-target deploy-all report — **accept** (P4): `live.py` checks only Twin's gate (ticket 03 "Twin: off"), and the report is parked.
- Cut 3 95 % bound and CSV sampling — **accept** (P1): the report prints plain counts, because ticket 02 asks only for a measured rate. Parked.
- Cut 4 waitlist and least-loaded slots — **reject** (P2): ticket 04 and the goal state both.
- Cut 5 Hide setting and snooze Undo — **partial** (P3): Hide and the 7-day snooze stay (06), and the Undo is parked.
- Cut 6 `?day=` — **reject** (P4): ticket 07 names it.

Counts: 7 accept, 1 partial, 3 reject.

## Cut (YAGNI)

- Google CSE, Serper, Bing, DuckDuckGo, Brave lanes — CSE quota is shared with the owner's tools; Serper was cut in Fable round 2; the rest were never planned (P2).
- Suggested alias chips, the OnlyFans + Fansly "same person" link — cut in Fable round 2; aliases stay manual (P1, P2).
- The CSV export, pause reasons — cut in Fable round 2 (P1, P2, P4).
- The 30-day trend sparkline — no Phase lists it, and the owner's ticket 08 layout (variant D) has none (P1, P2).
- A headless-browser fallback, Telegram crawling — unmeasured browser cost; a `site:t.me` query covers Telegram (P2).
- Crawl worker-hours in admission — ticket 04 refuses on loads only (P2).
- Thumbnails, media, page bodies, any CRM fetch of a Leak — never (tickets 08, 10).
- Filing Notices from the CRM, billing and entitlement, a one-off "scan now" — out of the map's scope (P1, P2, P3).
- An in-app removal request — 06 chose a chat link (P3).
- A Bing Notice channel — no ledger exists (P3).
- Recovering history lost from self-overwriting ledgers — it can't be recovered (P3).
- A per-Creator offer mute or per-viewer snooze — 06 fixed a 7-day agency-wide snooze (P3).
- An export of Notices — the CSV was cut (P3).
- Price or revenue on the offer card — banned by 06 (P3).
- Running the exporter more than daily, or pulling from the laptop — ADR-0077 (P3).
- Telegram, email or OS push channels — the CRM has no agency sender (P4, ticket 07).
- A sidebar badge — `NavLink` has no badge field (P1, P4).
- A per-Creator bell mute — the Creator toggle already stops scans (P1, P4).
- The failed-day bell row — cut in Fable round 2; failures show on the page and in the service log (P4).
- An ops webhook, `ops_alerts`, `key rotate`, key expiry, a 7-day overlap — cut here (six-hats 17); a log line and issue-then-revoke cover them (P4).
- A past day's Leak list under `?day=` — the strip shows counts (P4).
- Creating tracker backups — none exist; the plan asks only for roll-off (P4).
- A timer for the public flip — owner flip only (ticket 03) (P4).
- Naming the brand in public copy — owner call, ADR-0074 (P4).
- Turning Twin on — needs the owner's sign-off (P3, P4).
- Slop runs — no mass send or concurrency path on the CRM side (P2, P3).

### Parked until after the pilot (Fable round 3)

- The deploy-all four-target tracker report — ticket 03 says only "Twin: off"; `live.py` checks Twin's gate alone (P4).
- The 95 % confidence bound and the CSV label sample — ticket 02 asks only for a measured rate; the report prints plain counts (P1).
- The snooze Undo — 06 does not state it; Hide and the 7-day snooze stay (P3).

## Not yet specified

- The global capacity number after the pilot (ticket 04): Phase 2 measures it, and no spec sets it.
- A live Fansly handle source (ticket 05): Fansly handles stay typed and unverified.
- Cell routing of `/admin/leaks`: the tracker is off in cell mode (P4). The routing spec must include the `leaks/watches` account-path pattern (P3).
- A Twin integration and its Removal offer: off until the owner signs off.
- ADR-0076 still names the tombstone as (watch_id, requested_at) and lists three delete triggers; Phase 1 has 7 columns and adds the agency-user delete. It was outside this pass's permitted files, and the coordinator may amend it.
- CONTEXT's Demo tracker line names Phase 1, and its Purge line says `deleted_ids` is pruned after 30 days. After Fable round 3 the Demo tracker is Phase 4's and `deleted_ids` rows stay while the tenant row exists. Coordinator checked: the CONTEXT lines name no Phase for the Demo tracker and say nothing of `deleted_ids` pruning, so they stand; ADR-0076 now states that `deleted_ids` is kept for the tenant's life.

## Open questions

Every ASSUMPTION in the four specs, sharpest first, with what falls if it is wrong. P<n> marks the spec.

1. P4: no tracker DB backup exists outside the repo (evidence blocked). Wrong → purged watches survive in a host or provider backup past 60 days, and the consent attestation's promise is broken.
2. P3: a "non-client" is an unlinked or ignored source client, and a linked source is kept whatever its watches' Service status. Wrong → Notices of linked clients with no `active`/`former` watch are kept against ticket 10, and the ingest must also withhold them.
3. P1: the tracer's plain counts decide nothing on their own, so the defaults hold through Phase 2's pilot. Wrong → the 7-day report already shows a flap rate well over 2 % on many observations; the 2-probe rule is then revisited before Phase 2.
4. P2: the pilot caps (300 daily loads, 2000 judge calls, 5 Creators, 1000 monthly loads) are arithmetic, not measured. Wrong → the waitlist bites too early, or spend overruns until the usage report resets them.
5. P1: an agency-user delete lands its tombstones inline and answers 409 while any is pending. Wrong → an admin can't delete a user while the Removal service is down, or the owner wanted the delete to go through and carry the key.
6. P4: the 30-day undo is automatic adoption on re-enrolling the same (tenant, account). Wrong → an Agency can't start fresh inside the window; the PUT needs a "start fresh" flag.
7. P3: withheld events are counted, not stored, so a newly linked source shows at the next replay. Wrong → the owner expects Notices to appear at link time; they then run the exporter by hand.
8. P1: the seed runs the Quick scan's candidate step privately and never reuses a stored scan, for at most 5 Creators per tenant. Wrong → the seed reads a slug-addressed stored scan, or misses what the full Quick scan finds.
9. P1: the DELETE's `requested_at` is clamped to the watch's life. Wrong → if client time can't be trusted, an outage's delay must be disclosed instead.
10. P1: `deleted_ids` rows, including purged watches' ids, stay while the tenant row exists. Wrong → the table grows large enough to matter; rows older than the tenant's last sync are then pruned.
11. P1: the watch purge's `WATCH_TABLES` hook covers every later watch-keyed table by `watch_id`. Wrong → a table keyed otherwise keeps a purged watch's rows; it then registers its own delete.
12. P1/P4: Phase 1 always refuses a foreign tenant; Phase 4 rebinds an Agency with no watch and no tombstone; clearing the key is refused while a tombstone is pending. Wrong → an AE Agency must move tenants during the tracer (Phase 4's rebind ships early), or the owner wants a migrate-tenant path.
13. P3: "on delete, the agency link is removed" is met by hiding at once, with `client_watches` purged by Phase 1. Wrong → the row must go at the DELETE.
14. P4: the tracker is off in cell mode until a spec routes `/admin/leaks`. Wrong → cell-mode Agencies expect the tracker; the routing spec is then needed first.
15. P2: a watch-scoped `scan_partial` lives in `lane_day`, not `leak_events`. Wrong → ADR-0075 must give the log watch-scoped events (this pass amended it to agree).
16. P1: `dead_since` is the first dead probe of the current run, kept through blocked and unknown probes. Wrong → a blocked probe should break the run, which changes the gone-after-notice dates.
17. P3: "Gone after notice" uses Phase 1's `dead_since`; a Leak without it is in neither gone count. Wrong → early gone spells undercount.
18. P2: a Mega `deleted` flag on two daily lookups makes a link-only Leak gone. Wrong → Mega packs flap or the flag means something else; Gone counts are inflated.
19. P4: a failed Daily-scan day is one log line, with no dedupe. Wrong → the owner wants a push; the fleet's `ALERT_WEBHOOK_URL` pattern is then the precedent.
20. P4: a key change is `key issue`, then `key revoke` when the owner chooses. Wrong → keys must expire on their own, or Agencies must be told a date.
21. P4: `live.py` checks only Twin's gate and goes red when it reads on; the four-target report is parked. Wrong → the owner wants every target's tracker state reported, or a red on public before their flip.
22. P4: adoption gives fresh `weekly_slot`/`plan_loads` and drops `carry_json`. Wrong → a restored Creator loses their weekday slot or a carried query.
23. P4: the tenant purge loops Phase 1's per-watch purge. Wrong → a large tenant makes the daily pass slow; it then batches by tenant.
24. P4: revoking every key stops scanning but starts no purge clock. Wrong → revoking the last key should offboard.
25. P4: the feed gate checks key presence, not validity. Wrong → a revoked-key Agency keeps its old rows visible.
26. P4: a capped day is a cap-reason `lane_day` row, and a failed day is any failed Daily scan. Wrong → the owner wants news filed through partly failed days.
27. P4: `leak_daily` runs only on the single Relay or the Control cell. Wrong → notifications move to data cells.
28. P4: a muted `leak_daily` preference files nothing, and re-enabling files only the 3-day window. Wrong → muted days must be backfilled further.
29. P4: `?day=` shows counts only; it stays because ticket 07 names it (Fable round 3 cut 6 rejected). Wrong → the owner wants the day's Leaks listed, which needs a filter on the leaks read.
30. P4: row text drops zero parts and uses UTC. Wrong → an owner copy call.
31. P4: adoption moves history to the new id and never revives the old one. Wrong → none known.
32. P1: a 410 `watch_deleted` is the one status for a deleted, purged or unseen-deleted id, and the CRM drops `leak_watch` with no tombstone; no 404 `watch_purged` exists. Wrong → the CRM must tell purged from deleted, or keep an "ended" marker; a field in the 410 body then says which.
33. P4: the delete triggers are Phase 1's, and this Phase owns the selftest plants. Wrong → Phase 1 ships the plants; story 44 is then done.
34. P4: the Demo tracker, moved from Phase 1, runs in-process as the demo's Tracker API and the tests' fake, and Phase 2 and 3 demo states are built on it in Phase 4; until then the demo keeps the tracker off. Wrong → Phase 2 or 3 demo work must ship first, or it is demo-only and seam 1 needs a loopback stub.
35. P3: `first_daily_at` counts a `partial` day. Wrong → the offer waits for a full-coverage day.
36. P3: Notice entries are a read-time join through the mapping. Wrong → ADR-0075 is read as requiring copies, which needs an attach job.
37. P3: the feed counts as updated only on a complete run; rejected and withheld rows count toward completeness. Wrong → any rejection should keep the feed stale.
38. P3: a missing or malformed ledger aborts the whole run. Wrong → one broken tool stalls every tool's freshness.
39. P3: a URL-keyed ledger gets its source client by exact url key from the laptop tools' findings. Wrong → many rows come back withheld in the dry-run reconcile.
40. P3: every URL of a `partial` Google notice is dropped. Wrong → a per-URL accepted list exists and Notices are undercounted.
41. P3: Delisted = an approved `google_dmca`/`google_outdated` decision. Wrong → "outdated" approvals mean something else, and Delisted overclaims.
42. P3: the outdated ledger yields approved/denied decisions (rung 1). Wrong → the same as 41.
43. P3: the Google filer's `stage` is its source client. Wrong → `stage` spans clients, and the mapping misattributes.
44. P3: the form extension's `host` class is its registrar check; other abuse desks are `site`. Wrong → the channel counts shift.
45. P3: stamps with form `links` are `site`, and `bing` stamps are dropped. Wrong → `links` is a non-site form.
46. P3: `src_client` goes inside `filing_ref`. Wrong → the owner prefers a seventh hashed field, and ids change.
47. P3: a ledger diff is the content id, so A→B→A does not re-append. Wrong → the owner needs every flip.
48. P3: `src` values are generic. Wrong → the tools' own names, which must stay out of docs.
49. P3: any Leak kind counts as gone when its log says gone. Wrong → link-only Leaks are kept out of the Removal track.
50. P3: `unknown` is set only by the owner; no mapping means `none`. Wrong → the service infers `unknown`.
51. P3: `contact_url` arrives with its prefill. Wrong → the CRM owns the prefill text.
52. P3: a stale feed replaces counts only, and dated lines stay. Wrong → the lines are hidden too.
53. P3: a fifth offer line, "{n} leaks are up right now." Wrong → an owner copy call.
54. P3: Admin is an assigned `admin` role id, whatever the enforcement setting. Wrong → Admin follows enforcement.
55. P3: "Hide removal offers" lives in Settings › Preferences. Wrong → it moves to the tracker page.
56. P3: no snooze Undo (parked, Fable round 3); a snooze is final for 7 days. Wrong → mis-clicks matter; the Undo comes back after the pilot.
57. P3: the demo disables contact through `demo.patch.swap`. Wrong → a preview flag from the Demo tracker.
58. P3: the snooze route is `/admin/leaks/watches/{account_id}/offer-snooze`. Wrong → the demo lets visitors snooze.
59. P3: the end-to-end contract test lives in the Removal service repo and follows Phase 1's e2e convention. Wrong → CI can't hold both checkouts, so it runs on the laptop only.
60. P3: the Ingest key is one sha256 in the service env. Wrong → a second ingest source appears.
61. P2: the Google fresh pass OR-joins the handle, aliases and socials into one load. Wrong → OR misses handle-only finds, and aliases need rotating.
62. P2: Leaks first seen by a lane's first run read "Found on first scan". Wrong → a false "new" wave on the first Weekly slot is accepted, or per-lane first scan is dropped.
63. P2: a judged-real Leak's `first_seen_at` is the judgement time. Wrong → New today should reflect discovery time.
64. P2: only spending lanes wait on a cap. Wrong → an over-allowance tenant gets probes only.
65. P2: judge calls reserve against a global daily judge cap as their own unit. Wrong → judge spend is negligible and the unit is dropped.
66. P2: judge calls skip the tenant's monthly allowance. Wrong → per-tenant judge spend is material.
67. P2: a weekly pass cut by the cap carries its leftover once. Wrong → carry days peak, and leftovers wait for the slot.
68. P2: same query, same UTC day, fetched once via `serp_cache` and charged to the first reserver. Wrong → each tenant is charged its own share.
69. P2: the Creator cap is checked at reserve time by `created_at` rank. Wrong → a lowered cap pauses watches instead.
70. P2: paused watches keep their slot and capacity. Wrong → capacity is tight and paused watches are released.
71. P2: refused enables are retried daily by Phase 1's sync. Wrong → the owner wants a manual retry.
72. P2: the listing recheck is capped at 20 per watch, rotating oldest-first. Wrong → watches rarely pass 20, and the ceiling goes.
73. P2: Google visibility is per (vertical, field), and an emptied set is unknown. Wrong → Leaks show Cached on a query a field never ran.
74. P2: unsure hits get one more round, and unjudged rows are deleted at 30 days. Wrong → real Leaks are found among the expired rows.
75. P2: the tracker load cap counts tracker loads only. Wrong → one shared Browserbase budget must be capped together.
76. P2: the registry crawl is plain HTTP. Wrong → key hosts are JS-only.
77. P2: `proxy_bytes` comes from the session report, else 0. Wrong → no bytes are reported, and the report shows minutes only.
78. P2: the judge prompt is catalogued in the Removal service repo, not `docs/prompts/`. Wrong → the owner wants a public entry.
79. P2: module and path names follow house precedent. Wrong → a rename only.
80. P1: the CRM mints `watch_id`. Wrong → the service mints ids, which needs a pending-create state and an account-keyed delete.
81. P1: the tombstone carries `agency_user_id`, `account_id`, `tenant_id`. Wrong → keys become deployment-wide.
82. P1: a DELETE of an unseen id is remembered so a late PUT gets 410. Wrong → a late first PUT after 30 days.
83. P4: `identity_note` is one additive column, added in Phase 4 with the rename note and shared with the restore note. Wrong → both must show at once, so it becomes a list.
84. P1: the relay compose passes both env vars with empty defaults. Wrong → AE injects env another way.
85. P1: enrol, edit, Tracking and Delete are Owner/Admin only. Wrong → Team Leaders manage watches.
86. P1: the role gate fails closed and ignores `enforce: false`. Wrong → the tracker follows the enforcement switch.
87. P1: a multi-Agency context answers 404. Wrong → multi-agency employees need an Agency picker.
88. P1: the roster lists the Creator switcher's Creators. Wrong → Team Leaders should see every Creator.
89. P1: the nav reads the effective flag from `/settings/applied`, with no new toggle. Wrong → the owner wants a settings toggle.
90. P1: a key is stored only after `/v1/me` answers 200. Wrong → owners must paste while the service is down.
91. P1: the read cache is in-process, with no TTL. Wrong → a restart showing "not reachable" confuses; it moves to a DB row.
92. P1: the sync is hourly, so a pause lands within about an hour. Wrong → an instant pause is needed; the toggle then pushes inline.
93. P1/P4: in Phase 1 a Deployment switch off makes the sync send nothing while tombstones still land; Phase 4 adds the paused push for watches the service holds. Wrong → the tracer needs the kill switch to stop spend at the service (Phase 4's push ships early), or "off" must mean zero egress.
94. P4: orphan watches are logged, never deleted (moved from Phase 1). Wrong → orphans pile up; an owner-confirmed cleanup is added.
95. P1: `creators_max` 5 until Phase 2. Wrong → it is superseded by Phase 2's cap.
96. P1: seed admission is a URL containing the handle or a strong alias after normalising. Wrong → the measured seed precision.
97. P1: a needle under 4 characters admits nothing; a Mega item needs a handle match. Wrong → a pilot Creator with a short handle.
98. P1: probes allow 5 redirects and 256 KB, and refuse private addresses. Wrong → real hosts need more to show the removal page.
99. P1: blocked and unknown probes neither break nor extend the dead streak. Wrong → the flap measurement.
100. P1: the report prints plain counts with denominators, no bound and no sample file, and the owner counts seed precision on the drill-ins. Wrong → Phase 2's pilot needs a bound; the bound and the CSV sample come back.
101. P1: Came back shows for 30 days. Wrong → the owner wants it permanent.
102. P1: one probe pass at 04:00 UTC. Wrong → superseded by Phase 2's Weekly slot spread.
103. P1: the key format is `ltk_` plus 40 base62 characters. Wrong → the service has a format, and the leak-check pattern follows it.
104. P1: the brand rule is at `report` level for AE. Wrong → AE's tree must also be brand-free.
105. P1: the e2e test prints SKIP and exits 0 without `$REMOVAL_REPO`, writes `$LEAK_E2E_OUT` when it runs, and Acceptance checks that file. Wrong → the house moves cross-repo tests out of `service/tests`.
106. P1: Phase 1 ships as slices A, B, C in that order. Wrong → slice C must land before AE enrols anyone; then C moves ahead of B.
107. P1: the tracer's rebind, kill-switch push, rename, orphans and Demo tracker wait for Phase 4. Wrong → AE needs one of them during the tracer; that piece ships early.
108. P2: the service keeps a thumbnail URL only for Google's own image CDN hosts, never a `data:` URI. Wrong → most pilot tiles are `data:`; then the full pass needs another source inside its reservation.
109. P2: Reveal is one page-level button held in memory. Wrong → the legal review wants per-tile reveal.
110. P2: the All Models strip is the 12 newest-seen previews across the viewer's Creators, not a "worst" rank. Wrong → the owner wants a severity order or one strip per Creator; then the service needs a per-Creator preview read.
111. P2: previews are `no-store` on both hops. Wrong → load measurements say it is too slow and the legal review allows a cache.
112. P2: Team Leaders see blurred previews and may reveal them. Wrong → the owner limits Reveal to Owner and Admin.
113. P2: no per-view audit of previews. Wrong → the legal review requires one.
114. P2: the Leak disclaimer's seen key is versioned for the preview line. Wrong → a second dialog is judged worse than missing the line.
115. P2: Agencies enrolled before previews need no new tick. Wrong → the legal review says the enable checkbox must name previews; then previews wait for an Owner or Admin re-tick.
116. P3: "Contact us to start removal" opens the Start removal popup instead of the link. Wrong → the owner wants the link one click away; then the card gets both.
117. P3: popup overlay scenes read `forum` as source `site_search` off X and `x` as Leak site `x.com` or `twitter.com`. Wrong → the service gains a forum Kind; then the mapping reads it.
118. P3: the popup video is Owner and Admin only. Wrong → Team Leaders should watch it.
119. P3: captions are required and there is no transcript. Wrong → an accessibility review asks for one.
120. P3: the Removal preview sits only in the popup, the Taken down gallery stops at 6 and keeps one generic after panel. Wrong → the owner wants it on the card, every Leak (paged), or per-Kind looks.
121. P1: the read cache keeps the last good response per (Agency, path), and a served copy is filtered to the viewer's Creator grants on every serve, as the live read is. Wrong → a cached copy can leak another Creator's rows; then the cache key gains the viewer's grant set.

## Owner answers (2026-11-27)

- Ticket 08 (owner, rung 2): the Inflowwww look. Creator names sit in the left Creator column with "All Models" on top, selected by default, showing the Today strip and one combined Leak list. One Creator shows its drill-in in the main pane, and phones get the house Creator dropdown (P1 stories 15, 34–37, 39 and 66). Removal is never self-serve: the only CTA is "Contact us to start removal", and the service owner links the client with the mapping CLI (P3 stories 24, 25, 41, 43, 50 and 51). The first open shows the Leak disclaimer, a bot-scrape notice dismissed once per person in that browser, and the demo shows it too (P1 stories 67–69). It replaces variant C. The prototype is variant D.
- Wayfinder tickets 11–14 (owner, rung 2: sliders, Google previews, a video popup to start removal). Phase 2's drill-in gains a List / Google view of media Leaks, with Google's thumbnails passed through by id, blurred by default, never stored, behind `LEAK_TRACKER_PREVIEWS` (off), and All Models gets one strip of the 12 newest-seen previews (P2 stories 47–58). Phase 3's contact CTA opens the Start removal popup: a captioned generic video served through the Relay, with the Creator's own Leaks drawn over it by the CRM on the service's cue times, the results as text, a Removal preview slider and the contact link; `active` and `former` Creators gain a Taken down gallery of at most 6 sliders (P3 stories 52–63). Phase 4's Demo tracker serves placeholders and the popup with no video. Build tickets 70–80.
- 2026-11-28 (owner, rung 2): paid Google lane on for every tenant (`TRACKER_PAID_TENANTS` dropped); scan on connect, then weekly or manual refresh (daily pass and the 00:00–04:00 pending window superseded); previews legal go, blurred by default, click to unblur; take-caption profanity OK, reddit = `forum` scene, >20 listings → partial OK, `came_back_30d` ASSUMPTION OK; offer video live, goldens unchanged. Spec: docs/spec/leak-tracker-cadence-and-previews.md (tickets 81–85, 70–73 amended).

## Needs the human

- **Phase 2:**
  - Resolved 2026-11-28: the legal go for Google previews is given (Owner answers).
- **Phase 4:**
  - D12, the backup inventory. Confirm that the Removal service host has no cron, provider snapshot or volume backup of the tracker DB, or name each one with its retention (at most 30 days after a purge).
- **Set:**
  - Twin sign-off is not needed now. Twin stays off, and deploy-all goes red if it turns on.
