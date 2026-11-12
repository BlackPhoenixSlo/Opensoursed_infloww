"""Daily AI spend limit, set in dollars on Settings > AI keys (2026-11-11; app/components/settings/AiSpendCapCard.tsx,
aiSpendCap.ts; service/account_config_{api,rules}.py; llm_client.spend_today). The owner raises one Creator's
`account_ai_config.daily_cost_cap_cents` mid-day; llm_client reads it per call, so the next AI call over the old cap
but under the new one must go through, and no other Creator's limit moves.

World: `agency_inbox`. SQL seed per Creator: an account_ai_config row at the default 100 cents ($1/day) and today's
(UTC) `grok_daily_cost` row for provider deepseek at 10_000 millicents (= the $1 cap, the row llm_client itself
writes). The agency's DeepSeek key is set through the real PUT /admin/my-llm-keys. The AI call is Copilot's
POST /admin/copilot/{account}/{fan}/suggest (deepseek-v4-flash, one reservation of ~25 millicents).

Flow: every Creator's suggest -> 429 (at the cap). Desktop 1440x900: /settings/ai-keys, the card shows $1.00 and
today's DeepSeek spend; type 5.00 (`ai-cap-trigger`), Save limit -> Saved (`ai-cap-settled`). The card's Creator is
the one its GET /admin/account-config asked for (scope, else the first). Suggest for that Creator -> 200; the others
stay 429. Phone 390x844 (touch): same page, 7.50 -> Saved (`ai-cap-trigger-phone`, `ai-cap-settled-phone`).
Concurrent reads: ctx.users owners GET /admin/account-config (now also sums today's spend) at once.
--no-ui: the limit moves through the same PUT the card sends (the config echoed + the cap); the UI checks skip.

Checks: lib/ai_cap_faults.py (C_REFUSED, C_UI, C_DB, C_ADMIT, C_SCOPED, C_PHONE, C_5XX) + C_READS [budget].

Bypasses (declared): DeepSeek is lib/ai_cap_relay.py's fake at its HTTP wire (llm_client's key lookup, cap
reservation and cost rows are the product's). Today's spend is seeded by SQL into the row llm_client writes, not
earned by 400 real calls. A run straddling 00:00 UTC would see a fresh day (spend 0); not guarded. Not a volume path.

FAULT `ai-cap-ui-sends-dollars-as-cents` (client: dollarsToCents drops its x100): C_DB and C_ADMIT alone.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from slop.actors import ui
from slop.lib.ai_cap_faults import C_5XX, C_ADMIT, C_DB, C_PHONE, C_REFUSED, C_SCOPED, C_UI
from slop.seed import ts

PROFILE = "agency_inbox"
UI = True
FAULT = "ai-cap-ui-sends-dollars-as-cents"
DESKTOP = (1440, 900)
PHONE = (390, 844)
WAIT_MS = 120_000          # first visit of /settings compiles it in next dev
CAP_CENTS = 100            # the column default, $1/day
SPENT_MC = CAP_CENTS * 100  # millicents: today's DeepSeek spend = the cap
DESKTOP_RAW, DESKTOP_CENTS = "5.00", 500
PHONE_RAW, PHONE_CENTS = "7.50", 750
READS_P95_MS = 1_500       # guess: a settings read with one extra grouped select, ctx.users at once
C_READS = f"--users concurrent GET /admin/account-config (capped at 50) all 200, p95 <= {READS_P95_MS} ms"
CFG = "/admin/account-config"
BOX = "Daily AI spend limit in dollars"


def _suggest_path(w, aid: str) -> str:
    return f"/admin/copilot/{aid}/{int(w.data['fans'][aid][0]['id'])}/suggest"


async def _suggest(ctx, w, aid: str):
    return await ctx.owner.post(_suggest_path(w, aid), json={"mode": "casual"})


async def _copilot_calls(ctx) -> int:
    return int(((await ctx.owner.get("/__slop/fake/calls")).json().get("calls") or {}).get("deepseek:copilot", 0))


def _caps(w) -> dict[str, int | None]:
    con = w.sql()
    try:
        return {r[0]: r[1] for r in con.execute("SELECT account_id, daily_cost_cap_cents FROM account_ai_config")}
    finally:
        con.close()


async def _put_cap(ctx, aid: str, cents: int):
    """--no-ui: the card's own PUT (the stored config echoed, the cap replaced)."""
    cfg = (await ctx.owner.get(f"{CFG}?account_id={aid}")).json()["config"]
    return await ctx.owner.put(CFG, json={"account_id": aid, "config": {**cfg, "daily_cost_cap_cents": cents}})


