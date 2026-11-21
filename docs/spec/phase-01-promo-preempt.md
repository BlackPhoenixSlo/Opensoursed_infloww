# Phase 01 — Pre-emptive re-create for Keep promos running

**Objective.** A Kept promo is Re-created while still live, at a Trusted count of ceil(0.9 × Claim cap) (cap ≥ 10) or shortly before its OF end time (cap ≥ 10), so the profile never shows a gap. Every promo create goes through one Create reservation, Create budget, Create back-off, Zero-claim breaker and Host fence, and OF read counts do not rise above PR #850's. Plan: `goal_promo_preempt.txt` (every line binds). ADRs: 0039, 0040, 0041.

**Slices.** One Phase, two slices, both specced here; every story, schema item, test and acceptance line is tagged **A** or **B**; tickets order A before B.
- **A — safeguards on the After-end path.** Deployable alone; makes merged PR #850 safe to deploy (plan line 1: "ships before any deploy").
- **B — Pre-emption** behind `PROMO_PREEMPT_ENABLED` (off) and the second tick. Needs A merged.

## Owner ruling 2026-11-21 (binding; overrides every line below that disagrees)
**Keep running is indefinite by default.** A Free trial's Re-create limit is optional: none (form default **No limit**) = re-created until unticked; 1–10 when the operator picks one (counts down, at 0 → off, `limit_reached`). Only the unlimited-claims trial (cap 0) stays refused (`trial_unlimited`: create/PATCH 422, `reserve()`, run turns it off `limit_needed`). `recreate_limit_required` is gone. Migration 0129 (+ init_db, marker `20261121_keep_running_rules_heal`) gives every account with a Kept campaign one enabled live `promo_reactivate` rule (Kept campaigns ticked before #850 had none, or a disabled / dry-run one).

## Owner rulings 2026-11-19 (binding; they override every line below that disagrees)
Given by the owner after reading the run report ("I don't want to do anything … flip it enabled from the start … check in the 4 hour checker").
1. **No human steps.** The agent builds, sets `PROMO_CREATE_HOST_ID` on each live box at deploy, runs the restamp for existing Kept campaigns, and deploys. MEASURE a–d are no longer gates; the fail-closed branches in the MEASURE table stay as designed.
2. **Pre-emption on from the start.** `PROMO_PREEMPT_ENABLED` defaults **on** (it stays a runtime switch: the kill switch for Fill + Timed). The second tick still defaults ticked.
3. **A price change is fine.** No price stamp, no price hold, no price read, no cache peek: `sub_price_cents`, `peek_price_cents`, `price_changed`, `price_unchecked`, `price_unread`, MEASURE e and the price rows of the decide table are **cut**. A percent promo is re-made at the same percent on whatever the price now is. Must-not 11 keeps one answer: a free page makes OF refuse the create ("Access denied") → Keep running off, warning `price_free`, no retry (`case_mn11_free_page_no_create`, now in the budget/back-off/turn-off ticket). Tick is not refused on price.
   ASSUMPTION: this is the reading of the owner's "if the promo is live, the price changes … this works, okay" (rung 2, ambiguous wording). Overturned if the owner wanted the cached-price hold kept.
4. **The 4 h sweep watches it instead of a measurement.** Two `WATCH_CHECKS` ship in Slice A: `promo_keep_fenced` (as specified) and `promo_keep_creates` — alert on any reservation `unknown`/`lost`, any campaign Inflowwww turned off (`keep_warning` set) in the window, a second live promo beside the Kept promo, a Creator at its Create budget, or more automatic creates in 24 h than the budget allows; watch (not alert) line with the count of automatic creates by source. The agent appends both WATCH.md lines after deploy.

## Problem Statement
PR #850 (7df39f6aa) stands down while any promo is live (`promo_reactivate.py:226`, `promo_already_live`). A filled cap therefore leaves no offer until the next look (about 2 min, longer while OF lags). Its create path has these faults (rung 1, file reads):
- A failed create records nothing (`promo_reactivate.py:305`, `except Exception: errors += 1; continue`). No budget and no back-off: the only spacing is the 2 min Cooldown. The catch also hides a dead session from `run_once`'s `mark_session_dead` path.
- An unparsed create response returns the whole dict (`of_promos.py:171`, `return res`). The id may be wrong or missing, and the campaign keeps the old id. A 2xx with a bad JSON body raises inside `request_json` (`of_client.py:921-929`) after OF has acted.
- The new id is written only after the POST returns. A crash in between causes a duplicate on the next Poke. A POST can wait up to 150 s for a signed slot before it is sent (`of_client.py:447`, `SIGNED_WAIT_S = 30 × 5`), and `_proxy_retry` re-sends on a connection error (`of_client.py:834-880`).
- `_recheck_pending` then `_queue_recheck` is check-then-insert (`promo_reactivate.py:94-130`). Two runs can each queue one.
- Since #850, `plan_rule` keeps every under-floor Poke of any Interval kind (`dispatch_plan.py:332`). `send_welcome` and `promo_reactivate` can then run every minute on a busy Creator.
- `_arm` unticks the other campaigns silently (`promotions_api.py:269-282`, log only).
- The default Create promotion form is a Free-trial promo with Keep running ticked: `PROMOTION_DEFAULTS.kind = "trial"` (`ofMirrorOffers.ts:74`) and `INITIAL_CREATE.keepRunning = true` (`createPromotionForm.ts:23`).
- A third create path, the raw proxy `POST /api/of/v2/promotions` (`server.py:5558`, used by the OF mirror's Start campaign, `ofMirrorWrites.ts:90`), bypasses every guard. The raw finish/delete routes (`server.py:5569-5576`) end a Kept promo without unticking it, so After-end re-creates what the operator stopped (Growth's own finish unticks first, client-side: `useGrowth.ts:518-527`).
- `expires_at` mixes OF `finishedAt` with the guessed end created + finish days (`of_promos.py:124`).
- `normalise_of_promo` coerces a missing `claimsCount` to 0 and calls `claims ≥ cap` finished whatever OF's flags say (`of_promos.py:96-119`), so a wrong high count reaches After-end with no trust check.
- `of_pacing.retry_after` ignores the `Retry-After` header (`of_pacing.py:172-175`); `asked_wait(header, allow)` honours it (`of_pacing.py:139-149`).
- The Keep-running card lists only ticked campaigns (`PromoReactivateCard.tsx:19`), so a campaign Inflowwww turned off disappears with its reason.
- `auto_reactivate` predates #850 (`git grep -n auto_reactivate 7df39f6aa^ -- service/db/models.py`, codex, measured), so deployed Kept campaigns may exist (count: needs-human, plan-review).

## Solution
- **B · Pre-emption.** `promo_reactivate` may Re-create while the Kept promo is live, cap ≥ 10 only: Fill at a Trusted count of ceil(0.9 × cap), Timed `TIMED_LEAD_S` before the OF end time. Both need the campaign's second tick, Re-create at 90% filled (`preempt`, default on), and the server switch `PROMO_PREEMPT_ENABLED` (default off until MEASURE a + d pass). After-end re-create stays as the fallback. Cost (inferred, arithmetic): Fill hands out 0.9 × cap per promo, so about 11 % more creates (POSTs) for the same Claims.
- **A · One create gate.** A new module, `promo_create_guard`, owns Create reservation, reconcile, settle, Create budget, Create back-off and Zero-claim breaker input. All three create paths call it. The pure decision lives in a new module, `promo_keep_decide`: inputs in, `Wait | AfterEnd | TurnOff` out in A, `Fill | Timed` added in B; table-tested like `dispatch_plan`.
- **A · Keep state.** A new per-Creator row, `promo_keep_state`, holds the claim memo and the Re-check slot, so a restart or a second worker sees the same history.
- **A · Host fence.** The env var `PROMO_CREATE_HOST_ID`, one value per box, is compared with `promo_campaigns.keep_host_id`, stamped when Keep running is ticked.
- **A · Price from cache.** The price check uses only `account_page`'s cached price (≤ 6 h), never a new OF read (plan GOAL: request counts as now). A mismatch holds and warns.
- **A · Repoke opt-in** per kind: `send_welcome` goes back to pre-#850 spent Pokes; `promo_reactivate` and `purchase_followup` keep #850's. **B · Toast gate:** `event_transcoder` Pokes `promo_reactivate` only when the claim estimate could have reached the threshold.
- **A · UI.** Free-trial Re-create limit, Takeover warning, card with every stop reason (also on a campaign Inflowwww turned off), owner notices on every automatic create and stop. **B** adds the second tick and the waiting line.

