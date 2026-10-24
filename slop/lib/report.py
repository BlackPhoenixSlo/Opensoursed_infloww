"""Invariants + evidence. A scenario calls ctx.check(...) / ctx.metric(...);
the run folder gets invariants.json, metrics.json, http.json, summary.txt,
logs and screenshots, and evidence/latest points at it."""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parents[1] / "evidence"


def run_dir(scenario: str, tag: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    d = EVIDENCE / f"{stamp}-{scenario}{'-' + tag if tag else ''}-{secrets.token_hex(2)}"
    (d / "screenshots").mkdir(parents=True, exist_ok=True)
    return d


class Report:
    def __init__(self, scenario: str, out: Path, params: dict):
        self.scenario, self.out, self.params = scenario, out, params
        self.checks: list[dict] = []
        self.metrics: dict = {}
        self.notes: list[str] = []
        self.infra: str | None = None  # the stack or the scenario itself broke: no verdict

    def check(self, name: str, ok: bool | None, *, budget: bool = False, **detail) -> bool:
        """`ok=None` records the check as SKIP (shown, never counted as a pass).
        `budget`: a latency/throughput budget rather than a correctness invariant
        (labelled in the summary; a miss is still FAIL)."""
        status = "skip" if ok is None else "pass" if ok else "fail"
        self.checks.append({"name": name, "ok": None if ok is None else bool(ok), "status": status,
                            **({"budget": True} if budget else {}), **detail})
        print(f"  [{status.upper()}] {name} {json.dumps(detail, default=str)[:300]}")
        return bool(ok)

    def skip(self, name: str, reason: str, **detail) -> None:
        self.check(name, None, reason=reason, **detail)

    def metric(self, key: str, value) -> None:
        self.metrics[key] = value

    def note(self, *lines: str) -> None:
        """Free-form lines for summary.txt (e.g. a per-stage table)."""
        self.notes += lines

    @property
    def ok(self) -> bool:
        return (not self.infra and any(c["ok"] for c in self.checks)
                and all(c["ok"] is not False for c in self.checks))

    @property
    def failed_invariants(self) -> list[str]:
        """Failed checks that are correctness invariants (not budgets)."""
        return [c["name"] for c in self.checks if c["ok"] is False and not c.get("budget")]

    def write(self, http_summary: dict, http_errors: list[str]) -> None:
        o = self.out
        (o / "invariants.json").write_text(json.dumps(self.checks, indent=2, default=str))
        (o / "metrics.json").write_text(json.dumps({"params": self.params, "infra": self.infra, **self.metrics}, indent=2, default=str))
        (o / "http.json").write_text(json.dumps({"routes": http_summary, "errors": http_errors}, indent=2))
        shots = sorted(str(p.relative_to(o)) for p in (o / "screenshots").glob("*.png"))
        verdict = "INFRA FAILURE" if self.infra else "PASS" if self.ok else "FAIL"
        lines = [f"scenario {self.scenario}: {verdict}", f"params {json.dumps(self.params)}"]
        lines += [f"infra: {self.infra}"] if self.infra else []
        lines += [""] + [f"{c['status'].upper()}  {'[budget] ' if c.get('budget') else ''}{c['name']}"
                         + (f"  ({c['reason']})" if c["status"] == "skip" and c.get("reason") else "")
                         for c in self.checks]
        lines += ([""] + self.notes if self.notes else [])
        lines += ["", "http (route: n, 4xx, 5xx, p50, p95 ms):"]
        lines += [f"  {k}: {v["n"]}, {v["4xx"]}, {v["5xx"]}, {v['p50_ms']}, {v['p95_ms']}" for k, v in http_summary.items()]
        lines += ["", "screenshots:"] + [f"  {s}" for s in shots]
        (o / "summary.txt").write_text("\n".join(lines) + "\n")
        latest = EVIDENCE / "latest"
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        os.symlink(o.name, latest)
