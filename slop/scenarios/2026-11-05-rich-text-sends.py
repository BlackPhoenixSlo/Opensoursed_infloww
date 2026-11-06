"""Formatted scripts (OF rich text, PR #233 + its service gaps): saved through Growth > Scripts, then sent: to Fansly
fans as the plain text a fan reads (Fansly renders `content` literally), to OnlyFans as OF's allow-listed markup.

World: `agency_inbox` (small 3 Creators x 50 fans, medium 10 x 500). The last `--fansly_creators=` (FLOW_SIZES
`rich_text_fansly_creators`) are Fansly accounts (seed/fansly_accounts.py: meta `platform: fansly` + a captured
session, so the relay builds its REAL `FanslyShimClient`), Fansly's API the loopback fake of lib/fansly_relay.py
(armed here); the rest OnlyFans Creators with a captured session (seed/of_sessions) against lib/of_wire.py
(`OF_WIRE`), so the relay's real `OFClient` posts.

Flow:
  S  per Creator, every script of SCRIPTS (hostile markup included) through the real `POST /admin/saved-replies`
     (`--users` at once), then the over-limit bodies (6501 plain characters, bare and in markup) on create and on
     update of the Creator's first script, and the 6500 edge inside heavy markup.
  F  the picker's send: `--sends=` (FLOW_SIZES `rich_text_sends`) sends over the Fansly Creators' fans, each the
     stored text of a script read back from `GET /admin/saved-replies`, through the real
     `POST /api/of/v2/chats/{fan}/messages`; a fan's sends one after another (a chatter's), `--users` fans at once.
  P  per OnlyFans Creator, every script's stored text as a feed post (`POST /api/of/v2/posts`), all at once.

Checks (names in lib/rich_text_faults.py); every expected value is written out in SCRIPTS, never computed by the
product's of_rich_text:
  SAVED         each create 200 with the script's allow-listed text; its saved_replies row (SQL) holds exactly it.
  OVER          every over-limit create / update 400; no row with it (SQL), the updated script unchanged; the 6500
                edge 200.
  FANSLY_PLAIN  every Fansly wire `POST /api/v1/message` `content` == the script's plain text.
  FANSLY_SENT   every send 200; the fake got exactly one `POST /message` per send, each signed, with that Creator's
                token, per fan one minted group, nothing unmodelled.
  POST_MARKUP   every OF wire `POST /api2/v2/posts` text == the script's allow-listed markup.
Budgets: p95 of the send (F) and the save (S) at --users, both vs the last green run; stock no 5xx / Traceback.

Break-it-once: fansly-sends-markup (the scenario's FAULT: the Fansly shim sends the word guard's output, OF markup
raw, as before the fix) turns FANSLY_PLAIN red, nothing else.

Bypasses (declared): Fansly is lib/fansly_relay.py's fake (its docstring); OnlyFans is lib/of_wire.py's. The owner
calls are httpx pools, not the app: the picker's pick is a read of the stored text, then the send route the
composer calls with it.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import Counter, defaultdict

from slop.lib import fansly_relay
from slop.lib.rich_text_faults import (BUDGET, FANSLY_PLAIN, FANSLY_SENT, OVER, POST_MARKUP, SAVE_ROUTE, SAVED,
                                       SEND_ROUTE)
from slop.seed import fansly_accounts, of_sessions

PROFILE = "agency_inbox"
UI = False
OF_WIRE = True
FAULT = "fansly-sends-markup"
P95_MS = {SEND_ROUTE: 5_000, SAVE_ROUTE: 3_000}
P95_VS_LAST = (2.0, 2000)
CALL_TIMEOUT_S = 120

_BLUE = '<span class="m-editor-fs__l m-editor-fc__blue-1">'
# (title, text sent to the route, stored = OF's allow-list, plain = what a Fansly fan reads)
SCRIPTS = [
    ("rt bold blue", f"<p><strong>{_BLUE}Hey babe</span></strong></p>",
     f"<p><strong>{_BLUE}Hey babe</span></strong></p>", "Hey babe"),
    ("rt hostile", '<p>hi <strong onclick="steal()">you</strong><img src=x onerror=alert(1)>'
                   '<script>evil()</script><span class="evil m-editor-fc__gray">!</span></p>',
     '<p>hi <strong>you</strong><span class="m-editor-fc__gray">!</span></p>', "hi you!"),
    ("rt pasted list", "<p>menu:</p><ul>\n<li>pics $10</li>\n<li>vids $20</li>\n</ul>",
     "<p>menu:</p><p>pics $10</p><p>vids $20</p>", "menu:\npics $10\nvids $20"),
    ("rt lines", "<p>a &amp; b<br>c&nbsp;d</p><p><em>e</em> &lt;3</p>",
     "<p>a &amp; b<br>c&nbsp;d</p><p><em>e</em> &lt;3</p>", "a & b\nc d\ne <3"),
    ("rt bare tags", "hey <b>babe</b> <i>xx</i>", "<p>hey <strong>babe</strong> <em>xx</em></p>", "hey babe xx"),
    ("rt plain", "plain <3 u & <VIP20>", "plain <3 u & <VIP20>", "plain <3 u & <VIP20>"),
]
OVER_BODIES = ["x" * 6501, "<p>" + "y" * 6501 + "</p>"]
EDGE = "<p>" + (_BLUE + "z" * 100 + "</span>") * 65 + "</p>"   # 6500 plain characters, ~9.5k raw


async def _pool(items, fn, n: int) -> None:
    it = iter(list(items))

    async def worker():
        for x in it:
            await fn(x)

    await asyncio.gather(*(worker() for _ in range(max(1, n))))


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    creators = w.data["creators"]
    n_fansly = min(ctx.param("fansly_creators", w.size["rich_text_fansly_creators"]), len(creators) - 1)
    fansly_cs, of_cs = creators[len(creators) - n_fansly:], creators[:len(creators) - n_fansly]
    of_sessions.seed(w, of_cs)
    fansly_accounts.seed(w, fansly_cs)
    await fansly_relay.arm(ctx.owner)
    n_sends = ctx.param("sends", w.size["rich_text_sends"])
    by_title = {t: (raw, stored, plain) for t, raw, stored, plain in SCRIPTS}
    http = ctx.owner.share(limits=ctx.users + 8)

    # ── S: save every script on every Creator, then the over-limit bodies ─────
    saves: dict[tuple[str, str], dict] = {}

    async def save(job: tuple[str, str]) -> None:
        aid, title = job
        r = await http.post(f"/admin/saved-replies?account_id={aid}", timeout=CALL_TIMEOUT_S,
                            json={"title": title, "text": by_title[title][0]})
        saves[job] = {"status": r.status_code, "body": r.json() if r.status_code == 200 else r.text[:300]}

    ctx.rec.stage = "save"
    await _pool([(c["id"], t) for c in creators for t, *_ in SCRIPTS], save, ctx.users)
    ctx.rec.stage = None
    over: list[dict] = []
    for c in creators:
        first = saves.get((c["id"], SCRIPTS[0][0]), {}).get("body")
        for text in OVER_BODIES:
            r = await http.post(f"/admin/saved-replies?account_id={c['id']}", json={"title": "rt over", "text": text})
            over.append({"aid": c["id"], "op": "create", "status": r.status_code})
            if isinstance(first, dict):
                u = await http.put(f"/admin/saved-replies/{first['id']}", json={"title": SCRIPTS[0][0], "text": text})
                over.append({"aid": c["id"], "op": "update", "status": u.status_code})
    edge = await http.post(f"/admin/saved-replies?account_id={creators[0]['id']}",
                           json={"title": "rt edge", "text": EDGE})

    # ── F: Fansly sends of the stored scripts, per fan in order ───────────────
    stored: dict[str, dict[str, str]] = {}   # aid -> title -> text as the picker reads it
    for c in fansly_cs:
        r = await http.get(f"/admin/saved-replies?account_id={c['id']}")
        stored[c["id"]] = {x["title"]: x["text"] for x in (r.json()["list"] if r.status_code == 200 else [])}
    targets = [(c["id"], f["id"]) for c in fansly_cs for f in w.data["fans"][c["id"]]]
    plan: dict[tuple[str, int], list[str]] = defaultdict(list)
    for i in range(n_sends):
        plan[targets[i % len(targets)]].append(SCRIPTS[i % len(SCRIPTS)][0])
    sends: list[dict] = []

    async def send_fan(key: tuple[str, int]) -> None:
        aid, fan = key
        for title in plan[key]:
            r = await http.post(f"/api/of/v2/chats/{fan}/messages", headers={"X-Account-Id": aid},
                                timeout=CALL_TIMEOUT_S, json={"text": stored[aid].get(title, "")})
            sends.append({"aid": aid, "fan": fan, "title": title, "status": r.status_code,
                          "text": r.json().get("text") if r.status_code == 200 else r.text[:300]})

    ctx.rec.stage = "send"
    t0 = time.time()
    await _pool(list(plan), send_fan, ctx.users)
    send_s = time.time() - t0
    ctx.rec.stage = None

    # ── P: OF posts of the stored scripts ─────────────────────────────────────
    posted: list[dict] = []

    async def post(job: tuple[str, str]) -> None:
        aid, title = job
        r = await http.post("/api/of/v2/posts", headers={"X-Account-Id": aid}, timeout=CALL_TIMEOUT_S,
                            json={"text": (saves.get(job, {}).get("body") or {}).get("text", "")})
        posted.append({"aid": aid, "title": title, "status": r.status_code})

    await asyncio.gather(*(post((c["id"], t)) for c in of_cs for t, *_ in SCRIPTS))
    await http.aclose()

    # ── SAVED / OVER: the route's answers and the rows (SQL) ──────────────────
    con = w.sql()
    try:
        rows = defaultdict(list)
        for aid, title, text in con.execute("SELECT account_id, title, text FROM saved_replies"):
            rows[(str(aid), title)].append(text)
    finally:
        con.close()
    bad_save = [{"aid": aid, "title": t, "status": s["status"], "got": (s["body"] or {}).get("text")
                 if isinstance(s["body"], dict) else s["body"], "rows": rows.get((aid, t))}
                for (aid, t), s in saves.items()
                if s["status"] != 200 or s["body"].get("text") != by_title[t][1] or rows.get((aid, t)) != [by_title[t][1]]]
    ctx.check(SAVED, len(saves) == len(creators) * len(SCRIPTS) and not bad_save, saves=len(saves),
              bad=bad_save[:5])
    over_rows = [k for k, v in rows.items() if any(x in OVER_BODIES for x in v) or k[1] == "rt over"]
    ctx.check(OVER, all(o["status"] == 400 for o in over) and len(over) == 4 * len(creators) and not over_rows
              and edge.status_code == 200 and rows.get((creators[0]["id"], "rt edge")) == [EDGE],
              over=Counter(f"{o['op']} {o['status']}" for o in over), rows_with_over=over_rows[:5],
              edge=edge.status_code)

    # ── FANSLY: the fake's wire ───────────────────────────────────────────────
    r = await ctx.owner.get("/__slop/fansly/calls")
    fw = r.json()
    calls = fw["calls"]
    tok = {fansly_accounts.token(c["id"]): c["id"] for c in fansly_cs}
    msgs = [c for c in calls if c["method"] == "POST" and c["path"] == "/api/v1/message"]
    groups = [c for c in calls if c["method"] == "POST" and c["path"] == "/api/v1/group"]
    fan_of = {g["id"]: (tok.get(g["token"]), str(g["body"]["users"][1]["userId"])) for g in groups}
    per_fan_groups = Counter(fan_of.values())
    got = defaultdict(list)   # (aid, fan) -> wire contents in arrival order
    for m in msgs:
        got[fan_of.get(str(m["body"].get("groupId")), ("?", "?"))].append(m["body"].get("content"))
    want = {(a, str(f)): [by_title[t][2] for t in v] for (a, f), v in plan.items()}
    off = [{"fan": k, "want": want.get(k), "got": v} for k, v in got.items() if want.get(k) != v]
    off += [{"fan": k, "want": v, "got": None} for k, v in want.items() if k not in got]
    ctx.check(FANSLY_PLAIN, bool(msgs) and not off, messages=len(msgs), fans_off=len(off), sample=off[:3])
    ok_sends = [s for s in sends if s["status"] == 200]
    ctx.check(FANSLY_SENT, len(sends) == n_sends and len(ok_sends) == n_sends and len(msgs) == n_sends
              and all(m["signed"] and m["token"] in tok for m in msgs)
              and per_fan_groups == Counter({(a, str(f)): 1 for a, f in plan}) and not fw["unmodelled"],
              sends=len(sends), ok200=len(ok_sends), wire_messages=len(msgs), groups=len(groups),
              fans=len(plan), unmodelled=fw["unmodelled"],
              failed=[s for s in sends if s["status"] != 200][:5])

    # ── POST_MARKUP: OF's wire ────────────────────────────────────────────────
    fake = ctx.of_wire
    with fake.lock:
        of_posts = {a: [p.get("text") for p in v] for a, v in fake.posts.items()}
    want_posts = {c["id"]: Counter(stored_ for _t, _r, stored_, _p in SCRIPTS) for c in of_cs}
    got_posts = {a: Counter(v) for a, v in of_posts.items() if a in want_posts}
    ctx.check(POST_MARKUP, all(p["status"] == 200 for p in posted) and got_posts == want_posts,
              posts=len(posted), failed=[p for p in posted if p["status"] != 200][:5],
              diff={a: dict(got_posts.get(a, Counter()) - want_posts[a]) for a in want_posts
                    if got_posts.get(a) != want_posts[a]})

    # ── budgets ───────────────────────────────────────────────────────────────
    routes = {**ctx.rec.summary("save"), **ctx.rec.summary("send")}
    for route, budget in P95_MS.items():
        if route not in routes:
            ctx.skip(BUDGET[route], "no samples")
        else:
            ctx.check(BUDGET[route], routes[route]["p95_ms"] < budget, budget=True, p95=routes[route]["p95_ms"],
                      n=routes[route]["n"], budget_ms=budget)
    ctx.metric("load", {"creators": len(creators), "fansly_creators": len(fansly_cs), "users": ctx.users,
                        "sends": n_sends, "fans": len(plan), "send_s": round(send_s, 2), "routes": routes})
    ctx.metric("p95_vs_last_green", {r: routes[r]["p95_ms"] for r in P95_MS if r in routes})
    (ctx.out / "fansly-wire.json").write_text(json.dumps(calls[:200], indent=1))
    (ctx.out / "sends.json").write_text(json.dumps(sends[:200], indent=1))
