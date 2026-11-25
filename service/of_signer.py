from __future__ import annotations

import hashlib
import re
import time as _time
from urllib.parse import urlparse


# OF's checksum chunk sums 32 `]W[..](0)` calls; indexes come from a dense cluster of `](0)` mod 40.
_CHARCODE_CLOSE = re.compile(r"\]\(0\)")
_NUM5_BEFORE_WBRACKET = re.compile(r"(\d{5})(?=[,%]W\[)")
_NUM5_BROAD = re.compile(r"\b(\d{5})\b")
_REGION_PAD = 200
_INDEX_COUNT = 32
_INDEX_MODULO = 40


def derive_rules_from_chunk(
    chunk_code: str,
    samples: list[dict],
) -> dict | None:
    if not samples:
        return None

    positions = [m.start() for m in _CHARCODE_CLOSE.finditer(chunk_code)]
    if len(positions) < _INDEX_COUNT:
        return None

    best_start, best_span = 0, float("inf")
    for i in range(len(positions) - (_INDEX_COUNT - 1)):
        span = positions[i + _INDEX_COUNT - 1] - positions[i]
        if span < best_span:
            best_span = span
            best_start = i

    region_start = max(0, positions[best_start] - _REGION_PAD)
    region_end = positions[best_start + _INDEX_COUNT - 1] + _REGION_PAD
    region = chunk_code[region_start:region_end]

    bases = [int(m.group(1)) for m in _NUM5_BEFORE_WBRACKET.finditer(region)]
    if len(bases) != _INDEX_COUNT:
        bases = [int(m.group(1)) for m in _NUM5_BROAD.finditer(region)]
        if len(bases) != _INDEX_COUNT:
            return None

    indexes = [n % _INDEX_MODULO for n in bases]

    # abs() in sign: the captured cv may be +sum or -sum.
    s0 = samples[0]
    byte_sum_0 = _byte_sum(s0["sha1Hex"], indexes)
    for candidate in (s0["checksumValue"] - byte_sum_0,
                      -s0["checksumValue"] - byte_sum_0):
        if all(
            abs(_byte_sum(s["sha1Hex"], indexes) + candidate) == s["checksumValue"]
            for s in samples
        ):
            return {
                "checksum_indexes": indexes,
                "checksum_constant": candidate,
                "samples_verified": len(samples),
            }

    return None


def verify_rules(rules: dict, samples: list[dict]) -> tuple[bool, list[dict]]:
    results = []
    indexes = rules["checksum_indexes"]
    constant = rules["checksum_constant"]
    for s in samples:
        got = abs(_byte_sum(s["sha1Hex"], indexes) + constant)
        results.append({
            "sha1Hex": s["sha1Hex"],
            "expected": s["checksumValue"],
            "got": got,
            "ok": got == s["checksumValue"],
        })
    return all(r["ok"] for r in results), results


def sign(url: str, user_id: str | int, rules: dict, time_ms: int | None = None) -> dict:
    if time_ms is None:
        time_ms = int(_time.time() * 1000)

    parsed = urlparse(url)
    path = parsed.path + (f"?{parsed.query}" if parsed.query else "")

    payload = "\n".join([
        rules["static_param"],
        str(time_ms),
        path,
        str(user_id),
    ])
    sha1_hex = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    checksum = _byte_sum(sha1_hex, rules["checksum_indexes"]) + rules["checksum_constant"]

    return {
        "sign": f"{rules['start']}:{sha1_hex}:{format(abs(checksum), 'x')}:{rules['end']}",
        "time": str(time_ms),
    }


def _byte_sum(sha1_hex: str, indexes: list[int]) -> int:
    return sum(ord(sha1_hex[i]) for i in indexes)
