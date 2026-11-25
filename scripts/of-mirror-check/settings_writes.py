import json, os, sys
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
BASE=f"http://localhost:{os.environ.get('PORT','3091')}"
M="/of-manager"
SHOTS="/tmp/of-mirror-shots"
os.makedirs(SHOTS, exist_ok=True)
user={"user_id":"u1","username":"tester","is_admin":False}
CAMPAIGNS="/api/of/v2/campaigns"
TRACKING="subscription/tracking-links/modal-1"
TRACKING_TAB=f"{M}/settings/subscription/tracking-links"
CREATE_LINK=".modal-footer button[type='submit']"
NAME="input[name='name']"
NOT_YET="Not available in Inflowwww yet"
OFFERS={"subscription/promotion-campaign/modal-1":("promotion",".modal-footer button[type='submit']","Start campaign",
            ["POST","/api/of/v2/promotions",{"discount":100,"subscribe_counts":10,"subscribe_days":7,"finish_days":7,"message":"","type":["all"]},"1"],
            f"{M}/settings/subscription/promotion-campaign"),
        "subscription/promotion-campaign/modal-2":("bundle",".modal-footer button","Save",None,None),
        "subscription/trial-links/modal-1":("trial",".modal-footer button[type='submit']","Create link",
            ["POST","/api/of/v2/trials",{"name":"","subscribe_counts":10,"expire_days":7,"subscribe_days":7},"1"],
            f"{M}/settings/subscription/trial-links")}
NOTE="document.getElementById('oi-note')?.textContent ?? null"
TOAST="document.querySelector('#oi-toast .toast__text')?.textContent ?? null"
ROWS={
    "/api/of/v2/users/me": {"id":1,"username":"alphaone","name":"Alpha One","subscribePrice":10,"canCreatePromotion":True,
                            "subscriptionBundles":[{"id":10,"price":20.35,"duration":3,"discount":30}],
                            "promotions":[{"id":9,"price":0,"type":"new","subscribeDays":30,"subscribeCounts":0,"claimsCount":4,"isFinished":False,"canClaim":True,"message":"<p>Synthetic welcome</p>","createdAt":"2026-03-02T12:00:00+00:00","finishedAt":None}]},
    "/api/of/v2/campaigns": [{"id":7,"campaignCode":3,"campaignName":"Synthetic link","countSubscribers":2,"countTransitions":9,"createdAt":"2026-04-16T00:00:00+00:00","isDeleted":False}],
    "/api/of/v2/trials": [{"id":8,"trialLinkName":"Synthetic trial","url":"https://onlyfans.com/action/trial/synthetic","subscribeDays":7,"subscribeCounts":10,"claimCounts":3,"clicksCounts":12,"createdAt":"2026-06-11T00:00:00+00:00","isFinished":False}],
}
ROW_TEXT="[...document.querySelectorAll('[data-oi-row]')].map(r => r.textContent.replace(/\\s+/g, ' ').trim())"
NO_RESULTS="[...document.querySelectorAll('.infinite-loading-container > .infinite-status-prompt')][1]?.checkVisibility() ?? null"
failures=[]
def check(label, got, want):
    print(json.dumps({"check":label,"want":want,"got":got}))
    if got!=want: failures.append(f"{label}: got {got!r}, expected {want!r}")
