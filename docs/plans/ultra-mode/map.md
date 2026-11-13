# Ultra mode + MCP — wayfinder map

Run: wayfinder-auto, run id `wf-ultra-20261113`, started 2026-11-13. No `--execute`: plan only (floor 1).

## Destination

An **owner** of an Agency can:
1. Ask the help bot (plain **Do mode**) for any report in their own words and download it as CSV after one confirm click.
2. Point an MCP client (Claude Desktop/Code, any MCP agent) at Inflowwww with an owner token and read their own Agency's data + run the same actions the app offers — including saving a report into a Desktop folder (the client writes the file).
3. Tick **Ultra mode** in the help bot: panel turns black + red "AI style"; the AI restates a multi-step plan, owner clicks OK once, then it runs to the end with no further confirms (sends go right away) and reports back. First jobs: Halloween vault → two folders → mass/Auto mass/Auto story → one post + one message now; connect N models from pasted logins; a bio page with background for each model missing one; any report.

Reading taken: one shared **toolbox** (curated tool list over existing routes/queries) serves Do-mode export, MCP and the Ultra loop; the effort is the four phases in the invocation, decisions only.
ASSUMPTION: rejected alternative = Ultra as a separate product with its own action layer (duplicates guards that ~613 existing routes already enforce). Overturned if the toolbox can't reach existing behaviour in-process.

## Notes

