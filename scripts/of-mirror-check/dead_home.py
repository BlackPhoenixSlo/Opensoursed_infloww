from dead_lib import READ_ONLY
MARKED=[
    (lambda p: p.startswith("home/"), "button[aria-label='Record video'], button[aria-label='Record voice']", False, 2),
]
PIN19="home/state-feed-tabs-edit"
SORT19="css:.modal button[aria-label='Sort']"
ROW19="css:.modal label.b-rows-lists__item[data-oi-list]"
SNAP19="""() => ({
  url: parent.location.pathname + parent.location.search,
  rows: [...document.querySelectorAll('.modal label.b-rows-lists__item[data-oi-list]')].filter(r => r.checkVisibility())
    .map(r => r.querySelector('.b-rows-lists__item__name').textContent.trim().replace('Synthetic list ', '')).join(' > '),
  note: document.getElementById('oi-note')?.textContent ?? null })"""
RECORD53="css:button[aria-label='Record video'], button[aria-label='Record voice']"
RECORD53_PAGES=[f"home/{p}" for p in ("index", "state-avatar-menu", "state-expiration", "state-feed-tabs-edit", "state-format-text",
                                       "state-poll", "state-promotion", "state-quiz", "state-schedule", "state-tag-people",
                                       "state-target", "state-vault")] + \
               [f"new-post/{p}" for p in ("index", "state-expiration", "state-format-text", "state-labels", "state-poll",
                                           "state-price", "state-promotion", "state-quiz", "state-schedule", "state-tag-people",
                                           "state-target", "state-trial-link", "state-vault")]
PHASE1=[(PIN19, SORT19, "not-yet"), *((p, RECORD53, "proven") for p in RECORD53_PAGES)]
READS=[
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
    {"page":PIN19, "steps":[("click", ROW19)], "get":None, "settled":SNAP19, "shows":[f'"note": "{READ_ONLY}"']},
]
