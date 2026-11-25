from __future__ import annotations

import hashlib
import os
import urllib.request
from pathlib import Path

# Same URL and md5 as the Dockerfile (NUDENET_640M_URL) and service/vault_jev.NUDENET_MD5; cached outside /tmp, which macOS cleanup empties.
URL = "https://api.github.com/repos/notAI-tech/NudeNet/releases/assets/176832019"
MD5 = "d04bbbd55428dc307b379ae1dfa55314"
DEFAULT = Path.home() / ".cache" / "slop" / "nudenet-640m.onnx"
PATH = os.environ.get("NUDENET_640M_PATH") or str(DEFAULT)


def _md5(p: Path) -> str:
    h = hashlib.md5()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure() -> str:
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
