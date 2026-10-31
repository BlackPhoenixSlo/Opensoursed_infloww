#!/usr/bin/env python3
"""event_transcode_decide: the pure decisions of service/event_transcoder.py as tables.
Pure: no DB, no clock (`now` is passed), no I/O; the shell's own path is test_event_transcoder_tip.py
(and the private-alias identity check lives there, since importing the shell binds a DB).

Pins: route sends a dict chat_message / PPV-unlock payload to its writer, toasts and chat_queue_* to
theirs, anything else (a non-dict chat_message too) to the touch fall-through, skipping `__` keys.
The blast ring ignores updates, a total of -1 or under 5 and a bad id; a cancel (finish or update)
removes its id; a re-sent finish replaces its entry (newest last); it keeps the newest 32. user_blob reads fromUser > user > data.relatedUser >
data.user; avatar > c144 > c50 > any str thumb; a non-int id or no field is None. dm_plan skips a
frame missing an id or the account, plans no row for our own echo, reads a tip's cents from
tipAmount (price as fallback, a negative one is 0), keeps is_paid NULL when free, emits exact
`messages` columns, gives a non-tip media/gif DM to the image hook (else words); a degenerate
isTip + media + tipAmount 0 is words. fan_upsert: newest non-blank field wins, blanks never
clobber on conflict, source from subscribedOn/By on insert, the flags handed back for the heal. ppv_fields: message first, then the
payload's fallbacks; None without an id, a fan or an amount.

Runs under pytest (parametrized tables) or as a script (the repo's convention, no pytest needed):
    ./venv/bin/python service/tests/test_event_transcode_decide.py
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import event_transcode_decide as td  # noqa: E402
from event_transcode_decide import Inbound, Outbound, Skip  # noqa: E402

try:
    import pytest
    table = pytest.mark.parametrize
except ImportError:  # script mode: the runner below calls each row
    def table(names, rows):
        def mark(fn):
            fn.rows = rows
            return fn
        return mark

A = "9101"                                   # the Creator
FAN = 354841559
NOW = datetime(2026, 10, 30, 12, 0, 0)
T = datetime(2026, 10, 30, 11, 0, 0)         # a frame's createdAt


# ── field parsers ────────────────────────────────────────────────────

@table("s, want", [
    ("2026-05-18T19:06:47+00:00", datetime(2026, 5, 18, 19, 6, 47)),
    ("2026-05-18T19:06:47Z", datetime(2026, 5, 18, 19, 6, 47)),
    ("2026-05-18T21:06:47+02:00", datetime(2026, 5, 18, 21, 6, 47)),   # tz dropped, not converted
    ("not a date", None),
    ("", None),
    (None, None),
])
def test_parse_iso(s, want):
    assert td.parse_iso(s) == want


@table("price, want", [
    (9.99, 999), ("9.99", 999), (10, 1000), (0.1 + 0.2, 30),
    (None, 0), ("", 0), ("abc", 0), (-5, -500),
])
def test_to_cents(price, want):
    assert td.to_cents(price) == want


@table("media, want", [
    ([{"id": 1}, {"id": "2"}, "x", {"id": 3}, {}], [1, 3]),
    ([], []),
    (None, []),
    ({"id": 1}, []),
])
def test_media_ids(media, want):
    assert td.media_ids(media) == want


@table("s, want", [
    ("<p>hey <strong>you</strong></p> ", "hey you"),
    ("plain", "plain"),
    ("", ""),
    (None, ""),
])
def test_strip_html(s, want):
    assert td.strip_html(s) == want


# ── route ────────────────────────────────────────────────────────────

P = {"id": 1}


@table("event, want", [
    ({"api2_chat_message": P, "__account_id": A}, ("chat_message", "api2_chat_message", P)),
    ({"__account_id": A, "api2_chat_message": P}, ("chat_message", "api2_chat_message", P)),  # sentinel first
    ({"api2_chat_message": "x"}, ("other", "api2_chat_message", "x")),          # non-dict: touch lane
    ({"paidMessage": P}, ("ppv", "paidMessage", P)),
    ({"messageUnlock": P}, ("ppv", "messageUnlock", P)),
    ({"purchase": P}, ("ppv", "purchase", P)),
    ({"purchase": [1]}, ("other", "purchase", [1])),
    ({"toasts": [P]}, ("toast", "toasts", [P])),
    ({"chat_queue_finish": P}, ("queue", "chat_queue_finish", P)),
    ({"chat_queue_update": P}, ("queue", "chat_queue_update", P)),
    ({"typing": P}, ("other", "typing", P)),
    ({"__account_id": A}, None),
    ({}, None),
    ("not a dict", None),
    (None, None),
])
def test_route(event, want):
    assert td.route(event) == want


# ── blast ring ───────────────────────────────────────────────────────

Q = 46605849959


def fin(qid=Q, total=23, **kw):
    return {"id": qid, "total": total, "isDone": True, **kw}


@table("ring, event_type, payload, want", [
    ((), "chat_queue_finish", fin(), ((Q, 100.0),)),
    ((), "chat_queue_update", fin(), ()),                                        # update ignored
    ((), "chat_queue_finish", fin(total=-1), ()),                                # first-update total
    ((), "chat_queue_finish", fin(total=4), ()),                                 # a hand-send
    ((), "chat_queue_finish", fin(total=5), ((Q, 100.0),)),                      # the floor
    ((), "chat_queue_finish", fin(total="x"), ()),
    ((), "chat_queue_finish", fin(qid="nope"), ()),
    ((), "chat_queue_finish", {"total": 23}, ()),                                # no id
    ((), "chat_queue_finish", "not a dict", ()),
    (((Q, 1.0), (7, 2.0)), "chat_queue_finish", fin(isCanceled=True), ((7, 2.0),)),   # cancel removes
    (((Q, 1.0), (7, 2.0)), "chat_queue_update", {"id": Q, "isCanceled": True}, ((7, 2.0),)),
    (((7, 2.0),), "chat_queue_finish", fin(isCanceled=True), ((7, 2.0),)),       # cancel of an unknown id
    (((Q, 1.0), (7, 2.0)), "chat_queue_finish", fin(), ((7, 2.0), (Q, 100.0))),  # re-sent: replace by id
])
def test_queue_fold(ring, event_type, payload, want):
    before = copy.deepcopy(ring)
    assert td.queue_fold(ring, event_type, payload, 100.0) == want
    assert ring == before                                                        # never mutates


def test_queue_ring_keeps_newest_32():
    ring: td.Ring = ()
    for i in range(td.QUEUE_RING_MAX + 1):
        ring = td.queue_fold(ring, "chat_queue_finish", fin(qid=i), float(i))
    assert len(ring) == td.QUEUE_RING_MAX == 32
    assert ring[0] == (1, 1.0) and ring[-1] == (32, 32.0)                        # oldest (0) dropped
    # a re-sent finish of a queue in a full ring keeps 32, the queue moves to newest
    ring = td.queue_fold(ring, "chat_queue_finish", fin(qid=5), 99.0)
    assert len(ring) == 32 and ring[-1] == (5, 99.0) and ring[0] == (1, 1.0)


@table("ring, now, seconds, want", [
    ((), 100.0, 3600, False),
    (((Q, 50.0),), 100.0, 3600, True),
    (((Q, 50.0),), 100.0, 50, True),                                             # at the floor
    (((Q, 50.0),), 100.0, 49.9, False),
    (((1, 0.0), (Q, 90.0)), 100.0, 10, True),                                    # any entry
])
def test_blasted(ring, now, seconds, want):
    assert td.blasted(ring, now, seconds) is want


# ── user_blob ────────────────────────────────────────────────────────

U = {"id": FAN, "name": "Bob"}


@table("payload, want", [
    ({"fromUser": U}, (FAN, {"of_display_name": "Bob"})),
    ({"user": U}, (FAN, {"of_display_name": "Bob"})),
    ({"data": {"relatedUser": U}}, (FAN, {"of_display_name": "Bob"})),
    ({"data": {"user": U}}, (FAN, {"of_display_name": "Bob"})),
    ({"fromUser": U, "user": {"id": 2, "name": "x"}}, (FAN, {"of_display_name": "Bob"})),   # fromUser first
    ({"data": {"relatedUser": U, "user": {"id": 2, "name": "x"}}}, (FAN, {"of_display_name": "Bob"})),
    ({"fromUser": {"id": FAN, "avatar": "a", "avatarThumbs": {"c144": "b"}}}, (FAN, {"avatar_url": "a"})),
    ({"user": {"id": FAN, "avatarThumbs": {"c50": "s", "c144": "m"}}}, (FAN, {"avatar_url": "m"})),
    ({"user": {"id": FAN, "avatarThumbs": {"c50": "s", "x": "y"}}}, (FAN, {"avatar_url": "s"})),
    ({"user": {"id": FAN, "avatarThumbs": {"x": 1, "y": "any"}}}, (FAN, {"avatar_url": "any"})),
    ({"user": {"id": FAN, "username": "bob", "name": "Bob", "avatar": "a"}},
     (FAN, {"avatar_url": "a", "of_display_name": "Bob", "of_username": "bob"})),
    ({"user": {"id": "354841559", "name": "Bob"}}, None),                        # non-int id
    ({"user": {"name": "Bob"}}, None),
    ({"user": {"id": FAN}}, None),                                               # no field
    ({"user": {"id": FAN, "name": "", "avatarThumbs": {"x": 1}}}, None),
    ({"user": {}}, None),
    ({"data": {"other": U}}, None),
    ({"typing": True}, None),
    ([U], None),
    (None, None),
])
def test_user_blob(payload, want):
    assert td.user_blob(payload) == want


# ── dm_plan ──────────────────────────────────────────────────────────

def msg(**kw) -> dict:
    m = {"id": 10001, "text": "<p>hi</p>", "fromUser": {"id": FAN},
         "createdAt": "2026-10-30T11:00:00+00:00", "media": [], "mediaCount": 0}
    m.update(kw)
    return m


@table("aid, m, want", [
    (A, msg(id=None), Skip(None, FAN)),
    (A, msg(id=0), Skip(0, FAN)),
    (A, msg(fromUser=None), Skip(10001, None)),
    (A, msg(fromUser={"name": "no id"}), Skip(10001, None)),
    (None, msg(), Skip(10001, FAN)),
    ("", msg(), Skip(10001, FAN)),
])
def test_dm_plan_skips_without_a_key(aid, m, want):
    assert td.dm_plan(aid, m, NOW) == want


@table("aid, fan", [(A, int(A)), (A, A), (int(A), A)])
def test_dm_plan_outbound_echo_writes_no_row(aid, fan):
    assert td.dm_plan(aid, msg(fromUser={"id": fan}), NOW) == Outbound(10001)


def plan(**kw) -> Inbound:
    p = td.dm_plan(A, msg(**kw), NOW)
    assert isinstance(p, Inbound), p
    return p


@table("kw, tip_cents, image", [
    (dict(isTip=True, price=0, tipAmount=10), 1000, False),                      # tipAmount, not price
    (dict(isTip=True, price=0, tipAmount="2.50"), 250, False),
    (dict(isTip=True, price=5.0), 500, False),                                   # fallback to price
    (dict(isTip=True, price=5.0, tipAmount=0), 500, False),
    (dict(isTip=True, price=5.0, tipAmount=-3), 0, False),                       # negative: no tip, no fallback
    (dict(isTip=True, price=0, tipAmount=0), 0, False),                          # $0: no tip hook
    (dict(isTip=False, price=9.99, tipAmount=10), 0, False),                     # not a tip: tipAmount unread
    (dict(isTip=True, price=0, tipAmount=10, media=[{"id": 7}]), 1000, False),   # tip w/ media: words
    (dict(isTip=True, price=0, tipAmount=0, media=[{"id": 7}]), 0, False),       # degenerate: words only
    (dict(media=[{"id": 7}]), 0, True),
    (dict(media=[], giphyId="Q9WDZTdraX9E4"), 0, True),
    (dict(text="hey you up"), 0, False),
])
def test_dm_plan_tip_and_image(kw, tip_cents, image):
    p = plan(**kw)
    assert (p.tip_cents, p.image) == (tip_cents, image)


@table("kw, has_media", [
    (dict(media=[{"id": 7}, {"id": 8}]), True),
    (dict(giphyId="Q9WDZTdraX9E4"), False),                                      # a gif: no media
    (dict(text="x"), False),
])
def test_dm_plan_has_media(kw, has_media):
    assert plan(**kw).has_media is has_media


@table("kw, price_cents, paid, purchased_at", [
    (dict(price=0, isOpened=True), 0, None, None),                               # free: NULL, not False
    (dict(price=None, isOpened=False), 0, None, None),
    (dict(price=9.99, isOpened=False), 999, False, None),
    (dict(price=9.99, isOpened=True, openedAt="2026-10-30T11:30:00Z"), 999, True,
     datetime(2026, 10, 30, 11, 30)),
    (dict(price=9.99, isOpened=None), 999, None, None),
])
def test_dm_plan_is_paid(kw, price_cents, paid, purchased_at):
    r = plan(**kw).msg
    assert (r["price_cents"], r["is_paid"], r["purchased_at"]) == (price_cents, paid, purchased_at)


def test_dm_plan_row():
    fu = {"id": FAN, "name": "N" * 300, "username": "bob"}
    p = plan(id="10002", fromUser=fu, media=[{"id": 7}, {"id": "x"}], mediaCount="2", text=None)
    assert p == Inbound(dict(
        account_id=A, fan_id=FAN, message_id=10002, direction="in",
        sender_name="N" * 255, body="", media_ids=json.dumps([7]), media_count=2,
        price_cents=0, is_paid=None, is_tip=False, purchased_at=None, is_unsent=False,
        created_at=T,
    ), from_user=fu, tip_cents=0, image=True, has_media=True)
    assert plan(fromUser={"id": FAN, "username": "bob"}).msg["sender_name"] == "bob"
    assert plan(createdAt=None).msg["created_at"] == NOW                         # stamped by the caller
    assert plan(createdAt="garbage").msg["created_at"] == NOW
    assert td.dm_plan(int(A), msg(), NOW).msg["account_id"] == A                 # str key for of_writer


# ── fan_upsert ───────────────────────────────────────────────────────

def item(created_at, **user) -> Inbound:
    return Inbound({"account_id": A, "fan_id": FAN, "created_at": created_at},
                   {"id": FAN, **user}, tip_cents=0, image=False, has_media=False)


T2 = datetime(2026, 10, 30, 11, 5)


BLANK = dict(of_username=None, of_display_name=None, avatar_url=None)


@table("items, values, on_conflict, flags", [
    # a plain DM: fromUser {id} only — insert blanks, conflict touches nothing but the time
    ([item(T)], dict(BLANK, source="unknown"), {"last_message_received_at": T}, (None, None)),
    # newest non-blank wins; a later blank / None never clobbers an earlier value
    ([item(T, username="old", name="Bob", avatar="a1"), item(T2, username="new", name="", avatar=None)],
     dict(of_username="new", of_display_name="Bob", avatar_url="a1", source="unknown"),
     {"last_message_received_at": T2, "of_username": "new", "of_display_name": "Bob", "avatar_url": "a1"},
     (None, None)),
    ([item(T, subscribedOn=True)], dict(BLANK, source="fan"), {"last_message_received_at": T},
     (True, None)),
    ([item(T, subscribedBy=True)], dict(BLANK, source="creator_we_follow"),
     {"last_message_received_at": T}, (None, True)),
    ([item(T, subscribedOn=True, subscribedBy=True)], dict(BLANK, source="fan"),
     {"last_message_received_at": T}, (True, True)),
    ([item(T, subscribedOn=False)], dict(BLANK, source="unknown"),               # False is a value, not blank
     {"last_message_received_at": T}, (False, None)),
])
def test_fan_upsert(items, values, on_conflict, flags):
    before = copy.deepcopy(items)
    v, oc, fl = td.fan_upsert(items)
    assert v == {"account_id": A, "fan_id": FAN, "last_message_received_at": items[-1].msg["created_at"],
                 **values}
    assert (oc, fl) == (on_conflict, flags)
    assert items == before


# ── ppv_fields ───────────────────────────────────────────────────────

def ppv(fan_id=FAN, message_id=555, amount_cents=999, occurred_at=T) -> dict:
    return dict(fan_id=fan_id, message_id=message_id, kind="ppv",
                amount_cents=amount_cents, occurred_at=occurred_at)


ISO = "2026-10-30T11:00:00+00:00"


@table("payload, want", [
    ({"message": {"id": 555, "fromUser": {"id": FAN}, "price": 9.99}, "openedAt": ISO}, ppv()),
    ({"id": 555, "fromUser": {"id": FAN}, "price": 9.99, "createdAt": ISO}, ppv()),            # flat
    ({"messageId": 555, "user": {"id": FAN}, "amount": "9.99", "createdAt": ISO}, ppv()),
    ({"message_id": "555", "fan": {"id": str(FAN)}, "price": 9.99, "createdAt": ISO}, ppv()),  # str ids
    ({"message": {"id": 555, "fromUser": {"id": FAN}, "openedAt": ISO}, "price": 9.99}, ppv()),
    ({"message": {"id": 1, "fromUser": {"id": FAN}, "price": 5}, "messageId": 555, "price": 9.99,
      "openedAt": ISO}, ppv(message_id=1, amount_cents=500)),                    # message first
    ({"id": 555, "fromUser": {"id": FAN}, "price": 9.99}, ppv(occurred_at=NOW)),  # no time: now
    ({"id": 555, "fromUser": {"id": FAN}, "price": 0}, None),                    # no amount
    ({"fromUser": {"id": FAN}, "price": 9.99}, None),                            # no message id
    ({"id": 555, "price": 9.99}, None),                                          # no fan
    ({"id": 555, "fan": 42, "price": 9.99}, None),                               # fan not a dict
])
def test_ppv_fields(payload, want):
    assert td.ppv_fields(payload, NOW) == want


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            for row in getattr(fn, "rows", [()]):
                fn(*(row if isinstance(row, tuple) else (row,)))
                n += 1
    print(f"all {n} cases passed")
