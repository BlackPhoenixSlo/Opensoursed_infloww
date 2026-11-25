import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from proof_core import Proof  # noqa: E402

PROOFS = ()


def _d30(now=None):
    now = now or datetime.now(timezone.utc)
    f = "%Y-%m-%d %H:%M:%S"
    return (now - timedelta(days=30)).strftime("%Y-%m-%d 00:00:00"), now.strftime(f)


def _ids(body, key="items"):
    rows = body if isinstance(body, list) else (body or {}).get(key) or []
    return [str(x["id"]) for x in rows if isinstance(x, dict) and "id" in x]


def _days(points):
    return [f"{d.get('date')}:{d.get('count')}" for d in points or [] if isinstance(d, dict) and d.get("count")]


def _messages(kind, query=""):
    def read(get, fan):
        start, end = _d30()
        q = {"startDate": start, "endDate": end, "limit": 10, "offset": 0, **({"query": query} if query else {})}
        return _ids(get(f"/api2/v2/users/me/stats/messages/{kind}", q))
    return read


def _top(kind, by):
    def read(get, fan):
        start, end = _d30()
        return _ids(get(f"/api2/v2/{kind}/top", {"by": by, "limit": 4 if kind == "stories" else 10, "offset": 0,
                                                 "start": start, "end": end}))
    return read


def _tab(pick):
    return f"[data-oi-pick='{pick}']"


def _tabs(area, page, kind, tabs, default, read):
    other = next(v for v, _ in tabs if v != default)
    return tuple(Proof(
        id=f"p1.{area}.{kind}.{v}", phase=1, page=page, control=label, kind="live",
        trigger=(*((("click", _tab(f"{kind}:{other}")), ("wait", 2)) if v == default else ()), ("click", _tab(f"{kind}:{v}"))),
        settled=("text", f"{_tab(f'{kind}:{v}')}.m-current", label), of_read=read(v),
    ) for v, label in tabs)


MESSAGES = "statistics/engagement/messages"
SEARCH = "[data-oi-search] input[type='search']"
SEARCH_TEXT = "you"
PROOFS += (
    *_tabs("engagement", MESSAGES, "msg", (("group", "Mass messages"), ("direct", "Direct messages")), "group", _messages),
    Proof(id="p1.engagement.msg.search-input", phase=1, page=MESSAGES, control="Search messages...", kind="live",
          trigger=(("fill", SEARCH, SEARCH_TEXT), ("wait", 2)), of_read=_messages("group", SEARCH_TEXT)),
    Proof(id="p1.engagement.msg.search", phase=1, page=MESSAGES, control="Search", kind="mocked"),
    *_tabs("engagement", "statistics/engagement/stories", "stories",
           (("tips", "Tips"), ("views", "Viewers"), ("likes", "Likes"), ("comments", "Comments")), "tips",
           lambda v: _top("stories", v)),
    *_tabs("engagement", "statistics/engagement/streaming", "streams",
           (("purchases", "Purchases"), ("tips", "Tips"), ("views", "Viewers"), ("likes", "Likes"),
            ("comments", "Comments")), "purchases", lambda v: _top("streams", v)),
)


FIND = "button[at-attr='search_btn']"
FIND_INPUT = ".b-chat__header form.b-chat__search-form input[name='query']"
FIND_TEXT = "you"
FOLDERS_SORT = ".modal button[aria-label='Sort']"


def _folders_by_name(get, fan):
    body = get("/api2/v2/lists", {"filter": "can_pin_chat", "isChat": "true", "skip_users": "all", "format": "infinite",
                                  "limit": 50, "offset": 0})
    rows = [x for x in (body or {}).get("list") or [] if isinstance(x, dict) and "id" in x and x.get("canPinnedToChat") is not False]
    return [str(x["id"]) for x in sorted(rows, key=lambda x: str(x.get("name") or "").casefold(), reverse=True)]


PROOFS += (
    Proof(id="p1.messages.find", phase=1, page="messages/chat/state-header-menu", control="Find", kind="live",
          trigger=(("click", FIND), ("fill", FIND_INPUT, FIND_TEXT), ("wait", 2)),
          settled=("text", ".b-chat__search__results-count", "/")),
    Proof(id="p1.messages.select", phase=1, page="messages/state-filter-dropdown", control="Select", kind="live",
          trigger=(("click", "[data-oi-select]"), ("wait", 2))),
    Proof(id="p1.messages.folders.sort", phase=1, page="messages/state-folders", control="Sort", kind="live",
          trigger=(("click", FOLDERS_SORT), ("click", "#oi-menu [data-oi-value='name']"), ("wait", 2)),
          of_read=_folders_by_name),
)


