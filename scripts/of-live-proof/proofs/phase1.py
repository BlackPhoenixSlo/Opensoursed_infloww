"""Phase 1's proofs (docs/spec/ofm-not-yet/phase-01-read-only-gaps.md, Seam D): one read `Proof` per control, kind
`live` (`mocked` where no live trigger reaches the control), nothing armed (zero writes), naming its sweep `page` and
`control` label (Phase 0's format, data only). Each Phase 1 control ticket appends its own block; ticket 26 runs
them on the Proof Creator. A proof's `of_read` is the same read the control's binder makes, as OnlyFans ids in the
order shown, so its settled rows can be matched.

    ./venv/bin/python -I scripts/of-live-proof/proofs/phase1.py --ids | --check-records <dir> | --check-sweep <sweep> <dir>

(proof_list.py says what each does.)
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from proof_core import Proof  # noqa: E402

PROOFS = ()


# ticket 14: Statistics › Engagement tabs and the messages search.
# ASSUMPTION: the period is the pages' default "Last 30 days" (periodOf d30: 30 days back at 00:00 to now) in UTC,
# the Proof Creator's time zone being unknown here (rung 4); overturned by the Proof Creator's capture, whose
# timezone then sets the window, as an id read for a day boundary row would differ.
def _d30(now=None):
    now = now or datetime.now(timezone.utc)
    f = "%Y-%m-%d %H:%M:%S"
    return (now - timedelta(days=30)).strftime("%Y-%m-%d 00:00:00"), now.strftime(f)


def _ids(body, key="items"):
    """The rows' ids: OF's `{key: [...]}` or a bare array."""
    rows = body if isinstance(body, list) else (body or {}).get(key) or []
    return [str(x["id"]) for x in rows if isinstance(x, dict) and "id" in x]


def _days(points):
    """A chart series as its non-zero days, "date:count" in order (what a redrawn chart is matched against)."""
    return [f"{d.get('date')}:{d.get('count')}" for d in points or [] if isinstance(d, dict) and d.get("count")]


def _messages(kind, query=""):
    """The messages table's first page (ofMirrorStatsSources listRoute massMessages): OF's startDate/endDate, 10 rows."""
    def read(get, fan):
        start, end = _d30()
        q = {"startDate": start, "endDate": end, "limit": 10, "offset": 0, **({"query": query} if query else {})}
        return _ids(get(f"/api2/v2/users/me/stats/messages/{kind}", q))
    return read


def _top(kind, by):
    """A Stories / Streaming list's first page ranked `by` (listRoute storiesTop / streamsTop)."""
    def read(get, fan):
        start, end = _d30()
        return _ids(get(f"/api2/v2/{kind}/top", {"by": by, "limit": 4 if kind == "stories" else 10, "offset": 0,
                                                 "start": start, "end": end}))
    return read


def _tab(pick):
    return f"[data-oi-pick='{pick}']"


def _tabs(area, page, kind, tabs, default, read):
    """One proof per tab, its of_read `read(tab)`: click it (the default tab is current, so another tab first), settled
    on it turning current. `default` None: no tab here is current on load (Referrals' default is its earnings page)."""
    other = next(v for v, _ in tabs if v != default)
    return tuple(Proof(
        id=f"p1.{area}.{kind}.{v}", phase=1, page=page, control=label, kind="live",
        trigger=(*((("click", _tab(f"{kind}:{other}")), ("wait", 2)) if v == default else ()), ("click", _tab(f"{kind}:{v}"))),
        settled=("text", f"{_tab(f'{kind}:{v}')}.m-current", label), of_read=read(v),
    ) for v, label in tabs)


MESSAGES = "statistics/engagement/messages"
SEARCH = "[data-oi-search] input[type='search']"
# ASSUMPTION: "you" is a word the Proof Creator's mass messages hold and not all of them do, so the search's rows differ
# from the unfiltered read (spec Seam D: an empty answer is no proof) (rung 4); overturned by the operator picking a
# word from the unfiltered table before the run.
SEARCH_TEXT = "you"
# The Search button lies under OF's search field (the field takes its clicks; dead.py presses Enter on it) and the
# driver has no key step, so a live trigger cannot reach it: its proof is `mocked` (dead.py's READS rows submit it),
# which the driver never runs live. The existing v2 binder (ofMirrorStatsEngagement bindSearch) already drops the
# button's Not-yet title, so proof_list --check-sweep reports it as "lost the Not-yet title" with no Live pass.
# ASSUMPTION: that D1 gap stays open for ticket 26 to close (a driver `press` step gives this proof a live trigger:
# put the text in place and press Enter on the button), not closed here by a binder change (rung 5: no driver or
# binder change in a read-only ticket); overturned by ticket 26 or the owner wanting the title kept until a pass.
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


