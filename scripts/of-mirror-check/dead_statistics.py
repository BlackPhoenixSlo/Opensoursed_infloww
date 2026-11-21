"""dead.py's Statistics rows (tickets 13, 14, 15; dead.py's MODULES): the v2 Relay mock (V2) and the PHASE1 and READS
rows of Statistics' Engagement, Fans, Profile visitors, Referrals and Overview > Earnings, in dead.py's shapes (see its
PHASE1 and READS notes). Data plus its own mocks; helpers from dead_lib.
"""
from dead_lib import SNAP, TIPS, each, fx, hits, rekey, rev, spot, top_by
def _chart_filter(q):
    """/earnings/chart's filter: Overview › Earnings asks every series' amount (ref among them), the Statements sidebar
    each category's count and amount, a Statements tab its own two."""
    f=q.get("filter","").split(",")
    return "overview" if "ref_amount" in f else "side" if len(f)>2 else q.get("filter","")
# A v2 Relay (omf-statistics-relay): /streaks/top, the probe (ofMirrorStats.ts V2_PROBE), answers an object, and every
# source a Phase 1 Statistics tab gates on answers in its real shape, from the Statistics vitest fixtures:
# path -> (param, or a function of the query; the body for OF's default tab or no param; {other tab's value: its body}).
# Another tab answers other rows than the default, so a dropped param reads the default (unfiltered) rows.
# ASSUMPTION: where the fixtures hold one body for a ranked list, another tab answers the same rows reversed; Top fans'
# other tabs answer statistics-subs-top-tips.json (synthetic rows in subs-top's shape, Tips-ranked; one body for every
# non-Total tab); overturned by a Request capture of a second tab's reply, which then becomes its fixture. Stories:
# see ticket 14's rows below.
V2={
    "/api/of/v2/streaks/top": (None, fx("streaks-top"), {}),
    "/api/of/v2/earnings/chart": (_chart_filter, [], {"overview":fx("earnings-chart-overview"), "side":fx("earnings-side")}),
    "/api/of/v2/users/me/referrals": ("onlyPerformers", fx("referred-empty"), {"1":fx("referred-creators"),
        "0":rev("referred-creators")}),  # ticket 15: Referred users (synthetic, ASSUMPTION as above: the creators reversed)
    "/api/of/v2/payouts/referrals/chart": (None, fx("referrals-chart-zero"), {}),
    "/api/of/v2/users/me/stats/top/message": (None, fx("top-message"), {}),
    "/api/of/v2/users/me/stats/top/story": (None, fx("top-story"), {}),
    "/api/of/v2/users/me/stats/top/stream": (None, fx("top-stream"), {}),
    "/api/of/v2/users/me/stats/top/fan": (None, fx("top-fan"), {}),
    # ticket 14: Stories' other tabs answer statistics-stories-top-views.json (synthetic, /stories/top's shape, two
    # stories Viewers-ranked; Likes and Comments the same reversed), and each metric's chart its own series and total.
    # ASSUMPTION: synthetic until a Request capture of a second tab's reply (as subs-top-tips above).
    "/api/of/v2/stories/top": ("by", fx("stories-top"), {"views":fx("stories-top-views"), **each(("likes","comments"), rev("stories-top-views"))}),
    "/api/of/v2/stories/chart": ("by", rekey("stories-chart-views", "views", "tips", 3), {"views":fx("stories-chart-views"),
        "likes":rekey("stories-chart-views", "views", "likes", 5), "comments":rekey("stories-chart-views", "views", "comments", 6)}),
    "/api/of/v2/streams/top": ("by", fx("streams-top"), each(("tips","views","likes","comments"), rev("streams-top"))),
    "/api/of/v2/streams/chart": ("by", fx("streams-chart-zero"), {"tips":fx("streams-chart-tips"),  # views..comments: ticket 14
        **{k: rekey("streams-chart-tips", "tips", k, n) for k, n in (("views", 7), ("likes", 3), ("comments", 2))}}),
    "/api/of/v2/subscriptions/subscribers/top": ("by", fx("subs-top"), each(("subscribes","tips","messages","post","streams"), fx("subs-top-tips"))
        | {k: top_by(f"{k.replace('post', 'posts')}Summ", 3) for k in ("subscribes","post","streams")}),  # ticket 15
    "/api/of/v2/subscriptions/subscribers/latest": ("by", fx("subs-latest"), {"renew":rev("subs-latest"),
        "new":{**fx("subs-latest"), "users":fx("subs-latest")["users"][:1]}}),  # ticket 15: New its own rows, Fan D alone (synthetic)
    "/api/of/v2/subscriptions/subscribers/chart": ("by", fx("subscribers-chart"), {"renew":fx("subs-chart-renew"),
        "new":spot("subs-chart-renew", {"subscribes":("2026-10-05", 1), "earnings":("2026-10-05", 9.99)}, subscribers=1, total=9.99)}),  # ticket 15
    "/api/of/v2/users/me/profile/stats": ("by", fx("profile-stats"), {"guests":fx("profile-stats-guests"),
        "users":spot("profile-stats-guests", {"chart.visitors":("2026-10-05", 5)})}),  # ticket 15
    # ticket 14: the search box's `query` ("message 3", READS) answers only the matching mass message; a 2-character
    # one, which the app must never send, answers no rows, so a sent one fails the short-text rows.
    "/api/of/v2/users/me/stats/messages/group": ("query", fx("messages-group"), {"message 3":hits("messages-group", "message 3"),
        "me":{**fx("messages-group"), "items":[]}}),
    "/api/of/v2/users/me/stats/messages/direct": (None, fx("messages-direct"), {}),
    "/api/of/v2/messages/queue/chart": ("type", fx("messages-chart-zero"), {"direct":fx("messages-chart-direct")}),
}
PHASE1=[
    ("statistics/fans/top-fans", "css:[data-oi-pick='top:tips']", "pending"),
    # ticket 14: Statistics › Engagement (remainder: every label wired by an existing binder under v2), pending until
    # each control's Live proof (D1, ticket 26).
    *[("statistics/engagement/messages", c, "pending") for c in ("Mass messages", "Direct messages", "Search", "Search messages...")],
    *[("statistics/engagement/stories", c, "pending") for c in ("Tips", "Viewers", "Likes", "Comments")],
    *[("statistics/engagement/streaming", c, "pending") for c in ("Purchases", "Tips", "Viewers", "Likes", "Comments")],
    # ticket 15: Fans, Profile visitors, Referrals and Overview › Earnings's category radio (remainder: wired by an
    # existing binder under v2), pending until each control's Live proof (D1, ticket 26). By selector: their labels
    # repeat on the page (Subscriptions and Tips are Top Fan card tabs too, All is in the nav).
    # Fans "More" (remainder: still Not-yet) is no read: OF's Fans header menu (statistics-fans.js, the m-extra-dropdown)
    # holds one item, "Add to list" (openUsersListsModal: the shown fans into a list, a write), and the Top Fan card's
    # More is the collections user-card menu; both are fan action menus, moved to Phase 2 story 51 (the ticket's own
    # ASSUMPTION, overturned by the coordinator assigning them elsewhere), so no row here.
    *[("statistics/fans/subscriptions", f"css:[data-oi-pick='subs:{v}']", "pending") for v in ("total", "renew", "new")],
    *[("statistics/fans/top-fans", f"css:[data-oi-pick='top:{v}']", "pending") for v in ("total", "subscribes", "messages", "post", "streams")],
    *[("statistics/reach/profile-visitors", f"css:[data-oi-pick='visitors:{v}']", "pending") for v in ("total", "guests", "users")],
    *[("statistics/statements/referrals/earnings", f"css:[data-oi-pick='ref:{v}']", "pending") for v in ("creators", "users")],
    ("statistics/overview/earnings", "[b-input-radio]", "pending"),
]
# ticket 14: Statistics › Engagement. Each row's snapshot is the table or cards plus the chart's summary (its figures
# come from the series the chart draws). OF's default tab (Mass messages, Stories Tips, Streaming Purchases) is current
# on load, so its row first picks another tab and then goes back, and checks only what settles (no `get`: whether
# going back reads again is the binder's cache, not the control).
MSG_SNAP=SNAP(".b-statements-table tbody > tr[data-oi-data]", "[data-oi-stat^='messages:massMessages']")
MSG_SEARCH="css:[data-oi-search] input[type='search']"
MSG_BUTTON="css:[data-oi-search] button[type='submit']"
MSG_GROUP, MSG_DIRECT="/api/of/v2/users/me/stats/messages/group", "/api/of/v2/users/me/stats/messages/direct"
MSG_ALL=["Synthetic mass message 1", "Synthetic mass message 2", "Synthetic mass message 3"]
def _list_reads(page, kind, tabs, default):
    """Stories or Streaming: one row per metric tab, its list and chart read with its `by`; the default tab's row
    picks another tab first."""
    snap=SNAP(f"[data-oi-list='{kind}'] > .b-top-statistic .b-top-statistic__content", f"[data-oi-summary='{kind}'] [data-oi-summary-b]")
    out=[]
    for by, (first, chart) in tabs.items():
        row={"page":page, "steps":[("click", f"css:[data-oi-pick='{kind}:{by}']")], "settled":snap,
             "shows":[f'"first": "{first}', f'"chart": "{chart}"'],
             "hides":[f'"chart": "{c}"' for b, (_, c) in tabs.items() if b!=by]}
        if by==default:
            other=next(b for b in tabs if b!=by)
            row["steps"].insert(0, ("click", f"css:[data-oi-pick='{kind}:{other}']"))
        else:
            row["get"]=[(f"/api/of/v2/{kind}/top", {"by":by}), (f"/api/of/v2/{kind}/chart", {"by":by})]
        out.append(row)
    return out
