"""service/permissions.py — what a Permission role grants one Employee.

Pure functions of an Agency's applied `roles` blob (`settings_api.applied_blob`,
docs/spec/phase-04-apply-stored-settings.md › Role enforcement):

  enforced(roles)             the per-Agency "Enforce role permissions" switch
  granted_pages(ctx, roles)   the granted page hrefs, or None for every page
  denied_actions(ctx, roles)  the `<page>#<action>` Function permissions it denies
  denied_cards(ctx, roles)    the Dashboard cards (`CARD_KEYS`) it hides
  OPT_IN_PAGES                My Automations: a chatter's only by explicit grant
  opt_in_granted(ctx, roles)  the OPT_IN_PAGES one Agency context may use
  require_opt_in_page(page)   403 unless some Agency context grants that page
                              (the rule-kind and funnel writes call it)
  data_scope(ctx, roles)      "all" or "self"
  narrowest_scope(scopes)     one Data scope across several Agency contexts
  scoped_employee_ids()       the Employee rows an employee-keyed report may show
                              ("Self and subordinates" reads the group tree)
  role_holders(role_id)       the Employees assigned one role, every linked Agency

and Role enforcement on the Relay:

  PAGE_MAP, UNMAPPED          each Permission-editor page's Relay prefixes; the rest
  route_pages(path, method)   the pages one route serves
  DASHBOARD_CARDS, CARD_KEYS  the Dashboard's cards a role can hide and the routes each reads
  ACTIONS, route_action(...)  the Function permissions and the one a request is
  require_permission(...)     403 "Your role does not allow <page label>"
  role_enforcement_middleware runs it for chatter sessions on mapped routes

`ctx` is the request's AgencyContext (`employees.agency_context`) and `roles`
that Agency's applied `roles` blob.

Enforcement is on unless the Agency stored `enforce: false` (a never-stored or
invalid switch reads on; `settings_api.migrate_role_enforcement_once` gave the
logins of Agencies that predate this default the built-in Admin). With it off
every page is granted with "all" data. With it on, the
Employee's assignment names its role: a stored role grants exactly the pages its
`permissions` mark true (a missing page is denied), and the built-in `owner` and
`admin` ids, when the blob stores no role of that id, grant every page with
"all" data, as the Role Settings Panel's built-ins do. No assignment, or one
naming a role the blob does not hold, grants nothing; so does a stored role
marked `disabled: true` (its Employees keep it, so re-enabling restores them).
Owner sessions and the Master are never checked: every page, "all" data,
whatever the blob says.

ASSUMPTION: a stored role with no `scope` reads as "self". Rung 4: never
wider than stored; the Panel creates custom roles with scope "self".
Overturned if the owner wants a missing scope to mean "all".

ASSUMPTION: `data_scope` (and so the Applied settings' `scope`) still reads
"subordinates" as "self"; only `scoped_employee_ids` widens it, to
`employee_groups_api.subtree_employee_ids` (docs/spec/phase-05, Data scope).
Rung 4: the Applied settings contract ("all" | "self") is unchanged and no
page reads the scope to widen anything. Overturned if a page must tell
"subordinates" apart.

ASSUMPTION: the spec's `granted_pages(ctx)` and `data_scope(ctx)` also take
the applied `roles` blob, so they stay pure reads and one blob read serves
every caller in a request. Rung 5: only the middleware below opens a database
session (the blob reads and Phase 1's Agency context, which may create a
Mirror Employee). Overturned if a caller needs them to read the blob themselves.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from auth import get_request_user, split_account_ids
from chatters import get_request_chatter
from db.engine import get_session
from employee_groups_api import subtree_employee_ids
from employees import AgencyContext, agency_contexts
from settings_schema import (  # noqa: F401 (REVENUE_CARD_KEYS: this module's API too)
    BUILT_IN_ROLE_DEFAULTS, BUILT_IN_ROLE_IDS, CARD_KEYS, DASHBOARD_CARDS, REVENUE_CARD_KEYS,
)

Scope = Literal["all", "self"]

# A built-in role the blob does not store: every page, all data.
_EVERY_PAGE: dict[str, Any] = {"scope": "all"}


def enforced(roles: dict[str, Any]) -> bool:
    return roles.get("enforce") is not False


def _role(roles: dict[str, Any], employee_id: int | None) -> dict[str, Any] | None:
    """The Employee's assigned role, `_EVERY_PAGE` for an unstored Owner or
    Admin, an unstored Team Leader, Chatter or Creator as its defaults
    (settings_schema.BUILT_IN_ROLE_DEFAULTS), or None when unassigned or
    assigned to a role the blob does not hold."""
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
    """`_role`, but None for a stored role marked `disabled`: a disabled role
    grants nothing. `_role` alone still reads it as held, so
    `settings_api.give_role_to_unroled` never reassigns its Employees. A
    built-in role is always on, `disabled` stored or not (Role Settings'
    Status switch is locked for it)."""
    role = _role(roles, employee_id)
    off = role is not None and role.get("disabled") is True and role.get("id") not in BUILT_IN_ROLE_IDS
    return None if off else role


# My Automations (ours, not Infloww; app/lib/nav.ts `chatterOptIn`). Off for a
# chatter by default: such a page is granted only by a stored role that ticks
# it, on an Agency enforcing role permissions. The built-in Owner and Admin,
# unstored, grant none of them (the Role Settings Panel shows them unticked);
# with enforcement off a chatter is refused them, where every other page opens.
# Where any one of the chatter's Agency contexts grants the page, it may use it.
# Owner sessions are never checked. Enforced on the routes only these pages
# serve (role_enforcement_middleware) and, for the shared rule and funnel
# routes, on the writes of these pages' own rule kinds and funnels
# (`require_opt_in_page`). service/tests/test_role_enforcement.py pins this set
# to the nav's My Automations group.
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
}


def opt_in_granted(ctx: AgencyContext, roles: dict[str, Any]) -> set[str]:
    """The OPT_IN_PAGES this Agency context may use: every one for an owner,
    else those a stored role ticks while the Agency enforces role permissions."""
    if ctx.is_owner:
        return set(OPT_IN_PAGES)
    if not enforced(roles):
        return set()
    role = _granting_role(roles, ctx.employee_id)
    if role is None or role is _EVERY_PAGE:
        return set()
    return {h for h in OPT_IN_PAGES if (role.get("permissions") or {}).get(h) is True}


def denied_detail(pages: Iterable[str]) -> str:
    """The 403 detail naming every page in `pages` ("Auto Post or Auto-reply")."""
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


def denied_actions(ctx: AgencyContext, roles: dict[str, Any]) -> set[str]:
    """The `<page>#<action>` keys (`ACTION_KEYS`) the context's role stores
    false. A key not stored falls back to its page's grant, so a role saved
    before Function permissions keeps every action of the pages it grants."""
    if ctx.is_owner or not enforced(roles):
        return set()
    role = _granting_role(roles, ctx.employee_id)
    if role is None or role is _EVERY_PAGE:
        return set()
    return {k for k, ok in (role.get("permissions") or {}).items()
            if "#" in k and k not in CARD_KEYS and ok is False}


def denied_cards(ctx: AgencyContext, roles: dict[str, Any]) -> set[str]:
    """The Dashboard card keys (`CARD_KEYS`) the context's role stores false;
    the built-in Chatter, unstored, its revenue cards (`_role`). A key not
    stored falls back to the Dashboard's grant, as a Function permission's does."""
    if ctx.is_owner or not enforced(roles):
        return set()
    role = _granting_role(roles, ctx.employee_id)
    if role is None or role is _EVERY_PAGE:
        return set()
    return {k for k in CARD_KEYS if (role.get("permissions") or {}).get(k) is False}


def _stored_scope(
    ctx: AgencyContext, roles: dict[str, Any]
) -> Literal["all", "subordinates", "self"]:
    """The context's stored Data scope: "all" for owners and enforcement off,
    "self" for no role or a missing/unknown scope."""
    if ctx.is_owner or not enforced(roles):
        return "all"
    role = _granting_role(roles, ctx.employee_id)
    scope = role.get("scope") if role is not None else None
    return scope if scope in ("all", "subordinates") else "self"


def data_scope(ctx: AgencyContext, roles: dict[str, Any]) -> Scope:
    return "all" if _stored_scope(ctx, roles) == "all" else "self"


# ── Role enforcement: the page map ─────────────────────────────────────────
# Data only. Each Permission-editor page (`PERMISSION_PAGES` in
# app/lib/nav.ts: the non-legacy SIDEBAR links, which the editor's
# `PAGE_HREFS` reads) maps to its nav label and the Relay path prefixes it
# calls, read from its relay calls. Every other route is owner-only already
# (`chatters._CHATTER_BLOCKED_ADMIN_PREFIXES`) or in `UNMAPPED` with a reason;
# service/tests/test_role_enforcement.py fails on a route in none of these.
#
# How a path matches: the longest matching prefix across both tables decides.
# A prefix matches itself and every path under it; a prefix ending in "/"
# only paths strictly under it ("/admin/s4s/requests/" is one request,
# "/admin/s4s/requests" the list); "/" alone matches only the root.
#
# ASSUMPTION: a route the app never calls belongs, by its name, to the page
# whose Creator data it serves (OnlyFans earnings to Statistics, balances to
# Bank, labels to My profile, promotions, trials and bundles to OF settings),
# so it is refused with that page. Rung 4: refusing fails closed and one map
# line reopens it. Overturned if the owner wants uncalled routes unmapped.
#
# ASSUMPTION: the map is by path only, whatever the method, but for writes to
# users/me and users/me/settings* (`route_pages`: OF settings only) and the
# Function permissions below (`ACTIONS`, by method and path), and admin
# routes no nav page calls (legacy, Settings-only, diagnostics) are UNMAPPED.
# Rung 5: the spec's map is path prefixes. Overturned if another method or an
# uncalled admin route must be refused.

_ME = "/api/of/v2/users/me"
# The vault picker every composer opens.
_PICKER = (
    "/admin/vault-ai/cache", "/admin/vault-ai/image", "/admin/vault-ai/items",
    "/admin/vault-ai/poster", "/admin/vault-ai/search-of", "/admin/vault-ai/thumb",
    "/admin/vault/cache", "/admin/vault/fan-history", "/admin/vault/media-stats",
    "/admin/vault/wall-media", "/api/of/v2/vault/lists", "/api/of/v2/vault/media",
)
# The mass message composer (Messages Pro's Fan List and Smart Messages). Its
# Mass Online panel reads the online subscribers list for the live count, so
# Smart Messages gains `subscribers` through here (Messages Pro had it already).
_MASS = (
    "/admin/fans", "/admin/funnels", "/admin/saved-replies", "/admin/smart-lists",
    "/admin/smart-lists/", "/api/of/v2/lists", "/api/of/v2/messages/queue",
    "/api/of/v2/subscribers",
    "/api/of/v2/messages/templates", "/api/of/v2/posts/tagged-friend-users", *_PICKER,
)
_STATS_REPORT = ("/admin/ingest/transactions",)
# The batch reassign: Sales records' selection and Shift records' "Reassign sales".
_BATCH_REASSIGN = "/admin/ingest/transactions/attribute"
# OF's new-subscriber chart: the Dashboard's Per-model KPIs card (tied to it in DASHBOARD_CARDS, so hiding that
# card closes it on the Dashboard) and Statistics › Fans both read it.
_SUBS_CHART = "/api/of/v2/subscriptions/subscribers/chart"

PAGE_MAP: dict[str, tuple[str, tuple[str, ...]]] = {
    # Its Employee sales card reads the per-employee report (ticket 26); Employee reports keeps routes of its own.
    "/": ("Dashboard", (
        "/admin/stats/revenue", "/admin/stats/per-model", "/admin/stats/per-employee", "/admin/stats/referrals",
        "/admin/shifts/clocked-in", "/api/of/v2/subscriptions/count", _SUBS_CHART, _ME)),
    # posts/likes: an own post's "N Likes" (also My profile's). Its Post statistics (posts/stats: per-post earnings)
    # stays Statistics'. streams/feed: the story strip's live and scheduled streams (not Go live's `/streams`).
    "/of-manager/home": ("Home", (
        _ME, "/api/of/v2/posts", "/api/of/v2/stories", "/api/of/v2/users/search", "/api/of/v2/posts/likes",
        "/api/of/v2/streams/feed")),
    "/of-manager/streaming": ("Go live", (_ME, "/api/of/v2/streams")),
    # labels: ADD LABELS (its rows, + and Sort); guests and release-forms: the tag dialog's Invite new user,
    # Release form tab and a row's hide; users/search, posts/search: the right column's search; promotions, trials,
    # subscriptions/bundles, performers-search, settings: the promotion and free trial link dialogs its tiles open;
    # queue/posts/: the Queue's Edit post saving in place.
    "/of-manager/new-post": ("New post", (
        _ME, "/api/of/v2/posts", "/api/of/v2/posts/tagged-friend-users", "/api/of/v2/upload",
        "/api/of/v2/stories", "/api/of/v2/vault/lists", "/api/of/v2/vault/media",
        "/api/of/v2/labels", "/api/of/v2/labels/sort", "/api/of/v2/guests", "/api/of/v2/release-forms",
        "/api/of/v2/users/search", "/api/of/v2/posts/search", "/api/of/v2/promotions",
        "/api/of/v2/trials", "/api/of/v2/subscriptions/bundles", "/api/of/v2/users/performers-search",
        f"{_ME}/settings", "/api/of/v2/queue/posts/")),
    # Its feed is `users/notifications`, which the top bar's bell also reads (UNMAPPED).
    "/of-manager/notifications": ("Notifications", (_ME, "/api/of/v2/release-forms/mentions")),
    # Every route the Messages tab's controls call (ofMirrorChat*, ofMirrorMessageMenu, ofMirrorThread): the chat
    # list and thread, a chat's header tools (subscriptions/: rename, notes, discount; lists; users/: restrict, block,
    # users/list), a message's menu (messages/), New message (messages/queue), and the composer (upload, vault, tag
    # creators and release forms; GIF search is every composer's, UNMAPPED). Not /tips: the composer's Tip is
    # disabled (a card payment the mirror never sends), so the page grants no payment route.
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
    # labels: Post Labels' rows and +; subscribers: Fans; users/: Add users' @username lookups.
    "/of-manager/collections": ("Collections", (
        _ME, "/api/of/v2/lists", "/api/of/v2/labels", "/api/of/v2/subscribers", "/api/of/v2/users/")),
    # Collections' Bookmarks tab, its own menu in Infloww (id 6), and the one page reading the bookmarks.
    "/of-manager/collections/bookmarks/all": ("Bookmarks", (_ME, "/api/of/v2/posts/bookmarks")),
    # Its Stats › Disputes tab shows the chargebacks ratio and list.
    "/of-manager/statements": ("Statements", (
        _ME, "/api/of/v2/payouts", "/api/of/v2/payouts/transactions", "/api/of/v2/payments",
        "/api/of/v2/payouts/chargebacks")),
    # Every Statistics tab's reads. Each is a specific prefix, because the longest
    # prefix wins and the shorter ones (`/messages/queue`, `/subscriptions/subscribers`,
    # `/streams`, `/stories`, `/trials`, `/promotions`, `/campaigns`, `users/me`) belong
    # to other pages and carry their writes; `users/me/stats` is Smart Messages' too
    # (its mass-message list), so the tops, today's activity and the direct list are named.
    "/of-manager/statistics": ("Statistics", (
        _ME, "/api/of/v2/earnings", "/api/of/v2/payouts/stats", "/api/of/v2/payouts/chargebacks",
        "/api/of/v2/posts/chart", "/api/of/v2/posts/top", f"{_ME}/stats", f"{_ME}/profile",
        f"{_ME}/start-date-model", f"{_ME}/referrals", f"{_ME}/stats/top", f"{_ME}/stats/today-activity",
        f"{_ME}/stats/messages/direct", "/api/of/v2/streaks",
        "/api/of/v2/messages/queue/chart", "/api/of/v2/messages/queue/buyers",
        "/api/of/v2/subscriptions/subscribers/latest", "/api/of/v2/subscriptions/subscribers/top",
        _SUBS_CHART, "/api/of/v2/fans-activity", "/api/of/v2/streams/top", "/api/of/v2/stories/top",
        "/api/of/v2/promotions/stats", "/api/of/v2/trials/stats", "/api/of/v2/campaigns/stats",
        # Statements › Earnings, the Statements / Reach / Engagement charts, the
        # stream and story stats popup's viewer lists, and the payout invoice link.
        "/api/of/v2/payouts/transactions", "/api/of/v2/payouts/chart", "/api/of/v2/payouts/referrals",
        "/api/of/v2/payouts/download-approved-invoice", "/api/of/v2/promotions/chart",
        "/api/of/v2/trials/chart", "/api/of/v2/campaigns/chart", "/api/of/v2/stories/chart",
        "/api/of/v2/streams/chart", "/api/of/v2/streams/viewers", "/api/of/v2/stories/viewers",
        # Full stat (a post's per-item stats), a post's buyer and tipper lists,
        # and Reach's claimed / subscribers lists.
        "/api/of/v2/posts/stats", "/api/of/v2/posts/buyers", "/api/of/v2/posts/tips", "/api/of/v2/posts/likes",
        "/api/of/v2/promotions/claims", "/api/of/v2/trials/claims", "/api/of/v2/campaigns/claimers")),
    "/of-manager/bank": ("Bank", (_ME, "/api/of/v2/payouts/balances", "/api/of/v2/payouts/check-receive")),
    # stories/highlights: a highlight tile's stories, which only My profile's strip draws (not Home's `/stories`).
    "/of-manager/profile": ("My profile", (
        _ME, "/api/of/v2/users/", "/api/of/v2/posts", "/api/of/v2/labels", "/api/of/v2/posts/likes",
        "/api/of/v2/stories/highlights")),
    # Its Tag user and Release form tabs and a row's hide (release-forms/toggle-show).
    "/of-manager/release-forms": ("Release forms", (
        _ME, "/api/of/v2/posts/tagged-friend-users", "/api/of/v2/release-forms")),
    "/of-manager/settings": ("OF settings", (
        _ME, "/api/of/v2/users/settings", f"{_ME}/settings", f"{_ME}/reply-on-subscribe",
        "/api/of/v2/campaigns", "/api/of/v2/subscriptions/bundles", "/api/of/v2/promotions",
        "/api/of/v2/trials", "/api/of/v2/users/performers-search",
        "/api/of/v2/sessions")),
    # Its Overview is the Creator Reports card, which reads revenue by day and by kind (ticket 20).
    "/analytics/creator-reports": ("Creator reports", (
        *_STATS_REPORT, "/admin/stats/revenue", "/admin/stats/per-model", "/admin/stats/referrals", "/admin/stats/xlsx",
        "/api/of/v2/subscriptions/count",
        "/api/of/v2/subscriptions/subscribers", _SUBS_CHART, _ME)),
    "/analytics/employee-reports": ("Employee reports", (
        *_STATS_REPORT, "/admin/stats/per-employee", "/admin/stats/chatting-stats", "/admin/stats/xlsx",
        "/admin/stats/attribution-coverage", "/admin/stats/automation-runs",
        "/admin/stats/per-automation")),
    "/analytics/fan-reports": ("Fan reports", (
        *_STATS_REPORT, "/admin/stats/per-fan-data", "/admin/stats/fan-report")),
    "/analytics/message-dashboard": ("Message dashboard", (
        "/admin/customs", "/admin/tips-list", "/admin/top-tippers", "/admin/paid-messages",
        "/admin/messages", "/admin/fans", "/admin/saved-replies", *_PICKER, "/api/of/v2/posts",
        "/api/of/v2/posts/top", "/api/of/v2/posts/tagged-friend-users",
        "/api/of/v2/messages/templates", _ME)),
    "/analytics/sales-records": ("Sales records", ("/admin/stats/sales-records", _BATCH_REASSIGN)),
    "/messages-pro": ("Messages Pro", (
        *_MASS, "/admin/account-config",
        "/admin/chats", "/admin/copilot", "/admin/do-not-mass", "/admin/messages",
        "/admin/paid-messages", "/admin/split-inbox", "/admin/translate", "/admin/vault/sends",
        "/api/of/v2/automation-restrict", "/api/of/v2/chats", "/api/of/v2/messages",
        "/api/of/v2/payouts/transactions", "/api/of/v2/scheduled-sends", "/api/of/v2/schedules",
        "/api/of/v2/subscriptions/", "/api/of/v2/users/",
        "/api/of/v2/users/list", _ME, f"{_ME}/settings")),
    # Its Automated Messages tab lists the Nudge message and opens its editor (ticket 41), and the Delayed welcome:
    # the welcome slot and its reply-on-subscribe switch (ticket 43). The templates prefix is also `_MASS`'s; it is
    # named here so the welcome row keeps it if the mass composer ever leaves this page. The Purchased Trigger's
    # editor reads and saves the purchase_followup rule (ticket 44); Nearing expiry, Expired, Resubscribe and Birthday
    # save theirs at the lifecycle-message config route.
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
    # Each draws a List select from the fan lists (/api/of/v2/lists).
    "/growth/profile-promotion": ("Profile promotion", (
        "/admin/promotions", "/admin/automation-rules", "/admin/link-metrics", "/admin/promo-list",
        "/api/of/v2/lists")),
    "/growth/free-trial-links": ("Free trial links", (
        "/admin/trial-links", "/admin/link-metrics", "/admin/link-meta", "/api/of/v2/lists")),
    "/growth/tracking-links": ("Tracking links", (
        "/admin/tracking-links", "/admin/of-tracking-links", "/admin/link-meta", "/api/of/v2/lists")),
    # Its writes are owner-only (`_CHATTER_BLOCKED_ADMIN_PREFIXES`); its list read is every composer's.
    "/growth/sensitive-words": ("Sensitive words", ()),
    "/share-for-share/discover-creators": ("Discover creators", (
        "/admin/s4s/discover", "/admin/s4s/profiles", "/admin/s4s/requests", "/admin/s4s/blocks", "/admin/s4s/media")),
    "/share-for-share/requests": ("Requests", (
        "/admin/s4s/profiles", "/admin/s4s/requests", "/admin/s4s/requests/", "/admin/s4s/media")),
    # Every S4S page's creator rail reads the received box for its new-request counts (page-parity 15).
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
    # Saved mass_premade rules, their run log, the audience's OF lists and the vault picker.
    "/growth/auto-mass": ("Auto Mass", (
        "/admin/automation-rules", "/admin/stats/automation-runs", "/api/of/v2/lists", *_PICKER)),
    # The switch, the reply delay, the folder pick (OF's lists) and Human style.
    "/growth/auto-reply": ("Auto-reply", ("/admin/autoreply-config", "/admin/style-config", "/api/of/v2/lists")),
    # The funnels list/editor, its Reply-walking switch, ▶ Start (a funnel-linked
    # mass to an OF list) and 🖼 Media (the vault picker).
    "/growth/auto-funnel": ("Auto Funnel", (
        "/admin/funnels", "/admin/automation-rules", "/api/of/v2/lists",
        "/api/of/v2/messages/queue", *_PICKER)),
    # Not opt-in (nav.ts `notOptIn`): its Model info is the account's, editable by whoever may PUT the
    # account config (Messages Pro's and Auto Post's route too). Its automation switch and settings ride the
    # rule routes other pages grant, so this page alone opens no rule write.
    "/growth/get-to-know-fans": ("Get to know fans", ("/admin/account-config",)),
    # The gen_info switch (its rule) and the one-shot old-fans enqueue (process_old_fans).
    "/growth/gen-info": ("Gen-Info", ("/admin/automation", "/admin/automation-rules")),
    "/creators": ("Manage creators", (
        "/admin/accounts/active", "/admin/automation", "/admin/reload-session")),
    # Its proxy routes are owner-only (`_CHATTER_BLOCKED_ADMIN_PREFIXES`).
    "/creators/proxy": ("Custom proxy", ()),
    # Its Employee and chatter writes are owner-only; the folder-access picker reads vault lists.
    "/employees": ("Manage employees", ("/api/of/v2/vault/lists",)),
    "/employees/shifts": ("Shift schedule", ("/admin/shifts", _BATCH_REASSIGN)),
}

# Routes no Permission-editor page owns: the shell every page needs, sign-in,
# health, and routes only Settings or the legacy pages call. Never checked.
UNMAPPED: dict[str, str] = {
    "/": "the Relay's root answer, no Creator data",
    "/auth": "sign-in (owners and employees), the owner session, 2FA and log out other sessions",
    "/chatter": "chatter sign-in, session, its Creators and folder access",
    "/t": "public tracking-link redirect",
    "/share": "a share link's public report, read by its secret",
    "/health": "health check", "/livez": "liveness check",
    "/docs": "API docs", "/openapi.json": "API schema", "/redoc": "API docs",
    "/events": "the shell's live event stream",
    "/img": "media proxy behind every page's images",
    "/lanes-panel": "operator lanes panel, no nav page",
    "/admin/accounts": "the shell's Creator switcher (ScopeSwitcher) and its recolor, the one write"
                       " a chatter may make here (chatters.py); the rest is owner-only",
    "/admin/settings": "Settings blobs (owner-only) and the Applied settings read every session needs",
    "/admin/shifts/me": "the top bar's clock", "/admin/shifts/clock-in": "the top bar's clock",
    "/admin/shifts/clock-out": "the top bar's clock",
    "/admin/shifts/clock-status": "the top bar's clock", "/admin/shifts/clock-heartbeat": "the top bar's clock",
    "/admin/assistant": "the shell's assistant widget",
    "/admin/ai-key-status": "the AI-key notice on every automation page (key presence only)",
    "/admin/errors": "client error reports from every page",
    "/admin/perflog": "client timing reports from every page",
    "/api/of/v2/users/notifications": "the top bar's notification bell",
    "/api/of/v2/giphy": "GIF search for every composer, no Creator data",
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


def _route_table() -> list[tuple[str, tuple[str, ...]]]:
    pages: dict[str, list[str]] = {}
    for href, (_, prefixes) in PAGE_MAP.items():
        for prefix in prefixes:
            pages.setdefault(prefix, []).append(href)
    rows = [(p, tuple(dict.fromkeys(h))) for p, h in pages.items()]
    rows += [(p, ()) for p in UNMAPPED]
    return sorted(rows, key=lambda row: len(row[0]), reverse=True)


_ROUTES = _route_table()


# Writes to the Creator's own OF account (profile, price, privacy and security
# toggles, watermarks) are OF settings' alone, whichever pages read the same path.
_OF_SETTINGS = "/of-manager/settings"
_READS = frozenset({"GET", "HEAD", "OPTIONS"})


def _account_write(path: str, method: str) -> bool:
    return method.upper() not in _READS and (path == _ME or _matches(f"{_ME}/settings", path))


def route_pages(path: str, method: str) -> tuple[str, ...] | None:
    """The pages serving `method path`, in map order: () for an UNMAPPED route,
    None for a path in neither table. A write to users/me or users/me/settings*
    is OF settings' only."""
    if _account_write(path, method):
        return (_OF_SETTINGS,)
    for prefix, pages in _ROUTES:
        if _matches(prefix, path):
            return pages
    return None


