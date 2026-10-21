"""Single-Creator scope: the queue rows' More menu writes through the relay (app/lib/ofMirrorQueue.ts).

Mocks the login (as feeds.py), the Creator list (account 1), GET /api/of/v2/schedules with SYNTHETIC wrapped schedule
items (a post with media ready, a message) and the three row writes (PUT /api/of/v2/schedules/<id>/publish,
DELETE /api/of/v2/posts/<id>, DELETE /api/of/v2/messages/queue/<id>), recording every relay call; any request to a
host other than localhost is aborted and fails the check. The mocked /schedules answers only the items in its
publish_date..publish_date_end. Scope `model:1`, browser time zone Europe/Ljubljana, the clock fixed at 2026-10-12 12:00,
on `queue/state-list-view`:
1. The post row's More opens OF's menu: Pin to your profile, Edit post, Post now, Delete post; the message row's:
   Edit message, Message now, Delete message. The right column lists today's (Oct 12) post.
2. Edit post and Edit message are enabled (no tooltip).
3. Post now with the confirm dismissed sends nothing; accepted, it sends exactly PUT /api/of/v2/schedules/901/publish
   (the schedule id) with X-Account-Id: 1, and the queue is asked for again.
4. Delete post with the confirm dismissed sends nothing; Delete message with it accepted sends exactly
   DELETE /api/of/v2/messages/queue/22 (the message id).
5. Month navigation on `queue` (the calendar): its days marked with OF's event bars and counts, nothing under it; the
   back arrow is greyed out on today's month; next_month shows "November 2026", asks /schedules for exactly
   publish_date=2026-11-01, publish_date_end=2026-11-30 and marks only the November post's day; prev_month brings
   October's two days back; a click on Oct 14 shows "October 14, 2026" in the right column with that day's message; the
   Messages tab leaves only the message's day, Posts with it both; nothing is sent.
6. Add to queue: the header's "+" opens OF's modal (Add to queue; Scheduled / Save for later; date, time and types),
   its Post opens New post with the picked moment on the draft; a saved-for-later page's "+" opens it on Save for later.
7. Edit post reads GET /api/of/v2/posts/11 (mocked) and opens New post filled ("Editing a scheduled post"); Post sends
   exactly PUT /api/of/v2/queue/posts/11 with the post's text and date, no POST. Edit message reads GET
   /api/of/v2/messages/queue/22 (mocked, with recipients and lists) and opens New message filled; Send sends exactly
   PUT /api/of/v2/messages/queue/22 with its text, lists, recipients and date.
8. No console errors.
Prints one {"check","want","got"} line per check. Screenshots: /tmp/of-mirror-shots/inapp-queue-menu.png,
inapp-queue-november.png. Exit 1 on a failed check.
"""
import json, os, sys
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright
BASE=f"http://localhost:{os.environ.get('PORT','3091')}"
SHOTS="/tmp/of-mirror-shots"
os.makedirs(SHOTS, exist_ok=True)
user={"user_id":"u1","username":"tester","is_admin":False}
ACCOUNTS={"accounts":[{"id":"1","nickname":"Model One","has_session":True}],"active_account_id":None}
NOT_YET="Not available in Inflowwww yet"
TZ="Europe/Ljubljana"
# The calendar's event bars: "<day> <type> <count>" per bar (OF names a bar by its count).
BARS="[...document.querySelectorAll('.v-calendar-monthly .v-event[data-oi-data]')].map(b => `${b.dataset.date} ${['post','chat','stream'].find(c => b.classList.contains(c))} ${b.textContent}`)"
OCT_BARS=["2026-10-12 post 1","2026-10-14 chat 1"]
NOW=datetime(2026,10,12,12,0,tzinfo=ZoneInfo(TZ))
SCHEDULES=[{"id":901,"type":"post","publishDateTime":"2026-10-12T09:05:00","entity":{"id":11,"text":"Alpha post","isMediaReady":True}},
           {"id":903,"type":"chat","publishDateTime":"2026-10-14T18:30:00","entity":{"id":22,"text":"Alpha message","scheduledAt":"2026-10-14T18:30:00"}},
           {"id":905,"type":"post","publishDateTime":"2026-11-03T10:00:00","entity":{"id":15,"text":"November post"}}]
WRITES={("PUT","/api/of/v2/schedules/901/publish"),("DELETE","/api/of/v2/posts/11"),("DELETE","/api/of/v2/messages/queue/22"),
        ("PUT","/api/of/v2/queue/posts/11"),("PUT","/api/of/v2/messages/queue/22")}
