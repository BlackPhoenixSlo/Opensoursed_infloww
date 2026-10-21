"""The Messages tab's writes (app/lib/ofMirrorChat.ts): a chat's Send and New message's Send.

Mocks the login (as post_vault.py) and the relay: GET /api/of/v2/chats (one synthetic chat, fan 9001, its partner bare as
OF sends it) and /users/list (that partner), its detail and messages, GET /api/of/v2/lists (the built-in "fans" and list
42); every write is recorded and answered {"id":1}; every other /api/** returns [] and a request to a host other than
localhost fails the check. window.confirm is accepted.
Single Creator (scope `model:1`):
- /of-manager/messages/chat?chat=9001: typing "Synthetic hello" enables Send; Send makes exactly one POST
  /api/of/v2/chats/9001/messages {"text":"Synthetic hello","price":0,"media_files":[]} with X-Account-Id: 1, shows
  "Sent" and empties the editor. Beside it, Messages Pro's Fan insights column (aside "Fan insights"): 280px, flush
  with the right edge, #0d0d0d (rgb(13, 13, 13)), over the frame's right 280px as Infloww's column sits inside OF's page:
  the frame keeps the view's width, so OF keeps its chat list beside the chat, and the chat ends where the column starts;
  the header's "Fan insights" toggle (aria-pressed) hides it, the chat then running on past it, and shows it again.
- /of-manager/messages/send: the Send to rows are the 2 lists; ticking both and typing "Synthetic blast" then Send asks
  first and makes exactly one POST /api/of/v2/messages/queue {"text":"Synthetic blast","user_lists":["fans","42"]}.
All Creators (scope key removed) with no creator: Infloww's OfNotHaveModel instead of the frame, nothing sent.
All Creators with models 1 and 2 (/admin/accounts): /of-manager/messages shows model 1's chat (its partner's name from
/users/list) under the line "Showing Model One, pick a model to switch", every relay read carrying X-Account-Id: 1.
No console errors. Screenshots: /tmp/of-mirror-shots/messages-*.png. Exit 1 on a failed check.
"""
import json, os, sys
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
BASE=f"http://localhost:{os.environ.get('PORT','3091')}"
M="/of-manager"
SHOTS="/tmp/of-mirror-shots"
os.makedirs(SHOTS, exist_ok=True)
user={"user_id":"u1","username":"tester","is_admin":False}
EDITOR="[contenteditable][aria-label='Textbox field']"
SEND="button[at-attr='send_btn']"
ROWS=".b-chats__scroller label.b-rows-lists__item[data-oi-list]"
FAN={"id":9001,"name":"Synthetic Fan","username":"synthfan"}
CHATS={"list":[{"withUser":{"id":9001,"_view":"m"},"lastMessage":{"id":1,"text":"hi","createdAt":"2026-10-10T12:00:00Z","fromUser":FAN}}],"hasMore":False}
DETAIL={"withUser":FAN,"isMutedNotifications":False}
MESSAGES={"list":[{"id":1,"text":"<p>hi</p>","createdAt":"2026-10-10T12:00:00Z","fromUser":FAN,"media":[]}],"hasMore":False}
FAN_RECORD={"account_id":"1","fan_id":9001,"of_username":"synthfan","of_display_name":"Synthetic Fan","avatar_url":None,"custom_nickname":None,"generated_nickname":None,"real_name":None,"his_age":None,"home_country":None,"home_city":None,"hobbies":None,"fetishes":None,"self_description":None,"description":None,"notes":None,"tags":[],"lifetime_spend_cents":0,"bought_amount":0,"subscription_status":None,"subscribed_at":None,"last_message_received_at":None,"source":"synthetic","is_followed":False,"language":None,"language_source":None}
LISTS={"list":[{"id":"fans","name":"Fans","usersCount":12},{"id":42,"name":"Synthetic list","usersCount":3}],"hasMore":False}
NOTE="(() => { const n = document.getElementById('oi-note'); return n && n.checkVisibility() ? n.textContent : null; })()"
failures=[]
def check(label, got, want):
    print(json.dumps({"check":label,"got":got,"want":want}))
    if got!=want: failures.append(f"{label}: got {got!r}, expected {want!r}")
