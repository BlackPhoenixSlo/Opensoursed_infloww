#!/usr/bin/env python3
"""
`vault_items.raw_json` and `vault_response_cache` keep only the `listStates`
entries with `hasMedia`.
Plain-assert, no pytest (repo convention).

Why: OF sends EVERY list the creator has on every media item (measured 786 per
item, 780 `hasMedia: false`), so each raw_json was ~100 KB and one box held
2 GB of them; the relay OOM'd when the vault opened. Every reader uses only the
`hasMedia` entries, so the rest is cut on write (`vault_mirror.compact_list_states`)
and once from existing rows at boot (`engine.compact_vault_list_states_once`,
which also empties `vault_response_cache`: it refills from OF).

Cases:
  case_helper_table — the pure rule: drops falsy hasMedia + non-dicts, keeps the
      key (an empty list, never removed), returns the SAME object when nothing
      is dropped, never mutates its input.
  case_row_values_writes_compact_raw_json — the write path: raw_json trimmed,
      of_folder_ids unchanged, the caller's OF dict untouched.
  case_cache_put_trims_media_pages_and_by_id — vault_cache.put stores media
      pages and by-id media trimmed; a /vault/lists page's folders (their own
      `hasMedia: false`) are untouched; the caller's payload is not mutated.
  case_compaction_streams_and_only_rewrites_what_shrinks — 786 lists incl. 3
      hasMedia → 3; no-listStates / already-compact / junk / NULL rows byte-equal;
      of_folder_ids + updated_at never move; batches of 2 cross the keyset; the
      marker stops a second run; vault_response_cache emptied.
  case_init_db_compacts_at_boot — booting (init_db, alembic never runs) applies
      both (row compacted, cache wiped, marker written).

Run: cd service/tests && \
  PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_vault_list_states_compact.py
Exit 0 = all cases passed. Temp DBs only (never prod).
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import copy  # noqa: E402
import importlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import sqlalchemy as sa  # noqa: E402

import vault_cache  # noqa: E402
import vault_mirror  # noqa: E402

db_engine = importlib.import_module("db.engine")  # `db.engine` the attr is the AsyncEngine


def _lists(n: int, has: tuple[int, ...]) -> list[dict]:
    """`n` OF lists as one media item carries them; ids in `has` hold the media."""
    out = [{"id": 1, "type": "posts", "name": "Posts", "hasMedia": False, "canAddMedia": False}]
    out += [{"id": 100 + i, "type": "custom", "name": f"L{i}", "hasMedia": (100 + i) in has,
             "canAddMedia": True} for i in range(n - 1)]
    return out


def case_helper_table():
    keep = {"id": 7, "type": "custom", "hasMedia": True}
    rows = [
        # (input, expected listStates or "same")
        ({"id": 1}, "same"),
        ({"id": 1, "listStates": None}, "same"),
        ({"id": 1, "listStates": []}, "same"),
        ({"id": 1, "listStates": [keep]}, "same"),
        ({"id": 1, "listStates": [{"id": 8, "hasMedia": False}]}, []),
        ({"id": 1, "listStates": [{"id": 8}, keep, {"id": 9, "hasMedia": None},
                                  {"id": 10, "hasMedia": 0}, "junk", None]}, [keep]),
        ({"id": 1, "listStates": [keep, {"id": 11, "type": "posts", "hasMedia": True}]}, "same"),
    ]
    for m, want in rows:
        before = copy.deepcopy(m)
        got = vault_mirror.compact_list_states(m)
        assert m == before, f"input mutated: {before} -> {m}"
        if want == "same":
            assert got is m, f"nothing to drop must return the same object: {m}"
        else:
            assert got is not m and got["listStates"] == want, f"{m} -> {got}"
            assert {k: v for k, v in got.items() if k != "listStates"} == \
                   {k: v for k, v in m.items() if k != "listStates"}, "other keys must survive"


def case_row_values_writes_compact_raw_json():
    m = {"id": 5, "type": "photo", "files": {"full": {"url": "u"}},
         "listStates": _lists(786, (105, 300, 700))}
    before = copy.deepcopy(m)
    v = vault_mirror.row_values("acc", m)
    stored = json.loads(v["raw_json"])
    assert [x["id"] for x in stored["listStates"]] == [105, 300, 700], stored["listStates"]
    assert json.loads(v["of_folder_ids"]) == [105, 300, 700], v["of_folder_ids"]
    assert m == before, "the caller's OF dict must not be mutated"
    assert len(v["raw_json"]) < 1000, len(v["raw_json"])
    # no listStates key stays absent (vault_runs: missing = "keep known folders")
    v2 = vault_mirror.row_values("acc", {"id": 6, "type": "photo"})
    assert "listStates" not in json.loads(v2["raw_json"])


async def case_cache_put_trims_media_pages_and_by_id():
    from db.engine import get_session
    from db.models import Account
    aid = "cache_acc"
    async with get_session() as s:
        s.add(Account(id=aid, nickname=aid, color="#aaaaaa"))
        await s.commit()
    page ={"list": [{"id": 1, "type": "photo", "listStates": _lists(786, (105,))},
                     {"id": 2, "type": "photo"}], "hasMore": True}
    by_id = {"id": 3, "type": "video", "listStates": _lists(20, (101, 102))}
    folders = {"list": [{"id": 9, "type": "custom", "name": "Empty", "hasMedia": False},
                        {"id": 10, "type": "custom", "name": "Full", "hasMedia": True}], "hasMore": False}
    before = copy.deepcopy(page)
    t0 = datetime.utcnow()
    await vault_cache.put(aid, "media:p0", page, started_at=t0)
    await vault_cache.put(aid, "media-by-id:3", by_id, started_at=t0)
    await vault_cache.put(aid, "lists:p0", folders, started_at=t0)
    assert page == before, "the caller's payload (served to the UI) must not be mutated"

    got = await vault_cache.get(aid, "media:p0")
    assert [x["id"] for x in got["list"][0]["listStates"]] == [105], got["list"][0]["listStates"]
    assert got["list"][1] == {"id": 2, "type": "photo"} and got["hasMore"] is True, got
    got = await vault_cache.get(aid, "media-by-id:3")
    assert [x["id"] for x in got["listStates"]] == [101, 102], got
    assert await vault_cache.get(aid, "lists:p0") == folders, "folder objects keep their own hasMedia"


def _temp_db(name: str) -> Path:
    db = Path(tempfile.gettempdir()) / f"{name}_{os.getpid()}.db"
    if db.exists():
        db.unlink()
    return db


def _rows(eng) -> dict[int, tuple]:
    with eng.connect() as c:
        return {r[0]: tuple(r[1:]) for r in c.execute(sa.text(
            "SELECT media_id, raw_json, of_folder_ids, updated_at FROM vault_items"))}


def case_compaction_streams_and_only_rewrites_what_shrinks():
    eng = sa.create_engine(f"sqlite:///{_temp_db('vault_ls_compact')}")
    bloated = {"id": 1, "type": "photo", "listStates": _lists(786, (101, 150, 800))}
    seed = {
        1: json.dumps(bloated),
        2: json.dumps({"id": 2, "type": "photo"}),                       # no listStates
        3: json.dumps({"id": 3, "listStates": [{"id": 9, "hasMedia": True}]}),  # already compact
        4: "{not json",
        5: None,
        6: json.dumps({"id": 6, "listStates": [{"id": 1, "hasMedia": False}]}),  # all dropped
    }
    with eng.begin() as c:
        c.exec_driver_sql("CREATE TABLE vault_items (account_id VARCHAR NOT NULL, media_id BIGINT NOT NULL, "
                          "raw_json TEXT, of_folder_ids TEXT, updated_at DATETIME, "
                          "PRIMARY KEY (account_id, media_id))")
        c.exec_driver_sql("CREATE TABLE vault_response_cache (account_id VARCHAR, query_key VARCHAR, "
                          "response_json TEXT, fetched_at DATETIME)")
        c.exec_driver_sql("INSERT INTO vault_response_cache VALUES ('a', 'k1', '{}', NULL), ('b', 'k2', '{}', NULL)")
        for mid, raw in seed.items():
            c.execute(sa.text("INSERT INTO vault_items VALUES ('a', :m, :r, '[1,2]', '2026-01-01 00:00:00')"),
                      {"m": mid, "r": raw})
    before = _rows(eng)

    n = db_engine.compact_vault_list_states_once(eng, batch=2)
    after = _rows(eng)

    assert n == 2, f"rows 1 and 6 shrink, got {n}"
    got1 = json.loads(after[1][0])
    assert [x["id"] for x in got1["listStates"]] == [101, 150, 800], got1["listStates"]
    assert {k: v for k, v in got1.items() if k != "listStates"} == {"id": 1, "type": "photo"}
    assert json.loads(after[6][0]) == {"id": 6, "listStates": []}, "key kept, empty list"
    for mid in (2, 3, 4, 5):
        assert after[mid] == before[mid], f"row {mid} must be untouched"
    for mid in seed:
        assert after[mid][1:] == before[mid][1:], f"row {mid}: of_folder_ids/updated_at moved"
    assert len(after[1][0]) * 50 < len(before[1][0]), (len(after[1][0]), len(before[1][0]))
    with eng.connect() as c:
        assert c.execute(sa.text("SELECT count(*) FROM vault_response_cache")).scalar() == 0, "cache wiped"

    # marker: a second run does nothing, even with a fresh bloated row
    with eng.begin() as c:
        c.execute(sa.text("UPDATE vault_items SET raw_json = :r WHERE media_id = 1"),
                  {"r": json.dumps(bloated)})
    assert db_engine.compact_vault_list_states_once(eng, batch=2) == 0
    assert len(_rows(eng)[1][0]) == len(json.dumps(bloated)), "marker must stop a rerun"
    eng.dispose()


def case_init_db_compacts_at_boot():
    """The relay never runs alembic: the harness DB was built by init_db (fresh
    branch, stamped), so this second boot takes the catch-up branch."""
    eng = sa.create_engine(db_engine.sync_database_url())
    raw = json.dumps({"id": 77, "type": "photo", "listStates": _lists(50, (110,))})
    with eng.begin() as c:
        assert c.execute(sa.text("SELECT 1 FROM data_migrations WHERE name = :n"),
                         {"n": db_engine._VAULT_LIST_STATES_COMPACT}).first() is None, \
            "the fresh-box branch must not have run it yet"
        c.execute(sa.text("INSERT OR IGNORE INTO accounts (id, nickname, color) VALUES ('boot', 'boot', '#aaaaaa')"))
        c.execute(sa.text("INSERT INTO vault_items (account_id, media_id, kind, raw_json, created_at, tags, "
                          "send_count) VALUES ('boot', 77, 'photo', :r, '2026-01-01', '[]', 0)"), {"r": raw})
        c.execute(sa.text("INSERT INTO vault_response_cache (account_id, query_key, response_json, fetched_at) "
                          "VALUES ('boot', 'media:x', :r, '2026-01-01')"), {"r": json.dumps({"list": [raw]})})
    asyncio.run(db_engine.init_db())
    with eng.connect() as c:
        stored = c.execute(sa.text("SELECT raw_json FROM vault_items WHERE media_id = 77")).scalar()
        marked = c.execute(sa.text("SELECT 1 FROM data_migrations WHERE name = :n"),
                           {"n": db_engine._VAULT_LIST_STATES_COMPACT}).first()
    assert [x["id"] for x in json.loads(stored)["listStates"]] == [110], stored
    assert marked is not None, "marker written"
    with eng.connect() as c:
        assert c.execute(sa.text("SELECT count(*) FROM vault_response_cache")).scalar() == 0, "cache wiped"
    eng.dispose()


_harness.run()