# What Edit reads: the post (OF's GET /posts/{id}) and the queued message (GET /messages/queue/{id}?format=scheduled).
EDIT_READS={"/api/of/v2/posts/11":{"id":11,"rawText":"Alpha post","text":"<p>Alpha post</p>","postedAt":"2026-10-20T10:00:00+02:00","canEditSchedule":True},
            "/api/of/v2/messages/queue/22":{"id":22,"text":"<p>Alpha message</p>","scheduledAt":"2026-10-21T18:30:00+02:00","userIds":[501],"userLists":["fans"],"excludedLists":[]}}
bodies={}
MENU="[...document.querySelectorAll('#oi-queue-menu button')].map(b => [b.getAttribute('at-attr'), b.textContent.trim()])"
NOTE="document.getElementById('oi-note')?.textContent ?? null"
# The rows outside the right column, and in it: their text.
MAIN="[...document.querySelectorAll('.b-agenda__area-events__item')].filter(e => e.checkVisibility() && !e.closest('.l-wrapper__sidebar')).map(e => e.querySelector('.b-agenda__area-events__item-inward').textContent)"
SIDE="[...document.querySelectorAll('.l-wrapper__sidebar .b-agenda__area-events__item')].filter(e => e.checkVisibility()).map(e => e.querySelector('.b-agenda__area-events__item-inward').textContent)"
HEADER="[...document.querySelectorAll('.b-queue-header__date')].map(e => e.textContent.trim())"
failures=[]
def check(label, got, want):
    print(json.dumps({"check":label,"want":want,"got":got}))
    if got!=want: failures.append(f"{label}: got {got!r}, expected {want!r}")
