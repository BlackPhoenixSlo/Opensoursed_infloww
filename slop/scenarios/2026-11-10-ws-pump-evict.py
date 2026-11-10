"""OF build bump / proxy edit evicts every pooled client; realtime keeps flowing.

Prod bug (fixed in service/of_ws.py `_refresh_auth` + server.py `_ws_pump_for_account`'s `client_source`):
sign_rules copied a new OF x_of_rev to every account and called client_pool.evict per account, which retires
the evicted client's signed sessions. Each OF WS pump kept the client it started with, so every reconnect's
GET /users/me raised `OFAPIError: signed session retired; retry with current account session`, forever, on
every account: no realtime DMs. Now the pump re-reads the account's pooled client before each (re)connect.

World: `flat_agency`, ws_pump_evict_creators Creators (small 5 / medium 50), each with a captured session: the
relay's REAL OFClient against lib/of_wire.py (`OF_WIRE`), every Creator's REAL of_ws pump on its socket
(`POST /__slop/pump-supervise`: one real `_reconcile_pumps` pass).

Flow:
  up      every pump connected; OF pushes one fan DM per Creator on its socket (`push_ws`): each must land.
  evict   the owner adds a proxy through the real `POST /admin/proxies` (signed in): the product's
          `_invalidate_client()` = `client_pool.evict(None)`, every pooled client retired, as sign_rules'
          per-account evict does. Then OF ends every Creator's socket (`drop_ws`), all at once.
  after   every pump must reconnect through /users/me on a fresh client within RECONNECT_S; OF pushes one more
          fan DM per Creator on the new socket: each must land.

Checks: C_UP, C_FRAMES_UP, C_EDIT, WS_EVICT_RECONNECT, WS_EVICT_NO_RETIRED (names in lib/of_ws_faults.py),
C_FRAMES_AFTER (SKIP when no socket came back: nothing to push on), C_FRAME_P95 (budget: OF push -> messages
row p95 within FRAME_P95_S, both pushes), plus the stock no-5xx / no-unexpected-Traceback. Side effect: the
`messages` rows (SQL); evidence `ws-connects.json`, `frames.json`.

Bypasses (declared): OnlyFans is lib/of_wire.py (its own declared answers; `push_ws` sends the fan DM frame in
the shape actors/fan_dm.frame uses). The evict is the owner's proxy edit, not sign_rules: CHATTERLY_TEST_MODE
skips server startup's `sign_rules.enable_background()`, so no new x_of_rev seen on the wire starts a refresh,
and no endpoint calls `sign_rules.refresh` (both end in client_pool.evict, which retires the same way). The
pump supervisor's 15 s cadence (the hook; one pass at the start). Seeding by SQL.
Break-it-once: ws-pump-keeps-evicted-client (the fault pins the first client the source returns, so after the
evict every reconnect asks the retired one): WS_EVICT_RECONNECT and
WS_EVICT_NO_RETIRED only (C_FRAMES_AFTER goes SKIP: no socket to push on).
"""
from __future__ import annotations

import asyncio
import json
import time

from slop.actors.fan_dm import frame
from slop.lib.of_ws_faults import WS_EVICT_NO_RETIRED, WS_EVICT_RECONNECT

PROFILE = "flat_agency"
UI = False
OF_WIRE = True
FAULT = "ws-pump-keeps-evicted-client"
PUMP_UP_S = 30.0
RECONNECT_S = 10.0     # the pump's first backoff after a drop is 1 s (of_ws_decide), then /users/me + connect
FRAME_WAIT_S = 15.0
FRAME_P95_S = 3.0      # OF push -> messages row (pump -> _broadcast_event -> persist worker -> transcoder)
RETIRED = "signed session retired"
ME = "GET /api2/v2/users/me"
LABEL = "slop-evict-edit"
MSG_BASE = 9_700_000_000_000

C_UP = "every Creator's WS pump connected through /users/me with the token OF issued"
C_FRAMES_UP = "before the evict: a fan DM OF pushes on each Creator's socket lands as its messages row"
C_EDIT = "the owner's proxy edit (POST /admin/proxies) saved: 200 and listed by GET /admin/proxies"
C_FRAMES_AFTER = "after the reconnect: a fan DM OF pushes on each Creator's new socket lands as its messages row"
C_FRAME_P95 = f"p95 OF push -> messages row <= {FRAME_P95_S:g} s"


