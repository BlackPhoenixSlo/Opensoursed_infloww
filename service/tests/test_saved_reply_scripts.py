#!/usr/bin/env python3
"""Growth > Scripts' tags, internal notes and sequences on the saved-replies routes.

The seam is the Relay over HTTP with the shared two-Agency fixture's owner
sessions: a script's tags and notes round-trip through create / PUT / list, a
PUT that omits them keeps them, and `/admin/saved-replies/relabel` renames,
deletes and bulk-adds tags and renames or ungroups sequences.

Run: ./venv/bin/python service/tests/test_saved_reply_scripts.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import _agency_fixtures as fx  # noqa: E402

IDS = fx.seed_two_agencies()
A = IDS["creator_a"]
B = IDS["creator_b"]


def _list(c, acc=A) -> list[dict]:
    r = c.get(f"/admin/saved-replies?account_id={acc}")
    assert r.status_code == 200, r.text
    return r.json()["list"]


def _new(c, **body) -> dict:
    r = c.post(f"/admin/saved-replies?account_id={A}", json={"text": "hi", **body})
    assert r.status_code == 200, r.text
    return r.json()


def _relabel(c, acc=A, **body):
    return c.post(f"/admin/saved-replies/relabel?account_id={acc}", json=body)


def _wipe(c) -> None:
    for r in _list(c):
        assert c.delete(f"/admin/saved-replies/{r['id']}").status_code == 200


def case_tags_and_notes_round_trip_and_a_put_without_them_keeps_them():
    c = fx.login_owner("agency_a_owner")
    _wipe(c)
    row = _new(c, title="ask name", tags=[" Opener ", "Opener", "", "VIP"], notes="only after 9pm")
    assert row["tags"] == ["Opener", "VIP"], row
    assert row["notes"] == "only after 9pm", row
    r = c.put(f"/admin/saved-replies/{row['id']}", json={"text": "hello"})
    assert r.status_code == 200, r.text
    assert r.json()["tags"] == ["Opener", "VIP"] and r.json()["notes"] == "only after 9pm", r.json()
    r = c.put(f"/admin/saved-replies/{row['id']}", json={"text": "hello", "tags": [], "notes": ""})
    assert r.json()["tags"] == [] and r.json()["notes"] is None, r.json()
    # An old row with no tags reads as [].
    assert _new(c)["tags"] == []


def case_a_tag_over_32_or_notes_over_256_characters_is_rejected():
    c = fx.login_owner("agency_a_owner")
    r = c.post(f"/admin/saved-replies?account_id={A}", json={"text": "x", "tags": ["x" * 33]})
    assert r.status_code == 400, r.text
    r = c.post(f"/admin/saved-replies?account_id={A}", json={"text": "x", "notes": "x" * 257})
    assert r.status_code == 422, r.text


def case_tag_rename_delete_add_and_remove_from_one_script():
    c = fx.login_owner("agency_a_owner")
    _wipe(c)
    a = _new(c, title="a", tags=["Opener"])
    b = _new(c, title="b", tags=["Opener", "VIP"])
    z = _new(c, title="z")
    # Rename merges into an existing tag without duplicating it.
    r = _relabel(c, kind="tag", **{"from": "Opener"}, to="VIP")
    assert r.status_code == 200 and r.json() == {"updated": 2}, r.text
    tags = {x["title"]: x["tags"] for x in _list(c)}
    assert tags == {"a": ["VIP"], "b": ["VIP"], "z": []}, tags
    # Add to the selected scripts.
    assert _relabel(c, kind="tag", to="Night", ids=[a["id"], z["id"]]).json() == {"updated": 2}
    # Remove one script from a tag.
    assert _relabel(c, kind="tag", **{"from": "VIP"}, ids=[b["id"]]).json() == {"updated": 1}
    tags = {x["title"]: x["tags"] for x in _list(c)}
    assert tags == {"a": ["VIP", "Night"], "b": [], "z": ["Night"]}, tags
    # Delete a tag everywhere.
    assert _relabel(c, kind="tag", **{"from": "Night"}).json() == {"updated": 2}
    assert {x["title"]: x["tags"] for x in _list(c)} == {"a": ["VIP"], "b": [], "z": []}
    # Adding with no selection is refused; so is an over-long name.
    assert _relabel(c, kind="tag", to="x").status_code == 400
    assert _relabel(c, kind="tag", to="x" * 33, ids=[a["id"]]).status_code == 400


def case_sequence_rename_clash_and_ungroup():
    c = fx.login_owner("agency_a_owner")
    _wipe(c)
    _new(c, title="s1", script_id="New Sub", script_step=1)
    _new(c, title="s2", script_id="New Sub", script_step=2)
    _new(c, title="o1", script_id="Other", script_step=1)
    assert _relabel(c, kind="sequence", **{"from": "New Sub"}, to="Other").status_code == 409
    assert _relabel(c, kind="sequence", **{"from": "New Sub"}, to="Welcome").json() == {"updated": 2}
    seq = {x["title"]: (x["script_id"], x["script_step"]) for x in _list(c)}
    assert seq == {"s1": ("Welcome", 1), "s2": ("Welcome", 2), "o1": ("Other", 1)}, seq
    assert _relabel(c, kind="sequence", **{"from": "Welcome"}).json() == {"updated": 2}
    seq = {x["title"]: (x["script_id"], x["script_step"]) for x in _list(c)}
    assert seq == {"s1": (None, None), "s2": (None, None), "o1": ("Other", 1)}, seq
    # A sequence edit needs its name.
    assert _relabel(c, kind="sequence", to="x", ids=[1]).status_code == 400


def case_relabel_is_scoped_to_the_owners_creator():
    _new(fx.login_owner("agency_a_owner"), tags=["VIP"])
    owner_b = fx.login_owner("agency_b_owner")
    r = _relabel(owner_b, acc=A, kind="tag", **{"from": "VIP"})
    assert r.status_code == 403, r.text
    # B's own Creator: nothing tagged, nothing updated.
    assert _relabel(owner_b, acc=B, kind="tag", **{"from": "VIP"}).json() == {"updated": 0}
    c = fx.login_owner("agency_a_owner")
    assert any(x["tags"] == ["VIP"] for x in _list(c)), "B's relabel touched A's scripts"


_harness.run(
    case_tags_and_notes_round_trip_and_a_put_without_them_keeps_them,
    case_a_tag_over_32_or_notes_over_256_characters_is_rejected,
    case_tag_rename_delete_add_and_remove_from_one_script,
    case_sequence_rename_clash_and_ungroup,
    case_relabel_is_scoped_to_the_owners_creator,
)