## User Stories
1. **B** As an Employee, I want a Kept promo at 90 % of its Claim cap Re-created while it is still live, so that the profile has no gap.
2. **B** As an Employee, I want a Kept promo with an OF end time Re-created shortly before that time, so that the offer has no gap.
3. **B** As an Employee, I want a second tick, Re-create at 90% filled, under Keep running and ticked by default, readable and tappable on phone portrait, so that Pre-emption is on unless I opt out.
4. **B** As an Employee, I want the second tick disabled with a hint when the Claim cap is under 10 or unlimited, so that I do not expect a Pre-emption that never happens.
5. **A** As an Employee, I want After-end re-create to keep working when Pre-emption is off, waits or fails, so that #850's behaviour stays the floor.
6. **A** As an Employee, I want Inflowwww to never replace a promo whose id is not the Kept campaign's current `of_promo_id`, so that my hand-made or other promos are never ended.
7. **B** As an Employee, I want Fill pre-emption to act only on a Trusted count, so that a stale or lagging Claims number never ends a promo with room left.
8. **B** As an Employee, I want Timed pre-emption to act only on OF's own `finishedAt`, read twice and agreeing, with the Relay clock checked against OF's, so that a guessed end or clock skew never ends a promo early.
9. **A** As an Employee, I want a create whose outcome cannot be found on OF to stop Keep running at once, and creates OF never lists live to stop it after 3 in a row, so that #850's ~690/day loop cannot recur.
10. **A** As an Employee, I want every failed create recorded and followed by a Create back-off that honours Retry-After in full, so that a 429 or a proxy 403 never becomes a retry storm.
11. **A** As an Employee, I want Keep running turned off with a warning on a captcha, a free-page refusal, a non-403/429 4xx or a second 403/429 in a row, and a dead session flagged like any other run, so that the account is not hammered and a single proxy refusal does not stop it.
12. **B** As an Employee, I want a Pre-emption only when the budget still holds a recovery create, and a failed one to warn "no promo may be live" at once and fall back to After-end re-create after the back-off, so that a gap is short and visible.
13. **A** As an Employee, I want a create whose id cannot be parsed held as unknown, never released by a missing row, so that the campaign never re-creates from the old id.
14. **A** As an Employee, I want a Relay crash or a slow send between reservation and DB write to end in adopting the promo OF made, or Keep running off, never a duplicate.
15. **A** As the owner, I want a copied DB, a second Relay or a failover box to never make automatic promo creates until I re-stamp there, so that test, shadow and demo stacks are inert on OF.
16. **A** As the owner, I want to clear `PROMO_CREATE_HOST_ID` on a box to stop all automatic creates there, so that I have a kill switch that a DB copy cannot undo.
17. **A** As an Employee, I want Keep running unticked by default on a Free-trial promo, refused on an unlimited one, and with an optional Re-create limit (1–10; default No limit = indefinite, owner 2026-11-21) when I tick it on create or edit, so that a burst cannot hand out unlimited free subs while a capped trial keeps running.
18. **A** As the owner, I want a Create budget of 3 per rolling hour and 8 per rolling day per Creator for automatic creates, failures and unknowns included, so that no bug can make more.
19. **A** As an Employee, I want Inflowwww to re-read Keep running, the second tick, the Kept promo id and the rule just before it POSTs, and to drop the create if any promo create was reserved after its decision read, so that a stop, untick, Takeover or promo I made a moment ago wins.
20. **A** As an Employee, I want Keep running held with a warning when the Creator's cached subscription price differs from the one stamped when I ticked it, so that a promo is never re-made on terms I did not set.
21. **A** As an Employee, I want Create promotion to name the campaign that will lose Keep running before I submit, refuse if that changed meanwhile, and confirm it after, so that a Takeover is never silent.
22. **A** As the owner, I want a notice on every automatic create and every automatic stop or hold of Keep running, so that I can see what Inflowwww did on OF.
23. **A** As an Employee, I want my manual Create promotion (both surfaces) refused with the reason while a create is in flight, and a one-click way to clear an unresolved one, so that the two never race and I am never blocked for good.
24. **A** As an Employee, I want my manual creates neither refused by nor counted in the Create budget, so that automation never blocks me and my tests never starve After-end.
25. **A** As the owner, I want at most one pending Re-check per Creator, even under racing runs or a Takeover, and a bounded chain, so that jobs never stack.
26. **A** As the owner, I want `send_welcome` to stop running every minute on deferred Pokes, so that busy Creators stay quiet.
27. **A** As the owner, I want OF read counts for the same toast script no higher than PR #850's, with no added request of any kind, so that pacing risk does not rise.
28. **B** As the owner, I want Pre-emption held off by a server switch until MEASURE a and d pass on the owner test account, so that an inferred OF behaviour is never acted on live.
29. **A** As the owner, I want each MEASURE step as a short procedure with a pass condition that I run on the owner test account after local proof, so that no agent touches live OF.
30. **A** As an Employee on a phone in portrait, I want the limit field, the Takeover line and the warnings readable and tappable without sideways scroll, so that Keep running works on mobile.
31. **A** As an Employee, I want the Keep-running card to show why Keep running is waiting, held or off (fence, budget, back-off, breaker, price, unknown create, limit, re-tick), and who can fix it, also for a campaign Inflowwww turned off, so that I know what to do.
32. **A** As the AI assistant, I want `assistant_manual.md` to describe Keep running's stop reasons and the Free-trial limit (B adds the second tick), so that my answers match the product.
33. **A** As the owner, I want local proof (guarded stack with the supervisor running, fake OF, temp DB, loopback) with screenshots of the new controls on desktop and phone and of each warning, so that the change is shown on the real path before any live test.
34. **A** As the owner, I want the spec re-reviewed by devils-advocate and codex before build, so that a second lens checks it.
35. **A** As an Employee, I want stopping or deleting a Kept promo from the OF mirror to untick Keep running, so that Inflowwww does not re-create what I stopped.
36. **B** As the owner, I want a subscribe-toast burst on a busy Creator to make no `promo_reactivate` job unless the claim estimate could be at the threshold, so that reads drop below #850's.
37. **B** As an Employee, I want the card to say "Waiting: will re-create after it ends" (and why) whenever Pre-emption cannot act, and "clock" when skew blocks Timed, so that "Re-creates at 90% filled" never promises what will not happen.
38. **A** As the owner, I want a notice when a Relay boots with `PROMO_CREATE_HOST_ID` unset or mismatched while Kept campaigns exist, and a post-deploy watch check for fenced Kept campaigns, so that a deploy that silently stops re-creates is caught.

## Implementation Decisions

### Threshold, Trusted count, zero gap (B unless tagged)
- **Threshold = ceil(0.9 × cap)** in integers: `(9*cap + 9) // 10`. Cap 10→9, 11→10, 50→45, 100→90. Cap < 10, and cap 0 (unlimited), never pre-empt, Fill or Timed (plan fixed decision; ADR-0039).
  ASSUMPTION: cap 0 counts as "under 10" (rung 4: fewer Pre-emptions). Overturned if the owner wants Timed on unlimited promos.
