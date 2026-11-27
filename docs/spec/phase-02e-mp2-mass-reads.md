# Phase 02e — Mass reads

**Objective.** A Fansly Creator's sent broadcasts and scheduled-broadcast queue are read from Fansly's captured feeds into the OnlyFans shapes (string ids, observed fields only, an explicit `incomplete` when the walk stops early). The Mass messages tab shows the sent history with unsend disabled; the scheduled queue is read back through `GET /api/of/v2/messages/queue` only (no screen in this Phase). Every unsend or cancel path that could hit a broadcast refuses with `platform_lacks:unsend_mass_message` before any write or local state change.

## Problem Statement
An owner with a Fansly Creator opens Smart messages → Mass messages and gets a load error for that Creator, because mass-message history, the engagement feed and the scheduled queue are Blocked on Fansly although Capture session 1126 recorded both feeds with our own bodies (W). The Relay can't tell him what he broadcast, how many fans got it or read it, or what is waiting in the queue, and the mass-write work after this Phase (02f) has no read-back to prove a scheduled broadcast landed or was cancelled.

Lifting the read naively is dangerous. The `unsend_messages` automation gates its mass Branch only on `mass_message_history`, then "unsends" each target with `cancel_scheduled`, which on the Fansly Shim is the scheduled-*post* cancel. The `DELETE /api/of/v2/messages/queue/{id}` route does the same. The moment history reads, both would fire a post-cancel request with a broadcast id and then flip the local mass cache, mirror rows and funnel discovery as if the broadcast had been recalled: a fake success on a Fan-facing write. Fansly ids are snowflakes above 2^53, and the mass cache hands them back to the app as JSON numbers, so two adjacent broadcasts can collapse into one row key.

## Solution
Fansly answers the three reads OnlyFans answers. History and engagement walk `/message/broadcast/stats` by id cursor and keep only the text-only rows the capture showed. The scheduled queue reads `/message/broadcast/scheduled` and keeps pending rows. Ids stay exact strings from the Shim to the browser. Every row says it cannot be unsent. A walk that hits its page cap says `incomplete`, and the Mass messages tab shows a "more not loaded" line for that Creator instead of pretending the list is whole.

Before any of that lifts, unsend gets its own method. `unsend_mass_message` is Blocked on Fansly (a delivered-broadcast delete was never captured). On OnlyFans it delegates to today's `cancel_scheduled`, with the same request on the wire. The mass Branch of `unsend_messages` refuses on Fansly before any Shim call or local write. On Fansly the DELETE route refuses a cached broadcast before any Shim call, and cancels only an id the Shim's scheduled-post read lists, with no mass bookkeeping. Single-row queue reads and buyers stay Blocked, each with an honest reason. OnlyFans behaviour does not change: same requests, same rows, same unsend.

