from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import types
from unittest.mock import patch

from curl_cffi import requests as curl
from curl_cffi.const import CurlECode
from fastapi import HTTPException

import _harness
from _send_kill import Killed

AID = "900539700124344777"
_fans = iter(range(72001, 73000))
_ids = iter(range(9_900_000_000_001, 9_999_000_000_000))
SYNC_URL = f"sqlite:///{_harness.DB_PATH}"


class Resp:
    def __init__(self, status: int, body=None, url: str = "", headers: dict | None = None):
        self.status_code, self.ok, self.url = status, 200 <= status < 300, url
        self._body, self.headers = body, headers or {}
        self.text = "" if body is None else json.dumps(body)

    def json(self):
        return self._body


class FakeHttp:
    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls: list[tuple] = []
        self.accepts: list[dict] = []

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.calls.append((method, url.split("/api2/v2")[-1], json))
        step = self.steps.pop(0) if self.steps else accept
        return step(self, url, json or {})

    def get(self, url, headers=None, timeout=None):
        return Resp(200, {}, url)


def accept(fake: FakeHttp, url: str, body: dict) -> Resp:
    msg = {"id": next(_ids), "text": body.get("text", ""), "createdAt": "2026-11-26T10:00:00+00:00",
           "fromUser": {"id": int(AID)}, "media": [], "price": 0}
    fake.accepts.append(msg)
    return Resp(200, msg, url)


def status(code: int, headers: dict | None = None):
    return lambda fake, url, body: Resp(code, {"error": {"code": code, "message": "no"}}, url, headers)


def raises(exc: BaseException):
    def step(fake, url, body):
        raise exc
    return step


def client(http: FakeHttp):
    from of_client import OFClient
    c = OFClient({"headers": {"user_id": AID, "x_bc": "bc", "x_of_rev": "rev", "user_agent": "ua"},
                  "signing": {"rules": {"static_param": "s", "start": "1", "end": "2", "checksum_indexes": [1],
                                        "checksum_constant": 1}}, "cookies": []})
    c._x_hash = "h"
    c.http = http
    return c


@contextlib.contextmanager
def cells(on: bool = True, accounts: str = f"onlyfans:{AID}", epoch: str = "1"):
    import server
    keys = ("OI_CELL_MAP", "OI_ACCOUNTS", "OI_EPOCH")
    saved = {k: os.environ.pop(k, None) for k in keys}
    if on:
        os.environ.update(OI_CELL_MAP="/nonexistent/placement.json", OI_ACCOUNTS=accounts, OI_EPOCH=epoch)
    try:
        with patch.object(server, "_CELLS", on):
            yield
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


async def post(http: FakeHttp, fan: int, op: str | None, text: str = "hi from the composer"):
    import server
    req = types.SimpleNamespace(method="POST", query_params={}, state=types.SimpleNamespace(),
                                headers={"x-account-id": AID, **({"x-op-id": op} if op else {})})
    tok = server._request_ctx.set(req)
    try:
        with patch.object(server, "_load_client", return_value=client(http)):
            return 200, await server.send_message(req, fan, server.SendMessageBody(text=text))
    except HTTPException as e:
        return e.status_code, e.detail
    finally:
        server._request_ctx.reset(tok)


def op_of(fan: int, anchor: str) -> str:
    import send_ops
    return send_ops.op_id("onlyfans", AID, "composer", str(fan), anchor)


def row(fan: int, anchor: str):
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c:
        try:
            r = c.execute("SELECT state, attempts, upstream_id, result FROM send_ops WHERE account=? AND op_id=?",
                          (AID, op_of(fan, anchor))).fetchone()
        except sqlite3.OperationalError:
            return None
    return None if r is None else {"state": r[0], "attempts": r[1], "upstream_id": r[2],
                                   "result": json.loads(r[3]) if r[3] else None}


def messages(fan: int) -> int:
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c:
        return c.execute("SELECT COUNT(*) FROM messages WHERE account_id=? AND fan_id=?", (AID, fan)).fetchone()[0]