- **A · Raw count.** `normalise_of_promo` gains `claims_present`; a missing count is never trusted.
- **Trusted count**, all required:
  1. The current read's Live promo id == `of_promo_id`, and no other promo is live.
  2. Claims present, ≥ threshold and < cap.
  3. The first read of this id (`promo_keep_state.first_claims`) saw a present count of exactly 0 (plan: "new promo observed at 0").
  4. Claims never went down across reads of this id.
  5. The decision read is ≤ 90 s old at the pre-POST check.
  6. The Fill/Timed would leave ≥ 1 automatic create in both budget windows (the recovery slot, #4).
  7. The cached price is known and equals the stamp (a cold cache holds Pre-emption only, see Price row).

  Any miss → `Wait(reason)`, stored in `promo_keep_state.wait_reason` for the card's waiting line; After-end covers it.
- **A · After-end on an inferred cap.** When OF's flags still say live (`isFinished` false, `canClaim` not false) and only `claims ≥ cap` makes it finished, After-end needs rules 1 (except "live"), 3 and 4; else `Wait` until OF flips a flag or the Backstop. A promo OF itself ended needs none.
- **A · Claim memo**, per Creator in `promo_keep_state`: kept id, first Claims, last Claims, seen-below-threshold, last `finishedAt`, read time. Toasts since the read stay in-process (only the B gate uses them). It survives restart; one Relay worker per DB (`docker-compose.yml:67-71`) still holds.
- **Zero gap, as measured with the fake OF.** The fake's timeline holds a live interval per promo and keeps feeding claims past the cap. Pass when the union of live intervals has no hole between the old promo's create and 30 s after the new one, and the POST happened while the old Claims were < cap. In fake mode (a)=yes, the fake ends the old promo at the POST; a missing or late Pre-emption lets the old promo fill, so the hole is real (DA 11).
- **Zero gap is conditional** (inferred): it holds when the claims after the threshold arrive slower than one decision cycle (Poke floor 60 s + read + send ≤ 150 s). A burst past the cap inside one cycle, a promo that fills with the WS down before the Backstop, or a reset memo falls back to After-end. The plan forbids the polling that would close it.

### Safeguards
| safeguard | exact design | storage | defaults |
|---|---|---|---|
| **A** Create reservation | States `pending → sending → created \| failed \| unknown`, `unknown → created \| lost \| cleared`. `reserve()` re-reads the campaign and inserts `pending` in one transaction; unique-index `IntegrityError` → refuse. Automatic sources also refuse (`newer_create`) when any reservation row of the Creator has `created_at > decision_read_at` (DA 2), and on discount 100 with `recreates_left` NULL or cap 0 (`trial_unlimited`, DA 6). Right before `client.create_promo`, in the sending thread, `UPDATE … SET state='sending' WHERE id=:id AND state='pending'` plus the pre-POST re-read; rowcount 0 → no POST. Callers: `promo_reactivate`, `POST /admin/promotions`, raw `POST /api/of/v2/promotions` (made async). | new table `promo_create_reservations`; partial unique `uq_promo_create_open(account_id) WHERE state IN ('pending','sending','unknown')` (precedent `models.py:209-215`) | — |
| **A** Settle | One transaction: CAS on `state IN ('pending','sending','unknown')`, plus the campaign repoint, `link_metrics._meta_row` of the old id, `reactivate_count`, `recreates_left`, and the notice row. A manual row carries name, discount and Keep-running intent in `terms_json`, so adoption creates the mirror row. rowcount 0 → do nothing (already settled). | same row | — |
| **A** Outcome on send | 2xx + parsed id → `created`. 2xx with no id, bad JSON, 5xx, timeout, connection error after send → `unknown`. 4xx → `failed`. Not sent (slot busy, retired, CAS lost) → `failed` with `error_class=not_sent`. | `error_class` | — |
| **A** Reconcile | Every OF list read first settles open rows: `promo_reactivate`'s, Growth's `GET /admin/promotions` (`promotions_api.py:88`), and the manual 409 path (DA 1). `pending` rows older than `SETTLE_GRACE_S` and every `sending`/`unknown` row are matched against page 1 (newest-first, 100 per page: a promo made after the reservation is on it, `promo_reactivate.py:219-220`, `of_promos.py:189`). Adopt only a **unique** candidate: id not in `pre_ids_json` (ids seen in the decision read), `created_at − 5 s ≤ createdAt ≤ settle-time`, cap equal with OF's null read as 0 (`promotions_api.py:186-190`), message and audience equal, `subscribeDays` compared (as sent, after `create_promotion`'s clamp) only for discount 100 (OF stores 0 otherwise, `promotions_api.py:217-224`); `finishDays` is never matched (not on read, `of_promos.py:15-16`). Zero or several candidates → stay open. A `pending` past grace whose sender is gone → `failed` (`not_sent`): `sending` is the only state that may have reached OF. | `terms_json`, `pre_ids_json`, `reconcile_reads` | `SETTLE_GRACE_S=600` |
| **A** Unknown → lost | A `sending`/`unknown` row with no candidate after `UNKNOWN_OFF_S` → `lost`, Keep running off, warning `create_unknown`, notice. A negative read never settles it `failed`. | same row | `UNKNOWN_OFF_S=900` |
| **A** Manual recovery | A manual create meeting an open row reconciles inline (one page-1 read, operator-initiated). Still open → 409 `{reason:"create_in_flight"}` while ≤ grace, else 409 `{reason:"create_unresolved", terms}`. The dialog then offers "It did not go through — create anyway"; the resend carries `resolve_open: <row id>`, which settles it `cleared` (the operator's reconcile) and proceeds. | same row | — |
| **A** Create budget | Rolling counts of **automatic** rows (any state) for the Creator; manual rows are neither counted nor refused (DA 4). Shoutout gets no exception. | derived; `ix_promo_create_account_time(account_id, created_at)` | 3 / 60 min, 8 / 24 h |
| **A** Create back-off | After a `failed`/`unknown`/`lost` automatic row: `not_before = now + max(asked_wait(header, allow_s(body)), min(120 s × 2^(k−1), 6 h))`, k = consecutive automatic failures. Retry-After is never capped. The raw route reads status/header inside `_proxy` (outside it the header is gone, `of_pacing.py:163-165`). | `not_before`, `error_class`, `retry_after_s` | 120 s base, 6 h cap on the doubling only |
| **A** Turn-off classes | Off (`auto_reactivate=false`, `keep_warning=<class>`, notice): captcha (body contains "captcha", guess); `OFDeactivatedError`; "Access denied" (free page, `api_errors.py:14-17`) → `price_free`; a 4xx other than 403/429; the second 403 or 429 in a row. A first 403 or 429 → `failed` + back-off only (DA 3: provider-side DC 403s, owner memory). `account_health.is_session_dead_error` → `failed` + `mark_session_dead` (the run_once precedent, `account_health.py:12-26`); Keep running stays on, `run_once` skips the account until the flag clears. `OFDeniedError` → `failed` (not sent, counts). | campaign `keep_warning` | — |
| **A** Zero-claim breaker | Uses the last N automatic `created` rows. A row counts as zero when its replaced promo gained no Claims while Kept (`claims_seen − first_claims ≤ 0`, NULL = 0; plan line, so a slow 0-claim promo counts too), or its new id was not seen **live** within `NOT_LISTED_S`. The hold starts at the row's `settled_at`: no further automatic create until the id is seen live or `NOT_LISTED_S` passes and back-off clears, so at most N creates reach the trip (DA 9). N in a row → turn off + warning `breaker` ("3 promos in a row got no new claims or never went live — check the offer, then tick Keep running again"). | `replaced_of_promo_id`, `claims_seen`, `listed_at` | N=3, `NOT_LISTED_S=600` |
| **B** Trusted count | as above | `promo_keep_state` | 0.9, cap ≥ 10, 90 s |
| **B** Timed only on OF end time | Timed needs cap ≥ 10, the current read's `finishedAt` for the Kept id equal to the previous read's, `0 < finishedAt − now ≤ TIMED_LEAD_S`, and a known clock: skew = local POST time − OF `createdAt` of our last `created` row, `|skew| ≤ 30 s`; unknown or larger → `Wait` + card "clock". `expires_at` only times the Re-check, at `finishedAt − TIMED_LEAD_S`. | `promo_keep_state.skew_s` | `TIMED_LEAD_S=120`, 30 s |
| **A** Pre-POST re-read | Twice: inside `reserve()`, and with the `sending` CAS just before the POST: `auto_reactivate`, `preempt` (B: Fill/Timed), `of_promo_id` == decided id, no reservation newer than `decision_read_at`, rule enabled, `recreates_left` ≠ 0, Host fence, price check, decision read ≤ 90 s. Any miss → no POST. Residual: the client's own signed-slot wait (≤ 150 s) after the CAS. | — | — |
| **A** Host fence | `PROMO_CREATE_HOST_ID` (env only; compose passes `${PROMO_CREATE_HOST_ID:-}`), **one value per box**, never shared by failover pairs (DA 7). Stamped on tick into `keep_host_id`. Automatic creates need non-empty env == stamp. A miss → no OF read, no create, a derived card warning. No `runtime_switches` entry. Test, shadow, demo and copied stacks leave it unset, so a tick there stamps "" and stays fenced. Failover: the box taking over re-stamps with `service/scripts/promo_keep_restamp.py` (rewrites `keep_host_id` of Kept rows to its own env value, prints the count), run by the human on takeover; `ae-fence clear` prints it in its start hint (it starts nothing itself, `deploy/ae/ae-fence:134-150`). | campaign `keep_host_id` | empty = fenced |
| **A** Fence notices | At boot, when Kept campaigns exist and env is empty or ≠ their stamp: one owner notice per campaign (dedupe `promo_keep_fenced:<campaign>:<env>`), log `promo_keep_blocked reason=fence account=… campaign=…` (K1). Rows ticked before 0126 (`keep_host_id`/`sub_price_cents` NULL) get the same notice with "Tick Keep running again". | — | — |
| **A** WATCH check | `scripts/proxy-health/watch.py` gains `WATCH_CHECKS["promo_keep_fenced"]`: alerts when any `auto_reactivate` campaign has a NULL/empty `keep_host_id`, or the relay log shows `promo_keep_blocked reason=fence` in the window. Test in `scripts/proxy-health/test_watch.py`. After deploy, the human appends `- promo-keep-fence \| added <date> \| expires +3d \| promo_keep_fenced \| <PR url>` to WATCH.md (outside this repo). | — | — |
| **A** Free-trial limit | Discount 100 + Keep running needs cap ≥ 1 (unlimited refused, `trial_unlimited`) and `recreates_left` 1–10 (form default 3), enforced on create, on PATCH re-tick (body must carry `recreate_limit`, else 422) and in `reserve()` (DA 6). Decremented at settle `created`. At 0 → turn off + warn `limit_reached`. Other discounts: NULL = no limit. | campaign `recreates_left` | 3; max 10 |
| **A** Price check | No OF read anywhere (plan GOAL). New `account_page.peek_price_cents(account_id) -> int \| None` returns the cached value only (≤ 6 h known, `account_page.py:47-48`; primed by the app's `/users/me`, `server.py:3028`, and the session probe), never fetches. **Tick:** stamp `sub_price_cents` = peek (NULL if cold); peek 0 → tick refused (`price_free`). **Before every automatic create** (in `reserve()` and at the CAS): peek 0 → hold `price_free`; peek known and stamp NULL → stamp it, proceed; peek == stamp → proceed; peek ≠ stamp → **hold** (no create, `keep_blocked=price_changed`, notice once per campaign + peek value); peek cold → After-end proceeds with card note `price_unchecked`, Fill/Timed `Wait(price_unread)`. A re-tick re-stamps. Until MEASURE e is recorded, a mismatch always holds; e = yes (the price reflects a live promo's discount) → stamp and compare only peeks primed while no promo is live. Free page on OF's side: OF itself refuses ("Access denied", `api_errors.py:14-17`) → `price_free` turn-off. | campaign `sub_price_cents` | — |
| **A** Takeover notice | Create only. The dialog shows the Kept campaign it will take from and sends `expect_taken_from` (id or null); a different current Kept campaign → 409 `keep_running_moved`. The response returns `keep_running_taken_from:{id,name}`. PATCH keeps its 409 (`promotions_api.py:310-318`). Notice kind `promo_keep_running`. | `agency_notifications` | — |
| **A** Automatic-create notice | `notifications_api.notify_creator_owners` (`notifications_api.py:334`), kind `promo_keep_running` (added to `settings_schema.NOTIFICATION_KINDS`), dedupe `promo_create:<row id>`, written in the settle transaction. Text names the campaign, the source (filled / ending / ended) and the new id. Turn-offs and holds use the same kind, dedupe `promo_keep_off:<campaign>:<at>`. The card shows the same reason, so a switched-off notice kind hides nothing (K3). | `agency_notifications` | on |
| **A** Raw finish / delete | `POST /api/of/v2/promotions/{id}/finish` and `DELETE …/{id}`: when `id` is a Kept promo's `of_promo_id`, untick it in the same request before the OF call (Growth's order, `useGrowth.ts:518-527`). | — | — |
| **A** Re-check, atomic | Per Creator: `UPDATE promo_keep_state SET recheck_at=:at WHERE account_id=:a AND (recheck_at IS NULL OR recheck_at < :now − 600 s)` (rowcount CAS, precedent `account_health.py:151`), then in the same session `_rule_is_live` + `enqueue_job(…, payload={…, FOLLOWUP_MARK: True}, rule_id=rid, session=s)` (the `enqueue_followup` body, `job_queue.py:251-278`). A Re-check run sets `recheck_at = NULL` at start. A Takeover does not reset it. Replaces `_recheck_pending`. Chain: near_cap only from a non-Re-check run; expiry retries ≤ 3 (existing); Timed is one-shot; ≤ 1 follow-up per run. | `promo_keep_state.recheck_at` | 600 s stale |
| **B** Pre-emption switch | `runtime_switches` `PROMO_PREEMPT_ENABLED` gates Fill + Timed (a copied value is harmless: the Host fence still binds). | switch registry | off |

