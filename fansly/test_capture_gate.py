from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "capture"))

import blank  # noqa: E402
import drive  # noqa: E402
import gate  # noqa: E402
import mirror  # noqa: E402
import watch  # noqa: E402

API = "https://apiv3.fansly.com"
USERNAME = "plantedcreator"
IDS = [{"role": "creator", "username": USERNAME, "displayName": "Planted Creator",
        "accountId": "900000000000000001"}]


def check(cond, label, fails):
    if not cond:
        fails.append(label)


def decide_table(fails):
    rows = [
        ("GET", "https://cdn3.fansly.com/abc/1.jpg", False, "continue", "continued", False),
        ("HEAD", "https://apiv3.fansly.com/api/v1/account/me", False, "continue", "continued", False),
        ("OPTIONS", "https://apiv3.fansly.com/api/v1/message/ack", False, "continue", "continued", False),
        ("POST", "https://apiv3.fansly.com/api/v1/message/ack?ngsw-bypass=true", False, "fulfill", "faked", False),
        ("POST", "https://apiv3.fansly.com/api/v1/notifications/ack", False, "fulfill", "faked", False),
        ("POST", "https://apiv3.fansly.com/api/v1/status?ngsw-bypass=true", False, "fulfill", "faked", False),
        ("POST", "https://apiv3.fansly.com/api/v1/it/pis", False, "fulfill", "faked", False),
        ("POST", "https://apiv3.fansly.com/api/v1/mediastory/view", False, "fulfill", "faked", False),
        ("PUT", "https://apiv3.fansly.com/api/v1/message/ack", False, "fail", "halted", True),
        ("POST", "https://apiv3.fansly.com/api/v1/message/ack/extra", False, "fail", "halted", True),
        ("POST", "https://apiv3.fansly.com/api/v2/message/ack", False, "fail", "halted", True),
        ("POST", "https://evil.example/api/v1/message/ack", False, "fail", "halted", True),
        ("POST", "https://fansly.com/api/v1/message/ack", False, "fail", "halted", True),
        ("POST", "https://fansly-upload.s3-accelerate.amazonaws.com/x", False, "fail", "halted", True),
        ("POST", "https://api-iam.intercom.io/messenger/web/ping", False, "fulfill", "faked", False),
        ("POST", "https://g2ytx5gg.messenger.intercom-chat.com/messenger/web/ping", False, "fulfill", "faked", False),
        ("PUT", "https://api-iam.intercom.io/messenger/web/ping", False, "fail", "halted", True),
        ("POST", "https://api-iam.intercom.io/messenger/web/events", False, "fail", "halted", True),
        ("POST", "https://metrics.fansly.com/event/track/v1/", False, "fulfill", "faked", False),
        ("POST", "https://metrics.fansly.com/event/track/v2/", False, "fail", "halted", True),
        ("POST", "http://api-iam.intercom.io/messenger/web/ping", False, "fail", "halted", True),
        ("POST", "https://www.google-analytics.com/g/collect", False, "fail", "halted", True),
        ("POST", "https://abc123.edge.sdk.awswaf.com/abc/verify", False, "continue", "waf", False),
        ("PUT", "https://abc123.edge.sdk.awswaf.com/abc/verify", False, "fail", "halted", True),
        ("POST", "https://awswaf.com.evil.example/verify", False, "fail", "halted", True),
        ("DELETE", "https://apiv3.fansly.com/api/v1/message", False, "fail", "halted", True),
        ("GET", "https://cdn3.fansly.com/abc/1.jpg", True, "fail", "denied", False),
        ("POST", "https://apiv3.fansly.com/api/v1/message/ack", True, "fail", "denied", False),
        ("POST", "https://abc.edge.sdk.awswaf.com/verify", True, "fail", "denied", False),
    ]
    for method, url, halted, action, decision, halt in rows:
        v = gate.decide(method, url, "XHR", halted, API)
        got = (v.action, v.decision, v.halt)
        check(got == (action, decision, halt),
              f"decide {method} {url} halted={halted}: {got} != {(action, decision, halt)}", fails)
    v = gate.decide("POST", "https://api-iam.intercom.io/messenger/web/ping", "XHR", False, API)
    check((v.status, v.body, v.provenance) == (204, "", "telemetry"), f"intercom ping fake {v}", fails)
    v = gate.decide("POST", "http://127.0.0.1:5555/api/v1/status", "Fetch", False,
                    "http://127.0.0.1:5555")
    check(v.action == "fulfill", "decide fakes On-open paths on the self-test's local origin", fails)
    v = gate.decide("POST", "http://127.0.0.1:5555/sink", "Fetch", False, "http://127.0.0.1:5555")
    check(v.action == "fail" and v.halt, "decide halts a non-On-open POST on the local origin", fails)
    v = gate.decide("post", "https://apiv3.fansly.com/api/v1/message/ack", "XHR", False, API)
    check(v.action == "fulfill", "decide matches the method case-insensitively", fails)
    print("decide: method x host x path x halted table")