with sync_playwright() as p:
    b=p.chromium.launch()
    ctx=b.new_context(viewport={"width":1440,"height":900}, timezone_id=TZ)
    ctx.add_init_script("localStorage.setItem('chatterly:scope','model:1')")
    ctx.clock.set_fixed_time(NOW)
    foreign=lambda url: urlparse(url).hostname not in ("localhost","127.0.0.1")
    def outside(route):
        failures.append(f"request to a non-localhost host: {route.request.url[:120]}")
        route.abort()
    ctx.route(foreign, outside)
    pg=ctx.new_page()
    calls=[]; queries=[]
    def mock(route):
        req=route.request; u=req.url; path=urlparse(u).path
        if foreign(u): return outside(route)
        if path.startswith("/api/"): calls.append([req.method, path, req.headers.get("x-account-id")])
        if req.method!="GET" and path.startswith("/api/"): bodies[(req.method, path)]=json.loads(req.post_data or "null")
        if req.method=="GET" and path in EDIT_READS: return route.fulfill(status=200, content_type="application/json", body=json.dumps(EDIT_READS[path]))
        if path=="/api/of/v2/schedules":
            q=parse_qs(urlparse(u).query); queries.append({k: v[0] for k, v in q.items() if k.startswith("publish_date")})
            span=q.get("publish_date",[""])[0], q.get("publish_date_end",[""])[0]
            items=[i for i in SCHEDULES if span[0]<=i["publishDateTime"][:10]<=span[1]]
            return route.fulfill(status=200, content_type="application/json", body=json.dumps({"list":items,"hasMore":False}))
        if (req.method, path) in WRITES: return route.fulfill(status=200, content_type="application/json", body='{"success":true}')
        if "/auth/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps(user))
        elif "/chatter/me/accounts" in u: route.fulfill(status=200, content_type="application/json", body="[]")
        elif path=="/admin/accounts": route.fulfill(status=200, content_type="application/json", body=json.dumps(ACCOUNTS))
        elif "/admin/employees" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"employees":[{"id":1,"display_name":"Tim","color":"#a78bfa","is_active":True,"chatter_id":None}]}))
        elif "/chatter/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"chatter":None,"owners":[]}))
        else: route.fulfill(status=200, content_type="application/json", body="[]")
    for pat in ["**/auth/**","**/chatter/**","**/admin/**","**/accounts**","**/api/**","**/img?**"]: pg.route(pat, mock)
    pg.route("**/events?**", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=""))  # no Relay: an empty stream, not a 500
    errs=[]; pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
    pg.on("pageerror", lambda e: errs.append(f"uncaught: {e}"))
    answer={"accept":False}
    pg.on("dialog", lambda d: d.accept() if answer["accept"] else d.dismiss())
    pg.goto(f"{BASE}/of-manager/queue/state-list-view", wait_until="load", timeout=90000); pg.wait_for_timeout(1500)
    card=pg.get_by_text("Tim", exact=True)
    if card.count(): card.first.click(); pg.wait_for_timeout(1500)
    fr=None
    for _ in range(60):
        fs=[f for f in pg.frames if f.url.endswith("/of-mirror/pages/queue/state-list-view.html")]
        if fs and fs[0].evaluate("document.querySelectorAll('[at-attr=more_menu]').length")==3: fr=fs[0]; break
        pg.wait_for_timeout(250)
    if not fr: failures.append("queue/state-list-view: no frame with three More buttons (two rows, today's in the right column)")
    else:
        more=fr.locator("[at-attr=more_menu]")
        writes=lambda: [c for c in calls if c[0]!="GET"]
        check("the rows, and today's in the right column", [fr.evaluate(MAIN), fr.evaluate(SIDE)], [["Alpha post","Alpha message"],["Alpha post"]])
        more.nth(0).click(); pg.wait_for_timeout(200)
        check("post row: OF's post menu", fr.evaluate(MENU), [["pin_to_profile","Pin to your profile page"],["edit_post","Edit post"],["publish_now","Publish now"],["delete_post","Delete post"]])
        pg.screenshot(path=f"{SHOTS}/inapp-queue-menu.png")
        check("Edit post: enabled, no tooltip", fr.evaluate("(b => [b.disabled, b.title])(document.querySelector('#oi-queue-menu [at-attr=edit_post]'))"), [False, ""])
        fr.evaluate("document.body.click()")
        more.nth(1).click(); pg.wait_for_timeout(200)
        check("message row: OF's message menu", fr.evaluate(MENU), [["edit_message","Edit message"],["message_now","Send message right now"],["delete_message","Delete message"]])
        fr.evaluate("document.body.click()")
        gets=len([c for c in calls if c[1]=="/api/of/v2/schedules"])
        more.nth(0).click(); fr.locator("#oi-queue-menu [at-attr=publish_now]").click(); pg.wait_for_timeout(500)
        check("Post now, confirm dismissed: nothing sent", writes(), [])
        answer["accept"]=True
        more.nth(0).click(); fr.locator("#oi-queue-menu [at-attr=publish_now]").click(); pg.wait_for_timeout(1500)
        check("Post now, confirmed: exactly the schedule's publish, by account 1", writes(), [["PUT","/api/of/v2/schedules/901/publish","1"]])
        check("Post now: the queue is asked for again", len([c for c in calls if c[1]=="/api/of/v2/schedules"])>gets, True)
        answer["accept"]=False
        more.nth(0).click(); fr.locator("#oi-queue-menu [at-attr=delete_post]").click(); pg.wait_for_timeout(500)
        check("Delete post, confirm dismissed: nothing more sent", len(writes()), 1)
        answer["accept"]=True
        more.nth(1).click(); fr.locator("#oi-queue-menu [at-attr=delete_message]").click(); pg.wait_for_timeout(1000)
        check("Delete message, confirmed: exactly DELETE of the message id", writes()[1:], [["DELETE","/api/of/v2/messages/queue/22","1"]])
    # 6. Add to queue.
    def frame_of(page, ready="document.readyState==='complete'"):
        for _ in range(80):
            fs=[f for f in pg.frames if f.url.endswith(f"/of-mirror/pages/{page}.html")]
            try:
                if fs and fs[0].evaluate(ready): return fs[0]
            except Exception: pass
            pg.wait_for_timeout(250)
        failures.append(f"{page}: no frame"); return None
    MODAL="(m => m && [m.querySelector('.modal-title').textContent.trim(), [...m.querySelectorAll('[data-oi-tab]')].map(b => [b.textContent.trim(), b.classList.contains('m-current')]), [...m.querySelectorAll('.modal-body button[at-attr]')].map(b => b.textContent.trim())])(document.getElementById('newScheduleEventModal'))"
    pg.goto(f"{BASE}/of-manager/queue", wait_until="load", timeout=90000)
    fr=frame_of("queue/index", "!!document.querySelector('[at-attr=add_event_header][data-oi-wired]')")
    if fr:
        pg.wait_for_timeout(800)
        fr.locator("[at-attr=add_event_header]").click(); pg.wait_for_timeout(300)
        check("Add to queue: OF's modal", fr.evaluate(MODAL), ["Add to queue", [["Scheduled",True],["Save for Later",False]], ["Post","Mass message","Stream"]])
        check("Add to queue: the shown day at the zone's time ten minutes on", fr.evaluate("[...document.querySelectorAll('#newScheduleEventModal input')].map(i => i.value)"), ["Oct 12, 2026","12:10"])
        pg.screenshot(path=f"{SHOTS}/inapp-queue-add.png")
        fr.locator("#newScheduleEventModal .vdatetime:has(input[at-attr=date_input])").click(); pg.wait_for_timeout(300)
        check("Add to queue: the date opens OF's day popup, one day, from today on", fr.evaluate("(p => p && [p.querySelector('.vdatetime-popup__title').textContent.trim(), !!p.querySelector('.vdatetime-popup__tabs'), p.querySelector(\"[data-oi-month='prev']\").disabled])(document.querySelector('[data-oi-picker] .vdatetime-popup'))"), ["Oct 12, 2026", False, True])
        pg.screenshot(path=f"{SHOTS}/inapp-queue-datepicker.png")
        fr.locator("[data-oi-picker] [data-oi-day='2026-10-14']").click(); fr.locator("[data-oi-picker] [data-oi-picker-apply]").click(); pg.wait_for_timeout(200)
        check("Add to queue: Apply sets the day", fr.evaluate("document.querySelector('#newScheduleEventModal input[at-attr=date_input]').value"), "Oct 14, 2026")
        fr.locator("#newScheduleEventModal input[type=time]").fill("18:30")
        fr.locator("#newScheduleEventModal [at-attr=add_post]").click()
        pg.wait_for_url("**/of-manager/new-post", timeout=30000)
        np_=frame_of("new-post/index", "!!document.getElementById('oi-post-summary')")
        if np_: check("Add to queue > Post: New post with the moment", np_.evaluate("document.getElementById('oi-post-summary').textContent"), "Scheduled for Wed, Oct 14, 6:30 PM · Clear")
    pg.goto(f"{BASE}/of-manager/queue/saved-for-later-messages", wait_until="load", timeout=90000)
    fr=frame_of("queue/saved-for-later-messages", "!!document.querySelector('[data-oi-add]')")
    if fr:
        pg.wait_for_timeout(800)
        fr.locator("[data-oi-add]").first.click(); pg.wait_for_timeout(300)
        check("saved for later's +: the modal on Save for later", fr.evaluate(MODAL), ["Add to queue", [["Scheduled",False],["Save for Later",True]], ["Post","Mass message"]])
    # 7. Edit post and Edit message: the composer filled from the item; saving sends PUT to the same item.
    answer["accept"]=True
    pg.evaluate("sessionStorage.clear()")
    pg.goto(f"{BASE}/of-manager/queue/state-list-view", wait_until="load", timeout=90000)
    fr=frame_of("queue/state-list-view", "document.querySelectorAll('[at-attr=more_menu]').length===3")
    if fr:
        fr.locator("[at-attr=more_menu]").nth(0).click(); fr.locator("#oi-queue-menu [at-attr=edit_post]").click()
        pg.wait_for_url("**/of-manager/new-post", timeout=30000)
        np_=frame_of("new-post/index", "!!document.getElementById('oi-post-summary')")
        if np_:
            check("Edit post: New post filled from the post", [np_.evaluate("document.querySelector(\"[contenteditable][aria-label='Textbox field']\").textContent"), np_.evaluate("document.getElementById('oi-post-summary').textContent")],
                  ["Alpha post", "Editing a scheduled post · Scheduled for Tue, Oct 20, 10:00 AM · Clear · Discard"])
            n=len(calls)
            np_.locator("button[at-attr='submit_post']").click(); pg.wait_for_timeout(1500)
            check("Edit post: Post sends exactly PUT /queue/posts/11 (no new post)", [c for c in calls[n:] if c[0]!="GET"], [["PUT","/api/of/v2/queue/posts/11","1"]])
            check("Edit post: its body", bodies.get(("PUT","/api/of/v2/queue/posts/11")), {"text":"Alpha post","media_files":[],"price":0,"posted_at":"2026-10-20T10:00:00+02:00"})
    pg.goto(f"{BASE}/of-manager/queue/state-list-view", wait_until="load", timeout=90000)
    fr=frame_of("queue/state-list-view", "document.querySelectorAll('[at-attr=more_menu]').length===3")
    if fr:
        fr.locator("[at-attr=more_menu]").nth(1).click(); fr.locator("#oi-queue-menu [at-attr=edit_message]").click()
        pg.wait_for_url("**/of-manager/messages/send", timeout=30000)
        ms=frame_of("messages/send", "!!document.getElementById('oi-chat-summary')")
        if ms:
            check("Edit message: New message filled", ms.evaluate("document.getElementById('oi-chat-summary').textContent"), "Editing a scheduled message · 1 user picked · Scheduled for Oct 21, 6:30 pm · Clear · Discard")
            n=len(calls)
            ms.locator("button[at-attr='send_btn']").click(); pg.wait_for_timeout(1500)
            check("Edit message: Send sends exactly PUT /messages/queue/22", [c for c in calls[n:] if c[0]!="GET"], [["PUT","/api/of/v2/messages/queue/22","1"]])
            check("Edit message: its body", bodies.get(("PUT","/api/of/v2/messages/queue/22")), {"text":"Alpha message","user_lists":["fans"],"user_ids":[501],"scheduled_date":"2026-10-21T18:30:00+02:00"})
    answer["accept"]=False
    # 5. Month navigation on the calendar.
    sent=len([c for c in calls if c[0]!="GET"])
    pg.goto(f"{BASE}/of-manager/queue", wait_until="load", timeout=90000); pg.wait_for_timeout(1500)
    fr=None
    for _ in range(60):
        fs=[f for f in pg.frames if f.url.endswith("/of-mirror/pages/queue/index.html")]
        if fs and fs[0].evaluate(BARS)==OCT_BARS: fr=fs[0]; break
        pg.wait_for_timeout(250)
    if not fr: failures.append("queue: no frame with October's two days marked")
    else:
        def until(js, want):
            for _ in range(40):
                got=fr.evaluate(js)
                if got==want: break
                pg.wait_for_timeout(250)
            return got
        check("queue: nothing under the calendar (OF lists the month only in its list view)", fr.evaluate("document.querySelector('.v-calendar').nextElementSibling"), None)
        check("queue: back arrow greyed out on today's month", fr.evaluate("document.querySelector('[at-attr=prev_month]').disabled"), True)
        q0=len(queries)
        fr.locator("[at-attr=next_month]").click()
        check("next_month: November's day only", until(BARS, ["2026-11-03 post 1"]), ["2026-11-03 post 1"])
        check("next_month: the header and the right column's day", fr.evaluate(HEADER), ["November 2026","November 1, 2026"])
        check("next_month: /schedules asked for November", queries[q0:], [{"publish_date":"2026-11-01","publish_date_end":"2026-11-30"}])
        pg.screenshot(path=f"{SHOTS}/inapp-queue-november.png")
        fr.locator("[at-attr=prev_month]").click()
        check("prev_month: October's days back", until(BARS, OCT_BARS), OCT_BARS)
        check("prev_month: on today, the back arrows greyed out", [fr.evaluate(HEADER), fr.evaluate("['prev_month','prev_day_sidebar'].map(a => document.querySelector(`[at-attr=${a}]`).disabled)")], [["October 2026","October 12, 2026"],[True,True]])
        fr.locator(".b-month-day-cell__value[at-attr='date:2026-10-14']").click()
        check("Oct 14 clicked: the right column shows that day's message", [until(SIDE, ["Alpha message"]), fr.evaluate(HEADER)[1]], [["Alpha message"], "October 14, 2026"])
        tab=lambda t: fr.locator(f".g-page__subheader .b-tabs__nav__link:has-text('{t}')").first
        tab("Messages").click()
        check("Messages tab: only the message's day", until(BARS, OCT_BARS[1:]), OCT_BARS[1:])
        tab("Posts").click()
        check("Posts and Messages tabs: both days", until(BARS, OCT_BARS), OCT_BARS)
        check("queue: no URL change, nothing sent", [urlparse(pg.url).path, len([c for c in calls if c[0]!="GET"])-sent], ["/of-manager/queue", 0])
    print("queue console errors:", [e[:160] for e in errs][:8])
    check("queue: no console errors", errs, [])
    b.close()
if failures:
    print("FAIL:", *failures, sep="\n  "); sys.exit(1)
print("queue ok")
