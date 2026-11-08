"""Inbox under a fan DM burst: --users fans DM their Creators; the manager watches
/events and the inbox. Frames enter in the pump's shape (actors/fan_dm.serial):
one frame in flight per Creator, every Creator at once, as fast as the relay
takes them, or open loop at --rate=N frames/s per Creator. Proves the WS ingest
path (pump boundary -> persist worker -> transcoder -> chats/messages -> SSE)
loses nothing under load and the inbox's unread counts add up.

Invariants: every DM accepted; zero persist-queue drops; every DM reaches the SSE
stream; every DM is in its thread (/admin/messages); each fan's unreadMessagesCount
(/admin/chats/recent) == seeded unread + DMs sent; the burst fans head their
Creator's inbox; UI: Messages Pro shows the burst, and a click on a notification of a
fan's DM (toast in the main window and in Messages Pro, top bar bell row, /notifications
row, OS notification; in the browser and in the desktop app) opens that Fan as a Fan tab
in the one Messages Pro window (actors/notif_click; `--set desktop=0` skips Electron).
Quick reply (the Messages Pro bell's Reply, app/components/NotificationQuickReply.tsx):
one Fan DMs two Creators (the same Fan id on both; the second Creator's chat is made by
the ingest), Messages Pro on All Models lists both rows in its bell; Reply on the second
Creator's row, a line typed and sent: OF got exactly that one send, as that Creator to
that Fan with the typed text, nothing to the first Creator (lib/relay.py `of_sends`), the
line is in that thread (/admin/messages) and not in the other; the field read Sent and
the other Creator's row still offers Reply (screenshots quick-reply-trigger / -settled).
Declared bypass: the bell's OF notifications feed is answered empty at the wire (as in
actors/notif_click), so the rows are the DMs' own (the SSE history mirror).
Budgets: end-to-end p95 (frame handed to the relay -> on the manager's /events stream)
and the inbox read p95s. Break-it-once: transcoder-drops-1-in-10,
`--fault=notif-click-opens-browser-tab` and `--fault=quick-reply-to-wrong-fan` (targets in
lib/faults.py).
"""
from __future__ import annotations

import asyncio
import json
import math
import re

from slop.actors import fan_dm, manager, notif_click, ui

