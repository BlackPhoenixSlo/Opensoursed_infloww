#!/usr/bin/env python3
from __future__ import annotations

import _harness

from _full_ai_chat_helpers import (
    _CHAIN_KEYS, _GIF_TAG, A, DEEPSEEK, NANO, OK_LINE, OPENROUTER, OWNER_A, TURN, ZAI, _agency_keys,
    _body, _guarded, _reply, _rows, _store_config,
)
from types import SimpleNamespace

from _full_ai_fixtures import GIF_FITS, QUIET, FakeInfoJev, FakeJev, FakeWriterHTTP, _fake_jev, _shape_drop
from automations import _heat_jev, cat_stickers
from automations import _info_jev as ij
from automations import full_ai_writers as wr
from automations.full_ai_config import DEFAULTS
from _full_ai_live_fixtures import LINE3, LiveOF  # noqa: E402 — after the chat helpers' bootstrap
from _full_ai_live_helpers import dm_turn, fan_row, live_rows, reply, seed_live  # noqa: E402

OFFERED = frozenset({"home_city"})
LINE = OK_LINE.removeprefix("ok:")
CITY = wr.LEAD_HEAD + "[home_city] " + wr.LEAD_LINES["location"]


def case_asked_marker_table():
    m = ij.asked_marker
    both = frozenset({"home_city", "hobbies", "name"})
    for text, offered, want in (
        ("what city r u in?\nASKED: home_city", OFFERED, ("what city r u in?", "home_city", "home_city")),
        ("what city r u in?\nasked: Home_City", OFFERED, ("what city r u in?", "home_city", "Home_City")),
        ("what city r u in?\n  *ASKED: [home_city]*", OFFERED, ("what city r u in?", "home_city", "home_city")),
        ("what city r u in? ASKED: home_city", OFFERED, ("what city r u in?", "home_city", "home_city")),
        ("lol same\nASKED: none", OFFERED, ("lol same", None, "none")),
        ("which part?\nASKED: city", OFFERED, ("which part?", None, "city")),
        ("which part?\nASKED: home_city", frozenset(), ("which part?", None, "home_city")),
        ("what do u do for fun? asked: hobbies", both, ("what do u do for fun?", "hobbies", "hobbies")),
        ("where u from Asked: home_city", both, ("where u from", "home_city", "home_city")),
        ("where u from?\n*asked: home_city*", both, ("where u from?", "home_city", "home_city")),
        ("where u from?\n**Asked: home_city**", both, ("where u from?", "home_city", "home_city")),
        ("where u from?\n**ASKED:** home_city", both, ("where u from?", "home_city", "home_city")),
        ("where u from?\nASKED - home_city", both, ("where u from?", "home_city", "home_city")),
        ("where u from?\nASKED = hobbies", both, ("where u from?", "hobbies", "hobbies")),
        ("where u from?\nASKED home_city", both, ("where u from?", "home_city", "home_city")),
        ("where u from?\nasked: city", both, ("where u from?", None, "city")),
        ("[hobbies] what do u do for fun?", both, ("what do u do for fun?", None, None)),
        ("what do u do for fun? [Hobbies]\nASKED: hobbies", both, ("what do u do for fun?", "hobbies", "hobbies")),
        ("[city] which part?", both, ("[city] which part?", None, None)),
        ("hey\nASKED: none\nwhat do u do?\nASKED: home_city", OFFERED,
         ("hey\n\nwhat do u do?", "home_city", "home_city")),
        ("hey u\n\nASKED: home_city\n\nASKED: none", OFFERED, ("hey u", None, "none")),
        ("what city r u in?", OFFERED, ("what city r u in?", None, None)),
        ("since u asked: im in leeds", OFFERED, ("since u asked: im in leeds", None, None)),
        ("since u asked: im 24", both, ("since u asked: im 24", None, None)),
        ("omg u ASKED: and i answered", both, ("omg u", None, "and")),
        ("u asked name already lol", both, ("u asked name already lol", None, None)),
        ("i asked hobbies not that", both, ("i asked hobbies not that", None, None)),
        ("he asked: name and age", both, ("he asked: name and age", None, None)),
        ("unasked: hobbies", both, ("unasked: hobbies", None, None)),
        ("lol u asked name", both, ("lol u asked name", None, None)),
        ("lol u asked age?", both | {"age"}, ("lol u asked age?", None, None)),
        ("lol u asked: name?", both, ("lol u", "name", "name")),
        ("where u from?\nASKED: location, hobbies", frozenset({"location", "hobbies"}),
         ("where u from?", "location", "location")),
        ("what do u do?\nASKED: hobbies (he mentioned golf)", both, ("what do u do?", "hobbies", "hobbies")),
        ("lol same\nASKED: none - just vibing", both, ("lol same", None, "none")),
        ("which part?\nASKED: home city", OFFERED, ("which part?", None, "home")),
        ("which part?\nASKED: home-city", OFFERED, ("which part?", None, "home")),
        ("where u from?\nASKED: [hobbies, location]", both, ("where u from?", "hobbies", "hobbies")),
        ("where u from?\nasked: hobbies cause he golfs", both, ("where u from?", "hobbies", "hobbies")),
        ("hey\nASKED:", OFFERED, ("hey", None, "")),
        ("what do u do? ASKED: hobbies STICKER: shy", both, ("what do u do? STICKER: shy", "hobbies", "hobbies")),
        ("what do u do? *ASKED: none* *sticker: shy*", both, ("what do u do? *sticker: shy*", None, "none")),
        ("hey  \n  what do u do?\nASKED: none", both, ("hey  \n  what do u do?", None, "none")),
        ("", OFFERED, ("", None, None)),
    ):
        got = m(text, offered)
        assert tuple(got) == want, (text, got)
        assert (got.text, got.key, got.raw) == want
    for text in ("what do u do? ASKED: hobbies STICKER: shy", "what do u do? *ASKED: none* *sticker: shy*"):
        assert cat_stickers.parse_marker(m(text, both).text) == ("what do u do?", "shy"), text


