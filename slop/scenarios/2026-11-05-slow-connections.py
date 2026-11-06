"""The owner's phone far from the host: what each everyday screen costs on a slow connection. The AE client works
from Tokyo (250 ms to the Düsseldorf host, measured 2026-11-05); the owner from Slovenia (25 ms) calls it instant.

The stack as a live deployment serves it: the app as a production build (`APP_MODE = "prod"`) behind a TLS +
HTTP/2 edge (lib/wan.py's nghttpx, as Traefik; its DelayProxy at 0 ms: the round trip is Chromium's, below).
OnlyFans is lib/of_wire.py (`OF_WIRE`), each call `of_ms` (300); its CDN is lib/img_relay.py's fake (chat photos,
vault thumbs), each asset `cdn_ms` (50).

The world: one Agency with `creators` (13) Creators, every one with a captured session, its seeded Fans and threads
(seed/threads.py) as OF's chat list (`fake.chats`) and threads (`fake.messages`: the seeded rows, photos included);
chat photos (seed/chat_media.py, `slow_conn_chat_assets`); the opened Fan's Creator has `slow_conn_vault_media`
photos in its OF vault (`fake.vault_media`). The opened Fan: a chat with photos, heading the Fan List.

Per lib/net.py profile (`--net=X`: X only; default si, jp, jp-mobile, jp-bad), one fresh browser context (390x844,
touch, iPhone UA; nothing cached), its page throttled (`net.emulate`; a wire profile, jp-lossy / jp-lossy-bad: by
dummynet on the edge's port instead, below), the flows in order, each timed by
`net.Meter` from its trigger to settled (its key on screen and the network 1.5 s quiet; the /events stream and the
perf log's 10 s beacon aside):
  dashboard  `/` typed (cold): Total earnings' figure
  creators   the drawer's Creators > Manage creators link (drawer opened, then the network quiet, untimed: Next
             prefetches a link once it shows): the table's first page rows
  fan-list   /messages-pro loaded in the page (the nav opens it as its own window, a phone's new tab: a new
             document, the HTTP cache warm): Fan List rows (All scope: every Creator's first page); judged at
             ready = the rows shown and the first page's reads answered (`FIRST_PAGE`: OF's chat list per
             Creator, /admin/chats/recent, by-ids, spend-batch); settled adds useUnreadMessagesPrefetch's idle
             thread reads (seconds of them), recorded in the table and metrics, not judged
  thread     tap the first row (the opened Fan): its messages
  vault      the composer's Vault button: the picker's tiles (live OF path: /api/of/v2/vault/media, thumbs via /img)
  send       type a line, tap Send: the bubble, and OF's POST
  receive    `--users` Fans DM through `/__slop/of-ws-frame` (fan_dm.serial: per Creator one frame in flight), then
             the opened Fan: settled = its frames handed to the relay -> their bubbles on the page
Screenshots `screenshots/<profile>-<flow>-trigger.png` (the screen the user acts on; dashboard: just after the
navigation commits; receive: the open thread before the first frame) and `-settled.png`; every request per flow
(path, status, bytes, ms) in `net-<profile>.json`.

Checks: per profile x flow, ready (settled; fan-list above) <= BUDGET_MS (budget; receive: one RECEIVE_MS for every
profile, the stream is not throttled) and requests <= REQ_MAX (receive's REQ_PER_DM per DM delivered; bytes: metrics
and the table); each profile's burst has exactly `--users` Fans (else INFRA); the creators flow went by the drawer's
link; the Fan List rows == the expected first page (sum over Creators of min(25, its chats), capped at the 200 rows
drawn); the thread's bubbles == OF's thread (seeded, then earlier profiles' lines), oldest first; the picker's
tiles, scrolled to the end, == the seeded vault; every /img 200; the send side effect (OF got exactly one POST with
that text); receive: every DM in the DB (`/admin/messages`), each thread's DMs in send order, the opened Fan's DM
visible, and frame -> SSE p95 (the manager's /events listener, harness side) <= SSE_P95_MS (budget). Each profile
starts on a cold relay (`_cold_relay`), after one untimed warm-up load of `/` before the first (`_warm_up`: the Next
server's first render is not the phone's to pay); creators, thread, vault and send start once the network went
`DRAIN_MS` quiet (untimed: past the Fan List's idle prefetch and Next's link prefetch, so a flow counts only its own
requests). TARGET_MS (the post-fix aims) is recorded in the table and metrics, never checked.

Raw Playwright behind lib/wan.py's edge, not actors/ui.py's owner_browser: that context routes every request
(`route("**/*")`: Chromium's HTTP cache off, so each flow would refetch every chunk a phone keeps) and holds
/api/of/, and it opens the app's own port, not the TLS + HTTP/2 edge a deployment serves. `_cold_relay` is not
shared with dashboard-load (its two-line crash + start keeps the /img disk cache and the CDN arm; this one wipes and
re-arms both).

`--no-ui`: the browser checks SKIP; the relay half of receive runs (`--users` Fans x `per_fan`, frame -> SSE p95).
Break-it-once: net-si-budget-forced (lib/net_faults.py): si's budgets applied to every profile; only the far
profiles' budgets measured at >= 2x si's go red (the rest, and receive's one budget, are not its targets). For a wire
profile: `slop/run slow-conn --net=jp-lossy --break --fault=net-lossy-si-budget-forced` (si's budgets on jp-lossy;
targets its flows measured >= 2x si's).

Wire profiles (`--net=jp-lossy` / `--net=jp-lossy-bad`, never in the default set; the run stops at once, naming
`sudo slop/install-netloss`, without the helper; one wire run per machine, lib/net.py `wire_lock`): real TCP through
macOS dummynet on the edge's browser-facing port (lib/net.py `wired`, switched on after the profile's cold relay, off
when it ends): RTT, bandwidth and loss per packet each way, CDP emulation off. Every correctness check above runs;
budgets per flow from `WIRE_BUDGET_MS` (receive included: the /events stream rides the shaped line, so it has its
own budget per wire profile instead of RECEIVE_MS), request caps REQ_MAX (receive's per DM `REQ_PER_DM_WIRE`: loss
adds refetches). Recorded per profile x flow: request duration p50 / p95 / max (`req_ms`
metric and table; the question: do minute-long requests appear), and `net-wire-<profile>.txt` (the helper's status
and `calibrate`'s TCP connect times); check `<profile>: wire RTT calibrated` (median connect within
max(`CAL_TOL_MS`, `CAL_TOL` x RTT) of the profile's RTT). Default `--timeout_ms` 300 s for them (a 118 s request
must not hit the meter's timeout).

Bypasses, declared: the round trip and bandwidth are Chromium's CDP throttling (per request, no handshake or slow
start, no loss: lib/net.py); OnlyFans and its CDN are fakes at their wire (lib/of_wire.py, lib/img_relay.py: the
bytes are seeded noise in a 1x1 JPEG: a tile decodes one grey pixel, so a photo's decode cost is not measured); wire
profiles: loss is dummynet's per-packet coin at the loopback wire (no bypass inside service/ or the app; lo0's MTU
clamped to an MSS of 1460 on the shaped port; the edge -> app hop is unshaped); a
sent line and every injected DM join `fake.messages` and head `fake.chats` as OF's thread and chat list would; the
app is built from this checkout (no brand env); Next and the relay run unthrottled on the laptop; Fans enter at the
WS frame hook (`/__slop/of-ws-frame`), not OF's socket; Chromium, not WebKit. Service workers are blocked (CDP's
throttle does not reach a worker's own fetches, and app/public/sw-images.js fetches every /img: measured 25-45 ms
each under jp-bad), so /img rides the page's throttled line as a cold worker cache's fetches would. Receive's frame
-> bubble does not see the round trip: CDP holds only a response's headers, so events on the open /events stream
arrive unthrottled (measured ~120 ms on every profile); a real phone adds about half an RTT."""
from __future__ import annotations

