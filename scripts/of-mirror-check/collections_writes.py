"""Collections writes (app/lib/ofMirrorCollections.ts) in the frame, relay mocked: the list page's More menu, a user
card's Lists menu and the header's + (OF's "Create new list" / "Create new label" dialog) send their relay writes;
with all models nothing is sent.

Mocks the login (as writes.py) and, with scope `model:acc1`: GET /api/of/v2/lists (two synthetic custom lists with
OF's flags, Whales 31 and Regulars 32), GET /lists/31/users (two synthetic users), GET /users/alphaone (id 901) and
POST /lists/users ({"31": [901]}); every other non-GET /api/** is recorded (method, path, X-Account-Id, body) and
answered {"success": true}. Confirm dialogs are accepted. Checks, on collections/user-lists/list?list=31: More lists
Rename list, Add users, Clear list, Delete list; Rename (the dialog holding "Whales") sends PATCH /lists/31 {name};
Add users with "@alphaone" sends POST /lists/users {"31": [901]}; a card's Lists offers "Remove from Whales" and "Add
to Regulars", which send DELETE /lists/31/users/202 and POST /lists/32/users/202; Clear list sends DELETE
/lists/31/users; Delete list sends DELETE /lists/31 and lands on /of-manager/collections, which shows the first list's
users and whose + opens the "Create new list" dialog, whose Save sends POST /lists {name}; Post Labels' + opens
"Create new label", whose Save sends POST /labels {name}. Every write carries X-Account-Id acc1. All models (scope key
removed): the + shows "Select a model to save changes" and nothing is sent. Screenshots:
/tmp/of-mirror-shots/inapp-collections-more.png, inapp-collections-card.png, inapp-collections-create.png,
inapp-collections-label.png. Exit 1 on a failed check.
"""
import json, os, sys
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
BASE=f"http://localhost:{os.environ.get('PORT','3091')}"
SHOTS="/tmp/of-mirror-shots"
os.makedirs(SHOTS, exist_ok=True)
user={"user_id":"u1","username":"tester","is_admin":False}
FLAGS={"canUpdate":True,"canDelete":True,"canAddUsers":True,"canManageUsers":True}
SOURCES={
    "/api/of/v2/users/me": {"id":1,"username":"alphaone","name":"Alpha One"},
    "/api/of/v2/lists": {"list":[{"id":31,"name":"Whales","usersCount":2,**FLAGS},{"id":32,"name":"Regulars","usersCount":0,**FLAGS}],"hasMore":False},
    "/api/of/v2/lists/31/users": {"list":[{"id":201,"name":"Delta Four","username":"delta"},{"id":202,"name":"Echo Five","username":"echo"}],"hasMore":False},
    "/api/of/v2/users/alphaone": {"id":901,"username":"alphaone","name":"Alpha One"},
}
SELECT_MODEL="Select a model to save changes"
MORE="[at-attr='list_dropdown'] > button"
CREATE="button[aria-label='Create new list']"
NOTE="document.getElementById('oi-note')?.textContent ?? null"
ITEMS="[...document.querySelectorAll('[data-oi-menu] [role=menuitem]')].map(e => e.textContent)"
DIALOG="[data-oi-dialog]"
TITLE="document.querySelector('[data-oi-dialog] .modal-title')?.textContent.trim() ?? null"
failures=[]
def check(label, got, want):
    print(json.dumps({"check":label,"want":want,"got":got}))
    if got!=want: failures.append(f"{label}: got {got!r}, expected {want!r}")
