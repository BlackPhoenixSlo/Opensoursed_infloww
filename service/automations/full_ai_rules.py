"""full_ai_rules — the Full AI Chat Turn as data, for the read-only AI rules page (/ai-rules).

  rules(mode) -> {mode, versions, nodes: [{id, title, group, summary, flags, blocks}], edges}

Every prompt, Jev question, threshold, table and key below is read off the live code objects
(the constants, or the pure builders called with a placeholder Fan), never pasted here, so the
page cannot drift from what a Turn sends. Hand-written: the step titles and 1-2 sentence
summaries, the Sell executor's short rules (numbers from its constants), the edge labels, the
prompt-catalog ids (docs/prompts/README.md), the route probes' "when" text, the fold table,
the floor reasons and the jev_json / reply_json key lists (dict literals inside run_turn).

A block: {label, kind: prompt|table|list|note, text | rows | items, source, doc?, flag?, qid?}.
A prompt block may also carry `items` (a question's criteria and cut-off); a table's first row
is its header. `flag` names the config key the wording rides on (test + live, never Shadow).

Mode "test" (and "live", the same page) is the full Turn (full_ai_turn.run_turn). "shadow" asks the Router and
writes the Decision row (status planned) and stops (automations/full_ai_chat.py), so its later
steps carry a note, and no test-only wording appears anywhere in it; it reads no config but
`describe_fan_photos` (route flags all on, no Pending tease). Pure: no DB, no network.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import inbound_describe

from automations import _heat_jev as heat
from automations import _info_jev as info
from automations import _price_jev as price
from automations import _prompt_rules as rules_txt
from automations import _router_jev as router
from automations import full_ai_caption as caption
from automations import full_ai_config as config
from automations import full_ai_decide as decide
from automations import full_ai_photo as photo
from automations import full_ai_scene as scene
from automations import full_ai_sell as sell
from automations import full_ai_test as test_chat
from automations import full_ai_writers as writers
from automations import welcome_chatter_for_info as wcfi
from automations.full_ai_mode import MODES, full   # MODES: the rules route's modes
from db.models import AiDecision

# Config keys that count in test + live only: each one's gate checks `full(mode)`. The
# full_ai_writers gates by key; test_full_ai_rules.py probes every `*_flag` there against this map.
# `draft_questions`' gate is inline in full_ai_turn._route.
GATES = {"sext_scene": writers.scene_flag, "lead_in": writers.lead_flag, "sell_nearest": writers.nearest_flag,
         "sell_spacing": writers.spacing_flag, "he_likes": writers.likes_flag, "sell_bundle": writers.bundle_of,
         "chat_tease": writers.tease_flag, "ask_implied": writers.implied_flag,
         "info_wide": writers.wide_flag, "sell_count": writers.count_flag}
# `chat_tease_prices` is read only on a Chat tease Turn (`tease_flag`). "Test only" is 03b's name:
# these count in test + live (`full(mode)`); Shadow ignores them.
TEST_ONLY_KEYS = (*GATES, "draft_questions", "chat_tease_prices")
# Config keys only live reads: the live sender's owner check (spec 04b, `full_ai_owner_io`) and the catch-up's
# schedule (`full_ai_catchup`). Test and Shadow ignore them.
LIVE_ONLY_KEYS = ("top_spend_cents", "fans", "catchup_minutes")
# The only config key Shadow reads (full_ai_chat._photos_on; its Facts keep every route flag on).
SHADOW_READS = (photo.KEY,)
# Router wording variants a test-only key swaps in: (router dict, flag, label). `TEST_NEW_ONLY` (no key: test and
# live always ask it) is the main block in full modes (`_router`), as `_router_jev._questions` merges it.
_VARIANTS = (("TEST_SPACING", "sell_spacing", "Spacing"), ("TEST_LIKES", "he_likes", "He likes"),
             ("TEST_IMPLIED", "ask_implied", "Implied"))
# Router state key sets test Mode adds (`full_ai_test.fetch`): router `<NAME>_STATE_KEYS` -> flag.
_KEYSET_FLAG = {"SCENE": "sext_scene", "SPACING": "sell_spacing", "LIKES": "he_likes", "TEASE": "chat_tease"}

# Prompt-catalog ids (docs/prompts/README.md) of the wording shown here.
_DOC = {
    "QUESTIONS": "NEW-106", "asks_subject": "NEW-118", "asks_format": "NEW-119",
    "counter_offer": "NEW-120", "offer_moment": "NEW-121", "scene_on": "NEW-133", "scene_offer": "NEW-133",
    "scene_stage": "NEW-133", "offer_level": "NEW-133", "spacing:offer_moment": "NEW-142",
    "spacing:scene_offer": "NEW-143", "info": "NEW-115", "NEXT_QUESTION_LEAD": "NEW-139",
    "_EXTRACT_SYSTEM": "NEW-45", "_extract_messages": "NEW-46", "PRICE": "NEW-134",
    "chat": "NEW-109", "sell_now": "NEW-116", "SELL_OFF_LINE": "NEW-111", "MAKE_RIGHT_HEAD": "NEW-112",
    "DARE_JOIN": "NEW-113", "BRUSH_OFF": "NEW-159", "DARE_NEXT": "NEW-160", "SEXT_HEAT": "NEW-114", "TEASE_GOAL": "NEW-123", "CAPTION_APART": "NEW-126",
    "FREE_PRICE_BLOCK": "NEW-127", "caption": "NEW-128", "SEXT_SCENE": "NEW-129", "SCENE_STAGE": "NEW-130",
    "SCENE_SELL": "NEW-131", "SCENE_NARRATION": "NEW-132", "SCENE_SELF": "NEW-132", "LEAD_HEAD": "NEW-135",
    "LEAD_LINES": "NEW-136", "LEAD_EXAMPLES": "NEW-137", "SELF_GIVE": "NEW-138", "NEAREST_NOTE": "NEW-161", "OFFER_OPEN": "NEW-162", "MANIFEST_TEST": "NEW-163",
    "SELL_OFF_SCENE": "NEW-141", "fallback_caption": "NEW-122", "LIKES_EXTRACT": "NEW-144",
    "SEXT_HOT_TEST": "NEW-145", "SELL_STEP_TEST": "NEW-146", "ESCALATION_TEST": "NEW-147", "RIDE_NOTE": "NEW-148",
    "chat_tease": "NEW-149", "implied:wants_content": "NEW-150",
    "new only:asks_if_ai": "NEW-158", "STATED_WIDE": "NEW-151",
    "HOBBIES_EXTRACT": "NEW-152", "TEASE_PRICE": "NEW-153", "BROKE_JOKE": "NEW-154", "describe": "NEW-73",
    "REPLY_LEVEL": "NEW-155",
}

_RJ, _IJ, _PJ = ("service/automations/_router_jev.py", "service/automations/_info_jev.py",
                 "service/automations/_price_jev.py")
_FW, _FS, _FT = ("service/automations/full_ai_writers.py", "service/automations/full_ai_sell.py",
                 "service/automations/full_ai_turn.py")
_FC, _CFG, _WC = ("service/automations/full_ai_caption.py", "service/automations/full_ai_config.py",
                  "service/automations/welcome_chatter_for_info.py")
_TEST = "service/automations/full_ai_test.py"
_SHADOW_NOTE = ("Shadow records the Decision row (status planned) and stops here: this step runs "
                "in test and live Modes only.")


def _b(label: str, kind: str, source: str, *, doc: str | None = None, flag: str | None = None,
       **body: Any) -> dict[str, Any]:
    out = {"label": label, "kind": kind, "source": source, **body}
    if doc:
        out["doc"] = doc
    if flag:
        out["flag"] = flag
    return out


def _prompt(label: str, text: str, source: str, **kw: Any) -> dict[str, Any]:
    return _b(label, "prompt", source, text=text, **kw)


def _note(label: str, text: str, source: str, **kw: Any) -> dict[str, Any]:
    return _b(label, "note", source, text=text, **kw)


def _list(label: str, items: list[str], source: str, **kw: Any) -> dict[str, Any]:
    return _b(label, "list", source, items=[str(i) for i in items], **kw)


def _table(label: str, rows: list[list[Any]], source: str, **kw: Any) -> dict[str, Any]:
    return _b(label, "table", source, rows=[[str(c) for c in r] for r in rows], **kw)


def _criteria(criteria: Any) -> list[str]:
    if isinstance(criteria, dict):
        return [f"{'YES' if k == 'true' else 'NO' if k == 'false' else k}: {v}" for k, v in criteria.items()]
    return [f"{i}: {v}" for i, v in enumerate(criteria)]


def _cutoff(qid: str, mode: str) -> float | None:
    """`router.fired`'s threshold: in test Mode a `TEST_THRESHOLDS` value replaces `THRESHOLDS`'."""
    test = router.TEST_THRESHOLDS.get(qid) if full(mode) else None
    return router.THRESHOLDS.get(qid) if test is None else test


def _flag(key: str) -> dict[str, Any]:
    return {"key": key, "label": _label(key), "default": config.DEFAULTS[key]}


def _label(key: str) -> str:
    from assistant_full_ai import label   # lazy: assistant_full_ai imports the automations
    return label(key)


def _node(nid: str, title: str, group: str, summary: str, blocks: list[dict], flags: tuple[str, ...] = (),
          mode: str = "test") -> dict[str, Any]:
    keep = [k for k in flags if full(mode) or k in SHADOW_READS]
    return {"id": nid, "title": title, "group": group, "summary": summary,
            "flags": [_flag(k) for k in keep], "blocks": blocks}


# ── 1. His lines + state ───────────────────────────────────────────────────

def keysets() -> list[tuple[str, tuple[str, ...]]]:
    """(prefix, keys) per router `<PREFIX>_STATE_KEYS`: the sets test Mode adds to the state."""
    return [(n.removesuffix("_STATE_KEYS"), getattr(router, n)) for n in sorted(dir(router))
            if n.endswith("_STATE_KEYS") and n != "STATE_KEYS"]


def _state_keys(mode: str) -> list[str]:
    keys = list(router.state([], [], "", "", ""))
    if full(mode):
        keys += [k for _, ks in keysets() for k in ks if k not in keys]
    return keys


def _his_lines(mode: str) -> dict:
    blocks = [
        _list("Router state keys", _state_keys(mode), f"{_RJ}:state"),
        _table("What the state reads", [["setting", "value"], ["model", router.MODEL],
                                        ["thread lines", router.THREAD_LINES],
                                        ["purchase window (days)", router.PURCHASE_DAYS],
                                        ["state version", router.STATE_VERSION],
                                        ["Jev timeout (s)", router.TIMEOUT_S]], f"{_RJ}:THREAD_LINES"),
        _prompt(f"Photo describe (vision, with {photo.KEY})", inbound_describe._PROMPT,
                "service/inbound_describe.py:_PROMPT", doc=_DOC["describe"], flag=photo.KEY),
        _list("His photo line, as the Router and Writers read it", [
            router.line_text(SimpleNamespace(body="his words", photo_read="<description>", media_count=1,
                                             direction="in", raw_json=None)),
            f"models: {', '.join(inbound_describe._MODELS)} (escalate on a refusal only)",
            "his words sent with the photo are appended to the prompt above (describe_images)",
            "Shadow: only descriptions already cached (no OF client)" if mode == "shadow"
            else "test: the uploaded photo is described once for both sides",
        ], f"{_RJ}:line_text", flag=photo.KEY),
    ]
    if full(mode):
        for prefix, ks in keysets():
            flag = _KEYSET_FLAG.get(prefix)
            blocks.append(_list(f"{prefix.title()} keys" + (f" (with {flag})" if flag else ""), list(ks),
                                f"{_RJ}:{prefix}_STATE_KEYS", flag=flag))
    return _node("his_lines", "His lines + state", "input",
                 "His new messages, the thread before them, her last line, his last purchase and the "
                 "Pending offer become the one Jev state every question reads.",
                 blocks, (photo.KEY, *_KEYSET_FLAG.values()), mode)


# ── 2. Router Jev ──────────────────────────────────────────────────────────

def _question(qid: str, spec: dict, mode: str, src: str, *, kind: str = "Noul",
              flag: str | None = None, doc: str | None = None, draft: bool = False) -> dict:
    items = _criteria(spec["criteria"])
    cut = _cutoff(qid, mode)
    if cut is not None:
        items.append(f"cut-off: {cut}")
    if kind == "Choice":
        items.append(f"default: {router.CHOICE_DEFAULT[qid]}")
    tag = " · DRAFT" if draft else ""
    return _prompt(f"{qid} ({kind}{tag})", spec["instructions"], src, items=items, qid=qid,
                   doc=doc or _DOC.get(qid, _DOC["QUESTIONS"]), flag=flag)


def _router(mode: str) -> dict:
    blocks = []
    for q, s in router.QUESTIONS.items():
        if full(mode) and q in router.TEST_NEW_ONLY:
            blocks.append(_question(q, router.TEST_NEW_ONLY[q], mode, f"{_RJ}:TEST_NEW_ONLY",
                                    doc=_DOC.get(f"new only:{q}")))
        else:
            blocks.append(_question(q, s, mode, f"{_RJ}:QUESTIONS"))
        if full(mode):
            blocks += _variants(q, mode, "Noul")
    blocks.append(_question("intensity", router.INTENSITY, mode, f"{_RJ}:INTENSITY", kind="Score",
                            doc=_DOC["QUESTIONS"]))
    if full(mode):
        for qid, spec in router.TEST_NOULS.items():
            blocks.append(_question(qid, spec, mode, f"{_RJ}:TEST_NOULS", draft=qid in router.DRAFT,
                                    flag="sext_scene" if qid in router.SCENE else
                                    "draft_questions" if qid in router.DRAFT else
                                    "chat_tease" if qid in router.TEASE else None))
            blocks += _variants(qid, mode, "Noul")
        for qid, spec in router.TEST_CHOICES.items():
            blocks.append(_question(qid, spec, mode, f"{_RJ}:TEST_CHOICES", kind="Choice",
                                    flag="sext_scene" if qid in router.SCENE else None))
            blocks += _variants(qid, mode, "Choice")
        drafts = [q for q in router.QUESTIONS if q in router.DRAFT]
        if drafts:
            blocks.append(_list("DRAFT ids asked but not routed on", drafts, f"{_RJ}:DRAFT"))
    blocks.append(_table("Version", [["mode", "question_version"], [mode, router.question_version(mode)]],
                         f"{_RJ}:question_version"))
    return _node("router_jev", "Router Jev", "decide",
                 "One Jev request answers every question at once; a question fires at or above its "
                 "cut-off. Test Mode adds the Choices (what he asks for) and the draft and scene Nouls.",
                 blocks, ("draft_questions", "sext_scene", "sell_spacing", "he_likes", "chat_tease",
                          "ask_implied"), mode)


def _variants(qid: str, mode: str, kind: str) -> list[dict]:
    """The `_VARIANTS` wordings that replace `qid`'s when their key is on (test Mode)."""
    out = []
    for name, flag, label in _VARIANTS:
        spec = getattr(router, name).get(qid)
        if spec is None:
            continue
        b = _question(qid, spec, mode, f"{_RJ}:{name}", kind=kind, draft=qid in router.DRAFT, flag=flag,
                      doc=_DOC.get(f"{label.lower()}:{qid}"))
        b["label"] = f"{qid} — {label} wording ({kind})"
        out.append(b)
    return out


