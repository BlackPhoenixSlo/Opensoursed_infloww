"""Help bot as a Siri-style box (spec D12; app/components/assistant/{prepass.ts, markers.ts, MarkerCards.tsx,
AssistantWidget.tsx}): plain commands run with no LLM call, and a figure the bot needs is a live card read with
the asker's own session, never a number the model wrote.

World: `agency_inbox`. Creator 0 (C) gets SALES ledger rows a few minutes before the build (SQL `transactions`,
amounts from `--seed`, whole dollars; the rollup triggers keep tx_hourly / tx_daily in step). The Agency has its
own DeepSeek key (PUT /admin/my-llm-keys). DeepSeek is lib/assistant_qa_relay.py's fake: REVENUE_Q -> a sentence
with a planted "$999 ... 999 sales" beside `[[data:revenue|today|this]]`, HOWTO_Q -> a how-to line.

Flow, the owner's browser, desktop 1440x900 (Q&A, not do-mode): /growth/auto-post, open the help bot, focus C.
"open settings" (`prepass-trigger` typed, `prepass-settled` on /settings with "Opened Settings."), "light mode",
"dark mode", HOWTO_Q, REVENUE_Q (`card-trigger` typed, `card-settled` with the card's figure). Then a chatter
(real invite + register, C assigned) on the built-in "chatter" role with enforcement on: its own browser, the bot,
REVENUE_Q (`chatter-card`).

Checks:
  prepass_navigates_no_llm        "open settings": URL on /settings, "Opened Settings." in the thread, no POST
                                  /admin/assistant/ask, no fake DeepSeek call
  prepass_question_falls_through  HOWTO_Q: one POST /admin/assistant/ask (200), one `deepseek:help_assistant` call,
                                  the fake's how-to in the thread
  prepass_theme                   "light mode" then "dark mode": <html data-theme> light then dark, each with its
                                  "Switched to ... mode." line; no ask, no fake call
  marker_card_shows_db_total      the card (Revenue · Today · This model) reads C (account_id) and shows
                                  fmtCents(SQL sum of C's tracked `transactions` in the card's own from/to window),
                                  which holds the seeded rows; the owner's API read of that URL sums the same
  figure_stripped                 the answer's text (the bubble minus its card) has no "$" and no PLANTED
  marker_not_in_history           REVENUE_Q's `assistant_turns` row is stored (with the marker), and the card's
                                  figure is in no stored turn and not in GET /admin/assistant/history
  marker_403_not_zero             the chatter's API read of the revenue window is 403, the card's own read 403,
                                  and the card says "Not available for your role", no "$"
  no_5xx                          no 5xx in either browser (OF's /api/of/ reads are held, left out)
Side effects: siri.json (seeded rows, SQL sum, card request, turns, chatter reads).

FAULT `assistant-marker-figure-kept` (client: markers.ts' strip of figures beside a data marker skipped):
figure_stripped alone.

Bypasses (declared): DeepSeek is the fake above (the answer text is canned; the strip, the card and its read are
the product's). No OF session: every /api/of/ read stays held in the browser (actors/ui). The theme pass starts
from whatever theme the page booted in ("light mode" first, so "dark mode" is always a switch). Not a volume path:
one owner, one chatter, a handful of commands.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

from slop.actors import ui
from slop.lib.assistant_qa_relay import HOWTO_Q, PLANTED, REVENUE_Q
from slop.lib.client import Http
from slop.seed import chatters, ts

PROFILE = "agency_inbox"
UI = True
FAULT = "assistant-marker-figure-kept"
DESKTOP = (1440, 900)
WAIT_MS = 120_000   # first visit of a page compiles it in next dev
START = "/growth/auto-post"
ASK, REV = "/admin/assistant/ask", "/admin/stats/revenue"
SALES = 4
TRACKED = ("cleared", "pending")
NOT_ALLOWED = "Not available for your role"
CARD_SEL = '[data-testid="assistant-data-card"]'
PANEL = '[data-look="messenger"]'

C_NAV, C_FALL, C_THEME, C_TOTAL, C_STRIP, C_HIST, C_403, C_5XX = (
    "prepass_navigates_no_llm", "prepass_question_falls_through", "prepass_theme", "marker_card_shows_db_total",
    "figure_stripped", "marker_not_in_history", "marker_403_not_zero", "no_5xx")

# Finite animations (the dock's pop in) done; a skeleton's endless pulse does not count.
_SETTLED = """() => document.getAnimations().filter((a) => a.playState === 'running'
  && a.effect && a.effect.getComputedTiming().iterations !== Infinity).length === 0"""
# The newest card has its figure (or its refusal): no "Loading…" left.
_CARD_DONE = f"""() => {{ const c = [...document.querySelectorAll('{CARD_SEL}')].pop();
  return !!c && !c.innerText.includes('Loading'); }}"""
# The newest card's answer bubble, its text without the card(s).
_ANSWER_TEXT = f"""(card) => {{ const b = card.closest('.rounded-bl-md')
  || [...document.querySelectorAll('{PANEL} .rounded-bl-md')].pop();
  if (!b) return null; const c = b.cloneNode(true);
  c.querySelectorAll('{CARD_SEL}').forEach((x) => x.remove()); return c.textContent; }}"""


def fmt_cents(c: int) -> str:
    """app/lib/format.ts fmtCents for a non-negative whole-dollar total: "$1,234"."""
    return f"${int(abs(c) / 100 + 0.5):,}"


def _seed_today(w, aid: str) -> list[dict]:
    """SALES tracked ledger rows on C, minutes before the build, whole dollars (no "999" in their total)."""
    rng = w.rng("siri-box")
    fans = [f["id"] for f in w.data["fans"][aid]]
    rows = []
    for i in range(SALES):
        cents = rng.randint(15, 140) * 100
        at = w.now - timedelta(minutes=2 + 3 * i)
        rows.append({"fan_id": rng.choice(fans), "kind": ("ppv_message", "tip")[i % 2], "amount_cents": cents,
                     "occurred_at": ts(at), "ptx": f"slop-siri-{w.seed}-{i}"})
    while PLANTED in fmt_cents(sum(r["amount_cents"] for r in rows)):
        rows[0]["amount_cents"] += 100
    con = w.sql()
    with con:
        con.executemany(
            "INSERT INTO transactions(account_id, fan_id, kind, amount_cents, currency, occurred_at, ingested_at, "
            "provider_transaction_id, status, net_cents, fee_cents, vat_cents, source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(aid, r["fan_id"], r["kind"], r["amount_cents"], "USD", r["occurred_at"], ts(w.now), r["ptx"], "pending",
              round(r["amount_cents"] * 0.8), r["amount_cents"] - round(r["amount_cents"] * 0.8), 0, "ledger")
             for r in rows])
    con.close()
    return rows


def _utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)


def _sql_sum(w, aid: str, frm: str, to: str) -> int:
    """C's tracked gross in [frm, to] (the card's own instants), straight off `transactions`."""
    con = w.sql()
    try:
        r = con.execute("SELECT COALESCE(SUM(amount_cents), 0) FROM transactions WHERE account_id=? AND status IN "
                        f"({','.join('?' * len(TRACKED))}) AND occurred_at >= ? AND occurred_at <= ?",
                        (aid, *TRACKED, ts(_utc(frm)), ts(_utc(to)))).fetchone()
    finally:
        con.close()
    return int(r[0])


def _turns(w) -> list[dict]:
    con = w.sql()
    try:
        rows = con.execute("SELECT id, user_id, chatter_id, account_id, role, question, answer, error, model "
                           "FROM assistant_turns ORDER BY id").fetchall()
    finally:
        con.close()
    return [dict(zip(("id", "user_id", "chatter_id", "account_id", "role", "question", "answer", "error", "model"), r))
            for r in rows]


async def _calls(ctx) -> dict:
    return dict((await ctx.owner.get("/__slop/fake/calls")).json().get("calls") or {})


def _delta(a: dict, b: dict) -> dict:
    return {k: b.get(k, 0) - a.get(k, 0) for k in set(a) | set(b) if b.get(k, 0) != a.get(k, 0)}


async def _shot(ctx, page, name: str) -> str:
    try:
        await page.wait_for_function(_SETTLED, timeout=15_000)
    except Exception:  # noqa: BLE001 — a shot of a page still moving beats none
        pass
    return await ui.shot(ctx, page, name)


async def _open_bot(page, nick: str | None) -> str | None:
    """Open the help bot (unfold it when tucked) and, given `nick`, focus it on that Creator; the focus label."""
    launcher = page.locator('button[aria-label="Help assistant"], button[aria-label="Show help assistant"]')
    await launcher.first.wait_for(timeout=WAIT_MS)
    tucked = page.get_by_role("button", name="Show help assistant", exact=True)
    if await tucked.count():
        await tucked.click()
    await page.get_by_role("button", name="Help assistant", exact=True).first.click(timeout=30_000)
    btn = page.locator('[aria-label^="Help bot focus: "]').first
    await btn.wait_for(timeout=30_000)
    if nick and await btn.get_attribute("aria-label") != f"Help bot focus: {nick}":
        await btn.click()
        await page.get_by_role("menuitemradio", name=re.compile(rf"^{re.escape(nick)}(?:\s|$)")).first.click()
    return await btn.get_attribute("aria-label")


async def _card(page) -> dict:
    """The newest data card once settled: its title, figure line, whole text, and its answer's text."""
    await page.wait_for_function(_CARD_DONE, timeout=60_000)
    card = page.locator(CARD_SEL).last
    ps = [x.strip() for x in await card.locator("p").all_inner_texts()]
    return {"title": ps[0] if ps else None, "value": ps[1] if len(ps) > 1 else None,
            "text": (await card.inner_text()).strip(), "answer_text": await card.evaluate(_ANSWER_TEXT)}


