import json, os, sys
from playwright.sync_api import sync_playwright
BASE=f"http://localhost:{os.environ.get('PORT','3091')}"
SHOTS="/tmp/of-mirror-shots"
os.makedirs(SHOTS, exist_ok=True)
# A full path ("/of-manager/statistics", "/of-manager/messages/chat") or, as before, a settings page ("fans", "account/2fa").
def target(a):
    if a.startswith("/of-manager/"):
        section, _, sub = a[len("/of-manager/"):].strip("/").partition("/")
    else:
        section, sub = "settings", a.strip("/")
    # The section root shows its index page (SECTION_INDEX in scripts/of-mirror.mjs; Statistics redirects to Statements ›
    # Earnings, app/next.config.ts); the others' index.html.
    index = {"settings": "profile", "statistics": "statements/earnings"}.get(section, "index")
    return section, sub, f"/of-manager/{section}" + (f"/{sub}" if sub else ""), f"/of-mirror/pages/{section}/{sub or index}.html"
pages=sys.argv[1:] or ["fans"]
user={"user_id":"u1","username":"tester","is_admin":False}
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={"width":1440,"height":900}); pg=ctx.new_page()
    def mock(route):
        u=route.request.url
        if "/auth/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps(user))
        elif u.split("?")[0].endswith("/admin/accounts"): route.fulfill(status=200, content_type="application/json", body='{"accounts":[{"id":"acc1","nickname":"Model One","has_session":true},{"id":"1","nickname":"Model Two","has_session":true}],"active_account_id":null}')  # creators: none shows OfNotHaveModel
        elif "/chatter/me/accounts" in u: route.fulfill(status=200, content_type="application/json", body="[]")
        elif "/admin/employees" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"employees":[{"id":1,"display_name":"Tim","color":"#a78bfa","is_active":True,"chatter_id":None}]}))
        elif "/chatter/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"chatter":None,"owners":[]}))
        else: route.fulfill(status=200, content_type="application/json", body="[]")
    for pat in ["**/auth/**","**/chatter/**","**/admin/**","**/accounts**","**/api/**"]:
        pg.route(pat, mock)
    pg.route("**/events?**", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=""))  # no Relay: an empty stream, not a 500
    errs=[]; pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
    failures=[]
    for s in pages:
        section, sub, path, want = target(s)
        pg.goto(f"{BASE}{path}", wait_until="load", timeout=90000); pg.wait_for_timeout(3000)
        card=pg.get_by_text("Tim", exact=True)
        if card.count(): card.first.click(); pg.wait_for_timeout(3000)
        fr=[f for f in pg.frames if "of-mirror" in f.url]
        info={"page":s,"url":pg.url,"iframe":[f.url for f in fr]}
        if fr:
            f=fr[0]
            info["content_len"]=f.evaluate("document.querySelector('#content')?.innerText.length||0")
            info["links"]=f.evaluate("[...document.querySelectorAll('a[href^=\"/of-manager\"]')].length")
        pg.screenshot(path=f"{SHOTS}/inapp-{path.removeprefix('/of-manager/').replace('/','__')}.png")
        print(json.dumps(info))
        if not fr: failures.append(f"{s}: NO IFRAME (url {pg.url})")
        elif not fr[0].url.endswith(want): failures.append(f"{s}: iframe {fr[0].url}, expected {want}")
        elif not info["content_len"]: failures.append(f"{s}: empty page content")
    print("console errors:", [e[:160] for e in errs][:8])
    if errs: failures.append(f"{len(errs)} console error(s)")
if failures:
    print("FAIL:", *failures, sep="\n  "); sys.exit(1)
