# Plan review: Full AI Chat

Review of the Full AI Chat set for `plans/full-ai-chat.md`, 2026-11-13. Inputs: the one spec `docs/spec/phase-01-full-ai-shadow-router.md` with its codex review, and a six-hats report on the set (plan Phases 01-06, the spec, ADRs 0032-0036, CONTEXT.md). This review reconciled the report into the spec (a `### Six hats` subsection at the end of its `## Review`) and edited the plan (D32 exceptions, Phase 04 split into 04a/04b, Enrolment moved to Phase 05, Phase 07 and retention lines, Rollout stage mapping), ADR-0035 (Enrolment with selling on), ADR-0033 and ADR-0034 (follow the dropped columns and the NULL Writer), and CONTEXT.md (Writer, Decision row, Enrolment, Arm). Design only: no code, no migration, no network access, no paid call.

## Workstreams

Waves follow each Phase's Depends on in the plan. Phases in the same wave can be built in parallel. Only Phase 01 is specified; every other row is a plan line only.

| Wave | Phase | Spec | Depends on |
|---|---|---|---|
| 0 | 01. Shadow router (PR1) | `docs/spec/phase-01-full-ai-shadow-router.md` | none. Owner D28 approval gates the AE flip, not the merge |
| 1 | 02. Ownership recorded (PR2) | plan line only | 01 |
| 1 | 03. Writers + test chat (PR3) | plan line only | 01; gated by ticket 09 + a v2.3 host pick (D38), see Needs the human |
| 1 | Ledger retention (small PR) | plan line only | 01; due before 2027-02, independent of 03 |
| 2 | 04a. Live on one Creator, selling off (PR4a) | plan line only | 02, 03 |
| 3 | 04b. Stand-down + OF-app yield, selling off (PR4b) | plan line only | 04a |
| 4 | 05. Selling (PR5), Enrolment starts | plan line only | 04b |
| 5 | 06. Tease + sext live (PR6) | plan line only | 05 |
| 5 | 07. Revenue readout (PR7) | plan line only | 05 (and ticket 21's relink before S4 revenue reporting, `.scratch/full-ai-chat/issues/12-rollout.md:79`) |

Rollout stages (plan › Rollout stages by Phase): S0 replay = research, done; S1 = 01; S2 = 03; S3 = 04a/04b on 1 Creator; S4 = 05; S5 = widen, no PR (07 reads it); S6 = 06. Phase 02 and retention carry no stage.

The critical path is 01 → 03 → 04a → 04b → 05. Phase 03 is the long pole: it waits on a host for Euryale v2.3 that does not exist yet (Needs the human).

## Adversary

- **Phase 01** (`phase-01-full-ai-shadow-router.md`): codex, 2026-11-13 (blind and draft calls, `.scratch/full-ai-chat/adv/spec/01-*.out`). 18 accept, 8 partial, 4 reject: 29 codex findings plus the Coordinator line (`docs/prompts` entry, accept). Needs-human: none. Counted from its Review, before this reconcile's `### Six hats` lines (13 lines: 8 accept, 0 partial, 5 reject).

## Six hats

Bullets that touch the Phase 01 spec are reconciled in its `## Review` › `### Six hats`: the Phase 03-05 columns, `brake_reason`, Writer lock-in, story 49's silver sample, `gif_fits`, `GIF_ONLY`, the `OPT_IN_KINDS` guard and catch-up, "380 lines", the 7-day "none", the three Yellow bullets, and D28 / Blue's "ship Phase 01". The lines below cover the bullets about the set. 16 lines: 12 accept, 2 partial, 1 reject, 1 needs-human.

**White**
- Phase 01 is fully specified, 02-06 are one-line plan entries, and every live Phase sits behind Phase 03, which waits on ticket 09 and a v2.3 host pick; the writer test ran on a stand-in: **accept**. Verified: plan Phase 03 line; `.scratch/full-ai-chat/research/11-writers-old-prompts.md:4-5` (v2.2 stand-in); `.scratch/full-ai-chat/issues/09-sexting-prodpath.md:14-15` (host open). The consequence is the Hermes-only question under Needs the human.
- Glossary drift, CONTEXT.md:708 "Euryale l3.1": **accept**. Fixed to "Euryale v2.3 (L3.3-70B; host open, D38)". The same entry's "Each Decision row records its Writer" and the Decision row entry now allow no Writer on a Shadow row, which follows the spec's Writer reframing.
- No phase-to-Rollout-stage mapping: **accept**. Plan › Rollout stages by Phase: S0 replay = research done; S1 = 01; S2 = 03; S3 = 04a/04b on 1 Creator; S4 = 05; S5 = widen (no PR); S6 = 06.
- No inventory of which stood-down Lanes sell today: **accept, as Not yet specified**. The 04b spec needs it; see below.

**Red**
- Phase 04 is where the danger lives and it is the least cut (Green: split it into 04a and 04b): **accept**. Plan rewritten:
  - 04a is the live sender, Last-look, `FULL_AI_CHAT_OFF` and pacing on one Creator. With them, from 12-rollout's PR slice 4, ride Wake, the send marker on rows, the periodic sweep for missed WS events, the owner's account first (D10), and the new `full_ai_live` WATCH with `of_calls_vs_baseline`. Full AI Chat answers only where no other Lane acts, or with the minimal stand-down needed for one owner per Fan; the 04a spec picks which.
  - 04b is the stand-down edits across the Lanes plus OF-app yield. It carries wcfi's per-bubble last-look (12 r3 change 2), the welcome handoff with `_rule_id` and anchor (r3 change 3), and OF-app yield's roughly 1 OF call per AI reply, read on `of_calls_vs_baseline` (12-rollout:78).
  - Both stay selling-off. 04a depends on 02 and 03, 04b on 04a, and 05 on 04b, so every Depends on line stays true.
  - Enrolment goes to 05, not to 04a as the hat proposed (next Black line).
- An unhosted model on the critical path (Green: ship Phase 03 Hermes-only): **needs-human**. D38 picked a 50/50 Hermes / Euryale v2.3 split, and shipping Hermes-only until a host exists changes it. Both positions and the evidence are under Needs the human.

**Black**
- Revenue measure bias: Enrolment starts in 04 with selling off, so the first cohort's 14-day window counts a stretch where treatment sells nothing (Green: start Enrolments at 05): **accept**. Enrolment and its 14-day clock start at the first eligible inbound once the Creator's Full AI Chat sells (Phase 05). During 04a/04b the Arm hash still decides who gets Full AI Chat; only the Enrolment row and the clock wait.
  - Edited: the plan (`ai_enrolments` + migration moved from Phase 04 to Phase 05; the Ledger bullet says "from Phase 05").
  - ADR-0035 now reads "first eligible inbound in live mode with selling on (Shadow and the selling-off stage enrol no one, R8; until then the Arm hash still decides who gets Full AI Chat)".
  - CONTEXT.md's Enrolment entry is edited the same way. Its Arm entry becomes "A Fan's side of the fixed Fan-hash split, on every Decision row and fixed for good by his Enrolment", since Treatment fans now exist before any Enrolment.
  - The spec's story 34, Schema and Out of Scope now name Phase 05.
- D32 leakage: hard-coded numbers in Human yield, the Top spend limit, the Pending tease, the funnel walk rule, pacing and the 7-day "none", with only the last one named: **accept**. The plan's Binding decisions gain "D32 exceptions (owner-set numbers, not Jev questions; revisit with prod data)". Each item's wording was checked against its source:
  - Human yield 1 h: its default (CONTEXT.md › Human yield).
  - Top spend limit $1000 (D8): the glossary term, not "whale gate" (CONTEXT.md › Top spend limit `_Avoid_`). The plan's Phase 05 "Whale gate" is renamed to match.
  - Pending tease 15 min (CONTEXT.md › Pending tease).
  - Pacing: the old `PACE_BUCKETS`, `INLINE_MAX_S` 120 s and `wake_at` (DECISIONS.md D3). CONTEXT.md has no Pacing entry, only Wake.
  - A funnel walk owns the Fan only while it advances (ADR-0036).
  - The 7-day last-purchase "none" (Phase 01 Contracts).

**Green**
- Re-cut: fold 02 into 04: **reject for now**. Recording ownership in Shadow before live is the cheap way to see Lane conflicts before anything sends. Re-decide when 02 is specified (Not yet specified).

**What the set misses**
- No phase builds replay, though ADR-0035 reads router quality from replay ablation and S0 is replay: **partial**. S0 replay was done as research (`.scratch/full-ai-chat/research/10-jev-probe.md`, `research/jevprobe/probe.py`). Replay ablation for router quality reruns `probe.py` on the ledger's `jev_json.state`, which every Phase 01 row keeps. No PR phase is needed; the note is in the plan's Rollout stage mapping.
- No Revenue-per-enrolled-fan readout, the plan's win measure: **accept**. New plan line, Phase 07: "Revenue readout: $ per enrolled fan, 14 d, net of refunds/chargebacks, treatment vs holdout, on the Full AI page + a WATCH/report query; depends on 05."
- The `asks_subject` / `asks_format` Choices are handed to the selling Phases but not named in the plan's Phase 05 line: **accept**. They are added to Phase 05, since they ride in the same Jev request and pick the vault item. The spec's Out of Scope now points at Phase 05.
- The 90-day retention ticket: **accept**. New plan line: "JSON nulling at 90 d for terminal rows (ADR-0034), own small PR, due before 2027-02; independent of 03." The spec's Out of Scope points at it.
- Tease Noul measured in Shadow before 06: **partial**. No new phase. The plan's Phase 06 line now says that, once written, the tease question can ride in the shadow call to be measured before 06 goes live.

**Blue**
- Before specifying 02-06, revise the plan (D32 exceptions, replay and revenue-readout phases, CONTEXT.md:708, ask about Hermes-only), then re-cut 04 and decide when Enrolment starts: **accept**. All of it is done in this review except two items: replay is partial (no PR phase, see above), and Hermes-only is a question for the owner (Needs the human). No 04 spec existed, so none needed rewriting.

**Recommendation**
- Ship Phase 01 now, and re-plan 02-06 first (Hermes-only Phase 03, split 04, Enrolment at selling, explicit D32 exceptions): **accept**. Phase 01 ships as specified minus the cut columns (spec › Six hats). The re-plan is in the plan, except Hermes-only, which waits on the owner.

## Cut (YAGNI)

The spec's Out of Scope, deduplicated, plus what this review cut. Each line gives where the item went, or why it was dropped.

- **`complaint.py` classify.** D32 makes complaints a Router question (`complains_now`).
- **Lane ownership** (`who_owns`, its loader, recorded per row). Phase 02.
- **Pending tease fold, the tease_next Route and its Noul.** No tease question exists yet and the route is off (R7). Phase 06 owns it; Shadow uses the Pending offer stand-in.
- **The `asks_subject` / `asks_format` Choices.** Nothing in Shadow picks media. They go to Phase 05.
- **Writers, prompts, the GIF sticker block, Test chat, mode test, `full_ai_config_json`.** Phase 03.
- **The Writer split** (`writer_of`, `WRITERS`, the writer salt; cut here). Shadow writes no reply, so no Writer exists for its rows: `writer_model` is NULL. Phase 03 adds the split with its own salt, so a host or model swap bumps it.
- **The intensity post-check.** Phase 06.
- **Live sending:** `sender_for`, Last-look, Wake, pacing, the send marker, `FULL_AI_CHAT_OFF` and the periodic sweep for missed WS events. Phase 04a.
- **Stand-down edits, the Welcome handoff and OF-app yield.** Phase 04b.
- **The send, offer and outcome columns of `ai_decisions` and the partial UNIQUE on `offer_message_id`** (cut here). Shadow never writes them. Each lands, nullable, with the Phase that first writes it (03-05), through init_db's additive catch-up (`service/db/engine.py:390-430`) and that Phase's alembic revision.
- **`brake_reason`** (cut here, never to be built). "Brakes" is a retired word (CONTEXT.md › Send-correctness rules), and nothing writes a brake.
- **Offer, Free item, settle, the purchase join, and `full_ai_chat` in `_SELLING_KINDS`.** Phase 05.
- **`ai_enrolments` and the Enrolment.** Phase 05, once the Creator's Full AI Chat sells (moved from 04 here). Shadow and the selling-off Phases enrol no one (R8, ADR-0035).
- **Retention.** Nulling terminal JSON at 90 days is its own small PR, due before 2027-02. Deleting test rows at 7 days lands with Test chat (Phase 03).
- **Silver LLM label code (D36).** Labelling is offline reading of rows. The 48 h sample is a manual Acceptance line, with no Relay code.
- **Jev answers per row on the page.** YAGNI: SQL reads `jev_json`.
- **Draining several Fans' jobs per run.** A job catches up only its own Fan. Lag is measured from rows first.
- **A slop run.** Slop is opt-in (repo CLAUDE.md), and this run is unattended, so no answer means no slop.
- **Outcome and revenue readings.** Shadow observes no purchase (ADR-0033). They start in the live Rollout stages; the revenue readout is Phase 07.

## Not yet specified

- Phases 02, 03, 04a, 04b, 05, 06, 07 and Ledger retention are plan lines only. None has a spec.
- **Fold 02 into 04: rejected for now.** Recording ownership in Shadow before live is the cheap way to see Lane conflicts. Re-decide when 02 is specified.
- **Which stood-down Lanes sell today.** The 04b spec needs this inventory. Known so far: wcfi sends a closing PPV (12 r3 change 5, `welcome_chatter_for_info.py:1141-1168`). Not yet checked: Auto-reply and the Lanes W7's `_classify` dispatches to.
- **04a's one-owner choice.** Full AI Chat either answers only where no other Lane acts, or takes the minimal stand-down needed for one owner per Fan. The 04a spec picks.
- **Phase 07's join quality.** Ticket 21's relink must land before S4 revenue reporting (12-rollout:79).
- **The Writer split's salt and ids** (Phase 03), including whether Euryale joins later behind a salt bump (Needs the human).

## Open questions

Every ASSUMPTION: line in the Phase 01 spec (Further Notes), sharpest first. Each one says what falls if it is wrong.

1. **Pending offer stand-in with no age limit** (the probe used 24 h). If wrong, `says_yes_to_offer` fires on offers days old and inflates sell_now. It also breaks the "state mirrors the probe" premise of item 4, which the thresholds rest on.
2. **The hook dedups on a pending job naming the Fan; the catch-up is what makes that safe.** If wrong, Turn ends are lost between a claim and the run. S1 coverage drops under 95 % and the hook needs redesign.
3. **The Turn's context is cut at the newest outbound of any sender, mass rows included.** If wrong, Turns are cut by mass rows he never saw. The Router reads too little and the route mix is skewed.
4. **The Jev state's wording (thread `when`, `ppv` notes, last purchase with its 7-day "none") mirrors the probe.** If wrong (the owner's D28 review changes the state, or a later Phase sends the real age), the measured thresholds no longer apply and need re-measuring.
5. **If `_dispatch_inbound` raises, the hook does not run.** If wrong, `w7_dispatch_failed` lines line up with uncovered Turns and the hook must move out of W7's error flow.
6. **`full_ai_shadow` reads coverage and failure share only at n ≥ 20, skips Turn ends under 5 min, and counts from the rule's `created_at`** (all [g]). If wrong, the S1 gates false-watch or miss. They are retuned from the first 48 h of S1.
7. **Each run's Anchor is its last inbound row, read at decide time.** If wrong (Phase 04a's Last-look needs the payload's anchor as the key), `trigger_key` semantics change under existing rows.
8. **Only the decision block is created now; later columns land through init_db's catch-up and their Phase's revision.** If wrong (a later column must be NOT NULL with no server default, which the catch-up skips, `engine.py:409`), that Phase needs a table rebuild.
9. **A catch-up asks Jev once per undecided run, with no cap.** If wrong (one run's stats show more than about 20 rows), a recovering dead session spikes Jev calls and lag.
10. **A GIF-only message reads `[sent a GIF]`** (new words). If wrong, GIF Turns are misrouted or the owner rewords them in D28. The wording edit then bumps `question_version`.
11. **Shadow writes rows for both Arms.** If wrong (the owner wants holdout Fans unread before live), the hook must filter on `arm_of` and the coverage denominator changes.
12. **`writer_model` is NULL on Shadow rows and PR1 has no Writer helper.** If wrong (replay needs a planned Writer per row), it can be recomputed from Phase 03's pure split; no column is lost.
13. **Shadow rows are `status = planned` and terminal by their mode.** If wrong (Phase 04a's status machine needs a separate value), Shadow rows need a new status value.
14. **Heat is the `intensity` Score rounded to the nearest level.** If wrong (Phase 03's Writers read Heat from the probabilities), Heat on existing rows is not what the Writers expect.
15. **Coverage starts at the enabled rule's `created_at`.** If wrong (an Off/On spell gives a false watch), the switch needs an enable stamp.
16. **`says_yes_to_offer` is asked every Turn and counted only with a Pending offer.** If wrong (the owner wants it dropped when there is no offer), the request shape depends on the offer and `question_version` must cover both shapes.
17. **`full_ai_chat` in `OPT_IN_KINDS` maps to a page outside `OPT_IN_PAGES`, so only the owner flips Shadow.** If wrong (a chatter role should flip it), the page joins `OPT_IN_PAGES` and drops its nav `notOptIn`.
18. **`jev_json` keeps the exact Jev state, about 2-4 KB a row.** If wrong (row size matters before retention lands), retention moves ahead of 2027-02 or the state is trimmed.
19. **The Arm salt, `SALT_VER` 1 and `HOLDOUT_PCT` 20 are code constants.** If wrong (the owner wants the salt out of the public tree), public-sync must strip it, or it moves to env.
20. **`QUESTION_VERSION` is a digest computed at import and pinned in the pure test.** If wrong (the owner prefers named versions such as "r7"), the pin becomes a name.
21. **The catalog entry is `surface: internal`, `recurring: False`, `cadence_default_s: 86400`.** If wrong (Phase 04a gives the interval a sweep), the cadence must shorten.
22. **The switch is the house `HeaderSwitch` with a Shadow/Off pill, and the page reads mode shadow only.** If wrong (Phase 03 or 04a adds a Mode choice), the switch becomes a Mode picker.

## Needs the human

**Set (six hats Red + Green): may Phase 03 ship Hermes-only until a Euryale v2.3 host exists?**

- **For.** It takes the unhosted model off the critical path: 04a, 04b, 05 and 06 all wait on 03, and 03 waits on ticket 09 plus a v2.3 host pick (plan › Phase 03).
  - In the writer test, Hermes was OK on every route: 3 of 68 chat-route replies had a defect the fan would see, p50 0.75 s, about $0.00065 a reply [m] (`.scratch/full-ai-chat/research/11-writers-old-prompts.md` § 0).
  - The Writer split is data with its own salt (spec story 23), so Euryale can join later behind a salt bump without moving any Arm.
- **Against.**
  - The owner picked a 50/50 split of Hermes-4-405b and Euryale v2.3 (DECISIONS.md D38; plan Goal), and he alone judges writer quality (D39). Hermes-only overrides his split for every Phase it lasts.
  - v2.3 never ran on the old prompts. The test ran v2.2 as a stand-in, which was OK on chat and sext, not on caption, make_right or dare: 9 of 68 replies had visible defects, p50 1.21 s, about $0.00108 a reply. It was also the hottest sext match [m] (research/11 § 0). So the case for v2.3 is the owner's bake-off pick (D38, `research/bakeoff/nano/compare.html`), not a measurement on the old prompts.
- **Host state** (`.scratch/full-ai-chat/issues/09-sexting-prodpath.md:14-15`; DECISIONS.md D38):
  - v2.3 is not on OpenRouter.
  - NanoGPT is for tests only: 4-7 s, one 429, a reseller with unchecked privacy.
  - Featherless serves v2.3 directly and is the prod candidate, at about $0.0008 a reply [i]. Its key and privacy check are pending.
- **What would settle it:** the owner's yes or no, or a Featherless key with a privacy OK followed by a v2.3 rerun of research/11 on the old prompts.

**Phase 01 spec:** none.

Standing owner gate (not a finding): D28 approval of `.scratch/full-ai-chat/OWNER-REVIEW-router.md` gates the AE flip of Phase 01, not its merge.