import asyncio
import itertools
import json
import re
import shutil
import time
from datetime import datetime

from playwright.async_api import async_playwright

from slop.actors import fan_dm, manager
from slop.actors.ui import LAUNCH_ARGS, track
from slop.lib.img_relay import arm_run
from slop.lib.net import DEFAULT_PROFILES, HELPER, INSTALL, PROFILES, Meter, calibrate, emulate, is_wire, wired
from slop.lib.net_faults import LOSSY_SI_FORCED, SI_FORCED, budget_check
from slop.lib.wan import WanEdge
from slop.seed import agency, chat_media, fans, of_sessions, threads
from slop.seed import creators as creators_seed

UI = True
APP_MODE = "prod"
RELAY_ENV = {"VAPID_SUBJECT": "mailto:slop@example.test"}  # push on, as in prod (else GET /push/key 503)
OF_WIRE = True
FAULT = SI_FORCED
CREATORS = 13
OF_MS = 300      # a guess between the fake's 50 ms and prod's cold 0.9-1.3 s (dashboard-load's docstring)
CDN_MS = 50
PER_FAN = 2      # DMs per Fan in receive: two, so a thread's order can be wrong
FLOWS = ("dashboard", "creators", "fan-list", "thread", "vault", "send", "receive")
FANLIST_PAGE, FANLIST_RENDER = 25, 200   # useChatList PAGE_SIZE, fanListPaging ROW_RENDER_STEP
# Before creators, thread, vault and send (untimed): network quiet this long, past Next's link prefetch and the
# Fan List's unread prefetch (useUnreadMessagesPrefetch: an idle tier starts 2.5 s after the last input, then
# within a 2 s idle deadline).
DRAIN_MS = 5_000
CREATORS_PAGE = 10                        # AccountsTable's default page size
THREAD_PAGE = 30                          # useChatMessages PAGE_SIZE: the thread's first page
# The Fan List's first page (All scope): per Creator OF's chat list, its Fans' rows and spend; then the relay's
# recent-chat merge. Its rows show before the last of these lands (the spend column fills in).
FIRST_PAGE = tuple(re.compile(x) for x in (r"^/api/of/v2/chats(\?|$)", r"^/admin/chats/recent",
                                           r"^/admin/fans/\d+/by-ids", r"^/admin/fans/\d+/spend-batch"))
IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
# Ready ms per profile x flow: the small run 20261105T184058Z-...-345a (cold relay per profile; its measured ready
# in the comment; red only on the two old jp-bad budgets this replaces, every other check green) + max(30 %, 2 RTT,
# 500 ms: the laptop's load jitter, ~400 ms measured with other runs going, 20261105T164833Z-...-5937 si dashboard
# 1341 vs 951), rounded up to 50 ms. The run starts with `_warm_up`, so si's dashboard is browser-cold only (no
# server first render). Since #237 the per-Creator background queue paces the badge / roster / chart reads after the
# paint, so on a capped line settled trails the key by seconds (jp-bad dashboard: 13 x users/me, count/all,
# subscribers/chart after the figure): settled stays the judged time (key + network idle); the table's key column
# and its paced-tail note show the paint.
BUDGET_MS: dict[str, dict[str, int]] = {
    "si": {"dashboard": 1_550,        # 1002
           "creators": 1_000,         # 452
           "fan-list": 950,           # 402
           "thread": 1_200,           # 695
           "vault": 1_900,            # 1351
           "send": 950},              # 426
    "jp": {"dashboard": 2_950,        # 2246
           "creators": 1_450,         # 935
           "fan-list": 1_650,         # 1101
           "thread": 1_350,           # 834
           "vault": 1_800,            # 1285
           "send": 1_400},            # 878
    "jp-mobile": {"dashboard": 6_050, # 4651
                  "creators": 1_650,  # 1114
                  "fan-list": 2_650,  # 2033
                  "thread": 1_600,    # 1064
                  "vault": 7_900,     # 6055
                  "send": 1_450},     # 950
    "jp-bad": {"dashboard": 13_000,   # 9973
               "creators": 2_500,     # 1699
               "fan-list": 5_600,     # 4292
               "thread": 2_150,       # 1330
               "vault": 12_300,       # 9429
               "send": 2_100},        # 1280
}
# Wire profiles (lib/net.py jp-lossy, jp-lossy-bad; never in DEFAULT_PROFILES: they need the root helper). Ready ms
# per flow from two small runs each (the measured pair in the comment: jp-lossy 20261106T005802Z-...-b548 and
# 20261106T010257Z-...-aa1e, jp-lossy-bad 20261106T005956Z-...-8ff4 and 20261106T010508Z-...-06d8; host 1-min load
# 6.1-8.4 at start, the machine gate running up to 6 slots), budget = max(2 x the worse run, the worse + 3 s), rounded
# up to 500 ms. Wider than the CDP rule (30 %): loss is a per-packet coin, and the same flow measured 1.4-4.6x apart
# between two runs (jp-lossy thread 1651 vs 7629: a lost SYN or tail segment costs a retransmit timeout of 1 s and
# more); the 3 s floor is a few such timeouts on a short flow.
WIRE_BUDGET_MS: dict[str, dict[str, int]] = {
    "jp-lossy": {"dashboard": 37_500,      # 16207, 18595
                 "creators": 5_500,        # 2469, 2483
                 "fan-list": 14_500,       # 3982, 7116
                 "thread": 15_500,         # 1651, 7629
                 "vault": 38_500,          # 14171, 19196
                 "send": 4_500,            # 1138, 1137
                 "receive": 3_500},        # 305, 255
    "jp-lossy-bad": {"dashboard": 60_000,  # 29967, 23795
                     "creators": 11_000,   # 5409, 4371
                     "fan-list": 14_000,   # 6850, 5569
                     "thread": 15_000,     # 5463, 7271
                     "vault": 93_000,      # 33308, 46282
                     "send": 6_500,        # 3082, 1599
                     "receive": 8_000},    # 3807, 443
}
REQ_PER_DM_WIRE = 2.0  # receive's requests per DM under loss (measured 23-57 for 42 DMs: 0.55-1.36)
WIRE_TIMEOUT_MS = 300_000  # a flow's wait under a wire profile (the phone saw a 118 s call)
CAL_TOL_MS, CAL_TOL = 40, 0.2  # wire RTT calibrated: median TCP connect within max(40 ms, 20 % of RTT)
RECEIVE_MS = 800  # frame -> bubble, any profile (CDP leaves the open /events stream alone): 20261105T184058Z-...-345a's
# max 251 + max(30 %, 500 ms) (no RTT to add; 500 ms the load-jitter floor)
# Requests per flow at most (any profile): the small baselines' max x 1.3. Receive's per DM delivered (its
# refetches follow the DMs and where they land, so a fixed cap tracks --users and the scale; measured 27-34 for 42
# DMs at small, 40 at medium, 20261105T172951Z-...-dde2): one read per DM + 25 %.
REQ_MAX: dict[str, int] = {"dashboard": 103, "creators": 16, "fan-list": 153, "thread": 30, "vault": 73, "send": 6}
REQ_PER_DM = 1.25
PACED_GAP_MS = 2_000  # judged time this far past the key: the table note names the flow (key = the paint)
# Where each flow should land after the fixes (recorded, never checked): si as measured (the owner's "instant");
# a far profile = si + 2 RTT (one for the request, one for its data, nothing serial beyond) + its bytes at the
# line's speed (jp-mobile 1.6, jp-bad 1 Mbit/s), from the same baselines.
TARGET_MS: dict[str, dict[str, int]] = {
    "si": {"dashboard": 1_000, "creators": 500, "fan-list": 3_250, "thread": 700, "vault": 1_200, "send": 500,
           "receive": 150},
    "jp": {"dashboard": 1_500, "creators": 1_000, "fan-list": 3_750, "thread": 1_200, "vault": 1_700, "send": 1_000,
           "receive": 650},
    "jp-mobile": {"dashboard": 3_750, "creators": 1_150, "fan-list": 4_600, "thread": 1_550, "vault": 6_600,
                  "send": 1_000, "receive": 700},
    "jp-bad": {"dashboard": 5_350, "creators": 1_550, "fan-list": 5_400, "thread": 1_850, "vault": 9_800,
               "send": 1_300, "receive": 1_050},
}
SSE_P95_MS = 500   # frame handed to the relay -> on the manager's /events (inbox-unread's E2E budget)
SSE_CHECK = "receive: frame -> /events p95 within budget"

