"""Synthetic demo agency for the marketing screenshots (scripts/demo-shots/).

`build(now)` returns one deterministic dataset (fixed seed) for a studio named
"Northstar Studio": 20 Creators whose month-to-date sales sum to about
$1,000,000 (skewed, top about $180k, bottom about $8k), 12 Employees (the owner,
2 managers, 9 chatters), a shared pool of fans, sales over the last ~35 days,
chat traffic, shifts, scripts, vault folders, auto posts, tracking links, S4S
partners. Every name is invented; every picture is a local file under assets/.

Times are relative to `now`: `$DEMO_SHOTS_NOW` (ISO 8601, UTC) when set, else the
latest 22:40 UTC that has passed, so "today" is nearly over and the period
comparisons are not dragged down by a day that has just begun. capture.py sets
the browser's clock to the same `now`. Same seed, same `now` -> same dataset.
"""
from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

SEED = 20261023
STUDIO = "Northstar Studio"
OWNER_USERNAME = "northstar"
OWNER_NAME = "Alex Morgan"
MONTH_TARGET_CENTS = 100_000_000          # $1,000,000.00 month to date
TOP_CENTS, BOTTOM_CENTS = 18_000_000, 800_000
HISTORY_DAYS = 35                          # sales and chats this far back
ASSET_ORIGIN = "https://demo-assets.invalid"   # fulfilled from assets/ by the capture router


def asset(path: str) -> str:
    return f"{ASSET_ORIGIN}/{path}"


CREATOR_NAMES = [
    ("Ava Monroe", "avamonroe"), ("Luna Rivera", "lunarivera"), ("Mia Sinclair", "miasinclair"),
    ("Sofia Blake", "sofiablake"), ("Chloe Hart", "chloehart"), ("Isla Bennett", "islabennett"),
    ("Ruby Vale", "rubyvale"), ("Nova Quinn", "novaquinn"), ("Lily Carter", "lilycarter"),
    ("Zoe Marlowe", "zoemarlowe"), ("Emma Rose", "emmarose.x"), ("Ivy Laurent", "ivylaurent"),
    ("Ella Belle", "ariabelle"), ("Stella Grey", "stellagrey"), ("Jade Ellison", "jadeellison"),
    ("Maya Torres", "mayatorres"), ("Willow Hayes", "willowhayes"), ("Camila Reyes", "camilareyes"),
    ("Hazel Brooks", "hazelbrooks"), ("Skye Adler", "skyeadler"),
]
CREATOR_COLORS = ["#e8618c", "#8b5cf6", "#4f7cff", "#14b8a6", "#f59e0b", "#ef4444", "#10b981", "#ec4899",
                  "#6366f1", "#0ea5e9", "#f97316", "#a855f7", "#22c55e", "#e11d48", "#06b6d4", "#d946ef",
                  "#84cc16", "#3b82f6", "#f43f5e", "#64748b"]

# (display name, role id, colour). The owner is the registered user; the rest are chatter logins.
EMPLOYEES = [
    (OWNER_NAME, "owner", "#4f7cff"),
    ("Jordan Lee", "manager", "#8b5cf6"), ("Priya Shah", "manager", "#ec4899"),
    ("Marco Ruiz", "chatter", "#f59e0b"), ("Hannah Kim", "chatter", "#10b981"),
    ("Diego Santos", "chatter", "#ef4444"), ("Olivia Chen", "chatter", "#0ea5e9"),
    ("Tom Becker", "chatter", "#a855f7"), ("Sara Novak", "chatter", "#14b8a6"),
    ("Liam Walsh", "chatter", "#f97316"), ("Ana Petrova", "chatter", "#6366f1"),
    ("Kai Nakamura", "chatter", "#22c55e"),
]
MANAGER = 1  # Jordan Lee: the dashboard hero signs in as this manager, whose "My shifts" lists the evening shift
# Three daily shift slots (UTC hours [start, end)); every Creator is covered by one chatter per slot.
SLOTS = [("Morning", 6, 14), ("Evening", 14, 22), ("Night", 22, 30)]

