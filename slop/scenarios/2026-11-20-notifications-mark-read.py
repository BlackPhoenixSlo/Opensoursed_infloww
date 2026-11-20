"""Messages Pro's green "Notifications" button clears OF's notification count (service/server.py
`of_notifications_mark_read`, app hooks/useOfNotifCount.ts `useMarkOfNotifsRead`). Its badge is OF's own counter
(`/users/notifications/count` `all`); only OF's mark-read (`POST /users/notifications/read`, what OF web sends on
opening a notifications tab) lowers it. Before the fix it was never sent: the badge only grew.

World: `agency_inbox`, a captured session per Creator, OnlyFans on lib/of_wire.py with Creator A's count at
COUNTS (`all` 7) and Creator B's at COUNTS too.
1. UI (not --no-ui): the owner, scoped to A, opens /messages-pro: the button reads "Notifications 7" (shot
   `notif-badge-trigger`); click it, the panel lists, Escape closes it (shot `notif-badge-settled`).
   WIRE_ONE: the wire got exactly one mark-read for A, All (no type), none for B. BADGE: the button read 7 before
   and has no number after. RELAY_ZERO: the relay's count route for A answers `all` 0 (OF's lowered count).
2. API: `POST /api/of/v2/users/notifications/read` as B (X-Account-Id): its answer's `counters.all` 0, the wire
   saw one mark-read for B, and the count route for B answers 0 right after, its 30 s cache dropped (API_BUST).

Bypasses (declared): the counts are set at the wire (the fake keeps them until a mark-read).
Break-it-once (lib/notifications_read_faults.py): notif-read-not-sent: OFClient.notifications_read answers `{}`
without reaching OF (the pre-fix state at the wire): WIRE_ONE, BADGE, RELAY_ZERO, API_BUST.
"""
from __future__ import annotations

import asyncio
import re

from slop.actors import ui
from slop.lib.notifications_read_faults import API_BUST, BADGE, RELAY_ZERO, WIRE_ONE
from slop.seed import of_sessions

PROFILE = "agency_inbox"
UI = True
OF_WIRE = True
FAULT = "notif-read-not-sent"
COUNTS = {"all": 7, "subscribed": 4, "purchases": 2, "tip": 1}
COUNT = "/api/of/v2/users/notifications/count"
READ = "/api/of/v2/users/notifications/read"
THROUGH = (COUNT, re.compile(r"/api/of/v2/users/notifications"), ("POST", re.compile(re.escape(READ))))
SETTLE_S = 30


def _reads(fake, aid: str) -> list:
    with fake.lock:
        return list(fake.notif_reads.get(aid, ()))


async def _count(ctx, aid: str) -> int | None:
    r = await ctx.owner.get(COUNT, headers={"X-Account-Id": aid})
    return r.json().get("all") if r.status_code == 200 else None


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    creators = w.data["creators"]
    a, b = creators[0]["id"], creators[1]["id"]
    of_sessions.seed(w, creators)
    fake = ctx.of_wire
    with fake.lock:
        fake.notif_counts[a] = dict(COUNTS)
        fake.notif_counts[b] = dict(COUNTS)

    if not ctx.app:
        for n in (WIRE_ONE, BADGE, RELAY_ZERO):
            ctx.skip(n, "--no-ui")
    else:
        async with ui.owner_browser(ctx, through=THROUGH) as page:
            await page.add_init_script(f"try {{ localStorage.setItem('chatterly:scope', 'model:{a}'); }} catch (e) {{}}")
            await page.goto(f"{ctx.app}/messages-pro", wait_until="domcontentloaded")
            button = page.get_by_role("button", name=re.compile(r"^Notifications\b")).first
            before = None
            try:
                await page.get_by_role("button", name=f"Notifications {COUNTS['all']}").first.wait_for(timeout=120_000)
                before = COUNTS["all"]
            except Exception:  # noqa: BLE001 — BADGE fails on it
                before = await button.get_attribute("aria-label") or await button.inner_text()
            trigger = await ui.shot(ctx, page, "notif-badge-trigger")
            await button.click()
            await page.get_by_role("button", name="Subscriptions").first.wait_for(timeout=30_000)
            await page.keyboard.press("Escape")
            try:   # the badge gone: the button's name is the word alone
                await page.get_by_role("button", name="Notifications", exact=True).first.wait_for(timeout=SETTLE_S * 1000)
                after = "Notifications"
            except Exception:  # noqa: BLE001 — BADGE fails on it
                after = " ".join((await button.inner_text()).split())
            settled = await ui.shot(ctx, page, "notif-badge-settled")
            await asyncio.sleep(1.0)   # a stray second mark-read would have reached the wire by now
        got = _reads(fake, a)
        ctx.check(WIRE_ONE, len(got) == 1 and got[0][1] is None and not _reads(fake, b), a=got, b=_reads(fake, b))
        ctx.check(BADGE, before == COUNTS["all"] and after == "Notifications", before=before, after=after,
                  trigger=trigger, settled=settled)
        relay_after = await _count(ctx, a)
        ctx.check(RELAY_ZERO, relay_after == 0, relay_all=relay_after)

    warm = await _count(ctx, b)   # cached at the relay for 30 s
    r = await ctx.owner.post(READ, headers={"X-Account-Id": b})
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    after_b = await _count(ctx, b)
    ctx.check(API_BUST, warm == COUNTS["all"] and r.status_code == 200
              and (body.get("counters") or {}).get("all") == 0 and len(_reads(fake, b)) == 1 and after_b == 0,
              warm=warm, http=r.status_code, body=body, wire=_reads(fake, b), after=after_b)
