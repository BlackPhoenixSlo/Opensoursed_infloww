"""Sales attribution of TIPS and PPV (README.attribution.md): who Employee reports and Sales
records credit when many chatters work the same fans and the fans pay, under Infloww's
Converters rule: "Sale is attributed to the last Chatter who messaged the fan within X hours
and Y minutes of the sale"; nobody messaged in that window -> nobody.

World: `agency_inbox` (1 Agency; small 3 Creators x 50 fans, medium 10 x 500) plus `--users`
chatters, each with its own login (seed/chatters: the real invite + register), each assigned 2
Creators (k and k+1 mod C).

Settings, through the real route (PUT /admin/settings/sales and /time-tracking, backdated to
the epoch so they rule every sale): Converters for Messages and for Posts and tips, the
Converters window 1 h (`attribution.converters_window_seconds` 3600), Time tracking off.

Load: `--set episodes=` per Creator (small 30, medium 120), at most `--users` at once. An
episode is one fan: 1-3 replies by the Creator's chatters (the real send route, each chatter
one send at a time), then the fan pays, then half the time another reply ("thanks"):
  - ledger_tip: a chat tip only OnlyFans' ledger has ("Tip from ...", no message);
  - ws_tip: a tip frame through the pump (POST /__slop/of-ws-frame, serial per Creator);
    its ledger twin is appended after the pump went quiet (the ledger lags the WebSocket);
  - ppv_ws: a chatter sends a PPV (`price`), half the time another chatter replies, the fan
    unlocks it (purchase frame);
  - ppv_ledger: the same, the unlock only in the ledger ("Payment for message from ...").
Each step waits THINK_MS first, so payments, replies after them and scans interleave.
Meanwhile the ledger scan runs per Creator every TICK_S (POST /admin/ingest/transactions/
{aid}/run) and the owner re-reads Employee reports and Sales records every READ_S.
Specials (Creator 0, its first two chatters A and B, before the load): past touches written by
SQL (seed/sales_touches) and one tip each: A 59 min / 61 min before the tip (the 1 h window
+-60 s) and 3 h 29 min / 3 h 31 min (the 3 h 30 min window +-60 s); Automation as the only
touch; A then Automation, A then a mass send by B, Automation then A (ledger tips); WS tips
after A then Automation, and after A then B. Live (the real send route): A sends a PPV, B
replies, the fan unlocks it (`ppv_a_then_b`).

Expected credit (`expect`): every kind (message PPV, WS chat tip linked to the fan's own tip
message, standalone ledger tip) -> the last HUMAN chatter's 1:1 send to the fan at or before
the sale, within the window, else nobody; Automation (the sentinel Employee, `automation_kind`)
and mass sends are never a touch; a PPV's sender is not credited for being its sender.

Checks (credit read through the real report routes; no SQL):
  per kind (TIP_LEDGER, TIP_WS, PPV), a new chatter's reply after the payment (TIP_AFTER), the 1 h
  window's edges (WINDOW) and the automation/mass specials (AUTO), Employee report totals per
  Employee == expected to the cent (TOTALS) and == Sales records summed (AGREE); then each
  settings change, saved through the route and re-read: the window changed to 3 h 30 min
  (WINDOW330: the saved value read back and every sale re-expected, the read path's per-sale
  window), Exclude the 20% fee (same Employee, net amount), Message sender (SENDER: a linked
  sale -> its message's sender, so a PPV -> its sender A though B chatted later and a WS tip ->
  nobody; a ledger tip has no message and is Posts and tips, so it keeps the Converters read),
  Shift schedule with Time tracking off (the product falls back to Converters, with the
  fallback line), and a change saved effective now recredits nothing earlier; nothing dropped
  (one sale per payment), every reply stamped with its chatter's Employee (STAMP), ledger
  scans settled; budgets: WS tip frame -> owner /events p95, report route p95s, send route p95.
  With UI: the Sales settings page shows the window as 1 h 0 min, saves 3 h 30 min, and
  GET /admin/settings/sales reads 12600 (screenshots `trigger-sales-converters-window`,
  `settled-sales-converters-window-saved`).

Break-it-once: converters-first-chatter (the default; TIP_LEDGER, TIP_WS, PPV, TOTALS,
WINDOW330 go red); `--fault=converters-window-ignored` (WINDOW330); `--fault=converters-
counts-automation` (AUTO, TOTALS, WINDOW330); `--fault=chatter-send-unstamped` (STAMP, PPV,
TIP_LEDGER, TIP_WS, TOTALS, WINDOW330, SENDER).

Declared bypasses:
  - OnlyFans' payouts ledger is a file (lib/attribution_relay.py, `of-ledger.jsonl`); the
    scan runs only when POSTed (the tx-ingest supervisor is off under CHATTERLY_TEST_MODE).
  - Past touches (hours ago, Automation, mass) are SQL rows in the product's shape: no
    actor can send in the past, run an automation for a chosen fan, or reach OF's mass API.
  - Chatters' mirror Employees are SQL rows (seed/sales_touches.employees) before any send, the
    row the first send would create, so a fault on the send path cannot change the load.
  - A WS tip's ledger twin is appended only after the pump is quiet, and WS-unlocked PPVs
    have no ledger twin (separate fans from ledger PPVs): the product links a ledger tip to a
    WS tip by fingerprint but never a ledger PPV to a WS unlock (`_ENABLE_PPV_FINGERPRINT`
    False), so a twin would count twice; that is a product limit this run does not test.
  - Chatters reach the relay directly (no Next proxy).
Not provable here: a tip ingested BEFORE an outbound row whose createdAt precedes it (the
fake OF stamps createdAt at answer time); tx_rollup's message-insert re-credit is covered by
its unit tests only.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from slop.actors import fan_dm, focus, manager, ui
from slop.lib.attribution_faults import (AUTO, PPV, SENDER, STAMP, TIP_AFTER, TIP_LEDGER, TIP_WS, TOTALS, WINDOW,
                                         WINDOW330)
from slop.seed import chatters as chatters_seed
from slop.seed import sales_touches

PROFILE = "agency_inbox"
UI = True
FAULT = "converters-first-chatter"
E2E_P95_MS = 500           # a WS tip frame handed to the relay -> on the owner's /events
# The send route's budget is a STRESS budget: THINK_MS pacing offers ~100 sends/s at medium
# --users=200 (measured 99/s), ~50x chatter-crowd's measured chatter (a send every 10-30 s),
# which owns the realistic 750 ms gate; dense sends are what make the credit races likely.
P95_MS = {"GET /admin/stats/per-employee": 1000, "GET /admin/stats/sales-records": 1000,
          "POST /api/of/v2/chats/:id/messages": 1500}
EPISODES = {"small": 30, "medium": 120, "huge": 300}   # per Creator
WINDOW_S = 3600             # the Converters window this run saves first (the product's default)
WINDOW_330_S = 3 * 3600 + 30 * 60
TICK_S, READ_S = 1.0, 0.5
THINK_MS = (50, 400)        # a chatter reads and types before each step (timing only, never the credit)
SETTLE_S = 90
EPOCH = "1970-01-01T00:00:00Z"
TIP_FRAME_BASE = 9_750_000_000_000   # between fan_dm's bands and sales_touches' 9.8e12
LEDGER_ID_BASE = 7_700_000_000
KINDS = (("ledger_tip", 35), ("ws_tip", 25), ("ppv_ws", 20), ("ppv_ledger", 20))
PPV_KINDS = ("ppv_ws", "ppv_ledger")
LINKED_KINDS = ("ws_tip", *PPV_KINDS)   # the sale carries a message_id (a ledger tip has none)
FALLBACK_LINE = "Shift schedule needs Time tracking on; credited by Converters."
# Specials (Creator 0): name -> (touches as (minutes before the tip, who), how the fan pays).
SPECIALS = {
    "edge_in": ([(59, "A")], "ledger_tip"),        # 1 h - 60 s: A
    "edge_out": ([(61, "A")], "ledger_tip"),       # 1 h + 60 s: nobody (A under 3 h 30 min)
    "w330_in": ([(209, "A")], "ledger_tip"),       # 3 h 30 min - 60 s: nobody under 1 h, A under 3 h 30 min
    "w330_out": ([(211, "A")], "ledger_tip"),      # 3 h 30 min + 60 s: nobody under both
    "auto_last": ([(30, "auto")], "ledger_tip"),
    "human_then_auto": ([(50, "A"), (20, "auto")], "ledger_tip"),
    "human_then_mass": ([(50, "A"), (20, "massB")], "ledger_tip"),
    "auto_then_human": ([(40, "auto"), (20, "A")], "ledger_tip"),
    "ws_human_then_auto": ([(50, "A"), (20, "auto")], "ws_tip"),
    "ws_a_then_b": ([(50, "A"), (20, "B")], "ws_tip"),
}
LIVE_SPECIAL = "ppv_a_then_b"   # A sends a PPV, B replies, the fan unlocks it (the real routes)
WINDOW_SPECIALS = ("edge_in", "edge_out", "w330_in", "w330_out")
AUTO_SPECIALS = ("auto_last", "human_then_auto", "human_then_mass", "auto_then_human", "ws_human_then_auto")

AGREE = "Employee reports == Sales records summed per Employee, to the cent"
FEE = ("Exclude the 20% OnlyFans fee on: each sale keeps its Employee, credited at OnlyFans' net (else 80% "
       "rounded down); Employee reports == expected to the cent")
SHIFT = ("Shift schedule with Time tracking off: every sale keeps its Converters credit (Sales records and "
         "Employee reports) and the report shows the fallback line")
VERSION = "a Sales change saved effective now (fee excluded) recredits no earlier sale (Employee reports unchanged)"
COUNT = ("nothing dropped: every send and frame 2xx, every payment exactly one sale in Sales records "
         "(a WS tip and its ledger twin are one)")
SCANS = "ledger scans settled: no error, rows inserted == ledger-only payments, every WS tip promoted by its twin"
UI_SAVE = ("Sales settings page: the Converters window shows 1 h 0 min, Save with 3 h 30 min answers 200 and "
           "shows Saved, GET /admin/settings/sales reads converters_window_seconds 12600")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds") + "+00:00"


def _parse(s) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).replace(tzinfo=None)


def _p(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * q))]


class Ledger:
    """OnlyFans' payouts ledger as lib/attribution_relay.py reads it (one line per row)."""

    def __init__(self, path):
        self.path, self.n = path, 0

    def add(self, aid: str, fan: int, cents: int, at: datetime, what: str) -> int:
        self.n += 1
        fee = round(cents * 0.2)
        row = {"id": LEDGER_ID_BASE + self.n, "user": {"id": fan}, "amount": cents / 100, "currency": "USD",
               "createdAt": _iso(at), "status": "done", "net": (cents - fee) / 100, "fee": fee / 100,
               "vatAmount": 0, "description": f"{what} u{fan}"}
        with self.path.open("a") as f:
            f.write(json.dumps({"account_id": aid, "row": row}) + "\n")
        return cents - fee


