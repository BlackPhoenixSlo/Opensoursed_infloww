"""New post's vault dialog (new-post/state-vault, app/lib/ofMirrorData.ts and ofMirrorPost.ts): the Creator's vault media
with proxied thumbnails, picked into the Post draft.

Mocks the login (as post.py) and the relay's GET /api/of/v2/vault/media (3 synthetic items, CDN URLs on
cdn.example.invalid, no _thumb) and /img (a 1x1 PNG built by this script); every unmocked /api/** returns [] and any
request to a host other than localhost is aborted and fails the check (even one whose path a mock matches). Checks
in the frame:
Single Creator (scope `model:1`): with "Synthetic post" typed, "Add media from vault" on New post opens
/of-manager/new-post/state-vault, whose grid shows exactly the 3 media (newest first, each tile stamped data-oi-media
with its vault id and wired, dated as on the Vault page, no example tile left); every tile <img> has an /img? src
carrying account_id=1 and loaded (naturalWidth > 0); the vault requests (the Relay's cached answer, then its one
recheck past the cache, refresh=1) carry X-Account-Id: 1. Picking 61 and 62,
unpicking 61 and picking it again marks exactly those tiles (tile and checkbox `selected`) and leaves the draft
(sessionStorage oi:new-post:1) with the text, media_files [62, 61] and the tiles' own srcs as thumbs, in click order.
Search ("Search media" opens OF's search form; 62 alone has _ai.description "synthetic beach"): " BEACH " leaves only tile 62 shown and
clearing shows all 3, before and after the picks; a search hiding picked tile 61 changes neither its mark nor the draft,
and no further vault request is made.
Close returns to the composer with the text and a row of 2 loaded thumbs (naturalWidth > 0) directly before the actions
bar, whose srcs equal the picked tiles' srcs in click order; reopening the dialog marks exactly 61 and 62 again, and
nothing is sent until Post. After Close again, Post sends exactly one POST /api/of/v2/posts
{"text":"Synthetic post","media_files":[62,61],"price":0} with X-Account-Id: 1 and stays on New post, whose thumbs row
is gone and editor empty.
Folders: the dialog's folder list is the Relay's (unmocked: []), so it shows "All media" alone, never the captured
"List <n>" folders, in both scopes.
All Creators (scope key removed before every load): New post stands in with the first listed creator (ofMirrorProfile's
STAND_IN_SRC), so the dialog shows that creator's media (never the capture's 21 example tiles), read with its id.
Add to story: with 61 and 62 picked it shows "Pick one vault item for the story" and sends nothing; in a fresh session it
sits before Close, wired; picking photo 61 alone and pressing it sends exactly one POST /api/of/v2/stories
{"media_url": 61's full url} with X-Account-Id: 1 and shows "Added to story"; video 62 alone sends {"media_files":[62]};
no post is sent.
No console errors. Screenshots: /tmp/of-mirror-shots/post-vault-*.png. Exit 1 on a failed check.
"""
import json, os, struct, sys, zlib
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright
BASE=f"http://localhost:{os.environ.get('PORT','3091')}"
M="/of-manager"
SHOTS="/tmp/of-mirror-shots"
os.makedirs(SHOTS, exist_ok=True)
user={"user_id":"u1","username":"tester","is_admin":False}
VAULT_MEDIA_PATH="/api/of/v2/vault/media"
POSTS="/api/of/v2/posts"
STORIES="/api/of/v2/stories"
STORY="footer button"
ONE_FOR_STORY="Pick one vault item for the story"
POST="button[at-attr='submit_post']"
VAULT_LINK="a[at-attr='add_vault_media']"
EDITOR="[contenteditable][aria-label='Textbox field']"
CLOSE="footer a"
SEARCH="input[name='media_vault_search']"
OPEN_SEARCH="button[aria-label='Search media']"
DRAFT="JSON.parse(sessionStorage.getItem('oi:new-post:1'))"
# Newest first, as the relay sends them; noon UTC keeps the local day.
VAULT_MEDIA=[
    {"id":61,"type":"photo","createdAt":"2026-10-10T12:00:00Z","files":{"thumb":{"url":"https://cdn.example.invalid/v61.jpg"},
     "full":{"url":"https://cdn.example.invalid/f61.jpg"}}},
    {"id":62,"type":"video","createdAt":"2026-10-09T12:00:00Z","files":{"squarePreview":{"url":"https://cdn.example.invalid/v62.jpg"}},
     "_ai":{"description":"synthetic beach"}},
    {"id":63,"type":"photo","createdAt":"2026-10-08T12:00:00Z","files":{"preview":{"url":"https://cdn.example.invalid/v63.jpg"}}},
]
def png_1x1():
    def chunk(kind, data): return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00\x00\xaf\xf0")) + chunk(b"IEND", b"")
