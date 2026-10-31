#!/usr/bin/env python3
"""W14 — llm_attempt_outcome: the pure retry/give-up decision behind chat().

One failed attempt in, one verdict out — Retry(pause) / KeyErr(kind) / Fail.
A table, so the rule is visible at a glance and no network is needed:

  - timeouts / transport errors / non-JSON body, 429 and 5xx retry on every
    attempt but the last, where they fail;
  - 401/403 → KeyErr("invalid"), 402 → KeyErr("no_credit") (the kinds
    LLMKeyError / key_error_payload know), never retried;
  - any other 4xx fails on the first try;
  - the pause is _LLM_RETRY_BACKOFF_S × (attempt+1), read when called.

Run: ./venv/bin/python service/tests/test_llm_retry_table.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

import llm_client  # noqa: E402
from llm_client import Fail, KeyErr, Retry, llm_attempt_outcome  # noqa: E402

N = llm_client._LLM_MAX_ATTEMPTS
B = llm_client._LLM_RETRY_BACKOFF_S
FIRST, MID, LAST = 0, 1, N - 1

# (status or exc kind, attempt, expected). The str kinds are illustrative:
# llm_attempt_outcome treats ANY str as a transient request-side fault.
_TABLE = [
    ("ReadTimeout",    FIRST, Retry(B * 1)),
    ("ReadTimeout",    MID,   Retry(B * 2)),
    ("ReadTimeout",    LAST,  Fail("attempts_exhausted")),
    ("ConnectError",   FIRST, Retry(B * 1)),
    ("ConnectError",   LAST,  Fail("attempts_exhausted")),
    ("ValueError",     FIRST, Retry(B * 1)),      # resp.json() on a non-JSON body
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
    (501,              FIRST, Fail("not_retryable")),  # 5xx outside _RETRYABLE_STATUS
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
    # Every KeyErr kind is one LLMKeyError documents for a provider refusal
    # ("missing" is client-side, never a status).
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


_harness.run()