# ── Dashboard cards ────────────────────────────────────────────────────────
# The Dashboard's cards a role can hide (`settings_schema.DASHBOARD_CARDS`,
# each with the Dashboard routes it reads), stored as `/#card-<id>` in the
# role's same `permissions` map. A key stored false hides the card (the
# Applied settings' `denied_cards`) and narrows the Dashboard's grant of those
# routes: the Dashboard opens one only while some card reading it is not
# hidden (`require_permission`). Another page granting the route still opens
# it, as for any shared route. A missing key falls back to the Dashboard's
# grant; an unstored built-in role's defaults may store some false
# (`BUILT_IN_ROLE_DEFAULTS[...]["denied"]`: the Chatter's revenue cards). The
# Dashboard's other routes and its owner-only cards (Current clocked-in
# employees, Scheduled hours) carry no key. The editor's and the page's list
# is app/lib/dashboardCards.ts; service/tests/test_dashboard_cards.py pins it.


def _card_route_open(path: str, denied: set[str]) -> bool:
    """Whether the Dashboard grants `path` given the hidden cards `denied`:
    a route no card reads always, a card route while one card reading it is not hidden."""
    keys = [f"/#card-{c}" for c, (_, routes, _) in DASHBOARD_CARDS.items() if any(_matches(r, path) for r in routes)]
    return not keys or any(k not in denied for k in keys)


