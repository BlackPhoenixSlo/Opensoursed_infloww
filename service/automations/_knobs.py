from __future__ import annotations

import os



# CHATTERLY_TEST_MODE=0 means no; a bare truthiness test would read it as yes.
def test_mode() -> bool:
    v = (os.environ.get("CHATTERLY_TEST_MODE") or "").strip().lower()
    return v not in ("", "0", "false", "no", "off")


# Absent and null both take the default: .get(k, True) turns null into False; on money_gate/follow_back_gate that spends money, on dry_run it sends for real.
def bool_knob(payload: dict | None, key: str, default: bool) -> bool:
    v = (payload or {}).get(key)
    return default if v is None else bool(v)


def coerce_ids(raw: object) -> set[int]:
    out: set[int] = set()
    if not isinstance(raw, (list, tuple, set)):
        return out
    for x in raw:
        try:
            out.add(int(x))
        except (TypeError, ValueError):
            continue
    return out
