#!/usr/bin/env bash
# ui-shots.sh — render Messages Pro to PNGs from a throwaway localhost stack.
#
#   scripts/ui-shots.sh                         real run; exit 0 only if every gated shot passes
#   UI_SHOTS_SELFTEST=1 scripts/ui-shots.sh     self-test; injects faults, MUST exit non-zero
#   UI_SHOTS_SWEEP=1 scripts/ui-shots.sh        overflow sweep only: 4 sizes x (app, Pop-out window),
#                                               writes messages-pro-sweep.json (Phase 6 ticket 109)
#
# Starts a temp-DB relay and `next dev` on free 127.0.0.1 ports, registers a
# throwaway owner, serves fixture Fans from the browser router, screenshots each
# shot into docs/screenshots/ and writes docs/screenshots/messages-pro-report.json.
# Nothing leaves the machine: the browser aborts off-host requests and WebSockets,
# the relay refuses non-loopback lookups and sockets, and Next's fetch and
# http(s).request refuse non-loopback hosts. Never installs anything. See docs/ui-shots.md.
#
# Exit codes: 0 pass · 1 a gate failed (see the report) · 2 usage
#             3 prerequisite missing or unsafe (venv, Chromium, legacy secret store)
#             4 the stack did not start
set -euo pipefail

if [ "$#" -ne 0 ]; then
  echo "ui-shots: takes no arguments (UI_SHOTS_SELFTEST=1 and UI_SHOTS_SWEEP=1 are its switches; see docs/ui-shots.md)" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/venv/bin/python"
OUT="$ROOT/docs/screenshots"
# Every output the harness owns; all are deleted at start so nothing stale can pass.
OUTPUTS=(messages-pro-desktop messages-pro-popout messages-pro-insights messages-pro-phone-list
         messages-pro-phone-thread messages-pro-composer-ppv)
REPORT_NAME=messages-pro-report.json
# The sweep (UI_SHOTS_SWEEP=1) owns only its own outputs and leaves the default run's alone.
if [ "${UI_SHOTS_SWEEP:-}" = 1 ]; then
  OUTPUTS=(messages-pro-1280 messages-pro-768)
  REPORT_NAME=messages-pro-sweep.json
fi

# Before anything under docs/screenshots/ is written or deleted: a git worktree has no venv.
if ! test -x "$PY"; then
  echo "ui-shots: $PY not found. The harness needs the main checkout's relay venv (uvicorn, FastAPI, Playwright); in a git worktree, link it first: see Worktrees in docs/ui-shots.md." >&2
  exit 3
fi

STARTED_AT="$(date +%s)"
mkdir -p "$OUT"
for name in "${OUTPUTS[@]}"; do rm -f "$OUT/$name.png"; done
rm -f "$OUT/$REPORT_NAME"

# Importing service/secrets_store.py runs _adopt_legacy_file() (secrets_store.py:177-197,440):
# when service/secrets.json exists and service/secrets/secrets.json does not, it reads the
# first and writes the second, before any redirect can run. Refuse to start in that state.
if [ -f "$ROOT/service/secrets.json" ] && [ ! -e "$ROOT/service/secrets/secrets.json" ]; then
  echo "ui-shots: service/secrets.json exists and service/secrets/secrets.json does not." >&2
  echo "ui-shots: starting the relay would copy your stored keys before the harness can redirect" >&2
  echo "ui-shots: the store, so it refuses. Move the file into service/secrets/ (or start your own" >&2
  echo "ui-shots: relay once, which does that), then re-run. See docs/ui-shots.md." >&2
  exit 3
fi