def on_open_table(fails):
    rows = {
        "/api/v1/message/ack": "recorded",
        "/api/v1/status": "recorded",
        "/api/v1/it/pis": "unverified",
        "/api/v1/notifications/ack": "unverified",
        "/api/v1/mediastory/view": "unverified",
    }
    for path, prov in rows.items():
        r = gate.on_open_reply("POST", API + path + "?ngsw-bypass=true", API)
        check(r is not None, f"on_open_reply {path} has a reply", fails)
        if r is None:
            continue
        body, provenance = r
        check(provenance == prov, f"on_open_reply {path} provenance {provenance} != {prov}", fails)
        check(json.loads(body)["success"] is True, f"on_open_reply {path} body success", fails)
    body, _ = gate.on_open_reply("POST", API + "/api/v1/status", API)
    resp = json.loads(body)["response"]
    check(set(resp) == {"accountId", "statusId", "lastSeenAt", "updatedAt"} and resp["statusId"] == 1,
          f"on_open_reply /status shape {sorted(resp)}", fails)
    check(json.loads(gate.on_open_reply("POST", API + "/api/v1/message/ack", API)[0])
          == {"success": True}, "on_open_reply /message/ack body", fails)
    check(gate.on_open_reply("GET", API + "/api/v1/message/ack", API) is None,
          "on_open_reply ignores GET", fails)
    check(gate.on_open_reply("POST", "https://other.example/api/v1/message/ack", API) is None,
          "on_open_reply ignores other hosts", fails)
    check(gate.on_open_reply("POST", API + "/api/v1/message/send", API) is None,
          "on_open_reply ignores other paths", fails)
    print("on_open_reply: shapes and provenance")


def redact_table(fails):
    rows = [
        (f"/{USERNAME}", "/{username}"),
        (f"/{USERNAME.upper()}/posts", "/{username}/posts"),
        ("/api/v1/account/900000000000000001", "/api/v1/account/{id}"),
        ("/messages/900544249083420672", "/messages/{id}"),
        ("/api/v1/messaging/groups", "/api/v1/messaging/groups"),
        ("/12345678", "/12345678"),
        ("/123456789", "/{id}"),
        ("/", "/"),
    ]
    for path, want in rows:
        got = gate.redact_path(path, IDS)
        check(got == want, f"redact_path {path!r} -> {got!r} != {want!r}", fails)
    check(gate.redact_path(f"/{USERNAME}", []) == f"/{USERNAME}",
          "redact_path with no identities leaves names", fails)
    print("redact_path: username and 9+ digit ids")


def stale_table(fails):
    rows = [(None, 100.0, 2.0, True), (99.0, 100.0, 2.0, False), (98.0, 100.0, 2.0, False),
            (97.9, 100.0, 2.0, True), (101.0, 100.0, 2.0, False)]
    for beat, now, max_age, want in rows:
        check(gate.is_stale(beat, now, max_age) is want,
              f"is_stale({beat}, {now}, {max_age}) != {want}", fails)
    print("is_stale: edges")


def binds_table(fails):
    ok = {"pass": True, "browser_id": "b1", "cases": []}
    check(gate.selftest_binds(ok, "b1") is None, "selftest_binds passes a matching self-test", fails)
    for st, bid, label in [(None, "b1", "missing"),
                           ({"pass": False, "browser_id": "b1"}, "b1", "failed"),
                           (ok, "b2", "other browser id")]:
        r = gate.selftest_binds(st, bid)
        check(isinstance(r, str) and "self-test" in r, f"selftest_binds refuses {label}: {r!r}", fails)
    print("selftest_binds: missing, failed, other browser")

    blanked = [{"type": "page", "url": "about:blank"}, {"type": "page", "url": "http://127.0.0.1:5/t/page.html"}]
    check(gate.unblanked_refusal(blanked) is None, "unblanked_refusal passes blank and non-Fansly tabs", fails)
    for t in ({"type": "page", "url": "https://fansly.com/home"},
              {"type": "iframe", "url": "https://apiv3.fansly.com/x"},
              {"type": "service_worker", "url": "https://fansly.com/sw.js"}):
        r = gate.unblanked_refusal(blanked + [t])
        check(isinstance(r, str) and "blank" in r, f"unblanked_refusal refuses an open {t['type']}: {r!r}", fails)
    print("unblanked_refusal: any Fansly target refused")


def log_line_table(fails):
    req = {"url": f"https://apiv3.fansly.com/api/v1/{USERNAME}/media?token=SECRETTOK&limit=10",
           "method": "GET",
           "headers": {"authorization": "AUTHSECRET", "Cookie": "c=COOKIESECRET"},
           "postData": "BODYSECRET"}
    v = gate.decide(req["method"], req["url"], "XHR", False, API)
    line = gate.request_line(1.0, "s1", "page", req, "XHR", v, IDS)
    text = json.dumps(line)
    for secret in ("AUTHSECRET", "COOKIESECRET", "SECRETTOK", "BODYSECRET", USERNAME, "authorization"):
        check(secret not in text, f"gate.jsonl line holds {secret}", fails)
    check(line["path"] == "/api/v1/{username}/media", f"line path {line['path']}", fails)
    check(sorted(line["query_keys"]) == ["limit", "token"], f"line query keys {line['query_keys']}", fails)
    check(line["decision"] == "continued" and line["host"] == "apiv3.fansly.com",
          "line decision/host", fails)
    print("gate.jsonl line: no header, token, body or username")