## User Stories
1. As an owner, I want unsend of a mass broadcast on a Fansly Creator to stop before anything happens, recorded as `skipped` / `platform_lacks:unsend_mass_message`, so that a broadcast Fansly can't recall is never reported recalled.
2. As an owner, I want the `unsend_messages` automation's chat Branch to keep unsending 1:1 messages on Fansly while its mass Branch refuses, so that one gap doesn't stop the part that works.
3. As an owner, I want a mass-only unsend run on Fansly to persist `skipped` with `platform_lacks:unsend_mass_message` in its run outcome and `stats_json`, so that Automations history tells the truth after a reload.
4. As an owner, I want a mixed (chat + mass) unsend run on Fansly to make exactly the chat unsend requests and row flips it makes today, finish `ok`, and persist the mass refusal under `target_skips`, so that I see exactly which half was refused.
5. As an owner, I want a refused Fansly mass unsend to leave the mass cache, mass runs, queue copies, mirror rows and funnel discovery untouched, with no `cancel_scheduled` call and no follow-up job, so that local state never claims an unsend that didn't happen.
6. As an owner, I want the mass-unsend gate to run before the mass-cache refresh and the cancel-race repair, so that a mass-only refused run makes zero Fansly requests and a mixed run makes only its chat requests.
7. As an owner, I want a dry-run unsend on Fansly to list only chat targets and report the mass refusal, so that a preview never offers broadcasts it can't recall.
8. As an owner, I want `DELETE /api/of/v2/messages/queue/{id}` on a Fansly Creator to answer 501 `platform_lacks:unsend_mass_message` when the id is a cached broadcast (before any Shim call or local state change), and also when the id isn't a pending scheduled post (after one scheduled-post read, before any write), so that no broadcast id — cached, uncached or from the scheduled queue — ever reaches the post-cancel path.
9. As an owner, I want that same DELETE route to keep cancelling a Fansly scheduled post whose id the Shim's scheduled-post read lists, without touching the mass cache, funnel discovery or mirror rows, so that the Fansly Manager's Scheduled Posts cancel keeps working and never stamps mass bookkeeping.
10. As an owner on OnlyFans, I want mass unsend (automation and DELETE route) to send exactly the request it sends today, so that nothing changes for OnlyFans Creators.
11. As an owner, I want the Fansly Shim's mass-message history to return my sent broadcasts in the OnlyFans `{items, hasMore}` shape, so that every consumer that reads OnlyFans history reads Fansly's.
12. As an owner, I want history to delegate to the engagement "group" feed on Fansly exactly as it does on OnlyFans, so that the two never disagree.
13. As an owner, I want the history walk to page by message id (`before=<last id>`, starting at `before=0`), never by date, so that a page boundary never repeats or skips a broadcast.
14. As an owner, I want the date window (start and end, `YYYY-MM-DD HH:MM:SS` UTC) applied to the fetched rows, with the walk stopping at the first row older than the start, so that OnlyFans date-range callers (Stats feed, Mass tab) work unchanged.
15. As an owner, I want offset and limit applied to the filtered rows, so that the Stats feed's offset paging and its search paging work on Fansly.
16. As an owner, I want the walk to stop only on an empty page or a repeated cursor, never on a short page, so that a short page never ends a feed that has more.
17. As an owner, I want a walk that reaches its 20-page cap, or stops on a repeated cursor after a non-empty page, to answer `hasMore: true, incomplete: true`, so that a cut-off or stalled list is never presented as complete.
18. As an operator, I want a malformed stats page to raise a Shim API error instead of returning an empty list, so that callers that require `items` plus a boolean `hasMore` fail loudly rather than reading "no broadcasts".
19. As an owner, I want the engagement feed's "direct" type to stay Blocked on Fansly, so that the Direct messages stats tab answers 501 rather than inventing a direct-message feed.
20. As an owner, I want each broadcast row to carry only observed fields: `id`, `text`/`rawText` from `content`, ISO `date` from `createdAt` seconds, `sentCount` from `stats.delivered`, `viewedCount` from `stats.read`, so that no unobserved value becomes a number on screen.
21. As an owner, I want every Fansly broadcast row to say `canUnsend: false`, `unsendSeconds: 0`, `isCanceled: false`, `isTip: false`, so that no screen offers an unsend or tip reading Fansly can't back.
22. As an owner, I want a kept row marked `isFree: true` only because it is text-only with no attachment, so that no price can be read where none could exist.
23. As an operator, I want rows whose `type` is not 3 or whose `attachments` are not empty skipped with one counted log line per walk, so that unseen media or priced broadcasts never reach a screen and I can see how many were hidden.
24. As an owner, I want Fansly tip fields on broadcast stats ignored, so that nothing outside the Banking set reads as money (ADR-0055).
25. As an owner, I want the Stats feed's search box on a Fansly Creator to match a case-insensitive substring of the broadcast text in the Relay, so that search returns what I typed.
26. As an owner, I want broadcast ids to reach the browser as exact strings, from the Shim through the mass cache to `/admin/mass-messages`, so that two broadcasts whose ids differ above 2^53 never collapse into one row.
27. As an owner on OnlyFans, I want mass-cache ids that fit a JavaScript number to stay numbers, so that OnlyFans rows, keys and unsend paths are unchanged.
28. As an owner, I want the Shim's scheduled-messages read to return my pending scheduled broadcasts (`status: 1`) as `{list, hasMore}` rows with a string `id`, `text` from the parsed `messageTemplate` and an ISO `scheduledDate` from `scheduledFor` milliseconds, so that the queue can be read back.
29. As an owner, I want cancelled (`status: 3`) and other-status rows, and rows whose `messageTemplate` doesn't parse as a JSON string, skipped, so that nothing unclear shows as pending.
30. As an owner, I want scheduled-messages `limit`/`offset` applied locally with `hasMore` computed from the eligible rows, so that the existing route's paging stays honest.
31. As an owner, I want scheduled broadcasts kept out of the Shim's `schedules()` for now, so that neither Scheduled screen sends a post cancel at a broadcast id before 02f's typed cancel exists.
32. As a chatter on the OF Manager edit flow, I want the single-row queued-message read to stay Blocked with the reason "no single-row GET; its only caller is the queued-message edit, graded I", so that the reason says what is really missing.
33. As an owner, I want mass-message buyers to stay Blocked on Fansly with their own reason (no buyers in broadcast stats; a priced broadcast needs a Proof purchase), so that the buyers route keeps answering 501 for the right reason.
34. As an owner, I want the app to have a `mass_history` Capability mapped to the history and engagement reads, so that a screen showing past broadcasts asks for exactly what it needs.
35. As an owner, I want `mass_message` (the composer) to stay in Fansly's lacks, so that reading history never lights a send control.
36. As an owner, I want the Mass messages tab to list only Creators whose Platform has `mass_history`, so that a Creator that can't read history shows no load error.
37. As an owner, I want the Mass messages tab to show a "more not loaded" line naming the Creators whose last history read came back `incomplete` or `hasMore`, so that a cut-off list never reads as the whole list.
38. As an owner, I want unsend buttons, bulk unsend counts and row selection to treat Fansly rows as not actionable, so that the tab never offers an unsend the Relay would refuse.
39. As an owner, I want `/admin/mass-messages` and its refresh route to carry `hasMore` and `incomplete` for the account and the exact window/limit asked, refreshing a Fansly account whose flags for that window are unknown (cold, other window, after a Relay restart), so that the tab can tell me when it didn't load everything and never reuses another window's answer.
40. As an owner, I want the Stats group feed (`/api/of/v2/users/me/stats/messages/group`) on Fansly to return the history rows with string ids and no unsend offer, so that Group Stats doesn't advertise a recall Fansly lacks.
41. As an operator, I want the Drift test to hold `mass_history` against the Fansly Shim (built ⇒ not in lacks), so that the app table and the Shim can't disagree.
42. As an operator, I want the Capability test to see `unsend_mass_message` as a reachable, Blocked Fansly method, so that a new unsend caller can't slip in unmarked.
43. As an operator, I want a scrubbed `fansly/fixtures/broadcast.json` whose `_source` names the RECIPES section of Capture session 1126, covering empty, malformed, cross-page, repeated-cursor, out-of-window, attachment, type≠3, tip and two adjacent above-2^53 ids, so that every adapter rule has an offline case.
44. As an operator, I want the Stateful fake (02a) to answer both broadcast GETs from that fixture, so that the Verdict table runs the real Shim over them.
45. As an operator, I want the Verdict table's `unsend_messages` rows to read: mass Branch `gated:unsend_mass_message` on Fansly with an OnlyFans `same` control, chat Branch `same`, so that the lane's verdict is measured, not described.
46. As an operator, I want the Lift table to gain `unsend_mass_message`, rewritten `queued_message` and `mass_message_buyers` rows and to lose the rows for the three reads now built, so that `fansly/test_lift_table.py` stays equal to the Shim's markers.
47. As an operator, I want parity rows for schedules/scheduled_messages and the mass-read Blocked rows to gain Provenance and Coverage (W; one text-only stats row; one pending + one cancelled queue row), so that the parity doc says how strong the evidence is.
48. As a demo viewer, I want Nova Reyes (the Fansly demo Creator) to have two sent broadcasts and one scheduled broadcast in her FixtureShim, so that verify-app and demo shots show the Fansly Mass tab with real-shaped rows.
49. As the owner reviewing the PR, I want desktop and phone screenshots of the Mass messages tab with Nova's rows (trigger and settled), plus the `/admin/mass-messages` response showing string ids and `canUnsend: false`, so that the UI claim is proved on the running app.
51. As the mirror thread, I want a message before this Phase edits the Shim, Nova seed, shape tests or RECIPES, and the merge sha after, so that our edits don't collide.

