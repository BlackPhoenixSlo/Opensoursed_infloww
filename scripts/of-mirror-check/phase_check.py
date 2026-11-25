import copy, json, os, re, sys
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.append(os.path.join(os.path.dirname(HERE), "of-live-proof"))
from proof_core import fill  # noqa: E402
from proof_core import Proof  # noqa: E402
from proof_core import NEVER_TITLED, NEVER_TITLED_SEP, OFM_NEW_WRITES  # noqa: E402
from proof_list import record_of, load_records, live_passed  # noqa: E402
from sweep_diff import LABEL_JS  # noqa: E402
BASE=f"http://localhost:{os.environ.get('PORT','3091')}"
M="/of-manager"
SHOTS="/tmp/of-mirror-shots"
ROOT=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAPTURES=os.path.join(ROOT,"docs","of-manager","captures")
LOCAL=("localhost","127.0.0.1")
NOT_YET="Not available in Inflowwww yet"
OFM_WRITES="/api/of/ofm-writes"
RED="rgb(255, 69, 69)"
SINGLE, SINGLE_ID="model:1", "1"
STAND_IN="acc1"
user={"user_id":"u1","username":"tester","is_admin":False}
NOTE="document.getElementById('oi-note')?.textContent ?? null"
NOTE_COLOR="document.getElementById('oi-note')?.style.color ?? null"
FIND=r"""(want) => {
  const vis = (e) => { const r = e.getBoundingClientRect(); return e.checkVisibility({ checkVisibilityCSS: true }) && r.width > 0 && r.height > 0; };
  const label = """+LABEL_JS+r""";
  const all = [...document.querySelectorAll('button, [role=button], input, select, textarea, a[href], [contenteditable], [title], [data-oi-wired]')]
    .filter((e) => vis(e) && !e.closest('.l-sidebar') && label(e) === want);
  return all.find((e) => e.matches('button, [role=button], input, select, textarea, a[href], [contenteditable]')) ?? all[0] ?? null;
}"""
STATE=r"""(e) => e === null ? [false, false, false] : [true,
  e.matches('[data-oi-wired]') || !!e.querySelector('[data-oi-wired]') || (e.matches('input[type=checkbox]') && !!e.closest('[data-oi-wired]'))
    || (e.matches('label[for]') && !!document.getElementById(e.htmlFor)?.matches('[data-oi-wired]')),  // ticket 57: a switch's label (its hidden checkbox Wired)
  !!e.closest('[title]') && e.closest('[title]').getAttribute('title') === %s]""" % json.dumps(NOT_YET)
failures=[]
def check(label, got, want):
    print(json.dumps({"check":label,"want":want,"got":got}))
    if got!=want: failures.append(f"{label}: got {got!r}, expected {want!r}")
def url_of(page):
    page, _, query=page.partition("?")
    section, _, sub=page.partition("/")
    return f"{M}/{section}" + ("" if sub=="index" else f"/{sub}") + (f"?{query}" if query else "")
def from_record(rec, values=None):
    req=rec["request"]; values=values or {}
    return [req["method"], "/api/of/v2/"+fill(req["path"], values).split("/api2/v2/",1)[1], fill(req.get("body"), values)]
def multipart(req):
    ctype=req.headers.get("content-type") or ""
    if not ctype.startswith("multipart/form-data"): return None
    from email.parser import BytesParser
    from email.policy import HTTP
    msg=BytesParser(policy=HTTP).parsebytes(b"Content-Type: "+ctype.encode()+b"\r\n\r\n"+(req.post_data_buffer or b""))
    out={}
    for part in msg.iter_parts():
        name, fname=part.get_param("name", header="content-disposition"), part.get_filename()
        out[name]={"type": part.get_content_type(), "ext": os.path.splitext(fname)[1]} if fname is not None else part.get_content()
    return out