def _fans(path, by):
    def read(get, fan):
        start, end = _d30()
        return _ids(get(f"/api2/v2/subscriptions/subscribers/{path}", {"by": by, "offset": 0, "startDate": start,
                                                                        "endDate": end}), "users")
    return read


def _visitors(by):
    def read(get, fan):
        start, end = _d30()
        body = get("/api2/v2/users/me/profile/stats", {"startDate": start, "endDate": end, "limit": 3, "by": by}) or {}
        return _days((body.get("chart") or {}).get("visitors"))
    return read


def _referred(performers):
    def read(get, fan):
        start, end = _d30()
        return _ids(get("/api2/v2/users/me/referrals", {"startDate": start, "endDate": end, "offset": 0,
                                                        "onlyPerformers": performers}), "list")
    return read


OVERVIEW_FILTER = [f"{c}_amount" for c in ("total", "subscribes", "tips", "tips_stream", "post", "messages", "ref", "stream")]


def _series(row):
    def read(get, fan):
        start, end = _d30()
        body = get("/api2/v2/earnings/chart", {"startDate": start, "endDate": end, "withTotal": "true",
                                               **{f"filter[{k}]": k for k in OVERVIEW_FILTER}}) or {}
        return _days((body.get(row) or {}).get("chartAmount"))
    return read


RADIO = ".m-overview-earnings-table [data-oi-pick='row:subscribes']"
PROOFS += (
    *_tabs("fans", "statistics/fans/subscriptions", "subs",
           (("total", "All"), ("renew", "Renews"), ("new", "New subscribers")), "total", lambda v: _fans("latest", v)),
    *_tabs("fans", "statistics/fans/top-fans", "top",
           (("total", "Total"), ("subscribes", "Subscriptions"), ("tips", "Tips"), ("messages", "Messages"),
            ("post", "Posts"), ("streams", "Streams")), "total", lambda v: _fans("top", v)),
    *_tabs("reach", "statistics/reach/profile-visitors", "visitors",
           (("total", "All"), ("guests", "Guests"), ("users", "Users")), "total", _visitors),
    *_tabs("referrals", "statistics/statements/referrals/earnings", "ref",
           (("creators", "Referred creators"), ("users", "Referred users")), None,
           lambda v: _referred(1 if v == "creators" else 0)),
    Proof(id="p1.overview.earnings.radio", phase=1, page="statistics/overview/earnings", control="[b-input-radio]",
          kind="live", trigger=(("click", RADIO),),
          settled=("text", ".m-overview-earnings-table .b-stats-row__label.m-current", "Subscriptions"),
          of_read=_series("subscribes")),
)


NOTIF_TABS = ("index", "subscribed", "commented", "mentioned", "tip", "purchases", "favorited", "message", "deactivated_media", "tags")
FAN_TEXT = "you"
NOTIF_SEARCH = ".m-notifications-user-search button[aria-label='Search users']"
NOTIF_FORM = "[data-oi-notif-search] input[type='search']"
NOTIF_PICK = "#oi-notif-users [data-oi-notif-user]"
ASIDE_SEARCH = "input[name='feed-search-input']"


def _fans_found(get, query, limit=5):
    body = get("/api2/v2/users", {"limit": limit, "offset": 0, "query": query, "view": "se"})
    return _ids(body, "list")


def _notifs_of(tab):
    def read(get, fan):
        fans = _fans_found(get, FAN_TEXT)
        if not fans:
            return []
        if tab == "tags":
            body = get("/api2/v2/release-forms/mentions", {"limit": 20, "offset": 0, "skip_users": "all", "format": "infinite"})
            return [str(x["id"]) for x in (body or {}).get("list") or []
                    if isinstance(x, dict) and "id" in x and str((x.get("user") or x.get("fromUser") or {}).get("id")) == fans[0]]
        q = {"limit": 20, "offset": 0, **({} if tab == "index" else {"type": tab}), "related_user": fans[0]}
        return _ids(get("/api2/v2/users/notifications", q), "list")
    return read


def _aside(get, fan):
    posts = get("/api2/v2/posts", {"limit": 5, "query": FAN_TEXT, "skip_users": "all", "format": "infinite"})
    return _fans_found(get, FAN_TEXT) + _ids(posts, "list")


