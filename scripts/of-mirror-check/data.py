"""Single-model scope: the OF mirror's list pages show the model's real rows (app/lib/ofMirrorData.ts).

Mocks the login (as render.py) and the relay's chats, chat, messages, vault lists, vault media, user lists and list
users with SYNTHETIC rows (and the relay's /img proxy with a small SVG), sets scope `model:1` (as settings_values.py),
and checks in the frame: the chats page shows exactly the 3 chats (no `Fan ` text); clicking "Beta Two" opens
/of-manager/messages/chat?chat=<id> with that header and the 5 messages in order on the right sides, the media
message's picture loaded through /img in OF's media bubble; the price dialog keeps the header (and the query); the
vault shows the 2 folders and its grid the 3 media (pictures loaded through /img, the video with OF's play button
and duration), and a clicked folder (/of-manager/vault?list=<id>) is marked, heads the grid and is asked for with
`list_id=<id>`; the collections page shows the 2 lists and clicking one shows its title, the lists with it marked,
and its 2 users.
Screenshots: /tmp/of-mirror-shots/inapp-data-*.png. Exit 1 on a failed check.
"""
import json, os, re, sys
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
BASE=f"http://localhost:{os.environ.get('PORT','3091')}"
M="/of-manager"
SHOTS="/tmp/of-mirror-shots"
os.makedirs(SHOTS, exist_ok=True)
user={"user_id":"u1","username":"tester","is_admin":False}
AV="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3Crect width='1' height='1' fill='%2300aff0'/%3E%3C/svg%3E"
def fan(i, name, username): return {"id":i,"name":name,"username":username,"avatar":AV}
CHATS=[
    {"withUser":fan(101,"Alpha One","alphaone"),"lastMessage":{"id":11,"text":"synthetic hello","createdAt":"2026-10-10T10:00:00Z"},"unreadMessagesCount":2},
    {"withUser":fan(102,"Beta Two","betatwo"),"lastMessage":{"id":4,"text":"synthetic four","createdAt":"2026-10-09T10:03:00Z"}},
    {"withUser":fan(103,"Gamma Three","gammathree"),"lastMessage":{"id":12,"text":"synthetic bye","createdAt":"2026-10-08T10:00:00Z"}},
]
# Newest first, as the relay sends them; 102 is the fan, 1 the model.
MESSAGES=[{"id":i,"text":t,"fromUser":{"id":f},"createdAt":at,"media":[]} for i,f,t,at in [
    (4,1,"synthetic four","2026-10-09T10:03:00Z"),(3,102,"synthetic three","2026-10-09T10:02:00Z"),
    (2,1,"synthetic two","2026-10-09T10:01:00Z"),(1,102,"synthetic one","2026-10-09T10:00:00Z")]]
# The newest: a fan's photo with a caption (OF's message shape: media[].files.<variant>.url).
MESSAGES.insert(0, {"id":5,"text":"synthetic five","fromUser":{"id":102},"createdAt":"2026-10-09T10:04:00Z",
    "media":[{"id":51,"type":"photo","width":600,"height":600,"files":{"preview":{"url":"https://cdn.example.invalid/m51.jpg"}}}]})
WANT_MESSAGES=[["synthetic one",False],["synthetic two",True],["synthetic three",False],["synthetic four",True],["synthetic five",False]]
VAULT=[{"id":7,"type":"custom","name":"Folder Seven","hasMedia":True,"photosCount":3,"videosCount":1},
       {"id":8,"type":"custom","name":"Folder Eight","hasMedia":False}]
VAULT_MEDIA=[
    {"id":61,"type":"photo","createdAt":"2026-10-10T10:00:00Z","files":{"thumb":{"url":"https://cdn.example.invalid/v61.jpg"}}},
    {"id":62,"type":"video","duration":65,"createdAt":"2026-10-09T10:00:00Z","files":{"thumb":{"url":"https://cdn.example.invalid/v62.jpg"}}},
    {"id":63,"type":"photo","createdAt":"2026-10-08T10:00:00Z","files":{"thumb":{"url":"https://cdn.example.invalid/v63.jpg"}}},
]
LISTS=[{"id":31,"name":"Whales","usersCount":2},{"id":32,"name":"Newcomers","usersCount":2}]
LIST_USERS={"31":[fan(201,"Delta Four","deltafour"),fan(202,"Echo Five","echofive")],
            "32":[fan(203,"Foxtrot Six","foxtrotsix"),fan(204,"Golf Seven","golfseven")]}
