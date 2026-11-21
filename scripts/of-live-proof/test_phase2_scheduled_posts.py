"""FakeOF's scheduled posts and the upload behind them (soak/fake_of/posts.py): the Record proofs' before, after-write
and after-undo reads through the fake's real routes (signature check included), read by the proof's own reader.
Ticket 136 (live read docs/of-manager/captures/queue--scheduled-post-endpoint.json): a dated post is only in
`GET /schedules` (date range honoured, limit/offset ignored, `{list, syncInProcess}`); `later/post` lists undated
ones."""
import hashlib
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

import pytest
from starlette.testclient import TestClient

import fake_layer  # noqa: F401  (puts the repo root on sys.path for soak/)
from proofs import phase2
from soak.fake_of import posts
from soak.fake_of.app import FakeOF
from soak.fake_of.signing import sign_value
from soak.world import World

LATER = "/api2/v2/schedules/later/post"
SCHEDULES = "/api2/v2/schedules"


def _fake():
    fake = FakeOF(World(seed=1))
    client = TestClient(fake.build())

    def call(method, path_qs, json=None, status=200, signed=True, **kw):
        h = {}
        if signed:
            t, uid = str(int(time.time() * 1000)), str(fake.world.creator_id)
            h = {"user-id": uid, "x-hash": fake.x_hash, "time": t,
                 "sign": sign_value(fake.rules, time_ms=t, path_qs=path_qs, user_id=uid)}
        r = client.request(method, path_qs, headers=h, json=json, **kw)
        assert r.status_code == status, (method, path_qs, r.status_code, r.text[:200])
        return r

    def get(path, params):
        return call("GET", f"{path}?{urlencode(params)}" if params else path).json()
    return fake, call, get


def _soon():
    """Ten days ahead, inside the reader's window (the proofs' next month's first day is at most ~31 days out)."""
    return (datetime.now(timezone.utc) + timedelta(days=10)).replace(microsecond=0).isoformat()


def _schedule(call, text, media=1, when=None):
    """The Relay's upload_media + create_post, as FakeOF sees them: signed create, storage PUT, convert (the claim
    of_upload sends: OF's key, the token, the PUT's ETag), the post."""
    signed = call("POST", "/api2/v2/upload/signed/create", json={"key": "upload/u/1/rec.webm", "parts": 1}).json()
    put_path = signed["putUrl"].split("://", 1)[1].split("/", 1)[1]
    etag = call("PUT", f"/{put_path}", signed=False, content=text.encode()).headers["etag"]
    assert etag == f'"{hashlib.md5(text.encode()).hexdigest()}"'
    claim = call("POST", "/file/upload", signed=False, data={"file[ETag]": etag, "file[Key]": signed["key"],
                                                              "file[uploadToken]": signed["uploadToken"]}).json()
    return call("POST", "/api2/v2/posts", json={
        "text": text, "isScheduled": 1, "scheduledDate": when or _soon(),
        "mediaFiles": [{"processId": claim["processId"], "host": claim["host"], "name": "rec.webm"}] * media}).json()


def _range(start, end, tz="UTC", **extra):
    return f"{SCHEDULES}?" + urlencode({"filter[publishDate]": start, "filter[publishDateEnd]": end,
                                        "filter[timeZone]": tz, **extra})


def test_both_lists_start_empty_in_the_captured_envelopes():
    _, call, get = _fake()
    assert call("GET", f"{LATER}?limit=10&offset=0").json() == {"list": [], "hasMore": False, "syncInProcess": False}
    assert call("GET", _range("2026-11-21", "2027-11-21", limit=10)).json() == {"list": [], "syncInProcess": False}
    assert phase2.read_scheduled_posts(get, None) == []


def test_a_dated_post_is_in_schedules_and_not_in_later_post():
    _, call, _ = _fake()
    post = _schedule(call, "oi-proof-dated", when="2026-12-01T00:00:00+00:00")
    assert call("GET", f"{LATER}?limit=10&offset=0").json()["list"] == []   # later/post: saved-for-later only
    rows = call("GET", _range("2026-11-21", "2026-12-31", limit=10)).json()["list"]
    assert [(r["type"], r["publishDateTime"], r["entity"]["id"]) for r in rows] == [
        ("post", "2026-12-01T00:00:00+00:00", post["id"])]
    assert set(rows[0]) == {"id", "type", "publishDateTime", "createdDateTime", "entity"}


