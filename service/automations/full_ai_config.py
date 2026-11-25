from __future__ import annotations

import copy
import json
import re
from typing import Any

from automations.welcome_chatter_for_info import _EXTRACT_FIELDS
from llm_models import MODELS

INFO_FIELDS: tuple[str, ...] = _EXTRACT_FIELDS

DEFAULTS: dict[str, Any] = {
    "version": 1,
    "reply_speed": "0-2m",
    "style": {"texting": True, "nonnative": True, "spacing": True, "typos": True, "painful": True},
    "gifs": False,
    "sell_on": False,
    "sext_on": True,
    "sext_scene": True,
    "lead_in": True,
    "folders": {"include": [], "exclude": []},
    "draft_questions": True,
    "writers": ["euryale-v2.3", "euryale-v2.2", "hermes-4-405b", "deepseek-v4-flash"],
    "writer_timeout_s": 45,
    "writer_timeouts": {},
    "writer_retries": 0,
    "floor_on": True,
    "info_fields": list(INFO_FIELDS),
    "info_questions": "pick",
    "reply_by_webhook": True,
    "typing_sign": True,
    "typing_notification": True,
    "caption_writer": "chat",
    "sell_nearest": "note",
    "sell_bundle": "fill",
    "sell_count": True,
    "describe_fan_photos": True,
    "sell_spacing": True,
    "he_likes": True,
    "typo_pct": None,
    "gif_pct": None,
    "chat_tease": True,
    "chat_tease_prices": [0, 300, 1000, 4000, 8000, 12000, 16000, 20000],
    "ask_implied": True,
    "info_wide": True,
    "strip_emojis": False,
    "top_spend_cents": 100000,
    "fans": {"include": [], "exclude": []},
    "catchup_minutes": {"after_live": [0, 5, 15], "then_every": 15},
}


REPLY_SPEEDS: tuple[str, ...] = ("0-2m", "0-15-60")
TEXT_STYLES: tuple[str, ...] = ("girl", "formal")
STYLE_LAYERS: tuple[str, ...] = tuple(DEFAULTS["style"])
LEGACY_KEYS: tuple[str, ...] = ("text_style",)
RETIRED: dict[str, str] = {
    "chat_tease_rungs": "retired, renamed to chat_tease_prices: remove it",
    "offer_ride": "retired, folded into chat_tease: remove it",
}
RETIRED_KEYS: tuple[str, ...] = tuple(RETIRED)


def retired_errors(cfg: dict) -> list[str]:
    return [f"{k}: {RETIRED[k]}" for k in cfg if k in RETIRED]
INFO_QUESTIONS: tuple[str, ...] = ("pick", "list")
CAPTION_WRITERS: tuple[str, ...] = ("chat", "caption")
SELL_NEAREST: tuple[str, ...] = ("off", "plain", "note")
SELL_BUNDLE: tuple[str, ...] = ("shoot", "fill")
MAX_WRITERS = 6
WRITER_TIMEOUT_S = (5, 120)
WRITER_RETRIES = (0, 3)
TURN_BOUND_MAX_S = 900
WRITER_PROVIDERS: frozenset[str] = frozenset({"nanogpt", "openrouter", "zai", "deepseek"})
WRITER_EXTRA: frozenset[str] = frozenset({"euryale-v2.3-deepinfra"})


def is_writer(model_id: str) -> bool:
    m = MODELS.get(model_id)
    return m is not None and (m.provider in WRITER_PROVIDERS or model_id in WRITER_EXTRA)


WRITER_MODELS: list[str] = sorted(m for m in MODELS if is_writer(m))
FOLDER_REF = re.compile(r"(vf|of):[0-9]+")
_FOLDER_KEYS = ("include", "exclude")
_BOOLS = ("gifs", "sext_on", "sext_scene", "lead_in", "sell_on", "draft_questions", "floor_on", "reply_by_webhook", "typing_sign", "typing_notification",
          "describe_fan_photos", "sell_spacing", "he_likes", "chat_tease", "ask_implied",
          "info_wide", "sell_count", "strip_emojis")
TEASE_PRICES = (1, 12)
TEASE_CENTS = (300, 20000)
CATCHUP_PASSES = (1, 6)
CATCHUP_MAX_MIN = 1440
CATCHUP_EVERY_MIN = 5

