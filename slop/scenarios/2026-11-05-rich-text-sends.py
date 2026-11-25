from __future__ import annotations

import asyncio
import json
import time
from collections import Counter, defaultdict

from slop.lib import fansly_relay
from slop.lib.scen_pool import pool
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
EDGE = "<p>" + (_BLUE + "z" * 100 + "</span>") * 65 + "</p>"




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

    saves: dict[tuple[str, str], dict] = {}

    async def save(job: tuple[str, str]) -> None:
        aid, title = job
        r = await http.post(f"/admin/saved-replies?account_id={aid}", timeout=CALL_TIMEOUT_S,
                            json={"title": title, "text": by_title[title][0]})
        saves[job] = {"status": r.status_code, "body": r.json() if r.status_code == 200 else r.text[:300]}

    ctx.rec.stage = "save"
    await pool([(c["id"], t) for c in creators for t, *_ in SCRIPTS], save, ctx.users)
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

    stored: dict[str, dict[str, str]] = {}
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
    await pool(list(plan), send_fan, ctx.users)
    send_s = time.time() - t0
    ctx.rec.stage = None

    posted: list[dict] = []

    async def post(job: tuple[str, str]) -> None:
        aid, title = job
        r = await http.post("/api/of/v2/posts", headers={"X-Account-Id": aid}, timeout=CALL_TIMEOUT_S,
                            json={"text": (saves.get(job, {}).get("body") or {}).get("text", "")})
        posted.append({"aid": aid, "title": title, "status": r.status_code})

    await asyncio.gather(*(post((c["id"], t)) for c in of_cs for t, *_ in SCRIPTS))
    await http.aclose()

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

    r = await ctx.owner.get("/__slop/fansly/calls")
    fw = r.json()
    calls = fw["calls"]
    tok = {fansly_accounts.token(c["id"]): c["id"] for c in fansly_cs}
    msgs = [c for c in calls if c["method"] == "POST" and c["path"] == "/api/v1/message"]
    groups = [c for c in calls if c["method"] == "POST" and c["path"] == "/api/v1/group"]
    fan_of = {g["id"]: (tok.get(g["token"]), str(g["body"]["users"][1]["userId"])) for g in groups}
    per_fan_groups = Counter(fan_of.values())
    got = defaultdict(list)
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

    fake = ctx.of_wire
    with fake.lock:
        of_posts = {a: [p.get("text") for p in v] for a, v in fake.posts.items()}
    want_posts = {c["id"]: Counter(stored_ for _t, _r, stored_, _p in SCRIPTS) for c in of_cs}
    got_posts = {a: Counter(v) for a, v in of_posts.items() if a in want_posts}
    ctx.check(POST_MARKUP, all(p["status"] == 200 for p in posted) and got_posts == want_posts,
              posts=len(posted), failed=[p for p in posted if p["status"] != 200][:5],
              diff={a: dict(got_posts.get(a, Counter()) - want_posts[a]) for a in want_posts
                    if got_posts.get(a) != want_posts[a]})

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
