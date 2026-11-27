from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from auth import get_request_user, split_account_ids
from chatters import get_request_chatter
from db.engine import get_session
from employee_groups_api import subtree_employee_ids
from employees import AgencyContext, agency_contexts, remember_chatter_employee
from send_ops import cells
from settings_schema import (  # noqa: F401 (REVENUE_CARD_KEYS: this module's API too)
    BUILT_IN_ROLE_DEFAULTS, BUILT_IN_ROLE_IDS, CARD_KEYS, DASHBOARD_CARDS, REVENUE_CARD_KEYS,
)

Scope = Literal["all", "self"]

_EVERY_PAGE: dict[str, Any] = {"scope": "all"}


def enforced(roles: dict[str, Any]) -> bool:
    return roles.get("enforce") is not False


def _role(roles: dict[str, Any], employee_id: int | None) -> dict[str, Any] | None:
    if employee_id is None:
        return None
    role_id = (roles.get("assignments") or {}).get(str(employee_id))
    if not isinstance(role_id, str):
        return None
    for role in roles.get("roles") or []:
        if role.get("id") == role_id:
            return role
    if role_id in BUILT_IN_ROLE_DEFAULTS:
        d = BUILT_IN_ROLE_DEFAULTS[role_id]
        permissions = {href: True for href in d["pages"]} | dict.fromkeys(d.get("denied", ()), False)
        return {"id": role_id, "scope": d["scope"], "permissions": permissions}
    return _EVERY_PAGE if role_id in BUILT_IN_ROLE_IDS else None


def _granting_role(roles: dict[str, Any], employee_id: int | None) -> dict[str, Any] | None:
    role = _role(roles, employee_id)
    off = role is not None and role.get("disabled") is True and role.get("id") not in BUILT_IN_ROLE_IDS
    return None if off else role


OPT_IN_PAGES: frozenset[str] = frozenset({
    "/growth/auto-post", "/growth/auto-story", "/growth/auto-mass",
    "/growth/auto-reply", "/growth/auto-funnel", "/growth/gen-info",
})

# The automation_rules kinds only a My Automations page writes, and that page.
# A rule write of one of these kinds needs the page (`require_opt_in_page`);
# every other kind (Smart Messages' welcome, follow-up, unsend…) is unchanged.
OPT_IN_KINDS: dict[str, str] = {
    "auto_posts": "/growth/auto-post",
    "auto_stories": "/growth/auto-story",
    "mass_premade": "/growth/auto-mass",
    "autoreply": "/growth/auto-reply",
    "reply_mass_funnel": "/growth/auto-funnel",
    "gen_info": "/growth/gen-info",
    # Not in OPT_IN_PAGES, so no stored role grants it: every chatter is refused the switch.
    "full_ai_chat": "/full-ai-chatter",
}


def opt_in_granted(ctx: AgencyContext, roles: dict[str, Any]) -> set[str]:
    if ctx.is_owner:
        return set(OPT_IN_PAGES)
    if not enforced(roles):
        return set()
    role = _granting_role(roles, ctx.employee_id)
    if role is None or role is _EVERY_PAGE:
        return set()
    return {h for h in OPT_IN_PAGES if (role.get("permissions") or {}).get(h) is True}


def denied_detail(pages: Iterable[str]) -> str:
    return "Your role does not allow " + " or ".join(PAGE_MAP[p][0] for p in pages)


def granted_pages(ctx: AgencyContext, roles: dict[str, Any]) -> set[str] | None:
    if ctx.is_owner or not enforced(roles):
        return None
    role = _granting_role(roles, ctx.employee_id)
    if role is None:
        return set()
    if role is _EVERY_PAGE:
        return None
    return {href for href, ok in (role.get("permissions") or {}).items() if ok is True and "#" not in href}


LEAK_PAGE = "/creators/leaks"


def _leak_role(ctx: AgencyContext, roles: dict[str, Any]) -> dict[str, Any] | None:
    if not enforced(roles):
        return None
    return _granting_role(roles, ctx.employee_id)


def _owner_or_admin(role: dict[str, Any] | None) -> bool:
    return role is _EVERY_PAGE or (role is not None and role.get("id") in ("owner", "admin"))


# Fails closed, unlike granted_pages: enforcement off or no role never grants the Leak tracker.
def leak_page_granted(ctx: AgencyContext, roles: dict[str, Any]) -> bool:
    if ctx.is_owner:
        return True
    role = _leak_role(ctx, roles)
    return _owner_or_admin(role) or (role is not None and (role.get("permissions") or {}).get(LEAK_PAGE) is True)


def leak_writer(ctx: AgencyContext, roles: dict[str, Any]) -> bool:
    return ctx.is_owner or _owner_or_admin(_leak_role(ctx, roles))


