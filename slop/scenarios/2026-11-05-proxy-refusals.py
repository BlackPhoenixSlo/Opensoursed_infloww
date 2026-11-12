"""A flapping pool proxy: alive, but the provider refuses a share of its CONNECTs (docs/adr/0030
Consequences, docs/proxies.md "Refusals", service/proxy_health.py refusal window + flap knob).

Prod 2026-11 (slop/evidence/20261105T150727Z-ae-proxy-refusals-296e9299c, local only): the
provider refuses CONNECT about a third of the time on half the pool, in bursts, not from load;
each refusal is back within 1-20 s, so no DOWN_AFTER streak forms and the outage path never
fires. Built: every `_proxy_retry` attempt (and probe) feeds a per-proxy window shown on
`GET /admin/proxies` (`health.refusals`; `inflight`/`inflight_peak` to the site owner only), the
Proxies table adds "refusing N% (M min)", the Accounts badge reads "proxy refusing", and the flap
knob (`PROXY_FLAP_BAD_PCT` = X, default 20 since the owner accepted the IP change on 2026-11-05;
0 = off) marks a proxy bad (FlapBad) on a refusal with >= 20 attempts in the window, >= X %
refused, refusals in >= 3 of the window's tenths, not already down; it stays bad (hysteresis)
while >= X/2 % of >= 20 attempts in the window, however old (no recency rule since 2026-11-08: it
comes back only once its window drains), then the next answer or recheck brings it back as standby;
nobody is moved (or newly bound) onto a flapping proxy.

At the defaults, on purpose: RELAY_ENV sets no knob (the relay's own PROXY_FLAP_BAD_PCT 20 and
PROXY_FLAP_WINDOW_S 600, so the table reads "(10 min)" as on prod); only PROXY_RECHECK_S=2
compresses the recheck cadence, as 2026-10-28-proxy-failover does (same defaults: a dead proxy's
failures are no refusals, its confirm -> recheck -> move timeline unchanged). The off switch is the
unit test `case_flap_knob_on_by_default_zero_turns_it_off` (service/tests/test_proxy_health.py:
PROXY_FLAP_BAD_PCT=0, 50 refusals at 100 %, not down).

The world: `one_agency` (one Agency, 50 Creators, medium = 5,000 fans by SQL), each Creator with a
captured session (seed/of_sessions.py) so the relay builds its REAL OFClient; OnlyFans is
lib/of_wire.py (`OF_WIRE`). A pool of POOL (3) lib/proxy_wire.py proxies synced through
`POST /__slop/proxy-pool`, PER_PROXY (2, as prod) Creators each bound least-used through
`POST /admin/proxy-pool/assign`; plus the owner's custom proxy (`POST /admin/proxies` + `/assign`)
with CUSTOM (4) Creators: custom Creators never move, so traffic stays on it and its stay and clear
rules are exercised under load; pool proxies are never listed in the Proxies table, so the UI is
read on it. Phase A (LOAD_S 180 s, past the move budget): the first Creator's pool proxy and the
custom one refuse REFUSE_SHARE (0.3, `--set refuse_share=`) of CONNECTs (seeded); `--users` people
(seeded picks among the 10 Creators) refresh the Fan List once a second
(`GET /api/of/v2/chats?refresh=1`, interactive: 2 tries) and send a unique DM every third second
(5 tries); the harness polls the registry and `GET /admin/proxies` twice a second (a registry read
that is empty or lacks a bound Creator, i.e. mid-write, is skipped). Then the pool proxy's share
goes to 0 and two clocks run side by side: the moved-away pool proxy's standby is polled (only
probes reach it now), while on the custom proxy phase B (HOLD_S 60 s) has it
refuse HOLD_SHARE (0.16) with every person reading its 4 Creators (paced users/HOLD_RPS, 0.25-1 s;
the UI shot taken meanwhile), then phase C: its share goes to 0 and the reads go on until it
clears. Attempts per proxy track its Creators, not the read rate (2 Creators gave 746 / 777 per
minute at 20 / 30 reads/s, ...-d789, ...-e726; inferred: a Creator's reads coalesce), hence CUSTOM 4.

Checks (each with its why): C_RATE_SHOWN (the owner can see a flapping proxy; an Agency's owner sees the
share alone, `refusals` {window_s, pct}: the counts are every Agency's traffic, the site owner's since
2026-11-08; so n is the fake's own CONNECTs since phase A began, WS dials excluded (they skip
`_proxy_retry`), >= 20 of them, pct within the share +- PCT_Z (3.5) binomial sd of n (two-sided
P 0.05 %; a fixed [20, 40] failed at n 69, 15.9 %, ...-d789: the pool row is read at its last moment
before the move, which the hysteresis lets fall under X); the band only, not the fake's own share: the
relay counts attempts over its 600 s window (warm-up and probes included), the fake CONNECTs (custom
28.8 % vs the fake's 460/1536 = 29.9 %, ...-b755; a "5 refusals' worth" tolerance was 0.33 points there;
a keep-alive tunnel dialed before phase A carried ~325 attempts on one CONNECT once the relay shared
curl handles across workers, 24.0 % vs 30.3 %, ...-022c, so lib/proxy_wire.py closes it too); pool row from the owner's last read before the move (after
it the row leaves the owner's list), the custom row after a 1 s quiet; clean pool proxies pct 0); C_UI_TEXT (the operator sees it without
the API: the custom row reads "refusing N% (10 min)" while refusing; knob-independent; skipped under
--no-ui); C_FLAP_MOVES (the knob does what the ADR says, through the existing machinery, without
losing a DM: bad + both Creators on answering pool proxies within FLAP_MOVE_MS of the refusals
starting, their calls after the move all 200, the clean pool Creators all 200, every non-200 a 502
proxy_unreachable, no send lost / duplicated / ghosted, interactive read p95 <= INTERACTIVE_P95_MS);
C_STANDBY_NO_FAILBACK (a recovered proxy is usable again but nobody moves back: FAILS without the move,
then `pool.bad` 0 within STANDBY_MS of its share going to 0, bindings identical from the move to the
end); C_HYSTERESIS (a flap-bad proxy does not flip bad/up while it keeps refusing: the custom proxy
was flap-bad at the end of phase A and, through phase B, never up in any poll, still bad with
bad_reason flapping at its end, pct >= STAY_PCT (X/2), `/admin/accounts` proxy_bad_reason flapping for its
Creators, with UI the badge "proxy refusing" on all CUSTOM; at the 600 s window B's attempts blend
with A's, so the shown pct stays >= X: that a rate inside [X/2, X) alone holds it is the unit test
`case_flap_hysteresis_probe_class_and_bad_reason` and ...-20261105T170854Z-...-a337, this scenario
at a 60 s window with B = window + 20 s); C_CLEARS (it comes back: steadily bad (the last 5 polls of
B and the read at the stop) when its refusals stop, not bad within CLEAR_MS, accounts proxy_down
false, with UI the badge gone).
Evidence only: the share of people's reads that surfaced proxy_unreachable with today's 2 tries,
inflight_peak per proxy when the owner may see it (metric `proxy_refusals`), flap toggles.

Budgets, from the rule at the defaults. FLAP_MOVE_MS 160 s: refusals in 3 tenths of the window are
3 different absolute minutes, so bad comes with the first refusal of the third minute, 61-121 s
after the first (>= 20 attempts and >= 20 % arrive within seconds: 4 attempts/s on small's pool
proxy, 13/s medium); + the 2 failed rechecks at bad +2 and +6 s (FAILOVER_AFTER_RECHECKS 2; a
passing probe while still flapping counts as failed) + 2 probes 0.7 s + poll 0.5 s: ~130 s; the
30 s over it are for a loaded host (the move's threads, not the clock, slow down). STANDBY_MS 1000 s
(inferred from the rule, not yet measured): after the move (bad + ~6 s) only probes reach it
(rechecks at bad +2, +6, +14, +30, +62, +126, +254, +510, +1022 s: doubling, capped at RECHECK_MAX_S
600 s, which PROXY_RECHECK_S does not scale), fewer than 20 attempts, so its window holds phase A's
30 % >= X/2 until phase A's attempts age out, ~bad + 606 s; the first recheck after that, bad + 1022 s,
brings it back (bad is 57-120 s before share-0): share-0 + 902-965 s, + probe and poll. CLEAR_MS
630 s (inferred from the rule): the custom proxy's reads keep answering in phase C, diluting its window
(at ~13 attempts/s under X/2 around C + ~375 s, as phase A's attempts age out), and at the latest every
refused attempt is out of the window WINDOW_S after the share went to 0, then the next answer (people
read ~HOLD_RPS/s) brings it back, + poll. HOLD_S 60 s: 1/10 of the window; under the fault a refusal every ~0.5 s (16 % of 13/s) marks it bad and the next answer
(~0.1 s) brings it up, so 120 polls at 0.5 s see "up" with certainty and C_CLEARS' 5 + 1 steady-bad
reads pass by luck with P ~0.2^6. INTERACTIVE_P95_MS 4.5 s (phase A reads): this relay at 200
people with no refusals reads p95 1.6 s on the dev host (`--set refuse_share=0`, ...-3222); refusals
slow every Creator's reads (inferred: refused tries hold relay threads): with 6 of 10 Creators behind
a refusing proxy the clean pool Creators read p95 3.06 s (host load 12-17, ...-604a), and a read's
worst refusal path adds ~0.9 s (0.33 + 0.2 + 0.33): 4.0 s + margin; P95_VS_LAST guards it run to run.

Bypasses, declared: as 2026-10-28-proxy-failover (pool synced by the hook; PROXY_RECHECK_S=2;
SOCKS5 on loopback, a refusal = reply 0x02 after 0.33 s, curl 97 not prod's 56, both ProxyError;
the probe's trace is lib/of_wire.py's; people are httpx pools on their own recorder, their 502s
being expected answers this scenario checks); while refusing, the fake closes a tunnel after one
exchange so each attempt draws its own CONNECT (lib/proxy_wire.py).

Break-it-once (FAULT = flap-knob-ignored, lib/proxy_refusals_faults.py: `still_flapping()` + `herd_guarded()` False):
C_FLAP_MOVES, C_STANDBY_NO_FAILBACK, C_HYSTERESIS, C_CLEARS red; C_RATE_SHOWN and C_UI_TEXT (the
window and its text, knob-independent) stay green. `--fault=refusal-window-blind` (the window
records nothing) turns all six red.
"""
from __future__ import annotations

