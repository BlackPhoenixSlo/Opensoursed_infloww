from __future__ import annotations

import random
import re

# equals _inbound.MSG_CLIP, literal so this module stays DB-free; test_bubbles pins them equal
_MSG_CLIP = 400

_EMOJI = "[\U0001F300-\U0001FAFF\U00002600-\U000027BF❤]️?"
_EMOJI_RE = re.compile(_EMOJI)
_TRAIL_EMOJI_RE = re.compile(_EMOJI + r"\s*$")
_DASH_RE = re.compile(r"\s*[—–]\s*|\s*--\s*|\s+-\s+")
_DASH_CLEAN_RE = re.compile(r"\s*[—–]\s*")


def _strip_dash(s: str) -> str:
    return _DASH_CLEAN_RE.sub(", ", s).strip().rstrip(",").strip()


_REACTIONS = (r"oo+f|lo+l|lma+o|omg|ha+ha+|hah|mm+|mhm+|ugh|hmm+|aw+|damn|stop|oh|yo|"
              r"wait|bet|nice|fair|true|lowkey|ok|okay|yeah|yep|nah")
_LEAD_REACT_RE = re.compile(rf"^({_REACTIONS})\b[,!.]*\s+", re.I)
_REACT_WORD_RE = re.compile(rf"^({_REACTIONS})\b", re.I)
_SENT_SPLIT_RE = re.compile(r"(?<=[.?!])\s+|\s*,\s*|\s*[—–]\s*|\s*--\s*|\s+-\s+")


_WH_RE = re.compile(r"\b(what|whats|where|when|who|why|which|how)\b", re.I)
_LONG_CHUNK = 40
_WH_MIN_LEAD_WORDS = 4


def _split_emoji_wh(seg: str) -> list[str]:
    seg = seg.strip()
    if not seg:
        return []
    if len(seg) <= _LONG_CHUNK:
        return [seg]
    for m in _EMOJI_RE.finditer(seg):
        before, after = seg[:m.end()].strip(), seg[m.end():].strip()
        if before and after:
            return [before] + _split_emoji_wh(after)
    for m in _WH_RE.finditer(seg):
        if m.start() == 0:
            continue
        before, after = seg[:m.start()].strip().rstrip(","), seg[m.start():].strip()
        if before and after and len(before.split()) >= _WH_MIN_LEAD_WORDS:
            return [before] + _split_emoji_wh(after)
    return [seg]


def _split_units(text: str) -> list[str]:
    out: list[str] = []
    for chunk in _SENT_SPLIT_RE.split(text.strip()):
        for sub in _split_emoji_wh(chunk):
            if sub.endswith("."):
                sub = sub[:-1].strip()
            if sub:
                out.append(sub)
    return out


def _cap_merge(parts: list[str], max_bubbles: int) -> list[str]:
    if len(parts) > max_bubbles:
        return parts[:max_bubbles - 1] + [" ".join(parts[max_bubbles - 1:])]
    return parts


_HAS_WORD_RE = re.compile(r"[A-Za-z0-9]")


def _merge_orphans(parts: list[str]) -> list[str]:
    out: list[str] = []
    for p in parts:
        if out and not _HAS_WORD_RE.search(p):
            out[-1] = (out[-1] + " " + p).strip()
        else:
            out.append(p)
    return out


def _casual_join(parts: list[str]) -> str:
    out = (parts[0] or "").strip()
    for p in parts[1:]:
        p = (p or "").strip()
        if not p:
            continue
        sep = " " if out.rstrip().endswith(("?", "!", ".", "…")) else ", "
        out = out.rstrip() + sep + p
    return out


def _target_bubbles(words: int) -> int:
    if words <= 4:
        return 1
    if words <= 9:
        return 2
    if words <= 15:
        return 3
    return 4


def _group_to_target(units: list[str], target: int) -> list[str]:
    n = len(units)
    if target <= 1:
        return [_casual_join(units)] if units else []
    if target >= n:
        return units
    base, rem = divmod(n, target)
    sizes = [base] * (target - rem) + [base + 1] * rem
    out, i = [], 0
    for s in sizes:
        out.append(_casual_join(units[i:i + s]))
        i += s
    return out


def _break_units(text: str) -> list[str]:
    units: list[str] = []
    for line in text.split("\n"):
        units.extend(_split_units(line))
    return _cap_one_question(_merge_orphans(units))


_SPLIT_STRATEGIES = ("length", "clause", "terse")
_SPLIT_WEIGHTS = (58, 22, 20)


def _strategy_target(parts: list[str], max_bubbles: int, rng) -> int:
    n = max(1, len(parts))
    strat = rng.choices(_SPLIT_STRATEGIES, weights=_SPLIT_WEIGHTS)[0]
    if strat == "clause":
        target = n
    elif strat == "terse":
        target = min(2, n)
    else:
        target = _target_bubbles(sum(len(p.split()) for p in parts))
    return max(1, min(target, max_bubbles, n))


