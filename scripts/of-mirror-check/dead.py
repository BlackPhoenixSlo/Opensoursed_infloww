"""No Silent control: every visible, enabled control on the signed-off Mirror pages answers a click (Phase 6).

Pages: every page of new-post, home, streaming, profile, queue, collections, notifications, statements, statistics, messages, vault, bank
and settings with their tabs, modals and states, read from app/lib/of-mirror-pages.ts (arguments: only the pages named, or under a
named prefix, e.g. `queue` or `new-post/state-vault`). sessionStorage is cleared before each page.
Mocks the login (as writes.py), GET /api/of/v2/users/me (synthetic), GET /posts/tagged-friend-users and GET /vault/media
(one synthetic "Alpha One" row each), a v2 Relay for Statistics (V2: the probe /streaks/top as an object and every source a
Phase 1 tab gates on in its real shape, from app/lib/__fixtures__/of/statistics-*.json, another tab's param value answering
other rows), GET /img (a 1x1 PNG built by this script), the OFM_NEW_WRITES_ENABLED probe GET /api/of/ofm-writes answered
on (the tables hold the switch-gated controls Wired, as of-live-proof runs the Relay; their switch-off state is
phase_check.py's `ofm_new_writes` pass and vitest's) and [] for every other GET /api/**; every GET /api/** is recorded
(path, query, X-Account-Id); every non-GET /api/** is recorded (method, path, X-Account-Id, body) and answered 200 {}.
Any request to a host other than localhost is aborted and fails the check.
Phase 1 (Single Creator): each PHASE1 row's control is found on its page, and a "proven" one is Wired with no Not-yet
title; each READS row, on a fresh load with its controls un-greyed by the check, makes its GETs with their params, settles
(the same snapshot over consecutive polls) to what only the filtered answer shows and not what only the default shows,
and writes nothing (see PHASE1 and READS). A row whose page the sweep never opens fails up front.
Single Creator (scope `model:1`): the frame's visible, enabled button, [role=button] and input[type=checkbox] (not inside
.video-js; a hidden checkbox through its visible label) are clicked one by one with the mouse at their centre, so whatever
lies on top (a State page backdrop) takes the click as it would the operator's; a control under anything else (a page
layer, a modal) or out of reach (OF's recycled feed views) is listed as skipped. Marked means as bindWrites reads it: a
checkbox inside [data-oi-wired], a button with the mark on it or on a part of it. Before each click #oi-note is removed;
then for 1s the first outcome is taken: a Relay write, a file chooser or download, a top-URL change, a fresh #oi-note, or (a marked
control) a change to its own markup, checked state, ancestors' classes, the size of its dialog, poll panel or form, or the
queue date beside it, or focus moved to a [data-oi-wired] text field outside it (Release forms' filter Search). After a navigation or a write the page is
loaded again and the sweep goes on with the next control.
- An unmarked control must give the Read-only note or a navigation to a localhost /of-manager/ URL.
- A control in a[href] (a link, a State page opener or backdrop) must navigate to a localhost /of-manager/ URL, or stay
  inert when its href is # or the page itself; it never shows a note.
- A [data-oi-wired] control must give an allow-listed write, a navigation, a file chooser, a change to its own markup,
  focus moved to a Wired field outside it, or a note that is not the Read-only note; the queue calendar's selected day may stay inert (it already shows that day).
  Its centre must be its own (elementFromPoint): one under a State page's backdrop with no dialog, menu or focused
  field open over it fails, as the operator's click would go back instead (Home's poll page once sent Post's click to
  Home, and nothing posted).
- An open State menu's items (each scrolled into view) are over the page's backdrop: none has its centre on it (My
  profile's More menu lay under it, so Statistics and Copy link went back to the profile).
- No Relay write from an unmarked control; no write off the allow-list (POST /api/of/v2/posts, /upload, /stories/upload,
  /campaigns, /trials, /promotions, /streams; the settings saves: PATCH /users/me, /users/me/reply-on-subscribe,
  /users/me/settings/security, /users/settings/notifications, /users/settings/story, PUT /users/me/settings/security).
  Each Phase's control tickets add their writes to ALLOWED or ALLOWED_RE (an id in the path), their Wired controls to
  MARKED, each from its area module (dead_<area>.py, MODULES). Phase 3 adds HANDOFF: a popup to an
  allow-listed hand-off URL (aborted, never loaded) is a Wired control's or link's outcome, and those hand-off links
  are swept too (ticket 57).
- The controls with no Known body (DISABLED; none left: the promotion modal's "Start campaign", the bundle modal's "Save"
  and the trial modal's "Create link" send OF's own bodies) are disabled with the tooltip "Not available in Inflowwww yet".
- The plan's measured Wired controls (Ground truth 5) carry data-oi-wired on the pages that bind them.
- No console errors.
No All-Creators pass: OF Manager has no All creators (owner 2026-11-20, OneCreator in
app/components/of-manager/OfManagerChrome.tsx); phase_check.py's one_creator checks a saved "all" scope shows one creator.
Prints one {"check","want","got"} line per check, one {scope, page, controls, links, wired, readonly} line per page and
one {scope, pages, controls, links, wired, readonly} line per pass.
Screenshots (the page's first note showing): /tmp/of-mirror-shots/inapp-dead-<page>.png. Exit 1 on a failed check.
--sweep-out <file> (anywhere among the arguments): the same run, with release-forms added to the sections, also writes the
Not-yet sweep of the Single-Creator pass to <file>: [[page, {"ny", "dis", "ro"}]] per swept page, `ny` the visible controls
with the Not-yet title and `dis` the visible disabled ones without it (each label once, as the page opens), `ro` one entry
per control that gave the Read-only note (as many as the page's printed readonly count). A label is the control's
aria-label, text or placeholder (60 characters), with a date "Mon D, YYYY" read as {date}, else [its first two classes],
else [its tag]. In this mode a page that ends with no frame (NO IFRAME) is opened once more before it counts.
sweep_diff.py compares two such files.
"""
import importlib, json, os, re, struct, sys, zlib
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import Error as PwError, sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sweep_diff import LABEL_JS  # noqa: E402  (the sweep's label, shared with phase_check.py)
from dead_lib import READ_ONLY, ROOT  # noqa: E402  (shared with the area modules, MODULES)
ARGS=sys.argv[1:]
SWEEP_OUT=None
if "--sweep-out" in ARGS:
    _i=ARGS.index("--sweep-out")
    SWEEP_OUT=ARGS[_i+1]
    del ARGS[_i:_i+2]