ACCOUNTS={"accounts":[{"id":"1","nickname":"Model One","has_session":True},{"id":"2","nickname":"Model Two","has_session":True}],"active_account_id":None}
def session(b, scope_js, models=True, reads=None):
    """A fresh page with scope_js run before every load; returns (page, sent writes as (method, path, body, X-Account-Id), console errors).
    models: /admin/accounts lists models 1 and 2 (else none). reads: a list that gets each /api/of GET as (path, X-Account-Id)."""
    ctx=b.new_context(viewport={"width":1440,"height":900})
    ctx.add_init_script(scope_js)
    foreign=lambda url: urlparse(url).hostname not in ("localhost","127.0.0.1")
    def outside(route):
        failures.append(f"request to a non-localhost host: {route.request.url[:120]}")
        route.abort()
    ctx.route(foreign, outside)
    pg=ctx.new_page()
    pg.on("dialog", lambda d: d.accept())
    sent=[]
    def ok(route, body): route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
    def mock(route):
        req=route.request; u=req.url; path=urlparse(u).path
        if foreign(u): return outside(route)
        if req.method!="GET" and path.startswith("/api/"):
            sent.append((req.method, path, req.post_data_json if req.post_data else None, req.headers.get("x-account-id")))
            return ok(route, {"id":1})
        if reads is not None and path.startswith("/api/of/"): reads.append((path, req.headers.get("x-account-id")))
        if path=="/api/of/v2/chats": return ok(route, CHATS)
        if path=="/api/of/v2/users/list": return ok(route, {"9001":FAN})
        if path=="/admin/accounts" and models: return ok(route, ACCOUNTS)
        if path=="/api/of/v2/chats/9001": return ok(route, DETAIL)
        if path=="/api/of/v2/chats/9001/messages": return ok(route, MESSAGES)
        if path=="/api/of/v2/lists": return ok(route, LISTS)
        if path=="/admin/fans/1/9001": return ok(route, FAN_RECORD)  # Fan insights (useFan)
        if path=="/admin/fans/1/9001/ppv-history": return ok(route, {"items":[],"summary":{"max_cents":0,"avg_cents":0}})  # its Sales
        if path=="/api/of/v2/chats/9001/media": return ok(route, {"list":[],"hasMore":False})  # its unsold PPVs
        if "/auth/me" in u: ok(route, user)
        elif "/chatter/me/accounts" in u: ok(route, [])
        elif "/admin/employees" in u: ok(route, {"employees":[{"id":1,"display_name":"Tim","color":"#a78bfa","is_active":True,"chatter_id":None}]})
        elif "/chatter/me" in u: ok(route, {"chatter":None,"owners":[]})
        else: ok(route, [])
    for pat in ["**/auth/**","**/chatter/**","**/admin/**","**/accounts**","**/api/**","**/img?**"]: pg.route(pat, mock)
    pg.route("**/events?**", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=""))  # no Relay: an empty stream, not a 500
    errs=[]; pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
    return pg, sent, errs
def frame(pg, page):
    for _ in range(60):
        fr=[f for f in pg.frames if f.url.endswith(f"/of-mirror/pages/messages/{page}.html")]
        if fr and fr[0].evaluate("document.readyState")=="complete":
            pg.wait_for_timeout(1500)
            return fr[0]
        pg.wait_for_timeout(250)
    failures.append(f"messages/{page}: NO IFRAME (url {pg.url})"); return None
def go(pg, url, page):
    pg.goto(f"{BASE}{url}", wait_until="load", timeout=90000); pg.wait_for_timeout(2000)
    card=pg.get_by_text("Tim", exact=True)
    if card.count(): card.first.click(); pg.wait_for_timeout(2000)
    return frame(pg, page)
def wait_for(fn, n=40):
    for _ in range(n):
        if fn(): return
        pg.wait_for_timeout(250)
