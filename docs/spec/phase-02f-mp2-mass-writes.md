# Phase 02f — Mass writes

**Objective.** A Fansly broadcast to one numeric list, sent now or scheduled, and the cancel of a scheduled one, are Live-check methods: each refuses before any request, claim, run row or job unless a Live-check grant names that Creator, method and a list whose Complete read holds only the granted Fan. Every other broadcast Branch is a persisted Platform refusal.

## Problem Statement
An operator on a Fansly Creator can start a mass message from the composer, an automation (send_mass_message, mass_premade), and today the outcome is wrong in four ways:
- **Nothing guards a real send.** The only guard is the Shim's `confirm_live_broadcast` kwarg, and no Relay caller passes it.
- **Arguments are thrown away.** The Shim takes `include_lists`/`exclude_lists` and swallows everything else through `**_ignored`. The runner's `user_lists`, `excluded_users`, `price`, `filters` and `online_only` are dropped, so a broadcast that worked would reach a different audience than the one planned.
- **A successful send reads as a failure.** The send returns `"broadcast sent"` as its id, and the runner's `int(queue_id)` crashes after delivery.
- **Refusals still leave side effects behind:**
  - mass_premade plans its dry run before the gate and drips the rest after a refused send.
  - The route reserves keys, mints runs and syncs exclude lists before it learns Fansly can't do it.
  - A lost response outside Cells has no ledger, so a retry or a restart can double-send.

The operator can't schedule or cancel a Fansly broadcast either. Settings' Cancel can't say which kind of row it is cancelling.

## Solution
- **Eligible broadcast.** On Fansly the only broadcast that goes out is text only, to exactly one numeric Fansly list, with no explicit exclusions, filters, funnel, media, price, locked text, tags or giphy. Each other shape refuses with its own `platform_lacks:send_mass_message:<branch>`, before anything is touched.
- **Grant and audience check.** Even the eligible shape refuses until the owner sets a Live-check grant for that Creator and method. The Relay then reads the list (a Complete read) and requires it to hold only the granted Fan and none of the Fans the contact guard would skip. It re-reads the list just before the POST.
- **Ledger.** Every Fansly broadcast goes through the send ledger, so a lost response shows as uncertain and is never re-sent, even after a restart.
- **Schedule and cancel.** Scheduling uses the same check under its own grant. Cancelling a scheduled broadcast reads the row's list and checks it the same way, then cancels and reads back.
- **OnlyFans** behaves exactly as today. Its cancel goes through a typed method that calls the same wire.
- **Defaults.** With no grant set, which is every deployed Relay because `PLATFORM_LIVE_CHECK` has no compose passthrough, every Fansly mass write is a persisted Platform refusal with zero requests.