async def _owner_pass(ctx, aid: str, nick: str) -> dict:
    res: dict = {"shots": {}, "errors": []}
    async with ui.owner_browser(ctx, viewport=DESKTOP) as page:
        asks, revs = [], []

        def on_resp(r) -> None:
            path = urlsplit(r.url).path
            if r.request.method == "POST" and path.endswith(ASK):
                asks.append(r)
            elif r.request.method == "GET" and path.endswith(REV):
                revs.append(r)

        page.on("response", on_resp)
        page.context.set_default_navigation_timeout(WAIT_MS)
        try:
            # Warm /settings (its first compile) so the command's push lands within the wait.
            await page.goto(f"{ctx.app}/settings", wait_until="domcontentloaded")
            await page.goto(f"{ctx.app}{START}?creator={aid}", wait_until="domcontentloaded")
            res["focus"] = await _open_bot(page, nick)
            panel = page.locator(PANEL)
            box = page.get_by_placeholder("Ask a question…")

            # 1. "open settings": a command, no LLM.
            c0, n0 = await _calls(ctx), len(asks)
            await box.fill("open settings")
            res["shots"]["prepass_trigger"] = await _shot(ctx, page, "prepass-trigger")
            await box.press("Enter")
            await page.wait_for_url(re.compile(r"^https?://[^/]+/settings(?:[/?#]|$)"), timeout=WAIT_MS)
            await panel.get_by_text("Opened Settings.", exact=True).wait_for(timeout=30_000)
            await page.wait_for_timeout(1_500)   # an ask it would have sent is out by now
            res["nav"] = {"url": page.url, "asks": len(asks) - n0, "calls": _delta(c0, await _calls(ctx)),
                          "line": await panel.get_by_text("Opened Settings.", exact=True).count()}
            res["shots"]["prepass_settled"] = await _shot(ctx, page, "prepass-settled")

            # 2. Theme words: "light mode" then "dark mode" (so the second is always a switch).
            c0, n0 = await _calls(ctx), len(asks)
            steps = []
            for want in ("light", "dark"):
                before = await page.evaluate("() => document.documentElement.getAttribute('data-theme')")
                await box.fill(f"{want} mode")
                await box.press("Enter")
                await panel.get_by_text(f"Switched to {want} mode.", exact=True).wait_for(timeout=30_000)
                steps.append({"want": want, "before": before, "after": await page.evaluate(
                    "() => document.documentElement.getAttribute('data-theme')")})
            await page.wait_for_timeout(1_000)
            res["theme"] = {"steps": steps, "asks": len(asks) - n0, "calls": _delta(c0, await _calls(ctx))}
            res["shots"]["theme"] = await _shot(ctx, page, "prepass-theme")

            # 3. A question that names a page: the LLM's.
            c0, n0 = await _calls(ctx), len(asks)
            await box.fill(HOWTO_Q)
            await box.press("Enter")
            await panel.get_by_text("at the bottom of the sidebar").first.wait_for(timeout=60_000)
            res["howto"] = {"asks": [a.status for a in asks[n0:]], "calls": _delta(c0, await _calls(ctx)),
                            "url": page.url}

            # 4. The data marker: a live card, the model's figure stripped.
            n0, r0 = len(asks), len(revs)
            await box.fill(REVENUE_Q)
            res["shots"]["card_trigger"] = await _shot(ctx, page, "card-trigger")
            await box.press("Enter")
            res["card"] = await _card(page)
            res["shots"]["card_settled"] = await _shot(ctx, page, "card-settled")
            res["revenue_reads"] = [{"status": r.status, "url": r.url} for r in revs[r0:]]
            res["revenue_asks"] = []
            for a in asks[n0:]:
                try:
                    res["revenue_asks"].append({"status": a.status, "body": await a.json()})
                except Exception:  # noqa: BLE001
                    res["revenue_asks"].append({"status": a.status, "body": None})
        except Exception as e:  # noqa: BLE001 — the checks below say what was missing
            res["errors"].append(f"{type(e).__name__}: {str(e)[:300]}")
            res["shots"]["error"] = await ui.shot(ctx, page, "error-owner")
        res["statuses"] = list(page.slop["statuses"])
    return res


