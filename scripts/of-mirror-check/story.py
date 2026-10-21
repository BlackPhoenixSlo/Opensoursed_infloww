"""The story strip's "Add to story" (app/lib/ofMirrorPost.ts bindStory): a picked image is published as the Creator's Story.

Mocks the login (as writes.py) and the relay's POST /api/of/v2/stories/upload (200 {}); every unmocked /api/** returns []
and any request to a host other than localhost is aborted and fails the check (even one whose path a mock matches). Every
non-GET /api/** request is recorded as [method, path, X-Account-Id, multipart parts as [name, filename, bytes as hex]].
The script builds a 1x1 PNG (stdlib zlib/struct) and hands it to the chooser as an in-memory file, because Chromium leaves
a disk file's bytes out of the request body Playwright reports (post_upload.py); the multipart body is parsed with stdlib
email.parser.BytesParser. Checks in the frame, scope `model:1`, on `home` and on `new-post`:
1. "Add to story" carries data-oi-wired; clicking it fires a file chooser whose input has accept="image/*,video/*" and no
   multiple (OF's stories take a photo or a video).
2. Setting the PNG sends exactly one non-GET /api/** request: POST /api/of/v2/stories/upload with X-Account-Id: 1 and one
   multipart part named `file`, filename the PNG's name, bytes equal to the PNG.
3. The note reads "Added to story" in grey, is visible and sits right after the strip (.stories-list).
4. No console errors but the 500's one failed resource load; no request left localhost.
5. Error: the mock answers the next upload 500 {"detail":"synthetic failure"} once; picking the same PNG again sends a
   second identical upload, the note reads "Could not add: synthetic failure" in red after the strip and is still there
   after the grey note's 3s fade, and the tile is enabled again.
6. Neither image nor video: setting a .txt file on the chooser sends nothing (the recorded requests equal those before the
   pick) and the note reads exactly the red "Could not add: choose an image or a video" right after the strip, never
   "Added to story".
7. All Creators (scope key removed before every load), on `home`: clicking "Add to story" fires no file chooser within
   1s, sends nothing (the recorded requests equal those before the click) and the note reads the grey "Select a model to
   save changes", visible, right after the strip. On `new-post`, which stands in with the first listed creator
   (ofMirrorProfile's STAND_IN_SRC), the chooser opens and the PNG goes up for that creator (acc1). No console errors.
8. My profile, scope `model:1`: "Create highlight" (no Relay write; like Home's and New post's "Start profile
   promotion") is disabled with the tooltip "Not available in Inflowwww yet"; a dispatched click fires no file chooser
   within 1s, sends nothing and shows no note. "Story archive" carries data-oi-wired; a click opens the in-place archive
   box right after the strip (ofMirrorProfile), sends nothing but GETs, shows no note and leaves the page where it is.
   No console errors.
Prints one {"check","want","got"} line per check. Screenshots: /tmp/of-mirror-shots/inapp-story-{home,new-post}.png and
inapp-story-{home,new-post}-error.png, inapp-story-all-models.png (home) and inapp-story-all-models-new-post.png, and
inapp-story-profile.png (profile, the archive box open).
Exit 1 on a failed check.
"""
import json, os, struct, sys, zlib
from email.parser import BytesParser
from email.policy import HTTP
from urllib.parse import urlparse
from playwright.sync_api import TimeoutError as PlaywrightTimeout, sync_playwright
BASE=f"http://localhost:{os.environ.get('PORT','3091')}"
SHOTS="/tmp/of-mirror-shots"
os.makedirs(SHOTS, exist_ok=True)
user={"user_id":"u1","username":"tester","is_admin":False}
STORY_UPLOAD="/api/of/v2/stories/upload"
OWN=".b-story-item.m-story-item-own"
SELECT_MODEL="Select a model to save changes"
NOT_YET="Not available in Inflowwww yet"
CREATE_HIGHLIGHT=".b-story-item:not(.m-story-item-own):has(.b-story-item__text:text-is('Create highlight'))"
ARCHIVE=".b-story-item[data-oi-story-archive]"
def png_1x1():
    def chunk(kind, data): return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00\x00\xaf\xf0")) + chunk(b"IEND", b"")
