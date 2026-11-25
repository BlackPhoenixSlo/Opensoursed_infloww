from __future__ import annotations

import asyncio
import re
import time
from collections import Counter
from contextlib import ExitStack
from pathlib import Path

from slop.lib.browserbase import paste_curl
from slop.lib.client import Recorder, actor_call as _call
from slop.lib.procmon import pct
from slop.lib.proxy_wire import REFUSE_S, ProxyWire, registry_bindings, registry_pool
from slop.lib.service_constant import service_number
from slop.lib.proxy_failover_faults import C_BIND, C_MOVE, C_TIER, C_SURF, C_LOGIN, C_SENDS, C_HEALTHY, C_BACK, C_NOSTANDBY, C_LOGIN_ALL_DEAD, C_REWATCH, C_RECHECK_GAP, C_WIRE, C_PROBE_OF
from slop.seed import of_sessions

PROFILE = "one_agency"
UI = False
OF_WIRE = True
FAULT = "proxy-failover-never-moves"
RELAY_ENV = {"PROXY_RECHECK_S": "2"}
P95_VS_LAST = (1.5, 100)
P95_VS_LAST_MIN_N = 50
POOL = 3
TIER0 = 2
ON_POOL = 12
LOAD_S = 30.0
LOGIN_AT_S = 3.0
FAILOVER_MS = 30_000
BACK_MS = 40_000
ALL_DEAD_S = 35.0
LOGIN_ALL_DEAD_AT_S = 1.0
LOGIN_ASSIGN_MS = 12_000
REWATCH_MS = 25_000
RECHECK_ARMED_MS = 60_000
WINDOW_S = 11.0
REBAD_MS = 30_000
CUSTOM_LABEL = "slop-recheck-gap"
REV = "slop-of-rev-202610281200"

READ = "/api/of/v2/users/me"
PEOPLE_READ = "/api/of/v2/chats?limit=5&refresh=1"


# a blip must move nobody: an OF session is tied to its IP; only a proxy that stays dead moves Creators
DOWN_AFTER = service_number("proxy_health_decide", "DOWN_AFTER")


def _plain(html: str) -> str:
    return re.sub(r"</?p>", "", html or "")


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    of_sessions.seed(w, w.data["creators"])
    main = w.data["agencies"][0]["user_id"]
    aids = [c["id"] for c in w.data["creators"] if c["owner"] == main]
    n_on = int(ctx.param("on_pool", ON_POOL))
    on_pool, login_aid, back_aid, late_aid = aids[:n_on], aids[n_on], aids[n_on + 1], aids[n_on + 2]
    refuse = float(ctx.param("refuse_ms", REFUSE_S * 1000)) / 1000
    reg = ctx.stack.sessions.parent / "proxies.json"
    fake = ctx.of_wire
    n0 = len(fake.calls)
    with ExitStack() as stack:
        wires = [stack.enter_context(ProxyWire(refuse)) for _ in range(POOL)]
        spare = stack.enter_context(ProxyWire(refuse))
        custom = stack.enter_context(ProxyWire(refuse))
        pool_text, revived_at, back_wall = await _run(ctx, w, reg, wires, on_pool, login_aid, back_aid, late_aid)
        await _rewatch(ctx, reg, pool_text, spare, aids[n_on + 3], w.data["fans"])
        await _recheck_gap(ctx, custom, aids[n_on + 4], w.data["fans"])
    ctx.check(C_WIRE, fake.unsigned == 0 and not fake.unmodelled, unsigned=fake.unsigned,
              unmodelled=dict(fake.unmodelled), of_calls=len(fake.calls) - n0)
    watcher_calls = [c for c in fake.calls[n0:] if revived_at <= c["t"] <= back_wall]
    probes = [c for c in watcher_calls if c["route"] == "GET /robots.txt" and not c["account"]]
    ctx.check(C_PROBE_OF, bool(probes) and not any(c["cookie"] for c in probes), probes=len(probes),
              with_cookie=sum(1 for c in probes if c["cookie"]))