PIXEL=png_1x1()
# Shown grid tiles: [data-oi-media, date label]
FOLDERS="[...document.querySelectorAll('.b-rows-lists__item')].filter(r => r.checkVisibility()).map(r => r.querySelector('.b-rows-lists__item__name')?.textContent.trim())"
TILES="[...document.querySelectorAll('.b-photos .b-photos__item')].filter(t => t.checkVisibility()).map(t => [t.getAttribute('data-oi-media'), t.querySelector('.b-element-label.m-timestamp')?.textContent.trim() ?? null])"
# Shown tile pictures: [src under /img?, its account_id, loaded with a size]
IMAGES="[...document.querySelectorAll('.b-photos .b-photos__item__img')].filter(e => e.checkVisibility()).map(e => { const s = e.getAttribute('src'); return [s.startsWith('/img?'), new URLSearchParams(s.split('?')[1] ?? '').get('account_id'), e.complete && e.naturalWidth > 0]; })"
# Marked tiles: [data-oi-media, its checkbox marked too], in grid order
MARKED="[...document.querySelectorAll('.b-photos .b-photos__item.selected')].map(t => [t.getAttribute('data-oi-media'), !!t.querySelector('.checkbox-item.selected')])"
WIRED="[...document.querySelectorAll('.b-photos .b-photos__item')].filter(t => t.checkVisibility()).map(t => t.hasAttribute('data-oi-wired'))"
# The composer's thumbs row: [directly before the actions bar, [src, loaded with a size] per picture]
COMPOSER_THUMBS="(() => { const r = document.getElementById('oi-post-thumbs'); return r && [!!r.nextElementSibling?.classList.contains('b-make-post__actions'), [...r.querySelectorAll('img.b-photos__item__img')].map(e => [e.getAttribute('src'), e.complete && e.naturalWidth > 0])]; })()"
SRC="id => document.querySelector(`[data-oi-media='${id}'] .b-photos__item__img`).getAttribute('src')"
NOTE="(() => { const n = document.getElementById('oi-note'); return n && n.checkVisibility() ? n.textContent : null; })()"
failures=[]
def check(label, got, want):
    print(json.dumps({"check":label,"got":got,"want":want}))
    if got!=want: failures.append(f"{label}: got {got!r}, expected {want!r}")