C_ROWS = "fan-list: rows == the expected first page (every Creator's first 25, at most 200 drawn)"
C_CREATORS = "creators: the table's first page has a row per Creator (at most 10)"
C_CREATORS_LINK = "creators: reached by the drawer's link (client-side), not the URL"
C_RECEIVE = "receive: frame -> the opened Fan's bubbles within budget, every profile"
C_ORDER = "thread: the bubbles are OF's thread (seeded, then earlier profiles' lines), oldest first"
C_VAULT = "vault: the picker's tiles, scrolled to the end, == the seeded vault"
C_IMG = "every /img the page fetched answered 200"
C_SEND = "send: OF got exactly one POST with the typed text, and its bubble shows"
C_DB = "receive: every DM sent is in its thread (/admin/messages)"
C_THREAD_ORDER = "receive: each thread's DMs in send order"
C_VISIBLE = "receive: the opened Fan's DM shows in the open thread"
C_SSE_ALL = "receive: every DM reached the manager's /events"
C_NO_5XX = "no request the page sent was answered 5xx"
UI_CHECKS = (C_ROWS, C_CREATORS, C_CREATORS_LINK, C_ORDER, C_VAULT, C_IMG, C_SEND, C_VISIBLE, C_RECEIVE)

ROWS_JS = "() => [...document.querySelectorAll('table tbody tr')].filter(r => r.cells.length > 1).length"
SEEN_JS = r"""() => { if (window.__seen) return; window.__seen = {};
  const mark = () => { for (const e of document.querySelectorAll('[data-msg-id]'))
    if (!(e.dataset.msgId in window.__seen)) window.__seen[e.dataset.msgId] = Date.now(); };
  mark(); new MutationObserver(mark).observe(document.body, {childList: true, subtree: true}); }"""


