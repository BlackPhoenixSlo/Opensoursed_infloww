"""No Silent control: every visible, enabled control on the signed-off Mirror pages answers a click (Phase 6).

Pages: every page of new-post, home, streaming, profile, queue, collections, notifications, statements, statistics, messages, vault, bank
and settings with their tabs, modals and states, read from app/lib/of-mirror-pages.ts (arguments: only the pages named, or under a
named prefix, e.g. `queue` or `new-post/state-vault`). sessionStorage is cleared before each page.
Mocks the login (as writes.py), GET /api/of/v2/users/me (synthetic), GET /posts/tagged-friend-users and GET /vault/media
(one synthetic "Alpha One" row each), GET /img (a 1x1 PNG built by this script) and [] for every other GET /api/**; every
non-GET /api/** is recorded (method, path, X-Account-Id, body) and answered 200 {}. Any request to a host other than
localhost is aborted and fails the check.
Single Creator (scope `model:1`): the frame's visible, enabled button, [role=button] and input[type=checkbox] (not inside
.video-js; a hidden checkbox through its visible label) are clicked one by one with the mouse at their centre, so whatever
lies on top (a State page backdrop) takes the click as it would the operator's; a control under anything else (a page
layer, a modal) or out of reach (OF's recycled feed views) is listed as skipped. Marked means as bindWrites reads it: a
checkbox inside [data-oi-wired], a button with the mark on it or on a part of it. Before each click #oi-note is removed;
then for 1s the first outcome is taken: a Relay write, a file chooser or download, a top-URL change, a fresh #oi-note, or (a marked
control) a change to its own markup, checked state, ancestors' classes, the size of its dialog, poll panel or form, or the
queue date beside it. After a navigation or a write the page is
loaded again and the sweep goes on with the next control.
- An unmarked control must give the Read-only note or a navigation to a localhost /of-manager/ URL.
- A control in a[href] (a link, a State page opener or backdrop) must navigate to a localhost /of-manager/ URL, or stay
  inert when its href is # or the page itself; it never shows a note.
- A [data-oi-wired] control must give an allow-listed write, a navigation, a file chooser, a change to its own markup,
  or a note that is not the Read-only note; the queue calendar's selected day may stay inert (it already shows that day).
  Its centre must be its own (elementFromPoint): one under a State page's backdrop with no dialog, menu or focused
  field open over it fails, as the operator's click would go back instead (Home's poll page once sent Post's click to
  Home, and nothing posted).
- An open State menu's items (each scrolled into view) are over the page's backdrop: none has its centre on it (My
  profile's More menu lay under it, so Statistics and Copy link went back to the profile).
- No Relay write from an unmarked control; no write off the allow-list (POST /api/of/v2/posts, /upload, /stories/upload,
  /campaigns, /trials, /promotions, /streams; the settings saves: PATCH /users/me, /users/me/reply-on-subscribe,
  /users/me/settings/security, /users/settings/notifications, /users/settings/story, PUT /users/me/settings/security).
- The controls with no Known body (DISABLED; none left: the promotion modal's "Start campaign", the bundle modal's "Save"
  and the trial modal's "Create link" send OF's own bodies) are disabled with the tooltip "Not available in Inflowwww yet", in both scopes.
- The plan's measured Wired controls (Ground truth 5) carry data-oi-wired on the pages that bind them.
- No console errors.
All Creators (the scope key removed before every load): the same pages, sweep and checks but the mark check, and
- no non-GET /api/** request from a page that does not stand in; a stand-in page (app/lib/ofMirrorProfile.ts
  STAND_IN_SRC, read as text: New post, Settings, Messages and the rest show the first model with a session in All
  models, and their actions are that model's) may write, each write with that model's X-Account-Id (STAND_IN);
- each send control on a page that does not stand in, made sendable as an operator would (Post: text in the composer),
  clicked on its page gives exactly "Select a model to save changes": Post, Add to story (home), Start campaign (home/state-promotion) and the stream
  schedule form's SCHEDULE.
Prints one {"check","want","got"} line per check, one {scope, page, controls, links, wired, readonly} line per page and
one {scope, pages, controls, links, wired, readonly} line per pass.
Screenshots (the page's first note showing): /tmp/of-mirror-shots/inapp-dead-<page>.png; both passes share the names, so
the All-Creators pass overwrites the Single-Creator image where both showed a note. Exit 1 on a failed check.
"""
import json, os, re, struct, sys, zlib
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
BASE=f"http://localhost:{os.environ.get('PORT','3091')}"
M="/of-manager"
SHOTS="/tmp/of-mirror-shots"
os.makedirs(SHOTS, exist_ok=True)
ROOT=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
user={"user_id":"u1","username":"tester","is_admin":False}
READ_ONLY="Read-only in Inflowwww for now"
ALLOWED={("POST",f"/api/of/v2/{p}") for p in ("posts","upload","stories/upload","campaigns","trials","promotions","streams",
    "subscriptions/bundles","trials/share-access","labels","labels/sort","guests")} | {
    ("PATCH",f"/api/of/v2/{p}") for p in ("users/me","users/me/reply-on-subscribe","users/me/settings/security","users/settings/notifications","users/settings/story",
    "release-forms/toggle-show")} | {
    ("PUT","/api/of/v2/users/me/settings/security")}