def session(b, scope_js):
    """A fresh context and page with scope_js run before every load; returns (page, vault media GETs as
    (query, X-Account-Id), /img proxy queries, sent writes as (method, path, body, X-Account-Id), console errors)."""
    ctx=b.new_context(viewport={"width":1440,"height":900})
    ctx.add_init_script(scope_js)
    foreign=lambda url: urlparse(url).hostname not in ("localhost","127.0.0.1")
    def outside(route):
        failures.append(f"request to a non-localhost host: {route.request.url[:120]}")
        route.abort()
    ctx.route(foreign, outside)
    pg=ctx.new_page()
    vault_gets=[]; imgs=[]; sent=[]
    def mock(route):
        req=route.request; u=req.url; path=urlparse(u).path
        # Page routes win over the context's: a foreign URL matching a mock pattern still fails the check.
        if foreign(u): return outside(route)
        if req.method!="GET" and path.startswith("/api/"):
            sent.append((req.method, path, req.post_data_json if req.post_data else None, req.headers.get("x-account-id")))
            if path==POSTS: return route.fulfill(status=200, content_type="application/json", body=json.dumps({"id":1}))
        if path=="/img":
            imgs.append(parse_qs(urlparse(u).query))
            return route.fulfill(status=200, content_type="image/png", body=PIXEL)
        if req.method=="GET" and path==VAULT_MEDIA_PATH:
            vault_gets.append((urlparse(u).query, req.headers.get("x-account-id")))
            return route.fulfill(status=200, content_type="application/json", body=json.dumps({"list":VAULT_MEDIA,"hasMore":False}))
        if "/auth/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps(user))
        elif u.split("?")[0].endswith("/admin/accounts"): route.fulfill(status=200, content_type="application/json", body='{"accounts":[{"id":"acc1","nickname":"Model One","has_session":true},{"id":"1","nickname":"Model Two","has_session":true}],"active_account_id":null}')  # creators: none shows OfNotHaveModel
        elif "/chatter/me/accounts" in u: route.fulfill(status=200, content_type="application/json", body="[]")
        elif "/admin/employees" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"employees":[{"id":1,"display_name":"Tim","color":"#a78bfa","is_active":True,"chatter_id":None}]}))
        elif "/chatter/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"chatter":None,"owners":[]}))
        else: route.fulfill(status=200, content_type="application/json", body="[]")
    for pat in ["**/auth/**","**/chatter/**","**/admin/**","**/accounts**","**/api/**","**/img?**"]: pg.route(pat, mock)
    pg.route("**/events?**", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=""))  # no Relay: an empty stream, not a 500
    errs=[]; pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
    return pg, vault_gets, imgs, sent, errs
def frame(pg, page):
    for _ in range(60):
        fr=[f for f in pg.frames if f.url.endswith(f"/of-mirror/pages/new-post/{page}.html")]
        if fr and fr[0].evaluate("document.readyState")=="complete":
            pg.wait_for_timeout(500)
            return fr[0]
        pg.wait_for_timeout(250)
    failures.append(f"new-post/{page}: NO IFRAME (url {pg.url})"); return None
def open_vault_dialog(pg, text=None):
    """New post (typing `text`), then its "Add media from vault" link: the loaded new-post/state-vault frame."""
    pg.goto(f"{BASE}{M}/new-post", wait_until="load", timeout=90000); pg.wait_for_timeout(2000)
    card=pg.get_by_text("Tim", exact=True)
    if card.count(): card.first.click(); pg.wait_for_timeout(2000)
    fr=frame(pg, "index")
    if not fr: return None
    if text: fr.locator(EDITOR).fill(text); pg.wait_for_timeout(300)
    return reopen(pg, fr)
def reopen(pg, fr):
    """From the composer frame `fr`, the "Add media from vault" link: the loaded new-post/state-vault frame."""
    fr.locator(VAULT_LINK).click()
    for _ in range(40):
        if urlparse(pg.url).path==f"{M}/new-post/state-vault": break
        pg.wait_for_timeout(250)
    check("the vault link opens the dialog", urlparse(pg.url).path, f"{M}/new-post/state-vault")
    return frame(pg, "state-vault")
def settle(fr, n):
    for _ in range(40):
        if len(fr.evaluate(TILES))==n and all(i[2] for i in fr.evaluate(IMAGES)): return
        fr.page.wait_for_timeout(250)
def console_ok(label, errs):
    print(f"{label} console errors:", [e[:160] for e in errs][:8])
    if errs: failures.append(f"{label}: {len(errs)} console error(s)")
