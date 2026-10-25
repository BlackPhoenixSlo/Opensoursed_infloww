"""The screens capture.py shoots: slug (the web/public/img/<slug>*.webp name), route,
what must be on screen before the shot, and any clicks that put the page in state.

Keys: slug, path (or desktop_path / phone_path; a string, or callable(dataset) -> string),
wait / desktop_wait / phone_wait (texts that must be visible; "placeholder=<text>" for an input's hint), forbid (texts that must not
be visible; default "$0.00", "No creators" and "Loading…", a chart still waiting on its read), act / desktop_act / phone_act
(callable(page, kind)), pre_wait (texts to wait for before act), skip (("desktop",) or
("phone",)), anon (signed out), session ("manager": signed in as the manager, who has Shifts), pause (ms),
frame_wait (texts inside the page's iframe), desktop_viewport (CSS size; the shot stays 2560 px wide), min_bubbles / desktop_min_bubbles (Messages Pro bubbles wholly in view),
key (text, or "css=<selector>", of the figure the combo's phone must not cover: a text's first visible match, a
selector's last), prices (the screen shows unit prices or averages, LTV, ARPU, avg spend, CPC, which keep their cents as
Infloww prints them, so a non-round "$19.99" is allowed; every other cents figure fails the money check).
"""
from __future__ import annotations

from dataset import STUDIO



def gross(page, kind):
    page.locator('[data-control="basis"] button').first.click()
    page.get_by_text("Gross earnings", exact=True).last.click()


def scroll_to(selector: str, gap: int = 12):
    """An act: scroll the page so the element's top sits `gap` px under the sticky top bar."""
    def act(page, kind):
        page.locator(selector).first.evaluate("""(el, gap) => {
            el.scrollIntoView({block: 'start'});
            const bar = document.querySelector('header')?.getBoundingClientRect().bottom || 56;
            const off = el.getBoundingClientRect().top - bar - gap;
            for (let p = el.parentElement; p; p = p.parentElement) {   // the vertical scroller that moved
              if (p.scrollTop > 0 && p.clientHeight > window.innerHeight / 2) { p.scrollTop += off; return; }
            }
            document.scrollingElement.scrollTop += off;
          }""", gap)
        page.wait_for_timeout(600)
    return act


def gross_table(page, kind):
    """Creator statistics at gross: with "Show net earnings" on (the default) every per-kind money column reads "-"."""
    sw = page.get_by_role("switch", name="Show net earnings").first
    if sw.get_attribute("aria-checked") == "true":
        sw.click()
    page.wait_for_timeout(800)
    scroll_to(CREATOR_TABLE)(page, kind)


def gross_then(act):
    def both(page, kind):
        gross(page, kind)
        page.get_by_text("20 models", exact=True).first.wait_for(state="attached", timeout=45_000)
        act(page, kind)
    return both


def thread(d) -> str:
    return f"/messages-pro/{d.thread['account_id']}/{d.thread['fan_id']}"


def unpin(page, kind):
    """A real wheel over the thread ends Messages Pro's auto-pin ("Jumping to latest..."). Its 5s backstop timer is
    cleared whenever the message list refetches inside those 5s, so without a user gesture the chip can stay."""
    page.get_by_text("Unlocked it. Worth every cent", exact=True).filter(visible=True).first.hover()
    page.mouse.wheel(0, 400)
    page.get_by_text("Jumping to latest", exact=False).wait_for(state="hidden", timeout=10_000)


def insights(page, kind):
    page.get_by_label("Fan insights", exact=True).first.click()
    page.wait_for_timeout(1000)
    unpin(page, kind)


def of_home(d) -> str:
    return f"/of-manager/home?account={d.creators[0]['id']}"


THREAD = ["Worth every cent", "$50.00 tip", "made my whole day", "Can't wait for the next set"]
WIDE = {"width": 1600, "height": 1000}  # Messages Pro desktop: 9+ bubbles need a taller thread; still 2560x1600 px
LAST_BUBBLE = "css=[data-msg-id]"  # the thread's last bubble (key: its last visible match)
KPIS = 'section:has(> header > h2:text-is("Per-model KPIs"))'
CREATOR_TABLE = '[role="table"][aria-label="Creator statistics"]'
NO_JUMP = ["$0.00", "No creators", "Loading…", "Jumping to latest"]