## User Stories
4. As an operator, I want a mass_premade dry run on Fansly to return the same persisted Platform refusal as a live run, so that a preview never suggests it would send.
5. As an operator, I want mass_premade to refuse before it resolves folder media, so that a refused run never touches the vault.
6. As an operator, I want a refused inner send in mass_premade to stop the run with that reason and enqueue none of the remaining messages, so that one refusal is not followed by a drip of later refusals.
7. As an operator, I want `unsend_after_hours` on Fansly to refuse as `platform_lacks:unsend_mass_message` before the send, so that a send is never left with a promised unsend that can't happen.
8. As an operator, I want a broadcast with no list, two or more lists, or a non-numeric list to refuse as `:audience_lists`, so that only the single-list shape the capture proved is sent.
9. As an operator, I want a broadcast to explicit fans, a local list id or a recent-chat or unread selection to refuse as `:recipients`, judged on the raw request or payload before audience resolution can empty it, so that no recipient set is sent that Fansly can't target.
10. As an operator, I want explicit exclude users or exclude lists to refuse as `:exclude_lists`, so that the unproven 30001 recipient type is never sent.
11. As an operator, I want an enforce-mode audience policy (AUTOFENCE) to refuse as `:autofence`, while a paused or unhealthy policy keeps today's AudienceHalt outcome, both before any list sync, so that no exclusion list is written for Fansly and the kill switch still reads as the kill switch.
12. As an operator, I want `online_only`, `filters` or any spend/tip/tenure/expiry threshold to refuse as `:filters`, `price`/`media_files`/`previews` as `:media`, `funnel_id` as `:funnel`, and locked text, tags or giphy as `:extras`, so that no part of the message is silently dropped.
13. As an operator, I want the contact guard to keep working: a Complete read of the list intersected with the contact-guard exclusions must be empty, or the send refuses as `:contact_guard:<n>` with the overlap count in the reason, so that a Fan the guard protects is never messaged. The set is every effective exclusion the house resolver builds (contact-guard windows, MASSdmEXCLUDE, pending sends, funnel responders).
14. As an operator, I want a list read that isn't Complete to refuse as `:list_incomplete`, so that the send never trusts a partial audience.
15. As an operator in Cell mode, I want every Fansly broadcast write to refuse as `:cell_mode` before any request (ticket 14 item 9), so that no Cell claim ever carries a broadcast until a Cell-mode broadcast is proven.
16. As the owner, I want every Fansly broadcast caller (route and runner) to check the Live-check grant before any claim, key reservation, run row, client build, lock, list sync, dry run or request, so that with no grant there are zero requests.
17. As the owner, I want a grant with a list that holds anyone other than my fan to make only membership GETs and zero writes, so that a wrong list can never reach a real Fan.
18. As the owner, I want the list re-read before the run row is minted and again between POST /group and POST /message/broadcast, so that a Fan added after authorization or during group creation blocks the send.
19. As an operator, I want a sent Fansly broadcast to record the run ok with a null queue id, so that a delivered message never shows as an error.
20. As an operator, I want every Fansly broadcast written to the send ledger in both modes, with a lost response recorded as `uncertain` and never retried, so that a broadcast is never sent twice, even across a restart.
21. As an operator, I want any new Fansly mass send on that Creator refused 409 while a mass ledger row is `uncertain`, whatever its key, so that a reload or edit that mints a fresh composer key can't resend an uncertain broadcast.
21a. As an operator, I want a replayed ledger op to return its stored result before any run row is minted, so that a replay adds no `mass_runs` row.
22. As a developer, I want the Shim's mass methods to take the runner's argument names, raise `TypeError` on an unknown argument and refuse blocked values, so that no argument is ever dropped.
23. As a developer, I want `confirm_live_broadcast` gone, folded into the Live-check grant, so that there is one guard.
24. As the owner, I want a scheduled Fansly broadcast (text, one list, `scheduledFor` in ms) behind its own grant, with `save_for_later` refused, an unparseable or not-future `scheduled_date` refused as `:scheduled_date` before any request, and the new row identified by a raw before/after read of the scheduled queue, so that I can prove scheduling before it lifts.
25. As an operator, I want cancelling a scheduled broadcast to go through a typed `cancel_scheduled_mass_message`, which on OnlyFans calls today's wire unchanged, so that chat and post cancels never cross.
26. As the owner, I want a Fansly cancel to probe its grant first (no grant, zero requests), bind to this Creator's pending (`status: 1`) row and its single type-30000 list, POST the cancel and confirm from the raw cancel response and a raw re-read, failing closed when the row, group or list is missing or ambiguous, so that a cancel never acts on an unknown audience and never falls back to a post cancel.
27. As an operator in Settings or a chat's scheduled list, I want Cancel to send the row's `type` when the row has one, so that the Relay picks the chat or post cancel correctly and a typeless call keeps today's behaviour.
28. As the owner, I want `edit_queued_message` to stay Blocked, so that an edit never loses the message by cancelling and re-creating it.
29. As a reviewer, I want the Verdict table, the Lift table and the parity rows for send, schedule, cancel and mass_premade updated in the same PR, so that the docs match the gates.
30. As the owner, I want the manual Live checks listed with exact steps, so that I can run them after 02g lands and lift each method in its PR 2.

## Implementation Decisions
- **Owns.**
  - Relay: Side-effect gate, send_mass_decide, automations send_mass_message / mass_premade, mass_queue_api, send_ops, of_write (only the no-retry option), of_sends (OFClient), server (only the boot `send_ops.install`).
  - Shim: FanslyShimClient's `send_message` / `send_mass_message` / `schedule_mass_message` / `cancel_scheduled_mass_message` / `_broadcast_group` and its `UNBUILT` entry; FanslyClient `_request`'s `delivery` flag.
  - App: useScheduledMessages, ScheduledTab and ScheduledForChat (pass `type`).
  - Docs: the parity doc rows and the Lift table rows.
  - Tests: the Verdict table rows.
