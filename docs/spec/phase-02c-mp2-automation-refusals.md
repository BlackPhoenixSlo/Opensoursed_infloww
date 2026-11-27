# Phase 02c — Automation refusals

**Objective.** On a Fansly account, every automation and stats read that would act on a fact Fansly lacks stops before any read, claim, write, typing hold or send, records `skipped` (single-Box mode; Cell mode keeps its existing pre-claim hold) with a `platform_lacks:<lack>[:<branch>]` reason, and the same run on OnlyFans behaves exactly as it does today.

## Problem Statement
A Fansly agency turning on a lane built for OnlyFans gets one of three bad outcomes today. Some lanes run on a guess. Nudge treats `statusId == 1` as "online". The welcome lane reads "subscribed" when Fansly counts a follow. Lifecycle treats an empty roster as "nobody expired". Other lanes partly act and then fail: S4S claims a slot and writes an audit row before the media post fails. Typed replies show "typing…" and commit a typo before a send that is refused. Stats show a built-looking chart or zero referrals where the truth is "not available". The operator cannot tell "nothing to do" from "this Platform can't do it". The run log says `ok` or `error` when it should say "skipped, Fansly lacks X".

## Solution
Each affected lane has one refusal as its first step on a Platform that lacks the fact. The run then reads `skipped` with a reason that names what is missing, and nothing else happens: no requests, no state change, no typing, no follow-up job. Lanes whose fact a Live-check grant can prove (nudge presence) stay refused unless the owner grants that account, method and audience. Stats routes answer 501, or list Fansly under `unavailable`, instead of showing a made-up number. OnlyFans keeps every current behaviour. The Verdict table rows for these lanes go from `owner:NN` to their real verdict in the same PR, so the table and the code cannot drift.

