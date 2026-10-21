"""New post's "Add media" (app/lib/ofMirrorPost.ts): a file from disk uploads through the Relay and the next Post sends it.

Mocks the login (as post_vault.py) and the relay's POST /api/of/v2/upload and POST /api/of/v2/posts; every unmocked
/api/** returns [] and any request to a host other than localhost is aborted and fails the check (even one whose path a
mock matches). The script builds a 1x1 PNG (stdlib zlib/struct) and hands it to the chooser as an in-memory file, because
Chromium leaves a disk file's bytes out of the request body Playwright reports; the multipart upload body is parsed with
stdlib email.parser.BytesParser. Checks in the frame, scope `model:1`:
1. Clicking "Add media" fires a file chooser whose input has accept="image/*,video/*,audio/*" and multiple (OF's
   composer takes several photos, videos and audio at once); the button
   carries data-oi-wired.
2. Every upload is held (its route kept and fulfilled later). With "Synthetic post" typed, Post is disabled while the
   upload is held; after it is fulfilled with the accepted claim p1, Post is enabled and the strip shows one blob: thumb.
   A second session holds two picks at once: Post stays disabled after the first is refused
   ({"ready":false,"send_with":null,"note":"Synthetic refusal"}) while the second is in flight, and is enabled again
   after the second fails (HTTP 502). A third session holds one upload across a State page round trip (Schedule, then
   Cancel): back on new-post Post is still disabled, and is enabled once the upload is fulfilled.
3. The mock receives exactly one POST /api/of/v2/upload with X-Account-Id: 1 and one multipart part named `file`,
   filename the PNG's name, bytes equal to the PNG.
4. After the accepted claim p1 the attached-media strip shows one thumb whose src starts with blob: (loaded), and Post
   sends exactly one POST /api/of/v2/posts with X-Account-Id: 1 and
   {"text":"Synthetic post","media_files":[{"processId":"p1","host":"h","name":"n"}],"price":0}.
5. With "Synthetic post" typed and the accepted claim p2 attached, a second pick refused with
   {"ready":false,"send_with":null,"note":"Synthetic refusal"} shows a red #oi-note containing `Synthetic refusal`; the
   strip still has exactly one thumb, the editor still holds "Synthetic post", the oi:new-post:1 draft's media_files is
   still [p2], and no POST /api/of/v2/posts is sent within 1s. A refusal with no note reads `Could not upload: upload
   not ready`.
6. An upload answered HTTP 502 shows a red #oi-note starting `Could not upload:` and adds no thumb; picking the same
   PNG again sends a second POST /api/of/v2/upload with the same bytes. No console error but the 502's own resource line
   (a rejection left unhandled is a page error, collected with the console errors).
7. All Creators (scope key removed before every load): New post stands in with the first listed creator (ofMirrorProfile's
   STAND_IN_SRC), so clicking "Add media" opens the file chooser and the PNG goes up once with X-Account-Id acc1; no post.
8. No console errors; no request left localhost.
9. Dedupe hit: with vault id 42 seeded in the oi:new-post:1 draft before load, an upload answered
   {"ready":true,"deduped":true,"vault_id":42,"send_with":[42]} is appended as returned: Post sends media_files [42, 42].
10. After an accepted upload (claim p1), Schedule then Cancel and back on new-post: the strip shows one blob: thumb,
    loaded, and Post sends the claim in media_files.
11. After an accepted upload (claim p1) and a full reload (its blob: URL dead), the strip holds one 64px square in OF's
    grey (#8a96a3) with no visible <img> whose naturalWidth is 0, and the draft's media_files is still [p1].
Prints one {"check","want","got"} line per check. Screenshots: /tmp/of-mirror-shots/inapp-post-upload*.png. Exit 1 on a
failed check.
"""
import base64, json, os, struct, sys, zlib
from email.parser import BytesParser
from email.policy import HTTP
from urllib.parse import urlparse
from playwright.sync_api import TimeoutError as PlaywrightTimeout, sync_playwright
BASE=f"http://localhost:{os.environ.get('PORT','3091')}"
M="/of-manager"
SHOTS="/tmp/of-mirror-shots"
os.makedirs(SHOTS, exist_ok=True)
user={"user_id":"u1","username":"tester","is_admin":False}
UPLOAD="/api/of/v2/upload"
POSTS="/api/of/v2/posts"
POST="button[at-attr='submit_post']"
ADD_MEDIA="button[aria-label='Add media']"
EDITOR="[contenteditable][aria-label='Textbox field']"
SCHEDULE="a[at-attr='scheduled_msg']"
CANCEL=".vdatetime-popup__actions__button--cancel a"
CLAIM={"processId":"p1","host":"h","name":"n"}
CLAIM2={"processId":"p2","host":"h","name":"n"}
ACCEPTED={"ready":True,"deduped":False,"vault_id":None,"send_with":[CLAIM]}
REFUSED={"ready":False,"send_with":None,"note":"Synthetic refusal"}
def png_1x1():
    def chunk(kind, data): return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00\x00\xaf\xf0")) + chunk(b"IEND", b"")
