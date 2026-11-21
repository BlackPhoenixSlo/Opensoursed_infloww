"""dead.py's ticket 83 hooks (loaded by dead.py's MODULES, as dead_collections.py is): Phase 4's schedule form, dashboard and Go
live (docs/spec/ofm-not-yet/phase-04-go-live.md). Data only, in dead.py's shapes: ALLOWED ({(method, path)}),
ALLOWED_RE ([(method, regex)]: an id in the path) and MARKED ([(pages fn, selector, shown only, count)]).
Each Phase 4 control ticket appends its writes and Wired controls here in its own `# ticket NN` block (ticket 84: the schedule form's search).

SWEPT: the three pages stay swept while their tickets wire them; dead.py checks it against its page list (Go live's controls stay pinned until track B's gate ticket closes, D7).
"""
ALLOWED = set()
ALLOWED_RE = []
MARKED = []
SWEPT = {"streaming/dashboard/create", "streaming/dashboard", "streaming/index"}

# ticket 84: the schedule form's right column search (Home's, bindFeedSearch), in dead.py's PHASE1 and READS shapes too.
# The box and its Search button are Wired (MARKED) and keep the Not-yet title (PHASE1 "not-yet", D1). READS answer from
# dead_notifications.py's users and posts search mocks (V2 is one namespace: "synth" only); each row checks no Relay
# write (no POST /streams). The Enter and Search rows open the form valid (the Queue's ?date=&time= prefill, a
# far-future day).
SCHEDULE = "streaming/dashboard/create"
SEARCH_BOX, SEARCH_BTN = "input[name='feed-search-input']", "button.m-search-btn"
BOX, BTN = f"css:{SEARCH_BOX}", f"css:{SEARCH_BTN}"
# Enter goes to the same box, named by a second selector: read_step checks a PHASE1 "not-yet" control's title before
# each of its steps, and the fill step's un-grey has already taken it off, so the title is checked once, on the bare load.
ENTER = ("press", f"css:form {SEARCH_BOX}", "Enter")
VALID = "date=2030-01-15&time=18:30"
SEARCHED = [("/api/of/v2/users/search", {"q": "synth"}), ("/api/of/v2/posts/search", {"query": "synth"})]
ROWS = ('"results": ["Users", "Synthetic Fan 9101 @u_synthetic_9101", "Synthetic Fan 9102 @u_synthetic_9102", "Posts", '
        '"Synthetic post \\u00b7 @u_synthetic_9101"]')
LINKS = ('"links": ["https://onlyfans.com/u_synthetic_9101", "https://onlyfans.com/u_synthetic_9102", '
         '"https://onlyfans.com/u_synthetic_9101"]')
SNAP = """() => ({ results: [...document.querySelectorAll('#oi-search-results > *')].map((e) => e.textContent.trim()),
  links: [...document.querySelectorAll('#oi-search-results a')].map((a) => a.getAttribute('href')),
  date: document.querySelector("input[name='date']")?.value ?? null,
  note: document.getElementById('oi-note')?.textContent ?? null })"""
MARKED += [(lambda p: p == SCHEDULE, SEARCH_BOX, False, 1), (lambda p: p == SCHEDULE, SEARCH_BTN, False, 1)]
PHASE1 = [(SCHEDULE, BOX, "not-yet"), (SCHEDULE, BTN, "not-yet")]
READS = [
    # Typing: both searches, both kinds listed, each row linking to its OF profile (Home's links).
    {"page": SCHEDULE, "steps": [("fill", BOX, "synth")], "get": SEARCHED, "settled": SNAP, "shows": [ROWS, LINKS]},
    # Enter in the box and the Search button, a valid date filled: the search runs at once, nothing is scheduled.
    *[{"page": SCHEDULE, "query": VALID, "steps": [("fill", BOX, "synth"), last], "get": SEARCHED, "settled": SNAP,
       "shows": [ROWS, '"date": "Jan 15, 2030"', '"note": null']} for last in (ENTER, ("click", BTN))],
]