## User Stories
1. As a Fansly operator, I want nudge_online to treat a fan as online only when `lastSeenAt` falls inside the house 5-minute window, so that a fan who has been away for days is never nudged as "online".
2. As a Fansly operator, I want nudge_online and nudge_online_fire to record `skipped`/`platform_lacks:nudge_online` unless my account holds a Live-check grant for that method and fan, so that an unproven presence signal never causes a send.
3. As the owner, I want every nudge_online path refused before it writes presence: the forced/test-fan path, and the scheduled scan before its warm-up seed and its last-seen refresh, so that a refused run leaves no last-seen row behind and an ungranted fan beside a granted one gets no row either.
4. As the owner, I want a queued nudge fire to re-check the grant before it trusts its queued state, and when refused to clear its pending latch only where the latch still holds this job's id, so that a grant revoked between scan and fire still stops the send and a newer job's latch is never cleared.
5. As a Fansly operator, I want promo_reactivate to record `skipped`/`platform_lacks:promotions` before it touches the recheck state, stands down or notes a wait, so that a queued recheck on Fansly changes nothing.
6. As a Fansly operator, I want media posts (s4s_post and auto_posts with media, previews, folders or a price) refused as `platform_lacks:create_post:media`, so that no upload, slot claim, audit row, media delete or follow-up happens for a post Fansly cannot make.
7. As an S4S partner, I want accepting a request refused with 501 when either poster is on a Platform that cannot post the partner's snapshotted media, before the request moves, so that I learn at once and no slot, job, transition or audit row is written.
7a. As an S4S partner, I want a legacy media slot already booked for a Fansly poster to show as failed with `platform_lacks:create_post:media` once its run refuses, so that it never reads "Will be posted shortly".
8. As the owner, I want s4s_post's refusal placed before its unconditional prune, so that a refused run does not prune.
9. As the owner, I want auto_posts' refusal placed above the dry-run return and before pool resolution and the send tripwire, so that a dry run on Fansly reports the refusal too.
10. As a Fansly operator, I want expiry_message, expired_message and resubscribe_message to record `platform_lacks:renewal_state`, `platform_lacks:lapse_detection` and `platform_lacks:return_detection` right after the disabled check, so that an empty Fansly roster is never read as "no one to message".
11. As the owner, I want the lifecycle refusal placed before the no-text check, the discount refusal, the dry-run return, forced ids, client creation, roster refresh, snapshot, lease and claim, and lifecycle follow-up payloads refused before the follow-up runs, so that the scheduled, forced and follow-up paths all have zero effect.
12. As a Fansly operator, I want birthday_message to keep running as it does today, so that the one lifecycle lane that does not depend on a missing fact keeps working.
13. As a Fansly operator, I want queueing a mass message with "expired over N days" to answer 501 before any claim or audience resolution, so that I never send to an audience Fansly cannot work out.
14. As a Fansly operator, I want customs_watch to record `platform_lacks:tip_ledger` before any read, enqueue, owed-flag change or webhook dispatch, and the inbound-tip webhook to enqueue no customs_watch job on a TIP_LEDGER Platform, so that tips never counted are never chased.
15. As a Fansly operator, I want purchase_followup to record `platform_lacks:purchase_linkage` after its own disabled, no-text and no-enabled-at checks but before reading purchases, claiming or folding, including when there are no candidates, so that it never thanks a fan for a purchase it cannot link.
16. As a Fansly operator, I want the notification count to come from the captured unacknowledged totals and to raise when the fetch fails, so that a failure never reads as "0 new".
17. As a Fansly operator, I want follow notifications (3003) to arrive as `followed` instead of `subscribed`, so that a free follow is never treated as a paid subscription.
18. As a Fansly operator, I want send_welcome's trigger to read `followed` (3003) plus 15016 on a free-follow Platform, chosen from the Platform registry, with the poll and the extractor changed in the same commit as the 3003 remap, so that the welcome goes to the people it is meant for and no commit loses follows.
19. As a client of the notifications route, I want `hasMore` to reflect the raw page and not the filtered one, so that paging never stops early.
20. As the owner, I want the Fansly revenue scan to write `fully_backfilled=False`, clearing rows stamped True before this Phase, so that the revenue screen does not claim a backfill that never happened.
21. As a Fansly operator, I want the transactions, payout requests and payout balances reads marked Blocked with honest reasons, so that the app no longer shows them as built.
22. As a Fansly operator, I want the subscribers chart to drop its `returns` series, the chart route to answer 501 on Fansly, and the screens bundle to return an item-level 501 for Fansly `newFans` before its warm `_LAST` and `_cached` entries are read, all with zero upstream requests, so that no invented or stale returns figure is shown.
23. As the owner, I want of_stats_daily to skip any registered non-OnlyFans Platform, proven with a registered third Platform, so that the daily stats job stays OnlyFans-only by registry and not by a Fansly key check.
24. As an agency manager, I want referral stats to list Fansly accounts under `unavailable` while mixed scopes keep OnlyFans rows, so that a Fansly-only view says "unavailable" and not "zero".
25. As a Fansly operator, I want every refusal for a reply (send refusal, the Backend's sendable check, the Platform gate, the Live check) checked for the whole burst before its first typing hold or typo throttle, so that a refused reply shows no "typing…", commits no typo, and never lands a text bubble ahead of a refused PPV bubble. Platform and Live-check refusals also run before welcome_chatter's attempt bump; a payload refusal found after shaping keeps that bump, by its own invariant.
27. As the owner, I want s4s_check to treat an empty or id-less post as `inconclusive` under both baselines, and to catch the account Backend's API error as well as the OnlyFans one, so that a Fansly read gap is never reported as tampering.
28. As a Fansly operator, I want apply_profiles to push nicknames and notes through my account's Backend client, and process_old_fans' Verdict row to show that push in its nested apply_profiles stats, so that a Fansly push neither goes through the OnlyFans client nor is silently dropped.
29. As an OnlyFans operator, I want apply_profiles to keep its current client, so that the default path does not change.
30. As a Fansly operator, I want send_welcome with the OF-welcome toggle on to record `skipped`/`platform_lacks:my_settings` before client creation, lease, claim, notification read, send, WelcomeSent write, follow-up job or group creation, with the job marked `done`, so that a setting Fansly cannot read never guesses "off".
31. As the owner, I want the trigger fixes in story 17–18 committed before the toggle refusal's trigger proof in story 30, so that the proof runs against the real trigger.
32. As an OnlyFans operator, I want every lane above to keep its present behaviour, shown by an OnlyFans control test wherever the code is shared, so that this Phase changes nothing for OnlyFans.
33. As the owner, I want each lane's Verdict table row and Lift table row changed in the same PR as its code, so that the table and the code cannot drift.
34. As the owner, I want this Phase's one PR safe in prod on its own, so that it deploys without waiting on 02d.
35. As the owner, I want the Cell-mode hold on nudge_online_fire and purchase_followup left as it is and proven to send nothing on Fansly, so that the single-Box refusal contract is not mistaken for a Cell-mode one.

## Implementation Decisions
- **Owns.** Automation lanes nudge_online, nudge_online_fire, promo_reactivate, s4s_post, auto_posts, lifecycle_messages, customs_watch, purchase_followup, s4s_check, apply_profiles, process_old_fans, send_welcome (this Phase owns every send_welcome edit), and the typing-hold call sites in autoreply, full_ai_live, reply_mass_funnel, send_welcome and welcome_chatter_for_info. The inbound-tip webhook (`webhook_dispatch.on_inbound_tip`). Relay routes: mass queue, S4S requests (accept), the S4S schedule read (`_display`), of_stats (referrals), the subscribers chart route in the server module, and the screens bundle reader. Shim: the `of_user` presence fields, `notifications_count`, the notification type map, the notifications `hasMore`, the unbuilt table entries for transactions, payout requests, payout balances and the earnings-chart reason, and the subscribers chart. fansly_revenue's scan marker. Registry: `create_post` gets blocked branches. Gate: one new branch-refusal entry point and `nudge_online` added to 02a's `LIVE_CHECK_LANES`. Lifecycle: the kind→Lack map `LIFECYCLE_LACKS` (02c owns it; 02d imports it). Rows in the Verdict table, the Lift table and the parity status doc for these lanes.
- **Interfaces.**
  - The Side-effect gate gets `branch_refusal(account, method, branch)`. It returns `platform_lacks:<method>:<branch>` when the account's Platform lists that branch in the method's `platform_blocked_branches`, and None otherwise.
  - `create_post` declares the `media` branch, which covers media files, a media folder, preview media and a price.
  - Lanes that refuse on a Lack call 02a's `platforms.lack_reason(lack)` when the Platform's `lacks` contains it; no second helper.
  - `lifecycle_messages.LIFECYCLE_LACKS: Mapping[str, Lack]` = `{expiry_message: RENEWAL_STATE, expired_message: LAPSE_DETECTION, resubscribe_message: RETURN_DETECTION}` (birthday_message absent). The sweep gate here and 02d's lifecycle config API both read it.
  - The Lack members TIP_LEDGER, PURCHASE_LINKAGE, RENEWAL_STATE, LAPSE_DETECTION and RETURN_DETECTION come from 02a. This Phase is their first user.
  - nudge_online and nudge_online_fire call 02a's `live_check(account, "nudge_online", frozenset({fan}))` at the caller, one fan per call, under a `<aid>:nudge_online:fan=<id>` grant.
  - `nudge_online` is a caller-side lane: 02c adds it to 02a's `LIVE_CHECK_LANES`, so `is_live_check_name` classifies it and `live_check` answers `platform_lacks:nudge_online` instead of falling through to `refusal_for_account`. No Shim attribute is added.
  - The scan path reads 02a's `live_check_targets(account_id, "nudge_online")` (presence probe, zero requests).
  - Typing senders call `send_refusal` and the Backend's `check_sendable` on every part of the burst before the first `hold_with_typing`, `apply_typo_throttle` or hop reservation. A refused burst sends nothing and the run reason is the refusal tag. `hold_with_typing` itself does not change.
  - The Shim's `notifications_count` now raises the Backend's API error instead of returning 0.
  - The notification type map gains `followed`.
- **Schema.** None. Every refusal writes the existing `AutomationRun.status` / `stats_json.reason` fields, and no migration is added.
- **Contracts.**
  - Reason strings, exactly: `platform_lacks:nudge_online`, `platform_lacks:promotions`, `platform_lacks:create_post:media`, `platform_lacks:renewal_state`, `platform_lacks:lapse_detection`, `platform_lacks:return_detection`, `platform_lacks:tip_ledger`, `platform_lacks:purchase_linkage`, `platform_lacks:my_settings`. Typing-sender refusals carry `send_refusal`'s own tags.
  - `run_decide.outcome` already maps any `platform_lacks:` reason to (`skipped`, `done`). Jobs therefore end terminal and are never retried.
  - HTTP 501 through `refuse_if_platform_lacks` comes from these routes:
    - mass queue with `expired_over_days` on a LAPSE_DETECTION Platform
    - the subscribers chart route
    - the screens bundle subscribers section
  - S4S accept answers 501 with the `platform_lacks:create_post:media` detail when either slot's poster lacks the branch for its partner's snapshotted media (`s4s_media.slot_media_ids`). The check runs before the request's status update, so nothing moves. Platform refusals answer 501 (`CONTEXT.md` Platform refusal); 409 stays for booking conflicts.
  - S4S schedule `_display`: a `scheduled` slot whose job is `done` and whose poster's Platform lists the `media` branch shows failed with reason `platform_lacks:create_post:media`. Read-side only; the slot row is not written.
  - Referrals adds Fansly ids to its existing `unavailable` list.
  - The notification type `followed` is new on the notifications route.
  - The Capability counts change by built −3, Blocked +3 and live_check +1 (`nudge_online` lane).
  - fansly_revenue's scan writes `fully_backfilled=False`. The Fansly account then sits in the supervisor's backfill bucket, which still routes to `backend.revenue_tick` regardless of mode (`transaction_ingest.py:1347-1364,1664-1683`); the stale comment at `fansly_revenue.py:110` goes.
- **Placement rule.** Each refusal is the first statement after the lane's own `disabled` check. Where the lane has no such check (customs_watch), it is the first statement of `run`. Nothing that reads, claims, leases, writes, logs an audit Action or prunes may come before it.
- **Exception: the nudge fire.** A refused nudge fire clears its pending latch the way every other skip branch does (`nudge_online_fire.py:90-118`), but only `WHERE pending_job_id = <this job>`. The Verdict row names this one `NudgeState` write as declared lane bookkeeping; every other delta stays zero.
- **Grant check before audience.** For nudge's scan path, an empty `live_check_targets` refuses before `_make_client` and `iter_online_subscribers`: zero requests. With targets, the audience read runs (behind 02b's complete-roster guard), `online_ids` is cut to fans passing `live_check` before `_account_warmed`'s seed and the refresh upsert (`nudge_online.py:465-504`), then the per-fan loop runs.
- **customs webhook.** `on_inbound_tip` checks the Lack before `watch_flags` and enqueues nothing on a TIP_LEDGER Platform (`webhook_dispatch.py:397-410`).
- **Cell mode.** The executor's `no_anchor` return for nudge_online_fire and purchase_followup (`automation_executor.py:119,538-540`) fires before claim on every Platform, so in Cell mode no run or reason is persisted and the job stays pending, with no send. This Phase does not change it.
- **welcome trigger.** It reads `platforms.for_account(account).free_follow`, the same way auto_follow does, never a Platform key comparison.
- **apply_profiles.** It takes its push client from `ax._make_client` (which is `backend.get_client`, as gen_info already does, `gen_info.py:475-480`) for any account whose Platform has a Backend module. Accounts without one keep `OFClient.from_account`, as ADR-0053 sets. process_old_fans already forwards `push_to_of` (`process_old_fans.py:147-148`) and is not edited.
- **s4s_check.** It imports the Platform's Backend `APIError` through the registry, as the server's send path already does.
- **File rules (from 11).**
  - Only one PR at a time edits the Platform registry, the server module or the Shim.
  - This Phase never edits fansly_ws (02d owns it).
  - Before each Shim edit, read the mirror thread log, and post the merged sha to the Fansly Manager Feature Coverage thread.