# ticket 16: Messages › Find on the chat header menu's State page, the sort dropdown's Select, the folders dialog's Sort.
# Find (the chat page's find bar, GET /chats/{id}/messages/search?query=): live, on the header menu's State page only.
# Price, schedule, tag people and vault lay their backdrop over the chat header, so no click reaches Find there (the
# coordinator's carve-out, 2026-11-21: no proof for those four).
# ASSUMPTION: live but blocked (rung 5: no driver change in a read-only ticket): a State page needs the open chat's
# ?chat=, the driver opens a proof's page with no query (prove.py _mirror_frame matches the bare page path), and the
# Proof fan's chat id is not named yet, so its of_read is unset. Overturned by ticket 26 giving the driver a page query
# plus the Proof fan's chat id: the trigger below then runs as is, and of_read becomes that chat's search for FIND_TEXT.
FIND = "button[at-attr='search_btn']"
FIND_INPUT = ".b-chat__header form.b-chat__search-form input[name='query']"
# ASSUMPTION: "you" is a word the Proof fan's chat holds (as SEARCH_TEXT above, rung 4); overturned by the operator
# picking a word from that chat before the run.
FIND_TEXT = "you"
# Select: a UI-state control (D1: proven by its state with zero Relay writes). Its click opens the list in select mode
# (?select=1): the Mirror frame is keyed on its page (OfMirrorFrame.tsx `key={src}`), so the dropdown's frame the
# driver settles in is gone, and nothing in the list can be asserted by the driver.
# ASSUMPTION: the settled screenshot (prove.py: the whole tab after the 2 s wait) is the bar's evidence, checked by eye
# (rung 5: no driver change); overturned by a driver that re-finds the Mirror frame after a navigation: settled then
# becomes ("text", "[data-oi-select-bar]", "Select all").
# Sort: the folders dialog's lists in OF's Name, Descending, client-side over /chats/folders. A read-through proof: its
# pass shows the dialog reads OF's lists and sorts them, but does not certify OF's ordering, since FakeOF's GET /lists
# ignores sort/order (soak/fake_of/growth.py _lists) and the order is the app's own.
FOLDERS_SORT = ".modal button[aria-label='Sort']"


def _folders_by_name(get, fan):
    """The folders dialog's lists (the Relay's /chats/folders: OF's GET /lists, can_pin_chat) as ids, Name descending,
    the order its Sort's Name pick shows (ofMirrorDataLists sortFolders; casefold stands in for localeCompare)."""
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


# ticket 15: Statistics › Fans tabs, Profile visitors chips, Referrals kinds and Overview › Earnings's category radio.
# Fans "More" has no proof: both are fan action menus (OF's header menu holds only "Add to list"), moved to Phase 2
# story 51 (dead.py PHASE1's ticket 15 note). The period is the pages' default "Last 30 days", in UTC (ticket 14's
# ASSUMPTION above, `_d30`).
# ASSUMPTION: the proofs here are joined to their capture record and sweep entry by label and page (proof_list.py
# record_of / check_sweep), but "Subscriptions" and "Tips" on top-fans (the Top Fan card's tabs too) and "All" on
# subscriptions and profile-visitors (the nav's too) repeat on their page, the condition under which proof_list's own
# ASSUMPTION says Proof needs a record id. Left for ticket 26 (rung 5, and Proof's shape lives in proof_core.py, outside
# this ticket's files): measured today the twins carry no Not-yet title under v2 (the 2026-11-20 v2 sweep's ny for
# those pages holds none of these labels), so --check-sweep is not misled now; a twin keeping the title, or a second
# capture record under the same label and page, makes these proofs ambiguous. Overturned by ticket 26 adding a record id
# (or a selector) to Proof and to the sweep's ny.
def _fans(path, by):
    """A Fans table's first page for tab `by` (listRoute subsLatest / subsTop: OF's startDate/endDate, offset 0)."""
    def read(get, fan):
        start, end = _d30()
        return _ids(get(f"/api2/v2/subscriptions/subscribers/{path}", {"by": by, "offset": 0, "startDate": start,
                                                                        "endDate": end}), "users")
    return read


