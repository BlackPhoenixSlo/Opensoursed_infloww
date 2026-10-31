"""Thumb-typo humanizer + *fix throttle."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from db.engine import get_session
from db.models import Fan

# The per-fan state blob lives in its own leaf module — see fan_state.py for why
# storage does not belong in here. apply_typo_throttle below is a consumer like
# any other; this is NOT a re-export, so importers go to the leaf directly.
from .fan_state import fan_state, put_fan_state
from ._prompt_rules import STYLE_MAX_BUBBLES
from ._textutil import _TYPO_EDGE_PUNCT, _WORD_RE


# ── "Hard" thumb-typo injector (opt-in, deterministic) ────────────────
# Prompt-only typos are unreliable (the model ignores or over-clusters them, and
# reasoning models "fix" them). This is the CODE-level injector: at most ONE
# realistic phone slip across a reply, ~1 per 5 sentences, and SOMETIMES a
# follow-up "*fix" bubble — the strongest not-a-bot tell. Pure + seeded so it's
# reproducible and testable; OFF unless the caller opts in.
#
# Only readable, meaning-preserving slips (transpose / drop / double-collapse) —
# never a wrong-word "autocorrect". PROTECTED tokens never mutate: anything with
# a digit (prices/ages/times), @handle, link, $, emoji, or a name passed in
# `protect`. Corrupting a price or the fan's name is worse than no typo at all.
_TYPO_SENTENCE_RATE = 0.2        # ~1 typo per 5 sentences (capped at 1 / reply)
# Of the typos that slip in, how many get a self-correct bubble — SEVERITY-WEIGHTED:
# a subtle slip (one dropped letter mid-word) usually rides; an ugly, hard-to-read
# garble gets fixed more often, the way a real person notices the bad ones.
_TYPO_FIX_P_BASE = 0.25          # subtle slip → usually leave it
_TYPO_FIX_P_UGLY = 0.55          # obviously-wrong slip → more likely to "*fix"
# Don't bother "*fix"-ing a SHORT word: a slip in a <6-char word (lol, ur, gonna,
# hey, babe) is instantly guessable, so a real person wouldn't correct it — and a
# "*lol" correction on something that obvious reads like a bot. The thumb-slip
# itself still rides; only the follow-up correction bubble is suppressed.
_TYPO_FIX_MIN_WORD_LEN = 6
_SENT_RE = re.compile(r"[.!?]+")
_VOWELS = "aeiouAEIOU"


def _typo_eligible(word: str, protect: set[str]) -> bool:
    """A word a real thumb would slip on: ≥4 letters, all-alpha, not a name."""
    return len(word) >= 4 and word.isalpha() and word.lower() not in protect


def _mutate_word(word: str, rng) -> str | None:
    """One readable slip on a single word. None if no valid mutation found.
    transpose: could→coudl · drop: really→realy · double-collapse: gonna→gona."""
    lo = word.lower()
    # double-collapse first when a double exists (most natural-looking)
    doubles = [i for i in range(len(lo) - 1) if lo[i] == lo[i + 1]]
    choice = rng.random()
    if doubles and choice < 0.25:
        i = rng.choice(doubles)
        out = word[:i] + word[i + 1:]
    elif choice < 0.65:                                  # adjacent transpose
        # interior pairs only (don't flip the first letter — too jarring)
        idxs = list(range(1, len(word) - 1))
        if not idxs:
            return None
        i = rng.choice(idxs)
        out = word[:i] + word[i + 1] + word[i] + word[i + 2:]
    else:                                                # drop one interior letter
        idxs = list(range(1, len(word) - 1))
        if not idxs:
            return None
        i = rng.choice(idxs)
        out = word[:i] + word[i + 1:]
    if out == word or len(out) < 3:
        return None
    return out


def _slip_is_ugly(orig: str, slipped: str) -> bool:
    """Does the slip read obviously-wrong at a glance (→ likelier to get fixed)?
    Two cheap eye-catches: the word START reordered (we read first letters first),
    or a NEW 3+ consonant run the original didn't have ('really'→'rae lly' style)."""
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


# The correction bubble varies its SHAPE so the literal "*word" isn't itself a bot
# signature — weighted across the ways a real person fixes a typo. Seeded via rng.
_TYPO_FIX_FORMS = (
    ("star_pre", 44),    # *word
    ("star_post", 20),   # word*
    ("star_lol", 16),    # *word lol
    ("omg_star", 10),    # omg *word  (names the word — never a bare "omg typo")
    ("retype", 10),      # word       (just retype it, no marker)
)


