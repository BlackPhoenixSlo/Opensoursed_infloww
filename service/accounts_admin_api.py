"""service/accounts_admin_api.py — server.py's session + multi-account admin
block, moved wholesale.

  POST   /admin/reload-session              hot-swap an account's OFClient
  GET    /admin/rev/live                    OF's live build + last sign-rule refresh
  POST   /admin/session/bootstrap           paste-curl session capture
  POST   /admin/session/fansly              register a Fansly session blob
  GET    /admin/accounts                    the principal's accounts
  GET    /admin/accounts/roster-counts      per-model inbox badge counts
  POST   /admin/accounts/active             default account
  PATCH  /admin/accounts/{account_id}       rename / recolor
  DELETE /admin/accounts/{account_id}       remove an account
  POST   /admin/accounts/{account_id}/active  Deactivate / Activate

Server globals (`_load_client`, `_invalidate_client`, `_get_request_user`,
the chats-window cache, ...) are relay_host's call-time forwards, never
`from server import`, so a test's `server._load_client = fake` still reaches
these routes. `_ROSTER_SCAN_MAX` lives here; server.py's list_chats imports it.
Included mid-file in server.py for route order (pinned by
service/tests/test_route_order.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time as _time_mod
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

import account_health
import accounts as account_registry
import live_rev
import proxies as proxy_registry
import proxy_health
import relay_cache
import sign_rules
import vault_cache
from auth import assert_account_owned
from chatters import get_request_chatter as _get_request_chatter
from relay_host import assemble_chats_page as _assemble_chats_page
from relay_host import chats_window_fetched_at as _chats_window_fetched_at
from relay_host import get_request_user as _get_request_user
from relay_host import invalidate_client as _invalidate_client
from relay_host import kick_db_sync as _kick_db_sync
from relay_host import list_chats_ttl
from relay_host import load_client as _load_client
from relay_host import post_bootstrap_hooks
from relay_host import roster_window_max_age_s
from relay_host import server_module_name
from relay_host import stop_account_pump as _stop_account_pump
from relay_host import sync_and_link_after_bootstrap as _sync_and_link_after_bootstrap

log = logging.getLogger("of-relay")

router = APIRouter()


# ── Admin ──────────────────────────────────────────────────────

@router.post("/admin/reload-session")
def reload_session(account_id: str | None = Query(None)) -> dict[str, Any]:
    """Hot-swap an account's OFClient (re-read its latest session from disk).
    `account_id` defaults to the currently-active account."""
    aid = account_id or account_registry.get_active_account_id()
    if not aid:
        raise HTTPException(status_code=503, detail="no active account")
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


@router.post("/admin/session/fansly")
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

@router.get("/admin/accounts")
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
        fetched_at = _chats_window_fetched_at().get(account_id)
        from of_ws import connected_since
        live_since = connected_since(account_id)
        ws_kept = fetched_at is not None and live_since is not None and fetched_at >= live_since
        if fetched_at is None or (
            not ws_kept and _time_mod.monotonic() - fetched_at > roster_window_max_age_s()
        ):
            bypass = True

    def _fetch_window() -> dict[str, Any]:
        value = _assemble_chats_page(
            client, limit=_ROSTER_SCAN_MAX, offset=0, order="recent",
        )
        _chats_window_fetched_at()[account_id] = _time_mod.monotonic()
        return value

    resp = await relay_cache.get_or_fetch(
        "list_chats", account_id,
        (_ROSTER_SCAN_MAX, 0, "recent", None, None, None),
        ttl_seconds=list_chats_ttl(),
        fetcher=_fetch_window,
        bypass=bypass,
    )
    rows = resp.get("list") or resp.get("chats") or []
    from automations._common import load_of_restricted_ids
    exclude = await load_of_restricted_ids(account_id)
    return _roster_counts_from_rows(rows, str(client.user_id), exclude)


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
    __module__ = server_module_name()  # keeps its OpenAPI name (server___ActivateBody): account_security_api has one too
    account_id: str | None


@router.post("/admin/accounts/active")
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


@router.delete("/admin/accounts/{account_id}")
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