def _visitors(by):
    """Profile visitors' chart for chip `by` (statsRoute profileStats: limit 3), as its non-zero days, "date:count" in
    order: the chip changes a chart, not a list, so its days are what the settled chart is matched against."""
    def read(get, fan):
        start, end = _d30()
        body = get("/api2/v2/users/me/profile/stats", {"startDate": start, "endDate": end, "limit": 3, "by": by}) or {}
        return _days((body.get("chart") or {}).get("visitors"))
    return read


def _referred(performers):
    """A Referrals kind's first page (listRoute referredCreators / referredUsers: offset 0, onlyPerformers 1 / 0)."""
    def read(get, fan):
        start, end = _d30()
        return _ids(get("/api2/v2/users/me/referrals", {"startDate": start, "endDate": end, "offset": 0,
                                                        "onlyPerformers": performers}), "list")
    return read


# ASSUMPTION: the radio makes no read (it redraws a series already loaded), so its of_read is the read the page made
# on load, OF's Overview earnings chart (statsRoute earningsChart: every series' amount), as the picked series'
# non-zero days, to match the redrawn chart (rung 3: ticket 14's of_read is the binder's read); overturned by ticket
# 26 wanting no of_read for a control with no read of its own.
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


# ticket 17: Notifications' Search users, Search users or posts and the Scheduled events widget's new-event button, on
# every tab. Labels as the sweep's (each once per page on its bare load: the Search users form, whose field reads "Search
# users" too, opens only on a click). Search users picks the users search's first fan (the binder's first row) and reads
# the tab for that fan; Tags reads its mentions and keeps that fan's (relatedOnly). The new-event button only navigates:
# a UI-state control, with no of_read, its settled screenshot the evidence (ticket 16 Select's ASSUMPTION: the driver
# does not re-find the Mirror frame after a navigation).
# ASSUMPTION: FAN_TEXT is a word that names the Proof fan in OF's users search, the fan first among its answers and
# holding a notification of each type tab's kind (an empty answer is no proof, Seam D) (rung 4); overturned by ticket 26
# naming the Proof fan, whose username then replaces it (a tab where that fan has no notification needs a seeded one).
# ASSUMPTION: OF's /users/notifications and /release-forms/mentions answer {list} of items with an "id" (the Relay
# passes them through: of_reads.py notifications, release_form_mentions; no capture of the ids here) (rung 4);
# overturned by the capture, whose key then replaces "list".
NOTIF_TABS = ("index", "subscribed", "commented", "mentioned", "tip", "purchases", "favorited", "message", "deactivated_media", "tags")
FAN_TEXT = "you"
NOTIF_SEARCH = ".m-notifications-user-search button[aria-label='Search users']"
NOTIF_FORM = "[data-oi-notif-search] input[type='search']"
NOTIF_PICK = "#oi-notif-users [data-oi-notif-user]"
ASIDE_SEARCH = "input[name='feed-search-input']"


def _fans_found(get, query, limit=5):
    """OF's users search as the Relay sends it (of_reads.py search_users: view=se), its fans' ids in order."""
    body = get("/api2/v2/users", {"limit": limit, "offset": 0, "query": query, "view": "se"})
    return _ids(body, "list")


def _notifs_of(tab):
    """The tab for the search's first fan: a type tab re-read with related_user (ofMirrorFeedsNotifications
    notificationsRoute), Tags its mentions keeping that fan's (relatedOnly)."""
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
    """The aside's search (bindFeedSearch, 5 of each): the users' ids, then the posts' (of_reads.py search_posts)."""
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


# ticket 18: Collections' Posts tab (Collections and Fans), Fans' Expired tab and Search users (Collections and a list
# page). Posts and Expired keep OF's disabled and Not-yet title until their pass (D1, dead.py's "not-yet" rows), so
# their live triggers reach them only once ticket 26's driver un-greys a proof's control as dead.py does.
# Posts opens another Mirror page (collections/user-lists/list/posts?list=<id>): the frame the driver settles in is gone,
# so its proofs have no settled check (ticket 16's Select ASSUMPTION: the settled screenshot is the evidence, rung 5;
# overturned by a driver that re-finds the Mirror frame after a navigation, settled then becoming
# ("text", ".l-main-content.m-r-side .b-post__text", "") with the of_read ids matched).
# Search users needs Enter on its field (the driver has no key step, ticket 14's Search): `mocked`, dead.py's READS rows
# submit it. It is already Wired with no Not-yet title (an existing binder), so --check-sweep reports it as ticket 14's
# Search is reported (that D1 gap left to ticket 26 as there).
POSTS_TAB = "button.b-tabs__nav__link.m-tb-sm"
FANS = "collections/user-lists/subscribers/active"