def has_table() -> bool:
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c:
        return c.execute("SELECT 1 FROM sqlite_master WHERE name='send_ops'").fetchone() is not None


def restart() -> int:
    import send_ops
    import sends_inflight
    with sends_inflight._lock:
        sends_inflight._open.clear()
    return send_ops.install(SYNC_URL)


def err(body) -> str | None:
    return body.get("error") if isinstance(body, dict) else None


def unknown_proxy() -> curl.exceptions.ProxyError:
    return curl.exceptions.ProxyError("Proxy CONNECT aborted", CurlECode.RECV_ERROR)


Check = tuple[str, bool, dict]


async def env_unset() -> list[Check]:
    fan = next(_fans)
    with cells(on=False):
        plain, tagged = FakeHttp(), FakeHttp()
        s1, _ = await post(plain, fan, None)
        s2, _ = await post(tagged, fan, "op-env")
    same = [c[:2] for c in plain.calls] == [c[:2] for c in tagged.calls] == [("POST", f"/chats/{fan}/messages")]
    return [("env unset: X-Op-Id changes no wire call (1 POST each, same as main)", s1 == s2 == 200 and same,
             {"plain": plain.calls, "tagged": tagged.calls}),
            ("env unset: no send_ops table", not has_table(), {})]


async def boundary() -> list[Check]:
    import platforms
    import send_ops
    out: list[Check] = []

    fan = next(_fans)
    http = FakeHttp()
    st, body = await post(http, fan, "clean")
    r = row(fan, "clean")
    out.append(("clean composer send = 1 accept + 1 sent row", st == 200 and len(http.accepts) == 1
                and len(http.calls) == 1 and r is not None and r["state"] == "sent" and r["attempts"] == 1
                and r["upstream_id"] == str(http.accepts[0]["id"]), {"status": st, "calls": http.calls, "row": r}))
    first, n_msgs = body, messages(fan)
    st, body = await post(http, fan, "clean")
    out.append(("same X-Op-Id resubmit returns the first body, 0 extra wire calls, no side-effect rows",
                st == 200 and body == first and len(http.calls) == 1 and messages(fan) == n_msgs
                and row(fan, "clean")["attempts"] == 1, {"status": st, "calls": len(http.calls), "body": body}))
    st, body = await post(http, fan, "clean", text="a different message")
    out.append(("same X-Op-Id, different body → op_conflict, 0 wire calls",
                st == 409 and err(body) == "op_conflict" and len(http.calls) == 1, {"status": st, "body": body}))

    fan = next(_fans)
    http = FakeHttp()
    st, body = await post(http, fan, None)
    out.append(("no X-Op-Id in Cell mode → unclaimed_send, 0 wire calls",
                st == 409 and err(body) == "unclaimed_send" and not http.calls and row(fan, "") is None,
                {"status": st, "body": body, "calls": http.calls}))

    fan = next(_fans)
    http = FakeHttp()
    with cells(accounts="onlyfans:1"):
        st, body = await post(http, fan, "foreign")
    with cells(epoch=""):
        st2, body2 = await post(http, fan, "foreign")
    out.append(("not_owner alone (account not owned / no Owner epoch) → 0 transport calls",
                (st, err(body), st2, err(body2)) == (409, "not_owner", 409, "not_owner") and not http.calls
                and row(fan, "foreign") is None, {"answers": [st, body, st2, body2], "calls": http.calls}))
    with patch.object(platforms, "refusal_for_account", lambda aid, name: "send_message is not on this platform"):
        st, body = await post(http, fan, "cap")
    out.append(("capability alone → 0 transport calls", st == 501 and err(body) == "capability" and not http.calls
                and row(fan, "cap") is None, {"status": st, "body": body}))
    with patch.object(send_ops, "_connect", side_effect=sqlite3.OperationalError("disk I/O error")):
        st, body = await post(http, fan, "nostore")
    out.append(("claim_failed alone (claim cannot be written) → 0 transport calls, no fallback",
                st == 503 and err(body) == "claim_failed" and not http.calls and row(fan, "nostore") is None,
                {"status": st, "body": body}))

    fan = next(_fans)
    http = FakeHttp()
    await post(http, fan, "order", text="first")
    base = len(http.calls)
    order = []
    cap = patch.object(platforms, "refusal_for_account", lambda aid, name: "lacks")
    store = patch.object(send_ops, "_connect", side_effect=sqlite3.OperationalError("locked"))
    for gates in (("owner", "cap", "store"), ("cap", "store"), ("store",), ()):
        with contextlib.ExitStack() as stack:
            stack.enter_context(cells(accounts="onlyfans:1" if "owner" in gates else f"onlyfans:{AID}"))
            if "cap" in gates:
                stack.enter_context(cap)
            if "store" in gates:
                stack.enter_context(store)
            order.append(err((await post(http, fan, "order", text="second"))[1]))
    out.append(("gate order: not_owner → capability → claim → op_conflict, 0 transport calls",
                order == ["not_owner", "capability", "claim_failed", "op_conflict"] and len(http.calls) == base,
                {"order": order, "extra_calls": len(http.calls) - base}))

    fan = next(_fans)
    http = FakeHttp(status(400))
    st, body = await post(http, fan, "refused")
    r1 = row(fan, "refused")
    st2, _ = await post(http, fan, "refused")
    out.append(("full OF 4xx → refused; same-op resubmit re-claims and sends once",
                st == 502 and r1 and r1["state"] == "refused" and st2 == 200 and len(http.accepts) == 1
                and row(fan, "refused")["state"] == "sent", {"first": [st, body], "row": r1, "resubmit": st2}))

    fan = next(_fans)
    http = FakeHttp(status(429, {"Retry-After": "0"}))
    st, _ = await post(http, fan, "paced")
    out.append(("429 pacing shares the budget: full 4xx then 1 more attempt, 1 accept",
                st == 200 and len(http.calls) == 2 and len(http.accepts) == 1 and row(fan, "paced")["attempts"] == 2,
                {"status": st, "calls": len(http.calls)}))

    fan = next(_fans)
    http = FakeHttp(raises(curl.exceptions.ProxyError("CONNECT tunnel failed, response 403", CurlECode.RECV_ERROR)))
    st, _ = await post(http, fan, "tunnel")
    out.append(("proxy refused CONNECT before any tunnel → second attempt allowed, 1 accept",
                st == 200 and len(http.calls) == 2 and len(http.accepts) == 1, {"status": st, "calls": len(http.calls)}))

    fan = next(_fans)
    http = FakeHttp(raises(unknown_proxy()), raises(unknown_proxy()), raises(unknown_proxy()),
                    raises(unknown_proxy()), raises(unknown_proxy()))
    st, body = await post(http, fan, "unknown")
    r = row(fan, "unknown")
    out.append(("unknown error under _proxy_retry = 1 attempt, then uncertain",
                len(http.calls) == 1 and r is not None and r["state"] == "uncertain" and r["attempts"] == 1
                and isinstance(body, dict) and body.get("op_state") == "uncertain",
                {"status": st, "calls": len(http.calls), "row": r, "body": body}))

    fan = next(_fans)
    http = FakeHttp(raises(curl.exceptions.Timeout("Operation timed out after 30000 ms", CurlECode.OPERATION_TIMEDOUT)))
    st, body = await post(http, fan, "timeout")
    r = row(fan, "timeout")
    st2, body2 = await post(http, fan, "timeout")
    out.append(("unknown outcome (timeout) → uncertain; same-op resubmit → op_uncertain, 0 extra wire calls",
                r is not None and r["state"] == "uncertain" and (st2, err(body2)) == (409, "op_uncertain")
                and len(http.calls) == 1, {"first": [st, body], "row": r, "resubmit": [st2, body2],
                                           "calls": len(http.calls)}))

    from of_client import OFClient, OFDispatchRefused, proxy_refused
    fan = next(_fans)
    http = FakeHttp()
    with patch.object(OFClient, "prepare_message", side_effect=RuntimeError("boom")):
        st, body = await post(http, fan, "noproof")
    with patch.object(OFClient, "post_message", side_effect=OFDispatchRefused("window expired")):
        st2, _ = await post(http, fan, "known")
    out.append(("no wire attempt without a known pre-wire refusal → uncertain; a known refusal → refused",
                not http.calls and row(fan, "noproof")["state"] == "uncertain" and row(fan, "known")["state"] == "refused",
                {"noproof": [st, body, row(fan, "noproof")], "known": [st2, row(fan, "known")]}))
    import proxies
    fan = next(_fans)
    http = FakeHttp()
    with patch.object(proxies, "CELLS", True):
        try:
            got = await post(http, fan, "noproxy")
        except proxies.NoProxyRefused as e:
            got = e
    out.append(("Creator with no proxy in a Cell → NoProxyRefused, 0 wire calls, claim refused",
                isinstance(got, proxies.NoProxyRefused) and not http.calls
                and row(fan, "noproxy")["state"] == "refused", {"got": repr(got), "row": row(fan, "noproxy")}))
    out.append(("Cell mode proxy_refused accepts only a refusal before any tunnel",
                not proxy_refused(unknown_proxy()) and proxy_refused(curl.exceptions.ProxyError(
                    "CONNECT tunnel failed, response 407", CurlECode.RECV_ERROR)), {}))

    fan = next(_fans)
    http = FakeHttp(status(500))
    st, body = await post(http, fan, "5xx")
    out.append(("OF 5xx → uncertain, 1 attempt", len(http.calls) == 1 and row(fan, "5xx")["state"] == "uncertain",
                {"status": st, "body": body}))

    fan = next(_fans)
    http = FakeHttp()
    real_finish = send_ops._finish

    def broken_mark(account, op, state, budget, result=None):
        if state == "sent":
            with patch.object(send_ops, "_connect", side_effect=sqlite3.OperationalError("database is locked")):
                return real_finish(account, op, state, budget, result)
        return real_finish(account, op, state, budget, result)
    with patch.object(send_ops, "_finish", broken_mark):
        st, body = await post(http, fan, "nomark")
    st2, body2 = await post(http, fan, "nomark")
    out.append(("mark-sent write fails after an accept → route answers the result; resubmit op_pending, 0 wire",
                st == 200 and isinstance(body, dict) and body.get("id") == http.accepts[0]["id"]
                and (st2, err(body2)) == (409, "op_pending") and len(http.calls) == 1,
                {"first": [st, body], "resubmit": [st2, body2]}))

    return out


