#!/usr/bin/env python3
"""test_style_config.py — every flag a loader READS must be one the API can WRITE.

`style_config_api._persist` is an allowlist: a key that is not in its `known` set
is dropped SILENTLY, on a 200, with no warning in the response or the log. That is
a one-way trapdoor between two files that are edited months apart — the loader
lands in `_common.py`, the allowlist lives in `style_config_api.py`, and nothing
connects them.

It has already cost one shipped-inert feature. The PHASE 2 pre-send consistency
check went out with a loader (`load_consistency_flags`), an LLM call, a guard stage
in `_outbound`, 341 lines of test and a drawer panel — and `consistency_*` was not
in `known`, so no operator could ever switch it on. It read as "off by default"
and was in fact "off by construction".

  case_every_loader_key_survives_persist:
      the invariant, stated once over every loader: write True, read True back.
      A new `load_*_flags` whose keys were never added to the allowlist fails
      HERE, in the commit that adds it, instead of shipping dead.
  case_persist_still_drops_unknown_keys:
      the allowlist must stay an allowlist — this is a guard against "fixing" the
      above by letting arbitrary keys through, which would let a typo'd key
      persist forever and read as a real setting.
  case_consistency_is_off_until_explicitly_written:
      the regression itself, end to end, plus the reason it must not be
      tri-state: an absent key stays False so nobody is billed a second LLM call
      per reply by default.

Run: ./venv/bin/python service/tests/test_style_config.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

# These cases test feature logic, not the account gate (that is
# test_account_isolation_gate's job). They reach `/admin` routes or
# `assert_account_owned` with no session, which fails closed (401) since
# 3b30b486. This is the documented escape hatch (read per call), scoped to this
# test process.
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
    """Persist through the SAME function the PUT endpoint uses, so this test can
    never pass by writing a key the real save path would have dropped."""
    payload = json.dumps(_persist(cfg))
    async with get_session() as s:
        if await s.get(Account, _AID) is None:   # account_ai_config FKs to accounts
            s.add(Account(id=_AID))
            await s.flush()
        await s.execute(
            sqlite_insert(AccountAiConfig)
            .values(account_id=_AID, utc_offset=0, style_config_json=payload)
            .on_conflict_do_update(index_elements=["account_id"],
                                   set_={"style_config_json": payload})
        )


# (key, loader, how to read this key out of the loader's return value)
#
# Every `load_*` in _common that resolves a style_config_json flag belongs here.
# Adding a loader without adding a row is itself the bug this file exists to
# catch, so `case_every_loader_key_is_covered` asserts the list is complete.
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
    # The day log. ONE key for BOTH chat engines, because the day belongs to the
    # CREATOR rather than to whichever engine answered — two engine-scoped flags
    # could be flipped independently and hand the same fan two different days.
    #
    # This row exists because the key was NOT in the allowlist when it first
    # shipped: the operator's flip returned 200, the response echoed back the OLD
    # value, and the feature stayed dark with nothing in any log to say why. Exactly
    # the failure the rest of this file was written for, one release later.
    #
    # Read the way the engines read it: `load_day` fetches the brain row once and
    # asks `enabled_for(row)`, so the loader here is that row fetch and the
    # reader is the same pure parser.
    rows.append((DAY_LOG_ENABLED_KEY, load_day_log_cfg_row, enabled_for))
    return rows


# The NUMERIC knobs are the same contract with a different type: dropped by the
# allowlist ⇒ the operator's "one gif per fan per 6h" silently reverts to the
# default forever. They are listed apart because `load_cat_sticker_config` returns
# numbers, so the write-True/read-True loop above cannot express them — which is
# exactly why they were missed on the first pass of this file.
_NUMERIC_READERS = (
    (CAT_STICKER_SKIP_PCT_KEY, 30.0),
    (CAT_STICKER_SOLO_PCT_KEY, 40.0),
    (CAT_STICKER_GAP_MIN_KEY, 360.0),
)


async def case_every_loader_key_survives_persist():
    """Write True through the real save path; every loader must read True back.

    This is the whole contract in one loop. A `consistency_*` key failed it
    before the allowlist entry existed: `_persist` returned {} and the loader
    dutifully reported False forever."""
    dropped = []
    for key, loader, read in _flag_readers():
        if key not in _persist({key: True}):
            dropped.append(key)
    assert not dropped, (
        "these keys are read by a loader but DROPPED by style_config_api._persist, "
        "so the feature behind each can never be switched on", dropped)

    # Not just present in the dict — actually visible to the loader that gates the
    # feature. Catches a key that persists but is read off a different column.
    unreadable = []
    for key, loader, read in _flag_readers():
        await _store({key: True})
        got = read(await loader(_AID))
        if got is not True:
            unreadable.append((key, got))
    assert not unreadable, ("persisted True but the loader does not see it", unreadable)

    # And the same contract for the numeric knobs, which the boolean loop cannot
    # reach: a dropped key here reverts an operator's tuning to the default with
    # no error, which reads as "the setting does not work".
    #
    # Asserted as "the loader's answer CHANGES", not as an expected number:
    # load_cat_sticker_config returns the percentages scaled to 0-1, and pinning
    # the scale here would make this test fail whenever that mapping is retuned,
    # which is not what it is guarding.
    await _store({})
    base = await load_cat_sticker_config(_AID)
    for key, val in _NUMERIC_READERS:
        assert key in _persist({key: val}), (f"{key} is dropped by _persist", key)
        await _store({key: val})
        got = await load_cat_sticker_config(_AID)
        assert got != base, (
            f"{key} persisted as {val} but load_cat_sticker_config still reports "
            "the defaults — the key never reaches the loader", key, base, got)
        await _store({})   # back to bare so each knob is measured against `base`


async def case_an_explicit_false_survives_too():
    """Un-ticking must persist as an explicit False, not vanish.

    Only ever writing True would leave the whole UNTICK path unverified for the
    default-ON keys (painful texting, cat stickers, the day log, …): a `_persist`
    that quietly dropped explicit Falses would let an operator untick one, see it
    save, and find it back ON at load time — the key would be absent and absent
    means default-ON. That is a silent revert of an operator's decision."""
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
    """The fix must not turn the allowlist into a passthrough.

    If arbitrary keys persisted, a typo ('consistancy_autoreply') would be stored
    forever, render as a real setting, and gate nothing — the same failure wearing
    a different name."""
    out = _persist({"totally_made_up_key": True, "consistancy_autoreply": True,
                    "strip_emojis": True})
    assert "totally_made_up_key" not in out, out
    assert "consistancy_autoreply" not in out, ("a near-miss typo must not persist", out)
    assert out["strip_emojis"] is True, ("a known key must still get through", out)


