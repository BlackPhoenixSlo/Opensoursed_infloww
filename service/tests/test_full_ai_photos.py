#!/usr/bin/env python3
"""test_full_ai_photos — Full AI Chat reads the photo he sends (side key `describe_fan_photos`).

Run: ./venv/bin/python service/tests/test_full_ai_photos.py

No paid call: the vision call is a fake `llm_client.chat` on the describe purposes (as
test_autoreply.py fakes it), the CDN download and key check are faked, Writers and Jev use the
Full AI fakes. Covers: key off reads every line as before; key on puts Auto-reply's
`[he sent: <desc>]` in the Router state and the Writer history; one describe per photo (the
second Turn is a cache hit); a video still is labelled; no key / cap / model failure answer with
`MEDIA_ONLY`; Shadow reads cached descriptions only; the Test chat's photo route describes once
for both sides, a side with the key off reads `MEDIA_ONLY`, a reload shows it; upload limits.
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import base64  # noqa: E402
import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from _full_ai_chat_helpers import (  # noqa: E402
    A, NANO, OK_LINE, OWNER_A, TURN, _body, _db, _guarded, _reply, _rows, _store_config,
)
from _full_ai_fixtures import QUIET, FakeJev, FakeWriterHTTP, _fake_jev  # noqa: E402
import inbound_describe  # noqa: E402
import llm_client  # noqa: E402
from automations import _router_jev as router  # noqa: E402
from automations import full_ai_chat as runner  # noqa: E402
from automations import full_ai_photo  # noqa: E402
from automations._jev import MEDIA_ONLY  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AiDecision, Message  # noqa: E402

PHOTO = "/admin/full-ai/test/photo"
DESC = "a selfie of a guy in a grey hoodie, thumbs up, kitchen behind him"
_PHOTO_RAW = json.dumps({"media": [{"type": "photo", "files": {"full": {"url": "https://cdn.example/p1.jpg"}}}]})
_VIDEO_RAW = json.dumps({"media": [{"type": "video", "files": {"preview": {"url": "https://cdn.example/v1.jpg"}}}]})
_CAP = llm_client.LLMCapExceeded(A, 100, 101)
_DESCRIBE = {inbound_describe.PURPOSE, inbound_describe.PURPOSE_TEST}
T0 = datetime(2026, 11, 10, 12, 0)


# ── Fakes ─────────────────────────────────────────────────────────────

@contextlib.contextmanager
def _vision(reply="ok", *, key: bool = True):
    """The describe call faked on its purposes only (Writers keep the real `llm_client.chat` over
    the faked wire): `reply` is the description, or an exception to raise. Yields the calls."""
    calls: list[dict] = []
    real = llm_client.chat

    async def chat(**kw):
        if kw.get("purpose") not in _DESCRIBE:
            return await real(**kw)
        calls.append(kw)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(content=DESC if reply == "ok" else reply, call_id=1)

    async def key_ok(_aid):
        return key

    async def download(_client, urls):
        calls.append({"download": list(urls)})
        return ["data:image/jpeg;base64,AAAA" for _ in urls]

    saved = (llm_client.chat, inbound_describe.key_available, inbound_describe.download_frames,
             inbound_describe.shrink_data_url)
    llm_client.chat = chat  # type: ignore[assignment]
    inbound_describe.key_available = key_ok  # type: ignore[assignment]
    inbound_describe.download_frames = download  # type: ignore[assignment]
    inbound_describe.shrink_data_url = lambda u, e=0: u  # type: ignore[assignment]
    try:
        yield calls
    finally:
        (llm_client.chat, inbound_describe.key_available, inbound_describe.download_frames,
         inbound_describe.shrink_data_url) = saved


def _describes(calls: list[dict]) -> list[dict]:
    return [c for c in calls if "purpose" in c]


def _row(direction: str, body: str, mid: int, *, media: int = 0, desc: str | None = None, mins: int = 0):
    return SimpleNamespace(direction=direction, body=body, created_at=T0 + timedelta(minutes=mins),
                           message_id=mid, automation_kind=None, media_count=media, raw_json=None,
                           price_cents=None, is_paid=False, purchased_at=None, image_desc=desc)


async def _seed(fan: int, rows: list[dict]) -> None:
    async with get_session() as s:
        for r in rows:
            s.add(Message(account_id=A, fan_id=fan, **r))


async def _msgs(fan: int) -> list[Message]:
    async with get_session() as s:
        from sqlalchemy import select
        return list((await s.execute(select(Message).where(Message.account_id == A, Message.fan_id == fan)
                                     .order_by(Message.created_at, Message.message_id))).scalars().all())


def _png(fmt: str = "PNG", size=(40, 30)) -> str:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, format=fmt)
    mime = {"PNG": "png", "JPEG": "jpeg", "GIF": "gif", "WEBP": "webp"}[fmt]
    return f"data:image/{mime};base64," + base64.b64encode(buf.getvalue()).decode()


def _config(checkpoint: bool, draft: bool) -> None:
    _store_config(A, {"checkpoint": {"describe_fan_photos": checkpoint},
                      "draft": {"describe_fan_photos": draft}, "rev": 0})


# ── The one line rule (pure) ──────────────────────────────────────────

def case_key_off_lines_identical():
    """Key off: a described photo reads exactly as it did before the feature (`MEDIA_ONLY`, or
    his text alone) and the whole Jev state equals the rows' with no description at all."""
    def rows(desc):
        return ([_row("out", "hey babe", 1)],
                [_row("in", "", 2, media=1, desc=desc, mins=1), _row("in", "rate me", 3, media=1, desc=desc, mins=2)])
    th, turn = rows(DESC)
    off, _ = runner.build_state(turn, th, None, None, photos=False)
    th0, turn0 = rows(None)
    base, _ = runner.build_state(turn0, th0, None, None)
    assert off == base, (off, base)
    assert off["fan_new_messages"] == [MEDIA_ONLY, "rate me"], off


