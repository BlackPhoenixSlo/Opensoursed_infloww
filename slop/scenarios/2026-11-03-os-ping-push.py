from __future__ import annotations

import asyncio
import itertools
import json
import time
from collections import Counter, defaultdict

from slop.actors import fan_dm, ui
from slop.actors.manager import SseListener, quiesce
from slop.actors.push_device import PushDevice, sign_in, subscribe
from slop.lib.push_faults import (PUSH_ALL_ONCE, PUSH_DECRYPT, PUSH_NO_REPUSH, PUSH_ORDER, PUSH_PRUNED_DEAD,
                                  PUSH_PRUNED_GONE, PUSH_SCOPE, PUSH_TYPES, PUSH_VAPID, UI_SW_SHOW,
                                  UI_TEST_BUTTON)
from slop.lib.push_wire import PushWire
from slop.seed import agency
from slop.seed import chatters as chatters_seed

PROFILE = "multi_agency_big_models"
UI = True
APP_MODE = "prod"
FAULT = "push-leaks-scope"
RELAY_ENV = {"PUSH_ENDPOINT_HOSTS": "127.0.0.1", "VAPID_SUBJECT": "mailto:slop@example.test"}
E2E_P95_MS = 250
# measured at medium --users=200 --no-ui (host load 8): frame -> push p95 41.4 ms, PUT p95 94 ms; budgets ~6x / ~3x for a shared laptop
PUT_P95_MS = 300
P95_VS_LAST = (1.5, 100)
P95_VS_LAST_MIN_N = 20
E2E_KEY, PUT_ROUTE = "frame->push (steady)", "PUT /push/subscription"
OWNER_DEVICES = 2
MIN_DEVICES = 15
FANS_PER_CREATOR = 6
ID_BASE = 9_800_000_000_000
TYPE_MIX = (("default", ("purchases", "tip"), 5), ("messages", ("message", "purchases", "tip"), 2),
            ("toasts", ("purchases", "tip", "subscribed", "favorited"), 1), ("tip-muted", ("purchases",), 1),
            ("purchases-muted", ("message", "tip"), 1))
KIND_MIX = (("dm", 35), ("purchase", 25), ("tip", 15), ("like", 10), ("sub", 10), ("unknown", 5))
RATE = 1.0
LATENCY_DEVS, LATENCY_S = 2, 0.05
RETRY_DEVS = 3
GONE_DEVS_FRAC, GONE_DEVS_MIN = 0.05, 2
IDLE_S = 1.0
SETTLE_S = 180.0
REPLAY_WAIT_S = 15.0
UI_WAIT_MS = 120_000
STEP_MS = 30_000
SW_SHOW_WAIT_S = 15.0
KNOWN_RED: dict[str, str] = {}

STUB_JS = """(() => {
  const EP = %(endpoint)s, KEYS = %(keys)s;
  if (!self.PushManager) return;
  let sub = null;
  const make = (opts) => ({
    endpoint: EP, expirationTime: null,
    options: { userVisibleOnly: true, applicationServerKey: opts && opts.applicationServerKey
      ? new Uint8Array(opts.applicationServerKey).slice().buffer : null },
    toJSON() { return { endpoint: EP, expirationTime: null, keys: KEYS }; },
    getKey() { return null; },
    async unsubscribe() { sub = null; return true; },
  });
  PushManager.prototype.subscribe = async function (opts) {
    window.__slopSubscribes = (window.__slopSubscribes || 0) + 1;
    sub = sub || make(opts);
    return sub;
  };
  PushManager.prototype.getSubscription = async function () { return sub; };
})();"""

OVERLAY_JS = """(items) => {
  const d = document.createElement('div');
  d.id = 'slop-sw-notifications';
  d.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:2147483647;max-width:420px;padding:12px 14px;' +
    'background:#111827;color:#f9fafb;font:13px/1.4 system-ui;border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.35)';
  const h = document.createElement('div');
  h.style.cssText = 'font-weight:600;margin-bottom:6px';
  h.textContent = 'slop: service worker registration.getNotifications()';
  d.appendChild(h);
  for (const n of items) {
    const r = document.createElement('div');
    r.style.cssText = 'margin-top:6px;padding-top:6px;border-top:1px solid #374151';
    r.textContent = n.title + ' — ' + n.body + '  [tag ' + n.tag + ']';
    d.appendChild(r);
  }
  document.body.appendChild(d);
}"""


def _chk(ctx, name: str, ok: bool, **detail) -> None:
    if name in KNOWN_RED:
        ctx.skip(name, KNOWN_RED[name], observed_ok=ok, **detail)
    else:
        ctx.check(name, ok, **detail)