async def kill(point: str) -> list[Check]:
    import server
    fan, anchor = next(_fans), f"kill-{point}"
    at_kill: dict = {}

    def die_before(fake, url, body):
        at_kill["row"] = row(fan, anchor)
        raise Killed()

    def die_after_accept(fake, url, body):
        accept(fake, url, body)
        at_kill["row"] = row(fan, anchor)
        raise Killed()

    async def die_after_update(*_a, **_k):
        at_kill["row"] = row(fan, anchor)
        raise Killed()

    http = FakeHttp({"after_claim": die_before, "accepted": die_after_accept, "after_update": accept}[point])
    killed = False
    with patch.object(server, "_record_fan_send", die_after_update) if point == "after_update" \
            else contextlib.nullcontext():
        try:
            await post(http, fan, anchor)
        except Killed:
            killed = True
    want_at_kill = "sent" if point == "after_update" else "claimed"
    reached = killed and (at_kill.get("row") or {}).get("state") == want_at_kill
    out: list[Check] = [(f"kill {point}: kill point reached (claim row {want_at_kill} at the kill)", reached,
                         {"killed": killed, "row": at_kill.get("row")})]
    if point == "after_claim":
        before = len(http.calls)
        st, body = await post(http, fan, anchor)
        out.append(("kill after_claim: resubmit before restart → op_pending, 0 wire calls",
                    (st, err(body)) == (409, "op_pending") and len(http.calls) == before and not http.accepts,
                    {"answer": [st, body], "calls": http.calls}))
    restart()
    after = row(fan, anchor)
    again = FakeHttp()
    st, body = await post(again, fan, anchor)
    accepts = len(http.accepts) + len(again.accepts)
    if point == "after_update":
        ok = (after or {}).get("state") == "sent" and st == 200 and body == http.accepts[0] and not again.calls
        want = "replays the first body"
    else:
        ok = (after or {}).get("state") == "uncertain" and (st, err(body)) == (409, "op_uncertain") \
            and not again.calls
        want = "open claim is uncertain, never resent"
    out.append((f"kill {point}: after restart {want}; ≤1 accept for the op", ok and accepts <= 1,
                {"row_after_restart": after, "resubmit": [st, body], "accepts": accepts,
                 "resubmit_calls": again.calls}))
    return out