class FakeConn:
    def __init__(self, targets, crash_reports=True, fail=(), collateral=(), already=(), silent_once=(),
                 destroyed=(), crash_error=(), late=None, spawn=False):
        self.targets = [dict(t) for t in targets]
        self.crash_reports, self.fail, self.collateral = crash_reports, set(fail), set(collateral)
        self.already, self.silent_once, self.destroyed = set(already), set(silent_once), set(destroyed)
        self.crash_error, self.late, self.spawn, self.lists = set(crash_error), late or {}, spawn, 0
        self.calls, self.seq = [], 0
        self.ended = {k: {} for k in blank.TARGET_END.values()}

    def end(self, kind, tid):
        self.seq += 1
        self.ended[kind][tid] = self.seq

    async def send(self, method, params=None, session_id=None, timeout=10.0):
        self.calls.append((method, session_id or (params or {}).get("targetId")))
        if method in self.fail:
            raise RuntimeError(method)
        if method == "Target.getTargets":
            self.lists += 1
            self.targets += self.late.pop(self.lists, [])
            if self.spawn:
                self.targets.append({"targetId": f"n{self.lists}", "type": "page", "url": "https://fansly.com/n"})
            return {"targetInfos": [dict(t) for t in self.targets]}
        if method == "Target.attachToTarget":
            return {"sessionId": "s-" + params["targetId"]}
        if method == "Page.navigate":
            for t in self.targets:
                if t["targetId"] == session_id[2:]:
                    t["url"] = "about:blank"
        if method == "Page.crash":
            tid = session_id[2:]
            if tid in self.already:
                raise RuntimeError("{'code': -32000, 'message': 'The target has already crashed'}")
            if tid in self.crash_error:
                raise RuntimeError("{'code': -32000, 'message': 'Target crashed'}")
            if tid in self.destroyed:
                self.end("destroyed", tid)
            elif tid in self.silent_once:
                self.silent_once.discard(tid)
            elif self.crash_reports:
                for x in [tid, *sorted(self.collateral)]:
                    self.end("crashed", x)
            await asyncio.sleep(60)
        return {}


BLANK_TARGETS = [{"targetId": "p1", "type": "page", "url": "https://fansly.com/home"},
                 {"targetId": "f1", "type": "iframe", "url": "https://other.example/x", "parentId": "p1"},
                 {"targetId": "p2", "type": "page", "url": "about:blank"},
                 {"targetId": "p3", "type": "page", "url": "about:blank", "openerId": "p1"},
                 {"targetId": "w1", "type": "service_worker", "url": "https://fansly.com/sw.js"}]


def _blank(c, sessions=None, close_others=False):
    t0 = time.monotonic()
    r = asyncio.run(blank.blank_web_pages(c, {"p1": "s-p1"} if sessions is None else sessions, close_others))
    return r, time.monotonic() - t0


def _seq(c, keep=("Page.crash", "Page.navigate")):
    return [(m, s) for m, s in c.calls if m in keep or (m == "Target.closeTarget" and s == "w1")]


