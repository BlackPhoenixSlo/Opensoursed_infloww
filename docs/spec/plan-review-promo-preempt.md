# Plan review: Pre-emptive re-create for Keep promos running, Phase 01

Reviews `goal_promo_preempt.txt` (one Phase) and its one spec, `docs/spec/phase-01-promo-preempt.md`, on 2026-11-19.

Inputs: codex blind + draft review (B1–B10, D1–D25, N1); devils-advocate (DA1–DA12, `.scratch/promo-preempt/devils-advocate.md`); six-hats (`.scratch/promo-preempt/six-hats.md`); coordinator rulings (N1 = option B; one Phase, two slices; Kept-row count and WATCH.md are the human's).

Spec-level bullets are reconciled in the spec's `## Review`. This file holds the set-level lines.

## Workstreams

One Phase, one spec, two slices. A ships first and is deployable alone. B builds on A and is dark until MEASURE a + d pass.

| Wave | Phase | Spec | Depends on |
|---|---|---|---|
| 1 | 01-A Safeguards on the After-end path: reservation/settle/reconcile, budget (automatic only), back-off, turn-offs, breaker, Host fence + boot notice + `promo_keep_fenced` WATCH check, cached-price hold, Free-trial limit, Takeover, atomic Re-check, Repoke opt-in, raw create/finish/delete routes, card reasons, migration 0126 | `docs/spec/phase-01-promo-preempt.md` (A) | PR #850 (7df39f6aa), migration 0125 |
| 2 | 01-B Pre-emption: Fill/Timed in `promo_keep_decide`, Trusted count, skew, toast gate, second tick, waiting line, `PROMO_PREEMPT_ENABLED` | same spec (B) | A merged; switch flip needs MEASURE a + d (human) |

## Adversary

- `docs/spec/phase-01-promo-preempt.md`
  - codex (gpt via `codex exec`, reasoning high, blind + draft): 22 accept · 11 partial · 2 reject. N1 needs-human → resolved (rung 2, plan GOAL + coordinator ruling: option B).
  - devils-advocate: 10 accept · 2 partial · 0 reject · 0 needs-human.
  - six-hats: 12 accept · 3 partial · 1 reject · 0 needs-human (16 bullets: 9 in the spec, 7 here).
  - Needs-human: none.

## Six hats

- **White 1** — split Phase 01 into PR A safeguards, PR B pre-emption — **accept** as two slices of one spec (coordinator ruling: no second spec file). Every story, schema item, test and acceptance line is tagged A or B.
- **Red 1** — too much machinery for one diff — **partial**: the slice split halves each review; the parts stay because each closes a plan must-not or a measured #850 gap (spec Problem). Nothing was cut for size alone; the prune and the mirror retarget were cut (see Cut).
- **White 3** — ADRs 0039/0040 and CONTEXT Trusted count contradict the spec — **accept**, done in this pass, not left as build work: ADR-0039 (cached price, slices, ~11 %), ADR-0040 (unique-candidate adopt, never-sent → failed, sent + no match → lost + off, Employee clear, automatic-only budget, raw route), ADR-0041 (per-box id, boot notice, re-stamp, WATCH check); CONTEXT Trusted count, Create reservation, Create budget, Zero-claim breaker, Host fence, Poke.
- **Yellow 1** — A alone makes #850 safe to deploy — **accept**: A is self-contained and listed as the deploy gate (plan line 1).
- **Blue (DA list)** — DA 2/3/4/6/8 open, 5/9/10/11 partly — **accept**, folded: see the spec's `devils-advocate 2026-11-19` lines.
- **Blue (next step)** — rewrite as A then B, fold fixes, sync ADRs, then send N1 to the owner — **partial**: all taken except sending N1: the coordinator resolved it as option B (plan GOAL is a constraint, rung 2).
- **Recommendation** — keep Phase 01, ship as A then B after DA 2/3/4/6/8 — **accept**.

## Cut (YAGNI)

The spec's Out of Scope, deduplicated:
- Agent-run live OF tests, MEASURE runs, host env setup, restamp, Kept-row count, deploy, WATCH.md writes: human only (plan + floor 2).
- Slop scenario / gate: slop is opt-in (owner rule); the guarded-stack proof covers it.
- Fencing manual creates: ADR-0041 ASSUMPTION; the reservation still serialises them.
- OF idempotency key: none exists (inferred).
- Auto re-create at a new price; any OF read for the price: plan #11 + GOAL.
- Auto-finishing a second live promo when (a)=no: would end promos Inflowwww does not own.
- Free trial links (`/trials`); `max_reactivations` changes; reservation prune.
- Inducing a failed-create order on live OF; detecting OF.com-side edits; changing `_proxy_retry`.
- Timed `failed` settle of open rows (DA 1 fix): a negative read proves nothing.
- Mirror Start campaign retarget (six-hats Green 1): raw route still needs the guard.
- Breaker exemption for slow 0-claim promos: plan defines the breaker on "0 new claims".

## Not yet specified

Each plan line checked against the spec:
- L1 ships before deploy → Slice A gate, Workstreams. L3 sanitised id → "the owner test account" throughout.
- GOAL (L6): 90 % Fill, Timed, request counts → B Threshold/Trusted/Timed rows; Contracts + Acceptance read asserts (A ≤, `/users/me` == #850; B strict-less on `toast-far`).
- Fixed decisions L9–L13 → stories 3/4, threshold cap ≥ 10, story 5, story 6, MEASURE section.
- Must-not L16–L29 → must-not table rows 1–14, each with named tests and a proof scenario.
- Safeguards L32–L41 → Safeguards table (reservation incl. manual + raw; budget + shoutout ASSUMPTION; back-off + Retry-After + turn-offs; breaker; Trusted count; Timed on `finishedAt`; pre-POST re-read; Host fence; Free-trial; Takeover + notices).
- MEASURE L44–L47 → MEASURE a–d with procedure + pass condition (+ e, from N1).
- Acceptance L50–L53 → Acceptance blocks A/B + manual screenshot, DB-row and re-review lines.
- CONTEXT files L56 → all in Owns.

Gaps: none. Build-time detail only: the fake OF's internal API (only its `counts.json` keys and scenario names are fixed by the spec).

## Open questions

Every ASSUMPTION in the spec, sharpest first, with what falls if wrong.
1. Price only from the ≤ 6 h cache (option B). Wrong → a paid→paid price change on OnlyFans is re-made at the old percent for up to 6 h (longer while cold); must-not 11 is only partly met.
2. Unset `PROMO_CREATE_HOST_ID` = no automatic create, After-end included. Wrong → every Deployment's re-creates stop on deploy day until the env is set; the boot notice + WATCH check only make it visible.
3. First 403 transient; off only on a second 403/429 or "Access denied". Wrong → a permanent 403 costs one extra create attempt per back-off; or, the other way, repeated proxy 403s turn Keep running off.
4. 5xx/timeout/connection error after send = unknown → lost + off at 15 min. Wrong → a blip OF never acted on switches Keep running off and needs a re-tick.
5. Price mismatch holds, never turns off. Wrong (MEASURE e = yes and peeks primed with a promo live) → false holds until re-tick; if the owner wanted untick, a held campaign looks "on" but is idle.
6. Existing Kept campaigns stay fenced until re-ticked. Wrong → any deployed Kept campaign silently stops re-creating until someone re-ticks (count is the human's read below).
7. Cold price cache lets After-end proceed. Wrong → a re-create can run on an unchecked price after a price change.
8. Failover re-stamp is human-run. Wrong → after an unattended failover, re-creates stop until the restamp runs.
9. Captcha detected by "captcha" in the body (guess). Wrong → a captcha is treated as a 4xx (still off) or as unknown/failed with back-off.
10. Reconcile match on terms + createdAt + pre-read ids. Wrong → two identical hand-made promos in the window leave the row open → lost + off.
11. Budget 3/h, 8/day. Wrong → shoutouts wait (too low) or bugs cost more creates (too high).
12. No shoutout exception. Wrong → a 4th fill in an hour leaves a gap.
13. Breaker N=3, `NOT_LISTED_S=600`, `UNKNOWN_OFF_S=900`, `SETTLE_GRACE_S=600`. Wrong (list lag > 10 min) → false breaker trips / lost rows.
14. `TIMED_LEAD_S=120`, skew ≤ 30 s. Wrong → Timed fires late (gap) or waits on "clock".
15. Session-dead create keeps Keep running on. Wrong → owner expected a re-tick after re-login.
16. Cap 0 = "under 10". Wrong → no Timed on unlimited promos the owner wanted.
17. One switch gates Fill and Timed. Wrong → Timed waits for MEASURE a like Fill.
18. Fence check before any OF read. Wrong → fenced stacks show no live Claims on the card.
19. Toast gate 600 s staleness. Wrong → reads exceed #850 (caught by `toast-100`/`toast-far`).
20. Notice kind owner-switchable. Wrong → plan's "notified on every automatic create" not met when switched off (card still shows).
21. Free-trial limit default 3, max 10. Wrong → owner number differs (copy + validation change).
22. One migration in A carries B's columns. Wrong → reviewer wants a 0127; columns stay inert meanwhile.
23. No reservation prune. Wrong → table grows past 100k rows.
24. MEASURE (a) failure order stays unmeasured. Wrong → if OF keeps the old promo on a failed create, the designed worst case is just pessimistic.
25. Proof scripts under `scripts/demo-shots/`. Wrong → owner wants them in `slop/scenarios/`.
26. ADR-0041: manual creates not fenced. Wrong → a copied stack's operator can still create on OF by hand.

## Needs the human

All read-only or on the owner test account; no agent runs them.
- **Kept-row count per Deployment** (pre-deploy A). On each box: `docker exec <ae-relay|openinflowwww-relay> python -c "import sqlite3;c=sqlite3.connect('file:/app/service/data/chatterly.db?mode=ro',uri=True);print(c.execute('select account_id,id,name,discount_percent from promo_campaigns where auto_reactivate=1').fetchall())"`. Each row = a Creator whose re-create stops until re-ticked (or restamped) after A deploys.
- **`PROMO_CREATE_HOST_ID` per box** (pre-deploy A): one unique value per live box, never on test/shadow/demo or a failover twin. In the compose-level `.env` beside `docker-compose.yml` (not `service/.env`, `docker-compose.yml:186-189`): `printf 'PROMO_CREATE_HOST_ID=%s\n' <unique-box-id> >> .env && docker compose up -d --no-deps <relay service>`. Then re-tick each Kept campaign, or `docker exec <relay> python service/scripts/promo_keep_restamp.py`. After deploy append to WATCH.md: `- promo-keep-fence | added <date> | expires +3d | promo_keep_fenced | <PR url>`.
- **MEASURE a** (B switch): spec MEASURE row a, procedure + pass condition; record in ADR-0039.
- **MEASURE b** (efficiency): spec row b; compare relay log `grep -i subscribed` lines against the Claims delta over one hour.
- **MEASURE c** (Timed): spec row c; read `finished_at` from Growth's promo list (`GET /admin/promotions`) for a cap-10, 1-day promo.
- **MEASURE d** (B switch): spec row d; B's first raw `claimsCount`, then list reads 60 s apart against toast times.
- **MEASURE e** (A price): spec row e; `GET /api/of/v2/users/me` → `subscribePrice` with no promo live, then with a 50 % promo live. Until recorded, every mismatch holds.
- Flip `PROMO_PREEMPT_ENABLED` only when a and d pass.
