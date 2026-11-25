from __future__ import annotations

import re

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(s: str | None) -> str:
    if not s:
        return ""
    if "<" not in s:
        return s.strip()
    return _TAG_RE.sub("", s).strip()


def step_number_index(steps: list[dict]) -> dict[int, int]:
    out: dict[int, int] = {}
    for i, st in enumerate(steps):
        try:
            out[int(st.get("step"))] = i
        except (TypeError, ValueError):
            continue
    return out


def _keyword_hit(word: str, text_cf: str) -> bool:
    w = str(word).strip().casefold()
    if not w:
        return False
    return re.search(r"\b" + re.escape(w) + r"\b", text_cf) is not None


def resolve_next(step: dict, facts, num_to_idx: dict[int, int], cur_idx: int) -> int:
    nxt = step.get("next")
    if not isinstance(nxt, dict):
        return cur_idx + 1

    def _idx(target) -> int:
        try:
            return num_to_idx.get(int(target), cur_idx + 1)
        except (TypeError, ValueError):
            return cur_idx + 1

    kw = nxt.get("keyword")
    if isinstance(kw, dict) and facts.substantive:
        text_cf = strip_html(facts.reply_text).casefold()
        # Precedence: keyword > bought > ignored > default > +1; only a substantive reply trips a keyword.
        for word, target in kw.items():
            if _keyword_hit(word, text_cf):
                return _idx(target)
    if facts.bought and nxt.get("bought") is not None:
        return _idx(nxt.get("bought"))
    if not facts.replied and nxt.get("ignored") is not None:
        return _idx(nxt.get("ignored"))
    if nxt.get("default") is not None:
        return _idx(nxt.get("default"))
    return cur_idx + 1
