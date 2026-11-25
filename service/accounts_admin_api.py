from __future__ import annotations

import asyncio
import json
import logging
import time as _time_mod
from typing import Any, Callable

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

import account_health
import accounts as account_registry
import client_pool
import live_rev
import notifications_api
import proxies as proxy_registry
import proxy_health
import relay_cache
import shared_refresher
import sign_rules
import split_inbox
import unread_total_decide
import vault_cache
from audit_log import credential_write
from auth import assert_account_owned, require_actor_account_ids
from chatters import get_request_chatter as _get_request_chatter
from relay_host import assemble_chats_page as _assemble_chats_page
from relay_host import chats_window_fetched_at as _chats_window_fetched_at
from relay_host import get_request_user as _get_request_user
from relay_host import flag_dead_session as _flag_dead_session
from relay_host import invalidate_client as _invalidate_client
from relay_host import kick_db_sync as _kick_db_sync
from relay_host import list_chats_ttl
from relay_host import load_client as _load_client
from relay_host import post_bootstrap_hooks
from relay_host import roster_window_max_age_s
from relay_host import server_module_name
from relay_host import spawn_bg as _spawn_bg
from relay_host import stop_account_pump as _stop_account_pump

log = logging.getLogger("of-relay")

router = APIRouter()



def owned_account_ids() -> list[str]:
    ids = require_actor_account_ids()
    if ids is None:
        return []
    return [str(a["id"]) for a in account_registry.list_accounts() if a.get("id") in ids]


@router.post("/admin/reload-session")
def reload_session(account_id: str | None = Query(None)) -> dict[str, Any]:
    """Hot-swap an account's OFClient (re-read its latest session from disk).
    `account_id` defaults to the currently-active account."""
    aid = account_id or account_registry.get_active_account_id()
    if not aid:
        raise HTTPException(status_code=503, detail="no active account")
    # The resolved id, not just the query's: the default is relay-wide and may be another Agency's Creator.
    assert_account_owned(aid)
    _invalidate_client(aid)
    c = _load_client(aid)
    return {"ok": True, "account_id": aid, "user_id": c.user_id, "x_of_rev": c.x_of_rev}


@router.get("/admin/rev/live")
def admin_rev_live() -> dict[str, Any]:
    """OF's live build (`x-of-rev`) as the relay last saw it on OF's own API
    responses (live_rev.py), plus the last central sign-rule refresh. The
    founder's OF Manager mirror-freshness banner reads `live_rev`. A session
    captured at an older build keeps working, so nothing here flags sessions."""
    live_snap = live_rev.get()
    return {
        "live_rev": live_snap.get("rev"),
        "live_fetched_at": live_snap.get("fetched_at"),
        "sign_rules": sign_rules.last(),
    }


class _BootstrapBody(BaseModel):
    mode: str = Field(..., description="'paste-curl'")
    curl: str | None = Field(None, description="Required for mode=paste-curl — `curl …` from DevTools")
    static_param_override: str | None = Field(None, description="Optional override for an unfamiliar OF revision")
    account_id: str | None = Field(None, description="Hint: re-capture for this account (uses its stored proxy)")
    nickname: str | None = Field(None, description="Friendly label persisted to the account meta")
    make_active: bool = Field(True, description="Flip the relay's active account to the newly-captured one")


