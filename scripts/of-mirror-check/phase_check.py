"""phase_check: the shared harness of a Phase's in-app Mirror check (content_writes.py for Phase 2, golive.py for Phase
4). A Phase file holds only its tables and calls run(); the harness is writes.py's and collections_writes.py's.

Mocks the login (as writes.py, the Single-Creator card "Tim"), /admin/accounts with acc1 and 1, both with a session
(one_creator's: acc0 with a dead session first), GET /api/of/v2/users/me (synthetic),
the Phase's `reads` (GET path -> JSON), the OFM_NEW_WRITES_ENABLED probe GET /api/of/ofm-writes answered on (as
of-live-proof's prove.py runs the Relay; a session's `switch` False: 404, the switch off) and [] for every other GET /api/**. Every non-GET /api/** and /admin/** request is
recorded as [method, path, X-Account-Id, JSON body] and answered {"success": true}, after the Phase's `after` hooks
((method, path regex, fn(reads, match, body))) changed `reads`, so the write's read-back shows what it changed; a hook
that returns a dict or list answers the write with it instead (an upload's claim). A multipart body is recorded as
{part name: text, or for a file part {"type": its content type, "ext": its file name's extension}} (a recording's
name carries a timestamp). The Phase's `init` script, when given, runs in every page and frame before its own. Any
request to a host other than localhost is aborted and fails the check. Prints one {"check","want","got"} line per check;
exit 1 on a failure. Screenshots: /tmp/of-mirror-shots/inapp-<name>-*.png only.

Tables (plain lists and dicts, so a JSON plant reads like the Phase file's own rows):
  proofs        the Phase's proof list (scripts/of-live-proof/proofs/phase<N>.py PROOFS), its control list: check 1,
                runtime state only (D18), Single Creator (scope `model:1`): each proof has exactly one capture record,
                found as `proof_list.py --check-sweep` finds it (label == control, page in pages); its control (the
                visible element whose Not-yet sweep label, sweep_diff.LABEL_JS, is `control`) is found and Wired
                (data-oi-wired on it or a part of it; a checkbox inside a mark; a label whose field has it); with that record's Live-proof pass
                (proof_list.live_passed) it has no Not-yet title, else it still has it (D1). A `never-titled` proof
                (ticket 35): each label of its joined `control` found, Wired or a State page opener (a link to another
                /of-manager page, whose Wired controls are there), and untitled whatever the pass. An
                `ofm_new_writes` proof (proof_core OFM_NEW_WRITES): also, in a pass of its own with
                OFM_NEW_WRITES_ENABLED off (GET /api/of/ofm-writes answered 404, as the Relay's switch off), its
                control is found, not Wired and keeps the Not-yet title, and that pass sends nothing.
  requests      {"page", "steps", "want": [[method, path, body]] | "proof": id, "fill": {...}}: Single Creator; the
                steps send exactly `want`, or the proof's capture record's request with `fill` applied, each with
                X-Account-Id "1"; "page" defaults to the proof's; "after": [js, value] checks the read-back;
                "opens": "/of-manager/<path>[?query]" checks the steps took the app there (a State page opener).
  red_notes     {"page", "steps", "fail": [method, path], "status": 502, "note"?, "kept"?: js}: Single Creator; with
                that write answered `status`, #oi-note shows red (#ff4545), its text `note` when given, and the `kept`
                expression reads the same before and after (the page stays in its last saved state). "fail" may be
                left out (the note comes from the page, e.g. a refused camera); "sent": [[method, path, body]] checks
                exactly those writes went out during the row (with X-Account-Id "1"; [] = nothing sent). "reads"
                (GET path -> JSON, ticket 60): served for this row only, over the pass's (with_reads). "body" (ticket
                63): the failed answer's JSON, default {"detail": "synthetic failure"} (e.g. OF's session-lost answer).
A row's "prep" (requests, red_notes): a JS expression run in the frame before its steps, and before a red_notes row's
"kept" is read (e.g. a refusing getUserMedia, or a seeded draft).
A step is a control's label (clicked) or [label, text] (typed into it); a label "css=<selector>" names a field the
sweep labels only by its tag or classes. A row's "page" may carry a query ("messages/chat/state-price?chat=9001"),
loaded with it. run()'s `pages` ({page: landmark}, a landmark being a step's label): each page loaded in Single Creator
whatever the tables hold, its landmark shown (a 404 or blank page fails); with no rows and no `pages`, the pass loads
home/index. No console errors.
No All-Creators pass: OF Manager has no All creators (owner 2026-11-20). one_creator instead: with a saved "all" scope
OF Manager shows one Creator (OneCreator, app/components/of-manager/OfManagerChrome.tsx: the first with a live session),
unsaved, so home/index (not a stand-in page, app/lib/ofMirrorProfile.ts STAND_IN_SRC) posts as acc1. It runs once:
run(..., one_creator_pass=True) from golive.py only (the cheapest Phase check).

--plant <file.json> adds proofs ({"proofs": [{"id", "page", "control", "kind", "phase"?}]}, phase 2 unless given),
rows ({"requests", "red_notes"}), capture records ({"records": {file name: record}}, replacing a capture file of that name) and an "init"
script (run after the Phase's, e.g. to mark a control Wired) to the Phase's, to show a check fails; --captures <dir>
reads the records from <dir> instead of docs/of-manager/captures.
"""
import copy, json, os, re, sys
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# Every import below is stdlib only (the check runs under python3 -I). proof_list/capture_record push of-live-proof to
# the front of sys.path when imported, so a same-named module in of-mirror-check would be shadowed: keep names distinct.
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
OFM_WRITES="/api/of/ofm-writes"   # app/lib/ofMirrorNewWrites.ts OFM_WRITES_PATH: {"on": true} only with the switch on
RED="rgb(255, 69, 69)"   # ofMirrorWrites.note(..., error=true): #ff4545
SINGLE, SINGLE_ID="model:1", "1"
STAND_IN="acc1"           # one_creator: the first mocked account with a live session
user={"user_id":"u1","username":"tester","is_admin":False}
NOTE="document.getElementById('oi-note')?.textContent ?? null"
NOTE_COLOR="document.getElementById('oi-note')?.style.color ?? null"
# The control by its Not-yet sweep label (sweep_diff.LABEL_JS, dead.py's own):
# ASSUMPTION: the first visible match in document order is the control, a real control (button, field, link) before a
# titled wrapper (rung 5); overturned by a Phase 2 page with two visible controls of one label, which then needs a
# selector column in its table.
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
    """[method, Relay path, body] of a capture record's request: OF's /api2/v2/<p> is the Relay's /api/of/v2/<p> (spec Contracts)."""
    req=rec["request"]; values=values or {}
    return [req["method"], "/api/of/v2/"+fill(req["path"], values).split("/api2/v2/",1)[1], fill(req.get("body"), values)]