_TEST = "Test chat + live (Shadow ignores). "
_BOOL = "true | false"
_PCT = "whole 0-100, or null"


def _one_of(values: tuple[str, ...]) -> str:
    return " | ".join(values)


def _ref(allowed: str, about: str, page: str | None = None) -> dict[str, str | None]:
    return {"allowed": allowed, "about": about, "page": page}


REFERENCE: dict[str, dict[str, str | None]] = {
    "version": _ref("1", "Config format version."),
    "reply_speed": _ref(_one_of(REPLY_SPEEDS), "How long she waits before replying.", "Reply speed"),
    "style": _ref("{" + ", ".join(STYLE_LAYERS) + "}, each true | false",
                  "The five human-texting layers: texting = lowercase short bubbles, nonnative = u/ur, spacing = a "
                  "space before ?/!, typos = thumb typos and a *fix bubble, painful = the painful-texting block.",
                  "Human style / Typos"),
    "gifs": _ref(_BOOL, "Sticker GIFs in her replies.", "GIFs"),
    "sell_on": _ref(_BOOL, "She offers PPVs from the content folders. Off: she never sells.", "Sell"),
    "sext_on": _ref(_BOOL, "Sexting. Off: she stays in normal chat.", "Sexting"),
    "sext_scene": _ref(_BOOL, _TEST + "The Jev-run sext scene (stages, content level, its own price Jev)."),
    "lead_in": _ref(_BOOL, _TEST + "Get-to-know questions are led into, not asked straight.", "Lead-in questions"),
    "folders": _ref(f"{{include: [refs], exclude: [refs]}}, a ref matches {FOLDER_REF.pattern}",
                    "Content folders she sells from. Empty include = all; exclude wins.", "Content folders"),
    "draft_questions": _ref(_BOOL, _TEST + "Unasked offers: she may send a PPV he did not ask for and answer "
                            "haggling with a new offer; in normal chat, with chat_tease on, it goes out as a chat "
                            "tease. Needs sell_on.", "Unasked offers"),
    "writers": _ref(f"1-{MAX_WRITERS} distinct Writer model ids; one Turn at most {TURN_BOUND_MAX_S} s",
                    "The Writer chain: the first writes, the rest are fallbacks in order.", "Writers"),
    "writer_timeout_s": _ref("{}-{} seconds".format(*WRITER_TIMEOUT_S),
                             "Seconds one Writer try may take; the fact extract gets the same limit. "
                             f"With the Writers' tries, one Turn stays within {TURN_BOUND_MAX_S} s."),
    "writer_timeouts": _ref("{{Writer model id: {}-{} seconds}}".format(*WRITER_TIMEOUT_S),
                            "Per-Writer override of writer_timeout_s. "
                            f"With the Writers' tries, one Turn stays within {TURN_BOUND_MAX_S} s."),
    "writer_retries": _ref("whole {}-{}".format(*WRITER_RETRIES),
                           "Retries of the same Writer on 429, 5xx or timeout before the next one. "
                           f"With the Writers' tries, one Turn stays within {TURN_BOUND_MAX_S} s."),
    "floor_on": _ref(_BOOL, "Reply checks: a reply that fails them is rejected and the next Writer tries; and the Heat check on a sext reply."),
    "info_fields": _ref("distinct, any of " + ", ".join(INFO_FIELDS), "The facts she tries to learn about him."),
    "info_questions": _ref(_one_of(INFO_QUESTIONS),
                           "pick = Jev picks one thing to ask; list = the old whole still-needed list.", "Questions"),
    "reply_by_webhook": _ref(_BOOL, "Live: on = his DM queues her reply at the reply speed; off = only the missed-message sweep answers."),
    "typing_sign": _ref(_BOOL, "Live: she waits her typing time before each text bubble. Off: no typing wait."),
    "typing_notification": _ref(_BOOL, "Live: OF shows her typing during that wait (the account's typing indicator must be on too). Off: never."),
    "caption_writer": _ref(_one_of(CAPTION_WRITERS),
                           "PPV caption: chat = the last bubble of her reply; caption = its own call.", "PPV caption"),
    "sell_nearest": _ref(_one_of(SELL_NEAREST), _TEST + "Nothing matches his ask: off = no PPV, plain = sell the "
                         "nearest piece, note = sell it and play his ask out as a story.", "Nearest piece"),
    "sell_bundle": _ref(_one_of(SELL_BUNDLE), _TEST + "fill = a photo offer holds up to 5 of its shoot, filled to 3 "
                        "with other photos matching his ask; shoot = shoot mates only, up to 4.", "Fill the set"),
    "sell_count": _ref(_BOOL, _TEST + "A fresh offer aims at the number he names (\"bundle of 5 videos\", at most 5): "
                       "a video goes with more of his asked videos priced at their sum (up to $200), a photo set "
                       "fills to it. Fewer when there are fewer.", "Match his count"),
    "describe_fan_photos": _ref(_BOOL, "She reads a photo he sends (one paid vision call per photo).", "Read his photos"),
    "sell_spacing": _ref(_BOOL, _TEST + "Unasked offers respect spacing: his lines since the last piece and pieces "
                         "this sitting.", "Spacing"),
    "he_likes": _ref(_BOOL, _TEST + "What he likes is stored and steers what she sends.", "He likes"),
    "typo_pct": _ref(_PCT, "Chance (%) a reply gets a typo while Typos is on. null = auto (about 1 per 5 "
                     "sentences).", "Typos %"),
    "gif_pct": _ref(_PCT, "Of the replies a GIF fits, the share (%) that send one. null = the Writer decides on each.",
                    "GIFs %"),
    "chat_tease": _ref(_BOOL, _TEST + "Chat tease: in normal chat photos ride her normal reply with no word about "
                       "them, free or at a price Jev picks from chat_tease_prices. An unasked offer in normal chat "
                       "goes out this way too. Needs sell_on.", "Chat tease"),
    "chat_tease_prices": _ref("{}-{} distinct cents, each 0 or {}-{}".format(*TEASE_PRICES, *TEASE_CENTS),
                              _TEST + "Prices in cents Jev may pick for a chat tease (0 = free). A price holds at "
                              "most price ÷ $5 photos, at least 1."),
    "ask_implied": _ref(_BOOL, _TEST + 'Implied asks ("send me something fun") count as asking for content.', "Implied asks"),
    "info_wide": _ref(_BOOL, _TEST + "What he is watching, playing, reading or listening to right now counts as a "
                      "hobby and is stored."),
    "strip_emojis": _ref(_BOOL, "Emojis are removed from her replies. The account's own strip-emojis setting "
                         "still applies when this is off.", "Strip emojis"),
    "top_spend_cents": _ref("whole cents >= 0, 0 = off",
                            "Live only. A Fan whose lifetime spend reaches this is left to humans: Full AI stops and "
                            "the other reply automations stay off him.", "Top spend limit"),
    "fans": _ref("{include: [OF list ids], exclude: [OF list ids]}",
                 "Live only. The Fans Full AI answers: on an include list (empty include = every Fan) and on no "
                 "exclude list. A list OF will not read leaves the Fan to the other automations.", "Fans"),
    "catchup_minutes": _ref("{{after_live: {}-{} ascending whole minutes 0-{}, then_every: whole minutes {}-{}}}".format(
                                *CATCHUP_PASSES, CATCHUP_MAX_MIN, CATCHUP_EVERY_MIN, CATCHUP_MAX_MIN),
                            "Live only. Waiting-chats catch-up: a pass at each after_live minute from Live (or relay "
                            "start + 1 min), then every then_every minutes. A saved change applies from the next wait."),
}