with sync_playwright() as p:
    b=p.chromium.launch()

    pg, sent, errs=session(b, "localStorage.setItem('chatterly:scope','model:1')")
    fr=go(pg, f"{M}/messages/chat?chat=9001", "chat")
    if fr:
        aside=pg.get_by_role("complementary", name="Fan insights")
        box=lambda el: [round(v) for v in (lambda r: [r["x"], r["width"]])(el.bounding_box())]
        iframe=pg.locator("iframe[src*='/of-mirror/pages/messages/chat.html']")
        check("insights: the 280px column at the right edge", box(aside), [1160, 280])
        check("insights: #0d0d0d", aside.evaluate("e => getComputedStyle(e).backgroundColor"), "rgb(13, 13, 13)")
        LAYOUT="""[...['.b-chats__conversations-list', '.b-chats__conversations-content']].map(s => document.querySelector(s))
          .map(e => [e.checkVisibility(), Math.round(e.getBoundingClientRect().right)])"""
        edge=lambda: [[v, r+box(iframe)[0]] for v, r in fr.evaluate(LAYOUT)]
        check("insights: the frame keeps the view's width", sum(box(iframe)), 1440)
        check("insights: OF's chat list beside the chat, the chat ending where the column starts", [e[0] for e in edge()]+[edge()[1][1]], [True, True, 1160])
        pg.screenshot(path=f"{SHOTS}/messages-chat-insights.png")
        toggle=pg.get_by_role("button", name="Fan insights")
        check("insights: the toggle is pressed", toggle.get_attribute("aria-pressed"), "true")
        toggle.click(); pg.wait_for_timeout(300)
        check("insights: hidden by the toggle, the OF chat running past where it was", [aside.count(), edge()[1][1] > 1160], [0, True])
        toggle.click(); pg.wait_for_timeout(300)
        check("insights: shown again", [aside.count(), edge()[1][1]], [1, 1160])
        check("chat: Send disabled before typing", fr.locator(SEND).is_disabled(), True)
        fr.locator(EDITOR).fill("Synthetic hello"); pg.wait_for_timeout(300)
        check("chat: typing enables Send", fr.locator(SEND).is_disabled(), False)
        fr.locator(SEND).click()
        wait_for(lambda: fr.evaluate(NOTE)=="Sent")
        check("chat: one POST to the chat with the Known body", sent,
              [("POST","/api/of/v2/chats/9001/messages",{"text":"Synthetic hello","price":0,"media_files":[]},"1")])
        check("chat: the Sent note", fr.evaluate(NOTE), "Sent")
        check("chat: the editor is empty", fr.locator(EDITOR).inner_text().strip(), "")
        pg.screenshot(path=f"{SHOTS}/messages-chat-sent.png")
    sent.clear()
    fr=go(pg, f"{M}/messages/send", "send")
    if fr:
        wait_for(lambda: fr.locator(ROWS).count()==2)
        check("new message: the Creator's lists", [t.strip() for t in fr.locator(f"{ROWS} .b-rows-lists__item__name").all_inner_texts()], ["Fans","Synthetic list"])
        for i in range(2): fr.locator(ROWS).nth(i).click(); pg.wait_for_timeout(200)
        fr.locator(EDITOR).fill("Synthetic blast"); pg.wait_for_timeout(300)
        fr.locator(SEND).click()
        wait_for(lambda: fr.evaluate(NOTE)=="Sent")
        check("new message: one POST /messages/queue to both lists", sent,
              [("POST","/api/of/v2/messages/queue",{"text":"Synthetic blast","user_lists":["fans","42"]},"1")])
        pg.screenshot(path=f"{SHOTS}/messages-send-sent.png")
    print("single creator console errors:", [e[:160] for e in errs][:8])
    if errs: failures.append(f"single creator: {len(errs)} console error(s)")

    pg, sent, errs=session(b, "localStorage.removeItem('chatterly:scope')", models=False)
    pg.goto(f"{BASE}{M}/messages/chat?chat=9001", wait_until="load", timeout=90000); pg.wait_for_timeout(3000)
    check("all creators, no creator: OfNotHaveModel, no frame", [pg.get_by_text("You have not yet tied a creator").count() > 0, [f.url for f in pg.frames if "of-mirror" in f.url]], [True, []])
    check("all creators: nothing sent", sent, [])
    print("all creators console errors:", [e[:160] for e in errs][:8])
    if errs: failures.append(f"all creators: {len(errs)} console error(s)")

    reads=[]
    pg, sent, errs=session(b, "localStorage.removeItem('chatterly:scope')", models=True, reads=reads)
    fr=go(pg, f"{M}/messages", "index")
    if fr:
        wait_for(lambda: fr.evaluate("[...document.querySelectorAll('.b-chats__item .g-user-name')].filter(e => e.checkVisibility()).length")==1)
        check("all creators with models: model 1's chat, its partner named from /users/list",
              fr.evaluate("[...document.querySelectorAll('.b-chats__item')].filter(e => e.checkVisibility()).map(e => [e.querySelector('.g-user-name').textContent.trim(), e.querySelector('.g-user-username').textContent.trim()])"),
              [["Synthetic Fan","@synthfan"]])
        check("all creators with models: the line over the frame names the model", pg.get_by_test_id("of-standin-hint").inner_text(), "Showing Model One, pick a model to switch")
        # The creator column reads each listed creator's /users/me and notification count.
        check("all creators with models: every relay read but the creator column's carries X-Account-Id: 1", sorted({a for r, a in reads if r not in ("/api/of/v2/users/me", "/api/of/v2/users/notifications/count")}, key=str), ["1"])
        check("all creators with models: nothing sent", sent, [])
        pg.screenshot(path=f"{SHOTS}/messages-all-standin.png")
    print("all creators with models console errors:", [e[:160] for e in errs][:8])
    if errs: failures.append(f"all creators with models: {len(errs)} console error(s)")
    b.close()
if failures:
    print("FAILED:"); [print(" -", f) for f in failures]; sys.exit(1)
print("ALL OK")
