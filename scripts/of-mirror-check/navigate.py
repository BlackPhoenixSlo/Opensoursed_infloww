import json, os, sys
from urllib.parse import unquote
from playwright.sync_api import sync_playwright
BASE=f"http://localhost:{os.environ.get('PORT','3091')}"
SHOTS="/tmp/of-mirror-shots"
os.makedirs(SHOTS, exist_ok=True)
R="/of-manager/settings"
user={"user_id":"u1","username":"tester","is_admin":False}
failures=[]
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_context(viewport={"width":1440,"height":900}).new_page()
    def mock(route):
        u=route.request.url
        if "/auth/me" in u: body=json.dumps(user)
        elif "/admin/employees" in u: body=json.dumps({"employees":[{"id":1,"display_name":"Tim","color":"#a78bfa","is_active":True,"chatter_id":None}]})
        elif u.split("?")[0].endswith("/admin/accounts"): body='{"accounts":[{"id":"acc1","nickname":"Model One","has_session":true},{"id":"1","nickname":"Model Two","has_session":true}],"active_account_id":null}'  # creators: none shows OfNotHaveModel
        elif "/chatter/me/accounts" in u: body="[]"
        elif "/chatter/me" in u: body="null"
        # All models' Settings stand in with the first creator (ofMirrorProfile): a performer OF lets start a promotion.
        elif u.split("?")[0].endswith("/api/of/v2/users/me"): body=json.dumps({"id":1,"username":"alphaone","name":"Alpha One","isPerformer":True,"subscribePrice":10,"canEarn":True,"canCreatePromotion":True,"canCreateTrial":True})
        else: body="[]"
        route.fulfill(status=200, content_type="application/json", body=body)
    for pat in ["**/auth/**","**/chatter/**","**/admin/**","**/accounts**","**/api/**"]: pg.route(pat, mock)
    pg.route("**/events?**", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=""))  # no Relay: an empty stream, not a 500
    pg.goto(f"{BASE}{R}", wait_until="load", timeout=90000); pg.wait_for_timeout(3000)
    c=pg.get_by_text("Tim", exact=True)
    if c.count(): c.first.click(); pg.wait_for_timeout(2500)
    pg.evaluate("window.__marker=1")
    def frame(): return [f for f in pg.frames if "of-mirror" in f.url][0]
    def fail(msg):
        failures.append(msg); print("FAIL:", msg)
    def step(label, fn, path, page):
        """Run fn, then expect the app URL path `path` and the iframe page `page` (under pages/, no full reload)."""
        fn(); pg.wait_for_timeout(3500)
        fr=[f for f in pg.frames if "of-mirror" in f.url]
        if not fr: return fail(f"{label}: NO IFRAME; url {pg.url} | body: {pg.evaluate('document.body.innerText.slice(0,200)')}")
        url=unquote(pg.url.replace(BASE,"")); path=unquote(path); shown=fr[0].url.split("/pages/")[1]; spa=pg.evaluate("window.__marker===1")
        print(label, "->", url, "| iframe:", shown, "| spa:", spa)
        if url!=path: fail(f"{label}: url {url}, expected {path}")
        if shown!=f"{page}.html": fail(f"{label}: iframe {shown}, expected {page}.html")
        if not spa: fail(f"{label}: full page reload (client-side navigation lost)")
    step("click Fans and following", lambda: frame().get_by_text("Fans and following").first.click(), f"{R}/fans", "settings/fans")

    # Switches and inputs: in All Creators the Settings pages stand in with the first creator (ofMirrorProfile), so a
    # settings switch (ofMirrorSettingsWrites) writes for it and stays flipped with no note (the write is mocked); the
    # price is a Save form, so typing in it shows no note.
    note=lambda: frame().evaluate("document.getElementById('oi-note')?.textContent ?? null")
    sw="#setting_isAutoFollowBack + label.b-checkbox-switcher"
    look=lambda: frame().evaluate("s=>{const l=document.querySelector(s);return [l.previousElementSibling.checked,getComputedStyle(l.firstElementChild).backgroundColor,getComputedStyle(l.firstElementChild).left].join()}", sw)
    off=look(); frame().locator(sw).click(); pg.wait_for_timeout(500); after=look(); said=note()
    print("switch before/after, note:", off, "|", after, "|", said)
    if not (off.startswith("false") and after.startswith("true") and said is None): fail(f"switch: expected it on (from {off}) with no note, got {after} and {said!r}")

    step("click Subscription price", lambda: frame().get_by_text("Subscription price and bundles").first.click(), f"{R}/subscription", "settings/subscription")
    price=frame().locator("input[placeholder='Free']").first
    price.click(); price.fill("12.5")
    # Commit the field before the next click: its change note, shown on blur, would move the opener under a pending click.
    price.press("Tab"); pg.wait_for_timeout(300); said=note()
    print("price input:", price.input_value(), "| note:", said)
    if price.input_value()!="12.5": fail("Price per month input does not take typed text")
    if said is not None: fail(f"Price per month change: note {said!r}, expected none")
    step("click START PROMOTION CAMPAIGN", lambda: frame().get_by_text("START PROMOTION CAMPAIGN").first.click(), f"{R}/subscription/promotion-campaign/modal-1", "settings/subscription/promotion-campaign/modal-1")
    pg.screenshot(path=f"{SHOTS}/inapp-modal1.png")
    step("click CANCEL", lambda: frame().get_by_text("CANCEL").last.click(), f"{R}/subscription/promotion-campaign", "settings/subscription/promotion-campaign")
    step("click FREE TRIAL LINKS tab", lambda: frame().get_by_text("FREE TRIAL LINKS").first.click(), f"{R}/subscription/trial-links", "settings/subscription/trial-links")
    step("click Account", lambda: frame().get_by_text("Account", exact=True).first.click(), f"{R}/account", "settings/account")
    step("click Two step auth", lambda: frame().locator("a[href*='2fa']").first.click(), f"{R}/account/2fa", "settings/account/2fa")
    step("browser back", lambda: pg.go_back(), f"{R}/account", "settings/account")
    step("click back arrow", lambda: frame().locator("#content .b-settings__header a, #content .g-page__header a, #content a.b-back-btn, #content a[href='/of-manager/settings']").first.click(), R, "settings/profile")
    step("click Privacy and safety", lambda: frame().get_by_text("Privacy and safety").first.click(), f"{R}/security", "settings/security")
    step("click Block by country", lambda: frame().get_by_text("Block by country").first.click(), f"{R}/security/block_by_country", "settings/security/block_by_country")
    st="security/block_by_country/state-country-picker"
    step("open country picker (state page)", lambda: frame().locator(".v-select .of-state-link").first.click(), f"{R}/{st}", f"settings/{st}")
    pg.screenshot(path=f"{SHOTS}/inapp-state1.png")
    step("click an option (closes)", lambda: frame().locator(".of-state-menu .v-list-item .of-state-link").first.click(), f"{R}/security/block_by_country", "settings/security/block_by_country")
    step("open country picker again", lambda: frame().locator(".v-select .of-state-link").first.click(), f"{R}/{st}", f"settings/{st}")
    step("click the backdrop (closes)", lambda: pg.mouse.click(900, 700), f"{R}/security/block_by_country", "settings/security/block_by_country")

    # The other OF Manager sections: sidebar entry, then a tab or row inside the frame.
    M="/of-manager"
    def side(href):  # the 60px rail: the OF Manager icon opens its pages in a flyout (shell/Sidebar.tsx)
        def go():
            if not pg.locator(f"[role=menu] a[href='{href}']").count(): pg.locator("nav[aria-label=Main] button[aria-label='OF Manager']").click()
            pg.locator(f"[role=menu] a[href='{href}']").click()
        return go
    inframe=lambda href: (lambda: frame().locator(f"#content a[href='{href}']").first.click())  # #content: not OF's left nav
    step("sidebar OF Manager > Vault", side(f"{M}/vault"), f"{M}/vault", "vault/index")
    if not frame().evaluate("!!document.querySelector('#content')?.innerText.toLowerCase().includes('vault')"): fail("vault: frame does not show the vault")
    step("sidebar Notifications", side(f"{M}/notifications"), f"{M}/notifications", "notifications/index")
    step("click notifications Tips tab", inframe(f"{M}/notifications/tip"), f"{M}/notifications/tip", "notifications/tip")
    step("sidebar Messages Basic", side(f"{M}/messages"), f"{M}/messages", "messages/index")
    # All Creators with no model (this mock lists none): the list shows OF's own "Nothing found", no example rows.
    got=frame().evaluate("""[[...document.querySelectorAll('.b-chats__item')].filter(e => e.checkVisibility()).length,
      [...document.querySelectorAll('.b-chats__scroller [data-oi-empty]')].some(e => e.checkVisibility() && e.textContent.includes('Nothing found'))]""")
    print("  chat list rows, Nothing found:", got)
    if got!=[0,True]: fail(f"chat list: {got[0]} example row(s) shown or no Nothing found ({got})")
    pg.screenshot(path=f"{SHOTS}/inapp-chat-list.png")
    # A chat's composer dialogs are state pages: the price tool opens one, its Cancel goes back to the chat.
    pg.goto(f"{BASE}{M}/messages/chat", wait_until="load", timeout=90000); pg.wait_for_timeout(3000); pg.evaluate("window.__marker=1")
    price=frame().locator("a[href^='/of-manager/messages/chat/state-price']").first
    step("open the price dialog (state page) from the chat", lambda: price.click(), price.get_attribute("href"), "messages/chat/state-price")
    back=frame().locator("a.g-btn.m-flat:has-text('Cancel')").first
    step("click the dialog's Cancel (closes)", lambda: back.click(), back.get_attribute("href"), "messages/chat")
    # Infloww's Statistics lands on Statements › Earnings (app/next.config.ts); OF's top tabs land where OF lands them
    # (Engagement on Posts: scripts/of-mirror.mjs REDIRECTS), and Statements' Chargebacks is Statistics'.
    step("sidebar Statistics", side(f"{M}/statistics"), f"{M}/statistics/statements/earnings", "statistics/statements/earnings")
    step("click statistics Engagement tab (Posts)", inframe(f"{M}/statistics/engagement/posts"), f"{M}/statistics/engagement/posts", "statistics/engagement/posts")
    step("click statistics Messages chip", inframe(f"{M}/statistics/engagement/messages"), f"{M}/statistics/engagement/messages", "statistics/engagement/messages")
    step("click statistics Statements tab (Earnings)", inframe(f"{M}/statistics/statements/earnings"), f"{M}/statistics/statements/earnings", "statistics/statements/earnings")
    step("sidebar Statements", side(f"{M}/statements"), f"{M}/statements", "statements/index")
    step("click Statements' Chargebacks (Statistics')", inframe(f"{M}/statistics/statements/disputes"), f"{M}/statistics/statements/disputes", "statistics/statements/disputes")
    step("sidebar OF Manager > Go live", side(f"{M}/streaming"), f"{M}/streaming", "streaming/index")

    # Page states (a live capture's dialogs and dropdowns): the control opens the state page; Cancel, the backdrop and a menu's control go back.
    step("sidebar New post", side(f"{M}/new-post"), f"{M}/new-post", "new-post/index")
    sch=f"{M}/new-post/state-schedule"
    step("open Schedule post (state page)", lambda: frame().locator("a[aria-label='Schedule post']").first.click(), sch, "new-post/state-schedule")
    pg.screenshot(path=f"{SHOTS}/inapp-state-schedule.png")
    step("click Cancel (closes)", lambda: frame().locator("a.custom-datepicker-button-cancel").click(), f"{M}/new-post", "new-post/index")
    step("open Add poll (state page)", lambda: frame().locator("a[aria-label='Add poll']").first.click(), f"{M}/new-post/state-poll", "new-post/state-poll")
    step("click the poll's delete (closes)", lambda: frame().locator("a[aria-label='Delete']").first.click(), f"{M}/new-post", "new-post/index")
    step("open Expiration period (modal state)", lambda: frame().locator("a[aria-label='Expiration period']").first.click(), f"{M}/new-post/state-expiration", "new-post/state-expiration")
    step("click the backdrop (closes)", lambda: pg.mouse.click(300, 800), f"{M}/new-post", "new-post/index")
    step("sidebar Messages Basic", side(f"{M}/messages"), f"{M}/messages", "messages/index")
    step("open the chat list sort menu (state page)", lambda: frame().locator(".of-state-link").first.click(), f"{M}/messages/state-filter-dropdown", "messages/state-filter-dropdown")
    pg.screenshot(path=f"{SHOTS}/inapp-state-filter.png")
    step("click an option (closes)", lambda: frame().locator(".of-state-menu .v-list-item .of-state-link").first.click(), f"{M}/messages", "messages/index")
    step("sidebar Queue", side(f"{M}/queue"), f"{M}/queue", "queue/index")
    # The Posts / Messages / Streams tabs filter in place (OF's type filter), as the month arrows do; the view switch and
    # "Messages saved for later" navigate.
    tab=lambda: frame().locator("#content .g-page__subheader .b-tabs__nav__link:has-text('Messages')").first
    step("click the Messages tab (in place)", lambda: tab().click(), f"{M}/queue", "queue/index")
    if "m-current" not in (tab().get_attribute("class") or ""): fail("queue: the Messages tab not selected after its click")
    step("click the Messages tab again (in place)", lambda: tab().click(), f"{M}/queue", "queue/index")
    if "m-current" in (tab().get_attribute("class") or ""): fail("queue: the Messages tab still selected after a second click")
    step("click Messages saved for later", lambda: frame().locator("#content a[aria-label='Messages saved for later']").first.click(), f"{M}/queue/saved-for-later-messages", "queue/saved-for-later-messages")
    step("click its back arrow", lambda: frame().locator("#content a[aria-label='Back']").first.click(), f"{M}/queue", "queue/index")

    # OF's own left nav stays in the frame's DOM but hidden, as Infloww hides it (ofMirrorChrome.ts): the rail's OF
    # Manager flyout navigates instead. Then Go live from Home, and the streaming dashboard's SCHEDULE and back.
    if frame().locator("header.l-header > nav").is_visible(): fail("OF's own left nav shown in the frame (Infloww hides it)")
    step("sidebar OF Manager > New post", side(f"{M}/new-post"), f"{M}/new-post", "new-post/index")
    step("sidebar OF Manager > Home", side(f"{M}/home"), f"{M}/home", "home/index")
    step("OF home > GO LIVE", inframe(f"{M}/streaming"), f"{M}/streaming", "streaming/index")
    step("click Go live's back arrow", inframe(f"{M}/home"), f"{M}/home", "home/index")
    step("open the streaming dashboard", lambda: (pg.goto(f"{BASE}{M}/streaming/dashboard", wait_until="load", timeout=90000), pg.evaluate("window.__marker=1")), f"{M}/streaming/dashboard", "streaming/dashboard")
    step("click the dashboard's SCHEDULE", inframe(f"{M}/streaming/dashboard/create"), f"{M}/streaming/dashboard/create", "streaming/dashboard/create")
    pg.screenshot(path=f"{SHOTS}/inapp-stream-create.png")
    step("click the schedule form's back arrow", inframe(f"{M}/streaming/dashboard"), f"{M}/streaming/dashboard", "streaming/dashboard")
    step("sidebar OF Manager > OF settings", side(f"{M}/settings"), f"{M}/settings", "settings/profile")

    # Single-model scope: /users/me fills the placeholders (username, name, price, bio) in the frame.
    me={"username":"livemodel","name":"Live Model","subscribePrice":12.5,"rawAbout":"Hi from live","avatar":None,"header":None}
    c2=b.new_context(viewport={"width":1440,"height":900}); c2.add_init_script("localStorage.setItem('chatterly:scope','model:acc1')")
    p2=c2.new_page()
    def mock2(route):
        if "/api/of/v2/users/me" in route.request.url and route.request.url.split("?")[0].endswith("/users/me"):
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(me))
        mock(route)
    for pat in ["**/auth/**","**/chatter/**","**/admin/**","**/accounts**","**/api/**"]: p2.route(pat, mock2)
    p2.route("**/events?**", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=""))  # no Relay: an empty stream, not a 500
    p2.goto(f"{BASE}{R}", wait_until="load", timeout=90000); p2.wait_for_timeout(3000)
    c=p2.get_by_text("Tim", exact=True)
    if c.count(): c.first.click(); p2.wait_for_timeout(2500)
    p2.wait_for_timeout(2000)
    fr=[f for f in p2.frames if "of-mirror" in f.url]
    if not fr: fail("live identity: NO IFRAME")
    else:
        text=fr[0].evaluate("document.body.innerText+' '+[...document.querySelectorAll('input')].map(i=>i.value).join(' ')")
        for want in ["@livemodel","Live Model","12.5","Hi from live"]:
            if want not in text: fail(f"live identity: frame lacks {want!r}")
        if "12/1000" not in fr[0].evaluate("document.querySelector('.count-block')?.textContent.replace(/\\s/g,'')||''"): fail("live identity: bio counter not updated")
        for gone in ["yourmodel","Your Model","Welcome to my page"]:
            if gone in text: fail(f"live identity: frame still shows {gone!r}")
        print("live identity ok" if len(failures)==0 else "live identity: see FAIL lines")
    p2.screenshot(path=f"{SHOTS}/inapp-live-identity.png")
if failures:
    print(f"{len(failures)} check(s) failed"); sys.exit(1)
print("all checks passed")