def blank_table(fails):
    saved = blank.CRASH_WAIT
    blank.CRASH_WAIT = 0.2
    crash_f1, crash_p1, nav_p1 = ("Page.crash", "s-f1"), ("Page.crash", "s-p1"), ("Page.navigate", "s-p1")
    try:
        c = FakeConn(BLANK_TARGETS)
        r, _ = _blank(c, close_others=True)
        seq = _seq(c, ("ServiceWorker.stopAllWorkers", "Page.crash", "Page.navigate"))
        check(r == (1, []) and seq == [("ServiceWorker.stopAllWorkers", "s-p1"), ("Target.closeTarget", "w1"),
                                       crash_f1, crash_p1, nav_p1],
              f"blank: SWs stopped, worker closed, iframe crashed, page crashed, then blanked: {r} {seq}", fails)
        check(("Target.closeTarget", "p1") not in c.calls, f"blank keeps the page tab: {c.calls}", fails)

        c = FakeConn(BLANK_TARGETS, crash_reports=False)
        r, _ = _blank(c, {"p1": "s-p1", "f1": "s-f1"})
        attaches = [s for m, s in c.calls if m == "Target.attachToTarget"]
        check(r == (1, ["f1", "p1"]) and not attaches,
              f"blank reuses the caller's sessions, also on retry (no explicit attach): {r} {attaches}", fails)

        for name, kw in [("never reported", {"crash_reports": False}), ("refused", {"fail": ("Page.crash",)})]:
            c = FakeConn(BLANK_TARGETS, **kw)
            r, took = _blank(c)
            check(r == (1, ["f1", "p1"]) and _seq(c) == [crash_f1, crash_f1, crash_p1, crash_p1, nav_p1],
                  f"blank crash {name}: retried once, still blanked, both reported unconfirmed: {r} {_seq(c)}", fails)
            if name == "refused":
                check(took < blank.CRASH_WAIT, f"blank does not wait out a refused crash: {took:.2f}s", fails)

        c = FakeConn(BLANK_TARGETS, silent_once=("p1",))
        r, _ = _blank(c)
        check(r == (1, []) and _seq(c) == [crash_f1, crash_p1, crash_p1, nav_p1],
              f"blank retries a silent crash and accepts the second: {r} {_seq(c)}", fails)

        for name, kw in [("'already crashed'", {"already": ("f1", "p1")}),
                         ("'Target crashed'", {"crash_error": ("f1", "p1")})]:
            c = FakeConn(BLANK_TARGETS, **kw)
            r, took = _blank(c)
            check(r == (1, []) and took < blank.CRASH_WAIT and _seq(c) == [crash_f1, crash_p1, nav_p1],
                  f"blank counts a {name} reply as crashed, no wait, no retry: {r} {took:.2f}s {_seq(c)}", fails)

        c = FakeConn(BLANK_TARGETS, destroyed=("f1",))
        r, took = _blank(c)
        check(r == (1, []) and took < 2 * blank.CRASH_WAIT,
              f"blank counts a destroyed target as done: {r} {took:.2f}s", fails)

        late = {3: [{"targetId": "f2", "type": "iframe", "url": "blob:https://fansly.com/u", "parentId": "p1"},
                    {"targetId": "f3", "type": "iframe", "url": "data:text/html,x", "parentId": "f2"},
                    {"targetId": "fx", "type": "iframe", "url": "https://x.example/", "parentId": "p3"},
                    {"targetId": "p4", "type": "page", "url": "https://fansly.com/pop", "openerId": "p1"}]}
        c = FakeConn(BLANK_TARGETS, late=late)
        r, _ = _blank(c)
        crashes = [s for m, s in c.calls if m == "Page.crash"]
        check(r == (2, []) and crashes == ["s-f1", "s-p1", "s-f2", "s-f3", "s-fx", "s-p4"]
              and ("Page.navigate", "s-p4") in c.calls,
              f"blank re-lists: late iframes (any URL, any parent) and a late popup crashed: {r} {crashes}", fails)

        c = FakeConn(BLANK_TARGETS, spawn=True)
        r, _ = _blank(c)
        check(set(r[1]) == {"n6", "n7"},
              f"blank reports tabs still live after its last pass: {r}", fails)

        c = FakeConn(BLANK_TARGETS, collateral=("p3",))
        c.end("crashed", "p2")
        _blank(c)
        navs = [s for m, s in c.calls if m == "Page.navigate"]
        check(navs == ["s-p1", "s-p3"],
              f"blank blanks a page that crashed with it, not one crashed before the call: {navs}", fails)

        c = FakeConn(BLANK_TARGETS, fail=("Page.navigate",))
        sessions = {"p1": "s-p1"}
        _blank(c, sessions)
        check(("Target.closeTarget", "p1") in c.calls and "p1" not in sessions,
              f"blank closes a page it cannot navigate: {c.calls}", fails)
    finally:
        blank.CRASH_WAIT = saved

    info = {"sessionId": "s-p1", "targetInfo": {"targetId": "p1", "type": "page"}}
    for halted in (False, True):
        g = object.__new__(gate.Gate)
        g.halted, g.patterns, g.conn = halted, [], FakeConn([], fail=("Fetch.enable",))
        g.event = lambda *a, **k: None

        async def no_halt(reason):
            pass
        g.halt = no_halt
        asyncio.run(g.arm(None, info))
        check((("Target.closeTarget", "p1") in g.conn.calls) is not halted,
              f"gate arm failure closes the tab only before a halt (halted={halted}): {g.conn.calls}", fails)
        b = watch.Backstop(Path("/nonexistent"), 1)
        b.deny_all, b.conn = halted, FakeConn([], fail=("Fetch.enable",))
        asyncio.run(b.arm(None, info))
        check((("Target.closeTarget", "p1") in b.conn.calls) is not halted,
              f"backstop arm failure closes the tab only before blanking (deny_all={halted}): {b.conn.calls}", fails)

    saved = gate.BLANK_EXIT_WAIT
    gate.BLANK_EXIT_WAIT = 0.05
    try:
        for done in (False, True):
            g = object.__new__(gate.Gate)
            events = []
            g.halted, g.event = True, lambda name, **kw: events.append(name)

            async def run(done=done):
                g.blank_done = asyncio.Event()
                if done:
                    g.blank_done.set()
                await g.wait_blank()
            asyncio.run(run())
            check(events == ([] if done else ["blank_unconfirmed"]),
                  f"gate exit waits for the halt blank (done={done}): {events}", fails)
    finally:
        gate.BLANK_EXIT_WAIT = saved

    class WS:
        def __init__(self, replies=()):
            self.replies, self.sent = list(replies), []

        async def send(self, raw):
            self.sent.append(json.loads(raw))

        async def close(self):
            pass

        def __aiter__(self):
            async def gen():
                for m in ("Target.targetCrashed", "Target.targetDestroyed", "Target.detachedFromTarget"):
                    yield json.dumps({"method": m, "params": {"targetId": "t9"}})
                while self.replies:
                    await asyncio.sleep(0.01)
                    if self.sent:
                        yield json.dumps({"id": self.sent[-1]["id"], **self.replies.pop(0)})
            return gen()

    async def read():
        conn = gate.Conn(WS())
        await conn.closed.wait()
        return conn.seq, conn.ended
    check(asyncio.run(read()) == (3, {"crashed": {"t9": 1}, "destroyed": {"t9": 2}, "detached": {"t9": 3}}),
          "Conn records crash, destroy and detach by target in order", fails)

    async def dial(reply):
        ws = WS([reply])
        saved_url, saved_connect = gate.browser_ws_url, gate.websockets.connect

        async def fake_connect(*a, **k):
            return ws
        gate.browser_ws_url, gate.websockets.connect = (lambda port: "ws://x"), fake_connect
        try:
            await gate.connect(1)
            return [m["method"] for m in ws.sent]
        except Exception as e:
            return type(e).__name__
        finally:
            gate.browser_ws_url, gate.websockets.connect = saved_url, saved_connect
    check(asyncio.run(dial({"result": {}})) == ["Target.setDiscoverTargets"],
          "connect enables target discovery", fails)
    check(asyncio.run(dial({"error": {"code": -1, "message": "no"}})) == "RuntimeError",
          "connect fails when target discovery is refused", fails)
    check(gate._unconfirmed_refusal([]) == 0 and gate._unconfirmed_refusal(["p1"]) == 3,
          "blank/stop exit 3 when a target was blanked without a confirmed crash", fails)
    print("blank_web_pages: renderers crashed before any navigate, unconfirmed crashes reported")


class Root:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def session(self, sid, lines, unread=None, files=()):
        d = self.root / "sessions" / sid
        d.mkdir(parents=True)
        with (d / "gate.jsonl").open("w") as f:
            for ln in lines:
                f.write(json.dumps({"session": sid, **ln}) + "\n")
        if unread is not None:
            with (d / "unread.jsonl").open("w") as f:
                for i, groups in enumerate(unread):
                    f.write(json.dumps({"ts": 10 + i, "groups": groups}) + "\n")
        for name in files:
            (d / name).write_text("reason\n")
        return d


def req(method, decision, ts=5.0, path="/api/v1/x", host="apiv3.fansly.com", **kw):
    return {"ts": ts, "method": method, "host": host, "path": path, "query_keys": [],
            "resource_type": "XHR", "target_type": "page", "decision": decision,
            "reason": "", **kw}