def _late_claim():
    import send_ops
    real_claim, real_finish = send_ops._claim, send_ops._finish
    pending: dict = {}

    def late_claim(account, op, kind, target, dig, epoch):
        pending[(account, op)] = (kind, target, dig, epoch)
        return None

    def late_finish(account, op, state, budget, result=None):
        if (args := pending.pop((account, op), None)) is not None:
            real_claim(account, op, *args)
        real_finish(account, op, state, budget, result)
    return _patches((send_ops, "_claim", late_claim), (send_ops, "_finish", late_finish))


@contextlib.contextmanager
def _patches(*targets):
    with contextlib.ExitStack() as stack:
        for obj, name, new in targets:
            stack.enter_context(patch.object(obj, name, new))
        yield


def _mutant(name: str):
    import of_client
    import send_tripwire
    import unconfirmed_sends_api
    return {
        "tripwire_bypass": lambda: _patches((send_tripwire, "check", lambda method: None)),
        "claim_after_wire": _late_claim,
        "retry_unknown": lambda: _patches((of_client, "before_tunnel", lambda e: True)),
        "transport_retry": lambda: _patches((send_tripwire, "budget", lambda: None)),
        "retry_on": lambda: _patches((unconfirmed_sends_api, "_retry_allowed", lambda: True)),
    }[name]()