FAN_FIRST = ["Mike", "Chris", "Dan", "Jason", "Ryan", "Matt", "Kevin", "Brian", "Josh", "Tyler", "Nick", "Eric",
             "Adam", "Steve", "Mark", "Paul", "Jake", "Luke", "Sam", "Ben", "Tony", "Alex", "Greg", "Scott", "Sean",
             "Kyle", "Derek", "Brandon", "Aaron", "Jeff", "Carlos", "Andre", "Marcus", "Victor", "Ethan", "Noah",
             "Owen", "Henry", "Leo", "Max", "Oscar", "Felix", "Hugo", "Ivan", "Rafael", "Theo", "Jonas", "Emil"]
FAN_LAST = ["T", "R", "M", "K", "B", "S", "W", "P", "D", "H", "L", "G", "C", "F", "J", "N", "V", "Z"]
FAN_TAGS = ["_fan", "88", "_nyc", "_la", "77", "_tx", "_uk", "92", "_real", "x", "_99", "_mtl", "21", "_aus"]

CHAT_FAN = [
    "hey gorgeous, how's your day going?", "just got off work, finally relaxing", "that last post was amazing",
    "what are you up to tonight?", "you always make my day better", "did you have a good weekend?",
    "haha you're too funny", "I was thinking about you today", "any plans for halloween?",
    "loved the beach pics", "how was the gym?", "good morning beautiful", "can't wait for the next set",
    "you looked so good in that red dress", "tell me about your day", "I just got back from a trip",
    "ok you got me curious", "send me something special?", "what's your favorite movie?", "lol same",
]
CHAT_CREATOR = [
    "heyy you! just finished a shoot, kinda tired but happy", "aww you're sweet, thank you",
    "nothing much, cozy night in with some tea", "I'm good babe, how about you?", "omg thank you!! that one was fun",
    "you're always so nice to me", "haha stop it", "gym then brunch, perfect day", "tell me more",
    "I made something just for you", "it's a surprise, you'll love it", "morning! coffee first",
    "that sounds amazing, where did you go?", "I'll show you if you're good", "miss chatting with you",
]
PPV_TEXT = ["Something special just for you", "Sunset set from today", "Behind the scenes from the shoot",
            "A little surprise, made this morning", "Exclusive set, only for my favorites",
            "New outfit try-on", "Weekend getaway pics", "You asked for it"]
SCRIPT_TITLES = [
    ("Welcome sequence", "Hey {name}! So happy you're here, I'm {creator}. What made you subscribe?"),
    ("Good morning opener", "Good morning {name}! Just woke up, what are you up to today?"),
    ("Weekend tease", "Weekend plans? I've got a little something for you later..."),
    ("PPV follow-up", "Did you get a chance to open what I sent you? I made it with you in mind"),
    ("Re-engage quiet fan", "Haven't heard from you in a while, I missed our chats!"),
    ("Birthday message", "Happy birthday {name}! Got a special gift for you today"),
    ("Custom request intro", "I love doing customs, tell me what you have in mind and I'll make it happen"),
    ("Renewal reminder", "Your sub renews soon, stick around, the next set is my best yet"),
    ("Tip thank-you", "Thank you so much for the tip, you just made my whole day!"),
    ("Live stream invite", "Going live tonight at 9, come hang out with me"),
    ("Bundle offer", "3 sets for the price of 2 this week only, want the bundle?"),
    ("Late night check-in", "Can't sleep... what are you doing up so late?"),
    ("Gym selfie lead-in", "Just finished leg day, want to see the post-workout pics?"),
    ("Holiday special", "Halloween costume reveal coming, want first look?"),
]
VAULT_FOLDERS = ["Beach day", "Gym & fitness", "Behind the scenes", "Travel", "Cozy at home", "Outfits",
                 "Customs", "Best sellers"]
POST_TEXT = ["New week, new set. Who's ready?", "Golden hour is my favorite hour", "Sunday reset, coffee and sunshine",
             "Throwback to the beach trip", "Gym done, feeling unstoppable", "Cozy night in, come keep me company",
             "Outfit of the day, rate it 1-10", "Travel diaries, part 3", "Halloween countdown has started",
             "Just dropped a new bundle in your DMs"]