- **One PR, commit order** (ticket 11: eight specs, eight PRs; send_welcome changes stay in one PR).
  1. Shim notification fixes (06 D) together with send_welcome's free-follow poll and `_extract_new_subscribers` accepting `followed` (`send_welcome.py:118-132,609-632`; the Shim filters by type at `fansly_shim.py:1320-1322`).
  2. send_welcome toggle refusal (13 A).
  3. The rest, in any order.

## Testing Decisions
- **Seam 1, the main seam: `automation_executor.run_once` against the real Shim client over 02a's Stateful fake.**
  - It is driven through the KIND_VERDICTS harness with the marker-call recorder, in single-Box mode, from an enqueued due job that `run_once` claims (not a passed payload).
  - Every automation lane in this Phase gets one row asserting, for each path that applies (scheduled, forced, test-fan, follow-up payload, queued recheck/fire, dry run):
    - the stored `AutomationRun.status` and the exact `stats_json.reason`
    - the terminal job disposition
    - zero provider calls (or, under a grant with the audience refused, only membership GETs)
    - zero business-row deltas: snapshot, lease, claim, WelcomeSent, follow-up job, audit Action, presence, owed flags, typos, attempts and hop reservations
  - Each shared-code row has an OnlyFans control.
  - Specific rows: nudge scan with a granted fan beside an ungranted one (presence rows only for the granted fan) and with no grant (zero requests); nudge fire refused with a newer job's latch present (latch unchanged); Full AI text → refused PPV with typing explicitly enabled (zero sends, zero holds, zero typos); customs_watch via `on_inbound_tip` with an above-floor tip and an enabled rule (zero jobs); send_welcome toggle-off with a 3003 follow alone and a 15016 alone (one welcome each); process_old_fans with push (nested apply_profiles stats name the Backend push).
  - Cell mode: with `OI_CELL_MAP` set, a due nudge_online_fire and purchase_followup job on Fansly stays pending with zero provider calls.
