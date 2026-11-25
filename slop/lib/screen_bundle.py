from __future__ import annotations

LATE = {"upstream_status": "bundle_deadline"}
CHAT_SCREEN_PATH = "/admin/screens/chat"
DASH_SCREEN_PATH = "/admin/screens/dashboard"
NO_BUNDLES_COOKIE = "slop_no_bundles"


def bundle_view(env: dict | None) -> dict | None:
    if env is None:
        return None
    v: dict = {"errors": [], "refreshing": [], "asOf": env.get("asOf"), "duplicates": []}
    seen: set[tuple] = set()
    for a in env.get("answers") or []:
        pair = (a["accountId"], a["read"])
        if pair in seen:
            v["duplicates"].append(pair)
            continue
        seen.add(pair)
        if "status" in a:
            v["errors"].append(a)
            continue
        if a.get("refreshing"):
            v["refreshing"].append({"accountId": a["accountId"], "read": a["read"]})
        if a["accountId"] is None:
            v[a["read"]] = a["body"]
        else:
            v.setdefault(a["read"], {})[a["accountId"]] = a["body"]
    return v


def late_reads(v: dict | None) -> set[tuple[str | None, str]]:
    return {(e["accountId"], e["read"]) for e in (v or {}).get("errors", [])
            if e["status"] == 504 and e["detail"] == LATE}