def session(b, scope_js):
    ctx=b.new_context(viewport={"width":1440,"height":900})
    ctx.add_init_script(scope_js)
    pg=ctx.new_page()
    sent=[]
    def mock(route):
        req=route.request; u=req.url; path=urlparse(u).path
        if urlparse(u).hostname not in ("localhost","127.0.0.1"):
            failures.append(f"request to a non-localhost host: {u[:120]}"); return route.abort()
        if req.method!="GET" and path.startswith("/api/"):
            sent.append((req.method, path, req.headers.get("x-account-id"), req.post_data_json if req.post_data else None))
            body={"31":[901]} if path=="/api/of/v2/lists/users" else {"success":True}
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        if req.method=="GET" and path in SOURCES:
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(SOURCES[path]))
        if "/auth/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps(user))
        elif u.split("?")[0].endswith("/admin/accounts"): route.fulfill(status=200, content_type="application/json", body='{"accounts":[{"id":"acc1","nickname":"Model One","has_session":true},{"id":"1","nickname":"Model Two","has_session":true}],"active_account_id":null}')  # creators: none shows OfNotHaveModel
        elif "/chatter/me/accounts" in u: route.fulfill(status=200, content_type="application/json", body="[]")
        elif "/admin/employees" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"employees":[{"id":1,"display_name":"Tim","color":"#a78bfa","is_active":True,"chatter_id":None}]}))
        elif "/chatter/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"chatter":None,"owners":[]}))
        else: route.fulfill(status=200, content_type="application/json", body="[]")
    for pat in ["**/auth/**","**/chatter/**","**/admin/**","**/accounts**","**/api/**"]: pg.route(pat, mock)
    pg.route("**/events?**", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=""))  # no Relay: an empty stream, not a 500
    pg.on("dialog", lambda d: d.accept())
    errs=[]; pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
    first=[True]
    def open_page(page, query=""):
        url=f"{BASE}/of-manager/collections/{page}{query}".replace("/index","")
        pg.goto(url, wait_until="load", timeout=90000); pg.wait_for_timeout(3000)
        if first[0]:
            card=pg.get_by_text("Tim", exact=True)
            if card.count(): card.first.click(); pg.wait_for_timeout(3000)
            first[0]=False
        fr=[f for f in pg.frames if urlparse(f.url).path==f"/of-mirror/pages/collections/{page}.html"]
        if not fr: failures.append(f"{page}: NO IFRAME (url {pg.url})")
        return fr[0] if fr else None
    return pg, sent, errs, open_page
def pick(fr, label):
    fr.locator("[data-oi-menu] [role=menuitem]", has_text=label).first.click()
def type_in(fr, text):
    fr.locator(f"{DIALOG} input").fill(text)
    fr.locator(f"{DIALOG} button[type=submit]").click()
def wait_for(pg, sent, n):
    for _ in range(40):
        if len(sent)>=n: return
        pg.wait_for_timeout(100)
