"""service/proxies_admin_api.py — server.py's proxy registry admin block,
moved wholesale.

  GET    /admin/proxies                     proxies + the assign-to picker
  POST   /admin/proxies                     add / edit one
  POST   /admin/proxies/bulk                paste many, one per line
  DELETE /admin/proxies/{label}             delete one no Creator uses
  POST   /admin/proxies/assign              bind to an account (or session file)
  POST   /admin/proxy-pool/assign           put an account on an Inflowwww proxy
  POST   /admin/proxy-pool/unbind           take it off
  POST   /admin/proxies/{label}/unbind      drop one account from a proxy
  POST   /admin/proxies/{label}/test        probe one

`_invalidate_client`, `_kick_db_sync` and `_get_request_user` are relay_host's
call-time forwards, never `from server import`, so a test's
`server._invalidate_client = fake` still reaches these routes.
`_assert_proxy_assignable` is also remote_login_api's custom-proxy check.
Included mid-file in server.py for route order (pinned by
service/tests/test_route_order.py).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

import accounts as account_registry
import proxies as proxy_registry
import proxy_health
from auth import assert_account_owned
from brand import BRAND_NAME
from relay_host import get_request_user as _get_request_user
from relay_host import invalidate_client as _invalidate_client
from relay_host import kick_db_sync as _kick_db_sync

router = APIRouter()


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


@router.get("/admin/proxies")
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
    # Watchers ride proxies too: a proxy one uses must read as in use.
    accounts = account_registry.list_accounts(include_watchers=True)
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


@router.post("/admin/proxies")
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


@router.post("/admin/proxies/bulk")
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


@router.delete("/admin/proxies/{label}")
def admin_proxies_remove(label: str) -> dict[str, Any]:
    """Delete a proxy no Creator uses. A proxy still bound to a live account
    is a 409 naming those Creators (Infloww's "Proxy already in use"): the
    owner unbinds or moves them first, so no Creator silently falls back to
    direct egress. Bindings left by a deleted account do not count, nor, for
    a signed-in caller, bindings to accounts it cannot see (GET /admin/proxies
    hides them too); those go with the proxy, as before."""
    p = _assert_proxy_owned_or_mine(label)
    user = _get_request_user()
    live = {a["id"]: a for a in account_registry.list_accounts(include_watchers=True)}
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


@router.post("/admin/proxies/assign")
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
@router.post("/admin/proxy-pool/assign")
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


@router.post("/admin/proxy-pool/unbind")
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


@router.post("/admin/proxies/{label}/unbind")
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


@router.post("/admin/proxies/{label}/test")
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
