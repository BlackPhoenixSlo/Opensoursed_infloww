# Caption writer for posts and one-off masses

Type: grilling
Status: answered (build, 2026-11-14; owner may veto)
Blocked by: 04

Reuse which existing prompt wording (`docs/prompts/README.md`), does post/mass text go through the `finalize_draft` chain, model choice.

## Answer

**No separate Caption writer: the Ultra planning model writes post/mass text inline in `submit_plan`, guided by a caption block reused verbatim from old fastt wording, and the text passes the ticket-13 chain at plan submit.**

- **Why no writer (code judo):** ticket 13 already runs the chain at plan submit and the executor sends approved text byte-for-byte. A second LLM call per text adds spend and a step whose output must re-enter the plan anyway. MCP clients write their own text (ticket 05), so a server writer would cover only in-app Ultra.
- **Today:** this repo has NO mass/post caption prompt. `docs/prompts/README.md` has only `SELL_CAPTION_EXAMPLE` (NEW-17, `service/_voice.py:660`) and the per-fan PPV rewrites (NEW-67/68). `suggested_caption` is written only by operator overrides (`service/vault_ai_api.py:1331,1363`). `MASS_CAPTION_BRIEF` / `_copy_system_prompt` exist only in `docs/prompts/old/other.md`.
- **Reused wording (verbatim, appended to the Ultra planner system prompt):**
  - OLD-OTH-26 `_CAPTION_GROUND_TRUTH` ("never name a colour, garment, place, body part or act that is not in the facts above… Never claim a time, a deadline or a limited window.") (`docs/prompts/old/other.md:1538`).
  - OLD-OTH-26 `_CAPTION_MASS_AUDIENCE` ("this one line goes to hundreds of people at once…").
  - OLD-OTH-26 "house" style: "ONE {tone} line <= 110 chars. At most ONE emoji." with tone = teasing (`{tone}` filled from OLD-OTH-25 "1 teasing line, no hashtags/@").
  - Not OLD-OTH-43 `MASS_CAPTION_BRIEF` whole: it is a PPV/locked seven-day build plan (`other.md:2642`); only "lowercase, no quotes, no hashtags" fits a free mass, and it is reused verbatim as one line.
- **Facts the text may use:** the theme words + the `vault_search` descriptions the planner already read. Picks are made after the text is pinned (ticket 09), so ground truth = theme only.
- **Chain:** yes, ticket 13 stages at submit (refuse on narration/off-platform/banned/empty; transform word restriction + emoji strip). Not the per-fan stages (`finalize_draft` 1–4 partly, `shape_parts`, typos, typing hold: `docs/prompts/post-processing.md`). A refusal goes back to the planner as a validation error; it rewrites, capped by the planner's 25 turns.
- **Model:** the planner's own model (DeepSeek flash, house default like `help_assistant_do`, `service/assistant_draft.py:33,121`), billed to the owner with `account_id=None` like Ultra planning (ticket 06).
- **New things:** one prompt block (constant beside the Ultra planner prompt) + one `docs/prompts/README.md` entry (next free NEW-1xx) quoting it, where/when/why, in the same PR.

ASSUMPTION: one teasing line ≤110 chars fits posts and free masses. Overturned if owner wants longer post copy → raise the cap in the same block, no new prompt.
ASSUMPTION: flash writes acceptable captions with the old rules. Overturned if owner vetoes texts on the plan card often → add a dedicated writer call (OLD-OTH-25 shape) behind the same chain.
ASSUMPTION: the creator's voice block is not needed for a mass line. Overturned if owner wants masses in each creator's voice → prepend `load_voice_blocks(account_id)` (exists) per text.

Deferred: caption-library reuse; per-item captions written after the pick; PPV/locked mass copy.

Build: step 5 (planner prompt block + README entry). Chain itself: step 4.
