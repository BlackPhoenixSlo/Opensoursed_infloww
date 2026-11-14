"""MCP wild (service/mcp_api.py, token_auth.py, toolbox.py, report_recipe_api.py, ultra_api.py): POST /admin/mcp
under malformed, hostile and concurrent calls answers a proper JSON-RPC error (or the token layer's 401/403),
never a crash, never another Agency's data, never a send. No LLM anywhere: every path here is pure.

World: `agency_inbox` (Agency A = the run's owner, its Creators on lib/of_wire.py via `OF_WIRE`). Built here:
Agency B through the real POST /auth/register, one Creator (creators._add, i=2000) whose nickname, a bio page +
link (SQL bio_profiles/bio_links) and a sales row (SQL transactions, SENTINEL_CENTS) carry B-only sentinel strings;
B's token (real POST /admin/owner-tokens), B's plan (MCP propose_plan, never OK'd) and B's report file (MCP
report_file). A: tokens main / to-revoke (then DELETE'd) / mix; an Employee (real invite + /chatter/login, Creator
0 assigned); a 2FA owner (real register, then SQL users.totp_secret: declared bypass).

Flow: every case of lib/mcp_wild_cases.py in order: protocol, auth, token scope (direct routes), args, plans (+ the
never-OK'd plan's follow-ups), report files, sign-up/login (each on its own X-Forwarded-For 203.0.113.x so the
login throttles never cross cases; then a burst of 8 wrong logins on one name/address), the 2FA right code. Then
the volume mix: MIX[--scale] (clients, seconds) concurrent clients, each looping weighted picks of mix_table()
(tokens A/B, anon, revoked, cookie, garbage, batch, send tool …). Each answer is judged like a case.

Checks:
  no_5xx                      no case and no mix call answers ≥500 or a transport error
  jsonrpc_errors_wellformed   every /admin/mcp answer is JSON-RPC 2.0 (one of result/error; error {code known
                              int, message}; id echoed, None when unusable or refused before the body is read
                              (Case.unread); code on its HTTP status), a bodiless 202, a 405, or the token
                              layer's 401 with WWW-Authenticate: Bearer
  no_send_ever                fake OF saw no SEND_ROUTES call and holds no send/queue/post/unsend; automation_rules
                              rows unchanged; no plan running/done/needs_you; every send-tool call refused
  no_cross_agency             no answer to A/anon holds a B sentinel, none to B an A sentinel; A's calls on B's
                              Creator/page/plan/file refused (403/404); B's rows hash the same before/after; no
                              bio page on B's Creator but B's own
  send_tools_never_listed     tools/list for tokens A and B (cases + mix) names no send tool, lists both builtins
  anonymous_only_three_tools  anon (and token-in-query) tools/list == connect_account/register_account/login, and
                              an anon data tool / propose_plan / plan_status call is isError 401 with open_url
  revoked_token_dead          the revoked token: 401 on MCP (cases + mix) and on its report file
  origin_refused              any Origin header (anon or token): 403 -32600
  cookie_refused              owner cookie / Basic / employee cookie without a token: 401 -32001 (employee: 401/403)
  token_scope_403             a token on 16 routes off its allowlist (admin, OF send, rules, Ultra OK/new): 403 REFUSED
  employee_no_token           the employee's cookie gets no MCP answer and its login tool call isError 403, no token
  errors_are_plain            no error (rpc message, tool detail, plain 4xx text) shows a stack, path, exception,
                              driver, or a password/code/token the request carried
  report_file_owner_only      a report file downloads for its maker only: other Agency 404, anon 401/403, revoked 401
  no_stuck_plans              at the end no ultra_plans row is planning/running; this run's plans are awaiting_ok
  cases_answer_as_specified   every case without a named check answers its table status / code / tool outcome
Side effects: mcp-wild.json (every case: request redacted, HTTP status, rpc code + message, tool isError/status/
detail, ms, problems; the mix: p50/p95 per pick and overall, status histogram, sample problems).

FAULT `mcp-anon-sees-token-builtins` (mcp_api._builtins ignores `token`): anonymous_only_three_tools alone.

Bypasses (declared): OnlyFans is lib/of_wire.py (no real account; no folder-create handler, so no case creates a
folder on A). B's Creator, bio page/link and sales row and the 2FA secret are SQL (no product route makes them
without OF or an authenticator). X-Forwarded-For from loopback (a trusted proxy, client_addr.py) gives each hostile
login its own throttle bucket. No plan is ever OK'd (the OK needs a browser cookie and would send). Not covered:
an expired token (needs a clock or SQL on owner_tokens: product-path free but the 401 is the revoked one's code),
the 15-minute report-file expiry (TTL), MAX_PER_USER report files, report_run's 429 (needs a run in flight).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from collections import Counter, defaultdict
from urllib.parse import urlsplit

from slop.lib import mcp_wild_cases as mc
from slop.lib.client import Http
from slop.lib.mcp_wild_faults import (C_5XX, C_ANON3, C_AS_SPECIFIED, C_COOKIE, C_CROSS, C_EMPLOYEE, C_NO_SEND,
                                      C_ORIGIN, C_PLAIN, C_REPORT_FILE, C_REVOKED, C_SCOPE, C_SEND_LISTED, C_STUCK,
                                      C_WELLFORMED)
from slop.seed import agency, chatters, creators as creator_seed, of_sessions, ts

PROFILE = "agency_inbox"
UI = False
OF_WIRE = True
FAULT = "mcp-anon-sees-token-builtins"
MIX = {"small": (40, 60), "medium": (80, 120), "large": (160, 300)}   # (concurrent clients, seconds)
SENTINEL_CENTS = 777_777
SEND_ROUTES = ("POST /api2/v2/messages/queue", "POST /api2/v2/chats/{id}/messages", "POST /api2/v2/posts",
               "DELETE /api2/v2/messages/queue/{id}")
B_TABLES = (("accounts", "SELECT * FROM accounts WHERE id=?", "aid"),
            ("user_accounts", "SELECT * FROM user_accounts WHERE user_id=?", "uid"),
            ("bio_profiles", "SELECT * FROM bio_profiles WHERE owner_user_id=? ORDER BY id", "uid"),
            ("bio_links", "SELECT l.* FROM bio_links l JOIN bio_profiles p ON p.id=l.profile_id "
                          "WHERE p.owner_user_id=? ORDER BY l.id", "uid"),
            ("ultra_plans", "SELECT id, status, plan_json FROM ultra_plans WHERE owner_user_id=? ORDER BY id", "uid"),
            ("owner_tokens", "SELECT id, revoked_at FROM owner_tokens WHERE user_id=? ORDER BY id", "uid"),
            ("automation_rules", "SELECT COUNT(*) FROM automation_rules WHERE account_id=?", "aid"))


class Wild:
    """The run's identities and every judged answer."""

    def __init__(self, ctx):
        self.ctx, self.rec = ctx, ctx.rec
        self.hdrs: dict[str, dict[str, str]] = {}
        self.secrets: dict[str, str] = {}      # value -> label, for evidence redaction
        self.rows: list[dict] = []
        self.fails: dict[str, list[str]] = defaultdict(list)
        self.a_sent: tuple[str, ...] = ()
        self.b_sent: tuple[str, ...] = ()
        self.lists: dict[str, list[set]] = defaultdict(list)    # who -> tools/list name sets
        self.http = Http(ctx.relay, ctx.rec, limits=8)
        self.query_token = ""

    def fail(self, check: str, why: str) -> None:
        if len(self.fails[check]) < 40:
            self.fails[check].append(why)

    def headers(self, who: str, case_headers=(), xff: str | None = None) -> dict:
        h = dict(self.hdrs.get(who, {}))
        h.update(dict(case_headers))
        if xff:
            h["X-Forwarded-For"] = xff
        return h

    async def send(self, http: Http, case: mc.Case, route: str) -> tuple[int, str, str, str, float]:
        kw: dict = {"headers": self.headers(case.who, case.headers, case.xff)}
        if case.body is not None:
            if isinstance(case.body, bytes):
                kw["content"] = case.body
                kw["headers"].setdefault("Content-Type", "application/json")
            else:
                kw["json"] = case.body
        if case.path == mc.MCP and case.who == "a_query":
            path = f"{mc.MCP}?token={self.query_token}&access_token={self.query_token}"
        else:
            path = case.path
        http.c.cookies.clear()       # only the identity's own Cookie header, never a jar picked up on the way
        t0 = time.perf_counter()
        try:
            r = await http.request(case.method, path, route=route, expect=tuple(range(400, 500)), **kw)
        except Exception as e:  # noqa: BLE001  transport error: recorded 599 by Http
            return 599, "", "", f"{type(e).__name__}", (time.perf_counter() - t0) * 1000
        return (r.status_code, r.headers.get("content-type", ""), r.text, r.headers.get("www-authenticate", ""),
                (time.perf_counter() - t0) * 1000)

    def judge(self, case: mc.Case, status: int, ctype: str, text: str, www: str, ms: float, *, keep=True) -> dict:
        on_mcp = case.path == mc.MCP
        parsed = mc.parse(text) if "json" in ctype else None
        rid = None if case.unread else mc.request_id(case.body)
        err = parsed.get("error") if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict) else {}
        is_err, tstatus, tdetail = mc.tool_outcome(parsed)
        row = {"name": case.name, "group": case.group, "who": case.who,
               "request": {"method": case.method, "path": case.path,
                           "headers": mc.redact(self.headers(case.who, case.headers, case.xff), self.secrets),
                           "body": mc.redact(mc.short_body(case.body), self.secrets)},
               "status": status, "rpc_code": err.get("code"), "rpc_message": mc.short_body(err.get("message")),
               "is_error": is_err, "tool_status": tstatus,
               "tool_detail": mc.redact(mc.short_body(tdetail), self.secrets), "ms": round(ms, 1),
               "text": None if parsed is not None else mc.redact(text[:300], self.secrets), "bug": case.bug or None}
        res = parsed.get("result") if isinstance(parsed, dict) else None
        sc = res.get("structuredContent") if isinstance(res, dict) else None
        row["open_url"] = isinstance(sc, dict) and "open_url" in sc
        row["checks"] = list(case.checks)
        problems = mc.expect_problems(case, status, parsed)
        row["problems"] = problems
        tag = f"{case.name}: "
        if status >= 500:
            self.fail(C_5XX, f"{tag}HTTP {status} {text[:120]!r}")
        if on_mcp and (why := mc.wellformed(status, ctype, text, rid, www_auth=www)):
            self.fail(C_WELLFORMED, tag + why)
        # Plain errors: an rpc message, a tool error, a plain 4xx body.
        err_text = " ".join(str(x) for x in (err.get("message"), tdetail) if x) or (text if status >= 400 else "")
        auth = self.hdrs.get(case.who, {}).get("Authorization", "")
        secrets = case.secrets + ((auth[7:],) if auth[:7].lower() == "bearer " and len(auth) > 11 else ())
        if err_text and (bad := mc.leaks(err_text, secrets)):
            self.fail(C_PLAIN, f"{tag}{bad}")
        # Cross-Agency: sentinels of the other side in anything answered.
        other = self.a_sent if case.who == "b" else self.b_sent
        if hits := mc.sentinel_hits(text, other):
            self.fail(C_CROSS, f"{tag}holds {hits}")
        names = mc.tool_names(parsed)
        if status == 200 and isinstance(res, dict) and isinstance(res.get("tools"), list):
            self.lists[case.who].append(names)
        if problems:
            for c in case.checks or (C_AS_SPECIFIED,):
                self.fail(c, tag + "; ".join(problems))
        if keep:
            self.rows.append(row)
        return {"row": row, "parsed": parsed}

    async def run(self, case: mc.Case) -> dict:
        status, ctype, text, www, ms = await self.send(self.http, case, f"mcp-wild {case.group}")
        return self.judge(case, status, ctype, text, www, ms)


