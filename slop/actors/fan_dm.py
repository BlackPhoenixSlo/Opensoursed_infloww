from __future__ import annotations

import asyncio
import itertools
import time
from datetime import datetime, timezone

INJECT_ID_BASE = 9_500_000_000_000
PACED_ID_BASE = 9_600_000_000_000
PURCHASE_ID_BASE = 9_650_000_000_000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _user(fan: dict) -> dict:
    return {"id": fan["id"], "username": fan["username"], "name": fan["name"]}


def frame(msg_id: int, fan: dict, text: str, *, tip_dollars: float = 0) -> dict:
    return {"api2_chat_message": {
        "id": msg_id, "text": f"<p>{text}</p>", "price": 0, "isFree": True, "isOpened": False,
        "isTip": bool(tip_dollars), **({"tipAmount": tip_dollars} if tip_dollars else {}),
        "mediaCount": 0, "media": [], "responseType": "message",
        "fromUser": _user(fan), "createdAt": _now_iso(),
    }}


def purchase_frame(msg_id: int, fan: dict, dollars: float) -> dict:
    return {"purchase": {"message": {"id": msg_id, "fromUser": _user(fan), "price": dollars},
                         "openedAt": _now_iso()}}


def typing_frame(fan: dict) -> dict:
    return {"typing": {"id": fan["id"]}}


async def inject(http, account_id: str, fr: dict):
    return await http.post("/__slop/of-ws-frame", json={"account_id": account_id, "frame": fr})


async def burst(http, targets: list[dict], per_fan: int, concurrency: int, *, text: str = "slop dm") -> list[dict]:
    sem = asyncio.Semaphore(concurrency)
    sent: list[dict] = []
    seq = iter(range(INJECT_ID_BASE, INJECT_ID_BASE + 10**9))

    async def one_fan(f: dict) -> None:
        async with sem:
            for k in range(per_fan):
                mid = next(seq)
                r = await http.post("/__slop/of-ws-frame", json={
                    "account_id": f["account_id"], "frame": frame(mid, f, f"{text} {k + 1}/{per_fan}")})
                if r.status_code < 300:
                    sent.append({"account_id": f["account_id"], "fan_id": f["id"], "message_id": mid})

    await asyncio.gather(*(one_fan(f) for f in targets), return_exceptions=True)
    return sent


class Paced:

    BURST = ((1, 0.5), (2, 0.3), (3, 0.2))
    MEAN_BURST = sum(k * p for k, p in BURST)

    def __init__(self, http, fans: dict[str, list[dict]], rng, *, tip_p=0.03, purchase_p=0.02, typing_p=0.5,
                 gap_s=(0.2, 0.8), max_in_flight=2000):
        self.http, self.fans, self.rng = http, fans, rng
        self.tip_p, self.purchase_p, self.typing_p, self.gap_s = tip_p, purchase_p, typing_p, gap_s
        self.max_in_flight = max_in_flight
        self.rates: dict[str, float] = {}
        self.stage: str | None = None
        self.sent: list[dict] = []
        self.purchases: list[dict] = []
        self.failed = 0
        self.shed = 0
        self.typing = 0
        self._busy: set[tuple] = set()
        self._ids = itertools.count(PACED_ID_BASE)
        self._pids = itertools.count(PURCHASE_ID_BASE)
        self._tasks: set[asyncio.Task] = set()
        self._stop = asyncio.Event()

    async def _arrival(self, aid: str, fan: dict, k: int) -> None:
        key = (aid, fan["id"])
        try:
            for i in range(k):
                if i:
                    await asyncio.sleep(self.rng.uniform(*self.gap_s))
                if self.rng.random() < self.typing_p:
                    self.typing += 1
                    await inject(self.http, aid, typing_frame(fan))
                tip = round(self.rng.choice([5, 10, 20, 50]), 2) if self.rng.random() < self.tip_p else 0
                mid = next(self._ids)
                rec = {"account_id": aid, "fan_id": fan["id"], "message_id": mid, "kind": "tip" if tip else "dm",
                       "stage": self.stage, "t0": time.time() * 1000}
                r = await inject(self.http, aid, frame(mid, fan, f"slop paced {mid % 100000}", tip_dollars=tip))
                rec["t1"], rec["status"] = time.time() * 1000, r.status_code
                if r.status_code < 300:
                    self.sent.append(rec)
                self.failed += r.status_code >= 300
                if self.rng.random() < self.purchase_p:
                    pid = next(self._pids)
                    r = await inject(self.http, aid, purchase_frame(pid, fan, self.rng.choice([10, 25, 40])))
                    if r.status_code < 300:
                        self.purchases.append({"account_id": aid, "fan_id": fan["id"], "message_id": pid,
                                               "stage": self.stage})
        except Exception:
            self.failed += 1
        finally:
            self._busy.discard(key)

    async def _model(self, aid: str) -> None:
        pool = self.fans[aid]
        loop = asyncio.get_running_loop()
        due = loop.time()
        while not self._stop.is_set():
            rate = self.rates.get(aid, 0) / 60 / self.MEAN_BURST
            if rate <= 0:
                await asyncio.sleep(0.5)
                due = loop.time()
                continue
            # Arrival times are absolute (due += gap): a late wake-up never lowers the offered rate (open loop).
            due += self.rng.expovariate(rate)
            try:
                await asyncio.wait_for(self._stop.wait(), max(0.0, due - loop.time()))
                return
            except asyncio.TimeoutError:
                pass
            if len(self._tasks) >= self.max_in_flight:
                self.shed += 1
                continue
            for _ in range(20):
                fan = self.rng.choice(pool)
                if (aid, fan["id"]) not in self._busy:
                    break
            else:
                continue
            self._busy.add((aid, fan["id"]))
            k = self.rng.choices([b for b, _ in self.BURST], [w for _, w in self.BURST])[0]
            t = asyncio.create_task(self._arrival(aid, fan, k))
            self._tasks.add(t)
            t.add_done_callback(self._tasks.discard)

    def start(self) -> None:
        self._runners = [asyncio.create_task(self._model(aid)) for aid in self.fans]

    async def stop(self) -> None:
        self._stop.set()
        await asyncio.gather(*self._runners, return_exceptions=True)
        await asyncio.gather(*list(self._tasks), return_exceptions=True)