def reference() -> list[dict[str, Any]]:
    return [{"key": k, "default": copy.deepcopy(v), **REFERENCE[k]} for k, v in DEFAULTS.items()]


def limits() -> dict[str, Any]:
    return {"max_writers": MAX_WRITERS, "reply_speeds": list(REPLY_SPEEDS),
            "default_reply_speed": DEFAULTS["reply_speed"],
            "info_questions": list(INFO_QUESTIONS), "caption_writers": list(CAPTION_WRITERS)}


class StaleRev(Exception):

    def __init__(self, rev: int):
        super().__init__(rev)
        self.rev = rev


class Invalid(Exception):

    def __init__(self, errors: list[str]):
        super().__init__(errors)
        self.errors = errors


def _writers_error(ws: Any) -> str | None:
    if not isinstance(ws, list) or not all(isinstance(w, str) for w in ws):
        return "must be a list of model ids"
    if not 1 <= len(ws) <= MAX_WRITERS:
        return f"needs 1 to {MAX_WRITERS} Writers"
    if len(set(ws)) != len(ws):
        return "a Writer is listed twice"
    for w in ws:
        if w not in MODELS:
            return f"unknown model {w!r}"
        if not is_writer(w):
            return f"{w!r} runs on {MODELS[w].provider}, not a Writer provider ({', '.join(sorted(WRITER_PROVIDERS))})"
    return None


