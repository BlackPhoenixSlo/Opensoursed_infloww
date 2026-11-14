"""service/login_paste.py — pure: a pasted block of OnlyFans logins → the logins to run and the bad lines
(ultra-mode ticket 11, the login queue; HTTP: remote_login_api, runner: login_queue).

One `email<sep>password` per line; the separator is `:`, `|`, a tab or a space (spaces around it are
dropped; the password is the rest of the line, trimmed). The email holds no `,` `;` `/` (nor space, `:`,
`|`) and its domain has dot-separated non-empty labels, so "a@x.com,secretA:secretB" is a bad line, not
the email "a@x.com,secretA". Blank lines are skipped. A line over MAX_LINE characters (trimmed), an email
seen again (any case) is a bad line; the first one runs. A bad line is reported by its 1-based number and
a reason, never by its text (it may hold a password). Each line matches in one pass (no backtracking
blow-up): a 64 kB paste parses in milliseconds on the one relay process.

`holds_login(text)`: the credential guard for free text (Ultra's request, the panel before sending). True
when some line starts like a login with a looser email (any characters but space, `:`, `|`, `@`; a dot
inside the domain; no length bound), or holds, anywhere, an email followed by
- `:` / `|` / a tab, then any text ("ask a@x.com: nothing" too);
- `,` / `;` / `/` with no space, then any text ("a@x.com,pw");
- a space (or `, ` / `; ` / ` / `), then a password-looking word: 6+ characters, not an email, holding a
  digit or a symbol once trailing `.,;:!?)'"` is trimmed ("a@x.com password123"; "a@x.com tomorrow." passes).
Wider than `parse` on purpose (false positives possible: the user rephrases); a request carrying a login is
refused before any model call. Only the word right after the email counts. The table both halves (this and
app/lib/loginPaste.ts) check: service/tests/fixtures/login_paste_cases.json.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_LOGINS = 50  # one Agency's Creators at most (sized for 50 models)
MAX_LINE = 512  # characters in one trimmed line; longer is a bad line (an email + a password fit easily)
LOGINS_PAGE = "/creators/logins"  # the app page with the paste card (LoginQueueCard)

# Email, then `:` / `|` (blanks around it) or blanks, then the password's first character. Each part has
# one way to match, so a miss costs one pass. Matched on a trimmed line: the password is the rest of it.
_SEP = r"(?:[ \t]*[:|][ \t]*|[ \t]+)(?=\S)"
_EMAIL = r"[^\s:|@,;/]+@[^\s:|@,;/.]+(?:\.[^\s:|@,;/.]+)+"
_LINE = re.compile(rf"({_EMAIL}){_SEP}")
# The guard's line: a looser email than parse's (`,` `;` `/` and any dots allowed, one dot inside the domain).
_G_LINE = re.compile(rf"\s*[^\s:|@]+@[^\s:|@][^\s:|@.]*\.[^\s:|@]+{_SEP}")
# The guard's email stops at `,` `;` `/` too, so "a@x.com,pw" reads as an email then a separator.
# It starts only at a word start and its domain labels hold no dot: one way to match, so a crafted request
# cannot make the scan backtrack for seconds (the relay is one process).
_G_EMAIL = r"(?<![^\s:|@,;/])[^\s:|@,;/]+@[^\s:|@,;/.]+(?:\.[^\s:|@,;/.]+)+\.*"
_INLINE = re.compile(rf"{_G_EMAIL}[ \t]*(?:[:|\t][ \t]*\S|[,;/]\S)")
_SPACED = re.compile(rf"{_G_EMAIL}(?:[ \t]*[,;/][ \t]+|[ \t]+)(?=(\S+))")  # lookahead: the word may start the next match
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


def holds_login(text: str) -> bool:
    return any(_G_LINE.match(raw) or _INLINE.search(raw) or any(_password_like(m.group(1)) for m in _SPACED.finditer(raw))
               for raw in (text or "").splitlines())