# ── Function permissions ───────────────────────────────────────────────────
# The destructive, money and export actions on pages a chatter can reach
# (Infloww's FUN_PERMISSIONS, 07-admin-settings M8; owner-only areas need none).
# Each is stored as `<page href>#<action>` in the role's same `permissions`
# map, one key for every page serving its routes (`ACTION_KEYS`, derived). The
# relay cannot tell which page sent a request, so the rule is per action and
# fails closed: a request matching a pattern (`METHOD /path`, `*` one path
# segment, `?k=v` a query value it must carry) is refused when ANY of the
# action's keys is stored false, under any page; a missing key falls back to
# the page grant. The editor sets every key of an action alike. The editor's
# list is app/lib/permissionActions.ts; service/tests/test_role_enforcement.py
# pins it. `?format=csv` matches the exact lower-case value, the only one the
# CSV routes accept (their `format` Query pattern 422s any other).
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
        "POST /api/of/v2/users/*/restrict", "DELETE /api/of/v2/users/*/restrict")),
    "discount": ("Give subscription discounts", ("PUT /api/of/v2/subscriptions/*/discount",)),
    "export": ("Export CSV", (
        "GET /admin/paid-messages?format=csv", "GET /admin/stats/sales-records?format=csv",
        "GET /admin/stats/fan-report?format=csv", "GET /admin/tips-list?format=csv",
        "GET /admin/top-tippers?format=csv", "POST /admin/stats/xlsx")),
    "withdraw": ("Request withdrawals", (
        "POST /api/of/v2/payouts/requests", "PATCH /api/of/v2/payouts/requests")),
    "delete-post": ("Delete posts", ("DELETE /api/of/v2/posts/*",)),
    "delete-folder": ("Delete vault folders", ("DELETE /admin/vault-ai/of-folders/*",)),
    "delete-script": ("Delete scripts", ("DELETE /admin/saved-replies/*",)),
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
}


