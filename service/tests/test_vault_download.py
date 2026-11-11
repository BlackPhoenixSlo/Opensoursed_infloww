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
  case_resign_ignores_foreign_u         — the chatter's resign with a `u` of a hidden media: that media's fresh url
                                          (cached) never comes back; the visible media's own fresh url does.
  case_empty_account_id_is_422          — `account_id=` on every route: 422, never an anonymous answer.
  case_video_is_not_gzipped             — a `video/mp4` upstream streams with its Content-Length, no Content-Encoding.
  case_disconnect_before_body_frees_slot — the client is gone before the body generator starts: slot back, the
                                          upstream response closed (the generator's `finally` never runs then).
  case_full_lane_is_503                 — every slot held: the next download waits SLOT_WAIT_S, then 503, lane intact.

OF and its CDN are faked at `automation_executor._make_client`: no request leaves the process.
Run: ./venv/bin/python service/tests/test_vault_download.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB
_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
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
    def __init__(self, status: int, body: bytes, client: "_Client", ctype: str = "application/octet-stream"):
        self.status_code, self._body, self._c = status, body, client
        self.headers = {"Content-Type": ctype, "Content-Length": str(len(body))}
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
        self.ctype = "application/octet-stream"
        self.resps: list[_Resp] = []
        self.lock = threading.Lock()

        def get(url, **_kw):
            with self.lock:
                self.gets.append(url)
            mid = int(url.split("/files/v/")[1].split("/")[0])
            ok = "Policy=new" in url or self.accept_old
            r = _Resp(200 if ok else 403, BODY.get(mid, b"x") if ok else b"<Error/>", self, self.ctype)
            self.resps.append(r)
            return r
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


def case_resign_ignores_foreign_u():
    chatter = _login("/chatter/login", "cd")
    c = _use(_Client(fresh=_payload(201, "photo", [12], sig=SIG_NEW)))
    # 202 (folder 99, hidden from the chatter) was re-signed earlier for someone else: its fresh url is cached.
    cdn_resign._remember(AID, _payload(202, "video", [99], sig=SIG_NEW))
    r = chatter.get("/admin/vault-ai/download/resign",
                    params={"account_id": AID, "media_id": 201, "u": _full(202, "video") + SIG_OLD})
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json() == {"url": _full(201, "photo") + SIG_NEW}, ("201's own url, never 202's", r.json())
    assert c.reads == [201], c.reads
    assert (AID, 201) not in cdn_resign._failed, "a mismatched u must not mark the visible media failed"


def case_empty_account_id_is_422():
    owner = _login("/auth/login", "ownerd")
    anon = _harness.make_client()
    c = _use(_Client())
    for path in ("/admin/vault-ai/download/info?account_id=",
                 "/admin/vault-ai/download/resign?account_id=&media_id=201",
                 "/admin/vault-ai/download?account_id=&media_id=201"):
        r = owner.get(path)
        assert r.status_code == 422, (path, r.status_code, r.text[:120])
        r = anon.get(path)
        assert r.status_code in (401, 403, 422), (path, r.status_code, r.text[:120])
    assert c.gets == [] and c.reads == []


def case_video_is_not_gzipped():
    owner = _login("/auth/login", "ownerd")
    c = _use(_Client())
    c.ctype = "video/mp4"
    r = owner.get(f"/admin/vault-ai/download?account_id={AID}&media_id=202", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.content == BODY[202], (r.status_code, len(r.content))
    assert r.headers.get("content-type") == "video/mp4", r.headers
    assert "content-encoding" not in r.headers, r.headers
    assert r.headers.get("content-length") == str(len(BODY[202])), r.headers


def _no_gate():
    orig = vault_download_api._gate

    async def _ok(_a, _m):
        return True
    vault_download_api._gate = _ok
    return orig


def case_disconnect_before_body_frees_slot():
    c = _use(_Client())
    orig = _no_gate()
    sent: list[dict] = []

    async def receive():
        return {"type": "http.disconnect"}

    async def send(m):
        # A send that yields (the hook chain's memory stream does): the disconnect's cancel lands here, on the
        # response start, before Starlette ever iterates the body.
        sent.append(m)
        await asyncio.sleep(0.05)

    async def go():
        resp = await vault_download_api.download(account_id=AID, media_id=202, u=None)
        assert admission.VAULT_DOWNLOAD.busy == 1, admission.VAULT_DOWNLOAD.busy
        # ASGI 2.3 (uvicorn's): the disconnect wins the task group, the body generator never starts.
        await resp({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send)
    try:
        asyncio.run(go())
    finally:
        vault_download_api._gate = orig
    assert [m["type"] for m in sent] == ["http.response.start"], sent
    assert c.chunks_out == 0, ("the body never started", c.chunks_out)
    assert admission.VAULT_DOWNLOAD.busy == 0, ("slot leaked", admission.VAULT_DOWNLOAD.busy)
    assert c.resps and all(r.closed for r in c.resps), "the upstream response is closed"


def case_full_lane_is_503():
    from fastapi import HTTPException
    _use(_Client())
    orig, wait = _no_gate(), vault_download_api.SLOT_WAIT_S
    lane = admission.VAULT_DOWNLOAD
    vault_download_api.SLOT_WAIT_S = 0.05

    async def go():
        for _ in range(lane.cap):
            await lane.__aenter__()
        try:
            await vault_download_api.download(account_id=AID, media_id=201, u=None)
        except HTTPException as e:
            return e.status_code
        finally:
            for _ in range(lane.cap):
                await lane.__aexit__()
        return 200
    try:
        code = asyncio.run(go())
    finally:
        vault_download_api._gate, vault_download_api.SLOT_WAIT_S = orig, wait
    assert code == 503, code
    assert lane.busy == 0, lane.busy



async def _until(pred, s: float = 3.0) -> bool:
    end = asyncio.get_running_loop().time() + s
    while not pred():
        if asyncio.get_running_loop().time() > end:
            return False
        await asyncio.sleep(0.01)
    return True


def _count_leaves(lane) -> list[int]:
    """Every slot give-back of `lane` from now on (`__aexit__` goes through `leave` too); undo with `del lane.leave`."""
    n: list[int] = []
    real = type(lane).leave.__get__(lane)

    def leave() -> None:
        n.append(1)
        real()
    lane.leave = leave
    return n


async def _drain(resp) -> bytes:
    got: list[bytes] = []

    async def receive():
        await asyncio.Event().wait()

    async def send(m):
        if m["type"] == "http.response.body":
            got.append(m.get("body", b""))
    await resp({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send)
    return b"".join(got)


def case_slot_held_until_upstream_close_finishes():
    """#37: the slot is freed only once the upstream close has finished, so a burst of ended streams never admits new
    ones while the old curl transfers are still closing."""
    c = _use(_Client())
    orig, orig_close = _no_gate(), vault_download_api._close
    lane = admission.VAULT_DOWNLOAD
    closing, finish = threading.Event(), threading.Event()

    def slow_close(r):
        closing.set()
        finish.wait(5)
        orig_close(r)
    vault_download_api._close = slow_close
    leaves = _count_leaves(lane)
    seen: dict = {}

    async def go():
        resp = await vault_download_api.download(account_id=AID, media_id=201, u=None)
        seen["body"] = await _drain(resp)
        assert await asyncio.to_thread(closing.wait, 5), "the close started"
        await asyncio.sleep(0.1)
        seen["mid"] = (lane.busy, len(leaves), c.resps[0].closed)
        finish.set()
        seen["freed"] = await _until(lambda: lane.busy == 0)
        await asyncio.sleep(0.05)
    try:
        asyncio.run(go())
    finally:
        finish.set()
        vault_download_api._gate, vault_download_api._close = orig, orig_close
        del lane.leave
    assert seen["body"] == BODY[201], len(seen["body"])
    assert seen["mid"] == (1, 0, False), ("slot freed while the close still ran", seen["mid"])
    assert seen["freed"] and c.resps[0].closed, seen
    assert len(leaves) == 1, ("freed exactly once", leaves)


def case_send_idle_cuts_a_stalled_consumer():
    """#39: a browser that takes no chunk for SEND_IDLE_S is cut: the stream ends, upstream is closed, the slot is
    freed exactly once, and the next download streams."""
    c = _use(_Client())
    orig, idle = _no_gate(), vault_download_api.SEND_IDLE_S
    lane = admission.VAULT_DOWNLOAD
    vault_download_api.SEND_IDLE_S = 0.2
    leaves = _count_leaves(lane)
    seen: dict = {}

    async def go():
        resp = await vault_download_api.download(account_id=AID, media_id=202, u=None)

        async def receive():
            await asyncio.Event().wait()   # no disconnect: the socket looks alive

        async def send(m):
            if m["type"] == "http.response.body":
                await asyncio.Event().wait()   # the tab stopped reading
        t0 = time.monotonic()
        try:
            await asyncio.wait_for(resp({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send), 3)
            seen["ended"] = "returned"
        except BaseException as e:  # noqa: BLE001 — the cut surfaces as an error; which one is Starlette's choice
            seen["ended"] = type(e).__name__
        seen["secs"] = time.monotonic() - t0
        seen["freed"] = await _until(lambda: lane.busy == 0)
        await asyncio.sleep(0.05)
        seen["leaves"] = len(leaves)
        seen["next"] = await _drain(await vault_download_api.download(account_id=AID, media_id=201, u=None))
        seen["freed_next"] = await _until(lambda: lane.busy == 0)
    try:
        asyncio.run(go())
    finally:
        vault_download_api._gate, vault_download_api.SEND_IDLE_S = orig, idle
        del lane.leave
    brief = {k: v for k, v in seen.items() if k != "next"}
    assert seen["secs"] < 2, ("the stalled stream was cut by SEND_IDLE_S, not left hanging", brief)
    assert seen["freed"] and seen["leaves"] == 1, brief
    assert c.resps[0].closed, "the stalled stream's upstream is closed"
    assert seen["next"] == BODY[201] and seen["freed_next"], (len(seen["next"]), seen.get("freed_next"))


class _Cut(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _cut_run(chunked: bool):
    """media 202 through the whole middleware stack (as uvicorn calls it), its upstream dying after one chunk (curl
    28); `chunked`: the upstream sent no Content-Length. -> (ASGI messages sent, warning lines, exception out)."""
    owner = _login("/auth/login", "ownerd")
    c = _use(_Client())
    get = c.http.get

    def cut_get(url, **kw):
        r = get(url, **kw)
        full = r.iter_content
        if chunked:
            r.headers.pop("Content-Length", None)

        def iter_content(chunk_size=65536):
            it = full(chunk_size)
            yield next(it)
            raise RuntimeError("Failed to perform, curl: (28) Operation too slow. Less than 1 bytes/sec")
        r.iter_content = iter_content
        return r
    c.http.get = cut_get
    import server
    cookie = "; ".join(f"{k}={v}" for k, v in owner.cookies.items()).encode()
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
             "path": "/admin/vault-ai/download", "raw_path": b"/admin/vault-ai/download", "root_path": "",
             "query_string": f"account_id={AID}&media_id=202".encode(), "server": ("testserver", 80),
             "client": ("127.0.0.1", 5000), "headers": [(b"host", b"testserver"), (b"cookie", cookie)]}
    out: list[dict] = []
    asked = []

    async def receive():   # the request once, then (as uvicorn) nothing until the client goes
        asked.append(1)
        if len(asked) == 1:
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()

    async def send(m):
        out.append(m)
    h = _Cut()
    vault_download_api.log.addHandler(h)
    exc = None
    try:
        asyncio.run(server.app(scope, receive, send))
    except Exception as e:  # noqa: BLE001 — returned for the case to judge
        exc = e
    finally:
        vault_download_api.log.removeHandler(h)
    return out, h.lines, exc


def case_upstream_cut_mid_body_ends_short_without_raising():
    """The CDN goes silent / drops mid-body (curl 28 / 18 on the proxy): the stream ends short of its Content-Length
    (the browser's byte count fails the item), one warning, no exception out of the body, the slot given back."""
    out, lines, exc = _cut_run(chunked=False)
    assert exc is None, repr(exc)
    start, bodies = out[0], [m for m in out if m["type"] == "http.response.body"]
    hdr = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    assert start["status"] == 200 and hdr["content-length"] == str(len(BODY[202])), start
    assert b"".join(m.get("body", b"") for m in bodies) == BODY[202][:vault_download_api.CHUNK], len(bodies)
    assert all(m.get("more_body") for m in bodies), "never completed: uvicorn closes the connection short"
    assert [x for x in lines if "upstream cut" in x and "media=202" in x and "curl: (28)" in x], lines
    assert [x for x in lines if "status=upstream_cut" in x], lines
    assert admission.VAULT_DOWNLOAD.busy == 0, "the slot given back"


def case_chunked_upstream_cut_mid_body_aborts():
    """Same cut with no Content-Length (chunked): a clean end would read as the whole file and the browser has no
    length to check, so the final message is dropped too (`cut_short`: uvicorn closes without the terminating chunk);
    no exception out, one warning, the slot given back."""
    out, lines, exc = _cut_run(chunked=True)
    assert exc is None, repr(exc)
    start, bodies = out[0], [m for m in out if m["type"] == "http.response.body"]
    hdr = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    assert start["status"] == 200 and "content-length" not in hdr, start
    assert b"".join(m.get("body", b"") for m in bodies) == BODY[202][:vault_download_api.CHUNK], len(bodies)
    assert all(m.get("more_body") for m in bodies), ("never completed", [(m["type"], len(m.get("body", b"")), m.get("more_body")) for m in out])
    assert [x for x in lines if "upstream cut" in x and "media=202" in x], lines
    assert [x for x in lines if "status=upstream_cut" in x], lines
    assert admission.VAULT_DOWNLOAD.busy == 0, "the slot given back"


def case_short_body_is_cut_not_completed():
    """server._CutShortStreams: a body short of its Content-Length never sends the final message (uvicorn then
    closes the connection, no "shorter than Content-Length" RuntimeError); a full one, HEAD, a 304 pass as sent."""
    import server

    def run(method: str, status: int, length: int, chunks: list[bytes]):
        out: list[dict] = []

        async def app(_s, _r, send):
            await send({"type": "http.response.start", "status": status,
                        "headers": [(b"content-type", b"x"), (b"content-length", str(length).encode())]})
            for i, ch in enumerate(chunks):
                await send({"type": "http.response.body", "body": ch, "more_body": i < len(chunks) - 1})

        async def send(m):
            out.append(m)
        asyncio.run(server._CutShortStreams(app)({"type": "http", "method": method}, None, send))
        return [(m["type"], m.get("more_body", False)) for m in out]

    start, more, last = ("http.response.start", False), ("http.response.body", True), ("http.response.body", False)
    assert run("GET", 200, 10, [b"abc", b""]) == [start, more], "short: the final message dropped"
    assert run("GET", 200, 6, [b"abc", b"def"]) == [start, more, last], "full: completed"
    assert run("HEAD", 200, 10, [b""]) == [start, last], "HEAD: no body to count"
    assert run("GET", 304, 10, [b""]) == [start, last], "304: no body to count"


_harness.run()