- **Interfaces.**
  - **`broadcast_branch_refusal(args, audience_policy) -> str | None`.** Pure, beside 02a's `send_refusal`.
    - `args` is the raw send arguments under the runner's names (`user_lists`, `included_users`, `excluded_users`, `excluded_user_lists`, `price`, `locked_text`, `media_files`, `previews`, `tagged_users`, `giphy_id`, `filters`, `online_only`, `funnel_id`, `save_for_later`, `scheduled_date`) plus the raw selectors (`recent_chat_hours`, `recent_chat_limit`, `unread_limit`, `min_total_spent`, `min_tipped`, `subscribed_over_days`, `expired_over_days`, `unsend_after_hours`). Callers pass the payload or request body before `resolve_mass_audience`, so resolution can't erase a selector.
    - It returns `platform_lacks:<method>:<branch>`, where `method` is `send_mass_message` or `schedule_mass_message`.
    - The runner, the route and the Shim all call it, so one function is the truth.
  - **Grant API (02a, unchanged).** `live_check_targets(aid, method)` is the presence probe (env only, zero requests); `live_check(aid, method, audience)` is the exact check; grants are `<aid>:<method>:fan=<id>`. 02f adds no gate helper.
  - **Gate paths for a Live-check method.** 02a's `refusal` returns a reason for a `platform_live_check` method (`phase-02a-mp2-primitives.md:61`), so every Fansly caller of the three methods replaces `refusal_for_account` / `refuse_if_platform_lacks` with grant probe + `live_check`. `send_ops._capable` admits a Live-check verdict only when `live_check_targets(aid, method)` is non-empty; otherwise it refuses as today. Presence only admits the claim: `_capable` has no audience, so the write is gated by the caller's exact `live_check` on the Complete read, re-run at `before_write` and at `_before_broadcast`. Cases 3 and 4 prove a granted wrong audience makes zero writes. OnlyFans paths are untouched.
  - **The audience passed to `live_check(aid, method, audience)`** is `ListAudience(list_id, member_ids, complete)` from `list_users_in`'s Complete read (02b); under the `fan=` grant it passes only when `complete` and `member_ids == {fan}`.
  - **OFClient `cancel_scheduled_mass_message(queue_id)`.** Delegates to `cancel_scheduled`; the wire is unchanged.
  - **Shim `send_mass_message`.** Keyword-only arguments under OFClient's names and no `**_ignored`. It calls `broadcast_branch_refusal`, then raises the typed refusal. It takes a private `_before_broadcast(group_id)` callback, run after POST /group and before POST /message/broadcast. It returns `{"success": True, "groupId": g, "id": None}`.
  - **Broadcast group is not a delivery.** `_broadcast_group` posts /group with a private `_request(..., delivery=False)` that skips the claim Budget (hold check unchanged). POST /group type 3 is idempotent per audience and delivers nothing (`fansly/capture/RECIPES.md:1008`); without this the one-write Budget is spent on /group and the broadcast POST raises `SendBudgetSpent` (`send_tripwire.py:25-28`, `fansly_client.py:231-235`). DM `create_group` keeps its budget. This applies outside Cells only; Cell mode refuses before any request (`:cell_mode`).
  - **`send_ops.pre_wire`** recognises the typed Platform refusal, so a refusal raised before the broadcast POST records `refused`, not `uncertain`.
  - **Shim `schedule_mass_message`.** Same names plus `scheduled_date` and `save_for_later`; it leaves `UNBUILT`. Both mass methods carry `platform_live_check`.
  - **Shim `send_message`.** Gains a private `_scheduled_for_ms`, which only `schedule_mass_message` passes. A broadcast response that isn't a dict yields `id: None`, following the `create_post` precedent.
  - **Shim `cancel_scheduled_mass_message(queue_id)`** (`platform_live_check`). Does POST /message/broadcast/scheduled/<id>/cancel and reports done only when the raw cancel response is that id with `status: 3` and a raw GET /message/broadcast/scheduled shows that id absent or `status: 3`. Anything else (malformed, other status, error) is not done. 02e's filtered `scheduled_messages` is never the confirmation, because it hides status 3 and malformed rows.
  - **Shim `scheduled_broadcast_audience(queue_id) -> str | None`.** A raw read that finds the row by exact id, requires `accountId` = this Creator and `status: 1`, maps its `groupId` through `groups[]`, and returns the list id only when the group has exactly one recipient of type 30000; else None.
  - **Shim `scheduled_broadcast_ids() -> dict[str, tuple[str, int]]`.** Raw `{id: (groupId, scheduledFor)}` of pending rows, for schedule matching.
  - **`send_ops.automated_sync(..., ledger=True)` and `send_ops.begin(..., ledger=True)`.**
    - The kwarg forces the ledger outside Cells.
    - Outside Cells this skips owner-epoch, permit and hold, and stores the epoch as NULL.
    - `(kind, anchor)` dedupe and the `claimed→uncertain` boot sweep stay as they are.
  - **`of_write_paced(..., retry=False)`.** Runs `fn` exactly once.
  - **`useCancelScheduled`.** Takes `{id, accountId, type?}` and adds `?type=<type>` only when given. ScheduledTab and ScheduledForChat both pass the row's `type` when present.
