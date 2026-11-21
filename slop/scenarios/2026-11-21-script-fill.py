"""Growth > Scripts' "Fill with content" (service/script_fill_api.py fill/plan, fill/apply, fill/undo; the button, the
Fill notice and the Fill dialog in app/components/growth/ScriptsPage.tsx / ScriptFillDialog.tsx), on the real path:
one press fills a Sequence from the Creator's own described vault, and the filled steps really send.

World: `agency_inbox` (one Agency, 3 Creators at small) plus seed/script_fill_vault.py (its docstring has the rows):
  A  the Fill Creator: Sequence "Slop Fill S1" (a freebie, two unpriced ppv steps, a "2 pics" step saved at $25, the
     rest bridges) over a vault (one WHITE Shoot) of Fillable items (solo readings, Rungs, a $99 OF-list folder price
     on its explicit clip, free-safe stills) and three decoys that rank first in that Shoot but are not Fillable: a
     partner clip, a Jev-held photo, a photo in the standard REVIEW folder.
  B  the same-named Sequence with saved prices (the Agency's template prices for A) and no vault: never written.
  C  the short vault: Sequence "Slop Fill Short" (a freebie, one ppv step) over two described free-safe stills and
     six photos never described, each armed with a Jev answer (bare vulva / topless) and an ok describe answer.
The Agency's DeepInfra key is a dummy set through Setup > Keys (`PUT /admin/my-llm-keys`), as the describe sweep's.

Flow (one owner browser, `send` let through; a second tab of the same context is the chat):
  1. A: Scripts > Sequence > "Slop Fill S1", press "Fill with content" (screenshots fill-trigger, fill-filled).
     FILL_ONE_PRESS: apply 200 `ok`, no dialog, the notice "Added N items to M steps" (N, M from the DB; singular
     at 1), every step card shows its row's media tiles (`data-media-id`, at most 6) and price (`fmtPrice` of the
     DB's `price_cents`, none at 0). FILL_READ_BACK: the rows as the DB holds them (module checks; a free step's
     media free-safe stills only).
  2. Chat tab, A's first Fan: the template picker sends step 1 (free), step 3 (paid photos + a free preview) and
     step 7 (paid clip), 3.5 s apart (OnlyFans' send gap, app/lib/sendGuards.ts). FILL_SEND reads lib/of_wire.py's
     recorded send bodies (`ctx.of_wire.sends[A]`): mediaFiles == the row's media, previews == its previews, price ==
     its price in dollars, no decoy anywhere (screenshots send-free, send-paid).
  3. Back on the Scripts tab, the notice's Undo. FILL_UNDO: every row's media / previews empty again, every price
     back to its saved value (the $25 kept, the prices Fill set zeroed), no card shows a tile (fill-undo-restored).
     The notice off screen: a reload (a page mark gone, `reloaded`) fails it, the notice being lost by design; else
     A + the Sequence are opened again and it must come back (`reopened`). A failure shoots fill-undo-failed.
  4. C, "Slop Fill Short":
     DESCRIBE_BLOCKED  today's describe cap row at the cap (SQL, as 2026-11-11-ai-daily-cap writes it) before the
                       press: the dialog carries the plan's `describe.blocked_reason` (POST fill/plan), no Describe
                       button, no describe-all POST, no fill write (describe-blocked).
     DESCRIBE_REFUSED  cap row gone, the press offers "Describe content first?"; the cap row is written back, then
                       Describe: describe-all answers 429 and the dialog shows its `blocked_reason`, no JSON, no
                       describe call (describe-refused).
     DESCRIBE_OFFER    cap row gone, the press offers again (describe-offer); Describe starts describe-all with
                       target 1000; the dialog is closed and the button pressed again while the sweep runs: the
                       reopened dialog shows its progress (describe-progress) within DESCRIBE_HOLD_S of the start
                       (no describe call answers sooner); the sweep settles to "Ready to fill." (describe-ready)
                       with C's rows untouched; the dialog's Fill then fills step 2 (describe-filled).
  FILL_ISOLATION (last): A's apply answered 200 `ok` with writes (the press; `--no-ui`: one POST fill/apply), and
  B's saved_replies rows are byte-equal to the seed's.
Budgets (this file): POST fill/apply as the browser saw it (A's press) and POST fill/plan p95 over PLAN_SAMPLES
serial owner reads of A's plan.

Bypasses (declared):
  - DeepInfra and TypeSafe are lib/vault_describe_relay.py's and lib/vault_jev_relay.py's loopback fakes, armed for
    C's six photos only (outcome ok; a Jev profile each), stills seeded into the stores the arm answers, NudeNet the
    product's (`NUDENET_640M_PATH`); describe calls wait `--set llm_latency_s=` (DESCRIBE_HOLD_S, 30 s: the
    fake has no release-on-demand hold, so this fixed wait is the hold that keeps the sweep running through the
    reopen; real describe calls take ~14 s: time stretched, declared).
  - OnlyFans is lib/of_wire.py (`OF_WIRE`, seed/of_sessions.py): the relay's real OFClient sends there; its vault
    page and by-id reads hold A's and C's seeded media.
  - The describe cap rows (`grok_daily_cost` provider describe, `account_ai_config` cap) are written and deleted by
    SQL: what a spent day leaves, and what midnight UTC clears.
  - The browser aborts `/img` (card and composer thumbnails through the account's OF CDN; not this flow).
  - next dev compiles a route on its first visit: a throwaway tab opens A's chat before the Scripts tab, so the
    chat tab's first visit does not compile with the Scripts tab open (it reloaded it once, losing the notice).
  - The vault rows are SQL (seed/script_fill_vault.py), never a collect.
  - Template prices: B is A's only sibling with the Sequence, so step 3 borrows B's $15 (script_fill_api
    `_template_prices`); A's plan ends ok: $15, the saved $25, then step 7 at its $99 folder price.

Break-it-once: `script-fill-skips-eligibility` (lib/script_fill_faults.py: Phase 1's `fillable` passes every item)
puts A's partner clip on step 7: FILL_READ_BACK and FILL_SEND go red. By construction: the partner clip's reading is
A+13's but for `people_count` / `partner_visible`, so the two tie on every `vault_scripts._script_sort_key` element
but the last (`media_id`, A+14 > A+13), the partner clip tops the pool's clips, and `script_fill_decide._track` gives
the last paid Step (a clip ask: the video alone) the top clip. Proven offline (no relay) with `plan_from_vault` over
these seeded rows: without the fault step 3 = [A+2 pv, A+4] at $15 (`no_video`: two clips, three paid Steps, the
earliest yields), step 5 = [A+3 pv, A+11, A+12, A+8] at $25, step 7 = [A+13] at $99; with it step 7 = [A+14] at $50,
step 5 takes the Jev-held photo (A+15, a $50 paid candidate under the fault, its `read_lane5`) and A+13, step 3 takes
A+8, step 1 unchanged; C's plan stays not_enough_content (its undescribed rows have no reading, so no Fillable paid
item), so the DESCRIBE_* checks do not move. The REVIEW-folder decoy cannot flip (full_ai_sell.load_rows drops its
member before the gate).
"""
# No `from __future__ import annotations`: lib/cli.py loads a scenario outside sys.modules.
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
WAIT_MS = 120_000          # a page's first visit compiles it in next dev
FILL = "/admin/saved-replies/fill"
PLAN, APPLY, UNDO = f"{FILL}/plan", f"{FILL}/apply", f"{FILL}/undo"
DESCRIBE = "/admin/vault-ai/describe-all"
STATUS = f"{DESCRIBE}/status"
DESCRIBE_TARGET = 1000     # service/vault_ai_vision_decide.DESCRIBE_TARGET (the dialog's start body)
SEND_GAP_S = 3.5           # app/lib/sendGuards.ts SEND_GAP_MS (3 s) plus slack
SWEEP_TIMEOUT_S = 180
# The describe fake's per-call wait (`--set llm_latency_s=`), the hold that keeps C's sweep running through the reopen:
# `_DESCRIBE_CONCURRENCY` 8 >= C's 6 photos, so every call starts at once and none answers before HOLD_S, and the
# sweep cannot settle earlier (Jev's pass runs before them). DESCRIBE_OFFER requires the reopen's progress text
# within HOLD_S of the start (`reopen_s`), so it never passes on timing luck. Under llm_client's 120 s timeout.
DESCRIBE_HOLD_S = 30.0
CAP_CENTS = 100            # C's daily AI cap ($1); the cap row spends all of it (grok_daily_cost is in millicents)
DIALOG = '[role="dialog"][aria-modal="true"]'
IMG = re.compile(r"/img(/scrub)?\?")
COMPOSER = 'Press "/" + keyword'
SENT_STEPS = (1, 3, 7)     # a free step, a paid photo step with a free preview, the paid clip step
CHECKS = (FILL_ONE_PRESS, FILL_READ_BACK, FILL_SEND, FILL_ISOLATION, FILL_UNDO, DESCRIBE_OFFER, DESCRIBE_BLOCKED,
          DESCRIBE_REFUSED)