ARMED = {"ts": 1.0, "event": "armed"}
STOPPED = {"ts": 99.0, "event": "stopped"}
UNREAD = [{"g1": 0, "g2": 3}, {"g1": 0, "g2": 3}]


def audit_table(fails):
    r = Root()
    cases = [
        ("clean", [ARMED, req("GET", "continued"), STOPPED], UNREAD, (), True),
        ("continued POST", [ARMED, req("POST", "continued"), STOPPED], UNREAD, (), False),
        ("continued HEAD", [ARMED, req("HEAD", "continued"), req("OPTIONS", "continued"), STOPPED],
         UNREAD, (), True),
        ("waf POST", [ARMED, req("POST", "waf", host="x.edge.sdk.awswaf.com"), STOPPED], UNREAD, (), True),
        ("socket frame", [ARMED, {"ts": 3.0, "event": "ws_frame_sent"}, STOPPED], UNREAD, (), False),
        ("socket created", [ARMED, {"ts": 3.0, "event": "ws_created", "host": "x"}, STOPPED], UNREAD, (), False),
        ("unread drop", [ARMED, STOPPED], [{"g1": 2, "g2": 3}, {"g1": 0, "g2": 3}], (), False),
        ("unread rise", [ARMED, STOPPED], [{"g1": 0, "g2": 3}, {"g1": 1, "g2": 3}], (), True),
        ("one groups obs", [ARMED, STOPPED], [{"g1": 0}], (), False),
        ("empty first obs, drop later", [ARMED, STOPPED], [{}, {"g1": 2}, {"g1": 0}], (), False),
        ("empty first obs, steady", [ARMED, STOPPED], [{}, {"g1": 2}, {}, {"g1": 2}], (), True),
        ("no thread seen twice", [ARMED, STOPPED], [{}, {"g1": 2}, {"g2": 0}], (), False),
        ("no groups obs", [ARMED, STOPPED], None, (), False),
        ("missing stopped", [ARMED, req("GET", "continued")], UNREAD, (), False),
        ("watchdog trip", [ARMED, STOPPED], UNREAD, ("WATCHDOG_TRIP",), False),
        ("halt", [ARMED, {"ts": 4.0, "event": "halt", "reason": "write"}, STOPPED], UNREAD, ("HALT",), False),
        ("halt marker only", [ARMED, STOPPED], UNREAD, ("HALT",), False),
        ("blank unconfirmed", [ARMED, {"ts": 98.0, "event": "blank_unconfirmed", "targets": ["p1"], "by": "stop"},
                               STOPPED], UNREAD, (), False),
        ("unverified fake", [ARMED, req("POST", "faked", ts=20.0, path="/api/v1/it/pis",
                                        provenance="unverified"), STOPPED], UNREAD, (), True),
    ]
    results = {}
    for name, lines, unread, files, want in cases:
        sid = name.replace(" ", "-")
        d = r.session(sid, lines, unread, files)
        res = gate.audit(d, 100.0)
        results[name] = res
        check(res.passed is want, f"audit {name}: passed={res.passed} failures={res.failures}", fails)
    check(results["waf POST"].counts.get("waf") == 1 and results["waf POST"].counts.get("continued_writes") == 0,
          f"audit counts WAF apart: {results['waf POST'].counts}", fails)
    check(any("rose" in w for w in results["unread rise"].warnings),
          f"audit warns on unread rise: {results['unread rise'].warnings}", fails)
    check(not results["clean"].warnings, f"clean audit has no warnings: {results['clean'].warnings}", fails)

    sid = "unverified-next-page"
    d = r.session(sid, [ARMED, req("POST", "faked", ts=time.time() - 50, path="/api/v1/it/pis",
                                   provenance="unverified"), STOPPED], UNREAD)
    pages = r.root / "pages" / "creator" / "stats"
    pages.mkdir(parents=True)
    early = pages / "early.meta.json"
    early.write_text(json.dumps({"session": sid}))
    os.utime(early, (time.time() - 100, time.time() - 100))
    nxt = pages / "overview.meta.json"
    nxt.write_text(json.dumps({"session": sid}))
    os.utime(nxt, (time.time() - 40, time.time() - 40))
    other = r.root / "pages" / "home.meta.json"
    other.write_text(json.dumps({"session": "someone-else"}))
    os.utime(other, (time.time() - 45, time.time() - 45))
    res = gate.audit(d, time.time())
    check(res.passed and any("creator/stats/overview" in w and "/api/v1/it/pis" in w for w in res.warnings),
          f"unverified fake warns naming the next saved page: {res.warnings}", fails)
    print("audit: fixture session table")


def unread_parse_table(fails):
    body = {"success": True, "response": {"data": [{"groupId": "g1", "unreadCount": 2},
                                                   {"groupId": "g2"}], "aggregationData": {}}}
    check(gate.unread_from_groups(body) == {"g1": 2, "g2": 0}, "unread_from_groups reads data[]", fails)
    check(gate.unread_from_groups({"success": False}) is None, "unread_from_groups on a failed reply", fails)
    me = {"success": True, "response": {"account": {"id": "1", "username": "u", "displayName": "D",
                                                    "avatar": {"id": "2", "locations": []}, "n": 3}}}
    check(gate.identity_from_me(me) == {"role": "creator", "username": "u", "displayName": "D",
                                        "accountId": "1"}, "identity_from_me", fails)
    check(gate.value_shape(me["response"]["account"]) == {
        "id": "str", "username": "str", "displayName": "str",
        "avatar": {"id": "str", "locations": []}, "n": "int"}, "value_shape keeps keys and types", fails)
    ids = {"success": True, "response": [{"id": "5", "username": "f", "displayName": "F"}]}
    check(gate.identity_from_accounts(ids, "5") == {"role": "fan", "username": "f", "displayName": "F",
                                                    "accountId": "5"}, "identity_from_accounts", fails)
    check(gate.identity_from_accounts(ids, "6") is None, "identity_from_accounts other id", fails)
    print("response readers: unread, identities, shape")


