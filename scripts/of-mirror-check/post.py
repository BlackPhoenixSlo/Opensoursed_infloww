"""New post (app/lib/ofMirrorPost.ts): Post sends exactly one POST /api/of/v2/posts for the selected Creator.

Mocks the login (as writes.py) and the relay, scope `model:1` (as data.py); every unmocked /api/** returns [] and any
request to a host other than localhost is aborted and fails the check. Checks in the frame:
Run 1: Post is disabled at first; typing "Synthetic post" enables it; pressing it sends exactly one
POST /api/of/v2/posts {"text":"Synthetic post","media_files":[],"price":0} with X-Account-Id: 1, stays on
/of-manager/new-post with the composer empty and OF's toast "Your post has been published", and the draft key
(sessionStorage oi:new-post:1) is gone.
Run 2 (schedule): type the text, open Schedule, move to tomorrow, click it, type "6:30 pm" and press Next: back on the
composer the text is restored and the "Scheduled for <date> 6:30 PM · Clear" summary shows; Schedule then Cancel leaves
the summary unchanged; Tag other creators lists the mocked Relay's "Alpha One" (901) and "Beta Two" (902) from one
GET /api/of/v2/posts/tagged-friend-users?limit=50&offset=0 (X-Account-Id: 1) and no "List <n>" example text; checking
Alpha One and pressing Close shows "Tagged: Alpha One" in the summary; Post sends exactly one POST /api/of/v2/posts with
posted_at = Python's datetime(tomorrow, 18:30).astimezone().isoformat() and tagged_users [901], and stays with the toast
"Your post is scheduled for …".
Tag list failure: with tagged-friend-users answering 502, the tag dialog shows no rows (never the captured examples); the
following Post carries no tagged_users.
Validation: Next with today at 12:00 am (already past) sends nothing, stores no schedule and shows the red note.
Save for Later (marked wired) sends nothing, stores save_for_later in the draft and returns to the composer.
Extras: new-post/state-labels lists the mocked Relay's "Alpha label" (11) from GET /api/of/v2/labels; checking it and
typing two options on new-post/state-poll send nothing, add label_ids [11] and the poll to the draft and show no note;
the poll's "7 days" piece opens new-post/state-expiration titled "POLL DURATION", whose "3 days" tab and Save return to
the poll with the piece at "3 days" and the options kept; New post (loaded afresh) names the label in its summary
("Labels: Alpha label"); Post then sends exactly one POST /api/of/v2/posts with
label_ids [11], voting_type 1, voting_options ["Yes","No"] and voting_due 3, and stays with the toast.
Error: with the mock answering 502, the page shows the red "Could not post: <relay text>" note, Post is enabled again,
the draft is kept and the page stays on New post.
All-Creators (scope key removed before every load): New post stands in with the first listed creator ("Showing Model
One, pick a model to switch" over the frame), so Post sends its POST /api/of/v2/posts with X-Account-Id acc1.
Screenshots: /tmp/of-mirror-shots/inapp-post-*.png. Exit 1 on a failed check.
"""
import json, os, sys
from datetime import date, datetime, timedelta
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
BASE=f"http://localhost:{os.environ.get('PORT','3091')}"
M="/of-manager"
SHOTS="/tmp/of-mirror-shots"
os.makedirs(SHOTS, exist_ok=True)
user={"user_id":"u1","username":"tester","is_admin":False}
POSTS="/api/of/v2/posts"
EDITOR="[contenteditable][aria-label='Textbox field']"
POST="button[at-attr='submit_post']"
SELECT_MODEL="Select a model to save changes"
TOO_SOON="Pick a time at least a minute from now"
SCHEDULE="a[at-attr='scheduled_msg']"
TAG="a[aria-label='Tag other creators']"
TAGS="/api/of/v2/posts/tagged-friend-users"
TAG_ROW="label.b-rows-lists__item"
LABELS="/api/of/v2/labels"
LABEL_ITEMS=[{"id":11,"name":"Alpha label","postsCount":3}]
# the poll panel's "Poll · 7 days" piece and its value
PIECE=".b-make-post__voting .b-post-piece"
PIECE_VALUE=f"{PIECE} .b-post-piece__value"
TAG_ITEMS=[{"id":901,"name":"Alpha One","type":"user","user":{"id":901,"name":"Alpha One","username":"alphaone"}},
           {"id":902,"name":"Beta Two","type":"user","user":{"id":902,"name":"Beta Two","username":"betatwo"}}]
