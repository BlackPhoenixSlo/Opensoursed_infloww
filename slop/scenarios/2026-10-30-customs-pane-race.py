from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import parse_qs, urlsplit

from slop.actors import ui
from slop.lib.customs_faults import API_B, CLEAR_PULL, CLEARED, CLIP_B, GATE, PANE_B, PULL_STALE, RACE
from slop.seed import customs

PROFILE = "agency_inbox"
UI = True
FAULT = "customs-pane-seq-unguarded"
VIEWPORT = (1440, 900)
WAIT_MS = 120_000
HOLD_A_S = 2.0
CHECKS = (RACE, GATE, PANE_B, CLIP_B, API_B, PULL_STALE, CLEAR_PULL, CLEARED)
KINDS = ("context", "order", "brief")


def _who(req, a: dict, b: dict) -> tuple[str | None, str | None]:
    u = urlsplit(req.url)
    kind = u.path.rsplit("/", 1)[-1]
    try:
        if u.path.startswith("/admin/messages/") and kind == "rescrape-now":
            kind, fan = "rescrape", int(u.path.rsplit("/", 2)[-2])
        elif u.path.startswith("/admin/customs/") and kind in KINDS:
            fan = (int(parse_qs(u.query).get("fan_id", ["0"])[0]) if req.method == "GET"
                   else int((req.post_data_json or {}).get("fan_id") or 0))
        else:
            return None, None
    except (ValueError, TypeError):
        return None, None
    return ("A" if fan == a["fan_id"] else "B" if fan == b["fan_id"] else None), kind


class _Timeline:

    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.events: list[dict] = []

    def now(self) -> float:
        return round(time.monotonic() - self.t0, 3)

    def add(self, who: str, kind: str, ev: str) -> None:
        self.events.append({"t": self.now(), "who": who, "kind": kind, "ev": ev})

    def seen(self, who: str, kinds: str | tuple[str, ...], ev: str, after: float = 0) -> list[dict]:
        kinds = (kinds,) if isinstance(kinds, str) else kinds
        return [e for e in self.events if e["who"] == who and e["kind"] in kinds and e["ev"] == ev
                and e["t"] > after]

    def answered(self, who: str, kinds: tuple[str, ...] = KINDS, after: float = 0) -> bool:
        return {e["kind"] for e in self.seen(who, kinds, "answered", after)} == set(kinds)

    async def until(self, pred, timeout_s: float, what: str) -> None:
        end = time.monotonic() + timeout_s
        while not pred():
            if time.monotonic() > end:
                raise TimeoutError(f"{what} not seen in {timeout_s}s; timeline={self.events}")
            await asyncio.sleep(0.05)


def _row(page, f: dict):
    return page.locator("tr").filter(has_text=f"@{f['username']}").first


def _pane(page):
    return page.locator("tr").filter(has=page.get_by_role("button", name="Copy handoff"))


