from dead_lib import SNAP, TIPS, each, fx, hits, rekey, rev, spot, top_by
def _chart_filter(q):
    f=q.get("filter","").split(",")
    return "overview" if "ref_amount" in f else "side" if len(f)>2 else q.get("filter","")
V2={
    "/api/of/v2/streaks/top": (None, fx("streaks-top"), {}),
    "/api/of/v2/earnings/chart": (_chart_filter, [], {"overview":fx("earnings-chart-overview"), "side":fx("earnings-side")}),
    "/api/of/v2/users/me/referrals": ("onlyPerformers", fx("referred-empty"), {"1":fx("referred-creators"),
        "0":rev("referred-creators")}),
    "/api/of/v2/payouts/referrals/chart": (None, fx("referrals-chart-zero"), {}),
    "/api/of/v2/users/me/stats/top/message": (None, fx("top-message"), {}),
    "/api/of/v2/users/me/stats/top/story": (None, fx("top-story"), {}),
    "/api/of/v2/users/me/stats/top/stream": (None, fx("top-stream"), {}),
    "/api/of/v2/users/me/stats/top/fan": (None, fx("top-fan"), {}),
    "/api/of/v2/stories/top": ("by", fx("stories-top"), {"views":fx("stories-top-views"), **each(("likes","comments"), rev("stories-top-views"))}),
    "/api/of/v2/stories/chart": ("by", rekey("stories-chart-views", "views", "tips", 3), {"views":fx("stories-chart-views"),
        "likes":rekey("stories-chart-views", "views", "likes", 5), "comments":rekey("stories-chart-views", "views", "comments", 6)}),
    "/api/of/v2/streams/top": ("by", fx("streams-top"), each(("tips","views","likes","comments"), rev("streams-top"))),
    "/api/of/v2/streams/chart": ("by", fx("streams-chart-zero"), {"tips":fx("streams-chart-tips"),
        **{k: rekey("streams-chart-tips", "tips", k, n) for k, n in (("views", 7), ("likes", 3), ("comments", 2))}}),
    "/api/of/v2/subscriptions/subscribers/top": ("by", fx("subs-top"), each(("subscribes","tips","messages","post","streams"), fx("subs-top-tips"))
        | {k: top_by(f"{k.replace('post', 'posts')}Summ", 3) for k in ("subscribes","post","streams")}),
    "/api/of/v2/subscriptions/subscribers/latest": ("by", fx("subs-latest"), {"renew":rev("subs-latest"),
        "new":{**fx("subs-latest"), "users":fx("subs-latest")["users"][:1]}}),
    "/api/of/v2/subscriptions/subscribers/chart": ("by", fx("subscribers-chart"), {"renew":fx("subs-chart-renew"),
        "new":spot("subs-chart-renew", {"subscribes":("2026-10-05", 1), "earnings":("2026-10-05", 9.99)}, subscribers=1, total=9.99)}),
    "/api/of/v2/users/me/profile/stats": ("by", fx("profile-stats"), {"guests":fx("profile-stats-guests"),
        "users":spot("profile-stats-guests", {"chart.visitors":("2026-10-05", 5)})}),
    "/api/of/v2/users/me/stats/messages/group": ("query", fx("messages-group"), {"message 3":hits("messages-group", "message 3"),
        "me":{**fx("messages-group"), "items":[]}}),
    "/api/of/v2/users/me/stats/messages/direct": (None, fx("messages-direct"), {}),
    "/api/of/v2/messages/queue/chart": ("type", fx("messages-chart-zero"), {"direct":fx("messages-chart-direct")}),
}
PHASE1=[
    ("statistics/fans/top-fans", "css:[data-oi-pick='top:tips']", "pending"),
    *[("statistics/engagement/messages", c, "pending") for c in ("Mass messages", "Direct messages", "Search", "Search messages...")],
    *[("statistics/engagement/stories", c, "pending") for c in ("Tips", "Viewers", "Likes", "Comments")],
    *[("statistics/engagement/streaming", c, "pending") for c in ("Purchases", "Tips", "Viewers", "Likes", "Comments")],
    *[("statistics/fans/subscriptions", f"css:[data-oi-pick='subs:{v}']", "pending") for v in ("total", "renew", "new")],
    *[("statistics/fans/top-fans", f"css:[data-oi-pick='top:{v}']", "pending") for v in ("total", "subscribes", "messages", "post", "streams")],
    *[("statistics/reach/profile-visitors", f"css:[data-oi-pick='visitors:{v}']", "pending") for v in ("total", "guests", "users")],
    *[("statistics/statements/referrals/earnings", f"css:[data-oi-pick='ref:{v}']", "pending") for v in ("creators", "users")],
    ("statistics/overview/earnings", "[b-input-radio]", "pending"),
]
MSG_SNAP=SNAP(".b-statements-table tbody > tr[data-oi-data]", "[data-oi-stat^='messages:massMessages']")
MSG_SEARCH="css:[data-oi-search] input[type='search']"
MSG_BUTTON="css:[data-oi-search] button[type='submit']"
MSG_GROUP, MSG_DIRECT="/api/of/v2/users/me/stats/messages/group", "/api/of/v2/users/me/stats/messages/direct"
MSG_ALL=["Synthetic mass message 1", "Synthetic mass message 2", "Synthetic mass message 3"]
def _list_reads(page, kind, tabs, default):
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
S58001, S58011="Viewers 4 Likes 2 Comments 1 Tips 0 ($0.00)", "Viewers 9 Likes 3 Comments 2 Tips 0 ($0.00)"
S57001, S57002="Viewers 2 ($0.00) Likes 1 Comments 0 Tips 1 ($5.00)", "Viewers 0 ($0.00) Likes 0 Comments 0 Tips 0 ($0.00)"
def _msg(steps, **row): return {"page":"statistics/engagement/messages", "steps":steps, "settled":MSG_SNAP, **row}
ENGAGEMENT_READS=[
    _msg([("click", "css:[data-oi-pick='msg:direct']")], all=True,
         get=[(MSG_DIRECT, {}), ("/api/of/v2/messages/queue/chart", {"type":"direct"})],
         shows=["Synthetic direct message", "$9.98"], hides=["Synthetic mass message 1"]),
    _msg([("click", "css:[data-oi-pick='msg:direct']"), ("click", "css:[data-oi-pick='msg:group']")],
         shows=["Synthetic mass message 1"], hides=["Synthetic direct message", "$9.98"]),
    *[_msg(steps, get=[(MSG_GROUP, {"query":"message 3"})], shows=["Synthetic mass message 3"], hides=MSG_ALL[:2])
      for steps in ([("fill", MSG_SEARCH, "message 3")],
                    [("set", MSG_SEARCH, "message 3"), ("press", MSG_BUTTON, "Enter")])],
    *[_msg(steps, shows=["Synthetic mass message 3"], hides=MSG_ALL[:2])
      for steps in ([("fill", MSG_SEARCH, "message 3"), ("fill", MSG_SEARCH, "me")],
                    [("fill", MSG_SEARCH, "message 3"), ("set", MSG_SEARCH, "me"), ("press", MSG_BUTTON, "Enter")])],
    *[_msg(steps, shows=MSG_ALL)
      for steps in ([("fill", MSG_SEARCH, "message 3"), ("fill", MSG_SEARCH, "")],
                    [("fill", MSG_SEARCH, "message 3"), ("set", MSG_SEARCH, ""), ("press", MSG_BUTTON, "Enter")])],
    *_list_reads("statistics/engagement/stories", "stories", {
        "tips": (S58001, "$3.00"), "views": (S58011, "4 viewers"), "likes": (S58001, "5 likes"), "comments": (S58001, "6 comments")}, "tips"),
    *_list_reads("statistics/engagement/streaming", "streams", {
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
FANS_READS=[
    *[{"page":"statistics/fans/top-fans", "steps":[_pick("top", by)], "get":[(TOP, {"by":by})], "settled":TOP_SNAP,
       "shows":[f'"first": "{first}"', f"| {title} |"], "hides":["Synthetic Fan E"] + ([] if by=="messages" else [f'"first": "{FAN_T}'])}
      for by, title, first in (("subscribes", "Subscriptions", f"{FAN_U} | $3.00 | $12.00"), ("messages", "Messages", f"{FAN_T} | $12.00 | $52.00"),
                               ("post", "Posts", f"{FAN_U} | $3.00 | $12.00"), ("streams", "Streams", f"{FAN_U} | $3.00 | $12.00"))],
    {"page":"statistics/fans/top-fans", "steps":[_pick("top", "tips"), _pick("top", "total")], "settled":TOP_SNAP,
     "shows":[f'"first": "{FAN_E} | $12.00"'], "hides":["Synthetic Fan T", "| Tips |"]},
    {"page":"statistics/fans/subscriptions", "steps":[_pick("subs", "renew")], "get":SUBS_GET("renew"), "settled":SUBS_SNAP,
     "shows":['"first": "u900011 @u900011 | $9.99 | Oct ', "2 Subscribers $19.98", "Renew date",
              "Earnings $19.98 Subscribers 2"], "hides":["Total duration", "Subscribers 1"]},
    {"page":"statistics/fans/subscriptions", "steps":[_pick("subs", "new")], "get":SUBS_GET("new"), "settled":SUBS_SNAP,
     "shows":['"first": "SF Synthetic Fan D @u_synthetic_d | free | ', "1 Subscribers $9.99", "Subscription date",
              "Earnings $9.99 Subscribers 1"], "hides":["Total duration", "$19.98", "u900011", "1 month"]},
    {"page":"statistics/fans/subscriptions", "steps":[_pick("subs", "renew"), _pick("subs", "total")], "settled":SUBS_SNAP,
     "shows":['"first": "SF Synthetic Fan D @u_synthetic_d | free | 1 month"', "10 Subscribers", "Total duration"],
     "hides":["Renew date", "$19.98"]},
    {"page":"statistics/reach/profile-visitors", "steps":[_pick("visitors", "guests")], "settled":VISIT_SNAP,
     "get":[("/api/of/v2/users/me/profile/stats", {"by":"guests"})], "shows":["Visitors 2 View duration"], "hides":["Visitors 64"]},
    {"page":"statistics/reach/profile-visitors", "steps":[_pick("visitors", "users")], "settled":VISIT_SNAP,
     "get":[("/api/of/v2/users/me/profile/stats", {"by":"users"})], "shows":["Visitors 5 View duration"], "hides":["Visitors 64", "Visitors 2 "]},
    {"page":"statistics/reach/profile-visitors", "steps":[_pick("visitors", "guests"), _pick("visitors", "total")], "settled":VISIT_SNAP,
     "shows":["Visitors 64 View duration 0h:09m"]},
    {"page":"statistics/statements/referrals/earnings", "steps":[_pick("ref", "creators")], "settled":REF_SNAP,
     "shows":['"first": "SC Synthetic Creator F @u_synthetic_f | '], "hides":['"first": "u900010']},
    {"page":"statistics/statements/referrals/earnings", "steps":[_pick("ref", "users")], "settled":REF_SNAP,
     "shows":['"first": "u900010 @u900010 | '], "hides":['"first": "SC Synthetic Creator F']},
    {"page":"statistics/overview/earnings", "steps":[("click", RADIO % "subscribes")], "get":None, "settled":RADIO_SNAP,
     "shows":['"checked": ["subscribes"]', "Subscriptions $0.00"], "hides":["$20.00", "Total "]},
    {"page":"statistics/overview/earnings", "steps":[("click", RADIO % "subscribes"), ("click", RADIO % "total")], "get":None,
     "settled":RADIO_SNAP, "shows":['"checked": ["total"]', "Total $20.00"], "hides":["Subscriptions $0.00"]},
]
READS=[
    {"page":"statistics/fans/top-fans", "steps":[("click", "css:[data-oi-pick='top:tips']")],
     "get":[("/api/of/v2/subscriptions/subscribers/top", {"by":"tips"})],
     "settled":SNAP("[data-oi-table='topfans'] tbody > tr"), "shows":["SF Synthetic Fan T @u_synthetic_t | $40.00 | $52.00"],
     "hides":["Synthetic Fan E"]},
    *ENGAGEMENT_READS,
    *FANS_READS,
]
