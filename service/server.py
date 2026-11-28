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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES as _GZIP_SKIP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field, field_validator

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

_CELLS = bool(os.environ.get("OI_CELL_MAP"))
if _CELLS:
    import cell_mode  # noqa: E402
    cell_mode.boot_check()

from isotime import parse_iso  # noqa: E402

import accounts as account_registry  # noqa: E402
import admission  # noqa: E402  # bounded-concurrency lanes (see service/admission.py)
import lane_config  # noqa: E402  # durable store behind the Concurrency panel
import account_health  # noqa: E402  # dead-session pause (see service/account_health.py)
import pump_reconcile  # noqa: E402  # the pump supervisor's pass, pure (see service/pump_reconcile.py)
import account_page  # noqa: E402  # free-vs-paid page (see service/account_page.py)
import runtime_switches  # noqa: E402  # Settings → System switches (OFM_NEW_WRITES_ENABLED gates ofm-not-yet writes)
import ownership  # noqa: E402  # owned-media semantics (see service/ownership.py)
import proxies as proxy_registry  # noqa: E402
from brand import BRAND_NAME  # noqa: E402
import proxy_health  # noqa: E402  # proxy up/down + trace probe (2.14)
import live_rev  # noqa: E402
import sign_rules  # noqa: E402  # one sign-rule refresh for every account (2.17)
import secrets_store  # noqa: E402  # UI-writable key store (Setup → Keys)
import owner_tokens as _owner_tokens  # noqa: E402  # `Bearer ifw_…` parse, for the share-token gate
import token_auth as _token_auth  # noqa: E402  # owner-token cookie strip (ASGI) + route allowlist
from of_client import DEFAULT_TIMEOUT_S, IMPERSONATE, INTERACTIVE_READ, OF_CDN_SUFFIXES, READ_TIMING, OFClient, OFAPIError, OFDeactivatedError, OFDeniedError, OFDispatchRefused, OFSessionRetired, OFSignedPoolBusy, PRE_DISPATCH, timing_add  # noqa: E402
from of_sends import SendsMixin  # noqa: E402
from of_rich_text import MARKUP_MAX, is_of_html, sanitize_of_html  # noqa: E402
import client_pool  # noqa: E402 — the relay's one OFClient pool
import platforms  # noqa: E402
from curl_cffi import requests as curl_requests  # noqa: E402  # proxy/network error types

from db import init_db as db_init  # noqa: E402
from db.repo import ensure_user_account_link, sync_from_disk as _sync_db_from_disk  # noqa: E402
from events import (  # noqa: E402
    handle_event as _sse_handle_event,
    is_app_tab,
    js_safe_id,
    owner_audience,
    publish_chat_responded,
    ring_seq as _sse_ring_seq,
    sessions_audience,
    sse_stats as _sse_stats,
    sse_stream,
    start_persist_worker as _start_persist_worker,
)
from events_persist import stop_persist_worker as _stop_persist_worker  # noqa: E402
from employees import router as _employees_router, audit_middleware as _audit_middleware  # noqa: E402
from audit_log import credential_write as _credential_write  # noqa: E402
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
from events_decide import is_plain_chat_view  # noqa: E402
import relay_cache  # noqa: E402  # in-process TTL cache for hot-path OF endpoints (Stage C will wire call-sites)
import of_promos  # noqa: E402  # `to_cents`, OF's dollars to our cents
import of_paging  # noqa: E402
import of_pacing  # noqa: E402  # background walks: the per-Creator pacer, 429 retry, busy signal
import of_call_counter  # noqa: E402  # every OF call counted (Caller kind, path, Creator, status), to a file
import stats_file  # noqa: E402  # lane-stats file: path, read, tmp + os.replace
import relay_coalesce  # noqa: E402  # in-flight dedup for idempotent OF GETs (Stage B-2)
from bg_lane import BgLane, BgLease  # noqa: E402  # a Creator's background sub-cap, loop + threads
import relay_hooks  # noqa: E402
import send_tripwire  # noqa: E402
import side_effect_gate  # noqa: E402
import read_flip  # noqa: E402  # what follows a landed read flip (routes + automations)
import chats_page  # noqa: E402  # one logical page of OF /chats
import db_retention  # noqa: E402  # DB retention loops (raw_json, audit, optimize, payload cap)
from lists import router as _lists_router  # noqa: E402
from automation_rules_api import router as _automation_rules_router  # noqa: E402
from translate_api import router as _translate_router  # noqa: E402
from funnels_api import router as _funnels_router  # noqa: E402
from unconfirmed_sends_api import cell_router as _unconfirmed_cell_router, router as _unconfirmed_sends_router  # noqa: E402
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
from vault_download_api import CUT_SHORT as _vault_cut_short, router as _vault_download_router  # noqa: E402
from style_config_api import router as _style_config_router  # noqa: E402
from account_config_api import router as _account_config_router  # noqa: E402
from of_consent_api import router as _of_consent_router  # noqa: E402
from ofm_writes_api import OFM_NEW_WRITES, router as _ofm_writes_router  # noqa: E402
from of_live_window import router as _of_live_window_router  # noqa: E402
from assistant_api import router as _assistant_router  # noqa: E402
import support_api as _support_api  # noqa: E402
import support_hub as _support_hub  # noqa: E402
from assistant_draft import router as _assistant_draft_router  # noqa: E402
from report_recipe_api import router as _report_recipe_router  # noqa: E402
import report_recipe as _report_recipe  # noqa: E402
import report_recipe_api as _report_recipe_api  # noqa: E402
from copilot_api import router as _copilot_router  # noqa: E402
from smart_lists_api import router as _smart_lists_router  # noqa: E402
from trial_links_api import router as _trial_links_router  # noqa: E402
from tracking_links_api import router as _tracking_links_router  # noqa: E402
import tracking_stats  # noqa: E402
from db.engine import sync_database_url  # noqa: E402
from of_tracking_api import router as _of_tracking_router  # noqa: E402
from link_metrics import router as _link_metrics_router  # noqa: E402
from promotions_api import router as _promotions_router  # noqa: E402
from promotions_api import (IN_FLIGHT as _PROMO_IN_FLIGHT,  # noqa: E402
                            reserve_manual as _promo_reserve_manual,
                            untick_kept_promo as _untick_kept_promo)
import promo_create_guard  # noqa: E402
from link_share_api import router as _link_share_router  # noqa: E402
from bio_pages.admin import router as _bio_admin_router  # noqa: E402
from owner_tokens_api import router as _owner_tokens_router  # noqa: E402
import mcp_api  # noqa: E402  # hosted MCP server, POST /admin/mcp (bearer or no-credential surface)
import mcp_oauth  # noqa: E402  # the MCP client's browser sign-in: /.well-known/oauth-*, /auth/oauth/*
import ultra_api  # noqa: E402  # Ultra plans: POST /admin/ultra/plans, GET …/{id}, POST …/ok, …/cancel
from full_ai_api import router as _full_ai_router  # noqa: E402
from tenant_keys_api import (  # noqa: E402
    router as _tenant_keys_router,
    admin_router as _tenant_keys_admin_router,
    status_router as _ai_key_status_router,
)
from system_admin_api import router as _system_admin_router  # noqa: E402
from settings_api import router as _settings_router  # noqa: E402
import notifications_api  # noqa: E402
import push_api  # noqa: E402
from shifts_api import router as _shifts_router  # noqa: E402
from employee_groups_api import router as _employee_groups_router  # noqa: E402
from sensitive_words_api import router as _sensitive_words_router  # noqa: E402
from scripts_import_api import router as _scripts_import_router  # noqa: E402
from script_fill_api import router as _script_fill_router  # noqa: E402
from clock_api import router as _clock_router, _sweep_callers_agencies  # noqa: E402
from sales_amend import router as _sales_amend_router  # noqa: E402
from s4s_api import router as _s4s_router  # noqa: E402
from s4s_requests_api import router as _s4s_requests_router, expire_callers_requests as _expire_s4s_requests  # noqa: E402
from s4s_schedule_api import router as _s4s_schedule_router  # noqa: E402
from s4s_media import router as _s4s_media_router  # noqa: E402
import leak_tracker_api as _leak_tracker_api  # noqa: E402
from leak_tracker_api import router as _leak_tracker_router  # noqa: E402
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
import split_inbox  # noqa: E402
import unread_total  # noqa: E402  # registers `values.unread_total` with the Shared refresher (UNREAD_TOTAL); on_reply


def _kick_db_sync(reason: str) -> None:
    _on_main_loop(lambda: _sync_db_from_disk(), f"db-sync-{reason}")


def _redact(s: str) -> str:
    return re.sub(r"://[^/@]+@", "://***@", s)

log = logging.getLogger("of-relay")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

account_registry.migrate_legacy()

def _migrate_proxy_bindings_to_accounts() -> None:
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
    r = proxy_registry.sync_pool(os.environ.get(proxy_registry.POOL_ENV))
    for err in r["errors"]:
        log.warning("%s: bad line %s", proxy_registry.POOL_ENV, err)
    if r["skipped"]:
        return
    log.info("Inflowwww proxy pool: %d proxies, %d account(s) re-picked, %d left without one",
             r["size"], r["rebound"], r["dropped"])

app = FastAPI(title="OF Relay", version="0.1.0",
              dependencies=[Depends(cell_mode.route_guard)] if _CELLS else None,
              **({"docs_url": None, "redoc_url": None, "openapi_url": None} if _CELLS else {}))
if _CELLS:
    app.add_middleware(cell_mode.FaninTags)

# Registered FIRST (innermost but cell mode's FaninTags): the hook chain re-streams bodies in chunks, so GZip behind it could not see a small body whole and `minimum_size` would stop applying.
app.add_middleware(
    GZipMiddleware,
    minimum_size=1024,
    compresslevel=6,
    exclude_content_types=(*_GZIP_SKIP, "image/*", "application/octet-stream",
                           "binary/octet-stream"),
)

# A hook added LAST runs OUTERMOST (Starlette ordering); the comments at each site rely on it.
_http_hooks = HookChain()
app.add_middleware(BaseHTTPMiddleware, dispatch=_http_hooks.dispatch)
# Outside the hook chain: a `Bearer ifw_` request loses Cookie and X-Employee-Id before any hook sees a cookie identity beside a token.
app.add_middleware(_token_auth.StripCookieIdentities)


class _DbBusy503:

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = False

        async def tracked(msg):
            nonlocal started
            started = started or msg["type"] == "http.response.start"
            await send(msg)

        try:
            await self.app(scope, receive, tracked)
        except _sqla_exc.TimeoutError:
            if started:
                raise
            log.warning("db pool busy: 503 %s %s", scope.get("method"), scope.get("path"))
            await JSONResponse(status_code=503, headers={"Retry-After": "5"},
                               content={"detail": "database busy, retry shortly"})(scope, receive, send)


from sqlalchemy import exc as _sqla_exc  # noqa: E402
app.add_middleware(_DbBusy503)
from db import write_telemetry as _write_telemetry  # noqa: E402
_http_hooks.add(_write_telemetry.label_request_writes)
_http_hooks.add(of_call_counter.label_request_calls)

import llm_client as _llm_client  # noqa: E402  (the key-error handler below)
import vault_sweep as _vault_sweep  # noqa: E402  (the sweep-stop handler below)


# _proxy() maps only OFAPIError: a Backend's API error would otherwise be a generic 500 with its message lost.
def _backend_api_error_handler(key: str):
    async def handle(request, exc):  # noqa: ANN001
        return JSONResponse(status_code=getattr(exc, "status_code", 502),
                            content={"ok": False, "error": key, "detail": str(exc)})
    return handle


for _p in platforms.ALL:
    if _p.backend is not None:
        app.add_exception_handler(_p.backend.APIError, _backend_api_error_handler(_p.key))


@app.exception_handler(of_paging.ListGone)
async def _list_gone_handler(request: Request, exc: of_paging.ListGone):
    return JSONResponse(status_code=501,
                        content={"ok": False, "error": platforms.for_account(_current_aid()).key,
                                 "detail": str(exc)})


@app.exception_handler(_llm_client.LLMKeyError)
async def _llm_key_error_handler(request, exc):  # noqa: ANN001
    log.warning("llm key error path=%s kind=%s provider=%s purpose=%s",
                request.url.path, exc.kind, exc.provider, exc.purpose)
    return JSONResponse(status_code=424,
                        content={"detail": _llm_client.key_error_payload(exc)})

@app.exception_handler(_vault_sweep.SweepStop)
async def _sweep_stop_handler(request, exc):  # noqa: ANN001
    log.warning("sweep stop path=%s: %s", request.url.path, exc.message)
    return JSONResponse(status_code=424, content={"detail": {"error": "stopped", **exc.payload()}})

app.add_exception_handler(_report_recipe.RecipeError, _report_recipe_api.refused)


@app.exception_handler(platforms.UnknownPlatformKey)
async def _unknown_platform_key_handler(request, exc):  # noqa: ANN001
    return JSONResponse(status_code=501, content={"detail": exc.reason})


@app.exception_handler(405)
async def _leak_paths_never_answer_405(request, exc):  # noqa: ANN001
    if _leak_tracker_api.owns(request.url.path):
        return _leak_tracker_api.hidden()
    return await http_exception_handler(request, exc)

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
app.include_router(_unconfirmed_sends_router)
if _CELLS:
    app.include_router(_unconfirmed_cell_router)
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
app.include_router(_vault_download_router)
app.include_router(_style_config_router)
app.include_router(_account_config_router)
app.include_router(_of_consent_router)
app.include_router(_ofm_writes_router)
app.include_router(_of_live_window_router)
app.include_router(_assistant_router)
app.include_router(_support_api.router)
app.include_router(_support_hub.router)
app.include_router(_assistant_draft_router)
app.include_router(_report_recipe_router)
app.include_router(_copilot_router)
app.include_router(_tenant_keys_router)
app.include_router(_tenant_keys_admin_router)
app.include_router(_owner_tokens_router)
app.include_router(mcp_api.router)
app.include_router(mcp_oauth.router)
app.include_router(ultra_api.router)
app.include_router(_ai_key_status_router)
app.include_router(_system_admin_router)
app.include_router(_settings_router)
app.include_router(notifications_api.router)
app.include_router(push_api.router)
app.include_router(_employee_groups_router)
app.include_router(_sensitive_words_router)
app.include_router(_scripts_import_router)
app.include_router(_script_fill_router)
app.include_router(_shifts_router, dependencies=[Depends(_sweep_callers_agencies)])
app.include_router(_clock_router, dependencies=[Depends(_sweep_callers_agencies)])
app.include_router(_sales_amend_router)
if not _CELLS:
    app.include_router(_leak_tracker_router)
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
if fleet_api.enabled():
    app.include_router(fleet_api.router)
if _CELLS:
    import actor_token  # noqa: E402
    import cell_hold  # noqa: E402
    import restore_reconcile  # noqa: E402
    app.include_router(cell_hold.router)
    app.include_router(restore_reconcile.router)
if _CELLS and cell_mode.is_control():
    import agency_copy  # noqa: E402
    import cell_notices  # noqa: E402
    import creator_reservations  # noqa: E402
    app.include_router(agency_copy.router)
    app.include_router(cell_notices.router)
    app.include_router(creator_reservations.router)
    app.include_router(actor_token.router())
app.include_router(_chatters_router)
app.include_router(_chatters_admin_router)
app.include_router(_smart_lists_router)
app.include_router(_trial_links_router)
app.include_router(_tracking_links_router)
app.include_router(tracking_stats.router)
app.include_router(_of_tracking_router)
app.include_router(_link_metrics_router)
app.include_router(_promotions_router)
app.include_router(_link_share_router)
app.include_router(_bio_admin_router)
app.include_router(_full_ai_router)

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


async def _account_isolation_middleware(request: Request, call_next):
    path = request.url.path
    if not (path.startswith("/admin/") or path.startswith("/api/of/")):
        return await call_next(request)

    # No /admin/ twin of these: /admin/:path* is rewritten from the public host, so an ungated one would be a public door.
    if path in _UNAUTHENTICATED_PATHS:
        return await call_next(request)

    user = _get_request_user()
    if user is not None:
        allowed_ids: frozenset[str] | None = user.account_ids
    else:
        chatter = _get_request_chatter()
        allowed_ids = chatter.account_ids if chatter is not None else None
    if allowed_ids is None:
        # Nobody signed in: 401, never abstain (abstaining left /admin/accounts open without a cookie).
        if _allow_anonymous_account_access():
            return await call_next(request)
        if mcp_api.anonymous_surface(request.method, path):
            return await call_next(request)
        if _CELLS and (refusal := actor_token.refused(path, "actor_missing")):
            return refusal
        return Response("sign in required", status_code=401)

    candidates: set[str] = set()
    qaid = request.query_params.get("account_id")
    if qaid:
        candidates.add(qaid)
    for seg in path.split("/"):
        if seg.isdigit() and 5 <= len(seg) <= 12:
            candidates.add(seg)
    if not candidates:
        return await call_next(request)

    # `is_account` raises rather than guess if it can't read the tree: a gate that can't answer must not allow.
    # A Creator a data Cell doesn't own is route_guard's 409 not_owner: the app reloads Placement on it, not on 403.
    stray = {qaid} if _CELLS and qaid and not cell_mode.is_control() and qaid not in cell_mode.owned_ids() else set()
    if any(account_registry.is_account(c) for c in candidates - allowed_ids - stray):
        if _leak_tracker_api.owns(path):
            return _leak_tracker_api.hidden()
        return Response("not your account", status_code=403)
    return await call_next(request)


_DEACTIVATED_DETAIL = {
    "error": "account_deactivated",
    "message": "This Creator is deactivated. Activate it on Creators to use it again.",
}


async def _deactivated_write_guard(request: Request, call_next):
    if request.method in ("GET", "HEAD", "OPTIONS") or not request.url.path.startswith("/api/of/"):
        return await call_next(request)
    aid = request.headers.get("x-account-id") or request.query_params.get("account_id")
    if not aid:
        default = account_registry.get_active_account_id()
        owned = _require_actor_account_ids()
        aid = default if default and (owned is None or default in owned) else None
    if aid and await account_health.is_deactivated(aid):
        return JSONResponse(status_code=409, content={"detail": _DEACTIVATED_DETAIL})
    return await call_next(request)


async def _bg_admission_route(request: Request, call_next):
    if ((request.headers.get("x-priority") or "").lower() == "background"
            and request.method in ("GET", "HEAD")
            and request.url.path.startswith("/api/of/")):
        async with _bg_admission(request):
            return await call_next(request)
    return await call_next(request)


# Registered AFTER the share-token gate: the gate runs first, so only authed requests reach the audit writer.
_http_hooks.add(_audit_middleware)

# After every gate has admitted the request (never tells a stranger a Creator is off), before audit: a refused write writes no `actions` row.
_http_hooks.add(_deactivated_write_guard)

# Registered after audit so it runs before it: a refused request reaches no handler and writes no `actions` row.
_http_hooks.add(role_enforcement_middleware)

# Admission is inside tenant isolation and outside role enforcement. The
# queued request's role is checked only after it receives a background slot.
_http_hooks.add(_bg_admission_route)

# LOAD-BEARING slot: registered BEFORE both session middlewares so it RUNS AFTER them and sees the principal; registered below them it sees none and silently does nothing. Do not move.
_http_hooks.add(_account_isolation_middleware)

# Registered BEFORE the User session middleware so it runs AFTER it: the admin-gate reads get_request_user() and fires only with no User cookie.
_http_hooks.add(_chatter_session_middleware)

_http_hooks.add(_auth_session_middleware)


SHARE_TOKEN = os.environ.get("SHARE_TOKEN", "").strip()
_SHARE_COOKIE = "share_token"


def _effective_share_token() -> str:
    try:
        s = secrets_store.stored("SHARE_TOKEN")
        if s:
            return s
    except Exception:
        pass
    return SHARE_TOKEN


_request_ctx: ContextVar[Request | None] = ContextVar("of_relay_request", default=None)


@_http_hooks.add
async def _account_context(request: Request, call_next):
    token = _request_ctx.set(request)
    try:
        return await call_next(request)
    finally:
        _request_ctx.reset(token)


# EVERY route under /share/ is public (unguessable per-share secret, one row, no calls): put nothing else there.
_PUBLIC_PREFIXES = ("/auth/", "/chatter/", "/t/", "/share/")


@_http_hooks.add
async def _share_token_gate(request: Request, call_next):
    share_token = _effective_share_token()
    if not share_token or (_CELLS and request.url.path == "/api/cell/hold"):
        return await call_next(request)
    if request.url.path == "/health" or request.url.path == "/livez":
        return await call_next(request)
    # The hub checks its own owner cookie / instance token on every route.
    if _support_hub.owns(request.url.path):
        return await call_next(request)
    if request.url.path.startswith(_PUBLIC_PREFIXES):
        return await call_next(request)
    if request.url.path in _UNAUTHENTICATED_PATHS:
        return await call_next(request)
    if mcp_api.anonymous_surface(request.method, request.url.path):
        return await call_next(request)
    if request.url.path in mcp_oauth.PUBLIC_PATHS:
        return await call_next(request)
    if request.cookies.get(_SHARE_COOKIE) == share_token:
        return await call_next(request)
    if request.cookies.get(_AUTH_COOKIE_NAME) or request.cookies.get(_CHATTER_COOKIE_NAME):
        return await call_next(request)
    if _CELLS and request.cookies.get(actor_token.COOKIE):
        return await call_next(request)
    if _owner_tokens.bearer(request.headers.get("authorization")):
        return await call_next(request)
    if request.query_params.get("t") == share_token:
        resp = await call_next(request)
        resp.set_cookie(
            _SHARE_COOKIE, share_token,
            max_age=7 * 24 * 3600, httponly=True, samesite="lax",
        )
        return resp
    if _CELLS and (refusal := actor_token.refused(request.url.path, "actor_missing")):
        return refusal
    # `no-store` on the refusal: a cached 401 would outlive the token that fixes it.
    return Response("unauthorized — link missing or expired", status_code=401,
                    headers={"Cache-Control": "no-store"})




