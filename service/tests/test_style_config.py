#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import json  # noqa: E402

from sqlalchemy.dialects.sqlite import insert as sqlite_insert  # noqa: E402

from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig  # noqa: E402
from automations.cat_stickers import load_cat_sticker_config  # noqa: E402
from automations._common import (  # noqa: E402
    CAT_STICKER_GAP_MIN_KEY, CAT_STICKER_SKIP_PCT_KEY, CAT_STICKER_SOLO_PCT_KEY,
    CAT_STICKERS_KEY, CONSISTENCY_AUTOMATIONS, FACTGROUND_KEY,
    PAINFUL_TEXTING_KEY,
    STYLE_AUTOMATIONS, consistency_flag_key,
    load_cat_stickers_flag, load_consistency_flags,
    load_factground_flag, load_nonnative_flags, load_painful_texting_flag,
    load_spacing_flags, load_strip_emojis, load_style_flags, load_typo_flags,
    nonnative_flag_key, spacing_flag_key, typo_flag_key,
)
from automations._daylog import (  # noqa: E402
    DAY_LOG_ENABLED_KEY, _load_cfg_row as load_day_log_cfg_row, enabled_for,
)
from style_config_api import _defaults, _persist, _resolved_view  # noqa: E402

_AID = "style_cfg_acct"


async def _store(cfg: dict) -> None:
    payload = json.dumps(_persist(cfg))
    async with get_session() as s:
        if await s.get(Account, _AID) is None:
            s.add(Account(id=_AID))
            await s.flush()
        await s.execute(
            sqlite_insert(AccountAiConfig)
            .values(account_id=_AID, utc_offset=0, style_config_json=payload)
            .on_conflict_do_update(index_elements=["account_id"],
                                   set_={"style_config_json": payload})
        )


def _flag_readers():
    rows = []
    for a in STYLE_AUTOMATIONS:
        rows.append((a, load_style_flags, lambda d, a=a: d[a]))
        rows.append((typo_flag_key(a), load_typo_flags, lambda d, a=a: d[a]))
        rows.append((nonnative_flag_key(a), load_nonnative_flags, lambda d, a=a: d[a]))
        rows.append((spacing_flag_key(a), load_spacing_flags, lambda d, a=a: d[a]))
    for a in CONSISTENCY_AUTOMATIONS:
        rows.append((consistency_flag_key(a), load_consistency_flags, lambda d, a=a: d[a]))
    rows.append(("strip_emojis", load_strip_emojis, lambda v: v))
    rows.append((FACTGROUND_KEY, load_factground_flag, lambda v: v))
    rows.append((PAINFUL_TEXTING_KEY, load_painful_texting_flag, lambda v: v))
    rows.append((CAT_STICKERS_KEY, load_cat_stickers_flag, lambda v: v))
    rows.append((DAY_LOG_ENABLED_KEY, load_day_log_cfg_row, enabled_for))
    return rows


_NUMERIC_READERS = (
    (CAT_STICKER_SKIP_PCT_KEY, 30.0),
    (CAT_STICKER_SOLO_PCT_KEY, 40.0),
    (CAT_STICKER_GAP_MIN_KEY, 360.0),
)


async def case_every_loader_key_survives_persist():
    dropped = []
    for key, loader, read in _flag_readers():
        if key not in _persist({key: True}):
            dropped.append(key)
    assert not dropped, (
        "these keys are read by a loader but DROPPED by style_config_api._persist, "
        "so the feature behind each can never be switched on", dropped)

    unreadable = []
    for key, loader, read in _flag_readers():
        await _store({key: True})
        got = read(await loader(_AID))
        if got is not True:
            unreadable.append((key, got))
    assert not unreadable, ("persisted True but the loader does not see it", unreadable)

    await _store({})
    base = await load_cat_sticker_config(_AID)
    for key, val in _NUMERIC_READERS:
        assert key in _persist({key: val}), (f"{key} is dropped by _persist", key)
        await _store({key: val})
        got = await load_cat_sticker_config(_AID)
        assert got != base, (
            f"{key} persisted as {val} but load_cat_sticker_config still reports "
            "the defaults — the key never reaches the loader", key, base, got)
        await _store({})