## Implementation Decisions
- **Owns.**
  - Relay: the Fansly Shim's broadcast reads, `unsend_mass_message`, and the `queued_message`/`mass_message_buyers` marker reasons. The OnlyFans client's new `unsend_mass_message`. The `unsend_messages` automation's mass gate and call. The mass queue API's DELETE route gate. The mass broadcast cache's id boundary and last-walk flags. The two `/admin/mass-messages` routes and the Stats group route response.
  - App: the Platform table's `mass_history` Capability; the Mass messages tab, its hook, and the pure helpers beside it (`massFilterBar`, `massUnsendRules`).
  - Tests and proof: the Drift test map, `fansly/fixtures/broadcast.json`, the Nova FixtureShim, the parity doc rows and the Lift table rows. This Phase's rows in the Verdict table and Stateful fake (both built by 02a).
- **Files** (11 item 5 "each spec lists its files"): `fansly/fansly_shim.py`, `fansly/fixtures/broadcast.json` (new), `fansly/test_broadcast_reads.py` (new), `fansly/FANSLY_PARITY_STATUS.md`, `fansly/capture/RECIPES.md` (one Provenance line under the broadcast section, no new entry), `service/of_sends.py`, `service/automations/unsend_messages.py`, `service/mass_queue_api.py`, `service/mass_broadcast_cache.py`, `service/server.py`, `service/tests/test_fansly_automation_gates.py`, `service/tests/test_fansly_mass_reads_routes.py` (new), `service/tests/test_fansly_cancel_scheduled_route.py`, `service/tests/test_platform_table_drift.py`, `service/tests/test_platform_kind_verdicts.py`, the unsend-lane OnlyFans fakes (`service/tests/test_a12_unsend.py`, `test_unsend_mass_policy.py`, `test_mass_placeholder_staleness.py`, `_send_kill_jobs.py`), the Stateful fake module from 02a, `scripts/demo-shots/fansly_nova.py`, `app/lib/platform.ts`, `app/hooks/useMassMessages.ts`, `app/components/settings/MassMessagesTab.tsx` (+ test), `app/components/settings/massFilterBar.ts` (+ test), `app/components/settings/massUnsendRules.ts` (+ test).
- **Interfaces.**
  - `OFClient.unsend_mass_message(queue_id) -> Any` (new). On OnlyFans it delegates to `cancel_scheduled(queue_id)`, so the request is unchanged. On the Fansly Shim it is Blocked with the Platform marker, reason "delivered-broadcast delete not captured". This Phase adds the method only.
  - `FanslyShimClient.engagement_messages(type, *, start_date, end_date, limit=50, offset=0, query=None) -> {"items": [...], "hasMore": bool, "incomplete": bool}`. `type="group"` is built; any other type raises the Shim's Blocked error.
  - `FanslyShimClient.mass_message_history(*, start_date, end_date, limit=50, offset=0)` returns `engagement_messages("group", …)`, the same delegation as OnlyFans.
  - `FanslyShimClient.scheduled_messages(*, limit=10, offset=0) -> {"list": [...], "hasMore": bool}`.
  - Two pure module-level adapters beside the existing `of_chats_page`: `of_broadcast_row(msg) -> dict | None` and `of_scheduled_broadcast_row(row) -> dict | None`. They return None for a skipped row, and the caller counts skips by reason.
  - `engagement_messages`, `mass_message_history` and `scheduled_messages` leave the Shim's unbuilt table. `unsend_mass_message` joins it as Blocked. `queued_message` leaves the queue group with its own reason. `mass_message_buyers` leaves the stats group with its own reason.
  - Mass broadcast cache:
    - `is_cached(account_id, queue_id) -> bool` (new).
    - `note_walk(account_id, days_back, limit, *, has_more, incomplete)` / `last_walk(account_id, days_back, limit) -> {"hasMore", "incomplete"} | None` (new, in process memory, keyed by the exact window and limit; a walk for one window is never reported for another).
    - Row dicts emit `id` as a decimal string when it is above 2^53 − 1, otherwise an int.
  - `unsend_messages`:
    - The mass Branch checks `("unsend_mass_message", "mass_message_history")` in that order, so the first refusal names the unsend gap.
    - The check stays ahead of the cache refresh and the cancel-race repair.
    - Each mass target calls `client.unsend_mass_message`, and the automation no longer calls `cancel_scheduled` itself.
  - App:
    - `CAPABILITIES` gains `mass_history`. The Fansly row doesn't list it once the Shim reads are built. The filter uses today's `accountPlatform`/`can` unchanged; 02d's Unknown sentinel (`can()` false for every capability) composes with it whenever it lands, so this Phase doesn't rely on it.
    - `useMassMessages` returns, per account, the rows plus that account's `hasMore`/`incomplete`.
    - `MassMessageRow.id` becomes `number | string`.
    - New pure `moreNotLoaded(perCreator) -> string[]` in `massFilterBar` (Creator ids to name). `isActionable` stays data-driven on `canUnsend`, and Fansly rows arrive `false`.