def _pattern(pattern: str) -> tuple[str, list[str], tuple[str, str] | None]:
    method, target = pattern.split(" ", 1)
    path, _, query = target.partition("?")
    key, _, value = query.partition("=")
    return method, path.split("/"), ((key, value) if query else None)


_ACTION_PATTERNS = [(action, _pattern(p)) for action, (_, ps) in ACTIONS.items() for p in ps]


def route_action(method: str, path: str, query: Mapping[str, str] | None = None) -> str | None:
    """The `ACTIONS` key `method path` performs, or None. `query` is the
    request's query params, read only by a `?k=v` pattern."""
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


# Every Function permission key the editor shows, in page-map order, and its label.
ACTION_KEYS: dict[str, str] = {
    f"{page}#{action}": ACTIONS[action][0]
    for page in PAGE_MAP for action in ACTIONS if page in _action_pages(action)
}


def require_permission(
    ctx: AgencyContext, roles: dict[str, Any], pages: tuple[str, ...], path: str, action: str | None = None,
) -> None:
    """403 `Your role does not allow <label>` unless the role grants one of
    `pages` (the pages one route serves; the Dashboard only while a card
    reading `path` is not hidden, `_card_route_open`) and, for a route performing `action`
    (`route_action`), no key of that action is stored false under any page
    (`denied_actions`; fails closed, the 403 names the action). Owners, enforcement off and an
    empty `pages` pass. A route only My Automations pages serve is not checked
    here but by `opt_in_refusal` (role_enforcement_middleware).

    ASSUMPTION: it takes the applied `roles` blob and every page the route
    serves, where the spec wrote `require_permission(ctx, page_href)`, and the
    label is the first of them in map order. Rung 5: a route shared by pages
    is allowed when any is granted, in one call. Overturned if a caller needs
    the one-page form.
    """
    granted = granted_pages(ctx, roles)
    if granted is None or not pages:
        return
    hidden = denied_cards(ctx, roles) if "/" in pages else set()
    open_pages = [p for p in pages if p in granted and (p != "/" or _card_route_open(path, hidden))]
    if not open_pages:
        raise HTTPException(status_code=403, detail=f"Your role does not allow {PAGE_MAP[pages[0]][0]}")
    if action is None:
        return
    denied = denied_actions(ctx, roles)
    if any(key.endswith(f"#{action}") for key in denied):
        raise HTTPException(status_code=403, detail=f"Your role does not allow {ACTIONS[action][0]}")