# A card's figures as the fixtures give them (viewersCount/viewsCount, likesCount, commentsCount, tipsCount, tips sum).
S58001, S58011="Viewers 4 Likes 2 Comments 1 Tips 0 ($0.00)", "Viewers 9 Likes 3 Comments 2 Tips 0 ($0.00)"
S57001, S57002="Viewers 2 ($0.00) Likes 1 Comments 0 Tips 1 ($5.00)", "Viewers 0 ($0.00) Likes 0 Comments 0 Tips 0 ($0.00)"
def _msg(steps, **row): return {"page":"statistics/engagement/messages", "steps":steps, "settled":MSG_SNAP, **row}
ENGAGEMENT_READS=[
    # Mass vs Direct: the table's path and the chart's `type` follow the tab; the direct answer's rows and chart figures
    # (2 messages, $9.98) show, the group's rows do not.
    _msg([("click", "css:[data-oi-pick='msg:direct']")], all=True,
         get=[(MSG_DIRECT, {}), ("/api/of/v2/messages/queue/chart", {"type":"direct"})],
         shows=["Synthetic direct message", "$9.98"], hides=["Synthetic mass message 1"]),
    _msg([("click", "css:[data-oi-pick='msg:direct']"), ("click", "css:[data-oi-pick='msg:group']")],
         shows=["Synthetic mass message 1"], hides=["Synthetic direct message", "$9.98"]),
    # Search, typed in the field or put there and submitted with the button: 3+ characters read the group stats with
    # `query` and show only the match; under 3 send nothing, so the "message 3" filter stays (the mock answers "me"
    # with no rows, so a sent one empties the table and fails `shows`); clearing the field restores the full table.
    # Both start from the "message 3" filter, so a clear that sends nothing fails `shows` too.
    *[_msg(steps, get=[(MSG_GROUP, {"query":"message 3"})], shows=["Synthetic mass message 3"], hides=MSG_ALL[:2])
      for steps in ([("fill", MSG_SEARCH, "message 3")],
                    [("set", MSG_SEARCH, "message 3"), ("press", MSG_BUTTON, "Enter")])],
    *[_msg(steps, shows=["Synthetic mass message 3"], hides=MSG_ALL[:2])
      for steps in ([("fill", MSG_SEARCH, "message 3"), ("fill", MSG_SEARCH, "me")],
                    [("fill", MSG_SEARCH, "message 3"), ("set", MSG_SEARCH, "me"), ("press", MSG_BUTTON, "Enter")])],
    *[_msg(steps, shows=MSG_ALL)
      for steps in ([("fill", MSG_SEARCH, "message 3"), ("fill", MSG_SEARCH, "")],
                    [("fill", MSG_SEARCH, "message 3"), ("set", MSG_SEARCH, ""), ("press", MSG_BUTTON, "Enter")])],
    # Stories and Streaming: each metric tab re-ranks the cards (the first card differs between tabs) and redraws the
    # chart, whose summary figure is that metric's total in the v2 mock's chart for it.
    *_list_reads("statistics/engagement/stories", "stories", {
        # first cards: 58001 (statistics-stories-top.json) for Tips, 58011 for Viewers, 58001 again for Likes/Comments
        "tips": (S58001, "$3.00"), "views": (S58011, "4 viewers"), "likes": (S58001, "5 likes"), "comments": (S58001, "6 comments")}, "tips"),
    *_list_reads("statistics/engagement/streaming", "streams", {
        # first cards: 57001 (statistics-streams-top.json) for Purchases, 57002 (the rows reversed) for the rest
        "purchases": (S57001, "$0.00"), "tips": (S57002, "$5.00"), "views": (S57002, "7 viewers"), "likes": (S57002, "3 likes"),
        "comments": (S57002, "2 comments")}, "purchases"),
]
def _pick(kind, v): return ("click", f"css:[data-oi-pick='{kind}:{v}']")
TOP_SNAP=SNAP("[data-oi-table='topfans'] tbody > tr", "[data-oi-table='topfans'] thead th")
TOP="/api/of/v2/subscriptions/subscribers/top"
FAN_E, FAN_T, FAN_U="SF Synthetic Fan E @u_synthetic_e", "SF Synthetic Fan T @u_synthetic_t", "SF Synthetic Fan U @u_synthetic_u"
SUBS_SNAP=TIPS("[data-oi-table='subs'] tbody > tr[data-oi-data]",
               ".b-statistics-page-content__wrapper > .b-elements-determinant__value, [data-oi-table='subs'] thead th")