def denied_actions(ctx: AgencyContext, roles: dict[str, Any]) -> set[str]:
    if ctx.is_owner or not enforced(roles):
        return set()
    role = _granting_role(roles, ctx.employee_id)
    if role is None or role is _EVERY_PAGE:
        return set()
    return {k for k, ok in (role.get("permissions") or {}).items()
            if "#" in k and k not in CARD_KEYS and ok is False}


def denied_cards(ctx: AgencyContext, roles: dict[str, Any]) -> set[str]:
    if ctx.is_owner or not enforced(roles):
        return set()
    role = _granting_role(roles, ctx.employee_id)
    if role is None or role is _EVERY_PAGE:
        return set()
    return {k for k in CARD_KEYS if (role.get("permissions") or {}).get(k) is False}


def _stored_scope(
    ctx: AgencyContext, roles: dict[str, Any]
) -> Literal["all", "subordinates", "self"]:
    if ctx.is_owner or not enforced(roles):
        return "all"
    role = _granting_role(roles, ctx.employee_id)
    # a stored role with no scope reads as "self": never wider than stored
    scope = role.get("scope") if role is not None else None
    return scope if scope in ("all", "subordinates") else "self"


def data_scope(ctx: AgencyContext, roles: dict[str, Any]) -> Scope:
    return "all" if _stored_scope(ctx, roles) == "all" else "self"



_ME = "/api/of/v2/users/me"
_PICKER = (
    "/admin/vault-ai/cache", "/admin/vault-ai/image", "/admin/vault-ai/items",
    "/admin/vault-ai/poster", "/admin/vault-ai/search-of", "/admin/vault-ai/thumb",
    "/admin/vault/cache", "/admin/vault/fan-history", "/admin/vault/media-stats",
    "/admin/vault/wall-media", "/api/of/v2/vault/lists", "/api/of/v2/vault/media",
)
_MASS = (
    "/admin/fans", "/admin/funnels", "/admin/saved-replies", "/admin/smart-lists",
    "/admin/smart-lists/", "/api/of/v2/lists", "/api/of/v2/messages/queue",
    "/api/of/v2/subscribers",
    "/api/of/v2/messages/templates", "/api/of/v2/posts/tagged-friend-users", *_PICKER,
)
_STATS_REPORT = ("/admin/ingest/transactions",)
_BATCH_REASSIGN = "/admin/ingest/transactions/attribute"
_SUBS_CHART = "/api/of/v2/subscriptions/subscribers/chart"

COMPOSER_PAGE = "/messages-pro"