TRACKING_LINK_NAMES = ["Instagram bio", "TikTok bio", "Reddit promo", "Twitter pinned", "Linktree", "Fansly cross-promo",
                       "Snapchat story", "Telegram channel", "YouTube shorts", "Threads bio"]
S4S_PARTNERS = [("Bella Vaughn", "bellavaughn"), ("Rosie Lane", "rosielane"), ("Kira Moss", "kiramoss"),
                ("Daisy Fox", "daisyfox"), ("Gia Romano", "giaromano"), ("Elle Harper", "elleharper"),
                ("Tessa Wilde", "tessawilde"), ("Nina Cruz", "ninacruz"), ("Piper Lane", "piperlane"),
                ("Remi Sloan", "remisloan"), ("Lola James", "lolajames"), ("Faye Sterling", "fayesterling")]

KIND_COUNT_WEIGHTS = {"subscription": 13, "rebill": 15, "ppv_message": 37, "custom": 1, "ppv_post": 8, "tip": 20,
                      "tip_post": 3, "ppv_stream": 1.5, "tip_stream": 1.5}
PRICES = {  # dollars, weights
    "ppv_message": ([10, 15, 20, 25, 30, 35, 40, 50, 60, 75, 100, 150], [6, 10, 12, 12, 10, 9, 8, 8, 5, 4, 3, 1]),
    "custom": ([100, 150, 200, 250, 300, 400], [4, 4, 3, 2, 2, 1]),
    "ppv_post": ([5, 10, 15, 20, 25], [3, 5, 4, 2, 1]),
    "tip": ([5, 10, 15, 20, 25, 50, 100, 200], [8, 12, 6, 8, 6, 5, 2, 1]),
    "tip_post": ([3, 5, 10], [3, 4, 2]),
    "ppv_stream": ([10, 15, 20], [3, 3, 1]),
    "tip_stream": ([5, 10, 20, 50], [4, 4, 2, 1]),
}
SUB_PRICES = [999, 1299, 1499, 1999]
# Hour-of-day activity (UTC), evening heavy.
HOUR_W = [5, 4, 3, 2, 2, 2, 2, 3, 3, 4, 4, 5, 5, 5, 6, 6, 7, 8, 9, 10, 10, 9, 8, 6]


@dataclass
class Dataset:
    now: datetime
    month_start: datetime
    creators: list[dict[str, Any]] = field(default_factory=list)
    employees: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[tuple[str, int], int] = field(default_factory=dict)   # (account_id, slot) -> employee index
    fans: dict[int, dict[str, Any]] = field(default_factory=dict)        # fan_id -> fan
    creator_fans: dict[str, list[int]] = field(default_factory=dict)      # account_id -> fan ids
    subs: list[dict[str, Any]] = field(default_factory=list)              # (account, fan) subscription facts
    transactions: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    clock_events: list[dict[str, Any]] = field(default_factory=list)
    scripts: list[dict[str, Any]] = field(default_factory=list)
    vault: list[dict[str, Any]] = field(default_factory=list)
    vault_folders: list[dict[str, Any]] = field(default_factory=list)
    posts: list[dict[str, Any]] = field(default_factory=list)
    tracking_links: list[dict[str, Any]] = field(default_factory=list)
    s4s_partners: list[dict[str, Any]] = field(default_factory=list)
    referrals: dict[str, int] = field(default_factory=dict)
    thread: dict[str, Any] = field(default_factory=dict)                  # the open Messages Pro thread

    def creator(self, account_id: str) -> dict[str, Any]:
        return next(c for c in self.creators if c["id"] == account_id)


