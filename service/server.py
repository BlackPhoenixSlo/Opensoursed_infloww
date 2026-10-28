"""
Step 4: HTTP relay over the signed OF client.

A thin FastAPI wrapper around OFClient. Endpoints mirror OF's URL structure so
the frontend can speak OF's shape directly — we just sign + forward + return.

  GET  /health                           — does the captured session still work?
  GET  /api/of/v2/users/me
  GET  /api/of/v2/chats?limit=10&offset=0&order=recent
  GET  /api/of/v2/chats/{chat_id}/messages?limit=10&before_id=...

Run from the repo root with whichever venv has curl_cffi + fastapi + uvicorn:
  ./venv/bin/uvicorn service.server:app --reload --port 8787
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
import threading
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal, NamedTuple

import json

import asyncio
import atexit
import contextlib
import functools
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES as _GZIP_SKIP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field, field_validator

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import accounts as account_registry  # noqa: E402
import admission  # noqa: E402  # bounded-concurrency lanes (see service/admission.py)
import lane_config  # noqa: E402  # durable store behind the Concurrency panel
import account_health  # noqa: E402  # dead-session pause (see service/account_health.py)
import account_page  # noqa: E402  # free-vs-paid page (see service/account_page.py)
import ownership  # noqa: E402  # owned-media semantics (see service/ownership.py)
import proxies as proxy_registry  # noqa: E402
from brand import BRAND_NAME  # noqa: E402
import proxy_health  # noqa: E402  # proxy up/down + trace probe (2.14)
import live_rev  # noqa: E402
import sign_rules  # noqa: E402  # one sign-rule refresh for every account (2.17)
import secrets_store  # noqa: E402  # UI-writable key store (Setup → Keys)
from of_client import DEFAULT_TIMEOUT_S, IMPERSONATE, INTERACTIVE_READ, OF_CDN_SUFFIXES, OFClient, OFAPIError, OFDeactivatedError, OFDeniedError  # noqa: E402
import client_pool  # noqa: E402 — the relay's one OFClient pool
from curl_cffi import requests as curl_requests  # noqa: E402  # proxy/network error types

# Phase A — SQL persistence + SSE broadcaster. Both are additive: the
# legacy WS subscribers in `_event_subscribers` keep working alongside.
from db import init_db as db_init  # noqa: E402
from db.repo import ensure_user_account_link, sync_from_disk as _sync_db_from_disk  # noqa: E402
from events import (  # noqa: E402
    handle_event as _sse_handle_event,
    owner_audience,
    publish_chat_responded,
    sessions_audience,
    sse_stats as _sse_stats,
    sse_stream,
    start_persist_worker as _start_persist_worker,
    stop_persist_worker as _stop_persist_worker,
)
from employees import router as _employees_router, audit_middleware as _audit_middleware  # noqa: E402
from permissions import role_enforcement_middleware  # noqa: E402
from http_hooks import HookChain  # noqa: E402
from fans import router as _fans_router  # noqa: E402
from fan_insights_api import router as _fan_insights_router  # noqa: E402
from messages import (  # noqa: E402
    router as _messages_router,
    persist_rest_media_dims,
    stamp_rest_media_dims,
)
from stats import router as _stats_router, scope_ids as _stats_scope_ids, stats_guard as _stats_guard  # noqa: E402
from transactions import router as _transactions_router  # noqa: E402
from vault import router as _vault_router  # noqa: E402
import vault_cache  # noqa: E402  # shared TTL cache for /api/of/v2/vault/* responses
import vault_ingest  # noqa: E402  # a finished import -> mirror rows (the grid reads the mirror)
import vault_upload  # noqa: E402  # batch vault import (spool -> OF -> clear spool)
import vault_ai_api  # noqa: E402  # an import's per-file details -> mirror rows
import gdrive  # noqa: E402  # the Drive key's reader, for the import card's on/off flag
import relay_cache  # noqa: E402  # in-process TTL cache for hot-path OF endpoints (Stage C will wire call-sites)
import of_promos  # noqa: E402  # `to_cents`, OF's dollars to our cents
import relay_coalesce  # noqa: E402  # in-flight dedup for idempotent OF GETs (Stage B-2)
import chats_page  # noqa: E402  # one logical page of OF /chats (inbox, badge)
from lists import router as _lists_router  # noqa: E402
from automation_rules_api import router as _automation_rules_router  # noqa: E402
from translate_api import router as _translate_router  # noqa: E402
from funnels_api import router as _funnels_router  # noqa: E402
from nudge_config_api import router as _nudge_config_router  # noqa: E402
from purchase_followup_config_api import router as _purchase_followup_config_router  # noqa: E402
from auto_follow_api import router as _auto_follow_router  # noqa: E402
from lifecycle_message_config_api import router as _lifecycle_message_config_router  # noqa: E402
from priority_mass_api import router as _priority_mass_router  # noqa: E402
from split_inbox_api import router as _split_inbox_router  # noqa: E402
import lane_config_api  # noqa: E402  # Concurrency panel — UNAUTHENTICATED, see below
from autoreply_config_api import router as _autoreply_config_router  # noqa: E402
from customs_api import router as _customs_router  # noqa: E402
from vault_ai_api import router as _vault_ai_router  # noqa: E402
from style_config_api import router as _style_config_router  # noqa: E402
from account_config_api import router as _account_config_router  # noqa: E402
from assistant_api import router as _assistant_router  # noqa: E402
from copilot_api import router as _copilot_router  # noqa: E402
# Growth surfaces (gaps-lane: Infloww-gap features) — all self-contained routers.
from smart_lists_api import router as _smart_lists_router  # noqa: E402
from trial_links_api import router as _trial_links_router  # noqa: E402
from tracking_links_api import router as _tracking_links_router  # noqa: E402
from of_tracking_api import router as _of_tracking_router  # noqa: E402
from link_metrics import router as _link_metrics_router  # noqa: E402
from promotions_api import router as _promotions_router  # noqa: E402
from link_share_api import router as _link_share_router  # noqa: E402
from tenant_keys_api import (  # noqa: E402
    router as _tenant_keys_router,
    admin_router as _tenant_keys_admin_router,
    status_router as _ai_key_status_router,
)
from system_admin_api import router as _system_admin_router  # noqa: E402
from settings_api import router as _settings_router  # noqa: E402
import notifications_api  # noqa: E402
from shifts_api import router as _shifts_router  # noqa: E402
from employee_groups_api import router as _employee_groups_router  # noqa: E402
from sensitive_words_api import router as _sensitive_words_router  # noqa: E402
from scripts_import_api import router as _scripts_import_router  # noqa: E402
from clock_api import router as _clock_router, _sweep_callers_agencies  # noqa: E402
from sales_amend import router as _sales_amend_router  # noqa: E402
from s4s_api import router as _s4s_router  # noqa: E402
from s4s_requests_api import router as _s4s_requests_router, expire_callers_requests as _expire_s4s_requests  # noqa: E402
from s4s_schedule_api import router as _s4s_schedule_router  # noqa: E402
from s4s_media import router as _s4s_media_router  # noqa: E402
from account_security_api import router as _account_security_router  # noqa: E402
import fleet_api  # noqa: E402  # cross-shard login lookup, fleet installs only
from remote_login_api import router as _remote_login_router  # noqa: E402 — served Browserbase login
from auth import (  # noqa: E402
    router as _auth_router,
    admin_router as _auth_admin_router,
    impersonate_router as _auth_impersonate_router,
    session_middleware as _auth_session_middleware,
    get_request_user as _get_request_user,
    require_master as _require_master,
    assert_account_owned,
    allow_anonymous_account_access as _allow_anonymous_account_access,
    require_actor_account_ids as _require_actor_account_ids,
    clamp_account_filter,
    COOKIE_NAME as _AUTH_COOKIE_NAME,
)
from chatters import (  # noqa: E402
    router as _chatters_router,
    admin_router as _chatters_admin_router,
    chatter_session_middleware as _chatter_session_middleware,
    get_request_chatter as _get_request_chatter,
    current_actor as _current_actor,
    allowed_folder_ids_for_chatter as _allowed_folder_ids_for_chatter,
    COOKIE_NAME as _CHATTER_COOKIE_NAME,
)


def _kick_db_sync(reason: str) -> None:
    """Fire-and-forget re-import of JSON files into SQL. Called after every
    mutating admin endpoint so the SQL mirror catches up within a few hundred
    ms of any change to accounts.py / proxies.py / session_bootstrap state.

    Wrapped in try/except + logged because a sync failure must NEVER bubble
    out of an admin response — the user's actual mutation already succeeded
    against the JSON write path."""
    import asyncio as _aio
    try:
        loop = _aio.get_running_loop()
    except RuntimeError:
        # Sync FastAPI handlers run in the threadpool; trampoline to the
        # main loop captured at startup.
        if _main_loop is None:
            return
        _main_loop.call_soon_threadsafe(
            lambda: _aio.create_task(_sync_db_from_disk(), name=f"db-sync-{reason}")
        )
        return
    loop.create_task(_sync_db_from_disk(), name=f"db-sync-{reason}")


def _redact(s: str) -> str:
    """Mask user:password in a connection URL before logging.
    Turns 'postgresql://user:pass@host/db' into 'postgresql://***@host/db'.
    No-op for SQLite paths and any URL without credentials."""
    import re as _re
    return _re.sub(r"://[^/@]+@", "://***@", s)

log = logging.getLogger("of-relay")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Run the one-shot legacy-layout migration before any client load — moves
# pre-multi-account sessions into accounts/<user_id>/. Idempotent.
account_registry.migrate_legacy()

# Promote any pre-existing proxy → session-file bindings to proxy → account_id
# bindings, so the new UI sees them and so re-captures don't silently lose
# the proxy. Idempotent — only fires for proxies that haven't been upgraded.
def _migrate_proxy_bindings_to_accounts() -> None:
    # Build a filename → account_id map by scanning each account dir.
    mapping: dict[str, str] = {}
    base = HERE / "sessions" / "accounts"
    if base.is_dir():
        for adir in base.iterdir():
            if not adir.is_dir():
                continue
            for sp in adir.glob("session_*.json"):
                mapping[sp.name] = adir.name
    if mapping:
        n = proxy_registry.migrate_legacy_assignments(mapping)
        if n:
            log.info("migrated %d legacy proxy assignment(s) → account_id", n)


_migrate_proxy_bindings_to_accounts()


def _sync_proxy_pool() -> None:
    """Seed the Inflowwww proxy pool from the env (proxies.sync_pool). Called
    first thing in the startup hook, not at import."""
    r = proxy_registry.sync_pool(os.environ.get(proxy_registry.POOL_ENV))
    for err in r["errors"]:
        log.warning("%s: bad line %s", proxy_registry.POOL_ENV, err)
    if r["skipped"]:
        return
    log.info("Inflowwww proxy pool: %d proxies, %d account(s) re-picked, %d left without one",
             r["size"], r["rebound"], r["dropped"])

app = FastAPI(title="OF Relay", version="0.1.0")

# ── Response compression ───────────────────────────────────────
# JSON shrinks 5-8x (measured: /admin/fans 63,870 → 7,604 B; a 30-message
# thread 19,392 → 3,343 B). Registered FIRST so it is the innermost layer: the
# hook chain below re-streams every body in chunks, and behind it GZip could
# no longer see a small body whole, so `minimum_size` would stop applying. Starlette's default exclusion list already skips
# `text/event-stream` (SSE must flush frame by frame), audio/* and video/*, five
# named image types and every 206 range reply. Added: all of image/* and both
# octet-streams, because /img streams the CDN's Content-Type through verbatim
# (heic, svg, an S3 `binary/octet-stream`, or our octet-stream default when it
# sends none) and a media stream must never be buffered through the
# compressor. Level 6, not Starlette's 9: about the same ratio on JSON for much
# less CPU on a single-worker relay. `exclude_content_types` and its `type/*`
# matching are recent Starlette, hence the starlette pin in requirements.txt.
app.add_middleware(
    GZipMiddleware,
    minimum_size=1024,
    compresslevel=6,
    exclude_content_types=(*_GZIP_SKIP, "image/*", "application/octet-stream",
                           "binary/octet-stream"),
)

# ── HTTP hooks ─────────────────────────────────────────────────
# Every `(request, call_next)` hook below is added to this chain rather than
# with `@app.middleware("http")`, so all of them run inside ONE middleware
# layer instead of one each (see http_hooks: a layer costs a task group and a
# body re-stream, which made a trivial request 8x slower). `_http_hooks.add`
# keeps Starlette's ordering rule, which the comments at each site rely on:
# the hook added LAST runs OUTERMOST. Registered after GZip so it is outside
# it, as each hook's own layer was.
_http_hooks = HookChain()
app.add_middleware(BaseHTTPMiddleware, dispatch=_http_hooks.dispatch)
# Added first, so innermost: labels the request's SQLite writes for
# db/write_telemetry (outer hooks' writes after call_next see the label too).
from db import write_telemetry as _write_telemetry  # noqa: E402
_http_hooks.add(_write_telemetry.label_request_writes)

import llm_client as _llm_client  # noqa: E402  (the key-error handler below)


# Fansly writes we haven't wired raise FanslyAPIError. _proxy() only maps
# OFAPIError, so without this these surface as a generic 500 and the
# "isn't wired for Fansly yet" message never reaches the UI. Map it to a 502
# carrying the message. Registered defensively — Fansly may be absent.
try:
    import fansly_backend as _fansly_backend  # noqa: F401  (puts ../fansly on sys.path)
    from fansly_client import FanslyAPIError as _FanslyAPIError

    @app.exception_handler(_FanslyAPIError)
    async def _fansly_api_error_handler(request, exc):  # noqa: ANN001
        return JSONResponse(
            status_code=502,
            content={"ok": False, "error": "fansly", "detail": str(exc)},
        )
except Exception:
    log.warning("FanslyAPIError handler not registered", exc_info=True)


# An AI feature whose API key is missing, empty or rejected (401/403/402): one
# typed answer for every route, so the app shows one notification with the fix
# instead of each feature failing its own way. 424 Failed Dependency — unused
# elsewhere, and apart from 409 (free page) and 429 (daily cap).
@app.exception_handler(_llm_client.LLMKeyError)
async def _llm_key_error_handler(request, exc):  # noqa: ANN001
    log.warning("llm key error path=%s kind=%s provider=%s purpose=%s",
                request.url.path, exc.kind, exc.provider, exc.purpose)
    return JSONResponse(status_code=424,
                        content={"detail": _llm_client.key_error_payload(exc)})

# Phase A: employees CRUD + audit log routes (read-only browse + admin).
# Middleware registered below so every mutating call gets logged.
app.include_router(_employees_router)
app.include_router(_fans_router)
app.include_router(_fan_insights_router)
app.include_router(_messages_router)
app.include_router(_stats_router)
app.include_router(_transactions_router)
app.include_router(_vault_router)
app.include_router(_lists_router)
app.include_router(_automation_rules_router)
app.include_router(_translate_router)
app.include_router(_funnels_router)
app.include_router(_nudge_config_router)
app.include_router(_purchase_followup_config_router)
app.include_router(_auto_follow_router)
app.include_router(_lifecycle_message_config_router)
app.include_router(_priority_mass_router)
app.include_router(_split_inbox_router)
app.include_router(lane_config_api.router)
app.include_router(_autoreply_config_router)
app.include_router(_customs_router)
app.include_router(_vault_ai_router)
app.include_router(_style_config_router)
app.include_router(_account_config_router)
# In-product help bot (POST /admin/assistant/ask). Under /admin/* so it
# inherits the share-token gate + account-isolation middleware; chatters
# may ask (deliberately not in _CHATTER_BLOCKED_ADMIN_PREFIXES) and the
# handler derives their role server-side.
app.include_router(_assistant_router)
# Messages Pro's AI Copilot (POST /admin/copilot/{a}/{f}/suggest): reply
# suggestions only, never a send. Chatters reach it through Messages Pro.
app.include_router(_copilot_router)
# Per-agency LLM keys. Placed before the auth routers because it is
# session-gated by them: the signed-in owner is the only row it can touch.
app.include_router(_tenant_keys_router)
app.include_router(_tenant_keys_admin_router)
app.include_router(_ai_key_status_router)
# Settings → System (/admin/system/*): the master's read-only automation status
# + run log. Master-only by a router dependency; chatter-blocked by prefix.
app.include_router(_system_admin_router)
# Settings blobs (GET/PUT /admin/settings/{tab}); session-gated the same way.
app.include_router(_settings_router)
# The owner's agency notifications (/admin/agency-notifications); owner-only, chatter-blocked by prefix.
app.include_router(notifications_api.router)
# Employee groups (/admin/employee-groups), the Organization Chart's tree; owner-only, session-gated the same way.
app.include_router(_employee_groups_router)
app.include_router(_sensitive_words_router)
app.include_router(_scripts_import_router)
# Both /admin/shifts routers run the lazy Auto clock-out first (clock_api).
app.include_router(_shifts_router, dependencies=[Depends(_sweep_callers_agencies)])
app.include_router(_clock_router, dependencies=[Depends(_sweep_callers_agencies)])
# Reassign sales, one or a batch (Sales records, Shift records, the orphan lists); owner-only.
app.include_router(_sales_amend_router)
# Share for Share (/admin/s4s/profiles…, /admin/s4s/requests…, /admin/s4s/schedule, /admin/s4s/slots…,
# /admin/s4s/media…); owner-only, session-gated the same way. All four S4S routers expire the caller's past-due requests
# first (s4s_requests_api), as the /admin/shifts routers run the Auto clock-out.
app.include_router(_s4s_router, dependencies=[Depends(_expire_s4s_requests)])
app.include_router(_s4s_requests_router, dependencies=[Depends(_expire_s4s_requests)])
app.include_router(_s4s_schedule_router, dependencies=[Depends(_expire_s4s_requests)])
app.include_router(_s4s_media_router, dependencies=[Depends(_expire_s4s_requests)])
app.include_router(_auth_router)
# The sign-in form, personal 2FA, the sign-in 2FA step and Log out other sessions (/auth/sign-in, /auth/2fa/*, /auth/sessions/*).
app.include_router(_account_security_router)
app.include_router(_remote_login_router)
app.include_router(_auth_admin_router)
app.include_router(_auth_impersonate_router)
if fleet_api.enabled():  # /auth/fleet/whois only with a FLEET_SECRET, else 404 (fleet_api.py)
    app.include_router(fleet_api.router)
# Chatter principal — separate from User. /chatter/* is the chatter-facing
# auth surface; /admin/chatters/* is the owner-side link/unlink/invite UI.
# Order doesn't matter for routers; placed next to the auth pair so the
# two principals' surfaces sit together.
app.include_router(_chatters_router)
app.include_router(_chatters_admin_router)
# Growth surfaces: Smart Lists, Trial Links, Tracking Links (+ public /t/{slug}),
# Profile Promotion. Their /admin/* routes ride the existing admin rewrite +
# share-token gate; the public /t/{slug} redirect is exempted below.
app.include_router(_smart_lists_router)
app.include_router(_trial_links_router)
app.include_router(_tracking_links_router)
app.include_router(_of_tracking_router)
app.include_router(_link_metrics_router)
app.include_router(_promotions_router)
# Share links: owner routes under /admin/*, and the public report /share/{key}/data (exempted below).
app.include_router(_link_share_router)

# ── The one no-auth allowlist ───────────────────────────────────────
#
# Exact paths — never prefixes — that answer with NO share token and NO session.
# BOTH gates below consult this single set: `_share_token_gate` (the outer
# perimeter) and `_account_isolation_middleware` (the tenant gate). One decision
# stated once, because two copies is one place to forget when the decision
# changes.
#
# 🚨 `/lanes-panel/config` is an unauthenticated READ **and WRITE** of the
# process-wide concurrency ceilings. That is a deliberate operator choice for a
# friends-only deployment, not an oversight — `lane_config_api`'s module
# docstring carries the full reasoning and the blast radius being accepted.
#
# Built from the router's own constant rather than repeating the string, so a
# route rename cannot leave a stale hole in the gates. Exact match on purpose:
# a prefix would open every future route sharing the stem, which is how an
# allowlist stops being one.
#
# 🚨 `RESTART_PATH` is the destructive one: it ends this process so docker
# restarts it, which drops in-flight sends and the OF websocket pumps. It is
# open for the same reason as the other two — the panel must work without a
# login — and it is bounded where the others are not: two per hour, counted in
# a file that outlives the restart, refused unless this process is pid 1, and
# refused without a JSON body so a cross-origin page cannot fire it
# preflight-free. See `lane_config_api.restart_relay`.
#
# ⚠️ ALL THREE LIVE UNDER `/lanes-panel`, and since 2026-09-20 that prefix IS
# rewritten to this relay by `app/next.config.ts`, so these three paths are
# reachable from the open internet with no cookie — by the operator's explicit,
# repeated decision ("anyone that pastes https://your-host.example.com/lanes-panel gets the
# panel, no login, no token, no key"). The bounds that remain are on the
# handlers, not the gates: the on-disk restart budget, the JSON-body CSRF
# guard, restart-only application. Adding any OTHER path to this set is a
# separate decision; see the block comment in `lane_config_api`.
_UNAUTHENTICATED_PATHS = frozenset({
    lane_config_api.PATH,
    lane_config_api.PAGE_PATH,
    lane_config_api.RESTART_PATH,
})


# Tenant isolation. Every per-account request passes here: no principal at all is
# 401, and a principal naming an account it doesn't own is 403.
#
# ⚠️ ITS REGISTRATION SLOT IS LOAD-BEARING — see below. Until 2026-08-10 this was
# registered AFTER the two session middlewares, which in Starlette makes it the
# OUTERMOST, so it ran BEFORE either cookie had been resolved and `allowed_ids`
# was None on every real request. It abstained on None, so it had never once
# fired in production, and its suite stayed green only because the tests set
# `auth._request_user` by hand. Moving the registration is what makes the 403
# below real; do not move it back.
#
# It scans the URL for any OF account_id the principal doesn't own (as
# `?account_id=…` or as a numeric path segment), which catches per-account
# endpoints nobody wrapped with assert_account_owned(). False-positive domain:
# fan_ids and other numeric segments — only ids matching a real OF account row
# trigger the gate, so fan_ids that merely share the shape do not.
async def _account_isolation_middleware(request: Request, call_next):
    # Cheap pre-filter — only /admin/* and /api/of/* paths can possibly
    # reference per-account data. /auth/*, /events, /img, /ws/* never do.
    path = request.url.path
    if not (path.startswith("/admin/") or path.startswith("/api/of/")):
        return await call_next(request)

    # The Concurrency panel, deliberately open. None of these routes carry an
    # account_id — not in the path, not in the query, not in the response — so
    # exempting them takes nothing away from the tenant isolation this
    # middleware exists for. That holds for the restart route too: it names no
    # account, though it does stop every account's work at once, which is why
    # its own bounds live on the handler rather than here.
    #
    # ⚠️ Since they moved under `/lanes-panel`, the pre-filter above already
    # returns before this line is reached. The check is kept because it costs a
    # set lookup and it is what makes the exemption survive a future change to
    # either the prefix or the pre-filter.
    #
    # There is deliberately no `/admin/` twin of these: `/admin/:path*` is
    # rewritten from the public host, so an ungated one would be a public door.
    if path in _UNAUTHENTICATED_PATHS:
        return await call_next(request)

    # Pick the active principal's account_ids set. User wins precedence;
    # falls back to chatter's set-union if no user is signed in. Both
    # paths must be checked because the same account_id can be reached
    # via either cookie family.
    user = _get_request_user()
    if user is not None:
        allowed_ids: frozenset[str] | None = user.account_ids
    else:
        chatter = _get_request_chatter()
        allowed_ids = chatter.account_ids if chatter is not None else None
    if allowed_ids is None:
        # Nobody is signed in. This used to `return await call_next(request)` —
        # the same abstain-on-anonymous bug as `assert_account_owned`, and the
        # reason `GET /admin/accounts` answered 200 with no cookie in prod on
        # 2026-08-10. `assert_account_owned` alone is not enough: it guards only
        # routes someone remembered to wrap, and /admin/accounts is one of the
        # ~50 nobody did.
        if _allow_anonymous_account_access():
            return await call_next(request)
        return Response("sign in required", status_code=401)

    candidates: set[str] = set()
    qaid = request.query_params.get("account_id")
    if qaid:
        candidates.add(qaid)
    # Any numeric path segment in the OF account-id shape (5-12 digits).
    for seg in path.split("/"):
        if seg.isdigit() and 5 <= len(seg) <= 12:
            candidates.add(seg)
    if not candidates:
        return await call_next(request)

    # Own ids are subtracted first — a free set hit, so the common case never
    # touches the filesystem. `is_account` raises rather than guessing if it
    # can't read the tree: a gate that can't answer must not answer "allow".
    if any(account_registry.is_account(c) for c in candidates - allowed_ids):
        return Response("not your account", status_code=403)
    return await call_next(request)


# The one answer to an OF write for a deactivated Creator: the hook below, and
# `_proxy` when OFClient's own gate refuses it (OFDeactivatedError).
_DEACTIVATED_DETAIL = {
    "error": "account_deactivated",
    "message": "This Creator is deactivated. Activate it on Creators to use it again.",
}


async def _deactivated_write_guard(request: Request, call_next):
    """409 for an OF-proxy WRITE (`/api/of/*`, any method but a read) aimed at
    a deactivated Creator (`account_health.deactivate`). Reads stay open: the
    Creator's history is still the owner's to look at, and the app already
    drops it from the switcher and inbox, so a write here is a stale tab or a
    script. A hook rather than a check in `_resolve_account_id` because that
    is sync and the flag lives in the database, and because only writes are
    refused. The id checked is the one the route will use: the explicit one
    (header or ?account_id=), else the default-account fallback, which may
    still point at a deactivated Creator (the default is never moved: its
    file is shared across agencies). Every other OF write (the /admin/*
    routes, background jobs) is refused one layer down, in OFClient
    (`account_health.refuses_writes`); this hook only makes /api/of/'s a 409."""
    if request.method in ("GET", "HEAD", "OPTIONS") or not request.url.path.startswith("/api/of/"):
        return await call_next(request)
    aid = (request.headers.get("x-account-id") or request.query_params.get("account_id")
           or account_registry.get_active_account_id())
    if aid and await account_health.is_deactivated(aid):
        return JSONResponse(status_code=409, content={"detail": _DEACTIVATED_DETAIL})
    return await call_next(request)


# Audit middleware. Registered AFTER the share-token gate (below) on purpose
# — middlewares run in *reverse* registration order in starlette, so the
# share-token gate fires first, blocks unauthed requests, and only authed
# ones reach the audit writer. The decorator-registered middlewares below
# are added before this line, so we add this one via the imperative API to
# control ordering explicitly.
_http_hooks.add(_audit_middleware)

# Between audit and role: it runs after every gate has admitted the request
# (signed in, own account, role), so it never tells a stranger a Creator is
# off, and before the audit writer, so a refused write writes no `actions` row.
_http_hooks.add(_deactivated_write_guard)

# Role enforcement (permissions.py). Registered after audit, so it runs before
# it: a refused request reaches no handler and writes no `actions` row. It runs
# inside both session middlewares, so it sees the chatter they resolved.
_http_hooks.add(role_enforcement_middleware)

# Tenant isolation. Registered here — BEFORE both session middlewares — so that
# it RUNS AFTER them (Starlette: last registered = outermost) and can see the
# principal they set. Registered below them, as it was until 2026-08-10, it runs
# before either cookie is read, sees no principal, and silently does nothing.
_http_hooks.add(_account_isolation_middleware)

# Chatter session middleware — registered BEFORE the User session
# middleware so on the inbound path it runs AFTER auth (Starlette runs
# user-added middlewares in reverse registration order). That ordering
# lets the chatter middleware's admin-gate read `get_request_user()` and
# only fire when no User cookie is present, while still landing both
# contextvars before the audit middleware's post-block resolves them.
_http_hooks.add(_chatter_session_middleware)

# Friend-auth session middleware. Same ordering trick: registered here so
# it runs *inside* the share-token gate (gate fires first, rejects unauthed
# requests; only then does this middleware read the session cookie and
# populate _request_user for _resolve_account_id).
_http_hooks.add(_auth_session_middleware)


# ── Share-link gate ────────────────────────────────────────────
# Optional extra gate in front of everything: when a token is set, only
# requests carrying it via ?t=... or the share_token cookie get through. Off
# by default (empty) — access is via friend-auth / chatter sign-in sessions.
# Turn it on with the SHARE_TOKEN env var or Setup → Keys (the stored secret
# wins, see _effective_share_token). /health is always open so load balancers
# can probe it.
SHARE_TOKEN = os.environ.get("SHARE_TOKEN", "").strip()
_SHARE_COOKIE = "share_token"


def _effective_share_token() -> str:
    """The live access token: a value set via Setup → Keys (secrets.json) wins,
    else the env/module default. Read per-request so the UI can set/clear the
    gate without a relay restart."""
    try:
        s = secrets_store.stored("SHARE_TOKEN")
        if s:
            return s
    except Exception:  # never let the gate crash on a bad store
        pass
    return SHARE_TOKEN


# Stash the current Request so deep helpers (_get_client) can pick up the
# X-Account-Id header without us having to add `request: Request` to every
# one of the ~60 endpoint signatures. Set by the middleware below.
_request_ctx: ContextVar[Request | None] = ContextVar("of_relay_request", default=None)


@_http_hooks.add
async def _account_context(request: Request, call_next):
    """Make the current Request available to non-endpoint code paths
    (notably _get_client → _resolve_account_id) via a ContextVar. The token
    is reset in `finally` so the contextvar doesn't leak between requests."""
    token = _request_ctx.set(request)
    try:
        return await call_next(request)
    finally:
        _request_ctx.reset(token)


# Path prefixes reachable WITHOUT the share token. Keep this an explicit,
# annotated allowlist rather than a chain of `if startswith(...)` — every entry
# is a deliberate hole in the gate and they belong where they can be read
# together:
#   /auth/     a brand-new friend registers / signs in from the landing page,
#              so they cannot yet hold any cookie.
#   /chatter/  a chatter following an owner-issued invite link arrives cold.
#   /t/        the public tracking-link redirect (Growth → Tracking Links) — a
#              FAN clicks this from the creator's bio; it records the click and
#              302s.
#   /share/    a Share link's report (Growth → Free trial links / Tracking
#              links → Share links), for someone outside the agency. Its one
#              route answers only to an unguessable per-share secret, reads one
#              row and calls nothing (link_share_api). EVERY route under /share/
#              is public: put nothing else there.
_PUBLIC_PREFIXES = ("/auth/", "/chatter/", "/t/", "/share/")


@_http_hooks.add
async def _share_token_gate(request: Request, call_next):
    share_token = _effective_share_token()
    if not share_token:
        return await call_next(request)
    if request.url.path == "/health" or request.url.path == "/livez":
        return await call_next(request)
    if request.url.path.startswith(_PUBLIC_PREFIXES):
        return await call_next(request)
    if request.url.path in _UNAUTHENTICATED_PATHS:
        return await call_next(request)
    if request.cookies.get(_SHARE_COOKIE) == share_token:
        return await call_next(request)
    # Anyone carrying a friend-auth OR chatter session cookie has already
    # cleared username+password — the legacy share-token gate is
    # redundant for them. (The session middlewares validate the HMAC +
    # DB row downstream.)
    if request.cookies.get(_AUTH_COOKIE_NAME) or request.cookies.get(_CHATTER_COOKIE_NAME):
        return await call_next(request)
    if request.query_params.get("t") == share_token:
        resp = await call_next(request)
        # Persist the token so subsequent fetch() calls (which won't carry ?t=)
        # still authenticate. 7-day TTL is plenty for an ad-hoc share session.
        resp.set_cookie(
            _SHARE_COOKIE, share_token,
            max_age=7 * 24 * 3600, httponly=True, samesite="lax",
        )
        return resp
    # `no-store` on the REFUSAL, for every path the gate guards — not just the
    # two static prefixes a retired middleware happened to stamp. An
    # unauthorized answer is per-request by nature and must never be held by a
    # browser or a shared proxy; a cached 401 would outlive the token that
    # fixes it. (401 is not heuristically cacheable, so this is belt-and-
    # suspenders — but it is the belt the /ui prefix used to get by accident.)
    return Response("unauthorized — link missing or expired", status_code=401,
                    headers={"Cache-Control": "no-store"})


# ── Setup → Keys: UI-writable secret/key store ─────────────────────
# Lets the FOUNDER paste the deployment's DeepSeek key, Drive API key,
# access password, etc. instead of editing the VPS .env. Values land in
# service/secrets.json and every consumer checks the store before the env, so
# they take effect on the next call with no restart. GET never returns raw
# secrets — only a masked status.
#
# MASTER ONLY, both verbs. These are the SERVER's house keys, not a tenant's —
# distinct from /admin/my-llm-keys, which is one agency's own. A comment here
# used to claim "both sit under /admin/* (already gated)"; that was FALSE and
# had been since the routes were written. Nothing gated them: the account-
# isolation middleware returns early on a path with no account id, the
# share-token gate waves through any auth cookie, and /auth/register is open —
# so any signed-in agency could read the masked house-key status AND overwrite
# the deployment's credentials. The read is gated too, because the masked hint
# still leaks the last four characters of every house key.


@app.get("/admin/secrets")
def admin_secrets_status() -> dict[str, Any]:
    """Masked status of every UI-settable key (set?/source/hint — never the
    raw value). Master only."""
    _require_master()
    return {"keys": secrets_store.status()}


@app.put("/admin/secrets")
async def admin_secrets_set(request: Request) -> dict[str, Any]:
    """Set or clear keys. Body is a flat JSON object {KEY: value, …}; an empty
    string or null clears that key. Unknown keys are ignored. Returns the new
    masked status. Master only."""
    _require_master()
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="expected a JSON object of key→value")
    try:
        secrets_store.set_many({str(k): v for k, v in body.items()})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"keys": secrets_store.status()}


# ── /tmp/of-api.log — dedicated single-file access log ─────────────
# Every HTTP request that makes it past the share-token gate gets one
# line here. Pure text (no binary bytes from upstream stream bodies
# the way uvicorn's mixed log can have), append-only, so the user can
# `tail -f /tmp/of-api.log` and see live API traffic without needing
# grep -a flags. The access timing is measured around `call_next` so
# it includes all our middleware + the handler + StreamingResponse
# generator startup.
#
# Written OFF the event loop: the hook only queues the line, and one daemon
# thread appends whatever has queued, one open+write+close per burst. It used
# to `open()` the file on the loop for every request — a syscall triple each,
# and a stall for every request in flight whenever the disk was slow. The
# file is still reopened per burst, so deleting or rotating it just works. A
# full queue (the disk gone for a long while) drops lines, never blocks.
_API_LOG_PATH = os.environ.get("OF_API_LOG_PATH") or "/tmp/of-api.log"
_API_LOG_QUEUE_MAX = 10_000
import queue as _queue_mod
import time as _time_mod

_api_log_queue: "_queue_mod.Queue[str]" = _queue_mod.Queue(maxsize=_API_LOG_QUEUE_MAX)


_api_log_write_lock = threading.Lock()   # one appender at a time: writer vs exit flush


def _api_log_write(lines: list[str]) -> None:
    """Append `lines` plus everything queued behind them, in queue order."""
    with _api_log_write_lock:
        while True:
            try:
                lines.append(_api_log_queue.get_nowait())
            except _queue_mod.Empty:
                break
        if not lines:
            return
        try:
            with open(_API_LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write("".join(lines))
        except Exception:
            pass


def _api_log_writer() -> None:
    while True:
        _api_log_write([_api_log_queue.get()])


threading.Thread(target=_api_log_writer, name="api-access-log", daemon=True).start()
# The writer is a daemon thread, killed at exit: write out what is still queued
# first, so the last requests before a shutdown are in the log.
atexit.register(lambda: _api_log_write([]))

# A share link's URL carries its secret (/share/<id>.<secret>/data): no log keeps it.
_SHARE_SECRET = re.compile(r"(/share/[^./?\s]*)\.[^/?\s]*")


def redact_share_secret(text: str) -> str:
    return _SHARE_SECRET.sub(r"\1.<secret>", text)


class _RedactShareSecret(logging.Filter):
    """uvicorn's access line ("GET /share/7.<secret>/data") without the secret."""
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(redact_share_secret(a) if isinstance(a, str) else a for a in record.args)
        return True


logging.getLogger("uvicorn.access").addFilter(_RedactShareSecret())


@_http_hooks.add
async def _api_access_log(request: Request, call_next):
    started = _time_mod.monotonic()
    response = None
    status = 0
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    except HTTPException as exc:
        status = exc.status_code
        raise
    except Exception:
        status = 500
        raise
    finally:
        ms = int((_time_mod.monotonic() - started) * 1000)
        # Strip the share token from the logged URL — even though the file
        # is local-only, no need to mirror it on every line.
        url = str(request.url)
        if "?t=" in url:
            url = url.split("?t=", 1)[0] + (
                "?" + url.split("?", 1)[1].split("&", 1)[1]
                if "&" in url.split("?", 1)[1] else ""
            )
        elif "&t=" in url:
            head, tail = url.split("&t=", 1)
            rest = tail.split("&", 1)[1] if "&" in tail else ""
            url = head + (("&" + rest) if rest else "")
        url = redact_share_secret(url)
        ts = datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
        line = f"{ts} {request.method:6s} {status} {ms:5d}ms {url}\n"
        try:
            _api_log_queue.put_nowait(line)
        except _queue_mod.Full:
            pass


@_http_hooks.add
async def _persist_unhandled_errors(request: Request, call_next):
    """Catch unhandled server-side exceptions, persist a row in app_errors
    (so /admin/errors surfaces them), then re-raise so FastAPI's default
    500 response still fires. HTTPException is intentionally NOT caught —
    those are deliberate, structured replies, not bugs."""
    try:
        return await call_next(request)
    except HTTPException:
        raise
    except Exception as exc:
        import traceback as _tb
        try:
            from db.engine import get_session
            from db.models import AppError as _AE
            _scrub = proxy_registry.scrub_pool_secrets   # /admin/errors is not tenant-filtered
            stack = _scrub("".join(_tb.format_exception(type(exc), exc, exc.__traceback__)))[:16384]
            account_id = request.headers.get("x-account-id")
            emp_hdr = request.headers.get("x-employee-id")
            try:
                employee_id = int(emp_hdr) if emp_hdr else None
            except ValueError:
                employee_id = None
            async with get_session() as s:
                s.add(_AE(
                    source="server",
                    kind=type(exc).__name__[:64],
                    message=_scrub(str(exc))[:4096],
                    stack=stack,
                    url=str(request.url)[:1024],
                    account_id=account_id[:64] if account_id else None,
                    employee_id=employee_id,
                    user_agent=(request.headers.get("user-agent") or "")[:512] or None,
                ))
                await s.commit()
        except Exception:
            # Don't let the logger crash the response path on top of the
            # original error — just log and move on.
            log.exception("failed to persist server-side error to app_errors")
        # OF's definite session-death signature ("Wrong user." — the creator
        # got unlinked) pauses the account's automations right away and drops
        # the pooled client, so a session re-captured on disk is picked up on
        # the next request without a restart. See service/account_health.py.
        try:
            dead_reason = account_health.is_session_dead_error(exc)
            aid = (request.headers.get("x-account-id")
                   or request.query_params.get("account_id"))
            if dead_reason and aid:
                _invalidate_client(aid)
                if await account_health.mark_session_dead(aid, dead_reason):
                    log.warning(
                        "account_session_dead account=%s via=%s — automations "
                        "paused until the session recovers",
                        aid, request.url.path,
                    )
        except Exception:
            log.exception("failed to mark session-dead account")
        raise


# The OFClient pool lives in client_pool (shared with the automation lane).
# Hot-reload via /admin/reload-session?account_id=... or by re-bootstrapping.

# ── Realtime event bus ─────────────────────────────────────────
# We connect ONCE to OF's WebSocket (wss://ws2.onlyfans.com/ws3/N) at startup
# and fan every event out to (a) browser clients on /events (SSE) and (b) any
# local subscribers (CLI tailer, future plugins).
# Subscribers are asyncio.Queue instances; if a queue is full, we drop the
# oldest message rather than block the producer.

_event_subscribers: set[asyncio.Queue] = set()
_event_stats: dict[str, Any] = {
    "received": 0,
    "by_type": {},
    "by_account": {},
    "started_at": None,
    "last_event_ts": None,
    "subscribers": 0,
}

async def _broadcast_event(event: dict) -> None:
    """Push an event to every subscriber queue and the SSE module."""
    _event_stats["received"] += 1
    _event_stats["last_event_ts"] = __import__("time").time()
    if isinstance(event, dict):
        for k in event:
            if k.startswith("__"):  # don't tally our own meta-keys
                continue
            _event_stats["by_type"][k] = _event_stats["by_type"].get(k, 0) + 1
        aid = event.get("__account_id")
        if aid:
            _event_stats["by_account"][aid] = _event_stats["by_account"].get(aid, 0) + 1
    _event_stats["subscribers"] = len(_event_subscribers)

    dead: list[asyncio.Queue] = []
    for q in _event_subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # Drop oldest, push new — better than blocking the OF pump
            with contextlib.suppress(asyncio.QueueEmpty):
                q.get_nowait()
            try:
                q.put_nowait(event)
            except Exception:
                dead.append(q)
    for q in dead:
        _event_subscribers.discard(q)

    # Phase A: also fan into the SSE module + persist to event_inbox. Wrapped
    # in try/except because we never want a SQL hiccup to break the legacy
    # WS broadcast — those subscribers were already served above.
    try:
        await _sse_handle_event(event)
    except Exception:
        log.exception("SSE handle_event failed")


# One WebSocket pump per account. Events are tagged with `__account_id` +
# `__account_name` before broadcast so subscribers (the UI) can route
# or filter by account. The pumps dict is mutated only by the helpers below.
_account_pumps: dict[str, asyncio.Task] = {}
_supervisor_task: asyncio.Task | None = None
_tx_ingest_task: asyncio.Task | None = None
_tx_fast_task: asyncio.Task | None = None
# Automation executor supervisor (service/automation_executor.py) — consumes
# scheduled_jobs / automation_rules and runs the 12 automations. Cancelled in
# _stop_event_pumps alongside _tx_ingest_task.
_automation_exec_task: asyncio.Task | None = None
# W7 (0): seed the inbox with each account's chat links ONCE on startup so the
# bot has conversation links to react to; webhooks carry deltas after that.
# Guarded so a re-entered startup can't double-enqueue the scrape sweep.
_chat_links_seeded: bool = False
# The asyncio loop the app is running on. Captured at startup so sync FastAPI
# endpoints (which run in the threadpool, with NO running loop in the worker
# thread) can schedule pump start/stop via `call_soon_threadsafe`.
_main_loop: asyncio.AbstractEventLoop | None = None


# ── The one periodic-task loop ────────────────────────────────────────
#
# Six background sweepers (img cache, storyboard locks, perflog, raw_json,
# audit retention, payload size cap) were six hand-copied transcriptions of the
# same eight lines: loop, sleep, work, swallow-and-log, return on cancel. Copies
# do not stay identical, and the way this one drifted was expensive.
#
# Every copy slept BEFORE its first pass. For the hourly sweepers that is
# invisible. For the two DAILY ones it meant the sweep only ever ran on a
# process that stayed up longer than a day — and this relay is redeployed,
# autohealed and restarted far more often than that. So the result was not a
# late prune, it was NO prune, ever, silently, on precisely the tables whose
# only job is to stay bounded. Measured on the live DB 2026-08-25, every window
# long blown:
#
#     scheduled_jobs     retain  7d  → rows back to 45d  (263,790)
#     automation_runs    retain 14d  → rows back to 20d  (409,479)
#     messages.raw_json  retain 60d  → 3,668 rows still holding payloads
#
# That unbounded job table is what turned an unindexed lookup into the
# 6.7s-per-supervisor-tick scan the indexes in db/models.py now fix; this loop
# is what stops it growing back.
#
# Hence one implementation, with `first_after_s` as a NAMED ARGUMENT rather than
# a mutable each caller re-derives. The point is not that eight lines are saved
# six times over — it is that "when does the first pass happen" is now a
# decision each sweeper states out loud at its call site, instead of an
# emergent property of a loop nobody re-reads.
async def _periodic(
    label: str,
    interval_s: float,
    work: Callable[[], Awaitable[None]],
    *,
    first_after_s: float | None = None,
) -> None:
    """Run `work()` every `interval_s` seconds, forever.

    The first pass happens `first_after_s` from now — defaulting to a full
    interval, which is what every caller used to hardcode. Sweepers whose
    interval outruns the process's own uptime pass a short boot grace instead,
    so they run soon after startup and then settle onto their cadence.

    `work` owns its own logging of what it did; this owns only the failure path.
    A raised exception is logged and the cadence continues — one bad cycle must
    never take a sweeper down for the life of the process. Cancellation returns
    cleanly so `_stop_event_pumps` can tear these down at shutdown.
    """
    delay = interval_s if first_after_s is None else first_after_s
    while True:
        try:
            await asyncio.sleep(delay)
            delay = interval_s
            await work()
        except asyncio.CancelledError:
            return
        except Exception:
            log.warning("%s cycle failed", label, exc_info=True)


async def _ws_pump_for_account(account_id: str) -> None:
    """Run the realtime WS pump for one account until cancelled. Both the OF
    and Fansly sockets carry their own reconnect-with-backoff loop, so this
    task is only torn down when the account is removed or the server is
    shutting down."""
    from of_ws import OFWebSocket, SessionDead, register_pump, unregister_pump
    # A deactivated Creator gets no socket, whichever path spawned this
    # (`_restart_account_pump` after a re-capture, the startup spawn, or a
    # supervisor pass that read the roster just before the deactivate). A
    # pump already connected when the flag lands is cancelled by the
    # deactivate endpoint itself; the supervisor reaps any stragglers.
    if await account_health.is_deactivated(account_id):
        log.info("ws-pump[%s]: not started, the Creator is deactivated", account_id)
        return
    while True:
        try:
            client = _load_client(account_id)
            meta = account_registry.get_account(account_id) or {}
            nickname = meta.get("nickname") or account_id
            color = meta.get("color")
            # Seam 3 of 3 (HTTP client, automation client, WS pump). Fansly's
            # socket is a different protocol end to end — wsv3, in-band auth,
            # triple-encoded frames — but FanslyWebSocket presents the same
            # interface and yields the same OF-shaped events, so everything
            # below this branch is platform-blind.
            platform = account_registry.get_platform(account_id)
            if platform == "fansly":
                from fansly_ws import FanslyWebSocket
                ws = FanslyWebSocket(client)
            else:
                ws = OFWebSocket(client, session_dead=account_health.is_session_dead_error)
            # Publish this live pump so the automation layer can push outbound
            # frames (e.g. the typing indicator) on the same socket. Both
            # platforms share this registry, so `of_ws.emit_typing` finds a
            # Fansly pump the same way (it routes typing over REST).
            register_pump(account_id, ws)
            log.info("ws-pump[%s]: connecting to %s", nickname,
                     "Fansly" if platform == "fansly" else "OF")
            try:
                async for event in ws.events():
                    # Tag every event so multi-account subscribers can route.
                    # Use sentinel `__` keys so we never collide with real OF event names.
                    if isinstance(event, dict):
                        event = {
                            "__account_id": account_id,
                            "__account_name": nickname,
                            "__account_color": color,
                            **event,
                        }
                    await _broadcast_event(event)
            finally:
                unregister_pump(account_id, ws)
        except SessionDead as e:
            # OF rejected the session (e.g. it wants a 2FA code): pause the
            # account like any other caller that hit it, and stop. The
            # supervisor starts no pump while it is flagged; a re-login
            # (post_bootstrap_hooks) or the recovery probe clears the flag and
            # the next start loads the fresh session.
            _invalidate_client(account_id)
            if await account_health.mark_session_dead(account_id, e.reason):
                log.warning("account_session_dead account=%s via=ws-pump reason=%s — automations "
                            "paused until the session recovers", account_id, e.reason)
            log.info("ws-pump[%s]: parked, the session is dead (%s)", account_id, e.reason)
            return
        except HTTPException as e:
            log.warning("ws-pump[%s]: %s — retry in 30s", account_id, e.detail)
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("ws-pump[%s] unexpected: %s — retry in 10s", account_id, e)
            await asyncio.sleep(10)


def _start_account_pump(account_id: str) -> None:
    """Spawn a pump for an account if one isn't already running.

    Safe to call from BOTH the event loop and from a worker thread (FastAPI
    sync endpoints run in the threadpool, where `asyncio.create_task` raises
    `RuntimeError: no running event loop`). From a thread we trampoline back
    to the main loop via `call_soon_threadsafe`.
    """
    try:
        asyncio.get_running_loop()
        _do_start_account_pump(account_id)
    except RuntimeError:
        if _main_loop is None:
            # Startup hasn't run yet; the supervisor / startup hook will
            # eventually spawn this pump. Drop silently rather than crash.
            return
        _main_loop.call_soon_threadsafe(_do_start_account_pump, account_id)


def _do_start_account_pump(account_id: str) -> None:
    """Inner: must be called from inside the event loop."""
    task = _account_pumps.get(account_id)
    if task and not task.done():
        return
    _account_pumps[account_id] = asyncio.create_task(
        _ws_pump_for_account(account_id), name=f"ws-pump-{account_id}",
    )


def _stop_account_pump(account_id: str) -> None:
    """Cancel an account's pump. `.cancel()` is documented to be safe from
    any thread, but the dict pop and the task reference both want the loop;
    we trampoline for symmetry with _start_account_pump."""
    try:
        asyncio.get_running_loop()
        _do_stop_account_pump(account_id)
    except RuntimeError:
        if _main_loop is None:
            return
        _main_loop.call_soon_threadsafe(_do_stop_account_pump, account_id)


def _do_stop_account_pump(account_id: str) -> None:
    task = _account_pumps.pop(account_id, None)
    if task and not task.done():
        task.cancel()


def _restart_account_pump(account_id: str) -> None:
    _stop_account_pump(account_id)
    _start_account_pump(account_id)


def _reroute_account_pump(account_id: str) -> None:
    """Restart an account's pump if one is running, so its socket reconnects
    on the account's current proxy. No pump → nothing to do: the supervisor's
    start reads the new route. Thread-safe like _start_account_pump."""
    try:
        asyncio.get_running_loop()
        _do_reroute_account_pump(account_id)
    except RuntimeError:
        if _main_loop is None:
            return
        _main_loop.call_soon_threadsafe(_do_reroute_account_pump, account_id)


def _do_reroute_account_pump(account_id: str) -> None:
    task = _account_pumps.get(account_id)
    if task is None or task.done():
        return
    log.info("ws-pump[%s]: proxy changed, reconnecting on the new route", account_id)
    _do_stop_account_pump(account_id)
    _do_start_account_pump(account_id)


def _on_proxy_switched(account_ids: list[str]) -> None:
    """proxies.save's hook, for every write that changes an account's egress
    (Change proxy, Inflowwww proxy, No proxy, a proxy edit, the pool sync):
    the pooled client goes and a live chat socket reconnects, so REST and the
    WS leave from the same IP from now on, not after the next relay restart."""
    for aid in account_ids:
        _invalidate_client(aid)
        _reroute_account_pump(aid)


proxy_registry.on_switch(_on_proxy_switched)


async def _pump_supervisor() -> None:
    """Reconcile the set of running pumps against the set of accounts every
    15s (`_reconcile_pumps`)."""
    while True:
        try:
            await _reconcile_pumps()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("supervisor pass failed")
        await asyncio.sleep(15)


async def _reconcile_pumps() -> None:
    """One supervisor pass. Picks up newly-bootstrapped accounts without needing
    an explicit 'start pump' call from the bootstrap endpoint, and reaps pumps
    for deleted and deactivated accounts. Also restarts any pump that crashed
    unexpectedly. A session-dead account is parked: no pump is started or
    restarted for it (its pump exits on the dead session, see
    _ws_pump_for_account) until the flag clears."""
    off = await account_health.deactivated_ids()
    current_ids = {a["id"] for a in account_registry.list_accounts()
                   if a.get("has_session") and a["id"] not in off}
    parked = set(await account_health.dead_session_map())
    # Start missing
    for aid in current_ids - parked:
        _start_account_pump(aid)
    # Stop pumps whose account vanished or was deactivated
    for aid in list(_account_pumps.keys()):
        if aid not in current_ids:
            _stop_account_pump(aid)
            continue
        task = _account_pumps[aid]
        if task.done() and not task.cancelled() and aid not in parked:
            log.warning("ws-pump[%s] task exited — restarting", aid)
            _restart_account_pump(aid)


# Background tasks the relay owns for its own lifetime. CPython keeps only a
# WEAK reference to a task returned by create_task, so a fire-and-forget task
# can be garbage-collected mid-flight — for a vault import that means the run
# vanishes silently with its carriers still live, which is the one failure the
# whole crash-safety design exists to prevent. Hold the reference until it is
# actually done.
_bg_tasks: set[asyncio.Task] = set()


def _spawn_bg(coro, name: str) -> asyncio.Task:
    task = asyncio.create_task(coro, name=name)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


@app.on_event("startup")
async def _close_streams_on_term() -> None:
    """SIGTERM ends every open SSE stream before uvicorn's graceful wait, and
    no automation run or send starts after it.

    uvicorn installs its exit handler before startup hooks run, so this wraps
    it: streams close first (events.close_streams) and the automation lane
    stops claiming (automation_executor.stop_claiming; the shutdown drain waits
    for what it already claimed), then uvicorn stops as before. Without it each
    open stream holds the wait to its timeout and is cancelled, and new sends
    start during that wait. Not behind the test-mode guard: slop stops the relay
    with it."""
    import signal
    import events
    import automation_executor
    prev = signal.getsignal(signal.SIGTERM)
    if not callable(prev):
        return

    def _on_term(sig, frame):
        events.close_streams()
        automation_executor.stop_claiming()
        prev(sig, frame)

    signal.signal(signal.SIGTERM, _on_term)


@app.on_event("startup")
async def _start_event_pumps() -> None:
    global _supervisor_task, _tx_ingest_task, _tx_fast_task, _automation_exec_task, _main_loop
    _main_loop = asyncio.get_running_loop()
    _event_stats["started_at"] = __import__("time").time()

    # Inflowwww proxy pool, before anything below (vault sweep, pumps, the
    # automation lane) can load an OFClient, so every client is built with the
    # synced binding. Registry-file only (no network). Not behind the test-mode
    # guard (the local stack runs with CHATTERLY_TEST_MODE=1); with the env
    # unset and no pool it writes nothing, and the test harness unsets it.
    try:
        _sync_proxy_pool()
    except Exception:
        log.exception("Inflowwww proxy pool sync failed — pool unchanged")

    # Vault-import crash recovery, FIRST and off the loop, then hourly. A batch
    # that died mid-flight can have left a scheduled carrier post on a real
    # creator's feed; left alone it publishes on its postedAt date. Boot alone
    # is not a schedule — this container runs for weeks and a carrier is 30 days
    # out, so a session that went stale mid-run would otherwise be retried once,
    # never, at a restart that never comes. Best-effort by design: a sweep
    # failure must never stop the relay from booting.
    async def _vault_sweep_once() -> None:
        try:
            res = await asyncio.to_thread(vault_upload.sweep, _load_client)
            if res.get("carriers_failed"):
                log.error("vault sweep: %d orphaned carrier(s) could NOT be "
                          "deleted — check scheduled posts", res["carriers_failed"])
        except Exception as e:  # noqa: BLE001
            log.warning("vault sweep failed: %s", e)

    async def _vault_sweep_loop() -> None:
        while True:
            await _vault_sweep_once()
            await asyncio.sleep(3600)
    _spawn_bg(_vault_sweep_loop(), "vault-sweep")

    # Bump the anyio thread pool. `/img` is a sync streaming endpoint —
    # each in-flight video / avatar fetch holds one thread for as long as
    # the browser keeps the stream open. With hover-preview, scrub seeks,
    # the chat-list avatars, vault thumbnails and notification polls all
    # sharing the default ~40-thread pool, the relay would exhaust threads
    # and start dropping requests (ECONNRESET storms on the Next side).
    # 200 gives plenty of headroom; each thread is cheap and idle when no
    # stream is active.
    try:
        import anyio
        anyio.to_thread.current_default_thread_limiter().total_tokens = 200
        log.info("anyio thread pool bumped to 200")
    except Exception:
        log.exception("could not bump anyio thread pool — sticking with default")

    # Bump the ASYNCIO default executor too — a SEPARATE pool from anyio's.
    # Every `asyncio.to_thread` in this codebase (all `_proxy` OF calls, the
    # automation executor's OF roundtrips, media pulls) shares the loop's
    # default ThreadPoolExecutor, which sizes at min(32, cpus+4) — just 6
    # threads on the 2-CPU VPS. A couple of long automation sweeps pinned
    # all 6 and every user-initiated send queued invisibly until the Next
    # proxy gave up (2026-07-04 "socket hang up" / HTTP 500 incident). The
    # threads only block on network I/O; see `_EXECUTOR_THREADS` for the size.
    try:
        from concurrent.futures import ThreadPoolExecutor
        _main_loop.set_default_executor(
            ThreadPoolExecutor(max_workers=_EXECUTOR_THREADS,
                               thread_name_prefix="to-thread")
        )
        log.info("asyncio default executor bumped to %d threads", _EXECUTOR_THREADS)
    except Exception:
        log.exception("could not resize asyncio default executor — default is min(32, cpus+4)")

    # Phase A — bring up SQLite. Idempotent: creates tables on first boot,
    # no-ops on subsequent. Must precede pump spawn because the SSE writer
    # below tries to insert event_inbox rows from the first event onward.
    try:
        await db_init()
        log.info("db ready (DATABASE_URL=%s)", _redact(os.environ.get("DATABASE_URL", "(default)")))
    except Exception:
        log.exception("db_init failed — relay will run but SSE/inbox writes will error")

    # Settings → System's runtime switch overrides (runtime_switches), into the
    # in-process cache every consumer reads; none loaded = env / defaults.
    import runtime_switches
    try:
        await runtime_switches.load()
    except Exception:
        log.exception("runtime switch overrides not loaded: env / defaults apply; retrying in the background")
        _spawn_bg(runtime_switches.load_until_loaded(), "runtime-switches-load")

    # OFClient's deactivated-Creator write gate (account_health.refuses_writes),
    # filled once; deactivate/activate keep it after. The vault sweep spawned
    # above only removes carriers, which the gate lets through anyway.
    try:
        await account_health.load_write_gate()
    except Exception:
        log.exception("deactivated Creators not loaded: their OF writes are NOT refused until a restart")

    # Pre-add the default "strokes" funnel (once per box, insert-if-missing by
    # name — never overwrites an edited one, never resurrects a deleted one).
    try:
        from seeds.funnels import seed_defaults_once
        added = await seed_defaults_once()
        if added:
            log.info("default funnels added: %s", ", ".join(added))
    except Exception:
        log.exception("default funnel seed failed — Funnel follow-up stays empty "
                      "until a funnel is created by hand")

    try:
        import settings_api
        n = await settings_api.migrate_role_enforcement_once()
        log.info("role enforcement default: %d login(s) given Admin", n)
    except Exception:
        log.critical("ROLE ENFORCEMENT MIGRATION FAILED: existing logins were not given Admin, so any "
                     "holding no role are refused every page; it retries on the next start", exc_info=True)
    try:
        n = await settings_api.migrate_bookmarks_page_once()
        log.info("bookmarks page: %d stored role(s) granting Collections given Bookmarks", n)
    except Exception:
        log.critical("BOOKMARKS PAGE MIGRATION FAILED: stored roles granting Collections are refused "
                     "Bookmarks; it retries on the next start", exc_info=True)

    # TEST-MODE GUARD — db init above already ran (prod-critical at startup);
    # everything BELOW is the spawn/network section (persist worker, WS pumps,
    # pump-supervisor, live_rev network refresh, evictors, tx-ingest,
    # automation-exec). Tests neither exercise the WS path nor want OF/network
    # round-trips, so skip the whole section. MUST stay AFTER db_init — moving
    # it above would leave the schema uninitialized. (Belt-and-suspenders: the
    # harness also no-ops this function and live_rev.refresh post-import.)
    from automations._common import test_mode
    if test_mode():
        log.info("CHATTERLY_TEST_MODE=1 — skipping pump/supervisor/network spawns")
        return

    # Start the bounded persist worker BEFORE pumps spawn. Otherwise the
    # first burst of events takes the pre-startup fallback path in
    # events.handle_event (unbounded create_task), which is exactly what
    # this worker exists to avoid.
    _start_persist_worker()

    # Spawn pumps for every existing account with a session (not deactivated)
    off = await account_health.deactivated_ids()
    for meta in account_registry.list_accounts():
        if meta.get("has_session") and meta["id"] not in off:
            _start_account_pump(meta["id"])
    _supervisor_task = asyncio.create_task(_pump_supervisor(), name="pump-supervisor")
    log.info("event pumps started for %d account(s)", len(_account_pumps))

    # Seed the live OF build hash from the session files so sign_rules and
    # /admin/rev/live have a value before the first OF response lands. Off-thread
    # so reading every session file doesn't block FastAPI startup.
    asyncio.get_running_loop().run_in_executor(None, live_rev.refresh)

    # Periodic GC of `_storyboard_locks` — the prune cron clears the on-disk
    # storyboard dirs but the in-memory lock entries would otherwise leak
    # ~200 bytes per unique video ever hovered. Eviction is conservative:
    # only drops locks whose dir is gone AND whose `acquire(blocking=False)`
    # succeeds, so it never races with an active build.
    asyncio.create_task(_storyboard_evictor_loop(), name="storyboard-evictor")

    # Periodic TTL sweep of the on-disk /img cache. Keys are host+path
    # so entries are shared across all accounts/users — the sweep just
    # drops anything older than _IMG_CACHE_TTL_S by mtime.
    asyncio.create_task(_img_cache_evictor_loop(), name="img-cache-evictor")

    # Prune of `perf_events` so the client-side perflog ingest table
    # stays bounded. Retain window via PERFLOG_RETAIN_S (default 7d).
    asyncio.create_task(_perflog_evictor_loop(), name="perflog-evictor")

    # Cap DB growth: NULL out messages.raw_json older than _RAW_JSON_RETAIN_S
    # (default 60d). The payloads are a write-only migration buffer; left
    # unbounded they grew the DB to ~1.9 GB. Daily ticks.
    asyncio.create_task(_raw_json_evictor_loop(), name="raw-json-evictor")

    # Hard SIZE ceiling on the two raw-OF-payload columns (event_inbox +
    # messages.raw_json) so the SQLite file stays well under ~2 GB even when
    # VOLUME, not age, is the problem. Drives off logical SUM(LENGTH(...)),
    # evicts oldest-first down to PAYLOAD_BUDGET_BYTES (never breaching the
    # EVENT_INBOX_RETAIN_FLOOR_S floor), then returns freed pages to the OS.
    # Touches no fan rows. Hourly ticks. See _payload_size_cap_loop.
    asyncio.create_task(_payload_size_cap_loop(), name="payload-size-cap")

    # Retention sweep for the append-only audit/log tables (automation_runs,
    # grok_calls, scheduled_jobs terminal rows, actions) — none had any prune,
    # so they grew unbounded and crept the DB back up after the raw-payload
    # columns were capped. Daily ticks; per-table windows via *_RETAIN_S env.
    asyncio.create_task(_audit_retention_evictor_loop(), name="audit-retention-evictor")

    # Planner statistics stay current as tables grow (see _db_optimize_loop).
    asyncio.create_task(_db_optimize_loop(), name="sqlite-optimize")

    # Opt-in periodic proxy probe (PROXY_HEALTH_INTERVAL_S; off by default).
    # Returns at once when unset.
    asyncio.create_task(proxy_health.probe_loop(), name="proxy-health-probe")

    # A new OF build seen in a response, or a capture's first 2xx, spreads its
    # sign rules to every account on an older build (sign_rules, 2.17).
    sign_rules.enable_background()

    # Missed clock-ins become agency notifications, and old ones are pruned (notifications_api.tick).
    asyncio.create_task(_periodic("clock-in missed", notifications_api.TICK_S, notifications_api.tick,
                                  first_after_s=60), name="clock-in-missed")

    # Tracking / free trial / promotion link figures, read hourly per live
    # account so Growth pages open from cache (link_metrics.prewarm_all). First
    # pass 10 min in, clear of the boot herd.
    import link_metrics
    asyncio.create_task(_periodic(
        "link figures prewarm", link_metrics.PREWARM_PAUSE_S, link_metrics.prewarm_all,
        first_after_s=600), name="link-figures-prewarm")

    # Phase F: poll OF's /api2/v2/payouts/transactions ledger so per-model
    # stats include subs / tips / PPV unlocks / paid posts. 10-min ticks,
    # sequential per-account refresh, parallel backfill (sem=4). See
    # service/transaction_ingest.py docstring.
    from transaction_ingest import (
        start_supervisor as _start_tx_ingest,
        start_fast_poll as _start_tx_fast,
    )
    _tx_ingest_task = asyncio.create_task(_start_tx_ingest(), name="tx-ingest-supervisor")
    # 30s freshness poll layered on the 5-min supervisor: fetches just the last
    # 10 transactions per online account so a PPV unlock / tip lands in the
    # ledger within ~30s and the automations see it the next tick. Idempotent
    # with the supervisor (shared per-account lock + provider_id dedup). Cancelled in _stop_event_pumps.
    _tx_fast_task = asyncio.create_task(_start_tx_fast(), name="tx-ingest-fast-poll")

    # OnlyFans Statistics figures per Creator per UTC day (visitors, new subs,
    # renewals) for Creator reports' windows: three reads per Creator once a
    # day, hourly checks. See service/of_stats_daily.py.
    import of_stats_daily
    _spawn_bg(of_stats_daily.run_loop(), "of-stats-daily")

    # P3 — automation executor: consumes scheduled_jobs / automation_rules and
    # runs the 12 automations (scrape_chats ships as the reference). Mirrors the
    # supervisor pattern above; cancelled in _stop_event_pumps next to tx-ingest.
    from automation_executor import automation_supervisor as _automation_supervisor
    _automation_exec_task = asyncio.create_task(
        _automation_supervisor(), name="automation-exec",
    )

    # W7 (0) — seed chat links ONCE for all accounts: enqueue a one-shot
    # scrape_chats sweep per session-backed account so the inbox has the full
    # conversation list (the WS pump then carries deltas — no second bulk-pull).
    # Reuses the existing scrape_chats automation; the supervisor's first drain
    # (immediate at loop start) picks the jobs up. Fire-and-forget so N inserts
    # don't block startup.
    asyncio.create_task(_seed_chat_links_once(), name="w7-seed-chat-links")


async def _seed_chat_links_once() -> None:
    """Enqueue a one-shot scrape_chats job per active account (W7 part 0)."""
    global _chat_links_seeded
    if _chat_links_seeded:
        return
    _chat_links_seeded = True
    try:
        from automation_executor import enqueue_job, wake_supervisor
        n = 0
        off = await account_health.deactivated_ids()
        for meta in account_registry.list_accounts():
            if not meta.get("has_session") or meta["id"] in off:
                continue
            try:
                await enqueue_job(meta["id"], "scrape_chats", payload={})
                n += 1
            except Exception:
                log.warning("w7_seed_enqueue_failed account=%s", meta.get("id"), exc_info=True)
        if n:
            wake_supervisor()
        log.info("w7_chat_links_seeded accounts=%d", n)
    except Exception:
        log.warning("w7_seed_chat_links failed", exc_info=True)


@app.on_event("shutdown")
async def _stop_event_pumps() -> None:
    # Save the lane counters before anything else can raise — a clean stop is
    # the one restart where we can avoid losing the last flush interval.
    _lane_stats_flush(force=True)
    # Finish every automation run that has claimed a send (a mass message on
    # its way to OF) before anything below stops, and start no new one: a restart
    # never leaves a send half done (automation_executor.drain, bounded).
    from automation_executor import drain as _drain_automations
    with contextlib.suppress(Exception):
        await _drain_automations()
    # CancelledError is not an "Exception" in 3.8+ (it's BaseException) so we
    # have to suppress it explicitly — otherwise FastAPI logs a noisy traceback
    # at every clean shutdown.
    if _supervisor_task and not _supervisor_task.done():
        _supervisor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _supervisor_task
    if _tx_ingest_task and not _tx_ingest_task.done():
        _tx_ingest_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _tx_ingest_task
    if _tx_fast_task and not _tx_fast_task.done():
        _tx_fast_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _tx_fast_task
    if _automation_exec_task and not _automation_exec_task.done():
        _automation_exec_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _automation_exec_task
    for task in list(_account_pumps.values()):
        if not task.done():
            task.cancel()
    for task in list(_account_pumps.values()):
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    _account_pumps.clear()

    # Drain the persist worker last — pumps are already cancelled above, so
    # no new events are arriving. Anything still in the queue is dropped.
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await _stop_persist_worker()

    # Close the pooled SQLite connections (db/engine.py), so the last one out
    # checkpoints the WAL as a closed NullPool connection used to.
    from db.engine import engine as _db_engine
    with contextlib.suppress(Exception):
        await _db_engine.dispose()


def _load_client(account_id: str) -> OFClient:
    """Return the OFClient for `account_id`, loading it the first time.
    Raises a structured 503 if the account has no usable session yet.

    Pooling lives in client_pool; this is only the HTTP translation of the two
    ways a build can fail. Routes and automations share the one pool, so an
    account has one client (and one cookie jar), not one per lane.

    Platform branch (additive): a Fansly account returns the OF-shaped shim
    (fansly_backend → FanslyShimClient); OnlyFans accounts — the default for
    every account without a `platform` — hit the unchanged client_pool."""
    try:
        if account_registry.get_platform(account_id) == "fansly":
            import fansly_backend
            return fansly_backend.get_client(account_id)
        return client_pool.get(account_id)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "no_session",
                "account_id": account_id,
                "message": str(e),
                "remedy": ["POST /admin/session/bootstrap"],
            },
        ) from None
    except ValueError as e:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "incomplete_signing_rules",
                "account_id": account_id,
                "message": str(e),
                "remedy": ["POST /admin/session/bootstrap"],
            },
        ) from None


def _resolve_account_id(request: Request | None) -> str:
    """Pick the account_id for this request, in priority order:
       1. `X-Account-Id` request header (UI sends this)
       2. `?account_id=...` query param (curl-friendly)
       3. the currently active account (fallback for un-aware callers)
    Raises 404 if the explicit id doesn't exist, 503 if no active account,
    403 if the signed-in user doesn't own the resolved account.

    Ownership gate: if a session cookie identifies a signed-in friend (see
    auth.session_middleware), the resolved account_id MUST appear in their
    `user_accounts` set. Background paths with no request user (cron, WS
    pump callbacks) bypass the check — they're trusted system code. This
    is the single choke point for cross-user data isolation.
    """
    explicit: str | None = None
    if request is not None:
        explicit = request.headers.get("x-account-id") or request.query_params.get("account_id")
    if explicit:
        if account_registry.get_account(explicit) is None:
            raise HTTPException(status_code=404, detail=f"Unknown account_id {explicit!r}")
        aid = explicit
    else:
        aid = account_registry.get_active_account_id() or ""
        if not aid:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "no_active_account",
                    "message": "No account has a captured session yet.",
                    "remedy": ["POST /admin/session/bootstrap"],
                },
            )

    user = _get_request_user()
    if user is not None:
        if aid not in user.account_ids:
            raise HTTPException(status_code=403, detail="not your account")
    else:
        # Chatter principal: account_ids is the SET UNION across every
        # owner that linked this chatter (see service/chatters.py).
        chatter = _get_request_chatter()
        if chatter is not None and aid not in chatter.account_ids:
            raise HTTPException(status_code=403, detail="not your account")
    return aid


def _get_client(request: Request | None = None) -> OFClient:
    """Resolve the account for `request` (or — if not passed — the request
    captured by the middleware contextvar, falling back to the active
    account) and return its OFClient."""
    if request is None:
        request = _request_ctx.get()
    return _load_client(_resolve_account_id(request))


def _invalidate_client(account_id: str | None = None) -> None:
    """Drop pooled OFClient(s) so the next request reloads from disk.
    Used after re-bootstrap or proxy reassignment. None = every account (a
    proxy edit can affect any of them)."""
    client_pool.evict(account_id)


def _kick_clear_session_dead(account_id: str) -> None:
    """Fire-and-forget clear of the account's dead-session pause (see
    service/account_health.py) — a fresh capture proves the session works, so
    automations resume immediately instead of waiting for the next probe.
    Trampolines to the main loop because sync handlers run in the threadpool
    (same pattern as _kick_db_sync)."""
    async def _clear() -> None:
        try:
            if await account_health.clear_session_dead(account_id):
                log.info("account_session_recovered account=%s via=bootstrap "
                         "— automations resume", account_id)
        except Exception:
            log.exception("failed to clear session-dead flag")

    _on_main_loop(_clear, f"session-recover-{account_id}")


def _kick_mark_session_dead(account_id: str, reason: str, via: str) -> None:
    """Fire-and-forget account_health.mark_session_dead from a sync caller (a
    `_proxy` read in the threadpool): OF rejected the session, so automations
    pause and the owner is told once, as for an automation that hit it."""
    async def _mark() -> None:
        try:
            if await account_health.mark_session_dead(account_id, reason):
                log.warning("account_session_dead account=%s via=%s reason=%s — automations "
                            "paused until the session recovers", account_id, via, reason)
        except Exception:
            log.exception("failed to mark session-dead account")

    _on_main_loop(_mark, f"session-dead-{account_id}")


def _on_main_loop(make_coro, name: str) -> None:
    """Run `make_coro()` as a task on the relay's loop, from the loop itself or
    from a threadpool thread (sync handlers); dropped before startup."""
    import asyncio as _aio
    try:
        loop = _aio.get_running_loop()
    except RuntimeError:
        if _main_loop is None:
            return
        _main_loop.call_soon_threadsafe(lambda: _aio.create_task(make_coro(), name=name))
        return
    loop.create_task(make_coro(), name=name)


def _sync_and_link_after_bootstrap(account_id: str) -> None:
    """Mirror the new on-disk account into SQL, then give it its owner.

    These two used to be separate fire-and-forget tasks, and the link lost
    the race often enough that every recently captured account was owned by
    nobody. They are ordered inside ONE coroutine now, so the `accounts`
    parent is always committed before the link is attempted — the FK can no
    longer fire, and the `except IntegrityError` that hid it is gone.

    The link half is skipped for an unauthed request (founder pre-auth curl,
    internal cron); the sync half always runs. Failures are logged, never
    swallowed.
    """
    user = _get_request_user()

    async def _run() -> None:
        await _sync_db_from_disk()
        if user is None:
            return
        await ensure_user_account_link(user.id, account_id)
        # Refresh the in-process snapshot so the SAME request (sync handler
        # called us, then returns to the user) sees the new account_id in
        # its set on any follow-up _resolve_account_id call.
        user.account_ids = frozenset(user.account_ids | {account_id})  # type: ignore[misc]

    loop = _main_loop
    if loop is None:
        return
    import asyncio as _asyncio
    fut = _asyncio.run_coroutine_threadsafe(_run(), loop)
    try:
        # Wait so the row is visible by the time we answer, capped so a slow
        # import can't hang the response. On timeout the coroutine keeps
        # running and still lands the link — ordering, not this wait, is what
        # makes it correct.
        fut.result(timeout=10)
    except Exception:
        log.exception("bootstrap sync+link failed for account %s", account_id)


def post_bootstrap_hooks(account_id: str):
    """What every session registration runs once the session is on disk, in
    order: drop the pooled client, clear the dead-session pause, load the
    client, restart the WS pump so the new cookies are used immediately, then
    mirror into SQL and link the account to the signed-in user (ordered, not
    raced — see _sync_and_link_after_bootstrap; unauthed callers still get the
    sync). Shared by POST /admin/session/bootstrap and the served Browserbase
    login (remote_login.py). Returns the loaded OFClient."""
    _invalidate_client(account_id)
    _kick_clear_session_dead(account_id)
    c = _load_client(account_id)
    _restart_account_pump(account_id)
    _sync_and_link_after_bootstrap(account_id)
    return c


# ── Per-account OF call priority lanes ────────────────────────────────
#
# All OF API calls for one account share a single curl_cffi.requests.Session
# routed through one proxy IP. curl_cffi Sessions are NOT thread-safe and
# OF + the proxy provider cap concurrent connections per source IP — so
# firing 8 parallel /users/list batches behind a 11s /chats/messages call
# starves anything else (like a vault picker open) that tries to land
# during that window.
#
# We solve this with two semaphores per account:
#   * `total`      — hard concurrency cap so we never exceed what the
#                    proxy/OF can serve cleanly
#   * `background` — sub-cap so bulk enrichment can't fill every slot
#
# Background calls acquire BOTH; user calls only the total cap. Result:
# user-initiated work always has at least (total - background) reserved
# slots and jumps the queue ahead of any waiting background call.
#
# Priority is signalled by the `X-Priority: background` request header.
# Anything else (including missing) is treated as user.
# Tunable, like every admission lane — this was the one concurrency ceiling in
# the process that could only be changed by editing source, which is why it had
# never been retuned.
#
# WHAT ACTUALLY BOUNDS THIS, measured 2026-08-26. The comment below says the cap
# exists because OF and the proxy cap connections per source IP. That is not
# what the numbers show: 100 concurrent `users/me` from ONE egress IP returned
# 100x 200 with p50 flat at 0.55s, no 429 and no rate limiting — no knee at all
# up to 100. Five accounts sharing one IP ran 25 concurrent with zero queuing
# (p50 0.88s, against 0.61s for three accounts at 15).
#
# The real ceiling is THREADS. Every OF call is sync and runs via
# `asyncio.to_thread`, so the fleet shares the one executor set at startup
# (`_EXECUTOR_THREADS`) — with automation runs, vault stills and storyboard
# builds. The budget is therefore:
#
#     accounts x _ACCOUNT_LANE_TOTAL  <=  _EXECUTOR_THREADS - headroom
#
# At 7 accounts the default 5 spent 35 of the old 64 (55%). At 20 accounts it
# would have wanted 100 of 64 — every lane saturated at once queues inside the
# pool, starving the automation lane and /health behind it (the 2026-07-04
# thread-starvation shape). So the executor below is now DERIVED from this
# number, not the other way round. Raise this only with evidence that the cap
# is costing anything at all (`admin_priority_lane_stats()`'s `blocked_rate`).
# It has been 0.0% across every measurement so far.
_ACCOUNT_LANE_TOTAL = lane_config.resolve("ACCOUNT_LANE_TOTAL", 5)
# Still clamped below total: the sub-cap exists to RESERVE slots for user
# work, so a saved value of background >= total would silently delete the
# reservation and turn the two semaphores into one.
_ACCOUNT_LANE_BACKGROUND = max(1, min(
    _ACCOUNT_LANE_TOTAL - 1 if _ACCOUNT_LANE_TOTAL > 1 else 1,
    lane_config.resolve("ACCOUNT_LANE_BACKGROUND", 2),
))
# The clamp above means the number ENFORCED can differ from the number resolved,
# and this is the only knob where that is true. Told to the store explicitly, or
# the panel would report a pending change that no restart will ever deliver.
lane_config.record_live("ACCOUNT_LANE_BACKGROUND", _ACCOUNT_LANE_BACKGROUND)

# The asyncio default executor's size. Every `asyncio.to_thread` in this
# codebase shares this one pool — all `_proxy` OF calls, the automation
# executor's roundtrips, media pulls — so it is the budget the per-account
# lane spends from. Settable from the Concurrency panel (env > panel > this
# default). A `ThreadPoolExecutor` cannot be resized, so it is read once, here.
#
# THE DEFAULT IS DERIVED, sized 2026-10-25 for one agency of 50 accounts on
# one relay (the 8 vCPU box; it was 20 accounts on 4 vCPU, 20 x 5 + 92 = 192):
#
#     accounts x _ACCOUNT_LANE_TOTAL  +  _EXECUTOR_HEADROOM
#     50       x 5                    +  128                 =  378
#
# The headroom is what draws on the pool OUTSIDE `_proxy`'s lanes, counted at
# 50 Creators: automation runs call the OF client directly (run slots —
# run_slot.auto_runs(50) = 6, plus 2 operator-reserved — x up to 6 paced
# welcome workers, + 2 bulk = 50); transaction ingest's own fan-outs (the
# fast poll 5, backfill 4, the supervisor 1 = 10; counted again on purpose,
# though the fast poll's call also sits in its account's lane); and the
# admission lanes that dispatch to threads (vault media 10, stills 6,
# storyboard 3, health 24, referrals 16 = 59) — 119, rounded up. `accounts` is the larger of the fleet this box is sized
# for and the account directories on disk at boot, so a relay that grows past
# 50 grows its pool at the next restart instead of silently re-running the
# 7-on-64 maths with 80.
#
# What it costs: threads only block on network I/O, and `ThreadPoolExecutor`
# starts one only when work arrives with none idle, so a 5-account relay never
# reaches this number — it is a ceiling, like the lanes. Descriptors are the
# scarce thing on 2026-08-08's evidence, and 378 threads x a few sockets each
# sits far under the container's 65536 `nofile` (docker-compose.yml) — the
# 08-08 exhaustion was uncapped /img misses at the 1024 default, fixed by
# `admission.IMG_FETCH` and that ulimit.
_FLEET_ACCOUNTS = 50
_EXECUTOR_HEADROOM = 128


def _accounts_on_disk() -> int:
    """Account directories present at boot. A plain directory count — not
    `list_accounts()`, which materialises meta as a side effect — and never
    raises: a sizing hint must not stop the relay from importing."""
    try:
        return sum(1 for p in account_registry.ACCOUNTS_DIR.iterdir() if p.is_dir())
    except Exception:
        return 0


_EXECUTOR_THREADS = lane_config.resolve(
    "RELAY_EXECUTOR_THREADS",
    max(_FLEET_ACCOUNTS, _accounts_on_disk()) * _ACCOUNT_LANE_TOTAL + _EXECUTOR_HEADROOM,
)
_account_lanes_lock = threading.Lock()
_account_lanes: dict[str, tuple[threading.BoundedSemaphore, threading.BoundedSemaphore]] = {}
#
# ── Lane accounting ────────────────────────────────────────────────────
# The previous two counters (`_priority_total_waits`,
# `_priority_background_waits`) incremented before EVERY acquire, not only
# blocked ones, and nothing ever read them — so they could not answer the
# only question that matters here: is this lane actually a queue, and for
# how long? These replace them with per-account + fleet-wide accounting of
# *blocked* acquires and the time spent blocked, exposed at
# /admin/priority-lanes/stats. Observation only: no acquire is bounded and
# nothing is rejected.
_lane_stats_lock = threading.Lock()
_lane_stats_since = _time_mod.monotonic()


def _new_lane_stat() -> dict:
    return {
        "calls": 0,                 # lane entries
        "calls_user": 0,
        "calls_background": 0,
        "blocked_total": 0,         # entries that waited for a `total` slot
        "blocked_background": 0,    # background entries that waited on the sub-cap
        "wait_s_total": 0.0,        # cumulative seconds blocked on `total`
        "wait_s_background": 0.0,   # cumulative seconds blocked on `background`
        "wait_s_max": 0.0,          # worst single entry's total wait
        "in_flight": 0,
        "in_flight_peak": 0,
        "bg_in_flight": 0,
        "bg_in_flight_peak": 0,
    }


_lane_stats_all: dict = _new_lane_stat()
_lane_stats: dict[str, dict] = {}

# ── Persistence ────────────────────────────────────────────────────────
# The counters above answer "is this lane actually a queue?", and that is a
# question answered over DAYS, not over one process lifetime. Held only in
# memory they reset on every relay restart — so an observation window that
# spanned a container recreate would silently start from zero and read as
# "no queueing", which is the one wrong answer that looks like a result.
#
# So the CUMULATIVE fields persist to a small JSON file and fold back in on
# boot. Live gauges (`in_flight`, `bg_in_flight`) deliberately do NOT
# restore: nothing is in flight in a process that just started, and a
# restored gauge would be wrong forever. Peaks and `wait_s_max` merge by max.
#
# The default path is the directory the SQLite DB lives in — in this
# deployment that is the one path that is a real volume and therefore
# survives `docker rm`. `PRIORITY_LANE_STATS_PATH=/some/file.json` moves it;
# `PRIORITY_LANE_STATS_PATH=` (empty) turns persistence off entirely.
_LANE_STATS_SCHEMA = 1
_LANE_STATS_FLUSH_S = 30.0
_LANE_CUMULATIVE = ("calls", "calls_user", "calls_background",
                    "blocked_total", "blocked_background",
                    "wait_s_total", "wait_s_background")
_LANE_MAXED = ("wait_s_max", "in_flight_peak", "bg_in_flight_peak")


def _lane_stats_file() -> Path | None:
    """Where the cumulative counters live between restarts, or None to keep
    them in memory only."""
    raw = os.environ.get("PRIORITY_LANE_STATS_PATH")
    if raw is not None:
        raw = raw.strip()
        return Path(raw) if raw else None
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("sqlite") and ":///" in url:
        db = url.split(":///", 1)[1].split("?", 1)[0]
        if db:
            parent = Path(db).parent
            if parent.is_dir():
                return parent / "priority_lane_stats.json"
    return None


_LANE_STATS_PATH: Path | None = _lane_stats_file()
_lane_stats_base: dict = _new_lane_stat()               # fleet-wide, from disk
_lane_stats_base_by_account: dict[str, dict] = {}
_lane_stats_started_at: float = _time_mod.time()        # wall clock, window start
_lane_stats_boots: int = 1                              # restarts this window spans
_lane_stats_last_flush: float = 0.0                     # monotonic
_lane_stats_load_error: str | None = None
_lane_stats_write_error: str | None = None


def _merge_lane_row(dst: dict, src: dict) -> None:
    """Fold a persisted row into `dst`: cumulative fields add, peaks take the
    max, live gauges are ignored on purpose."""
    for k in _LANE_CUMULATIVE:
        v = src.get(k)
        if isinstance(v, (int, float)) and v >= 0:
            dst[k] += v
    for k in _LANE_MAXED:
        v = src.get(k)
        if isinstance(v, (int, float)) and v > dst[k]:
            dst[k] = v


def _lane_row_combined(base: dict, live: dict) -> dict:
    """One row as a reader should see it: what survived restarts plus what
    this process has seen. Gauges come from the live row only."""
    out = _new_lane_stat()
    for k in _LANE_CUMULATIVE:
        out[k] = base[k] + live[k]
    for k in _LANE_MAXED:
        out[k] = max(base[k], live[k])
    out["in_flight"] = live["in_flight"]
    out["bg_in_flight"] = live["bg_in_flight"]
    return out


def _lane_stats_load() -> None:
    """Best-effort restore at import. A missing, unreadable or older-schema
    file is not an error worth failing a boot over — it just means this
    window starts now, and the endpoint says so."""
    global _lane_stats_started_at, _lane_stats_boots, _lane_stats_load_error
    p = _LANE_STATS_PATH
    if p is None:
        return
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except Exception as exc:
        _lane_stats_load_error = f"{type(exc).__name__}: {exc}"[:200]
        return
    if not isinstance(raw, dict) or raw.get("v") != _LANE_STATS_SCHEMA:
        _lane_stats_load_error = "schema mismatch — starting a fresh window"
        return
    try:
        started = float(raw.get("started_at") or 0.0)
        if started > 0:
            _lane_stats_started_at = started
        _lane_stats_boots = int(raw.get("boots") or 0) + 1
        _merge_lane_row(_lane_stats_base, raw.get("overall") or {})
        for aid, row in (raw.get("accounts") or {}).items():
            if isinstance(aid, str) and isinstance(row, dict):
                _merge_lane_row(
                    _lane_stats_base_by_account.setdefault(aid, _new_lane_stat()), row)
    except Exception as exc:
        _lane_stats_load_error = f"{type(exc).__name__}: {exc}"[:200]


def _lane_stats_snapshot() -> dict:
    """Everything a reader (or the file) needs, base folded into live."""
    with _lane_stats_lock:
        overall = _lane_row_combined(_lane_stats_base, _lane_stats_all)
        accounts = {}
        for aid in set(_lane_stats) | set(_lane_stats_base_by_account):
            accounts[aid] = _lane_row_combined(
                _lane_stats_base_by_account.get(aid) or _new_lane_stat(),
                _lane_stats.get(aid) or _new_lane_stat())
    return {
        "v": _LANE_STATS_SCHEMA,
        "started_at": _lane_stats_started_at,
        "boots": _lane_stats_boots,
        "overall": overall,
        "accounts": accounts,
    }


def _lane_stats_flush(force: bool = False) -> None:
    """Persist the cumulative counters. Throttled, because this is called from
    every lane exit and must never become a write per OF call. Never raises —
    a lane that cannot save its stats still has to serve traffic."""
    global _lane_stats_last_flush, _lane_stats_write_error
    p = _LANE_STATS_PATH
    if p is None:
        return
    now = _time_mod.monotonic()
    if not force and (now - _lane_stats_last_flush) < _LANE_STATS_FLUSH_S:
        return
    _lane_stats_last_flush = now
    try:
        payload = json.dumps(_lane_stats_snapshot())
        tmp = p.parent / (p.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, p)
        _lane_stats_write_error = None
    except Exception as exc:
        _lane_stats_write_error = f"{type(exc).__name__}: {exc}"[:200]


_lane_stats_load()
# Persist immediately rather than waiting for the first lane exit. Two reasons:
# the bumped `boots` should be durable even on a relay that then serves no OF
# traffic at all, and a path we cannot write to should surface as
# `persist_error` at boot rather than silently at the end of the first window.
_lane_stats_flush(force=True)


def _lane_stat_rows(account_id: str) -> tuple[dict, dict]:
    """Fleet-wide + per-account stat dicts. Caller holds `_lane_stats_lock`."""
    st = _lane_stats.get(account_id)
    if st is None:
        st = _new_lane_stat()
        _lane_stats[account_id] = st
    return _lane_stats_all, st


def _lane_acquire(sem: threading.BoundedSemaphore, account_id: str, which: str) -> float:
    """Acquire `sem`, recording whether we had to wait and for how long.

    Behaviourally identical to a bare `sem.acquire()` — the non-blocking
    probe exists ONLY so "took a free slot" can be told apart from "queued
    behind someone". Still unbounded: this never gives up, never rejects.
    Returns the seconds spent blocked (0.0 when a slot was free)."""
    if sem.acquire(blocking=False):
        return 0.0
    t0 = _time_mod.monotonic()
    sem.acquire()
    waited = _time_mod.monotonic() - t0
    ckey = "blocked_background" if which == "background" else "blocked_total"
    wkey = "wait_s_background" if which == "background" else "wait_s_total"
    with _lane_stats_lock:
        for st in _lane_stat_rows(account_id):
            st[ckey] += 1
            st[wkey] += waited
    return waited


def _lane_entered(account_id: str, priority: str, waited: float, bg_held: bool) -> None:
    with _lane_stats_lock:
        for st in _lane_stat_rows(account_id):
            st["calls"] += 1
            st["calls_background" if priority == "background" else "calls_user"] += 1
            st["in_flight"] += 1
            if st["in_flight"] > st["in_flight_peak"]:
                st["in_flight_peak"] = st["in_flight"]
            if bg_held:
                st["bg_in_flight"] += 1
                if st["bg_in_flight"] > st["bg_in_flight_peak"]:
                    st["bg_in_flight_peak"] = st["bg_in_flight"]
            if waited > st["wait_s_max"]:
                st["wait_s_max"] = waited


def _lane_exited(account_id: str, bg_held: bool) -> None:
    with _lane_stats_lock:
        for st in _lane_stat_rows(account_id):
            st["in_flight"] -= 1
            if bg_held:
                st["bg_in_flight"] -= 1
    # Outside the lock on purpose — the flush serialises its own snapshot and
    # must not hold every other lane user behind a disk write.
    _lane_stats_flush()


def _lanes_for(account_id: str) -> tuple[threading.BoundedSemaphore, threading.BoundedSemaphore]:
    """Return (total, background) semaphores for `account_id`, creating
    them on first access."""
    with _account_lanes_lock:
        pair = _account_lanes.get(account_id)
        if pair is None:
            pair = (
                threading.BoundedSemaphore(_ACCOUNT_LANE_TOTAL),
                threading.BoundedSemaphore(_ACCOUNT_LANE_BACKGROUND),
            )
            _account_lanes[account_id] = pair
        return pair


def _current_priority() -> str:
    """Read X-Priority off the current request. Defaults to 'user' when
    the header is missing or the call originates outside a request (e.g.
    background tasks). The only value that changes behaviour is the exact
    string 'background'."""
    req = _request_ctx.get()
    if req is None:
        return "user"
    return (req.headers.get("x-priority") or "user").lower()


@contextlib.contextmanager
def _priority_lane(account_id: str | None, priority: str | None = None):
    """Acquire the right semaphore(s) for the current request's priority.
    Background callers also hold the background sub-semaphore, so user
    callers always have at least (total - background) reserved slots.

    `priority` overrides the X-Priority header — used by server-side
    callers that have no request context (see `_priority_lane_background`).

    Neither acquire is bounded. If the second acquire raises, the first is
    released before the exception propagates: without that, a background
    caller interrupted between the two acquires would permanently shrink
    the background cap (2 → 1 → 0) for that account."""
    if not account_id:
        yield
        return
    total, background = _lanes_for(account_id)
    if priority is None:
        priority = _current_priority()
    bg_held = False
    waited = 0.0
    if priority == "background":
        waited += _lane_acquire(background, account_id, "background")
        bg_held = True
    try:
        waited += _lane_acquire(total, account_id, "total")
    except BaseException:
        if bg_held:
            try: background.release()
            except ValueError: pass
        raise
    _lane_entered(account_id, priority, waited, bg_held)
    try:
        yield
    finally:
        _lane_exited(account_id, bg_held)
        try: total.release()
        except ValueError: pass
        if bg_held:
            try: background.release()
            except ValueError: pass


POOL_PROXY_ERROR = f"{BRAND_NAME} proxy unreachable"


def _pool_safe_error(aid: str | None, text: str, label: str | None = None) -> str:
    """curl error text names the proxy host. When the client is on an
    Inflowwww proxy (by `label`, else by the account's binding), return a fixed
    message and log the real one here; other text only has pool secrets
    scrubbed (scrub_pool_secrets), so custom/no-proxy text reads as before."""
    p = (proxy_registry.get_by_label(label) if label
         else proxy_registry.get_for_account(aid) if aid else None)
    if not proxy_registry.is_pool(p):
        return proxy_registry.scrub_pool_secrets(text)
    log.warning("inflowwww_proxy_error account=%s: %s", aid, text[:300])
    return POOL_PROXY_ERROR


def _proxy(call):
    """Translate OFAPIError + curl_cffi proxy/network errors into a structured
    502 so the frontend can react, and log a one-liner instead of a 200-line
    traceback for transient proxy failures (cf-tunnel 403s, timeouts, DNS).

    Also serializes the upstream call through the per-account priority
    lane, so a bulk background enrichment can't starve a user-initiated
    fetch (vault open, chat click). A request that is not `X-Priority:
    background` marks its reads interactive (of_client.INTERACTIVE_READ):
    a dead proxy fails them after 2 tries, not 5; writes keep the 5."""
    aid: str | None = None
    token = None
    try:
        req = _request_ctx.get()
        if req is not None:
            try:
                aid = _resolve_account_id(req)
            except HTTPException:
                aid = None
            # Someone is waiting on this request: its reads fail fast on a dead proxy.
            if _current_priority() != "background":
                token = INTERACTIVE_READ.set(True)
        with _priority_lane(aid):
            return call()
    except OFDeactivatedError:
        raise HTTPException(status_code=409, detail=_DEACTIVATED_DETAIL) from None
    except OFDeniedError as e:
        # The Relay's own deny-list (of_client._denied), never sent: not an upstream failure.
        raise HTTPException(status_code=403,
                            detail={"upstream_status": "refused_by_relay", "upstream_body": str(e)})
    except OFAPIError as e:
        r = e.response
        status = r.status_code if r is not None else 500
        body = r.text[:2000] if r is not None else str(e)
        log.warning("upstream error: %s %s", status, body[:200])
        # OF rejected the session itself (logged out, wants a 2FA code): pause the
        # account and tell its owner, as an automation hitting it does. The read
        # still answers 502; the error middleware never sees an OFAPIError here.
        dead_reason = account_health.is_session_dead_error(e)
        if dead_reason and aid:
            _invalidate_client(aid)
            _kick_mark_session_dead(aid, dead_reason, via="proxy")
        # 502 = bad gateway: we tried, OF didn't like it.
        raise HTTPException(
            status_code=502,
            detail={"upstream_status": status, "upstream_body": body},
        )
    except curl_requests.exceptions.ProxyError as e:
        # of_client._http_call already logged the structured details
        # (account, proxy label, endpoint). Surface a clean 502 to the UI.
        log.warning("proxy_unreachable: %s", str(e)[:200])
        raise HTTPException(
            status_code=502,
            detail={"upstream_status": "proxy_unreachable",
                    "upstream_body": _pool_safe_error(aid, str(e)[:500])},
        )
    except curl_requests.exceptions.Timeout as e:
        log.warning("upstream_timeout: %s", str(e)[:200])
        raise HTTPException(
            status_code=504,
            detail={"upstream_status": "timeout", "upstream_body": _pool_safe_error(aid, str(e)[:500])},
        )
    except curl_requests.exceptions.RequestException as e:
        log.warning("upstream_network_error: %s %s", type(e).__name__, str(e)[:200])
        raise HTTPException(
            status_code=502,
            detail={"upstream_status": "network", "upstream_body": _pool_safe_error(aid, str(e)[:500])},
        )
    finally:
        if token is not None:
            INTERACTIVE_READ.reset(token)


def _account_ttl(namespace: str, ttl_seconds: float):
    """Cache a sync, read-only OF proxy route per account for `ttl_seconds`.

    Put it under the `@app.get(...)`. The key is (namespace, account, route name,
    every query/path parameter). The account comes from `_resolve_account_id`,
    which also enforces ownership (403/404), so it runs BEFORE any cache read: a
    caller is only ever answered from its own account's entry. Concurrent
    misses on one key share ONE upstream call (relay_cache's per-key lock).
    Errors are never cached. A request whose account does not resolve skips
    the cache and runs the route as before, which answers the same 403/404/503
    through `_get_client`.

    Writes clear these entries in `of_client` (`_WRITE_INVALIDATES`), whoever
    makes them; anything else waits out the TTL. The undecorated route stays
    callable as `route.__wrapped__`."""
    def wrap(fn):
        @functools.wraps(fn)   # FastAPI reads the route's parameters through __wrapped__
        async def cached(**params):
            try:
                aid = _resolve_account_id(_request_ctx.get())
            except HTTPException:
                return await asyncio.to_thread(fn, **params)
            key = (fn.__name__, *sorted(params.items()))
            return await relay_cache.get_or_fetch(
                namespace, aid, key, ttl_seconds, lambda: fn(**params))
        return cached
    return wrap


# ── Endpoints ──────────────────────────────────────────────────

@app.get("/livez")
def livez():
    """Process liveness probe. Returns 200 as long as FastAPI is running.

    Distinct from /health which reports session/account readiness and can
    return 503 when no OF account is loaded yet. The Docker HEALTHCHECK
    directive aims this endpoint so a relay with zero captured sessions
    (i.e. a brand-new install before paste-cURL bootstrap) is still
    marked healthy — otherwise app.depends_on.relay:service_healthy
    deadlocks fresh deploys, since the UI that creates the first session
    lives behind that very dependency. Always cheap, no side effects, no
    auth required (same exemption as /health from the share-token gate)."""
    return {"ok": True}


# ── /health?all_accounts=1 — one live OF probe per account ──────────────
#
# The loop that makes them used to be serial: 7 accounts measured 4.11s then
# 3.06s against 0.60s for a single account. Concurrency is the fix, and the
# ceiling that keeps it from being a downgrade is `admission.HEALTH_PROBE` —
# see that lane for why an unbounded fan-out here is a process-wide problem.
#
# What is local to this handler is the BUDGET, and the budget is not a cancel.
# `c.me()` blocks in a worker thread and outlives any cancellation of the task
# awaiting it, so `asyncio.wait(timeout=)` stops WAITING and nothing more: each
# probe still runs to completion and still releases its own slot when it
# actually finishes. Releasing on timeout instead would let the next probe start
# while the abandoned OF call was still in flight — a ceiling reported but not
# held. Timed-out probes are parked in `_health_probes_running` so the loop
# cannot collect a live task, and their row says `timeout`, which is an honest
# "still running" rather than a verdict on the session.
#
# 20s, and deliberately nowhere near the 0.60s a healthy probe takes: that is
# what healthy looks like, not a safe deadline. `OFClient.timeout_s` is 30s and
# `_proxy_retry` can spend several attempts inside it, so a budget sized off the
# observed number would fail slow-but-fine accounts and flag their sessions in
# the switcher — manufacturing the exact fault this route exists to report.
_HEALTH_PROBE_BUDGET_S = max(1.0, float(os.environ.get("HEALTH_ALL_BUDGET_S", "20")))

# Strong references to probes still running past the budget. Their only other
# reference is a local in a frame we are about to return from, and the loop is
# free to collect a task nobody holds — mid-OF-call.
_health_probes_running: set[asyncio.Task] = set()


def _probe_account_blocking(aid: str) -> dict[str, Any]:
    """One account's live probe. NEVER raises — returns that row's fields.

    Every branch of the old serial loop's try/except lives here unchanged. The
    endpoint's "never raises 500" contract is what makes that mandatory: once
    this runs in a worker thread, an escaping exception is no longer inside the
    loop that used to wrap it."""
    try:
        c = _load_client(aid)
        me = c.me()
        # An Inflowwww proxy's label, host and credentials never leave the relay.
        pool = proxy_registry.is_pool(proxy_registry.get_by_label(c.proxy_label or ""))
        return {"ok": True, "user_id": me.get("id"), "name": me.get("name"),
                "proxy": {"pool": True} if pool else {"label": c.proxy_label, "url": c.proxy_url}}
    except OFAPIError as e:
        r = e.response
        return {"ok": False, "error": "upstream",
                "upstream_status": r.status_code if r else None,
                "upstream_body": (r.text[:300] if r else str(e))}
    except HTTPException as e:
        return {"ok": False,
                "error": (e.detail.get("error") if isinstance(e.detail, dict) else "error"),
                "detail": e.detail}
    except Exception as e:
        return {"ok": False, "error": _pool_safe_error(aid, f"{type(e).__name__}: {e}")}


async def _probe_account(aid: str) -> dict[str, Any]:
    """Hold a slot for the WHOLE life of the blocking call, then release it."""
    async with admission.HEALTH_PROBE:
        return await asyncio.to_thread(_probe_account_blocking, aid)


async def _health_all_accounts() -> dict[str, Any]:
    """The `?all_accounts=1` snapshot: one bounded, budgeted probe per account."""
    rows: list[dict[str, Any]] = []
    # Task → the row it answers, so association is by identity and no ordering
    # or id-uniqueness assumption stands between a probe and its account.
    probes: dict[asyncio.Task, dict[str, Any]] = {}
    off = await account_health.deactivated_ids()
    for meta in account_registry.list_accounts():
        aid = meta["id"]
        row: dict[str, Any] = {
            "account_id": aid, "nickname": meta.get("nickname"),
            "color": meta.get("color"),
            "has_session": meta.get("has_session", False),
        }
        rows.append(row)
        if not meta.get("has_session"):
            # No session means no client to load: answered off the registry
            # alone, without spending a slot or an OF call to say so.
            row.update({"ok": False, "error": "no_session"})
            continue
        if aid in off:
            # A deactivated Creator gets no OF call, this probe included.
            row.update({"ok": False, "error": "deactivated"})
            continue
        probes[asyncio.create_task(_probe_account(aid))] = row

    if probes:
        done, pending = await asyncio.wait(set(probes), timeout=_HEALTH_PROBE_BUDGET_S)
        for t in done:
            try:
                probes[t].update(t.result())
            except Exception as e:  # noqa: BLE001 — never raises 500
                # `_probe_account_blocking` swallows everything, so reaching
                # here means the dispatch itself failed (executor shut down).
                probes[t].update({"ok": False, "error": f"{type(e).__name__}: {e}"})
        for t in pending:
            _health_probes_running.add(t)          # deliberately NOT cancelled
            t.add_done_callback(_health_probes_running.discard)
            probes[t].update({
                "ok": False, "error": "timeout", "timed_out": True,
                "message": f"no answer within {_HEALTH_PROBE_BUDGET_S:g}s; the probe is still running",
            })

    return {"ok": all(r.get("ok") for r in rows) if rows else False,
            "accounts": rows}


def _health_one(request: Request):
    """The single-account branch, unchanged — and still blocking (`me()` and
    `egress_ip()` are both OF round-trips), which is why the handler hands it
    to a thread rather than running it on the loop."""
    try:
        client = _get_client(request)
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content={"ok": False, **(e.detail if isinstance(e.detail, dict) else {"detail": e.detail})})
    # An Inflowwww proxy's label, host and credentials never leave the relay.
    pool = proxy_registry.is_pool(proxy_registry.get_by_label(client.proxy_label or ""))
    try:
        me = client.me()
    except OFAPIError as e:
        r = e.response
        return JSONResponse(status_code=502, content={
            "ok": False,
            "error": "upstream",
            "upstream_status": r.status_code if r else None,
            "upstream_body": (r.text[:500] if r else str(e)),
            "proxy": {"pool": True} if pool
            else {"label": client.proxy_label, "url": client.proxy_url},
        })
    proxy = ({"pool": True} if pool
             else {"label": client.proxy_label, "url": client.proxy_url, "egress_ip": client.egress_ip()})
    return {
        "ok": True,
        "account_id": client.account_id,
        "user_id": me.get("id"),
        "name": me.get("name"),
        "proxy": proxy,
    }


@app.get("/health")
async def health(request: Request, all_accounts: bool = Query(False, description="Probe every account, not just the requested one")):
    """Never raises 500. Always returns a JSON body the frontend can act on.

    By default reports the health of the account resolved from
    `X-Account-Id` / `?account_id=` / active. Pass `?all_accounts=1` to get
    the full per-account snapshot, which the UI uses to flag any expired
    sessions in the switcher dropdown."""
    if all_accounts:
        # AccountsTable's query inherits `retry: 1` (app/components/providers.tsx),
        # so a slow answer can launch a SECOND fan-out on top of the first.
        # Coalescing makes the retry JOIN the in-flight probe instead of doubling
        # it. Legal per relay_coalesce's own rules — a GET, no `X-Employee-Id`,
        # no attribution — and the key carries no account because the fan-out
        # covers every account and is identical for every caller; the clamp to
        # the caller's own Creators runs after it (_clamp_health_all).
        # ASSUMPTION: the ALLOW_ANONYMOUS_ADMIN escape hatch (allowed None)
        # passes unclamped, as it does for /admin/* (rung 3); rows still lose
        # proxy.url. Overturned if the hatch must not cover /health.
        allowed = _require_actor_account_ids()
        snapshot = await relay_coalesce.coalesce(("health_all",), _health_all_accounts)
        return _clamp_health_all(snapshot, allowed)
    return await asyncio.to_thread(_health_one, request)


def _clamp_health_all(snapshot: dict[str, Any], allowed: frozenset[str] | None) -> dict[str, Any]:
    """Keep only the caller's rows and drop `proxy.url` (it carries the proxy's
    username and password, and no UI reads it). Builds new rows, so the
    coalesced snapshot is never mutated."""
    rows = []
    for row in snapshot["accounts"]:
        if allowed is not None and row.get("account_id") not in allowed:
            continue
        row = dict(row)
        if isinstance(row.get("proxy"), dict):
            row["proxy"] = {k: v for k, v in row["proxy"].items() if k != "url"}
        rows.append(row)
    # ASSUMPTION: the top-level `ok` is recomputed over the caller's rows, with
    # `_health_all_accounts`' own rule (rung 5: another Agency's dead session
    # must not turn this caller's answer false). Overturned if a caller needs
    # the fleet-wide verdict.
    return {**snapshot, "ok": all(r.get("ok") for r in rows) if rows else False,
            "accounts": rows}


@app.get("/api/of/v2/users/me")
@_account_ttl("users_me", 60)
def users_me() -> dict[str, Any]:
    me = _proxy(lambda: _get_client().me())
    # Free-vs-paid page rides on `subscribePrice` here; hand it to account_page
    # so the feed-post gate gets its answer without a second OF round-trip.
    account_page.prime(_resolve_account_id(_request_ctx.get()), me)
    return me


# ── Image proxy ────────────────────────────────────────────────
# OF's CDN signs URLs with `AWS:SourceIp=<egress IP>/32` — the IP of the
# proxy that fetched the API response. The user's browser doesn't share
# that IP, so the image fetch fails on any account whose session uses a
# different egress than the user's home IP. We tunnel the fetch back
# through the account's HTTP client so the source IP matches.
#
# Restricted to known OF CDN hosts to keep this from becoming an SSRF
# foot-gun. Caches at the browser via Cache-Control passthrough.

_ALLOWED_CDN_SUFFIXES = (
    *OF_CDN_SUFFIXES,
    ".fansly.com",  # Fansly media CDN (cdn3.fansly.com); Policy-signed, not ip-bound
)

# OF's unsigned static hosts, which Infloww's desktop sends direct
# (bypassRules.ts: `static*.onlyfans.com`, `public.onlyfans.com`). No Policy and
# no SourceIp to match, so /img fetches them out the relay's own WAN instead of
# spending proxy bandwidth. Every other host (cdn*.onlyfans.com is the signed
# one) stays on the account's proxy.
_DIRECT_CDN_HOST = re.compile(r"static\d*\.onlyfans\.com|public\.onlyfans\.com")
# …and through this bare session, never the account's: no cookies (none kept,
# none sent), no account UA or OF headers, no proxy. A fetch from the relay's
# own IP must carry nothing that names an account, or it links the account to
# that IP. curl_cffi gives each thread its own curl handle, so one is enough.
_DIRECT_HTTP = curl_requests.Session(impersonate=IMPERSONATE, discard_cookies=True)

# In-flight /img stream counters. Each active proxy_image generator
# increments _img_active on first chunk and decrements in its finally
# block. Read via /admin/streams so the user can see whether hover-
# preview is actually blowing the budget or it's something else (e.g.,
# a stalled upstream holding a thread). Pure counters, no lock — Python
# int += is atomic enough for monotonic stats.
_img_active: int = 0
_img_high_water: int = 0
_img_total_started: int = 0
_img_total_aborted: int = 0

# The sync-side admission lanes this module drives live in `admission` —
# instances included — because they bound resources of the PROCESS and
# `vault_frames` takes the build lane too. Referenced through the module rather
# than aliased here: an alias is indirection that buys nothing, and reading
# `admission.IMG_FETCH` at the call site says where the ceiling is defined.
# Each carries its own sizing rationale there; the ⚠️ on IMG_FETCH is worth
# reading before retuning any of them.

# Stable handle for /img assets. OF CDN URLs include a signed Policy +
# Signature + Key-Pair-Id that rotate per upstream fetch — the SAME
# physical image looks like a different URL each time we re-list a chat.
# Browser HTTP cache keys by full URL, so signature rotation gives a
# 0% hit rate across re-fetches of the same chat.
#
# Fix: hash the stable identity of the asset (host + path, scoped by
# account), keep an in-memory hash → most-recent-signed-URL map, and
# expose /img/by-hash/<h> that the frontend can use as a stable cache
# key once it's seen the hash via /admin/img-cache/stats or via the
# response header X-Img-Hash from /img?u=...
#
# TTL on entries matches OF's signed-URL lifetime (~1h). After expiry,
# /img/by-hash/<h> returns 410 and the frontend falls back to /img?u=
# with a fresh URL from the next /messages payload.
_IMG_HASH_TTL_S = 60 * 60
_IMG_HASH_CAP = 50_000
_img_hash_lock = threading.Lock()
_img_hash_map: dict[str, tuple[str, float]] = {}   # hash -> (signed_url, ts_seen)


def _img_stable_hash(account_id: str, u: str) -> str:
    """SHA-1 (truncated to 20 hex chars) over the stable identity of an
    OF CDN asset. Drops the query string (Policy/Signature/Key-Pair-Id),
    lowercases the host, scopes by account so two accounts can't collide
    on a shared asset that might be re-signed differently."""
    from urllib.parse import urlparse as _urlparse
    parsed = _urlparse(u)
    base = (parsed.hostname or "").lower() + (parsed.path or "")
    return hashlib.sha1(f"{account_id}\0{base}".encode("utf-8")).hexdigest()[:20]


def _img_hash_remember(account_id: str, u: str) -> str:
    """Record (or refresh) the hash → signed-URL mapping. Returns the hash.
    Naive size-cap: when over _IMG_HASH_CAP, drop oldest 10% by ts."""
    h = _img_stable_hash(account_id, u)
    now = _time_mod.monotonic()
    with _img_hash_lock:
        _img_hash_map[h] = (u, now)
        if len(_img_hash_map) > _IMG_HASH_CAP:
            # Sort once, drop the bottom 10% in one pass — cheaper than
            # per-eviction in steady state. Triggered rarely (only at cap).
            ordered = sorted(_img_hash_map.items(), key=lambda kv: kv[1][1])
            for k, _ in ordered[: len(ordered) // 10]:
                _img_hash_map.pop(k, None)
    return h


# ── On-disk image cache ───────────────────────────────────────────────
#
# Persistent cache for /img bytes, keyed by hostname+path (signature
# stripped) so it's shared across all accounts/users. Motivation:
#
#   - OF CDN URLs carry a Policy/Signature query string that rotates
#     every ~hours. The browser HTTP cache keys on the full URL, so
#     the moment OF hands us a freshly-signed URL for the same physical
#     asset (chat refetch, vault re-list, signature expiry) the browser
#     cache misses even within the same session.
#   - This cache keys on host+path → those re-signed URLs become disk
#     hits. Same physical image, served from disk, no upstream call.
#   - User A and user B viewing the same chat/profile both hit the same
#     bytes — cross-session sharing without a CDN round-trip each.
#
# Only stores SMALL FULL responses. Range requests (browser <video>) and
# 206 partials are never cached — partials would poison the cache, and
# videos are huge. _IMG_CACHE_MAX_BYTES caps per-file size as a safety
# net even when Content-Length isn't trustworthy.
_IMG_CACHE_DIR = Path(os.environ.get("IMG_CACHE_DIR", "/tmp/of-relay-img-cache"))
_IMG_CACHE_MAX_BYTES = int(os.environ.get("IMG_CACHE_MAX_BYTES", str(2 * 1024 * 1024)))
_IMG_CACHE_TTL_S = int(os.environ.get("IMG_CACHE_TTL_S", str(7 * 24 * 60 * 60)))
_IMG_CACHE_EVICT_INTERVAL_S = 30 * 60
_img_cache_hits: int = 0
_img_cache_misses: int = 0
# Requests that missed on the first look, queued for a fetch slot, and found
# the bytes already on disk when their turn came — i.e. a herd that collapsed
# instead of each member paying its own OF round-trip. Counted apart from
# `hits` on purpose: a rising number here is the cold-pane storm being absorbed,
# which is a different thing to report than a warm cache.
_img_cache_collapsed: int = 0
_img_cache_writes: int = 0
_img_cache_skipped_partial: int = 0
_img_cache_skipped_too_big: int = 0
_img_cache_write_errors: int = 0


def _img_cache_key(u: str) -> str:
    """Account-agnostic SHA-1 over host+path. Same physical asset → same
    key, regardless of which account fetched it or how OF signed the URL."""
    from urllib.parse import urlparse as _urlparse
    parsed = _urlparse(u)
    base = (parsed.hostname or "").lower() + (parsed.path or "")
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def _img_cache_paths(h: str) -> tuple[Path, Path]:
    """Returns (bytes_path, content_type_path). Sharded into 2-char dirs
    so any one dir doesn't grow unbounded (matters for ext4/some FS)."""
    sub = _IMG_CACHE_DIR / h[:2]
    return sub / f"{h}.bin", sub / f"{h}.ct"


def _img_cache_lookup(u: str) -> tuple[Path, str] | None:
    """Returns (bytes_path, content_type) if a complete cache entry exists,
    else None. A complete entry has BOTH .bin and .ct present — half-written
    state is invisible (writers use unique .tmp paths and atomic rename)."""
    h = _img_cache_key(u)
    bin_p, ct_p = _img_cache_paths(h)
    if not bin_p.is_file() or not ct_p.is_file():
        return None
    try:
        ct = ct_p.read_text(encoding="utf-8", errors="replace").strip() or "application/octet-stream"
    except OSError:
        return None
    return bin_p, ct


def _img_cache_touch(bin_p: Path, ct_p: Path) -> None:
    """Refresh an entry's mtime on a cache HIT so the TTL evictor ages it by
    last-ACCESS, not last-WRITE. Without this a frequently-served image (a
    popular vault preview shared by many messages) is evicted at
    _IMG_CACHE_TTL_S even while in active use, forcing a CDN refetch and a
    visible tile flicker. Throttled: only bumps when the entry is already
    older than one evict interval, so a hot file costs at most ~one utime per
    interval — not one per request. Best-effort; never raises into the
    request path."""
    try:
        now = _time_mod.time()
        if now - bin_p.stat().st_mtime < _IMG_CACHE_EVICT_INTERVAL_S:
            return  # touched recently — skip the syscall
        os.utime(bin_p, (now, now))
        try:
            os.utime(ct_p, (now, now))
        except OSError:
            pass
    except OSError:
        pass


def _img_cache_write(u: str, content_type: str, data: bytes) -> bool:
    """Atomically write `data` for `u` to the cache. Unique .tmp filename
    + rename means concurrent writers for the same hash don't corrupt
    each other (last writer wins, identical bytes either way). Returns
    True on success."""
    global _img_cache_writes, _img_cache_write_errors
    h = _img_cache_key(u)
    bin_p, ct_p = _img_cache_paths(h)
    try:
        bin_p.parent.mkdir(parents=True, exist_ok=True)
        suffix = f".tmp.{os.getpid()}.{threading.get_ident()}"
        tmp_bin = bin_p.with_suffix(bin_p.suffix + suffix)
        tmp_ct = ct_p.with_suffix(ct_p.suffix + suffix)
        tmp_bin.write_bytes(data)
        tmp_ct.write_text(content_type, encoding="utf-8")
        os.replace(tmp_bin, bin_p)
        os.replace(tmp_ct, ct_p)
        _img_cache_writes += 1
        return True
    except OSError:
        _img_cache_write_errors += 1
        # Best-effort cleanup of leftover .tmp files; ignore errors.
        for p in (tmp_bin, tmp_ct):  # type: ignore[possibly-unbound]
            try: p.unlink()
            except (OSError, NameError): pass
        return False


def _img_cache_evict_once() -> int:
    """Walk the cache dir and delete entries older than _IMG_CACHE_TTL_S
    (by mtime). Returns the number of (bin, ct) pairs removed. Cheap on
    a few-tens-of-thousands of files; if the cache grows past that we'd
    want a smarter index, but this is fine for current expected size."""
    if not _IMG_CACHE_DIR.exists():
        return 0
    import time as _t
    cutoff = _t.time() - _IMG_CACHE_TTL_S
    removed = 0
    # Pinned just-sent media (Wave 2.1) is protected from TTL eviction
    # during its warm-up window so the local copy always outlives OF's
    # CDN cold-start. Prune expired pins first, then snapshot the surviving
    # key set so we can skip those files below.
    _pin_prune_expired()
    with _pin_lock:
        protected = set(_pinned_keys)
    try:
        for sub in _IMG_CACHE_DIR.iterdir():
            if not sub.is_dir():
                continue
            for f in sub.iterdir():
                try:
                    if f.stem in protected:
                        continue
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                        if f.suffix == ".bin":
                            removed += 1
                except OSError:
                    continue
    except OSError:
        return removed
    return removed


async def _img_cache_sweep() -> None:
    removed = await asyncio.to_thread(_img_cache_evict_once)
    if removed:
        log.info("img cache evicted: %d entries (TTL=%ds)", removed, _IMG_CACHE_TTL_S)


async def _img_cache_evictor_loop() -> None:
    """Periodic TTL sweep. Same shape as _storyboard_evictor_loop."""
    await _periodic("img cache evictor", _IMG_CACHE_EVICT_INTERVAL_S, _img_cache_sweep)


# ── Pinned outbound media (Wave 2.1) ──────────────────────────────────
#
# When WE send an image, the frontend renders it instantly from a local
# blob (useSendMessage `_localPreview`). After OF reconciles the message,
# the bubble swaps to /img?u=<of-cdn-url>. That CDN URL can be COLD for
# the first seconds/minutes after upload — OF's edge hasn't warmed the
# object yet — so a just-sent image can flip to a slow/blank state.
#
# Fix: right after a successful send, fetch the freshly-signed media URLs
# server-side ONCE and write the bytes into the on-disk /img cache under
# their host+path key — the SAME key the reconciled /img?u= request will
# resolve to (signature stripped, see `_img_cache_key`). The reconciled
# bubble then disk-HITs our local copy instead of racing OF's cold edge.
#
# We track the pin by MEDIA ID so (a) we never re-fetch the same media
# twice and (b) the TTL evictor leaves the entry alone during the warm-up
# window — guaranteeing the local copy outlives the CDN cold-start
# regardless of cache pressure. After the window, normal TTL reclaims it.
_IMG_PIN_WARM_S = int(os.environ.get("IMG_PIN_WARM_S", str(24 * 60 * 60)))
_IMG_PIN_MAX_URLS = 6                 # cap variants warmed per media (full/thumb/preview/…)
_pin_lock = threading.Lock()
# media_id -> {"keys": set[str], "pinned_at": float (monotonic)}
_pinned_media: dict[str, dict[str, Any]] = {}
_pinned_keys: set[str] = set()        # union of pinned cache-key hashes (fast evictor skip)
_img_pins_added: int = 0
_img_pins_fetched: int = 0
_img_pins_fetch_errors: int = 0
_img_pins_skipped_existing: int = 0


def _pin_prune_expired() -> None:
    """Drop pins past the warm-up window so normal TTL can reclaim their
    bytes, and rebuild the flat key set from survivors. Cheap; safe to
    call on every evictor pass."""
    now = _time_mod.monotonic()
    with _pin_lock:
        stale = [m for m, p in _pinned_media.items()
                 if now - p["pinned_at"] > _IMG_PIN_WARM_S]
        if not stale:
            return
        for m in stale:
            _pinned_media.pop(m, None)
        _pinned_keys.clear()
        for p in _pinned_media.values():
            _pinned_keys.update(p["keys"])


def _media_urls_from_result(result: Any) -> list[tuple[str, list[str]]]:
    """Extract [(media_id, [absolute CDN urls])] from an OF send response.
    Tolerant of shape drift: walks a top-level `media` list (the
    /chats/{id}/messages send echo) and pulls every `files.*.url` plus any
    top-level src/preview/thumb url on the item. Returns [] for shapes
    without per-message media (mass/queue echoes), so it's a no-op there."""
    out: list[tuple[str, list[str]]] = []
    if not isinstance(result, dict):
        return out
    media = result.get("media")
    if not isinstance(media, list):
        return out
    for it in media:
        if not isinstance(it, dict):
            continue
        mid = it.get("id")
        if mid is None:
            continue
        urls: list[str] = []
        files = it.get("files")
        if isinstance(files, dict):
            for variant in files.values():
                if isinstance(variant, dict):
                    u = variant.get("url")
                    if isinstance(u, str) and u.startswith("http"):
                        urls.append(u)
        for k in ("full", "src", "preview", "thumb", "squareThumb"):
            u = it.get(k)
            if isinstance(u, str) and u.startswith("http"):
                urls.append(u)
        if urls:
            out.append((str(mid), urls))
    return out


@contextlib.contextmanager
def _priority_lane_background(account_id: str):
    """Acquire the per-account total + background semaphores (background
    priority) for a server-side fetch with no request context.

    Delegates to `_priority_lane` with the priority forced, so this path
    gets the same accounting and the same enter/exit pairing rather than a
    second copy of the branch that drifts from it."""
    with _priority_lane(account_id, priority="background"):
        yield


def _pin_one_media_blocking(account_id: str, media_id: str, urls: list[str]) -> None:
    """Fetch each variant's bytes (via the account's OF client) and write
    them into the on-disk /img cache under their host+path key, then record
    the pin keyed by media id. Runs in a worker thread (blocking curl).
    Best-effort — never raises out."""
    global _img_pins_fetched, _img_pins_fetch_errors, _img_pins_added, _img_pins_skipped_existing
    from urllib.parse import urlparse as _urlparse
    # Dedup by cache key (variants can share a path) and cap how many we warm.
    seen: dict[str, str] = {}   # cache_key -> url
    for u in urls:
        try:
            host = (_urlparse(u).hostname or "").lower()
        except Exception:
            continue
        if not any(host.endswith(s) for s in _ALLOWED_CDN_SUFFIXES):
            continue
        seen.setdefault(_img_cache_key(u), u)
        if len(seen) >= _IMG_PIN_MAX_URLS:
            break
    if not seen:
        return
    try:
        client = _load_client(account_id)
    except Exception:
        return
    pinned: set[str] = set()
    for k, u in seen.items():
        # Already on disk (e.g. re-sending a vault asset we've served
        # before) → no fetch, just pin the existing entry so the evictor
        # protects it for the warm-up window.
        if _img_cache_lookup(u) is not None:
            pinned.add(k)
            _img_pins_skipped_existing += 1
            continue
        try:
            with _priority_lane_background(account_id):
                r = client.http.get(u, timeout=client.timeout_s, stream=False)
            if r.status_code != 200:
                _img_pins_fetch_errors += 1
                continue
            data = r.content or b""
            # Honour the same size cap as the live cache — a >2MB asset
            # wouldn't be disk-cached on reconcile anyway, so pinning it
            # would just be dead weight the serve path can't use.
            if not (0 < len(data) <= _IMG_CACHE_MAX_BYTES):
                continue
            ct = r.headers.get("Content-Type", "application/octet-stream")
            if _img_cache_write(u, ct, data):
                pinned.add(k)
                _img_pins_fetched += 1
        except Exception:
            _img_pins_fetch_errors += 1
            continue
    if not pinned:
        return
    now = _time_mod.monotonic()
    with _pin_lock:
        entry = _pinned_media.get(media_id)
        if entry is None:
            entry = {"keys": set(), "pinned_at": now}
            _pinned_media[media_id] = entry
        entry["keys"] |= pinned
        entry["pinned_at"] = now
        _pinned_keys.update(pinned)
    _img_pins_added += 1


def _pin_sent_media(account_id: str, result: Any) -> None:
    """Fire-and-forget from a send handler: warm + pin the on-disk /img
    cache with the bytes of any media in an outbound send response, so the
    reconciled bubble serves a local copy instead of OF's cold edge.
    Reserves the media id under the lock immediately so concurrent/rapid
    sends of the same asset don't double-fetch. Never blocks the response;
    never raises."""
    try:
        items = _media_urls_from_result(result)
    except Exception:
        return
    if not items:
        return
    _pin_prune_expired()
    now = _time_mod.monotonic()
    fresh: list[tuple[str, list[str]]] = []
    with _pin_lock:
        for media_id, urls in items:
            if media_id in _pinned_media:
                continue
            # Reserve now (empty key set) so a second send of the same media
            # in-flight is deduped; the worker fills in the keys on success.
            _pinned_media[media_id] = {"keys": set(), "pinned_at": now}
            fresh.append((media_id, urls))
    for media_id, urls in fresh:
        try:
            asyncio.create_task(
                asyncio.to_thread(_pin_one_media_blocking, account_id, media_id, urls)
            )
        except Exception:
            log.debug("pin dispatch failed (media_id=%s)", media_id, exc_info=True)


@app.get("/admin/streams")
def admin_streams() -> dict:
    """Live view of the /img stream budget. `active` = currently streaming
    right now; `high_water` = peak since startup. If active sits near the
    thread-pool limit while you scroll, that's the bottleneck. If it stays
    low but you still see ECONNRESETs, look elsewhere (Next dev proxy,
    upstream OF, network)."""
    return {
        "active": _img_active,
        "high_water": _img_high_water,
        "total_started": _img_total_started,
        "total_aborted": _img_total_aborted,
        # `collapsed` is the one to watch on a cold pane: it counts the storms
        # the fetch lane absorbed rather than passed on to OF.
        "img_cache_collapsed": _img_cache_collapsed,
        # Every lane reports itself — derived, not restated, so a lane added
        # later cannot be forgotten in the diagnostics that would show it
        # saturating. See service/admission.py.
        **admission.all_stats(),
    }


# ── /admin/errors ───────────────────────────────────────────────────
# Persisted error log. The frontend POSTs unhandled errors here via
# useErrorReporter; the server's exception middleware writes 500s
# here too. GET returns recent rows for the badge + admin viewer.

_APP_ERROR_CONTEXT_MAX = 16384


def _app_error_context_json(text: str) -> str:
    """The stored context, always valid JSON: one too long to keep whole is kept
    as its first characters under `truncated` (a raw slice of the JSON text
    would not parse, and GET /admin/errors would 500 on it)."""
    if len(text) <= _APP_ERROR_CONTEXT_MAX:
        return text
    return json.dumps({"truncated": text[:_APP_ERROR_CONTEXT_MAX - 64]})


def _app_error_context(raw: str | None) -> Any:
    """A row's context for GET /admin/errors; a row stored before
    _app_error_context_json (a cut-off JSON text) comes back as that text."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return {"unparsed": raw}


class _AppErrorBody(BaseModel):
    source: str = "browser"             # "browser" | "server" (clients should send "browser")
    kind: str = "error"                 # short category — "unhandledrejection", "react-render", …
    message: str
    stack: str | None = None
    url: str | None = None
    account_id: str | None = None
    employee_id: int | None = None
    user_agent: str | None = None
    # Free-form bag of extra fields the client wants persisted. Stored
    # as a JSON blob; we don't enforce a schema.
    context: dict[str, Any] | None = None


@app.post("/admin/errors")
async def admin_errors_create(body: _AppErrorBody = Body(...)) -> dict[str, Any]:
    """Persist a single error report. Never raises — if we can't write
    we still 200 so the reporter loop doesn't error-on-error."""
    from db.engine import get_session
    from db.models import AppError
    # The list is served to every caller (not tenant-filtered): no pool proxy secrets in it.
    scrub = proxy_registry.scrub_pool_secrets
    try:
        async with get_session() as s:
            row = AppError(
                source=(body.source or "browser")[:32],
                kind=(body.kind or "error")[:64],
                message=scrub(body.message or "")[:4096],
                stack=scrub(body.stack)[:16384] if body.stack else None,
                url=scrub(body.url)[:1024] if body.url else None,
                account_id=body.account_id[:64] if body.account_id else None,
                employee_id=body.employee_id,
                user_agent=body.user_agent[:512] if body.user_agent else None,
                context_json=_app_error_context_json(scrub(json.dumps(body.context))) if body.context else None,
            )
            s.add(row)
            await s.commit()
            return {"ok": True, "id": row.id}
    except Exception:
        log.exception("failed to persist app_error")
        return {"ok": False}


@app.delete("/admin/errors")
async def admin_errors_clear(
    since_hours: int | None = Query(None, ge=1, le=720, description="Only clear rows within this window; omit to clear all"),
    source: str | None = Query(None, description="Filter by 'browser' or 'server'"),
) -> dict[str, Any]:
    """Dismiss errors — used by the TopNav badge's Clear button. Deletes
    rows matching the same filter the GET uses so the badge count drops
    to zero immediately."""
    from db.engine import get_session
    from db.models import AppError
    from sqlalchemy import delete as sa_delete
    async with get_session() as s:
        stmt = sa_delete(AppError)
        if since_hours is not None:
            cutoff = datetime.utcnow() - timedelta(hours=since_hours)
            stmt = stmt.where(AppError.occurred_at >= cutoff)
        if source:
            stmt = stmt.where(AppError.source == source)
        result = await s.execute(stmt)
        await s.commit()
        return {"ok": True, "deleted": result.rowcount or 0}


@app.get("/admin/errors")
async def admin_errors_list(
    limit: int = Query(50, ge=1, le=500),
    since_hours: int = Query(24, ge=1, le=720),
    source: str | None = Query(None, description="Filter by 'browser' or 'server'"),
) -> dict[str, Any]:
    """Recent errors, newest first. `since_hours` defaults to 24h so the
    TopNav badge can count today's errors cheaply."""
    from db.engine import get_session
    from db.models import AppError
    from sqlalchemy import select, and_
    cutoff = datetime.utcnow() - timedelta(hours=since_hours)
    async with get_session() as s:
        stmt = select(AppError).where(AppError.occurred_at >= cutoff)
        if source:
            stmt = stmt.where(AppError.source == source)
        stmt = stmt.order_by(AppError.occurred_at.desc()).limit(limit)
        rows = (await s.execute(stmt)).scalars().all()
        return {
            "count": len(rows),
            "since_hours": since_hours,
            "list": [
                {
                    "id": r.id,
                    "occurred_at": r.occurred_at.isoformat() + "Z",
                    "source": r.source,
                    "kind": r.kind,
                    "message": r.message,
                    "stack": r.stack,
                    "url": r.url,
                    "account_id": r.account_id,
                    "employee_id": r.employee_id,
                    "user_agent": r.user_agent,
                    "context": _app_error_context(r.context_json),
                }
                for r in rows
            ],
        }


# ── /admin/perflog — client-side timing log ingest ────────────────
# Frontend `app/lib/perfLog.ts` batches PerfEvents and POSTs them here so
# we can aggregate "tab open → call asked → call delivered" timing across
# all chatters. Append-only. Pruned every `_PERFLOG_EVICT_INTERVAL_S` by
# `_perflog_evictor_loop()` so the table stays bounded.

_PERFLOG_RETAIN_S = int(os.environ.get("PERFLOG_RETAIN_S", str(7 * 24 * 60 * 60)))
_PERFLOG_EVICT_INTERVAL_S = 60 * 60
_PERFLOG_BATCH_MAX = 500
_PERFLOG_META_MAX_BYTES = 4 * 1024


class _PerfLogEventBody(BaseModel):
    opId: str
    kind: str
    phase: str
    ts: float  # client epoch ms (may be sub-ms float from performance.timeOrigin)
    tabId: str | None = None
    meta: dict[str, Any] | None = None


class _PerfLogIngestBody(BaseModel):
    tabId: str
    parentTabId: str | None = None
    employeeId: int | None = None
    accountId: str | None = None
    events: list[_PerfLogEventBody]


@app.post("/admin/perflog/ingest")
async def admin_perflog_ingest(request: Request, body: _PerfLogIngestBody = Body(...)) -> dict[str, Any]:
    """Persist a batch of client-side perf events. Never raises — if we
    can't write we still 200 so the client's flush loop doesn't error-on-
    error. Sent via `navigator.sendBeacon` on page unload, plain
    `fetch(..., keepalive: true)` otherwise.

    Soft-tags rows with the requesting employee + account from headers
    when the body didn't carry them, so analytics queries can filter on
    "who's been seeing slow loads"."""
    from db.engine import get_session
    from db.models import PerfEventRow

    if not body.events:
        return {"ok": True, "inserted": 0}
    events = body.events[:_PERFLOG_BATCH_MAX]

    # Best-effort identity backfill from headers (employee picker writes
    # X-Employee-Id on every relayed call; X-Account-Id rides scope).
    hdr_employee_raw = request.headers.get("x-employee-id")
    try:
        hdr_employee_id: int | None = int(hdr_employee_raw) if hdr_employee_raw else None
    except ValueError:
        hdr_employee_id = None
    hdr_account_id = request.headers.get("x-account-id") or None

    employee_id = body.employeeId if body.employeeId is not None else hdr_employee_id
    account_id = body.accountId if body.accountId else hdr_account_id

    try:
        async with get_session() as s:
            for e in events:
                meta_str: str | None = None
                if e.meta is not None:
                    try:
                        meta_str = json.dumps(e.meta, default=str)[:_PERFLOG_META_MAX_BYTES]
                    except (TypeError, ValueError):
                        meta_str = None
                # The body tabId is per-batch; fall back to per-event if a
                # client ever wants to ship cross-tab batches (today they
                # don't — but keeping the schema honest).
                tab_id = (e.tabId or body.tabId)[:64]
                s.add(PerfEventRow(
                    tab_id=tab_id,
                    parent_tab_id=body.parentTabId[:64] if body.parentTabId else None,
                    op_id=(e.opId or "")[:128],
                    kind=(e.kind or "")[:64],
                    phase=(e.phase or "")[:32],
                    client_ts_ms=int(e.ts),
                    employee_id=employee_id,
                    account_id=account_id[:64] if account_id else None,
                    meta_json=meta_str,
                ))
            await s.commit()
        return {"ok": True, "inserted": len(events)}
    except Exception:
        log.exception("perflog ingest failed")
        return {"ok": False}


@app.get("/admin/perflog/recent")
async def admin_perflog_recent(
    limit: int = Query(200, ge=1, le=2000),
    since_minutes: int = Query(60, ge=1, le=24 * 60 * 7),
    kind: str | None = Query(None, description="Filter by event kind (exact match)"),
    tab_id: str | None = Query(None, description="Filter to a single tab session"),
    op_id: str | None = Query(None, description="Filter to a single op id (all phases)"),
) -> dict[str, Any]:
    """Recent perfLog events, newest first. Powers ad-hoc inspection of
    timing across chatters — e.g. histogram of `vault.media` request→
    delivered deltas, or per-tab "open → first useful paint" times."""
    from db.engine import get_session
    from db.models import PerfEventRow
    from sqlalchemy import select

    cutoff = datetime.utcnow() - timedelta(minutes=since_minutes)
    async with get_session() as s:
        stmt = select(PerfEventRow).where(PerfEventRow.received_at >= cutoff)
        if kind:
            stmt = stmt.where(PerfEventRow.kind == kind)
        if tab_id:
            stmt = stmt.where(PerfEventRow.tab_id == tab_id)
        if op_id:
            stmt = stmt.where(PerfEventRow.op_id == op_id)
        stmt = stmt.order_by(PerfEventRow.received_at.desc()).limit(limit)
        rows = (await s.execute(stmt)).scalars().all()
        return {
            "count": len(rows),
            "since_minutes": since_minutes,
            "list": [
                {
                    "id": r.id,
                    "tab_id": r.tab_id,
                    "parent_tab_id": r.parent_tab_id,
                    "op_id": r.op_id,
                    "kind": r.kind,
                    "phase": r.phase,
                    "client_ts_ms": r.client_ts_ms,
                    "received_at": r.received_at.isoformat() + "Z",
                    "employee_id": r.employee_id,
                    "account_id": r.account_id,
                    "meta": json.loads(r.meta_json) if r.meta_json else None,
                }
                for r in rows
            ],
        }


# ── messages.raw_json retention ───────────────────────────────────────
#
# `raw_json` stores the full OF message payload per row (avg ~8 KB, mostly
# the media[] array nobody reads back — it's only a migration safety-net).
# Left unbounded it grew the DB to ~1.9 GB. We keep a recent window so a
# future backfill still has fresh payloads to read, and NULL anything older.
#
# This is a NULL-out, not a row delete — message rows stay intact, only the
# heavy column is cleared. auto_vacuum is off, so freed pages return to the
# freelist and are reused by new inserts; the file plateaus rather than
# growing. To actually shrink the file on disk, run VACUUM manually.
_RAW_JSON_RETAIN_S = int(os.environ.get("RAW_JSON_RETAIN_S", str(60 * 24 * 60 * 60)))
_RAW_JSON_EVICT_INTERVAL_S = int(os.environ.get("RAW_JSON_EVICT_INTERVAL_S", str(24 * 60 * 60)))

# How long after startup a DAILY sweeper takes its first pass (see `_periodic`
# for why the daily ones need one at all). Long enough to stay out of startup's
# way — index creation, the pumps connecting, the first ingest walk — and short
# enough that a relay restarted twice a day still prunes twice a day. A restart
# loop therefore re-sweeps, which is harmless: after the first pass these
# deletes match nothing and cost only their scan.
_EVICT_BOOT_GRACE_S = int(os.environ.get("EVICT_BOOT_GRACE_S", str(5 * 60)))


async def _raw_json_sweep() -> None:
    from db.engine import get_session
    from db.models import Message
    from sqlalchemy import update as sa_update
    cutoff = datetime.utcnow() - timedelta(seconds=_RAW_JSON_RETAIN_S)
    async with get_session() as s:
        res = await s.execute(
            sa_update(Message)
            .where(Message.created_at < cutoff, Message.raw_json.isnot(None))
            .values(raw_json=None)
        )
        await s.commit()
        if (res.rowcount or 0) > 0:
            log.info("raw_json evictor cleared %d rows (retain=%ds)", res.rowcount, _RAW_JSON_RETAIN_S)


async def _raw_json_evictor_loop() -> None:
    """Periodic NULL-out of messages.raw_json older than _RAW_JSON_RETAIN_S.
    Caps DB growth (the payloads are a write-only migration buffer). Runs
    daily by default; tune via RAW_JSON_RETAIN_S / RAW_JSON_EVICT_INTERVAL_S."""
    await _periodic(
        "raw_json evictor", _RAW_JSON_EVICT_INTERVAL_S, _raw_json_sweep,
        # Daily interval, sub-daily uptime — see _periodic. 3,668 rows were
        # still holding payloads past a 60-day window when this was measured.
        first_after_s=_EVICT_BOOT_GRACE_S,
    )


async def _perflog_sweep() -> None:
    from db.engine import get_session
    from db.models import PerfEventRow
    from sqlalchemy import delete as sa_delete
    cutoff = datetime.utcnow() - timedelta(seconds=_PERFLOG_RETAIN_S)
    async with get_session() as s:
        res = await s.execute(
            sa_delete(PerfEventRow).where(PerfEventRow.received_at < cutoff)
        )
        await s.commit()
        if (res.rowcount or 0) > 0:
            log.info("perflog evictor pruned %d rows (retain=%ds)", res.rowcount, _PERFLOG_RETAIN_S)


async def _perflog_evictor_loop() -> None:
    """Periodic prune of perf_events older than _PERFLOG_RETAIN_S. Cheap —
    indexed on received_at. Runs hourly by default; tune via env."""
    await _periodic("perflog evictor", _PERFLOG_EVICT_INTERVAL_S, _perflog_sweep)


# ── audit / log table retention ──────────────────────────────────────
#
# Four append-only tables had NO prune and grew unbounded — so the DB crept
# back toward bloat from the audit side even after the raw-payload columns were
# capped. Each gets a retention window; one daily sweep DELETEs rows past it.
# These are ROW-deletes only. ⚠️ Prod is auto_vacuum=NONE (measured 2026-08-04:
# `PRAGMA auto_vacuum` → 0, freelist 97782 pages), so deleted pages go to the
# freelist and the FILE NEVER SHRINKS — `_reclaim_freelist()` early-returns
# until the DB is converted to INCREMENTAL. This comment previously claimed the
# opposite, which is precisely why grok_calls was allowed to reach 1.3 GB while
# looking self-healing. Reclaiming disk needs a deliberate offline VACUUM.
# Set any window to 0 to disable that table.
_AUTOMATION_RUNS_RETAIN_S = int(os.environ.get("AUTOMATION_RUNS_RETAIN_S", str(14 * 24 * 60 * 60)))
_GROK_CALLS_RETAIN_S = int(os.environ.get("GROK_CALLS_RETAIN_S", str(30 * 24 * 60 * 60)))
_SCHEDULED_JOBS_RETAIN_S = int(os.environ.get("SCHEDULED_JOBS_RETAIN_S", str(7 * 24 * 60 * 60)))
_ACTIONS_RETAIN_S = int(os.environ.get("ACTIONS_RETAIN_S", str(90 * 24 * 60 * 60)))
_AUDIT_EVICT_INTERVAL_S = int(os.environ.get("AUDIT_EVICT_INTERVAL_S", str(24 * 60 * 60)))


async def evict_audit_logs_once() -> dict[str, int]:
    """One retention sweep of the append-only audit/log tables that otherwise
    grow unbounded: automation_runs (run audit), grok_calls (LLM-call audit),
    scheduled_jobs (only the TERMINAL done/error rows), actions (mutation audit).
    Deletes rows older than each table's own window. grok_daily_cost (the cap
    rollup) is a SEPARATE, tiny, un-pruned table, so spend/cap history survives
    the grok_calls per-call prune. Returns {tablename: deleted_count}."""
    from db.engine import get_session
    from db.models import Action, AutomationRun, GrokCall, ScheduledJob
    from sqlalchemy import delete as sa_delete

    now = datetime.utcnow()
    plan = [
        (AutomationRun, AutomationRun.started_at, _AUTOMATION_RUNS_RETAIN_S, None),
        (GrokCall, GrokCall.called_at, _GROK_CALLS_RETAIN_S, None),
        (ScheduledJob, ScheduledJob.created_at, _SCHEDULED_JOBS_RETAIN_S,
         ScheduledJob.status.in_(("done", "error"))),
        (Action, Action.at, _ACTIONS_RETAIN_S, None),
    ]
    out: dict[str, int] = {}
    for model, col, retain_s, extra in plan:
        if retain_s <= 0:
            continue
        cutoff = now - timedelta(seconds=retain_s)
        stmt = sa_delete(model).where(col < cutoff)
        if extra is not None:
            stmt = stmt.where(extra)
        async with get_session() as s:
            res = await s.execute(stmt)
            await s.commit()
            out[model.__tablename__] = int(res.rowcount or 0)
    return out


async def _audit_retention_sweep() -> None:
    pruned = {k: v for k, v in (await evict_audit_logs_once()).items() if v}
    if pruned:
        log.info("audit-retention evictor pruned %s", pruned)


async def _audit_retention_evictor_loop() -> None:
    """Daily retention sweep of the unbounded audit/log tables. Tune each window
    via AUTOMATION_RUNS_RETAIN_S / GROK_CALLS_RETAIN_S / SCHEDULED_JOBS_RETAIN_S
    / ACTIONS_RETAIN_S (0 disables a table). See evict_audit_logs_once.

    Sweeps after a boot grace rather than after a full day — this loop's own
    interval used to exceed the process's typical uptime, so it had never run.
    See _periodic for the measurements. The delete is one statement per table on
    purpose: measured on a snapshot of the live DB, the two big ones clear 137k
    and 133k rows in 798ms and 931ms, so the write lock is held for about a
    second, once a day. Batching that would be machinery bought against a cost
    nobody is paying."""
    await _periodic(
        "audit-retention evictor", _AUDIT_EVICT_INTERVAL_S, _audit_retention_sweep,
        first_after_s=_EVICT_BOOT_GRACE_S,
    )


# SQLite's advice for long-lived connections: `PRAGMA optimize` every few hours
# (init_db runs it once at boot). Refreshes planner stats only for tables whose
# row counts moved, sampled (analysis_limit), so a pass is milliseconds.
_DB_OPTIMIZE_INTERVAL_S = 6 * 60 * 60


async def _db_optimize_loop() -> None:
    from db.engine import optimize as _db_optimize
    await _periodic("sqlite optimize", _DB_OPTIMIZE_INTERVAL_S, _db_optimize)


# ── raw-OF-payload SIZE cap (event_inbox + messages.raw_json) ─────────
#
# Two columns hoard raw OnlyFans payloads we receive but read back only for
# a short window:
#   • event_inbox.payload_json — the raw WS/SSE event firehose. Every event
#     is already transcoded into permanent tables (DMs → messages, subs →
#     fans, tips → transactions); the envelope is re-read ONLY for SSE
#     Last-Event-ID reconnect replay (minutes–hours) and provider_event_id
#     idempotency. It was NEVER pruned → the real leak.
#   • messages.raw_json — the full OF message JSON (mostly the media[] array
#     nobody reads back). The real message lives in its own columns. The
#     time-based _raw_json_evictor_loop (60d) already trims it; this size
#     cap is the hard ceiling on top, for when volume — not age — is the
#     problem.
#
# The time-based evictors above bound the trailing window; THIS bounds the
# absolute footprint so the SQLite file stays well under ~2 GB.
#
# Two facts shape the design:
#   1. auto_vacuum is OFF on the prod DB, so DELETE / NULL only moves pages
#      to the freelist — the FILE plateaus at its high-water mark, it does
#      not shrink. So a "if file > 2 GB, delete" cap would never shrink
#      anything. We therefore drive the cap off LOGICAL content bytes
#      (SUM(LENGTH(...))), and reclaim disk separately via incremental_vacuum
#      once the DB has been converted to auto_vacuum=INCREMENTAL (a one-time
#      full VACUUM — gated behind PAYLOAD_VACUUM_ON_START so it only runs on
#      a deliberately-scheduled off-peak restart).
#   2. We must lose ZERO fan data. The cap NEVER deletes messages/fans/
#      transactions ROWS — it deletes spent event_inbox envelopes and NULLs
#      the duplicate raw_json column, and NEVER touches anything newer than
#      the retention floor (the last EVENT_INBOX_RETAIN_FLOOR_S stays intact
#      for debugging + SSE replay).
#
# Default budget 1.5 GB of payload bytes keeps total DB < 2 GB (the rest —
# message columns, fans, txns, indexes — is ~0.4 GB and grows slowly).
_PAYLOAD_BUDGET_BYTES = int(os.environ.get("PAYLOAD_BUDGET_BYTES", str(1_500_000_000)))
_PAYLOAD_RETAIN_FLOOR_S = int(os.environ.get("EVENT_INBOX_RETAIN_FLOOR_S", str(2 * 24 * 60 * 60)))
_PAYLOAD_CAP_INTERVAL_S = int(os.environ.get("PAYLOAD_CAP_INTERVAL_S", str(60 * 60)))
_PAYLOAD_EVICT_BATCH = int(os.environ.get("PAYLOAD_EVICT_BATCH", "2000"))
# Unconditional age cap on the event_inbox landing table — runs EVERY tick,
# independent of the byte budget above. event_inbox is a spent-envelope log:
# the WS transcoder writes the real message/chat/transaction rows synchronously,
# so nothing reads an envelope older than a couple days. The budget-driven cap
# only trims event_inbox once LOGICAL payload exceeds PAYLOAD_BUDGET_BYTES
# (1.5 GB) — which the envelope + raw_json bytes can sit under for a month while
# the table still accretes hundreds of thousands of rows (the exact failure we
# saw: 360k rows / 421 MB with the budget cap never firing). This hard age floor
# holds event_inbox at a fixed ~2-day window no matter what the budget is doing.
# Set to 0 to disable (fall back to budget-only behavior).
_EVENT_INBOX_MAX_AGE_S = int(os.environ.get("EVENT_INBOX_MAX_AGE_S", str(2 * 24 * 60 * 60)))
# One-time conversion of an existing auto_vacuum=NONE DB to INCREMENTAL +
# the heavy full VACUUM that makes it take effect. Off by default; flip on
# for a single off-peak restart (via a deploy), then unset. After conversion,
# incremental_vacuum each tick returns freed pages to the OS for free.
_PAYLOAD_VACUUM_ON_START = os.environ.get("PAYLOAD_VACUUM_ON_START", "0") == "1"
# Pages reclaimed per tick once auto_vacuum=INCREMENTAL. Bounded so each tick
# holds the write lock only briefly (default ~80 MB at 4 KiB pages).
_PAYLOAD_INCR_VACUUM_PAGES = int(os.environ.get("PAYLOAD_INCR_VACUUM_PAGES", "20000"))

# VACUUM / incremental_vacuum are whole-DB write locks; never let two run at
# once, and never overlap a full VACUUM with an eviction pass.
_payload_vacuum_lock = asyncio.Lock()


def _floor_cutoff_str(floor_s: int) -> str:
    """Retention-floor cutoff as the fixed-width string SQLAlchemy stores
    DateTime in ('YYYY-MM-DD HH:MM:SS.ffffff'), so a raw `received_at < ?`
    comparison sorts chronologically. Rows newer than this are never touched."""
    return (datetime.utcnow() - timedelta(seconds=floor_s)).strftime("%Y-%m-%d %H:%M:%S.%f")


async def _payload_bytes(conn) -> tuple[int, int]:
    """(event_inbox.payload_json bytes, messages.raw_json bytes) via SUM(LENGTH).
    This is the LOGICAL content size the cap is driven off — not file size."""
    ev = (await conn.exec_driver_sql(
        "SELECT COALESCE(SUM(LENGTH(payload_json)), 0) FROM event_inbox"
    )).scalar() or 0
    rj = (await conn.exec_driver_sql(
        "SELECT COALESCE(SUM(LENGTH(raw_json)), 0) FROM messages"
    )).scalar() or 0
    return int(ev), int(rj)


async def evict_payloads_once(
    *,
    budget_bytes: int | None = None,
    floor_s: int | None = None,
    batch: int | None = None,
) -> dict[str, int]:
    """Size-driven eviction of raw OF payloads. SQLite only (no-op elsewhere —
    Postgres autovacuums and has no rowid).

    Frees logical payload bytes until
        SUM(LENGTH(event_inbox.payload_json)) + SUM(LENGTH(messages.raw_json))
    is under `budget_bytes`, deleting the OLDEST event_inbox rows first (the
    real leak, lowest value — a spent envelope), then NULLing the OLDEST
    messages.raw_json — but NEVER touching any row whose timestamp is within
    `floor_s` of now. Eviction happens in autocommit batches so the write
    lock is released between batches and the WS pump keeps flowing.

    Touches ONLY the two raw envelope columns; messages / fans / transactions
    ROWS are left fully intact. Idempotent: a no-op once under budget, and a
    no-op once everything older than the floor is gone (it will not breach the
    floor to reach budget — it logs that it's floor-bound instead).

    Returns a summary dict (also used by the test to assert before/after)."""
    from db.engine import engine, _is_sqlite
    budget = _PAYLOAD_BUDGET_BYTES if budget_bytes is None else budget_bytes
    floor = _PAYLOAD_RETAIN_FLOOR_S if floor_s is None else floor_s
    bsize = _PAYLOAD_EVICT_BATCH if batch is None else batch
    if not _is_sqlite:
        return {"skipped": 1}

    cutoff = _floor_cutoff_str(floor)
    deleted_events = nulled_messages = freed = 0

    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        ev0, rj0 = await _payload_bytes(conn)
        before = ev0 + rj0
        over = before - budget

        if over > 0:
            # 1) event_inbox — delete oldest spent envelopes older than floor.
            while freed < over:
                row = (await conn.exec_driver_sql(
                    "SELECT COALESCE(SUM(LENGTH(payload_json)), 0), COUNT(*) FROM "
                    "(SELECT payload_json FROM event_inbox "
                    " WHERE received_at < ? ORDER BY rowid ASC LIMIT ?)",
                    (cutoff, bsize),
                )).first()
                nbytes, cnt = int(row[0] or 0), int(row[1] or 0)
                if cnt == 0:
                    break  # nothing left older than the floor
                await conn.exec_driver_sql(
                    "DELETE FROM event_inbox WHERE rowid IN "
                    "(SELECT rowid FROM event_inbox WHERE received_at < ? "
                    " ORDER BY rowid ASC LIMIT ?)",
                    (cutoff, bsize),
                )
                deleted_events += cnt
                freed += nbytes
                await asyncio.sleep(0)  # yield between batches

            # 2) messages.raw_json — NULL oldest duplicates older than floor.
            while freed < over:
                row = (await conn.exec_driver_sql(
                    "SELECT COALESCE(SUM(LENGTH(raw_json)), 0), COUNT(*) FROM "
                    "(SELECT raw_json FROM messages "
                    " WHERE raw_json IS NOT NULL AND created_at < ? "
                    " ORDER BY rowid ASC LIMIT ?)",
                    (cutoff, bsize),
                )).first()
                nbytes, cnt = int(row[0] or 0), int(row[1] or 0)
                if cnt == 0:
                    break
                await conn.exec_driver_sql(
                    "UPDATE messages SET raw_json = NULL WHERE rowid IN "
                    "(SELECT rowid FROM messages WHERE raw_json IS NOT NULL "
                    " AND created_at < ? ORDER BY rowid ASC LIMIT ?)",
                    (cutoff, bsize),
                )
                nulled_messages += cnt
                freed += nbytes
                await asyncio.sleep(0)

        ev1, rj1 = await _payload_bytes(conn)

    after = ev1 + rj1
    summary = {
        "before_bytes": before,
        "after_bytes": after,
        "budget_bytes": budget,
        "freed_bytes": freed,
        "deleted_events": deleted_events,
        "nulled_messages": nulled_messages,
        "event_bytes_after": ev1,
        "raw_json_bytes_after": rj1,
        "floor_bound": int(after > budget),  # 1 = floor stopped us short of budget
    }
    return summary


async def prune_event_inbox_once(
    *,
    max_age_s: int | None = None,
    batch: int | None = None,
) -> dict[str, int]:
    """Unconditional age-based prune of the event_inbox landing table. Deletes
    EVERY row older than `max_age_s` (default _EVENT_INBOX_MAX_AGE_S = 2 days),
    regardless of the size budget — unlike evict_payloads_once, which only trims
    event_inbox when total LOGICAL payload exceeds PAYLOAD_BUDGET_BYTES.

    event_inbox is a spent-envelope log: by the time a row lands here the WS
    transcoder has already written the real message/chat/transaction rows, so an
    envelope older than a couple days is dead weight (kept only for short-window
    debugging + SSE replay). Touches ONLY event_inbox — messages / fans /
    transactions are never referenced. Batched autocommit deletes so the WS
    pump's write lock is released between batches and the firehose keeps flowing.
    SQLite only (no-op elsewhere — Postgres has no rowid and autovacuums).

    Returns {"deleted_events": N} (0 = nothing older than the cutoff)."""
    from db.engine import engine, _is_sqlite
    age = _EVENT_INBOX_MAX_AGE_S if max_age_s is None else max_age_s
    bsize = _PAYLOAD_EVICT_BATCH if batch is None else batch
    if not _is_sqlite or age <= 0:
        return {"deleted_events": 0, "skipped": int(age <= 0)}

    cutoff = _floor_cutoff_str(age)
    deleted = 0
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        while True:
            res = await conn.exec_driver_sql(
                "DELETE FROM event_inbox WHERE rowid IN "
                "(SELECT rowid FROM event_inbox WHERE received_at < ? "
                " ORDER BY rowid ASC LIMIT ?)",
                (cutoff, bsize),
            )
            n = int(res.rowcount or 0)
            deleted += n
            if n < bsize:
                break
            await asyncio.sleep(0)  # yield between batches — let the pump write
    return {"deleted_events": deleted, "cutoff": cutoff}


async def _maybe_convert_to_incremental_autovacuum() -> None:
    """One-time: convert an existing auto_vacuum=NONE DB to INCREMENTAL so the
    freelist can be returned to the OS. The conversion itself requires a full
    VACUUM (rewrites the whole file — a heavy, whole-DB write lock), so it is
    gated behind PAYLOAD_VACUUM_ON_START and runs at most once per boot. No-op
    if already INCREMENTAL or not SQLite."""
    from db.engine import engine, _is_sqlite
    if not _is_sqlite or not _PAYLOAD_VACUUM_ON_START:
        return
    async with _payload_vacuum_lock:
        try:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                mode = (await conn.exec_driver_sql("PRAGMA auto_vacuum")).scalar()
                if int(mode or 0) == 2:
                    log.info("payload-cap: auto_vacuum already INCREMENTAL")
                    return
                log.warning("payload-cap: converting auto_vacuum→INCREMENTAL via full VACUUM "
                            "(heavy, whole-DB lock) — this runs once")
                await conn.exec_driver_sql("PRAGMA auto_vacuum=INCREMENTAL")
                await conn.exec_driver_sql("VACUUM")
                mode2 = (await conn.exec_driver_sql("PRAGMA auto_vacuum")).scalar()
                log.warning("payload-cap: auto_vacuum now=%s (2=INCREMENTAL)", mode2)
        except Exception:
            log.warning("payload-cap: auto_vacuum conversion failed", exc_info=True)


async def _reclaim_freelist() -> None:
    """Return up to _PAYLOAD_INCR_VACUUM_PAGES freelist pages to the OS. Cheap
    and bounded (unlike full VACUUM); only does anything once the DB is in
    auto_vacuum=INCREMENTAL mode — otherwise it is a silent no-op. Guarded by
    the vacuum lock so it never overlaps the one-time full VACUUM."""
    from db.engine import engine, _is_sqlite
    if not _is_sqlite:
        return
    async with _payload_vacuum_lock:
        try:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                if int((await conn.exec_driver_sql("PRAGMA auto_vacuum")).scalar() or 0) != 2:
                    return  # NONE/FULL mode: incremental_vacuum is a no-op
                free0 = int((await conn.exec_driver_sql("PRAGMA freelist_count")).scalar() or 0)
                if free0 <= 0:
                    return
                await conn.exec_driver_sql(f"PRAGMA incremental_vacuum({_PAYLOAD_INCR_VACUUM_PAGES})")
                free1 = int((await conn.exec_driver_sql("PRAGMA freelist_count")).scalar() or 0)
                if free0 != free1:
                    log.info("payload-cap: reclaimed %d freelist pages (%d→%d)",
                             free0 - free1, free0, free1)
        except Exception:
            log.warning("payload-cap: incremental_vacuum failed", exc_info=True)


async def _payload_size_cap_sweep() -> None:
    pruned = await prune_event_inbox_once()
    if pruned.get("deleted_events"):
        log.info("event-inbox prune: deleted %d rows older than %ds",
                 pruned["deleted_events"], _EVENT_INBOX_MAX_AGE_S)
    summary = await evict_payloads_once()
    if summary.get("freed_bytes"):
        log.info(
            "payload-cap: %d→%d MB (budget %d MB) — deleted %d events, "
            "nulled %d raw_json%s",
            summary["before_bytes"] // 1_000_000,
            summary["after_bytes"] // 1_000_000,
            summary["budget_bytes"] // 1_000_000,
            summary["deleted_events"],
            summary["nulled_messages"],
            " (floor-bound)" if summary.get("floor_bound") else "",
        )
    await _reclaim_freelist()


async def _payload_size_cap_loop() -> None:
    """Periodic size cap on the raw OF payload columns. Each tick:
      1. prune event_inbox to a hard ~2-day age window (unconditional — this is
         what keeps the landing table from accreting a month-long backlog while
         the byte budget sits idle);
      2. evict raw payloads down to PAYLOAD_BUDGET_BYTES (honoring the floor);
      3. return freed pages to the OS (once auto_vacuum=INCREMENTAL).
    Hourly by default; tune via EVENT_INBOX_MAX_AGE_S / PAYLOAD_* env vars.

    The autovacuum conversion runs ONCE, before the cadence starts — it is a
    one-time migration of the DB's page layout, not part of the sweep."""
    await _maybe_convert_to_incremental_autovacuum()
    await _periodic("payload-cap", _PAYLOAD_CAP_INTERVAL_S, _payload_size_cap_sweep)


# ── /admin/chats/recent — instant-load seed for the inbox ──────────
# Returns the most recent rows from the LOCAL `chats` table (populated
# by the WS transcoder) joined to `fans` for display names + avatars.
# Sub-50ms because everything is indexed in SQLite — no OF call.
# Used by the frontend to render an instant 10-25 row chat list while
# the live OF `/chats` fetch is still in flight, so users can click a
# conversation immediately instead of waiting for the cold OF round-trip.

@app.get("/admin/chats/recent")
async def admin_chats_recent(
    limit: int = Query(25, ge=1, le=100),
    account_id: str | None = Query(None, description="Filter to one account; omit for all"),
) -> dict[str, Any]:
    from db.engine import get_session
    from db.models import Chat as _Chat, Fan as _Fan
    from sqlalchemy import select
    account_ids = clamp_account_filter(account_id)
    async with get_session() as s:
        stmt = (
            select(_Chat, _Fan)
            .join(_Fan, (_Fan.account_id == _Chat.account_id) & (_Fan.fan_id == _Chat.fan_id), isouter=True)
            .where(_Chat.hidden_locally == False)  # noqa: E712
            .order_by(_Chat.last_message_at.desc().nullslast())
            .limit(limit)
        )
        if account_ids is not None:
            if not account_ids:
                return {"list": [], "source": "local-db"}
            stmt = stmt.where(_Chat.account_id.in_(account_ids))
        rows = (await s.execute(stmt)).all()
        out: list[dict[str, Any]] = []
        for chat, fan in rows:
            out.append({
                "__accountId": chat.account_id,
                "withUser": {
                    "id": chat.fan_id,
                    "name": fan.of_display_name if fan else None,
                    "username": fan.of_username if fan else None,
                    "avatar": fan.avatar_url if fan else None,
                },
                "lastMessage": {
                    "id": chat.last_message_id,
                    "text": chat.last_message_preview or "",
                    "createdAt": chat.last_message_at.isoformat() + "Z" if chat.last_message_at else None,
                } if chat.last_message_id else None,
                "hasUnread": (chat.unread_count or 0) > 0,
                "unreadMessagesCount": chat.unread_count or 0,
            })
        return {"list": out, "source": "local-db"}


@app.get("/img")
def proxy_image(request: Request, u: str = Query(..., description="Absolute OF CDN URL")):
    """Fetch `u` via the requesting account's OF client (so the source IP
    matches the URL's signed Policy) and stream the bytes back. The unsigned
    static hosts (`_DIRECT_CDN_HOST`) are the exception: they go out the
    relay's own IP on `_DIRECT_HTTP`, with no cookies or account headers."""
    from urllib.parse import urlparse
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="bad scheme")
    host = (parsed.hostname or "").lower()
    if not any(host.endswith(s) for s in _ALLOWED_CDN_SUFFIXES):
        raise HTTPException(status_code=400, detail="host not allowed")

    range_hdr = request.headers.get("range") or request.headers.get("Range")

    # Disk-cache fast path: only safe when the client wants the WHOLE
    # asset (no Range). Cached bytes are account-agnostic — once we have
    # them, the upstream signature is irrelevant for serving them again.
    # Skipped on Range because we don't store partials.
    if not range_hdr:
        global _img_cache_hits, _img_cache_misses
        hit = _img_cache_lookup(u)
        if hit is not None:
            _img_cache_hits += 1
            return _serve_cached(hit, u, label="HIT")
        _img_cache_misses += 1

    if _DIRECT_CDN_HOST.fullmatch(host):
        http, timeout_s = _DIRECT_HTTP, DEFAULT_TIMEOUT_S
    else:
        client = _get_client(request)
        http, timeout_s = client.http, client.timeout_s

    # Forward the browser's Range header so video <video> tags can seek.
    # Without this, the upstream always returns 200 with the whole file and
    # the browser can't jump past whatever's buffered — long videos can't
    # be scrubbed, and `currentTime` writes stall.
    upstream_headers: dict[str, str] = {}
    if range_hdr:
        upstream_headers["Range"] = range_hdr

    # A Range request is a browser <video> seeking and has its own ceiling;
    # everything reaching here without one is a cache miss on its way to OF.
    # Picking the lane rather than branching on it keeps ONE admission site —
    # the rejection reads the same for both because the lane names itself.
    held = admission.VIDEO_STREAM if range_hdr else admission.IMG_FETCH
    if not held.enter(u[:80]):
        raise HTTPException(
            status_code=503,
            detail=f"too many {held.name} requests in flight; retry shortly",
        )

    if not range_hdr:
        # Re-read the store INSIDE the slot, the same way vault_stills does.
        # Forty tiles opening on one media all miss together, all queue here,
        # and without this re-read each would then pay its own OF round-trip
        # for bytes the first waiter has already written. The cap bounds how
        # many run at once; this is what stops them being redundant.
        hit = _img_cache_lookup(u)
        if hit is not None:
            held.exit()
            global _img_cache_collapsed
            # Not also counted as a hit: this request DID miss, and was already
            # tallied as one above. `collapsed` is the separate story of how
            # many of those misses the lane absorbed instead of forwarding.
            _img_cache_collapsed += 1
            return _serve_cached(hit, u, label="COLLAPSED")

    # From here to the `return StreamingResponse` the slot is held by THIS
    # frame; past it, `_safe_iter`'s finally owns the release. Everything
    # between is wrapped because a lane that leaks a slot never gets it back —
    # it drains to zero and then rejects every request forever. Three
    # hand-placed release sites used to cover only the two failures anyone had
    # thought of, leaving the header-building below unguarded.
    #
    # The unwind closes the upstream response too. That is not hypothetical
    # tidiness: OF answers 403 on an expired signature, which is the single most
    # common failure this proxy sees, and an unclosed streamed response holds its
    # socket. Leaking a descriptor per expired thumbnail, inside the very
    # function whose descriptor use took the process down, is the bug this whole
    # change exists to prevent.
    r = None
    try:
        try:
            r = http.get(
                u, timeout=timeout_s, stream=True,
                headers=upstream_headers or None,
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"upstream fetch failed: {e}")
        # 206 (Partial Content) is the normal Range response — treat it as ok.
        if r.status_code not in (200, 206):
            raise HTTPException(status_code=r.status_code, detail="upstream non-2xx")
        return _stream_upstream(
            r, u, held, range_hdr,
            account_id_hdr=request.headers.get("x-account-id") or "")
    except BaseException:
        if r is not None:
            try: r.close()
            except Exception: pass
        held.exit()
        raise


def _serve_cached(hit: tuple[Path, str], u: str, *, label: str) -> FileResponse:
    """Serve bytes we already have on disk.

    `label` rides out as `X-Img-Cache` and is the only thing that differs
    between the two ways we get here — a first-look hit, and a waiter that
    found the bytes written while it queued for a fetch slot. They were two
    copies of this block; the header value is not a reason to have two.
    """
    bin_p, ct_cached = hit
    # Keep popular entries warm: age by last-access, not last-write, so a hot
    # vault preview isn't evicted out from under live use.
    _img_cache_touch(*_img_cache_paths(_img_cache_key(u)))
    return FileResponse(
        str(bin_p),
        media_type=ct_cached,
        headers={
            "Cache-Control":
                "public, max-age=604800, stale-while-revalidate=86400, immutable",
            "X-Img-Cache": label,
        },
    )


def _stream_upstream(r: Any, u: str, held: admission.Lane,
                     range_hdr: str | None, *,
                     account_id_hdr: str) -> StreamingResponse:
    """Wrap a live upstream response as the streamed reply, handing `held` to
    the generator — which is what releases it, whether the stream ends, the
    client vanishes, or the max-age timer fires.

    Takes the account id rather than the `Request` it came from: this streams
    bytes and needs exactly one header off the caller, and a helper holding a
    whole request object invites the next person to reach for more of it.

    ⚠️ The release lives in the generator's `finally`, so it depends on
    something iterating the generator. Starlette always does — including closing
    it on client disconnect, which arrives as GeneratorExit and is caught — but
    that is the one assumption keeping this lane from leaking, and it is why the
    caller unwinds by hand for every path that returns BEFORE this point.
    """
    ct = r.headers.get("Content-Type", "application/octet-stream")
    # OF's CDN sends short Cache-Control because the signed Policy expires,
    # but the IMAGE BYTES themselves don't expire. We override upstream's
    # header to keep the browser HTTP cache (and a future Service Worker)
    # holding the asset for 7 days — matches the disk-cache TTL above so
    # the browser doesn't re-fetch bytes we still have on disk. Once we've
    # fetched the bytes, the upstream signature is irrelevant for serving
    # them again. SWR window of 1 day lets the SW serve a stale copy
    # instantly while silently refreshing in the background.
    cache_control = "public, max-age=604800, stale-while-revalidate=86400, immutable"
    out_headers = {"Cache-Control": cache_control}
    # Stable hash exposed back to the browser so the frontend can pivot
    # to /img/by-hash/<h> on subsequent renders — same image, same key,
    # even after OF rotates the upstream signature.
    if account_id_hdr:
        try:
            h_stable = _img_hash_remember(account_id_hdr, u)
            out_headers["X-Img-Hash"] = h_stable
        except Exception:
            # Hashing should never fail (urlparse + sha1), but if it does
            # we just skip the header — the proxy still works.
            pass
    # Pass through the bits the <video> element relies on to seek. Without
    # Accept-Ranges Chrome won't even attempt a Range request; without
    # Content-Range it can't tell what slice it got back.
    for h in ("Content-Range", "Accept-Ranges", "Content-Length", "ETag", "Last-Modified"):
        v = r.headers.get(h)
        if v:
            out_headers[h] = v
    if "Accept-Ranges" not in out_headers:
        # If upstream didn't advertise but we got 206/200, hint that we
        # support ranges so the browser will try one next time.
        out_headers["Accept-Ranges"] = "bytes"

    # Wrap iter_content so a browser-side abort (the common case — user
    # hovers a new tile, the old <video> unmounts, the TCP socket dies)
    # cleanly closes the upstream connection instead of bubbling up as
    # an unhandled ChunkedEncodingError / ConnectionResetError that the
    # worker would otherwise log as a 500 and tear down the thread.
    # Also enforces a hard max-stream-age so a `/img` stream can't pin a
    # worker thread for the full lifetime of an mp4 — uvicorn's graceful
    # shutdown was taking 2+ minutes because in-flight streams blocked on
    # iter_content() and never noticed the shutdown signal. After
    # _MAX_STREAM_SEC we bail; the browser will reissue a Range request
    # for the rest, which is what `<video>` elements do natively anyway.
    _MAX_STREAM_SEC = 60
    import time as _time
    started_mono = _time.monotonic()

    # Tee bytes to the disk cache only when the upstream response is a
    # complete 200 (not 206), the request had no Range, and Content-Length
    # is either unknown or under the cap. We additionally enforce the cap
    # while streaming — past it, we drop the buffer rather than allocate
    # unbounded memory for a video that slipped past the host filter.
    out_headers["X-Img-Cache"] = "MISS" if not range_hdr else "BYPASS"
    cache_buffer: bytearray | None = None
    if not range_hdr and r.status_code == 200:
        try:
            advertised = int(r.headers.get("Content-Length") or 0)
        except ValueError:
            advertised = 0
        if 0 < advertised <= _IMG_CACHE_MAX_BYTES or advertised == 0:
            cache_buffer = bytearray()
        else:
            global _img_cache_skipped_too_big
            _img_cache_skipped_too_big += 1
    elif r.status_code == 206:
        global _img_cache_skipped_partial
        _img_cache_skipped_partial += 1

    def _safe_iter():
        global _img_active, _img_high_water, _img_total_started, _img_total_aborted
        global _img_cache_skipped_too_big
        _img_active += 1
        _img_total_started += 1
        if _img_active > _img_high_water:
            _img_high_water = _img_active
        aborted = False
        completed = False
        local_buf = cache_buffer
        try:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if _time.monotonic() - started_mono > _MAX_STREAM_SEC:
                    # Hit our cap — close upstream so the worker thread
                    # is reusable. The browser will Range-request the
                    # tail if it still wants more bytes.
                    break
                if chunk:
                    if local_buf is not None:
                        if len(local_buf) + len(chunk) > _IMG_CACHE_MAX_BYTES:
                            # Asset grew past the cap mid-stream — drop
                            # the buffer (don't cache), keep streaming.
                            _img_cache_skipped_too_big += 1
                            local_buf = None
                        else:
                            local_buf.extend(chunk)
                    yield chunk
            else:
                completed = True
        except (ConnectionResetError, BrokenPipeError, GeneratorExit):
            # Client went away — silent, this is normal browser behavior
            # for unmounting video elements.
            aborted = True
        except Exception:
            aborted = True
            log.warning("upstream stream error mid-flight (u=%s)", u[:120], exc_info=True)
        finally:
            if aborted:
                _img_total_aborted += 1
            _img_active = max(0, _img_active - 1)
            try:
                r.close()
            except Exception:
                pass
            # Only persist when the full upstream body landed cleanly.
            # Aborted/truncated bodies must never enter the cache.
            if completed and not aborted and local_buf is not None and len(local_buf) > 0:
                try:
                    _img_cache_write(u, ct, bytes(local_buf))
                except Exception:
                    log.warning("img cache write failed (u=%s)", u[:120], exc_info=True)
            # Released LAST, after the bytes are on disk. The waiter this hands
            # the slot to re-reads the store as its first act, so releasing
            # before the write is a race that costs exactly what the re-read
            # exists to save: it wakes, finds nothing, and pays its own
            # round-trip for bytes that were milliseconds away.
            held.exit()

    return StreamingResponse(
        _safe_iter(),
        media_type=ct,
        status_code=r.status_code,
        headers=out_headers,
    )


@app.get("/img/by-hash/{h}")
def proxy_image_by_hash(request: Request, h: str):
    """Stable-URL alias for /img. Resolves the hash to the most recent
    signed URL we've seen for it, then delegates to proxy_image. Returns
    410 if the signed URL has aged past _IMG_HASH_TTL_S — at that point
    the upstream signature is likely expired and the frontend should
    fetch a fresh URL from /messages (or whatever surface produced this
    asset originally) and call /img?u=... directly.

    The browser's Cache-Control window (2 days) is much longer than the
    upstream signature window (~1h), so most hits never reach the server
    at all — only first-sight requests touch us here."""
    with _img_hash_lock:
        entry = _img_hash_map.get(h)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail="unknown img hash; refetch the producing endpoint for a fresh signed URL",
        )
    u, ts = entry
    if _time_mod.monotonic() - ts > _IMG_HASH_TTL_S:
        # Drop the stale entry while we're here.
        with _img_hash_lock:
            _img_hash_map.pop(h, None)
        raise HTTPException(
            status_code=410,
            detail="signed URL expired; refetch the producing endpoint for a fresh one",
        )
    return proxy_image(request, u=u)


@app.get("/admin/priority-lanes/stats")
def admin_priority_lane_stats() -> dict:
    """Is the per-account OF lane actually a queue?

    Read this BEFORE deciding whether the acquire needs a timeout. The
    numbers that matter: `blocked_total` vs `calls` (what fraction of
    requests queued at all) and `wait_s_max` / `wait_s_avg_blocked` (how
    long the ones that queued actually waited). They count blocked acquires
    ONLY — an entry that took a free slot adds to `calls` and nothing else.

    The window is `window_s`, NOT `uptime_s`: cumulative counters survive
    restarts on disk, so the numbers can span several relay lifetimes and
    `boots` says how many. `uptime_s` is only this process — when it is far
    smaller than `window_s`, the live gauges are young but the totals are not.

    Nothing here rejects or bounds anything; `rejections` is 0 by
    construction and is listed so the shape stays stable if a bound is
    ever added."""
    def _view(st: dict) -> dict:
        blocked = st["blocked_total"] + st["blocked_background"]
        wait_s = st["wait_s_total"] + st["wait_s_background"]
        return {
            "calls": st["calls"],
            "calls_user": st["calls_user"],
            "calls_background": st["calls_background"],
            "blocked": blocked,
            "blocked_total": st["blocked_total"],
            "blocked_background": st["blocked_background"],
            "blocked_rate": round(blocked / st["calls"], 4) if st["calls"] else 0.0,
            "wait_s_total": round(st["wait_s_total"], 3),
            "wait_s_background": round(st["wait_s_background"], 3),
            "wait_s_avg_blocked": round(wait_s / blocked, 3) if blocked else 0.0,
            "wait_s_max": round(st["wait_s_max"], 3),
            "in_flight": st["in_flight"],
            "in_flight_peak": st["in_flight_peak"],
            "bg_in_flight": st["bg_in_flight"],
            "bg_in_flight_peak": st["bg_in_flight_peak"],
            "saturated": st["in_flight"] >= _ACCOUNT_LANE_TOTAL,
        }

    snap = _lane_stats_snapshot()
    overall = _view(snap["overall"])
    rows = {aid: _view(st) for aid, st in snap["accounts"].items()}
    # The fleet-wide row's `saturated`/peaks are sums across accounts, not a
    # cap breach — the cap is per account, so drop the flag there.
    overall.pop("saturated", None)
    return {
        "cap_total": _ACCOUNT_LANE_TOTAL,
        "cap_background": _ACCOUNT_LANE_BACKGROUND,
        "window_s": max(0, int(_time_mod.time() - snap["started_at"])),
        "uptime_s": int(_time_mod.monotonic() - _lane_stats_since),
        "boots": snap["boots"],
        "persisted_to": str(_LANE_STATS_PATH) if _LANE_STATS_PATH else None,
        "persist_error": _lane_stats_load_error or _lane_stats_write_error,
        "lanes": len(_account_lanes),
        "rejections": 0,
        "overall": overall,
        "accounts": dict(sorted(
            rows.items(),
            key=lambda kv: (kv[1]["blocked"], kv[1]["wait_s_total"]),
            reverse=True,
        )),
    }


@app.get("/admin/img-cache/disk")
def admin_img_cache_disk() -> dict:
    """Disk cache stats. `hit_rate` is the headline number — if it stays
    near zero, the cache isn't paying for itself; if it climbs past ~0.4
    we're saving meaningful upstream calls. `bytes` is a `du`-equivalent
    of the cache root so we can see growth over time."""
    total_bytes = 0
    entry_count = 0
    try:
        if _IMG_CACHE_DIR.exists():
            for sub in _IMG_CACHE_DIR.iterdir():
                if not sub.is_dir():
                    continue
                for f in sub.iterdir():
                    try:
                        st = f.stat()
                        total_bytes += st.st_size
                        if f.suffix == ".bin":
                            entry_count += 1
                    except OSError:
                        continue
    except OSError:
        pass
    total = _img_cache_hits + _img_cache_misses
    hit_rate = (_img_cache_hits / total) if total else 0.0
    return {
        "dir": str(_IMG_CACHE_DIR),
        "entries": entry_count,
        "bytes": total_bytes,
        "hits": _img_cache_hits,
        "misses": _img_cache_misses,
        "writes": _img_cache_writes,
        "hit_rate": round(hit_rate, 3),
        "skipped_partial": _img_cache_skipped_partial,
        "skipped_too_big": _img_cache_skipped_too_big,
        "write_errors": _img_cache_write_errors,
        "max_bytes_per_entry": _IMG_CACHE_MAX_BYTES,
        "ttl_seconds": _IMG_CACHE_TTL_S,
        # Wave 2.1 pinned-outbound-media stats.
        "pins_active": len(_pinned_media),
        "pinned_keys": len(_pinned_keys),
        "pins_added": _img_pins_added,
        "pins_fetched": _img_pins_fetched,
        "pins_skipped_existing": _img_pins_skipped_existing,
        "pins_fetch_errors": _img_pins_fetch_errors,
        "pin_warm_seconds": _IMG_PIN_WARM_S,
    }


@app.get("/admin/img-cache/stats")
def admin_img_cache_stats() -> dict:
    """Live view of the hash → signed-URL map. `entries` counts distinct
    images we've ever proxied since boot; `freshest_age_s` shows how
    recently we saw activity. Used to gauge whether /img/by-hash is
    actually doing work (entries climbing == hits expected to follow)."""
    now = _time_mod.monotonic()
    with _img_hash_lock:
        n = len(_img_hash_map)
        if n:
            ages = [now - ts for _, ts in _img_hash_map.values()]
            oldest_age = int(max(ages))
            freshest_age = int(min(ages))
        else:
            oldest_age = 0
            freshest_age = 0
    return {
        "entries": n,
        "cap": _IMG_HASH_CAP,
        "ttl_seconds": _IMG_HASH_TTL_S,
        "oldest_age_s": oldest_age,
        "freshest_age_s": freshest_age,
    }


@app.get("/admin/_debug/relay-cache-stats")
def admin_relay_cache_stats() -> dict[str, Any]:
    """Hit/miss counters + entry counts for the in-process relay_cache.

    Empty `namespaces` is expected until Stage C wires call-sites into
    `relay_cache.get_or_fetch(...)`. Useful afterwards for tuning TTLs:
    a namespace with 0 hits after a warm-up window is either keyed wrong
    (per-employee data cached account-wide?) or has every caller passing
    `?refresh=1`.
    """
    return relay_cache.stats()


# ── Video scrub storyboard ────────────────────────────────────────────
#
# /img/scrub?u=<signed-video-url>&i=<0..11>
#
# Replaces the streaming hover-preview pipeline (two <video> elements
# pulling Range bytes through /img) with 12 pre-extracted JPGs at evenly
# spaced timestamps (every 8.33%). First request for a video triggers
# a one-time ffmpeg extraction: download the mp4, extract 12 frames,
# write to disk, drop the mp4. Subsequent requests serve directly from
# disk and are immutable cacheable.
#
# Motivation: streaming videos through /img pinned uvicorn threadpool
# slots for up to 60s each. Five users hovering through video tiles
# could deadlock the relay. Storyboard frames are ~20KB JPGs served
# from disk — never blocks the upstream pool past the one-time build.

# Configurable cache root. /tmp is fine on macOS (cleared at boot, so
# eviction handles itself). In Docker /tmp is per-container and goes
# away on restart — point STORYBOARD_DIR at a mounted volume in prod
# so storyboards survive across container restarts.
_STORYBOARD_DIR = Path(os.environ.get("STORYBOARD_DIR", "/tmp/of-relay-storyboard"))
_STORYBOARD_FRAMES = 12
_STORYBOARD_WIDTH = 400
# Drop from 90s → 30s. Past 30s Next dev's HTTP proxy and most browsers
# have already given up; holding the uvicorn worker thread any longer
# just leaks the slot for nothing. The client retries naturally on the
# next hover cycle so failing fast is cheaper than queueing zombies.
_STORYBOARD_BUILD_TIMEOUT_S = 30
_storyboard_locks: dict[str, threading.Lock] = {}
_storyboard_locks_lock = threading.Lock()
_storyboard_total_built: int = 0
_storyboard_total_served: int = 0
_storyboard_build_failures: int = 0
# Per-hover-session cancel signal. Set by POST /img/scrub/cancel when the
# user moves off a video before its download finishes. The download loop
# polls this every chunk and bails IF it hasn't already crossed the
# "almost done" threshold below — past that point we let the bytes
# finish landing so the next hover gets a warm cache.
#
# Keyed by `session_id` (client-generated UUID per hover) rather than by
# video hash on purpose: a previous fix used hash-keyed events, which let
# a late cancel POST from a prior hover abort a brand-new build for the
# same video (re-hover within ~100-300ms). With session-keyed events,
# the new hover gets a new id → fresh event → the stale cancel POST
# finds no entry and is a no-op.
_storyboard_cancel_events: dict[str, threading.Event] = {}
_storyboard_cancel_events_lock = threading.Lock()
# If the cancel arrives after this fraction of the bytes has landed,
# we finish the download anyway — the remaining bandwidth is cheap and
# the cached storyboard will be there next time the user hovers this
# video. Lower = more cache built (more wasted bytes on truly-abandoned
# videos); higher = less wasted bandwidth (more re-download next time).
# 0.80 was the user's call after measuring the tradeoff.
_STORYBOARD_CANCEL_KEEP_THRESHOLD = 0.80
_storyboard_total_cancelled: int = 0
_storyboard_total_cancel_ignored: int = 0


def _storyboard_register_session(session_id: str) -> threading.Event:
    """Reserve a cancel event for an active build's session. Called once
    at the start of a download; the event is dropped at end of build."""
    with _storyboard_cancel_events_lock:
        ev = threading.Event()
        _storyboard_cancel_events[session_id] = ev
        return ev


def _storyboard_release_session(session_id: str) -> None:
    """Drop the session's cancel event after the build finishes (success
    or failure). Late cancel POSTs that arrive after this find no entry
    and become a no-op, which is the desired behaviour."""
    with _storyboard_cancel_events_lock:
        _storyboard_cancel_events.pop(session_id, None)


def _storyboard_signal_cancel(session_id: str) -> bool:
    """Set the cancel event for `session_id` if a build is active. Returns
    True when a live session was found, False otherwise (stale cancel)."""
    with _storyboard_cancel_events_lock:
        ev = _storyboard_cancel_events.get(session_id)
    if ev is None:
        return False
    ev.set()
    return True


def _storyboard_lock_for(h: str) -> threading.Lock:
    with _storyboard_locks_lock:
        lk = _storyboard_locks.get(h)
        if lk is None:
            lk = threading.Lock()
            _storyboard_locks[h] = lk
        return lk


def _storyboard_evict_locks_once() -> int:
    """Drop `_storyboard_locks` entries for hashes whose on-disk
    storyboard dir is gone — the prune-storyboards cron deletes those
    dirs on TTL, but the in-memory lock dict would otherwise grow
    without bound (≈200 bytes per unique video ever hovered).

    Safety: we only evict a lock when (a) the dir is missing AND (b)
    `lock.acquire(blocking=False)` succeeds, meaning no thread is
    currently building. We then re-check the dir under the lock and
    only pop from the dict if the same lock instance is still mapped.
    Returns the number of entries evicted (for the periodic logger)."""
    existing: set[str] = set()
    try:
        if _STORYBOARD_DIR.exists():
            existing = {p.name for p in _STORYBOARD_DIR.iterdir() if p.is_dir()}
    except OSError:
        return 0
    with _storyboard_locks_lock:
        candidates = [h for h in _storyboard_locks.keys() if h not in existing]
    evicted = 0
    for h in candidates:
        with _storyboard_locks_lock:
            lk = _storyboard_locks.get(h)
        if lk is None:
            continue
        if not lk.acquire(blocking=False):
            continue  # active build → leave it alone
        try:
            if (_STORYBOARD_DIR / h).is_dir():
                continue  # someone resurrected it between our snapshot and now
            with _storyboard_locks_lock:
                if _storyboard_locks.get(h) is lk:
                    _storyboard_locks.pop(h, None)
                    evicted += 1
        finally:
            lk.release()
    return evicted


async def _storyboard_lock_sweep() -> None:
    evicted = await asyncio.to_thread(_storyboard_evict_locks_once)
    if evicted:
        log.info("storyboard locks evicted: %d", evicted)


async def _storyboard_evictor_loop() -> None:
    """Background task spawned at startup. Runs the lock evictor every
    30 minutes — matches the cadence of the prune-storyboards cron so
    the in-memory dict catches up shortly after the disk cleanup."""
    await _periodic("storyboard evictor", 30 * 60, _storyboard_lock_sweep)


def _video_path_hash(u: str) -> str:
    """SHA-1 of host+path (signature stripped, account-agnostic). Same
    physical video → same hash → same on-disk frames, regardless of
    which account fetched it or how OF signed the URL today."""
    from urllib.parse import urlparse as _urlparse
    parsed = _urlparse(u)
    base = (parsed.hostname or "").lower() + (parsed.path or "")
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]


_ALL_FRAME_INDICES = tuple(range(_STORYBOARD_FRAMES))


def _storyboard_frame_path(h: str, i: int) -> Path:
    return _STORYBOARD_DIR / h / f"{i}.jpg"


def _storyboard_all_frames_present(h: str) -> bool:
    return all(_storyboard_frame_path(h, i).is_file() for i in _ALL_FRAME_INDICES)


def _storyboard_download(
    request: Request, u: str, src_path: Path, session_id: str | None,
) -> bool:
    """Pull the mp4 into src_path via the right account's HTTP client (so
    the URL's source-IP signature matches). Returns False on failure or
    when the client cancelled before 90% of the bytes had landed.

    The cancel hook lets us bail mid-download when the user moves on to
    another video. Past `_STORYBOARD_CANCEL_KEEP_THRESHOLD` we ignore
    the cancel and finish the bytes anyway — the next hover gets a
    warm cache and the bandwidth we already burned isn't wasted.

    `session_id` scopes the cancel to one hover session. If empty/None
    (old client, no sid supplied), the build runs without cancellation
    support — a missed cancel is strictly better than the alternative,
    which was aborting unrelated builds."""
    global _storyboard_build_failures, _storyboard_total_cancelled, _storyboard_total_cancel_ignored
    # Fresh, session-scoped event. Drop it on exit (finally) so a late
    # cancel POST arriving after the build wraps up is a no-op — not a
    # poison flag for the next session that happens to reuse this id.
    cancel_event = _storyboard_register_session(session_id) if session_id else None
    try:
        client = _get_client(request)
        r = client.http.get(u, timeout=client.timeout_s, stream=True)
        if r.status_code not in (200, 206):
            log.warning("storyboard download non-2xx %d for %s", r.status_code, u[:120])
            _storyboard_build_failures += 1
            return False
        total_bytes = 0
        try:
            total_bytes = int(r.headers.get("content-length") or 0)
        except (TypeError, ValueError):
            total_bytes = 0
        bytes_done = 0
        with src_path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if cancel_event is not None and cancel_event.is_set():
                    # Past the keep threshold? Honour the bytes we already
                    # paid for and finish the file — bumping the ignored
                    # counter so we can see the cap is working.
                    fraction = (bytes_done / total_bytes) if total_bytes > 0 else 0.0
                    if total_bytes > 0 and fraction >= _STORYBOARD_CANCEL_KEEP_THRESHOLD:
                        _storyboard_total_cancel_ignored += 1
                        cancel_event.clear()  # treat the rest of the dl as committed
                    else:
                        # Truly abort — drop the partial mp4, signal failure.
                        _storyboard_total_cancelled += 1
                        try: r.close()
                        except Exception: pass
                        return False
                if chunk:
                    f.write(chunk)
                    bytes_done += len(chunk)
        try: r.close()
        except Exception: pass
        return True
    except Exception:
        log.warning("storyboard download failed for %s", u[:120], exc_info=True)
        _storyboard_build_failures += 1
        try: src_path.unlink(missing_ok=True)
        except Exception: pass
        return False
    finally:
        if session_id:
            _storyboard_release_session(session_id)


def _storyboard_probe_duration(src_path: Path) -> float:
    """ffprobe → duration in seconds, 0 on failure."""
    import subprocess
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             str(src_path)],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return float(probe.stdout.strip())
    except Exception:
        return 0.0


def _storyboard_extract_batch(
    src_path: Path, dest: Path, indices: tuple[int, ...], dur: float,
) -> bool:
    """Extract all `indices` frames in a SINGLE ffmpeg invocation, using
    repeated `-ss TIME -i SRC -frames:v 1 OUT` blocks. ffmpeg reopens the
    file per `-i` (keyframe seek is fast on local disk) but the process
    spawn happens only once per batch — cuts pass-1 latency by ~4x for a
    4-frame batch vs. one subprocess per frame. Frames write directly to
    their final 0-based name.

    Tolerates partial success: if ffmpeg returns non-zero (common when
    the final frame's seek lands at/past EOF on short clips with
    rounded-up duration metadata) but at least one jpg landed on disk,
    we treat the batch as good. Returns False only if zero frames came
    out — that's the case where the source mp4 is unreadable or the
    timeout fired."""
    import subprocess
    # Stay at least 100ms before the encoded EOF — ffmpeg can't seek past
    # the last decodable frame, and short clips whose container metadata
    # rounds the duration up (e.g. "4.0s" for a 3.93s file) would otherwise
    # blow up on the last index.
    safe_dur = max(0.1, dur - 0.1)
    args: list[str] = ["ffmpeg", "-y", "-nostdin", "-loglevel", "error"]
    for pos, i in enumerate(indices):
        # Mid-segment seek (i + 0.5) lands away from cut boundaries where
        # an I-frame might be black or a hard transition.
        ts = (i + 0.5) * dur / _STORYBOARD_FRAMES
        ts = min(ts, safe_dur)
        out_path = dest / f"{i}.jpg"
        args += [
            "-ss", f"{ts:.4f}", "-i", str(src_path),
            "-map", f"{pos}:v:0",
            "-frames:v", "1",
            "-vf", f"scale={_STORYBOARD_WIDTH}:-2",
            "-q:v", "5",
            str(out_path),
        ]
    rc = -1
    try:
        proc = subprocess.run(
            args, check=False, capture_output=True,
            timeout=_STORYBOARD_BUILD_TIMEOUT_S,
        )
        rc = proc.returncode
    except Exception:
        log.warning(
            "storyboard batch extract crashed for %s indices=%s",
            dest.name, indices, exc_info=True,
        )

    landed = [i for i in indices if (dest / f"{i}.jpg").is_file()]
    if not landed:
        log.warning(
            "storyboard batch extract produced no frames for %s "
            "(rc=%s indices=%s dur=%.3f)",
            dest.name, rc, indices, dur,
        )
        return False
    if len(landed) < len(indices):
        # Backfill missing indices by copying the nearest neighbour so the
        # storyboard is always complete-shaped after a build. Without this
        # any missing frame would trigger a fresh download+extract on the
        # next request and fail the same way — an infinite loop.
        import shutil
        for i in indices:
            if (dest / f"{i}.jpg").is_file():
                continue
            nearest = min(landed, key=lambda j: abs(j - i))
            try:
                shutil.copyfile(dest / f"{nearest}.jpg", dest / f"{i}.jpg")
            except Exception:
                log.warning(
                    "storyboard backfill copy %s→%s failed for %s",
                    nearest, i, dest.name, exc_info=True,
                )
        log.info(
            "storyboard partial extract for %s: %d/%d frames (rc=%s dur=%.3f, backfilled rest)",
            dest.name, len(landed), len(indices), rc, dur,
        )
    return True


def _ensure_storyboard_frame(
    request: Request, u: str, h: str, i: int,
    *, hint_duration: float | None = None,
    session_id: str | None = None,
) -> bool:
    """Make sure frame `i` is on disk. Returns True if it is now.

    Single-pass build: any caller that finds the storyboard missing
    downloads the source mp4 and extracts all 12 frames in one batched
    ffmpeg invocation. We tried a two-phase (4-then-8) split but the
    measured breakdown showed ffmpeg is ~230ms total vs ~3-7s for the
    download — splitting saved nothing meaningful and added background-
    thread coordination.

    `hint_duration` (seconds) lets the caller skip ffprobe entirely —
    VaultMedia carries duration in the vault listing so the client
    passes it through. The worst case if it's wrong is mis-spaced
    scrub frames; we sanity-check it's positive."""
    global _storyboard_total_built, _storyboard_build_failures
    dest = _STORYBOARD_DIR / h
    frame_path = _storyboard_frame_path(h, i)

    if frame_path.is_file():
        return True

    lock = _storyboard_lock_for(h)
    if not lock.acquire(timeout=_STORYBOARD_BUILD_TIMEOUT_S):
        return False
    build_slot = False
    try:
        # Another concurrent caller may have produced our frame while we
        # waited on the lock.
        if frame_path.is_file():
            return True

        # Global build slot. Taken INSIDE the per-video lock deliberately:
        # everyone queued on that lock is waiting on a build of the SAME video
        # already under way, and a waiter holding a build slot would be
        # reserving a core it will never use. The lock stops duplicate work;
        # the lane stops N DISTINCT videos putting N ffmpeg processes on a
        # 2-core box.
        if not admission.STORYBOARD_BUILD.enter(f"scrub h={h}"):
            return False
        build_slot = True

        dest.mkdir(parents=True, exist_ok=True)
        src_path = dest / "source.tmp"

        # Download mp4 (skipped if a prior failed build left it around).
        if not src_path.is_file():
            if not _storyboard_download(request, u, src_path, session_id):
                # On cancel/error, drop the partial bytes — incomplete
                # mp4s aren't useful for extraction.
                try: src_path.unlink(missing_ok=True)
                except Exception: pass
                return False

        if hint_duration and hint_duration > 0:
            dur = hint_duration
        else:
            dur = _storyboard_probe_duration(src_path)
        if dur <= 0:
            _storyboard_build_failures += 1
            try: src_path.unlink(missing_ok=True)
            except Exception: pass
            return False

        if not _storyboard_extract_batch(src_path, dest, _ALL_FRAME_INDICES, dur):
            _storyboard_build_failures += 1
            # Drop the source mp4 on extract failure. The previous code
            # kept it around so a follow-up call could skip the download
            # and re-attempt extraction, but if the file is the cause of
            # the failure (corrupt download, codec ffmpeg can't decode)
            # leaving it on disk pins us into an infinite-retry loop on
            # this video — every subsequent hover hits the same broken
            # mp4 and fails the same way. Re-downloading is cheap
            # relative to a permanently-broken cache entry.
            try: src_path.unlink(missing_ok=True)
            except Exception: pass
            return False

        try: src_path.unlink(missing_ok=True)
        except Exception: pass
        _storyboard_total_built += 1
        return frame_path.is_file()
    finally:
        if build_slot:
            admission.STORYBOARD_BUILD.exit()
        lock.release()


@app.get("/img/scrub")
def proxy_image_scrub(
    request: Request,
    u: str = Query(..., description="Signed OF video URL (.mp4)"),
    i: int = Query(..., ge=0, lt=_STORYBOARD_FRAMES, description="Frame index 0..11"),
    dur: float | None = Query(None, gt=0, description="Video duration in seconds (from VaultMedia.duration). When supplied, the relay skips its own ffprobe."),
    sid: str | None = Query(None, description="Per-hover session id. The matching /img/scrub/cancel POST carries the same value; the server scopes cancellation to this session so a stale cancel from a previous hover can't abort a fresh build."),
):
    """Returns the i-th frame of the 12-frame storyboard for video `u`.
    First call builds; subsequent calls serve from disk."""
    from urllib.parse import urlparse as _urlparse
    parsed = _urlparse(u)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="bad scheme")
    host = (parsed.hostname or "").lower()
    if not any(host.endswith(s) for s in _ALLOWED_CDN_SUFFIXES):
        raise HTTPException(status_code=400, detail="host not allowed")

    h = _video_path_hash(u)
    ok = _ensure_storyboard_frame(request, u, h, i, hint_duration=dur, session_id=sid)
    if not ok:
        raise HTTPException(status_code=502, detail="storyboard build failed")
    frame_path = _storyboard_frame_path(h, i)
    if not frame_path.is_file():
        raise HTTPException(status_code=404, detail=f"frame {i} not extracted")

    # Bump the dir's mtime so the prune script's find -mtime treats this
    # as "last used now". Cheap (one syscall) — does NOT touch each frame
    # file, just the parent dir, which is all the prune script looks at.
    try:
        os.utime(_STORYBOARD_DIR / h, None)
    except OSError:
        pass

    global _storyboard_total_served
    _storyboard_total_served += 1
    return FileResponse(
        frame_path,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=604800, immutable",
            "X-Img-Hash": h,
        },
    )


@app.post("/img/scrub/cancel")
def cancel_storyboard_build(
    u: str = Query(..., description="Signed OF video URL whose in-flight storyboard build should be cancelled"),
    sid: str | None = Query(None, description="Per-hover session id from the matching /img/scrub request. Cancellation is scoped to this session — a missing or unknown sid is a no-op (intentional: stale cancels from a previous hover must not abort fresh builds for the same video)."),
):
    """Signal the in-flight download for hover session `sid` to abort,
    unless it's already past `_STORYBOARD_CANCEL_KEEP_THRESHOLD` (in
    which case we let it finish so the bytes aren't wasted). Idempotent —
    calling with a sid that has no in-flight build is a no-op.

    `u` is still validated for hygiene but isn't used to route the cancel
    anymore — that would re-introduce the hash-keyed race where a late
    POST from a stale hover aborted a fresh hover of the same video.

    Browser fires this on hover end (useEffect cleanup in VaultPicker).
    Fire-and-forget; the browser doesn't wait for or read the response."""
    from urllib.parse import urlparse as _urlparse
    parsed = _urlparse(u)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="bad scheme")
    host = (parsed.hostname or "").lower()
    if not any(host.endswith(s) for s in _ALLOWED_CDN_SUFFIXES):
        raise HTTPException(status_code=400, detail="host not allowed")
    if not sid:
        return {"ok": True, "ignored": "no-sid"}
    found = _storyboard_signal_cancel(sid)
    return {"ok": True, "found": found}


@app.get("/admin/coalesce/stats")
def admin_coalesce_stats() -> dict:
    """In-flight request coalescer activity (Stage B-2).

    `coalesced_hits` per namespace = waiters that joined an already-
    in-flight upstream call instead of dispatching a fresh one. A
    non-zero value means the coalescer is doing useful work in prod.
    `first_calls` = the leading caller for each namespace. Ratio
    `coalesced_hits / (first_calls + coalesced_hits)` is the hit rate."""
    return relay_coalesce.stats()


@app.get("/admin/storyboard/stats")
def admin_storyboard_stats() -> dict:
    """How the scrub-frame storyboard cache is doing."""
    try:
        n_videos = sum(1 for p in _STORYBOARD_DIR.iterdir() if p.is_dir()) if _STORYBOARD_DIR.exists() else 0
    except Exception:
        n_videos = 0
    return {
        "cached_videos": n_videos,
        "frames_per_video": _STORYBOARD_FRAMES,
        "total_built": _storyboard_total_built,
        "total_served": _storyboard_total_served,
        "build_failures": _storyboard_build_failures,
        "total_cancelled": _storyboard_total_cancelled,
        "total_cancel_ignored": _storyboard_total_cancel_ignored,
        "cancel_keep_threshold": _STORYBOARD_CANCEL_KEEP_THRESHOLD,
    }


# One TTL for every reader of the "list_chats" namespace (the inbox list AND
# the roster badge, which derives its counts from the same cached window —
# see _compute_roster_count_of). WS patching keeps it live; the TTL is the
# no-WS fallback.
_LIST_CHATS_TTL = 600.0
# How long past that TTL the inbox list still answers from RAM while ONE
# background read refreshes it — an expired window used to cost the opener a
# 3-call OF read (p50 ~2 s). The badge fold does not use it: it keeps its own
# window-age rule (_ROSTER_WINDOW_MAX_AGE_S, see _compute_roster_count_of).
_LIST_CHATS_SWR = 600.0

# When the badge's page-0 window was last fetched LIVE from OF, per account.
# The badge fold escalates to a live re-read when the window is older than
# _ROSTER_WINDOW_MAX_AGE_S — without this, counts folded from a near-expiry
# window and then cached for the roster TTL could serve ~900s-old state on a
# WS-dead account (the pre-unification badge re-read OF at least every 300s).
# Stamped by BOTH fetch sites (the inbox endpoint and the badge compute), so
# either one refreshing the window resets the clock for both.
_ROSTER_WINDOW_MAX_AGE_S = 300.0
_chats_window_fetched_at: dict[str, float] = {}


def _assemble_chats_page(
    client: OFClient,
    *,
    limit: int,
    offset: int,
    order: str,
    filter: str | None = None,
    list_id: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    """Blocking: the inbox's (and the roster badge's) page of chats — see
    chats_page.assemble_chats_page. A page OF's 429 cut short raises that 429
    (a short page cached as the whole window would hide the rest for the TTL);
    a dup-only read keeps OF's hasMore."""
    page = chats_page.assemble_chats_page(
        client, limit=limit, offset=offset, order=order, filter=filter, list_id=list_id, q=q,
    )
    if page.throttled is not None:
        raise page.throttled
    return {"list": page.rows, "hasMore": page.has_more}


@app.get("/api/of/v2/chats")
async def list_chats(
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    order: str = Query("recent"),
    filter: str | None = Query(None, description="OF chat filter: 'unread'|'pinned'|'priority'"),
    list_id: str | None = Query(None, description="Show only chats whose fan is in this custom list (folder)"),
    query: str | None = Query(None, description="Free-text search by fan name/username (OF param: ?query=)"),
    # Legacy alias from the first cut of the chat-search UI — the real OF param
    # is `query=`. We accept both so any deep-linked URLs from earlier builds
    # don't silently 400.
    search: str | None = Query(None, description="Alias for `query` (back-compat)"),
    refresh: bool = Query(False, alias="refresh"),
) -> dict[str, Any]:
    # BC1: 10min TTL relay_cache, patched in place by an inbound
    # api2_chat_message (event_transcoder._inbox_patcher); an expired window is
    # served stale while one background read refreshes it (_LIST_CHATS_SWR).
    # ?refresh=1 bypasses the cache but still warms it for the next caller.
    aid = _resolve_account_id(_request_ctx.get())
    q = query or search
    coalesce_key = ("list_chats", aid, limit, offset, order, filter, list_id, q)
    # The badge folds its counts from the plain recent page-0 window — when
    # THIS request happens to be that exact view, a live read here also resets
    # the badge's staleness clock (see _chats_window_fetched_at).
    is_badge_window = (
        limit == _ROSTER_SCAN_MAX and offset == 0 and order == "recent"
        and not filter and list_id is None and not q
    )
    async def _fetch():
        def _read():
            value = _assemble_chats_page(
                _get_client(), limit=limit, offset=offset, order=order,
                filter=filter, list_id=list_id, q=q,
            )
            if is_badge_window:
                _chats_window_fetched_at[aid] = _time_mod.monotonic()
            return value
        value = await relay_coalesce.coalesce(
            coalesce_key, lambda: asyncio.to_thread(_proxy, _read),
        )
        # Reconcile OF's authoritative read state + last-message direction into
        # the local `chats` mirror the roster badge aggregates — from a FRESH OF
        # read only (a miss, ?refresh=1, or the background stale-while-revalidate
        # refresh). A cached value is either a stale SWR window or one patched
        # from WS frames, so it is not OF's read state and must not overwrite the
        # mirror. Only the unfiltered/no-search/no-folder view (unbiased
        # snapshot); fire-and-forget so it never adds latency.
        if value and not filter and not q and list_id is None:
            chats = value.get("list") or value.get("chats") or []
            if chats:
                from messages import reconcile_chats_from_of
                asyncio.create_task(
                    reconcile_chats_from_of(aid, chats),
                    name=f"reconcile-chats-{aid}",
                )
        return value
    resp = await relay_cache.get_or_fetch(
        "list_chats", aid, (limit, offset, order, filter, list_id, q),
        ttl_seconds=_LIST_CHATS_TTL, fetcher=_fetch, bypass=refresh,
        stale_while_revalidate=_LIST_CHATS_SWR,
    )
    # Manual Refresh (?refresh=1) on the plain recent view just re-read the very
    # window the roster badge folds its counts from — drop the cached fold so
    # the next badge poll re-folds from these fresh rows (pure RAM, no OF read).
    # Without this, the one button users press when badge≠list leaves the badge
    # serving pre-refresh counts for up to its own TTL: the symptom survives its
    # own remedy.
    if refresh and offset == 0 and not filter and not q and list_id is None:
        relay_cache.invalidate("roster_count", aid)
    return await _annotate_chat_rows(aid, resp)


async def _annotate_chat_rows(aid: str, resp: dict[str, Any]) -> dict[str, Any]:
    """Stamp what we already store about each fan onto the /chats rows, so the
    Fan List paints it with no extra call (Infloww's chat-list smart signals):

      withUser.isRestricted  restricted on OF via our UI (the durable skip_list
                             registry). The inbox list runs skip_users=all, whose
                             thin withUser is just {id, _view}, so OF never sends
                             the flag here; the frontend chips need the stamp to
                             apply the SAME unread-count exclusion the badge fold
                             applies server-side.
      withUser.needsHuman    a custom is owed (`fans.customs_owed_at`): the bot
                             stopped selling and a human has to record and send it
      withUser.autoRenewOff  listed active at the last roster crawl
                             (`subscriber_snapshot`) with renew off and an expiry
                             still ahead; no crawl, a stale one, or a fan it
                             did not list stamps nothing

    Absent means unknown or no, never false. Serve-time and on a COPY: the
    cached window is shared with the badge fold and other requests, so a stale
    stamp must never be baked into it. Nothing to stamp returns `resp` itself."""
    if not resp:
        return resp
    rows_key = "list" if "list" in resp else ("chats" if "chats" in resp else None)
    if rows_key is None:
        return resp
    ids: set[int] = set()
    for ch in resp.get(rows_key) or []:
        try:
            ids.add(int((ch.get("withUser") or {}).get("id")))
        except (TypeError, ValueError):
            continue  # a Fansly snowflake or a malformed row: nothing stored for it
    if not ids:
        return resp
    from automations._common import load_of_restricted_ids
    from automations._customs import owed_fan_ids
    from automations.lifecycle_messages import renew_off_fan_ids
    restricted = await load_of_restricted_ids(aid) & ids
    owed = await owed_fan_ids(aid) & ids
    renew_off = await renew_off_fan_ids(aid, ids, datetime.utcnow())
    if not (restricted or owed or renew_off):
        return resp
    out_rows = []
    for ch in resp.get(rows_key) or []:
        wu = ch.get("withUser") or {}
        try:
            fid = int(wu.get("id"))
        except (TypeError, ValueError):
            fid = None
        stamp = {}
        if fid in restricted:
            stamp["isRestricted"] = True
        if fid in owed:
            stamp["needsHuman"] = True
        if fid in renew_off:
            stamp["autoRenewOff"] = True
        out_rows.append({**ch, "withUser": {**wu, **stamp}} if stamp else ch)
    return {**resp, rows_key: out_rows}


# Short on purpose. Folder edits are rare but they are OPERATOR edits — a
# rename or a pin that stays invisible for minutes reads as a failed write. 60s
# is long enough to collapse the inbox-open burst (chip strip + picker + the
# automation audience selector all mount together) and short enough that a
# missed invalidation self-heals before anyone reaches for the mouse again.
_CHAT_FOLDERS_TTL = 60.0


@app.get("/api/of/v2/chats/folders")
async def chat_folders(
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    refresh: bool = Query(False, alias="refresh"),
) -> dict[str, Any]:
    """Fan-lists the user has pinned (or can pin) to the chat sidebar.
    Mirrors OF's `/lists?filter=can_pin_chat&isChat=true&format=infinite`.

    BC8: 60s TTL relay_cache + coalesce — this was the last inbox-family
    endpoint with neither, so every inbox open spent a live OF round-trip on a
    list that changes maybe once a week. Invalidated by every list write below
    (`_invalidate_chat_folders`); `?refresh=1` bypasses.

    Now `async def`: the cache and the coalescer are both awaitables, so the
    blocking OF read moves into `asyncio.to_thread` exactly as `list_chats`
    does. `to_thread` copies the context, so `_get_client()` still resolves the
    same account inside the worker."""
    aid = _resolve_account_id(_request_ctx.get())
    coalesce_key = ("chat_folders", aid, limit, offset)

    async def _fetch():
        return await relay_coalesce.coalesce(coalesce_key, lambda: asyncio.to_thread(
            _proxy, lambda: _get_client().chat_folders(limit=limit, offset=offset),
        ))

    return await relay_cache.get_or_fetch(
        "chat_folders", aid, (limit, offset),
        ttl_seconds=_CHAT_FOLDERS_TTL, fetcher=_fetch, bypass=refresh,
    )


def _invalidate_chat_folders() -> None:
    """Drop this account's cached folder list after a write that changed it.

    Sync (relay_cache.invalidate does no I/O) so the sync list-write routes can
    call it inline. Never raises: an invalidation miss costs one stale minute,
    but a raise here would fail a write that already succeeded upstream."""
    try:
        relay_cache.invalidate("chat_folders", _resolve_account_id(_request_ctx.get()))
    except Exception:  # noqa: BLE001
        log.debug("chat_folders invalidation skipped", exc_info=True)


class _PinChatBody(BaseModel):
    pinned: bool


@app.patch("/api/of/v2/lists/{list_id}/pin-chat")
def pin_list_to_chat(list_id: int, body: _PinChatBody = Body(...)) -> dict[str, Any]:
    """Pin or unpin a fan list as a chat-sidebar folder.
    Maps to PATCH /lists/{id} with `{"isPinnedToChat": <bool>}`."""
    out = _proxy(lambda: _get_client().set_list_pinned_to_chat(list_id, body.pinned))
    # `isPinnedToChat` IS the field the chip strip filters on — without this the
    # pin the operator just clicked would not appear for up to a full TTL.
    _invalidate_chat_folders()
    return out


@app.get("/api/of/v2/chats/{chat_id}/messages")
async def get_messages(
    chat_id: int,
    limit: int = Query(10, ge=1, le=100),
    order: str = Query("desc"),
    before_id: int | None = Query(None, description="Paginate older: pass last message id"),
    refresh: bool = Query(False, alias="refresh"),
) -> dict[str, Any]:
    # BC2: cache ONLY paginated history (before_id non-None). Head page
    # (before_id=None) is where new messages land — we have no
    # per-message WS invalidator, so head MUST go through to OF every
    # time. Coalescing still applies on both paths.
    aid = _resolve_account_id(_request_ctx.get())
    coalesce_key = ("get_messages", aid, chat_id, before_id, limit, order)
    async def _fetch():
        return await relay_coalesce.coalesce(coalesce_key, lambda: asyncio.to_thread(
            _proxy, lambda: _get_client().get_messages(
                chat_id, limit=limit, order=order, before_id=before_id,
            ),
        ))
    if before_id is None:
        # Head page: skip cache entirely. New inbound DMs arrive via the
        # WS pump + SSE; caching the head would mask them for ~TTL.
        payload = await _fetch()
    else:
        # Paginated tail: mostly immutable, but PPV lock/unlock state can flip
        # on an old message when a fan pays — so cap the cache at 5min (not
        # 10) to bound how long a just-paid PPV lingers as "locked". Still
        # plenty to coalesce a scroll-burst; `bypass=refresh` forces fresh.
        payload = await relay_cache.get_or_fetch(
            "get_messages_tail", aid, (chat_id, before_id, limit),
            ttl_seconds=300.0, fetcher=_fetch, bypass=refresh,
        )
    # Media render-stability (18_chat_render_stability §1.1): surface
    # width/height at each media item's top level so the client sizes the
    # skeleton without parsing OF's nested files, and persist those dims into
    # message_media (the primary dims source). Best-effort — a media hiccup
    # must never break loading the chat. Idempotent, so a cache hit re-running
    # it is harmless.
    #
    # The two halves are deliberately split. Stamping is what the RESPONSE
    # needs, so it stays awaited. Persisting is a write transaction on the one
    # shared SQLite writer, and nothing in this response reads it back — it
    # only feeds a LATER request — so it rides a fire-and-forget task, the same
    # shape `reconcile_chats_from_of` uses in `list_chats` above. Paying for it
    # inline meant every chat open and every 30s/2min poll queued behind the
    # writer. Both halves are handed the SAME list object: stamp mutates it,
    # persist reads it.
    if isinstance(payload, dict) and aid:
        of_rows = payload.get("list") or []
        try:
            await stamp_rest_media_dims(str(aid), int(chat_id), of_rows)
        except Exception:  # noqa: BLE001
            log.debug("stamp_rest_media_dims failed for chat %s", chat_id, exc_info=True)
        if of_rows:
            # `persist_rest_media_dims` swallows its own exceptions — in a bare
            # create_task an escaping error would only ever surface as an
            # unretrieved-task warning.
            asyncio.create_task(
                persist_rest_media_dims(str(aid), int(chat_id), of_rows),
                name=f"media-dims-{aid}-{chat_id}",
            )
    return payload


@app.get("/api/of/v2/chats/{chat_id}/pinned")
async def get_pinned(chat_id: int) -> dict[str, Any]:
    """The chat's pinned messages — ALL of them, straight from OF.

    The rail used to derive its pins by filtering the LOADED BACKLOG for
    `isPinned` (ChatSurface), so a pin older than the first page was invisible
    and a thread holding two rendered "Pinned · 1". Verified live 2026-07-27: a
    real thread's only pin sat outside the head page and the rail showed none.

    Static path, and it must stay declared BEFORE `/chats/{chat_id}/messages/...`
    is irrelevant here (different segment) — but it DOES have to come before any
    future `/chats/{chat_id}/{something}` catch-all, same trap as mark-as-read.

    Cheap enough to call per open chat: one OF request, no pagination (see
    of_client.get_pinned_messages — `hasMore` lies on this filter)."""
    rows = await asyncio.to_thread(
        _proxy, lambda: _get_client().get_pinned_messages(chat_id))
    return {"list": rows}


# ── Users ──────────────────────────────────────────────────────
# Order matters: the static /users/list route must be declared BEFORE the
# dynamic /users/{...} route, otherwise FastAPI would match "list" as a
# username and never reach the batch endpoint.

@app.get("/api/of/v2/users/list")
async def list_users(
    ids: list[int] = Query(..., description="One or more user ids: ?ids=1&ids=2"),
    view: str = Query("m", pattern="^[mx]$",
                      description="'m' = chat-list view (default), 'x' = extended"),
) -> dict[str, Any]:
    """Batch-fetch up to ~50 user profiles in one request. Returns OF's native
    shape: a dict keyed by user-id string, e.g. {"117183": {...}}.

    Quirk: when OF can't resolve ANY of the requested ids (deleted accounts,
    typos, etc.) it returns `[]` instead of `{}`. Normalize to dict so the
    response validator stays happy and callers don't have to type-guard.

    Augments each entry with `customNickname` from our local Fan table when
    one is set. Read-only join — never creates Fan stub rows. Lets the chat
    list / group panes / popouts all surface team-set nicknames without a
    separate fetch.

    The OF httpx call is blocking; we run it via `asyncio.to_thread` so the
    event loop stays responsive while the upstream request is in flight.
    Direct `_proxy(...)` from this `async def` would freeze SSE, webhooks,
    and concurrent requests for the duration of the upstream call."""
    aid = _resolve_account_id(_request_ctx.get())
    # IDs must be sorted in the key — two requests with [1,2,3] vs [3,2,1]
    # should coalesce. The OF response is keyed by user-id string anyway,
    # so per-waiter slicing is order-insensitive.
    key = ("list_users", aid, view, tuple(sorted(ids)))

    async def _fetch():
        resp = await asyncio.to_thread(
            _proxy, lambda: _get_client().list_users(ids, view=view)
        )
        if isinstance(resp, list):
            resp = {}
        # Overlay runs INSIDE the fetcher so coalesced waiters see the
        # same already-stitched dict (Stage B-2 bug guard #3 — moves
        # mutation inside the one shared execution).
        try:
            await _sync_of_user_overlay(aid, resp)
        except Exception:
            log.exception("custom_nickname stitch failed for /users/list")
        return resp

    return await relay_coalesce.coalesce(key, _fetch)


class _OverlayLocal(NamedTuple):
    """The local Fan columns `_sync_of_user_overlay` reconciles."""
    nick: str | None
    notes: str | None


async def _sync_of_user_overlay(
    account_id: str, users: dict[str, Any]
) -> None:
    """Reconcile OF's per-fan `displayName`/`notice` with our local mirror
    (`Fan.custom_nickname` / `Fan.notes`), in both directions:

      • OF → local: whenever a chatter edits the values directly on
        onlyfans.com, the next OF refetch flips our local row to match.
        OF wins; this is the read-back leg of the bidirectional sync.

      • local → response: stitches the (now-fresh) `customNickname` into
        each entry of the dict so legacy consumers reading that field
        get the same value the chat-list rail/group pane already pick.

    `users` is mutated in place. Empty string from OF means "cleared",
    normalised to NULL locally. Missing local rows are skipped here —
    /users/list already auto-creates fan stubs via the WS pump, and we
    don't want this read path to create rows for arbitrary id lookups."""
    if not users:
        return
    fan_ids: list[int] = []
    for key in users.keys():
        try:
            fan_ids.append(int(key))
        except (TypeError, ValueError):
            continue
    if not fan_ids:
        return

    from db.engine import get_session
    from db.models import Fan
    from sqlalchemy import select as _select, update as _update

    async with get_session() as s:
        rows = (await s.execute(
            _select(
                Fan.fan_id, Fan.custom_nickname, Fan.notes,
            )
            .where(Fan.account_id == account_id, Fan.fan_id.in_(fan_ids))
        )).all()
        local_by_id: dict[int, _OverlayLocal] = {
            int(r.fan_id): _OverlayLocal(
                nick=r.custom_nickname,
                notes=r.notes,
            )
            for r in rows
        }

        dirty = False
        for key, entry in users.items():
            if not isinstance(entry, dict):
                continue
            try:
                fid = int(key)
            except (TypeError, ValueError):
                continue
            of_display = entry.get("displayName")
            of_notice = entry.get("notice")
            local = local_by_id.get(fid)
            if local is None:
                continue
            norm_display = of_display if of_display else None
            norm_notice = of_notice if of_notice else None
            patch: dict[str, Any] = {}
            if of_display is not None and norm_display != local.nick:
                patch["custom_nickname"] = norm_display
            if of_notice is not None and norm_notice != local.notes:
                patch["notes"] = norm_notice
            if patch:
                patch["updated_at"] = datetime.utcnow()
                await s.execute(
                    _update(Fan)
                    .where(Fan.account_id == account_id, Fan.fan_id == fid)
                    .values(**patch)
                )
                dirty = True
                local_by_id[fid] = local._replace(
                    nick=patch.get("custom_nickname", local.nick),
                    notes=patch.get("notes", local.notes),
                )
        if dirty:
            await s.commit()

        for fid, local in local_by_id.items():
            if not local.nick:
                continue
            entry = users.get(str(fid))
            if isinstance(entry, dict):
                entry["customNickname"] = local.nick


# NOTE: /users/{user_id_or_username} is declared at the very end of the user-family
# routes (see "Catch-all single user lookup" further down) so static routes like
# /users/list, /users/search, /users/{id}/posts can match first.


# ── Send a message ─────────────────────────────────────────────

class SendMessageBody(BaseModel):
    text: str = Field(..., description="Message body. Plain text or HTML.")
    locked_text: bool = Field(False, description="Lock the text behind the PPV price.")
    price: float = Field(0, ge=0, description="PPV price; 0 = free message.")
    # Either: ints (existing vault ids) or dicts (fresh-upload claim objects
    # like {processId, host, name, extra}). OF accepts both in mediaFiles.
    media_files: list[int | dict] = Field(default_factory=list, description="Vault media ids OR fresh-upload claim objects {processId,host,name,extra}")
    # Vault media ids that ride along UNLOCKED (free preview) when `price > 0`.
    # Must be a subset of `media_files`'s numeric ids; fresh-claim dicts can't
    # appear here because they have no id until OF resolves them.
    previews: list[int] = Field(default_factory=list, description="Subset of media_files (by vault id) sent unlocked when price > 0")
    is_forward: bool = False
    reply_to_message_id: int | None = Field(
        None,
        description="OF native quote-reply target id — receiver renders the quoted message above this one.",
    )
    # Numeric OF user ids of creators to tag in this message. Picker UI
    # populates these from GET /api/of/v2/self/tagged-friend-users; OF
    # rejects ids that aren't on the caller's tagged-friend list with 400.
    tagged_users: list[int] = Field(
        default_factory=list,
        description="OF user ids of creators to tag (sent as `userTags`).",
    )
    # Giphy GIF id (e.g. "0ndspgUFbm9iQtyX2Q"). Forwarded as top-level
    # `giphyId` in the OF body — sibling of `mediaFiles`, not nested in it.
    # OF accepts one GIF per send and echoes it back on the response.
    giphy_id: str | None = Field(
        None,
        description="Giphy GIF id (string). Sent as top-level `giphyId`; one per message.",
    )
    # OF's other two release-form tag fields on a chat message (OF web's
    # mapper: a guest is `rfGuest`, a release form's link or document is
    # `rfPartner`; a creator is `rfTag`, which `tagged_users` fills).
    rf_guest: list[int] = Field(default_factory=list, description="Release-form guest ids (sent as `rfGuest`).")
    rf_partner: list[int] = Field(default_factory=list, description="Release-form link / document ids (sent as `rfPartner`).")


# Mass-message route MUST come before /chats/{chat_id}/messages below, otherwise
# FastAPI matches `chat_id="messages"` and 422s on int validation.
#
# `_MassMessageBody` MUST be defined here, ABOVE the route that annotates it.
# With `from __future__ import annotations` the body annotation is a string, so
# FastAPI/Pydantic build a deferred TypeAdapter from a ForwardRef at decoration
# time — if the class is defined later in the file nothing ever resolves it, and
# `/openapi.json` blows up with "is not fully defined" (PydanticUserError).
class _MassMessageBody(BaseModel):
    text: str
    user_lists: list[int] = Field(default_factory=list)
    included_users: list[int] = Field(default_factory=list)
    excluded_users: list[int] = Field(default_factory=list)
    price: float = Field(0, ge=0)
    locked_text: bool = False
    # Mirror SendMessageBody: int = vault id, dict = fresh-upload claim
    # (the same payload shape /upload returns in `send_with`).
    media_files: list[int | dict] = Field(default_factory=list)
    # Plumbed end-to-end in Work Unit O (Phase 6). Accepted here so a
    # forward-compat client can already send it without 422; the value is
    # currently ignored downstream because `of_client.send_mass_message`
    # doesn't yet thread it to OF.
    previews: list[int] = Field(default_factory=list)
    scheduled_date: str | None = None


async def _open_mass_run(
    request: Request,
    *,
    user_lists: list,
    included_users: list[int],
    excluded_users: list[int],
    excluded_user_lists: list | None = None,
    funnel_id: int | None = None,
) -> tuple[str, int | None, int | None]:
    """Resolve account + X-Employee-Id and mint a `mass_runs` row so every
    per-fan outbound row downstream can reference it. Returns
    `(account_id, employee_id, mass_run_id)` — `mass_run_id` may be None if
    the mint failed (the broadcast still proceeds; attribution degrades to
    NULL, same fallback as the single-fan path)."""
    account_id = _resolve_account_id(request)
    # Resolves header (owner) OR chatter mirror Employee under the
    # account's owner. Chatters never carry X-Employee-Id and the header
    # is the only way the old path knew "who sent this"; without this
    # branch every chatter send showed up as Automation in the per-
    # employee stats table.
    from employees import resolve_outbound_employee_id
    employee_id = await resolve_outbound_employee_id(request, account_id)

    audience_filter = json.dumps({
        "user_lists": user_lists,
        "included_users": included_users,
        "excluded_users": excluded_users,
        # The audience actually SENT is wider than the three keys above: OF has
        # no per-user exclusion field for a list audience, so the excluded ids
        # ride in the Auto_Exclude list attached here. Forensics only — who
        # RECEIVED the blast is recorded on `recipients_json` at close.
        "excluded_user_lists": list(excluded_user_lists or []),
    })
    mass_run_id: int | None = None
    try:
        from db.engine import get_session
        from db.models import MassRun
        async with get_session() as s:
            run = MassRun(
                account_id=str(account_id),
                funnel_id=int(funnel_id) if funnel_id is not None else None,
                started_by_employee_id=employee_id,
                audience_filter=audience_filter,
                recipient_count=len(included_users),
                status="running",
            )
            s.add(run)
            await s.flush()
            mass_run_id = int(run.id)
    except Exception:
        log.exception("mass_runs mint failed (account=%s)", account_id)
    return account_id, employee_id, mass_run_id


async def _close_mass_run(
    *,
    account_id: str,
    employee_id: int | None,
    mass_run_id: int | None,
    text: str,
    price: float,
    result: Any,
    recipient_ids: list[int] | None = None,
    audience: dict | None = None,
    scheduled: bool = False,
) -> None:
    """After OF returns, persist a `messages` row per recipient of the
    broadcast. Two sources, handled in order:

      1. **Echoed ids.** OF's `/messages/queue` shape varies — some
         installations echo `{messages: [{userId, id, ...}]}`. For each
         echoed pair we write the REAL row (`write_outbound_attribution`) and
         drop any optimistic placeholder for that recipient.
      2. **Optimistic rows.** For the explicit recipients OF did NOT echo
         (`recipient_ids`, i.e. the `userIds` audience), we write an optimistic
         placeholder row at send time — direction='out', `mass_run_id` set,
         a synthetic `message_id` + `temp_id` — so the broadcast shows up in
         the chat cache immediately instead of never. The WS pump skips
         outbound events, so without this the row would otherwise never land.

    List-based audiences (`userLists`) aren't expanded here, so their members
    aren't in `recipient_ids` and NO per-fan row is written for them. What they
    get instead is step 4: the run itself records the body, OF's send stamp and —
    from `audience`, by paging OF's own rosters — the recipient set, so
    the chat engines' history read can materialize that row at READ time for
    the fans who reply (plans/blast-splice; this is the "future WS-pump reconciler" the
    previous version of this docstring was waiting for, arrived by another route:
    the pump never echoes outbound blasts at all).

    `audience` is the request body's own audience block (`user_lists`,
    `excluded_users`, `excluded_user_lists`, `filters`, `online_only`); omit it
    and the recipient set is simply not recorded. `scheduled=True` says OF has
    NOT sent this yet — the run gets no body and no stamp, because there is
    nothing on anyone's thread to splice."""
    if mass_run_id is None:
        return
    from attribution import (
        reconcile_mass_placeholder,
        write_mass_optimistic_rows,
        write_outbound_attribution,
    )
    from event_transcoder import _parse_iso, _to_cents

    created_at = (
        (_parse_iso(result.get("createdAt")) if isinstance(result, dict) else None)
        or datetime.utcnow()
    )
    price_cents = _to_cents(price)

    # ── 1) Real rows for any per-fan ids OF echoed in the response ──────
    msgs = result.get("messages") if isinstance(result, dict) else None
    per_fan_ids: list[tuple[int, int]] = []
    if isinstance(msgs, list):
        for m in msgs:
            if not isinstance(m, dict):
                continue
            fid_raw = m.get("userId") or m.get("toUserId") or m.get("recipientId")
            mid_raw = m.get("id") or m.get("messageId")
            try:
                if fid_raw is not None and mid_raw is not None:
                    per_fan_ids.append((int(fid_raw), int(mid_raw)))
            except (TypeError, ValueError):
                continue

    echoed_fans: set[int] = set()
    for fan_id, msg_id in per_fan_ids:
        echoed_fans.add(fan_id)
        try:
            await write_outbound_attribution(
                account_id=account_id,
                fan_id=fan_id,
                message_id=msg_id,
                sent_by_employee_id=employee_id,
                body=text or "",
                price_cents=price_cents,
                created_at=created_at,
                mass_run_id=mass_run_id,
            )
            # If an optimistic placeholder for this recipient already landed
            # (e.g. a retry, or a future async reconciler), drop it so the
            # real row is the only one left.
            await reconcile_mass_placeholder(
                account_id=account_id, fan_id=fan_id, mass_run_id=mass_run_id,
            )
        except Exception:
            log.exception(
                "mass attribution write failed (account=%s run=%s fan=%s)",
                account_id, mass_run_id, fan_id,
            )

    # ── 2) Optimistic placeholders for the explicit recipients not echoed ─
    pending: list[int] = []
    for raw in (recipient_ids or []):
        try:
            fid = int(raw)
        except (TypeError, ValueError):
            continue
        if fid not in echoed_fans:
            pending.append(fid)
    if pending:
        await write_mass_optimistic_rows(
            account_id=account_id,
            fan_ids=pending,
            mass_run_id=mass_run_id,
            sent_by_employee_id=employee_id,
            body=text or "",
            price_cents=price_cents,
            created_at=created_at,
        )

    # ── 3) Close the run. reply_mass_funnel only anchors on status='ok'
    #      runs, and the Mass Messages tab joins the broadcast cache on
    #      queue_id — mirror send_mass_message's close step.
    queue_id = result.get("id") if isinstance(result, dict) else None
    try:
        from db.engine import get_session
        from db.models import MassRun
        async with get_session() as s:
            mr = await s.get(MassRun, mass_run_id)
            if mr is not None:
                mr.status = "ok"
                mr.completed_at = datetime.utcnow()
                if queue_id is not None:
                    mr.queue_id = int(queue_id)
                if not scheduled:
                    # The splice record — mirror send_mass_message's close step.
                    # A SCHEDULED send leaves both NULL: it has not gone out, so
                    # there is no line on anyone's thread yet and a `sent_at` in
                    # the future would put one there.
                    mr.body = text or ""
                    mr.sent_at = created_at
    except Exception:
        log.exception("mass run close failed (account=%s run=%s)", account_id, mass_run_id)

    # ── 4) …and WHO OF sent it to, off OF's rosters (plans/blast-splice A.2).
    # BACKGROUNDED: the crawl is up to ~17 pages on the largest account and a
    # human is watching this response. It fails closed on its own (None →
    # `recipients_json` stays NULL → the run is never spliced), so there is
    # nothing for the request to wait on and nothing it could do about a failure.
    if audience is not None and not scheduled:
        async def _record_recipients() -> None:
            try:
                from attribution import stamp_mass_recipients
                from audiences import resolve_recipients_blocking
                # `_load_client(account_id)`, never `_get_client()`: this runs
                # detached from the request, so the middleware contextvar the
                # bare form reads is gone and it would fall back to the ACTIVE
                # account — another creator's roster, on the wrong run.
                recorded = await asyncio.to_thread(
                    resolve_recipients_blocking, _load_client(account_id),
                    user_lists=audience.get("user_lists") or [],
                    included_users=recipient_ids or [],
                    excluded_users=audience.get("excluded_users") or [],
                    excluded_user_lists=audience.get("excluded_user_lists") or [],
                    filters=audience.get("filters"),
                    online_only=bool(audience.get("online_only")),
                )
                await stamp_mass_recipients(mass_run_id, recorded)
            except Exception:
                log.warning("mass recipient record failed (account=%s run=%s) — "
                            "the blast is sent, it just will not be spliced",
                            account_id, mass_run_id, exc_info=True)
        _spawn_bg(_record_recipients(), f"mass-recipients-{mass_run_id}")


# ── re-sale guard ─────────────────────────────────────────────────────
# ppv_send checks ownership before it sells; the extension/UI
# chat send did not, and it is where the real damage happened: 8 separately-paid
# messages across 4 fans re-charged $456 for content already owned, one whale
# paying 4× for the same two clips at a climbing price. Charging twice for one
# file is a refund + chargeback, and chargebacks are what kill an OF account.
#
# The rules live in `ownership.resale_verdict` (the one home for owned-media
# semantics); only the operator-facing wording lives here. Keyed by reason so a
# third rule is a new entry, not a new branch.
_RESALE_MESSAGES = {
    ownership.RESALE_OWNED_VIDEO: (
        "This fan already paid for video in this message. "
        "Remove it, or send at price 0."
    ),
    ownership.RESALE_MOSTLY_OWNED_PHOTOS: (
        "{owned} of {total} photos here are ones this fan already paid for. "
        "A priced set needs at least half new photos — swap some in, or send "
        "at price 0."
    ),
}


async def _reject_if_resale(account_id: str, fan_id: int, body: SendMessageBody) -> None:
    """Raise 409 if this PRICED send re-charges the fan for content he holds.

    Runs BEFORE the OF call — the sibling `/admin/vault/sends` recorder fires
    only AFTER a send lands, so a guard there would log the mistake, not prevent
    it. Priced sends only: a FREE re-send (a fan who lost the file) is not a
    re-sale and is never touched."""
    if body.price <= 0:
        return
    vault_ids = [m for m in body.media_files if isinstance(m, int) and m > 0]
    if not vault_ids:
        return
    try:
        verdict = await ownership.resale_verdict(
            account_id, fan_id, vault_ids, body.previews)
    except Exception:
        # A broken guard read must not take the chat offline. Logged, allowed.
        log.exception("re-sale guard lookup failed (fan=%s) — allowing send", fan_id)
        return
    if not verdict.blocked:
        return
    log.warning("re-sale blocked account=%s fan=%s price=%s reason=%s videos=%s "
                "photos=%d/%d", account_id, fan_id, body.price, verdict.reason,
                verdict.owned_videos, len(verdict.owned_photos), verdict.photos_total)
    raise HTTPException(
        status_code=409,
        detail={
            "error": verdict.reason,
            "message": _RESALE_MESSAGES[verdict.reason].format(
                owned=len(verdict.owned_photos), total=verdict.photos_total),
            "owned_media": verdict.owned_media,
        },
    )


@app.post("/api/of/v2/chats/{chat_id}/messages")
async def send_message(
    request: Request,
    chat_id: int,
    body: SendMessageBody = Body(...),
) -> dict[str, Any]:
    """Send a message to a fan. `chat_id` is the fan's user id (same id used
    everywhere else in this API).

    After OF returns 200, immediately writes a `messages` row stamped with
    `sent_by_employee_id` from the `X-Employee-Id` header (or the system
    Automation employee when the header is absent). The transcoder skips
    outbound chat_message events on purpose; this is the single producer
    of outbound rows."""
    # Extract context BEFORE _proxy — its lambda has no request scope.
    try:
        account_id = _resolve_account_id(request)
    except HTTPException:
        # _resolve_account_id already shaped the error; let it propagate.
        raise
    # Same chatter-aware resolution as the mass-message path above. For
    # owner sessions this reads X-Employee-Id; for chatter sessions it
    # looks up (chatter, account_owner) → Employee, materialising the
    # mirror row on first hit so the message bubble's "Sent by" label
    # reads the chatter's display name instead of "Automation."
    from employees import resolve_outbound_employee_id
    employee_id = await resolve_outbound_employee_id(request, account_id)

    await _reject_if_resale(account_id, int(chat_id), body)

    # Bridge sync _proxy from this async handler — copied from the
    # /users/list pattern at server.py around line 2388.
    result = await asyncio.to_thread(
        _proxy,
        lambda: _get_client().send_message(
            chat_id,
            text=body.text,
            locked_text=body.locked_text,
            price=body.price,
            media_files=body.media_files,
            previews=body.previews,
            is_forward=body.is_forward,
            reply_to_message_id=body.reply_to_message_id,
            tagged_users=body.tagged_users,
            giphy_id=body.giphy_id,
            rf_guest=body.rf_guest,
            rf_partner=body.rf_partner,
            # A human is composing this one and has the tag picker right there,
            # so their choice stands as made — the co-performer auto-tag
            # (media_cotag) covers the automated senders, which have no operator
            # to make it. Flip to True to auto-tag the composer too.
            auto_tag=False,
        ),
    )

    await _record_fan_send(account_id, int(chat_id), result,
                           employee_id=employee_id, price=body.price)
    return result


async def _record_fan_send(account_id: str, fan_id: int, result: Any, *,
                           employee_id: int | None, price: float) -> None:
    """Everything a fan DM owes the relay once OnlyFans has said 200: the
    outbound `messages` row, the `chat_responded` announcement, the media pin,
    the chat-list cache bust.

    The transcoder skips outbound chat_message events on purpose, so the
    sender is the single producer of outbound rows — every send that reaches a
    fan has to come through here (the chat route, and the vault import's send
    to its linked fan). Never raises: the send already happened."""
    # Best-effort attribution write. Never raise — the OF send already
    # succeeded and the frontend reconcile depends on the response.
    try:
        from attribution import write_outbound_attribution
        from event_transcoder import _parse_iso, _to_cents
        msg_id = result.get("id") if isinstance(result, dict) else None
        if msg_id:
            await write_outbound_attribution(
                account_id=account_id,
                fan_id=int(fan_id),
                message_id=int(msg_id),
                sent_by_employee_id=employee_id,
                body=str(result.get("text") or ""),
                price_cents=_to_cents(price),
                created_at=_parse_iso(result.get("createdAt")) or datetime.utcnow(),
            )
    except Exception:
        log.exception("attribution write failed (chat_id=%s)", fan_id)

    await publish_chat_responded(account_id=account_id, fan_id=int(fan_id), employee_id=employee_id)

    # Wave 2.1 — pin the just-sent image bytes in the on-disk /img cache so
    # the bubble keeps serving a local copy after OF reconciles, instead of
    # racing OF's cold CDN edge. Fire-and-forget; never blocks this response.
    try:
        _pin_sent_media(account_id, result)
    except Exception:
        log.debug("pin sent media dispatch failed (chat_id=%s)", fan_id, exc_info=True)

    # The reply moved the chat window (lastMessage direction → owe-reply/unread
    # drop, preview text). The WS echo of our own send also busts these, but it
    # can lag the response or be missed outright (pump down) — bust here so the
    # sender's own next list/badge read reflects the reply immediately.
    relay_cache.invalidate("list_chats", account_id)
    relay_cache.invalidate("roster_count", account_id)


# ── Dashboard / init ───────────────────────────────────────────


@app.get("/api/of/v2/labels")
async def of_labels() -> dict[str, Any]:
    """Post labels (New post's ADD LABELS)."""
    aid = _resolve_account_id(_request_ctx.get())
    key = ("labels", aid)
    async def _fetch():
        return await asyncio.to_thread(_proxy, lambda: _get_client().labels())
    return await relay_coalesce.coalesce(key, _fetch)

@app.get("/api/of/v2/users/notifications")
async def of_notifications(
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    type: str | None = Query(None, description="'all','tips','subscribes','comments','mentions'"),
    related_user: int | None = Query(None, description="One user's notifications (OF web's View user's comments: type=commented)."),
    refresh: bool = Query(False, alias="refresh"),
):
    """Notifications feed. Captured-correct path is /users/notifications (not /notifications).

    BC7: 30s TTL relay_cache + coalesce — the last member of this family to
    get either, and the most fanned-out of them: MoneyRail asks for 2 money
    types x N accounts on every hard load and NotificationBell repeats the
    same keys, so one page load was N x 2 live OF round-trips at ~630ms each.

    A money feed is only safe to cache with the other half of the deal:
    `relay_cache.invalidate_money_feeds` is called from every money-event path
    and owns the list of them. The TTL is held at the browser's own 30s
    `staleTime` regardless, so even an unmodelled money path can be at most
    30s stale — the bound the badge next door already ships with.

    Keyed on (limit, offset, type) — the two money types and the paging
    offsets are different feeds and must not share an entry. Account-wide,
    not per-employee (OF serves this off the session, and nothing on this
    path reads X-Employee-Id), so it satisfies relay_coalesce's rules.
    """
    aid = _resolve_account_id(_request_ctx.get())
    # `type or ""` collapses absent and empty to ONE entry, matching
    # of_client.notifications, which forwards `type` only when truthy.
    extras = (limit, offset, type or "") + ((related_user,) if related_user is not None else ())
    coalesce_key = ("notifications", aid) + extras
    async def _fetch():
        return await relay_coalesce.coalesce(coalesce_key, lambda: asyncio.to_thread(
            _proxy, lambda: _get_client().notifications(
                limit=limit, offset=offset, type=type,
                **({"related_user": related_user} if related_user is not None else {})),
        ))
    return await relay_cache.get_or_fetch(
        "notifications", aid, extras,
        ttl_seconds=30.0, fetcher=_fetch, bypass=refresh,
    )

@app.get("/api/of/v2/users/notifications/count")
async def of_notifications_count(
    refresh: bool = Query(False, alias="refresh"),
):
    """Per-category badge counts (all, subscribed, purchases, tip).

    BC4: 30s TTL relay_cache (kept short — this is a badge the user is
    staring at). Invalidated by the same event set as BC3.
    """
    aid = _resolve_account_id(_request_ctx.get())
    coalesce_key = ("notifications_count", aid)
    async def _fetch():
        return await relay_coalesce.coalesce(coalesce_key, lambda: asyncio.to_thread(
            _proxy, lambda: _get_client().notifications_count(),
        ))
    return await relay_cache.get_or_fetch(
        "notifications_count", aid, (),
        ttl_seconds=30.0, fetcher=_fetch, bypass=refresh,
    )


@app.get("/api/of/v2/release-forms/mentions")
def of_release_form_mentions(limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0)):
    """Notifications' Tags tab: posts the creator is tagged in, notification-shaped."""
    return _proxy(lambda: _get_client().release_form_mentions(limit=limit, offset=offset))

@app.get("/api/of/v2/users/me/settings")
async def of_my_settings(
    refresh: bool = Query(False, alias="refresh"),
):
    """Full settings dump (account, payments, streaming keys, etc.).

    BC5: 5min TTL relay_cache. Invalidated explicitly when our own write
    endpoints touch settings (PATCH /users/me, PATCH
    /users/me/reply-on-subscribe) — those handlers call
    `relay_cache.invalidate("my_settings", aid)` after a successful upstream
    write.

    NOT WS-event-driven: a chatter editing settings on onlyfans.com (outside
    this app) won't trigger invalidation. **5 minutes is the upper bound on
    staleness** in that case; callers can force a fresh fetch via ?refresh=1.
    """
    aid = _resolve_account_id(_request_ctx.get())
    coalesce_key = ("my_settings", aid)
    async def _fetch():
        return await relay_coalesce.coalesce(coalesce_key, lambda: asyncio.to_thread(
            _proxy, lambda: _get_client().my_settings(),
        ))
    return await relay_cache.get_or_fetch(
        "my_settings", aid, (),
        ttl_seconds=300.0, fetcher=_fetch, bypass=refresh,
    )


@app.post("/api/of/v2/streams")
def of_schedule_stream(body: dict = Body(...)):
    """POST /streams — schedule a live stream. Body passes through as OF's
    own create form sends it: {description, scheduledDate, isShowTips}
    (scheduledDate local ISO with offset). Response carries the stream `.id`."""
    return _proxy(lambda: _get_client().schedule_stream(**body))

@app.get("/api/of/v2/streams/feed")
def of_streams_feed():
    """Live and scheduled streams for Home's story strip (OF's streams/feed)."""
    return _proxy(lambda: _get_client().streams_feed())

@app.get("/api/of/v2/users/{user_id}/streams")
def of_user_streams(user_id: str, limit: int = Query(8, ge=1, le=50), offset: int = Query(0, ge=0)):
    """A creator's past live streams (Streaming dashboard). `user_id` numeric or 'me'."""
    return _proxy(lambda: _get_client().user_streams(user_id, limit=limit, offset=offset))

class _PayoutRequestBody(BaseModel):
    withdrawal_amount: float = Field(..., gt=0)

class _WithdrawalPeriodBody(BaseModel):
    withdrawalPeriod: str = Field(..., min_length=1, max_length=32)

@app.post("/api/of/v2/payouts/requests")
def of_request_payout(body: _PayoutRequestBody):
    """OF's Statements "Request withdrawal": POST /payouts/requests
    {withdrawal_amount}. OF's own refusals (below the minimum, not enough funds)
    come back as the usual structured 502 with OF's message in upstream_body."""
    return _proxy(lambda: _get_client().request_payout(body.withdrawal_amount))

@app.patch("/api/of/v2/payouts/requests")
def of_update_withdrawal_period(body: _WithdrawalPeriodBody):
    """OF's Statements payout frequency select: PATCH /payouts/requests
    {withdrawalPeriod} (a withdrawalPeriodOptions code). Answers {success}."""
    return _proxy(lambda: _get_client().update_withdrawal_period(body.withdrawalPeriod))

@app.get("/api/of/v2/payouts/requests")
@_account_ttl("payouts", 60)
def of_payout_requests(limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0),
                       start: str | None = Query(None, max_length=32), end: str | None = Query(None, max_length=32),
                       marker: str | None = Query(None, max_length=64)):
    """Payout request history (Statements > Payout requests tab). `start`/`end`
    ('YYYY-MM-DD HH:MM:SS') and `marker` go to OF as startDate, endDate and
    marker, the way OF's own page pages it; without them the request is unchanged."""
    return _proxy(lambda: _get_client().payout_requests(
        limit=limit, offset=offset, start=start, end=end, marker=marker))

@app.get("/api/of/v2/subscriptions/count/all")
def of_subscription_counts_all():
    """Full subscription breakdown (active/expired/blocked/etc) + subscribers + bookmarks."""
    return _proxy(lambda: _get_client().subscription_counts_all())

@app.get("/api/of/v2/subscriptions/subscribers/chart")
def of_subscribers_chart(start: str | None = Query(None), end: str | None = Query(None),
                         by: str | None = Query(None, pattern="^(total|renew|new)$")):
    """Daily new-subscriber time-series (Statistics > Fans). Earnings-based:
    accurate for paid pages, 0 for free pages. `by` = the Subscriptions tab
    (All=total / Renews=renew / New=new), as OF's page sends it."""
    return _proxy(lambda: _get_client().subscribers_chart(start=start, end=end, by=by))


# ── Users / search ─────────────────────────────────────────────

@app.get("/api/of/v2/users/search")
def of_search_users(q: str = Query(..., min_length=1, max_length=100), limit: int = Query(10, ge=1, le=50),
                    offset: int = Query(0, ge=0)):
    """Search users by name/username (OF's own search box: `/users?query=&view=se`)."""
    return _proxy(lambda: _get_client().search_users(q, limit=limit, offset=offset))

@app.get("/api/of/v2/users/performers-search")
def of_performers_search(query: str = Query(..., min_length=1, max_length=100),
                         limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0)):
    """Creators only (the share dialog's username autocomplete)."""
    return _proxy(lambda: _get_client().performers_search(query, limit=limit, offset=offset))

@app.get("/api/of/v2/posts/search")
def of_search_posts(query: str = Query(..., min_length=1, max_length=100),
                    limit: int = Query(10, ge=1, le=50)):
    """The feed search's posts (OF's posts list with `query`)."""
    return _proxy(lambda: _get_client().search_posts(query, limit=limit))

@app.get("/api/of/v2/release-forms")
def of_release_forms(limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0),
                     filter: str = Query("all", pattern="^(all|pending)$"),
                     sort: str = Query("date:desc", pattern="^(date|name):(asc|desc)$"),
                     name: str | None = Query(None, max_length=100)):
    """The tag dialog's Release form tab (OF's releaseForms/fetchFormsPage)."""
    return _proxy(lambda: _get_client().release_forms(
        limit=limit, offset=offset, filter=filter, sort=sort, name=name))

class _ReleaseFormToggleBody(BaseModel):
    entity_id: int = Field(..., ge=1)
    entity_type: str = Field(..., pattern="^(user|guest|partner|form)$")

@app.patch("/api/of/v2/release-forms/toggle-show")
def of_toggle_release_form(body: _ReleaseFormToggleBody = Body(...)):
    """A tag row's "More" > hide from / back to the list (OF: {entityId, entityType})."""
    return _proxy(lambda: _get_client().toggle_release_form(
        entity_id=body.entity_id, entity_type=body.entity_type))

class _GuestBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)

@app.post("/api/of/v2/guests")
def of_create_guest(body: _GuestBody = Body(...)):
    """The tag dialog's "Invite new user": OF answers with the guest (its invite token)."""
    return _proxy(lambda: _get_client().create_guest(name=body.name))

@app.get("/api/of/v2/posts/tagged-friend-users")
async def of_tagged_friend_users(
    search: str | None = Query(None, max_length=100),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    filter: str = Query("all"),
    sort: str = Query("date:desc"),
    skip_users: str = Query("all"),
    refresh: bool = Query(False, alias="refresh"),
):
    """Creators eligible to be tagged in posts AND chat messages — same
    endpoint OF web uses for the chat composer's @-tag picker. Search is
    forwarded as `name=` to OF (captured live 2026-05-23).

    BC6: 5min TTL relay_cache, exact-tuple key (NO prefix-collapse). A
    user typing "abc" then "abcd" intentionally produces two cache
    entries — OF's response shape differs per substring.
    """
    aid = _resolve_account_id(_request_ctx.get())
    coalesce_key = ("tagged_friend_users", aid, search, limit, offset, filter, sort, skip_users)
    async def _fetch():
        return await relay_coalesce.coalesce(coalesce_key, lambda: asyncio.to_thread(
            _proxy, lambda: _get_client().tagged_friend_users(
                search=search, limit=limit, offset=offset,
                filter=filter, sort=sort, skip_users=skip_users,
            ),
        ))
    return await relay_cache.get_or_fetch(
        "tagged_friend_users", aid,
        (search, limit, offset, filter, sort, skip_users),
        ttl_seconds=300.0, fetcher=_fetch, bypass=refresh,
    )

@app.get("/api/of/v2/users/{user_id}/posts")
def of_user_posts(user_id: str, limit: int = Query(10, ge=1, le=50),
                  type: str | None = Query(None, description="'photo'|'video'|'audio'"),
                  before_publish_time: str | None = Query(
                      None, description="OF cursor (tailMarker) for the next/older page"),
                  format: str | None = Query(
                      None, description="'infinite' → OF returns hasMore/tailMarker for stitching")):
    """Posts owned by a creator's OWN profile wall — NOT the subscriptions
    home feed (`/posts`, which mixes in other creators). `user_id` accepts a
    numeric id or 'me'. `type` filters by media. Pass `format=infinite` plus
    the previous response's `tailMarker` as `before_publish_time` to page
    backwards through the wall."""
    return _proxy(lambda: _get_client().user_posts(
        user_id, limit=limit, type=type,
        before_publish_time=before_publish_time, format=format))

# /posts/bookmarks declared earlier above (before /posts/{post_id}) so static
# path wins over the dynamic one.

@app.get("/api/of/v2/users/{user_id}/stories")
def of_user_stories(user_id: str):
    """Active stories for a creator. `user_id` accepts numeric id or 'me'."""
    return _proxy(lambda: _get_client().user_stories(user_id))

@app.get("/api/of/v2/users/{user_id}/stories/highlights")
def of_user_highlights(user_id: str):
    """Highlights for a creator. `user_id` accepts numeric id or 'me'."""
    return _proxy(lambda: _get_client().user_highlights(user_id))

@app.get("/api/of/v2/stories/highlights/{highlight_id}")
def of_highlight(highlight_id: int = PathParam(..., ge=1)):
    """One highlight with its stories (`{..., stories: [...]}`), as OF's profile
    plays it (My profile's highlight tiles)."""
    return _proxy(lambda: _get_client().highlight(highlight_id))

@app.get("/api/of/v2/users/{user_id}/posts/photos")
def of_user_photos(user_id: str, limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0)):
    """Photo posts by a creator."""
    return _proxy(lambda: _get_client().user_photos(user_id, limit=limit, offset=offset))

@app.get("/api/of/v2/users/{user_id}/posts/videos")
def of_user_videos(user_id: str, limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0)):
    """Video posts by a creator."""
    return _proxy(lambda: _get_client().user_videos(user_id, limit=limit, offset=offset))


# ── Subscribers / counts ───────────────────────────────────────

@app.get("/api/of/v2/subscribers")
def of_subscribers(
    type: str = Query("active", pattern="^(active|expired|all|attention|muted|recent)$"),
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    online: int | None = Query(None, ge=0, le=1, description="1 = only fans currently online"),
):
    """Fans subscribed to me. `type` filters by subscription state.
    `online=1` adds OF's `filter[online]=1` (the "Subscribers · online" list)."""
    return _proxy(lambda: _get_client().subscribers(
        type=type, limit=limit, offset=offset,
        online=(bool(online) if online is not None else None),
    ))


# ── Posts ──────────────────────────────────────────────────────

@app.get("/api/of/v2/posts")
def of_list_posts(limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0)):
    """My own posts."""
    return _proxy(lambda: _get_client().list_posts(limit=limit, offset=offset))


# Posts shortcuts — declared BEFORE /posts/{post_id: int} to avoid the int-validation
# trap on static second segments like "chart" / "top".
@app.get("/api/of/v2/posts/chart")
def of_posts_chart(start: str | None = Query(None), end: str | None = Query(None),
                   by: str | None = Query(None, pattern="^(purchases|tips|views|likes|comments)$")):
    """Post-performance time-series (Statistics > Engagement chart). `by` adds
    OF's filter[{by}] + filter[posts], the Purchases/Views/Likes/Comments chips."""
    return _proxy(lambda: _get_client().posts_chart(start=start, end=end, by=by))

@app.get("/api/of/v2/posts/top")
def of_posts_top(
    start: str | None = Query(None),
    end: str | None = Query(None),
    by: str = Query("purchases", description="purchases|likes|comments|views"),
    limit: int = Query(10, ge=1, le=50),
    offset: int | None = Query(None, ge=0, description="Engagement › Posts paging"),
):
    """Top-performing posts in a date range."""
    return _proxy(lambda: _get_client().posts_top(start=start, end=end, by=by, limit=limit,
                                                  offset=offset))

# Statistics' per-post reads. The post id rides in the query (as on
# /messages/queue/buyers) so the permission map can give them to Statistics:
# `/posts/{id}/...` could only be mapped through `/posts`, which carries the
# post writes of Home, New post and My profile.
@app.get("/api/of/v2/posts/stats")
def of_post_stats(post_id: int | None = Query(None, ge=1)):
    """Full stat / the post stats popup header: OF's /posts/{post_id}/stats?withChart=true.
    With no post_id: {"supported": true} and no OF request, the mirror's probe that
    this relay has the per-item reads (a 2xx, so the browser logs no error)."""
    if post_id is None:
        return {"supported": True}
    return _proxy(lambda: _get_client().post_stats(post_id))

@app.get("/api/of/v2/posts/buyers")
def of_post_buyers(post_id: int = Query(..., ge=1), limit: int = Query(10, ge=1, le=50),
                   offset: int = Query(0, ge=0)):
    """A post's Purchases figure: OF's /posts/{post_id}/buyers, {list:[user], hasMore}."""
    return _proxy(lambda: _get_client().post_users(post_id, "buyers", limit=limit, offset=offset))

@app.get("/api/of/v2/posts/tips")
def of_post_tips(post_id: int = Query(..., ge=1), limit: int = Query(10, ge=1, le=50),
                 offset: int = Query(0, ge=0)):
    """A post's Tips figure: OF's /posts/{post_id}/tips, {list:[user], hasMore}."""
    return _proxy(lambda: _get_client().post_users(post_id, "tips", limit=limit, offset=offset))

@app.get("/api/of/v2/posts/likes")
def of_post_likes(post_id: int = Query(..., ge=1), limit: int = Query(10, ge=1, le=50),
                  offset: int = Query(0, ge=0)):
    """A post's Likes figure (OF's PostLikes list): OF's /posts/{post_id}/favorites,
    {list:[user], hasMore}."""
    return _proxy(lambda: _get_client().post_users(post_id, "favorites", limit=limit, offset=offset))

@app.get("/api/of/v2/posts/{post_id}")
def of_get_post(post_id: int):
    """Single post detail."""
    return _proxy(lambda: _get_client().get_post(post_id))

@app.get("/api/of/v2/posts/{post_id}/comments")
def of_post_comments(post_id: int, limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0)):
    """Comments on a post."""
    return _proxy(lambda: _get_client().post_comments(post_id, limit=limit, offset=offset))


# ── Vault ──────────────────────────────────────────────────────

def vault_media_cache_key(*, type: str = "all", list_id: int | None = None,
                          offset: int = 0, limit: int = 24, sort: str = "desc",
                          field: str = "recent", q_norm: str = "",
                          before: str | None = None) -> str:
    """THE cache key for a /vault/media request — the single place its format
    lives. tests/test_chatter_access seeds vault_cache through this helper, so
    a format change (like the `query=` part vault search added) can never
    silently strand a stale literal and turn the suite red again."""
    # `before` (Go to date) only when set, so every existing key stays as it was.
    return (f"media:type={type}|list={list_id}|offset={offset}|limit={limit}"
            f"|sort={sort}|field={field}|query={q_norm}"
            + (f"|before={before}" if before else ""))


def vault_lists_cache_key(*, view: str = "main", limit: int = 10, offset: int = 0,
                          q_norm: str = "") -> str:
    """THE cache key for a /vault/lists request — same single-home rule.
    The folder search (`q_norm`) only when set, so the plain key is unchanged."""
    return f"lists:view={view}|limit={limit}|offset={offset}" + (f"|query={q_norm}" if q_norm else "")


@app.get("/api/of/v2/vault/media")
async def of_vault_media(
    limit: int = Query(24, ge=1, le=100),
    offset: int = Query(0, ge=0),
    type: str = Query("all", pattern="^(all|photo|video|gif|audio)$",
                      description="OF uses `type=`, not `filter=` — guessing wrong silently returns everything"),
    list_id: int | None = Query(None),
    sort: str = Query("desc", pattern="^(asc|desc)$",
                      description="OF honors server-side sort; asc = oldest-first"),
    field: str = Query("recent"),
    query: str | None = Query(None, description="OF-native vault search (wire param `query`)"),
    before_publish_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$",
                                            description="OF's Go to date (wire param `beforePublishDate`)"),
    refresh: bool = Query(False, description="Bypass the shared server cache; forces a fresh OF fetch"),
):
    """My vault items. Filter by media kind via `type=`, order via `sort=`
    (asc/desc — OF honors both), full-text search via `query=`.

    Reads from the shared server-side cache (vault_response_cache) keyed
    on (account_id, query_key). All employees on the same OF account
    share the cache, so the second open is instant. Cache is invalidated
    on uploads/deletes and ages out by TTL for external edits.
    """
    aid = _resolve_account_id(_request_ctx.get())
    # Chatter Access (step 4): folder-visibility gate. Evaluate the deny
    # BEFORE touching vault_cache — a cached list_id=None "All" entry must
    # never reach a restricted chatter. SOFT deny (empty payload matching
    # OF's exact shape, {"list": [], "hasMore": False}) so the frontend's
    # .map() never throws; never raise.
    allowed_folders = await _allowed_folder_ids_for_chatter(aid)
    if allowed_folders is not None and (
        list_id is None or list_id not in allowed_folders
    ):
        return {"list": [], "hasMore": False}
    # `query` is part of the cache key so a search result can never be served
    # for a different (or empty) query.
    q_norm = (query or "").strip()
    key = vault_media_cache_key(type=type, list_id=list_id, offset=offset,
                                limit=limit, sort=sort, field=field, q_norm=q_norm,
                                before=before_publish_date)
    if not refresh:
        cached = await vault_cache.get(aid, key)
        if cached is not None:
            return cached
    result = await asyncio.to_thread(
        _proxy,
        lambda: _get_client().vault_media(
            limit=limit, offset=offset, type=type, list_id=list_id,
            sort=sort, field=field, query=q_norm or None,
            before_publish_date=before_publish_date,
        ),
    )
    await vault_cache.put(aid, key, result)
    return result


@app.get("/api/of/v2/vault/media/{media_id}")
async def of_vault_media_by_id(media_id: int) -> dict[str, Any]:
    """One vault item by id — resolves a bare media id back to a media object
    (with `files.thumb` etc. for thumbnails). Powers the Brain panel's saved
    per-slot images (`time_images` stores only ids), which the paginated list
    can't surface unless the item happens to land on a loaded page.

    Owner-gated: the only caller is the owner-only Brain editor, and gating to
    the account owner keeps this from becoming a folder-restriction bypass for
    restricted chatters (the list route soft-denies per folder; a by-id read
    can't be folder-scoped, so we require ownership instead). Cached server-side
    via vault_cache like the list route, so repeat loads are instant and shared.
    """
    aid = _resolve_account_id(_request_ctx.get())
    assert_account_owned(aid)
    key = f"media-by-id:{media_id}"
    cached = await vault_cache.get(aid, key)
    if cached is not None:
        return cached

    async def _fetch() -> dict[str, Any]:
        # The slot is INSIDE the coalescer on purpose (see relay_coalesce's
        # module docstring): waiters that joined an in-flight fetch hold no
        # slot, so only the one caller actually going to OF occupies one.
        async with admission.VAULT_MEDIA_READ:
            fetched = await asyncio.to_thread(
                _proxy, lambda: _get_client().vault_media_by_id(media_id),
            )
        await vault_cache.put(aid, key, fetched)
        return fetched

    # A remount, a second tab, or two panes resolving the same slot image all
    # ask for the SAME id at once; without this each paid its own OF round-trip
    # for bytes the others were already fetching. Keyed on the account too — a
    # bare media id would let two accounts share a response.
    return await relay_coalesce.coalesce(
        ("vault_media_by_id", aid, media_id), _fetch,
    )


# ── Fan lists ──────────────────────────────────────────────────

@app.get("/api/of/v2/lists")
def of_get_lists(limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0)):
    """My custom fan lists + built-in ones like 'fans', 'recent'."""
    return _proxy(lambda: _get_client().get_lists(limit=limit, offset=offset))

# A list's id in OF's URL path: a number, or a built-in list's name ("fans", "tagged", …); nothing else reaches OF
# (a decoded "7?x=" or "7/../8" would otherwise become another OF path). Every /lists/{list_id} route takes it.
ListId = Annotated[str, PathParam(pattern=r"^[A-Za-z0-9_-]+$")]


@app.get("/api/of/v2/lists/{list_id}")
def of_get_list(list_id: ListId):
    """List metadata. Built-in names like 'fans' work too."""
    return _proxy(lambda: _get_client().get_list(list_id))

@app.get("/api/of/v2/lists/{list_id}/users")
def of_list_users_in(list_id: ListId, limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0),
                     query: str | None = Query(None, max_length=100)):
    """Fans in a list; `query` is Collections' Search users (OF's own `query` param)."""
    return _proxy(lambda: _get_client().list_users_in(list_id, limit=limit, offset=offset, query=query or None))

@app.get("/api/of/v2/lists/{list_id}/posts")
def of_list_posts_in(list_id: ListId, limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0),
                     type: str | None = Query(None, pattern="^(photos|videos|audios|other|locked)$")):
    """A list's Posts tab (OF Manager > Collections): its users' posts; `type` is the tab's chip."""
    return _proxy(lambda: _get_client().list_posts_in(list_id, limit=limit, offset=offset, type=type))


# ── Money ──────────────────────────────────────────────────────

@app.post("/admin/vault/cache/invalidate")
async def admin_vault_cache_invalidate() -> dict[str, Any]:
    """Drop every cached vault response for the current account. The picker's
    Refresh button calls this so both vault-media AND vault-lists go upstream
    on the next fetch (the `?refresh=1` flag only covers a single endpoint)."""
    aid = _resolve_account_id(_request_ctx.get())
    deleted = await vault_cache.invalidate(aid)
    return {"ok": True, "account_id": aid, "deleted": deleted}


@app.get("/api/of/v2/vault/lists")
async def of_vault_lists(view: str = Query("main"), limit: int = Query(10, ge=1, le=50),
                         offset: int = Query(0, ge=0),
                         query: str | None = Query(None, description="The folder search (wire param `query`)"),
                         refresh: bool = Query(False, description="Bypass the shared server cache")):
    """Vault folders. Note OF's required `view` param value is `main`.
    Cached server-side via vault_cache (same invalidation semantics as
    /api/of/v2/vault/media)."""
    aid = _resolve_account_id(_request_ctx.get())
    # Chatter Access (step 4): compute the folder gate BEFORE the cache read
    # so a cached unfiltered payload is never handed straight to a restricted
    # chatter. None ⇒ no restriction (owner, or unrestricted chatter).
    allowed_folders = await _allowed_folder_ids_for_chatter(aid)
    q_norm = (query or "").strip()
    key = vault_lists_cache_key(view=view, limit=limit, offset=offset, q_norm=q_norm)
    result = None
    if not refresh:
        result = await vault_cache.get(aid, key)
    if result is None:
        result = await asyncio.to_thread(
            _proxy,
            lambda: _get_client().vault_lists(view=view, limit=limit, offset=offset,
                                              query=q_norm or None),
        )
        # Cache the UNFILTERED payload — owners + other chatters share this
        # entry. Filtering happens per-response below, never written back.
        await vault_cache.put(aid, key, result)
    if allowed_folders is not None and isinstance(result, dict):
        # Filter on READ only — shallow-copy so the cached object keeps its
        # full folder list for owners/unrestricted chatters.
        filtered = dict(result)
        filtered["list"] = [
            f for f in (result.get("list") or [])
            if f.get("id") in allowed_folders
        ]
        return filtered
    return result

@app.get("/api/of/v2/payouts/balances")
@_account_ttl("payouts", 60)
def of_payout_balances():
    """Current balance + breakdown."""
    return _proxy(lambda: _get_client().payout_balances())

@app.get("/api/of/v2/payouts/check-receive")
@_account_ttl("payouts", 60)
def of_payout_check_receive():
    """Eligibility for next payout (banking complete, KYC done, etc)."""
    return _proxy(lambda: _get_client().payout_check_receive())


@app.get("/api/of/v2/users/settings/story")
def of_settings_story():
    """Story settings (who may reply to stories)."""
    return _proxy(lambda: _get_client().settings_story())

@app.get("/api/of/v2/schedules/later/chat")
def of_schedules_later_chat(limit: int = Query(10, ge=1, le=50)):
    """Chats scheduled for the future (newer API than /messages/queue)."""
    return _proxy(lambda: _get_client().schedules_later_chat(limit=limit))

@app.get("/api/of/v2/schedules/later/post")
def of_schedules_later_post(limit: int = Query(10, ge=1, le=50)):
    """Posts scheduled for the future."""
    return _proxy(lambda: _get_client().schedules_later_post(limit=limit))

@app.get("/api/of/v2/schedules")
def of_schedules(
    publish_date: str | None = Query(None, description="ISO yyyy-mm-dd"),
    publish_date_end: str | None = Query(None, description="ISO yyyy-mm-dd"),
    time_zone: str = Query("Europe/Ljubljana"),
    limit: int = Query(20, ge=1, le=50),
):
    """Calendar view of scheduled chats + posts in a date range."""
    return _proxy(lambda: _get_client().schedules(
        publish_date=publish_date, publish_date_end=publish_date_end,
        time_zone=time_zone, limit=limit,
    ))


@app.put("/api/of/v2/schedules/{schedule_id}/publish")
def of_publish_schedule(schedule_id: int):
    """Publish a queue item now (OF Manager's queue "Post now" / "Message now")."""
    return _proxy(lambda: _get_client().publish_schedule(schedule_id))

@app.get("/api/of/v2/payouts/transactions")
@_account_ttl("payouts", 60)
def of_transactions(
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    type: str | None = Query(None),
    start: str | None = Query(None, description="ISO yyyy-mm-dd"),
    end: str | None = Query(None, description="ISO yyyy-mm-dd"),
    startDate: str | None = Query(None, max_length=32,
                                  description="Statistics: the period start, 'YYYY-MM-DD HH:MM:SS'"),
    marker: str | None = Query(None, pattern=r"^[0-9]{1,20}$",
                               description="Statistics paging: the period end as a unix "
                                           "timestamp, then each response's nextMarker"),
    tipsSource: str | None = Query(None, pattern="^(profile|post_all|chat|stream|story)$",
                                   description="Statistics › Tips sub-tab"),
):
    """Earning transactions (tips/subs/messages/posts). Statistics › Statements ›
    Earnings pages it OF's way: startDate + marker (+ type, tipsSource)."""
    return _proxy(lambda: _get_client().transactions(
        limit=limit, offset=offset, type=type, start=start, end=end,
        start_date=startDate, marker=marker, tips_source=tipsSource,
    ))

@app.get("/api/of/v2/payouts/stats")
@_account_ttl("payouts", 60)
def of_earning_stats(
    by: str = Query("day", pattern="^(day|week|month)$"),
    start: str | None = Query(None),
    end: str | None = Query(None),
):
    """Time-series earnings totals."""
    return _proxy(lambda: _get_client().earning_stats(by=by, start=start, end=end))


# ── Stories ────────────────────────────────────────────────────


# ── Catch-all single user lookup ───────────────────────────────
# Declared AFTER every static /users/... route so it doesn't shadow them.

@app.get("/api/of/v2/users/{user_id_or_username}")
async def get_user(user_id_or_username: str) -> dict[str, Any]:
    """Fetch a single user profile by numeric id or username.

    Runs the OF→local sync of `displayName`/`notice` (same logic as
    /users/list) so that opening the drawer for a fan whose name was
    edited directly on onlyfans.com flips our local `Fan.custom_nickname`
    /`Fan.notes` to match. Without this, the chat-list rail keeps
    showing the stale value because enrichWithUsers short-circuits to
    the local `by-ids` lookup for any fan we already know."""
    aid = _resolve_account_id(_request_ctx.get())
    key = ("get_user", aid, user_id_or_username)

    async def _fetch():
        resp = await asyncio.to_thread(
            _proxy, lambda: _get_client().get_user(user_id_or_username)
        )
        if not isinstance(resp, dict):
            return resp
        # Overlay inside the fetcher — see /users/list rationale.
        fid = resp.get("id")
        if isinstance(fid, int):
            try:
                await _sync_of_user_overlay(aid, {str(fid): resp})
            except Exception:
                log.exception("custom_nickname stitch failed for /users/{id}")
        return resp

    return await relay_coalesce.coalesce(key, _fetch)


# ── Promotions / Trials ────────────────────────────────────────

@app.get("/api/of/v2/promotions")
def of_promotions():
    """My subscription promotions."""
    return _proxy(lambda: _get_client().promotions())


# ── Chat extras ────────────────────────────────────────────────

@app.get("/api/of/v2/chats/{chat_id}")
def of_get_chat(chat_id: int):
    """Full chat detail. Richer than the per-item shape from /chats."""
    return _proxy(lambda: _get_client().get_chat(chat_id))

@app.get("/api/of/v2/messages/queue")
def of_scheduled_messages(limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0)):
    """Messages scheduled for future delivery."""
    return _proxy(lambda: _get_client().scheduled_messages(limit=limit, offset=offset))

@app.get("/api/of/v2/users/me/stats/messages/group")
async def of_mass_message_history(
    request: Request,
    startDate: str = Query(..., description="YYYY-MM-DD HH:MM:SS"),
    endDate: str = Query(..., description="YYYY-MM-DD HH:MM:SS"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    query: str | None = Query(None, max_length=200, description="The tab's search box text"),
):
    """Past mass-message broadcasts (the /statistics/engagement/messages
    feed). `query` is the page's search box (OF pages a search by offset). Each item carries the queue `id` — pass to DELETE
    /messages/queue/{id} to unsend the broadcast from EVERY recipient
    (no edit window for mass sends, per OF's `unsendSeconds=1000000`).

    Write-through to `mass_broadcast_cache` on every successful fetch so
    the /admin/mass-messages read path can serve subsequent opens off
    SQLite without an OF roundtrip."""
    import mass_broadcast_cache as cache
    resp = await asyncio.to_thread(_proxy, lambda: _get_client().engagement_messages(
        "group", start_date=startDate, end_date=endDate, limit=limit, offset=offset, query=query,
    ))
    # Best-effort write-through. Don't let a cache miss surface as a 502
    # — the upstream succeeded, the operator should still see the data.
    if isinstance(resp, dict):
        items = resp.get("items") or []
        try:
            account_id = _resolve_account_id(request)
            await cache.upsert_many(account_id, items)
        except Exception as e:
            log.warning("mass_broadcast_cache upsert failed: %s", e)
    return resp


@app.get("/admin/mass-messages")
async def admin_mass_messages_list(
    request: Request,
    account_id: str | None = Query(None, description="OF account id; defaults to X-Account-Id"),
    days_back: int = Query(30, ge=1, le=730),
    limit: int = Query(100, ge=1, le=500),
):
    """Read past mass broadcasts for ONE account from the local cache.

    Fast path for the Settings → Mass messages tab — no OF roundtrip,
    snappy across reloads. Pair with POST /admin/mass-messages/refresh
    to force a fresh pull from OF and re-warm the cache.

    Safety net: if the cache hasn't been refreshed within TTL_SECONDS
    (1 day), pull from OF once before serving so the UI doesn't drift
    silently when no-one clicks Refresh."""
    import mass_broadcast_cache as cache
    aid = account_id or _resolve_account_id(request)
    if await cache.is_stale(aid):
        try:
            end = datetime.utcnow()
            start = end - timedelta(days=days_back)
            fmt = "%Y-%m-%d %H:%M:%S"
            client = _load_client(aid)

            def _fetch():
                # Run the blocking OF round-trip (and the per-account lane
                # acquire) OFF the event loop so a stale-cache safety-net
                # refresh can't freeze vault-open / chat-click for everyone.
                with _priority_lane(aid):
                    return client.mass_message_history(
                        start_date=start.strftime(fmt),
                        end_date=end.strftime(fmt),
                        limit=limit, offset=0,
                    )
            resp = await asyncio.to_thread(_fetch)
            items = (resp.get("items") if isinstance(resp, dict) else None) or []
            await cache.upsert_many(aid, items)
        except Exception as e:
            # Don't fail the read just because the safety-net refresh failed;
            # serve whatever we have and let the user hit Refresh manually.
            log.warning("mass_broadcast_cache safety-net refresh failed for %s: %s", aid, e)
    since = datetime.utcnow() - timedelta(days=days_back)
    items = await cache.list_for_account(aid, since=since, limit=limit)
    return {"account_id": aid, "days_back": days_back, "items": items}


@app.post("/admin/mass-messages/refresh")
async def admin_mass_messages_refresh(
    request: Request,
    account_id: str | None = Query(None),
    days_back: int = Query(30, ge=1, le=730),
    limit: int = Query(100, ge=1, le=500),
):
    """Pull from OF + upsert into the cache + return the fresh rows.

    The frontend calls this when the user clicks Refresh. Done as a
    single HTTP call (vs. fetching from OF and then re-reading the cache)
    so the UI gets the new state in one roundtrip."""
    import mass_broadcast_cache as cache
    aid = account_id or _resolve_account_id(request)
    end = datetime.utcnow()
    start = end - timedelta(days=days_back)
    fmt = "%Y-%m-%d %H:%M:%S"
    # Resolve the right client by hand — _proxy() relies on the request
    # context's X-Account-Id, but for this endpoint we accept it as a
    # query param too. _load_client() bypasses the context resolver.
    client = _load_client(aid)
    try:
        def _fetch():
            # Blocking OF round-trip + lane acquire run OFF the event loop;
            # this manual Refresh must not freeze every other request.
            with _priority_lane(aid):
                return client.mass_message_history(
                    start_date=start.strftime(fmt),
                    end_date=end.strftime(fmt),
                    limit=limit, offset=0,
                )
        resp = await asyncio.to_thread(_fetch)
    except OFAPIError as e:
        r = e.response
        status = r.status_code if r is not None else 500
        body = r.text[:2000] if r is not None else str(e)
        raise HTTPException(
            status_code=502,
            detail={"upstream_status": status, "upstream_body": body},
        )
    items = (resp.get("items") if isinstance(resp, dict) else None) or []
    written = await cache.upsert_many(aid, items)
    since = datetime.utcnow() - timedelta(days=days_back)
    rows = await cache.list_for_account(aid, since=since, limit=limit)
    return {"account_id": aid, "days_back": days_back, "written": written, "items": rows}


# ── Writes (UNVERIFIED — code-only, no live test from auto run) ───
# Every endpoint below maps to a known OF API path inferred from the cracked
# extension + OnlyFansAPI/OFAuth docs. Shapes are likely correct but each one
# needs a single careful live test before you trust it in a UI.

# Pydantic bodies for FastAPI's auto-validation + Swagger forms.
class _TextBody(BaseModel):
    text: str = Field(..., min_length=1)

class _NameBody(BaseModel):
    name: str = Field(..., min_length=1)

class _ScheduleMessageBody(BaseModel):
    text: str
    scheduled_date: str = Field(..., description="ISO 8601, e.g. 2026-06-01T18:00:00+00:00")
    price: float = Field(0, ge=0)
    locked_text: bool = False
    # Same shape as immediate-send: numeric vault ids OR fresh-upload claim
    # dicts. OF accepts both in mediaFiles on the queue endpoint too.
    media_files: list[int | dict] = Field(default_factory=list)
    previews: list[int] = Field(default_factory=list)
    tagged_users: list[int] = Field(default_factory=list)

class _ScheduledSendBody(BaseModel):
    """Near-term (≤15 min) deferred 1:1 send, fired by OUR executor (the
    `scheduled_send` automation), not OF's queue. Survives reload + is shared
    cross-chatter because it's a DB row, not an in-browser timer."""
    fan_id: int = Field(..., description="Fan's OF user id (the chat peer).")
    run_at: str = Field(..., description="ISO 8601 fire time, e.g. 2026-06-13T15:38:00Z")
    text: str = ""
    price: float = Field(0, ge=0)
    locked_text: bool = False
    media_files: list[int | dict] = Field(default_factory=list)
    previews: list[int] = Field(default_factory=list)
    tagged_users: list[int] = Field(default_factory=list)
    giphy_id: str | None = None


class _CreatePostBody(BaseModel):
    text: str
    # int = existing vault id; dict = fresh-upload claim payload from
    # the /upload endpoint's `send_with`. OF accepts mixed.
    media_files: list[int | dict] = Field(default_factory=list)
    price: float = Field(0, ge=0)
    # Media ids (⊆ media_files) shown FREE as the teaser on a PAID post.
    previews: list[int] = Field(default_factory=list)
    # Our names for OF's post extras; of_client.create_post maps each to OF's
    # own keys (posted_at -> isScheduled + scheduledDate, and so on).
    posted_at: str | None = None
    save_for_later: bool = False
    expire_days: int | None = Field(None, ge=1)
    fund_raising_target: float | None = Field(None, gt=0)
    fund_raising_presets: list[float] = Field(default_factory=list)
    voting_type: int | None = Field(None, ge=1, le=2)  # 1 poll, 2 quiz
    voting_options: list[str] = Field(default_factory=list)
    voting_due: int | None = Field(None, ge=1)  # days
    voting_correct_index: int | None = Field(None, ge=0)  # quiz only
    label_ids: list[int] = Field(default_factory=list)
    # OF user ids of creators to @-tag in the post (sent as `userTags`).
    tagged_users: list[int] = Field(default_factory=list)
    # Giphy id (e.g. "0ndspgUFbm9iQtyX2Q") — forwarded as top-level
    # `giphyId` to OF. Same wire shape as chat sends.
    giphy_id: str | None = Field(
        None,
        description="Giphy GIF id forwarded to OF as top-level `giphyId`.",
    )

class _EditPostBody(BaseModel):
    text: str | None = None
    price: float | None = None
    media_files: list[int | dict] | None = None


# Chat-message writes ---------------------------------------------
# These hit /messages/{id}/... directly on OF (no /chats/{cid} prefix). All
# four like/unlike/pin/unpin VERIFIED LIVE; unsend works but is DESTRUCTIVE.

class _UnsendMessageBody(BaseModel):
    """OF web sends `{withUserId: <fanId>}` on every message unsend. Forwarding
    it lets OF return the parent `queue` object in the response — needed so
    the UI can offer "also unsend from everyone" on mass-message bubbles."""
    withUserId: int | None = None


@app.delete("/api/of/v2/messages/{message_id}")
async def of_unsend_message(request: Request, message_id: int):
    """Unsend (delete) a chat message. Works inside OF's edit window only.

    The OF endpoint expects an optional `{"withUserId": <fan_id>}` body.
    We accept the body if present (FastAPI's `Body(...)` would 400 on
    empty bodies, so we parse defensively)."""
    with_user_id: int | None = None
    try:
        raw = await request.body()
        if raw:
            import json as _json
            parsed = _json.loads(raw)
            if isinstance(parsed, dict) and parsed.get("withUserId") is not None:
                with_user_id = int(parsed["withUserId"])
    except Exception:
        with_user_id = None
    resp = await asyncio.to_thread(
        _proxy, lambda: _get_client().unsend_message(message_id, with_user_id=with_user_id))
    # OF took the bubble down — mirror that onto our `messages` row, or the
    # chat pane's DB seed (GET /admin/messages) paints it again on the next
    # reload as an EMPTY locked shell (the seed carries no media, and a PPV
    # row's body is blank). Best-effort: the upstream unsend already happened,
    # so a mirror failure must not surface as a 500.
    try:
        from messages import mark_unsent
        await mark_unsent(_resolve_account_id(request), message_id, fan_id=with_user_id)
    except Exception as e:
        log.warning("unsend mirror flip failed message_id=%s: %s", message_id, e)
    return resp

class _WithUserBody(BaseModel):
    withUserId: int

class _BookmarkBody(BaseModel):
    chat_group_id: int | None = None

@app.put("/api/of/v2/messages/{message_id}/hide")
def of_hide_message(message_id: int, body: _WithUserBody = Body(...)):
    """Hide a message the other side sent (OF web's per-message "Hide": PUT /messages/{id}/hide {withUserId})."""
    return _proxy(lambda: _get_client().hide_message(message_id, body.withUserId))

@app.post("/api/of/v2/messages/{message_id}/bookmark")
def of_bookmark_message(message_id: int, body: _BookmarkBody | None = Body(None)):
    """Bookmark a chat message (OF web: POST /posts/{id}/bookmarks {chat_group_id})."""
    return _proxy(lambda: _get_client().bookmark_message(message_id, body.chat_group_id if body else None, True))

@app.delete("/api/of/v2/messages/{message_id}/bookmark")
def of_unbookmark_message(message_id: int, body: _BookmarkBody | None = Body(None)):
    return _proxy(lambda: _get_client().bookmark_message(message_id, body.chat_group_id if body else None, False))

@app.delete("/api/of/v2/chats/{chat_id}/messages/pin")
def of_unpin_all_messages(chat_id: int):
    """OF web's pinned page "Unpin all messages": DELETE /chats/{id}/messages/pin."""
    result = _proxy(lambda: _get_client().unpin_all_messages(chat_id))
    _bust_chat_list_cache()  # the chat drops off the list's Pinned tab
    return result

@app.post("/api/of/v2/messages/{message_id}/like")
def of_like_message(message_id: int):
    """Like a message you received (can't like your own)."""
    return _proxy(lambda: _get_client().like_message(message_id))

@app.delete("/api/of/v2/messages/{message_id}/like")
def of_unlike_message(message_id: int):
    return _proxy(lambda: _get_client().unlike_message(message_id))

@app.post("/api/of/v2/messages/{message_id}/pin/user/{user_id}")
def of_pin_message(message_id: int, user_id: int):
    """Pin a message inside a chat. Path mirrors OF's wire shape
    (`/messages/{msg}/pin/user/{chat_partner}`) — the shorter `/pin` form
    didn't reliably pin to the chat's visible pinned list."""
    return _proxy(lambda: _get_client().pin_message(message_id, user_id))

@app.delete("/api/of/v2/messages/{message_id}/pin/user/{user_id}")
def of_unpin_message(message_id: int, user_id: int):
    return _proxy(lambda: _get_client().unpin_message(message_id, user_id))

# Chat-level actions (VERIFIED LIVE) — mark read/unread, mute, hide.
# Static path BEFORE dynamic /chats/{chat_id}/... to avoid `chat_id="mark-as-read"`
# int-validation 422.

async def _set_local_unread(account_id: str, *, fan_id: int | None, value: int) -> None:
    """Mirror an OF read-state change into local `chats.unread_count` so the roster
    badge (a local aggregate) updates immediately instead of waiting for the next
    /chats reconcile. fan_id=None → every chat on the account (bulk mark-all-read).
    Best-effort: own session, swallows errors."""
    try:
        from db.engine import get_session as _gs
        from db.models import Chat as _Chat
        from sqlalchemy import update as _update
        async with _gs() as s:
            stmt = _update(_Chat).where(_Chat.account_id == account_id).values(unread_count=value)
            if fan_id is not None:
                stmt = stmt.where(_Chat.fan_id == fan_id)
            await s.execute(stmt)
            await s.commit()
    except Exception:
        log.warning("_set_local_unread(%s, fan=%s) failed — best-effort", account_id, fan_id,
                    exc_info=True)

def _bust_chat_list_and_badges(aid: str) -> None:
    """Drop the account's cached chat window AND its roster badge counts, after
    an OF write that changes what both derive from: a read-state flip (mark
    read/unread changes `unreadMessagesCount`) or a deleted chat (its row and
    its count leave). Neither is a message, so the WS pump never busts these,
    and without this both would serve the pre-write snapshot for their TTL."""
    relay_cache.invalidate("list_chats", aid)
    relay_cache.invalidate("roster_count", aid)

@app.post("/api/of/v2/chats/mark-as-read")
async def of_mark_all_chats_read():
    """Mark EVERY chat as read (bulk no-arg endpoint)."""
    aid = _resolve_account_id(_request_ctx.get())
    await _set_local_unread(aid, fan_id=None, value=0)
    result = await asyncio.to_thread(_proxy, lambda: _get_client().mark_all_chats_read())
    _bust_chat_list_and_badges(aid)
    return result

async def _paced_of_write(aid: str, call):
    """One OF write that reaches no fan, spaced through the account's write
    pacer and translated like any `_proxy` call. Not every OF write is paced:
    the pacer's gap is for what a fan sees (messages, posts), so a write a fan
    never sees (mark read/unread, hide, list membership) goes out unpaced by
    default. This is for the one still spaced: the chat delete — an
    operator's, so it goes ahead of automation's waiting writes (ADR 0025)."""
    from automation_executor import of_write_paced
    return await of_write_paced(aid, lambda: _proxy(call), send_purpose="not_fan_dm", operator=True)

@app.post("/api/of/v2/chats/{chat_id}/mark-as-read")
async def of_mark_chat_read(chat_id: int):
    """Mark chat as read (chat_id == fan id). Clears local unread_count too.

    Unpaced, bulk loops included: a read flip reaches no fan, and pacing it
    would reserve an 11 s write slot per chat ahead of the automations' fan
    sends."""
    aid = _resolve_account_id(_request_ctx.get())
    await _set_local_unread(aid, fan_id=chat_id, value=0)
    result = await asyncio.to_thread(_proxy, lambda: _get_client().mark_chat_read(chat_id))
    _bust_chat_list_and_badges(aid)
    return result

@app.delete("/api/of/v2/chats/{chat_id}/mark-as-read")
async def of_mark_chat_unread(chat_id: int):
    """Mark chat as unread (same path as mark-read but DELETE)."""
    aid = _resolve_account_id(_request_ctx.get())
    await _set_local_unread(aid, fan_id=chat_id, value=1)
    result = await asyncio.to_thread(_proxy, lambda: _get_client().mark_chat_unread(chat_id))
    _bust_chat_list_and_badges(aid)
    return result

@app.post("/api/of/v2/chats/{chat_id}/mute")
def of_mute_chat(chat_id: int):
    """Mute notifications for a chat."""
    return _proxy(lambda: _get_client().mute_chat(chat_id))

@app.delete("/api/of/v2/chats/{chat_id}/mute")
def of_unmute_chat(chat_id: int):
    return _proxy(lambda: _get_client().unmute_chat(chat_id))

@app.post("/api/of/v2/chats/{chat_id}/hide")
def of_hide_chat(chat_id: int):
    """Hide chat from inbox (chat still exists; fan can still message)."""
    r = _proxy(lambda: _get_client().hide_chat(chat_id))
    # OF already drops the chat from its `/chats` feed server-side, but our
    # relay caches that feed for 10 min — without busting it the hidden row
    # lingers in the inbox until the TTL expires. Drop it so the row vanishes
    # on the very next refetch the hide mutation already fires.
    _bust_chat_list_cache()
    return r

@app.delete("/api/of/v2/chats/{chat_id}/hide")
def of_unhide_chat(chat_id: int):
    r = _proxy(lambda: _get_client().unhide_chat(chat_id))
    _bust_chat_list_cache()  # symmetric: surface the un-hidden chat immediately
    return r

@app.delete("/api/of/v2/chats/{chat_id}")
async def of_delete_chat(chat_id: int):
    """Clear a chat's messages (OF's chat-list row "x", DELETE /chats/{id}). Not
    reversible. Paced (`_paced_of_write`); one chat per call (OF web's bulk form
    joins ids with commas, but no live capture vouches for it). Busts the cached
    chat list and the roster badge so the row and its count go on the next read."""
    aid = _resolve_account_id(_request_ctx.get())
    r = await _paced_of_write(aid, lambda: _get_client().delete_chat(chat_id))
    _bust_chat_list_and_badges(aid)
    return r


# ── Per-fan "Restrict from automations" (durable skip_list, NOT an OF call) ──
# A human can durably opt a fan out of EVERY automation from the chat ⋯ menu /
# Settings. It writes skip_list(reason='manual_restrict') in OUR DB — honoured by
# every sender (see automations/_common HARD_SKIP_REASONS). Distinct from the
# auto 'muted_creator' skip the scrape manages off the OF mute state.

@app.get("/api/of/v2/automation-restrict/{fan_id}")
async def of_automation_restrict_status(fan_id: int, request: Request) -> dict:
    """Is this fan restricted from automations? {restricted, reason}."""
    from automations._common import automation_restrict_status
    account_id = _resolve_account_id(request)
    return await automation_restrict_status(account_id, fan_id)


@app.get("/api/of/v2/chats/{chat_id}/media")
def of_chat_media(
    chat_id: int,
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    last_id: str | None = Query(None, description="Cursor: pass the previous response's nextLastId."),
    skip_users: str | None = Query(None, description="Set to 'all' to drop the per-message fromUser blob (matches OF's purchased-tab call)."),
    opened: int | None = Query(None, ge=0, le=1, description="opened=1 filters to messages the fan has VIEWED (includes free)."),
    purchased: int | None = Query(None, ge=0, le=1, description="purchased=1 filters to PPVs the fan actually paid for (OF's Purchased tab)."),
    from_user: int | None = Query(None, description="Filter to messages from one specific user; pair with purchased=1 + the creator's user id to get only outbound paid messages (the canonical Sales feed)."),
):
    """Only messages in this chat that contain media.

    `purchased=1` + `from_user=<creator_user_id>` + `skip_users=all`
    mirrors OF's per-fan PURCHASED gallery (the /gallery/purchased URL
    in the web UI) and is the canonical source for the fan-drawer Sales
    section. `opened=1` is a different filter — items the fan has
    viewed, including free messages — kept for the "any viewed" case."""
    return _proxy(lambda: _get_client().chat_media(
        chat_id,
        limit=limit,
        offset=offset,
        last_id=last_id,
        skip_users=skip_users,
        opened=opened,
        purchased=purchased,
        from_user=from_user,
    ))

@app.get("/api/of/v2/chats/{chat_id}/media/{kind}")
def of_chat_media_kind(
    chat_id: int,
    kind: Literal["photos", "videos", "audios"],
    limit: int = Query(20, ge=1, le=50),
    last_id: str | None = Query(None, description="Cursor: pass the previous response's nextLastId."),
    skip_users: str | None = Query(None),
    opened: int | None = Query(None, ge=0, le=1),
    purchased: int | None = Query(None, ge=0, le=1),
    from_user: int | None = Query(None),
):
    """One type of this chat's media: OF web's gallery Photos / Videos / Audio
    tabs, which put the type in the PATH (/chats/{id}/media/photos), not the
    query. Same params and `{list, hasMore, nextLastId}` page as /media."""
    return _proxy(lambda: _get_client().chat_media(
        chat_id,
        limit=limit,
        last_id=last_id,
        skip_users=skip_users,
        opened=opened,
        purchased=purchased,
        from_user=from_user,
        kind=kind,
    ))

@app.get("/api/of/v2/chats/{chat_id}/messages/search")
def of_search_chat(chat_id: int, query: str = Query(..., min_length=1, description="Substring to match against message text."),
                   filter: Literal["pinned"] | None = Query(None, description="OF web's pinned page: its pins only.")):
    """Search the FULL history of one chat. Returns a list of matching
    message IDs (newest first) — OF's native chat-search endpoint. The
    caller is responsible for fetching previews / paging to load the
    matched message bodies if they aren't in the local cache yet.

    OF param is `query` (not `text` — that 200s with an empty list)."""
    return _proxy(lambda: _get_client().search_chat(chat_id, query, filter))

@app.post("/api/of/v2/users/{user_id}/block")
def of_block_user(user_id: int):
    """Block a user (hides chat + prevents future messages from them)."""
    return _proxy(lambda: _get_client().block_user(user_id))

@app.delete("/api/of/v2/users/{user_id}/block")
def of_unblock_user(user_id: int):
    return _proxy(lambda: _get_client().unblock_user(user_id))

@app.post("/api/of/v2/users/{user_id}/restrict")
async def of_restrict_user(user_id: int, request: Request, ack: bool = Query(True),
                           hide: bool = Query(True)) -> dict:
    """Restrict a user on OnlyFans (their messages stop being delivered to us),
    with the inbox left CLEAN — restricting is how operators silence promo-spam
    peer creators, and the whole point is getting them out of the unread counts:

      1. `ack` (default on): send one "." reply first, so OUR message is the
         chat's lastMessage and the thread stops counting as owe-reply, then
         mark the chat read so OF's unreadMessagesCount is 0. Both best-effort —
         a creator we can't message anymore must still be restrictable.
      2. Restrict on OF (the only step that must succeed).
      3. Write the durable skip_list(reason='of_restricted') row — every
         automation hard-skips them (HARD_SKIP_REASONS) and the roster badge /
         inbox chips exclude them from the unread counts from now on, even if
         OF ever flags the thread again.
      4. `hide` (default on): hide the chat on OF, best-effort. OF's hide is
         deliberately NOT durable — the thread re-surfaces on the next inbound
         message — which is exactly the shelf life we want here: the restricted
         creator's dead thread leaves the inbox now, but a genuine new message
         still brings it back. Must run LAST: the "." send in step 1 would
         re-surface a just-hidden chat.

    The ack rides the normal send handler so it gets employee attribution, the
    local outbound mirror and the cache busts for free. Skipped when the fan is
    already in the durable registry (a second click must not send another dot)."""
    from automations._common import load_of_restricted_ids, set_of_restricted_skip
    account_id = _resolve_account_id(request)
    acked = False
    if ack and int(user_id) not in await load_of_restricted_ids(account_id):
        try:
            await send_message(request, user_id, SendMessageBody(text="."))
            acked = True
        except Exception:
            log.warning("restrict ack send failed (account=%s fan=%s) — restricting anyway",
                        account_id, user_id, exc_info=True)
        try:
            await of_mark_chat_read(user_id)
        except Exception:
            log.warning("restrict mark-read failed (account=%s fan=%s)",
                        account_id, user_id, exc_info=True)
    result = await asyncio.to_thread(_proxy, lambda: _get_client().restrict_user(user_id))
    await set_of_restricted_skip(account_id, user_id, True)
    hidden = False
    if hide:
        try:
            await asyncio.to_thread(_proxy, lambda: _get_client().hide_chat(user_id))
            hidden = True
        except Exception:
            log.warning("restrict hide-chat failed (account=%s fan=%s) — restricted anyway",
                        account_id, user_id, exc_info=True)
    # The counts derive from the cached window + this registry — drop both
    # folds so the next badge/list read reflects the exclusion (and the hidden
    # row's disappearance) immediately.
    relay_cache.invalidate("list_chats", account_id)
    relay_cache.invalidate("roster_count", account_id)
    return {"ok": True, "restricted": True, "acked": acked, "hidden": hidden, "of": result}

@app.delete("/api/of/v2/users/{user_id}/restrict")
async def of_unrestrict_user(user_id: int, request: Request, unhide: bool = Query(True)) -> dict:
    """Lift an OF restrict + remove the durable 'of_restricted' row (the fan
    re-enters unread counts and automations may target them again). `unhide`
    (default on) also un-hides the chat (best-effort, symmetric with the
    hide-on-restrict) so the thread is visible again without waiting for the
    fan's next message. The OF Manager mirror sends `unhide=false`: OF's own
    Unrestrict is the one DELETE, and a chat the Creator hid stays hidden."""
    from automations._common import set_of_restricted_skip
    account_id = _resolve_account_id(request)
    result = await asyncio.to_thread(_proxy, lambda: _get_client().unrestrict_user(user_id))
    await set_of_restricted_skip(account_id, user_id, False)
    if unhide:
        try:
            await asyncio.to_thread(_proxy, lambda: _get_client().unhide_chat(user_id))
        except Exception:
            log.warning("unrestrict unhide-chat failed (account=%s fan=%s)",
                        account_id, user_id, exc_info=True)
    relay_cache.invalidate("list_chats", account_id)
    relay_cache.invalidate("roster_count", account_id)
    return {"ok": True, "restricted": False, "of": result}

@app.get("/api/of/v2/stories")
def of_stories_feed():
    """Stories feed (creators I follow)."""
    return _proxy(lambda: _get_client().stories_feed())

@app.get("/api/of/v2/stories/archive")
def of_stories_archive(limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0)):
    """My own archived (expired) stories."""
    return _proxy(lambda: _get_client().my_stories_archive(limit=limit, offset=offset))

@app.get("/api/of/v2/giphy/proxy/gifs/trending")
def of_gif_trending(limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0)):
    """Trending GIFs via OF's Giphy proxy."""
    return _proxy(lambda: _get_client().gif_trending(limit=limit, offset=offset))

@app.get("/api/of/v2/giphy/proxy/gifs/search")
def of_gif_search(q: str = Query(..., min_length=1),
                  limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0)):
    """Search Giphy via OF's proxy."""
    return _proxy(lambda: _get_client().gif_search(q, limit=limit, offset=offset))

# ── Message templates (welcome + saved replies) ───────────────


@app.get("/api/of/v2/messages/templates")
def of_message_templates(template: str | None = Query(None, description="filter, e.g. 'reply_on_subscribe'")):
    """Saved replies + welcome message. `template=reply_on_subscribe` filters to the welcome message."""
    return _proxy(lambda: _get_client().message_templates(template=template))


# ── Welcome message slot (reply_on_subscribe) ──────────────────
# Slot-specific upsert + delete + the `replyOnSubscribe` master toggle.
# OF's web client doesn't go through the generic /messages/templates
# create/PUT for the welcome — it POSTs/DELETEs the slot URL directly
# and uses the extended body shape, so we mirror that here.
#
# IMPORTANT: declared BEFORE the generic /messages/templates/{id} routes
# so FastAPI's first-match-wins ordering routes /reply_on_subscribe here
# rather than treating it as a numeric template id.


class _ReplyOnSubscribeBody(BaseModel):
    enabled: bool


@app.patch("/api/of/v2/users/me/reply-on-subscribe")
def of_set_reply_on_subscribe(body: _ReplyOnSubscribeBody = Body(...)):
    """Toggle the master `replyOnSubscribe` flag on /users/me."""
    result = _proxy(lambda: _get_client().set_reply_on_subscribe(body.enabled))
    # BC5 invalidation: this write changes /users/me/settings.replyOnSubscribe.
    aid = _resolve_account_id(_request_ctx.get())
    relay_cache.invalidate("my_settings", aid)
    return result


# ── Subscription bundles ──────────────────────────────────────

class _BundleBody(BaseModel):
    # OF's own ADD SUBSCRIPTION BUNDLE dialog sends {discount, duration} (months)
    # and OF prices the bundle; the legacy {months, price[, discount]} stays.
    months: int | None = Field(None, ge=1, le=24)
    price: float | None = Field(None, ge=0)
    discount: int | None = Field(None, ge=0, le=100)
    duration: int | None = Field(None, ge=1, le=24)

@app.get("/api/of/v2/subscriptions/bundles")
def of_subscription_bundles():
    """Multi-month bundle pricing config."""
    return _proxy(lambda: _get_client().subscription_bundles())

@app.post("/api/of/v2/subscriptions/bundles")
def of_create_bundle(body: _BundleBody = Body(...)):
    if body.duration is None and (body.months is None or body.price is None):
        raise HTTPException(status_code=422, detail="send duration (OF's dialog) or months and price")
    return _proxy(lambda: _get_client().create_bundle(
        months=body.months, price=body.price, discount=body.discount,
        duration=body.duration,
    ))

@app.delete("/api/of/v2/subscriptions/bundles/{bundle_id}")
def of_delete_bundle(bundle_id: int):
    return _proxy(lambda: _get_client().delete_bundle(bundle_id))

class _BundleEditBody(BaseModel):
    discount: int = Field(..., ge=0, le=100)
    duration: int = Field(..., ge=1, le=24)

@app.put("/api/of/v2/subscriptions/bundles/{bundle_id}")
def of_edit_bundle(bundle_id: int, body: _BundleEditBody = Body(...)):
    """OF's bundle edit: PUT /subscriptions/bundles/{id} {discount, duration, id}."""
    return _proxy(lambda: _get_client().edit_bundle(
        bundle_id, discount=body.discount, duration=body.duration,
    ))

# ── Promotion campaigns: write side ───────────────────────────

class _PromoBody(BaseModel):
    # OF promos are a % discount off the sub (verified live) — NOT an abs price.
    # A free trial is discount 100 (OF's own Start campaign, ModalPromotion).
    discount: int = Field(..., ge=1, le=100)
    # 0 = no limit (OF's "No limits" option).
    subscribe_counts: int = Field(..., ge=0)
    subscribe_days: int = Field(30, ge=0)
    message: str = Field("", max_length=500)
    # OF's composer sends a list: ["all"], ["expired"] or both.
    type: str | list[str] = "all"
    # The offer's expiration in days (0 = no limit); OF's composer sends it.
    finish_days: int | None = Field(None, ge=0, le=30)

@app.post("/api/of/v2/promotions")
def of_create_promo(body: _PromoBody = Body(...)):
    """Create a promo campaign. Touches public-facing offers; double-check before exposing."""
    if isinstance(body.type, list) and (not body.type or not set(body.type) <= {"all", "expired"}):
        raise HTTPException(status_code=422, detail='type: a list of "all" and/or "expired"')
    return _proxy(lambda: _get_client().create_promo(
        discount=body.discount, subscribe_counts=body.subscribe_counts,
        subscribe_days=body.subscribe_days, message=body.message, type=body.type,
        finish_days=body.finish_days,
    ))

@app.post("/api/of/v2/promotions/{promo_id}/finish")
def of_finish_promo(promo_id: int):
    """Stop promotion: OF's POST /promotions/{id}/finish (the campaign ends, the row stays)."""
    return _proxy(lambda: _get_client().finish_promo(promo_id))

@app.delete("/api/of/v2/promotions/{promo_id}")
def of_delete_promo(promo_id: int):
    return _proxy(lambda: _get_client().delete_promo(promo_id))

# ── Tracking links (/campaigns) ──────────────────────────────

class _TrackingLinkBody(BaseModel):
    name: str
    code: int | None = None

@app.get("/api/of/v2/campaigns")
def of_tracking_links():
    """Tracking link list with countSubscribers + countTransitions stats."""
    return _proxy(lambda: _get_client().tracking_links())

@app.post("/api/of/v2/campaigns")
def of_create_tracking_link(body: _TrackingLinkBody = Body(...)):
    return _proxy(lambda: _get_client().create_tracking_link(
        name=body.name, code=body.code,
    ))

@app.delete("/api/of/v2/campaigns/{campaign_id}")
def of_delete_tracking_link(campaign_id: int):
    return _proxy(lambda: _get_client().delete_tracking_link(campaign_id))

# ── Free-trial links (/trials) ───────────────────────────────

class _TrialLinkBody(BaseModel):
    # OF's "Create link" sends the name trimmed of leading spaces; it may be empty.
    name: str = Field("", max_length=64)
    subscribe_days: int = Field(7, ge=1, le=365)
    # 0 = no limit (OF's "No limits").
    subscribe_counts: int = Field(1, ge=0)
    expired_at: str | None = None
    # OF's own field: the link's validity in days (0 = no expiration).
    expire_days: int | None = Field(None, ge=0, le=30)

_TRIAL_SORT_FIELDS = {"create_date", "expire_date", "subscribe_counts", "subscribe_days",
                      "claims_count", "clicks_count", "shared"}

@app.get("/api/of/v2/trials")
def of_trial_links(field: str | None = Query(None, description="OF's sort field (TrialFilter)"),
                   sort: str | None = Query(None, pattern="^(asc|desc)$")):
    """Free-trial link list with claim/click counts; `field` + `sort` is OF's own sort menu."""
    if field or sort:
        if field not in _TRIAL_SORT_FIELDS or not sort:
            raise HTTPException(status_code=422, detail=f"field: one of {sorted(_TRIAL_SORT_FIELDS)}, with sort asc|desc")
        return _proxy(lambda: _get_client().trial_links_sorted(field=field, sort=sort))
    return _proxy(lambda: _get_client().trial_links())

@app.get("/api/of/v2/trials/share-access")
def of_trials_shared_with_me(limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0)):
    """The "Shared with you" tab: other creators' free trial links shared with this model."""
    return _proxy(lambda: _get_client().trials_shared_with_me(limit=limit, offset=offset))

class _ShareTrialBody(BaseModel):
    trial_id: int = Field(..., ge=1)
    user_id: int = Field(..., ge=1)

@app.post("/api/of/v2/trials/share-access")
def of_share_trial_stats(body: _ShareTrialBody = Body(...)):
    """Share a free trial link's statistics with another creator (OF: {trialId, userId})."""
    return _proxy(lambda: _get_client().share_trial_stats(trial_id=body.trial_id, user_id=body.user_id))

@app.post("/api/of/v2/trials")
def of_create_trial_link(body: _TrialLinkBody = Body(...)):
    return _proxy(lambda: _get_client().create_trial_link(
        name=body.name.lstrip(" "), subscribe_days=body.subscribe_days,
        subscribe_counts=body.subscribe_counts, expired_at=body.expired_at,
        expire_days=body.expire_days,
    ))

@app.delete("/api/of/v2/trials/{trial_id}")
def of_delete_trial_link(trial_id: int):
    return _proxy(lambda: _get_client().delete_trial_link(trial_id))

# ── Profile writes (bio, display name, etc.) ─────────────────

# The keys the OF Manager mirror sends to each users/me write (app/lib/ofMirrorWrites.ts
# ProfilePatch; ofMirrorSettingsWrites.ts settingWrite, SECURITY_KEYS, collectWatermarks).
# Any other key is refused, so a crafted body cannot reach the rest of the Creator's account.
_PROFILE_KEYS = frozenset({
    # settings/profile
    "name", "about", "location", "website", "wishlist",
    # settings/subscription's price Save
    "subscribePrice",
    # the settings/fans, settings/security and notifications/mentions toggles outside the security section
    "recommenderReward", "sendAwardsTop1", "sendAwardsTop5",
    "isVisibleOnline", "isOldLoginRedirect", "commentsOnlyForPayers", "creatorsCommentsOnlyForFriends",
    "notifyOnAllMentions", "muteTagsInChats", "muteTagsInPosts", "muteTagsInStories",
})
_SECURITY_PATCH_KEYS = frozenset({
    "isSuggestionsOptOut", "phoneOtp", "isPrivate", "showPostsTips", "showFriendsToSubscribers",
    "showSubscribesOffers", "showSubscribersCount", "isWantComments", "isAutoFollowBack",
    "unfollowAutoFollowBack", "coStreamingRequestFrom", "showMediaCount", "isDrmEnabled",
    "requireFaceIdForPayoutUpdate",
})
_WATERMARK_KEYS = frozenset({"hasWatermarkPhoto", "hasWatermarkVideo", "watermarkText", "watermarkPosition"})


def _allowed_body(body: dict, allowed: frozenset[str]) -> dict:
    """`body` when it is non-empty and every key is in `allowed`, else 422."""
    if not body:
        raise HTTPException(status_code=422, detail="empty body")
    if extra := sorted(set(body) - allowed):
        raise HTTPException(status_code=422, detail=f"keys not allowed: {', '.join(extra)}")
    return body


@app.patch("/api/of/v2/users/me")
def of_update_profile(body: dict = Body(...)):
    """PATCH /users/me — profile fields and the settings toggles OF saves here:
    only the `_PROFILE_KEYS` the mirror sends (422 on any other)."""
    body = _allowed_body(body, _PROFILE_KEYS)
    result = _proxy(lambda: _get_client().update_profile(**body))
    # BC5 invalidation: many /users/me fields are mirrored under
    # /users/me/settings, so any profile patch may change the cached blob.
    aid = _resolve_account_id(_request_ctx.get())
    relay_cache.invalidate("my_settings", aid)
    # A profile PATCH can move `subscribePrice` — re-read the page tier next ask.
    account_page.invalidate(aid)
    return result

# ── Settings writes (OF settings pages in the OF Manager mirror) ──

class _StorySettingsBody(BaseModel):
    allowReplyFrom: str = Field(..., pattern="^(subscribers|nobody)$")

def _settings_write(call: Callable[[], Any]) -> Any:
    """Proxy a settings write, then drop the cached /users/me/settings blob."""
    result = _proxy(call)
    relay_cache.invalidate("my_settings", _resolve_account_id(_request_ctx.get()))
    return result

@app.patch("/api/of/v2/users/me/settings/security")
def of_patch_security_settings(body: dict = Body(...)):
    """One security-section toggle, `{key: value}`, as OF's settings pages send it (`_SECURITY_PATCH_KEYS`)."""
    body = _allowed_body(body, _SECURITY_PATCH_KEYS)
    return _settings_write(lambda: _get_client().patch_security_settings(body))

@app.put("/api/of/v2/users/me/settings/security")
def of_put_security_settings(body: dict = Body(...)):
    """OF's watermarks Save: `{hasWatermarkPhoto, hasWatermarkVideo, watermarkText?, watermarkPosition}`."""
    body = _allowed_body(body, _WATERMARK_KEYS)
    return _settings_write(lambda: _get_client().put_security_settings(body))

@app.patch("/api/of/v2/users/settings/notifications")
def of_patch_notification_settings(body: dict = Body(...)):
    """A notification toggle `{notifications: {<transport>: [{code, value}]}}` or an email master switch."""
    if not body:
        raise HTTPException(status_code=422, detail="empty body")
    return _settings_write(lambda: _get_client().patch_notification_settings(body))

@app.patch("/api/of/v2/users/settings/story")
def of_patch_story_settings(body: _StorySettingsBody = Body(...)):
    """Story replies switch: `{allowReplyFrom: "subscribers" | "nobody"}`."""
    return _settings_write(lambda: _get_client().patch_story_settings(body.allowReplyFrom))

# ── Analytics (Statistics > Earnings/Engagement/Reach tabs) ────────
# All accept startDate/endDate as ISO with space (OF spec). Default = 30d window.

_CHART_FILTER_KEY = re.compile(r"^[a-z][a-z_]{0,40}$")

def _chart_filter(filter: str | None) -> list[str] | None:
    """Comma-separated series names → OF's filter[k]=k keys (422 on junk)."""
    if not filter:
        return None
    keys = [k.strip() for k in filter.split(",") if k.strip()]
    if not keys or not all(_CHART_FILTER_KEY.match(k) for k in keys):
        raise HTTPException(status_code=422, detail="filter: comma-separated series names")
    return keys

@app.get("/api/of/v2/earnings/chart")
@_account_ttl("earnings_chart", 120)
def of_earnings_chart(
    start: str | None = Query(None), end: str | None = Query(None),
    filter: str | None = Query(None, description="Comma-separated series, e.g. "
                               "'tips_count,tips_amount' (Statements) or "
                               "'total_amount,subscribes_amount,…' (Overview)"),
    monthlyTotal: int = Query(0, ge=0, le=1, description="1 = Overview's monthly bars (dates ignored)"),
):
    """Earnings series for Statistics (Overview chart, Statements sidebar and
    category radios). OF only returns the series named in `filter` — with none
    it answers [], which is why these charts were blank."""
    keys = _chart_filter(filter)
    return _proxy(lambda: _get_client().earnings_chart(
        start=start, end=end, filter=keys, monthly_total=bool(monthlyTotal)))

# /posts/chart and /posts/top declared above /posts/{post_id} in the file
# (see "Posts shortcuts" section) so they don't get shadowed by the int-typed
# dynamic route. Routes themselves live there; nothing here.

@app.get("/api/of/v2/users/me/stats/overview")
@_account_ttl("me_stats", 120)
def of_my_stats_overview(start: str | None = Query(None), end: str | None = Query(None),
                          by: str = Query("visitors")):
    """My stats overview (visitors/engagement)."""
    return _proxy(lambda: _get_client().my_stats_overview(start=start, end=end, by=by))

@app.get("/api/of/v2/users/me/stats/top/post")
@_account_ttl("me_stats", 120)
def of_my_stats_top_posts(start: str | None = Query(None), end: str | None = Query(None),
                          limit: int = Query(10, ge=1, le=50)):
    """My best-performing posts across types."""
    return _proxy(lambda: _get_client().my_stats_top_posts(start=start, end=end, limit=limit))

_PROFILE_STATS_BLOCKS = {"chart", "topDomains", "topCountries"}

@app.get("/api/of/v2/users/me/profile/stats")
def of_my_profile_stats(start: str | None = Query(None), end: str | None = Query(None),
                         limit: int = Query(10, ge=0, le=50),
                         by: str | None = Query(None, pattern="^(total|guests|users)$",
                                                description="Reach's All / Guests / Users chips"),
                         filter: str | None = Query(None, description="Comma-separated blocks: "
                                                    "chart, topDomains, topCountries (OF's filter[])")):
    """Visitor source breakdown (Statistics → Reach)."""
    blocks = [b.strip() for b in filter.split(",") if b.strip()] if filter else None
    if blocks is not None and (not blocks or not set(blocks) <= _PROFILE_STATS_BLOCKS):
        raise HTTPException(status_code=422, detail="filter: chart, topDomains and/or topCountries")
    return _proxy(lambda: _get_client().my_profile_stats(
        start=start, end=end, limit=limit, by=by, filter=blocks))

@app.get("/api/of/v2/users/me/profile/views/qr")
def of_my_qr_views():
    """Settings > QR code's scan count: OF's GET /users/me/profile/views/qr ({count})."""
    return _proxy(lambda: _get_client().qr_views())

@app.get("/api/of/v2/sessions")
def of_sessions():
    """Settings > Account > Login sessions, read-only: OF's GET /sessions (a list). Ending
    sessions (OF's DELETE /sessions) has no relay route."""
    return _proxy(lambda: _get_client().sessions())

@app.get("/api/of/v2/streams/users/blocked")
def of_stream_blocked_users(limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0),
                            query: str = Query("", max_length=64)):
    """Settings > Streaming > Blocked users, read-only: OF's GET /streams/users/blocked
    ({list, hasMore}). Blocking and unblocking have no relay route."""
    return _proxy(lambda: _get_client().stream_blocked_users(limit=limit, offset=offset, query=query))

@app.get("/api/of/v2/users/me/start-date-model")
def of_my_start_date():
    """When I became a creator — used to range-cap charts."""
    return _proxy(lambda: _get_client().my_start_date())

@app.get("/api/of/v2/payouts/chargebacks/ratio")
@_account_ttl("payouts", 60)
def of_chargebacks_ratio(start: str | None = Query(None), end: str | None = Query(None)):
    """Chargeback-rate risk metric."""
    return _proxy(lambda: _get_client().chargebacks_ratio(start=start, end=end))

# ── Statistics pages: lists, tops, streaks (OF app.js module 977600) ──
# Read-only GETs, one per call OF's own Statistics pages make; paths and query
# params copied from OF's client. `start`/`end` are 'YYYY-MM-DD HH:MM:SS' and
# default to the last 30 days, like every other analytics route here.

@app.get("/api/of/v2/payouts/chargebacks")
@_account_ttl("payouts", 60)
def of_chargebacks(start: str | None = Query(None), end: str | None = Query(None),
                   limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0),
                   marker: str | None = Query(None, max_length=64)):
    """Statements › Chargebacks list: {list, marker} (no hasMore; a full page means more)."""
    return _proxy(lambda: _get_client().chargebacks(
        start=start, end=end, limit=limit, offset=offset, marker=marker))

@app.get("/api/of/v2/users/me/stats/top/{kind}")
@_account_ttl("me_stats", 120)
def of_my_stats_top(kind: str, start: str | None = Query(None), end: str | None = Query(None)):
    """Overview › Top highlights: top message / stream / story, or top fan per
    category (an object keyed by category). /top/post is its own route above."""
    if kind not in ("message", "stream", "story", "fan"):
        raise HTTPException(status_code=404, detail="unknown top kind")
    return _proxy(lambda: _get_client().stats_top(kind, start=start, end=end))

@app.get("/api/of/v2/streaks")
def of_streaks(start: str | None = Query(None), end: str | None = Query(None)):
    """Overview › Streaks calendar: {list:[streak]}."""
    return _proxy(lambda: _get_client().streaks(start=start, end=end))

@app.get("/api/of/v2/streaks/top")
def of_streaks_top():
    """Overview › Streaks: the longest streak (`days`)."""
    return _proxy(lambda: _get_client().streaks_top())

@app.get("/api/of/v2/users/me/stats/today-activity")
@_account_ttl("me_stats", 120)
def of_today_activity():
    """Overview › Streaks: whether today already counts toward the streak."""
    return _proxy(lambda: _get_client().today_activity())

@app.get("/api/of/v2/users/me/stats/messages/direct")
@_account_ttl("me_stats", 120)
def of_direct_message_stats(startDate: str = Query(..., description="YYYY-MM-DD HH:MM:SS"),
                            endDate: str = Query(..., description="YYYY-MM-DD HH:MM:SS"),
                            limit: int = Query(50, ge=1, le=100),
                            offset: int = Query(0, ge=0),
                            query: str | None = Query(None, max_length=200)):
    """Engagement › Messages › Direct messages tab (and its search box):
    {hasMore, items:[message]}. Same params as the mass-messages route."""
    return _proxy(lambda: _get_client().engagement_messages(
        "direct", start_date=startDate, end_date=endDate, limit=limit, offset=offset, query=query))

@app.get("/api/of/v2/messages/queue/chart")
def of_messages_chart(type: str = Query("group", pattern="^(group|direct)$"),
                      start: str | None = Query(None), end: str | None = Query(None)):
    """Engagement › Messages chart + totals for one tab: OF's
    filter[{type}_messages] and filter[{type}_messages_purchases], withTotal."""
    return _proxy(lambda: _get_client().messages_chart(type, start=start, end=end))

# The queue id rides in the query, not the path, so the permission map can give
# this read to Statistics alone: a `/messages/queue/{id}/...` path could only be
# mapped through the `/messages/queue` prefix, which also carries the queue's writes.
@app.get("/api/of/v2/messages/queue/buyers")
def of_mass_message_buyers(queue_id: int = Query(..., ge=1, description="The mass message's queue id"),
                           limit: int = Query(10, ge=1, le=50),
                           offset: int = Query(0, ge=0),
                           marker: str | None = Query(None, max_length=64),
                           skip_users: str | None = Query(None, pattern="^(all|none)$")):
    """Who bought one mass message (the row's buyers list) — OF's
    /messages/queue/{queue_id}/buyers."""
    return _proxy(lambda: _get_client().mass_message_buyers(
        queue_id, limit=limit, offset=offset, marker=marker, skip_users=skip_users))

@app.get("/api/of/v2/subscriptions/subscribers/latest")
def of_subscribers_latest(by: str = Query("total", pattern="^(total|renew|new)$"),
                          start: str | None = Query(None), end: str | None = Query(None),
                          offset: int = Query(0, ge=0)):
    """Fans › Subscriptions table, tab All (total) / Renews (renew) / New (new):
    {users, hasMore}, 10 a page."""
    return _proxy(lambda: _get_client().subscribers_latest(by=by, start=start, end=end, offset=offset))

@app.get("/api/of/v2/subscriptions/subscribers/top")
def of_subscribers_top(by: str = Query("total", pattern="^(total|subscribes|tips|messages|post|streams)$"),
                       start: str | None = Query(None), end: str | None = Query(None),
                       offset: int = Query(0, ge=0)):
    """Fans › Top fans by total / subscriptions / tips / messages / posts /
    streams: {users, hasMore}, 10 a page."""
    return _proxy(lambda: _get_client().subscribers_top(by=by, start=start, end=end, offset=offset))

@app.get("/api/of/v2/fans-activity/list")
def of_fans_activity(format: str = Query("table", pattern="^(table|hours)$"),
                     start: str | None = Query(None), end: str | None = Query(None),
                     timeZone: str = Query("UTC", pattern=r"^[A-Za-z0-9_+\-]+(/[A-Za-z0-9_+\-]+)*$")):
    """Fans › Fans activity: weekday table or hourly bars in the owner's timezone."""
    return _proxy(lambda: _get_client().fans_activity(
        format=format, start=start, end=end, time_zone=timeZone))

@app.get("/api/of/v2/streams/top")
def of_streams_top(by: str = Query("purchases", pattern="^(purchases|tips|views|likes|comments)$"),
                   start: str | None = Query(None), end: str | None = Query(None),
                   limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0)):
    """Engagement › Streaming list: {items, hasMore}."""
    return _proxy(lambda: _get_client().streams_top(
        by=by, start=start, end=end, limit=limit, offset=offset))

@app.get("/api/of/v2/stories/top")
def of_stories_top(by: str = Query("tips", pattern="^(tips|views|likes|comments)$"),
                   start: str | None = Query(None), end: str | None = Query(None),
                   limit: int = Query(4, ge=1, le=50), offset: int = Query(0, ge=0)):
    """Engagement › Stories list: {items, hasMore}."""
    return _proxy(lambda: _get_client().stories_top(
        by=by, start=start, end=end, limit=limit, offset=offset))

@app.get("/api/of/v2/promotions/stats")
def of_promotions_stats(start: str | None = Query(None), end: str | None = Query(None),
                        limit: int = Query(10, ge=1, le=100), offset: int = Query(0, ge=0)):
    """Reach › Promotions table: OF's dated /promotions?offset&startDate&endDate&limit,
    {items, hasMore}. Its own path (not /promotions) so the permission map can give
    this read to Statistics without the promotion writes."""
    return _proxy(lambda: _get_client().promotions_stats(
        start=start, end=end, limit=limit, offset=offset))

@app.get("/api/of/v2/campaigns/stats")
def of_campaigns_stats(start: str | None = Query(None), end: str | None = Query(None),
                       limit: int = Query(10, ge=1, le=100), offset: int = Query(0, ge=0),
                       field: str | None = Query(None, pattern="^[A-Za-z_]{1,40}$"),
                       sort: str | None = Query(None, pattern="^(asc|desc)$")):
    """Reach › Tracking links table: OF's /campaigns?limit&offset&pagination=1&dates
    &with_deleted=1&sorting_deleted=0&stats=true (+field/sort), {list, hasMore}.
    Its own path (not /campaigns) so the permission map can give this read to
    Statistics without the tracking-link writes."""
    return _proxy(lambda: _get_client().campaigns_stats(
        start=start, end=end, limit=limit, offset=offset, field=field, sort=sort))

@app.get("/api/of/v2/trials/stats")
def of_trials_stats(start: str | None = Query(None), end: str | None = Query(None),
                    limit: int = Query(10, ge=1, le=100), offset: int = Query(0, ge=0)):
    """Reach › Free trial links table: {items, hasMore}."""
    return _proxy(lambda: _get_client().trials_stats(
        start=start, end=end, limit=limit, offset=offset))

# Reach's "claimed" / subscribers lists, one per row, paged by 10 like OF's
# user-list modal. The row id rides in the query: `/promotions/{id}`,
# `/trials/{id}` and `/campaigns/{id}` are OF settings' writes.
@app.get("/api/of/v2/promotions/claims")
def of_promotion_claims(promo_id: int = Query(..., ge=1), limit: int = Query(10, ge=1, le=50),
                        offset: int = Query(0, ge=0)):
    """Reach › Promotions › claimed: OF's /subscriptions/subscribers
    ?filter[promoId]=<promo_id>&format=infinite, {list:[user], hasMore}."""
    return _proxy(lambda: _get_client().offer_claims(promo_id, "promo", limit=limit, offset=offset))

@app.get("/api/of/v2/trials/claims")
def of_trial_claims(trial_id: int = Query(..., ge=1), limit: int = Query(10, ge=1, le=50),
                    offset: int = Query(0, ge=0)):
    """Reach › Free trial links › claimed: OF's /subscriptions/subscribers
    ?filter[trial_id]=<trial_id>&format=infinite, {list:[user], hasMore}."""
    return _proxy(lambda: _get_client().offer_claims(trial_id, "trial", limit=limit, offset=offset))

@app.get("/api/of/v2/campaigns/claimers")
def of_campaign_claimers(campaign_id: int = Query(..., ge=1), limit: int = Query(10, ge=1, le=50),
                         offset: int = Query(0, ge=0),
                         query: str | None = Query(None, max_length=100, description="the modal's search box")):
    """Reach › Tracking links › subscribers: OF's /campaigns/{campaign_id}/claimers,
    {list:[user], hasMore}."""
    return _proxy(lambda: _get_client().campaign_claimers(
        campaign_id, limit=limit, offset=offset, query=query))

# Charts OF's Statistics pages draw (module 977600; campaigns via 616150).
@app.get("/api/of/v2/payouts/chart")
@_account_ttl("payouts", 60)
def of_payouts_chart(start: str | None = Query(None), end: str | None = Query(None)):
    """Statements › Payout requests chart: {total, delta, chartAmount, chartCount}."""
    return _proxy(lambda: _get_client().payouts_chart(start=start, end=end))

@app.get("/api/of/v2/payouts/referrals/chart")
@_account_ttl("payouts", 60)
def of_referrals_chart(start: str | None = Query(None), end: str | None = Query(None)):
    """Statements › Referrals chart: {total, delta, chartAmount, chartCount}."""
    return _proxy(lambda: _get_client().referrals_chart(start=start, end=end))


# The referrals fan-out's overall budget: a Creator OF has not answered for by
# then is listed `unavailable` and the rest return. Its read keeps running
# (parked below, not cancelled) and lands in the cache for the next ask.
_REFERRALS_BUDGET_S = max(1.0, float(os.environ.get("REFERRALS_BUDGET_S", "10")))
_referrals_running: set[asyncio.Task] = set()
# Creators with a referrals read in flight, one at a time each: a miss for
# another window while one runs is `unavailable` rather than a second read, so
# flipping through date ranges cannot stack OF reads up behind the slots.
_referrals_reading: set[str] = set()


@app.get("/admin/stats/referrals", dependencies=[Depends(_stats_guard)])
async def admin_stats_referrals(
    account_id: str | None = Query(None, description="One id or several comma-separated; omit for every Creator"),
    from_: str = Query(..., alias="from", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    to: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    """Referral earnings per Creator over `from`..`to` (whole days), for the
    Dashboard's Referrals tile and Creator reports' Referrals channel.

    No transaction carries them, so this is OF's Statements › Referrals
    chart, ONE read per Creator (`referrals_chart`), at background priority,
    cached 5 minutes in the `payouts` namespace like the proxy above. The
    fan-out holds `admission.REFERRALS_READ` slots and answers within
    `_REFERRALS_BUDGET_S`. Read-only. OF buckets the days in its own time
    zone, not the report zone, so `by_day` and the window's edges can sit a
    few hours off the ledger's days. Scoped like the stats reads (the
    caller's Creators, 403 on a foreign id), then narrowed to Creators with a
    session; Fansly has no referral program, so its Creators are skipped. A
    Creator whose read fails, runs past the budget, is still reading another
    window, or is deactivated (it gets no OF call) is listed in `unavailable`
    rather than failing the rest. Rows `{account_id, total_cents, by_day:
    [{day, cents}]}`; OF's amounts are dollars."""
    scoped, _ = _stats_scope_ids(account_id)
    metas = account_registry.list_accounts()
    live = {m["id"] for m in metas if m.get("has_session")}
    ids = [a for a in (scoped if scoped is not None else [m["id"] for m in metas])
           if a in live and account_registry.get_platform(a) != "fansly"]
    off = await account_health.deactivated_ids()
    start, end = f"{from_} 00:00:00", f"{to} 23:59:59"

    async def one(aid: str) -> dict[str, Any]:
        def read():
            with _priority_lane_background(aid):
                return _load_client(aid).referrals_chart(start=start, end=end)

        async def fetch():
            # Only a cache miss takes a slot: a hit never queues behind OF reads.
            if aid in _referrals_reading:
                raise RuntimeError("a read for another window is still running")
            _referrals_reading.add(aid)
            try:
                async with admission.REFERRALS_READ:
                    return await asyncio.to_thread(read)
            finally:
                _referrals_reading.discard(aid)
        data = await relay_cache.get_or_fetch("payouts", aid, ("referrals", start, end), 300.0, fetch) or {}
        by_day = [{"day": str(p.get("date") or "")[:10], "cents": of_promos.to_cents(p.get("count"))}
                  for p in data.get("chartAmount") or [] if p.get("date")]
        return {"account_id": aid, "total_cents": of_promos.to_cents(data.get("total")), "by_day": by_day}

    tasks = {asyncio.create_task(one(a)): a for a in ids if a not in off}
    done, late = await asyncio.wait(set(tasks), timeout=_REFERRALS_BUDGET_S) if tasks else (set(), set())
    rows: list[dict[str, Any]] = []
    unavailable: list[str] = [a for a in ids if a in off]
    for t, aid in tasks.items():
        if t in late:
            _referrals_running.add(t)  # deliberately NOT cancelled
            t.add_done_callback(_referrals_running.discard)
            unavailable.append(aid)
        elif t.exception() is not None:
            log.warning("referrals read failed for %s: %r", aid, t.exception())
            unavailable.append(aid)
        else:
            rows.append(t.result())
    return {"rows": rows, "unavailable": unavailable}

@app.get("/api/of/v2/payouts/chargebacks/chart")
@_account_ttl("payouts", 60)
def of_chargebacks_chart(start: str | None = Query(None), end: str | None = Query(None)):
    """Statements › Chargebacks chart: {total, delta, chartAmount, chartCount}."""
    return _proxy(lambda: _get_client().chargebacks_chart(start=start, end=end))


@app.get("/api/of/v2/promotions/chart")
def of_promotions_chart(start: str | None = Query(None), end: str | None = Query(None)):
    """Reach › Promotions chart: {<series>: {chart, total, delta}}."""
    return _proxy(lambda: _get_client().promotions_chart(start=start, end=end))

@app.get("/api/of/v2/trials/chart")
def of_trials_chart(start: str | None = Query(None), end: str | None = Query(None)):
    """Reach › Free trial links chart: {<series>: {chart, total, delta}}."""
    return _proxy(lambda: _get_client().trials_chart(start=start, end=end))

@app.get("/api/of/v2/campaigns/chart")
def of_campaigns_chart(start: str | None = Query(None), end: str | None = Query(None)):
    """Reach › Tracking links chart: {clicks: {chart, total, delta}, claims: {...}}."""
    return _proxy(lambda: _get_client().campaigns_chart(start=start, end=end))

@app.get("/api/of/v2/stories/chart")
def of_stories_chart(by: str = Query("tips", pattern="^(tips|views|likes|comments)$"),
                     start: str | None = Query(None), end: str | None = Query(None)):
    """Engagement › Stories chart for one tab: {<by>|stories: {chart, total, delta}}."""
    return _proxy(lambda: _get_client().stories_chart(by=by, start=start, end=end))

@app.get("/api/of/v2/streams/chart")
def of_streams_chart(by: str = Query("purchases", pattern="^(purchases|tips|views|likes|comments)$"),
                     start: str | None = Query(None), end: str | None = Query(None)):
    """Engagement › Streaming chart for one tab: {<by>|duration: {chart, total, delta}}."""
    return _proxy(lambda: _get_client().streams_chart(by=by, start=start, end=end))

# The stream / story stats popup's Viewers and Tippers lists. The id rides in the
# query (as on /messages/queue/buyers) so the permission map can give these reads
# to Statistics: `/streams/{id}/...` and `/stories/{id}/...` could only be mapped
# through `/streams` and `/stories`, which are Go live's and Home's / New post's.
@app.get("/api/of/v2/streams/viewers")
def of_stream_viewers(stream_id: int = Query(..., ge=1), limit: int = Query(10, ge=1, le=50),
                      offset: int = Query(0, ge=0),
                      tips_only: int = Query(0, ge=0, le=1, description="1 = the Tippers tab")):
    """OF's /streams/{stream_id}/viewers: {list:[user], hasMore?}."""
    return _proxy(lambda: _get_client().stream_viewers(
        stream_id, limit=limit, offset=offset, tips_only=bool(tips_only)))

@app.get("/api/of/v2/stories/viewers")
def of_story_viewers(story_id: int = Query(..., ge=1), limit: int = Query(10, ge=1, le=50),
                     offset: int = Query(0, ge=0),
                     tips_only: int = Query(0, ge=0, le=1, description="1 = the Tippers tab")):
    """OF's /stories/{story_id}/viewers: {list:[user], hasMore?}."""
    return _proxy(lambda: _get_client().story_viewers(
        story_id, limit=limit, offset=offset, tips_only=bool(tips_only)))


@app.get("/api/of/v2/payouts/download-approved-invoice")
def of_payout_invoice(invoiceId: int = Query(..., ge=1),
                      isRefbonus: int = Query(0, ge=0, le=1, description="1 = a referral payout")):
    """An approved payout request's invoice, as OF's Download invoice link
    fetches it. OF answers 200 application/pdf with an attachment
    Content-Disposition (confirmed live); that PDF and OF's file name come back
    as sent. Anything else is a 502 carrying only OF's status code: the upstream
    URL is never logged nor returned."""
    r = _proxy(lambda: _get_client().payout_invoice(invoiceId, referral=bool(isRefbonus)))
    if not r.ok or "application/pdf" not in (r.headers.get("content-type") or "").lower():
        log.warning("payout invoice download failed: upstream %s, not a PDF", r.status_code)
        raise HTTPException(status_code=502, detail={"upstream_status": r.status_code})
    return Response(content=r.content, media_type="application/pdf", headers={
        "Cache-Control": "no-store",
        "Content-Disposition": r.headers.get("content-disposition") or "attachment"})

@app.get("/api/of/v2/users/me/referrals")
def of_my_referrals(onlyPerformers: int = Query(0, ge=0, le=1,
                                                description="1 = Referred creators, 0 = Referred users"),
                    start: str | None = Query(None), end: str | None = Query(None),
                    offset: int = Query(0, ge=0), marker: str | None = Query(None, max_length=64)):
    """Statements › Referrals › Referred creators / Referred users: {list, hasMore}."""
    return _proxy(lambda: _get_client().referrals(
        start=start, end=end, offset=offset, marker=marker, only_performers=bool(onlyPerformers)))

# ── Bookmarks (Collections → Bookmarks tab) ────────────────────────

@app.get("/api/of/v2/posts/bookmarks/all")
def of_bookmarks_all(limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0)):
    """Paginated bookmarks feed (the OF UI tab)."""
    return _proxy(lambda: _get_client().bookmarks_all(limit=limit, offset=offset))


# ── Referrals ──────────────────────────────────────────────────────

@app.get("/api/of/v2/payments/referrals/balance")
def of_referrals_balance():
    """Referral earnings balance."""
    return _proxy(lambda: _get_client().referrals_balance())

@app.get("/api/of/v2/payouts/requests/referral")
@_account_ttl("payouts", 60)
def of_referral_payouts(limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0),
                        start: str | None = Query(None, max_length=32), end: str | None = Query(None, max_length=32),
                        marker: str | None = Query(None, max_length=64)):
    """Referral payout history, paged as /payouts/requests (start, end, marker)."""
    return _proxy(lambda: _get_client().referral_payouts(
        limit=limit, offset=offset, start=start, end=end, marker=marker))

# ── Stories with map param + notification transports ──────────────


@app.get("/api/of/v2/users/settings/notifications/{transport}")
def of_notification_settings(transport: str, group: int | None = Query(None)):
    """One transport's notification toggles (read-only); `group=1` passes through."""
    if transport not in ("email", "message", "toast", "webpush", "sms", "telegram"):
        raise HTTPException(status_code=404, detail="unknown notification transport")
    return _proxy(lambda: _get_client().notification_settings(transport, group=group))


# Scheduled / mass --------------------------------------------------

@app.post("/api/of/v2/chats/{chat_id}/messages/scheduled")
async def of_schedule_message(chat_id: int, request: Request,
                              body: _ScheduleMessageBody = Body(...)):
    """Schedule a single message for future delivery (the frontend routes sends
    >15 min out here; ≤15 min go to /scheduled-sends).

    OF: POST /api2/v2/messages/queue with userIds=[chat_id]. Fansly has no
    per-message server queue we can reach, and its shim has no `schedule_message`
    — so a Fansly send >15 min out used to hit an AttributeError → 500 that the
    frontend swallowed, silently dropping the message. Instead, ride the relay's
    OWN executor queue (the same DB-backed `scheduled_jobs`/`scheduled_send` path
    the ≤15-min route uses, fired through the shim's real `send_message`). The OF
    path is untouched."""
    account_id = _resolve_account_id(request)
    if account_registry.get_platform(account_id) == "fansly":
        # Apply the shim's OWN send rules AT SCHEDULE TIME. The executor
        # forwards these kwargs verbatim, so anything send_message refuses
        # would otherwise be accepted here and fail silently at fire time —
        # hours later, with no operator feedback.
        #
        # Delegated, never re-implemented: these rules were briefly hand-copied
        # into this branch and drifted within a day (the all-previews money
        # check was added to the shim and not here, re-opening the exact
        # deferred-failure hole this block exists to close). check_sendable is
        # stateless precisely so this route can ask without a session.
        from fansly_client import FanslyAPIError
        from fansly_shim import check_sendable
        try:
            check_sendable(media_files=body.media_files, price=body.price,
                           previews=body.previews, locked_text=body.locked_text)
        except FanslyAPIError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        from employees import resolve_outbound_employee_id
        from automation_executor import enqueue_job
        employee_id = await resolve_outbound_employee_id(request, account_id)
        run_at = _run_at_naive_utc(body.scheduled_date)
        payload = {
            "fan_id": chat_id,
            "text": body.text,
            "price": body.price,
            "locked_text": body.locked_text,
            "media_files": body.media_files,
            "previews": body.previews,
            "tagged_users": body.tagged_users,
            "giphy_id": None,
            "sent_by_employee_id": employee_id,
            "send_purpose": "manual",
        }
        job_id = await enqueue_job(
            account_id, "scheduled_send",
            payload=payload, run_at=run_at, created_by_employee_id=employee_id,
        )
        return {"job_id": job_id, "fan_id": chat_id, "run_at": run_at.isoformat() + "Z"}
    return await asyncio.to_thread(_proxy, lambda: _get_client().schedule_message(
        chat_id, text=body.text, scheduled_date=body.scheduled_date,
        price=body.price, locked_text=body.locked_text, media_files=body.media_files,
        previews=body.previews,
        tagged_users=body.tagged_users,
        auto_tag=False,   # same composer, same operator — see of_send_message
    ))


# ── Near-term scheduled sends (executor-fired, survive reload, cross-chatter) ──
#
# These replace the old in-browser local-wait timer. A row in `scheduled_jobs`
# (kind="scheduled_send") is enqueued here; the executor's `scheduled_send`
# automation fires it at `run_at`. Distinct from the OF-queue path above
# (`/messages/scheduled`), which is for longer delays and lives on OF's servers.

def _run_at_naive_utc(iso: str) -> datetime:
    """Parse an ISO fire-time to a NAIVE-UTC datetime — the form the rest of the
    schema uses (everything compares against `datetime.utcnow()`).

    NB: we parse with `fromisoformat`, NOT event_transcoder._parse_iso — the
    latter *strips* the offset (treats the wall-clock as-is) rather than
    converting it, so a `+02:00` time would fire 2h late. The UI only sends `Z`
    strings, but normalizing correctly costs nothing and is robust to other
    callers."""
    from datetime import timezone
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"invalid run_at: {iso!r}")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


@app.post("/api/of/v2/scheduled-sends")
async def create_scheduled_send(request: Request, body: _ScheduledSendBody = Body(...)):
    """Enqueue a near-term deferred 1:1 send. Resolves the scheduling chatter's
    employee id so the eventual bubble is attributed to them, then inserts a
    `scheduled_jobs` row the executor will fire at `run_at`."""
    account_id = _resolve_account_id(request)
    # Same at-schedule-time rejection the >15-min Fansly path makes: the shim's
    # send_message refuses PPV price and media attachments, and it does so at
    # FIRE time — minutes later, into a retry loop the chatter never sees. Fail
    # here, while they are still looking at the composer.
    if account_registry.get_platform(account_id) == "fansly" and (
            body.media_files or body.price > 0):
        raise HTTPException(
            status_code=400,
            detail="Fansly scheduled sends support text and GIFs for now — "
                   "PPV price and media attachments aren't wired on the Fansly "
                   "path yet.",
        )
    from employees import resolve_outbound_employee_id
    from automation_executor import enqueue_job

    employee_id = await resolve_outbound_employee_id(request, account_id)
    run_at = _run_at_naive_utc(body.run_at)
    payload = {
        "fan_id": body.fan_id,
        "text": body.text,
        "price": body.price,
        "locked_text": body.locked_text,
        "media_files": body.media_files,
        "previews": body.previews,
        "tagged_users": body.tagged_users,
        "giphy_id": body.giphy_id,
        "sent_by_employee_id": employee_id,
        # Typed stamp: a HUMAN scheduled this. The audience at-fire recheck
        # bypasses manual sends; automation-enqueued scheduled_send jobs don't
        # carry it and get re-checked against the fence at fire time.
        "send_purpose": "manual",
    }
    job_id = await enqueue_job(
        account_id, "scheduled_send",
        payload=payload, run_at=run_at, created_by_employee_id=employee_id,
    )
    return {"job_id": job_id, "fan_id": body.fan_id, "run_at": run_at.isoformat() + "Z"}


@app.get("/api/of/v2/scheduled-sends")
async def list_scheduled_sends(request: Request, fan_id: int | None = None):
    """List this account's pending/running near-term sends — optionally scoped to
    one fan. The chat thread renders these as ghost bubbles; every chatter on the
    account sees the same rows."""
    from db.engine import get_session
    from db.models import ScheduledJob
    from sqlalchemy import select

    account_id = _resolve_account_id(request)
    async with get_session() as s:
        rows = (await s.execute(
            select(ScheduledJob)
            .where(
                ScheduledJob.account_id == account_id,
                ScheduledJob.kind == "scheduled_send",
                ScheduledJob.status.in_(("pending", "running")),
            )
            .order_by(ScheduledJob.run_at)
        )).scalars().all()

    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            p = json.loads(r.payload_json or "{}")
        except Exception:
            p = {}
        row_fan = int(p.get("fan_id") or 0)
        if not row_fan or (fan_id is not None and row_fan != fan_id):
            continue
        out.append({
            "job_id": r.id,
            "kind": "scheduled_send",
            "fan_id": row_fan,
            "run_at": (r.run_at.isoformat() + "Z") if r.run_at else None,
            "status": r.status,
            "text": p.get("text") or "",
            "price": p.get("price") or 0,
            "locked_text": bool(p.get("locked_text")),
            "media_count": len(p.get("media_files") or []),
            "giphy_id": p.get("giphy_id"),
        })
    return {"list": out}


@app.delete("/api/of/v2/scheduled-sends/{job_id}")
async def cancel_scheduled_send(request: Request, job_id: int):
    """Cancel a near-term scheduled send before it fires. Atomic: only a still
    `pending` job is cancellable — once the executor has CLAIMED it (`running`)
    it's already going out, so we report it as too-late rather than lying."""
    from db.engine import get_session
    from db.models import ScheduledJob
    from sqlalchemy import update
    import events

    account_id = _resolve_account_id(request)
    async with get_session() as s:
        res = await s.execute(
            update(ScheduledJob)
            .where(
                ScheduledJob.id == job_id,
                ScheduledJob.account_id == account_id,
                ScheduledJob.kind == "scheduled_send",
                ScheduledJob.status == "pending",
            )
            .values(status="cancelled")
        )
        if res.rowcount:
            # The other tabs on this Creator drop the ghost bubble now.
            events.on_commit(s, "scheduled_send_changed", account_id=account_id, job_id=job_id)
    cancelled = bool(res.rowcount)
    if not cancelled:
        return {"cancelled": False, "reason": "not_pending"}
    return {"cancelled": True, "job_id": job_id}


class _MassScheduleBody(BaseModel):
    text: str
    # Optional — omit for an immediate broadcast. /messages/queue is OF's
    # send-now path when no scheduledDate is in the body; with one it
    # becomes the scheduled-send path.
    scheduled_date: str | None = Field(
        None, description="ISO 8601 (e.g. 2026-06-01T18:00:00+00:00); omit to send now",
    )
    # OF's "Save for later": queued with no date (isPublishedWithPeriod: 1),
    # never sent now. Takes the scheduled branch below.
    save_for_later: bool = False
    user_ids: list[int] = Field(default_factory=list)
    user_lists: list[str] = Field(default_factory=list, description="List ids or built-in names like 'fans'")
    excluded_users: list[int] = Field(default_factory=list)
    excluded_user_lists: list[str] = Field(default_factory=list, description="List ids/names to exclude from the audience")
    price: float = Field(0, ge=0)
    locked_text: bool = False
    # int = existing vault id; dict = fresh-upload claim payload from
    # the /upload endpoint's `send_with`. Same shape send_message accepts.
    media_files: list[int | dict] = Field(default_factory=list)
    # Vault ids that ride along unlocked when price > 0. Must be a subset
    # of `media_files`'s numeric ids.
    previews: list[int] = Field(default_factory=list)
    # OF user ids of creators to @-tag in the broadcast (sent as `userTags`).
    # Same picker contract as direct chat sends — ids must come from
    # /api/of/v2/posts/tagged-friend-users or OF will 400.
    tagged_users: list[int] = Field(default_factory=list)
    # Giphy id — forwarded as top-level `giphyId` to OF. Multi-GIF mass
    # broadcasts fan out client-side as separate calls.
    giphy_id: str | None = Field(
        None,
        description="Giphy GIF id forwarded to OF as top-level `giphyId`.",
    )
    # Native audience filter — forwarded to OF as the top-level `filters` object.
    # `online_only=True` (or `filters={"online": 1}`) targets fans currently
    # online at send time. Combine with `user_lists=["fans"]` to blast every
    # online fan. Mirrors OF web's online broadcast.
    online_only: bool = False
    filters: dict | None = None
    # DB-sourced audience: inject the fan ids we exchanged a message with in the
    # last `recent_chat_hours` (newest first, capped to `recent_chat_limit`).
    # Resolved server-side from the local `messages` table and MERGED into
    # `user_ids` — no OF call needed. Bots + blacklisted fans are dropped.
    recent_chat_hours: float | None = Field(
        None, gt=0, description="Target fans chatted with in the last N hours (from local DB)",
    )
    recent_chat_limit: int | None = Field(
        None, gt=0, description="Cap the recent-chat audience to the N most-recent fans",
    )
    # DB-sourced EXCLUSIONS — drop fans from the audience based on recent
    # activity (resolved server-side, merged into `excluded_users`).
    #   exclude_replied_hours: fans we sent an OUTBOUND message to in the last
    #     N hours (i.e. "already replied") — don't re-blast them.
    #   exclude_inbound_hours: fans who messaged us INBOUND in the last N hours
    #     — the extra "2h inbound" filter.
    exclude_replied_hours: float | None = Field(
        None, gt=0, description="Exclude fans we replied to (outbound) in the last N hours",
    )
    exclude_inbound_hours: float | None = Field(
        None, gt=0, description="Exclude fans who messaged us (inbound) in the last N hours",
    )
    # Target fans with UNREAD messages (the OF "Unread" inbox tab), capped at
    # `unread_limit`. Resolved via OF `GET /chats?filter=unread` and MERGED into
    # `user_ids`. Great for "reply blast" to fans waiting on us.
    unread_limit: int | None = Field(
        None, gt=0, le=1000, description="Target up to N fans with unread messages",
    )
    # Auto-unsend: N hours after an immediate broadcast goes out, unsend it from
    # every recipient. OF has no native timer, so we enqueue a one-shot
    # `unsend_messages` job at send_time + N hours (the A12 automation calls
    # DELETE /messages/queue/{id} — the forever-window mass unsend). Ignored for
    # scheduled sends (unsending a future send is just a cancel).
    unsend_after_hours: float | None = Field(
        None, gt=0, le=8760, description="Auto-unsend the broadcast N hours after it sends",
    )
    # Funnel anchor — stamps the minted `mass_runs` row with this
    # `mass_message_funnels.id` so the reply_mass_funnel automation discovers
    # repliers and walks the funnel's reply/PPV steps. Send-now only (a
    # scheduled run is closed by OF later, so it never reaches 'ok' here).
    funnel_id: int | None = Field(
        None, gt=0, description="mass_message_funnels.id to walk repliers through",
    )
    # Online-fans thresholds (Infloww's Total spent / Tipped over / Subscribed
    # over / Expired over), resolved from our own records by
    # `audiences.threshold_fan_ids`. Any one set turns the audience into the
    # explicit ids of the picked lists' members and `user_ids` that clear them
    # all (online now, with `online_only`), at most THRESHOLD_IDS_MAX — the
    # lists and the OF online filter drop out. A list OF won't page → 422.
    min_total_spent: float | None = Field(None, gt=0, description="Only fans who spent at least $N")
    min_tipped: float | None = Field(None, gt=0, description="Only fans who tipped at least $N")
    subscribed_over_days: float | None = Field(None, gt=0, description="Only fans subscribed N+ days")
    expired_over_days: float | None = Field(None, gt=0, description="Only fans expired N+ days ago")

    def has_thresholds(self) -> bool:
        return bool(self.min_total_spent or self.min_tipped
                    or self.subscribed_over_days or self.expired_over_days)


@app.post("/api/of/v2/messages/queue")
async def of_send_or_schedule_mass(
    request: Request,
    body: _MassScheduleBody = Body(...),
):
    """POST /messages/queue — broadcasts a mass message to many fans.
    With `scheduled_date` it's a scheduled send; without, it's immediate.
    `user_ids` for explicit fans OR `user_lists` for list-based audience.

    Attribution: mint a `mass_runs` row up front, then walk the
    OF response for per-fan ids and write attribution rows. This is the
    path the Next UI broadcast composer actually hits."""
    # DB-sourced audience: merge "chatted in the last N hours" fan ids into the
    # explicit user_ids before anything else, so mass-run attribution + the OF
    # send both see the full recipient set.
    # R1/R2: also resolve whenever a funnel_id is present (even with no other
    # audience knob) — else a plain funnel launch skips the resolver entirely and
    # never dedups answerers (the composer used to gate only on recent/exclude/
    # unread). exclude_funnel_responders drops fans who already answered THIS
    # funnel; for explicit ids they leave user_ids, for OF-native list/online
    # audiences they ride the Auto_Exclude list path below (excluded_users).
    _skipped_answered: list[int] = []
    _answered_total = 0
    # Run UNCONDITIONALLY (not just when an audience knob is set): the resolver
    # ALSO applies the always-on MASSdmEXCLUDE opt-out list + not-yet-fired
    # queued-send dedup, so a plain composer blast still skips an excluded /
    # already-queued fan. The client is only needed for the OF "Unread" lookup,
    # so build it only when unread_limit is set.
    _thresholds = body.has_thresholds()
    _online_now = bool(body.online_only or (body.filters or {}).get("online"))
    if _thresholds and _online_now:
        # The thresholded online audience is OF's online list read NOW, so it
        # can't wait for a schedule; and that list is active subscribers only,
        # so nobody on it has expired.
        if body.scheduled_date or body.save_for_later:
            raise HTTPException(422, "Thresholds with 'Only fans online right now' resolve "
                                     "the online list at send time: send now, or turn "
                                     "off online-only to schedule.")
        if body.expired_over_days:
            raise HTTPException(422, "OnlyFans' online list holds active subscribers only, "
                                     "so 'Expired over' can't combine with online-only.")
    if True:
        from audiences import (MASSDMEXCLUDE_LIST, THRESHOLD_IDS_MAX,
                               AudienceUnknown, resolve_mass_audience)
        _aid = _resolve_account_id(request)
        try:
            resolved = await resolve_mass_audience(
                _aid,
                included_users=body.user_ids,
                excluded_users=body.excluded_users,
                recent_chat_hours=body.recent_chat_hours,
                recent_chat_limit=body.recent_chat_limit,
                exclude_replied_hours=body.exclude_replied_hours,
                exclude_inbound_hours=body.exclude_inbound_hours,
                exclude_funnel_responders=body.funnel_id,  # R1/R2 answered-once dedup
                unread_limit=body.unread_limit,
                # Every blast, priced or not, skips the MASSdmEXCLUDE opt-out list.
                exclude_list_name=MASSDMEXCLUDE_LIST,
                min_spent_cents=round(body.min_total_spent * 100) if body.min_total_spent else None,
                min_tips_cents=round(body.min_tipped * 100) if body.min_tipped else None,
                subscribed_over_days=body.subscribed_over_days,
                expired_over_days=body.expired_over_days,
                online_now=_thresholds and _online_now,
                # Read only by a thresholded send: the lists it narrows, and the
                # excluded lists it subtracts (OF's excludedLists is verified on
                # list audiences only, and this send becomes explicit userIds).
                user_lists=body.user_lists if _thresholds else None,
                excluded_user_lists=body.excluded_user_lists if _thresholds else None,
                client=_get_client() if (body.unread_limit or _thresholds) else None,
            )
        except AudienceUnknown as e:
            raise HTTPException(422, str(e))
        body.user_ids = resolved["included_users"]
        body.excluded_users = resolved["excluded_users"]
        if _thresholds:
            # The resolved ids ARE the audience: OF unions userLists with
            # userIds, so a list left in would re-add every fan below the bar.
            if not body.user_ids:
                raise HTTPException(422, "No fan clears these thresholds right now "
                                         "— nothing was sent.")
            if len(body.user_ids) > THRESHOLD_IDS_MAX:
                raise HTTPException(422, f"{len(body.user_ids)} fans clear these thresholds; "
                                         f"one send takes at most {THRESHOLD_IDS_MAX}. Raise a "
                                         "threshold or pick a smaller list — nothing was sent.")
            body.user_lists = []
            body.online_only = False
            body.filters = None
        _skipped_answered = resolved.get("skipped_funnel_responders") or []
        _answered_total = int(resolved.get("funnel_responders_total") or 0)
    # Excluded ids must leave `user_ids` HERE too — of_client subtracts them
    # from the wire `userIds` (OF has no per-user exclude field), so if we left
    # them in `body.user_ids` the mass_runs recipient_count + the optimistic
    # `messages` rows _close_mass_run writes would be PHANTOM (rows for fans OF
    # never messaged), and those outbound rows would then poison the contact
    # guard. Mirror the of_client subtraction so our record matches the send.
    if body.excluded_users and body.user_ids:
        _excl = {int(x) for x in body.excluded_users}
        body.user_ids = [u for u in body.user_ids if int(u) not in _excl]
    # OF cannot exclude individual ids from a list/online audience — the
    # `excludedUsers` body field doesn't exist (verified live 2026-06-12: it was
    # silently dropped and excluded fans got the blast). Mirror the ids into the
    # per-account Auto_Exclude OF list, which OF honors via `excludedLists`.
    # Explicit `user_ids` need no list — they're already stripped just above.
    # Done under the shared per-account broadcast lock so a concurrent
    # automation send can't rewrite the list mid-sync. Errors bubble up (500) —
    # a broadcast without its guard is the bug itself. (Known minor gap: the
    # lock is released before the send below, so a manual composer blast firing
    # in the same instant as an automation tick on the SAME account can race on
    # Auto_Exclude membership; automation<->automation sends hold it through.)
    if body.excluded_users and (body.user_lists or body.online_only or body.filters):
        from audiences import broadcast_lock, ensure_exclude_list
        _aid2 = _resolve_account_id(request)
        async with broadcast_lock(_aid2):
            auto_lid = await ensure_exclude_list(
                _aid2, body.excluded_users, client=_get_client())
        if auto_lid is not None and auto_lid not in (body.excluded_user_lists or []):
            body.excluded_user_lists = [*(body.excluded_user_lists or []), auto_lid]
    account_id, employee_id, mass_run_id = await _open_mass_run(
        request,
        user_lists=body.user_lists,
        included_users=body.user_ids,
        excluded_users=body.excluded_users,
        excluded_user_lists=body.excluded_user_lists,
        funnel_id=body.funnel_id,
    )
    # A funnel-linked send only works if the reply-walker runs on this account —
    # without it the opener goes out and no reply-check ever fires. Best-effort:
    # never blocks the broadcast.
    if body.funnel_id and mass_run_id is not None:
        try:
            from funnels_api import ensure_funnel_walker
            await ensure_funnel_walker(account_id)
        except Exception:
            log.exception("funnel walker ensure failed (account=%s) — enable "
                          "Reply-walking in My Automations > Auto Funnel", account_id)
    client = _get_client()
    # OF throttles consecutive broadcast POSTs with a 400 "Please allow 10
    # seconds". Every automation absorbs that already (of_write_paced pre-spaces
    # >=11s, of_write_with_retry re-tries once after an async pause); this
    # handler — the one the Next composer hits, with a human watching — did not.
    # A blast landing within ~10s of an automation's blast failed AFTER the
    # audience resolve, the exclude sync and the mass_runs mint, and the manual
    # resubmit re-paid all of it.
    #
    # Retry only, no pacing: pacing would tax the common un-throttled case and
    # this is the interactive path. Safe to re-send because the retry fires only
    # on OF's rate-limit 400 — a POST OF refused, so nothing was created. Every
    # other error still surfaces unchanged. Both branches are wrapped: scheduled
    # and immediate are the same throttled endpoint. The function-local import
    # mirrors this module's other automation_executor uses (that module must not
    # import server).
    from automation_executor import of_write_with_retry
    if body.scheduled_date or body.save_for_later:
        # Scheduled sends don't produce per-fan rows now — OF fires the
        # actual messages later. The mass_run_id is stamped on `mass_runs`
        # so the WS-pump reconciler (TODO inside _close_mass_run) can match
        # the eventual arrivals.
        result = await of_write_with_retry(
            lambda: _proxy(
                lambda: client.schedule_mass_message(
                    text=body.text, scheduled_date=body.scheduled_date,
                    save_for_later=body.save_for_later and not body.scheduled_date,
                    user_ids=body.user_ids, user_lists=body.user_lists,
                    excluded_users=body.excluded_users,
                    excluded_user_lists=body.excluded_user_lists,
                    price=body.price,
                    locked_text=body.locked_text, media_files=body.media_files,
                    previews=body.previews,
                    tagged_users=body.tagged_users,
                    giphy_id=body.giphy_id,
                    filters=body.filters,
                    online_only=body.online_only,
                ),
            ),
        )
    else:
        result = await of_write_with_retry(
            lambda: _proxy(
                lambda: client.send_mass_message(
                    text=body.text,
                    user_lists=body.user_lists,
                    included_users=body.user_ids,
                    excluded_users=body.excluded_users,
                    excluded_user_lists=body.excluded_user_lists,
                    price=body.price,
                    locked_text=body.locked_text,
                    media_files=body.media_files,
                    previews=body.previews,
                    tagged_users=body.tagged_users,
                    giphy_id=body.giphy_id,
                    filters=body.filters,
                    online_only=body.online_only,
                ),
            ),
        )
        await _close_mass_run(
            account_id=account_id,
            employee_id=employee_id,
            mass_run_id=mass_run_id,
            text=body.text,
            price=body.price,
            result=result,
            recipient_ids=body.user_ids,
            audience={"user_lists": body.user_lists,
                      "excluded_users": body.excluded_users,
                      "excluded_user_lists": body.excluded_user_lists,
                      "filters": body.filters,
                      "online_only": body.online_only},
            # This branch is the IMMEDIATE one (the scheduled branch above never
            # calls us at all — see §8 of plans/blast-splice, that run stays
            # 'running' forever and is its own bug), so this is always False.
            # Passed explicitly anyway: the day the scheduled branch learns to
            # close itself, the flag is already where it belongs.
            scheduled=False,
        )
        # Auto-unsend timer: schedule a one-shot `unsend_messages` job for the
        # forever-window mass unsend (DELETE /messages/queue/{id}) at send_time
        # + N hours. Picked up by the automation supervisor when due.
        queue_id = result.get("id") if isinstance(result, dict) else None
        if body.unsend_after_hours and queue_id:
            from automation_executor import enqueue_job
            run_at = datetime.utcnow() + timedelta(hours=body.unsend_after_hours)
            job_id = await enqueue_job(
                account_id, "unsend_messages",
                payload={"targets": [{"queue_id": int(queue_id),
                                      "mass_run_id": mass_run_id}]},
                run_at=run_at,
                created_by_employee_id=employee_id,
            )
            if isinstance(result, dict):
                result["_auto_unsend_at"] = run_at.isoformat() + "Z"
                result["_auto_unsend_job_id"] = job_id
    if mass_run_id is not None and isinstance(result, dict):
        result.setdefault("_mass_run_id", mass_run_id)
    if isinstance(result, dict) and (_answered_total or _skipped_answered):
        # R1/R2 surfacing: how many known answerers of this funnel were excluded
        # from the send (total), and the precise ids removed from an explicit-id
        # audience. The UI prints "N already answered — skipped".
        result["_skipped_already_answered"] = _answered_total or len(_skipped_answered)
        result["_skipped_already_answered_ids"] = _skipped_answered
    return result

class _EditQueuedMessageBody(BaseModel):
    """PUT /api/of/v2/messages/queue/{id}: a queued mass message saved in
    place. A schedule (`scheduled_date`) or `save_for_later` is required, so
    an edit can never send the message at once (that is Message now)."""
    text: str
    scheduled_date: str | None = None
    save_for_later: bool = False
    user_ids: list[int] = Field(default_factory=list)
    user_lists: list[str] = Field(default_factory=list)
    excluded_user_lists: list[str] = Field(default_factory=list)
    price: float = Field(0, ge=0)
    locked_text: bool = False
    media_files: list[int | dict] = Field(default_factory=list)
    previews: list[int] = Field(default_factory=list)
    tagged_users: list[int] = Field(default_factory=list)


@app.post("/api/of/v2/messages/queue/later")
async def of_save_mass_for_later(request: Request, body: _MassScheduleBody = Body(...)):
    """A mass message saved for later (OF's Save for later: queued with no
    date). POST /messages/queue with `save_for_later` does the same; this route
    is what OF Manager calls, so a relay that predates `save_for_later` answers
    405 instead of ignoring the field and sending the message at once."""
    body.save_for_later = True
    body.scheduled_date = None
    return await of_send_or_schedule_mass(request, body)


@app.get("/api/of/v2/messages/queue/{queue_id:int}")
def of_queued_message(queue_id: int):
    """One queued mass message (scheduled or saved for later), as OF's Edit
    message loads it: GET /messages/queue/{id}?format=scheduled."""
    return _proxy(lambda: _get_client().queued_message(queue_id))


@app.put("/api/of/v2/messages/queue/{queue_id:int}")
def of_edit_queued_message(queue_id: int, body: _EditQueuedMessageBody = Body(...)):
    """Save a queued mass message in place (OF Manager's Edit message, from the
    Queue): OF's PUT /messages/queue/{id}. A new `scheduled_date` reschedules."""
    if not body.scheduled_date and not body.save_for_later:
        raise HTTPException(422, "an edited queued message needs scheduled_date or save_for_later")
    return _proxy(lambda: _get_client().edit_queued_message(
        queue_id, text=body.text, scheduled_date=body.scheduled_date,
        save_for_later=body.save_for_later and not body.scheduled_date,
        user_ids=body.user_ids, user_lists=body.user_lists,
        excluded_user_lists=body.excluded_user_lists, price=body.price,
        locked_text=body.locked_text, media_files=body.media_files,
        previews=body.previews, tagged_users=body.tagged_users,
    ))


@app.delete("/api/of/v2/messages/queue/{queue_id}")
async def of_cancel_scheduled(request: Request, queue_id: int):
    """Cancel a previously scheduled message or unsend a mass broadcast.

    Both code paths share OF's wire endpoint:
      • scheduled (future) → cancel before it fires
      • mass broadcast (past) → unsend from EVERY recipient (no window)

    On success we flip `is_canceled=True` in the local mass-broadcast
    cache so the Settings → Mass messages list reflects the new state
    without waiting for the next refresh.

    On a Fansly Creator this is ALSO the scheduled-POST cancel: the Fansly
    shim's `cancel_scheduled` is Fansly's `POST /post/scheduled/{id}/cancel`,
    so `queue_id` is a post id from `GET /api/of/v2/schedules` (the Fansly
    Manager's Scheduled Posts page, roadmap 8.1). The bookkeeping below then
    finds nothing to mark. Locked by test_fansly_cancel_scheduled_route.py."""
    import mass_broadcast_cache as cache
    resp = await asyncio.to_thread(_proxy, lambda: _get_client().cancel_scheduled(queue_id))
    try:
        account_id = _resolve_account_id(request)
    except Exception as e:  # authed route — unreachable in practice
        log.warning("cancel bookkeeping skipped, account unresolved: %s", e)
        return resp

    # Three independent bits of local bookkeeping. OF has already canceled the
    # queue, so none of them may 500 the caller — and none may be skipped
    # because an earlier one failed, hence one guard each.
    try:
        await cache.mark_canceled(account_id, queue_id)
    except Exception as e:
        log.warning("mass_broadcast_cache mark_canceled failed: %s", e)
    try:
        # #R4: a manual mass unsend also closes funnel discovery for that run —
        # stop enrolling NEW repliers off the deleted mass (the walker keeps
        # advancing already-engaged fans until a purchase halts them).
        from audiences import close_funnel_discovery_for_queue
        await close_funnel_discovery_for_queue(account_id, queue_id=queue_id)
    except Exception as e:
        log.warning("close_funnel_discovery failed queue_id=%s: %s", queue_id, e)
    try:
        # Same mirror flip as the per-chat unsend above, one broadcast wide:
        # every recipient's mirror row would otherwise re-seed as an empty
        # bubble on their next chat open. Purchasers and funnel follow-ups
        # are spared inside mark_queue_unsent — they stay live on OF.
        from messages import mark_queue_unsent
        await mark_queue_unsent(account_id, queue_id)
    except Exception as e:
        log.warning("queue unsend mirror flip failed queue_id=%s: %s", queue_id, e)
    return resp

# Posts writes ------------------------------------------------------

async def _refuse_paid_post_on_paid_page(request: Request, price: float | int | None) -> None:
    """A priced feed post needs a FREE page — a subscription page has no
    paid-post lane on OF (service/account_page.py). Refused here, at the one
    route the composer and its all-models fan-out both go through, so the
    operator gets the reason instead of an opaque OF rejection."""
    if not price or float(price) <= 0:
        return
    if await account_page.is_paid_page(_resolve_account_id(request)):
        raise HTTPException(
            409, "this page charges for a subscription — OF has no paid-post lane "
                 "for it. Post it free, or sell it as a PPV in DMs.")


@app.post("/api/of/v2/posts")
async def of_create_post(request: Request, body: _CreatePostBody = Body(...)):
    await _refuse_paid_post_on_paid_page(request, body.price)
    return await asyncio.to_thread(_proxy, lambda: _get_client().create_post(
        text=body.text, media_files=body.media_files,
        price=body.price, previews=body.previews, posted_at=body.posted_at,
        save_for_later=body.save_for_later, expire_days=body.expire_days,
        fund_raising_target=body.fund_raising_target,
        fund_raising_presets=body.fund_raising_presets,
        voting_type=body.voting_type, voting_options=body.voting_options,
        voting_due=body.voting_due, voting_correct_index=body.voting_correct_index,
        label_ids=body.label_ids,
        tagged_users=body.tagged_users,
        giphy_id=body.giphy_id,
    ))

@app.put("/api/of/v2/posts/{post_id}")
async def of_edit_post(post_id: int, request: Request, body: _EditPostBody = Body(...)):
    await _refuse_paid_post_on_paid_page(request, body.price)
    return await asyncio.to_thread(_proxy, lambda: _get_client().edit_post(
        post_id, text=body.text, price=body.price, media_files=body.media_files,
    ))

@app.put("/api/of/v2/queue/posts/{post_id}")
async def of_save_queued_post(post_id: int, request: Request, body: _CreatePostBody = Body(...)):
    """Save a queued (scheduled or saved-for-later) post in place: OF
    Manager's Edit post, from the Queue. The create body (_CreatePostBody),
    sent whole as OF's PUT /posts/{id}, as OF's composer does; a new
    `posted_at` reschedules, `save_for_later` keeps it saved for later.
    A route of its own, not PUT /posts/{id}: a relay without it answers 404
    instead of sending a partial body that drops the schedule."""
    await _refuse_paid_post_on_paid_page(request, body.price)
    return await asyncio.to_thread(_proxy, lambda: _get_client().save_queued_post(
        post_id, body.text, tagged_users=body.tagged_users,
        media_files=body.media_files, price=body.price, previews=body.previews,
        posted_at=body.posted_at, save_for_later=body.save_for_later,
        expire_days=body.expire_days, fund_raising_target=body.fund_raising_target,
        fund_raising_presets=body.fund_raising_presets,
        voting_type=body.voting_type, voting_options=body.voting_options,
        voting_due=body.voting_due, voting_correct_index=body.voting_correct_index,
        label_ids=body.label_ids,
    ))

@app.delete("/api/of/v2/posts/{post_id}")
def of_delete_post(post_id: int):
    return _proxy(lambda: _get_client().delete_post(post_id))

@app.post("/api/of/v2/posts/{post_id}/like")
def of_like_post(post_id: int, author_id: int | None = Query(
        None, description="The post's author (another creator's post); default: me")):
    return _proxy(lambda: _get_client().like_post(post_id, author_id))

@app.delete("/api/of/v2/posts/{post_id}/like")
def of_unlike_post(post_id: int, author_id: int | None = Query(
        None, description="The post's author (another creator's post); default: me")):
    return _proxy(lambda: _get_client().unlike_post(post_id, author_id))

@app.post("/api/of/v2/posts/{post_id}/comments")
def of_comment_post(post_id: int, body: _TextBody = Body(...)):
    return _proxy(lambda: _get_client().comment_on_post(post_id, body.text))

@app.post("/api/of/v2/posts/{post_id}/pin")
def of_pin_post(post_id: int):
    return _proxy(lambda: _get_client().pin_post(post_id))

@app.delete("/api/of/v2/posts/{post_id}/pin")
def of_unpin_post(post_id: int):
    return _proxy(lambda: _get_client().unpin_post(post_id))

@app.post("/api/of/v2/posts/{post_id}/archive")
def of_archive_post(post_id: int):
    """Archive one of my posts (OF's post menu "Archive post")."""
    return _proxy(lambda: _get_client().archive_post(post_id))

# List writes -------------------------------------------------------

@app.post("/api/of/v2/lists")
def of_create_list(body: _NameBody = Body(...)):
    out = _proxy(lambda: _get_client().create_list(body.name))
    _invalidate_chat_folders()
    return out

# list_id is typed `str` (not `int`) so built-in lists like 'fans', 'recent',
# 'bookmarks' work alongside custom numeric ids. OF's API accepts both.

@app.patch("/api/of/v2/lists/{list_id}")
def of_rename_list(list_id: ListId, body: _NameBody = Body(...)):
    """Rename a list. OF uses PATCH (not PUT) — verified live."""
    out = _proxy(lambda: _get_client().rename_list(list_id, body.name))
    _invalidate_chat_folders()
    return out

@app.delete("/api/of/v2/lists/{list_id}")
def of_delete_list(list_id: ListId):
    out = _proxy(lambda: _get_client().delete_list(list_id))
    _invalidate_chat_folders()
    return out

@app.post("/api/of/v2/lists/{list_id}/users/{user_id}")
def of_add_user_to_list(list_id: ListId, user_id: int):
    out = _proxy(lambda: _get_client().add_user_to_list(list_id, user_id))
    _invalidate_chat_folders()  # usersCount rides in the folders payload
    return out

@app.delete("/api/of/v2/lists/{list_id}/users/{user_id}")
def of_remove_user_from_list(list_id: ListId, user_id: int):
    out = _proxy(lambda: _get_client().remove_user_from_list(list_id, user_id))
    _invalidate_chat_folders()  # usersCount rides in the folders payload
    return out

@app.post("/api/of/v2/lists/users")
def of_add_users_to_lists(body: dict[str, list[int]] = Body(...)):
    """Bulk add: `{"<listId>": [userId, ...]}`, passed to OF's POST /lists/users as is."""
    if not body or not all(body.values()):
        raise HTTPException(status_code=422, detail="each list needs at least one user id")
    out = _proxy(lambda: _get_client().add_users_to_lists(body))
    _invalidate_chat_folders()  # usersCount rides in the folders payload
    return out

@app.delete("/api/of/v2/lists/{list_id}/users")
def of_clear_list(list_id: ListId):
    """OF's "Clear list": every user leaves the list (the list stays)."""
    out = _proxy(lambda: _get_client().clear_list(list_id))
    _invalidate_chat_folders()  # usersCount rides in the folders payload
    return out

# Labels writes -----------------------------------------------------

@app.post("/api/of/v2/labels")
def of_create_label(body: _NameBody = Body(...)):
    """A new post label (New post's NEW LABEL); OF answers with the label."""
    return _proxy(lambda: _get_client().create_label(body.name))

class _LabelSortBody(BaseModel):
    sort: str = Field(..., pattern="^(default|recent|name|posts|custom)$")
    order: str = Field(..., pattern="^(asc|desc)$")

@app.post("/api/of/v2/labels/sort")
def of_sort_labels(body: _LabelSortBody = Body(...)):
    """ADD LABELS' Sort menu: OF keeps the order (POST /labels/sort {sort, order})."""
    return _proxy(lambda: _get_client().sort_labels(sort=body.sort, order=body.order))


# Subscriber tools — FOUND via Playwright UI capture.
# OF uses ONE endpoint PUT /subscriptions/{id} with body containing either
# `notice` (fan note) or `displayName` (custom nickname) — or both.

class _NoteBody(BaseModel):
    note: str

class _CustomNameBody(BaseModel):
    name: str = Field(..., description="Custom display name; empty string clears it")

class _SubscriptionPatchBody(BaseModel):
    notice: str | None = None
    displayName: str | None = None

def _bust_chat_list_cache() -> None:
    """Drop the account's cached `list_chats` so a nickname/note change shows on the
    inbox rail immediately instead of after the 10-min TTL. The chat list's per-fan
    `displayName` is overlaid from the local mirror / OF, so a stale cached page keeps
    rendering the old name (the "<name>/Whale" drawers stayed stale after a gen_info
    rewrite). The drawer's own read (get_user) is live + coalesced, so it needs no bust."""
    try:
        aid = _resolve_account_id(_request_ctx.get())
        relay_cache.invalidate("list_chats", aid)
    except Exception as e:  # noqa: BLE001 — cache bust must never break the write response
        log.warning("relay_cache: chat-list invalidate after subscription write failed: %s", e)

@app.put("/api/of/v2/subscriptions/{user_id}/note")
def of_set_fan_note(user_id: int, body: _NoteBody = Body(...)):
    """Set the creator-side private note on a fan. Send empty string to clear."""
    result = _proxy(lambda: _get_client().set_fan_note(user_id, body.note))
    _bust_chat_list_cache()
    return result

@app.put("/api/of/v2/subscriptions/{user_id}/custom-name")
def of_set_fan_custom_name(user_id: int, body: _CustomNameBody = Body(...)):
    """Set the custom nickname for a fan. Send empty string to clear."""
    result = _proxy(lambda: _get_client().set_fan_custom_name(user_id, body.name))
    _bust_chat_list_cache()
    return result

class _DiscountBody(BaseModel):
    discount: int = Field(..., ge=0, le=60, description="Percent off; 0 clears (OF's Clear sends {discount: 0, period: 1})")
    period: int = Field(..., ge=1, le=12, description="Months the discount lasts")

    @field_validator("discount")
    @classmethod
    def _of_steps(cls, v: int) -> int:
        # OF's PERSONAL_OFFER select (40681): 5..60 by 5; 0 is its Clear.
        if v != 0 and (v < 5 or v % 5):
            raise ValueError("discount must be 0 or 5..60 in steps of 5")
        return v

@app.put("/api/of/v2/subscriptions/{user_id}/discount")
def of_set_subscription_discount(user_id: int, body: _DiscountBody = Body(...)):
    """OF web's "Give user a discount": PUT /subscriptions/{id}/discount {discount, period}."""
    result = _proxy(lambda: _get_client().set_subscription_discount(user_id, body.discount, body.period))
    _bust_chat_list_cache()
    return result

@app.put("/api/of/v2/subscriptions/{user_id}")
def of_update_subscription(user_id: int, body: _SubscriptionPatchBody = Body(...)):
    """Generic update: set notice and/or displayName together in one call."""
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    result = _proxy(lambda: _get_client().update_subscription(user_id, **payload))
    _bust_chat_list_cache()
    return result

# Media upload -----------------------------------------------------
# Three-step flow: dedupe-hash check → POST /upload/signed/create →
# PUT bytes to presigned S3 URL → returns vault media id we can send in
# subsequent /chats/{id}/messages or /posts with mediaFiles=[id].

from fastapi import UploadFile, File, Form


def _upload_basename(raw: str | None) -> str:
    """The browser's file name, safe as one path segment and as part of an S3
    key: the base name of a POSIX or Windows path, every run of characters
    outside `[A-Za-z0-9._-]` replaced by `_`, no leading or trailing `.`/`_`/`-`
    on the stem, at most 200 characters (ASCII, so 200 bytes; filesystems cap
    a name at 255 bytes). A plain ASCII extension of up to 15 characters is
    kept; a name with no stem left is `upload` plus that extension, else
    `upload.bin`. ASCII only, because the key goes into URLs we build without
    encoding (`of_client`: `s3_location`) and keys used to be plain temp names."""
    import os
    import re
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem, ext = os.path.splitext(name)
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,15}", ext):
        stem, ext = name, ""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    if not stem:
        return "upload" + (ext or ".bin")
    return stem[: 200 - len(ext)] + ext


@app.post("/api/of/v2/upload")
async def of_upload_media(file: UploadFile = File(...)):
    """Upload a file to OF's vault. Multipart form field name: `file`.
    Returns {media_id, deduped, size, filename, ...}.
    The returned `media_id` is usable as mediaFiles=[id] in send/post calls
    after OF's transcoder finishes (typically 5-30s for images)."""
    import tempfile, os, shutil
    # Spool to `<tempdir>/<the name, as safe ASCII>`: both clients name the
    # upload after `path.name` (S3 key, convert claim `name`, Fansly
    # `fileName`), so a bare NamedTemporaryFile landed every Composer upload in
    # the vault as `tmpXXXX`.
    tmp_dir = tempfile.mkdtemp(prefix="of-upload-")
    tmp_path = os.path.join(tmp_dir, _upload_basename(file.filename))
    try:
        with open(tmp_path, "wb") as tmp:
            shutil.copyfileobj(file.file, tmp)
        result = _proxy(lambda: _get_client().upload_media(
            tmp_path,
            content_type=file.content_type,
        ))
        # New vault item — every cached page is now potentially stale.
        # Drop the whole account's cache so the next picker open re-fetches.
        try:
            aid = _resolve_account_id(_request_ctx.get())
            await vault_cache.invalidate(aid)
        except Exception as e:  # noqa: BLE001 — cache invalidation must never block the upload response
            log.warning("vault_cache: invalidate-on-upload failed: %s", e)
        return result
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


_VAULT_BATCH_PATH = "/api/of/v2/vault/upload/batch"
# One more file for a run the batch route opened with `keep_open` — the browser
# sends a batch a file at a time so the first is uploading to OnlyFans while
# the rest are still crossing the wire. Capped by the same middleware.
_VAULT_APPEND_PATH = "/api/of/v2/vault/upload/batch/append"
# Ceiling on one import write's wait for the per-account pacer. Generous by
# design — it is a wedge detector, not a policy — but finite: an unbounded wait
# here is an import that never ends, and an import that never ends keeps its
# account marked live, which silences the carrier sweep and its warnings.
_VAULT_WRITE_GATE_TIMEOUT_S = 30 * 60
# Ceiling on the post-import mirror write. The run reports `running` for the
# whole of it (that is the point — see `vault_upload._mirror_landed`), so a
# wedged read here would hold the account's lock open and silence the carrier
# sweep exactly like an unbounded pacer wait would.
#
# It is NOT an order of magnitude above the work, which is what this comment
# used to claim. The honest worst case is `resolve_budget`'s `max_files * 2` —
# 80 landed ids at the default cap, because `_apply_caps` counts only `pending`
# items and a Google Drive memo hit is already `done` before caps run — each one
# a serial OF by-id read. At an OF read timeout in the tens of seconds, 80 of
# those exceed 15 minutes. So the ceiling is a DEADLINE for the whole write and
# the write is chunked underneath it: a slow OF loses the tail rather than the
# whole thing, which matters because a cancelled write is the pre-import grid
# coming back on exactly the largest imports — the symptom the mirror write was
# added to remove.
_VAULT_MIRROR_TIMEOUT_S = 15 * 60
# Ids per hop. Small enough that a chunk's own share of the deadline is a real
# bound, large enough that the loop hop and the commit are amortised.
_VAULT_MIRROR_CHUNK = 10
# Budget for writing an import's per-file details onto the rows that landed. Its
# own, not what the mirror write left over: local DB writes, so seconds, and a
# mirror write that ran out of time must not take the details down with it.
_VAULT_DETAILS_TIMEOUT_S = 60


@_http_hooks.add
async def _cap_vault_batch_body(request: Request, call_next):
    """Refuse an oversized batch upload BEFORE anything is written to disk.

    The per-file cap inside the handler is already too late: FastAPI resolves
    the form before the handler body runs, and Starlette spills every part past
    1 MB into TMPDIR. So 60 GB dragged into the browser filled TMPDIR in full
    and only the SECOND copy — into the staging directory — was ever capped. A
    full disk takes SQLite, and with it the whole relay, down.

    The ceiling is what BOTH filesystems involved can hold: Starlette spills the
    parts into TMPDIR and the handler then copies them into
    `vault_upload.STAGE_ROOT` under the spool, so the batch has to fit twice
    when those are the same device and into the tighter of the two when they are
    not. Measuring only TMPDIR — while the staging copy had been moved to the
    spool — passed batches the spool could not hold (aborting 507 only after the
    whole upload had transferred) and, where /tmp is a small tmpfs, rejected
    every batch citing a volume with nothing to do with it.

    A body with no content-length cannot be measured before it is read, and the
    handler's own cap runs too late, so this route requires one.
    """
    if request.method == "POST" and request.url.path in (_VAULT_BATCH_PATH,
                                                         _VAULT_APPEND_PATH):
        try:
            declared = int(request.headers.get("content-length") or 0)
        except ValueError:
            declared = 0
        if declared <= 0:
            return JSONResponse(
                status_code=411,
                content={"detail": (
                    "this upload needs a content-length — the server has to "
                    "know how big a batch is before it starts writing it to "
                    "disk, and a chunked body cannot be measured until it has "
                    "already landed there. Send it as a normal form upload, or "
                    "(if a proxy in front of the relay re-encodes the body) "
                    "import from Google Drive links instead.")})
        else:
            # .checked() so the staging loop's cap matches the run's — an
            # unchecked Limits still carries the raw two-ceiling pair.
            limits = vault_upload.Limits().checked()
            import shutil as _shutil, tempfile as _tempfile
            tmp_dir = Path(_tempfile.gettempdir())
            stage_root = vault_upload.STAGE_ROOT
            try:
                stage_root.mkdir(parents=True, exist_ok=True)
                same_device = os.stat(tmp_dir).st_dev == os.stat(stage_root).st_dev
                free = min(_shutil.disk_usage(tmp_dir).free,
                           _shutil.disk_usage(stage_root).free)
            except OSError:
                same_device, free = True, _shutil.disk_usage(tmp_dir).free
            # Both copies are live at once: the handler streams out of the
            # spooled part while writing the staged one.
            copies = 2 if same_device else 1
            room = min(max(free - limits.min_free_bytes, 0) // copies,
                       limits.max_files * limits.max_download_bytes)
            if declared > room:
                return JSONResponse(
                    status_code=413,
                    content={"detail": (
                        f"that batch is {declared / 1e9:.1f} GB; this server can "
                        f"stage at most {room / 1e9:.1f} GB right now. Import it "
                        f"in smaller batches, or from Google Drive links, which "
                        f"are fetched one file at a time.")})
    return await call_next(request)


_STAGE_CHUNK = 1024 * 1024
_STAGE_FREE_CHECK_EVERY = 64 * _STAGE_CHUNK


async def _vault_stage_file(f: UploadFile, stage_dir: str,
                            limits: "vault_upload.Limits") -> str:
    """Stream one uploaded part into its own sub-directory of `stage_dir`,
    under its per-file cap and the spool's free-space floor. Returns the staged
    path; raises 413 / the guard's RuntimeError, having removed its own partial.

    Its OWN sub-directory, so the staged file keeps the operator's file name
    (the run names its item after it) while two files of the same name — two
    `IMG_0001.jpg` from two phones — can never be the same path. They used to
    be: the later one truncated the earlier while it was still queued, and its
    failure cleanup deleted the earlier one's bytes."""
    import shutil, tempfile
    vault_upload.guard_space(0, limits, path=Path(stage_dir))
    own = tempfile.mkdtemp(prefix="f-", dir=stage_dir)
    dest = os.path.join(own, os.path.basename(f.filename or "upload") or "upload")
    # The SAME cap rule the Drive path uses: only video ffmpeg can shrink earns
    # the big download ceiling. Applying that ceiling to everything meant a
    # 1.5 GB dragged-in JPEG was streamed to disk in full and then skipped at
    # 200 MB.
    cap = vault_upload.cap_for(f.filename or "", f.content_type, limits)
    written = since_check = 0
    try:
        with open(dest, "wb") as out:
            while chunk := await f.read(_STAGE_CHUNK):
                written += len(chunk)
                since_check += len(chunk)
                if written > cap:
                    raise HTTPException(
                        status_code=413,
                        detail=(f"{f.filename} is over the "
                                f"{cap / 1e6:.0f} MB per-file limit"))
                if since_check >= _STAGE_FREE_CHECK_EVERY:
                    since_check = 0
                    vault_upload.guard_space(0, limits, path=Path(stage_dir))
                out.write(chunk)
    except BaseException:
        shutil.rmtree(own, ignore_errors=True)
        raise
    return dest


def _vault_resolve_fan(client, raw: str) -> dict | None:
    """The fan account the operator typed, as OnlyFans names it:
    `{id, username, name}`, or None when the field was left empty (the carrier
    path). ONE `get_user` — the import card's "check" step and the batch
    route's re-check both come here.

    Only OnlyFans' 404 means "no such account". Anything else (a dead session,
    a 429, a proxy error) is said as itself: calling it "no such account" sent
    operators off to re-type a name that was right."""
    try:
        handle = vault_upload.fan_handle(raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not handle:
        return None
    try:
        user = client.get_user(handle)
    except OFAPIError as e:
        code = e.response.status_code if e.response is not None else None
        if code == 404:
            raise HTTPException(status_code=404,
                                detail=f"No OnlyFans account @{handle} — check the username")
        raise HTTPException(status_code=502,
                            detail=f"Could not look up @{handle}: OnlyFans answered {code}")
    except Exception as e:  # noqa: BLE001 — a transport failure, said as one
        raise HTTPException(status_code=502,
                            detail=f"Could not look up @{handle}: {type(e).__name__}: {e}")
    fid = user.get("id") if isinstance(user, dict) else None
    if not fid:
        raise HTTPException(status_code=404,
                            detail=f"No OnlyFans account @{handle} — check the username")
    return {"id": int(fid), "username": str(user.get("username") or handle),
            "name": str(user.get("name") or "")}


@app.get("/api/of/v2/vault/upload/fan")
async def of_vault_upload_fan(username: str):
    """Who a vault import would send to: `{id, username, name}` for the typed
    OnlyFans username (or `@name`, or profile link). Read-only — one profile
    read. The card shows the answer and sends its `id` and `username` back
    with the import, which re-checks them, so a typo can never quietly pick a
    different fan."""
    aid = _resolve_account_id(_request_ctx.get())
    assert_account_owned(aid)
    client = _get_client()
    fan = await asyncio.to_thread(_vault_resolve_fan, client, username)
    if fan is None:
        raise HTTPException(status_code=400, detail="no username given")
    return fan


@app.post(_VAULT_BATCH_PATH)
async def of_vault_upload_batch(
    request: Request,
    files: list[UploadFile] = File(default=[]),
    drive_links: str = Form(default=""),
    list_id: str = Form(default=""),
    meta: str = Form(default=""),
    fan_username: str = Form(default=""),
    fan_id: str = Form(default=""),
    keep_open: bool = Form(False),
):
    """Start a batch import into the vault. Returns `{run_id}` immediately.

    Accepts either uploaded files (repeated `files` parts) or `drive_links`
    (newline/comma separated public Google Drive file or folder links), or
    both. `list_id` optionally files everything into a vault folder at the end.

    `meta` is a JSON list of per-file details, one per `files` part in order
    (`{hashtags, tag_creators, notes, price_cents, list_id}`); they are written
    onto each file's mirror row once it lands. `fan_username` + `fan_id` send
    each new file to that fan (Infloww's "Link a fan account") instead of a
    carrier post: both are what `GET …/upload/fan` answered, and the username
    is looked up again here and must still be that id — the operator confirmed
    a person, not a string. `keep_open` leaves the run taking more files from
    `POST …/batch/append` until one of those says `last`.

    The run record is created HERE, synchronously, so the response can name the
    run: the worker starts on a thread and a client that polled before it got
    there used to be told `running: false` and never start polling at all.

    The work itself runs in a worker THREAD, not on the event loop: each file is
    a multi-minute sequence of blocking network calls, and the relay serves every
    other account from this same loop. Poll
    `/api/of/v2/vault/upload/status?run_id=…`.
    """
    import asyncio, re, shutil, tempfile, time
    from concurrent.futures import TimeoutError as FuturesTimeout
    # Local import, matching every other automation_executor callsite here —
    # importing it at module scope reintroduces the load cycle its own docstring
    # warns about.
    from automation_executor import of_write_paced
    aid = _resolve_account_id(_request_ctx.get())
    assert_account_owned(aid)
    # BEFORE `begin`, because it can raise. `_get_client` answers 503 for an
    # account whose OnlyFans session is dead — a first-class state here, with
    # its own columns and its own banner on the vault page — and it used to sit
    # below the staging block, outside the `try` that abandons the run. So the
    # 503 left `_live[aid]` claimed, the lockfile on disk and `run.json` saying
    # `running`, with nothing to release any of it: `begin()` refuses on `_live`
    # unconditionally and there is no stall ceiling on the in-process claim, so
    # every later import for that account answered 409 until the relay was
    # restarted. Restoring the session did not help. Asking for the client while
    # we still hold nothing costs one lookup and cannot strand anything.
    client = _get_client()
    # Same rule: resolving the linked fan can fail, so it happens while we
    # still hold nothing. And it must be the fan the operator was SHOWN: the
    # card resolved the name first and sends that id back; a mismatch (a
    # different typo, a renamed account) refuses rather than sending.
    fan = await asyncio.to_thread(_vault_resolve_fan, client, fan_username)
    if fan is not None and str(fan["id"]) != fan_id.strip():
        raise HTTPException(
            status_code=400,
            detail=(f"@{fan['username']} is not the fan account that was checked "
                    f"— check the username again before importing"))
    if fan is None and fan_id.strip():
        raise HTTPException(status_code=400, detail="fan_id without fan_username")
    # Who the fan messages are from, for their outbound rows — the same
    # resolution the chat route uses.
    employee_id = None
    if fan is not None:
        from employees import resolve_outbound_employee_id
        employee_id = await resolve_outbound_employee_id(request, aid)
    metas_in = vault_upload.parse_metas(meta)
    # pace_s=0: the write gate below already spaces every write for this
    # account, so the module's own inter-file sleep would only double it. This
    # is the POLICY, stated here — it used to be inferred from whether a gate
    # was passed at all, which silently disabled pacing for any other gate.
    limits = vault_upload.Limits(pace_s=0).checked()
    # The staging dir, made BEFORE the claim. Making it is not staging a byte,
    # and a full, read-only or permission-broken spool volume then fails here,
    # while we hold nothing — between `begin()` and a handler that abandons,
    # NOTHING may raise (the rule stated above `_get_client()`); out there these
    # two calls once left `_live[aid]` claimed, the lockfile on disk and
    # `run.json` saying `running`, a permanent 409 for the account.
    #
    # Under the spool, not TMPDIR: a SIGKILL between staging and the run leaked
    # the whole staged batch, and nothing in a container ever cleans /tmp. Here
    # the boot sweep owns it.
    try:
        vault_upload.STAGE_ROOT.mkdir(parents=True, exist_ok=True)
        stage_dir = tempfile.mkdtemp(prefix="vault-in-",
                                     dir=str(vault_upload.STAGE_ROOT))
    except Exception as e:  # noqa: BLE001 — a spool that cannot be written
        raise HTTPException(status_code=507, detail=str(e))
    # Claim the account BEFORE staging a single byte. `begin` is the only
    # gate: it takes the in-process claim and the cross-process lockfile
    # together, so it also refuses while a CLI import holds the lock. The
    # cheap pre-check that used to live here read the in-process registry
    # only, which meant a 5 GB drag-in was transferred and written to disk
    # in full before the lock refused it -- and, once a wedged run aged past
    # the stall ceiling, it answered 409 to the very re-run the dashboard was
    # telling the operator to start. The staging dir rides on the run's inbox,
    # so an append finds it — and stops finding it — with the run itself.
    try:
        run_id = vault_upload.begin(aid, list_id=int(list_id) if list_id else None,
                                    fan_id=fan["id"] if fan else None,
                                    keep_open=keep_open, stage_dir=stage_dir)
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise HTTPException(status_code=409, detail=str(e))

    links = [s.strip() for s in re.split(r"[\n,]+", drive_links or "") if s.strip()]
    # Spool uploaded bytes to disk here, inside the request, so the client's
    # connection can close; the run itself must not depend on it staying open.
    #
    # Streamed with a running byte count and a free-space check on the STAGING
    # filesystem, which is usually not the spool's: dragging in 60 GB of raw
    # footage used to fill the disk with no cap consulted at all, and a full disk
    # takes SQLite — and with it the whole relay — down, which is the exact
    # outcome this feature's design notes claim to prevent.
    staged: list[str] = []
    metas: list[dict | None] = []
    try:
        for n, f in enumerate(files or []):
            if not f.filename:
                continue
            staged.append(await _vault_stage_file(f, stage_dir, limits))
            # Indexed by the PART, not by the staged count: a skipped nameless
            # part must not shift every later file onto its neighbour's details.
            metas.append(metas_in[n] if n < len(metas_in) else None)
        if not staged and not links:
            raise HTTPException(status_code=400, detail="no files and no drive links")
    except HTTPException as e:
        shutil.rmtree(stage_dir, ignore_errors=True)
        vault_upload.abandon(run_id, str(e.detail))
        raise
    except Exception as e:  # noqa: BLE001 — a staging failure is the caller's answer
        shutil.rmtree(stage_dir, ignore_errors=True)
        vault_upload.abandon(run_id, str(e))
        raise HTTPException(status_code=507, detail=str(e))

    loop = asyncio.get_running_loop()

    def _hop(coro, timeout: float):
        """Run one coroutine on the relay's loop from this worker thread, bounded.

        The wait is BOUNDED. `fut.result()` with no timeout meant a wedged
        pacer (or a loop that never got round to us) parked the import thread
        for the life of the process, and an import that never ends keeps its
        account marked live — which silences the sweep and the carrier warnings
        for every one of its older runs.

        Bounding the WAIT is not enough, though. `run_coroutine_threadsafe`
        returns a future whose timeout does not touch the coroutine: a write
        parked in its pacing sleep still goes out when its slot arrives — after
        this call has raised past the `finally` that would have deleted a
        carrier, after the run finished, and after the sweep concluded there
        was nothing scheduled and retired the intent. The post then appears with
        nothing on record tracking it, and publishes on its date. Hence the
        cancel, and hence `vault_upload` treating a timeout as "may still have
        happened" (`carrier_write_pending`, `message_write_pending`).
        """
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return fut.result(timeout=timeout)
        except FuturesTimeout:
            fut.cancel()
            raise

    def _write_gate(thunk):
        """Run one OnlyFans write that reaches NO fan — the carrier create, the
        carrier delete, the final foldering call — through the relay's
        per-account write pacer. The fan send has its own gate below.

        A GATE, not a post factory: none of those writes is described here —
        `of_client` stays the only place that knows what a carrier post is.

        OnlyFans throttles EVERY write per account, so an import that paced only
        its own posts would still crowd an automation's fan message into OF's
        limit. Through the pacer it is spaced like every write, and it goes
        ahead of automation's waiting writes (the operator's tier, ADR 0025):
        those wait one more gap, none is dropped. The
        pacer lives on the event loop; we are on a worker thread, so hop across
        and block this thread (not the loop) until it is our turn. The ceiling
        is far above any real wait: the pacer spaces writes 11 s apart and the
        write itself carries its own network timeouts, so minutes here means
        something is stuck.
        """
        return _hop(of_write_paced(aid, thunk, send_purpose="not_fan_dm", operator=True),
                    _VAULT_WRITE_GATE_TIMEOUT_S)

    def _fan_send_gate(thunk):
        """The linked-fan run's chat message: a real DM to a real fan, so it is
        sent as one. The same pacer as every write, declared as what it is
        (`manual`: the operator picked this fan and confirmed who it is), the
        chat route's resale guard, and the chat route's outbound bookkeeping —
        the `messages` row, the media pin, the chat cache bust — since the
        sender is the only producer of outbound rows."""
        async def _send():
            # Free by construction (`materialize_via_message` sends price 0),
            # so the guard passes today; it runs so that stays the guard's call.
            await _reject_if_resale(aid, fan["id"], SendMessageBody(text=""))
            result = await of_write_paced(aid, thunk, send_purpose="manual", operator=True)
            await _record_fan_send(aid, fan["id"], result,
                                   employee_id=employee_id, price=0)
            return result
        return _hop(_send(), _VAULT_WRITE_GATE_TIMEOUT_S)

    def _mirror_gate(media_ids: list[int], details: dict[int, dict]) -> dict | None:
        """Write the ids this run landed into the local mirror, and the
        operator's per-file details onto those rows, BEFORE the run reports
        finished. Returns what became of the details (`{applied, skipped,
        why}`), which the run keeps on its record for the card to show.

        The grid reads the LOCAL mirror the moment the mirror holds any row for
        this account, and an upload only ever reached OnlyFans — so without this
        the file the operator just watched succeed appears in no vault view at
        all until somebody runs a full re-collect.

        It is a `vault_upload` hook rather than something this route does after
        the run because of the ORDER. The card polls the status route and fires
        its cache invalidations on the `running → not running` edge, exactly
        once; a mirror write that lands after that edge is a write nothing
        refetches (the mirror query has a 30 s staleTime, no interval, and
        `refetchOnWindowFocus` is off). Two hundred imported photos then stay
        invisible until the next collect — precisely the failure the mirror
        write was added to fix. `vault_upload` calls this while the run is still
        `running`, so the edge the client watches now comes after the write.

        Same loop-hop as `_write_gate`, for the same reason: `vault_upload.start`
        is on a worker thread and `ingest_ids` needs the relay's loop (and its DB
        session).

        CHUNKED under one deadline — see `_VAULT_MIRROR_TIMEOUT_S`, which can be
        smaller than the work it bounds. One 80-id write that runs out of time
        loses ALL of it (`fut.cancel()` does not stop the coroutine, so the rows
        land later, after the edge nothing refetches — the pre-import grid, back
        on the largest imports). Chunked, the same slow OF loses only the tail,
        and everything before it is in the mirror before the run reports
        finished. The details then go onto whichever rows DID land, on a budget
        of their own: a mirror write that ran out of time is no reason to drop
        the hashtags of the files it did write.

        The server-side listing cache is dropped here too, and unconditionally,
        because it is the SAME ordering rule applied to the other cache — and it
        matters most for the account `ingest_ids` stands aside for. An account
        that was never collected has no mirror, so its only view of the import is
        `/api/of/v2/vault/media`, which is served out of `vault_cache` on a 24 h
        TTL to a client whose `vault-media` staleTime is three days with
        `refetchOnWindowFocus` off. Dropping it in `_drive`'s `finally` — after
        `start` published `done` — leaves a refetch that beats the drop by a
        millisecond showing the pre-import listing for a day. `_drive` keeps its
        invalidate as belt-and-braces for the run that never reached this hook.
        """
        ids = list(media_ids)
        deadline = time.monotonic() + _VAULT_MIRROR_TIMEOUT_S
        try:
            for i in range(0, len(ids), _VAULT_MIRROR_CHUNK):
                left = deadline - time.monotonic()
                if left <= 0:
                    log.warning("vault mirror write ran out of time with %d of "
                                "%d ids unwritten", len(ids) - i, len(ids))
                    break
                try:
                    _hop(vault_ingest.ingest_ids(
                        aid, ids[i:i + _VAULT_MIRROR_CHUNK], client), left)
                except FuturesTimeout:
                    log.warning("vault mirror write timed out with %d of %d ids "
                                "unwritten", len(ids) - i, len(ids))
                    break
            if not details:
                return None
            try:
                return _hop(vault_ai_api.apply_import_meta(aid, details),
                            _VAULT_DETAILS_TIMEOUT_S)
            except FuturesTimeout:
                # Said on the run, not only in the log: the card shows it.
                return {"applied": 0, "skipped": len(details),
                        "why": "saving them timed out — check the files' "
                               "details in the vault"}
        finally:
            # Its own `finally`, and not conditional on the ingest: a chunk that
            # timed out or raised still leaves a stale listing behind, and the
            # media IS on OnlyFans either way.
            try:
                _hop(vault_cache.invalidate(aid), 30)
            except Exception as e:  # noqa: BLE001 — never mask the run's outcome
                log.warning("vault_cache: invalidate-before-finish failed: %s", e)

    def _run():
        try:
            return vault_upload.start(aid, client=client, local_paths=staged,
                                      drive_links=links, gate=_write_gate,
                                      send_gate=_fan_send_gate if fan else None,
                                      run_id=run_id, limits=limits,
                                      on_landed=_mirror_gate, metas=metas,
                                      list_id=int(list_id) if list_id else None)
        finally:
            shutil.rmtree(stage_dir, ignore_errors=True)

    async def _drive():
        try:
            await asyncio.to_thread(_run)
        except Exception:
            log.exception("vault batch upload failed")
            vault_upload.abandon(run_id, "the import worker died before it started")
        finally:
            # Its own `finally`, not a sibling `except Exception`: the relay
            # shutting down mid-run cancels this task, and `CancelledError` is a
            # BaseException — it would have walked straight past an `except
            # Exception` and left the server-side TTL cache serving the
            # PRE-import listing until it aged out on its own.
            try:
                await vault_cache.invalidate(aid)
            except Exception as e:  # noqa: BLE001 — never mask the run's own outcome
                log.warning("vault_cache: invalidate-after-batch failed: %s", e)

    _spawn_bg(_drive(), "vault-import")
    return {"run_id": run_id, "started": True,
            "files": len(staged), "drive_links": len(links)}


@app.post(_VAULT_APPEND_PATH)
async def of_vault_upload_batch_append(
    run_id: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    meta: str = Form(default=""),
    last: bool = Form(False),
):
    """Hand a run opened with `keep_open` its next file(s). `last` says that
    was everything (it may come with no file). 409 once the run has stopped
    taking files — it finished, failed, or sat idle past `OPEN_IDLE_S`."""
    aid = _resolve_account_id(_request_ctx.get())
    assert_account_owned(aid)
    state = (vault_upload.read_state(run_id)
             if re.fullmatch(r"[\w.-]+", run_id or "") else None)
    if state is None or str(state.get("account_id")) != str(aid):
        raise HTTPException(status_code=404, detail="no such import for this account")
    limits = vault_upload.Limits(pace_s=0).checked()
    metas_in = vault_upload.parse_metas(meta)
    taken = 0
    for n, f in enumerate(files or []):
        if not f.filename:
            continue
        try:
            # Held open for the transfer: the run does not idle out under a
            # large file, and the staging dir is the run's own.
            with vault_upload.receiving(run_id) as stage_dir:
                dest = await _vault_stage_file(f, stage_dir, limits)
                try:
                    vault_upload.append(run_id, dest,
                                        metas_in[n] if n < len(metas_in) else None)
                except vault_upload.NotTaking:
                    # Stopped listening while this file crossed the wire: it
                    # is ours to drop, and the operator's to re-send.
                    Path(dest).unlink(missing_ok=True)
                    raise
        except vault_upload.NotTaking as e:
            raise HTTPException(status_code=409, detail=str(e))
        except HTTPException:
            raise
        except (RuntimeError, OSError) as e:      # the disk floor, or the disk
            raise HTTPException(status_code=507, detail=str(e))
        taken += 1
    closed = vault_upload.close(run_id) if last else False
    return {"run_id": run_id, "files": taken, "closed": closed}


@app.get("/api/of/v2/vault/upload/drive/list")
async def of_vault_drive_list(link: str):
    """What a public Drive folder (or file) link would import, before importing
    it: each file's name, size, whether it can be imported, and the hashtags
    its folder path gives it. Read-only — it lists, it downloads nothing.
    `max_files` is how many of them one import takes."""
    aid = _resolve_account_id(_request_ctx.get())
    assert_account_owned(aid)
    limits = vault_upload.Limits(pace_s=0).checked()
    try:
        found = await asyncio.to_thread(
            gdrive.resolve, [link], max_files=vault_upload.resolve_budget(limits))
    except gdrive.GDriveError as e:
        raise HTTPException(status_code=400, detail=gdrive.redact(str(e)))
    out = []
    for f in found:
        ok, why = gdrive.is_uploadable(f)
        out.append({"name": f.name, "size": f.size, "mime_type": f.mime_type,
                    "folders": list(f.folders),
                    "hashtags": (vault_upload.drive_meta(f) or {}).get("hashtags", []),
                    "importable": ok, "reason": why or None})
    return {"files": out, "max_files": limits.max_files}


@app.get("/api/of/v2/vault/upload/status")
async def of_vault_upload_status(run_id: str | None = None):
    """Progress for the current (or named) batch. Safe to poll every ~2s.

    A run whose relay restarted mid-flight reports `interrupted` rather than a
    forever-`running` lie, and `running` describes THIS run, not the account, so
    an old run does not read as live because a new one is.

    Every field here that turns on liveness — the run's status and both carrier
    warnings — is `vault_upload._run_is_live` answering, once. It used to be two
    different answers: this payload could report a CLI import as "interrupted"
    (the dashboard renders that as "the relay restarted mid-run") while
    suppressing its carrier warnings in the same breath BECAUSE the account was
    busy.
    """
    aid = _resolve_account_id(_request_ctx.get())
    assert_account_owned(aid)
    # Whether the Drive import is on, for the card's Drive section: the key's
    # own reader answers (store first, then environment), so a paste in
    # Settings -> AI keys shows on the next poll with no restart. One deployment-wide
    # boolean on every answer; the key and any hint of it stay here.
    try:
        gdrive.api_key()
        drive_import_configured = True
    except gdrive.GDriveError:
        drive_import_configured = False
    # This server's own upload limits, the ones the batch route enforces, for
    # the card's rules row (in place of Infloww's 4 GB / 100 MB / pixel rules).
    limits = vault_upload.Limits(pace_s=0).checked()
    upload_limits = {"max_file_mb": limits.max_bytes // (1024 * 1024),
                     "max_files": limits.max_files}
    # Whether per-file details (hashtags, notes, price, tagged creators) can be
    # kept for this account at all: they live on its vault mirror rows, and an
    # account never synced here has none — the card labels those columns.
    details_saved_here = await vault_ingest.has_live_mirror(aid)
    # ONE walk of the spool per request: the latest run and the account-wide
    # carrier roll-up used to scan and re-parse every run.json separately, twice
    # over, for every 2.5s poll of every open tab. OFF the event loop, too — it
    # reads every run.json and, while another process holds an import lock, asks
    # the OS about that process, which on a non-Linux host forks `ps`.
    def _roll_up():
        runs = vault_upload.account_runs(aid)
        state = (vault_upload.read_state(run_id) if run_id
                 else vault_upload.latest_of(runs))
        return state, vault_upload.carriers_outstanding(aid, runs)

    try:
        state, (carriers_undeletable, carriers_unrecorded) = \
            await asyncio.to_thread(_roll_up)
    except ValueError:
        raise HTTPException(status_code=400, detail="bad run id")
    if state is None:
        return {"running": False, "run": None,
                "drive_import_configured": drive_import_configured,
                "upload_limits": upload_limits,
                "details_saved_here": details_saved_here}
    if str(state.get("account_id")) != str(aid):
        raise HTTPException(status_code=403, detail="not your run")
    items = state.get("items") or []
    counts = {st: sum(1 for i in items if i.get("status") == st)
              for st in vault_upload.ITEM_STATUSES}
    return {
        "running": state.get("status") == "running",
        "run_id": state.get("run_id"),
        "status": state.get("status"),
        "phase": state.get("phase"),
        "error": state.get("error"),
        "filing_error": state.get("filing_error"),
        # `{applied, skipped, why}` for the per-file details, once landed.
        "details_saved": state.get("details_saved"),
        # The linked fan, if any: that path costs one write per file, not two.
        "fan_id": state.get("fan_id"),
        "finished_at": state.get("finished_at"),
        "total": len(items),
        **counts,
        # Across EVERY run for the account and only FINISHED ones: a carrier
        # that could not be deleted must stay on screen until it is actually
        # gone, and one that legitimately exists for the two seconds of a live
        # import must never be reported as an escape. `carriers_unrecorded`
        # counts the worse case — an intent whose create response was lost, so
        # there is no id to name. The names are `vault_upload`'s own: this wire
        # said `carriers_live` long after the module stopped, so the retired
        # name was the one every consumer read.
        "carriers_undeletable": carriers_undeletable,
        "carriers_unrecorded": carriers_unrecorded,
        "items": items,
        "drive_import_configured": drive_import_configured,
        "upload_limits": upload_limits,
        "details_saved_here": details_saved_here,
    }


# Stories writes ----------------------------------------------------
# /stories does NOT accept a vault media id — even "pick from vault" in the
# UI re-uploads bytes through the convert pipeline. So we fetch the image
# (a vault item's files.full.url, or any CDN/image url), re-upload via
# upload_media(), then POST the convert claim to /stories. See
# of_client.post_story_from_url for the captured flow.

class _CreateStoryBody(BaseModel):
    media_url: str | None = Field(
        None, description="Image URL to download + repost (vault files.full.url / any CDN url)")
    media_files: list | None = Field(
        None, description="Already-prepared mediaFiles (send_with from POST /upload)")
    watermark_text: str | None = None
    # Optional overlays — replayed at the captured editor coordinates.
    caption: str | None = Field(None, description="Text overlay")
    mention: str | None = Field(None, description="@username tag (with or without @)")
    question: str | None = Field(None, description="Question sticker prompt")

@app.post("/api/of/v2/stories")
async def of_create_story(body: _CreateStoryBody = Body(...)):
    """Publish an image as a story, optionally with a caption / @mention tag /
    question sticker (placed at the captured editor coordinates).

    Two input modes:
      • media_url  → download bytes, re-upload through OF's convert pipeline,
                     then post (the "from vault / from CDN" path).
      • media_files → already-prepared claim from POST /api/of/v2/upload
                     (its `send_with`); posted as-is.
    """
    if body.media_files:
        return _proxy(lambda: _get_client().create_story(
            body.media_files,
            caption=body.caption, mention=body.mention, question=body.question,
        ))
    if not body.media_url:
        raise HTTPException(400, "provide media_url or media_files")
    return _proxy(lambda: _get_client().post_story_from_url(
        body.media_url, watermark_text=body.watermark_text,
        caption=body.caption, mention=body.mention, question=body.question,
    ))

@app.post("/api/of/v2/stories/upload")
async def of_create_story_upload(file: UploadFile = File(...)):
    """Publish a directly-uploaded file as a story. Multipart field: `file`."""
    import tempfile, os, shutil
    suffix = os.path.splitext(file.filename or "story.jpg")[1] or ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    try:
        return _proxy(lambda: _get_client().post_story(
            tmp_path, content_type=file.content_type,
        ))
    finally:
        try: os.unlink(tmp_path)
        except OSError: pass


# ── Admin ──────────────────────────────────────────────────────

@app.post("/admin/reload-session")
def reload_session(account_id: str | None = Query(None)) -> dict[str, Any]:
    """Hot-swap an account's OFClient (re-read its latest session from disk).
    `account_id` defaults to the currently-active account."""
    aid = account_id or account_registry.get_active_account_id()
    if not aid:
        raise HTTPException(status_code=503, detail="no active account")
    _invalidate_client(aid)
    c = _load_client(aid)
    return {"ok": True, "account_id": aid, "user_id": c.user_id, "x_of_rev": c.x_of_rev}


@app.get("/admin/rev/live")
def admin_rev_live() -> dict[str, Any]:
    """OF's live build (`x-of-rev`) as the relay last saw it on OF's own API
    responses (live_rev.py), plus the last central sign-rule refresh. The
    founder's OF Manager mirror-freshness banner reads `live_rev`. A session
    captured at an older build keeps working, so nothing here flags sessions."""
    live_snap = live_rev.get()
    return {
        "live_rev": live_snap.get("rev"),
        "live_fetched_at": live_snap.get("fetched_at"),
        # The last central sign-rule refresh (sign_rules.refresh): which build,
        # whose capture it copied, which accounts took it.
        "sign_rules": sign_rules.last(),
    }


class _BootstrapBody(BaseModel):
    mode: str = Field(..., description="'paste-curl'")
    curl: str | None = Field(None, description="Required for mode=paste-curl — `curl …` from DevTools")
    static_param_override: str | None = Field(None, description="Optional override for an unfamiliar OF revision")
    # Multi-account additions: optional hint/nickname and whether to flip the
    # newly-captured account to active. account_id is a hint only — the real
    # account is always determined by the captured user_id (OF's identity).
    account_id: str | None = Field(None, description="Hint: re-capture for this account (uses its stored proxy)")
    nickname: str | None = Field(None, description="Friendly label persisted to the account meta")
    make_active: bool = Field(True, description="Flip the relay's active account to the newly-captured one")


@app.post("/admin/session/bootstrap")
def bootstrap_session(body: _BootstrapBody = Body(...)) -> dict[str, Any]:
    """Set up an OF session. Mode:

    - **paste-curl**: paste a `curl ...` command copied from DevTools
      (right-click a `/api2/v2/*` request → Copy as cURL). We extract
      cookies + signed-header sample, fetch 2313.js, derive rules.

    Each captured session is written into its account's directory
    (sessions/accounts/<user_id>/). Pass `account_id` to re-capture an
    existing one.
    `nickname` is the friendly label shown in the UI switcher."""
    import session_bootstrap
    try:
        if body.mode == "paste-curl":
            if not body.curl:
                raise HTTPException(status_code=400, detail="curl text required for paste-curl")
            path = session_bootstrap.from_curl(
                body.curl,
                static_param_override=body.static_param_override,
                account_id=body.account_id, nickname=body.nickname,
                make_active=body.make_active,
            )
        else:
            raise HTTPException(status_code=400, detail=f"unknown mode: {body.mode}")
    except session_bootstrap.CurlParseError as e:
        raise HTTPException(status_code=400, detail=f"curl parse error: {e}")
    except HTTPException:
        raise
    except Exception as e:
        log.exception("bootstrap failed")
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")

    # Resolve which account dir we ended up in (path = .../accounts/<id>/session_*.json)
    actual_aid = path.parent.name
    c = post_bootstrap_hooks(actual_aid)
    return {
        "ok": True,
        "session_file": path.name,
        "account_id": actual_aid,
        "user_id": c.user_id,
        "x_of_rev": c.x_of_rev,
    }


class _FanslySessionBody(BaseModel):
    """The Fansly session blob the login-capture extension copies to the
    clipboard (see loginExtensionMulti/fansly_bridge.js)."""
    token: str = Field(..., description="Fansly authorization token")
    id: str | None = Field(None, description="fansly-session-id")
    accountId: str = Field(..., description="the creator account id (ours)")
    device_id: str | None = Field(None, description="fansly-client-id")
    user_agent: str = Field(..., description="must match the capturing browser")
    accept_language: str | None = None
    check_key: str | None = None
    nickname: str | None = Field(None, description="friendly label for the switcher")
    make_active: bool = Field(True)


@app.post("/admin/session/fansly")
def bootstrap_fansly_session(body: _FanslySessionBody = Body(...)) -> dict[str, Any]:
    """Register a Fansly account from a captured session blob.

    The Fansly twin of /admin/session/bootstrap's paste-curl mode — but there
    is no curl and no signing to derive: the session is a small JSON blob the
    extension lifts out of the fansly.com tab. We persist it beside the OF
    accounts, stamp the meta with platform="fansly" + the creator's display
    name, then run the SAME sync+ownership-link the OF path runs so the account
    shows up in the switcher and passes the isolation gate."""
    import fansly_backend

    account_id = str(body.accountId)
    session = {
        "token": body.token,
        "id": body.id,
        "accountId": account_id,
        "device_id": body.device_id,
        "user_agent": body.user_agent,
        "accept_language": body.accept_language or "en-US,en;q=0.9",
        "check_key": body.check_key,
    }

    # Write the session into the account dir (next to any OF cousins).
    adir = account_registry.account_dir(account_id)
    adir.mkdir(parents=True, exist_ok=True)
    session_file = adir / fansly_backend.SESSION_FILENAME
    session_file.write_text(json.dumps(session, indent=2) + "\n")
    try:
        session_file.chmod(0o600)
    except OSError:
        pass

    # Evict any stale cached client, then resolve the creator's display name
    # off a live me() so the switcher shows a name, not an id.
    fansly_backend.drop(account_id)
    name = None
    try:
        me = fansly_backend.get_client(account_id).me()
        name = me.get("name") or me.get("username")
    except Exception:
        log.warning("fansly me() failed during setup for %s", account_id, exc_info=True)

    account_registry.upsert_account(
        account_id,
        platform="fansly",
        name=name,
        nickname=body.nickname or name or f"Fansly {account_id}",
    )
    if body.make_active:
        account_registry.set_active_account_id(account_id)

    # Same ownership-link + SQL mirror the OF bootstrap runs.
    _sync_and_link_after_bootstrap(account_id)

    return {"ok": True, "account_id": account_id, "platform": "fansly", "name": name}


# ── Multi-account admin ───────────────────────────────────────

@app.get("/admin/accounts")
async def admin_accounts_list(response: Response) -> dict[str, Any]:
    """List every account the signed-in user owns + the currently-active one
    (clamped to the user's set). The UI populates its switcher from this.

    Account lists are PER-PRINCIPAL and must never be cached — a response
    fetched in one auth state must not be replayed in another — hence
    `no-store`. An UNauthenticated caller gets an EMPTY list, never the full
    multi-tenant registry: that fallback used to leak every owner's models,
    get cached by the client, and then 403 on save ("account X is not one of
    yours"). Sign in to get the real, `user_accounts`-scoped list."""
    response.headers["Cache-Control"] = "no-store"
    user = _get_request_user()
    if user is None:
        # Anonymous caller — expose nothing. Authentication yields the
        # real, scoped list; leaking the registry here poisoned client
        # caches across owners.
        return {"accounts": [], "active_account_id": None}
    all_accounts = [
        a for a in account_registry.list_accounts() if a.get("id") in user.account_ids
    ]
    # Dead-session accounts (automations paused — see account_health.py) are
    # stamped so the switcher can badge "unlinked" instead of looking idle.
    # Deactivated Creators stay listed (analytics, grants and history keep
    # their rows); `is_active` lets the switcher and inbox drop them.
    try:
        dead = await account_health.dead_session_map()
        off = await account_health.deactivated_ids()
    except Exception:
        log.exception("dead_session_map failed")
        dead, off = {}, set()
    # The Creator's proxy is bad: DOWN_AFTER counted failures in a row and a failed confirm probe (proxy_health).
    down = proxy_health.down_labels()
    for a in all_accounts:
        health = dead.get(a.get("id"), account_health.NO_DEAD_SESSION)
        a["session_dead_at"] = health.at
        a["session_dead_reason"] = health.reason
        a["is_active"] = a.get("id") not in off
        a["proxy_down"] = bool(down) and (
            (proxy_registry.get_for_account(a["id"]) or {}).get("label") in down)
    active = account_registry.get_active_account_id()
    if active not in user.account_ids:
        active = all_accounts[0]["id"] if all_accounts else None
    return {
        "accounts": all_accounts,
        "active_account_id": active,
    }


# Roster badge reads OF's LIVE chat list — the SAME source the chat-list rows
# read — over the inbox's first-page window, so the per-model badge matches what
# you see at a glance and the All-icon sums to the unified header's "Owe reply".
#
# Why NOT the local `chats` table (an earlier implementation): it is not a
# faithful mirror of OF — it accumulates phantom/old rows (one account: ~290 local vs
# OF's ~106), `last_message_at` ordering is unreliable, and `unread_count` drifts
# (WS only increments it), so a local scan read 3 "unread" for a model OF reports
# as 0. Why NOT a deep scan: paginating the whole history over-counted owe-reply
# vs the inbox (the All-icon read 11 where the unified header showed 5-6). Why NOT
# OF's `filter=unread` for blue: it proved unreliable — returned 0 for a model
# (Amia) that had a genuine `unreadMessagesCount=1` chat in its recent window.
# The badge window MUST equal the inbox's first page (frontend PAGE_SIZE in
# useChatList.ts) — both are served from the SAME "list_chats" cache entry
# keyed (25, 0, "recent", None, None, None), which is what guarantees the
# badge and the visible list can never disagree.
_ROSTER_SCAN_MAX = 25


def _roster_counts_from_rows(
    rows: list[dict[str, Any]], me: str,
    exclude: frozenset[int] | set[int] = frozenset(),
) -> dict[str, int]:
    """Pure fold of a /chats window into the two badge colors, exactly as the
    chat-list rows render them:

      • unread (blue)    — `unreadMessagesCount > 0` (OF's per-chat read state =
                           the inbox's blue unread badge).
      • owe_reply (orange) — READ (`unreadMessagesCount == 0`) AND the fan spoke
                           last (`lastMessage.fromUser.id != my id`, the chat-list
                           header's `isUnresponded` rule). Disjoint from blue so
                           the two pills don't double-count.

    Deduped by fan id and capped at the badge window. `exclude` is the account's
    OF-restricted set (skip_list reason='of_restricted'): restricted creators
    never count as unread/owe-reply — we deliberately cut them off, so their
    threads are not backlog. They still occupy a window slot (the list shows
    their row), which is what keeps the badge≡first-page parity intact — the
    frontend chips apply the SAME exclusion off the rows' `withUser.isRestricted`
    stamp (see the /chats serve-time annotation)."""
    blue = owe = 0
    seen: set[Any] = set()
    for ch in rows:
        wu = ch.get("withUser") or {}
        fid = wu.get("id")
        if fid is None or fid in seen:
            continue
        if len(seen) >= _ROSTER_SCAN_MAX:
            break
        seen.add(fid)
        if fid in exclude or wu.get("isRestricted"):
            continue
        if int(ch.get("unreadMessagesCount") or 0) > 0:
            blue += 1
            continue
        lm = ch.get("lastMessage") or {}
        from_id = (lm.get("fromUser") or {}).get("id")
        if from_id is not None and str(from_id) != me:
            owe += 1
    return {"unread": blue, "owe_reply": owe}


async def _compute_roster_count_of(account_id: str, *, bypass: bool = False) -> dict[str, int]:
    """A model's inbox backlog, derived from the SAME cached chats window the
    inbox list is served from (namespace "list_chats", the page-0 key the
    frontend requests). One OF read feeds both surfaces:

      • warm window → the badge is a pure fold over cached rows, zero OF cost;
      • cold window / `bypass=True` → ONE live scan that also REWARMS the list
        cache, so the next /api/of/v2/chats read is a warm hit of fresh rows.

    `bypass=True` is the ?bust= path: badge authoritative NOW **and** the list
    the user is about to open comes from that same read — they cannot disagree.
    The WS pump patches an inbound DM into the window in place and busts it on
    an outbound echo, and busts the roster count on both (event_transcoder), so
    a new inbound DM bumps blue — and our reply drops orange — on the next
    poll.

    Mirror-first: that WS-kept window IS the badge's mirror. Local
    `chats.unread_count` is not (see the block comment above), so the badge
    does not read it."""
    client = await asyncio.to_thread(_load_client, account_id)
    if not bypass:
        # Freshness contract: never fold from a window older than the badge's
        # pre-unification re-read cadence. A near-expiry window (≤600s) whose
        # fold is then cached for the roster TTL (300s) could otherwise serve
        # ~900s-old counts on a WS-dead account. Escalating to a live read
        # also rewarms the window, so the list gets fresher along with us.
        # Except while the account's WS has stayed connected since the window
        # was read: then the window is folded for its whole list TTL (600 s)
        # rather than 300 s. What keeps it current in that time: an inbound DM
        # is patched in (+1 unread, never re-ordered); an outbound echo (a reply
        # from OF web, another device) busts it, at most once per 20 s per
        # account, so a second reply inside that gap is not seen; our own sends
        # and our mark-read/unread routes bust it. OF pushes no read frame the
        # transcoder applies, so a chat read outside Inflowwww stays unread on
        # the badge until the window expires (≤600 s, was ≤300 s).
        fetched_at = _chats_window_fetched_at.get(account_id)
        from of_ws import connected_since
        live_since = connected_since(account_id)
        ws_kept = fetched_at is not None and live_since is not None and fetched_at >= live_since
        if fetched_at is None or (
            not ws_kept and _time_mod.monotonic() - fetched_at > _ROSTER_WINDOW_MAX_AGE_S
        ):
            bypass = True

    def _fetch_window() -> dict[str, Any]:
        value = _assemble_chats_page(
            client, limit=_ROSTER_SCAN_MAX, offset=0, order="recent",
        )
        _chats_window_fetched_at[account_id] = _time_mod.monotonic()
        return value

    resp = await relay_cache.get_or_fetch(
        "list_chats", account_id,
        (_ROSTER_SCAN_MAX, 0, "recent", None, None, None),
        ttl_seconds=_LIST_CHATS_TTL,
        fetcher=_fetch_window,
        bypass=bypass,
    )
    rows = resp.get("list") or resp.get("chats") or []
    from automations._common import load_of_restricted_ids
    exclude = await load_of_restricted_ids(account_id)
    return _roster_counts_from_rows(rows, str(client.user_id), exclude)


@app.get("/admin/accounts/roster-counts")
async def admin_accounts_roster_counts(
    response: Response, bust: str | None = None
) -> dict[str, Any]:
    """Per-model inbox badge counts for the left roster strip.

    Two colors, both straight from OF's live chat list (see
    `_compute_roster_count_of`) so the badge always agrees with the model's own
    inbox header:

      • unread    — OF reports the conversation unread (blue: "fans waiting to be
                    read").
      • owe_reply — read, but the fan spoke last (orange: "seen, not answered").

    Scoped to the signed-in principal's accounts (never the full registry, same as
    /admin/accounts). The principal may be a User (owner) OR a Chatter — a
    chatter sees the badges for the SET UNION of every linked owner's accounts,
    exactly the set its roster strip already renders. Each model's count is
    cached 5 min in relay_cache and the models are scanned concurrently, so a 60s
    frontend poll almost always serves from cache and a cold miss costs one
    bounded burst of OF reads, not one per poll. A model that fails to read (no
    session / OF hiccup) yields zero counts rather than failing the whole strip.

    `?bust=<account_id>` force-recomputes ONE model (the just-swapped-to / just-read
    one) so its badge is authoritative the instant the user touches it, instead of
    up to the 5-min cache TTL stale. Only that account re-reads OF; every other
    model still serves from cache, so a swap/hover costs the same one bounded burst
    a cold miss would — not a full-strip rescan. The bust is scoped to the
    principal's own accounts: an id outside `ids` is ignored (no cross-tenant cache
    poisoning), and the path is unchanged so the chatter admin allow-list still
    matches (chatters.py permits GET /admin/accounts/roster-counts)."""
    response.headers["Cache-Control"] = "no-store"
    user = _get_request_user()
    if user is not None:
        ids = list(user.account_ids or [])
    else:
        chatter = _get_request_chatter()
        ids = list(chatter.account_ids or []) if chatter is not None else []
    if not ids:
        return {"counts": {}}

    async def _one(aid: str, *, bypass: bool = False) -> tuple[str, dict[str, int]]:
        try:
            # Named async closure, not a lambda: get_or_fetch dispatches sync
            # fetchers to a thread, and a lambda returning a coroutine would
            # come back unawaited.
            async def _fetch() -> dict[str, int]:
                return await _compute_roster_count_of(aid, bypass=bypass)
            value = await relay_cache.get_or_fetch(
                "roster_count", aid, (),
                ttl_seconds=300.0,
                fetcher=_fetch,
            )
            return aid, value
        except Exception as e:  # noqa: BLE001 — one bad model must not blank the strip
            log.warning("roster-counts: OF read failed for %s", aid, exc_info=True)
            # OF rejected the session itself: pause the Creator and tell its owner,
            # as `_proxy` does. This strip is the read an owner makes even for a
            # Creator nobody chats on.
            dead_reason = account_health.is_session_dead_error(e)
            if dead_reason:
                _invalidate_client(aid)
                try:
                    if await account_health.mark_session_dead(aid, dead_reason):
                        log.warning("account_session_dead account=%s via=roster-counts reason=%s — "
                                    "automations paused until the session recovers", aid, dead_reason)
                except Exception:  # noqa: BLE001 — the strip still answers
                    log.exception("failed to mark session-dead account")
            return aid, {"unread": 0, "owe_reply": 0}

    # Targeted force-refresh: drop + recompute JUST this model and return only it.
    # The frontend merges the single entry into its cached map, so a swap / hover /
    # read costs exactly ONE bounded OF read — not a full-strip rescan, which the
    # gather would trigger for any *other* model whose cache is cold/expired. Gated
    # on ownership (a crafted `bust` can't evict another tenant's entry); an id the
    # principal doesn't own falls through to the normal full-map path.
    #
    # bypass=True is the badge↔list bridge: the recompute forces a LIVE OF read
    # of the shared chats window and REWARMS the "list_chats" page-0 entry, so
    # the list refetch the frontend chains after this call is a warm hit of the
    # same rows these counts were folded from.
    if bust and bust in ids:
        relay_cache.invalidate("roster_count", bust)
        _, value = await _one(bust, bypass=True)
        return {"counts": {bust: value}}

    pairs = await asyncio.gather(*[_one(a) for a in ids])
    return {"counts": {aid: c for aid, c in pairs}}


class _ActivateBody(BaseModel):
    account_id: str | None


@app.post("/admin/accounts/active")
def admin_accounts_activate(body: _ActivateBody = Body(...)) -> dict[str, Any]:
    """Flip which account is the default (no X-Account-Id header → this one)."""
    if body.account_id is not None and account_registry.get_account(body.account_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown account {body.account_id!r}")
    account_registry.set_active_account_id(body.account_id)
    _kick_db_sync("accounts-active")
    return {"ok": True, "active_account_id": body.account_id}


class _AccountUpdateBody(BaseModel):
    nickname: str | None = None
    color: str | None = None


@app.patch("/admin/accounts/{account_id}")
def admin_accounts_update(account_id: str, body: _AccountUpdateBody = Body(...)) -> dict[str, Any]:
    """Rename / recolor. Doesn't touch sessions.

    A chatter principal may ONLY recolor — `nickname` is owner management. For
    a chatter every field except `color` is forced to None so a crafted body
    can't rename. Owners and unauthed internal
    callers (curl/setup flows) keep the full field set. The chatter-allowed-admin
    gate already restricts chatters here to PATCH-only."""
    if account_registry.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown account {account_id!r}")
    # Explicit ownership gate. The account-isolation middleware only catches
    # NUMERIC account-id path segments — real OF ids are numeric so owners are
    # covered, but now that chatters can reach this path we assert ownership at
    # the handler regardless of id shape (no-op for unauthed curl; the full
    # registry set clears it for owners/masters).
    assert_account_owned(account_id)
    nickname = body.nickname
    if _get_request_user() is None and _get_request_chatter() is not None:
        nickname = None
    meta = account_registry.upsert_account(
        account_id,
        nickname=nickname,
        color=body.color,
    )
    _kick_db_sync(f"accounts-update-{account_id}")
    return {"ok": True, "account": meta}


@app.delete("/admin/accounts/{account_id}")
async def admin_accounts_remove(account_id: str) -> dict[str, Any]:
    """Permanently remove an account dir (sessions + meta). Stops its WS pump,
    drops its pooled client, and clears every server-side cache scoped to it.
    Cannot be undone."""
    if account_registry.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown account {account_id!r}")
    _stop_account_pump(account_id)
    _invalidate_client(account_id)
    # Purge both server caches for this account so a re-added account (same
    # account_id) can't read the prior session's chats/vault, and so the
    # next caller after the drop goes upstream instead of serving ghost
    # data. Both are strictly account-scoped — zero collateral on other
    # accounts. Best-effort: cache cleanup must never fail the delete.
    try:
        relay_cache.invalidate_account(account_id)
    except Exception as e:  # noqa: BLE001
        log.warning("relay_cache: invalidate-on-delete failed for %s: %s", account_id, e)
    try:
        await vault_cache.invalidate(account_id)
    except Exception as e:  # noqa: BLE001
        log.warning("vault_cache: invalidate-on-delete failed for %s: %s", account_id, e)
    ok = account_registry.delete_account(account_id)
    _kick_db_sync(f"accounts-delete-{account_id}")
    return {"ok": ok}


class _AccountActiveBody(BaseModel):
    active: bool


@app.post("/admin/accounts/{account_id}/active")
async def admin_accounts_set_active(
    account_id: str, body: _AccountActiveBody = Body(...),
) -> dict[str, Any]:
    """Creators › ⋮ › Deactivate / Activate.

    Owner-only, like Delete: a chatter session never reaches a POST under
    /admin/accounts (`chatters._chatter_allowed_admin`), so the owner and the
    Master hold this and no role grants it.

    Deactivate stops the Creator's work: its WS pump and pooled OF client now;
    the ledger polls, the chat-link seed and the automation executor on their
    next pass (each subtracts `account_health.deactivated_ids()`); OF-proxy
    writes to it answer 409 (`_deactivated_write_guard`). Every listing keeps
    it, stamped `is_active: false`. Billing and seat counts do not change —
    Infloww's own warning: fees still apply.

    Activate clears it; the pump supervisor restarts the pump within 15s.
    Jobs that fell due while it was off are cancelled as missed
    (`automation_executor.cancel_jobs_missed_while_off`), and a gap longer than
    the ledger's refresh window is backfilled
    (`transaction_ingest.backfill_after_reactivation`).

    The default (no-header) account is left alone, even when it is this
    Creator: that file is shared across agencies. The 409 guard covers
    writes that fall back to it."""
    if account_registry.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown account {account_id!r}")
    assert_account_owned(account_id)
    if not body.active:
        await account_health.deactivate(account_id)
        _stop_account_pump(account_id)
        _invalidate_client(account_id)
        return {"ok": True, "account_id": account_id, "is_active": False}
    # Jobs that fell due while it was off are cancelled while the flag still
    # holds the executor off them, so none fires between here and activate().
    off_since = await account_health.deactivated_since(account_id)
    if off_since is not None:
        from automation_executor import cancel_jobs_missed_while_off
        await cancel_jobs_missed_while_off(account_id, off_since)
    since = await account_health.activate(account_id)
    if since is not None:
        from transaction_ingest import backfill_after_reactivation
        await backfill_after_reactivation(account_id, since)
    return {"ok": True, "account_id": account_id, "is_active": True}


# ── Proxy registry admin ──────────────────────────────────────
# Phase-1 (DC testing): creds are returned in plaintext on purpose so the UI
# can show host:port:user:pass. Move to keychain in Phase 2.

class _ProxyBody(BaseModel):
    label: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None
    scheme: str = "http"
    notes: str = ""


class _AssignBody(BaseModel):
    label: str
    # Legacy: bind to a specific session file. Kept for back-compat.
    session_file: str | None = Field(None, description="LEGACY: session_*.json filename; prefer account_id")
    # Preferred: bind to an OF account (survives re-captures).
    account_id: str | None = Field(None, description="OF account id to bind this proxy to (null to unassign)")


@app.get("/admin/proxies")
def admin_proxies_list() -> dict[str, Any]:
    """Return proxies + the account list the UI populates its 'assign to'
    picker from. Each proxy is enriched with `assigned_accounts` (a list of
    {id, nickname, color}). A proxy may serve many accounts — the UI flags
    >1 as a shared-egress warning because OF can correlate same-IP behaviour.

    Per-user filtering: a signed-in friend sees only proxies they own
    (`user_id == them`) plus shared defaults (`user_id is None`). The
    `accounts` picker list and each proxy's `assigned_accounts` are
    clamped to accounts the viewer owns so we don't leak nicknames of
    other friends' accounts via the proxy chip render path.

    `assigned_account` (singular, deprecated) and `assigned_account_id`
    (legacy scalar) are mirrored from the list's first entry so older
    callers keep working until they migrate."""
    user = _get_request_user()
    proxies_list = proxy_registry.list_proxies()
    accounts = account_registry.list_accounts()
    if user is not None:
        accounts = [a for a in accounts if a["id"] in user.account_ids]
    by_aid = {a["id"]: a for a in accounts}
    enriched = []
    pool_ids: list[str] = []
    pool_size = pool_bad = 0
    down = proxy_health.down_labels()
    for p in proxies_list:
        if proxy_registry.is_pool(p):
            # Never listed: only the count, how many are bad (proxy_health), and
            # the viewer's accounts on one (`proxy_down` on /admin/accounts says which are down).
            pool_size += 1
            pool_ids += [aid for aid in proxy_registry._ids_on(p) if aid in by_aid]
            pool_bad += p.get("label") in down
            continue
        if user is not None:
            pu = p.get("user_id")
            if pu is not None and pu != user.id:
                continue
        out = dict(p)
        ids = proxy_registry._ids_on(p)
        bound = [
            {
                "id": aid,
                "nickname": by_aid[aid].get("nickname"),
                "color": by_aid[aid].get("color"),
            }
            for aid in ids if aid in by_aid
        ]
        out["assigned_accounts"] = bound
        out["assigned_account_ids"] = [b["id"] for b in bound]
        # Legacy singular: mirror first entry so old consumers don't break.
        out["assigned_account"] = bound[0] if bound else None
        out["assigned_account_id"] = bound[0]["id"] if bound else None
        out["url"] = proxy_registry.proxy_url(p)
        out["health"] = proxy_health.snapshot(p["label"])
        enriched.append(out)
    return {
        "proxies": enriched,
        # Inflowwww proxy pool: how many the relay holds, and which of the
        # viewer's accounts are on one. Hosts and credentials stay here.
        "pool": {"size": pool_size, "account_ids": pool_ids, "bad": pool_bad},
        # Slim account list shaped the way the picker wants it.
        "accounts": [{
            "id": a["id"], "nickname": a.get("nickname"),
            "color": a.get("color"), "has_session": a.get("has_session", False),
        } for a in accounts],
    }


def _assert_proxy_owned_or_mine(label: str) -> dict[str, Any]:
    """Look up a proxy by label and verify the signed-in user may mutate it.

    Shared defaults (`user_id is None`) are read-only for friends — they
    can't reassign or delete the 3 hu-* entries we ship by default.
    Friend-owned proxies (`user_id == me`) are freely mutable by that
    friend. Unauthed requests (cron, share-token bootstrap) bypass.
    """
    p = proxy_registry.get_by_label(label)
    if p is None or proxy_registry.is_pool(p):
        raise HTTPException(status_code=404, detail=f"no proxy with label {label!r}")
    user = _get_request_user()
    if user is None:
        return p
    pu = p.get("user_id")
    if pu is None:
        raise HTTPException(status_code=403, detail="shared default proxy is read-only")
    if pu != user.id:
        raise HTTPException(status_code=403, detail="not your proxy")
    return p


def _assert_proxy_assignable(label: str) -> dict[str, Any]:
    """Visibility check for binding/unbinding an account to a proxy.

    Distinct from `_assert_proxy_owned_or_mine`, which gates mutation of the
    proxy *entity* (upsert/delete) and keeps shared defaults read-only.
    Attaching YOUR OWN account to a shared-default proxy is the whole point
    of shipping shared defaults, so it's allowed here — account ownership is
    enforced separately by `assert_account_owned`, so a friend can only ever
    bind/unbind an account they own. We still 404 another friend's private
    proxy (they can't see it, so they can't bind to it by guessing a label).
    Unauthed requests (cron, share-token bootstrap) bypass.
    """
    p = proxy_registry.get_by_label(label)
    if p is None or proxy_registry.is_pool(p):
        raise HTTPException(status_code=404, detail=f"no proxy with label {label!r}")
    user = _get_request_user()
    if user is None:
        return p
    pu = p.get("user_id")
    if pu is not None and pu != user.id:
        raise HTTPException(status_code=404, detail=f"no proxy with label {label!r}")
    return p


@app.post("/admin/proxies")
def admin_proxies_upsert(body: _ProxyBody = Body(...)) -> dict[str, Any]:
    payload = body.model_dump()
    user = _get_request_user()
    existing = proxy_registry.get_by_label(payload.get("label", ""))
    if proxy_registry.is_pool(existing):
        raise HTTPException(status_code=403, detail=f"{BRAND_NAME} proxy is read-only")
    if existing is None and proxy_registry.is_reserved_label(payload.get("label", "")):
        raise HTTPException(status_code=400, detail=f"label is reserved for the {BRAND_NAME} proxy pool")
    if user is not None:
        if existing is not None:
            eu = existing.get("user_id")
            if eu is None:
                raise HTTPException(status_code=403, detail="shared default proxy is read-only")
            if eu != user.id:
                raise HTTPException(status_code=403, detail="not your proxy")
            # Preserve owner — don't let a payload field reassign ownership.
            payload["user_id"] = eu
        else:
            # New proxy created by a signed-in friend → tag with their id.
            payload["user_id"] = user.id
    try:
        entry = proxy_registry.upsert(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # An upsert edits host/port/credentials in place under the same label, so
    # pooled clients would keep dialing the OLD proxy. Nothing cleared here
    # before pooling reached the automation lane; now it has to.
    _invalidate_client()
    _kick_db_sync(f"proxy-upsert-{body.label}")
    return {"ok": True, "proxy": entry}


class _ProxyBulkBody(BaseModel):
    text: str
    scheme: str = "http"


def _proxy_owner() -> str | None:
    """Owner for proxies created from a pasted line — same rule as
    POST /admin/proxies: a signed-in user owns what they add; unauthed
    requests (cron, share-token bootstrap) write to the shared pool."""
    user = _get_request_user()
    return user.id if user is not None else None


@app.post("/admin/proxies/bulk")
def admin_proxies_bulk(body: _ProxyBulkBody = Body(...)) -> dict[str, Any]:
    """Paste many proxies at once, one per line (formats: docs/proxies.md).
    Blank and `#` lines are skipped. Passwords never appear in the response."""
    owner = _proxy_owner()
    added: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for n, raw in enumerate(body.text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            e = proxy_registry.upsert_from_line(line, body.scheme, owner=owner)
        except (ValueError, PermissionError) as exc:
            errors.append({"line": n, "text_redacted": proxy_registry.redact_line(line),
                           "reason": str(exc)})
            continue
        added.append({k: e.get(k) for k in ("label", "host", "port", "scheme", "username")})
    if added:
        _invalidate_client()
        _kick_db_sync(f"proxy-bulk-{len(added)}")
    return {"added": added, "errors": errors}


@app.delete("/admin/proxies/{label}")
def admin_proxies_remove(label: str) -> dict[str, Any]:
    """Delete a proxy no Creator uses. A proxy still bound to a live account
    is a 409 naming those Creators (Infloww's "Proxy already in use"): the
    owner unbinds or moves them first, so no Creator silently falls back to
    direct egress. Bindings left by a deleted account do not count, nor, for
    a signed-in caller, bindings to accounts it cannot see (GET /admin/proxies
    hides them too); those go with the proxy, as before."""
    p = _assert_proxy_owned_or_mine(label)
    user = _get_request_user()
    live = {a["id"]: a for a in account_registry.list_accounts()}
    in_use = [
        live[aid] for aid in proxy_registry._ids_on(p)
        if aid in live and (user is None or aid in user.account_ids)
    ]
    if in_use:
        names = ", ".join(a.get("nickname") or a["id"] for a in in_use)
        raise HTTPException(status_code=409, detail=f"Proxy already in use by {names}. Unbind it first.")
    ok = proxy_registry.remove(label)
    if not ok:
        raise HTTPException(status_code=404, detail=f"no proxy with label {label!r}")
    # Proxy assignment is per session-file, but a session-file is owned by
    # exactly one account → invalidating the whole pool is the simplest
    # correct option (one network round-trip on next request per account).
    _invalidate_client()
    _kick_db_sync(f"proxy-delete-{label}")
    return {"ok": True}


@app.post("/admin/proxies/assign")
def admin_proxies_assign(body: _AssignBody = Body(...)) -> dict[str, Any]:
    """Bind a proxy to an account (preferred) or to a specific session file
    (legacy). Pass `account_id: null` to unassign the account binding.

    Whichever scheme is used, all pooled clients are dropped so the affected
    account picks up the new proxy on its next request."""
    _assert_proxy_assignable(body.label)
    if body.account_id is not None:
        assert_account_owned(body.account_id)
    try:
        # If the caller specified account_id (even as null), treat as account
        # binding — even an explicit null is a "please unassign" signal.
        if body.account_id is not None or "account_id" in body.model_fields_set:
            entry = proxy_registry.assign_account(body.label, body.account_id)
        else:
            entry = proxy_registry.assign(body.label, body.session_file)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    _invalidate_client()
    _kick_db_sync(f"proxy-assign-{body.label}")
    return {"ok": True, "proxy": entry}


class _PoolBody(BaseModel):
    account_id: str


# Its own prefix, so no custom proxy label can shadow these routes.
@app.post("/admin/proxy-pool/assign")
def admin_proxies_pool_assign(body: _PoolBody = Body(...)) -> dict[str, Any]:
    """Put an account on an Inflowwww proxy: kept if it already holds one
    unless its failover is due, else the least-used one that answers a probe,
    or the least-used not bad when none answers, or the least-used when every
    pool proxy is bad (proxy_health.assign_pool). The answer names no host,
    label or credentials. 409 only when the env pool is empty (nothing bound)."""
    assert_account_owned(body.account_id)
    try:
        _, kept = proxy_health.assign_pool(body.account_id)
    except LookupError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not kept:
        _invalidate_client()
        _kick_db_sync("proxy-pool-assign")
    return {"ok": True, "kept": kept}


@app.post("/admin/proxy-pool/unbind")
def admin_proxies_pool_unbind(body: _PoolBody = Body(...)) -> dict[str, Any]:
    """Take an account off its Inflowwww proxy (No proxy). No-op when it has none."""
    assert_account_owned(body.account_id)
    removed = proxy_registry.unbind_pool(body.account_id)
    if removed:
        _invalidate_client()
        _kick_db_sync("proxy-pool-unbind")
    return {"ok": True, "removed": removed}


class _UnbindBody(BaseModel):
    account_id: str


@app.post("/admin/proxies/{label}/unbind")
def admin_proxies_unbind(label: str, body: _UnbindBody = Body(...)) -> dict[str, Any]:
    """Remove a single account from a proxy's binding list. The account
    falls back to direct egress until reassigned. Distinct from `/assign`
    (which now appends rather than replaces) — needed because multi-binding
    made the old `account_id: null` unbind gesture ambiguous (unbind WHICH
    account from the list?)."""
    _assert_proxy_assignable(label)
    assert_account_owned(body.account_id)
    try:
        entry = proxy_registry.unbind_account(label, body.account_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    _invalidate_client()
    _kick_db_sync(f"proxy-unbind-{label}-{body.account_id}")
    return {"ok": True, "proxy": entry}


@app.post("/admin/proxies/{label}/test")
def admin_proxies_test(label: str) -> dict[str, Any]:
    # Read-only probe — fine to run against any proxy the user can see
    # (own + shared defaults). Just blocks "test some other friend's
    # proxy by label" since they can't see it in the first place.
    user = _get_request_user()
    p = proxy_registry.get_by_label(label)
    if p is None or proxy_registry.is_pool(p):
        raise HTTPException(status_code=404, detail=f"no proxy with label {label!r}")
    if user is not None:
        pu = p.get("user_id")
        if pu is not None and pu != user.id:
            raise HTTPException(status_code=404, detail=f"no proxy with label {label!r}")
    result = proxy_registry.probe(p)
    proxy_registry.record_verification(
        label, ip=result.get("ip"), geo=result.get("geo"), ok=result.get("ok", False),
    )
    proxy_health.record_probe(label, result)
    return result


# ── Realtime: WS fan-out, stats ────────────────

@app.get("/events", include_in_schema=False)
async def sse_events(
    request: Request, scope: str = Query("all"),
    last_event_id: str | None = Query(None),
):
    """Server-Sent Events stream for the new browser app.

    Uses SSE so the client uses native
    EventSource (one-way, auto-reconnect, plays well with corporate
    proxies). Scope grammar:
      ?scope=all                    — every event of the session's Creators
      ?scope=model:<account_id>     — only that Creator (403 if not the session's)

    Only the session's Creators' events reach it (owner: its accounts;
    chatter: the union its Agencies grant), plus its Agencies' own events.
    401 signed out, as every per-account read.

    Replay: the browser's `Last-Event-ID` header on its own reconnect, or
    `?last_event_id=` when it reopens the stream itself; see events.sse_stream.
    """
    accounts = _require_actor_account_ids()
    if scope.startswith("model:") and accounts is not None and scope[len("model:"):] not in accounts:
        raise HTTPException(status_code=403, detail="not your account")
    user = _get_request_user()
    chatter = _get_request_chatter() if user is None else None
    agencies = (frozenset({user.id, owner_audience(user.id), sessions_audience("user", user.id)})
                if user is not None
                else chatter.owner_user_ids | {sessions_audience("chatter", chatter.id)}
                if chatter is not None else frozenset())
    return StreamingResponse(
        sse_stream(request, scope, accounts=accounts, agencies=agencies,
                   last_event_id=request.headers.get("last-event-id") or last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # tell nginx/cloudflare to flush, not buffer
            "Connection": "keep-alive",
        },
    )


@app.get("/admin/events/stats")
def event_stats() -> dict[str, Any]:
    """How many events the pumps have seen, broken down by type + account.
    Useful to confirm each account's WS is alive without subscribing."""
    pumps = {
        aid: {"running": not t.done(), "cancelled": t.cancelled() if t.done() else False}
        for aid, t in _account_pumps.items()
    }
    return {
        **_event_stats,
        "subscribers": len(_event_subscribers),
        "pumps": pumps,
        "pumps_running": sum(1 for p in pumps.values() if p["running"]),
        "supervisor_running": (_supervisor_task is not None and not _supervisor_task.done()),
        # Each open SSE stream's mode (immediate / batch), rate and queue depth.
        "sse": _sse_stats(),
    }


# ── Saved replies (local-only "templates" minus welcome) ──────────────
# OF's /messages/templates rejects creates for everything except the
# welcome slot. We keep regular saved replies in the local DB and let
# the UI merge them with OF's welcome at render time.

class _SavedReplyBody(BaseModel):
    title: str | None = None
    text: str
    price: float = Field(0, ge=0)
    locked_text: bool = False
    # Vault-media references, persisted as JSON so the editor can
    # re-render thumbs without a second fetch.
    media: list[dict] = Field(default_factory=list)
    # OF user ids of creators to @-tag when this template is applied.
    # Persisted so the picker can re-hydrate tagging without re-querying
    # OF's tagged-friend-users endpoint on every pick.
    tagged_users: list[int] = Field(default_factory=list)
    # Subset of `media`'s vault ids that ride along UNLOCKED when `price > 0`.
    # Order does not matter; OF treats this as a set.
    previews: list[int] = Field(default_factory=list)
    # Optional Giphy id stored on the template. NULL/None = no GIF. When set,
    # the picker seeds the composer's picked-GIF state on pick so the GIF
    # rides along on send.
    gif_id: str | None = None
    # Cached animated preview URL so the picker chip can render without a
    # fresh Giphy roundtrip.
    gif_url: str | None = None
    # Optional script grouping: when both `script_id` (free-text name) and
    # `script_step` (1-based order) are set, sending this template advances
    # a per-chat cursor; the composer then surfaces the next step in the
    # same script as a one-tap suggestion bubble. NULL on either field opts
    # the template out of the script flow.
    script_id: str | None = None
    script_step: int | None = None
    # Growth > Scripts' tags (names, at most 32 characters each) and internal
    # notes (at most 256). None leaves a stored value as it is on PUT, so a
    # client that predates them never wipes them.
    tags: list[str] | None = None
    notes: str | None = Field(None, max_length=256)


_SCRIPT_TAG_MAX = 32


def _clean_tags(tags: list[str]) -> list[str]:
    """Trimmed, de-duplicated (first spelling wins), empty names dropped; 400 over 32 characters."""
    out: list[str] = []
    for t in tags:
        name = str(t).strip()
        if not name or name in out:
            continue
        if len(name) > _SCRIPT_TAG_MAX:
            raise HTTPException(status_code=400, detail=f"tag name over {_SCRIPT_TAG_MAX} characters")
        out.append(name)
    return out


def _serialize_saved_reply(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "title": row.title,
        "text": row.text,
        "price": (row.price_cents or 0) / 100,
        "locked_text": bool(row.locked_text),
        "media": json.loads(row.media_json or "[]"),
        "tagged_users": json.loads(getattr(row, "tagged_users_json", None) or "[]"),
        "previews": json.loads(getattr(row, "previews_json", None) or "[]"),
        "gif_id": getattr(row, "gif_id", None),
        "gif_url": getattr(row, "gif_url", None),
        "script_id": getattr(row, "script_id", None),
        "script_step": getattr(row, "script_step", None),
        "tags": json.loads(getattr(row, "tags_json", None) or "[]"),
        "notes": getattr(row, "notes", None),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@app.get("/admin/saved-replies")
async def admin_saved_replies_list(account_id: str = Query(...)) -> dict[str, Any]:
    """Saved replies for one account. Sorted newest-edit first.

    Each row also carries `removed_media_ids`: its media our vault mirror has
    since marked deleted on OF (`vault_items.removed_at`), so the composer can
    warn before a chatter sends a script whose media is gone."""
    assert_account_owned(account_id)
    from db.engine import get_session
    from db.models import SavedReply, VaultItem
    from sqlalchemy import select
    async with get_session() as s:
        result = await s.execute(
            select(SavedReply)
            .where(SavedReply.account_id == account_id)
            .order_by(SavedReply.updated_at.desc()),
        )
        rows = result.scalars().all()
        out = [_serialize_saved_reply(r) for r in rows]
        ids_by_row = [[int(m["id"]) for m in r["media"]
                       if isinstance(m, dict) and str(m.get("id", "")).isdigit()] for r in out]
        media_ids = {i for ids in ids_by_row for i in ids}
        removed: set[int] = set()
        if media_ids:
            removed = set((await s.execute(
                select(VaultItem.media_id).where(
                    VaultItem.account_id == account_id,
                    VaultItem.media_id.in_(media_ids),
                    VaultItem.removed_at.is_not(None),
                ),
            )).scalars().all())
        for r, ids in zip(out, ids_by_row):
            r["removed_media_ids"] = [i for i in ids if i in removed]
        return {"list": out}


@app.post("/admin/saved-replies")
async def admin_saved_replies_create(
    body: _SavedReplyBody = Body(...),
    account_id: str = Query(...),
) -> dict[str, Any]:
    """Create a new saved reply for an account."""
    assert_account_owned(account_id)
    from db.engine import get_session
    from db.models import SavedReply
    async with get_session() as s:
        row = SavedReply(
            account_id=account_id,
            title=body.title,
            text=body.text,
            price_cents=int(round(body.price * 100)),
            locked_text=body.locked_text,
            media_json=json.dumps(body.media),
            tagged_users_json=json.dumps([int(u) for u in body.tagged_users]),
            previews_json=json.dumps([int(p) for p in body.previews]),
            gif_id=body.gif_id or None,
            gif_url=body.gif_url or None,
            script_id=body.script_id or None,
            script_step=body.script_step,
            tags_json=json.dumps(_clean_tags(body.tags or [])),
            notes=body.notes or None,
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return _serialize_saved_reply(row)


@app.put("/admin/saved-replies/{reply_id}")
async def admin_saved_replies_update(
    reply_id: int,
    body: _SavedReplyBody = Body(...),
) -> dict[str, Any]:
    """Replace a saved reply's contents wholesale (no PATCH semantics — UI
    submits the full draft on every save, matching the editor's mental model)."""
    from db.engine import get_session
    from db.models import SavedReply
    from datetime import datetime as _dt
    async with get_session() as s:
        row = await s.get(SavedReply, reply_id)
        if not row:
            raise HTTPException(status_code=404, detail="saved reply not found")
        # Defense-in-depth: the row's account_id must be in the active
        # principal's allowed set. Without this, a chatter linked to
        # @alice could PUT a reply that belongs to @bob just by guessing
        # the reply_id.
        assert_account_owned(row.account_id)
        row.title = body.title
        row.text = body.text
        row.price_cents = int(round(body.price * 100))
        row.locked_text = body.locked_text
        row.media_json = json.dumps(body.media)
        row.tagged_users_json = json.dumps([int(u) for u in body.tagged_users])
        row.previews_json = json.dumps([int(p) for p in body.previews])
        row.gif_id = body.gif_id or None
        row.gif_url = body.gif_url or None
        row.script_id = body.script_id or None
        row.script_step = body.script_step
        if body.tags is not None:
            row.tags_json = json.dumps(_clean_tags(body.tags))
        if body.notes is not None:
            row.notes = body.notes or None
        row.updated_at = _dt.utcnow()
        await s.commit()
        await s.refresh(row)
        return _serialize_saved_reply(row)


@app.delete("/admin/saved-replies/{reply_id}")
async def admin_saved_replies_delete(reply_id: int) -> dict[str, Any]:
    from db.engine import get_session
    from db.models import SavedReply
    async with get_session() as s:
        row = await s.get(SavedReply, reply_id)
        if row is not None:
            # Same row-based ownership check as PUT.
            assert_account_owned(row.account_id)
        if not row:
            raise HTTPException(status_code=404, detail="saved reply not found")
        await s.delete(row)
        await s.commit()
        return {"ok": True}


class _SavedReplyRelabelBody(BaseModel):
    """One tag or sequence edit across an account's scripts (Growth > Scripts).

    - tag, from X, to Y: rename X to Y (merging into Y if it exists); to null deletes X from every script.
    - tag, from null, to Y, ids: add Y to those scripts (the selection bar's "Add to tag").
    - sequence, from X, to Y: rename the sequence (409 if Y is another sequence's name); to null ungroups its
      scripts (script_id and script_step cleared; the scripts themselves stay).
    `ids` limits any of these to those scripts (e.g. removing one script from a tag or sequence)."""
    kind: Literal["tag", "sequence"]
    from_: str | None = Field(None, alias="from")
    to: str | None = None
    ids: list[int] | None = None


@app.post("/admin/saved-replies/relabel")
async def admin_saved_replies_relabel(
    body: _SavedReplyRelabelBody = Body(...),
    account_id: str = Query(...),
) -> dict[str, Any]:
    assert_account_owned(account_id)
    from db.engine import get_session
    from db.models import SavedReply
    from sqlalchemy import select
    src = (body.from_ or "").strip() or None
    dst = (body.to or "").strip() or None
    if src is None and (dst is None or body.kind == "sequence" or not body.ids):
        raise HTTPException(status_code=400, detail="from is required, or to and ids to add a tag")
    if body.kind == "tag" and dst is not None and len(dst) > _SCRIPT_TAG_MAX:
        raise HTTPException(status_code=400, detail=f"tag name over {_SCRIPT_TAG_MAX} characters")
    if body.kind == "sequence" and dst is not None and len(dst) > 64:
        raise HTTPException(status_code=400, detail="sequence name over 64 characters")
    async with get_session() as s:
        q = select(SavedReply).where(SavedReply.account_id == account_id)
        if body.ids is not None:
            q = q.where(SavedReply.id.in_(body.ids))
        rows = (await s.execute(q)).scalars().all()
        updated = 0
        if body.kind == "tag":
            for row in rows:
                tags = json.loads(row.tags_json or "[]")
                if src is not None:
                    if src not in tags:
                        continue
                    tags = [t for t in tags if t != src]
                if dst is not None and dst not in tags:
                    tags.append(dst)
                row.tags_json = json.dumps(tags)
                updated += 1
        else:
            if dst is not None and dst != src:
                clash = (await s.execute(
                    select(SavedReply.id).where(SavedReply.account_id == account_id,
                                                SavedReply.script_id == dst).limit(1)
                )).first()
                if clash:
                    raise HTTPException(status_code=409, detail="Sequence name already exists. Please rename sequence.")
            for row in rows:
                if row.script_id != src:
                    continue
                row.script_id = dst
                if dst is None:
                    row.script_step = None
                updated += 1
        await s.commit()
        return {"updated": updated}


# ── Vault sends + per-fan history ─────────────────────────────────────
# Powers the picker's "you sent this to her 2 weeks ago / she bought it"
# badges. Frontend writes here right after a successful chat-send (better
# than wrapping the OF send proxy — keeps that path a clean mirror, and
# lets us decide per-call whether to track, e.g. don't track mass-sends).

class _VaultSendBody(BaseModel):
    account_id: str
    fan_id: int
    media_ids: list[int] = Field(default_factory=list)
    message_id: int | None = None
    price_cents: int = Field(0, ge=0, description="PPV price in cents (0 = free send)")


@app.post("/admin/vault/sends")
async def admin_vault_sends_create(body: _VaultSendBody = Body(...)) -> dict[str, Any]:
    """Record one vault-send row per media id. Returns the inserted count.

    Skips negative ids (fresh-claim placeholders the optimistic bubble
    used before the real vault id was assigned) — those slip through if
    the caller doesn't filter, and we shouldn't pollute history with them."""
    from db.engine import get_session
    from db.models import VaultSend
    real_ids = [mid for mid in body.media_ids if isinstance(mid, int) and mid > 0]
    if not real_ids:
        return {"ok": True, "inserted": 0}
    async with get_session() as s:
        for mid in real_ids:
            s.add(VaultSend(
                account_id=body.account_id,
                fan_id=body.fan_id,
                media_id=mid,
                message_id=body.message_id,
                price_cents=body.price_cents,
                # was_purchased flips later when a matching transaction
                # lands (see Transaction ingest path). Default null = unknown.
            ))
        await s.commit()
    return {"ok": True, "inserted": len(real_ids)}


class _VaultBackfillItem(BaseModel):
    message_id: int
    media_ids: list[int] = Field(default_factory=list)
    price_cents: int = Field(0, ge=0)
    # OF reports `isOpened=true` on a PPV once the fan has paid; we mirror
    # that as `was_purchased`. None for free sends — leave the column null
    # so the UI can distinguish "definitely not paid" vs "wasn't paid for".
    was_purchased: bool | None = None


class _VaultBackfillBody(BaseModel):
    account_id: str
    fan_id: int
    items: list[_VaultBackfillItem] = Field(default_factory=list)


@app.post("/admin/vault/sends/backfill")
async def admin_vault_sends_backfill(body: _VaultBackfillBody = Body(...)) -> dict[str, Any]:
    """Bulk-insert vault-send rows from chat history. The frontend calls
    this whenever a chat opens — every outgoing message with media that
    DOESN'T already have a vault_send row gets one. Idempotent: existing
    rows are detected via (account_id, fan_id, media_id, message_id) and
    skipped, so it's safe to fire on every chat-open without dupes.

    This is how we cover historical sends (pre-tracking), without
    requiring a one-off backfill job."""
    from db.engine import get_session
    from db.models import VaultSend
    from sqlalchemy import select
    if not body.items:
        return {"ok": True, "inserted": 0, "skipped": 0}

    # Pull every existing (media_id, message_id) for this fan in one query
    # so the dupe check is O(rows) instead of O(items × DB roundtrip).
    seen_msg_ids = {it.message_id for it in body.items if it.message_id}
    inserted = 0
    skipped = 0
    async with get_session() as s:
        existing: set[tuple[int, int]] = set()
        if seen_msg_ids:
            res = await s.execute(
                select(VaultSend.media_id, VaultSend.message_id)
                .where(
                    VaultSend.account_id == body.account_id,
                    VaultSend.fan_id == body.fan_id,
                    VaultSend.message_id.in_(seen_msg_ids),
                ),
            )
            for mid, msg in res.all():
                if msg is not None:
                    existing.add((mid, msg))

        for item in body.items:
            real_ids = [mid for mid in item.media_ids if isinstance(mid, int) and mid > 0]
            for mid in real_ids:
                if (mid, item.message_id) in existing:
                    skipped += 1
                    continue
                s.add(VaultSend(
                    account_id=body.account_id,
                    fan_id=body.fan_id,
                    media_id=mid,
                    message_id=item.message_id,
                    price_cents=item.price_cents,
                    was_purchased=item.was_purchased,
                ))
                existing.add((mid, item.message_id))
                inserted += 1
        if inserted:
            await s.commit()
    return {"ok": True, "inserted": inserted, "skipped": skipped}


def _parse_of_iso(s: Any) -> datetime | None:
    """OF's postedAt is "2026-04-12T17:33:11+00:00"-ish. Returns a naive
    UTC datetime (matches the rest of our DB convention) or None."""
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


@app.get("/admin/vault/wall-media")
async def admin_vault_wall_media(
    request: Request,
    account_id: str = Query(...),
    pages: int = Query(5, ge=1, le=20, description="Max OF /posts pages to walk per call."),
    limit: int = Query(50, ge=1, le=50, description="Posts per page."),
    force: bool = Query(False, description="Force a re-scan from the top, ignoring the cached watermarks. UI's '↻ refresh' button."),
) -> dict[str, Any]:
    """Aggregate every vault media id ever posted on this model's wall,
    backed by SQLite (`wall_media` + `wall_scan_state`) so subsequent
    calls are O(diff-since-last-scan) instead of the old 5-page
    (~250-post) re-walk every hour.

    Two operating modes (state per-account in `wall_scan_state`):
      • Backfill: walks BACKWARD from `oldest_post_published_at` using
        OF's beforePublishTime cursor. Used until we hit the bottom of
        the post feed; `pages` per call so creators with thousands of
        posts amortize the walk over several picker opens.
      • Refresh: once `fully_backfilled=True`, walks FORWARD from the
        top and stops at the post matching `newest_post_published_at`.
        Usually a single page round-trip — creators rarely post 50
        wall items between picker opens.

    Returns the UNION of every media_id we've ever recorded for this
    account plus scan status. `has_more=true` means DB coverage is
    incomplete (older history remains) — the frontend uses it to
    optionally trigger another fetch in the background.

    The OF httpx calls (`client.me()`, `client.user_posts(...)`) are
    blocking; we run each via `asyncio.to_thread` so the event loop
    stays responsive — the up-to-5 sequential page walks otherwise
    froze SSE / webhooks for the full duration (observed 13.5s in the
    wild). `request.is_disconnected()` checks between pages so a folder
    switch mid-walk frees the per-account proxy slot promptly."""
    from db.engine import get_session
    from db.models import WallMedia, WallScanState
    from sqlalchemy import func, select
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    client = _load_client(account_id)
    me_resp = await asyncio.to_thread(client.me)
    my_id = me_resp.get("id")
    if not isinstance(my_id, int):
        raise HTTPException(status_code=500, detail="Could not resolve current user id from /users/me")

    # 1. Load scan state; honor `force` by wiping watermarks (rows stay —
    #    re-walking just re-confirms what we know via on_conflict_do_nothing).
    async with get_session() as s:
        state = (await s.execute(
            select(WallScanState).where(WallScanState.account_id == account_id)
        )).scalar_one_or_none()
        if force and state is not None:
            state.newest_post_published_at = None
            state.oldest_post_published_at = None
            state.fully_backfilled = False
            await s.flush()
        # Snapshot the values we need outside the session (state row is
        # detached after the `async with` exits).
        prev_newest = state.newest_post_published_at if state else None
        prev_oldest = state.oldest_post_published_at if state else None
        prev_backfilled = bool(state.fully_backfilled) if state else False
        prev_total = int(state.scanned_posts_total) if state else 0

    # 2. Pick mode + cursor. Three cases:
    #    • first   — never scanned this account before, walk forward from top.
    #    • refresh — fully covered already, walk forward and stop at watermark.
    #    • backfill — middle: walk backward from oldest known post.
    if prev_newest is None and prev_oldest is None:
        mode = "first"
        before: str | None = None
        stop_forward_at: datetime | None = None
    elif prev_backfilled:
        mode = "refresh"
        before = None
        stop_forward_at = prev_newest
    else:
        mode = "backfill"
        before = (
            f"{prev_oldest.timestamp():.6f}"
            if prev_oldest is not None else None
        )
        stop_forward_at = None

    # 3. Walk pages, accumulating new (account, media, post, published_at).
    new_rows: list[dict[str, Any]] = []
    seen_media_in_call: set[int] = set()  # dedupe within this call's batch
    scanned = 0
    page_newest_ts: datetime | None = None
    page_oldest_ts: datetime | None = None
    hit_known_top = False
    of_has_more = False
    for _ in range(pages):
        if await request.is_disconnected():
            raise HTTPException(status_code=499, detail="client disconnected")
        resp = await asyncio.to_thread(
            client.user_posts,
            my_id,
            limit=limit,
            skip_users="all",
            format="infinite",
            before_publish_time=before,
        )
        posts = resp.get("list", []) if isinstance(resp, dict) else []
        if not posts:
            break
        scanned += len(posts)
        for post in posts:
            pid = post.get("id")
            posted_at = _parse_of_iso(post.get("postedAt") or post.get("postedAtPrecise"))
            if posted_at and (page_newest_ts is None or posted_at > page_newest_ts):
                page_newest_ts = posted_at
            if posted_at and (page_oldest_ts is None or posted_at < page_oldest_ts):
                page_oldest_ts = posted_at
            # Refresh-mode stop: posts older-than-or-equal-to the watermark
            # are already in our DB. Don't enqueue their media (we have
            # them) and flag the outer loop to bail.
            if mode == "refresh" and stop_forward_at and posted_at and posted_at <= stop_forward_at:
                hit_known_top = True
                continue
            # OF posts carry a top-level `price` (dollars, float) for paid /
            # PPV wall posts; free posts omit it or send 0. Convert to cents
            # so the picker can badge "WALL $X.XX".
            try:
                post_price_cents = int(round(float(post.get("price") or 0) * 100))
            except (TypeError, ValueError):
                post_price_cents = 0
            if post_price_cents < 0:
                post_price_cents = 0
            for m in (post.get("media") or []):
                mid = m.get("id")
                if isinstance(mid, int) and mid > 0 and mid not in seen_media_in_call:
                    seen_media_in_call.add(mid)
                    new_rows.append({
                        "account_id": account_id,
                        "media_id": mid,
                        "post_id": int(pid) if isinstance(pid, int) else None,
                        "post_published_at": posted_at,
                        "price_cents": post_price_cents,
                    })
        of_has_more = bool(resp.get("hasMore"))
        if hit_known_top:
            break
        if not of_has_more:
            break
        before = resp.get("tailMarker")
        if not before:
            break

    # 4. Persist new rows + scan state, then read the full union back.
    now = datetime.utcnow()
    new_fully_backfilled = prev_backfilled
    if mode == "first":
        new_fully_backfilled = not of_has_more
    elif mode == "backfill" and not of_has_more:
        new_fully_backfilled = True
    # refresh mode never flips back to False — force=True is the only path
    # that resets the watermarks.

    # Merge watermarks: extend in whichever direction this call walked.
    new_newest = page_newest_ts
    if prev_newest is not None and (new_newest is None or prev_newest > new_newest):
        new_newest = prev_newest
    new_oldest = page_oldest_ts
    if prev_oldest is not None and (new_oldest is None or prev_oldest < new_oldest):
        new_oldest = prev_oldest

    new_total = prev_total + scanned

    async with get_session() as s:
        # Ensure the parent accounts row exists — wall_media + wall_scan_state
        # both FK to accounts.id. Without import_legacy ever running for this
        # account, the FK insert blows up. Idempotent ON CONFLICT no-op.
        from db.models import Account
        await s.execute(
            sqlite_insert(Account)
            .values(id=account_id, is_active_default=False)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        if new_rows:
            ins = sqlite_insert(WallMedia).values(new_rows)
            # Upsert price_cents to MAX(existing, incoming) so a media seen
            # in both a free and a paid wall post keeps the paid signal, and
            # already-recorded rows pick up a price on a forward/force
            # re-scan. post_id / post_published_at keep their first-seen
            # values — only the price is refined.
            await s.execute(
                ins.on_conflict_do_update(
                    index_elements=["account_id", "media_id"],
                    set_={"price_cents": func.max(WallMedia.price_cents, ins.excluded.price_cents)},
                )
            )
        await s.execute(
            sqlite_insert(WallScanState)
            .values(
                account_id=account_id,
                newest_post_published_at=new_newest,
                oldest_post_published_at=new_oldest,
                fully_backfilled=new_fully_backfilled,
                last_scan_at=now,
                scanned_posts_total=new_total,
            )
            .on_conflict_do_update(
                index_elements=["account_id"],
                set_={
                    "newest_post_published_at": new_newest,
                    "oldest_post_published_at": new_oldest,
                    "fully_backfilled": new_fully_backfilled,
                    "last_scan_at": now,
                    "scanned_posts_total": new_total,
                },
            )
        )
        all_rows = (await s.execute(
            select(WallMedia.media_id, WallMedia.price_cents)
            .where(WallMedia.account_id == account_id)
        )).all()

    # Only the priced rows go in the map — keeps the payload lean (free wall
    # posts are the common case and the frontend defaults missing ids to 0).
    media_prices = {
        str(int(mid)): int(cents)
        for mid, cents in all_rows
        if cents and int(cents) > 0
    }
    return {
        "media_ids": sorted({int(mid) for mid, _ in all_rows}),
        "media_prices": media_prices,
        "scanned_posts": scanned,
        "new_media_count": len(new_rows),
        "has_more": not new_fully_backfilled,
        "fully_backfilled": new_fully_backfilled,
        "mode": mode,
        "last_scan_at": now.isoformat() + "Z",
        "newest_post_published_at": new_newest.isoformat() + "Z" if new_newest else None,
        "oldest_post_published_at": new_oldest.isoformat() + "Z" if new_oldest else None,
    }


@app.get("/admin/vault/fan-history")
async def admin_vault_fan_history(
    account_id: str = Query(...),
    fan_id: int = Query(...),
) -> dict[str, Any]:
    """Per-media send history for ONE fan. Drives the vault-picker's
    'sent / purchased / unseen' badges with an O(1) lookup per tile.

    Returns:
      by_media: { "<media_id>": { send_count, last_sent_at,
                                  last_price_cents, was_purchased,
                                  last_purchase_at, total_paid_cents } }

    `was_purchased` mirrors the column on vault_sends — true once a
    transaction with the same message_id is observed.
    `last_purchase_at` / `total_paid_cents` come from joining the
    transactions table (kind in {message, ppv}) on message_id."""
    from db.engine import get_session
    from db.models import Transaction, VaultSend
    from sqlalchemy import select
    async with get_session() as s:
        # All sends to this fan, newest first.
        sends_res = await s.execute(
            select(VaultSend)
            .where(VaultSend.account_id == account_id, VaultSend.fan_id == fan_id)
            .order_by(VaultSend.sent_at.desc()),
        )
        sends = sends_res.scalars().all()
        if not sends:
            return {"by_media": {}}

        # Pull transactions referenced by any of our sends so we can mark
        # was_purchased + sum paid amounts. Filter to message-bearing txns
        # to skip subscription rebills + tips.
        msg_ids = {s.message_id for s in sends if s.message_id is not None}
        tx_by_msg: dict[int, list[Transaction]] = {}
        if msg_ids:
            tx_res = await s.execute(
                select(Transaction)
                .where(
                    Transaction.account_id == account_id,
                    Transaction.fan_id == fan_id,
                    Transaction.message_id.in_(msg_ids),
                ),
            )
            for t in tx_res.scalars().all():
                if t.message_id is None:
                    continue
                tx_by_msg.setdefault(t.message_id, []).append(t)

        by_media: dict[str, dict[str, Any]] = {}
        for snd in sends:
            entry = by_media.setdefault(str(snd.media_id), {
                "send_count": 0,
                "last_sent_at": None,
                "last_price_cents": 0,
                "was_purchased": False,
                "last_purchase_at": None,
                "total_paid_cents": 0,
            })
            entry["send_count"] += 1
            # Sends came back newest-first, so the first one we see is
            # the most recent — only fill these when they're still empty.
            if entry["last_sent_at"] is None:
                entry["last_sent_at"] = snd.sent_at.isoformat() if snd.sent_at else None
                entry["last_price_cents"] = snd.price_cents or 0
            # was_purchased: row flag OR any matching transaction.
            if snd.was_purchased:
                entry["was_purchased"] = True
            if snd.message_id and snd.message_id in tx_by_msg:
                for t in tx_by_msg[snd.message_id]:
                    entry["was_purchased"] = True
                    entry["total_paid_cents"] += t.amount_cents or 0
                    iso = t.occurred_at.isoformat() if t.occurred_at else None
                    if iso and (entry["last_purchase_at"] is None or iso > entry["last_purchase_at"]):
                        entry["last_purchase_at"] = iso
        return {"by_media": by_media}


# ── /admin/ingest/transactions/* — Phase F supervisor admin surface ─
# Read/write surface over `transaction_scan_history` (the per-account
# watermark for the OF payouts/transactions ingest job) plus a few
# observability queries on `transactions`. Sits next to the other
# /admin/* routes; share-token gate fires via middleware so no
# per-route auth dep is needed.

def _tx_ingest_tier(minutes_since_scan: float | None, current_status: str) -> str:
    """Health tier per synthesis §7.
    green:  scanned within 30m AND status in {idle, ok, refreshing, backfilling}
    yellow: 30 < minutes_since_scan <= 360
    red:    minutes_since_scan > 360 OR status in {paused, error, never_scanned}

    Note: 'refreshing'/'backfilling' here are the in-flight steady states
    (tick START stamps them, _mark_success then stamps 'ok'). A row
    sitting in those states still counts as green if the timestamp is
    fresh — it means a scan is actively running.
    """
    if current_status in ("paused", "error", "never_scanned"):
        return "red"
    if minutes_since_scan is None:
        return "red"
    if minutes_since_scan <= 30 and current_status in (
        "idle", "ok", "refreshing", "backfilling",
    ):
        return "green"
    if minutes_since_scan <= 360:
        return "yellow"
    return "red"


_TIER_RANK = {"green": 0, "yellow": 1, "red": 2}


@app.get("/admin/ingest/transactions/health")
async def admin_ingest_tx_health() -> dict[str, Any]:
    from db.engine import get_session
    from db.models import Account, TransactionScanHistory
    from sqlalchemy import select
    now = datetime.utcnow()
    # Scope to the signed-in principal's account_ids union (same rule as
    # /admin/accounts and the picker). Unauthed callers (internal curl /
    # cron) still see every row. Without this filter the Ingest health
    # banner would list models the chatter has no permission to act on.
    user = _get_request_user()
    chatter = _get_request_chatter() if user is None else None
    if user is not None:
        allowed_ids: frozenset[str] | None = user.account_ids
    elif chatter is not None:
        allowed_ids = chatter.account_ids
    else:
        allowed_ids = None
    async with get_session() as s:
        acct_rows = (await s.execute(select(Account.id, Account.nickname))).all()
        hist_rows = (await s.execute(select(TransactionScanHistory))).scalars().all()

    if allowed_ids is not None:
        acct_rows = [r for r in acct_rows if r[0] in allowed_ids]

    hist_by_acct = {h.account_id: h for h in hist_rows}
    accounts_out: list[dict[str, Any]] = []
    worst = "green"
    for aid, nick in acct_rows:
        h = hist_by_acct.get(aid)
        if h is None:
            entry = {
                "account_id": aid,
                "display_name": nick,
                "last_scan_at": None,
                "current_status": "never_scanned",
                "last_error": None,
                "consecutive_failures": 0,
                "paused_until": None,
                "rows_inserted_total": 0,
                "rows_patched_total": 0,
                "fully_backfilled": False,
                "minutes_since_scan": None,
                "tier": "red",
            }
        else:
            mins = (
                (now - h.last_scan_at).total_seconds() / 60.0
                if h.last_scan_at is not None else None
            )
            tier = _tx_ingest_tier(mins, h.current_status or "idle")
            entry = {
                "account_id": aid,
                "display_name": nick,
                "last_scan_at": h.last_scan_at.isoformat() if h.last_scan_at else None,
                "current_status": h.current_status,
                "last_error": h.last_error,
                "consecutive_failures": int(h.consecutive_failures or 0),
                "paused_until": h.paused_until.isoformat() if h.paused_until else None,
                "rows_inserted_total": int(h.rows_inserted_total or 0),
                "rows_patched_total": int(h.rows_patched_total or 0),
                "fully_backfilled": bool(h.fully_backfilled),
                "minutes_since_scan": round(mins, 2) if mins is not None else None,
                "tier": tier,
            }
        accounts_out.append(entry)
        if _TIER_RANK[entry["tier"]] > _TIER_RANK[worst]:
            worst = entry["tier"]

    return {
        "overall_status": worst,
        "as_of": now.isoformat(),
        "accounts": accounts_out,
    }


class _TxRunBody(BaseModel):
    mode: str = Field("refresh", pattern="^(refresh|backfill)$")


@app.post("/admin/ingest/transactions/{account_id}/run", status_code=202)
async def admin_ingest_tx_run(
    account_id: str,
    body: _TxRunBody | None = Body(None),
) -> dict[str, Any]:
    from db.engine import get_session
    from db.models import Account, TransactionScanHistory
    from sqlalchemy import select
    mode = (body.mode if body else "refresh") or "refresh"
    async with get_session() as s:
        acct = (await s.execute(
            select(Account.id).where(Account.id == account_id)
        )).first()
        if acct is None:
            raise HTTPException(status_code=404, detail="account not found")
        h = (await s.execute(
            select(TransactionScanHistory)
            .where(TransactionScanHistory.account_id == account_id)
        )).scalar_one_or_none()
        if h is not None and h.current_status in ("backfilling", "refreshing"):
            # Stale-age escape valve. last_scan_at is stamped at tick
            # START (transaction_ingest.run_one_tick), so its age ==
            # how long the row has been parked at this status. A real
            # in-flight tick holds an asyncio.Lock + finishes well under
            # _STALE_INFLIGHT_S; anything older is a tombstone from a
            # process restart or cancelled task that escaped both the
            # try/finally and the boot sweep — we must NOT keep locking
            # the user's manual Refresh out forever.
            from transaction_ingest import _STALE_INFLIGHT_S  # type: ignore[import-not-found]
            age_s = (
                (datetime.utcnow() - h.last_scan_at).total_seconds()
                if h.last_scan_at is not None
                else _STALE_INFLIGHT_S + 1
            )
            if age_s < _STALE_INFLIGHT_S:
                raise HTTPException(
                    status_code=409,
                    detail=f"already in-flight: {h.current_status}",
                )
            log.warning(
                "admin_ingest_tx_run_proceed_after_stale account=%s status=%s age_s=%.0f",
                account_id, h.current_status, age_s,
            )

    # Lock peek removed: run_one_tick now stamps current_status to
    # "refreshing"/"backfilling" at the START of the tick (inside the
    # session that took the lock), so the upstream current_status check
    # at line 4714 catches in-flight scans without needing to import
    # supervisor internals here. See library/db_data/17_round2_synthesis.md.
    queued_at = datetime.utcnow()

    async def _trigger() -> None:
        try:
            from transaction_ingest import run_one_tick  # type: ignore[import-not-found]
        except ImportError:
            log.info("admin_ingest_tx_run: transaction_ingest not yet available; no-op")
            return
        try:
            await run_one_tick(account_id, mode=mode)
        except Exception:
            log.warning("run_one_tick failed for %s", account_id, exc_info=True)

    asyncio.create_task(_trigger(), name=f"tx-ingest-trigger-{account_id}")

    return {"accepted": True, "mode": mode, "queued_at": queued_at.isoformat()}


@app.post("/admin/roster/{account_id}/crawl")
async def admin_roster_crawl(account_id: str) -> dict[str, Any]:
    """One subscriber-roster crawl NOW, past its 25-minute TTL
    (`lifecycle_messages._CRAWL_TTL_S`): the on-demand trigger for
    `subscriber_snapshot`, as /admin/ingest/transactions/{id}/run is for the
    ledger. Same code path as the lifecycle sweep and smart_list_sync, under
    the same per-account lock; answers that run's stats ({roster: crawled |
    truncated | empty, listed, returned}). A seam in ADR 0024."""
    from db.engine import get_session
    from db.models import Account
    from sqlalchemy import select
    assert_account_owned(account_id)
    async with get_session() as s:
        if (await s.execute(select(Account.id).where(Account.id == account_id))).first() is None:
            raise HTTPException(status_code=404, detail="account not found")
    import automation_executor as ax
    from automations.lifecycle_messages import refresh_roster
    client = await asyncio.to_thread(ax._make_client, account_id)
    return await refresh_roster(account_id, client, now=datetime.utcnow(), force=True)


class _TxPauseBody(BaseModel):
    duration_hours: int = Field(1, ge=1, le=24 * 30)


@app.post("/admin/ingest/transactions/{account_id}/pause", status_code=202)
async def admin_ingest_tx_pause(
    account_id: str,
    body: _TxPauseBody = Body(...),
) -> dict[str, Any]:
    from db.engine import get_session
    from db.models import Account, TransactionScanHistory
    from sqlalchemy import select
    paused_until = datetime.utcnow() + timedelta(hours=body.duration_hours)
    async with get_session() as s:
        acct = (await s.execute(
            select(Account.id).where(Account.id == account_id)
        )).first()
        if acct is None:
            raise HTTPException(status_code=404, detail="account not found")
        h = (await s.execute(
            select(TransactionScanHistory)
            .where(TransactionScanHistory.account_id == account_id)
        )).scalar_one_or_none()
        if h is None:
            h = TransactionScanHistory(account_id=account_id)
            s.add(h)
        h.paused_until = paused_until
        await s.commit()
    return {"accepted": True, "paused_until": paused_until.isoformat()}


@app.post("/admin/ingest/transactions/{account_id}/resume", status_code=202)
async def admin_ingest_tx_resume(account_id: str) -> dict[str, Any]:
    """Clear `paused_until` so the supervisor picks this account back up
    on the next tick. Idempotent — calling on an already-unpaused row
    is a no-op."""
    from db.engine import get_session
    from db.models import Account, TransactionScanHistory
    from sqlalchemy import select
    async with get_session() as s:
        acct = (await s.execute(
            select(Account.id).where(Account.id == account_id)
        )).first()
        if acct is None:
            raise HTTPException(status_code=404, detail="account not found")
        h = (await s.execute(
            select(TransactionScanHistory)
            .where(TransactionScanHistory.account_id == account_id)
        )).scalar_one_or_none()
        if h is not None:
            h.paused_until = None
            if h.current_status == "paused":
                h.current_status = "ok"
            await s.commit()
    return {"accepted": True}


@app.get("/admin/ingest/transactions/orphan-tips")
async def admin_ingest_tx_orphan_tips(
    account_id: str | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    include_assigned: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """Tip transactions that fall into the 'Unattributed' bucket in the
    per-employee view: kind in tip family, status cleared or pending (the
    view's own statuses, so this list matches the Unattributed total), and no
    chatter-attributed outbound message within the 7-day lookback. With
    `include_assigned=true` ALSO returns tips that already have a
    manual `attributed_employee_id` set (so the UI can offer reassign
    / clear). Each row's `attributed_employee_id` is null for true
    orphans, populated for previously-assigned tips.

    Optional `from` / `to` (ISO date) scope to the dashboard's window."""
    from db.engine import get_session
    from sqlalchemy import text as sql_text
    # LEFT JOIN employees so we return the chatter's display_name with the
    # row — the UI used to look this up against the current owner's roster
    # and fell back to "Employee {id}" when the employee was scoped out
    # (e.g. transferred). The DB has the canonical name; surface it here.
    sql = """
      SELECT t.id, t.account_id, t.fan_id, t.amount_cents, t.occurred_at,
             t.description, t.kind, t.attributed_employee_id,
             e.display_name AS attributed_employee_name
        FROM transactions t
        LEFT JOIN employees e ON e.id = t.attributed_employee_id
       WHERE t.kind IN ('tip', 'tip_post', 'tip_stream')
         AND t.status IN ('cleared', 'pending')
         AND t.message_id IS NULL
         AND NOT EXISTS (
           SELECT 1 FROM messages m
            WHERE m.account_id = t.account_id
              AND m.fan_id = t.fan_id
              AND m.direction = 'out'
              AND m.sent_by_employee_id IS NOT NULL
              AND m.created_at <= t.occurred_at
              AND m.created_at > datetime(t.occurred_at, '-7 days')
         )
    """
    params: dict[str, Any] = {"lim": limit}
    if not include_assigned:
        sql += " AND t.attributed_employee_id IS NULL"
    if account_id:
        sql += " AND t.account_id = :aid"
        params["aid"] = account_id
    if from_:
        sql += " AND t.occurred_at >= :start"
        params["start"] = from_
    if to:
        # End-of-day for bare ISO dates so "to=YYYY-MM-DD" includes that day.
        sql += " AND t.occurred_at <= :end"
        params["end"] = f"{to} 23:59:59" if len(to) == 10 else to
    sql += " ORDER BY t.occurred_at DESC LIMIT :lim"

    async with get_session() as s:
        rows = (await s.execute(sql_text(sql), params)).all()
    return {
        "rows": [
            {
                "id": int(r.id),
                "account_id": r.account_id,
                "fan_id": int(r.fan_id) if r.fan_id is not None else None,
                "kind": r.kind,
                "amount_cents": int(r.amount_cents or 0),
                "occurred_at": r.occurred_at if isinstance(r.occurred_at, str)
                                else (r.occurred_at.isoformat() if r.occurred_at else None),
                "description": r.description,
                "attributed_employee_id": (
                    int(r.attributed_employee_id)
                    if r.attributed_employee_id is not None else None
                ),
                # "No one" (sales_attribution.NO_ONE) names no Employee row.
                "attributed_employee_name": ("No one" if r.attributed_employee_id == 0
                                             else r.attributed_employee_name),
            }
            for r in rows
        ]
    }


@app.get("/admin/ingest/transactions/sales-needing-attribution")
async def admin_sales_needing_attribution(
    account_id: str | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    include_assigned: bool = Query(False),
    lookback_days: int = Query(7, ge=1, le=90),
    limit: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    """Confirmed sales (`cleared`+`pending`) currently in the per-employee view's
    'Unattributed' bucket — standalone-tip orphans, message-linked orphans (a
    PPV whose scraped message carries no sender, e.g. duplicate-price PPVs the
    auto-rule leaves ambiguous), AND unlinked PPV/custom orphans (`message_id`
    NULL — the relinker found no unambiguous message; per ops' manual-only rule
    these are never auto-credited, so THIS panel is their only path to a
    chatter). Each row ships the CANDIDATE chatters (distinct NON-MASS 1:1
    senders to that fan within `lookback_days` before the sale) so the operator
    can assign the right one via
    POST /admin/ingest/transactions/{id}/attribute. `include_assigned=true` also
    returns sales that already carry a manual override (to reassign / clear).

    Mirrors attribution_backfill's orphan predicates; the 7-day NOT-EXISTS on the
    standalone-tip branch matches the live view's own lookup so the two agree.
    The unlinked-PPV branch has NO toucher exclusion — the view gives PPVs no
    lookback, so every unlinked one is an orphan regardless of recent chat."""
    from db.engine import get_session
    from sqlalchemy import text as sql_text

    orphan_cte = """
      WITH orphans AS (
        SELECT t.id, t.account_id, t.fan_id, t.amount_cents, t.occurred_at,
               t.description, t.kind, t.status, t.attributed_employee_id
          FROM transactions t
          JOIN messages m ON m.account_id = t.account_id AND m.fan_id = t.fan_id
                         AND m.message_id = t.message_id
         WHERE t.message_id IS NOT NULL
           AND t.kind IN ('ppv','ppv_message','ppv_post','ppv_stream',
                          'tip','tip_post','tip_stream','custom')
           AND t.status IN ('cleared','pending')
           AND m.sent_by_employee_id IS NULL
        UNION ALL
        SELECT t.id, t.account_id, t.fan_id, t.amount_cents, t.occurred_at,
               t.description, t.kind, t.status, t.attributed_employee_id
          FROM transactions t
         WHERE t.kind IN ('tip','tip_post','tip_stream')
           AND t.message_id IS NULL
           AND t.status IN ('cleared','pending')
           AND t.fan_id IS NOT NULL
           AND NOT EXISTS (
             SELECT 1 FROM messages m
              WHERE m.account_id = t.account_id AND m.fan_id = t.fan_id
                AND m.direction = 'out' AND m.sent_by_employee_id IS NOT NULL
                AND m.created_at <= t.occurred_at
                AND m.created_at > datetime(t.occurred_at, '-7 days'))
        UNION ALL
        SELECT t.id, t.account_id, t.fan_id, t.amount_cents, t.occurred_at,
               t.description, t.kind, t.status, t.attributed_employee_id
          FROM transactions t
         WHERE t.kind IN ('ppv','ppv_message','ppv_post','ppv_stream','custom')
           AND t.message_id IS NULL
           AND t.status IN ('cleared','pending')
           AND t.fan_id IS NOT NULL
      )
      SELECT o.id, o.account_id, o.fan_id, o.amount_cents, o.occurred_at,
             o.description, o.kind, o.status, o.attributed_employee_id,
             e.display_name AS attributed_employee_name
        FROM orphans o
        LEFT JOIN employees e ON e.id = o.attributed_employee_id
       WHERE 1=1
    """
    params: dict[str, Any] = {"lim": limit}
    if not include_assigned:
        orphan_cte += " AND o.attributed_employee_id IS NULL"
    if account_id:
        orphan_cte += " AND o.account_id = :aid"
        params["aid"] = account_id
    if from_:
        orphan_cte += " AND o.occurred_at >= :start"
        params["start"] = from_
    if to:
        orphan_cte += " AND o.occurred_at <= :end"
        params["end"] = f"{to} 23:59:59" if len(to) == 10 else to
    orphan_cte += " ORDER BY o.occurred_at DESC LIMIT :lim"

    # Distinct non-mass 1:1 senders to (account, fan) in the window before the
    # sale — the assignment candidates. `mass_run_id IS NULL` keeps blasts out.
    # lookback_days is a validated int (Query ge=1 le=90), safe to inline.
    cand_sql = sql_text(
        f"""
        SELECT m.sent_by_employee_id AS eid, e.display_name AS name,
               MAX(m.created_at) AS last_at
          FROM messages m
          LEFT JOIN employees e ON e.id = m.sent_by_employee_id
         WHERE m.account_id = :aid AND m.fan_id = :fid AND m.direction = 'out'
           AND m.sent_by_employee_id IS NOT NULL
           AND m.mass_run_id IS NULL
           AND m.created_at <= :occ
           AND m.created_at > datetime(:occ, '-{int(lookback_days)} days')
         GROUP BY m.sent_by_employee_id, e.display_name
         ORDER BY last_at DESC
        """
    )

    def _iso(v: Any) -> str | None:
        if v is None:
            return None
        return v if isinstance(v, str) else (v.isoformat() if hasattr(v, "isoformat") else str(v))

    async with get_session() as s:
        rows = (await s.execute(sql_text(orphan_cte), params)).all()
        out: list[dict[str, Any]] = []
        for r in rows:
            occ = _iso(r.occurred_at)
            cands: list[dict[str, Any]] = []
            if r.fan_id is not None and occ is not None:
                crows = (await s.execute(cand_sql, {
                    "aid": r.account_id, "fid": r.fan_id, "occ": occ,
                })).all()
                cands = [
                    {"employee_id": int(c.eid), "name": c.name, "last_at": _iso(c.last_at)}
                    for c in crows if c.eid is not None
                ]
            out.append({
                "id": int(r.id),
                "account_id": r.account_id,
                "fan_id": int(r.fan_id) if r.fan_id is not None else None,
                "kind": r.kind,
                "status": r.status,
                "amount_cents": int(r.amount_cents or 0),
                "occurred_at": occ,
                "description": r.description,
                "attributed_employee_id": (
                    int(r.attributed_employee_id)
                    if r.attributed_employee_id is not None else None
                ),
                # "No one" (sales_attribution.NO_ONE) names no Employee row.
                "attributed_employee_name": ("No one" if r.attributed_employee_id == 0
                                             else r.attributed_employee_name),
                "candidate_chatters": cands,
            })
    return {"rows": out}


# ── Relay root ─────────────────────────────────────────────────
# The product UI is the Next app (app/); the relay root just identifies itself.

@app.get("/", include_in_schema=False)
def root():
    return {"service": "openinflowwww-relay", "ok": True}
