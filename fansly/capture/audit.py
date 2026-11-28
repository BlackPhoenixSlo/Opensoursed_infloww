from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from policy import SAFE_METHODS, waf_allowed


@dataclass
class AuditResult:
    passed: bool
    failures: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"passed": self.passed, "failures": self.failures,
                "warnings": self.warnings, "counts": self.counts}


def read_jsonl(path: Path) -> list[dict]:
    out = []
    if path.exists():
        for ln in path.read_text().splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
    return out


def _next_saved_page(session: Path, after: float):
    pages = session.parent.parent / "pages"
    best = None
    if pages.is_dir():
        for meta in pages.rglob("*.meta.json"):
            try:
                m = json.loads(meta.read_text())
            except ValueError:
                continue
            if m.get("session") != session.name:
                continue
            t = float(m.get("saved_at") or meta.stat().st_mtime)
            if t > after and (best is None or t < best[0]):
                best = (t, str(meta.relative_to(pages))[: -len(".meta.json")])
    return best[1] if best else None


def audit(session: Path, now: float) -> AuditResult:
    failures, warnings = [], []
    counts = Counter()
    stopped = False
    unverified: dict[str, float] = {}
    for ln in read_jsonl(session / "gate.jsonl"):
        ev = ln.get("event")
        if ev:
            counts[f"event_{ev}"] += 1
            stopped = stopped or ev == "stopped"
            continue
        d = ln.get("decision", "")
        counts[d] += 1
        if d == "continued" and str(ln.get("method", "")).upper() not in SAFE_METHODS:
            counts["continued_writes"] += 1
        if d == "waf" and not waf_allowed(ln.get("method", ""), ln.get("origin", ""), ln.get("path", "")):
            counts["invalid_waf"] += 1
        if d == "faked" and ln.get("provenance") == "unverified":
            p = ln.get("path", "")
            unverified[p] = min(unverified.get(p, ln.get("ts", 0)), ln.get("ts", 0))
    counts.setdefault("continued_writes", 0)
    counts.setdefault("waf", 0)
    if counts["invalid_waf"]:
        failures.append(f"{counts['invalid_waf']} POST(s) outside the WAF endpoint allowlist")
    if counts["continued_writes"]:
        failures.append(f"{counts['continued_writes']} continued request(s) outside GET/HEAD/OPTIONS")
    if counts["event_ws_frame_sent"]:
        failures.append(f"{counts['event_ws_frame_sent']} socket frame(s) sent after arming")
    if counts["event_ws_created"]:
        failures.append(f"{counts['event_ws_created']} socket(s) created after arming")
    if counts["event_ws_handshake"]:
        failures.append(f"{counts['event_ws_handshake']} socket handshake(s) completed after arming")
    if counts["event_blank_unconfirmed"]:
        failures.append(f"{counts['event_blank_unconfirmed']} blank(s) left a target without a confirmed crash")
    if (session / "HALT").exists() or counts["event_halt"]:
        failures.append("session halted")
    if (session / "WATCHDOG_TRIP").exists():
        failures.append("watchdog tripped")
    if not stopped:
        failures.append("no stopped event: session was not closed by gate.py stop")
    obs = read_jsonl(session / "unread.jsonl")
    counts["groups_observations"] = len(obs)
    if len(obs) < 2:
        failures.append(f"{len(obs)} /messaging/groups observation(s); need at least 2")
    else:
        initial, previous = {}, {}
        compared, dropped, rose = set(), set(), set()
        for observation in obs:
            groups = {g: n for g, n in (observation.get("groups") or {}).items() if type(n) is int and n >= 0}
            for group, count in groups.items():
                initial.setdefault(group, count)
                if group in previous:
                    compared.add(group)
                    if count < previous[group]:
                        dropped.add(group)
                    elif count > previous[group]:
                        rose.add(group)
                previous[group] = count
        missing = sum(count > 0 and group not in groups for group, count in initial.items())
        counts["groups_compared"] = len(compared)
        if not compared:
            failures.append("no thread was seen in two /messaging/groups observations")
        if missing:
            failures.append(f"{missing} initially unread group(s) missing from closing observation")
        if dropped:
            failures.append(f"unread count dropped in {len(dropped)} group(s)")
        if rose:
            warnings.append(f"unread count rose in {len(rose)} group(s) (fan activity)")
    for path, ts in sorted(unverified.items()):
        page = _next_saved_page(session, ts)
        where = f"check the screenshot of page {page}" if page else "no page was saved after it"
        warnings.append(f"unverified fake {path} fired; {where}")
    return AuditResult(not failures, failures, warnings, dict(counts))
