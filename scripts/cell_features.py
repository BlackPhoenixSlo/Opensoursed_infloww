#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCOPE = ROOT / "service" / "cell_scope.json"
FEATURES = ROOT / "service" / "cell_features.json"
PAGE = ROOT / "docs" / "cell-mode" / "release-1-features.md"
SEND_KINDS = ROOT / "service" / "tests" / "test_send_ops_kill.golden.json"

APP_CALLS = ROOT / "app" / "lib" / "relayCallSites.ledger.json"
UNROUTED = "Agency calls without a front-door route"

STATES = ("off", "partial", "works")
MEMBERS = ("routes", "jobs", "send_kinds")
FEATURE_KEYS = {"state", "why", *MEMBERS}
DOC_KEYS = {"schema", "scope_sha256", "signed", "features"}

ANCHORLESS = {
    "autoreply": "keys on a timestamp, not the fan's message id",
    "welcome_chatter": "has no message id to key on",
    "followup": "generic follow-up has no origin",
    "vault_send": "vault items have no id",
    "nudge": "has no occurrence id",
    "purchase_followup": "the purchase batch changes after it is picked",
    "welcome_closing_ppv": "stamps its once-per-fan mark only after OF accepts",
}

ROOT_PATHS = ("/livez", "/health", "/")
CROSS = "Reads several Creators at once: works, but a down Cell's Creators show as missing."
CROSS_READS = "Reads across every Creator"
KEPT_CROSS_READS = {"GET /admin/accounts", "GET /admin/chats/recent", "GET /admin/screens/inbox"}