def cli_table(fails):
    py = sys.executable
    g = str(HERE / "capture" / "gate.py")
    with tempfile.TemporaryDirectory() as root:
        for sub in ("run", "watch", "selftest", "blank", "stop"):
            p = subprocess.run([py, g, sub, "--port", "9222", "--root", root],
                               capture_output=True, text=True, timeout=30)
            check(p.returncode != 0 and "9222" in (p.stdout + p.stderr),
                  f"{sub} --port 9222 refused: rc={p.returncode} {p.stderr[-200:]}", fails)
        p = subprocess.run([py, g, "run", "--port", "9241", "--root", root],
                           capture_output=True, text=True, timeout=30)
        check(p.returncode != 0 and "self-test" in (p.stdout + p.stderr),
              f"run on a fresh root refuses naming the self-test: rc={p.returncode} {p.stderr[-200:]}", fails)
        check(not (Path(root) / "ports").exists(), "refused run wrote no ports file", fails)
    print("cli: 9222 refused everywhere; run needs the self-test")

REQUIRED = {
    "routes": [
        "/home", "/{username}", "/{username}/media", "/{username}/media/pictures", "/{username}/followers",
        "/{username}/following", "/post/{postId}", "/messages", "/messages/{groupId}", "/creator/chat",
        "/notifications", "/creator", "/creator/vault", "/creator/vault/{albumId}",
        "/creator/stats/overview", "/creator/stats/content", "/creator/stats/audience",
        "/creator/stats/earnings", "/creator/stats/streams", "/creator/wallet/payouts",
        "/creator/wallet/history", "/creator/payout/documentation", "/creator/plans",
        "/creator/trackinglinks", "/creator/subscribers", "/creator/followers", "/creator/topsupporters",
        "/creator/uploads", "/creator/management", "/creator/streaming", "/creator/coperformers",
        "/creator/coperformers/requests", "/creator/coperformers/new", "/creator/coperformers/new/manual",
        "/creator/coperformers/new/request", "/creator/coperformers/new/sign",
        "/creator/coperformers/{coperformerId}", "/scheduled", "/lists", "/lists/{listId}", "/bookmarks",
        "/lists/blocked_accounts", "/lists/muted_accounts", "/lists/vip_accounts",
        "/lists/dm_permission_bypass", "/bookmarks/2007", "/subscriptions", "/settings/account", "/settings/profile",
        "/settings/notifications", "/settings/display", "/settings/payments", "/settings/privacy",
        "/settings/sessions", "/settings/connections", "/settings/about",
    ],
    "states": [
        "home/state-avatar-menu", "home/state-balance-menu", "home/state-post-create",
        "profile/state-post-menu", "profile/state-edit", "profile/state-wall-manage",
        "profile/state-locked-text-story", "messages/state-broadcast-composer",
        "messages/state-broadcast-queue", "messages/state-broadcast-history", "messages/thread/state-menu",
        "messages/thread/state-reaction-picker", "messages/thread/state-notes-edit",
        "messages/thread/state-list-select", "messages/thread/state-message-schedule",
        "messages/thread/state-read-receipts", "creator/vault/state-album-create", "creator/vault/state-upload",
        "creator/stats/audience/state-fan-detail", "creator/plans/state-tier-create",
        "creator/plans/state-promotion-create", "creator/plans/state-promotion-edit",
        "creator/plans/state-gift-code-create", "creator/trackinglinks/state-create",
        "creator/management/state-session-create", "lists/list/state-edit", "lists/list/state-add-account",
        "lists/list/state-row-menu", "settings/account/state-password-change",
        "settings/account/state-email-change", "settings/account/state-2fa",
        "settings/account/state-username-change", "settings/payments/state-add-payment-method",
        "settings/sessions/state-session-close",
    ],
}


def page(pid, url, **kw):
    return {"id": pid, "kind": "page", "url": url, **kw}


def state(pid, parent, url, **kw):
    return {"id": pid, "kind": "state", "url": url, "parent": parent, **kw}


GOOD_PLAN = [page("home", "/home", tracer=True), state("home/state-menu", "home", "/home", tracer=True),
             page("creator", "/creator"), page("settings/account", "/settings/account", tracer=True),
             page("creator/coperformers/detail", "/creator/coperformers/{coperformerId}", optional=True)]


