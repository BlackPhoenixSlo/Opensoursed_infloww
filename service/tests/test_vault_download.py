#!/usr/bin/env python3
"""Vault Pro's download routes (`vault_download_api`): the relay fallback stream, the direct path's re-sign, the
direct/relay decision. Plain-assert, no pytest (repo convention, `_harness.run()`).

Real HTTP with real owner / chatter logins. Owner A owns accD; chatter `cd` is restricted to OF folder 12.
Mirror rows: 201 photo in folder 12, 202 video in folder 99, 203 a DRM-only video (no full url) in folder 12.

  case_info_direct_only_without_proxy   — {direct} true for a Direct egress, false for a proxy (and a refused one).
  case_stream_attachment_and_bytes      — 200, every byte, Content-Disposition attachment `<id>.<ext>`, Content-Length,
                                          one VAULT_DOWNLOAD slot taken and given back.
  case_stream_is_lazy                   — the body is relayed chunk by chunk: after the first chunk out, the CDN
                                          has handed over one chunk, not the file (never read whole).
  case_403_resigns_once                 — 403 → one listing-window read → the fresh url of the same file → 200.
  case_403_after_resign_is_403          — the fresh url 403s too (a dead signature): 403, lane free.
  case_drm_only_is_422_and_unknown_404  — no full url in OF's fresh payload: 422; OF has no such media: 404.
  case_chatter_folder_gate              — the chatter: 404 outside its folders on download AND resign, 200 inside;
                                          a `u` naming another media's file is ignored (the row's url is fetched).
  case_anonymous_refused                — no login: neither route answers bytes or urls.
  case_resign_returns_fresh_url         — GET /download/resign: {url} for the same file, one by-id read, no bytes.
  case_resigns_paced_and_429_retried    — two stale downloads: one shared window read, then a by-id read for the
                                          media the window lacks, >= PAGE_GAP_S apart on
                                          the Creator (of_pacing walk), OF's 429 waited out and retried, all 200
                                          (AE 2026-11-10: unpaced, 76 re-signs in 19 s, then 429 and 26 failed).
  case_transient_resign_failure_retries_soon — a window read that failed in transit is remembered (no by-id read)
                                          FAIL_TRANSIENT_S, not FAIL_TTL_S: the panel's Retry re-asks OF.

OF and its CDN are faked at `automation_executor._make_client`: no request leaves the process.
Run: ./venv/bin/python service/tests/test_vault_download.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB
_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import admission  # noqa: E402
import automation_executor as ax  # noqa: E402
import cdn_resign  # noqa: E402
import of_pacing  # noqa: E402
import proxies  # noqa: E402
import vault_download_api  # noqa: E402
from _pre_enforcement import seed_pre_enforcement_install  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, Chatter, ChatterFolderAccess, ChatterUser, User, UserAccount, VaultItem,
)

AID = "accD"
HOST = "https://cdn2.onlyfans.com"
SIG_OLD = "?Policy=old&Signature=s&Key-Pair-Id=K"
SIG_NEW = "?Policy=new&Signature=s2&Key-Pair-Id=K"


def _full(mid: int, kind: str) -> str:
    return f"{HOST}/files/v/{mid}/source.{'mp4' if kind == 'video' else 'jpg'}"


def _payload(mid: int, kind: str, folders: list[int], sig: str = SIG_OLD, drm: bool = False) -> dict:
    full = {"sources": []} if drm else {"url": _full(mid, kind) + sig}
    return {"id": mid, "type": kind, "files": {"thumb": {"url": f"{HOST}/files/v/{mid}/thumb.jpg{sig}"}, "full": full},
            "listStates": [{"id": f, "type": "custom", "hasMedia": True, "name": f"f{f}"} for f in folders]}


ROWS = {201: ("photo", [12], False), 202: ("video", [99], False), 203: ("video", [12], True)}
BODY = {mid: bytes([mid % 256]) * (3 * 1024 * 1024 + 17) for mid in ROWS}   # > 1 chunk (CHUNK = 256 KiB)


class _Resp:
    def __init__(self, status: int, body: bytes, client: "_Client"):
        self.status_code, self._body, self._c = status, body, client
        self.headers = {"Content-Type": "application/octet-stream", "Content-Length": str(len(body))}
        self.closed = False

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self._body), chunk_size):
            self._c.chunks_out += 1
            yield self._body[i:i + chunk_size]

    def close(self):
        self.closed = True


class _Client:
    """The account's client: the CDN answers urls signed `Policy=new` (or every url when `accept_old`)."""

    def __init__(self, accept_old: bool = True, fresh: dict | None = None):
        self.account_id, self.timeout_s = AID, 5
        self.accept_old, self.fresh = accept_old, fresh
        self.gets: list[str] = []
        self.reads: list = []   # OF reads: a media id (by-id) or "p<offset>" (a listing window)
        self.chunks_out = 0
        self.lock = threading.Lock()

        def get(url, **_kw):
            with self.lock:
                self.gets.append(url)
            mid = int(url.split("/files/v/")[1].split("/")[0])
            ok = "Policy=new" in url or self.accept_old
            return _Resp(200 if ok else 403, BODY.get(mid, b"x") if ok else b"<Error/>", self)
        self.http = SimpleNamespace(get=get)

    def vault_media(self, *, offset: int = 0, **_kw):
        """OF's asc listing: the one media this OF still has (`fresh`), else nothing."""
        with self.lock:
            self.reads.append(f"p{offset}")
        return {"list": [self.fresh] if self.fresh else [], "hasMore": False}

    def vault_media_by_id(self, media_id: int):
        with self.lock:
            self.reads.append(int(media_id))
        if self.fresh is None:
            e = RuntimeError("OF 404")
            e.response = SimpleNamespace(status_code=404)
            raise e
        return self.fresh