async def serial(http, targets: list[dict], per_fan: int, *, rate: float = 0, text: str = "slop dm",
                 ids=None, phase: dict[str, float] | None = None, stop: asyncio.Event | None = None,
                 out: list[dict] | None = None, due_shift_ms: float = 0.0, make=None) -> list[dict]:
    ids = ids if ids is not None else itertools.count(INJECT_ID_BASE)
    by_acct: dict[str, list[dict]] = {}
    for f in targets:
        by_acct.setdefault(f["account_id"], []).append(f)
    out = out if out is not None else []

    async def pump(aid: str, fans: list[dict]) -> None:
        start = time.time() + ((phase or {}).get(aid, 0.0) if rate > 0 else 0.0)
        for i, (k, f) in enumerate((k, f) for k in range(per_fan) for f in fans):
            if rate > 0:
                wait = max(0.0, start + i / rate - time.time())
                if stop is None:
                    await asyncio.sleep(wait)
                else:
                    try:
                        await asyncio.wait_for(stop.wait(), wait)
                    except asyncio.TimeoutError:
                        pass
            if stop is not None and stop.is_set():
                return
            mid = next(ids)
            rec = {"account_id": aid, "fan_id": f["id"], "message_id": mid, "t0": time.time() * 1000}
            rec["due"] = ((start + i / rate) * 1000 if rate > 0 else rec["t0"]) - due_shift_ms
            try:
                fr = make(mid, f, k) if make else frame(mid, f, f"{text} {k + 1}/{per_fan}")
                r = await inject(http, aid, fr)
                rec["status"] = r.status_code
            except Exception as e:
                rec["status"], rec["error"] = 599, type(e).__name__
            rec["t1"] = time.time() * 1000
            out.append(rec)

    await asyncio.gather(*(pump(a, fs) for a, fs in by_acct.items()))
    return out


SAY_ID_BASE = 9_560_000_000_000
_say_ids = itertools.count(SAY_ID_BASE)


async def say(http, lines: list[tuple[dict, str]]) -> list[dict]:
    by_acct: dict[str, list[tuple[dict, str]]] = {}
    for f, text in lines:
        by_acct.setdefault(f["account_id"], []).append((f, text))
    out: list[dict] = []

    async def pump(aid: str, items: list[tuple[dict, str]]) -> None:
        for f, text in items:
            mid = next(_say_ids)
            rec = {"account_id": aid, "fan_id": f["id"], "message_id": mid, "text": text,
                   "t0": time.time() * 1000}
            try:
                r = await inject(http, aid, frame(mid, f, text))
                rec["status"] = r.status_code
            except Exception as e:
                rec["status"], rec["error"] = 599, type(e).__name__
            rec["t1"] = time.time() * 1000
            out.append(rec)

    await asyncio.gather(*(pump(a, it) for a, it in by_acct.items()))
    return out