def _seconds_ok(t: Any) -> bool:
    lo, hi = WRITER_TIMEOUT_S
    return not isinstance(t, bool) and isinstance(t, (int, float)) and lo <= t <= hi


def _timeouts_error(ts: Any) -> str | None:
    if not isinstance(ts, dict):
        return "must be an object {model id: seconds}"
    for w, t in ts.items():
        if not is_writer(w):
            return f"{w!r} is not a Writer model"
        if not _seconds_ok(t):
            return "{!r}: must be a number of seconds from {} to {}".format(w, *WRITER_TIMEOUT_S)
    return None


def writer_timeout(cfg: dict, writer: str) -> float:
    return float((cfg.get("writer_timeouts") or {}).get(writer, cfg["writer_timeout_s"]))


def _folders_error(fs: Any) -> str | None:
    if not isinstance(fs, dict):
        return "must be an object {include, exclude}"
    if set(fs) != set(_FOLDER_KEYS):
        return f"want exactly include and exclude, got {sorted(fs)}"
    for k in _FOLDER_KEYS:
        refs = fs[k]
        if not isinstance(refs, list):
            return f"{k} must be a list of folder refs"
        for ref in refs:
            if not isinstance(ref, str) or not FOLDER_REF.fullmatch(ref):
                return f"bad ref {ref!r} in {k} (want vf:<id> or of:<id>)"
    return None


def _fans_error(fs: Any) -> str | None:
    if not isinstance(fs, dict):
        return "must be an object {include, exclude}"
    if set(fs) != set(_FOLDER_KEYS):
        return f"want exactly include and exclude, got {sorted(fs)}"
    for k in _FOLDER_KEYS:
        ids = fs[k]
        if not isinstance(ids, list):
            return f"{k} must be a list of OF list ids"
        for i in ids:
            if type(i) is not int or i <= 0:
                return f"bad id {i!r} in {k} (want an OF list id, a whole number)"
        if len(set(ids)) != len(ids):
            return f"an id is listed twice in {k}"
    return None


def catchup_error(cm: Any) -> str | None:
    (n0, n1), hi = CATCHUP_PASSES, CATCHUP_MAX_MIN
    if not isinstance(cm, dict) or set(cm) != {"after_live", "then_every"}:
        return "want exactly after_live and then_every"
    al, ev = cm["after_live"], cm["then_every"]
    if (not isinstance(al, list) or not n0 <= len(al) <= n1 or not all(type(m) is int and 0 <= m <= hi for m in al)
            or any(a >= b for a, b in zip(al, al[1:]))):
        return f"after_live must be {n0} to {n1} ascending whole minutes from 0 to {hi}"
    if type(ev) is not int or not CATCHUP_EVERY_MIN <= ev <= hi:
        return f"then_every must be whole minutes from {CATCHUP_EVERY_MIN} to {hi}"
    return None


def style_layers(cfg: dict) -> dict[str, bool]:
    ts, st = cfg.get("text_style"), cfg.get("style")
    if ts in TEXT_STYLES or not isinstance(st, dict):
        return dict.fromkeys(STYLE_LAYERS, ts == "girl")
    return {k: st.get(k) is True for k in STYLE_LAYERS}


def _style_error(st: Any) -> str | None:
    if not isinstance(st, dict) or set(st) != set(STYLE_LAYERS) or not all(isinstance(v, bool) for v in st.values()):
        return f"want exactly {', '.join(STYLE_LAYERS)}, each true or false"
    return None