LIST_ROWS="--list-rows" in ARGS   # print the loaded tables' rows and counts, start no browser
if LIST_ROWS: ARGS.remove("--list-rows")
BASE=f"http://localhost:{os.environ.get('PORT','3091')}"
M="/of-manager"
SHOTS="/tmp/of-mirror-shots"
os.makedirs(SHOTS, exist_ok=True)
user={"user_id":"u1","username":"tester","is_admin":False}
ALLOWED={("POST",f"/api/of/v2/{p}") for p in ("posts","upload","stories/upload","campaigns","trials","promotions","streams",
    "subscriptions/bundles","trials/share-access","labels","labels/sort","guests")} | {
    ("PATCH",f"/api/of/v2/{p}") for p in ("users/me","users/me/reply-on-subscribe","users/me/settings/security","users/settings/notifications","users/settings/story",
    "release-forms/toggle-show")} | {
    ("PUT","/api/of/v2/users/me/settings/security")}
# The allow-list's rows with an id in the path, (method, full-match regex): a running promotion's Stop promotion
# (ofMirrorOffers), POST /promotions/<id>/finish. Each Phase's control tickets add their writes to ALLOWED or here,
# their Wired controls to MARKED, from their area module (MODULES below;
# docs/spec/ofm-not-yet/phase-02-content-chat-writes.md, Testing Decisions, dead.py).
ALLOWED_RE=[("POST", re.compile(r"/api/of/v2/promotions/\d+/finish"))]
NOT_YET="Not available in Inflowwww yet"
# Submits with no Known body, disabled with the tooltip: none left (the promotion, bundle and free trial link dialogs send
# OF's own bodies through ofMirrorOffers).
DISABLED=[]
LOCAL=("localhost","127.0.0.1")
SOURCES={
    "/api/of/ofm-writes": {"on": True},   # OFM_NEW_WRITES_ENABLED on (docstring)
    "/api/of/v2/users/me": {"id":1,"username":"alphaone","name":"Alpha One"},
    "/api/of/v2/posts/tagged-friend-users": {"items":[{"id":901,"name":"Alpha One","type":"user","user":{"id":901,"name":"Alpha One","username":"alphaone"}}],"hasMore":False},
    "/api/of/v2/vault/media": {"list":[{"id":61,"type":"photo","createdAt":"2026-10-10T12:00:00Z","files":{"thumb":{"url":"https://cdn.example.invalid/v61.jpg"}}}],"hasMore":False},
}
# The v2 Relay mock: path -> (param, or a function of the query; the default body; {param value: its body}). Its rows
# live in the area modules (dead_statistics.py: the Statistics sources and the probe /streaks/top).
V2={}
def v2_body(path, query):
    """The v2 mock's body for a GET (None: not a v2 source; the usual [] then)."""
    if path not in V2: return None
    param, default, other=V2[path]
    q={k: v[0] for k, v in parse_qs(query).items()}
    value=param(q) if callable(param) else q.get(param) if param else None
    return other.get(value, default)
# Ground truth 5's Wired controls, by the pages whose binder marks them: (pages, selector, shown matches only, how many).
# The offer dialogs' submits (ofMirrorOffers) are marked like the tracking link's.
MARKED=[
    (lambda p: p.startswith("new-post/") or p.startswith("home/"), "button[at-attr='submit_post']", False, 1),
    (lambda p: p.startswith("new-post/") or p=="home/index", "[aria-label='Add media']", False, 1),
    (lambda p: p.split("/")[0] in ("home","new-post"), ".b-story-item.m-story-item-own", False, 1),
    (lambda p: p in ("new-post/state-vault","home/state-vault"), "input[name='media_vault_search']", False, 1),
    (lambda p: p in ("new-post/state-vault","home/state-vault"), ".b-photos .b-photos__item", True, 1),
    (lambda p: p in ("new-post/state-tag-people","home/state-tag-people"), "label.b-rows-lists__item", True, 1),
    (lambda p: p in ("new-post/state-schedule","home/state-schedule"), ".vdatetime-popup__actions__button--confirm button", False, 1),
    (lambda p: p=="messages/chat" or p.startswith("messages/chat/state-"), "[aria-label='Add media']", False, 1),
    (lambda p: p=="messages/chat/state-vault", "input[name='media_vault_search']", False, 1),
    (lambda p: p=="settings/subscription/tracking-links/modal-1", ".modal-footer button[type='submit']", False, 1),
    (lambda p: p in ("settings/subscription/promotion-campaign/modal-1","settings/subscription/trial-links/modal-1",
                     "new-post/state-promotion","new-post/state-trial-link","home/state-promotion"), ".modal-footer button[type='submit']", False, 1),
    (lambda p: p.startswith("new-post/"), "button[aria-label='Record video'], button[aria-label='Record voice']", False, 2),
    (lambda p: p.startswith("new-post/"), "input[name='feed-search-input']", False, 1),
    (lambda p: p=="streaming/dashboard/create", ".g-page__header > button.g-btn", False, 1),
    # The Queue's Add to queue (ofMirrorQueue): the Scheduled events widget's "+" on New post and Go live, the
    # saved-for-later pages' two "+", and New message's schedule button (ofMirrorChat's date and time dialog).
    (lambda p: p.startswith("new-post/") or p=="streaming/dashboard/create", "[at-attr='add_event_widget']", False, 1),
    (lambda p: p.startswith("queue/saved-for-later-"), "[data-oi-add]", False, 2),
    (lambda p: p=="messages/send", "button[at-attr='scheduled_msg']", False, 1),
]
# Phase 1 (docs/spec/ofm-not-yet/phase-01-read-only-gaps.md), Single Creator only. Each Phase 1 ticket adds its own rows,
# in its area module (MODULES below).
# PHASE1: (page, control, status); control "css:<selector>" or the sweep's label (ending in a space: a prefix).
# - "pending": the control must be found on its page (it may keep the Not-yet title, or be Wired by an older binder);
# - "proven": also Wired (data-oi-wired, no Not-yet title). A row turns "proven" in the change that commits its control's
#   capture record with a live pass (docs/of-manager/captures/), the only title-drop event (D1).
# - "not-yet" (ticket 16): found, and every match still carries the Not-yet title (D1: kept until the Live pass), so the
#   Live pass flips this one status to "proven" and nothing else.
# ASSUMPTION: pending rows only need the control found, and READS un-greys the control itself, so a binder's wiring is
# proven before the app drops the title (ticket 13, rung 4: no app-side test hook); overturned if the owner wants a
# check-only switch in the app instead.
PHASE1=[]
# READS: one dict per check. On a fresh load it runs `steps`, each (verb, control[, text]) on the control's first match
# (control as PHASE1's; the check removes its `disabled` and Not-yet title itself), followed by 1.5s for its reads to
# land: "click"; "fill" (typed, with its input events); "set" (the value put in place with no event, as text typed
# before pressing Search); "press" (a key on it: the Search button lies under OF's search field, so the operator
# reaches it from the keyboard). Within 5s more it needs every GET of `get` = [(path, {param: value})] made during the
# last step (no `get`: requests unchecked), then the `settled` snapshot (`SNAP`: a frame-side function's JSON, the same
# over SETTLE consecutive polls) holding every `shows` (required: what only the filtered answer renders) and none of
# `hides` (optional: what only the unfiltered/default answer renders), and no Relay write. `query` (ticket 16):
# the page opens with it (a chat State page needs its ?chat=); `get` None: no GET /api/** at all during the last step
# and the settle polls (a client-side control); the snapshot reads whichever Mirror page frame is loaded now
# (frame_now: a step may open another page). The step ("back", None) (ticket 17): the top frame's history back.
SETTLE=5
def read_label(r):
    """A READS row's name in the check lines: its page and steps."""
    return f"{r['page']}: READS " + " > ".join(" ".join(map(str, s)) for s in r["steps"])
