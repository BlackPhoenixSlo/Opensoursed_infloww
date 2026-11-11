"""Help bot "Do it for me" builds an Auto mass from one sentence (docs/spec/assistant-do-mode.md; service/
assistant_draft.py, app/components/assistant/{DoMode.tsx, doFlows.ts, useDoRunner.ts, AgentCursor.tsx}).

World: `agency_inbox`, a captured session per Creator against lib/of_wire.py (`OF_WIRE`). Creator 0 (C) gets the
vault of seed/assistant_do_vault.py (SQL): "SFW teasers" (every photo flagged sfw/suggestive), "Spicy" (more sfw
photos, but 2 explicit), "Unflagged" (most photos, none flagged); OF's side holds the same folders (`vault_lists`)
and two custom fan lists, MASSdmEXCLUDE and VIP. DeepSeek is lib/assistant_do_relay.py's fake: PHRASE -> its intent.

Flow: POST /admin/assistant/draft {PHRASE} as the owner (the API pick, also under --no-ui). Then the owner's browser,
desktop 1440x900 and phone portrait 390x844: warm /growth/auto-mass (first compile), open /growth/auto-post, open the
help bot, focus C, the "Do it for me" card, type PHRASE, Enter -> the plan card (`plan-<pass>`), Do it -> the agent
cursor mid-run, the page moved to Auto mass (`cursor-<pass>`; phone: the sheet folded to its pill) -> "Created OFF"
and the rule's row in the table (`settled-desktop`; phone: the pill stays with "Created OFF · Open" over the table,
`settled-phone-table`, then Open -> the sheet's card, `settled-phone-card`).
The phone pass's rule is "Hourly SFW mass 2" (the draft names around the desktop one).

Checks:
  plan_card_shown        the plan card with Do it, its lines: every hour, 10 AI captions, the SFW teasers folder, online
                         and offline fans, unsend after 1h, saved OFF; nothing in "Couldn't match"
  folder_is_sfw_teasers  every draft (API + each pass) picked folder SFW teasers (not Spicy / Unflagged), plan says so
  rule_saved_disabled    each pass's automation_rules row (SQL): kind mass_premade, is_enabled 0; every POST body the
                         agent sent has is_enabled false
  rule_payload_matches   each row: trigger every_seconds 3600, one message, online_only false, the 10 captions,
                         media_folder_id SFW teasers, unsend_after_hours 1, fans + following, MASSdmEXCLUDE not in
                         excluded_user_lists
  no_send_happened       OF's wire saw the lists read and no mass / chat / post send or unsend
  no_5xx                 no 5xx to the drafts or in either browser session
Side effects: rules.json (rows + POST bodies), drafts.json.

FAULT `assistant-do-skips-disabled` (client: drops BOTH OFF layers -- ReadyMadeRuleEditor's forced-OFF guard in the
agent save and doFlows.ts' "Leaving it OFF" step patch, since either alone keeps the rule OFF and would mask the
other; the blank editor's enabled default stands): rule_saved_disabled alone. Each rewrite must match, else INFRA. No
automation tick runs here (no supervisor), so an enabled rule still sends nothing.

VIDEO (opt-in, `--set video=1`; off = all of the above unchanged): the desktop pass alone, recorded (Playwright
record_video, 1440x900) at human pace: an intro title, PHRASE typed ~35 ms/char, a pause on the plan card, the
animated run played out, a hold on the done card + the rule's row (Enabled off), then a "What this cost" card. The
cost prices the exact draft prompt the fake DeepSeek got (lib/assistant_do_relay.py PROMPTS: system + user + its
completion) with service/llm_models.py's own `deepseek-v4-flash` rates: tokens by tiktoken cl100k if importable,
else chars/4 (labelled; an estimate either way); cold call (all input a cache miss), warm (system prefix cached),
per 100 / 1000 setups; plus the draft's assistant_turns row (its cost is off the fake's synthetic usage).
Outputs: video/do-mode-demo.webm, do-mode-demo.mp4 (ffmpeg H.264, trimmed to the intro), cost.json.
  video_recorded         (video=1 only) do-mode-demo.mp4 exists and is > 100 KB

Bypasses (declared): OnlyFans is lib/of_wire.py; the browser's /api/of/v2/lists and /api/of/v2/vault/lists go
through to the relay and on to it, every other /api/of/ read stays held (actors/ui). DeepSeek is the fake above
(the intent is canned; the folder, lists, name and unsend hours are the product's own resolution). Not a volume
path: one owner, one sentence, proven on the real page.
"""
from __future__ import annotations

