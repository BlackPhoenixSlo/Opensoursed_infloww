from __future__ import annotations

import logging
import re

from sqlalchemy import select

from db.engine import get_session
from db.models import SensitiveWord, UserAccount

log = logging.getLogger("of-relay.automation.wordfilter")


BANNED_WORD_MODES = ("block", "mask")


def _mask_hit(word: str) -> str:
    if not word:
        return word
    return word[0] + "*" * (len(word) - 1) if len(word) > 1 else word + "*"


# Whole-word on purpose: an "ass" rule must not trip on "class"/"pass".
def _compile_banned_re(words):
    try:
        clean, seen = [], set()
        for w in words or ():
            w = str(w).strip()
            k = w.lower()
            if w and k not in seen:
                seen.add(k)
                clean.append(w)
        if not clean:
            return None
        clean.sort(key=len, reverse=True)
        return re.compile(
            r"\b(" + "|".join(re.escape(w) for w in clean) + r")\b", re.IGNORECASE)
    except Exception:
        return None


def scan_outbound(text, words, mode="block") -> dict:
    try:
        s = "" if text is None else str(text)
        rx = _compile_banned_re(words)
        if rx is None or not s:
            return {"clean_text": s, "hits": []}
        hits = [m.group(0) for m in rx.finditer(s)]
        if not hits:
            return {"clean_text": s, "hits": []}
        if str(mode).strip().lower() == "mask":
            clean = rx.sub(lambda m: _mask_hit(m.group(0)), s)
        else:
            clean = s
        return {"clean_text": clean, "hits": hits}
    except Exception:
        # Fail open: a broken list must not crash a send.
        return {"clean_text": "" if text is None else str(text), "hits": []}


def filter_banned(parts, words, mode="block") -> tuple[list[str] | None, list[str]]:
    # Whole turn: one dirty bubble blocks all (a half conversation must not ship); call before the nonnative/typo layers so a typo cannot smuggle a word past.
    parts = list(parts or ())
    if not words:
        return parts, []
    masking = str(mode).strip().lower() == "mask"
    out: list[str] = []
    hits: list[str] = []
    for p in parts:
        r = scan_outbound(p, words, "mask" if masking else "block")
        hits += r["hits"]
        out.append(r["clean_text"])
    if hits and not masking:
        return None, hits
    return out, hits


def banned_hit_summary(hits) -> list[str]:
    return sorted({str(h).lower() for h in hits or ()})


def normalize_banned_config(cfg) -> tuple[list[str], str]:
    if not isinstance(cfg, dict):
        cfg = {}
    words: list[str] = []
    seen: set[str] = set()
    for w in cfg.get("words") or []:
        w = str(w).strip()
        k = w.lower()
        if w and k not in seen:
            seen.add(k)
            words.append(w)
    words = words[:5000]
    mode = str(cfg.get("mode") or "block").strip().lower()
    if mode not in BANNED_WORD_MODES:
        mode = "block"
    return words, mode


async def load_banned_words(account_id: str) -> tuple[list[str], str]:
    sensitive = await load_sensitive_words(account_id)
    return normalize_banned_config({"words": sensitive, "mode": "block"})


async def load_sensitive_words(account_id: str) -> list[str]:
    # Fails open: the list is a safety net, not a runtime dependency.
    try:
        async with get_session() as s:
            return list((await s.execute(
                select(SensitiveWord.word)
                .join(UserAccount, UserAccount.user_id == SensitiveWord.agency_user_id)
                .where(UserAccount.account_id == str(account_id))
            )).scalars().all())
    except Exception:
        log.warning("sensitive_words_load_failed account=%s", account_id, exc_info=True)
        return []


class OutboundWordsBlocked(Exception):

    def __init__(self, hits):
        self.hits = banned_hit_summary(hits)
        super().__init__(f"outbound text holds banned/sensitive word(s) {self.hits!r}")


class OutboundGuard:

    def __init__(self, words, mode="block"):
        self.words, self.mode = words, mode
        self.passed = 0
        self.blocked = 0
        self.hits: list[str] = []

    def __call__(self, text):
        if text:
            r = scan_outbound(text, self.words, self.mode)
            if r["hits"] and str(self.mode).strip().lower() != "mask":
                blocked = OutboundWordsBlocked(r["hits"])
                self.blocked += 1
                self.hits = sorted(set(self.hits) | set(blocked.hits))
                raise blocked
            text = r["clean_text"]
        self.passed += 1
        return text

    def summary(self) -> dict:
        return {"texts_passed_guard": self.passed, "texts_blocked": self.blocked,
                "blocked_hits": list(self.hits)}

    def run_status(self) -> str:
        return "skipped" if self.blocked and not self.passed else "ok"


def outbound_guard(words, mode="block"):
    return OutboundGuard(words, mode) if words else None


def sensitive_hits(text: str, words: list[str]) -> list[str]:
    hits: list[str] = []
    for w in words:
        parts = [re.escape(p) for p in str(w).split()]
        if parts and re.search(r"(?<![^\W_])" + r"\s+".join(parts) + r"(?![^\W_])",
                               text, re.IGNORECASE):
            hits.append(w)
    return hits
