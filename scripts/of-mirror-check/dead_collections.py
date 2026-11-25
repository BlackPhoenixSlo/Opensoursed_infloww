POSTS = "css:button.b-tabs__nav__link.m-tb-sm"
SEARCH = "css:button[aria-label='Search users']"
SEARCH_IN = "css:#oi-users-search input"
FANS = "collections/user-lists/subscribers/active"
POSTS_PAGE = "/of-manager/collections/user-lists/list/posts"


def lst(i, name):
    return {"id": i, "type": "custom", "name": name, "usersCount": 0, "postsCount": 1}


def post(i, text):
    return {"id": i, "text": f"<p>{text}</p>", "rawText": text, "postedAt": "2026-10-10T12:00:00+00:00", "media": [], "author": {"id": 1}}


def fan(i):
    return {"id": i, "name": f"Synthetic Fan {i}", "username": f"u_synthetic_{i}"}


SOURCES = {"/api/of/v2/lists": {"list": [lst(7000, "Synthetic list Empty"), lst(7001, "Synthetic list Alpha"), lst(7002, "Synthetic list Bravo")],
                                "hasMore": False},
           **{f"/api/of/v2/lists/{lid}/posts": {"list": [post(7101 + n, f"Synthetic {word} post")], "hasMore": False}
              for n, (lid, word) in enumerate((("7001", "Alpha"), ("7002", "Bravo"), ("fans", "Fans")))}}
V2 = {
    "/api/of/v2/lists/7001/users": ("query", [fan(2001), fan(2002)], {"bravo": [fan(2002)]}),
    "/api/of/v2/subscribers": ("type", [], {"active": [fan(2001), fan(2002)], "expired": [fan(2003)]}),
}
PHASE1 = [("collections/index", POSTS, "not-yet"), (FANS, POSTS, "not-yet"), (FANS, "Expired", "not-yet"),
          ("collections/index", SEARCH, "pending"), ("collections/user-lists/list", SEARCH, "pending")]
SNAP = """() => {
  const t = (e) => e.textContent.replace(/\\s+/g, ' ').trim();
  const v = (sel) => [...document.querySelectorAll(sel)].filter((e) => e.checkVisibility());
  return { url: parent.location.pathname + parent.location.search,
    current: v('.l-main-content.m-r-side .b-tabs__nav__link.m-current').map(t),
    note: document.getElementById('oi-note')?.textContent ?? null,
    posts: v('.l-main-content.m-r-side .g-page-content__body .vue-recycle-scroller__item-wrapper > [data-oi-data] .b-post__text').map(t),
    users: v('.b-users__item .g-user-username').map(t) };
}"""
FIND = [("click", SEARCH), ("fill", SEARCH_IN, "bravo"), ("press", SEARCH_IN, "Enter")]
READS = [
    *[{"page": page, "query": query, "steps": [("click", POSTS)], "get": [(f"/api/of/v2/lists/{lid}/posts", {})], "settled": SNAP,
       "shows": [f'"url": "{POSTS_PAGE}?list={lid}"', f'"posts": ["Synthetic {word} post"]'], "hides": [f"Synthetic {o} post" for o in others]}
      for page, query, lid, word, others in [("collections/index", "list=7001", "7001", "Alpha", ("Bravo", "Fans")),
                                             ("collections/index", "list=7002", "7002", "Bravo", ("Alpha", "Fans")),
                                             (FANS, "", "fans", "Fans", ("Alpha", "Bravo"))]],
    {"page": FANS, "steps": [("click", "Expired")], "get": [("/api/of/v2/subscribers", {"type": "expired"})], "settled": SNAP,
     "shows": [f'"url": "/of-manager/{FANS}?type=expired"', '"Expired"', '"users": ["@u_synthetic_2003"]'], "hides": ['"Active"', "@u_synthetic_2001"]},
    {"page": FANS, "steps": [("click", "Expired"), ("back", None)], "settled": SNAP,
     "shows": [f'"url": "/of-manager/{FANS}"', '"Active"', '"users": ["@u_synthetic_2001", "@u_synthetic_2002"]'], "hides": ["@u_synthetic_2003"]},
    *[row for page, href in [("collections/index", "/of-manager/collections"), ("collections/user-lists/list", "/of-manager/collections/user-lists/list")]
      for row in (
          {"page": page, "query": "list=7001", "steps": FIND, "get": [("/api/of/v2/lists/7001/users", {"query": "bravo"})], "settled": SNAP,
           "shows": [f'"url": "{href}?list=7001&query=bravo"', '"users": ["@u_synthetic_2002"]'], "hides": ["@u_synthetic_2001"]},
          {"page": page, "query": "list=7001&query=bravo", "steps": [("fill", SEARCH_IN, ""), ("press", SEARCH_IN, "Enter")],
           "get": [("/api/of/v2/lists/7001/users", {})], "settled": SNAP,
           "shows": [f'"url": "{href}?list=7001"', '"users": ["@u_synthetic_2001", "@u_synthetic_2002"]']},
          {"page": page, "query": "list=7001", "steps": [*FIND, ("back", None)], "settled": SNAP,
           "shows": [f'"url": "{href}?list=7001"', '"users": ["@u_synthetic_2001", "@u_synthetic_2002"]']})],
]