# A running promotion's Stop promotion (ofMirrorOffers): POST /promotions/<id>/finish.
FINISH=re.compile(r"^/api/of/v2/promotions/\d+/finish$")
NOT_YET="Not available in Inflowwww yet"
# Submits with no Known body, disabled with the tooltip: none left (the promotion, bundle and free trial link dialogs send
# OF's own bodies through ofMirrorOffers).
DISABLED=[]
LOCAL=("localhost","127.0.0.1")
SOURCES={
    "/api/of/v2/users/me": {"id":1,"username":"alphaone","name":"Alpha One"},
    "/api/of/v2/posts/tagged-friend-users": {"items":[{"id":901,"name":"Alpha One","type":"user","user":{"id":901,"name":"Alpha One","username":"alphaone"}}],"hasMore":False},
    "/api/of/v2/vault/media": {"list":[{"id":61,"type":"photo","createdAt":"2026-10-10T12:00:00Z","files":{"thumb":{"url":"https://cdn.example.invalid/v61.jpg"}}}],"hasMore":False},
}
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
# The send controls, by page, for the All-Creators pass: (page, selector, field typed first or None, the exact note).
# Checked only on a page that does not stand in (stands_in): New post's and Settings' act as the stand-in model there,
# and stay listed for the day their page stops standing in.
EDITOR="[contenteditable][aria-label='Textbox field']"
SEND=[
    ("new-post/index", "button[at-attr='submit_post']", EDITOR, "Select a model to save changes"),
    ("new-post/index", ".b-story-item.m-story-item-own", None, "Select a model to save changes"),
    ("home/index", "button[at-attr='submit_post']", EDITOR, "Select a model to save changes"),
    ("home/index", ".b-story-item.m-story-item-own", None, "Select a model to save changes"),
    ("settings/subscription/tracking-links/modal-1", ".modal-footer button[type='submit']", "input[name='name']", "Select a model to save changes"),
    ("settings/subscription/promotion-campaign/modal-1", ".modal-footer button[type='submit']", None, "Select a model to save changes"),
    ("settings/subscription/trial-links/modal-1", ".modal-footer button[type='submit']", None, "Select a model to save changes"),
    ("new-post/state-promotion", ".modal-footer button[type='submit']", None, "Select a model to save changes"),
    ("new-post/state-trial-link", ".modal-footer button[type='submit']", None, "Select a model to save changes"),
    ("home/state-promotion", ".modal-footer button[type='submit']", None, "Select a model to save changes"),
    ("streaming/dashboard/create", ".g-page__header > button.g-btn", None, "Select a model to save changes"),
]
SECTIONS=("new-post","home","streaming","profile","queue","collections","notifications","statements","statistics","messages","vault","bank","settings")
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
def stand_in_re():
    """OfMirrorFrame's stand-in pages: STAND_IN_SRC of app/lib/ofMirrorProfile.ts, read as text (a JS regex literal)."""
    src=open(os.path.join(ROOT,"app/lib/ofMirrorProfile.ts")).read()
    m=re.search(r"^const STAND_IN_SRC = /(.+)/;$", src, re.M)
    if not m: sys.exit("dead.py: STAND_IN_SRC not found in app/lib/ofMirrorProfile.ts")
    return re.compile(m[1].replace("\\/", "/"))
