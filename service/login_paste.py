from __future__ import annotations

import re
from dataclasses import dataclass

MAX_LOGINS = 50
MAX_LINE = 512
LOGINS_PAGE = "/creators/logins"

_SEP = r"(?:[ \t]*[:|][ \t]*|[ \t]+)(?=\S)"
_EMAIL = r"[^\s:|@,;/]+@[^\s:|@,;/.]+(?:\.[^\s:|@,;/.]+)+"
_LINE = re.compile(rf"({_EMAIL}){_SEP}")
_G_LINE = re.compile(rf"\s*[^\s:|@]+@[^\s:|@][^\s:|@.]*\.[^\s:|@]+{_SEP}")
# One way to match: a crafted request must not make the scan backtrack for seconds (the relay is one process).
_G_EMAIL = r"(?<![^\s:|@,;/])[^\s:|@,;/]+@[^\s:|@,;/.]+(?:\.[^\s:|@,;/.]+)+\.*"
_INLINE = re.compile(rf"{_G_EMAIL}[ \t]*(?:[:|\t][ \t]*\S|[,;/]\S)")
_SPACED = re.compile(rf"{_G_EMAIL}(?:[ \t]*[,;/][ \t]+|[ \t]+)(?=(\S+))")
_TRAIL = ".,;:!?)'\""

NOT_A_LOGIN = "not email<separator>password"
DUPLICATE = "duplicate email"
TOO_LONG = f"over {MAX_LINE} characters"
TOO_MANY = f"over {MAX_LOGINS} logins"


@dataclass(frozen=True)
class Login:
    line: int
    email: str
    password: str


@dataclass(frozen=True)
class BadLine:
    line: int
    reason: str


# A bad line is reported by number and reason, never by text (it may hold a password).
def parse(text: str) -> tuple[list[Login], list[BadLine]]:
    logins: list[Login] = []
    bad: list[BadLine] = []
    seen: set[str] = set()
    for no, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        m = _LINE.match(line) if len(line) <= MAX_LINE else None
        if m is None:
            bad.append(BadLine(no, TOO_LONG if len(line) > MAX_LINE else NOT_A_LOGIN))
        elif m.group(1).lower() in seen:
            bad.append(BadLine(no, DUPLICATE))
        elif len(logins) >= MAX_LOGINS:
            bad.append(BadLine(no, TOO_MANY))
        else:
            seen.add(m.group(1).lower())
            logins.append(Login(no, m.group(1), line[m.end():]))
    return logins, bad


def _password_like(word: str) -> bool:
    w = word.rstrip(_TRAIL)
    return len(w) >= 6 and re.search(r"[^A-Za-z]", w) is not None and re.fullmatch(_G_EMAIL, w) is None


# Wider than parse on purpose (false positives possible: the user rephrases); a request carrying a login is refused before any model call.
def holds_login(text: str) -> bool:
    return any(_G_LINE.match(raw) or _INLINE.search(raw) or any(_password_like(m.group(1)) for m in _SPACED.finditer(raw))
               for raw in (text or "").splitlines())