def plan_table(fails):
    rows = [
        ("good", GOOD_PLAN, None),
        ("duplicate id", GOOD_PLAN + [page("home", "/home")], "duplicate id home"),
        ("state parent is a state", GOOD_PLAN + [state("home/state-menu/state-x", "home/state-menu", "/home")],
         "is a State"),
        ("state parent missing", GOOD_PLAN + [state("x/state-y", "x", "/x")], "not in the plan"),
        ("more than 5 tracer pages", GOOD_PLAN + [page(f"p{i}", f"/p{i}", tracer=True) for i in range(4)],
         "tracer pages"),
        ("no tracer state", [e for e in GOOD_PLAN if e["kind"] == "page"], "no tracer State"),
        ("id escapes the root", GOOD_PLAN + [page("../out", "/out")], "path-like"),
        ("unknown placeholder", GOOD_PLAN + [page("x", "/x/{nope}")], "placeholder"),
    ]
    for name, plan, want in rows:
        errs = mirror.check_plan(plan, None)
        if want is None:
            check(not errs, f"check_plan {name}: {errs}", fails)
        else:
            check(any(want in e for e in errs), f"check_plan {name}: {errs} lacks {want!r}", fails)
    real = mirror.load_plan()
    errs = mirror.check_plan(real, REQUIRED)
    check(not errs, f"real mirror_plan.json passes the ticket 01 REQUIRED literal: {errs}", fails)
    short = [e for e in real if e["id"] not in ("creator/followers", "lists/list/state-row-menu")]
    errs = mirror.check_plan(short, REQUIRED)
    check(any("/creator/followers" in e for e in errs) and any("state-row-menu" in e for e in errs),
          f"a plan short of a ticket 01 route and State fails: {errs}", fails)
    check(mirror.REQUIRED == REQUIRED, "gate's REQUIRED matches the ticket 01 literal in this test", fails)
    tracer = [e for e in real if e.get("tracer")]
    check(sorted(e["id"] for e in tracer) == ["creator/stats/overview", "home", "messages/thread",
                                              "messages/thread/state-menu", "profile", "settings/account"],
          f"tracer marks: {[e['id'] for e in tracer]}", fails)
    p = subprocess.run([sys.executable, str(HERE / "capture" / "gate.py"), "plan", "--check"],
                       capture_output=True, text=True, timeout=30)
    check(p.returncode == 0, f"gate.py plan --check exits 0: {p.returncode} {p.stdout[-300:]}", fails)
    print("check_plan: broken plans fail, the real plan covers ticket 01")


CREATOR_HTML = ('<html><body><a href="/home">h</a><a href="https://fansly.com/settings/account">s</a>'
                '<a href="/explore/x">e</a><a href="https://other.example/x">o</a>'
                '<a href="/creator/coperformers/123">c</a><a href="/creator/old-alias">a</a>{extra}</body></html>')


class ManifestRoot:
    def __init__(self, sessions=None, idents=None, skipped=True, extra_link="", settings_html="<html></html>",
                 drop=()):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        sessions = sessions or {"s1": True}
        for sid, passed in sessions.items():
            d = self.root / "sessions" / sid
            d.mkdir(parents=True)
            if passed is not None:
                (d / "audit.json").write_text(json.dumps({"session": sid, "passed": passed}))
        ids = idents if idents is not None else [
            {"role": "creator", "username": USERNAME, "displayName": "Planted Creator", "accountId": 900000000000000001},
            {"role": "fan", "username": "plantedfan", "displayName": "Fan", "accountId": "123456789012345678"}]
        (self.root / "sessions" / "s1" / "identities.json").write_text(json.dumps(ids))
        saves = [("home", "page", "https://fansly.com/home", "<html><a href='/nowhere'>x</a></html>"),
                 ("home/state-menu", "menu", "https://fansly.com/home", "<html></html>"),
                 ("creator", "page", "https://fansly.com/creator/old-alias", CREATOR_HTML.format(extra=extra_link)),
                 ("settings/account", "page", "https://fansly.com/settings/account", settings_html)]
        for pid, st, url, html in saves:
            if pid not in drop:
                self.save(pid, st, url, html, "s1")
        if skipped:
            (self.root / "skipped.json").write_text(json.dumps([
                {"id": "creator/coperformers/detail", "reason": "none on the account", "tried": ["a.coperf"]},
                {"id": "home", "reason": "not optional", "tried": ["x"]}]))
        (self.root / "static" / "assets.fansly.com").mkdir(parents=True)
        (self.root / "static" / "assets.fansly.com" / "a.css").write_text("body{}")
        (self.root / "assets.json").write_text(json.dumps([
            {"url": "https://assets.fansly.com/a.css", "file": "static/assets.fansly.com/a.css"},
            {"url": "https://assets.fansly.com/b.css", "file": "static/../../outside.css"}]))

    def save(self, pid, st, url, html, sid, bundle="abc"):
        final = "https://fansly.com/creator" if pid == "creator" else url
        meta = {"id": pid, "url": url, "final_url": final, "state": st, "opener": "button" if st != "page" else None,
                "settled_selector": "body", "reset": None, "bundle_hash": bundle, "theme": "light",
                "session": sid, "canvases": 1, "shadow_roots": 0, "iframes": 0}
        drive.commit_save(drive.stage_save(self.root, pid, html, b"png", meta), keep=True)

    def build(self):
        return mirror.build_manifest(self.root, GOOD_PLAN, mirror.read_audits(self.root))


