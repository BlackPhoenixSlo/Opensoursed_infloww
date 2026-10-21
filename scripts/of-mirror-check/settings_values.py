"""Single-model scope: the OF settings mirror shows the model's settings values.

Mocks the login (as render.py) and the relay's settings sources with SYNTHETIC
values, sets scope `model:acc1` (as navigate.py), and checks the mapped controls
in the frame. Screenshot: /tmp/of-mirror-shots/inapp-settings-values.png. Exit 1 on a failed check.
"""
import json, os, sys
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
BASE=f"http://localhost:{os.environ.get('PORT','3091')}"
SHOTS="/tmp/of-mirror-shots"
os.makedirs(SHOTS, exist_ok=True)
user={"user_id":"u1","username":"tester","is_admin":False}
SOURCES={
    "/api/of/v2/users/me": {"username":"livemodel","name":"Live Model","hasWatermarkPhoto":True,"hasWatermarkVideo":False,
                            "watermarkText":"synthetic-mark","watermarkPosition":"top_left"},
    "/api/of/v2/users/me/settings": {"isAutoFollowBack":True,"unfollowAutoFollowBack":False,"recommenderReward":True,
                                     "sendAwardsTop1":True,"sendAwardsTop5":False,"replyOnSubscribe":True,"coStreamingRequestFrom":"nobody"},
    "/api/of/v2/users/settings/notifications/toast": [{"code":"g","items":[{"code":"new_tips","isEnabled":True},{"code":"new_comment","isEnabled":False}]}],
}
# page -> (control id or name, expected checked / value / text JS)
CHECKS={
    "fans": [("#setting_isAutoFollowBack",True),("#setting_unfollowAutoFollowBack",False),("#setting_recommenderReward",True),
             ("#setting_sendAwardsTop1",True),("#setting_sendAwardsTop5",False)],
    "messaging": [("#autoMessage",True)],
    "streaming": [("#allowSubscribers",False),("#allowFriends",False),("#allowNobody",True)],
    "notifications/toast": [("#toggle_new_tips",True),("#toggle_new_comment",False)],
    "security/watermarks": [("#hasWatermarkPhoto",True),("#hasWatermarkVideo",False),
                            ("text:.g-input__help","Current: synthetic-mark"),("text:.v-select__selection","Top left")],
}
failures=[]
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={"width":1440,"height":900})
    ctx.add_init_script("localStorage.setItem('chatterly:scope','model:acc1')")
    pg=ctx.new_page()
    seen=set()
    def mock(route):
        u=route.request.url; path=urlparse(u).path
        if path in SOURCES:
            seen.add(path); return route.fulfill(status=200, content_type="application/json", body=json.dumps(SOURCES[path]))
        if "/auth/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps(user))
        elif u.split("?")[0].endswith("/admin/accounts"): route.fulfill(status=200, content_type="application/json", body='{"accounts":[{"id":"acc1","nickname":"Model One","has_session":true},{"id":"1","nickname":"Model Two","has_session":true}],"active_account_id":null}')  # creators: none shows OfNotHaveModel
        elif "/chatter/me/accounts" in u: route.fulfill(status=200, content_type="application/json", body="[]")
        elif "/admin/employees" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"employees":[{"id":1,"display_name":"Tim","color":"#a78bfa","is_active":True,"chatter_id":None}]}))
        elif "/chatter/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"chatter":None,"owners":[]}))
        else: route.fulfill(status=200, content_type="application/json", body="[]")
    for pat in ["**/auth/**","**/chatter/**","**/admin/**","**/accounts**","**/api/**"]: pg.route(pat, mock)
    pg.route("**/events?**", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=""))  # no Relay: an empty stream, not a 500
    errs=[]; pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
    first=True
    for page, checks in CHECKS.items():
        pg.goto(f"{BASE}/of-manager/settings/{page}", wait_until="load", timeout=90000); pg.wait_for_timeout(3000)
        if first:
            card=pg.get_by_text("Tim", exact=True)
            if card.count(): card.first.click(); pg.wait_for_timeout(3000)
            first=False
        fr=[f for f in pg.frames if f.url.endswith(f"/of-mirror/pages/settings/{page}.html")]
        if not fr: failures.append(f"{page}: NO IFRAME (url {pg.url})"); continue
        for sel, want in checks:
            if sel.startswith("text:"):
                got=fr[0].evaluate("s => document.querySelector(s)?.textContent.trim() ?? null", sel[5:])
            else:
                got=fr[0].evaluate("s => document.querySelector(s)?.checked ?? null", sel)
            print(json.dumps({"page":page,"control":sel,"want":want,"got":got}))
            if got!=want: failures.append(f"{page}: {sel} is {got!r}, expected {want!r}")
        if page=="fans": pg.screenshot(path=f"{SHOTS}/inapp-settings-values.png")
    missing=set(SOURCES)-seen
    if missing: failures.append(f"sources never fetched: {sorted(missing)}")
    print("console errors:", [e[:160] for e in errs][:8])
    if errs: failures.append(f"{len(errs)} console error(s)")
if failures:
    print("FAIL:", *failures, sep="\n  "); sys.exit(1)
print("settings values ok")
