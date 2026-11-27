# Phase 02 — Leak tracker: discovery lanes, budget, judge

**Objective.** Every unpaused Leak watch gets its Daily scan lanes (Mega lookup, listing recheck, one Google fresh pass) and its Weekly slot lanes (full Google pass, registry crawl). Every paid call is held by a Load reservation first. Title-only results reach the page only after the Leak judge says real. The page's Today strip and each Creator's lane coverage show exactly what ran, what waited and when it tries again. The AE pilot produces the cost-per-Creator and crawl-minutes figures the owner needs to set the real caps.

## Problem Statement
After Phase 1 an agency sees the Leaks the Quick scan seeded and whether each one is still up. Nothing new is ever found, though. A Leak posted yesterday on a pirate site, a new Mega pack or a fresh Google result stays invisible until someone runs a manual search. The owner's existing search stack can't just be switched on for every agency:
- its counters race;
- LLM spend is booked after the call;
- the free Google CSE quota is shared with the owner's own tools;
- nothing stops one agency, or a busy weekday, from spending the whole day's Browserbase budget.

And when a search does not run, nothing on the page says so. An empty day then looks like a clean one.

## Solution
The Removal service runs a fixed set of Leak lanes per Leak watch.

Every day it runs three free lanes and one Browserbase load:
- the Mega index lookup;
- a re-fetch of the Creator's known leak-site listing pages;
- one past-day Google web query.

Once a week, on the Weekly slot (the least-loaded weekday it was given at enable), it runs:
- a full Google pass over web, images and videos, at most 31 loads;
- a crawl of the known leak-site registry.

Before each paid call the service atomically reserves budget against three limits: the global daily load cap, the Tracker tenant's monthly load allowance and its Creator cap. When a cap is hit, that discovery waits, Origin probes keep running, and the day is marked partial. A new Creator that would push the busiest day over the cap goes on a waitlist instead of being half-served.

A result whose URL names the handle or a strong alias becomes a Leak at once. A result where only the title names them is a Pending hit: it stays hidden until the Leak judge (Jev first, then DeepSeek) calls it real.

In the CRM:
- The page opens with a Today strip: new today, came back, gone, and how many Creators were fully checked.
- Each drill-in lists every Leak lane with its last success, its next attempt, and anything skipped for budget.
- The identity form shows which aliases are searched on their own and which only beside the handle.

## User Stories
1. As a Team Leader, I want each tracked Creator's known Mega packs looked up daily, so that a new pack shows the day it is indexed.
2. As a Team Leader, I want a Mega pack that the index marks deleted on two daily lookups in a row to turn Gone, and one that merely drops off the index's first page to stay Listed, so that a short index page never fakes a removal.
3. As a Team Leader, I want the Creator's known leak-site listing pages re-read daily (oldest-read first, 20 a day, the lane reading Reduced on a day some waited), so that new posts on a site that already hosts them show within a day.
4. As a Team Leader, I want one past-day Google web search per Creator every day, so that fresh Google results show within a day.
5. As a Team Leader, I want a full Google search over web, images and videos once a week, on a fixed weekday, so that older and image-only Leaks are found without a daily bill.
6. As a Team Leader, I want the known leak-site registry crawled for each Creator once a week, so that sites Google doesn't show are still covered.
7. As a Team Leader, I want the handle searched in every lane, so that the Creator's main name is never dropped.
8. As a Team Leader, I want strong aliases (5 or more characters) searched on their own in Google web, the site searches and the weekly images and videos pass, so that a stage name finds Leaks that don't name the handle.
9. As a Team Leader, I want weak aliases (4 characters) only searched beside the handle, so that a short alias doesn't flood the page with strangers.
10. As a Team Leader, I want Instagram and X handles searched only in Google web, so that socials widen the search without leak-site noise.
11. As a Team Leader, I want the display name used only to confirm a hit and never to find one, Mega titles included, so that a common name never adds someone else's Leaks.
12. As a Team Leader, I want each alias in the identity form labelled "searched on its own" or "only with the handle", so that I know what a 4-letter alias buys.
13. As a Team Leader, when budget runs short I want aliases dropped first (last-added first), then Instagram and X, with the drill-in naming what was skipped, so that I can see which names weren't searched.
14. (Owned by Phase 4, its story 49, moved from Phase 1: the rename rule. Phase 2 only searches whatever aliases the watch holds; once Phase 4 lands, the old handle it inserts as alias #1 is searched like any other alias.)
15. As a Team Leader, I want a result whose URL names the handle or a strong alias to become a Leak at once, so that clear finds show the same day.
16. As a Team Leader, I want results where only the title names the Creator hidden until the Leak judge calls them real, so that the page never shows a guess.
17. As a Team Leader, I want results the judge calls fake never shown and never judged again, so that the same false hit doesn't come back daily.
18. As a Team Leader, I want the Creator's own OnlyFans, Instagram and X pages and the Removal service's own hosts never counted as Leaks, so that their real profiles don't inflate the count.
19. As a Team Leader, I want every Google image or video result stored as a `media` Leak linked to its landing page, with no image fetched or kept, so that image-only leaks are tracked without storing the content.
20. As a Team Leader, I want a known Leak marked visible in Google when a search returns it, and not visible only when the full pass ran every (vertical, field) query that ever returned it to the end and missed it, so that Cached never rests on a search that didn't run, and never sticks on a query that no longer runs.
21. As a Team Leader, I want Leaks found the first time a lane ever runs for a Creator to read "Found on first scan", not "new", so that a first full search doesn't look like a leak wave.
22. As a Team Leader, I want a Today strip at the top of the Leak tracker page (new today, came back today, gone today, Creators fully checked today), so that I see the day's change in one line.
23. As a Team Leader, I want each roster row to show New today and a "Partial check" marker on a day a cap or a failure cut its scan, so that a quiet row isn't mistaken for a clean one.
24. As a Team Leader, I want the drill-in to list each Leak lane with its last success, its next attempt and its state (OK, Waiting on budget, Reduced, Failed, Not run yet), so that I know how fresh each part of the picture is.
25. As a Team Leader, I want the page to state the freshness promise: known links daily; new Google results within a day, or a week on a reduced day; images, videos and new sites within a week. So that I know what "nothing new" means.
26. As a Team Leader, I want the page never to promise a "next full search" date, only each lane's next attempt, so that a capped week never breaks a promise.
27. As a Team Leader, I want a day whose Google load failed marked "Reduced", with no silent fallback to a weaker search engine, so that coverage is never overstated.
28. As an agency owner, I want a new Creator refused with "waitlist" when the service is at capacity, and retried daily until it is accepted, so that nobody gets a half-served tracker.
29. As an agency owner, I want a refusal at my agency's Creator cap to say so and show the cap, so that I know to ask the Removal service for more.
30. As an agency owner, I want the enable dialog to say beforehand when the service isn't taking new Creators, or my cap is full, so that I'm not surprised after filling the form.
31. As an agency owner, I want hitting a cap to never pause a Creator, so that link checks continue and only new searches wait.
32. As the owner, I want every paid call (every Browserbase navigation, wall retries included, and every judge HTTP attempt) reserved atomically before it is made, against the global daily load cap, the tenant's monthly allowance and its Creator cap (a watch ranked past a lowered cap reserves nothing), so that concurrent workers can never overspend.
33. As the owner, I want a reservation a crashed worker never settled to count as spent, so that a crash can't free budget that may have been used.
34. As the owner, I want each new watch's Weekly slot put on the weekday with the fewest planned loads, so that no weekday peaks.
35. As the owner, I want admission to refuse a new watch when its slot day or any day would pass the global daily load cap, so that a Creator gets its full plan as accepted; later identity edits and carried queries are absorbed by runtime trimming, never by passing the cap.
36. As the owner, I want a weekly pass that a cap cut short to carry its leftover queries to the next day once, then wait for the next slot, so that one busy day costs a day, not a week.
37. As the owner, I want the daily past-day loads of many watches batched into shared Browserbase sessions, so that the one-minute session minimum isn't paid per Creator.
38. As the owner, I want no Google CSE and no Serper in any Leak lane, so that my own tools' quota is never touched by discovery and every lane means the same thing. (Phase 1's enable-time seed runs the Quick scan's candidate step privately and never reuses a stored scan, the plan's "enable-time seed from the existing quick scan"; it is not a Leak lane.)
39. As the owner, I want per-tenant, per-day, per-lane usage totals (loads, sessions, billed minutes, proxy bytes, captchas, judge calls and tokens per judge model, crawl seconds, and confirmed finds), with no handles, so that the pilot measures cost and each lane's yield without keeping a browsing record.
40. As the owner, I want a `tracker usage` report giving cost per Creator per month and crawl minutes per Creator per week, so that I can set the real caps after the AE pilot.
41. As the owner, I want CLI commands to set the global daily load cap, the global daily judge cap, and each tenant's monthly allowance (the Creator cap stays Phase 1's `tenant cap`), so that I raise limits without a deploy.
42. As the owner, I want registry-crawl workers sized by an env setting, with each crawl's minutes recorded, so that I see when a second worker is needed.
43. As the owner, I want Pending hits never judged within 30 days deleted, so that unconfirmed URLs don't pile up.
44. Built by Phase 4 (its stories 48 and 52): the Demo tracker serves the Today strip, every lane state and a waitlisted Creator from fixtures. Until then the demo keeps the tracker off.
45. As a developer, I want every Phase 2 service table keyed by `watch_id` or `tenant_id` (the one-day `serp_cache` excepted, which holds no tenant data past its day), so that Phase 1's purge removes a deleted watch's discovery data with the rest.
46. As the owner, I want the same Google query on the same UTC day run once across all watches and tenants, charged to the first reserver, while each watch keeps its own Leak rows, so that two Agencies tracking one Creator don't pay twice (ADR-0070: scan work is deduped, Leak rows never shared).

