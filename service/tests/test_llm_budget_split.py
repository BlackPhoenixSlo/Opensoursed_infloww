import _harness
_harness.bootstrap()

from datetime import datetime
from sqlalchemy import select
import llm_client as llm
from db.engine import get_session
from db.models import Account, AccountAiConfig, GrokDailyCost

async def case_split():
    aid = 'split-budget'
    async with get_session() as s:
        s.add(Account(id=aid))
        await s.flush()
        s.add(AccountAiConfig(account_id=aid, daily_cost_cap_cents=100))
    hold = await llm.reserve_external(aid, 'deepinfra', 'qwen3-vl-30b', 10000,
                                      purpose='describe_media', request={})
    await hold.done(10000, tokens_in=1, ok=True, latency_ms=1)
    try:
        await llm.reserve_external(aid, 'typesafe', 'jev', 1,
                                  purpose='vault_jev_flags', request={})
    except llm.LLMCapExceeded:
        pass
    else:
        raise AssertionError('flags escaped describe cap')
    other = await llm.reserve_external(aid, 'deepseek', 'deepseek-v4-flash', 10000,
                                       purpose='gen_info', request={})
    await other.done(10000, tokens_in=1, ok=True, latency_ms=1)
    try:
        await llm.reserve_external(aid, 'deepinfra', 'qwen3-vl-30b', 1,
                                  purpose='translate', request={})
    except llm.LLMCapExceeded:
        pass
    else:
        raise AssertionError('other provider escaped chat cap')
    async with get_session() as s:
        rows = (await s.execute(select(GrokDailyCost).where(GrokDailyCost.account_id == aid))).scalars().all()
    assert {r.provider: r.cost_cents for r in rows} == {'describe': 10000, 'chat': 10000}
    assert (await llm.cap_state(aid, 'describe'))['capped']
    assert (await llm.cap_state(aid, 'deepseek'))['capped']

_harness.run(case_split)