def _split_sentences(text: str, max_bubbles: int) -> list[str]:
    return _cap_merge(_merge_orphans(_split_units(text)), max_bubbles)


_QMARK_TAIL_RE = re.compile(r"\s*\?+\s*$")


def _cap_one_question(parts: list[str]) -> list[str]:
    q_idx = [i for i, p in enumerate(parts) if p.rstrip().endswith("?")]
    if len(q_idx) <= 1:
        return parts
    keep = q_idx[-1]
    return [(_QMARK_TAIL_RE.sub("", p) if (i in q_idx and i != keep) else p)
            for i, p in enumerate(parts)]


def _react_token(s: str) -> str | None:
    m = _REACT_WORD_RE.match((s or "").strip())
    if not m:
        return None
    return re.sub(r"(.)\1+", r"\1", m.group(1).lower())


def _dedupe_lead_reaction(parts: list[str], recent_out: list[str]) -> list[str]:
    if not parts:
        return parts
    recent = {t for b in recent_out[-3:] if (t := _react_token(b))}
    if not recent:
        return parts
    tok = _react_token(parts[0])
    if not tok or tok not in recent:
        return parts
    if len(parts) > 1:
        return parts[1:]                              # drop the standalone "oof"
    m = _LEAD_REACT_RE.match(parts[0].strip())        # fused → strip just the opener
    rest = parts[0].strip()[m.end():].strip() if m else ""
    return [rest] if rest else parts


def split_for_bubbles(text: str, max_bubbles: int = 2, rng=None,
                      force_single: bool = False) -> list[str]:
    """Make one generated reply read like real texting, and NO em-dash ever survives
    (every return path runs _strip_dash). Non-style mode caps the number of lines:

      • style mode (max_bubbles ≥ 3) → walk the model's OWN line breaks, then split
        each line on commas + sentence boundaries + dash + (for a long chunk) emoji /
        WH word. A per-reply STRATEGY randomiser (_strategy_target) then picks the
        bubble count — length-based / split-every-clause / terse — so replies don't
        all chop the same way.
      • non-style (cap 2) → the model's two-line style, else a single dash / a
        MID-LINE emoji break (2/3 of the time), else a trailing-emoji drop (1/3).

    EVERY random draw on both paths goes through `rng`, so passing one seeded off
    the reply (the senders use `Random(f"split:{fan_id}:{raw}")`) makes the split
    stable — the same draft re-run after a retry bubbles the same way.
    """
    _rng = rng if rng is not None else random
    text = text.strip()
    # Not max_bubbles=1 (non-style path truncates, drops content); merge instead. Humans return single-bubble ~64% at every gap length.
    if force_single and text:
        units = _break_units(text)
        return [_strip_dash(_casual_join(units) if units else text)]
    if max_bubbles >= 3:                         # STYLE MODE
        parts = _break_units(text)
        parts = _group_to_target(parts, _strategy_target(parts, max_bubbles, _rng))
        if parts:
            return [_strip_dash(p) for p in parts]
    if "\n" in text:
        parts = [p.strip() for p in text.split("\n") if p.strip()][:max_bubbles]
        return [_strip_dash(p) for p in parts] or [_strip_dash(text)]
    dm = _DASH_RE.search(text)
    if dm:
        before, after = text[:dm.start()].strip(), text[dm.end():].strip()
        if before and after:
            return [_strip_dash(before), _strip_dash(after)]
    if _rng.random() < (2.0 / 3.0):
        for m in _EMOJI_RE.finditer(text):
            after = text[m.end():].strip()
            if not after:
                continue
            before = text[:m.end()].strip()
            if _rng.random() < 0.5:
                before = text[:m.start()].strip()
            if before:
                return [_strip_dash(before), _strip_dash(after)]
    if _rng.random() < (1.0 / 3.0):
        stripped = _TRAIL_EMOJI_RE.sub("", text).strip()
        if stripped and stripped != text:
            return [_strip_dash(stripped)]
    return [_strip_dash(text)]


_ECHO_NORM_RE = re.compile(r"[^a-z0-9]+")


def _norm_echo(s: str) -> str:
    return _ECHO_NORM_RE.sub("", (s or "").lower())


def _looks_like_echo(part: str, last_in: str) -> bool:
    a, b = _norm_echo(part), _norm_echo(last_in)
    if len(a) < 12 or len(b) < 12:
        return False
    if a == b:
        return True
    lo, hi = (a, b) if len(a) <= len(b) else (b, a)
    return lo in hi and len(lo) / len(hi) >= 0.7


_HTML_OPEN = "<"
_TAG_RE = re.compile(r"<[^>]+>")



def _strip_html(s: str | None) -> str:
    if not s:
        return ""
    if _HTML_OPEN not in s:
        return s.strip()
    return _TAG_RE.sub("", s).strip()


def _history_text(direction: str, body: str | None, image_desc: str | None) -> str:
    text = _strip_html(body)[:_MSG_CLIP]
    if direction == "in" and image_desc:
        tag = f"[he sent: {image_desc}]"
        text = f"{text} {tag}" if text else tag
    return text
