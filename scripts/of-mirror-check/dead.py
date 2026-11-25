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
LIST_ROWS="--list-rows" in ARGS
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
ALLOWED_RE=[("POST", re.compile(r"/api/of/v2/promotions/\d+/finish"))]
NOT_YET="Not available in Inflowwww yet"
DISABLED=[]
LOCAL=("localhost","127.0.0.1")
SOURCES={
    "/api/of/ofm-writes": {"on": True},
    "/api/of/v2/users/me": {"id":1,"username":"alphaone","name":"Alpha One"},
    "/api/of/v2/posts/tagged-friend-users": {"items":[{"id":901,"name":"Alpha One","type":"user","user":{"id":901,"name":"Alpha One","username":"alphaone"}}],"hasMore":False},
    "/api/of/v2/vault/media": {"list":[{"id":61,"type":"photo","createdAt":"2026-10-10T12:00:00Z","files":{"thumb":{"url":"https://cdn.example.invalid/v61.jpg"}}}],"hasMore":False},
}
V2={}
def v2_body(path, query):
    if path not in V2: return None
    param, default, other=V2[path]
    q={k: v[0] for k, v in parse_qs(query).items()}
    value=param(q) if callable(param) else q.get(param) if param else None
    return other.get(value, default)
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
    (lambda p: p.startswith("new-post/") or p=="streaming/dashboard/create", "[at-attr='add_event_widget']", False, 1),
    (lambda p: p.startswith("queue/saved-for-later-"), "[data-oi-add]", False, 2),
    (lambda p: p=="messages/send", "button[at-attr='scheduled_msg']", False, 1),
]
PHASE1=[]
SETTLE=5
def read_label(r):
    return f"{r['page']}: READS " + " > ".join(" ".join(map(str, s)) for s in r["steps"])
READS=[]
HANDOFF=[]
SWEEP_QUERY={}
def sweep_url(page):
    q=SWEEP_QUERY.get(page, "")
    return url_of(page)+(f"?{q}" if q else "")
MODULES=("dead_statistics", "dead_home", "dead_messages", "dead_settings", "dead_notifications", "dead_collections", "dead_content", "dead_vault",
         "dead_statements", "dead_golive")
def load(modules):
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
SWEPT=set()
load(MODULES)
HANDOFFS=[]
SECTIONS=("new-post","home","streaming","profile","queue","collections","notifications","statements","statistics","messages","vault","bank","settings")
if SWEEP_OUT:
    SECTIONS+=("release-forms",)
def pages():
    out=[]; section=None
    for line in open(os.path.join(ROOT,"app/lib/of-mirror-pages.ts")):
        if m:=re.match(r'^  "([^"]+)": \{', line): section=m[1]
        elif (m:=re.match(r'^      "([^"]*)": "', line)) and section:
            sub=m[1]
            if section in SECTIONS and f"{section}/{sub}" not in redirected():
                out.append(f"{section}/{sub or 'index'}")
    return out
def redirected():
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
    def handoff(route):
        HANDOFFS.append(route.request.url); route.abort()
    ctx.route(lambda url: url in HANDOFF, handoff)
    pg=ctx.new_page()
    sent=[]; choosers=[]; gets=[]
    def mock(route):
        req=route.request; u=req.url; path=urlparse(u).path
        # page routes win over the context's: a foreign URL matching a mock pattern must still fail
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
        elif u.split("?")[0].endswith("/admin/accounts"): route.fulfill(status=200, content_type="application/json", body='{"accounts":[{"id":"acc1","nickname":"Model One","has_session":true},{"id":"1","nickname":"Model Two","has_session":true}],"active_account_id":null}')
        elif "/chatter/me/accounts" in u: route.fulfill(status=200, content_type="application/json", body="[]")
        elif "/admin/employees" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"employees":[{"id":1,"display_name":"Tim","color":"#a78bfa","is_active":True,"chatter_id":None}]}))
        elif "/chatter/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"chatter":None,"owners":[]}))
        else: route.fulfill(status=200, content_type="application/json", body="[]")
    for pat in ["**/auth/**","**/chatter/**","**/admin/**","**/accounts**","**/api/**","**/img?**"]: pg.route(pat, mock)
    pg.route("**/events?**", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=""))
    pg.on("filechooser", lambda fc: choosers.append(fc))
    pg.on("download", lambda d: choosers.append(d))
    pg.on("dialog", lambda d: d.dismiss())
    errs=[]; pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
    pg.on("pageerror", lambda e: errs.append(f"uncaught: {e}"))
    return pg, sent, choosers, errs, gets
def open_page(pg, page, reopened=False, query=""):
    pg.goto(f"{BASE}{url_of(page)}"+(f"?{query}" if query else ""), wait_until="load", timeout=90000)
    want=f"/of-mirror/pages/{page}.html"
    for _ in range(80):
        card=pg.get_by_text("Tim", exact=True)
        if card.count(): card.first.click()
        fr=[f for f in pg.frames if urlparse(f.url).path==want]
        try:
            if fr and fr[0].evaluate("document.readyState")=="complete":
                pg.wait_for_timeout(800)
                fr[0].evaluate(HELPERS)
                return fr[0]
        except Exception: pass
        pg.wait_for_timeout(250)
    if SWEEP_OUT and not reopened:
        return open_page(pg, page, reopened=True, query=query)
    failures.append(f"{page}: NO IFRAME (url {pg.url})"); return None
