from datetime import datetime, timezone

import pytest

from proof_core import Proof, Run, Write, add_read_id, read_id_query, read_keys_for


def P(arm=(), undo=(), tags=(), id="p.x"):
    return Proof(id=id, phase=0, page="collections/index", control="x", kind="live", tags=frozenset(tags),
                 arm=tuple(arm), undo=tuple(undo), effect=lambda before, after: True)


TRACER = P(arm=[Write("POST", "/api2/v2/lists")], undo=[Write("DELETE", "/api2/v2/lists/{id}")], id="tracer.create-list")
HIDE = Write("PUT", "/api2/v2/vault/media/hidden", body_must={"mediaIds": ["{media}"]}, relay_method="POST",
             relay="/admin/vault-ai/items/{media}/hide", relay_body={"account_id": "{account}"}, reverses=(0, 1))
RECORD = P(arm=[Write("POST", "/api2/v2/upload/signed/create"), Write("POST", "/api2/v2/posts")],
           undo=[Write("DELETE", "/api2/v2/posts/{id}", relay="/api/of/v2/posts/{id}", reverses=(1,)), HIDE],
           tags={"post"}, id="p2.record")
POSTED = Run(proof=RECORD, spent={("arm", 1): 1}, created=frozenset({"9", "55"}),
             created_by={0: frozenset({"55"}), 1: frozenset({"9"})})


def test_read_id_registers_its_own_kind_only():
    run = add_read_id(POSTED, "media", "77", "9")
    assert run.keys == {"media": frozenset({"77"})} and run.created == frozenset({"9", "55"})
    assert add_read_id(run, "media", "78", "9").keys == {"media": frozenset({"77", "78"})}


@pytest.mark.parametrize("run, key, of_id, source, why", [
    (POSTED, "id", "77", "9", "not a kind"),
    (POSTED, "fan", "77", "9", "not a kind"),
    (POSTED, "media", "77", "8", "not created"),
    (POSTED, "media", "77", "77", "not created"),
    (POSTED, "media", "77", "55", "not created"),
    (POSTED, "media", "", "9", "no id"),
    (Run(created=frozenset({"9"})), "media", "77", "9", "no proof armed"),
    (Run(proof=TRACER, created=frozenset({"9"})), "media", "77", "9", "not a kind"),
    (POSTED, "schedule", "77", "9", "not a kind"),
], ids=["id is the created kind", "a key no undo body names", "source post not created", "source is the media id",
        "source is an id an upload arm's reply created",
        "empty id", "no proof armed", "a proof whose undos name no key", "an unknown kind (no bind declares it)"])
def test_read_id_refused(run, key, of_id, source, why):
    with pytest.raises(ValueError, match=why):
        add_read_id(run, key, of_id, source)


READ = {"9": {"media": 77}, "10": {"media": "78"}}


@pytest.mark.parametrize("read, source, want", [
    (READ, "9", {"media": "77"}), (READ, 10, {"media": "78"}), (READ, "11", {}), (None, "9", {}),
    ({"9": {"media": None}}, "9", {}),
], ids=["its own post's media", "another post's media is not taken", "source not in the read", "no read",
        "a none value is dropped"])
def test_read_keys_for(read, source, want):
    assert read_keys_for(read, source) == want


def test_read_id_query_shapes_and_the_schedule_read_needs_now():
    now = datetime(2026, 11, 21, 23, 0, tzinfo=timezone.utc)
    assert read_id_query("media", "7", None) == ("/api2/v2/posts/7", {})
    assert read_id_query("message", None, "555") == ("/api2/v2/chats/555/messages", {"limit": 10, "order": "desc"})
    path, q = read_id_query("schedule", None, None, now)
    assert path == "/api2/v2/schedules" and (q["filter[publishDate]"], q["filter[publishDateEnd]"]) == \
        ("2026-11-21", "2026-11-22")
    with pytest.raises(ValueError, match="needs `now`"):
        read_id_query("schedule", None, None)