def narrowest_scope(scopes: Iterable[str]) -> str:
    """The Data scope across several Agency contexts: "all" only if every
    one is "all", else "self" (one narrowing Agency narrows the whole)."""
    return "all" if all(scope == "all" for scope in scopes) else "self"


def agency_chatter():
    """The session's chatter when an Agency's settings apply to it, else None:
    an owner or Master session, no chatter session and a chatter linked to no
    Agency are never checked against an Agency's switches."""
    chatter = get_request_chatter()
    if get_request_user() is not None or chatter is None or not chatter.owner_user_ids:
        return None
    return chatter


async def _enforcing_roles() -> dict[str, dict[str, Any]] | None:
    """The applied `roles` blob of each Agency the session's chatter is
    linked to, or None when the session is not a chatter some linked Agency
    enforces roles on (`agency_chatter` is None, or every linked Agency's
    switch off)."""
    chatter = agency_chatter()
    if chatter is None:
        return None
    from settings_api import applied_blob  # settings_api imports this module
    async with get_session() as s:
        roles = {a: await applied_blob(s, a, "roles") for a in sorted(chatter.owner_user_ids)}
    return roles if any(enforced(blob) for blob in roles.values()) else None


async def opt_in_refusal(pages: tuple[str, ...], account_id: str | None) -> str | None:
    """None when this session may use a route or write only OPT_IN_PAGES among
    `pages` serve, else the 403 detail. Owner, Master and non-Agency sessions
    pass. A chatter passes when any of its Agency contexts for `account_id`
    (every linked Agency when None) grants one of `pages` (`opt_in_granted`),
    so a non-enforcing Agency beside an enforcing one that grants it does not
    refuse. Raises the Agency context's own refusal (403 not your account)."""
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
    """403 unless this session may use My Automations page `page` for
    `account_id` (`opt_in_refusal`): the guard on the shared rule and funnel
    routes' writes that only that page makes."""
    if (detail := await opt_in_refusal((page,), account_id)) is not None:
        raise HTTPException(status_code=403, detail=detail)


