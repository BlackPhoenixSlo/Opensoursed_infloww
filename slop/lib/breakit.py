"""--break: break-it-once against a green baseline (run first, or read from --baseline). Moved from lib/cli.py
(which re-exports break_one); adds the Run identity checks. cli's scenario loading and runs are looked up on the
module at call time."""
from __future__ import annotations

import json
from pathlib import Path

from slop.lib import cli, identity
from slop.lib.faults import FAULTS


def _status(checks: list[dict]) -> dict[str, str]:
    return {c["name"]: c.get("status") or ("pass" if c["ok"] else "fail") for c in checks}


def _load_baseline(d: Path, name: str, ui: bool, args, params, shards: int = 1) -> tuple[dict, str | None, dict]:
    """(statuses, problem, params) from a previous no-fault run of the same scenario, knobs and Run identity."""
    try:
        checks = json.loads((d / "invariants.json").read_text())
        meta = json.loads((d / "metrics.json").read_text())
    except (OSError, ValueError) as e:
        return {}, f"baseline {d} unreadable: {e}", {}
    bp = meta.get("params", {})
    want = cli._run_knobs(name, args, params, ui, shards, None)
    diff = cli._same_knobs(bp, want)
    if diff:
        return {}, f"baseline {d} was run with other knobs (have, want): {diff}", bp
    why = identity.baseline_problem(bp, {"source_id": cli._source_id(), "env_id": args.env_id,
                                         "env_names": args.env_names})
    if why:
        return {}, f"baseline {d}: not the same Run identity: {why}", bp
    if meta.get("infra"):
        return {}, f"baseline {d} had an infra failure: {meta['infra']}", bp
    return _status(checks), None, bp


def break_one(name: str, path: Path, args, params) -> str:
    """Break-it-once. Returns CAUGHT, NOT CAUGHT or INCONCLUSIVE."""
    try:
        mod = cli.load(path)
    except Exception as e:
        print(f"slop: {name} break INCONCLUSIVE: scenario import failed: {type(e).__name__}: {e}")
        return "INCONCLUSIVE"
    fault = args.fault or getattr(mod, "FAULT", None)
    if not fault or fault not in FAULTS:
        print(f"slop: {name} declares no known FAULT ({fault!r}); --break needs one of {', '.join(FAULTS)}")
        return "INCONCLUSIVE"
    targets = FAULTS[fault].targets
    if args.baseline:
        base_dir = Path(args.baseline).resolve()
        ui, shards = cli._knobs(mod, args, params)
        base, problem, base_params = _load_baseline(base_dir, name, ui, args, params, shards)
    else:
        print(f"slop: break-it-once {fault}: green baseline first")
        b = cli.run_one(name, path, args, params, tag="baseline")
        base_dir, base, problem = b.out, _status(b.checks), (f"baseline infra failure: {b.infra}" if b.infra else None)
        base_params, problem = b.params, problem or identity.raced([b.params])
    broken_dir, broken, broken_problem = None, {}, None
    if not problem:
        r = cli.run_one(name, path, args, params, fault=fault, tag="break")
        broken_dir, broken = r.out, _status(r.checks)
        broken_problem = f"fault run infra failure: {r.infra}" if r.infra else identity.raced([base_params, r.params])

    missing = [t for t in targets if t not in base or (broken_dir and t not in broken)]
    not_green = [t for t in targets if base.get(t) not in (None, "pass")]
    went_red = [t for t in targets if base.get(t) == "pass" and broken.get(t) == "fail"]
    stayed = [f"{t} ({base.get(t)} -> {broken.get(t)})" for t in targets if t not in went_red]
    noise = [f"{n}: {base.get(n, 'absent')} -> {st}" for n, st in broken.items()
             if n not in targets and base.get(n) in ("pass", "fail") and st in ("pass", "fail")
             and base[n] != st]
    reasons = [x for x in (problem, broken_problem) if x]
    reasons += [f"fault targets check(s) the scenario never ran: {missing}"] if missing and not problem else []
    reasons += [f"targeted check(s) not green in the baseline: {not_green}"] if not_green and not problem else []
    skipped = [t for t in targets if broken.get(t) == "skip"]
    reasons += [f"targeted check(s) skipped in the fault run: {skipped}"] if skipped else []
    if reasons:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "CAUGHT" if len(went_red) == len(targets) else "NOT CAUGHT"
    base_red = sorted(n for n, st in base.items() if st == "fail" and n not in targets)

    lines = [f"break-it-once {fault}: mutation {verdict}",
             f"  baseline: {base_dir}", f"  fault run: {broken_dir}",
             f"  targeted checks PASS -> FAIL: {went_red or 'none'}"]
    lines += [f"  targeted checks NOT turned red: {stayed}"] if stayed and not reasons else []
    lines += [f"  inconclusive: {r_}" for r_ in reasons]
    lines += [f"  noise (non-targeted checks that changed; they catch nothing): {noise or 'none'}"]
    lines += [f"  note: baseline already red on non-targeted: {base_red}"] if base_red else []
    print("slop: " + "\n".join(lines))
    if broken_dir:
        # Line 1 is the fault run's own status, red by design: label it so it is not read as the verdict.
        summary = broken_dir / "summary.txt"
        head, _, rest = summary.read_text().partition("\n")
        head += f"  (under injected fault {fault}: red expected; break verdict {verdict}, see the end / break.json)"
        summary.write_text(f"{head}\n{rest}\n" + "\n".join(lines) + "\n")
        (broken_dir / "break.json").write_text(json.dumps({
            "fault": fault, "verdict": verdict, "targets": list(targets), "went_red": went_red,
            "noise": noise, "inconclusive": reasons, "baseline": str(base_dir)}, indent=2))
    return verdict
