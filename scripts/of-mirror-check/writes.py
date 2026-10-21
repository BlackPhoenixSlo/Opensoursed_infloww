"""Single-model scope: the writable OF settings mirror controls send their relay PATCH; others send nothing.
All-models scope (no single model selected): nothing is sent; writable controls say "Select a model".

Mocks the login and relay as settings_values.py (SYNTHETIC values), records the
bodies of PATCH /api/of/v2/users/me and /users/me/reply-on-subscribe, and checks:
typing a display name + SAVE sends {name}, stays on the page with OF's settings toast ("Changes were saved",
visible, no note) and the page's name (.g-user-name) then shows it (the
mocked /users/me returns what was saved), the filled Location field's label sits clear of its value,
the welcome switch sends {enabled: true} with the toast, the fans auto-follow toggle sends PATCH /users/me/settings/security
{isAutoFollowBack: true} with the toast, a toast notification toggle sends PATCH /users/settings/notifications, the subscription
price shows the real price and its Save (after the confirm) sends PATCH /users/me {subscribePrice: 12.5} with the toast,
staying on the page, the web push permission switch (the browser's, no Relay write) is disabled with the tooltip "Not
available in Inflowwww yet", and the stream schedule form (streaming/dashboard/create): SCHEDULE with the form
empty sends nothing and shows the validation note; with tomorrow picked in the Date field's day popup (shown as OF's
"Oct 13, 2026"), 6:30 pm in the Time field's time input and a description it sends exactly one POST /api/of/v2/streams {description, scheduledDate (local ISO with
offset), isShowTips: true} and lands on /of-manager/queue.
Then, with the scope key cleared before every load (all models, two creators listed): the Settings pages stand in
with the first creator (ofMirrorProfile's STAND_IN_SRC), so typing a name + SAVE sends its PATCH and the welcome
switch its write; the schedule form (no stand-in) sends nothing on SCHEDULE and shows "Select a model to save changes".
Screenshots: /tmp/of-mirror-shots/inapp-writes.png (profile, its toast), inapp-writes-fans.png, inapp-writes-price.png, inapp-writes-webpush.png,
inapp-writes-schedule-invalid.png, inapp-writes-schedule-filled.png, inapp-writes-schedule-queue.png,
inapp-writes-all-models-schedule.png. Exit 1 on a failed check.
"""
import json, os, sys
from datetime import date, datetime, timedelta
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
BASE=f"http://localhost:{os.environ.get('PORT','3091')}"
SHOTS="/tmp/of-mirror-shots"
os.makedirs(SHOTS, exist_ok=True)
user={"user_id":"u1","username":"tester","is_admin":False}
SOURCES={
    "/api/of/v2/users/me": {"username":"livemodel","name":"Live Model","location":"Synthetic City","subscribePrice":9.99},
    "/api/of/v2/users/me/settings": {"isAutoFollowBack":False,"replyOnSubscribe":False},
}
WRITES={"/api/of/v2/users/me","/api/of/v2/users/me/reply-on-subscribe","/api/of/v2/streams",
        "/api/of/v2/users/me/settings/security","/api/of/v2/users/settings/notifications"}
failures=[]
def check(label, got, want):
    print(json.dumps({"check":label,"want":want,"got":got}))
    if got!=want: failures.append(f"{label}: got {got!r}, expected {want!r}")
SELECT_MODEL="Select a model to save changes"
def session(b, scope_js):
    """A fresh context and page with scope_js run before every load; returns (page, sent writes, console errors, open_page)."""
    ctx=b.new_context(viewport={"width":1440,"height":900})
    ctx.add_init_script(scope_js)
    pg=ctx.new_page()
    sent=[]
    def mock(route):
        req=route.request; u=req.url; path=urlparse(u).path
        if req.method!="GET" and path.startswith("/api/"):
            sent.append((req.method, path, req.post_data_json if req.post_data else None))
            if req.method=="PATCH" and path=="/api/of/v2/users/me": SOURCES[path]={**SOURCES[path], **sent[-1][2]}
            if req.method=="PATCH" and path=="/api/of/v2/users/me/settings/security":
                SOURCES["/api/of/v2/users/me/settings"]={**SOURCES["/api/of/v2/users/me/settings"], **sent[-1][2]}
            if path=="/api/of/v2/streams": return route.fulfill(status=200, content_type="application/json", body='{"id":123}')
            if path in WRITES: return route.fulfill(status=200, content_type="application/json", body='{"success":true}')
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
    errs=[]; pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
    first=[True]
    def open_page(page, section="settings"):
        pg.goto(f"{BASE}/of-manager/{section}/{page}", wait_until="load", timeout=90000); pg.wait_for_timeout(3000)
        if first[0]:
            card=pg.get_by_text("Tim", exact=True)
            if card.count(): card.first.click(); pg.wait_for_timeout(3000)
            first[0]=False
        fr=[f for f in pg.frames if f.url.endswith(f"/of-mirror/pages/{section}/{page}.html")]
        if not fr: failures.append(f"{page}: NO IFRAME (url {pg.url})")
        return fr[0] if fr else None
    return pg, sent, errs, open_page