ACCOUNTS=[{"id":"acc1","nickname":"Model One","has_session":True},{"id":"1","nickname":"Model Two","has_session":True}]
def session(b, scope_js, reads, after, fail, init="", gets=None, switch=True, accounts=ACCOUNTS):
    ctx=b.new_context(viewport={"width":1440,"height":900})
    ctx.add_init_script(scope_js)
    if init: ctx.add_init_script(init)
    foreign=lambda url: urlparse(url).hostname not in LOCAL
    def outside(route):
        failures.append(f"request to a non-localhost host: {route.request.url[:120]}"); route.abort()
    ctx.route(foreign, outside)
    pg=ctx.new_page()
    sent=[]
    def mock(route):
        req=route.request; u=req.url; path=urlparse(u).path
        if foreign(u): return outside(route)
        if gets is not None and req.method=="GET" and path.startswith("/api/"): gets.append((path, urlparse(u).query, req.headers.get("x-account-id")))
        if req.method!="GET" and (path.startswith("/api/") or path.startswith("/admin/")):
            body=multipart(req)
            if body is None:
                try: body=req.post_data_json if req.post_data else None
                except Exception: body=req.post_data
            if not (path.startswith("/admin/perflog/") or path=="/admin/view-lease"): sent.append([req.method, path, req.headers.get("x-account-id"), body])
            if fail.get("route")==[req.method, path]:
                return route.fulfill(status=fail["status"], content_type="application/json", body=fail.get("body", '{"detail":"synthetic failure"}'))
            answer={"success":True}
            for m, rx, fn in after:
                if m==req.method and (hit:=re.fullmatch(rx, path)):
                    if isinstance(got:=fn(reads, hit, body), (dict, list)): answer=got
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(answer))
        if req.method=="GET" and path==OFM_WRITES:
            return route.fulfill(status=200 if switch else 404, content_type="application/json", body=json.dumps({"on": True} if switch else {"detail": "Not Found"}))
        if req.method=="GET" and path in reads:
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(reads[path]))
        if "/auth/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps(user))
        elif u.split("?")[0].endswith("/admin/accounts"): route.fulfill(status=200, content_type="application/json", body=json.dumps({"accounts":accounts,"active_account_id":None}))
        elif "/chatter/me/accounts" in u: route.fulfill(status=200, content_type="application/json", body="[]")
        elif "/admin/employees" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"employees":[{"id":1,"display_name":"Tim","color":"#a78bfa","is_active":True,"chatter_id":None}]}))
        elif "/chatter/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"chatter":None,"owners":[]}))
        else: route.fulfill(status=200, content_type="application/json", body="[]")
    for pat in ["**/auth/**","**/chatter/**","**/admin/**","**/accounts**","**/api/**"]: pg.route(pat, mock)
    pg.route("**/events?**", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=""))
    pg.on("dialog", lambda d: d.accept())
    errs=[]; pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
    pg.on("pageerror", lambda e: errs.append(f"uncaught: {e}"))
    return pg, sent, errs
def drop_cache(pg):
    pg.goto(f"{BASE}/of-mirror/pages/home/index.html", wait_until="load", timeout=90000)
    pg.evaluate("() => new Promise(r => { const q = indexedDB.deleteDatabase('chatterly-rq'); q.onsuccess = q.onerror = q.onblocked = () => r(); })")
def with_reads(reads, extra, pg=None):
    saved={k: reads[k] for k in extra if k in reads}
    reads.update(copy.deepcopy(extra))
    if extra and pg: drop_cache(pg)
    def restore():
        for k in extra:
            if k in saved: reads[k]=saved[k]
            else: reads.pop(k, None)
        if extra and pg: drop_cache(pg)
    return restore
def open_page(pg, page):
    if urlparse(pg.url).hostname in LOCAL: pg.evaluate("sessionStorage.clear()")
    pg.goto(f"{BASE}{url_of(page)}", wait_until="load", timeout=90000)
    want=f"/of-mirror/pages/{page.partition('?')[0]}.html"
    for _ in range(80):
        card=pg.get_by_text("Tim", exact=True)
        if card.count(): card.first.click()
        fr=[f for f in pg.frames if urlparse(f.url).path==want]
        try:
            if fr and fr[0].evaluate("document.readyState")=="complete":
                pg.wait_for_timeout(800)
                return fr[0]
        except Exception: pass
        pg.wait_for_timeout(250)
    failures.append(f"{page}: NO IFRAME (url {pg.url})"); return None
def locate(fr, label):
    return fr.query_selector(label[4:]) if label.startswith("css=") else fr.evaluate_handle(FIND, label).as_element()
def landmark(scope, pg, page, label):
    fr=open_page(pg, page)
    check(f"{scope}: {page} shows {label!r}", fr is not None and (el:=locate(fr, label)) is not None and el.is_visible(), True)
def act(fr, steps):
    for step in steps:
        label, text=(step, None) if isinstance(step, str) else step
        for _ in range(50):
            if (el:=locate(fr, label)) is not None: break
            fr.page.wait_for_timeout(100)
        if el is None: return f"{label!r} not found"
        try:
            if text is None: el.click(timeout=5000)
            else: el.fill(text, timeout=5000)
        except Exception as e: return f"{label!r}: {str(e).splitlines()[0][:120]}"
        fr.page.wait_for_timeout(300)
    return None