# Latency budgets. Guesses (no green run yet): the apply route plans one 13-step Sequence over 16 vault rows and
# writes 4 rows; the plan route is the same read without the write. Both are a few hundred ms on a dev box; these
# catch a gross regression (a whole-vault scan per Option, a lock wait), not drift.
APPLY_BUDGET_MS = 5000
PLAN_P95_MS = 3000
PLAN_SAMPLES = 10
# Every card's step label (ScriptsParts.tsx `aria-label="Step N"`, the bare step: scriptsPageState.sequenceSteps), the
# media tiles it shows (MediaStrip.tsx `data-media-id`, at most 6) and its price (`aria-label="Price"`, `fmtPrice`).
CARDS_JS = r"""() => [...document.querySelectorAll('[aria-label^="Step "]')].map((e) => { const li = e.closest('li');
  return { label: e.textContent.trim(), tiles: li ? li.querySelectorAll('[data-media-id]').length : -1,
           price: li?.querySelector('[aria-label="Price"]')?.textContent?.trim() ?? null }; })"""


# ── DB reads ───────────────────────────────────────────────────────────

def _rows(w, aid: str, script: str | None = None) -> list[dict]:
    """`saved_replies` rows of `aid` (of one Sequence), every column, by id."""
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
    """A card's price as app/lib/format.ts `fmtPrice` writes it ("$15", "$10.50", "$1,200"); None: no price shown
    (ScriptsParts.tsx renders it only when the row's price > 0)."""
    if cents <= 0:
        return None
    return f"${cents / 100:,.{0 if cents % 100 == 0 else 2}f}"


