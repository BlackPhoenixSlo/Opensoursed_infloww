from __future__ import annotations

KIND = "walk:shared_refresher"
FLAT_LO, FLAT_HI = 0.8, 1.2
FLAT_GAP = 0.25
QUEUE_WAIT_S = 10.0


def per_creator_min(by_caller: dict | None, n_creators: int, seconds: float) -> float | None:
    if by_caller is None or not n_creators or not seconds or seconds <= 0:
        return None
    return round(by_caller.get(KIND, 0) / n_creators / (seconds / 60), 3)


def flat_in_n(n3: float | None, n1: float | None) -> bool:
    if n3 is None or n1 is None:
        return False
    return FLAT_LO <= n3 <= FLAT_HI and FLAT_LO <= n1 <= FLAT_HI and n3 - n1 <= FLAT_GAP


def staleness(samples: list[dict]) -> dict:
    per: dict[str, float] = {}
    never: set[str] = set()
    missing: set[str] = set()
    max_s = excess = None
    worst = None
    cycles: set[int] = set()
    n = 0
    for s in samples:
        for aid, fr in (s.get("rows") or {}).items():
            n += 1
            if not isinstance(fr, dict) or fr.get("cycle_s") is None or fr.get("now") is None:
                missing.add(aid)
                continue
            if fr.get("at") is None:
                never.add(aid)
                continue
            age = round((fr["now"] - fr["at"]) / 1000, 1)
            cycles.add(int(fr["cycle_s"]))
            per[aid] = max(per.get(aid, age), age)
            over = round(age - fr["cycle_s"], 1)
            if excess is None or over > excess:
                excess, worst = over, {"creator": aid, "phase": s.get("phase"), "age_s": age, "cycle_s": fr["cycle_s"]}
            max_s = age if max_s is None else max(max_s, age)
    return {"max_s": max_s, "excess_s": excess, "cycle_s": max(cycles) if cycles else None,
            "per_creator": dict(sorted(per.items())), "never": sorted(never), "missing": sorted(missing),
            "worst": worst, "samples": len(samples), "rows": n, "queue_wait_s": QUEUE_WAIT_S}


def within_cycle(st: dict) -> bool:
    return bool(st["samples"]) and not st["never"] and not st["missing"] and st["excess_s"] is not None \
        and st["excess_s"] <= QUEUE_WAIT_S


def fresh_until(sample: dict, t: float) -> list[str]:
    out = []
    for aid, fr in (sample.get("rows") or {}).items():
        if not isinstance(fr, dict) or None in (fr.get("at"), fr.get("cycle_s"), fr.get("now")):
            continue
        if sample["t"] + (fr["at"] + fr["cycle_s"] * 1000 - fr["now"]) / 1000 > t:
            out.append(aid)
    return sorted(out)


# D's own calls: 37 at 10 Creators (measured 33); the spec's 30 left the inbox screen reads out.
OPEN_TOTAL_MAX = 40
FRESH_MIN_SHARE = 0.5


def open_after_cycle(*, fresh: list[str], warmed: dict[str, int], answers: list, own_total: int | None,
                     n_creators: int) -> dict:
    fresh_set = set(fresh)
    read_fresh = sorted(a for a in fresh_set if warmed.get(a))
    started_past = sorted(a for a, n in warmed.items() if n and a not in fresh_set)
    allowed = {"reused", "started"} if started_past else {"reused"}
    failed = []
    if not answers or any(a not in allowed for a in answers):
        failed.append(f"answers {answers} not all in {sorted(allowed)}")
    if len(fresh_set) < FRESH_MIN_SHARE * n_creators:
        failed.append(f"{len(fresh_set)} of {n_creators} Creators within Cycle at the open")
    if read_fresh:
        failed.append(f"warm read {len(read_fresh)} Creators within their Cycle")
    if own_total is None or own_total > OPEN_TOTAL_MAX:
        failed.append(f"own total {own_total} > {OPEN_TOTAL_MAX}")
    return {"ok": not failed, "failed": failed, "fresh_at_open": len(fresh_set), "warm_read_within_cycle": read_fresh,
            "warm_started_past_cycle": started_past, "own_total": own_total, "own_total_max": OPEN_TOTAL_MAX}


ME_KEY = "GET /api2/v2/users/me"
LIST_KEY = "GET /api2/v2/chats"
WINDOW_CALLS = 3


def per_cycle(r0: dict | None, r1: dict | None, creators: list[str], seconds: float, cycle_s: float) -> dict | None:
    if r0 is None or r1 is None or not cycle_s:
        return None

    def n(key: str, aid: str) -> int:
        return r1.get((KIND, key, aid), 0) - r0.get((KIND, key, aid), 0)
    me = {a: n(ME_KEY, a) for a in creators}
    lists = {a: n(LIST_KEY, a) for a in creators}
    cap = int(seconds // cycle_s) + 1
    me_max, list_max = max(me.values(), default=0), max(lists.values(), default=0)
    return {"users_me": me, "list_calls": lists, "users_me_max": me_max, "list_calls_max": list_max,
            "cycles": round(seconds / cycle_s, 2), "cap_reads": cap, "window_calls": WINDOW_CALLS,
            "ok": me_max <= cap and list_max <= cap * WINDOW_CALLS}


def clears_within(got: dict[str, dict], max_ms: int) -> dict:
    late = sorted(f"{t}.{k}" for t, g in got.items() for k in ("row_cleared_ms", "chip_dropped_ms")
                  if g.get(k) is None or g[k] > max_ms)
    return {"ok": bool(got) and not late, "late_or_never": late, "max_ms": max_ms}


def fresh_badge(badge_first: int | None, truth: dict[str, int]) -> dict:
    t = sum(truth.values())
    diff = None if badge_first is None else badge_first - t
    return {"ok": diff == 0, "badge_first": badge_first, "truth": t, "diff": diff}


AS_OF = "as of"


def quiet_stale(samples: list[dict]) -> dict:
    read = [s for s in samples if isinstance(s.get("text"), str)]
    stale = [s for s in read if AS_OF in s["text"]]
    per: dict[str, list[int]] = {}
    for s in samples:
        p = per.setdefault(str(s.get("phase")), [0, 0])
        if isinstance(s.get("text"), str):
            p[0] += 1
            p[1] += AS_OF in s["text"]
    return {"ok": bool(read) and not stale, "quiet_stale_samples": len(stale) if read else None,
            "samples": len(read), "missing": len(samples) - len(read), "per_phase": per,
            "first_stale": dict(stale[0]) if stale else None}