def session(b, scope_js):
    """A fresh context and page with scope_js run before every load; returns (page, writes as [method, path, body,
    X-Account-Id], console errors)."""
    ctx=b.new_context(viewport={"width":1440,"height":900}, permissions=["clipboard-read","clipboard-write"])
    ctx.add_init_script(scope_js)
    foreign=lambda url: urlparse(url).hostname not in ("localhost","127.0.0.1")
    def outside(route):
        failures.append(f"request to a non-localhost host: {route.request.url[:120]}")
        route.abort()
    ctx.route(foreign, outside)
    pg=ctx.new_page()
    writes=[]
    def mock(route):
        req=route.request; u=req.url; path=urlparse(u).path
        if foreign(u): return outside(route)
        if req.method!="GET" and path.startswith("/api/"):
            writes.append([req.method, path, req.post_data_json if req.post_data else None, req.headers.get("x-account-id")])
            if req.method=="POST" and path==CAMPAIGNS: return route.fulfill(status=200, content_type="application/json", body='{"id":1}')
        if req.method=="GET" and path in ROWS: return route.fulfill(status=200, content_type="application/json", body=json.dumps(ROWS[path]))
        if "/auth/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps(user))
        elif u.split("?")[0].endswith("/admin/accounts"): route.fulfill(status=200, content_type="application/json", body='{"accounts":[{"id":"acc1","nickname":"Model One","has_session":true},{"id":"1","nickname":"Model Two","has_session":true}],"active_account_id":null}')
        elif "/chatter/me/accounts" in u: route.fulfill(status=200, content_type="application/json", body="[]")
        elif "/admin/employees" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"employees":[{"id":1,"display_name":"Tim","color":"#a78bfa","is_active":True,"chatter_id":None}]}))
        elif "/chatter/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"chatter":None,"owners":[]}))
        else: route.fulfill(status=200, content_type="application/json", body="[]")
    for pat in ["**/auth/**","**/chatter/**","**/admin/**","**/accounts**","**/api/**"]: pg.route(pat, mock)
    pg.route("**/events?**", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=""))
    errs=[]; pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
    pg.on("pageerror", lambda e: errs.append(f"uncaught: {e}"))
    first=[True]
    def open_page(page):
        pg.goto(f"{BASE}{M}/settings/{page}", wait_until="load", timeout=90000); pg.wait_for_timeout(2000)
        if first[0]:
            card=pg.get_by_text("Tim", exact=True)
            if card.count(): card.first.click(); pg.wait_for_timeout(2000)
            first[0]=False
        for _ in range(60):
            fr=[f for f in pg.frames if f.url.endswith(f"/of-mirror/pages/settings/{page}.html")]
            if fr and fr[0].evaluate("document.readyState")=="complete":
                pg.wait_for_timeout(500)
                return fr[0]
            pg.wait_for_timeout(250)
        failures.append(f"{page}: NO IFRAME (url {pg.url})"); return None
    return pg, writes, errs, open_page
def wait_path(pg, path):
    for _ in range(40):
        if urlparse(pg.url).path==path: break
        pg.wait_for_timeout(250)
    pg.wait_for_timeout(500)
    return urlparse(pg.url).path
ONE=[["POST",CAMPAIGNS,{"name":"Synthetic link"},"1"]]
def offers(pg, writes, open_page):
    for page, (name, sel, text, write, tab) in OFFERS.items():
        fr=open_page(page)
        if not fr: continue
        before=list(writes)
        state=fr.evaluate("([sel, text]) => [...document.querySelectorAll(sel)].filter(e => e.textContent.trim() === text).map(e => e.disabled)", [sel, text])
        pg.screenshot(path=f"{SHOTS}/inapp-settings-writes-{name}.png")
        if write is None:
            check(f"{name}: {text} is disabled while OF offers no bundle", state, [True])
            check(f"{name}: the dialog says why", fr.evaluate("document.querySelector('.modal.show p.g-input__help')?.textContent.trim() ?? null"),
                  "OnlyFans offers no more subscription bundles for this page")
            continue
        check(f"{name}: {text} is enabled", state, [False])
        fr.locator(sel, has_text=text).click()
        check(f"{name}: lands on its tab", wait_path(pg, tab), tab)
        check(f"{name}: exactly one POST of OF's default body", writes[len(before):], [write])
