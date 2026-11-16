#!/usr/bin/env python3
"""test_full_ai_rules — the AI rules page's read (GET /admin/full-ai/rules, automations/full_ai_rules.py).

  case_owner_gets_200_and_no_login_is_refused   the handler serves a signed-in owner, 401 with no session;
                                                the route answers to the /ai-rules page grant
  case_router_questions_are_the_code_constants  both Modes: every Router question id present, text identical
  case_price_instructions_are_the_constant      PRICE instructions == _price_jev.PRICE["instructions"]; the
                                                Chat tease price Choice, its options and keys (chat_tease)
  case_every_default_key_is_a_switch            every DEFAULTS key in the switches table; Shadow chips only
                                                what Shadow reads
  case_test_only_keys_are_the_gates             every full_ai_writers `*_flag` gate is in GATES; each counts
                                                in test Mode only
  case_every_router_variant_and_keyset_shown    every router TEST_* wording dict and *_STATE_KEYS set in test
  case_edges_point_at_nodes                     every edge's ends are node ids; ids unique; same node set both Modes
  case_shadow_holds_no_test_only_wording        no test-only question, prompt or flag in Shadow
  case_route_rows_match_decide_turn             the table's rows are decide_turn's own rows and Routes
  case_info_shows_old_and_lead_wording          NEXT_QUESTION and NEXT_QUESTION_LEAD labelled, extract prompt shown
  case_bad_mode_is_refused                      ValueError on an unknown mode
  case_price_text_matches_code                  rwl-a F15: no "clamped to the list price"; tease prices named;
                                                reply keys include chat_tease and ride; cents shown
  case_heat_check_listed                        96: the reply chain lists `reply_level` with its five
                                                criteria under floor_on, doc NEW-155; reply keys hold
                                                heat_check; not on the Shadow page
  case_cutoff_is_what_fired_applies             rwl-a N8: test Mode shows the TEST_THRESHOLDS value, not min
                                                with Shadow's; both pages show declines_buying's .95

Run: ./venv/bin/python service/tests/test_full_ai_rules.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

from types import SimpleNamespace  # noqa: E402

from fastapi import HTTPException  # noqa: E402

import auth  # noqa: E402
import full_ai_api  # noqa: E402
import permissions  # noqa: E402
from automations import _heat_jev as hj  # noqa: E402
from automations import _info_jev as ij  # noqa: E402
from automations import _price_jev as pj  # noqa: E402
from automations import _router_jev as rj  # noqa: E402
from automations import full_ai_config, full_ai_decide  # noqa: E402
from automations import full_ai_rules as fr  # noqa: E402
from automations import full_ai_writers as fw  # noqa: E402
from automations.full_ai_mode import full  # noqa: E402


def _node(payload: dict, nid: str) -> dict:
    (n,) = [n for n in payload["nodes"] if n["id"] == nid]
    return n


def _strings(x) -> list[str]:
    if isinstance(x, str):
        return [x]
    if isinstance(x, dict):
        return [s for v in x.values() for s in _strings(v)]
    if isinstance(x, list):
        return [s for v in x for s in _strings(v)]
    return []


async def _as_owner(mode: str) -> dict:
    tok = auth._request_user.set(auth.AuthedUser("u_rules", "rules_owner", frozenset({"acct_rules"})))
    try:
        return await full_ai_api.full_ai_rules_read(mode=mode)
    finally:
        auth._request_user.reset(tok)


async def case_owner_gets_200_and_no_login_is_refused():
    for mode in fr.MODES:
        got = await _as_owner(mode)
        assert got["mode"] == mode and got["nodes"] and got["edges"], mode
    try:
        await full_ai_api.full_ai_rules_read(mode="test")
    except HTTPException as e:
        assert e.status_code == 401, e.status_code
    else:
        raise AssertionError("no session was served")
    assert permissions.route_pages("/admin/full-ai/rules", "GET") == ("/ai-rules",)
    assert permissions.route_pages("/admin/full-ai/today", "GET") == ("/full-ai-chatter",)


def case_router_questions_are_the_code_constants():
    for mode in fr.MODES:
        blocks = _node(fr.rules(mode), "router_jev")["blocks"]
        by_id: dict[str, list[str]] = {}
        for b in blocks:
            if "qid" in b:
                by_id.setdefault(b["qid"], []).append(b["text"])
        want = {**rj.QUESTIONS, "intensity": rj.INTENSITY}
        if full(mode):      # test + live ask `TEST_NEW_ONLY`'s wording in its place (`_router_jev._questions`)
            want |= {**rj.TEST_NEW_ONLY, **rj.TEST_NOULS, **rj.TEST_CHOICES}
        assert set(by_id) == set(want), (mode, set(want) ^ set(by_id))
        for qid, spec in want.items():
            assert spec["instructions"] in by_id[qid], (mode, qid)
        if full(mode):      # rwl2 F6: Shadow's asks_if_ai wording is not shown as what test / live ask
            for qid in rj.TEST_NEW_ONLY:
                assert rj.QUESTIONS[qid]["instructions"] not in by_id[qid], (mode, qid)
        if full(mode):
            for qid, spec in rj.TEST_SPACING.items():
                assert spec["instructions"] in by_id[qid], ("spacing", qid)
        # The cut-off shown is the one `fired` applies.
        promo = next(b for b in blocks if b.get("qid") == "promo")
        assert f"cut-off: {rj.THRESHOLDS['promo']}" in promo["items"], promo["items"]


def case_price_instructions_are_the_constant():
    p = fr.rules("test")
    blocks = _node(p, "price_jev")["blocks"]
    b, t = [b for b in blocks if b["kind"] == "prompt"]
    assert b["text"] == pj.PRICE["instructions"] and b["doc"] == "NEW-134" and b["flag"] == "sext_scene"
    assert t["text"] == pj.TEASE_PRICE["instructions"] and t["doc"] == "NEW-153" and t["flag"] == "chat_tease"
    opts = pj.tease_options(full_ai_config.DEFAULTS["chat_tease_prices"])
    assert [i.split(":", 1)[0] for i in t["items"][:len(opts)]] == list(opts), t["items"]
    lists = {b["label"]: b["items"] for b in blocks if b["kind"] == "list"}
    assert lists["Tease price state keys"] == list(pj.TEASE_PRICE_STATE_KEYS), lists
    assert p["versions"]["tease_price_version"] == pj.TEASE_PRICE_VERSION
    assert "chat_tease_prices" in {f["key"] for f in _node(p, "price_jev")["flags"]}


def case_heat_check_listed():
    blocks = _node(fr.rules("test"), "reply_chain")["blocks"]
    (b,) = [b for b in blocks if b.get("doc") == "NEW-155"]
    assert b["kind"] == "prompt" and b["flag"] == "floor_on" and b["text"] == hj.REPLY_LEVEL["instructions"], b
    assert b["items"][:5] == [f"{i}: {c}" for i, c in enumerate(hj.REPLY_LEVEL["criteria"])], b["items"]
    assert "floor_on" in {f["key"] for f in _node(fr.rules("test"), "reply_chain")["flags"]}
    assert "heat_check" in fr._REPLY_KEYS
    shadow = _node(fr.rules("shadow"), "reply_chain")["blocks"]
    assert not [b for b in shadow if b.get("doc") == "NEW-155"], shadow


def case_every_default_key_is_a_switch():
    for mode in fr.MODES:
        n = _node(fr.rules(mode), "switches")
        want = list(full_ai_config.DEFAULTS) if full(mode) else list(fr.SHADOW_READS)
        assert [f["key"] for f in n["flags"]] == want, mode
        rows = n["blocks"][0]["rows"]
        assert [r[0] for r in rows[1:]] == list(full_ai_config.DEFAULTS), mode
        scoped = {r[0] for r in rows[1:] if r[3].startswith("test + live (off")}
        assert scoped == set(fr.TEST_ONLY_KEYS), scoped
        live = {r[0] for r in rows[1:] if r[3].startswith("live only")}
        assert live == set(fr.LIVE_ONLY_KEYS), live
    assert set(fr.TEST_ONLY_KEYS) | set(fr.SHADOW_READS) | set(fr.LIVE_ONLY_KEYS) <= set(full_ai_config.DEFAULTS)
    assert "top_spend_cents" in fr.LIVE_ONLY_KEYS
    # Every key Shadow reads sits on a step card too, not just the switches table.
    for mode in fr.MODES:
        steps = {f["key"] for n in fr.rules(mode)["nodes"] if n["id"] != "switches" for f in n["flags"]}
        assert set(fr.SHADOW_READS) <= steps, (mode, steps)


def case_test_only_keys_are_the_gates():
    gates = {n for n in dir(fw) if n.endswith("_flag") and callable(getattr(fw, n))}
    assert gates <= {g.__name__ for g in fr.GATES.values()}, gates
    on = {**full_ai_config.DEFAULTS, "sext_scene": True, "lead_in": True, "sell_nearest": "plain",
          "sell_spacing": True, "he_likes": True, "sell_bundle": "fill",
          "chat_tease": True, "ask_implied": True, "info_wide": True, "sell_count": True}
    for key, gate in fr.GATES.items():
        test = gate(SimpleNamespace(mode="test", config=on))
        shadow = gate(SimpleNamespace(mode="shadow", config=on))
        assert test and test != shadow and shadow in (False, "shoot"), (key, test, shadow)


def case_every_router_variant_and_keyset_shown():
    p = fr.rules("test")
    router_text = "\n".join(_strings(_node(p, "router_jev")))
    dicts = [n for n in dir(rj) if n.startswith("TEST_") and isinstance(getattr(rj, n), dict)
             and all(isinstance(v, dict) and "instructions" in v for v in getattr(rj, n).values())]
    assert {"TEST_NOULS", "TEST_CHOICES", "TEST_SPACING", "TEST_LIKES"} <= set(dicts), dicts
    for n in dicts:
        for qid, spec in getattr(rj, n).items():
            assert spec["instructions"] in router_text, (n, qid)
    keys = next(b for b in _node(p, "his_lines")["blocks"] if b["label"] == "Router state keys")["items"]
    for n in dir(rj):
        if n.endswith("_STATE_KEYS"):
            assert set(getattr(rj, n)) <= set(keys) or n == "STATE_KEYS", n
    assert "he_likes" in keys and "teases_sent" in keys
    assert all(v in router_text for v in rj.TEST_NOULS["chat_tease"]["criteria"].values())   # Chat tease wording
    assert {p for p, _ in fr.keysets()} <= set(fr._KEYSET_FLAG), fr.keysets()
    info_text = "\n".join(_strings(_node(p, "get_fan_info")))
    assert ij.LIKES_EXTRACT in info_text
    d = full_ai_config.DEFAULTS
    assert ij.HOBBIES_EXTRACT in info_text
    for spec in ij.STATED_WIDE.values():
        assert spec["instructions"] in info_text
    assert p["versions"]["info_version"] == ij.info_version(bool(d["lead_in"]), bool(d["he_likes"]),
                                                            bool(d["info_wide"]))


def case_edges_point_at_nodes():
    ids = {}
    for mode in fr.MODES:
        p = fr.rules(mode)
        nids = [n["id"] for n in p["nodes"]]
        assert len(nids) == len(set(nids)) == 11, nids
        ids[mode] = nids
        for e in p["edges"]:
            assert e["from"] in nids and e["to"] in nids, e
        routes = {e["label"] for e in p["edges"] if e["from"] == "route_table"}
        assert routes == set(full_ai_decide.Route.__args__), routes
    assert ids["test"] == ids["shadow"]


def case_shadow_holds_no_test_only_wording():
    p = fr.rules("shadow")
    text = "\n".join(_strings(p))
    test_only = [s["instructions"] for s in (*rj.TEST_NOULS.values(), *rj.TEST_CHOICES.values(),
                                             *rj.TEST_SPACING.values(), *rj.TEST_LIKES.values(),
                                             *rj.TEST_IMPLIED.values(), *ij.STATED_WIDE.values())]
    test_only.append(ij.HOBBIES_EXTRACT)
    test_only += [ij.NEXT_QUESTION_LEAD["instructions"], ij.LIKES_EXTRACT, pj.PRICE["instructions"],
                  pj.TEASE_PRICE["instructions"], pj.TEASE_PRICE["free"], fw.LEAD_HEAD, fw.SELF_GIVE,
                  fw.SEXT_SCENE, fw.SCENE_NARRATION, *fw.LEAD_LINES.values(), *fw.SCENE_STAGE.values()]
    test_only += [fw.SEXT_HOT_TEST, fw.RIDE_NOTE, fw.OFFER_OPEN, "these are real, already made"]
    test_only += [s.split("{", 1)[0] for s in (fw.NEAREST_NOTE, fw.SCENE_SELL, fw.SELL_OFF_SCENE,
                                                fw.SELL_STEP_TEST, fw.ESCALATION_TEST)]
    leaks = [s[:60] for s in test_only if s.strip() and s.strip() in text]
    assert leaks == [], leaks
    flags = {f["key"] for n in p["nodes"] for f in n["flags"]}
    blocks = {b.get("flag") for n in p["nodes"] for b in n["blocks"]} - {None}
    assert flags <= set(fr.SHADOW_READS) and blocks <= set(fr.SHADOW_READS), (flags, blocks)
    table = next(b for b in _node(p, "route_table")["blocks"] if b["label"] == "Rows in walk order")["rows"][1:]
    assert not {"sell_off", "tease_off", "sext_off"} & {r[1] for r in table}, table   # route flags all on
    assert not any("after a tease" in r[0] for r in table), table                      # no Pending tease
    assert not any(e["to"] == "price_jev" or e["from"] == "price_jev" for e in p["edges"])
    assert "tease_price_version" not in p["versions"] and "teases_sent" not in text
    assert "Shadow" in [b["label"] for b in _node(p, "writers")["blocks"]]


def case_route_rows_match_decide_turn():
    for mode in fr.MODES:
        (b,) = [b for b in _node(fr.rules(mode), "route_table")["blocks"] if b["label"] == "Rows in walk order"]
        rows = b["rows"][1:]
        assert rows[0][1:] == ["jev_failed", "chat"], rows[0]
        assert [r[1] for r in rows[1:1 + len(full_ai_decide._FIRST)]] == [q for q, _ in full_ai_decide._FIRST]
        names = {r[1] for r in rows}
        assert {"sell", "tease_price", "sexual_now", "otherwise"} <= names, names
        # "Broke" routes nothing in any Mode (owner 2026-11-15); the page still names it.
        assert ["declines_buying fired: routes nothing; the Writer may joke", "otherwise", "chat"] in rows, rows
        assert not {"decline", "tease_decline"} & names, names
        assert ("sell_off" in names) == (full(mode)), names
        assert ("haggle" in names) == (full(mode)) and ("scene_offer" in names) == (full(mode)), names
        assert ("chat_tease" in names) == (full(mode)), names


def case_info_shows_old_and_lead_wording():
    blocks = _node(fr.rules("test"), "get_fan_info")["blocks"]
    by_label = {b["label"]: b for b in blocks}
    assert by_label["next_question (Choice) — old wording"]["text"] == ij.NEXT_QUESTION["instructions"]
    lead = by_label["next_question (Choice) — lead-in wording, DRAFT"]
    assert lead["text"] == ij.NEXT_QUESTION_LEAD["instructions"] and lead["flag"] == "lead_in"
    assert any(b["text"].startswith("You are a profile analyzer") for b in blocks if b["kind"] == "prompt")
    store = _node(fr.rules("test"), "store")["blocks"][0]
    assert store["items"] == list(full_ai_config.INFO_FIELDS), store


def case_bad_mode_is_refused():
    try:
        fr.rules("nope")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown mode served")


def case_price_text_matches_code():
    page = " ".join(_strings(fr.rules("test")))
    assert "clamped to the list price" not in page and "chat_tease_prices option" in page, page[:200]
    assert {"chat_tease", "ride"} <= set(fr._REPLY_KEYS), fr._REPLY_KEYS
    assert fr._money(1250) == "$12.50" and fr._money(1000) == "$10"



def case_cutoff_is_what_fired_applies():
    for qid in rj.TEST_THRESHOLDS:
        assert fr._cutoff(qid, "test") == rj.TEST_THRESHOLDS[qid], qid
        assert fr._cutoff(qid, "shadow") == rj.THRESHOLDS.get(qid), qid
    assert fr._cutoff("declines_buying", "test") == fr._cutoff("declines_buying", "shadow") == .95
    assert fr._cutoff("promo", "test") == rj.THRESHOLDS["promo"]
    for mode in fr.MODES:
        blocks = _node(fr.rules(mode), "router_jev")["blocks"]
        db = next(b for b in blocks if b.get("qid") == "declines_buying")
        assert "cut-off: 0.95" in db["items"], (mode, db["items"])


_harness.run()