def case_key_on_tag_in_state():
    """Key on: his described photo reads Auto-reply's tag, after his text; an undescribed one
    stays `MEDIA_ONLY`; her media never takes a tag."""
    th = [_row("in", "", 1, media=1, desc="old pic of a dog"), _row("out", "", 2, media=1, desc="x", mins=1)]
    turn = [_row("in", "", 3, media=1, desc=DESC, mins=2), _row("in", "rate me", 4, media=1, desc=DESC, mins=3),
            _row("in", "", 5, media=1, mins=4)]
    st, _ = runner.build_state(turn, th, None, None, photos=True)
    assert st["fan_new_messages"] == [f"[he sent: {DESC}]", f"rate me [he sent: {DESC}]", MEDIA_ONLY], st
    assert router.line_text(th[0]) == "[he sent: old pic of a dog]"
    assert router.line_text(th[1]) == router.HER_MEDIA
    runner.build_state(turn, th, None, None, photos=False)     # switched back per Turn
    assert router.line_text(th[0]) == MEDIA_ONLY and router.line_text(turn[1]) == "rate me"


# ── describe_turn: the real-messages step ─────────────────────────────

def case_describe_once_then_cache():
    """The Turn's undescribed photo is described once (row cached); the next Turn's read is a
    cache hit with no call."""
    fan = 7101
    _db(lambda: _seed(fan, [dict(message_id=71011, direction="in", body="<p>what u think</p>", media_count=1,
                                 raw_json=_PHOTO_RAW, created_at=T0)]))
    with _vision() as calls:
        turn = _db(lambda: _msgs(fan))
        rec = _db(lambda: full_ai_photo.describe_turn(A, turn, object()))
        assert rec["outcome"] == "described" and rec["model"] == "qwen3-vl-30b", rec
        assert isinstance(rec["ms"], int), rec
        assert turn[0].image_desc == DESC
        router.read_photos(turn, True)
        assert router.line_text(turn[0]) == f"what u think [he sent: {DESC}]"
        prompt = _describes(calls)[0]["messages"][0]["content"][0]["text"]
        assert prompt.startswith(inbound_describe._PROMPT) and prompt.endswith("what u think"), prompt
        again = _db(lambda: _msgs(fan))
        assert again[0].image_desc == DESC          # cached on messages.image_desc
        rec2 = _db(lambda: full_ai_photo.describe_turn(A, again, object()))
        assert rec2 == {"outcome": "cached", "model": None, "ms": None}, rec2
    assert len(_describes(calls)) == 1, calls


def case_video_still_labelled():
    fan = 7102
    _db(lambda: _seed(fan, [dict(message_id=71021, direction="in", body="", media_count=1,
                                 raw_json=_VIDEO_RAW, created_at=T0)]))
    with _vision():
        turn = _db(lambda: _msgs(fan))
        rec = _db(lambda: full_ai_photo.describe_turn(A, turn, object()))
    assert rec["outcome"] == "described", rec
    assert turn[0].image_desc == f"a video (this is one frame of it): {DESC}", turn[0].image_desc