# MASTER ONLY, both verbs: house keys, not a tenant's; nothing else gates them (any auth cookie passes the share gate) and the masked hint leaks the last four chars.
@app.get("/admin/secrets")
def admin_secrets_status() -> dict[str, Any]:
    """Masked status of every UI-settable key (set?/source/hint — never the
    raw value). Master only."""
    _require_master()
    return {"keys": secrets_store.status()}


@app.put("/admin/secrets", dependencies=[Depends(_credential_write)])
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


# Written off the event loop (an open() per request stalled everything on a slow disk); a full queue drops lines, never blocks.
_API_LOG_PATH = os.environ.get("OF_API_LOG_PATH") or "/tmp/of-api.log"
_API_LOG_QUEUE_MAX = 10_000
import queue as _queue_mod
import time as _time_mod

_api_log_queue: "_queue_mod.Queue[str]" = _queue_mod.Queue(maxsize=_API_LOG_QUEUE_MAX)


_api_log_write_lock = threading.Lock()


def _api_log_write(lines: list[str]) -> None:
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
# Daemon writer dies at exit: flush what is queued so the last requests are logged.
atexit.register(lambda: _api_log_write([]))

# A share link's URL carries its secret: no log keeps it.
_SHARE_SECRET = re.compile(r"(/share/[^./?\s]*)\.[^/?\s]*")


def redact_share_secret(text: str) -> str:
    return _SHARE_SECRET.sub(r"\1.<secret>", text)


class _RedactShareSecret(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(redact_share_secret(a) if isinstance(a, str) else a for a in record.args)
        return True


logging.getLogger("uvicorn.access").addFilter(_RedactShareSecret())

from request_log import RequestLog as _RequestLog  # noqa: E402
app.add_middleware(_RequestLog, redact=redact_share_secret)


class _CutShortStreams:

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") == "HEAD":
            return await self.app(scope, receive, send)
        want, sent = None, 0
        mark: dict = {}
        _vault_cut_short.set(mark)

        async def guard(msg):
            nonlocal want, sent
            if msg["type"] == "http.response.start":
                if msg.get("status") not in (204, 304):
                    want = next((int(v) for k, v in msg.get("headers", ()) if k.lower() == b"content-length"), None)
            elif msg["type"] == "http.response.body":
                sent += len(msg.get("body", b""))
                if not msg.get("more_body", False) and (
                        sent < want if want is not None else mark.get("cut")):
                    return
            await send(msg)

        await self.app(scope, receive, guard)


app.add_middleware(_CutShortStreams)
if _CELLS:
    app.add_middleware(cell_mode.CellGenHeader)
    app.add_exception_handler(proxy_registry.NoProxyRefused, cell_mode.no_proxy_refused)
    app.add_exception_handler(cell_hold.CellHeld, cell_hold.refused)


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
async def _no_store_by_default(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("cache-control", "no-store")
    return response


@_http_hooks.add
async def _persist_unhandled_errors(request: Request, call_next):
    try:
        return await call_next(request)
    except (HTTPException, _sqla_exc.TimeoutError):
        # A pool timeout is backpressure (_DbBusy503): writing its row would take another connection from the exhausted pool.
        raise
    except Exception as exc:
        import traceback as _tb
        try:
            from db.engine import get_session
            from db.models import AppError as _AE
            _scrub = proxy_registry.scrub_pool_secrets
            stack = _scrub("".join(_tb.format_exception(type(exc), exc, exc.__traceback__)))[:16384]
            account_id, employee_id = await diag_api.owned_attribution(
                *diag_api.header_attribution(request))
            async with get_session() as s:
                s.add(_AE(
                    source="server",
                    kind=type(exc).__name__[:64],
                    message=_scrub(str(exc))[:4096],
                    stack=stack,
                    url=str(request.url)[:1024],
                    account_id=account_id,
                    employee_id=employee_id,
                    user_agent=(request.headers.get("user-agent") or "")[:512] or None,
                    context_json=json.dumps({"request_id": getattr(request.state, "request_id", None)}),
                ))
                await s.commit()
        except Exception:
            log.exception("failed to persist server-side error to app_errors")
        # A session-dead error (wrong user, OTP required, no session) pauses the account and drops the pooled client so a re-captured session loads on the next request.
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




_event_stats: dict[str, Any] = {
    "received": 0,
    "by_type": {},
    "by_account": {},
    "started_at": None,
    "last_event_ts": None,
}

async def _broadcast_event(event: dict) -> None:
    _event_stats["received"] += 1
    _event_stats["last_event_ts"] = _time_mod.time()
    if isinstance(event, dict):
        for k in event:
            if k.startswith("__"):
                continue
            _event_stats["by_type"][k] = _event_stats["by_type"].get(k, 0) + 1
        aid = event.get("__account_id")
        if aid:
            _event_stats["by_account"][aid] = _event_stats["by_account"].get(aid, 0) + 1

    try:
        await _sse_handle_event(event)
    except Exception:
        log.exception("SSE handle_event failed")


_account_pumps: dict[str, asyncio.Task] = {}


@dataclass
class _PumpRun:
    started: float
    restarts: int = 0
    due: float | None = None


_pump_runs: dict[str, _PumpRun] = {}
_supervisor_task: asyncio.Task | None = None
_tx_ingest_task: asyncio.Task | None = None
_tx_fast_task: asyncio.Task | None = None
_automation_exec_task: asyncio.Task | None = None
_main_loop: asyncio.AbstractEventLoop | None = None


# Every sweeper used to sleep BEFORE its first pass, so the daily ones never ran on a relay restarted more often than daily (tables grew unbounded); `first_after_s` makes each caller state it.
async def _periodic(
    label: str,
    interval_s: float,
    work: Callable[[], Awaitable[None]],
    *,
    first_after_s: float | None = None,
) -> None:
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


async def _ws_pump_for_account(account_id: str) -> bool:
    from of_ws import OFWebSocket, SessionDead, register_pump, unregister_pump
    # A deactivated Creator gets no socket, whichever path spawned this.
    if await account_health.is_deactivated(account_id):
        log.info("ws-pump[%s]: not started, the Creator is deactivated", account_id)
        return False
    while True:
        try:
            meta = account_registry.get_account(account_id) or {}
            nickname = meta.get("nickname") or account_id
            color = meta.get("color")
            if unknown := platforms.unknown_refusal(account_id):
                log.info("ws-pump[%s]: parked, %s", account_id, unknown)
                return True
            platform = platforms.for_account(account_id)
            if platform.backend is not None:
                ws = platform.backend.ws(_load_client(account_id))
            else:
                ws = OFWebSocket(lambda: _load_client(account_id),
                                 session_dead=account_health.is_session_dead_error,
                                 account_id=account_id,
                                 on_reconnect=lambda: relay_hooks.fire_socket_reconnected(account_id))
            register_pump(account_id, ws)
            log.info("ws-pump[%s]: connecting to %s", nickname, platform.label)
            try:
                async for event in ws.events():
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
            # OF rejected the session (e.g. 2FA): pause the account; the supervisor starts no pump while flagged, until a re-login or the recovery probe clears it.
            _invalidate_client(account_id)
            if await account_health.mark_session_dead(account_id, e.reason):
                log.warning("account_session_dead account=%s via=ws-pump reason=%s — automations "
                            "paused until the session recovers", account_id, e.reason)
            log.info("ws-pump[%s]: parked, the session is dead (%s)", account_id, e.reason)
            return True
        except HTTPException as e:
            log.warning("ws-pump[%s]: %s — retry in 30s", account_id, e.detail)
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("ws-pump[%s] unexpected: %s — retry in 10s", account_id, e)
            await asyncio.sleep(10)


def _start_account_pump(account_id: str) -> None:
    try:
        asyncio.get_running_loop()
        _do_start_account_pump(account_id)
    except RuntimeError:
        if _main_loop is None:
            return
        _main_loop.call_soon_threadsafe(_do_start_account_pump, account_id)


def _do_start_account_pump(account_id: str) -> None:
    if _CELLS and str(account_id) not in cell_mode.owned_ids():
        return
    task = _account_pumps.get(account_id)
    if task and not task.done():
        return
    with of_call_counter.caller("loop:ws-pump"):
        task = _account_pumps[account_id] = asyncio.create_task(
            _ws_pump_for_account(account_id), name=f"ws-pump-{account_id}",
        )
    old = _pump_runs.get(account_id)
    _pump_runs[account_id] = _PumpRun(_time_mod.monotonic(), old.restarts if old else 0)
    task.add_done_callback(functools.partial(_on_pump_exit, account_id))


def _on_pump_exit(account_id: str, task: asyncio.Task) -> None:
    if _account_pumps.get(account_id) is not task:
        return
    run = _pump_runs[account_id]
    exc = None if task.cancelled() else task.exception()
    if exc is not None:
        log.error("ws-pump[%s] crashed", account_id, exc_info=exc)
    parked = not task.cancelled() and exc is None and task.result() is True
    now = _time_mod.monotonic()
    run.restarts, run.due = pump_reconcile.restart_due(run.restarts, run.started, now, parked)
    if run.due > now:
        log.info("ws-pump[%s] exited — restart in %.0fs (backoff, attempt %d)",
                 account_id, run.due - now, run.restarts)


def _stop_account_pump(account_id: str) -> None:
    try:
        asyncio.get_running_loop()
        _do_stop_account_pump(account_id)
    except RuntimeError:
        if _main_loop is None:
            return
        _main_loop.call_soon_threadsafe(_do_stop_account_pump, account_id)


def _do_stop_account_pump(account_id: str) -> None:
    _pump_runs.pop(account_id, None)
    task = _account_pumps.pop(account_id, None)
    if task and not task.done():
        task.cancel()


def _restart_account_pump(account_id: str) -> None:
    _stop_account_pump(account_id)
    _start_account_pump(account_id)


def _reroute_account_pump(account_id: str) -> None:
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
    for aid in account_ids:
        _invalidate_client(aid)
        _reroute_account_pump(aid)
        vault_cache.mark_stale(aid)
        _on_main_loop(lambda a=aid: _vault_after_proxy_switch(a), f"vault-proxy-switch-{aid}")


async def _vault_after_proxy_switch(account_id: str) -> None:
    import vault_collect
    await vault_collect.preempt(account_id)
    await vault_cache.invalidate(account_id)
    vault_collect.request_rewarm(account_id)


proxy_registry.on_switch(_on_proxy_switched)


async def _pump_supervisor() -> None:
    while True:
        try:
            await _reconcile_pumps()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("supervisor pass failed")
        await asyncio.sleep(15)


async def _reconcile_pumps() -> None:
    off = await account_health.deactivated_ids()
    with_session = [a["id"] for a in account_registry.list_accounts() if a.get("has_session")]
    if _CELLS:
        with_session = cell_mode.owned_only(with_session)
    parked = set(await account_health.dead_session_map())
    done = {aid: t.done() for aid, t in _account_pumps.items()}
    now = _time_mod.monotonic()
    for act in pump_reconcile.reconcile(with_session, off, parked, done):
        aid = act.account_id
        if isinstance(act, pump_reconcile.Start):
            _start_account_pump(aid)
        elif isinstance(act, pump_reconcile.Stop):
            _stop_account_pump(aid)
        elif isinstance(act, pump_reconcile.Restart):
            run = _pump_runs[aid]
            if run.due is None or now < run.due:
                continue
            log.info("ws-pump[%s] not running (exited, or resumed after park) — restarting (attempt %d)",
                     aid, run.restarts)
            run.restarts += 1
            _start_account_pump(aid)
        else:
            raise TypeError(f"unknown pump action {act!r}")


# CPython keeps only a WEAK ref to a create_task task: a vault import could be collected mid-flight with its carriers still live. Hold until done.
_bg_tasks: set[asyncio.Task] = set()


def _spawn_bg(coro, name: str) -> asyncio.Task:
    with of_call_counter.caller(f"loop:{name}"):
        task = asyncio.create_task(coro, name=name)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


@app.on_event("startup")
async def _close_streams_on_term() -> None:
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


async def _rebind_deactivated_proxies(off: frozenset[str]) -> None:
    try:
        if not proxy_registry.pool_entries():
            return
    except Exception:
        log.exception("could not read proxy pool for deactivated Creator rebind")
        return
    for aid in off:
        try:
            session = account_registry.latest_session_path(aid)
            route = proxy_registry.egress(proxy_registry.registry(), aid, session.name if session else None)
            if isinstance(route, proxy_registry.Direct):
                await asyncio.to_thread(proxy_health.assign_pool, aid)
                log.info("restored proxy binding for deactivated Creator %s", aid)
        except Exception:
            log.exception("could not restore proxy binding for deactivated Creator %s", aid)


@app.on_event("startup")
async def _start_event_pumps() -> None:
    global _supervisor_task, _tx_ingest_task, _tx_fast_task, _automation_exec_task, _main_loop
    _main_loop = asyncio.get_running_loop()
    from of_session_registry import Registry
    Registry.instance()
    _event_stats["started_at"] = _time_mod.time()

    try:
        _sync_proxy_pool()
    except Exception:
        log.exception("Inflowwww proxy pool sync failed — pool unchanged")

    # Boot alone is not a schedule (carriers are 30 days out, the container runs for weeks): also hourly. Best-effort: a sweep failure must never stop boot.
    async def _vault_sweep_once() -> None:
        try:
            res = await asyncio.to_thread(vault_upload.sweep, _load_client)
            if res.get("carriers_failed"):
                log.error("vault sweep: %d orphaned carrier(s) could NOT be "
                          "deleted — check scheduled posts", res["carriers_failed"])
        except Exception as e:  # noqa: BLE001
            log.warning("vault sweep failed: %s", e)

    async def _vault_sweep_loop(gate_loaded: bool) -> None:
        while True:
            if gate_loaded and (off := account_health.write_gate_snapshot()):
                await _rebind_deactivated_proxies(off)
            await _vault_sweep_once()
            await asyncio.sleep(3600)

    # /img holds one thread per open stream; the default ~40-thread pool exhausted into ECONNRESET storms.
    try:
        import anyio
        anyio.to_thread.current_default_thread_limiter().total_tokens = 200
        log.info("anyio thread pool bumped to 200")
    except Exception:
        log.exception("could not bump anyio thread pool — sticking with default")

    # Separate pool from anyio's: the asyncio default executor is min(32, cpus+4) = 6 threads on the 2-CPU VPS, and long sweeps pinned it so sends queued invisibly.
    try:
        from concurrent.futures import ThreadPoolExecutor
        _main_loop.set_default_executor(
            ThreadPoolExecutor(max_workers=_EXECUTOR_THREADS,
                               thread_name_prefix="to-thread")
        )
        log.info("asyncio default executor bumped to %d threads", _EXECUTOR_THREADS)
    except Exception:
        log.exception("could not resize asyncio default executor — default is min(32, cpus+4)")

    # Must precede pump spawn: the SSE writer inserts event_inbox rows from the first event.
    try:
        await db_init()
        log.info("db ready (DATABASE_URL=%s)", _redact(os.environ.get("DATABASE_URL", "(default)")))
        _spawn_bg(tracking_stats.classify_old_rows_background(sync_database_url()), "tracking-click-classify")
    except Exception:
        log.exception("db_init failed — relay will run but SSE/inbox writes will error")
    if _CELLS:
        log.info("Cells: %s data_gen %d", os.environ["OI_CELL_ID"], cell_mode.install_meta(sync_database_url()))
        import send_ops
        log.info("Cells: %d open Send claims turned uncertain at boot", send_ops.install(sync_database_url()))
        import cell_hold
        import restore_reconcile
        restore_reconcile.install(sync_database_url())
        await cell_hold.boot(sync_database_url())
        import agency_copy
        import creator_reservations
        role = cell_mode.role()
        if role == "control":
            creator_reservations.install(sync_database_url())
        log.info("Cells: agency copy %s triggers %s", role, agency_copy.install(sync_database_url(), role))
        if role == "control":
            import employees
            try:
                log.info("Cells: agency rows backfilled for %d owner(s)", await employees.backfill_agency_rows())
            except Exception:
                log.exception("Cells: AGENCY ROW BACKFILL FAILED: an owner or chatter without a Mirror Employee"
                              " gets 503 on data Cells")
        if role == "data":
            log.info("Cells: bootstrap owner grants come from Control")
            from db.engine import engine as _db_engine
            agency_copy.log_read_only_hits(_db_engine.sync_engine)
            age = agency_copy.load_confirmed(agency_copy.db_path(sync_database_url()))
            log.info("Cells: grant age %s (max %.0f s)", "none (no confirmed copy)" if age is None else f"{age:.0f} s",
                     agency_copy.max_grant_age_s())
            _spawn_bg(agency_copy.watch_grant_age(), "grant-age-watch")
            if os.environ.get("OI_CELL_CONTROL_URL"):
                _spawn_bg(agency_copy.poll_forever(agency_copy.db_path(sync_database_url())), "agency-copy-poll")
                _spawn_bg(creator_reservations.retry_activations(), "reservation-activation-retry")
                import cell_notices
                _spawn_bg(cell_notices.forward_forever(), "bell-notices-to-control")
            else:
                log.error("Cells: OI_CELL_CONTROL_URL unset: this data Cell never receives the Agency copy")

    import runtime_switches
    try:
        await runtime_switches.load()
    except Exception:
        log.exception("runtime switch overrides not loaded: env / defaults apply; retrying in the background")
        _spawn_bg(runtime_switches.load_until_loaded(), "runtime-switches-load")

    try:
        await account_health.load_write_gate()
    except Exception:
        log.exception("deactivated Creators not loaded: their OF writes are NOT refused until a restart")
        gate_loaded = False
    else:
        gate_loaded = True
    _spawn_bg(_vault_sweep_loop(gate_loaded), "vault-sweep")

    try:
        from seeds.funnels import seed_defaults_once
        added = [] if _CELLS and cell_mode.role() == "data" else await seed_defaults_once()
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

    try:
        import ultra_run
        n = await ultra_run.recover()
        if n:
            log.warning("ultra: %d running plan(s) marked interrupted", n)
    except Exception:
        log.exception("ultra plan recovery failed: running plans stay running until the next start")

    # MUST stay AFTER db_init: everything below is spawn/network work tests skip, and moving this above leaves the schema uninitialized.
    from automations._common import test_mode
    if test_mode():
        log.info("CHATTERLY_TEST_MODE=1 — skipping pump/supervisor/network spawns")
        return

    # Before pumps spawn, else the first event burst takes the unbounded create_task fallback in events.handle_event.
    _start_persist_worker()

    off = await account_health.deactivated_ids()
    for meta in account_registry.list_accounts():
        if meta.get("has_session") and meta["id"] not in off:
            _start_account_pump(meta["id"])
    _supervisor_task = asyncio.create_task(_pump_supervisor(), name="pump-supervisor")
    log.info("event pumps started for %d account(s)", len(_account_pumps))

    import shared_refresher
    shared_refresher.start()

    asyncio.get_running_loop().run_in_executor(None, live_rev.refresh)

    from storyboard import _storyboard_evictor_loop
    asyncio.create_task(_storyboard_evictor_loop(), name="storyboard-evictor")

    from img_api import _img_cache_evictor_loop
    asyncio.create_task(_img_cache_evictor_loop(), name="img-cache-evictor")

    asyncio.create_task(_perflog_evictor_loop(), name="perflog-evictor")

    asyncio.create_task(db_retention._raw_json_evictor_loop(), name="raw-json-evictor")
    asyncio.create_task(db_retention._payload_size_cap_loop(), name="payload-size-cap")
    asyncio.create_task(db_retention._audit_retention_evictor_loop(), name="audit-retention-evictor")
    asyncio.create_task(db_retention._db_optimize_loop(), name="sqlite-optimize")

    asyncio.create_task(proxy_health.probe_loop(), name="proxy-health-probe")
    asyncio.create_task(proxy_health.rebalance_loop(), name="proxy-rebalance")

    sign_rules.enable_background()

    if not _CELLS or cell_mode.runs_job("clock-in-missed"):
        _spawn_bg(_periodic("clock-in missed", notifications_api.TICK_S, notifications_api.tick,
                            first_after_s=60), "clock-in-missed")

    import link_prewarm
    _spawn_bg(_periodic(
        "link figures prewarm", link_prewarm.PREWARM_PAUSE_S, link_prewarm.prewarm_all,
        first_after_s=600), "link-figures-prewarm")

    import vault_collect
    if vault_collect.ENABLED:
        _spawn_bg(_periodic("vault collect", vault_collect.TICK_S, vault_collect.tick,
                            first_after_s=vault_collect.FIRST_AFTER_S), "vault-collect")

    import leak_tracker
    if leak_tracker.jobs_on():
        _spawn_bg(_periodic("leak watch sync", leak_tracker.SYNC_EVERY_S, leak_tracker.sync_watches,
                            first_after_s=leak_tracker.SYNC_FIRST_AFTER_S), "leak-watch-sync")
        _spawn_bg(leak_tracker.tombstone_loop(), "leak-watch-tombstones")

    relay_hooks.start_background_loops()

    from transaction_ingest import start_supervisor as _start_tx_ingest
    from purchase_poll import start_fast_poll as _start_tx_fast
    _tx_ingest_task = asyncio.create_task(_start_tx_ingest(), name="tx-ingest-supervisor")
    # 30 s purchases-feed poll flips messages.is_paid; shares the per-account lock with the supervisor.
    _tx_fast_task = _spawn_bg(_start_tx_fast(), "tx-ingest-fast-poll")

    import of_stats_daily
    _spawn_bg(of_stats_daily.run_loop(), "of-stats-daily")

    from automation_executor import automation_supervisor as _automation_supervisor
    _automation_exec_task = asyncio.create_task(
        _automation_supervisor(), name="automation-exec",
    )

    import sweep_cadence
    _spawn_bg(_periodic("chat sweep cadence", sweep_cadence.TICK_S, sweep_cadence.tick,
                        first_after_s=sweep_cadence.FIRST_AFTER_S), "chat-sweep-cadence")


if _CELLS:
    @app.on_event("startup")
    async def _start_cell_stats() -> None:
        import importlib
        import cell_stats
        from sqlalchemy.engine import make_url
        eng = importlib.import_module("db.engine")
        cell_stats.instrument(eng._SpillQueuePool)
        url = make_url(eng.DATABASE_URL)
        if url.get_backend_name() == "sqlite" and url.database:
            cell_stats.start(Path(url.database).parent / cell_stats.FILE)


@app.on_event("startup")
async def _start_push() -> None:
    import push_send
    try:
        await push_send.start()
    except Exception:
        log.exception("push_send start failed; push off")


@app.on_event("startup")
async def _promo_fence_notices() -> None:
    try:
        await promo_create_guard.fence_notices()
        await promo_create_guard.duplicate_notices()
    except Exception:
        log.exception("promo fence notices failed")


@app.on_event("shutdown")
async def _stop_push() -> None:
    import push_send
    with contextlib.suppress(Exception):
        await push_send.stop()


_REGISTRY_DRAIN_S = 15.0


@app.on_event("shutdown")
async def _stop_event_pumps() -> None:
    from of_session_registry import Registry
    registry = Registry.instance()
    # Before anything can raise: a clean stop is the one restart that can save the last flush interval.
    _lane_stats_flush(force=True)
    of_call_counter.flush()
    import shared_refresher
    await shared_refresher.stop()
    # Finish every run that claimed a send (a mass on its way to OF) first and start none: a restart never leaves a send half done.
    from automation_executor import drain as _drain_automations
    with contextlib.suppress(Exception):
        await _drain_automations()
    registry.stop_admission()
    # CancelledError is a BaseException: suppress it explicitly or every clean shutdown logs a traceback.
    for task in (_supervisor_task, _tx_ingest_task, _tx_fast_task, _automation_exec_task):
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
    for task in list(_account_pumps.values()):
        if not task.done():
            task.cancel()
    for task in list(_account_pumps.values()):
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    _account_pumps.clear()
    _pump_runs.clear()

    background = list(_bg_tasks)
    for task in background:
        task.cancel()
    if background:
        await asyncio.gather(*background, return_exceptions=True)
    # Bounded: stop_grace_period 75 s minus streams 5 s and the automation drain 45 s leaves ~25 s; a stuck native worker must not eat the persist flush.
    try:
        drained = await asyncio.wait_for(asyncio.to_thread(registry.drain, _REGISTRY_DRAIN_S),
                                         _REGISTRY_DRAIN_S + 1.0)
    except asyncio.TimeoutError:
        registry.stop_event.set()
        drained = False
    if not drained:
        left = [s for s in registry.snapshot() if s.active or s.pins or s.retiring]
        log.warning("registry_drain_timeout after %.0fs: %d slot(s) still owned (active=%d pins=%d retiring=%d)",
                    _REGISTRY_DRAIN_S, len(left), sum(s.active for s in left),
                    sum(s.pins for s in left), sum(s.retiring for s in left))

    # Last: pumps are already cancelled; anything still queued is dropped.
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await _stop_persist_worker()

    client_pool.evict()

    from db.engine import engine as _db_engine
    with contextlib.suppress(Exception):
        await _db_engine.dispose()
    # Last: catches the OF calls a send finished inside the drain above.
    of_call_counter.flush()


_proxy_clients: ContextVar[list[OFClient] | None] = ContextVar("proxy_clients", default=None)


def _load_client(account_id: str) -> OFClient:
    try:
        backend = platforms.require_account(account_id).backend
        if backend is not None:
            return backend.get_client(account_id)
        c = client_pool.get(account_id)
        seen = _proxy_clients.get()
        if seen is not None:
            seen.append(c)
        return c
    except platforms.UnknownPlatformKey as e:
        raise HTTPException(status_code=501, detail=e.reason) from None
    except (FileNotFoundError, ValueError, KeyError) as e:
        error, message = next(v for t, v in (
            (FileNotFoundError, ("no_session", str(e))),
            (ValueError, ("incomplete_signing_rules", str(e))),
            (KeyError, ("bad_session", f"session file is missing {e}")),
        ) if isinstance(e, t))
        raise HTTPException(
            status_code=503,
            detail={
                "error": error,
                "account_id": account_id,
                "message": message,
                "remedy": ["POST /admin/session/bootstrap"],
            },
        ) from None


@dataclass(frozen=True)
class Refuse:
    status: int
    detail: dict[str, Any]


def resolve_account(explicit: str | None, active: Callable[[], str | None],
                    method: Callable[[], str] | None,
                    n_accounts: int) -> str | None | Refuse:
    if explicit:
        return explicit
    if method is not None and n_accounts > 1 and method() not in ("GET", "HEAD"):
        return Refuse(400, {
            "error": "account_required",
            "message": "This write must name its Creator: more than one is reachable.",
            "remedy": ["X-Account-Id header", "?account_id="],
        })
    return active()


def _active_for(request: Request | None) -> Callable[[], str | None]:
    scope = getattr(request, "scope", None)
    if not isinstance(scope, dict):
        return account_registry.get_active_account_id

    def active() -> str | None:
        if "relay.active_account_id" not in scope:
            scope["relay.active_account_id"] = account_registry.get_active_account_id()
        return scope["relay.active_account_id"]
    return active


def _resolve_account_id(request: Request | None) -> str:
    explicit: str | None = None
    if request is not None:
        explicit = request.headers.get("x-account-id") or request.query_params.get("account_id")
    if explicit and account_registry.get_account(explicit) is None:
        raise HTTPException(status_code=404, detail=f"Unknown account_id {explicit!r}")
    # A chatter's set is the UNION across every owner that linked them; None = nobody signed in, so nothing is gated.
    user = _get_request_user()
    chatter = _get_request_chatter() if user is None else None
    principal_ids = (user.account_ids if user is not None
                     else chatter.account_ids if chatter is not None else None)
    reach = principal_ids if principal_ids is not None else account_registry.account_ids()
    aid = resolve_account(
        explicit, _active_for(request),
        None if request is None else (lambda: request.method),
        len(reach))
    if isinstance(aid, Refuse):
        raise HTTPException(status_code=aid.status, detail=aid.detail)
    if aid is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "no_active_account",
                "message": "No account has a captured session yet.",
                "remedy": ["POST /admin/session/bootstrap"],
            },
        )
    if principal_ids is not None and aid not in principal_ids:
        raise HTTPException(status_code=403, detail="not your account")
    return aid


