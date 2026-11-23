"""Creator badges scenario 5 (docs/spec/creator-badges/phase-0E-slop-and-fake-of-realism.md story 24, scenario row 5;
phase-0C stories 6, 12, 36): a deep inbox shows "9+" for 32 and never OF's raw 35, its Muted chats show no dot, its
incomplete Unread list flips no Fan to read, and a same-value swap on a Creator with a complete list settles every dot.

World: `flat_agency`; each Creator a captured session (the relay's REAL OFClient against lib/of_wire.py, `OF_WIRE`)
whose OF is lib/badge_wire.py with counter frames on. Deep Creators (X; TIERS `deep`): RESTRICTED registry-restricted
unread chats (OF's restrict + the Relay's `skip_list` row), MUTED Muted unread chats, DEEP_PLAIN plain unread chats,
in that order: counter 35, red 32; the Unread list (Muted left out) is 35 rows, 4 pages of 10, and the Relay reads
2, so it is incomplete. Swap Creators (Y; TIERS `swap`): SWAP_UNREAD plain unread, AWAITING read Fan-last (awaiting
reply: E2's 5-amber leg; all inside the 25-row window), SWAP_READ read Creator-last (a complete 2-page list). X has
no Fan to spare (50 chats, the small scale's 50 Fans). Every Live connection up (`/__slop/pump-supervise`).

Actors: one headless tab per Creator (actors/badge_tab.py: `/events?lease=1`, a View lease, so each Creator has an
Open tab and Attribution reads run); one owner stream keeping every `chat_read_changed` and DM frame (`_Flips`). One
Chromium tab on /messages-pro with X's tab picked (UI runs): screenshots `badge-edge-deep-inbox-trigger` (the legs
fired) and `badge-edge-deep-inbox-settled` (SETTLE_S later; both show the Amber circle beside the Red one, metric
`screenshots.amber`), Creator tab titles sampled every DOM_EVERY_S, the Fan List rows read before and after, once
the tab's own `/api/of/v2/chats` read for X (let through) answered (none in LIVE_LIST_S: INFRA, the rows are
FanList's local-DB seed).

Legs, at once once every slot holds its truth: X, `read_elsewhere` on its first plain unread chat (window row 18);
Y, `read_elsewhere` on one unread chat and a DM on one read chat (the first awaiting one: amber -1, the read +1) in
the same instant, so both counter frames carry the same value and only the read's (0.8 s after the DM, outside its
0.5 s window) is Unexplained.

Checks: NINE_PLUS (X: held slot `n` 32, the app's redCircle text "9+", roster-counts `unread` 32, the Chromium tab
title "9+ unread" when sampled); MUTED_NO_DOT (X: every Muted chat's row in the Relay's chats answer keeps
`isMutedNotifications` true, and no Muted row in the Fan List draws an Unread marker); RAW_COUNTER_NEVER_RENDERED
(`raw_leak` over every served slot `n`, roster-counts `unread`, SSE slot and tab title); INCOMPLETE_NO_FLIP (X: no
`chat_read_changed` to read, while an Attribution read ran after the leg, and the held slot `n` ends at
`truth_red`: red still follows the counter); SWAP_SETTLES (Y: the dot per Fan, the seed plus every flip and DM in
arrival order under FanRow's rule, `badge_metrics.dots`, equals `truth_unread` after the settle); NO_PHANTOM_AMBER
(E2's 5-amber leg, `no_phantom_amber`: every Amber circle the tab held or the Chromium title drew is at most the
amber truth of the last AMBER_SLACK_S, so no Creator-last Fan and no Fan off X's incomplete list counts, and when
settled it equals truth on a complete list, at most truth on X; through `badge_metrics.amber_gate`: SKIP while
Phase F's `amber` is absent from the accounts answer, FAIL under `--set require_amber=1`). NINE_PLUS, MUTED_NO_DOT and
RAW_COUNTER_NEVER_RENDERED `ctx.skip` while Phase B's slot is absent; INCOMPLETE_NO_FLIP and SWAP_SETTLES while
Phase C's completeness (service/badge_reads_decide.py `complete`) is absent. Pumps not all up or a Creator with no
counter frame after its leg is INFRA. Evidence `deep-inbox.json`.

Bypasses (declared): OF at its wire (lib/badge_wire.py on lib/of_wire.py); the tabs are API tabs (one Chromium tab:
the machine gate); the tab's store and display rule run in node (lib/badge_tab_ts.mjs); the per-Fan dot model is
`badge_metrics.dots` (the Chromium Fan List is the real-path view of X).
"""
from __future__ import annotations