note="document.getElementById('oi-note')?.textContent ?? null"
toast="document.querySelector('#oi-toast .toast__text')?.textContent ?? null"
SAVED_TOAST="Changes were saved"
SUBMIT=".g-page__header > button.g-btn"
TOMORROW=date.today()+timedelta(days=1)
def fill_stream(fr):
    """Tomorrow picked in OF's day popup (the Date field's), 6:30 pm in the Time field's time input and a description;
    returns the expected POST body."""
    fr.locator(".vdatetime:has(input[name='date'])").click()
    fr.locator(".vdatetime-popup").wait_for(state="visible")
    if TOMORROW.month!=date.today().month: fr.locator("[data-oi-month='next']").click()
    fr.locator(f"[data-oi-day='{TOMORROW.isoformat()}'] .v-calendar-weekly__day-label span").click()
    fr.locator("[data-oi-picker-apply]").click()
    check("schedule form: the day popup fills the date as OF shows it", fr.evaluate("document.querySelector(\"input[name='date']\").value"), f"{TOMORROW.strftime('%b')} {TOMORROW.day}, {TOMORROW.year}")
    check("schedule form: the time is a time input", fr.evaluate("document.querySelector(\"input[name='time']\").type"), "time")
    fr.locator("input[name='time']").fill("18:30")
    fr.locator(".create-scheduled__description [contenteditable]").fill("Synthetic stream")
    at=datetime(TOMORROW.year, TOMORROW.month, TOMORROW.day, 18, 30).astimezone()
    return {"description":"Synthetic stream","scheduledDate":at.isoformat(),"isShowTips":True}