PROOFS += tuple(p for tab in NOTIF_TABS for p in (
    Proof(id=f"p1.notifications.{tab}.search-users", phase=1, page=f"notifications/{tab}", control="Search users",
          kind="live", trigger=(("click", NOTIF_SEARCH), ("fill", NOTIF_FORM, FAN_TEXT), ("wait", 2), ("click", NOTIF_PICK),
                                ("wait", 2)),
          of_read=_notifs_of(tab)),
    Proof(id=f"p1.notifications.{tab}.search-aside", phase=1, page=f"notifications/{tab}", control="Search users or posts",
          kind="live", trigger=(("fill", ASIDE_SEARCH, FAN_TEXT), ("wait", 2)), settled=("text", "#oi-search-results", "Users"),
          of_read=_aside),
    Proof(id=f"p1.notifications.{tab}.new-event", phase=1, page=f"notifications/{tab}", control="[b-new-event-btn]",
          kind="live", trigger=(("click", "button[at-attr='add_event_widget']"), ("wait", 2))),
))


POSTS_TAB = "button.b-tabs__nav__link.m-tb-sm"
FANS = "collections/user-lists/subscribers/active"


def _list_posts(list_id=None):
    def read(get, fan):
        lid = list_id or next(iter(_ids(get("/api2/v2/lists", {"limit": 50, "offset": 0, "format": "infinite"}), "list")), None)
        return _ids(get(f"/api2/v2/lists/{lid}/posts", {"offset": 0, "limit": 10, "skip_users": "all"}), "list") if lid else []
    return read


def _expired(get, fan):
    body = get("/api2/v2/subscriptions/subscribers", {"type": "expired", "limit": 50, "offset": 0, "sort": "-users.last_activity"})
    return _ids(body, "list")


PROOFS += (
    Proof(id="p1.collections.posts", phase=1, page="collections/index", control="Posts", kind="live",
          trigger=(("click", POSTS_TAB), ("wait", 2)), of_read=_list_posts()),
    Proof(id="p1.collections.fans.posts", phase=1, page=FANS, control="Posts", kind="live",
          trigger=(("click", POSTS_TAB), ("wait", 2)), of_read=_list_posts("fans")),
    Proof(id="p1.collections.fans.expired", phase=1, page=FANS, control="Expired", kind="live",
          trigger=(("click", "button.b-tabs__nav__link:text-is('Expired')"), ("wait", 2)),
          settled=("text", ".l-main-content.m-r-side .b-tabs__nav__link.m-current", "Expired"), of_read=_expired),
    Proof(id="p1.collections.search-users", phase=1, page="collections/index", control="Search users", kind="mocked"),
    Proof(id="p1.collections.list.search-users", phase=1, page="collections/user-lists/list", control="Search users", kind="mocked"),
)


PIN_SORT = ".modal button[aria-label='Sort']"


def _pin_home_by_name(get, fan):
    body = get("/api2/v2/lists", {"limit": 50, "offset": 0, "format": "infinite"})
    rows = [x for x in (body or {}).get("list") or [] if isinstance(x, dict) and "id" in x and x.get("canPinnedToFeed") is not False]
    return [str(x["id"]) for x in sorted(rows, key=lambda x: str(x.get("name") or "").casefold(), reverse=True)]


PROOFS += (
    Proof(id="p1.home.pin.sort", phase=1, page="home/state-feed-tabs-edit", control="Sort", kind="live",
          trigger=(("click", PIN_SORT), ("click", "#oi-menu [data-oi-value='name']"), ("wait", 2)),
          of_read=_pin_home_by_name),
)


RANGE_BTN = ".b-stats-row__body button.m-time-period"


def _month_to_date(now=None):
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1), now


def _earning_range(get, fan):
    first, today = _month_to_date()

    def totals(q):
        body = get("/api2/v2/payouts/stats", q) or {}
        a = ((body.get("list") or body).get("total") or {}).get("all") or {}
        return [a.get("total_net") or 0, a.get("total_gross") or 0]

    all_time = totals({"by": "day"})
    ranged = totals({"by": "day", "startDate": first.strftime("%Y-%m-%d"), "endDate": today.strftime("%Y-%m-%d")})
    if not any(ranged) or ranged == all_time:
        raise ValueError(f"the range's totals {ranged} are empty or equal all time's {all_time}: no proof")
    return {"all": all_time, "range": ranged}


_FIRST = _month_to_date()[0]
PROOFS += (
    Proof(id="p1.statements.range.apply", phase=1, page="statements/stats/earnings", control="From ", kind="live",
          trigger=(("click", RANGE_BTN), ("click", f"[data-oi-picker] [data-oi-day='{_FIRST:%Y-%m-%d}']"),
                   ("click", "[data-oi-picker-apply]"), ("wait", 2)),
          settled=("text", ".b-stats-row.m-expanded .b-date-value", f"{_FIRST:%b} 1, {_FIRST.year}"),
          of_read=_earning_range),
)

if __name__ == "__main__":
    import proof_list
    sys.exit(proof_list.main(PROOFS, sys.argv[1:], prog="phase1.py"))