# ── 3. Route table ─────────────────────────────────────────────────────────

def _probes(mode: str) -> list[tuple[str, dict]]:
    """(when, Facts kwargs): one probe per table row, in walk order; `decide_turn` names the row and
    Route. Test-only rows (haggle, offer_moment, scene) only in test and live Mode (`full`)."""
    test = full(mode)
    on = {"draft_on": True, "scene": True, "chat_tease": True} if test else {}
    p: list[tuple[str, dict]] = [("Jev failed (any error)", {"jev_ok": False})]
    p += [(f"{q} fired", {"fired": {q}}) for q, _ in decide._FIRST]
    if full(mode):
        p.append(("counter_offer fired on an open Offer (DRAFT, draft_questions)",
                  {"fired": {"counter_offer"}, "open_offer": True, **on}))
    p += [("wants_content fired", {"fired": {"wants_content"}}),
          ("says_yes_to_offer with a Pending offer", {"fired": {"says_yes_to_offer"}, "pending_offer": True}),
          *([("the Turn after a tease", {"pending_tease": True})] if test else []),   # Shadow sends no tease
          ("price fired", {"fired": {"price"}}),
          ("declines_buying fired: routes nothing; the Writer may joke", {"fired": {"declines_buying"}, **on})]
    if full(mode):
        p += [("offer_moment fired (DRAFT, draft_questions)", {"fired": {"offer_moment"}, **on}),
              ("scene_offer with sexual_now or scene_on (sext_scene)",
               {"fired": {"scene_offer", "sexual_now"}, **on})]
    p.append(("sexual_now fired", {"fired": {"sexual_now"}}))
    if full(mode):
        p += [("scene_on fired (sext_scene)", {"fired": {"scene_on"}, **on}),
              ("chat_tease fired (chat_tease): a photo rides her chat reply", {"fired": {"chat_tease"}, **on})]
    p.append(("nothing above", {}))
    if test:   # Shadow: route flags all on
        p += [("a sell row with sell_on off", {"fired": {"wants_content"}, "sell_on": False}),
              ("a tease row with sell_on off", {"fired": {"price"}, "sell_on": False}),
              ("sexual_now with sext_on off", {"fired": {"sexual_now"}, "sext_on": False})]
    return p


