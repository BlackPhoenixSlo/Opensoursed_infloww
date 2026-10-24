"""Lay a `dataset.Dataset` into the throwaway relay started by run.sh.

Bulk rows (accounts, fans, sales, messages, shifts, clock events, scripts, posts,
links, S4S) go straight into the temp SQLite file; the relay's own triggers keep
the sales rollups and the per-sale Employee credit up to date. Settings that the
relay validates (roles, time tracking) and the Employee mirrors of the chatter
logins go through its API as the signed-in owner. The account registry is the
temp `sessions/accounts/` dir that relay_guarded.py redirected; nothing outside
the run's temp dir is written.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dataset import SLOTS, STUDIO, Dataset, iso, ts


def _uid(*parts: Any) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:32]


class Api:
    """Thin JSON client over a Playwright APIRequestContext signed in as the owner."""

    def __init__(self, request, base: str):
        self.r, self.base = request, base

    def _do(self, method: str, path: str, body: Any = None) -> Any:
        res = self.r.fetch(self.base + path, method=method,
                           data=json.dumps(body) if body is not None else None,
                           headers={"content-type": "application/json"} if body is not None else None)
        if not res.ok:
            raise RuntimeError(f"{method} {path} -> {res.status} {res.text()[:300]}")
        return res.json() if res.text() else None

    def get(self, path: str) -> Any:
        return self._do("GET", path)

    def put(self, path: str, body: Any) -> Any:
        return self._do("PUT", path, body)

    def patch(self, path: str, body: Any) -> Any:
        return self._do("PATCH", path, body)


def seed(d: Dataset, *, db: Path, sessions: Path, user_id: str, api: Api) -> dict[int, int]:
    """Write the dataset; returns employee index -> employees.id."""
    con = sqlite3.connect(db, timeout=30)
    con.execute("PRAGMA foreign_keys=ON")
    now = d.now
    with con:
        _accounts(con, d, sessions, user_id)
        _chatters(con, d, user_id)
    # The relay creates each login's Employee row (and the owner's) on the roster read.
    roster = api.get("/admin/employees?include_disabled=true")["employees"]
    by_chatter = {r.get("chatter_id"): r["id"] for r in roster if r.get("chatter_id")}
    owner = next(r["id"] for r in roster if r["kind"] == "owner" or r.get("user_id") == user_id and not r.get("chatter_id"))
    emp_ids = {0: owner}
    for e in d.employees[1:]:
        emp_ids[e["index"]] = by_chatter[_uid("chatter", e["username"])]
    api.patch(f"/admin/employees/{owner}", {"display_name": d.employees[0]["name"]})
    with con:
        con.executemany("UPDATE employees SET color=?, created_at=? WHERE id=?",
                        [(e["color"], ts(now - timedelta(days=200 - 9 * e["index"])), emp_ids[e["index"]])
                         for e in d.employees])
        _bulk(con, d, emp_ids, user_id)
    con.close()
    _settings(d, api, emp_ids)
    return emp_ids


def _accounts(con, d: Dataset, sessions: Path, user_id: str) -> None:
    acc_dir = sessions / "accounts"
    acc_dir.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate(d.creators):
        a = acc_dir / c["id"]
        a.mkdir(exist_ok=True)
        (a / "meta.json").write_text(json.dumps({
            "id": c["id"], "nickname": c["nickname"], "color": c["color"], "incogniton_profile_id": None,
            "platform": "onlyfans", "name": c["name"], "created_at": iso(c["created_at"]),
            "last_used_at": iso(d.now - timedelta(minutes=3 + 11 * i))}))
        (a / "session_demo.json").write_text("{}")
        (a / "latest.json").write_text(json.dumps({"session": "session_demo.json", "ts": iso(d.now)}))
        con.execute("INSERT INTO accounts(id, nickname, color, is_active_default, created_at, last_used_at) "
                    "VALUES (?,?,?,?,?,?)", (c["id"], c["nickname"], c["color"], 1 if i == 0 else 0,
                                             ts(c["created_at"]), ts(d.now)))
        con.execute("INSERT INTO user_accounts(user_id, account_id, created_at) VALUES (?,?,?)",
                    (user_id, c["id"], ts(c["created_at"])))
    (sessions / "active.json").write_text(json.dumps({"active_account_id": d.creators[0]["id"]}))


def _chatters(con, d: Dataset, user_id: str) -> None:
    for e in d.employees[1:]:
        cid = _uid("chatter", e["username"])
        con.execute("INSERT INTO chatters(id, username, password, display_name, color, is_active, created_at, "
                    "last_seen_at) VALUES (?,?,?,?,?,1,?,?)",
                    (cid, e["username"], "demo-shots-throwaway", e["name"], e["color"],
                     ts(d.now - timedelta(days=200 - 9 * e["index"])), ts(e["last_login"])))
        con.execute("INSERT INTO chatter_users(chatter_id, user_id, created_at) VALUES (?,?,?)",
                    (cid, user_id, ts(d.now - timedelta(days=190))))


def _bulk(con, d: Dataset, emp: dict[int, int], user_id: str) -> None:
    now = d.now
    spend: dict[tuple[str, int], int] = {}
    last_tx: dict[tuple[str, int], Any] = {}
    for t in d.transactions:
        k = (t["account_id"], t["fan_id"])
        spend[k] = spend.get(k, 0) + t["amount_cents"]
        last_tx[k] = max(last_tx.get(k, t["occurred_at"]), t["occurred_at"])
    last_in: dict[tuple[str, int], Any] = {}
    last_out: dict[tuple[str, int], Any] = {}
    for m in d.messages:
        k = (m["account_id"], m["fan_id"])
        tgt = last_in if m["direction"] == "in" else last_out
        tgt[k] = max(tgt.get(k, m["created_at"]), m["created_at"])

    # Fans (one row per Creator x fan).
    rows = []
    for s in d.subs:
        f = d.fans[s["fan_id"]]
        k = (s["account_id"], s["fan_id"])
        rows.append((s["account_id"], f["id"], f["username"], f["name"], f["avatar"], 0, "[]", 0, 0, "[]", "[]",
                     "[]", "{}", spend.get(k, 0), 0, 0, ts(last_in[k]) if k in last_in else None,
                     ts(last_out[k]) if k in last_out else None, ts(now - timedelta(minutes=(f["id"] % 3000))),
                     ts(s["subscribed_at"]), ts(s["subscribed_at"]), spend.get(k, 0), ts(s["expires_at"]),
                     s["status"], 0, "idle", 0, 0, "demo-shots", ts(s["subscribed_at"]), ts(now)))
    con.executemany(
        "INSERT INTO fans(account_id, fan_id, of_username, of_display_name, avatar_url, is_name_real, recent_events, "
        "likes_boobs, likes_ass, family_names, pets, communication_style, custom_fields, lifetime_spend_cents, is_bot, "
        "turn_counter, last_message_received_at, last_message_sent_at, last_online_at, subscribed_at, "
        "of_subscribed_at, of_total_spent_cents, subscription_expires_at, subscription_status, is_followed, "
        "deep_convo_state, deep_convo_skip_level, deep_convo_skip_remaining, source, created_at, updated_at, tags) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'[]')", rows)
    # NOT NULL text columns the insert above leaves to their defaults are filled here if the schema has no default.

    # Messages first: a sale's credit trigger reads the message that earned it.
    con.executemany(
        "INSERT INTO messages(account_id, fan_id, message_id, direction, sender_name, body, media_ids, media_count, "
        "price_cents, is_paid, is_tip, purchased_at, is_unsent, is_promise, sent_by_employee_id, created_at, "
        "ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?,0,?,0,0,?,?,?)",
        [(m["account_id"], m["fan_id"], m["message_id"], m["direction"],
          d.fans[m["fan_id"]]["name"] if m["direction"] == "in" else d.creator(m["account_id"])["name"],
          m["body"], "[]", m["media_count"], m["price_cents"], m["is_paid"],
          ts(m["purchased_at"]) if m["purchased_at"] else None,
          emp[m["employee"]] if m["employee"] is not None else None, ts(m["created_at"]), ts(m["created_at"]))
         for m in sorted(d.messages, key=lambda m: m["created_at"])])

    desc = {"subscription": "Subscription from ", "rebill": "Recurring subscription from ",
            "ppv_message": "Payment for message from ", "custom": "Custom request from ", "ppv_post": "Post purchase by ",
            "tip": "Tip from ", "tip_post": "Tip on post from ", "ppv_stream": "Stream from ",
            "tip_stream": "Tip on stream from "}
    tx_rows = []
    for t in sorted(d.transactions, key=lambda t: t["occurred_at"]):
        pending = t["occurred_at"] > now - timedelta(days=7)
        fee = t["amount_cents"] // 5
        tx_rows.append((t["account_id"], t["fan_id"], t["kind"], t["message_id"], t["amount_cents"], "USD",
                        ts(t["occurred_at"]), f"demo-{t['id']}", "pending" if pending else "cleared",
                        None if pending else ts(t["occurred_at"] + timedelta(days=7)), 7,
                        t["amount_cents"] - fee, fee, 0, desc[t["kind"]] + d.fans[t["fan_id"]]["name"], "ingest",
                        None if t["message_id"] else emp[t["employee"]], ts(t["occurred_at"])))
    con.executemany(
        "INSERT INTO transactions(account_id, fan_id, kind, message_id, amount_cents, currency, occurred_at, "
        "provider_transaction_id, status, cleared_at, payout_pending_days, net_cents, fee_cents, vat_cents, "
        "description, source, attributed_employee_id, ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        tx_rows)

    # Local chat rows (the app's first-paint seed and the roster counts).
    latest: dict[tuple[str, int], dict] = {}
    for m in d.messages:
        k = (m["account_id"], m["fan_id"])
        if k not in latest or m["created_at"] > latest[k]["created_at"]:
            latest[k] = m
    con.executemany(
        "INSERT INTO chats(account_id, fan_id, last_message_id, last_message_at, last_message_preview, unread_count, "
        "is_pinned, is_priority, hidden_locally, list_ids) VALUES (?,?,?,?,?,?,0,0,0,'[]')",
        [(a, f, m["message_id"], ts(m["created_at"]), m["body"][:120], 1 if m["direction"] == "in" else 0)
         for (a, f), m in latest.items()])

    # Shifts: one daily series per seat (Employee x slot), from two weeks back.
    day0 = (now - timedelta(days=14)).replace(hour=0, minute=0, second=0)
    seats: dict[tuple[int, int], list[str]] = {}
    for (aid, s), e in d.coverage.items():
        seats.setdefault((e, s), []).append(aid)
    shift_of: dict[tuple[int, int], int] = {}
    for (e, s), aids in sorted(seats.items()):
        start = day0 + timedelta(hours=SLOTS[s][1])
        cur = con.execute(
            "INSERT INTO shifts(agency_user_id, start_utc, end_utc, tz, repeat_days, repeat_until, cancelled_dates, "
            "status, created_by, created_at, updated_at) VALUES (?,?,?,?,?,NULL,NULL,'scheduled',?,?,?)",
            (user_id, ts(start), ts(start + timedelta(hours=8)), "UTC", json.dumps([1, 2, 3, 4, 5, 6, 7]),
             f"owner:{user_id}", ts(day0), ts(day0)))
        shift_of[(e, s)] = cur.lastrowid
        con.executemany("INSERT INTO shift_assignments(shift_id, employee_id, account_id) VALUES (?,?,?)",
                        [(cur.lastrowid, emp[e], a) for a in aids])
        con.executemany("INSERT OR IGNORE INTO employee_account_access(employee_id, account_id) VALUES (?,?)",
                        [(emp[e], a) for a in aids])
    # Chatter logins' Creator allowlists, so each one's access lists its Creators.
    for e in d.employees[1:]:
        cid = _uid("chatter", e["username"])
        aids = sorted({a for (a, s), x in d.coverage.items() if x == e["index"]})
        if e["role"] == "manager":
            continue  # managers see every Creator
        con.executemany("INSERT OR IGNORE INTO chatter_account_access(chatter_id, user_id, account_id, created_at) "
                        "VALUES (?,?,?,?)", [(cid, user_id, a, ts(now - timedelta(days=120))) for a in aids])
    con.executemany(
        "INSERT INTO clock_events(agency_user_id, employee_id, account_id, shift_id, in_utc, out_utc, close_reason, "
        "last_seen_utc) VALUES (?,?,?,?,?,?,?,?)",
        [(user_id, emp[c["employee"]], c["account_id"], shift_of.get((c["employee"], c["slot"])), ts(c["in"]),
          ts(c["out"]) if c["out"] else None, "manual" if c["out"] else None,
          # An open event's heartbeat is the relay's real now, so its Auto clock-out sweep (real clock) keeps it open.
          ts(c["last_seen"]) if c["out"] else ts(datetime.now(timezone.utc)))
         for c in d.clock_events])

    # Scripts (saved replies) for the top Creators.
    for c in d.creators[:6]:
        con.executemany(
            "INSERT INTO saved_replies(account_id, title, text, price_cents, locked_text, media_json, "
            "tagged_users_json, previews_json, tags_json, created_at, updated_at) VALUES (?,?,?,?,0,?, '[]','[]',?,?,?)",
            [(c["id"], s["title"], s["text"].replace("{creator}", c["nickname"]), s["price_cents"],
              json.dumps([{"id": d.vault[(s["step"] * 3) % 40]["id"], "type": "photo"}] if s["price_cents"] else []),
              json.dumps(s["tags"]), ts(now - timedelta(days=60 - s["step"] * 3)),
              ts(now - timedelta(days=20 - s["step"]))) for s in d.scripts])

    # Scheduled posts.
    con.executemany(
        "INSERT INTO posts(account_id, status, text, price_cents, media_ids, label_ids, scheduled_for, "
        "excluded_list_ids, created_by_employee_id, created_at, updated_at) VALUES (?,?,?,?,?,'[]',?,'[]',?,?,?)",
        [(p["account_id"], "scheduled", p["text"], p["price_cents"],
          json.dumps([d.vault[int(f.split("-")[1][:2]) - 1]["id"] for f in p["media"]]), ts(p["scheduled_for"]),
          emp[1], ts(now - timedelta(days=1)), ts(now - timedelta(days=1))) for p in d.posts])

    # Tracking links with their clicks.
    for link in d.tracking_links:
        cur = con.execute("INSERT INTO tracking_links(account_id, name, slug, target_url, click_count, created_at) "
                          "VALUES (?,?,?,?,?,?)", (link["account_id"], link["name"], link["slug"],
                                                   f"https://onlyfans.com/{d.creator(link['account_id'])['username']}",
                                                   link["clicks"], ts(link["created_at"])))
        link["db_id"] = cur.lastrowid

    # Share for Share: each top Creator's own profile, opted in.
    for c in d.creators[:8]:
        con.execute("INSERT INTO s4s_profiles(account_id, opted_in, discovery_visible, daily_limit, display_name, "
                    "username, avatar_url, created_at, updated_at) VALUES (?,1,1,3,?,?,?,?,?)",
                    (c["id"], c["name"], c["username"], c["avatar"], ts(now - timedelta(days=40)), ts(now)))


def _settings(d: Dataset, api: Api, emp: dict[int, int]) -> None:
    api.put("/admin/settings/account", {"agency_name": STUDIO})
    api.put("/admin/settings/time-tracking", {"enabled": True, "auto_clock_out_minutes": 120})
    roles = api.get("/admin/settings/roles")["config"]
    ids = {r["id"] for r in roles.get("roles", [])}
    assign = dict(roles.get("assignments") or {})
    for e in d.employees[1:]:
        want = "manager" if e["role"] == "manager" else "chatter"
        if e["index"] == 3 and "team-leader" in ids:
            want = "team-leader"
        if want in ids or want in ("chatter",):
            assign[str(emp[e["index"]])] = want
    roles["assignments"] = assign
    api.put("/admin/settings/roles", roles)