import ast
import asyncio
import bisect
import contextlib
import json
import re
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from slop.actors import ui
from slop.actors.badge_tab import BadgeTab, open_ts
from slop.actors.manager import SseListener, events_of
from slop.lib.badge_load import phase_b
from slop.lib.badge_metrics import amber_gate, dots, group_reads, held_at, raw_leak
from slop.lib.badge_wire import BadgeWire, chat_plan, restrict_in_relay

PROFILE = "flat_agency"
UI = True
OF_WIRE = True
FAULT = None
TIMEOUT_S = 900
RELAY_ENV = {"INGEST_FAST_BOOT_GRACE_S": "0", "SHARED_REFRESHER": "1", "UNREAD_TOTAL": "1", "BADGE_READS": "full"}
TIERS = {"small": {"deep": 1, "swap": 1}, "full": {"deep": 3, "swap": 4}}
NINE_PLUS = "NINE_PLUS"
MUTED_NO_DOT = "MUTED_NO_DOT"
RAW_COUNTER_NEVER_RENDERED = "RAW_COUNTER_NEVER_RENDERED"
INCOMPLETE_NO_FLIP = "INCOMPLETE_NO_FLIP"
SWAP_SETTLES = "SWAP_SETTLES"
NO_PHANTOM_AMBER = "NO_PHANTOM_AMBER"
BASE_CHECKS = (NINE_PLUS, MUTED_NO_DOT, RAW_COUNTER_NEVER_RENDERED)
C_CHECKS = (INCOMPLETE_NO_FLIP, SWAP_SETTLES)
CHECKS = BASE_CHECKS + C_CHECKS + (NO_PHANTOM_AMBER,)
RESTRICTED = 3
MUTED = 15
DEEP_PLAIN = 32
DEEP_CHATS = RESTRICTED + MUTED + DEEP_PLAIN
DEEP_RAW = RESTRICTED + DEEP_PLAIN
DEEP_RED = DEEP_PLAIN
SWAP_UNREAD = 12
AWAITING = 10
SWAP_READ = 8
SWAP_CHATS = SWAP_UNREAD + AWAITING + SWAP_READ
RELAY_PAGES = 2
PUMP_UP_S = 30.0
SLOT_WAIT_S = 60.0
ROWS_TIMEOUT_S = 180.0
LIVE_LIST_S = 30.0
CHATS = "/api/of/v2/chats"
SETTLE_S = 15.0
AMBER_SLACK_S = 2.0
SAMPLE_S = 0.02
DOM_EVERY_S = 1.0
VIEWPORT = (1440, 900)
SHOT = "badge-edge-deep-inbox"
ROOT = Path(__file__).resolve().parents[2]
TITLES_JS = """() => [...document.querySelectorAll('[role="tablist"][aria-label="Creator tabs"] [role="tab"]')]
  .map((b) => b.getAttribute('title') || '')"""
PICK_JS = """(name) => {
  const t = [...document.querySelectorAll('[role="tablist"][aria-label="Creator tabs"] [role="tab"]')]
    .find((b) => (b.getAttribute('title') || '').startsWith(name + ' — '));
  if (t) t.click();
  return !!t;
}"""
ROWS_JS = """() => [...document.querySelectorAll('[data-chat-row]')]
  .map((r) => [r.textContent || '', !!r.querySelector('[role="img"][aria-label^="Unread"]')])"""
