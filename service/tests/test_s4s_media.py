#!/usr/bin/env python3
"""S4S media and the tamper check (ADR-0015; W7 rows 7.6 and 7.11).

The seam is the Relay over HTTP on the two-Agency bench, and the `s4s_post`
and `s4s_check` automations run directly, with `ax._make_client` patched to a
fake: no OnlyFans call is possible. The fake answers each account's vault
read, serves bytes for the post-time download and the preview, records each
upload and post, and answers `get_post` as a case sets it. Nothing is stored
on disk but the temporary directory a post uploads from.

Run: ./venv/bin/python service/tests/test_s4s_media.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import automation_executor as ax  # noqa: E402 — the shared _make_client seam
import automations.s4s_check as s4s_check  # noqa: E402 — registers
import automations.s4s_post as s4s_post  # noqa: E402 — registers
import s4s_media  # noqa: E402
from _s4s_fixtures import IDS, db, list_in_discovery, profile, seed_creators, with_env  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Post, S4SMedia, S4SRequest, S4SSlot, ScheduledJob  # noqa: E402
from of_client import OFAPIError  # noqa: E402

A = IDS["creator_a"]
B = IDS["creator_b"]
C = "1000051"  # Agency A, never in a request with B
seed_creators({C: "agency_a_owner"})
OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
CAPTION = {A: list_in_discovery(OWNER_A, A, "Fixture Alpha", "fixture_alpha"),
           B: list_in_discovery(OWNER_B, B, "Fixture Beta", "fixture_beta"),
           C: list_in_discovery(OWNER_A, C, "Fixture Gamma", "fixture_gamma")}
PID = {aid: profile(o, aid)["profile_id"] for aid, o in ((A, OWNER_A), (B, OWNER_B), (C, OWNER_A))}
PRIMARY = {aid: profile(o, aid)["posts"][0]["id"] for aid, o in ((A, OWNER_A), (B, OWNER_B), (C, OWNER_A))}
FLAG = "S4S_LIVE_POSTING"
CDN = "https://cdn2.onlyfans.com/files/a/b/"
# No 11-second spacing between this suite's fake writes.
ax.of_write_paced.__kwdefaults__["min_gap_s"] = 0.0


def photo(vid: int, url: str | None = None, **extra) -> dict:
    return {"id": vid, "type": "photo", "files": {"full": {"url": url or f"{CDN}{vid}.jpg"}}, **extra}


class Response:
    def __init__(self, body: bytes, status: int = 200):
        self.status_code, self._body = status, body
        self.content, self.headers = body, {"content-type": "image/jpeg"}

    def iter_content(self, chunk_size):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def close(self):
        pass


class Fake:
    """The of-client for every account: a vault (id → item), downloads,
    uploads and posts recorded with the account that made them."""

    def __init__(self, vault=None, *, upload_raises=None, post_now=None, post_raises=None):
        self.vault = vault or {}
        self.reads: list[tuple[str, int]] = []
        self.gets: list[str] = []
        self.status = 200
        self.uploads: list[tuple[str, str, bytes]] = []
        self.upload_paths: list = []
        self.posts: list[dict] = []
        self.upload_raises = upload_raises
        self.post_now, self.post_raises = post_now, post_raises
        self.body = b"x" * 1000
        ax._make_client = self._client  # type: ignore[attr-defined]
        ax._next_write_at.clear()

    def _client(self, account_id):
        fake = self

        class Http:
            def get(self, url, **kw):
                assert kw.get("allow_redirects") is False, kw
                fake.gets.append(url)
                return Response(fake.body, fake.status)

        class Client:
            http = Http()
            timeout_s = 5
            user_id = "999"

            def vault_media_by_id(self, vid):
                fake.reads.append((account_id, vid))
                item = fake.vault.get((account_id, vid))
                if item is None:
                    raise OFAPIError("404 Media Not Found")
                return item

            def upload_media(self, path):
                if fake.upload_raises is not None:
                    raise fake.upload_raises
                fake.upload_paths.append(path)
                fake.uploads.append((account_id, path.name, path.read_bytes()))
                return {"ready": True, "send_with": [{"processId": f"p{len(fake.uploads)}", "name": "x"}]}

            def create_post(self, text, media_files=None, price=0, previews=None):
                fake.posts.append({"account_id": account_id, "text": text, "media_files": list(media_files or [])})
                return {"id": 80000 + len(fake.posts), "text": text,
                        "media": [{"id": 90000 + i} for i, _ in enumerate(media_files or [])]}

            def get_post(self, post_id):
                if fake.post_raises is not None:
                    raise fake.post_raises
                return fake.post_now

            def delete_post(self, post_id):
                return {"success": True}

        return Client()


def put_media(client, aid: str, post_id: int, ids: list) -> object:
    return client.put(f"/admin/s4s/profiles/{aid}/posts/{post_id}/media", json={"vault_media_ids": ids})


async def _rows(model, **where) -> list:
    async with get_session() as s:
        q = select(model)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        return list((await s.execute(q.order_by(model.id))).scalars().all())


def rows(model, **where) -> list:
    return asyncio.run(_rows(model, **where))


def day(n: int) -> datetime:
    today = datetime.utcnow().date()
    return datetime(today.year, today.month, today.day) + timedelta(days=n, hours=10)


def z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def send(from_id: str, to_id: str, n: int) -> int:
    owner = OWNER_A if from_id in (A, C) else OWNER_B
    r = owner.post("/admin/s4s/requests", json={"from_account_id": from_id, "to_profile_id": PID[to_id],
                                                "slot_at": z(day(n))})
    assert r.status_code == 201, f"send: {r.status_code} {r.text}"
    return r.json()["id"]


def booked(n: int) -> dict[str, S4SSlot]:
    """A sends B a request for day `n`, B accepts, both slots move just past due."""
    request_id = send(A, B, n)
    r = OWNER_B.post(f"/admin/s4s/requests/{request_id}/accept")
    assert r.status_code == 200, f"accept: {r.status_code} {r.text}"
    db(update(S4SSlot).where(S4SSlot.request_id == request_id).values(slot_at=datetime.utcnow() - timedelta(minutes=1)))
    return {s.poster_account_id: s for s in rows(S4SSlot, request_id=request_id)}


def run_post(account_id: str, slot_id: int) -> dict:
    return with_env(FLAG, "1", lambda: asyncio.run(s4s_post.run(account_id, {"slot_id": slot_id}, run_id=0)))


def run_check(account_id: str, slot_id: int) -> dict:
    return asyncio.run(s4s_check.run(account_id, {"slot_id": slot_id}, run_id=0))


def state(slot_id: int) -> tuple:
    (row,) = rows(S4SSlot, id=slot_id)
    return row.status, row.reason


# ── Save ─────────────────────────────────────────────────────────────

def case_saving_checks_each_vault_item_with_the_creators_own_session_and_stores_no_file():
    fake = Fake({(A, 11): photo(11), (A, 12): {"id": 12, "type": "video", "files": {"full": {}},
                                               "videoSources": {"720": f"{CDN}12.mp4"}}})
    r = put_media(OWNER_A, A, PRIMARY[A], [12, 11])
    assert r.status_code == 200, r.text
    media = r.json()
    assert [(m["vault_media_id"], m["media_type"]) for m in media] == [(12, "video"), (11, "photo")], media
    assert fake.reads == [(A, 12), (A, 11)] and fake.gets == [], (fake.reads, fake.gets)
    assert not hasattr(s4s_media, "MEDIA_ROOT"), "S4S media has a disk store again"
    (post,) = [p for p in profile(OWNER_A, A)["posts"] if p["id"] == PRIMARY[A]]
    assert post["media"] == media, post["media"]
    # A re-save keeps what is attached (no second read) and detaches the rest.
    fake.reads.clear()
    r = put_media(OWNER_A, A, PRIMARY[A], [11])
    assert r.status_code == 200 and [m["vault_media_id"] for m in r.json()] == [11], r.text
    assert fake.reads == [], "an attached item was read again"
    # The detached video named no request: pruned.
    assert not rows(S4SMedia, id=media[0]["id"]) and rows(S4SMedia, id=media[1]["id"])


def case_a_save_refuses_six_twice_listed_drm_foreign_and_off_host_items_writing_nothing():
    Fake({(C, 21): photo(21), (C, 22): photo(22, url="https://evil.example/22.jpg"),
          (C, 23): {"id": 23, "type": "video", "files": {"full": {}, "drm": {"manifest": {"hls": "x"}}}},
          (C, 24): {"id": 24, "type": "audio", "files": {}}, (B, 25): photo(25),
          (C, 26): photo(26, url="https://x@evil.example\\@cdn2.onlyfans.com/26.jpg"),
          (C, 27): photo(27, url="https://cdn2.onlyfans.com:8443/27.jpg")})
    for ids, code, words in (([1, 2, 3, 4, 5, 6], 400, "at most 5"), ([21, 21], 400, "twice"),
                             ([21, 23], 400, "DRM"), ([21, 24], 400, "only photos"),
                             ([21, 25], 400, "not in this Creator's vault"), ([21, 22], 400, "media host"),
                             ([26], 400, "media host"), ([27], 400, "media host"),
                             (["21"], 400, "vault_media_ids")):
        r = put_media(OWNER_A, C, PRIMARY[C], ids)
        assert r.status_code == code and words in r.json()["detail"], (ids, r.status_code, r.text)
    assert not rows(S4SMedia, account_id=C), "a refused save left rows"


def case_only_the_creators_own_agency_saves_and_reads_its_media():
    Fake({(C, 51): photo(51)})
    r = put_media(OWNER_B, C, PRIMARY[C], [51])
    assert r.status_code in (403, 404), r.status_code
    r = put_media(OWNER_A, C, PRIMARY[A], [51])  # A's post under C's path
    assert r.status_code == 404, r.status_code
    r = put_media(OWNER_A, C, PRIMARY[C], [51])
    assert r.status_code == 200, r.text
    mid = r.json()[0]["id"]
    fake = Fake({(C, 51): photo(51, files={"full": {"url": f"{CDN}51.jpg"}, "thumb": {"url": f"{CDN}51_t.jpg"}})})
    got = OWNER_A.get(f"/admin/s4s/media/{mid}")
    assert got.status_code == 200 and got.content == b"x" * 1000 and got.headers["content-type"] == "image/jpeg"
    # The still is the item's thumb, read live with C's own session.
    assert fake.reads == [(C, 51)] and fake.gets == [f"{CDN}51_t.jpg"], (fake.reads, fake.gets)
    assert OWNER_B.get("/admin/s4s/media/abc").status_code == 404
    # B is in no request with C, but Discovery lists C to B with this item on its Primary post.
    assert OWNER_B.get(f"/admin/s4s/media/{mid}").status_code == 200
    (listed,) = [i for i in OWNER_B.get("/admin/s4s/discover").json() if i["profile_id"] == PID[C]]
    assert listed["primary_media"] == [{"id": mid, "media_type": "photo"}], listed
    # Hidden from Discovery, or blocked by B: 404 to B, still 200 to A.
    for hide, show in (
        (lambda: OWNER_A.put(f"/admin/s4s/profiles/{C}", json={"discovery_visible": False}),
         lambda: OWNER_A.put(f"/admin/s4s/profiles/{C}", json={"discovery_visible": True})),
        (lambda: OWNER_B.post("/admin/s4s/blocks", json={"profile_id": PID[C]}),
         lambda: OWNER_B.delete(f"/admin/s4s/blocks/{PID[C]}")),
    ):
        assert hide().status_code == 200
        assert OWNER_B.get(f"/admin/s4s/media/{mid}").status_code == 404
        assert OWNER_A.get(f"/admin/s4s/media/{mid}").status_code == 200
        assert show().status_code == 200
    # Off the Primary post: 404 to B.
    other = OWNER_A.post(f"/admin/s4s/profiles/{C}/posts", json={"caption": "Not primary"}).json()
    assert OWNER_A.post(f"/admin/s4s/profiles/{C}/posts/{other['id']}/primary").status_code == 200
    assert OWNER_B.get(f"/admin/s4s/media/{mid}").status_code == 404
    assert OWNER_A.post(f"/admin/s4s/profiles/{C}/posts/{PRIMARY[C]}/primary").status_code == 200
    assert OWNER_A.delete(f"/admin/s4s/profiles/{C}/posts/{other['id']}").status_code == 200
    # Gone from the vault: no preview.
    Fake()
    assert OWNER_A.get(f"/admin/s4s/media/{mid}").status_code == 404
    assert put_media(OWNER_A, C, PRIMARY[C], []).status_code == 200


def case_signed_out_is_401_and_a_chatter_is_403_on_every_media_route():
    def every(client):
        return [("PUT media", put_media(client, A, PRIMARY[A], [])),
                ("GET media", client.get("/admin/s4s/media/1"))]
    for label, r in every(_harness.make_client()):
        assert r.status_code == 401, f"{label} signed out: {r.status_code}"
    for name in ("chatter_a", "chatter_ab"):
        for label, r in every(fx.login_chatter(name)):
            assert r.status_code == 403, f"{label} as {name}: {r.status_code}"


# ── Send, preview, post ──────────────────────────────────────────────

def case_a_request_snapshots_the_primary_media_and_the_partner_may_preview_it():
    Fake({(A, 61): photo(61)})
    r = put_media(OWNER_A, A, PRIMARY[A], [11, 61])
    assert r.status_code == 200, r.text
    ids = [m["id"] for m in r.json()]
    request_id = send(A, B, 2)
    (req,) = [q for q in OWNER_B.get("/admin/s4s/requests?box=received").json() if q["id"] == request_id]
    assert [m["id"] for m in req["from_media"]] == ids and req["to_media"] == [], req
    assert OWNER_B.get(f"/admin/s4s/media/{ids[1]}").status_code == 200
    # Detached after the send, the row stays while the request is open.
    assert put_media(OWNER_A, A, PRIMARY[A], [11]).status_code == 200
    (m61,) = rows(S4SMedia, id=ids[1])
    assert m61.post_id is None, "a snapshotted row was pruned"
    # Declined: nothing needs it now; the next prune removes it.
    assert OWNER_B.post(f"/admin/s4s/requests/{request_id}/decline").status_code == 200
    assert OWNER_B.get(f"/admin/s4s/media/{ids[1]}").status_code == 404, "a declined request still grants"
    asyncio.run(s4s_media.prune())
    assert not rows(S4SMedia, id=ids[1])


def case_a_slot_reads_the_partners_vault_item_then_uploads_it_on_the_posters_account_and_posts():
    fake = Fake({(A, 11): photo(11)})
    slots = booked(3)
    mine = slots[B]  # B posts A's promo: A's vault item 11
    res = run_post(B, mine.id)
    assert res["status"] == "ok", res
    # Read from A's vault with A's session at post time, uploaded with B's.
    assert fake.reads == [(A, 11)] and fake.gets == [f"{CDN}11.jpg"], (fake.reads, fake.gets)
    assert fake.uploads == [(B, "11.jpg", b"x" * 1000)], fake.uploads
    assert not fake.upload_paths[0].parent.exists(), "the temporary download outlived the post"
    (post,) = fake.posts
    assert post["account_id"] == B and post["media_files"] == [{"processId": "p1", "name": "x"}], post
    assert state(mine.id) == ("posted", None)
    (row,) = rows(Post, id=rows(S4SSlot, id=mine.id)[0].post_id)
    assert json.loads(row.media_ids) == [90000], row.media_ids
    (check,) = rows(ScheduledJob, kind="s4s_check", account_id=B)
    assert json.loads(check.payload_json) == {"slot_id": mine.id}
    to_removal = (rows(S4SSlot, id=mine.id)[0].remove_at - check.run_at).total_seconds()
    assert 1790 < to_removal < 1810, to_removal


def case_a_vault_item_gone_ends_media_missing_and_failed_reads_or_uploads_post_nothing():
    fake = Fake()  # A's item 11 has left A's vault
    slots = booked(4)
    res = run_post(B, slots[B].id)
    assert res == {"status": "error", "reason": "media_missing", "slot_id": slots[B].id}, res
    assert state(slots[B].id) == ("failed", "media_missing")
    assert fake.uploads == [] and fake.posts == []

    fake = Fake({(A, 11): photo(11)})
    fake.status = 500
    slots = booked(5)
    res = run_post(B, slots[B].id)
    assert res["reason"] == "media_fetch_failed" and state(slots[B].id) == ("failed", "media_fetch_failed"), res
    assert fake.uploads == [] and fake.posts == []

    fake = Fake({(A, 11): photo(11)}, upload_raises=RuntimeError("upload 500"))
    slots = booked(9)
    res = run_post(B, slots[B].id)
    assert res["reason"] == "upload_failed" and state(slots[B].id) == ("failed", "upload_failed"), res
    assert fake.posts == []
    # A's side has no media to upload (B's Primary has none): posts text only.
    assert run_post(A, slots[A].id)["status"] == "ok" and fake.posts[0]["media_files"] == []


# ── Tamper check ─────────────────────────────────────────────────────

# A's Primary carries vault item 11 from here on: a slot B posts reads it.
A_VAULT = {(A, 11): photo(11)}

def case_tamper_reason_reads_deleted_archived_and_edited():
    tr = s4s_check.tamper_reason
    then = {"text": "<p>Hi <b>there</b></p>", "media": []}  # media still converting at create
    assert tr(None, then, "Hi there", 1) == "post_deleted"
    assert tr({"isDeleted": True}, then, "", 1) == "post_deleted"
    assert tr({"isArchived": True, "text": "Hi there"}, then, "", 1) == "post_archived"
    # The media count is the sent files', not the create response's.
    assert tr({"text": "Hi  there", "media": [{"id": 1}]}, then, "", 1) is None
    assert tr({"text": "Hi you", "media": [{"id": 1}]}, then, "", 1) == "post_edited"
    assert tr({"text": "Hi there", "media": []}, then, "", 1) == "post_edited"
    # A read without `media` skips the count.
    assert tr({"text": "Hi there"}, then, "", 1) is None
    # A create response without text: the sent text.
    assert tr({"text": "Sent", "media": []}, {"id": 5}, "Sent", 0) is None


def case_the_check_ends_a_tampered_slot_failed_and_the_partner_sees_why():
    fake = Fake(A_VAULT)
    slots = booked(6)
    mine = slots[B]
    assert run_post(B, mine.id)["status"] == "ok"
    sent = fake.posts[-1]
    fake.post_now = {"id": 1, "text": sent["text"], "media": [{"id": 90000}]}
    assert run_check(B, mine.id)["tamper"] is None and state(mine.id) == ("posted", None)
    assert run_check(A, mine.id)["reason"] == "not_the_poster"
    fake.post_raises = OFAPIError("500 upstream")
    assert run_check(B, mine.id)["reason"] == "inconclusive" and state(mine.id) == ("posted", None)
    fake.post_raises = None
    fake.post_now = {"id": 1, "text": "something else", "media": [{"id": 90000}]}
    res = run_check(B, mine.id)
    assert res["tamper"] == "post_edited" and res["moved"], res
    assert state(mine.id) == ("failed", "post_edited")
    # A sees B's tamper on its own (A's) slot of the pair.
    r = OWNER_A.get(f"/admin/s4s/schedule?from={z(day(-2))}&to={z(day(30))}")
    (item,) = [i for i in r.json() if i["id"] == slots[A].id]
    assert item["partner_issue"] == "post_edited", item
    # Done: a later check leaves it.
    assert run_check(B, mine.id)["status"] == "skipped"


def case_a_410_from_onlyfans_reads_as_deleted():
    fake = Fake(A_VAULT)
    mine = booked(8)[B]
    assert run_post(B, mine.id)["status"] == "ok"
    fake.post_raises = OFAPIError("410 for https://onlyfans.com/api2/v2/posts/1\nGone")
    assert run_check(B, mine.id)["tamper"] == "post_deleted"
    assert state(mine.id) == ("failed", "post_deleted")


def case_the_check_skips_a_post_our_own_unsend_already_removed():
    fake = Fake(A_VAULT)
    mine = booked(7)[B]
    assert run_post(B, mine.id)["status"] == "ok"
    db(update(Post).where(Post.id == rows(S4SSlot, id=mine.id)[0].post_id).values(status="deleted"))
    fake.post_now = None
    assert run_check(B, mine.id)["reason"] == "already_removed"
    assert state(mine.id) == ("posted", None)


_harness.run()
