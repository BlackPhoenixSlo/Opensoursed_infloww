from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import proof_list  # noqa: E402
from proofs.phase6_reads import *  # noqa: E402,F401,F403
from proofs.phase6_reads import (HOME_STORY_STRIP, NOTIFICATIONS_TIPS, PROFILE_HIGHLIGHTS,  # noqa: E402
                                 STATEMENTS_PAYOUT_ROWS, VAULT_THUMBNAILS)
from proofs.phase6_writes import *  # noqa: E402,F401,F403
from proofs.phase6_writes import (NEW_POST_DEDUPE, NEW_POST_UPLOAD, QUEUE_PUBLISH_NOW, QUEUE_SEND_NOW,  # noqa: E402
                                  VAULT_CUSTOMIZE_ORDER)
from proofs.phase6_cotag import *  # noqa: E402,F401,F403  (ticket 98)
from proofs.phase6_cotag import NEW_POST_COTAG_IMMEDIATE, NEW_POST_COTAG_SCHEDULED  # noqa: E402  (ticket 98)

ROOT = HERE.parents[1]
CAPTURES = ROOT / "docs" / "of-manager" / "captures"

IDS = (
    "vault--thumbnails", "notifications--tips", "home--story-strip", "profile--highlights", "statements--payout-rows",
    "vault--customize-order-save", "new-post--upload", "new-post--dedupe-duplicate-id", "new-post--cotag-scheduled",
    "queue--publish-now", "new-post--cotag-immediate", "queue--send-message-right-now",
)

PROOFS = (
    VAULT_THUMBNAILS,
    NOTIFICATIONS_TIPS, HOME_STORY_STRIP, PROFILE_HIGHLIGHTS, STATEMENTS_PAYOUT_ROWS,
    VAULT_CUSTOMIZE_ORDER,
    QUEUE_SEND_NOW,
    NEW_POST_UPLOAD, NEW_POST_DEDUPE,
    QUEUE_PUBLISH_NOW,
    NEW_POST_COTAG_SCHEDULED, NEW_POST_COTAG_IMMEDIATE,
)
assert {p.id for p in PROOFS} <= set(IDS), "a Phase 6 definition outside IDS"



def record_problems(folder: Path = CAPTURES, ids=IDS) -> list:
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