@router.post("/admin/session/bootstrap")
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
    except account_registry.PlatformCollision as e:
        raise HTTPException(status_code=409, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        log.exception("bootstrap failed")
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")

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


@router.post("/admin/session/fansly", dependencies=[Depends(credential_write)])
def bootstrap_fansly_session(body: _FanslySessionBody = Body(...)) -> dict[str, Any]:
    """Register a Fansly account from a captured session blob.

    The Fansly twin of /admin/session/bootstrap's paste-curl mode — but there
    is no curl and no signing to derive: the session is a small JSON blob the
    extension lifts out of the fansly.com tab. Nothing is written until the
    token's own `me()` answers as `accountId` (else 400) and the id is no other
    Platform's Creator (else 409); then the blob lands beside the OF accounts,
    the meta gets platform="fansly" + the creator's display name, and the same
    post_bootstrap_hooks the OF path runs evict, reload and restart the pump."""
    import fansly_backend
    import platforms

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

    try:
        adir = account_registry.account_dir(account_id)
    except account_registry.NotAnAccountId as e:
        raise HTTPException(status_code=400, detail=str(e))

    def _refuse_collision() -> None:
        try:
            account_registry.ensure_platform(account_id, platforms.FANSLY.key)
        except account_registry.PlatformCollision as e:
            raise HTTPException(status_code=409, detail=str(e))

    _refuse_collision()
    try:
        me, session = fansly_backend.identify(session)
    except Exception as e:  # noqa: BLE001 — any failure means the token is not proven
        why = f"{type(e).__name__}: {e}"
        if body.token:  # client errors can carry request headers
            why = why.replace(body.token, "***")
        log.warning("fansly session for %s not proven: %s", account_id, why)
        raise HTTPException(status_code=400, detail=f"Fansly did not accept this session: {why}")
    me_id = str(me.get("id") or "")
    if me_id != account_id:
        raise HTTPException(status_code=400, detail=(
            f"this session signs in as Fansly account {me_id or '(none)'}, not {account_id}"))
    _refuse_collision()

    name = me.get("name") or me.get("username")
    adir.mkdir(parents=True, exist_ok=True)
    session_file = adir / fansly_backend.SESSION_FILENAME
    session_file.write_text(json.dumps(session, indent=2) + "\n")
    try:
        session_file.chmod(0o600)
    except OSError:
        pass

    account_registry.upsert_account(
        account_id,
        platform=platforms.FANSLY.key,
        name=name,
        nickname=body.nickname or name or f"Fansly {account_id}",
    )
    if body.make_active:
        account_registry.set_active_account_id(account_id)

    post_bootstrap_hooks(account_id)

    return {"ok": True, "account_id": account_id, "platform": "fansly", "name": name}



@router.get("/admin/accounts")
async def admin_accounts_list(response: Response) -> dict[str, Any]:
    """List every account the signed-in user owns + the currently-active one
    (clamped to the user's set). The UI populates its switcher from this.

    Account lists are PER-PRINCIPAL and must never be cached — a response
    fetched in one auth state must not be replayed in another — hence
    `no-store`. An UNauthenticated caller gets an EMPTY list, never the full
    multi-tenant registry: that fallback used to leak every owner's models,
    get cached by the client, and then 403 on save ("account X is not one of
    yours"). Sign in to get the real, `user_accounts`-scoped list.

    `watchers`: the caller's watcher accounts (`role` "watcher", a fan account
    that reads what the Creators send), never in `accounts` (every sending / automation
    surface reads `accounts`), with the same fields as a Creator so Manage
    creators can edit one and OF Manager can browse as it. A watcher is never
    `active_account_id`."""
    response.headers["Cache-Control"] = "no-store"
    user = _get_request_user()
    if user is None:
        # Anonymous: expose nothing; leaking the registry here poisoned client caches across owners.
        return {"accounts": [], "active_account_id": None, "watchers": []}
    mine = [a for a in account_registry.list_accounts(include_watchers=True) if a.get("id") in user.account_ids]
    all_accounts = [a for a in mine if a.get("role") != account_registry.ROLE_WATCHER]
    watchers = [a for a in mine if a.get("role") == account_registry.ROLE_WATCHER]
    try:
        dead = await account_health.dead_session_map()
        off = await account_health.deactivated_ids()
    except Exception:
        log.exception("dead_session_map failed")
        dead, off = {}, set()
    bad = proxy_health.bad_reasons()
    for a in all_accounts + watchers:
        health = dead.get(a.get("id"), account_health.NO_DEAD_SESSION)
        a["session_dead_at"] = health.at
        a["session_dead_reason"] = health.reason
        a["is_active"] = a.get("id") not in off
        reason = bad.get((proxy_registry.get_for_account(a["id"]) or {}).get("label")) if bad else None
        a["proxy_down"] = reason is not None
        if reason:
            a["proxy_bad_reason"] = reason
    if shared_refresher.ENABLED:
        for a in all_accounts:
            a["freshness"] = shared_refresher.snapshot(a["id"])
    active = account_registry.get_active_account_id()
    if active not in {a.get("id") for a in all_accounts}:
        active = all_accounts[0]["id"] if all_accounts else None
    return {
        "accounts": all_accounts,
        "active_account_id": active,
        "watchers": watchers,
    }


# Badge window must equal the inbox first page (same list_chats entry); local chats (phantom rows, drifting unread_count), deep scans and filter=unread all disagreed.
_ROSTER_SCAN_MAX = unread_total_decide.WINDOW
_ROSTER_WINDOW_KEY = (_ROSTER_SCAN_MAX, 0, "recent", None, None, None)
ROSTER_COUNT_TTL_S = 300.0
_roster_last: dict[str, dict[str, int]] = {}


def held_window(aid: str) -> dict | None:
    value = relay_cache.peek("list_chats", aid, _ROSTER_WINDOW_KEY)
    return value if isinstance(value, dict) else None


def patch_window(aid: str, changes: dict[int, Callable[[dict], dict]]) -> None:
    def patch(extras: tuple, value: Any) -> Any:
        if extras != _ROSTER_WINDOW_KEY:
            return None
        if not isinstance(value, dict):
            return value
        key = "list" if "list" in value else "chats"
        rows = []
        for row in unread_total_decide.window_rows(value):
            change = changes.get(unread_total_decide.window_fan_id(row))
            rows.append(change(row) if change is not None else row)
        return {**value, key: rows}

    relay_cache.patch("list_chats", aid, patch)


def _roster_counts_from_rows(
    rows: list[dict[str, Any]], exclude: frozenset[int] | set[int] = frozenset(),
) -> dict[str, int]:
    # Excluded chat still occupies a window slot (badge parity with the first page) but never counts unread.
    return _window_roster_counts(_window_chats(rows), exclude)


def _window_roster_counts(
    window: list[tuple[Any, dict[str, Any]]], exclude: frozenset[int] | set[int],
) -> dict[str, int]:
    blue = counted = 0
    for fid, ch in window:
        if unread_total_decide.excluded_from_badges(fid, ch, exclude):
            continue
        counted += 1
        if int(ch.get("unreadMessagesCount") or 0) > 0:
            blue += 1
    out = {"unread": blue}
    if len(window) >= _ROSTER_SCAN_MAX and blue > 0 and blue == counted:
        out["unread_capped"] = True
    return out


def _window_chats(rows: list[dict[str, Any]]) -> list[tuple[Any, dict[str, Any]]]:
    out: list[tuple[Any, dict[str, Any]]] = []
    seen: set[Any] = set()
    for ch in rows:
        fid = (ch.get("withUser") or {}).get("id")
        if fid is None or fid in seen:
            continue
        if len(seen) >= _ROSTER_SCAN_MAX:
            break
        seen.add(fid)
        out.append((fid, ch))
    return out


async def _compute_roster_count_of(account_id: str, *, bypass: bool = False) -> dict[str, int]:
    client = await asyncio.to_thread(_load_client, account_id)
    if not bypass:
        # Never fold a window older than the re-read cadence: near-expiry plus the 300s roster TTL serves ~900s-old counts on a WS-dead account.
        fetched_at = _chats_window_fetched_at().get(account_id)
        from of_ws import connected_since
        live_since = connected_since(account_id)
        ws_kept = fetched_at is not None and live_since is not None and fetched_at >= live_since
        if fetched_at is None or (
            not ws_kept and _time_mod.monotonic() - fetched_at > roster_window_max_age_s()
        ):
            bypass = True

    fetched_at = None

    def _fetch_window() -> dict[str, Any]:
        nonlocal fetched_at
        value = _assemble_chats_page(
            client, limit=_ROSTER_SCAN_MAX, offset=0, order="recent",
        )
        fetched_at = _time_mod.monotonic()
        return {**value, "fetched_at": int(_time_mod.time() * 1000)}

    resp = await relay_cache.get_or_fetch(
        "list_chats", account_id, _ROSTER_WINDOW_KEY,
        ttl_seconds=list_chats_ttl(),
        fetcher=_fetch_window,
        bypass=bypass,
    )
    if fetched_at is not None and held_window(account_id) is resp:
        _chats_window_fetched_at()[account_id] = fetched_at
    counts = await fold_held_roster_window(account_id, str(client.user_id))
    if counts is None:
        # An invalidation during the list read must also fence the roster cache write-back.
        relay_cache.invalidate("roster_count", account_id)
        return _roster_last.get(account_id, {"unread": 0, "owe_reply": 0, "as_of": 0})
    return counts


async def _window_fold_inputs(aid: str) -> tuple[frozenset[int], dict | None, list[dict] | None, int]:
    from automations._common import load_of_restricted_ids

    exclude = frozenset(await load_of_restricted_ids(aid))
    resp = held_window(aid)
    if resp is None:
        return exclude, None, None, 0
    return exclude, resp, unread_total_decide.window_rows(resp), resp.get("fetched_at") or 0


async def fold_held_roster_window(account_id: str, me: str) -> dict[str, int] | None:
    exclude, resp, rows, as_of = await _window_fold_inputs(account_id)
    if resp is None:
        return None
    window = _fold_registry(account_id, rows, as_of, exclude, me)
    out = {**_window_roster_counts(window, exclude), "owe_reply": _amber_set(account_id, resp), "as_of": as_of}
    _roster_last[account_id] = out
    return out


def _amber_set(aid: str, resp: dict[str, Any]) -> int:
    import badge_reads
    import unread_total
    me, exclude = _amber_ctx[aid]
    view = badge_reads.unread_set(aid)
    rows = unread_total_decide.overlay(unread_total_decide.window_rows(resp), badge_reads.arrivals(aid),
                                       resp.get("asked_at"), me)
    n = unread_total_decide.amber_count(rows, me, exclude, None if view is None else view.fans)
    at = resp.get("fetched_at")
    if unread_total.ENABLED and at is not None:
        unread_total.set_amber(aid, n, at)
    return n


_amber_ctx: dict[str, tuple[str, frozenset[int]]] = {}


def amber_creator_id(aid: str) -> str | None:
    ctx = _amber_ctx.get(aid)
    return None if ctx is None else ctx[0]


def amber_refresh(account_id: str) -> int | None:
    try:
        import unread_total
        aid = str(account_id)
        resp = held_window(aid)
        if not unread_total.ENABLED or aid not in _amber_ctx or resp is None:
            return None
        n = _amber_set(aid, resp)
        held = relay_cache.peek("roster_count", aid, ())
        if isinstance(held, dict) and held.get("owe_reply") != n:
            relay_cache.patch("roster_count", aid, lambda _ex, v: {**v, "owe_reply": n} if isinstance(v, dict) else v)
        if aid in _roster_last:
            _roster_last[aid] = {**_roster_last[aid], "owe_reply": n}
        return n
    except Exception:  # noqa: BLE001 — the change already happened; the next trigger re-folds
        log.warning("amber_refresh_failed account=%s", account_id, exc_info=True)
        return None


def _fold_registry(
    aid: str, rows: list[dict[str, Any]] | None, as_of: int, exclude: frozenset[int], me: str | None = None,
) -> list[tuple[Any, dict[str, Any]]]:
    import badge_reads
    window = _window_chats(rows) if rows is not None else []
    badge_reads.rescore(aid, rows, exclude, as_of)
    if me is not None:
        _amber_ctx[aid] = (me, exclude)
    elif aid in _amber_ctx:
        _amber_ctx[aid] = (_amber_ctx[aid][0], exclude)
    return window


async def restrict_refresh(account_id: str) -> None:
    aid = str(account_id)
    try:
        exclude, _, rows, as_of = await _window_fold_inputs(aid)
        _fold_registry(aid, rows, as_of, exclude)
    except Exception:  # noqa: BLE001 — the restrict already landed; the next fold re-reads the registry
        log.warning("restrict_refresh_failed account=%s", aid, exc_info=True)
    amber_refresh(aid)


async def _held_roster_count(account_id: str) -> dict[str, int] | None:
    resp = held_window(account_id)
    if resp is not None and resp.get("fetched_at") is not None:
        try:
            client = await asyncio.to_thread(_load_client, account_id)
            counts = await fold_held_roster_window(account_id, str(client.user_id))
            if counts is not None:
                return counts
        except Exception:  # noqa: BLE001 — no client to fold with: the last-known count
            log.debug("roster-counts: held window not folded for %s", account_id, exc_info=True)
    return _roster_last.get(account_id)


def _principal() -> tuple[str, Any, list[str]] | None:
    user = _get_request_user()
    if user is not None:
        return "user", user, list(user.account_ids or ())
    chatter = _get_request_chatter()
    if chatter is not None:
        return "chatter", chatter, list(chatter.account_ids or ())
    return None


def _roster_answer(counts: dict[str, Any], grouped: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    grouped = grouped or {}
    return {"counts": {aid: grouped[aid] if aid in grouped else _red(aid, c) for aid, c in counts.items()},
            "now": int(_time_mod.time() * 1000)}


async def _group_counts(counts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    import badge_reads
    out: dict[str, dict[str, Any]] = {}
    chatter_id = split_inbox.acting_chatter_id()
    if chatter_id is None:
        return out
    for aid in counts:
        keep = await split_inbox.filter_for(chatter_id, aid)
        if keep is None:
            continue
        resp = held_window(aid)
        ctx = _amber_ctx.get(aid)
        if resp is None or ctx is None:
            out[aid] = {"unread": 0, "owe_reply": 0, "as_of": 0}
            continue
        me, exclude = ctx
        rows = [r for r in unread_total_decide.window_rows(resp)
                if keep((r.get("withUser") or {}).get("id"))]
        view = badge_reads.unread_set(aid)
        late = unread_total_decide.overlay(rows, badge_reads.arrivals(aid), resp.get("asked_at"), me)
        out[aid] = {"unread": _roster_counts_from_rows(rows, exclude)["unread"],
                    "owe_reply": unread_total_decide.amber_count(late, me, exclude,
                                                                 None if view is None else view.fans),
                    "as_of": resp.get("fetched_at") or 0}
    return out


def _red(account_id: str, count: dict[str, Any]) -> dict[str, Any]:
    import unread_total
    slot = unread_total.snapshot(account_id)
    if slot is None or slot.get("grey") or slot.get("n") is None:
        return count
    return {**{k: v for k, v in count.items() if k != "unread_capped"}, "unread": slot["n"], "as_of": slot["at"]}


@router.get("/admin/accounts/roster-counts")
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
    principal = _principal()
    ids = principal[2] if principal is not None else []
    # Watcher is never read here: a dead-session mark would pause it.
    ids = [a for a in ids if not account_registry.is_watcher(a)]
    if not ids:
        return _roster_answer({})

    async def _one(aid: str, *, bypass: bool = False) -> tuple[str, dict[str, int]]:
        client = client_pool.peek(aid)
        try:
            # Named async closure, not a lambda: get_or_fetch threads sync fetchers and a lambda's coroutine would go unawaited.
            async def _fetch() -> dict[str, int]:
                return await _compute_roster_count_of(aid, bypass=bypass)
            value = await relay_cache.get_or_fetch(
                "roster_count", aid, (),
                ttl_seconds=ROSTER_COUNT_TTL_S,
                fetcher=_fetch,
            )
            return aid, value
        except Exception as e:  # noqa: BLE001 — one bad model must not blank the strip
            log.warning("roster-counts: OF read failed for %s", aid, exc_info=True)
            await _flag_dead_session(aid, e, "roster-counts", client)
            return aid, {"unread": 0, "owe_reply": 0, "as_of": 0}

    # Comment, not docstring: the docstring is the OpenAPI description, pinned by test_route_order.
    # OF read only for leased/bust/App-open-warm Creators; others and Dead-session ones are served from the held window (_held_roster_count).
    import view_lease
    leased = view_lease.leased_ids()
    dead = set(await account_health.dead_session_map())

    async def _served(aid: str) -> tuple[str, dict[str, int] | None]:
        if aid in leased and aid not in dead:
            return await _one(aid)
        return aid, await _held_roster_count(aid)

    # Ownership-gated: a crafted bust can't evict another tenant's entry; bypass=True forces a live read and rewarms list_chats page 0.
    if bust and bust in ids:
        if bust in dead:
            held = await _held_roster_count(bust)
            counts = {bust: held} if held is not None else {}
            return _roster_answer(counts, await _group_counts(counts))
        async def _rewarm() -> dict[str, int]:
            relay_cache.invalidate("roster_count", bust)
            return (await _one(bust, bypass=True))[1]

        import badge_reads
        value = await badge_reads.hover(bust, _rewarm, lambda: _held_roster_count(bust))
        counts = {bust: value} if value is not None else {}
        return _roster_answer(counts, await _group_counts(counts))

    pairs = await asyncio.gather(*[_served(a) for a in ids])
    counts = {aid: c for aid, c in pairs if c is not None}
    return _roster_answer(counts, await _group_counts(counts))


async def rewarm_roster_count(account_id: str) -> dict[str, int]:
    relay_cache.invalidate("roster_count", account_id)

    async def _fetch() -> dict[str, int]:
        return await _compute_roster_count_of(account_id, bypass=True)
    return await relay_cache.get_or_fetch("roster_count", account_id, (), ttl_seconds=ROSTER_COUNT_TTL_S,
                                          fetcher=_fetch)


_VIEW_LEASE_MAX_IDS = 200


async def _select_refresh(account_id: str) -> None:
    import of_call_counter
    import purchase_poll
    with of_call_counter.caller("select_refresh"):
        await purchase_poll.poll_now(account_id)


class _ViewLeaseBody(BaseModel):
    tab: str = Field(min_length=1, max_length=64)
    account_ids: list[str] = Field(max_length=_VIEW_LEASE_MAX_IDS)
    selected: str | None = None
    opened: bool = False


@router.post("/admin/view-lease")
async def admin_view_lease(body: _ViewLeaseBody = Body(...)) -> dict[str, Any]:
    """Renew this tab's View lease: the Creators it shows now (`view_lease`). Owner or chatter
    session, no X-Account-Id. Ids outside the principal's Creators, and watchers, are dropped
    silently (as roster-counts), re-filtered on every renewal; `selected` is leased too; no ids and
    no `selected` releases the tab; no wildcard. A changed `selected`, or one nobody leased before, gets one purchases
    poll now (`purchase_poll.poll_now`, Caller kind `select_refresh`), in the background, unless a poll started
    within SELECT_MIN_AGE_S (ok or not); its exit's next paced read waits GAP_S (`app_open_warm.note_read`). Any other
    Creator nobody leased before gets the same poll through `app_open_warm`'s one per-exit gate (`pace`, shared with
    every renewal and warm), unless `app_open_warm.current` (a poll started within PURCHASES_POLL_FAST_S or warmed
    within APP_OPEN_WARM_REUSE_S) or the post is `opened` (the warm reads it, leased first, same gate)
    (`view_lease.refresh_plan`).
    `opened` (a document load's first renewal) also starts the App-open warm of every Creator the
    principal can access (`app_open_warm.start`; the Select-refreshed ones count as warmed); `warm` answers
    started | reused | none, "none" unless `opened`. Not audited (audit_log skip list)."""
    import app_open_warm
    import view_lease

    principal = _principal()
    if principal is None:
        raise HTTPException(status_code=401, detail="sign in required")
    kind, who, order = principal
    pid = str(who.id)
    allowed = set(order)

    def ok(a: str | None) -> bool:
        return a is not None and a in allowed and not account_registry.is_watcher(a)

    selected = body.selected if ok(body.selected) else None
    ids = [a for a in dict.fromkeys([*body.account_ids, *([selected] if selected else [])]) if ok(a)]
    refreshed, paced = view_lease.refresh_plan(view_lease.renew((kind, pid, body.tab), ids, selected), selected,
                                               opened=body.opened, current=app_open_warm.current,
                                               fresh=app_open_warm.just_polled)
    for aid in refreshed:
        app_open_warm.note_read(aid)
        _spawn_bg(_select_refresh(aid), f"select-refresh:{aid}")
    if paced:
        app_open_warm.pace(paced, _select_refresh)
    warm = "none"
    if body.opened:
        got = await app_open_warm.start((kind, pid), [a for a in order if ok(a)], view_lease.leased_ids(),
                                        refreshed=refreshed)
        warm = app_open_warm.summary(got)
    return {"leased": ids, "ttl_s": view_lease.TTL_S, "warm": warm}


class _ActivateBody(BaseModel):
    __module__ = server_module_name()  # keeps its OpenAPI name (server___ActivateBody): account_security_api has one too
    account_id: str | None


@router.post("/admin/accounts/active")
def admin_accounts_activate(body: _ActivateBody = Body(...)) -> dict[str, Any]:
    """Flip which account is the default (no X-Account-Id header → this one)."""
    assert_account_owned(body.account_id if body.account_id is not None
                         else account_registry.get_stored_active_account_id())
    if body.account_id is not None and account_registry.get_account(body.account_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown account {body.account_id!r}")
    if not account_registry.set_active_account_id(body.account_id):
        raise HTTPException(status_code=400, detail="a watcher account cannot be the default")
    _kick_db_sync("accounts-active")
    return {"ok": True, "active_account_id": body.account_id}


class _AccountUpdateBody(BaseModel):
    nickname: str | None = None
    color: str | None = None


@router.patch("/admin/accounts/{account_id}")
def admin_accounts_update(account_id: str, body: _AccountUpdateBody = Body(...)) -> dict[str, Any]:
    """Rename / recolor. Doesn't touch sessions.

    A chatter principal may ONLY recolor — `nickname` is owner management. For
    a chatter every field except `color` is forced to None so a crafted body
    can't rename. Owners and unauthed internal
    callers (curl/setup flows) keep the full field set. The chatter-allowed-admin
    gate already restricts chatters here to PATCH-only."""
    if account_registry.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown account {account_id!r}")
    # Assert ownership here: the isolation middleware only checks numeric path segments.
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


@router.delete("/admin/accounts/{account_id}")
async def admin_accounts_remove(account_id: str) -> dict[str, Any]:
    """Permanently remove an account dir (sessions + meta). Stops its WS pump,
    drops its pooled client, and clears every server-side cache scoped to it.
    Cannot be undone."""
    if account_registry.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown account {account_id!r}")
    _stop_account_pump(account_id)
    _invalidate_client(account_id)
    # Purge caches so a re-added account can't read the prior session's chats/vault; best-effort.
    try:
        relay_cache.invalidate_account(account_id)
    except Exception as e:  # noqa: BLE001
        log.warning("relay_cache: invalidate-on-delete failed for %s: %s", account_id, e)
    try:
        await vault_cache.invalidate(account_id)
    except Exception as e:  # noqa: BLE001
        log.warning("vault_cache: invalidate-on-delete failed for %s: %s", account_id, e)
    try:
        await notifications_api.drop_pinned(account_id)
    except Exception as e:  # noqa: BLE001
        log.warning("notifications: drop-pinned-on-delete failed for %s: %s", account_id, e)
    ok = account_registry.delete_account(account_id)
    _kick_db_sync(f"accounts-delete-{account_id}")
    return {"ok": ok}


class _AccountActiveBody(BaseModel):
    active: bool


@router.post("/admin/accounts/{account_id}/active")
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
    it, stamped `is_active: false`. Proxy bindings stay in place for carrier
    cleanup and resumption. Billing and seat counts do not change —
    Infloww's own warning: fees still apply.

    Activate clears it; the pump supervisor restarts the pump within 15s.
    Jobs that fell due while it was off are cancelled as missed
    (`automation_executor.cancel_jobs_missed_while_off`), and a gap longer than
    the ledger's recent window is backfilled
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
    # Cancel jobs that fell due while off before activate(), while the flag still holds the executor off them.
    off_since = await account_health.deactivated_since(account_id)
    if off_since is not None:
        from automation_executor import cancel_jobs_missed_while_off
        await cancel_jobs_missed_while_off(account_id, off_since)
    since = await account_health.activate(account_id)
    if since is not None:
        from transaction_ingest import backfill_after_reactivation
        await backfill_after_reactivation(account_id, since)
    return {"ok": True, "account_id": account_id, "is_active": True}