_TITLE = re.compile(r"(.+?) — (\d+|9\+) unread(?: — .*)?")
_AMBER_TITLE = re.compile(r" — (\d+|9\+) awaiting reply(?: — |$)")
_ID = re.compile(r"\d{6,}")


def plan_deep(fans: list[dict]) -> list[dict]:
    return chat_plan(fans, [("restricted", RESTRICTED, True), ("muted", MUTED, True), ("plain", DEEP_PLAIN, True)])


def plan_swap(fans: list[dict]) -> list[dict]:
    out = chat_plan(fans, [("plain", SWAP_UNREAD, True), ("plain", AWAITING + SWAP_READ, False)])
    for f in out[SWAP_UNREAD:SWAP_UNREAD + AWAITING]:
        f["awaiting"] = True
    return out


def phase_c() -> bool:
    tree = ast.parse((ROOT / "service" / "badge_reads_decide.py").read_text())
    return any(isinstance(n, ast.FunctionDef) and n.name == "complete" for n in tree.body)


def title_text(title: str) -> tuple[str, str] | None:
    """(Creator name, its circle's text: a digit or "9+") from CreatorTabs' title; None for grey."""
    m = _TITLE.fullmatch(title)
    return (m.group(1), m.group(2)) if m else None


def row_fan(text: str, fan_ids: set[int]) -> int | None:
    """The one Fan of `fan_ids` a Fan List row's text names (its name or handle carries the id), else None."""
    hits = {int(x) for x in _ID.findall(text)} & fan_ids
    return next(iter(hits)) if len(hits) == 1 else None


def live_list(answers: list[tuple[float, str | None, int]], aid: str, since: float) -> bool:
    """The browser's own chats read for `aid` answered 200 at or after `since`: the Fan List shows OF's rows, not
    FanList's local-DB seed (/admin/chats/recent: the world's rows, no Muted flag)."""
    return any(s == 200 and a == aid and t >= since for t, a, s in answers)


def nine_plus(slot_n, text, roster_n, dom_text) -> tuple[bool, dict]:
    ok = slot_n == DEEP_RED and text == "9+" and roster_n == DEEP_RED and dom_text in (None, "9+")
    return ok, {"slot_n": slot_n, "circle": text, "roster_unread": roster_n, "dom": dom_text, "want_n": DEEP_RED}


def muted_no_dot(muted: set[int], api_rows: list[dict], dom_rows: list[tuple[int | None, bool]]) -> tuple[bool | None,
                                                                                                          dict]:
    """Muted Fans' rows in the Relay's chats answer keep `isMutedNotifications` true; none draws a dot in the DOM."""
    api = [r for r in api_rows if (r.get("withUser") or {}).get("id") in muted]
    lost = sorted(r["withUser"]["id"] for r in api if r.get("isMutedNotifications") is not True)
    dom = [(f, d) for f, d in dom_rows if f in muted]
    dotted = sorted({f for f, d in dom if d})
    judged = len(api) + len(dom)
    return (None if not judged else not lost and not dotted), {"api_rows": len(api), "dom_rows": len(dom),
                                                                 "lost_muted_flag": lost, "dom_dots": dotted}


def incomplete_no_flip(flips: list[tuple[float, int | None, bool]], reads_after: int, slot_n,
                       truth_red: int) -> tuple[bool | None, dict]:
    read_flips = [list(f) for f in flips if not f[2]]
    detail = {"read_flips": read_flips[:10], "attribution_reads_after_leg": reads_after, "slot_n": slot_n,
              "truth_red": truth_red}
    if not reads_after:
        return None, detail
    return not read_flips and slot_n == truth_red, detail


