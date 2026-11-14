# Owner access tokens

Type: grilling
Status: resolved 2026-11-13
Blocked by: none

How does a non-browser caller (MCP server/client) authenticate as an Agency owner? Token storage (hashed), scope (one Agency, owner only), expiry/revocation UI, how middleware turns a bearer into the same Agency context the cookie gives, audit tagging "via agent", demo-site handling.

## Answer

**Opaque owner tokens (personal access tokens), hashed.** Rejected: copying session cookies (logout only clears the cookie, `service/auth.py:554`); stateless JWTs (cookies re-check `sessions_valid_after` and reload access per request, `service/auth.py:674` — JWTs would lose that); OAuth now (more surface; parked into MCP server shape ticket — MCP spec: stdio takes env credentials, HTTP SHOULD use OAuth). Rung: 3 (house: share links `token_urlsafe` + revoke/expiry, `service/link_share_api.py:190`; sha256 codes, `service/account_security.py:116`) + 5.

- Token `ifw_` + `secrets.token_urlsafe(32)`; store `sha256` only; plaintext shown once.
- Table `owner_tokens` (id, user_id FK users CASCADE, name, token_sha256 unique, hint, created_at, expires_at NOT NULL, last_used_at, revoked_at) + `actions.via` nullable; inspector-guarded migration after head 0116.
- `service/owner_tokens.py` (pure mint/digest/verdict) + `service/owner_tokens_api.py` `/admin/owner-tokens` GET/POST `{name, days: 30|90|365}` (default 90)/DELETE; owner session only (`require_user`, own `user.id`, as `service/tenant_keys_api.py`). UI: Access tokens card on Settings → AI keys (already chatter-hidden, `app/lib/nav.ts:354`).
- **Resolution** in `auth._resolve_session`: `Authorization: Bearer ifw_…` → look up by digest; refuse revoked, expired, or `created_at < sessions_valid_after` (Log out other sessions kills tokens too); `_request_user = AuthedUser(user.id, …, agency_account_ids(own), is_admin=False)` — **a Master's token is clamped to its own Agency**; ContextVar `_request_token=(id,name)`; `last_used_at` at most every 5 min. Bad token → 401, never a cookie fallback.
- **Bearer suppresses every cookie identity**: session, impersonation **and the chatter cookie** (chatter middleware sets `_request_chatter` independently, `service/chatters.py:841-848`).
- **Superseded (build-log F3, 2026-11-14): an allowlist, not this blocklist** — a token reaches only the Toolbox non-send routes, report files and `/admin/mcp` (`service/token_auth.py`); everything else 403. Original: **Token-blocked (403, `session_stamps.token_blocks`)**: `/auth/` and `/chatter/` writes, `/admin/owner-tokens*`, `/admin/impersonate`, `/admin/my-llm-keys` writes, **`GET /events`** (an SSE stream captures access at connect and never re-checks, `service/server.py:6235`, `service/events.py:627-660`; MCP needs no stream). **`_assert_admin_password` refuses token requests** (founder routes such as `POST …/{user_id}/accounts` gate on the password only, `service/auth.py:983-1005`).
- **Attribution**: for token requests ignore `X-Employee-Id` in audit and message attribution (`service/audit_log.py:126-181`, `service/employees.py:904-919`); actions land on the owner's Employee with `via="token <name>"`; Audit tab shows it.
- Share gate (`service/server.py:~739`) lets `Bearer ifw_` through to the session check. No CSRF work (bearer is not ambient; no CORS middleware). No login throttle (256-bit). Demo: lock `POST /admin/owner-tokens` (`demo/middleware.py:58-108`). No env/secrets; tokens are per DB; leak-gate regex `ifw_[A-Za-z0-9_-]{40,}`.
- **Constraint for the Toolbox ticket:** in-process tool calls must go through the same HTTP middleware stack (isolation, deactivated-write guard and audit are HTTP hooks, `service/server.py:582-647`, `service/audit_log.py:188`); setting ContextVars alone is not enough.

ASSUMPTION: tokens = full owner rights, no read-only split. Overturned if the owner wants report-only tokens — falls: MCP server shape.
ASSUMPTION: Master token clamped to own Agency. Overturned if MCP must span Agencies.
ASSUMPTION: expiry required (30/90/365, default 90). Overturned by owner.
ASSUMPTION: reverse proxies pass `Authorization` (Caddy template shows no stripping, `deploy/fleet/templates/Caddyfile.tmpl`; not run). Overturned by a live 401 through AE's proxy.

**Adversary (codex, 2 phases):** P0 founder-password grant reachable with a token — accept (gate refuses tokens). P0 SSE stream outlives revocation — accept (block `/events` for tokens). P1 chatter cookie still resolves — accept. P1 `X-Employee-Id` spoofing — accept. P2 in-process bypass — accept as Toolbox constraint. Phase-1 MCP-spec OAuth note — partial: moved to MCP server shape.
