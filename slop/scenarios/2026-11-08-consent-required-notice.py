"""OnlyFans' consent-form demand (NC/AL law) as a pinned agency notification and a shell banner
(service/consent_notices.py, notifications_api.PINNED_KINDS, app ConsentBanner + AgencyFeed's pinned rows).

World: `agency_inbox` (small 3 Creators x 50 fans, medium 10 x 500), a captured session per Creator against
lib/of_wire.py (`OF_WIRE`), every Creator's WS pump up on the fake's socket. REF = creators[0] (OF refuses its
media sends), ME = creators[1] (its /users/me says needConsent, law AL), the rest clean.

Flow:
  L  `--sends=` (FLOW_SIZES `consent_sends`) media sends through the real `POST /api/of/v2/chats/{fan}/messages`
     over every Creator's fans, `--users` at once, while OF refuses REF's (400 Consent not accepted).
  M  ME flagged by OF; its socket dropped: the pump's reconnect reads /users/me.
  D  each pinned row's `POST /{id}/read`, then read-all.
  U  owner's browser, desktop 1600x1000 and phone portrait 390x844: the banner, its View, the bell's Agency tab
     (screenshots `trigger-desktop`, `trigger-phone`).
  C  REF signs (/users/me approved) and its socket drops: the reconnect clears it. ME's refusal lifts and one
     media send goes through: cleared. REF refused again (one send), then the owner deletes REF from Creators
     (`DELETE /admin/accounts/{id}`): dropped. Browser again (`settled-desktop`, `settled-phone`).

Checks (names in lib/consent_faults.py): FLAGGED_ONCE, SENDS_KEPT, FLAGGED_BY_ME, NOT_DISMISSABLE, UI_TRIGGER,
CLEARED_BY_ME, CLEARED_BY_SEND, CLEARED_BY_REMOVAL, UI_SETTLED; budget p95 of the send route at --users, and vs
the last green run. Side effect: the agency_notifications rows (SQL) after every step, `rows.json`.

Bypasses (declared): OnlyFans is lib/of_wire.py's fake (its consent fields and refusal body as OF answered AE's
send 1495; `consentStatus` null while unsigned is a guess). REF's refused sends answer 502 by design (the relay's
upstream-error mapping), so they go through their own recorder, checked by SENDS_KEPT, not the stock no-5xx.
The owner calls are httpx pools, not the composer.
"""
from __future__ import annotations

import asyncio
import json
import time

from slop.actors import ui
from slop.lib.client import Recorder
from slop.lib.consent_faults import (CLEARED_BY_ME, CLEARED_BY_REMOVAL, CLEARED_BY_SEND, FLAGGED_BY_ME, FLAGGED_ONCE,
                                     NOT_DISMISSABLE, SEND_ROUTE, SENDS_KEPT, UI_SETTLED, UI_TRIGGER)
from slop.seed import of_sessions

PROFILE = "agency_inbox"
UI = True
OF_WIRE = True
FAULT = "consent-send-ok-not-clearing"
P95_MS = {SEND_ROUTE: 5_000}
P95_VS_LAST = (2.0, 2000)
BUDGET = f"p95 {SEND_ROUTE} at --users within the scenario's P95_MS"
CALL_TIMEOUT_S = 120
SETTLE_S = 60
FEED = "/admin/agency-notifications?limit=50"
PHONE = (390, 844)