- **Schema.** None. `mass_broadcast_cache.queue_id` is already BigInteger, which holds Fansly snowflakes (under 2^63). The last-walk flags live in process memory, so there's no migration (map assumption "no P2 phase needs a migration").
- **Contracts.**
  - Fansly wire, reads only, exactly as recorded under Capture session 1126 → broadcast (W):
    - `GET /message/broadcast/stats?before=<id>&limit=24` (first call `before=0`) → `{messages:[{id,type,content,createdAt(s),attachments,stats:{total,delivered,read},…}], …}`.
    - `GET /message/broadcast/scheduled` → `{scheduledBroadcastMessages:[{id,status,messageTemplate:<JSON string>,scheduledFor(ms),…}], groups:[…]}`.
    - No other Fansly request is added.
  - History row (OnlyFans shape, observed fields only):
    - `{id:str, text, rawText, date:ISO UTC, sentCount, viewedCount, isFree:true, isTip:false, isCanceled:false, canUnsend:false, unsendSeconds:0, mediaCount:0, media:[], previews:[]}`.
    - `total` is not mapped.
  - Scheduled row: `{id:str, text, scheduledDate:ISO UTC}`. Price, lists and media aren't emitted (Unseen values).
  - `/admin/mass-messages` and `POST /admin/mass-messages/refresh` responses gain `hasMore` and `incomplete` from `last_walk(aid, days_back, limit)`. This is additive; existing keys are unchanged. On a non-OnlyFans account (`accounts.get_platform`; today only Fansly reads history), a missing `last_walk` for the asked window counts as stale, so the read path walks once before serving. OnlyFans keeps today's staleness rule and request count; its keys are absent when unknown.
  - The DELETE refusal is HTTP 501 with detail `platform_lacks:unsend_mass_message`, the exact Platform refusal reason, not the generic "not on this platform".
  - The persisted run refusal for unsend is `status: skipped` and `reason: platform_lacks:unsend_mass_message` when no Branch is left. With the chat Branch kept, it is `target_skips: {"mass": "platform_lacks:unsend_mass_message"}`.
- **Walk rules** (engagement "group"):
  - The walk collects eligible rows until it holds `offset + limit + 1` of them or a stop condition fires.
  - Stop conditions:
    - an empty `messages` page;
    - a cursor equal to one already used;
    - the first row older than `start_date`;
    - the 20th page.
  - The page cap and a repeated cursor after a non-empty page set `incomplete: true`, which forces `hasMore: true`. Otherwise `hasMore` is true exactly when an eligible row exists beyond `offset + limit`. A 500-row Mass-tab request against a feed longer than 480 rows therefore reads `incomplete`, by design.
  - The cursor is the last row's id on the raw page, including skipped rows, so a skipped row never stalls the walk.
  - Rows newer than `end_date` are passed over but still advance the cursor.
  - `query` filters before offset/limit.
  - One info log line per walk counts the skips by reason: `type`, `attachments`, `window`.
- **Gate order on the DELETE route.**
  1. Resolve the account.
  2. If the account's Platform doesn't refuse `unsend_mass_message` (OnlyFans), take today's path unchanged: `cancel_scheduled`, then the cache, funnel and mirror bookkeeping.
  3. Refusing Platform (Fansly): `is_cached(aid, queue_id)` → 501, no Shim call. A cached id that is also a listed post still refuses (ambiguity refuses).
  4. Else one Shim `schedules()` read (`GET /post/scheduled`). The id not among its pending post ids → 501, no write.
  5. Else Shim `cancel_scheduled` (the post cancel) and return. No mass-cache, funnel or mirror bookkeeping runs on a refusing Platform.
  - An unresolved account keeps today's behaviour, because the Fansly client can't load without one either.