def route_rows(mode: str) -> list[list[str]]:
    rows = []
    for when, kw in _probes(mode):
        kw = {"intensity": 1.0, "pending_offer": False, "pending_tease": False, "jev_ok": True, **kw}
        kw["fired"] = frozenset(kw.get("fired", ()))
        d = decide.decide_turn(decide.Facts(**kw))
        rows.append([when, d.row, d.route])
    return rows


def _route_table(mode: str) -> dict:
    heat = [["intensity Score", "Heat"]] + [[s, decide.heat_of(s)] for s in (0, 0.5, 1.5, 2.5, 3.5)]
    flags_note = ("an off switch drops its row to chat" if full(mode)
                  else "Shadow runs with every route flag on and no Pending tease")
    return _node("route_table", "Route table", "decide",
                 f"The first matching row picks the Route; {flags_note}. Heat is his intensity level plus "
                 "one, at most 4.",
                 [_table("Rows in walk order", [["when", "row", "route"], *route_rows(mode)],
                         "service/automations/full_ai_decide.py:decide_turn"),
                  _table("Heat", heat, "service/automations/full_ai_decide.py:heat_of"),
                  _list("Routes", list(decide.Route.__args__), "service/automations/full_ai_decide.py:Route"),
                  _note("Holdout", f"{decide.HOLDOUT_PCT}% of Fans are the holdout Arm (salt version "
                        f"{decide.SALT_VER}).", "service/automations/full_ai_decide.py:arm_of")],
                 ("sell_on", "sext_on", "draft_questions", "sext_scene", "chat_tease"), mode)


