#!/usr/bin/env python3
"""
of_write's rate-limit gate — table tests over is_rate_limited, _may_have_sent and the
vault carrier's retry (of_upload.materialize_to_vault), over the real exception classes.
OF's "Please allow 10 seconds" is a refusal only with a 4xx answer: a 5xx or a lost answer
echoing that text may be a message OF created, so it is never sent again.

  case_is_rate_limited_table:  mark + 400 / 429 -> True; mark + 500 / 502, mark with no
                               response, 400 without the mark, ReadTimeout -> False; the
                               composer's wrap (the real server._proxy's HTTPException
                               detail) read the same: 400 + mark True, 502 + mark and no
                               answer False.
  case_may_have_sent_table:    mark + 502 -> True; mark with no response -> True; mark + 400
                               -> False.
  case_proxy_refused_table:    a ProxyError (curl 5/56/97: before the tunnel), terminal or
                               `raise from` -> unreached, not sent; a refusal only in
                               __context__, or the text without a ProxyError -> may have sent.
  case_carrier_retry_table:    the carrier create answered mark + 502 -> raised after one
                               create (never re-posted); mark + 400 -> waited and re-posted.

Run: ./venv/bin/python service/tests/test_of_write_decide.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB before engine import)

_harness.bootstrap()

from types import SimpleNamespace  # noqa: E402

from curl_cffi import requests as curl  # noqa: E402
from curl_cffi.const import CurlECode  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import of_upload  # noqa: E402
import of_write  # noqa: E402
import server  # noqa: E402
from of_client import OFAPIError, OFClient, OFDeniedError, OFDeactivatedError  # noqa: E402

_BODY = '{"error":{"code":0,"message":"Please allow 10 seconds"}}'


def _of(status: int | None, body: str = _BODY) -> OFAPIError:
    resp = None if status is None else SimpleNamespace(status_code=status, text=body)
    return OFAPIError(f"{status} for https://onlyfans.com/api2/v2/chats/1/messages\n{body}", response=resp)


def _via_proxy(inner: Exception) -> HTTPException:
    """What the real server._proxy raises over the OF error (the composer's path)."""
    def call():
        raise inner
    try:
        server._proxy(call)
    except HTTPException as e:
        return e
    raise AssertionError("_proxy answered")


def case_is_rate_limited_table():
    rows = [
        (_of(400), True),
        (_of(429), True),
        (_of(500), False),
        (_of(502), False),
        (_of(None), False),                                    # no answer: unconfirmed
        (Exception("400 ... Please Allow 10 seconds before"), False),
        (_of(400, '{"error":{"message":"Cannot send message to this user"}}'), False),
        (curl.exceptions.ReadTimeout("Operation timed out after 30000 ms"), False),
        (_via_proxy(_of(400)), True),                          # the composer's retry keeps working
        (_via_proxy(_of(502)), False),
        (_via_proxy(_of(None)), False),                        # _proxy: no answer -> 500
    ]
    for e, want in rows:
        assert of_write.is_rate_limited(e) is want, (repr(e), want)


def case_may_have_sent_table():
    rows = [
        (_of(502), True),
        (_of(None), True),
        (_of(400), False),
        (_via_proxy(_of(400, "rejected")), False),
        (_via_proxy(_of(502, "unknown")), True),
        (_via_proxy(curl.exceptions.ProxyError("CONNECT refused")), False),
        (_via_proxy(curl.exceptions.ReadTimeout("timed out")), True),
        (_via_proxy(curl.exceptions.ConnectionError("connection dropped")), True),
        (_via_proxy(OFDeniedError("refused locally")), False),
        (_via_proxy(OFDeactivatedError("deactivated")), False),
        (_via_proxy(curl.exceptions.ConnectionError("couldn't connect", code=CurlECode.COULDNT_CONNECT)), False),
        (curl.exceptions.ConnectionError("couldn't connect", code=CurlECode.COULDNT_CONNECT), False),
        (curl.exceptions.Timeout("curl 28 in any phase"), True),
    ]
    for e, want in rows:
        assert of_write._may_have_sent(e) is want, (repr(e), want)


def _raised(make):
    """The exception `make` raises, with Python's own __context__/__cause__."""
    try:
        make()
    except Exception as e:  # noqa: BLE001 — the one we want
        return e
    raise AssertionError("no raise")


def _refused():
    raise curl.exceptions.ProxyError(_CONNECT_403)


def _after_refusal():   # a refusal caught, then the retry's own write timed out
    try:
        _refused()
    except curl.exceptions.ProxyError:
        raise curl.exceptions.ReadTimeout("Operation timed out after 30000 ms")


def _from_refusal():
    try:
        _refused()
    except curl.exceptions.ProxyError as e:
        raise RuntimeError("send failed") from e


_CONNECT_403 = "Failed to perform, curl: (56) CONNECT tunnel failed, response 403"


def case_proxy_refused_table():
    """One classifier (of_client.proxy_refused) behind of_write's send once
    (`_may_have_sent`).
    Only a ProxyError, terminal or its `raise ... from` cause, is unreached;
    an earlier refusal in `__context__` says nothing of the error that ended it."""
    from of_client import proxy_refused
    rows = [   # (exception, unreached)
        (curl.exceptions.ProxyError(_CONNECT_403), True),
        (_raised(_refused), True),
        (curl.exceptions.ProxyError("curl: (5) Could not resolve proxy: px"), True),
        (curl.exceptions.ProxyError("curl: (56) Proxy CONNECT aborted"), True),
        (curl.exceptions.ProxyError("curl: (97) Can't complete SOCKS5 connection"), True),
        (_raised(_after_refusal), False),
        (_raised(_from_refusal), True),
        (RuntimeError(_CONNECT_403), False),          # the text alone is not a ProxyError
    ]
    for e, unreached in rows:
        assert proxy_refused(e) is unreached, (repr(e), repr(e.__context__), unreached)
        assert of_write._may_have_sent(e) is (not unreached), (repr(e), repr(e.__context__))


def _carrier(fails):
    """A real OFClient (test_create_post_body's `_client()`) whose create_post raises
    `fails` in order, then returns no id: materialize_to_vault stops right after."""
    c = OFClient.__new__(OFClient)
    c.creates, fails = 0, list(fails)

    def create_post(*a, **kw):
        c.creates += 1
        if fails:
            raise fails.pop(0)
        return {"id": None}
    c.create_post = create_post
    return c


def case_carrier_retry_table():
    gap = of_upload._CARRIER_MIN_GAP_S
    of_upload._CARRIER_MIN_GAP_S = 0
    try:
        rows = [   # (create answers, creates, raised text contains)
            ([_of(502)], 1, "502 for"),
            ([_of(400)], 2, "returned no id"),
        ]
        for fails, creates, raised in rows:
            c = _carrier(fails)
            try:
                c.materialize_to_vault([{"processId": "x"}])
            except OFAPIError as e:
                got = str(e)
            else:
                got = ""
            assert c.creates == creates and raised in got, (fails, c.creates, got)
    finally:
        of_upload._CARRIER_MIN_GAP_S = gap


_harness.run()