def _current_aid() -> str:
    return _resolve_account_id(_request_ctx.get())


def _get_client(request: Request | None = None) -> OFClient:
    if request is None:
        request = _request_ctx.get()
    return _load_client(_resolve_account_id(request))


def _invalidate_client(account_id: str | None = None, only: OFClient | None = None) -> bool:
    return client_pool.evict(account_id, only=only)


def _kick_clear_session_dead(account_id: str) -> None:
    async def _clear() -> None:
        try:
            if await account_health.clear_session_dead(account_id):
                log.info("account_session_recovered account=%s via=bootstrap "
                         "— automations resume", account_id)
        except Exception:
            log.exception("failed to clear session-dead flag")

    _on_main_loop(_clear, f"session-recover-{account_id}")


def _kick_mark_session_dead(account_id: str, reason: str, via: str) -> None:
    async def _mark() -> None:
        try:
            if await account_health.mark_session_dead(account_id, reason):
                log.warning("account_session_dead account=%s via=%s reason=%s — automations "
                            "paused until the session recovers", account_id, via, reason)
        except Exception:
            log.exception("failed to mark session-dead account")

    _on_main_loop(_mark, f"session-dead-{account_id}")


async def flag_dead_session(account_id: str, exc: BaseException, via: str, client: OFClient | None) -> bool:
    reason = account_health.is_session_dead_error(exc)
    if not reason and exc.__cause__ is not None:
        reason = account_health.is_session_dead_error(exc.__cause__)
    issued = getattr(exc, "of_client", None) or getattr(exc.__cause__, "of_client", None) or client
    if not reason or _invalidate_client(account_id, only=issued) is False:
        return False
    try:
        if await account_health.mark_session_dead(account_id, reason):
            log.warning("account_session_dead account=%s via=%s reason=%s — automations "
                        "paused until the session recovers", account_id, via, reason)
    except Exception:  # noqa: BLE001
        log.exception("failed to mark session-dead account")
    return True


def _on_main_loop(make_coro, name: str) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        if _main_loop is None:
            return
        _main_loop.call_soon_threadsafe(lambda: asyncio.create_task(make_coro(), name=name))
        return
    loop.create_task(make_coro(), name=name)


def _sync_and_link_after_bootstrap(account_id: str) -> None:
    user = _get_request_user()

    async def _run() -> None:
        await _sync_db_from_disk()
        if user is None or (_CELLS and cell_mode.role() == "data"):
            return
        await ensure_user_account_link(user.id, account_id)
        user.account_ids = frozenset(user.account_ids | {account_id})  # type: ignore[misc]

    loop = _main_loop
    if loop is None:
        return
    fut = asyncio.run_coroutine_threadsafe(_run(), loop)
    try:
        # Capped so a slow import can't hang the response; on timeout the coroutine still lands the link: ordering, not this wait, makes it correct.
        fut.result(timeout=10)
    except Exception:
        log.exception("bootstrap sync+link failed for account %s", account_id)


def post_bootstrap_hooks(account_id: str):
    if _CELLS and cell_mode.role() == "data":
        import creator_reservations
        creator_reservations.activate(account_id)
    _invalidate_client(account_id)
    _kick_clear_session_dead(account_id)
    c = _load_client(account_id)
    _restart_account_pump(account_id)
    _sync_and_link_after_bootstrap(account_id)
    return c


# curl_cffi Sessions aren't thread-safe and OF/the proxy cap connections per IP; background calls take BOTH semaphores so user calls keep (total - background) reserved slots. Measured: 100 concurrent users/me from one IP, no knee; the real ceiling is executor threads: accounts x _ACCOUNT_LANE_TOTAL <= _EXECUTOR_THREADS - headroom.
_ACCOUNT_LANE_TOTAL = lane_config.resolve("ACCOUNT_LANE_TOTAL", 5)
# Clamped below total: background >= total would delete the user-slot reservation.
_ACCOUNT_LANE_BACKGROUND = max(1, min(
    _ACCOUNT_LANE_TOTAL - 1 if _ACCOUNT_LANE_TOTAL > 1 else 1,
    lane_config.resolve("ACCOUNT_LANE_BACKGROUND", 2),
))
# Enforced can differ from resolved: told to the store or the panel reports a pending change no restart delivers.
lane_config.record_live("ACCOUNT_LANE_BACKGROUND", _ACCOUNT_LANE_BACKGROUND)

# Default is derived (50 accounts x 5 + 128 headroom = 378): a ThreadPoolExecutor can't be resized so it is read once; threads start only on demand, so it is a ceiling.
_FLEET_ACCOUNTS = 50
_EXECUTOR_HEADROOM = 128


def _accounts_on_disk() -> int:
    try:
        return sum(1 for p in account_registry.ACCOUNTS_DIR.iterdir() if p.is_dir())
    except Exception:
        return 0


_EXECUTOR_THREADS = lane_config.resolve(
    "RELAY_EXECUTOR_THREADS",
    max(_FLEET_ACCOUNTS, _accounts_on_disk()) * _ACCOUNT_LANE_TOTAL + _EXECUTOR_HEADROOM,
)
_account_lanes_lock = threading.Lock()
_account_lanes: dict[str, tuple[threading.BoundedSemaphore, BgLane]] = {}
_lane_stats_lock = threading.Lock()
_lane_stats_since = _time_mod.monotonic()


def _new_lane_stat() -> dict:
    return {
        "calls": 0,
        "calls_user": 0,
        "calls_background": 0,
        "blocked_total": 0,
        "blocked_background": 0,
        "wait_s_total": 0.0,
        "wait_s_background": 0.0,
        "wait_s_max": 0.0,
        "in_flight": 0,
        "in_flight_peak": 0,
        "bg_in_flight": 0,
        "bg_in_flight_peak": 0,
        "loop_waiting_background": 0,
        "loop_waiting_background_peak": 0,
        "threads_waiting_background": 0,
        "threads_waiting_background_peak": 0,
    }


_lane_stats_all: dict = _new_lane_stat()
_lane_stats: dict[str, dict] = {}

# Cumulative counters persist so a window spanning a restart doesn't read as 'no queueing'; live gauges deliberately don't restore.
_LANE_STATS_SCHEMA = 1
_LANE_STATS_FLUSH_S = 30.0
_LANE_CUMULATIVE = ("calls", "calls_user", "calls_background",
                    "blocked_total", "blocked_background",
                    "wait_s_total", "wait_s_background")
_LANE_MAXED = ("wait_s_max", "in_flight_peak", "bg_in_flight_peak",
               "loop_waiting_background_peak", "threads_waiting_background_peak")
_LANE_GAUGES = ("in_flight", "bg_in_flight", "loop_waiting_background", "threads_waiting_background")


def _lane_stats_file() -> Path | None:
    return stats_file.beside_db("PRIORITY_LANE_STATS_PATH", "priority_lane_stats.json")


_LANE_STATS_PATH: Path | None = _lane_stats_file()
_lane_stats_base: dict = _new_lane_stat()
_lane_stats_base_by_account: dict[str, dict] = {}
_lane_stats_started_at: float = _time_mod.time()
_lane_stats_boots: int = 1
_lane_stats_last_flush: float = 0.0
_lane_stats_load_error: str | None = None
_lane_stats_write_error: str | None = None


def _merge_lane_row(dst: dict, src: dict) -> None:
    for k in _LANE_CUMULATIVE:
        v = src.get(k)
        if isinstance(v, (int, float)) and v >= 0:
            dst[k] += v
    for k in _LANE_MAXED:
        v = src.get(k)
        if isinstance(v, (int, float)) and v > dst[k]:
            dst[k] = v


def _lane_row_combined(base: dict, live: dict) -> dict:
    out = _new_lane_stat()
    for k in _LANE_CUMULATIVE:
        out[k] = base[k] + live[k]
    for k in _LANE_MAXED:
        out[k] = max(base[k], live[k])
    for k in _LANE_GAUGES:
        out[k] = live[k]
    return out


def _lane_stats_load() -> None:
    global _lane_stats_started_at, _lane_stats_boots, _lane_stats_load_error
    p = _LANE_STATS_PATH
    if p is None:
        return
    try:
        raw = stats_file.read(p)
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
    global _lane_stats_last_flush, _lane_stats_write_error
    p = _LANE_STATS_PATH
    if p is None:
        return
    now = _time_mod.monotonic()
    if not force and (now - _lane_stats_last_flush) < _LANE_STATS_FLUSH_S:
        return
    _lane_stats_last_flush = now
    try:
        stats_file.write(p, _lane_stats_snapshot())
        _lane_stats_write_error = None
    except Exception as exc:
        _lane_stats_write_error = f"{type(exc).__name__}: {exc}"[:200]


_lane_stats_load()
of_call_counter.start(of_call_counter.stats_path())
_lane_stats_flush(force=True)


def _lane_stat_rows(account_id: str) -> tuple[dict, dict]:
    st = _lane_stats.get(account_id)
    if st is None:
        st = _new_lane_stat()
        _lane_stats[account_id] = st
    return _lane_stats_all, st


def _lane_gauge(account_id: str, key: str, d: int) -> None:
    with _lane_stats_lock:
        for st in _lane_stat_rows(account_id):
            st[key] += d
            if st[key] > st[key + "_peak"]:
                st[key + "_peak"] = st[key]


def _lane_acquire(sem, account_id: str, which: str) -> float:
    if sem.acquire(blocking=False):
        return 0.0
    t0 = _time_mod.monotonic()
    if which == "background":
        _lane_gauge(account_id, "threads_waiting_background", 1)
        try:
            sem.acquire()
        finally:
            _lane_gauge(account_id, "threads_waiting_background", -1)
    else:
        sem.acquire()
    waited = _time_mod.monotonic() - t0
    _lane_record_wait(account_id, which, waited)
    return waited


def _lane_record_wait(account_id: str, which: str, waited: float) -> None:
    ckey = "blocked_background" if which == "background" else "blocked_total"
    wkey = "wait_s_background" if which == "background" else "wait_s_total"
    with _lane_stats_lock:
        for st in _lane_stat_rows(account_id):
            st[ckey] += 1
            st[wkey] += waited


def _lane_entered(account_id: str, priority: str, waited: float, bg_held: bool) -> None:
    # The relay's one 'a person is on this Creator' signal (of_pacing.note_user): vault collector and link prewarm stay off. Requestless/background entries are not a user. RAM-only.
    if priority != "background" and _request_ctx.get() is not None:
        of_pacing.note_user(account_id)
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
    # Outside the lock on purpose: the flush must not hold other lane users behind a disk write.
    _lane_stats_flush()


_bg_lease: ContextVar[BgLease | None] = ContextVar("bg_lease", default=None)
_BG_LANE_LONG_WAIT_S = 30.0


def _bg_long_wait(aid: str, waited: float, where: str, outcome: str) -> None:
    if waited >= _BG_LANE_LONG_WAIT_S:
        log.warning("bg_lane_long_wait account=%s where=%s outcome=%s waited_ms=%d",
                    aid, where, outcome, int(waited * 1000))


@contextlib.asynccontextmanager
async def _bg_admission(request: Request | None = None, *, own: bool = False):
    req = request if request is not None else _request_ctx.get()
    aid = _bg_reads_aid.get() if req is None else None
    if req is not None and (req.headers.get("x-priority") or "").lower() == "background":
        try:
            aid = _resolve_account_id(req)
        except HTTPException:
            aid = None
    held = _bg_lease.get()
    if aid is None or (not own and held is not None and held.aid == aid and not held.closed):
        yield
        return
    lane = _lanes_for(aid)[1]
    t0 = _time_mod.monotonic()
    _lane_gauge(aid, "loop_waiting_background", 1)
    outcome = "gave_up"
    try:
        queued = await lane.admit()
        outcome = "admitted"
    finally:
        _lane_gauge(aid, "loop_waiting_background", -1)
        _bg_long_wait(aid, _time_mod.monotonic() - t0, "loop", outcome)
    waited = _time_mod.monotonic() - t0 if queued else 0.0
    if queued:
        _lane_record_wait(aid, "background", waited)
    lease = BgLease(aid, lane, waited)
    token = _bg_lease.set(lease)
    try:
        yield
    finally:
        _bg_lease.reset(token)
        lease.close()


relay_coalesce.priority_class = lambda: "background" if _current_priority() == "background" else "user"
relay_coalesce.admission = lambda own=False: _bg_admission(own=own)


def _lanes_for(account_id: str) -> tuple[threading.BoundedSemaphore, BgLane]:
    with _account_lanes_lock:
        pair = _account_lanes.get(account_id)
        if pair is None:
            pair = (
                threading.BoundedSemaphore(_ACCOUNT_LANE_TOTAL),
                BgLane(_ACCOUNT_LANE_BACKGROUND),
            )
            _account_lanes[account_id] = pair
        return pair


def _current_priority() -> str:
    req = _request_ctx.get()
    if req is None:
        return "background" if _bg_reads_aid.get() is not None else "user"
    return (req.headers.get("x-priority") or "user").lower()


def _list_header(name: str) -> str | None:
    req = _request_ctx.get()
    return req.headers.get(name) if req is not None else None


_bg_reads_aid: ContextVar[str | None] = ContextVar("bg_reads_aid", default=None)


@contextlib.contextmanager
def _background_reads(account_id: str):
    token = _bg_reads_aid.set(str(account_id))
    try:
        yield
    finally:
        _bg_reads_aid.reset(token)