async def require_opt_in_kind(kind: str, account_id: str | None) -> None:
    """`require_opt_in_page` for a rule kind only a My Automations page writes
    (`OPT_IN_KINDS`); any other kind passes."""
    if (page := OPT_IN_KINDS.get(kind)) is not None:
        await require_opt_in_page(page, account_id)


async def scoped_employee_ids() -> set[int] | None:
    """The Employee ids whose rows an employee-keyed report may show this
    session (docs/spec/phase-04 › Data scope): None for every row (owner and
    Master sessions, no chatter session, every linked Agency's enforcement
    off, or an "all" scope), else the chatter's own Mirror Employee ids, and
    where an Agency's role is "Self and subordinates" its Mirror Employee's
    `subtree_employee_ids` (phase-05: the Employees in the groups below its own).

    The Agency contexts are every linked Agency, the named Creator unread:
    `stats.per_employee` takes no Creator filter (its only parameters are
    from, to and by_account; it reads `clamp_account_filter(None)` and
    `_report_zone(None)`), so its report spans every Creator of every linked
    Agency, and one narrowing Agency narrows it (`narrowest_scope`).

    ASSUMPTION: an `X-Account-Id` sent with the report is not read,
    as the report itself does not read it. Rung 4: never wider than a stored
    scope. Overturned if per_employee gains a Creator filter: then follow
    `X-Account-Id` / `?account_id=` as role_enforcement_middleware does.
    """
    if (roles := await _enforcing_roles()) is None:
        return None
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
    """The Employees assigned role `role_id` (`_role`) in any Agency this
    session acts in (`agency_contexts`, each one's applied `roles` blob):
    Employee reports' "Show employees with chatter role only" asks for
    "chatter" (roadmap W5 5.13).

    ASSUMPTION: an Employee with no role assigned holds none, as `_role`
    reads it, and a custom role named after a built-in is not it. Rung 4.
    Overturned if Infloww's toggle keys on the role's name or treats the
    unassigned as chatters."""
    from settings_api import applied_blob  # settings_api imports this module
    out: set[int] = set()
    async with get_session() as s:
        for ctx in await agency_contexts():
            roles = await applied_blob(s, ctx.agency_user_id, "roles")
            out |= {int(eid) for eid in (roles.get("assignments") or {})
                    if str(eid).isdigit() and (_role(roles, int(eid)) or {}).get("id") == role_id}
    return out