STAND_IN_SRC=stand_in_re()
def stands_in(page): return bool(STAND_IN_SRC.match(f"/of-mirror/pages/{page}.html"))
# The model a stand-in page shows in All Creators: the first mocked account with a session (session(), /admin/accounts).
STAND_IN="acc1"
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
    window.__dead = list;
    return list.length;
  };
  window.__deadProbe = (i) => {
    const [el, target] = window.__dead[i];
    document.getElementById('oi-note')?.remove(); // only a note this click causes counts (and the layout is the one clicked)
    if (!el.isConnected || el.matches(':disabled') || !vis(target)) return { skip: desc(el) };
    target.scrollIntoView({ block: 'center', inline: 'center' });
    const r = target.getBoundingClientRect();
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
             what: desc(el) + (own ? '' : ` (on top: ${desc(hit)})`), state: snap(el), selected: el.matches('.b-month-day-cell.selected') };
  };
  window.__deadState = (i) => { const e = window.__dead[i][0]; return e.isConnected ? snap(e) : null; };
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
    pg=ctx.new_page()
    sent=[]; choosers=[]
    def mock(route):
        req=route.request; u=req.url; path=urlparse(u).path
        # Page routes win over the context's: a foreign URL matching a mock pattern still fails the check.
        if foreign(u): return outside(route)
        if req.method!="GET" and path.startswith("/api/"):
            sent.append((req.method, path, req.headers.get("x-account-id"), req.post_data))
            return route.fulfill(status=200, content_type="application/json", body="{}")
        if path=="/img": return route.fulfill(status=200, content_type="image/png", body=PIXEL)
        if req.method=="GET" and path in SOURCES:
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(SOURCES[path]))
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
    return pg, sent, choosers, errs
def open_page(pg, page):
    """Load the page's /of-manager URL; the frame once loaded, bound and settled, with the helpers installed (or None)."""
    pg.goto(f"{BASE}{url_of(page)}", wait_until="load", timeout=90000)
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
    failures.append(f"{page}: NO IFRAME (url {pg.url})"); return None
def navigated(pg, page):
    u=urlparse(pg.url)
    return (u.path!=url_of(page) or u.query) and u  # a link to the page itself with a query (?row=) changes the URL too
def outcome(pg, fr, page, i, probe, sent, choosers, before):
    """The click's first outcome within 1s: ("write"|"chooser"|"nav"|"note"|"changed", detail) or (None, None)."""
    n_sent, n_choosers=before
    for _ in range(20):
        if len(sent)>n_sent: return "write", sent[n_sent:]
        if len(choosers)>n_choosers: return "chooser", None
        if (u:=navigated(pg, page)): return "nav", u
        try:
            text=fr.evaluate(NOTE)
            if text is not None: return "note", text
            if probe["kind"]=="wired" and fr.evaluate("i => window.__deadState(i)", i)!=probe["state"]: return "changed", None
        except Exception: pass  # the frame went away: a navigation, seen on the next round
        pg.wait_for_timeout(50)
    return None, None
def send_controls(pg, page, sent, choosers):
    """All Creators: each send control of the page, made sendable, clicked at its centre; its outcome must be exactly its note."""
    got=[]; want=[]
    for _, sel, field, note in [s for s in SEND if s[0]==page and not stands_in(page)]:
        fr=open_page(pg, page)
        if not fr: return
        if field: fr.locator(field).fill("Alpha One")
        i=fr.evaluate("sel => (window.__deadList(), window.__dead.findIndex(([e]) => e.matches(sel)))", sel)
        probe=fr.evaluate("i => window.__deadProbe(i)", i) if i>=0 else {"skip":"not found, or disabled"}
        if "skip" in probe: got.append([sel, "skipped: "+probe["skip"]])
        else:
            box=pg.locator(f"iframe[src='/of-mirror/pages/{page}.html']").bounding_box()
            pg.mouse.click(box["x"]+probe["x"], box["y"]+probe["y"])
            kind, out=outcome(pg, fr, page, i, probe, sent, choosers, (len(sent), len(choosers)))
            got.append([sel, out if kind=="note" else kind])
        want.append([sel, note])
    if want: check(f"{page}: all creators: send controls give exactly their note", got, want)