def ts(dt: datetime) -> str:
    """SQLAlchemy's SQLite DateTime storage (naive UTC, microseconds)."""
    return dt.astimezone(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S.%f")


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _targets(rng: random.Random) -> list[int]:
    """20 month-to-date targets, top TOP_CENTS, bottom BOTTOM_CENTS, summing to MONTH_TARGET_CENTS."""
    n = len(CREATOR_NAMES)
    lo, hi = 0.5, 12.0
    for _ in range(60):  # bisect the curve exponent so the sum lands on the target
        p = (lo + hi) / 2
        vals = [BOTTOM_CENTS + (TOP_CENTS - BOTTOM_CENTS) * ((n - 1 - i) / (n - 1)) ** p for i in range(n)]
        if sum(vals) > MONTH_TARGET_CENTS:
            lo = p
        else:
            hi = p
    jit = [1.0] + [rng.uniform(0.94, 1.06) for _ in range(n - 2)] + [1.0]
    vals = [v * j for v, j in zip(vals, jit)]
    mid = sum(vals[1:-1])
    scale = (MONTH_TARGET_CENTS - vals[0] - vals[-1]) / mid
    vals = [vals[0]] + [v * scale for v in vals[1:-1]] + [vals[-1]]
    return sorted((int(v) for v in vals), reverse=True)


def default_now() -> datetime:
    """`$DEMO_SHOTS_NOW`, else the latest 22:40 UTC that has passed."""
    if os.environ.get("DEMO_SHOTS_NOW"):
        return datetime.fromisoformat(os.environ["DEMO_SHOTS_NOW"].replace("Z", "+00:00")).astimezone(timezone.utc)
    real = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    anchor = real.replace(hour=22, minute=40)
    return anchor if anchor <= real else anchor - timedelta(days=1)


def build(now: datetime | None = None) -> Dataset:
    rng = random.Random(SEED)
    now = (now or default_now()).astimezone(timezone.utc).replace(microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0)
    d = Dataset(now=now, month_start=month_start)

    # ── Creators ─────────────────────────────────────────────────────────────
    targets = _targets(rng)
    ids = sorted(rng.sample(range(180_000_000, 420_000_000), len(CREATOR_NAMES)))
    rng.shuffle(ids)
    for i, ((name, username), target) in enumerate(zip(CREATOR_NAMES, targets)):
        d.creators.append({
            "id": str(ids[i]), "name": name, "username": username, "nickname": name.split()[0],
            "color": CREATOR_COLORS[i], "avatar": asset(f"avatars/creator-{i + 1:02d}.jpg"),
            "target_cents": target, "sub_price_cents": rng.choice(SUB_PRICES),
            "fan_count": int(140 + 2400 * (target / TOP_CENTS) ** 0.8),
            "created_at": now - timedelta(days=rng.randint(120, 600)),
            "online": i % 4 != 3, "posts": rng.randint(180, 1400), "media": rng.randint(400, 3200),
            "likes": rng.randint(40_000, 900_000),
        })

    # ── Employees and coverage ───────────────────────────────────────────────
    for i, (name, role, color) in enumerate(EMPLOYEES):
        first = name.split()[0].lower()
        d.employees.append({"index": i, "name": name, "role": role, "color": color,
                            "username": f"{first}.{name.split()[1][0].lower()}" if i else OWNER_USERNAME,
                            "avatar": asset(f"avatars/employee-{i + 1:02d}.jpg"),
                            "last_login": now - timedelta(minutes=rng.randint(2, 60 * 30))})
    chatters = [e["index"] for e in d.employees if e["role"] == "chatter"]
    managers = [e["index"] for e in d.employees if e["role"] == "manager"]
    assert d.employees[MANAGER]["role"] == "manager"
    for ci, c in enumerate(d.creators):
        for s in range(len(SLOTS)):
            # 9 chatters x 3 slots = 27 seats across 60 creator-slots; heavier creators get dedicated seats.
            d.coverage[(c["id"], s)] = chatters[(ci + 3 * s) % len(chatters)]
    for ci, c in enumerate(d.creators[:4]):  # managers also chat the top creators in the evening
        d.coverage[(c["id"], 1)] = managers[ci % 2] if ci >= 2 else d.coverage[(c["id"], 1)]

    # ── Fans ─────────────────────────────────────────────────────────────────
    pool_size = 2600
    used: set[str] = set()
    pool: list[int] = []
    for k in range(pool_size):
        fid = rng.randint(100_000_000, 999_999_999)
        while fid in d.fans:
            fid = rng.randint(100_000_000, 999_999_999)
        first = rng.choice(FAN_FIRST)
        last = rng.choice(FAN_LAST)
        uname = f"{first.lower()}{rng.choice(FAN_TAGS)}"
        while uname in used:
            uname = f"{first.lower()}{last.lower()}{rng.randint(1, 999)}"
        used.add(uname)
        d.fans[fid] = {"id": fid, "name": f"{first} {last}.", "username": uname,
                       "avatar": asset(f"avatars/fan-{(k % 30) + 1:02d}.jpg") if k < 30 or rng.random() < 0.25 else None,
                       "country": rng.choice(["US", "US", "US", "UK", "CA", "AU", "DE", "NL", "SE", "IE"])}
        pool.append(fid)
    for c in d.creators:
        fans = rng.sample(pool, min(c["fan_count"], pool_size))
        d.creator_fans[c["id"]] = fans
        for fid in fans:
            sub_at = now - timedelta(days=rng.betavariate(1.2, 2.5) * 300, minutes=rng.randint(0, 1440))
            active = rng.random() < 0.82
            expires = now + timedelta(days=rng.randint(1, 30)) if active else now - timedelta(days=rng.randint(1, 40))
            d.subs.append({"account_id": c["id"], "fan_id": fid, "subscribed_at": sub_at, "expires_at": expires,
                           "status": "active" if active else "expired"})

    # ── Sales and the PPV messages that earned them ──────────────────────────
    hist_start = now - timedelta(days=HISTORY_DAYS)
    mtd_days = max((now - month_start).total_seconds() / 86400, 0.5)
    msg_id = 7_000_000_000
    tx_id = 0

    def when(start: datetime, end: datetime) -> datetime:
        span = (end - start).total_seconds()
        for _ in range(20):
            t = start + timedelta(seconds=rng.random() * span)
            growth = 0.7 + 0.3 * (t - hist_start) / (now - hist_start)  # a studio that is growing
            if rng.random() * max(HOUR_W) <= HOUR_W[t.hour] * growth:
                return t
        return t

    def slot_of(t: datetime) -> int:
        h = t.hour
        return 0 if 6 <= h < 14 else 1 if 14 <= h < 22 else 2

    kinds, kweights = zip(*KIND_COUNT_WEIGHTS.items())
    for c in d.creators:
        fans = d.creator_fans[c["id"]]
        # Pareto spend weights: a handful of whales, a long tail.
        fw = [rng.paretovariate(1.3) for _ in fans]
        rate = c["target_cents"] / mtd_days
        for (start, end, goal) in ((month_start, now, c["target_cents"]),
                                   (hist_start, month_start, int(rate * (month_start - hist_start).total_seconds()
                                                                 / 86400 * rng.uniform(0.9, 1.0)))):
            if end <= start:
                continue
            total = 0
            while total < goal:
                kind = rng.choices(kinds, kweights)[0]
                if kind in ("subscription", "rebill"):
                    cents = c["sub_price_cents"]
                else:
                    vals, w = PRICES[kind]
                    cents = rng.choices(vals, w)[0] * 100
                t = when(start, end)
                fan = rng.choices(fans, fw)[0]
                tx_id += 1
                tx = {"id": tx_id, "account_id": c["id"], "fan_id": fan, "kind": kind, "amount_cents": cents,
                      "occurred_at": t, "message_id": None, "employee": d.coverage[(c["id"], slot_of(t))]}
                if kind in ("ppv_message", "custom"):
                    msg_id += 1
                    sent = t - timedelta(minutes=rng.randint(3, 240))
                    d.messages.append({"account_id": c["id"], "fan_id": fan, "message_id": msg_id, "direction": "out",
                                       "body": rng.choice(PPV_TEXT), "price_cents": cents, "is_paid": True,
                                       "purchased_at": t, "employee": d.coverage[(c["id"], slot_of(sent))],
                                       "created_at": sent, "media_count": rng.randint(1, 6)})
                    tx["message_id"] = msg_id
                d.transactions.append(tx)
                total += cents

    # ── Chat traffic (hand-written sends, fan replies, unpaid PPVs) ──────────
    for c in d.creators:
        fans = d.creator_fans[c["id"]][:400]
        per_day = int(30 + 220 * (c["target_cents"] / TOP_CENTS))
        day = hist_start
        while day < now:
            for _ in range(per_day):
                t = when(day, min(day + timedelta(days=1), now))
                fan = rng.choice(fans)
                msg_id += 1
                d.messages.append({"account_id": c["id"], "fan_id": fan, "message_id": msg_id, "direction": "in",
                                   "body": rng.choice(CHAT_FAN), "price_cents": 0, "is_paid": None,
                                   "purchased_at": None, "employee": None, "created_at": t, "media_count": 0})
                reply = t + timedelta(seconds=rng.randint(40, 420))
                if reply < now:
                    msg_id += 1
                    priced = rng.random() < 0.12
                    d.messages.append({"account_id": c["id"], "fan_id": fan, "message_id": msg_id, "direction": "out",
                                       "body": rng.choice(PPV_TEXT if priced else CHAT_CREATOR),
                                       "price_cents": rng.choice([1500, 2000, 2500, 3000, 4000]) * (1 if priced else 0),
                                       "is_paid": False if priced else None, "purchased_at": None,
                                       "employee": d.coverage[(c["id"], slot_of(reply))], "created_at": reply,
                                       "media_count": rng.randint(1, 4) if priced else 0})
            day += timedelta(days=1)

    # ── Clock events: closed shifts for the history, the current slot still open ──
    day0 = (now - timedelta(days=14)).replace(hour=0, minute=0, second=0)
    seats: dict[tuple[int, int], list[str]] = {}
    for (aid, s), e in d.coverage.items():
        seats.setdefault((e, s), []).append(aid)
    for (e, s), aids in sorted(seats.items()):
        for k in range(15):
            start = day0 + timedelta(days=k, hours=SLOTS[s][1], minutes=rng.randint(0, 9))
            if start > now:
                continue
            end = start + timedelta(hours=8, minutes=rng.randint(-20, 15))
            is_open = end > now
            d.clock_events.append({"employee": e, "account_id": aids[0], "slot": s, "in": start,
                                   "out": None if is_open else end, "last_seen": now - timedelta(seconds=40)
                                   if is_open else end})

    # ── Scripts, vault, posts, links, S4S, referrals ─────────────────────────
    for k, (title, text) in enumerate(SCRIPT_TITLES):
        d.scripts.append({"title": title, "text": text, "price_cents": [0, 0, 1500, 0, 0, 2500, 0, 0, 0, 0, 3500, 0, 2000,
                                                                       1000][k], "tags": [["welcome"], ["opener"],
                          ["tease"], ["ppv"], ["re-engage"], ["birthday"], ["custom"], ["renewal"], ["tips"],
                          ["live"], ["bundle"], ["night"], ["fitness"], ["seasonal"]][k], "step": k})
    for k, name in enumerate(VAULT_FOLDERS):
        d.vault_folders.append({"id": 9100 + k, "name": name, "count": rng.randint(18, 240)})
    for k in range(40):
        d.vault.append({"id": 880_000_000 + k * 7919, "file": f"media/media-{k + 1:02d}.jpg",
                        "type": "video" if k % 5 == 2 else "photo", "duration": rng.randint(15, 420),
                        "folder": d.vault_folders[k % len(VAULT_FOLDERS)]["id"],
                        "created_at": now - timedelta(days=k * 0.9 + rng.random()), "sent": rng.randint(0, 900),
                        "sales_cents": rng.randint(0, 2_400_000)})
    for k in range(18):
        c = d.creators[k % 10]
        d.posts.append({"account_id": c["id"], "text": POST_TEXT[k % len(POST_TEXT)],
                        "scheduled_for": (now + timedelta(hours=3 + k * 7)).replace(minute=0, second=0),
                        "media": [d.vault[(k * 3 + j) % 40]["file"] for j in range(1 + k % 3)],
                        "price_cents": [0, 0, 999, 0, 1499][k % 5]})
    for k, c in enumerate(d.creators[:12]):
        for j in range(8 if k < 3 else 2 + k % 2):
            name = TRACKING_LINK_NAMES[(k + j * 3) % len(TRACKING_LINK_NAMES)]
            clicks = int(rng.uniform(800, 26_000) * (c["target_cents"] / TOP_CENTS) ** 0.5)
            subs = int(clicks * rng.uniform(0.03, 0.11))
            d.tracking_links.append({"account_id": c["id"], "name": name, "slug": f"{c['username']}-{j + 1}",
                                     "clicks": clicks, "subs": subs,
                                     "revenue_cents": subs * rng.randint(2_000, 9_000),
                                     "created_at": now - timedelta(days=rng.randint(10, 200))})
    for k, (name, username) in enumerate(S4S_PARTNERS):
        d.s4s_partners.append({"name": name, "username": username, "fans": rng.randint(4_000, 140_000),
                               "avatar": asset(f"avatars/partner-{k + 1:02d}.jpg")})
    for c in d.creators:
        d.referrals[c["id"]] = int(c["target_cents"] * rng.uniform(0.002, 0.008))

    d.thread = _thread(d, rng)
    return d


def _thread(d: Dataset, rng: random.Random) -> dict[str, Any]:
    """The Messages Pro conversation that is open in the shots: the top Creator and her biggest fan,
    with text, an image, a paid PPV and a tip."""
    c = d.creators[0]
    spend: dict[int, int] = {}
    for t in d.transactions:
        if t["account_id"] == c["id"]:
            spend[t["fan_id"]] = spend.get(t["fan_id"], 0) + t["amount_cents"]
    whale = max(spend, key=spend.get)
    now = d.now
    # (minutes ago, from_fan, text, extra). Lines a few seconds apart share a minute, so the app draws them as
    # one run with one timestamp, and the desktop viewport holds 9+ bubbles: short lines from both sides, the
    # photo, the paid PPV and the tip. The fan has the last word (left side, clear of the combo's phone).
    lines = [
        (63, True, "Good morning! Just landed in Miami, the weather is unreal", {}),
        (58, False, "Omg jealous!! Have the best trip", {}),
        (46, True, "Wow 😍 got anything new for me?", {"liked": True}),
        (41, False, "Just for you 😘", {}),
        (40.9, False, "", {"ppv": 4500, "paid": True, "media": ["media/media-27.jpg", "media/media-31.jpg"]}),
        (14, True, "Unlocked it. Worth every cent", {}),
        (13.9, True, "The second one 🔥🔥", {}),
        (13.8, True, "", {"tip": 5000}),
        (6, False, "Stop it 🙈 a little thank-you from the beach", {"image": "media/media-14.jpg"}),
        (5.9, False, "You just made my whole day, thank you so much!", {}),
        (3, True, "Can't wait for the next set 👀", {}),
        (2.9, True, "Same time tomorrow? 😏", {}),
    ]
    if not d.fans[whale]["avatar"]:
        d.fans[whale]["avatar"] = asset("avatars/fan-30.jpg")
    return {"account_id": c["id"], "fan_id": whale, "spend_cents": spend[whale],
            "messages": [{"minutes": m, "from_fan": f, "text": t, **x} for m, f, t, x in lines]}


if __name__ == "__main__":
    ds = build()
    mtd = sum(t["amount_cents"] for t in ds.transactions if t["occurred_at"] >= ds.month_start)
    print(f"creators={len(ds.creators)} fans={len(ds.fans)} subs={len(ds.subs)} tx={len(ds.transactions)} "
          f"messages={len(ds.messages)} clock={len(ds.clock_events)}")
    print(f"month to date ${mtd / 100:,.2f}; top ${ds.creators[0]['target_cents'] / 100:,.0f}, "
          f"bottom ${ds.creators[-1]['target_cents'] / 100:,.0f}")