- **Schema.** None. The send ledger table already exists. 02f only runs `send_ops.install` (CREATE IF NOT EXISTS) at every Relay boot instead of only in Cells.
- **Contracts.**
  - **Fansly wire**, exact bodies from RECIPES §6.6:
    - POST /group: `recipients` is exactly `[{"recipientId": <listId>, "type": 30000}]`, with no 30001, `groupFlags: 32`, `groupFlagsMetadata: ""` and `users: [{userId: <creator>, permissionFlags: 65535}]`.
    - POST /message/broadcast: `type: 1`, `attachments: []`, `likes: []`, `content`, `groupId`, `scheduledFor` (0 for send, epoch ms for schedule) and `inReplyTo: null`.
    - Cancel: POST /message/broadcast/scheduled/<id>/cancel with no body.
  - **Relay routes.**
    - POST /api/of/v2/messages/queue answers 501 with `detail` = the Platform refusal reason (for the guard, `platform_lacks:<method>:contact_guard:<n>`).
    - DELETE /api/of/v2/messages/queue/{id} takes an optional `type` query (`chat` → `cancel_scheduled_mass_message`). With no `type` it keeps today's behaviour.
  - **Persisted run.** `{"status": "skipped", "reason": "platform_lacks:<lack>[:<branch>]"}`; the guard branch carries its count as `:contact_guard:<n>` (ticket 14 item 4). The Lift table lists it as `…:contact_guard:<n>`; 02a's drift test strips one trailing `:<digits>`.
  - **Grant.** One `<aid>:<method>:fan=<id>` entry (02a grammar) each for `send_mass_message`, `schedule_mass_message` and `cancel_scheduled_mass_message` (ADR-0070).
- **Order inside the PR** (plan 11 file rules: one PR at a time touches platforms.py, server.py or fansly_shim.py; read the mirror log before each Shim edit, M1; send the sha after the merge, M3):
  1. **14A re-key.**
  2. **14C caller auth.** 00 slice c (`confirm_live_broadcast` removal) lands in this same commit, so no commit has neither guard.
  3. **14B Shim lift.**
  4. **D, E and G.** 03 slice 2 rides along with A and B.
  - Each of the four commits runs green on its own and is reviewed commit by commit; the PR stays one (one Shim lift, one file-rule slot).
- **14A re-key.**
  - `delete_live_set._cancel` calls `client.unsend_mass_message` (OF delegates to `cancel_scheduled`, per 02e).
- **14C caller auth: runner** (automations send_mass_message, Fansly account only; OnlyFans keeps its order). The runner runs these steps before the `unread_limit` reads, `_make_client`, the dry run, `broadcast_lock`, list sync, ledger claim and POST /group:
  1. **Pure gates:**
     - the Platform refusal;
     - the Cell mode check (`:cell_mode`);
     - `broadcast_branch_refusal` over the raw payload, before `resolve_mass_audience`;
     - `unsend_after_hours` (`platform_lacks:unsend_mass_message`);
     - AUTOFENCE: paused/unhealthy → today's AudienceHalt; enforce → `:autofence`.
  2. **Grant probe.** No grant gives `platform_lacks:send_mass_message` and zero requests (no client build either).
  3. **One Complete read** of the list (GET; a cold client may first GET /device/id).
  4. **`live_check`** on that read.
  5. **Contact-guard intersection** against `plan.excl_set` (already every effective exclusion: windows, MASSdmEXCLUDE, pending sends, funnel responders, `send_mass_message.py:183-201`).
  6. **Fansly skips** `ensure_exclude_list` and `drop_exclude_list_members`.
  7. **Ledger first.** `send_ops.begin(..., ledger=True)` runs before mint. A `Sent` replay returns its stored result with no mint, no POST. An `uncertain` mass row on the Creator refuses 409 (`fan_held` extended to Fansly manual mass kinds, `send_ops.py:142-146`).
  8. **`before_write`** re-reads the list and re-runs both checks. A failure raises a typed refusal before mint, so no MassRun row exists. A pass mints.
  9. **`fn`** is `claim.wire` around the Shim call, with `retry=False`; `_before_broadcast` re-reads once more after /group. A failure there raises the typed refusal: zero broadcast POSTs, ledger `refused`, the minted run closed unsent (`close_run_if_unsent`).
  10. **`queue_id`** None skips the `int()` and every row keyed on it.
- **Caller auth: route.**
  - POST /queue on a Fansly account runs the same steps over the request body before `_reserve_send`, any ledger claim, `resolve_mass_audience` reads that need a client, `_exclude_list_held` and `_open_mass_run`.
  - The branch check runs on the raw body: thresholds → `:filters`; `user_ids`, `recent_chat_*`, `unread_limit` → `:recipients`; `unsend_after_hours` → `platform_lacks:unsend_mass_message`.
  - The contact-guard set is the route's full `resolve_mass_audience` exclusion set (windows, MASSdmEXCLUDE, pending sends, funnel responders), resolved with no client.
  - `require_recipients` applies to the Complete read's size (an empty list refuses 422 as today).
  - The ledger anchor is X-Op-Id read regardless of Cells (`send_ops.anchor(request, ledger=True)`), falling back to the composer key hash. `begin` runs before `_open_mass_run` (as today), and any `uncertain` mass row on the Creator refuses 409 whatever the anchor.
  - The same `_before_broadcast` re-read runs between /group and the broadcast POST.
- **mass_premade.**
  - The gate set above runs before the dry-run return and before `pick_media`.
  - A non-ok inner send whose reason starts `platform_lacks:` ends the run skipped with that reason. It skips `_drip_rest`, the unsend job and the resend follow-up.