def _p95(xs: list[float]) -> float | None:
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * 0.95))], 1) if xs else None


class _S:

    def __init__(self, ctx, w, wire: PushWire) -> None:
        self.ctx, self.w, self.wire, self.owner = ctx, w, wire, ctx.owner
        self.rng = w.rng("scenario:os-ping-push")
        self.devs: list[PushDevice] = []
        self.ids = itertools.count(ID_BASE)
        self.offers: list[dict] = []
        self.first: dict[str, dict] = {}
        self.n_offers: Counter = Counter()
        self.frames: dict[str, dict] = {}
        self.live: set[str] = set()
        self.armed_gone: dict[str, float] = {}
        self.dead: dict[str, float] = {}
        self.steady_purchase: dict[str, dict] = {}
        self.by_agency: dict[int, list[str]] = {}
        self.fans: dict[str, list[dict]] = {}
        self.phase_end: dict[str, int] = {}
        self.replayed: dict = {}
        self.restart: dict = {}
        self.prune: dict = {}

    def dev(self, name: str) -> PushDevice:
        return next(d for d in self.devs if d.name == name)

    def offer(self, tag: str, aid: str, tk: str | None, phase: str) -> None:
        o = {"tag": tag, "aid": aid, "tk": tk, "phase": phase, "t0": time.time() * 1000,
             "live": frozenset(self.live), "i": len(self.offers)}
        self.offers.append(o)
        self.first.setdefault(tag, o)
        self.n_offers[tag] += 1


def _purchase(mid: int, fan: dict, cents: int) -> dict:
    return {"purchase_notified": {"notif_id": str(mid), "fan_id": fan["id"], "message_id": mid,
                                  "amount_cents": cents, "created_at": None, "name": fan["name"]}}


def _toast(mid: int, fan: dict, typ: str, text: str) -> dict:
    return {"toasts": [{"id": mid, "type": typ, "text": text, "createdAt": fan_dm._now_iso(),
                        "data": {"relatedUser": {"id": fan["id"], "name": fan["name"], "username": fan["username"]}}}]}


def _build(kind: str, mid: int, fan: dict, aid: str, rng) -> tuple[dict, str, str | None]:
    if kind == "dm":
        return fan_dm.frame(mid, fan, "slop push dm"), f"{aid}:m{mid}", "message"
    if kind == "tip":
        return fan_dm.frame(mid, fan, "", tip_dollars=rng.choice((5, 10, 20, 50))), f"{aid}:m{mid}", "tip"
    if kind == "purchase":
        return _purchase(mid, fan, rng.choice((500, 1000, 2500, 4999))), f"{aid}:{mid}", "purchases"
    if kind == "like":
        return _toast(mid, fan, "favorited", f"{fan['name']} liked your post"), f"{aid}:{mid}", "favorited"
    if kind == "sub":
        return _toast(mid, fan, "subscribed", f"{fan['name']} subscribed to you"), f"{aid}:{mid}", "subscribed"
    return _toast(mid, fan, "release_forms", "Release form signed"), f"{aid}:{mid}", None


async def _send(s: _S, phase: str, plan: dict[str, list], rate: float = 0) -> list[dict]:
    plan = {a: v for a, v in plan.items() if v}
    n = {len(v) for v in plan.values()}
    assert len(n) <= 1, f"{phase}: plans of unequal length {n}"
    if not plan:
        return []

    def make(mid: int, f: dict, k: int) -> dict:
        fr, tag, tk = plan[f["account_id"]][k](mid)
        s.offer(tag, f["account_id"], tk, phase)
        s.frames.setdefault(tag, fr)
        return fr

    targets = [{"account_id": a, "id": s.fans[a][0]["id"]} for a in plan]
    stagger = {t["account_id"]: i / (rate * len(targets)) for i, t in enumerate(targets)} if rate > 0 else None
    recs = await fan_dm.serial(s.owner, targets, n.pop(), ids=s.ids, make=make, rate=rate, phase=stagger)
    bad = [r for r in recs if r.get("status", 0) >= 300]
    if bad:
        raise RuntimeError(f"{phase}: {len(bad)} frames refused, first {bad[0]}")
    return recs


def _new(kind: str, aid: str, fan: dict, s: _S):
    rng = s.rng
    return lambda mid: _build(kind, mid, fan, aid, rng)


def _again(fr: dict, tag: str, tk: str | None):
    return lambda _mid: (fr, tag, tk)


