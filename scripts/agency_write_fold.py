#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "service" / "tests" / "_cell_probe"))
import cell_probe  # noqa: E402

from run_tests_parallel import RUN_FILE, discover_scripts  # noqa: E402
from send_site_inventory import inventory as send_inventory  # noqa: E402

SEND_JOBS = frozenset({"job:automation-exec", "job:full-ai-catchup-boot"})


def send_reason(h: dict, routes: frozenset[str]) -> str | None:
    if h["label"] in routes:
        return "send route"
    if h["label"] in SEND_JOBS:
        return "send job"
    modules = {frame.split(":", 1)[0] for frame in h["frames"]}
    modules.discard("server.py")
    mods = sorted(modules & send_inventory().modules)
    return f"send module {mods[0]}" if mods else None


def expected_scripts() -> set[str]:
    return {p.stem for p in discover_scripts(Path(cell_probe.__file__).resolve().parent.parent)}


def send_routes_from_scope(scope: dict) -> frozenset[str]:
    return send_inventory().route_labels({k: r.get("hint", {}) for k, r in scope["routes"].items()})


class Run(NamedTuple):
    hits: list[dict]
    errors: list[str]
    crashed: list[str]
    failed: list[str]
    run_id: str


def load(d: Path, mode: str) -> Run:
    manifest = d / "_scripts.txt"
    rc = d / "_rc.tsv"
    run = d / RUN_FILE
    if not manifest.is_file() or not rc.is_file() or not run.is_file():
        raise SystemExit(f"{d}: missing _scripts.txt, _rc.tsv or {RUN_FILE}")
    meta = json.loads(run.read_text())
    if meta.get("mode") != mode or not meta.get("run_id"):
        raise SystemExit(f"{d}: {RUN_FILE} says mode {meta.get('mode')!r}, want a {mode} run with a run_id")
    scripts = manifest.read_text().split()
    results = [ln.split("\t") for ln in rc.read_text().splitlines()]
    if any(len(row) != 2 for row in results):
        raise SystemExit(f"{d}: invalid _rc.tsv")
    statuses = {name: code for code, name in results}
    expected = expected_scripts()
    if len(scripts) != len(expected) or set(scripts) != expected:
        raise SystemExit(f"{d}: incomplete script manifest; missing {sorted(expected - set(scripts))}")
    if len(results) != len(expected) or statuses.keys() != expected:
        raise SystemExit(f"{d}: incomplete script exit records; missing {sorted(expected - statuses.keys())}")
    hits, errors = [], []
    failed = sorted(name for name, code in statuses.items() if code != "0")
    crashed = sorted(name for name in expected if not (d / f"{name}.jsonl").is_file())
    for f in sorted(d.glob("*.jsonl")):
        root, _, _ = f.stem.partition(".child-")
        if root not in expected:
            continue
        for line in f.read_text().splitlines():
            row = json.loads(line)
            (errors.append(f"{f.name}: {row['error']}") if "error" in row else hits.append(row))
    return Run(hits, errors, crashed, failed, meta["run_id"])


def key(h: dict) -> tuple:
    return (h["table"], h["op"], h["label"], h["site"])


def fold(block: Path, record: Path, out: Path, *, send_routes: frozenset[str]) -> int:
    runs = {"block": load(block, "block"), "record": load(record, "record")}
    if runs["block"].run_id == runs["record"].run_id:
        raise SystemExit(f"{block} and {record} are the same probe run")
    union: dict[tuple, dict] = {}
    for m, run in runs.items():
        for h in run.hits:
            u = union.setdefault(key(h), {k: h[k] for k in ("table", "op", "label", "class", "site", "frames")}
                                 | {"n": 0, "modes": [], "tests": []})
            u["n"] += h["n"]
            if m not in u["modes"]:
                u["modes"].append(m)
            if h["test"] not in u["tests"]:
                u["tests"].append(h["test"])
            if "stack" in h and "stack" not in u:
                u["stack"] = h["stack"]
    rows = sorted(union.values(), key=lambda u: (u["table"], u["op"], u["label"], u["site"]))
    for u in rows:
        u["tests"] = sorted(u["tests"])[:20]
    missing = [name for name, req in cell_probe.REQUIRED.items()
               if not any(cell_probe.is_required(u, *req) for u in rows)]
    send = [u | {"why": r} for u in rows if u["class"] != "local" and (r := send_reason(u, send_routes))]
    crashed = {m: r.crashed for m, r in runs.items() if r.crashed}
    errors = {m: r.errors for m, r in runs.items() if r.errors}
    inventory = {
        "tables": {t: sorted({u["class"] for u in rows if u["table"] == t}) for t in sorted({u["table"] for u in rows})},
        "writes": [{k: v for k, v in u.items() if k != "stack"} for u in rows if u["label"] != "thread"],
        "thread": [u for u in rows if u["label"] == "thread"],
        "diff": {"block_only": [list(key(u)) for u in rows if u["modes"] == ["block"]],
                 "record_only": [list(key(u)) for u in rows if u["modes"] == ["record"]]},
        "required_missing": missing,
        "crashed": crashed,
        "failed_scripts": {m: r.failed for m, r in runs.items()},
        "errors": errors,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "inventory.json").write_text(json.dumps(inventory, indent=1) + "\n")
    (out / "send_path.json").write_text(json.dumps({"replan_07": bool(send), "hits": send}, indent=1) + "\n")

    print(f"agency writes: {len(rows)} (table, op, label, site) rows over {len(inventory['tables'])} tables; "
          f"thread {len(inventory['thread'])}; block-only {len(inventory['diff']['block_only'])}, "
          f"record-only {len(inventory['diff']['record_only'])}")
    for t, cls in inventory["tables"].items():
        labels = sorted({u["label"] for u in rows if u["table"] == t})
        print(f"  {t} [{','.join(cls)}]: {len(labels)} label(s)")
    print(f"send-path hits: {len(send)} -> {out / 'send_path.json'}")
    for u in send:
        print(f"  {u['table']} {u['op']} {u['label']} {u['site']} ({u['why']})")
    if send:
        print("REPLAN 07")
    print(f"scripts that exited non-zero (hits up to the failure kept): "
          f"block {len(runs['block'].failed)}, record {len(runs['record'].failed)}")
    bad = bool(runs["record"].failed)
    if bad:
        print(f"✗ record: nonzero exits: {', '.join(runs['record'].failed)}")
    for m, names in crashed.items():
        bad = True
        print(f"✗ {m}: {len(names)} script(s) wrote no probe file (crashed): {', '.join(names)}")
    for m, errs in errors.items():
        bad = True
        print(f"✗ {m}: {len(errs)} probe error(s); first: {errs[0]}")
    if missing:
        bad = True
        print(f"✗ required writers missing: {', '.join(missing)}")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Union the CELL_PROBE block and record runs into the agency-write list.")
    ap.add_argument("block", type=Path)
    ap.add_argument("record", type=Path)
    ap.add_argument("--out", type=Path, help="default: the parent of BLOCK")
    a = ap.parse_args()
    scope = json.loads((Path(__file__).resolve().parents[1] / "service" / "cell_scope.json").read_text())
    return fold(a.block, a.record, a.out or a.block.parent, send_routes=send_routes_from_scope(scope))


if __name__ == "__main__":
    sys.exit(main())
