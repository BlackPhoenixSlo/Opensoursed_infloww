from __future__ import annotations

import math
import random
import re
import time as _time
from urllib.parse import urlsplit



# re-derive with derive_check_key() when Fansly ships a new bundle; do not trust this literal after a 403/422 storm
CHECK_KEY = "necvac-govry3-tybkYz"

# cyrb53 constants from the bundle: re-read them if digests start mismatching
_H1_INIT = 0xDEADBEEF
_H2_INIT = 0x41C6CE57
_MUL_H1 = 2654435761
_MUL_H2 = 1597334677
_MUL_FIN_A = 2246822507
_MUL_FIN_B = 3266489909

_TS_JITTER_CENTER_MS = 5000
_TS_JITTER_SPAN_MS = 10000
_TS_REFRESH_INTERVAL_S = 3.0

_SERVER_DRIFT_THRESHOLD_MS = 30000

_MASK32 = 0xFFFFFFFF



def _int32(value: int) -> int:
    value &= _MASK32
    return value - 0x100000000 if value & 0x80000000 else value


def _urshift32(value: int, bits: int) -> int:
    return (value & _MASK32) >> bits


def imul32(a: int, b: int) -> int:
    return _int32((a & _MASK32) * (b & _MASK32))


# JS charCodeAt yields UTF-16 units, ord() diverges above the BMP: fine for our ASCII inputs only (check key, URL path, device id)
def cyrb53(text: str, seed: int = 0) -> int:
    h1 = _int32(_H1_INIT ^ seed)
    h2 = _int32(_H2_INIT ^ seed)

    for ch in text:
        code = ord(ch)
        h1 = imul32(h1 ^ code, _MUL_H1)
        h2 = imul32(h2 ^ code, _MUL_H2)

    h1 = imul32(h1 ^ _urshift32(h1, 16), _MUL_FIN_A)
    h1 ^= imul32(h2 ^ _urshift32(h2, 13), _MUL_FIN_B)
    h2 = imul32(h2 ^ _urshift32(h2, 16), _MUL_FIN_A)
    h2 ^= imul32(h1 ^ _urshift32(h1, 13), _MUL_FIN_B)

    return 4294967296 * (2097151 & h2) + _urshift32(h1, 0)



def signed_string(path: str, device_id: str, check_key: str = CHECK_KEY) -> str:
    return f"{check_key}_{path}_{device_id}"


def client_check(path_or_url: str, device_id: str, check_key: str = CHECK_KEY) -> str:
    path = urlsplit(path_or_url).path if "//" in path_or_url else path_or_url
    return f"{cyrb53(signed_string(path, device_id, check_key)):x}"


# jittered like the web client: a clean int(time()*1000) is a fingerprint
def client_timestamp(server_offset_ms: int = 0, now_ms: int | None = None) -> int:
    base = now_ms if now_ms is not None else int(_time.time() * 1000)
    jitter = _TS_JITTER_CENTER_MS - math.floor(_TS_JITTER_SPAN_MS * random.random())
    return base + jitter + server_offset_ms


def server_offset_ms(server_time_ms: int, now_ms: int | None = None) -> int:
    now = now_ms if now_ms is not None else int(_time.time() * 1000)
    drift = server_time_ms - now
    return drift if abs(drift) > _SERVER_DRIFT_THRESHOLD_MS else 0


# the bundle keeps the recomputed value only if greater: requests inside one 3 s tick carry an identical fansly-client-ts
class ClientTimestamp:

    def __init__(self, server_offset: int = 0) -> None:
        self.server_offset = server_offset
        self._value = client_timestamp(server_offset)
        self._last_refresh = _time.monotonic()

    def value(self) -> int:
        now = _time.monotonic()
        if now - self._last_refresh >= _TS_REFRESH_INTERVAL_S:
            self._last_refresh = now
            candidate = client_timestamp(self.server_offset)
            if candidate > self._value:
                self._value = candidate
        return self._value