PROFILE = "agency_inbox"
UI = True
FAULT = "transcoder-drops-1-in-10"
# Budgets (ms). E2E: frame handed to the relay -> that message on the manager's
# /events SSE stream. P95_MS: real inbox read routes, per actor call.
E2E_P95_MS = 500
P95_MS = {"GET /admin/chats/recent": 500, "GET /admin/messages/:id/:id": 500}
RECENT_MAX = 100  # /admin/chats/recent limit cap: per-creator targets stay within one page


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    per_fan = ctx.param("per_fan", w.size["inbox_unread_per_fan"])
    rate = ctx.param("rate", 0.0)  # frames/s per Creator; 0 = closed loop (next frame when the last returns)
    creators, fans = w.data["creators"], w.data["fans"]
    k = min(RECENT_MAX, math.ceil(ctx.users / len(creators)))
    rng = w.rng("scenario:inbox-burst")
    targets = [f for c in creators for f in rng.sample(fans[c["id"]], min(k, len(fans[c["id"]])))][: ctx.users]
    seeded_unread = {(t["account_id"], t["fan_id"]): t["unread"] for t in w.data["threads"]}
    accounts = sorted({t["account_id"] for t in targets})
    ctx.metric("burst", {"fans": len(targets), "per_fan": per_fan, "dms": len(targets) * per_fan,
                         "accounts_in_parallel": len(accounts), "in_flight_per_account": 1,
                         "rate_per_account": rate or "closed-loop"})

    sse = manager.SseListener(ctx.owner.share())
    await sse.start()
    pool = ctx.owner.share(limits=max(10, len(accounts)))
    t0 = asyncio.get_running_loop().time()
    recs = await fan_dm.serial(pool, targets, per_fan, rate=rate)
    burst_s = asyncio.get_running_loop().time() - t0
    sent = [r for r in recs if r["status"] < 300]
    stats = await manager.quiesce(ctx.owner)
    await asyncio.sleep(1.0)  # let the SSE tail flush
    await sse.stop()
    await pool.aclose()
    ctx.metric("burst_seconds", round(burst_s, 2))
    ctx.metric("dms_per_second", round(len(sent) / burst_s, 1) if burst_s else None)
    ctx.metric("relay_stats", stats)
    ctx.metric("pump", _pump_metrics(recs, rate))

    want = len(targets) * per_fan
    ctx.check("every DM accepted (2xx)", len(sent) == want, sent=len(sent), want=want)
    ctx.check("relay quiesced (every frame processed)", not stats.get("timed_out"), stats=stats)
    ctx.check("zero persist-queue drops", stats["persist_drops"] == 0, drops=stats["persist_drops"])
    sent_ids = {s["message_id"] for s in sent}
    missing_sse = sent_ids - set(sse.message_ids)
    ctx.check("every DM reached the manager's /events stream", not missing_sse,
              missing=len(missing_sse), received=len(sse.message_ids))
    e2e = [sse.received_at[r["message_id"]] - r["t0"] for r in sent if r["message_id"] in sse.received_at]
    from_due = [sse.received_at[r["message_id"]] - r["due"] for r in sent if r["message_id"] in sse.received_at]
    ctx.metric("e2e_ms", {"n": len(e2e), **_pcts(e2e), **({"from_due": _pcts(from_due)} if rate else {})})
    name = f"e2e p95 (frame handed to relay -> on /events) < {E2E_P95_MS}ms"
    if e2e:
        ctx.check(name, _p(e2e, 0.95) < E2E_P95_MS, budget=True, p95=round(_p(e2e, 0.95), 1), n=len(e2e))
    else:
        ctx.skip(name, "no DM reached /events: no samples")

    # Threads: every injected id present in its fan's timeline.
    sem = asyncio.Semaphore(20)
    by_fan: dict[tuple, set[int]] = {}
    for s in sent:
        by_fan.setdefault((s["account_id"], s["fan_id"]), set()).add(s["message_id"])

    async def thread_gap(key):
        async with sem:
            got = {m["message_id"] for m in await manager.thread_messages(ctx.owner, key[0], key[1])}
            return len(by_fan[key] - got)

    gaps = await asyncio.gather(*(thread_gap(k_) for k_ in by_fan))
    ctx.check("every DM is in its thread (/admin/messages)", sum(gaps) == 0,
              missing=sum(gaps), threads_short=sum(1 for g in gaps if g))

    # Inbox: unread counts add up and the burst fans head each Creator's list.
    bad_unread, bad_order = [], 0
    for c in creators:
        rows = await manager.recent_chats(ctx.owner, c["id"], RECENT_MAX)
        mine = [t for t in targets if t["account_id"] == c["id"]]
        top = {r["withUser"]["id"] for r in rows[: len(mine)]}
        bad_order += len({t["id"] for t in mine} - top)
        unread = {r["withUser"]["id"]: r["unreadMessagesCount"] for r in rows}
        for t in mine:
            exp = seeded_unread.get((c["id"], t["id"]), 0) + per_fan
            if unread.get(t["id"]) != exp:
                bad_unread.append({"fan": t["id"], "got": unread.get(t["id"]), "want": exp})
    ctx.check("unreadMessagesCount == seeded + sent for every burst fan", not bad_unread,
              wrong=len(bad_unread), sample=bad_unread[:5])
    ctx.check("burst fans head their Creator's inbox", bad_order == 0, out_of_place=bad_order)

    routes = ctx.rec.summary()
    for route, budget in P95_MS.items():
        if route in routes:
            ctx.check(f"p95 {route} < {budget}ms", routes[route]["p95_ms"] < budget, budget=True,
                      p95=routes[route]["p95_ms"], n=routes[route]["n"])
        else:
            ctx.skip(f"p95 {route} < {budget}ms", "no samples")

    if not ctx.app:
        for n in (*UI_CHECKS, *notif_click.BROWSER_CHECKS, *notif_click.DESKTOP_CHECKS, *QR_CHECKS):
            ctx.skip(n, "--no-ui")
    else:
        async with ui.owner_browser(ctx) as page:
            await page.goto(f"{ctx.app}/messages-pro", wait_until="domcontentloaded")
            needle = f"slop dm {per_fan}/{per_fan}"
            try:
                await page.get_by_text(needle).first.wait_for(timeout=90_000)
                seen = True
            except Exception:
                seen = False
            path = await ui.shot(ctx, page, "messages-pro-inbox")
            rows = await page.get_by_text(needle).count()
            relay_5xx = [u for s, u in page.slop["statuses"] if s >= 500 and "/api/of/" not in u]
            ctx.metric("ui", {"url": page.url, "rows_with_burst_preview": rows, "screenshot": path,
                              "held_of_reads": len(page.slop["held_of_reads"]),
                              "offhost_aborted": len(page.slop["offhost_aborted"]), "5xx": relay_5xx[:10]})
            ctx.check(UI_CHECKS[0], seen and rows > 0, rows=rows, url=page.url)
            ctx.check(UI_CHECKS[1], not relay_5xx, count=len(relay_5xx))

        # Notification clicks: fans of the first Creator, quiet after the burst.
        c0 = creators[0]["id"]
        clicks = await notif_click.browser(ctx, c0, fans[c0])
        if ctx.param("desktop", 1):
            clicks += await notif_click.desktop(ctx, c0, fans[c0])
        else:
            for n in notif_click.DESKTOP_CHECKS:
                ctx.skip(n, "--set desktop=0")
        (ctx.out / "notif-click.json").write_text(json.dumps(clicks, indent=2, default=str))

        qr = await _quick_reply(ctx, creators, fans)
        (ctx.out / "quick-reply.json").write_text(json.dumps(qr, indent=2, default=str))