READS=[]
# HANDOFF (ticket 57): the hand-off table's URLs (app/lib/ofMirrorHandoffs.ts, exact). A visible
# a[data-oi-wired][target=_blank] with one of these hrefs joins the swept controls (after the page's own), and a click
# that opens a popup to one is a Wired control's or link's outcome: recorded and aborted (no non-localhost load); a popup
# to any other URL still fails as a non-localhost request.
HANDOFF=[]
# SWEEP_QUERY (ticket 33): {page: query}, the query the sweep opens a page with (and reopens it with after a write or a
# navigation; a URL with just that query is still the page itself, `navigated`). A page with no entry opens bare, as
# before. For a page whose controls draw only with a query: the chat page's own bubbles need its ?chat=.
SWEEP_QUERY={}
def sweep_url(page):
    """The URL the sweep opens `page` at: url_of, with the page's SWEEP_QUERY if it has one."""
    q=SWEEP_QUERY.get(page, "")
    return url_of(page)+(f"?{q}" if q else "")
# Per-ticket rows live in area modules beside dead.py, merged here in this order (the rows run in it): each module is
# data plus its own mocks (helpers from dead_lib, never `import dead`: it runs as __main__) and may export PHASE1,
# READS, SOURCES, V2, MARKED, ALLOWED, ALLOWED_RE, HANDOFF, SWEPT and SWEEP_QUERY. An explicit tuple, never a glob: a misnamed file
# would be skipped silently, and file order would pick which mock wins. A new area: one more module, listed here.
MODULES=("dead_statistics", "dead_home", "dead_messages", "dead_settings", "dead_notifications", "dead_collections", "dead_content", "dead_vault",
         "dead_statements", "dead_golive")
def load(modules):
    """Merge each module's tables into these. A mock path (SOURCES and V2 are one namespace: SOURCES wins a path in both)
    already present, from dead.py or an earlier module, raises with the path and both module names."""
    owner=dict.fromkeys(SOURCES, "dead")
    for name in modules:
        mod=importlib.import_module(name)
        for table in ("SOURCES", "V2"):
            for path in getattr(mod, table, {}):
                if path in owner: raise ValueError(f"dead.py: mock key {path!r} ({table}) in both {owner[path]} and {name}")
                owner[path]=name
        SOURCES.update(getattr(mod, "SOURCES", {})); V2.update(getattr(mod, "V2", {}))
        for table in ("PHASE1", "READS", "MARKED", "ALLOWED_RE", "HANDOFF", "DISABLED"): globals()[table].extend(getattr(mod, table, ()))
        ALLOWED.update(getattr(mod, "ALLOWED", ())); SWEPT.update(getattr(mod, "SWEPT", ())); SWEEP_QUERY.update(getattr(mod, "SWEEP_QUERY", {}))
SWEPT=set()   # pages a module needs swept while its controls are pinned (dead_golive.py), checked against pages()
load(MODULES)
HANDOFFS=[]   # the hand-off URLs requested so far (session(), aborted)
SECTIONS=("new-post","home","streaming","profile","queue","collections","notifications","statements","statistics","messages","vault","bank","settings")
# ASSUMPTION: Release forms joins only the --sweep-out run (spec story 46), so the default run's pages and output stay as
# they were; overturned if the default run should check Release forms too.
if SWEEP_OUT:
    SECTIONS+=("release-forms",)
def pages():
    """The signed-off pages in the Mirror page list's order, as <section>/<sub, or index>."""
    out=[]; section=None
    for line in open(os.path.join(ROOT,"app/lib/of-mirror-pages.ts")):
        if m:=re.match(r'^  "([^"]+)": \{', line): section=m[1]
        elif (m:=re.match(r'^      "([^"]*)": "', line)) and section:
            sub=m[1]
            if section in SECTIONS and f"{section}/{sub}" not in redirected():
                out.append(f"{section}/{sub or 'index'}")
    return out
def redirected():
    """The pages whose URL opens another page (REDIRECTS of app/lib/of-mirror-route.ts, read as text): not swept."""
    src=open(os.path.join(ROOT,"app/lib/of-mirror-route.ts")).read()
    block=src[src.index("const REDIRECTS"):]
    return set(re.findall(r'^  "([^"]+)":', block[:block.index("};")], re.M))
