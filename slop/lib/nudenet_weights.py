"""NudeNet 640m weights for the vault Jev scenarios, kept where macOS does not clean them.

They used to sit in /tmp/nn-weights, which macOS's periodic cleanup empties (gone 2026-11-16: both Jev scenarios
INFRA every night after). Now: `NUDENET_640M_PATH` if set, else ~/.cache/slop/nudenet-640m.onnx, fetched once with
the same URL and md5 as the Dockerfile (a different file is refused, as the product refuses it).
"""
from __future__ import annotations

import hashlib
import os
import urllib.request
from pathlib import Path

URL = "https://api.github.com/repos/notAI-tech/NudeNet/releases/assets/176832019"   # = Dockerfile NUDENET_640M_URL
MD5 = "d04bbbd55428dc307b379ae1dfa55314"                                             # = service/vault_jev.NUDENET_MD5
DEFAULT = Path.home() / ".cache" / "slop" / "nudenet-640m.onnx"
PATH = os.environ.get("NUDENET_640M_PATH") or str(DEFAULT)


def _md5(p: Path) -> str:
    h = hashlib.md5()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure() -> str:
    """The weights' path, fetched first if missing (only for the default path: a set env path is the caller's)."""
    p = Path(PATH)
    if p.is_file():
        return PATH
    if p != DEFAULT:
        raise RuntimeError(f"slop: NudeNet weights not at {PATH} (NUDENET_640M_PATH): Jev refuses without them")
    p.parent.mkdir(parents=True, exist_ok=True)
    part = p.with_suffix(".part")
    req = urllib.request.Request(URL, headers={"Accept": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=300) as r, part.open("wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    if (got := _md5(part)) != MD5:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"slop: fetched NudeNet weights md5 {got} != {MD5}")
    part.replace(p)
    return PATH