def _iso(db_ts: str) -> str:
    return datetime.strptime(db_ts[:19], "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _of_world(w, cs, opened: tuple[str, int]) -> tuple[dict, dict, dict]:
    """OF's chat list and threads from the seeded rows (newest first); the opened Fan heads its Creator's list,
    newest of all. Returns chats, messages, and the opened thread's seeded ids oldest first."""
    con = w.sql()
    rows = con.execute("SELECT account_id, fan_id, message_id, direction, body, created_at FROM messages "
                       "ORDER BY account_id, fan_id, created_at DESC, message_id DESC").fetchall()
    media = con.execute("SELECT account_id, fan_id, message_id, media_id, thumb_url, source_url FROM message_media "
                        "ORDER BY media_id").fetchall()
    unread = dict(((a, f), u) for a, f, u in con.execute("SELECT account_id, fan_id, unread_count FROM chats"))
    con.close()
    by_msg: dict[tuple, list[dict]] = {}
    for a, f, mid, med, th, src in media:
        by_msg.setdefault((a, f, mid), []).append({
            "id": med, "type": "photo", "canView": True, "isReady": True, "hasError": False,
            "files": {"thumb": {"url": th}, "source": {"url": src, "width": 960, "height": 1280},
                      "full": {"url": src, "width": 960, "height": 1280}}})
    msgs: dict[str, dict[int, list[dict]]] = {c["id"]: {} for c in cs}
    for a, f, mid, d, body, at in rows:
        m = by_msg.get((a, f, mid), [])
        msgs[a].setdefault(f, []).append({
            "id": mid, "text": body or "", "createdAt": _iso(at), "fromUser": {"id": f if d == "in" else int(a)},
            "isFree": True, "price": 0, "mediaCount": len(m), "media": m, "lockedText": False, "isOpened": True})
    chats = {}
    for a, by_fan in msgs.items():
        items = [{"withUser": {"id": f, "_view": "s"}, "unreadMessagesCount": unread.get((a, f), 0),
                  "lastMessage": {k: t[0][k] for k in ("id", "text", "fromUser", "isFree", "price", "createdAt")}}
                 for f, t in by_fan.items()]
        items.sort(key=lambda c: (c["withUser"]["id"] == opened[1] and a == opened[0], c["lastMessage"]["createdAt"]),
                   reverse=True)
        chats[a] = items
    head = chats[opened[0]][0]
    head["lastMessage"] = {**head["lastMessage"], "createdAt": w.now.strftime("%Y-%m-%dT%H:%M:%S+00:00")}
    seeded = [m["id"] for m in reversed(msgs[opened[0]][opened[1]])]
    return chats, msgs, seeded


def _vault(w, n: int) -> tuple[list[dict], dict]:
    """The picker Creator's OF vault page (newest first) and its thumbs as CDN assets."""
    rng, exp = w.rng("slow-conn:vault"), int(w.now.timestamp()) + 6 * 3600
    items, assets = [], {}
    for i in range(n):
        host = chat_media.SIGNED_HOSTS[i % 2]
        path = f"/files/v/{i:04d}/vault_{950_000_000 + i}_300x300.jpg"
        url = chat_media.sign(host, path, exp)
        assets[f"{host}{path}"] = {"host": host, "path": path, "size": rng.randint(*chat_media.THUMB), "url": url}
        f = {"url": url, "width": 300, "height": 300}
        items.append({"id": 950_000_000 + n - i, "type": "photo", "isReady": True, "canView": True, "hasError": False,
                      "createdAt": w.now.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                      "files": {"thumb": f, "preview": f, "squarePreview": f, "full": f}})
    return items, assets


def req_check(p: str, f: str) -> str:
    return f"{p}: {f} requests within cap"


def _budget(p: str, f: str) -> int | None:
    if is_wire(p):
        return WIRE_BUDGET_MS[p].get(f)
    return BUDGET_MS[p].get(f, RECEIVE_MS)


def cal_check(p: str) -> str:
    return f"{p}: wire RTT calibrated"


WIRE_SKIP = "wire profile: receive judged per wire profile (its budget check), not by RECEIVE_MS"


def _req_ms(r: dict) -> dict:
    """One flow's request durations (the SSE stream and the beacon aside): n, p50 / p95 / max ms, the slowest's path,
    how many over 10 s and 60 s, unfinished, and failed (not the page's own ERR_ABORTED)."""
    qs = [q for q in r.get("reqs", []) if q["kind"] not in ("sse", "beacon")]
    done = sorted((q["ms"], q["path"]) for q in qs if q["ms"] is not None)
    ms = [m for m, _ in done]
    return {"n": len(qs), "p50": _p(ms, 0.5), "p95": _p(ms, 0.95), "max": ms[-1] if ms else None,
            "max_path": done[-1][1][:120] if done else None, "over_10s": sum(m > 10_000 for m in ms),
            "over_60s": sum(m > 60_000 for m in ms), "unfinished": len(qs) - len(done),
            "failed": sum(1 for q in qs if q.get("failed") and q["failed"] != "net::ERR_ABORTED")}


_IDS = itertools.count(fan_dm.INJECT_ID_BASE)  # one count for every burst of the run: no id twice


def _p(xs: list[float], q: float) -> float | None:
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(q * len(s)))], 1) if s else None


async def _burst(ctx, targets: list[dict], opened_fan: dict | None) -> dict:
    """`targets` DM `PER_FAN` each through the WS frame hook, then the opened Fan alone (so it is the newest chat
    again, heading the next profile's Fan List); OF's thread gets each DM too."""
    fake, tracked = ctx.of_wire, {}

    def make(mid, f, k):
        fr = fan_dm.frame(mid, f, f"slop net dm {k + 1}/{PER_FAN}")
        with fake.lock:
            fake.messages.setdefault(f["account_id"], {}).setdefault(f["id"], []).insert(0, fr["api2_chat_message"])
            fake.head_chat(f["account_id"], f["id"], fr["api2_chat_message"])
        if opened_fan and f["id"] == opened_fan["id"] and f["account_id"] == opened_fan["account_id"]:
            tracked[k] = mid
        return fr

    sse = manager.SseListener(ctx.owner.share())
    await sse.start()
    pool = ctx.owner.share(limits=max(10, len({t["account_id"] for t in targets})))
    recs = await fan_dm.serial(pool, targets, PER_FAN, ids=_IDS, make=make)
    if opened_fan:
        await asyncio.sleep(1.1)  # its DMs a clock second after every other: newest by any stamp
        recs += await fan_dm.serial(pool, [opened_fan], PER_FAN, ids=_IDS, make=make)
    stats = await manager.quiesce(ctx.owner)
    await asyncio.sleep(1.0)  # the SSE tail
    await sse.stop()
    await pool.aclose()
    sent = [r for r in recs if r["status"] < 300]
    e2e = [sse.received_at[r["message_id"]] - r["t0"] for r in sent if r["message_id"] in sse.received_at]
    return {"recs": recs, "sent": sent, "e2e": e2e, "missing_sse": len({r["message_id"] for r in sent}
                                                                       - set(sse.message_ids)),
            "stats": stats, "tracked": tracked}


async def _db_checks(ctx, sent: list[dict]) -> tuple[int, int]:
    """(DMs missing from their thread, threads out of send order), from /admin/messages."""
    by: dict[tuple, list[int]] = {}
    for r in sorted(sent, key=lambda r: r["t0"]):
        by.setdefault((r["account_id"], r["fan_id"]), []).append(r["message_id"])
    missing = disorder = 0
    for (a, f), ids in by.items():
        rows = await manager.thread_messages(ctx.owner, a, f)
        if len(rows) > 1 and str(rows[0].get("created_at")) > str(rows[-1].get("created_at")):
            rows = rows[::-1]
        got = [int(m["message_id"]) for m in rows if int(m["message_id"]) in set(ids)]
        missing += len(set(ids) - set(got))
        disorder += got != [i for i in ids if i in set(got)]
    return missing, disorder


async def _drawer(page, group: str) -> str | None:
    """Untimed: the phone's nav drawer open (TopBar's Toggle sidebar) and `group` expanded, its links on screen.
    Returns None, or why not (then _nav falls back to the URL and C_CREATORS_LINK fails with this reason)."""
    try:
        await page.get_by_role("button", name="Toggle sidebar").first.tap(timeout=10_000)
        await page.get_by_role("button", name=group, exact=True).first.tap(timeout=10_000)
        await page.wait_for_timeout(400)
    except Exception as e:  # noqa: BLE001  reported, judged by C_CREATORS_LINK
        return f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
    return None