def url_of(page):
    section, _, sub=page.partition("/")
    return f"{M}/{section}" + ("" if sub=="index" else f"/{sub}")
def png_1x1():
    def chunk(kind, data): return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00\x00\xaf\xf0")) + chunk(b"IEND", b"")
PIXEL=png_1x1()
failures=[]
def check(label, got, want):
    print(json.dumps({"check":label,"want":want,"got":got}))
    if got!=want: failures.append(f"{label}: got {got!r}, expected {want!r}")
# Frame-side helpers, installed per load: the controls in document order (control, what to click), a probe that scrolls
# one into view and reports what the mouse would hit at its centre, and its state snapshot.
HELPERS=r"""() => {
  const vis = (e) => { const r = e.getBoundingClientRect(); return e.checkVisibility({ checkVisibilityCSS: true }) && r.width > 0 && r.height > 0; };
  const labelOf = (e) => e.closest('label') || (e.id ? document.querySelector(`label[for="${CSS.escape(e.id)}"]`) : null);
  const desc = (e) => {
    const t = (e.getAttribute('aria-label') || e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 30);
    const cls = (e.getAttribute('class') || '').trim().split(/\s+/).slice(0, 2).join('.');
    const at = e.getAttribute('at-attr');
    return `${e.tagName.toLowerCase()}${cls ? '.' + cls : ''}${at ? `[at-attr=${at}]` : ''}${e.type === 'checkbox' ? '[checkbox]' : ''} "${t}"`;
  };
  // The Not-yet sweep's label (--sweep-out): aria-label, text or placeholder, else [first two classes], else [TAG]; a date
  // "Mon D, YYYY" reads "{date}", so the sweep does not depend on the run day (sweep_diff.py reads old files the same way).
  const label = """+LABEL_JS+r""";
  const HANDOFF = """+json.dumps(HANDOFF)+r""";  // ticket 57
  window.__deadSweep = (notYet) => {
    const ny = [], dis = [];
    // Not OF's own left nav (.l-sidebar, under the content column: no click reaches it); a disabled part of a control
    // with the Not-yet title (a select's input) is that control.
    for (const e of document.querySelectorAll('[title], button:disabled, input:disabled, select:disabled, textarea:disabled')) {
      if (!vis(e) || e.closest('.l-sidebar')) continue;
      const l = label(e);
      if (e.getAttribute('title') === notYet) { if (!ny.includes(l)) ny.push(l); }
      else if (e.matches(':disabled') && !e.closest(`[title="${notYet}"]`) && !dis.includes(l)) dis.push(l);
    }
    return { ny, dis };
  };
  // A Wired control's own state: its markup, its checked state, its ancestors' classes (Search media opens its header) and
  // the size of the dialog, poll panel or form it sits in ("+ Add another option" adds a row there) and the date shown
  // beside it (the queue's month and day arrows).
  const snap = (e) => {
    let c = ''; for (let a = e.parentElement; a; a = a.parentElement) c += '|' + a.className;
    const panel = e.closest('.modal-content, .b-make-post__voting, form');
    const date = e.parentElement?.querySelector('.b-queue-header__date')?.textContent ?? '';
    return e.outerHTML + '|' + (e.checked ?? '') + c + '|' + (panel ? panel.getElementsByTagName('*').length : '') + '|' + date;
  };
  window.__deadList = () => {
    const list = [];
    for (const e of document.querySelectorAll('button, [role=button], input[type=checkbox]')) {
      if (e.closest('.video-js') || e.matches(':disabled')) continue;
      const target = e.matches('input') && !vis(e) ? labelOf(e) : e;
      if (target && vis(target)) list.push([e, target]);
    }
    // ticket 57: a hand-off link (HANDOFF), after the page's own controls
    for (const a of document.querySelectorAll('a[data-oi-wired][target=_blank]')) if (HANDOFF.includes(a.href) && vis(a)) list.push([a, a]);
    window.__dead = list;
    return list.length;
  };
  window.__deadProbe = (i) => {
    const [el, target] = window.__dead[i];
    document.getElementById('oi-note')?.remove(); // only a note this click causes counts (and the layout is the one clicked)
    window.__deadWas = document.activeElement;
    if (!el.isConnected || el.matches(':disabled') || !vis(target)) return { skip: desc(el) };
    target.scrollIntoView({ block: 'center', inline: 'center' });
    // ticket 57: a hand-off link is inline text that may wrap: the centre of its first line box, not of its bounding box
    const r = target.matches('a[data-oi-wired][target=_blank]') ? target.getClientRects()[0] : target.getBoundingClientRect();
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    const hit = x >= 0 && y >= 0 && x < innerWidth && y < innerHeight ? document.elementFromPoint(x, y) : null;
    if (!hit) return { skip: desc(el) };
    // The mouse lands on the control (a checkbox: or its label), or on a link laid over it (a State page backdrop or opener); anything else on top
    // (a page layer over an off-canvas menu, the cell of a control without pointer events) means no operator can click it.
    const own = target.contains(hit) || el.contains(hit) || (el.matches('input') && !!labelOf(el)?.contains(hit));
    // A Wired control (its own mark, as below) under a State page's backdrop with no dialog, menu or focused field open
    // over it: the operator's click goes back instead of to the control (Home's poll panel backdrop took Post's click,
    // and Post never posted). An open menu or field closes on a click outside, as OF's.
    const mine = el.matches('input') ? !!el.closest('[data-oi-wired]') : el.matches('[data-oi-wired]') || !!el.querySelector('[data-oi-wired]');
    if (mine && !own && hit.closest('a.of-state-backdrop') && !hit.closest('.modal') && !document.querySelector('.of-state-menu, .m-focused'))
      return { covered: `${desc(el)} (on top: ${desc(hit)})` };
    if (!own && !hit.closest('a[href]')) return { skip: `${desc(el)} (on top: ${desc(hit)})` };
    // Marked as bindWrites reads the mark: a checkbox inside [data-oi-wired] (the change path); a button whose mark is on it
    // or on a part of it (the click fallback), not a button nested in a Wired row.
    const wired = hit.closest('[data-oi-wired]');
    const marked = !own ? wired : el.matches('input') ? el.closest('[data-oi-wired]') : wired && el.contains(wired);
    const link = hit.closest('a[href]') || (own ? el.closest('a[href]') : null);
    return { x, y, kind: marked ? 'wired' : link ? 'link' : 'plain', href: link?.getAttribute('href') ?? null,
             what: desc(el) + (own ? '' : ` (on top: ${desc(hit)})`), state: snap(el), selected: el.matches('.b-month-day-cell.selected'),
             label: label(el) };
  };
  // A PHASE1/READS control: "css:<selector>", else the sweep's label (one ending in a space: a label prefix, "From "),
  // visible and outside OF's left nav; per match its Wired mark (as bindWrites reads a button's) and its Not-yet title.
  const find = (spec, notYet) => (spec.startsWith('css:') ? [...document.querySelectorAll(spec.slice(4))]
    : [...document.querySelectorAll('[title], button, [role=button], input, select, textarea, a[href]')]
        .filter((e) => label(e) === spec || (spec.endsWith(' ') && label(e).startsWith(spec))))
    .filter((e) => vis(e) && !e.closest('.l-sidebar'))
    .map((e) => ({ e, wired: e.matches('[data-oi-wired]') || !!e.querySelector('[data-oi-wired]'), ny: e.getAttribute('title') === notYet }));
  window.__deadFind = ([spec, notYet]) => find(spec, notYet).map(({ wired, ny }) => ({ wired, ny }));
  // READS: the check itself un-greys the control under test (no app-side switch, ticket 13's ASSUMPTION).
  // The first match carries data-oi-reads for the check's own click.
  window.__deadUngrey = ([spec, notYet]) => find(spec, notYet).map(({ e }, i) => {
    e.removeAttribute('disabled');
    // ticket 16: a greyed menu item (the chat dropdown's Select) is also greyed by aria-disabled and Vuetify's class
    if (e.getAttribute('title') === notYet) { e.removeAttribute('title'); e.removeAttribute('aria-disabled'); e.classList.remove('v-list-item--disabled'); }
    if (!i) e.setAttribute('data-oi-reads', '');
    return label(e);
  }).length;
  window.__deadState = (i) => { const e = window.__dead[i][0]; return e.isConnected ? snap(e) : null; };
  // A Wired control that puts the cursor in a Wired field outside itself (Release forms' filter Search focuses the
  // sidebar search, which its binder marks): the binder's own focus(), not any field the click happens to reach.
  window.__deadFocus = (i) => {
    const a = document.activeElement;
    return !!a && a !== window.__deadWas && !window.__dead[i][0].contains(a) && a.matches('[data-oi-wired]')
      && a.matches('input:not([type=checkbox]):not([type=radio]):not([type=hidden]), textarea, [contenteditable=""], [contenteditable="true"]');
  };
}"""
NOTE="document.getElementById('oi-note')?.textContent ?? null"
# An open State menu's items, each scrolled into view: the ones whose centre is the page's backdrop (null: no menu open).
MENU_HIT=r"""() => {
  const items = [...document.querySelectorAll('.of-state-menu .v-list-item, .of-state-menu [role=menuitem]')].filter((e, i, all) => all.indexOf(e) === i && e.checkVisibility());
  if (!items.length) return null;
  // Only the items the menu shows now: one its scroll box clips is a wheel away (a script's scrollTop doesn't take on
  // these state pages, so it can't be brought into view here).
  return items.flatMap((e) => {
    const r = e.getBoundingClientRect();
    const box = e.closest('.of-state-menu').getBoundingClientRect();
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    if (y < Math.max(box.top, 0) || y > Math.min(box.bottom, innerHeight)) return [];
    const hit = document.elementFromPoint(x, y);
    return hit?.closest('a.of-state-backdrop') ? [e.textContent.trim().replace(/\s+/g, ' ').slice(0, 30)] : [];
  });
}"""
def session(b, scope_js):
    """A fresh context and page with scope_js run before every load; returns (page, sent writes as (method, path,
    X-Account-Id, body), file choosers, console errors)."""
    ctx=b.new_context(viewport={"width":1440,"height":900})
    ctx.add_init_script(scope_js)
    foreign=lambda url: urlparse(url).hostname not in LOCAL
    def outside(route):
        failures.append(f"request to a non-localhost host: {route.request.url[:120]}")
        route.abort()
    ctx.route(foreign, outside)
    def handoff(route):   # ticket 57: registered after `outside`, so it runs first, for HANDOFF URLs only
        HANDOFFS.append(route.request.url); route.abort()
    ctx.route(lambda url: url in HANDOFF, handoff)
    pg=ctx.new_page()
    sent=[]; choosers=[]; gets=[]
    def mock(route):
        req=route.request; u=req.url; path=urlparse(u).path
        # Page routes win over the context's: a foreign URL matching a mock pattern still fails the check.
        if foreign(u): return outside(route)
        if req.method=="GET" and path.startswith("/api/"): gets.append((path, urlparse(u).query, req.headers.get("x-account-id")))
        if req.method!="GET" and path.startswith("/api/"):
            sent.append((req.method, path, req.headers.get("x-account-id"), req.post_data))
            return route.fulfill(status=200, content_type="application/json", body="{}")
        if path=="/img": return route.fulfill(status=200, content_type="image/png", body=PIXEL)
        if req.method=="GET" and path in SOURCES:
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(SOURCES[path]))
        if req.method=="GET" and (body:=v2_body(path, urlparse(u).query)) is not None:
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        if "/auth/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps(user))
        elif u.split("?")[0].endswith("/admin/accounts"): route.fulfill(status=200, content_type="application/json", body='{"accounts":[{"id":"acc1","nickname":"Model One","has_session":true},{"id":"1","nickname":"Model Two","has_session":true}],"active_account_id":null}')  # creators: none shows OfNotHaveModel
        elif "/chatter/me/accounts" in u: route.fulfill(status=200, content_type="application/json", body="[]")
        elif "/admin/employees" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"employees":[{"id":1,"display_name":"Tim","color":"#a78bfa","is_active":True,"chatter_id":None}]}))
        elif "/chatter/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"chatter":None,"owners":[]}))
        else: route.fulfill(status=200, content_type="application/json", body="[]")
    for pat in ["**/auth/**","**/chatter/**","**/admin/**","**/accounts**","**/api/**","**/img?**"]: pg.route(pat, mock)
    pg.route("**/events?**", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=""))  # no Relay: an empty stream, not a 500
    pg.on("filechooser", lambda fc: choosers.append(fc))
    pg.on("download", lambda d: choosers.append(d))  # a save (QR code's Download): counted as a file chooser
    pg.on("dialog", lambda d: d.dismiss())
    errs=[]; pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
    pg.on("pageerror", lambda e: errs.append(f"uncaught: {e}"))
    return pg, sent, choosers, errs, gets