async def case_an_explicit_false_survives_too():
    default_on = [k for k, v in _defaults().items() if v is True]
    assert default_on, "expected at least one default-ON key to guard"

    for key in default_on:
        out = _persist({key: False})
        assert out.get(key) is False, (
            "an explicit untick must be STORED as False — dropping it means the "
            "default silently switches the layer back on", key, out)
    for key, loader, read in _flag_readers():
        if key not in default_on:
            continue
        await _store({key: False})
        assert read(await loader(_AID)) is False, (
            "the loader must honour an explicit untick", key)


async def case_persist_still_drops_unknown_keys():
    out = _persist({"totally_made_up_key": True, "consistancy_autoreply": True,
                    "strip_emojis": True})
    assert "totally_made_up_key" not in out, out
    assert "consistancy_autoreply" not in out, ("a near-miss typo must not persist", out)
    assert out["strip_emojis"] is True, ("a known key must still get through", out)


async def case_consistency_is_off_until_explicitly_written():
    await _store({})
    off = await load_consistency_flags(_AID)
    assert off == {k: False for k in CONSISTENCY_AUTOMATIONS}, (
        "absent must resolve OFF, never the _STYLE_DEFAULT_ON tri-state", off)
    assert all(_resolved_view({})[consistency_flag_key(k)] is False
               for k in CONSISTENCY_AUTOMATIONS), "the UI must render it unchecked"

    key = consistency_flag_key("welcome_chatter_for_info")
    await _store({key: True})
    on = await load_consistency_flags(_AID)
    assert on["welcome_chatter_for_info"] is True, ("an explicit tick must reach the loader", on)
    assert _resolved_view({key: True})[key] is True, "and must render checked"


def case_the_route_merges_instead_of_replacing():
    import asyncio

    client = _harness.make_client()
    aid = "style_cfg_route"

    async def _mk():
        async with get_session() as s:
            if await s.get(Account, aid) is None:
                s.add(Account(id=aid))
    asyncio.run(_mk())

    of_key = consistency_flag_key("welcome_chatter_for_info")

    r = client.put("/admin/style-config", json={"account_id": aid, "config": {of_key: True}})
    assert r.status_code == 200, r.text
    assert r.json()["config"][of_key] is True, r.json()

    r = client.put("/admin/style-config", json={"account_id": aid, "config": {
        "autoreply": True, "typos_autoreply": True, "nonnative_autoreply": True}})
    assert r.status_code == 200, r.text

    got = client.get(f"/admin/style-config?account_id={aid}").json()["config"]
    assert got[of_key] is True, ("a sparse save from the other surface wiped it", got)
    assert got["typos_autoreply"] is True, got
    assert asyncio.run(load_consistency_flags(aid)) == {"welcome_chatter_for_info": True}


async def case_every_loader_key_is_covered():
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent
    READ_RE = re.compile(r'getattr\(\s*\w+\s*,\s*["\']style_config_json["\']|\.style_config_json\b')
    DEF_RE = re.compile(r"\s*(?:async\s+)?def\s+(\w+)")
    readers: set[str] = set()
    for path in root.rglob("*.py"):
        if ("tests" in path.parts or "migrations" in path.parts
                or path.name.startswith("_probe") or "_drive_" in path.name):
            continue
        try:
            src = path.read_text()
        except Exception:
            continue
        if "style_config_json" not in src:
            continue
        fn = None
        for line in src.splitlines():
            m = DEF_RE.match(line)
            if m:
                fn = m.group(1)
            elif fn and READ_RE.search(line) and not line.lstrip().startswith("#"):
                readers.add(f"{path.name}:{fn}")

    covered = {l.__name__ for _, l, _ in _flag_readers()}
    exempt = {"_parse_style_config", "_resolve_style_flag", "_style_default",
              "enabled_for",
              "get_style_config", "put_style_config", "_persist", "_resolved_view",
              "_defaults"}
    missing = sorted(r for r in readers
                     if r.split(":", 1)[1] not in covered | exempt)
    assert not missing, (
        "these functions read style_config_json but no row in _flag_readers covers "
        "their keys — add a row (or add to `exempt` if it does not gate a feature) "
        "so the allowlist contract reaches them", missing)


_harness.run(
    case_every_loader_key_survives_persist,
    case_an_explicit_false_survives_too,
    case_persist_still_drops_unknown_keys,
    case_consistency_is_off_until_explicitly_written,
    case_the_route_merges_instead_of_replacing,
    case_every_loader_key_is_covered,
)