@contextlib.contextmanager
def _priority_lane(account_id: str | None, priority: str | None = None):
    if not account_id:
        yield
        return
    total, background = _lanes_for(account_id)
    if priority is None:
        priority = _current_priority()
    release_bg, waited = _take_bg(account_id, background) if priority == "background" else (None, 0.0)
    total_held = entered = False
    try:
        waited += _lane_acquire(total, account_id, "total")
        total_held = True
        timing_add("lane_wait_s", waited)
        _lane_entered(account_id, priority, waited, release_bg is not None)
        entered = True
        yield
    finally:
        if entered:
            _lane_exited(account_id, release_bg is not None)
        if total_held:
            try: total.release()
            except ValueError: pass
        if release_bg is not None:
            release_bg()


def _take_bg(account_id: str, background: BgLane) -> tuple[Callable[[], None], float]:
    lease = _bg_lease.get()
    if lease is not None and lease.borrow(account_id):
        return lease.give_back, lease.take_wait()

    def release() -> None:
        try: background.release()
        except ValueError: pass
    if lease is not None and lease.aid == account_id and not lease.closed:
        if background.acquire(blocking=False):
            return release, 0.0
        t0 = _time_mod.monotonic()
        _lane_gauge(account_id, "threads_waiting_background", 1)
        try:
            shared = lease.borrow(account_id, wait=True)
        finally:
            _lane_gauge(account_id, "threads_waiting_background", -1)
        _bg_long_wait(account_id, _time_mod.monotonic() - t0, "lease", "borrowed" if shared else "owner_left")
        if shared:
            waited = _time_mod.monotonic() - t0
            _lane_record_wait(account_id, "background", waited)
            return lease.give_back, waited
    waited = _lane_acquire(background, account_id, "background")
    _bg_long_wait(account_id, waited, "thread", "acquired")
    return release, waited


POOL_PROXY_ERROR = f"{BRAND_NAME} proxy unreachable"


def _pool_safe_error(aid: str | None, text: str, label: str | None = None) -> str:
    p = (proxy_registry.get_by_label(label) if label
         else proxy_registry.get_for_account(aid) if aid else None)
    if not proxy_registry.is_pool(p):
        return proxy_registry.scrub_pool_secrets(text)
    log.warning("inflowwww_proxy_error account=%s: %s", aid, text[:300])
    return POOL_PROXY_ERROR


class _SendRetryExpired(of_pacing.SendDispatchExpired, OFDispatchRefused):
    pass


def _proxy(call, *, client: OFClient | None = None, send: bool = False, started: float | None = None):
    send_deadline = (started or _time_mod.monotonic()) + of_pacing.SEND_BUDGET_S if send else None
    aid: str | None = None
    token = None
    loaded: list[OFClient] = []
    loaded_token = _proxy_clients.set(loaded)
    req = _request_ctx.get()
    background = _current_priority() == "background"
    try:
        if req is not None:
            try:
                aid = _resolve_account_id(req)
            except HTTPException:
                aid = None
            if not background:
                token = INTERACTIVE_READ.set(True)
        def _attempt():
            with _priority_lane(aid):
                t_call = _time_mod.monotonic()
                try:
                    return call()
                except OFSessionRetired as e:
                    # Retry only GETs since a write may have partially reached OF and could repeat a send.
                    # A busy pool was never evicted, so a retry would wait on the same handles.
                    if isinstance(e, OFSignedPoolBusy) or req is None or req.method != "GET":
                        raise
                    log.info("client evicted mid-read account=%s: re-run on the current client", aid)
                    return call()
                finally:
                    timing_add("call_s", _time_mod.monotonic() - t_call)
        if send_deadline is not None:
            previous = PRE_DISPATCH.get()

            def _before_send():
                if _time_mod.monotonic() >= send_deadline:
                    raise _SendRetryExpired("Send window expired before dispatch.")
                return previous() if previous is not None else None

            guard = PRE_DISPATCH.set(_before_send)
            try:
                return of_pacing.absorb_429(
                    aid, _attempt, prio=of_pacing.PERSON_SEND, send_deadline=send_deadline, clock=_time_mod.monotonic)
            finally:
                PRE_DISPATCH.reset(guard)
        if getattr(req, "method", None) == "GET":
            return of_pacing.absorb_429(
                aid, _attempt, prio=of_pacing.BACKGROUND if background else of_pacing.USER_READ)
        return _attempt()
    except of_pacing.SendDispatchExpired as e:
        raise HTTPException(status_code=504, detail="Send window expired before dispatch.") from e
    except send_tripwire.SendBudgetSpent as e:
        raise HTTPException(status_code=502, detail={"upstream_status": "send_budget_spent",
                                                     "upstream_body": str(e)}) from e
    except OFDeactivatedError as e:
        raise HTTPException(status_code=409, detail=_DEACTIVATED_DETAIL) from e
    except OFSessionRetired as e:
        busy = isinstance(e, OFSignedPoolBusy)
        reason = "signed_pool_busy" if busy else "session_retired"
        log.warning("signed_pool_503 account=%s reason=%s method=%s", aid, reason,
                    req.method if req is not None else None)
        raise HTTPException(status_code=503, headers={"Retry-After": "5" if busy else "1"},
                            detail={"upstream_status": reason, "upstream_body": str(e)}) from e
    except OFDeniedError as e:
        raise HTTPException(status_code=403,
                            detail={"upstream_status": "refused_by_relay", "upstream_body": str(e)}) from e
    except OFAPIError as e:
        issued = e.of_client = loaded[-1] if loaded else client
        r = e.response
        status = r.status_code if r is not None else 500
        body = r.text[:2000] if r is not None else str(e)
        log.warning("upstream error: %s %s", status, body[:200])
        # OF rejected the session itself: pause the account and tell its owner; the read still answers 502.
        dead_reason = account_health.is_session_dead_error(e)
        if dead_reason and aid:
            # Only the client that met it: a concurrent read already replaced it, so keep the fresh one.
            if _invalidate_client(aid, only=issued):
                _kick_mark_session_dead(aid, dead_reason, via="proxy")
        raise HTTPException(
            status_code=502,
            detail={"upstream_status": status, "upstream_body": body},
        ) from e
    except curl_requests.exceptions.ProxyError as e:
        log.warning("proxy_unreachable: %s", str(e)[:200])
        raise HTTPException(
            status_code=502,
            detail={"upstream_status": "proxy_unreachable",
                    "upstream_body": _pool_safe_error(aid, str(e)[:500])},
        ) from e
    except curl_requests.exceptions.Timeout as e:
        log.warning("upstream_timeout: %s", str(e)[:200])
        raise HTTPException(
            status_code=504,
            detail={"upstream_status": "timeout", "upstream_body": _pool_safe_error(aid, str(e)[:500])},
        ) from e
    except curl_requests.exceptions.RequestException as e:
        log.warning("upstream_network_error: %s %s", type(e).__name__, str(e)[:200])
        raise HTTPException(
            status_code=502,
            detail={"upstream_status": "network", "upstream_body": _pool_safe_error(aid, str(e)[:500])},
        ) from e
    finally:
        if token is not None:
            INTERACTIVE_READ.reset(token)
        _proxy_clients.reset(loaded_token)


@contextlib.contextmanager
def _of_read_timing(route: str, aid: str | None, chat_id: int | None = None):
    t: dict[str, Any] = {"_t0": _time_mod.monotonic(), "_task": None, "_admit_s": 0.0}
    try:
        t["_task"] = asyncio.current_task()
        lease = _bg_lease.get()
        if lease is not None and not lease.closed:
            t["_admit_s"] = float(lease.waited)
            t["_t0"] -= t["_admit_s"]
    except Exception:  # noqa: BLE001 — a timing line must never fail a read
        pass
    token = READ_TIMING.set(t)
    status: Any = 200
    upstream: Any = "-"
    try:
        yield t
    except HTTPException as e:
        status = e.status_code
        if isinstance(e.detail, dict) and e.detail.get("upstream_status") is not None:
            upstream = e.detail["upstream_status"]
        raise
    except BaseException:
        status = "error"
        raise
    finally:
        READ_TIMING.reset(token)
        try:
            end = _time_mod.monotonic()
            ms = lambda s: int(round(s * 1000))  # noqa: E731
            post0 = t.get("_post_t0")
            log.info(
                "of_read_timing route=%s account=%s chat=%s prio=%s status=%s of_calls=%d "
                "lane_wait_ms=%d signed_wait_ms=%d of_ms=%d post_ms=%d total_ms=%d "
                "caller=%s intent=%s offset=%s limit=%s upstream=%s",
                route, aid or "-", chat_id if chat_id is not None else "-", _current_priority(),
                status, int(t.get("of_calls", 0)), ms(max(t.get("lane_wait_s", 0.0), t["_admit_s"])),
                ms(t.get("signed_wait_s", 0.0)),
                ms(max(0.0, t.get("call_s", 0.0) - t.get("signed_wait_s", 0.0))),
                ms(end - post0) if post0 is not None else 0, ms(end - t["_t0"]),
                t.get("caller", "-"), t.get("intent", "-"), t.get("offset", "-"), t.get("limit", "-"), upstream,
            )
        except Exception:  # noqa: BLE001 — a timing line must never fail a read
            pass


def _timing_post_start() -> None:
    t = READ_TIMING.get()
    if t is not None:
        t["_post_t0"] = _time_mod.monotonic()


def _timing_detach_foreign() -> None:
    t = READ_TIMING.get()
    if t is None:
        return
    try:
        if asyncio.current_task() is not t.get("_task"):
            READ_TIMING.set(None)
    except RuntimeError:
        READ_TIMING.set(None)


def _account_ttl(namespace: str, ttl_seconds: float):
    def wrap(fn):
        @functools.wraps(fn)
        async def cached(**params):
            try:
                aid = _current_aid()
            except HTTPException:
                return await asyncio.to_thread(fn, **params)
            key = (fn.__name__, *sorted(params.items()))
            return await relay_cache.get_or_fetch(
                namespace, aid, key, ttl_seconds, lambda: fn(**params))
        return cached
    return wrap



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


# The budget is not a cancel: c.me() blocks in a worker thread and outlives task cancellation, so asyncio.wait(timeout=) only stops WAITING; each probe frees its slot when it really finishes. Deliberately not near a healthy probe's 0.60s: OFClient.timeout_s is 30s with retries, and a tight budget would flag slow-but-fine sessions.
_HEALTH_PROBE_BUDGET_S = max(1.0, float(os.environ.get("HEALTH_ALL_BUDGET_S", "20")))

# Strong refs: the loop may collect a task nobody holds, mid-OF-call.
_health_probes_running: set[asyncio.Task] = set()


def _probe_account_blocking(aid: str) -> dict[str, Any]:
    try:
        c = _load_client(aid)
        me = c.me()
        # An Inflowwww proxy's label, host and credentials never leave the relay.
        pool = proxy_registry.is_pool(proxy_registry.get_by_label(c.proxy_label or ""))
        row = {"ok": True, "user_id": me.get("id"), "name": me.get("name"),
               "proxy": {"pool": True} if pool else {"label": c.proxy_label, "url": c.proxy_url}}
        if me.get("id") is not None and str(me["id"]) == aid:
            row["profile"] = {key: me.get(key) for key in ("id", "avatar", "avatarThumbs")}
        return row
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
    async with admission.HEALTH_PROBE:
        return await asyncio.to_thread(_probe_account_blocking, aid)


async def _health_all_accounts() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
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
            row.update({"ok": False, "error": "no_session"})
            continue
        if aid in off:
            row.update({"ok": False, "error": "deactivated"})
            continue
        probes[asyncio.create_task(_probe_account(aid))] = row

    if probes:
        done, pending = await asyncio.wait(set(probes), timeout=_HEALTH_PROBE_BUDGET_S)
        for t in done:
            try:
                probes[t].update(t.result())
            except Exception as e:  # noqa: BLE001 — never raises 500
                probes[t].update({"ok": False, "error": f"{type(e).__name__}: {e}"})
        for t in pending:
            _health_probes_running.add(t)
            t.add_done_callback(_health_probes_running.discard)
            probes[t].update({
                "ok": False, "error": "timeout", "timed_out": True,
                "message": f"no answer within {_HEALTH_PROBE_BUDGET_S:g}s; the probe is still running",
            })

    return {"ok": all(r.get("ok") for r in rows) if rows else False,
            "accounts": rows}


def _health_one(request: Request):
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
        # Coalesced: AccountsTable's retry:1 would launch a second fan-out; the retry joins the in-flight probe. The key has no account (identical for every caller); the clamp to the caller's Creators runs after.
        allowed = _require_actor_account_ids()
        snapshot = await relay_coalesce.coalesce(("health_all",), _health_all_accounts)
        return _clamp_health_all(snapshot, allowed)
    return await asyncio.to_thread(_health_one, request)


def _clamp_health_all(snapshot: dict[str, Any], allowed: frozenset[str] | None) -> dict[str, Any]:
    rows = []
    for row in snapshot["accounts"]:
        if allowed is not None and row.get("account_id") not in allowed:
            continue
        row = dict(row)
        if isinstance(row.get("proxy"), dict):
            row["proxy"] = {k: v for k, v in row["proxy"].items() if k != "url"}
        rows.append(row)
    # `ok` recomputed over the caller's rows: another Agency's dead session must not turn this answer false.
    return {**snapshot, "ok": all(r.get("ok") for r in rows) if rows else False,
            "accounts": rows}


_ME_TTL_S = 60.0
_ME_MAX_AGE_MAX_S = 1800


def _users_me_read() -> dict[str, Any]:
    me = _proxy(lambda: _get_client().me())
    account_page.prime(_current_aid(), me)
    return me


@app.get("/api/of/v2/users/me")
async def users_me(max_age: int | None = None) -> dict[str, Any]:
    """The Creator's OF `/users/me`, cached per account for _ME_TTL_S (key `("users_me",)`, shared with
    account_page.of_me). `max_age` (s, clamped to [_ME_TTL_S, _ME_MAX_AGE_MAX_S]): an identity reader (the app's
    `["of-profile"]`: avatars, card name, paid/free) takes a body that old: the plain entry while fresh, else its
    own entry of that TTL, so a new tab's per-Creator avatar reads cost OF nothing for that long. Writes clear
    both (namespace `users_me`, of_client._WRITE_INVALIDATES); a change made on OF web waits out the age asked."""
    try:
        aid = _current_aid()
    except HTTPException:
        return await asyncio.to_thread(_users_me_read)
    key = ("users_me",)
    age = _ME_TTL_S
    held = relay_cache.peek_fresh("users_me", aid, key) if max_age else None
    if held is None:
        if max_age:
            age = int(min(max(max_age, _ME_TTL_S), _ME_MAX_AGE_MAX_S))
            key = (*key, "max_age", age)
        held = await relay_cache.get_or_fetch("users_me", aid, key, age, _users_me_read)
    if await split_inbox.chatter_inbox_filter(aid) is not None:
        return split_inbox.without_count(held, "chatMessagesCount")
    return held


import img_api  # noqa: E402


@contextlib.contextmanager
def _priority_lane_background(account_id: str):
    with _priority_lane(account_id, priority="background"):
        yield


app.include_router(img_api.streams_router)


import diag_api  # noqa: E402
from diag_api import _perflog_evictor_loop  # noqa: E402
app.include_router(diag_api.router)



@app.get("/admin/chats/recent")
async def admin_chats_recent(
    limit: int = Query(25, ge=1, le=100),
    account_id: str | None = Query(None, description="Filter to one account; omit for all"),
) -> dict[str, Any]:
    from db.engine import get_session
    from db.models import Chat as _Chat, Fan as _Fan
    from sqlalchemy import select
    account_ids = clamp_account_filter(account_id)
    if account_ids is not None and not account_ids:
        return {"list": [], "source": "local-db"}
    chatter_id = split_inbox.acting_chatter_id()
    stmt = (
        select(_Chat.account_id, _Chat.fan_id, _Chat.last_message_id, _Chat.last_message_at,
               _Chat.last_message_preview, _Chat.unread_count, _Fan.of_display_name, _Fan.of_username,
               _Fan.avatar_url, _Fan.is_muted)
        .join(_Fan, (_Fan.account_id == _Chat.account_id) & (_Fan.fan_id == _Chat.fan_id), isouter=True)
        .where(_Chat.hidden_locally == False)  # noqa: E712
        .order_by(_Chat.last_message_at.desc().nullslast())
        .limit(limit)
    )
    sig = None
    if account_ids is not None:
        stmt = stmt.where(_Chat.account_id.in_(account_ids))
        if chatter_id is not None:
            await split_inbox.warm(account_ids)
            scope = split_inbox.sql_scope(chatter_id, account_ids, _Chat.account_id, _Chat.fan_id)
            if scope is not None:
                expr, sig = scope
                stmt = stmt.where(expr)

    async def _read() -> list[dict[str, Any]]:
        async with get_session() as s:
            rows = (await s.execute(stmt)).all()
        return [{
            "__accountId": r.account_id,
            "withUser": {"id": js_safe_id(r.fan_id), "name": r.of_display_name,
                         "username": r.of_username, "avatar": r.avatar_url},
            "lastMessage": {
                "id": js_safe_id(r.last_message_id), "text": r.last_message_preview or "",
                "createdAt": r.last_message_at.isoformat() + "Z" if r.last_message_at else None,
            } if r.last_message_id else None,
            "hasUnread": (r.unread_count or 0) > 0,
            "unreadMessagesCount": r.unread_count or 0,
            "isMutedNotifications": bool(r.is_muted),
        } for r in rows]

    key = ("chats_recent", limit, None if account_ids is None else tuple(sorted(account_ids)), sig)
    rows = await relay_coalesce.coalesce(key, _read)
    if chatter_id is not None:
        keeps = {aid: await split_inbox.filter_for(chatter_id, aid) for aid in {r["__accountId"] for r in rows}}
        rows = [r for r in rows if (keep := keeps[r["__accountId"]]) is None or keep(r["withUser"]["id"])]
    return {"list": rows, "source": "local-db"}


app.include_router(img_api.router)


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
            "loop_waiting_background": st["loop_waiting_background"],
            "loop_waiting_background_peak": st["loop_waiting_background_peak"],
            "threads_waiting_background": st["threads_waiting_background"],
            "threads_waiting_background_peak": st["threads_waiting_background_peak"],
            "saturated": st["in_flight"] >= _ACCOUNT_LANE_TOTAL,
        }

    snap = _lane_stats_snapshot()
    overall = _view(snap["overall"])
    rows = {aid: _view(st) for aid, st in snap["accounts"].items()}
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


app.include_router(img_api.cache_router)


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


import storyboard  # noqa: E402
app.include_router(storyboard.router)


@app.get("/admin/coalesce/stats")
def admin_coalesce_stats() -> dict:
    """In-flight request coalescer activity (Stage B-2).

    `coalesced_hits` per namespace = waiters that joined an already-
    in-flight upstream call instead of dispatching a fresh one. A
    non-zero value means the coalescer is doing useful work in prod.
    `first_calls` = the leading caller for each namespace. Ratio
    `coalesced_hits / (first_calls + coalesced_hits)` is the hit rate."""
    return relay_coalesce.stats()


app.include_router(storyboard.stats_router)


_LIST_CHATS_TTL = 600.0
_LIST_CHATS_SWR = 600.0

# Stamped by both fetch sites; past _ROSTER_WINDOW_MAX_AGE_S the badge fold re-reads live, else counts from a near-expiry window could serve ~900s-old state on a WS-dead account.
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
    asked_at = unread_total._clock()
    bg_aid = _bg_reads_aid.get() if _request_ctx.get() is None else None
    with _priority_lane(bg_aid, priority="background"):
        page = chats_page.assemble_chats_page(
            client, limit=limit, offset=offset, order=order, filter=filter, list_id=list_id, q=q,
        )
    if page.throttled is not None:
        raise page.throttled
    return {"list": page.rows, "hasMore": page.has_more, "asked_at": asked_at}


_CHATS_429_HOLD = chats_page.ThrottleHold()


async def _cached_or_held_on_429(namespace: str, aid: str, extras: tuple, **kw: Any) -> tuple[Any, bool]:
    try:
        return await relay_cache.get_or_fetch(namespace, aid, extras, **kw), False
    except HTTPException as e:
        held = relay_cache.peek(namespace, aid, extras) if of_pacing.retry_after(e) is not None else None
        if held is None:
            raise
        log.info("%s 429: served the held copy account=%s", namespace, aid)
        return held, True