- **00 slice c.**
  - `confirm_live_broadcast` and `_BROADCAST_UNCONFIRMED` are removed.
  - The three tests that pass the kwarg (test_outbound_word_guard, test_of_rich_text, test_cell_send_tripwire) drop it.
  - The executor zero-effect test is the runner case in Testing Decisions.
- **D: schedule.** POST /queue with `scheduled_date` on Fansly runs the same gates under `schedule_mass_message`.
  - `save_for_later` refuses as `:save_for_later`; an unparseable or not-future `scheduled_date` refuses as `:scheduled_date`, both before any request.
  - Before /group the Shim snapshots `scheduled_broadcast_ids()`; after the POST it re-reads. The new row is the one id not in the snapshot with this `groupId` and `scheduledFor`. Exactly one → the ledger stores it and the result's `id` is that string. Zero, several, or a failed re-read after acceptance → ledger `uncertain`, never retried.
  - The run row stays open as OnlyFans' scheduled path leaves it (`mass_queue_api.py:413-414`); a cancel settles it through `mark_queue_unsent`.
- **E: cancel.**
  - DELETE with `type=chat` runs these steps in order:
    1. grant probe (no grant: `platform_lacks:cancel_scheduled_mass_message`, zero requests);
    2. `scheduled_broadcast_audience`;
    3. the Complete read;
    4. `live_check(aid, "cancel_scheduled_mass_message", audience)`;
    5. the Shim cancel and its raw confirmation;
    6. the existing cache `mark_canceled`, funnel close and `mark_queue_unsent`.
  - An unknown, foreign, non-pending row or an ambiguous group fails closed as `platform_lacks:cancel_scheduled_mass_message:audience_unknown`. `type=chat` never falls back to the post cancel; no `type` keeps today's post cancel and the OnlyFans path.
- **G.**
  - Lift table: one row per new reason.
  - Parity rows: send_mass_message, schedule_mass_message and cancel move to 🔬 Live-check.
  - Verdict table rows: send_mass_message and mass_premade, one per Branch, each `gated:<reason>` with no grant.
- **Deploy.** Deploy waits for 02h. With no grant passthrough, every new path is off in production.

## Testing Decisions
- **Main seam: one test file, service/tests/test_fansly_mass_writes.py.**
  - It drives `run_once` for the four kinds plus the Relay routes POST and DELETE /api/of/v2/messages/queue.
  - It runs on the real FanslyShimClient with 02a's Stateful fake installed at `FanslyClient.http.request`, below the Shim and the tripwire Budget, so the claim budget is exercised (/group, /message/broadcast, scheduled GET, cancel, list members, /device/id), with an OnlyFans control.
  - Each case asserts external behaviour only:
    - the persisted run status and reason;
    - the terminal job disposition;
    - exact provider-call deltas and exact request bodies;
    - business-row deltas: mass_runs, send_ops rows, claims, jobs, exclude lists.
  - Cases:
    1. Each refused Branch plus the dry run, at both entry points: skipped, zero requests, zero rows. Raw selectors that resolution would erase (explicit fans all excluded, recent-chat, unread, thresholds, route `unsend_after_hours`) are run with a grant and an otherwise eligible list and still refuse.
    2. No grant: zero requests, on a cold client (no device id).
    3. Grant with a two-member list: GETs only (device id + membership), zero writes; session-file rewrite is the only local write.
    4. A second member added after authorization: refused at the pre-mint re-read, zero POSTs. A member added in the fake's /group response: refused at `_before_broadcast`, one /group, zero broadcast POSTs, ledger `refused`.
    5. Granted send through the real Budget: exact bodies, run ok, `queue_id` null.
    6. Lost broadcast response: one POST, ledger `uncertain`. After a simulated restart (`send_ops.install` sweep), replays of both a `sent` and an `uncertain` op make zero POSTs and zero `mass_runs` rows; a fresh composer key on the same Creator gets 409.
    7. Cell mode: `:cell_mode`, zero requests.
    9. mass_premade with a folder and two messages: persisted refusal, zero jobs.
    10. Schedule: ms `scheduledFor`; an existing lookalike row is not matched; invalid or past date refuses with zero requests; a failed re-read after acceptance leaves `uncertain`.
    11. Cancel: no grant zero requests; POST, raw status 3; foreign, non-pending, malformed or unknown row fails closed; `type=chat` never hits the post cancel.
    12. OnlyFans: `cancel_scheduled_mass_message` makes the same DELETE as today; post cancel with no `type` unchanged.