# the tag dialog's shown rows: [data-oi-user, name, subline]
ROWS="[...document.querySelectorAll('label.b-rows-lists__item')].filter(r => r.getClientRects().length).map(r => [r.getAttribute('data-oi-user'), r.querySelector('.b-rows-lists__item__name').textContent.trim(), r.querySelector('.b-rows-lists__item__subline').textContent.trim()])"
EXAMPLE_TEXT="/\\bList \\d+/.test(document.querySelector('.b-rows-lists').innerText)"
NEXT=".vdatetime-popup__actions__button--confirm button"
SUMMARY="(() => { const n = document.getElementById('oi-post-summary'); return n ? [n.textContent, getComputedStyle(n).color] : null; })()"
TODAY=date.today(); TOMORROW=TODAY+timedelta(days=1)
GREY="rgb(138, 150, 163)"; RED="rgb(255, 69, 69)"
RELAY_ERROR="Synthetic relay failure"
NOTE="(() => { const n = document.getElementById('oi-note'); return n ? [n.textContent, getComputedStyle(n).color] : null; })()"
DRAFT="sessionStorage.getItem('oi:new-post:1')"
TOAST="document.querySelector('.toasts-host .v-snack.m-alert .toast__text')?.textContent ?? null"
POSTED="Your post has been published"
failures=[]
def check(label, got, want):
    print(json.dumps({"check":label,"got":got,"want":want}))
    if got!=want: failures.append(f"{label}: got {got!r}, expected {want!r}")
def session(b, scope_js, post_status=200, tags_status=200):
    """A fresh context and page with scope_js run before every load; returns (page, sent writes, tag list GETs
    as (query, X-Account-Id), console errors, open_new_post)."""
    ctx=b.new_context(viewport={"width":1440,"height":900})
    ctx.add_init_script(scope_js)
    def outside(route):
        failures.append(f"request to a non-localhost host: {route.request.url[:120]}")
        route.abort()
    ctx.route(lambda url: urlparse(url).hostname not in ("localhost","127.0.0.1"), outside)
    pg=ctx.new_page()
    sent=[]; tag_gets=[]
    def mock(route):
        req=route.request; u=req.url; path=urlparse(u).path
        if req.method=="GET" and path==TAGS:
            tag_gets.append((urlparse(u).query, req.headers.get("x-account-id")))
            body={"items":TAG_ITEMS,"hasMore":False} if tags_status==200 else {"detail":RELAY_ERROR}
            return route.fulfill(status=tags_status, content_type="application/json", body=json.dumps(body))
        if req.method=="GET" and path==LABELS:
            return route.fulfill(status=200, content_type="application/json", body=json.dumps({"list":LABEL_ITEMS,"hasMore":False}))
        if req.method!="GET" and path.startswith("/api/"):
            sent.append((req.method, path, req.post_data_json if req.post_data else None, req.headers.get("x-account-id")))
            if path==POSTS:
                body={"id":1} if post_status==200 else {"detail":RELAY_ERROR}
                return route.fulfill(status=post_status, content_type="application/json", body=json.dumps(body))
        if "/auth/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps(user))
        elif u.split("?")[0].endswith("/admin/accounts"): route.fulfill(status=200, content_type="application/json", body='{"accounts":[{"id":"acc1","nickname":"Model One","has_session":true},{"id":"1","nickname":"Model Two","has_session":true}],"active_account_id":null}')  # creators: none shows OfNotHaveModel
        elif "/chatter/me/accounts" in u: route.fulfill(status=200, content_type="application/json", body="[]")
        elif "/admin/employees" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"employees":[{"id":1,"display_name":"Tim","color":"#a78bfa","is_active":True,"chatter_id":None}]}))
        elif "/chatter/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"chatter":None,"owners":[]}))
        else: route.fulfill(status=200, content_type="application/json", body="[]")
    for pat in ["**/auth/**","**/chatter/**","**/admin/**","**/accounts**","**/api/**"]: pg.route(pat, mock)
    pg.route("**/events?**", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=""))  # no Relay: an empty stream, not a 500
    errs=[]; pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
    def open_new_post(page="index"):
        pg.goto(f"{BASE}{M}/new-post" + ("" if page=="index" else f"/{page}"), wait_until="load", timeout=90000); pg.wait_for_timeout(2000)
        card=pg.get_by_text("Tim", exact=True)
        if card.count(): card.first.click(); pg.wait_for_timeout(2000)
        return frame(pg, page)
    return pg, sent, tag_gets, errs, open_new_post
