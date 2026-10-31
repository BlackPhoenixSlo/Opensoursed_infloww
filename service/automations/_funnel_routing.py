"""service/automations/_funnel_routing.py — branching-storyline routing for
reply_mass_funnel.

The PURE step-graph logic split out of the walker: strip a reply to plain text,
map step NUMBERS→list indices and choose the next step from the fan's reply facts.
No DB, no OF, no LLM. The loop-guarded hop that (re)schedules a fan is
funnel_decide's (the walk's status machine); the walker owns all I/O.

Kept separate so reply_mass_funnel stays a readable size and the routing rules
(precedence, +1 fallback) can be read and tested in isolation.

Branching contract (funnels_api validates the shape + target existence)::
    {"next": {"bought": 5, "ignored": 2, "keyword": {"more": 3}, "default": 3}}
Targets are step NUMBERS (the `step` field); resolve_next maps them to LIST
INDICES via `step_number_index`. ABSENT `next` → the classic current_step + 1
advance, so every existing (linear) funnel behaves exactly as before.
"""
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
    """Map each step's declared `step` NUMBER → its INDEX in the list. A funnel
    numbers steps from 1; the walker drives by index, so `next` targets (step
    numbers) resolve through this."""
    out: dict[int, int] = {}
    for i, st in enumerate(steps):
        try:
            out[int(st.get("step"))] = i
        except (TypeError, ValueError):
            continue
    return out


def _keyword_hit(word: str, text_cf: str) -> bool:
    """Case-insensitive WORD match of `word` inside already-casefolded `text_cf`
    (a whole-word boundary so 'no' doesn't fire on 'now'). Blank word → no hit."""
    w = str(word).strip().casefold()
    if not w:
        return False
    return re.search(r"\b" + re.escape(w) + r"\b", text_cf) is not None


def resolve_next(step: dict, facts, num_to_idx: dict[int, int], cur_idx: int) -> int:
    """The NEXT step INDEX for `step`, chosen from the fan's `facts` (a
    funnel_decide.Facts: .replied / .bought / .substantive / .reply_text). Precedence (spec):
        keyword match > bought > ignored(didn't reply) > default > (+1 fallback)
    A missing/blank `next`, or a target naming an unknown step, yields the linear
    cur_idx + 1 — so a funnel with no `next` walks exactly as it did before."""
    nxt = step.get("next")
    if not isinstance(nxt, dict):
        return cur_idx + 1

    def _idx(target) -> int:
        try:
            return num_to_idx.get(int(target), cur_idx + 1)
        except (TypeError, ValueError):
            return cur_idx + 1

    # 1) keyword — first matching key wins. Only a SUBSTANTIVE reply (real text,
    #    not a lone reaction — is_substantive_msg) can trip a keyword branch.
    kw = nxt.get("keyword")
    if isinstance(kw, dict) and facts.substantive:
        text_cf = strip_html(facts.reply_text).casefold()
        for word, target in kw.items():
            if _keyword_hit(word, text_cf):
                return _idx(target)
    # 2) bought — the fan unlocked a PPV since the baseline (#30 signal).
    if facts.bought and nxt.get("bought") is not None:
        return _idx(nxt.get("bought"))
    # 3) ignored — no reply in the window.
    if not facts.replied and nxt.get("ignored") is not None:
        return _idx(nxt.get("ignored"))
    # 4) default.
    if nxt.get("default") is not None:
        return _idx(nxt.get("default"))
    # 5) linear fallback.
    return cur_idx + 1