ASSUMPTION: budget 3/h, 8/day from the plan's "proposed" (rung 2 as a proposal). Overturned if the owner sets other numbers.
ASSUMPTION: shoutout bursts get no budget exception (rung 4). A 4th fill in an hour waits, with a card warning. Overturned if the owner prefers gaps closed over the cap.
ASSUMPTION: captcha is detected by "captcha" in the response body (guess; no captcha class in `service/` outside remote login). Overturned by a measured OF captcha response.
ASSUMPTION: a first 403 on create is transient (proxy) and only a second in a row, or "Access denied", turns Keep running off (rung 4; owner memory: DC 403s are provider-side). Overturned if a measured OF create 403 other than "Access denied" proves permanent.
ASSUMPTION: a 5xx, timeout or connection error after send is `unknown`, not `failed` (rung 4); `_proxy_retry` may already have re-sent it (`of_client.py:834-880`), so the reconcile allows several candidates → stays open → `lost`. Overturned if OF is measured never to create on a 5xx.
ASSUMPTION: breaker N=3, `NOT_LISTED_S=600`, `UNKNOWN_OFF_S=900`, `SETTLE_GRACE_S=600` (rung 5; grace > 150 s slot wait + retries). Overturned by MEASURE d showing list lag over 10 min.
ASSUMPTION: `TIMED_LEAD_S=120` and skew ≤ 30 s measured from our own create's `createdAt` (rung 5). Overturned if MEASURE c shows OF ends promos before `finishedAt`.
ASSUMPTION: Free-trial limit default 3, max 10 (rung 5). Overturned by an owner number.
ASSUMPTION: a session-dead create keeps Keep running on (rung 3: `run_once` parks the account, `account_health.py:12-26`). Overturned if the owner wants a re-tick after every re-login.
ASSUMPTION: the price comes only from `account_page`'s cache (rung 2: plan GOAL "request counts as now", coordinator ruling on N1); residual: a paid → paid change made on OnlyFans is re-made at the same percent for up to 6 h, and indefinitely while the cache stays cold. Overturned if the owner accepts one `/users/me` read per automatic create, or MEASURE e shows the cached price is unusable.
ASSUMPTION: a price mismatch holds (no create, warning, notice) rather than turning Keep running off (rung 4: reversible, resumes on a re-tick or matching price; with MEASURE e open a false mismatch must not end Keep running). Overturned if the owner wants a mismatch to untick.
ASSUMPTION: a cold price cache lets After-end proceed with a visible `price_unchecked` note and holds only Pre-emption (rung 2: plan fixes After-end as the fallback; Pre-emption is the optional speed-up). Overturned if the owner wants After-end held on a cold cache.
ASSUMPTION: failover re-stamp is a human-run script, not automatic in `ae-fence` (rung 4: the takeover is already a human act and `ae-fence` starts nothing). Overturned if failover must be hands-off.

### Owns
- **A** `promo_reactivate`: decision wiring, memo, reconcile call, settle, notices. **B** Fill/Timed wiring, `should_poke`.
- **A** New `promo_create_guard`; new `promo_keep_decide` (pure; B adds Fill/Timed).
- **A** `of_promos.extract_created_promo`: a dict without `id`/`promoId` (and no usable `items`) returns `{}`; a bare promo dict still parses. `normalise_of_promo` gains `claims_present`.
- **A** `account_page.peek_price_cents`.
- **A** `promotions_api`: `recreate_limit`, `expect_taken_from`, `resolve_open`, Takeover field, reservation on create, reconcile on GET, tick-time price/host stamp. **B** `preempt`.
- **A** Raw promo create, finish and delete routes in `server`.
- **A** `dispatch_plan.plan_rule` Repoke opt-in (`REPOKE_KINDS = {"promo_reactivate", "purchase_followup"}`). **B** `event_transcoder._transcode_toast` gate; `_has_subscribe_toast` → a count.
- **A** `settings_schema.NOTIFICATION_KINDS`; the compose relay env line; `service/scripts/promo_keep_restamp.py`; `ae-fence clear` hint; `scripts/proxy-health/watch.py` check. **B** `runtime_switches` entry.
- Frontend: **A** `createPromotionForm` (trial default, limit, takeover), `PromotionTab`, `PromoListRow`, `PromoReactivateCard`; **B** second tick, waiting line.
- **A** `assistant_manual.md` (B adds the second tick).

### Interfaces
- **A** `promo_keep_decide.decide(inputs) -> Wait(reason) | AfterEnd | TurnOff(reason)`; **B** adds `Fill | Timed`. Inputs: read summary (incl. `claims_present`, OF flags), memo, campaign fields, budget/back-off/breaker facts, price peek, skew, switch, fence, now. Pure, no I/O.
- **A** `promo_create_guard.reserve(account_id, campaign_id, source, terms, expect, pre_ids, decision_read_at) -> Reservation | Refused(reason)`; `mark_sending(res, recheck) -> bool`; `settle(res, outcome)`, `reconcile(account_id, items)`, `budget_state(account_id, now)`.
- **B** `promo_reactivate.should_poke(account_id, n_toasts) -> bool`: sync, in-memory. True when there is no in-process memo copy, when last Claims + toasts since read ≥ threshold, or when the read is older than 600 s. Adds `n_toasts`; a read resets the toast count.
- **A** `POST /admin/promotions` body gains `recreate_limit: int | None` (1–10), `expect_taken_from: int | None`, `resolve_open: int | None`; **B** `preempt: bool = true`. The response gains `keep_running_taken_from`. 409 `create_in_flight` / `create_unresolved` / `keep_running_moved`.
- **A** `PATCH /admin/promotions/{id}` gains `recreate_limit` (**B** `preempt`). GET rows gain `recreates_left`, `keep_warning`, `keep_blocked` (derived: fence / budget / back-off / unknown / price_changed / price_unchecked); **B** `preempt`, `keep_blocked` switch / clock, `keep_wait` (from `wait_reason`).
- **A** Raw `POST /api/of/v2/promotions` gains the 409s and `resolve_open`.
- **A** `test_route_order.golden.json` updated if route signatures change.

### Schema (A; one revision, B-only columns unused until B)
Alembic revision `0126_promo_preempt`, down_revision `0125_promo_campaign_expiry`. Inspector-guarded and idempotent, like 0125. `init_db` additive catch-up covers the columns.
```
promo_create_reservations                          -- A
  id INTEGER PK
  account_id TEXT FK accounts ON DELETE CASCADE NOT NULL
  campaign_id INTEGER FK promo_campaigns ON DELETE SET NULL NULL
  source TEXT NOT NULL      -- manual | manual_raw | auto_ended | auto_fill | auto_timed (B: auto_fill, auto_timed)
  state TEXT NOT NULL       -- pending | sending | created | failed | unknown | lost | cleared
  terms_json TEXT NOT NULL  -- discount, subscribeCounts, subscribeDays, finishDays, message, type; manual: name, keep intent
  pre_ids_json TEXT NOT NULL DEFAULT '[]'
  replaced_of_promo_id BIGINT NULL, claims_seen INTEGER NULL
  host_id TEXT NULL, of_promo_id BIGINT NULL, listed_at DATETIME NULL
  error_class TEXT NULL, retry_after_s INTEGER NULL, not_before DATETIME NULL
  reconcile_reads INTEGER NOT NULL DEFAULT 0
  created_at DATETIME NOT NULL, sent_at DATETIME NULL, settled_at DATETIME NULL
  UNIQUE uq_promo_create_open(account_id) WHERE state IN ('pending','sending','unknown')
  INDEX ix_promo_create_account_time(account_id, created_at)
promo_keep_state                                   -- A
  account_id TEXT PK FK accounts ON DELETE CASCADE
  kept_of_promo_id BIGINT NULL, first_claims INTEGER NULL, last_claims INTEGER NULL,
  seen_below BOOLEAN NOT NULL DEFAULT 0, finished_at TEXT NULL, read_at DATETIME NULL,
  recheck_at DATETIME NULL
  skew_s INTEGER NULL, wait_reason TEXT NULL       -- B reads
promo_campaigns + recreates_left INTEGER NULL, sub_price_cents INTEGER NULL,
                  keep_host_id TEXT NULL, keep_warning TEXT NULL      -- A
                + preempt BOOLEAN NOT NULL DEFAULT 1                  -- B reads
```
`scheduled_jobs` is not altered (hot table, `models.py:1910`).
ASSUMPTION: no reservation prune in Phase 01 (rung 5; ≤ 8 automatic/day/Creator × 50 Creators). Overturned if the table passes 100k rows.
ASSUMPTION: one migration in A carries B's three columns (rung 5: one revision, additive, unused until B). Overturned if B is dropped (columns stay inert) or the reviewer wants a 0127.