def frame(pg, page="index"):
    """The loaded new-post/<page> frame, once useOfPost has bound it."""
    for _ in range(60):
        fr=[f for f in pg.frames if f.url.endswith(f"/of-mirror/pages/new-post/{page}.html")]
        if fr and fr[0].evaluate("document.readyState")=="complete":
            pg.wait_for_timeout(500)  # useOfPost binds on the frame's load
            return fr[0]
        pg.wait_for_timeout(250)
    failures.append(f"new-post/{page}: NO IFRAME (url {pg.url})"); return None
def pick(fr, day, time):
    """In the schedule dialog: show day's month with the next arrow, click the day, type the time."""
    for _ in range(3):
        if fr.locator(".vdatetime-calendar__current--month").inner_text().strip()==day.strftime("%B %Y"): break
        fr.locator(".vdatetime-calendar__navigation--next").click()
    fr.locator(".vdatetime-calendar__month").get_by_text(str(day.day), exact=True).click()
    fr.locator(".vdatetime-popup__tab.time").fill(time)
def wait_url(pg, path):
    for _ in range(40):
        if urlparse(pg.url).path==path: return
        pg.wait_for_timeout(250)
def wait_toast(pg, fr):
    """OF's toast text once it shows (None after 10s)."""
    for _ in range(40):
        if (t:=fr.evaluate(TOAST)): return t
        pg.wait_for_timeout(250)
    return None
def console_ok(label, errs, failed_loads=0):
    # the Error case's 502 is logged by the browser as one failed resource load; only there, and exactly once
    loads=[e for e in errs if "Failed to load resource" in e and "502" in e]
    if len(loads)!=failed_loads: failures.append(f"{label}: {len(loads)} failed 502 load(s), expected {failed_loads}")
    errs=[e for e in errs if e not in loads]
    print(f"{label} console errors:", [e[:160] for e in errs][:8])
    if errs: failures.append(f"{label}: {len(errs)} console error(s)")
