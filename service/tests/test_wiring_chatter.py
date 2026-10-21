"""test_wiring_chatter — the Settings on/off switch really turns the engine on/off.

One checkpoint chain, driven through the REAL config handlers the
tabs call and the REAL runtime gates the executor / webhook dispatch read:

  tab toggle → PUT handler → persisted key (config blob + automation_rules row)
             → `_materialize_due_rules` schedules (ON) / does not (OFF)
             → a job ALREADY queued before OFF runs and sends nothing
             → real-time webhook routing stops handing the fan to the engine.

Automation: autoreply / "Auto Convo" (AutoreplyTab → PUT /admin/autoreply-config).

Confirmed wiring bugs are `_harness.xfail(strict=True)` so the marker breaks the
moment the bug is fixed.

House style: plain assert, no pytest; _harness temp DB; config handlers called as
functions (no request principal → ALLOW_ANONYMOUS_ADMIN); FakeOF via ax._make_client so nothing reaches OF.
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"
os.environ.pop("W7_WEBHOOK_DISPATCH_DISABLED", None)

import json  # noqa: E402

from sqlalchemy import delete, select  # noqa: E402

import automation_executor as ax  # noqa: E402
import autoreply_config_api  # noqa: E402
import webhook_dispatch as wd  # noqa: E402
from automations import autoreply  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AccountAiConfig, AutomationRule, Fan, ScheduledJob,
)


# ── seams / helpers ──────────────────────────────────────────────────────────

class FakeOF:
    """Records every send; any send at all while OFF is the failure."""

    def __init__(self):
        self.sent: list = []

    def send_message(self, chat_id, text, media_files=None, price=0, **kw) -> dict:
        self.sent.append((int(chat_id), text))
        return {"id": 9_000_000_000_000 + len(self.sent), "text": text,
                "createdAt": "2026-10-17T12:00:00+00:00"}

    def __getattr__(self, name):  # any other OF call → empty, never network
        return lambda *a, **k: {"list": []}


def _use_fake() -> FakeOF:
    fake = FakeOF()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


async def _seed(aid: str, fid: int = 4242) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        if await s.get(Fan, (aid, fid)) is None:
            s.add(Fan(account_id=aid, fan_id=fid, of_display_name="Wire"))


async def _rules(aid: str, kind: str) -> list[AutomationRule]:
    async with get_session() as s:
        rows = list((await s.execute(select(AutomationRule).where(
            AutomationRule.account_id == aid, AutomationRule.kind == kind,
        ).order_by(AutomationRule.id))).scalars())
        s.expunge_all()
    return rows


async def _clear_jobs(aid: str) -> None:
    async with get_session() as s:
        await s.execute(delete(ScheduledJob).where(ScheduledJob.account_id == aid))


async def _jobs(aid: str, kind: str) -> list[ScheduledJob]:
    async with get_session() as s:
        rows = list((await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid, ScheduledJob.kind == kind,
            ScheduledJob.status == "pending"))).scalars())
        s.expunge_all()
    return rows


async def _schedules(aid: str, kind: str) -> bool:
    """Does the executor's materializer put a job on the queue for (aid, kind)?"""
    await _clear_jobs(aid)
    await ax._materialize_due_rules()
    return bool(await _jobs(aid, kind))


async def _stored(aid: str, column: str) -> dict:
    async with get_session() as s:
        row = await s.get(AccountAiConfig, aid)
    return json.loads(getattr(row, column) or "{}") if row else {}


# ── autoreply ("Auto Convo") ────────────────────────────────────────────────

async def case_autoreply_off_stops_queued_job():
    aid, fid = "wire_ar_off", 5101
    await _seed(aid, fid)
    await autoreply_config_api.put_autoreply_config(autoreply_config_api._ConfigBody(
        account_id=aid, config={"enabled": True}))
    assert await autoreply._load_config(aid) is not None
    await _clear_jobs(aid)
    await ax.enqueue_job(aid, "autoreply", payload={})

    await autoreply_config_api.put_autoreply_config(autoreply_config_api._ConfigBody(
        account_id=aid, config={"enabled": False}))
    assert (await _stored(aid, "autoreply_config_json")).get("enabled") is False
    assert await autoreply._load_config(aid) is None
    fake = _use_fake()
    res = await ax.run_once(aid, "autoreply")
    assert res.get("enabled") is False and res.get("sent") == 0 and res.get("job_id"), res
    assert fake.sent == []
    # webhook_dispatch never routes to autoreply at all (rule-tick only).
    assert await wd._classify_kind(aid, fid) != "autoreply"


async def case_autoreply_on_schedules():
    aid = "wire_ar_on"
    await _seed(aid)
    await autoreply_config_api.put_autoreply_config(autoreply_config_api._ConfigBody(
        account_id=aid, config={"enabled": True}))
    assert await autoreply._load_config(aid) is not None
    assert [r for r in await _rules(aid, "autoreply") if r.is_enabled], \
        "no enabled autoreply rule after saving Enabled"
    assert await _schedules(aid, "autoreply")


_harness.run()