import asyncio
import html
import importlib.util
import json
import re
import shutil
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from slop.actors import ui
from slop.lib.assistant_do_relay import CAPTIONS, PHRASE, PROMPTS, RULE_NAME, request_of
from slop.seed import assistant_do_vault, of_sessions

PROFILE = "agency_inbox"
UI = True
OF_WIRE = True
FAULT = "assistant-do-skips-disabled"
DESKTOP = (1440, 900)
PHONE = (390, 844)
WAIT_MS = 120_000   # first visit of a page compiles it in next dev
RUN_MS = 180_000    # the animated run: ~18 steps, 10 typed captions
THROUGH = ("/api/of/v2/vault/lists", "/api/of/v2/lists")
DRAFT, RULES = "/admin/assistant/draft", "/admin/automation-rules"
DONE = "Created OFF — turn it on in the table when ready"
MASS_EXCLUDE = {"id": 880_001, "type": "custom", "name": "MASSdmEXCLUDE"}
VIP = {"id": 880_002, "type": "custom", "name": "VIP"}
PLAN_WANT = ("Every hour", "Captions: 10 (10 AI-written — edit later)", "Audience: online and offline fans",
             "Unsend after 1h", "Saved OFF — you turn it on")
# OF wire routes that send or unsend (lib/of_wire.py `route`: numbers as {id}).
SEND_ROUTES = ("POST /api2/v2/messages/queue", "POST /api2/v2/chats/{id}/messages", "POST /api2/v2/posts",
               "DELETE /api2/v2/messages/queue/{id}")

C_PLAN, C_FOLDER, C_DISABLED, C_PAYLOAD, C_NOSEND, C_5XX = (
    "plan_card_shown", "folder_is_sfw_teasers", "rule_saved_disabled", "rule_payload_matches", "no_send_happened",
    "no_5xx")
C_VIDEO = "video_recorded"
# video=1 (module docstring): pacing, outputs, the model priced.
TYPE_MS, INTRO_S, PLAN_HOLD_S, DONE_HOLD_S, COST_HOLD_S = 35, 2.5, 1.5, 3.0, 6.0
VIDEO_DIR, WEBM, MP4, MP4_MIN_BYTES = "video", "do-mode-demo.webm", "do-mode-demo.mp4", 100_000
COST_MODEL = "deepseek-v4-flash"
LLM_MODELS = Path(__file__).resolve().parents[2] / "service" / "llm_models.py"
INTRO_TITLE = "Help bot · Do it for me — Auto mass"

# Finite animations (the sheet's pop in / out) done; a skeleton's endless pulse does not count.
_SETTLED = """() => document.getAnimations().filter((a) => a.playState === 'running'
  && a.effect && a.effect.getComputedTiming().iterations !== Infinity).length === 0"""


async def _shot(ctx, page, name: str) -> str:
    try:
        await page.wait_for_function(_SETTLED, timeout=15_000)
    except Exception:  # noqa: BLE001 — a shot of a page still moving beats none
        pass
    return await ui.shot(ctx, page, name)


def _folder_of(draft: dict | None) -> dict | None:
    return ((draft or {}).get("slots") or {}).get("folder")


def _rows(w, aid: str) -> list[dict]:
    con = w.sql()
    try:
        rows = con.execute("SELECT id, name, kind, is_enabled, trigger_json, steps_json FROM automation_rules "
                           "WHERE account_id=? ORDER BY id", (aid,)).fetchall()
    finally:
        con.close()
    return [{"id": r[0], "name": r[1], "kind": r[2], "is_enabled": r[3], "trigger": json.loads(r[4] or "{}"),
             "payload": json.loads(r[5] or "{}")} for r in rows]


