#!/usr/bin/env python3
"""Vault import: the linked fan, per-file details, the open run, Drive folder
hashtags, and the routes that drive them.

  case_fan_handle_reads_any_paste          name / @name / profile link / blank / junk
  case_meta_is_sanitised                   only the known keys and shapes survive
  case_empty_username_takes_the_carrier_path   no fan -> send_to=None on every file
  case_username_sends_to_the_fan           a fan id on the run -> send_to on every file
  case_fan_send_uses_the_fan_gate          the DM goes through send_gate, foldering does not
  case_fan_timeout_is_not_a_carrier_alarm  a timed-out fan send raises no carrier alarm
  case_fan_refusal_stops_the_run           "Cannot send message" stops the batch
  case_fan_send_reads_the_vault_id         the message's media id IS the vault id
  case_fan_send_polls_the_chat_for_the_id  ...read off a page pinned to the message
  case_fan_send_poll_is_bounded            a few tries, read errors tolerated, then the hash
  case_folder_tags                         sub-folders, else the pasted folder's name
  case_resolve_stamps_the_folder_path      a folder walk records every file's path
  case_drive_items_carry_folder_hashtags   _plan turns that path into the item's hashtags
  case_appended_files_upload_as_they_arrive    the open run, closed by close()
  case_append_after_the_run_is_refused     ...and a late file is refused, not lost
  case_queued_files_are_recorded_when_the_run_fails   accepted files never vanish
  case_drive_and_appended_files_share_one_cap  one files-per-import count
  case_idle_timer_waits_for_a_file_in_flight   a slow transfer is not idle time
  case_each_file_is_filed_into_its_category    per-file folder, else the run's
  case_every_failed_folder_is_reported     one filing_error naming each failed list
  case_same_name_files_stage_apart         two IMG_0001.jpg never share a path
  case_import_details_land_on_the_mirror_row   tags merged + locked, price, notes
  case_imported_tags_survive_a_full_tag_list   imported tags go first under the cap
  case_details_outcome_reaches_the_run_record  the hook gets the details, run keeps its answer
  case_drive_list_route_lists_with_hashtags    GET …/drive/list, Google faked out
  case_fan_route_resolves_and_batch_rechecks   GET …/upload/fan, then the batch's re-check
  case_batch_route_opens_the_run_and_aligns_meta   keep_open, stage dir, meta by part
  case_fan_dm_is_paced_as_manual_and_recorded  purpose `manual` + an outbound messages row
  case_append_route_guards                 404 / 409 / 413 cleanup / `closed`

Offline by construction: no OnlyFans client exists (fakes only) and every Drive
call goes through a faked `gdrive._get` / `gdrive.resolve`.

Run: ./venv/bin/python service/tests/test_vault_import_extras.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from concurrent.futures import TimeoutError as FuturesTimeout  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

os.environ.pop("GOOGLE_DRIVE_API_KEY", None)
_SPOOL = Path(tempfile.mkdtemp(prefix="vault_import_extras_spool_"))
os.environ["VAULT_SPOOL_DIR"] = str(_SPOOL)

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
import gdrive  # noqa: E402
import of_client  # noqa: E402
import vault_ai_api  # noqa: E402
import vault_upload  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Message, VaultItem  # noqa: E402
from sqlalchemy import select  # noqa: E402
from vault_ai_effective import effective_value, locked_fields  # noqa: E402

vault_upload.SPOOL_ROOT = _SPOOL
vault_upload.LOCK_DIR = _SPOOL / "locks"


def _no_network(*_a, **_k):
    raise AssertionError("a real Drive session was opened")


gdrive._session = _no_network


class _Client:
    """An OFClient stand-in for `vault_upload.start`: records each file's way
    into the vault (a carrier, or `send_to` a fan) and its gate, and lands
    every file as a fresh vault id. `fail` maps a file name to the exception
    its carrier or send raises."""

    def __init__(self, fail: dict | None = None):
        self.calls: list[dict] = []
        self.filed: list[tuple] = []
        self.ids: dict[str, int] = {}
        self._next = 700
        self.fail = fail or {}
        self.filing_fails: set[int] = set()

    def upload_claim(self, path):
        name = Path(path).name
        return of_client.UploadClaim(media={"name": name}, dedupe_key=name, size=1)

    def _land(self, send_with, send_to, gate) -> list[int]:
        names = [m["name"] for m in send_with]
        self.calls += [{"name": n, "send_to": send_to, "gate": gate} for n in names]
        for n in names:
            if n in self.fail:
                raise self.fail[n]
            self._next += 1
            self.ids[n] = self._next
        return [self.ids[n] for n in names]

    def materialize_to_vault(self, send_with, *, gate, **_):
        return {"media": [{"id": v} for v in self._land(send_with, None, gate)],
                "carrier_post_id": None, "carrier_deleted": None}

    def materialize_via_message(self, send_with, fan_id, *, gate, **_):
        (vid,) = self._land(send_with, fan_id, gate)
        return {"vault_id": vid, "message_id": 99}

    def vault_media_lookup_hash(self, key, size):
        return {"id": self.ids[key]}

    def add_media_to_vault_list(self, list_id, ids):
        if list_id in self.filing_fails:
            raise RuntimeError(f"list {list_id} refused")
        self.filed.append((list_id, tuple(ids)))
        return {}

    def delete_post(self, pid):
        return {}


def _files(td: Path, *names: str) -> list[str]:
    out = []
    for n in names:
        p = td / n
        p.write_bytes(b"x" * 16)
        out.append(str(p))
    return out


def _run(aid: str, **kw) -> dict:
    return vault_upload.start(aid, limits=vault_upload.Limits(pace_s=0), **kw)


def _wait(cond, what: str, tries: int = 300) -> None:
    for _ in range(tries):
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}")


# ── input sanitising ──────────────────────────────────────────────────────

def case_fan_handle_reads_any_paste():
    h = vault_upload.fan_handle
    assert h("") == "" and h(None) == "" and h("   ") == ""
    assert h("testfan") == "testfan"
    assert h(" @testfan ") == "testfan"
    assert h("https://onlyfans.com/testfan") == "testfan"
    assert h("onlyfans.com/testfan/media?x=1") == "testfan"
    assert h("test.fan_2-x") == "test.fan_2-x"
    for junk in ("two words", "name;drop", "näme", "a/b"):
        try:
            h(junk)
            assert False, f"{junk!r} passed as a username"
        except ValueError:
            pass


def case_meta_is_sanitised():
    got = vault_upload.parse_metas(json.dumps([
        {"hashtags": ["#Beach", " red set ", "beach"], "tag_creators": ["@Collab", ""],
         "notes": "  shot at noon ", "price_cents": "1299", "list_id": "42",
         "evil": "dropped"},
        {"hashtags": [], "notes": ""},
        "not a dict",
        {"price_cents": "abc", "list_id": None},
        # Strings are not split any more: the card sends lists.
        {"hashtags": "beach, red"},
    ]))
    assert got[0] == {"hashtags": ["beach", "red set"], "tag_creators": ["collab"],
                      "notes": "shot at noon", "price_cents": 1299, "list_id": 42}, got[0]
    assert got[1:] == [None, None, None, None], got[1:]
    assert vault_upload.parse_metas("{not json") == []
    assert vault_upload.parse_metas("") == []


# ── the linked fan, optional ──────────────────────────────────────────────

def case_empty_username_takes_the_carrier_path():
    with tempfile.TemporaryDirectory() as td:
        c = _Client()
        st = _run("51", client=c, local_paths=_files(Path(td), "a.jpg", "b.jpg"))
        assert st["status"] == "done", st
        assert st["fan_id"] is None
        assert [call["send_to"] for call in c.calls] == [None, None], c.calls


def case_username_sends_to_the_fan():
    with tempfile.TemporaryDirectory() as td:
        c = _Client()
        st = _run("52", client=c, local_paths=_files(Path(td), "a.jpg", "b.jpg"),
                  fan_id=31337)
        assert st["status"] == "done", st
        assert [call.get("send_to") for call in c.calls] == [31337, 31337], c.calls
        assert [i["message_id"] for i in st["items"]] == [99, 99]


def case_fan_send_uses_the_fan_gate():
    def gate(thunk):
        return thunk()

    def send_gate(thunk):
        return thunk()

    with tempfile.TemporaryDirectory() as td:
        c = _Client()
        _run("57", client=c, local_paths=_files(Path(td), "a.jpg"), fan_id=31337,
             gate=gate, send_gate=send_gate, list_id=7)
        assert c.calls[0]["gate"] is send_gate, "the fan DM went through the carrier gate"
        assert c.filed == [(7, (701,))]
        c = _Client()
        _run("57", client=c, local_paths=_files(Path(td), "b.jpg"),
             gate=gate, send_gate=send_gate)
        assert c.calls[0]["gate"] is gate, "a carrier went through the fan gate"


def case_fan_timeout_is_not_a_carrier_alarm():
    with tempfile.TemporaryDirectory() as td:
        c = _Client(fail={"a.jpg": FuturesTimeout()})
        st = _run("58", client=c, local_paths=_files(Path(td), "a.jpg"), fan_id=31337)
        (it,) = st["items"]
        assert it["status"] == "failed" and it["message_write_pending"] is True, it
        assert not it["carrier_write_pending"], it
        assert "may still go out" in it["error"], it["error"]
        assert vault_upload.carriers_outstanding("58", [st]) == (0, 0)
        # The carrier path keeps its alarm.
        c = _Client(fail={"b.jpg": FuturesTimeout()})
        st = _run("58", client=c, local_paths=_files(Path(td), "b.jpg"))
        assert st["items"][0]["carrier_write_pending"] is True


def case_fan_refusal_stops_the_run():
    with tempfile.TemporaryDirectory() as td:
        c = _Client(fail={"a.jpg": of_client.FanSendRefused("refused: not subscribed")})
        st = _run("59", client=c, fan_id=31337,
                  local_paths=_files(Path(td), "a.jpg", "b.jpg", "c.jpg"))
        assert [x["name"] for x in c.calls] == ["a.jpg"], "it kept sending after a refusal"
        assert st["status"] == "failed" and "refused" in st["error"], st
        assert [i["status"] for i in st["items"]] == ["failed"] * 3, st["items"]
        assert "refused" in st["items"][0]["error"]
        assert "stopped first" in st["items"][1]["error"], st["items"][1]


class _FanSelf:
    def __init__(self, send_media, chat_media=None, read_error=None, hash_hit=None):
        self.sent: list = []
        self.reads: list = []
        self._send_media = send_media
        self._chat_media = chat_media
        self._read_error = read_error
        self._hash_hit = hash_hit

    def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("media_files"), kw.get("auto_tag")))
        return {"id": 77, "media": self._send_media}

    def get_messages(self, chat_id, **kw):
        self.reads.append(kw)
        if self._read_error:
            raise self._read_error
        return {"list": [{"id": 77, "media": self._chat_media or []},
                         {"id": 76, "media": [{"id": 1}]}]}

    def vault_media_lookup_hash(self, *_a):
        return self._hash_hit


def case_fan_send_reads_the_vault_id():
    s = _FanSelf([{"id": 555, "isReady": True}])
    res = of_client.OFClient.materialize_via_message(s, [{"processId": "p"}], 31337,
                                                     poll_interval_s=0)
    assert s.sent == [(31337, "", [{"processId": "p"}], False)], s.sent
    assert res["vault_id"] == 555 and res["message_id"] == 77, res
    assert res["carrier_post_id"] is None and res["still_transcoding"] is False, res
    assert s.reads == [], "polled the chat for an id the send already gave"


def case_fan_send_polls_the_chat_for_the_id():
    s = _FanSelf([], chat_media=[{"id": 556, "isReady": False}])
    res = of_client.OFClient.materialize_via_message(s, [{"processId": "p"}], 31337,
                                                     poll_interval_s=0)
    assert res["vault_id"] == 556 and res["still_transcoding"] is True, res
    # Pinned to the sent message: "older than 78" puts message 77 on top.
    assert s.reads[0]["before_id"] == 78, s.reads


def case_fan_send_poll_is_bounded():
    s = _FanSelf([], read_error=RuntimeError("chat read 500"), hash_hit={"id": 557})
    res = of_client.OFClient.materialize_via_message(
        s, [{"processId": "p"}], 31337, dedupe_key="k", size=16,
        poll_interval_s=0, polls=3)
    assert len(s.reads) == 3, s.reads
    assert res["vault_id"] == 557 and res["message_id"] == 77, res
    s = _FanSelf([])                       # never surfaces, no hash either
    res = of_client.OFClient.materialize_via_message(s, [{"processId": "p"}], 31337,
                                                     poll_interval_s=0, polls=2)
    assert res["vault_id"] is None and res["message_id"] == 77, res
    assert len(s.reads) == 2


def case_fan_refusal_is_recognised():
    class _Resp:
        status_code, text = 400, '{"error":{"message":"Cannot send message to this user"}}'

    class _Refusing(_FanSelf):
        def send_message(self, *a, **k):
            raise of_client.OFAPIError("400", response=_Resp())

    try:
        of_client.OFClient.materialize_via_message(_Refusing([]), [{}], 31337)
        assert False, "a refusal read as an ordinary error"
    except of_client.FanSendRefused as e:
        assert "subscribed" in str(e)


# ── Google Drive folder → hashtags ────────────────────────────────────────

def case_folder_tags():
    F = gdrive.DriveFile
    assert gdrive.folder_tags(F("1", "a.jpg", "image/jpeg", 1, folders=("Shoot",))) == ["Shoot"]
    assert gdrive.folder_tags(
        F("1", "a.jpg", "image/jpeg", 1, folders=("Shoot", "Beach", " Red "))) == ["Beach", " Red "]
    assert gdrive.folder_tags(F("1", "a.jpg", "image/jpeg", 1)) == []
    # The tag form is the vault normaliser's, applied once.
    assert vault_upload.drive_meta(
        F("1", "a.jpg", "image/jpeg", 1, folders=("Shoot", "Beach", " Red ", "beach"))
    ) == {"hashtags": ["beach", "red"]}


class _Resp:
    def __init__(self, body):
        self.ok, self.status_code, self._body, self.text = True, 200, body, ""

    def json(self):
        return self._body


def _fake_drive(url, *, params, refs, what, **kw):
    """A two-level public folder: Shoot/{root.jpg, Beach/{b.jpg}}."""
    if url.endswith("/ROOT"):
        return _Resp({"id": "ROOT", "name": "Shoot", "mimeType": gdrive.FOLDER_MIME})
    q = params.get("q", "")
    if "'ROOT' in parents" in q:
        return _Resp({"files": [
            {"id": "f1", "name": "root.jpg", "mimeType": "image/jpeg", "size": "10"},
            {"id": "SUB", "name": "Beach", "mimeType": gdrive.FOLDER_MIME},
        ]})
    if "'SUB' in parents" in q:
        return _Resp({"files": [
            {"id": "f2", "name": "b.jpg", "mimeType": "image/jpeg", "size": "20"}]})
    raise AssertionError(f"unexpected Drive call {url} {params}")


def case_resolve_stamps_the_folder_path():
    orig = gdrive._get
    gdrive._get = _fake_drive
    try:
        got = gdrive.resolve(["https://drive.google.com/drive/folders/ROOT"])
    finally:
        gdrive._get = orig
    by = {f.name: f for f in got}
    assert by["root.jpg"].folders == ("Shoot",), by["root.jpg"]
    assert by["b.jpg"].folders == ("Shoot", "Beach"), by["b.jpg"]
    assert gdrive.folder_tags(by["root.jpg"]) == ["Shoot"]
    assert gdrive.folder_tags(by["b.jpg"]) == ["Beach"]


def case_drive_items_carry_folder_hashtags():
    orig = vault_upload.gdrive.resolve
    vault_upload.gdrive.resolve = lambda links, **k: [
        gdrive.DriveFile("f1", "a.jpg", "image/jpeg", 10, md5=None, folders=("Shoot",)),
        gdrive.DriveFile("f2", "b.jpg", "image/jpeg", 10, md5=None,
                         folders=("Shoot", "Beach")),
        gdrive.DriveFile("f3", "c.jpg", "image/jpeg", 10, md5=None),
    ]
    try:
        items = vault_upload._plan({"account_id": "53", "run_id": "x"}, [], ["link"],
                                   client=None, limits=vault_upload.Limits())
    finally:
        vault_upload.gdrive.resolve = orig
    assert [i["meta"] for i in items] == [
        {"hashtags": ["shoot"]}, {"hashtags": ["beach"]}, None], items


# ── the open run: upload as files arrive ──────────────────────────────────

def case_appended_files_upload_as_they_arrive():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        first, second, third = _files(td, "1.jpg", "2.jpg", "3.jpg")
        c = _Client()
        run_id = vault_upload.begin("54", keep_open=True)
        out: dict = {}
        t = threading.Thread(target=lambda: out.update(st=_run(
            "54", client=c, run_id=run_id, local_paths=[first],
            metas=[{"hashtags": ["one"]}])))
        t.start()
        # The first file is uploaded before the second has even been sent.
        _wait(lambda: c.calls, "the first upload")
        assert [x["name"] for x in c.calls] == ["1.jpg"], c.calls
        vault_upload.append(run_id, second, {"hashtags": ["two"]})
        vault_upload.append(run_id, third, None)
        assert vault_upload.close(run_id) is True
        t.join(10)
        assert not t.is_alive(), "the run never stopped listening"
        st = out["st"]
        assert st["status"] == "done", st
        assert [i["name"] for i in st["items"]] == ["1.jpg", "2.jpg", "3.jpg"]
        assert vault_upload.landed_meta(st) == {701: {"hashtags": ["one"]},
                                                702: {"hashtags": ["two"]}}, st["items"]


def case_append_after_the_run_is_refused():
    with tempfile.TemporaryDirectory() as td:
        (path,) = _files(Path(td), "late.jpg")
        run_id = vault_upload.begin("55", keep_open=True)
        vault_upload.OPEN_IDLE_S, idle = 0.05, vault_upload.OPEN_IDLE_S
        try:
            _run("55", client=_Client(), run_id=run_id, local_paths=[path])
        finally:
            vault_upload.OPEN_IDLE_S = idle
        try:
            vault_upload.append(run_id, path)
            assert False, "a finished run accepted a file"
        except vault_upload.NotTaking:
            pass
        try:
            with vault_upload.receiving(run_id):
                assert False, "a finished run opened a transfer"
        except vault_upload.NotTaking:
            pass
        assert vault_upload.close(run_id) is False


def case_queued_files_are_recorded_when_the_run_fails():
    with tempfile.TemporaryDirectory() as td:
        a, b = _files(Path(td), "a.jpg", "b.jpg")
        run_id = vault_upload.begin("60", keep_open=True)
        vault_upload.append(run_id, a, {"hashtags": ["x"]})
        vault_upload.append(run_id, b, None)

        def private_link(*_a, **_k):
            raise gdrive.GDriveError("folder is private")

        orig = vault_upload.gdrive.resolve
        vault_upload.gdrive.resolve = private_link
        try:
            st = _run("60", client=_Client(), run_id=run_id, drive_links=["link"])
        finally:
            vault_upload.gdrive.resolve = orig
        assert st["status"] == "failed", st
        assert [(i["name"], i["status"]) for i in st["items"]] == \
            [("a.jpg", "failed"), ("b.jpg", "failed")], st["items"]
        assert "ended before this file" in st["items"][0]["error"]
        assert st["items"][0]["meta"] == {"hashtags": ["x"]}
        on_disk = vault_upload.read_state(run_id)
        assert len(on_disk["items"]) == 2, "the record on disk lost them"


def case_drive_and_appended_files_share_one_cap():
    with tempfile.TemporaryDirectory() as td:
        a, b = _files(Path(td), "a.jpg", "b.jpg")
        orig = vault_upload.gdrive.resolve
        vault_upload.gdrive.resolve = lambda links, **k: [
            gdrive.DriveFile("d1", "d1.jpg", "image/jpeg", 10)]
        orig_fetch = vault_upload._fetch_drive

        def fetch(items, run_dir, limits, progress):
            for it in items:
                if it["source"] == "gdrive" and it["status"] == "pending":
                    p = run_dir / it["name"]
                    p.write_bytes(b"d" * 10)
                    it.update(path=str(p), spooled=True)

        vault_upload._fetch_drive = fetch
        run_id = vault_upload.begin("61", keep_open=True)
        vault_upload.append(run_id, a, None)
        vault_upload.append(run_id, b, None)
        vault_upload.close(run_id)
        try:
            st = vault_upload.start("61", client=_Client(), run_id=run_id,
                                    drive_links=["link"],
                                    limits=vault_upload.Limits(pace_s=0, max_files=2))
        finally:
            vault_upload.gdrive.resolve = orig
            vault_upload._fetch_drive = orig_fetch
        assert [(i["name"], i["status"]) for i in st["items"]] == [
            ("d1.jpg", "done"), ("a.jpg", "done"), ("b.jpg", "skipped")], st["items"]
        assert "batch cap of 2" in st["items"][2]["error"]


def case_idle_timer_waits_for_a_file_in_flight():
    with tempfile.TemporaryDirectory() as td:
        (path,) = _files(Path(td), "slow.jpg")
        c = _Client()
        run_id = vault_upload.begin("62", keep_open=True)
        vault_upload.OPEN_IDLE_S, idle = 0.05, vault_upload.OPEN_IDLE_S
        out: dict = {}
        try:
            with vault_upload.receiving(run_id):
                t = threading.Thread(target=lambda: out.update(st=_run(
                    "62", client=c, run_id=run_id, local_paths=[])))
                t.start()
                time.sleep(0.3)                     # six idle periods mid-transfer
                assert t.is_alive(), "the run idled out under a file in flight"
                vault_upload.append(run_id, path, None)
            t.join(10)
        finally:
            vault_upload.OPEN_IDLE_S = idle
        assert [i["status"] for i in out["st"]["items"]] == ["done"], out["st"]["items"]


def case_each_file_is_filed_into_its_category():
    with tempfile.TemporaryDirectory() as td:
        c = _Client()
        _run("56", client=c, local_paths=_files(Path(td), "a.jpg", "b.jpg", "c.jpg"),
             list_id=7, metas=[{"list_id": 9}, None, {"list_id": 9}])
        assert sorted(c.filed) == [(7, (702,)), (9, (701, 703))], c.filed


def case_every_failed_folder_is_reported():
    with tempfile.TemporaryDirectory() as td:
        c = _Client()
        c.filing_fails = {7, 9}
        st = _run("63", client=c,
                  local_paths=_files(Path(td), "a.jpg", "b.jpg", "c.jpg"),
                  list_id=7, metas=[{"list_id": 9}, None, {"list_id": 11}])
        assert c.filed == [(11, (703,))], c.filed
        assert st["filed_into_list"] == 1
        err = st["filing_error"]
        assert "folder 7" in err and "folder 9" in err, err


# ── staging (the HTTP route's helper) ─────────────────────────────────────

class _Part:
    """An `UploadFile` stand-in: a name and some bytes, read in chunks."""

    def __init__(self, filename: str, data: bytes, content_type="image/jpeg"):
        self.filename, self.content_type = filename, content_type
        self._data = data

    async def read(self, n: int) -> bytes:
        out, self._data = self._data[:n], self._data[n:]
        return out


def case_same_name_files_stage_apart():
    import server
    from fastapi import HTTPException
    limits = vault_upload.Limits(pace_s=0)
    stage = tempfile.mkdtemp(dir=_SPOOL)
    try:
        a = asyncio.run(server._vault_stage_file(_Part("IMG_0001.jpg", b"first"), stage, limits))
        b = asyncio.run(server._vault_stage_file(_Part("IMG_0001.jpg", b"second"), stage, limits))
        assert a != b, "two same-named files were staged onto one path"
        assert Path(a).name == Path(b).name == "IMG_0001.jpg"
        assert Path(a).read_bytes() == b"first" and Path(b).read_bytes() == b"second"
        # An over-cap part removes ITS partial, and nothing of anyone else's.
        try:
            asyncio.run(server._vault_stage_file(
                _Part("IMG_0001.jpg", b"x" * 64), stage,
                vault_upload.Limits(pace_s=0, max_bytes=8, max_download_bytes=8)))
            assert False, "an over-cap file was staged"
        except HTTPException as e:
            assert e.status_code == 413
        left = sorted(p.read_bytes() for p in Path(stage).rglob("*") if p.is_file())
        assert left == [b"first", b"second"], left
    finally:
        shutil.rmtree(stage, ignore_errors=True)


# ── the details reach the mirror ──────────────────────────────────────────

async def _seed_item(aid: str, media_id: int, tags: list[str]) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        s.add(VaultItem(account_id=aid, media_id=media_id, kind="photo",
                        created_at=datetime(2026, 10, 1), tags=json.dumps(tags)))
        await s.commit()


def case_import_details_land_on_the_mirror_row():
    aid = "acc_import_extras"

    async def go():
        await _seed_item(aid, 801, ["ai-tag"])
        n = await vault_ai_api.apply_import_meta(aid, {
            801: {"hashtags": ["beach"], "tag_creators": ["collab"],
                  "notes": "noon", "price_cents": 1299},
            802: {"hashtags": ["nowhere"]},           # no mirror row: skipped
        })
        async with get_session() as s:
            item = await s.get(VaultItem, (aid, 801))
            return n, item

    n, item = asyncio.run(go())
    assert n["applied"] == 1 and n["skipped"] == 1, n
    assert n["why"] == vault_ai_api.IMPORT_META_NO_ROW, n
    assert effective_value(item, "tags") == ["beach", "@collab", "ai-tag"], item.tags
    assert "tags" in locked_fields(item), "an imported hashtag must survive a re-describe"
    assert effective_value(item, "suggested_price_cents") == 1299
    assert item.notes == "noon"


def case_imported_tags_survive_a_full_tag_list():
    aid = "acc_import_full_tags"
    have = [f"ai-{n}" for n in range(12)]

    async def go():
        await _seed_item(aid, 811, have)
        await vault_ai_api.apply_import_meta(aid, {811: {"hashtags": ["beach", "red"]}})
        async with get_session() as s:
            return await s.get(VaultItem, (aid, 811))

    tags = effective_value(asyncio.run(go()), "tags")
    assert len(tags) == 12 and tags[:2] == ["beach", "red"], tags
    assert tags[2:] == have[:10], tags


def case_details_outcome_reaches_the_run_record():
    seen: list = []

    def hook(ids, details):
        seen.append((list(ids), details))
        return {"applied": 1, "skipped": 0, "why": None}

    with tempfile.TemporaryDirectory() as td:
        st = _run("64", client=_Client(), local_paths=_files(Path(td), "a.jpg", "b.jpg"),
                  metas=[{"hashtags": ["one"]}, None], on_landed=hook)
    assert seen == [([701, 702], {701: {"hashtags": ["one"]}})], seen
    assert st["details_saved"] == {"applied": 1, "skipped": 0, "why": None}, st
    assert vault_upload.read_state(st["run_id"])["details_saved"]["applied"] == 1


# ── HTTP ──────────────────────────────────────────────────────────────────

_HTTP: dict = {}


def _http():
    """Agency A's owner and creator, plus agency B's creator, seeded once."""
    if not _HTTP:
        ids = fx.seed_two_agencies()
        account_registry.upsert_account(ids["creator_a"], nickname="Extras Creator")
        account_registry.upsert_account(ids["creator_b"], nickname="Other Creator")
        _HTTP.update(owner=fx.login_owner("agency_a_owner"),
                     creator=ids["creator_a"], other=ids["creator_b"])
    return _HTTP["owner"], _HTTP["creator"], _HTTP["other"]


class _OFUser:
    """An OFClient stand-in for the routes: `get_user` answers for `testfan`
    only, and a fan upload sends through the gate it was handed."""

    def __init__(self):
        self.lookups: list = []
        self.uploads: list = []

    def get_user(self, handle):
        self.lookups.append(handle)
        if handle == "testfan":
            return {"id": 31337, "username": "testfan", "name": "Test Fan"}
        if handle == "ratelimited":
            class R:
                status_code, text = 429, "slow down"
            raise of_client.OFAPIError("429", response=R())

        class R404:
            status_code, text = 404, "not found"
        raise of_client.OFAPIError("404", response=R404())

    def upload_claim(self, path):
        return of_client.UploadClaim(media={"name": Path(path).name})

    def materialize_via_message(self, send_with, fan_id, *, gate, **_):
        sent = gate(lambda: {"id": 5555, "text": "", "media": [{"id": 901}],
                             "createdAt": "2026-10-18T10:00:00+00:00"})
        self.uploads.append((send_with[0]["name"], fan_id))
        return {"vault_id": 901, "message_id": sent["id"]}


def _patched(server, client):
    """Swap the route's OF client and capture the spawned worker."""
    spawned: list = []
    saved = (server._get_client, server._spawn_bg)
    server._get_client = lambda *a, **k: client
    server._spawn_bg = lambda coro, name: spawned.append(coro)
    return spawned, saved


