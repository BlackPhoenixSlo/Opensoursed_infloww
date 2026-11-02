#!/usr/bin/env python3
"""`/admin/saved-replies/relabel` is all-or-nothing.

The seam is the Relay over HTTP with the shared two-Agency fixture's owner
session; the DB is read back through a fresh sqlite3 connection, not the
route. A relabel that blows up on one script (a corrupt tags_json) must leave
every script as it was, a clean one changes exactly the scripts it names, and
a sequence rename onto an existing name changes nothing.

Run: ./venv/bin/python service/tests/test_saved_reply_relabel_atomic.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import json  # noqa: E402
import sqlite3  # noqa: E402

import _agency_fixtures as fx  # noqa: E402

IDS = fx.seed_two_agencies()
A = IDS["creator_a"]


def _sql(query: str, *args) -> list[tuple]:
    con = sqlite3.connect(_harness.DB_PATH)
    try:
        rows = con.execute(query, args).fetchall()
        con.commit()
        return rows
    finally:
        con.close()


def _db_rows() -> dict[int, tuple]:
    return {r[0]: r[1:] for r in _sql(
        "SELECT id, tags_json, script_id, script_step FROM saved_replies WHERE account_id = ?", A)}


def _corrupt_tags(reply_id: int) -> None:
    _sql("UPDATE saved_replies SET tags_json = ? WHERE id = ?", "[not json", reply_id)


def _new(c, **body) -> dict:
    r = c.post(f"/admin/saved-replies?account_id={A}", json={"text": "hi", **body})
    assert r.status_code == 200, r.text
    return r.json()


def _relabel(c, **body):
    return c.post(f"/admin/saved-replies/relabel?account_id={A}", json=body)


def _wipe() -> None:
    # SQL, not the list route: the atomic case leaves a corrupt row the list can't serialize.
    _sql("DELETE FROM saved_replies WHERE account_id = ?", A)


def case_a_relabel_that_fails_midway_leaves_every_script_unchanged():
    c = fx.login_owner("agency_a_owner")
    _wipe()
    ids = [_new(c, title=t, tags=["Old"])["id"] for t in ("r1", "r2", "r3")]
    # The handler's select has no ORDER BY; the corrupt row is the middle one, so an ascending or a descending scan
    # both relabel a clean row before the failing one.
    _corrupt_tags(ids[1])
    before = _db_rows()
    try:
        _relabel(c, kind="tag", **{"from": "Old"}, to="New", ids=ids)
    except json.JSONDecodeError:  # TestClient re-raises the handler's error
        pass
    else:
        raise AssertionError("relabel over a corrupt row did not fail")
    after = _db_rows()
    assert after == before, (before, after)


def case_a_tag_rename_changes_exactly_the_scripts_that_have_it():
    c = fx.login_owner("agency_a_owner")
    _wipe()
    a = _new(c, title="a", tags=["Old", "VIP"])["id"]
    b = _new(c, title="b", tags=["VIP"])["id"]
    d = _new(c, title="d", tags=["Old"])["id"]
    before = _db_rows()
    r = _relabel(c, kind="tag", **{"from": "Old"}, to="New")
    assert r.status_code == 200 and r.json() == {"updated": 2}, r.text
    after = _db_rows()
    assert json.loads(after[a][0]) == ["VIP", "New"] and json.loads(after[d][0]) == ["New"], after
    assert after[b] == before[b], (before, after)


def case_a_sequence_rename_onto_an_existing_name_is_409_and_changes_nothing():
    c = fx.login_owner("agency_a_owner")
    _wipe()
    _new(c, title="s1", script_id="Welcome", script_step=1)
    _new(c, title="s2", script_id="Welcome", script_step=2)
    _new(c, title="o1", script_id="Other", script_step=1)
    before = _db_rows()
    r = _relabel(c, kind="sequence", **{"from": "Welcome"}, to="Other")
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "Sequence name already exists. Please rename sequence.", r.text
    assert _db_rows() == before


_harness.run(
    case_a_relabel_that_fails_midway_leaves_every_script_unchanged,
    case_a_tag_rename_changes_exactly_the_scripts_that_have_it,
    case_a_sequence_rename_onto_an_existing_name_is_409_and_changes_nothing,
)
