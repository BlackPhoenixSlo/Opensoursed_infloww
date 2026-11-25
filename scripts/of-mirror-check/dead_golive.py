ALLOWED = set()
ALLOWED_RE = []
MARKED = []
SWEPT = {"streaming/dashboard/create", "streaming/dashboard", "streaming/index"}

SCHEDULE = "streaming/dashboard/create"
SEARCH_BOX, SEARCH_BTN = "input[name='feed-search-input']", "button.m-search-btn"
BOX, BTN = f"css:{SEARCH_BOX}", f"css:{SEARCH_BTN}"
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
    {"page": SCHEDULE, "steps": [("fill", BOX, "synth")], "get": SEARCHED, "settled": SNAP, "shows": [ROWS, LINKS]},
    *[{"page": SCHEDULE, "query": VALID, "steps": [("fill", BOX, "synth"), last], "get": SEARCHED, "settled": SNAP,
       "shows": [ROWS, '"date": "Jan 15, 2030"', '"note": null']} for last in (ENTER, ("click", BTN))],
]

