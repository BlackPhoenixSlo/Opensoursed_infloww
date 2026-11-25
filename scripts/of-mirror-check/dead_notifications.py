TABS = ("index", "subscribed", "commented", "mentioned", "tip", "purchases", "favorited", "message", "deactivated_media")
PAGES = [f"notifications/{t}" for t in (*TABS, "tags")]
SEARCH_USERS = "css:.m-notifications-user-search button[aria-label='Search users']"
FORM = "css:[data-oi-notif-search] input[type='search']"
PICK = "css:#oi-notif-users [data-oi-notif-user='9101']"
ASIDE = "css:input[name='feed-search-input']"
NEW_EVENT = "css:button[at-attr='add_event_widget']"


def fan(i):
    return {"id": i, "name": f"Synthetic Fan {i}", "username": f"u_synthetic_{i}", "avatar": None}


def notif(i, day):
    return {"type": "commented", "isRead": True, "createdAt": f"2026-10-{day}T10:00:00", "text": f"Synthetic comment {i}", "user": fan(i)}


V2 = {
    "/api/of/v2/users/notifications": ("related_user", {"list": [notif(9102, 17)], "hasMore": False},
                                       {"9101": {"list": [notif(9101, 18)], "hasMore": False}}),
    "/api/of/v2/users/search": ("q", [], {"synth": [fan(9101), fan(9102)]}),
    "/api/of/v2/posts/search": ("query", [], {"synth": [{"id": 9201, "text": "<p>Synthetic post</p>", "author": fan(9101)}]}),
}
SOURCES = {"/api/of/v2/release-forms/mentions": {"list": [notif(9101, 18), notif(9102, 17)], "hasMore": False}}
PHASE1 = [(p, c, "not-yet") for p in PAGES for c in (SEARCH_USERS, ASIDE, NEW_EVENT)]
SNAP = """() => ({ url: parent.location.pathname + parent.location.search,
  rows: [...document.querySelectorAll('.b-notifications__list .vue-recycle-scroller__item-view')].filter((e) => e.checkVisibility()).map((e) => e.querySelector('.g-user-username')?.textContent.trim() ?? null),
  form: document.querySelector('[data-oi-notif-search] input')?.value ?? null,
  results: [...document.querySelectorAll('#oi-search-results > *')].map((e) => e.textContent.trim()),
  note: document.getElementById('oi-note')?.textContent ?? null })"""
FIND = [("click", SEARCH_USERS), ("fill", FORM, "synth"), ("click", PICK)]


def url(page, query=""):
    tab = page.split("/")[1]
    return "/of-manager/notifications" + ("" if tab == "index" else f"/{tab}") + (f"?{query}" if query else "")


READS = [
    *[{"page": f"notifications/{t}", "steps": FIND,
       "get": [("/api/of/v2/users/notifications", {"related_user": "9101", **({"type": t} if t != "index" else {})})],
       "settled": SNAP, "shows": [f'"url": "{url(f"notifications/{t}", "related_user=9101")}"', '"rows": ["@u_synthetic_9101"]', '"form": "9101"'],
       "hides": ["u_synthetic_9102"]} for t in TABS],
    {"page": "notifications/tags", "steps": FIND, "get": None, "settled": SNAP,
     "shows": ['"url": "/of-manager/notifications/tags?related_user=9101"', '"rows": ["@u_synthetic_9101"]'], "hides": ["u_synthetic_9102"]},
    {"page": "notifications/tip", "steps": [*FIND, ("back", None)], "settled": SNAP,
     "shows": ['"url": "/of-manager/notifications/tip"', '"rows": ["@u_synthetic_9102"]', '"form": null'], "hides": ["u_synthetic_9101"]},
    {"page": "notifications/index", "steps": [("fill", ASIDE, "synth")],
     "get": [("/api/of/v2/users/search", {"q": "synth"}), ("/api/of/v2/posts/search", {"query": "synth"})], "settled": SNAP,
     "shows": ['"results": ["Users", "Synthetic Fan 9101 @u_synthetic_9101", "Synthetic Fan 9102 @u_synthetic_9102", "Posts", "Synthetic post \\u00b7 @u_synthetic_9101"]']},
    {"page": "notifications/index", "steps": [("click", NEW_EVENT)], "settled": SNAP, "shows": ['"url": "/of-manager/home/state-schedule"']},
]