async def run(ctx) -> None:
    w, fake, owner = ctx.world, ctx.of_wire, ctx.owner
    w.data["flat_creators"] = int(ctx.param("creators", w.size["ws_pump_evict_creators"]))
    await ctx.build(PROFILE)
    cs = w.data["creators"]
    ids = [c["id"] for c in cs]
    fan_of = {aid: w.data["fans"][aid][0] for aid in ids}
    frames: list[dict] = []
    seq = iter(range(MSG_BASE, MSG_BASE + 10**6))

    async def until(pred, timeout_s: float) -> bool:
        t_end = time.time() + timeout_s
        while not pred():
            if time.time() > t_end:
                return False
            await asyncio.sleep(0.2)
        return True

    def connects(after: float) -> list[dict]:
        with fake.lock:
            return [c for c in fake.ws_connects if c["t"] > after]

    def me_ok(after: float) -> dict[str, float]:
        """Per Creator, the first /users/me OF answered 200 after `after`."""
        out: dict[str, float] = {}
        with fake.lock:
            for c in fake.calls:
                if c["route"] == ME and c["status"] == 200 and c["t"] > after:
                    out.setdefault(c["account"], c["t"])
        return out

    def landed(mids) -> dict[int, float]:
        con = w.sql()
        try:
            rows = con.execute(f"SELECT message_id FROM messages WHERE direction='in' AND message_id IN "
                               f"({','.join('?' * len(mids))})", list(mids)).fetchall()
        finally:
            con.close()
        return {r[0]: time.time() for r in rows}

    async def push_round(phase: str, to: list[str]) -> tuple[list[dict], dict[int, float]]:
        """One fan DM per Creator in `to`, pushed on its socket by OF; waits for their messages rows."""
        sent = []
        for aid in to:
            mid = next(seq)
            t = time.time()
            n = await asyncio.to_thread(fake.push_ws, aid, frame(mid, fan_of[aid], f"after evict? {phase}"))
            sent.append({"phase": phase, "account": aid, "fan": fan_of[aid]["id"], "mid": mid, "t": t, "socks": n})
        want = {s["mid"] for s in sent if s["socks"]}
        seen: dict[int, float] = {}
        t_end = time.time() + FRAME_WAIT_S
        while want - seen.keys() and time.time() < t_end:
            for mid, t in landed(want - seen.keys()).items():
                seen.setdefault(mid, t)
            await asyncio.sleep(0.1)
        for s in sent:
            s["landed_s"] = round(seen[s["mid"]] - s["t"], 3) if s["mid"] in seen else None
        frames.extend(sent)
        return sent, seen

    # ── up: every pump on OF's socket ────────────────────────────────────────
    ctx.rec.stage = "up"
    await owner.post("/__slop/pump-supervise")
    up = await until(lambda: {c["account"] for c in connects(0)} >= set(ids) and set(fake.ws_live()) >= set(ids),
                     PUMP_UP_S)
    first = connects(0)
    ctx.check(C_UP, up and all(c["token_ok"] for c in first),
              connected=len({c["account"] for c in first}), want=len(ids),
              bad_token=[c["account"] for c in first if not c["token_ok"]][:5])
    sent, seen = await push_round("up", ids)
    ctx.check(C_FRAMES_UP, all(s["socks"] == 1 for s in sent) and len(seen) == len(ids),
              pushed=sum(1 for s in sent if s["socks"]), landed=len(seen), want=len(ids),
              missing=[s["account"] for s in sent if s["landed_s"] is None][:5])

    # ── evict: the owner's proxy edit, then OF ends every socket ─────────────
    ctx.rec.stage = "evict"
    log_at = (ctx.out / "relay.log").stat().st_size
    t_evict = time.time()
    made = await owner.post("/admin/proxies", json={"label": LABEL, "scheme": "socks5", "host": "127.0.0.1",
                                                    "port": 1})
    listed = await owner.get("/admin/proxies")
    ctx.check(C_EDIT, made.status_code == 200 and listed.status_code == 200 and LABEL in listed.text,
              post=made.status_code, get=listed.status_code)
    t_drop = time.time()
    dropped = await asyncio.to_thread(fake.drop_ws, ids)

    # ── after: every pump back on a fresh client ─────────────────────────────
    ctx.rec.stage = "after"
    back = await until(lambda: {c["account"] for c in connects(t_drop)} >= set(ids)
                       and set(fake.ws_live()) >= set(ids), RECONNECT_S)
    again = connects(t_drop)
    first_back = {}
    for c in again:
        first_back.setdefault(c["account"], c)
    mes = me_ok(t_drop)
    await asyncio.sleep(1.0)  # the pumps' log lines reach relay.log (stderr, line-buffered)
    after_log = (ctx.out / "relay.log").read_bytes()[log_at:].decode(errors="replace")
    retired = [ln for ln in after_log.splitlines() if RETIRED in ln]
    rebuilt = {a for a in ids if f"OFClient ready (account={a} " in after_log}
    late = sorted(a for a in ids if a not in first_back or first_back[a]["t"] - t_drop > RECONNECT_S)
    ctx.check(WS_EVICT_RECONNECT,
              back and not late and all(first_back[a]["token_ok"] for a in ids)
              and all(a in mes and mes[a] <= first_back[a]["t"] for a in ids) and rebuilt >= set(ids),
              dropped=dropped, reconnected=len(first_back), want=len(ids), late=late[:5],
              me_200=len(mes), rebuilt=len(rebuilt),
              reconnect_s_max=round(max((c["t"] - t_drop for c in first_back.values()), default=0), 2))
    ctx.check(WS_EVICT_NO_RETIRED, not retired, count=len(retired), first=retired[:3])

    live = [a for a in ids if fake.ws_live().get(a)]
    if not live:
        ctx.skip(C_FRAMES_AFTER, "no Creator's socket came back: nothing to push on (see the reconnect check)")
    else:
        sent2, seen2 = await push_round("after", ids)
        ctx.check(C_FRAMES_AFTER, all(s["socks"] == 1 for s in sent2) and len(seen2) == len(ids),
                  pushed=sum(1 for s in sent2 if s["socks"]), landed=len(seen2), want=len(ids),
                  missing=[s["account"] for s in sent2 if s["landed_s"] is None][:5])
    ctx.rec.stage = None

    lat = sorted(s["landed_s"] for s in frames if s["landed_s"] is not None)
    p95 = lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else None
    ctx.check(C_FRAME_P95, None if p95 is None else p95 <= FRAME_P95_S, budget=True, p95_s=p95, n=len(lat))
    ctx.metric("ws_pump_evict", {"creators": len(ids), "evict_to_drop_s": round(t_drop - t_evict, 3),
                                 "reconnect_s": sorted(round(c["t"] - t_drop, 3) for c in first_back.values()),
                                 "retired_lines": len(retired), "frame_p95_s": p95})
    with fake.lock:
        (ctx.out / "ws-connects.json").write_text(json.dumps(fake.ws_connects))
    (ctx.out / "frames.json").write_text(json.dumps(frames))