RULES: list[tuple[str, str | None, str, list[str], list[str], list[str]]] = [
    (UNROUTED, "off", "Some agency tools require a front-door route before they can work in cell mode.", [], [], []),
    ("Public tracking links (/t/...)", "off",
     "Fans who tap a tracking link get an error page. Links need an agency-wide id first.",
     ["/t"], ["tracking-click-classify"], []),
    ("Shared stats links (/share/...)", "off",
     "Stats links you shared stop opening. They need an agency-wide lookup first.",
     ["/share", "/admin/link-shares"], [], []),
    ("Bio pages (link-in-bio sites)", "off",
     "Bio sites stop loading and cannot be edited. Their web addresses need an agency-wide lookup first.",
     ["/admin/bio-pages"], [], []),
    (CROSS_READS, "off",
     "Screens that read every Creator at once do not load: dashboard, chatting and per-employee stats, "
     "live revenue, Excel export, Full AI rules list, proxy list, AI key status, "
     "a user's Creator list. The Creator list and All inbox stay.",
     ["GET /admin/rev/live", "GET /admin/accounts/roster-counts", "POST /admin/stats/xlsx"], [], []),
    ("Auto clock-out", "off",
     "Idle chatters are not clocked out on their own: their last activity sits on other Cells. "
     "Chatters clock out by hand.",
     [], [], []),
    ("S4S requests between Creators", "off",
     "Shout-for-shout swaps name two Creators who may sit on different Cells.",
     ["/admin/s4s/requests", "/admin/s4s/discover", "/admin/s4s/blocks", "/admin/s4s/slots", "/admin/s4s/schedule"],
     ["automation:s4s_check"], []),
    ("Auto-reply", None, "Fans get no automatic replies. Reason: after a crash it could send one twice.",
     ["/admin/autoreply-config"], ["automation:autoreply"], ["autoreply"]),
    ("Welcome-for-info message", None, "No welcome-for-info message. Reason: after a crash it could send it twice.",
     [], ["automation:welcome_chatter_for_info"], ["welcome_chatter", "welcome_closing_ppv"]),
    ("Follow-ups", None, "No automatic follow-ups. Reason: after a crash it could send one twice.",
     [], ["automation:send_followup"], ["followup"]),
    ("Send vault media to a fan (upload)", None,
     "Uploads that need a temporary feed post are refused until posts have send ids. "
     "Uploads linked to a fan use a send id for the message.",
     ["/api/of/v2/vault/upload"], ["vault-sweep"], ["vault_send"]),
    ("Online nudge", None, "No nudges when a fan comes online. Reason: after a crash it could send one twice.",
     ["/admin/nudge-config"], ["automation:nudge_online", "automation:nudge_online_fire"], ["nudge"]),
    ("Purchase follow-up", None, "No thank-you after a purchase. Reason: after a crash it could send it twice.",
     ["/admin/purchase-followup-config"], ["automation:purchase_followup"], ["purchase_followup"]),
    ("Remote login", None, "Logging a Creator in from the app is off until it is checked (Phase 1).",
     ["/admin/login/remote"], [], []),
    ("Translate", None, "Translating a message is off until it is checked (Phase 1).", ["/admin/translate"], [], []),
    ("Leak tracker", "off", "The Leak tracker is off in cell mode: its pages and routes answer as if it did not exist.",
     ["/admin/leaks"], ["leak-watch-sync", "leak-watch-tombstones"], []),
    ("Copy or import saved replies", "off",
     "Copying replies to other Creators and importing them from a file are off.",
     ["/admin/saved-replies/copy", "/admin/saved-replies/import", "GET /admin/saved-replies/import-template"], [], []),
    ("Small tools not checked yet", None,
     "Off until checked (Phase 1): image proxy, Full AI content prep, standard vault folders, "
     "vault cache reset.",
     ["GET /img", "/admin/full-ai/prepare-content", "/admin/vault-ai/standard-folders",
      "POST /admin/vault/cache/invalidate"], [], []),
    ("API docs pages", None, "The relay's /docs pages are off in cell mode.",
     ["/docs", "/redoc", "/openapi.json"], [], []),
    ("Creator list (roster)", None, CROSS, ["GET /admin/accounts"], [], []),
    ("All inbox", None, CROSS,
     ["GET /admin/screens/inbox", "GET /admin/chats/recent", "/admin/view-lease"], [], []),
    ("Split inbox", None, "One Creator's split inbox works. Group edits are off until the Front door fans writes out; "
     "other Cells' split-inbox caches also miss a newly saved default.",
     ["/admin/split-inbox"], [], []),
    ("Payroll and shift records", "partial",
     "Records and timesheets show, but finalising pay waits until every Creator's sales are fresh.",
     ["/admin/shifts/records", "/admin/shifts/timesheet", "/admin/ingest/transactions/attribute",
      "/admin/ingest/transactions/{tx_id}/attribute"], [], []),
    ("Feed posts and stories", "partial",
     "Feed post creation and story publication are refused in Cell mode until they have send ids.",
     ["/api/of/v2/posts", "/api/of/v2/stories", "/api/of/v2/queue/posts", "/api/of/v2/users/settings/story"],
     ["automation:auto_posts", "automation:auto_stories"], []),
    ("S4S profiles and promo posts", "partial",
     "Profiles work. Publishing promo posts is refused in Cell mode until feed posts have send ids.",
     ["/admin/s4s"], ["automation:s4s_post"], []),
    ("Sign-in and security", None, "Works as today.",
     ["/auth", "/chatter/login", "/chatter/logout", "/chatter/register", "/chatter/invite", "/.well-known"], [], []),
    ("Team and access", None,
     "Access edits can name several Creators: a down Cell's Creators are marked missing.",
     ["/admin/employees", "/admin/employee-groups", "/admin/chatters", "/admin/users", "/admin/impersonate",
      "/chatter/me", "/admin/audit", "GET /fleet/agency-copy"], ["agency-copy-poll", "grant-age-watch"], []),
    ("Shifts and clock-in", None, "Works as today.",
     ["/admin/shifts"], ["clock-in-missed"], []),
    ("Agency settings and alerts", None, "Works as today.",
     ["/admin/settings", "/admin/sensitive-words", "/admin/agency-notifications", "/push", "/admin/owner-tokens",
      "/admin/mcp", "/admin/my-llm-keys", "/admin/ai-key-status", "POST /fleet/notices"],
     ["push-send", "bell-notices-to-control"], []),
    ("Proxies", None, "The proxy list is off (see Reads across every Creator); edits work, a down Cell's Creators show as missing.",
     ["/admin/proxies", "/admin/proxy-pool"], ["proxy-health-probe", "proxy-rebalance"], []),
    ("Connect a Creator (sessions)", None,
     "Fansly session import is refused in Cell mode because the platform is not admitted.",
     ["/admin/session", "/admin/reload-session", "/admin/accounts", "/api/of/v2/sessions", "/api/of/live-window",
      "POST /fleet/reservations", "POST /api/cell/reservations/handoff"],
     ["pump-supervisor", "reservation-activation-retry"], []),
    ("Chat with a fan", None, "Works per Creator, as today.",
     ["/api/of/v2/chats", "/api/of/v2/messages/{message_id}", "/admin/messages/{account_id}", "/admin/screens/chat",
      "/admin/fans", "/api/of/v2/giphy", "/api/of/v2/labels", "/api/of/v2/automation-restrict",
      "/admin/unconfirmed-sends", "/admin/copilot", "/api/of/v2/upload"],
     [], ["composer", "composer_shim", "restrict_ack", "native_schedule"]),
    ("Mass messages", None, "Works per Creator, as today.",
     ["/api/of/v2/messages", "/admin/mass-messages", "/admin/mass-exclude", "/admin/do-not-mass",
      "/admin/messages/detect-mass", "/admin/paid-messages"],
     ["automation:send_mass_message", "automation:mass_premade", "automation:unsend_messages"],
     ["manual_mass_send", "manual_mass_schedule", "mass_job", "mass_premade"]),
    ("Scheduled sends", None, "Works per Creator, as today.",
     ["/api/of/v2/scheduled-sends", "/api/of/v2/schedules"], ["automation:scheduled_send"],
     ["scheduled_send", "publish_now"]),
    ("Priority mass", None, "Works per Creator, as today.", ["/admin/priority-mass"],
     ["automation:priority_mass"], ["priority_mass"]),
    ("Funnels", None, "Works per Creator, as today.", ["/admin/funnels"], ["automation:reply_mass_funnel"], ["funnel"]),
    ("Lifecycle messages", None, "Works per Creator, as today.", ["/admin/lifecycle-message-config"],
     ["automation:expiry_message", "automation:expired_message", "automation:resubscribe_message",
      "automation:birthday_message"], ["lifecycle", "lifecycle_initial"]),
    ("Welcome message", None, "Works per Creator, as today.", [], ["automation:send_welcome"], ["send_welcome"]),
    ("Full AI", None, "Works per Creator. Only the rules list across all Creators is off.", ["/admin/full-ai"],
     ["automation:full_ai_chat", "full-ai-catchup-boot"], ["full_ai_live", "full_ai_ppv"]),
    ("Automation rules", None, "Works per Creator, as today.",
     ["/admin/automation-rules", "/admin/automation", "/admin/system/automations", "/admin/system/runs",
      "POST /admin/cell-holds/release", "/admin/cell/restore-gap"],
     ["automation-exec", "automation:apply_profiles", "automation:gen_info", "automation:process_old_fans",
      "automation:scrape_chats", "automation:scrape_fan"], []),
    ("Smart lists and OF lists", None, "Works per Creator, as today.", ["/admin/smart-lists", "/api/of/v2/lists"],
     ["automation:smart_list_sync"], []),
    ("Saved replies", None, "Works per Creator, as today.", ["/admin/saved-replies"], [], []),
    ("Vault library", None, "Works per Creator, as today.", ["/admin/vault-ai", "/admin/vault", "/api/of/v2/vault"],
     ["vault-collect"], []),
    ("Customs", None, "Works per Creator, as today.", ["/admin/customs"], ["automation:customs_watch"], []),
    ("Auto-follow", None, "Works per Creator, as today.", ["/admin/auto-follow"], ["automation:auto_follow"], []),
    ("Promotions and trials", None, "Works per Creator, as today.",
     ["/admin/promotions", "/api/of/v2/promotions", "/admin/trial-links", "/api/of/v2/trials"],
     ["automation:promo_reactivate"], []),
    ("Tracking link stats", None, "Stats per Creator work; only the public link itself is off (see above).",
     ["/admin/tracking-links", "/admin/of-tracking-links", "/admin/link-meta", "/admin/link-metrics",
      "/admin/promo-list", "/api/of/v2/campaigns"], ["link-figures-prewarm"], []),
    ("Stats and reports per Creator", None, "Works per Creator, as today.",
     ["/admin/stats", "/admin/reports", "/admin/tips-list", "/admin/top-tippers", "/api/of/v2/payouts",
      "/api/of/v2/earnings", "/api/of/v2/payments", "/api/of/v2/streaks", "/api/of/v2/fans-activity",
      "/api/of/v2/init", "/api/of/v2/users/me/stats", "/api/of/v2/users/me/profile/stats"],
     ["of-stats-daily"], []),
    ("Sales ingest", None, "Works per Creator, as today.", ["/admin/ingest", "/admin/roster"],
     ["tx-ingest-supervisor", "tx-ingest-fast-poll"], []),
    ("Creator settings", None, "Works per Creator, as today.",
     ["/admin/account-config", "/admin/style-config", "/admin/of-consent", "/admin/ofm-writes", "/api/of/ofm-writes"],
     [], []),
    ("AI assistant", None, "Works per Creator, as today.", ["/admin/assistant", "/admin/ultra"], [], []),
    ("Support chat", None, "The Support tab talks to the central hub; the hub runs on its own Relay.",
     ["/admin/support", "/support"], [], []),
    ("OF profile, fans and streams", None, "Works per Creator, as today.",
     ["/api/of/v2/users", "/api/of/v2/subscriptions", "/api/of/v2/subscribers", "/api/of/v2/guests",
      "/api/of/v2/countries", "/api/of/v2/release-forms", "/api/of/v2/streams"], [], []),
    ("Live updates", None, "Each Cell streams its own updates; the app listens to every Cell it needs.",
     ["/events"], ["badge-reads", "chat-sweep-cadence", "shared-refresher", "persist-worker"], []),
    ("Relay health and housekeeping", None,
     "Per-Relay tools. Perf log upload names several Creators: a down Cell's Creators are marked missing.",
     ["/lanes-panel", "/admin/perflog", "/admin/errors", "/admin/coalesce",
      "/admin/events", "/admin/_debug", "/admin/priority-lanes", "/admin/storyboard", "/admin/img-cache",
      "/admin/streams", "/admin/system", "/admin/secrets", "/admin/automation-kinds", "/img", "GET /api/cell/hold",
      *ROOT_PATHS],
     ["runtime-switches-load", "storyboard-evictor", "img-cache-evictor", "perflog-evictor", "raw-json-evictor",
      "payload-size-cap", "audit-retention-evictor", "sqlite-optimize"], []),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def table_sha256(doc: dict) -> str:
    feats = {n: doc["features"][n] for n in sorted(doc["features"])}
    return hashlib.sha256(json.dumps(feats, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def route_matches(spec: str, key: str) -> bool:
    if " " in spec:
        return key == spec
    path = key.partition(" ")[2]
    return path == spec or (spec != "/" and path.startswith(spec + "/"))


def member_state(kind: str, name: str, scope: dict) -> str:
    if kind == "routes":
        return {"closed": "off", "fanin": "partial"}.get(scope["routes"][name]["scope"], "works")
    if kind == "send_kinds":
        return "off" if name in ANCHORLESS else "works"
    return "works"


def universe(scope: dict, kinds: list[str]) -> dict[str, list[str]]:
    return {"routes": sorted(scope["routes"]), "jobs": sorted(scope["jobs"]), "send_kinds": sorted(kinds)}


def worst(feature: dict, scope: dict) -> tuple[str, str | None]:
    low, who = "works", None
    for kind in MEMBERS:
        for name in feature.get(kind, []):
            if kind == "routes" and name not in scope["routes"] or kind == "jobs" and name not in scope["jobs"]:
                continue
            s = member_state(kind, name, scope)
            if STATES.index(s) < STATES.index(low):
                low, who = s, f"{kind[:-1]} {name}"
    return low, who


def _rule_for(kind: str, name: str, scope: dict) -> str | None:
    if (kind == "routes" and name.startswith("GET ") and name not in KEPT_CROSS_READS
            and scope["routes"][name]["scope"] == "fanin"):
        return CROSS_READS
    for fname, _, _, routes, jobs, sends in RULES:
        if kind == "routes" and any(route_matches(s, name) for s in routes):
            return fname
        if kind == "jobs" and name in jobs or kind == "send_kinds" and name in sends:
            return fname
    return None


def draft(scope: dict, kinds: list[str], old: dict | None) -> tuple[dict, list[str]]:
    old_f = (old or {}).get("features", {})
    rules = {r[0]: r for r in RULES}
    features: dict[str, dict] = {}
    for name in [*rules, *[n for n in old_f if n not in rules]]:
        state, why = (rules[name][1], rules[name][2]) if name in rules else (old_f[name]["state"], old_f[name]["why"])
        features[name] = {"state": state, "why": why, "routes": [], "jobs": [], "send_kinds": []}
    features[UNROUTED]["calls"] = sorted(k for k, e in json.loads(APP_CALLS.read_text()).items() if e.get("state") == "off")
    placed = {(k, m): n for n, f in old_f.items() for k in MEMBERS for m in f.get(k, [])}
    unplaced = []
    for kind, names in universe(scope, kinds).items():
        for m in names:
            home = placed.get((kind, m)) or _rule_for(kind, m, scope)
            if home is None:
                unplaced.append(f"{kind[:-1]} {m}")
                continue
            features[home][kind].append(m)
    for f in features.values():
        low, _ = worst(f, scope)
        if f["state"] is None or STATES.index(f["state"]) > STATES.index(low):
            f["state"] = low
    doc = {"schema": 1, "scope_sha256": sha256(SCOPE), "signed": None, "features": features}
    signed = (old or {}).get("signed")
    if isinstance(signed, dict) and signed.get("sha256") == table_sha256(doc):
        doc["signed"] = signed
    return doc, unplaced


def check(doc: dict, scope: dict, scope_sha: str, kinds: list[str], page: str | None) -> list[str]:
    out = []
    if set(doc) != DOC_KEYS or doc.get("schema") != 1:
        out.append(f"invalid: top-level keys {sorted(doc)} (want {sorted(DOC_KEYS)}, schema 1)")
    if doc.get("scope_sha256") != scope_sha:
        out.append("stale: scope_sha256 does not match service/cell_scope.json (rerun --features)")
    signed = doc.get("signed")
    if signed is not None and (not isinstance(signed, dict) or set(signed) != {"by", "at", "sha256"}):
        out.append("invalid: signed must be null or {by, at, sha256}")
    elif signed is not None and signed["sha256"] != table_sha256(doc):
        out.append("stale: signed sha256 does not match the table (the owner signed a different table)")
    for fname, _, _, specs, _, _ in RULES:
        out += [f"unused: rule {fname!r} route {s!r} matches no route" for s in specs
                if not any(route_matches(s, k) for k in scope["routes"])]
    feats = doc.get("features", {})
    homes: dict[tuple[str, str], list[str]] = {}
    for name, f in feats.items():
        if set(f) != (FEATURE_KEYS | {"calls"} if name == UNROUTED else FEATURE_KEYS):
            out.append(f"invalid: feature {name!r} keys {sorted(f)}")
            continue
        if f["state"] not in STATES:
            out.append(f"invalid: feature {name!r} state {f['state']!r}")
        if not str(f["why"]).strip():
            out.append(f"invalid: feature {name!r} has no why")
        for kind in MEMBERS:
            for m in f[kind]:
                homes.setdefault((kind, m), []).append(name)
        low, who = worst(f, scope)
        if f["state"] in STATES and STATES.index(f["state"]) > STATES.index(low):
            out.append(f"better than worst member: {name!r} says {f['state']}, {who} is {low}")
    want = universe(scope, kinds)
    for kind, names in want.items():
        for m in names:
            got = homes.get((kind, m), [])
            if not got:
                out.append(f"missing: {kind[:-1]} {m} is in no feature")
            elif len(got) > 1:
                out.append(f"duplicate: {kind[:-1]} {m} is in {', '.join(map(repr, got))}")
    out += [f"stale: {k[:-1]} {m} in {h[0]!r} is gone" for (k, m), h in sorted(homes.items()) if m not in want[k]]
    if page is not None and page != render(doc):
        out.append(f"stale: {PAGE.relative_to(ROOT)} differs from the table (rerun --features)")
    return out


def render(doc: dict) -> str:
    feats = doc["features"]
    by = {s: [(n, f) for n, f in feats.items() if f["state"] == s] for s in STATES}
    signed = doc.get("signed")
    status = (f"Signed by {signed['by']} on {signed['at']}." if signed else "Draft. Not signed yet.")
    lines = [
        "# Release 1: what works, what is off",
        "",
        status,
        "",
        "Release 1 splits the agency's Creators across several Relays (Cells).",
        "Most of the app works as today.",
        f"{len(by['off'])} parts are switched off and {len(by['partial'])} work with a gap.",
        "",
        f"## Switched off ({len(by['off'])})",
        "",
    ]
    for state, head in (("off", None), ("partial", f"## Works with a gap ({len(by['partial'])})")):
        if head:
            lines += [head, ""]
        for n, f in by[state]:
            lines += [f"**{n}**", f["why"], ""]
            if n == UNROUTED:
                lines += [f"{len(f.get('calls', []))} app call sites are marked off.", ""]
    lines += [f"## Works as today ({len(by['works'])})", ""]
    lines += [f"- {n}" for n, _ in by["works"]]
    lines += [
        "",
        "## To sign",
        "",
        'Say "yes, Release 1 features signed" in the build chat.',
        "We record your name, the date and the table's fingerprint",
        f"(short form: `{table_sha256(doc)[:16]}`).",
        "Any change to the table needs a new yes.",
        "",
        "## What is in each part",
        "",
        "Generated from `service/cell_features.json` by",
        "`scripts/cell_scope_scan.py --features`. Do not edit by hand.",
        "",
    ]
    for s in STATES:
        for n, f in by[s]:
            count = ", ".join(f"{len(f[k])} {k.replace('_', ' ')[:-1 if len(f[k]) == 1 else None]}"
                              for k in MEMBERS if f[k]) or "no members"
            lines += [f"<details><summary>{n} ({s}; {count})</summary>", ""]
            lines += [f"- `{m}`" for k in MEMBERS for m in f[k]]
            lines += ["", "</details>", ""]
    return "\n".join(lines).rstrip() + "\n"


def dump(doc: dict) -> str:
    def one(v):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))

    feats = ",\n".join(f" {one(n)}:{one(f)}" for n, f in doc["features"].items())
    return (f'{{"schema":{doc["schema"]},"scope_sha256":{one(doc["scope_sha256"])},"signed":{one(doc["signed"])},\n'
            f'"features":{{\n{feats}\n}}}}\n')


def load() -> tuple[dict, list[str]]:
    return json.loads(SCOPE.read_text()), sorted(json.loads(SEND_KINDS.read_text()))


def main(check_only: bool, fresh: bool = False) -> int:
    scope, kinds = load()
    old = json.loads(FEATURES.read_text()) if FEATURES.exists() else None
    if fresh and old:
        old = {"signed": old.get("signed")}
    if check_only:
        problems = check(old or {}, scope, sha256(SCOPE), kinds, PAGE.read_text() if PAGE.exists() else "")
        for p in problems:
            print(p)
        print(f"cell features: {len((old or {}).get('features', {}))} features; {len(problems)} problem(s)")
        return 1 if problems else 0
    doc, unplaced = draft(scope, kinds, old)
    for u in unplaced:
        print(f"no rule: {u} (add it to RULES in scripts/cell_features.py)")
    FEATURES.write_text(dump(doc))
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(render(doc))
    counts = {s: sum(f["state"] == s for f in doc["features"].values()) for s in STATES}
    print(f"wrote {FEATURES.relative_to(ROOT)} + {PAGE.relative_to(ROOT)}: {counts}; {len(unplaced)} unplaced")
    return 1 if unplaced else 0