def validate(cfg: Any) -> list[str]:
    if not isinstance(cfg, dict):
        return ["config: must be an object"]
    errs = [f"{k}: unknown key" for k in cfg if k not in DEFAULTS and k not in LEGACY_KEYS + RETIRED_KEYS]
    errs += retired_errors(cfg)
    c = {**DEFAULTS, **cfg}

    def bad(key: str, why: str) -> None:
        errs.append(f"{key}: {why}")

    if c["version"] != 1 or isinstance(c["version"], bool):
        bad("version", "must be 1")
    if c["reply_speed"] not in REPLY_SPEEDS:
        bad("reply_speed", f"must be one of {', '.join(REPLY_SPEEDS)}")
    if "text_style" in c and c["text_style"] not in TEXT_STYLES:
        bad("Human style", "must be on or off")
    if (why := _style_error(c["style"])) is not None:
        bad("style", why)
    if c["caption_writer"] not in CAPTION_WRITERS:
        bad("caption_writer", f"must be one of {', '.join(CAPTION_WRITERS)}")
    if c["sell_nearest"] not in SELL_NEAREST:
        bad("sell_nearest", f"must be one of {', '.join(SELL_NEAREST)}")
    if c["sell_bundle"] not in SELL_BUNDLE:
        bad("sell_bundle", f"must be one of {', '.join(SELL_BUNDLE)}")
    for k in _BOOLS:
        if not isinstance(c[k], bool):
            bad(k, "must be true or false")
    n_before = len(errs)
    if (why := _writers_error(c["writers"])) is not None:
        bad("writers", why)
    if not _seconds_ok(c["writer_timeout_s"]):
        bad("writer_timeout_s", "must be a number of seconds from {} to {}".format(*WRITER_TIMEOUT_S))
    if (why := _timeouts_error(c["writer_timeouts"])) is not None:
        bad("writer_timeouts", why)
    n, (lo, hi) = c["writer_retries"], WRITER_RETRIES
    if isinstance(n, bool) or not isinstance(n, int) or not lo <= n <= hi:
        bad("writer_retries", f"must be a whole number from {lo} to {hi}")
    if len(errs) == n_before and (b := turn_bound_s(c)) > TURN_BOUND_MAX_S:
        bad("writers", f"one Turn could take {round(b)} s (Jev {_JEV_STAGES_S} + extract + every Writer try); "
                       f"max {TURN_BOUND_MAX_S} s: fewer Writers or retries, or shorter timeouts")
    f = c["info_fields"]
    if (not isinstance(f, list) or len(set(map(str, f))) != len(f)
            or not all(isinstance(x, str) and x in INFO_FIELDS for x in f)):
        bad("info_fields", f"must be distinct fields of {', '.join(INFO_FIELDS)}")
    if c["info_questions"] not in INFO_QUESTIONS:
        bad("info_questions", f"must be one of {', '.join(INFO_QUESTIONS)}")
    if (why := _folders_error(c["folders"])) is not None:
        bad("folders", why)
    for k in ("typo_pct", "gif_pct"):
        p = c[k]
        if p is not None and (isinstance(p, bool) or not isinstance(p, int) or not 0 <= p <= 100):
            bad(k, "must be a whole percent from 0 to 100, or null")
    r, (n0, n1), (lo, hi) = c["chat_tease_prices"], TEASE_PRICES, TEASE_CENTS
    if (not isinstance(r, list) or not n0 <= len(r) <= n1
            or not all(type(x) is int and (x == 0 or lo <= x <= hi) for x in r) or len(set(r)) != len(r)):
        bad("chat_tease_prices", f"must be {n0} to {n1} distinct prices in cents, each 0 (free) or {lo} to {hi}")
    if type(c["top_spend_cents"]) is not int or c["top_spend_cents"] < 0:
        bad("top_spend_cents", "must be a whole number of cents, 0 or more (0 = off)")
    if (why := _fans_error(c["fans"])) is not None:
        bad("fans", why)
    if (why := catchup_error(c["catchup_minutes"])) is not None:
        bad("catchup_minutes", why)
    return errs


def side(cfg: dict | None) -> dict[str, Any]:
    c = {**copy.deepcopy(DEFAULTS), **{k: copy.deepcopy(v) for k, v in (cfg or {}).items()
                                       if k not in RETIRED_KEYS}}
    if c.get("text_style") in TEXT_STYLES:
        c["style"] = style_layers(c)
        del c["text_style"]
    return c


