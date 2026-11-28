#!/usr/bin/env python3
import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import struct  # noqa: E402
import zlib  # noqa: E402
from contextlib import contextmanager  # noqa: E402

import httpx  # noqa: E402

import leak_tracker_api  # noqa: E402

from test_leak_tracker_api import (  # noqa: E402
    CHATTER_A, CREATOR, EMP_A, ERR_401, FANSLY, IDS, KEY_1, MIA_W, OWNER_A, ROWAN_W, SCOPED, SECOND, TRACKER, _connect, _golden, _live,
    _setup, _tracker, _watches,
)
from test_leak_tracker_leaks import CREATOR_LEAKS, LEAKS, MIA_LEAKS, TEAM_LEADER, _all, _drill, _enrol_two, _gets  # noqa: E402


def _png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\x00")) + chunk(b"IEND", b""))


PNG = _png()
PREVIEW_ONLY = _golden("leaks_preview_only")
MEDIA = next(x for x in CREATOR_LEAKS["response"]["leaks"] if x["preview"])
LEAK_ID = MEDIA["leak_id"]
UPSTREAM = f"/v1/creators/{MIA_W}/leaks/{LEAK_ID}/thumb"
THUMB = {"method": "GET", "path": UPSTREAM, "status": 200, "raw": PNG, "headers": {"content-type": "image/png"}}
CLOSED = ("private, no-store", "nosniff")


@contextmanager
def _previews(value: str | None):
    saved = os.environ.get("LEAK_TRACKER_PREVIEWS")
    if value is None:
        os.environ.pop("LEAK_TRACKER_PREVIEWS", None)
    else:
        os.environ["LEAK_TRACKER_PREVIEWS"] = value
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("LEAK_TRACKER_PREVIEWS", None)
        else:
            os.environ["LEAK_TRACKER_PREVIEWS"] = saved


def _thumb(account: str = CREATOR, leak_id: str = LEAK_ID, client=OWNER_A, params: dict | None = None):
    return client.get(f"/admin/leaks/watches/{account}/leaks/{leak_id}/thumb", params=params)


def _closed(r) -> tuple[str | None, str | None]:
    return r.headers.get("cache-control"), r.headers.get("x-content-type-options")


def _thumbs(t) -> list:
    return [c for c in t.calls if c.url.path.endswith("/thumb")]


def _no_streams() -> None:
    assert sum(leak_tracker_api._thumbs.values()) == 0, leak_tracker_api._thumbs


def case_switch_unset_streams_the_thumb_and_off_hides_it_with_no_call():
    for value in (None, ""):
        _connect()
        with _tracker() as t, _live({}), _previews(value):
            _enrol_two(t)
            t.routes[UPSTREAM] = THUMB
            r = _thumb()
            assert (r.status_code, r.headers["content-type"], r.content) == (200, "image/png", PNG), (value, r.text)
            assert _closed(r) == CLOSED, r.headers
            assert len(_thumbs(t)) == 1
            assert _setup()["previews"] is True
    for value in ("0", "off", "false"):
        _connect()
        with _tracker() as t, _live({}), _previews(value):
            _enrol_two(t)
            t.routes[UPSTREAM] = THUMB
            t.routes[MIA_LEAKS] = CREATOR_LEAKS
            t.routes["/v1/leaks"] = {**LEAKS, "path": "/v1/leaks"}
            r = _thumb()
            strip = OWNER_A.get("/admin/leaks/all", params={"preview": 1})
            drill = _drill().json()
            listed = _all()
            setup = _setup()
            assert not _thumbs(t), value
        assert (r.status_code, r.json(), _closed(r)) == (404, {"detail": "Not Found"}, CLOSED), r.text
        assert setup["previews"] is False, setup
        assert (strip.status_code, strip.json()) == (404, {"detail": "Not Found"}), strip.text
        assert drill["leaks"] and all(x["preview"] is None for x in drill["leaks"]), drill["leaks"]
        assert listed["leaks"] and all(x["preview"] is None for x in listed["leaks"]), listed["leaks"]


