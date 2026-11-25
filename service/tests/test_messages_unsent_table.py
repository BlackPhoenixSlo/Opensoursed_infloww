from __future__ import annotations

import _harness

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import messages  # noqa: E402 — the re-exporting module callers use
from db.engine import get_session  # noqa: E402
from db.models import Account, MassRun, Message  # noqa: E402
from messages_unsent import unsent_targets  # noqa: E402

QID = 555
RUN = 7
SENT = datetime(2026, 10, 1, 12, 0, 0)
BOUGHT = SENT + timedelta(minutes=5)
FRAME = json.dumps({"queueId": QID, "isFromQueue": True})


def R(fan_id, message_id, body=None, created_at=None, raw_json=None):
    return (fan_id, message_id, body, created_at, raw_json)


def _check(table, *, body=None, sent_at=None):
    for name, row, want in table:
        got = unsent_targets(QID, [row], body=body, sent_at=sent_at)
        assert (got == [(row[0], row[1])]) is want, (name, got, want)


def case_queue_id_via_raw_json():
    _check([
        ("queueId int", R(1, 1, raw_json=FRAME), True),
        ("queueId numeric string", R(1, 2, raw_json=json.dumps({"queueId": str(QID)})), True),
        ("queueId, hours late", R(1, 3, raw_json=FRAME, created_at=SENT + timedelta(hours=3)), True),
        ("queueId, no stamp known", R(1, 4, raw_json=FRAME), True),
        ("other queue", R(1, 5, raw_json=json.dumps({"queueId": QID + 1})), False),
        ("malformed frame", R(1, 6, raw_json='{"queueId": 555'), False),
        ("word only", R(1, 7, raw_json=json.dumps({"text": "queueId 555"})), False),
        ("bool queueId", R(1, 8, raw_json=json.dumps({"queueId": True})), False),
    ])


def case_copy_with_other_body():
    at = SENT + timedelta(minutes=10)
    _check([
        ("same body in window", R(1, 1, body="hi babe", created_at=at), True),
        ("OF's <br /> echo", R(1, 2, body="hi<br />babe", created_at=at), True),
        ("same body, edge of window", R(1, 8, body="hi babe",
                                        created_at=SENT + timedelta(minutes=30)), True),
        ("other body in window", R(1, 3, body="something else", created_at=at), False),
        ("same body 3h later", R(1, 4, body="hi babe", created_at=SENT + timedelta(hours=3)), False),
        ("same body, no created_at", R(1, 5, body="hi babe"), False),
        ("same body in window, another queue's copy",
         R(1, 9, body="hi babe", created_at=at, raw_json=json.dumps({"queueId": QID + 1})), False),
        ("same body in window, malformed frame",
         R(1, 10, body="hi babe", created_at=at, raw_json='{"queueId": 555'), True),
    ], body="hi babe", sent_at=SENT)
    _check([("body match, no sent_at", R(1, 6, body="hi babe", created_at=SENT), False)],
           body="hi babe", sent_at=None)
    _check([("media-only blast", R(1, 7, body="", created_at=SENT), False)],
           body="<photo>", sent_at=SENT)