def _find(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            if (x := _find(v, key)) is not None:
                return x
    if isinstance(obj, list):
        for v in obj:
            if (x := _find(v, key)) is not None:
                return x
    return None


def _sc(out: dict):
    p = out["parsed"]
    return p.get("result", {}).get("structuredContent") if isinstance(p, dict) else None


async def _mint(http: Http, name: str) -> tuple[str, str]:
    r = await http.post("/admin/owner-tokens", json={"name": name, "days": 30})
    r.raise_for_status()
    return r.json()["id"], r.json()["token"]


def _cookie(http: Http) -> str:
    return "; ".join(f"{k}={v}" for k, v in http.c.cookies.items())


def _b_snapshot(w, uid: str, aid: str) -> str:
    con = w.sql()
    try:
        snap = {name: [list(r) for r in con.execute(q, (uid if k == "uid" else aid,)).fetchall()]
                for name, q, k in B_TABLES}
    finally:
        con.close()
    return hashlib.sha256(json.dumps(snap, default=str, sort_keys=True).encode()).hexdigest()


def _sql_one(w, q: str, args=()) -> list:
    con = w.sql()
    try:
        return con.execute(q, args).fetchall()
    finally:
        con.close()


async def _agency_b(ctx, w, wild: Wild) -> dict:
    """Agency B: register, one Creator with sentinels, a bio page + link, a sales row, its token."""
    http = Http(ctx.relay, ctx.rec)
    uname = f"{w.user_prefix}{w.seed}mcpb"
    uid = await agency._register(http, uname)
    aid = 450_000_000 + w.seed % 1_000_000
    s = f"bwild{w.seed}"
    con = w.sql()
    with con:
        c = creator_seed._add(w, con, 2000, aid, uid)
        con.execute("UPDATE accounts SET nickname=? WHERE id=?", (f"{s}nick", c["id"]))
        con.execute("INSERT INTO bio_profiles(id, owner_user_id, account_id, username, display_name, bio, avatar, "
                    "mode, verified, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    ("bpmcpwild000001", uid, c["id"], f"{s}page", f"{s.upper()}DISPLAY", f"{s} bio", "", "direct",
                     0, ts(w.now), ts(w.now)))
        con.execute("INSERT INTO bio_links(id, profile_id, link_id, title, destination, default_tracking_code, mode, "
                    "geo, is_adult, tracking, sort_order) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    ("blmcpwild000001", "bpmcpwild000001", "kmcpwild0001", f"{s} link",
                     f"https://dest.slop.test/{s}dest", "", "direct", None, 0, 0, 0.0))
        con.execute("INSERT INTO transactions(account_id, fan_id, kind, amount_cents, currency, occurred_at, "
                    "ingested_at, provider_transaction_id, status, net_cents, fee_cents, vat_cents, source) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (c["id"], "slopbfan1", "tip", SENTINEL_CENTS, "USD", ts(w.now), ts(w.now), f"slop-mcpb-{w.seed}",
                     "pending", SENTINEL_CENTS, 0, 0, "ledger"))
    con.close()
    meta = w.sessions / "accounts" / c["id"] / "meta.json"
    m = json.loads(meta.read_text())
    meta.write_text(json.dumps({**m, "nickname": f"{s}nick", "name": f"{s}nick B"}))
    tid, tok = await _mint(http, "slop mcp-wild B")
    wild.secrets[tok] = "token:b"
    wild.hdrs["b"] = {"Authorization": f"Bearer {tok}"}
    wild.hdrs["cookie_b_plus_a"] = {"Cookie": _cookie(http)}
    wild.b_sent = (f"{s}nick", f"{s.upper()}DISPLAY", f"{s}page", f"{s}dest", f"{s} link", str(SENTINEL_CENTS),
                   f"{SENTINEL_CENTS / 100:.2f}", f"{SENTINEL_CENTS / 100:,.2f}", uname)
    return {"http": http, "uid": uid, "aid": c["id"], "user": uname, "pid": "bpmcpwild000001",
            "lid": "blmcpwild000001", "token_id": tid}


