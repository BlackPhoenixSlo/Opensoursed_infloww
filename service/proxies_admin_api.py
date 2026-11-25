from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

import accounts as account_registry
import proxies as proxy_registry
import proxy_health
import proxy_probe
from audit_log import credential_write
from auth import assert_account_owned
from brand import BRAND_NAME
from relay_host import get_request_user as _get_request_user
from relay_host import invalidate_client as _invalidate_client
from relay_host import kick_db_sync as _kick_db_sync

router = APIRouter()



# Creds are returned in plaintext on purpose so the UI can show host:port:user:pass.
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
    session_file: str | None = Field(None, description="LEGACY: session_*.json filename; prefer account_id")
    account_id: str | None = Field(None, description="OF account id to bind this proxy to (null to unassign)")


def _health_view(h: dict[str, Any], site_owner: bool, keys: tuple[str, ...] | None = None) -> dict[str, Any]:
    out = {k: v for k, v in h.items() if keys is None or k in keys}
    if not site_owner:
        out.pop("inflight", None)
        out.pop("inflight_peak", None)
        if "refusals" in out:
            out["refusals"] = {k: out["refusals"][k] for k in ("window_s", "pct")}
    return out


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
    pool_rows: list[dict[str, Any]] = []
    pool_size = pool_bad = 0
    down = proxy_health.down_labels()
    site_owner = user is None or user.is_admin
    for p in proxies_list:
        if proxy_registry.is_pool(p):
            # Pool proxies are never listed: only counts, and the viewer's accounts on one.
            pool_size += 1
            mine = [aid for aid in proxy_registry._ids_on(p) if aid in by_aid]
            pool_ids += mine
            pool_bad += p.get("label") in down
            if p.get("label") and (user is None or mine):
                pool_rows.append({"slot": pool_size, "health": _health_view(
                    proxy_health.snapshot(p["label"]), site_owner,
                    keys=("state", "down", "refusals", "inflight", "inflight_peak"))})
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
        out["assigned_account"] = bound[0] if bound else None
        out["assigned_account_id"] = bound[0]["id"] if bound else None
        out["url"] = proxy_registry.proxy_url(p)
        out["health"] = _health_view(proxy_health.snapshot(p["label"]), site_owner)
        enriched.append(out)
    return {
        "proxies": enriched,
        "pool": {"size": pool_size, "account_ids": pool_ids, "bad": pool_bad, "proxies": pool_rows},
        "accounts": [{
            "id": a["id"], "nickname": a.get("nickname"),
            "color": a.get("color"), "has_session": a.get("has_session", False),
        } for a in accounts],
    }


def _get_listed_proxy(label: str) -> dict[str, Any]:
    p = proxy_registry.get_by_label(label)
    if p is None or proxy_registry.is_pool(p):
        raise HTTPException(status_code=404, detail=f"no proxy with label {label!r}")
    return p


def _assert_proxy_owned_or_mine(label: str) -> dict[str, Any]:
    p = _get_listed_proxy(label)
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
    p = _get_listed_proxy(label)
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
            # Preserve owner: a payload field must not reassign ownership.
            payload["user_id"] = eu
        else:
            payload["user_id"] = user.id
    try:
        entry = proxy_registry.upsert(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # An upsert edits creds in place under the same label; pooled clients would keep dialing the OLD proxy.
    # Assignment is per session-file, owned by one account: invalidating the whole pool is the simplest correct option.
    _invalidate_client()
    _kick_db_sync(f"proxy-upsert-{body.label}")
    return {"ok": True, "proxy": entry}


class _ProxyBulkBody(BaseModel):
    text: str
    scheme: str = "http"


def _proxy_owner() -> str | None:
    user = _get_request_user()
    return user.id if user is not None else None


@router.post("/admin/proxies/bulk", dependencies=[Depends(credential_write)])
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
        # An explicit null account_id is a "please unassign" signal.
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


# Own prefix so no custom proxy label can shadow these routes.
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
    user = _get_request_user()
    p = _get_listed_proxy(label)
    if user is not None:
        pu = p.get("user_id")
        if pu is not None and pu != user.id:
            raise HTTPException(status_code=404, detail=f"no proxy with label {label!r}")
    # `ok` is the health probe's (tunnels to OF), so it never says ok where health says bad.
    with ThreadPoolExecutor(2) as pool:
        health_f, trace_f = pool.submit(proxy_probe.probe_of, p), pool.submit(proxy_probe.probe, p)
        health, trace = health_f.result(), trace_f.result()
    ok = bool(health.get("ok"))
    # A failed trace (1.1.1.1 blocked) has no ip: record_verification keeps the last ip/geo.
    proxy_registry.record_verification(label, ip=trace.get("ip"), geo=trace.get("geo"), ok=ok)
    proxy_health.note_trace(label, trace)
    egress = {k: trace.get(k) for k in ("ip", "geo", "colo")}
    if ok and egress["ip"] is None:
        egress.update(ip=p.get("verified_ip"), geo=p.get("verified_geo"))
    return {"ok": ok, "error": health.get("error"), "ttfb_ms": health.get("ttfb_ms"), **egress}