PAGE_MAP: dict[str, tuple[str, tuple[str, ...]]] = {
    "/": ("Dashboard", (
        "/admin/stats/revenue", "/admin/stats/per-model", "/admin/stats/per-employee", "/admin/stats/referrals",
        "/admin/shifts/clocked-in", "/api/of/v2/subscriptions/count", _SUBS_CHART, _ME)),
    "/of-manager/home": ("Home", (
        _ME, "/api/of/v2/posts", "/api/of/v2/stories", "/api/of/v2/users/search", "/api/of/v2/posts/likes",
        "/api/of/v2/streams/feed", "/api/of/v2/lists")),
    "/of-manager/streaming": ("Go live", (
        _ME, "/api/of/v2/streams", "/api/of/live-window", "/api/of/v2/users/search", "/api/of/v2/posts/search")),
    "/of-manager/new-post": ("New post", (
        _ME, "/api/of/v2/posts", "/api/of/v2/posts/tagged-friend-users", "/api/of/v2/upload",
        "/api/of/v2/stories", "/api/of/v2/vault/lists", "/api/of/v2/vault/media",
        "/api/of/v2/labels", "/api/of/v2/labels/sort", "/api/of/v2/guests", "/api/of/v2/release-forms",
        "/api/of/v2/users/search", "/api/of/v2/posts/search", "/api/of/v2/promotions",
        "/api/of/v2/trials", "/api/of/v2/subscriptions/bundles", "/api/of/v2/users/performers-search",
        f"{_ME}/settings", "/api/of/v2/queue/posts/")),
    "/of-manager/notifications": ("Notifications", (
        _ME, "/api/of/v2/release-forms/mentions", "/api/of/v2/users/search", "/api/of/v2/posts/search")),
    "/of-manager/messages": ("Messages Basic", (
        _ME, "/api/of/v2/chats", "/api/of/v2/messages", "/api/of/v2/messages/queue",
        "/api/of/v2/subscriptions/", "/api/of/v2/lists", "/api/of/v2/users/", "/api/of/v2/users/list",
        "/api/of/v2/upload", "/api/of/v2/vault/lists", "/api/of/v2/vault/media",
        "/api/of/v2/posts/tagged-friend-users", "/api/of/v2/release-forms", "/api/of/v2/guests")),
    "/of-manager/vault": ("Vault", (
        _ME, "/api/of/v2/vault", "/api/of/v2/vault/lists", "/api/of/v2/vault/media")),
    "/of-manager/queue": ("Queue", (
        _ME, "/api/of/v2/schedules", "/api/of/v2/schedules/later", "/api/of/v2/messages/queue",
        "/api/of/v2/queue/posts/")),
    "/of-manager/collections": ("Collections", (
        _ME, "/api/of/v2/lists", "/api/of/v2/labels", "/api/of/v2/subscribers", "/api/of/v2/users/")),
    "/of-manager/collections/bookmarks/all": ("Bookmarks", (_ME, "/api/of/v2/posts/bookmarks")),
    "/of-manager/statements": ("Statements", (
        _ME, "/api/of/v2/payouts", "/api/of/v2/payouts/transactions", "/api/of/v2/payments",
        "/api/of/v2/payouts/chargebacks", f"{_ME}/start-date-model", "/api/of/v2/payouts/stats")),
    "/of-manager/statistics": ("Statistics", (
        _ME, "/api/of/v2/earnings", "/api/of/v2/payouts/stats", "/api/of/v2/payouts/chargebacks",
        "/api/of/v2/posts/chart", "/api/of/v2/posts/top", f"{_ME}/stats", f"{_ME}/profile",
        f"{_ME}/start-date-model", f"{_ME}/referrals", f"{_ME}/stats/top", f"{_ME}/stats/today-activity",
        f"{_ME}/stats/messages/direct", "/api/of/v2/streaks",
        "/api/of/v2/messages/queue/chart", "/api/of/v2/messages/queue/buyers",
        "/api/of/v2/subscriptions/subscribers/latest", "/api/of/v2/subscriptions/subscribers/top",
        _SUBS_CHART, "/api/of/v2/fans-activity", "/api/of/v2/streams/top", "/api/of/v2/stories/top",
        "/api/of/v2/promotions/stats", "/api/of/v2/trials/stats", "/api/of/v2/campaigns/stats",
        "/api/of/v2/payouts/transactions", "/api/of/v2/payouts/chart", "/api/of/v2/payouts/referrals",
        "/api/of/v2/payouts/download-approved-invoice", "/api/of/v2/promotions/chart",
        "/api/of/v2/trials/chart", "/api/of/v2/campaigns/chart", "/api/of/v2/stories/chart",
        "/api/of/v2/streams/chart", "/api/of/v2/streams/viewers", "/api/of/v2/stories/viewers",
        "/api/of/v2/posts/stats", "/api/of/v2/posts/buyers", "/api/of/v2/posts/tips", "/api/of/v2/posts/likes",
        "/api/of/v2/promotions/claims", "/api/of/v2/trials/claims", "/api/of/v2/campaigns/claimers")),
    "/of-manager/bank": ("Bank", (_ME, "/api/of/v2/payouts/balances", "/api/of/v2/payouts/check-receive")),
    "/of-manager/profile": ("My profile", (
        _ME, "/api/of/v2/users/", "/api/of/v2/posts", "/api/of/v2/labels", "/api/of/v2/posts/likes",
        "/api/of/v2/stories/highlights")),
    "/of-manager/release-forms": ("Release forms", (
        _ME, "/api/of/v2/posts/tagged-friend-users", "/api/of/v2/release-forms")),
    "/of-manager/settings": ("OF settings", (
        _ME, "/api/of/v2/users/settings", f"{_ME}/settings", f"{_ME}/reply-on-subscribe",
        "/api/of/v2/campaigns", "/api/of/v2/subscriptions/bundles", "/api/of/v2/promotions",
        "/api/of/v2/trials", "/api/of/v2/users/performers-search",
        "/api/of/v2/sessions",
        "/api/of/v2/countries",
        f"{_ME}/profile-image",
        "/api/of/v2/users/social/buttons",
        "/api/of/v2/init",
        "/api/of/v2/users/links",
        "/api/of/v2/streams/users",
        "/api/of/v2/streams/obs")),
    "/analytics/creator-reports": ("Creator reports", (
        *_STATS_REPORT, "/admin/stats/revenue", "/admin/stats/per-model", "/admin/stats/referrals", "/admin/stats/xlsx",
        "/admin/reports",
        "/api/of/v2/subscriptions/count",
        "/api/of/v2/subscriptions/subscribers", _SUBS_CHART, _ME)),
    "/analytics/employee-reports": ("Employee reports", (
        *_STATS_REPORT, "/admin/stats/per-employee", "/admin/stats/chatting-stats", "/admin/stats/xlsx", "/admin/reports",
        "/admin/stats/attribution-coverage", "/admin/stats/automation-runs",
        "/admin/stats/per-automation")),
    "/analytics/fan-reports": ("Fan reports", (
        *_STATS_REPORT, "/admin/stats/per-fan-data", "/admin/stats/fan-report", "/admin/reports")),
    "/analytics/message-dashboard": ("Message dashboard", (
        "/admin/customs", "/admin/tips-list", "/admin/top-tippers", "/admin/paid-messages",
        "/admin/messages", "/admin/fans", "/admin/saved-replies", *_PICKER, "/api/of/v2/posts",
        "/api/of/v2/posts/top", "/api/of/v2/posts/tagged-friend-users",
        "/api/of/v2/messages/templates", _ME)),
    "/analytics/sales-records": ("Sales records", ("/admin/stats/sales-records", _BATCH_REASSIGN)),
    # saved-replies/sent: the Composer counts a send that rode a script (Scripts' orange send box).
    COMPOSER_PAGE: ("Messages Pro", (
        *_MASS, "/admin/account-config", "/admin/saved-replies/sent",
        "/admin/chats", "/admin/copilot", "/admin/do-not-mass", "/admin/messages",
        "/admin/paid-messages", "/admin/split-inbox", "/admin/translate", "/admin/vault/sends",
        "/api/of/v2/automation-restrict", "/api/of/v2/chats", "/api/of/v2/messages",
        "/api/of/v2/payouts/transactions", "/api/of/v2/scheduled-sends", "/api/of/v2/schedules",
        "/api/of/v2/subscriptions/", "/api/of/v2/users/",
        "/api/of/v2/users/list", _ME, f"{_ME}/settings")),
    "/growth/smart-messages": ("Smart Messages", (
        *_MASS, "/admin/automation-rules", "/admin/mass-messages", "/admin/nudge-config",
        "/admin/purchase-followup-config", "/admin/lifecycle-message-config", "/admin/priority-mass",
        "/api/of/v2/messages/templates", "/api/of/v2/schedules", f"{_ME}/stats", f"{_ME}/reply-on-subscribe",
        f"{_ME}/settings")),
    "/growth/smart-lists": ("Smart lists", (
        "/admin/smart-lists", "/admin/smart-lists/", "/admin/smart-lists/preview")),
    "/growth/auto-follow": ("Auto-follow", ("/admin/auto-follow", "/admin/automation-rules", "/admin/smart-lists")),
    "/growth/vault-pro": ("Vault Pro", (
        *_PICKER, "/admin/vault-ai", "/admin/vault", "/api/of/v2/vault")),
    "/growth/scripts": ("Scripts", (
        "/admin/saved-replies", "/admin/saved-replies/", *_PICKER, "/api/of/v2/messages/templates",
        "/api/of/v2/posts/tagged-friend-users", f"{_ME}/reply-on-subscribe", f"{_ME}/settings")),
    "/growth/profile-promotion": ("Profile promotion", (
        "/admin/promotions", "/admin/automation-rules", "/admin/link-metrics", "/admin/promo-list",
        "/api/of/v2/lists")),
    "/growth/free-trial-links": ("Free trial links", (
        "/admin/trial-links", "/admin/link-metrics", "/admin/link-meta", "/api/of/v2/lists")),
    "/growth/tracking-links": ("Tracking links", (
        "/admin/tracking-links", "/admin/of-tracking-links", "/admin/link-meta", "/api/of/v2/lists")),
    "/growth/sensitive-words": ("Sensitive words", ()),
    "/share-for-share/discover-creators": ("Discover creators", (
        "/admin/s4s/discover", "/admin/s4s/profiles", "/admin/s4s/requests", "/admin/s4s/blocks", "/admin/s4s/media")),
    "/share-for-share/requests": ("Requests", (
        "/admin/s4s/profiles", "/admin/s4s/requests", "/admin/s4s/requests/", "/admin/s4s/media")),
    "/share-for-share/schedule": ("S4S schedule", (
        "/admin/s4s/profiles", "/admin/s4s/requests", "/admin/s4s/schedule", "/admin/s4s/slots",
        "/admin/s4s/media")),
    "/share-for-share/settings": ("S4S settings", ("/admin/s4s/profiles", "/admin/s4s/requests", "/admin/s4s/media")),
    "/growth/auto-post": ("Auto Post", (
        *_PICKER, "/admin/account-config",
        "/admin/automation", "/admin/automation-kinds",
        "/admin/automation-rules", "/admin/autoreply-config",
        "/admin/fans", "/admin/funnels",
        "/admin/nudge-config",
        "/admin/saved-replies",
        "/admin/stats/automation-runs", "/admin/style-config",
        "/api/of/v2/lists",
        "/api/of/v2/messages/queue", "/api/of/v2/messages/templates",
        "/api/of/v2/posts/tagged-friend-users", _ME)),
    "/growth/auto-story": ("Auto Story", ("/admin/automation-rules", *_PICKER)),
    "/growth/auto-mass": ("Auto Mass", (
        "/admin/automation-rules", "/admin/stats/automation-runs", "/api/of/v2/lists", *_PICKER)),
    "/growth/auto-reply": ("Auto-reply", (
        "/admin/autoreply-config", "/admin/style-config", "/api/of/v2/lists", "/admin/account-config")),
    "/growth/auto-funnel": ("Auto Funnel", (
        "/admin/funnels", "/admin/automation-rules", "/api/of/v2/lists",
        "/api/of/v2/messages/queue", "/admin/unconfirmed-sends", *_PICKER)),
    "/growth/get-to-know-fans": ("Get to know fans", ("/admin/account-config",)),
    # The gen_info switch (its rule) and the one-shot old-fans enqueue (process_old_fans).
    "/growth/gen-info": ("Gen-Info", ("/admin/automation", "/admin/automation-rules")),
    # Today's Shadow Decision rows (full_ai_api) and the full_ai_chat switch on the shared rule routes.
    # That kind's writes stay owner-only (OPT_IN_KINDS: this page is not in OPT_IN_PAGES), but like
    # Gen-Info's, a role ticking this page opens the rule routes, so other kinds' rule writes too.
    "/full-ai-chatter": ("Full AI Chat", ("/admin/full-ai", "/admin/automation-rules")),
    "/ai-rules": ("AI rules", ("/admin/full-ai/rules",)),
    "/creators": ("Manage creators", (
        "/admin/accounts/active", "/admin/automation", "/admin/reload-session")),
    "/creators/proxy": ("Custom proxy", ()),
    "/creators/leaks": ("Leak tracker", ()),
    "/employees": ("Manage employees", ("/api/of/v2/vault/lists",)),
    "/employees/shifts": ("Shift schedule", ("/admin/shifts", _BATCH_REASSIGN)),
}