UI_CHECKS = ("Messages Pro Fan List shows the burst", "no 5xx in the browser session")
QR_EXACT = ("quick reply: OF got exactly one send, as the replied row's Creator to its Fan with the typed text, "
            "none to the other Creator's same Fan; the line is in that thread only (DB)")
QR_UI = "quick reply: the bell row's field takes the line and reads Sent; the other Creator's row still offers Reply"
QR_CHECKS = (QR_EXACT, QR_UI)
QR_ID_BASE = fan_dm.INJECT_ID_BASE + 888_000
SENT_JS = """() => { window.__slopQrSent = false; new MutationObserver(() => {
  if ([...document.querySelectorAll('[role=status]')].some((e) => e.textContent.trim() === 'Sent')) window.__slopQrSent = true;
}).observe(document.body, {subtree: true, childList: true, characterData: true}); }"""


def _plain(html: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


async def _quick_reply(ctx, creators: list[dict], fans: dict) -> dict:
    """The Messages Pro bell's quick reply (module docstring): one Fan, two Creators, Reply on the second's row."""
    a, b = creators[0]["id"], creators[1]["id"]
    used = {f["id"] for f in notif_click.distinct(fans[a])[:5]}  # notif_click's Fans
    fan = next((f for f in notif_click.distinct(fans[a]) if f["id"] not in used), None)
    if fan is None:
        for n in QR_CHECKS:
            ctx.check(n, False, reason="no Fan with a name of its own left after notif_click's five")
        return {}
    line = {a: f"slop qr dm to {a}", b: f"slop qr dm to {b}"}
    typed = "slop quick reply: only to this Creator"
    ids = iter(range(QR_ID_BASE, QR_ID_BASE + 100))
    got: dict = {"fan": fan["id"], "creators": [a, b], "replied_as": b, "typed": typed}

    async def sends() -> list[dict]:
        return (await ctx.owner.get("/__slop/fake/calls?sends=1")).json()["of_sends"]

    async def feed(r):  # declared bypass: OF's notifications feed empty, the rows are the DMs' own
        await r.fulfill(json={} if "/count" in r.request.url else {"list": [], "hasMore": False})

    async with ui.owner_browser(ctx, send=True) as page:
        await page.route("**/api/of/v2/users/notifications**", feed)
        await page.goto(f"{ctx.app}/messages-pro", wait_until="domcontentloaded")
        bell = page.get_by_role("button", name="Notifications").first
        await bell.wait_for(timeout=120_000)
        reply_btn = page.get_by_role("button", name="Reply", exact=True)
        rows = {c: page.locator("div").filter(has_text=line[c]).filter(has=reply_btn).last for c in (a, b)}
        got["dm_tries"] = 0
        for got["dm_tries"] in range(1, 4):   # a DM the transcoder fault drops is sent again (new id)
            for c in (a, b):
                await fan_dm.inject(ctx.owner, c, fan_dm.frame(next(ids), fan, line[c]))
            if await bell.get_attribute("aria-expanded") != "true":
                await bell.click()
            try:
                await rows[a].wait_for(timeout=20_000)
                await rows[b].wait_for(timeout=20_000)
                break
            except Exception:  # noqa: BLE001
                continue
        mark = len(await sends())   # no send of this step can have gone yet
        try:
            await rows[b].get_by_role("button", name="Reply", exact=True).click(timeout=10_000)
            field = rows[b].get_by_role("textbox", name=f"Reply to {fan['name']}")
            await field.wait_for(timeout=60_000)   # the field's module is lazy
            await field.fill(typed)
            got["trigger_png"] = await ui.shot(ctx, page, "quick-reply-trigger")
            await page.evaluate(SENT_JS)
            await rows[b].get_by_role("button", name="Send", exact=True).click()
            await page.wait_for_function("() => window.__slopQrSent", timeout=30_000)
            got["sent_seen"] = True
        except Exception as e:  # noqa: BLE001 — a step that cannot complete is the checks' FAIL
            got["error"] = f"{type(e).__name__}: {e}"[:400]
            got["sent_seen"] = await page.evaluate("() => !!window.__slopQrSent")
        # Settled: the replied row says who responded (chat_responded), the other Creator's still offers Reply.
        responded = page.locator("div").filter(has_text=line[b]).filter(has_text="has responded").last
        try:
            await responded.wait_for(timeout=15_000)
            got["replied_row_responded"] = True
        except Exception:  # noqa: BLE001
            got["replied_row_responded"] = False
        got["other_row_reply"] = await rows[a].get_by_role("button", name="Reply", exact=True).count() == 1
        got["settled_png"] = await ui.shot(ctx, page, "quick-reply-settled")
        await asyncio.sleep(1.0)  # a stray second send would have reached OF by now
        new = (await sends())[mark:]
    got["of_sends"] = new
    threads = {c: [m for m in await manager.thread_messages(ctx.owner, c, fan["id"]) if _plain(m.get("body")) == typed]
               for c in (a, b)}
    got["thread_rows"] = {c: [{k: m.get(k) for k in ("message_id", "direction", "body")} for m in ms]
                          for c, ms in threads.items()}
    exact = [s for s in new if str(s["account_id"]) == b and int(s["fan_id"]) == int(fan["id"])
             and _plain(s["text"]) == typed]
    ctx.check(QR_EXACT, len(new) == 1 and len(exact) == 1 and len(threads[b]) == 1 and not threads[a],
              sends=new, want={"account_id": b, "fan_id": fan["id"], "text": typed},
              thread_b=len(threads[b]), thread_a=len(threads[a]))
    ctx.check(QR_UI, "error" not in got and got["sent_seen"] and got["other_row_reply"],
              **{k: got.get(k) for k in ("error", "sent_seen", "other_row_reply", "replied_row_responded",
                                         "dm_tries", "trigger_png", "settled_png")})
    return got


def _p(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * q))]


def _pcts(xs: list[float]) -> dict:
    return {"p50": round(_p(xs, 0.5), 1), "p95": round(_p(xs, 0.95), 1), "max": round(max(xs), 1)} if xs else {}


def _pump_metrics(recs: list[dict], rate: float) -> dict:
    """Per Creator: frames, achieved frames/s, and (open loop) how far sends lagged their schedule."""
    out = {}
    for aid in sorted({r["account_id"] for r in recs}):
        rs = [r for r in recs if r["account_id"] == aid]
        span_s = (max(r["t1"] for r in rs) - min(r["t0"] for r in rs)) / 1000
        out[aid] = {"frames": len(rs), "achieved_per_s": round(len(rs) / span_s, 1) if span_s else None,
                    "relay_ms": _pcts([r["t1"] - r["t0"] for r in rs]),
                    **({"scheduled_per_s": rate, "lag_ms": _pcts([r["t0"] - r["due"] for r in rs])} if rate else {})}
    return out