async def _push_stats(s: _S) -> dict:
    r = await s.owner.get("/admin/events/stats")
    r.raise_for_status()
    return r.json()["sse"]["push"]


async def _settle(s: _S, phase: str) -> dict:
    await quiesce(s.owner)
    t0 = time.time()
    while True:
        st = await _push_stats(s)
        quiet = time.time() - max(s.wire.last_recv(), t0 - IDLE_S)
        if (not st["inbox"] and not st["queued"] and not st["retry_pending"] and quiet >= IDLE_S) \
                or time.time() - t0 > SETTLE_S:
            s.phase_end[phase] = len(s.wire.snapshot())
            st["settle_s"] = round(time.time() - t0, 2)
            st["timed_out"] = time.time() - t0 > SETTLE_S
            return st
        await asyncio.sleep(0.2)


async def _setup(s: _S) -> None:
    ctx, w = s.ctx, s.w
    ctx.rec.stage = "setup"
    ags = w.data["agencies"]
    creators = w.data["creators"]
    s.by_agency = {i: [c["id"] for c in creators if c["owner"] == a["user_id"]] for i, a in enumerate(ags)}
    s.fans = {aid: fs[:FANS_PER_CREATOR] for aid, fs in w.data["fans"].items()}
    n = max(ctx.users, MIN_DEVICES)
    rng = s.rng
    mix = [name for name, _, wt in TYPE_MIX for _ in range(wt)]
    types_of = {name: t for name, t, _ in TYPE_MIX}
    devs: list[PushDevice] = []
    for a, ag in enumerate(ags):
        for j in range(OWNER_DEVICES):
            devs.append(PushDevice(f"o{a}d{j}", "user", ag["username"], agency.PASSWORD, a,
                                   frozenset(s.by_agency[a])))
    plans: dict[int, list[tuple[str, list[str]]]] = defaultdict(list)
    staffed = [a for a in range(len(ags)) if s.by_agency[a]]
    for k in range(n - len(devs)):
        a = staffed[k % len(staffed)]
        cs = s.by_agency[a]
        subset = sorted(rng.sample(cs, rng.randint(1, len(cs) - 1))) if len(cs) >= 2 else list(cs)
        plans[a].append((f"slpush{ctx.seed}c{k}", subset))
    for a, rows in plans.items():
        made = await chatters_seed.seed(w, ags[a]["http"], ags[a]["user_id"], [u for u, _ in rows],
                                        account_ids=[sub for _, sub in rows])
        for (u, subset), m in zip(rows, made):
            devs.append(PushDevice(f"c{u.rsplit('c', 1)[1]}", "chatter", u, m["password"], a, frozenset(subset)))
    for i, d in enumerate(devs):
        d.types = types_of[mix[(i * 7 + ctx.seed) % len(mix)]]
    s.devs = devs
    s.dev("o1d1").platforms = {"onlyfans": False, "fansly": True}
    for d in (s.dev("o2d0"), s.dev("o2d1"), s.dev("o3d0")):
        d.types = types_of["default"]
    sem = asyncio.Semaphore(10)

    async def up(d: PushDevice) -> None:
        async with sem:
            await sign_in(d, ctx.relay, ctx.rec)

    await asyncio.gather(*(up(d) for d in devs))
    key = await devs[0].http.get("/push/key")
    key.raise_for_status()
    s.wire.vapid_key = key.json()["key"]

    async def sub(d: PushDevice) -> None:
        async with sem:
            await subscribe(d, s.wire)

    await asyncio.gather(*(sub(d) for d in devs))
    bad = [(d.name, d.put_status) for d in devs if d.put_status != 200]
    if bad:
        raise RuntimeError(f"PUT /push/subscription refused: {bad[:5]}")
    s.live = {d.name for d in devs}
    st = await _push_stats(s)
    ctx.metric("devices", {"n": len(devs), "owners": sum(d.kind == "user" for d in devs),
                           "chatters": sum(d.kind == "chatter" for d in devs),
                           "partial_scope": sum(d.kind == "chatter" and len(d.scope) < len(s.by_agency[d.agency])
                                                for d in devs),
                           "types": dict(Counter(",".join(d.types) for d in devs)),
                           "creators_per_agency": {a: len(v) for a, v in s.by_agency.items()},
                           "relay_subs": st["subs"]})


