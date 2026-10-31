"""Customs tab (Messages dashboard > Customs, `?tab=customs`): open row A, then row B before A's
replies are back. A's late thread / order / brief must never land in B's pane, Copy handoff must
stay disabled until B's brief and order have settled, and the copy must carry B's @username and
B's work order only. One owner, one browser (1440x900), `agency_inbox` (3 Creators) plus two owed
fans by SQL (`seed/customs.py`: A on Creator 0, B on Creator 1, A's tip older so A's row is first).
A race flow, not a volume one: `--users` and `--scale` change nothing, so no latency budget.

Timeline (held at the browser's wire by a page route, then let through to the relay unchanged):
  1. Read on A: A's GET /admin/customs/context, GET /admin/customs/order, POST /admin/customs/brief
     are all held.
  2. Read on B: B's context goes through; B's order and brief are held. Copy handoff shows (drawn
     with the pane) and must be disabled. Screenshot `trigger-b-in-flight`.
  3. B released: B's order and brief answer; Copy must turn enabled.
  4. A released (HOLD_A_S after the clicks at the earliest): A's three replies answer AFTER B's.
     Then B's pane must still be B's alone. Screenshot `settled-b-after-a-late`.
  5. Copy handoff clicked, the clipboard read back (permissions granted to the app's origin):
     B's @username, account and tag, nothing of A's. Side effects: the clipboard text
     (`clipboard.txt`), GET /admin/customs/order for B (`order-b.json`), the request timeline
     (`timeline.json`), all in the run folder; screenshot `copied-b-pane` (the whole pane, brief
     included, with "Copied").
  6. Pull on A (A's POST rescrape-now held), then Hide B and Read B: a NEWER open. B's three
     replies answer, then A's rescrape is let through and answers ok (OF's side of A's thread is
     `of-truth.jsonl`, so the product's real scrape runs). A must reopen nothing: no context,
     order or paid brief asked for A after it, B's pane still open and B's alone. Screenshot
     `pull-a-after-b-reopen`; the rescrape's answer is `rescrape-a.json`.
  7. (last: it settles A) Pull on A again (its rescrape held), then Sent on A: the real POST
     /admin/customs/clear, A's row leaves the queue. A's rescrape is let through and answers ok.
     A must reopen nothing: no context, order or paid brief asked for A after Sent, and no pane
     shows A (B's pane, still open, is recorded). Screenshot `sent-mid-pull`. Separately, the
     clear itself: its POST answered 200, A's `fans.customs_owed_at` (NULL now) read from the
     DB, and GET /admin/customs without A (side effect `cleared-a.json`).

Bypasses (declared): A's three requests and B's order + brief are HELD at the browser's wire
(a Playwright page route; nothing else about them changes) to make the race deterministic. The
brief's LLM call (DeepSeek) is answered by lib/customs_relay.py's loopback fake (0.4 s, a brief
in the product's schema read off the transcript the product built); no LLM key is real (the
Agency's key is `slop-fake-deepseek`, stored through the real PUT /admin/my-llm-keys) and the
guard refuses every off-host name. A's rescrape-now is HELD at the browser's wire too (then let
through unchanged); its OF read (`get_messages`) is lib/relay.py's, from `of-truth.jsonl` (A's
newest message, as OF holds it). Every other `/api/of/*`
read stays held (ui.py). Owed fans are SQL (seed/customs.py), as customs_watch + the transcoder
+ transaction_ingest leave them.

Fault (client side, lib/customs_faults.py): `customs-pane-seq-unguarded` drops the reducer's seq
guard, so A's late replies fill B's pane; only the pane, clipboard and API checks go red.
`customs-pull-reopens-stale` drops Pull's newer-open condition (`mayReopen`'s `paneMoved`), so
A's ok rescrape reopens A over B and asks for a paid brief; only the Pull check goes red.
`customs-clear-keeps-pull-reopen` drops Pull's fan-cleared condition (`fanCleared`), so A's ok
rescrape reopens the cleared A and asks for a paid brief; only the Sent-mid-Pull check goes red
(the clear's own side effects stay green).
"""
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
WAIT_MS = 120_000  # first visit of a page compiles it in next dev
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
    """Every held request (A's and B's customs reads, A's rescrape): asked, let through, answered."""

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
    # A's reads wait on "A", B's order + brief on "B" (B's context goes through). A's rescrapes
    # wait on their own gate each: the 1st (step 6) on pulls[0], the 2nd (step 7) on pulls[1]; no 3rd.
    gates = {"A": asyncio.Event(), "B": asyncio.Event()}
    pulls = (asyncio.Event(), asyncio.Event())

    async def hold(route):
        who, kind = _who(route.request, a, b)
        if who is None:
            return await route.fallback()
        tl.add(who, kind, "asked")
        if kind == "rescrape":
            await pulls[len(tl.seen(who, "rescrape", "asked")) - 1].wait()  # a 3rd: IndexError
        elif who == "A" or kind != "context":
            await gates[who].wait()
        tl.add(who, kind, "let_through")
        await route.fallback()  # the context route continues it to the relay

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
    await page.wait_for_timeout(800)  # React renders whatever A's replies dispatched
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
        await pane.screenshot(path=str(ctx.out / "screenshots" / "copied-b-pane.png"))  # the whole pane, brief too
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
    """Step 6: Pull on A (its rescrape held), then a newer open (Hide B, Read B) before it answers."""
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
    await _row(page, a).get_by_role("button", name="Pull", exact=True).wait_for(timeout=10_000)  # pullDone
    await page.wait_for_timeout(1_500)  # a reopen's three requests would be asked by now
    a_asked = tl.seen("A", KINDS, "asked", after=t_release)
    pane_pull = await _pane(page).inner_text()
    hide_pull = [await _row(page, f).get_by_role("button", name="Hide", exact=True).count() for f in (a, b)]
    await ui.shot(ctx, page, "pull-a-after-b-reopen")
    chk(PULL_STALE, rescrape.get("ok") is True and not a_asked and hide_pull == [0, 1]
        and b["tag"] in pane_pull and a["tag"] not in pane_pull,
        rescrape_ok=rescrape.get("ok"), a_asked_after_pull=a_asked, hide_buttons_a_b=hide_pull,
        b_tag_shown=b["tag"] in pane_pull, a_tag_shown=a["tag"] in pane_pull)


async def _sent_mid_pull(ctx, w, page, a: dict, b: dict, chk, tl: _Timeline, pull_gate: asyncio.Event) -> None:
    """Step 7: Pull on A (its rescrape held), Sent on A (the real clear), then the rescrape answers ok."""
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
    await page.wait_for_timeout(1_500)  # a reopen's three requests would be asked by now
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
    # B's pane is recorded, not required: under customs-pull-reopens-stale step 6 already replaced it
    # with A's, and this check must stay about step 7 alone.
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
    # The Agency's own DeepSeek key, through the real route (the brief bills the tenant's key, never a
    # platform one); it is fake, and only lib/customs_relay.py's loopback DeepSeek ever sees it.
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