@app.get("/api/of/v2/chats")
async def list_chats(
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    order: str = Query("recent"),
    filter: str | None = Query(None, description="OF chat filter: 'unread'|'pinned'|'priority'"),
    list_id: str | None = Query(None, description="Show only chats whose fan is in this custom list (folder)"),
    query: str | None = Query(None, description="Free-text search by fan name/username (OF param: ?query=)"),
    # Legacy alias of `query=` from the first search UI: accepted so deep links don't 400.
    search: str | None = Query(None, description="Alias for `query` (back-compat)"),
    refresh: bool = Query(False, alias="refresh"),
) -> dict[str, Any]:
    aid = _current_aid()
    q = query or search
    coalesce_key = ("list_chats", aid, limit, offset, order, filter, list_id, q)
    plain_view = is_plain_chat_view(filter, list_id, q)
    is_badge_window = (
        limit == _ROSTER_SCAN_MAX and offset == 0 and order == "recent"
        and plain_view
    )
    async def _fetch():
        _timing_detach_foreign()
        # The 429 hold gates the upstream read only: a cached window is still served.
        held = _CHATS_429_HOLD.check(coalesce_key)
        if held is not None:
            raise HTTPException(status_code=held.status_code, detail=held.detail, headers=held.headers)
        def _read():
            value = _assemble_chats_page(
                _get_client(), limit=limit, offset=offset, order=order,
                filter=filter, list_id=list_id, q=q,
            )
            if is_badge_window:
                _chats_window_fetched_at[aid] = _time_mod.monotonic()
                return {**value, "fetched_at": int(_time_mod.time() * 1000)}
            return value
        async def _upstream():
            try:
                with of_pacing.read_budget(of_pacing.LIST_READ_BUDGET_S):
                    return await asyncio.to_thread(_proxy, _read)
            except HTTPException as e:
                wait = of_pacing.retry_after(e)
                if wait is not None:
                    secs = _CHATS_429_HOLD.hold(coalesce_key, e, wait)
                    log.info("list_chats 429 hold account=%s offset=%s caller=%s for %.1fs", aid, offset,
                             chats_page.list_caller(_list_header("x-list-caller")), secs)
                raise
        value = await relay_coalesce.coalesce(coalesce_key, _upstream)
        # Reconcile the local `chats` mirror from a FRESH OF read only: a cached value is a stale SWR window or WS-patched, not OF's read state.
        if value and plain_view:
            chats = value.get("list") or value.get("chats") or []
            if chats:
                from messages import reconcile_chats_from_of
                asyncio.create_task(
                    reconcile_chats_from_of(aid, chats),
                    name=f"reconcile-chats-{aid}",
                )
        return value
    held_before = accounts_admin_api.held_window(aid) if is_badge_window else None
    with _of_read_timing("chats", aid) as t:
        t.update(caller=chats_page.list_caller(_list_header("x-list-caller")),
                 intent=chats_page.list_intent(_list_header("x-list-intent")), offset=offset, limit=limit)
        if chats_page.deep_page_refused(offset, limit, t["intent"]):
            raise HTTPException(status_code=428, detail=chats_page.DEEP_REFUSED_DETAIL)
        resp, _ = await _cached_or_held_on_429(
            "list_chats", aid, (limit, offset, order, filter, list_id, q),
            ttl_seconds=_LIST_CHATS_TTL, fetcher=_fetch, bypass=refresh,
            stale_while_revalidate=_LIST_CHATS_SWR,
        )
        _timing_post_start()
        # Refresh on the plain view drops the cached badge fold, else the badge serves pre-refresh counts for its TTL.
        if refresh and offset == 0 and plain_view:
            relay_cache.invalidate("roster_count", aid)
        held = accounts_admin_api.held_window(aid) if is_badge_window else None
        if held is not None and held is resp and held is not held_before and unread_total.ENABLED:
            try:
                me = getattr(await asyncio.to_thread(_get_client), "user_id", None)
                if me is not None:
                    await accounts_admin_api.fold_held_roster_window(aid, str(me))
            except Exception:
                log.warning("list_chats: fresh page-0 window not folded for %s", aid, exc_info=True)
        scanned = len(resp.get("list") or resp.get("chats") or [])
        resp = split_inbox.filter_rows({**resp, "scanned": scanned}, await split_inbox.chatter_inbox_filter(aid))
        return await _annotate_chat_rows(aid, resp)


async def _annotate_chat_rows(aid: str, resp: dict[str, Any]) -> dict[str, Any]:
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
            continue
    import unread_total_decide
    registry: set[int] = set()
    owed: set[int] = set()
    renew_off: set[int] = set()
    if ids:
        from automations._common import load_of_restricted_ids
        from automations._customs import owed_fan_ids
        from automations.lifecycle_messages import renew_off_fan_ids
        registry = await load_of_restricted_ids(aid)
        owed = await owed_fan_ids(aid) & ids
        renew_off = await renew_off_fan_ids(aid, ids, datetime.utcnow())
    out_rows = []
    stamped = False
    for ch in resp.get(rows_key) or []:
        wu = ch.get("withUser") or {}
        try:
            fid = int(wu.get("id"))
        except (TypeError, ValueError):
            fid = None
        stamp = {}
        if fid in registry:
            stamp["isRestricted"] = True
        if unread_total_decide.excluded_from_badges(wu.get("id"), ch, registry):
            stamp["badgeExcluded"] = True
        if fid in owed:
            stamp["needsHuman"] = True
        if fid in renew_off:
            stamp["autoRenewOff"] = True
        stamped = stamped or bool(stamp)
        out_rows.append({**ch, "withUser": {**wu, **stamp}} if stamp else ch)
    if not stamped:
        return resp
    return {**resp, rows_key: out_rows}


for _wiring in relay_hooks.import_wirings():
    _wiring.wire(app)


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
    aid = _current_aid()
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
    try:
        relay_cache.invalidate("chat_folders", _current_aid())
    except Exception:  # noqa: BLE001
        log.debug("chat_folders invalidation skipped", exc_info=True)


class _PinChatBody(BaseModel):
    pinned: bool


@app.patch("/api/of/v2/lists/{list_id}/pin-chat")
def pin_list_to_chat(list_id: int, body: _PinChatBody = Body(...)) -> dict[str, Any]:
    """Pin or unpin a fan list as a chat-sidebar folder.
    Maps to PATCH /lists/{id} with `{"isPinnedToChat": <bool>}`."""
    out = _proxy(lambda: _get_client().set_list_pinned_to_chat(list_id, body.pinned))
    # `isPinnedToChat` is what the chip strip filters on: without this a fresh pin wouldn't show for a full TTL.
    _invalidate_chat_folders()
    return out


@app.get("/api/of/v2/chats/{chat_id}/messages")
async def get_messages(
    chat_id: int,
    limit: int = Query(10, ge=1, le=100),
    order: str = Query("desc"),
    before_id: int | None = Query(None, description="Paginate older: pass last message id"),
    refresh: bool = Query(False, alias="refresh"),
    peek: bool = False,
) -> dict[str, Any]:
    if peek and order != "desc":
        raise HTTPException(400, "peek requires descending order")
    # Cache ONLY paginated history: no per-message WS invalidator, so the head page (where new messages land) always goes to OF.
    aid = _current_aid()
    with _of_read_timing("messages", aid, chat_id):
        coalesce_key = ("get_messages", aid, chat_id, before_id, limit, order, peek)
        async def _fetch():
            return await asyncio.to_thread(
                _proxy, lambda: _get_client().get_messages(
                    chat_id, limit=limit, order=order, before_id=before_id, peek=peek,
                ),
            )

        held = False
        if before_id is None:
            async def _fetch_head():
                click_at = read_flip.now_ms() if not peek else None
                return click_at, await _fetch()

            click_at, payload = await relay_coalesce.coalesce(coalesce_key, _fetch_head)
            _timing_post_start()
            if isinstance(payload, dict) and aid:
                # A reply sent from OF web / app has no event of its own.
                relay_hooks.fire_thread_head(aid, chat_id, payload.get("list"))
                if click_at is not None:
                    relay_hooks.fire_thread_click_read(aid, chat_id, click_at)
        else:
            # A fan's payment can flip a PPV old message to unlocked: cap at 5min to bound how long it lingers as locked.
            payload, held = await _cached_or_held_on_429(
                "get_messages_tail", aid, (chat_id, before_id, limit),
                ttl_seconds=300.0, fetcher=functools.partial(relay_coalesce.coalesce, coalesce_key, _fetch),
                bypass=refresh,
            )
            _timing_post_start()
        # Stamp stays awaited (the response needs it); persist is a write on the shared SQLite writer nothing here reads back, so fire-and-forget. Same list object: stamp mutates, persist reads.
        if isinstance(payload, dict) and aid:
            of_rows = payload.get("list") or []
            try:
                await stamp_rest_media_dims(str(aid), int(chat_id), of_rows)
            except Exception:  # noqa: BLE001
                log.debug("stamp_rest_media_dims failed for chat %s", chat_id, exc_info=True)
            try:
                own_user_id = getattr(_get_client(), "user_id", None) if of_rows and not held else None
            except Exception:  # noqa: BLE001
                own_user_id = None
            if own_user_id:
                from automations.scrape_chats import save_thread_page  # noqa: PLC0415
                asyncio.create_task(
                    save_thread_page(str(aid), int(chat_id), own_user_id, of_rows,
                                     peek_head=peek and before_id is None),
                    name=f"thread-page-{aid}-{chat_id}",
                )
            if of_rows and not held:
                # persist swallows its own exceptions: in a bare create_task an escaping error would only be an unretrieved-task warning.
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

    One OF request, no pagination (see of_client.get_pinned_messages —
    `hasMore` lies on this filter), cached per (account, chat) for
    `_pins_cache_ttl_s()` and shared by every tab and Employee; the cache's
    per-key lock makes concurrent opens one OF read. Our own message writes
    (pin, unpin, unpin-all, unsend, hide, like, bookmark) clear the account's
    pins (`_proxy_message_write`), and so does every money event (a sale's
    lock/price flip: `chat_pinned` is in `relay_cache._MONEY_FEED_NAMESPACES`),
    so only a change made on OF web can show up to the TTL late. The TTL
    defaults to 300 s like `get_messages_tail`. TTL 0 reads OF every time."""
    async def _fetch() -> dict[str, Any]:
        async with _bg_admission():
            rows = await asyncio.to_thread(
                _proxy, lambda: _get_client().get_pinned_messages(chat_id))
        return {"list": rows}

    ttl = _pins_cache_ttl_s()
    if ttl <= 0:
        return await _fetch()
    return await relay_cache.get_or_fetch(
        "chat_pinned", _current_aid(), (chat_id,), ttl_seconds=ttl, fetcher=_fetch)


def _pins_cache_ttl_s() -> float:
    try:
        return max(0.0, float(os.environ.get("PINS_CACHE_TTL_S", "300")))
    except ValueError:
        return 300.0


def _proxy_message_write(fn: Callable[[], Any]) -> Any:
    import send_ops
    send_ops.check_permit()
    try:
        return _proxy(fn)
    finally:
        try:
            relay_cache.invalidate("chat_pinned", _current_aid())
        except Exception:  # noqa: BLE001
            log.debug("chat_pinned invalidation skipped", exc_info=True)


def _platform_call(name: str, what: str) -> Callable[..., Any]:
    client = _get_client()
    side_effect_gate.raise_if_refused(side_effect_gate.refusal(client, name), what)
    return getattr(client, name)


# Static /users/list before the dynamic /users/{...}, else FastAPI matches 'list' as a username.
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
    aid = _current_aid()
    # Ids sorted in the key so [1,2,3] and [3,2,1] coalesce.
    key = ("list_users", aid, view, tuple(sorted(ids)))

    async def _fetch():
        resp = await asyncio.to_thread(_proxy, lambda: _get_client().list_users(ids, view=view))
        _timing_post_start()
        if isinstance(resp, list):
            resp = {}
        # Overlay inside the fetcher so coalesced waiters see the same stitched dict.
        try:
            await _sync_of_user_overlay(aid, resp)
        except Exception:
            log.exception("custom_nickname stitch failed for /users/list")
        return resp

    with _of_read_timing("users_list", aid):
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





class SendMessageBody(BaseModel):
    text: str = Field(..., max_length=MARKUP_MAX, description="Message body. Plain text or HTML. At most of_rich_text.MARKUP_MAX (422).")
    locked_text: bool = Field(False, description="Lock the text behind the PPV price.")
    price: float = Field(0, ge=0, description="PPV price; 0 = free message.")
    media_files: list[int | dict] = Field(default_factory=list, description="Vault media ids OR fresh-upload claim objects {processId,host,name,extra}")
    # Subset of media_files' numeric ids: a fresh claim has no id until OF resolves it.
    previews: list[int] = Field(default_factory=list, description="Subset of media_files (by vault id) sent unlocked when price > 0")
    is_forward: bool = False
    reply_to_message_id: int | None = Field(
        None,
        description="OF native quote-reply target id — receiver renders the quoted message above this one.",
    )
    # OF rejects ids not on the caller's tagged-friend list with 400.
    tagged_users: list[int] = Field(
        default_factory=list,
        description="OF user ids of creators to tag (sent as `userTags`).",
    )
    giphy_id: str | None = Field(
        None,
        description="Giphy GIF id (string). Sent as top-level `giphyId`; one per message.",
    )
    rf_guest: list[int] = Field(default_factory=list, description="Release-form guest ids (sent as `rfGuest`).")
    rf_partner: list[int] = Field(default_factory=list, description="Release-form link / document ids (sent as `rfPartner`).")


# Re-sale guard: charging twice for one file is a refund + chargeback, which kills OF accounts (8 paid messages re-charged $456 for owned content). Rules live in ownership.resale_verdict.
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


def _refuse_send(account_id: str, body: BaseModel) -> platforms.Platform:
    platform = platforms.for_account(account_id)
    if reason := side_effect_gate.send_refusal(platform, body.model_dump()):
        raise HTTPException(status_code=501, detail=reason)
    return platform


async def _reject_if_resale(account_id: str, fan_id: int, body: SendMessageBody) -> None:
    if body.price <= 0:
        return
    vault_ids = [m for m in body.media_files if isinstance(m, int) and m > 0]
    if not vault_ids:
        return
    try:
        verdict = await ownership.resale_verdict(
            account_id, fan_id, vault_ids, body.previews)
    except Exception:
        # A broken guard read must not take the chat offline: log, allow.
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
    started = _time_mod.monotonic()
    account_id = _resolve_account_id(request)
    _refuse_send(account_id, body)
    # Read BEFORE _proxy: its lambda has no request scope.
    from employees import resolve_outbound_employee_id
    employee_id = await resolve_outbound_employee_id(request, account_id)

    await _reject_if_resale(account_id, int(chat_id), body)

    before_send_at = read_flip.now_ms()

    def send():
        fields = dict(
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
            # A human composing has the tag picker, so their choice stands; media_cotag auto-tags the automated senders.
            auto_tag=False,
        )
        # Fansly shim, demo FakeOF and slop's offline client answer send_message only.
        if not isinstance(_proxy(_get_client), SendsMixin):
            return _proxy(lambda: _get_client().send_message(chat_id, **fields))
        prepared_chat_id, path, payload, retry_plan = _proxy(
            lambda: _get_client().prepare_message(chat_id, **fields))
        return _proxy(lambda: _get_client().post_message(prepared_chat_id, path, payload, retry_plan),
                      send=retry_plan is None, started=started)

    import send_ops
    anchor = send_ops.anchor(request)
    try:
        if anchor:
            platform = account_registry.get_platform(account_id)
            result, replay = await asyncio.to_thread(
                send_ops.dispatch, platform, account_id,
                send_ops.op_id(platform, account_id, "composer", str(chat_id), anchor),
                "composer", str(chat_id), send_ops.digest(body.model_dump()), send)
            if replay:
                return send_ops.manual_json(result, explicit_reconciliation=True)
        else:
            send_ops.check_permit()
            result = await asyncio.to_thread(send)
    except HTTPException as e:
        relay_hooks.fire_send_failed(account_id, int(chat_id), e)
        raise

    await _record_fan_send(account_id, int(chat_id), result,
                           employee_id=employee_id, price=body.price, before_send_at=before_send_at)
    return result


async def _record_fan_send(account_id: str, fan_id: int, result: Any, *,
                           employee_id: int | None, price: float, before_send_at: int) -> None:
    # A reply reads an unread chat: prior state peeked before the bust below, before an awaited write lets the WS echo drop it.
    read_flip.after_reply(account_id, fan_id, before_send_at)
    # Best-effort: the OF send already succeeded; never raise.
    try:
        from attribution import write_outbound_attribution
        from event_transcoder import _to_cents
        msg_id = result.get("id") if isinstance(result, dict) else None
        if msg_id:
            await write_outbound_attribution(
                account_id=account_id,
                fan_id=int(fan_id),
                message_id=int(msg_id),
                sent_by_employee_id=employee_id,
                body=str(result.get("text") or ""),
                price_cents=_to_cents(price),
                created_at=parse_iso(result.get("createdAt")) or datetime.utcnow(),
            )
    except Exception:
        log.exception("attribution write failed (chat_id=%s)", fan_id)

    # Busted before the announcement: a list read after `chat_responded` must be fresh; the WS echo of our send can lag or be missed.
    _bust_chat_list_and_badges(account_id, fan_id)
    await publish_chat_responded(account_id=account_id, fan_id=int(fan_id), employee_id=employee_id,
                                 message=result)

    try:
        from img_api import _pin_sent_media
        _pin_sent_media(account_id, result)
    except Exception:
        log.debug("pin sent media dispatch failed (chat_id=%s)", fan_id, exc_info=True)




@app.get("/api/of/v2/labels")
async def of_labels() -> dict[str, Any]:
    """Post labels (New post's ADD LABELS)."""
    aid = _current_aid()
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
    return await _notifications_read(_current_aid(), limit, offset, type, related_user, refresh)


async def _notifications_read(aid: str, limit: int, offset: int, type: str | None, related_user: int | None,
                              refresh: bool) -> Any:
    # `type or ""` collapses absent and empty to one entry, matching of_client.notifications.
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
    aid = _current_aid()
    coalesce_key = ("notifications_count", aid)
    async def _fetch():
        return await relay_coalesce.coalesce(coalesce_key, lambda: asyncio.to_thread(
            _proxy, lambda: _get_client().notifications_count(),
        ))
    return await relay_cache.get_or_fetch(
        "notifications_count", aid, (),
        ttl_seconds=30.0, fetcher=_fetch, bypass=refresh,
    )


@app.post("/api/of/v2/users/notifications/read")
async def of_notifications_mark_read():
    """Mark all of the Creator's OF notifications read, as OF web does when its All notifications tab opens
    (the bell's badge). Answers OF's body (`{counters: {all, <type>: n}}`, the `/count` shape); drops the cached
    count and feed, whose read flags it changed. A non-2xx from OF is `_proxy`'s 502 and drops nothing. Unpaced:
    a read flip reaches no fan (see `of_mark_chat_read`). Fansly: the shim's `/notifications/ack` (same answer)."""
    aid = _current_aid()

    def call():
        mark = getattr(_get_client(), "notifications_read", None)
        if mark is None:
            raise HTTPException(status_code=501, detail="mark notifications read: not on this platform")
        return mark()
    result = await asyncio.to_thread(_proxy, call)
    relay_cache.invalidate("notifications_count", aid)
    relay_cache.invalidate("notifications", aid)
    return result


_RAIL_PAGE_SIZE = 20
_RAIL_MONEY_TYPES = ("tip", "purchases")


@app.get("/api/of/v2/users/notifications/money")
async def of_notifications_money(
    types: str = Query(..., description="Comma-separated money types: 'purchases', 'tip'."),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
):
    """The Money rail's lists for one Creator in one call (app/lib/moneyLists.ts): `{type: body}` per asked type,
    each the exact body `GET /api/of/v2/users/notifications?type=<type>` answers, read through the same relay_cache
    entry and coalesce key (`_notifications_read`), so a list still cached costs OF nothing and nothing is read
    that was not asked. A type whose read failed is under `errors` as `{status, detail}` instead while another
    answered; every type failed → the first failure, as the per-type route would answer it."""
    asked = list(dict.fromkeys(t for t in types.split(",") if t))
    if not asked or any(t not in _RAIL_MONEY_TYPES for t in asked):
        raise HTTPException(status_code=422, detail=f"types: one or more of {', '.join(_RAIL_MONEY_TYPES)}")
    aid = _current_aid()
    got = await asyncio.gather(*(_notifications_read(aid, limit, offset, t, None, False) for t in asked),
                               return_exceptions=True)
    out: dict[str, Any] = {}
    errors: dict[str, Any] = {}
    for t, v in zip(asked, got):
        if isinstance(v, HTTPException):
            errors[t] = {"status": v.status_code, "detail": v.detail}
        elif isinstance(v, BaseException):
            raise v
        else:
            out[t] = v
    if not out:
        raise next(v for v in got if isinstance(v, HTTPException))
    if errors:
        out["errors"] = errors
    return out


def _warm_fetch(coalesce_key: tuple, aid: str, read: Callable[[OFClient], Any]):
    def run():
        with _priority_lane_background(aid):
            return _proxy(lambda: read(_load_client(aid)))

    async def _fetch():
        return await relay_coalesce.coalesce(coalesce_key, lambda: asyncio.to_thread(run))
    return _fetch


async def app_open_warm_reads(account_id: str) -> None:
    aid = str(account_id)
    import shared_refresher
    kept, asked = False, None
    with _background_reads(aid):
        async with _bg_admission():
            if shared_refresher.ENABLED:
                asked = shared_refresher.ask_time()
                kept = await _users_me_bypass(aid)
                await shared_refresher.window_read(aid)
            else:
                await accounts_admin_api.rewarm_roster_count(aid)
            for typ in _RAIL_MONEY_TYPES:
                extras = (_RAIL_PAGE_SIZE, 0, typ)
                await relay_cache.get_or_fetch(
                    "notifications", aid, extras, ttl_seconds=30.0,
                    fetcher=_warm_fetch(("notifications", aid) + extras, aid,
                                        lambda c, t=typ: c.notifications(limit=_RAIL_PAGE_SIZE, offset=0, type=t)))
            await relay_cache.get_or_fetch(
                "notifications_count", aid, (), ttl_seconds=30.0,
                fetcher=_warm_fetch(("notifications_count", aid), aid, lambda c: c.notifications_count()))
    if kept:
        shared_refresher.note_refresh(aid, asked)


async def _users_me_bypass(aid: str) -> bool:
    def read(c: OFClient) -> dict[str, Any]:
        me = c.me()
        account_page.prime(aid, me)
        return me
    me = await relay_cache.get_or_fetch("users_me", aid, ("users_me",), _ME_TTL_S,
                                        _warm_fetch(("users_me", aid), aid, read), bypass=True)
    return relay_cache.peek_fresh("users_me", aid, ("users_me",)) is me


async def shared_refresher_reads(account_id: str,
                                 window: Callable[[], Awaitable[Any]] | None = None) -> bool:
    aid = str(account_id)
    client = client_pool.peek(aid)
    try:
        with _background_reads(aid):
            async with _bg_admission():
                kept = await _users_me_bypass(aid)
                if kept and window is not None:
                    await window()
    except Exception as e:
        await flag_dead_session(aid, e, "shared_refresher", client)
        raise
    return kept


def app_open_warm_values(account_id: str) -> dict[str, Any]:
    aid = str(account_id)
    out: dict[str, Any] = {}
    roster = relay_cache.peek_fresh("roster_count", aid, ())
    if isinstance(roster, dict) and roster.get("as_of"):
        out["roster"] = {k: roster[k] for k in ("unread", "owe_reply", "as_of") if k in roster}
    count = relay_cache.peek_fresh("notifications_count", aid, ())
    if isinstance(count, dict) and isinstance(count.get("all"), int) and not isinstance(count.get("all"), bool):
        out["notif_count"] = count["all"]
    return out


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
    aid = _current_aid()
    side_effect_gate.refuse_if_platform_lacks(aid, "my_settings", "account settings")
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
    side_effect_gate.refuse_if_platform_lacks(_current_aid(), "subscribers_chart", "subscribers chart")
    return _proxy(lambda: _get_client().subscribers_chart(start=start, end=end, by=by))



@app.get("/api/of/v2/users/search")
def of_search_users(q: str = Query(..., min_length=1, max_length=100), limit: int = Query(10, ge=1, le=50),
                    offset: int = Query(0, ge=0)):
    """Search users by name/username (OF's own search box: `/users?query=&view=se`)."""
    return _proxy(lambda: _platform_call("search_users", "search users")(q, limit=limit, offset=offset))

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
    aid = _current_aid()
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



@app.get("/api/of/v2/posts")
def of_list_posts(limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0)):
    """My own posts."""
    return _proxy(lambda: _get_client().list_posts(limit=limit, offset=offset))


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



