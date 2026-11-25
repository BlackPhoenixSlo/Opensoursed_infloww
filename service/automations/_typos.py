from __future__ import annotations

import re
from datetime import datetime, timedelta

from db.engine import get_session
from db.models import Fan

from .fan_state import fan_state, put_fan_state
from ._prompt_rules import STYLE_MAX_BUBBLES
from ._textutil import _TYPO_EDGE_PUNCT, _WORD_RE


_TYPO_SENTENCE_RATE = 0.2
_TYPO_FIX_P_BASE = 0.25
_TYPO_FIX_P_UGLY = 0.55
_TYPO_FIX_MIN_WORD_LEN = 6
_SENT_RE = re.compile(r"[.!?]+")
_VOWELS = "aeiouAEIOU"


def _typo_eligible(word: str, protect: set[str]) -> bool:
    # Alpha-only: prices, ages, handles and links must never mutate.
    return len(word) >= 4 and word.isalpha() and word.lower() not in protect


def _mutate_word(word: str, rng) -> str | None:
    lo = word.lower()
    doubles = [i for i in range(len(lo) - 1) if lo[i] == lo[i + 1]]
    choice = rng.random()
    if doubles and choice < 0.25:
        i = rng.choice(doubles)
        out = word[:i] + word[i + 1:]
    elif choice < 0.65:
        idxs = list(range(1, len(word) - 1))
        if not idxs:
            return None
        i = rng.choice(idxs)
        out = word[:i] + word[i + 1] + word[i] + word[i + 2:]
    else:
        idxs = list(range(1, len(word) - 1))
        if not idxs:
            return None
        i = rng.choice(idxs)
        out = word[:i] + word[i + 1:]
    if out == word or len(out) < 3:
        return None
    return out


def _slip_is_ugly(orig: str, slipped: str) -> bool:
    o, s = orig.lower(), slipped.lower()
    if o[:2] != s[:2]:
        return True

    def _max_cons_run(w: str) -> int:
        run = best = 0
        for ch in w:
            run = run + 1 if (ch.isalpha() and ch not in _VOWELS) else 0
            best = max(best, run)
        return best

    return _max_cons_run(s) >= 3 and _max_cons_run(s) > _max_cons_run(o)


_TYPO_FIX_FORMS = (
    ("star_pre", 44),
    ("star_post", 20),
    ("star_lol", 16),
    ("omg_star", 10),
    ("retype", 10),
)


def _correction_bubble(word: str, rng) -> str:
    w = word.lower()
    total = sum(wt for _, wt in _TYPO_FIX_FORMS)
    pick = rng.random() * total
    acc = 0
    form = _TYPO_FIX_FORMS[0][0]
    for name, wt in _TYPO_FIX_FORMS:
        acc += wt
        if pick < acc:
            form = name
            break
    return {"star_pre": f"*{w}", "star_post": f"{w}*", "star_lol": f"*{w} lol",
            "omg_star": f"omg *{w}", "retype": w}[form]


def _humanize_typos_impl(parts: list[str], rng, *, protect=(),
                         max_bubbles: int = STYLE_MAX_BUBBLES,
                         allow_correction: bool = True,
                         reply_rate: float | None = None) -> tuple[list[str], bool]:
    parts = [p for p in parts if p and p.strip()]
    if not parts:
        return parts, False
    protect_set = {w.lower() for name in protect for w in _WORD_RE.findall(str(name))}

    if reply_rate is None:
        n_sent = sum(max(1, len(_SENT_RE.findall(p))) for p in parts)
        p_typo = min(1.0, n_sent * _TYPO_SENTENCE_RATE)
    else:
        p_typo = reply_rate
    if rng.random() >= p_typo:
        return list(parts), False

    # Whole tokens, not alpha runs: a word inside a handle/link/price ("@ava_xo", "$25") is never touched.
    cands = []
    for bi, p in enumerate(parts):
        for m in re.finditer(r"\S+", p):
            tok = m.group()
            core = tok.strip(_TYPO_EDGE_PUNCT)
            lead = len(tok) - len(tok.lstrip(_TYPO_EDGE_PUNCT))
            if _typo_eligible(core, protect_set):
                cands.append((bi, m.start() + lead, m.start() + lead + len(core), core))
    if not cands:
        return list(parts), False

    bi, start, end, word = rng.choice(cands)
    slipped = _mutate_word(word, rng)
    if slipped is None:
        return list(parts), False

    out = list(parts)
    out[bi] = out[bi][:start] + slipped + out[bi][end:]

    fix_p = _TYPO_FIX_P_UGLY if _slip_is_ugly(word, slipped) else _TYPO_FIX_P_BASE
    emitted = False
    # rng draw stays first so seeded callers keep their draw order; the guards only suppress the emit.
    if (allow_correction and len(out) < max_bubbles and rng.random() < fix_p
            and len(word) >= _TYPO_FIX_MIN_WORD_LEN):
        out.append(_correction_bubble(word, rng))
        emitted = True
    return out, emitted


def humanize_typos(parts: list[str], rng, *, protect=(),
                   max_bubbles: int = STYLE_MAX_BUBBLES, reply_rate: float | None = None) -> list[str]:
    return _humanize_typos_impl(parts, rng, protect=protect, max_bubbles=max_bubbles,
                                reply_rate=reply_rate)[0]


_TYPO_FIX_MIN_INTERVAL = timedelta(hours=1)
_TYPO_FIX_MIN_EXCHANGES = 50
_TYPO_FIX_STATE_KEY = "_typo_fix"


def _typo_correction_allowed(state: dict, now: datetime) -> bool:
    last_raw = state.get("at")
    if not last_raw:
        return True
    try:
        last = datetime.fromisoformat(last_raw)
    except Exception:
        return True
    since = int(state.get("since", 0) or 0)
    return (now - last) >= _TYPO_FIX_MIN_INTERVAL or since >= _TYPO_FIX_MIN_EXCHANGES


def _throttled(state: dict, parts, rng, now: datetime, *, protect, max_bubbles,
               reply_rate: float | None = None) -> tuple[list[str], dict]:
    out, emitted = _humanize_typos_impl(
        parts, rng, protect=protect, max_bubbles=max_bubbles,
        allow_correction=_typo_correction_allowed(state, now), reply_rate=reply_rate)
    return out[:max_bubbles], ({"at": now.isoformat(), "since": 0} if emitted else
                               {"at": state.get("at"),
                                "since": int(state.get("since", 0) or 0) + 1})


async def apply_typo_throttle(account_id, fan_id, parts, rng, *, protect=(),
                              max_bubbles: int = STYLE_MAX_BUBBLES,
                              state: dict | None = None,
                              reply_rate: float | None = None) -> list[str]:
    # The fan lease gives one sender per fan per tick, so this read-modify-write needs no lock.
    now = datetime.utcnow()
    if state is not None:
        out, nxt = _throttled(state, parts, rng, now, protect=protect, max_bubbles=max_bubbles,
                              reply_rate=reply_rate)
        state.clear()
        state.update(nxt)
        return out
    async with get_session() as s:
        fan = await s.get(Fan, (str(account_id), int(fan_id)))
        cur = fan_state(fan, _TYPO_FIX_STATE_KEY)
        out, nxt = _throttled(cur, parts, rng, now, protect=protect, max_bubbles=max_bubbles,
                              reply_rate=reply_rate)
        if fan is not None:
            put_fan_state(fan, _TYPO_FIX_STATE_KEY, nxt)
            await s.commit()
    return out