async def _two_factor_owner(ctx, w) -> dict:
    http = Http(ctx.relay, ctx.rec)
    try:
        uname = f"{w.user_prefix}{w.seed}mcptf"
        await agency._register(http, uname)
    finally:
        await http.aclose()
    secret = base64.b32encode(bytes(w.rng("mcp-wild-2fa").getrandbits(8) for _ in range(20))).decode()
    con = w.sql()
    with con:
        con.execute("UPDATE users SET totp_secret=?, totp_enabled_at=? WHERE username=?", (secret, ts(w.now), uname))
    con.close()
    return {"user": uname, "password": agency.PASSWORD, "secret": secret}


async def _mix(ctx, wild: Wild, ids: dict, clients: int, seconds: float) -> dict:
    table = mc.mix_table(ids)
    weights = [x[0] for x in table]
    lat: dict[str, list[float]] = defaultdict(list)
    hist: Counter = Counter()
    probs: Counter = Counter()
    sample: list[str] = []
    stop = time.monotonic() + seconds

    async def client(k: int) -> None:
        rng = ctx.world.rng(f"mcp-wild-mix-{k}")
        http = Http(ctx.relay, ctx.rec, limits=2)
        try:
            while time.monotonic() < stop:
                _, name, who, body = rng.choices(table, weights)[0]
                case = mc.Case(name, "mix", who=who, body=body, status=_MIX_STATUS[name][0], code=_MIX_STATUS[name][1],
                               tool=_MIX_STATUS[name][2], checks=_MIX_STATUS[name][3], unread=name in _MIX_UNREAD)
                status, ctype, text, www, ms = await wild.send(http, case, f"mcp-wild mix {name}")
                out = wild.judge(case, status, ctype, text, www, ms, keep=False)
                lat[name].append(ms)
                lat["*"].append(ms)
                hist[str(status)] += 1
                if out["row"]["problems"]:
                    probs[name] += 1
                    if len(sample) < 20:
                        sample.append(f"{name}: {out['row']['problems']}")
        finally:
            await http.aclose()

    t0 = time.monotonic()
    await asyncio.gather(*(client(k) for k in range(clients)))
    wall = time.monotonic() - t0
    return {"clients": clients, "seconds": round(wall, 1), "calls": len(lat["*"]),
            "rps": round(len(lat["*"]) / wall, 1) if wall else None,
            "p50_ms": mc.pct(lat["*"], 0.5), "p95_ms": mc.pct(lat["*"], 0.95),
            "per_pick": {k: {"n": len(v), "p50_ms": mc.pct(v, 0.5), "p95_ms": mc.pct(v, 0.95)}
                         for k, v in sorted(lat.items()) if k != "*"},
            "status_histogram": dict(sorted(hist.items())), "problems": dict(probs), "problem_sample": sample}