SOURCES={
    "/api/of/v2/users/me": {"username":"livemodel","name":"Live Model"},
    "/api/of/v2/chats": {"list":CHATS,"hasMore":False},
    "/api/of/v2/chats/102": CHATS[1],
    "/api/of/v2/chats/102/messages": {"list":MESSAGES,"hasMore":False},
    "/api/of/v2/vault/lists": {"list":VAULT,"hasMore":False},
    "/api/of/v2/vault/media": {"list":VAULT_MEDIA,"hasMore":False},
    "/api/of/v2/lists": {"list":LISTS,"hasMore":False},
    **{f"/api/of/v2/lists/{k}/users": v for k,v in LIST_USERS.items()},
}
PIXEL="<svg xmlns='http://www.w3.org/2000/svg' width='4' height='4'><rect width='4' height='4' fill='#00aff0'/></svg>"
# [src under /img?, loaded with a size] for the shown images matching a selector.
IMAGES="s => [...document.querySelectorAll(s)].filter(e => e.checkVisibility()).map(e => [e.getAttribute('src').startsWith('/img?'), e.complete && e.naturalWidth > 0])"
# Text of the elements matching a selector that are shown in the frame's viewport (hidden examples, and rows pushed out of view, excluded).
SHOWN="s => [...document.querySelectorAll(s)].filter(e => e.checkVisibility() && e.getBoundingClientRect().top < innerHeight).map(e => e.textContent.trim())"
COLUMN_READS={"/api/of/v2/users/me", "/api/of/v2/users/notifications/count"}  # OfManagerChrome's creator column, one read per creator
failures=[]
def check(label, got, want):
    print(json.dumps({"check":label,"got":got,"want":want}))
    if got!=want: failures.append(f"{label}: got {got!r}, expected {want!r}")
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={"width":1440,"height":900})
    ctx.add_init_script("localStorage.setItem('chatterly:scope','model:1')")
    pg=ctx.new_page()
    seen=set(); accounts=set(); media_queries=[]
    def mock(route):
        u=route.request.url; path=urlparse(u).path
        if path=="/img": return route.fulfill(status=200, content_type="image/svg+xml", body=PIXEL)
        if path=="/api/of/v2/vault/media": media_queries.append(urlparse(u).query)
        if path in SOURCES:
            seen.add(path)
            if path not in COLUMN_READS: accounts.add(route.request.headers.get("x-account-id"))  # the creator column reads every creator
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(SOURCES[path]))
        if re.fullmatch(r"/admin/fans/[^/]+/[0-9]+/ppv-history", path):  # the open chat's Fan insights (FanDrawer): its Sales
            return route.fulfill(status=200, content_type="application/json", body='{"items":[],"summary":{"max_cents":0,"avg_cents":0}}')
        if re.fullmatch(r"/api/of/v2/chats/[^/]+/media", path):  # its unsold PPVs
            return route.fulfill(status=200, content_type="application/json", body='{"list":[],"hasMore":false}')
        if m:=re.fullmatch(r"/admin/fans/([^/]+)/([0-9]+)", path):  # its fan record
            return route.fulfill(status=200, content_type="application/json", body=json.dumps({"account_id":m[1],"fan_id":int(m[2]),"tags":[],"lifetime_spend_cents":0,"bought_amount":0,"source":"synthetic"}))
        if "/auth/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps(user))
        elif u.split("?")[0].endswith("/admin/accounts"): route.fulfill(status=200, content_type="application/json", body='{"accounts":[{"id":"acc1","nickname":"Model One","has_session":true},{"id":"1","nickname":"Model Two","has_session":true}],"active_account_id":null}')  # creators: none shows OfNotHaveModel
        elif "/chatter/me/accounts" in u: route.fulfill(status=200, content_type="application/json", body="[]")
        elif "/admin/employees" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"employees":[{"id":1,"display_name":"Tim","color":"#a78bfa","is_active":True,"chatter_id":None}]}))
        elif "/chatter/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"chatter":None,"owners":[]}))
        else: route.fulfill(status=200, content_type="application/json", body="[]")
    for pat in ["**/auth/**","**/chatter/**","**/admin/**","**/accounts**","**/api/**","**/img?**"]: pg.route(pat, mock)
    pg.route("**/events?**", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=""))  # no Relay: an empty stream, not a 500
    errs=[]; pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
    def frame(page):
        for _ in range(60):
            fr=[f for f in pg.frames if f.url.endswith(f"/of-mirror/pages/{page}.html")]
            if fr and fr[0].evaluate("document.readyState")=="complete": return fr[0]
            pg.wait_for_timeout(250)
        failures.append(f"{page}: NO IFRAME (url {pg.url})"); return None
    def settle(fr, sel, n):
        """Wait until `n` rows matching `sel` are visible (the relay data has landed)."""
        for _ in range(40):
            if len(fr.evaluate(SHOWN, sel))==n: return
            pg.wait_for_timeout(250)
    def at(path):
        if not pg.url.endswith(path): failures.append(f"url is {pg.url}, expected …{path}")

    pg.goto(f"{BASE}{M}/messages", wait_until="load", timeout=90000); pg.wait_for_timeout(2000)
    card=pg.get_by_text("Tim", exact=True)
    if card.count(): card.first.click(); pg.wait_for_timeout(2000)
    fr=frame("messages/index")
    if fr:
        settle(fr, ".b-chats__item .g-user-name", 3)
        check("chats: rows", fr.evaluate(SHOWN, ".b-chats__item .g-user-name"), ["Alpha One","Beta Two","Gamma Three"])
        check("chats: handles", fr.evaluate(SHOWN, ".b-chats__item .g-user-username"), ["@alphaone","@betatwo","@gammathree"])
        text=fr.evaluate("document.body.innerText")
        check("chats: no 'Fan ' text", re.findall(r"Fan \d+|@fan\d+", text)[:3], [])
        pg.screenshot(path=f"{SHOTS}/inapp-data-chats.png")
        fr.locator(".b-chats__item__link", has_text="Beta Two").first.click(); pg.wait_for_timeout(1500)
        at(f"{M}/messages/chat?chat=102")
    fr=frame("messages/chat")
    if fr:
        settle(fr, ".b-chat__messages-wrapper .b-chat__message", 5)
        check("chat: header", fr.evaluate(SHOWN, ".b-chat__header__title span.g-user-name"), ["Beta Two"])
        check("chat: messages (text, from me) in order", fr.evaluate("""[...document.querySelectorAll('.b-chat__messages-wrapper .b-chat__message')]
          .filter(e => e.checkVisibility() && e.getBoundingClientRect().top < innerHeight).map(e => [e.querySelector('.b-chat__message__text-holder').textContent.trim(), e.classList.contains('m-from-me')])"""), WANT_MESSAGES)
        check("chat: sides (bubble right of centre = from me)", fr.evaluate("""[...document.querySelectorAll('.b-chat__messages-wrapper .b-chat__message__text')]
          .filter(e => e.checkVisibility()).map(e => { const r = e.getBoundingClientRect(), w = e.closest('.b-chat__messages-wrapper').getBoundingClientRect();
            return r.left + r.width / 2 > w.left + w.width / 2; })"""), [w[1] for w in WANT_MESSAGES])
        check("chat: open row marked", fr.evaluate(SHOWN, ".b-chats__item.current .g-user-name"), ["Beta Two"])
        fr.evaluate("[...document.querySelectorAll('.b-chat__message.m-has-media')].find(e => e.checkVisibility())?.scrollIntoView({block: 'center'})"); pg.wait_for_timeout(800)
        check("chat: the media message's picture, in OF's media bubble, loaded through /img", fr.evaluate(IMAGES, ".b-chat__message.m-has-media .b-chat__message__media img.b-post__media__img"), [[True, True]])
        # (OF's <img> takes no pointer events: the hit is its media box, which must not be a loading cover)
        check("chat: the picture is on top (no loading cover over it)", fr.evaluate("""(() => { const i = [...document.querySelectorAll('.b-chat__message.m-has-media img.b-post__media__img')].find(e => e.checkVisibility());
          const r = i.getBoundingClientRect(); const t = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!t && !t.closest('.post_media__loading') && t.closest('.b-chat__message__media') === i.closest('.b-chat__message__media'); })()"""), True)
        check("chat: no Media placeholder text", fr.evaluate(SHOWN, ".b-chat__message__text-holder").count("Media"), 0)
        pg.screenshot(path=f"{SHOTS}/inapp-data-chat.png")
        price=fr.locator("a[href^='/of-manager/messages/chat/state-price']").first
        check("chat: price link keeps the chat", price.get_attribute("href"), "/of-manager/messages/chat/state-price?chat=102")
        price.click(); pg.wait_for_timeout(1500)
        at(f"{M}/messages/chat/state-price?chat=102")
    fr=frame("messages/chat/state-price")
    if fr:
        settle(fr, ".b-chat__header__title span.g-user-name", 1)
        for _ in range(20):
            if fr.evaluate(SHOWN, ".b-chat__header__title span.g-user-name")==["Beta Two"]: break
            pg.wait_for_timeout(250)
        check("price dialog: header", fr.evaluate(SHOWN, ".b-chat__header__title span.g-user-name"), ["Beta Two"])
        pg.screenshot(path=f"{SHOTS}/inapp-data-chat-price.png")

    pg.goto(f"{BASE}{M}/vault", wait_until="load", timeout=90000)
    fr=frame("vault/index")
    if fr:
        settle(fr, ".b-rows-lists__item__name", 3)
        check("vault: folders", fr.evaluate(SHOWN, ".b-rows-lists__item__name"), ["All media","Folder Seven","Folder Eight"])
        settle(fr, ".b-photos .b-photos__item", 3)
        pg.wait_for_timeout(500)
        check("vault: the grid's tiles", len(fr.evaluate(SHOWN, ".b-photos .b-photos__item")), 3)
        check("vault: tile pictures loaded through /img", fr.evaluate(IMAGES, ".b-photos .b-photos__item__img"), [[True, True]]*3)
        check("vault: the video tile's play button and duration", [fr.evaluate(SHOWN, ".b-photos .b-photos__item__play-btn").__len__(),
              fr.evaluate(SHOWN, ".b-photos .m-video-duration")], [1, ["1:05"]])
        check("vault: ALL MEDIA asks for no folder", "list_id" in (media_queries[0] if media_queries else "list_id"), False)
        pg.screenshot(path=f"{SHOTS}/inapp-data-vault-media.png")
        fr.locator("a.b-rows-lists__item__text", has_text="Folder Eight").first.click(); pg.wait_for_timeout(1500)
        at(f"{M}/vault?list=8")
        fr=frame("vault/index")
        if fr:
            settle(fr, ".b-rows-lists__item__name", 3)
            check("vault: the open folder marked", fr.evaluate(SHOWN, "a.m-current .b-rows-lists__item__name"), ["Folder Eight"])
            check("vault: the folder's media asked for with list_id", any("list_id=8" in q for q in media_queries), True)
            check("vault: the folder heads the grid", fr.evaluate(SHOWN, ".l-main-content.m-r-side .g-page-title > span"), ["Folder Eight"])
        pg.screenshot(path=f"{SHOTS}/inapp-data-vault.png")

    pg.goto(f"{BASE}{M}/collections", wait_until="load", timeout=90000)
    fr=frame("collections/index")
    if fr:
        settle(fr, ".b-user-lists__list .b-rows-lists__item__name", 2)
        check("collections: lists", fr.evaluate(SHOWN, ".b-user-lists__list .b-rows-lists__item__name"), ["Whales","Newcomers"])
        pg.screenshot(path=f"{SHOTS}/inapp-data-lists.png")
        fr.locator(".b-user-lists__list a.b-rows-lists__item__text", has_text="Newcomers").first.click(); pg.wait_for_timeout(1500)
        at(f"{M}/collections/user-lists/list?list=32")
    fr=frame("collections/user-lists/list")
    if fr:
        settle(fr, ".b-users__item .g-user-name", 2)
        check("list: title", fr.evaluate(SHOWN, ".l-main-content .g-page-title > span"), ["Newcomers"])
        check("list: lists, the open one marked", [fr.evaluate(SHOWN, ".b-user-lists__list .b-rows-lists__item__name"),
              fr.evaluate(SHOWN, ".b-user-lists__list a.m-current .b-rows-lists__item__name")], [["Whales","Newcomers"],["Newcomers"]])
        check("list: users", fr.evaluate(SHOWN, ".b-users__item .g-user-name"), ["Foxtrot Six","Golf Seven"])
        check("list: handles", fr.evaluate(SHOWN, ".b-users__item .g-user-username"), ["@foxtrotsix","@golfseven"])
        pg.screenshot(path=f"{SHOTS}/inapp-data-list-users.png")

    missing=set(SOURCES)-seen-{"/api/of/v2/lists/31/users"}
    if missing: failures.append(f"sources never fetched: {sorted(missing)}")
    check("relay calls carry the model's X-Account-Id", sorted(accounts, key=str), ["1"])
    print("console errors:", [e[:160] for e in errs][:8])
    if errs: failures.append(f"{len(errs)} console error(s)")
if failures:
    print("FAIL:", *failures, sep="\n  "); sys.exit(1)
print("data ok")