class DigestCache:

    MAX_ENTRIES = 100

    def __init__(self, device_id: str, check_key: str = CHECK_KEY) -> None:
        self.device_id = device_id
        self.check_key = check_key
        self._order: list[str] = []
        self._cache: dict[str, str] = {}

    def get(self, path_or_url: str) -> str:
        path = urlsplit(path_or_url).path if "//" in path_or_url else path_or_url
        cached = self._cache.get(path)
        if cached is not None:
            return cached
        digest = client_check(path, self.device_id, self.check_key)
        self._cache[path] = digest
        self._order.append(path)
        while len(self._order) > self.MAX_ENTRIES:
            self._cache.pop(self._order.pop(0), None)
        return digest



_MAIN_JS_RE = re.compile(r'"(/?main\.[0-9a-f]+\.js)"', re.IGNORECASE)
_SRC_MAIN_JS_RE = re.compile(r'src\s*=\s*"(main\.[^"]*?\.js)"', re.IGNORECASE)

_STRING_LIT = r'"[^"]*"|\'[^\']*\''
_ASSIGN_RE = re.compile(r"this\.checkKey_\s*=\s*")
_PUSH_RE = re.compile(r"(\w+)\.push\(\s*(" + _STRING_LIT + r")\s*\)")

_JOIN_VAR_RE = re.compile(r"\A(\w+)\.join\(\s*(" + _STRING_LIT + r")\s*\)")
_ARRAY_JOIN_RE = re.compile(
    r"\A\[([^\]]*)\]((?:\.reverse\(\))?)\.join\(\s*(" + _STRING_LIT + r")\s*\)"
)
_CONCAT_LIT_RE = re.compile(r"\A\s*\+\s*(" + _STRING_LIT + r")")
_BARE_LIT_RE = re.compile(r"\A(" + _STRING_LIT + r")")

_EXPR_WINDOW = 400
_PUSH_WINDOW = 2000


def find_main_js(text: str) -> str | None:
    match = _SRC_MAIN_JS_RE.search(text) or _MAIN_JS_RE.search(text)
    return match.group(1).lstrip("/") if match else None


def _unquote(literal: str) -> str:
    return literal[1:-1]


# checkKey_ is assigned twice in the bundle and the first is a decoy: return all, let verification decide; unknown shapes are skipped, not guessed
def candidate_check_keys(chunk_code: str) -> list[str]:
    keys: list[str] = []

    for match in _ASSIGN_RE.finditer(chunk_code):
        window = chunk_code[match.end():match.end() + _EXPR_WINDOW]
        preamble = chunk_code[max(0, match.start() - _PUSH_WINDOW):match.start()]
        value = _eval_key_expr(window, preamble)
        if value and value not in keys:
            keys.append(value)

    return keys


def _eval_key_expr(window: str, preamble: str) -> str | None:
    join_var = _JOIN_VAR_RE.match(window)
    if join_var:
        var, sep = join_var.group(1), _unquote(join_var.group(2))
        parts = [_unquote(lit) for name, lit in _PUSH_RE.findall(preamble) if name == var]
        return sep.join(parts) if parts else None

    arr = _ARRAY_JOIN_RE.match(window)
    if arr:
        items = [m.group(0) for m in re.finditer(_STRING_LIT, arr.group(1))]
        items = [_unquote(i) for i in items]
        if arr.group(2):
            items.reverse()
        value = _unquote(arr.group(3)).join(items)
        rest = window[arr.end():]
        while True:
            concat = _CONCAT_LIT_RE.match(rest)
            if not concat:
                break
            value += _unquote(concat.group(1))
            rest = rest[concat.end():]
        return value

    bare = _BARE_LIT_RE.match(window)
    if bare:
        return _unquote(bare.group(1))

    return None


def verify_samples(samples: list[dict], check_key: str) -> tuple[int, list[dict]]:
    matched = 0
    mismatches: list[dict] = []

    for sample in samples:
        expected = sample["check"]
        actual = client_check(sample["path"], sample["device_id"], check_key)
        if actual == expected:
            matched += 1
        else:
            mismatches.append({**sample, "computed": actual})

    return matched, mismatches


# None, not a guess, when no candidate reproduces every sample: Fansly changed the scheme
def derive_check_key(chunk_code: str, samples: list[dict]) -> str | None:
    if not samples:
        raise ValueError("derive_check_key needs captured samples to verify against")

    for candidate in candidate_check_keys(chunk_code):
        _, mismatches = verify_samples(samples, candidate)
        if not mismatches:
            return candidate

    return None