def swap_settles(rows: dict[int, tuple[bool, bool]], events: list[tuple[float, int | None, bool]],
                 truth: set[int]) -> tuple[bool, dict]:
    shown = dots(rows, events)
    wrong = sorted(f for f in set(shown) | truth if shown.get(f, False) != (f in truth))
    return not wrong, {"wrong": wrong[:10], "shown_unread": sorted(f for f, d in shown.items() if d)[:20],
                       "truth_unread": sorted(truth)[:20]}


def amber_title(title: str) -> int | None:
    """The Amber circle CreatorTabs' title states ("9+" as 9, a floor), None when it states none."""
    m = _AMBER_TITLE.search(title)
    return None if not m else 9 if m.group(1) == "9+" else int(m.group(1))


def no_phantom_amber(slot: list[tuple[float, int]], dom: list[tuple[float, int]], truth: list[tuple[float, int]],
                     end: float, complete: bool, slack: float = AMBER_SLACK_S) -> tuple[bool | None, dict]:
    """One Creator: every Amber circle drawn (`slot` the tab's held slot, `dom` the Chromium title), at its draw and
    `slack` after each truth change, is at most the most amber truth held within `slack` before; at `end` the held
    slot equals truth where the Creator's Unread list is `complete`, else is at most it (a Fan the incomplete list
    could not name stays out of amber until a window read)."""
    truth, slot = sorted(truth), sorted(slot)
    tk = [t for t, _ in truth]

    def most(t):
        i, j = bisect.bisect_right(tk, t - slack), bisect.bisect_right(tk, t)
        xs = ([truth[i - 1][1]] if i else []) + [v for _, v in truth[i:j]]
        return max(xs, default=None)

    points = [(t, n, "slot") for t, n in slot if t <= end] + [(t, n, "dom") for t, n in dom if t <= end]
    points += [(t + slack, held_at(slot, t + slack), "slot") for t in tk if t + slack <= end]
    over, judged = [], 0
    for t, n, source in points:
        cap = most(t)
        if n is None or cap is None:
            continue
        judged += 1
        if n > cap:
            over.append({"t": round(t, 3), "amber": n, "truth_max": cap, "source": source})
    shown, want = held_at(slot, end), held_at(truth, end)
    final_ok = shown is not None and want is not None and (shown == want if complete else shown <= want)
    detail = {"judged": judged, "over": over[:10], "final": {"amber": shown, "truth": want, "complete": complete}}
    return (None if not judged else not over and final_ok), detail


def fire(wire: BadgeWire, target: dict[str, int], pair: dict[str, tuple[int, int]]) -> None:
    """The legs: each deep Creator's target read elsewhere; each swap Creator's (unread, read) pair read and DMed in
    one instant, so both counter frames (the DM's 1 ms, the read's click delay) carry the same value."""
    for a, fan in target.items():
        wire.read_elsewhere(a, fan)
    for a, (gone, new) in pair.items():
        wire.read_elsewhere(a, gone)
        wire.push_dm(a, {"id": new})


def merge(per: dict[str, tuple[bool | None, dict]]) -> tuple[bool | None, dict]:
    """One verdict over Creators: FAIL if any fails, SKIP (None) when none was judged, else PASS."""
    oks = [ok for ok, _d in per.values() if ok is not None]
    return (None if not oks else all(oks)), {a: d for a, (_ok, d) in per.items()}


def _check(ctx, name: str, per: dict[str, tuple[bool | None, dict]]) -> None:
    ok, detail = merge(per)
    ctx.check(name, ok, per_creator=detail)


