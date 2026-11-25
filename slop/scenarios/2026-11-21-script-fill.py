import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from slop.actors import ui
from slop.lib import nudenet_weights
from slop.lib.procmon import pct
from slop.lib.script_fill_faults import (
    DESCRIBE_BLOCKED, DESCRIBE_OFFER, DESCRIBE_REFUSED, FILL_ISOLATION, FILL_ONE_PRESS, FILL_READ_BACK, FILL_SEND,
    FILL_UNDO,
)
from slop.lib.vault_describe_relay import FAKE_KEY, arm_run
from slop.lib.vault_jev_relay import arm_jev, photo_sizes
from slop.seed import of_sessions, script_fill_vault as sfv

PROFILE = "agency_inbox"
UI = True
OF_WIRE = True
FAULT = "script-fill-skips-eligibility"
RELAY_ENV = {"NUDENET_640M_PATH": nudenet_weights.PATH}
VIEWPORT = (1440, 900)
WAIT_MS = 120_000
FILL = "/admin/saved-replies/fill"
PLAN, APPLY, UNDO = f"{FILL}/plan", f"{FILL}/apply", f"{FILL}/undo"
DESCRIBE = "/admin/vault-ai/describe-all"
STATUS = f"{DESCRIBE}/status"
DESCRIBE_TARGET = 1000
SEND_GAP_S = 3.5
SWEEP_TIMEOUT_S = 180
# every describe call answers no sooner than this (concurrency 8 >= C's 6 photos), so C's sweep is still running at the reopen; under llm_client's 120 s timeout
DESCRIBE_HOLD_S = 30.0
CAP_CENTS = 100
DIALOG = '[role="dialog"][aria-modal="true"]'
IMG = re.compile(r"/img(/scrub)?\?")
COMPOSER = 'Press "/" + keyword'
SENT_STEPS = (1, 3, 7)
CHECKS = (FILL_ONE_PRESS, FILL_READ_BACK, FILL_SEND, FILL_ISOLATION, FILL_UNDO, DESCRIBE_OFFER, DESCRIBE_BLOCKED,
          DESCRIBE_REFUSED)
APPLY_BUDGET_MS = 5000
PLAN_P95_MS = 3000
PLAN_SAMPLES = 10
CARDS_JS = r"""() => [...document.querySelectorAll('[aria-label^="Step "]')].map((e) => { const li = e.closest('li');
  return { label: e.textContent.trim(), tiles: li ? li.querySelectorAll('[data-media-id]').length : -1,
           price: li?.querySelector('[aria-label="Price"]')?.textContent?.trim() ?? null }; })"""



def _rows(w, aid: str, script: str | None = None) -> list[dict]:
    con = w.sql()
    try:
        q, args = "SELECT * FROM saved_replies WHERE account_id = ?", [aid]
        if script is not None:
            q, args = q + " AND script_id = ?", args + [script]
        cur = con.execute(q + " ORDER BY id", args)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()


def _ids(raw) -> list[int]:
    return [int(m["id"] if isinstance(m, dict) else m) for m in json.loads(raw or "[]")]


def _fmt_price(cents: int) -> str | None:
    if cents <= 0:
        return None
    return f"${cents / 100:,.{0 if cents % 100 == 0 else 2}f}"


def _want_cards(rows: list[dict]) -> dict[str, dict]:
    return {str(r["script_step"]): {"tiles": min(6, len(_ids(r["media_json"]))), "price": _fmt_price(r["price_cents"])}
            for r in rows}