PIXEL=png_1x1()
PNG={"name":"synthetic.png","mimeType":"image/png","buffer":PIXEL}
TXT={"name":"synthetic.txt","mimeType":"text/plain","buffer":b"synthetic"}
# The shared note: [text, red, the strip right before it]
NOTE="(() => { const e = document.getElementById('oi-note'); return e && [e.textContent, e.style.color === 'rgb(255, 69, 69)', !!e.previousElementSibling?.matches('.stories-list')]; })()"
failures=[]
def check(label, got, want):
    print(json.dumps({"check":label,"want":want,"got":got}))
    if got!=want: failures.append(f"{label}: got {got!r}, expected {want!r}")
def parts(content_type, body):
    """A multipart body's parts as [name, filename, bytes as hex]; [] when the body is not multipart."""
    if not content_type.startswith("multipart/"): return []
    msg=BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body)
    return [[p.get_param("name", header="content-disposition"), p.get_filename(), p.get_payload(decode=True).hex()] for p in msg.iter_parts()]
def session(b, scope_js):
    """A fresh context and page with scope_js run before every load; returns (page, non-GET /api/** requests, console
    errors, fail), where fail["next"] story uploads are answered 500 {"detail":"synthetic failure"} before the 200s."""
    ctx=b.new_context(viewport={"width":1440,"height":900})
    ctx.add_init_script(scope_js)
    foreign=lambda url: urlparse(url).hostname not in ("localhost","127.0.0.1")
    def outside(route):
        failures.append(f"request to a non-localhost host: {route.request.url[:120]}")
        route.abort()
    ctx.route(foreign, outside)
    pg=ctx.new_page()
    sent=[]
    fail={"next":0}
    def mock(route):
        req=route.request; u=req.url; path=urlparse(u).path
        # Page routes win over the context's: a foreign URL matching a mock pattern still fails the check.
        if foreign(u): return outside(route)
        if req.method!="GET" and path.startswith("/api/"):
            sent.append([req.method, path, req.headers.get("x-account-id"), parts(req.headers.get("content-type",""), req.post_data_buffer or b"")])
            if req.method=="POST" and path==STORY_UPLOAD:
                if fail["next"]:
                    fail["next"]-=1
                    return route.fulfill(status=500, content_type="application/json", body=json.dumps({"detail":"synthetic failure"}))
                return route.fulfill(status=200, content_type="application/json", body="{}")
        if "/auth/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps(user))
        elif u.split("?")[0].endswith("/admin/accounts"): route.fulfill(status=200, content_type="application/json", body='{"accounts":[{"id":"acc1","nickname":"Model One","has_session":true},{"id":"1","nickname":"Model Two","has_session":true}],"active_account_id":null}')  # creators: none shows OfNotHaveModel
        elif "/chatter/me/accounts" in u: route.fulfill(status=200, content_type="application/json", body="[]")
        elif "/admin/employees" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"employees":[{"id":1,"display_name":"Tim","color":"#a78bfa","is_active":True,"chatter_id":None}]}))
        elif "/chatter/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"chatter":None,"owners":[]}))
        else: route.fulfill(status=200, content_type="application/json", body="[]")
    for pat in ["**/auth/**","**/chatter/**","**/admin/**","**/accounts**","**/api/**"]: pg.route(pat, mock)
    pg.route("**/events?**", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=""))  # no Relay: an empty stream, not a 500
    errs=[]; pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
    pg.on("pageerror", lambda e: errs.append(f"uncaught: {e}"))
    return pg, sent, errs, fail
def open_page(pg, section):
    """/of-manager/<section> and its Mirror frame (pages/<section>/index.html) once loaded, or None."""
    pg.goto(f"{BASE}/of-manager/{section}", wait_until="load", timeout=90000); pg.wait_for_timeout(2000)
    card=pg.get_by_text("Tim", exact=True)
    if card.count(): card.first.click(); pg.wait_for_timeout(2000)
    for _ in range(60):
        fr=[f for f in pg.frames if f.url.endswith(f"/of-mirror/pages/{section}/index.html")]
        if fr and fr[0].evaluate("document.readyState")=="complete":
            pg.wait_for_timeout(500)
            return fr[0]
        pg.wait_for_timeout(250)
    failures.append(f"{section}: NO IFRAME (url {pg.url})"); return None