- **Seam 2: relay HTTP routes through the app TestClient.**
  - The mass queue with `expired_over_days` answers 501 with no claim.
  - S4S accept refuses with 501 for each poster direction (Fansly `to` poster, Fansly `from` poster), with zero request-transition, slot, job and audit deltas; the schedule read shows a legacy refused slot as failed.
  - The subscribers chart answers 501 and the screens bundle's `newFans` item answers 501 with zero `_request` calls, with `_LAST` and `_cached` seeded warm first.
  - fansly_revenue: a seeded `fully_backfilled=True` row reads False after one scan, and the ingest admin API reports False.
  - Referrals lists Fansly as unavailable, and a mixed scope keeps OnlyFans rows.
  - The notifications route reports `followed` and the raw `hasMore`.
- **Seam 3: Shim shape tests and Capability counts in fansly/.**
  - `of_user` presence on dormant, recent and stale `_source` fixtures.
  - `notifications_count` from `/unack` totals, raising on a fetch error.
  - The type map entry for 3003.
  - The Blocked entries and the count change.
  - The subscribers chart without `returns`.
  - Lift table rows for the lanes touched.
- **Mutation check (one per harness, D6).** Move the nudge fire's `live_check` below its first effect and confirm the zero-effect test goes red. Take the backup with cp, never git checkout. The old send_welcome assertion that pinned "sends with the toggle on" changes in the same PR.
- **of_stats_daily.** A registered-double test skips a third registered Platform.
- **Prior art:**
  - service/tests: test_fansly_automation_gates (the `_Recorder` Shim subclass driven through run_once), test_lifecycle_messages, test_nudge_online, test_nudge_online_fire, test_promo_reactivate, test_s4s_post, test_s4s_requests, test_s4s_check, test_auto_posts, test_customs_watch, test_purchase_followup, test_send_welcome, test_apply_profiles, test_of_stats_daily, test_screens_api, test_fansly_revenue, test_full_ai_live_typing, test_autoreply, test_welcome_chatter_for_info, test_platform_capability
  - fansly/: test_shim_shapes, test_fansly_capability, test_har_replay