def _payload_ok(row: dict, sfw_id: int) -> tuple[bool, dict]:
    msgs = (row.get("payload") or {}).get("messages") or []
    m = msgs[0] if len(msgs) == 1 else {}
    excl = [str(x) for x in m.get("excluded_user_lists") or []]
    got = {"every_seconds": row["trigger"].get("every_seconds"), "messages": len(msgs),
           "online_only": m.get("online_only", False), "texts": m.get("texts"),
           "media_folder_id": m.get("media_folder_id"), "unsend_after_hours": m.get("unsend_after_hours"),
           "user_lists": m.get("user_lists"), "excluded_user_lists": excl}
    ok = (got["every_seconds"] == 3600 and got["messages"] == 1 and got["online_only"] is False
          and got["texts"] == CAPTIONS and str(got["media_folder_id"]) == str(sfw_id)
          and got["unsend_after_hours"] == 1 and sorted(got["user_lists"] or []) == ["fans", "following"]
          and str(MASS_EXCLUDE["id"]) not in excl and MASS_EXCLUDE["name"] not in excl)
    return ok, got


class _Recorder:
    """A browser whose new_context records video (Playwright takes record_video_* only there): ui._owner_page's
    context, nothing else changed."""

    def __init__(self, browser, vdir: Path, size) -> None:
        self._b = browser
        self._kw = {"record_video_dir": str(vdir), "record_video_size": {"width": size[0], "height": size[1]}}

    def __getattr__(self, k):
        return getattr(self._b, k)

    async def new_context(self, **kw):
        return await self._b.new_context(**kw, **self._kw)


@asynccontextmanager
async def _video_browser(ctx, viewport, vdir: Path):
    """ui.owner_browser (through=THROUGH, desktop), its context recording into `vdir`."""
    vdir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=ui.LAUNCH_ARGS)
        try:
            yield await ui._owner_page(_Recorder(browser, vdir, viewport), ctx, viewport, [], [], through=THROUGH)
        finally:
            await browser.close()


_OVERLAY_ADD = """([id, inner]) => {
  const d = document.createElement('div');
  d.id = id;
  d.setAttribute('data-slop-overlay', '');
  d.style.cssText = 'position:fixed;inset:0;z-index:2147483647;display:flex;align-items:center;'
    + 'justify-content:center;background:rgba(3,6,12,.6);pointer-events:none;'
    + 'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif';
  d.innerHTML = inner;
  document.body.appendChild(d);
}"""
_OVERLAY_DEL = "(id) => { const d = document.getElementById(id); if (d) d.remove(); }"
_CARD = ("background:#0f141c;color:#f3f6fa;border:1px solid #2a3442;border-radius:20px;"
         "box-shadow:0 24px 80px rgba(0,0,0,.6);padding:44px 56px;")


async def _overlay(page, oid: str, inner: str, hold_s: float, shot=None) -> str | None:
    """A fixed card over the page for `hold_s` (video only: the recording's titles); `shot` (ctx, name): a
    screenshot of it, its path."""
    await page.evaluate(_OVERLAY_ADD, [f"slop-{oid}", inner])
    t0 = time.monotonic()
    path = await ui.shot(shot[0], page, shot[1]) if shot else None
    await asyncio.sleep(max(0.0, hold_s - (time.monotonic() - t0)))
    await page.evaluate(_OVERLAY_DEL, f"slop-{oid}")
    return path


def _intro_html() -> str:
    style = f"{_CARD}font-size:46px;font-weight:700;letter-spacing:-.01em"
    return f'<div style="{style}">{html.escape(INTRO_TITLE)}</div>'


def _usd(v: float) -> str:
    return f"${v:,.2f}" if v >= 0.01 else f"${v:.6f}".rstrip("0")


