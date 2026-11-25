from __future__ import annotations

import json

from . import World


def token(account_id: str) -> str:
    return f"slop-fansly-{account_id}"


def seed(w: World, creators: list[dict]) -> list[str]:
    out = []
    for c in creators:
        a = w.sessions / "accounts" / c["id"]
        meta = json.loads((a / "meta.json").read_text())
        (a / "meta.json").write_text(json.dumps({**meta, "platform": "fansly"}))
        (a / "fansly_session.json").write_text(json.dumps({
            "accountId": c["id"], "token": token(c["id"]), "device_id": f"slop-device-{c['id']}",
            "device_id_ts": w.now.timestamp(),
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/141.0.0.0 Safari/537.36"}))
        out.append(c["id"])
    w.data["fansly_creators"] = out
    return out