def settle(pg, sent, n, want):
    for _ in range(15 if want else 10):
        if want and len(sent)>=n+want: break
        pg.wait_for_timeout(100)
    pg.wait_for_timeout(300)
def shot(pg, name, i, page):
    pg.screenshot(path=f"{SHOTS}/inapp-{name}-{i:02d}-{re.sub(r'[/?=&]', '-', page)}.png")
def console(label, errs, statuses):
    planted=[e for e in errs if not any(f"status of {s}" in e and e.startswith("Failed to load resource") for s in statuses)]
    check(f"{label}: no console errors", [e[:160] for e in planted][:8], [])
def single(b, name, t, records, reads, after, init="", pages=None):
    fail={}
    pg, sent, errs=session(b, f"localStorage.setItem('chatterly:scope','{SINGLE}')", reads, after, fail, init)
    n_shot=0
    view=lambda p: t["views"].get(p.id, p.page)
    for page in dict.fromkeys(view(p) for p in t["proofs"]):
        fr=open_page(pg, page)
        if not fr: continue
        for proof in [p for p in t["proofs"] if view(p)==page]:
            _, rec, problem=record_of(proof, records)
            check(f"{proof.id}: one capture record", problem, None)
            if NEVER_TITLED in proof.tags:
                for label in proof.control.split(NEVER_TITLED_SEP):
                    found, wired, titled=fr.evaluate(f"(want) => ({STATE})(({FIND})(want))", label)
                    href=fr.evaluate(f"(want) => ({FIND})(want)?.closest('a[href]')?.getAttribute('href') ?? null", label)
                    opener=href in {url_of(s[1]) for s in proof.trigger if s[0]=="frame"}
                    check(f"{proof.id} {page} {label!r}: found, Wired or a State page opener ({href}), never Not-yet titled",
                          [found, wired or opener, titled], [True, True, False])
                continue
            got=fr.evaluate(f"(want) => ({STATE})(({FIND})(want))", proof.control)
            titled=not live_passed(rec)
            check(f"{proof.id} {page} {proof.control!r}: found, Wired, Not-yet title {'kept' if titled else 'dropped'} ({'no Live-proof pass' if titled else 'Live-proof pass'})",
                  got, [True, True, titled])
        n_shot+=1; shot(pg, name, n_shot, page)
    by_id={p.id: p for p in t["proofs"]}
    for row in t["requests"]:
        if "want" not in row:
            proof=by_id.get(row.get("proof"))
            _, rec, problem=record_of(proof, records) if proof else (None, None, f"{row.get('proof')}: not in the proof list")
            check(f"{row.get('proof')}: one capture record for the request row", problem, None)
            if problem: continue
            row={"page": proof.page, **row, "want": [from_record(rec, row.get("fill"))]}
        want=row["want"]
        fr=open_page(pg, row["page"])
        if not fr: continue
        n=len(sent)
        if row.get("prep"): fr.evaluate(row["prep"])
        check(f"{row['page']} {row['steps']}: steps run", act(fr, row["steps"]), None)
        settle(pg, sent, n, len(want))
        check(f"{row['page']} {row['steps']}: sends exactly the capture's request with X-Account-Id {SINGLE_ID}",
              sent[n:], [[m, p, SINGLE_ID, body] for m, p, body in want])
        if row.get("opens"):
            for _ in range(30):
                if (u:=urlparse(pg.url)).path+(f"?{u.query}" if u.query else "")==row["opens"]: break
                pg.wait_for_timeout(100)
            check(f"{row['page']} {row['steps']}: opens {row['opens']}", u.path+(f"?{u.query}" if u.query else ""), row["opens"])
        if row.get("after"):
            js, value=row["after"]
            for _ in range(30):
                if (got:=fr.evaluate(js))==value: break
                pg.wait_for_timeout(100)
            check(f"{row['page']} {row['steps']}: read-back {js}", got, value)
        n_shot+=1; shot(pg, name, n_shot, row["page"])
    for row in t["red_notes"]:
        restore=with_reads(reads, row.get("reads", {}), pg)
        fr=open_page(pg, row["page"])
        if not fr: restore(); continue
        if row.get("fail"): fail.update(route=list(row["fail"]), status=row.get("status", 502))
        if "body" in row: fail["body"]=json.dumps(row["body"])
        what=f"{row['page']} {row['steps']} ({row['fail'][0]} {row['fail'][1]} -> {fail['status']})" if row.get("fail") else f"{row['page']} {row['steps']} (no write failed)"
        if row.get("prep"): fr.evaluate(row["prep"])
        kept=fr.evaluate(row["kept"]) if row.get("kept") else None
        n=len(sent)
        check(f"{what}: steps run", act(fr, row["steps"]), None)
        for _ in range(15):
            if fr.evaluate(NOTE) is not None: break
            pg.wait_for_timeout(100)
        got=[fr.evaluate(NOTE_COLOR), fr.evaluate(row["kept"]) if row.get("kept") else None]
        want=[RED, kept]
        if "note" in row: got.append(fr.evaluate(NOTE)); want.append(row["note"])
        check(f"{what}: red note, page in its last saved state", got, want)
        if "sent" in row:
            pg.wait_for_timeout(300)
            check(f"{what}: sends exactly", sent[n:], [[m, p, SINGLE_ID, body] for m, p, body in row["sent"]])
        fail.clear(); restore()
        n_shot+=1; shot(pg, name, n_shot, row["page"])
    for page, label in (pages or {}).items():
        landmark("single creator", pg, page, label)
        n_shot+=1; shot(pg, name, n_shot, page)
    if not (t["proofs"] or t["requests"] or t["red_notes"] or pages):
        check("single creator: home/index frame loads", open_page(pg, "home/index") is not None, True)
        shot(pg, name, 0, "home/index")
    console("single creator", errs, {r.get("status", 502) for r in t["red_notes"] if r.get("fail")})
    print("single creator relay writes:", sent)
    pg.context.close()