MUTANTS = {
    "tripwire_bypass": ("no X-Op-Id in Cell mode → unclaimed_send, 0 wire calls",),
    "claim_after_wire": ("kill after_claim: kill point reached (claim row claimed at the kill)",
                         "kill accepted: after restart open claim is uncertain, never resent; ≤1 accept for the op"),
    "retry_unknown": ("unknown outcome (timeout) → uncertain; same-op resubmit → op_uncertain, 0 extra wire calls",),
    "transport_retry": ("unknown error under _proxy_retry = 1 attempt, then uncertain",),
    "retry_on": ("/retry in Cell mode → 409 retry_off_cell_mode before any settle",),
}


async def run_all() -> list[Check]:
    await _seed()
    checks = await env_unset()
    restart()
    with cells():
        checks += await boundary()
        for point in ("after_claim", "accepted", "after_update"):
            checks += await kill(point)
        import _send_kill_held
        checks += await _send_kill_held.run()
    return checks


async def _seed() -> None:
    from db.engine import get_session
    from db.models import Account
    async with get_session() as s:
        if await s.get(Account, AID) is None:
            s.add(Account(id=AID, nickname=AID))


def report(checks: list[Check]) -> list[str]:
    for name, ok, seen in checks:
        print(f"[{'ok' if ok else 'FAIL'}] {name}" + ("" if ok else f"  {json.dumps(seen, default=str)[:700]}"))
    return [name for name, ok, _ in checks if not ok]


def run_mutant(name: str) -> int:
    import asyncio
    if name not in MUTANTS:
        print(f"--break {name}: no such mutant (have {', '.join(MUTANTS)})")
        return 2

    async def go():
        with _mutant(name):
            return await run_all()
    checks = asyncio.run(go())
    failed = report(checks)
    own = MUTANTS[name]
    if absent := [c for c in own if c not in {n for n, _, _ in checks}]:
        print(f"--break {name}: own checks never ran: {absent}")
        return 1
    green = [c for c in own if c not in failed]
    print(f"--break {name}: {len(own) - len(green)}/{len(own)} own checks red" + (f"; still green: {green}" if green else ""))
    return 0 if not green else 1
