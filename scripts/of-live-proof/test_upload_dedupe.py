"""Ticket 97: the upload and duplicate-id proofs (proofs/phase6.py `NEW_POST_UPLOAD`, `NEW_POST_DEDUPE`): FakeOF's
upload chain, posts and Remove from vault (soak/fake_of/posts.py) with the planted faults (fake_layer), the Live
guard on their writes (ticket 30's hide, its `{media}` bound to the id registered through `/__proof/read-id`), and
the proofs' pure helpers and undo (undo_driver `register_keys`, `settle_rows`: each post's DELETE, then the hide).
"""
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest
from starlette.testclient import TestClient

import fake_layer
import of_browser
import undo_driver
from undo_log import needs_row_id, row_undos, undo_order
from proof_core import Request, Run, decide
from proofs.phase2 import S3_HOST
from proofs.phase6 import (NEW_POST_DEDUPE, NEW_POST_UPLOAD, new_media, new_posts, post_media, proof_png,
                           read_posts_and_vault, upload_effect, find_new_post, draft_text)
from soak import ids
from soak.fake_of import posts as fake_posts
from soak.fake_of.app import FakeOF
from soak.fake_of.signing import sign_value
from soak.fake_of.vault import MEDIA_COUNT
from soak.world import World

AT = datetime(2026, 11, 21, 3, 10, tzinfo=timezone.utc)
HASH = "/api2/v2/vault/media/" + "hash"
SEEDED = [ids.vault_media_id(n) for n in range(1, MEDIA_COUNT + 1)]



@pytest.fixture
def fake():
    def make(fault=None):
        of = FakeOF(World(1))
        of.host, of.port = "127.0.0.1", 1
        client = TestClient(fake_layer.Recorder(of.build(), fault, of))

        def req(method, path, **kw):
            t, uid = str(int(time.time() * 1000)), str(of.world.creator_id)
            h = {"user-id": uid, "x-hash": of.x_hash, "time": t,
                 "sign": sign_value(of.rules, time_ms=t, path_qs=path, user_id=uid)}
            r = client.request(method, path, headers=h, **kw)
            return r.status_code, r.json()
        return of, req, client
    return make


def _upload(req, client, data: bytes, name="x.png"):
    """The relay's chain (service/of_upload.py `upload_media`): dedupe, signed/create, S3 PUT, convert claim."""
    md5 = hashlib.md5(data).hexdigest()
    status, hit = req("GET", f"{HASH}?h={md5}&size={len(data)}")
    if status == 200:
        return {"deduped": True, "vault_id": hit["id"], "hidden": hit["hidden"]}
    assert status == 404
    status, signed = req("POST", "/api2/v2/upload/signed/create",
                         json={"key": f"upload/u/1/{name}", "parts": 1, "contentType": "image/png", "secure": False,
                               "userPrefix": "upload"})
    assert status == 200 and signed["key"].startswith("upload/") and signed["uploadToken"]
    u = urlsplit(signed["putUrl"])
    put = client.put(f"{u.path}?{u.query}", content=data)
    assert put.status_code == 200 and put.headers["etag"] == f'"{md5}"'
    claim = client.post("/file/upload", files={"file[ETag]": (None, f'"{md5}"'), "file[Key]": (None, signed["key"]),
                                               "file[uploadToken]": (None, signed["uploadToken"]),
                                               "file[Location]": (None, f"{of_origin(u)}{u.path}")})
    assert claim.status_code == 200
    c = claim.json()
    return {"deduped": False, "send_with": {"processId": c["processId"], "host": c["host"], "name": name,
                                            "extra": c["extra"]}}


def of_origin(u):
    return f"{u.scheme}://{u.netloc}"


def _post(req, media, text="oi-proof-t", ahead=45):
    when = (datetime.now(timezone.utc) + timedelta(minutes=ahead)).isoformat()
    return req("POST", "/api2/v2/posts", json={"text": text, "mediaFiles": media, "price": 0, "isScheduled": 1,
                                               "scheduledDate": when})


