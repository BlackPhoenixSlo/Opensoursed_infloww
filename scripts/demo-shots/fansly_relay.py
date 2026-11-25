from __future__ import annotations

from datetime import datetime

import fansly_backend
import fansly_nova


def install(now_iso: str) -> None:
    shim = fansly_nova.FixtureShim(fansly_nova.raw_payloads(datetime.fromisoformat(now_iso)), "relay")
    real = fansly_backend.get_client
    fansly_backend.get_client = lambda aid: shim if aid == fansly_nova.ACCOUNT else real(aid)