AID = "acct_unsent_table"
PRIOR = "test:prior"
CALLS = {
    "runs": lambda: messages.mark_mass_runs_unsent(AID, [RUN], reason="runs"),
    "copies": lambda: messages.mark_queue_copies_unsent(
        AID, QID, body="hi babe", sent_at=SENT, reason="copies"),
    "single_fan": lambda: messages.mark_unsent(AID, 900, fan_id=20, reason="single_fan"),
    "single_any": lambda: messages.mark_unsent(AID, 902, reason="single_any"),
    "single_again": lambda: messages.mark_unsent(AID, 903, fan_id=24, reason="single_again"),
}
TABLE = [
    ("run row", 1, 101, dict(mass_run_id=RUN, body="hi babe"), "runs"),
    ("other run's row", 2, 102, dict(mass_run_id=RUN + 1, body="hi babe"), None),
    ("other run's row with our queueId", 3, 103,
     dict(mass_run_id=RUN + 1, raw_json=FRAME), None),
    ("copy via queueId, hours late", 4, 104, dict(raw_json=FRAME, body="pic", minutes=200), "copies"),
    ("copy via body", 5, 105, dict(body="hi babe", minutes=10), "copies"),
    ("copy via <br /> echo", 6, 106, dict(body="hi<br />babe", minutes=-20), "copies"),
    ("other queue", 7, 107, dict(raw_json=json.dumps({"queueId": QID + 1}), body="x"), None),
    ("same body 3h later", 8, 108, dict(body="hi babe", minutes=180), None),
    ("other body", 9, 109, dict(body="other", minutes=1), None),
    ("inbound with queueId", 10, 110, dict(raw_json=FRAME, direction="in"), None),
    ("run row already unsent", 11, 111,
     dict(mass_run_id=RUN, body="hi babe", is_unsent=True, unsent_reason=PRIOR), None),
    ("copy already unsent", 12, 112,
     dict(raw_json=FRAME, is_unsent=True, unsent_reason=PRIOR), None),
    ("bought run row", 13, 113, dict(mass_run_id=RUN, body="hi babe", purchased_at=BOUGHT), None),
    ("funnel follow-up on the run", 14, 114,
     dict(mass_run_id=RUN, body="hi babe", funnel_step=1), None),
    ("bought queueId copy", 15, 115, dict(raw_json=FRAME, purchased_at=BOUGHT), None),
    ("bought body copy", 16, 116, dict(body="hi babe", purchased_at=BOUGHT), None),
    ("funnel follow-up copy", 17, 117, dict(raw_json=FRAME, funnel_step=2), None),
    ("single, that fan", 20, 900, dict(body="dm"), "single_fan"),
    ("single, same id other fan", 21, 900, dict(body="dm"), None),
    ("single, other id same fan", 20, 901, dict(body="dm"), None),
    ("single, no fan: fan a", 22, 902, dict(body="dm"), "single_any"),
    ("single, no fan: fan b", 23, 902, dict(body="dm"), "single_any"),
    ("single re-stamps an unsent row", 24, 903,
     dict(body="dm", is_unsent=True, unsent_reason=PRIOR), "single_again"),
]


async def case_shells_table():
    async with get_session() as s:
        s.add(Account(id=AID))
        s.add(MassRun(id=RUN, account_id=AID, queue_id=QID, body="hi babe", sent_at=SENT))
        s.add(MassRun(id=RUN + 1, account_id=AID, queue_id=QID + 1, body="x", sent_at=SENT))
    async with get_session() as s:
        for _name, fan, mid, kw, _want in TABLE:
            kw = dict(kw)
            at = SENT + timedelta(minutes=kw.pop("minutes", 0))
            s.add(Message(account_id=AID, fan_id=fan, message_id=mid,
                          direction=kw.pop("direction", "out"), created_at=at, **kw))

    returned = {}
    for reason, call in CALLS.items():
        returned[reason] = await call()

    async with get_session() as s:
        final = {(int(f), int(m)): r for f, m, r in (await s.execute(
            select(Message.fan_id, Message.message_id, Message.unsent_reason)
            .where(Message.account_id == AID)
        )).all()}
    bad = []
    for name, fan, mid, kw, want in TABLE:
        expect = want or kw.get("unsent_reason")
        if final[(fan, mid)] != expect:
            bad.append((name, final[(fan, mid)], expect))
    assert not bad, bad
    want_n = {r: sum(1 for *_x, w in TABLE if w == r) for r in CALLS}
    copies, stamped = returned.pop("copies")
    got_n = {**returned, "copies": copies}
    assert got_n == want_n, (got_n, want_n)
    assert stamped == 1, stamped


if __name__ == "__main__":
    _harness.run()
