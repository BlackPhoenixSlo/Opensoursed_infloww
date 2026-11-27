from __future__ import annotations

import json
import re
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

from gate import SELFTEST_SESSION_PREFIX, read_json, write_json

PLAN_PATH = Path(__file__).resolve().parent / "mirror_plan.json"
FANSLY_ORIGIN = "https://fansly.com"
PLACEHOLDERS = frozenset({"username", "groupId", "albumId", "listId", "postId", "coperformerId"})
MAX_TRACER_PAGES = 5

REQUIRED = {
    "routes": [
        "/home", "/{username}", "/{username}/media", "/{username}/media/pictures", "/{username}/followers",
        "/{username}/following", "/post/{postId}", "/messages", "/messages/{groupId}", "/creator/chat",
        "/notifications", "/creator", "/creator/vault", "/creator/vault/{albumId}",
        "/creator/stats/overview", "/creator/stats/content", "/creator/stats/audience",
        "/creator/stats/earnings", "/creator/stats/streams", "/creator/wallet/payouts",
        "/creator/wallet/history", "/creator/payout/documentation", "/creator/plans",
        "/creator/trackinglinks", "/creator/subscribers", "/creator/followers", "/creator/topsupporters",
        "/creator/uploads", "/creator/management", "/creator/streaming", "/creator/coperformers",
        "/creator/coperformers/requests", "/creator/coperformers/new", "/creator/coperformers/new/manual",
        "/creator/coperformers/new/request", "/creator/coperformers/new/sign",
        "/creator/coperformers/{coperformerId}", "/scheduled", "/lists", "/lists/{listId}", "/bookmarks",
        "/lists/blocked_accounts", "/lists/muted_accounts", "/lists/vip_accounts",
        "/lists/dm_permission_bypass", "/bookmarks/2007", "/subscriptions", "/settings/account", "/settings/profile",
        "/settings/notifications", "/settings/display", "/settings/payments", "/settings/privacy",
        "/settings/sessions", "/settings/connections", "/settings/about",
    ],
    "states": [
        "home/state-avatar-menu", "home/state-balance-menu", "home/state-post-create",
        "profile/state-post-menu", "profile/state-edit", "profile/state-wall-manage",
        "profile/state-locked-text-story", "messages/state-broadcast-composer",
        "messages/state-broadcast-queue", "messages/state-broadcast-history", "messages/thread/state-menu",
        "messages/thread/state-reaction-picker", "messages/thread/state-notes-edit",
        "messages/thread/state-list-select", "messages/thread/state-message-schedule",
        "messages/thread/state-read-receipts", "creator/vault/state-album-create", "creator/vault/state-upload",
        "creator/stats/audience/state-fan-detail", "creator/plans/state-tier-create",
        "creator/plans/state-promotion-create", "creator/plans/state-promotion-edit",
        "creator/plans/state-gift-code-create", "creator/trackinglinks/state-create",
        "creator/management/state-session-create", "lists/list/state-edit", "lists/list/state-add-account",
        "lists/list/state-row-menu", "settings/account/state-password-change",
        "settings/account/state-email-change", "settings/account/state-2fa",
        "settings/account/state-username-change", "settings/payments/state-add-payment-method",
        "settings/sessions/state-session-close",
    ],
}

OUT_ROUTES = ("/explore", "/fyp", "/search", "/tag", "/tags", "/affiliates", "/leaderboard",
              "/application", "/live", "/legal", "/tos", "/terms", "/privacy", "/cookies", "/dmca", "/admin")


def load_plan(path: Path | None = None) -> list:
    return json.loads((path or PLAN_PATH).read_text())


def _bad_id(pid) -> bool:
    if not isinstance(pid, str) or not pid or pid.startswith("/") or pid.endswith("/"):
        return True
    return any(seg in ("", ".", "..") for seg in pid.split("/")) or not re.fullmatch(r"[A-Za-z0-9/_-]+", pid)