def _cost_html(c: dict) -> str:
    if c.get("error"):
        rows = [("Cost", c["error"])]
    else:
        t = c["tokens"]
        rows = [("Model", c["model"]),
                ("Tokens in", f'{t["system"]:,} system + {t["user"]:,} user'),
                ("Tokens out", f'{t["output"]:,}'),
                ("Cold call (nothing cached)", _usd(c["usd"]["cold"])),
                ("Warm call (system prompt cached)", _usd(c["usd"]["warm"])),
                ("Per 1000 setups (warm)", _usd(c["usd"]["per_1000"]["warm"])),
                ("LLM calls", "1 (draft only — filling the form uses no AI)")]
    trs = "".join(f'<tr><td style="color:#9aa7b8;padding:8px 36px 8px 0">{html.escape(k)}</td>'
                  f'<td style="color:#f3f6fa;font-weight:600;padding:8px 0">{html.escape(str(v))}</td></tr>' for k, v in rows)
    foot = f'estimate · priced from llm_models.py · tokens: {c.get("token_count", "n/a")}'
    return (f'<div style="{_CARD}min-width:760px"><div style="font-size:44px;font-weight:700;margin-bottom:22px">'
            f'What this cost</div><table style="font-size:28px;color:#f3f6fa;border-collapse:collapse">{trs}</table>'
            f'<div style="margin-top:26px;font-size:18px;color:#7d8a9c">{html.escape(foot)}</div></div>')


def _tokens(text: str) -> tuple[int, str]:
    """(tokens, how): tiktoken cl100k when importable and its table loads, else chars/4."""
    try:
        import tiktoken
        return len(tiktoken.get_encoding("cl100k_base").encode(text)), "tiktoken cl100k_base (estimate)"
    except Exception:  # noqa: BLE001 — not in the venv, or its BPE file not cached (loopback only)
        return (len(text) + 3) // 4, "chars/4 (estimate)"


def _llm_models():
    """service/llm_models.py by path (stdlib only; registered so its dataclasses resolve)."""
    spec = importlib.util.spec_from_file_location("slop_llm_models", LLM_MODELS)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _cost(ctx, w, aid: str, row_id=None) -> dict:
    """The draft's price (module docstring, VIDEO): the newest captured PHRASE prompt, cost.json's body."""
    f = ctx.stack.tmp / PROMPTS
    lines = [json.loads(x) for x in f.read_text().splitlines() if x.strip()] if f.is_file() else []
    mine = [x for x in lines if request_of(x.get("user") or "") == PHRASE]
    if not mine:
        return {"error": f"no draft prompt captured ({f})"}
    p = mine[-1]
    m = _llm_models().MODELS[COST_MODEL]
    (ts, how), (tu, _), (to, _) = _tokens(p["system"]), _tokens(p["user"]), _tokens(p["completion"])

    def usd(n: int, cents_per_1k: float) -> float:
        return n / 1000 * cents_per_1k / 100

    out = usd(to, m.output_per_1k_cents)
    cold = usd(ts + tu, m.input_per_1k_cents) + out
    warm = usd(ts, m.input_cache_hit_per_1k_cents) + usd(tu, m.input_per_1k_cents) + out
    con = w.sql()
    try:
        q = "SELECT id, model, provider, cost_millicents, latency_ms, error FROM assistant_turns "
        r = (con.execute(q + "WHERE id=?", (row_id,)).fetchone() if row_id is not None else None) or \
            con.execute(q + "WHERE account_id=? AND question=? ORDER BY id DESC LIMIT 1", (aid, PHRASE)).fetchone()
    finally:
        con.close()
    turn = r and dict(zip(("id", "model", "provider", "cost_millicents", "latency_ms", "error"), r))
    return {"model": COST_MODEL, "estimate": True, "token_count": how, "priced_from": "service/llm_models.py",
            "rates_cents_per_1k": {"input_cache_miss": m.input_per_1k_cents,
                                   "input_cache_hit": m.input_cache_hit_per_1k_cents,
                                   "output": m.output_per_1k_cents},
            "tokens": {"system": ts, "user": tu, "output": to},
            "chars": {"system": len(p["system"]), "user": len(p["user"]), "output": len(p["completion"])},
            "usd": {"cold": cold, "warm": warm,
                    "per_100": {"cold": cold * 100, "warm": warm * 100},
                    "per_1000": {"cold": cold * 1000, "warm": warm * 1000}},
            "llm_calls": 1, "llm_calls_note": "the draft only; the agent fills the form with no AI call",
            "assistant_turn": turn,
            "assistant_turn_note": "cost_millicents is off the fake DeepSeek's synthetic usage (automation_relay: "
                                   "900 prompt / 20 completion tokens, no cache hits), not a real bill",
            "draft_model_matches": bool(turn) and turn.get("model") == COST_MODEL,
            "prompt": p}


