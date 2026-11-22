#!/usr/bin/env python3
"""test_full_ai_rules — the AI rules page's read (GET /admin/full-ai/rules, automations/full_ai_rules.py).

  case_owner_gets_200_and_no_login_is_refused   the handler serves a signed-in owner, 401 with no session;
                                                the route answers to the /ai-rules page grant
  case_router_questions_are_the_code_constants  both Modes: every Router question id present, text identical
  case_price_instructions_are_the_constant      PRICE instructions == _price_jev.PRICE["instructions"]; the
                                                Chat tease price Choice, its options and keys (chat_tease)
  case_every_default_key_is_a_switch            every DEFAULTS key in the switches table and chips
  case_test_only_keys_are_the_gates             every full_ai_writers `*_flag` gate is in GATES; each counts
                                                in test Mode only
  case_every_router_variant_and_keyset_shown    every router TEST_* wording dict and *_STATE_KEYS set in test
  case_edges_point_at_nodes                     every edge's ends are node ids; ids unique; same node set both Modes
  case_shadow_is_refused                        W30 #6: no Shadow view (owner 11-15): rules("shadow") and the
                                                route's mode both refuse it
  case_route_rows_match_decide_turn             the table's rows are decide_turn's own rows and Routes
  case_info_shows_old_and_lead_wording          NEXT_QUESTION and NEXT_QUESTION_LEAD labelled, extract prompt shown
  case_bad_mode_is_refused                      ValueError on an unknown mode
  case_price_text_matches_code                  rwl-a F15: no "clamped to the list price"; tease prices named;
                                                reply keys include chat_tease and ride; cents shown
  case_heat_check_listed                        96: the reply chain lists `reply_level` with its five
                                                criteria under floor_on, doc NEW-155; reply keys hold
                                                heat_check
  case_cutoff_is_what_fired_applies             rwl-a N8: the page shows the TEST_THRESHOLDS value; both
                                                Modes show declines_buying's .95
  case_every_decider_row_on_the_page            every row decide_turn can return (enumerated over Facts' flags
                                                and fired pairs) is a table row
  case_every_vault_switch_on_the_page           every vault_settings key in the test page's vault table
  case_offer_details_shown                      resolver steps (Step), look-back constants, OfferFacts fields,
                                                the branch prompt (OFFER_GOAL, no NO_SELL_OFFERS), check RULES,
                                                diagnostics keys, the switch notes, the live read

Run: ./venv/bin/python service/tests/test_full_ai_rules.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import itertools  # noqa: E402
from dataclasses import fields  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from typing import get_args, get_type_hints  # noqa: E402

from fastapi import HTTPException  # noqa: E402

import auth  # noqa: E402
import full_ai_api  # noqa: E402
import permissions  # noqa: E402
import vault_settings  # noqa: E402
from automations import _heat_jev as hj  # noqa: E402
from automations import _info_jev as ij  # noqa: E402
from automations import _price_jev as pj  # noqa: E402
from automations import _router_jev as rj  # noqa: E402
from automations import full_ai_config, full_ai_decide  # noqa: E402
from automations import full_ai_offer_details as fo  # noqa: E402
from automations import full_ai_rules as fr  # noqa: E402
from automations import full_ai_writers as fw  # noqa: E402


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
        # test + live ask `TEST_NEW_ONLY`'s wording in its place (`_router_jev._questions`)
        want = {**rj.QUESTIONS, "intensity": rj.INTENSITY, **rj.TEST_NEW_ONLY, **rj.TEST_NOULS, **rj.TEST_CHOICES}
        assert set(by_id) == set(want), (mode, set(want) ^ set(by_id))
        for qid, spec in want.items():
            assert spec["instructions"] in by_id[qid], (mode, qid)
        for qid in rj.TEST_NEW_ONLY:   # rwl2 F6: the old asks_if_ai wording is not shown as what test / live ask
            assert rj.QUESTIONS[qid]["instructions"] not in by_id[qid], (mode, qid)
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


def case_every_default_key_is_a_switch():
    for mode in fr.MODES:
        n = _node(fr.rules(mode), "switches")
        assert [f["key"] for f in n["flags"]] == list(full_ai_config.DEFAULTS), mode
        rows = n["blocks"][0]["rows"]
        assert [r[0] for r in rows[1:]] == list(full_ai_config.DEFAULTS), mode
        live = {r[0] for r in rows[1:] if r[3].startswith("live only")}
        assert live == set(fr.LIVE_ONLY_KEYS), live
        assert {r[3] for r in rows[1:] if r[0] not in live} == {"test + live"}, rows
    assert set(fr.LIVE_ONLY_KEYS) <= set(full_ai_config.DEFAULTS)
    assert "top_spend_cents" in fr.LIVE_ONLY_KEYS


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
    assert ids["test"] == ids["live"]


async def case_shadow_is_refused():
    # W30 #6: the page never asks for Shadow (AiRulesPage reads ?mode=test; owner 11-15 no Shadow view).
    assert fr.MODES == ("test", "live"), fr.MODES
    try:
        fr.rules("shadow")
    except ValueError:
        pass
    else:
        raise AssertionError("Shadow page served")
    assert get_args(get_type_hints(full_ai_api.full_ai_rules_read)["mode"]) == ("test", "live")


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
        assert {"sell_off", "haggle", "scene_offer", "chat_tease"} <= names, names


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
        assert fr._cutoff(qid) == rj.TEST_THRESHOLDS[qid], qid
    assert fr._cutoff("declines_buying") == .95
    assert fr._cutoff("promo") == rj.THRESHOLDS["promo"]
    for mode in fr.MODES:
        blocks = _node(fr.rules(mode), "router_jev")["blocks"]
        db = next(b for b in blocks if b.get("qid") == "declines_buying")
        assert "cut-off: 0.95" in db["items"], (mode, db["items"])


def _decider_rows(qids, **fixed) -> set[str]:
    """Every row `decide_turn` returns over all of Facts' bool flags not `fixed` and every fired set of at
    most two of `qids`."""
    bools = [f.name for f in fields(full_ai_decide.Facts) if f.type in ("bool", bool) and f.name not in fixed]
    fired = [()] + [(q,) for q in qids] + list(itertools.combinations(qids, 2))
    rows = set()
    for vals in itertools.product((False, True), repeat=len(bools)):
        kw = {**dict(zip(bools, vals)), **fixed}
        for f in fired:
            rows.add(full_ai_decide.decide_turn(full_ai_decide.Facts(fired=frozenset(f), intensity=1.0, **kw)).row)
    return rows


def _table_rows(mode: str) -> set[str]:
    (b,) = [b for b in _node(fr.rules(mode), "route_table")["blocks"] if b["label"] == "Rows in walk order"]
    return {r[1] for r in b["rows"][1:]}


def case_every_decider_row_on_the_page():
    every = sorted({q for n in dir(rj) if isinstance(getattr(rj, n), dict) for q, s in getattr(rj, n).items()
                    if isinstance(s, dict) and "instructions" in s})
    want = _decider_rows(every)
    assert "offer_details" in want and want <= _table_rows("test"), want - _table_rows("test")


def case_every_vault_switch_on_the_page():
    (b,) = [b for b in _node(fr.rules("test"), "switches")["blocks"] if b["label"].startswith("Vault switches")]
    assert [r[0] for r in b["rows"][1:]] == list(vault_settings.KEYS), b["rows"]
    assert all(r[1] == ("on" if vault_settings.DEFAULTS[r[0]] else "off") and r[2]
               for r in b["rows"][1:]), b["rows"]  # undescribed key = fail, not a 500
    assert dict((r[0], r[1]) for r in b["rows"][1:])["solo_sequences"] == "on", b["rows"]


def case_offer_details_shown():
    p = fr.rules("test")
    w = _node(p, "writers")["blocks"]
    (res,) = [b for b in w if b["label"].startswith("Row offer_details: Offer resolver")]
    assert [r[0] for r in res["rows"][1:]] == list(get_args(fo.Step)), res["rows"]
    (reads,) = [b for b in w if b["label"] == "Row offer_details: what the resolver reads"]
    assert f"newest {fo.LOOKBACK_N} Offer rows sent within {fo.LOOKBACK_S // 86400} days" in reads["items"][0]
    (facts,) = [b for b in w if b["label"].startswith("Row offer_details: Offer facts")]
    assert facts["items"] == [f.name for f in fields(fo.OfferFacts)]
    branch = [b for b in w if "(row offer_details" in b["label"]]
    assert len(branch) == 2, [b["label"] for b in branch]
    for b in branch:
        assert fw.OFFER_GOAL in b["text"] and fw.OFFER_HEAD in b["text"], b["label"]
        assert fw.NO_SELL_OFFERS not in b["text"] and fw.ASKED_EXCEPTION.strip() not in b["text"], b["label"]
    assert fw.OFFER_NONE in branch[1]["text"]
    (check,) = [b for b in _node(p, "reply_chain")["blocks"] if b["label"].startswith("Offer answer check")]
    assert [i.split(":", 1)[0] for i in check["items"][:len(fo.RULES)]] == list(fo.RULES), check["items"]
    assert any("zero dollars" in i for i in check["items"]) and any("filmed" in i for i in check["items"])
    assert {"offer_details", "asked_marker", "held_tease"} <= set(fr._REPLY_KEYS)
    send = {b["label"]: b for b in _node(p, "send_record")["blocks"]}
    diag = next(b for k, b in send.items() if k.startswith("reply_json.offer_details keys"))
    assert diag["items"] == list(fo.diagnostics(fo.NONE, None)), diag["items"]
    assert "Live read before sending (live only)" in send
    store = [b["label"] for b in _node(p, "store")["blocks"]]
    assert "What moves an asked count (NEW-168)" in store, store
    sell = "\n".join(_strings(_node(p, "sell")))
    assert "hold_folder_price" in sell and "folder_price_final" in sell and "standard_folders" in sell
    assert fr._review_label() in sell and "Needs Review" in fr._review_label()
    assert "folder_price_final" in "\n".join(_strings(_node(p, "price_jev")))


_harness.run()