def sweep(b, scope, only=()):
    """Every signed-off page in one scope (`model:1`, or None for All Creators: the scope key removed before every load)."""
    scope_js=f"localStorage.setItem('chatterly:scope','{scope}')" if scope else "localStorage.removeItem('chatterly:scope')"
    pg, sent, choosers, errs=session(b, scope_js)
    todo=[p for p in pages() if not only or any(p==o or p.startswith(o.rstrip("/")+"/") for o in only)]
    check(f"{scope or 'all creators'}: pages swept", bool(todo), True)
    totals={"controls":0,"links":0,"wired":0,"readonly":0}
    by_page=[]   # All Creators: (page, the writes made while it was swept)
    for page in todo:
        w0=len(sent)
        if urlparse(pg.url).hostname in LOCAL: pg.evaluate("sessionStorage.clear()")
        fr=open_page(pg, page)
        if not fr: continue
        marks=[]
        for applies, sel, shown, n in MARKED:
            # Single Creator only: in All Creators the Co-tag rows and vault tiles are hidden (no Data part rows).
            if scope and applies(page):
                got=fr.evaluate("([sel, shown]) => [...document.querySelectorAll(sel)].filter(e => !shown || e.checkVisibility()).map(e => e.hasAttribute('data-oi-wired'))", [sel, shown])
                marks.append([sel, got==[True]*n, got])
        if marks: check(f"{page}: Ground truth 5 Wired controls carry data-oi-wired", [m[:2] for m in marks], [[m[0], True] for m in marks])
        for _, sel, text in [d for d in DISABLED if d[0]==page]:
            got=fr.evaluate("([sel, text]) => [...document.querySelectorAll(sel)].filter(e => e.textContent.trim() === text).map(e => [e.disabled, e.title])", [sel, text])
            check(f"{scope or 'all creators'} {page}: {text} is disabled with the tooltip", got, [[True, NOT_YET]])
        # An open menu's own items take their clicks: none lies under the backdrop (My profile's More menu once did, inside
        # the content column's stacking context, so Statistics and Copy link went back to the profile).
        if (menu:=fr.evaluate(MENU_HIT)) is not None: check(f"{scope or 'all creators'} {page}: the open menu's items are over the backdrop", menu, [])
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
            before=(len(sent), len(choosers))
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
                    if w[:2] not in ALLOWED and not (w[0]=="POST" and FINISH.match(w[1])): off_list.append([what, w[0], w[1]])
                    if probe["kind"]!="wired": unmarked_writes.append([what, w[0], w[1]])
            elif kind=="nav":
                if got.hostname not in LOCAL or not got.path.startswith(M+"/"): silent.append([what, f"navigated to {pg.url}"])
            elif kind=="note":
                if not shot: pg.screenshot(path=f"{SHOTS}/inapp-dead-{page.replace('/','__')}.png"); shot=True
                if probe["kind"]=="link": silent.append([what, f"link shows note {got!r}"])
                elif probe["kind"]=="wired":
                    if got==READ_ONLY: wired_ro.append(what)
                elif got==READ_ONLY: counts["readonly"]+=1
                else: silent.append([what, f"note {got!r}"])
            elif kind in ("chooser","changed"):
                if probe["kind"]!="wired": silent.append([what, kind])
            elif not (probe["kind"]=="link" and probe["href"] in ("#", url_of(page))) and not (probe["kind"]=="wired" and probe["selected"]):
                silent.append([what, "no write, navigation or note within 1s"])
            i+=1
            if kind in ("write","nav"):
                fr=open_page(pg, page)
                if not fr: break
                if (again:=fr.evaluate("window.__deadList()"))!=total:
                    failures.append(f"{page}: {again} controls after a reload, {total} before"); break
        label=f"{scope or 'all creators'} {page}"
        check(f"{label}: no Silent control", silent, [])
        check(f"{label}: no Relay write from an unmarked control", unmarked_writes, [])
        check(f"{label}: no Relay write off the allow-list", off_list, [])
        check(f"{label}: no Wired control shows the Read-only note", wired_ro, [])
        check(f"{label}: no Wired control under a backdrop with nothing open over it", covered, [])
        print(json.dumps({"scope":scope or "all creators", "page":page, **counts}))
        for k in totals: totals[k]+=counts[k]
        if skipped: print(json.dumps({"scope":scope or "all creators","page":page,"skipped (hidden or gone by their turn)":skipped}))
        if not scope: send_controls(pg, page, sent, choosers)
        by_page.append((page, sent[w0:]))
    print(json.dumps({"scope":scope or "all creators", "pages":len(todo), **totals}))
    print(f"{scope or 'all creators'} relay writes:", [w[:3] for w in sent])
    if not scope:
        check("all creators: no non-GET /api/** request from a page that does not stand in",
              [[p, *w] for p, ws in by_page if not stands_in(p) for w in ws], [])
        check(f"all creators: a stand-in page's writes carry the stand-in's X-Account-Id ({STAND_IN})",
              [[p, *w[:3]] for p, ws in by_page if stands_in(p) for w in ws if w[2]!=STAND_IN], [])
    check(f"{scope or 'all creators'}: no console errors", [e[:160] for e in errs][:8], [])
    pg.context.close()
with sync_playwright() as p:
    b=p.chromium.launch()
    sweep(b, "model:1", sys.argv[1:])
    sweep(b, None, sys.argv[1:])
if failures:
    print("FAIL:", *failures, sep="\n  "); sys.exit(1)
print("dead ok")