async def _steady(s: _S) -> dict:
    s.ctx.rec.stage = "steady"
    nframes = s.ctx.param("frames", s.w.size["os_ping_frames"])
    kinds, weights = zip(*KIND_MIX)
    plan = {}
    for c in s.w.data["creators"]:
        aid, fans = c["id"], s.fans[c["id"]]
        ks = s.rng.choices(kinds, weights, k=nframes)
        if "purchase" not in ks:
            ks[0] = "purchase"
        plan[aid] = [_new(k, aid, fans[i % len(fans)], s) for i, k in enumerate(ks)]
    slow = [d.name for d in s.rng.sample(s.devs, LATENCY_DEVS)]
    for name in slow:
        s.wire.arm(name, latency_s=LATENCY_S)
    rate = s.ctx.param("rate", RATE)
    await _send(s, "steady", plan, rate=rate)
    st = await _settle(s, "steady")
    for name in slow:
        s.wire.arm(name)
    for o in s.offers:
        if o["phase"] == "steady" and o["tk"] == "purchases" and o["aid"] not in s.steady_purchase:
            s.steady_purchase[o["aid"]] = o
    return {"frames": sum(1 for o in s.offers if o["phase"] == "steady"), "rate_per_creator": rate, "slow": slow,
            "push": st}


async def _reoffer(s: _S) -> dict:
    s.ctx.rec.stage = "reoffer"
    cand = [d.name for d in s.devs if "purchases" in d.types and d.platforms.get("onlyfans", True)]
    retry = s.rng.sample(cand, min(RETRY_DEVS, len(cand)))
    for name in retry:
        s.wire.arm(name, status=429, once=True)
    plan = {}
    for c in s.w.data["creators"]:
        aid, fan = c["id"], s.fans[c["id"]][1 % len(s.fans[c["id"]])]
        mid = next(s.ids)
        fr, tag, tk = _build("purchase", mid, fan, aid, s.rng)
        old = s.steady_purchase[aid]
        plan[aid] = [_again(fr, tag, tk)] * 3 + [_again(s.frames[old["tag"]], old["tag"], old["tk"])]
    await _send(s, "reoffer", plan)
    return {"retry_429_once": retry, "push": await _settle(s, "reoffer")}


async def _replay(s: _S, listener: SseListener) -> dict:
    s.ctx.rec.stage = "replay"
    last = listener.last_id
    await listener.stop()
    plan = {aid: [_new("purchase", aid, s.fans[aid][2 % len(s.fans[aid])], s)] for aid in s.by_agency[0]}
    await _send(s, "replay", plan)
    tags = {o["tag"] for o in s.offers if o["phase"] == "replay"}
    back = SseListener(s.owner.share(limits=2), states=("purchase_notified",), last_id=last)
    await back.start()
    t0 = time.time()
    seen: set[str] = set()
    while time.time() - t0 < REPLAY_WAIT_S:
        seen = {f"{acct}:{f.get('notif_id')}" for t, f, acct in back.state_events if t == "purchase_notified"}
        if tags <= seen:
            break
        await asyncio.sleep(0.2)
    await back.stop()
    await back.http.aclose()
    s.replayed = {"last_event_id": last, "sent": len(tags), "replayed": len(tags & seen)}
    return {**s.replayed, "push": await _settle(s, "replay")}


async def _restart(s: _S) -> dict:
    ctx = s.ctx
    ctx.rec.stage = "restart"
    t_term, took = await asyncio.to_thread(ctx.stack.stop_relay, 0, 30.0)
    await asyncio.to_thread(ctx.stack.start_relay)
    s.owner = ctx.owner.share()
    for d in s.devs:
        d.http = d.http.share(limits=4)
    t0 = time.time()
    st = {}
    while time.time() - t0 < 30:
        st = await _push_stats(s)
        if st["subs"] >= len(s.live):
            break
        await asyncio.sleep(0.5)
    loaded = st.get("subs")
    plan = {}
    for c in s.w.data["creators"]:
        aid = c["id"]
        old = s.steady_purchase[aid]
        plan[aid] = [_again(s.frames[old["tag"]], old["tag"], old["tk"]),
                     _new("purchase", aid, s.fans[aid][3 % len(s.fans[aid])], s)]
    await _send(s, "restart", plan)
    s.restart = {"stop_s": None if took is None else round(took, 2), "subs_loaded": loaded,
                 "live": len(s.live), "push": await _settle(s, "restart")}
    return s.restart