### Contracts
- The OF create body is unchanged (`of_sends.create_promo`). There is no idempotency key; OF exposes none (inferred: none observed).
- `promo_reactivate` reads stay through `of_pacing.walk`. Writes are unpaced, as now.
- Deployed Kept campaigns may exist (pre-#850 `auto_reactivate`); no backfill: they stay fenced until re-ticked, with the fence notice. The `_recheck` payload mark may change freely.
- Request counts, per HTTP request (each page counts), by trigger, for the same scripted toast sequence: **A** `GET /promotions` ≤ PR #850's, `GET /users/me` == PR #850's (no added read), POST count == expected creates; **B** a far-from-threshold toast script reads strictly fewer `GET /promotions` than #850. Operator actions (tick, manual create, manual reconcile, Growth GET) are outside the automatic count.

### UI
- **Reducer** (`createPromotionForm.ts`, house rule; template `fanDrawerForm.ts`). State gains:
  - **A** `keepRunning: boolean | null` (null = untouched → `kind !== "trial"`);
  - **A** `recreateLimit: number` (3);
  - **A** `takenFrom: {id, name} | null` (from the loaded campaigns);
  - **B** `preempt: boolean` (true).

  Actions gain `recreateLimit`, `takenFromLoaded` (A), `preempt` (B). Pure helpers `keepRunningOn`, `takeoverNotice(keptName)` (A), `preemptUsable` (cap ≥ 10, B). `canSubmit` adds: trial + keep on → cap ≥ 1 and 1 ≤ limit ≤ 10. `buildPayload` sends `recreate_limit` only for trial + keep on, `expect_taken_from` with keep on (A), `preempt` only with keep on (B). Vitest tables cover every action and helper.
- **Phone portrait** (≤ 390 px). **A** The limit field is full-width under Keep running, trial only; the Takeover line and warnings are full-width text, not tooltips. **B** The second tick sits on its own line, indented 24 px under Keep running, label wraps, 44 px tap row; disabled hint "Needs an Offer limit of 10 or more". The same layout applies to the row (`PromoListRow`).
- **Card copy** (`PromoReactivateCard`). **A** It lists ticked campaigns and any campaign with `keep_warning`. Status "Re-creates after it ends". One line per block reason, naming who fixes it: fence "This server is not set to create promos — ask the owner to set it up"; re-tick "Tick Keep running again"; budget "Paused: 3 re-creates this hour"; back-off until; unknown create; breaker; price_changed "Price changed on OnlyFans — tick Keep running again to accept it"; price_unchecked; limit. **B** Status "Re-creates at 90% filled / shortly before it ends"; switch "Re-create at 90% filled is off on this server — ask the owner"; clock; waiting line "Waiting: will re-create after it ends (<reason>)" from `keep_wait`.
- **Docs.** **A** In `assistant_manual.md` (Profile promotion block, around line 549-560): Keep running's stop/hold reasons, the Free-trial limit, the notice. Deploy note: set a unique `PROMO_CREATE_HOST_ID` per box in the compose-level env of each live Deployment, never on test/shadow/demo; after failover run `promo_keep_restamp.py` on the box taking over; re-tick existing Kept campaigns. **B** both ticks. ADR-0039/0040/0041 status → accepted at build. MEASURE results are appended to ADR-0039.

## Testing Decisions
Seams sit at public interfaces only. Prior art: `test_promo_reactivate.py` (FakeOF returning LIST, `_use_fake` patching `ax._make_client`, `run_once`), `test_promotions.py` (`_agency_fixtures`), `test_event_triggers.py`, `test_automation_executor_decide.py`, `test_promo_expiry_migration.py`, `test_watch.py`, `createPromotionForm.test.ts`, `PromotionTab.test.tsx`.
- **A** `test_promo_keep_decide.py` pure table, A rows: inferred-cap After-end, budget (automatic only), back-off math (Retry-After > 6 h), turn-off classes (first 403/429 back-off, second off, "Access denied" off), breaker (gained vs absolute, hold from settle), limit, price (match, mismatch hold, cold, stamp NULL, free). **B** rows: threshold arithmetic for caps 9/10/11/50/100/0, trust rules (missing count, first read ≠ 0, drop, stale, no recovery slot, price_unread), Timed window and skew, `wait_reason`.
- **A** `test_promo_reactivate.py` additions use `run_once("promo_reactivate")` against the FakeOF with modes `lists_new`, `lists_new_after` (delay), `claims_missing`, `fail_with` (429 + Retry-After, 403 once/twice, "Access denied", captcha body, session-dead, 400, 500, timeout-after-send, bad JSON 2xx), `create_shape` (list, bare dict, dict without id), `raise_after_post` (crash), `slow_send` (pending past grace), `on_list` / `before_send` hooks (operator change before and after reserve, manual create after the decision read). The FakeOF keeps a request log (method, path, t) and a live timeline.
- **B** `test_promo_preempt.py` uses the same FakeOF plus `ends_old_on_create`, `ends_old_on_failed_create`, `claims_lag`, `new_starts_at`, `finished_at`, `created_at_skew`; cases: Fill, Timed success, After-end with the switch off and with `preempt` off, no `finishedAt` → no Timed.
- **A** `test_promo_create_guard.py`: two concurrent `reserve()` (one wins), the `sending` CAS, `newer_create` refusal, trial NULL refusal, reconcile adopt / several candidates / pre-id excluded / null cap = 0 / no match stays open, unknown → lost at `UNKNOWN_OFF_S`, settle atomic (crash before commit leaves the row open), late settle after `cleared`, budget windows ignore manual rows.
- **A** `test_promotions.py` additions: manual 409 while open; `create_unresolved` then `resolve_open` succeeds; GET reconciles an open row; manual create after budget exhaustion succeeds and is not counted; raw route reserved; raw finish of a Kept id unticks; Takeover field; `keep_running_moved`; trial needs limit and cap ≥ 1 on create and PATCH; tick refused on cached price 0; tick stamps host id and cached price without an OF read. **B** PATCH `preempt`.
- **A** `test_promo_keep_restamp.py`: restamps only Kept rows, prints the count, refuses an empty env.
- **A** `test_automation_executor_decide.py`: an under-floor Poke is spent for `send_welcome`, kept for `promo_reactivate` and `purchase_followup`.
- **B** `test_event_triggers.py`: a far-from-threshold toast makes no promo Poke; near-threshold, no memo or a stale memo does; a frame with 3 subscribed toasts counts 3.
- **A** `test_promo_preempt_migration.py`: 0126 up on a 0125 DB, idempotent, partial index present.
- **A** `scripts/proxy-health/test_watch.py`: `promo_keep_fenced` alerts on a NULL stamp and on the fence log line, silent otherwise.
- **A** `PromoReactivateCard.test.tsx`: a turned-off campaign with `keep_warning` renders its reason; fence and price lines name who fixes. **B** waiting line renders `keep_wait`.

### Must-not table
| # | failure | design answer | storage | test |
|---|---|---|---|---|
| 1 A+B | loop from stale/wrong claimsCount, new promo not at 0 | A: inferred-cap After-end needs id, first-read-0 and monotonic history. B: Trusted count (raw count present, first read 0, same id, monotonic, ≤ 90 s, < cap). Residual (OF lying consistently from 0 to 90) bounded by budget 3/h, 8/day | `promo_keep_state` | A `case_mn01_inferred_cap_without_history_waits`, `case_mn01_missing_count_untrusted`; B `case_mn01_lagging_or_nonzero_new_count_waits` |
| 2 A | create accepted, never listed (~690/day) | no id → `unknown` → `lost` + off after `UNKNOWN_OFF_S`; id never seen live → breaker N=3, hold from settle; budget | reservation `state`, `listed_at` | `case_mn02_unparsed_never_listed_turns_off`, `case_mn02_listed_never_live_stops_after_three` |
| 3 A | retry storm (429, 403, captcha, session dead) | recorded `failed`, back-off with uncapped Retry-After, second 403/429 or captcha → off, `mark_session_dead`, budget | reservation `error_class`, `not_before`; `keep_warning` | `case_mn03_429_backs_off_then_turns_off`, `case_mn03_single_403_backs_off_keeps_on`, `case_mn03_retry_after_over_6h_honoured`, `case_mn03_captcha_turns_off`, `case_mn03_dead_session_flags_account` |
| 4 B | old ended, new create fails | Pre-emption only with a recovery slot in both windows; warn "no promo may be live" + notice; After-end after back-off; switch off until MEASURE a | reservation `failed` | `case_mn04_failed_preempt_falls_back_after_backoff`, `case_mn04_no_recovery_slot_no_preempt` |
| 5 A | create OK, no id parsed | `extract_created_promo` → `{}` → `unknown`; never released by a negative read; unique-candidate adopt or `lost` + off | reservation `unknown` | `case_mn05_unparsed_id_unknown_then_adopted`, `case_mn05_invisible_two_reads_no_second_create` |
| 6 A | crash or slow send between POST and DB write | `pending` committed before; `sending` CAS before the POST; a stale `pending` (never sent) → `failed`, a `sending` → adopt or `lost`; grace 600 s > slot wait | reservation `pending`/`sending` | `case_mn06_crash_after_post_adopts_no_duplicate`, `case_mn06_slow_send_past_grace_no_second_post` |
| 7 A | two Relays / copied DB / failover box | partial unique index (same DB); Host fence env ≠ stamp or unset (copy); one id per box, re-stamp only by the human on takeover | `uq_promo_create_open`, `keep_host_id` | `case_two_reservers_one_wins` (guard), `case_mn07_host_mismatch_or_unset_no_create`, `case_mn07_tick_on_unfenced_copy_stamps_empty`, `test_promo_keep_restamp` |
| 8 B | Timed on guessed end / skew | cap ≥ 10; Timed only on read `finishedAt`, two reads agree, within `TIMED_LEAD_S`, `\|skew\| ≤ 30 s` from our own `createdAt`; `expires_at` only times the Re-check | `promo_keep_state` | `case_mn08_guessed_end_never_timed`, `case_mn08_finished_at_changed_waits`, `case_mn08_skew_waits`, `case_mn08_cap9_never_timed` |
| 9 A | free trial + burst = unlimited subs | Keep running unticked by default for trial; unlimited (cap 0) trial refused on create, PATCH and in `reserve()`; claim cap bounds each promo; `recreates_left` optional (NULL = indefinite, owner 2026-11-21), counts down when set; budget | `recreates_left` | `case_mn09_free_trial_stops_at_limit`, `case_mn09_unlimited_trial_refused`, `case_free_trial_limit_optional`, `case_free_trial_no_limit_keeps_running`; vitest `trial default keep off` |
| 10 A | operator stop/edit/replace/untick between read and POST | campaign re-read in `reserve()` and at the `sending` CAS; `newer_create` refusal; raw finish/delete unticks; residual: a native OF.com edit inside the ≤ 90 s decision window, or after the CAS during the ≤ 150 s slot wait | — | `case_mn10_untick_mid_run_no_post`, `case_mn10_untick_after_reserve_no_post`, `case_mn10_takeover_mid_run_no_post`, `case_mn10_manual_create_after_decision_read_no_post`, `case_raw_finish_unticks` |
| 11 A | price changed / went free | cached price vs `sub_price_cents`: mismatch → hold + warning + notice; cached 0 or OF "Access denied" → `price_free`; cold → After-end with visible note, Pre-emption waits; residual ≤ 6 h cache (ASSUMPTION) | `sub_price_cents` | `case_mn11_price_changed_holds`, `case_mn11_free_page_no_create`, `case_mn11_cold_cache_after_end_flagged` |
| 12 A | silent untick of previous Kept campaign | create-only `expect_taken_from` → 409 on change; `keep_running_taken_from` + dialog line + notice | notice row | `case_create_takeover_names_previous`, `case_create_takeover_moved_409` (test_promotions); vitest `takeoverNotice` |
| 13 A | Re-checks stacking/chaining | per-Creator CAS on `promo_keep_state.recheck_at` (cleared by the Re-check run, stale after 600 s), same-session rule-live enqueue, bounded chain | `recheck_at` | `case_mn13_racing_rechecks_queue_one`, `case_mn13_due_unclaimed_recheck_no_second`, `case_mn13_takeover_no_second`, `case_mn13_chain_bounded` |
| 14 A+B | deferred Pokes every minute on busy Creators | A: Repoke opt-in (`promo_reactivate`, `purchase_followup`). B: toast gate on claim estimate, so promo runs ≤ #850's per-toast Pokes | in-process toast count | A `case_send_welcome_underfloor_poke_spent` (decide); B `case_toast_far_from_threshold_no_poke` (event_triggers) |

## MEASURE FIRST
Each step is run by the human on the owner test account, only after the Acceptance local proof is green. No agent runs it. Results are appended to ADR-0039. The switch flips only when every pass condition holds.
| | question | design if yes | design if no | procedure (human) | pass condition | holds |
|---|---|---|---|---|---|---|
| a (B) | Does a create while a promo is live end the old one? If the create fails, is the old one ended? | Fill/Timed give zero gap | Two promos live → the next read sees another live promo → stand down + card warning "two promos live"; no further create. Failure ends the old one → worst case already designed (#4). | Make promo A (Keep running off, cap 10, 5 %). Confirm A live in Growth → Profile promotion and on the profile in a logged-out browser. Make promo B; reload the logged-out profile right after. Record A's `finishedAt`, B's `createdAt`, both live states; screenshot. Failure order is not induced. | A not live, B live, A `finishedAt` ≥ B `createdAt` − 5 s, logged-out profile showed an offer on every reload | `PROMO_PREEMPT_ENABLED` off until pass |
| b (B) | Does a claim fire a Subscribe toast? | The toast gate catches the threshold: Fill on time | Fill only from Backstop / stale-memo reads; mostly After-end, as in #850 | With a promo live, note the Relay log's subscribed-toast lines against the Claims delta in the list over the same hour of natural claims. | — (efficiency only) | none |
| c (B) | Does a timed promo carry `finishedAt` on read? | Timed works | Timed never fires (self-gated); expiry Re-check + After-end | Make a cap-10 promo with expiration 1 day. Record the normalised `finished_at` from the list and that it equals create + 1 day. Finish it by hand. | — (data-gated) | none |
| d (B) | Is claimsCount fresh, and does a new promo start at 0? | Trusted count passes | Lag → monotonic / ≤ 90 s rules Wait; nonzero start → rule 3 fails → After-end only | During a, record B's raw `claimsCount` on its first read. During b, list reads 60 s apart against toast times. | B's first `claimsCount` present and 0; no read lags a toast by > 90 s | `PROMO_PREEMPT_ENABLED` off until pass |
| e (A) | Does `subscribePrice` on `/users/me` (the cached price) show the base price while a promo is live? | Stamp/compare only peeks primed while no promo is live | Compare every peek (the A default) | In the dashboard, with no promo live, open the creator (primes `/users/me`) and note `subscribePrice` from the Relay's `GET /api/of/v2/users/me`. Make a 50 % promo; reload; note it again. Finish the promo. | Both values equal the profile price | price mismatch holds and warns until recorded |

OF claims in this section are inferred (ping-pong note in `promo_reactivate.py`, ADR-0039; `account_page.py:10` for e) or guess; none are measured.
ASSUMPTION: the failure order in (a) stays unmeasured and the worst case is designed for (rung 4). Overturned by an observed failed create on the owner test account.

## Acceptance
Shared stems: unit scripts exit non-zero on a failed assert; the proof writes per-scenario counts; the heredoc asserts every expected scenario exists, its exact POST count, and the read counts, so a missing or vacuous scenario fails.
```sh
# ---- Slice A ----
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
for t in promo_keep_decide promo_create_guard promo_reactivate promotions automation_executor_decide \
         promo_preempt_migration promo_expiry_migration promo_keep_restamp; do
  ./venv/bin/python "service/tests/test_$t.py"
done
./venv/bin/python scripts/proxy-health/test_watch.py
(cd app && nice -n 10 npx vitest run components/growth/createPromotionForm.test.ts components/growth/PromotionTab.test.tsx components/growth/PromoReactivateCard.test.tsx)
(cd app && nice -n 10 npx tsc --noEmit)
nice -n 10 scripts/run-tests.sh
# Proof relay: scripts/demo-shots/promo_proof_relay.py = relay_guarded.py's sandbox (temp DB, loopback, fetch-guard)
# with automation_supervisor left running (relay_guarded imports _run_ui_safe, which neuters it: service/_run_ui_safe.py:52),
# pumps off, OF origin at a stateful fake /promotions + /users/me with a per-origin request log (OF_WEB_ORIGIN seam, ADR 0024).
# Toasts enter through the transcoder (POST /__slop/of-ws-frame wired by the proof relay).
git worktree add /tmp/promo-850 7df39f6aa
nice -n 10 ./venv/bin/python scripts/demo-shots/promo_preempt_proof.py --slice A --out /tmp/promo-a-proof
nice -n 10 ./venv/bin/python scripts/demo-shots/promo_preempt_proof.py --relay-root /tmp/promo-850 --only toast-100 --out /tmp/promo-850-proof
./venv/bin/python - <<'EOF'
import json
n = json.load(open('/tmp/promo-a-proof/counts.json')); o = json.load(open('/tmp/promo-850-proof/counts.json'))
POSTS = {'after-end': 1, 'mn02-unparsed': 1, 'mn02-never-live': 3, 'mn03-429': 2, 'mn03-403-once': 2, 'mn05': 1,
         'mn06-crash': 1, 'mn06-slow': 1, 'mn07-two-relays': 1, 'mn07-copy-unset': 0, 'mn09-trial': 3,
         'mn10-untick': 0, 'mn10-manual-after-read': 1, 'mn11-price-changed': 0, 'mn11-free': 0,
         'mn12-takeover': 1, 'mn13': 1, 'mn14': 1, 'fence-unset': 0}
missing = set(POSTS) - set(n); assert not missing, missing
for k, want in POSTS.items():
    s = n[k]; assert s['pass'], k
    assert s['POST /promotions'] == want, (k, s['POST /promotions'], want)
    assert s['GET /users/me'] == 0, (k, 'added read')
assert n['mn03-403-once']['keep_running'] is True and n['mn03-429']['keep_running'] is False
assert n['mn13']['recheck_jobs'] == 1 and n['mn11-price-changed']['notices_price'] == 1
assert n['fence-unset']['notices_fence'] >= 1 and n['mn07-copy-unset']['POST /promotions'] == 0
t, b = n['toast-100'], o['toast-100']
assert b['jobs_run'] > 0 and t['jobs_run'] > 0, 'toasts never reached the executor'
assert t['GET /promotions'] <= b['GET /promotions'] and t['GET /users/me'] <= b['GET /users/me']
print('slice A ok')
EOF
# ---- Slice B (adds; runs Slice A first) ----
./venv/bin/python service/tests/test_promo_preempt.py
./venv/bin/python service/tests/test_event_triggers.py
nice -n 10 ./venv/bin/python scripts/demo-shots/promo_preempt_proof.py --slice B --out /tmp/promo-b-proof
nice -n 10 ./venv/bin/python scripts/demo-shots/promo_preempt_proof.py --relay-root /tmp/promo-850 --only toast-far --out /tmp/promo-850-far
./venv/bin/python - <<'EOF'
import json
n = json.load(open('/tmp/promo-b-proof/counts.json')); o = json.load(open('/tmp/promo-850-far/counts.json'))
POSTS = {'fill-90': 1, 'timed': 1, 'burst-past-cap': 1, 'mn01-lag': 0, 'mn01-nonzero-start': 1,
         'mn04-failed-preempt': 2, 'mn04-no-slot': 1, 'mn08-guessed-end': 1, 'mn08-skew': 1, 'switch-off': 1}
missing = set(POSTS) - set(n); assert not missing, missing
for k, want in POSTS.items():
    s = n[k]; assert s['pass'], k
    assert s['POST /promotions'] == want, (k, s['POST /promotions'], want)
    assert s['GET /users/me'] == 0, (k, 'added read')
f = n['fill-90']; assert f['claims_at_post'] < f['cap'] and f['gap_s'] == 0, f
assert n['switch-off']['claims_at_post'] >= n['switch-off']['cap'], 'switch off must fall back to After-end'
assert n['toast-far']['GET /promotions'] < o['toast-far']['GET /promotions'], 'toast gate did not cut reads'
print('slice B ok')
EOF
git worktree remove /tmp/promo-850
# manual A: screenshots — create dialog desktop + 390x844 portrait (trial limit, takeover line, moved 409), card with each
#   warning (fence, budget, back-off, unknown, breaker, price_changed, price_unchecked, limit, re-tick) on a ticked and a
#   turned-off campaign; DB row check of promo_create_reservations + promo_keep_state + agency_notifications.
# manual B: screenshots — both ticks desktop + portrait, disabled hint, switch-off / clock / waiting lines.
# manual: devils-advocate agent + codex exec re-review of this spec before build.
# manual (human, pre-deploy A): Kept-row count per Deployment (plan-review "Needs the human"); set a unique PROMO_CREATE_HOST_ID
#   per box; re-tick or restamp; after deploy append the promo_keep_fenced WATCH.md line.
# manual (human, B): MEASURE a-d on the owner test account; flip PROMO_PREEMPT_ENABLED only if a and d pass. MEASURE e (A).
```

## Depends on
- PR #850 merged (7df39f6aa): Keep running, Re-checks, Pokes.
- ADRs 0039, 0040, 0041 (proposed; accepted when built).
- Migration 0125 present (`revision = "0125_promo_campaign_expiry"`).
- The OF origin test seam (`OF_WEB_ORIGIN`, ADR 0024, `of_client.py:268`) for the proof relay.
- Slice B depends on Slice A merged.
- Deploy-time (A): compose-level `PROMO_CREATE_HOST_ID`, unique per box, on each live Deployment before After-end is expected there (ADR-0041).

## Out of Scope
- Live OF runs by an agent: plan says the owner test account only, after local proof, by the human.
- Setting `PROMO_CREATE_HOST_ID` on real hosts, running the restamp, counting Kept rows, deploying, writing WATCH.md: deploy steps / production, floor 2.
- A slop scenario or slop gate: slop is opt-in (owner rule); the guarded-stack proof covers it.
- Fencing manual creates: ADR-0041 ASSUMPTION; the reservation still serialises them.
- An OF idempotency key: OF exposes none (inferred).
- Re-creating at a new subscription price automatically: #11 says hold and ask via a warning.
- Any OF read for the price check (`/users/me` before a create or at tick): plan GOAL "request counts as now".
- Auto-finishing a second live promo when (a)=no: it would end promos Inflowwww does not own (ADR-0039).
- Free trial links (`/trials`): a different OF object.
- Changing `max_reactivations` (lifetime cycle count): unchanged; `recreates_left` is the per-tick limit.
- Reservation retention prune: YAGNI at ≤ 8 automatic/day/Creator.
- Measuring a failed-create order on live OF: no safe way to induce it.
- Detecting a stop or edit made on OnlyFans itself: indistinguishable from an ending; After-end re-creates it, as in #850 (untick in Inflowwww).
- Making `_proxy_retry` skip POST re-sends: shared client code; the reconcile treats several candidates as unresolved.
- Settling open rows `failed` after a timeout (DA 1 fix): a negative read cannot prove OF made nothing; `lost` + off and Manual recovery cover it.
- Retargeting the OF mirror's Start campaign to `/admin/promotions` (six-hats Green): the raw route still exists and must be guarded anyway; it would add a Growth row per mirror start the plan did not ask for.
- Breaker exemption for slow 0-claim promos: the plan defines the breaker on "0 new claims".

## Further Notes
ASSUMPTION: one switch `PROMO_PREEMPT_ENABLED` gates Fill and Timed (rung 5; both depend on MEASURE a). Overturned if the owner wants Timed on before Fill.
ASSUMPTION: the Host fence check precedes any OF read, so a fenced copy makes zero OF calls for Keep running (rung 4). Overturned if the card must show live Claims on fenced stacks.
ASSUMPTION: the toast gate's 600 s staleness bound (rung 5) keeps reads ≤ #850's while still catching (b)=no via organic toasts. Overturned by a request-count regression in toast-100 / toast-far.
ASSUMPTION: the reconcile match uses terms + createdAt + pre-read ids, since OF does not echo the discount on read (measured 2026-07-22 per `of_promos.py:15-17`) (rung 3). Overturned if two identical-terms promos can be made within the window by hand.
ASSUMPTION: the stateful fake, `promo_proof_relay.py` and `promo_preempt_proof.py` live under `scripts/demo-shots/`, never in `service/` (rung 3: PR #850 proof at /tmp, guarded-stack precedent). Overturned if the owner wants the proof in `slop/scenarios/`.
ASSUMPTION: the notice kind `promo_keep_running` is owner-switchable like other kinds (rung 3); the card carries the same reasons. Overturned if the plan's "notified on every automatic create" must be unswitchable.
ASSUMPTION: existing Kept campaigns stay fenced until re-ticked, with a fence notice, rather than auto-stamped (rung 4). Overturned if the owner wants a one-time stamp at first boot.
ASSUMPTION: an unset `PROMO_CREATE_HOST_ID` means no automatic create, After-end included (rung 4, ADR-0041); the fence notice + WATCH check make it visible. Overturned if the owner wants Deployments to keep creating before their env is set.

## Review
Reviewer: **codex** (gpt via `codex exec`, reasoning high, sandbox read-only, blind workspace) · 2026-11-19. Both calls exited 0 inside 20 min with fresh non-empty output. Raw: `.scratch/promo-preempt/adversary-blind.md`, `.scratch/promo-preempt/adversary-draft.md`. Line refs below were re-checked in the worktree.

**Blind call**
- B1 zero gap only conditional (60 s Poke floor, `dispatch_plan.py:136-145`) — **partial**: true (measured by codex: Repoke <60 s, Enqueue at 60 s); goal kept, bound stated in "Zero gap is conditional", `burst-past-cap` scenario added.
- B2 alternatives: harden After-end first / separate enables / new read budget — **reject**: plan fixes Pre-emption in Phase 01; the gate already covers After-end with the switch off; both Pre-emptions depend on MEASURE a; plan forbids more reads. (Later: "harden After-end first" now ships as Slice A, same Phase, see six-hats.)
- B3 gate every create entry point, legacy binding, distinct host ids — **partial**: raw route was already in; added unique-env rule, Fence notices row (pre-0126 rows) and deploy note.
- B4 define what settles unknown; `retry_after()` ignores header (`of_pacing.py:172-175`, verified); catch hides dead session (`promo_reactivate.py:305`) — **accept**: new state machine (Reservation, Reconcile, Unknown → lost rows), `asked_wait`, `mark_session_dead`.
- B5 stop/price as write guards; raw finish only calls OF (`server.py:5569-5576`, verified) — **accept**: Raw finish/delete row, story 35; free page via OF 403.
- B6 normaliser coerces missing to 0, inferred cap reaches After-end untrusted (`of_promos.py:96-119`, verified) — **accept**: `claims_present`, rule 3 "first read 0", inferred-cap After-end rule.
- B7 per-request counts, recheck coalescing, unlimited free trial defeats limit — **accept**: Contracts per request incl. pages; `trial_unlimited` refusal; Re-check row rewritten.
- B8 test at Relay boundary; event tests stop before a job runs — **accept**: proof relay keeps the supervisor, toasts through the transcoder, `two-relays-one-db`.
- B9 measure fan-side claimability — **accept**: MEASURE a uses a logged-out profile and `finishedAt`/`createdAt`.
- B10 local tests fail (`_harness` missing) — **reject**: sparse workspace artifact (`git ls-files -v` showed `S`, skip-worktree).

**Draft call**
- D1 MN1 "1 then bad 90" passes; missing → 0; bad 100 via After-end — **accept**: rule 3 now "first read present and 0", inferred-cap rule; consistent-lie residual bounded by budget (stated).
- D2 MN2 unparsed + never listed → `failed` → breaker blind — **accept**: negative reads never settle `failed`; `lost` + off; "seen live" for `listed_at`.
- D3 MN3 dead-session LIST/price → None; 6 h cap breaks Retry-After 28800; raw guard loses header — **partial**: Retry-After uncapped, header read inside `_proxy`; failed LIST is a paced read with no create, as #850 (not a create storm).
- D4 MN4 third attempt ends A, budget blocks recovery — **accept**: Trusted rule 6 recovery slot; `case_mn04_no_recovery_slot_no_preempt`.
- D5 MN5 two negative LISTs release slot → C from A; bad-JSON 2xx (`of_client.py:921-929`, verified) — **accept**: unknown held, bad JSON = unknown.
- D6 MN6 send waits 150 s (`of_client.py:447`, verified) past 120 s grace — **accept**: `sending` CAS state, grace 600 s, stale `pending` → `failed` only.
- D7 MN7 copied DB + shared AE env; tick on copy stamps own id — **partial**: unset env stamps "" (fenced); unique env rule. Shared failover id superseded: one id per box (devils-advocate 7).
- D8 MN8 fast clock; cap-9 Timed contradicts plan — **accept**: skew from own `createdAt`; Pre-emption cap ≥ 10 for Timed too; story 4.
- D9 MN9 unlimited free trial — **accept**: `trial_unlimited`.
- D10 MN10 untick after reserve while waiting; native OF edit — **partial**: second re-read at `sending` CAS, raw finish unticks; native edit in ≤ 90 s window left as residual (implausible edge case, owner memory: human test only).
- D11 MN11 6 h cache; race read→POST — **partial**: free via 403; sub-second race rejected (implausible). Superseded by N1 resolution: the 6 h cache is now the design, residual flagged.
- D12 MN12 concurrent arm before submit; switchable notice — **partial**: `expect_taken_from` → 409 accepted; switchable notice kept (rung 3 ASSUMPTION), card shows the same reason.
- D13 MN13 CAS `recheck_at<=now` queues 2 (codex measured in SQLite); takeover new slot; lost rule-live check — **accept**: per-Creator `promo_keep_state`, cleared by the run, 600 s stale, same-session `_rule_is_live` + `FOLLOWUP_MARK`.
- D14 MN14 at 89 every toast runs promo; send_welcome fresh toasts each minute — **partial**: gate never exceeds #850's per-toast Poke (#850 poked every toast, `event_transcoder.py:168-169`); per-frame toast count added; send_welcome on fresh toasts is pre-#850 behaviour, rejected.
- D15 manual create blocked forever on unarmed Creator — **accept**: Manual recovery row (`create_unresolved` → `resolve_open` → `cleared`).
- D16 matcher adopts native promo / misses (subscribeDays 0 for percent) — **accept**: unique candidate, `pre_ids_json`, window, audience, subscribeDays only for discount 100.
- D17 settlement not atomic — **accept**: Settle row (one transaction, CAS, notice inside, manual intent in `terms_json`).
- D18 memo lost on restart; WS down; two workers; batched frames — **partial**: memo moved to `promo_keep_state` (accept); WS-down gap needs polling the plan forbids (reject, stated as conditional zero gap); one worker per DB (`docker-compose.yml:67-71`).
- D19 reads rise: tick GET, price GET with zero POSTs, LIST 2 pages on reconcile — **partial**: reconcile reads page 1 only, complete because newest-first (reject). Superseded by N1 resolution: no price read at tick or before create.
- D20 unset env / NULL stamps on deployed rows; "deployed nowhere" false — **accept**: premise corrected (Problem, Contracts), fence notice, deploy note, Depends on.
- D21 Acceptance false-green: guarded relay neuters supervisor (`_run_ui_safe.py:51-56`, verified), `0<=0`, no `set -e` — **accept**: proof relay, per-scenario pass, `jobs_run > 0`, `set -euo pipefail`.
- D22 stories without failing seams; card hides stopped campaigns (`PromoReactivateCard.tsx:19`, verified) — **partial**: added Timed/After-end/switch-off, delayed list, slow send, manual after budget, after-reserve change, due-unclaimed Re-check, card test, extra screenshots; UI-through-scheduler e2e left to the proof script.
- D23 MEASURE a/d cannot show gap or initial 0; flip without pass conditions — **accept**: pass-condition column, logged-out profile, raw first count; flip only on pass.
- D24 `REPOKE_KINDS` drops `purchase_followup` (`event_transcoder.py:531`) — **accept**: kept in the set.
- D25 PATCH takeover contradicts its 409 — **accept**: Takeover is create-only.

**needs-human (codex)**
- N1 price read vs "request counts as now" — **resolved (rung 2)**: the plan GOAL "Keep OnlyFans request counts as they are now" is a constraint, so option B: cached price only (Price check row), residual flagged as ASSUMPTION, MEASURE e added, mismatch holds and warns.

**devils-advocate 2026-11-19** (raw: `.scratch/promo-preempt/devils-advocate.md`, against 195b31463)
- DA1 manual creates refused for hours/forever (`promo_reactivate.py:193-194` returns before any read, verified) — **accept**: closed by codex D15 (Manual recovery); plus Growth's `GET /admin/promotions` list read (`promotions_api.py:88`, verified) now reconciles (Reconcile row). Timed `failed` settle rejected (Out of Scope).
- DA2 automation can end a promo the Employee just made (re-read checks the DB id only) — **accept**: `reserve()` and CAS refuse on a reservation newer than `decision_read_at` (Reservation, Pre-POST rows; story 19; `case_mn10_manual_create_after_decision_read_no_post`); raw finish unticks already in.
- DA3 transient 403 turns Keep running off — **accept**: first 403 → `failed` + back-off; off on second in a row or "Access denied" (`api_errors.py:14-17`, verified) (Turn-off row, story 11, MN3 test, ASSUMPTION).
- DA4 manual creates use the automation's budget — **accept**: budget counts automatic rows only (Budget row, story 24); old ASSUMPTION dropped.
- DA5 reconcile matches fields OF does not return — **partial**: codex D16 closed most (unique candidate, subscribeDays only for 100); added cap null→0 (`promotions_api.py:186-190`, verified) and "subscribeDays as sent"; `finishDays` never matched (`of_promos.py:15-16`, verified); `finishedAt − createdAt` rejected (finish days optional and often 0).
- DA6 free-trial limit bypass via NULL `recreates_left` — **accept**: refused in `reserve()`, on create and PATCH re-tick (Free-trial row, story 17, `case_mn09_null_limit_trial_reserve_refused`).
- DA7 Host fence passes on a shadow copy with a shared AE id — **accept**: one id per box; takeover re-stamp script (Host fence row, story 15, MN7).
- DA8 price check silent / false turn-off / pushes past 90 s — **accept**: no price read at all (N1 option B); `price_unread`/`price_unchecked` visible; mismatch holds, never turns off; MEASURE e.
- DA9 breaker trips on slow promos; hold start undefined — **partial**: 0-claim counting kept (plan line "0 new claims", rung 2), warning text explains it; hold now starts at `settled_at`, ≤ N creates before trip (Breaker row).
- DA10 tick read overstates "one per create" — **accept**: no OF read at tick or before create (Price row, story 27, Contracts).
- DA11 Acceptance passes while broken — **accept**: fake feeds claims past cap so a late POST leaves a real hole (`claims_at_post < cap`); exact POST count per named scenario, missing scenario fails; `toast-far` strict-less read case; `GET /users/me == 0`; `fence-unset` notice scenario; WATCH check `promo_keep_fenced`.
- DA12 adopting a hand-made identical promo — **accept**: closed by codex D16 (unique candidate + `pre_ids_json`).

**six-hats 2026-11-19** (raw: `.scratch/promo-preempt/six-hats.md`; bullets about the set as a whole are in plan-review)
- W2 Kept-row count on AE/public unknown — **accept**: production read, floor 2 → plan-review "Needs the human" with the command; Acceptance pre-deploy manual line.
- R2 card promises "90% filled" when it waits — **accept**: `wait_reason` → `keep_wait` → card waiting line (story 37, Trusted count, UI).
- K1 unset env stops all re-creates with no notice; no WATCH check — **accept**: fence notice at boot when env empty or mismatched and Kept rows exist; `promo_keep_fenced` WATCH check (story 38, Fence notices + WATCH rows).
- K2 shared AE failover id; `ae-fence arm` re-stamps — **partial**: one id per box accepted; re-stamp on takeover, not `arm`: `arm` fences the box being retired, `clear` is the takeover (`deploy/ae/ae-fence:12-16`, verified), and it stays a human-run script (ASSUMPTION).
- K3 403 turn-off punishes; notices owner-only/switchable; name who fixes — **accept**: 403 rule (DA3); card shows every reason incl. holds, copy names the owner where only the owner can fix (UI Card copy).
- Y2 pure `decide` + reservation table testable; raw-route fix — **accept**: no change needed.
- G1 retarget mirror Start campaign to `/admin/promotions` — **reject**: the raw `POST /api/of/v2/promotions` (`server.py:5558`, verified) stays reachable and must be guarded or removed anyway; retargeting adds a body adapter (`ofMirrorWrites.ts:90`, verified) and a Growth row per mirror start the plan did not ask for (Out of Scope).
- G2 N1 option B; say Fill costs ~11 % more creates — **accept**: Price check row; Solution states the 11 %.
- G3 count only automatic rows — **accept**: as DA4.