def test_an_undated_post_is_in_later_post_only():
    _, call, _ = _fake()
    post = call("POST", "/api2/v2/posts", json={"text": "later", "isScheduled": 1, "mediaFiles": []}).json()
    page = call("GET", f"{LATER}?limit=10&offset=0").json()
    assert [(r["publishDateTime"], r["entity"]["id"]) for r in page["list"]] == [(None, post["id"])]
    assert call("GET", _range("2000-01-01", "2100-01-01")).json()["list"] == []


def test_schedules_honours_the_date_range_and_ignores_limit_and_offset():
    _, call, _ = _fake()
    a = _schedule(call, "a", when="2026-11-25T10:00:00+00:00")
    b = _schedule(call, "b", when="2026-12-10T10:00:00+00:00")
    ids = lambda q: [r["entity"]["id"] for r in call("GET", q).json()["list"]]  # noqa: E731
    assert ids(_range("2026-11-21", "2026-12-31", limit=1, offset=0)) == [a["id"], b["id"]]
    assert ids(_range("2026-11-21", "2026-12-31", limit=1, offset=1)) == [a["id"], b["id"]]
    assert ids(_range("2026-11-21", "2026-12-01")) == [a["id"]]
    assert ids(_range("2026-12-10", "2026-12-10")) == [b["id"]]   # both ends inclusive
    assert ids(_range("2026-12-11", "2027-01-01")) == []
    assert "hasMore" not in call("GET", _range("2026-11-21", "2026-12-31")).json()


def test_schedules_reads_the_day_in_the_named_time_zone():
    _, call, _ = _fake()
    late = _schedule(call, "late", when="2026-12-01T23:30:00+00:00")   # 2 Dec in Berlin
    ids = lambda q: [r["entity"]["id"] for r in call("GET", q).json()["list"]]  # noqa: E731
    assert ids(_range("2026-12-01", "2026-12-01")) == [late["id"]]
    assert ids(_range("2026-12-01", "2026-12-01", tz="Europe/Berlin")) == []
    assert ids(_range("2026-12-02", "2026-12-02", tz="Europe/Berlin")) == [late["id"]]


def test_the_reader_asks_schedules_once_over_the_window_in_the_browser_time_zone():
    asked = []
    today = date(2026, 11, 21)
    phase2.scheduled_post_items(lambda path, q: asked.append((path, q)) or {"list": [], "syncInProcess": False},
                                today=today)
    assert asked == [(SCHEDULES, {"filter[publishDate]": "2026-11-20", "filter[publishDateEnd]": "2027-01-05",
                                  "filter[timeZone]": "UTC", "limit": 100})]


def _row(type_, entity=None, **kw):
    return {"id": 70, "type": type_, "publishDateTime": "2026-12-01T00:00:00+00:00", **kw,
            **({"entity": entity} if entity is not None else {})}


@pytest.mark.parametrize("rows,want", [
    ([_row("post", {"id": 9, "rawText": "p"})], ["9"]),
    ([_row("chat", {"id": 8, "text": "mass"}), _row("post", {"id": 9, "rawText": "p"})], ["9"]),   # chat skipped
    ([_row("chat", {"id": 8, "text": "mass"})], []),
    ([_row("chat")], []),                                           # a chat row's shape is not the post's business
    ([_row("post")], ValueError),                                   # a post row without `entity`
    ([{"id": 70, "entity": {"id": 9}}], ValueError),                # no `type`: not OF's captured shape
    (["junk"], ValueError),
])
def test_the_reader_keeps_post_rows_only(rows, want):
    get = lambda path, q: {"list": rows, "syncInProcess": False}  # noqa: E731
    if want is ValueError:
        with pytest.raises(ValueError):
            phase2.scheduled_post_items(get)
    else:
        assert [str(p["id"]) for p in phase2.scheduled_post_items(get)] == want


@pytest.mark.parametrize("bad", [{"filter[timeZone]": "{tz}"}, {"filter[publishDate]": "{today}"},
                                 {"filter[publishDateEnd]": "2026-13-01"}])
def test_schedules_refuses_a_malformed_filter(bad):
    _, call, _ = _fake()
    call("GET", _range("2026-11-21", "2026-12-31", **bad), status=400)


def test_the_reader_ignores_later_post():
    pages = {SCHEDULES: {"list": [], "syncInProcess": False},
             LATER: {"list": [{"id": 1, "type": "post", "publishDateTime": None, "entity": {"id": 9}}],
                     "hasMore": False}}
    assert phase2.scheduled_post_items(lambda path, q: pages[path]) == []