def case_failures_answer_media_only():
    """No key (before any download), cap, a provider error and a crash: no description, the
    line stays `MEDIA_ONLY`, and each outcome is recorded."""
    cases = [("no_key", dict(key=False)), ("cap", dict(reply=_CAP)),
             ("none", dict(reply=llm_client.LLMError("502"))), ("failed", dict(reply=RuntimeError("boom"))),
             ("none", dict(reply="I can't help with that."))]
    for i, (want, kw) in enumerate(cases):
        fan, mid = 7110 + i, 71100 + i
        _db(lambda fan=fan, mid=mid: _seed(fan, [dict(message_id=mid, direction="in", body="", media_count=1,
                                                      raw_json=_PHOTO_RAW, created_at=T0)]))
        with _vision(**kw) as calls:
            turn = _db(lambda fan=fan: _msgs(fan))
            rec = _db(lambda turn=turn: full_ai_photo.describe_turn(A, turn, object()))
        assert rec["outcome"] == want, (want, rec)
        if want == "no_key":
            assert calls == [], calls               # key check before the CDN download
        router.read_photos(turn, True)
        assert router.line_text(turn[0]) == MEDIA_ONLY and turn[0].image_desc is None, (want, turn[0].image_desc)


def case_shadow_reads_cached_only():
    """Shadow (no OF client): with the checkpoint key on, a cached description reads as the tag
    and the row records `cached`; an undescribed photo records `no_client` and reads
    `MEDIA_ONLY`; key off: no record."""
    fan = 7120
    _db(lambda: _seed(fan, [
        dict(message_id=71200, direction="out", body="hey", created_at=T0),
        dict(message_id=71201, direction="in", body="<p>me</p>", media_count=1, raw_json=_PHOTO_RAW,
             image_desc=DESC, created_at=T0 + timedelta(minutes=1)),
        dict(message_id=71202, direction="out", body="cute", created_at=T0 + timedelta(minutes=2)),
        dict(message_id=71203, direction="in", body="", media_count=1, raw_json=_PHOTO_RAW,
             created_at=T0 + timedelta(minutes=3))]))
    _config(True, False)
    assert _db(lambda: runner._photos_on(A)) is True
    with _vision() as calls:
        on = _db(lambda: runner._read(A, fan, 71201, True))
    assert _describes(calls) == [], calls
    (a1, st1, _, p1), (a2, st2, _, p2) = on
    assert st1["fan_new_messages"] == [f"me [he sent: {DESC}]"] and p1["outcome"] == "cached", (st1, p1)
    assert st2["fan_new_messages"] == [MEDIA_ONLY] and p2["outcome"] == "no_client", (st2, p2)
    assert f"[he sent: {DESC}]" in json.dumps(st2["thread"]), st2["thread"]
    _config(False, False)
    assert _db(lambda: runner._photos_on(A)) is False
    off = _db(lambda: runner._read(A, fan, 71201, False))
    assert [o[3] for o in off] == [None, None] and off[0][1]["fan_new_messages"] == ["me"], off
    row_id, *_ = _db(lambda: runner._record(A, fan, a1, st1, False, "jev down", p1))
    async def jev_json():
        async with get_session() as s:
            return json.loads((await s.get(AiDecision, row_id)).jev_json)
    assert _db(jev_json)["photo"] == p1


# ── Test chat: the photo route and both sides ─────────────────────────

def _turn(body: dict, *, writer: str = OK_LINE):
    fake_w, fake_j = FakeWriterHTTP({NANO: writer}), FakeJev((QUIET, 1.0))
    with _guarded(), fake_w.on(), _fake_jev(fake_j):
        r = OWNER_A.post(TURN, json=body)
    assert r.status_code == 200, r.text
    return fake_w, fake_j


def _writer_text(fake_w: FakeWriterHTTP) -> str:
    return json.dumps(fake_w.requests[0]["body"]["messages"])