def _list_posts(list_id=None):
    """A list's Posts tab's first page (listPostsPath: limit 10, the Relay's offset 0 and skip_users=all); `list_id`
    None: the list a bare Collections page opens, the first of OF's lists (USER_LISTS: limit 50, format=infinite)."""
    def read(get, fan):
        lid = list_id or next(iter(_ids(get("/api2/v2/lists", {"limit": 50, "offset": 0, "format": "infinite"}), "list")), None)
        return _ids(get(f"/api2/v2/lists/{lid}/posts", {"offset": 0, "limit": 10, "skip_users": "all"}), "list") if lid else []
    return read


def _expired(get, fan):
    """Fans' Expired cards (subscribersPath expired: limit 50; the Relay's offset 0 and default sort)."""
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


# ticket 19: Home's feed tabs pencil (home/state-feed-tabs-edit, OF's "Pin to home"): its Sort, Name, over the Relay's
# /lists (USER_LISTS) filtered to the lists OF lets pin (canPinnedToFeed not false; OF's own open read asks
# filter=can_pin, docs/of-manager/captures/home--story-editor-page.json). The Sort keeps OF's disabled and Not-yet title
# until its pass (D1, dead.py's "not-yet" row), so the trigger reaches it once ticket 26's driver un-greys a proof's
# control as dead.py does. A pick navigates to the same Mirror page with ?fsort=&forder= (the frame is kept).
# ASSUMPTION: a read-through proof, as ticket 16's folders Sort: FakeOF's GET /lists ignores sort/order and the order is
# the app's own (ofMirrorDataLists sortFolders), so a pass shows the dialog reads OF's lists and sorts them, not OF's own
# ordering (rung 3); overturned by a capture of OF's Pin to home sort menu showing a server-side sort (a re-read with
# sort/order params), which then becomes this proof's of_read.
PIN_SORT = ".modal button[aria-label='Sort']"


def _pin_home_by_name(get, fan):
    """Pin to home's lists (the Relay's /lists: limit 50, offset 0, format=infinite) OF lets pin, as ids, Name
    descending, the order its Sort's Name pick shows (casefold stands in for localeCompare)."""
    body = get("/api2/v2/lists", {"limit": 50, "offset": 0, "format": "infinite"})
    rows = [x for x in (body or {}).get("list") or [] if isinstance(x, dict) and "id" in x and x.get("canPinnedToFeed") is not False]
    return [str(x["id"]) for x in sorted(rows, key=lambda x: str(x.get("name") or "").casefold(), reverse=True)]


PROOFS += (
    Proof(id="p1.home.pin.sort", phase=1, page="home/state-feed-tabs-edit", control="Sort", kind="live",
          trigger=(("click", PIN_SORT), ("click", "#oi-menu [data-oi-value='name']"), ("wait", 2)),
          of_read=_pin_home_by_name),
)


# ticket 24: Statements › Earning statistics' "From … To …" Apply re-reads /payouts/stats for the picked days (OF's
# startDate/endDate, YYYY-MM-DD; OF ignores start/end, measured 2026-11-21) and All time shows the range's totals and its
# days on the button. The button keeps OF's Not-yet title and disabled until its pass (D1, dead.py's "not-yet" row), so
# the trigger reaches it once ticket 26's driver un-greys a proof's control as dead.py does. The picker opens on today;
# its first day click sets the range's start (the end stays today), so the range is this month's 1st to today.
# ASSUMPTION: the range is the current month's 1st to today in UTC, the Proof Creator's time zone being unknown here
# (rung 4, ticket 14's _d30); overturned by the Proof Creator's capture showing another zone, or a run at a UTC day edge.
# ASSUMPTION: the Proof Creator started before this month's 1st (the picker's earliest day is their start) and earned
# something outside this month, so the range's totals differ from all time's (Seam D: an empty answer is no proof)
# (rung 4); overturned by of_read refusing on a pass, which then names a range with sales.
RANGE_BTN = ".b-stats-row__body button.m-time-period"


def _month_to_date(now=None):
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1), now


def _earning_range(get, fan):
    """All time's and the range's net and gross (OF's /payouts/stats `list.total.all`), as OF answers each; refused when
    the range is empty or answers what all time does."""
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