UNMAPPED: dict[str, str] = {
    "/": "the Relay's root answer, no Creator data",
    "/auth": "sign-in (owners and employees), the owner session, 2FA and log out other sessions",
    "/chatter": "chatter sign-in, session, its Creators and folder access",
    "/t": "public tracking-link redirect",
    "/share": "a share link's public report, read by its secret",
    "/.well-known/": "MCP sign-in discovery (public JSON, names no account)",
    "/health": "health check", "/livez": "liveness check",
    "/docs": "API docs", "/openapi.json": "API schema", "/redoc": "API docs",
    "/events": "the shell's live event stream",
    "/push": "the session's own Web Push subscriptions (OS notifications), no Creator data",
    "/img": "media proxy behind every page's images",
    "/lanes-panel": "operator lanes panel, no nav page",
    "/admin/accounts": "the shell's Creator switcher (ScopeSwitcher) and its recolor, the one write"
                       " a chatter may make here (chatters.py); the rest is owner-only",
    "/admin/view-lease": "every open tab's View lease renewal (accounts_admin_api): ids outside the"
                         " session's Creators are dropped; answers only the kept ids",
    "/admin/of-consent": "a Creator's Auto-accept OnlyFans consent switch (of_consent_api): the route checks"
                         " the Creator is the session's; its PUT is owner-only there",
    "/admin/screens": "a screen's reads in one call (screens_api): each inner read is checked as its own route",
    "/admin/leaks": "the Leak tracker (leak_tracker_api): every route runs leak_tracker.require_gates,"
                    " whose role gate is leak_page_granted and answers 404",
    "/admin/settings": "Settings blobs (owner-only) and the Applied settings read every session needs",
    "/admin/shifts/me": "the top bar's clock", "/admin/shifts/clock-in": "the top bar's clock",
    "/admin/shifts/clock-out": "the top bar's clock",
    "/admin/shifts/clock-status": "the top bar's clock", "/admin/shifts/clock-heartbeat": "the top bar's clock",
    "/admin/assistant": "the shell's assistant widget",
    "/admin/support": "the help widget's Support tab (support_api): the session's own thread, no Creator data",
    "/support": "the central support hub (support_hub): its own owner password and instance token, no Creator data",
    "/admin/mcp": "the hosted MCP endpoint (mcp_api): owner token or no credential, never a session;"
                  " each tool's inner read is checked as its own route",
    "/admin/ai-key-status": "the AI-key notice on every automation page (key presence only)",
    "/admin/errors": "client error reports from every page",
    "/admin/perflog": "client timing reports from every page",
    "/api/of/v2/users/notifications": "the top bar's notification bell (its reads and its mark-read, which every"
                                      " bell viewer sends as OF web does on open) and the Money rail (its /money read)",
    "/api/of/v2/giphy": "GIF search for every composer, no Creator data",
    "/api/of/ofm-writes": "the OF Manager's new-writes switch probe (server._ofm_new_writes_on), no Creator data",
    "/admin/ofm-writes": "a Creator's OF Manager new-writes force-off (ofm_writes_api, Settings › OF Manager writes):"
                         " the route checks the Creator is the session's; its PUT is owner-only there",
    "/admin/sensitive-words": "the Agency's Sensitive words list every composer warns on;"
                              " its writes are owner-only (chatters.py)",
    "/admin/_debug": "diagnostics, no nav page", "/admin/coalesce": "diagnostics, no nav page",
    "/admin/events": "diagnostics, no nav page", "/admin/img-cache": "diagnostics, no nav page",
    "/admin/priority-lanes": "diagnostics, no nav page",
    "/admin/storyboard": "diagnostics, no nav page",
    "/admin/stats/grok-calls": "diagnostics, no nav page",
    "/admin/stats/grok-cost": "diagnostics, no nav page",
    "/admin/mass-exclude": "no nav page calls it",
    "/admin/streams": "no nav page calls it",
}