def _cap(w, aid: str, on: bool) -> None:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    con = w.sql()
    with con:
        con.execute("INSERT OR IGNORE INTO account_ai_config (account_id, utc_offset, daily_cost_cap_cents) "
                    "VALUES (?,0,?)", (aid, CAP_CENTS))
        con.execute("UPDATE account_ai_config SET daily_cost_cap_cents = ? WHERE account_id = ?", (CAP_CENTS, aid))
        con.execute("DELETE FROM grok_daily_cost WHERE day = ? AND account_id = ? AND provider = 'describe'", (day, aid))
        if on:
            con.execute("INSERT INTO grok_daily_cost (day, account_id, provider, cost_cents, call_count, is_capped, "
                        "updated_at) VALUES (?,?,'describe',?,?,1,?)",
                        (day, aid, CAP_CENTS * 100, 40, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")))
    con.close()


async def _count(ctx) -> int:
    return (await ctx.owner.get("/__slop/vault-describe/count")).json()["n"]



POLL_S = 0.25


# page waits poll from Python, never page.wait_for_function: that polls on requestAnimationFrame and a predicate stayed false for 30 s over cards a single read gave as wanted
async def _poll(fn, timeout_s: float):
    t = time.monotonic()
    while True:
        try:
            v = await fn()
        except Exception:  # noqa: BLE001 — not readable yet: poll again
            v = None
        if v or time.monotonic() - t >= timeout_s:
            return v
        await asyncio.sleep(POLL_S)


async def _open(page, nickname: str, sequence: str, n_cards: int) -> None:
    await ui.pick_creator(page, nickname, timeout_ms=WAIT_MS)
    await page.get_by_role("tab", name="Sequence").click(timeout=WAIT_MS)
    await page.get_by_label("Search sequences").fill(sequence)
    row = page.locator('aside[aria-label="Sequences"] li div[role="button"]').filter(
        has=page.locator("span.truncate", has_text=re.compile(f"^{re.escape(sequence)}$")))
    await row.first.click(timeout=WAIT_MS)
    if not await _poll(lambda: page.evaluate(f"() => ({CARDS_JS})().length === {int(n_cards)}"), 60):
        raise TimeoutError(f"{sequence}: its {n_cards} step cards not shown within 60 s")


async def _scripts_state(page) -> dict:
    out: dict = {"url": page.url}
    try:
        out["sequence_aside"] = await page.locator('aside[aria-label="Sequences"]').count() > 0
        out["notice"] = await page.get_by_role("status", name="Fill notice").count() > 0
        out["headings"] = await page.locator("h2").all_inner_texts()
        out["creator"] = await page.get_by_test_id("of-creator-row").and_(
            page.locator("[aria-current='true']")).all_inner_texts()
    except Exception as e:  # noqa: BLE001 — evidence only
        out["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    return out


def _is(path: str, method: str = "POST"):
    return lambda r: r.request.method == method and urlsplit(r.url).path.endswith(path)


async def _press(page, scope=None) -> tuple[int, dict, float]:
    btn = (scope or page).get_by_role("button", name="Fill with content", exact=True).first
    t = time.monotonic()
    async with page.expect_response(_is(APPLY), timeout=60_000) as info:
        await btn.click(timeout=WAIT_MS)
    r = await info.value
    ms = (time.monotonic() - t) * 1000
    try:
        return r.status, await r.json(), ms
    except Exception:  # noqa: BLE001 — a non-JSON answer is the check's to report
        return r.status, {}, ms


async def _dialog(page, text: str, timeout_ms: int = 30_000) -> str:
    dlg = page.locator(DIALOG).last
    try:
        await dlg.filter(has_text=text).wait_for(timeout=timeout_ms)
    except Exception:  # noqa: BLE001 — the caller's check reports what it showed
        return ""
    return await dlg.inner_text()


async def _dialog_now(page) -> str:
    dlg = page.locator(DIALOG)
    return await dlg.last.inner_text() if await dlg.count() else ""


async def _close(page) -> None:
    dlg = page.locator(DIALOG).last
    await dlg.get_by_role("button", name=re.compile(r"^(Cancel|Close)$")).last.click(timeout=10_000)
    await page.locator(DIALOG).wait_for(state="detached", timeout=10_000)


async def _has_describe(page) -> bool:
    return await page.locator(DIALOG).get_by_role("button", name="Describe content", exact=True).count() > 0


async def _tiles(page) -> dict[str, int]:
    return {c["label"]: c["tiles"] for c in await page.evaluate(CARDS_JS)}


def _card_map(raw: list[dict]) -> dict[str, dict]:
    return {c["label"]: {"tiles": c["tiles"], "price": c["price"]} for c in raw}


async def _cards(page) -> dict[str, dict]:
    return _card_map(await page.evaluate(CARDS_JS))


async def _await_cards(page, want: dict, timeout_s: float = 30.0) -> dict:
    t, last = time.monotonic(), {}

    async def read() -> bool:
        raw = await page.evaluate(CARDS_JS)
        last.update(cards=_card_map(raw), elements=len(raw))
        return last["cards"] == want
    ok = bool(await _poll(read, timeout_s))
    return {"ok": ok, "cards": last.get("cards"), "waited_s": round(time.monotonic() - t, 1),
            "elements": last.get("elements")}



def _check_read_back(ctx, d: dict, before: list[dict], after: list[dict]) -> dict:
    fillable, decoys = set(d["fillable"]), set(d["decoys"].values())
    free_safe = {it["media_id"] for it in d["items"] if it["account_id"] == d["a"] and it["role"] == "free"}
    by0 = {r["id"]: r for r in before}
    written = {r["id"]: r for r in after if _ids(r["media_json"])}
    media = {m for r in written.values() for m in (*_ids(r["media_json"]), *_ids(r["previews_json"]))}
    bad = {}
    for r in after:
        r0, w = by0[r["id"]], r["id"] in written
        step, saved = r["script_step"], r0["price_cents"]
        why = []
        if w != (step in sfv.STEPS_A):
            why.append("written" if w else "not written")
        if w and not set(_ids(r["previews_json"])) <= (set(_ids(r["media_json"])) & free_safe):
            why.append("previews not free-safe media of the row")
        paid = step in sfv.STEPS_A and step != 1
        if w and not paid and not set(_ids(r["media_json"])) <= free_safe:
            why.append("free step holds non-free-safe media")
        if saved > 0 and r["price_cents"] != saved:
            why.append("saved price changed")
        if saved == 0 and w and paid and r["price_cents"] <= 0:
            why.append("paid step written without a price")
        if saved == 0 and (not w or not paid) and r["price_cents"] != 0:
            why.append("price on a free or unwritten row")
        if (r["updated_at"] != r0["updated_at"]) != w:
            why.append("updated_at bumped" if not w else "updated_at not bumped")
        if why:
            bad[step] = {"why": why, "media": _ids(r["media_json"]), "previews": _ids(r["previews_json"]),
                         "price": [saved, r["price_cents"]]}
    not_fillable = sorted(media - fillable)
    ctx.check(FILL_READ_BACK, bool(written) and not bad and not not_fillable and not (media & decoys),
              written={r["script_step"]: [_ids(r["media_json"]), _ids(r["previews_json"]), r["price_cents"]]
                       for r in written.values()},
              bad=bad, not_fillable=not_fillable, decoys_written=sorted(media & decoys), decoys=d["decoys"])
    return written


async def _send(ctx, chat, aid: str, fan, row: dict) -> dict:
    key = " ".join(row["text"].split())[:30]
    out: dict = {"step": row["script_step"], "id": row["id"]}

    def wire() -> list[dict]:
        with ctx.of_wire.lock:
            return [m for m in ctx.of_wire.sends.get(aid, []) if str(m["fan_id"]) == str(fan)]

    n0 = len(wire())
    try:
        composer = chat.get_by_placeholder(COMPOSER).first
        await composer.wait_for(timeout=WAIT_MS)
        await chat.get_by_title("Insert saved template").first.click(timeout=30_000)
        await chat.get_by_placeholder("Search templates…").fill(key)
        hit = chat.get_by_text(key).first
        await hit.wait_for(timeout=30_000)
        await hit.click()
        if not await _poll(lambda: chat.evaluate("(t) => [...document.querySelectorAll('textarea')].some((e) => "
                                                 "e.value.includes(t))", key), 15):
            raise TimeoutError(f"the composer never held {key!r} within 15 s")
        await composer.focus()
        async with chat.expect_response(lambda r: r.request.method == "POST" and bool(
                ui.SEND_PATH.fullmatch(urlsplit(r.url).path)), timeout=30_000) as info:
            await chat.keyboard.press("Enter")
        out["status"] = (await info.value).status
        t = time.monotonic()
        while len(wire()) <= n0 and time.monotonic() - t < 30:
            await asyncio.sleep(0.2)
    except Exception as e:  # noqa: BLE001 — the check reports it
        out["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    got = wire()
    out["body"] = got[n0].get("body") if len(got) > n0 else None
    return out


def _check_send(ctx, d: dict, written: dict, sends: list[dict]) -> None:
    decoys = set(d["decoys"].values())
    bad = {}
    for s in sends:
        r = written.get(s["id"])
        b = s.get("body") or {}
        if r is None:
            bad[s["step"]] = "row not written"
            continue
        sent_m, sent_p = sorted(int(m) for m in b.get("mediaFiles") or []), sorted(int(m) for m in b.get("previews") or [])
        want_m, want_p = sorted(_ids(r["media_json"])), sorted(_ids(r["previews_json"]))
        price = float(b.get("price") or 0)
        if s.get("error") or not s.get("status") or s["status"] >= 300 or not b:
            bad[s["step"]] = {"status": s.get("status"), "error": s.get("error"), "body": b}
        elif sent_m != want_m or sent_p != want_p or round(price * 100) != r["price_cents"] or set(sent_m) & decoys:
            bad[s["step"]] = {"sent": [sent_m, sent_p, price], "written": [want_m, want_p, r["price_cents"]],
                              "decoys": sorted(set(sent_m) & decoys)}
    steps = {s["step"] for s in sends if s.get("body")}
    paid_with_preview = any(_ids(written[s["id"]]["previews_json"]) for s in sends if s["id"] in written
                            and written[s["id"]]["price_cents"] > 0)
    ctx.check(FILL_SEND, steps == set(SENT_STEPS) and not bad and paid_with_preview, bad=bad,
              sends=[{k: s.get(k) for k in ("step", "status", "error", "body")} for s in sends])


async def _flow_a(ctx, page, d: dict, creators: dict, out: dict) -> None:
    w, a = ctx.world, d["a"]
    n_cards = len(d["rows"][a])
    before = _rows(w, a, sfv.SEQUENCE)
    fan = next((t["fan_id"] for t in w.data["threads"] if str(t["account_id"]) == a), None)
    one: dict = {}
    marked = False
    try:
        if fan is not None:
            # warm the chat route first: its first next-dev compile with the Scripts tab open reloaded that tab and a reload loses the Fill notice by design
            warm = await page.context.new_page()
            try:
                await ui.accept_confirms(warm)
                await warm.goto(f"{ctx.app}/messages-pro/{a}/{fan}", wait_until="domcontentloaded")
                await warm.get_by_placeholder(COMPOSER).first.wait_for(timeout=WAIT_MS)
            finally:
                await warm.close()
        await page.goto(f"{ctx.app}/growth/scripts", wait_until="domcontentloaded")
        await _open(page, creators[a]["nickname"] or a, sfv.SEQUENCE, n_cards)
        out["shots"]["fill-trigger"] = await ui.shot(ctx, page, "fill-trigger")
        one["http_status"], body, one["apply_ms"] = await _press(page)
        one["plan_status"] = body.get("status")
        out["apply_ms"] = one["apply_ms"]
        out["apply"] = {"status": one["http_status"], "plan_status": one["plan_status"],
                        "written": len(body.get("applied") or [])}
        notice = page.get_by_role("status", name="Fill notice")
        await notice.wait_for(timeout=30_000)
        one["notice"] = (await notice.inner_text()).split("·")[0].strip()
        after = _rows(w, a, sfv.SEQUENCE)
        want_cards = _want_cards(after)
        seen = await _await_cards(page, want_cards)
        one["cards"], one["want_cards"] = seen["cards"], want_cards
        one["cards_waited_s"], one["card_elements"] = seen["waited_s"], seen["elements"]
        if not seen["ok"]:
            one["cards_error"] = "the cards did not match the written rows within 30 s"
        one["dialog"] = await _dialog_now(page)
        out["shots"]["fill-filled"] = await ui.shot(ctx, page, "fill-filled")
        await page.evaluate("() => { window.__slopFillMark = 1; }")
        marked = True
    except Exception as e:  # noqa: BLE001 — the checks report it
        one["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        after = _rows(w, a, sfv.SEQUENCE)
    written = {r["id"]: r for r in after if _ids(r["media_json"])}
    n = len({m for r in written.values() for m in (*_ids(r["media_json"]), *_ids(r["previews_json"]))})
    m = len({r["script_step"] for r in written.values()})
    one["want_notice"] = f"Added {n} item{'' if n == 1 else 's'} to {m} step{'' if m == 1 else 's'}"
    ctx.check(FILL_ONE_PRESS, not one.get("error") and one.get("http_status") == 200
              and one.get("plan_status") == "ok" and bool(written) and one.get("notice") == one["want_notice"]
              and not one.get("dialog") and not one.get("cards_error") and one.get("cards") == one.get("want_cards"),
              **one)
    written = _check_read_back(ctx, d, before, after)

    sends: list[dict] = []
    chat = await page.context.new_page()
    await ui.accept_confirms(chat)
    try:
        if fan is None:
            raise RuntimeError(f"no seeded thread for Creator A {a}")
        await chat.goto(f"{ctx.app}/messages-pro/{a}/{fan}", wait_until="domcontentloaded")
        by_step = {r["script_step"]: r for r in after}
        for k, step in enumerate(SENT_STEPS):
            if k:
                await asyncio.sleep(SEND_GAP_S)
            sends.append(await _send(ctx, chat, a, fan, by_step[step]))
            await chat.wait_for_timeout(500)
            name = "send-free" if step == 1 else f"send-paid-step{step}"
            out["shots"][name] = await ui.shot(ctx, chat, name)
    except Exception as e:  # noqa: BLE001 — the check reports it
        sends.append({"step": None, "id": None, "error": f"{type(e).__name__}: {str(e)[:200]}"})
    finally:
        await chat.close()
    _check_send(ctx, d, written, sends)

    undo: dict = {"reloaded": None, "reopened": False}
    notice = page.get_by_role("status", name="Fill notice")
    try:
        await page.bring_to_front()
        if marked:
            undo["reloaded"] = not await page.evaluate("() => window.__slopFillMark === 1")
        try:
            await notice.wait_for(timeout=5_000)
        except Exception:  # noqa: BLE001 — not on screen: open A + the Sequence again
            undo["notice_gone"] = await _scripts_state(page)
            await _open(page, creators[a]["nickname"] or a, sfv.SEQUENCE, n_cards)
            undo["reopened"] = True
            await notice.wait_for(timeout=10_000)
        async with page.expect_response(_is(UNDO), timeout=60_000) as info:
            await notice.get_by_role("button", name="Undo", exact=True).click(timeout=10_000)
        r = await info.value
        undo["status"], undo["body"] = r.status, await r.json()
        await notice.wait_for(state="detached", timeout=30_000)
        undo["want_cards"] = _want_cards(_rows(w, a, sfv.SEQUENCE))
        seen = await _await_cards(page, undo["want_cards"])
        undo["cards"], undo["cards_waited_s"], undo["card_elements"] = seen["cards"], seen["waited_s"], seen["elements"]
        undo["tiles"] = {k: v["tiles"] for k, v in (seen["cards"] or {}).items()}
        if not seen["ok"]:
            raise TimeoutError("the cards did not match the undone rows within 30 s")
        out["shots"]["fill-undo-restored"] = await ui.shot(ctx, page, "fill-undo-restored")
    except Exception as e:  # noqa: BLE001 — the check reports it
        undo["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        undo["at_failure"] = await _scripts_state(page)
        try:
            out["shots"]["fill-undo-failed"] = await ui.shot(ctx, page, "fill-undo-failed")
        except Exception as e2:  # noqa: BLE001 — evidence only
            undo["shot_error"] = f"{type(e2).__name__}: {str(e2)[:200]}"
        if "tiles" not in undo:
            try:
                undo["tiles"] = await _tiles(page)
            except Exception:  # noqa: BLE001 — no cards readable: the check fails on empty tiles
                undo["tiles"] = {}
    back = _rows(w, a, sfv.SEQUENCE)
    by0 = {r["id"]: r for r in before}
    left = {r["script_step"]: [_ids(r["media_json"]), _ids(r["previews_json"]), by0[r["id"]]["price_cents"],
                               r["price_cents"]]
            for r in back if r["media_json"] != "[]" or r["previews_json"] != "[]"
            or r["price_cents"] != by0[r["id"]]["price_cents"]}
    ctx.check(FILL_UNDO, not undo.get("error") and undo.get("status") == 200 and bool(written)
              and not (undo.get("body") or {}).get("kept") and not left
              and all(v == 0 for v in undo.get("tiles", {}).values()) and bool(undo.get("tiles")),
              left=left, undo=undo, saved_price_step5=next((r["price_cents"] for r in back if r["script_step"] == 5), None))



async def _flow_c(ctx, page, d: dict, creators: dict, out: dict) -> None:
    w, c = ctx.world, d["c"]
    rows0 = _rows(w, c, sfv.SHORT_SEQUENCE)
    posts: list[dict] = []
    plans: list[int] = []

    def on_response(r) -> None:
        if _is(DESCRIBE)(r):
            posts.append({"status": r.status, "body": r.request.post_data})
        elif _is(PLAN)(r):
            plans.append(r.status)
    page.on("response", on_response)

    async def plan_api() -> dict:
        r = await ctx.owner.post(f"{PLAN}?account_id={c}", json={"sequence": sfv.SHORT_SEQUENCE})
        return r.json() if r.status_code == 200 else {"http": r.status_code, "text": r.text[:200]}

    blocked: dict = {}
    try:
        await page.goto(f"{ctx.app}/growth/scripts", wait_until="domcontentloaded")
        await _open(page, creators[c]["nickname"] or c, sfv.SHORT_SEQUENCE, len(d["rows"][c]))
        _cap(w, c, True)
        p = await plan_api()
        blocked["plan_status"] = p.get("status")
        blocked["blocked_reason"] = (p.get("describe") or {}).get("blocked_reason")
        n_posts, n0 = len(posts), await _count(ctx)
        blocked["apply"], body, _ = await _press(page)
        blocked["apply_status"] = body.get("status")
        blocked["text"] = await _dialog(page, blocked["blocked_reason"] or "\x00")
        blocked["describe_button"] = await _has_describe(page)
        out["shots"]["describe-blocked"] = await ui.shot(ctx, page, "describe-blocked")
        await _close(page)
        blocked["posts"], blocked["calls"] = posts[n_posts:], await _count(ctx) - n0
    except Exception as e:  # noqa: BLE001 — the check reports it
        blocked["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    ctx.check(DESCRIBE_BLOCKED, not blocked.get("error") and blocked.get("apply") == 200
              and blocked.get("plan_status") == "not_enough_content"
              and bool(blocked.get("blocked_reason")) and blocked["blocked_reason"] in blocked.get("text", "")
              and blocked.get("describe_button") is False and not blocked.get("posts") and blocked.get("calls") == 0
              and _rows(w, c, sfv.SHORT_SEQUENCE) == rows0, **blocked)

    refused: dict = {}
    try:
        _cap(w, c, False)
        n_plans = len(plans)
        refused["apply"], body, _ = await _press(page)
        refused["apply_status"] = body.get("status")
        refused["offer"] = await _dialog(page, "Describe content first?")
        t0 = time.monotonic()
        while len(plans) <= n_plans and time.monotonic() - t0 < 10:
            await asyncio.sleep(0.2)
        await page.wait_for_timeout(300)
        refused["describe_button"] = await _has_describe(page)
        _cap(w, c, True)
        n0 = await _count(ctx)
        async with page.expect_response(_is(DESCRIBE), timeout=60_000) as info:
            await page.locator(DIALOG).get_by_role("button", name="Describe content", exact=True).click(timeout=10_000)
        r = await info.value
        refused["http_status"] = r.status
        try:
            refused["sentence"] = ((await r.json()).get("detail") or {}).get("blocked_reason")
        except Exception:  # noqa: BLE001 — no JSON: no sentence, the check fails
            refused["sentence"] = None
        refused["text"] = await _dialog(page, refused["sentence"] or "\x00")
        out["shots"]["describe-refused"] = await ui.shot(ctx, page, "describe-refused")
        await _close(page)
        refused["calls"] = await _count(ctx) - n0
    except Exception as e:  # noqa: BLE001 — the check reports it
        refused["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    text = refused.get("text", "")
    ctx.check(DESCRIBE_REFUSED, not refused.get("error") and refused.get("apply") == 200
              and "Describe content first?" in refused.get("offer", "")
              and refused.get("describe_button") is True and refused.get("http_status") == 429
              and bool(refused.get("sentence")) and refused["sentence"] in text
              and not any(s in text for s in ("{", "daily_cap_reached", '"error"')) and refused.get("calls") == 0
              and _rows(w, c, sfv.SHORT_SEQUENCE) == rows0, **refused)

    offer: dict = {"applies": []}
    try:
        _cap(w, c, False)
        st, body, _ = await _press(page)
        offer["applies"].append([st, body.get("status")])
        offer["offer"] = await _dialog(page, "Describe content first?")
        offer["describe_button"] = await _has_describe(page)
        out["shots"]["describe-offer"] = await ui.shot(ctx, page, "describe-offer")
        n0 = await _count(ctx)
        async with page.expect_response(_is(DESCRIBE), timeout=60_000) as info:
            await page.locator(DIALOG).get_by_role("button", name="Describe content", exact=True).click(timeout=10_000)
        r = await info.value
        t_start = time.monotonic()
        offer["start"] = {"status": r.status, "body": r.request.post_data_json}
        offer["running_text"] = await _dialog(page, "Describing content")
        await _close(page)
        offer["running_at_reopen"] = (await ctx.owner.get(f"{STATUS}?account_id={c}")).json().get("running")
        st, body, _ = await _press(page)
        offer["applies"].append([st, body.get("status")])
        offer["progress"] = await _dialog(page, "Keeps going if you close this.")
        offer["reopen_s"] = round(time.monotonic() - t_start, 1)
        out["shots"]["describe-progress"] = await ui.shot(ctx, page, "describe-progress")
        t0 = time.monotonic()
        while time.monotonic() - t0 < SWEEP_TIMEOUT_S:
            s = (await ctx.owner.get(f"{STATUS}?account_id={c}")).json()
            p = s.get("progress") or {}
            if not s.get("running") and p.get("total") and p.get("done") == p.get("total"):
                offer["sweep"] = p
                break
            await asyncio.sleep(1)
        offer["ready"] = await _dialog(page, "Ready to fill.", timeout_ms=90_000)
        offer["rows_unchanged_until_press"] = _rows(w, c, sfv.SHORT_SEQUENCE) == rows0
        out["shots"]["describe-ready"] = await ui.shot(ctx, page, "describe-ready")
        offer["calls"] = await _count(ctx) - n0
        st, body, _ = await _press(page, page.locator(DIALOG).last)
        offer["applies"].append([st, body.get("status")])
        await page.get_by_role("status", name="Fill notice").wait_for(timeout=30_000)
        seen = await _await_cards(page, _want_cards(_rows(w, c, sfv.SHORT_SEQUENCE)))
        offer["filled_cards"], offer["filled_cards_ok"] = seen["cards"], seen["ok"]
        out["shots"]["describe-filled"] = await ui.shot(ctx, page, "describe-filled")
    except Exception as e:  # noqa: BLE001 — the check reports it
        offer["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    filled = {r["script_step"]: _ids(r["media_json"]) for r in _rows(w, c, sfv.SHORT_SEQUENCE)}
    offer["filled"] = filled
    start = offer.get("start") or {}
    applies = offer["applies"]
    offer["hold_s"] = hold_s = ctx.param("llm_latency_s", DESCRIBE_HOLD_S)
    ctx.check(DESCRIBE_OFFER, not offer.get("error") and "Describe content first?" in offer.get("offer", "")
              and offer.get("describe_button") is True and start.get("status") == 200
              and (start.get("body") or {}).get("target") == DESCRIBE_TARGET
              and bool(offer.get("running_text")) and offer.get("running_at_reopen") is True
              and "Keeps going if you close this." in offer.get("progress", "")
              and offer.get("reopen_s") is not None and offer["reopen_s"] < hold_s
              and bool(offer.get("sweep")) and "Ready to fill." in offer.get("ready", "")
              and offer.get("calls", 0) > 0 and offer.get("rows_unchanged_until_press") is True
              and len(applies) == 3 and all(a == [200, "not_enough_content"] for a in applies[:2])
              and applies[2] == [200, "ok"] and bool(filled.get(max(sfv.SHORT_STEPS))), **offer)



async def _plan_budget(ctx, a: str) -> None:
    lat = []
    for _ in range(PLAN_SAMPLES):
        t = time.monotonic()
        r = await ctx.owner.post(f"{PLAN}?account_id={a}", json={"sequence": sfv.SEQUENCE})
        if r.status_code == 200:
            lat.append((time.monotonic() - t) * 1000)
    p95 = pct(lat) if lat else None
    ctx.check(f"p95 POST {PLAN} (serial, {PLAN_SAMPLES}) < {PLAN_P95_MS}ms", p95 is not None and len(lat) == PLAN_SAMPLES
              and p95 < PLAN_P95_MS, budget=True, p95=p95, n=len(lat))


async def run(ctx) -> None:
    if os.environ.get("SLOP_LIVE") == "1":
        for c in CHECKS:
            ctx.skip(c, "SLOP_LIVE=1: this scenario runs on the DeepInfra / TypeSafe fakes only")
        return
    await asyncio.to_thread(nudenet_weights.ensure)
    w = await ctx.build(PROFILE)
    creators = {c["id"]: c for c in w.data["creators"]}
    of_sessions.seed(w, w.data["creators"])
    r = await ctx.owner.put("/admin/my-llm-keys", json={"deepinfra": FAKE_KEY})
    ctx.metric("agency_deepinfra_key", {"status": r.status_code})
    d = sfv.plan(w, w.data["creators"])
    photo_sizes(d["short_new"])
    armed = await arm_run(ctx.owner, ctx.stack.tmp, d["short_new"], ctx.param("llm_latency_s", DESCRIBE_HOLD_S))
    await arm_jev(ctx.owner, ctx.stack.tmp, d["short_new"], ctx.param("jev_latency_s", 0.1))
    await sfv.seed(w, armed)
    with ctx.of_wire.lock:
        for aid in (d["a"], d["c"]):
            mine = [sfv.of_media(it) for it in d["items"] if it["account_id"] == aid]
            ctx.of_wire.vault_media[aid] = sorted(mine, key=lambda m: m["createdAt"], reverse=True)
            ctx.of_wire.vault[aid] = {m["id"]: m for m in mine}
    jev = (await ctx.owner.get(f"{DESCRIBE}/plan?account_id={d['c']}")).json().get("jev") or {}
    if not jev.get("ready"):
        raise RuntimeError(f"slop: Jev not ready on the relay: {jev}")
    b_rows = _rows(w, d["b"])
    ctx.metric("script_fill_seed", {"items": len(d["items"]), "fillable": len(d["fillable"]), "decoys": d["decoys"],
                                    "short_new": [[it["media_id"], it["jev"]] for it in d["short_new"]]})
    applied: dict = {}
    if ctx.app is None:
        for c in CHECKS:
            if c != FILL_ISOLATION:
                ctx.skip(c, "--no-ui: every Fill check is a press on the Scripts page")
        r = await ctx.owner.post(f"{APPLY}?account_id={d['a']}", json={"sequence": sfv.SEQUENCE})
        applied = {"status": r.status_code, "plan_status": r.json().get("status") if r.status_code == 200 else None,
                   "written": len(r.json().get("applied") or []) if r.status_code == 200 else 0}
    else:
        out: dict = {"shots": {}}
        async with ui.owner_browser(ctx, viewport=VIEWPORT, send=True) as page:
            await page.context.add_init_script(
                f"try {{ localStorage.setItem('of-owner:{d['a']}', '{int(d['a'])}'); }} catch (e) {{}}")
            await page.context.route(IMG, lambda r: r.abort())
            await _flow_a(ctx, page, d, creators, out)
            await _flow_c(ctx, page, d, creators, out)
        if "apply_ms" in out:
            ctx.check(f"POST {APPLY} (A's press, as the browser saw it) < {APPLY_BUDGET_MS}ms",
                      out["apply_ms"] < APPLY_BUDGET_MS, budget=True, ms=round(out["apply_ms"], 1))
        else:
            ctx.check(f"POST {APPLY} (A's press, as the browser saw it) < {APPLY_BUDGET_MS}ms", False, budget=True,
                      error="the press never answered")
        ctx.metric("screenshots", out["shots"])
        applied = out.get("apply") or {}
    after = _rows(w, d["b"])
    ctx.check(FILL_ISOLATION, applied.get("status") == 200 and applied.get("plan_status") == "ok"
              and applied.get("written", 0) > 0 and bool(b_rows) and after == b_rows, a_apply=applied,
              rows=len(b_rows), changed=[r["id"] for r, s in zip(after, b_rows) if r != s][:5],
              count=[len(b_rows), len(after)])
    await _plan_budget(ctx, d["a"])