def open_page(pg, page, reopened=False, query=""):
    """Load the page's /of-manager URL (with `query`, ticket 16: a READS row's ?chat=); the frame once loaded, bound and settled, with the helpers installed (or None).
    With --sweep-out a page that ends with no frame is opened once more before it counts (a long dev-server run's flake)."""
    pg.goto(f"{BASE}{url_of(page)}"+(f"?{query}" if query else ""), wait_until="load", timeout=90000)
    want=f"/of-mirror/pages/{page}.html"
    for _ in range(80):
        card=pg.get_by_text("Tim", exact=True)
        if card.count(): card.first.click()
        fr=[f for f in pg.frames if urlparse(f.url).path==want]
        try:
            if fr and fr[0].evaluate("document.readyState")=="complete":
                pg.wait_for_timeout(800)  # the binders run on the frame's load; the Data parts' mocked rows land
                fr[0].evaluate(HELPERS)
                return fr[0]
        except Exception: pass
        pg.wait_for_timeout(250)
    # ASSUMPTION: one re-open, --sweep-out only (coordinator's call); the default run still counts the first NO IFRAME.
    if SWEEP_OUT and not reopened:
        return open_page(pg, page, reopened=True, query=query)
    failures.append(f"{page}: NO IFRAME (url {pg.url})"); return None