def _vault_picker_revalidate_s() -> float:
    try:
        return max(0.0, float(os.environ.get("VAULT_PICKER_REVALIDATE_S", "300")))
    except ValueError:
        return 300.0


def _listing_ids(payload: Any) -> list[Any] | None:
    rows = payload.get("list") if isinstance(payload, dict) else None
    return [m.get("id") if isinstance(m, dict) else m for m in rows] if isinstance(rows, list) else None


async def _vault_read(aid: str, key: str, *, refresh: bool, revalidate: bool,
                      fetch: Callable[[], Awaitable[Any]], first_page: bool = False) -> Any:

    async def _fetch_put(compare: Any) -> Any:
        t0 = datetime.utcnow()
        result = await fetch()
        if compare is not None and _listing_ids(compare) != _listing_ids(result):
            await vault_cache.drop_view_pages(aid, key, include_self=vault_cache._is_empty_listing(result))
        await vault_cache.put(aid, key, result, started_at=t0)
        return result

    if not refresh:
        cached = (await vault_cache.get(aid, key, max_age_s=_vault_picker_revalidate_s())
                  if revalidate else await vault_cache.get(aid, key))
        if cached is not None:
            return cached
        if revalidate:
            async def _revalidate() -> Any:
                old = await vault_cache.get(aid, key) if first_page else None
                return await _fetch_put(old)
            return await relay_coalesce.coalesce(("vault_revalidate", aid, key), _revalidate)
    return await _fetch_put(None)




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
    revalidate: Annotated[bool, Query(description="The picker's open: the cache only when younger than "
                                                  "VAULT_PICKER_REVALIDATE_S, else a fresh OF fetch")] = False,
):
    """My vault items. Filter by media kind via `type=`, order via `sort=`
    (asc/desc — OF honors both), full-text search via `query=`.

    Reads from the shared server-side cache (vault_response_cache) keyed
    on (account_id, query_key). All employees on the same OF account
    share the cache, so the second open is instant. Cache is invalidated
    on uploads/deletes and ages out by TTL for external edits.
    """
    aid = _current_aid()
    # Folder gate BEFORE vault_cache: a cached 'All' entry must never reach a restricted chatter. Soft deny (empty payload in OF's shape), never raise.
    allowed_folders = await _allowed_folder_ids_for_chatter(aid)
    if allowed_folders is not None and (
        list_id is None or list_id not in allowed_folders
    ):
        return {"list": [], "hasMore": False}
    # `query` is in the cache key so a search result is never served for another query.
    q_norm = (query or "").strip()
    key = vault_cache.vault_media_cache_key(type=type, list_id=list_id, offset=offset,
                                            limit=limit, sort=sort, field=field, q_norm=q_norm,
                                            before=before_publish_date)
    async def _fetch() -> Any:
        return await asyncio.to_thread(
            _proxy,
            lambda: _get_client().vault_media(
                limit=limit, offset=offset, type=type, list_id=list_id,
                sort=sort, field=field, query=q_norm or None,
                before_publish_date=before_publish_date,
            ),
        )

    return await _vault_read(aid, key, refresh=refresh, revalidate=revalidate, fetch=_fetch,
                             first_page=offset == 0)


@app.get("/api/of/v2/vault/media/{media_id}")
async def of_vault_media_by_id(media_id: int) -> dict[str, Any]:
    """One vault item by id — resolves a bare media id back to a media object
    (with `files.thumb` etc. for thumbnails). Powers the Brain panel's saved
    per-slot images (`time_images` stores only ids), which the paginated list
    can't surface unless the item happens to land on a loaded page.

    Folder-gated like the stills: a restricted chatter gets 404 for a media
    outside its folders or one the mirror has no row for
    (vault_ai_api.assert_media_visible), checked before the cache read. Cached
    server-side via vault_cache like the list route, so repeat loads are
    instant and shared.
    """
    aid = _current_aid()
    assert_account_owned(aid)
    await vault_ai_api.assert_media_visible(aid, media_id)
    key = f"media-by-id:{media_id}"
    cached = await vault_cache.get(aid, key)
    if cached is not None:
        return cached

    async def _fetch() -> dict[str, Any]:
        # The slot is INSIDE the coalescer: waiters on an in-flight fetch hold none.
        t0 = datetime.utcnow()
        async with admission.VAULT_MEDIA_READ:
            fetched = await asyncio.to_thread(
                _proxy, lambda: _get_client().vault_media_by_id(media_id),
            )
        await vault_cache.put(aid, key, fetched, started_at=t0)
        return fetched

    # Keyed on the account too: a bare media id would share a response across accounts.
    return await relay_coalesce.coalesce(
        ("vault_media_by_id", aid, media_id), _fetch,
    )



@app.get("/api/of/v2/lists")
def of_get_lists(limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0)):
    """My custom fan lists + built-in ones like 'fans', 'recent'."""
    return _proxy(lambda: _get_client().get_lists(limit=limit, offset=offset))

# Nothing else reaches OF: a decoded '7?x=' or '7/../8' would become another OF path.
ListId = Annotated[str, PathParam(pattern=r"^[A-Za-z0-9_-]+$")]


@app.get("/api/of/v2/lists/{list_id}")
def of_get_list(list_id: ListId):
    """List metadata. Built-in names like 'fans' work too."""
    return _proxy(lambda: _get_client().get_list(list_id))

@app.get("/api/of/v2/lists/{list_id}/users")
def of_list_users_in(list_id: ListId, limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0),
                     query: str | None = Query(None, max_length=100)):
    """Fans in a list; `query` is Collections' Search users (OF's own `query` param)."""
    return _proxy(lambda: _platform_call("list_users_in", "list members")(
        list_id, limit=limit, offset=offset, query=query or None))

@app.get("/api/of/v2/lists/{list_id}/posts")
def of_list_posts_in(list_id: ListId, limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0),
                     type: str | None = Query(None, pattern="^(photos|videos|audios|other|locked)$")):
    """A list's Posts tab (OF Manager > Collections): its users' posts; `type` is the tab's chip."""
    return _proxy(lambda: _get_client().list_posts_in(list_id, limit=limit, offset=offset, type=type))



@app.post("/admin/vault/cache/invalidate")
async def admin_vault_cache_invalidate() -> dict[str, Any]:
    """Drop every cached vault response for the current account. The picker's
    Refresh button calls this so both vault-media AND vault-lists go upstream
    on the next fetch (the `?refresh=1` flag only covers a single endpoint)."""
    aid = _current_aid()
    deleted = await vault_cache.invalidate(aid)
    return {"ok": True, "account_id": aid, "deleted": deleted}


@app.get("/api/of/v2/vault/lists")
async def of_vault_lists(view: str = Query("main"), limit: int = Query(10, ge=1, le=50),
                         offset: int = Query(0, ge=0),
                         query: str | None = Query(None, description="The folder search (wire param `query`)"),
                         refresh: bool = Query(False, description="Bypass the shared server cache"),
                         revalidate: Annotated[bool, Query(description="The picker's open: the cache only when "
                                                           "younger than VAULT_PICKER_REVALIDATE_S")] = False):
    """Vault folders. Note OF's required `view` param value is `main`.
    Cached server-side via vault_cache (same invalidation semantics as
    /api/of/v2/vault/media)."""
    aid = _current_aid()
    # Gate computed BEFORE the cache read: the cached payload is unfiltered and shared with other chatters.
    allowed_folders = await _allowed_folder_ids_for_chatter(aid)
    q_norm = (query or "").strip()
    key = vault_cache.vault_lists_cache_key(view=view, limit=limit, offset=offset, q_norm=q_norm)

    async def _fetch() -> Any:
        return await asyncio.to_thread(
            _proxy,
            lambda: _get_client().vault_lists(view=view, limit=limit, offset=offset,
                                              query=q_norm or None),
        )

    result = await _vault_read(aid, key, refresh=refresh, revalidate=revalidate, fetch=_fetch)
    if allowed_folders is not None and isinstance(result, dict):
        # Filter on read only, never written back: OF's `all` key counts folders the chatter may not see.
        return {
            "list": [f for f in (result.get("list") or [])
                     if isinstance(f, dict) and f.get("id") in allowed_folders],
            "hasMore": result.get("hasMore"),
        }
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

@app.get("/api/of/v2/users/links")
def of_users_links():
    """Things I Like's links: OF's GET /users/links (a list of {id, sort, url, title, description, image}:
    the link is `url`, measured live 2026-11-21). Creating one (PUT `{link}`) and deleting one is of_add_users_link /
    of_delete_users_link."""
    return _proxy(lambda: _get_client().users_links())

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
    def send():
        return _proxy(lambda: _get_client().publish_schedule(schedule_id))
    if not _CELLS:
        return send()
    import send_ops
    aid = _current_aid()
    name, sid = account_registry.get_platform(aid), str(schedule_id)
    result = send_ops.dispatch(name, aid, send_ops.op_id(name, aid, "publish_now", sid, sid), "publish_now", sid,
                               send_ops.digest({"schedule_id": sid}), send).result
    return send_ops.manual_json(result)

# OF's ledger lands hours late (measured 209/560/628 min after occurred_at), so a 60 s entry bought no freshness; fresh payments arrive via the WS / purchases feed.
_LEDGER_TTL_S = 900


@app.get("/api/of/v2/payouts/transactions")
@_account_ttl("payouts", _LEDGER_TTL_S)
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

# A day, or a day and time (both honoured by OF); never an ISO `T...Z`: the payouts ledger answers empty.
_STATS_DAY = r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?$"

@app.get("/api/of/v2/payouts/stats")
@_account_ttl("payouts", 60)
def of_earning_stats(
    by: str = Query("day", pattern="^(day|week|month)$"),
    startDate: str | None = Query(None, pattern=_STATS_DAY,
                                  description="Statements' Custom period: its first day (YYYY-MM-DD)"),
    endDate: str | None = Query(None, pattern=_STATS_DAY,
                                description="Statements' Custom period: its last day (YYYY-MM-DD)"),
):
    """Time-series earnings totals; a range as OF's own startDate/endDate, sent on as is (OF ignores start/end here,
    of_reads.earning_stats)."""
    return _proxy(lambda: _get_client().earning_stats(by=by, start_date=startDate, end_date=endDate))





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
    aid = _current_aid()
    key = ("get_user", aid, user_id_or_username)

    async def _fetch():
        resp = await asyncio.to_thread(
            _proxy, lambda: _get_client().get_user(user_id_or_username)
        )
        if not isinstance(resp, dict):
            return resp
        fid = resp.get("id")
        if isinstance(fid, int):
            try:
                await _sync_of_user_overlay(aid, {str(fid): resp})
            except Exception:
                log.exception("custom_nickname stitch failed for /users/{id}")
        return resp

    return await relay_coalesce.coalesce(key, _fetch)



@app.get("/api/of/v2/promotions")
def of_promotions():
    """My subscription promotions."""
    return _proxy(lambda: _get_client().promotions())



# 30 s: half the rail's staleTime; our own changes drop the entry (send, mark read/unread, delete, restrict, mute, inbound DM).
_GET_CHAT_TTL = 30.0


@app.get("/api/of/v2/chats/{chat_id}")
async def of_get_chat(chat_id: int):
    """Full chat detail. Richer than the per-item shape from /chats.
    Cached `_GET_CHAT_TTL` per (account, chat) and coalesced, like chat_folders."""
    aid = _current_aid()

    async def _fetch():
        return await relay_coalesce.coalesce(("get_chat", aid, chat_id), lambda: asyncio.to_thread(
            _proxy, lambda: _get_client().get_chat(chat_id),
        ))

    with _of_read_timing("chat", aid, chat_id):
        return await relay_cache.get_or_fetch(
            "get_chat", aid, (chat_id,), ttl_seconds=_GET_CHAT_TTL, fetcher=_fetch,
        )


def _bust_chat_detail(aid: str | None, chat_id: int | None = None) -> None:
    try:
        aid = aid or _current_aid()
        match = None if chat_id is None else (lambda ex, c=int(chat_id): ex == (c,))
        relay_cache.invalidate("get_chat", aid, match=match)
    except Exception:  # noqa: BLE001
        log.debug("get_chat invalidation skipped", exc_info=True)

def _bust_chat_list() -> None:
    try:
        relay_cache.invalidate("list_chats", _current_aid())
    except Exception:  # noqa: BLE001
        log.debug("list_chats invalidation skipped", exc_info=True)

@app.get("/api/of/v2/messages/queue")
def of_scheduled_messages(limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0)):
    """Messages scheduled for future delivery."""
    return _proxy(lambda: _platform_call("scheduled_messages", "scheduled messages")(limit=limit, offset=offset))

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
    async with _bg_admission():
        resp = await asyncio.to_thread(_proxy, lambda: _platform_call("engagement_messages", "mass message history")(
            "group", start_date=startDate, end_date=endDate, limit=limit, offset=offset, query=query,
        ))
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
    side_effect_gate.refuse_if_platform_lacks(aid, "mass_message_history", "mass message history")
    if await cache.is_stale(aid):
        try:
            end = datetime.utcnow()
            start = end - timedelta(days=days_back)
            fmt = "%Y-%m-%d %H:%M:%S"
            client = _load_client(aid)

            def _fetch():
                with _priority_lane(aid):
                    return client.mass_message_history(
                        start_date=start.strftime(fmt),
                        end_date=end.strftime(fmt),
                        limit=limit, offset=0,
                    )
            # Blocking OF round-trip off the event loop so a stale-cache refresh can't freeze vault-open / chat-click for everyone.
            resp = await asyncio.to_thread(_fetch)
            items = (resp.get("items") if isinstance(resp, dict) else None) or []
            await cache.upsert_many(aid, items)
        except Exception as e:
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
    side_effect_gate.refuse_if_platform_lacks(aid, "mass_message_history", "mass message history")
    end = datetime.utcnow()
    start = end - timedelta(days=days_back)
    fmt = "%Y-%m-%d %H:%M:%S"
    client = _load_client(aid)
    try:
        def _fetch():
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



class _TextBody(BaseModel):
    text: str = Field(..., min_length=1)

class _NameBody(BaseModel):
    name: str = Field(..., min_length=1)

class _ScheduleMessageBody(BaseModel):
    text: str
    scheduled_date: str = Field(..., description="ISO 8601, e.g. 2026-06-01T18:00:00+00:00")
    price: float = Field(0, ge=0)
    locked_text: bool = False
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
    media_files: list[int | dict] = Field(default_factory=list)
    price: float = Field(0, ge=0)
    previews: list[int] = Field(default_factory=list)
    posted_at: str | None = None
    save_for_later: bool = False
    expire_days: int | None = Field(None, ge=1)
    fund_raising_target: float | None = Field(None, gt=0)
    fund_raising_presets: list[float] = Field(default_factory=list)
    voting_type: int | None = Field(None, ge=1, le=2)
    voting_options: list[str] = Field(default_factory=list)
    voting_due: int | None = Field(None, ge=1)
    voting_correct_index: int | None = Field(None, ge=0)
    label_ids: list[int] = Field(default_factory=list)
    tagged_users: list[int] = Field(default_factory=list)
    giphy_id: str | None = Field(
        None,
        description="Giphy GIF id forwarded to OF as top-level `giphyId`.",
    )

class _EditPostBody(BaseModel):
    text: str | None = None
    price: float | None = None
    media_files: list[int | dict] | None = None



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
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed.get("withUserId") is not None:
                with_user_id = int(parsed["withUserId"])
    except Exception:
        with_user_id = None
    resp = await asyncio.to_thread(
        _proxy_message_write, lambda: _get_client().unsend_message(message_id, with_user_id=with_user_id))
    # Mirror OF's take-down onto our row, else the DB seed repaints it as an empty locked shell; best-effort, and only on `success: true` (a 2xx refusal leaves the row live).
    _bust_chat_detail(None, with_user_id)
    if not (isinstance(resp, dict) and resp.get("success") is True):
        log.warning("unsend not confirmed by OF message_id=%s: %r", message_id, resp)
        return resp
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
    return _proxy_message_write(lambda: _get_client().hide_message(message_id, body.withUserId))

@app.post("/api/of/v2/messages/{message_id}/bookmark")
def of_bookmark_message(message_id: int, body: _BookmarkBody | None = Body(None)):
    """Bookmark a chat message (OF web: POST /posts/{id}/bookmarks {chat_group_id})."""
    return _proxy_message_write(lambda: _get_client().bookmark_message(message_id, body.chat_group_id if body else None, True))

@app.delete("/api/of/v2/messages/{message_id}/bookmark")
def of_unbookmark_message(message_id: int, body: _BookmarkBody | None = Body(None)):
    return _proxy_message_write(lambda: _get_client().bookmark_message(message_id, body.chat_group_id if body else None, False))

@app.delete("/api/of/v2/chats/{chat_id}/messages/pin")
def of_unpin_all_messages(chat_id: int):
    """OF web's pinned page "Unpin all messages": DELETE /chats/{id}/messages/pin."""
    result = _proxy_message_write(lambda: _get_client().unpin_all_messages(chat_id))
    _bust_chat_list_cache()
    _bust_chat_detail(None, chat_id)
    return result

@app.post("/api/of/v2/messages/{message_id}/like")
def of_like_message(message_id: int):
    """Like a message you received (can't like your own)."""
    return _proxy_message_write(lambda: _get_client().like_message(message_id))

@app.delete("/api/of/v2/messages/{message_id}/like")
def of_unlike_message(message_id: int):
    return _proxy_message_write(lambda: _get_client().unlike_message(message_id))

@app.post("/api/of/v2/messages/{message_id}/pin/user/{user_id}")
def of_pin_message(message_id: int, user_id: int):
    """Pin a message inside a chat. Path mirrors OF's wire shape
    (`/messages/{msg}/pin/user/{chat_partner}`) — the shorter `/pin` form
    didn't reliably pin to the chat's visible pinned list."""
    side_effect_gate.refuse_if_platform_lacks(_current_aid(), "pin_message", "pin message")
    result = _proxy_message_write(lambda: _platform_call("pin_message", "pin message")(message_id, user_id))
    _bust_chat_detail(None, user_id)
    return result

@app.delete("/api/of/v2/messages/{message_id}/pin/user/{user_id}")
def of_unpin_message(message_id: int, user_id: int):
    side_effect_gate.refuse_if_platform_lacks(_current_aid(), "unpin_message", "unpin message")
    result = _proxy_message_write(lambda: _platform_call("unpin_message", "unpin message")(message_id, user_id))
    _bust_chat_detail(None, user_id)
    return result


def _bust_chat_list_and_badges(aid: str, chat_id: int | None = None) -> None:
    read_flip.bust_chat_list_and_badges(aid, chat_id)

def _read_not_landed(result: Any) -> HTTPException:
    reason = result.get("reason") if isinstance(result, dict) else None
    return HTTPException(status_code=502, detail={"upstream_status": reason or "partial", "upstream_body": result})


