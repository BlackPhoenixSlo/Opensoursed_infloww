"""dead.py's Home rows (ticket 30; dead.py's MODULES): Record video and Record voice on Home, Wired (MARKED),
"proven" on Home and New post (PHASE1; ticket 53); ticket 19: Pin to home's lists and Sort
(PHASE1, READS)."""
from dead_lib import READ_ONLY
MARKED=[
    # ticket 30
    # Record video and Record voice on Home and its State pages (ofMirrorPost, the chat composer's recorders); New post's
    # entry in dead.py's MARKED now marks the same recorders (its popup is gone).
    (lambda p: p.startswith("home/"), "button[aria-label='Record video'], button[aria-label='Record voice']", False, 2),
]
# ticket 19
# Pin to home (home/state-feed-tabs-edit, the feed tabs' pencil, sitting r5/r6): its rows are the Creator's lists from
# the Relay's /lists read (dead_collections' mock: Synthetic list Empty 7000, Alpha 7001, Bravo 7002); its Sort ("not-yet":
# the title stays until the Live pass, D1) orders them client-side, each pick a navigation to the dialog in that sort
# (?fsort=&forder=), no GET, no write. Custom (the default) keeps the read's order; Recent is by id; Name by name. People
# is vitest's (the mock's lists all have usersCount 0, and it is dead_collections'). A row's tick is the Read-only note
# (the pin stays Phase 2's).
PIN19="home/state-feed-tabs-edit"
SORT19="css:.modal button[aria-label='Sort']"
ROW19="css:.modal label.b-rows-lists__item[data-oi-list]"
SNAP19="""() => ({
  url: parent.location.pathname + parent.location.search,
  rows: [...document.querySelectorAll('.modal label.b-rows-lists__item[data-oi-list]')].filter(r => r.checkVisibility())
    .map(r => r.querySelector('.b-rows-lists__item__name').textContent.trim().replace('Synthetic list ', '')).join(' > '),
  note: document.getElementById('oi-note')?.textContent ?? null })"""
# ticket 53
# Record video and Record voice: "proven" (D1: the title dropped on their Live pass, p2.record-video and p2.record-voice,
# docs/of-manager/captures/home--record-video.json and home--record-voice.json), on every page those records list (Home
# and its State pages, New post and its State pages; ofMirrorPost's one binder). New post's never carried the title.
# New message's list page keeps its titled recorders (dead_content.py: ofMirrorChatShared's, no Live pass).
RECORD53="css:button[aria-label='Record video'], button[aria-label='Record voice']"
RECORD53_PAGES=[f"home/{p}" for p in ("index", "state-avatar-menu", "state-expiration", "state-feed-tabs-edit", "state-format-text",
                                       "state-poll", "state-promotion", "state-quiz", "state-schedule", "state-tag-people",
                                       "state-target", "state-vault")] + \
               [f"new-post/{p}" for p in ("index", "state-expiration", "state-format-text", "state-labels", "state-poll",
                                           "state-price", "state-promotion", "state-quiz", "state-schedule", "state-tag-people",
                                           "state-target", "state-trial-link", "state-vault")]
PHASE1=[(PIN19, SORT19, "not-yet"), *((p, RECORD53, "proven") for p in RECORD53_PAGES)]
READS=[
    # The pencil opens the dialog: one /lists read, one row per list.
    {"page":"home/index", "steps":[("click", "css:a.b-tabs__nav__link[href='/of-manager/home/state-feed-tabs-edit']")],
     "get":[("/api/of/v2/lists", {"limit":"50"})], "settled":SNAP19,
     "shows":[f'"url": "/of-manager/{PIN19}"', '"rows": "Empty > Alpha > Bravo"']},
    *[{"page":PIN19, "query":query, "steps":[("click", SORT19), ("click", f"css:#oi-menu [data-oi-value='{pick}']")],
       "get":None, "settled":SNAP19, "shows":[f'"url": "/of-manager/{PIN19}{url}"', f'"rows": "{want}"'], "hides":[f'"rows": "{was}"']}
      for query, pick, url, want, was in [
          ("", "recent", "?fsort=recent&forder=desc", "Bravo > Alpha > Empty", "Empty > Alpha > Bravo"),
          ("", "name", "?fsort=name&forder=desc", "Empty > Bravo > Alpha", "Empty > Alpha > Bravo"),
          ("fsort=name&forder=asc", "custom", "?fsort=custom&forder=asc", "Empty > Alpha > Bravo", "Alpha > Bravo > Empty"),
          ("fsort=recent&forder=desc", "asc", "?fsort=recent&forder=asc", "Empty > Alpha > Bravo", "Bravo > Alpha > Empty")]],
    # A row's tick: the Read-only note, no write.
    {"page":PIN19, "steps":[("click", ROW19)], "get":None, "settled":SNAP19, "shows":[f'"note": "{READ_ONLY}"']},
]