def check_plan(plan, required) -> list[str]:
    if not isinstance(plan, list):
        return ["the plan is not a list"]
    errors: list[str] = []
    by_id: dict[str, dict] = {}
    for i, e in enumerate(plan):
        if not isinstance(e, dict):
            errors.append(f"entry {i} is not an object")
            continue
        pid = e.get("id")
        if _bad_id(pid):
            errors.append(f"entry {i}: id {pid!r} is not a path-like id inside the capture root")
            continue
        if pid in by_id:
            errors.append(f"duplicate id {pid}")
        by_id[pid] = e
        if e.get("kind") not in ("page", "state"):
            errors.append(f"{pid}: kind {e.get('kind')!r} is not page or state")
        url = e.get("url")
        if not isinstance(url, str) or not url.startswith("/"):
            errors.append(f"{pid}: url {url!r} is not a path template")
        else:
            for name in re.findall(r"\{([^}]*)\}", url):
                if name not in PLACEHOLDERS:
                    errors.append(f"{pid}: unknown placeholder {{{name}}}")
    for pid, e in by_id.items():
        if e.get("kind") != "state":
            continue
        parent = by_id.get(e.get("parent"))
        if parent is None:
            errors.append(f"{pid}: parent {e.get('parent')!r} is not in the plan")
        elif parent.get("kind") != "page":
            errors.append(f"{pid}: parent {e['parent']} is a State, not a page")
        elif not pid.startswith(f"{e['parent']}/state-"):
            errors.append(f"{pid}: a State's id is <parent>/state-<name>")
    tracer_pages = [p for p, e in by_id.items() if e.get("tracer") and e.get("kind") == "page"]
    if len(tracer_pages) > MAX_TRACER_PAGES:
        errors.append(f"{len(tracer_pages)} tracer pages; at most {MAX_TRACER_PAGES}")
    if not any(e.get("tracer") and e.get("kind") == "state" for e in by_id.values()):
        errors.append("no tracer State")
    if required:
        page_urls = {e.get("url") for e in by_id.values() if e.get("kind") == "page"}
        for route in required.get("routes", ()):
            if route not in page_urls:
                errors.append(f"ticket 01 route {route} has no page entry")
        states = {p for p, e in by_id.items() if e.get("kind") == "state"}
        for sid in required.get("states", ()):
            if sid not in states:
                errors.append(f"ticket 01 State {sid} has no state entry")
    return errors


def fill(template: str, values: dict) -> str:
    return re.sub(r"\{([^}]*)\}", lambda m: str(values.get(m.group(1), m.group(0))), template)


def _template_re(template: str) -> re.Pattern:
    parts = re.split(r"(\{[^}]*\})", template.rstrip("/") or "/")
    return re.compile("".join("[^/]+" if p.startswith("{") else re.escape(p) for p in parts if p))


def path_matches(template: str, path: str) -> bool:
    return bool(_template_re(template).fullmatch(path.rstrip("/") or "/"))


def url_matches(template: str, url: str) -> bool:
    s = urllib.parse.urlsplit(url or "")
    return f"{s.scheme}://{s.netloc}".lower() == FANSLY_ORIGIN and path_matches(template, s.path)


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def same_origin_paths(html: str) -> set[str]:
    p = _Links()
    p.feed(html)
    out = set()
    for href in p.hrefs:
        s = urllib.parse.urlsplit(urllib.parse.urljoin(FANSLY_ORIGIN + "/", href))
        if f"{s.scheme}://{s.netloc}".lower() == FANSLY_ORIGIN:
            out.add(s.path.rstrip("/") or "/")
    return out


def _out_route(path: str) -> bool:
    return path == "/" or any(path == r or path.startswith(r + "/") for r in OUT_ROUTES)


def _inside(root: Path, rel: str) -> bool:
    try:
        return (root / rel).resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def read_audits(root: Path) -> dict:
    out = {}
    for f in sorted((root / "sessions").glob("*/audit.json")):
        a = read_json(f)
        if isinstance(a, dict):
            out[f.parent.name] = a
    return out


def _identities(root: Path, passed: set) -> list[dict]:
    found: dict[str, dict] = {}
    for sid in sorted(passed):
        for i in read_json(root / "sessions" / sid / "identities.json") or []:
            if isinstance(i, dict) and i.get("role") in ("creator", "fan"):
                found[i["role"]] = {k: str(i.get(k) or "") for k in ("username", "displayName", "accountId")}
    return [{"role": r, **found[r]} for r in ("creator", "fan") if r in found]


def _shared(values):
    vals = {v for v in values if v}
    return vals.pop() if len(vals) == 1 else None