class _Flips(SseListener):
    """The owner's stream: every `chat_read_changed` as `(t, Creator, fan | None, unread)`; DM frames in `meta` /
    `received_at` (SseListener)."""

    def __init__(self, http) -> None:
        super().__init__(http, resume=True, states=("chat_read_changed",))
        self.flips: list[tuple[float, str, int | None, bool]] = []

    def _keep_states(self, obj) -> None:
        t = time.time()
        for ev in events_of(obj):
            body = ev.get("chat_read_changed")
            if isinstance(body, dict) and body.get("unread") in (0, 1):
                fan = body.get("fan_id")
                self.flips.append((t, str(ev.get("__account_id")), None if fan == "all" else int(fan),
                                   body["unread"] == 1))

    def timeline(self, aid: str) -> list[tuple[float, int | None, bool]]:
        out = [(t, fan, u) for t, a, fan, u in self.flips if a == aid]
        out += [(self.received_at[mid] / 1000, fan, True) for mid, (a, fan) in self.meta.items()
                if a == aid and fan is not None and mid in self.received_at]
        return sorted(out, key=lambda e: e[0])


async def run(ctx) -> None:
    tier_name = ctx.param("tier", "small")
    tier = TIERS[tier_name]
    w, fake = ctx.world, ctx.of_wire
    w.data["flat_creators"] = tier["deep"] + tier["swap"]
    await ctx.build(PROFILE)
    ids = [c["id"] for c in w.data["creators"]]
    deep, swap = ids[:tier["deep"]], ids[tier["deep"]:]
    seeds = {a: plan_deep(w.data["fans"][a]) for a in deep} | {a: plan_swap(w.data["fans"][a]) for a in swap}
    assert all(len(seeds[a]) == DEEP_CHATS for a in deep), f"each deep Creator needs {DEEP_CHATS} fans"
    assert all(len(seeds[a]) == SWAP_CHATS for a in swap), f"each swap Creator needs {SWAP_CHATS} fans"
    wire = BadgeWire(fake).install()
    halt = asyncio.Event()
    raw: dict[str, list[tuple[float, int]]] = {a: [] for a in ids}
    red: dict[str, list[tuple[float, int]]] = {a: [] for a in ids}
    amber: dict[str, list[tuple[float, int]]] = {a: [] for a in ids}
    sampler = None
    tabs: list[BadgeTab] = []
    flips = _Flips(ctx.owner.share(limits=4))
    sessions = []
    try:
        for a, fans in seeds.items():
            wire.seed(a, fans)
        got = {a: (wire.raw_counter(a), wire.truth_red(a)) for a in deep}
        assert set(got.values()) == {(DEEP_RAW, DEEP_RED)}, f"deep seed {got} must be raw {DEEP_RAW}, red {DEEP_RED}"
        con = w.sql()
        with con:
            restrict_in_relay(con, seeds)
        con.close()
        ctx.metric("world", {"tier": tier_name, **tier, "deep": deep, "swap": swap, "phase_c": phase_c(),
                             "raw": {a: wire.raw_counter(a) for a in ids}, "red": {a: wire.truth_red(a) for a in ids}})
        sampler = asyncio.create_task(_sample(wire, ids, raw, red, amber, halt))
        sessions = await open_ts(ctx, 1)
        t_pumps = time.time()
        (await ctx.owner.post("/__slop/pump-supervise")).raise_for_status()
        up: set = set()
        while time.time() - t_pumps < PUMP_UP_S and len(up) < len(ids):
            await asyncio.sleep(0.25)
            with fake.lock:
                up = {c["account"] for c in fake.ws_connects if c["t"] >= t_pumps}
        ctx.metric("pumps_up", {"connected": len(up), "creators": len(ids), "seconds": round(time.time() - t_pumps, 1)})
        if len(up) < len(ids):
            ctx.report.infra = ctx.report.infra or f"badge-edge-deep-inbox inconclusive: {len(up)} of {len(ids)} pumps up"
        await flips.start()
        tabs = [BadgeTab(ctx, f"{a}-t0", [a], sessions[0]) for a in ids]
        await asyncio.gather(*(t.start() for t in tabs))
        tab = {t.aids[0]: t for t in tabs}
        t_slot = time.time()
        while True:
            held = {a: tab[a].held(a) for a in ids}
            if all(phase_b(s) and s.get("grey") is None and s.get("n") == wire.truth_red(a) for a, s in held.items()):
                break
            if time.time() - t_slot > SLOT_WAIT_S:
                break
            await asyncio.sleep(1.0)
            await asyncio.gather(*(t.refetch() for t in tabs))
        present = any(phase_b(s) for s in held.values())
        ctx.metric("slot_ready", {"present": present, "seconds": round(time.time() - t_slot, 1), "held": held})
        if not present:
            for name in BASE_CHECKS + C_CHECKS:
                ctx.skip(name, "Phase B's slot (values.unread_total with v and grey) is absent")
            ok, why = amber_gate(False, ctx.param("require_amber", 0) == 1)
            ctx.check(NO_PHANTOM_AMBER, ok, reason=why)
            return
        await _legs(ctx, fake, wire, tab, flips, seeds, deep, swap, sessions[0], raw, red, amber)
    finally:
        await asyncio.gather(*(t.stop() for t in tabs), flips.stop(), return_exceptions=True)
        await asyncio.gather(*(s.close() for s in sessions), return_exceptions=True)
        halt.set()
        if sampler:
            await asyncio.gather(sampler, return_exceptions=True)
        wire.close()


