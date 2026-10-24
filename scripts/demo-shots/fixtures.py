"""Browser-side answers for the reads the throwaway relay cannot serve.

The relay answers every `/admin/*` read from the seeded SQLite (seed.py). What it
would fetch live from OnlyFans (`/api/of/*`, plus the few `/admin/*` reads that
proxy OF, like referrals) is answered here from the same dataset, so totals
agree across pages. `answer()` returns a JSON-able body, or None to let the
request through to the relay (for `/admin/*`) or to record it as unmatched (for
`/api/of/*`, which never reaches the relay).
"""
from __future__ import annotations

import random
import re
from datetime import timedelta
from typing import Any

from dataset import MANAGER, SLOTS, Dataset, asset, iso

PURCHASE_KINDS = {"ppv_message": "message", "custom": "message", "ppv_post": "post", "ppv_stream": "stream"}
TIP_KINDS = {"tip", "tip_post", "tip_stream"}
EMPTY = {"list": [], "hasMore": False}


class AssetRef(str):
    """An answer that is a picture: the router serves this asset URL's file."""


class Fixtures:
    def __init__(self, d: Dataset):
        self.d = d
        self.by_id = {c["id"]: c for c in d.creators}
        self.top = d.creators[0]
        self._chats: dict[str, list[dict[str, Any]]] = {}
        self.spend: dict[tuple[str, int], int] = {}
        self.sales: dict[str, list[dict[str, Any]]] = {}
        for t in d.transactions:
            key = (t["account_id"], t["fan_id"])
            self.spend[key] = self.spend.get(key, 0) + t["amount_cents"]
            if t["occurred_at"] >= d.now - timedelta(days=2):
                self.sales.setdefault(t["account_id"], []).append(t)
        for rows in self.sales.values():
            rows.sort(key=lambda t: t["occurred_at"], reverse=True)
        self.active = {(s["account_id"], s["fan_id"]) for s in d.subs if s["status"] == "active"}
        self._thread = self._build_thread()

    # ── shapes ──────────────────────────────────────────────────────────────
    def creator_user(self, c: dict[str, Any]) -> dict[str, Any]:
        return {"id": int(c["id"]), "name": c["name"], "username": c["username"], "avatar": c["avatar"],
                "avatarThumbs": {"c50": c["avatar"], "c144": c["avatar"]}}

    def profile(self, c: dict[str, Any]) -> dict[str, Any]:
        active = sum(1 for s in self.d.subs if s["account_id"] == c["id"] and s["status"] == "active")
        return {**self.creator_user(c), "subscribePrice": c["sub_price_cents"] / 100, "isFree": False,
                "header": asset("media/media-06.jpg"), "headerThumbs": {"w480": asset("media/media-06.jpg")},
                "about": "Sunsets, gym days and travel diaries. New sets every week.", "isVerified": True,
                "postsCount": c["posts"], "photosCount": int(c["media"] * 0.8), "videosCount": int(c["media"] * 0.2),
                "mediasCount": c["media"], "favoritedCount": c["likes"], "subscribersCount": active,
                "joinDate": iso(c["created_at"]), "location": "Los Angeles, CA", "website": None,
                "isPerformer": True, "isRealPerformer": True, "canEarn": True, "lastSeen": iso(self.d.now)}

    def fan_user(self, fid: int) -> dict[str, Any]:
        f = self.d.fans[fid]
        return {"id": fid, "name": f["name"], "username": f["username"], "avatar": f["avatar"],
                "customNickname": None, "displayName": None, "notice": None, "isRestricted": False}

    def media(self, file: str, mid: int, kind: str = "photo") -> dict[str, Any]:
        url = asset(file)
        v = {"url": url}
        return {"id": mid, "type": kind, "canView": True, "url": url, "width": 360, "height": 450,
                "files": {"thumb": v, "squarePreview": v, "preview": v, "full": v, "source": v},
                **({"duration": 95} if kind == "video" else {})}

    # ── Messages Pro ────────────────────────────────────────────────────────
    def _build_thread(self) -> list[dict[str, Any]]:
        th = self.d.thread
        c, fid = self.by_id[th["account_id"]], th["fan_id"]
        out = []
        for i, m in enumerate(th["messages"]):
            me, fan = self.creator_user(c), self.fan_user(fid)
            msg = {"id": 9_100_000 + i, "text": m["text"], "fromUser": fan if m["from_fan"] else me,
                   "toUser": me if m["from_fan"] else fan, "createdAt": iso(self.d.now - timedelta(minutes=m["minutes"])),
                   "isFree": True, "isOpened": True, "isTip": False, "price": 0, "media": [], "mediaCount": 0,
                   "isLiked": bool(m.get("liked")), "isPinned": False, "lockedText": False}
            if "image" in m:
                msg["media"] = [self.media(m["image"], 9_200_000 + i)]
                msg["mediaCount"] = 1
            if "ppv" in m:
                msg.update(isFree=False, price=m["ppv"] / 100, isOpened=True, isPaid=True,
                           media=[self.media(f, 9_300_000 + i * 10 + j) for j, f in enumerate(m["media"])],
                           mediaCount=24)
            if "tip" in m:
                msg.update(isTip=True, text=f"I sent you a ${m['tip'] / 100:.2f} tip ❤️", price=0)
            out.append(msg)
        return out

    def chats(self, account_id: str) -> list[dict[str, Any]]:
        if account_id in self._chats:
            return self._chats[account_id]
        latest: dict[int, dict[str, Any]] = {}
        for m in self.d.messages:
            if m["account_id"] != account_id:
                continue
            if m["fan_id"] not in latest or m["created_at"] > latest[m["fan_id"]]["created_at"]:
                latest[m["fan_id"]] = m
        # The list a chatter works: active subscribers, nearly all of whom have spent.
        rows = sorted((m for m in latest.values() if (account_id, m["fan_id"]) in self.active
                       and (self.spend.get((account_id, m["fan_id"]), 0) > 0 or m["fan_id"] % 7 == 0)),
                      key=lambda m: m["created_at"], reverse=True)[:60]
        c = self.by_id[account_id]
        th = self.d.thread
        out = []
        if account_id == th["account_id"]:
            last = self._thread[-1]
            out.append(self._chat_row(th["fan_id"], last, unread=0, online=True))
            rows = [m for m in rows if m["fan_id"] != th["fan_id"]]
        for k, m in enumerate(rows):
            fan_spoke = m["direction"] == "in"
            text = m["body"]
            last = {"id": m["message_id"], "text": text, "createdAt": iso(m["created_at"]),
                    "fromUser": self.fan_user(m["fan_id"]) if fan_spoke else self.creator_user(c),
                    "mediaCount": m["media_count"], "isFree": not m["price_cents"], "isTip": False,
                    "isOpened": bool(m["is_paid"]), "price": m["price_cents"] / 100}
            out.append(self._chat_row(m["fan_id"], last, unread=(1 + k % 3) if fan_spoke and k % 4 != 3 else 0,
                                      online=k % 3 == 0))
        self._chats[account_id] = out
        return out

    def _chat_row(self, fid: int, last: dict[str, Any], *, unread: int, online: bool) -> dict[str, Any]:
        keep = ("id", "text", "fromUser", "createdAt", "mediaCount", "isFree", "isTip", "isOpened")
        return {"withUser": self.fan_user(fid), "lastMessage": {k: last.get(k) for k in keep},
                "hasUnread": unread > 0, "unreadMessagesCount": unread, "isOnline": online,
                "canSendMessage": True, "canNotSendReason": None, "isMutedNotifications": False,
                "canGoToProfile": True, "hasUnreadTips": False, "countPinnedMessages": 0}

    # ── router ──────────────────────────────────────────────────────────────
    def answer(self, method: str, path: str, q: dict[str, list[str]], account: str | None) -> Any:
        one = lambda k: (q.get(k) or [None])[0]  # noqa: E731
        c = self.by_id.get(account or "") or self.top
        if method != "GET":
            return None
        if path == "/admin/stats/referrals":
            ids = (one("account_id") or ",".join(self.by_id)).split(",")
            return {"rows": [{"account_id": a, "total_cents": self._referral(a, one("from"), one("to")), "by_day": []}
                             for a in ids if a in self.by_id], "unavailable": []}
        if path == "/health" and one("all_accounts"):  # a live OF probe per Creator
            return {"ok": True, "accounts": [{"account_id": a, "nickname": x["name"].split()[0], "ok": True,
                                              "name": x["name"]} for a, x in self.by_id.items()]}
        if path == "/admin/shifts/me":  # a chatter's own shifts (the manager's dashboard), at the anchor, not real now
            return self._my_shifts(self.d.employees[MANAGER])
        if path == "/admin/errors":  # the sandbox's failed OF calls; a healthy deployment reads 0
            return {"count": 0, "since_hours": 24, "list": []}
        if path == "/admin/automation-rules":
            return {"rules": self.rules(one("account_id") or c["id"])}
        if path == "/admin/auto-follow/stats":
            return {"rows": [self._follows(x) for x in self.d.creators]}
        if path == "/admin/of-tracking-links":
            aid = one("account_id") or c["id"]
            return {"links": [self._link(k, x) for k, x in enumerate(self.d.tracking_links) if x["account_id"] == aid],
                    "username": self.by_id.get(aid, c)["username"], "url_verified": True, "of_available": True,
                    "sources": ["Instagram", "TikTok", "Reddit", "Twitter"], "tags": ["organic", "paid"]}
        if path == "/admin/of-tracking-links/earnings":
            aid = one("account_id") or c["id"]
            return {"available": True, "links": [
                {"id": 7_700_000 + k, "earnings_cents": x["revenue_cents"], "earnings_net_cents": x["revenue_cents"] * 4 // 5,
                 "fans_who_spent": int(x["subs"] * 0.62), "fans_counted": x["subs"], "net_missing_count": 0}
                for k, x in enumerate(self.d.tracking_links) if x["account_id"] == aid]}
        if path == "/admin/s4s/discover":
            return self._s4s(one("q") or "")
        m = re.fullmatch(r"/admin/s4s/media/(\d+)", path)
        if m:
            return AssetRef(asset(self.d.vault[int(m.group(1)) % len(self.d.vault)]["file"]))
        if path == "/api/of/v2/vault/lists":
            return {"list": [self._folder(f) for f in self.d.vault_folders], "hasMore": False}
        if path == "/api/of/v2/vault/media":
            if (one("offset") or "0") != "0" or one("query"):
                return EMPTY
            items = [v for v in self.d.vault if not one("list_id") or str(v["folder"]) == one("list_id")]
            t = one("type")
            if t and t != "all":
                items = [v for v in items if v["type"] == t]
            if one("sort") == "asc":
                items = items[::-1]
            return {"list": [self._vault_item(v) for v in items], "hasMore": False}
        if path == "/api/of/v2/vault/upload/status":
            return {"list": [], "uploads": []}
        if re.fullmatch(r"/api/of/v2/chats/(\d+)/pinned", path) or path in (
                "/api/of/v2/chats/folders", "/api/of/v2/scheduled-sends"):
            return EMPTY
        if path == "/admin/accounts/roster-counts":  # a live OF read on the relay
            return {"counts": {a: {"unread": sum(r["unreadMessagesCount"] for r in self.chats(a)),
                                   "owe_reply": sum(1 for r in self.chats(a) if r["hasUnread"])}
                               for a in self.by_id}}
        if path == "/api/of/v2/users/me":
            return self.profile(c)
        if path == "/api/of/v2/subscriptions/count/all":
            subs = [s for s in self.d.subs if s["account_id"] == c["id"]]
            act = sum(1 for s in subs if s["status"] == "active")
            return {"subscribers": {"active": act, "all": len(subs), "expired": len(subs) - act},
                    "subscriptions": {"active": 0, "all": 0, "expired": 0}}
        if path == "/api/of/v2/subscriptions/subscribers/chart":
            n = sum(1 for s in self.d.subs if s["account_id"] == c["id"]
                    and (s["subscribed_at"] >= self.d.now - timedelta(days=30)))
            return {"subscribers": n, "subscribes": [], "earnings": []}
        if path == "/api/of/v2/chats":
            if (one("offset") or "0") != "0" or one("query") or one("list_id"):
                return {"list": [], "hasMore": False}
            rows = self.chats(c["id"])
            f = one("filter")
            if f == "unread":
                rows = [r for r in rows if r["hasUnread"]]
            elif f:
                rows = []
            lim = int(one("limit") or 25)
            return {"list": rows[:lim], "hasMore": len(rows) > lim}
        m = re.fullmatch(r"/api/of/v2/chats/(\d+)/messages", path)
        if m:
            if int(m.group(1)) == self.d.thread["fan_id"] and not one("before_id"):
                return {"list": list(reversed(self._thread)), "hasMore": False}
            return {"list": [], "hasMore": False}
        m = re.fullmatch(r"/api/of/v2/(chats|users)/(\d+)", path)
        if m and int(m.group(2)) in self.d.fans:
            fid = int(m.group(2))
            if m.group(1) == "users":
                return self.fan_user(fid)
            return next((r for r in self.chats(c["id"]) if r["withUser"]["id"] == fid),
                        self._chat_row(fid, {}, unread=0, online=False))
        if path == "/api/of/v2/users/list":
            ids = q.get("ids", []) + q.get("ids[]", [])
            out = {i: self.fan_user(int(i)) for i in ids if i.isdigit() and int(i) in self.d.fans}
            out.update({i: self.creator_user(self.by_id[i]) for i in ids if i in self.by_id})
            return out
        if path == "/api/of/v2/posts":
            return EMPTY if (one("offset") or "0") != "0" else {"list": self._posts(c), "hasMore": False}
        if re.fullmatch(r"/api/of/v2/chats/(\d+)/media", path):
            return {"list": [], "hasMore": False}
        if path == "/api/of/v2/users/notifications/count":
            return {"unread": 7, "total": 7}
        if path == "/api/of/v2/users/notifications":
            return {"list": self._notifications(c["id"], one("type")), "hasMore": False}
        if path == "/api/of/v2/payouts/transactions":
            return {"list": [], "hasMore": False}
        return None

    # ── money, automations, links, vault, S4S ──────────────────────────────
    def _notifications(self, account_id: str, kind: str | None) -> list[dict[str, Any]]:
        out = []
        for t in self.sales.get(account_id, []):
            fan = self.fan_user(t["fan_id"])
            amount = f"${t['amount_cents'] / 100:,.2f}"
            if kind == "tip" and t["kind"] in TIP_KINDS:
                text = f"{fan['name']} sent you a {amount} tip"
            elif kind == "purchases" and t["kind"] in PURCHASE_KINDS:
                text = f"{fan['name']} purchased your {PURCHASE_KINDS[t['kind']]} for {amount}"
            else:
                continue
            out.append({"id": 5_000_000 + t["id"], "type": kind, "createdAt": iso(t["occurred_at"]), "text": text,
                        "user": fan, "isRead": True})
            if len(out) == 20:
                break
        return out

    def rules(self, account_id: str) -> list[dict[str, Any]]:
        c = self.by_id.get(account_id) or self.top
        scale = max(c["target_cents"] / self.top["target_cents"], 0.08)
        now = self.d.now
        rid = 40_000 + 100 * list(self.by_id).index(c["id"])

        def rule(k: int, kind: str, name: str, payload: dict[str, Any], every: int | None, sent: int | None,
                 on: bool = True, ran_min: int = 40) -> dict[str, Any]:
            started = now - timedelta(minutes=ran_min + 7 * k)
            return {"id": rid + k, "account_id": c["id"], "name": name, "kind": kind, "is_enabled": on,
                    "every_seconds": every, "trigger": {"every_seconds": every} if every else {},
                    "payload": payload, "quiet_hours": None,
                    "created_at": iso(now - timedelta(days=60 - 6 * k)),
                    "last_run": {"status": "ok", "started_at": iso(started),
                                 "completed_at": iso(started + timedelta(seconds=20)), "error_text": None,
                                 "stats": {}},
                    "next_due_at": iso(started + timedelta(seconds=every)) if every else None,
                    "has_pending_job": False, **({"sent": sent} if sent is not None else {})}
        n = lambda v: int(v * scale)  # noqa: E731
        posts = [rule(10 + k, "auto_posts", name, {"posts": [{"text": text}]}, every, None, on=k != 4, ran_min=25 + 50 * k)
                 for k, (name, text, every) in enumerate([
                     ("Morning teaser", "Good morning! New set dropping tonight", 86_400),
                     ("Golden hour post", "Golden hour is my favorite hour", 86_400),
                     ("Weekly bundle promo", "3 sets for the price of 2 this week only", 604_800),
                     ("Story: behind the scenes", "Behind the scenes from today's shoot", 43_200),
                     ("Holiday countdown", "Halloween countdown has started", 604_800)])]
        return [
            rule(0, "nudge_online", "Nudge online fans", {}, 900, None),
            rule(1, "send_welcome", "Subscriber welcome",
                 {"message": "Hey you! So happy you're here. Check your DMs for a little welcome gift"}, 300, n(4_120)),
            rule(2, "purchase_followup", "Purchased",
                 {"text": "Did you like it? I have a part 2 if you want more"}, 300, n(2_870)),
            rule(3, "expiry_message", "Nearing expiry",
                 {"text": "Your sub ends soon, renew and I'll send you something special", "hours": 48}, 3600, n(940)),
            rule(4, "expired_message", "Expired",
                 {"text": "I miss you already. Come back, I saved a set for you", "hours": 24}, 3600, n(610)),
            rule(5, "resubscribe_message", "Resubscribe", {"text": "You're back!! Welcome home"}, 300, n(388)),
            rule(6, "birthday_message", "Birthday", {"text": "Happy birthday! Your present is in your DMs"}, 3600, n(57),
                 on=False),
            *posts,
        ]

    def _follows(self, c: dict[str, Any]) -> dict[str, Any]:
        r = random.Random(c["id"])
        scale = (c["target_cents"] / self.top["target_cents"]) ** 0.5
        d30 = int(r.uniform(900, 1400) * scale)
        d7 = int(d30 * r.uniform(0.22, 0.28))
        on = c["target_cents"] > 9_000_00
        return {"account_id": c["id"], "on": on, "total": int(d30 * r.uniform(4.5, 7.5)), "today": int(d7 / 7 * 0.9),
                "yesterday": int(d7 / 7 * r.uniform(0.9, 1.2)), "d7": d7, "d30": d30,
                "last_followed_at": iso(self.d.now - timedelta(minutes=r.randint(2, 50)))}

    def _link(self, k: int, x: dict[str, Any]) -> dict[str, Any]:
        code = x["slug"]
        return {"id": 7_700_000 + k, "code": code, "name": x["name"], "url": f"https://onlyfans.com/{x['slug'].split('-')[0]}/c{k + 11}",
                "url_verified": True, "clicks": x["clicks"], "subscribers": x["subs"], "created_at": iso(x["created_at"]),
                "end_date": None, "is_deleted": False, "source": "onlyfans", "promo_cost_cents": None,
                "link_source": ["Instagram", "TikTok", "Reddit", "Twitter"][k % 4], "tags": [["organic"], ["paid"]][k % 2],
                "list_id": None, "list_name": None}

    def _folder(self, f: dict[str, Any]) -> dict[str, Any]:
        mine = [v for v in self.d.vault if v["folder"] == f["id"]]
        return {"id": f["id"], "type": "custom", "name": f["name"], "hasMedia": True,
                "photosCount": int(f["count"] * 0.8), "videosCount": f["count"] - int(f["count"] * 0.8),
                "gifsCount": 0, "audiosCount": 0,
                "medias": [{"type": v["type"], "url": asset(v["file"])} for v in mine[:3]]}

    def _vault_item(self, v: dict[str, Any]) -> dict[str, Any]:
        m = self.media(v["file"], v["id"], v["type"])
        return {**m, "isReady": True, "hasError": False, "createdAt": iso(v["created_at"]),
                **({"duration": v["duration"]} if v["type"] == "video" else {}),
                "listStates": [{"id": v["folder"], "type": "custom", "hasMedia": True}]}

    def _s4s(self, q: str) -> list[dict[str, Any]]:
        captions = ["New here? Come say hi, I reply to everyone", "Your new favorite redhead", "Gym girl with a soft side",
                    "Daily posts, no PPV spam", "Travel, beaches and bikinis", "Cosplay every Friday"]
        own = [(c["name"], c["username"], c["avatar"], True) for c in self.d.creators[:6]]
        other = [(p["name"], p["username"], p["avatar"], False) for p in self.d.s4s_partners]
        rows = []
        for k, (name, user, avatar, mine) in enumerate(sorted(other + own, key=lambda x: x[0].lower())):
            if q and q.lower() not in (name + user).lower():
                continue
            rows.append({"profile_id": 300 + k, "display_name": name, "username": user, "avatar_url": avatar,
                         "primary_caption": captions[k % len(captions)],
                         "primary_media": [{"id": 600 + k * 3 + j, "media_type": "photo"} for j in range(3)],
                         "daily_limit": 3 + k % 4, "opted_in": True, "own_agency": mine})
        return rows

    def _my_shifts(self, e: dict[str, Any]) -> dict[str, Any]:
        day0 = self.d.now.replace(hour=0, minute=0, second=0)
        seats = sorted({(s, a) for (a, s), x in self.d.coverage.items() if x == e["index"]})
        occ = [{"shift_id": 5_000 + s, "occurrence_start": iso(day0 + timedelta(days=k, hours=SLOTS[s][1])),
                "occurrence_end": iso(day0 + timedelta(days=k, hours=SLOTS[s][2])), "tz": "UTC", "account_id": a}
               for k in range(8) for s, a in seats]
        return {"accounts": [{"account_id": c["id"], "display_name": c["nickname"], "time_tracking_enabled": True,
                              "clock_in_reminder": False} for c in self.d.creators],
                "occurrences": sorted(occ, key=lambda o: o["occurrence_start"]), "open_clocks": [], "reminder": None}

    def _posts(self, c: dict[str, Any]) -> list[dict[str, Any]]:
        r = random.Random(f"posts-{c['id']}")
        scale = (c["target_cents"] / self.top["target_cents"]) ** 0.5
        out = []
        for k in range(8):
            files = [self.d.vault[(k * 5 + j * 3) % len(self.d.vault)]["file"] for j in range(1 + (k % 3 == 0))]
            likes = int(r.uniform(300, 2400) * scale)
            out.append({"id": 3_100_000 + k, "text": self._post_text(k), "rawText": self._post_text(k), "price": 0,
                        "postedAt": iso(self.d.now - timedelta(hours=5 + 19 * k, minutes=r.randint(0, 50))),
                        "likesCount": likes, "favoritesCount": likes, "commentsCount": int(likes * r.uniform(0.03, 0.08)),
                        "tipsAmount": f"${int(likes * r.uniform(0.05, 0.3))}", "mediaCount": len(files),
                        "media": [self.media(f, 3_200_000 + k * 10 + j) for j, f in enumerate(files)],
                        "isPinned": k == 0, "isOpened": True, "canComment": True, "isFavorite": False,
                        "canToggleFavorite": False, "author": {"id": int(c["id"])}})
        return out

    @staticmethod
    def _post_text(k: int) -> str:
        from dataset import POST_TEXT
        return POST_TEXT[k % len(POST_TEXT)]

    def _referral(self, account_id: str, frm: str | None, to: str | None) -> int:
        base = self.d.referrals.get(account_id, 0)
        if not frm or not to:
            return base
        try:
            from datetime import date
            days = (date.fromisoformat(to) - date.fromisoformat(frm)).days + 1
        except ValueError:
            return base
        mtd = max((self.d.now - self.d.month_start).days + 1, 1)
        return int(base * min(days, 40) / mtd)