async def _pool(items, fn, n: int) -> None:
    it = iter(list(items))

    async def worker():
        for x in it:
            await fn(x)

    await asyncio.gather(*(worker() for _ in range(max(1, n))))


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    creators = w.data["creators"]
    ids = [c["id"] for c in creators]
    ref, me_ = ids[0], ids[1]
    of_sessions.seed(w, creators)
    fake = ctx.of_wire
    owner = ctx.owner
    refused_rec = Recorder()
    http = owner.share(limits=ctx.users + 8)
    http_ref = owner.share(rec=refused_rec, limits=ctx.users + 8)
    names = {c["id"]: c.get("nickname") or c["id"] for c in creators}
    log: list[dict] = []

    def rows() -> list[tuple]:
        con = w.sql()
        try:
            return con.execute("SELECT agency_user_id, account_id, read_at, text FROM agency_notifications "
                               "WHERE kind = 'consent_required' ORDER BY id").fetchall()
        finally:
            con.close()

    async def feed() -> dict:
        r = await owner.get(FEED)
        r.raise_for_status()
        return r.json()

    async def pinned_ids() -> set[str]:
        return {n["account_id"] for n in (await feed())["pinned"]}

    async def until(pred, timeout_s: float = SETTLE_S) -> bool:
        t_end = time.time() + timeout_s
        while time.time() < t_end:
            if await pred():
                return True
            await asyncio.sleep(0.25)
        return False

    def snap(step: str) -> None:
        log.append({"step": step, "t": time.time(), "rows": [list(map(str, r)) for r in rows()]})

    async def send(aid: str, fan: int, media: int, h=None) -> dict:
        r = await (h or http).post(f"/api/of/v2/chats/{fan}/messages", headers={"X-Account-Id": aid},
                                   timeout=CALL_TIMEOUT_S, json={"text": "new set", "media_files": [media]})
        return {"aid": aid, "fan": fan, "status": r.status_code, "body": r.text[:300]}

    async def wait_ws(aid: str, after: float) -> bool:
        async def up() -> bool:
            with fake.lock:
                return any(c["account"] == aid and c["t"] > after for c in fake.ws_connects)
        return await until(up)

    # ── every Creator's pump on OF's socket ──────────────────────────────────
    await owner.post("/__slop/pump-supervise")
    for aid in ids:
        await wait_ws(aid, 0)

    # ── L: the send load while OF refuses REF's media sends ──────────────────
    with fake.lock:
        fake.consent[ref] = "NC"
    targets = [(c["id"], f["id"]) for c in creators for f in w.data["fans"][c["id"]]]
    n_sends = ctx.param("sends", w.size["consent_sends"])
    plan = [(targets[i % len(targets)], 700_000 + i) for i in range(n_sends)]
    sends: list[dict] = []

    async def one(job) -> None:
        (aid, fan), media = job
        sends.append(await send(aid, fan, media, http_ref if aid == ref else None))

    ctx.rec.stage = "send"
    t0 = time.time()
    await _pool(plan, one, ctx.users)
    send_s = time.time() - t0
    ctx.rec.stage = None
    await until(lambda: _true(ref in {r[1] for r in rows()}), 15)
    got = rows()
    body = await feed()
    snap("after-load")
    ctx.check(FLAGGED_ONCE, [tuple(r[:2]) for r in got] == [(creators[0]["owner"], ref)]
              and [n["account_id"] for n in body["pinned"]] == [ref]
              and "OnlyFans needs a signed consent form (NC/AL law)" in got[0][3],
              rows=[r[:2] for r in got], pinned=[n["account_id"] for n in body["pinned"]])
    with fake.lock:
        kept = {a: len(v) for a, v in fake.sends.items()}
    want = {a: sum(1 for (x, _f), _m in plan if x == a) for a in ids}
    bad = [s for s in sends if (s["status"] != 200) != (s["aid"] == ref)
           or (s["aid"] == ref and "Consent not accepted" not in s["body"])]
    ctx.check(SENDS_KEPT, len(sends) == n_sends and not bad and kept.get(ref, 0) == 0
              and all(kept.get(a, 0) == want[a] for a in ids if a != ref),
              sends=len(sends), bad=bad[:5], kept=kept, want=want)

    # ── M: ME flagged through /users/me on the pump's reconnect ──────────────
    with fake.lock:
        fake.consent[me_] = "AL"
    t1 = time.time()
    await asyncio.to_thread(fake.drop_ws, [me_])
    reconnected = await wait_ws(me_, t1)
    flagged = await until(lambda: _has(pinned_ids, me_))
    me_rows = [r for r in rows() if r[1] == me_]
    snap("after-users-me")
    ctx.check(FLAGGED_BY_ME, reconnected and flagged and len(me_rows) == 1 and "(AL law)" in me_rows[0][3],
              reconnected=reconnected, rows=[r[:2] for r in me_rows])

    # ── D: nothing dismisses them ─────────────────────────────────────────────
    body = await feed()
    reads = [(await owner.post(f"/admin/agency-notifications/{n['id']}/read")).status_code for n in body["pinned"]]
    after_all = (await owner.post("/admin/agency-notifications/read-all")).json()
    unread_sql = [r for r in rows() if r[2] in (None, "None")]
    snap("after-dismiss")
    ctx.check(NOT_DISMISSABLE, len(reads) == 2 and all(s == 409 for s in reads) and len(unread_sql) == 2
              and after_all.get("unread", 0) >= 2,
              reads=reads, read_all=after_all, unread_rows=len(unread_sql))

    # ── U: the banner and the Agency tab ──────────────────────────────────────
    async def look(tag: str, want_names: list[str]) -> dict:
        out: dict = {}
        for label, viewport, touch in (("desktop", (1600, 1000), False), ("phone", PHONE, True)):
            async with ui.owner_browser(ctx, viewport=viewport, touch=touch) as page:
                await page.goto(f"{ctx.app}/", wait_until="domcontentloaded")
                await page.get_by_role("button", name="Notifications").wait_for(timeout=90_000)
                banner = page.locator("[data-consent-banner]")
                info: dict = {}
                if want_names:
                    await banner.wait_for(timeout=60_000)
                    info["banner"] = await banner.inner_text()
                    await banner.get_by_role("button", name="View").click()
                    rows_ = page.get_by_test_id("agency-pinned")
                    await rows_.nth(len(want_names) - 1).wait_for(timeout=30_000)
                    info["pinned"] = await rows_.count()
                    info["controls"] = await page.locator("[data-testid=agency-pinned] :is(button, a)").count()
                    info["tab"] = await page.get_by_role("tab", name="Agency").get_attribute("aria-selected")
                    info["fits"] = await page.evaluate(
                        "() => { const b = document.querySelector('[data-consent-banner]').getBoundingClientRect();"
                        " return b.left >= 0 && b.right <= window.innerWidth && b.height <= 48; }")
                else:
                    await page.wait_for_timeout(3_000)
                    info["banner"] = await banner.count()
                    await page.get_by_role("button", name="Notifications").click()
                    tab = page.get_by_role("tab", name="Agency")
                    if await tab.count():
                        await tab.click()
                    await page.wait_for_timeout(1_000)
                    info["pinned"] = await page.get_by_test_id("agency-pinned").count()
                info["screenshot"] = await ui.shot(ctx, page, f"{tag}-{label}")
                out[label] = info
        return out

    want_names = [names[ref], names[me_]]
    if ctx.app:
        try:
            trig = await look("trigger", want_names)
            ok = all(v["pinned"] == 2 and v["controls"] == 0 and v["tab"] == "true" and v["fits"]
                     and all(n in v["banner"] for n in want_names) for v in trig.values())
        except Exception as e:  # noqa: BLE001 — a missing banner is a red check, not a crash
            trig, ok = {"error": repr(e)[:300]}, False
        ctx.check(UI_TRIGGER, ok, **trig)
    else:
        ctx.skip(UI_TRIGGER, "--no-ui")

    # ── C: three ways out ─────────────────────────────────────────────────────
    with fake.lock:
        fake.consent_signed.add(ref)
    t2 = time.time()
    await asyncio.to_thread(fake.drop_ws, [ref])
    rc = await wait_ws(ref, t2)
    gone = await until(lambda: _lacks(pinned_ids, ref))
    snap("after-approved")
    ctx.check(CLEARED_BY_ME, rc and gone and ref not in {r[1] for r in rows()}, reconnected=rc,
              rows=[r[:2] for r in rows()])

    with fake.lock:
        fake.consent.pop(me_, None)
    fan_me = w.data["fans"][me_][0]["id"]
    ok_send = await send(me_, fan_me, 799_001)
    gone = await until(lambda: _lacks(pinned_ids, me_), 15)
    snap("after-media-send")
    ctx.check(CLEARED_BY_SEND, ok_send["status"] == 200 and gone and me_ not in {r[1] for r in rows()},
              send=ok_send, rows=[r[:2] for r in rows()])

    with fake.lock:
        fake.consent_signed.discard(ref)
    again = await send(ref, w.data["fans"][ref][0]["id"], 799_002, http_ref)
    reflagged = await until(lambda: _has(pinned_ids, ref), 15)
    removed = await owner.request("DELETE", f"/admin/accounts/{ref}")
    body = await feed()
    snap("after-removal")
    ctx.check(CLEARED_BY_REMOVAL, again["status"] == 502 and reflagged and removed.status_code == 200
              and body["pinned"] == [] and rows() == [],
              resend=again["status"], reflagged=reflagged, delete=removed.status_code,
              pinned=[n["account_id"] for n in body["pinned"]], rows=[r[:2] for r in rows()])

    if ctx.app:
        try:
            sett = await look("settled", [])
            ok = all(v["banner"] == 0 and v["pinned"] == 0 for v in sett.values())
        except Exception as e:  # noqa: BLE001
            sett, ok = {"error": repr(e)[:300]}, False
        ctx.check(UI_SETTLED, ok, **sett)
    else:
        ctx.skip(UI_SETTLED, "--no-ui")
    await http.aclose()
    await http_ref.aclose()

    # ── budgets, evidence ─────────────────────────────────────────────────────
    routes = ctx.rec.summary("send")
    r = routes.get(SEND_ROUTE)
    if r is None:
        ctx.skip(BUDGET, "no samples")
    else:
        ctx.check(BUDGET, r["p95_ms"] < P95_MS[SEND_ROUTE], budget=True, p95=r["p95_ms"], n=r["n"],
                  budget_ms=P95_MS[SEND_ROUTE])
    ctx.metric("load", {"creators": len(creators), "users": ctx.users, "sends": n_sends, "send_s": round(send_s, 2),
                        "refused": len(refused_rec.calls.get(SEND_ROUTE, [])), "routes": routes})
    ctx.metric("p95_vs_last_green", {k: routes[k]["p95_ms"] for k in P95_MS if k in routes})
    (ctx.out / "rows.json").write_text(json.dumps(log, indent=1))
    with fake.lock:
        (ctx.out / "of-wire-calls.json").write_text(json.dumps(
            [c for c in fake.calls if c["route"] != "GET /hash"][-2000:]))


async def _true(v: bool) -> bool:
    return v


async def _has(pinned_ids, aid: str) -> bool:
    return aid in await pinned_ids()


async def _lacks(pinned_ids, aid: str) -> bool:
    return aid not in await pinned_ids()
