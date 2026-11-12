"""A current clip `_jev` (Jev v8, D53/D54) from a golden bench record, for suites that pin the qwen describe a clip
still runs (the V2 describe fed the clip's Jev facts) without running Jev itself (test_vault_jev does that)."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import vault_jev
import vault_jev_rules as rules

_GOLDEN = None


def video_jev(lane5: str = "free", *, review: str | None = None) -> dict:
    """A current, describe-feedable clip `_jev`: one golden pass-1-only frame of final lane `lane5`."""
    global _GOLDEN
    if _GOLDEN is None:
        p = Path(__file__).parent / "fixtures" / "vault_jev" / "golden.json.gz"
        _GOLDEN = json.load(gzip.open(p, "rt"))["images"]
    for g in _GOLDEN:
        d = rules.derive8({"resp": g["rec"]["resp"]})
        if (g["nn"] is not None and set(g["rec"]) == {"resp"} and g["expect"]["lane5"] == lane5
                and not d["need2"] and not d["needL"]):
            break
    else:
        raise LookupError(lane5)
    recs, nn = [{"resp": g["rec"]["resp"]}], dict(g["nn"])
    ds, top = rules.video_final(recs, [nn])
    frame = {"px": [1280, 720], "1": rules.pack(g["rec"]["resp"]["answers"], vault_jev.ORDER["1"]),
             "nn": [nn.get(k, 0) for k in vault_jev._NN], "lane5": ds[0]["lane5"]}
    return rules.video_blob(ds, top, recs, [nn], frames=[frame], passes=["1"], tok=1000, px=[[1280, 720]],
                            at="2026-11-12T00:00:00", src="720", review=review, nbytes=1)
