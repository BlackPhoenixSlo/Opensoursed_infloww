#!/usr/bin/env python3
"""test_account_config_language.py — the Brain-config language setting round-trips and
never clobbers the sibling JSON columns (the mandatory upsert-isolation case).

The cases call the route coroutines directly as a signed-in owner (the shared
two-Agency fixture): each case's Creator is linked to that owner's Agency and
the owner is put on the request principal the way the session middleware does,
so they pass with or without ALLOW_ANONYMOUS_ADMIN=1.

Run:  ./venv/bin/python service/tests/test_account_config_language.py
"""
import _harness  # noqa: F401 — MUST be first

_harness.bootstrap()

from account_config_api import (  # noqa: E402
    _ConfigBody, get_account_config, put_account_config, LANGUAGES,
)
from sqlalchemy import select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import auth  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, UserAccount  # noqa: E402

_IDS = fx.seed_two_agencies()
_OWNER = "agency_a_owner"


async def _sign_in_owner():
    """Put the owner on the request principal with the account_ids snapshot
    the session middleware takes from user_accounts (auth.session_middleware)."""
    async with get_session() as s:
        rows = (await s.execute(select(UserAccount.account_id).where(
            UserAccount.user_id == _IDS[_OWNER]))).all()
    auth._request_user.set(auth.AuthedUser(
        _IDS[_OWNER], _OWNER, frozenset(str(r[0]) for r in rows)))


async def _seed(aid: str):
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
            # the signed-in owner's Agency holds this Creator
            s.add(UserAccount(user_id=_IDS[_OWNER], account_id=aid))
    await _sign_in_owner()


async def case_language_roundtrips():
    aid = "acc_cfg_es"
    await _seed(aid)
    await put_account_config(_ConfigBody(account_id=aid, config={
        "persona": "una creadora española", "language": "es"}))
    got = await get_account_config(account_id=aid)
    assert got["config"]["language"] == "es", got["config"]["language"]
    assert got["config"]["persona"] == "una creadora española"
    # metadata for the dropdown is present
    codes = {l["code"] for l in got["languages"]}
    assert {"en", "es", "sl"} <= codes, codes


async def case_default_is_en():
    aid = "acc_cfg_default"
    await _seed(aid)
    got = await get_account_config(account_id=aid)
    assert got["config"]["language"] == "en", got["config"]["language"]


async def case_en_stores_null():
    aid = "acc_cfg_en"
    await _seed(aid)
    await put_account_config(_ConfigBody(account_id=aid, config={"language": "en"}))
    async with get_session() as s:
        row = await s.get(AccountAiConfig, aid)
        assert row.language is None, row.language      # NULL == en, column stays sparse
    got = await get_account_config(account_id=aid)
    assert got["config"]["language"] == "en"


async def case_junk_language_422():
    aid = "acc_cfg_junk"
    await _seed(aid)
    raised = False
    try:
        await put_account_config(_ConfigBody(account_id=aid, config={"language": "klingon"}))
    except Exception as e:
        raised = "422" in str(e) or "supported" in str(e).lower() or e.__class__.__name__ == "HTTPException"
    assert raised, "junk language must 422"


async def case_upsert_preserves_siblings():
    """Saving language must not wipe nudge_config_json (owned by another API)."""
    aid = "acc_cfg_sibling"
    await _seed(aid)
    async with get_session() as s:
        row = await s.get(AccountAiConfig, aid)
        if row is None:
            s.add(AccountAiConfig(account_id=aid, nudge_config_json='{"slots":{"x":1}}'))
        else:
            row.nudge_config_json = '{"slots":{"x":1}}'
    await put_account_config(_ConfigBody(account_id=aid, config={"language": "es"}))
    async with get_session() as s:
        row = await s.get(AccountAiConfig, aid)
        assert row.language == "es"
        assert row.nudge_config_json == '{"slots":{"x":1}}', "sibling JSON preserved"


if __name__ == "__main__":
    _harness.run(
        case_language_roundtrips,
        case_default_is_en,
        case_en_stores_null,
        case_junk_language_422,
        case_upsert_preserves_siblings,
    )