async def role_enforcement_middleware(request, call_next):
    """Refuse a chatter session a mapped route its Permission role denies,
    before the handler runs (docs/spec/phase-04 › Role enforcement).

    Owner sessions (the Master and impersonation included), requests with no
    chatter session and unmapped routes pass untouched. So does every chatter
    whose linked Agencies all have enforcement off, before any Agency context
    is resolved. A route only My Automations pages serve is opt-in instead
    (`opt_in_refusal`): refused unless one of the chatter's Agency contexts
    grants one of its pages, the 403 naming every page it serves. Otherwise the Agency is the one Phase 1's Agency context
    picks for the named Creator; a chatter naming none is checked in every
    linked Agency, and any enforcing Agency that denies refuses. An Agency
    context refusal (403 not your account, 503) is answered as such.

    Every Creator named in `X-Account-Id` and in every `?account_id=` (each may
    be a comma list, `split_account_ids`) is checked, the union of all, so
    naming one in the header or a repeated param cannot hide another; on an opt-in
    route each must be granted.

    ASSUMPTION: the named Creators are `X-Account-Id` and `?account_id=` only; a
    Creator named only in the path or the JSON body is not read, so such a
    request is checked in every linked Agency. Rung 4: stricter, never wider.
    Overturned if a path- or body-only route must follow its Creator's Agency.
    """
    pages = route_pages(request.url.path, request.method)
    if not pages:
        return await call_next(request)
    # Every Creator named, in either place, comma-listed or not, and in every
    # repeated ?account_id= (a list Query such as sales-records reads them all).
    ids = split_account_ids(request.headers.get("x-account-id"),
                            *request.query_params.getlist("account_id")) or [None]
    if set(pages) <= OPT_IN_PAGES:
        # Served only by My Automations pages: opt-in, whatever the switch.
        try:
            for one in ids:
                if (detail := await opt_in_refusal(pages, one)) is not None:
                    return JSONResponse({"detail": detail}, status_code=403)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return await call_next(request)
    if (roles := await _enforcing_roles()) is None:
        return await call_next(request)
    try:
        # Every context's Agency is one of the chatter's linked Agencies, so its
        # blob was read above; a missing key raises (500) rather than allow.
        action = route_action(request.method, request.url.path, request.query_params)
        for one in ids:
            for ctx in await agency_contexts(account_id=one):
                require_permission(ctx, roles[ctx.agency_user_id], pages, request.url.path, action)
    except HTTPException as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return await call_next(request)
