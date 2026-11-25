#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first

_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

from fans import FanUpdateBody, update_fan, get_fan  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan  # noqa: E402


async def _seed(aid: str, fan: int):
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        if await s.get(Fan, (aid, fan)) is None:
            s.add(Fan(account_id=aid, fan_id=fan, of_display_name="Bob"))


async def case_patch_sets_manual_source():
    aid, fan = "acc_fp", 8001
    await _seed(aid, fan)
    await update_fan(aid, fan, FanUpdateBody(language="es"))
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        assert f.language == "es", f.language
        assert f.language_source == "manual", f.language_source
    row = await get_fan(aid, fan)
    assert row["language"] == "es" and row["language_source"] == "manual"


async def case_patch_normalizes_and_rejects_junk():
    aid, fan = "acc_fp2", 8002
    await _seed(aid, fan)
    await update_fan(aid, fan, FanUpdateBody(language="ES-mx"))
    async with get_session() as s:
        assert (await s.get(Fan, (aid, fan))).language == "es"
    raised = False
    try:
        FanUpdateBody(language="klingon")
    except Exception:
        raised = True
    assert raised, "junk language must fail validation"


async def case_clear_override():
    aid, fan = "acc_fp3", 8003
    await _seed(aid, fan)
    await update_fan(aid, fan, FanUpdateBody(language="es"))
    await update_fan(aid, fan, FanUpdateBody(language=""))
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan))
        assert f.language is None and f.language_source is None, (f.language, f.language_source)


if __name__ == "__main__":
    _harness.run(
        case_patch_sets_manual_source,
        case_patch_normalizes_and_rejects_junk,
        case_clear_override,
    )