PIXEL=png_1x1()
PNG={"name":"synthetic.png","mimeType":"image/png","buffer":PIXEL}
# The composer's thumbs: [src starts with blob:, loaded with a size] per picture
DRAFT_MEDIA="JSON.parse(sessionStorage.getItem('oi:new-post:1')).media_files"
# The shared note: [text, red]
NOTE="(() => { const e = document.getElementById('oi-note'); return e && [e.textContent, e.style.color === 'rgb(255, 69, 69)']; })()"
# The strip's squares after their pictures settled: [width, height, background, visible <img>s with naturalWidth 0]
SQUARES="[...document.querySelectorAll('#oi-post-thumbs > .b-photos__item')].map(e => { const r = e.getBoundingClientRect(); return [r.width, r.height, getComputedStyle(e).backgroundColor, [...e.querySelectorAll('img')].filter(i => i.offsetParent !== null && i.complete && i.naturalWidth === 0).length]; })"
THUMBS="[...document.querySelectorAll('#oi-post-thumbs img.b-photos__item__img')].map(e => [e.getAttribute('src').startsWith('blob:'), e.complete && e.naturalWidth > 0])"
failures=[]
def check(label, got, want):
    print(json.dumps({"check":label,"want":want,"got":got}))
    if got!=want: failures.append(f"{label}: got {got!r}, expected {want!r}")
def parts(content_type, body):
    """The multipart body's parts as [name, filename, bytes as hex]."""
    msg=BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body)
    return [[p.get_param("name", header="content-disposition"), p.get_filename(), p.get_payload(decode=True).hex()] for p in msg.iter_parts()]
def session(b, scope_js):
    """A fresh context and page with scope_js run before every load; returns (page, uploads as (X-Account-Id, parts),
    held upload routes (fulfilled by the caller), posts as (body, X-Account-Id), console errors)."""
    ctx=b.new_context(viewport={"width":1440,"height":900})
    ctx.add_init_script(scope_js)
    foreign=lambda url: urlparse(url).hostname not in ("localhost","127.0.0.1")
    def outside(route):
        failures.append(f"request to a non-localhost host: {route.request.url[:120]}")
        route.abort()
    ctx.route(foreign, outside)
    pg=ctx.new_page()
    uploads=[]; held=[]; posts=[]
    def mock(route):
        req=route.request; u=req.url; path=urlparse(u).path
        # Page routes win over the context's: a foreign URL matching a mock pattern still fails the check.
        if foreign(u): return outside(route)
        if req.method=="POST" and path==UPLOAD:
            uploads.append((req.headers.get("x-account-id"), parts(req.headers.get("content-type",""), req.post_data_buffer or b"")))
            return held.append(route)
        if req.method=="POST" and path==POSTS:
            posts.append((req.post_data_json, req.headers.get("x-account-id")))
            return route.fulfill(status=200, content_type="application/json", body=json.dumps({"id":1}))
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
    return pg, uploads, held, posts, errs