# Static path BEFORE dynamic /chats/{chat_id}/...: else chat_id='mark-as-read' 422s.
@app.post("/api/of/v2/chats/mark-as-read")
async def of_mark_all_chats_read():
    """Mark EVERY chat as read (bulk no-arg endpoint). The local unread clears only for what the platform took
    (read_flip.after_write); anything less answers 502 (`_read_not_landed`)."""
    aid = _current_aid()
    if await split_inbox.chatter_inbox_filter(aid) is not None:
        raise HTTPException(409, "Mark chats individually for a split inbox")
    result, at = await read_flip.write(aid, None, lambda: _proxy(lambda: _get_client().mark_all_chats_read()))
    if not await read_flip.after_write(aid, None, 0, result, at=at):
        raise _read_not_landed(result)
    return result

async def _paced_of_write(aid: str, call):
    from automation_executor import of_write_paced
    return await of_write_paced(aid, lambda: _proxy(call), send_purpose="not_fan_dm", operator=True)

@app.post("/api/of/v2/chats/{chat_id}/mark-as-read")
async def of_mark_chat_read(chat_id: int):
    """Mark chat as read (chat_id == fan id). Clears local unread_count once the
    platform took it (read_flip.after_write); a write it refused answers 502.

    Unpaced, bulk loops included: a read flip reaches no fan, and pacing it
    would reserve an 11 s write slot per chat ahead of the automations' fan
    sends."""
    aid = _current_aid()
    result, at = await read_flip.write(aid, chat_id, lambda: _proxy(lambda: _get_client().mark_chat_read(chat_id)))
    if not await read_flip.after_write(aid, chat_id, 0, result, at=at):
        raise _read_not_landed(result)
    # After after_write, so the backfill's scrape finds the local marker already zeroed.
    relay_hooks.fire_thread_click_read(aid, chat_id, at)
    return result

@app.delete("/api/of/v2/chats/{chat_id}/mark-as-read")
async def of_mark_chat_unread(chat_id: int):
    """Mark chat as unread (same path as mark-read but DELETE). The local
    unread flip follows the platform's write: none on a 501 (Fansly has no
    server-side unread) or an upstream error."""
    aid = _current_aid()
    result, at = await read_flip.write(
        aid, chat_id, lambda: _proxy(lambda: _platform_call("mark_chat_unread", "mark as unread")(chat_id)))
    if not await read_flip.after_write(aid, chat_id, 1, result, at=at):
        raise _read_not_landed(result)
    return result

@app.post("/api/of/v2/chats/{chat_id}/mute")
async def of_mute_chat(chat_id: int):
    """Mute notifications for a chat."""
    aid = _current_aid()
    r, _at = await read_flip.write(aid, chat_id, lambda: _proxy(lambda: _get_client().mute_chat(chat_id)))
    if read_flip.landed(r):
        relay_hooks.fire_mute(chat_id, True, account_id=aid)
    _bust_chat_detail(None, chat_id)
    _bust_chat_list()
    return r

@app.delete("/api/of/v2/chats/{chat_id}/mute")
async def of_unmute_chat(chat_id: int):
    aid = _current_aid()
    r, _at = await read_flip.write(aid, chat_id, lambda: _proxy(lambda: _get_client().unmute_chat(chat_id)))
    if read_flip.landed(r):
        relay_hooks.fire_mute(chat_id, False, account_id=aid)
    _bust_chat_detail(None, chat_id)
    _bust_chat_list()
    return r

@app.post("/api/of/v2/chats/{chat_id}/hide")
def of_hide_chat(chat_id: int):
    """Hide chat from inbox (chat still exists; fan can still message)."""
    r = _proxy(lambda: _get_client().hide_chat(chat_id))
    # Our relay caches the /chats feed 10 min: bust it or the hidden row lingers until the TTL.
    _bust_chat_list_cache()
    return r

@app.delete("/api/of/v2/chats/{chat_id}/hide")
def of_unhide_chat(chat_id: int):
    r = _proxy(lambda: _get_client().unhide_chat(chat_id))
    _bust_chat_list_cache()
    return r

@app.delete("/api/of/v2/chats/{chat_id}")
async def of_delete_chat(chat_id: int):
    """Clear a chat's messages (OF's chat-list row "x", DELETE /chats/{id}). Not
    reversible. Paced (`_paced_of_write`); one chat per call (OF web's bulk form
    joins ids with commas, but no live capture vouches for it). Busts the cached
    chat list and the roster badge so the row and its count go on the next read."""
    aid = _current_aid()
    side_effect_gate.refuse_if_platform_lacks(aid, "delete_chat", "delete chat")
    r = await _paced_of_write(aid, lambda: _get_client().delete_chat(chat_id))
    _bust_chat_list_and_badges(aid, chat_id)
    return r



# Durable opt-out of every automation: skip_list(reason='manual_restrict') in OUR DB, not an OF call; distinct from the auto 'muted_creator' skip.
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
    return _proxy(lambda: _platform_call("chat_media", "chat media")(
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
    return _proxy(lambda: _platform_call("chat_media", "chat media")(
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
    return _proxy(lambda: _platform_call("search_chat", "search chat")(chat_id, query, filter))

def _block_user(user_id: int):
    aid = _current_aid()
    if not side_effect_gate.is_live_check_name(platforms.for_account(aid), "block_user"):
        return _platform_call("block_user", "block user")(user_id)
    side_effect_gate.raise_if_refused(
        side_effect_gate.live_check(aid, "block_user", frozenset({str(user_id)})), "block user")
    return _get_client().block_user(user_id)


@app.post("/api/of/v2/users/{user_id}/block")
def of_block_user(user_id: int):
    """Block a user (hides chat + prevents future messages from them)."""
    return _proxy(lambda: _block_user(user_id))

@app.delete("/api/of/v2/users/{user_id}/block")
def of_unblock_user(user_id: int):
    return _proxy(lambda: _platform_call("unblock_user", "unblock user")(user_id))

def _publish_restrict_changed(aid: str, user_id: int, restricted: bool) -> None:
    try:
        import events  # noqa: PLC0415
        events.publish({"chat_restrict_changed": {"fan_id": events.js_safe_id(int(user_id)), "restricted": restricted},
                        "__account_id": str(aid)})
    except Exception:  # noqa: BLE001
        log.warning("chat_restrict_changed publish failed (account=%s fan=%s)", aid, user_id, exc_info=True)

def _restricted_row(row: dict, restricted: bool) -> dict:
    if restricted and row.get("canSendMessage") is not False:
        row = {**row, "canSendMessage": False, "canNotSendReason": "muted"}
    elif not restricted and row.get("canNotSendReason") == "muted":
        row = {**row, "canSendMessage": True, "canNotSendReason": None}
    wu = {k: v for k, v in (row.get("withUser") or {}).items() if k != "isRestricted"}
    return {**row, "withUser": {**wu, "isRestricted": True} if restricted else wu}


async def restrict_landed(aid: str, user_id: int, restricted: bool, *, visibility_changed: bool) -> None:
    import badge_reads

    def change(row: dict) -> dict:
        return _restricted_row(row, restricted)

    try:
        badge_reads.patch_restriction(aid, user_id, change)
        accounts_admin_api.patch_window(aid, {user_id: change})
        relay_cache.invalidate("roster_count", aid)
        relay_cache.invalidate("get_chat", aid, match=lambda ex: ex == (user_id,))
    except Exception:
        log.warning("restrict window patch failed (account=%s fan=%s)", aid, user_id, exc_info=True)
    await accounts_admin_api.restrict_refresh(aid)
    if visibility_changed:
        relay_cache.invalidate("list_chats", aid)
    _publish_restrict_changed(aid, user_id, restricted)


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
    side_effect_gate.refuse_if_platform_lacks(account_id, "restrict_user", "restrict user")
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
    await restrict_landed(account_id, user_id, True, visibility_changed=hidden)
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
    result = await asyncio.to_thread(_proxy, lambda: _platform_call("unrestrict_user", "unrestrict user")(user_id))
    await set_of_restricted_skip(account_id, user_id, False)
    unhidden = False
    if unhide:
        try:
            await asyncio.to_thread(_proxy, lambda: _get_client().unhide_chat(user_id))
            unhidden = True
        except Exception:
            log.warning("unrestrict unhide-chat failed (account=%s fan=%s)",
                        account_id, user_id, exc_info=True)
    await restrict_landed(account_id, user_id, False, visibility_changed=unhidden)
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



@app.get("/api/of/v2/messages/templates")
def of_message_templates(template: str | None = Query(None, description="filter, e.g. 'reply_on_subscribe'")):
    """Saved replies + welcome message. `template=reply_on_subscribe` filters to the welcome message."""
    side_effect_gate.refuse_if_platform_lacks(_current_aid(), "message_templates", "message templates")
    return _proxy(lambda: _get_client().message_templates(template=template))




# Declared BEFORE the generic /messages/templates/{id}: first match wins, else /reply_on_subscribe is read as a template id. OF web POSTs/DELETEs the slot URL directly.
class _ReplyOnSubscribeBody(BaseModel):
    enabled: bool


@app.patch("/api/of/v2/users/me/reply-on-subscribe")
def of_set_reply_on_subscribe(body: _ReplyOnSubscribeBody = Body(...)):
    """Toggle the master `replyOnSubscribe` flag on /users/me."""
    result = _proxy(lambda: _get_client().set_reply_on_subscribe(body.enabled))
    aid = _current_aid()
    relay_cache.invalidate("my_settings", aid)
    return result



class _BundleBody(BaseModel):
    # OF's dialog sends {discount, duration} and OF prices the bundle; legacy {months, price} stays.
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


class _PromoBody(BaseModel):
    # OF promos are a % discount off the sub (a free trial is 100), not an absolute price.
    discount: int = Field(..., ge=1, le=100)
    subscribe_counts: int = Field(..., ge=0)
    subscribe_days: int = Field(30, ge=0)
    message: str = Field("", max_length=500)
    type: str | list[str] = "all"
    finish_days: int | None = Field(None, ge=0, le=30)
    resolve_open: int | None = None

@app.post("/api/of/v2/promotions")
async def of_create_promo(body: _PromoBody = Body(...)):
    """Create a promo campaign, under the Creator's create reservation like every create
    (promotions_api.reserve_manual: 409 while another is open)."""
    side_effect_gate.raise_if_refused(promo_create_guard.promotion_type_refusal(_current_aid()), "promotions")
    if isinstance(body.type, list) and (not body.type or not set(body.type) <= {"all", "expired"}):
        raise HTTPException(status_code=422, detail='type: a list of "all" and/or "expired"')
    terms = {"discount": body.discount, "subscribe_counts": body.subscribe_counts,
             "subscribe_days": body.subscribe_days, "message": body.message, "type": body.type,
             "finish_days": body.finish_days}
    res = await _promo_reserve_manual(_current_aid(), "manual_raw", terms, body.resolve_open)
    sent = await promo_create_guard.send(res, {}, _get_client, terms, wrap=_proxy)
    if sent.outcome is None:
        raise HTTPException(409, {"reason": "create_in_flight", "message": _PROMO_IN_FLIGHT})
    if sent.error is not None:
        raise sent.error
    return sent.result

@app.post("/api/of/v2/promotions/{promo_id}/finish")
async def of_finish_promo(promo_id: int):
    """Stop promotion: OF's POST /promotions/{id}/finish (the campaign ends, the row stays).
    A Kept promo is unticked first, so Keep running never re-creates it."""
    await _untick_kept_promo(_current_aid(), promo_id)
    return await asyncio.to_thread(_proxy, lambda: _get_client().finish_promo(promo_id))

@app.delete("/api/of/v2/promotions/{promo_id}")
async def of_delete_promo(promo_id: int):
    await _untick_kept_promo(_current_aid(), promo_id)
    return await asyncio.to_thread(_proxy, lambda: _get_client().delete_promo(promo_id))


class _TrackingLinkBody(BaseModel):
    name: str
    code: int | None = None

_CAMPAIGN_SORT_FIELDS = {"created_date", "name", "subscribers_counts", "clicks_count", "shared"}


def _campaign_sort_check(field: str | None, sort: str | None) -> None:
    if (field or sort) and (field not in _CAMPAIGN_SORT_FIELDS or not sort):
        raise HTTPException(status_code=422, detail=f"field: one of {sorted(_CAMPAIGN_SORT_FIELDS)}, with sort asc|desc")

@app.get("/api/of/v2/campaigns")
def of_tracking_links(field: str | None = Query(None, description="OF's sort field (campaign-field)"),
                      sort: str | None = Query(None, pattern="^(asc|desc)$")):
    """Tracking link list with countSubscribers + countTransitions stats; `field` + `sort` is OF's own sort menu."""
    _campaign_sort_check(field, sort)
    if field:
        return _proxy(lambda: _get_client().tracking_links_sorted(field=field, sort=sort))
    return _proxy(lambda: _get_client().tracking_links())

@app.post("/api/of/v2/campaigns")
def of_create_tracking_link(body: _TrackingLinkBody = Body(...)):
    return _proxy(lambda: _get_client().create_tracking_link(
        name=body.name, code=body.code,
    ))

@app.get("/api/of/v2/campaigns/share-access")
def of_tracking_links_shared_with_me(field: str | None = Query(None, description="OF's sort field (campaign-field)"),
                                     sort: str | None = Query(None, pattern="^(asc|desc)$"),
                                     limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0)):
    """The "Shared with you" tab: other creators' tracking links shared with this model."""
    _campaign_sort_check(field, sort)
    return _proxy(lambda: _get_client().tracking_links_shared_with_me(limit=limit, offset=offset, field=field, sort=sort))

# ofm-not-yet writes are inert until OFM_NEW_WRITES_ENABLED: off, each answers 404 before any OF call.
_ofm_new_writes_on = runtime_switches.require_switch(OFM_NEW_WRITES, account=_current_aid)
_OFM_WRITES = [Depends(_ofm_new_writes_on)]


@app.get("/api/of/ofm-writes", dependencies=_OFM_WRITES)
def of_ofm_writes_probe():
    """The OF Manager's new-writes switch probe for the request's Creator (X-Account-Id): `{"on": true}`, or 404
    while OFM_NEW_WRITES_ENABLED is off for it."""
    return {"on": True}


class _ShareCampaignBody(BaseModel):
    campaignId: int = Field(..., ge=1)
    userId: int = Field(..., ge=1)

@app.post("/api/of/v2/campaigns/share-access", dependencies=_OFM_WRITES)
def of_share_campaign_stats(body: _ShareCampaignBody = Body(...)):
    """Share a tracking link's statistics with another creator."""
    return _proxy(lambda: _get_client().share_campaign_stats(campaign_id=body.campaignId, user_id=body.userId))

@app.delete("/api/of/v2/campaigns/share-access", dependencies=_OFM_WRITES)
def of_unshare_campaign_stats(body: _ShareCampaignBody = Body(...)):
    """Stop sharing a tracking link's statistics (the share's undo)."""
    return _proxy(lambda: _get_client().unshare_campaign_stats(campaign_id=body.campaignId, user_id=body.userId))

@app.delete("/api/of/v2/campaigns/{campaign_id}")
def of_delete_tracking_link(campaign_id: int):
    return _proxy(lambda: _get_client().delete_tracking_link(campaign_id))


class _TrialLinkBody(BaseModel):
    name: str = Field("", max_length=64)
    subscribe_days: int = Field(7, ge=1, le=365)
    subscribe_counts: int = Field(1, ge=0)
    expired_at: str | None = None
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


# Any other key is refused, so a crafted body can't reach the rest of the Creator's account.
_PROFILE_KEYS = frozenset({
    "name", "about", "location", "website", "wishlist",
    "subscribePrice",
    "recommenderReward", "sendAwardsTop1", "sendAwardsTop5",
    "isVisibleOnline", "isOldLoginRedirect", "commentsOnlyForPayers", "creatorsCommentsOnlyForFriends",
    "notifyOnAllMentions", "muteTagsInChats", "muteTagsInPosts", "muteTagsInStories",
    "canAcceptMessageOnlyFromFriends",
    "avatar", "header",
})
# New keys: refused while OFM_NEW_WRITES_ENABLED is off.
_PROFILE_NEW_KEYS = frozenset({"canAcceptMessageOnlyFromFriends", "avatar", "header"})
_PROFILE_IMAGE_ITEM_KEYS = frozenset({"processId", "host", "name", "extra", "thumbId"})


def _check_profile_images(body: dict) -> None:
    for key in ("avatar", "header"):
        if key not in body or body[key] == "":
            continue
        v = body[key]
        if not (isinstance(v, dict) and v.get("processId") and set(v) <= _PROFILE_IMAGE_ITEM_KEYS):
            raise HTTPException(status_code=422, detail=f"{key}: an uploaded image or \"\"")


_SECURITY_PATCH_KEYS = frozenset({
    "isSuggestionsOptOut", "phoneOtp", "isPrivate", "showPostsTips", "showFriendsToSubscribers",
    "showSubscribesOffers", "showSubscribersCount", "isWantComments", "isAutoFollowBack",
    "unfollowAutoFollowBack", "coStreamingRequestFrom", "showMediaCount", "isDrmEnabled",
    "requireFaceIdForPayoutUpdate",
})
_SECURITY_NEW_KEYS = frozenset({"isPrivate"})
_WATERMARK_KEYS = frozenset({"hasWatermarkPhoto", "hasWatermarkVideo", "watermarkText", "watermarkPosition"})


def _allowed_body(body: dict, allowed: frozenset[str]) -> dict:
    if not body:
        raise HTTPException(status_code=422, detail="empty body")
    if extra := sorted(set(body) - allowed):
        raise HTTPException(status_code=422, detail=f"keys not allowed: {', '.join(extra)}")
    return body


def _new_writes_for(body: dict, new_keys: frozenset[str], ask: bool = False) -> bool:
    return (ask or not new_keys.isdisjoint(body)) and runtime_switches.on_for(OFM_NEW_WRITES, _current_aid)


@app.patch("/api/of/v2/users/me")
def of_update_profile(body: dict = Body(...)):
    """PATCH /users/me — profile fields and the settings toggles OF saves here:
    only the `_PROFILE_KEYS` the mirror sends (422 on any other). While OFM_NEW_WRITES_ENABLED is off for the
    request's Creator the `_PROFILE_NEW_KEYS` are refused too (422) and `about` goes as typed, as on main."""
    formatted = isinstance(body.get("about"), str) and is_of_html(body["about"])
    new_writes = _new_writes_for(body, _PROFILE_NEW_KEYS, ask=formatted)
    body = _allowed_body(body, _PROFILE_KEYS if new_writes else _PROFILE_KEYS - _PROFILE_NEW_KEYS)
    _check_profile_images(body)
    if new_writes and formatted:
        body = {**body, "about": sanitize_of_html(body["about"])}
    result = _proxy(lambda: _get_client().update_profile(**body))
    aid = _current_aid()
    relay_cache.invalidate("my_settings", aid)
    account_page.invalidate(aid)
    return result


class _StorySettingsBody(BaseModel):
    allowReplyFrom: str = Field(..., pattern="^(subscribers|nobody)$")

def _settings_write(call: Callable[[], Any]) -> Any:
    result = _proxy(call)
    relay_cache.invalidate("my_settings", _current_aid())
    return result

@app.patch("/api/of/v2/users/me/settings/security")
def of_patch_security_settings(body: dict = Body(...)):
    """One security-section toggle, `{key: value}`, as OF's settings pages send it (`_SECURITY_PATCH_KEYS`)."""
    allowed = (_SECURITY_PATCH_KEYS if _new_writes_for(body, _SECURITY_NEW_KEYS)
               else _SECURITY_PATCH_KEYS - _SECURITY_NEW_KEYS)
    body = _allowed_body(body, allowed)
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

@app.delete("/api/of/v2/sessions", dependencies=_OFM_WRITES)
def of_close_all_sessions():
    """Login sessions' Close all sessions: OF's DELETE /sessions, no body (`account-lockout`). The client's
    `_denied` backstop still refuses it (403 refused_by_relay, nothing sent) until the owner's go (ticket 81)."""
    return _settings_write(lambda: _get_client().close_all_sessions())

# Each block-list route sends only its own control's keys, allowlisted and type-checked, to OF's shared security PUT.
def _list_body(body: dict, kinds: dict[str, type]) -> dict:
    body = _allowed_body(body, frozenset(kinds))
    for key, kind in kinds.items():
        value = body.get(key)
        if not isinstance(value, list) or any(type(x) is not kind for x in value):
            raise HTTPException(status_code=422, detail=f"{key}: a list of {kind.__name__}")
    return body

@app.get("/api/of/v2/countries")
def of_countries():
    """Block by country's picker: OF's country list (`?all=1`), `[{code, name, ...}]`."""
    return _proxy(lambda: _get_client().countries())

@app.put("/api/of/v2/users/me/settings/security/blocked-countries", dependencies=_OFM_WRITES)
def of_block_countries(body: dict = Body(...)):
    """Block by country's Save: `{blockedCountries: [code], blockedStates: [id]}` (`account-lockout`)."""
    body = _list_body(body, {"blockedCountries": str, "blockedStates": int})
    return _settings_write(lambda: _get_client().put_security_settings(body))

@app.put("/api/of/v2/users/me/settings/security/blocked-ips", dependencies=_OFM_WRITES)
def of_block_ips(body: dict = Body(...)):
    """Block by IP's Save: `{blockedIps: [ip]}`, `[]` to clear (`account-lockout`)."""
    body = _list_body(body, {"blockedIps": str})
    return _settings_write(lambda: _get_client().put_security_settings(body))

def _is_http_link(v: str) -> bool:
    return re.fullmatch(r"https?://[^\s/]+\.[^\s]+", v) is not None


_SOCIAL_BUTTON_KEYS = frozenset({"socialMedia", "label", "link", "username"})

@app.put("/api/of/v2/users/social/buttons", dependencies=_OFM_WRITES)
def of_add_social_button(body: dict = Body(...)):
    """OF's PUT /users/social/buttons `{socialMedia, label, link, username}` (OF answers the whole list): only those
    keys, each a string, `socialMedia` and `label` non-blank, and exactly one of `link` (an http(s) URL: a link
    provider's) or `username` (a username provider's; OF's form sends the other "", 67786.js) (422 otherwise). Which
    providers OF takes is OF's to say (its 400 "SocialMedia contains invalid value")."""
    body = _allowed_body(body, _SOCIAL_BUTTON_KEYS)
    if not all(isinstance(v, str) for v in body.values()):
        raise HTTPException(status_code=422, detail="every value is a string")
    link, username = str(body.get("link") or ""), str(body.get("username") or "").strip()
    link_ok = _is_http_link(link)
    if (not str(body.get("label") or "").strip() or not str(body.get("socialMedia") or "").strip()
            or bool(link) == bool(username) or (link and not link_ok)):
        raise HTTPException(status_code=422, detail="socialMedia, label and either an http(s) link or a username are required")
    return _settings_write(lambda: _get_client().add_social_button(body))

@app.delete("/api/of/v2/users/social/buttons/{button_id}", dependencies=_OFM_WRITES)
def of_delete_social_button(button_id: int):
    """One social media button's remove: OF's DELETE /users/social/buttons/{id}, no body."""
    return _settings_write(lambda: _get_client().delete_social_button(button_id))

_USERS_LINK_KEYS = frozenset({"link"})

@app.put("/api/of/v2/users/links", dependencies=_OFM_WRITES)
def of_add_users_link(body: dict = Body(...)):
    """OF's PUT /users/links `{link}` (OF answers the whole list): only that key, an http(s) URL string (422 otherwise).
    OF's own form takes only Amazon/Goodreads/IMDB/YouTube/OFTV links; that check is the Mirror's (inferred hosts)."""
    body = _allowed_body(body, _USERS_LINK_KEYS)
    if not isinstance(body.get("link"), str) or not _is_http_link(body["link"]):
        raise HTTPException(status_code=422, detail="an http(s) link is required")
    return _settings_write(lambda: _get_client().add_users_link(body))

@app.delete("/api/of/v2/users/links/{link_id}", dependencies=_OFM_WRITES)
def of_delete_users_link(link_id: int):
    """One Things I Like link's delete: OF's DELETE /users/links/{id}, no body."""
    return _settings_write(lambda: _get_client().delete_users_link(link_id))

@app.delete("/api/of/v2/streams/obs/key", dependencies=_OFM_WRITES)
def of_reset_stream_key(server: Literal["obs_agora", "mux_direct"] = Query(..., alias="type"), body: dict | None = Body(None)):
    """Settings > Streaming's Reset stream key: OF's DELETE /streams/obs/key?type=<shown OBS server>, no body
    (`account-lockout`; any body key 422s, as does a type other than OF's two). Drops the cached settings, whose
    re-read carries the new key (never drawn: the page shows the mask)."""
    if body:
        raise HTTPException(status_code=422, detail="no body allowed")
    return _settings_write(lambda: _get_client().reset_stream_key(server))

@app.post("/api/of/v2/streams/users/{username}/block", dependencies=_OFM_WRITES)
def of_block_stream_viewer(username: str = PathParam(..., pattern=r"^[A-Za-z0-9._-]{1,24}$"), body: dict | None = Body(None)):
    """Settings > Streaming > Blocked users' Block a username: OF's POST /streams/users/{username}/block, no body
    (`block-fan`; any body key 422s). ASSUMPTION: OF usernames are 1–24 of [A-Za-z0-9._-] (the form's maxlength 24)."""
    if body:
        raise HTTPException(status_code=422, detail="no body allowed")
    return _proxy(lambda: _get_client().block_stream_viewer(username))

@app.delete("/api/of/v2/streams/users/{user_id}/block", dependencies=_OFM_WRITES)
def of_unblock_stream_viewer(user_id: int):
    """A Blocked users row's remove: OF's DELETE /streams/users/{user_id}/block (the row's id; `block-fan`)."""
    return _proxy(lambda: _get_client().unblock_stream_viewer(user_id))

import of_stats_api  # noqa: E402
app.include_router(of_stats_api.router)



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
    platform = _refuse_send(account_id, body)
    if platforms.Lack.SERVER_SCHEDULE in platform.lacks:
        # Delegated to check_sendable, never re-implemented: hand copies drifted and re-opened the hole where a send fails silently at fire time.
        try:
            platform.backend.check_sendable(media_files=body.media_files, price=body.price,
                                            previews=body.previews)
        except platform.backend.APIError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return await _enqueue_scheduled(request, account_id, body, fan_id=chat_id,
                                        run_at_iso=body.scheduled_date, giphy_id=None)
    def send():
        return _proxy(lambda: _get_client().schedule_message(
            chat_id, text=body.text, scheduled_date=body.scheduled_date,
            price=body.price, locked_text=body.locked_text, media_files=body.media_files,
            previews=body.previews,
            tagged_users=body.tagged_users,
            auto_tag=False,
        ))
    import send_ops
    if anchor := send_ops.anchor(request):
        name = account_registry.get_platform(account_id)
        outcome = await asyncio.to_thread(
            send_ops.dispatch, name, account_id,
            send_ops.op_id(name, account_id, "native_schedule", str(chat_id), anchor),
            "native_schedule", str(chat_id), send_ops.digest(body.model_dump()), send)
        return send_ops.manual_json(outcome.result)
    send_ops.check_permit()
    return await asyncio.to_thread(send)



def _run_at_naive_utc(iso: str) -> datetime:
    from datetime import timezone
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"invalid run_at: {iso!r}")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


async def _enqueue_scheduled(request: Request, account_id: str,
                             body: "_ScheduleMessageBody | _ScheduledSendBody", *,
                             fan_id: int, run_at_iso: str, giphy_id: str | None) -> dict[str, Any]:
    from employees import resolve_outbound_employee_id
    from automation_executor import enqueue_job
    from send_ops import anchor

    employee_id = await resolve_outbound_employee_id(request, account_id)
    run_at = _run_at_naive_utc(run_at_iso)
    payload = {
        "fan_id": fan_id,
        "text": body.text,
        "price": body.price,
        "locked_text": body.locked_text,
        "media_files": body.media_files,
        "previews": body.previews,
        "tagged_users": body.tagged_users,
        "giphy_id": giphy_id,
        "sent_by_employee_id": employee_id,
        # Typed stamp: a HUMAN scheduled this; the at-fire audience recheck bypasses manual sends.
        "send_purpose": "manual",
    }
    job_id = await enqueue_job(
        account_id, "scheduled_send",
        payload=payload, run_at=run_at, created_by_employee_id=employee_id, op_anchor=anchor(request),
    )
    return {"job_id": job_id, "fan_id": js_safe_id(fan_id), "run_at": run_at.isoformat() + "Z"}


@app.post("/api/of/v2/scheduled-sends")
async def create_scheduled_send(request: Request, body: _ScheduledSendBody = Body(...)):
    """Enqueue a near-term deferred 1:1 send. Resolves the scheduling chatter's
    employee id so the eventual bubble is attributed to them, then inserts a
    `scheduled_jobs` row the executor will fire at `run_at`."""
    account_id = _resolve_account_id(request)
    # Fail here while the chatter still sees the composer: the shim refuses PPV price and media at FIRE time, into a retry loop nobody sees.
    p = _refuse_send(account_id, body)
    if platforms.Lack.NEAR_SCHEDULE_MEDIA in p.lacks and (body.media_files or body.price > 0):
        raise HTTPException(
            status_code=400,
            detail=f"{p.label} scheduled sends support text and GIFs for now — "
                   f"PPV price and media attachments aren't wired on the {p.label} "
                   "path yet.",
        )
    return await _enqueue_scheduled(request, account_id, body, fan_id=body.fan_id,
                                    run_at_iso=body.run_at, giphy_id=body.giphy_id)


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
            "fan_id": js_safe_id(row_fan),
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
            events.on_commit(s, "scheduled_send_changed", account_id=account_id, job_id=job_id)
    cancelled = bool(res.rowcount)
    if not cancelled:
        return {"cancelled": False, "reason": "not_pending"}
    return {"cancelled": True, "job_id": job_id}


import mass_queue_api  # noqa: E402
app.include_router(mass_queue_api.router)


async def _refuse_paid_post_on_paid_page(request: Request, price: float | int | None) -> None:
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


@app.post("/api/of/v2/lists")
def of_create_list(body: _NameBody = Body(...)):
    out = _proxy(lambda: _get_client().create_list(body.name))
    _invalidate_chat_folders()
    return out


# list_id is `str` so built-in lists ('fans', 'recent', 'bookmarks') work beside numeric ids.
@app.patch("/api/of/v2/lists/{list_id}")
def of_rename_list(list_id: ListId, body: _NameBody = Body(...)):
    """Rename a list. OF uses PATCH (not PUT) — verified live."""
    out = _proxy(lambda: _platform_call("rename_list", "rename list")(list_id, body.name))
    _invalidate_chat_folders()
    return out

def _delete_list(list_id: ListId):
    aid = _current_aid()
    side_effect_gate.raise_if_refused(side_effect_gate.delete_list_ungranted(aid, list_id), "delete list")
    client = _get_client()
    page = platforms.for_account(aid).list_page
    try:
        why = side_effect_gate.delete_list_refusal(
            aid, list_id, client, lambda: of_paging.list_audience(client, list_id, list_page=page))
    except of_paging.ListGone:
        why = "platform_lacks:delete_list"
    side_effect_gate.raise_if_refused(why, "delete list")
    return client.delete_list(list_id)


@app.delete("/api/of/v2/lists/{list_id}")
def of_delete_list(list_id: ListId):
    out = _proxy(lambda: _delete_list(list_id))
    _invalidate_chat_folders()
    return out

@app.post("/api/of/v2/lists/{list_id}/users/{user_id}")
def of_add_user_to_list(list_id: ListId, user_id: int):
    out = _proxy(lambda: _get_client().add_user_to_list(list_id, user_id))
    _invalidate_chat_folders()
    return out

@app.delete("/api/of/v2/lists/{list_id}/users/{user_id}")
def of_remove_user_from_list(list_id: ListId, user_id: int):
    out = _proxy(lambda: _get_client().remove_user_from_list(list_id, user_id))
    _invalidate_chat_folders()
    return out

@app.post("/api/of/v2/lists/users")
def of_add_users_to_lists(body: dict[str, list[int]] = Body(...)):
    """Bulk add: `{"<listId>": [userId, ...]}`, passed to OF's POST /lists/users as is."""
    if not body or not all(body.values()):
        raise HTTPException(status_code=422, detail="each list needs at least one user id")
    out = _proxy(lambda: _get_client().add_users_to_lists(body))
    _invalidate_chat_folders()
    return out

@app.delete("/api/of/v2/lists/{list_id}/users")
def of_clear_list(list_id: ListId):
    """OF's "Clear list": every user leaves the list (the list stays)."""
    out = _proxy(lambda: _get_client().clear_list(list_id))
    _invalidate_chat_folders()
    return out


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



class _NoteBody(BaseModel):
    note: str

class _CustomNameBody(BaseModel):
    name: str = Field(..., description="Custom display name; empty string clears it")

class _SubscriptionPatchBody(BaseModel):
    notice: str | None = None
    displayName: str | None = None

def _bust_chat_list_cache() -> None:
    try:
        aid = _current_aid()
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
        if v != 0 and (v < 5 or v % 5):
            raise ValueError("discount must be 0 or 5..60 in steps of 5")
        return v

@app.put("/api/of/v2/subscriptions/{user_id}/discount")
def of_set_subscription_discount(user_id: int, body: _DiscountBody = Body(...)):
    """OF web's "Give user a discount": PUT /subscriptions/{id}/discount {discount, period}."""
    result = _proxy(lambda: _platform_call("set_subscription_discount", "subscription discount")(
        user_id, body.discount, body.period))
    _bust_chat_list_cache()
    return result

@app.put("/api/of/v2/subscriptions/{user_id}")
def of_update_subscription(user_id: int, body: _SubscriptionPatchBody = Body(...)):
    """Generic update: set notice and/or displayName together in one call."""
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    result = _proxy(lambda: _get_client().update_subscription(user_id, **payload))
    _bust_chat_list_cache()
    return result


from fastapi import UploadFile, File, Form


def _upload_basename(raw: str | None) -> str:
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
    import tempfile, shutil
    # Named after the upload: both clients use path.name (S3 key, convert claim, Fansly fileName); a bare temp file landed in the vault as tmpXXXX.
    def _upload():
        tmp_dir = tempfile.mkdtemp(prefix="of-upload-")
        try:
            tmp_path = os.path.join(tmp_dir, _upload_basename(file.filename))
            with open(tmp_path, "wb") as tmp:
                shutil.copyfileobj(file.file, tmp)
            return _proxy(lambda: _get_client().upload_media(
                tmp_path,
                content_type=file.content_type,
            ))
        finally:
            # In the worker, so a cancelled request can't unlink the spool under a running upload.
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # Off the loop: blocking curl for seconds stalled every other request and caused 'database is locked'. to_thread copies the contextvars `_proxy` and `_get_client` read.
    result = await asyncio.to_thread(_upload)
    try:
        aid = _current_aid()
        await vault_cache.invalidate(aid)
    except Exception as e:  # noqa: BLE001 — cache invalidation must never block the upload response
        log.warning("vault_cache: invalidate-on-upload failed: %s", e)
    return result


# Only JPEG, PNG, GIF or WebP up to one 5 MiB upload part (a single PUT); anything else is refused before any OF request.
from starlette.datastructures import UploadFile as StarletteUploadFile  # noqa: E402  (request.form()'s parts)

PROFILE_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})
PROFILE_IMAGE_MAX = 5 * 1024 * 1024


