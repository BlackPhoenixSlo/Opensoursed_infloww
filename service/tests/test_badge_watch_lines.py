#!/usr/bin/env python3
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # noqa: E401,E702
import _harness  # noqa: E402  (first: temp DB)

_harness.bootstrap()

import contextlib  # noqa: E402
import importlib  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from urllib.parse import parse_qs, urlsplit  # noqa: E402

import accounts as account_registry  # noqa: E402

_harness.make_client()
import server  # noqa: F401,E402  (wires the frame lane)
import badge_reads  # noqa: E402
import badge_watch  # noqa: E402
import events  # noqa: E402
import events_persist  # noqa: E402
import of_call_counter  # noqa: E402
import of_ws  # noqa: E402
import shared_refresher  # noqa: E402
import unread_total  # noqa: E402
from unread_total_decide import Restricted  # noqa: E402
from of_client import OFClient  # noqa: E402

A = "8241"
F, G = 9401, 9402
SCRAPE = "auto:scrape_chats"
THREAD_ROUTE = "route:GET /api/of/v2/chats/9401/messages"

account_registry.get_account = lambda aid: {"id": aid} if aid == A else None
account_registry.is_account = lambda aid: aid == A
account_registry.get_platform = lambda aid: "onlyfans"
account_registry.get_role = lambda aid: None
events_persist.enqueue = lambda *_a, **_k: None


class _Resp:
    def __init__(self, url, body):
        self.url, self.status_code, self.ok = url, 200, True
        self.text, self.headers = json.dumps(body), {}

    def json(self):
        return json.loads(self.text)


class _Wire:
    def __init__(self):
        self.calls: list = []

    def get(self, url, headers=None, timeout=None):
        u = urlsplit(url)
        assert u.path.startswith("/api2/v2/chats/") and u.path.endswith("/messages"), url
        self.calls.append({k: v[0] for k, v in parse_qs(u.query).items()})
        return _Resp(url, {"list": [], "hasMore": False})


def _client() -> OFClient:
    c = OFClient({"headers": {"user_id": A, "x_bc": "bc", "x_of_rev": "rev", "user_agent": "ua"},
                  "signing": {"rules": {"static_param": "s", "start": "1", "end": "2",
                                        "checksum_indexes": [1], "checksum_constant": 1}},
                  "cookies": []})
    c._x_hash = "h"
    c.http = _Wire()
    return c


@contextlib.contextmanager
def _world():
    saved = {k: os.environ.get(k) for k in ("SHARED_REFRESHER", "UNREAD_TOTAL", "BADGE_READS")}
    os.environ.update(SHARED_REFRESHER="1", UNREAD_TOTAL="1")
    os.environ.pop("BADGE_READS", None)
    lines: list = []

    class _Cap(logging.Handler):
        def emit(self, rec):
            msg = rec.getMessage()
            if msg.startswith(("badge_unpeeked_drop ", "badge_grey ")):
                lines.append(msg)
    cap = _Cap()
    loggers = [logging.getLogger(n) for n in ("of-relay.badge_watch", "of-relay.unread_total")]
    for lg in loggers:
        lg.addHandler(cap)
    for m in (shared_refresher, unread_total, badge_reads, badge_watch):
        importlib.reload(m)
    t = [1000.0]
    badge_watch._mono = lambda: t[0]
    up = time.monotonic()
    orig = (of_ws.connected_since, events.open_tab_accounts)
    of_ws.connected_since = lambda aid: up
    events.open_tab_accounts = lambda: frozenset()
    try:
        yield _client(), t, lines
    finally:
        for lg in loggers:
            lg.removeHandler(cap)
        of_ws.connected_since, events.open_tab_accounts = orig
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for m in (shared_refresher, unread_total, badge_reads, badge_watch):
            importlib.reload(m)


async def _frame(n: int) -> None:
    await events.handle_event({"__account_id": A, "chat_messages": n, "count_priority_chat": 0,
                               "count_call_request_chat": 0, "unread_tips": 0})


