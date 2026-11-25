from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from contextlib import ExitStack
from datetime import timedelta

from slop.lib.proxy_wire import ProxyWire
from slop.lib.sweep_pacing_evidence import IN_FLIGHT, SCAN_END, held, scan_many
from slop.lib.sweep_pacing_faults import TX_PROXY_SPACED
from slop.lib.sweep_pacing_ledger import tx_row

PX_N, POOL, PX_ROWS = 6, 3, 450
WALK_TIMEOUT_S = 180
PER_PROXY = 5
BIND_THINK_S = 1.0


async def bind(ctx, st: ExitStack, groups: list[list[str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, g in enumerate(groups):
        wire = st.enter_context(ProxyWire())
        label = f"slop-tx-{k}"
        r = await ctx.owner.post("/admin/proxies", json={"label": label, "scheme": "socks5", "host": "127.0.0.1",
                                                         "port": wire.port, "notes": "slop: sweep-pacing topology"})
        if r.status_code != 200:
            raise RuntimeError(f"slop: POST /admin/proxies {label}: {r.status_code} {r.text[:200]}")
        for a in g:
            await asyncio.sleep(BIND_THINK_S)
            r = await ctx.owner.post("/admin/proxies/assign", json={"label": label, "account_id": a})
            if r.status_code != 200:
                raise RuntimeError(f"slop: assign {a} to {label}: {r.status_code} {r.text[:200]}")
            out[a] = f"127.0.0.1:{wire.port}"
    return out


def _bindings(path, aids) -> dict[str, str]:
    out = {}
    for p in json.loads(path.read_text()).get("proxies", []):
        for a in p.get("assigned_account_ids") or ():
            if a in aids:
                out[a] = f"{p['host']}:{p['port']}"
    return out


def _labels(path) -> dict[str, str]:
    return {f"{p['host']}:{p['port']}": p["label"] for p in json.loads(path.read_text()).get("proxies", [])}


def _totals(w, aids) -> dict[str, tuple[int, int, int]]:
    out = {}
    for a in aids:
        ids, total, life = held(w, a)
        out[a] = (sum(ids.values()), total, life)
    return out


def _status(w, aids) -> dict[str, str]:
    return {a: s["status"] for a, s in scan_many(w, aids).items()}


async def _walks(ctx, w, sw, aids) -> dict:
    t0 = time.time()
    got = await asyncio.gather(*(ctx.owner.post(f"/admin/ingest/transactions/{a}/run", json={"mode": "refresh"})
                                 for a in aids))
    accepted = [r.status_code for r in got]
    until = time.monotonic() + WALK_TIMEOUT_S
    while time.monotonic() < until:
        await asyncio.sleep(1.0)
        st = _status(w, aids)
        ended = {m.group(1) for y in (await ctx.owner.get("/__slop/sweep-pacing/runs")).json()["log"]
                 if y["t"] >= t0 and (m := SCAN_END.search(y["msg"]))}
        gets = [e for e in sw.snapshot() if e["t"] >= t0 and e["route"] == "transactions" and e["account"] in aids]
        if all(st.get(a) not in IN_FLIGHT and (a in ended or st.get(a) == "error") for a in aids) \
                and {e["account"] for e in gets} >= set(aids):
            break
    gets = [e for e in sw.snapshot() if e["t"] >= t0 and e["route"] == "transactions" and e["account"] in aids]
    return {"t0": t0, "t1": time.time(), "accepted": accepted, "gets": gets, "status": _status(w, aids)}


def _judge(p: dict, binding: dict[str, str], gap: float, slack: float) -> dict:
    by_eg: dict[str, list[float]] = defaultdict(list)
    for e in p["gets"]:
        by_eg[e.get("egress") or "?"].append(e["t"])
    gaps = {eg: round(min((b - a for a, b in zip(sorted(ts), sorted(ts)[1:])), default=99.0), 3)
            for eg, ts in by_eg.items()}
    pairs = [(e["t"], e.get("egress")) for e in p["gets"]]
    overlap = any(abs(t1 - t2) < gap / 2 and g1 != g2 for (t1, g1), (t2, g2) in zip(sorted(pairs), sorted(pairs)[1:]))
    off_binding = sorted({e["account"] for e in p["gets"] if e.get("egress") != binding.get(e["account"])})
    per = defaultdict(int)
    for e in p["gets"]:
        per[e["account"]] += 1
    return {"min_gap_s": gaps, "spaced": all(g >= gap - slack for g in gaps.values()),
            "endpoints_overlap": overlap, "off_binding": off_binding,
            "gets": dict(per), "non_200": [e["status"] for e in p["gets"] if e["status"] != 200],
            "accepted": p["accepted"], "unsettled": {a: s for a, s in p["status"].items() if s in IN_FLIGHT},
            "wall_s": round(p["t1"] - p["t0"], 1)}


async def run(ctx, w, sw, px: list[str], rows: dict[str, list[dict]], *, gap: float, slack: float) -> None:
    reg = ctx.stack.sessions.parent / "proxies.json"
    with ExitStack() as st:
        wires = [st.enter_context(ProxyWire()) for _ in range(POOL)]
        text = ",".join(f"socks5://127.0.0.1:{p.port}" for p in wires)
        synced = (await ctx.owner.post("/__slop/proxy-pool", json={"text": text})).status_code
        assigned = [(await ctx.owner.post("/admin/proxy-pool/assign", json={"account_id": a})).status_code for a in px]
        b1 = _bindings(reg, set(px))
        for a in px:
            sw.txs[a] = rows[a]
        want = {a: (len(rows[a]), sum(round(r["amount"] * 100) for r in rows[a])) for a in px}
        p1 = await _walks(ctx, w, sw, px)
        tot1 = _totals(w, px)
        last = f"127.0.0.1:{wires[-1].port}"
        on_last = sorted(a for a, eg in b1.items() if eg == last)
        mv = await ctx.owner.post("/__slop/sweep-pacing/failover", json={"label": _labels(reg).get(last)})
        moved = sorted(mv.json().get("moved") or []) if mv.status_code == 200 else None
        b2 = _bindings(reg, set(px))
        p2 = await _walks(ctx, w, sw, px)
        tot2 = _totals(w, px)
    j1, j2 = _judge(p1, b1, gap, slack), _judge(p2, b2, gap, slack)
    per_proxy = defaultdict(list)
    for a, eg in b1.items():
        per_proxy[eg].append(a)
    shared = len(per_proxy) == POOL and all(len(v) >= 2 for v in per_proxy.values())
    totals_ok = all(tot1[a][0] == want[a][0] and tot1[a][1] == want[a][1] == tot1[a][2] for a in px) and tot1 == tot2
    move_ok = (moved == on_last and bool(on_last) and all(b2[a] != last for a in px)
               and all(b2[a] == b1[a] for a in px if a not in on_last))

    def ok(j: dict) -> bool:
        return (j["spaced"] and j["endpoints_overlap"] and not j["off_binding"] and not j["non_200"]
                and not j["unsettled"] and all(s == 202 for s in j["accepted"]) and len(j["gets"]) == len(px))
    ctx.check(TX_PROXY_SPACED, synced == 200 and all(s == 200 for s in assigned) and len(b1) == len(px) and shared
              and ok(j1) and ok(j2) and move_ok and totals_ok,
              creators=px, bound=b1, moved=moved, on_moved_proxy=on_last, bound_after=b2,
              phase1=j1, phase2=j2, totals_after_1=tot1, totals_after_2=tot2, want=want,
              synced=synced, assigned=assigned)
    ctx.metric("tx_proxy_pacing", {"phase_wall_s": [j1["wall_s"], j2["wall_s"]],
                                   "min_gap_s": [j1["min_gap_s"], j2["min_gap_s"]]})


def ledger_rows(rng, base: int, fan_ids: list[int], now) -> list[dict]:
    step = timedelta(days=6) / PX_ROWS
    return [tx_row(base + k, rng.choice(fan_ids), rng.randint(5, 50) * 100, now - timedelta(minutes=5) - step * k)
            for k in range(PX_ROWS)]