# ── 4. Get fan info ────────────────────────────────────────────────────────

def _blank_fan(**set_: str) -> SimpleNamespace:
    base = dict.fromkeys(("real_name", "custom_nickname", "his_age", "home_country", "home_city",
                          "occupation", "hobbies", "fetishes", "recent_events"), "")
    return SimpleNamespace(**{**base, **set_}, likes_boobs=False, likes_ass=False)


def ask_lines() -> list[str]:
    """wcfi's still-need lines, rendered: an empty Fan, then one with a city, one with a country."""
    seen: dict[str, str] = {}
    for f in (_blank_fan(), _blank_fan(home_city="<his city>"), _blank_fan(home_country="<his country>")):
        for key, line in wcfi._questions_still_needed(f, set()):
            seen.setdefault(key, line)
    return [f"{k}: {v}" for k, v in seen.items()]


def _extract_prompt() -> list[dict]:
    f = SimpleNamespace(**dict.fromkeys(wcfi._EXTRACT_FIELDS, ""), likes_boobs=False, likes_ass=False)
    c = SimpleNamespace(messages=[("in", "<his line>"), ("out", "<her line>")])
    return wcfi._extract_messages(f, c, persona="<her Model info>")


def _fan_info(mode: str) -> dict:
    blocks = [_prompt(f"{q} (Noul)", s["instructions"], f"{_IJ}:STATED", items=_criteria(s["criteria"])
                      + [f"cut-off: {info.THRESHOLD}"], doc=_DOC["info"]) for q, s in info.STATED.items()]
    if full(mode):
        blocks += [_prompt(f"{q} (Noul) — wider wording", s["instructions"], f"{_IJ}:STATED_WIDE",
                           items=_criteria(s["criteria"]) + [f"cut-off: {info.THRESHOLD}"],
                           doc=_DOC["STATED_WIDE"], flag="info_wide") for q, s in info.STATED_WIDE.items()]
    blocks.append(_prompt("next_question (Choice) — old wording", info.NEXT_QUESTION["instructions"],
                          f"{_IJ}:NEXT_QUESTION", items=_criteria(info.NEXT_QUESTION["criteria"]),
                          doc=_DOC["info"]))
    if full(mode):
        blocks.append(_prompt("next_question (Choice) — lead-in wording, DRAFT",
                              info.NEXT_QUESTION_LEAD["instructions"], f"{_IJ}:NEXT_QUESTION_LEAD",
                              items=[f"never led: {', '.join(info.NEVER_LED)}"],
                              doc=_DOC["NEXT_QUESTION_LEAD"], flag="lead_in"))
    blocks += [
        _list("Ask list (wcfi still-need lines, info_questions list or the pick's line)", ask_lines(),
              f"{_WC}:_questions_still_needed"),
    ]
    if full(mode):
        blocks += [_list("Lead-in lines (replace the ask lines)",
                         [f"{k}: {v}" for k, v in writers.LEAD_LINES.items()], f"{_FW}:LEAD_LINES",
                         doc=_DOC["LEAD_LINES"], flag="lead_in"),
                   _prompt("Lead-in head (replaces the ask head)", writers.LEAD_HEAD, f"{_FW}:LEAD_HEAD",
                           doc=_DOC["LEAD_HEAD"], flag="lead_in")]
    blocks.append(_prompt("Ask head", writers.ASK_HEAD, f"{_FW}:ASK_HEAD"))
    sys_msg, user_msg = _extract_prompt()
    blocks += [
        _prompt(f"Extract system ({info.EXTRACT_MODEL})", sys_msg["content"], f"{_WC}:_EXTRACT_SYSTEM",
                doc=_DOC["_EXTRACT_SYSTEM"]),
        _prompt("Extract user (placeholders)", user_msg["content"], f"{_WC}:_extract_messages",
                doc=_DOC["_extract_messages"]),
    ]
    if full(mode):
        blocks.insert(-1, _prompt("Extract system addendum (he_likes, after the system above, with fetishes "
                                  "fired)", info.LIKES_EXTRACT, f"{_IJ}:LIKES_EXTRACT",
                                  doc=_DOC["LIKES_EXTRACT"], flag="he_likes"))
        blocks.insert(-1, _prompt("Extract system addendum (info_wide, with stated_hobbies fired)",
                                  info.HOBBIES_EXTRACT, f"{_IJ}:HOBBIES_EXTRACT",
                                  doc=_DOC["HOBBIES_EXTRACT"], flag="info_wide"))
    blocks.append(_table("Info Jev", [["setting", "value"], ["model", info.MODEL],
                                      ["extract model", info.EXTRACT_MODEL],
                                      ["state keys", ", ".join(info.STATE_KEYS)]]
                         + [[f"version ({k})", v] for k, v in info_versions(mode).items()], f"{_IJ}:info_version"))
    if mode == "shadow":
        blocks.insert(0, _note("Shadow", _SHADOW_NOTE, f"{_FT}:_info"))
    return _node("get_fan_info", "Get fan info", "info",
                 "On every speaking Turn Jev says which facts he just stated (the extract then reads "
                 "them) and, on chat, which ONE thing she asks next.",
                 blocks, ("info_questions", "info_fields", "lead_in", "he_likes", "info_wide"), mode)