- **String-id rule.** The Shim emits every Fansly id as a string. The cache stores it as an integer, and on the way out emits it as a string when it is above 2^53 − 1. That rule is Platform-neutral and keeps OnlyFans ids (well under 2^53) as numbers.
- **Mass tab.**
  - Accounts are filtered by `can(accountPlatform(a), "mass_history")` before the per-account queries.
  - The "more not loaded" line names the Creators whose last fetch said `incomplete` or `hasMore`. It sits beside the existing "Showing the newest N per Creator" line and doesn't replace it.
  - No new joint `useState`. If a second state appears that changes with the filter, it goes into the existing `massFilterReducer` (repo reducer rule).
  - Fansly rows use the existing row component. The tab's OnlyFans-worded error copy is left alone (Out of Scope).
- **Order inside the PR** (11 item 1: "02 a is the first commit"):
  1. `unsend_mass_message` + Blocked mark + automation and route gates + the four moved test reasons, which fail first against today's code.
  2. Fixture, history/engagement adapter, string ids, shape tests.
  3. `scheduled_messages` adapter + slicing.
  4. `mass_history` Capability + Mass tab filter/line + vitest.
  5. `queued_message`/`mass_message_buyers` reasons, parity and Lift table rows.
  6. Nova GETs + verify-app proof.
  - Steps 1–3 and 5 edit the Shim, so M1 applies before each (read the mirror log) and M3 after merge (send the sha).
- **File-rule seat.** This PR edits `server.py` and `fansly_shim.py`, so per 11 item 1 no other P2 PR touching either may be open alongside it. `app/lib/platform.ts` is a shared file (plan): message the mirror thread before editing it.
- **Ship line.** Branch, PR, merge when green after the merge-train check (11 item 4). It is safe in prod on its own: Fansly gains reads plus refusals, OnlyFans sends the same requests. No deploy by this Phase; this run deploys after 02h.

## Testing Decisions
Seams, highest first. Each test checks external behaviour (requests made, persisted rows, HTTP responses, rendered rows), never internals.
- **Shim seam: `FanslyShimClient` read methods over a fixture-fed `_request`.** New `fansly/test_broadcast_reads.py`, a plain script beside `test_shim_shapes.py`. It loads `fansly/fixtures/broadcast.json` and asserts:
  - the returned shapes;
  - the exact request sequence (`before=0`, then the last raw id, `limit=24`, no date params on the wire);
  - stop on empty page (complete); a repeated non-empty cursor and the page cap each give `incomplete` + `hasMore`; never stop on a short page; a malformed page raises;
  - a page whose first row is older than `start_date` ends the walk (locks the date-stop rule, ticket 02 item 1);
  - window and offset/limit/query slicing; type≠3, attachment and tip handling;
  - two adjacent above-2^53 ids that stay distinct strings, and `float(a) == float(b)` for that pair, which proves a number would collide;
  - `direct` raises Blocked;
  - scheduled-row status/parse/slicing rules.
  Prior art: `fansly/test_shim_shapes.py`, `fansly/fixtures/earnings.json`, `service/tests/test_fansly_cancel_scheduled_route.py` (snowflake id kept digit for digit).
- **Executor seam: `automation_executor.run_once(aid, "unsend_messages", …)` on a Fansly Creator with history built.** It extends `service/tests/test_fansly_automation_gates.py`, whose four existing reasons move to `platform_lacks:unsend_mass_message`, and adds the 00 item 4 zero-effect checks for the mass-only and mixed runs, plus dry run:
  - persisted run status/reason and `stats_json`: mass-only `skipped` + reason; mixed `ok`, no `reason`, `target_skips: {"mass": "platform_lacks:unsend_mass_message"}`;
  - unchanged mass cache, mass runs, queue copies and mirror rows;
  - zero `cancel_scheduled` / `unsend_mass_message` calls;
  - Fansly request log (Stateful fake): mass-only and dry run zero requests; mixed exactly the seeded chat unsend request(s) and their row flips, and a non-empty chat seed so the check can't pass vacuously;
  - the claimed job reaches its terminal disposition; no follow-up jobs.
  The OnlyFans control asserts the unsend test fakes record the same queue-id call as today. Prior art: the same file (`case_fansly_unsend_drops_the_mass_lane_and_runs_per_chat`), `test_unsend_messages.py`, `test_a12_unsend.py`.