def manifest_table(fails):
    r = ManifestRoot()
    m = r.build()
    check(m["complete"] is True and m["audit"]["passed"] is True,
          f"complete fixture: complete={m['complete']} missing={m['missing']} links={m['uncovered_links']}", fails)
    check(sorted(e["id"] for e in m["entries"]) == ["creator", "home", "home/state-menu", "settings/account"],
          f"entries: {[e['id'] for e in m['entries']]}", fails)
    check([s["id"] for s in m["skipped"]] == ["creator/coperformers/detail"],
          f"skipped[] holds only optional, uncaptured ids: {m['skipped']}", fails)
    check(not set(s["id"] for s in m["skipped"]) & set(e["id"] for e in m["entries"]), "skipped apart", fails)
    check(m["assets"] == [{"url": "https://assets.fansly.com/a.css", "file": "static/assets.fansly.com/a.css"}],
          f"assets[] inside the root only: {m['assets']}", fails)
    for e in m["entries"]:
        check(e["file"] == f"pages/{e['id']}.html" and (r.root / e["file"]).is_file(), f"entry file {e['file']}", fails)
        check(set(e) >= {"kind", "url", "final_url", "state", "opener", "settled_selector", "reset", "bundle_hash",
                         "theme", "session", "canvases", "shadow_roots", "iframes", "meta", "png"},
              f"entry fields {sorted(e)}", fails)
    check(all(isinstance(i["accountId"], str) for i in m["identities"]) and
          {i["role"] for i in m["identities"]} == {"creator", "fan"}, f"identities: {m['identities']}", fails)
    check(m["identities"][0]["accountId"] == "900000000000000001", "account id kept exactly as a string", fails)
    check(m["bundle_hash"] == "abc" and m["theme"] == "light", "shared bundle hash and theme", fails)
    check(next(e for e in m["entries"] if e["id"] == "home/state-menu")["kind"] == "state", "state kind", fails)

    r = ManifestRoot(sessions={"s1": True, "s2": False, "s3": None})
    r.save("creator/coperformers/detail", "page", "https://fansly.com/creator/coperformers/5", "<html></html>", "s2")
    r.save("profile-extra", "page", "https://fansly.com/x", "<html></html>", "s3")
    m = r.build()
    check(m["unaudited"] == ["creator/coperformers/detail", "profile-extra"]
          and "creator/coperformers/detail" not in {e["id"] for e in m["entries"]},
          f"unpassed and unaudited sessions' saves listed unaudited, not entries: {m['unaudited']}", fails)
    check({s["id"]: s["verdict"] for s in m["audit"]["sessions"]} == {"s1": "pass", "s2": "fail", "s3": "unaudited"},
          f"audit.sessions verdicts: {m['audit']['sessions']}", fails)

    r = ManifestRoot()
    r.save("not-a-plan-id", "page", "https://fansly.com/x", "<html></html>", "s1")
    (r.root / "pages" / "home.meta.json").write_text(json.dumps(
        {**json.loads((r.root / "pages" / "home.meta.json").read_text()), "state": "menu"}))
    m = r.build()
    check("not-a-plan-id" not in {e["id"] for e in m["entries"]} and m["not_in_plan"] == ["not-a-plan-id"],
          f"a passed save whose id is not in the plan is left out and listed: {m.get('not_in_plan')}", fails)
    check(next(e for e in m["entries"] if e["id"] == "home")["kind"] == "page",
          "kind comes from the plan, never guessed from the meta", fails)
    check(m["complete"] is True, "a stray non-plan save does not change complete", fails)

    r = ManifestRoot(sessions={"s1": True, "s2": False})
    r.save("home", "page", "https://fansly.com/home", "<html>old</html>", "s2")
    r.save("home", "page", "https://fansly.com/home", "<html>new</html>", "s1")
    m = r.build()
    homes = [e for e in m["entries"] if e["id"] == "home"]
    check(len(homes) == 1 and homes[0]["session"] == "s1" and "home" not in m["unaudited"]
          and (r.root / "pages" / "home.html").read_text() == "<html>new</html>",
          f"a re-saved entry keeps only the latest: {homes} unaudited={m['unaudited']}", fails)

    variants = [
        ("missing non-optional entry", dict(drop=("settings/account",))),
        ("optional neither captured nor skipped", dict(skipped=False)),
        ("missing fan identity", dict(idents=[{"role": "creator", "username": USERNAME, "displayName": "P",
                                               "accountId": "1"}])),
        ("uncovered Creator Hub link", dict(extra_link='<a href="/creator/brand-new">n</a>')),
        ("uncovered settings link", dict(settings_html='<html><a href="/settings/brand-new">n</a></html>')),
    ]
    for name, kw in variants:
        m = ManifestRoot(**kw).build()
        check(m["complete"] is False and m["audit"]["passed"] is False, f"{name} leaves complete false", fails)
    m = ManifestRoot(extra_link='<a href="/creator/brand-new">n</a>').build()
    check(m["uncovered_links"] == ["/creator/brand-new"], f"uncovered links named: {m['uncovered_links']}", fails)
    r = ManifestRoot(sessions={"s1": True, "s2": False})
    (r.root / "sessions" / "s1" / "identities.json").write_text("[]")
    (r.root / "sessions" / "s2" / "identities.json").write_text(json.dumps([
        {"role": "creator", "username": "c", "displayName": "C", "accountId": "1"},
        {"role": "fan", "username": "f", "displayName": "F", "accountId": "2"}]))
    check(r.build()["complete"] is False, "identities from an unpassed session do not count", fails)
    r = ManifestRoot()
    r.save("settings/account", "page", "https://fansly.com/settings/account", "<html></html>", "s1", bundle="def")
    check(r.build()["bundle_hash"] is None, "mixed bundle hashes leave bundle_hash null", fails)

    r = ManifestRoot()
    (r.root / "plan.json").write_text(json.dumps(GOOD_PLAN))
    p = subprocess.run([sys.executable, str(HERE / "capture" / "gate.py"), "manifest", "--root", str(r.root),
                        "--plan", str(r.root / "plan.json")], capture_output=True, text=True, timeout=30)
    out = json.loads((r.root / "manifest.json").read_text()) if (r.root / "manifest.json").exists() else {}
    check(p.returncode == 0 and out.get("complete") is True and USERNAME not in p.stdout + p.stderr,
          f"gate.py manifest writes a complete manifest, prints no identity: {p.returncode} {p.stdout[-300:]}", fails)
    print("build_manifest: audited saves only, completeness rule, shape")


def main(argv) -> int:
    fails: list[str] = []
    decide_table(fails)
    on_open_table(fails)
    redact_table(fails)
    stale_table(fails)
    binds_table(fails)
    log_line_table(fails)
    blank_table(fails)
    audit_table(fails)
    unread_parse_table(fails)
    cli_table(fails)
    plan_table(fails)
    manifest_table(fails)
    for f in fails:
        print(f"  FAIL {f}", file=sys.stderr)
    if fails:
        print(f"{len(fails)} check(s) failed", file=sys.stderr)
        return 1
    print("all capture gate checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