- **Test loop.** service/tests are plain scripts run file by file, never through pytest. The parallel runner and the full run-tests script run on the merge candidate. No slop.

## Acceptance
```sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
N="nice -n 10"
fail() { echo "FAIL: $*" >&2; exit 1; }
for t in test_platform_kind_verdicts test_fansly_automation_gates \
         test_lifecycle_messages test_nudge_online test_nudge_online_fire test_promo_reactivate \
         test_s4s_post test_s4s_requests test_s4s_check test_auto_posts test_customs_watch \
         test_purchase_followup test_send_welcome test_apply_profiles \
         test_of_stats_daily test_screens_api test_fansly_revenue test_full_ai_live_typing \
         test_autoreply test_welcome_chatter_for_info test_platform_capability; do
  $N venv/bin/python "service/tests/$t.py"
done
for t in test_shim_shapes test_fansly_capability test_lift_table; do
  $N venv/bin/python "fansly/$t.py"
done
if grep -n '"isOnline": account.get("statusId")' fansly/fansly_shim.py; then fail "statusId presence"; fi
if grep -n 'statusId") == 1' fansly/fansly_shim.py; then fail "statusId presence"; fi
grep -q 'platform_lacks:my_settings\|"my_settings"' service/automations/send_welcome.py || fail "welcome toggle refusal"
$N venv/bin/python - <<'EOF'
import ast, pathlib
tree = ast.parse(pathlib.Path("service/tests/test_platform_kind_verdicts.py").read_text())
node = next(n for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AnnAssign))
            and any(getattr(t, "id", None) == "KIND_VERDICTS"
                    for t in (n.targets if isinstance(n, ast.Assign) else [n.target])))
kv = ast.literal_eval(node.value)
lanes = {"nudge_online", "nudge_online_fire", "promo_reactivate", "s4s_post", "auto_posts",
         "expiry_message", "expired_message", "resubscribe_message", "birthday_message",
         "customs_watch", "purchase_followup", "s4s_check",
         "apply_profiles", "process_old_fans", "send_welcome"}
bad = [(p, k, b, v) for p, kinds in kv.items() for k, branches in kinds.items() if k in lanes
       for b, v in branches.items() if str(v).startswith("owner:")]
assert not bad, bad
EOF
$N venv/bin/python scripts/comment_budget.py --check
test "$(PYTHONPATH=. $N venv/bin/alembic -c service/db/migrations/alembic.ini heads | grep -c head)" = 1
test -d app/node_modules/vitest || fail "vitest not installed; run-tests.sh would skip the frontend"
$N scripts/run-tests.sh
# manual: owner grants PLATFORM_LIVE_CHECK=<owner aid>:nudge_online:fan=<Proof fan id> on a non-prod relay, confirms Fansly's own UI shows the Proof fan online while lastSeenAt is inside 5 minutes (a mismatch keeps the grant off), runs a nudge fire, confirms one DM arrives on the Proof fan and the run reads ok; without the grant it reads skipped/platform_lacks:nudge_online
# manual: after deploy, owner opens a Fansly account's automation log and confirms lifecycle/customs/purchase/welcome-toggle runs read skipped with the named reason
```