def multipart(req):
    """A multipart body as {part name: text | {"type", "ext"}} (stdlib email parser, as post_upload.py), else None."""
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
    # ticket 57: `gets` (a list), when given, records every GET /api/** as dead.py does: (path, query, X-Account-Id).
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
        if gets is not None and req.method=="GET" and path.startswith("/api/"): gets.append((path, urlparse(u).query, req.headers.get("x-account-id")))  # ticket 57
        if req.method!="GET" and (path.startswith("/api/") or path.startswith("/admin/")):
            body=multipart(req)
            if body is None:
                try: body=req.post_data_json if req.post_data else None
                except Exception: body=req.post_data  # not JSON: its raw text
            # ASSUMPTION: the app's own perf telemetry (POST /admin/perflog/ingest, every page load) is no write and is not
            # recorded (rung 5); overturned if a Phase 2 control is meant to write under /admin/perflog.
            # ASSUMPTION (ticket 30): the app's view lease (POST /admin/view-lease, app/lib/viewLease.ts, a heartbeat while a
            # page stays open) is no write either and is not recorded (rung 5); overturned likewise.
            if not (path.startswith("/admin/perflog/") or path=="/admin/view-lease"): sent.append([req.method, path, req.headers.get("x-account-id"), body])
            if fail.get("route")==[req.method, path]:
                return route.fulfill(status=fail["status"], content_type="application/json", body=fail.get("body", '{"detail":"synthetic failure"}'))
            answer={"success":True}
            for m, rx, fn in after:
                if m==req.method and (hit:=re.fullmatch(rx, path)):
                    if isinstance(got:=fn(reads, hit, body), (dict, list)): answer=got
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(answer))
        if req.method=="GET" and path==OFM_WRITES:   # the switch's probe: on, else the Relay's 404 (switch off)
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
    pg.route("**/events?**", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=""))  # no Relay: an empty stream
    pg.on("dialog", lambda d: d.accept())
    errs=[]; pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
    pg.on("pageerror", lambda e: errs.append(f"uncaught: {e}"))
    return pg, sent, errs
