#!/usr/bin/env python3
import _harness

_harness.bootstrap()

from datetime import datetime  # noqa: E402

from sqlalchemy import select  # noqa: E402

from db.engine import get_session  # noqa: E402
from db.models import Account, GrokCall, GrokDailyCost  # noqa: E402
from llm_client import (  # noqa: E402
    LLMCapExceeded,
    _finalize_call,
    _insert_pending_call,
    _reserve,
)
from automation_registry import (  # noqa: E402
    failed_plugins,
    get_automation,
    load_automation_plugins,
    register,
    registered_kinds,
)
import automation_executor  # noqa: E402,F401 — importing self-registers scrape_chats
from automation_executor import run_once  # noqa: E402

_DAY = "2026-06-04"
_NOW = datetime(2026, 6, 4, 12, 0, 0)


async def _seed_account(account_id: str) -> None:
    async with get_session() as s:
        if await s.get(Account, account_id) is None:
            s.add(Account(id=account_id))


async def _daily_rows(account_id: str) -> list[GrokDailyCost]:
    async with get_session() as s:
        return list(
            (
                await s.execute(
                    select(GrokDailyCost).where(GrokDailyCost.account_id == account_id)
                )
            ).scalars()
        )



async def case_reserve_is_provider_keyed():
    acct = "acc_provider_split"
    await _seed_account(acct)
    await _reserve(_DAY, acct, 10, 100, _NOW, "grok")
    await _reserve(_DAY, acct, 5, 100, _NOW, "deepseek")

    rows = {r.provider: r for r in await _daily_rows(acct)}
    assert set(rows) == {"grok", "deepseek"}, f"expected per-provider rows, got {set(rows)}"
    assert rows["grok"].cost_cents == 10, rows["grok"].cost_cents
    assert rows["deepseek"].cost_cents == 5, rows["deepseek"].cost_cents


async def case_reserve_increments_same_provider():
    acct = "acc_increment"
    await _seed_account(acct)
    await _reserve(_DAY, acct, 7, 100, _NOW, "grok")
    total = await _reserve(_DAY, acct, 8, 100, _NOW, "grok")
    rows = await _daily_rows(acct)
    assert len(rows) == 1, f"expected one grok row, got {len(rows)}"
    assert rows[0].cost_cents == 15 and total == 15, (rows[0].cost_cents, total)
    assert rows[0].call_count == 2, rows[0].call_count


async def case_cap_is_enforced_per_provider():
    acct = "acc_capped"
    await _seed_account(acct)
    await _reserve(_DAY, acct, 60, 100, _NOW, "grok")
    raised = False
    try:
        await _reserve(_DAY, acct, 60, 100, _NOW, "grok")
    except LLMCapExceeded:
        raised = True
    assert raised, "expected LLMCapExceeded on the over-cap grok reserve"

    await _reserve(_DAY, acct, 60, 100, _NOW, "deepseek")

    rows = {r.provider: r.cost_cents for r in await _daily_rows(acct)}
    assert rows["grok"] == 60, f"grok must stay at 60 after the capped bump, got {rows['grok']}"
    assert rows["deepseek"] == 60, rows.get("deepseek")


async def case_grok_call_records_provider_and_status():
    call_id = await _insert_pending_call(
        purpose="gen_info", provider="deepseek", account_id="acc_audit", fan_id=42,
        model="deepseek-v4-flash", endpoint="/chat/completions", temperature=0.7,
        request_body={"model": "deepseek-v4-flash", "messages": []}, now=_NOW,
    )
    assert call_id is not None, "pending audit row should have been written"

    async with get_session() as s:
        row = await s.get(GrokCall, call_id)
        assert row.provider == "deepseek", row.provider
        assert row.status == "pending", row.status

    await _finalize_call(
        call_id, status="done", cache_hit_tokens=7, tokens_in=100, tokens_out=20,
    )
    async with get_session() as s:
        row = await s.get(GrokCall, call_id)
        assert row.status == "done", row.status
        assert row.cache_hit_tokens == 7, row.cache_hit_tokens
        assert row.tokens_in == 100 and row.tokens_out == 20



def case_scrape_chats_self_registered():
    assert get_automation("scrape_chats") is not None, "scrape_chats not registered"
    assert "scrape_chats" in registered_kinds()


def case_load_plugins_is_idempotent():
    load_automation_plugins()
    load_automation_plugins()


_dummy_calls: list[dict] = []


@register("p4pre_dummy")
async def _dummy_automation(account_id: str, payload: dict, *, run_id: int) -> dict:
    _dummy_calls.append({"account_id": account_id, "payload": payload, "run_id": run_id})
    return {"handled": payload.get("x")}


async def case_register_and_dispatch():
    _dummy_calls.clear()
    res = await run_once("acc_dispatch", "p4pre_dummy", payload={"x": 5})
    assert res["status"] == "ok", res
    assert res.get("handled") == 5, res
    assert len(_dummy_calls) == 1, _dummy_calls
    assert _dummy_calls[0]["payload"] == {"x": 5}


def case_every_registered_kind_is_executor_callable():
    import inspect
    load_automation_plugins()
    kinds = registered_kinds()
    assert len(kinds) >= 10, f"automation plugins did not load: {kinds}"
    assert not failed_plugins(), (
        f"automation modules crashed on import: {sorted(failed_plugins())}")
    for kind in kinds:
        fn = get_automation(kind)
        assert callable(fn), f"kind {kind!r} maps to {fn!r}, not a callable"
        assert inspect.iscoroutinefunction(fn), (
            f"kind {kind!r} -> {getattr(fn, '__qualname__', fn)!r} is not a "
            f"coroutine function; the executor awaits it")
        try:
            inspect.signature(fn).bind("acct", {}, run_id=1)
        except TypeError as exc:
            raise AssertionError(
                f"kind {kind!r} -> {getattr(fn, '__qualname__', fn)!r} cannot be "
                f"called the way run_once calls it "
                f"(account_id, payload, run_id=...): {exc}") from None


_harness.run(
    case_reserve_is_provider_keyed,
    case_reserve_increments_same_provider,
    case_cap_is_enforced_per_provider,
    case_grok_call_records_provider_and_status,
    case_scrape_chats_self_registered,
    case_load_plugins_is_idempotent,
    case_register_and_dispatch,
    case_every_registered_kind_is_executor_callable,
)