async def _prune(s: _S) -> dict:
    ctx = s.ctx
    ctx.rec.stage = "prune"
    fixed = {"o1d1", "o2d0", "o2d1", "o3d0"}
    cand = [d.name for d in s.devs if d.name not in fixed and "purchases" in d.types
            and d.platforms.get("onlyfans", True)]
    k = max(GONE_DEVS_MIN, int(len(s.devs) * GONE_DEVS_FRAC))
    gone = s.rng.sample(cand, min(k, len(cand)))
    for name in gone:
        s.wire.arm(name, status=410)
        s.armed_gone[name] = time.time()
        s.live.discard(name)
    plan = {c["id"]: [_new("purchase", c["id"], s.fans[c["id"]][i % len(s.fans[c["id"]])], s) for i in (4, 5)]
            for c in s.w.data["creators"]}
    await _send(s, "prune-gone", plan)
    st_gone = await _settle(s, "prune-gone")
    out, rev, other = s.dev("o3d0"), s.dev("o2d0"), s.dev("o2d1")
    s.dead[out.name] = time.time()
    r = await out.http.post("/auth/logout")
    r.raise_for_status()
    s.live.discard(out.name)
    s.dead[other.name] = time.time()
    r = await rev.http.post("/auth/sessions/revoke-others")
    r.raise_for_status()
    s.live.discard(other.name)
    reput = await subscribe(rev, s.wire)
    rows_after_logout = _rows(s, [out.name])
    plan = {c["id"]: [_new("purchase", c["id"], s.fans[c["id"]][0], s),
                      _new("tip", c["id"], s.fans[c["id"]][1 % len(s.fans[c["id"]])], s)]
            for c in s.w.data["creators"]}
    await _send(s, "prune-dead", plan)
    st_dead = await _settle(s, "prune-dead")
    s.prune = {"gone": gone, "logged_out": out.name, "revoked": other.name, "revoker_reput": reput,
               "rows_right_after_logout": rows_after_logout, "push_gone": st_gone, "push_dead": st_dead}
    return s.prune


def _rows(s: _S, names: list[str]) -> dict[str, int]:
    con = s.w.sql()
    try:
        return {n: con.execute("SELECT COUNT(*) FROM push_subscriptions WHERE endpoint=?",
                               (s.wire.endpoint(n),)).fetchone()[0] for n in names}
    finally:
        con.close()