def navigated(pg, page):
    u=urlparse(pg.url)
    return (u.path!=url_of(page) or u.query!=SWEEP_QUERY.get(page, "")) and u  # a link to the page itself with a query (?row=) changes the URL too
def outcome(pg, fr, page, i, probe, sent, choosers, before):
    """The click's first outcome within 1s: ("write"|"chooser"|"handoff"|"nav"|"note"|"changed", detail) or (None, None)."""
    n_sent, n_choosers, n_handoffs=before
    for _ in range(20):
        if len(sent)>n_sent: return "write", sent[n_sent:]
        if len(choosers)>n_choosers: return "chooser", None
        if len(HANDOFFS)>n_handoffs: return "handoff", HANDOFFS[n_handoffs:]  # ticket 57
        if (u:=navigated(pg, page)): return "nav", u
        try:
            text=fr.evaluate(NOTE)
            if text is not None: return "note", text
            if probe["kind"]=="wired" and fr.evaluate("i => window.__deadState(i)", i)!=probe["state"]: return "changed", None
            # ASSUMPTION: focus moved to a Wired field outside the control is a Wired control's outcome (the operator sees
            # the cursor there), in both modes; overturned if focusing a field should count as Silent.
            if probe["kind"]=="wired" and fr.evaluate("i => window.__deadFocus(i)", i):
                return "changed", None
        except Exception: pass  # the frame went away: a navigation, seen on the next round
        pg.wait_for_timeout(50)
    return None, None
def phase1_verdict(found, status):
    """A PHASE1 row's verdict from its matches on the page: "ok", or what is wrong."""
    if not found: return "not found"
    if status=="proven" and not all(m["wired"] and not m["ny"] for m in found):
        return f"not Wired: {sum(not m['wired'] for m in found)} unmarked, {sum(m['ny'] for m in found)} with the Not-yet title"
    if status=="not-yet" and not all(m["ny"] for m in found):  # ticket 16
        return f"lost the Not-yet title: {sum(not m['ny'] for m in found)} of {len(found)} without it"
    return "ok" if status in ("pending","proven","not-yet") else f"unknown status {status!r}"
def not_yet(page, spec):
    """ticket 16: the control is a "not-yet" PHASE1 row of the page (its READS steps are un-greyed)."""
    return (page, spec, "not-yet") in PHASE1
def frame_now(pg):
    """ticket 16: the Mirror page frame loaded now, whichever page (a READS step may open another, as Select opens the
    list), or None."""
    return next((f for f in pg.frames if f.parent_frame==pg.main_frame and urlparse(f.url).path.startswith("/of-mirror/pages/")), None)
def read_step(fr, s, ny=False):
    """One READS step: marks its control's first match (un-greyed by the check; `ny`, ticket 16: a "not-yet" control, every match must still carry
    the Not-yet title on the row's own load) and acts on it. A problem string, or None."""
    verb, spec, *text=s
    if verb=="back": return fr.evaluate("() => void parent.history.back()")  # ticket 17
    if ny and (problem:=phase1_verdict(fr.evaluate("a => window.__deadFind(a)", [spec, NOT_YET]), "not-yet"))!="ok":
        return f"{spec}: {problem}"  # ticket 16: the PHASE1 check sees the page's bare load (no ?chat=: Find unbound)
    fr.evaluate("() => document.querySelectorAll('[data-oi-reads]').forEach((e) => e.removeAttribute('data-oi-reads'))")
    if not fr.evaluate("a => window.__deadUngrey(a)", [spec, NOT_YET]): return f"{spec}: not found"
    loc=fr.locator("[data-oi-reads]").first
    try:  # ticket 16: a control still greyed (a lost Not-yet title leaves aria-disabled) is the row's red, not a crash
        if verb=="click": loc.click(timeout=5000)
        elif verb=="fill": loc.fill(text[0], timeout=5000)
        elif verb=="press": loc.press(text[0], timeout=5000)
        elif verb=="set": loc.evaluate("(e, t) => { e.value = t; }", text[0])
        else: raise ValueError(f"unknown READS step {s!r}")
    except PwError as e: return f"{spec}: {verb} failed: {str(e).splitlines()[0]}"