ANCHORS={"messages/chat": ".b-chat__message.m-from-me[data-oi-msg]"}
ANCHOR_WAIT_MS=5000
def anchor_of(t, proof):
    return t["anchors"].get(proof.id) or ANCHORS.get(t["views"][proof.id].partition("?")[0])
def anchored(fr, sel):
    for _ in range(ANCHOR_WAIT_MS//100):
        if fr.query_selector(sel) is not None: return True
        fr.page.wait_for_timeout(100)
    return False
def switch_off(b, name, t, reads, after, init=""):
    gated=[p for p in t["proofs"] if OFM_NEW_WRITES in p.tags]
    if not gated: return
    pg, sent, errs=session(b, f"localStorage.setItem('chatterly:scope','{SINGLE}')", copy.deepcopy(reads), after, {}, init, switch=False)
    view=lambda p: t["views"].get(p.id, p.page)
    for i, page in enumerate(dict.fromkeys(view(p) for p in gated), 1):
        fr=open_page(pg, page)
        if not fr: continue
        for proof in [p for p in gated if view(p)==page]:
            drawn=proof.id not in t["views"]
            if not drawn:
                sel=anchor_of(t, proof)
                check(f"{proof.id} {page}, OFM_NEW_WRITES_ENABLED off: anchor {sel!r} drawn (the page drew its data)",
                      bool(sel) and anchored(fr, sel), True)
            check(f"{proof.id} {page} {proof.control!r}, OFM_NEW_WRITES_ENABLED off: "+("found, not Wired, Not-yet title kept" if drawn else "not drawn (main)"),
                  fr.evaluate(f"(want) => ({STATE})(({FIND})(want))", proof.control), [True, False, True] if drawn else [False, False, False])
        shot(pg, f"{name}-switch-off", i, page)
    check("single creator, OFM_NEW_WRITES_ENABLED off: no Relay write", sent, [])
    console("single creator, OFM_NEW_WRITES_ENABLED off", errs, {404})
    pg.context.close()
ONE_ACCOUNTS=[{"id":"acc0","nickname":"Model Zero","has_session":True,"session_dead_at":"2026-01-01T00:00:00Z"}, *ACCOUNTS]
ONE_PAGE="home/index"
ONE_STEPS=[["css=[contenteditable][aria-label='Textbox field']", "Synthetic post"], "css=button[at-attr='submit_post']"]
ONE_WANT=[["POST", "/api/of/v2/posts", STAND_IN, {"text":"Synthetic post","media_files":[],"price":0}]]
def one_creator(b, name, reads):
    pg, sent, errs=session(b, "localStorage.setItem('chatterly:scope','all')", reads, [], {}, accounts=ONE_ACCOUNTS)
    fr=open_page(pg, ONE_PAGE)
    if fr:
        n=len(sent)
        check(f"saved all scope {ONE_PAGE}: steps run", act(fr, ONE_STEPS), None)
        settle(pg, sent, n, 1)
        check(f"saved all scope {ONE_PAGE}: Post sends as the first Creator with a live session ({STAND_IN})", sent[n:], ONE_WANT)
        check("saved all scope: the stand-in is not saved", pg.evaluate("localStorage.getItem('chatterly:scope')"), "all")
        shot(pg, name, 0, "one-creator-"+ONE_PAGE)
    console("saved all scope", errs, set())
    pg.context.close()
def run(name, proofs=(), requests=(), red_notes=(), reads=None, after=(), argv=None, init="", pages=None, one_creator_pass=False,
        views=None, handoffs=(), anchors=None):
    """The Phase's check: its tables, plus --plant's rows (and one_creator with `one_creator_pass`); exit 1 on a failed check."""
    args=list(sys.argv[1:] if argv is None else argv)
    plant, captures={}, CAPTURES
    if "--plant" in args:
        i=args.index("--plant"); plant=json.load(open(args[i+1])); del args[i:i+2]
    if "--captures" in args:
        i=args.index("--captures"); captures=args[i+1]; del args[i:i+2]
    if args: sys.exit(f"{name}: unknown arguments {args}")
    t={"proofs":[*proofs, *(Proof(**{"phase": 2, **p}) for p in plant.get("proofs", []))], "requests":[*requests, *plant.get("requests", [])],
       "red_notes":[*red_notes, *plant.get("red_notes", [])], "views":dict(views or {}), "anchors":dict(anchors or {}),
       "handoffs":[*handoffs, *plant.get("handoffs", [])]}
    if not os.path.isdir(captures): sys.exit(f"{name}: {captures} is not a directory")
    records, bad=load_records(Path(captures))
    check("capture records are valid JSON", bad, [])
    planted=plant.get("records", {})
    records=[r for r in records if r[0] not in planted]+list(planted.items())
    os.makedirs(SHOTS, exist_ok=True)
    reads={"/api/of/v2/users/me": {"id":1,"username":"alphaone","name":"Alpha One"}, **(reads or {})}
    init="\n".join(x for x in (init, plant.get("init", "")) if x)
    with sync_playwright() as p:
        b=p.chromium.launch()
        single(b, name, t, records, copy.deepcopy(reads), list(after), init, pages)
        switch_off(b, name, t, copy.deepcopy(reads), list(after), init)
        if one_creator_pass: one_creator(b, name, copy.deepcopy(reads))
        if t["handoffs"]: handoff_rows(b, name, t["handoffs"], reads, list(after), init)
    if failures:
        print("FAIL:", *failures, sep="\n  "); sys.exit(1)
    print(f"{name} ok")

HANDOFF_TITLE="opens onlyfans.com"
HANDOFF_ATTRS="(a) => [a.tagName, a.href, a.target, a.rel, a.hasAttribute('data-oi-wired'), a.title, a.getAttribute('aria-disabled'), a.textContent.trim()]"
def handoff_rows(b, name, rows, reads, after, init=""):
    scope="single creator"
    r_reads=copy.deepcopy(reads)
    pg, sent, errs=session(b, f"localStorage.setItem('chatterly:scope','{SINGLE}')", r_reads, after, {}, init)
    urls={r["handoff"] for r in rows}; opened=[]
    def handoff(route):
        opened.append(route.request.url); route.abort()
    pg.context.route(lambda u: u in urls, handoff)
    for i, row in enumerate(rows, 1):
        restore=with_reads(r_reads, row.get("reads", {}), pg)
        fr=open_page(pg, row["page"])
        if not fr: restore(); continue
        what=f"{scope} {row['page']} {row['steps']} -> {row['handoff']}"
        check(f"{what}: steps up to the hand-off run", act(fr, row["steps"][:-1]), None)
        el=locate(fr, row["steps"][-1])
        check(f"{what}: an <a>, new tab, noopener noreferrer, Wired, {HANDOFF_TITLE!r}, not disabled",
              el.evaluate(HANDOFF_ATTRS) if el else None, ["A", row["handoff"], "_blank", "noopener noreferrer", True, HANDOFF_TITLE, None, row["text"]])
        shot(pg, f"{name}-handoff-single", 2*i-1, row["page"])
        n, h=len(sent), len(opened)
        if el:
            try: el.click(timeout=5000)
            except Exception as e: failures.append(f"{what}: click: {str(e).splitlines()[0][:120]}")
        for _ in range(20):
            if len(opened)>h: break
            pg.wait_for_timeout(100)
        pg.wait_for_timeout(300)
        loaded=[f.url for p in pg.context.pages for f in p.frames if f.url==row["handoff"]]
        check(f"{what}: a popup to exactly the URL (aborted, never loaded), nothing sent", [opened[h:], loaded, sent[n:]], [[row["handoff"]], [], []])
        shot(pg, f"{name}-handoff-single", 2*i, row["page"])
        for p in pg.context.pages:
            if p is not pg: p.close()
        restore()
    console(f"{scope} hand-offs", errs, set())
    print(f"{scope} hand-offs (aborted):", opened, "relay writes:", sent)
    pg.context.close()