SUBS_GET=lambda by: [("/api/of/v2/subscriptions/subscribers/chart", {"by":by}), ("/api/of/v2/subscriptions/subscribers/latest", {"by":by})]
VISIT_SNAP=TIPS("[data-oi-chart-tip]", "[data-oi-stat^='visitors:']")
REF_SNAP=SNAP("[data-oi-table='referred'] tbody > tr[data-oi-data]")
RADIO="css:.m-overview-earnings-table [data-oi-pick='row:%s']"
RADIO_SNAP=TIPS(".m-overview-earnings-table .b-stats-row__label.m-current", None, ".b-chart__double-line__base__wrapper canvas",
                ".m-overview-earnings-table input.b-input-radio:checked")
# Dates stay out of `shows` (the browser's time zone is not pinned, so a midnight-UTC day may read a day earlier).
FANS_READS=[
    # Top fans: each ranking tab reads /top with its `by` and the table follows the answer's order, with that tab's own
    # column (its title in the head) before the total; Fan U leads Subscriptions, Posts and Streams (its $3.00 of
    # each), Fan T Messages ($12.00), Fan E Total (the default, so its row picks Tips first).
    *[{"page":"statistics/fans/top-fans", "steps":[_pick("top", by)], "get":[(TOP, {"by":by})], "settled":TOP_SNAP,
       "shows":[f'"first": "{first}"', f"| {title} |"], "hides":["Synthetic Fan E"] + ([] if by=="messages" else [f'"first": "{FAN_T}'])}
      for by, title, first in (("subscribes", "Subscriptions", f"{FAN_U} | $3.00 | $12.00"), ("messages", "Messages", f"{FAN_T} | $12.00 | $52.00"),
                               ("post", "Posts", f"{FAN_U} | $3.00 | $12.00"), ("streams", "Streams", f"{FAN_U} | $3.00 | $12.00"))],
    {"page":"statistics/fans/top-fans", "steps":[_pick("top", "tips"), _pick("top", "total")], "settled":TOP_SNAP,
     "shows":[f'"first": "{FAN_E} | $12.00"'], "hides":["Synthetic Fan T", "| Tips |"]},
    # Subscriptions: a tab reads the chart and the latest list with its `by`; the summary, the chart (its tooltips) and
    # the list's third column follow it. Renews reads the list reversed (u900011 first, its renew date), New its own
    # rows (Fan D alone, its subscription date; no u900011), each its own chart (2 renews, $19.98, on Oct 1; 1 new,
    # $9.99, on Oct 5); All (the default, picked after Renews) Fan D first with its duration and the 10-subscriber chart.
    {"page":"statistics/fans/subscriptions", "steps":[_pick("subs", "renew")], "get":SUBS_GET("renew"), "settled":SUBS_SNAP,
     "shows":['"first": "u900011 @u900011 | $9.99 | Oct ', "2 Subscribers $19.98", "Renew date",
              "Earnings $19.98 Subscribers 2"], "hides":["Total duration", "Subscribers 1"]},
    {"page":"statistics/fans/subscriptions", "steps":[_pick("subs", "new")], "get":SUBS_GET("new"), "settled":SUBS_SNAP,
     "shows":['"first": "SF Synthetic Fan D @u_synthetic_d | free | ', "1 Subscribers $9.99", "Subscription date",
              "Earnings $9.99 Subscribers 1"], "hides":["Total duration", "$19.98", "u900011", "1 month"]},
    {"page":"statistics/fans/subscriptions", "steps":[_pick("subs", "renew"), _pick("subs", "total")], "settled":SUBS_SNAP,
     "shows":['"first": "SF Synthetic Fan D @u_synthetic_d | free | 1 month"', "10 Subscribers", "Total duration"],
     "hides":["Renew date", "$19.98"]},
    # Profile visitors: a chip reads the stats with its `by` and the visitors chart redraws its series (Guests: 2 on
    # Oct 1; Users: 5 on Oct 5; All, the default, picked after Guests: 64 on Sep 27).
    {"page":"statistics/reach/profile-visitors", "steps":[_pick("visitors", "guests")], "settled":VISIT_SNAP,
     "get":[("/api/of/v2/users/me/profile/stats", {"by":"guests"})], "shows":["Visitors 2 View duration"], "hides":["Visitors 64"]},
    {"page":"statistics/reach/profile-visitors", "steps":[_pick("visitors", "users")], "settled":VISIT_SNAP,
     "get":[("/api/of/v2/users/me/profile/stats", {"by":"users"})], "shows":["Visitors 5 View duration"], "hides":["Visitors 64", "Visitors 2 "]},
    {"page":"statistics/reach/profile-visitors", "steps":[_pick("visitors", "guests"), _pick("visitors", "total")], "settled":VISIT_SNAP,
     "shows":["Visitors 64 View duration 0h:09m"]},
    # Referrals: both kinds are read on load, so no `get`: the shown table is the picked kind's (Referred creators:
    # Synthetic Creator F first; Referred users: the mock's reversed rows, u900010 first); the default tab shows neither.
    {"page":"statistics/statements/referrals/earnings", "steps":[_pick("ref", "creators")], "settled":REF_SNAP,
     "shows":['"first": "SC Synthetic Creator F @u_synthetic_f | '], "hides":['"first": "u900010']},
    {"page":"statistics/statements/referrals/earnings", "steps":[_pick("ref", "users")], "settled":REF_SNAP,
     "shows":['"first": "u900010 @u900010 | '], "hides":['"first": "SC Synthetic Creator F']},
    # Overview › Earnings's category radio: the picked radio is checked and the chart redraws its series in place from
    # the series already loaded, with no Relay request (ticket 16's `get` None: its `hit()` is taken again after the
    # settle polls, over every GET since the last step, so it covers the settle window): Subscriptions draws zeros,
    # Total (the default, picked after Subscriptions) its $20.00 on Sep 27.
    {"page":"statistics/overview/earnings", "steps":[("click", RADIO % "subscribes")], "get":None, "settled":RADIO_SNAP,
     "shows":['"checked": ["subscribes"]', "Subscriptions $0.00"], "hides":["$20.00", "Total "]},
    {"page":"statistics/overview/earnings", "steps":[("click", RADIO % "subscribes"), ("click", RADIO % "total")], "get":None,
     "settled":RADIO_SNAP, "shows":['"checked": ["total"]', "Total $20.00"], "hides":["Subscriptions $0.00"]},
]
# Top fans "Tips" (ticket 13's tracer; ticket 15 owns the page's rows): the v2 mock answers `by=tips` with other rows
# than `by=total`; `shows` is Fan T's row with its Tips column (tipsSumm) and total, `hides` the default's Fan E, so a
# dropped `by` fails on all three.
READS=[
    {"page":"statistics/fans/top-fans", "steps":[("click", "css:[data-oi-pick='top:tips']")],
     "get":[("/api/of/v2/subscriptions/subscribers/top", {"by":"tips"})],
     "settled":SNAP("[data-oi-table='topfans'] tbody > tr"), "shows":["SF Synthetic Fan T @u_synthetic_t | $40.00 | $52.00"],
     "hides":["Synthetic Fan E"]},
    *ENGAGEMENT_READS,  # ticket 14
    *FANS_READS,  # ticket 15
]