async def _ui_pass(ctx, tag: str, viewport, touch: bool, raw: str) -> dict:
    """Open the card, read it, type `raw`, save. Returns what the page showed and asked for."""
    out: dict = {"tag": tag, "asked": [], "errors": []}
    suffix = "" if tag == "desktop" else "-phone"
    async with ui.owner_browser(ctx, viewport=viewport, touch=touch) as page:
        def on_resp(r):
            u = urlsplit(r.url)
            if u.path.endswith(CFG) and r.request.method == "GET":
                out["asked"] += parse_qs(u.query).get("account_id", [])
        page.on("response", on_resp)
        try:
            await page.goto(f"{ctx.app}/settings/ai-keys", wait_until="domcontentloaded")
            box = page.get_by_label(BOX)
            await box.wait_for(timeout=WAIT_MS)
            await box.scroll_into_view_if_needed()
            out["shown"] = await box.input_value()
            out["spend"] = (await page.get_by_test_id("ai-cap-spend").text_content() or "").strip()
            await box.fill(raw)
            await ui.shot(ctx, page, f"ai-cap-trigger{suffix}")
            save = page.get_by_role("button", name="Save limit")
            out["layout"] = await page.evaluate("""([b, s]) => {
              const box = document.querySelector(`[aria-label="${b}"]`).getBoundingClientRect();
              const btn = [...document.querySelectorAll('button')].find((x) => x.textContent.trim() === s);
              const r = btn && btn.getBoundingClientRect();
              return { overflow: document.documentElement.scrollWidth - innerWidth, vw: innerWidth,
                       box: [box.left, box.right], save: r ? [r.left, r.right] : null };
            }""", [BOX, "Save limit"])
            await save.click()
            await page.get_by_text("Saved", exact=True).wait_for(timeout=30_000)
            out["saved"] = True
        except Exception as e:  # noqa: BLE001 — a missing element fails its check, never the run
            out["errors"].append(f"{type(e).__name__}: {str(e)[:200]}")
            out["saved"] = False
        await page.wait_for_timeout(500)
        await ui.shot(ctx, page, f"ai-cap-settled{suffix}")
        out["statuses"] = list(page.slop["statuses"])
    return out


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    creators = [c["id"] for c in w.data["creators"]]
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    con = w.sql()
    with con:
        for aid in creators:
            con.execute("INSERT OR IGNORE INTO account_ai_config (account_id, utc_offset, daily_cost_cap_cents) "
                        "VALUES (?,0,?)", (aid, CAP_CENTS))
            con.execute("UPDATE account_ai_config SET daily_cost_cap_cents=? WHERE account_id=?", (CAP_CENTS, aid))
            con.execute("INSERT OR REPLACE INTO grok_daily_cost (day, account_id, provider, cost_cents, call_count, "
                        "is_capped, updated_at) VALUES (?,?,?,?,?,?,?)",
                        (day, aid, "deepseek", SPENT_MC, 400, 0, ts(now.replace(tzinfo=None))))
    con.close()
    r = await ctx.owner.put("/admin/my-llm-keys", json={"deepseek": "slop-fake-deepseek"})
    ctx.metric("agency_deepseek_key", {"status": r.status_code, "day_utc": day})

    statuses: list = []
    before = [(aid, (await _suggest(ctx, w, aid)).status_code) for aid in creators]
    calls0 = await _copilot_calls(ctx)
    ctx.check(C_REFUSED, bool(before) and all(s == 429 for _, s in before) and calls0 == 0,
              statuses=before, copilot_calls=calls0)

    passes: list[dict] = []
    if ctx.app is None:
        target = creators[0]
        r1 = await _put_cap(ctx, target, DESKTOP_CENTS)
        db1 = _caps(w).get(target)
        statuses += [(r1.status_code, CFG)]
    else:
        passes.append(await _ui_pass(ctx, "desktop", DESKTOP, False, DESKTOP_RAW))
        asked = passes[0]["asked"]
        target = asked[-1] if asked else creators[0]
        db1 = _caps(w).get(target)
    ctx.metric("target", {"account": target, "picked_from": "card GET" if passes and passes[0]["asked"] else "creators[0]"})

    after = await _suggest(ctx, w, target)
    calls1 = await _copilot_calls(ctx)
    body = after.json() if after.status_code == 200 else {"detail": after.text[:200]}
    ctx.check(C_ADMIT, after.status_code == 200 and len(body.get("suggestions") or []) == 3 and calls1 - calls0 == 1,
              http_status=after.status_code, body=body, copilot_calls=calls1 - calls0, cap_cents=db1)

    others = [aid for aid in creators if aid != target]
    caps = _caps(w)
    still = [(aid, caps.get(aid), (await _suggest(ctx, w, aid)).status_code) for aid in others]
    ctx.check(C_SCOPED, all(c == CAP_CENTS and s == 429 for _, c, s in still), others=still)

    if ctx.app is None:
        r2 = await _put_cap(ctx, target, PHONE_CENTS)
        statuses += [(r2.status_code, CFG)]
        db2 = _caps(w).get(target)
        for c in (C_UI, C_PHONE, C_5XX):
            ctx.skip(c, "--no-ui")
    else:
        passes.append(await _ui_pass(ctx, "phone", PHONE, True, PHONE_RAW))
        db2 = _caps(w).get(target)
        d, p = passes
        ctx.check(C_UI, all(x["saved"] and x.get("shown") for x in passes) and d["shown"] == "1.00"
                  and "DeepSeek $1.00" in (d.get("spend") or "") and target in p["asked"],
                  **{x["tag"]: {k: x.get(k) for k in ("shown", "spend", "saved", "errors", "asked")} for x in passes})
        lay = p.get("layout") or {}
        vw = lay.get("vw") or PHONE[0]
        inside = lambda lr: bool(lr) and lr[0] >= 0 and lr[1] <= vw  # noqa: E731
        ctx.check(C_PHONE, lay.get("overflow", 1) <= 0 and inside(lay.get("box")) and inside(lay.get("save")),
                  layout=lay, errors=p["errors"])
        statuses += [st for x in passes for st in x["statuses"]]
        bad = [(s, u) for s, u in statuses if s >= 500 and "/api/of/" not in u]
        ctx.check(C_5XX, not bad, count=len(bad), sample=bad[:5])
    ctx.check(C_DB, db1 == DESKTOP_CENTS and db2 == PHONE_CENTS, desktop=db1, phone=db2,
              want=[DESKTOP_CENTS, PHONE_CENTS])

    # Concurrent reads of the settings GET (it now also sums today's spend).
    n = max(1, min(int(ctx.users or 1), 50))

    async def one():
        t = time.perf_counter()
        rr = await ctx.owner.get(f"{CFG}?account_id={target}")
        return rr.status_code, (time.perf_counter() - t) * 1000

    res = await asyncio.gather(*(one() for _ in range(n)))
    ms = sorted(m for _, m in res)
    p95 = ms[min(len(ms) - 1, int(0.95 * len(ms)))]
    ctx.metric("reads", {"n": n, "p95_ms": round(p95, 1), "max_ms": round(ms[-1], 1)})
    ctx.check(C_READS, all(s == 200 for s, _ in res) and p95 <= READS_P95_MS, budget=True,
              n=n, p95_ms=round(p95, 1), statuses=sorted({s for s, _ in res}))