def answer(route, reply):
    """Fulfil a held upload: a dict as JSON 200, an int as that HTTP status."""
    if isinstance(reply, int): route.fulfill(status=reply, content_type="application/json", body=json.dumps({"detail":"Synthetic relay error"}))
    else: route.fulfill(status=200, content_type="application/json", body=json.dumps(reply))
def frame(pg, page="index"):
    for _ in range(60):
        fr=[f for f in pg.frames if f.url.endswith(f"/of-mirror/pages/new-post/{page}.html")]
        if fr and fr[0].evaluate("document.readyState")=="complete":
            pg.wait_for_timeout(500)
            return fr[0]
        pg.wait_for_timeout(250)
    failures.append(f"new-post/{page}: NO IFRAME (url {pg.url})"); return None
def open_new_post(pg):
    pg.goto(f"{BASE}{M}/new-post", wait_until="load", timeout=90000); pg.wait_for_timeout(2000)
    card=pg.get_by_text("Tim", exact=True)
    if card.count(): card.first.click(); pg.wait_for_timeout(2000)
    return frame(pg)
def pick(pg, fr, timeout=5000):
    """Click Add media and give the chooser the PNG; returns the chooser, or None when none fired."""
    try:
        with pg.expect_file_chooser(timeout=timeout) as fc: fr.locator(ADD_MEDIA).click()
    except PlaywrightTimeout:
        return None
    fc.value.set_files(PNG)
    return fc.value
def wait_url(pg, path):
    for _ in range(40):
        if urlparse(pg.url).path==path: return
        pg.wait_for_timeout(250)
def wait_for(pg, fn, want):
    for _ in range(40):
        got=fn()
        if got==want: return got
        pg.wait_for_timeout(250)
    return fn()