## Depends on
- **02a.** It provides:
  - the grant API: `live_check`, `live_check_targets`, `LIVE_CHECK_LANES`, `is_live_check_name`, `PLATFORM_LIVE_CHECK` (`fan=` grammar)
  - `platforms.lack_reason`
  - `send_refusal` and the Shim's validate-before-group
  - the neutral Platform markers, and an unknown key that refuses
  - the Lack members TIP_LEDGER, PURCHASE_LINKAGE, RENEWAL_STATE, LAPSE_DETECTION and RETURN_DETECTION
  - the KIND_VERDICTS harness with its marker-call recorder and its effect, no-op and refusal assertions
  - the Stateful fake
  - Capability counts
  - the Lift table and its drift test
  - the WATCH checks
- **02b.** It provides the list-backed reads that the list-backed lanes (story 13's audience lists, and the smart-list inputs used by the lifecycle controls) are tested against, and `iter_online_subscribers`' complete-roster refusal that the granted nudge scan relies on (`phase-02b-mp2-lists.md:56,73`; 02b owns that catch in nudge_online). Lanes without list reads do not wait for it.
- Linear PR order (D8): 02a-1 → 02a-2 → 02b → **02c** → 02d → 02e → 02f → 02h → 02g; ticket 11's file rule allows one open PR on `platforms`, the server module or the Shim at a time.

## Out of Scope
- **03 item 5, 05 B, 06 A, 07 B, 08 S1/S4, 13 B–E and 09 C:** Phase 02d. This includes the type-10 and typing work in fansly_ws and the app KPI capability gate.
- **03 slice 2 and the mass_premade re-key:** Phase 02f.
- **01 item 7 (auto_follow expired) and smart-list renew/resubscribed_at:** Phase 02b.
- **06 E, the server's Query description of real filter names and the parity docs prose:** Phase 02h.
- **The P2c empty-roster lifecycle fix, the purchase_followup trigger build and the earnings stats read:** each needs a Proof purchase or a capture that does not exist yet. Building them now would be YAGNI until the matching Lack is lifted.
- **Lifting any Lack (TIP_LEDGER and PURCHASE_LINKAGE by P1/P3, the lifecycle Lacks by P2b–P2d):** owner-only Proof purchases and Live checks. These never block a merge.
- **Banking set {2007} reads:** not touched by any lane here.

## Further Notes
- **Observation:** S4S slots are created in the S4S requests booking route (`s4s_requests_api._book`, called from `_transition` after the status update), not in the schedule API the ticket cited. The creation-time refusal sits in `_transition` before that update (rung 1).
- **Observation:** `run_decide.outcome` already turns a `platform_lacks:` plugin reason into a terminal skip, so no executor change is needed (rung 1).

ASSUMPTION: a refused nudge fire clears its latch only for its own job id, as declared bookkeeping (rung 3 skip-branch precedent + rung 4). Overturned if the owner wants a refused latch left set until a lift.
ASSUMPTION (Cell mode): the existing pre-claim `no_anchor` hold stays the Cell-mode verdict for nudge_online_fire and purchase_followup (rung 4: no executor change). Overturned if the owner wants Cell-mode jobs made terminal with the Platform reason.
ASSUMPTION: a payload refusal found after welcome_chatter's shaping keeps the attempt bump, per its comment at `welcome_chatter_for_info.py:1440` (rung 3). Overturned if the owner wants refused payloads not counted.
ASSUMPTION: a refused legacy S4S slot is shown failed from read-side facts (job `done` + poster Platform branch) without writing the slot (rung 4). Overturned if the Verdict table requires the slot row cancelled.
ASSUMPTION: typing-sender refusals reuse send_refusal's and check_sendable's own tags; no new reason vocabulary (rung 5). Overturned by a Verdict row naming a specific string.
ASSUMPTION: all of 06 D lands in this Phase because the plan lists it nowhere else (rung 5). Overturned if 02d or 02h claims a part.
ASSUMPTION: apply_profiles keeps `OFClient.from_account` for OnlyFans per ADR-0053 (rung 3). Overturned by an ADR moving OnlyFans to backend.get_client.
Observation: `_decide_mode` does read `fully_backfilled` for Fansly accounts and puts an unstamped one in the backfill bucket (`transaction_ingest.py:1664-1683`), but `run_one_tick` routes any Backend account to `backend.revenue_tick` before mode matters (`:1347-1364`), so writing False changes the bucket and the display, not the fetch (rung 1).
ASSUMPTION: the welcome trigger keys on the registry's free_follow attribute (rung 3, auto_follow precedent). Overturned if a second free-follow Platform needs different types.
ASSUMPTION: after the 07 A Blocked entries, the app KPI may show a stale value until 02d's 07 B gate; safe in prod because the read now refuses rather than invents (rung 4). Overturned if 02d lands first.
ASSUMPTION: 02b is only needed by list-backed lanes' tests; other lanes merge without it (rung 2 says "02b for list-backed lanes"; which lanes count is rung 5). Overturned if the 02b spec names more lanes.

## Review
Reviewer: codex (blind + draft), 2026-11-27

- B1 Cell mode first blocker — **partial.** Measured: `no_anchor` returns before claim/run for both kinds in Cell mode (`automation_executor.py:119,538-540`), on every Platform, so no send can happen. Contract scoped to single-Box mode; Cell hold kept and proven (story 35, Cell-mode test). Making Cell jobs terminal would be an executor change outside this Phase (ASSUMPTION, Cell mode).
- B2 Presence: authorize before sweep writes; UI/timestamp mismatch — **accept.** Scan warms and refreshes presence before the per-fan loop (`nudge_online.py:480-504`). Grant-target check before the client, `online_ids` cut before both writes (story 3, Grant check before audience); manual Live check now compares Fansly's UI with `lastSeenAt`.
- B3 S4S both posters, legacy display — **accept.** `_book` creates both directions (`s4s_requests_api.py:319-331`); `_display` shows `scheduled` as Will post (`s4s_schedule_api.py:90-106`). Stories 7/7a, both-direction tests, read-side failed display.
- B4 Full AI partial send — **accept.** Text can land before a later bubble refuses (`full_ai_live.py:445-535`). Whole-burst preflight before the first hold (story 25, Interfaces).
- B5 Profile push and welcome — **partial.** `_make_client` reused for Backend accounts (equals `backend.get_client`); OnlyFans keeps `OFClient.from_account` per ADR-0053. process_old_fans already forwards `push_to_of` (`process_old_fans.py:147-148`), so no edit, only a nested-stats Verdict row. followed + poll + extractor land in one commit (accepted).
- B6 Proof seam — **partial.** Accepted: claimed due job through `run_once`, warm bundle cache, exact deltas. Gate-removed mutation extended to one lane per effect family, not every lane (rung 5).
- D1 Cell mode bypasses both refusals — **partial.** Same as B1.
- D2 Nudge's 02a dependency is false — **accept.** 02a's `live_check(account_id, method, audience)` has no grant-only form and needs exactly one target (`phase-02a-mp2-primitives.md:59`, story 2); `nudge_online` is not a Shim attribute, so the fall-through gives "nudge_online is not on this platform" (`platforms.py:54-56`, `side_effect_gate.py:11-19`). Added the `nudge_online` Shim marker, `live_check_targets`, per-fan calls, granted+ungranted test, 02b roster guard in Depends on. Name `nudge_online` kept (binding ticket 03 answer).
- D3 Latch clear writes business state — **partial.** Measured: `_clear_pending` has no job-id predicate (`nudge_online_fire.py:26-33`). Every skip branch clears it (`:90-118`) and a stuck latch would block the fan after a lift, so the clear stays, scoped to this job id and declared as the one bookkeeping write (story 4).
- D4 Refuse-before-typing half reply; typo/attempt writes — **partial.** Burst preflight, top-level reason, typo throttle (`autoreply.py:678-682`) accepted. welcome_chatter's attempt bump stays for payload refusals per its own invariant (`welcome_chatter_for_info.py:1440-1441`); Platform/Live-check refusals precede it.
- D5 Welcome dark between merges — **accept.** 02c is one PR (ticket 11 Answer 1); the Shim filters by type (`fansly_shim.py:1320-1322`) and the extractor drops non-`subscrib` types (`send_welcome.py:127-128`). PR order became commit order with 06 D + poll + extractor together; 3003-alone and 15016-alone toggle-off tests.
- D6 S4S coverage, legacy display, 409 vs 501 — **accept.** Glossary: a Platform refusal route answers 501 (`CONTEXT.md` Platform refusal). 409 dropped; refusal before the status update in `_transition` (`s4s_requests_api.py:351-368`).
- D7 Customs webhook enqueue — **accept.** `on_inbound_tip` enqueues on its own (`webhook_dispatch.py:397-410`). Gate there, owned, tested.
- D8 Cold stats miss stale success; existing backfill flag — **accept.** `_LAST` answers before the route (`screens_api.py:111-116`); stamp removal leaves old True rows (`fansly_revenue.py:117`, `tx_ingest_admin_api.py:112`). Item-level 501 before both caches; scan writes False; seeded-True test. Old display-only ASSUMPTION replaced by an observation.
- D9 Acceptance ignores failed guards — **accept.** `! cmd` never trips `set -e`. Explicit `fail`s, KIND_VERDICTS check scoped to 02c lanes by AST (send_followup stays 02d's), Fansly tests run as plain scripts, vitest presence required.

Counts: accept 9 · partial 6 · reject 0 · needs-human 0.

Plan review (six hats + coordinator D1–D8), 2026-11-27:
- White · four grant shapes; `nudge_online` stand-in Shim attribute vs `LIVE_CHECK_LANES` — **accept**: the attribute is dropped; `nudge_online` joins 02a's `LIVE_CHECK_LANES`, presence via 02a's `live_check_targets`, grant `fan=` (D1); 02c's own `live_check_targets` definition removed.
- White · duplicate Lack helper; "if 02c exposes none" — **accept**: lanes call 02a's `platforms.lack_reason`; 02c owns `LIFECYCLE_LACKS` and 02d imports it (D7).
- Red · "if 02a lacks" ASSUMPTIONs — **accept**: the three ASSUMPTIONs (grant reader, marked attribute, Lack helper) deleted; Depends on cites 02a's names.
- Green · one grant shape, consumed here — **accept**: as White.
- Blue · cite 02a's names, own the kind→Lack map — **accept**: as above.
- Coordinator D6 · one mutation per harness — **accept**: five effect-family mutations cut to the nudge fire gate.
- Real handles in the manual Live check — **accept**: replaced by `<owner aid>` / `<Proof fan id>`.
Counts (plan review): accept 7 · partial 0 · reject 0 · needs-human 0.