async def _nav(page, href: str) -> str:
    """Tap the app's own nav link (client-side navigation, as a phone user does); the URL if there is none."""
    a = page.locator(f"a[href='{href}']:visible").first
    if await a.count():
        await a.tap()
        return "link"
    await page.goto(page.url.split("/", 3)[0] + "//" + page.url.split("/", 3)[2] + href, wait_until="commit",
                    timeout=120_000)
    return "url"


async def _cold_relay(ctx, assets: dict) -> dict:
    """Every profile meets the same relay: SIGKILL (its in-memory OF caches gone), its /img disk cache (the harness's
    temp dir, lib/img_relay.py) wiped, started again on the same DB and port, the CDN fake re-armed, and its frames
    quiesced, all untimed."""
    t0 = time.time()
    await asyncio.to_thread(ctx.stack.crash_relay)
    shutil.rmtree(ctx.stack.shard_svc[0] / "img-cache", ignore_errors=True)
    await asyncio.to_thread(ctx.stack.start_relay)
    armed = await arm_run(ctx.owner, ctx.stack.tmp, assets, ctx.param("cdn_ms", CDN_MS) / 1000)
    await manager.quiesce(ctx.owner)
    return {"restart_s": round(time.time() - t0, 1), "img_arm": armed}


async def _warm_up(ctx, browser, edge, timeout_ms: int) -> dict:
    """Untimed, once before the first profile: a throwaway context loads `/` through the edge until Total earnings'
    figure shows, so the Next server's first render (its server chunks loaded on the first request) lands here, not
    in si's dashboard: a phone never pays the server's cold start. The relay still starts cold per profile."""
    t0 = time.time()
    bctx = await browser.new_context(service_workers="block")
    track(ctx, bctx)
    try:
        await bctx.add_cookies([{"name": c.name, "value": c.value, "url": edge.url, "expires": time.time() + 86400}
                                for c in ctx.owner.c.cookies.jar])
        page = await bctx.new_page()
        await page.goto(edge.url + "/", wait_until="commit", timeout=timeout_ms)
        await page.locator('[data-control="total"] [data-figure]').first.wait_for(timeout=timeout_ms)
    finally:
        await bctx.close()
    return {"warm_up_s": round(time.time() - t0, 1)}


async def _profile(ctx, browser, edge, prof: str, plan: dict) -> dict:
    """One profile's flows on a fresh context; answers per flow the meter's verdict, its requests and findings."""
    shots = ctx.out / "screenshots"
    # Service workers blocked: CDP's throttle is the page's, and sw-images.js fetches every /img itself (measured
    # 25-45 ms each under jp-bad's 400 ms, 20261105T145426Z-...-b98f).
    bctx = await browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True,
                                     has_touch=True, user_agent=IPHONE_UA, service_workers="block")
    track(ctx, bctx)  # the pages for slop/map.json (--changed), as dashboard-load's own contexts
    await bctx.add_cookies([{"name": c.name, "value": c.value, "url": edge.url, "expires": time.time() + 86400}
                            for c in ctx.owner.c.cookies.jar])
    out: dict = {"flows": {}, "found": {}, "relay": plan["relay"]}
    try:
        page = await bctx.new_page()
        cdp = await bctx.new_cdp_session(page)
        out["conditions"] = await emulate(cdp, prof)
        meter = Meter(cdp)

        async def flow(name: str, act, key: str, *, shot_before: bool = True, idle_ms: int = 1500,
                       drain: bool = False, first_page: tuple = ()) -> dict:
            if drain:  # untimed: earlier prefetches (Next's links, the Fan List's threads) run out, so the flow
                # counts only its own requests
                meter.mark()
                d = await meter.settled(page, "body", idle_ms=DRAIN_MS, timeout_ms=plan["timeout_ms"])
                drained = d["requests"]
            if shot_before:
                await page.screenshot(path=str(shots / f"{prof}-{name}-trigger.png"))
            meter.mark()
            how = await act()
            if not shot_before:
                await page.screenshot(path=str(shots / f"{prof}-{name}-trigger.png"))
            r = await meter.settled(page, key, idle_ms=idle_ms, timeout_ms=plan["timeout_ms"])
            await page.screenshot(path=str(shots / f"{prof}-{name}-settled.png"))
            r["how"] = how
            r["ready_ms"] = r["settled_ms"]
            if first_page:  # ready: the key shown and the first page's reads answered (the prefetch tail aside)
                fp = [q for q in meter.window() if any(rx.match(q["path"]) for rx in first_page)]
                done = fp and r["key_ms"] is not None and all(q["end"] is not None for q in fp)
                r["ready_ms"] = max(r["key_ms"], *(q["end"] for q in fp)) if done else None
                r["first_page_requests"] = len(fp)
            if drain:
                r["drained_requests"] = drained
            r["reqs"] = [{"path": q["path"][:300], "method": q["method"], "kind": q["kind"], "status": q["status"],
                          "bytes": q["bytes"], "start": q["start"],
                          "ms": None if q["end"] is None else q["end"] - q["start"],
                          "cached": q["cached"], "failed": q["failed"]} for q in meter.window()]
            out["flows"][name] = r
            return r

        async def goto():
            await page.goto(edge.url + "/", wait_until="commit", timeout=plan["timeout_ms"])
            return "typed"
        await flow("dashboard", goto, '[data-control="total"] [data-figure]', shot_before=False)
        n_rows = min(CREATORS_PAGE, len(plan["creators"]))
        out["found"]["drawer_error"] = await _drawer(page, "Creators")
        await flow("creators", lambda: _nav(page, "/creators"), f"() => ({ROWS_JS})() >= {n_rows}", drain=True)
        out["found"]["creator_rows"] = await page.evaluate(ROWS_JS)
        async def mp():  # nav.ts opens Messages Pro as its own window (a phone: a tab): a new document, cache warm
            await page.goto(edge.url + "/messages-pro", wait_until="commit", timeout=plan["timeout_ms"])
            return "new-tab"
        await flow("fan-list", mp, "[data-chat-row]", first_page=FIRST_PAGE)
        out["found"]["fan_rows"] = await page.locator("[data-chat-row]").count()

        with ctx.of_wire.lock:  # OF's thread now: the seeded rows, then what earlier profiles sent and received
            out["found"]["thread_want"] = [m["id"] for m in reversed(
                ctx.of_wire.messages[plan["opened"]["account_id"]][plan["opened"]["id"]])][-THREAD_PAGE:]

        async def tap_row():  # the opened Fan heads the list: its chat is the newest (seeded so, then _burst)
            await page.locator("[data-chat-row]").first.tap()
            return "tap"
        await flow("thread", tap_row, "[data-msg-id]", drain=True)
        out["found"]["thread_url"] = page.url
        out["found"]["thread_ids"] = [int(x) for x in await page.evaluate(
            "() => [...document.querySelectorAll('[data-msg-id]')].map(e => e.dataset.msgId)") if x.isdigit()]

        async def vault():
            await page.locator("[data-composer-area]").get_by_role("button", name="Vault", exact=True).click()
            return "tap"
        await flow("vault", vault, "[role=dialog] [data-tile-id]", drain=True)
        dlg = page.get_by_role("dialog", name="Vault picker")

        async def close_vault():
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)
            if await dlg.count():
                await page.keyboard.press("Escape")
        await close_vault()

        text = f"slop net {prof} {ctx.seed}"
        box = page.locator("[data-composer-area] textarea")
        await box.fill(text)
        before = len(ctx.of_wire.sends.get(plan["opened"]["account_id"], []))

        async def send():
            await page.locator("[data-composer-area]").get_by_role("button", name="Send", exact=True).click()
            return "tap"
        await flow("send", send, f"() => [...document.querySelectorAll('[data-msg-id]')].some(e => "
                                 f"e.textContent.includes({json.dumps(text)}))", drain=True)
        with ctx.of_wire.lock:
            got = [s for s in ctx.of_wire.sends.get(plan["opened"]["account_id"], [])[before:]]
        out["found"]["send"] = {"text": text, "posts": [{"fan": s["fan_id"], "text": s["text"]} for s in got]}

        await page.evaluate(SEEN_JS)
        await page.screenshot(path=str(shots / f"{prof}-receive-trigger.png"))  # the open thread, before any frame
        meter.mark()
        b = await _burst(ctx, plan["chunks"][prof], plan["opened"])
        mids = list(b["tracked"].values())
        try:
            await page.wait_for_function("ids => ids.every(i => window.__seen[String(i)])", arg=mids,
                                         timeout=plan["timeout_ms"])
        except Exception:  # noqa: BLE001  judged below
            pass
        seen = await page.evaluate("ids => ids.map(i => window.__seen[String(i)] || null)", mids)
        t0 = {r["message_id"]: r["t0"] for r in b["recs"]}
        vis = [s - t0[m] for m, s in zip(mids, seen, strict=True) if s is not None]
        r = await meter.settled(page, "[data-msg-id]", timeout_ms=30_000)
        await page.screenshot(path=str(shots / f"{prof}-receive-settled.png"))
        settled = round(max(vis)) if vis and len(vis) == len(mids) else None
        r.update(settled_ms=settled, ready_ms=settled, how="ws-frame", key_ms=round(min(vis)) if vis else None,
                 reqs=[{"path": q["path"][:300], "kind": q["kind"], "status": q["status"], "bytes": q["bytes"],
                        "start": q["start"], "ms": None if q["end"] is None else q["end"] - q["start"],
                        "failed": q["failed"]} for q in meter.window()])
        out["flows"]["receive"] = r
        out["burst"] = b

        # The picker scrolled to the end, untimed and last: on jp-bad it takes long enough (medium: 200 tiles at
        # 1 Mbit/s) that the timed flows after it would meet useChatList's 90 s poll (measured: 13 head reads in
        # receive, 20261105T160900Z-...-710f). A step waits for the network's quiet: the next page queues behind tiles.
        await vault()
        await dlg.locator("[data-tile-id]").first.wait_for(timeout=plan["timeout_ms"])
        last = -1
        for _ in range(60):
            n = await dlg.locator("[data-tile-id]").count()
            if n in (0, last):
                break
            last = n
            meter.mark()
            await dlg.locator("[data-tile-id]").last.scroll_into_view_if_needed(timeout=30_000)
            await meter.settled(page, "body", timeout_ms=plan["timeout_ms"])
        out["found"]["vault_tiles"] = await dlg.locator("[data-tile-id]").count()
        await close_vault()
    finally:
        await bctx.close()
    return out


