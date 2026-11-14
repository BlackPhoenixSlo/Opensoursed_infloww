# Plan review: Full AI Chat, Phase 03d

Review of `.scratch/full-ai-chat/GOAL-03d.md` (run fa4) and its one spec, `docs/spec/phase-03d-full-ai-ask-price-spacing-bundle.md`, 2026-11-14. Inputs: the spec with its codex review (B1-B21, D1-D5), a six-hats report on plan and spec, and the coordinator's rulings. Bullets that touch the spec are reconciled in its `## Review` › `### Six hats (2026-11-14)`. This file holds the set-level lines.

## Workstreams

One Phase, three code groups and the owner proof. Groups in one wave build in parallel (two workers). Merge order R, then P, then B.

| Wave | Group | Spec | Depends on |
|---|---|---|---|
| 1 | R. Ask cut-off + Spacing (ticket 59) | `docs/spec/phase-03d-full-ai-ask-price-spacing-bundle.md` (R) | origin/main 9718d06e3 (#634, #637, #646) |
| 1 | P. Price signals (ticket 60) | same spec (P) | origin/main 9718d06e3 (#634 price Jev, `purchases_of`) |
| 2 | B. Bundle (ticket 61) | same spec (B) | P (the P×B test reads the price Jev's state; same worker, after 60). Rebases on R for the config lines |
| 3 | Owner proof on the local stack (ticket 62, manual, coordinator) | same spec, `# manual:` Acceptance lines | R, P, B merged to main |

Shared files are additive only and in separate functions (spec › Owns › Shared). The config files take one added line per group (R `sell_spacing`, B `sell_bundle`).

## Adversary

codex (gpt, reasoning high, read-only, blind + draft calls), 2026-11-14: 16 accept · 2 partial · 8 reject after the coordinator's rulings (B2 partial → reject, B5 partial → accept); this six-hats pass: 12 accept · 4 partial · 3 reject (17 lines in the spec, 2 here). Needs-human: none.

## Six hats

**White**
- White 1 "the owner's text only partly backs the numbers; the Bundle is the coordinator's reading of a typo line ending in 'sometimes'; no your-host.example.com number for bundle size against buy rate": **accept** (no change). True as stated. Item 1 (0.65) and item 3 (3 lines, 3 unasked) are owner text and bind; the Bundle reading is the sharpest ASSUMPTION (Open question 1) and the owner judges it in his own Test chat. No bundle-size data exists to cite, so none is invented.

**Recommendation** "execute R then P after fixing the line count and the two price drifts; ship B with default 'shoot' and mates raised to 4": **partial**. R then P: taken, and the price drifts are fixed (the orchestrator revised PRICE: first buy $15 to $35, never under 1.25x). The line-count change is rejected (in the Test chat every row holds exactly one of his lines; spec › Contracts). B's default stays "fill" (test-Mode flag precedent #634/#637/#646, rung 3; no state touched).

## Cut (YAGNI)

The spec's Out of Scope, each with its reason.

- **Any Shadow or live change, including the Ask cut-off in Shadow.** The owner says Shadow keeps 0.7; Shadow's request, thresholds and Writer prompt stay byte-identical (plan A).
- **A Route-table gate or code cap for Spacing.** ADR 0032: every behavioural "if" is a Jev question. Kept only as the fallback if the proof shows Jev ignoring the counts.
- **Page controls for the two flags.** Plan A: JSON-only; the page is at its control limit.
- **Bundles of videos, or video plus photos.** The owner's line is about photos after a one-photo Offer; a video still sells alone.
- **A $51 price floor for repeat buyers.** The 1.25x to 2x step rule wins where the two targets disagree (Open question 4).
- **Spacing across sessions or days beyond the 120-minute Sitting.** The your-host.example.com analysis used 120 minutes; a Test chat is normally one Sitting.
- **Deploy to AE or the public repo, and the WATCH.md line.** No prod ship in this Phase; test Mode only.
- **Slop runs.** No volume or concurrency path; slop is opt-in and the plan says no slop.
- **Owner sign-off on the DRAFT wording before Shadow or live.** A later Phase (04a/05); the wording ships DRAFT, test Mode only.

## Not yet specified

None. Every plan line (items 1-4, Docs, Proof, Evidence) maps to the spec's groups R, P, B and its `# manual:` Acceptance lines.

## Open questions

Every ASSUMPTION in the spec, sharpest first. Each says what falls if it is wrong.

1. **Bundle means photos per Offer, default "fill" in test Mode.** If the owner meant pieces per Sitting, B is turned to "shoot" or reverted (its key goes with it), and item 3's numbers change.
2. **Spacing is Jev wording, not a Route-table gate (ADR 0032).** If the proof shows Jev offering unasked inside 3 lines or a 4th Unasked piece, a state exception like the Pending tease is added, and the owner's rule is not met until then.
3. **The owner's "never bought $11 to $35" is written as a first buy at $15 to $35; $10 only for one or two soft photos or after a no.** If the owner wants $10 as a normal first price, the `$10` and `$20` criteria and the PRICE first-buy line are reworded and the price version moves again.
4. **The step rule (1.25x to 2x) wins over "$51 to $75" where they disagree.** If a buyer must never see under $51, the PRICE wording gains a floor and story 8's check changes.
5. **An Unasked piece takes the lower of two fitting prices.** If a measured unasked price says otherwise, the `he_asked` sentence of PRICE is reworded.
6. **No fill for subject "anything".** If any mix is fine, generic unasked offers stay at shoot-only bundles that could have been 3 photos.
7. **The ladder bounds the targets ($5 rounding, $150 cap).** If the owner wants a wider ladder, the 1.25x step above $120 last paid is unmet until the ladder grows.
8. **A failed price Jev keeps the vault's list price.** If a failure must fall back to a target price, `_price`'s failure path changes and a test is added.
9. **The 120-minute gap is also measured between the last row and `now`.** If the Sitting must keep its last row, a return after 2 hours still counts old Pieces and she stays quiet.
10. **A haggle re-offer row is an asked Piece and resets the line count.** If a re-priced piece is the same piece, the fold skips haggle rows for the reset.
11. **His lines count the "in" line of failed and dropped rows.** If only answered lines count, the fold skips those rows and she waits longer after a failure.
12. **The spacing keys are added whenever `sell_spacing` is on, even with `draft_questions` off.** If unused state must stay out of the request, `fetch` also checks `draft_questions` / `sext_scene`.
13. **The counts are JSON ints and "no piece yet" is a string.** If Jev reads ints worse than words in the proof, the fold returns words and the digest moves.
14. **B1 needs the `test_full_ai_decide.py` invariants rewritten (a test cut-off can only lower Shadow's).** If the owner wants a test value above 0.7, the union becomes a replace.
15. **Each group adds its own config key; B rebases on R.** If the config-file conflict costs more than the clean drop saves, one group owns both keys again.
16. **`reply_json.price` records only `he_asked` and `bought_before`.** If the proof needs the whole price state, `_price` saves it and the row grows.
17. **The fill does not check near-dupe `prints`.** If two near-identical photos from different shoots show up in one Bundle, the fill gains a prints check.
18. **The labels are "Spacing" and "Photo bundle".** Owner wording replaces them; no behaviour falls.
19. **The Ask cut-off gets no new prompt id; the NEW-106 thresholds line records it.** If the docs rule counts thresholds as prompts, a NEW entry is added.

## Needs the human

None as findings. The owner judges in his own Test chat, after the merge (ticket 62): the Bundle reading (Open question 1), whether Jev holds the Spacing counts (Open question 2), and the $15 first-buy wording (Open question 3). DRAFT wording sign-off before Shadow or live stays a later Phase (04a/05).