def expect(sale: dict, touches: list[dict], window_s: int) -> int | None:
    """Converters: the last human chatter's 1:1 send to the fan at or before the sale, within
    `window_s` (inclusive), else nobody. Automation and mass sends are never a touch; the send
    order is (created_at, message_id), as the product's lookback orders it."""
    at, lo = sale["at"], sale["at"] - timedelta(seconds=window_s)
    xs = [t for t in touches if lo <= t["at"] <= at and not (t["auto"] or t["mass"])]
    return max(xs, key=lambda t: (t["at"], t["mid"]))["emp"] if xs else None


def _plan(w, creators: list[str], fans: dict, by_creator: dict, n_ep: int, taken: set) -> list[dict]:
    rng = w.rng("sales-attribution")
    names, weights = [k for k, _ in KINDS], [x for _, x in KINDS]
    eps = []
    for aid in creators:
        pool = [f for f in fans[aid] if f["id"] not in taken]
        rng.shuffle(pool)
        ch = by_creator[aid]
        for f in pool[:n_ep]:
            kind = rng.choices(names, weights)[0]
            steps: list[tuple] = []
            if kind in PPV_KINDS:
                a = rng.choice(ch)
                if rng.random() < 0.3:
                    steps.append(("reply", rng.choice(ch)))
                steps.append(("ppv", a))
                others = [x for x in ch if x != a]
                if others and rng.random() < 0.5:
                    steps.append(("reply", rng.choice(others)))   # another chatter after the PPV
            elif kind == "ws_tip" and rng.random() < 0.5:
                one = rng.choice(ch)
                steps += [("reply", one)] * rng.randint(1, 3)      # one chatter: the sole-chatter credit
            else:
                steps += [("reply", rng.choice(ch)) for _ in range(rng.randint(1, 3))]
            steps.append(("pay",))
            if rng.random() < 0.5:
                steps.append(("reply", rng.choice(ch)))            # "thanks", after the payment
            eps.append({"aid": aid, "fan": f, "kind": kind, "steps": steps, "cents": rng.randint(300, 5000),
                        "think": [rng.randint(*THINK_MS) / 1000 for _ in steps]})
    rng.shuffle(eps)
    return eps


