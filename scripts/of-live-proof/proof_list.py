from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_record import _proof_problems  # noqa: E402
from proof_core import NEVER_TITLED, NEVER_TITLED_SEP  # noqa: E402

MIRROR_PAGES = Path(__file__).resolve().parents[2] / "app" / "public" / "of-mirror" / "pages"


def on_mirror_page(page: str, label: str) -> bool:
    try:
        doc = (MIRROR_PAGES / f"{page.partition('?')[0]}.html").read_text()
    except OSError:
        return False
    esc = re.escape(html.escape(label, quote=True))
    return bool(re.search(rf'(?:aria-label|placeholder)="{esc}"|>\s*{esc}\s*<', doc))


def load_records(folder: Path) -> tuple[list, list]:
    recs, bad = [], []
    for f in sorted(folder.glob("*.json")):
        try:
            rec = json.loads(f.read_text())
        except (ValueError, UnicodeDecodeError):
            bad.append(f"{f.name}: not valid JSON")
            continue
        if isinstance(rec, dict):
            recs.append((f.name, rec))
    return recs, bad


def record_of(proof, recs) -> tuple[str | None, dict | None, str | None]:
    mine = [(n, r) for n, r in recs if r.get("label") == proof.control and proof.page in (r.get("pages") or [])]
    if not mine:
        return None, None, f"{proof.id}: no capture record for {proof.page} {proof.control!r}"
    if len(mine) > 1:
        return None, None, f"{proof.id}: {len(mine)} capture records ({', '.join(n for n, _ in mine)})"
    return mine[0][0], mine[0][1], None


def live_passed(rec: dict | None) -> bool:
    p = (rec or {}).get("proof") or {}
    return p.get("kind") == "live" and p.get("verdict") == "pass"


def check_records(proofs, folder: Path) -> list:
    recs, out = load_records(folder)
    for proof in proofs:
        name, rec, problem = record_of(proof, recs)
        if problem:
            out.append(problem)
            continue
        p = rec.get("proof")
        if not isinstance(p, dict):
            out.append(f"{proof.id}: {name}: no proof result")
            continue
        out += [f"{proof.id}: {name}: {x}" for x in _proof_problems(p)]
        if p.get("verdict") == "fail":
            out.append(f"{proof.id}: {name}: proof.verdict: a proof list record must be pass or parked")
        named = record_hosts(rec)
        out += [f"{proof.id}: {name}: host {h} is not named from the capture (no facts.<name>_host holds it)"
                for h in proof.hosts if h not in named]
    return out


def record_hosts(rec: dict) -> set:
    facts = rec.get("facts")
    return {v for k, v in facts.items() if str(k).endswith("_host") and isinstance(v, str)} \
        if isinstance(facts, dict) else set()


def overlaid(base: list, *overlays: list) -> list:
    out = [list(x) for x in base]
    for ov in overlays:
        by = dict(ov)
        out = [[page, by.get(page, found)] for page, found in out]
    return out


def check_sweep(proofs, sweep: list, folder: Path) -> list:
    recs, out = load_records(folder)
    ny = {page: (found or {}).get("ny") or [] for page, found in sweep}
    for proof in proofs:
        if proof.page not in ny:
            out.append(f"{proof.id}: page {proof.page} not in the sweep")
            continue
        passed = live_passed(record_of(proof, recs)[1])
        titled = proof.control in ny[proof.page]
        if NEVER_TITLED in proof.tags:
            for label in proof.control.split(NEVER_TITLED_SEP):
                if label in ny[proof.page]:
                    out.append(f"{proof.id}: tagged never-titled but {proof.page} {label!r} still titled")
                elif not on_mirror_page(proof.page, label):
                    out.append(f"{proof.id}: tagged never-titled but {proof.page} has no control labelled {label!r}")
        elif passed and titled:
            out.append(f"{proof.id}: Live proof passed but {proof.page} {proof.control!r} still has the Not-yet title")
        elif not passed and not titled:
            out.append(f"{proof.id}: no Live-proof pass but {proof.page} {proof.control!r} lost the Not-yet title")
    return out


def main(proofs, argv=None, prog="proofs") -> int:
    ap = argparse.ArgumentParser(prog=prog)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--ids", action="store_true", help="print the comma-joined proof ids")
    g.add_argument("--check-records", metavar="DIR", type=Path)
    g.add_argument("--check-sweep", nargs=2, metavar=("SWEEP", "DIR"))
    ap.add_argument("--overlay", action="append", default=[], type=Path, metavar="SWEEP",
                    help="with --check-sweep: a sweep whose pages replace the base sweep's (repeatable, in order)")
    a = ap.parse_args(argv)
    if a.overlay and not a.check_sweep:
        ap.error("--overlay needs --check-sweep")
    if a.ids:
        print(",".join(p.id for p in proofs))
        return 0
    cmd, folder = ("check-records", a.check_records) if a.check_records else ("check-sweep", Path(a.check_sweep[1]))
    if not folder.is_dir():
        print(f"{cmd}: {folder} is not a directory", file=sys.stderr)
        return 2
    if a.check_records:
        lines = check_records(proofs, folder)
    else:
        sweep = overlaid(json.loads(Path(a.check_sweep[0]).read_text()), *(json.loads(f.read_text()) for f in a.overlay))
        lines = check_sweep(proofs, sweep, folder)
    for line in lines:
        print(line)
    print(f"{cmd}: {len(proofs)} proofs, {len(lines)} problems")
    return 1 if lines else 0