# Each mix pick's expectation: (statuses, rpc code, tool outcome, checks fed).
_MIX_STATUS = {
    "v_list_a": ((200,), None, None, (C_SEND_LISTED,)), "v_list_b": ((200,), None, None, (C_SEND_LISTED,)),
    "v_list_anon": ((200,), None, None, (C_ANON3,)), "v_ping": ((200,), None, None, ()),
    "v_creators_a": ((200,), None, "ok", ()), "v_creators_b": ((200,), None, "ok", ()),
    "v_bio_list_a": ((200,), None, "ok", ()), "v_bio_other": ((200,), None, (403, 404), (C_CROSS,)),
    "v_vault_other": ((200,), None, (403, 404), (C_CROSS,)), "v_vault_own": ((200,), None, "ok", ()),
    "v_kinds": ((200,), None, "ok", ()), "v_catalogue": ((200,), None, "ok", ()),
    "v_status_other": ((200,), None, 404, (C_CROSS,)), "v_send_tool": ((200,), -32602, None, (C_NO_SEND,)),
    "v_garbage": ((400,), -32700, None, ()), "v_batch": ((400,), -32600, None, ()),
    "v_unknown_method": ((200,), -32601, None, ()), "v_revoked": ((401,), None, None, (C_REVOKED,)),
    "v_cookie": ((401,), -32001, None, (C_COOKIE,)), "v_anon_data": ((200,), None, 401, (C_ANON3,)),
    "v_bad_args": ((200,), None, 422, ()), "v_notification": ((202,), None, None, ()),
}
_MIX_UNREAD = frozenset({"v_cookie"})   # refused on its Cookie before the body is read: id null