def wait_for(pg, fn, want):
    for _ in range(40):
        got=fn()
        if got==want: return got
        pg.wait_for_timeout(250)
    return fn()
with sync_playwright() as p:
    b=p.chromium.launch()
    for section in ["home", "new-post"]:
        pg, sent, errs, fail=session(b, "localStorage.setItem('chatterly:scope','model:1')")
        fr=open_page(pg, section)
        chooser=None
        if fr:
            own=fr.locator(OWN)
            check(f"1 {section}: Add to story carries data-oi-wired", own.get_attribute("data-oi-wired"), "")
            try:
                with pg.expect_file_chooser(timeout=5000) as fc: own.click()
                chooser=fc.value
            except PlaywrightTimeout:
                pass
            check(f"1 {section}: clicking Add to story fires a file chooser", chooser is not None, True)
        if fr and chooser:
            check(f"1 {section}: the chooser's input takes images and videos, one file",
                  chooser.element.evaluate("e => [e.getAttribute('accept'), e.hasAttribute('multiple')]"), ["image/*,video/*", False])
            chooser.set_files(PNG)
            want_note=["Added to story", False, True]
            check(f"3 {section}: the grey note 'Added to story' right after the strip", wait_for(pg, lambda: fr.evaluate(NOTE), want_note), want_note)
            check(f"3 {section}: the note is visible", fr.locator("#oi-note").is_visible(), True)
            pg.screenshot(path=f"{SHOTS}/inapp-story-{section}.png")
            pg.wait_for_timeout(500)
            check(f"2 {section}: exactly one write, the story upload, X-Account-Id 1, one part `file` with the PNG", sent,
                  [["POST", STORY_UPLOAD, "1", [["file", PNG["name"], PIXEL.hex()]]]])
            fail["next"]=1
            retry=None
            try:
                with pg.expect_file_chooser(timeout=5000) as fc: fr.locator(OWN).click()
                retry=fc.value
            except PlaywrightTimeout:
                pass
            check(f"5 {section}: after the upload settled the tile opens the chooser again", retry is not None, True)
            if retry:
                retry.set_files(PNG)
                want_note=["Could not add: synthetic failure", True, True]
                check(f"5 {section}: a 500 shows the red note 'Could not add: synthetic failure' right after the strip",
                      wait_for(pg, lambda: fr.evaluate(NOTE), want_note), want_note)
                check(f"5 {section}: the same PNG picked again sent a second identical upload", sent,
                      [["POST", STORY_UPLOAD, "1", [["file", PNG["name"], PIXEL.hex()]]]]*2)
                check(f"5 {section}: the tile is enabled again", wait_for(pg, lambda: fr.locator(OWN).is_disabled(), False), False)
                pg.screenshot(path=f"{SHOTS}/inapp-story-{section}-error.png")
                pg.wait_for_timeout(3500)
                check(f"5 {section}: the red note stays past the grey note's fade", fr.evaluate(NOTE), want_note)
                before=json.loads(json.dumps(sent))
                txt=None
                try:
                    with pg.expect_file_chooser(timeout=5000) as fc: fr.locator(OWN).click()
                    txt=fc.value
                except PlaywrightTimeout:
                    pass
                check(f"6 {section}: the tile opens the chooser for the non-image pick", txt is not None, True)
                if txt:
                    txt.set_files(TXT)
                    want_note=["Could not add: choose an image or a video", True, True]
                    check(f"6 {section}: a .txt shows the red note 'Could not add: choose an image or a video' right after the strip",
                          wait_for(pg, lambda: fr.evaluate(NOTE), want_note), want_note)
                    pg.wait_for_timeout(1000)
                    check(f"6 {section}: a .txt sends nothing (requests unchanged by the pick)", sent, before)
                    check(f"6 {section}: no 'Added to story' note after the .txt", fr.evaluate(NOTE), want_note)
        # the error case's 500 is logged by the browser as one failed resource load; only that, exactly once
        loads=[e for e in errs if "Failed to load resource" in e and "500" in e]
        print(f"{section} console errors:", [e[:160] for e in errs][:8])
        check(f"4 {section}: one failed 500 load (the error case)", len(loads), 1)
        check(f"4 {section}: no other console errors", [e for e in errs if e not in loads], [])
        pg.context.close()
    for section in ["home", "new-post"]:
        # All Creators: the scope key cleared before every load; Add to story opens no picker and sends nothing.
        pg, sent, errs, fail=session(b, "localStorage.removeItem('chatterly:scope')")
        fr=open_page(pg, section)
        if fr:
            check(f"7 {section}: scope key absent", pg.evaluate("localStorage.getItem('chatterly:scope')"), None)
            before=json.loads(json.dumps(sent))
            chooser=None
            try:
                with pg.expect_file_chooser(timeout=1000) as fc: fr.locator(OWN).click()
                chooser=fc.value
            except PlaywrightTimeout:
                pass
            # A chooser that fires anyway gets the PNG, so an upload it led to is counted below.
            if chooser: chooser.set_files(PNG)
            if section=="new-post":
                check("7 new-post: stands in with the first creator, so Add to story opens the file chooser", chooser is not None, True)
                pg.wait_for_timeout(1500)
                check("7 new-post: the PNG goes up once, for the stand-in creator", [r[:3] for r in sent[len(before):]], [["POST", "/api/of/v2/stories/upload", "acc1"]])
                print(f"{section} all creators console errors:", [e[:160] for e in errs][:8])
                check(f"7 {section}: no console errors in All Creators", errs, [])
                pg.context.close()
                continue
            check(f"7 {section}: clicking Add to story fires no file chooser within 1s", chooser is not None, False)
            want_note=[SELECT_MODEL, False, True]
            check(f"7 {section}: the grey select-a-model note right after the strip", wait_for(pg, lambda: fr.evaluate(NOTE), want_note), want_note)
            check(f"7 {section}: the note is visible", fr.locator("#oi-note").is_visible(), True)
            pg.screenshot(path=f"{SHOTS}/inapp-story-all-models{'' if section=='home' else '-' + section}.png")
            pg.wait_for_timeout(500)
            check(f"7 {section}: sends nothing (requests unchanged by the click)", sent, before)
        print(f"{section} all creators console errors:", [e[:160] for e in errs][:8])
        check(f"7 {section}: no console errors in All Creators", errs, [])
        pg.context.close()
    # My profile: Create highlight disabled quietly; Story archive opens its box in place.
    pg, sent, errs, fail=session(b, "localStorage.setItem('chatterly:scope','model:1')")
    fr=open_page(pg, "profile")
    if fr:
        tile=fr.locator(CREATE_HIGHLIGHT)
        check("8 profile: one Create highlight tile", tile.count(), 1)
        check("8 profile: Create highlight is disabled with the tooltip", [tile.is_disabled(), tile.get_attribute("title")], [True, NOT_YET])
        before=json.loads(json.dumps(sent))
        chooser=None
        try:
            with pg.expect_file_chooser(timeout=1000) as fc: tile.dispatch_event("click")
            chooser=fc.value
        except PlaywrightTimeout:
            pass
        check("8 profile: clicking Create highlight fires no file chooser within 1s", chooser is not None, False)
        check("8 profile: Create highlight shows no note", fr.evaluate(NOTE), None)
        check("8 profile: Create highlight sends nothing", sent, before)
        archive=fr.locator(ARCHIVE)
        check("8 profile: Story archive carries data-oi-wired", archive.get_attribute("data-oi-wired"), "")
        url=fr.url
        archive.click()
        box="(() => { const b = document.querySelector('[data-oi-story-archive-box]'); return !!b && !!b.previousElementSibling?.matches('.stories-list') && b.checkVisibility(); })()"
        check("8 profile: Story archive opens its box right after the strip", wait_for(pg, lambda: fr.evaluate(box), True), True)
        check("8 profile: Story archive shows no note", fr.evaluate(NOTE), None)
        check("8 profile: Story archive stays on the page", fr.url, url)
        pg.screenshot(path=f"{SHOTS}/inapp-story-profile.png")
        pg.wait_for_timeout(500)
        check("8 profile: Story archive sends nothing but GETs", sent, before)
    print("profile console errors:", [e[:160] for e in errs][:8])
    check("8: no console errors on My profile", errs, [])
    pg.context.close()
check("4: no request left localhost", [f for f in failures if f.startswith("request to a non-localhost host")], [])
if failures:
    print("FAIL:", *failures, sep="\n  "); sys.exit(1)
print("story ok")