with sync_playwright() as p:
    b=p.chromium.launch()

    # Single Creator: pick the PNG, it uploads, the next Post sends its claim.
    pg, uploads, held, posts, errs=session(b, "localStorage.setItem('chatterly:scope','model:1')")
    fr=open_new_post(pg)
    if fr:
        fr.locator(EDITOR).fill("Synthetic post"); pg.wait_for_timeout(300)
        add=fr.locator(ADD_MEDIA)
        check("1: Add media carries data-oi-wired", add.get_attribute("data-oi-wired"), "")
        try:
            with pg.expect_file_chooser(timeout=5000) as fc: add.click()
            chooser=fc.value
        except PlaywrightTimeout:
            chooser=None
        check("1: clicking Add media fires a file chooser", chooser is not None, True)
    if fr and chooser:
        check("1: the chooser's input takes images, videos and audio, several files",
              chooser.element.evaluate("e => [e.getAttribute('accept'), e.hasAttribute('multiple')]"), ["image/*,video/*,audio/*", True])
        chooser.set_files(PNG)
        wait_for(pg, lambda: len(held), 1)
        check("2: Post is disabled while the upload is in flight", fr.locator(POST).is_disabled(), True)
        if held: answer(held[0], ACCEPTED)
        check("2: Post is enabled once the accepted upload settled", wait_for(pg, lambda: fr.locator(POST).is_disabled(), False), False)
        check("4: one thumb from a blob: URL, loaded", wait_for(pg, lambda: fr.evaluate(THUMBS), [[True, True]]), [[True, True]])
        check("3: exactly one upload, X-Account-Id 1, one part `file` with the PNG's name and bytes", uploads,
              [("1", [["file", PNG["name"], PIXEL.hex()]])])
        pg.screenshot(path=f"{SHOTS}/inapp-post-upload-thumb.png")
        fr.locator(POST).click()
        wait_for(pg, lambda: len(posts), 1); pg.wait_for_timeout(500)
        check("4: Post sends exactly one POST /posts with the claim, X-Account-Id 1", posts,
              [({"text":"Synthetic post","media_files":[CLAIM],"price":0}, "1")])
    print("single creator console errors:", [e[:160] for e in errs][:8])
    check("8: no console errors", errs, [])
    pg.context.close()

    # Single Creator: two picks in flight; Post comes back by Phase 0's rule only when both settled (refused, failed).
    pg, uploads, held, posts, errs=session(b, "localStorage.setItem('chatterly:scope','model:1')")
    fr=open_new_post(pg)
    if fr:
        fr.locator(EDITOR).fill("Synthetic post"); pg.wait_for_timeout(300)
        picked=[pick(pg, fr) is not None, pick(pg, fr) is not None]
        check("2: a second pick is allowed while the first is in flight", [picked, wait_for(pg, lambda: len(held), 2)], [[True, True], 2])
        check("2: Post is disabled while two uploads are in flight", fr.locator(POST).is_disabled(), True)
    if fr and len(held)==2:
        with pg.expect_event("requestfinished", predicate=lambda r: urlparse(r.url).path==UPLOAD): answer(held[0], REFUSED)
        pg.wait_for_timeout(300)
        check("2: Post stays disabled after a refusal while the other upload is in flight", fr.locator(POST).is_disabled(), True)
        answer(held[1], 502)
        check("2: Post is enabled once the failed upload settled too", wait_for(pg, lambda: fr.locator(POST).is_disabled(), False), False)
        check("2: a refused or failed upload attaches nothing", fr.evaluate(THUMBS), [])
    pg.context.close()

    # Single Creator: an upload still in flight after a State page round trip keeps Post disabled until it settles.
    pg, uploads, held, posts, errs=session(b, "localStorage.setItem('chatterly:scope','model:1')")
    fr=open_new_post(pg)
    if fr:
        fr.locator(EDITOR).fill("Synthetic post"); pg.wait_for_timeout(300)
        pick(pg, fr)
        check("2: one upload held before the State page round trip", wait_for(pg, lambda: len(held), 1), 1)
        fr.locator(SCHEDULE).click()
        fr=frame(pg, "state-schedule")
    if fr:
        fr.locator(CANCEL).click()
        wait_url(pg, f"{M}/new-post")
        fr=frame(pg)
    if fr and held:
        check("2: Post is disabled after a State page round trip while the upload is in flight", fr.locator(POST).is_disabled(), True)
        answer(held[0], ACCEPTED)
        check("2: Post is enabled once the upload settled after the round trip", wait_for(pg, lambda: fr.locator(POST).is_disabled(), False), False)
        check("2: the visible composer shows the thumb accepted after the round trip", wait_for(pg, lambda: fr.evaluate(THUMBS), [[True, True]]), [[True, True]])
    pg.context.close()
    # Single Creator: a refused upload leaves the text, the attached claim p2 and the draft alone and sends no post.
    pg, uploads, held, posts, errs=session(b, "localStorage.setItem('chatterly:scope','model:1')")
    fr=open_new_post(pg)
    if fr:
        fr.locator(EDITOR).fill("Synthetic post"); pg.wait_for_timeout(300)
        pick(pg, fr)
        wait_for(pg, lambda: len(held), 1)
        if held: answer(held[0], {**ACCEPTED, "send_with":[CLAIM2]})
        check("5: the accepted claim p2 is attached first", wait_for(pg, lambda: fr.evaluate(THUMBS), [[True, True]]), [[True, True]])
        pick(pg, fr)
        check("5: the second pick uploads", wait_for(pg, lambda: len(held), 2), 2)
    if fr and len(held)==2:
        with pg.expect_event("requestfinished", predicate=lambda r: urlparse(r.url).path==UPLOAD): answer(held[1], REFUSED)
        check("5: a refusal shows the Relay's note in red", wait_for(pg, lambda: fr.evaluate(NOTE), ["Could not upload: Synthetic refusal", True]),
              ["Could not upload: Synthetic refusal", True])
        pg.screenshot(path=f"{SHOTS}/inapp-post-upload-refused.png")
        check("5: the strip still has exactly one thumb", fr.evaluate(THUMBS), [[True, True]])
        check("5: the editor still holds the text", fr.locator(EDITOR).inner_text(), "Synthetic post")
        check("5: the draft's media_files is still the p2 claim", pg.evaluate(DRAFT_MEDIA), [CLAIM2])
        pg.wait_for_timeout(1000)
        check("5: no post is sent", posts, [])
        pick(pg, fr)
        if wait_for(pg, lambda: len(held), 3)==3:
            with pg.expect_event("requestfinished", predicate=lambda r: urlparse(r.url).path==UPLOAD): answer(held[2], {"ready":False,"send_with":None})
        check("5: a refusal with no note reads `upload not ready`", wait_for(pg, lambda: fr.evaluate(NOTE), ["Could not upload: upload not ready", True]),
              ["Could not upload: upload not ready", True])
        check("5: the draft's media_files is still the p2 claim after both refusals", pg.evaluate(DRAFT_MEDIA), [CLAIM2])
    print("refusal console errors:", [e[:160] for e in errs][:8])
    check("8: no console errors after a refusal", errs, [])
    pg.context.close()

    # Single Creator: a failed upload (Relay 502) attaches nothing, and the same file can be picked again.
    pg, uploads, held, posts, errs=session(b, "localStorage.setItem('chatterly:scope','model:1')")
    fr=open_new_post(pg)
    if fr:
        pick(pg, fr)
        check("6: the first pick uploads", wait_for(pg, lambda: len(held), 1), 1)
    if fr and held:
        answer(held[0], 502)
        note_got=wait_for(pg, lambda: fr.evaluate(NOTE), ["Could not upload: Synthetic relay error", True])
        check("6: a failed upload shows a red note starting `Could not upload:`",
              bool(note_got) and [note_got[0].startswith("Could not upload:"), note_got[1]], [True, True])
        check("6: a failed upload adds no thumb", fr.evaluate(THUMBS), [])
        before=len(uploads)
        pick(pg, fr)
        check("6: picking the same PNG again sends a second upload with its bytes", [before, wait_for(pg, lambda: len(uploads), 2), uploads],
              [1, 2, [("1", [["file", PNG["name"], PIXEL.hex()]])]*2])
        if len(held)==2: answer(held[1], 502)
        pg.wait_for_timeout(500)
    print("failed upload console errors:", [e[:160] for e in errs][:8])
    check("8: no console error after a failed upload but the 502's resource line", [e for e in errs if not e.startswith("Failed to load resource")], [])
    pg.context.close()
    # Single Creator: a dedupe hit's vault id is appended as returned, even when the draft already holds it.
    seed={"text":"","tagged_users":[],"media_files":[42],"thumbs":["data:image/png;base64,"+base64.b64encode(PIXEL).decode()]}
    pg, uploads, held, posts, errs=session(b, "localStorage.setItem('chatterly:scope','model:1');"
        f"if (!sessionStorage.getItem('oi:new-post:1')) sessionStorage.setItem('oi:new-post:1', {json.dumps(json.dumps(seed))})")
    fr=open_new_post(pg)
    if fr:
        check("9: vault id 42 is in the draft before the upload", pg.evaluate(DRAFT_MEDIA), [42])
        fr.locator(EDITOR).fill("Synthetic post"); pg.wait_for_timeout(300)
        pick(pg, fr)
        check("9: the pick uploads", wait_for(pg, lambda: len(held), 1), 1)
    if fr and held:
        answer(held[0], {"ready":True,"deduped":True,"vault_id":42,"send_with":[42]})
        check("9: the dedupe hit is appended to the draft", wait_for(pg, lambda: pg.evaluate(DRAFT_MEDIA), [42, 42]), [42, 42])
        check("9: Post is enabled once the dedupe hit settled", wait_for(pg, lambda: fr.locator(POST).is_disabled(), False), False)
        fr.locator(POST).click()
        wait_for(pg, lambda: len(posts), 1); pg.wait_for_timeout(500)
        check("9: Post sends media_files [42, 42]", posts, [({"text":"Synthetic post","media_files":[42, 42],"price":0}, "1")])
    print("dedupe console errors:", [e[:160] for e in errs][:8])
    check("8: no console errors after a dedupe hit", errs, [])
    pg.context.close()

    # Single Creator: an accepted upload stays attached, thumb and all, across a State page round trip.
    pg, uploads, held, posts, errs=session(b, "localStorage.setItem('chatterly:scope','model:1')")
    fr=open_new_post(pg)
    if fr:
        fr.locator(EDITOR).fill("Synthetic post"); pg.wait_for_timeout(300)
        pick(pg, fr)
        check("10: the pick uploads", wait_for(pg, lambda: len(held), 1), 1)
    if fr and held:
        answer(held[0], ACCEPTED)
        check("10: the accepted thumb shows before the round trip", wait_for(pg, lambda: fr.evaluate(THUMBS), [[True, True]]), [[True, True]])
        fr.locator(SCHEDULE).click()
        fr=frame(pg, "state-schedule")
    if fr and held:
        fr.locator(CANCEL).click()
        wait_url(pg, f"{M}/new-post")
        fr=frame(pg)
    if fr and held:
        check("10: back on new-post the strip shows one blob: thumb, loaded", wait_for(pg, lambda: fr.evaluate(THUMBS), [[True, True]]), [[True, True]])
        pg.screenshot(path=f"{SHOTS}/inapp-post-upload-round-trip.png")
        check("10: Post is enabled after the round trip", wait_for(pg, lambda: fr.locator(POST).is_disabled(), False), False)
        fr.locator(POST).click()
        wait_for(pg, lambda: len(posts), 1); pg.wait_for_timeout(500)
        check("10: Post sends the claim after the round trip", posts, [({"text":"Synthetic post","media_files":[CLAIM],"price":0}, "1")])
    print("round trip console errors:", [e[:160] for e in errs][:8])
    check("8: no console errors after a State page round trip", errs, [])
    pg.context.close()

    # Single Creator: after a full reload the accepted upload's blob: URL is dead; its thumb is a grey square, its media stays.
    pg, uploads, held, posts, errs=session(b, "localStorage.setItem('chatterly:scope','model:1')")
    fr=open_new_post(pg)
    if fr:
        pick(pg, fr)
        check("11: the pick uploads", wait_for(pg, lambda: len(held), 1), 1)
    if fr and held:
        answer(held[0], ACCEPTED)
        check("11: before the reload the square shows the picture", wait_for(pg, lambda: fr.evaluate(SQUARES), [[64, 64, "rgba(0, 0, 0, 0)", 0]]),
              [[64, 64, "rgba(0, 0, 0, 0)", 0]])
        fr=open_new_post(pg)
    if fr and held:
        check("11: after a full reload one 64px grey square, no broken <img> showing",
              wait_for(pg, lambda: fr.evaluate(SQUARES), [[64, 64, "rgb(138, 150, 163)", 0]]), [[64, 64, "rgb(138, 150, 163)", 0]])
        check("11: the claim is still in the draft's media_files", pg.evaluate(DRAFT_MEDIA), [CLAIM])
        pg.screenshot(path=f"{SHOTS}/inapp-post-upload-reloaded.png")
    # The dead blob: URL's own load failure is Chromium's resource line, not the app's.
    print("reload console errors:", [e[:160] for e in errs][:8])
    check("8: no console error after a reload but a dead blob: resource line", [e for e in errs if not e.startswith("Failed to load resource")], [])
    pg.context.close()

    # All Creators: the scope key cleared before every load; New post stands in with the first listed creator.
    pg, uploads, held, posts, errs=session(b, "localStorage.removeItem('chatterly:scope')")
    fr=open_new_post(pg)
    if fr:
        check("7: scope key absent", pg.evaluate("localStorage.getItem('chatterly:scope')"), None)
        check("7: clicking Add media opens the file chooser (the stand-in creator)", pick(pg, fr) is not None, True)
        pg.wait_for_timeout(1500)
        pg.screenshot(path=f"{SHOTS}/inapp-post-upload-all-creators.png")
        check("7: one upload, for the stand-in creator, and no post", [[u[0] for u in uploads], posts], [["acc1"], []])
    print("all creators console errors:", [e[:160] for e in errs][:8])
    check("8: no console errors in All Creators", errs, [])
    pg.context.close()
check("8: no request left localhost", [f for f in failures if f.startswith("request to a non-localhost host")], [])
if failures:
    print("FAIL:", *failures, sep="\n  "); sys.exit(1)
print("post upload ok")
