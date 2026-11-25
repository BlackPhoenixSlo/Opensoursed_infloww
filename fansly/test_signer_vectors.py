from __future__ import annotations

import json
import sys
from pathlib import Path

import fansly_signer as signer

ANONYMIZED_ANCHOR_DEVICE_ID = "700174924320792578"
VECTORS = Path(__file__).resolve().parent / "fixtures" / "signer_vectors.json"


def main() -> int:
    doc = json.loads(VECTORS.read_text())
    fails: list[str] = []
    anchor = doc.get("anchor")
    vectors = list(doc["vectors"])
    if not anchor:
        fails.append("missing browser anchor")
    elif anchor["device_id"] == ANONYMIZED_ANCHOR_DEVICE_ID:
        print("SKIP anchor: anonymized id")
    else:
        vectors.append(anchor)
    if not doc["vectors"]:
        fails.append("no vectors")
    for v in vectors:
        want = v["digest"]
        got = signer.client_check(v["path"], v["device_id"], v["check_key"])
        if got != want:
            fails.append(f"{v['path']} / {v['device_id']} / {v['check_key']}: {got} != {want}")
        url = f"https://apiv3.fansly.com{v['path']}?ngsw-bypass=true"
        if signer.client_check(url, v["device_id"], v["check_key"]) != want:
            fails.append(f"{url}: query or host leaked into the digest")
    for f in fails:
        print(f"  FAIL {f}", file=sys.stderr)
    if fails:
        return 1
    print(f"signer: {len(vectors)}/{len(vectors)} vectors from {doc['source']} ({doc['runtime']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