async def case_consistency_is_off_until_explicitly_written():
    """The regression, end to end — and the reason it is not tri-state.

    PHASE 2 costs a second LLM call on every reply it fires for. An absent key
    must read False, so an account that never asked for it is never billed; only
    an explicit True switches it on."""
    await _store({})                                  # nothing written at all
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
    """Through the REAL endpoint: a sparse save must not wipe the other tab's flags.

    Everything above calls `_persist` directly, which skips the read-modify-merge in
    `put_style_config` — and that merge is the only thing standing between the two
    UI surfaces that write this store. The rule editor posts only its own kind's
    keys; the Auto Convo tab posts its whole form. If the route ever wrote
    `body.config` straight through, one surface's save would silently blank the
    other's — including a paid `consistency_*` an operator had just enabled.

    Also the only coverage of the endpoint's own contract: PUT returns the RESOLVED
    view (not the sparse persisted dict), so the UI re-renders default-ON boxes as
    checked rather than flipping them off after a save."""
    import asyncio

    client = _harness.make_client()
    aid = "style_cfg_route"

    async def _mk():
        async with get_session() as s:
            if await s.get(Account, aid) is None:
                s.add(Account(id=aid))
    asyncio.run(_mk())

    of_key = consistency_flag_key("welcome_chatter_for_info")

    # Auto Convo tab: turns on the welcome_chatter_for_info check.
    r = client.put("/admin/style-config", json={"account_id": aid, "config": {of_key: True}})
    assert r.status_code == 200, r.text
    assert r.json()["config"][of_key] is True, r.json()

    # Rule editor: posts ONLY autoreply's keys, never mentioning welcome_chatter_for_info.
    r = client.put("/admin/style-config", json={"account_id": aid, "config": {
        "autoreply": True, "typos_autoreply": True, "nonnative_autoreply": True}})
    assert r.status_code == 200, r.text

    got = client.get(f"/admin/style-config?account_id={aid}").json()["config"]
    assert got[of_key] is True, ("a sparse save from the other surface wiped it", got)
    assert got["typos_autoreply"] is True, got
    # And the loader — the only opinion that actually gates the spend — agrees.
    assert asyncio.run(load_consistency_flags(aid)) == {"welcome_chatter_for_info": True}


async def case_every_loader_key_is_covered():
    """`_flag_readers` must enumerate every style-config loader in _common.

    Without this, the contract above silently stops covering new features: someone
    adds `load_foo_flags`, never adds a row here, and the allowlist gap ships
    exactly as `consistency_*` did."""
    import pathlib
    import re

    # Source-level, not inspect-level. The first version of this guard enumerated
    # `load_*_flag/_flags` coroutines in _common and MISSED the cat-sticker tuning loader
    # (wrong suffix) — a name-shaped filter only finds the loaders someone
    # remembered to name conventionally. This instead finds every function that
    # READS the column, whatever it is called, sync or async, in any module.
    root = pathlib.Path(__file__).resolve().parent.parent
    # An actual READ of the column, not a mention of its name: `getattr(cfg,
    # "style_config_json", ...)` or `row.style_config_json`. Matching the bare
    # name instead swept up every docstring that says "style_config_json key
    # for ..." and reported three key-NAME builders as loaders.
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
    # Reads the column but does NOT gate a feature on a flag: the shared parser,
    # the resolver, and the API's own read/write path.
    exempt = {"_parse_style_config", "_resolve_style_flag", "_style_default",
              # The day log's pure parser, which `load_day` calls on the row it
              # already holds. The key it reads IS covered — by the
              # DAY_LOG_ENABLED_KEY row above, which reads through it — so
              # exempting it here does not lose the guard.
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
