#!/usr/bin/env python3
"""P4 PRE — the two one-time prerequisites for the P4 automation wave.

A. llm_client cost accounting after migration 0026:
   - grok_daily_cost PK is (day, account_id, provider): the atomic ON CONFLICT
     reservation must target all three, so providers roll up independently and
     the reserve no longer raises on a PK/conflict-target mismatch.
   - grok_calls now records provider + status (+ cache_hit_tokens) directly.

B. The automation registry seam: P4 automations self-register via @register so
   each lives in its own file (no shared-dict merge collision), and run_once
   dispatches through the registry.

Run: ./venv/bin/python service/tests/test_p4_pre.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

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
    """grok_daily_cost.account_id FKs accounts.id — the parent must exist."""
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


# ── A. llm_client reserve / provider accounting ──────────────────────────

async def case_reserve_is_provider_keyed():
    """Two providers, same (day, account) → two independent rows. Before the fix
    this raised (ON CONFLICT target didn't match the new 3-col PK)."""
    acct = "acc_provider_split"
    await _seed_account(acct)
    await _reserve(_DAY, acct, 10, 100, _NOW, "grok")
    await _reserve(_DAY, acct, 5, 100, _NOW, "deepseek")

    rows = {r.provider: r for r in await _daily_rows(acct)}
    assert set(rows) == {"grok", "deepseek"}, f"expected per-provider rows, got {set(rows)}"
    assert rows["grok"].cost_cents == 10, rows["grok"].cost_cents
    assert rows["deepseek"].cost_cents == 5, rows["deepseek"].cost_cents


async def case_reserve_increments_same_provider():
    """Two reserves on the SAME (day, account, provider) sum into one row."""
    acct = "acc_increment"
    await _seed_account(acct)
    await _reserve(_DAY, acct, 7, 100, _NOW, "grok")
    total = await _reserve(_DAY, acct, 8, 100, _NOW, "grok")
    rows = await _daily_rows(acct)
    assert len(rows) == 1, f"expected one grok row, got {len(rows)}"
    assert rows[0].cost_cents == 15 and total == 15, (rows[0].cost_cents, total)
    assert rows[0].call_count == 2, rows[0].call_count


async def case_cap_is_enforced_per_provider():
    """A reserve that would breach the cap raises and does NOT bump the row; a
    different provider under the same account is unaffected (independent cap)."""
    acct = "acc_capped"
    await _seed_account(acct)
    await _reserve(_DAY, acct, 60, 100, _NOW, "grok")  # fits: 60 <= 100
    raised = False
    try:
        await _reserve(_DAY, acct, 60, 100, _NOW, "grok")  # 120 > 100 → capped
    except LLMCapExceeded:
        raised = True
    assert raised, "expected LLMCapExceeded on the over-cap grok reserve"

    # deepseek is a separate rollup row → its own headroom.
    await _reserve(_DAY, acct, 60, 100, _NOW, "deepseek")

    rows = {r.provider: r.cost_cents for r in await _daily_rows(acct)}
    assert rows["grok"] == 60, f"grok must stay at 60 after the capped bump, got {rows['grok']}"
    assert rows["deepseek"] == 60, rows.get("deepseek")


async def case_grok_call_records_provider_and_status():
    """The audit row is written with provider + status='pending', then finalized
    to status='done' with cache_hit_tokens — no response_json stand-in."""
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


# ── B. Automation registry seam ──────────────────────────────────────────

def case_scrape_chats_self_registered():
    """Importing automation_executor registers the reference automation via the
    @register decorator (no central dict)."""
    assert get_automation("scrape_chats") is not None, "scrape_chats not registered"
    assert "scrape_chats" in registered_kinds()


def case_load_plugins_is_idempotent():
    """Auto-loading the (currently empty) plugins package twice is a safe no-op."""
    load_automation_plugins()
    load_automation_plugins()  # second call must not raise / re-import


# A dummy P4-style automation registered the same way a real plugin would be.
_dummy_calls: list[dict] = []


@register("p4pre_dummy")
async def _dummy_automation(account_id: str, payload: dict, *, run_id: int) -> dict:
    _dummy_calls.append({"account_id": account_id, "payload": payload, "run_id": run_id})
    return {"handled": payload.get("x")}


async def case_register_and_dispatch():
    """run_once dispatches to a registered automation and writes its stats."""
    _dummy_calls.clear()
    res = await run_once("acc_dispatch", "p4pre_dummy", payload={"x": 5})
    assert res["status"] == "ok", res
    assert res.get("handled") == 5, res
    assert len(_dummy_calls) == 1, _dummy_calls
    assert _dummy_calls[0]["payload"] == {"x": 5}


def case_every_registered_kind_is_executor_callable():
    """THE registry-wide reachability check: every LIVE kind must resolve to a
    coroutine `run_once` can actually call.

    The executor invokes `fn(account_id, payload, run_id=...)`. A `@register`
    decorator that slips onto the wrong function inside a large engine file is
    INVISIBLE to that engine's own suite whenever its cases call
    `<engine>.run(...)` directly instead of going through `run_once` — all 268
    of ai_chatter's cases passed green while `@register("ai_chatter")` sat on
    `_select_candidates` and every executor-driven run raised TypeError. Only
    two unrelated suites caught it, neither of which names ai_chatter.

    Walking the registry closes that for every engine at once, in the suite
    that owns the seam. It cannot tell you the kind points at the RIGHT
    function — an engine that cares should also assert
    `get_automation("<kind>") is <mod>.run` in its own file — but it does tell
    you the kind points at something the executor can reach.
    """
    import inspect
    load_automation_plugins()
    kinds = registered_kinds()
    # Guard against a vacuous pass: if the plugin walk silently failed, the
    # registry would hold only the reference automation and the dummy below,
    # and the loop would assert nothing about the real engines.
    assert len(kinds) >= 10, f"automation plugins did not load: {kinds}"
    # ...and against the PER-ENGINE vacuous pass, which the count above cannot
    # see: `load_automation_plugins` catches a per-module import error, records
    # the basename, and continues (automation_registry.py:126-134). A crashed
    # engine is therefore simply ABSENT from `registered_kinds()` — the loop
    # below walks the survivors and goes green. "Its module did not import" is
    # one of the ways an engine is unreachable from the executor, which is what
    # this case is named for, and the registry already exports the accessor.
    assert not failed_plugins(), (
        f"automation modules crashed on import: {sorted(failed_plugins())}")
    for kind in kinds:
        fn = get_automation(kind)
        assert callable(fn), f"kind {kind!r} maps to {fn!r}, not a callable"
        # `automation_executor` does `await fn(...)`, so a @register that lands on
        # a SYNC helper with the right signature passes the bind below and dies
        # in production. The docstring says "coroutine"; this is the line that
        # makes that true. All live kinds already satisfy it.
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