def info_versions(mode: str) -> dict[str, str]:
    """`info_version(lead, likes, wide)` per flag combo the Mode can record (Shadow: never asks info)."""
    if not full(mode):
        return {}
    on = lambda x: "on" if x else "off"   # noqa: E731
    return {f"lead_in {on(a)}, he_likes {on(b)}, info_wide {on(c)}": info.info_version(a, b, c)
            for a in (False, True) for b in (False, True) for c in (False, True)}


# ── 5. What we store about him ─────────────────────────────────────────────

def _store(mode: str) -> dict:
    blocks = [
        _list("Facts (reply_json.fan_info, newest row wins)", list(wcfi._EXTRACT_FIELDS), f"{_WC}:_EXTRACT_FIELDS"),
        _list("Folded off the newest row's reply_json", ["fan_info", "asked", "typo_state", "scene"],
              f"{_TEST}:test_thread"),
        _table("Read off the Offer columns", [["fold", "what"],
                                              ["owned_of", "media he owns (bought or free) — never sold again"],
                                              ["sent_media_of", "media already sent this session"],
                                              ["bought_of / purchases_of", "his Buys, the price Jev's purchases"],
                                              ["open_offer_of", "a priced Offer with no outcome (haggle)"],
                                              ["pending_tease_of", f"a tease within {test_chat.TEASE_TTL_S} s"],
                                              ["spacing_of", f"Sitting counts; a gap over {test_chat.SITTING_GAP_S} s "
                                                             f"starts a new Sitting; unasked rows "
                                                             f"{', '.join(test_chat.UNASKED_ROWS)}"]],
               f"{_TEST}:owned_of"),
        _list("asked keys (count per topic, X then X:2)", list(wcfi._ASK_PRIORITY), f"{_WC}:_ASK_PRIORITY"),
    ]
    if full(mode):
        blocks.append(_list("Scene stages (reply_json.scene)", list(scene.STAGES),
                            "service/automations/full_ai_scene.py:STAGES", flag="sext_scene"))
    else:
        blocks.insert(0, _note("Shadow", "Shadow stores only the Decision row: no fan_info, asked or scene "
                               "fold yet (test Mode).", "service/automations/full_ai_chat.py"))
    return _node("store", "What we store about him", "store",
                 "Nothing is written to the Fan: every Turn's row carries the fold forward, and the next "
                 "Turn reads it back from the newest row and the Offer columns.",
                 blocks, ("info_fields",), mode)


# ── 6. Sell executor ───────────────────────────────────────────────────────

def _money(c: int) -> str:
    return price._dollars(c)


def _sell_node(mode: str) -> dict:
    lv = ", ".join(f"{k} {_money(v)}" for k, v in sell.LEVEL_CENTS.items())
    lanes = ", ".join(sell._LANE_CENTS)
    rules = [
        "Runs on sell_now and tease (both need sell_on), and make_right once he bought (the Free item).",
        f"Pool: the Content folders (include / exclude), no dupes, no unpriced item, partner content only "
        f"for {', '.join(sorted(sell._PARTNER_OK))}, nothing he owns.",
        f"Price lanes: {lanes}. Priced quotes stay within {_money(sell.MIN_CENTS)}–{_money(sell.MAX_CENTS)}; "
        "a Chat tease goes at its chat_tease_prices option (free allowed).",
        "Target by heat: " + ", ".join(f"intensity {i} → {_money(sell.target_cents(i))}" for i in range(5)) + ".",
        "A clip goes alone (unless he names a count, sell_count); a photo goes with its shoot mates; one free "
        "preview at most; a free item is his lowest unseen lane.",
        "Haggle: re-offers the open Offer's piece at his amount, clamped: e.g. list "
        + ", ".join(f"{_money(c)} → floor {_money(sell.clamp_quote(c, None))}" for c in (2000, 5000, 10000))
        + "; never above list.",
        "Refusal reasons: " + ", ".join(sell.Reason.__args__) + ".",
    ]
    blocks = [_list("Rules", rules, f"{_FS}:pick")]
    if full(mode):
        blocks += [_note("Content level (sext_scene)", f"The offer_level Choice targets: {lv}.",
                         f"{_FS}:LEVEL_CENTS", flag="sext_scene"),
                   _note("Nearest piece (sell_nearest)", "No match: same subject, then same format, then "
                         "anything; recorded as reply.nearest.", f"{_FS}:pick", flag="sell_nearest"),
                   _note("Fill the set (sell_bundle)", "fill: a fresh photo Offer holds up to 5 of its shoot "
                         "and fills to 3 from his ask; shoot: shoot mates only.", f"{_FS}:pick", flag="sell_bundle"),
                   _note("Asked count (sell_count)", f"He names a number (\"bundle of 5 videos\", at most "
                         f"{sell.COUNT_MAX}): a clip goes with up to that many matching clips at or under its price, "
                         f"listed at their sum (up to {_money(sell.MAX_CENTS)}); a filled photo set fills to it. "
                         "Fewer when there are fewer; recorded as reply.asked_count.", f"{_FS}:pick", flag="sell_count"),
                   _note("Chat tease (chat_tease)", "Row chat_tease, and an unasked offer in a normal chat "
                         "(row offer_moment, not hot): first the tease price Jev picks its price "
                         "from chat_tease_prices (see Price Jev); free is one unlocked photo, a price up to "
                         f"price / {_money(sell.TEASE_PHOTO_CENTS)} photos locked at it, attached to her ordinary "
                         "reply as a ride (photos only); the text does not mention them. The tease price Jev "
                         "failing sends no tease that Turn (plain chat); a text failing the Claim audit twice "
                         "goes out without the photos. Recorded as reply.chat_tease and reply.ride.",
                         f"{_FT}:_sell", flag="chat_tease")]
    else:
        blocks.insert(0, _note("Shadow", _SHADOW_NOTE, f"{_FT}:_sell"))
    return _node("sell", "Sell executor", "sell",
                 "Picks the one piece he gets (or a Refusal) from the vault, priced by his heat; the "
                 "Writer then sells or teases exactly that.",
                 blocks, ("sell_on", "folders", "sell_nearest", "sell_bundle", "sell_count", "sext_scene",
                          "chat_tease", "chat_tease_prices"), mode)