## Implementation Decisions

**Owns.**

| Module | Repo | Change |
|---|---|---|
| Query plan (`tracker_plan`) | Removal service repo | New. Pure: Leak identity → per-lane query list, load count, trim order. |
| Load reservation (`tracker_budget`) | Removal service repo | New. Atomic reserve/consume/settle/expire. Cap CLI. |
| Admission + Weekly slot (`tracker_admission`) | Removal service repo | New. Waitlist and Creator-cap checks, least-loaded slot, backfill for Phase 1 watches. |
| Leak lanes (`tracker_lanes`) | Removal service repo | New. Mega lookup, listing recheck, Google fresh pass, full Google pass, registry crawl. Lane state. Hooks into Phase 1's Daily scan runner and Origin probe for lane state. |
| Admission of hits + Leak judge (`tracker_judge`) | Removal service repo | New. URL/title rule, host rules, Pending hits, Jev → DeepSeek. |
| Usage + report (`tracker_usage`) | Removal service repo | New. Tenant-level counters and the `tracker usage` CLI. |
| Tracker API read shapes | Removal service repo | Modified (Phase 1's routes). `accepting_new`, `today`, `lanes`, and the watch-upsert refusals. |
| Judge logic, Jev scorer, Google SERP URL and parser, query templates | Laptop leak tools | Read-only source, vendored into the Removal service repo the way the service already vendors code, rewritten onto the standard library and the service's existing fetch where the source imports `httpx` or `bs4` (the service image installs neither: its Dockerfile's only pip line is `Pillow curl_cffi playwright`). The laptop leak tools are not changed. |
| Leak tracker relay module (`leak_tracker_api`) | This repo, `service/` | Modified (Phase 1's). Passes the new fields through. Stores waitlist/cap refusals and retries them once per UTC day. The rename rule is Phase 4's. |
| `leak_watch` model | This repo, `service/db` | Modified. Two additive nullable columns. |
| Coverage logic (`leakCoverage.ts`) | This repo, `app/` | New. Pure: Today strip sums, lane rows, day markers, freshness copy. |
| `LeakTodayStrip`, `LeakCoverage` components; roster and drill-in | This repo, `app/` | New components; Phase 1's page and drill-in modified to mount them. |
| `leakIdentityForm.ts` reducer | This repo, `app/` | Modified (Phase 1's). Adds `aliasLane` and the trimmed-field note. |
| Demo tracker fixtures | This repo | Not here: Phase 4 builds the Demo tracker with every Phase 2 shape and state. |

**Interfaces.**
- `tracker_plan.build(identity, platform) -> Plan`.
  - `Plan` = ordered `QuerySpec(lane, vertical, text, pages, field)`, where `field` ∈ `handle` | `alias:<i>` | `instagram` | `x`.
  - `Plan.loads` is the sum of pages.
  - `Plan.trim(n)` drops whole `field` groups in the 05 order until `loads <= n`: aliases last-added first, then `x`, then `instagram`. If the handle group alone is still over `n`, it drops handle queries from the bottom of the table below (`site:t.me`, `mega.nz`, videos, images, `<platform>`, `leaked`, then web page 2) until `loads <= n`. It always keeps the handle's web page 1, so `trim(1)` returns exactly that query; `n = 0` means the pass waits.
  - It also returns the dropped fields and, for a cut handle group, the dropped handle queries.
- `tracker_budget.reserve(conn, tenant_id, watch_id, unit, n) -> Reservation | Refused(reason, next_on)`.
  - `unit` ∈ `load` | `judge_call`. `reason` ∈ `cap_global` | `cap_tenant_month` | `creator_cap`.
  - It runs in one `BEGIN IMMEDIATE` transaction. It refuses `creator_cap` when the watch ranks past `tenants.creators_max` among the tenant's non-deleted watches by `created_at`, so a lowered cap stops spend for the newest watches without pausing them. It sums held plus used for the global UTC day, and for the tenant's UTC month (loads only), then inserts the hold.
  - A partial grant is allowed: `reserve(..., n, partial=True)` grants `min(n, room)`, and the caller trims to it.
  - Also `consume(r, k)` (refuses past the hold), `settle(r)` (releases the unused part) and `expire_stale(now)`. A hold older than 2 h becomes `expired` and counts in full.
  - One unit is one outbound attempt. The vendored SERP backend consumes one `load` before every navigation, including its same-page retry in a fresh session after a wall; with the hold used up it ends the query incomplete instead of retrying. The vendored Jev and DeepSeek clients consume one `judge_call` before every HTTP attempt, retries included.
- `tracker_admission.admit(conn, tenant_id, identity) -> Slot(weekday) | Waitlist | CreatorCap(cap)`. Called inside Phase 1's watch-create transaction.
  - `projected[d]` = number of non-deleted watches (1 fresh load each) + Σ `plan_loads` of the watches whose slot is `d`.
  - Paused watches count, so resuming never needs admission.
  - `d*` = argmin `projected`, with the lowest weekday index on a tie.
  - Accept iff `projected[d*] + plan.loads + 1 <= daily_loads` and every `projected[d] + 1 <= daily_loads`, and the tenant's non-deleted watches < `creators_max`.
  - An identity edit on an existing watch recomputes `plan_loads` and is never refused: runtime trimming absorbs it, so after an edit the slot day can be planned past the cap and the reservation, not admission, holds the cap.
- `tracker_lanes.run_daily(watch, day)` and `run_weekly(watch, day)` run each lane in order and write `lane_state`, `lane_day`, `seen` and status events. Phase 1's `tracker_scheduler` tick calls them: `run_daily` inside its daily pass, `run_weekly` for each watch whose `weekly_slot` is today's weekday (or that holds `carry_json` for today). `run_fresh_batch(watches, day)` packs up to 12 single-load fresh queries per Browserbase session; that is the measured loads-per-billed-minute in the laptop leak tools' SERP backend docstring.
- Before any Google navigation, a lane looks up `serp_cache` by (UTC day, vertical, query text, page). A hit reuses that day's result and reserves nothing; a miss reserves, loads and writes the cache. The cache is cleared at the next UTC day.
- `tracker_judge.admit_hit(watch, hit) -> Leak | PendingHit | None` and `judge_pending(day)`.
- `tracker usage --since YYYY-MM-DD [--tenant T]`, `tracker caps global --daily-loads N --daily-judge N`, `tracker caps tenant T --month-loads N`. The Creator cap stays Phase 1's `tenant cap <tenant_id> <n>` (`tenants.creators_max`).
- Relay: no new route. Phase 1's `GET /setup` passes through `accepting_new`, `creators_max` and `creators_used` from `/v1/me`; the roster and drill-in reads pass through `today` and `lanes`. Phase 1's `PUT /watches/{account_id}` keeps `{synced}` and adds `admission: "waitlist" | "creator_cap" | null` and `creators_max?`, answering 200 after it saves the `leak_watch` row.
- App: `leakCoverage.ts` exports:
  - `todayStrip(creators) -> {new, cameBack, gone, firstRun, checked, partial, total}`;
  - `laneRows(lanes, now) -> Row[]` (label, state chip, last-success text, next-attempt text, skipped names);
  - `dayMarker(today) -> null | "partial" | "reduced" | "pending" | "paused"`;
  - `FRESHNESS` copy.
  - `leakIdentityForm.ts` adds `aliasLane(alias) -> "alone" | "with_handle"` (length ≥5 → alone).

**Schema.**

*Removal service DB (Phase 1's `tracker_db`, tracker tables only, never the Quick scan tables). Phase 1 tables are extended additively, never replaced:*
```
tracker_limits        (id=1, daily_loads INT, daily_judge INT)                        -- pilot 300 / 2000
tenants              + month_loads INT                                                -- pilot 1000; Creator cap is P1's creators_max
watches              + weekly_slot INT CHECK 0..6, plan_loads INT, carry_json TEXT NULL
load_reservation      (id, tenant_id, watch_id, unit, day, month, held INT, used INT,
                       state held|settled|expired, created_at, settled_at)
lane_state            (watch_id, lane, state, reason, last_attempt_at, last_success_at,
                       next_attempt_on DATE, trimmed_json, PRIMARY KEY (watch_id, lane))
lane_day              (watch_id, day, lane, outcome ok|partial|failed, reason NULL,
                       PRIMARY KEY (watch_id, day, lane))                             -- append-only, one row per lane run
pending_hits         + query_id, verdict pending|unsure|real|fake DEFAULT pending,
                       judged_by NULL, judged_at NULL, rounds INT DEFAULT 0          -- P1's seed queue drains through the judge
leaks                + google_fields_json, landing_key NULL                           -- media → landing
serp_cache            (day, vertical, text, page, results_json, PRIMARY KEY (day, vertical, text, page))
tracker_usage         (tenant_id, day, lane, loads, sessions, session_s, proxy_bytes, captchas,
                       jev_calls, deepseek_calls, deepseek_in_tok, deepseek_out_tok, crawl_s, finds,
                       PRIMARY KEY (tenant_id, day, lane))
```
Phase 1's `daily_scans.outcome` gains `partial`, set when any of that day's `lane_day` rows is `partial` or `failed`.

`lane_state`, `lane_day` and `load_reservation` are appended to Phase 1's `tracker_purge.WATCH_TABLES` (column `watch_id`), so a purged watch leaves no row in them; `test_tracker_lanes.py` asserts it. `serp_cache` is cleared at the next UTC day and `tracker_usage` holds tenant totals only, so neither is on the list.

*This repo:* `leak_watch` gains `admission` (TEXT NULL: `waitlist` | `creator_cap`) and `admission_tried_on` (DATE NULL). Both are nullable, so the existing additive-column path in `service/db/engine.py` adds them; no migration script.

**Contracts** (Tracker API, additive; readers ship before writers):
- `GET /v1/me` adds `accepting_new: bool` beside Phase 1's `creators_max` and `creators_used`.
- Phase 1's watch upsert adds `409 {"error": "waitlist"}`, and keeps its `409 {"error": "creator_cap", "creators_max": N}`, both only when it would create a watch. Updates and unpauses never get them.
- Each `GET /v1/creators` item adds `today: {day, state: pending|complete|partial|coverage_reduced|paused, new, first_scan, came_back, gone}`, derived from that day's `lane_day` rows and the Leak event log.
  - `new` counts confirmed Leaks whose `first_seen_at` is on `day` (UTC), excluding first-scan finds.
  - `gone` counts origin-status changes to `gone` that day.
- `GET /v1/creators/{id}` adds `lanes: [{lane, cadence: daily|weekly, state: ok|waiting|reduced|failed|never|paused, reason, last_success_at, last_attempt_at, next_attempt_on, trimmed: [{field, value}]}]`.
  - `lane` ∈ `origin_probe`, `mega_lookup`, `listing_recheck`, `google_fresh`, `google_full`, `registry_crawl`.
- The event log keeps ticket 02's closed set and Phase 1's payload names.
  - `scan_partial` is watch-scoped, so it is the `lane_day` row with outcome `partial` or `failed`, one per (watch, UTC day, lane), with `reason` ∈ `cap_global` | `cap_tenant_month` | `creator_cap` | `judge_cap` | `lane_failed` | `google_failed` | `listing_rotated`. Phase 1's `leak_events` keeps its required `leak_id`; a watch with zero Leaks still gets its row.
  - The `coverage_reduced` day state is derived from `google_failed`.
  - `seen` keeps Phase 1's `first_scan: bool` and gains the query id.
  - `google_seen` carries `visible: true | false | null` and is written only when visibility changes; `null` is unknown.

**Lanes in detail.**
- **Mega lookup** (daily, $0, no reservation).
  - Uses the service's existing Mega index client with the handle and strong aliases as terms and `names=()`, so a display-name title match can never pick the Creator. Its own title-word rule only confirms packs.
  - The tracker variant returns `deleted` packs instead of skipping them. A known Mega Leak seen as `deleted` on two daily lookups in a row (counted in its `probe_state.consecutive_dead`, the 2-dead rule's counter) gets an origin-status change `listed → gone` with `data.source = mega_index`; seen live again, it gets `gone → listed`. A known pack simply absent from the 30-row page changes nothing and resets nothing.
  - Kind `mega`, source `mega_index`, link-only (Listed). This needs Phase 1's pill rule to read a link-only Leak whose last status is `gone` as Gone (see Review, cross-Phase).
- **Listing recheck** (daily, $0). Covers known `page` Leaks that the detection map's per-host patterns class as a Creator listing.
  - Plain HTTP fetch of page 1 only, using the service's leak-site crawler fetch and its per-host throttle, with Phase 1's probe bounds: 15 s timeout, at most 5 redirects, the body read up to 2 MB.
  - At most 20 listings per watch per day, oldest `last_attempt_at` first. A watch with more writes its lane `reduced` with reason `listing_rotated`, so each listing is re-read every ⌈n/20⌉ days and the page says so.
  - The post URLs found go through hit admission, with source `site_search`.
- **Google fresh pass** (daily, 1 load).
  - One web query: `"<handle>" OR "<strong alias>"… OR "<ig>" OR "<x>"`, past-day filter (`tbs=qdr:d`, the laptop leak tools' SERP URL builder), page 1. Weak aliases are left out.
  - Trimmed in the 05 order to Google's query-length limit.
  - It only ever sets visibility true; a past-day query can't show absence, so it never enters a Leak's `google_fields_json` as a query that must miss.
  - Browserbase with residential proxies on, as the service's media gather already does.
  - A failed load writes `scan_partial` with `google_failed`. There is no fallback engine.
- **Full Google pass** (Weekly slot, `tracker_plan`, ≤31 loads by construction):

  | Field | Queries (pages) | Loads |
  |---|---|---|
  | Handle | web `"H"` (2), `"H" leaked` (2), `"H" <platform>` (1) | 5 |
  | Handle | images `"H"` (1), videos `"H"` (1) | 2 |
  | Handle | `"H" mega.nz` (1), `"H" site:t.me` (1) | 2 |
  | Each strong alias, up to 5 | web `"A"` (1), `"A" leaked` (1), images (1), videos (1) | 4 each |
  | Each weak alias | web `"H" "W"` (1) | 1 each |
  | Instagram, X | web (1) each | 1 each |

  - The worst case is 9 + 20 + 2 = 31.
  - The pass reserves `partial=True`, trims to the grant, and writes the dropped fields to `lane_state.trimmed` and a `scan_partial`.
  - Queries cut by `cap_global` go to `carry_json` and run once the next UTC day, only inside that day's remaining room (a `partial=True` reserve like any other). After that they wait for the next slot.
  - Queries cut by `cap_tenant_month` wait until the 1st of the next month.
  - A Leak's `google_fields_json` is the set of (vertical, field) pairs whose full-pass query ever returned it. Phase 1's seed Google results map to (`web`, `handle`).
  - Visibility goes false only when every pair in that set that is still in the current plan ran to completion in this pass and none returned the Leak.
  - Pairs whose field left the identity are removed from the set. A set that empties sets visibility `null` (unknown), and an unknown Leak never reads Cached.
- **Registry crawl** (Weekly slot, $0).
  - The service's leak-site crawler, run over its detection map (the registry it syncs from the laptop leak tools), with the handle and strong aliases. Plain HTTP only.
  - `TRACKER_CRAWL_WORKERS` (default 1) workers pull from a queue ordered by oldest `last_success_at`.
  - A crawl not finished by the slot day's end continues the next day, with lane state `waiting` and reason `lane_failed`.
  - Crawl seconds go to `tracker_usage`.
- **Origin probe** (Phase 1's): Phase 2 only writes its `lane_state` row.
- **Waiting and paused.** Only lanes that spend reserved units wait on a cap (`google_fresh`, `google_full`, and judging); the $0 lanes keep running. A paused watch runs no lane, and its lanes read `paused` while keeping their last success.
- **First run.** A Leak first seen by the first-ever successful run of a lane for that watch gets `seen.first_scan = true`, so it reads "Found on first scan" and is excluded from New today. The Quick scan seed is Phase 1's first-scan set.
- **Usage.** Each lane adds its units to `tracker_usage` for (tenant, UTC day, lane) in the same transaction that settles its reservation. `finds` counts confirmed Leaks the lane first saw that day. `proxy_bytes` is the Browserbase session's reported proxy bytes, or 0 when the session reports none.

**Hit admission and the Leak judge.**
- Drop hits on the Creator's own OnlyFans, Instagram or X URLs, on the Removal service's own hosts, and on aggregator hosts. These rules are reused from the service's official-URL and aggregator filters.
- A hit whose URL holds the handle or a strong alias, or a weak alias together with the handle, becomes a Leak.
- A hit where only the title holds them becomes a Pending hit. Anything else is dropped.
- Image and video results become `media` Leaks keyed `url_key(landing) + "#google_images" | "#google_videos"`, with `landing_key` set. Their pill uses the landing page's Origin status, and no media is fetched.
- The judge runs Jev first: p ≤ 0.2 is fake, p ≥ 0.8 is real (the laptop leak tools' measured band, pinned model). The middle band, and any Jev failure, goes to DeepSeek in batches with the laptop leak tools' judge prompt as input. The display name is passed as confirmation context.
- Each model HTTP attempt reserves one `judge_call` first. Over the cap, judging waits and the watch's day gets a `scan_partial` `judge_cap`.
- The judge reads the watch's current identity. A Pending hit whose title no longer names any current field (an alias was removed) is deleted without a model call.
- `unsure` stays hidden and gets one more DeepSeek round the next day. `fake` keeps its `pending_hits` row as a do-not-rejudge marker. `real` creates the Leak with `first_seen_at` = the judgement time and `seen.found_at` = the hit time.
- A row still pending after 30 days is deleted.

**CRM behaviour.**
- **Today strip.** It sums the `today` fields across the active Agency's Leak watches and sits above Phase 1's roster.
  - Text: "{new} new today · {cameBack} came back · {gone} gone · checked {checked} of {total}", with "· {partial} partial" when non-zero.
  - First-run finds show as "{firstRun} found on first scans" only when non-zero.
- **Roster.** Rows gain a New today cell and a `dayMarker` chip: "Partial check", "Reduced", "Checking…" or "Paused".
- **Drill-in.** Gains a Coverage section.
  - Lane labels: Link check, Mega, Leak-site pages, Google (past day), Google full search, Leak-site search. Each row shows its state chip, "last OK <relative>", "next attempt <weekday date>" and "Skipped: <names>".
  - The freshness promise is shown as one line under the section.
  - No copy says "next full search".
- **Identity form.** Each alias row shows "Searched on its own" or "Only with the handle", and the display name field says "Only used to confirm matches". The rename note is Phase 4's.
- **Admission.**
  - Before submit, the enable dialog reads `accepting_new`, `creators_max` and `creators_used` from the setup read. When `accepting_new` is false it warns "The removal service is full right now; this Creator joins the waitlist". When `creators_used >= creators_max` it warns "Your agency's Creator limit ({cap}) is reached".
  - A refused save still stores the `leak_watch` row with `admission` set. The roster shows a "Waitlist" or "Limit reached" chip in place of the pills.
  - Phase 1's hourly `leak-watch-sync` skips rows with `admission` set, overriding its `synced_at is null` push, except once per UTC day: it pushes when `admission_tried_on` is before today, then sets `admission_tried_on` to today. A 2xx clears `admission` and sets `synced_at`.
- Every new field reaches the app only through Phase 1's gated routes, so the four Tracker gates and the 404-when-off rule cover Phase 2 unchanged.

**Deploy and cost.**
- The service needs `TYPESAFE_API_KEY` (Jev) on the VPS beside its existing DeepSeek and Browserbase keys. That step belongs to the owner.
- Pilot limits: 300 daily loads, which fits 50 Creators with least-loaded slots (50 + ⌈50/7⌉·31 = 298); 2000 daily judge requests; 5 Creators and 1000 monthly loads per tenant (about 30 + 31·30/7 ≈ 163 loads per Creator per month, ×5, plus slack).

## Testing Decisions
Seams, by public interface. Nothing is added to `service/` for tests, and no real scan or paid call is made anywhere.

- **CRM relay seam.** File: `service/tests/test_leak_tracker_discovery.py`, run as a script that exits non-zero on failure.
  - Uses `TestClient` on Phase 1's Leak tracker routes, with the Tracker API faked at the HTTP client (Phase 1's seam) and the four gates satisfied.
  - Field pass-through: `accepting_new`, `creators_max` and `creators_used` arrive on `/setup`, and `today` and `lanes` arrive unchanged on the roster and drill-in reads.
  - Refusals: a `409 waitlist` or `409 creator_cap` on save stores the row with `admission` set and answers `200` with `{synced: false, admission}`. Hourly ticks the same UTC day make no call for that row while the fake keeps answering 409; the first tick of the next UTC day pushes once and sets `admission_tried_on`; a 2xx clears `admission`.
  - Gates: with any gate off, the routes still answer 404.
  - Demo: Phase 1's `demo/tests/test_leak_tracker_off.py` stays green (tracker off, every `/admin/leaks` route 404, the new write routes locked, no egress), run explicitly in Acceptance.
- **App pure seam.** Vitest tables in `leakCoverage.test.ts`:
  - `todayStrip` with first-run, paused and pending watches;
  - `laneRows` for every state × reason, including `trimmed` and the `never` and `paused` rows;
  - `dayMarker` over every `today.state`.
  - It also asserts `FRESHNESS` and no row text contains "next full search".
  - `leakIdentityForm.test.ts` gains `aliasLane` rows for lengths 4 and 5.
- **App render seam.** `page.test.tsx` for the leaks page renders the Today strip, roster chips (Partial check, Waitlist, Limit reached) and the Coverage section from fixture responses, at desktop and phone widths. It also opens the enable dialog with `accepting_new: false` and with `creators_used = creators_max` and asserts each warning shows before submit, and renders the identity form with a 4- and a 5-letter alias and asserts "Only with the handle" and "Searched on its own".
- **Service seams** (Removal service repo, pytest, existing `app/tests` layout):
  - `test_tracker_plan.py`: tables for identity → plan. It checks:
    - the handle-only plan;
    - 5 strong aliases giving exactly 31 loads;
    - a weak alias appearing only beside the handle;
    - IG and X in web only;
    - the display name absent from every query;
    - the trim order, the handle-group cut order, that `trim(1)` returns exactly the handle's web page 1 and that `trim(0)` returns nothing;
    - the fresh-pass OR query with weak aliases excluded.
  - `test_tracker_budget.py`: 16 threads reserving at once never exceed the global day cap or the tenant month cap; the partial grant; `settle` releasing the unused part; `expire_stale` counting in full; a watch ranked past a lowered `creators_max` refused `creator_cap`; caps set through the CLI.
  - `test_tracker_admission.py`: least-loaded slot with a tie on the lowest weekday; the waitlist when the slot day or any day would pass the cap; the Creator cap; paused watches counting; edits never refused; slot backfill of Phase 1 watches in creation order.
  - `test_tracker_lanes.py`: Phase 1's `tracker_scheduler` tick, driven by a controlled UTC clock over a temp `TRACKER_DB`, against the repo's local wire stubs (precedent: its upstream, Browserbase and Mega index stubs). Every case asserts the stubs' recorded outbound requests equal the `used` units in `load_reservation`, and the API's `today` and `lanes` reads, not only the rows. It covers:
    - a tick on a watch's slot weekday runs `run_weekly` including the registry crawl; a tick on any other weekday doesn't;
    - a SERP wall followed by success consuming two loads; a wall with the hold used up ending the query incomplete with no second navigation;
    - two watches in two tenants with the same handle making one Google request per query, charged to the first, each getting its own Leak row;
    - Mega index `deleted` once → unchanged, twice in a row → gone; absent → unchanged;
    - 21 known listings → 20 fetched, the oldest first, lane `reduced` with `listing_rotated`;
    - a media result storing a `media` Leak with `landing_key`, its pill following the landing Leak, and no request to the media URL at the stub;
    - listing recheck → new `site_search` Leaks;
    - fresh pass with a failed load → `coverage_reduced` and no other engine called;
    - full pass under a partial grant → trimmed fields, `scan_partial`, `carry_json`, and next-day carry-over exactly once;
    - visibility false only when every (vertical, field) pair still in the plan completed; a removed alias's pair dropped; an emptied set giving `null` and no Cached pill;
    - a watch with zero Leaks still getting its `lane_day` rows and a `partial` `today.state` under a cap;
    - first-run flags;
    - 12 fresh loads packed into one session;
    - $0 lanes still running over the cap;
    - a paused watch running nothing.
  - `test_tracker_judge.py`: the URL, title and weak-alias admission table; own-profile and aggregator drops; the Jev band, with Jev down falling through to DeepSeek; a Jev 5xx retry consuming a second `judge_call`; a Pending hit for a removed alias deleted with no model call; Phase 1's seed `pending_hits` rows judged like new ones; `unsure` getting one more round; `fake` never rejudged; the judge cap leaving rows pending and writing `scan_partial`; the 30-day deletion; the `media` key and `landing_key`.
  - `test_tracker_api.py` (Phase 1's, extended): `/v1/me` `accepting_new`; the `409` shapes only on create; the `today` and `lanes` shapes; tenant isolation of the new fields.
  - `test_tracker_usage.py`: lanes run against stubs fill `tracker_usage`; `tracker usage --since` prints cost per Creator per month (Jev and DeepSeek calls and tokens apart, proxy bytes) and crawl minutes per Creator per week from a fixed fixture, and no handle appears in its output.

Prior art: in this repo, `app/components/chat/fanDrawerForm.test.ts` (pure tables), `app/app/creators/proxy/page.test.tsx` (page render) and `service/tests/test_s4s_api.py` (`TestClient` on an agency-scoped feature). In the Removal service repo, its wire stubs and its existing Mega index client tests, plus the laptop leak tools' judge and Jev tests as the source of the band cases.

## Acceptance
```sh
set -e
cd "$(git rev-parse --show-toplevel)"
PY=$PWD/venv/bin/python
nice -n 10 $PY service/tests/test_leak_tracker_discovery.py
nice -n 10 $PY -m pytest -q demo/tests/test_leak_tracker_off.py demo/tests/test_routes.py
(cd app && nice -n 10 pnpm exec vitest run components/leaks/leakCoverage.test.ts components/leaks/leakIdentityForm.test.ts app/creators/leaks/page.test.tsx)
test -d app/components/leaks && test -d app/app/creators/leaks
if grep -rniE 'next full search' app/components/leaks app/app/creators/leaks; then exit 1; fi
grep -q 'admission' service/db/models.py
nice -n 10 scripts/run-tests.sh
: "${REMOVAL_REPO:?set REMOVAL_REPO to the Removal service repo checkout}"
(cd "$REMOVAL_REPO" && nice -n 10 python3 -m pytest -q app/tests/test_tracker_plan.py app/tests/test_tracker_budget.py app/tests/test_tracker_admission.py app/tests/test_tracker_lanes.py app/tests/test_tracker_judge.py app/tests/test_tracker_api.py app/tests/test_tracker_usage.py)
for m in plan budget admission lanes judge usage; do f="$REMOVAL_REPO/app/tracker_$m.py"; test -f "$f"; if grep -niE 'cse_scanner|serper' "$f"; then exit 1; fi; done
# manual: owner sets TYPESAFE_API_KEY on the Removal service VPS, deploys the service, runs `tracker caps global --daily-loads 300 --daily-judge 2000`, `tracker caps tenant <AE> --month-loads 1000` and Phase 1's `tenant cap <AE> 5`
# manual: AE pilot on 3-5 Creators for 14 days (two Weekly slots each); owner opens /creators/leaks on AE: Today strip, one Partial/Reduced day if any, drill-in Coverage rows with last OK / next attempt
# manual: owner runs `tracker usage --since <pilot start>` and records cost per Creator per month and crawl minutes per Creator per week; sets the real caps from them
```

## Depends on
- **Phase 1.** It provides:
  - the Tracker tenant and header-auth Tracker key;
  - the watch upsert per (tenant, CRM account), with the paused bit;
  - the Leak event log and Probe state, with the daily Origin probe runner and the Daily scan scheduler;
  - the Quick scan seed (the first-scan set) and its `pending_hits` queue, which Phase 2 extends and drains;
  - `daily_scans` and `tracker_scheduler`, which Phase 2 hooks its lanes into;
  - `tenants.creators_max` and the `tenant cap` CLI;
  - the tenant-scoped `/v1/me`, creators and leaks reads;
  - the CRM's `leak_watch` table, identity reducer, gated Leak tracker relay routes, roster and drill-in page, the demo's tracker-off test (`demo/tests/test_leak_tracker_off.py`), and the leak-check rules.
- **Phase 1 amendment (cross-Phase, applied in the plan review).** The pill rule reads a link-only Leak whose last origin-status change is `gone` as Gone; Phase 3's removal track already assumes it.
- **Owner, before the pilot.** `TYPESAFE_API_KEY` (Jev) on the Removal service VPS. If a vendored module cannot be rewritten off `httpx`/`bs4`, its ticket parks with `pip install httpx beautifulsoup4` added to the service Dockerfile's pip line as the owner's step.

## Out of Scope
- Google CSE, Serper, Bing, DuckDuckGo and Brave lanes. CSE is cut (its quota is shared with the owner's tools), the Serper fallback is cut in the Fable round 2, and the rest were never in the plan.
- Suggested alias chips and the "same person" OnlyFans + Fansly link, both cut in the Fable round 2. Aliases stay manual.
- A 30-day trend sparkline per row. Ticket 08's layout awaits the owner and no Phase lists it; partial days show as the roster marker and the lane rows instead.
- The `?day=` past-day view and the bell row: Phase 4.
- Notice counts, Service status and the Removal offer's angles: Phase 3, which reads Phase 2's discovery counts.
- The purge jobs: the watch purge is Phase 1's, and Phase 2 only adds its watch-keyed tables to `WATCH_TABLES`; backups and tenant offboarding are Phase 4's.
- Headless-browser fallback for JS-only leak sites, and Telegram channel crawling. That is VPS browser cost the pilot hasn't measured; `"H" site:t.me` in Google covers Telegram in v1.
- Crawl worker-hours in admission. Ticket 04 refuses on loads only, and crawl minutes are measured first.
- Fetching, storing or thumbnailing any media (ticket 08: none).
- Filing notices from the CRM, which is out of the map's scope.
- A slop run. This is not a mass-send or many-user change on the CRM side, and the owner's rule is no slop unless asked.

## Further Notes
- ASSUMPTION: module names `tracker_plan`, `tracker_budget`, `tracker_admission`, `tracker_lanes`, `tracker_judge`, `tracker_usage` sit beside Phase 1's tracker modules in the Removal service repo, and the CRM side uses `leak_tracker_api`, `app/components/leaks/` and `app/app/creators/leaks/` (rung 3: `s4s_api`, `app/app/creators/proxy`). Overturned by Phase 1's chosen names, which these follow, unchanged in behaviour.
- ASSUMPTION: the Google fresh pass OR-joins the handle, strong aliases and socials into its one load (rung 5: one daily load). Overturned if the pilot shows OR queries miss what a handle-only query finds; then the pass runs the handle daily and rotates one alias per day.
- ASSUMPTION: only lanes that spend reserved units wait on a cap, while Mega, listing recheck and crawl keep running (rung 5: the caps count loads and judge calls, and ticket 04 says "discovery waits" about spend). Overturned if the owner wants a tenant over its allowance to get Origin probes only.
- ASSUMPTION: Leak judge requests reserve against a global daily judge cap (default 2000) as their own `judge_call` unit (rung 4: ticket 04 names post-call LLM booking as a race to remove, but lists only load caps). Overturned if the pilot's judge spend is negligible; then the unit is dropped.
- ASSUMPTION: a Mega index `deleted` flag on a known pack, seen on two daily lookups in a row, is an origin-status change to `gone` for that link-only Leak, and absence changes nothing (rung 1 for the flag, the Mega index client's response shape; rung 3 for two sightings, the 2-dead-probes rule). Overturned if the pilot shows the index never un-deletes packs; then one sighting is enough.
- ASSUMPTION: Leaks first seen by a lane's first-ever run read "Found on first scan", extending ticket 02's first-scan rule ("a Creator's first scan") from the seed to each lane's first run, since a Creator's first full scan only completes on its first Weekly slot (rung 4: no false "new" wave on the first Weekly slot). Overturned if the owner wants only the seed treated as first scan.
- ASSUMPTION: a judged-real Leak's `first_seen_at` is the judgement time, so it counts as New today the day it becomes visible (rung 5). Overturned if New today must reflect discovery time; then `seen.found_at` drives it and late verdicts never count as new.
- ASSUMPTION: paused watches keep their slot and count toward capacity, so resuming never needs admission (rung 4). Overturned if capacity gets tight and the owner wants paused watches released.
- ASSUMPTION: refused enables are stored in `leak_watch.admission` and retried once per UTC day by Phase 1's hourly `leak-watch-sync`, gated by `admission_tried_on` (rung 2: ticket 05 "a failed push is retried by the daily sync"; rung 4: additive columns).
- ASSUMPTION: a weekly pass cut by the global cap carries its leftover queries to the next UTC day once, inside that day's remaining room (rung 4; the reservation holds the cap, so a carry can trim but never overspend). Overturned if carry-over days start peaking; then the leftovers wait for the next slot.
- ASSUMPTION: the pilot caps (300 daily loads, 2000 judge requests, 5 Creators and 1000 monthly loads per tenant) come from ticket 04's arithmetic, not from measurement (rung 5). Overturned by the pilot's `tracker usage` report, which is this Phase's purpose.
- ASSUMPTION: the Leak judge prompt lives in, and is catalogued in, the Removal service repo, not `docs/prompts/` (rung 2: that catalog covers old fastt and this repo, and `docs/` goes public). Overturned if the owner wants a public entry with generic wording.
- ASSUMPTION: the tracker's load cap counts only tracker loads, and the Quick scan keeps its own Browserbase gate (rung 5). Overturned if both draw on one Browserbase budget that the owner wants capped together.
- ASSUMPTION: the registry crawl uses plain HTTP only on the VPS (rung 5: no browser cost until it is measured). Overturned if the pilot shows key hosts are JS-only.
- ASSUMPTION: unsure Pending hits get one more DeepSeek round, and unjudged rows are deleted after 30 days (rung 4, after the laptop leak tools' one-rejudge rule). Overturned if real Leaks are found among the expired rows.
- ASSUMPTION: a watch-scoped `scan_partial` lives in the append-only `lane_day` table, not in Phase 1's per-Leak `leak_events`, because a watch with zero Leaks must still record a capped day and Phase 4's `complete` reads it (rung 4: additive table, `leak_events.leak_id` untouched). Overturned if ADR-0070 is amended to give the Leak event log watch-scoped rows; then `lane_day` becomes those rows unchanged.
- ASSUMPTION: Google visibility is tracked per (vertical, field) pair, with Phase 1's seed results mapped to (`web`, `handle`), and an emptied set reads unknown, never Cached (rung 4; ticket 02: a query that didn't run gives unknown, not missing). Overturned if the pilot shows Leaks Cached on a handle query that the field rule clears too early.
- ASSUMPTION: the same Google query on the same UTC day is fetched once across watches and tenants through a one-day `serp_cache`, charged to the first reserver (rung 2: ADR-0070 "the service dedupes scan work across Agencies"; rung 5 for the cache). Overturned if the owner wants each tenant charged its own share; then reuse books a zero-load usage row per reuser.
- ASSUMPTION: the Creator cap is checked at reserve time by `created_at` rank, so a lowered cap stops spend for the newest watches without pausing them (rung 2: ticket 04 lists the Creator cap among the reservation's three limits; rung 4 for rank order). Overturned if the owner wants a lowered cap to pause watches instead.
- ASSUMPTION: a known-listing recheck over 20 per watch rotates oldest-first and marks the lane Reduced (rung 4: bounded VPS fetches, honest coverage). Overturned if the pilot shows watches rarely pass 20; then the ceiling goes.
- ASSUMPTION: judge calls reserve only against the global daily judge cap, not the tenant's monthly allowance, which ticket 04 names as a load allowance (rung 2); each tenant's judge spend is still recorded in `tracker_usage`. Overturned if the pilot shows judge spend per tenant is material.
- ASSUMPTION: `proxy_bytes` comes from the Browserbase session's own report, and is 0 when none is reported (rung 5; residential proxy bandwidth is billed apart, per the service's media gather). Overturned if Browserbase reports no bytes; then the report shows session minutes only and says so.

## Review
Reviewer: codex (blind call, then draft call), 2026-11-27.

*Blind call (no spec shown):*
- B1 **accept** — one planned SERP page can spend two navigations (wall, then the same page in a fresh session, the scraper tool's SERP module, lines 177-205). One unit is now one outbound attempt; story 32, `tracker_budget` and the wall cases in `test_tracker_lanes.py`.
- B2 **reject** — the existing planner's page counts and its lack of alias video queries are not inherited: `tracker_plan` is new, its table follows ticket 05 (aliases in video) and `test_tracker_plan.py` pins 31.
- B3 **reject** — the Mega display-name match is already closed: the lookup passes `names=()`.
- B4 **accept** — a watch with zero Leaks had nowhere to record a capped day (`CONTEXT.md` Leak event log is per Leak). New append-only `lane_day` table; Contracts and an ASSUMPTION.
- B5 **reject** — the late-verdict day is decided (judgement time, flagged ASSUMPTION) and matches Phase 4's `first_seen_at` reading.
- B6 **accept** — scan work across tenants was neither shared nor charged (ADR-0070 "dedupes scan work across Agencies"). One-day `serp_cache`, first reserver pays; story 46.
- B7 **reject** — the 110-watch peak overrun is about ticket 04's 600 cap; the pilot cap of 300 fits 50 watches (50 + 8·31 = 298) and admission refuses past it.
- B8 **accept** — the listing recheck had no request bounds: Phase 1's 15 s timeout, 5 redirects, 2 MB body, and oldest-first rotation with an honest Reduced state.
- B9 **partial** — `tracker_usage` gains `finds` per lane so the pilot sees each lane's yield; a paired weekly-Google holdout is rejected, since the plan's Phase 2 measures are cost and crawl minutes (`plan/goal.md:13`).
- B10 **reject** — a relay-driven screenshot path adds nothing the relay seam, render seam and manual AE line don't already cover; screenshots are execution-time proof, not spec.
- B11 **reject** — crash after dispatch is already handled: `expire_stale` counts a stale hold in full.
- B12 **partial** — per-query completeness now drives visibility (per (vertical, field) pair); lane states cover the rest, so no per-host stale state is added.
- B13 **reject** — new hosts enter the registry crawl through the detection map the service syncs from the laptop leak tools, already stated.
- B14 **accept** — identity edits with results in flight were undefined: the judge reads the current identity and deletes a Pending hit whose field was removed; removed fields leave `google_fields_json`.
- B15 **reject** — Jev thresholds and the DeepSeek fallback are already defined (≤0.2 fake, ≥0.8 real, middle band and failures to DeepSeek).

*Draft call:*
- D1 **partial** — accepted: the Creator cap was checked only on create, so `reserve` now refuses `creator_cap` for watches ranked past a lowered `creators_max`. Rejected: charging judge calls to the tenant's allowance, since ticket 04 names a monthly *load* allowance (flagged ASSUMPTION).
- D2 **partial** — the enable-time seed's CSE use is plan-sanctioned (`plan/goal.md:10` "enable-time seed from the existing quick scan"), so it stays Phase 1's; story 38 now says "no CSE in any Leak lane", and the Acceptance grep checks the six Phase 2 modules by name.
- D3 **accept** — `trim(1)` was impossible against a 9-load handle group. Trim now cuts handle queries in a fixed order, always keeps web page 1, and `trim(0)` means wait; test updated.
- D4 **partial** — accepted: story 35 promised a full plan that later edits and carries can break; it now promises the plan as accepted, with the reservation holding the cap and carries running inside the next day's room; cross-agency dedupe added (B6). Rejected: re-projecting admission on edits, since the plan sets admission at enable only.
- D5 **accept** — visibility could stick on Cached forever through the never-rerun seed, fresh or removed-alias queries. It is now kept per (vertical, field) pair still in the plan, the fresh pass never counts as a miss, and an emptied set reads unknown, never Cached.
- D6 **partial** — accepted: Mega `deleted` now needs two daily sightings (the 2-dead rule's counter), and the link-only Gone reading is a cross-Phase Phase 1 pill amendment. Rejected: dropping per-lane first scan, which stays a flagged ASSUMPTION reading ticket 02's "Creator's first scan" as the first full scan.
- D7 **partial** — accepted: the silent 20-listing ceiling now rotates and shows Reduced, and the carry is bounded. Rejected: the judge cap, second DeepSeek round and 30-day deletion are defaults the plan leaves open but needs for "unjudged hits stay pending", each a flagged ASSUMPTION.
- D8 **accept** — the shapes renamed Phase 1 fields (`synced`, `creators_max`, `first_scan`) and re-specced Phase 1's rename rule. Phase 1 names are kept, `/v1/me` adds only `accepting_new`, and the rename rule, `identity_note` and its test are removed. (Plan review, Six hats 3: `identity_note` is now Phase 1's column; Phase 2 still adds none.)
- D9 **accept** — the spec re-declared `pending_hit` beside Phase 1's `pending_hits`, and the event log had no home for zero-Leak days. It now extends `pending_hits` (seed queue drains through the judge) and adds `lane_day`; `daily_scans.outcome` gains `partial`.
- D10 **accept** — refused rows would be pushed hourly by Phase 1's `synced_at is null` rule. `admission_tried_on` gates them to once per UTC day; the relay test asserts no same-day call while 409 persists.
- D11 **accept** — `Depends on` lacked the Jev key and the vendored `httpx`/`bs4` imports the service image doesn't install (Dockerfile pip line: `Pillow curl_cffi playwright`). Both are added, with a stdlib rewrite or a parked pip step.
- D12 **accept** — the seams could pass with lanes never scheduled and egress unreserved. `test_tracker_lanes.py` now drives Phase 1's scheduler tick on a controlled clock, asserts stub outbound requests equal used units, and reads the API; Jev retry reservation is tested.
- D13 **accept** — stories 12, 19, 30 and 39-40 had no seam proving them. Page render asserts the alias labels and pre-submit warnings, the lanes test covers media with no media fetch, and a new `test_tracker_usage.py` covers the report. Judge tokens are split by model, and proxy bytes are added.
- D14 **partial** — accepted: the demo pytest now runs, and both `! grep` lines (fail-open under `set -e`, reproduced) became `if grep …; then exit 1; fi` with existence checks. Rejected: making deployment and the pilot executable, since they need the live Removal service, which floor 2 bars; they stay manual.

*Cross-Phase:*
- Binds Phase 1: its pill rule (link-only is always `listed`) must read a link-only Leak whose last status is `gone` as Gone, for Phase 2's Mega `deleted` and Phase 3's removal track (`phase-03…:141`).
- Binds Phase 1: its Acceptance lines `! printf … | leak-check.sh --diff` fail open under `set -e` (same reproduction as D14).
- Binds Phase 1 / ADR-0070: `scan_partial` is watch-scoped in `lane_day`, not a `leak_events` row; the ADR's event list should say so if amended.
- Binds Phase 4: its `complete` and partial-day reads come from `lane_day` and `daily_scans.outcome = partial`.

Counts: accept 13 · partial 8 · reject 8 · needs-human 0.

### Six hats
One six-hats pass over the four specs, 2026-11-27. Bullets touching this Phase:
- 3 (`identity_note` dropped here but reused by Phase 4) — **accept**: the column is Phase 1's (`leak_watch.identity_note`), shared by the rename and restore notes; D8 annotated.
- 13 (`first_daily_at` counts only `ok` days, so a Creator capped daily never gets an offer) — **accept**: Phase 3's `first_daily_at` now counts `ok` or `partial`; nothing changes here, since `partial` already means the day ran with less coverage.
- 18 (story 38 says the seed reuses the Quick scan) — **accept**: story 38 now says Phase 1 runs the candidate step privately and never reuses a stored scan.
- 11, consequence here (the watch purge moved into Phase 1) — **accept**: Phase 2's watch-keyed tables join Phase 1's `WATCH_TABLES`; story 45 names Phase 1's purge.
Counts: 4 accept, 0 partial, 0 reject.


### Fable round 3 (2026-11-27)
- Sizing (rename rule and Demo tracker leave Phase 1) — **accept**: story 14, the relay module row and the Identity form line name the rename rule as Phase 4's; the Demo tracker fixtures row and story 44 point to Phase 4; the demo seam, Acceptance and Depends on use Phase 1's `demo/tests/test_leak_tracker_off.py`.
- Cut 3 (95 % bound and CSV sampling) — **accept, no edit here**: Phase 1's report now prints plain counts, and this Phase's pilot reads them again; nothing here named the bound.
- Cut 4 (waitlist and least-loaded slots) — **reject**: ticket 04 states the waitlist and the least-loaded Weekly slot, and the plan names them.
- C1, C2, C3, C4, cuts 1, 2, 5, 6 — not this Phase's.
