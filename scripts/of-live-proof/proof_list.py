"""proof_list: the command line every Phase's proofs file runs (`proofs/phase<N>.py`), over that Phase's `PROOFS`.

    --ids                        print the comma-joined proof ids (for `run.sh --of fake --proof "$(...)"`)
    --check-records <dir>        exit 1 unless every proof has exactly one capture record in <dir> whose
                                 `proof.verdict` is `pass`, or `parked` with a non-empty `reason`, and whose
                                 `branches` verdicts are each `pass` or `parked: <reason>`, and which carries
                                 each of the proof's `hosts` as a `facts.<name>_host` (ticket 53)
    --check-sweep <sweep> <dir>  exit 1 if a proof whose record shows `kind: live, verdict: pass` is still in the
                                 sweep's `ny` for its page, or a proof without that pass is missing from it (D1: the
                                 Not-yet title drops on a Live-proof pass and only then), or its page is not swept;
                                 a proof tagged `never-titled` (never had the title): each of its sweep labels (its
                                 `control` split on `NEVER_TITLED_SEP`) absent from `ny`, always, and on its page's
                                 Mirror HTML (`on_mirror_page`)
    --overlay <sweep>            with --check-sweep, repeatable: each overlay's pages replace the sweep's (`overlaid`;
                                 a re-swept page set over a frozen dated file, ticket 10's phase1-v2 precedent)

The sweep is `dead.py --sweep-out`'s file, [[page, {"ny", "dis", "ro"}]]. Exit 2 when <dir> is missing (a mistyped
path never reads as clean, as capture_record.py check-records). docs/spec/ofm-not-yet/phase-02-content-chat-writes.md
(Interfaces, `proofs/phase2.py`).

A proof's record is the one whose `label` is the proof's `control` and whose `pages` hold the proof's `page`
(`record_of`; the Mirror check's check 1, scripts/of-mirror-check/phase_check.py, finds it the same way, and reads the
Live-proof pass with `live_passed`, so check 1 and --check-sweep never disagree on a control's title).
ASSUMPTION: records are matched by label and page, not by a record id on the Proof (rung 5: Phase 0's Proof shape
stays as is, and both carry the sweep's page and label); overturned if two controls on one page share a label, which
then needs a record id field on Proof.
"""
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

MIRROR_PAGES = Path(__file__).resolve().parents[2] / "app" / "public" / "of-mirror" / "pages"   # /of-mirror/pages/<page>.html


def on_mirror_page(page: str, label: str) -> bool:
    """Whether `page`'s Mirror HTML has a control the sweep would label `label`: an `aria-label` or `placeholder` of it,
    or an element whose whole text it is (sweep_diff.LABEL_JS, read statically: a made-up label is never there).
    ASSUMPTION: matching the static file is enough (rung 5: the binders do not rename these controls); overturned by a
    label that only a binder writes, which then needs dead.py's live sweep."""
    try:
        doc = (MIRROR_PAGES / f"{page.partition('?')[0]}.html").read_text()
    except OSError:
        return False
    esc = re.escape(html.escape(label, quote=True))
    return bool(re.search(rf'(?:aria-label|placeholder)="{esc}"|>\s*{esc}\s*<', doc))


def load_records(folder: Path) -> tuple[list, list]:
    """(records, problem lines) for every *.json directly in `folder`."""
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
    """(file, record, problem): the proof's one capture record, else a problem."""
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
    """The hosts a capture record names (ticket 53): every string `facts.<name>_host`."""
    facts = rec.get("facts")
    return {v for k, v in facts.items() if str(k).endswith("_host") and isinstance(v, str)} \
        if isinstance(facts, dict) else set()


def overlaid(base: list, *overlays: list) -> list:
    """`base` (a sweep, [[page, found]]) with each page an overlay also holds replaced by the overlay's, in base's order;
    an overlay's other pages are dropped (as Phase 0's Acceptance builds its ny baseline from the phase1-v2 overlay)."""
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
        if NEVER_TITLED in proof.tags:   # Wired before this effort: D1 has no title to drop, pass or not
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