def drop_cache(pg):
    """ticket 60: the app's persisted React Query snapshot (IndexedDB `chatterly-rq`, app/lib/rqPersister.ts) deleted
    from a static same-origin page, the app closed, so the next load fetches its reads instead of restoring them fresh."""
    pg.goto(f"{BASE}/of-mirror/pages/home/index.html", wait_until="load", timeout=90000)
    pg.evaluate("() => new Promise(r => { const q = indexedDB.deleteDatabase('chatterly-rq'); q.onsuccess = q.onerror = q.onblocked = () => r(); })")
def with_reads(reads, extra, pg=None):
    """ticket 60: a row's own reads (GET path -> JSON) put over the pass's `reads` (the session's dict); returns the
    function that puts the pass's back, so a row's state never leaks into the next row. With `pg`, the app's persisted
    reads are dropped both times (drop_cache): a restored `/users/me` would hide the row's own."""
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
    """The page's /of-manager URL loaded (sessionStorage cleared, the "Tim" card picked); its frame once bound, or None."""
    if urlparse(pg.url).hostname in LOCAL: pg.evaluate("sessionStorage.clear()")
    pg.goto(f"{BASE}{url_of(page)}", wait_until="load", timeout=90000)
    want=f"/of-mirror/pages/{page.partition('?')[0]}.html"
    for _ in range(80):
        card=pg.get_by_text("Tim", exact=True)
        if card.count(): card.first.click()
        fr=[f for f in pg.frames if urlparse(f.url).path==want]
        try:
            if fr and fr[0].evaluate("document.readyState")=="complete":
                pg.wait_for_timeout(800)  # the binders run on the frame's load; the mocked reads land
                return fr[0]
        except Exception: pass
        pg.wait_for_timeout(250)
    failures.append(f"{page}: NO IFRAME (url {pg.url})"); return None
def locate(fr, label):
    """A step label's element on the frame (FIND, or the "css=" selector's first match), or None."""
    return fr.query_selector(label[4:]) if label.startswith("css=") else fr.evaluate_handle(FIND, label).as_element()
def landmark(scope, pg, page, label):
    fr=open_page(pg, page)
    check(f"{scope}: {page} shows {label!r}", fr is not None and (el:=locate(fr, label)) is not None and el.is_visible(), True)
def act(fr, steps):
    """Each step on the frame: a label clicked, [label, text] typed. None, or the first step that could not run."""
    for step in steps:
        label, text=(step, None) if isinstance(step, str) else step
        # Up to 5s for the control to be drawn, as click/fill wait for a drawn one (e.g. Home's recorder panel, put in
        # only once the click's fetch of New post's markup lands: ofMirrorComposer ensureRecorder).
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
    """Up to 1.5s for the row's writes (1s when it wants none), then the follow-ups' 300ms."""
    for _ in range(15 if want else 10):
        if want and len(sent)>=n+want: break
        pg.wait_for_timeout(100)
    pg.wait_for_timeout(300)