def _turn(pair, text, *, nano, rest=f"ok:{LINE}", info=None, fake_j=None, heat=None):
    fw = FakeWriterHTTP({OPENROUTER: rest, ZAI: rest, DEEPSEEK: rest, NANO: nano})
    with _agency_keys(_CHAIN_KEYS), _guarded(), fw.on(), \
            _fake_jev(fake_j or FakeJev((QUIET, 1.0)), info or FakeInfoJev()):
        if heat is not None:
            _heat_jev._client = lambda key: heat
        r = OWNER_A.post(TURN, json=_body(pair, 1, text))
    assert r.status_code == 200, r.text
    return r.json(), _reply(_rows(A, pair)[-1]), [
        x["body"]["messages"][0]["content"] for x in fw.requests if x["host"] in (NANO, OPENROUTER)]


def _texts(parts) -> str:
    return "\n".join(p.get("text") or "" for p in parts)


def _home_city(pair, nano):
    return _turn(pair, "hey you, how was your day", info=FakeInfoJev(({}, "home_city")), nano=nano)


def case_pick_counts_named_fact():
    got, rep, (sys_,) = _home_city("p-ask-city", f"ok:{LINE}\nASKED: home_city")
    assert got["status"] == "sent", got
    assert CITY in sys_ and sys_.endswith(wr.ASKED_EXCEPTION), sys_
    assert rep["asked"] == {"home_city": 1} and rep["asked_marker"] == "home_city", rep
    assert "ASKED" not in _texts(got["parts"]) and "ASKED" not in _texts(rep["parts"]), got["parts"]
    assert _texts(got["parts"]).replace("\n", " ").startswith("haha stop it"), got["parts"]
    for pair, answer, raw in (("p-ask-none", f"ok:{LINE}\nASKED: none", "none"),
                              ("p-ask-key", f"ok:{LINE}\nASKED: city", "city"),
                              ("p-ask-missing", f"ok:{LINE}", None)):
        got, rep, _ = _home_city(pair, answer)
        assert got["status"] == "sent" and rep["asked"] == {} and rep["asked_marker"] == raw, (pair, rep)
        assert "ASKED" not in _texts(got["parts"]), (pair, got["parts"])