async def run(ctx) -> None:
    if ctx.users < 2:
        raise ValueError("--users must be >= 2 (the specials need two chatters on Creator 0)")
    w = await ctx.build(PROFILE)
    creators = [c["id"] for c in w.data["creators"]]
    fans = w.data["fans"]
    C = len(creators)
    n_ep = ctx.param("episodes", EPISODES[ctx.scale])
    owner = ctx.owner

    async def put(tab: str, blob: dict, effective_from: str | None = EPOCH) -> None:
        r = await owner.put(f"/admin/settings/{tab}", json=blob,
                            **({"params": {"effective_from": effective_from}} if effective_from else {}))
        if r.status_code != 200:
            raise RuntimeError(f"PUT /admin/settings/{tab}: {r.status_code} {r.text[:300]}")

    def sales_blob(messages="converters", posts_tips="converters", fee=False, window=WINDOW_S) -> dict:
        return {"exclude_welcome": False, "exclude_of_fee": fee, "multi_employee_shift": False,
                "attribution": {"messages": messages, "posts_tips": posts_tips,
                                "subscriptions_chatter_opt_in": False, "converters_window_seconds": window}}

    async def saved_window():
        r = await owner.get("/admin/settings/sales")
        return r.json()["config"].get("attribution", {}).get("converters_window_seconds") if r.status_code == 200 \
            else f"GET {r.status_code}"

    await put("sales", sales_blob())
    await put("time-tracking", {"enabled": False})

    # Chatters: own logins, 2 Creators each; their mirror Employees before any send.
    names = [f"attr-c{k:03d}" for k in range(ctx.users)]
    assign = [sorted({creators[k % C], creators[(k + 1) % C]}) for k in range(ctx.users)]
    recs = await chatters_seed.seed(w, owner, w.user_id, names, account_ids=assign)
    emp = sales_touches.employees(w, recs)
    by_creator = {aid: [k for k, r in enumerate(recs) if aid in r["account_ids"]] for aid in creators}
    chatters = [focus.Chatter(r, r["account_ids"][0]) for r in recs]
    sem = asyncio.Semaphore(20)

    async def login(c):
        async with sem:
            return await c.login(ctx.relay, ctx.rec)

    logins = await asyncio.gather(*(login(c) for c in chatters))
    ctx.check("every chatter signed in with its own login (POST /chatter/login 200)",
              all(s == 200 for s in logins), bad=sum(s != 200 for s in logins), chatters=len(chatters))
    locks = [asyncio.Lock() for _ in chatters]
    frame_locks = {aid: asyncio.Lock() for aid in creators}
    ledger = Ledger(ctx.stack.tmp / "of-ledger.jsonl")
    ledger.path.write_text("")
    pump = owner.share(limits=max(10, C))
    touches: dict[tuple, list[dict]] = defaultdict(list)
    sales: list[dict] = []
    replies: list[dict] = []
    frames: list[dict] = []
    twins: list[tuple] = []
    tip_ids = iter(range(TIP_FRAME_BASE, TIP_FRAME_BASE + 10**9))

    sse = manager.SseListener(owner.share())
    await sse.start()

    async def send(k: int, aid: str, fan_id: int, sale: dict, *, ppv: bool, paid: bool) -> None:
        async with locks[k]:
            r = await chatters[k].reply(aid, fan_id, "slop ppv" if ppv else "slop reply",
                                        price=sale["cents"] / 100 if ppv else 0)
        r.update(chatter=recs[k]["username"], ppv=ppv, after_pay=paid)
        replies.append(r)
        if r["status"] < 300 and r["id"] is not None:
            e = emp[recs[k]["username"]]
            touches[(aid, fan_id)].append({"at": _parse(r["created_at"]), "emp": e, "mid": int(r["id"]),
                                           "auto": False, "mass": False})
            if ppv:
                sale.update(sender=e, ppv_id=int(r["id"]))
            if paid:
                sale["after"] = True
        await asyncio.sleep(0.003)

    async def pay(sale: dict, fan: dict) -> None:
        aid, cents, kind = sale["aid"], sale["cents"], sale["kind"]
        await asyncio.sleep(0.003)  # strictly after the last reply's createdAt (ms)
        if kind in ("ledger_tip", "ppv_ledger"):
            sale["at"] = _now()
            sale["net"] = ledger.add(aid, fan["id"], cents, sale["at"],
                                     "Tip from" if kind == "ledger_tip" else "Payment for message from")
        else:
            async with frame_locks[aid]:   # the pump: one frame in flight per Creator
                if kind == "ws_tip":
                    mid = next(tip_ids)
                    fr = fan_dm.frame(mid, fan, "slop tip", tip_dollars=cents / 100)
                    sale["at"] = _parse(fr["api2_chat_message"]["createdAt"])
                else:
                    mid = sale["ppv_id"]
                    fr = fan_dm.purchase_frame(mid, fan, cents / 100)
                    sale["at"] = _parse(fr["purchase"]["openedAt"])
                t0 = time.time() * 1000
                r = await fan_dm.inject(pump, aid, fr)
                frames.append({"kind": kind, "message_id": mid, "status": r.status_code, "t0": t0})
            if kind == "ws_tip":
                twins.append((aid, fan["id"], cents, sale["at"], sale))
        await asyncio.sleep(0.003)  # a reply after the payment is strictly after it

    # Specials: SQL touches in the past, then the tip (Creator 0, its first two chatters).
    c0 = creators[0]
    rng_s = w.rng("sales-attribution:specials")
    pool0 = list(fans[c0])
    rng_s.shuffle(pool0)
    special_fans = dict(zip((*SPECIALS, LIVE_SPECIAL), pool0))
    kA, kB = by_creator[c0][:2]
    A, B = emp[recs[kA]["username"]], emp[recs[kB]["username"]]
    who = {"A": A, "B": B, "massB": B, "auto": emp["Automation"]}
    t_ref = _now()
    rows = []
    for name, (spec, _kind) in SPECIALS.items():
        for mins, x in spec:
            rows.append({"account_id": c0, "fan_id": special_fans[name]["id"], "employee_id": who[x],
                         "at": t_ref - timedelta(minutes=mins), "mass": x == "massB",
                         **({"automation_kind": "autoreply"} if x == "auto" else {})})
    for t in sales_touches.seed(w, rows):
        touches[(c0, t["fan_id"])].append({"at": t["at"], "emp": t["employee_id"], "mid": t["message_id"],
                                           "auto": t.get("automation_kind") is not None, "mass": bool(t["mass"])})
    for name, (_spec, kind) in SPECIALS.items():
        f = special_fans[name]
        sale = {"aid": c0, "fan": f["id"], "kind": kind, "cents": 1000 + 111 * len(sales), "sender": None,
                "net": None, "special": name, "after": False}
        await pay(sale, f)
        sales.append(sale)
    # Live: A sends a PPV, B replies, the fan unlocks it (Converters: B; Message sender: A).
    f = special_fans[LIVE_SPECIAL]
    sale = {"aid": c0, "fan": f["id"], "kind": "ppv_ws", "cents": 1000 + 111 * len(sales), "sender": None,
            "net": None, "special": LIVE_SPECIAL, "after": False, "ppv_id": None}
    await send(kA, c0, f["id"], sale, ppv=True, paid=False)
    await send(kB, c0, f["id"], sale, ppv=False, paid=False)
    if sale["ppv_id"] is not None:
        await pay(sale, f)
        sales.append(sale)

    # Load: episodes, the ledger scan and the owner's report reads alongside.
    eps = _plan(w, creators, fans, by_creator, n_ep, {f["id"] for f in special_fans.values()})
    stop = asyncio.Event()

    async def every(s: float, fn) -> int:
        n = 0
        while not stop.is_set():
            await fn()
            n += 1
            try:
                await asyncio.wait_for(stop.wait(), s)
            except asyncio.TimeoutError:
                pass
        return n

    reader = owner.share(limits=4)
    d0, d1 = (_now() - timedelta(days=1)).date(), (_now() + timedelta(days=1)).date()
    per_emp_url = f"/admin/stats/per-employee?from={d0}&to={d1}&by_account=true"
    rec_url = f"/admin/stats/sales-records?from={d0}&to={d1}"

    async def tick() -> None:
        for aid in creators:
            await owner.post(f"/admin/ingest/transactions/{aid}/run")

    async def read() -> None:
        await asyncio.gather(reader.get(per_emp_url), reader.get(rec_url + "&limit=50"), return_exceptions=True)

    esem = asyncio.Semaphore(ctx.users)

    async def episode(ep: dict) -> None:
        aid, fan = ep["aid"], ep["fan"]
        sale = {"aid": aid, "fan": fan["id"], "kind": ep["kind"], "cents": ep["cents"], "sender": None,
                "net": None, "special": None, "after": False, "ppv_id": None}
        paid = False
        async with esem:
            for st, think in zip(ep["steps"], ep["think"]):
                await asyncio.sleep(think)
                if st[0] == "pay":
                    if ep["kind"] == "ppv_ws" and sale["ppv_id"] is None:
                        sale["failed"] = "no PPV id"
                    else:
                        await pay(sale, fan)
                    paid = True
                    continue
                await send(st[1], aid, fan["id"], sale, ppv=st[0] == "ppv", paid=paid)
        if "at" in sale:
            sales.append(sale)

    t_load = time.time()
    bg = [asyncio.create_task(every(TICK_S, tick)), asyncio.create_task(every(READ_S, read))]
    await asyncio.gather(*(episode(ep) for ep in eps))
    stop.set()
    ticks, reads = await asyncio.gather(*bg)
    load_s = time.time() - t_load
    stats = await manager.quiesce(owner)
    await asyncio.sleep(1.0)
    await sse.stop()

    # The ledger catches up with the WebSocket: the WS tips' twins, then the last scans.
    for aid, fan, cents, at, sale in twins:
        sale["net"] = ledger.add(aid, fan, cents, at, "Tip in chat from")
    settled = await _settle(owner, creators)

    # ---- Reads: the report routes, phase by phase -------------------------------------------
    async def records() -> list[dict]:
        out, before = [], None
        while True:
            r = await owner.get(rec_url + "&limit=500" + (f"&before_id={before}" if before else ""))
            r.raise_for_status()
            body = r.json()
            out += body["rows"]
            before = body.get("next_before_id")
            if not before:
                return out

    async def report() -> tuple[dict, str | None]:
        r = await owner.get(per_emp_url)
        r.raise_for_status()
        body = r.json()
        return ({e["employee_id"]: e["revenue_cents"] for e in body["employees"] if e["revenue_cents"]},
                body.get("attribution_fallback"))

    def by_fan(rows: list[dict]) -> dict[tuple, list[dict]]:
        out = defaultdict(list)
        for r in rows:
            out[(str(r["account_id"]), int(r["fan_id"]))].append(r)
        return out

    def amount(s: dict, fee: bool) -> int:
        return (s["net"] if s["net"] is not None else s["cents"] * 8 // 10) if fee else s["cents"]

    def want_of(phase: str):
        """The Employee each sale should credit in `phase`. converters / window330: `expect` with
        that window. A setting's phase checks only that setting's change against the 1 h
        Converters read (`base`): fee and shift_off (the product falls back to Converters) keep
        it; sender credits a linked sale to its message's sender (a WS tip's message is the
        fan's own: nobody) and leaves a ledger tip (no message: Posts and tips) on Converters."""
        if phase in ("converters", "window330"):
            window = WINDOW_S if phase == "converters" else WINDOW_330_S
            return lambda s: expect(s, touches[(s["aid"], s["fan"])], window)

        def base(s):
            got = fan_rows.get((s["aid"], s["fan"]), [])
            return got[0]["employee_id"] if len(got) == 1 else "no single converters row"
        if phase == "sender":
            return lambda s: s["sender"] if s["kind"] in LINKED_KINDS else base(s)
        return base

    def compare(phase: str, rows: dict, subset: list[dict], fee: bool = False) -> dict:
        want_fn, bad = want_of(phase), []
        for s in subset:
            want = want_fn(s)
            got = rows.get((s["aid"], s["fan"]), [])
            ok = len(got) == 1 and got[0]["employee_id"] == want and got[0]["earnings_cents"] == amount(s, fee)
            if not ok:
                bad.append({"fan": s["fan"], "kind": s["kind"], "special": s["special"], "want": want,
                            "got": [(g["employee_id"], g["earnings_cents"], g["rule"]) for g in got],
                            "cents": amount(s, fee)})
        return {"n": len(subset), "mismatches": len(bad), "sample": bad[:6]}

    def totals(phase: str, fee: bool = False) -> dict:
        want_fn, out = want_of(phase), Counter()
        for s in sales:
            out[want_fn(s)] += amount(s, fee)
        return {k: v for k, v in out.items() if v}

    def diff(got: dict, want: dict) -> list:
        return [{"employee_id": k, "got": got.get(k, 0), "want": want.get(k, 0)}
                for k in sorted(set(got) | set(want), key=lambda x: (x is None, x or 0))
                if got.get(k, 0) != want.get(k, 0)]

    rows1 = await records()
    fan_rows = by_fan(rows1)
    rep1, fb1 = await report()
    ep_sales = [s for s in sales if s["special"] is None]
    kinds = Counter(s["kind"] for s in sales)
    ctx.metric("load", {"episodes": len(eps), "sales": len(sales), "by_kind": dict(kinds),
                        "replies": len(replies), "frames": len(frames), "ledger_rows": ledger.n,
                        "scan_posts": ticks, "report_reads": reads, "seconds": round(load_s, 1),
                        "window_s": WINDOW_S, "users": ctx.users})

    sub = {
        TIP_LEDGER: [s for s in ep_sales if s["kind"] == "ledger_tip"],
        TIP_WS: [s for s in sales if s["kind"] == "ws_tip" and s["special"] in (None, "ws_a_then_b")],
        PPV: [s for s in sales if s["kind"] in PPV_KINDS],
        WINDOW: [s for s in sales if s["special"] in WINDOW_SPECIALS],
        AUTO: [s for s in sales if s["special"] in AUTO_SPECIALS],
    }
    results = {}
    for name, subset in sub.items():
        res = results[name] = compare("converters", fan_rows, subset)
        if subset:
            ctx.check(name, res["mismatches"] == 0, **res)
        else:
            ctx.skip(name, "no sale of this kind in the run")
    # A reply after the payment: its chatter, if it never touched the fan before, gets nothing.
    after_bad, after_n = [], 0
    for s in sales:
        tt = touches[(s["aid"], s["fan"])]
        late = {t["emp"] for t in tt if t["at"] > s["at"]} - {t["emp"] for t in tt if t["at"] <= s["at"]}
        if not late:
            continue
        after_n += 1
        got = [r["employee_id"] for r in fan_rows.get((s["aid"], s["fan"]), [])]
        if set(got) & late:
            after_bad.append({"fan": s["fan"], "kind": s["kind"], "got": got, "after_only": sorted(late)})
    if after_n:
        ctx.check(TIP_AFTER, not after_bad, sales_with_a_new_chatter_after=after_n, wrong=len(after_bad),
                  sample=after_bad[:6])
    else:
        ctx.skip(TIP_AFTER, "no sale got a reply from a new chatter after the payment")
    want1 = totals("converters")
    ctx.check(TOTALS, not diff(rep1, want1), wrong=diff(rep1, want1)[:8], employees=len(want1),
              cents=sum(want1.values()))
    rec_sum = Counter()
    for r in rows1:
        rec_sum[r["employee_id"]] += r["earnings_cents"]
    ctx.check(AGREE, not diff(rep1, dict(rec_sum)), wrong=diff(rep1, dict(rec_sum))[:8])

    bad_sends = [r for r in replies if r["status"] >= 300 or r["id"] is None]
    bad_frames = [f for f in frames if f["status"] >= 300]
    want_keys = Counter((s["aid"], s["fan"]) for s in sales)
    extra = {k: len(v) for k, v in fan_rows.items() if len(v) != want_keys.get(k, 0)}
    unpaid = [s["fan"] for s in ep_sales if s.get("failed")]
    ctx.check(COUNT, not bad_sends and not bad_frames and not extra and not unpaid
              and len(rows1) == len(sales) and not stats.get("timed_out"),
              sales=len(sales), records=len(rows1), bad_sends=len(bad_sends), bad_frames=len(bad_frames),
              wrong_count_fans=list(extra.items())[:6], unpaid=unpaid[:6], persist_drops=stats.get("persist_drops"))
    ws_n = sum(1 for s in sales if s["kind"] == "ws_tip")
    ledger_only = sum(1 for s in sales if s["kind"] in ("ledger_tip", "ppv_ledger"))
    ws_promoted = sum(1 for s in sales if s["kind"] == "ws_tip" and len(fan_rows.get((s["aid"], s["fan"]), [])) == 1
                      and fan_rows[(s["aid"], s["fan"])][0]["net_cents"] is not None)
    ctx.check(SCANS, settled["ok"] and settled["inserted"] == ledger_only and ws_promoted == ws_n,
              inserted=settled["inserted"], ledger_only=ledger_only, ws_tips=ws_n, ws_promoted=ws_promoted,
              errors=settled["errors"], waited_s=settled["seconds"])

    # Every reply: one outbound row, stamped with its own chatter's Employee (thread read).
    async def thread(key):
        async with sem:
            return key, await manager.thread_messages(owner, key[0], key[1], limit=200)

    keys = sorted({(r["aid"], r["fan"]) for r in replies if r["id"] is not None})
    threads = dict(await asyncio.gather(*(thread(k) for k in keys)))
    bad_stamp = []
    for r in replies:
        if r["id"] is None:
            continue
        rows_ = [m for m in threads.get((r["aid"], r["fan"]), []) if int(m["message_id"]) == int(r["id"])]
        want = emp[r["chatter"]]
        if len(rows_) != 1 or rows_[0].get("direction") != "out" or rows_[0].get("sent_by_employee_id") != want:
            bad_stamp.append({"id": r["id"], "rows": len(rows_), "want": want,
                              "got": [m.get("sent_by_employee_id") for m in rows_]})
    ctx.check(STAMP, not bad_stamp, replies=len(replies), wrong=len(bad_stamp), sample=bad_stamp[:5])

    # The Converters window changed to 3 h 30 min, saved through the route and read back.
    await put("sales", sales_blob(window=WINDOW_330_S))
    saved = await saved_window()
    rows_w, (rep_w, _) = by_fan(await records()), await report()
    res = compare("window330", rows_w, sales)
    want_w = totals("window330")
    ctx.check(WINDOW330, saved == WINDOW_330_S and res["mismatches"] == 0 and not diff(rep_w, want_w),
              saved_window_s=saved, **res, wrong_totals=diff(rep_w, want_w)[:6])
    specials_330 = {s["special"]: [(r["employee_id"], r["rule"]) for r in rows_w.get((s["aid"], s["fan"]), [])]
                    for s in sales if s["special"]}

    # Exclude the 20% OnlyFans fee.
    await put("sales", sales_blob(fee=True))
    rows_fee, (rep_fee, _) = by_fan(await records()), await report()
    res = compare("fee", rows_fee, sales, fee=True)
    want_fee = totals("fee", fee=True)
    ctx.check(FEE, res["mismatches"] == 0 and not diff(rep_fee, want_fee), **res,
              wrong_totals=diff(rep_fee, want_fee)[:6])

    # Message sender.
    await put("sales", sales_blob(messages="sender"))
    rows_s, (rep_s, _) = by_fan(await records()), await report()
    res = compare("sender", rows_s, sales)
    want_s = totals("sender")
    ctx.check(SENDER, res["mismatches"] == 0 and not diff(rep_s, want_s), **res,
              wrong_totals=diff(rep_s, want_s)[:6])

    # Shift schedule, Time tracking off.
    await put("sales", sales_blob(messages="shift", posts_tips="shift"))
    rows_sh, (rep_sh, fb_sh) = by_fan(await records()), await report()
    res = compare("shift_off", rows_sh, sales)
    want_sh = totals("shift_off")
    want_fb = FALLBACK_LINE
    ctx.check(SHIFT, res["mismatches"] == 0 and not diff(rep_sh, want_sh) and fb_sh == want_fb, **res,
              wrong_totals=diff(rep_sh, want_sh)[:6], fallback=fb_sh, want_fallback=want_fb)

    # A change saved effective now: no earlier sale recredited.
    await put("sales", sales_blob())
    await put("sales", sales_blob(fee=True), effective_from=None)
    rep_v, _ = await report()
    ctx.check(VERSION, rep_v == rep1, wrong=diff(rep_v, rep1)[:6], fallback_before=fb1)

    # Budgets.
    sent_at = {f["message_id"]: f["t0"] for f in frames if f["kind"] == "ws_tip" and f["status"] < 300}
    e2e = [sse.received_at[m] - t0 for m, t0 in sent_at.items() if m in sse.received_at]
    ctx.metric("e2e_ms", {"n": len(e2e), "of": len(sent_at),
                          **({"p50": round(_p(e2e, .5), 1), "p95": round(_p(e2e, .95), 1)} if e2e else {})})
    name = f"e2e p95 (WS tip frame handed to relay -> on the owner's /events) < {E2E_P95_MS}ms"
    if e2e:
        ctx.check(name, _p(e2e, 0.95) < E2E_P95_MS and len(e2e) == len(sent_at), budget=True,
                  p95=round(_p(e2e, 0.95), 1), n=len(e2e), missing=len(sent_at) - len(e2e))
    else:
        ctx.skip(name, "no WS tip frame reached /events")
    routes = ctx.rec.summary()
    for route, budget in P95_MS.items():
        if route in routes:
            ctx.check(f"p95 {route} < {budget}ms", routes[route]["p95_ms"] < budget, budget=True,
                      p95=routes[route]["p95_ms"], n=routes[route]["n"],
                      **({"offered_sends_per_s": round(len(replies) / load_s, 1)} if "chats" in route else {}))
        else:
            ctx.skip(f"p95 {route} < {budget}ms", "no samples")

    ctx.metric("credit", {k: {"n": v["n"], "mismatches": v["mismatches"]} for k, v in results.items()})
    ctx.metric("specials", {s["special"]: {
        "want_1h": expect(s, touches[(s["aid"], s["fan"])], WINDOW_S),
        "want_3h30m": expect(s, touches[(s["aid"], s["fan"])], WINDOW_330_S),
        "sender": s["sender"],
        "got_1h": [(r["employee_id"], r["rule"]) for r in fan_rows.get((s["aid"], s["fan"]), [])],
        "got_3h30m": specials_330.get(s["special"]),
        "got_sender": [(r["employee_id"], r["rule"]) for r in rows_s.get((s["aid"], s["fan"]), [])]}
        for s in sales if s["special"]})
    ctx.metric("employee_ids", {"A": A, "B": B, "Automation": emp["Automation"]})
    ctx.note("Product notes (not this flow's change): Shift schedule with Time tracking off falls back to "
             "Converters (the report's fallback line); under Message sender a ledger-only tip has no message, "
             "so it is Posts and tips and keeps the Converters credit.")

    # The Sales settings page: the window's hours and minutes, saved as an owner saves (effective now).
    if ctx.app is None:
        ctx.skip(UI_SAVE, "--no-ui")
    else:
        await _ui_window(ctx, saved_window)
    for c in chatters:
        await c.close()
    await asyncio.gather(pump.aclose(), reader.aclose())


async def _settle(owner, creators: list[str]) -> dict:
    """Per Creator: one scan queued after the last ledger append (A), then another (B), which
    waits on A's tick lock; B started => A and its relink are done."""
    t0 = time.time()

    async def queue(aid: str) -> datetime | None:
        while time.time() - t0 < SETTLE_S:
            at = _now()
            r = await owner.post(f"/admin/ingest/transactions/{aid}/run")
            if r.status_code == 202:
                return at
            if r.status_code != 409:
                return None
            await asyncio.sleep(0.2)
        return None

    async def one(aid: str) -> bool:
        if await queue(aid) is None:
            return False
        qb = await queue(aid)
        if qb is None:
            return False
        while time.time() - t0 < SETTLE_S:
            h = next((a for a in (await owner.get("/admin/ingest/transactions/health")).json()["accounts"]
                      if str(a["account_id"]) == str(aid)), None)
            if h and h["last_scan_at"] and _parse(h["last_scan_at"]) >= qb and h["current_status"] not in (
                    "refreshing", "backfilling"):
                return True
            await asyncio.sleep(0.2)
        return False

    oks = await asyncio.gather(*(one(a) for a in creators))
    health = (await owner.get("/admin/ingest/transactions/health")).json()["accounts"]
    mine = [a for a in health if str(a["account_id"]) in {str(c) for c in creators}]
    errors = [(a["account_id"], a["last_error"]) for a in mine if a["last_error"]]
    return {"ok": all(oks) and not errors, "inserted": sum(a["rows_inserted_total"] for a in mine),
            "errors": errors, "seconds": round(time.time() - t0, 1)}


async def _ui_window(ctx, saved_window) -> None:
    async with ui.owner_browser(ctx) as page:
        await page.goto(f"{ctx.app}/settings/sales", wait_until="domcontentloaded")
        hours, minutes = page.get_by_label("Converters window hours"), page.get_by_label("Converters window minutes")
        await hours.wait_for(timeout=120_000)
        await page.wait_for_timeout(800)
        before = (await hours.input_value(), await minutes.input_value())
        await ui.shot(ctx, page, "trigger-sales-converters-window")
        await hours.fill("3")
        await minutes.fill("30")
        async with page.expect_response(lambda r: r.request.method == "PUT"
                                        and "/admin/settings/sales" in r.url) as put_:
            await page.get_by_role("button", name="Save", exact=True).last.click(timeout=5_000)
        resp = await put_.value
        shown = True
        try:
            await page.get_by_text("Saved ✓").first.wait_for(timeout=10_000)
        except Exception:
            shown = False
        await page.wait_for_timeout(300)
        after = (await hours.input_value(), await minutes.input_value())
        await ui.shot(ctx, page, "settled-sales-converters-window-saved")
    saved = await saved_window()
    ctx.check(UI_SAVE, before == ("1", "0") and resp.status == 200 and shown and saved == WINDOW_330_S
              and after == ("3", "30"), fields_before=before, fields_after=after, put_status=resp.status,
              saved_shown=shown, get_converters_window_seconds=saved)