SCREENS: list[dict] = [
    {"slug": "dashboard", "path": "/?window=month", "session": "manager", "pre_wait": ["Creator earnings overview"],
     "act": gross, "wait": ["Total earnings", "$1,0", "My shifts", "This week", "Next week", "20 models"],
     "key": "$1,0"},
    {"slug": "dashboard-kpis", "path": "/?window=month", "pre_wait": ["Creator earnings overview"],
     "act": gross_then(scroll_to(KPIS)), "wait": ["Per-model KPIs", "20 models"], "prices": True},
    {"slug": "messages-pro", "desktop_path": thread, "desktop_viewport": WIDE, "phone_path": "/messages-pro",
     "desktop_pre_wait": THREAD, "desktop_act": unpin,
     "desktop_wait": THREAD + ["placeholder=quickly search scripts"], "phone_wait": ["Newest first", "@"], "forbid": NO_JUMP,
     "prices": True, "desktop_min_bubbles": 9, "key": LAST_BUBBLE, "pause": 1500},
    {"slug": "messages-pro-thread", "path": thread, "desktop_viewport": WIDE, "pre_wait": THREAD, "desktop_act": insights,
     "phone_act": unpin, "wait": THREAD, "desktop_wait": THREAD + ["placeholder=quickly search scripts", "Total spend"],
     "forbid": NO_JUMP, "prices": True, "desktop_min_bubbles": 9, "key": LAST_BUBBLE, "pause": 1500},
    {"slug": "creators", "path": "/creators", "wait": ["Manage creators", "Connected", "@avamonroe"]},
    {"slug": "creator-reports", "path": "/analytics/creator-reports", "wait": ["Earnings summary", "Total earnings"],
     "key": "Total earnings"},
    {"slug": "creator-reports-table", "path": "/analytics/creator-reports", "pre_wait": ["Creator statistics", "Ava"],
     "act": gross_table, "wait": ["Creator statistics", "Ava", "Luna", "Total subscription earnings"], "prices": True},
    {"slug": "employee-reports", "path": "/analytics/employee-reports", "wait": ["Employee sales", "Sales ranking"], "prices": True},
    {"slug": "sales-records", "path": "/analytics/sales-records", "wait": ["Reassign"], "prices": True},
    {"slug": "message-dashboard", "path": "/analytics/message-dashboard", "wait": ["Unsend"]},
    {"slug": "fan-reports", "path": "/analytics/fan-reports", "wait": ["New fans (growth & trends)", "Renews"], "pause": 2500},
    {"slug": "vault-pro", "path": "/growth/vault-pro", "wait": ["Beach day"]},
    {"slug": "scripts", "path": "/growth/scripts", "wait": ["Holiday special"], "prices": True},
    {"slug": "smart-messages", "path": "/growth/smart-messages", "wait": ["Active", "Nudge"]},
    {"slug": "auto-post", "path": "/growth/auto-post", "wait": ["Morning teaser"]},
    {"slug": "auto-follow", "path": "/growth/auto-follow", "wait": ["Total follows", "October"]},
    {"slug": "tracking-links", "path": "/growth/tracking-links", "wait": ["Instagram bio"], "prices": True},
    {"slug": "employees", "path": "/employees", "wait": ["Olivia Chen", STUDIO]},
    {"slug": "shifts", "path": "/employees/shifts", "wait": ["Olivia Chen"]},
    {"slug": "roles", "path": "/settings/roles", "wait": ["Role Settings", "Team Leader"]},
    {"slug": "share-for-share", "path": "/share-for-share/discover-creators", "wait": ["Bella Vaughn"]},
    {"slug": "of-manager", "path": of_home, "frame_wait": ["New week, new set"], "pause": 2500},
    {"slug": "login", "path": "/login", "anon": True, "wait": ["Welcome to Inflowwww"], "forbid": []},
]