def _use(c: _Client) -> _Client:
    """`c` is the account's client from now on; the re-sign memory and the mirror rows back as seeded (a re-sign
    writes the fresh payload over its row)."""
    cdn_resign._fresh.clear()
    cdn_resign._failed.clear()
    cdn_resign._pages.clear()
    ax._make_client = lambda _aid: c

    async def _rows():
        async with get_session() as s:
            for mid, (kind, folders, drm) in ROWS.items():
                item = await s.get(VaultItem, (AID, mid))
                if item is not None:
                    item.raw_json = json.dumps(_payload(mid, kind, folders, drm=drm))
                    item.removed_at = None
            await s.commit()
    asyncio.run(_rows())
    return c


async def case_seed():
    uid, cid = uuid.uuid4().hex, uuid.uuid4().hex
    async with get_session() as s:
        s.add(User(id=uid, username="ownerd", password="secretpw"))
        s.add(Account(id=AID, nickname="D"))
    async with get_session() as s:
        s.add(UserAccount(user_id=uid, account_id=AID))
        s.add(Chatter(id=cid, username="cd", password="secretpw", display_name="Cd",
                      created_at=datetime.utcnow(), last_seen_at=datetime.utcnow()))
    async with get_session() as s:
        s.add(ChatterUser(chatter_id=cid, user_id=uid, created_at=datetime.utcnow()))
        s.add(ChatterFolderAccess(chatter_id=cid, account_id=AID, folder_id=12, folder_name="f12",
                                  created_at=datetime.utcnow()))
        for mid, (kind, folders, drm) in ROWS.items():
            p = _payload(mid, kind, folders, drm=drm)
            s.add(VaultItem(account_id=AID, media_id=mid, kind=kind, raw_json=json.dumps(p),
                            full_url=(p["files"]["full"].get("url")), of_folder_ids=json.dumps(folders),
                            created_at=datetime(2026, 1, 1), search_text=kind, tags="[]"))
    await seed_pre_enforcement_install()


def _login(path: str, user: str):
    c = _harness.make_client()
    r = c.post(path, json={"username": user, "password": "secretpw"})
    assert r.status_code == 200, (path, r.status_code, r.text)
    return c


def _dl(http, mid: int, u: str | None = None):
    q = f"/admin/vault-ai/download?account_id={AID}&media_id={mid}"
    return http.get(q + (f"&u={u.replace('&', '%26').replace('?', '%3F')}" if u else ""))


def case_info_direct_only_without_proxy():
    owner = _login("/auth/login", "ownerd")
    orig = proxies.egress
    try:
        for eg, want in ((proxies.Direct(), True), (proxies.Proxy({"label": "p1"}), False),
                         (proxies.Refuse("unreadable"), False)):
            proxies.egress = lambda _reg, _aid, _eg=eg: _eg
            r = owner.get(f"/admin/vault-ai/download/info?account_id={AID}")
            assert r.status_code == 200 and r.json() == {"direct": want}, (eg, r.status_code, r.text)
    finally:
        proxies.egress = orig