async def _drive(ctx, w, page, a: dict, b: dict, chk) -> None:
    tl = _Timeline()
    gates = {"A": asyncio.Event(), "B": asyncio.Event()}
    pulls = (asyncio.Event(), asyncio.Event())

    async def hold(route):
        who, kind = _who(route.request, a, b)
        if who is None:
            return await route.fallback()
        tl.add(who, kind, "asked")
        if kind == "rescrape":
            await pulls[len(tl.seen(who, "rescrape", "asked")) - 1].wait()
        elif who == "A" or kind != "context":
            await gates[who].wait()
        tl.add(who, kind, "let_through")
        await route.fallback()

    def done(req):
        who, kind = _who(req, a, b)
        if who:
            tl.add(who, kind, "answered")

    page.on("requestfinished", done)
    await page.route("**/admin/customs/**", hold)
    await page.route("**/admin/messages/*/*/rescrape-now", hold)

    await page.goto(f"{ctx.app}/analytics/message-dashboard?tab=customs", wait_until="domcontentloaded")
    await _row(page, a).wait_for(timeout=WAIT_MS)
    await _row(page, b).wait_for(timeout=30_000)
    await _row(page, a).get_by_role("button", name="Read", exact=True).click()
    t_click_a = tl.now()
    await _row(page, b).get_by_role("button", name="Read", exact=True).click()
    t_click_b = tl.now()
    pane = _pane(page)
    copy = page.get_by_role("button", name="Copy handoff")
    await tl.until(lambda: tl.answered("B", ("context",)), 30, "B's context answered")
    await copy.wait_for(timeout=30_000)
    await page.wait_for_timeout(300)
    in_flight = {"disabled": await copy.is_disabled(), "title": await copy.get_attribute("title"),
                 "pane": await pane.inner_text()}
    await ui.shot(ctx, page, "trigger-b-in-flight")

    gates["B"].set()
    await tl.until(lambda: tl.answered("B"), 30, "B's order and brief answered")
    t_b_settled = tl.now()
    enabled_after_b = True
    try:
        await page.wait_for_function("(b) => b && !b.disabled", arg=await copy.element_handle(), timeout=10_000)
    except Exception:  # noqa: BLE001 — recorded as the gate check's FAIL
        enabled_after_b = False
    pane_before_a = await pane.inner_text()

    await asyncio.sleep(max(0.0, HOLD_A_S - (tl.now() - t_click_a)))
    gates["A"].set()
    await tl.until(lambda: tl.answered("A"), 30, "A's three replies answered")
    await page.wait_for_timeout(800)
    pane_after = await pane.inner_text()
    hide_rows = [await _row(page, f).get_by_role("button", name="Hide", exact=True).count() for f in (a, b)]
    await ui.shot(ctx, page, "settled-b-after-a-late")

    a_first = min(e["t"] for e in tl.seen("A", KINDS, "answered"))
    b_last = max(e["t"] for e in tl.seen("B", KINDS, "answered"))
    chk(RACE, t_click_a < t_click_b and a_first > b_last, click_a=t_click_a, click_b=t_click_b,
        b_settled=t_b_settled, a_first_answer=a_first, b_last_answer=b_last)
    chk(GATE, in_flight["disabled"] is True and enabled_after_b, in_flight_disabled=in_flight["disabled"],
        in_flight_title=in_flight["title"], enabled_after_b_settled=enabled_after_b)
    foreign = [s for s in (a["tag"], f"@{a['username']}", a["call"]) if s in pane_after]
    chk(PANE_B, b["tag"] in pane_after and not foreign and pane_after == pane_before_a and hide_rows == [0, 1],
        b_tag_shown=b["tag"] in pane_after, a_data_shown=foreign, changed_by_a_late=pane_after != pane_before_a,
        hide_buttons_a_b=hide_rows, pane=pane_after[:1500])

    clip = ""
    if await copy.is_enabled():
        await copy.click()
        await page.get_by_text("Copied", exact=True).wait_for(timeout=5_000)
        clip = await page.evaluate("navigator.clipboard.readText()")
        await pane.screenshot(path=str(ctx.out / "screenshots" / "copied-b-pane.png"))
    (ctx.out / "clipboard.txt").write_text(clip)
    foreign = [s for s in (a["tag"], f"@{a['username']}", f"-account: {a['account_name']}", a["call"]) if s in clip]
    want = [f"-username: @{b['username']}", f"-account: {b['account_name']}", b["tag"], f"-call him: {b['call']}"]
    missing = [s for s in want if s not in clip]
    chk(CLIP_B, bool(clip) and not missing and not foreign, missing=missing, a_data=foreign, clipboard=clip)

    r = await ctx.owner.get(f"/admin/customs/order?account_id={b['account_id']}&fan_id={b['fan_id']}")
    order_b = r.json()
    (ctx.out / "order-b.json").write_text(json.dumps(order_b, indent=2))
    texts = [ln["text"] for ln in order_b.get("lines") or [] if ln.get("text")]
    absent = [t for t in texts if t not in pane_after]
    chk(API_B, r.status_code == 200 and len(texts) >= 3 and all(b["tag"].lower() in t.lower() for t in texts)
        and not absent and a["tag"] not in pane_after, http_status=r.status_code, api_lines=texts,
        api_lines_missing_from_pane=absent)

    await _pull_after_reopen(ctx, page, a, b, chk, tl, pulls[0])
    await _sent_mid_pull(ctx, w, page, a, b, chk, tl, pulls[1])
    (ctx.out / "timeline.json").write_text(json.dumps(tl.events, indent=2))
    ctx.metric("customs_timeline", tl.events)


async def _pull_after_reopen(ctx, page, a: dict, b: dict, chk, tl: _Timeline, pull_gate: asyncio.Event) -> None:
    await _row(page, a).get_by_role("button", name="Pull", exact=True).click()
    await tl.until(lambda: tl.seen("A", "rescrape", "asked"), 10, "A's rescrape asked")
    t_hide = tl.now()
    await _row(page, b).get_by_role("button", name="Hide", exact=True).click()
    await _row(page, b).get_by_role("button", name="Read", exact=True).click()
    await tl.until(lambda: tl.answered("B", after=t_hide), 30, "B's reopen answered")
    t_release = tl.now()
    async with page.expect_response(lambda r: r.url.endswith("/rescrape-now")) as got:
        pull_gate.set()
    rescrape = await (await got.value).json()
    (ctx.out / "rescrape-a.json").write_text(json.dumps(rescrape, indent=2))
    await _row(page, a).get_by_role("button", name="Pull", exact=True).wait_for(timeout=10_000)
    await page.wait_for_timeout(1_500)
    a_asked = tl.seen("A", KINDS, "asked", after=t_release)
    pane_pull = await _pane(page).inner_text()
    hide_pull = [await _row(page, f).get_by_role("button", name="Hide", exact=True).count() for f in (a, b)]
    await ui.shot(ctx, page, "pull-a-after-b-reopen")
    chk(PULL_STALE, rescrape.get("ok") is True and not a_asked and hide_pull == [0, 1]
        and b["tag"] in pane_pull and a["tag"] not in pane_pull,
        rescrape_ok=rescrape.get("ok"), a_asked_after_pull=a_asked, hide_buttons_a_b=hide_pull,
        b_tag_shown=b["tag"] in pane_pull, a_tag_shown=a["tag"] in pane_pull)