def case_the_drill_in_passes_the_preview_through_with_the_switch_on():
    _connect()
    with _tracker() as t, _live({}), _previews(None):
        _enrol_two(t)
        t.routes[MIA_LEAKS] = CREATOR_LEAKS
        body = _drill().json()
    assert [x["preview"] for x in body["leaks"]] == [x["preview"] for x in CREATOR_LEAKS["response"]["leaks"]], body
    assert next(x for x in body["leaks"] if x["leak_id"] == LEAK_ID)["preview"] == MEDIA["preview"]


def case_the_google_view_reads_preview_only_pages_with_no_detail_calls():
    _connect()
    with _tracker() as t, _live({}), _previews(None):
        _enrol_two(t)
        t.routes["/v1/leaks"] = {**PREVIEW_ONLY, "path": "/v1/leaks",
                                 "response": {**PREVIEW_ONLY["response"], "next_cursor": "c2"}}
        calls = len(t.calls)
        first = OWNER_A.get(f"/admin/leaks/watches/{CREATOR}", params={"preview": 1})
        second = OWNER_A.get(f"/admin/leaks/watches/{CREATOR}", params={"preview": 1, "cursor": "c2"})
        urls = [str(c.url) for c in t.calls[calls:]]
    assert first.status_code == 200 and second.status_code == 200, (first.text, second.text)
    q1, q2 = (httpx.URL(u).params for u in urls)
    assert [httpx.URL(u).path for u in urls] == ["/v1/leaks", "/v1/leaks"], urls
    assert (q1.get_list("watch_id"), q1.get("preview_only"), q1.get("limit"), q1.get("cursor")) == ([MIA_W], "1", "100", None)
    assert (q2.get("preview_only"), q2.get("cursor")) == ("1", "c2"), q2
    body = first.json()
    (leak,) = body["leaks"]
    assert (leak["leak_id"], leak["preview"], leak["events"], body["next_cursor"]) == (LEAK_ID, MEDIA["preview"], [], "c2")
    assert "watch_id" not in leak and body["lanes"] is None and body["offer"] is None, body
    with _tracker() as t, _live({}), _previews("off"):
        r = OWNER_A.get(f"/admin/leaks/watches/{CREATOR}", params={"preview": 1})
        assert not t.calls
    assert (r.status_code, r.json()) == (404, {"detail": "Not Found"}), r.text


def case_a_chatter_another_agency_a_missing_grant_or_watch_gets_404_before_egress():
    _connect({**TEAM_LEADER, "assignments": {**TEAM_LEADER["assignments"], str(EMP_A): "creator"}})
    with _tracker() as t, _live({}), _previews(None):
        _enrol_two(t)
        t.routes[UPSTREAM] = THUMB
        calls = len(t.calls)
        refused = {
            "creator role": _thumb(client=CHATTER_A),
            "creator of another agency": _thumb(IDS["creator_b"]),
            "missing grant": _thumb(SECOND, client=SCOPED),
            "untracked": _thumb(FANSLY),
            "bad leak id": _thumb(leak_id="lk_0005..x"),
        }
        assert len(t.calls) == calls, [str(c.url) for c in t.calls[calls:]]
        assert _thumb(client=SCOPED).status_code == 200
    for label, r in refused.items():
        assert (r.status_code, _closed(r)) == (404, CLOSED), (label, r.status_code, r.text)


def case_a_caller_url_is_ignored_and_the_outbound_request_carries_only_bearer():
    _connect()
    with _tracker() as t, _live({}), _previews(None):
        _enrol_two(t)
        t.routes[UPSTREAM] = THUMB
        r = _thumb(params={"u": "https://evil.example/x.png", "url": "https://evil.example/y.png"})
        (call,) = _thumbs(t)
    assert r.status_code == 200, r.text
    assert (str(call.url), call.method) == (TRACKER + UPSTREAM, "GET"), call.url
    assert call.headers["authorization"] == f"Bearer {KEY_1}"
    assert set(call.headers) <= {"host", "authorization", "accept-encoding", "connection"}, dict(call.headers)
    assert call.headers["accept-encoding"] == "identity"


