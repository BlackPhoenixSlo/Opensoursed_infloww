from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from . import World, ts
from .fans import FAN_ID_BASE

CAMPAIGN_ID_BASE = 410_000_000
SLUG_BASE = 70_000_000
TX_ID_BASE = 8_300_000_000
WS_MSG_ID_BASE = 9_000_990_000_000
SILENT_ID_OFFSET = 800_000
CLAIMERS_PAGE = 50
BIG_CLAIMERS = CLAIMERS_PAGE + 11
MAX_CLICKS = 40
CLICK_DAYS = 14
KINDS = ("subscription", "rebill", "ppv_post", "ppv_message", "custom", "ppv_stream", "tip", "tip_post",
         "tip_stream")
STATUSES = ("cleared",) * 70 + ("pending",) * 15 + ("chargedback",) * 10 + ("refund_pending",) * 5
OF_LATENCY_S = 0.05
REFERERS = ((None, ""), ("https://www.instagram.com/", "instagram"), ("https://l.instagram.com/", "instagram"),
            ("https://t.co/", "x"), ("https://www.reddit.com/", "reddit"), ("https://www.tiktok.com/", "tiktok"),
            ("https://example.org/page", "other"))
UAS = (("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)", ""), ("Mozilla/5.0 (Linux; Android 14)", ""),
       ("Mozilla/5.0 (Windows NT 10.0; Win64; x64)", ""),
       ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Mobile/15E148 Instagram 302.0.0.23.114", "instagram"),
       ("Mozilla/5.0 (Linux; Android 14; wv) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36 "
        "musical_ly_2023203030 BytedanceWebview/d8a21c6", "tiktok"),
       ("facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)", "bot"))
COUNTRIES = ("DE", "US", "GB", None)
HOT_DAYS = 90
HOT_COUNTRIES = ("US", "GB", "DE", "FR", "ES", "IT", "NL", "BE", "SE", "NO", "DK", "PL", "CZ", "AT", "CH",
                 "CA", "AU", "NZ", "BR", "JP")
HOT_MIX = tuple((ref, ua, country) for ref in (REFERERS[0], REFERERS[1], REFERERS[3], REFERERS[4], REFERERS[5])
                for ua in (UAS[0], UAS[3], UAS[4]) for country in HOT_COUNTRIES)
HOUR = "%Y-%m-%d %H:00:00"