def case_stream_attachment_and_bytes():
    owner = _login("/auth/login", "ownerd")
    c = _use(_Client())
    for mid, ext in ((201, "jpg"), (202, "mp4")):
        r = _dl(owner, mid)
        assert r.status_code == 200, (mid, r.status_code, r.text[:200])
        assert r.content == BODY[mid], (mid, len(r.content))
        assert r.headers["content-disposition"] == f'attachment; filename="{mid}.{ext}"', r.headers
        assert r.headers["content-length"] == str(len(BODY[mid])), r.headers
    assert c.gets == [_full(201, "photo") + SIG_OLD, _full(202, "video") + SIG_OLD], c.gets
    assert c.reads == [], "a good stored url needs no OF read"
    assert admission.VAULT_DOWNLOAD.busy == 0, "every slot given back"
    assert admission.VAULT_DOWNLOAD.peak >= 1


def case_stream_is_lazy():
    c = _use(_Client())
    orig = vault_download_api._gate

    async def _ok(_a, _m):
        return True
    vault_download_api._gate = _ok

    async def go():
        resp = await vault_download_api.download(account_id=AID, media_id=202, u=None)
        it = resp.body_iterator
        first = await it.__anext__()
        out_after_first = c.chunks_out
        rest = [ch async for ch in it]
        return first, out_after_first, rest
    try:
        first, out_after_first, rest = asyncio.run(go())
    finally:
        vault_download_api._gate = orig
    total = -(-len(BODY[202]) // vault_download_api.CHUNK)
    assert len(first) == vault_download_api.CHUNK and out_after_first <= 2, (len(first), out_after_first)
    assert 1 + len(rest) == total and first + b"".join(rest) == BODY[202], (len(rest), total)


def case_403_resigns_once():
    owner = _login("/auth/login", "ownerd")
    c = _use(_Client(accept_old=False, fresh=_payload(201, "photo", [12], sig=SIG_NEW)))
    r = _dl(owner, 201)
    assert r.status_code == 200 and r.content == BODY[201], (r.status_code, r.text[:200])
    assert c.gets == [_full(201, "photo") + SIG_OLD, _full(201, "photo") + SIG_NEW], c.gets
    assert c.reads == ["p0"], c.reads   # its listing window, no by-id read
    c.gets.clear()
    assert _dl(owner, 201).status_code == 200
    assert c.gets == [_full(201, "photo") + SIG_NEW] and c.reads == ["p0"], "the fresh url is reused, no 2nd read"


def case_403_after_resign_is_403():
    owner = _login("/auth/login", "ownerd")
    dead = _payload(201, "photo", [12], sig="?Policy=stillold&Signature=z&Key-Pair-Id=K")
    c = _use(_Client(accept_old=False, fresh=dead))
    r = _dl(owner, 201)
    assert r.status_code == 403, (r.status_code, r.text[:200])
    assert len(c.gets) == 2 and c.reads == ["p0"], (c.gets, c.reads)
    assert admission.VAULT_DOWNLOAD.busy == 0
    again = _dl(owner, 201)
    assert again.status_code == 403 and c.reads == ["p0"], (again.status_code, c.reads)
    assert len(c.gets) == 3, c.gets  # failure memory prevents another OF by-id read


def case_drm_only_is_422_and_unknown_404():
    owner = _login("/auth/login", "ownerd")
    c = _use(_Client(fresh=_payload(203, "video", [12], drm=True)))
    r = _dl(owner, 203)
    assert r.status_code == 422, (r.status_code, r.text[:200])
    assert c.reads == [203] and c.gets == [], (c.reads, c.gets)
    c = _use(_Client(fresh=None))
    r = _dl(owner, 777)   # no mirror row, OF has none either
    assert r.status_code in (404,), (r.status_code, r.text[:200])


def case_chatter_folder_gate():
    chatter = _login("/chatter/login", "cd")
    c = _use(_Client(fresh=_payload(202, "video", [99], sig=SIG_NEW)))
    r = _dl(chatter, 202)
    assert r.status_code == 404, ("outside its folders", r.status_code)
    r = chatter.get(f"/admin/vault-ai/download/resign?account_id={AID}&media_id=202")
    assert r.status_code == 404, ("resign outside its folders", r.status_code)
    r = _dl(chatter, 777)
    assert r.status_code == 404, ("no mirror row", r.status_code)
    assert c.gets == [] and c.reads == [], (c.gets, c.reads)
    # Inside: 201. A `u` naming 202's file rides along: ignored, 201's own url is fetched.
    r = _dl(chatter, 201, u=_full(202, "video") + SIG_NEW)
    assert r.status_code == 200 and r.content == BODY[201], (r.status_code, len(r.content))
    assert c.gets == [_full(201, "photo") + SIG_OLD], c.gets


def case_anonymous_refused():
    anon = _harness.make_client()
    c = _use(_Client())
    for path in (f"/admin/vault-ai/download?account_id={AID}&media_id=201",
                 f"/admin/vault-ai/download/resign?account_id={AID}&media_id=201",
                 f"/admin/vault-ai/download/info?account_id={AID}"):
        r = anon.get(path)
        assert r.status_code in (401, 403), (path, r.status_code, r.text[:120])
    assert c.gets == [] and c.reads == []


def case_resign_returns_fresh_url():
    owner = _login("/auth/login", "ownerd")
    c = _use(_Client(fresh=_payload(201, "photo", [12], sig=SIG_NEW)))
    stale = _full(201, "photo") + SIG_OLD
    r = owner.get("/admin/vault-ai/download/resign", params={"account_id": AID, "media_id": 201, "u": stale})
    assert r.status_code == 200 and r.json() == {"url": _full(201, "photo") + SIG_NEW}, (r.status_code, r.text)
    assert c.reads == ["p0"] and c.gets == [], (c.reads, c.gets)
    # Without `u`: the full file of the fresh payload.
    _use(c)
    r = owner.get(f"/admin/vault-ai/download/resign?account_id={AID}&media_id=201")
    assert r.status_code == 200 and r.json()["url"] == _full(201, "photo") + SIG_NEW, r.text



class _PacedClient(_Client):
    """OF reads through `of_pacing.paced` as OFClient.get_json sends them; the first answered OF's 429. Its listing
    holds 201 only, so 202 falls back to a by-id read."""

    def __init__(self):
        super().__init__(accept_old=False)
        self.at: list[float] = []
        self.too_many = 1

    def _paced(self, what, answer):
        def call():
            with self.lock:
                self.at.append(time.monotonic())
                self.reads.append(what)
                if self.too_many:
                    self.too_many -= 1
                    e = RuntimeError("OF 429")
                    e.response = SimpleNamespace(status_code=429, text="Too many requests. Please allow 0 seconds")
                    raise e
            return answer()
        return of_pacing.paced(self.account_id, call)

    def vault_media(self, *, offset: int = 0, **_kw):
        return self._paced(f"p{offset}", lambda: {"list": [_payload(201, "photo", [12], sig=SIG_NEW)],
                                                  "hasMore": False})

    def vault_media_by_id(self, media_id: int):
        kind = ROWS[int(media_id)][0]
        return self._paced(int(media_id), lambda: _payload(int(media_id), kind, ROWS[int(media_id)][1], sig=SIG_NEW))


def case_resigns_paced_and_429_retried():
    owner = _login("/auth/login", "ownerd")
    c = _use(_PacedClient())
    gap, jit = of_pacing.PAGE_GAP_S, of_pacing.JITTER_S
    of_pacing.PAGE_GAP_S, of_pacing.JITTER_S = 0.3, 0.0
    of_pacing._next_at.pop(AID, None)
    try:   # one after the other: TestClient runs each thread's request on its own loop; the relay has one
        out = {m: _dl(owner, m).status_code for m in (201, 202)}
    finally:
        of_pacing.PAGE_GAP_S, of_pacing.JITTER_S = gap, jit
    assert out == {201: 200, 202: 200}, out
    assert c.reads == ["p0", "p0", 202], c.reads   # one shared window read (429, retried), then 202 by id
    gaps = [b - a for a, b in zip(c.at, c.at[1:])]
    assert all(g >= 0.29 for g in gaps), gaps
    assert admission.VAULT_DOWNLOAD.busy == 0


def case_transient_resign_failure_retries_soon():
    owner = _login("/auth/login", "ownerd")
    c = _use(_Client(accept_old=False, fresh=_payload(201, "photo", [12], sig=SIG_NEW)))

    def blip(**_kw):
        with c.lock:
            c.reads.append("p0")
        raise RuntimeError("proxy reset")
    c.vault_media = blip
    assert _dl(owner, 201).status_code == 403
    assert _dl(owner, 201).status_code == 403 and c.reads == ["p0"], "a hover's frames: one OF call, no by-id"
    until = cdn_resign._failed[(AID, 201)]
    assert until - time.monotonic() <= cdn_resign.FAIL_TRANSIENT_S, until
    assert cdn_resign._pages[(AID, 0)][0] - time.monotonic() <= cdn_resign.FAIL_TRANSIENT_S
    cdn_resign._failed[(AID, 201)] = time.monotonic() - 1   # FAIL_TRANSIENT_S later
    cdn_resign._pages[(AID, 0)] = (time.monotonic() - 1, None)
    del c.vault_media                                        # OF answers again
    assert _dl(owner, 201).status_code == 200 and c.reads == ["p0", "p0"], c.reads


_harness.run()
