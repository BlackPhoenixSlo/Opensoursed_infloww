#!/usr/bin/env python3
"""test_full_ai_live_typing — typing, GIF, photo read, mark read (04a ticket 71, full_ai_live).

OF faked (`LiveOF` behind `ax._make_client`), Jev + Writers faked, the vision call faked at
`inbound_describe.describe_message`, holds recorded (never slept). Temp DB only.

  case_typing_sign            on: each text bubble's hold = typing_delay_seconds(text, wpm), in order; off: 0 s
  case_typing_notification    off -> indicator False; on + account indicator off -> False; both on -> True
  case_text_and_gif           text bubbles, then one `giphy_id` DM; gif part has its message_id; cat_stickers marked
  case_gif_only               one OF call, `sent`, no hold above 0 s
  case_photo_read             describe_fan_photos on: the job's client reaches describe, image_desc stored,
                              Jev state has "[he sent: ...]", reply_json.fan_photo; off: no describe call
  case_describe_fails         the Turn still sends; fan_photo.outcome "failed"
  case_mark_read              once after a sent Turn; not after no_send / stood down; its error leaves `sent`
  case_config_reference       none of the three live switches reads "Read by nothing yet"

Run: ./venv/bin/python service/tests/test_full_ai_live_typing.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import contextlib  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import update  # noqa: E402

from _full_ai_fixtures import GIF_FITS, QUIET, _msg  # noqa: E402
from _full_ai_live_fixtures import LiveOF, live_rows, out_rows, payload, seed_live, world  # noqa: E402
import inbound_describe  # noqa: E402
from automations import cat_stickers, full_ai_config, full_ai_live  # noqa: E402
from automations._typing_hold import typing_delay_seconds  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Message  # noqa: E402

TAG = "laugh"
WPM = 55
DESC = "a mirror selfie in a grey hoodie"
PHOTO_RAW = json.dumps({"media": [{"type": "photo", "files": {"full": {"url": "https://cdn.example/p1.jpg"}}}]})


@contextlib.contextmanager
def _patched(obj, name, value):
    real = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield real
    finally:
        setattr(obj, name, real)


@contextlib.contextmanager
def _holds(indicator: bool = True):
    """Record every `hold_with_typing` (seconds, typing_indicator); wpm fixed, account indicator given."""
    got = []

    async def hold(_aid, _fan, seconds, *, typing_indicator=False, cut=None):
        got.append((seconds, typing_indicator))

    async def wpm(_aid):
        return WPM

    async def ind(_aid):
        return indicator
    with _patched(full_ai_live, "hold_with_typing", hold), _patched(full_ai_live, "load_typing_wpm", wpm), \
            _patched(full_ai_live, "load_typing_indicator", ind):
        yield got


async def _turn(aid, fan, mid, config=None, *, line=None, of=None, jev=(QUIET, 1.0), body="hey you", **dm_kw):
    rid = await seed_live(aid, config)
    await _msg(aid, fan, mid, "in", body, datetime.utcnow() - timedelta(seconds=30), **dm_kw)
    kw = {"line": line} if line else {}
    with world(of, jev=jev, **kw) as w:
        res = await full_ai_live.run(aid, payload(fan, mid, rid), run_id=0)
    rows = await live_rows(aid)
    return res, w, (rows[-1] if rows else None)


def _parts(row) -> list[dict]:
    return json.loads(row.reply_json)["parts"]


async def case_typing_sign():
    with _holds() as got:
        _res, w, row = await _turn("fa_ty_on", 801, 10101, {"typing_sign": True})
    texts = [p["text"] for p in _parts(row)]
    assert row.status == "sent" and len(texts) >= 2, row.status
    assert [s for s, _i in got] == [typing_delay_seconds(t, WPM) for t in texts], (got, texts)
    assert all(s > 0 for s, _i in got)
    with _holds() as got:
        _res, w, row = await _turn("fa_ty_off", 802, 10201, {"typing_sign": False})
    assert row.status == "sent" and got and all(s == 0 for s, _i in got), got
    assert len(got) == len(_parts(row)) == w.of.calls


async def case_typing_notification():
    cases = [("fa_tn_off", 803, False, True, False), ("fa_tn_acct", 804, True, False, False),
             ("fa_tn_on", 805, True, True, True)]
    for i, (aid, fan, notif, acct, want) in enumerate(cases):
        with _holds(indicator=acct) as got:
            _res, _w, row = await _turn(aid, fan, 10301 + i * 10, {"typing_notification": notif})
        assert row.status == "sent" and got and all(ind is want for _s, ind in got), (aid, got)


async def case_text_and_gif():
    gifs = cat_stickers._CATALOG[TAG][1]
    marked = []
    real = cat_stickers.mark_sent

    def mark(account_id, fan_id, now=None, tag=None, gif_id=None):
        marked.append((account_id, fan_id, tag, gif_id))
        return real(account_id, fan_id, now, tag=tag, gif_id=gif_id)
    with _holds() as got, _patched(cat_stickers, "mark_sent", mark):
        _res, w, row = await _turn("fa_gif", 806, 10401, {"gifs": True},
                                   line=f"ok:omg ur funny. i cant stop laughing\nSTICKER: {TAG}",
                                   jev=(GIF_FITS, 1.0))
    parts = _parts(row)
    *texts, gif = parts
    assert row.status == "sent" and set(gif) == {"gif", "tag", "message_id"} and gif["gif"] in gifs, parts
    assert [s["text"] for s in w.of.sent] == [p["text"] for p in texts] + [""], w.of.sent
    assert w.of.sent[-1].get("giphy_id") == gif["gif"] and all("giphy_id" not in s for s in w.of.sent[:-1])
    assert len(await out_rows("fa_gif", 806)) == len(parts) and all("message_id" in p for p in parts)
    assert marked == [("fa_gif", 806, TAG, gif["gif"])], marked
    assert got[-1][0] == 0 and all(s > 0 for s, _i in got[:-1]), got


async def case_gif_only():
    with _holds() as got:
        _res, w, row = await _turn("fa_gif1", 807, 10501, {"gifs": True}, line=f"ok:STICKER: {TAG}",
                                   jev=(GIF_FITS, 1.0))
    parts = _parts(row)
    assert (row.status, w.of.calls, len(parts)) == ("sent", 1, 1), (row.status, parts)
    assert "giphy_id" in w.of.sent[0] and "message_id" in parts[0]
    assert got and all(s == 0 for s, _i in got), got


@contextlib.contextmanager
def _vision(fail: bool = False):
    calls = []

    async def describe(account_id, message_id, client, *, his_words=""):
        calls.append(client)
        if fail:
            raise RuntimeError("vision down")
        async with get_session() as s:
            await s.execute(update(Message).where(Message.account_id == account_id,
                                                  Message.message_id == message_id).values(image_desc=DESC))
        return DESC, "qwen3-vl-30b"
    with _patched(inbound_describe, "describe_message", describe):
        yield calls


async def _desc(aid, fan, mid):
    async with get_session() as s:
        return (await s.get(Message, (aid, fan, mid))).image_desc


async def case_photo_read():
    of = LiveOF()
    with _vision() as calls:
        _res, w, row = await _turn("fa_ph_on", 808, 10601, {"describe_fan_photos": True}, of=of,
                                   body="what u think", media_count=1, raw_json=PHOTO_RAW)
    assert calls == [of], calls
    assert await _desc("fa_ph_on", 808, 10601) == DESC
    state = json.dumps(w.jev.calls[0]["state"], ensure_ascii=False)
    assert f"[he sent: {DESC}]" in state, state
    photo = json.loads(row.reply_json)["fan_photo"]
    assert photo["outcome"] == "described" and row.status == "sent", (photo, row.status)
    with _vision() as calls:
        _res, w, row = await _turn("fa_ph_off", 809, 10701, {"describe_fan_photos": False},
                                   body="what u think", media_count=1, raw_json=PHOTO_RAW)
    assert calls == [] and "fan_photo" not in json.loads(row.reply_json) and row.status == "sent"
    assert await _desc("fa_ph_off", 809, 10701) is None


async def case_describe_fails():
    with _vision(fail=True) as calls:
        _res, w, row = await _turn("fa_ph_fail", 810, 10801, {"describe_fan_photos": True},
                                   body="what u think", media_count=1, raw_json=PHOTO_RAW)
    assert len(calls) == 1 and row.status == "sent" and w.of.calls == len(_parts(row)), row.status
    assert json.loads(row.reply_json)["fan_photo"]["outcome"] == "failed"


class ReadFailsOF(LiveOF):
    def mark_chat_read(self, chat_id):
        self.read.append(int(chat_id))
        raise RuntimeError("HTTP 500")


async def case_mark_read():
    _res, w, row = await _turn("fa_rd_sent", 811, 10901)
    assert row.status == "sent" and w.of.read == [811], w.of.read
    _res, w, row = await _turn("fa_rd_nosend", 812, 10911, jev=({**QUIET, "promo": 0.99}, 1.0))
    assert row.status == "no_send" and w.of.read == [], w.of.read
    saved = list(full_ai_live.LAST_LOOK)
    full_ai_live.LAST_LOOK.insert(0, ("fake", None, lambda look: "no" if look.index == 0 else None))
    try:
        _res, w, row = await _turn("fa_rd_stood", 813, 10921)
    finally:
        full_ai_live.LAST_LOOK[:] = saved
    assert row.status == "no_send" and w.of.calls == 0 and w.of.read == [], (row.status, w.of.read)
    _res, w, row = await _turn("fa_rd_fail", 814, 10931, of=ReadFailsOF())
    assert row.status == "sent" and w.of.read == [814] and w.of.calls == len(_parts(row)), row.status


def case_config_reference():
    for k in ("reply_by_webhook", "typing_sign", "typing_notification"):
        text = json.dumps(full_ai_config.REFERENCE[k])
        assert "Read by nothing yet" not in text and "Live" in text, (k, text)
    assert all("Read by nothing yet" not in json.dumps(r) for r in full_ai_config.reference())


_harness.run()