def _checks(s: _S) -> None:
    ctx, recs = s.ctx, s.wire.snapshot()
    devs = {d.name: d for d in s.devs}
    ok_n: Counter = Counter()
    any_n: Counter = Counter()
    after: dict[str, list] = defaultdict(list)
    for r in recs:
        tag = (r.get("plain") or {}).get("tag")
        if r["sub"] not in devs or tag not in s.first:
            continue
        any_n[(r["sub"], tag)] += 1
        if 200 <= r["status"] < 300:
            ok_n[(r["sub"], tag)] += 1
        after[r["sub"]].append((r["t_recv"], r["status"], tag))

    missing, dup, expected = [], [], 0
    for tag, o in s.first.items():
        for name in o["live"]:
            if devs[name].wants(o["aid"], o["tk"]):
                expected += 1
                n = ok_n[(name, tag)]
                if n < 1:
                    missing.append((name, tag, o["phase"]))
                elif n > 1 and s.n_offers[tag] == 1:
                    dup.append((name, tag, n))
    _chk(ctx, PUSH_ALL_ONCE, expected > 0 and not missing and not dup, expected=expected,
         delivered=sum(ok_n.values()), missing=len(missing), dup=len(dup), first_missing=missing[:10],
         first_dup=dup[:10], by_phase=dict(Counter(o["phase"] for o in s.first.values())))

    leaks, typed, out_pairs, muted_pairs = [], [], 0, 0
    for tag, o in s.first.items():
        for name, d in devs.items():
            if o["aid"] not in d.scope:
                out_pairs += 1
                if any_n[(name, tag)]:
                    leaks.append((name, d.kind, sorted(d.scope)[:3], tag))
            elif not d.wants(o["aid"], o["tk"]):
                muted_pairs += 1
                if any_n[(name, tag)]:
                    typed.append((name, d.types, d.platforms, o["tk"], tag))
    partial = sum(1 for d in devs.values() if d.kind == "chatter" and len(d.scope) < len(s.by_agency[d.agency]))
    _chk(ctx, PUSH_SCOPE, out_pairs > 0 and partial > 0 and not leaks, out_of_scope_pairs=out_pairs,
         partial_scope_chatters=partial, leaks=len(leaks), first_leaks=leaks[:10])
    unknown = sum(1 for o in s.first.values() if o["tk"] is None)
    _chk(ctx, PUSH_TYPES, muted_pairs > 0 and unknown > 0 and not typed, muted_pairs=muted_pairs,
         unknown_type_frames=unknown, platform_off=[n for n, d in devs.items() if not d.platforms.get("onlyfans", True)],
         pushed=len(typed), first=typed[:10])

    rank = {o["tag"]: o["i"] for o in s.offers if o["phase"] == "steady"}
    aid_of = {t: o["aid"] for t, o in s.first.items()}
    out_of_order, by_dev = [], defaultdict(list)
    for r in recs[:s.phase_end["steady"]]:
        by_dev[r["sub"]].append((r["t_recv"], r["status"], (r.get("plain") or {}).get("tag")))
    for name, seq in by_dev.items():
        last: dict[str, int] = {}
        for _, st, tag in seq:
            if not (200 <= st < 300) or tag not in rank:
                continue
            a = aid_of[tag]
            if rank[tag] < last.get(a, -1):
                out_of_order.append((name, a, tag))
            last[a] = max(last.get(a, -1), rank[tag])
    steady_n = sum(1 for seq in by_dev.values() for _, st, t in seq if 200 <= st < 300 and t in rank)
    _chk(ctx, PUSH_ORDER, steady_n > 0 and not out_of_order, steady_pushes=steady_n,
         out_of_order=len(out_of_order), first=out_of_order[:10])

    watch = {t for t, n in s.n_offers.items() if n > 1} | {o["tag"] for o in s.offers if o["phase"] == "replay"}
    extra = [(dv, t, n) for (dv, t), n in ok_n.items() if t in watch and n > 1]
    replay_ok = s.replayed.get("sent", 0) > 0 and s.replayed.get("replayed") == s.replayed.get("sent")
    restart_ok = bool(s.restart) and s.restart.get("subs_loaded") is not None \
        and s.restart["subs_loaded"] >= s.restart["live"]
    _chk(ctx, PUSH_NO_REPUSH, bool(watch) and replay_ok and restart_ok and not extra, watched_tags=len(watch),
         reoffered=sum(1 for t, n in s.n_offers.items() if n > 1), replay=s.replayed,
         restart={k: v for k, v in s.restart.items() if k != "push"}, extra=len(extra), first=extra[:10])

    gone_rows = _rows(s, list(s.armed_gone))
    gone_detail = {n: {"requests_after_arm": sum(1 for t, _, _ in after[n] if t >= s.armed_gone[n]),
                       "row": gone_rows[n]} for n in s.armed_gone}
    _chk(ctx, PUSH_PRUNED_GONE, bool(gone_detail) and all(v == {"requests_after_arm": 1, "row": 0}
                                                          for v in gone_detail.values()), devices=gone_detail)

    dead_rows = _rows(s, list(s.dead))
    dead_detail = {n: {"requests_after": sum(1 for t, _, _ in after[n] if t >= s.dead[n]), "row": dead_rows[n]}
                   for n in s.dead}
    _chk(ctx, PUSH_PRUNED_DEAD, len(dead_detail) == 2 and all(v == {"requests_after": 0, "row": 0}
                                                              for v in dead_detail.values())
         and s.prune.get("rows_right_after_logout", {}).get(s.prune.get("logged_out")) == 0,
         devices=dead_detail, logout_row_right_after=s.prune.get("rows_right_after_logout"),
         revoker_reput=s.prune.get("revoker_reput"))

    e2e = [r["t_recv"] * 1000 - s.first[r["plain"]["tag"]]["t0"] for r in recs[:s.phase_end["steady"]]
           if 200 <= r["status"] < 300 and (r.get("plain") or {}).get("tag") in rank]
    p95 = _p95(e2e)
    ctx.check(f"p95 frame -> push (steady) <= {E2E_P95_MS}ms", p95 is not None and p95 <= E2E_P95_MS, budget=True,
              p95=p95, n=len(e2e), p50=round(sorted(e2e)[len(e2e) // 2], 1) if e2e else None, max=max(e2e, default=None))
    put = ctx.rec.summary().get(PUT_ROUTE)
    ctx.check(f"p95 {PUT_ROUTE} <= {PUT_P95_MS}ms", bool(put) and put["p95_ms"] <= PUT_P95_MS, budget=True,
              p95=put and put["p95_ms"], n=put["n"] if put else 0)
    ctx.metric("p95_vs_last_green", {E2E_KEY: p95, PUT_ROUTE: put and put["p95_ms"]})
    ctx.metric("p95_vs_last_green_n", {E2E_KEY: len(e2e), PUT_ROUTE: put["n"] if put else 0})
    ctx.metric("pushes", {"requests": len(recs), "ok": sum(1 for r in recs if 200 <= r["status"] < 300),
                          "by_status": dict(Counter(str(r["status"]) for r in recs)),
                          "offers": len(s.offers), "tags": len(s.first), "phase_end_records": s.phase_end})


def _wire_checks(s: _S) -> None:
    recs = s.wire.snapshot()
    keys = ("v", "tag", "title", "body", "href", "type")
    bad_plain = []
    for r in recs:
        p = r.get("plain")
        if not isinstance(p, dict) or p.get("v") != 1 or any(k not in p for k in keys):
            bad_plain.append((r["sub"], r.get("decrypt_error") or p))
            continue
        test = str(p.get("tag", "")).startswith("test-")
        if not test and (not p.get("account_id") or not str(p["tag"]).startswith(f"{p['account_id']}:")):
            bad_plain.append((r["sub"], p))
    s.ctx.check(PUSH_DECRYPT, bool(recs) and not bad_plain, requests=len(recs), bad=len(bad_plain),
                first=[str(b)[:300] for b in bad_plain[:5]])
    bad_vapid = [(r["sub"], r["vapid"]["why"]) for r in recs if not r["vapid"]["ok"]]
    exp = [r["vapid"]["exp_in_s"] for r in recs if r["vapid"]["exp_in_s"] is not None]
    s.ctx.check(PUSH_VAPID, bool(recs) and not bad_vapid, requests=len(recs), bad=len(bad_vapid),
                first=bad_vapid[:5], subs=sorted({str(r["vapid"]["sub"]) for r in recs})[:3],
                exp_in_h=[round(min(exp) / 3600, 2), round(max(exp) / 3600, 2)] if exp else None)
    with open(s.ctx.out / "push-records.jsonl", "w") as f:
        for r in recs:
            f.write(json.dumps(r, default=str) + "\n")


async def _ui(s: _S) -> None:
    ctx, w = s.ctx, s.w
    ctx.rec.stage = "ui"
    if ctx.app is None:
        ctx.skip(UI_TEST_BUTTON, "--no-ui")
        ctx.skip(UI_SW_SHOW, "--no-ui")
        return
    from playwright.async_api import async_playwright

    ag = w.data["agencies"][0]
    dev = PushDevice("ui", "user", ag["username"], agency.PASSWORD, 0, frozenset(s.by_agency[0]))
    await sign_in(dev, ctx.relay, ctx.rec)
    s.wire.device(dev.name, dev.priv, dev.auth)
    endpoint = s.wire.endpoint(dev.name)
    stub = STUB_JS % {"endpoint": json.dumps(endpoint), "keys": json.dumps(dev.keys())}
    detail: dict = {}
    test_ok = sw_ok = False
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(args=ui.LAUNCH_ARGS, channel="chromium")
            try:
                page = await ui._owner_page(browser, ctx, (1440, 900), [], [], (stub,), http=dev.http)
                await page.context.grant_permissions(["notifications"], origin=ctx.app)
                await page.goto(f"{ctx.app}/notifications", wait_until="domcontentloaded")
                await page.get_by_role("tablist", name="Notification types").wait_for(timeout=UI_WAIT_MS)
                detail["sw"] = await page.evaluate("""async () => { const r = await Promise.race([
                    navigator.serviceWorker.ready, new Promise((_, j) => setTimeout(() => j(new Error('sw ready timeout')), 30000))]);
                    return { script: r.active && r.active.scriptURL, perm: Notification.permission }; }""")
                cdp = await page.context.new_cdp_session(page)
                regs: list = []
                cdp.on("ServiceWorker.workerRegistrationUpdated", lambda e: regs.extend(e["registrations"]))
                await cdp.send("ServiceWorker.enable")
                await page.get_by_role("button", name="Notifications", exact=True).click()
                await page.get_by_role("tablist", name="Notification feeds").get_by_role("tab", name="Settings", exact=True).click()
                box = page.get_by_label("OS notification when tab is unfocused")
                await box.wait_for(timeout=STEP_MS)
                if not await box.is_checked():
                    await box.check()
                detail["os_checkbox"] = await box.is_checked()
                async with page.expect_response(lambda r: r.url.endswith("/push/subscription")
                                                and r.request.method == "PUT", timeout=STEP_MS) as rr:
                    await page.get_by_role("button", name="Test", exact=True).click()
                put = await rr.value
                detail["put_status"] = put.status
                await page.get_by_text("Push on: lock screen alerts active").wait_for(timeout=STEP_MS)
                detail["subscribes"] = await page.evaluate("() => window.__slopSubscribes || 0")
                await ui.shot(ctx, page, "push-test-trigger")
                row = _q1(w, "SELECT id, principal_kind, types FROM push_subscriptions WHERE endpoint=?", endpoint)
                detail["row"] = row
                test_ok = put.status == 200 and detail["os_checkbox"] and row is not None
                _chk(ctx, UI_TEST_BUTTON, test_ok, **detail)

                sent_before = (await _push_stats(s))["sent"]
                aid = s.by_agency[0][0]
                await _send(s, "ui", {aid: [_new("purchase", aid, s.fans[aid][0], s)]})
                tag = next(o["tag"] for o in reversed(s.offers) if o["phase"] == "ui")
                rec = None
                t0 = time.time()
                while rec is None and time.time() - t0 < SW_SHOW_WAIT_S:
                    rec = next((r for r in s.wire.snapshot() if r["sub"] == dev.name and 200 <= r["status"] < 300
                                and (r.get("plain") or {}).get("tag") == tag), None)
                    await asyncio.sleep(0.2)
                detail["relay_push"] = rec and {k: rec[k] for k in ("status", "plain", "headers")}
                if rec is None:
                    raise RuntimeError(f"the relay pushed nothing for {tag} to the browser's subscription")
                await page.goto("about:blank")
                for _ in range(50):
                    if regs:
                        break
                    await asyncio.sleep(0.1)
                rid = next(r["registrationId"] for r in regs if r.get("scopeURL", "").startswith(ctx.app))
                await cdp.send("ServiceWorker.deliverPushMessage",
                               {"origin": ctx.app, "registrationId": rid, "data": json.dumps(rec["plain"])})
                sw = page.context.service_workers[0]
                shown: list = []
                t0 = time.time()
                while time.time() - t0 < SW_SHOW_WAIT_S:
                    shown = await sw.evaluate("""async () => (await self.registration.getNotifications())
                        .map(n => ({ tag: n.tag, title: n.title, body: n.body }))""")
                    if any(n["tag"] == tag for n in shown):
                        break
                    await asyncio.sleep(0.3)
                detail["sw_notifications"] = shown
                await page.goto(f"{ctx.app}/notifications", wait_until="domcontentloaded")
                await page.get_by_role("tablist", name="Notification types").wait_for(timeout=UI_WAIT_MS)
                await page.evaluate(OVERLAY_JS, shown)
                await ui.shot(ctx, page, "push-settled")
                stats = await _push_stats(s)
                detail["push_sent"] = {"before": sent_before, "after": stats["sent"]}
                detail["row_after"] = _q1(w, "SELECT id FROM push_subscriptions WHERE endpoint=?", endpoint)
                five = [(st, u) for st, u in page.slop["statuses"] if st >= 500]
                detail["five_xx"] = five[:10]
                sw_ok = any(n["tag"] == tag for n in shown) and stats["sent"] > sent_before \
                    and detail["row_after"] is not None and not five
                _chk(ctx, UI_SW_SHOW, sw_ok, tag=tag, **{k: detail[k] for k in
                                                        ("sw_notifications", "push_sent", "row_after", "five_xx")})
            finally:
                await browser.close()
    except Exception as e:  # noqa: BLE001 — a UI step that cannot complete is the checks' FAIL
        err = f"{type(e).__name__}: {e}"[:600]
        if not any(c["name"] == UI_TEST_BUTTON for c in ctx.report.checks):
            _chk(ctx, UI_TEST_BUTTON, False, error=err, **detail)
        _chk(ctx, UI_SW_SHOW, False, error=err, **{k: v for k, v in detail.items() if k != "row"})
    finally:
        await dev.http.aclose()


def _q1(w, q: str, *a):
    con = w.sql()
    try:
        return con.execute(q, a).fetchone()
    finally:
        con.close()


async def run(ctx) -> None:
    from slop.seed.profiles import multi_agency_big_models as prof

    t0 = time.time()
    w = await prof.build(ctx.world, creators=ctx.param("creators", ctx.world.size["os_ping_creators"]))
    ctx.metric("seed", {"profile": PROFILE, "seconds": round(time.time() - t0, 2),
                        "creators": len(w.data["creators"]), "agencies": len(w.data["agencies"]),
                        "fans_total": sum(len(v) for v in w.data["fans"].values())})
    with PushWire() as wire:
        s = _S(ctx, w, wire)
        await _setup(s)
        listener = SseListener(s.owner.share(limits=2))
        await listener.start()
        phases = {"steady": await _steady(s), "reoffer": await _reoffer(s), "replay": await _replay(s, listener),
                  "restart": await _restart(s), "prune": await _prune(s)}
        ctx.metric("phases", phases)
        _checks(s)
        await _ui(s)
        _wire_checks(s)
        ctx.rec.stage = None
        for d in s.devs:
            await d.http.aclose()