def _matches(prefix: str, path: str) -> bool:
    if prefix == "/":
        return path == "/"
    if prefix.endswith("/"):
        return path.startswith(prefix) and len(path) > len(prefix)
    return path == prefix or path.startswith(prefix + "/")


UNCONFIRMED_SENDS = "/admin/unconfirmed-sends"
RESOLVE_SEND = f"{UNCONFIRMED_SENDS}/resolve"
_CELL_PAGE_GRANTS = {
    COMPOSER_PAGE: ((UNCONFIRMED_SENDS, "GET"), (RESOLVE_SEND, "POST")),
    "/growth/auto-funnel": ((UNCONFIRMED_SENDS, "GET"),),
}


def _route_table() -> list[tuple[str, str | None, tuple[str, ...]]]:
    pages: dict[tuple[str, str | None], list[str]] = {}
    for href, (_, prefixes) in PAGE_MAP.items():
        for prefix in prefixes:
            pages.setdefault((prefix, None), []).append(href)
        for route in _CELL_PAGE_GRANTS.get(href, ()):
            pages.setdefault(route, []).append(href)
    rows = [(p, method, tuple(dict.fromkeys(h))) for (p, method), h in pages.items()]
    rows += [(p, None, ()) for p in UNMAPPED]
    return sorted(rows, key=lambda row: (len(row[0]), row[1] is not None), reverse=True)


