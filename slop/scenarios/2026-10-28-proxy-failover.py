"""An Inflowwww pool proxy dies: its Creators fail over, the proxy is rechecked and comes
back (docs/adr/0030, service/proxy_health.py).

Prod 2026-10-28 (slop/evidence/20261028T111800Z-scale-vs-load-7cc9bbd67): both pool
proxies answer CONNECT 403 in 0-32 s blips every ~5 min, every retry chain ending in a
success. A blip must move nobody (an OnlyFans session is tied to the IP it is used from:
a moved Creator is a security-check risk); a proxy that stays dead must. Now DOWN_AFTER
full-policy (5-try) failures in a row (a send's, a background read's; a read someone waits
on gives up in ~1 s and never counts) start one confirm probe, run CONFIRM_GAP_S after the
first of them so it never lands inside the same blip; a failed confirm makes the proxy bad
(surfaced, never picked for a new Creator, rechecked at PROXY_RECHECK_S doubling to 10 min)
and the second failed recheck moves its Creators to the least-used pool proxies that answer
a probe, in one registry write (clients evicted, chat sockets rerouted); a move that found
no answering destination is retried at every later failed recheck. A recheck that answers
brings it back as the standby; nobody is moved back. Prod timeline from the constants
(service/proxy_health.py, docs/adr/0030): first full-policy failure ~7.7 s after the death,
confirm at +30 s (~38 s), rechecks at +20 s and +40 s: the move about 100 s after the death
(98 s plus ~1 s of probes).

The world: one Agency with 50 Creators (`one_agency`), each with a captured session
(seed/of_sessions.py) so the relay builds its REAL OFClient; OnlyFans is lib/of_wire.py on
loopback (`OF_WIRE`), which also answers the probe's Cloudflare trace. The pool is POOL (3)
proxies, each lib/proxy_wire.py on loopback, synced into the registry through
`POST /__slop/proxy-pool` (the startup's own `proxies.sync_pool`). The owner puts ON_POOL
(12, `--set on_pool=`) Creators on the Inflowwww proxy through the product's own
`POST /admin/proxy-pool/assign` (least-used: 4 per proxy) and each reads `users/me` once
through it. Then the proxy holding the first Creator dies, and for LOAD_S (`--set load_s=`)
`--users` people (seeded picks among the Creators on the pool, so about a third of them on
the dead proxy) each read the Fan List with its manual refresh (`GET /api/of/v2/chats?refresh=1`,
the one read that bypasses relay_cache; `users/me` is cached 60 s) once a second and send a DM
every third second (`POST /api/of/v2/chats/{fan}/messages`, unique text). LOGIN_AT_S after the death the owner
logs in a Creator not on the pool: the real `POST /admin/session/bootstrap` (paste-curl),
the attach step's `POST /admin/proxy-pool/assign` (the least-used proxy is the dying one, not
yet confirmed bad: the bind's own probe passes it over), `POST /admin/reload-session`. The
harness polls the registry and `GET /admin/proxies` / `/admin/accounts` twice a second.
Then the dead proxy is revived; once the pool reads 0 bad, one more Creator is attached
and must land on it (least-used) and read through it. Last, every pool proxy dies for
ALL_DEAD_S (a provider-wide outage): the two proxies confirmed first find their failover
destination dead at the probe that precedes every move, so nobody moves, and every pool
Creator is surfaced once the last proxy is confirmed too. LOGIN_ALL_DEAD_AT_S into that outage
the owner logs in one more Creator the same way: no pick answers its probe, and the attach
must still bind it (the least-used proxy not bad) and keep the session, never throw a
finished login away. Last (re-watch), with the pool revived, a fourth pool proxy joins it
(`POST /__slop/proxy-pool` again, the three kept with their bindings) and one more Creator
is attached to it (least-used: it holds 0, every other one at least 1). It blips: dead for
DOWN_AFTER sends of that Creator at once (DOWN_AFTER full-policy failures together start its
watcher), then back, and a Fan List refresh answers through it inside the confirm's wait, so
the watcher's ConfirmDue ends it (no probe, nothing surfaced). Then it dies for good and exactly
DOWN_AFTER more sends fail through it (no more traffic). Their failures land ~7.7 s after the
kill (inferred from the 5-try chain), well after that watcher's last step, so the clean run only
proves a streak after a watcher's end is watched; the window right at the end (microseconds in
the relay) is pinned by service/tests/test_proxy_health.py
(case_an_error_right_after_the_watchers_last_step_starts_a_new_watcher), and only the fault
below widens it enough for this traffic to land in. Last (recheck-gap), a custom proxy
CUSTOM_LABEL (`POST /admin/proxies`, the owner's own; custom so its `health` is listed and it is
never failed over) dies and the owner presses its Test button (`POST /admin/proxies/{label}/test`,
a probe counted like a call) DOWN_AFTER times: its watcher confirms it bad and rechecks it
(2 s, 4 s, 8 s). Once a recheck is armed at least WINDOW_S out (`health.next_recheck_at`), it
revives and one Test answers (back up), then it dies again and DOWN_AFTER Tests fail, all before
that recheck is due: the errors start no watcher (the sleeping one holds the claim), so only that
watcher, waking to a proxy at DOWN_AFTER, can confirm it bad again.

Invariants: the binding went through (4/4/4, each warm-up tunneled); the dead proxy's
Creators are on a healthy pool proxy within FAILOVER_MS of the death and their reads and
sends after the move answer 200 (budget); before the move the relay surfaced it (pool
`bad` 1, `proxy_down` on exactly its Creators); the Creator logged in during the outage was
bound once, to a healthy proxy, and still is; no send was duplicated (a 200 is in
OnlyFans' record exactly once, a 502 never, no text twice); Creators on the healthy
proxies answered 200 throughout; the revived proxy is back within BACK_MS and the next
Creator lands on it (the least-used, judged from the bindings) while the moved ones stay put; with every proxy dead the bindings are
byte-identical (but for the outage login) and all pool Creators read `proxy_down`; the
outage login was saved and bound to a pool proxy, its attach answering within
LOGIN_ASSIGN_MS (the probes are bounded); the re-watch proxy was not surfaced by its blip and
is surfaced (its Creator proxy_down) within REWATCH_MS of dying for good, every
send through it dead answering 502 and the refresh 200; the recheck-gap proxy, back up then at
DOWN_AFTER inside a recheck's sleep (asserted against next_recheck_at), is bad again within
REBAD_MS of its streak; lib/of_wire.py saw only signed calls it models. p95 of the healthy
reads vs the last green run. DOWN_AFTER is read from service/proxy_health_decide.py's source.

Bypasses, declared: the pool is synced by the hook, not the env (the fake proxies' ports
exist only once the relay is up); `PROXY_RECHECK_S=2` (RELAY_ENV) compresses the whole
cadence tenfold (rechecks 2 s doubling, the confirm's wait 3 s), so the move that takes
about 100 s on prod takes about 7.7 + 3 + 2 + 4 = ~17 s here, plus the wait for the
first counted failure (the first send through the dead proxy, ~4 s in) (the state machine
is the same code); the proxies are SOCKS5 on loopback that
refuse each CONNECT after 0.33 s (lib/proxy_wire.py: curl 97, not prod's 56, both
`ProxyError`); the probe's trace is lib/of_wire.py's `/cdn-cgi/trace`; people are httpx
pools on their own recorder (their reads of a dead Creator 502 on purpose; the stock no-5xx
check covers the owner's calls, this scenario's checks cover theirs); the login is a
re-capture of a seeded Creator (`account_id` given), the Add creator flow's relay calls
without its browser. The re-watch's window: in the relay it was microseconds (the claim
dropped after the watcher returned), which no traffic can hit on purpose, so the fault widens
it (below); a plain revert of the claim fix passes this scenario (the unit case above is its
pin); the re-watch proxy's sends go through a recorder of their own (their 502s are on purpose).
The recheck-gap's counted errors are Test-button probes, not Creator traffic (a pool proxy has
no Test and is failed over at the 2nd failed recheck; the counting is the same `record`).

Break-it-once: proxy-failover-never-moves (the move gone) turns only the failover check
red; `--fault=proxy-recheck-never-runs` (no recheck, so no move either) turns the
failover and the recheck checks red; `--fault=pool-assign-drops-unanswered-login` (the attach
refuses a Creator on no pool proxy when no pick answers) turns only the outage-login check red.
The rules are a pure `service/proxy_health_decide.decide`; `--fault=proxy-decide-recheck-answer-ignored`
breaks it in the relay (an answering recheck read as failed) and turns only the revived-proxy check red.
`--fault=proxy-watch-claim-released-late` puts the claim's release back after the watcher returns
(every Unwatch dropped) and widens that window to 60 s: the re-watch proxy's streak finds the claim
still held and is never watched, so the re-watch check goes red; so does the pool-wide outage's
(the proxy revived just before it dies again inside its window: never confirmed bad), the same bug.
`--fault=proxy-recheck-unwatches-at-threshold` puts back the recheck phase's old not-bad exit
(Unwatch whatever the count): the recheck-gap proxy sits at DOWN_AFTER unwatched, so only the
recheck-gap check goes red. `proxy-recheck-never-runs` also turns the recheck-gap check red (noise,
not its target: with no recheck armed that stage cannot be set up).
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections import Counter
from contextlib import ExitStack
from pathlib import Path

from slop.lib.browserbase import paste_curl
from slop.lib.client import Recorder
from slop.lib.procmon import pct
from slop.lib.proxy_wire import REFUSE_S, ProxyWire
from slop.seed import of_sessions

PROFILE = "one_agency"
UI = False
OF_WIRE = True
FAULT = "proxy-failover-never-moves"
RELAY_ENV = {"PROXY_RECHECK_S": "2"}   # declared: 20 s doubling on prod, 2 s doubling here
P95_VS_LAST = (1.5, 100)
P95_VS_LAST_MIN_N = 50
POOL = 3
ON_POOL = 12
LOAD_S = 30.0          # people read and send through the outage and the move
LOGIN_AT_S = 3.0       # the owner's login, into the outage
FAILOVER_MS = 30_000   # death -> every Creator of the dead proxy on a healthy one, reads 200
BACK_MS = 40_000       # revival -> pool reads 0 bad
ALL_DEAD_S = 35.0      # every proxy dead: each is confirmed ~11 s in (sends' 5-try failures ~7.7 s + the 3 s confirm gap); the rest is margin
LOGIN_ALL_DEAD_AT_S = 1.0   # the owner's login into the pool-wide outage, before any proxy is confirmed bad
LOGIN_ASSIGN_MS = 12_000    # its attach: at most 2 probes of <= 5 s each (refused here in 0.33 s), plus margin
REWATCH_MS = 25_000         # dead for good -> its Creators proxy_down: sends' 5-try failures ~7.7 s + the 3 s confirm gap
RECHECK_ARMED_MS = 40_000   # recheck-gap: dead -> bad with a recheck armed >= WINDOW_S out (gap 3 s, rechecks 2, 4, 8 s)
WINDOW_S = 3.0              # what the answer + the DOWN_AFTER Tests need inside that recheck's sleep (~1.5 s), plus margin
REBAD_MS = 20_000           # the streak's end -> bad again: the rest of that sleep (<= 8 s) + the 3 s confirm gap + a probe
CUSTOM_LABEL = "slop-recheck-gap"
REV = "slop-of-rev-202610281200"

READ = "/api/of/v2/users/me"                      # the warm-up and the new Creator's first read (cached 60 s after)
PEOPLE_READ = "/api/of/v2/chats?limit=5&refresh=1"  # the Fan List's manual refresh: bypasses relay_cache, reaches OF
C_BIND = "pool: ON_POOL Creators bound least-used through /admin/proxy-pool/assign, each warm-up tunneled"
C_MOVE = "dead pool proxy: its Creators are on a healthy pool proxy within budget, reads and sends answer again"
C_SURF = "dead pool proxy: surfaced before the move (pool bad=1, proxy_down on exactly its Creators)"
C_LOGIN = "login during the outage: bound once, to a healthy pool proxy, and never moved"
C_SENDS = "sends never duplicated: each 200 once in OnlyFans' record, each 502 never, no text twice"
C_HEALTHY = "healthy pool proxies: every read and send of their Creators answered 200 throughout"
C_BACK = ("revived proxy: the recheck brings it back within budget and the next new Creator lands on the least-used "
          "proxy (the revived one, once its Creators moved) and reads through it")
C_NOSTANDBY = "every pool proxy dead: nobody moves (bindings identical) and every pool Creator reads proxy_down"
C_LOGIN_ALL_DEAD = ("login during a pool-wide outage: no probe answers, yet the session is saved and bound to a pool "
                    "proxy within budget (a login is never lost; every-proxy-bad: test_proxy_health)")
C_REWATCH = ("re-watch: a pool proxy that dies for good right after a blip ended its watcher is watched again and "
             "surfaced within budget (its Creator reads proxy_down)")
C_RECHECK_GAP = ("recheck-gap: a bad proxy an answer brings back while its watcher sleeps before a recheck, then "
                 "DOWN_AFTER failed Tests before it wakes, is confirmed bad again by that watcher within budget")
C_WIRE = "lib/of_wire.py saw only signed calls it models"


def _service_int(module: str, name: str) -> int:
    """A service constant, read from the source the relay runs (this harness never imports service/)."""
    src = (Path(__file__).resolve().parents[2] / "service" / f"{module}.py").read_text()
    return int(re.search(rf"^{name} = (\d+)", src, re.M).group(1))


DOWN_AFTER = _service_int("proxy_health_decide", "DOWN_AFTER")   # counted failures in a row that start the watcher


def _plain(html: str) -> str:
    return re.sub(r"</?p>", "", html or "")


class _Registry:
    """The relay's registry file (its own temp dir): label per Creator, read as the relay wrote it."""

    def __init__(self, path):
        self.path = path

    def bindings(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        return {aid: p["label"] for p in data.get("proxies", []) for aid in (p.get("assigned_account_ids") or [])}

    def pool_labels(self) -> dict[str, int]:
        data = json.loads(self.path.read_text())
        return {p["label"]: p["port"] for p in data["proxies"] if p.get("pool")}


async def _call(http, kind: str, aid: str, path: str, method: str = "GET", body=None, text=None) -> dict:
    t0 = time.perf_counter()
    try:
        if method == "GET":
            r = await http.get(path, headers={"X-Account-Id": aid})
        else:
            r = await http.post(path, headers={"X-Account-Id": aid}, json=body)
        status = r.status_code
        detail = (r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json")
                  else None) if status >= 400 else None
    except Exception:  # noqa: BLE001  transport error: 599 as the recorder does
        status, detail = 599, None
    return {"kind": kind, "aid": aid, "status": status, "ms": (time.perf_counter() - t0) * 1000,
            "t0": t0, "t1": time.perf_counter(), "text": text, "detail": detail}


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    of_sessions.seed(w, w.data["creators"])
    main = w.data["agencies"][0]["user_id"]
    aids = [c["id"] for c in w.data["creators"] if c["owner"] == main]
    n_on = int(ctx.param("on_pool", ON_POOL))
    on_pool, login_aid, back_aid, late_aid = aids[:n_on], aids[n_on], aids[n_on + 1], aids[n_on + 2]
    refuse = float(ctx.param("refuse_ms", REFUSE_S * 1000)) / 1000
    reg = _Registry(ctx.stack.sessions.parent / "proxies.json")
    fake = ctx.of_wire
    n0 = len(fake.calls)
    with ExitStack() as stack:
        wires = [stack.enter_context(ProxyWire(refuse)) for _ in range(POOL)]
        spare = stack.enter_context(ProxyWire(refuse))    # joins the pool for the re-watch only
        custom = stack.enter_context(ProxyWire(refuse))   # the recheck-gap's custom proxy
        text = await _run(ctx, w, reg, wires, on_pool, login_aid, back_aid, late_aid)
        await _rewatch(ctx, reg, text, spare, aids[n_on + 3], w.data["fans"])
        await _recheck_gap(ctx, custom)
    ctx.check(C_WIRE, fake.unsigned == 0 and not fake.unmodelled, unsigned=fake.unsigned,
              unmodelled=dict(fake.unmodelled), of_calls=len(fake.calls) - n0)


async def _rewatch(ctx, reg: _Registry, pool_text: str, spare: ProxyWire, aid: str, fans: dict) -> None:
    """A fourth pool proxy, one Creator on it: a blip whose watcher the confirm's wait ends, then dead for
    good with exactly DOWN_AFTER failures (its sends, together) landing just after that end (module docstring)."""
    owner = ctx.owner
    budget_ms = float(ctx.param("rewatch_ms", REWATCH_MS))
    r = await owner.post("/__slop/proxy-pool", json={"text": f"{pool_text},socks5://127.0.0.1:{spare.port}"})
    label = next((lb for lb, port in reg.pool_labels().items() if port == spare.port), None)
    bound = (await owner.post("/admin/proxy-pool/assign", json={"account_id": aid})).status_code
    on = reg.bindings().get(aid)   # least-used: the new proxy holds 0, every other pool proxy >= 1
    http = owner.share(rec=Recorder(), limits=2 * DOWN_AFTER + 4)   # declared: its dead sends 502 on purpose
    to = [f["id"] for f in fans[aid]]

    async def sends(tag: str) -> list[dict]:   # DOWN_AFTER full-policy failures together, then nothing
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
    blip = await sends("blip")   # its watcher starts and waits the confirm gap
    spare.revive()
    answer = await _call(http, "read", aid, PEOPLE_READ)   # inside the gap: the count resets; ConfirmDue ends it
    before = await down_now()
    t_dead = time.perf_counter()
    spare.kill()
    dead = await sends("dead")   # dead for good: the streak lands right after the watcher ended
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


async def _recheck_gap(ctx, wire: ProxyWire) -> None:
    """A custom proxy (Test button, listed `health`; never failed over) dies: DOWN_AFTER failed Tests make it
    bad. While its watcher sleeps before a recheck at least WINDOW_S out, it answers a Test (back up), then
    dies again and fails DOWN_AFTER Tests, all before that recheck is due: the waking watcher must confirm
    it bad again (module docstring)."""
    owner = ctx.owner
    test = f"/admin/proxies/{CUSTOM_LABEL}/test"

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

    async def tests(n: int) -> list[int]:
        return [(await owner.post(test)).status_code for _ in range(n)]

    ctx.rec.stage = "recheck-gap"
    made = (await owner.post("/admin/proxies", json={"label": CUSTOM_LABEL, "scheme": "socks5",
                                                       "host": "127.0.0.1", "port": wire.port})).status_code
    wire.kill()
    first = await tests(DOWN_AFTER)   # dead: DOWN_AFTER counted errors start its watcher
    armed, armed_at = await until(lambda h: h.get("state") == "bad" and h.get("next_recheck_at") is not None
                                  and h["next_recheck_at"] - time.time() >= WINDOW_S,
                                  float(ctx.param("recheck_armed_ms", RECHECK_ARMED_MS)))
    due = armed.get("next_recheck_at")
    lead_s = round(due - time.time(), 2) if armed_at else None   # how far out that recheck was
    wire.revive()
    answer = await owner.post(test)   # an answer through it: back up (its watcher sleeps on)
    up = (await health()).get("state")
    wire.kill()
    streak = await tests(DOWN_AFTER)   # at DOWN_AFTER again; the watcher's claim is held, so none starts
    t_streak, t0 = time.time(), time.perf_counter()
    after = (await health()).get("state")
    rebad_ms = float(ctx.param("rebad_ms", REBAD_MS))
    bad, bad_at = await until(lambda h: h.get("state") in ("bad", "rechecking"), rebad_ms)
    ctx.rec.stage = None
    wire.revive()
    in_window = due is not None and t_streak < due
    ctx.check(C_RECHECK_GAP, made == 200 and all(c == 200 for c in first + streak) and armed_at is not None
              and answer.status_code == 200 and answer.json().get("ok") is True and up == "healthy"
              and after == "suspect" and in_window and bad_at is not None, budget=True,
              rebad_ms=round((bad_at - t0) * 1000, 1) if bad_at else None, budget_ms=rebad_ms, create=made,
              first_tests=Counter(first), armed=armed_at is not None, armed_lead_s=lead_s, answer=answer.status_code, up=up, streak_tests=Counter(streak), after_streak=after,
              streak_before_recheck_s=round(due - t_streak, 2) if due else None, in_window=in_window,
              final_state=bad.get("state"))


async def _run(ctx, w, reg: _Registry, wires: list[ProxyWire], on_pool: list[str], login_aid: str, back_aid: str,
               late_aid: str) -> str:
    """The pool stages (bind, death and move, revival, pool-wide outage). Returns the pool's sync text."""
    owner, fake = ctx.owner, ctx.of_wire
    load_s = float(ctx.param("load_s", LOAD_S))
    failover_ms = float(ctx.param("failover_ms", FAILOVER_MS))
    back_ms = float(ctx.param("back_ms", BACK_MS))

    # ── the pool (the startup's sync, run now), ON_POOL Creators attached, each warmed through its proxy ──
    text = ",".join(f"socks5://127.0.0.1:{p.port}" for p in wires)
    r = await owner.post("/__slop/proxy-pool", json={"text": text})
    synced = r.status_code == 200 and r.json().get("size") == POOL
    by_port = {p.port: p for p in wires}
    label_wire = {label: by_port[port] for label, port in reg.pool_labels().items()}
    bound = [(await owner.post("/admin/proxy-pool/assign", json={"account_id": a})).status_code for a in on_pool]
    binding = reg.bindings()
    per_label = Counter(binding.get(a) for a in on_pool)
    warm = await asyncio.gather(*(_call(owner, "warm", a, READ) for a in on_pool))
    tunneled = {label: sum(1 for c in wire.connects if c["alive"]) for label, wire in label_wire.items()}
    spread = sorted(per_label.values()) == sorted([len(on_pool) // POOL + (1 if i < len(on_pool) % POOL else 0)
                                                   for i in range(POOL)])
    ctx.check(C_BIND, synced and all(s == 200 for s in bound) and spread and set(per_label) <= set(label_wire)
              and all(x["status"] == 200 for x in warm)
              and all(tunneled[label] >= n for label, n in per_label.items()),
              synced=synced, assign=Counter(bound), per_proxy=dict(per_label), tunneled=tunneled,
              warm=Counter(x["status"] for x in warm))

    # ── the proxy holding the first Creator dies; people read and send; the owner logs a Creator in ──
    dead_label = binding[on_pool[0]]
    dead_wire = label_wire[dead_label]
    dead = sorted(a for a in on_pool if binding[a] == dead_label)
    healthy = sorted(a for a in on_pool if binding[a] != dead_label)
    rng = w.rng("proxy_failover_people")
    picks = [rng.choice(on_pool) for _ in range(ctx.users)]
    fans = w.data["fans"]
    people_rec = Recorder()   # declared: their dead reads 502 on purpose
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
            b = reg.bindings()
            pr = await owner.get("/admin/proxies")
            ac = await owner.get("/admin/accounts")
            pool = pr.json().get("pool", {}) if pr.status_code == 200 else {}
            down = sorted(a["id"] for a in ac.json().get("accounts", []) if a.get("proxy_down")) \
                if ac.status_code == 200 else None
            polls.append({"t": time.perf_counter(), "on_dead": sorted(a for a in on_pool if b.get(a) == dead_label),
                          "bad": pool.get("bad"), "down": down, "bindings": b})
            if not polls[-1]["on_dead"] and not moved_at:
                moved_at.append(time.perf_counter())
            await asyncio.sleep(0.5)

    async def login(at: float, aid: str = login_aid) -> dict:
        await asyncio.sleep(at)
        boot = await owner.post("/admin/session/bootstrap", timeout=60, json={
            "mode": "paste-curl", "curl": paste_curl(aid, REV, "login"), "account_id": aid, "make_active": False})
        t_att = time.perf_counter()
        att = await owner.post("/admin/proxy-pool/assign", timeout=60, json={"account_id": aid})
        assign_ms = round((time.perf_counter() - t_att) * 1000, 1)
        label = reg.bindings().get(aid)
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
    final = reg.bindings()

    t_moved = (moved_at[0] - t_dead) * 1000 if moved_at else None
    after = [x for x in seen if x["aid"] in dead and moved_at and x["t0"] > moved_at[0] + 1.0]
    after_bad = Counter(f"{x['kind']} {x['status']}" for x in after if x["status"] != 200)
    now_on = {a: final.get(a) for a in dead}
    ctx.check(C_MOVE, t_moved is not None and t_moved <= failover_ms
              and all(lbl in label_wire and lbl != dead_label for lbl in now_on.values())
              and bool(after) and not after_bad, budget=True,
              moved_ms=round(t_moved, 1) if t_moved else None, budget_ms=failover_ms, now_on=now_on,
              after_move_calls=len(after), after_move_not_200=dict(after_bad))

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

    with fake.lock:   # the relay sends OF web's `<p>text</p>`: compared on the text inside
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

    # ── the dead proxy revives: the recheck brings it back, the next Creator lands on it ──
    t_rev = time.perf_counter()
    dead_wire.revive()
    back_at = None
    while time.perf_counter() - t_rev < back_ms / 1000:
        pr = await owner.get("/admin/proxies")
        if pr.status_code == 200 and pr.json().get("pool", {}).get("bad") == 0:
            back_at = time.perf_counter()
            break
        await asyncio.sleep(0.5)
    # Least-used before the bind: the revived proxy alone once its Creators moved (0 held). Judged from the
    # bindings, so a run where nobody moved (a fault) is not read as a wrong pick.
    held = Counter(reg.bindings().get(a) for a in [*on_pool, login_aid])
    least = min(held.get(label, 0) for label in label_wire)
    least_used = sorted(label for label in label_wire if held.get(label, 0) == least)
    r = await owner.post("/admin/proxy-pool/assign", json={"account_id": back_aid})
    back_label = reg.bindings().get(back_aid)
    back_wire = label_wire.get(back_label)
    c1 = len(back_wire.connects) if back_wire else 0
    back_read = await _call(owner, "back", back_aid, READ)
    through = sum(1 for c in back_wire.connects[c1:] if c["alive"]) if back_wire else 0
    stayed = {a: reg.bindings().get(a) for a in dead}
    ctx.check(C_BACK, back_at is not None and r.status_code == 200 and back_label in least_used
              and back_read["status"] == 200 and through >= 1
              and all(lbl == now_on[a] for a, lbl in stayed.items()), budget=True,
              back_ms=round((back_at - t_rev) * 1000, 1) if back_at else None, budget_ms=back_ms,
              least_used=least_used, revived=dead_label, new_creator_on=back_label, read=back_read["status"],
              tunneled=through, moved_stayed=all(lbl == now_on[a] for a, lbl in stayed.items()))

    # ── every pool proxy dies: nobody can move, nobody does; every pool Creator is surfaced ──
    all_pool = sorted(a for a, lbl in reg.bindings().items() if lbl in label_wire)
    b0 = reg.bindings()
    for p in wires:
        p.kill()
    ctx.rec.stage = "all-dead"
    until = time.perf_counter() + float(ctx.param("all_dead_s", ALL_DEAD_S))
    polls.clear()
    moved_at.clear()
    rng2 = w.rng("proxy_failover_people_2")   # every pool Creator gets a person, the rest at random
    picks2 = (all_pool + [rng2.choice(all_pool) for _ in range(ctx.users)])[:max(ctx.users, len(all_pool))]
    late, *_ = await asyncio.gather(login(float(ctx.param("login_all_dead_at_s", LOGIN_ALL_DEAD_AT_S)), late_aid),
                                    poll(until), *(person(n, a, until) for n, a in enumerate(picks2)))
    ctx.rec.stage = None
    b1 = reg.bindings()
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
    return text