- **Verdict table.** service/tests/test_platform_kind_verdicts.py (02a) gains the rows. The Lift table drift test fansly/test_lift_table.py (02a) checks the reasons.
- **Pure function.** `broadcast_branch_refusal` gets a case table in test_send_mass_decide (rung 3: the pure decide tests live there).
- **App.** New useScheduledMessages.test.ts drives the real `useCancelScheduled` over a mocked `relay.delete` and asserts the URL with and without `type`. ScheduledTab.test.tsx and a new ScheduledForChat.test.tsx assert each caller passes the row's `type` (the existing ScheduledTab test mocks the hook, so it can't see the URL).
- **Prior art:**
  - service/tests: test_fansly_automation_gates (`_Recorder` + `run_once`), test_fansly_cancel_scheduled_route, test_unconfirmed_sends (`send_ops.install` on the harness DB), test_send_ops_kill, test_mass_premade, test_send_mass, test_of_client_mass_body;
  - fansly: test_har_replay (body value compare), test_shim_shapes.

## Acceptance
```sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
for t in test_fansly_mass_writes test_platform_kind_verdicts test_fansly_automation_gates \
         test_fansly_unsupported_writes test_fansly_cancel_scheduled_route test_mass_premade test_send_mass \
         test_send_mass_decide test_unconfirmed_sends test_send_ops_kill \
         test_cell_send_tripwire test_outbound_word_guard test_of_rich_text test_of_client_mass_body \
         test_mass_queue_lock test_platform_capability; do
  nice -n 10 venv/bin/python "service/tests/$t.py"
done
for t in fansly/test_*.py; do nice -n 10 venv/bin/python "$t"; done
test -z "$(git grep -n -e confirm_live_broadcast -e _BROADCAST_UNCONFIRMED -- service fansly app || true)"
nice -n 10 venv/bin/python - <<'PY'
import inspect, sys
sys.path[:0] = ["fansly", "service"]
from fansly_shim import FanslyShimClient as S
for m in ("send_mass_message", "schedule_mass_message", "cancel_scheduled_mass_message"):
    ps = inspect.signature(getattr(S, m)).parameters.values()
    assert not any(p.kind is p.VAR_KEYWORD for p in ps), m
assert "schedule_mass_message" not in getattr(sys.modules["fansly_shim"], "UNBUILT", {})
PY
test -z "$(git diff --name-only main...HEAD -- service/db/migrations)"
test "$(PYTHONPATH=. nice -n 10 venv/bin/alembic -c service/db/migrations/alembic.ini heads | grep -c head)" = 1
(cd app && nice -n 10 pnpm exec vitest related --run hooks/useScheduledMessages.ts components/settings/ScheduledTab.tsx components/chat/ScheduledForChat.tsx)
nice -n 10 venv/bin/python scripts/comment_budget.py --check
.claude/skills/public-sync/replay.sh --check
log="$(mktemp)"
nice -n 10 scripts/run-tests.sh > "$log" 2>&1
(cd app && nice -n 10 pnpm test:run)
# manual: after 02g, local Relay with PLATFORM_LIVE_CHECK=<aid>:schedule_mass_message:fan=<Proof fan id>,<aid>:cancel_scheduled_mass_message:fan=<Proof fan id>,<aid>:send_mass_message:fan=<Proof fan id>, on a list holding only the Proof fan:
# manual:   schedule +1 h then cancel (fan sees nothing, scheduled reads []); schedule +10 min and let it fire (one message);
# manual:   send once (one message, run ok, queue_id null). Each pass is recorded in that method's PR 2 (Lift).
```

## Depends on
- **02a — Primitives.**
  - the grant API (`live_check_targets`, `live_check`, `ListAudience`, `is_live_check_name`, `PLATFORM_LIVE_CHECK` `fan=` grammar), the `platform_live_check` marker and Capability counts;
  - the neutral markers (ADR-0068);
  - `send_refusal`;
  - the Stateful fake;
  - the Verdict table harness;
  - the Lift table and its drift test (route-only reasons and the trailing `:<digits>` strip).
- **02b.** `list_users_in` with its Complete read flag, and the priority_mass gates (04 item 6). Two preconditions 02b leaves to this phase (D28): the Fansly Shim has no `unread_chat_fan_ids`, which `audiences.resolve_mass_audience` calls for the unread audience; and the online-only audience read in `resolve_mass_audience` lets the Shim's `platform_lacks:subscribers:incomplete` refusal through as an error, not a skip. Both are reachable today only behind the mass-send refusals; this phase's verdict rows must prove each one refuses or is built before any Fansly mass send is lifted.
- **02e.** Blocked `unsend_mass_message`, which OFClient delegates to `cancel_scheduled`. Also the unsend lane and DELETE-route gate (501 for a cached broadcast id), `scheduled_messages` (string ids, `scheduledFor` → `scheduledDate`) and history.
- Linear PR order (D8): 02a-1 → 02a-2 → 02b → 02c → 02d → 02e → **02f** → 02h → 02g.