async def _rewatch(ctx, reg: Path, pool_text: str, spare: ProxyWire, aid: str, fans: dict) -> None:
    owner = ctx.owner
    budget_ms = float(ctx.param("rewatch_ms", REWATCH_MS))
    r = await owner.post("/__slop/proxy-pool", json={"text": f"{pool_text},socks5://127.0.0.1:{spare.port}"})
    label = next((lb for lb, port in registry_pool(reg).items() if port == spare.port), None)
    bound = (await owner.post("/admin/proxy-pool/assign", json={"account_id": aid})).status_code
    on = registry_bindings(reg).get(aid)
    http = owner.share(rec=Recorder(), limits=2 * DOWN_AFTER + 4)
    to = [f["id"] for f in fans[aid]]

    async def sends(tag: str) -> list[dict]:
        return list(await asyncio.gather(*(
            _call(http, "send", aid, f"/api/of/v2/chats/{to[i % len(to)]}/messages", "POST",
                  {"text": f"slop rewatch {tag} {i} {aid}"}, f"slop rewatch {tag} {i} {aid}")
            for i in range(DOWN_AFTER))))

    async def down_now() -> bool | None:
        ac = await owner.get("/admin/accounts")
        return any(a["id"] == aid and a.get("proxy_down") for a in ac.json().get("accounts", [])) \
            if ac.status_code == 200 else None

    ctx.rec.stage = "rewatch"
    spare.kill()
    blip = await sends("blip")
    spare.revive()
    answer = await _call(http, "read", aid, PEOPLE_READ)
    before = await down_now()
    t_dead = time.perf_counter()
    spare.kill()
    dead = await sends("dead")
    surfaced_at = None
    while time.perf_counter() - t_dead < budget_ms / 1000:
        if await down_now():
            surfaced_at = time.perf_counter()
            break
        await asyncio.sleep(0.5)
    ctx.rec.stage = None
    spare.revive()
    await http.aclose()
    ctx.check(C_REWATCH, r.status_code == 200 and label is not None and bound == 200 and on == label
              and all(x["status"] == 502 for x in blip + dead) and answer["status"] == 200 and before is False
              and surfaced_at is not None, budget=True,
              surfaced_ms=round((surfaced_at - t_dead) * 1000, 1) if surfaced_at else None, budget_ms=budget_ms,
              sync=r.status_code, label=label, assign=bound, on=on, blip_sends=Counter(x["status"] for x in blip),
              refresh=answer["status"], down_after_blip=before, dead_sends=Counter(x["status"] for x in dead))