Owner decisions (2026-11-13, chat; source: memory `ultra-mode-idea.md`, written from owner's words — rung 2):
- "Not new" = **not nude** (free masses can't be nude).
- "Buy a page" = build a bio page; only gap = **page-level background picture**. Domain/DNS linking: later, out of scope.
- One confirm click at the **start** of every long action (AI restates plan → OK → no more confirms; sends go right away).
- Ultra + MCP: **owners only**.
- MCP may read the Agency's own DB data, not only REST.
- Reports "however the client asks" must be codified (any report by prompt), and CSV-by-prompt must work in plain Do mode too.
- AI descriptions are the prerequisite for picking media (OF vault has no captions).
- Browserbase login shows no captchas (owner). Multi-login **sequential** first; a model not logged in after 5 min → notify the user; parallel only if needed.
- Models to test for the tool loop: DeepSeek flash vs Claude Sonnet.
- (2026-11-13, later) **MCP can also register a new account, and always serves a link to open in the browser.** Read as: (a) an MCP client with no account gets a browser link to register / log in and approve the connection (registration itself stays the existing `/auth/register` form, `service/auth.py:512`; note it has no human check, `app/components/auth/Landing.tsx:211`); (b) every MCP tool result carries a link that opens the same thing in the app.
- (2026-11-13, owner answers to the plan report):
  - **Judgement mid-run is OK.** If a step needs judging later (e.g. which pictures), the AI judges then sends. If the client asked to confirm, show a card with a few pictures to pick from, then send. Something in the middle needing the human → ask the user (needs-you card).
  - **MCP does everything, including register and log in** — the headless MCP register/login is the **last build step** ("just for fun"). The sign-up *link* reading is also right (both exist).
  - MCP plan (ticket 05) approved: "go for the plan".
  - Black/red Ultra look: **agent picks one**, owner asks for changes later (no prototype gate).
  - `/auth/register` with no human check is fine for now; harden at ~100 clients.
ASSUMPTION: "register via MCP" = the MCP hands out a browser link, not a headless `register` tool posting email+password. Overturned if the owner wants fully headless signup — falls: MCP server shape.

Scouted facts (2026-11-13, read-only Explore agents; file refs in tickets):
- No MCP / tool-calling code; no API tokens (cookie-only auth: `service/auth.py`, `service/chatters.py:78`); `llm_client` sends no tools.
- Do mode = one JSON-mode LLM call → validated intents → browser fills real editor / `POST /admin/assistant/edit/apply` (`service/assistant_draft.py`, `service/assistant_edit.py`, `app/components/assistant/`).
- Middleware chain does isolation, role enforcement (chatters only), audit of 2xx writes (`service/server.py:607-660`, `service/audit_log.py`).
- Exports: `?format=csv` on sales-records, paid-messages, fan-report, tips-list, top-tippers; `POST /admin/stats/xlsx` (rows from client).
- Remote login: Browserbase jobs, OTP endpoint, 285 s window, one job per email (`service/remote_login.py`, `service/remote_login_api.py`).
- Bio pages: create/list/avatar/link backgrounds from vault (`service/bio_pages/admin.py`); no page-level background (`BioProfile`, `service/db/models.py:3954`).
- Vault: text search over AI descriptions/tags (`service/vault_ai_api.py:621-646`); describe-all is operator-started; OF folders create/add (`service/vault_of_folders.py:696,731`); rules take OF folder ids (`automation_catalog.py`); one-off mass takes media ids.

Constraint from Owner tokens: tool calls run through the HTTP middleware stack (isolation, deactivated-write guard, audit are HTTP hooks) — ContextVars alone bypass them.

Housekeeping rules that bind the build (repo CLAUDE.md): reducers for multi-state UI; new prompts → `docs/prompts/README.md`; model text to OF → `finalize_draft` chain; slop opt-in only.

## Tickets

| # | Ticket | Type | Blocked by |
|---|---|---|---|
| 01 | [Report recipe: shape and Agency scoping](issues/01-report-recipe.md) | domain-modeling | — |
| 02 | [Do-mode export intent](issues/02-do-mode-export.md) | grilling | Report recipe |
| 03 | [Owner access tokens](issues/03-owner-tokens.md) | grilling | — |
| 04 | [Toolbox: one tool registry](issues/04-toolbox.md) | grilling | Report recipe |
| 05 | [MCP server shape](issues/05-mcp-server.md) | grilling | Owner tokens, Toolbox |
| 06 | [Ultra loop](issues/06-ultra-loop.md) | grilling | Toolbox |
| 07 | [DeepSeek flash vs Sonnet eval](issues/07-model-eval.md) | grilling | Toolbox, Ultra loop |
| 08 | [Ultra black/red look](issues/08-ultra-look.md) | prototype (agent picks) | — |
| 09 | [Halloween pick pipeline](issues/09-halloween-pick.md) | grilling | Toolbox |
| 10 | [Caption writer](issues/10-caption-writer.md) | grilling | Toolbox |
| 11 | [Sequential login queue](issues/11-login-queue.md) | grilling | Owner tokens |
| 12 | [Bio page background](issues/12-bio-background.md) | grilling | — |
| 13 | [Send chain for tool-written text](issues/13-send-chain.md) | grilling | Toolbox |

## Decisions so far

- [Report recipe](issues/01-report-recipe.md): enum-only recipe over 4 datasets (sales, employee_sales, chat_activity, fan_spend) on existing engines; scope from session → own Agency's Creators **and own Employees**; csv/xlsx/json; catalogue endpoint is the bot's closed book.
- [Owner tokens](issues/03-owner-tokens.md): hashed `ifw_` tokens, Settings → AI keys card, bearer resolves to owner context clamped to own Agency, suppresses all cookies, blocked from `/events`/founder/auth routes, audit `via="token <name>"`.

- [Do-mode export](issues/02-do-mode-export.md): 4th Do flow `report_export`; every named Creator/Employee must resolve uniquely or Download stays off; works from General focus; card → POST → blob download; retry by attempt counter.
- [Toolbox](issues/04-toolbox.md): pydantic-typed registry → MCP/OpenAI/Anthropic schemas; in-process ASGI with caller's credential in an empty context; resource tools bind to the resource's own Creator; rule create/enable = send; every result gets `open_url`; login and chat_send held back.
- [MCP server shape](issues/05-mcp-server.md): hosted `POST /admin/mcp`, hand-rolled JSON-RPC, no SDK dep; reads + non-send writes direct; sends only via `propose_plan` → owner OKs in browser link; no-bearer calls get a register/login link; `report_file` download URL for Desktop saves.
- [Ultra loop](issues/06-ultra-loop.md): plan-then-execute — model plans with read tools, card shows every pinned arg, one OK, server runs steps with no LLM; `ultra_plans` table records step states, uncertain sends never retried; shared by in-app Ultra and MCP.
- [Ultra look](issues/08-ultra-look.md): agent-picked near-black + red panel, owner tweaks later.

## Not yet specified

- Fan-typed text (display names, messages) reaching the Ultra/MCP model = prompt-injection path (from Report recipe).
- Post-v1 report datasets: ppv_messages incl. mass, new subs, vault media stats.
- Remote MCP over HTTP: MCP spec says SHOULD use OAuth; Claude Desktop/claude.ai remote connectors expect it (inferred) — folded into MCP server shape.

- Owner-adjustable Ultra cost cap (v1 fixed 100¢ planning cap).
- Harden `/auth/register` (human check / rate limit) at ~100 clients (owner).
- OAuth 2.1 + PKCE for remote MCP connectors (claude.ai) — post-v1.
- Steps that need model judgement after a write (e.g. pick after captions finish) — v1 = separate plan runs.
- Release blocker: model-written mass/post text must pass the shared finalize chain (→ ticket 13).

## Out of scope

- Custom domain / DNS linking for bio pages (owner: later, own notes).
- Chatter / admin access to Ultra or MCP (owner: owners only).
- Captcha auto-solving (off by design, `service/remote_login.py:12`).

## Needs the human

(none — owner answered 2026-11-13)

## Assumptions to veto

- Do-mode export with no names = all owned Creators. Falls: Do-mode export.
- Toolbox: empty `contextvars.Context()` per in-process call isolates identity. Falls: Toolbox, MCP server shape, Ultra loop.
- Automation rule create/enable classed as `send` (needs the start confirm). Falls: Ultra loop.
- Ultra = plan-then-execute; after OK the LLM runs only inside `judge` steps that pick among candidates the plan named. Falls: Ultra loop, Halloween pick, model eval.
- MCP sends only via browser-approved plan, not per-tool client approval. Falls: MCP server shape.
- Executor holds approving owner's cookie in memory for the run. Falls: Ultra loop.
- Owner token pasted into MCP client config in v1 (no OAuth); headless `login`/`register_account` tools return the token into the agent transcript (owner: fine). Falls: MCP server shape.
- Anthropic tool adapter deferred; Sonnet eval arm via Claude Code over MCP. Falls: model eval.

- Report recipe is owners-only in v1. Falls: Do-mode export.
- Owner tokens carry full owner rights (no read-only split). Falls: MCP server shape.
- Master token clamped to own Agency. Falls: MCP server shape.
- Reverse proxies pass `Authorization` (Caddy template read, not run). Falls: MCP server shape (hosted).

- Destination reading: one shared toolbox for export, MCP and Ultra. Falls: 03, 04, 05, 06.
- Map lives tracked in `docs/plans/ultra-mode/` (house precedent `docs/plans/*.md`), not `.scratch/` (git-excluded, so uncommittable). Falls: nothing but location.

## Build order (Fable advisor, adopted)

1. Report recipe + Do-mode export (destination 1 alone, no tokens/toolbox).
2. Owner tokens → Toolbox read tools + `report_run`/`report_file` → `/admin/mcp` read-only (destination 2 incl. Desktop save).
3. Non-send write tools (folders, bio pages); drive the four owner jobs from Claude Code as the eval.
4. Send chain (ticket 13) → `ultra_plans` executor + `propose_plan`.
5. In-app Ultra planning on DeepSeek, `judge` steps + pick cards; black/red look (agent-picked).
6. Last: headless MCP `register_account` + `login` tools.