def _correction_bubble(word: str, rng) -> str:
    """One varied self-correct bubble for `word` (already lowercased on use). Every
    form names the actual word being fixed — no generic 'omg typo' filler (it reads
    like a bot and corrects nothing)."""
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
                         allow_correction: bool = True) -> tuple[list[str], bool]:
    """Core injector → (new_parts, correction_emitted). At most one thumb-typo across
    `parts`, rate ~1 per 5 sentences, and SOMETIMES a '*fix' correction bubble. Pure:
    takes an explicit `rng` (random.Random) — caller seeds it off (fan_id, text) for
    reproducibility. When `allow_correction` is False the thumb-slip still rides but
    the '*fix' bubble is suppressed (the per-fan throttle path); the True branch keeps
    the original RNG draw order so seeded callers stay byte-identical."""
    parts = [p for p in parts if p and p.strip()]
    if not parts:
        return parts, False
    protect_set = {w.lower() for name in protect for w in _WORD_RE.findall(str(name))}

    # sentences across the whole reply → P(one typo) = min(1, n * rate)
    n_sent = sum(max(1, len(_SENT_RE.findall(p))) for p in parts)
    if rng.random() >= min(1.0, n_sent * _TYPO_SENTENCE_RATE):
        return list(parts), False

    # collect eligible words across all bubbles, pick one. Scan WHOLE
    # whitespace-tokens (not bare alpha runs) so a word embedded in a handle /
    # link / price ("@ava_xo", "onlyfans.com/ava", "$25") is never touched —
    # the token's core must be purely alphabetic after stripping edge punctuation.
    cands = []  # (bubble_idx, core_start, core_end, word)
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

    # self-correct: a beat later, a "*fix" bubble (the strongest not-a-bot tell).
    # Fires whenever there's ROOM under the bubble cap — a 1-bubble reply becomes 2,
    # a 2-bubble reply becomes 3 — but NEVER a stray 4th: if the reply is already at
    # max_bubbles, the "*word" would be a bubble too far (out of place), so we skip.
    # Chance is severity-weighted (ugly garbles get fixed more) and the SHAPE varies
    # so the literal "*word" isn't itself a tell. `allow_correction` short-circuits
    # FIRST so a throttled reply never consumes the fix RNG draw — the allowed path's
    # draw order is unchanged.
    fix_p = _TYPO_FIX_P_UGLY if _slip_is_ugly(word, slipped) else _TYPO_FIX_P_BASE
    emitted = False
    # NOTE: the `rng.random() < fix_p` draw stays FIRST so seeded callers keep their
    # exact draw order; the short-word guard is an extra AND after it (short-circuit
    # only suppresses the emit, never skips the draw) — see _TYPO_FIX_MIN_WORD_LEN.
    if (allow_correction and len(out) < max_bubbles and rng.random() < fix_p
            and len(word) >= _TYPO_FIX_MIN_WORD_LEN):
        out.append(_correction_bubble(word, rng))
        emitted = True
    return out, emitted


def humanize_typos(parts: list[str], rng, *, protect=(),
                   max_bubbles: int = STYLE_MAX_BUBBLES) -> list[str]:
    """Back-compat wrapper returning just the bubble list (drops the emitted flag).
    Callers that need the per-fan '*fix' throttle use apply_typo_throttle instead."""
    return _humanize_typos_impl(parts, rng, protect=protect, max_bubbles=max_bubbles)[0]


# ── Per-fan '*fix' correction throttle ───────────────────────────────
# The thumb-typo itself always rides (an uncorrected slip reads natural), but the
# "*fix" self-correct bubble is the strongest tell — two of them minutes apart reads
# like a bot. So across ALL senders a fan sees at most one correction per window:
# another only after _TYPO_FIX_MIN_INTERVAL has passed OR _TYPO_FIX_MIN_EXCHANGES
# replies have gone by (whichever comes first re-enables it). State is per-fan and
# shared between automations, stamped under fans.custom_fields[_TYPO_FIX_STATE_KEY]
# (an otherwise-unused JSON column → no migration), namespaced under a leading "_"
# so it never collides with a future user-facing custom field.
_TYPO_FIX_MIN_INTERVAL = timedelta(hours=1)
_TYPO_FIX_MIN_EXCHANGES = 50
_TYPO_FIX_STATE_KEY = "_typo_fix"


def _typo_correction_allowed(state: dict, now: datetime) -> bool:
    """True if a '*fix' bubble may fire now given the per-fan throttle `state`
    ({'at': iso, 'since': int}). First correction always allowed; afterwards gated
    on 1h elapsed OR _TYPO_FIX_MIN_EXCHANGES replies since the last one."""
    last_raw = state.get("at")
    if not last_raw:
        return True
    try:
        last = datetime.fromisoformat(last_raw)
    except Exception:
        return True
    since = int(state.get("since", 0) or 0)
    return (now - last) >= _TYPO_FIX_MIN_INTERVAL or since >= _TYPO_FIX_MIN_EXCHANGES


async def apply_typo_throttle(account_id, fan_id, parts, rng, *, protect=(),
                              max_bubbles: int = STYLE_MAX_BUBBLES) -> list[str]:
    """humanize_typos + the per-fan, cross-automation '*fix' throttle. The thumb-slip
    always rides; the correction bubble is suppressed unless _typo_correction_allowed.
    Every reply that runs this layer bumps the per-fan 'since' counter (shared across
    all 4 senders); a fired correction resets it and stamps the time. Returns the
    bubble list sliced to max_bubbles. The fan-lease guarantees one sender per fan per
    tick, so the read-modify-write needs no extra locking."""
    now = datetime.utcnow()
    async with get_session() as s:
        fan = await s.get(Fan, (str(account_id), int(fan_id)))
        state = fan_state(fan, _TYPO_FIX_STATE_KEY)

        out, emitted = _humanize_typos_impl(
            parts, rng, protect=protect, max_bubbles=max_bubbles,
            allow_correction=_typo_correction_allowed(state, now))
        out = out[:max_bubbles]

        if fan is not None:
            # Atomic with nothing else here, but the blob merge is the shared one —
            # this throttle is cross-sender state and must not clobber a sibling key.
            put_fan_state(fan, _TYPO_FIX_STATE_KEY,
                          {"at": now.isoformat(), "since": 0} if emitted else
                          {"at": state.get("at"),
                           "since": int(state.get("since", 0) or 0) + 1})
            await s.commit()
    return out