async def run(ctx):
    w = await ctx.build(PROFILE)
    wild = Wild(ctx)
    a_creators = w.data["creators"]
    a_aid = a_creators[0]["id"]

    # ── identities ──
    b = await _agency_b(ctx, w, wild)
    of_sessions.seed(w, a_creators + [{"id": b["aid"]}])
    _, tok_a = await _mint(ctx.owner, "slop mcp-wild A")
    rid, tok_rev = await _mint(ctx.owner, "slop mcp-wild A revoked")
    r = await ctx.owner.request("DELETE", f"/admin/owner-tokens/{rid}")
    ctx.check("setup: the to-revoke token is revoked (DELETE /admin/owner-tokens/{id})", r.status_code in (200, 204),
              http_status=r.status_code)   # not `status`: that key is the check's own pass/fail (report.py)
    wild.query_token = tok_a
    for v, lab in ((tok_a, "token:a"), (tok_rev, "token:a_revoked")):
        wild.secrets[v] = lab
    emp_name = f"{w.user_prefix}{w.seed}mcpemp"
    emp = (await chatters.seed(w, ctx.owner, w.user_id, [emp_name], account_ids=[[a_aid]]))[0]
    emp_http = Http(ctx.relay, ctx.rec)
    r = await emp_http.post("/chatter/login", json={"username": emp_name, "password": emp["password"]})
    r.raise_for_status()
    tf = await _two_factor_owner(ctx, w)
    a_user = w.data["agency"]["username"]
    wild.hdrs.update({
        "anon": {}, "a": {"Authorization": f"Bearer {tok_a}"}, "a_revoked": {"Authorization": f"Bearer {tok_rev}"},
        "a_query": {}, "a_lower": {"Authorization": f"bearer {tok_a}"},
        "a_emp_hdr": {"Authorization": f"Bearer {tok_a}", "X-Employee-Id": "1"},
        "cookie_a": {"Cookie": _cookie(ctx.owner)}, "employee": {"Cookie": _cookie(emp_http)},
        "garbage": {"Authorization": "Bearer ifw_slopgarbage0000000000000000"}, "bare_ifw": {"Authorization": "Bearer ifw_"},
        "basic": {"Authorization": "Basic " + base64.b64encode(b"slop:slop").decode()},
        "bearer_empty": {"Authorization": "Bearer"},   # h11 refuses "Bearer " (trailing OWS is no header value)
    })
    wild.hdrs["cookie_b_plus_a"] = {**wild.hdrs["cookie_b_plus_a"], "Authorization": f"Bearer {tok_a}"}
    for k in ("cookie_a", "employee", "cookie_b_plus_a"):
        wild.secrets[wild.hdrs[k]["Cookie"]] = f"cookie:{k}"
    for v, lab in ((agency.PASSWORD, "password"), (emp["password"], "password"), (tf["secret"], "totp_secret")):
        wild.secrets[v] = lab
    wild.a_sent = tuple(c["id"] for c in a_creators) + (a_user,)

    ids = {"a_aid": a_aid, "b_aid": b["aid"], "b_pid": b["pid"], "b_lid": b["lid"], "b_user": b["uid"],
           "a_user": a_user, "a_password": agency.PASSWORD, "new_user": f"{w.user_prefix}{w.seed}mcpnew",
           "emp_user": emp_name, "emp_password": emp["password"], "tf_user": tf["user"], "tf_password": tf["password"],
           "squat": f"slopsquat{w.seed % 100000}", "tf_bad_code": "", "a_plan": None, "b_plan": None, "a_file": None, "b_file": None}

    # B's plan and report file, through B's own token (positive controls; the plan is never OK'd).
    out = await wild.run(mc.Case("setup_b_plan", "setup", who="b", body=mc.call("propose_plan", {
        "summary": "slop mcp-wild B plan", "steps": [mc.mass_step(b["aid"])]}), tool="ok"))
    ids["b_plan"] = _find(_sc(out), "plan_id") or "e" * 32
    out = await wild.run(mc.Case("setup_b_file", "setup", who="b", body=mc.call("report_file", {
        "recipe": {"dataset": "sales", "window": {"preset": "last_7_days"}}}), tool="ok"))
    ids["b_file"] = urlsplit(str(_find(_sc(out), "download_url") or "/admin/reports/files/" + "d" * 32)).path

    b_before = _b_snapshot(w, b["uid"], b["aid"])
    rules_before = _sql_one(w, "SELECT COUNT(*) FROM automation_rules")[0][0]

    # ── the table ──
    for case in mc.protocol_cases() + mc.auth_cases(ids) + mc.args_cases(ids):
        await wild.run(case)
    out = await wild.run(mc.Case("ar_report_file_ok", "args", who="a", body=mc.call("report_file", {
        "recipe": {"dataset": "sales", "window": {"preset": "last_7_days"}}, "format": "csv"}), tool="ok",
        checks=(C_REPORT_FILE,)))
    ids["a_file"] = urlsplit(str(_find(_sc(out), "download_url") or "/admin/reports/files/" + "c" * 32)).path
    for case in mc.plan_cases(ids):
        out = await wild.run(case)
        if case.name == "pl_good":
            ids["a_plan"] = _find(_sc(out), "plan_id") or "b" * 32
    for case in mc.plan_followups(ids) + mc.scope_cases(ids) + mc.report_file_cases(ids):
        await wild.run(case)
    ids["tf_bad_code"] = mc.bad_code(tf["secret"], int(time.time() // 30))   # off now ± BAD_TOTP_SPREAD steps
    for case in mc.signup_cases(ids):
        await wild.run(case)
    burst = [await wild.run(c) for c in mc.login_burst(ids)]
    ctx.metric("login_burst", {"tool_status": [x["row"]["tool_status"] for x in burst]})
    ids["tf_code"] = mc.totp(tf["secret"], int(time.time() // 30))
    await wild.run(mc.two_factor_followup(ids))

    # ── volume ──
    clients, seconds = MIX.get(ctx.scale, MIX["small"])
    clients, seconds = ctx.param("clients", clients), ctx.param("seconds", seconds)
    mix = await _mix(ctx, wild, ids, clients, seconds)
    ctx.metric("mix", {k: mix[k] for k in ("clients", "seconds", "calls", "rps", "p50_ms", "p95_ms",
                                            "status_histogram")})

    # ── end state ──
    fake = ctx.of_wire
    with fake.lock:
        send_calls = [c for c in fake.calls if c.get("route") in SEND_ROUTES]
        held = {k: sum(len(v) for v in getattr(fake, k).values()) for k in ("sends", "queue", "posts", "unsends")}
        b_wire = [c for c in fake.calls if str(c.get("account")) == b["aid"]]
    rules_after = _sql_one(w, "SELECT COUNT(*) FROM automation_rules")[0][0]
    plans = _sql_one(w, "SELECT id, owner_user_id, status FROM ultra_plans")
    b_after = _b_snapshot(w, b["uid"], b["aid"])
    squat = _sql_one(w, "SELECT id, owner_user_id FROM bio_profiles WHERE account_id=? AND owner_user_id<>?",
                     (b["aid"], b["uid"]))
    if send_calls or any(held.values()) or rules_after != rules_before:
        wild.fail(C_NO_SEND, f"wire sends {len(send_calls)}, held {held}, rules {rules_before}->{rules_after}")
    if bad := [p for p in plans if p[2] in ("running", "done", "needs_you")]:
        wild.fail(C_NO_SEND, f"plans past their OK: {bad}")
    if b_after != b_before:
        wild.fail(C_CROSS, "Agency B's rows changed")
    if squat:
        wild.fail(C_CROSS, f"bio page on B's Creator owned by another user: {squat}")
    if b_wire:
        wild.fail(C_CROSS, f"fake OF saw {len(b_wire)} calls for B's Creator: {[c.get('route') for c in b_wire[:5]]}")
    ours = {ids["a_plan"], ids["b_plan"]}
    if stuck := [p for p in plans if p[2] in ("planning", "running")]:
        wild.fail(C_STUCK, f"stuck plans {stuck}")
    if not_waiting := [p for p in plans if p[0] in ours and p[2] != "awaiting_ok"]:
        wild.fail(C_STUCK, f"this run's plans not awaiting_ok: {not_waiting}")
    # tools/list sets per identity.
    for who in ("a", "b"):
        for names in wild.lists.get(who, []):
            if names & set(mc.SEND_TOOLS) or not mc.TOKEN_BUILTINS <= names:
                wild.fail(C_SEND_LISTED, f"{who} tools/list {sorted(names)}")
                break
    for who in ("anon", "a_query"):
        for names in wild.lists.get(who, []):
            if names != mc.ANON_TOOLS:
                wild.fail(C_ANON3, f"{who} tools/list {sorted(names)}")
                break
    for who, c in (("a", C_SEND_LISTED), ("b", C_SEND_LISTED), ("anon", C_ANON3)):
        if not wild.lists.get(who):
            wild.fail(c, f"no tools/list answer for {who}")
    for row in wild.rows:   # anon data-tool refusals carry the connect link
        if row["who"] in ("anon", "a_query") and row["tool_status"] == 401 and not row["open_url"]:
            wild.fail(C_ANON3, f"{row['name']}: 401 without open_url")

    by_check = {c: [r["name"] for r in wild.rows if c in r["checks"]] for c in
                (C_ORIGIN, C_COOKIE, C_SCOPE, C_EMPLOYEE, C_REPORT_FILE, C_REVOKED)}
    for c, names in by_check.items():   # a check with no case behind it is no proof
        if not names:
            wild.fail(c, "no case ran")
    for c, extra in ((C_5XX, {"cases": len(wild.rows), "mix_calls": mix["calls"]}),
                     (C_WELLFORMED, {}), (C_NO_SEND, {"wire_sends": len(send_calls), "held": held,
                                                       "rules": [rules_before, rules_after]}),
                     (C_CROSS, {"b_rows_same": b_after == b_before}), (C_SEND_LISTED, {}), (C_ANON3, {}),
                     (C_REVOKED, {}), (C_ORIGIN, {}), (C_COOKIE, {}), (C_SCOPE, {}), (C_EMPLOYEE, {}), (C_PLAIN, {}),
                     (C_REPORT_FILE, {}), (C_STUCK, {"plans": [list(p) for p in plans]}), (C_AS_SPECIFIED, {})):
        ctx.check(c, not wild.fails.get(c), failures=wild.fails.get(c, []), **extra)

    (ctx.out / "mcp-wild.json").write_text(json.dumps(
        {"ids": mc.redact({k: v for k, v in ids.items() if k not in ("a_password", "emp_password", "tf_password")},
                          wild.secrets),
         "cases": wild.rows, "mix": mix, "failures": wild.fails,
         "suspected_bugs": sorted({r["bug"] for r in wild.rows if r["bug"]})},
        indent=2, ensure_ascii=False, default=str), errors="backslashreplace")   # lone surrogates echoed back
    for h in (wild.http, b["http"], emp_http):
        await h.aclose()