def _unpatch(server, saved):
    server._get_client, server._spawn_bg = saved


def _on_one_loop(owner, server, send, spawned) -> tuple:
    """POST through the app and then run the worker it spawned, on ONE loop.

    The worker hops back to the loop the request ran on, and a TestClient
    closes that loop when the request returns."""
    import httpx

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),
                                     base_url="http://testserver",
                                     cookies=owner.cookies) as ac:
            r = await send(ac)
        for coro in spawned:
            await coro
        return r

    return asyncio.run(go())


def _multipart(fields: dict, parts: list[tuple[str, bytes]]) -> tuple[bytes, str]:
    """A hand-built body, because a client library drops `filename=""`, the
    nameless part the batch route has to skip."""
    b = "vaultboundary"
    out = b""
    for k, v in fields.items():
        out += (f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'
                f"{v}\r\n").encode()
    for name, data in parts:
        out += (f'--{b}\r\nContent-Disposition: form-data; name="files"; '
                f'filename="{name}"\r\nContent-Type: image/jpeg\r\n\r\n').encode()
        out += data + b"\r\n"
    return out + f"--{b}--\r\n".encode(), f"multipart/form-data; boundary={b}"


def _discard(run_id: str, spawned: list) -> None:
    """Release a run whose worker the test chose not to run."""
    for coro in spawned:
        coro.close()
    st = vault_upload.read_state(run_id) or {}
    vault_upload.abandon(run_id, "test")
    return st


