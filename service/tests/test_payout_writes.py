#!/usr/bin/env python3
"""POST and PATCH /api/of/v2/payouts/requests — OF Manager's Statements writes.

"Request withdrawal" sends OF's POST /api2/v2/payouts/requests {withdrawal_amount}
and the payout frequency select OF's PATCH /api2/v2/payouts/requests
{withdrawalPeriod}, exactly as OF's statements bundle does (app.js module 874727).
An OF refusal surfaces as the usual structured 502 with OF's body. Plain-assert,
OF faked.

  case_routes_are_registered
  case_withdrawal_passes_amount
  case_period_passes_code
  case_client_sends_ofs_requests
  case_of_refusal_is_502
  case_bad_bodies_are_rejected

Run: ./venv/bin/python service/tests/test_payout_writes.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402

import of_client  # noqa: E402
import server  # noqa: E402

# OF's answer to a withdrawal below the balance/minimum (captured live, account balance $4.40, minimum $20).
REFUSAL = '{"error":{"code":0,"message":"Not enough funds to request a payout"}}'


class _Fake:
    def __init__(self, fail=False):
        self.calls: list[tuple] = []
        self.fail = fail

    def _maybe_fail(self):
        if self.fail:
            class R:
                status_code = 400
                text = REFUSAL
            raise of_client.OFAPIError("400", response=R())

    def request_payout(self, amount):
        self.calls.append(("withdraw", amount))
        self._maybe_fail()
        return {"list": [{"state": "pending", "rejectReason": None}]}

    def update_withdrawal_period(self, code):
        self.calls.append(("period", code))
        self._maybe_fail()
        return {"success": True}


def _with(fake, fn):
    orig = server._get_client, server._resolve_account_id
    server._get_client = lambda: fake
    server._resolve_account_id = lambda _req=None: "acct-payouts"
    try:
        return fn()
    finally:
        server._get_client, server._resolve_account_id = orig


def case_routes_are_registered():
    routes = {(m, r.path) for r in server.app.routes for m in getattr(r, "methods", ())}
    for m in ("POST", "PATCH", "GET"):
        assert (m, "/api/of/v2/payouts/requests") in routes, f"{m} /api/of/v2/payouts/requests missing"


def case_withdrawal_passes_amount():
    fake = _Fake()
    out = _with(fake, lambda: server.of_request_payout(server._PayoutRequestBody(withdrawal_amount=20)))
    assert fake.calls == [("withdraw", 20)], fake.calls
    assert out["list"][0]["state"] == "pending", out


def case_period_passes_code():
    fake = _Fake()
    out = _with(fake, lambda: server.of_update_withdrawal_period(server._WithdrawalPeriodBody(withdrawalPeriod="weekly")))
    assert fake.calls == [("period", "weekly")], fake.calls
    assert out == {"success": True}, out


def case_client_sends_ofs_requests():
    c = of_client.OFClient.__new__(of_client.OFClient)
    sent = []
    c.request_json = lambda method, path, **kw: sent.append((method, path, kw)) or {"success": True}
    c.request_payout(4.4)
    c.update_withdrawal_period("manual")
    assert sent == [
        ("POST", f"{of_client.API_BASE}/payouts/requests", {"json_body": {"withdrawal_amount": 4.4}}),
        ("PATCH", f"{of_client.API_BASE}/payouts/requests", {"json_body": {"withdrawalPeriod": "manual"}}),
    ], sent


def case_of_refusal_is_502():
    try:
        _with(_Fake(fail=True), lambda: server.of_request_payout(server._PayoutRequestBody(withdrawal_amount=4.4)))
    except HTTPException as e:
        assert e.status_code == 502, e.status_code
        assert e.detail["upstream_status"] == 400, e.detail
        assert "Not enough funds to request a payout" in e.detail["upstream_body"], e.detail
    else:
        raise AssertionError("expected a 502")


def case_bad_bodies_are_rejected():
    for build in (
        lambda: server._PayoutRequestBody(withdrawal_amount=0),
        lambda: server._PayoutRequestBody(),
        lambda: server._WithdrawalPeriodBody(withdrawalPeriod=""),
    ):
        try:
            build()
        except ValidationError:
            continue
        raise AssertionError("expected a validation error")


_harness.run()