def _vault(req):
    return [m["id"] for m in req("GET", "/api2/v2/vault/media?limit=100")[1]["list"]]


def test_fake_upload_post_delete_and_remove_from_vault(fake):
    of, req, client = fake()
    up = _upload(req, client, b"proof bytes a")
    assert up["deduped"] is False
    assert _vault(req) == SEEDED
    status, post = _post(req, [up["send_with"]])
    assert status == 200 and post["id"] == ids.post_id(1)
    x = post["media"][0]["id"]
    assert x == ids.vault_media_id(ids.UPLOADED + 1) and _vault(req) == [x, *SEEDED]
    assert req("GET", f"/api2/v2/posts/{post['id']}")[1]["media"] == post["media"]
    rows = req("GET", "/api2/v2/schedules?limit=50")[1]["list"]
    assert [(r["id"], r["type"], r["entity"]["id"]) for r in rows] == [(ids.post_schedule_id(1), "post", post["id"])]
    again = _upload(req, client, b"proof bytes a")
    assert again == {"deduped": True, "vault_id": x, "hidden": False}
    assert req("DELETE", f"/api2/v2/posts/{post['id']}") == (200, {"success": True})
    assert req("GET", f"/api2/v2/posts/{post['id']}")[0] == 404
    assert req("GET", "/api2/v2/schedules?limit=50")[1]["list"] == []
    assert req("PUT", "/api2/v2/vault/media/hidden", json={"mediaIds": [x]}) == (200, {"success": True})
    assert _vault(req) == SEEDED
    assert _upload(req, client, b"proof bytes a") == {"deduped": True, "vault_id": x, "hidden": True}
    assert _post(req, [x])[0] == 200


def test_fake_post_keeps_a_duplicate_id_and_refuses_unknown_media(fake):
    of, req, client = fake()
    status, post = _post(req, [SEEDED[0], SEEDED[0]])
    assert status == 200 and [m["id"] for m in post["media"]] == [SEEDED[0], SEEDED[0]]
    assert _post(req, [123])[0] == 400
    assert _post(req, [{"processId": "nope"}])[0] == 400
    assert req("POST", "/api2/v2/posts", json={"text": "t", "mediaFiles": [], "isScheduled": 0})[0] == 200
    assert [x["entity"]["id"] for x in req("GET", "/api2/v2/schedules?limit=50")[1]["list"]] == [post["id"]]
    assert req("PUT", "/api2/v2/vault/media/hidden", json={"mediaIds": [123]})[0] == 400