def navigated(pg, page):
    u=urlparse(pg.url)
    return (u.path!=url_of(page) or u.query!=SWEEP_QUERY.get(page, "")) and u
def outcome(pg, fr, page, i, probe, sent, choosers, before):
    n_sent, n_choosers, n_handoffs=before
    for _ in range(20):
        if len(sent)>n_sent: return "write", sent[n_sent:]
        if len(choosers)>n_choosers: return "chooser", None
        if len(HANDOFFS)>n_handoffs: return "handoff", HANDOFFS[n_handoffs:]
        if (u:=navigated(pg, page)): return "nav", u
        try:
            text=fr.evaluate(NOTE)
            if text is not None: return "note", text
            if probe["kind"]=="wired" and fr.evaluate("i => window.__deadState(i)", i)!=probe["state"]: return "changed", None
            if probe["kind"]=="wired" and fr.evaluate("i => window.__deadFocus(i)", i):
                return "changed", None
        except Exception: pass
        pg.wait_for_timeout(50)
    return None, None
def phase1_verdict(found, status):
    if not found: return "not found"
    if status=="proven" and not all(m["wired"] and not m["ny"] for m in found):
        return f"not Wired: {sum(not m['wired'] for m in found)} unmarked, {sum(m['ny'] for m in found)} with the Not-yet title"
    if status=="not-yet" and not all(m["ny"] for m in found):
        return f"lost the Not-yet title: {sum(not m['ny'] for m in found)} of {len(found)} without it"
    return "ok" if status in ("pending","proven","not-yet") else f"unknown status {status!r}"
def not_yet(page, spec):
    return (page, spec, "not-yet") in PHASE1
def frame_now(pg):
    return next((f for f in pg.frames if f.parent_frame==pg.main_frame and urlparse(f.url).path.startswith("/of-mirror/pages/")), None)
def read_step(fr, s, ny=False):
    verb, spec, *text=s
    if verb=="back": return fr.evaluate("() => void parent.history.back()")
    if ny and (problem:=phase1_verdict(fr.evaluate("a => window.__deadFind(a)", [spec, NOT_YET]), "not-yet"))!="ok":
        return f"{spec}: {problem}"
    fr.evaluate("() => document.querySelectorAll('[data-oi-reads]').forEach((e) => e.removeAttribute('data-oi-reads'))")
    if not fr.evaluate("a => window.__deadUngrey(a)", [spec, NOT_YET]): return f"{spec}: not found"
    loc=fr.locator("[data-oi-reads]").first
    try:
        if verb=="click": loc.click(timeout=5000)
        elif verb=="fill": loc.fill(text[0], timeout=5000)
        elif verb=="press": loc.press(text[0], timeout=5000)
        elif verb=="set": loc.evaluate("(e, t) => { e.value = t; }", text[0])
        else: raise ValueError(f"unknown READS step {s!r}")
    except PwError as e: return f"{spec}: {verb} failed: {str(e).splitlines()[0]}"
def reads(pg, page, sent, gets):
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
            if r.get("get", ()) is None: return not [g for g in gets[g0:] if g[0].startswith("/api/")]
            return all(one(path, params, gets[g0:]) for path, params in r.get("get", []))
        snaps, first=[], None
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
        after=(tail or snaps or [None])[-1] or ""
        got={"settled":len(tail)==SETTLE and tail[0] is not None and len(set(tail))==1,
             "shows":all(x in after for x in r["shows"]), "writes":[list(w[:2]) for w in sent[s0:]]}
        want={"settled":True, "shows":True, "writes":[]}
        if "get" in r: got["get"]=hit(); want["get"]=True
        if "hides" in r: got["hides"]=not any(h in after for h in r["hides"]); want["hides"]=True
        check(label, got, want)
def sweep(b, scope, only=()):
    pg, sent, choosers, errs, gets=session(b, f"localStorage.setItem('chatterly:scope','{scope}')")
    h0=len(HANDOFFS)
    todo=[p for p in pages() if not only or any(p==o or p.startswith(o.rstrip("/")+"/") for o in only)]
    check(f"{scope}: pages swept", bool(todo), True)
    totals={"controls":0,"links":0,"wired":0,"readonly":0}
    found=[]
    opened_at=[]
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
            try: fr.evaluate("document.querySelector('.modal.show[data-oi-data]') && document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))")
            except Exception: pass
            what=f"#{i} {probe['what']}"
            counts["controls"]+=1
            if probe["kind"]=="link": counts["links"]+=1
            if probe["kind"]=="wired": counts["wired"]+=1
            if kind=="write":
                pg.wait_for_timeout(300)
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
            elif kind=="handoff":
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
    if HANDOFF: print(f"{scope} hand-offs (aborted):", HANDOFFS[h0:])
    if SWEEP_OUT:
        with open(SWEEP_OUT, "w") as f:
            json.dump(found, f, indent=1)
        print(json.dumps({"sweep-out": SWEEP_OUT, "pages": len(found)}))
    check(f"{scope}: no console errors", [e[:160] for e in errs][:8], [])
    pg.context.close()
def list_rows():
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
check("v2 mock: the probe answers an object", bool(v2_body("/api/of/v2/streaks/top", "")) and isinstance(v2_body("/api/of/v2/streaks/top", ""), dict), True)
check("v2 mock: a param's other values answer other rows than its default", [p for p, (_, d, o) in V2.items() if any(b==d for b in o.values())], [])
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