@app.post("/api/of/v2/users/me/profile-image", dependencies=_OFM_WRITES)
async def of_upload_profile_image(request: Request):
    """POST /api/of/v2/users/me/profile-image — upload a cover (`kind` header) or avatar image; answers the upload item."""
    import tempfile, shutil
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > PROFILE_IMAGE_MAX + 64 * 1024:
        raise HTTPException(status_code=413, detail="image over 5 MB")
    form = await request.form()
    if extra := sorted(set(form.keys()) - {"file", "kind"}):
        raise HTTPException(status_code=422, detail=f"keys not allowed: {', '.join(extra)}")
    file, kind = form.get("file"), form.get("kind")
    if kind not in ("avatar", "header"):
        raise HTTPException(status_code=422, detail="kind: avatar or header")
    if not isinstance(file, StarletteUploadFile):
        raise HTTPException(status_code=422, detail="file: missing")
    if (file.content_type or "").lower() not in PROFILE_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="only JPEG, PNG, GIF or WebP images")
    if file.size is None or file.size > PROFILE_IMAGE_MAX:
        raise HTTPException(status_code=413, detail="image over 5 MB")

    def _upload():
        tmp_dir = tempfile.mkdtemp(prefix="of-profile-image-")
        try:
            tmp_path = os.path.join(tmp_dir, _upload_basename(file.filename))
            with open(tmp_path, "wb") as tmp:
                shutil.copyfileobj(file.file, tmp)
            return _proxy(lambda: _get_client().upload_media(
                tmp_path, content_type=file.content_type, check_dedupe=False, thumb_size=kind))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    result = await asyncio.to_thread(_upload)
    if not isinstance(result, dict) or not result.get("ready"):
        note = result.get("note") if isinstance(result, dict) else None
        raise HTTPException(status_code=502, detail=f"upload failed: {note or 'no upload item'}")
    items = result.get("send_with")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise HTTPException(status_code=502, detail="upload failed: no upload item")
    return items[0]


import vault_import_api  # noqa: E402
_http_hooks.add(vault_import_api._cap_vault_batch_body)
app.include_router(vault_import_api.router)



# /stories doesn't accept a vault media id: bytes are re-uploaded through the convert pipeline.
class _CreateStoryBody(BaseModel):
    media_url: str | None = Field(
        None, description="Image URL to download + repost (vault files.full.url / any CDN url)")
    media_files: list | None = Field(
        None, description="Already-prepared mediaFiles (send_with from POST /upload)")
    watermark_text: str | None = None
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
        side_effect_gate.refuse_if_platform_lacks(_current_aid(), "create_story", "create story")
        return _proxy(lambda: _get_client().create_story(
            body.media_files,
            caption=body.caption, mention=body.mention, question=body.question,
        ))
    if not body.media_url:
        raise HTTPException(400, "provide media_url or media_files")
    side_effect_gate.refuse_if_platform_lacks(_current_aid(), "post_story_from_url", "create story")
    return _proxy(lambda: _get_client().post_story_from_url(
        body.media_url, watermark_text=body.watermark_text,
        caption=body.caption, mention=body.mention, question=body.question,
    ))

@app.post("/api/of/v2/stories/upload")
async def of_create_story_upload(file: UploadFile = File(...)):
    """Publish a directly-uploaded file as a story. Multipart field: `file`."""
    import tempfile, shutil
    side_effect_gate.refuse_if_platform_lacks(_current_aid(), "post_story", "create story")
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


import accounts_admin_api  # noqa: E402
import proxies_admin_api  # noqa: E402
from accounts_admin_api import _ROSTER_SCAN_MAX  # noqa: E402  # list_chats' page-0 window = the badge's
app.include_router(accounts_admin_api.router)
app.include_router(proxies_admin_api.router)
import screens_api  # noqa: E402  # /admin/screens/*: one call per screen (dashboard, inbox)
app.include_router(screens_api.router)
import chat_screen_api  # noqa: E402  # /admin/screens/chat: a thread open's local reads in one call
app.include_router(chat_screen_api.router)



_CHAT_HISTORY = "/api/of/v2/chats/0/messages"


async def _chats_readable(accounts: frozenset[str] | None) -> frozenset[str] | None:
    import permissions
    pages = permissions.route_pages(_CHAT_HISTORY, "GET")
    if not pages:
        log.warning("chats_readable_unmapped route=%s", _CHAT_HISTORY)
        return frozenset()
    if (await permissions.route_refusal(pages, "GET", _CHAT_HISTORY, [None]))[0] is None:
        return None
    return frozenset([a for a in sorted(accounts or ())
                      if (await permissions.route_refusal(pages, "GET", _CHAT_HISTORY, [a]))[0] is None])


@app.get("/events", include_in_schema=False)
async def sse_events(
    request: Request, scope: str = Query("all"),
    last_event_id: str | None = Query(None), lease: str | None = Query(None),
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

    `?lease=1`: the app renews its own View lease; an unmarked browser stream is a tab loaded
    before that and leases the session's Creators while open (view_lease "Legacy tabs").
    """
    granted_at = _sse_ring_seq()
    claims = None
    if _CELLS:
        claims = getattr(request.state, "oi_actor", None)
        if stale := actor_token.stream_refusal(claims):
            return stale
    accounts = _require_actor_account_ids()
    if scope.startswith("model:") and accounts is not None and scope[len("model:"):] not in accounts:
        raise HTTPException(status_code=403, detail="not your account")
    user = _get_request_user()
    chatter = _get_request_chatter() if user is None else None
    agencies = (frozenset({user.id, owner_audience(user.id), sessions_audience("user", user.id)})
                if user is not None
                else chatter.owner_user_ids | {sessions_audience("chatter", chatter.id)}
                if chatter is not None else frozenset())
    readable = await _chats_readable(accounts) if chatter is not None else None
    if chatter is not None:
        await split_inbox.warm(accounts or ())
    body = sse_stream(request, scope, accounts=accounts, agencies=agencies,
                      last_event_id=request.headers.get("last-event-id") or last_event_id,
                      tab=is_app_tab(lease, request.headers.get("referer")), readable=readable,
                      granted_at=granted_at, chatter=chatter.id if chatter is not None else None,
                      expires_at=claims.exp if claims is not None else None)
    import view_lease
    legacy = view_lease.legacy_stream_ids(lease, request.headers.get("referer"), accounts,
                                          account_registry.is_watcher)
    if legacy:
        log.info("view_lease_legacy_stream creators=%d", len(legacy))
    return StreamingResponse(
        view_lease.legacy_held(body, legacy) if legacy else body,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
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
        "pumps": pumps,
        "pumps_running": sum(1 for p in pumps.values() if p["running"]),
        "supervisor_running": (_supervisor_task is not None and not _supervisor_task.done()),
        "sse": _sse_stats(),
    }


import saved_replies_api  # noqa: E402
import vault_sends_api  # noqa: E402
app.include_router(saved_replies_api.router)
app.include_router(vault_sends_api.router)


import tx_ingest_admin_api  # noqa: E402
app.include_router(tx_ingest_admin_api.router)



@app.get("/", include_in_schema=False)
def root():
    return {"service": "openinflowwww-relay", "ok": True}
