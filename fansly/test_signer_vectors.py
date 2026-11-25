from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import fansly_signer as signer

ANONYMIZED_ID_PREFIX = "700"
VECTORS = Path(__file__).resolve().parent / "fixtures" / "signer_vectors.json"


def main() -> int:
    doc = json.loads(VECTORS.read_text())
    fails: list[str] = []
    fn = doc["function"]
    if hashlib.sha256(fn["text"].encode()).hexdigest() != fn["sha256"]:
        fails.append("function text does not match its recorded sha256")
    anchor = doc["anchor"]
    anchor_id_anonymized_for_public = anchor["device_id"].startswith(ANONYMIZED_ID_PREFIX)
    vectors = [*doc["vectors"], *([] if anchor_id_anonymized_for_public else [anchor])]
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