def case_test_chat_one_describe_both_sides():
    """The photo is described once; the checkpoint (key on) Router and Writer read the tag, the
    draft (key off) reads `MEDIA_ONLY`; the session read and the next Turn's thread keep it."""
    _config(True, False)
    with _vision() as calls:
        r = OWNER_A.post(PHOTO, json={"account_id": A, "image": _png(), "text": ""})
        assert r.status_code == 200, r.text
        photo = r.json()
        assert photo["desc"] == DESC and photo["outcome"] == "described", photo
        assert photo["thumb"].startswith("data:image/jpeg;base64,"), photo["thumb"][:40]
        pair = "photo1"
        w_l, j_l = _turn({**_body(pair, text=""), "photo": photo})
        w_r, j_r = _turn({**_body(pair, text="", side="draft"), "photo": photo})
    assert len(_describes(calls)) == 1 and _describes(calls)[0]["purpose"] == "full_ai_test_photo", calls
    assert j_l.calls[0]["state"]["fan_new_messages"] == [f"[he sent: {DESC}]"], j_l.calls[0]["state"]
    assert f"[he sent: {DESC}]" in _writer_text(w_l)
    assert j_r.calls[0]["state"]["fan_new_messages"] == [MEDIA_ONLY], j_r.calls[0]["state"]
    assert DESC not in _writer_text(w_r) and MEDIA_ONLY in _writer_text(w_r)
    rows = _rows(A, pair)
    fp = [_reply(x)["fan_photo"] for x in rows]
    assert [f["read"] for f in fp] == [True, False] and {f["desc"] for f in fp} == {DESC}, fp
    got = OWNER_A.get("/admin/full-ai/test/session", params={"account_id": A, "pair": pair}).json()["rows"]
    assert [(x["text"], x["photo"]["desc"], x["photo"]["read"]) for x in got] == [("", DESC, True), ("", DESC, False)], got
    # Turn 2 on the checkpoint: his photo is in the thread, still tagged (rebuilt off the row).
    w2, j2 = _turn(_body(pair, n=2, text="so?"))
    assert f"[he sent: {DESC}]" in json.dumps(j2.calls[0]["state"]["thread"]), j2.calls[0]["state"]
    assert f"[he sent: {DESC}]" in _writer_text(w2)


def case_test_chat_keys_off_no_call():
    """Both sides off: the route makes no vision call and returns outcome off; his text with the
    photo reads as his text."""
    _config(False, False)
    with _vision() as calls:
        photo = OWNER_A.post(PHOTO, json={"account_id": A, "image": _png("JPEG"), "text": "hi"}).json()
        assert photo["outcome"] == "off" and photo["desc"] is None, photo
        _, j = _turn({**_body("photo2", text="hi"), "photo": photo})
    assert _describes(calls) == []
    assert j.calls[0]["state"]["fan_new_messages"] == ["hi"]


def case_test_chat_no_key_424_and_cap_429():
    """The account's own DeepInfra key missing: llm_client's key error → 424 (the page's key
    notice), nothing sent anywhere; the cost cap → 429."""
    _config(True, True)
    fake_w = FakeWriterHTTP({})
    with fake_w.on():
        r = OWNER_A.post(PHOTO, json={"account_id": A, "image": _png(), "text": ""})
    assert r.status_code == 424, (r.status_code, r.text)
    assert fake_w.requests == [], fake_w.requests
    with _vision(reply=_CAP):
        r = OWNER_A.post(PHOTO, json={"account_id": A, "image": _png(), "text": ""})
    assert r.status_code == 429, r.text
    with _vision(reply=llm_client.LLMError("502")):
        r = OWNER_A.post(PHOTO, json={"account_id": A, "image": _png(), "text": ""})
    assert r.status_code == 200 and r.json()["outcome"] == "none" and r.json()["desc"] is None, r.text


def case_upload_validation():
    _config(False, False)
    for fmt in ("PNG", "JPEG", "GIF", "WEBP"):
        assert OWNER_A.post(PHOTO, json={"account_id": A, "image": _png(fmt)}).status_code == 200, fmt
    bad = ["data:text/plain;base64,aGVsbG8=", "data:image/png;base64,not-base64!!",
           "data:image/png;base64," + base64.b64encode(b"not an image").decode(), "https://x/y.png",
           "data:image/svg+xml;base64," + base64.b64encode(b"<svg/>").decode()]
    for img in bad:
        r = OWNER_A.post(PHOTO, json={"account_id": A, "image": img})
        assert r.status_code == 415, (img[:30], r.status_code, r.text)
    assert r.json()["detail"] == "Pick a JPG, PNG, GIF or WebP image.", r.text
    big = "data:image/png;base64," + "A" * (full_ai_photo.MAX_UPLOAD * 4 // 3 + 8)
    r = OWNER_A.post(PHOTO, json={"account_id": A, "image": big})
    assert r.status_code == 413 and r.json()["detail"] == "The image is larger than 20 MB.", r.status_code
    # A turn needs text or a photo; a forged photo must look like the route's.
    assert OWNER_A.post(TURN, json=_body("photo3", text="")).status_code == 422
    forged = {"desc": DESC, "thumb": "https://evil/x.png", "outcome": "described"}
    assert OWNER_A.post(TURN, json={**_body("photo3", text=""), "photo": forged}).status_code == 422
    # Another Agency's account: refused before any work.
    from _full_ai_chat_helpers import B
    assert OWNER_A.post(PHOTO, json={"account_id": B, "image": _png()}).status_code == 403


if __name__ == "__main__":
    _harness.run()