def case_list_counts_named_key():
    _store_config(A, {"checkpoint": {**DEFAULTS, "info_questions": "list",
                                     "info_fields": ["home_city", "hobbies"]}})
    try:
        got, rep, (sys_,) = _turn("p-ask-list", "hey you, how was your day",
                                  nano=f"ok:{LINE}\nASKED: hobbies")
    finally:
        _store_config(A, {})
    assert got["status"] == "sent", got
    lines = [f"[{k}] " + wr.LEAD_LINES[k] for k in ("location", "hobbies")]
    assert wr.LEAD_HEAD + "\n".join(lines) in sys_ and sys_.endswith(wr.ASKED_EXCEPTION), sys_
    assert rep["asked"] == {"hobbies": 1} and rep["asked_marker"] == "hobbies", rep
    assert "ASKED" not in _texts(got["parts"]), got["parts"]


def case_no_ask_no_contract_line():
    marked = f"ok:{LINE}\nASKED: home_city"
    got, rep, (sys_,) = _turn("p-ask-nopick", "hey you", info=FakeInfoJev(({}, "none")), nano=marked)
    assert "[home_city]" not in sys_ and wr.ASKED_EXCEPTION not in sys_, sys_
    assert rep["asked"] == {} and "asked_marker" not in rep and "ASKED" not in _texts(got["parts"]), rep
    got, rep, (sys_,) = _turn("p-ask-sext", "fuck me", info=FakeInfoJev(({}, "home_city")), nano=marked,
                              fake_j=FakeJev(({**QUIET, "sexual_now": 0.95}, 3.0)))
    assert got["route"] == "sext" and wr.ASKED_EXCEPTION not in sys_, (got, sys_)
    assert rep["asked"] == {} and "asked_marker" not in rep and "ASKED" not in _texts(got["parts"]), rep


def case_lone_gif_or_dropped():
    _store_config(A, {"checkpoint": {**DEFAULTS, "gifs": True}})
    try:
        got, rep, _ = _turn("p-ask-gif", "hey you", info=FakeInfoJev(({}, "home_city")),
                            nano=f"ok:STICKER: {_GIF_TAG}\nASKED: home_city", fake_j=FakeJev((GIF_FITS, 1.0)))
    finally:
        _store_config(A, {})
    assert got["status"] == "sent" and [set(p) for p in got["parts"]] == [{"gif", "tag"}], got
    assert rep["asked"] == {} and rep["asked_marker"] == "home_city", rep
    _store_config(A, {"checkpoint": {**DEFAULTS, "gifs": True}})
    try:
        got, rep, _ = _turn("p-ask-gif-inline", "hey you", info=FakeInfoJev(({}, "home_city")),
                            nano=f"ok:{LINE} ASKED: home_city STICKER: {_GIF_TAG}", fake_j=FakeJev((GIF_FITS, 1.0)))
    finally:
        _store_config(A, {})
    assert got["status"] == "sent" and {"gif", "tag"} in [set(p) for p in got["parts"]], got
    assert "ASKED" not in _texts(got["parts"]) and "STICKER" not in _texts(got["parts"]), got["parts"]
    assert rep["asked"] == {"home_city": 1} and rep["asked_marker"] == "home_city", rep
    with _shape_drop("banned"):
        got, rep, _ = _home_city("p-ask-drop", f"ok:{LINE}\nASKED: home_city")
    assert got["status"] == "failed" and got["parts"] == [], got
    assert rep["asked"] == {} and rep["dropped_reason"] == "banned", rep


def case_dare_keeps_ids_with_goal():
    ask = wr.Need(CITY, ("home_city",))
    assert wr._dare_beat("chat", ask, None, False) == ask
    rated = wr._dare_beat("chat", ask, "seen", True)
    assert rated == wr.Need(CITY + "\n" + wr.DARE_RATE, ("home_city",)), rated
    assert wr._dare_beat("chat", ask, None, False, due=True) == wr.Need(wr.DARE_NEXT), ask
    for photo, dared, due in (("seen", False, False), (None, True, False), (None, False, True)):
        assert wr._dare_beat("ai_dare", wr.Need(wr.BRUSH_OFF), photo, dared, due).asked_ids == ()


