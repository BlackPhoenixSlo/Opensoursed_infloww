"""OF sessions: a captured session file per Creator, in the shape the bootstrap
writes (`headers` user_id / x_bc / x_of_rev / user_agent, `signing.rules` with
all five keys, already `signed_ok_at`, `cookies`), and `latest.json` pointed at
it, so the relay builds a REAL `OFClient` for the Creator (client_pool) instead
of failing on seed/creators.py's stub. Only for a run whose OnlyFans is
lib/of_wire.py (`OF_WIRE = True`): the client talks to `OF_API_ORIGIN`.
The signing rules are lib/browserbase.py's synthetic ones (never OF's)."""
from __future__ import annotations

import json

from . import World


def seed(w: World, creators: list[dict]) -> list[str]:
    from slop.lib.browserbase import signing  # lazy: imports service/of_signer

    rng = w.rng("of_sessions")
    rules = signing("0", "slop-rev", 0)["rules"]
    out = []
    for c in creators:
        a = w.sessions / "accounts" / c["id"]
        sess = {
            "headers": {"user_id": c["id"], "x_bc": "%040x" % rng.getrandbits(160),
                        "x_of_rev": "slop-of-rev-202610251200",
                        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                                      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"},
            "signing": {"rules": dict(rules), "signed_ok_at": w.now.strftime("%Y-%m-%dT%H:%M:%SZ")},
            "cookies": [{"name": "auth_id", "value": c["id"], "domain": ".onlyfans.com", "path": "/"},
                        {"name": "sess", "value": "%032x" % rng.getrandbits(128), "domain": ".onlyfans.com",
                         "path": "/"}],
        }
        (a / "session_wire.json").write_text(json.dumps(sess))
        (a / "latest.json").write_text(json.dumps({"session": "session_wire.json", "ts": w.now.isoformat() + "Z"}))
        out.append(c["id"])
    w.data["of_sessions"] = out
    return out