def case_a_non_image_answer_is_404_and_every_status_is_no_store_nosniff():
    for label, answer in [
        ("html", {**THUMB, "raw": b"<html>hi</html>", "headers": {"content-type": "text/html"}}),
        ("svg", {**THUMB, "raw": b"<svg/>", "headers": {"content-type": "image/svg+xml"}}),
        ("no type", {**THUMB, "headers": {}}),
        ("too big", {**THUMB, "headers": {"content-type": "image/png", "content-length": str(3 * 1024 * 1024 + 1)}}),
        ("redirect", {**THUMB, "status": 302, "headers": {"location": "https://evil.example/a.png"}}),
        ("404", {**THUMB, "status": 404, "raw": b'{"error":"not_found"}', "headers": {"content-type": "application/json"}}),
        ("down", httpx.ConnectError("refused")),
    ]:
        _connect()
        with _tracker() as t, _live({}), _previews(None):
            _enrol_two(t)
            t.routes[UPSTREAM] = answer
            r = _thumb()
            assert len(_thumbs(t)) == 1, label
            _no_streams()
        assert (r.status_code, r.json(), _closed(r)) == (404, {"detail": "Not Found"}, CLOSED), (label, r.text)
    for value, ctype in (("image/jpeg", "image/jpeg"), ("image/webp; q=1", "image/webp"), ("IMAGE/GIF", "image/gif")):
        _connect()
        with _tracker() as t, _live({}), _previews(None):
            _enrol_two(t)
            t.routes[UPSTREAM] = {**THUMB, "headers": {"content-type": value}}
            r = _thumb()
        assert (r.status_code, r.headers["content-type"], _closed(r)) == (200, ctype, CLOSED), (value, r.headers)


def case_an_upstream_429_is_429_and_more_than_the_agency_cap_is_429_with_no_call():
    _connect()
    with _tracker() as t, _live({}), _previews(None):
        _enrol_two(t)
        t.routes[UPSTREAM] = {**THUMB, "status": 429, "raw": b'{"error":"rate_limited"}',
                              "headers": {"content-type": "application/json"}}
        limited = _thumb()
        t.routes[UPSTREAM] = THUMB
        served = _thumb()
        _no_streams()
        agency = IDS["agency_a_owner"]
        leak_tracker_api._thumbs[agency] = leak_tracker_api.THUMBS_MAX
        try:
            calls = len(t.calls)
            over = _thumb()
            assert len(t.calls) == calls
        finally:
            leak_tracker_api._thumbs[agency] = 0
    assert (limited.status_code, _closed(limited)) == (429, CLOSED), limited.text
    assert served.status_code == 200
    assert (over.status_code, over.json(), _closed(over)) == (429, {"detail": "Too Many Requests"}, CLOSED), over.text


def case_a_stream_with_no_length_stops_at_3_mib():
    async def endless():
        for _ in range(64):
            yield b"x" * (64 * 1024)

    _connect()
    with _tracker() as t, _live({}), _previews(None):
        _enrol_two(t)
        t.routes[UPSTREAM] = {**THUMB, "raw": endless()}
        r = _thumb()
        _no_streams()
    assert r.status_code == 200 and "content-length" not in r.headers, r.headers
    assert len(r.content) <= leak_tracker_api.THUMB_MAX, len(r.content)


def case_the_thumb_stream_stops_at_its_deadline():
    async def stalls():
        yield b"x" * leak_tracker_api.CHUNK
        await asyncio.Event().wait()

    _connect()
    saved = leak_tracker_api.THUMB_FOR_S
    leak_tracker_api.THUMB_FOR_S = 0.25
    try:
        with _tracker() as t, _live({}), _previews(None):
            _enrol_two(t)
            t.routes[UPSTREAM] = {**THUMB, "raw": stalls()}
            r = _thumb()
            _no_streams()
    finally:
        leak_tracker_api.THUMB_FOR_S = saved
    assert (r.status_code, r.content) == (200, b"x" * leak_tracker_api.CHUNK), (r.status_code, len(r.content))