async def run(ctx) -> None:  # noqa: C901  one flow, its checks in order
    w = ctx.world
    await agency.seed(w)
    cs = creators_seed.seed(w, ctx.param("creators", CREATORS))
    by_creator = fans.seed(w, cs)
    threads.seed(w, by_creator)
    of_sessions.seed(w, cs)
    data = chat_media.seed(w, ctx.param("chat_assets", w.size["slow_conn_chat_assets"]))
    pick = next(c for c in data["chats"] if not c["stale"])
    opened = {"account_id": pick["account_id"], "id": pick["fan_id"]}
    fan_by_id = {f["id"]: f for f in by_creator[pick["account_id"]]}
    opened.update(username=fan_by_id[pick["fan_id"]]["username"], name=fan_by_id[pick["fan_id"]]["name"])
    fake = ctx.of_wire
    fake.latency_s = ctx.param("of_ms", OF_MS) / 1000
    chats, msgs, seeded = _of_world(w, cs, (pick["account_id"], pick["fan_id"]))
    fake.chats.update(chats)
    fake.messages.update(msgs)
    n_vault = ctx.param("vault_media", w.size["slow_conn_vault_media"])
    fake.vault_media[pick["account_id"]], vault_assets = _vault(w, n_vault)
    assets = {**data["assets"], **vault_assets}  # armed per profile by _cold_relay (--no-ui fetches no /img)
    profiles = [ctx.net] if ctx.net else list(DEFAULT_PROFILES)
    want_rows = min(FANLIST_RENDER, sum(min(FANLIST_PAGE, len(chats[c["id"]])) for c in cs))
    ctx.metric("world", {"creators": len(cs), "fans": sum(len(v) for v in by_creator.values()),
                         "chats": {c["id"]: len(chats[c["id"]]) for c in cs}, "opened": opened,
                         "opened_thread": len(seeded), "vault_media": n_vault,
                         "cdn_assets": len(data["assets"]) + n_vault,
                         "of_ms": round(fake.latency_s * 1000), "profiles": profiles,
                         "want_fan_rows": want_rows})

    # Receive's Fans: per profile its own `--users` (distinct across profiles, the opened Fan apart; --no-ui: one
    # burst), shuffled over the Creators; the opened Fan last. Fewer seeded Fans than that is the harness's fault.
    rng = w.rng("slow-conn:receive")
    pool = [dict(f, account_id=c["id"]) for c in cs for f in by_creator[c["id"]] if f["id"] != opened["id"]]
    rng.shuffle(pool)
    bursts = profiles if ctx.ui else profiles[:1]
    chunks = {p: pool[i * ctx.users:(i + 1) * ctx.users] for i, p in enumerate(bursts)}
    if ctx.users < 1 or any(len(v) != ctx.users for v in chunks.values()):
        raise RuntimeError(f"receive: {len(pool)} Fans seeded, {len(bursts)} bursts x --users={ctx.users} wanted")

    if not ctx.ui:
        b = await _burst(ctx, chunks[profiles[0]], None)
        missing, disorder = await _db_checks(ctx, b["sent"])
        ctx.metric("receive", {"sent": len(b["sent"]), "frame_to_sse_p50": _p(b["e2e"], 0.5),
                               "frame_to_sse_p95": _p(b["e2e"], 0.95), "relay": b["stats"]})
        ctx.check(C_DB, len(b["sent"]) == len(b["recs"]) and missing == 0, sent=len(b["sent"]),
                  recs=len(b["recs"]), missing=missing)
        ctx.check(C_THREAD_ORDER, disorder == 0, threads_out_of_order=disorder)
        ctx.check(C_SSE_ALL, b["missing_sse"] == 0, missing=b["missing_sse"])
        p95 = _p(b["e2e"], 0.95)
        ctx.check(SSE_CHECK, p95 is not None and p95 <= SSE_P95_MS, budget=True, p95=p95, n=len(b["e2e"]))
        for c in UI_CHECKS:
            ctx.skip(c, "--no-ui: no browser")
        for p in PROFILES:
            for f in FLOWS:
                if f in BUDGET_MS.get(p, {}) or is_wire(p):
                    ctx.skip(budget_check(p, f), "--no-ui: no browser")
                ctx.skip(req_check(p, f), "--no-ui: no browser")
            if is_wire(p):
                ctx.skip(cal_check(p), "--no-ui: no browser")
        ctx.skip(C_NO_5XX, "--no-ui: no browser")
        return

    plan = {"creators": cs, "opened": opened, "chunks": chunks,
            "timeout_ms": ctx.param("timeout_ms", WIRE_TIMEOUT_MS if any(map(is_wire, profiles)) else 120_000)}
    edge = await asyncio.to_thread(WanEdge, ctx.stack, 0)
    res: dict[str, dict] = {}
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(args=[*LAUNCH_ARGS, *edge.chrome_args])
            try:
                ctx.metric("warm_up", await _warm_up(ctx, browser, edge, plan["timeout_ms"]))
                for p in profiles:
                    plan["relay"] = await _cold_relay(ctx, assets)
                    if not is_wire(p):
                        res[p] = await _profile(ctx, browser, edge, p, plan)
                    else:  # dummynet on the port the browser dials (the edge's), only for this profile's flows
                        with wired(p, [edge.wan.port]) as status:
                            cal = await calibrate(edge.wan.port)
                            (ctx.out / f"net-wire-{p}.txt").write_text(
                                f"{status}\ncalibrate (TCP connect ms, one RTT each): {json.dumps(cal)}\n")
                            res[p] = await _profile(ctx, browser, edge, p, plan)
                        res[p]["wire"] = {"status": status, "calibrate": cal}
                        ctx.metric(f"net_wire_{p}", {"profile": PROFILES[p], "status": status, "calibrate": cal})
                    burst = res[p].pop("burst")
                    res[p]["burst"] = {k: burst[k] for k in ("sent", "e2e", "missing_sse", "stats", "tracked")}
                    (ctx.out / f"net-{p}.json").write_text(json.dumps(res[p], indent=1, default=str))
            finally:
                await browser.close()
    finally:
        edge.close()

    # The table: profile x flow, ready (judged) / settled / key / requests / KB, budget and target.
    rows = []
    for p in profiles:
        for f in FLOWS:
            r = res[p]["flows"].get(f, {})
            rows.append(f"{p:10} {f:10} {str(r.get('ready_ms')):>7} {str(r.get('settled_ms')):>8} "
                        f"{str(r.get('key_ms')):>6} {str(r.get('requests')):>5} "
                        f"{round((r.get('bytes') or 0) / 1024, 1):>7} {str(_budget(p, f) or '-'):>7} "
                        f"{str(TARGET_MS.get(p, {}).get(f) or '-'):>7}  "
                        f"{r.get('how')}")
    ctx.note("ms from the trigger: key = the key shown, settled = it + the network 1.5 s quiet, ready = what the "
             "budget judges (settled; fan-list: the rows + the first page's reads, its prefetch tail aside; receive: "
             "frame -> bubble, key the first DM's, ready = settled the last's), KB on the wire:",
             f"{'profile':10} {'flow':10} {'ready':>7} {'settled':>8} {'key':>6} {'reqs':>5} {'KB':>7} "
             f"{'budget':>7} {'target':>7}",
             *rows)
    # Where settled trails the paint by seconds (jp-bad dashboard: #237's per-Creator background queue paces the
    # badge / roster reads after the figure shows), the paint time a fix thread wants is the key column; named here.
    paced = [f"{p} {f}: key {r['key_ms']} ms, judged {r['ready_ms']} ms (reads after the paint: net-{p}.json)"
             for p in profiles for f, r in res[p]["flows"].items() if f in BUDGET_MS.get(p, {})
             and r.get("key_ms") is not None and r.get("ready_ms") is not None
             and r["ready_ms"] - r["key_ms"] > PACED_GAP_MS]
    if paced:
        ctx.note(f"judged (ready) > key + {PACED_GAP_MS} ms (the budget judges the key + network idle):", *paced)
    ctx.metric("flows", {p: {f: {k: res[p]["flows"].get(f, {}).get(k) for k in
                                 ("ready_ms", "settled_ms", "key_ms", "requests", "bytes", "by_kind", "pending",
                                  "how")}
                             for f in FLOWS} for p in profiles})
    ctx.metric("target_ms", TARGET_MS)
    # Request durations per profile x flow (every profile; the wire profiles' question: minute-long requests?).
    req_ms = {p: {f: _req_ms(res[p]["flows"].get(f, {})) for f in FLOWS} for p in profiles}
    ctx.metric("req_ms", req_ms)
    ctx.note("request ms per flow (SSE and beacon aside): n p50 p95 max  >10s >60s unfinished failed  slowest",
             *(f"{p:12} {f:10} {d['n']:>4} {str(d['p50']):>7} {str(d['p95']):>7} {str(d['max']):>7}  "
               f"{d['over_10s']:>3} {d['over_60s']:>3} {d['unfinished']:>3} {d['failed']:>3}  {d['max_path']}"
               for p, by in req_ms.items() for f, d in by.items()))

    # Correctness, per profile.
    bad_rows = {p: res[p]["found"].get("fan_rows") for p in profiles if res[p]["found"].get("fan_rows") != want_rows}
    ctx.check(C_ROWS, not bad_rows, want=want_rows, got=bad_rows)
    bad_cr = {p: res[p]["found"].get("creator_rows") for p in profiles
              if res[p]["found"].get("creator_rows") != min(CREATORS_PAGE, len(cs))}
    ctx.check(C_CREATORS, not bad_cr, want=min(CREATORS_PAGE, len(cs)), got=bad_cr)
    ctx.check(C_CREATORS_LINK, all(res[p]["flows"]["creators"].get("how") == "link" for p in profiles),
              how={p: res[p]["flows"]["creators"].get("how") for p in profiles},
              drawer_error={p: res[p]["found"].get("drawer_error") for p in profiles})
    bad_order = {p: {"want": res[p]["found"]["thread_want"], "got": res[p]["found"].get("thread_ids")}
                 for p in profiles if res[p]["found"].get("thread_ids") != res[p]["found"]["thread_want"]}
    ctx.check(C_ORDER, not bad_order, wrong=bad_order, urls={p: res[p]["found"].get("thread_url") for p in profiles})
    bad_v = {p: res[p]["found"].get("vault_tiles") for p in profiles if res[p]["found"].get("vault_tiles") != n_vault}
    ctx.check(C_VAULT, not bad_v, want=n_vault, got=bad_v)
    # A tile the page itself cancelled (MediaTile aborts on unmount: ERR_ABORTED, no answer) is not an answer.
    imgs = [(p, f, q["status"], q["failed"]) for p in profiles for f, r in res[p]["flows"].items()
            for q in r.get("reqs", []) if q["kind"] == "img" and q["path"].startswith("/img")]
    answered = [x for x in imgs if x[3] != "net::ERR_ABORTED"]
    bad_img = [x for x in answered if x[2] != 200]
    ctx.check(C_IMG, bool(answered) and not bad_img, n=len(answered), cancelled=len(imgs) - len(answered),
              bad=bad_img[:10])
    bad_send = {p: res[p]["found"]["send"] for p in profiles
                if [re.sub(r"<[^>]+>", "", x["text"]) for x in res[p]["found"]["send"]["posts"]]
                != [res[p]["found"]["send"]["text"]]
                or res[p]["flows"]["send"].get("key_ms") is None}
    ctx.check(C_SEND, not bad_send, wrong=bad_send)
    five = [(p, f, q["status"], q["path"][:120]) for p in profiles for f, r in res[p]["flows"].items()
            for q in r.get("reqs", []) if (q["status"] or 0) >= 500]
    ctx.check(C_NO_5XX, not five, n=len(five), bad=five[:10])

    sent = [r for p in profiles for r in res[p]["burst"]["sent"]]
    recs_n = (ctx.users + 1) * PER_FAN * len(profiles)  # + the opened Fan, after each burst
    missing, disorder = await _db_checks(ctx, sent)
    ctx.check(C_DB, len(sent) == recs_n and missing == 0, sent=len(sent), want=recs_n, missing=missing)
    ctx.check(C_THREAD_ORDER, disorder == 0, threads_out_of_order=disorder)
    ctx.check(C_SSE_ALL, all(res[p]["burst"]["missing_sse"] == 0 for p in profiles),
              missing={p: res[p]["burst"]["missing_sse"] for p in profiles})
    ctx.check(C_VISIBLE, all(res[p]["flows"]["receive"].get("settled_ms") is not None for p in profiles),
              frame_to_visible={p: res[p]["flows"]["receive"].get("settled_ms") for p in profiles})
    e2e = [x for p in profiles for x in res[p]["burst"]["e2e"]]
    p95 = _p(e2e, 0.95)
    ctx.check(SSE_CHECK, p95 is not None and p95 <= SSE_P95_MS, budget=True, p95=p95, limit_ms=SSE_P95_MS,
              n=len(e2e))
    rcv = {p: res[p]["flows"]["receive"].get("ready_ms") for p in profiles if not is_wire(p)}
    if rcv:  # a wire profile's /events rides the shaped line: its own receive budget (below), not RECEIVE_MS
        ctx.check(C_RECEIVE, all(v is not None and v <= RECEIVE_MS for v in rcv.values()), budget=True,
                  ready_ms=rcv, limit_ms=RECEIVE_MS)
    else:
        ctx.skip(C_RECEIVE, WIRE_SKIP)

    # Budgets: ready per profile x flow (the fault: si's, everywhere), requests per flow.
    forced = ctx.fault == SI_FORCED
    lossy_forced = ctx.fault == LOSSY_SI_FORCED
    for p in PROFILES:
        if is_wire(p):  # budgets (WIRE_BUDGET_MS, receive included), request caps, the calibration
            if p not in res:
                not_run = f"wire profile: run alone with --net={p}" + (
                    "" if HELPER.exists() else f" (helper not installed: {INSTALL})")
                for f in FLOWS:
                    ctx.skip(budget_check(p, f), not_run)
                    ctx.skip(req_check(p, f), not_run)
                ctx.skip(cal_check(p), not_run)
                continue
            for f in FLOWS:
                r = res[p]["flows"].get(f, {})
                lim = _budget("si", f) if lossy_forced else WIRE_BUDGET_MS[p][f]
                v = r.get("ready_ms")
                ctx.check(budget_check(p, f), v is not None and v <= lim, budget=True, key_ms=r.get("key_ms"),
                          ready_ms=v, limit_ms=lim, settled_ms=r.get("settled_ms"), pending=r.get("pending"),
                          req_max_ms=req_ms[p][f]["max"])
                cap = int(REQ_PER_DM_WIRE * len(res[p]["burst"]["sent"])) if f == "receive" else REQ_MAX[f]
                ctx.check(req_check(p, f), (r.get("requests") or 0) <= cap, requests=r.get("requests"), limit=cap,
                          by_kind=r.get("by_kind"))
            cal, rtt = res[p]["wire"]["calibrate"], PROFILES[p]["rtt_ms"]
            tol = max(CAL_TOL_MS, CAL_TOL * rtt)
            ctx.check(cal_check(p), cal["median_ms"] is not None and abs(cal["median_ms"] - rtt) <= tol,
                      median_ms=cal["median_ms"], rtt_ms=rtt, tolerance_ms=tol, failed=cal["failed"])
            continue
        for f in FLOWS:
            if p not in res:
                if f in BUDGET_MS[p]:
                    ctx.skip(budget_check(p, f), f"--net={ctx.net}: profile not run")
                ctx.skip(req_check(p, f), f"--net={ctx.net}: profile not run")
                continue
            r = res[p]["flows"].get(f, {})
            if f in BUDGET_MS[p]:
                lim = BUDGET_MS["si"][f] if forced else BUDGET_MS[p][f]
                v = r.get("ready_ms")
                ctx.check(budget_check(p, f), v is not None and v <= lim, budget=True, key_ms=r.get("key_ms"),
                          ready_ms=v, limit_ms=lim, settled_ms=r.get("settled_ms"), pending=r.get("pending"))
            cap = int(REQ_PER_DM * len(res[p]["burst"]["sent"])) if f == "receive" else REQ_MAX[f]
            ctx.check(req_check(p, f), (r.get("requests") or 0) <= cap, requests=r.get("requests"), limit=cap,
                      by_kind=r.get("by_kind"))