# ── 7. Price Jev ───────────────────────────────────────────────────────────

def _price_node(mode: str) -> dict:
    if not full(mode):
        blocks = [_note("Shadow", "The price Jev runs in test Mode with sext_scene only.", f"{_FT}:_price")]
    else:
        blocks = [_prompt("price (Score)", price.PRICE["instructions"], f"{_PJ}:PRICE",
                          items=_criteria(price.PRICE["criteria"]), doc=_DOC["PRICE"], flag="sext_scene"),
                  _list("Ladder", [_money(c) for c in price.PRICE_LADDER_CENTS], f"{_PJ}:PRICE_LADDER_CENTS"),
                  _list("State keys", list(price.STATE_KEYS), f"{_PJ}:STATE_KEYS"),
                  _table("Version", [["price_version"], [price.PRICE_VERSION]], f"{_PJ}:PRICE_VERSION")]
        opts = price.tease_options(config.DEFAULTS["chat_tease_prices"])
        blocks += [_prompt(f"{price.TEASE_QID} (Choice · DRAFT)", price.TEASE_PRICE["instructions"],
                           f"{_PJ}:TEASE_PRICE", items=_criteria(price._tease_criteria(opts))
                           + ["answer: the most probable option; any failure: no tease this Turn"],
                           doc=_DOC["TEASE_PRICE"], flag="chat_tease"),
                   _list("Tease price options (chat_tease_prices, default)", list(opts), f"{_CFG}:DEFAULTS",
                         flag="chat_tease"),
                   _list("Tease price state keys", list(price.TEASE_PRICE_STATE_KEYS),
                         f"{_PJ}:TEASE_PRICE_STATE_KEYS", flag="chat_tease"),
                   _table("Tease price version", [["tease_price_version"], [price.TEASE_PRICE_VERSION]],
                          f"{_PJ}:TEASE_PRICE_VERSION", flag="chat_tease")]
    return _node("price_jev", "Price Jev", "sell",
                 "On a fresh priced sell_now in a scene Jev picks the Offer price from the ladder; it "
                 f"replaces the list price (above or below it), clamped to {_money(sell.MIN_CENTS)}–"
                 f"{_money(sell.MAX_CENTS)} only. On a Chat tease Jev picks the tease's price from "
                 "chat_tease_prices before the pick.", blocks, ("sext_scene", "chat_tease", "chat_tease_prices"),
                 mode)


# ── 8. Writers ─────────────────────────────────────────────────────────────

def _facts(mode: str) -> SimpleNamespace:
    return SimpleNamespace(cut_rows=[], anchor_key="ai-rules", config=dict(config.DEFAULTS), fan_info={},
                           offer_piece=None, spent=[], mode=mode, next_question=None, ask_list=None)


def _pick() -> sell.Pick:
    return sell.Pick(ref=1, media=(1,), previews=(), price_cents=2000, list_cents=2000, subject="anything",
                     format="photo", lane="$10", facts={"description": "<what the piece shows>"})


def rendered(mode: str) -> list[tuple[str, str, list[dict]]]:
    """(label, row, messages) per Route, built by `messages_for` over a placeholder Fan."""
    f, pick = _facts(mode), _pick()
    out = [(r, "otherwise", writers.messages_for(r, "otherwise", 2, f, None))
           for r in ("chat", "sext", "ai_dare", "make_right")]
    out += [("sell_now", "sell", writers.messages_for("sell_now", "sell", 2, f, pick)),
            ("tease", "tease_price", writers.messages_for("tease", "tease_price", 2, f, pick)),
            ("chat (selling off)", "sell_off", writers.messages_for("chat", "sell_off", 2, f, None))]
    if full(mode):
        out.append(("sext (scene, building)", "sexual_now",
                    writers.messages_for("sext", "sexual_now", 2, f, None, scene="building")))
    return out


_SHARED = ("ROLE", "SELF_BAN", "READ_ALL", "HOW_YOU_TEXT", "EXPLICIT_EARLY", "CONTRACT", "CONTRACT_OFFER",
           "STICKER_EXCEPTION", "CALL_HIM", "REPLY_NOW", "KNOW_ENOUGH", "FAN_ASKED", "NO_SELL_OFFERS",
           "HIS_KINK", "NOTHING_ON_FILE", "BROKE_JOKE")
_BY_ROUTE = (("sext", ("SEXT_HOT", "SEXT_HEAT")), ("ai_dare", ("BRUSH_OFF", "DARE_NEXT", "DARE_JOIN", "DARE")),
             ("make_right", ("MAKE_RIGHT_HEAD", "MAKE_RIGHT_TAIL", "FREE_TERMS")),
             ("sell_now", ("CONTENT_ASK", "ESCALATION", "SELL_STEP", "CLOSE_BY_ID", "INTRO_BY_ID", "MANIFEST",
                           "ITEM_LINE", "TERMS", "PRICE_BLOCK", "WAS_PRICE_BLOCK", "FILMING_MORE")),
             ("tease", ("TEASE_GOAL", "ITEM_HEAD")), ("chat (selling off)", ("SELL_OFF_LINE",)))
# (constant, flag): the test-only wording, each riding one config key.
_FLAGGED = (("LEAD_HEAD", "lead_in"), ("LEAD_LINES", "lead_in"), ("LEAD_EXAMPLES", "lead_in"),
            ("SELF_GIVE", "lead_in"), ("NEAREST_NOTE", "sell_nearest"), ("SEXT_SCENE", "sext_scene"),
            ("SCENE_STAGE", "sext_scene"), ("SCENE_SELL", "sext_scene"), ("SCENE_NARRATION", "sext_scene"),
            ("SCENE_SELF", "sext_scene"), ("SELL_OFF_SCENE", "sext_scene"), ("RIDE_NOTE", "chat_tease"))