import asyncio
import math
import re
import time
from collections import Counter
from contextlib import AsyncExitStack, ExitStack

from slop.actors import ui
from slop.lib.client import Recorder, actor_call as _call
from slop.lib.procmon import pct
from slop.lib.proxy_refusals_faults import (C_CLEARS, C_FLAP_MOVES, C_HYSTERESIS, C_RATE_SHOWN,
                                             C_STANDBY_NO_FAILBACK, C_UI_TEXT)
from slop.lib.proxy_wire import ProxyWire, registry_bindings, registry_pool
from slop.lib.service_constant import service_number
from slop.seed import of_sessions

PROFILE = "one_agency"
UI = True
OF_WIRE = True
FAULT = "flap-knob-ignored"
P95_VS_LAST = (1.5, 100)
P95_VS_LAST_MIN_N = 50
RELAY_ENV = {"PROXY_RECHECK_S": "2"}   # the flap knob at the relay's defaults (20 %, 600 s): only the cadence compressed
WINDOW_S = 600              # service/proxy_health.WINDOW_S, the default this scenario runs at
POOL = 3
PER_PROXY = 2
CUSTOM = 4                 # 2 gave ~13 attempts/s whatever the read rate (746-777 per window, ...-d789/-e726)
CUSTOM_LABEL = "slop-flappy"
REFUSE_SHARE = 0.3
HOLD_SHARE = 0.16
LOAD_S = 180.0              # past FLAP_MOVE_MS: the move lands inside phase A, reads follow it
HOLD_S = 60.0               # phase B: 1/10 of the window, ~120 polls (the fault's flicker shows with certainty)
FLAP_MOVE_MS = 160_000
STANDBY_MS = 1_000_000     # inferred (docstring "Budgets"): the first recheck after the window drains
CLEAR_MS = 630_000         # inferred: WINDOW_S after the share went to 0 at the latest, + an answer and a poll
INTERACTIVE_P95_MS = 4500
PCT_Z = 3.5                # the shown pct within share +- 3.5 binomial sd of its calls (two-sided P 0.05 %)
HOLD_RPS = 30.0            # phase-B reads per second wanted (each person paced users/HOLD_RPS, 0.25-1 s)
STAY_PCT = service_number("proxy_health", "FLAP_PCT_DEFAULT", as_float=True) / 2
MIN_CALLS = 20
UI_WAIT_MS = 20_000
VIEWPORT = (1440, 900)
SHOTS = ("1-proxies-before-refusing", "2-proxies-refusing", "3-accounts-proxy-refusing", "4-proxies-settled",
         "5-accounts-settled")
