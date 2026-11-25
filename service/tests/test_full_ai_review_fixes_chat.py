#!/usr/bin/env python3
from __future__ import annotations

import _harness

from _full_ai_sell_helpers import (  # noqa: E402
    NANO, OPENROUTER, OWNER_A, PICS, PRICED, TURN, _body, _guarded, _hot, _no_offer, _post, _ppvs,
    _put_draft, _reply, _rows, _sell_draft, _vault,
)
import asyncio  # noqa: E402
import contextlib  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402

from _full_ai_fixtures import GIF_FITS, QUIET, FakeJev, FakeWriterHTTP, _fake_jev  # noqa: E402
import vault_dupes  # noqa: E402
from automations import _router_jev as router  # noqa: E402
from automations import cat_stickers, full_ai_sell, full_ai_turn, full_ai_writers  # noqa: E402
from automations.full_ai_config import DEFAULTS, turn_bound_s  # noqa: E402

EURYALE, HERMES = DEFAULTS["writers"][:2]
_GIF_TAG = "laugh"


@contextlib.contextmanager
def _draft(**cfg):
    _put_draft({**DEFAULTS, **cfg})
    try:
        yield
    finally:
        _put_draft(dict(DEFAULTS))


def _texts(parts: list[dict]) -> list[str]:
    return [p["text"] for p in parts if "text" in p]


def _user(fw: FakeWriterHTTP, i: int = 0) -> str:
    return fw.requests[i]["body"]["messages"][1]["content"]



def case_ppv_never_rides_the_typo_fix():
    pair, line = "p-typo-turns", "literally sounds gorgeous"
    with _sell_draft(), _vault(PRICED):
        chat, _, no_pick = _post(_body(pair, side="checkpoint"), f"ok:{line}")
        sell, _, (pick,) = _post(_body(pair, side="draft"), f"ok:{line}")
    c, s = chat.json(), sell.json()
    assert no_pick == [] and c["route"] == "chat" and c["offer"] is None, c
    assert _texts(c["parts"])[-1] == "*literally lol", ("the seed fires the fix without a Pick", c["parts"])
    assert (s["status"], s["route"]) == ("sent", "sell_now") and isinstance(pick, full_ai_sell.Pick), s
    assert _texts(s["parts"]) == _texts(c["parts"])[:-1], (s["parts"], c["parts"])
    assert _ppvs(s["parts"]) == [len(s["parts"]) - 1] and s["parts"][-1]["ppv"]["ref"] == pick.ref, s["parts"]
    assert _reply(_rows(pair)[1])["caption_fallback"] is False



def case_sticker_only_sell_tries_next():
    pair = "p-sticker-sell"
    with _draft(sell_on=True, gifs=True), _vault(PRICED):
        r, fw, (pick,) = _post(_body(pair), {NANO: f"ok:STICKER: {_GIF_TAG}",
                                             OPENROUTER: "ok:mm ok i have something cute for u"})
    got = r.json()
    assert [(a["writer"], a["outcome"]) for a in got["attempts"]] == [
        (EURYALE, "floor:no_letters"), (HERMES, "ok")], got["attempts"]
    assert len(fw.requests) == 2 and got["writer"] == HERMES, got
    assert isinstance(pick, full_ai_sell.Pick) and got["offer"]["ref"] == pick.ref, got
    assert _ppvs(got["parts"]) == [len(_texts(got["parts"])) - 1], got["parts"]
    assert "offer_dropped" not in _reply(_rows(pair)[0]), _reply(_rows(pair)[0])



def case_gif_only_reply_seen_next_turn():
    pair = "p-gif-only"
    with _draft(gifs=True):
        r1, _, _ = _post(_body(pair, "hi cutie"), f"ok:STICKER: {_GIF_TAG}", jev=(GIF_FITS, 1.0))
        g1 = r1.json()
        assert g1["status"] == "sent" and [set(p) for p in g1["parts"]] == [{"gif", "tag"}], g1
        fj = FakeJev((QUIET, 1.0))
        fw = FakeWriterHTTP({NANO: "ok:heyy what are u up to"})
        with _guarded(), fw.on(), _fake_jev(fj):
            r2 = OWNER_A.post(TURN, json=_body(pair, "how are you", n=2))
    assert r2.status_code == 200, r2.text
    st = fj.calls[0]["state"]
    assert st["fan_new_messages"] == ["how are you"], st
    assert [(x["from"], x["text"]) for x in st["thread"]][-2:] == [
        ("fan", "hi cutie"), ("her", router.GIF_ONLY)], st["thread"]
    assert f"YOU: {router.GIF_ONLY}" in _user(fw), _user(fw)



class _Clock:
    def __init__(self):
        self.t = 1000.0

    def now(self) -> float:
        return self.t


class _SlowJev(FakeJev):

    def __init__(self, clock: _Clock, took_s: float, *verdicts):
        super().__init__(*verdicts)
        self.clock, self.took_s = clock, took_s

    async def system_one(self, state, questions, model=None):
        self.clock.t += self.took_s
        return await super().system_one(state, questions, model)


def case_sell_step_inside_the_deadline():
    bound = turn_bound_s(DEFAULTS)
    assert bound == 245, bound
    clock, real = _Clock(), vault_dupes.find_duplicates

    async def slow(*a, **k):
        await asyncio.sleep(3.0)
        return await real(*a, **k)
    saved = (full_ai_turn.time, full_ai_writers.time)
    full_ai_turn.time = full_ai_writers.time = types.SimpleNamespace(monotonic=clock.now,
                                                                     perf_counter=time.perf_counter)
    vault_dupes.find_duplicates = slow
    fw = FakeWriterHTTP({NANO: "ok:not right now babe, wbu"})
    try:
        with _sell_draft(), _vault(PRICED), _guarded(), fw.on(), \
                _fake_jev(_SlowJev(clock, bound - 0.3, (_hot(wants_content=0.9), 1.0))):
            t0 = time.perf_counter()
            r = OWNER_A.post(TURN, json=_body("p-sell-deadline", PICS))
            wall = time.perf_counter() - t0
    finally:
        full_ai_turn.time, full_ai_writers.time = saved
        vault_dupes.find_duplicates = real
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["route"] == "sell_now" and got["offer"] is None and _ppvs(got["parts"]) == [], got
    (row,) = _rows("p-sell-deadline")
    assert _reply(row)["refusal"] == "inventory_unknown", _reply(row)
    _no_offer(row)
    assert wall < 2.0, ("the sell step waited past the Turn's time left", wall)


if __name__ == "__main__":
    assert cat_stickers._CATALOG[_GIF_TAG][1], "the GIF tag has gifs"
    _harness.run()