def reads(pg, page, sent, gets):
    """Single Creator: each READS row of the page on a fresh load (see READS)."""
    for r in [r for r in READS if r["page"]==page]:
        fr=open_page(pg, page, query=r.get("query", ""))
        if not fr: return
        label=read_label(r)
        pg.wait_for_timeout(300)
        s0, problem=len(sent), None
        for n, s in enumerate(r["steps"]):
            if n==len(r["steps"])-1: g0=len(gets)
            problem=read_step(frame_now(pg) or fr, s, not_yet(page, s[1]))
            if problem: break
            pg.wait_for_timeout(1500)
        if problem:
            check(label, problem, "every step's control found"); continue
        def one(path, params, new):
            return any(g[0]==path and all(parse_qs(g[1]).get(k)==[v] for k, v in params.items()) for g in new)
        def hit():
            if r.get("get", ()) is None: return not [g for g in gets[g0:] if g[0].startswith("/api/")]  # ticket 16
            return all(one(path, params, gets[g0:]) for path, params in r.get("get", []))
        snaps, first=[], None   # settled: the same snapshot over SETTLE polls in a row, all taken after the GETs are seen
        for _ in range(50):
            pg.wait_for_timeout(100)
            if first is None and hit(): first=len(snaps)
            try:
                f=frame_now(pg)
                snaps.append(json.dumps(f.evaluate(r["settled"])) if f else None)
            except Exception: snaps.append(None)
            tail=snaps[first:][-SETTLE:] if first is not None else []
            if len(tail)==SETTLE and tail[0] is not None and len(set(tail))==1: break
        tail=snaps[first:][-SETTLE:] if first is not None else []
        after=(tail or snaps or [None])[-1] or ""   # ticket 14: no GET seen -> the last snapshot (was an IndexError)
        got={"settled":len(tail)==SETTLE and tail[0] is not None and len(set(tail))==1,
             "shows":all(x in after for x in r["shows"]), "writes":[list(w[:2]) for w in sent[s0:]]}
        want={"settled":True, "shows":True, "writes":[]}
        if "get" in r: got["get"]=hit(); want["get"]=True
        if "hides" in r: got["hides"]=not any(h in after for h in r["hides"]); want["hides"]=True
        check(label, got, want)
def sweep(b, scope, only=()):
    """Every signed-off page in one Creator's scope (`model:1`)."""
    pg, sent, choosers, errs, gets=session(b, f"localStorage.setItem('chatterly:scope','{scope}')")
    h0=len(HANDOFFS)
    todo=[p for p in pages() if not only or any(p==o or p.startswith(o.rstrip("/")+"/") for o in only)]
    check(f"{scope}: pages swept", bool(todo), True)
    totals={"controls":0,"links":0,"wired":0,"readonly":0}
    found=[]     # --sweep-out, Single Creator: [page, {"ny", "dis", "ro"}]
    opened_at=[]   # SWEEP_QUERY (ticket 33): pages the sweep found at another query than their entry (none: bare)
    for page in todo:
        if urlparse(pg.url).hostname in LOCAL: pg.evaluate("sessionStorage.clear()")
        fr=open_page(pg, page, query=SWEEP_QUERY.get(page, ""))
        if not fr: continue
        if (q:=urlparse(pg.url).query)!=SWEEP_QUERY.get(page, ""): opened_at.append([page, q])
        marks=[]
        for applies, sel, shown, n in MARKED:
            if applies(page):
                got=fr.evaluate("([sel, shown]) => [...document.querySelectorAll(sel)].filter(e => !shown || e.checkVisibility()).map(e => e.hasAttribute('data-oi-wired'))", [sel, shown])
                marks.append([sel, got==[True]*n, got])
        if marks: check(f"{page}: Ground truth 5 Wired controls carry data-oi-wired", [m[:2] for m in marks], [[m[0], True] for m in marks])
        if rows:=[r for r in PHASE1 if r[0]==page]:
            check(f"{page}: PHASE1 controls found (proven: Wired, no Not-yet title)",
                  [[c, s, phase1_verdict(fr.evaluate("a => window.__deadFind(a)", [c, NOT_YET]), s)] for _, c, s in rows],
                  [[c, s, "ok"] for _, c, s in rows])
        for _, sel, text in [d for d in DISABLED if d[0]==page]:
            got=fr.evaluate("([sel, text]) => [...document.querySelectorAll(sel)].filter(e => e.textContent.trim() === text).map(e => [e.disabled, e.title])", [sel, text])
            check(f"{scope} {page}: {text} is disabled with the tooltip", got, [[True, NOT_YET]])
        # An open menu's own items take their clicks: none lies under the backdrop (My profile's More menu once did, inside
        # the content column's stacking context, so Statistics and Copy link went back to the profile).
        if (menu:=fr.evaluate(MENU_HIT)) is not None: check(f"{scope} {page}: the open menu's items are over the backdrop", menu, [])
        found_page=fr.evaluate("t => window.__deadSweep(t)", NOT_YET) if SWEEP_OUT else None
        ro=[]
        total=fr.evaluate("window.__deadList()")
        counts={"controls":0,"links":0,"wired":0,"readonly":0}
        silent=[]; unmarked_writes=[]; off_list=[]; wired_ro=[]; covered=[]; skipped=[]; shot=False
        i=0
        while i<total:
            try: probe=fr.evaluate("i => window.__deadProbe(i)", i)
            except Exception as e: probe={"skip":f"#{i}: {str(e)[:80]}"}
            if "skip" in probe:
                skipped.append(probe["skip"]); i+=1; continue
            if "covered" in probe:
                covered.append(f"#{i} {probe['covered']}"); i+=1; continue
            box=pg.locator(f"iframe[src='/of-mirror/pages/{page}.html']").bounding_box()
            before=(len(sent), len(choosers), len(HANDOFFS))
            pg.mouse.click(box["x"]+probe["x"], box["y"]+probe["y"])
            kind, got=outcome(pg, fr, page, i, probe, sent, choosers, before)
            # A dialog the click built in place (Add to queue, New message's schedule dialog) closes with Escape, as an
            # operator closes it, so the page's other controls stay in reach.
            try: fr.evaluate("document.querySelector('.modal.show[data-oi-data]') && document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))")
            except Exception: pass
            what=f"#{i} {probe['what']}"
            counts["controls"]+=1
            if probe["kind"]=="link": counts["links"]+=1
            if probe["kind"]=="wired": counts["wired"]+=1
            if kind=="write":
                pg.wait_for_timeout(300)  # a write's own follow-ups (a navigation) settle before the reload
                for w in sent[before[0]:]:
                    if w[:2] not in ALLOWED and not any(w[0]==m and r.fullmatch(w[1]) for m, r in ALLOWED_RE): off_list.append([what, w[0], w[1]])
                    if probe["kind"]!="wired": unmarked_writes.append([what, w[0], w[1]])
            elif kind=="nav":
                if got.hostname not in LOCAL or not got.path.startswith(M+"/"): silent.append([what, f"navigated to {pg.url}"])
            elif kind=="note":
                if not shot: pg.screenshot(path=f"{SHOTS}/inapp-dead-{page.replace('/','__')}.png"); shot=True
                if probe["kind"]=="link": silent.append([what, f"link shows note {got!r}"])
                elif probe["kind"]=="wired":
                    if got==READ_ONLY: wired_ro.append(what)
                elif got==READ_ONLY:
                    counts["readonly"]+=1
                    ro.append(probe["label"])
                else: silent.append([what, f"note {got!r}"])
            elif kind in ("chooser","changed"):
                if probe["kind"]!="wired": silent.append([what, kind])
            elif kind=="handoff":   # ticket 57: a Wired control's or link's popup, aborted
                if probe["kind"] not in ("wired","link"): silent.append([what, f"hand-off {got}"])
                for p in pg.context.pages[1:]: p.close()
            elif not (probe["kind"]=="link" and probe["href"] in ("#", url_of(page))) and not (probe["kind"]=="wired" and probe["selected"]):
                silent.append([what, "no write, navigation or note within 1s"])
            i+=1
            if kind in ("write","nav"):
                fr=open_page(pg, page, query=SWEEP_QUERY.get(page, ""))
                if not fr: break
                if (again:=fr.evaluate("window.__deadList()"))!=total:
                    failures.append(f"{page}: {again} controls after a reload, {total} before"); break
        label=f"{scope} {page}"
        check(f"{label}: no Silent control", silent, [])
        check(f"{label}: no Relay write from an unmarked control", unmarked_writes, [])
        check(f"{label}: no Relay write off the allow-list", off_list, [])
        check(f"{label}: no Wired control shows the Read-only note", wired_ro, [])
        check(f"{label}: no Wired control under a backdrop with nothing open over it", covered, [])
        print(json.dumps({"scope":scope, "page":page, **counts}))
        for k in totals: totals[k]+=counts[k]
        if skipped: print(json.dumps({"scope":scope,"page":page,"skipped (hidden or gone by their turn)":skipped}))
        reads(pg, page, sent, gets)
        if found_page is not None:
            found.append([page, {**found_page, "ro": ro}])
    check(f"{scope}: SWEEP_QUERY: every page loads at its entry's query, bare with none", opened_at, [])
    print(json.dumps({"scope":scope, "pages":len(todo), **totals}))
    print(f"{scope} relay writes:", [w[:3] for w in sent])
    if HANDOFF: print(f"{scope} hand-offs (aborted):", HANDOFFS[h0:])  # ticket 57
    if SWEEP_OUT:
        with open(SWEEP_OUT, "w") as f:
            json.dump(found, f, indent=1)
        print(json.dumps({"sweep-out": SWEEP_OUT, "pages": len(found)}))
    check(f"{scope}: no console errors", [e[:160] for e in errs][:8], [])
    pg.context.close()
