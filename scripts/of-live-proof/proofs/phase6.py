"""Phase 6's proofs: the Unproven controls' Live check (docs/spec/ofm-not-yet/phase-06-unproven-live-check.md).

`IDS` is the twelve controls in the spec's "Proof order" (reads, then writes no Fan can see, then Fan-reaching
writes); `PROOFS` holds the ones built so far. Tickets 95-100 each append their proof to `PROOFS` in a `# ticket NN`
block (D29); the driver parks an id with no definition yet (`proofs.PENDING`). Each proof's capture record carries
the proof's `control` as `label` and its `page` in `pages` (proof_list.record_of).

Trigger steps, beside Phase 0's (phase0.py): ("images", selector) records every matching <img> in the Mirror frame
(its resolved src, whether it loaded, its natural width) once they have settled; ("goto", page) opens another Mirror
page (`new-post/state-vault`) in the same tab; ("dom", container, items, fields) records every shown item's fields
(of_browser.py `_dom_snapshot`, ticket 95). A proof's `check(seen)` judges what the browser saw and answers
{problems, parked, record} (proof_core.Proof); `seen["responses"]` is every app-browser answer in the proof's window,
and the check picks its own. The definitions live in phase6_reads.py (94, 95) and phase6_writes.py (96, 97, 99, 100);
this module assembles them, re-exporting their names.

  python -I scripts/of-live-proof/proofs/phase6.py --ids                 all twelve ids, in proof order
  python -I scripts/of-live-proof/proofs/phase6.py --check-records DIR   proof_list's check over PROOFS, then the
                                                                         spec's Acceptance check over all twelve ids
  python -I scripts/of-live-proof/proofs/phase6.py --check-sweep SWEEP DIR   proof_list's, over PROOFS
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:   # run as a script under -I: the harness dir is not on sys.path
    sys.path.insert(0, str(HERE))
import proof_list  # noqa: E402
from proofs.phase6_reads import *  # noqa: E402,F401,F403
from proofs.phase6_reads import (HOME_STORY_STRIP, NOTIFICATIONS_TIPS, PROFILE_HIGHLIGHTS,  # noqa: E402
                                 STATEMENTS_PAYOUT_ROWS, VAULT_THUMBNAILS)
from proofs.phase6_writes import *  # noqa: E402,F401,F403
from proofs.phase6_writes import (NEW_POST_DEDUPE, NEW_POST_UPLOAD, QUEUE_PUBLISH_NOW, QUEUE_SEND_NOW,  # noqa: E402
                                  VAULT_CUSTOMIZE_ORDER)

ROOT = HERE.parents[1]
CAPTURES = ROOT / "docs" / "of-manager" / "captures"

IDS = (
    # 1. reads
    "vault--thumbnails", "notifications--tips", "home--story-strip", "profile--highlights", "statements--payout-rows",
    # 2. writes no Fan can see
    "vault--customize-order-save", "new-post--upload", "new-post--dedupe-duplicate-id", "new-post--cotag-scheduled",
    # 3. Fan-reaching writes
    "queue--publish-now", "new-post--cotag-immediate", "queue--send-message-right-now",
)

PROOFS = (
    # ticket 94
    VAULT_THUMBNAILS,
    # ticket 95
    NOTIFICATIONS_TIPS, HOME_STORY_STRIP, PROFILE_HIGHLIGHTS, STATEMENTS_PAYOUT_ROWS,
    # ticket 96
    VAULT_CUSTOMIZE_ORDER,
    # ticket 100
    QUEUE_SEND_NOW,
    # ticket 97
    NEW_POST_UPLOAD, NEW_POST_DEDUPE,
    # ticket 99
    QUEUE_PUBLISH_NOW,
)
assert {p.id for p in PROOFS} <= set(IDS), "a Phase 6 definition outside IDS"


# ── the spec's Acceptance record check ──

def record_problems(folder: Path = CAPTURES, ids=IDS) -> list:
    """The spec's Acceptance record-check block as a function (it reads `<id>.json`, not proof_list's label match, as
    the spec does): (id, problem) for every Phase 6 control whose capture record is missing or unreadable, is neither a
    live pass with evidence nor parked with a reason, carries a FAILED undo, or (Publish now) passes without its
    `hidden-dedupe` branch (D13)."""
    recs = dict(proof_list.load_records(Path(folder))[0])
    bad = []
    for i in ids:
        p = (recs.get(f"{i}.json") or {}).get("proof")
        if not isinstance(p, dict):
            bad.append((i, "no readable capture record with a proof"))
            continue
        ok = (p.get("kind") == "live" and p.get("verdict") == "pass" and p.get("evidence")) or \
             (p.get("verdict") == "parked" and p.get("reason"))
        if not ok or p.get("undo") == "FAILED":
            bad.append((i, p))
        if i == "queue--publish-now" and p.get("verdict") == "pass" \
                and not (p.get("branches") or {}).get("hidden-dedupe"):
            bad.append((i, "no hidden-dedupe branch"))
    return bad


def main(argv=None) -> int:
    """proof_list's checks over `PROOFS`, except `--ids` prints all twelve `IDS` (the spec's `run.sh --proof "$(...)"`;
    the driver parks the pending ones) and `--check-records` adds the spec's id-file check over all twelve."""
    ap = argparse.ArgumentParser(prog="phase6.py")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--ids", action="store_true", help="print all twelve ids, comma-separated, in proof order")
    g.add_argument("--check-records", metavar="DIR", type=Path)
    g.add_argument("--check-sweep", nargs=2, metavar=("SWEEP", "DIR"))
    a = ap.parse_args(argv)
    if a.ids:
        print(",".join(IDS))
        return 0
    cmd, folder = ("check-records", a.check_records) if a.check_records else ("check-sweep", Path(a.check_sweep[1]))
    if not folder.is_dir():
        print(f"{cmd}: {folder} is not a directory", file=sys.stderr)
        return 2
    if a.check_records:
        lines = proof_list.check_records(PROOFS, folder)
        lines += [f"{i}: {why}" for i, why in record_problems(folder)]
    else:
        lines = proof_list.check_sweep(PROOFS, json.loads(Path(a.check_sweep[0]).read_text()), folder)
    for line in lines:
        print(line)
    print(f"{cmd}: {len(PROOFS)} proofs, {len(IDS)} ids, {len(lines)} problems")
    return 1 if lines else 0


if __name__ == "__main__":
    sys.exit(main())