with sync_playwright() as p:
    b=p.chromium.launch()
    pg, sent, errs, open_page=session(b, "localStorage.setItem('chatterly:scope','model:acc1')")

    fr=open_page("profile")
    if fr:
        check("profile: Location label raised over its value", fr.evaluate("document.getElementById('input-location').closest('.v-input').classList.contains('v-input--is-label-active')"), True)
        save=fr.locator(".g-btn__wrapper button[type='submit']")
        check("profile: Save disabled before an edit", save.is_disabled(), True)
        fr.locator("#input-name").fill("Synthetic Name")
        check("profile: Save enabled after an edit", save.is_enabled(), True)
        save.click(); pg.wait_for_timeout(1000)
        check("profile: PATCH /users/me body", [s[2] for s in sent if s[:2]==("PATCH","/api/of/v2/users/me")], [{"name":"Synthetic Name"}])
        check("profile: Save disabled after saving", save.is_disabled(), True)
        check("profile: OF's settings toast, no note", [fr.evaluate(toast), fr.evaluate(note)], [SAVED_TOAST, None])
        check("profile: toast visible", fr.locator("#oi-toast").is_visible(), True)
        check("profile: still on the page", urlparse(pg.url).path, "/of-manager/settings/profile")
        pg.wait_for_timeout(1500)
        check("profile: the page's name after saving", fr.evaluate("document.querySelector('.g-user-name').textContent.trim()"), "Synthetic Name")
        pg.screenshot(path=f"{SHOTS}/inapp-writes.png")

    fr=open_page("messaging")
    if fr:
        fr.locator("label[for='autoMessage']").click(); pg.wait_for_timeout(1000)
        check("messaging: PATCH reply-on-subscribe body", [s[2] for s in sent if s[1]=="/api/of/v2/users/me/reply-on-subscribe"], [{"enabled":True}])
        check("messaging: OF's settings toast", fr.evaluate(toast), SAVED_TOAST)

    fr=open_page("fans")
    if fr:
        before=len(sent)
        fr.locator("label[for='setting_isAutoFollowBack']").click(); pg.wait_for_timeout(1000)
        check("fans: a security-section toggle PATCHes settings/security", [list(x) for x in sent[before:]],
              [["PATCH","/api/of/v2/users/me/settings/security",{"isAutoFollowBack":True}]])
        check("fans: OF's settings toast, no note", [fr.evaluate(toast), fr.evaluate(note)], [SAVED_TOAST, None])
        check("fans: the toggle stays on", fr.evaluate("document.getElementById('setting_isAutoFollowBack').checked"), True)
        pg.screenshot(path=f"{SHOTS}/inapp-writes-fans.png")

    fr=open_page("notifications/toast")
    if fr:
        before=len(sent)
        fr.locator("label[for='toggle_new_tips']").click(); pg.wait_for_timeout(1000)
        check("toast: a notification toggle PATCHes notifications", [list(x) for x in sent[before:]],
              [["PATCH","/api/of/v2/users/settings/notifications",{"notifications":{"toast":[{"code":"new_tips","value":True}]}}]])

    fr=open_page("subscription")
    if fr:
        before=len(sent)
        check("subscription: the real price is shown", fr.evaluate("document.getElementById('priceInput_23').value"), "9.99")
        asked=[]
        pg.once("dialog", lambda d: (asked.append(d.message), d.accept()))
        fr.locator("#priceInput_23").fill("12.50")
        fr.locator("form[data-vv-scope='action-info-form'] button[type='submit']").click(); pg.wait_for_timeout(1000)
        check("subscription: the price Save asks first", asked, ["Change the subscription price to $12.50 per month?"])
        check("subscription: the price Save PATCHes subscribePrice", [list(x) for x in sent[before:]],
              [["PATCH","/api/of/v2/users/me",{"subscribePrice":12.5}]])
        check("subscription: OF's settings toast, on the page", [fr.evaluate(toast), urlparse(pg.url).path], [SAVED_TOAST, "/of-manager/settings/subscription"])
        pg.screenshot(path=f"{SHOTS}/inapp-writes-price.png")

    fr=open_page("notifications/webpush")
    if fr:
        check("webpush: the browser's permission switch is disabled with the tooltip",
              fr.evaluate("(e => [e.disabled, e.title])(document.getElementById('push-notifications'))"), [True, "Not available in Inflowwww yet"])
        pg.screenshot(path=f"{SHOTS}/inapp-writes-webpush.png")

    fr=open_page("dashboard/create", "streaming")
    if fr:
        before=len(sent)
        fr.locator(SUBMIT).click(); pg.wait_for_timeout(1000)
        check("schedule form: an empty SCHEDULE sends nothing", sent[before:], [])
        check("schedule form: validation note visible", fr.locator("#oi-note").is_visible(), True)
        check("schedule form: validation note", fr.evaluate(note), "Enter a date and a time")
        check("schedule form: still on the form", pg.url.endswith("/of-manager/streaming/dashboard/create"), True)
        pg.screenshot(path=f"{SHOTS}/inapp-writes-schedule-invalid.png")
        want=fill_stream(fr)
        check("schedule form: typing clears the validation note (and adds no read-only note)", fr.evaluate(note), None)
        check("schedule form: the description's label moves up and its counter counts", fr.evaluate("""[document.querySelector('.create-scheduled__description [contenteditable]').getAttribute('data-is-empty'),
          document.querySelector('.create-scheduled__description .count-block').textContent.trim()]"""), ["false","16/500"])
        pg.wait_for_timeout(600)  # the label's own transition
        pg.screenshot(path=f"{SHOTS}/inapp-writes-schedule-filled.png")
        fr.locator(SUBMIT).click()
        for _ in range(40):
            if pg.url.endswith("/of-manager/queue"): break
            pg.wait_for_timeout(250)
        check("schedule form: exactly one POST /streams with the form", [s for s in sent[before:]], [("POST","/api/of/v2/streams",want)])
        check("schedule form: lands on the queue", urlparse(pg.url).path, "/of-manager/queue")
        pg.wait_for_timeout(1500)
        pg.screenshot(path=f"{SHOTS}/inapp-writes-schedule-queue.png")
    print("relay writes:", sent)
    print("console errors:", [e[:160] for e in errs][:8])
    if errs: failures.append(f"{len(errs)} console error(s)")

    # All models: the scope key cleared before every load.
    pg, sent, errs, open_page=session(b, "localStorage.removeItem('chatterly:scope')")
    fr=open_page("profile")
    if fr:
        check("all models: scope key absent", pg.evaluate("localStorage.getItem('chatterly:scope')"), None)
        save=fr.locator(".g-btn__wrapper button[type='submit']")
        fr.locator("#input-name").fill("Synthetic Name")
        check("all models profile: Save enabled after an edit", save.is_enabled(), True)
        save.click(); pg.wait_for_timeout(1000)
        check("all models profile: stands in with the first creator, PATCH /users/me sent", [s for s in sent if s[:2]==("PATCH","/api/of/v2/users/me")], [("PATCH","/api/of/v2/users/me",{"name":"Synthetic Name"})])
    fr=open_page("messaging")
    if fr:
        before=fr.evaluate("document.getElementById('autoMessage').checked")
        fr.locator("label[for='autoMessage']").click(); pg.wait_for_timeout(1000)
        check("all models messaging: stands in, the switch's write sent", [s[:2] for s in sent if s[1].endswith("/reply-on-subscribe")], [("PATCH","/api/of/v2/users/me/reply-on-subscribe")])
        check("all models messaging: the switch stays flipped", fr.evaluate("document.getElementById('autoMessage').checked"), not before)
    fr=open_page("dashboard/create", "streaming")
    if fr:
        fill_stream(fr)
        n=len(sent)
        fr.locator(SUBMIT).click(); pg.wait_for_timeout(1000)
        check("all models schedule form: no write", sent[n:], [])
        check("all models schedule form: note visible", fr.locator("#oi-note").is_visible(), True)
        check("all models schedule form: note", fr.evaluate(note), SELECT_MODEL)
        check("all models schedule form: still on the form", pg.url.endswith("/of-manager/streaming/dashboard/create"), True)
        pg.screenshot(path=f"{SHOTS}/inapp-writes-all-models-schedule.png")
    print("all models relay writes:", sent)
    print("all models console errors:", [e[:160] for e in errs][:8])
    if errs: failures.append(f"all models: {len(errs)} console error(s)")
if failures:
    print("FAIL:", *failures, sep="\n  "); sys.exit(1)
print("writes ok")