def build_manifest(root: Path, plan: list, audits: dict) -> dict:
    by_id = {e["id"]: e for e in plan}
    passed = {sid for sid, a in audits.items() if a.get("passed") is True}
    entries, unaudited, not_in_plan, savers = [], [], [], set()
    pages = root / "pages"
    for meta_path in sorted(pages.rglob("*.meta.json")) if pages.is_dir() else ():
        m = read_json(meta_path)
        if not isinstance(m, dict):
            continue
        pid = str(meta_path.relative_to(pages))[: -len(".meta.json")]
        savers.add(str(m.get("session") or ""))
        if m.get("session") not in passed:
            unaudited.append(pid)
            continue
        if pid not in by_id:
            not_in_plan.append(pid)
            continue
        files = {k: f"pages/{pid}{ext}" for k, ext in (("file", ".html"), ("meta", ".meta.json"), ("png", ".png"))}
        if not all(_inside(root, f) for f in files.values()) or not (root / files["file"]).exists():
            continue
        entries.append({
            "id": pid, "kind": by_id[pid]["kind"],
            **{k: m.get(k) for k in ("url", "final_url", "state", "opener", "settled_selector", "reset",
                                     "bundle_hash", "theme", "session")},
            **{k: int(m.get(k) or 0) for k in ("canvases", "shadow_roots", "iframes")},
            **files})
    captured = {e["id"] for e in entries}
    skipped = []
    for s in read_json(root / "skipped.json") or []:
        if isinstance(s, dict) and s.get("id") not in captured and by_id.get(s.get("id"), {}).get("optional"):
            skipped.append({"id": s["id"], "reason": str(s.get("reason") or ""),
                            "tried": [str(t) for t in s.get("tried") or []]})
    skipped_ids = {s["id"] for s in skipped}
    assets = [{"url": a["url"], "file": a["file"]} for a in read_json(root / "assets.json") or []
              if isinstance(a, dict) and a.get("url") and str(a.get("file", "")).startswith("static/")
              and _inside(root, a["file"]) and (root / a["file"]).is_file()]
    identities = _identities(root, passed)
    creator = next((i for i in identities if i["role"] == "creator"), None)
    values = {"username": creator["username"]} if creator and creator["username"] else {}

    missing = [pid for pid, e in by_id.items() if pid not in captured
               and not (e.get("optional") and pid in skipped_ids)]
    covered_urls = set()
    for e in entries:
        for u in (e.get("url"), e.get("final_url")):
            if u:
                covered_urls.add(urllib.parse.urlsplit(u).path.rstrip("/") or "/")
    templates = [fill(e["url"], values) for e in plan if e.get("kind") == "page"]
    uncovered = set()
    for e in entries:
        if e["kind"] == "page" and (e["id"] == "creator" or e["id"].startswith("settings/")):
            for path in same_origin_paths((root / e["file"]).read_text(errors="replace")):
                if not (path in covered_urls or _out_route(path) or any(path_matches(t, path) for t in templates)):
                    uncovered.add(path)
    roles = {i["role"] for i in identities if i["username"] and i["accountId"]}
    complete = bool(entries) and not missing and not uncovered and roles == {"creator", "fan"}
    sessions = sorted(s for s in set(audits) | savers if s and not s.startswith(SELFTEST_SESSION_PREFIX))
    verdict = {s: "pass" if s in passed else "fail" if s in audits else "unaudited" for s in sessions}
    return {
        "audit": {"passed": complete,
                  "sessions": [{"id": s, "verdict": verdict[s]} for s in sessions]},
        "bundle_hash": _shared(e.get("bundle_hash") for e in entries),
        "theme": _shared(e.get("theme") for e in entries),
        "complete": complete,
        "identities": identities,
        "entries": entries,
        "skipped": skipped,
        "unaudited": sorted(unaudited),
        "not_in_plan": sorted(not_in_plan),
        "assets": assets,
        "missing": missing,
        "uncovered_links": sorted(uncovered),
    }


def cmd_plan(args) -> int:
    plan = load_plan(args.plan)
    errors = check_plan(plan, REQUIRED)
    for e in errors:
        print(f"  plan: {e}")
    pages = sum(1 for e in plan if isinstance(e, dict) and e.get("kind") == "page")
    print(f"plan {'OK' if not errors else 'BROKEN'}: {pages} pages, {len(plan) - pages} states, "
          f"{len(errors)} error(s)")
    return 0 if not errors else 1


def cmd_manifest(args, root: Path) -> int:
    m = build_manifest(root, load_plan(args.plan), read_audits(root))
    write_json(root / "manifest.json", m)
    print(f"manifest: complete={str(m['complete']).lower()} audit.passed={str(m['audit']['passed']).lower()} "
          f"entries {len(m['entries'])} unaudited {len(m['unaudited'])} skipped {len(m['skipped'])} "
          f"not in plan {len(m['not_in_plan'])} assets {len(m['assets'])} identities {len(m['identities'])} missing {len(m['missing'])} "
          f"uncovered links {len(m['uncovered_links'])}")
    return 0 if m["complete"] else 1