WANT={"text":"Synthetic post","media_files":[],"price":0}
with sync_playwright() as p:
    b=p.chromium.launch()

    # Run 1: a text-only post for Creator 1.
    pg, sent, tag_gets, errs, open_new_post=session(b, "localStorage.setItem('chatterly:scope','model:1')")
    fr=open_new_post()
    if fr:
        check("run 1: Post disabled at first", fr.locator(POST).is_disabled(), True)
        fr.locator(EDITOR).fill("Synthetic post")
        check("run 1: typing enables Post", fr.locator(POST).is_enabled(), True)
        check("run 1: the placeholder is gone", fr.locator(EDITOR).get_attribute("data-is-empty"), "false")
        check("run 1: the draft is kept for Creator 1", json.loads(pg.evaluate(DRAFT) or "{}").get("text"), "Synthetic post")
        pg.wait_for_timeout(600)  # OF's own placeholder and button transitions
        pg.screenshot(path=f"{SHOTS}/inapp-post-typed.png")
        fr.locator(POST).click()
        check("run 1: OF's toast says the post is published", wait_toast(pg, fr), POSTED)
        check("run 1: exactly one POST /posts with the body and X-Account-Id: 1", sent, [("POST",POSTS,WANT,"1")])
        check("run 1: stays on New post", urlparse(pg.url).path, f"{M}/new-post")
        check("run 1: the composer is empty and Post disabled", [fr.locator(EDITOR).inner_text().strip(), fr.locator(POST).is_disabled()], ["", True])
        check("run 1: the draft key is gone", pg.evaluate(DRAFT), None)
        pg.screenshot(path=f"{SHOTS}/inapp-post-posted.png")
    console_ok("run 1", errs)
    pg.context.close()

    # Run 2: a post scheduled for tomorrow 6:30 pm.
    pg, sent, tag_gets, errs, open_new_post=session(b, "localStorage.setItem('chatterly:scope','model:1')")
    fr=open_new_post()
    if fr:
        at=datetime(TOMORROW.year, TOMORROW.month, TOMORROW.day, 18, 30).astimezone().isoformat()
        want_summary=[f"Scheduled for {TOMORROW.strftime('%a, %b')} {TOMORROW.day}, 6:30 PM · Clear", GREY]
        fr.locator(EDITOR).fill("Synthetic post")
        fr.locator(SCHEDULE).click()
        fr=frame(pg, "state-schedule")
    if fr:
        check("run 2: the calendar shows the current month", fr.locator(".vdatetime-calendar__current--month").inner_text().strip(), TODAY.strftime("%B %Y"))
        pick(fr, TOMORROW, "6:30 pm")
        check("run 2: the header shows tomorrow", fr.locator(".vdatetime-popup__date").inner_text().strip(), f"{TOMORROW.day} {TOMORROW.strftime('%B')}")
        pg.wait_for_timeout(400)
        pg.screenshot(path=f"{SHOTS}/inapp-post-schedule.png")
        fr.locator(NEXT).click()
        wait_url(pg, f"{M}/new-post")
        fr=frame(pg)
    if fr:
        check("run 2: Next returns to the composer", urlparse(pg.url).path, f"{M}/new-post")
        check("run 2: the text is restored", fr.locator(EDITOR).inner_text().strip(), "Synthetic post")
        check("run 2: the summary shows the schedule", fr.evaluate(SUMMARY), want_summary)
        check("run 2: the summary is visible", fr.locator("#oi-post-summary").is_visible(), True)
        pg.wait_for_timeout(400)
        pg.screenshot(path=f"{SHOTS}/inapp-post-scheduled.png")
        fr.locator(SCHEDULE).click()
        fr=frame(pg, "state-schedule")
    if fr:
        fr.locator(".vdatetime-popup__actions__button--cancel a").click()
        wait_url(pg, f"{M}/new-post")
        fr=frame(pg)
    if fr:
        check("run 2: Schedule then Cancel leaves the summary unchanged", fr.evaluate(SUMMARY), want_summary)
        fr.locator(TAG).click()
        fr=frame(pg, "state-tag-people")
    if fr:
        for _ in range(40):
            if fr.locator(f"{TAG_ROW}[data-oi-user]").count(): break
            pg.wait_for_timeout(250)
        check("run 2: the tag dialog lists the Creator's taggable creators", fr.evaluate(ROWS), [["901","Alpha One","@alphaone"],["902","Beta Two","@betatwo"]])
        check("run 2: no example row text", fr.evaluate(EXAMPLE_TEXT), False)
        check("run 2: one tag list GET, limit=50&offset=0, X-Account-Id: 1", tag_gets, [("limit=50&offset=0","1")])
        fr.locator(f"{TAG_ROW}[data-oi-user='901'] .b-rows-lists__item__name").click(); pg.wait_for_timeout(300)
        check("run 2: Alpha One is checked", fr.locator(f"{TAG_ROW}[data-oi-user='901'] input").is_checked(), True)
        check("run 2: the draft's Co-tags", json.loads(pg.evaluate(DRAFT) or "{}").get("tagged_users"), [901])
        pg.screenshot(path=f"{SHOTS}/inapp-post-tags.png")
        fr.locator("footer.modal-footer a", has_text="Close").click()
        wait_url(pg, f"{M}/new-post")
        fr=frame(pg)
    if fr:
        tagged_summary=[want_summary[0].replace(" · Clear", " · Tagged: Alpha One · Clear"), GREY]
        check("run 2: the summary names the Co-tag", fr.evaluate(SUMMARY), tagged_summary)
        pg.wait_for_timeout(400)
        pg.screenshot(path=f"{SHOTS}/inapp-post-tagged.png")
        check("run 2: nothing sent before Post", sent, [])
        fr.locator(POST).click()
        check("run 2: OF's toast names the moment", (wait_toast(pg, fr) or "").startswith("Your post is scheduled for "), True)
        check("run 2: exactly one POST /posts with posted_at, tagged_users and X-Account-Id: 1", sent, [("POST",POSTS,{**WANT,"posted_at":at,"tagged_users":[901]},"1")])
        check("run 2: stays on New post", urlparse(pg.url).path, f"{M}/new-post")
        check("run 2: the draft key is gone", pg.evaluate(DRAFT), None)
    console_ok("run 2", errs)
    pg.context.close()

    # Validation and Save for Later, in the schedule dialog.
    pg, sent, tag_gets, errs, open_new_post=session(b, "localStorage.setItem('chatterly:scope','model:1')")
    fr=open_new_post("state-schedule")
    if fr:
        pick(fr, TODAY, "12:00 am")
        fr.locator(NEXT).click(); pg.wait_for_timeout(1000)
        check("validation: nothing sent", sent, [])
        check("validation: the red note", fr.evaluate(NOTE), [TOO_SOON, RED])
        check("validation: the note is visible", fr.locator("#oi-note").is_visible(), True)
        check("validation: no schedule stored", json.loads(pg.evaluate(DRAFT) or "{}").get("posted_at"), None)
        check("validation: still in the dialog", urlparse(pg.url).path, f"{M}/new-post/state-schedule")
        pg.screenshot(path=f"{SHOTS}/inapp-post-validation.png")
        check("save for later: Save for Later is marked wired", fr.locator(".custom-datepicker-button-save-later").get_attribute("data-oi-wired"), "")
        check("save for later: Next is marked wired", fr.locator(NEXT).get_attribute("data-oi-wired"), "")
        fr.locator(".custom-datepicker-button-save-later").click()
        wait_url(pg, f"{M}/new-post")
        check("save for later: sends nothing", sent, [])
        check("save for later: stored in the draft", json.loads(pg.evaluate(DRAFT) or "{}").get("save_for_later"), True)
        check("save for later: back on the composer", urlparse(pg.url).path, f"{M}/new-post")
        pg.screenshot(path=f"{SHOTS}/inapp-post-save-later.png")
    console_ok("validation", errs)
    pg.context.close()

    # Extras: a label and a poll, then Post.
    pg, sent, tag_gets, errs, open_new_post=session(b, "localStorage.setItem('chatterly:scope','model:1')")
    fr=open_new_post("state-labels")
    if fr:
        row=fr.locator(f".modal.show {TAG_ROW}[data-oi-label='11']")
        for _ in range(40):
            if row.count(): break
            pg.wait_for_timeout(250)
        check("extras: the labels dialog lists the Creator's labels", fr.evaluate(ROWS.replace("data-oi-user","data-oi-label")), [["11","Alpha label","3 posts"]])
        row.click(); pg.wait_for_timeout(300)
        check("extras: the label is checked", row.locator("input").is_checked(), True)
        check("extras: no note on the label", fr.evaluate(NOTE), None)
        check("extras: the draft's labels", json.loads(pg.evaluate(DRAFT) or "{}").get("label_ids"), [11])
        pg.screenshot(path=f"{SHOTS}/inapp-post-labels.png")
        fr=open_new_post("state-poll")
    if fr:
        fr.locator(".b-make-post__voting input[placeholder='Enter first option...']").fill("Yes")
        fr.locator(".b-make-post__voting input[placeholder='Enter second option...']").fill("No"); pg.wait_for_timeout(300)
        check("extras: no note on the poll", fr.evaluate(NOTE), None)
        check("extras: the draft's poll", json.loads(pg.evaluate(DRAFT) or "{}").get("voting"), {"type":1,"options":["Yes","No"]})
        pg.screenshot(path=f"{SHOTS}/inapp-post-poll.png")
        check("extras: the poll piece shows OF's 7 days", fr.locator(PIECE_VALUE).inner_text().strip(), "7 days")
        fr.locator(PIECE).click()
        wait_url(pg, f"{M}/new-post/state-expiration")
        fr=frame(pg, "state-expiration")
    if fr:
        check("extras: the poll piece opens the period dialog, titled for the poll", fr.locator(".modal.show .modal-title").inner_text().strip(), "POLL DURATION")
        fr.locator(".modal.show .b-tabs__nav__link", has_text="3 days").click()
        pg.screenshot(path=f"{SHOTS}/inapp-post-poll-duration.png")
        fr.locator(".modal.show .modal-footer button", has_text="Save").click()
        wait_url(pg, f"{M}/new-post/state-poll")
        fr=frame(pg, "state-poll")
    if fr:
        check("extras: Save returns to the poll, whose piece shows 3 days", fr.locator(PIECE_VALUE).inner_text().strip(), "3 days")
        check("extras: the poll's options are kept", [fr.locator(f".b-make-post__voting input[placeholder='Enter {n} option...']").input_value() for n in ("first","second")], ["Yes","No"])
        check("extras: nothing sent before Post", sent, [])
        fr=open_new_post()
    if fr:
        for _ in range(40):
            if "Alpha label" in fr.evaluate("document.getElementById('oi-post-summary')?.textContent ?? ''"): break
            pg.wait_for_timeout(250)
        check("extras: the summary names the label (after a full load)", "Labels: Alpha label ·" in fr.evaluate("document.getElementById('oi-post-summary')?.textContent ?? ''"), True)
        fr.locator(EDITOR).fill("Synthetic post")
        fr.locator(POST).click()
        check("extras: OF's toast", wait_toast(pg, fr), POSTED)
        check("extras: exactly one POST /posts with the label and the poll", sent, [("POST",POSTS,{**WANT,"label_ids":[11],"voting_type":1,"voting_options":["Yes","No"],"voting_due":3},"1")])
    console_ok("extras", errs)
    pg.context.close()

    # Tag list failure: tagged-friend-users answers 502.
    pg, sent, tag_gets, errs, open_new_post=session(b, "localStorage.setItem('chatterly:scope','model:1')", tags_status=502)
    fr=open_new_post()
    if fr:
        fr.locator(EDITOR).fill("Synthetic post")
        fr.locator(TAG).click()
        fr=frame(pg, "state-tag-people")
    if fr:
        for _ in range(40):
            if tag_gets: break
            pg.wait_for_timeout(250)
        pg.wait_for_timeout(1000)
        check("tag list failure: the tag list was asked for once", tag_gets, [("limit=50&offset=0","1")])
        check("tag list failure: no rows, never the captured examples", fr.evaluate(ROWS), [])
        check("tag list failure: no Co-tag in the draft", json.loads(pg.evaluate(DRAFT) or "{}").get("tagged_users"), [])
        pg.screenshot(path=f"{SHOTS}/inapp-post-tags-failed.png")
        fr.locator("footer.modal-footer a", has_text="Close").click()
        wait_url(pg, f"{M}/new-post")
        fr=frame(pg)
    if fr:
        fr.locator(POST).click()
        wait_toast(pg, fr)
        check("tag list failure: Post carries no tagged_users", sent, [("POST",POSTS,WANT,"1")])
    console_ok("tag list failure", errs, failed_loads=1)
    pg.context.close()

    # Error: the relay answers 502.
    pg, sent, tag_gets, errs, open_new_post=session(b, "localStorage.setItem('chatterly:scope','model:1')", post_status=502)
    fr=open_new_post()
    if fr:
        fr.locator(EDITOR).fill("Synthetic post")
        fr.locator(POST).click(); pg.wait_for_timeout(1500)
        check("error: one POST /posts was tried", [s[:2] for s in sent], [("POST",POSTS)])
        check("error: the red Could not post note", fr.evaluate(NOTE), [f"Could not post: {RELAY_ERROR}", "rgb(255, 69, 69)"])
        check("error: the note is visible", fr.locator("#oi-note").is_visible(), True)
        check("error: Post enabled again", fr.locator(POST).is_enabled(), True)
        check("error: the draft is kept", json.loads(pg.evaluate(DRAFT) or "{}").get("text"), "Synthetic post")
        check("error: still on New post", urlparse(pg.url).path, f"{M}/new-post")
        pg.screenshot(path=f"{SHOTS}/inapp-post-error.png")
    console_ok("error", errs, failed_loads=1)
    pg.context.close()

    # All-Creators scope: the scope key cleared before every load. New post stands in with the first listed creator
    # (ofMirrorProfile's STAND_IN_SRC, the "Showing ..." line over the frame), so POST goes out for it.
    pg, sent, tag_gets, errs, open_new_post=session(b, "localStorage.removeItem('chatterly:scope')")
    fr=open_new_post()
    if fr:
        check("all creators: scope key absent", pg.evaluate("localStorage.getItem('chatterly:scope')"), None)
        check("all creators: the line over the frame names the stand-in", pg.get_by_test_id("of-standin-hint").inner_text(), "Showing Model One, pick a model to switch")
        fr.locator(EDITOR).fill("Synthetic post")
        fr.locator(POST).click(); pg.wait_for_timeout(1000)
        check("all creators: POST for the stand-in creator", sent, [("POST","/api/of/v2/posts",{"text":"Synthetic post","media_files":[],"price":0},"acc1")])
        pg.screenshot(path=f"{SHOTS}/inapp-post-all-creators.png")
    console_ok("all creators", errs)
    pg.context.close()
if failures:
    print("FAIL:", *failures, sep="\n  "); sys.exit(1)
print("post ok")
