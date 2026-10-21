"""OF settings > Subscription: the modals that write through the Relay (app/lib/ofMirrorWrites.ts SUBMITS), the ones with
no Known body, and the Relay's rows (app/lib/ofMirrorSubscription.ts).

Mocks the login (as writes.py), the relay's POST /api/of/v2/campaigns and synthetic GETs (ROWS: /users/me, one tracking
link, one free trial link, and one promotion and one bundle in /users/me's promotions and subscriptionBundles, as OF reads them); every unmocked /api/** returns [] and any
request to a host other than localhost is aborted and fails the check (even one whose path a mock matches). Every
non-GET /api/** request is recorded as [method, path, JSON body, X-Account-Id]. Checks in the frame:
Single Creator (scope `model:1`), "Create new tracking link" (settings/subscription/tracking-links/modal-1):
1. "Create Link" is disabled until a name is typed, and enabled once "Synthetic link" is typed; the name's label then
   floats clear of it and the counter reads "14 / 100".
2. Clicking it sends exactly one POST /api/of/v2/campaigns {"name":"Synthetic link"} with X-Account-Id: 1 (no `code`),
   and the page lands on the Tracking links tab (/of-manager/settings/subscription/tracking-links).
3. Opening the modal again, typing "Synthetic link" and pressing Enter in the name field sends exactly one more such
   POST, and lands on the tab too (a native form submit never reloads the frame).
4. The offer dialogs (OFFERS; ofMirrorOffers, OF's own bodies): the promotion modal's "Start campaign"
   (settings/subscription/promotion-campaign/modal-1) and the free trial modal's "Create link" (trial-links/modal-1) are
   enabled, and a click sends exactly one POST of OF's default body (promotions: a 7-day free trial for new subscribers,
   offer limit 10, 7 days; trials: no name, 10, 7, 7) with X-Account-Id 1 and lands on its tab; the bundle modal's "Save"
   (.../modal-2) is disabled with OF's reason while users/me settings offer no bundle (unmocked here). The
   writes are answered by the mock, never sent anywhere.
5. The rows (Single Creator): the Tracking links tab shows the synthetic link (name, Clicks count) and no "No results :(";
   its Copy link shows OF's toast "Link copied"; its Delete asks in OF's ModalConfirm (its Delete clicked) and sends exactly one
   DELETE /api/of/v2/campaigns/7 with X-Account-Id 1, removes the row and stays on the tab. The Free trial links tab and
   the promotion page show their synthetic rows (the promotion's title, the bundle's "$20.35 USD total for 3 months").
All Creators (scope key removed before every load): the Settings pages stand in with the first listed creator
(ofMirrorProfile's STAND_IN_SRC), so typing "Synthetic link" and clicking "Create Link" sends one POST /campaigns
{name} with X-Account-Id acc1 and lands on the Tracking links tab.
No console errors in either pass. Prints one {"check","want","got"} line per check. Screenshots:
/tmp/of-mirror-shots/inapp-settings-writes-tracking-filled.png, -tracking-tab.png, -all-models-tracking.png,
-promotion.png, -bundle.png, -trial.png (and -all-models- each), -rows-tracking.png, -rows-trials.png, -rows-promotion.png,
-all-models-rows-tracking.png.
Exit 1 on a failed check.
"""
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
SELECT_MODEL="Select a model to save changes"
NOT_YET="Not available in Inflowwww yet"
# Page under settings/ -> (screenshot name, its button, its label, its write (None: disabled here), the tab it lands on).
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
    # OF lists the bundles and the settings promotions from /users/me (subscriptionBundles, promotions), not
    # /subscriptions/bundles or /promotions.
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
        # Page routes win over the context's: a foreign URL matching a mock pattern still fails the check.
        if foreign(u): return outside(route)
        if req.method!="GET" and path.startswith("/api/"):
            writes.append([req.method, path, req.post_data_json if req.post_data else None, req.headers.get("x-account-id")])
            if req.method=="POST" and path==CAMPAIGNS: return route.fulfill(status=200, content_type="application/json", body='{"id":1}')
        if req.method=="GET" and path in ROWS: return route.fulfill(status=200, content_type="application/json", body=json.dumps(ROWS[path]))
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
    first=[True]
    def open_page(page):
        """The settings page's frame, once loaded (the employee card picked on the first load)."""
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
    pg.wait_for_timeout(500)  # a stray second write would land here
    return urlparse(pg.url).path
ONE=[["POST",CAMPAIGNS,{"name":"Synthetic link"},"1"]]
def offers(pg, writes, open_page, single):
    """The offer dialogs (4), in the Single Creator (`single`) or the All Creators scope."""
    scope, shot = ("", "") if single else ("all creators ", "all-models-")
    for page, (name, sel, text, write, tab) in OFFERS.items():
        fr=open_page(page)
        if not fr: continue
        before=list(writes)
        state=fr.evaluate("([sel, text]) => [...document.querySelectorAll(sel)].filter(e => e.textContent.trim() === text).map(e => e.disabled)", [sel, text])
        pg.screenshot(path=f"{SHOTS}/inapp-settings-writes-{shot}{name}.png")
        if write is None:
            check(f"{scope}{name}: {text} is disabled while OF offers no bundle", state, [True])
            check(f"{scope}{name}: the dialog says why", fr.evaluate("document.querySelector('.modal.show p.g-input__help')?.textContent.trim() ?? null"),
                  "OnlyFans offers no more subscription bundles for this page" if single else SELECT_MODEL)
            continue
        check(f"{scope}{name}: {text} is enabled", state, [False])
        fr.locator(sel, has_text=text).click()
        if single:
            check(f"{scope}{name}: lands on its tab", wait_path(pg, tab), tab)
            check(f"{scope}{name}: exactly one POST of OF's default body", writes[len(before):], [write])
        else:
            pg.wait_for_timeout(800)
            check(f"{scope}{name}: sends nothing", writes, before)
            check(f"{scope}{name}: the select-a-model note", fr.evaluate(NOTE), SELECT_MODEL)
def rows(pg, writes, open_page):
    """The Relay's rows (5), Single Creator."""
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
    offers(pg, writes, open_page, True)
    rows(pg, writes, open_page)
    print("relay writes:", writes)
    print("console errors:", [e[:160] for e in errs][:8])
    if errs: failures.append(f"{len(errs)} console error(s)")

    # All Creators: the scope key cleared before every load.
    pg, writes, errs, open_page=session(b, "localStorage.removeItem('chatterly:scope')")
    fr=open_page(TRACKING)
    if fr:
        check("all creators: scope key absent", pg.evaluate("localStorage.getItem('chatterly:scope')"), None)
        before=len(writes)
        fr.locator(NAME).fill("Synthetic link")
        fr.locator(CREATE_LINK).click()
        check("all creators tracking link: lands on the Tracking links tab", wait_path(pg, TRACKING_TAB), TRACKING_TAB)
        check("all creators tracking link: one POST /campaigns for the stand-in creator", writes[before:], [["POST",CAMPAIGNS,{"name":"Synthetic link"},"acc1"]])
        pg.screenshot(path=f"{SHOTS}/inapp-settings-writes-all-models-tracking.png")
    print("all creators relay writes:", writes)
    print("all creators console errors:", [e[:160] for e in errs][:8])
    if errs: failures.append(f"all creators: {len(errs)} console error(s)")
if failures:
    print("FAIL:", *failures, sep="\n  "); sys.exit(1)
print("settings_writes ok")