_ROUTES = _route_table()


READ_ONLY_GRANTS: dict[str, frozenset[str]] = {
    "/of-manager/home": frozenset({"/api/of/v2/lists"}),
    "/growth/tracking-links": frozenset({"/api/of/v2/lists"}),
}


def _writers(prefix: str, pages: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(h for h in pages if prefix not in READ_ONLY_GRANTS.get(h, ()))


# a read-only grant must leave a writer page for the prefix: () would let every write through
for _prefix, _, _pages in _ROUTES:
    assert not _pages or _writers(_prefix, _pages), f"{_prefix}: every page granting it is read-only (READ_ONLY_GRANTS)"

_OF_SETTINGS = "/of-manager/settings"
_READS = frozenset({"GET", "HEAD", "OPTIONS"})


def _account_write(path: str, method: str) -> bool:
    return method.upper() not in _READS and (path == _ME or _matches(f"{_ME}/settings", path))


def route_pages(path: str, method: str) -> tuple[str, ...] | None:
    method = method.upper()
    if _account_write(path, method):
        return (_OF_SETTINGS,)
    for prefix, cell_method, pages in _ROUTES:
        if cell_method is None:
            matches = _matches(prefix, path)
        else:
            matches = path == prefix and method == cell_method and cells()
        if matches:
            if method in _READS:
                return pages
            return _writers(prefix, pages)  # a write drops the read-only grants
    return None




def _card_route_open(path: str, denied: set[str]) -> bool:
    keys = [f"/#card-{c}" for c, (_, routes, _) in DASHBOARD_CARDS.items() if any(_matches(r, path) for r in routes)]
    return not keys or any(k not in denied for k in keys)


# fails closed: refused when ANY page key of the action is stored false; ?format=csv matches the exact lower-case value (others 422)
ACTIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "unsend": ("Unsend messages", ("DELETE /api/of/v2/messages/*",)),
    "delete-chat": ("Delete chats", ("DELETE /api/of/v2/chats/*",)),
    "mass-message": ("Send or unsend mass messages", (
        "POST /api/of/v2/messages/queue",
        "POST /api/of/v2/messages/queue/later", "PUT /api/of/v2/messages/queue/*",
        "DELETE /api/of/v2/messages/queue/*", "PUT /api/of/v2/schedules/*/publish",
        "POST /admin/priority-mass/runs", "POST /admin/priority-mass/runs/*/resume")),
    "block-fan": ("Block or restrict fans", (
        "POST /api/of/v2/users/*/block", "DELETE /api/of/v2/users/*/block",
        "POST /api/of/v2/users/*/restrict", "DELETE /api/of/v2/users/*/restrict",
        "POST /api/of/v2/streams/users/*/block", "DELETE /api/of/v2/streams/users/*/block")),
    "discount": ("Give subscription discounts", ("PUT /api/of/v2/subscriptions/*/discount",)),
    "export": ("Export CSV", (
        "GET /admin/paid-messages?format=csv", "GET /admin/stats/sales-records?format=csv",
        "GET /admin/stats/fan-report?format=csv", "GET /admin/tips-list?format=csv",
        "GET /admin/top-tippers?format=csv", "POST /admin/stats/xlsx", "POST /admin/reports/run")),
    "withdraw": ("Request withdrawals", (
        "POST /api/of/v2/payouts/requests", "PATCH /api/of/v2/payouts/requests")),
    "delete-post": ("Delete posts", ("DELETE /api/of/v2/posts/*",)),
    "delete-folder": ("Delete vault folders", (
        "DELETE /admin/vault-ai/of-folders/*", "DELETE /admin/vault-ai/internal-folders/*")),
    "delete-script": ("Delete scripts", ("DELETE /admin/saved-replies/*", "POST /admin/saved-replies/delete")),
    "edit-shifts": ("Create, edit or cancel shifts", (
        "POST /admin/shifts", "PATCH /admin/shifts/*", "POST /admin/shifts/*/cancel")),
    "edit-clock": ("Edit or delete clock records", (
        "PATCH /admin/shifts/clock-events/*", "DELETE /admin/shifts/clock-events/*")),
    "reassign-sales": ("Reassign sales", (
        f"POST {_BATCH_REASSIGN}", "POST /admin/ingest/transactions/*/attribute")),
    "delete-link": ("Delete links and promotions", (
        "DELETE /admin/tracking-links/*", "DELETE /admin/of-tracking-links/*", "DELETE /admin/trial-links/*",
        "DELETE /api/of/v2/campaigns/*", "DELETE /api/of/v2/trials/*",
        "DELETE /admin/promotions/*", "DELETE /api/of/v2/promotions/*", "POST /api/of/v2/promotions/*/finish")),
    "account-lockout": ("Block countries or IPs, close sessions, reset the stream key", (
        "DELETE /api/of/v2/sessions",
        "PUT /api/of/v2/users/me/settings/security/blocked-countries",
        "PUT /api/of/v2/users/me/settings/security/blocked-ips",
        "DELETE /api/of/v2/streams/obs/key",
    )),
}