def shot(pg, name, i, page):
    pg.screenshot(path=f"{SHOTS}/inapp-{name}-{i:02d}-{re.sub(r'[/?=&]', '-', page)}.png")
def console(label, errs, statuses):
    # ASSUMPTION: the browser's own "Failed to load resource" line for a status a red-note row planted is that row's
    # doing, not a page error (rung 5); overturned if a reviewer wants those rows to assert the line instead.
    planted=[e for e in errs if not any(f"status of {s}" in e and e.startswith("Failed to load resource") for s in statuses)]
    check(f"{label}: no console errors", [e[:160] for e in planted][:8], [])
def single(b, name, t, records, reads, after, init="", pages=None):
    """records: [(file name, record)], as proof_list reads a captures folder."""
    fail={}
    pg, sent, errs=session(b, f"localStorage.setItem('chatterly:scope','{SINGLE}')", reads, after, fail, init)
    n_shot=0
    for page in dict.fromkeys(p.page for p in t["proofs"]):
        fr=open_page(pg, page)
        if not fr: continue
        for proof in [p for p in t["proofs"] if p.page==page]:
            _, rec, problem=record_of(proof, records)
            check(f"{proof.id}: one capture record", problem, None)
            if NEVER_TITLED in proof.tags:   # ticket 35: each joined label, never titled, pass or not
                for label in proof.control.split(NEVER_TITLED_SEP):
                    found, wired, titled=fr.evaluate(f"(want) => ({STATE})(({FIND})(want))", label)
                    href=fr.evaluate(f"(want) => ({FIND})(want)?.closest('a[href]')?.getAttribute('href') ?? null", label)
                    # A State page opener (dead.py's kind "link") is not Wired itself: its Wired controls are on the
                    # page it opens (post.py, and the proof's own trigger steps), so it counts only when it opens one
                    # of the proof's own ("frame", page) steps. Every other proof keeps the plain Wired check below.
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
            for _ in range(30):   # up to 3s: the opener's navigation lands
                if (u:=urlparse(pg.url)).path+(f"?{u.query}" if u.query else "")==row["opens"]: break
                pg.wait_for_timeout(100)
            check(f"{row['page']} {row['steps']}: opens {row['opens']}", u.path+(f"?{u.query}" if u.query else ""), row["opens"])
        if row.get("after"):
            js, value=row["after"]
            for _ in range(30):   # up to 3s: the binder's read-back request lands
                if (got:=fr.evaluate(js))==value: break
                pg.wait_for_timeout(100)
            check(f"{row['page']} {row['steps']}: read-back {js}", got, value)
        n_shot+=1; shot(pg, name, n_shot, row["page"])
    for row in t["red_notes"]:
        restore=with_reads(reads, row.get("reads", {}), pg)   # ticket 60
        fr=open_page(pg, row["page"])
        if not fr: restore(); continue
        if row.get("fail"): fail.update(route=list(row["fail"]), status=row.get("status", 502))
        if "body" in row: fail["body"]=json.dumps(row["body"])   # ticket 63: e.g. a session-lost answer
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
        # ASSUMPTION: with empty tables the pass still loads one page, so the harness and the console check run on
        # today's pages (rung 5); overturned once the tables hold rows (then their pages are the ones loaded).
        check("single creator: home/index frame loads", open_page(pg, "home/index") is not None, True)
        shot(pg, name, 0, "home/index")
    console("single creator", errs, {r.get("status", 502) for r in t["red_notes"] if r.get("fail")})
    print("single creator relay writes:", sent)
    pg.context.close()
    switch_off(b, name, t, reads, after, init)