def _of_time(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def label(country: str | None) -> str:
    return country or "XX"


def seed(w: World, creators: list[dict], tmp: Path, *, links: int, campaigns: int, claimed: int,
         hot_per_day: int = 0) -> dict:
    rng = w.rng("tracking_campaigns")
    out: dict = {"links": [], "campaigns": {}, "claimers": {}, "tx": []}
    who: dict[int, dict] = {}
    link_rows, tx_rows = [], []
    tx_id, msg_id = TX_ID_BASE, WS_MSG_ID_BASE
    for ci, c in enumerate(creators):
        aid = c["id"]
        for k in range(links):
            slug = str(SLUG_BASE + ci * 1000 + k)
            created = w.now - timedelta(days=rng.randint(CLICK_DAYS + 1, 60), seconds=rng.randint(0, 86_399))
            seeded = [(w.now - timedelta(days=rng.uniform(0, CLICK_DAYS), seconds=rng.randint(60, 3600)),
                       rng.choice(REFERERS), rng.choice(UAS), rng.choice(COUNTRIES))
                      for _ in range(rng.randint(1, MAX_CLICKS))]
            # UTC 00-03h is the day before in New York (EDT and EST)
            if not any(at.hour < 4 for at, *_ in seeded):
                at, *rest = seeded[0]
                at = at.replace(hour=rng.randint(0, 3))
                seeded[0] = (at if at < w.now - timedelta(minutes=1) else at - timedelta(days=1), *rest)
            link_rows.append((aid, f"{c['name']} link {k}", slug, f"https://linktr.ee/slop{aid}/{k}", ts(created),
                              sorted(seeded, key=lambda x: x[0]), False))
        if hot_per_day > 0:
            step = 86_400 / hot_per_day
            day0 = w.now.replace(hour=0, minute=0, second=0)
            last = w.now - timedelta(minutes=1)
            hot = ((at, *HOT_MIX[(d * hot_per_day + j) % len(HOT_MIX)])
                   for d in range(HOT_DAYS) for j in range(hot_per_day)
                   for at in (day0 - timedelta(days=d) + timedelta(seconds=j * step + step / 2),) if at < last)
            link_rows.append((aid, f"{c['name']} hot", str(SLUG_BASE + ci * 1000 + 999),
                              f"https://linktr.ee/slop{aid}/hot", ts(w.now - timedelta(days=HOT_DAYS + 1)), hot, True))
        rows, live = [], []
        for k in range(campaigns):
            cid = CAMPAIGN_ID_BASE + ci * 1000 + k
            created = w.now - timedelta(days=80 * (campaigns - k) / campaigns, seconds=rng.randint(0, 3600) + k)
            zero = k % 4 == 3
            ended = k == 1
            rows.append({"id": cid, "campaignCode": 1000 + k, "campaignName": f"{c['name']} OF link {k}",
                         "countTransitions": 0, "countSubscribers": 0, "createdAt": _of_time(created),
                         "endDate": (created + timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S") if ended else None,
                         "isDeleted": ended})
            if not zero:
                live.append(cid)
            out["claimers"][cid] = []
        fans = list(w.data["fans"][aid])
        rng.shuffle(fans)
        who.update({f["id"]: {"id": f["id"], "name": f["name"], "username": f["username"]} for f in fans})
        start = {r["id"]: datetime.fromisoformat(r["createdAt"][:19]) for r in rows}
        claimers = fans[:min(claimed, len(fans))]
        bystanders = fans[len(claimers):len(claimers) + max(2, claimed // 10)]
        mine: dict[int, list[datetime]] = {f["id"]: [] for f in claimers + bystanders}
        for f in claimers:
            for cid in rng.sample(live, rng.randint(1, min(3, len(live)))):
                out["claimers"][cid].append(f["id"])
                mine[f["id"]].append(start[cid])
        big = out["claimers"][live[0]]
        for j in range(max(0, BIG_CLAIMERS - len(big))):
            fid = FAN_ID_BASE + ci * 1_000_000 + SILENT_ID_OFFSET + j
            who[fid] = {"id": fid, "name": f"Free fan {j}", "username": f"u{fid}"}
            big.append(fid)
        rng.shuffle(big)
        for f in claimers + bystanders:
            lo = (min(mine[f["id"]]) if mine[f["id"]] else w.now - timedelta(days=60)) - timedelta(days=10)
            for _ in range(rng.randint(2, 8)):
                at = lo + timedelta(seconds=rng.randint(0, int((w.now - lo).total_seconds()) - 60))
                gross = rng.choice((500, 999, 1500, 2500, 4999, 10000))
                if rng.random() < 0.05:
                    msg_id += 1
                    kind, status, net, pid, mid, source = rng.choice(("tip", "ppv")), "cleared", None, None, msg_id, "ws"
                else:
                    tx_id += 1
                    kind, status, net, pid, mid, source = (rng.choice(KINDS), rng.choice(STATUSES),
                                                           round(gross * 0.8), str(tx_id), None, "ledger")
                tx_rows.append((aid, f["id"], kind, gross, "USD", ts(at), ts(w.now), pid, mid, status, net,
                                None if net is None else gross - net, None if net is None else 0, source))
                out["tx"].append((aid, f["id"], kind, gross, net, at, status))
        for r in rows:
            fids = out["claimers"][r["id"]]
            r["countSubscribers"] = len(fids)
            r["countTransitions"] = len(fids) * rng.randint(3, 10) + rng.randint(0, 50)
        rows.reverse()
        out["campaigns"][aid] = rows

    con = w.sql()
    try:
        with con:
            for aid, name, slug, target, created, seeded, is_hot in link_rows:
                lid = con.execute("INSERT INTO tracking_links(account_id, name, slug, target_url, click_count, "
                                  "created_at) VALUES (?,?,?,?,?,?)", (aid, name, slug, target, 0, created)).lastrowid
                by_key: Counter = Counter()

                def rows(lid=lid, seeded=seeded, by_key=by_key):
                    for n, (at, (ref, ref_l), (ua, ua_l), country) in enumerate(seeded):
                        by_key[(at.strftime(HOUR), label(country), ua_l, ref_l)] += 1
                        old = n % 17 == 0
                        yield lid, ts(at), ref, ua, f"203.0.113.{n % 254 + 1}", country, None if old else ua_l, None if old else ref_l

                con.executemany("INSERT INTO tracking_clicks(tracking_link_id, clicked_at, referer, user_agent, ip, "
                                "country, in_app, ref) VALUES (?,?,?,?,?,?,?,?)", rows())
                con.execute("UPDATE tracking_links SET click_count = ? WHERE id = ?", (by_key.total(), lid))
                out["links"].append({"id": lid, "account_id": aid, "name": name, "slug": slug, "target": target,
                                     "hot": is_hot, "seeded": by_key})
            con.executemany(
                "INSERT INTO transactions(account_id, fan_id, kind, amount_cents, currency, occurred_at, ingested_at, "
                "provider_transaction_id, message_id, status, net_cents, fee_cents, vat_cents, source) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", tx_rows)
    finally:
        con.close()
    of_claimers = {str(cid): [who[fid] for fid in fids] for cid, fids in out["claimers"].items()}
    (tmp / "of-campaigns.json").write_text(json.dumps({"latency_s": OF_LATENCY_S, "accounts": out["campaigns"],
                                                       "claimers": of_claimers}))
    (tmp / "of-me.json").write_text(json.dumps({"latency_s": OF_LATENCY_S}))
    w.data["tracking_campaigns"] = out
    return out
