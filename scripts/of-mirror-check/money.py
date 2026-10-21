"""Single-model scope: the OF mirror's Statements and Statistics pages show the model's money figures (app/lib/ofMirrorMoney.ts).

Mocks the login (as settings_values.py) and the relay's GET /api/of/v2/payouts/balances, /payouts/stats,
/payments/referrals/balance and /payouts/chargebacks/ratio with SYNTHETIC values, sets scope `model:acc1`, and checks in
the frame: the balance box (Statements) and sidebar (Statistics) amounts, payout frequency and its line (OF's minSumMessage); Earning
Statistics' all-time net and month rows; the referral earnings; the chargeback ratio. Every money request is a GET with
X-Account-Id. Screenshot: /tmp/of-mirror-shots/inapp-money.png. Exit 1 on a failed check.
"""
import datetime, json, os, sys, time
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
BASE=f"http://localhost:{os.environ.get('PORT','3091')}"
SHOTS="/tmp/of-mirror-shots"
os.makedirs(SHOTS, exist_ok=True)
user={"user_id":"u1","username":"tester","is_admin":False}
month=lambda y, m: str(int(time.mktime((y, m, 1, 0, 0, 0, 0, 0, -1))))
# OF's minSumMessage for weekly payouts (OF reads availableAmount, absent from its balances): the next payout, a week on's Monday.
_d=datetime.date.today()+datetime.timedelta(days=7); _d-=datetime.timedelta(days=_d.weekday())
WEEKLY_LINE=f"Once your balance is over $50 next payout will be scheduled on: {_d.strftime('%b')} {_d.day}, {_d.year}"
SOURCES={
    "/api/of/v2/payouts/balances": {"payoutAvailable":1234.5,"payoutPending":0,"minPayoutSumm":50,"withdrawalPeriod":"weekly",
                                    "withdrawalPeriodOptions":[{"code":"manual","name":"Manual payouts"},{"code":"weekly","name":"Weekly payouts"}]},
    "/api/of/v2/payouts/stats": {"list":{"total":{"all":{"total_gross":2500,"total_net":2000}},
                                         "months":{month(2026,10):{"total_net":800},month(2026,9):{"total_net":1200}}}},
    "/api/of/v2/payments/referrals/balance": {"referralEarnings":42.1},
    "/api/of/v2/payouts/chargebacks/ratio": {"chargebacksRatio":1.236},
}
TEXT="s => [...document.querySelectorAll(s)].filter(e => !e.closest(\"[style*='display:none']\")).map(e => e.textContent.trim())"
CHECKS={
    "statements/earnings": [(".b-statements__current-balance__value > span",["$1,234.50"]),(".b-statements__pending-balance__value > span",["$0.00"]),
                            (".balance-block .v-select__selection",["Weekly payouts"]),(".b-statements__min-payout-summ",[WEEKLY_LINE])],
    "statements/stats/earnings": [(".b-stats-row__month",["All time","October, 2026","September, 2026"]),
                                  (".b-stats-row__total-net",["$2,000.00","$800.00","$1,200.00"])],
    "statements/referrals": [(".g-box__header__inner__value > span",["$42.10"])],
    "statistics/statements/disputes": [(".m-statistics-alert .alert-text-wrapper > p",["Chargeback ratio 1.24%"]),
                                       (".b-statements-balances__sum",["$1,234.50","$0.00"]),(".balance-block .b-holder-options__title",["Weekly payouts"])],
    "statistics/statements/referrals/earnings": [(".b-referrals-state__count",["$42.10"])],
}
failures=[]
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={"width":1440,"height":900})
    ctx.add_init_script("localStorage.setItem('chatterly:scope','model:acc1')")
    pg=ctx.new_page()
    seen=set(); sent=[]
    def mock(route):
        r=route.request; u=r.url; path=urlparse(u).path
        if urlparse(u).hostname not in ("localhost","127.0.0.1"): failures.append(f"off-host request {u}"); return route.abort()
        if path in SOURCES:
            seen.add(path); sent.append((r.method, path, r.headers.get("x-account-id")))
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(SOURCES[path]))
        if "/auth/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps(user))
        elif u.split("?")[0].endswith("/admin/accounts"): route.fulfill(status=200, content_type="application/json", body='{"accounts":[{"id":"acc1","nickname":"Model One","has_session":true},{"id":"1","nickname":"Model Two","has_session":true}],"active_account_id":null}')  # creators: none shows OfNotHaveModel
        elif "/chatter/me/accounts" in u: route.fulfill(status=200, content_type="application/json", body="[]")
        elif "/admin/employees" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"employees":[{"id":1,"display_name":"Tim","color":"#a78bfa","is_active":True,"chatter_id":None}]}))
        elif "/chatter/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"chatter":None,"owners":[]}))
        else:
            if r.method!="GET" and "/api/of/" in u: sent.append((r.method, path, r.headers.get("x-account-id")))
            route.fulfill(status=200, content_type="application/json", body="[]")
    for pat in ["**/auth/**","**/chatter/**","**/admin/**","**/accounts**","**/api/**"]: pg.route(pat, mock)
    pg.route("**/events?**", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=""))  # no Relay: an empty stream, not a 500
    errs=[]; pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
    first=True
    for page, checks in CHECKS.items():
        pg.goto(f"{BASE}/of-manager/{page}", wait_until="load", timeout=90000); pg.wait_for_timeout(3000)
        if first:
            card=pg.get_by_text("Tim", exact=True)
            if card.count(): card.first.click(); pg.wait_for_timeout(3000)
            first=False
        fr=[f for f in pg.frames if f.url.endswith(f"/of-mirror/pages/{page}.html")]
        if not fr: failures.append(f"{page}: NO IFRAME (url {pg.url})"); continue
        for sel, want in checks:
            got=fr[0].evaluate(TEXT, sel)
            print(json.dumps({"page":page,"sel":sel,"want":want,"got":got}))
            if got!=want: failures.append(f"{page}: {sel} is {got!r}, expected {want!r}")
        if page=="statements/stats/earnings": pg.screenshot(path=f"{SHOTS}/inapp-money.png")
    missing=set(SOURCES)-seen
    if missing: failures.append(f"sources never fetched: {sorted(missing)}")
    bad=[s for s in sent if s[0]!="GET" or not s[2]]
    if bad: failures.append(f"non-GET or account-less money requests: {bad}")
    print("console errors:", [e[:160] for e in errs][:8])
    if errs: failures.append(f"{len(errs)} console error(s)")
if failures:
    print("FAIL:", *failures, sep="\n  "); sys.exit(1)
print("money ok")
