#!/usr/bin/env python3
"""
"Auto-accept OnlyFans consent" on the WIRE BODY (of_consent + of_sends).

OF answers a media send from a consent-flagged Creator without consent
`400 Consent not accepted`; OF's web client adds `isConsentAccepted: true` (top
level, beside `mediaFiles`) only after its "Yes?" and only when the send has media.
The account switch (`of_consent_accepts`, newest row wins) is that "Yes" given once.

  case_on_media_adds_the_field_on_every_media_send: switch on + media → the field
      is `True` on the DM, mass, scheduled mass, scheduled DM, queued-mass edit,
      post, post edits and story bodies.
  case_off_never_adds_it: no row, or the newest row off → no field anywhere.
  case_on_text_only_never_adds_it: switch on, no media (a text DM / mass / post,
      a GIF) → no field.
  case_other_account_and_no_account_stay_off: one account's switch never reaches
      another's sends, nor a client without an account id.
  case_a_failed_read_is_off: the lookup raising → no field.

Run: ./venv/bin/python service/tests/test_of_consent.py
"""
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

import asyncio  # noqa: E402
from datetime import datetime  # noqa: E402

import of_client  # noqa: E402
import of_consent  # noqa: E402
from db.engine import get_session  # noqa: E402

ON, OFF_AGAIN, NEVER = "771001", "771002", "771003"


async def _seed() -> None:
    async with get_session() as s:
        await of_consent.record(s, ON, True, user_id="u1", username="owner1", employee_id=None,
                                at=datetime(2026, 11, 8, 10))
        await of_consent.record(s, OFF_AGAIN, True, user_id="u1", username="owner1",
                                employee_id=None, at=datetime(2026, 11, 8, 10))
        await of_consent.record(s, OFF_AGAIN, False, user_id="u1", username="owner1",
                                employee_id=None, at=datetime(2026, 11, 8, 11))

asyncio.run(_seed())


def _client(account_id: str | None):
    """An OFClient that skips __init__ and captures each body instead of the network."""
    c = of_client.OFClient.__new__(of_client.OFClient)
    if account_id is not None:
        c.account_id = account_id
    c.captured = []
    grab = lambda path, json_body=None: c.captured.append((path, json_body)) or {"id": 1}  # noqa: E731
    c.post_json = grab
    c.put_json = grab
    return c


def _media_sends(c) -> list[tuple[str, dict]]:
    """Every of_sends media send once; answers [(kind, body)]."""
    m = [111, 222]
    claim = [{"processId": "p1", "host": "h", "name": "n", "extra": "e"}]
    c.send_message(5, "hi", media_files=m, price=10, auto_tag=False)
    c.send_mass_message("hi", user_lists=["fans"], media_files=m, price=10, auto_tag=False)
    c.schedule_mass_message(text="hi", scheduled_date="2026-12-01T10:00:00+00:00",
                            user_lists=["fans"], media_files=m, auto_tag=False)
    c.schedule_message(5, "hi", scheduled_date="2026-12-01T10:00:00+00:00", media_files=m,
                       auto_tag=False)
    c.edit_queued_message(9, text="hi", scheduled_date="2026-12-01T10:00:00+00:00",
                          user_lists=["fans"], media_files=m)
    c.create_post("hi", media_files=m, auto_tag=False)
    c.edit_post(9, media_files=m)
    c.save_queued_post(9, "hi", media_files=m)
    c.create_story(claim)
    kinds = ["dm", "mass", "scheduled mass", "scheduled dm", "queued edit", "post", "post edit",
             "queued post", "story"]
    assert len(c.captured) == len(kinds), c.captured
    return list(zip(kinds, (b for _p, b in c.captured)))


def _text_sends(c) -> list[tuple[str, dict]]:
    c.send_message(5, "hi", auto_tag=False)
    c.send_message(5, "", giphy_id="g1", auto_tag=False)
    c.send_mass_message("hi", user_lists=["fans"], auto_tag=False)
    c.create_post("hi", auto_tag=False)
    c.edit_post(9, text="hi")
    return list(zip(["dm", "gif dm", "mass", "post", "post edit"], (b for _p, b in c.captured)))


def case_on_media_adds_the_field_on_every_media_send():
    for kind, body in _media_sends(_client(ON)):
        assert body.get("isConsentAccepted") is True, (kind, body)
        assert body["mediaFiles"], (kind, body)


def case_off_never_adds_it():
    for aid in (OFF_AGAIN, NEVER):
        for kind, body in _media_sends(_client(aid)):
            assert "isConsentAccepted" not in body, (aid, kind, body)


def case_on_text_only_never_adds_it():
    for kind, body in _text_sends(_client(ON)):
        assert "isConsentAccepted" not in body, (kind, body)


def case_other_account_and_no_account_stay_off():
    for c in (_client("771999"), _client(None)):
        for kind, body in _media_sends(c):
            assert "isConsentAccepted" not in body, (kind, body)


def case_a_failed_read_is_off():
    import media_cotag
    real = media_cotag._sync_engine

    def boom():
        raise RuntimeError("db gone")
    media_cotag._sync_engine = boom
    try:
        for kind, body in _media_sends(_client(ON)):
            assert "isConsentAccepted" not in body, (kind, body)
    finally:
        media_cotag._sync_engine = real
    assert of_consent.auto_accept(ON) is True


if __name__ == "__main__":
    _harness.run()