async def _mp4(ctx, src: str | None, trim_s: float) -> dict:
    """The recording renamed to video/WEBM (kept) and ffmpeg'd to MP4 (H.264, yuv420p, faststart; from the intro)."""
    webm, mp4 = ctx.out / VIDEO_DIR / WEBM, ctx.out / MP4
    res = {"webm": None, "mp4": None, "trim_s": round(trim_s, 2), "error": None}
    if not src or not Path(src).is_file():
        res["error"] = f"no recording ({src})"
        return res
    Path(src).rename(webm)
    res["webm"] = str(webm)
    ff = shutil.which("ffmpeg")
    if not ff:
        res["error"] = "ffmpeg not on PATH"
        return res
    p = await asyncio.create_subprocess_exec(
        "nice", "-n", "10", ff, "-y", "-loglevel", "error", "-ss", f"{trim_s:.2f}", "-i", str(webm),
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-an", str(mp4), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, err = await asyncio.wait_for(p.communicate(), timeout=600)
    if p.returncode != 0:
        res["error"] = f"ffmpeg exit {p.returncode}: {err.decode(errors='replace')[-300:]}"
    if mp4.is_file():
        res.update(mp4=str(mp4), mp4_bytes=mp4.stat().st_size)
    return res


async def _focus(page, nick: str) -> str:
    """Point the bot at the Creator (Do it for me sets up one model's page); returns the focus label."""
    btn = page.locator('[aria-label^="Help bot focus: "]').first
    await btn.wait_for(timeout=30_000)
    if await btn.get_attribute("aria-label") != f"Help bot focus: {nick}":
        await btn.click()
        await page.get_by_role("menuitemradio", name=re.compile(rf"^{re.escape(nick)}(?:\s|$)")).first.click()
    return await btn.get_attribute("aria-label")


async def _pass(ctx, aid: str, nick: str, tag: str, viewport, touch: bool, video: Path | None = None,
                cost=None) -> dict:
    """One owner browser through the flow (module docstring); everything the checks read. `video`: record into
    that dir at human pace (module docstring, VIDEO); `cost(row_id)` -> the cost card's dict."""
    res: dict = {"tag": tag, "drafts": [], "saves": [], "shots": {}, "errors": []}
    browser = (_video_browser(ctx, viewport, video) if video
               else ui.owner_browser(ctx, viewport=viewport, touch=touch, through=THROUGH))
    async with browser as page:
        t_open = time.monotonic()
        drafts, saves = [], []

        def on_resp(r) -> None:
            path = urlsplit(r.url).path
            if r.request.method == "POST" and path.endswith(DRAFT):
                drafts.append(r)
            elif r.request.method == "POST" and path.endswith(RULES):
                saves.append(r)

        page.on("response", on_resp)
        page.context.set_default_navigation_timeout(WAIT_MS)
        try:
            await page.goto(f"{ctx.app}/growth/auto-mass?creator={aid}", wait_until="domcontentloaded")
            await page.get_by_role("button", name="New auto mass").first.wait_for(timeout=WAIT_MS)
            await page.goto(f"{ctx.app}/growth/auto-post?creator={aid}", wait_until="domcontentloaded")
            launcher = page.locator('button[aria-label="Help assistant"], button[aria-label="Show help assistant"]')
            await launcher.first.wait_for(timeout=WAIT_MS)
            if video:   # the mp4 starts here: the warm-up's compile waits are cut (trim_s, a margin early)
                try:
                    await page.wait_for_function(_SETTLED, timeout=15_000)
                except Exception:  # noqa: BLE001 — a page still moving is fine under the title
                    pass
                res["trim_s"] = max(0.0, time.monotonic() - t_open - 0.3)
                await _overlay(page, "intro", _intro_html(), INTRO_S)
            tucked = page.get_by_role("button", name="Show help assistant", exact=True)
            if await tucked.count():
                await tucked.click()
            await page.get_by_role("button", name="Help assistant", exact=True).first.click(timeout=30_000)
            res["focus"] = await _focus(page, nick)
            card = page.get_by_role("button").filter(has_text="Opens the page and fills it in")
            await card.first.click(timeout=30_000)
            box = page.get_by_placeholder("What should I set up?")
            if video:
                await box.click()
                await box.press_sequentially(PHRASE, delay=TYPE_MS)
                await asyncio.sleep(0.6)
            else:
                await box.fill(PHRASE)
            await box.press("Enter")
            plan = page.locator('[data-testid="do-plan"]')
            await plan.wait_for(timeout=60_000)
            res["plan_lines"] = [x.strip() for x in await plan.locator("ul").first.locator("li").all_inner_texts()]
            res["plan_notes"] = await plan.get_by_role("note").count()
            do_it = plan.get_by_role("button", name="Do it", exact=True)
            res["do_it"] = await do_it.count()
            res["shots"]["plan"] = await _shot(ctx, page, f"plan-{tag}")
            if video:
                await asyncio.sleep(PLAN_HOLD_S)

            await do_it.click(timeout=10_000)   # inside the bot: no takeover
            cursor = page.locator("[data-agent-cursor]")
            await cursor.wait_for(timeout=WAIT_MS)
            try:   # the captions are the long stretch: catch the cursor typing one
                await cursor.filter(has_text="Typing captions").wait_for(timeout=30_000)
            except Exception:  # noqa: BLE001 — any mid-run frame still proves the cursor
                pass
            res["cursor_label"] = (await cursor.inner_text()).strip() if await cursor.count() else None
            res["pill"] = await page.locator("[data-assistant-ui][role=status]", has_text="Doing it…").count()
            res["shots"]["cursor"] = await ui.shot(ctx, page, f"cursor-{tag}")   # mid-run: no settle wait

            # Phone: once over, the pill keeps the outcome ("Created OFF · Open") over the page; desktop: the card.
            done_pill = page.locator("[data-assistant-ui][role=status]", has_text="Created OFF")
            if touch:
                await done_pill.wait_for(timeout=RUN_MS)
            else:
                await page.get_by_text(DONE, exact=True).wait_for(timeout=RUN_MS)
            res["url"] = page.url
            name = None
            if saves:
                body = saves[-1].request.post_data_json or {}
                name = body.get("name")
            switch = page.get_by_role("switch", name=f"Enabled: {name or RULE_NAME}", exact=True)
            await switch.wait_for(timeout=30_000)
            res["switch_checked"] = await switch.get_attribute("aria-checked")
            if video:   # the done card + the new row, Enabled off
                await switch.scroll_into_view_if_needed(timeout=10_000)
                await asyncio.sleep(DONE_HOLD_S)
            if touch:
                res["shots"]["table"] = await _shot(ctx, page, f"settled-{tag}-table")
                await done_pill.get_by_role("button", name="Open", exact=True).click(timeout=10_000)
                await page.get_by_text(DONE, exact=True).wait_for(timeout=30_000)
                res["shots"]["settled"] = await _shot(ctx, page, f"settled-{tag}-card")
            else:
                res["shots"]["settled"] = await _shot(ctx, page, f"settled-{tag}")
            if video and cost:
                try:
                    row_id = (await drafts[-1].json()).get("id") if drafts else None
                except Exception:  # noqa: BLE001 — the newest PHRASE turn stands in
                    row_id = None
                res["cost"] = cost(row_id)
                res["shots"]["cost"] = await _overlay(page, "cost", _cost_html(res["cost"]), COST_HOLD_S,
                                                      shot=(ctx, f"cost-{tag}"))
        except Exception as e:  # noqa: BLE001 — the checks below say what was missing
            res["errors"].append(f"{type(e).__name__}: {str(e)[:300]}")
            res["shots"]["error"] = await ui.shot(ctx, page, f"error-{tag}")
        for r in drafts:
            try:
                res["drafts"].append({"status": r.status, "body": await r.json()})
            except Exception:  # noqa: BLE001
                res["drafts"].append({"status": r.status, "body": None})
        for r in saves:
            try:
                res["saves"].append({"status": r.status, "body": r.request.post_data_json, "rule": await r.json()})
            except Exception:  # noqa: BLE001
                res["saves"].append({"status": r.status, "body": r.request.post_data_json, "rule": None})
        res["statuses"] = list(page.slop["statuses"])
        if video:   # the webm is written when its context closes
            try:
                res["video_src"] = await page.video.path() if page.video else None
                await page.context.close()
            except Exception as e:  # noqa: BLE001 — video_recorded says it
                res["errors"].append(f"video: {type(e).__name__}: {str(e)[:200]}")
    return res


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    creators = w.data["creators"]
    of_sessions.seed(w, creators)
    c = creators[0]
    aid, nick = c["id"], c.get("nickname") or c["id"]
    vault = assistant_do_vault.seed(w, c)
    sfw_id = vault["sfw_id"]
    fake = ctx.of_wire
    with fake.lock:
        fake.lists[aid] = [dict(MASS_EXCLUDE, usersCount=0), dict(VIP, usersCount=0)]
        fake.list_users[MASS_EXCLUDE["id"]] = [910_001, 910_002]
        fake.list_users[VIP["id"]] = [910_003]
        fake.vault_lists[aid] = vault["of_lists"]

    # Do-mode bills the agency's own key (no platform fallback, unlike Q&A): set one, as lib/followup.py does.
    r = await ctx.owner.put("/admin/my-llm-keys", json={"deepseek": "slop-fake-deepseek"})
    ctx.metric("agency_deepseek_key", {"status": r.status_code})

    api = await ctx.owner.post(DRAFT, json={"request": PHRASE, "account_id": aid})
    api_body = api.json() if api.status_code == 200 else None
    drafts = [{"via": "api", "status": api.status_code, "body": api_body}]

    video = str(ctx.param("video", "0")).lower() in ("1", "true", "yes", "on")
    passes = []
    if ctx.app and video:   # module docstring, VIDEO: the desktop pass alone, recorded
        passes.append(await _pass(ctx, aid, nick, "desktop", DESKTOP, False, video=ctx.out / VIDEO_DIR,
                                  cost=lambda row_id: _cost(ctx, w, aid, row_id)))
    elif ctx.app:
        passes.append(await _pass(ctx, aid, nick, "desktop", DESKTOP, False))
        passes.append(await _pass(ctx, aid, nick, "phone", PHONE, True))
    drafts += [{"via": p["tag"], **d} for p in passes for d in p["drafts"]]

    # folder_is_sfw_teasers: the server's pick in every draft, and each plan card's folder line.
    folders = [{"via": d["via"], "folder": _folder_of(d["body"])} for d in drafts]
    plan_folder = [next((x for x in p.get("plan_lines") or [] if x.startswith("Folder: ")), None) for p in passes]
    ctx.check(C_FOLDER, api.status_code == 200
              and all(f["folder"] and str(f["folder"].get("id")) == str(sfw_id)
                      and f["folder"].get("name") == "SFW teasers" for f in folders)
              and all((x or "").startswith("Folder: SFW teasers") for x in plan_folder)
              and all(p["drafts"] for p in passes),
              sfw_id=sfw_id, folders=folders, plan_folder=plan_folder, vault=vault["folders"])

    rows = _rows(w, aid)
    saved = {p["tag"]: [s for s in p["saves"]] for p in passes}
    (ctx.out / "drafts.json").write_text(json.dumps(drafts, indent=2, ensure_ascii=False))
    (ctx.out / "rules.json").write_text(json.dumps({"rows": rows, "saves": saved,
                                                    "passes": [{k: v for k, v in p.items() if k not in
                                                                ("drafts", "saves", "statuses", "cost")}
                                                               for p in passes]},
                                                   indent=2, ensure_ascii=False, default=str))

    if not ctx.app:
        for n in (C_PLAN, C_DISABLED, C_PAYLOAD):
            ctx.skip(n, "--no-ui")
    else:
        plan = {p["tag"]: {"lines": p.get("plan_lines"), "notes": p.get("plan_notes"), "do_it": p.get("do_it"),
                           "focus": p.get("focus"), "errors": p["errors"], "shot": p["shots"].get("plan")}
                for p in passes}
        ctx.check(C_PLAN, all(v["lines"] and all(x in v["lines"] for x in PLAN_WANT) and v["notes"] == 0
                              and v["do_it"] == 1 for v in plan.values()),
                  **plan, want=PLAN_WANT, screenshots=[p["shots"].get("plan") for p in passes])

        by_id = {r["id"]: r for r in rows}
        mine = {}
        for p in passes:
            ids = [(s.get("rule") or {}).get("id") for s in p["saves"] if s["status"] == 200]
            mine[p["tag"]] = [by_id.get(i) for i in ids]
        flat = [r for rs in mine.values() for r in rs]
        posted = [(s["body"] or {}).get("is_enabled") for p in passes for s in p["saves"]]
        ctx.check(C_DISABLED, all(len(rs) == 1 for rs in mine.values()) and all(
                      r is not None and r["kind"] == "mass_premade" and r["is_enabled"] == 0 for r in flat)
                  and bool(posted) and all(x is False for x in posted),
                  rows={t: [r and {k: r[k] for k in ("id", "name", "kind", "is_enabled")} for r in rs]
                        for t, rs in mine.items()},
                  posted_is_enabled={p["tag"]: [(s["body"] or {}).get("is_enabled") for s in p["saves"]]
                                     for p in passes},
                  table_switch={p["tag"]: p.get("switch_checked") for p in passes},
                  errors={p["tag"]: p["errors"] for p in passes},
                  screenshots=[x for p in passes for k, x in p["shots"].items() if k in ("settled", "table")])
        judged = [(_payload_ok(r, sfw_id) if r else (False, None)) for r in flat]
        ctx.check(C_PAYLOAD, bool(flat) and all(len(rs) == 1 for rs in mine.values()) and all(ok for ok, _ in judged),
                  got=[g for _, g in judged], names=[r and r["name"] for r in flat], sfw_id=sfw_id,
                  mass_exclude_id=MASS_EXCLUDE["id"], captions=len(CAPTIONS))
        ctx.metric("cursor", {p["tag"]: {"label": p.get("cursor_label"), "pill": p.get("pill"), "url": p.get("url"),
                                         "shot": p["shots"].get("cursor")} for p in passes})

    with fake.lock:
        calls = list(fake.calls)
        state = {k: {a: len(v) for a, v in getattr(fake, k).items() if v} for k in ("sends", "queue", "posts", "unsends")}
    sends = [x for x in calls if x["route"] in SEND_ROUTES]
    lists_reads = sum(1 for x in calls if x["route"] == "GET /api2/v2/lists" and x["account"] == aid)
    ctx.check(C_NOSEND, not sends and not any(state.values()) and lists_reads > 0,
              send_calls=sends[:5], state=state, lists_reads=lists_reads, wire_calls=len(calls))

    if video and not ctx.app:
        ctx.skip(C_VIDEO, "--no-ui")
    elif video:
        p = passes[0]
        cost = p.get("cost") or _cost(ctx, w, aid)
        (ctx.out / "cost.json").write_text(json.dumps(cost, indent=2, ensure_ascii=False, default=str))
        vid = await _mp4(ctx, p.get("video_src"), p.get("trim_s", 0.0))
        ctx.metric("video", vid)
        ctx.metric("cost", {k: v for k, v in cost.items() if k != "prompt"})
        ctx.note(f"video webm: {vid['webm']}", f"video mp4:  {vid['mp4']}", f"cost:       {ctx.out / 'cost.json'}")
        print(f"  video: {vid['mp4']} (webm {vid['webm']})")
        ctx.check(C_VIDEO, bool(vid["mp4"]) and vid.get("mp4_bytes", 0) > MP4_MIN_BYTES, **vid,
                  min_bytes=MP4_MIN_BYTES, cost_error=cost.get("error"), errors=p["errors"],
                  screenshots=[x for x in (p["shots"].get("settled"), p["shots"].get("cost")) if x])

    fc = (await ctx.owner.get("/__slop/fake/calls")).json()
    ctx.metric("fake_calls", fc.get("calls"))
    bad = [(d["via"], d["status"]) for d in drafts if d["status"] >= 500]
    bad += [(s, u) for p in passes for s, u in p["statuses"] if s >= 500]
    ctx.check(C_5XX, not bad, count=len(bad), sample=bad[:5])