def case_marker_only_draft_falls_through():
    def floor(text, ids=frozenset()):
        return wr.reject(wr.asked_marker(text, ids).text, "en", False)

    assert floor(f"{LINE}\nASKED: home_city") is None
    assert floor(f"{LINE}\nASKED: [home_city]") is None
    assert floor("ASKED: home_city") == "no_letters"
    assert floor(f"{LINE}\nASKED: [hobbies, location]") is None
    assert floor(f"{LINE}\nASKED: none - just vibing") is None
    ids = frozenset({"home_city", "hobbies"})
    assert floor(f"{LINE} asked: hobbies", ids) is None
    assert floor(f"[hobbies] {LINE}", ids) is None
    assert floor(f"[hobbies] {LINE}") == "bracket"
    assert wr.reject(f"{LINE}\nASKED: [home_city]", "en", False) == "bracket"
    assert wr.reject(f"{LINE}\nASKED:", "en", False) is not None
    got, rep, systems = _turn("p-ask-floor", "hey you", info=FakeInfoJev(({}, "home_city")),
                              nano="ok:ASKED: home_city", rest=f"ok:{LINE}\nASKED: home_city")
    assert got["status"] == "sent" and len(systems) == 2 and systems[0] == systems[1], got
    assert [a["outcome"] for a in rep["attempts"]] == ["empty", "ok"], rep["attempts"]
    assert rep["asked"] == {"home_city": 1} and "ASKED" not in _texts(got["parts"]), rep


def case_quoted_marker_counted_never_leaks():
    got, rep, _ = _turn("p-ask-quoted", "hey you", info=FakeInfoJev(({}, "home_city")),
                        nano=f'ok:"{LINE}"\nASKED: home_city')
    assert got["status"] == "sent" and [a["outcome"] for a in rep["attempts"]] == ["ok"], rep["attempts"]
    assert rep["asked"] == {"home_city": 1} and rep["asked_marker"] == "home_city", rep
    text = _texts(got["parts"])
    assert "ASKED" not in text and '"' not in text, got["parts"]
    for i, raw in enumerate((f'"{LINE}\nASKED: home_city"', f'"{LINE}\nASKED home_city"',
                             f"'{LINE}\nASKED: home_city'", f'“{LINE}\nASKED: home_city”',
                             f'YOU: "{LINE}\nASKED: home_city"', f'{LINE}\nASKED: home_city"')):
        got, rep, _ = _turn(f"p-ask-quoted-whole-{i}", "hey you",
                            info=FakeInfoJev(({}, "home_city")), nano="ok:" + raw)
        text = _texts(got["parts"])
        assert got["status"] == "sent" and rep["asked"] == {"home_city": 1}, (raw, rep)
        assert "ASKED" not in text and not set(text) & set('"“”') and text.strip("'") == text, (raw, got["parts"])


class _Heat:

    def __init__(self, *scores):
        self.scores = list(scores)

    async def system_one(self, state, questions, model=None):
        return SimpleNamespace(scores={"reply_level": SimpleNamespace(
            score=self.scores.pop(0), probabilities={0: .1, 1: .1, 2: .2, 3: .4, 4: .2})})


def case_heat_rewrite_strips():
    got, rep, _ = _turn("p-ask-heat", "ur making me so hard", heat=_Heat(4.0, 3.0),
                        nano=["ok:mm i want u so bad\nASKED: none", "ok:mm come here baby\nASKED: none"],
                        fake_j=FakeJev(({**QUIET, "sexual_now": 0.95}, 2.0)))
    assert got["route"] == "sext" and rep["heat_check"]["outcome"] == "regen_ok", rep
    assert "baby" in _texts(got["parts"]) and "ASKED" not in _texts(got["parts"]), got["parts"]


def _fail_second(n: int, _text: str) -> None:
    if n == 2:
        raise RuntimeError("HTTP 500 boom")


async def case_live_cut_counts_nothing():
    answer = f"{LINE3}\nASKED: occupation"
    for aid, fan, of, want in (("fa_ask_whole", 701, LiveOF(), {"occupation": 1}),
                               ("fa_ask_cut", 702, LiveOF(_fail_second), {})):
        await seed_live(aid)
        await fan_row(aid, fan)
        res, *_ = await dm_turn(aid, fan, fan * 10, "hey", fake=of, writers={NANO: answer},
                                info=FakeInfoJev(({}, "occupation")))
        (r,) = await live_rows(aid, fan)
        rep = reply(r)
        assert (r.status, rep["asked"], rep["asked_marker"]) == ("sent", want, "occupation"), (aid, r.status, rep)
        assert ("cut" in rep) == (not want) and len(rep["parts"]) >= 2, (aid, rep)
        assert "ASKED" not in _texts(rep["parts"]) and all("ASKED" not in x["text"] for x in of.sent), of.sent


if __name__ == "__main__":
    _harness.run()
