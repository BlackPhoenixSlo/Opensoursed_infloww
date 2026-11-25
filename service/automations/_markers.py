from __future__ import annotations

import re

_WRAP = r"[*_~`\"'()\[\]{}]*"
_BOUND = r"(?:(?<![A-Za-z])|(?-i:(?<=[a-z])(?=[A-Z])))"


def protocol_marker_re(keyword: str) -> re.Pattern[str]:
    return re.compile(
        rf"{_WRAP}{_BOUND}(?:{keyword})([^\n]*)",
        re.IGNORECASE | re.MULTILINE)


STICKER_KEYWORD = r"STICKERS?[ \t]*:"
_STICKER_RE = protocol_marker_re(STICKER_KEYWORD)

_ASK_SEP = r"[ \t]*[:=\-–—]"
_EOL = r"(?![\w])[^\w\n]*$"
_VALUE = re.compile(rf"[ \t]*{_WRAP}[ \t]*(\w*)")


def _asked_re(ids: frozenset[str]) -> re.Pattern[str]:
    known = "|".join(re.escape(k) for k in sorted({"none", *ids}, key=len, reverse=True))
    caps = protocol_marker_re(rf"(?-i:ASKED){_WRAP}{_ASK_SEP}").pattern
    opens = rf"^[ \t]*{_WRAP}asked{_WRAP}{_ASK_SEP}([^\n]*)"
    sep = rf"{_WRAP}{_BOUND}asked{_WRAP}{_ASK_SEP}[ \t]*{_WRAP}[ \t]*({known}){_EOL}"
    bare = (rf"(?:^[ \t]*{_WRAP}asked|{_WRAP}{_BOUND}(?-i:ASKED)){_WRAP}[ \t]+{_WRAP}[ \t]*"
            rf"({known}){_EOL}")
    return re.compile(rf"[ \t]*(?:{caps}|{opens}|{sep}|{bare})", re.IGNORECASE | re.MULTILINE)


def strip_asked(text: str, ids: frozenset[str]) -> tuple[str, list[str]]:
    values: list[str] = []

    def cut(m: re.Match[str]) -> str:
        tail = m.group(1) if m.group(1) is not None else m.group(2)
        if tail is None:
            values.append(m.group(3) if m.group(3) is not None else m.group(4))
            return ""
        values.append(_VALUE.match(tail).group(1))
        s = _STICKER_RE.search(tail)
        if s:
            return tail[len(tail[:s.start()].rstrip()):]
        return ""

    out, n = _asked_re(ids).subn(cut, text or "")
    if ids:
        echo = "|".join(re.escape(k) for k in ids)
        out, e = re.subn(rf"^[ \t]*\[(?:{echo})\][ \t]*|[ \t]*\[(?:{echo})\]", "", out,
                         flags=re.IGNORECASE | re.MULTILINE)
        n += e
    return (out.strip(), values) if n else (text, [])


# Group 2 (trailing separator) is cut with the span so no cleanup pass is needed; a space before punctuation ("thoughtful ?") is deliberate house style.
_STAR_SPAN_RE = re.compile(r"\*\s*([^*\n]+?)\s*\*([ \t]*[,;:]?[ \t]*)")
# Short on purpose: prod sent *laughs*/*blushes*; every other one-word span is real emphasis, which growing this list would start eating.
_EMOTE_WORDS = frozenset(
    "wink winks giggle giggles blush blushes smirk smirks grin grins laugh "
    "laughs sigh sighs shrug shrugs moan moans pout pouts smile smiles "
    "nod nods stretch stretches yawn yawns snap snaps squeeze squeezes".split())


def bare_star_span(text: str) -> str | None:
    m = _STAR_SPAN_RE.fullmatch((text or "").strip())
    return m.group(1) if m else None


def strip_narration(raw: str) -> str:
    text = (raw or "").strip()
    if bare_star_span(text) is not None:
        return ""
    return _STAR_SPAN_RE.sub(
        lambda m: "" if (" " in m.group(1)
                         or m.group(1).lower() in _EMOTE_WORDS)
        else m.group(1) + m.group(2), text).strip()


# Model answering its prompt inside the reply; the lookarounds keep emoticons like ":(" whole.
_ASIDE_RE = re.compile(r"[ \t]*(?<![:;=8xX])\((?![:;=])[^()\n]*(?<![:;=^-])\)")


def strip_asides(raw: str) -> str:
    raw = raw or ""
    out: list[str] = []
    for ln in raw.split("\n"):
        kept = _ASIDE_RE.sub("", ln)
        if kept == ln:
            out.append(ln)
        elif kept.strip():
            out.append(kept.strip())
    text = "\n".join(out)
    if text != raw:
        text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