BAD = ("bad", "rechecking")

READ = "/api/of/v2/users/me"
PEOPLE_READ = "/api/of/v2/chats?limit=5&refresh=1"


def _plain(html: str) -> str:
    return re.sub(r"</?p>", "", html or "")


def _connects(wire: ProxyWire, ws_port: int, since: float) -> list[int]:
    """[CONNECTs, refused] the fake proxy saw since epoch `since`, the chat WebSocket's dials left out."""
    with wire.lock:
        cs = [c for c in wire.connects if c["t"] >= since and not c["dest"].endswith(f":{ws_port}")]
    return [len(cs), sum(1 for c in cs if not c["alive"])]


async def _proxies(owner) -> tuple[dict[int, dict], dict, int | None]:
    """Pool rows by slot (only those the owner has a Creator on), the custom proxy's health and
    `pool.bad`, from the owner's GET /admin/proxies."""
    r = await owner.get("/admin/proxies")
    if r.status_code != 200:
        return {}, {}, None
    body = r.json()
    rows = {p["slot"]: p["health"] for p in body.get("pool", {}).get("proxies", [])}
    custom = next((p.get("health") or {} for p in body.get("proxies", []) if p.get("label") == CUSTOM_LABEL), {})
    return rows, custom, body.get("pool", {}).get("bad")