async def _recheck_gap(ctx, wire: ProxyWire, aid: str, fans: dict) -> None:
    owner = ctx.owner
    test = f"/admin/proxies/{CUSTOM_LABEL}/test"
    http = owner.share(rec=Recorder(), limits=2 * DOWN_AFTER + 4)
    to = [f["id"] for f in fans[aid]]

    async def health() -> dict:
        pr = await owner.get("/admin/proxies")
        rows = pr.json().get("proxies", []) if pr.status_code == 200 else []
        return next((p.get("health") or {} for p in rows if p.get("label") == CUSTOM_LABEL), {})

    async def until(pred, budget_ms: float) -> tuple[dict, float | None]:
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < budget_ms / 1000:
            h = await health()
            if pred(h):
                return h, time.perf_counter()
            await asyncio.sleep(0.2)
        return await health(), None

    async def sends(tag: str) -> list[int]:
        return [x["status"] for x in await asyncio.gather(*(
            _call(http, "send", aid, f"/api/of/v2/chats/{to[i % len(to)]}/messages", "POST",
                  {"text": f"slop recheck-gap {tag} {i} {aid}"}) for i in range(DOWN_AFTER)))]

    ctx.rec.stage = "recheck-gap"
    made = (await owner.post("/admin/proxies", json={"label": CUSTOM_LABEL, "scheme": "socks5",
                                                       "host": "127.0.0.1", "port": wire.port})).status_code
    bound = (await owner.post("/admin/proxies/assign", json={"label": CUSTOM_LABEL, "account_id": aid})).status_code
    warm = (await _call(http, "read", aid, PEOPLE_READ))["status"]
    tunneled = sum(1 for c in wire.connects if c["alive"])
    wire.kill()
    first = await sends("first")
    armed, armed_at = await until(lambda h: h.get("state") == "bad" and h.get("next_recheck_at") is not None
                                  and h["next_recheck_at"] - time.time() >= WINDOW_S,
                                  float(ctx.param("recheck_armed_ms", RECHECK_ARMED_MS)))
    due = armed.get("next_recheck_at")
    lead_s = round(due - time.time(), 2) if armed_at else None
    wire.revive()
    click = await owner.post(test)
    after_click = (await health()).get("state")
    answer = (await _call(http, "read", aid, PEOPLE_READ))["status"]
    up = (await health()).get("state")
    wire.kill()
    streak = await sends("streak")
    t_streak, t0 = time.time(), time.perf_counter()
    after = (await health()).get("state")
    rebad_ms = float(ctx.param("rebad_ms", REBAD_MS))
    bad, bad_at = await until(lambda h: h.get("state") in ("bad", "rechecking"), rebad_ms)
    ctx.rec.stage = None
    wire.revive()
    await http.aclose()
    in_window = due is not None and t_streak < due
    click_ok = click.status_code == 200 and click.json().get("ok") is True
    ctx.check(C_RECHECK_GAP, made == 200 and bound == 200 and warm == 200 and tunneled >= 1
              and all(c == 502 for c in first + streak) and armed_at is not None
              and click_ok and after_click == "bad" and answer == 200 and up == "healthy"
              and after == "suspect" and in_window and bad_at is not None, budget=True,
              rebad_ms=round((bad_at - t0) * 1000, 1) if bad_at else None, budget_ms=rebad_ms, create=made,
              assign=bound, warm=warm, tunneled=tunneled, first_sends=Counter(first), armed=armed_at is not None,
              armed_lead_s=lead_s, test_click=click.status_code, test_ok=click_ok, after_click=after_click,
              answer=answer, up=up, streak_sends=Counter(streak), after_streak=after,
              streak_before_recheck_s=round(due - t_streak, 2) if due else None, in_window=in_window,
              final_state=bad.get("state"))


