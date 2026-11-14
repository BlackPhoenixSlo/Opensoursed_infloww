# Ultra loop: where it runs and its state machine

Type: grilling
Status: resolved
Blocked by: 04

Server-side job (SSE progress) vs browser-driven loop like Do mode's runner. Plan → one OK → run → report; "needs you" cards (OTP, 5-min login notice); cancel; tool-call support in `llm_client` for DeepSeek + Anthropic; step/cost caps; resumability.

## Answer

**Plan-then-execute, not a free tool loop.** The model loops **only while planning** and uses read tools. The owner OKs an exact step list with every argument pinned. After OK, the server runs those steps **deterministically, with no LLM**. Rung 2 ("AI restates the plan → OK → no more confirms, sends go right away") + rung 5. This came from the Fable advisor's reframing. Codex P0: grants of tool + Creator + count left audience, price, media and text free after OK (`service/automations/send_mass_message.py:35-47`), so they are dropped.

**Planning**
- `POST /admin/ultra/plans {request}`. The planning loop gets read tools only; no writes of any kind.
- It ends with `submit_plan {summary, steps:[{id, tool, args}]}`. `args` are full, and may reference earlier step outputs as `"$<step>.<field>"` (for example, the new folder id).
- The server validates each step with that tool's pydantic model (Toolbox) and resolves the Creator binding. It then stores the plan and its sha256.
- The card is rendered **from the steps**, not from the summary. It shows every send's audience, price, media count and the **full text verbatim**, plus every write. OK = `POST …/{id}/ok` with that hash. Since injected fan text can only act during planning, whatever it changed is shown on the card.
- Caps for planning: 25 turns, 100¢ (billed to the owner with `account_id=None`, help-bot precedent `assistant_api.py:817`). Refuse to start when the owner is over the daily cap. ASSUMPTION: these numbers; ticket 07 refines them.

**Executing** — `service/ultra_run.py` (in-memory asyncio task; precedent `remote_login.py:315`, `vault_ai_vision.py:1036`) + `service/ultra_decide.py` (pure: plan validation, ref substitution, step transitions).
- Runs the steps in order through `toolbox.call`.
- Long steps (describe-all, etc.): the executor polls that job's status tool until done or `needs_you`. `needs_you` covers human-only steps (OTP from the [login queue](11-login-queue.md)).
- Report at the end: a deterministic summary of step results with each `open_url`; no LLM.
- Notifications `ultra_needs_you` and `ultra_done` via `notify()` (`notifications_api.py:142`).
- A step whose args depend on judgement after a write, such as "pick after captions exist", is **not supported** in v1. That is a separate plan run later. ASSUMPTION.

**Record** — table `ultra_plans`:
- Columns: id, owner_user_id, source `ui|mcp`, plan_json, plan_sha256, status, step_states json, created/approved/finished_at.
- MCP reuses it ([MCP server shape](05-mcp-server.md)).
- A step is written `started` **before** a send call. Timeout, 5xx or dropped connection → `uncertain` (`of_write.py:164-181`); the run stops and is **never auto-retried**. Each send carries an idempotency key `plan:step`.
- On relay restart, `running` → `interrupted`, and `started` steps → `uncertain`. There is no resume; the owner sees the step list. Codex P1: audit + LLM rows can't prove send outcomes.

**Credential**
- The executor holds the approving owner's **Cookie** in memory (the OK request's; for MCP, the browser approval's), not a minted token (Fable; rung 5).
- Logout does not stop it: `/auth/logout` only clears the browser's cookies (sessions are stateless), so the held Cookie still works. **Cancel is the stop.** "Log out other sessions" or turning 2FA on/off (`account_security.revoke_sessions` → `sessions_valid_after`) revokes it → the next step gets 401 → run `failed`. Every step re-checks. (An owner has no password-change route.)

**Cancel**
- Cooperative flag, checked before each step.
- Child jobs that a long step launched are cancelled through that job's own cancel route. Codex P1: `remote_login.py:375-380` and `vault_ai_vision.py:1037` run independent workers.
- Toolbox rule: a `long` tool must declare its `cancel` tool, and the drift test checks it.
- A send already in flight finishes.

**Secrets**
- `/admin/ultra/plans*` is **excluded from audit eligibility** by path, like `/admin/login` (`audit_log.py:40`). Codex reproduced a pasted password surviving the top-level redaction (`:235-252`).
- Login credentials never go through the Ultra prompt; they go through the login queue's own paste form.

**Client**
- Poll `GET /admin/ultra/plans/{id}` (precedent `BrowserbaseLoginCard.tsx:85`).
- `ultraRunReducer.ts` + vitest tables.
- States: `planning → awaiting_ok (10 min) → running ⇄ needs_you → done | failed | cancelled | capped | interrupted`.

**LLM tool calls**
- `llm_client.chat(tools=…, tool_choice)` in OpenAI shape for DeepSeek: messages accept assistant `tool_calls` and `role:"tool"`; `LLMResult.tool_calls`; empty content with tool calls is valid; schemas are counted in the token estimate.
- The Anthropic adapter (`llm_anthropic.py:76,108` drops non-text blocks) is **deferred**. The Sonnet arm of the [model eval](07-model-eval.md) runs through Claude Code against `/admin/mcp` instead.

ASSUMPTION: in-memory executor + `ultra_plans` row, no resume. ASSUMPTION: cookie held in memory ≤ run length is acceptable (it differs from ticket 03's reason to reject cookie copying, which was about long-lived external clients). ASSUMPTION: polling, not SSE.

Adversary (codex, 2 phases) + Fable: unpinned grants (P0) → pinned steps; credential leak via request audit (P0) → audit-ineligible path; child jobs outlive cancel → declared cancel tools; uncertain sends → durable step state, no retry.

## Owner amendment (2026-11-13, rung 2)

Judgement mid-run is allowed. This overturns "no post-write judgement in v1".
- New step kind `judge {question, candidates: "$<step>.<field>" | tool-read, pick_n, confirm: bool}`. After OK, the executor makes one LLM call to pick `pick_n` among the candidates. The picks fill a slot that a later send step references, e.g. `media_ids: "$pick.ids"`.
- The judge can only **select among the candidates the plan named**. Audience, price and text stay pinned on the card, so fan text still can't widen what gets sent.
- `confirm: true` when the client asked to confirm, or when the planner chose to → `needs_you` **pick card**: about 6 candidate thumbnails with the AI's picks pre-ticked → owner picks → the run continues and sends. With no confirm, the run sends right away.
- Any other human-only gap in the middle → a `needs_you` card asking the user to do it or check it.
- Judge calls count toward the run's cost cap.
