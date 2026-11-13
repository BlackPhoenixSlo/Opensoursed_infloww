# MCP server shape

Type: grilling
Status: resolved
Blocked by: 03, 04

Transport and home: hosted streamable-HTTP endpoint on the relay vs local stdio package on the owner's machine vs both. How "save report to a Desktop folder" works (client-side file write vs local package). Public-repo and AE deploy implications.

Owner (2026-11-13): MCP can register a new account and always serves a link to open in the browser. Decide the browser-link connect flow (device-code style: MCP shows URL → owner logs in or registers → Approve → token handed to the MCP; maps onto MCP OAuth later) and how every result carries an `open_url`.

## Answer

**Hosted `POST /admin/mcp` on the relay, a hand-rolled JSON-RPC endpoint; sends only through an approved plan whose OK happens in the browser.** Rung 5 + rung 2.

Home and protocol
- Streamable HTTP that answers plain JSON (no SSE, no `Mcp-Session-Id`); GET/DELETE 405; a batch → -32600.
- `/admin/` already reaches the relay on every deploy: Next rewrite `app/next.config.ts:133`, Traefik `docker-compose.yml:314`, Caddy `deploy/fleet/templates/Caddyfile.tmpl:16-19`. So no proxy change.
- Foreign `Origin` is refused.
- `service/mcp_api.py`, about 200 lines: `initialize` (2025-03-26 / 2025-06-18 / 2025-11-25), `notifications/initialized` 202, `ping`, `tools/list`, `tools/call`.
- No `mcp` package: it would clash with the pinned starlette (`requirements.txt:8-20`).
- No local stdio package in v1. Clients that only speak stdio use the third-party `npx mcp-remote <url> --header "Authorization: Bearer …"`.

Tools (with an `ifw_` bearer)
- Toolbox v1 **read** tools plus **non-send writes** (folders, bio pages), each with `open_url`.
- Results = `structuredContent` + one text block.
- **Send-class tools are not exposed one by one.** Instead:
  - `propose_plan {summary, steps}` — same shape and validation as the [Ultra loop](06-ultra-loop.md), stored in `ultra_plans` with `source=mcp`. It returns `plan_id` + `open_url` = `/ultra/plans/{id}`.
  - The owner opens the link, sees the pinned-args card, and clicks OK (browser cookie). The server executor runs the plan.
  - `plan_status {plan_id}` reports progress and per-step `open_url`s.
- This meets "one OK at start, no more confirms" and "always serves a link". Codex P1: per-tool client approval did not meet it.

Connect / "register via MCP"
- A call without a bearer serves `initialize`, `tools/list` and one tool, `connect_account`. It returns a link to register or log in → `next=/settings/ai-keys`, where the owner mints a token on the Access tokens card (ticket 03). Minting is the approval.
- The owner pastes the token into the client config, never into chat. Every other call without a bearer returns the same link as `isError`.
- `/admin/mcp` goes on an exact-path allowlist in `_account_isolation_middleware`, only for requests with no credential (pattern `server.py:486`).
- Fleet shards with registration closed 403 `/auth/register` (`deploy/fleet/fleet.py:294-299`). So the register link uses optional env `MCP_SIGNUP_URL` (the fleet template sets it to the open shard's URL), and falls back to the same host.
- ASSUMPTION: pasting the token into config is fine for v1.
- Later, OAuth 2.1 code + PKCE for remote connectors: discovery `/.well-known/*` (3 proxies), consent page, and Approve mints an ordinary `owner_tokens` row. That is its own ticket, not v1.
- Token blocks from ticket 03 still hold.

Desktop save
- `report_run` returns ≤200 JSON rows (Report recipe). For a full file, `report_file {recipe, format}` builds the CSV/xlsx and returns `download_url` = `GET /admin/reports/files/{id}` (15 min, in memory, same bearer).
- The client saves it (Claude Code `curl -H "Authorization: Bearer …" -o ~/Desktop/…`). Codex P1: 200 rows would have silently truncated.

Audit and the rest
- `/admin/mcp` is **excluded from audit eligibility by path** (not only its body snapshot); inner calls carry the audit (`audit_log.py:66,73,202`).
- Demo: `LOCKED POST /admin/mcp` (`demo/middleware.py:61`).
- Public repo: shareable.

ASSUMPTION: register link = browser link, not a headless signup tool (map). ASSUMPTION: the Next rewrite forwards `Authorization` (falsified by a 401 on AE). ASSUMPTION: `mcp-remote` is acceptable for stdio clients.

Adversary (codex, 2 phases) + Fable: per-tool approval ≠ start confirm → plan + browser OK; 200-row Desktop truncation → `report_file`; closed-shard signup → `MCP_SIGNUP_URL`; audit eligibility, not snapshot.

## Owner amendment (2026-11-13, rung 2)

"Go for the plan" — approved. MCP should do everything, including **register and log in**, built as the **last step**:
- `register_account {email, password, agency_name}` and `login {email, password, code?}`, both offered without a bearer.
- Each runs in-process `/auth/register` / `/auth/login`, then mints an owner token with the fresh session (`/admin/owner-tokens`), and returns the token + `open_url`.
- The token passing through the agent transcript is accepted (owner: "just for fun").
- `/admin/mcp` is already audit-ineligible, so passwords are never stored.
- Closed shards → `MCP_SIGNUP_URL` host or refuse with the link.
- The sign-up link stays for clients without these tools.