def switch_off(b, name, t, reads, after, init=""):
    """Single Creator with OFM_NEW_WRITES_ENABLED off: each `ofm_new_writes` proof's control found, not Wired, its
    Not-yet title kept (main's state); no Relay write."""
    gated=[p for p in t["proofs"] if OFM_NEW_WRITES in p.tags]
    if not gated: return
    pg, sent, errs=session(b, f"localStorage.setItem('chatterly:scope','{SINGLE}')", copy.deepcopy(reads), after, {}, init, switch=False)
    for i, page in enumerate(dict.fromkeys(p.page for p in gated), 1):
        fr=open_page(pg, page)
        if not fr: continue
        for proof in [p for p in gated if p.page==page]:
            check(f"{proof.id} {page} {proof.control!r}, OFM_NEW_WRITES_ENABLED off: found, not Wired, Not-yet title kept",
                  fr.evaluate(f"(want) => ({STATE})(({FIND})(want))", proof.control), [True, False, True])
        shot(pg, f"{name}-switch-off", i, page)
    check("single creator, OFM_NEW_WRITES_ENABLED off: no Relay write", sent, [])
    console("single creator, OFM_NEW_WRITES_ENABLED off", errs, {404})
    pg.context.close()
# one_creator: acc0 listed first with a dead session, so the stand-in is the first with a live one (acc1), not the first.
ONE_ACCOUNTS=[{"id":"acc0","nickname":"Model Zero","has_session":True,"session_dead_at":"2026-01-01T00:00:00Z"}, *ACCOUNTS]
ONE_PAGE="home/index"   # not a stand-in page (STAND_IN_SRC): its Post going out as acc1 is OneCreator's doing
ONE_STEPS=[["css=[contenteditable][aria-label='Textbox field']", "Synthetic post"], "css=button[at-attr='submit_post']"]
ONE_WANT=[["POST", "/api/of/v2/posts", STAND_IN, {"text":"Synthetic post","media_files":[],"price":0}]]
def one_creator(b, name, reads):
    """A saved "all" scope: OF Manager shows one Creator, the first with a live session (acc1), and never saves it."""
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
def run(name, proofs=(), requests=(), red_notes=(), reads=None, after=(), argv=None, init="", pages=None, one_creator_pass=False):
    """The Phase's check: its tables, plus --plant's rows (and one_creator with `one_creator_pass`); exit 1 on a failed check."""
    args=list(sys.argv[1:] if argv is None else argv)
    plant, captures={}, CAPTURES
    if "--plant" in args:
        i=args.index("--plant"); plant=json.load(open(args[i+1])); del args[i:i+2]
    if "--captures" in args:
        i=args.index("--captures"); captures=args[i+1]; del args[i:i+2]
    if args: sys.exit(f"{name}: unknown arguments {args}")
    t={"proofs":[*proofs, *(Proof(**{"phase": 2, **p}) for p in plant.get("proofs", []))], "requests":[*requests, *plant.get("requests", [])],
       "red_notes":[*red_notes, *plant.get("red_notes", [])]}
    if not os.path.isdir(captures): sys.exit(f"{name}: {captures} is not a directory")   # a mistyped path never reads as clean
    records, bad=load_records(Path(captures))
    check("capture records are valid JSON", bad, [])
    planted=plant.get("records", {})   # a planted record replaces the capture file of the same name
    records=[r for r in records if r[0] not in planted]+list(planted.items())
    os.makedirs(SHOTS, exist_ok=True)
    reads={"/api/of/v2/users/me": {"id":1,"username":"alphaone","name":"Alpha One"}, **(reads or {})}
    init="\n".join(x for x in (init, plant.get("init", "")) if x)
    with sync_playwright() as p:
        b=p.chromium.launch()
        single(b, name, t, records, copy.deepcopy(reads), list(after), init, pages)   # each pass starts from the Phase's reads
        if one_creator_pass: one_creator(b, name, copy.deepcopy(reads))
    if failures:
        print("FAIL:", *failures, sep="\n  "); sys.exit(1)
    print(f"{name} ok")
