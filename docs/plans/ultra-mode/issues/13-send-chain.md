# Send chain for tool-written text

Type: grilling
Status: answered (build, Fable F2 2026-11-13; owner may veto)
Blocked by: 04

`mass_send`, `post_create` and automation rules can carry text the model wrote. CLAUDE.md requires model replies to OF to run `finalize_draft → shape_parts → apply_typo_throttle → hold_with_typing`, but the routes forward text raw (`service/server.py:3899-3918`, `:5854-5868`). Where does the chain run for tool calls: inside `toolbox.call` for send tools, as a route flag (`model_written: true`), or in the Caption writer? Which stages fit a mass/post (no typing hold)? Release blocker for Ultra and MCP sends.

## Answer

Decided by the build (Fable F2, 2026-11-13), not the owner. ASSUMPTION: owner may veto; would overturn = owner wants the chain at send time.

- **Where:** at plan submit (`propose_plan` / in-app plan validation), not inside `toolbox.call`, not a route flag, not the Caption writer. The stored plan, the plan card and its sha256 hold the post-chain text; the executor sends it byte-for-byte. Why: ticket 06 shows the full text verbatim and runs nothing after OK, so a chain after OK would change approved text; a route flag is caller opt-in on routes the human composer shares; MCP clients write their own text and would skip the Caption writer.
- **`toolbox.call` refuses `effect="send"`** unless the executor calls it with a plan step.
- **`Tool` fields frozen in step 2:** `model_text: tuple[str, ...] = ()` (arg paths carrying OF-bound text), `text_kind: Literal["mass", "post"] | None = None`. Drift test: every `send` tool with a string text arg declares both (vacuous until step 4).
- **Stages for mass/post (one body, no fan):**
  - Refuse the plan (validation error back to the planner, never a rewrite): narration strip hit, `scan_offplatform` hit, banned words (block mode), empty text.
  - Transform: `apply_word_restriction`; emoji strip when the account flag is on.
  - Skip: bubble split, 600-char cap, echo, lead dedupe, consistency, non-native style, typos, typing hold (per-fan chat mechanics).
  - One shared helper wraps these (no re-implementation); record the stage list in `docs/prompts/post-processing.md` in step 4. `_bubbles._cap_merge` keeps overflow (merges, never drops), so `max_bubbles=1` is safe if reused.
- **Step 2 risk carried into step 3:** silent arg loss (routes drop bad ids and return 2xx). Every write tool checks the response echoes what was asked, else `error`; names resolve by exact unique match only, one negative test per tool.
