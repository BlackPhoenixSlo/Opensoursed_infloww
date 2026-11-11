#!/usr/bin/env python3
"""service/tests/test_of_call_counter.py — the OF call counter (service/of_call_counter.py).

Every signed OF request `OFClient._http_call` sends lands in the counter, keyed by
(Caller kind, "METHOD folded-path", Creator, status class); a refused call never does.
The Relay persists the cumulative counts to a file beside the DB (`start`), and a
process that never calls `start` counts in memory only.

Seam 1: a bare OFClient (via __new__) with a recording fake `http`, driven through
get_json / request_json / request, read back through `of_call_counter.snapshot()`.
Each case uses its own Creator id, so cases never read each other's rows.
Seam 2: child processes (a restart is a new process with empty module state), as
test_priority_lane_accounting.py does.

Plain-assert script:  ./venv/bin/python service/tests/test_of_call_counter.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402

from curl_cffi import requests as curl_requests  # noqa: E402

import account_health  # noqa: E402
import of_call_counter  # noqa: E402
import of_client  # noqa: E402
import of_pacing  # noqa: E402
from of_client import API_BASE, OFClient, OFDeactivatedError, OFDeniedError  # noqa: E402
from _of_wire import fake_wire  # noqa: E402

SERVICE_ROOT = Path(__file__).resolve().parents[1]


class _Resp:
    def __init__(self, status: int, text: str = "{}"):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.text = text
        self.headers: dict = {}
        self.url = "https://onlyfans.com/x"

    def json(self):
        return json.loads(self.text or "null")


def _client(answers=None, account_id=None):
    """A bare OFClient whose transport answers from `answers` (a list of statuses or
    exceptions, consumed in order; then 200). Returns (client, sent)."""
    queue = list(answers or [])
    sent: list[tuple[str, str]] = []

    def _answer(method, url):
        sent.append((method, url))
        a = queue.pop(0) if queue else 200
        if isinstance(a, BaseException):
            raise a
        if isinstance(a, tuple):
            return _Resp(*a)
        return _Resp(a, "" if a == 204 else "{}")

    c = OFClient.__new__(OFClient)
    c.account_id = account_id or f"cc-{uuid.uuid4().hex[:8]}"
    c.user_id = "999"
    c.timeout_s = 5
    c._x_hash = "HASH"
    c.proxy_label = None
    c.proxy_url = None
    fake_wire(c, types.SimpleNamespace(get=lambda url, **_k: _answer("GET", url),
                                       request=lambda method, url, **_k: _answer(method, url)))
    c._signed_headers = lambda _url: {}
    return c, sent


def _rows(account_id: str) -> dict[tuple[str, str, str], int]:
    """(caller, path, status) -> count for one Creator, from the public snapshot."""
    out: dict[tuple[str, str, str], int] = {}
    for caller, path, aid, status, n in of_call_counter.snapshot()["rows"]:
        if aid == account_id:
            out[(caller, path, status)] = out.get((caller, path, status), 0) + n
    return out


def _by_path_status(account_id: str) -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = {}
    for (_caller, path, status), n in _rows(account_id).items():
        out[(path, status)] = out.get((path, status), 0) + n
    return out


def _swallow(fn, *a, **k):
    try:
        fn(*a, **k)
    except Exception:  # noqa: BLE001 — the case reads the counter, not the raise
        pass


# ── seam 1: the transport ───────────────────────────────────────────────────

def case_one_row_per_call_with_its_status_class():
    c, sent = _client([200, 204, 301, 302, 401, 403, (429, "Please allow 1 seconds"), 404, 500, 502, 503])
    for _ in range(11):
        _swallow(c.request, "GET", f"{API_BASE}/users/me")
    assert len(sent) == 11, sent
    got = _by_path_status(c.account_id)
    want = {("GET /api2/v2/users/me", "2xx"): 2, ("GET /api2/v2/users/me", "3xx"): 2,
            ("GET /api2/v2/users/me", "401"): 1, ("GET /api2/v2/users/me", "403"): 1,
            ("GET /api2/v2/users/me", "429"): 1, ("GET /api2/v2/users/me", "4xx"): 1,
            ("GET /api2/v2/users/me", "5xx"): 3}
    assert got == want, got


def case_every_public_entry_point_is_counted():
    """get_json never passes request_json (get -> _http_call): each entry point counts once."""
    c, sent = _client()
    c.get_json("/api2/v2/users/me")
    c.request_json("POST", "/api2/v2/messages/queue", json_body={"text": "x"})
    c.request("PATCH", "/api2/v2/users/me", json_body={"name": "x"})
    c.post_json("/api2/v2/lists", json_body={"name": "x"})
    assert len(sent) == 4, sent
    got = _by_path_status(c.account_id)
    assert got == {("GET /api2/v2/users/me", "2xx"): 1, ("POST /api2/v2/messages/queue", "2xx"): 1,
                   ("PATCH /api2/v2/users/me", "2xx"): 1, ("POST /api2/v2/lists", "2xx"): 1}, got


def case_path_key_folds_ids_and_usernames_and_drops_the_query():
    c, _ = _client()
    for method, path in [
        ("GET", "/api2/v2/chats/123456/messages?limit=10&id=999"),
        ("GET", "/api2/v2/chats/777/messages"),
        ("GET", "/api2/v2/vault/media/abcdef0123456789abcd"),
        ("GET", "/api2/v2/users/somefan_name"),
        ("GET", "/api2/v2/users/otherfan/posts?limit=5"),
        ("GET", "/api2/v2/users/me"),
        ("GET", "/api2/v2/users/list?a=1"),
        ("GET", "/api2/v2/users/notifications/count"),
        ("GET", "/api2/v2/users/performers"),
        ("PATCH", "/api2/v2/users/settings"),
        ("DELETE", "/api2/v2/lists/55/users/66"),
    ]:
        c.request(method, path)
    got = _by_path_status(c.account_id)
    want = {
        ("GET /api2/v2/chats/{}/messages", "2xx"): 2,
        ("GET /api2/v2/vault/media/{}", "2xx"): 1,
        ("GET /api2/v2/users/{}", "2xx"): 1,
        ("GET /api2/v2/users/{}/posts", "2xx"): 1,
        ("GET /api2/v2/users/me", "2xx"): 1,
        ("GET /api2/v2/users/list", "2xx"): 1,
        ("GET /api2/v2/users/notifications/count", "2xx"): 1,
        ("GET /api2/v2/users/performers", "2xx"): 1,
        ("PATCH /api2/v2/users/settings", "2xx"): 1,
        ("DELETE /api2/v2/lists/{}/users/{}", "2xx"): 1,
    }
    assert got == want, got


def case_a_refused_call_is_not_counted():
    c, sent = _client(account_id=f"cc-dead-{uuid.uuid4().hex[:6]}")
    try:
        c.request("POST", f"{API_BASE}/users/logout")
        raise AssertionError("logout went out")
    except OFDeniedError:
        pass
    before = account_health._writes_off
    account_health._writes_off = frozenset({c.account_id})
    try:
        try:
            c.request("POST", "/api2/v2/messages/queue", json_body={"text": "x"})
            raise AssertionError("a deactivated Creator's write went out")
        except OFDeactivatedError:
            pass
        c.request("GET", "/api2/v2/users/me")   # its reads stay open, and count
    finally:
        account_health._writes_off = before
    assert sent == [("GET", f"{API_BASE}/users/me")], sent
    assert _by_path_status(c.account_id) == {("GET /api2/v2/users/me", "2xx"): 1}, _rows(c.account_id)


def case_a_proxy_failure_is_one_error_and_connect_retries_count_once():
    pe = curl_requests.exceptions.ProxyError
    tok = of_client.INTERACTIVE_READ.set(True)   # 2 tries, a 0.1-0.2 s pause
    try:
        c, sent = _client([pe("CONNECT 403"), 200])
        c.request("GET", "/api2/v2/users/me")
        assert len(sent) == 2, sent
        assert _by_path_status(c.account_id) == {("GET /api2/v2/users/me", "2xx"): 1}, _rows(c.account_id)

        c, sent = _client([pe("CONNECT 403"), pe("CONNECT 403")])
        try:
            c.request("GET", "/api2/v2/users/me")
            raise AssertionError("no raise")
        except pe:
            pass
        assert len(sent) == 2, sent
        assert _by_path_status(c.account_id) == {("GET /api2/v2/users/me", "error"): 1}, _rows(c.account_id)
    finally:
        of_client.INTERACTIVE_READ.reset(tok)


def case_a_timeout_with_no_answer_is_error():
    c, _ = _client([curl_requests.exceptions.Timeout("read timed out")])
    _swallow(c.request, "POST", "/api2/v2/messages/queue", json_body={"text": "x"})
    assert _by_path_status(c.account_id) == {("POST /api2/v2/messages/queue", "error"): 1}, _rows(c.account_id)


def case_a_429_retried_by_the_pacer_counts_twice():
    gap, jit = of_pacing.PAGE_GAP_S, of_pacing.JITTER_S
    of_pacing.PAGE_GAP_S, of_pacing.JITTER_S = 0.0, 0.0
    try:
        c, sent = _client([(429, "Please allow 0 seconds"), 200])

        async def go():
            return await of_pacing.walk(c.account_id, "test", lambda: asyncio.to_thread(
                c.get_json, "/api2/v2/promotions"))
        asyncio.run(go())
    finally:
        of_pacing.PAGE_GAP_S, of_pacing.JITTER_S = gap, jit
    assert len(sent) == 2, sent
    assert _by_path_status(c.account_id) == {("GET /api2/v2/promotions", "429"): 1,
                                             ("GET /api2/v2/promotions", "2xx"): 1}, _rows(c.account_id)


def case_the_fallback_caller_kinds():
    """With no label: a call on the event loop is `task:<its task's name>`, one from a bare
    thread (or a worker thread) `unlabelled`."""
    c, _ = _client()

    async def on_loop():
        c.request("GET", "/api2/v2/users/me")

    async def main():
        t = asyncio.get_running_loop().create_task(on_loop(), name="slop-named")
        await t
        await asyncio.to_thread(c.request, "GET", "/api2/v2/chats")
    asyncio.run(main())
    th = threading.Thread(target=c.request, args=("GET", "/api2/v2/lists"))
    th.start()
    th.join()
    got = _rows(c.account_id)
    assert got == {("task:slop-named", "GET /api2/v2/users/me", "2xx"): 1,
                   ("unlabelled", "GET /api2/v2/chats", "2xx"): 1,
                   ("unlabelled", "GET /api2/v2/lists", "2xx"): 1}, got


def _callers(account_id: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for (caller, _path, _status), n in _rows(account_id).items():
        out[caller] = out.get(caller, 0) + n
    return out


def case_a_caller_scope_labels_and_the_innermost_wins():
    c, _ = _client()
    with of_call_counter.caller("auto:outer"):
        c.request("GET", "/api2/v2/users/me")
        with of_call_counter.caller("walk:inner"):
            c.request("GET", "/api2/v2/users/me")
        c.request("GET", "/api2/v2/users/me")
    c.request("GET", "/api2/v2/users/me")
    assert _callers(c.account_id) == {"auto:outer": 2, "walk:inner": 1, "unlabelled": 1}, _rows(c.account_id)


def case_a_label_follows_child_tasks_and_to_thread_but_not_a_bare_thread():
    c, _ = _client()

    async def child():
        c.request("GET", "/api2/v2/lists")

    async def main():
        with of_call_counter.caller("auto:parent"):
            t = asyncio.get_running_loop().create_task(child(), name="child-task")
            await asyncio.to_thread(c.request, "GET", "/api2/v2/chats")
            th = threading.Thread(target=c.request, args=("GET", "/api2/v2/users/me"))
            th.start()
            await asyncio.to_thread(th.join)
        await t   # started inside the scope, still labelled after it closed
    asyncio.run(main())
    got = _rows(c.account_id)
    assert got == {("auto:parent", "GET /api2/v2/lists", "2xx"): 1,
                   ("auto:parent", "GET /api2/v2/chats", "2xx"): 1,
                   ("unlabelled", "GET /api2/v2/users/me", "2xx"): 1}, got


def case_a_walk_labels_its_calls_walk_kind_and_wins_inside_an_automation():
    gap, jit = of_pacing.PAGE_GAP_S, of_pacing.JITTER_S
    of_pacing.PAGE_GAP_S, of_pacing.JITTER_S = 0.0, 0.0
    c, _ = _client()

    async def go():
        with of_call_counter.caller("auto:mass_send"):
            await of_pacing.walk(c.account_id, "audience_crawl",
                                 lambda: asyncio.to_thread(c.get_json, "/api2/v2/subscriptions/subscribers"))
            await asyncio.to_thread(c.get_json, "/api2/v2/messages/queue")
    try:
        asyncio.run(go())
    finally:
        of_pacing.PAGE_GAP_S, of_pacing.JITTER_S = gap, jit
    got = _rows(c.account_id)
    assert got == {("walk:audience_crawl", "GET /api2/v2/subscriptions/subscribers", "2xx"): 1,
                   ("auto:mass_send", "GET /api2/v2/messages/queue", "2xx"): 1}, got


def case_an_audience_crawl_page_inside_an_automation_run_counts_as_walk_audience_crawl():
    """phase-02: a mass send hands its audience to audience_crawl inside its automation run's scope; the crawl's
    roster page and its mass feed read (P2b: OF's count of the send) count as walk:audience_crawl (innermost wins),
    the run's own call as auto:send_mass_message."""
    import audience_crawl
    from db.engine import get_session
    from db.models import Account, MassRun
    gap, jit = of_pacing.PAGE_GAP_S, of_pacing.JITTER_S
    of_pacing.PAGE_GAP_S, of_pacing.JITTER_S = 0.0, 0.0
    page = json.dumps({"list": [{"id": 11}, {"id": 12}], "hasMore": False})
    feed = json.dumps({"items": [{"id": 8_300_000_001, "sentCount": 2}], "hasMore": False})
    c, sent = _client([200, (200, page), (200, feed)])

    async def go():
        async with get_session() as s:
            s.add(Account(id=c.account_id))
            mr = MassRun(account_id=c.account_id, audience_filter="{}", recipient_count=0, status="ok",
                         queue_id=8_300_000_001)
            s.add(mr)
            await s.flush()
            run = int(mr.id)
        with of_call_counter.caller("auto:send_mass_message"):
            await asyncio.to_thread(c.get_json, f"{API_BASE}/messages/queue")
            await audience_crawl.record_after_send(c.account_id, c, run, user_lists=["fans"],
                                                   sent_at=time.monotonic())
        await audience_crawl.drain(c.account_id, timeout_s=30)
        async with get_session() as s:
            return (await s.get(MassRun, run)).recipients_json
    try:
        stamped = asyncio.run(go())
    finally:
        of_pacing.PAGE_GAP_S, of_pacing.JITTER_S = gap, jit
    got = _rows(c.account_id)
    assert got == {("auto:send_mass_message", "GET /api2/v2/messages/queue", "2xx"): 1,
                   ("walk:audience_crawl", "GET /api2/v2/subscriptions/subscribers", "2xx"): 1,
                   ("walk:audience_crawl", "GET /api2/v2/users/me/stats/messages/group", "2xx"): 1}, (got, sent)
    assert stamped is not None and sorted(json.loads(stamped)) == [11, 12], stamped


def case_caller_kinds_fold_ids_so_one_code_site_is_one_kind():
    c, _ = _client()

    async def call():
        c.request("GET", "/api2/v2/users/me")

    async def main():
        loop = asyncio.get_running_loop()
        for name in ("mass-recipients-1545", "mass-recipients-1546", "media-dims-123456-789",
                     "reconcile-chats-0123abcd4567"):
            await loop.create_task(call(), name=name)
        for name in ("loop:mass-recipients-77", "loop:mass-recipients-78",
                     "route:GET /api/accounts/123456/chats/789",
                     "loop:job-deadbeefcafe0123456789"):
            with of_call_counter.caller(name):
                await call()
    asyncio.run(main())
    got = _callers(c.account_id)
    assert got == {"task:mass-recipients-{}": 2, "task:media-dims-{}-{}": 1, "task:reconcile-chats-{}": 1,
                   "loop:mass-recipients-{}": 2, "route:GET /api/accounts/{}/chats/{}": 1,
                   "loop:job-{}": 1}, got
    # a plain name is left alone
    with of_call_counter.caller("loop:link-figures-prewarm"):
        c.request("GET", "/api2/v2/users/me")
    assert "loop:link-figures-prewarm" in _callers(c.account_id), _callers(c.account_id)


def case_the_request_hook_labels_route_method_and_folded_path():
    c, _ = _client()
    seen = []

    async def call_next(_req):
        await asyncio.to_thread(c.request, "GET", "/api2/v2/chats")
        seen.append(of_call_counter.caller_kind())
        return "resp"

    def req(method, path):
        return types.SimpleNamespace(method=method, url=types.SimpleNamespace(path=path, query="x=1"))

    async def main():
        assert await of_call_counter.label_request_calls(req("GET", "/api/of/v2/chats/123/messages"),
                                                         call_next) == "resp"
        await of_call_counter.label_request_calls(req("get", "/api/of/v2/chats/456/messages"), call_next)
        await of_call_counter.label_request_calls(req("POST", "/api/of/v2/users/somefan/block"), call_next)
        await of_call_counter.label_request_calls(req("GET", "/api/of/v2/users/notifications/count"), call_next)
        return of_call_counter.caller_kind()
    after = asyncio.run(main())
    assert after.startswith("task:"), after          # the label ends with the request
    assert _callers(c.account_id) == {"route:GET /api/of/v2/chats/{}/messages": 2,
                                      "route:POST /api/of/v2/users/{}/block": 1,
                                      "route:GET /api/of/v2/users/notifications/count": 1}, _rows(c.account_id)


def case_the_row_cap_folds_new_keys_into_other():
    cap = of_call_counter.MAX_ROWS
    snap = of_call_counter.snapshot()
    used = len(snap["rows"])
    folded0 = snap["folded"]
    of_call_counter.MAX_ROWS = used + 5
    creators = [f"cc-cap{k}-{uuid.uuid4().hex[:6]}" for k in range(3)]
    try:
        n = 0
        for k in range(200):
            aid = creators[k % 3]
            status = (200, 404, 500)[k % 3]
            of_call_counter.record(aid, "GET", f"{API_BASE}/route{k}/x", status)
            n += 1
        snap = of_call_counter.snapshot()
    finally:
        of_call_counter.MAX_ROWS = cap
    rows = snap["rows"]
    assert len(rows) <= used + 5 + len(creators) * 8, (len(rows), used)
    mine = [r for r in rows if r[2] in creators]
    assert sum(r[4] for r in mine) == 200, sum(r[4] for r in mine)       # nothing dropped
    other = [r for r in mine if r[0] == "other"]
    assert other and all(r[1] == "other" for r in other), other
    assert {(r[2], r[3]) for r in other} <= {(a, s) for a in creators for s in ("2xx", "4xx", "5xx")}, other
    assert snap["folded"] - folded0 == sum(r[4] for r in other), (snap["folded"], folded0, other)
    assert snap["folded"] - folded0 >= 200 - 5, snap["folded"]


def case_record_never_raises():
    of_call_counter.record(None, "GET", None, None)          # nonsense in, no raise
    of_call_counter.record("x", None, "not a url", "weird")


# ── seam 2: persistence across processes ────────────────────────────────────

def _child(body: str, *, env: dict | None = None, server: bool = False, db_dir: Path | None = None) -> dict:
    """Run `body` in a fresh interpreter (its DB in `db_dir`, so the default counter path
    is that dir's). `server=True` imports server first, as the Relay boots. Returns the
    JSON the child prints last."""
    db_dir = db_dir or Path(tempfile.mkdtemp(prefix="occ-"))
    e = dict(os.environ)
    for k in ("OF_CALL_STATS_PATH", "OF_CALL_STATS_FLUSH_S", "OF_CALL_STATS_MAX_ROWS"):
        e.pop(k, None)
    db = db_dir / "chatterly.db"
    e["DATABASE_URL"] = f"sqlite+aiosqlite:///{db}"
    e["CHATTERLY_DB_URL"] = f"sqlite:///{db}"
    e["PRIORITY_LANE_STATS_PATH"] = ""
    e.update(env or {})
    code = ("import sys, json, time\n"
            f"sys.path.insert(0, {str(SERVICE_ROOT)!r})\n"
            + ("import server\n" if server else "")
            + "import of_call_counter\n" + body)
    r = subprocess.run([sys.executable, "-c", code], env=e, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, f"child failed: {r.stderr[-1500:]}"
    return json.loads(r.stdout.strip().splitlines()[-1])


_REC3 = ("for _ in range(3):\n"
         "    of_call_counter.record('acct-r', 'GET', 'https://onlyfans.com/api2/v2/users/me', 200)\n"
         "of_call_counter.flush()\n"
         "print(json.dumps(of_call_counter.snapshot()))\n")


def case_the_relay_persists_beside_the_db_and_counts_survive_a_restart():
    d = Path(tempfile.mkdtemp(prefix="occ-restart-"))
    first = _child(_REC3, server=True, db_dir=d)
    f = d / "of_call_stats.json"
    assert f.exists(), "server did not persist beside the DB"
    assert first["boots"] == 1 and first["v"] == 1, first
    disk = json.loads(f.read_text())
    assert set(disk) == {"v", "started_at", "flushed_at", "boots", "rows", "folded", "write_error", "unobserved_s",
                         "unobserved_since"}, disk
    assert (disk["unobserved_s"], disk["unobserved_since"]) == (0.0, disk["started_at"]), disk
    assert disk["rows"] == [["unlabelled", "GET /api2/v2/users/me", "acct-r", "2xx", 3]], disk["rows"]
    assert disk["write_error"] is None and disk["folded"] == 0, disk
    second = _child(_REC3, server=True, db_dir=d)
    assert second["boots"] == 2, second
    assert second["started_at"] == first["started_at"], (first["started_at"], second["started_at"])
    assert second["rows"] == [["unlabelled", "GET /api2/v2/users/me", "acct-r", "2xx", 6]], second["rows"]
    assert second["unobserved_since"] == first["unobserved_since"] and 0 < second["unobserved_s"] < 120, second
    assert json.loads(f.read_text())["rows"][0][4] == 6


def case_a_quiet_process_is_flushed_on_the_interval():
    d = Path(tempfile.mkdtemp(prefix="occ-quiet-"))
    p = d / "stats.json"
    out = _child(
        f"of_call_counter.start({str(p)!r})\n"
        "a = json.loads(open(" + repr(str(p)) + ").read())\n"
        "of_call_counter.record('acct-q', 'GET', 'https://onlyfans.com/api2/v2/chats?limit=1', 500)\n"
        "time.sleep(1.2)\n"
        "b = json.loads(open(" + repr(str(p)) + ").read())\n"
        "time.sleep(0.8)\n"
        "c = json.loads(open(" + repr(str(p)) + ").read())\n"
        "print(json.dumps({'a': a, 'b': b, 'c': c}))\n",
        env={"OF_CALL_STATS_FLUSH_S": "0.3"}, db_dir=d)
    assert out["a"]["rows"] == [] and out["a"]["boots"] == 1, out["a"]      # start writes at once
    assert out["b"]["rows"] == [["unlabelled", "GET /api2/v2/chats", "acct-q", "5xx", 1]], out["b"]
    assert out["c"]["flushed_at"] > out["b"]["flushed_at"] > out["a"]["flushed_at"], out


_V1 = '{"v": 1, "started_at": 1.0, "boots": 9, "folded": 0, "rows": [["x", "GET /a", "acct-v", "2xx", 50]%s]%s}'


def case_a_bad_or_other_version_file_starts_a_fresh_window():
    """Anything but a wholly valid v1 file: a fresh window, never its valid part under the old started_at."""
    for content in ('{"v": 0, "started_at": 1.0, "boots": 9, "rows": [["x", "GET /a", "acct-v", "2xx", 50]]}',
                    "{not json", '["a list"]',
                    _V1 % (', ["x", "GET /a", "acct-v", "2xx", "7"]', ""),     # one malformed row
                    _V1 % (', ["x", "GET /a", "acct-v"]', ""),
                    _V1 % ("", ', "boots": true'), _V1 % ("", ', "folded": -1'),
                    _V1.replace('"started_at": 1.0', '"started_at": "1.0"') % ("", ""),
                    _V1.replace('"started_at": 1.0', '"started_at": 1' + "0" * 400) % ("", ""),   # too large for a float
                    _V1 % ("", ', "boots": 1' + "0" * 400),
                    '{"v": 1, "started_at": 1.0, "boots": 9, "folded": 0}'):     # no rows
        d = Path(tempfile.mkdtemp(prefix="occ-bad-"))
        p = d / "stats.json"
        p.write_text(content)
        t0 = time.time()
        out = _child(f"of_call_counter.start({str(p)!r})\n" + _REC3, db_dir=d)
        assert out["boots"] == 1, (content, out)
        assert out["started_at"] >= t0 - 1, (content, out["started_at"], t0)
        assert out["rows"] == [["unlabelled", "GET /api2/v2/users/me", "acct-r", "2xx", 3]], (content, out)
        assert json.loads(p.read_text())["boots"] == 1
    d = Path(tempfile.mkdtemp(prefix="occ-ok-"))                          # control: a valid v1 file folds in
    p = d / "stats.json"
    p.write_text(_V1 % ("", ""))
    out = _child(f"of_call_counter.start({str(p)!r})\n" + _REC3, db_dir=d)
    assert (out["boots"], out["started_at"]) == (10, 1.0), out
    assert ["x", "GET /a", "acct-v", "2xx", 50] in out["rows"], out


def case_the_downtime_tally_adds_each_boots_gap_and_restarts_when_unknown():
    """unobserved_s += boot time - the loaded flushed_at; a gap it cannot measure (no tally in the file, a flush
    in the future) restarts the tally at this boot (a new unobserved_since: unknown to a reader, never 0)."""
    now = time.time()
    tally = ', "flushed_at": %r, "unobserved_s": 5.0, "unobserved_since": 2.0'
    for extra, want in ((tally % (now - 100), "added"), (tally % (now + 1000), "restart"),
                        (', "flushed_at": %r' % (now - 100), "restart"),
                        (tally.replace("5.0", "-1") % (now - 100), "restart"),
                        (tally.replace("5.0", "1" + "0" * 400) % (now - 100), "restart"),   # too large for a float:
                        (tally.replace("2.0", "1" + "0" * 400) % (now - 100), "restart"),   # the tally only, the
                        (tally.replace("%r", "1" + "0" * 400), "restart")):                 # window carries on
        d = Path(tempfile.mkdtemp(prefix="occ-unobs-"))
        p = d / "stats.json"
        p.write_text(_V1 % ("", extra))
        t0 = time.time()
        out = _child(f"of_call_counter.start({str(p)!r})\n" + _REC3, db_dir=d)
        assert (out["boots"], out["started_at"]) == (10, 1.0), (extra, out)         # the counts carry on either way
        if want == "added":
            assert out["unobserved_since"] == 2.0 and 104 < out["unobserved_s"] < 160, (extra, out)
        else:
            assert out["unobserved_s"] == 0.0 and out["unobserved_since"] >= t0 - 1, (extra, out)


def case_an_empty_path_writes_nothing():
    d = Path(tempfile.mkdtemp(prefix="occ-empty-"))
    out = _child(_REC3.replace("print(json.dumps(of_call_counter.snapshot()))",
                               "import threading\nprint(json.dumps({'snap': of_call_counter.snapshot(), "
                               "'threads': [t.name for t in threading.enumerate()]}))"),
                 server=True, env={"OF_CALL_STATS_PATH": ""}, db_dir=d)
    assert out["snap"]["rows"][0][4] == 3, out
    assert not any("of-call" in t for t in out["threads"]), out["threads"]
    assert sorted(x.name for x in d.iterdir() if "of_call" in x.name) == [], list(d.iterdir())


def case_of_client_alone_counts_in_memory_only():
    d = Path(tempfile.mkdtemp(prefix="occ-nostart-"))
    out = _child(
        "import types, of_client\n"
        "class R:\n"
        "    status_code = 200; ok = True; text = '{}'; headers = {}\n"
        "c = of_client.OFClient.__new__(of_client.OFClient)\n"
        "c.account_id = 'acct-n'; c.user_id = '1'; c.timeout_s = 5; c._x_hash = 'H'\n"
        "c.proxy_label = None; c.proxy_url = None; c._signed_headers = lambda u: {}\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parent)!r}); from _of_wire import fake_wire\n"
        "fake_wire(c, types.SimpleNamespace(get=lambda url, **k: R(), request=lambda m, url, **k: R()))\n"
        "c.request('GET', '/api2/v2/users/me')\n"
        "of_call_counter.flush()\n"
        "import threading\n"
        "print(json.dumps({'snap': of_call_counter.snapshot(), 'threads': [t.name for t in threading.enumerate()]}))\n",
        db_dir=d)
    assert out["snap"]["rows"] == [["unlabelled", "GET /api2/v2/users/me", "acct-n", "2xx", 1]], out
    assert not any("of-call" in t for t in out["threads"]), out["threads"]
    assert [x.name for x in d.iterdir() if "of_call" in x.name] == [], list(d.iterdir())


def case_knobs_are_read_with_defaults():
    out = _child("print(json.dumps({'flush': of_call_counter.FLUSH_S, 'rows': of_call_counter.MAX_ROWS, "
                 "'path': str(of_call_counter.stats_path())}))\n")
    assert out["flush"] == 30.0 and out["rows"] == 20000, out
    assert out["path"].endswith("/of_call_stats.json"), out
    out = _child("print(json.dumps({'flush': of_call_counter.FLUSH_S, 'rows': of_call_counter.MAX_ROWS, "
                 "'path': str(of_call_counter.stats_path())}))\n",
                 env={"OF_CALL_STATS_FLUSH_S": "2", "OF_CALL_STATS_MAX_ROWS": "50",
                      "OF_CALL_STATS_PATH": "/tmp/x/y.json"})
    assert out == {"flush": 2.0, "rows": 50, "path": "/tmp/x/y.json"}, out
    out = _child("print(json.dumps({'path': of_call_counter.stats_path()}))\n", env={"OF_CALL_STATS_PATH": ""})
    assert out == {"path": None}, out
    for bad in ("inf", "nan", "-5", "x"):                                 # never a failed import (the Relay boot)
        out = _child("print(json.dumps({'flush': of_call_counter.FLUSH_S, 'rows': of_call_counter.MAX_ROWS}))\n",
                     env={"OF_CALL_STATS_FLUSH_S": bad, "OF_CALL_STATS_MAX_ROWS": bad})
        assert out == {"flush": 30.0, "rows": 20000}, (bad, out)


_harness.run()