TMP=""
PIDS=()
cleanup() {
  local code=$?
  trap - EXIT INT TERM
  local pid
  for pid in "${PIDS[@]+"${PIDS[@]}"}"; do kill -TERM -- "-$pid" 2>/dev/null || true; done
  for _ in $(seq 1 50); do
    local alive=0
    for pid in "${PIDS[@]+"${PIDS[@]}"}"; do kill -0 -- "-$pid" 2>/dev/null && alive=1; done
    [ "$alive" = 0 ] && break
    sleep 0.2
  done
  for pid in "${PIDS[@]+"${PIDS[@]}"}"; do kill -KILL -- "-$pid" 2>/dev/null || true; done
  local f
  for f in tsconfig.json next-env.d.ts; do
    if [ -n "$TMP" ] && [ -f "$TMP/$f.orig" ] && ! cmp -s "$TMP/$f.orig" "$ROOT/app/$f"; then
      cp "$TMP/$f.orig" "$ROOT/app/$f"
      echo "ui-shots: restored app/$f (next dev had rewritten it)" >&2
    fi
  done
  [ -n "$TMP" ] && rm -rf "$TMP"
  exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

TMP="$(mktemp -d "${TMPDIR:-/tmp}/ui-shots.XXXXXX")"
# `next dev` rewrites these two when it sees a new distDir; the trap puts them back.
cp "$ROOT/app/tsconfig.json" "$TMP/tsconfig.json.orig"
cp "$ROOT/app/next-env.d.ts" "$TMP/next-env.d.ts.orig"

# ── Embedded programs ───────────────────────────────────────────────────────

# Relay launcher. Order matters: network guards and the dotenv no-ops first, then the
# secret store redirected, then the house safe runner's patches, then serve on loopback
# under the stdlib asyncio loop (uvloop connects through libuv, past socket.connect).
cat >"$TMP/relay.py" <<'PY'
import ipaddress, json, os, socket, sys
from pathlib import Path

TMP = Path(os.environ["UI_SHOTS_TMP"])
LOG = TMP / "server-offhost.jsonl"


def _record(path, rec):
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")


def _loopback(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if host is None or host == "localhost":  # None: a local bind lookup, getaddrinfo(None, port)
        return True
    try:
        return ipaddress.ip_address(str(host).split("%")[0]).is_loopback
    except ValueError:
        return False


def _refused(where, target):
    _record(LOG, {"process": "relay", "via": where, "target": str(target), "refused": True})
    return f"ui-shots: off-host {where} refused: {target!r}"


_real = {"connect": socket.socket.connect, "connect_ex": socket.socket.connect_ex,
         "create_connection": socket.create_connection, "getaddrinfo": socket.getaddrinfo,
         "gethostbyname": socket.gethostbyname, "gethostbyname_ex": socket.gethostbyname_ex}


def connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _loopback(address[0]):
        raise ConnectionRefusedError(_refused("socket.connect", address))
    return _real["connect"](self, address)


def connect_ex(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _loopback(address[0]):
        raise ConnectionRefusedError(_refused("socket.connect_ex", address))
    return _real["connect_ex"](self, address)


def create_connection(address, *a, **k):
    if not _loopback(address[0]):
        raise ConnectionRefusedError(_refused("socket.create_connection", address))
    return _real["create_connection"](address, *a, **k)


# Name lookups are refused before resolution, so no DNS query leaves the machine either.
def getaddrinfo(host, *a, **k):
    if not _loopback(host):
        raise socket.gaierror(socket.EAI_NONAME, _refused("socket.getaddrinfo", host))
    return _real["getaddrinfo"](host, *a, **k)


def gethostbyname(host):
    if not _loopback(host):
        raise socket.gaierror(socket.EAI_NONAME, _refused("socket.gethostbyname", host))
    return _real["gethostbyname"](host)


def gethostbyname_ex(host):
    if not _loopback(host):
        raise socket.gaierror(socket.EAI_NONAME, _refused("socket.gethostbyname_ex", host))
    return _real["gethostbyname_ex"](host)


socket.socket.connect, socket.socket.connect_ex, socket.create_connection = connect, connect_ex, create_connection
socket.getaddrinfo, socket.gethostbyname, socket.gethostbyname_ex = getaddrinfo, gethostbyname, gethostbyname_ex

# service/.env holds real keys; db/engine.py, llm_providers.py and auth.py
# read it through `from dotenv import ...`. No-op both before any import.
import dotenv  # noqa: E402
import dotenv.main  # noqa: E402


def _no_load_dotenv(*a, **k):
    return False


def _no_dotenv_values(*a, **k):
    return {}


for _m in (dotenv, dotenv.main):
    _m.load_dotenv, _m.dotenv_values = _no_load_dotenv, _no_dotenv_values

SERVICE = Path(os.environ["UI_SHOTS_ROOT"]) / "service"
sys.path.insert(0, str(SERVICE))

# The stored secret outranks the env (server._effective_share_token), so point
# the store into the temp dir before anything can read it (_harness.py:75-80).
import secrets_store  # noqa: E402
secrets_store._DIR = TMP / "secrets"
secrets_store._PATH = secrets_store._DIR / "secrets.json"
secrets_store._CACHE = None

import _run_ui_safe  # noqa: E402,F401  (sets CHATTERLY_TEST_MODE, neuters loops)
import uvicorn  # noqa: E402

uvicorn.run(_run_ui_safe.server.app, host="127.0.0.1", port=int(os.environ["UI_SHOTS_RELAY_PORT"]),
            loop="asyncio", log_level="warning")
PY

# Next preload: global fetch and http(s).request/get refuse non-loopback hosts (npm
# version check, next/font's Google Fonts download, etc.) and log each refusal.
cat >"$TMP/fetch-guard.cjs" <<'JS'
const fs = require("fs");
const path = require("path");
const http = require("http");
const https = require("https");
const LOG = path.join(process.env.UI_SHOTS_TMP, "server-offhost.jsonl");
const LOOPBACK = new Set(["127.0.0.1", "localhost", "[::1]", "::1"]);
const log = (via, target) => {
  try { fs.appendFileSync(LOG, JSON.stringify({ process: "next", via, target, refused: true }) + "\n"); } catch {}
};
const realFetch = globalThis.fetch;
if (realFetch) {
  globalThis.fetch = function guardedFetch(input, init) {
    let url;
    try { url = new URL(typeof input === "string" || input instanceof URL ? String(input) : input.url); } catch { url = null; }
    if (url && !LOOPBACK.has(url.hostname)) {
      log("fetch", url.origin + url.pathname);
      return Promise.reject(new TypeError("ui-shots: off-host fetch refused: " + url.origin));
    }
    return realFetch.call(this, input, init);
  };
}
// request(url[, options][, cb]) or request(options[, cb]); options override the url, and no host means localhost.
function target(args, proto) {
  let host = "localhost", where = proto + "//localhost";
  const a = args[0];
  if (typeof a === "string" || a instanceof URL) {
    try { const u = new URL(String(a)); host = u.hostname; where = u.origin + u.pathname; } catch {}
  }
  const o = a && typeof a === "object" && !(a instanceof URL) ? a : args[1] && typeof args[1] === "object" ? args[1] : null;
  if (o && (o.hostname || o.host)) {
    host = String(o.hostname || o.host);
    if (host.split(":").length === 2) host = host.split(":")[0];
    where = proto + "//" + host + (o.path || "");
  }
  return { host, where };
}
for (const [mod, proto] of [[http, "http:"], [https, "https:"]]) {
  for (const name of ["request", "get"]) {
    const real = mod[name];
    mod[name] = function guardedRequest(...args) {
      const t = target(args, proto);
      if (!LOOPBACK.has(t.host)) {
        log(proto.slice(0, -1) + "." + name, t.where);
        throw new Error("ui-shots: off-host " + proto.slice(0, -1) + "." + name + " refused: " + t.host);
      }
      return real.apply(this, args);
    };
  }
}
JS

# Browser driver: login, fixtures, shots, report.
cat >"$TMP/driver.py" <<'PY'
import json, os, re, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

INSTALL = "venv/bin/python -m playwright install chromium"


def preflight():
    with sync_playwright() as p:
        try:
            p.chromium.launch().close()
        except Exception as e:  # noqa: BLE001
            print(f"ui-shots: Chromium is not available to Playwright ({str(e).splitlines()[0]}).")
            print(f"ui-shots: the harness installs nothing. Install it yourself:\n\n    {INSTALL}\n")
            sys.exit(3)


if sys.argv[1:] == ["preflight"]:
    preflight()
    sys.exit(0)

ROOT = Path(os.environ["UI_SHOTS_ROOT"])
TMP = Path(os.environ["UI_SHOTS_TMP"])
APP = os.environ["UI_SHOTS_APP"]
RELAY = os.environ["UI_SHOTS_RELAY"]
STARTED_AT = int(os.environ["UI_SHOTS_STARTED_AT"])
SELFTEST = os.environ.get("UI_SHOTS_SELFTEST") == "1"
SWEEP = os.environ.get("UI_SHOTS_SWEEP") == "1"
OUT = "docs/screenshots"
REPORT = ROOT / OUT / "messages-pro-report.json"

# ── Fixtures (shapes follow app/lib/relay.ts and the hooks that read them) ────
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def ago(minutes):
    return (NOW - timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


ACCOUNT_ID = "424242"
CREATOR = {"id": 424242, "name": "Ella", "username": "aria", "avatar": None}
ACCOUNT = {"id": ACCOUNT_ID, "nickname": "Ella", "name": "Ella", "platform": "onlyfans", "color": "#e8618c",
           "has_session": True, "session_dead_at": None, "created_at": ago(60 * 24 * 30),
           "last_used_at": ago(5)}
EMPLOYEE = {"id": 7, "display_name": "Sam", "color": "#4f7cff", "is_active": True, "chatter_id": None,
            "created_at": ago(60 * 24 * 30)}
FANS = [
    {"id": 1001, "name": "Bella Hart", "username": "bellahart"},
    {"id": 1002, "name": "Chloe Rivers", "username": "chloerivers"},
    {"id": 1003, "name": "Dana Brooks", "username": "danabrooks"},
    {"id": 1004, "name": "Eva Stone", "username": "evastone"},
    {"id": 1005, "name": "Faye Monroe", "username": "fayemonroe"},
]
UNREAD_FAN = 1002
FAN_NAMES = [f["name"] for f in FANS]
DAY = 60 * 24  # minutes
# Phase 2's row facts, so the badges and the spend display have something to show (Phase 2
# ticket 55). Bella is online and the big spender, Chloe bought a PPV two days ago, Dana's
# subscription expired three days ago after she spent (and renewal was off), Eva's renewal
# is off with a known $0, and Faye's last message is four days old with no spend entry.
BIG_SPENDER_FAN, PPV_FAN, EXPIRED_FAN, RENEWAL_OFF_FAN, QUIET_FAN = 1001, 1002, 1003, 1004, 1005
SPEND = {  # spend-batch entries (service/fans.py fans_spend_batch); the quiet Fan has none
    BIG_SPENDER_FAN: {"spend_cents": 1_248_000, "subscription_status": "active", "expired_at": ago(-20 * DAY)},
    PPV_FAN: {"spend_cents": 4_500, "subscription_status": "active", "expired_at": ago(-12 * DAY)},
    EXPIRED_FAN: {"spend_cents": 23_000, "subscription_status": "Set to Expire", "expired_at": ago(3 * DAY)},
    RENEWAL_OFF_FAN: {"spend_cents": 0, "subscription_status": "Set to Expire", "expired_at": ago(-9 * DAY)},
}


def user(fan):
    return {**fan, "avatar": None, "customNickname": None, "displayName": None, "notice": None}


def msg(i, fan, from_fan, text, minutes, **extra):
    base = {"id": 50000 + i, "text": text, "fromUser": user(fan) if from_fan else dict(CREATOR),
            "toUser": dict(CREATOR) if from_fan else user(fan), "createdAt": ago(minutes),
            "isFree": True, "isOpened": True, "isTip": False, "price": 0, "media": [], "mediaCount": 0,
            "isLiked": False, "isPinned": False}
    base.update(extra)
    return base


THREAD = [  # oldest first; served newest first (order=desc)
    msg(1, FANS[0], True, "Hey Ella! Loved your last post", 70),
    msg(2, FANS[0], False, "Aww thank you babe, that one was fun to shoot", 66),
    msg(3, FANS[0], True, "What are you up to tonight?", 60),
    msg(4, FANS[0], False, "Just wrapped a new set. Want a peek?", 55),
    msg(5, FANS[0], True, "Yes please!", 50),
    msg(6, FANS[0], False, "Something special just for you", 45, isFree=False, isOpened=False, price=15,
        lockedText=False),
    msg(7, FANS[0], True, "Unlocking it now", 40),
]


def chat_row(i, fan):
    last = THREAD[-1] if fan is FANS[0] else msg(100 + i, fan, True, f"Hi Ella, it's {fan['name'].split()[0]}",
                                                   4 * DAY if fan["id"] == QUIET_FAN else 90 + 30 * i)
    unread = fan["id"] == UNREAD_FAN
    return {"withUser": user(fan), "lastMessage": {k: last[k] for k in (
        "id", "text", "fromUser", "createdAt", "mediaCount", "isFree", "isTip", "isOpened")},
            "hasUnread": unread, "unreadMessagesCount": 1 if unread else 0, "isOnline": i == 0,
            "canSendMessage": True, "canNotSendReason": None, "isMutedNotifications": False}


CHATS = [chat_row(i, f) for i, f in enumerate(FANS)]
# The Creator's transactions feed (OF's /payouts/transactions, read by useFanActivity): one PPV
# unlock by Chloe two days ago, under the "Payment for message from " prefix that
# service/transaction_ingest.py classifies as a PPV.
PPV_BUYER = next(f for f in FANS if f["id"] == PPV_FAN)
TRANSACTIONS = [{"id": "uishots-tx-1", "amount": 25, "net": 20, "fee": 5, "currency": "USD",
                 "createdAt": ago(2 * DAY), "description": f"Payment for message from {PPV_BUYER['name']}",
                 "status": "done", "user": user(PPV_BUYER)}]


def fan_record(fan):  # FanRecord in app/lib/relay.ts
    nulls = ("custom_nickname generated_nickname real_name his_age home_country home_city hobbies fetishes "
             "self_description description notes subscription_status subscribed_at language language_source")
    return {**{k: None for k in nulls.split()}, "account_id": ACCOUNT_ID, "fan_id": fan["id"],
            "of_username": fan["username"], "of_display_name": fan["name"], "avatar_url": None, "tags": [],
            "lifetime_spend_cents": 0, "bought_amount": 0, "last_message_received_at": ago(40),
            "source": "ui-shots", "is_followed": False, "created_at": ago(60 * 24 * 30), "updated_at": ago(40)}
FAN_BY_ID = {str(f["id"]): f for f in FANS}


def fixture(method, path, q):
    """Answer one relay-bound request, or None when no fixture matches."""
    one = lambda k: (q.get(k) or [None])[0]  # noqa: E731
    if method != "GET":
        return None
    if path == "/admin/accounts":
        return {"accounts": [ACCOUNT], "active_account_id": ACCOUNT_ID}
    # The Creator tab's unread total (app/hooks/useRosterCounts.ts), by the relay's rule
    # (service/server.py admin_accounts_roster_counts): unread chats, and read chats the Fan
    # spoke last in. Answered for the plain poll and a ?bust= refresh alike.
    if path == "/admin/accounts/roster-counts":
        return {"counts": {ACCOUNT_ID: {
            "unread": sum(1 for c in CHATS if c["hasUnread"]),
            "owe_reply": sum(1 for c in CHATS if not c["hasUnread"]
                             and c["lastMessage"]["fromUser"]["id"] == c["withUser"]["id"])}}}
    if path == "/admin/employees":
        return {"employees": [EMPLOYEE]}
    # The Creator's Split Inbox (service/split_inbox_api.py, ticket 102): the unset default, as the
    # relay answers a Creator never split, so the selector reads "All inboxes".
    if path == "/admin/split-inbox" and one("account_id") == ACCOUNT_ID:
        return {"account_id": ACCOUNT_ID, "config": {"group_count": 1, "assignments": {}}}
    if path == "/api/of/v2/chats":
        if (one("offset") or "0") != "0" or one("query") or one("list_id"):
            return {"list": [], "hasMore": False}
        f = one("filter")  # no fixture Fan is pinned or priority
        rows = CHATS if not f else [c for c in CHATS if c["hasUnread"]] if f == "unread" else []
        return {"list": rows, "hasMore": False}
    # The app's owner-id read (app/components/chat/ChatSurface.tsx, `of-me`): the Creator, so her
    # messages sit on the right as ours (Phase 3 ticket 97's two-sided bubbles).
    if path == "/api/of/v2/users/me":
        return dict(CREATOR)
    # Single chat / user reads.
    m = re.fullmatch(r"/api/of/v2/(chats|users)/(\d+)", path)
    if m and m.group(2) in FAN_BY_ID:
        fan = FAN_BY_ID[m.group(2)]
        return CHATS[FANS.index(fan)] if m.group(1) == "chats" else user(fan)
    # Local reads. chats/recent: the app's first-paint seed (app/components/chat/ChatList.tsx:279-283).
    # Shape per service/server.py (chats/recent).
    if path == "/admin/chats/recent":
        return {"list": [{"__accountId": ACCOUNT_ID, "withUser": {k: c["withUser"][k] for k in (
            "id", "name", "username", "avatar")}, "lastMessage": {k: c["lastMessage"][k] for k in (
            "id", "text", "createdAt")}, "hasUnread": c["hasUnread"], "unreadMessagesCount": c[
            "unreadMessagesCount"]} for c in CHATS], "source": "local-db"}
    m = re.fullmatch(r"/api/of/v2/chats/(\d+)/messages", path)
    if m:
        if m.group(1) == str(FANS[0]["id"]) and not one("before_id"):
            return {"list": list(reversed(THREAD)), "hasMore": False}
        return {"list": [], "hasMore": False}
    if path == f"/admin/fans/{ACCOUNT_ID}/spend-batch":
        ids = ",".join(q.get("ids", [])).split(",")
        return {"spend": {i: {**SPEND[int(i)], "last_purchase_at": None} for i in ids
                          if i.isdigit() and int(i) in SPEND}}
    if path == "/api/of/v2/payouts/transactions":
        return {"list": TRANSACTIONS if (one("offset") or "0") == "0" else [], "hasMore": False}
    if path == f"/admin/fans/{ACCOUNT_ID}/by-ids":
        ids = ",".join(q.get("ids", [])).split(",")
        return {"fans": {i: {**user(FAN_BY_ID[i]), "id": int(i)} for i in ids if i in FAN_BY_ID}}
    if re.fullmatch(r"/api/of/v2/chats/(\d+)/media", path):
        return {"list": [], "hasMore": False}
    m = re.fullmatch(rf"/admin/fans/{ACCOUNT_ID}/(\d+)/ppv-history", path)
    if m:
        return {"items": [], "summary": {"count": 0, "max_cents": 0, "avg_cents": 0, "tips_cents": 0,
                                         "messages_cents": 0, "posts_cents": 0}}
    # The error badge's read (app/components/ErrorBadge.tsx), in service/server.py's /admin/errors
    # shape: one synthetic error in the last 24h, so the sweep's flag-on run measures the Window
    # header with the inline badge shown (it hides at zero; Phase 1 ticket 136). Sweep only: with
    # the flag off the badge sits in the closed Extras overflow, so the committed outputs stay as
    # they were, and the default run's shots are untouched.
    if SWEEP and path == "/admin/errors":
        return {"count": 1, "since_hours": 24, "list": [
            {"id": 1, "occurred_at": ago(30), "source": "browser", "kind": "ui-shots",
             "message": "ui-shots synthetic error", "stack": None, "url": None}]}
    m = re.fullmatch(rf"/admin/fans/{ACCOUNT_ID}/(\d+)", path)
    if m and m.group(1) in FAN_BY_ID:
        return fan_record(FAN_BY_ID[m.group(1)])
    if path == "/api/of/v2/users/list":
        ids = q.get("ids", []) + q.get("ids[]", [])
        return {i: user(FAN_BY_ID[i]) for i in ids if i in FAN_BY_ID}
    return None


# ── Router: default-deny ──────────────────────────────────────────────────────
RELAY_PREFIXES = ("/admin", "/api", "/auth", "/chatter", "/img", "/events", "/ws", "/health")
TO_RELAY = lambda p: p.startswith("/auth/") or p == "/events"  # noqa: E731


def relay_bound(path):  # app/next.config.ts rewrites these to the relay
    return any(path == x or path.startswith(x + "/") for x in RELAY_PREFIXES)


FONT_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com")
OWN_ORIGINS = {APP, RELAY}
# Belt under the router: Chromium resolves no name but localhost, so a request the router
# missed fails to resolve instead of leaving the machine.
LAUNCH_ARGS = ["--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost"]


def make_router(rec):
    def handle(route, request):
        u = urlsplit(request.url)
        if u.scheme in ("data", "blob"):
            return route.continue_()
        if u.hostname in FONT_HOSTS:
            rec["stubbedRequests"].append(request.url)
            return route.fulfill(status=200, body="", content_type="text/css" if "googleapis" in u.hostname else
                                 "font/woff2")
        if f"{u.scheme}://{u.netloc}" not in OWN_ORIGINS:
            rec["offHostRequests"].append(request.url)
            return route.abort()
        p = u.path
        if not relay_bound(p) or TO_RELAY(p):
            return route.continue_()
        body = fixture(request.method, p, parse_qs(u.query))
        if body is None:
            rec["unmatchedRequests"].append(f"{request.method} {p}{'?' + u.query if u.query else ''}")
            body = {}
        return route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
    return handle


def make_ws_router(rec):
    # page.route does not see WebSockets. Only own-origin sockets on a path that is not
    # relay-bound (the dev server's live reload) connect through. Relay-bound ones are
    # listed in unmatchedRequests, other origins in offHostRequests; neither is connected
    # to a server. (Not ws.close(): the sync API runs this handler on its dispatcher
    # fiber, where a blocking call spins forever. connect_to_server() does not block.)
    def handle(ws):
        u = urlsplit(ws.url)
        if f"{'https' if u.scheme == 'wss' else 'http'}://{u.netloc}" not in OWN_ORIGINS:
            rec["offHostRequests"].append(ws.url)
        elif relay_bound(u.path):
            rec["unmatchedRequests"].append(f"WS {u.path}{'?' + u.query if u.query else ''}")
        else:
            ws.connect_to_server()
    return handle


SELFTEST_JS = """(() => {
  const inject = () => {
    console.error("ui-shots self-test: injected console error");
    const d = document.createElement("div");
    d.setAttribute("data-ui-shots-selftest", "");
    d.style.cssText = "position:absolute;top:0;left:0;width:2000px;height:1px;pointer-events:none";
    document.body.appendChild(d);
    try { new WebSocket("wss://ui-shots-selftest.invalid/"); } catch (e) {}  // the WebSocket router must catch it
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", inject);
  else inject();
})();"""


# ── Steps and checks ──────────────────────────────────────────────────────────
def login(page, n):
    r = page.context.request.post(f"{APP}/auth/register",
                                  data={"username": f"uishots{n}", "password": "ui-shots-throwaway"})
    if not r.ok:
        raise RuntimeError(f"/auth/register -> {r.status} {r.text()[:200]}")


def pick_employee(page):
    # Commit 8c82ae32 retired the "Who's chatting?" pick: an Owner session acts as itself,
    # so this step only waits for the Fan List's first Fan.
    page.get_by_text(FAN_NAMES[0], exact=True).first.wait_for(timeout=60_000)


def open_first_fan(page):
    page.get_by_text(FAN_NAMES[0], exact=True).first.click(timeout=60_000)
    page.locator("[data-msg-id]").nth(len(THREAD) - 1).wait_for(timeout=60_000)


def open_second_fan(page):
    # The second Fan's Thread has no messages; its Chat header is mounted once "Open in new tab" shows.
    page.get_by_text(FAN_NAMES[1], exact=True).first.click(timeout=60_000)
    page.get_by_role("button", name="Open in new tab", exact=True).wait_for(timeout=60_000)


def open_in_new_tab(page):
    # Through the real Chat header: a button that is not mounted fails the step.
    page.get_by_role("button", name="Open in new tab", exact=True).click(timeout=30_000)


def show_fan_list(page):
    page.get_by_text(FAN_NAMES[0], exact=True).first.wait_for(timeout=60_000)


PPV_PRICE = "25"


def type_ppv_price(page):
    # The PPV row is closed until its "PPV" pill opens it (Phase 4 ticket 30).
    page.locator("[data-composer-area]").get_by_role("button", name="PPV", exact=True).click()
    page.get_by_label("PPV price").first.press_sequentially(PPV_PRICE)


def insights_pane(page):
    # The lg+ Fan insights pane is the complementary landmark named "Fan insights" (the slide-over
    # is a dialog of the same name, so it never matches). The insights shot, check_insights and
    # the pane height check all use this one locator. The Fan's name is no longer visible text in
    # the pane (the identity block sits in the collapsed Extras overflow, Phase 5 ticket 16), so
    # check_insights reads it from the Nickname field instead.
    return page.get_by_role("complementary", name="Fan insights").filter(visible=True).first


def visible_messages(page):
    return sum(1 for el in page.locator("[data-msg-id]").all() if el.is_visible())


def back_button(page):
    return page.get_by_title("Back to chat list")


def check_fan_names(page):
    return [{"name": f"Fan List shows {n!r}", "ok": page.get_by_text(n, exact=True).first.is_visible()}
            for n in FAN_NAMES]


def check_thread(page):
    return [{"name": f"Thread shows {len(THREAD)} messages", "ok": visible_messages(page) == len(THREAD)}]


def check_insights(page):
    # "Naming" the Fan: the pane's Nickname field holds the first Fan's name as value or placeholder.
    pane = insights_pane(page)
    nick = pane.get_by_role("textbox", name=re.compile("nickname", re.I)).first
    named = nick.count() > 0 and FAN_NAMES[0] in (nick.input_value(), nick.get_attribute("placeholder"))
    return [{"name": f"Fan insights pane visible, naming {FAN_NAMES[0]!r}", "ok": pane.is_visible() and named}]


def check_fan_tabs(page):
    # Phase 1 ticket 70: two Fan tabs, in open order, the second (the open conversation) active.
    tabs = page.get_by_role("tablist", name="Fan tabs strip").get_by_role("tab")
    # The name only: since ticket 73 the tab also holds the unread count and the signal.
    names = [t.locator("span").first.inner_text() for t in tabs.all()]
    selected = [t.get_attribute("aria-selected") for t in tabs.all()]
    return [{"name": f"two Fan tabs {FAN_NAMES[1]!r}, {FAN_NAMES[0]!r}, the second active",
             "ok": names == [FAN_NAMES[1], FAN_NAMES[0]] and selected == ["false", "true"]}]


def check_sidebar(page):
    # Phase 6 ticket 107 (spec D3): in-app Messages Pro keeps the docked sidebar in the DOM but
    # hidden at every width, and "Toggle sidebar" controls the (closed) drawer instead.
    sidebar = page.locator("#app-sidebar")
    toggle = page.get_by_role("button", name="Toggle sidebar")
    return [{"name": "#app-sidebar in the DOM and hidden", "ok": sidebar.count() == 1 and not sidebar.is_visible()},
            {"name": "'Toggle sidebar' controls #app-sidebar-drawer, collapsed",
             "ok": toggle.get_attribute("aria-controls") == "app-sidebar-drawer"
             and toggle.get_attribute("aria-expanded") == "false"}]


def check_ppv(page):
    ppv = next(m for m in THREAD if not m["isFree"])
    shown = page.locator(f'[data-msg-id="{ppv["id"]}"]').is_visible()
    price = page.get_by_text(f"${ppv['price']:.2f}", exact=True).first.is_visible()
    return [{"name": f"Thread shows the ${ppv['price']} PPV", "ok": shown and price}]


def check_ppv_status(page):
    # Phase 3 ticket 99: the fixture PPV is ours, unopened and has no isPaid, so its status line
    # reads "$15.00 · not paid". The line is the last line inside the card, as the old Infloww
    # overlay's `.ppv-mini .paid-tag`: its column holds exactly one, inside the bubble, and no
    # "UNLOCK FOR" bar (that is the Fan's view, not the Creator's).
    ppv = next(m for m in THREAD if not m["isFree"])
    bubble = page.locator(f'[data-msg-id="{ppv["id"]}"]')
    column = bubble.locator("xpath=..")
    text = f"${ppv['price']:.2f} · not paid"
    line = column.get_by_text(text, exact=True)
    inside = bubble.get_by_text(text, exact=True)
    ok = line.count() == 1 and inside.count() == 1 and inside.first.is_visible()
    no_bar = column.get_by_text("UNLOCK FOR", exact=False).count() == 0
    return [{"name": "the fixture PPV reads '· not paid' once, inside its card", "ok": ok},
            {"name": "the fixture PPV shows no 'UNLOCK FOR' bar", "ok": no_bar}]


def check_time_under_bubble(page):
    # Phase 3 ticket 97, moved by messages-pro-look-and-feel ticket 146 (Part C, Compare TH9): the
    # first fixture message's time sits under its bubble. The time is the <time> carrying the
    # fixture's createdAt, in the `data-time-row` that is the bubble box's next sibling; its box must
    # start below the bubble box's bottom and lie inside the bubble's column. The gap under the
    # bubble and the row's font size are recorded, and with them the bubble's computed radii, padding
    # and type (Compare TH7) and the gap from its line to the next run's line (TH8; the fixture's
    # sides alternate, so it holds no two-bubble run).
    first = THREAD[0]
    bubble = page.locator(f'[data-msg-id="{first["id"]}"]')
    bb, column = bubble.bounding_box(), bubble.locator("xpath=..").bounding_box()
    row = bubble.locator("xpath=following-sibling::*[1][@data-time-row]")
    time = row.locator(f'time[datetime="{first["createdAt"]}"]')
    box = time.first.bounding_box() if time.count() else None
    under = bool(bb and column and box) and (box["y"] >= bb["y"] + bb["height"]
                                             and column["x"] <= box["x"] and box["x"] + box["width"] <= column["x"] + column["width"]
                                             and box["y"] + box["height"] <= column["y"] + column["height"])
    rb = row.bounding_box() if row.count() else None
    shape = bubble.evaluate("e => { const s = getComputedStyle(e); return {radius: [s.borderTopLeftRadius,"
                            " s.borderTopRightRadius, s.borderBottomRightRadius, s.borderBottomLeftRadius],"
                            " padding: s.padding, font: [s.fontSize, s.lineHeight]}; }")
    lines = bubble.locator("xpath=../..")
    gap = lines.evaluate("l => { const n = l.nextElementSibling; return n ? n.getBoundingClientRect().top"
                         " - l.getBoundingClientRect().bottom : null; }")
    return [{"name": "the first fixture message's time sits under its bubble", "ok": under,
             "rowBelowBubble": round(rb["y"] - (bb["y"] + bb["height"]), 2) if rb and bb else None,
             "fontSize": row.evaluate("e => getComputedStyle(e).fontSize") if row.count() else None,
             "bubble": shape, "nextRunGap": round(gap, 2) if gap is not None else None}]


def check_receipt(page):
    # Phase 3 ticket 98, read in the bubble's column since ticket 146 (Part C): the first outgoing
    # fixture bubble's time row carries the glyph receipt named "Delivered". The fixture chat rows
    # set no lastReadMessageId, so no bubble is Seen.
    first = next(m for m in THREAD if m["fromUser"]["id"] == CREATOR["id"])
    column = page.locator(f'[data-msg-id="{first["id"]}"]').locator("xpath=..")
    tick = column.locator('[role="img"][aria-label="Delivered"]')
    ok = tick.count() == 1 and tick.first.is_visible() and tick.first.inner_text() == "✓"
    return [{"name": "an outgoing fixture bubble shows a receipt named 'Delivered' in its column", "ok": ok}]


# messages-pro-look-and-feel ticket 143 (Compare TH1-TH2): the Bubble action row beside an
# incoming bubble. `bubble_actions` is a bubble's "Message actions" group, in its bubble line.
INCOMING_ACTIONS = ["Pin", "Reply", "Like", "Translate"]


def bubble_actions(page, m):
    return page.locator(f'[data-msg-id="{m["id"]}"]').locator("xpath=../..").get_by_role(
        "group", name="Message actions")


def opacity(loc):
    return loc.evaluate("e => getComputedStyle(e).opacity")


def action_names(group):
    return [b.get_attribute("aria-label") for b in group.get_by_role("button").all()]


# At 1440: before any hover the first incoming fixture bubble's row is transparent; hovering the
# bubble shows it, naming Pin, Reply, Like and Translate in order, each inside the thread pane;
# with the pointer away and Pin focused it shows again. The row's drawn glyphs are recorded (the
# first glyph's gap after the bubble, the glyph pitch and widths). The check then blurs Pin and
# moves the pointer away again, and restores the list's scroll, so the PNG is the untouched state.
def check_bubble_actions_hover(page):
    first = next(m for m in THREAD if m["fromUser"]["id"] != CREATOR["id"])
    bubble = page.locator(f'[data-msg-id="{first["id"]}"]')
    group = bubble_actions(page, first)
    scroller = "e => { let s = e; while (s && getComputedStyle(s).overflowY !== 'auto') s = s.parentElement; return s; }"
    top = bubble.evaluate(f"e => ({scroller})(e).scrollTop")
    page.mouse.move(0, 0)
    hidden = group.count() == 1 and opacity(group) == "0"
    bubble.hover()
    shown = group.count() == 1 and opacity(group) == "1"
    names = action_names(group) if group.count() == 1 else []
    pane = page.locator('[data-mp-pane="thread"]').filter(visible=True).first.bounding_box()
    boxes = [b.bounding_box() for b in group.get_by_role("button").all()]
    inside = bool(pane) and all(b and pane["x"] <= b["x"] and b["x"] + b["width"] <= pane["x"] + pane["width"]
                                for b in boxes)
    glyphs = [b.bounding_box() for b in group.locator("svg").all()]
    bb = bubble.bounding_box()
    drawn = {"firstGlyphAfterBubble": round(glyphs[0]["x"] - (bb["x"] + bb["width"]), 2) if glyphs and bb else None,
             "pitch": [round(glyphs[i + 1]["x"] - glyphs[i]["x"], 2) for i in range(len(glyphs) - 1)],
             "box": [round(b["width"], 2) for b in boxes],
             "centreOnBubble": round((boxes[0]["y"] + boxes[0]["height"] / 2) - (bb["y"] + bb["height"] / 2), 2)
             if boxes and bb else None}
    page.mouse.move(0, 0)
    group.get_by_role("button", name="Pin", exact=True).focus()
    focused = opacity(group) == "1"
    page.evaluate("document.activeElement && document.activeElement.blur()")
    restored = opacity(group) == "0"
    bubble.evaluate(f"(e, t) => {{ ({scroller})(e).scrollTop = t; }}", top)
    return [{"name": "the first incoming bubble's Message actions show on hover only: transparent before, "
                     "shown on hover naming " + ", ".join(INCOMING_ACTIONS) + " in order inside the thread pane",
             "ok": bool(hidden and shown and names == INCOMING_ACTIONS and inside), "got": names, **drawn},
            {"name": "the first incoming bubble's Message actions show on focus: shown with Pin focused and "
                     "the pointer away, transparent again once blurred", "ok": bool(focused and restored)}]


# At 390: with no hover the last incoming fixture bubble's row shows, wholly inside the viewport,
# and each of its buttons is at least 24px each way (the shot's overflowX stays false).
def check_bubble_actions_phone(page):
    last = [m for m in THREAD if m["fromUser"]["id"] != CREATOR["id"]][-1]
    group = bubble_actions(page, last)
    width = page.viewport_size["width"]
    box = group.bounding_box() if group.count() == 1 else None
    shown = bool(box) and opacity(group) == "1" and 0 <= box["x"] and box["x"] + box["width"] <= width
    sizes = [b.bounding_box() for b in group.get_by_role("button").all()] if box else []
    big = bool(sizes) and all(b and b["width"] >= 24 and b["height"] >= 24 for b in sizes)
    return [{"name": "an incoming bubble's Message actions show with no hover, inside the 390px viewport",
             "ok": shown, "got": action_names(group) if box else []},
            {"name": "the phone Message actions buttons are at least 24px",
             "ok": big, "sizes": [[round(b["width"], 2), round(b["height"], 2)] for b in sizes if b]}]


# messages-pro-look-and-feel ticket 144 (Compare TH3-TH5): the Date divider above the first fixture
# message and the run avatars. `bubble_line` is the flex row holding a bubble's column.
def bubble_line(page, m):
    return page.locator(f'[data-msg-id="{m["id"]}"]').locator("xpath=../..")


# A run ends where the next message is on the other side or in another minute (the fixture has no
# "Sent by" label and no read pointer, so those never split it). The fixture's sides alternate,
# so every message ends its run. Each run's last line holds one `data-msg-avatar` slot, the Fan's
# as its first child and ours as its last; earlier lines hold none. The 36px box, its gap from the
# bubble and its bottom's offset from the bubble's are recorded for the first slot of each side.
def check_run_avatars(page):
    def side(m):
        return "creator" if m["fromUser"]["id"] == CREATOR["id"] else "fan"

    def ends_run(i):
        return i == len(THREAD) - 1 or side(THREAD[i + 1]) != side(THREAD[i]) \
            or THREAD[i + 1]["createdAt"][:16] != THREAD[i]["createdAt"][:16]
    ok, measured = True, {}
    for i, m in enumerate(THREAD):
        slots = bubble_line(page, m).evaluate("l => [...l.children].map(c => c.getAttribute('data-msg-avatar'))")
        want = side(m) if ends_run(i) else None
        edge = slots[0] if want == "fan" else slots[-1]
        ok = ok and edge == want and sum(1 for x in slots if x) == (1 if want else 0)
        if want and want not in measured:
            av = bubble_line(page, m).locator(":scope > [data-msg-avatar]").bounding_box()
            bb = page.locator(f'[data-msg-id="{m["id"]}"]').bounding_box()
            gap = (bb["x"] - (av["x"] + av["width"])) if want == "fan" else (av["x"] - (bb["x"] + bb["width"]))
            measured[want] = {"size": [round(av["width"], 2), round(av["height"], 2)], "gap": round(gap, 2),
                              "bottomBelowBubble": round((av["y"] + av["height"]) - (bb["y"] + bb["height"]), 2)}
    return [{"name": "every run's last bubble has its avatar: the Fan's first in its line, ours last", "ok": bool(ok),
             **measured}]


# The element just before the first fixture message's line is a separator whose label reads "Today",
# or the short month and day when the fixture spans midnight (computed in the page as the app does),
# lying wholly above the bubble; its label's computed text-transform is none.
def check_date_separator(page):
    first = THREAD[0]
    sep = bubble_line(page, first).locator("xpath=preceding-sibling::*[1]")
    want = page.evaluate("iso => { const d = new Date(iso), n = new Date(); return d.toDateString() === n.toDateString()"
                         " ? 'Today' : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }); }",
                         first["createdAt"])
    is_sep = sep.count() == 1 and sep.get_attribute("role") == "separator"
    box, bb = (sep.bounding_box() if is_sep else None), page.locator(f'[data-msg-id="{first["id"]}"]').bounding_box()
    above = bool(box and bb) and box["y"] + box["height"] <= bb["y"]
    label = sep.locator("span").first if is_sep else None
    style = label.evaluate("e => { const s = getComputedStyle(e); return [s.textTransform, s.fontSize]; }") \
        if label is not None and label.count() else [None, None]
    return [{"name": "a Date separator sits above the first fixture message", "got": sep.get_attribute("aria-label")
             if is_sep else None, "want": want, "ok": bool(is_sep and above and sep.get_attribute("aria-label") == want
                                                          and label.inner_text() == want)},
            {"name": "the Date separator label is not uppercase", "ok": style[0] == "none", "fontSize": style[1]}]


def check_selected_row(page):
    # The Fan List marks the selected Fan's row, and only it (spec Contracts; Phase 2 keeps it).
    marked = page.locator('[aria-current="true"]')
    ok = marked.count() == 1 and marked.first.get_by_text(FAN_NAMES[0], exact=True).count() == 1
    return [{"name": f"only {FAN_NAMES[0]!r}'s row has aria-current=\"true\"", "ok": ok}]


def fan_row(page, fan_id):
    return page.locator("[data-chat-row]").filter(has_text=FAN_BY_ID[str(fan_id)]["name"])


def badge_check(page, label, fan_id, locate):
    # Spend, status and activity load after the Fan List's deferred delay, so wait for the element
    # rather than for a fixed time. Then: the expected Fan's row shows it, and no other row does.
    rows = page.locator("[data-chat-row]")
    try:
        locate(fan_row(page, fan_id)).first.wait_for(timeout=30_000)
    except Exception:  # noqa: BLE001 — never appeared: the check fails below
        pass
    lit = [i for i in range(rows.count()) if locate(rows.nth(i)).count() > 0]
    name = FAN_BY_ID[str(fan_id)]["name"]
    ok = len(lit) == 1 and locate(fan_row(page, fan_id)).first.is_visible()
    return [{"name": f"only {name!r}'s row shows {label}", "ok": ok}]


def check_row_badges(page):
    return (badge_check(page, '"Off"', RENEWAL_OFF_FAN, lambda r: r.get_by_text("Off", exact=True))
            + badge_check(page, "🔥", PPV_FAN, lambda r: r.get_by_role("img", name="Bought a PPV within 7 days"))
            + badge_check(page, "❄️", QUIET_FAN,
                          lambda r: r.get_by_role("img", name="No message for over 72 hours"))
            + badge_check(page, "the expired ✕ avatar", EXPIRED_FAN,
                          lambda r: r.get_by_role("img", name="Subscription expired")))


def check_spend_display(page):
    # Phase 2 ticket 57. The figures are the fixture's spend in the spec's format: $12,480 reads
    # "$12.5k", Dana's $230 sits in a pill in the ✕ avatar's slot, and Eva's known zero is "$0".
    # The "$0" check waits for spend to load, so the no-pill check after it reads loaded data.
    checks = (badge_check(page, 'the orange figure "$12.5k"', BIG_SPENDER_FAN,
                          lambda r: r.get_by_text("$12.5k", exact=True))
              + badge_check(page, 'the ✕ avatar with a "$230" pill in its slot', EXPIRED_FAN,
                            lambda r: r.get_by_role("img", name="Subscription expired").locator("xpath=..")
                            .get_by_text("$230", exact=True))
              + badge_check(page, 'a "$0" pill', RENEWAL_OFF_FAN, lambda r: r.get_by_text("$0", exact=True)))
    shown = fan_row(page, QUIET_FAN).get_by_text(re.compile(r"^\$")).count()
    name = FAN_BY_ID[str(QUIET_FAN)]["name"]
    return checks + [{"name": f"{name!r}'s row, with no spend entry, shows no spend pill", "ok": shown == 0}]


def check_row_height(page):
    # messages-pro-look-and-feel ticket 137 (Compare FL1, FL7): the first fixture row's box is
    # Infloww's 96px, divider included, and its avatar a 40px square: the first square element
    # in the row at least 24px wide (no class names read).
    row = page.locator("[data-chat-row]").first
    box = row.bounding_box() if row.count() else None
    avatar = row.evaluate("""r => { for (const el of r.querySelectorAll("div")) {
        const b = el.getBoundingClientRect();
        if (b.width >= 24 && Math.abs(b.width - b.height) < 0.5) return [b.width, b.height]; } return null; }"""
                          ) if box else None
    width = page.viewport_size["width"]
    return [{"name": f"a Fan List row is 96px tall at {width}, with a 40px avatar",
             "ok": bool(box) and abs(box["height"] - 96) < 0.5 and avatar is not None
             and all(abs(v - 40) < 0.5 for v in avatar)}]


# The first fixture Fan's chat row says she is online (`chat_row`, "isOnline": i == 0), so her
# Chat header's presence line reads "Available now" (Phase 3 ticket 85).
FIRST_FAN_PRESENCE = "Available now"


def chat_header(page):
    # The Chat header is the <header> holding the "Fan insights" toggle (no class names read).
    return page.locator("header").filter(has=page.get_by_role("button", name="Fan insights", exact=True)).first


def check_chat_header(page):
    head = chat_header(page)
    name = head.get_by_text(FAN_NAMES[0], exact=True).first.is_visible()
    presence = head.get_by_text(FIRST_FAN_PRESENCE, exact=True).first
    # DOM text alone would pass a presence line cut to "Available …": the element holding the
    # text, and its parent, must each be at least as wide as what they hold.
    unclipped = presence.evaluate(
        "el => [el, el.parentElement].every(e => e.scrollWidth <= e.clientWidth)")
    return [{"name": f"Chat header shows {FAN_NAMES[0]!r} and {FIRST_FAN_PRESENCE!r}, not clipped",
             "ok": name and presence.is_visible() and unclipped}]


# The Chat header's icon row (Phase 3 tickets 86, 87, 88), by accessible name, in DOM order.
CHAT_HEADER_ICONS = ["Priority", "Mute notifications", "Notes", "Pinned chat", "Gallery", "Find"]
FOLLOWS_JS = "(a, b) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)"


def check_chat_header_icons(page):
    head = chat_header(page)
    icons = [head.get_by_role("button", name=n, exact=True) for n in CHAT_HEADER_ICONS]
    found = all(b.count() == 1 and b.is_visible() for b in icons)
    in_order = found and all(a.evaluate(FOLLOWS_JS, b.element_handle()) for a, b in zip(icons, icons[1:]))
    return [{"name": "Chat header's icon row names " + ", ".join(CHAT_HEADER_ICONS[:-1])
             + f" and {CHAT_HEADER_ICONS[-1]}, in that order", "ok": in_order}]


# The Chat header's right group (Phase 3 ticket 90), by accessible name, in DOM order. 📈 "Message
# statistics" moved into the Kebab menu (ticket 140). Since ticket 141 it ends line 1, so in DOM
# order it follows the "Avatar menu" button (the name), and line 2's icon row comes after it.
CHAT_HEADER_RIGHT = ["Open in new tab", "Refresh", "Fan insights", "More actions"]


def check_chat_header_right(page):
    head = chat_header(page)
    group = [head.get_by_title("Avatar menu", exact=True)] \
        + [head.get_by_role("button", name=n, exact=True) for n in CHAT_HEADER_RIGHT]
    found = all(b.count() == 1 and b.is_visible() for b in group)
    in_order = found and all(a.evaluate(FOLLOWS_JS, b.element_handle()) for a, b in zip(group, group[1:]))
    return [{"name": "Chat header's right group names " + ", ".join(CHAT_HEADER_RIGHT[:-1])
             + f" and {CHAT_HEADER_RIGHT[-1]}, in that order, after the name", "ok": in_order}]


def header_boxes(page, names):
    # The Chat header's box, the first Fan's name and presence text, and each named button's box; a
    # line-2 button by its drawn icon, since its 24px target's padding draws nothing (ticket 141).
    head = chat_header(page)
    def box(loc):
        return loc.first.bounding_box() if loc.count() >= 1 and loc.first.is_visible() else None
    def button(n):
        b = head.get_by_role("button", name=n, exact=True)
        return b.locator("svg") if n in CHAT_HEADER_ICONS else b
    return (head.bounding_box() if head.count() == 1 else None,
            box(head.get_by_text(FAN_NAMES[0], exact=True)),
            box(head.get_by_text(FIRST_FAN_PRESENCE, exact=True)),
            {n: box(button(n)) for n in names})


def middle(b):
    return b["y"] + b["height"] / 2


RIGHT_CENTRED = ["Open in new tab", "Refresh", "More actions"]


# messages-pro-look-and-feel ticket 141 (Compare CH1-CH3): at 1440 the Chat header is Infloww's two
# lines: 52px tall (1px), line 2 starts right after the presence text (Priority at most 24px past
# its right edge), its icons sit below the name's box, and the right group shares one vertical
# centre (1px) inside the header. The measured values are recorded with the check.
def check_chat_header_two_lines(page):
    head, name, presence, b = header_boxes(page, ["Priority", "Gallery", "Find", *RIGHT_CENTRED])
    found = bool(head and name and presence) and all(b.values())
    after = found and b["Priority"]["x"] - (presence["x"] + presence["width"])
    below = found and all(b[n]["y"] >= name["y"] + name["height"] for n in ("Priority", "Gallery", "Find"))
    centres = [middle(b[n]) for n in RIGHT_CENTRED] if found else []
    inside = found and all(head["y"] <= b[n]["y"] and b[n]["y"] + b[n]["height"] <= head["y"] + head["height"]
                           for n in RIGHT_CENTRED)
    return [{"name": "Chat header is two lines and line 2 follows the presence line: 52px tall (1px), "
                     "Priority at most 24px right of the presence text, Priority, Gallery and Find below the "
                     "name, 'Open in new tab', 'Refresh' and 'More actions' on one centre (1px)",
             "ok": bool(found and abs(head["height"] - 52) <= 1 and 0 <= after <= 24 and below and inside
                        and max(centres) - min(centres) <= 1),
             "height": head and head["height"], "priorityAfterPresence": after if found else None,
             "rightCentres": centres}]


# Ticket 141 on a 390 phone: two lines, Priority below the name's box and Find on Priority's line
# (centres 1px apart at most), and the header never scrolls sideways.
def check_chat_header_two_lines_phone(page):
    head, name, _, b = header_boxes(page, ["Priority", "Find"])
    found = bool(head and name) and all(b.values())
    fits = chat_header(page).evaluate("h => h.scrollWidth <= h.clientWidth") if head else False
    ok = found and b["Priority"]["y"] >= name["y"] + name["height"] \
        and abs(middle(b["Priority"]) - middle(b["Find"])) <= 1 and fits
    return [{"name": "Chat header is two lines on a phone: Priority below the name, Find on Priority's line, "
                     "no horizontal scroll", "ok": bool(ok), "height": head and head["height"]}]


# No Inflowwww extra renders inline in the Chat header (ticket 140): the "+" Extras overflow and
# 📈 are reached through the Kebab menu, and the header keeps no 🌐 translate toggle (the Composer
# toolbar's Translator drives that mode, spec F12).
def check_chat_header_extras(page):
    head = chat_header(page)
    inline = sum(head.get_by_role("button", name=n, exact=True).count()
                 for n in ["Inflowwww extras", "Message statistics"])
    no_translate = head.get_by_text(re.compile(r"🌐|translate", re.I)).count() == 0
    return [{"name": "no 'Inflowwww extras' or 'Message statistics' button in the Chat header, and no translate toggle",
             "ok": bool(inline == 0 and no_translate)}]


# The shots run with the Legacy flag off (OPENINFLOWW_LEGACY_AUTOMATIONS unset, below), so the
# Chat header holds no Persona button and no AI strip band (Phase 3 ticket 93).
def check_chat_header_legacy_off(page):
    head = chat_header(page)
    persona = head.get_by_role("button", name="Persona", exact=True).count()
    strip = head.get_by_role("note", name="AI status", exact=True).count()
    return [{"name": "no Persona button and no AI strip in the Chat header",
             "ok": head.count() == 1 and persona == 0 and strip == 0}]


def check_phone_header(page):
    head = chat_header(page)
    def shown(name):
        return any(b.is_visible() for b in head.get_by_role("button", name=name, exact=True).all())
    ok = back_button(page).is_visible() and shown("Fan insights") \
        and not shown("Open in new tab") and not shown("Refresh")
    return [{"name": "'Back to chat list' and 'Fan insights' are visible, "
             "and 'Open in new tab' and 'Refresh' are not", "ok": ok}]


def check_no_thread(page):
    return [{"name": "no Thread visible", "ok": visible_messages(page) == 0 and not back_button(page).is_visible()}]


def check_back(page):
    return [{"name": "'Back to chat list' visible", "ok": back_button(page).is_visible()}]


def check_fan_list_hidden(page):
    # The Fan List has no landmark yet; the other four Fan names appear only in it.
    shown = [n for n in FAN_NAMES[1:] if any(el.is_visible() for el in page.get_by_text(n, exact=True).all())]
    return [{"name": "Fan List not visible", "ok": not shown}]


def check_ppv_price(page):
    field = [el for el in page.get_by_label("PPV price").all() if el.is_visible()]
    return [{"name": f"Composer 'PPV price' holds {PPV_PRICE!r}",
             "ok": len(field) == 1 and field[0].input_value() == PPV_PRICE}]


def check_composer_in_viewport(page):
    box = page.locator("[data-composer-area]").bounding_box()
    vp = page.viewport_size
    ok = bool(box) and box["x"] >= 0 and box["y"] >= 0 and box["x"] + box["width"] <= vp["width"] + 1 \
        and box["y"] + box["height"] <= vp["height"] + 1
    return [{"name": "Composer inside the viewport", "ok": ok}]


def check_composer_rows(page):
    # Look-and-feel ticket 147 (Phase 5, C2 and C8): row 1 ("Composer buttons") is 44px tall, its
    # rule included; Send is 32px tall and its bottom edge sits 16px above the Composer's (row 3's
    # bottom padding, Send bottom-aligned in row 3 as in the capture).
    area = page.locator("[data-composer-area]").first
    composer = area.bounding_box()
    row1 = area.get_by_role("toolbar", name="Composer buttons").bounding_box()
    send = area.get_by_role("button", name="Send", exact=True).bounding_box()
    row1_h = row1 and round(row1["height"], 1)
    send_h = send and round(send["height"], 1)
    above = send and composer and round(composer["y"] + composer["height"] - (send["y"] + send["height"]), 1)
    return [{"name": "row 1 is 44px", "ok": row1_h is not None and abs(row1_h - 44) <= 1, "got": row1_h},
            {"name": "Send is 32px", "ok": send_h is not None and abs(send_h - 32) <= 1, "got": send_h},
            {"name": "Send 16px above Composer bottom", "ok": above is not None and abs(above - 16) <= 2,
             "got": above}]


def check_ppv_row_between(page):
    # Look-and-feel ticket 148 (Phase 5, C10): the PPV row opens between row 2 (the input) and row 3
    # ("Composer toolbar"), so row 3 and Send stay where they were. `got` is the PPV row's top less
    # the input's bottom, and row 3's top less the PPV row's bottom (both >= 0, 1px tolerance).
    area = page.locator("[data-composer-area]").first
    textbox = area.locator("textarea").first.bounding_box()
    ppv = area.get_by_role("group", name="PPV row").bounding_box()
    row3 = area.get_by_role("toolbar", name="Composer toolbar").bounding_box()
    above = textbox and ppv and round(ppv["y"] - (textbox["y"] + textbox["height"]), 1)
    below = ppv and row3 and round(row3["y"] - (ppv["y"] + ppv["height"]), 1)
    ok = above is not None and below is not None and above >= -1 and below >= -1
    return [{"name": "PPV row between input and toolbar", "ok": ok, "got": [above, below]}]


def check_no_top_bar(page):
    # Look-and-feel ticket 135 (SH1-SH2): at desktop in-app Messages Pro renders no Top bar, so the
    # Window header is the first row, and it holds the Top bar's toggle, time zone and avatar.
    header = page.get_by_role("region", name="Window header")
    box = header.bounding_box() if header.count() == 1 else None
    banners = [b for b in page.get_by_role("banner").all() if b.is_visible()]
    moved = [header.get_by_role("button", name="Toggle sidebar"), header.get_by_title("Your time zone"),
             header.get_by_role("button", name="Account menu")]
    return [{"name": "no Top bar above the Window header: its top is 0 and no banner is visible",
             "ok": box is not None and abs(box["y"]) <= 1 and not banners,
             "got": {"top": box and box["y"], "banners": len(banners)}},
            {"name": "Toggle sidebar, the time zone and Account menu sit in the Window header",
             "ok": all(m.count() == 1 and m.is_visible() for m in moved)}]


def check_top_bar_below_lg(page):
    banner = page.get_by_role("banner")
    return [{"name": "the Top bar is shown below lg",
             "ok": banner.count() == 1 and banner.is_visible()
             and banner.get_by_role("button", name="Toggle sidebar").is_visible()}]


def check_no_chrome(page):
    # In the DOM at all, not just visible: a Pop-out window renders no app chrome.
    return [{"name": "no #app-sidebar in the DOM", "ok": page.locator("#app-sidebar").count() == 0},
            {"name": "no 'Toggle sidebar' button in the DOM",
             "ok": page.get_by_role("button", name="Toggle sidebar", include_hidden=True).count() == 0}]


# A pane is the topmost ancestor of its anchor that holds no other pane's anchor, so the
# check needs no class names. Anchors: the last Fan's name (shown only in the Fan List),
# the Composer (the Thread's bottom row) and the Fan insights pane.
PANE_BOX_JS = """([anchor, others]) => {
  let pane = anchor;
  while (pane.parentElement && pane.parentElement !== document.body
         && !others.some((o) => o && pane.parentElement.contains(o))) pane = pane.parentElement;
  const r = pane.getBoundingClientRect();
  return { left: r.left, right: r.right, bottom: r.bottom, vw: innerWidth, vh: innerHeight };
}"""


def pane_anchors(page):
    def handle(loc):
        return loc.element_handle(timeout=5_000) if loc.count() else None
    return {"Fan List": handle(page.get_by_text(FAN_NAMES[-1], exact=True).first),
            "Thread": handle(page.locator("[data-composer-area]").first),
            "Fan insights": handle(insights_pane(page))}


def pane_fills_bottom(page, name, anchors):
    a = anchors[name]
    if a is None:
        return False
    b = page.evaluate(PANE_BOX_JS, [a, [h for k, h in anchors.items() if k != name]])
    return abs(b["bottom"] - b["vh"]) <= 1 and b["left"] >= -1 and b["right"] <= b["vw"] + 1


def check_panes_full_height(page):
    anchors = pane_anchors(page)
    return [{"name": f"{name} pane ends at the viewport's bottom edge (1px) and sits inside it horizontally",
             "ok": pane_fills_bottom(page, name, anchors)} for name in anchors]


# Phase 6 ticket 106: the three pane roots carry `data-mp-pane` (spec D9). From lg up they sit side
# by side in the Clone's order, tops level, with the Fan List 400px (page-parity 07 FL12) and Fan
# insights 280px (Gap rows PN2 and PN4, `MP.panes`); the Thread takes the rest.
PANE_WIDTHS = {"fan-list": 400, "insights": 280}


def pane_box(page, name):
    loc = page.locator(f'[data-mp-pane="{name}"]').filter(visible=True)
    return loc.first.bounding_box() if loc.count() == 1 else None


def check_pane_row(page):
    f, t, i = (pane_box(page, n) for n in ("fan-list", "thread", "insights"))
    found = bool(f and t and i)
    checks = [{"name": "one visible [data-mp-pane] root each for fan-list, thread and insights", "ok": found}]
    for name, box in (("fan-list", f), ("insights", i)):
        checks.append({"name": f"the {name} pane is {PANE_WIDTHS[name]}px wide (0.5px)",
                       "ok": bool(box) and abs(box["width"] - PANE_WIDTHS[name]) <= 0.5})
    side = found and f["x"] + f["width"] <= t["x"] + 1 and t["x"] + t["width"] <= i["x"] + 1 \
        and abs(f["y"] - t["y"]) <= 1 and abs(t["y"] - i["y"]) <= 1
    checks.append({"name": "fan-list, thread and insights side by side in that order, tops level (1px)",
                   "ok": bool(side)})
    return checks


# Phase 6 ticket 108 (hand-off from 106): with Fan insights open the Thread is 770px at 1440; since
# ticket 141 that is above the 448px word fold, so the two-line Chat header shows "Gallery", "Find"
# and "Open in new tab" as words and still fits. Its last control, the "More actions" kebab, must sit wholly inside the Thread pane's box. Strict:
# no tolerance. The two right edges are recorded with the check.
def check_kebab_in_thread(page):
    t = pane_box(page, "thread")
    kebab = chat_header(page).get_by_role("button", name="More actions", exact=True)
    k = kebab.bounding_box() if kebab.count() == 1 else None
    inside = bool(t and k) and t["x"] <= k["x"] and k["x"] + k["width"] <= t["x"] + t["width"] \
        and t["y"] <= k["y"] and k["y"] + k["height"] <= t["y"] + t["height"]
    return [{"name": "the Chat header's 'More actions' kebab sits inside the thread pane's box",
             "ok": inside, "kebabRight": k and k["x"] + k["width"], "threadRight": t and t["x"] + t["width"]}]


# Phase 1 ticket 133: Messages Pro's colours against the Colour inventory's Infloww values
# (docs/screenshots/messages-pro-compare.md). One sample per colour Compare row; each check's name
# carries its row ID, so a "matched" Status has a named passing check behind it. A sample is the
# element's own computed colour (no walk-up), written as #rrggbb; a translucent one reads null.
COLOUR_SAMPLES_JS = r"""(ids) => {
  const hex = (c) => {
    const m = (c || "").match(/[\d.]+/g);
    if (!m || m.length < 3 || (m.length > 3 && Number(m[3]) !== 1)) return null;
    return "#" + m.slice(0, 3).map((v) => Math.round(Number(v)).toString(16).padStart(2, "0")).join("");
  };
  const css = (el, prop) => (el ? hex(getComputedStyle(el)[prop]) : null);
  const msg = (id) => document.querySelector(`[data-msg-id="${id}"]`);
  const region = (name) => document.querySelector(`[role="region"][aria-label="${name}"]`);
  const row = [...document.querySelectorAll("[data-chat-row]")].find((r) => r.getAttribute("aria-current") === "true");
  const leaf = (root, text) => root && [...root.querySelectorAll("span")].find(
    (s) => s.childElementCount === 0 && s.textContent === text);
  const name = leaf(row, ids.name);
  const preview = leaf(row, ids.preview);
  const price = [...(msg(ids.ppv)?.parentElement?.querySelectorAll("div") || [])].find(
    (d) => d.textContent === ids.priceLine);
  const insights = document.querySelector('[data-mp-pane="insights"]');
  return {
    online: css([...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Online Fans"),
                "backgroundColor"),
    own: css(msg(ids.own), "backgroundColor"),
    fan: css(msg(ids.fan), "backgroundColor"),
    ppv: css(msg(ids.ppv), "backgroundColor"),
    ppvBorder: css(msg(ids.ppv), "borderTopColor"),
    priceLine: css(price, "color"),
    windowHeader: css(region("Window header"), "backgroundColor"),
    fanTabs: css(region("Fan tabs"), "backgroundColor"),
    fanList: css(document.querySelector('[data-mp-pane="fan-list"] > div'), "backgroundColor"),
    thread: css(document.querySelector('[data-mp-pane="thread"]')?.parentElement, "backgroundColor"),
    insights: css(insights, "backgroundColor"),
    selectedRow: css(row, "backgroundColor"),
    // The inset divider is the row's ::after fill (commit 342d3ca3, Compare FL16).
    rowDivider: row ? hex(getComputedStyle(row, "::after").backgroundColor) : null,
    name: css(name, "color"),
    preview: css(preview, "color"),
  };
}"""
# (row ID, what, sample key, the Colour inventory's Infloww value)
COLOUR_ROWS = [
    ("CO1", "the Fan List's Online Fans button is Infloww's accent", "online", "#4166f6"),
    ("CO2", "our own message bubble is Infloww's blue", "own", "#4166f6"),
    ("CO3", "the Fan's message bubble is Infloww's grey", "fan", "#262626"),
    ("CO4", "the PPV bubble is Infloww's grey card", "ppv", "#232323"),
    ("CO4", "the PPV bubble's outline", "ppvBorder", "#2f2f2f"),
    ("CO4", "the PPV's 'not paid' price line", "priceLine", "#8a8a8a"),
    ("CO5", "the Window header", "windowHeader", "#0d0d0d"),
    ("CO5", "the Fan tabs row", "fanTabs", "#2b2c30"),
    ("CO5", "the Fan List pane", "fanList", "#151515"),
    ("CO5", "the Thread pane", "thread", "#151515"),
    ("CO5", "the Fan insights pane", "insights", "#0d0d0d"),
    ("CO5", "the selected Fan row", "selectedRow", "#353535"),
    ("CO6", "a Fan List row divider", "rowDivider", "#444444"),
    ("CO7", "a Fan name (primary text)", "name", "#d9d9d9"),
    ("CO7", "a Fan row's preview (dim text)", "preview", "#999999"),
]


def colour_samples(page):
    own = next(m for m in THREAD if m["fromUser"]["id"] == CREATOR["id"] and m["isFree"])
    fan = next(m for m in THREAD if m["fromUser"]["id"] != CREATOR["id"])
    ppv = next(m for m in THREAD if not m["isFree"])
    return page.evaluate(COLOUR_SAMPLES_JS, {
        "own": own["id"], "fan": fan["id"], "ppv": ppv["id"], "priceLine": f"${ppv['price']:.2f} · not paid",
        "name": FAN_NAMES[0], "preview": THREAD[-1]["text"]})


def colour_checks(got, suffix=""):
    return [{"name": f"{rid} {what} {want}{suffix}", "ok": got.get(key) == want, "got": got.get(key)}
            for rid, what, key, want in COLOUR_ROWS]


def check_colours(page):
    return colour_checks(colour_samples(page))


def check_colours_light(page):
    # The app's light theme leaves Messages Pro in Infloww's dark palette: set the attribute in the
    # page, re-read the same samples, then restore whatever the page had.
    before = page.evaluate("document.documentElement.getAttribute('data-theme')")
    page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
    try:
        page.wait_for_timeout(200)
        got = colour_samples(page)
        # Read while the light theme is set: under it `html` is `color-scheme: light`.
        scheme = page.evaluate("""() => getComputedStyle(document.querySelector('[data-mp-pane="fan-list"]')).colorScheme""")
    finally:
        page.evaluate("(v) => v === null ? document.documentElement.removeAttribute('data-theme')"
                      " : document.documentElement.setAttribute('data-theme', v)", before)
    return ([{"name": f"same colours under data-theme=light: {c['name']}", "ok": c["ok"], "got": c["got"]}
             for c in colour_checks(got)]
            + [{"name": "same colours under data-theme=light: Messages Pro keeps color-scheme dark",
                "ok": scheme == "dark", "got": scheme}])


APP_ACCENT = "#3467ff"  # --color-accent, app/app/globals.css (the dark @theme)


def check_app_accent_outside(page):
    # The sidebar drawer is rendered by AppShell, outside Messages Pro's subtree, so its active link
    # (or the drawer itself when no link is active) reads the App accent, not Infloww's blue.
    page.get_by_role("button", name="Toggle sidebar").click()
    drawer = page.locator("#app-sidebar-drawer")
    drawer.wait_for(state="visible", timeout=10_000)
    accent = page.evaluate("""() => {
      const d = document.getElementById("app-sidebar-drawer");
      const el = d.querySelector('[aria-current="page"]') || d;
      return getComputedStyle(el).getPropertyValue("--color-accent").trim().toLowerCase();
    }""")
    page.keyboard.press("Escape")
    drawer.wait_for(state="hidden", timeout=10_000)
    return [{"name": f"App accent outside Messages Pro: the sidebar drawer reads {APP_ACCENT}, not #4166f6",
             "ok": accent == APP_ACCENT, "got": accent}]


OPEN_FIRST_FAN = [pick_employee, open_first_fan]
# The desktop shot only: two Fan tabs, the first Fan's last, so its conversation stays open and
# every earlier desktop check (selected row, Thread, PPV, Fan insights) still reads the first Fan.
OPEN_TWO_FAN_TABS = [pick_employee, open_second_fan, open_in_new_tab, open_first_fan, open_in_new_tab]
SHOTS = [
    {"name": "messages-pro-desktop", "url": "/messages-pro", "viewport": [1440, 900], "steps": OPEN_TWO_FAN_TABS,
     "checks": [check_no_top_bar, check_sidebar, check_fan_names, check_selected_row, check_thread, check_ppv, check_insights,
                check_row_badges, check_spend_display, check_row_height, check_fan_tabs, check_chat_header,
                check_chat_header_icons, check_chat_header_right, check_chat_header_extras,
                check_chat_header_legacy_off, check_chat_header_two_lines, check_time_under_bubble, check_receipt, check_ppv_status,
                check_bubble_actions_hover, check_run_avatars, check_date_separator,
                check_pane_row, check_kebab_in_thread, check_colours, check_colours_light,
                check_app_accent_outside, check_panes_full_height]},
    {"name": "messages-pro-popout", "url": "/messages-pro?window=1", "viewport": [1440, 900],
     "steps": OPEN_FIRST_FAN,
     "checks": [check_no_chrome, check_fan_names, check_thread, check_insights, check_panes_full_height,
                check_pane_row, check_kebab_in_thread],
     "selftest": True},
    # Element shot: only the Fan insights pane is written to the PNG.
    {"name": "messages-pro-insights", "url": "/messages-pro", "viewport": [1440, 900], "steps": OPEN_FIRST_FAN,
     "element": insights_pane, "checks": [check_insights]},
    {"name": "messages-pro-phone-list", "url": "/messages-pro", "viewport": [390, 844],
     "steps": [pick_employee, show_fan_list], "checks": [check_fan_names, check_no_thread, check_top_bar_below_lg, check_row_height]},
    {"name": "messages-pro-phone-thread", "url": "/messages-pro", "viewport": [390, 844], "steps": OPEN_FIRST_FAN,
     "checks": [check_thread, check_back, check_fan_list_hidden, check_phone_header,
                check_chat_header_two_lines_phone, check_bubble_actions_phone]},
    {"name": "messages-pro-composer-ppv", "url": "/messages-pro", "viewport": [1440, 900],
     "steps": OPEN_FIRST_FAN + [type_ppv_price], "checks": [check_ppv_price, check_composer_in_viewport, check_composer_rows,
                                                         check_ppv_row_between]},
]


# ── Flows: gated browser sequences with no PNG ───────────────────────────────
def check_thread_fills_bottom(page):
    return [{"name": "Thread pane ends at the viewport's bottom edge (1px)",
             "ok": pane_fills_bottom(page, "Thread", pane_anchors(page))}]


def insights_slide_over(page):
    return page.get_by_role("dialog", name="Fan insights")


def open_insights(page):
    page.get_by_role("button", name="Fan insights").filter(visible=True).first.click(timeout=30_000)
    insights_slide_over(page).wait_for(timeout=30_000)


def close_insights(page):
    insights_slide_over(page).get_by_role("button", name="Close").click(timeout=30_000)
    insights_slide_over(page).wait_for(state="detached", timeout=30_000)


def check_slide_over_open(page):
    return [{"name": "'Fan insights' opens the slide-over", "ok": insights_slide_over(page).is_visible()}]


def check_slide_over_gone(page):
    return [{"name": "closing Fan insights removes the slide-over", "ok": insights_slide_over(page).count() == 0}]


def back_to_list(page):
    back_button(page).click(timeout=30_000)
    show_fan_list(page)


# messages-pro-look-and-feel ticket 142 (Compare CH1): in the messages-pro-desktop state, the Chat
# header's "Edit name" pencil, pressed with Fan insights closed, opens Fan insights with the cursor in
# its Nickname field (focus is the edit affordance; the save stays Fan insights' blur path).
def close_fan_insights(page):
    set_insights(page, False)


def check_fan_insights_closed(page):
    return [{"name": "the Chat header's 'Fan insights' toggle closes Fan insights", "ok": not insights_open(page)}]


def press_edit_name(page):
    chat_header(page).get_by_role("button", name="Edit name", exact=True).click(timeout=30_000)


NICKNAME_FOCUSED_JS = """() => {
  const a = document.activeElement;
  return !!a && a.tagName === "INPUT" && a.checkVisibility() && !!a.closest('[data-mp-pane="insights"]')
    && [...a.labels].some((l) => l.textContent.trim() === "Nickname");
}"""


def check_edit_name_focuses_nickname(page):
    try:
        page.wait_for_function(NICKNAME_FOCUSED_JS, timeout=10_000)
    except Exception:  # noqa: BLE001 — read below; a timeout is a failed check, not a failed flow
        pass
    return [{"name": "'Edit name' opens Fan insights with Nickname focused (document.activeElement is "
                     "the visible Fan insights input labelled 'Nickname')",
             "ok": bool(insights_open(page) and page.evaluate(NICKNAME_FOCUSED_JS))}]


# Look-and-feel ticket 149 (Phase 5, C12-C14, stories 17-20 and 23): at 390 the Composer's row 1,
# its "+" and ⚙ panels, the PPV row and the Fan insights slide-over all stay inside the viewport.
def composer_area(page):
    return page.locator("[data-composer-area]").first


def box_in_viewport(page, box):
    vp = page.viewport_size
    return bool(box) and box["x"] >= -1 and box["y"] >= -1 and box["x"] + box["width"] <= vp["width"] + 1


def check_row1_on_one_line(page):
    # Every visible row-1 control shares one top (1px) and lies within the viewport.
    controls = [b for b in composer_area(page).get_by_role("toolbar", name="Composer buttons")
                .get_by_role("button").all() if b.is_visible()]
    boxes = [b.bounding_box() for b in controls]
    tops = [round(b["y"], 1) for b in boxes if b]
    rights = [round(b["x"] + b["width"], 1) for b in boxes if b]
    return [{"name": "row 1 on one line", "ok": len(tops) >= 7 and max(tops) - min(tops) <= 1,
             "got": [min(tops, default=None), max(tops, default=None)]},
            {"name": "row 1 in viewport", "ok": len(boxes) >= 7 and all(box_in_viewport(page, b) for b in boxes),
             "got": max(rights, default=None)}]


def panel_check(name, label):
    def check(page):
        area = composer_area(page)
        area.get_by_role("button", name=label, exact=True).click(timeout=30_000)
        panel = area.get_by_role("region", name=label, exact=True)
        panel.wait_for(timeout=30_000)
        box = panel.bounding_box()
        area.get_by_role("button", name=label, exact=True).click(timeout=30_000)
        panel.wait_for(state="detached", timeout=30_000)
        return [{"name": name, "ok": box_in_viewport(page, box),
                 "got": box and [round(box["x"], 1), round(box["x"] + box["width"], 1), round(box["y"], 1)]}]
    check.__name__ = f"check_{label.replace(' ', '_').lower()}_panel"
    return check


def check_quick_emojis_phone(page):
    # TODO.md A2 moved the quick emojis out of the "+" overflow to row 1, right after ⚙ (A1).
    area = composer_area(page)
    gear = area.get_by_role("button", name="Emoji favourites", exact=True).bounding_box()
    row = area.get_by_role("group", name="Quick emojis")
    box = row.bounding_box()
    first = row.get_by_role("button").first.bounding_box()
    after = bool(gear and box and first) and first["x"] >= gear["x"] + gear["width"] - 1 \
        and abs((first["y"] + first["height"] / 2) - (gear["y"] + gear["height"] / 2)) <= 1
    return [{"name": "quick emojis after ⚙", "ok": after,
             "got": gear and first and [round(gear["x"] + gear["width"], 1), round(first["x"], 1)]},
            {"name": "quick emojis in viewport", "ok": box_in_viewport(page, box),
             "got": box and [round(box["x"], 1), round(box["x"] + box["width"], 1)]}]


def check_timed_send_at_phone(page):
    # TODO.md A2 moved "Send at" +5m…+60m from the "+" overflow into ⏱; its panel and presets fit 390.
    area = composer_area(page)
    trigger = area.get_by_role("button", name="Timed message", exact=True)
    trigger.click(timeout=30_000)
    panel = area.get_by_role("region", name="Timed message", exact=True)
    panel.wait_for(timeout=30_000)
    box = panel.bounding_box()
    presets = panel.get_by_role("group", name="Send at presets").get_by_role("button")
    names = [b.inner_text().strip() for b in presets.all()]
    pboxes = [b.bounding_box() for b in presets.all()]
    trigger.click(timeout=30_000)
    panel.wait_for(state="detached", timeout=30_000)
    return [{"name": "⏱ panel in viewport", "ok": box_in_viewport(page, box),
             "got": box and [round(box["x"], 1), round(box["x"] + box["width"], 1), round(box["y"], 1)]},
            {"name": "Send at presets in ⏱", "ok": names == ["+5m", "+10m", "+15m", "+30m", "+60m"]
             and all(box_in_viewport(page, b) for b in pboxes), "got": names}]


def check_ppv_row_phone(page):
    # PPV mode on: the PPV row lies within x 0-390 and does not scroll sideways, and Send stays put.
    area = composer_area(page)
    send = area.get_by_role("button", name="Send", exact=True)
    before = send.bounding_box()
    area.get_by_role("button", name="PPV", exact=True).click(timeout=30_000)
    row = area.get_by_role("group", name="PPV row")
    row.wait_for(timeout=30_000)
    box = row.bounding_box()
    fits = row.evaluate("(el) => el.scrollWidth <= el.clientWidth")
    after = send.bounding_box()
    area.get_by_role("button", name="PPV", exact=True).click(timeout=30_000)
    row.wait_for(state="detached", timeout=30_000)
    moved = before and after and round(max(abs(after["x"] - before["x"]), abs(after["y"] - before["y"])), 1)
    return [{"name": "PPV row in viewport", "ok": box_in_viewport(page, box) and bool(fits),
             "got": box and [round(box["x"], 1), round(box["x"] + box["width"], 1)]},
            {"name": "Send unmoved by PPV", "ok": moved is not None and moved <= 1, "got": moved}]


# The slide-over's box, whether it or a card's scrolling ancestor scrolls sideways, and the
# narrowest gap between a card's right edge and the slide-over's less the padding-right between them.
SLIDE_OVER_FIT_JS = """(aside) => {
  const r = aside.getBoundingClientRect();
  const cards = [...aside.querySelectorAll("section[aria-labelledby]")].filter((c) => c.checkVisibility());
  const scrollers = new Set([aside]);
  let slack = null;
  for (const c of cards) {
    let pad = 0;
    for (let el = c.parentElement; el && aside.contains(el); el = el.parentElement) {
      pad += parseFloat(getComputedStyle(el).paddingRight) || 0;
      if (getComputedStyle(el).overflowX !== "visible") scrollers.add(el);
    }
    const s = r.right - c.getBoundingClientRect().right - pad;
    slack = slack === null ? s : Math.min(slack, s);
  }
  return {x: r.x, right: r.right, cards: cards.length, slack,
          overflow: [...scrollers].some((el) => el.scrollWidth > el.clientWidth)};
}"""


def check_slide_over_fit(page):
    fit = insights_slide_over(page).evaluate(SLIDE_OVER_FIT_JS)
    vp = page.viewport_size
    return [{"name": "slide-over in viewport", "ok": fit["x"] >= -1 and fit["right"] <= vp["width"] + 1,
             "got": [round(fit["x"], 1), round(fit["right"], 1)]},
            {"name": "slide-over no overflow", "ok": not fit["overflow"]},
            {"name": "slide-over padding visible", "ok": fit["cards"] > 0 and fit["slack"] >= -0.5,
             "got": fit["slack"] is not None and round(fit["slack"], 1)}]


STEP, CHECK = "step", "check"
FLOWS = [
    # Story 19: a Pop-out window on a phone is one pane at a time, as in-app.
    {"name": "phone-popout", "url": "/messages-pro?window=1", "viewport": [390, 844], "script": [
        (STEP, pick_employee), (STEP, show_fan_list), (CHECK, check_no_chrome), (CHECK, check_fan_names),
        (STEP, open_first_fan), (CHECK, check_thread), (CHECK, check_thread_fills_bottom),
        (STEP, open_insights), (CHECK, check_slide_over_open),
        (STEP, close_insights), (CHECK, check_slide_over_gone), (CHECK, check_thread),
        (STEP, back_to_list), (CHECK, check_fan_names), (CHECK, check_no_thread)]},
    # Ticket 149 (look-and-feel Phase 5): the Composer's overflows and the slide-over fit a phone.
    # The "+" Extras overflow is gone (TODO.md A2, d90e424f): its quick emojis and "Send at"
    # presets are checked where they moved; free previews sit inline in the PPV row only with
    # media attached, which this flow has no fixture for, so they are not checked here (A2).
    {"name": "phone-composer-overflow", "url": "/messages-pro", "viewport": [390, 844], "script": [
        (STEP, pick_employee), (STEP, open_first_fan), (CHECK, check_row1_on_one_line),
        (CHECK, check_quick_emojis_phone), (CHECK, check_timed_send_at_phone),
        (CHECK, panel_check("⚙ panel in viewport", "Emoji favourites")),
        (CHECK, check_ppv_row_phone),
        (STEP, open_insights), (CHECK, check_slide_over_fit), (STEP, close_insights)]},
    # Ticket 142: the header's "Edit name" pencil from the desktop shot's state (Compare CH1).
    {"name": "desktop-edit-name", "url": "/messages-pro", "viewport": [1440, 900], "script": [
        *[(STEP, step) for step in OPEN_TWO_FAN_TABS], (CHECK, check_insights),
        (STEP, close_fan_insights), (CHECK, check_fan_insights_closed),
        (STEP, press_edit_name), (CHECK, check_edit_name_focuses_nickname)]},
]


def open_page(browser, viewport, net, rec):
    """A fresh context: router and WebSocket router log to `net`, console errors to `rec`."""
    w, h = viewport
    # Fixed timezone and locale: shots match across machines and carry no host location.
    ctx = browser.new_context(viewport={"width": w, "height": h}, service_workers="block",
                              timezone_id="UTC", locale="en-US")
    ctx.route("**/*", make_router(net))
    ctx.route_web_socket(re.compile(".*"), make_ws_router(net))
    page = ctx.new_page()
    page.on("console", lambda m: m.type == "error" and rec["consoleErrors"].append(m.text))
    page.on("pageerror", lambda e: rec["consoleErrors"].append(f"uncaught: {e}"))
    return ctx, page


def run_flow(browser, n, spec):
    rec = {"name": spec["name"], "url": spec["url"], "viewport": spec["viewport"], "gated": True,
           "consoleErrors": [], "offHostRequests": [], "checks": []}
    # The flow record keeps the report's flow shape; stubbed and unmatched requests are not kept.
    net = {"offHostRequests": rec["offHostRequests"], "stubbedRequests": [], "unmatchedRequests": []}
    ctx, page = open_page(browser, spec["viewport"], net, rec)
    try:
        login(page, n)
        page.goto(APP + spec["url"], wait_until="domcontentloaded", timeout=120_000)
    except Exception as e:  # noqa: BLE001
        rec["checks"].append({"name": "page loaded", "ok": False})
        print(f"  {spec['name']}: page not loaded: {str(e).splitlines()[0]}")
        ctx.close()
        return rec
    for kind, fn in spec["script"]:
        try:
            if kind == STEP:
                fn(page)
            else:
                rec["checks"].extend(fn(page))
        except Exception as e:  # noqa: BLE001 — a step that cannot reach its state fails the flow, not the run
            rec["checks"].append({"name": f"{fn.__name__} {'reached' if kind == STEP else 'ran'}", "ok": False})
            print(f"  {spec['name']}: {fn.__name__} failed: {str(e).splitlines()[0]}")
            break
    ctx.close()
    return rec


def run_shot(browser, n, spec):
    rec = {"name": spec["name"], "file": f"{OUT}/{spec['name']}.png", "url": spec["url"],
           "viewport": spec["viewport"], "gated": True, "overflowX": False, "consoleErrors": [],
           "offHostRequests": [], "stubbedRequests": [], "unmatchedRequests": [], "checks": []}
    ctx, page = open_page(browser, spec["viewport"], rec, rec)
    reached = True
    try:
        login(page, n)
        if SELFTEST and spec.get("selftest"):
            ctx.add_init_script(SELFTEST_JS)
        page.goto(spec.get("origin", APP) + spec["url"], wait_until="domcontentloaded", timeout=120_000)
        for step in spec["steps"]:
            step(page)
        page.wait_for_timeout(1500)  # let late queries and layout settle
    except Exception as e:  # noqa: BLE001 — a step that cannot reach its state fails the shot, not the run
        reached = False
        print(f"  {spec['name']}: state not reached: {str(e).splitlines()[0]}")
    rec["checks"].append({"name": "state reached", "ok": reached})
    for check in spec["checks"]:
        try:
            rec["checks"].extend(check(page))
        except Exception as e:  # noqa: BLE001
            rec["checks"].append({"name": check.__name__, "ok": False})
            print(f"  {spec['name']}: {check.__name__} raised: {str(e).splitlines()[0]}")
    try:
        rec["overflowX"] = bool(page.evaluate("document.documentElement.scrollWidth > window.innerWidth"))
        target = spec["element"](page) if spec.get("element") else page
        target.screenshot(path=str(ROOT / rec["file"]))
    except Exception as e:  # noqa: BLE001
        print(f"  {spec['name']}: screenshot failed: {str(e).splitlines()[0]}")
    ctx.close()
    return rec


def shot_ok(rec):
    """The one gate, for shots and flows alike. A flow has no file and no overflow field."""
    if "file" in rec:
        f = ROOT / rec["file"]
        if not (f.exists() and f.stat().st_size > 0 and f.stat().st_mtime >= STARTED_AT):
            return False
    return bool(not rec.get("overflowX") and not rec["consoleErrors"] and not rec["offHostRequests"]
                and rec["checks"] and all(c["ok"] for c in rec["checks"]))


def server_attempts():
    log = TMP / "server-offhost.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


# ── Sweep (UI_SHOTS_SWEEP=1, Phase 6 ticket 109, spec D5): overflow, clipping and panes ──────────
# Eight runs, in the app and in the Pop-out window, each at four sizes. Each opens the page, clicks
# the first Fan row and waits for the Composer's textbox, then runs D5's checks (a) to (h). Only the
# in-app 1280 and 768 runs write a PNG; the 1440 and 390 PNGs are the default run's shots.
SWEEP_REPORT = ROOT / OUT / "messages-pro-sweep.json"
SWEEP_SIZES = [(1440, 900), (1280, 800), (768, 1024), (390, 844)]
SWEEP_PNG = {"inapp-1280": f"{OUT}/messages-pro-1280.png", "inapp-768": f"{OUT}/messages-pro-768.png"}
SWEEP_RUNS = [{"name": f"{kind}-{w}", "url": url, "viewport": [w, h]}
              for kind, url in (("inapp", "/messages-pro"), ("window", "/messages-pro?window=1"))
              for w, h in SWEEP_SIZES]
LG = 1024  # docs/routes.md: three panes from lg up, one pane at a time below it
# (h): a 60-character Fan name, set in the page on the Chat header's name (no new fixture).
LONG_NAME = (FAN_NAMES[0] + " ") * 6
LONG_NAME = LONG_NAME[:60]
assert len(LONG_NAME) == 60

# (b): every element under `main` (the window root in a Pop-out window is `main` too) at least half
# the viewport tall is no wider inside than out (1px), and every visible button and textbox inside a
# `[data-mp-pane]` root lies inside that pane's rect (1px). A scroller inside the pane exempts only
# the axis it really scrolls on (overflow auto or scroll, and content larger than its box): a
# sideways strip (chips, tab strips) on x, a vertical scroller (the message list, whose scrolled-out
# rows sit above the pane) on y. A tall scroller's own sideways overflow is still
# caught by the first rule.
CLIPPED_JS = r"""() => {
  const sel = (el) => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += "#" + el.id;
    const pane = el.getAttribute("data-mp-pane");
    if (pane) s += `[data-mp-pane="${pane}"]`;
    const cls = typeof el.className === "string" ? el.className.trim().split(/\s+/).filter(Boolean) : [];
    return s + cls.slice(0, 4).map((c) => "." + c).join("");
  };
  const label = (el) => (el.getAttribute("aria-label") || el.getAttribute("title")
    || (el.textContent || "").trim().slice(0, 40) || el.getAttribute("placeholder") || sel(el));
  const wide = [], outside = [];
  const root = document.querySelector("main");
  if (!root) return { root: false, wide, outside };
  for (const el of [root, ...root.querySelectorAll("*")]) {
    if (el.getBoundingClientRect().height < innerHeight / 2) continue;
    if (el.scrollWidth > el.clientWidth + 1)
      wide.push({ selector: sel(el), scrollWidth: el.scrollWidth, clientWidth: el.clientWidth });
  }
  const CONTROLS = 'button, [role="button"], textarea, [role="textbox"], [contenteditable="true"], '
    + '[contenteditable=""], input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"])'
    + ':not([type="range"]):not([type="file"])';
  for (const pane of root.querySelectorAll("[data-mp-pane]")) {
    if (!pane.checkVisibility()) continue;
    const p = pane.getBoundingClientRect();
    if (!p.width || !p.height) continue;
    for (const el of pane.querySelectorAll(CONTROLS)) {
      if (!el.checkVisibility({ visibilityProperty: true })) continue;
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      // A scroller inside the pane holds the control on the axis it really scrolls: a sideways strip
      // (chips, tabs) on x, the message list on y. The overflow value alone is not enough: CSS
      // computes overflow-x: visible to auto beside overflow-y: auto, so a plain vertical scroller
      // would otherwise exempt its controls on x too.
      let heldX = false, heldY = false;
      for (let a = el.parentElement; a && a !== pane; a = a.parentElement) {
        const cs = getComputedStyle(a);
        heldX ||= (cs.overflowX === "auto" || cs.overflowX === "scroll") && a.scrollWidth > a.clientWidth + 1;
        heldY ||= (cs.overflowY === "auto" || cs.overflowY === "scroll") && a.scrollHeight > a.clientHeight + 1;
      }
      const outX = !heldX && (r.left < p.left - 1 || r.right > p.right + 1);
      const outY = !heldY && (r.top < p.top - 1 || r.bottom > p.bottom + 1);
      if (outX || outY)
        outside.push({ pane: pane.getAttribute("data-mp-pane"), control: label(el),
                       left: Math.round(r.left), right: Math.round(r.right),
                       paneLeft: Math.round(p.left), paneRight: Math.round(p.right) });
    }
  }
  return { root: true, wide, outside };
}"""

PANES_JS = """() => {
  const boxes = {};
  for (const name of ["fan-list", "thread", "insights"]) {
    const shown = [...document.querySelectorAll(`[data-mp-pane="${name}"]`)].filter((e) => e.checkVisibility());
    const r = shown.length === 1 ? shown[0].getBoundingClientRect() : null;
    boxes[name] = { count: shown.length, box: r && { left: r.left, right: r.right, top: r.top, width: r.width,
                                                    height: r.height } };
  }
  return { boxes, vw: innerWidth, vh: innerHeight };
}"""


def overflow_x(page):
    return bool(page.evaluate("document.documentElement.scrollWidth > window.innerWidth"))


def sweep_clipped(page, tag, rec):
    """(b), and its repeats in (f) and (h). Failing tall elements go to `wide`."""
    got = page.evaluate(CLIPPED_JS)
    fails = []
    if not got["root"]:
        fails.append(f"{tag} no <main> root")
    for w in got["wide"]:
        rec["wide"].append(w)
        fails.append(f"{tag} {w['selector']} is wider inside than out ({w['scrollWidth']} > {w['clientWidth']})")
    for o in got["outside"]:
        fails.append(f"{tag} {o['control']!r} lies outside the {o['pane']} pane "
                     f"(x {o['left']}-{o['right']}, pane x {o['paneLeft']}-{o['paneRight']})")
    return fails


def sweep_panes(page):
    """(c) from lg up, (d) below it. Returns ("three" | "one" | "bad", failure lines)."""
    got = page.evaluate(PANES_JS)
    b, vw, vh = got["boxes"], got["vw"], got["vh"]
    if vw >= LG:
        f, t, i = (b[n]["box"] for n in ("fan-list", "thread", "insights"))
        fails = [f"(c) one visible {n} pane, found {b[n]['count']}" for n in b if b[n]["count"] != 1]
        if not fails:
            fails += [f"(c) the {n} pane is 0px wide" for n, x in (("fan-list", f), ("thread", t), ("insights", i))
                      if x["width"] <= 0]
            fails += [f"(c) the {n} pane is under half the viewport tall ({x['height']:.0f}px)"
                      for n, x in (("fan-list", f), ("thread", t), ("insights", i)) if x["height"] < vh / 2]
            if not (f["right"] <= t["left"] + 1 and t["right"] <= i["left"] + 1 and i["right"] <= vw):
                fails.append(f"(c) panes not in order inside the viewport: fan-list {f['left']:.0f}-{f['right']:.0f}, "
                             f"thread {t['left']:.0f}-{t['right']:.0f}, insights {i['left']:.0f}-{i['right']:.0f}")
            if abs(f["top"] - t["top"]) > 1 or abs(t["top"] - i["top"]) > 1:
                fails.append(f"(c) pane tops not level: {f['top']:.0f}, {t['top']:.0f}, {i['top']:.0f}")
        return ("bad" if fails else "three"), fails
    shown = [n for n in ("fan-list", "thread") if b[n]["count"] >= 1]
    if len(shown) != 1:
        return "bad", [f"(d) exactly one of the Fan List and the Thread visible, found {shown or 'none'}"]
    return "one", []


def insights_open(page):
    return page.locator('[data-mp-pane="insights"]').filter(visible=True).count() > 0


def set_insights(page, want):
    """Press the Chat header's "Fan insights" toggle once if the pane is not in the wanted state."""
    if insights_open(page) == want:
        return
    chat_header(page).get_by_role("button", name="Fan insights", exact=True).click(timeout=30_000)
    page.wait_for_function("(want) => [...document.querySelectorAll('[data-mp-pane=\"insights\"]')]"
                           ".some((e) => e.checkVisibility()) === want", arg=want, timeout=30_000)
    page.wait_for_timeout(300)


def gallery_word_width(page):
    gallery = chat_header(page).get_by_role("button", name="Gallery", exact=True)
    if gallery.count() != 1:
        return None
    word = gallery.get_by_text("Gallery", exact=True)
    box = word.bounding_box() if word.count() == 1 else None
    return box["width"] if box else 0


def sweep_gallery(page, insights):
    """(g) at 1440: the word "Gallery" shows with Fan insights closed (a 1050px Thread) and with it
    open (770px), both above the 448px word fold (messages-pro-look-and-feel ticket 141, Compare CH3;
    until then the fold sat at 886px and hid the word with Fan insights open, spec D4, CH14)."""
    w = gallery_word_width(page)
    state = " with Fan insights open" if insights else " with Fan insights closed"
    if w is None:
        return ["(g) no button named 'Gallery' in the Chat header" + state]
    if w <= 1:
        return [f"(g) the word 'Gallery' is hidden ({w:.0f}px wide)" + state]
    return []


# (h), story 32: the name ends in an ellipsis, and the painted text of the name and of the presence
# line (each text's extent, cut by every ancestor that clips sideways) starts inside the "Avatar menu"
# button that holds them and ends before what follows it: the presence text before Priority's drawn
# icon, the name before the right group. Since ticket 141 that button's box covers line 2's cell, so
# its right edge would let a presence line painted over Priority pass. (b) alone misses a name or
# presence line that spills over the icon row without pushing a button out of the pane.
SPILL_JS = """([name, presence, priority, kebab]) => {
  const button = name.closest("button");
  const b = button.getBoundingClientRect();
  const painted = (el) => {
    const range = document.createRange();
    range.selectNodeContents(el);
    let { left, right } = range.getBoundingClientRect();
    for (let a = el; a && a !== button.parentElement; a = a.parentElement) {
      if (getComputedStyle(a).overflowX === "visible") continue;
      const r = a.getBoundingClientRect();
      left = Math.max(left, r.left);
      right = Math.min(right, r.right);
    }
    return { left, right };
  };
  return { left: b.left, priority: priority.getBoundingClientRect().left,
           right: kebab.parentElement.getBoundingClientRect().left, name: painted(name), presence: painted(presence),
           ellipsis: getComputedStyle(name).textOverflow === "ellipsis" && name.scrollWidth > name.clientWidth };
}"""


def sweep_long_name(page, rec):
    """(h) in inapp-1280: the Chat header's Fan name set to 60 characters in the page, then (b) again,
    and the name ends in an ellipsis, the name and presence line starting inside the "Avatar menu"
    button, the presence text ending before Priority's icon and the name before the right group."""
    head = chat_header(page)
    name = head.get_by_text(FAN_NAMES[0], exact=True)
    presence = head.get_by_text(FIRST_FAN_PRESENCE, exact=True)
    priority = head.get_by_role("button", name="Priority", exact=True).locator("svg")
    kebab = head.get_by_role("button", name="More actions", exact=True)
    if name.count() != 1 or presence.count() != 1 or priority.count() != 1 or kebab.count() != 1:
        return ["(h) the Chat header's Fan name, presence line, Priority or 'More actions' not found"]
    handle = name.element_handle()
    handle.evaluate("(el, s) => { el.textContent = s; }", LONG_NAME)
    page.wait_for_timeout(300)
    fails = sweep_clipped(page, "(h)", rec)
    got = page.evaluate(SPILL_JS, [handle, presence.element_handle(), priority.element_handle(),
                                   kebab.element_handle()])
    if not got["ellipsis"]:
        fails.append("(h) the 60-character name does not end in an ellipsis")
    for part, end, what in (("name", "right", "the right group"), ("presence", "priority", "Priority")):
        t = got[part]
        if t["left"] < got["left"] - 1 or t["right"] > got[end] + 1:
            fails.append(f"(h) the {part} text spills (x {t['left']:.0f}-{t['right']:.0f}; the Avatar menu "
                         f"button starts at x {got['left']:.0f}, {what} at x {got[end]:.0f})")
    if handle.evaluate("el => el.textContent") != LONG_NAME:
        fails.append("(h) the 60-character name did not hold while (b) ran")
    handle.evaluate("(el, s) => { el.textContent = s; }", FAN_NAMES[0])
    return fails


def open_first_fan_row(page):
    page.locator("[data-chat-row]").first.click(timeout=60_000)
    page.locator("[data-composer-area]").get_by_role("textbox").filter(visible=True).first.wait_for(timeout=60_000)


def run_sweep(browser, n, spec):
    w = spec["viewport"][0]
    rec = {"name": spec["name"], "url": spec["url"], "viewport": spec["viewport"],
           "file": SWEEP_PNG.get(spec["name"]), "overflowX": False, "wide": [], "panes": "bad",
           "consoleErrors": [], "offHostRequests": [], "failures": [], "ok": False}
    net = {"offHostRequests": rec["offHostRequests"], "stubbedRequests": [], "unmatchedRequests": []}
    ctx, page = open_page(browser, spec["viewport"], net, rec)
    fails = rec["failures"]
    try:
        login(page, n)
        page.goto(APP + spec["url"], wait_until="domcontentloaded", timeout=120_000)
        pick_employee(page)
        open_first_fan_row(page)
        page.wait_for_timeout(1500)  # let late queries and layout settle
        if w >= LG:
            set_insights(page, True)  # three panes means Fan insights open (a Deep link opens it closed)
        rec["overflowX"] = overflow_x(page)  # (a)
        fails += sweep_clipped(page, "(b)", rec)
        rec["panes"], pane_fails = sweep_panes(page)  # (c) or (d)
        fails += pane_fails
        if rec["file"]:
            page.screenshot(path=str(ROOT / rec["file"]))
        if w == 1440:
            fails += sweep_gallery(page, True)
        if spec["name"] == "inapp-1280":
            fails += sweep_long_name(page, rec)
        if w >= LG:  # (f): the Thread at its widest, Fan insights closed
            set_insights(page, False)
            if overflow_x(page):
                fails.append("(f) the page scrolls sideways with Fan insights closed")
            fails += sweep_clipped(page, "(f)", rec)
            if w == 1440:
                fails += sweep_gallery(page, False)
    except Exception as e:  # noqa: BLE001 — a step that cannot reach its state fails the run, not the sweep
        fails.append(f"state not reached: {str(e).splitlines()[0]}")
    ctx.close()
    # (e): Phase 0's console-error and off-host checks.
    if rec["consoleErrors"]:
        fails.append(f"(e) {len(rec['consoleErrors'])} console error(s)")
    if rec["offHostRequests"]:
        fails.append(f"(e) {len(rec['offHostRequests'])} off-host request(s)")
    if rec["file"]:
        f = ROOT / rec["file"]
        if not (f.exists() and f.stat().st_size > 0 and f.stat().st_mtime >= STARTED_AT):
            fails.append(f"{rec['file']} missing, empty or stale")
    rec["ok"] = not rec["overflowX"] and not fails
    return rec


def sweep():
    runs = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=LAUNCH_ARGS)
        for n, spec in enumerate(SWEEP_RUNS):
            print(f"ui-shots: sweep {spec['name']} …")
            runs.append(run_sweep(browser, n, spec))
        browser.close()
    ok = all(r["ok"] for r in runs)
    SWEEP_REPORT.write_text(json.dumps({"ok": ok, "runs": runs}, indent=2) + "\n")
    for r in runs:
        print(f"  {r['name']}: {'PASS' if r['ok'] else 'FAIL'} overflowX={r['overflowX']} panes={r['panes']} "
              f"consoleErrors={len(r['consoleErrors'])} offHost={len(r['offHostRequests'])}")
        for line in r["failures"]:
            print(f"    {line}")
        for e in r["consoleErrors"]:
            print(f"    console: {e[:300]}")
    print(f"ui-shots: sweep report {OUT}/messages-pro-sweep.json ok={ok}")
    sys.exit(0 if ok else 1)


def main():
    shots, flows = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=LAUNCH_ARGS)
        for n, spec in enumerate(SHOTS):
            print(f"ui-shots: {spec['name']} …")
            shots.append(run_shot(browser, n, spec))
        for n, spec in enumerate(FLOWS, start=len(SHOTS)):
            print(f"ui-shots: flow {spec['name']} …")
            flows.append(run_flow(browser, n, spec))
        browser.close()
    ok = all(shot_ok(s) for s in shots + flows if s["gated"])
    report = {"ok": ok, "startedAt": STARTED_AT, "shots": shots, "flows": flows,
              "serverOffHostAttempts": server_attempts()}
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    for s in shots:
        bad = [c["name"] for c in s["checks"] if not c["ok"]]
        print(f"  {s['name']}: {'PASS' if shot_ok(s) else 'FAIL'} overflowX={s['overflowX']} "
              f"consoleErrors={len(s['consoleErrors'])} offHost={len(s['offHostRequests'])} "
              f"unmatched={len(s['unmatchedRequests'])} checks={len(s['checks'])}"
              + (f" failed={bad}" if bad else ""))
        for e in s["consoleErrors"]:
            print(f"    console: {e[:300]}")
    for fl in flows:
        bad = [c["name"] for c in fl["checks"] if not c["ok"]]
        print(f"  flow {fl['name']}: {'PASS' if shot_ok(fl) else 'FAIL'} consoleErrors={len(fl['consoleErrors'])} "
              f"offHost={len(fl['offHostRequests'])} checks={len(fl['checks'])}" + (f" failed={bad}" if bad else ""))
        for e in fl["consoleErrors"]:
            print(f"    console: {e[:300]}")
    print(f"ui-shots: serverOffHostAttempts={len(report['serverOffHostAttempts'])} (recorded, refused)")
    print(f"ui-shots: report {OUT}/messages-pro-report.json ok={ok}")
    sys.exit(0 if ok else 1)


try:
    sweep() if SWEEP else main()
except KeyboardInterrupt:
    sys.exit(130)
PY

# ── Preflight: the browser must already be cached ───────────────────────────
UI_SHOTS_ROOT="$ROOT" "$PY" "$TMP/driver.py" preflight

# ── Start the stack ─────────────────────────────────────────────────────────
read -r RELAY_PORT APP_PORT CLOSED_PORT < <("$PY" -c '
import socket
ss = [socket.socket() for _ in range(3)]
for s in ss: s.bind(("127.0.0.1", 0))
print(*[s.getsockname()[1] for s in ss])
for s in ss: s.close()')
RELAY="http://127.0.0.1:$RELAY_PORT"
APP="http://127.0.0.1:$APP_PORT"
DEAD_PROXY="http://127.0.0.1:$CLOSED_PORT"   # nothing listens: proxied calls are refused

set -m  # each background job gets its own process group, so the trap can stop its children too

env -u OPENINFLOWW_LEGACY_AUTOMATIONS \
  DATABASE_URL="sqlite+aiosqlite:///$TMP/relay.db" CHATTERLY_DB_URL="sqlite:///$TMP/relay.db" \
  CHATTERLY_TEST_MODE=1 SHARE_TOKEN= \
  SESSION_SECRET=ui-shots-session-not-for-prod CHATTER_SESSION_SECRET=ui-shots-chatter-not-for-prod \
  ADMIN_PASSWORD=ui-shots-admin-not-for-prod DEEPSEEK_API_KEY=ui-shots-fake \
  DEEPINFRA_API_KEY=ui-shots-fake GOOGLE_DRIVE_API_KEY=ui-shots-fake \
  UI_SHOTS_ROOT="$ROOT" UI_SHOTS_TMP="$TMP" UI_SHOTS_RELAY_PORT="$RELAY_PORT" \
  "$PY" "$TMP/relay.py" >"$TMP/relay.log" 2>&1 &
PIDS+=($!); disown $!

(cd "$ROOT/app" && exec env RELAY_URL="$RELAY" NEXT_DIST_DIR=.next/ui-shots NEXT_TELEMETRY_DISABLED=1 \
  HTTP_PROXY="$DEAD_PROXY" HTTPS_PROXY="$DEAD_PROXY" http_proxy="$DEAD_PROXY" https_proxy="$DEAD_PROXY" \
  NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
  NODE_OPTIONS="--require $TMP/fetch-guard.cjs" UI_SHOTS_TMP="$TMP" \
  node node_modules/next/dist/bin/next dev --webpack -H 127.0.0.1 -p "$APP_PORT") >"$TMP/next.log" 2>&1 &
PIDS+=($!); disown $!

set +m

wait_for() {  # name url timeout-seconds pid log
  local i
  for i in $(seq 1 "$3"); do
    if curl --noproxy '*' -s -o /dev/null --max-time 60 "$2"; then return 0; fi
    if ! kill -0 "$4" 2>/dev/null; then
      echo "ui-shots: $1 exited during startup; last log lines:" >&2; tail -n 30 "$5" >&2; exit 4
    fi
    sleep 1
  done
  echo "ui-shots: $1 not ready at $2 after $3s; last log lines:" >&2; tail -n 30 "$5" >&2; exit 4
}
echo "ui-shots: relay $RELAY, app $APP, temp $TMP"
wait_for relay "$RELAY/health" 60 "${PIDS[0]}" "$TMP/relay.log"
wait_for "next dev" "$APP/" 240 "${PIDS[1]}" "$TMP/next.log"

UI_SHOTS_ROOT="$ROOT" UI_SHOTS_TMP="$TMP" UI_SHOTS_APP="$APP" UI_SHOTS_RELAY="$RELAY" \
  UI_SHOTS_STARTED_AT="$STARTED_AT" UI_SHOTS_SELFTEST="${UI_SHOTS_SELFTEST:-}" \
  UI_SHOTS_SWEEP="${UI_SHOTS_SWEEP:-}" "$PY" -u "$TMP/driver.py"
