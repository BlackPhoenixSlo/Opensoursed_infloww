"""dead.py's ticket 17 rows (imported by dead.py, which they would push past 1000 lines): Notifications' Search users,
the aside's Search users or posts and the Scheduled events widget's new-event button, on every tab (spec stories 15,
16, 18). Data only: PHASE1, READS, SOURCES and V2 entries in dead.py's shapes (see its PHASE1 and READS notes).

Their PHASE1 rows are "not-yet" (D1: each title stays until the control's Live proof). The mocks: the type tabs'
`/users/notifications` answers fan 9102's notification and, for `related_user=9101`, fan 9101's only, so a dropped
param shows no 9101 row (relatedOnly filters 9102's out); Tags' `/release-forms/mentions` answers both fans' (no param
there: Search filters the rows read, so its row asserts no GET at all); the users and posts searches answer only
"synth".
"""
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
# The tab's rows (each its @handle), the page URL, the open Search users form's text and the note.
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
    # Search users on a type tab: the pick re-reads the tab for fan 9101 (related_user, the tab's own type kept).
    *[{"page": f"notifications/{t}", "steps": FIND,
       "get": [("/api/of/v2/users/notifications", {"related_user": "9101", **({"type": t} if t != "index" else {})})],
       "settled": SNAP, "shows": [f'"url": "{url(f"notifications/{t}", "related_user=9101")}"', '"rows": ["@u_synthetic_9101"]', '"form": "9101"'],
       "hides": ["u_synthetic_9102"]} for t in TABS],
    # Tags: the pick filters the mentions read on load, with no GET at all.
    {"page": "notifications/tags", "steps": FIND, "get": None, "settled": SNAP,
     "shows": ['"url": "/of-manager/notifications/tags?related_user=9101"', '"rows": ["@u_synthetic_9101"]'], "hides": ["u_synthetic_9102"]},
    # Back after a search: the tab as it was (fan 9102's row, no fan in the URL, the form closed).
    {"page": "notifications/tip", "steps": [*FIND, ("back", None)], "settled": SNAP,
     "shows": ['"url": "/of-manager/notifications/tip"', '"rows": ["@u_synthetic_9102"]', '"form": null'], "hides": ["u_synthetic_9101"]},
    # The aside's search: both searches, both kinds listed.
    {"page": "notifications/index", "steps": [("fill", ASIDE, "synth")],
     "get": [("/api/of/v2/users/search", {"q": "synth"}), ("/api/of/v2/posts/search", {"query": "synth"})], "settled": SNAP,
     "shows": ['"results": ["Users", "Synthetic Fan 9101 @u_synthetic_9101", "Synthetic Fan 9102 @u_synthetic_9102", "Posts", "Synthetic post \\u00b7 @u_synthetic_9101"]']},
    # The new-event button: Home's Schedule post state, nothing sent (the check's writes []).
    {"page": "notifications/index", "steps": [("click", NEW_EVENT)], "settled": SNAP, "shows": ['"url": "/of-manager/home/state-schedule"']},
]