async def _echo(fan: int, mid: int) -> None:
    await events.handle_event({"__account_id": A, "api2_chat_message": {
        "id": mid, "text": "on it", "chatUserId": fan,
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds")}})


def _read(client, caller: str, fan: int = F, **kw) -> None:
    with of_call_counter.caller(caller):
        client.get_messages(fan, **kw)


def _drops(lines) -> list:
    return [x for x in lines if x.startswith("badge_unpeeked_drop ")]


async def case_background_unpeeked_drop_logs_once():
    with _world() as (client, t, lines):
        await _frame(5)
        _read(client, SCRAPE)
        assert "id" not in client.http.calls[-1], client.http.calls
        t[0] += 1.0
        await _frame(4)
        assert _drops(lines) == [f"badge_unpeeked_drop account={A} chat={F} caller={SCRAPE} gap_ms=1000"], lines


async def case_explained_drop_logs_too():
    with _world() as (client, t, lines):
        await _frame(5)
        _read(client, SCRAPE)
        t[0] += 0.8
        await _echo(F, 77)
        t[0] += 0.2
        await _frame(4)
        assert _drops(lines) == [f"badge_unpeeked_drop account={A} chat={F} caller={SCRAPE} gap_ms=1000"], lines


async def case_no_line():
    legs = (("Peek cursor", SCRAPE, {"peek": True}, 1.0, 4),
            ("thread route caller", THREAD_ROUTE, {}, 1.0, 4),
            ("drop 3 s later", SCRAPE, {}, 3.0, 4),
            ("counter rise", SCRAPE, {}, 1.0, 6),
            ("older page", SCRAPE, {"before_id": 123}, 1.0, 4))
    for name, caller, kw, gap, n in legs:
        with _world() as (client, t, lines):
            await _frame(5)
            _read(client, caller, **kw)
            t[0] += gap
            await _frame(n)
            assert _drops(lines) == [], (name, lines)


async def case_slot_keeps_8_newest():
    with _world() as (client, t, lines):
        for i in range(20):
            _read(client, SCRAPE, fan=F + i)
            t[0] += 0.01
        slot = badge_watch._slots[A]
        assert len(slot) == 8 and [e[0] for e in slot] == [str(F + i) for i in range(12, 20)], list(slot)
        await _frame(5)
        await _frame(4)
        assert _drops(lines) == [f"badge_unpeeked_drop account={A} chat={F + 19} caller={SCRAPE} gap_ms=10"], lines


async def case_grey_on_off():
    with _world() as (_client, _t, lines):
        now = int(time.time() * 1000)
        unread_total.observe_counter(A, 3, now)
        unread_total.set_restricted_unread(A, Restricted(0, False, 0), now)
        assert lines == [f"badge_grey account={A} state=on reason=r_unknown",
                         f"badge_grey account={A} state=off reason=r_unknown"], lines
        lines.clear()
        unread_total.set_grey_cause(A, "dead")
        unread_total.set_grey_cause(A, None)
        unread_total.snapshot(A)
        assert lines == [f"badge_grey account={A} state=on reason=dead",
                         f"badge_grey account={A} state=off reason=dead"], lines

async def case_no_unread_total_platform_never_greys():
    with _world() as (_client, _t, lines), contextlib.ExitStack() as stack:
        stack.callback(setattr, account_registry, "get_platform", account_registry.get_platform)
        account_registry.get_platform = lambda aid: "fansly"
        now = int(time.time() * 1000)
        unread_total.set_grey_cause(A, "dead")
        unread_total.set_amber(A, 2, now)
        unread_total.observe_counter(A, 3, now)
        unread_total.set_restricted_unread(A, Restricted(0, False, 0), now)
        unread_total.set_grey_cause(A, None)
        unread_total.on_tick(A)
        assert lines == [] and unread_total.snapshot(A) is None, lines
        assert unread_total.badge_versions(frozenset({A})) == {}, "no badge state moved"
        assert not unread_total.restricted_unknown(A), "no seed read for a platform without the total"


_harness.run()