def case_an_upstream_401_marks_the_key_invalid_and_a_410_drops_the_watch_both_404():
    _connect()
    with _tracker() as t, _live({}), _previews(None):
        _enrol_two(t)
        t.routes[UPSTREAM] = {**THUMB, "status": 401, "raw": json.dumps(ERR_401["response"]).encode(),
                              "headers": {"content-type": "application/json"}}
        r = _thumb()
        key = _setup()["key"]
        calls = len(_thumbs(t))
        again = _thumb()
        assert len(_thumbs(t)) == calls, "a known-invalid key makes no call"
        _no_streams()
    assert (r.status_code, _closed(r), key, again.status_code) == (404, CLOSED, "invalid", 404), (r.text, key)
    _connect()
    with _tracker() as t, _live({}), _previews(None):
        _enrol_two(t)
        t.routes[UPSTREAM] = {**THUMB, "status": 410, "raw": b'{"error":"watch_deleted"}',
                              "headers": {"content-type": "application/json"}}
        r = _thumb()
        _no_streams()
    assert (r.status_code, _closed(r)) == (404, CLOSED), r.text
    assert MIA_W not in [w.watch_id for w in _watches()], "a 410 drops the local watch"

    async def broken():
        yield b'{"error":'
        raise httpx.ReadError("cut")

    _connect()
    with _tracker() as t, _live({}), _previews(None):
        _enrol_two(t)
        t.routes[UPSTREAM] = {**THUMB, "status": 410, "raw": broken(), "headers": {"content-type": "application/json"}}
        r = _thumb()
        _no_streams()
    assert (r.status_code, _closed(r)) == (404, CLOSED), r.text
    assert MIA_W in [w.watch_id for w in _watches()], "an unreadable 410 keeps the watch"


def case_the_strip_sends_only_granted_watches_with_preview_only_and_limit_12():
    _connect(TEAM_LEADER)
    with _tracker() as t, _live({}), _previews(None):
        _enrol_two(t)
        t.routes["/v1/leaks"] = {**PREVIEW_ONLY, "path": "/v1/leaks"}
        body = OWNER_A.get("/admin/leaks/all", params={"preview": 1})
        scoped = SCOPED.get("/admin/leaks/all", params={"preview": 1})
        urls = _gets(t)
        paged = OWNER_A.get("/admin/leaks/all", params={"preview": 1, "cursor": "c2"})
        assert _gets(t) == urls, "preview plus cursor makes no call"
    assert paged.status_code == 422, paged.text
    assert body.status_code == 200 and scoped.status_code == 200, (body.text, scoped.text)
    owner_q, scoped_q = (httpx.URL(u).params for u in urls)
    assert owner_q.get_list("watch_id") == sorted([MIA_W, ROWAN_W]), owner_q
    assert (scoped_q.get_list("watch_id"), scoped_q.get("preview_only"), scoped_q.get("limit")) == ([MIA_W], "1", "12")
    assert TRACKER + PREVIEW_ONLY["path"] in urls, urls
    (leak,) = scoped.json()["leaks"]
    assert (leak["leak_id"], leak["account_id"], leak["preview"]) == (LEAK_ID, CREATOR, MEDIA["preview"]), leak
    assert "watch_id" not in leak and scoped.json()["next_cursor"] is None


def case_no_log_line_holds_a_key_url_or_handle():
    lines: list[str] = []

    class Grab(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.name.startswith("of-relay"):
                lines.append(record.getMessage())

    grab = Grab(level=logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(grab)
    level, root.level = root.level, logging.DEBUG
    try:
        _connect()
        with _tracker() as t, _live({}), _previews(None):
            _enrol_two(t)
            for answer in (THUMB, {**THUMB, "headers": {"content-type": "text/html"}}, httpx.ConnectError("x")):
                t.routes[UPSTREAM] = answer
                _thumb()
    finally:
        root.removeHandler(grab)
        root.setLevel(level)
    thumb_lines = [x for x in lines if "thumb" in x]
    assert thumb_lines, lines
    for line in lines:
        for secret in (KEY_1, TRACKER, "127.0.0.1:9", UPSTREAM, "miavale", LEAK_ID):
            assert secret not in line, (secret, line)


if __name__ == "__main__":
    _harness.run()