## Out of Scope
- **14 F.** The app path (grant-scoped Capability in the composer, the `schedules()` merge, string ids in Settings) is 02g's. Settings can't cancel a Fansly row until 02g's string ids land.
- **Lifting `edit_queued_message`.** Stays Blocked (I grade: cancel + re-create loses the message on failure).
- **Media, price and preview broadcasts, exclusion lists (30001), tier audiences and `groupFlags` variants.** No capture proves them (W grade covers text to one include list only).
- **A two-write claim budget for Cell mode.** It belongs to the agency-scale-out plan; refusing costs nothing now.
- **`mass_message_buyers`.** It needs a Proof purchase (06).
- **Temp-list emulation and audience snapshots.** The ticket forbids a new wire call. The membership-at-delivery assumption stands until it falls.
- **PR 2 Lifts.** They follow the owner's Live check, one per method (ADR-0070).
- **Slop.** No slop runs (owner rule; the proof bar says no slop).
- **Deploy.** It comes after 02h; no compose passthrough is added.

## Further Notes
ASSUMPTION: branch suffix names `:audience_lists`, `:recipients`, `:exclude_lists`, `:autofence`, `:filters`, `:media`, `:funnel`, `:extras`, `:contact_guard:<n>`, `:list_incomplete`, `:cell_mode`, `:save_for_later`, `:scheduled_date`; rung 5. Overturned by an owner rename (the Lift table moves with it).
ASSUMPTION: enforce-mode AUTOFENCE refuses rather than checking the member difference, and paused/unhealthy keeps AudienceHalt; rung 4. Overturned if the owner wants AUTOFENCE on Fansly; then it gets a Complete-read member check.
Cell-mode reason `:cell_mode` (coordinator D4; ticket 14 item 9's `:cell_budget` was agent-written, so not rung 2; the refusal itself stands).
ASSUMPTION: POST /group type 3 runs outside the claim Budget via a private `delivery=False`; rung 1 for idempotence (`RECIPES.md:1008`) + rung 5. Overturned if a capture shows /group alone notifies a fan; then the Budget gains a broadcast-shaped two-write allowance outside Cells, and Cell mode still refuses.
ASSUMPTION: `send_ops._capable` admits on `live_check_targets` presence and every Fansly caller of the three methods runs the exact `live_check` before `begin` (rung 4: `_capable` sees no audience; no grant still refuses). Overturned by a caller that reaches `begin` without the exact check; then `begin` takes the checked `ListAudience` and re-runs `live_check` itself.
ASSUMPTION: a scheduled Fansly run stays open like OnlyFans' and settles on cancel via `mark_queue_unsent`; fire-time settlement waits for 02e history; rung 3. Overturned if 02e history can't join a run without a queue id (ticket 14 Fog).
ASSUMPTION: `broadcast_branch_refusal` takes the runner's argument names, not the plan object, so the Shim can share it; rung 5. Overturned if the Shim can't import the Side-effect gate.
ASSUMPTION: the forced ledger outside Cells skips epoch, permit and hold, and `send_ops.install` runs at every boot; rungs 3 and 4. Overturned if install needs Cell-only state; then it installs lazily on the first forced claim.
ASSUMPTION: Fansly broadcasts run with `retry=False`, including on 429, because it is unknown whether a retried POST resends (Fog); rung 4. Overturned by a capture showing that a retry doesn't resend.
ASSUMPTION: the route's ledger anchor is X-Op-Id, else the composer key hash, and any `uncertain` mass row holds the Creator's next Fansly mass send (rung 3: `fan_held`, `send_ops.py:142-146`), because the composer clears its op id on edit (`massMessageReducer.ts:158-161`) and reload loses it. Overturned if the owner wants a per-anchor hold only.
ASSUMPTION: membership resolves at delivery, so a scheduled broadcast is re-read only at schedule time (ticket 14). Overturned if scheduled delivery uses a snapshot; then scheduling refuses until a snapshot exists.
ASSUMPTION: scheduled `groups[]` carries the recipient list (ticket 14). Overturned and failing closed as `:audience_unknown` otherwise.
ASSUMPTION: thresholds refuse as `:filters` (they filter fans, a list send can't apply them) and `require_recipients` applies to the Complete read's size; rung 5. Overturned if Fansly gains a per-fan broadcast target.
ASSUMPTION: Verdict table rows are judged with no grant (`gated:`), and the granted path is proven in test_fansly_mass_writes; rung 3 (the deployed default is off). Overturned if 12 wants a granted Verdict column.

## Review
Reviewer: codex (blind + draft), 2026-11-27
- P1 Alternatives (keep refusal / immediate only / Relay-queued schedule with re-auth at dispatch): **reject** — ticket 14 item 10 binds native `scheduledFor` behind a Live check.
- P1 Ledger gap (non-Cell install/epoch/anchor, composer clears op id, mint before replay): **accept** — `begin` before mint, Cell-free anchor, Creator-wide hold on any `uncertain` mass row (`send_ops.py:142-146`, `massMessageReducer.ts:158-161`, `send_mass_message.py:307-347`); Interfaces, runner step 7, route, case 6.
- P1 Refusal gaps (raw selectors, unread/recent-chat/thresholds/auto-unsend, every exclusion, AUTOFENCE pause, cold client): **accept** — branch check on raw input; runner `excl_set` already holds MASSdmEXCLUDE/pending (`send_mass_message.py:183-201`), route now uses the same full set; pause keeps AudienceHalt; cold-client cases 2-3.
- P1 Schedule and cancel (bad dates, scalar ack → row, run settle, bound cancel, no post fallback): **accept** — `:scheduled_date`, raw before/after id match, run follows OF scheduled precedent (`mass_queue_api.py:413-414`), cancel bound to own pending row + single 30000 list; D, E, stories 24/26.
- P1 Test seam (fake at `http.request`, replay sent + uncertain, both cancel controls): **accept** — Testing main seam, cases 6/8/11/12.
- P1 Falsifiers: **partial** — roster change after final GET: re-read moved to between /group and broadcast POST (residual ms race on an owner-only list is inherent); ambiguous group/list → fail closed; schedule-time vs delivery membership **reject**, ticket 14 item 4 ASSUMPTION binds (falls → snapshot list).
- P2 Blocker, Budget spent on /group (measured, `send_tripwire.py:25-28`, `fansly_client.py:231-235`): **accept** — /group posts with `delivery=False` outside the Budget (idempotent, `RECIPES.md:1008`); case 5 through the real Budget.
- P2 Blocker, 02a refuses Live-check markers in `refusal` / `_capable` (`phase-02a-mp2-primitives.md:61`, `send_ops.py:86-89`): **accept** — explicit gate paths; old Further Notes assumption removed.
- P2 Blocker, final roster read precedes /group; native schedule gap: **partial** — `_before_broadcast` re-read + test; schedule gap rejected per ticket 14 item 4.
- P2 Blocker, cancel reads before grant; filtered read-back hides status 3: **accept** — grant probe first (ticket 11 item 3 request rule), raw response + raw re-read, Creator/pending/group binding.
- P2 Major, fresh anchor after reload/edit; mint before replay: **accept** — as P1 Ledger gap.
- P2 Major, resolved plan erases recipients; thresholds as roster size; route auto-unsend: **accept** — raw-input check, thresholds → `:filters`, route `unsend_after_hours` → `platform_lacks:unsend_mass_message`.
- P2 Major, schedule read-back row selection, lookalike, bad dates, post-accept read failure: **accept** — D, case 10.
- P2 Major, Settings test mocks the hook; chat-chip caller lacks `type` (measured, `ScheduledTab.test.tsx:8-11`, `ScheduledForChat.tsx:92-97`): **accept** — optional `type`, real-hook test, both callers.
- P2 Major, Acceptance lacks one-alembic-head check (ticket 11 item 3): **accept** — 02b's `alembic heads` line added.
- P2 Minor, overlap count must be in the reason (ticket 14 item 4): **accept** — `:contact_guard:<n>`, drift test strips trailing digits.

Plan review (six hats + coordinator D1–D8), 2026-11-27:
- White [02a,02b,02c,02f,02g], four grant shapes — **accept** (D1). `live_check_grant` deleted; `live_check_targets` + `live_check` + `fan=` grammar cited; audience is `ListAudience`.
- Red [02a,02b,02c,02f], "if 02a lacks" ASSUMPTIONs — **accept**. Grant-probe and drift-strip ASSUMPTIONs deleted (02a owns both, D7).
- Red [02f], too big to review — **partial**. Stays one PR (one Shim lift and one file-rule slot under 11's rules); the four commits must each run green and are reviewed commit by commit. Splitting into more PRs rejected: A–C alone would merge a send path with no schedule/cancel parity rows to judge it against.
- Black [02f], /group outside the Budget vs `:cell_budget` — **accept** (D4). /group `delivery=False` outside Cells stays; Cell mode refuses broadcast writes per ticket 14 item 9 as `:cell_mode`, not a budget argument. Story 15, runner step 1, case 7, suffix list rewritten.
- Black [02f], `_capable` passes on presence alone — **partial**. Kept: `_capable` has no audience to check. The exact `live_check` runs at the caller, at `before_write` and at `_before_broadcast`; the ASSUMPTION now names the falsifier (a caller reaching `begin` unchecked) and the fallback (`begin` re-runs `live_check`).
- Green [02f,02g,02h,plan], pick one /group answer — **accept** (D4): outside the Budget, Cell mode refuses on its own reason.
- Blue [02b,02c,02d,02f,02g], cite 02a's names — **accept**. Interfaces, Contracts and Depends on cite 02a's grant API.
- D4 `confirm_live_broadcast` removal in the caller-auth commit — **accept**. Order step 2.
- D8 linear order — **accept**.
Counts: accept 7 · partial 2 · reject 0 · needs-human 0.