def _pattern(pattern: str) -> tuple[str, list[str], tuple[str, str] | None]:
    method, target = pattern.split(" ", 1)
    path, _, query = target.partition("?")
    key, _, value = query.partition("=")
    return method, path.split("/"), ((key, value) if query else None)


_ACTION_PATTERNS = [(action, _pattern(p)) for action, (_, ps) in ACTIONS.items() for p in ps]


def route_action(method: str, path: str, query: Mapping[str, str] | None = None) -> str | None:
    segments = path.split("/")
    for action, (m, parts, q) in _ACTION_PATTERNS:
        if m != method.upper() or len(parts) != len(segments):
            continue
        if any(p != "*" and p != seg for p, seg in zip(parts, segments)):
            continue
        if q is not None and (query is None or query.get(q[0]) != q[1]):
            continue
        return action
    return None


def _action_pages(action: str) -> tuple[str, ...]:
    pages: set[str] = set()
    for a, (method, parts, _) in _ACTION_PATTERNS:
        if a == action:
            pages.update(route_pages("/".join("1" if p == "*" else p for p in parts), method) or ())
    return tuple(h for h in PAGE_MAP if h in pages)


ACTION_KEYS: dict[str, str] = {
    f"{page}#{action}": ACTIONS[action][0]
    for page in PAGE_MAP for action in ACTIONS if page in _action_pages(action)
}


def require_permission(
    ctx: AgencyContext, roles: dict[str, Any], pages: tuple[str, ...], path: str, action: str | None = None,
) -> None:
    granted = granted_pages(ctx, roles)
    if granted is None or not pages:
        return
    hidden = denied_cards(ctx, roles) if "/" in pages else set()
    open_pages = [p for p in pages if p in granted and (p != "/" or _card_route_open(path, hidden))]
    if not open_pages:
        raise HTTPException(status_code=403, detail=f"Your role does not allow {PAGE_MAP[pages[0]][0]}")
    if action is not None:
        _refuse_denied_action(ctx, roles, action)


def _refuse_denied_action(ctx: AgencyContext, roles: dict[str, Any], action: str) -> None:
    if any(key.endswith(f"#{action}") for key in denied_actions(ctx, roles)):
        raise HTTPException(status_code=403, detail=f"Your role does not allow {ACTIONS[action][0]}")


def narrowest_scope(scopes: Iterable[str]) -> str:
    return "all" if all(scope == "all" for scope in scopes) else "self"


def agency_chatter():
    chatter = get_request_chatter()
    if get_request_user() is not None or chatter is None or not chatter.owner_user_ids:
        return None
    return chatter


async def _enforcing_roles(*, db_session=None) -> dict[str, dict[str, Any]] | None:
    """The applied `roles` blob of each Agency the session's chatter is
    linked to, or None when the session is not a chatter some linked Agency
    enforces roles on (`agency_chatter` is None, or every linked Agency's
    switch off)."""
    chatter = agency_chatter()
    if chatter is None:
        return None
    from settings_api import applied_blob  # settings_api imports this module
    if db_session is None:
        async with get_session() as s:
            roles = {a: await applied_blob(s, a, "roles") for a in sorted(chatter.owner_user_ids)}
    else:
        roles = {a: await applied_blob(db_session, a, "roles") for a in sorted(chatter.owner_user_ids)}
    return roles if any(enforced(blob) for blob in roles.values()) else None