async def _sent_mid_pull(ctx, w, page, a: dict, b: dict, chk, tl: _Timeline, pull_gate: asyncio.Event) -> None:
    t_pull = tl.now()
    await _row(page, a).get_by_role("button", name="Pull", exact=True).click()
    await tl.until(lambda: tl.seen("A", "rescrape", "asked", after=t_pull), 10, "A's second rescrape asked")
    t_sent = tl.now()
    async with page.expect_response(lambda r: r.url.endswith("/admin/customs/clear")) as got_clear:
        await _row(page, a).get_by_role("button", name="Sent", exact=True).click()
    clear_status = (await got_clear.value).status
    a_row_gone = True
    try:
        await _row(page, a).wait_for(state="detached", timeout=10_000)
    except Exception:  # noqa: BLE001 — recorded as the CLEARED check's FAIL
        a_row_gone = False
    async with page.expect_response(lambda r: r.url.endswith("/rescrape-now")) as got:
        pull_gate.set()
    rescrape = await (await got.value).json()
    await page.wait_for_timeout(1_500)
    a_asked = tl.seen("A", KINDS, "asked", after=t_sent)
    pane = await _pane(page).inner_text() if await _pane(page).count() else ""
    hide_b = await _row(page, b).get_by_role("button", name="Hide", exact=True).count()
    await ui.shot(ctx, page, "sent-mid-pull")
    con = w.sql()
    try:
        owed_at, cleared_at = con.execute("SELECT customs_owed_at, customs_cleared_at FROM fans "
                                          "WHERE account_id=? AND fan_id=?", (a["account_id"], a["fan_id"])).fetchone()
    finally:
        con.close()
    listed = (await ctx.owner.get("/admin/customs")).json().get("customs") or []
    a_listed = [r for r in listed if r.get("account_id") == a["account_id"] and r.get("fan_id") == a["fan_id"]]
    (ctx.out / "cleared-a.json").write_text(json.dumps({
        "clear_status": clear_status, "rescrape": rescrape,
        "db_fans_a": {"customs_owed_at": owed_at, "customs_cleared_at": cleared_at},
        "get_admin_customs_rows_for_a": a_listed}, indent=2))
    chk(CLEAR_PULL, rescrape.get("ok") is True and not a_asked and a["tag"] not in pane,
        rescrape_ok=rescrape.get("ok"), a_asked_after_sent=a_asked, b_pane_open=hide_b == 1,
        b_tag_shown=b["tag"] in pane, a_tag_shown=a["tag"] in pane)
    chk(CLEARED, clear_status == 200 and owed_at is None and cleared_at is not None and not a_listed
        and a_row_gone, clear_status=clear_status, a_customs_owed_at=owed_at,
        a_customs_cleared_at=cleared_at, a_still_listed=bool(a_listed), a_row_gone_from_queue=a_row_gone)


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    a, b = customs.seed(w, 2)
    customs.write_of_truth(ctx.stack.tmp / "of-truth.jsonl", a)
    (await ctx.owner.put("/admin/my-llm-keys", json={"deepseek": "slop-fake-deepseek"})).raise_for_status()
    listed = (await ctx.owner.get("/admin/customs")).json().get("customs") or []
    ctx.metric("customs_rows", [{k: r.get(k) for k in ("account_id", "fan_id", "of_username", "tip_cents",
                                                      "tipped_at", "marked")} for r in listed])
    ctx.metric("customs_fans", [{k: str(v) for k, v in f.items()} for f in (a, b)])
    if ctx.app is None:
        for c in CHECKS:
            ctx.skip(c, "--no-ui")
        return
    done: set[str] = set()

    def chk(name: str, ok: bool, **detail) -> None:
        done.add(name)
        ctx.check(name, ok, **detail)

    async with ui.owner_browser(ctx, viewport=VIEWPORT) as page:
        await page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=ctx.app)
        try:
            await _drive(ctx, w, page, a, b, chk)
        except Exception as e:  # noqa: BLE001 — a UI step that cannot complete is its checks' FAIL
            try:
                await ui.shot(ctx, page, "failed-customs")
            except Exception:  # noqa: BLE001
                pass
            for c in CHECKS:
                if c not in done:
                    ctx.check(c, False, error=f"{type(e).__name__}: {e}"[:1200])
        ctx.metric("held_of_reads", len(page.slop["held_of_reads"]))
        ctx.metric("offhost_aborted", len(page.slop["offhost_aborted"]))