def _want_cards(rows: list[dict]) -> dict[str, dict]:
    """{step label: {tiles, price}} the cards must show for these rows (one Option per step)."""
    return {str(r["script_step"]): {"tiles": min(6, len(_ids(r["media_json"]))), "price": _fmt_price(r["price_cents"])}
            for r in rows}


def _cap(w, aid: str, on: bool) -> None:
    """Today's (UTC) describe cap row for `aid`: at the cap (`on`) or gone."""
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


# ── page helpers ───────────────────────────────────────────────────────

# Page waits poll from Python (`_poll`), never `page.wait_for_function`: that one polls on the page's
# requestAnimationFrame, and in run 20261121T064847Z its FILL_ONE_PRESS predicate stayed false for 30 s over cards
# that CARDS_JS, read once right after, gave exactly as wanted (the rows had refetched 12 ms after apply). A wait and
# its check now read the same reduction (`_card_map`).
POLL_S = 0.25


async def _poll(fn, timeout_s: float):
    """`await fn()` every POLL_S until it is truthy or `timeout_s` passed: its last value. A throw (the page mid
    navigation) counts as not yet."""
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
    """Scripts > the Creator > Sequence tab > `sequence` from the sidebar, its `n_cards` step cards shown."""
    await ui.pick_creator(page, nickname, timeout_ms=WAIT_MS)
    await page.get_by_role("tab", name="Sequence").click(timeout=WAIT_MS)
    await page.get_by_label("Search sequences").fill(sequence)
    row = page.locator('aside[aria-label="Sequences"] li div[role="button"]').filter(
        has=page.locator("span.truncate", has_text=re.compile(f"^{re.escape(sequence)}$")))
    await row.first.click(timeout=WAIT_MS)
    if not await _poll(lambda: page.evaluate(f"() => ({CARDS_JS})().length === {int(n_cards)}"), 60):
        raise TimeoutError(f"{sequence}: its {n_cards} step cards not shown within 60 s")


async def _scripts_state(page) -> dict:
    """What the Scripts tab shows, for a failure's evidence: its URL, whether the Sequence sidebar and the Fill notice
    are there, the headings (the open Sequence's name) and the picked Creator."""
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
    """Press "Fill with content" (the header's, or `scope`'s): apply's (status, body, ms)."""
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
    """The open Fill dialog's text once it contains `text` ("" if it never does)."""
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
    """Poll the step cards (`_card_map`) until they equal `want` or `timeout_s` passed: {ok, cards, waited_s,
    elements}. `elements`: how many `[aria-label^="Step "]` elements there were, so a second one per label (which the
    map hides) shows in the evidence."""
    t, last = time.monotonic(), {}

    async def read() -> bool:
        raw = await page.evaluate(CARDS_JS)
        last.update(cards=_card_map(raw), elements=len(raw))
        return last["cards"] == want
    ok = bool(await _poll(read, timeout_s))
    return {"ok": ok, "cards": last.get("cards"), "waited_s": round(time.monotonic() - t, 1),
            "elements": last.get("elements")}