def case_drive_list_route_lists_with_hashtags():
    owner, creator, _ = _http()
    import server
    orig = server.gdrive.resolve
    server.gdrive.resolve = lambda links, **k: [
        gdrive.DriveFile("f1", "a.jpg", "image/jpeg", 10, folders=("Shoot", "Beach")),
        gdrive.DriveFile("f2", "doc", "application/vnd.google-apps.document", None,
                         folders=("Shoot",)),
    ]
    try:
        r = owner.get("/api/of/v2/vault/upload/drive/list",
                      params={"link": "https://drive.google.com/drive/folders/X"},
                      headers={"X-Account-Id": creator})
    finally:
        server.gdrive.resolve = orig
    assert r.status_code == 200, r.text
    files = r.json()["files"]
    assert files[0]["hashtags"] == ["beach"] and files[0]["importable"] is True, files
    assert files[1]["importable"] is False and files[1]["reason"], files
    assert r.json()["max_files"] == vault_upload.MAX_FILES


def case_fan_route_resolves_and_batch_rechecks():
    owner, creator, _ = _http()
    import server
    c = _OFUser()
    spawned, saved = _patched(server, c)
    h = {"X-Account-Id": creator}
    try:
        r = owner.get("/api/of/v2/vault/upload/fan", params={"username": "@testfan"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json() == {"id": 31337, "username": "testfan", "name": "Test Fan"}
        r = owner.get("/api/of/v2/vault/upload/fan", params={"username": "testfam"}, headers=h)
        assert r.status_code == 404 and "No OnlyFans account" in r.text, r.text
        r = owner.get("/api/of/v2/vault/upload/fan", params={"username": "ratelimited"},
                      headers=h)
        assert r.status_code == 502 and "429" in r.text, "a 429 read as no such account"
        r = owner.get("/api/of/v2/vault/upload/fan", params={"username": "two words"},
                      headers=h)
        assert r.status_code == 400, r.text
        files = [("files", ("a.jpg", b"x" * 16, "image/jpeg"))]
        # Unknown, or not the id that was checked: refused before any claim.
        for form in ({"fan_username": "testfam", "fan_id": "31337"},
                     {"fan_username": "testfan", "fan_id": "31338"},
                     {"fan_username": "testfan"},
                     {"fan_id": "31337"}):
            r = owner.post("/api/of/v2/vault/upload/batch", data=form, files=files, headers=h)
            assert r.status_code in (400, 404), (form, r.status_code, r.text)
            assert creator not in vault_upload._live, f"{form} claimed the account"
        assert spawned == []
        r = owner.post("/api/of/v2/vault/upload/batch",
                       data={"fan_username": "testfan", "fan_id": "31337"},
                       files=files, headers=h)
        assert r.status_code == 200, r.text
        st = _discard(r.json()["run_id"], spawned)
        assert st["fan_id"] == 31337, st
    finally:
        _unpatch(server, saved)


def case_batch_route_opens_the_run_and_aligns_meta():
    owner, creator, _ = _http()
    import server
    spawned, saved = _patched(server, _OFUser())
    captured: dict = {}
    orig_start = vault_upload.start

    def fake_start(aid, **kw):
        box = vault_upload._inbox.get(kw["run_id"])
        captured.update(kw, stage_dir=box and box.stage_dir)
        return {}

    vault_upload.start = fake_start
    body, ctype = _multipart(
        {"keep_open": "1",
         "meta": json.dumps([{"hashtags": ["skipped"]}, {"hashtags": ["b"]}])},
        [("", b""), ("b.jpg", b"x" * 16)])
    try:
        r = _on_one_loop(owner, server, lambda ac: ac.post(
            "/api/of/v2/vault/upload/batch", content=body,
            headers={"X-Account-Id": creator, "Content-Type": ctype}), spawned)
    finally:
        vault_upload.start = orig_start
        _unpatch(server, saved)
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]
    vault_upload.abandon(run_id, "test")
    assert captured.get("stage_dir"), "the open run carried no staging dir"
    assert [Path(p).name for p in captured["local_paths"]] == ["b.jpg"], captured
    assert captured["metas"] == [{"hashtags": ["b"]}], \
        "a skipped nameless part shifted the details onto the wrong file"
    assert not Path(captured["stage_dir"]).exists(), "the worker left its staging dir behind"


def case_fan_dm_is_paced_as_manual_and_recorded():
    owner, creator, _ = _http()
    import automation_executor
    import server
    c = _OFUser()
    spawned, saved = _patched(server, c)
    purposes: list = []
    orig_paced = automation_executor.of_write_paced

    async def paced(aid, fn, **kw):
        purposes.append(kw.get("send_purpose"))
        return fn()

    automation_executor.of_write_paced = paced
    try:
        r = _on_one_loop(owner, server, lambda ac: ac.post(
            "/api/of/v2/vault/upload/batch",
            data={"fan_username": "testfan", "fan_id": "31337"},
            files=[("files", ("a.jpg", b"x" * 16, "image/jpeg"))],
            headers={"X-Account-Id": creator}), spawned)
    finally:
        automation_executor.of_write_paced = orig_paced
        _unpatch(server, saved)
    assert r.status_code == 200, r.text
    st = vault_upload.read_state(r.json()["run_id"])
    assert [i["status"] for i in st["items"]] == ["done"], st["items"]
    assert c.uploads == [("a.jpg", 31337)], c.uploads
    assert purposes == ["manual"], f"the fan DM went out as {purposes}"

    async def rows():
        async with get_session() as s:
            return (await s.execute(select(Message).where(
                Message.account_id == creator, Message.message_id == 5555))).scalars().all()

    got = asyncio.run(rows())
    assert len(got) == 1 and got[0].fan_id == 31337 and got[0].direction == "out", got


def case_append_route_guards():
    owner, creator, other = _http()
    h = {"X-Account-Id": creator}
    stage = tempfile.mkdtemp(dir=_SPOOL)
    run_id = vault_upload.begin(creator, keep_open=True, stage_dir=stage)
    theirs = vault_upload.begin(other, keep_open=True, stage_dir=stage)
    try:
        r = owner.post("/api/of/v2/vault/upload/batch/append",
                       data={"run_id": theirs},
                       files=[("files", ("a.jpg", b"x" * 16, "image/jpeg"))], headers=h)
        assert r.status_code == 404, "appended into another account's run"
        # Over the cap: 413, and its bytes are gone, nothing queued.
        orig = vault_upload.Limits.checked
        vault_upload.Limits.checked = lambda self: vault_upload.Limits(
            pace_s=0, max_bytes=8, max_download_bytes=8)
        try:
            r = owner.post("/api/of/v2/vault/upload/batch/append", data={"run_id": run_id},
                           files=[("files", ("big.jpg", b"x" * 64, "image/jpeg"))], headers=h)
        finally:
            vault_upload.Limits.checked = orig
        assert r.status_code == 413, r.text
        assert not [p for p in Path(stage).rglob("*") if p.is_file()], "413 left a partial"
        assert vault_upload._inbox[run_id].q.empty()
        r = owner.post("/api/of/v2/vault/upload/batch/append",
                       data={"run_id": run_id, "last": "1"},
                       files=[("files", ("a.jpg", b"x" * 16, "image/jpeg"))], headers=h)
        assert r.status_code == 200 and r.json() == {"run_id": run_id, "files": 1,
                                                     "closed": True}, r.text
        vault_upload.abandon(run_id, "test")
        r = owner.post("/api/of/v2/vault/upload/batch/append",
                       data={"run_id": run_id},
                       files=[("files", ("late.jpg", b"x" * 16, "image/jpeg"))], headers=h)
        assert r.status_code == 409 and "no longer taking files" in r.text, r.text
        assert not list(Path(stage).rglob("late.jpg")), "a refused file was left staged"
        # `closed` is close()'s answer, not an echo of `last`.
        r = owner.post("/api/of/v2/vault/upload/batch/append",
                       data={"run_id": run_id, "last": "1"}, headers=h)
        assert r.status_code == 200 and r.json()["closed"] is False, r.text
        st = vault_upload.read_state(run_id)
        assert [i["name"] for i in st["items"]] == ["a.jpg"], \
            "the accepted file vanished when the run was abandoned"
    finally:
        vault_upload.abandon(run_id, "test")
        vault_upload.abandon(theirs, "test")
        shutil.rmtree(stage, ignore_errors=True)


if __name__ == "__main__":
    _harness.run()