# Test Mode's twins of the old hot wording (off a scene Turn; no config key: Shadow keeps the old ones).
_TEST_TWINS = ("SEXT_HOT_TEST", "SELL_STEP_TEST", "ESCALATION_TEST", "MANIFEST_TEST")
# Test / live wording with no config key and no Shadow twin (a sell step Shadow never runs).
_FULL_ONLY = ("OFFER_OPEN",)


def _text(v: Any) -> str:
    if isinstance(v, dict):
        return "\n".join(f"{k}: {x}" for k, x in v.items())
    if isinstance(v, (tuple, list)):
        return "\n".join(str(x) for x in v)
    return str(v)


def _const(name: str, *, flag: str | None = None, route: str | None = None) -> dict:
    head = f"{route} · {name}" if route else name
    return _prompt(head, _text(getattr(writers, name)), f"{_FW}:{name}", doc=_DOC.get(name), flag=flag)


def _writers_node(mode: str) -> dict:
    cfg = config.DEFAULTS
    blocks = [
        _list("Writer order (first that passes wins)", list(cfg["writers"]), f"{_CFG}:DEFAULTS"),
        _table("Timing", [["setting", "value"], ["writer timeout (s)", cfg["writer_timeout_s"]],
                          ["per-model timeouts (s)", cfg["writer_timeouts"] or "none"],
                          ["retries per Writer (429 / 5xx / timeout)", cfg["writer_retries"]],
                          ["Turn bound (s)", config.turn_bound_s(cfg)]], f"{_CFG}:turn_bound_s"),
        _list("Code floor rejects", ["offer_ref", "bracket", "framework", "chevron", "cjk", "no_letters"],
              f"{_FW}:floor"),
    ]
    shown = rendered(mode)
    for label, row, msgs in shown:
        doc = _DOC["sell_now"] if label == "sell_now" else _DOC["chat"]
        blocks.append(_prompt(f"{label} — system (row {row}, placeholder Fan)", msgs[0]["content"],
                              f"{_FW}:messages_for", doc=doc))
    blocks.append(_prompt("User message (placeholder Fan)", shown[0][2][1]["content"],
                          f"{_FW}:_chat_user", doc=_DOC["chat"]))
    blocks += [_const(n) for n in _SHARED]
    blocks += [_const(n, route=r) for r, names in _BY_ROUTE for n in names]
    blocks += [_list("Apology frames (make_right)", list(writers.APOLOGY_FRAMES), f"{_FW}:APOLOGY_FRAMES",
                     doc=_DOC["MAKE_RIGHT_HEAD"]),
               _list("Style variants (one per Turn, seeded)", list(wcfi._STYLE_VARIANTS), f"{_WC}:_STYLE_VARIANTS"),
               _list("Breathers (no ask this Turn)", list(wcfi._BREATHER_VARIANTS), f"{_WC}:_BREATHER_VARIANTS"),
               _prompt("Shared rule: no narration", rules_txt.NO_NARRATION_RULE, "service/automations/_prompt_rules.py:NO_NARRATION_RULE"),
               _prompt("Shared rule: on platform", rules_txt.ONPLATFORM_GUARDRAIL, "service/automations/_prompt_rules.py:ONPLATFORM_GUARDRAIL"),
               _prompt("Shared rule: bio consistency", rules_txt.BIO_CONSISTENCY_GUARDRAIL,
                       "service/automations/_prompt_rules.py:BIO_CONSISTENCY_GUARDRAIL"),
               _prompt("Style: 3 lines", rules_txt.STYLE_3LINE, "service/automations/_prompt_rules.py:STYLE_3LINE"),
               _prompt("Style: brief", rules_txt.STYLE_BRIEF, "service/automations/_prompt_rules.py:STYLE_BRIEF"),
               _prompt("Caption apart (caption_writer caption)", writers.CAPTION_APART, f"{_FW}:CAPTION_APART",
                       doc=_DOC["CAPTION_APART"])]
    blocks += [_prompt(f"Caption system · {s}", caption.system(s), f"{_FC}:system", doc=_DOC["caption"])
               for s in caption.STYLES]
    blocks.append(_prompt("Caption free price block", caption.FREE_PRICE_BLOCK, f"{_FC}:FREE_PRICE_BLOCK",
                          doc=_DOC["FREE_PRICE_BLOCK"]))
    if full(mode):
        blocks += [_const(n, flag=k) for n, k in _FLAGGED]
        blocks += [_const(n, route=f"test Mode, replaces {n.removesuffix('_TEST')}") for n in _TEST_TWINS]
        blocks += [_const(n, route="sell_now (test and live)") for n in _FULL_ONLY]
    else:
        blocks.insert(0, _note("Shadow", _SHADOW_NOTE, f"{_FT}:run_turn"))
    return _node("writers", "Writers", "write",
                 "The Route's prompt goes to each Writer in order until one passes the code floor; the "
                 "PPV caption comes from the chat Writer or its own call (caption_writer).",
                 blocks, ("writers", "writer_timeout_s", "writer_timeouts", "writer_retries", "floor_on", "style", "gifs", "gif_pct", "caption_writer",
                          "lead_in", "sell_nearest", "sext_scene", "chat_tease"), mode)


# ── 9. Reply chain ─────────────────────────────────────────────────────────

