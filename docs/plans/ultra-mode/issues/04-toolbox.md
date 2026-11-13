# Toolbox: one tool registry for export, MCP and Ultra

Type: grilling
Status: resolved
Blocked by: 01

Where do tool definitions live and how are they executed: in-process call of existing route handlers vs internal HTTP with the caller's session vs new service functions? Tool schema format (JSON Schema both MCP and DeepSeek/Anthropic accept), first tool list, read tools vs DB reads, how writes keep isolation/role/audit.

## Answer

**One registry, executed in-process through the full HTTP stack with the caller's own credential.** Rung 2 (Owner tokens constraint: tool calls run through the middleware) + rung 1 (`httpx==0.28.1` in requirements; tests already use `ASGITransport`).

Execution — `service/toolbox.py: call(tool, args, creds)`
- `httpx.AsyncClient(transport=ASGITransport(app=server.app, raise_app_exceptions=False))`.
- Creds copied from the caller only: in-app → outer Cookie; MCP → `Authorization: Bearer ifw_…`; plus Host / X-Forwarded-Host/Proto (bio public URLs). Never `X-Employee-Id`.
- Each call runs in an empty context: `asyncio.create_task(_do(), context=contextvars.Context())`. Auth ContextVars are never reset (`auth.py:668`, `chatters.py:835`).
- The outer handler releases its DB session before awaiting tools (`db/engine.py:70`).
- Rejected: loopback HTTP (single worker, `Dockerfile:103`); direct handlers (bypass audit, `audit_log.py:188`).

Definitions — `service/toolbox_decide.py` (pure)
- `Tool(name, description, method, path, args: pydantic model, effect read|write|send, long, untrusted, shape, open)`.
- `input_schema` is **generated from the pydantic model** (precedent `assistant_draft.py:345`; pydantic 2.13 in requirements, no jsonschema dep). `call()` validates args against the model **before** `build_request`, because routes like folder create accept untyped dicts and silently drop bad ids (`vault_of_folders.py:697-707`).
- Exports: `as_mcp()` (`inputSchema` + readOnly/destructive hints), `as_openai()` (`function.parameters`, DeepSeek), `as_anthropic()` (`input_schema`). Schema rules: object, `additionalProperties:false`, no `$ref`/top-level `oneOf`, names `^[a-z0-9_]{1,64}$`.
- Account binding: tools on a Creator-level route take `account_id` (header + query + body as the route reads it). Tools on a **resource id** (rule, folder, bio page) take no `account_id`: `call()` first reads the resource, takes its stored Creator, refuses if it is not owned, and sends that as the header so audit records the truth (`automation_rules_api.py:649-663` vs `audit_log.py:130`).
- Effect is semantic, not HTTP: `report_run` (POST) = read; `automation_rule_create`/`update` and enable = **send** (enabled rules schedule sends, `automation_rules_api.py:357`, `mass_premade.py:132`).
- `open`: app path template + **explicit response-field mapping** (folder create returns `id`, add returns `list_id`, `vault_of_folders.py:728,751`). Real paths: `/growth/bio-pages/{profile_id}`, `/growth/vault-pro`, `/growth/auto-mass`, … `call()` adds `open_url` = public app base + path to every result that has a page (owner 2026-11-13).
- Drift test `service/tests/test_toolbox_routes.py`: each sample path FULL-matches its route + method in `server.app.routes`; GET ⇒ read; schema rules; every `open` path exists as `app/app/**/page.tsx`.

v1 tools
- read: creators_list, stats_per_model, vault_search (≤30), of_folders_list, describe_all_status, automation_kinds, automation_rules_list, bio_pages_list, report_catalogue, report_run.
- write: describe_all_start (long), of_folder_create, of_folder_add, bio_page_create, bio_avatar_from_vault, bio_link_add, bio_link_bg_from_vault.
- send: automation_rule_create/update/run_now, mass_send (`mass_queue_api.py:327`), post_create (`server.py:5854`).
- Held back from v1:
  - `chat_send` — not needed by any owner job.
  - Remote-login tools — OF passwords must never enter an LLM transcript or audit row. See [Sequential login queue](11-login-queue.md): a paste form parsed server-side.
  - `bio_page_background` — no route yet.
- **Any send tool carrying model-written text** must go through the shared chain `finalize_draft → shape_parts → apply_typo_throttle` (CLAUDE.md; `server.py:3899`, `:5854` forward text raw). This blocks release; it is its own ticket: [Send chain for tool text](13-send-chain.md).

Audit/secrets: the MCP host route is excluded from body snapshots, since `_safe_snapshot` redacts only top-level keys (`audit_log.py:247`; codex reproduced nested `password` surviving). Inner calls carry the audit.

No generic DB-read tool: "MCP reads own DB data" = report datasets + GET tools (rung 5).

Shaping: per-tool `shape`; lists ≤50 rows (reports 200), strings ≤500 chars, result ≤~24k chars with `truncated` + `row_count`; non-2xx → `{error:{status,detail}}`; untrusted output wrapped `{"data_only": …}`.

ASSUMPTION: empty Context per call is enough isolation (falsify: an inner call changes outer `get_request_user()`; a test must assert both ways). ASSUMPTION: 50 rows / 24k fits both models. ASSUMPTION: rule create/enable treated as send.

Adversary (codex, 2 phases): nested-password audit leak, raw model text to OF, resource/Creator mismatch, enabled-rule-is-a-send, wrong page paths, no runtime validation — all accepted above.