def list_rows():
    """--list-rows: one line per PHASE1 and READS row (in run order), the mocks (path and body digest) and the other
    tables, then the counts; no browser."""
    import hashlib
    def js(x): return json.dumps(x, sort_keys=True, default=lambda o: sorted(o) if isinstance(o, set) else getattr(o, "__name__", None) or o.pattern)
    for r in PHASE1: print("PHASE1", js(r))
    for r in READS: print("READS", js(r))
    for path in sorted({*SOURCES, *V2}):
        print("MOCK", path, hashlib.sha1(js([SOURCES.get(path), V2.get(path)]).encode()).hexdigest()[:12])
    for applies, sel, shown, n in MARKED: print("MARKED", js([sel, shown, n, [p for p in pages() if applies(p)]]))
    print("ALLOWED", js(sorted(ALLOWED))); print("ALLOWED_RE", js(ALLOWED_RE)); print("HANDOFF", js(HANDOFF)); print("DISABLED", js(DISABLED))
    print("SWEEP_URL", js([[p, sweep_url(p)] for p in pages()]))
    print("COUNT PHASE1", len(PHASE1))
    print("COUNT READS", len(READS))
if LIST_ROWS:
    list_rows(); sys.exit(0)
# The v2 mock itself: the probe is an object, and each param's other tabs answer other bodies than its default.
check("v2 mock: the probe answers an object", bool(v2_body("/api/of/v2/streaks/top", "")) and isinstance(v2_body("/api/of/v2/streaks/top", ""), dict), True)
check("v2 mock: a param's other values answer other rows than its default", [p for p, (_, d, o) in V2.items() if any(b==d for b in o.values())], [])
# The Phase 1 tables cannot pass on absence: every row's page is a swept page, every READS row names what it shows.
check("PHASE1/READS: every row's page is a page the sweep opens", sorted({r[0] for r in PHASE1}.union(r["page"] for r in READS)-set(pages())), [])
check("SWEEP_QUERY: every entry's page is a page the sweep opens", sorted(set(SWEEP_QUERY)-set(pages())), [])
check("READS: every row has `shows`", [read_label(r) for r in READS if not r.get("shows")], [])
check("SWEPT: every page a module keeps swept is a page the sweep opens", sorted(SWEPT-set(pages())), [])
with sync_playwright() as p:
    b=p.chromium.launch()
    sweep(b, "model:1", ARGS)
if failures:
    print("FAIL:", *failures, sep="\n  "); sys.exit(1)
print("dead ok")
