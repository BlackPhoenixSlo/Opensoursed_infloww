from __future__ import annotations

import _harness

import os  # noqa: E402
import sys  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from pathlib import Path  # noqa: E402

_harness.bootstrap()
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fansly"))

import send_ops  # noqa: E402
import send_tripwire  # noqa: E402
from fansly_shim import FanslyShimClient  # noqa: E402
from of_client import OFClient  # noqa: E402
from of_write import _may_have_sent  # noqa: E402

WIRE = ("_request", "request", "get", "post_json", "put_json", "delete_json", "_http_call", "_post_dropping_auto_cotag",
        "_group_for_send", "_fan_id_for_group", "upload_media")
SOON = "2026-12-01T00:00:00Z"
METHODS = {
    "post_message": lambda c: c.post_message(1, "https://onlyfans.com/api2/v2/chats/1/messages", {"text": "x"}, None),
    "schedule_message": lambda c: c.schedule_message(1, "x", scheduled_date=SOON),
    "schedule_mass_message": lambda c: c.schedule_mass_message(text="x", scheduled_date=SOON),
    "send_mass_message": lambda c: c.send_mass_message("x", included_users=[1]),
    "publish_schedule": lambda c: c.publish_schedule(5),
    "create_post": lambda c: c.create_post("x"),
    "create_story": lambda c: c.create_story([1]),
    "fansly.create_post": lambda c: c.create_post("x"),
    "fansly.send_mass_message": lambda c: c.send_mass_message("x", include_lists=[1], confirm_live_broadcast=True),
    "fansly.send_message": lambda c: c.send_message(1, "x"),
}


def _client(name: str):
    c = object.__new__(FanslyShimClient if name.startswith("fansly.") else OFClient)
    c.wire = []
    if name.startswith("fansly."):
        c._wall_id = "1"
        c.session = SimpleNamespace(account_id="1")
    else:
        c.account_id = "900539700124344320"
    for attr in WIRE:
        setattr(c, attr, lambda *a, _attr=attr, **k: c.wire.append(_attr) or {"id": 1})
    return c


class _Cells:
    def __init__(self, on: bool):
        self.on = on

    def __enter__(self):
        self.prev = os.environ.pop("OI_CELL_MAP", None)
        if self.on:
            os.environ["OI_CELL_MAP"] = "/nonexistent/placement.json"

    def __exit__(self, *_a):
        os.environ.pop("OI_CELL_MAP", None)
        if self.prev is not None:
            os.environ["OI_CELL_MAP"] = self.prev


def case_each_method_refuses_before_the_wire():
    failures = []
    with _Cells(True):
        for name, call in METHODS.items():
            c = _client(name)
            try:
                call(c)
            except send_tripwire.UnclaimedSend as e:
                if e.status_code != 409 or e.detail != {"error": "unclaimed_send", "method": name}:
                    failures.append((name, e.detail))
            else:
                failures.append((name, "no unclaimed_send"))
            if c.wire:
                failures.append((name, c.wire))
    assert not failures, failures


def case_a_claim_or_env_unset_lets_the_send_reach_the_wire():
    with _Cells(True):
        token = send_tripwire.claim.set(send_tripwire.Budget("op-1", send_ops.check_permit))
        try:
            c = _client("publish_schedule")
            METHODS["publish_schedule"](c)
            assert c.wire == ["put_json"], c.wire
        finally:
            send_tripwire.claim.reset(token)
    with _Cells(False):
        for name in ("publish_schedule", "post_message"):
            c = _client(name)
            METHODS[name](c)
            assert c.wire, (name, "env unset must send as main")


def case_fansly_claim_spends_one_attempt_on_deliveries_only():
    import types
    from fansly_client import FanslyClient
    c = object.__new__(FanslyClient)
    c.dry_run, c.timeout, c.wire = False, 5, []
    c._headers = lambda *a, **k: {}

    def request(method, url, **kw):
        c.wire.append((method, url.split("/api/v1")[-1]))
        return types.SimpleNamespace(status_code=200, json=lambda: {"success": True, "response": {"id": "1"}})
    c.http = types.SimpleNamespace(request=request)
    budget = send_tripwire.Budget("op-f", send_ops.check_permit)
    with _Cells(True):
        token = send_tripwire.claim.set(budget)
        try:
            c._request("POST", "/account/media", json_body={})
            c._request("POST", "/group", json_body={})
            c._request("POST", "/message", json_body={})
            try:
                c._request("POST", "/message", json_body={})
            except send_tripwire.SendBudgetSpent:
                pass
            else:
                raise AssertionError("second delivery under one claim reached the wire")
        finally:
            send_tripwire.claim.reset(token)
    assert [p for _m, p in c.wire] == ["/account/media", "/group", "/message"] and budget.sent == 1, (c.wire, budget.sent)


def case_refusal_counts_as_not_sent():
    assert _may_have_sent(send_tripwire.UnclaimedSend("post_message")) is False
    for reason in ("writes_paused", "cell_held", "not_owner", "claim_failed", "capability", "fan_held", "op_pending"):
        refusal = send_ops.SendRefused(409, reason)
        assert not _may_have_sent(refusal) and send_ops.refusal_reason(refusal) == reason


_harness.run()