async def opt_in_refusal(pages: tuple[str, ...], account_id: str | None) -> str | None:
    chatter = agency_chatter()
    if chatter is None:
        return None
    from settings_api import applied_blob  # settings_api imports this module
    async with get_session() as s:
        roles = {a: await applied_blob(s, a, "roles") for a in sorted(chatter.owner_user_ids)}
    for ctx in await agency_contexts(account_id=account_id):
        if opt_in_granted(ctx, roles[ctx.agency_user_id]).intersection(pages):
            return None
    return denied_detail(pages)


async def require_opt_in_page(page: str, account_id: str | None = None) -> None:
    if (detail := await opt_in_refusal((page,), account_id)) is not None:
        raise HTTPException(status_code=403, detail=detail)


async def require_action(action: str, account_id: str | None = None) -> None:
    if (roles := await _enforcing_roles()) is None:
        return
    for ctx in await agency_contexts(account_id=account_id):
        _refuse_denied_action(ctx, roles[ctx.agency_user_id], action)


async def require_opt_in_kind(kind: str, account_id: str | None) -> None:
    if (page := OPT_IN_KINDS.get(kind)) is not None:
        await require_opt_in_page(page, account_id)


async def scoped_employee_ids() -> set[int] | None:
    if (roles := await _enforcing_roles()) is None:
        return None
    # per_employee takes no Creator filter: every linked Agency is checked, the narrowest scope wins
    contexts = await agency_contexts()
    scopes = [_stored_scope(ctx, roles[ctx.agency_user_id]) for ctx in contexts]
    if narrowest_scope(scopes) == "all":
        return None
    own: set[int] = set()
    for ctx, scope in zip(contexts, scopes):
        if ctx.employee_id is None:
            continue
        if scope == "subordinates":
            own |= await subtree_employee_ids(ctx.agency_user_id, ctx.employee_id)
        else:
            own.add(ctx.employee_id)
    return own


async def role_holders(role_id: str) -> set[int]:
    from settings_api import applied_blob  # settings_api imports this module
    out: set[int] = set()
    async with get_session() as s:
        for ctx in await agency_contexts():
            roles = await applied_blob(s, ctx.agency_user_id, "roles")
            out |= {int(eid) for eid in (roles.get("assignments") or {})
                    if str(eid).isdigit() and (_role(roles, int(eid)) or {}).get("id") == role_id}
    return out


async def route_refusal(
    pages: tuple[str, ...], method: str, path: str, account_ids: list[str | None],
    query: Mapping[str, str] | None = None,
) -> tuple[HTTPException | None, list[AgencyContext]]:
    if not pages:
        return None, []
    # served only by My Automations pages: opt-in, whatever the switch
    if set(pages) <= OPT_IN_PAGES:
        try:
            for one in account_ids:
                if (detail := await opt_in_refusal(pages, one)) is not None:
                    return HTTPException(status_code=403, detail=detail), []
        except HTTPException as exc:
            return exc, []
        return None, []
    try:
        if agency_chatter() is None:
            return None, []
        async with get_session() as s:
            # one fresh checkout for this request; released before the route runs
            roles = await _enforcing_roles(db_session=s)
            contexts = []
            if roles is not None:
                for one in account_ids:
                    contexts.extend(await agency_contexts(account_id=one, db_session=s))
    except HTTPException as exc:
        return exc, []
    if roles is None:
        return None, []
    try:
        action = route_action(method, path, query)
        for ctx in contexts:
            # a missing blob key raises (500) rather than allow
            require_permission(ctx, roles[ctx.agency_user_id], pages, path, action)
    except HTTPException as exc:
        return exc, contexts
    return None, contexts


async def role_enforcement_middleware(request, call_next):
    pages = route_pages(request.url.path, request.method)
    if not pages:
        return await call_next(request)
    # every named Creator is checked (union): naming one cannot hide another
    ids = split_account_ids(request.headers.get("x-account-id"),
                            *request.query_params.getlist("account_id")) or [None]
    refusal, contexts = await route_refusal(pages, request.method, request.url.path, ids,
                                            request.query_params)
    if refusal is not None:
        return JSONResponse({"detail": refusal.detail}, status_code=refusal.status_code)
    chatter = agency_chatter()
    if (chatter is not None and len(chatter.owner_user_ids) == 1
            and len(ids) == len(contexts) == 1 and ids[0]
            and contexts[0].employee_id is not None):
        remember_chatter_employee(request, chatter, ids[0], contexts[0].employee_id)
    return await call_next(request)