with sync_playwright() as p:
    b=p.chromium.launch()
    pg, sent, errs, open_page=session(b, "localStorage.setItem('chatterly:scope','model:acc1')")
    fr=open_page("user-lists/list", "?list=31")
    if fr:
        pg.wait_for_timeout(1000)
        check("list page: the real list's title", fr.evaluate("document.querySelector('.l-main-content .g-page-title > span').textContent.trim()"), "Whales")
        fr.locator(MORE).click()
        check("More: OF's items by the list's flags", fr.evaluate(ITEMS), ["Rename list","Add users","Clear list","Delete list"])
        check("More: no Read-only note", fr.evaluate(NOTE), None)
        pg.screenshot(path=f"{SHOTS}/inapp-collections-more.png")
        pick(fr, "Rename list")
        check("Rename: OF's dialog", fr.evaluate(TITLE), "Rename list")
        check("Rename: the field holds the name", fr.locator(f"{DIALOG} input").input_value(), "Whales")
        type_in(fr, "Big whales"); wait_for(pg, sent, 1); pg.wait_for_timeout(300)
        check("Rename: PATCH /lists/31 {name}", sent[-1:], [("PATCH","/api/of/v2/lists/31","acc1",{"name":"Big whales"})])
        check("Rename: note", fr.evaluate(NOTE), "Saved")
        check("Rename: the dialog closed", fr.locator(DIALOG).count(), 0)

        n=len(sent)
        fr.locator(MORE).click(); pick(fr, "Add users")
        type_in(fr, "@alphaone"); wait_for(pg, sent, n+1); pg.wait_for_timeout(300)
        check("Add users: one bulk POST /lists/users", sent[n:], [("POST","/api/of/v2/lists/users","acc1",{"31":[901]})])
        check("Add users: note", fr.evaluate(NOTE), "Added 1 user")

        n=len(sent)
        card="[data-oi-user='202'] button[at-attr='add_to_list'].b-dot-item"
        fr.evaluate("document.getElementById('oi-note')?.remove()")
        fr.locator(card).click()
        check("card Lists: Remove from this list, Add to the other", fr.evaluate(ITEMS), ["Remove from Whales","Add to Regulars"])
        check("card Lists: no Read-only note", fr.evaluate(NOTE), None)
        pg.screenshot(path=f"{SHOTS}/inapp-collections-card.png")
        pick(fr, "Add to Regulars"); wait_for(pg, sent, n+1)
        fr.locator(card).click(); pick(fr, "Remove from Whales"); wait_for(pg, sent, n+2)
        check("card Lists: POST /lists/32/users/202, DELETE /lists/31/users/202", sent[n:],
              [("POST","/api/of/v2/lists/32/users/202","acc1",None),("DELETE","/api/of/v2/lists/31/users/202","acc1",None)])

        n=len(sent)
        fr.locator(MORE).click(); pick(fr, "Clear list"); wait_for(pg, sent, n+1)
        check("Clear list (confirmed): DELETE /lists/31/users", sent[n:], [("DELETE","/api/of/v2/lists/31/users","acc1",None)])
        n=len(sent)
        fr.locator(MORE).click(); pick(fr, "Delete list"); wait_for(pg, sent, n+1)
        for _ in range(40):
            if urlparse(pg.url).path=="/of-manager/collections": break
            pg.wait_for_timeout(100)
        check("Delete list (confirmed): DELETE /lists/31", sent[n:], [("DELETE","/api/of/v2/lists/31","acc1",None)])
        check("Delete list: lands on Collections", urlparse(pg.url).path, "/of-manager/collections")
    fr=open_page("index")
    if fr:
        pg.wait_for_timeout(1000)
        check("index: the first list's users", fr.evaluate("[...document.querySelectorAll('[data-oi-user] .g-user-name')].map(e => e.textContent)"), ["Delta Four","Echo Five"])
        n=len(sent)
        fr.locator(CREATE).click()
        check("Create new list: OF's dialog", fr.evaluate(TITLE), "Create new list")
        check("Create new list: Save off while empty", fr.locator(f"{DIALOG} button[type=submit]").is_disabled(), True)
        pg.screenshot(path=f"{SHOTS}/inapp-collections-create.png")
        type_in(fr, "Synthetic list"); wait_for(pg, sent, n+1); pg.wait_for_timeout(300)
        check("Create new list: POST /lists {name}", sent[n:], [("POST","/api/of/v2/lists","acc1",{"name":"Synthetic list"})])
        check("Create new list: note", fr.evaluate(NOTE), "List created")
    fr=open_page("post-labels/archived")
    if fr:
        n=len(sent)
        fr.locator(CREATE).click()
        check("Post Labels +: OF's dialog", fr.evaluate(TITLE), "Create new label")
        pg.screenshot(path=f"{SHOTS}/inapp-collections-label.png")
        type_in(fr, "Synthetic label"); wait_for(pg, sent, n+1); pg.wait_for_timeout(300)
        check("Create new label: POST /labels {name}", sent[n:], [("POST","/api/of/v2/labels","acc1",{"name":"Synthetic label"})])
        check("Create new label: note", fr.evaluate(NOTE), "Label created")
    print("relay writes:", sent)
    print("console errors:", [e[:160] for e in errs][:8])
    if errs: failures.append(f"{len(errs)} console error(s)")

    pg, sent, errs, open_page=session(b, "localStorage.removeItem('chatterly:scope')")
    fr=open_page("index")
    if fr:
        fr.locator(CREATE).click(); pg.wait_for_timeout(500)
        check("all models: the + notes Select a model", fr.evaluate(NOTE), SELECT_MODEL)
        check("all models: no dialog opens", fr.locator(DIALOG).count(), 0)
        check("all models: no write", sent, [])
    if errs: failures.append(f"all models: {len(errs)} console error(s)")
if failures:
    print("FAIL:", *failures, sep="\n  "); sys.exit(1)
print("collections ok")