async def _sample(wire: BadgeWire, aids: list[str], raw: dict, red: dict, amber: dict, halt: asyncio.Event) -> None:
    while not halt.is_set():
        t = time.time()
        for a in aids:
            for xs, v in ((raw[a], wire.raw_counter(a)), (red[a], wire.truth_red(a)), (amber[a], wire.truth_amber(a))):
                if not xs or xs[-1][1] != v:
                    xs.append((t, v))
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(halt.wait(), SAMPLE_S)


async def _legs(ctx, fake, wire: BadgeWire, tab: dict[str, BadgeTab], flips: _Flips, seeds: dict[str, list[dict]],
                deep: list[str], swap: list[str], ts, raw: dict, red: dict, amber: dict) -> None:
    ids = deep + swap
    rows0 = {a: {f["id"]: (f["unread"], f["muted"]) for f in seeds[a]} for a in ids}
    muted = {a: {f["id"] for f in seeds[a] if f["muted"]} for a in deep}
    target = {a: next(f["id"] for f in seeds[a] if f["kind"] == "plain") for a in deep}
    pair = {a: (next(f["id"] for f in seeds[a] if f["unread"]), next(f["id"] for f in seeds[a] if not f["unread"]))
            for a in swap}
    names = {}
    r = await ctx.owner.get("/admin/accounts")
    for acc in (r.json().get("accounts") or []) if r.status_code == 200 else []:
        names[acc.get("nickname") or acc["id"]] = acc["id"]
    shots: dict[str, str] = {}
    dom: list[tuple[float, str, int, str]] = []
    dom_text: dict[str, list[tuple[float, str]]] = {a: [] for a in ids}
    dom_amber: dict[str, list[tuple[float, int]]] = {a: [] for a in ids}
    shot_amber: dict[str, dict[str, int | None]] = {}
    dom_rows: dict[str, list[tuple[int | None, bool]]] = {}
    answers: list[tuple[float, str | None, int]] = []
    live = False
    stop = asyncio.Event()

    async with contextlib.AsyncExitStack() as stack:
        page = None
        if ctx.ui and ctx.app:
            try:
                page = await stack.enter_async_context(ui.owner_browser(ctx, viewport=VIEWPORT, through=(CHATS,)))
                page.on("response", lambda r: urlsplit(r.url).path == CHATS and answers.append(
                    (time.time(), r.request.headers.get("x-account-id"), r.status)))
                await page.goto(f"{ctx.app}/messages-pro", timeout=ROWS_TIMEOUT_S * 1000)
                await page.wait_for_selector('[role="tablist"][aria-label="Creator tabs"] [role="tab"]',
                                             timeout=ROWS_TIMEOUT_S * 1000)
                x_name = next((n for n, a in names.items() if a == deep[0]), deep[0])
                t_pick = time.time()
                if not await page.evaluate(PICK_JS, x_name):
                    ctx.metric("chromium_error", f"no Creator tab titled {x_name!r}")
                await page.wait_for_selector("[data-chat-row]", timeout=ROWS_TIMEOUT_S * 1000)
                while not live_list(answers, deep[0], t_pick) and time.time() - t_pick < LIVE_LIST_S:
                    await asyncio.sleep(0.25)
                live = live_list(answers, deep[0], t_pick)
                ctx.metric("fan_list_live", {"live": live, "answers": [[round(t - t_pick, 2), a, st]
                                                                       for t, a, st in answers][:20]})
                if live:
                    await asyncio.sleep(1.0)
                else:
                    ctx.report.infra = ctx.report.infra or (
                        f"badge-edge-deep-inbox inconclusive: no 200 {CHATS} for {deep[0]} in {LIVE_LIST_S:.0f} s "
                        "after the pick (the Fan List is FanList's local seed)")
            except Exception as e:  # noqa: BLE001 — the API checks still judge; the screenshots record why
                ctx.metric("chromium_error", f"{type(e).__name__}: {e}"[:300])

        async def shot(name: str) -> None:
            if page is None:
                return
            try:
                shot_amber[name] = {a: (tab[a].held(a) or {}).get("amber") for a in ids}
                shots[name] = await ui.shot(ctx, page, name)
            except Exception as e:  # noqa: BLE001
                ctx.metric(f"shot_{name}_error", f"{type(e).__name__}: {e}"[:300])

        async def scan_rows(when: str) -> None:
            if page is None or not live:
                return
            try:
                got = await page.evaluate(ROWS_JS)
            except Exception as e:  # noqa: BLE001
                ctx.metric(f"rows_{when}_error", f"{type(e).__name__}: {e}"[:300])
                return
            fan_ids = set(rows0[deep[0]])
            dom_rows[when] = [(row_fan(text, fan_ids), bool(dot)) for text, dot in got]

        async def titles() -> None:
            while page is not None and not stop.is_set():
                try:
                    ts_ = await page.evaluate(TITLES_JS)
                except Exception:  # noqa: BLE001 — mid-navigation: the next sample reads again
                    ts_ = []
                t = time.time()
                for title in ts_:
                    got = title_text(title)
                    if got and got[0] in names:
                        aid = names[got[0]]
                        dom_text.setdefault(aid, []).append((t, got[1]))
                        if (n := amber_title(title)) is not None:
                            dom_amber.setdefault(aid, []).append((t, n))
                        if got[1].isdigit():
                            dom.append((t, aid, int(got[1]), "dom"))
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stop.wait(), DOM_EVERY_S)

        sampler = asyncio.create_task(titles())
        await asyncio.gather(*(tab[a].roster() for a in deep))
        pre = {a: tab[a].held(a) for a in deep}
        circles = (await ts.call({"op": "circles", "slots": [pre[a] for a in deep]}))["circles"]
        roster_n = {a: next((n for _t, aid, n, s in reversed(tab[a].served) if aid == a and s == "roster"), None)
                    for a in deep}
        await scan_rows("before")
        t_leg = time.time()
        fire(wire, target, pair)
        await shot(f"{SHOT}-trigger")
        await asyncio.sleep(SETTLE_S)
        t_settled = time.time()
        await shot(f"{SHOT}-settled")
        await scan_rows("settled")
        stop.set()
        await sampler

    api_rows: dict[str, list[dict]] = {}
    for a in deep:
        r = await ctx.owner.get("/api/of/v2/chats?limit=25&offset=0&order=recent", headers={"X-Account-Id": a})
        api_rows[a] = ((r.json() or {}).get("list") or []) if r.status_code == 200 else []
    with fake.lock:
        calls = list(fake.calls)
    frames = list(wire.frames)
    reads = group_reads(calls)
    after = {a: [f["value"] for f in frames if f["account"] == a and f["kind"] == "counter" and f["t"] >= t_leg]
             for a in ids}
    ctx.metric("screenshots", {**shots, "amber": {n: shot_amber[n] for n in shots}})
    ctx.metric("legs", {"deep_target": target, "swap_pair": pair, "counter_frames_after": after,
                        "attribution_reads": dict(Counter(r.account for r in reads if r.start >= t_leg)),
                        "pages": dict(Counter(r.pages for r in reads)), "dom_rows": {k: len(v) for k, v in dom_rows.items()},
                        "tabs": {t.name: {"errors": t.errors[:5], "ended": t.ended} for t in tab.values()},
                        "flips": len(flips.flips), "seconds": round(t_settled - t_leg, 1)})
    silent = [a for a in ids if not after[a]]
    if silent:
        ctx.report.infra = ctx.report.infra or f"badge-edge-deep-inbox inconclusive: no counter frame after the leg on {silent}"

    nine = {}
    for a, c in zip(deep, circles):
        last_dom = next((x for t, x in reversed(dom_text.get(a, [])) if t < t_leg), None)
        nine[a] = nine_plus((pre[a] or {}).get("n"), c.get("text"), roster_n[a], last_dom)
    _check(ctx, NINE_PLUS, nine)
    seen = [(f, d) for when in ("before", "settled") for f, d in dom_rows.get(when, [])]
    _check(ctx, MUTED_NO_DOT, {a: muted_no_dot(muted[a], api_rows[a], seen if a == deep[0] else []) for a in deep})
    served = [(t, a, n) for tb in tab.values() for t, a, n, _ in tb.served] + [(t, a, n) for t, a, n, _ in dom]
    sources = Counter(s for tb in tab.values() for *_x, s in tb.served) + Counter(s for *_x, s in dom)
    leaks = raw_leak(served, [(t, a, v) for a, xs in raw.items() for t, v in xs],
                     [(t, a, v) for a, xs in red.items() for t, v in xs])
    judged = sum(1 for t, a, _ in served if a in deep and red[a] and red[a][0][0] <= t)
    ctx.check(RAW_COUNTER_NEVER_RENDERED, None if not judged else not leaks, judged=judged, served=len(served),
              by_source=dict(sources), leaks=[{"t": round(t - t_leg, 3), "creator": a, "n": n} for t, a, n in leaks[:10]])

    if not phase_c():
        for name in C_CHECKS:
            ctx.skip(name, "Phase C's completeness (service/badge_reads_decide.py complete) is absent")
    else:
        _check(ctx, INCOMPLETE_NO_FLIP, {a: incomplete_no_flip(
            flips.timeline(a), sum(1 for r in reads if r.account == a and r.start >= t_leg),
            (tab[a].held(a) or {}).get("n"), wire.truth_red(a)) for a in deep})
        _check(ctx, SWAP_SETTLES, {a: swap_settles(rows0[a], flips.timeline(a), wire.truth_unread(a)) for a in swap})
    present = any(isinstance(tab[a].held(a), dict) and "amber" in tab[a].held(a) for a in ids)
    per = {a: no_phantom_amber([(t, x["amber"]) for t, x in tab[a].slots[a]
                                if isinstance(x, dict) and isinstance(x.get("amber"), int)],
                               dom_amber.get(a, []), amber[a], t_settled, a in swap) for a in ids} if present else {}
    ok, detail = merge(per)
    ok, why = amber_gate(present, ctx.param("require_amber", 0) == 1, ok)
    ctx.check(NO_PHANTOM_AMBER, ok, per_creator=detail, **({"reason": why} if why else {}))
    (ctx.out / "deep-inbox.json").write_text(json.dumps({
        "t_leg": t_leg, "t_settled": t_settled, "raw_counter": raw, "truth_red": red, "truth_amber": amber,
        "dom_amber": dom_amber,
        "flips": flips.flips, "observed": {t.name: t.slots for t in tab.values()}, "dom_rows": dom_rows,
    }, default=str))