def test_fake_convert_refuses_a_claim_not_naming_the_stored_key_token_and_etag(fake):
    of, req, client = fake()
    signed = req("POST", "/api2/v2/upload/signed/create", json={"key": "upload/u/1/x.png", "parts": 1})[1]
    assert req("POST", "/api2/v2/upload/signed/create", json={"key": "upload/u/1/x.png", "parts": 2})[0] == 400
    u = urlsplit(signed["putUrl"])
    client.put(u.path, content=b"abc")
    md5 = hashlib.md5(b"abc").hexdigest()
    for key, token, etag in (("upload/u/1/x.png", signed["uploadToken"], md5), (signed["key"], "bad", md5),
                             (signed["key"], signed["uploadToken"], "0" * 32)):
        r = client.post("/file/upload", files={"file[ETag]": (None, f'"{etag}"'), "file[Key]": (None, key),
                                               "file[uploadToken]": (None, token)})
        assert r.status_code == 400 and r.json() == {"error": "Invalid input."}
    assert client.put("/upload/u/9/unknown.png", content=b"x").status_code == 404
    bad = req("POST", "/api2/v2/upload/signed/create", json={"key": "upload/u/2/bad.png", "parts": 1})[1]
    etag = client.put(urlsplit(bad["putUrl"]).path, content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\x01IHDR").headers["ETag"]
    r = client.post("/file/upload", files={"file[ETag]": (None, etag), "file[Key]": (None, bad["key"]),
                                           "file[uploadToken]": (None, bad["uploadToken"])})
    assert r.status_code == 400 and r.json()["error"]["message"] == "Image is corrupted"
    assert fake_posts.state(of)["claims"] == {}


def test_dup_id_refused_fault_refuses_only_a_post_holding_one_id_twice(fake):
    of, req, client = fake("dup-id-refused")
    status, body = _post(req, [SEEDED[0], SEEDED[0]])
    assert status == 400 and "duplicate media id" in body["error"]["message"]
    assert req("GET", "/api2/v2/schedules?limit=50")[1]["list"] == []
    assert _post(req, [SEEDED[0], SEEDED[1]])[0] == 200
    hits = client.app.snapshot()
    assert [h.get("fault") for h in hits if h["path"] == "/api2/v2/posts"] == ["dup-id-refused", None]


def test_post_commit_500_fault_makes_the_post_then_answers_500(fake):
    of, req, client = fake("post-commit-500")
    status, body = _post(req, [SEEDED[0]])
    assert status == 500 and body["error"]["code"] == 500
    rows = req("GET", "/api2/v2/schedules?limit=50")[1]["list"]
    assert [r["entity"]["id"] for r in rows] == [ids.post_id(1)]
    assert [h.get("fault") for h in client.app.snapshot() if h["path"] == "/api2/v2/posts"] == ["post-commit-500"]


def test_composer_once_is_an_app_fault_unknown_to_fakeof():
    f = fake_layer.FAULTS["composer-once"]
    assert isinstance(f, fake_layer.AppFault) and f.hook is fake_layer.composer_once
    with pytest.raises(ValueError, match="unknown FakeOF fault"):
        fake_layer.Recorder(None, "composer-once")
    assert of_browser.dedupe_media([5, {"processId": "p"}, 5, 6, 6]) == [5, {"processId": "p"}, 6]


def test_prove_fault_choices_and_usage_are_the_fault_table_plus_wrong_creator(monkeypatch):
    import argparse
    import re
    import live_entry
    import prove
    want = set(fake_layer.FAULTS) | set(fake_layer.STATES) | {live_entry.WRONG_CREATOR}
    seen = {}

    def grab(self, argv=None):
        seen["choices"] = next(a.choices for a in self._actions if a.dest == "fault")
        raise SystemExit(0)
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", grab)
    with pytest.raises(SystemExit):
        prove.main(["--of", "fake"])
    assert set(seen["choices"]) == want
    usage = prove.__doc__.split("[--fault ", 1)[1].split("]", 1)[0]
    assert set(re.sub(r"\s+", "", usage).split("|")) == want


def test_composer_once_hook_sends_each_media_id_once_and_records_it():
    from types import SimpleNamespace
    planted, sent = [], []
    hook = fake_layer.FAULTS["composer-once"].hook(planted)
    route = SimpleNamespace(continue_=lambda **kw: sent.append(kw))

    def req(method, path, body):
        return SimpleNamespace(method=method, url=f"http://127.0.0.1:1{path}", post_data=json.dumps(body))
    assert not hook(route, req("POST", "/api/of/v2/posts", {"media_files": [5, 6]}))
    assert not hook(route, req("POST", "/api/of/v2/other", {"media_files": [5, 5]}))
    assert not hook(route, req("GET", "/api/of/v2/posts", {"media_files": [5, 5]}))
    assert sent == [] and planted == []
    assert hook(route, req("POST", "/api/of/v2/posts", {"text": "t", "media_files": [5, 5]}))
    assert [json.loads(k["post_data"]) for k in sent] == [{"text": "t", "media_files": [5]}]
    assert planted == [{"method": "POST", "path": "/api/of/v2/posts", "media_files": [5, 5]}]



def R(method, path, body=None, host="onlyfans.com"):
    return Request(method=method, host=host, path=path, body=body, at=AT)


def post_body(media, ahead=45, **kw):
    return {"text": "oi-proof-x", "mediaFiles": media, "price": 0, "isScheduled": 1,
            "scheduledDate": (AT + timedelta(minutes=ahead)).isoformat(), **kw}


POST_ID, X = str(ids.post_id(1)), ids.vault_media_id(ids.UPLOADED + 1)
SPENT = {("arm", i): 1 for i in range(4)}
MEDIA = {"media": frozenset({str(X)})}
BY_POST = {3: frozenset({POST_ID})}


@pytest.mark.parametrize("why, request_, run, kind", [
    ("signed/create", R("POST", "/api2/v2/upload/signed/create", {"key": "upload/x"}), Run(proof=NEW_POST_UPLOAD),
     "allow"),
    ("the S3 PUT", R("PUT", "/upload/900000000000000001/9f1c/123/clip.png", host=S3_HOST),
     Run(proof=NEW_POST_UPLOAD, hosts=(S3_HOST,)), "allow"),
    ("the S3 PUT on onlyfans.com, live", R("PUT", "/upload/900000000000000001/9f1c/123/clip.png"),
     Run(proof=NEW_POST_UPLOAD, hosts=(S3_HOST,)), "refused"),
    ("the S3 PUT on FakeOF's origin, fake", R("PUT", "/upload/900000000000000001/9f1c/123/clip.png"),
     Run(proof=NEW_POST_UPLOAD, hosts=(S3_HOST,), of="fake"), "allow"),
    ("the S3 PUT, no host armed", R("PUT", "/upload/900000000000000001/9f1c/123/clip.png", host=S3_HOST),
     Run(proof=NEW_POST_UPLOAD), "refused"),
    ("the convert claim", R("POST", "/file/upload", host="convert.onlyfans.com"),
     Run(proof=NEW_POST_UPLOAD, hosts=(S3_HOST,)), "allow"),
    ("a post 45 min ahead", R("POST", "/api2/v2/posts", post_body([{"processId": "p"}])), Run(proof=NEW_POST_UPLOAD),
     "allow"),
    ("a post 10 min ahead", R("POST", "/api2/v2/posts", post_body([1], ahead=10)), Run(proof=NEW_POST_UPLOAD),
     "refused"),
    ("a second post in A", R("POST", "/api2/v2/posts", post_body([1])), Run(proof=NEW_POST_UPLOAD, spent=SPENT),
     "refused"),
    ("a second post in B", R("POST", "/api2/v2/posts", post_body([X, X])), Run(proof=NEW_POST_DEDUPE, spent=SPENT),
     "allow"),
    ("delete of its own post", R("DELETE", f"/api2/v2/posts/{POST_ID}"),
     Run(proof=NEW_POST_UPLOAD, spent=SPENT, created=frozenset({POST_ID}), created_by=BY_POST), "reversal"),
    ("a second delete in A", R("DELETE", f"/api2/v2/posts/{POST_ID}"),
     Run(proof=NEW_POST_UPLOAD, spent={**SPENT, ("undo", 0): 1}, created=frozenset({POST_ID}),
         created_by=BY_POST), "refused"),
    ("B's second post deleted", R("DELETE", f"/api2/v2/posts/{POST_ID}"),
     Run(proof=NEW_POST_DEDUPE, spent={**SPENT, ("undo", 0): 1}, created=frozenset({POST_ID}),
         created_by=BY_POST), "reversal"),
    ("delete of another post", R("DELETE", "/api2/v2/posts/42"),
     Run(proof=NEW_POST_UPLOAD, spent=SPENT, created=frozenset({POST_ID}), created_by=BY_POST), "refused"),
    ("hide of its registered upload", R("PUT", "/api2/v2/vault/media/hidden", {"mediaIds": [X]}),
     Run(proof=NEW_POST_UPLOAD, spent=SPENT, created=frozenset({POST_ID}), keys=MEDIA), "reversal"),
    ("hide of an upload not registered", R("PUT", "/api2/v2/vault/media/hidden", {"mediaIds": [X]}),
     Run(proof=NEW_POST_UPLOAD, spent=SPENT, created=frozenset({POST_ID, str(X)})), "refused"),
    ("hide of a vault item it did not make", R("PUT", "/api2/v2/vault/media/hidden", {"mediaIds": [SEEDED[0]]}),
     Run(proof=NEW_POST_UPLOAD, spent=SPENT, created=frozenset({POST_ID}), keys=MEDIA), "refused"),
    ("hide of its upload and another", R("PUT", "/api2/v2/vault/media/hidden", {"mediaIds": [X, SEEDED[0]]}),
     Run(proof=NEW_POST_UPLOAD, spent=SPENT, created=frozenset({POST_ID}), keys=MEDIA), "refused"),
    ("hide of X_B twice", R("PUT", "/api2/v2/vault/media/hidden", {"mediaIds": [X, X]}),
     Run(proof=NEW_POST_DEDUPE, spent=SPENT, created=frozenset({POST_ID}), keys=MEDIA), "refused"),
    ("B's hide of X_B once", R("PUT", "/api2/v2/vault/media/hidden", {"mediaIds": [X]}),
     Run(proof=NEW_POST_DEDUPE, spent=SPENT, created=frozenset({POST_ID}), keys=MEDIA), "reversal"),
], ids=lambda x: x if isinstance(x, str) else "")
def test_guard_on_upload_and_post_writes(why, request_, run, kind):
    v = decide(request_, run)
    assert v.kind == kind, (why, v)


def test_scheduled_post_is_not_fan_visible():
    assert not decide(R("POST", "/api2/v2/posts", post_body([1])), Run(proof=NEW_POST_UPLOAD)).fan_visible



RUN = "oi-proof-r"
UP_TEXT, DE_TEXT = draft_text(RUN, "upload"), draft_text(RUN, "dedupe")
BEFORE = {"queue": [], "vault": SEEDED}
A_AFTER = {"queue": [[ids.post_schedule_id(1), ids.post_id(1), UP_TEXT, X]], "vault": sorted([X, *SEEDED])}
B_AFTER = {"queue": [[ids.post_schedule_id(1), ids.post_id(1), DE_TEXT, X],
                     [ids.post_schedule_id(2), ids.post_id(2), DE_TEXT, X, X]], "vault": sorted([X, *SEEDED])}


def test_read_posts_and_vault_keeps_post_items_with_their_media():
    def get(path, params):
        if path == "/api2/v2/schedules":
            return {"list": [{"id": 9, "type": "chat", "entity": {"id": 3}},
                             {"id": 8, "type": "post", "entity": {"id": 2}}]}
        if path == "/api2/v2/posts/2":
            return {"id": 2, "text": "<p>t</p>", "rawText": "t", "media": [{"id": 7}, {"id": 7}]}
        return {"list": [{"id": 5}, {"id": 4}]}
    assert read_posts_and_vault(get, None) == {"queue": [[8, 2, "t", 7, 7]], "vault": [4, 5]}


def test_effects_and_new_ids():
    assert upload_effect(BEFORE, A_AFTER) and not upload_effect(BEFORE, BEFORE)
    assert not upload_effect(BEFORE, {"queue": [[1, 2, UP_TEXT, SEEDED[0]]], "vault": SEEDED})
    assert upload_effect(BEFORE, B_AFTER)
    assert new_posts(BEFORE, B_AFTER) == [ids.post_id(1), ids.post_id(2)] and new_media(BEFORE, B_AFTER) == [X]


def test_post_media_keys_each_new_post_holding_one_media_id():
    p1, p2 = str(ids.post_id(1)), str(ids.post_id(2))
    assert post_media(BEFORE, A_AFTER) == {p1: {"media": X}}
    assert post_media(BEFORE, B_AFTER) == {p1: {"media": X}, p2: {"media": X}}
    two = {"queue": [[1, 7, UP_TEXT, X, SEEDED[0]]], "vault": B_AFTER["vault"]}
    assert post_media(BEFORE, two) == {} and post_media(BEFORE, BEFORE) == {}


OTHER = [ids.post_schedule_id(9), ids.post_id(9), "an operator's post", X]


@pytest.mark.parametrize("suffix, after, want", [
    ("upload", A_AFTER, ids.post_id(1)),
    ("upload", {"queue": [OTHER], "vault": A_AFTER["vault"]}, None),
    ("upload", {"queue": [OTHER, A_AFTER["queue"][0]], "vault": A_AFTER["vault"]}, ids.post_id(1)),
    ("upload", {"queue": [[1, 5, RUN, X]], "vault": A_AFTER["vault"]}, None),
    ("upload", {"queue": [[1, 5, draft_text("oi-proof-other", "upload"), X]], "vault": A_AFTER["vault"]}, None),
    ("dedupe", A_AFTER, None),
    ("dedupe", B_AFTER, None),
    ("dedupe", {"queue": B_AFTER["queue"][:1] + [OTHER], "vault": B_AFTER["vault"]}, ids.post_id(1)),
    ("upload", BEFORE, None),
], ids=["marked", "unmarked", "marked + unmarked", "marker only", "another run", "other suffix", "two marked",
        "dedupe marked + unmarked", "none"])
def test_lost_post_finder_takes_only_the_one_post_with_the_seeded_text(suffix, after, want):
    assert find_new_post(suffix)(BEFORE, after, RUN) == want


@pytest.mark.parametrize("after, want", [
    (A_AFTER, {str(ids.post_id(1)): {"media": X}}),
    ({"queue": [[1, 7, UP_TEXT, SEEDED[0]]], "vault": A_AFTER["vault"]}, {}),
    ({"queue": [[1, 7, UP_TEXT, SEEDED[0]]], "vault": SEEDED}, {}),
    ({"queue": [A_AFTER["queue"][0], [1, 7, "x", SEEDED[1]]], "vault": A_AFTER["vault"]},
     {str(ids.post_id(1)): {"media": X}}),
], ids=["new medium", "old medium", "nothing new", "new + old"])
def test_post_media_never_keys_a_medium_the_vault_had_before(after, want):
    assert post_media(BEFORE, after) == want


def test_both_proofs_undo_each_post_then_hide_the_registered_media():
    for p in (NEW_POST_UPLOAD, NEW_POST_DEDUPE):
        assert p.find(BEFORE, A_AFTER, RUN) == (ids.post_id(1) if p is NEW_POST_UPLOAD else None)
        assert p.undo_keys is post_media and p.undo_steps is None and p.undo_ids is None
        assert [(w.method, w.path, w.reverses) for w in p.undo] == [
            ("DELETE", "/api2/v2/posts/{id}", (3,)), ("PUT", "/api2/v2/vault/media/hidden", (0, 1, 2, 3))]
        assert p.undo[1].body_must == {"mediaIds": ["{media}"]} and p.undo[1].relay_method == "POST"
        assert p.undo[1].relay == "/admin/vault-ai/items/{media}/hide"
    assert NEW_POST_UPLOAD.undo[0].max == 1 and NEW_POST_DEDUPE.undo[0].max == 2


def test_proof_png_is_a_png_with_its_own_bytes():
    a, b = proof_png("oi-proof-1", "new-post--upload"), proof_png("oi-proof-1", "new-post--dedupe-duplicate-id")
    assert a.startswith(b"\x89PNG\r\n\x1a\n") and a != b and a == proof_png("oi-proof-1", "new-post--upload")



class Wire:
    """A stub Relay: each reversal answered `status`, logged as the wire log would; `/__proof/read-id` answers
    `read_id_status`."""

    def __init__(self, status=200, read_id_status=200):
        self.status, self.read_id_status, self.lines, self.calls = status, read_id_status, [], []

    def __call__(self, method, route, data=None, account=None):
        self.calls.append((method, route, data, account))
        if route == "/__proof/read-id":
            return self.read_id_status, b"{}"
        path = "/api2/v2/vault/media/hidden" if route.endswith("/hide") else route.replace("/api/of/v2", "/api2/v2")
        self.lines.append({"seq": len(self.lines) + 1, "method": "PUT" if route.endswith("/hide") else method,
                           "path": path, "status": self.status, "verdict": "reversal"})
        return (200 if self.status < 300 else 502), b""

    def wire(self):
        return list(self.lines)


UP_ROW = {"row": 1, "arm": 0, "write": {"method": "POST", "path": "/api2/v2/upload/signed/create"}, "of_id": None}


def POST_ROW(n, post, **kw):
    return {"row": n, "arm": 3, "write": {"method": "POST", "path": "/api2/v2/posts"}, "of_id": post, **kw}


def _undo(w, rows, after_undo=BEFORE, proof=NEW_POST_DEDUPE, after=B_AFTER):
    """The driver as prove.py runs it: each key-source row's keys registered first, then the rows settled."""
    res, keys = {"problems": [], "screens": []}, {}
    for r in rows:
        if undo_driver.is_key_source(proof, r):
            undo_driver.register_keys(proof, r, BEFORE, lambda: after, w, res["problems"], keys)
    closed = undo_driver.settle_rows(proof, undo_order(proof, rows), w, w.wire, lambda tag: after_undo,
                                     creator="1", before=BEFORE, after=after, effect=True, keys=keys, sent={},
                                     res=res)
    return closed, res


def _sent(w):
    return [(m, r, d) for m, r, d, _ in w.calls if r != "/__proof/read-id"]


P1, P2 = str(ids.post_id(1)), str(ids.post_id(2))


def test_undo_deletes_both_posts_then_hides_x_b_once_for_every_row():
    w = Wire()
    closed, res = _undo(w, [UP_ROW, POST_ROW(2, P1), POST_ROW(3, P2)])
    assert res["problems"] == [] and [x["state"] for x in closed] == ["undone"] * 3
    assert _sent(w) == [("DELETE", f"/api/of/v2/posts/{P1}", None), ("DELETE", f"/api/of/v2/posts/{P2}", None),
                        ("POST", f"/admin/vault-ai/items/{X}/hide", {"account_id": "1"})]
    assert [d for _, r, d, _ in w.calls if r == "/__proof/read-id"] == [
        {"row": 2, "key": "media", "of_id": str(X), "source": P1}]
    assert w.calls[0][1] == "/__proof/read-id"
    by = {c["row"]: [rv["path"] for rv in c["reversals"]] for c in closed}
    assert by == {1: ["/api2/v2/vault/media/hidden"],
                  2: [f"/api2/v2/posts/{P1}", "/api2/v2/vault/media/hidden"],
                  3: [f"/api2/v2/posts/{P2}", "/api2/v2/vault/media/hidden"]}


def test_undo_of_a_refused_second_post_takes_only_the_shared_hide():
    w = Wire()
    refused = POST_ROW(3, None, write_status=400)
    closed, res = _undo(w, [UP_ROW, POST_ROW(2, P1), refused],
                        after={"queue": B_AFTER["queue"][:1], "vault": B_AFTER["vault"]})
    assert res["problems"] == [] and [x["state"] for x in closed] == ["undone"] * 3
    assert _sent(w) == [("DELETE", f"/api/of/v2/posts/{P1}", None),
                        ("POST", f"/admin/vault-ai/items/{X}/hide", {"account_id": "1"})]
    assert [rv["path"] for rv in closed[2]["reversals"]] == ["/api2/v2/vault/media/hidden"]


def test_undo_with_the_media_registration_refused_deletes_the_posts_and_sends_no_hide():
    w = Wire(read_id_status=409)
    closed, res = _undo(w, [UP_ROW, POST_ROW(2, P1)], after_undo={"queue": [], "vault": B_AFTER["vault"]})
    assert _sent(w) == [("DELETE", f"/api/of/v2/posts/{P1}", None)]
    assert [x["state"] for x in closed] == ["FAILED", "FAILED"]
    assert any("refused read id media" in p for p in res["problems"])


def test_undo_answered_500_closes_failed():
    w = Wire(status=500)
    closed, res = _undo(w, [POST_ROW(2, P1)], proof=NEW_POST_UPLOAD, after=A_AFTER, after_undo=A_AFTER)
    assert [x["state"] for x in closed] == ["FAILED"] and any("answered 500" in p for p in res["problems"])


def test_fake_check_counts_only_the_post_writes_after_each_row_opened():
    """B's two posts open two rows on one path: the later row's window holds only its own write (run 052328Z)."""
    t0 = AT.timestamp()

    def at(s):
        return datetime.fromtimestamp(t0 + s, timezone.utc).isoformat()

    def hit(s, method, path, body=None):
        return {"t": t0 + s, "method": method, "path": path, "body": body, "status": 200}

    keys = {"media": str(X)}
    rows = [POST_ROW(2, P1, opened=at(0), closed=at(7), keys=keys),
            POST_ROW(3, P2, opened=at(2), closed=at(7), keys=keys)]
    plain = [hit(1, "POST", "/api2/v2/posts"), hit(3, "POST", "/api2/v2/posts"),
             hit(4, "DELETE", f"/api2/v2/posts/{P1}"), hit(5, "DELETE", f"/api2/v2/posts/{P2}"),
             hit(6, "PUT", "/api2/v2/vault/media/hidden", {"mediaIds": [X]})]
    assert [undo_driver.row_problem(NEW_POST_DEDUPE, c, rows, plain) for c in rows] == [None, None]
    retried = plain + [hit(3.5, "POST", "/api2/v2/posts")]
    assert all(undo_driver.row_problem(NEW_POST_DEDUPE, c, rows, retried) for c in rows)



@pytest.mark.parametrize("status, deletes", [(400, False), (404, False), (500, True), (502, True),
                                             ("reply lost: OFAPIError", True)])
def test_only_a_4xx_post_create_drops_the_delete(status, deletes):
    row = POST_ROW(3, None, write_status=status)
    assert any(w.method == "DELETE" for _, w in row_undos(NEW_POST_UPLOAD, row)) is deletes
    assert needs_row_id(NEW_POST_UPLOAD, row) is deletes


def test_a_5xx_post_found_after_is_deleted_then_hidden_and_passes_the_fake_check():
    w = Wire()
    found = POST_ROW(2, P1, write_status=500, found_by="after-write read")
    closed, res = _undo(w, [UP_ROW, found], proof=NEW_POST_UPLOAD, after=A_AFTER)
    assert res["problems"] == [] and [x["state"] for x in closed] == ["undone", "undone"]
    assert _sent(w) == [("DELETE", f"/api/of/v2/posts/{P1}", None),
                        ("POST", f"/admin/vault-ai/items/{X}/hide", {"account_id": "1"})]
    t0 = AT.timestamp()
    at = lambda s: datetime.fromtimestamp(t0 + s, timezone.utc).isoformat()  # noqa: E731
    row = {**found, "opened": at(0), "closed": at(9), "keys": {"media": str(X)}}
    plain = [{"t": t0 + 1, "method": "POST", "path": "/api2/v2/posts", "status": 500, "body": None},
             {"t": t0 + 2, "method": "DELETE", "path": f"/api2/v2/posts/{P1}", "status": 200, "body": None},
             {"t": t0 + 3, "method": "PUT", "path": "/api2/v2/vault/media/hidden", "status": 200,
              "body": {"mediaIds": [X]}}]
    assert undo_driver.row_problem(NEW_POST_UPLOAD, row, [row], plain) is None