async def _run(ctx, w, reg: Path, wires: list[ProxyWire], on_pool: list[str], login_aid: str, back_aid: str,
               late_aid: str) -> tuple[str, float, float]:
    owner, fake = ctx.owner, ctx.of_wire
    load_s = float(ctx.param("load_s", LOAD_S))
    failover_ms = float(ctx.param("failover_ms", FAILOVER_MS))
    back_ms = float(ctx.param("back_ms", BACK_MS))

    items = [f"socks5://127.0.0.1:{p.port}" for p in wires]
    text = ",".join(items[:TIER0] + ["|"] + items[TIER0:])
    r = await owner.post("/__slop/proxy-pool", json={"text": text})
    synced = r.status_code == 200 and r.json().get("size") == POOL
    by_port = {p.port: p for p in wires}
    label_wire = {label: by_port[port] for label, port in registry_pool(reg).items()}
    bound = [(await owner.post("/admin/proxy-pool/assign", json={"account_id": a})).status_code for a in on_pool]
    binding = registry_bindings(reg)
    per_label = Counter(binding.get(a) for a in on_pool)
    warm = await asyncio.gather(*(_call(owner, "warm", a, READ) for a in on_pool))
    tunneled = {label: sum(1 for c in wire.connects if c["alive"]) for label, wire in label_wire.items()}
    tier0_labels = {lb for lb, wv in label_wire.items() if wv in wires[:TIER0]}
    spread = set(per_label) <= tier0_labels and sorted(per_label.values()) == sorted(
        [len(on_pool) // TIER0 + (1 if i < len(on_pool) % TIER0 else 0) for i in range(TIER0)])
    ctx.check(C_BIND, synced and all(s == 200 for s in bound) and spread
              and all(x["status"] == 200 for x in warm)
              and all(tunneled[label] >= n for label, n in per_label.items()),
              synced=synced, assign=Counter(bound), per_proxy=dict(per_label), tunneled=tunneled,
              warm=Counter(x["status"] for x in warm))

    dead_wire = wires[0]
    dead_label = next(lb for lb, wv in label_wire.items() if wv is dead_wire)
    tier0 = sorted(lb for lb, wv in label_wire.items() if wv in wires[:TIER0] and lb != dead_label)
    dead = sorted(a for a in on_pool if binding[a] == dead_label)
    healthy = sorted(a for a in on_pool if binding[a] != dead_label)
    rng = w.rng("proxy_failover_people")
    picks = [rng.choice(on_pool) for _ in range(ctx.users)]
    fans = w.data["fans"]
    people_rec = Recorder()
    http = owner.share(rec=people_rec, limits=4 * ctx.users + 16)
    c0 = len(dead_wire.connects)
    seen: list[dict] = []
    polls: list[dict] = []
    moved_at: list[float] = []

    async def person(n: int, aid: str, until: float) -> None:
        i = 0
        while time.perf_counter() < until:
            i += 1
            if i % 3 == 0:
                fan = fans[aid][(n + i) % len(fans[aid])]["id"]
                txt = f"slop failover p{n} #{i} {aid}"
                seen.append(await _call(http, "send", aid, f"/api/of/v2/chats/{fan}/messages", "POST",
                                        {"text": txt}, txt))
            else:
                seen.append(await _call(http, "read", aid, PEOPLE_READ))
            await asyncio.sleep(1.0)

    async def poll(until: float) -> None:
        while time.perf_counter() < until:
            t_b = time.perf_counter()
            b = registry_bindings(reg)
            pr = await owner.get("/admin/proxies")
            ac = await owner.get("/admin/accounts")
            pool = pr.json().get("pool", {}) if pr.status_code == 200 else {}
            down = sorted(a["id"] for a in ac.json().get("accounts", []) if a.get("proxy_down")) \
                if ac.status_code == 200 else None
            polls.append({"t": t_b, "on_dead": sorted(a for a in on_pool if b.get(a) == dead_label),
                          "bad": pool.get("bad"), "down": down, "bindings": b})
            if not polls[-1]["on_dead"] and not moved_at:
                moved_at.append(t_b)
            await asyncio.sleep(0.5)

    async def login(at: float, aid: str = login_aid) -> dict:
        await asyncio.sleep(at)
        boot = await owner.post("/admin/session/bootstrap", timeout=60, json={
            "mode": "paste-curl", "curl": paste_curl(aid, REV, "login"), "account_id": aid, "make_active": False})
        t_att = time.perf_counter()
        att = await owner.post("/admin/proxy-pool/assign", timeout=60, json={"account_id": aid})
        assign_ms = round((time.perf_counter() - t_att) * 1000, 1)
        label = registry_bindings(reg).get(aid)
        rel = await owner.post(f"/admin/reload-session?account_id={aid}")
        return {"bootstrap": boot.status_code, "assign": att.status_code, "assign_ms": assign_ms,
                "kept": att.json().get("kept") if att.status_code == 200 else None,
                "reload": rel.status_code, "label": label, "t": time.perf_counter()}

    t_dead = time.perf_counter()
    dead_wire.kill()
    ctx.rec.stage = "dead"
    until = t_dead + load_s
    login_res, *_ = await asyncio.gather(login(LOGIN_AT_S), poll(until),
                                         *(person(n, a, until) for n, a in enumerate(picks)))
    ctx.rec.stage = None
    await asyncio.sleep(0.5)
    final = registry_bindings(reg)

    t_moved = (moved_at[0] - t_dead) * 1000 if moved_at else None
    after = [x for x in seen if x["aid"] in dead and moved_at and x["t0"] > moved_at[0] + 1.0]
    after_bad = Counter(f"{x['kind']} {x['status']}" for x in after if x["status"] != 200)
    now_on = {a: final.get(a) for a in dead}
    ctx.check(C_MOVE, t_moved is not None and t_moved <= failover_ms
              and all(lbl in label_wire and lbl != dead_label for lbl in now_on.values())
              and bool(after) and not after_bad, budget=True,
              moved_ms=round(t_moved, 1) if t_moved else None, budget_ms=failover_ms, now_on=now_on,
              after_move_calls=len(after), after_move_not_200=dict(after_bad))

    moved = {a: lbl for a, lbl in now_on.items() if lbl != dead_label}
    ctx.check(C_TIER, bool(moved) and all(lbl in tier0 for lbl in moved.values()),
              moved=len(moved), on_tier0=sum(lbl in tier0 for lbl in moved.values()), tier0=tier0,
              per_proxy=dict(Counter(final.get(a) for a in [*on_pool, login_aid])))

    before = [p for p in polls if not moved_at or p["t"] < moved_at[0]]
    surfaced = [p for p in before if p["bad"] == 1 and p["down"] == dead]
    wrong = [p for p in before if p["bad"] not in (0, 1) or (p["down"] not in ([], dead))]
    ctx.check(C_SURF, bool(surfaced) and not wrong, polls_before_move=len(before), surfaced_polls=len(surfaced),
              first_surfaced_ms=round((surfaced[0]["t"] - t_dead) * 1000, 1) if surfaced else None,
              wrong=wrong[:3])

    login_label = login_res["label"]
    ctx.check(C_LOGIN, login_res["bootstrap"] == 200 and login_res["assign"] == 200 and login_res["kept"] is False
              and login_res["reload"] == 200 and login_label in label_wire and login_label != dead_label
              and final.get(login_aid) == login_label
              and all(p["bindings"].get(login_aid) == login_label for p in polls if p["t"] > login_res["t"]),
              **{k: v for k, v in login_res.items() if k != "t"}, final_label=final.get(login_aid),
              at_ms=round((login_res["t"] - t_dead) * 1000, 1))

    # the relay sends OF web's `<p>text</p>`: compared on the text inside
    with fake.lock:
        got = Counter(_plain(m["text"]) for ms in fake.sends.values() for m in ms)
    sends = [x for x in seen if x["kind"] == "send"]
    dup = {t: n for t, n in got.items() if n > 1}
    lost = [x["text"] for x in sends if x["status"] == 200 and got.get(x["text"], 0) != 1]
    ghost = [x["text"] for x in sends if x["status"] != 200 and got.get(x["text"], 0)]
    ctx.check(C_SENDS, bool(sends) and not dup and not lost and not ghost, sends=len(sends),
              by_status=dict(Counter(x["status"] for x in sends)), in_of_record=sum(got.values()),
              duplicated=dup, lost=len(lost), lost_eg=lost[:3], ghost=len(ghost), ghost_eg=ghost[:3])

    live = [x for x in seen if x["aid"] in healthy]
    live_bad = Counter(f"{x['kind']} {x['status']}" for x in live if x["status"] != 200)
    ctx.check(C_HEALTHY, bool(live) and not live_bad, calls=len(live), not_200=dict(live_bad))

    t_rev = time.perf_counter()
    revived_at = time.time()
    dead_wire.revive()
    back_at = None
    while time.perf_counter() - t_rev < back_ms / 1000:
        pr = await owner.get("/admin/proxies")
        if pr.status_code == 200 and pr.json().get("pool", {}).get("bad") == 0:
            back_at = time.perf_counter()
            break
        await asyncio.sleep(0.5)
    back_wall = time.time()
    held = Counter(registry_bindings(reg).get(a) for a in [*on_pool, login_aid])
    least = min(held.get(label, 0) for label in label_wire)
    least_used = sorted(label for label in label_wire if held.get(label, 0) == least)
    r = await owner.post("/admin/proxy-pool/assign", json={"account_id": back_aid})
    back_label = registry_bindings(reg).get(back_aid)
    back_wire = label_wire.get(back_label)
    c1 = len(back_wire.connects) if back_wire else 0
    back_read = await _call(owner, "back", back_aid, READ)
    through = sum(1 for c in back_wire.connects[c1:] if c["alive"]) if back_wire else 0
    stayed = {a: registry_bindings(reg).get(a) for a in dead}
    ctx.check(C_BACK, back_at is not None and r.status_code == 200 and back_label in least_used
              and back_read["status"] == 200 and through >= 1
              and all(lbl == now_on[a] for a, lbl in stayed.items()), budget=True,
              back_ms=round((back_at - t_rev) * 1000, 1) if back_at else None, budget_ms=back_ms,
              least_used=least_used, revived=dead_label, new_creator_on=back_label, read=back_read["status"],
              tunneled=through, moved_stayed=all(lbl == now_on[a] for a, lbl in stayed.items()))

    all_pool = sorted(a for a, lbl in registry_bindings(reg).items() if lbl in label_wire)
    b0 = registry_bindings(reg)
    for p in wires:
        p.kill()
    ctx.rec.stage = "all-dead"
    until = time.perf_counter() + float(ctx.param("all_dead_s", ALL_DEAD_S))
    polls.clear()
    moved_at.clear()
    rng2 = w.rng("proxy_failover_people_2")
    picks2 = (all_pool + [rng2.choice(all_pool) for _ in range(ctx.users)])[:max(ctx.users, len(all_pool))]
    late, *_ = await asyncio.gather(login(float(ctx.param("login_all_dead_at_s", LOGIN_ALL_DEAD_AT_S)), late_aid),
                                    poll(until), *(person(n, a, until) for n, a in enumerate(picks2)))
    ctx.rec.stage = None
    b1 = registry_bindings(reg)
    late_bound = b1.get(late_aid) in label_wire
    old = {a: lbl for a, lbl in b1.items() if a != late_aid}
    last = polls[-1] if polls else {}
    ctx.check(C_NOSTANDBY, polls and b0 == old and last.get("bad") == POOL
              and last.get("down") == sorted(all_pool + ([late_aid] if late_bound else [])),
              bindings_identical=b0 == old, last_bad=last.get("bad"), last_down=len(last.get("down") or []),
              pool_creators=len(all_pool))
    sessions = await owner.get("/admin/accounts")
    saved = sessions.status_code == 200 and any(
        a["id"] == late_aid and a.get("has_session") for a in sessions.json().get("accounts", []))
    ctx.check(C_LOGIN_ALL_DEAD, late["bootstrap"] == 200 and saved and late["assign"] == 200
              and late["kept"] is False and late_bound and late["label"] == b1.get(late_aid)
              and late["assign_ms"] <= LOGIN_ASSIGN_MS, budget=True,
              **{k: v for k, v in late.items() if k != "t"}, saved=saved, final_label=b1.get(late_aid),
              budget_ms=LOGIN_ASSIGN_MS)
    for p in wires:
        p.revive()
    await http.aclose()

    lms = [x["ms"] for x in live if x["kind"] == "read"]
    dms = [x["ms"] for x in seen if x["aid"] in dead and x["kind"] == "read" and x["status"] != 200]
    ctx.metric("proxy_failover", {
        "pool": POOL, "on_pool": len(on_pool), "dead": len(dead), "people": len(picks), "refuse_s": dead_wire.refuse_s,
        "moved_ms": round(t_moved, 1) if t_moved else None,
        "back_ms": round((back_at - t_rev) * 1000, 1) if back_at else None,
        "dead_read_ms": {"n": len(dms), "p50": pct(dms, 0.5), "p95": pct(dms, 0.95)},
        "healthy_read_ms": {"n": len(lms), "p50": pct(lms, 0.5), "p95": pct(lms, 0.95)},
        "refused_connects": sum(1 for c in dead_wire.connects[c0:] if not c["alive"]),
        "sends": dict(Counter(x["status"] for x in sends))})
    ctx.metric("http_people", people_rec.summary())
    ctx.metric("p95_vs_last_green", {"healthy reads": pct(lms, 0.95)} if lms else {})
    ctx.metric("p95_vs_last_green_n", {"healthy reads": len(lms)})
    ctx.note(f"pool of {POOL}, {len(on_pool)} Creators on it, {len(dead)} on the dead proxy; moved in "
             f"{round(t_moved, 1) if t_moved else None} ms; back in "
             f"{round((back_at - t_rev) * 1000, 1) if back_at else None} ms after revival",
             f"people {len(picks)}: healthy reads p95 {pct(lms, 0.95)} ms (n {len(lms)}); dead reads before the "
             f"move p95 {pct(dms, 0.95)} ms (n {len(dms)}); sends {dict(Counter(x['status'] for x in sends))}")
    return text, revived_at, back_wall