# ── A: one press, read back, send, undo ────────────────────────────────

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
    """Pick `row` in the composer's template picker by its text and send it: the relay's answer and the body the
    fake OnlyFans recorded for it."""
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
    one: dict = {}   # FILL_ONE_PRESS's detail: no key a check reserves (lib/report.py: name, ok, status, budget, reason)
    marked = False   # the Scripts tab carries `window.__slopFillMark` (a reload drops it: FILL_UNDO's `reloaded`)
    try:
        if fan is not None:
            # next dev compiles a route on its first visit; in run 20261121T064847Z the chat route's first compile,
            # with the Scripts tab open, reloaded that tab (its /events stream dropped as GET /messages-pro compiled)
            # and a reload loses the Fill notice by design. The chat route is compiled before the Scripts tab opens.
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

    # FILL_SEND: a second tab of this context (same routes: the send let through), the Scripts tab keeps its notice.
    sends: list[dict] = []
    chat = await page.context.new_page()
    await ui.accept_confirms(chat)
    try:
        if fan is None:   # agency_inbox small: thread_frac 0.6 of 50 Fans, so never at a seed in practice
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

    # FILL_UNDO: the Scripts tab's notice. It lives in the page's reducer per (Creator, Sequence) and shows while that
    # Creator + Sequence is on screen; a reload loses it by design (`reloaded`: the mark set after the press is gone).
    # Gone without a reload (the Sequence closed, another Creator picked): A + the Sequence are opened again and the
    # notice must come back (`reopened`). Any failure leaves fill-undo-failed and the tab's state (`at_failure`).
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


# ── C: the describe states ─────────────────────────────────────────────

async def _flow_c(ctx, page, d: dict, creators: dict, out: dict) -> None:
    w, c = ctx.world, d["c"]
    rows0 = _rows(w, c, sfv.SHORT_SEQUENCE)
    posts: list[dict] = []   # every describe-all POST the page made
    plans: list[int] = []    # every fill/plan answer the page got (the dialog refetches its plan on open)

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
        # DESCRIBE_BLOCKED: the cap row before the press.
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
        # DESCRIBE_REFUSED: the offer renders with the cap free, then the cap row lands before the press.
        _cap(w, c, False)
        n_plans = len(plans)
        refused["apply"], body, _ = await _press(page)
        refused["apply_status"] = body.get("status")
        refused["offer"] = await _dialog(page, "Describe content first?")
        t0 = time.monotonic()   # the dialog's own plan read lands before the cap row, so the offer stays up
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
        t_start = time.monotonic()   # every describe call of the sweep answers no sooner than `hold_s` after this
        offer["start"] = {"status": r.status, "body": r.request.post_data_json}
        offer["running_text"] = await _dialog(page, "Describing content")
        await _close(page)
        offer["running_at_reopen"] = (await ctx.owner.get(f"{STATUS}?account_id={c}")).json().get("running")
        st, body, _ = await _press(page)   # the reopen: a press while the sweep runs
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
        seen = await _await_cards(page, _want_cards(_rows(w, c, sfv.SHORT_SEQUENCE)))   # the shot shows them settled
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


# ── run ────────────────────────────────────────────────────────────────

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
    of_sessions.seed(w, w.data["creators"])   # a real OFClient per Creator, talking to lib/of_wire.py
    r = await ctx.owner.put("/admin/my-llm-keys", json={"deepinfra": FAKE_KEY})
    ctx.metric("agency_deepinfra_key", {"status": r.status_code})
    d = sfv.plan(w, w.data["creators"])
    photo_sizes(d["short_new"])
    armed = await arm_run(ctx.owner, ctx.stack.tmp, d["short_new"], ctx.param("llm_latency_s", DESCRIBE_HOLD_S))
    await arm_jev(ctx.owner, ctx.stack.tmp, d["short_new"], ctx.param("jev_latency_s", 0.1))
    await sfv.seed(w, armed)
    with ctx.of_wire.lock:   # OnlyFans' side of the seeded vaults: its vault page and by-id reads
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
    applied: dict = {}   # A's Fill as the isolation check's precondition: B's rows must survive a real write
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
