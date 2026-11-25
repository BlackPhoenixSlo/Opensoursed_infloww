from __future__ import annotations

import re

_HEX = frozenset("0123456789abcdefABCDEF")


_PATH_ENCODE = frozenset(' "#<>?`{}')
_SINGLE_DOT = frozenset((".", "%2e"))
_DOUBLE_DOT = frozenset(("..", ".%2e", "%2e.", "%2e%2e"))


def _encode_char(ch: str) -> str:
    if ord(ch) < 0x20 or ord(ch) > 0x7E or ch in _PATH_ENCODE:
        return "".join(f"%{b:02X}" for b in ch.encode("utf-8"))
    return ch


def url_path(raw_path: bytes) -> str:
    s = raw_path.decode("latin-1").replace("\t", "").replace("\n", "").replace("\r", "")
    if s[:1] in ("/", "\\"):
        s = s[1:]
    out: list[str] = []
    for seg in re.split(r"[/\\]", s):
        low = seg.lower()
        if low in _DOUBLE_DOT:
            if out:
                out.pop()
            continue
        if low in _SINGLE_DOT:
            continue
        out.append("".join(map(_encode_char, seg)))
    if re.split(r"[/\\]", s)[-1].lower() in _SINGLE_DOT | _DOUBLE_DOT:
        out.append("")
    return "/" + "/".join(out) if out else "/"


_URI_RESERVED = ";/?:@&=+$,#"


def decode(s: str, reserved: str) -> str:
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch != "%":
            out.append(ch)
            i += 1
            continue
        if i + 2 >= n or s[i + 1] not in _HEX or s[i + 2] not in _HEX:
            raise ValueError("malformed")
        b = int(s[i + 1:i + 3], 16)
        if b < 0x80:
            c = chr(b)
            out.append(s[i:i + 3] if c in reserved else c)
            i += 3
            continue
        if b & 0xE0 == 0xC0:
            k = 2
        elif b & 0xF0 == 0xE0:
            k = 3
        elif b & 0xF8 == 0xF0:
            k = 4
        else:
            raise ValueError("malformed")
        seq = [b]
        j = i + 3
        for _ in range(k - 1):
            if j + 3 > n or s[j] != "%" or s[j + 1] not in _HEX or s[j + 2] not in _HEX:
                raise ValueError("malformed")
            nb = int(s[j + 1:j + 3], 16)
            if nb & 0xC0 != 0x80:
                raise ValueError("malformed")
            seq.append(nb)
            j += 3
        # strict: overlong, surrogate, > U+10FFFF raise as in JS
        out.append(bytes(seq).decode("utf-8"))
        i = j
    return "".join(out)


def _trydecode(s: str, reserved: str) -> str:
    try:
        return decode(s, reserved)
    except ValueError:
        def run(m: re.Match) -> str:
            try:
                return decode(m.group(0), reserved)
            except ValueError:
                return m.group(0)
        return re.sub(r"(?:%[0-9A-Fa-f]{2})+", run, s)


def route_path(path: str) -> str:
    if "%" not in path:
        return path
    return _trydecode(path.replace("%25", "%2525"), _URI_RESERVED)


def param(segment: str) -> str:
    return _trydecode(segment, "") if "%" in segment else segment