def merged(stored: dict | None) -> dict[str, Any]:
    stored = stored or {}
    checkpoint = side(stored.get("checkpoint"))
    return {
        "checkpoint": checkpoint,
        "previous": _audience_of(side(stored["previous"]), checkpoint) if stored.get("previous") else None,
        "draft": _audience_of(side(stored["draft"]), checkpoint) if stored.get("draft") else copy.deepcopy(checkpoint),
        "rev": int(stored.get("rev") or 0),
    }


def loaded(raw: str | None) -> dict[str, Any] | None:
    try:
        stored = json.loads(raw) if raw else {}
        return merged(stored) if isinstance(stored, dict) else None
    except (ValueError, TypeError, AttributeError, KeyError):
        return None


AUDIENCE_KEYS: tuple[str, ...] = ("fans", "top_spend_cents")


def _audience_of(cfg: dict, src: dict) -> dict[str, Any]:
    return {**cfg, **{k: copy.deepcopy(src[k]) for k in AUDIENCE_KEYS}}


def _no_audience(cfg: Any) -> Any:
    return {k: v for k, v in cfg.items() if k not in AUDIENCE_KEYS} if isinstance(cfg, dict) else cfg


def _check(cur: dict, rev: int) -> None:
    if rev != cur["rev"]:
        raise StaleRev(cur["rev"])


def put_draft(stored: dict | None, draft: Any, rev: int) -> dict[str, Any]:
    cur = merged(stored)
    _check(cur, rev)
    if errs := validate(_no_audience(draft)):
        raise Invalid(errs)
    return {**cur, "draft": _audience_of(side(_no_audience(draft)), cur["checkpoint"]), "rev": rev + 1}


def save(stored: dict | None, rev: int) -> dict[str, Any]:
    cur = merged(stored)
    _check(cur, rev)
    if errs := validate(cur["draft"]):
        raise Invalid(errs)
    if cur["draft"] == cur["checkpoint"]:
        raise Invalid(["Draft is the same as the Live settings: nothing to make live"])
    return {"checkpoint": cur["draft"], "previous": cur["checkpoint"],
            "draft": copy.deepcopy(cur["draft"]), "rev": rev + 1}


def put_checkpoint(stored: dict | None, cfg: Any, rev: int) -> dict[str, Any]:
    cur = merged(stored)
    _check(cur, rev)
    if errs := validate(_no_audience(cfg)):
        raise Invalid(errs)
    new = _audience_of(side(_no_audience(cfg)), cur["checkpoint"])
    if new == cur["checkpoint"]:
        raise Invalid(["Live settings: no change, nothing to save"])
    return {**cur, "checkpoint": new, "previous": cur["checkpoint"], "rev": rev + 1}


def rollback(stored: dict | None, rev: int) -> dict[str, Any]:
    cur = merged(stored)
    _check(cur, rev)
    if cur["previous"] is None:
        raise Invalid(["previous: nothing to roll back to"])
    return {**cur, "checkpoint": cur["previous"], "previous": cur["checkpoint"], "rev": rev + 1}


def put_audience(stored: dict | None, patch: dict[str, Any]) -> dict[str, Any]:
    if not patch:
        raise Invalid([f"audience: want one of {', '.join(AUDIENCE_KEYS)}"])
    if errs := [f"{k}: not an audience key" for k in patch if k not in AUDIENCE_KEYS] or validate(patch):
        raise Invalid(errs)
    cur = merged(stored)
    src = {**cur["checkpoint"], **copy.deepcopy(patch)}
    return {"checkpoint": _audience_of(cur["checkpoint"], src), "draft": _audience_of(cur["draft"], src),
            "previous": _audience_of(cur["previous"], src) if cur["previous"] is not None else None,
            "rev": cur["rev"] + 1}


_JEV_STAGES_S = 20


def turn_bound_s(cfg: dict) -> float:
    tries = 1 + int(cfg.get("writer_retries") or 0)
    return (_JEV_STAGES_S + cfg["writer_timeout_s"]
            + tries * sum(writer_timeout(cfg, w) for w in cfg["writers"]))