async def _chatter(ctx, w, aid: str) -> tuple[Http, dict]:
    """A chatter (real invite + register) working C, on the built-in "chatter" role, enforcement on."""
    name = f"{w.user_prefix}{w.seed}siri"
    got = (await chatters.seed(w, ctx.owner, w.user_id, [name], account_ids=[[aid]]))[0]
    emps = (await ctx.owner.get("/admin/employees")).json()["employees"]
    emp = next(e for e in emps if e.get("username") == name)
    cfg = (await ctx.owner.get("/admin/settings/roles")).json().get("config") or {}
    blob = {**cfg, "enforce": True, "assignments": {**(cfg.get("assignments") or {}), str(emp["id"]): "chatter"}}
    put = await ctx.owner.put("/admin/settings/roles", json=blob)
    http = Http(ctx.relay, ctx.rec)
    r = await http.post("/chatter/login", json={"username": name, "password": got["password"]})
    r.raise_for_status()
    return http, {"username": name, "employee_id": emp["id"], "roles_put": put.status_code}


async def _chatter_pass(ctx, http: Http, nick: str) -> dict:
    res: dict = {"shots": {}, "errors": []}
    async with ui.chatter_tab(ctx, http, ctx.app, viewport=DESKTOP) as page:
        revs = []

        def on_resp(r) -> None:
            if r.request.method == "GET" and urlsplit(r.url).path.endswith(REV):
                revs.append(r)

        page.on("response", on_resp)
        page.context.set_default_navigation_timeout(WAIT_MS)
        try:
            await page.goto(f"{ctx.app}/", wait_until="domcontentloaded")
            res["focus"] = await _open_bot(page, nick)
            box = page.get_by_placeholder("Ask a question…")
            await box.fill(REVENUE_Q)
            await box.press("Enter")
            res["card"] = await _card(page)
            res["shots"]["card"] = await _shot(ctx, page, "chatter-card")
            res["revenue_reads"] = [{"status": r.status, "url": r.url} for r in revs]
        except Exception as e:  # noqa: BLE001 — the check below says what was missing
            res["errors"].append(f"{type(e).__name__}: {str(e)[:300]}")
            res["shots"]["error"] = await ui.shot(ctx, page, "error-chatter")
        res["statuses"] = list(page.slop["statuses"])
    return res


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    c = w.data["creators"][0]
    aid, nick = c["id"], c.get("nickname") or c["id"]
    seeded = _seed_today(w, aid)
    r = await ctx.owner.put("/admin/my-llm-keys", json={"deepseek": "slop-fake-deepseek"})
    ctx.metric("agency_deepseek_key", {"status": r.status_code})
    if not ctx.app:
        for n in (C_NAV, C_FALL, C_THEME, C_TOTAL, C_STRIP, C_HIST, C_403, C_5XX):
            ctx.skip(n, "--no-ui")
        return

    o = await _owner_pass(ctx, aid, nick)
    shots = o["shots"]

    nav = o.get("nav") or {}
    ctx.check(C_NAV, bool(nav) and urlsplit(nav["url"]).path.startswith("/settings") and nav["line"] >= 1
              and nav["asks"] == 0 and not nav["calls"],
              **nav, errors=o["errors"], screenshots=[shots.get("prepass_trigger"), shots.get("prepass_settled")])

    th = o.get("theme") or {}
    steps = th.get("steps") or []
    ctx.check(C_THEME, len(steps) == 2 and steps[0]["after"] == "light" and steps[1]["before"] == "light"
              and steps[1]["after"] == "dark" and th["asks"] == 0 and not th["calls"],
              **th, errors=o["errors"], screenshots=[shots.get("theme")])

    ho = o.get("howto") or {}
    ctx.check(C_FALL, ho.get("asks") == [200] and ho.get("calls") == {"deepseek:help_assistant": 1},
              **ho, errors=o["errors"])

    card = o.get("card") or {}
    reads = o.get("revenue_reads") or []
    q = parse_qs(urlsplit(reads[-1]["url"]).query) if reads else {}
    frm, to = (q.get("from") or [None])[0], (q.get("to") or [None])[0]
    sql = _sql_sum(w, aid, frm, to) if frm and to else None
    api = None
    if reads:
        u = urlsplit(reads[-1]["url"])
        a = await ctx.owner.get(f"{u.path}?{u.query}")
        api = sum((x.get("total_cents") or 0) for x in (a.json().get("rows") or [])) if a.status_code == 200 else None
    seeded_cents = sum(x["amount_cents"] for x in seeded)
    ctx.check(C_TOTAL, sql is not None and sql >= seeded_cents > 0 and card.get("value") == fmt_cents(sql)
              and api == sql and (q.get("account_id") or [None])[0] == aid
              and card.get("title") == "Revenue · Today · This model" and reads[-1]["status"] == 200,
              card=card, sql_cents=sql, want=sql is not None and fmt_cents(sql), api_cents=api,
              seeded_cents=seeded_cents, window=[frm, to], reads=reads, errors=o["errors"],
              screenshots=[shots.get("card_trigger"), shots.get("card_settled")])

    text = card.get("answer_text")
    ctx.check(C_STRIP, text is not None and "$" not in text and PLANTED not in text and "[[" not in text,
              answer_text=text, planted=PLANTED, screenshots=[shots.get("card_settled")])

    turns = _turns(w)
    mine = [t for t in turns if t["question"] == REVENUE_Q and t["account_id"] == aid and t["chatter_id"] is None]
    value = card.get("value") or ""
    bare = value.lstrip("$")
    needles = [x for x in {value, bare, bare.replace(",", "")} if x]
    hist = await ctx.owner.get("/admin/assistant/history?limit=50")
    hist_text = hist.text if hist.status_code == 200 else ""
    leaks = [t["id"] for t in turns if any(n in f'{t["question"]}\n{t["answer"]}' for n in needles)]
    ctx.check(C_HIST, bool(mine) and "[[data:revenue|today|this]]" in (mine[-1]["answer"] or "") and bool(needles)
              and not leaks and hist.status_code == 200 and not any(n in hist_text for n in needles),
              rows=[{k: t[k] for k in ("id", "role", "answer", "error")} for t in mine], card_value=value,
              leaks=leaks, history_status=hist.status_code,
              ask_ids=[(a["body"] or {}).get("id") for a in o.get("revenue_asks") or []])

    http, who = await _chatter(ctx, w, aid)
    try:
        path = f"{REV}?from={frm}&to={to}&account_id={aid}&group_by=kind" if frm else f"{REV}?account_id={aid}"
        direct = await http.get(path, expect=(403,))
        ch = await _chatter_pass(ctx, http, nick)
    finally:
        await http.aclose()
    cc = ch.get("card") or {}
    ctext = cc.get("text") or ""
    creads = ch.get("revenue_reads") or []
    ctx.check(C_403, direct.status_code == 403 and bool(creads) and all(x["status"] == 403 for x in creads)
              and NOT_ALLOWED in ctext and "$" not in ctext,
              api_status=direct.status_code, api_body=direct.text[:200], card=cc, reads=creads, chatter=who,
              errors=ch["errors"], screenshots=[ch["shots"].get("card"), ch["shots"].get("error")])

    (ctx.out / "siri.json").write_text(json.dumps({
        "seeded": seeded, "sql_cents": sql, "api_cents": api, "window": [frm, to], "owner": {
            k: v for k, v in o.items() if k != "statuses"}, "chatter": {k: v for k, v in ch.items() if k != "statuses"},
        "turns": turns}, indent=2, ensure_ascii=False, default=str))
    ctx.metric("fake_calls", await _calls(ctx))
    bad = [(s, u) for s, u in o["statuses"] + ch["statuses"] if s >= 500 and "/api/of/" not in u]
    ctx.check(C_5XX, not bad, count=len(bad), sample=bad[:5])