def rows(pg, writes, open_page):
    fr=open_page("subscription/tracking-links")
    if fr:
        pg.wait_for_timeout(1000)
        check("rows tracking: the synthetic link is drawn", fr.evaluate(ROW_TEXT),
              ["Synthetic link Share link's statistics with another user Tracking link created Apr 16, 2026 Subscribers count 2 Clicks count 9 Delete Copy link"])
        check("rows tracking: no No results", fr.evaluate(NO_RESULTS), False)
        pg.screenshot(path=f"{SHOTS}/inapp-settings-writes-rows-tracking.png")
        fr.locator("[data-oi-row] button", has_text="Copy link").click(); pg.wait_for_timeout(500)
        check("rows tracking: Copy link shows OF's toast", fr.evaluate(TOAST), "Link copied")
        before=len(writes)
        fr.locator("[data-oi-row] button", has_text="Delete").click(); pg.wait_for_timeout(500)
        asked=fr.evaluate("[document.querySelector('#ModalConfirm .modal-title')?.textContent ?? null, document.querySelector('#ModalConfirm .dialog_message')?.textContent ?? null]")
        check("rows tracking: Delete asks first, in OF's ModalConfirm", asked, ["Delete tracking link", "Are you sure you want to delete this tracking link?"])
        check("rows tracking: nothing sent before the answer", writes[before:], [])
        fr.locator("#ModalConfirm .modal-footer button", has_text="Delete").click(); pg.wait_for_timeout(1000)
        check("rows tracking: exactly one DELETE /campaigns/7 with X-Account-Id 1", writes[before:], [["DELETE",f"{CAMPAIGNS}/7",None,"1"]])
        check("rows tracking: still on the tab", urlparse(pg.url).path, TRACKING_TAB)
    fr=open_page("subscription/trial-links")
    if fr:
        pg.wait_for_timeout(1000)
        check("rows trials: the synthetic link is drawn", fr.evaluate(ROW_TEXT),
              ["Synthetic trial (7 days free trial) Share link's statistics with another user Free trial link created Jun 11, 2026 Offer limit 10 Claims count 3 Clicks count 12 Delete Copy link"])
        pg.screenshot(path=f"{SHOTS}/inapp-settings-writes-rows-trials.png")
    fr=open_page("subscription/promotion-campaign")
    if fr:
        pg.wait_for_timeout(1000)
        got=fr.evaluate(ROW_TEXT)
        check("rows promotion: the promotion and the bundle are drawn", [got[0].startswith("Limited offer - Free trial for 30 days! For new subscribers") if got else None, got[1:]],
              [True, ["$20.35 USD total for 3 months -30%"]])
        pg.screenshot(path=f"{SHOTS}/inapp-settings-writes-rows-promotion.png")
with sync_playwright() as p:
    b=p.chromium.launch()
    pg, writes, errs, open_page=session(b, "localStorage.setItem('chatterly:scope','model:1')")
    fr=open_page(TRACKING)
    if fr:
        button=fr.locator(CREATE_LINK)
        check("tracking link: Create Link disabled before a name", button.is_disabled(), True)
        fr.locator(NAME).fill("Synthetic link")
        check("tracking link: Create Link enabled with a name", button.is_enabled(), True)
        check("tracking link: typing gives no note", fr.evaluate(NOTE), None)
        check("tracking link: the label floats clear of the name and the counter counts", fr.evaluate(f"""[document.querySelector("{NAME}").closest('.v-input').classList.contains('v-input--is-label-active'),
          document.querySelector('.v-counter').textContent.trim()]"""), [True, "14 / 100"])
        pg.screenshot(path=f"{SHOTS}/inapp-settings-writes-tracking-filled.png")
        before=len(writes)
        button.click()
        check("tracking link: lands on the Tracking links tab", wait_path(pg, TRACKING_TAB), TRACKING_TAB)
        check("tracking link: exactly one POST /campaigns {name} with X-Account-Id 1", writes[before:], ONE)
        pg.wait_for_timeout(1000)
        pg.screenshot(path=f"{SHOTS}/inapp-settings-writes-tracking-tab.png")
    fr=open_page(TRACKING)
    if fr:
        before=len(writes)
        fr.locator(NAME).fill("Synthetic link")
        fr.locator(NAME).press("Enter")
        check("tracking link Enter: lands on the Tracking links tab", wait_path(pg, TRACKING_TAB), TRACKING_TAB)
        check("tracking link Enter: exactly one POST /campaigns {name} with X-Account-Id 1", writes[before:], ONE)
    offers(pg, writes, open_page)
    rows(pg, writes, open_page)
    print("relay writes:", writes)
    print("console errors:", [e[:160] for e in errs][:8])
    if errs: failures.append(f"{len(errs)} console error(s)")

if failures:
    print("FAIL:", *failures, sep="\n  "); sys.exit(1)
print("settings_writes ok")