- **Verdict table seam (02a's harness).** It updates the `unsend_messages` rows and adds the broadcast GET answers to the Stateful fake. Prior art: 02a's harness.
- **HTTP seam: Relay routes through the ASGI app, Nova's FixtureShim under the real client loader** (`scripts/demo-shots/fansly_relay.py` `install`, which swaps `fansly_backend.get_client`). New `service/tests/test_fansly_mass_reads_routes.py` covers:
  - DELETE, each with the Shim request log and the cache/funnel/mirror row deltas:
    - cached broadcast → 501 `platform_lacks:unsend_mass_message`, zero Shim calls;
    - uncached id not in `GET /post/scheduled` (a scheduled-broadcast id from the queue route) → 501, exactly one GET, zero writes;
    - id both cached and listed as a post → 501, zero Shim calls;
    - listed scheduled post → `GET /post/scheduled` then `POST /post/scheduled/{id}/cancel`, `mark_canceled` / funnel / mirror not called;
  - `/admin/mass-messages` cold (walks), refresh, warm (no request), and after clearing the walk memo (restart: walks again), for two `days_back` windows: string ids, `canUnsend: false`, and each window's own `hasMore`/`incomplete`;
  - the queue route pages Nova-shaped scheduled rows;
  - the Stats group route returns rows with string ids;
  - an OnlyFans control: an OnlyFans account's int ids stay numbers, the OnlyFans DELETE path and its bookkeeping are unchanged, and a warm OnlyFans read makes no request.
  `test_fansly_cancel_scheduled_route.py` is updated: its call list gains the leading `GET /post/scheduled` and `mark_canceled` is no longer awaited on Fansly. Prior art: that file.
- **Drift seam: `service/tests/test_platform_table_drift.py`.** `CAP_METHODS` gains `mass_history: (mass_message_history, engagement_messages)`, and the Fansly row agrees. Prior art: itself.
- **Lift-table seam: `fansly/test_lift_table.py` (02a's).** The reasons equal the markers after this Phase's moves.
- **App seam: pure helpers + component test.**
  - `massFilterBar.test.ts` gets a `moreNotLoaded` table.
  - `massUnsendRules.test.ts` checks that a `canUnsend: false` string-id row is not actionable and is not counted in bulk.
  - `MassMessagesTab.test.tsx` checks:
    - an account without `mass_history` gets no query;
    - two adjacent big string ids render as two rows;
    - the line appears for an `incomplete` Creator only.
  Prior art: those three test files.
- **Running app: verify-app `--fansly`.** `/growth/smart-messages?tab=mass` opened explicitly; desktop and phone screenshots, each trigger and settled, with both of Nova's broadcast texts on screen; the `/admin/mass-messages` response holding exactly Nova's two string ids with `canUnsend: false`; and exactly two matching cache rows from the temp DB (11 item 3, UI PRs). The "more not loaded" line is proved by the vitest and HTTP seams, since Nova's feed is whole.

## Acceptance
```sh
set -e
cd "$(git rev-parse --show-toplevel)"
# manual: worktree needs venv/ symlinked and app/node_modules cloned from the main checkout (verify-app SKILL.md)
PY=venv/bin/python
for t in test_broadcast_reads test_shim_shapes test_fansly_capability test_lift_table; do nice -n 10 $PY fansly/$t.py; done
for t in test_fansly_automation_gates test_fansly_mass_reads_routes test_fansly_cancel_scheduled_route \
         test_platform_table_drift test_platform_kind_verdicts test_unsend_messages test_unsend_mass_policy test_a12_unsend; do
  nice -n 10 $PY service/tests/$t.py
done
nice -n 10 $PY - <<'EOF'
import sys; sys.path[:0] = ["service", "fansly"]
from side_effect_gate import classify
from fansly_shim import FanslyShimClient as S
from of_client import OFClient
for n in ("engagement_messages", "mass_message_history", "scheduled_messages"):
    assert classify(S, n)[0] == "built", n
for n in ("unsend_mass_message", "queued_message", "mass_message_buyers"):
    assert classify(S, n)[0] == "blocked", n
assert hasattr(OFClient, "unsend_mass_message")
EOF
if grep -n "cancel_scheduled" service/automations/unsend_messages.py; then exit 1; fi
grep -q '"mass_history"' app/lib/platform.ts
test -f fansly/fixtures/broadcast.json && grep -q '"_source"' fansly/fixtures/broadcast.json
(cd app && nice -n 10 pnpm exec vitest related --run components/settings/MassMessagesTab.tsx components/settings/massFilterBar.ts components/settings/massUnsendRules.ts hooks/useMassMessages.ts lib/platform.ts)
nice -n 10 $PY scripts/comment_budget.py --check
test "$(PYTHONPATH=. nice -n 10 venv/bin/alembic -c service/db/migrations/alembic.ini heads | grep -c head)" = 1
# manual: regenerate the _send_kill_jobs.py strip patch with .claude/skills/public-sync/strip-regen.sh and commit it if it changed
nice -n 10 scripts/run-tests.sh
D=scripts/verify-app/drive.py
NOVA=900539700124344320
OUT=$(mktemp -d)
$D up --fansly
$D login --as owner --goto "/growth/smart-messages?tab=mass"
$D screenshot --path mass-fansly-desktop-trigger.png
$D wait --text "Nova Reyes" --timeout 120
$D screenshot --path mass-fansly-desktop-settled.png
$D screenshot --path mass-fansly-phone-trigger.png --phone
$D screenshot --path mass-fansly-phone-settled.png --phone
$D api "/admin/mass-messages?account_id=$NOVA" > "$OUT/api.json"
$D db "select queue_id, can_unsend from mass_broadcast_cache where account_id='$NOVA'" > "$OUT/db.json"
$PY - "$OUT" <<'EOF'
import json, sys
from pathlib import Path
d = Path(sys.argv[1])
def find(o, k):
    if isinstance(o, dict):
        if k in o: return o[k]
        for v in o.values():
            r = find(v, k)
            if r is not None: return r
    return None
items = find(json.loads((d / "api.json").read_text()), "items")
ids = [i["id"] for i in items]
assert len(ids) == 2 and len(set(ids)) == 2 and all(isinstance(i, str) and len(i) >= 18 for i in ids), ids
assert all(i["canUnsend"] is False for i in items), items
rows = json.loads((d / "db.json").read_text())["rows"]
assert sorted(str(r["queue_id"]) for r in rows) == sorted(ids) and not any(r["can_unsend"] for r in rows), rows
EOF
$D down
# manual: the settled shots show both Nova broadcast texts; link the four screenshots and the api/db output in the PR body
```

## Depends on
- **02a — Primitives.** It provides:
  - the neutral Platform markers (`platform_blocked`, used here for `unsend_mass_message`);
  - the Stateful fake (gains this Phase's two GETs);
  - the Verdict table harness (this Phase updates its unsend rows);
  - the Lift table, `fansly/test_lift_table.py` and the parity doc's Provenance/Coverage columns.
- Not a dependency: 02d's Unknown-platform sentinel. The `mass_history` filter works on today's `accountPlatform`/`can`.
- Linear PR order (D8): 02a-1 → 02a-2 → 02b → 02c → 02d → **02e** → 02f → 02h → 02g. Under the 11 file rule this PR doesn't overlap 02b/02c/02d PRs that edit `server.py` or `fansly_shim.py`.
- Downstream: 02f needs `scheduled_messages` (read-back) and `unsend_mass_message`.

## Out of Scope
- Merging scheduled broadcasts into `schedules()` and string ids in `useScheduledMessages`: these wait for 02f's typed cancel and 02g's mirror-filtered `FanslyScheduled` (ticket 02 item 4, 14 F).
- Any Fansly broadcast write: send, schedule, cancel, edit (02f).
- A delivered-broadcast unsend on Fansly: never captured, so it stays Blocked until a Capture session records one.
- `/stats/deleted` → `isCanceled`: it only matters once a delete exists (ticket 02 fog), so YAGNI.
- Media or priced broadcast rows: the capture saw no such row; they're skipped until a free-media broadcast row is captured (02f/14 dropped media broadcast).
- Mapping `stats.total`: its meaning against `delivered` is unobserved (fog).
- Buyers and single-row queue reads: Blocked (ticket 02 items 5, 6).
- The Mass tab's OnlyFans-worded error copy on Fansly rows: ticket 02 fog says the mirror may own the wording. It's cosmetic and a one-line follow-up.
- The Fansly Manager's Scheduled page (`FanslyScheduled.tsx`): mirror-owned.
- Persisting the `incomplete` flag in a cache column: YAGNI; a Fansly read with no memo for its window walks again instead (assumption below).
- Live checks: none, since this Phase builds reads and refusals only.
- Slop: owner rule.

## Further Notes
- Needs the human: nothing for this Phase. The broadcast Live check (text-only, list holding only the Proof fan) belongs to 02f/02g.
- ASSUMPTION: page size 24, the only `limit` seen in the capture (ticket 02 item 1). Falls: the page cap only.
- ASSUMPTION (evidence blocked): the one stats row seen was text-only, so `isFree: true` holds for every kept row (ticket 02 item 2). Falls: media rows stay hidden until a broadcast Live check adds a free-media row.
- ASSUMPTION: `stats.delivered` = OnlyFans `sentCount` (ticket 02 item 2; map assumption). Falls: one mapping line.
- ASSUMPTION: the Stats search box is a case-insensitive substring match on `content` in the Relay (ticket 02 item 2). Falls: search on Fansly Group Stats.
- ASSUMPTION: the cursor advances on the raw page's last id, including skipped and out-of-window rows (rung 5, so a page of skipped rows can't stall). Falls if Fansly's `before` doesn't accept a skipped row's id: the walk stops on a repeated cursor and reads `incomplete` (walk rules).
- ASSUMPTION: stats pages come newest-first by id, and snowflake ids encode creation time, so the binding date stop (ticket 02 item 1) loses no in-window row (inferred from `before` = last id, `RECIPES.md:1023`; only one page was captured). Overturned by a fixture or capture where a later page holds a row newer than an earlier page's row; then the date stop becomes a page-level filter and the walk runs to empty/cap.
- ASSUMPTION: both broadcast GETs are reads (the capture uses the queue GET as the read-back after cancel, `RECIPES.md:1024`; no before/after on the stats GET, 00 item 3). Overturned if the 02f broadcast Live check sees provider state change across two stats reads; then the stats read is treated as a write.
- ASSUMPTION: a malformed stats page raises the Shim's API error class, not a ValueError (rung 3: Shim errors are Backend API errors that routes map by status). Falls: one exception type.
- ASSUMPTION: the "direct" engagement type is refused by the Shim's Blocked raise inside the method, with no separate Lift-table row (rung 5). The Lift table counts markers, Lacks flags and Verdict `gated:` reasons, and this is none of those. Overturned if 02a's or 02c's table counts in-method Branch raises; then a `platform_lacks:engagement_messages:direct` row and a declared blocked Branch are added.
- ASSUMPTION (evidence blocked): OnlyFans `/messages/queue` answers `{list, hasMore}`, so the Fansly scheduled read copies the Shim's `schedules()` envelope (rung 3; no OnlyFans fixture, and no app reader of the GET today). Falls: the envelope keys of one method.
- ASSUMPTION: scheduled rows don't emit `userLists`/`groups`/price/media (rung 4: Unseen values; 14 item 11's assumption that `groups[]` carries the list is 02f's to prove). Falls: 02f adds the list mapping with its read-back proof.
- ASSUMPTION: string ids only above 2^53 − 1 at the mass-cache boundary, not for every Platform (rung 4: OnlyFans rows unchanged). Overturned if the owner wants one id type everywhere; then all cache ids become strings and the OnlyFans unsend and keys get re-tested.
- ASSUMPTION: on a Fansly Creator, a DELETE id that is neither a cached broadcast nor a listed pending scheduled post answers 501 `platform_lacks:unsend_mass_message`, not 404. This covers a scheduled-broadcast id, an uncached delivered one, and a stale post id that today would reach Fansly and fail (rung 4: refuse before any write; one reason keeps the Lift table at one row). Falls: the reason or status of one branch; 02f's typed cancel replaces the scheduled-broadcast case.
- ASSUMPTION: `hasMore`/`incomplete` come from a process-memory walk memo keyed by account, `days_back` and `limit`. On Fansly a missing memo counts as stale and walks once (≤20 GETs, reads only). On OnlyFans the flags are absent after a restart and no extra request is made (rung 4 + 5: no migration; OnlyFans request count unchanged). Overturned if the owner wants the line to survive restarts without a walk; then the flag moves to a cache column, which needs a migration.
- ASSUMPTION: the "more not loaded" line also shows for OnlyFans Creators whose history says `hasMore`. Ticket 02 item 7 words it Platform-neutrally (rung 2), but it is a visible OnlyFans change. Overturned if the owner wants it Fansly-only; then it keys on `incomplete` alone.
- ASSUMPTION: `mass_message` keeps `mass_message_history` in its Drift mapping (rung 4: smallest change; send stays refused, so the verdict is the same). Falls: one mapping entry.
- ASSUMPTION: the unsend gate checks `unsend_mass_message` before `mass_message_history`, so slice a's first commit already shows the final reason (rung 5). Falls: the order of two names.

## Review
Reviewer: codex (blind + draft), 2026-11-27
- B1 (blind) cache membership can't authorize a Fansly DELETE — **accept**: verified `mass_queue_api.py:516-538` cancels then stamps mass bookkeeping, and the queue GET returns uncached broadcast ids. DELETE now needs positive post identification (`schedules()` read) after the cached check, skips mass bookkeeping on Fansly; cached/uncached/colliding/post tests (Stories 8-9, Gate order, HTTP seam).
- B2 (blind) first-page-only vs cursor walk; ordering; repeated cursor; read-ness — **partial**: first-page-only and dropping the date stop rejected (ticket 02 Answer item 1 binds the id walk and "stop at first row < start_date"); repeated non-empty cursor now `incomplete` (Walk rules, Story 17); ordering and GET read-ness are ASSUMPTIONs with falsifiers, plus a date-stop shape test.
- B3 (blind) ids/completeness through refresh, warm reload and `useMassMessages`; 20×24 < 500 — **partial**: carry-through accepted (walk memo keyed by window+limit, cold/refresh/warm/restart test); a 500-row request over a >480-row feed reading `incomplete` is the designed cap outcome, not a defect (noted in Walk rules).
- B5 (blind) prove at the Relay boundary — **accept**: HTTP seam runs Nova's FixtureShim under the real loader (`fansly_relay.py` install), Group Stats, queue GET, cold/refresh/warm/restart admin reads, DELETE cases with request log and row deltas, OnlyFans control; distinct big-id rows stay in the vitest seam.
- D1 (draft, blocker) DELETE treats a cache miss as post intent — **accept**: same change as B1.
- D2 (draft, major) stalled walk claims completeness — **partial**: repeated cursor after a non-empty page now sets `incomplete` (fixes the spec's internal contradiction); the date-stop rule stays per ticket 02 Answer item 1, with the ordering ASSUMPTION and its falsifier.
- D3 (draft, major) account-only memo conflates windows; lost after restart — **accept**: memo keyed by account+`days_back`+`limit`; on Fansly a missing memo is stale and walks once; OnlyFans unchanged (flags absent, no extra request). Interfaces, Contracts, Story 39, ASSUMPTION rewritten.
- D5 (draft, major) mixed-run proof contradicts the chat story — **accept**: verified `test_fansly_automation_gates.py:180-193` (one chat unsend, `ok`); Executor seam now requires the exact chat request and row flips, non-empty chat seed, zero mass calls, persisted `target_skips`, terminal job disposition; Story 6 reworded.
- D6 (draft, major) UI acceptance can pass on the wrong tab — **partial**: `?tab=mass` (verified `useTabParam("tab")`, `SmartMessagesPage.tsx:48`), exact two string ids, `canUnsend:false`, exactly two matching cache rows, trigger+settled on both viewports accepted; the partial line on the running app rejected (Nova's feed is whole; proved by vitest + HTTP seams).
- D7 (draft, major) false 02a prerequisite — **accept**: verified 02a Out of Scope excludes 09 C; the filter uses today's `accountPlatform`/`can`, the 02a bullet is removed, 02d's sentinel noted as composing, not required.
- D8 (draft, major) merge checks incomplete — **accept**: one-alembic-head check (02b precedent), and `! grep` replaced with `if grep …; then exit 1; fi` (verified `sh -ec '! true; echo survived'` prints `survived`).
- D9 (draft, minor) scheduled rows outside the Mass-tab objective — **accept**: Objective now says the Mass tab shows sent history and the queue is read back via `/messages/queue` only.

Plan review (six hats + coordinator D1–D8), 2026-11-27:
- Yellow [02e,02g], string snowflake ids close a measured collision bug — **accept**. Kept as is: string ids above 2^53 − 1 at the mass-cache boundary; 02g's consumers read them as strings.
- White [plan], linear order — **accept** (D8). Depends on now states the linear order; the sequencing note folds into it.
- Real handle in Further Notes replaced with "the Proof fan" — **accept**.
- Blue cite 02a's grant names — **n/a**: 02e reads only and takes no Live-check grant.
Counts: accept 3 · partial 0 · reject 0 · needs-human 0.