async def _ui_row(ctx, page, name: str, want: re.Pattern | None) -> str:
    """Open the Proxies page, wait for the custom row (and `want` in it), screenshot; the row's text."""
    await page.goto(f"{ctx.app}/creators/proxy", wait_until="domcontentloaded")
    row = page.locator("tr", has_text=CUSTOM_LABEL).first
    text = ""
    t_end = time.perf_counter() + UI_WAIT_MS / 1000
    while time.perf_counter() < t_end:
        try:
            text = await row.inner_text(timeout=2000)
        except Exception:  # noqa: BLE001  not rendered yet
            text = ""
        if text and (want is None or want.search(text)):
            break
        await page.wait_for_timeout(500)
    await ui.shot(ctx, page, name)
    return text


async def _accounts(owner, aids) -> dict[str, tuple]:
    """(proxy_down, proxy_bad_reason) per Creator from the owner's GET /admin/accounts (the badge's data)."""
    r = await owner.get("/admin/accounts")
    rows = r.json().get("accounts", []) if r.status_code == 200 else []
    return {a["id"]: (a.get("proxy_down"), a.get("proxy_bad_reason")) for a in rows if a.get("id") in aids}


async def _ui_badges(ctx, page, name: str, ready: str, want: int) -> int:
    """Open the Accounts page (/creators), Per page 50 (all of the agency's Creators on one page), wait for
    `ready` (a custom Creator's name) and `want` "proxy refusing" badges, screenshot (the first badge in view);
    the count (-1: the page never showed `ready` at 50 per page)."""
    await page.goto(f"{ctx.app}/creators", wait_until="domcontentloaded")
    badge = page.get_by_text("proxy refusing", exact=True)
    n, sized = -1, False
    t_end = time.perf_counter() + UI_WAIT_MS / 1000
    while time.perf_counter() < t_end:
        try:
            await page.get_by_text(ready).first.wait_for(timeout=2000)
            if not sized:
                await page.get_by_label("Per page").click(timeout=2000)
                await page.get_by_role("option", name="50", exact=True).click(timeout=2000)
                sized = True
            n = await badge.count()
        except Exception:  # noqa: BLE001  not rendered yet
            n = -1
        if sized and n == want:
            break
        await page.wait_for_timeout(500)
    if n > 0:
        await badge.first.scroll_into_view_if_needed(timeout=2000)
    await ui.shot(ctx, page, name)
    return n if sized else -1


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    of_sessions.seed(w, w.data["creators"])
    main = w.data["agencies"][0]["user_id"]
    aids = [c["id"] for c in w.data["creators"] if c["owner"] == main]
    share = float(ctx.param("refuse_share", REFUSE_SHARE))
    load_s = float(ctx.param("load_s", LOAD_S))
    flap_ms = float(ctx.param("flap_move_ms", FLAP_MOVE_MS))
    standby_ms = float(ctx.param("standby_ms", STANDBY_MS))
    owner, fake = ctx.owner, ctx.of_wire
    reg = ctx.stack.sessions.parent / "proxies.json"
    n_pool = POOL * PER_PROXY
    on_pool, on_custom = aids[:n_pool], aids[n_pool:n_pool + CUSTOM]
    window_min = round(WINDOW_S / 60)   # the table's "(M min)"
    ui_re = re.compile(rf"refusing (\d+)% \({window_min} min\)")
    n0 = len(fake.calls)

    with ExitStack() as stack:
        wires = [stack.enter_context(ProxyWire(seed=ctx.seed * 100 + i)) for i in range(POOL)]
        custom = stack.enter_context(ProxyWire(seed=ctx.seed * 100 + POOL))

        # ── pool + custom proxy, Creators bound, each warmed through its proxy (clean) ──
        text = ",".join(f"socks5://127.0.0.1:{p.port}" for p in wires)
        synced = (await owner.post("/__slop/proxy-pool", json={"text": text})).status_code
        by_port = {p.port: p for p in wires}
        slots = registry_pool(reg)
        label_wire = {label: by_port[port] for label, port in slots.items()}
        slot_of = {label: i + 1 for i, (label, _port) in enumerate(slots.items())}
        bound = [(await owner.post("/admin/proxy-pool/assign", json={"account_id": a})).status_code for a in on_pool]
        made = (await owner.post("/admin/proxies", json={"label": CUSTOM_LABEL, "scheme": "socks5",
                                                         "host": "127.0.0.1", "port": custom.port})).status_code
        await asyncio.sleep(1.0)   # the add's SQL mirror sync before the binds (dead-proxy scenario: THINK_S)
        bound += [(await owner.post("/admin/proxies/assign", json={"label": CUSTOM_LABEL, "account_id": a}))
                  .status_code for a in on_custom]
        b0 = registry_bindings(reg)
        warm = await asyncio.gather(*(_call(owner, "warm", a, READ) for a in on_pool + on_custom))
        flap_label = b0.get(on_pool[0])
        flap_wire = label_wire.get(flap_label)
        flappy = sorted(a for a in on_pool if b0.get(a) == flap_label)
        clean = sorted(a for a in on_pool if a not in flappy)
        setup_ok = (synced == 200 and all(s == 200 for s in bound) and made == 200 and flap_wire is not None
                    and len(flappy) == PER_PROXY and all(x["status"] == 200 for x in warm)
                    and all(b0.get(a) == CUSTOM_LABEL for a in on_custom))
        ctx.metric("proxy_refusals_setup", {"sync": synced, "bind": dict(Counter(bound)), "custom": made,
                                            "warm": dict(Counter(x["status"] for x in warm)),
                                            "per_proxy": dict(Counter(b0.get(a) for a in on_pool)),
                                            "flap_slot": slot_of.get(flap_label), "ok": setup_ok})
        if not setup_ok:
            raise RuntimeError(f"setup failed: sync {synced} bind {bound} custom {made} warm "
                               f"{Counter(x['status'] for x in warm)} flappy {flappy}")

        async with AsyncExitStack() as astack:
            page = await astack.enter_async_context(ui.owner_browser(ctx, viewport=VIEWPORT)) if ctx.app else None
            before_text = await _ui_row(ctx, page, "1-proxies-before-refusing", None) if page else None
            ws_port = fake._ws_port
            flap_slot = slot_of[flap_label]
            rng = w.rng("proxy_refusals_people")
            picks = [rng.choice(on_pool + on_custom) for _ in range(ctx.users)]
            fans = w.data["fans"]
            ready = next(c["nickname"] for c in w.data["creators"] if c["id"] == on_custom[0])
            hold_share = float(ctx.param("hold_share", HOLD_SHARE))
            hold_s = float(ctx.param("hold_s", HOLD_S))
            clear_ms = float(ctx.param("clear_ms", CLEAR_MS))
            people_rec = Recorder()   # declared: reads of a refusing proxy's Creators 502 on purpose
            http = owner.share(rec=people_rec, limits=4 * ctx.users + 16)
            seen: list[dict] = []
            polls: list[dict] = []
            moved_at: list[float] = []
            bound_aids = set(flappy) | set(on_custom)

            hold_pace = min(max(len(picks) / HOLD_RPS, 0.25), 1.0)

            async def person(n: int, aid: str, until, sends: bool = True) -> None:
                i = 0
                while (time.perf_counter() < until) if isinstance(until, float) else not until.is_set():
                    i += 1
                    if sends and i % 3 == 0:
                        fan = fans[aid][(n + i) % len(fans[aid])]["id"]
                        txt = f"slop refusals p{n} #{i} {aid}"
                        seen.append(await _call(http, "send", aid, f"/api/of/v2/chats/{fan}/messages", "POST",
                                                {"text": txt}, txt))
                    else:
                        seen.append(await _call(http, "read" if sends else "hold", aid, PEOPLE_READ))
                    await asyncio.sleep(1.0 if sends else hold_pace)

            async def poll(until: float) -> None:
                while time.perf_counter() < until:
                    t_b = time.perf_counter()
                    b = registry_bindings(reg)
                    if not bound_aids <= b.keys():   # empty / mid-write registry read: no false move
                        await asyncio.sleep(0.1)
                        continue
                    t_get = time.time()
                    wire_c = _connects(flap_wire, ws_port, t_wall0)
                    rows, chealth, bad = await _proxies(owner)
                    row = rows.get(flap_slot)
                    polls.append({"t": t_b, "row": row, "state": (row or {}).get("state"), "bad": bad,
                                  "wire_connects": wire_c, "t_get": t_get, "custom": chealth.get("state"), "bindings": b,
                                  "on_flap": sorted(a for a in flappy if b.get(a) == flap_label)})
                    if not polls[-1]["on_flap"] and not moved_at:
                        moved_at.append(t_b)
                    await asyncio.sleep(0.5)

            # ── phase A: the flappy pool proxy and the custom one refuse `share` of CONNECTs, people read and send ──
            ctx.rec.stage = "refusing"
            t0, t_wall0 = time.perf_counter(), time.time()
            flap_wire.set_refuse_share(share)
            custom.set_refuse_share(share)
            until = t0 + load_s
            await asyncio.gather(poll(until), *(person(n, a, until) for n, a in enumerate(picks)))
            ctx.rec.stage = None
            flap_wire.set_refuse_share(0)
            t_zero = time.perf_counter()
            await asyncio.sleep(1.0)   # the last in-flight attempts land in the window

            # C_RATE_SHOWN: the pool row from the owner's last read before the move (then the owner is on it no more
            # and the row leaves the list) vs the fake's count at that read; the custom row after the quiet second.
            seen_rows = [p for p in polls if p["row"] is not None and (not moved_at or p["t"] < moved_at[0])]
            at = seen_rows[-1] if seen_rows else {"row": {}, "wire_connects": [0, 0]}
            ref = at["row"].get("refusals") or {}
            rows, chealth, _bad = await _proxies(owner)
            c_conn = _connects(custom, ws_port, t_wall0)
            clean_rows = {s: (h.get("refusals") or {}).get("pct") for s, h in rows.items() if s != flap_slot}
            c_ref = chealth.get("refusals") or {}
            custom_a = {"state": chealth.get("state"), "bad_reason": chealth.get("bad_reason")}

            def band(n):   # share +- PCT_Z binomial sd over n attempts (a fixed [20, 40] flakes at n ~70)
                sd = 100 * math.sqrt(share * (1 - share) / n) if n else 0
                return [round(100 * share - PCT_Z * sd, 1), round(100 * share + PCT_Z * sd, 1)]

            def rate_ok(r, n: int):   # the share alone is shown (an Agency's owner): n from the fake's own CONNECTs
                if n < MIN_CALLS:
                    return False
                lo, hi = band(n)
                p = r.get("pct")
                return p is not None and lo <= p <= hi
            ctx.check(C_RATE_SHOWN, bool(seen_rows) and rate_ok(ref, at["wire_connects"][0]) and rate_ok(c_ref, c_conn[0])
                      and not {"refused", "calls"} & (set(ref) | set(c_ref))
                      and len(clean_rows) == POOL - 1 and all(v == 0 for v in clean_rows.values()),
                      slot=flap_slot, refusals=ref, pct_band=band(at["wire_connects"][0]), wire_connects=at["wire_connects"],
                      read_ms_into_load=round((at["t"] - t0) * 1000, 1) if seen_rows else None,
                      clean_pct=clean_rows, custom_refusals=c_ref, custom_pct_band=band(c_conn[0]),
                      custom_wire_connects=c_conn,
                      why="the Agency owner sees the share alone; pct within the binomial band of the share over the "
                          "fake's CONNECTs")

            # C_FLAP_MOVES (phase A's calls)
            t_moved = (moved_at[0] - t0) * 1000 if moved_at else None
            went_bad = [p for p in polls if p["state"] in BAD or (p["bad"] or 0) >= 1]
            after_move = registry_bindings(reg)
            now_on = {a: after_move.get(a) for a in flappy}
            after = [x for x in seen if x["aid"] in flappy and moved_at and x["t0"] > moved_at[0] + 1.0]
            after_bad = Counter(f"{x['kind']} {x['status']}" for x in after if x["status"] != 200)
            clean_calls = [x for x in seen if x["aid"] in clean]
            clean_bad = Counter(f"{x['kind']} {x['status']}" for x in clean_calls if x["status"] != 200)
            odd = Counter(f"{x['kind']} {x['status']}" for x in seen if x["status"] != 200 and not x["unreachable"])
            with fake.lock:   # the relay sends OF web's `<p>text</p>`: compared on the text inside
                got = Counter(_plain(m["text"]) for ms in fake.sends.values() for m in ms)
            sends = [x for x in seen if x["kind"] == "send"]
            dup = {t: n for t, n in got.items() if n > 1 and t.startswith("slop refusals")}
            lost = [x["text"] for x in sends if x["status"] == 200 and got.get(x["text"], 0) != 1]
            ghost = [x["text"] for x in sends if x["status"] != 200 and got.get(x["text"], 0)]
            reads = [x["ms"] for x in seen if x["kind"] == "read"]
            p95 = pct(reads, 0.95)
            ctx.check(C_FLAP_MOVES, bool(went_bad) and t_moved is not None and t_moved <= flap_ms
                      and all(lb in label_wire and lb != flap_label for lb in now_on.values())
                      and bool(after) and not after_bad and bool(clean_calls) and not clean_bad and not odd
                      and bool(sends) and not dup and not lost and not ghost and p95 is not None
                      and p95 <= INTERACTIVE_P95_MS, budget=True,
                      moved_ms=round(t_moved, 1) if t_moved else None, budget_ms=flap_ms,
                      first_bad_ms=round((went_bad[0]["t"] - t0) * 1000, 1) if went_bad else None, now_on=now_on,
                      after_move_calls=len(after), after_move_not_200=dict(after_bad), clean_calls=len(clean_calls),
                      clean_not_200=dict(clean_bad), not_200_not_unreachable=dict(odd),
                      sends=dict(Counter(x["status"] for x in sends)), duplicated=dup, lost=len(lost), ghost=len(ghost),
                      read_p95_ms=p95, read_p95_budget_ms=INTERACTIVE_P95_MS)

            # ── after the move, two clocks side by side: the moved-away pool proxy's standby (only probes reach it) and,
            # on the custom proxy, phase B (refusing hold_share, every person reading its Creators, the UI shot) then
            # phase C (its refusals stop, the reads go on until it clears) ──
            ctx.rec.stage = "hold"
            custom.set_refuse_share(hold_share)
            t_b = time.perf_counter()
            stop = asyncio.Event()
            hold_people = [asyncio.create_task(person(n, on_custom[n % CUSTOM], stop, sends=False))
                           for n in range(len(picks))]
            hold_states: list[tuple[float, str | None]] = []
            standby: dict = {"at": None, "states": [], "drift": []}
            ui_b: dict = {}
            end_b: dict = {}
            clear: dict = {"bad_at": None, "t": None, "at": None}

            async def hold_poll(until: float) -> None:
                while time.perf_counter() < until:
                    hold_states.append((time.perf_counter() - t_b, (await _proxies(owner))[1].get("state")))
                    await asyncio.sleep(0.5)

            async def standby_poll() -> None:
                if not moved_at:
                    return
                while time.perf_counter() - t_zero < standby_ms / 1000:
                    bad = (await _proxies(owner))[2]
                    standby["states"].append(bad)
                    b = registry_bindings(reg)
                    if bound_aids <= b.keys() and b != after_move:
                        standby["drift"].append({k: (after_move.get(k), v) for k, v in b.items() if after_move.get(k) != v})
                    if bad == 0:
                        standby["at"] = time.perf_counter()
                        return
                    await asyncio.sleep(0.5)

            async def ui_hold() -> None:
                if page:
                    ui_b["row"] = await _ui_row(ctx, page, "2-proxies-refusing", ui_re)
                    ui_b["badges"] = await _ui_badges(ctx, page, "3-accounts-proxy-refusing", ready, CUSTOM)

            async def custom_clock() -> None:
                await asyncio.gather(hold_poll(t_b + hold_s), ui_hold())
                end_b["health"] = (await _proxies(owner))[1]   # end of B, read before the share goes to 0
                end_b["accounts"] = await _accounts(owner, on_custom)
                ctx.rec.stage = "clear"
                clear["bad_at"] = (await _proxies(owner))[1].get("state")
                custom.set_refuse_share(0)
                clear["t"] = time.perf_counter()
                while time.perf_counter() - clear["t"] < clear_ms / 1000:
                    if (await _proxies(owner))[1].get("state") not in BAD:
                        clear["at"] = time.perf_counter()
                        break
                    await asyncio.sleep(0.25)
                stop.set()

            await asyncio.gather(standby_poll(), custom_clock())
            await asyncio.gather(*hold_people)
            ctx.rec.stage = None

            # C_STANDBY_NO_FAILBACK: bindings from the move to the end
            end_bind = registry_bindings(reg)
            ctx.check(C_STANDBY_NO_FAILBACK, bool(moved_at) and standby["at"] is not None and end_bind == after_move
                      and not standby["drift"], budget=True, moved=bool(moved_at),
                      standby_ms=round((standby["at"] - t_zero) * 1000, 1) if standby["at"] else None,
                      budget_ms=standby_ms, pool_bad_last=standby["states"][-1] if standby["states"] else None,
                      bindings_unchanged=end_bind == after_move, drift=standby["drift"][:3])

            # C_HYSTERESIS: never up through phase B (still refusing), bad at its end
            ch_b = end_b.get("health") or {}
            r_b = ch_b.get("refusals") or {}
            acc_b = end_b.get("accounts") or {}
            up_during = [(round(t, 1), st) for t, st in hold_states if st not in BAD]
            hyst_ok = (custom_a["state"] in BAD and custom_a["bad_reason"] == "flapping"
                       and ch_b.get("state") in BAD and ch_b.get("bad_reason") == "flapping"
                       and (r_b.get("pct") or 0) >= STAY_PCT
                       and not up_during and len(acc_b) == CUSTOM and all(v == (True, "flapping") for v in acc_b.values())
                       and (not page or ui_b.get("badges") == CUSTOM))
            ctx.check(C_HYSTERESIS, hyst_ok, end_of_a=custom_a, end_of_b={"state": ch_b.get("state"),
                      "bad_reason": ch_b.get("bad_reason"), "refusals": r_b}, hold_share=hold_share, hold_s=hold_s,
                      stay_pct=STAY_PCT, up_during_b=up_during[:5], polls_b=len(hold_states), accounts=acc_b,
                      ui_badges=ui_b.get("badges") if page else "--no-ui",
                      why="the stay rule (>= X/2 of >= 20 attempts, no recency) holds it; at the 600 s window B's "
                          "attempts blend with A's (pct >= X): the [X/2, X) band alone is the unit test + ...-a337 (60 s window)")

            # C_CLEARS: steadily bad when its refusals stopped (the fault's flicker reads bad ~20 % of the time), then up
            bad_at_c, t_c, cleared_at = clear["bad_at"], clear["t"], clear["at"]
            steady = [st for _t, st in hold_states[-5:]] + [bad_at_c]
            acc_c = await _accounts(owner, on_custom)
            settled_text = badges_c = None
            if page:
                settled_text = await _ui_row(ctx, page, "4-proxies-settled", None)
                badges_c = await _ui_badges(ctx, page, "5-accounts-settled", ready, 0)
            ctx.check(C_CLEARS, len(steady) == 6 and all(st in BAD for st in steady) and cleared_at is not None
                      and len(acc_c) == CUSTOM and all(not v[0] for v in acc_c.values()) and (not page or badges_c == 0),
                      budget=True, steady_bad_before_stop=steady,
                      clear_ms=round((cleared_at - t_c) * 1000, 1) if cleared_at else None,
                      budget_ms=clear_ms, accounts=acc_c, ui_badges=badges_c if page else "--no-ui",
                      settled_row=settled_text)

            if page:
                m = ui_re.search(ui_b.get("row") or "")
                ctx.check(C_UI_TEXT, bool(m) and not ui_re.search(before_text or ""), before=before_text,
                          refusing=ui_b.get("row"), settled=settled_text, api_pct_at_rate_read=c_ref.get("pct"),
                          screenshots=[f"screenshots/{n}.png" for n in SHOTS])
            else:
                ctx.skip(C_UI_TEXT, "--no-ui")
            await http.aclose()

            # evidence only: proxy_unreachable share with today's 2 tries, inflight_peak per proxy (site owner only)
            rows, chealth, _bad = await _proxies(owner)
            flap_reads = [x for x in seen if x["kind"] == "read" and x["aid"] in flappy
                          and (not moved_at or x["t0"] < moved_at[0])]
            cust_reads = [x for x in seen if x["kind"] == "read" and x["aid"] in on_custom]
            hold_reads = [x for x in seen if x["kind"] == "hold"]

            def share_of(xs):
                return round(100.0 * sum(x["unreachable"] for x in xs) / len(xs), 2) if xs else None

            peaks = {f"slot{s}": h.get("inflight_peak") for s, h in sorted(rows.items())}
            if seen_rows:
                peaks[f"slot{flap_slot}"] = at["row"].get("inflight_peak")
            peaks["custom"] = chealth.get("inflight_peak")
            ctx.metric("proxy_refusals", {
                "refuse_share": share, "hold_share": hold_share, "people": len(picks), "flap_slot": flap_slot,
                "moved_ms": round(t_moved, 1) if t_moved else None,
                "standby_ms": round((standby["at"] - t_zero) * 1000, 1) if standby["at"] else None,
                "clear_ms": round((cleared_at - t_c) * 1000, 1) if cleared_at else None,
                "hold_window": r_b,
                "unreachable_pct": {"flappy_reads_before_move": share_of(flap_reads), "n_flappy": len(flap_reads),
                                    "custom_reads_a": share_of(cust_reads), "n_custom_a": len(cust_reads),
                                    "custom_reads_b_c": share_of(hold_reads), "n_b_c": len(hold_reads)},
                "inflight_peak": peaks, "sends": dict(Counter(x["status"] for x in sends)),
                "read_ms": {"n": len(reads), "p50": pct(reads, 0.5), "p95": p95, **{
                    g: {"n": len(xs), "p50": pct(xs, 0.5), "p95": pct(xs, 0.95)} for g, xs in (
                        ("refusing_pool_before_move", [x["ms"] for x in flap_reads]),
                        ("custom_a", [x["ms"] for x in cust_reads]), ("custom_b_c", [x["ms"] for x in hold_reads]),
                        ("clean_pool", [x["ms"] for x in seen if x["kind"] == "read" and x["aid"] in clean]))}},
                "wire_connects": {f"slot{slot_of[lb]}": len(wv.connects) for lb, wv in label_wire.items()}})
            log = (ctx.out / "relay.log").read_text(errors="replace")
            ctx.metric("flap_toggles", {lb: {"bad": len(re.findall(rf"proxy {re.escape(lb)} is DOWN \(refusing", log)),
                                             "back_up": len(re.findall(rf"proxy {re.escape(lb)} is back up", log))}
                                        for lb in (flap_label, CUSTOM_LABEL)})
            ctx.metric("http_people", people_rec.summary())
            ctx.metric("p95_vs_last_green", {"people reads": p95} if p95 is not None else {})
            ctx.metric("p95_vs_last_green_n", {"people reads": len(reads)})
            ctx.note(f"refusing slot {flap_slot} ({share:.0%}) + custom; people {len(picks)}; moved "
                     f"{round(t_moved, 1) if t_moved else None} ms; pool standby "
                     f"{round((standby['at'] - t_zero) * 1000, 1) if standby['at'] else None} ms; custom hold {r_b}; "
                     f"cleared {round((cleared_at - t_c) * 1000, 1) if cleared_at else None} ms",
                     f"proxy_unreachable: {share_of(flap_reads)}% of flappy reads before the move (n {len(flap_reads)}), "
                     f"{share_of(cust_reads)}% custom in A (n {len(cust_reads)}); inflight_peak {peaks}"
                     + (f"; screenshots: {', '.join(f'screenshots/{n}.png' for n in SHOTS)}" if page else ""))
    ctx.check("lib/of_wire.py saw only signed calls it models", fake.unsigned == 0 and not fake.unmodelled,
              unsigned=fake.unsigned, unmodelled=dict(fake.unmodelled), of_calls=len(fake.calls) - n0)
