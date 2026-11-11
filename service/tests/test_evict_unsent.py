#!/usr/bin/env python3
"""A signed call on an evicted OFClient (client_pool.evict retires its curl
handles) never leaves the box, so it must read as unsent everywhere: before
the fix it raised a plain OFAPIError with no response, which of_write and
priority_mass read as "may have sent", parking never-sent fans UNKNOWN forever.

  case_retired_signed_send_is_unsent_and_fan_stays_pending:
      a real OFClient pinned in the pool, retired, then a priority-mass leg on
      it: the call classifies unsent and the fan stays PENDING (resent on the
      next leg's fresh client), not UNKNOWN.
  case_proxy_answers_503_for_a_retired_client:
      server._proxy maps the retired refusal to 503 + Retry-After, not the
      relay deny-list's 403 "refused".

No network: the signed call stops at retirement, before any wire I/O.

Run: ./venv/bin/python service/tests/test_evict_unsent.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402

from sqlalchemy import select  # noqa: E402

import client_pool  # noqa: E402
import of_write  # noqa: E402
from automations import priority_mass  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, PriorityMassRecipient, PriorityMassRun  # noqa: E402
from of_client import OFAPIError, OFClient, OFSessionRetired  # noqa: E402


def _retired_client(account_id: str) -> OFClient:
    client = OFClient({
        "headers": {"user_id": account_id, "x_bc": "test", "x_of_rev": "test", "user_agent": "test"},
        "signing": {"rules": {"static_param": "test", "start": "1", "end": "2",
                              "checksum_indexes": [1], "checksum_constant": 1}},
        "cookies": [],
    })
    client._x_hash = "test"  # the signed write stops at retirement, before any wire I/O
    client.close_signed_sessions()
    return client


def case_retired_signed_send_is_unsent_and_fan_stays_pending():
    account_id = "evict_unsent_acct"
    fan_id = 901234567
    client = _retired_client(account_id)
    client_pool._POOL[account_id] = client

    async def exercise():
        async with get_session() as db:
            db.add(Account(id=account_id))
            run = PriorityMassRun(
                account_id=account_id, status=priority_mass.RUNNING, text="hello",
                media_json="[]", previews_json="[]", price_cents=0, locked_text=False,
                audience_json=json.dumps({"user_lists": [], "excluded_user_lists": []}),
            )
            db.add(run)
            await db.flush()
            run_id = run.id
            db.add(PriorityMassRecipient(run_id=run_id, fan_id=fan_id,
                                         status=priority_mass.PENDING))
        try:
            client.get("/api2/v2/users/me")
        except OFAPIError as exc:
            may_have_sent = of_write._may_have_sent(exc)
        else:
            raise AssertionError("retired signed call was admitted")

        await priority_mass.run(account_id, {"run_id": run_id}, run_id=0)
        async with get_session() as db:
            recipient = (await db.execute(select(PriorityMassRecipient).where(
                PriorityMassRecipient.run_id == run_id,
                PriorityMassRecipient.fan_id == fan_id))).scalar_one()
            return may_have_sent, recipient.status

    try:
        classification, status = asyncio.run(exercise())
    finally:
        client_pool._POOL.pop(account_id, None)
        client.http.close()

    assert (classification, status) == (False, priority_mass.PENDING), (
        f"retired signed call: may_have_sent={classification}, priority_mass fan={status}"
    )


def case_proxy_answers_503_for_a_retired_client():
    from fastapi import HTTPException

    _harness.make_client()
    import server

    client = _retired_client("evict_unsent_proxy")
    try:
        try:
            server._proxy(lambda: client.get("/api2/v2/users/me"))
        except HTTPException as e:
            assert e.status_code == 503, e.status_code
            assert (e.headers or {}).get("Retry-After"), e.headers
            assert e.detail["upstream_status"] == "session_retired", e.detail
        else:
            raise AssertionError("_proxy let a retired call through")
    finally:
        client.http.close()
    assert issubclass(OFSessionRetired, of_write.OFDeniedError)


_harness.run()