def test_record_post_appears_after_write_and_is_gone_after_undo():
    fake, call, get = _fake()
    before = phase2.read_scheduled_posts(get, None)
    post = _schedule(call, "oi-proof-abc")
    after = phase2.read_scheduled_posts(get, None)
    assert phase2.one_new_marked_post_with_media(before, after)
    assert phase2.find_marked_post(before, after, "oi-proof-abc") == str(post["id"])
    keys = phase2.vault_media(before, after)
    media = keys[str(post["id"])]["media"]
    row = call("GET", _range("2000-01-01", "2100-01-01")).json()["list"][0]
    assert row["id"] != post["id"] and row["entity"]["id"] == post["id"]   # the queue row's id is not the post's
    call("DELETE", f"/api2/v2/posts/{post['id']}")
    call("PUT", "/api2/v2/vault/media/hidden", json={"mediaIds": [int(media)]})
    assert phase2.read_scheduled_posts(get, None) == before and posts.hidden(fake) == {media}
    call("DELETE", f"/api2/v2/posts/{post['id']}", status=404)


def test_unscheduled_posts_are_on_neither_list():
    _, call, get = _fake()
    first, second = _schedule(call, "a"), _schedule(call, "b")
    call("POST", "/api2/v2/posts", json={"text": "now", "mediaFiles": []})   # not scheduled: on neither list
    assert call("GET", f"{LATER}?limit=10&offset=0").json()["list"] == []
    assert [r[0] for r in phase2.read_scheduled_posts(get, None)] == sorted([str(first["id"]), str(second["id"])])



@pytest.mark.parametrize("pid", ["p2.record-video", "settings--profile-cover-avatar"])
def test_signed_create_answers_ofs_live_put_shape_the_record_arm_matches(pid):
    """Live run 2026-11-21 (wire seq 45): OF's putUrl carries the Creator's id spliced into our key
    (service/of_upload.py request_signed_upload); FakeOF answers the same shape, and each uploading proof's storage PUT
    arm (Record video's; ticket 67's cover) matches it on S3_HOST."""
    from proofs import ALL
    from undo_driver import arm_hit
    fake, call, _ = _fake()
    signed = call("POST", "/api2/v2/upload/signed/create", json={"key": "upload/u/1/rec.webm", "parts": 1}).json()
    path = "/" + signed["putUrl"].split("://", 1)[1].split("/", 1)[1].split("?", 1)[0]
    assert path == f"/upload/{fake.world.creator_id}/u/1/rec.webm"
    put = ALL[pid].arm[phase2.UPLOAD[1]]
    assert arm_hit((put,), {"method": "PUT", "path": path}) and put.host == phase2.S3_HOST


@pytest.mark.parametrize("body", [{"key": "upload/u/1/voice-1.m4a", "parts": 1, "contentType": "audio/mp4"},
                                  {"key": "upload/u/1/voice-1.m4a", "parts": 1},
                                  {"key": "upload/u/1/voice-1", "parts": 1, "contentType": "audio/mp4;codecs=mp4a"}])
def test_signed_create_refuses_the_voice_type_of_refused_live(body):
    """Ticket 53v, live 2026-11-21 (p2.record-voice): OF's signed/create answered 400 "Invalid file type" for
    contentType audio/mp4, key voice-<n>.m4a; FakeOF answers the same, so the fake run reproduces it."""
    fake, call, _ = _fake()
    r = call("POST", "/api2/v2/upload/signed/create", json=body, status=400)
    assert r.json() == {"error": {"code": 0, "message": "Invalid file type"}}
    assert fake.hits[-1].status == 400


@pytest.mark.parametrize("name,ctype", [("voice-1.wav", "audio/wav"), ("voice-1.ogg", "audio/ogg"),
                                        ("voice-1.mp3", "audio/mpeg"), ("video-1.mp4", "video/mp4")])
def test_signed_create_takes_ofs_own_voice_types_and_video(name, ctype):
    """OF's own voice recorder's types (app/lib/ofMirrorComposer.ts VOICE_TYPES) and Record video's (live pass)."""
    _, call, _ = _fake()
    signed = call("POST", "/api2/v2/upload/signed/create",
                  json={"key": f"upload/u/1/{name}", "parts": 1, "contentType": ctype}).json()
    assert signed["putUrl"].split("?", 1)[0].endswith(f"/u/1/{name}")
