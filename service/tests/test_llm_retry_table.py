#!/usr/bin/env python3
import _harness  # MUST be first: binds temp DB

import llm_client  # noqa: E402
from llm_client import Fail, KeyErr, Retry, llm_attempt_outcome  # noqa: E402

N = llm_client._LLM_MAX_ATTEMPTS
B = llm_client._LLM_RETRY_BACKOFF_S
FIRST, MID, LAST = 0, 1, N - 1

_TABLE = [
    ("ReadTimeout",    FIRST, Retry(B * 1)),
    ("ReadTimeout",    MID,   Retry(B * 2)),
    ("ReadTimeout",    LAST,  Fail("attempts_exhausted")),
    ("ConnectError",   FIRST, Retry(B * 1)),
    ("ConnectError",   LAST,  Fail("attempts_exhausted")),
    ("ValueError",     FIRST, Retry(B * 1)),
    ("ValueError",     LAST,  Fail("attempts_exhausted")),
    (429,              FIRST, Retry(B * 1)),
    (429,              LAST,  Fail("attempts_exhausted")),
    (500,              FIRST, Retry(B * 1)),
    (500,              LAST,  Fail("attempts_exhausted")),
    (502,              FIRST, Retry(B * 1)),
    (503,              FIRST, Retry(B * 1)),
    (503,              LAST,  Fail("attempts_exhausted")),
    (504,              FIRST, Retry(B * 1)),
    (401,              FIRST, KeyErr("invalid")),
    (401,              LAST,  KeyErr("invalid")),
    (403,              FIRST, KeyErr("invalid")),
    (402,              FIRST, KeyErr("no_credit")),
    (400,              FIRST, Fail("not_retryable")),
    (404,              FIRST, Fail("not_retryable")),
    (422,              FIRST, Fail("not_retryable")),
    (501,              FIRST, Fail("not_retryable")),
]


def case_table():
    assert N == 3, f"table assumes 3 attempts, got {N}"
    bad = []
    for arg, attempt, want in _TABLE:
        got = llm_attempt_outcome(arg, attempt, N)
        if got != want:
            bad.append(f"{arg!r} @attempt {attempt}: want {want}, got {got}")
    assert not bad, "\n  ".join(["mismatches:"] + bad)


def case_key_kinds_match_key_status():
    for status, kind in llm_client._KEY_STATUS.items():
        assert kind in {"invalid", "no_credit"}, (status, kind)
        assert llm_attempt_outcome(status, FIRST, N) == KeyErr(kind), status
        assert status not in llm_client._RETRYABLE_STATUS, status


def case_single_attempt_never_retries():
    assert llm_attempt_outcome("ReadTimeout", 0, 1) == Fail("attempts_exhausted")
    assert llm_attempt_outcome(503, 0, 1) == Fail("attempts_exhausted")


def case_backoff_read_at_call_time():
    orig = llm_client._LLM_RETRY_BACKOFF_S
    try:
        llm_client._LLM_RETRY_BACKOFF_S = 7.0
        assert llm_attempt_outcome(503, MID, N) == Retry(14.0)
        llm_client._LLM_RETRY_BACKOFF_S = 0
        assert llm_attempt_outcome("ReadTimeout", FIRST, N) == Retry(0)
    finally:
        llm_client._LLM_RETRY_BACKOFF_S = orig
    assert llm_attempt_outcome(503, FIRST, N) == Retry(orig)


def case_non_object_200_body_fails_cleanly():
    import asyncio

    class _Resp:
        def __init__(self, data): self.data = data
        def raise_for_status(self): pass
        def json(self): return self.data

    class _Client:
        def __init__(self, data): self.data = data
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): return _Resp(self.data)

    class _Hold:
        provider, refunds = "deepseek", 0
        async def refund(self): self.refunds += 1

    orig = llm_client.httpx.AsyncClient
    try:
        for data in ("garbage", [1, 2], None, 7):
            llm_client.httpx.AsyncClient = lambda *a, _d=data, **k: _Client(_d)
            hold = _Hold()
            try:
                asyncio.run(llm_client._fire("http://x", {}, {}, call_id=None, hold=hold, model=next(iter(llm_client.MODELS)),
                                             purpose="p", max_attempts=1))
            except llm_client.LLMHTTPError as e:
                assert "not an object" in str(e), e
            else:
                raise AssertionError(f"{data!r}: no error")
            assert hold.refunds == 1, data
    finally:
        llm_client.httpx.AsyncClient = orig


_harness.run()