def _chain(mode: str) -> dict:
    steps = ["finalize_draft — leak guard, emoji strip (strip_emojis, else the account's setting; "
             "service/automations/_finalize.py)",
             "_reply_shape.shape_parts — bubbles, banned words, u/ur, spacing, name protect",
             "apply_typo_throttle — thumb typos + *fix (style typos; typo_pct = % of replies, unset = ~1 per 5 sentences)",
             "hold_with_typing — the live transport's typing hold (test: full_ai_test.hold only)"]
    blocks = [_list("Shared chain, in order", steps, f"{_FT}:_chain"),
              _list("Claim audit (a Turn with a PPV)",
                    ["claim_ok: her text claims only what the piece holds",
                     "price_ok: any price she names is the Offer's",
                     "discloses: a piece not what he asked for is told as such (test and live)",
                     "one rewrite on the Writer that answered, else the fallback caption"], f"{_FT}:_claim_audit",
                    doc=_DOC["fallback_caption"]),
              _note("Docs", "Stages, order and gaps: docs/prompts/post-processing.md.", f"{_FT}:_chain")]
    if mode == "shadow":
        blocks.insert(0, _note("Shadow", _SHADOW_NOTE, f"{_FT}:_chain"))
    else:   # the Heat check runs wherever a Writer writes (spec 06); Shadow writes nothing
        blocks.insert(-1, _prompt(
            f"Heat check: {heat.QID} (Score)", heat.REPLY_LEVEL["instructions"],
            "service/automations/_heat_jev.py:REPLY_LEVEL", items=_criteria(heat.REPLY_LEVEL["criteria"])
            + ["a Route sext reply with text: her level above the Heat the Writer got -> one rewrite "
               "(same Writer, same messages), sent only if not over; else, or a failed check, the "
               "first text is sent", f"version: {heat.HEAT_VERSION}"],
            doc=_DOC["REPLY_LEVEL"], flag="floor_on"))
    return _node("reply_chain", "Reply chain", "write",
                 "Every model reply goes through the one shared chain before it reaches him; a reply "
                 "with a PPV is then audited against the piece.", blocks, ("style", "typo_pct", "floor_on", "strip_emojis"),
                 mode)


# ── 10. Send + record ──────────────────────────────────────────────────────

_JEV_KEYS = ("answers", "intensity", "fired", "state", "choices", "info_version", "info")
_SHADOW_JEV_KEYS = ("answers", "intensity", "fired", "state", f"photo (with {photo.KEY})")
_REPLY_KEYS = ("parts", "attempts", "floor_reason", "dropped_reason", "leak", "side", "config_rev", "wait_s",
               "turn_ms", "fan_info", "asked", "typo_state", "info_error", "fan_photo", "scene", "refusal",
               "level", "nearest", "price", "caption", "caption_fallback", "claim_fail", "offer_dropped",
               "chat_tease", "ride", "heat_check", "asked_count", "offer_open")


def _send(mode: str) -> dict:
    cols = [c.name for c in AiDecision.__table__.columns]
    blocks = [_list("ai_decisions columns", cols, "service/db/models.py:AiDecision")]
    if full(mode):
        blocks += [_list("jev_json keys", list(_JEV_KEYS), f"{_FT}:_route"),
                   _list("reply_json keys", list(_REPLY_KEYS), f"{_FT}:run_turn"),
                   _note("Send", "Test sends nothing to OnlyFans: full_ai_test.send writes the parts, the "
                         "PPV and the offer_* columns; record inserts the row.", f"{_TEST}:send")]
    else:
        blocks += [_list("jev_json keys", list(_SHADOW_JEV_KEYS), "service/automations/full_ai_chat.py"),
                   _note("Shadow", "Shadow inserts the row with status planned and sends nothing.",
                         "service/automations/full_ai_chat.py")]
    return _node("send_record", "Send + record", "store",
                 "One ai_decisions row per Turn holds the Route, the Jev answers, the reply and the Offer; "
                 "a fake Buy or Decline settles its outcome.", blocks, ("reply_speed",), mode)


# ── 11. Config switches ────────────────────────────────────────────────────

def _scope(k: str) -> str:
    return ("test + live (off in Shadow)" if k in TEST_ONLY_KEYS else "test + live + Shadow" if k in SHADOW_READS
            else "live only (catch-up schedule)" if k == "catchup_minutes"
            else "live only (who owns a Fan)" if k in LIVE_ONLY_KEYS else "test + live; Shadow ignores")


def _switches(mode: str) -> dict:
    rows = [["key", "label", "default", "scope"]]
    rows += [[k, _label(k), v, _scope(k)] for k, v in config.DEFAULTS.items()]
    keys = [k for k in config.DEFAULTS if full(mode) or k in SHADOW_READS]
    return {"id": "switches", "title": "Config switches", "group": "config",
            "summary": "Every key of a side's config with its default and where it counts; Shadow reads "
                       "only " + ", ".join(SHADOW_READS) + ".",
            "flags": [_flag(k) for k in keys],
            "blocks": [_table("DEFAULTS", rows, f"{_CFG}:DEFAULTS")]}


# ── assembly ───────────────────────────────────────────────────────────────

_SPEAKING = tuple(r for r in decide.Route.__args__ if r != "no_send")


def _edges(mode: str) -> list[dict[str, str]]:
    e = [("switches", "router_jev", "gates"), ("his_lines", "router_jev", "state"),
         ("router_jev", "route_table", "answers")]
    e += [("route_table", "send_record", "no_send")]
    e += [("route_table", "get_fan_info", r) for r in _SPEAKING]
    e += [("get_fan_info", "store", "fan_info, asked"),
          ("get_fan_info", "sell", "sell_now · tease · make_right"),
          ("get_fan_info", "writers", "chat · sext · ai_dare")]
    if full(mode):   # the price Jev is test-only
        e += [("sell", "price_jev", "fresh priced sell_now (scene) · Chat tease (before the pick)"),
              ("price_jev", "writers", "price")]
    e += [("sell", "writers", "Pick | Refusal"),
          ("writers", "reply_chain", "text"), ("reply_chain", "send_record", "parts"),
          ("send_record", "store", "row → next Turn's fold")]
    return [{"from": a, "to": b, "label": lbl} for a, b, lbl in e]


def rules(mode: str = "test") -> dict[str, Any]:
    """The page's whole payload for `mode` ("test" | "shadow" | "live"; live = test). Pure."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    nodes = [_his_lines(mode), _router(mode), _route_table(mode), _fan_info(mode), _store(mode),
             _sell_node(mode), _price_node(mode), _writers_node(mode), _chain(mode), _send(mode), _switches(mode)]
    versions = {"question_version": router.question_version(mode), "router_model": router.MODEL}
    if full(mode):
        d = config.DEFAULTS
        versions |= {"info_version": info.info_version(bool(d["lead_in"]), bool(d["he_likes"]),
                                                       bool(d["info_wide"])),
                     "price_version": price.PRICE_VERSION, "tease_price_version": price.TEASE_PRICE_VERSION}
    return {"mode": mode, "versions": versions, "nodes": nodes, "edges": _edges(mode)}