with sync_playwright() as p:
    b=p.chromium.launch()

    # Single Creator: the Creator's vault media.
    pg, vault_gets, imgs, sent, errs=session(b, "localStorage.setItem('chatterly:scope','model:1')")
    fr=open_vault_dialog(pg, "Synthetic post")
    if fr:
        settle(fr, 3)
        check("single creator: the 3 media, newest first, stamped and dated", fr.evaluate(TILES),
              [["61","Oct 10"],["62","Oct 9"],["63","Oct 8"]])
        check("single creator: every tile wired", fr.evaluate(WIRED), [True]*3)
        check("single creator: the folders are All media alone (the Relay's [])", fr.evaluate(FOLDERS), ["All media"])
        check("single creator: every tile picture through /img for account 1, loaded", fr.evaluate(IMAGES), [[True,"1",True]]*3)
        check("single creator: /img asked for the media's CDN pictures", sorted(q["u"][0] for q in imgs),
              ["https://cdn.example.invalid/v61.jpg","https://cdn.example.invalid/v62.jpg","https://cdn.example.invalid/v63.jpg"])
        check("single creator: the Vault page's query, cached then rechecked once, X-Account-Id 1", vault_gets, [("limit=24","1"),("limit=24&refresh=1","1")])
        pg.screenshot(path=f"{SHOTS}/post-vault-tiles.png")
        fr.locator(OPEN_SEARCH).click(); pg.wait_for_timeout(300)
        check("search: Search media opens the search box", fr.locator(SEARCH).is_visible(), True)
        def search(q):
            fr.locator(SEARCH).fill(q); pg.wait_for_timeout(200)
            return [t[0] for t in fr.evaluate(TILES)]
        check("search: \" BEACH \" shows only the synthetic beach tile", search(" BEACH "), ["62"])
        check("search: clearing shows all 3", search(""), ["61","62","63"])
        # Pick 61 and 62, unpick 61, pick it again: the draft follows the clicks.
        for id in (61, 62, 61, 61): fr.locator(f"[data-oi-media='{id}']").click(); pg.wait_for_timeout(200)
        srcs=[fr.evaluate(f"({SRC})({id})") for id in (62, 61)]
        check("picks: exactly tiles 61 and 62 marked, tile and checkbox", fr.evaluate(MARKED), [["61",True],["62",True]])
        check("picks: the draft keeps the text and has the vault ids and the tiles' srcs in click order", pg.evaluate(DRAFT),
              {"text":"Synthetic post","tagged_users":[],"media_files":[62,61],"thumbs":srcs})
        pg.screenshot(path=f"{SHOTS}/post-vault-picked.png")
        check("search after picks: \"beach\" hides picked tile 61", search("beach"), ["62"])
        pg.screenshot(path=f"{SHOTS}/post-vault-search.png")
        check("search after picks: hidden tile 61 keeps its mark", fr.evaluate(MARKED), [["61",True],["62",True]])
        check("search after picks: clearing shows all 3", search(""), ["61","62","63"])
        check("search after picks: both picks still marked", fr.evaluate(MARKED), [["61",True],["62",True]])
        check("search after picks: the draft still has both ids in click order", pg.evaluate(DRAFT)["media_files"], [62,61])
        fr.locator(STORY, has_text="Add to story").click(); pg.wait_for_timeout(300)
        check("story with two picks: the pick-one note", fr.evaluate(NOTE), ONE_FOR_STORY)
        check("search: no further vault request", vault_gets, [("limit=24","1"),("limit=24&refresh=1","1")])
        def close(fr):
            """The dialog's own Close: the loaded composer frame."""
            fr.locator(CLOSE, has_text="Close").click()
            return frame(pg, "index")
        def thumbs_loaded(fr):
            for _ in range(40):
                got=fr.evaluate(COMPOSER_THUMBS)
                if got and all(t[1] for t in got[1]): return got
                pg.wait_for_timeout(250)
            return fr.evaluate(COMPOSER_THUMBS)
        fr=close(fr)
        if fr:
            check("close: back on the composer", urlparse(pg.url).path, f"{M}/new-post")
            check("close: the text is restored", fr.locator(EDITOR).inner_text().strip(), "Synthetic post")
            check("close: one thumbs row before the actions bar, the picked tiles' srcs in click order, loaded",
                  thumbs_loaded(fr), [True, [[srcs[0],True],[srcs[1],True]]])
            pg.screenshot(path=f"{SHOTS}/post-vault-composer.png")
            fr=reopen(pg, fr)
        if fr:
            settle(fr, 3)
            check("reopen: exactly tiles 61 and 62 marked again", fr.evaluate(MARKED), [["61",True],["62",True]])
            check("reopen: the draft is unchanged", pg.evaluate(DRAFT)["media_files"], [62,61])
            pg.screenshot(path=f"{SHOTS}/post-vault-reopened.png")
            check("single creator: nothing sent before Post", sent, [])
            fr=close(fr)
        if fr:
            check("close again: the same thumbs", thumbs_loaded(fr), [True, [[srcs[0],True],[srcs[1],True]]])
            fr.locator(POST).click()
            for _ in range(40):
                if sent: break
                pg.wait_for_timeout(250)
            pg.wait_for_timeout(500)
            check("post: exactly one POST /posts with the text and the picked ids in click order, X-Account-Id 1", sent,
                  [("POST",POSTS,{"text":"Synthetic post","media_files":[62,61],"price":0},"1")])
            check("post: stays on New post", urlparse(pg.url).path, f"{M}/new-post")
            check("post: the draft is cleared", pg.evaluate("sessionStorage.getItem('oi:new-post:1')"), None)
            check("post: New post then shows no thumbs row", fr.evaluate(COMPOSER_THUMBS), None)
            check("post: and an empty editor", fr.locator(EDITOR).inner_text().strip(), "")
    console_ok("single creator", errs)
    pg.context.close()

    # Story from vault: one picked item at a time.
    pg, vault_gets, imgs, sent, errs=session(b, "localStorage.setItem('chatterly:scope','model:1')")
    fr=open_vault_dialog(pg)
    if fr:
        settle(fr, 3)
        story=fr.locator(STORY, has_text="Add to story")
        check("story: Add to story sits before Close, wired", fr.evaluate("(() => { const b = [...document.querySelectorAll('footer button')].find(b => b.textContent.trim() === 'Add to story'); return [!!b?.hasAttribute('data-oi-wired'), b?.nextElementSibling?.textContent.trim() ?? null]; })()"), [True, "Close"])
        def publish(id):
            fr.locator(f"[data-oi-media='{id}']").click(); pg.wait_for_timeout(200)
            story.click()
            for _ in range(40):
                if fr.evaluate(NOTE)=="Added to story": break
                pg.wait_for_timeout(250)
            fr.locator(f"[data-oi-media='{id}']").click(); pg.wait_for_timeout(200)  # unpick
        publish(61)
        check("story: a picked photo goes by its full picture, X-Account-Id 1", sent, [("POST",STORIES,{"media_url":"https://cdn.example.invalid/f61.jpg"},"1")])
        check("story: then says so", fr.evaluate(NOTE), "Added to story")
        pg.screenshot(path=f"{SHOTS}/post-vault-story.png")
        publish(62)
        check("story: a picked video goes by its vault id", sent[1:], [("POST",STORIES,{"media_files":[62]},"1")])
        check("story: no post sent", [s for s in sent if s[1]==POSTS], [])
    console_ok("story", errs)
    pg.context.close()

    # All Creators: the scope key cleared before every load; New post stands in with the first listed creator (acc1).
    pg, vault_gets, imgs, sent, errs=session(b, "localStorage.removeItem('chatterly:scope')")
    fr=open_vault_dialog(pg)
    if fr:
        pg.wait_for_timeout(1500)
        check("all creators: the stand-in creator's media, never the capture's examples", fr.evaluate(TILES), [["61","Oct 10"],["62","Oct 9"],["63","Oct 8"]])
        check("all creators: the folders are All media alone", fr.evaluate(FOLDERS), ["All media"])
        check("all creators: the vault read by the stand-in creator", vault_gets, [("limit=24","acc1"),("limit=24&refresh=1","acc1")])
        check("all creators: nothing sent", sent, [])
        pg.screenshot(path=f"{SHOTS}/post-vault-all-creators.png")
    console_ok("all creators", errs)
    pg.context.close()
if failures:
    print("FAIL:", *failures, sep="\n  "); sys.exit(1)
print("post vault ok")
