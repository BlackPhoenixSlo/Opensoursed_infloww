"""Priority mass audiences: per Creator, the OF custom lists a Priority mass message names and
the local rows its exclusions read (automations/priority_mass.py `exclusions`).

Per Creator in `sizes` ({creator id: roster size}; `priced`: the Creators whose run is priced):
  pool       the Creator's seeded fans (seed/fans.py) plus roster fans up to the size, ids
             `fans.FAN_ID_BASE + ci * 1M + EXTRA_OFFSET + k` (past every fans.py id). 80% of them
             get a `fans` row (the roster sync wrote it), the rest are OF-only: the leg's
             cooldown upsert creates theirs.
  OF lists   `include` (2 lists, 70% and 50% of the pool) and `exclude` (1 list, 2%): OF's side,
             returned only (the scenario writes them to of-rosters.json, lib/priority_mass_relay.py).
             Plus OF's `MASSDMEXCLUDE` list (the composer pre-ticks it in Exclude): MASSDM_OF_FRAC of
             the pool (at least MASSDM_OF_MIN), all `include[0]` members on no local exclusion or
             guard row below, drawn from w.rng("priority_mass_audience:massdm_of") (the other
             draws unchanged).
  local      members of the Creator's MASSdmEXCLUDE list (kind 'exclude', system, no OF id, as
             service/lists.py makes it), 1.5% of the pool; global blacklist rows, 0.5%; for a `priced`
             Creator, fans who bought MEDIA_ID (a purchased `vault_sends` row), 1.5%.
  guard      the contact guard's recent history (`messages` rows, as the relay's ingest writes them,
             only for fans with a row): 3% a message out 1-5 h ago, 3% one in 20-90 min ago (both
             excluded: out 6 h / in 2 h), 3% out 7-30 h or in 2.5-12 h ago (not excluded). Plus
             seed/threads.py's own history.
Returns (and puts in w.data["priority_mass_audience"]) per Creator: `pool`, `no_row`, `lists`,
`include`, `exclude` (list ids), `massdm_of` (OF's MASSDMEXCLUDE list id); the local rows are read
back from the DB. Randomness only from w.rng("priority_mass_audience") and its ":massdm_of" stream.
"""
from __future__ import annotations

from datetime import timedelta

from . import World, ts
from .fans import FAN_ID_BASE, FIRST, LAST

EXTRA_OFFSET = 100_000
OF_LIST_BASE = 7_700_000          # OF list ids (automation_relay mints from 6_600_001 up)
MEDIA_ID = 7_100_000_001          # the priced run's vault media
NO_ROW_FRAC = 0.2
MASSDM_OF_FRAC, MASSDM_OF_MIN = 0.05, 5
MSG_ID_BASE = 9_500_000_000_000   # past threads.py's 9e12 history ids, below the fake OF's 9.7e12 sends


def seed(w: World, sizes: dict[str, int], priced: frozenset[str] | set[str] = frozenset()) -> dict[str, dict]:
    rng = w.rng("priority_mass_audience")
    rng_of = w.rng("priority_mass_audience:massdm_of")
    index = {c["id"]: ci for ci, c in enumerate(w.data["creators"])}
    out: dict[str, dict] = {}
    fan_rows, massdm_rows, black_rows, vault_rows, msg_rows = [], [], [], [], []
    seq = MSG_ID_BASE
    for aid, n in sizes.items():
        ci = index[aid]
        pool = [f["id"] for f in w.data["fans"].get(aid, [])][:n]
        extra = [FAN_ID_BASE + ci * 1_000_000 + EXTRA_OFFSET + k for k in range(max(0, n - len(pool)))]
        no_row = []
        for fid in extra:
            if rng.random() < NO_ROW_FRAC:
                no_row.append(fid)
                continue
            sub_at = w.now - timedelta(days=rng.randint(1, 400))
            fan_rows.append((aid, fid, f"u{fid}", f"{rng.choice(FIRST)} {rng.choice(LAST)}.", None, 0, "[]", 0, 0,
                             "[]", "[]", "[]", "{}", 0, 0, 0, None, None, None, ts(sub_at),
                             ts(w.now + timedelta(days=30)), "active", 0, "idle", 0, 0, "slop", ts(sub_at), ts(w.now)))
        pool += extra
        k = max(1, len(pool))

        def pick(frac: float) -> list[int]:
            return sorted(rng.sample(pool, max(1, round(k * frac))))

        lists = [{"id": OF_LIST_BASE + ci * 10 + 1, "name": "slop vip", "members": pick(0.70)},
                 {"id": OF_LIST_BASE + ci * 10 + 2, "name": "slop spenders", "members": pick(0.50)},
                 {"id": OF_LIST_BASE + ci * 10 + 3, "name": "slop do not send", "members": pick(0.02)}]
        massdm, black = pick(0.015), pick(0.005)
        owners = pick(0.015) if aid in priced else []
        nr = set(no_row)
        rowed = [f for f in pool if f not in nr]
        guard = rng.sample(rowed, min(len(rowed), round(len(rowed) * 0.09)))
        g3 = len(guard) // 3
        out_set, in_set = set(guard[:g3]), set(guard[g3:2 * g3])
        for f in guard:
            seq += 1
            if f in out_set:
                d, at = "out", w.now - timedelta(minutes=rng.randint(60, 300))
            elif f in in_set:
                d, at = "in", w.now - timedelta(minutes=rng.randint(20, 90))
            elif rng.random() < 0.5:
                d, at = "out", w.now - timedelta(minutes=rng.randint(7 * 60, 30 * 60))
            else:
                d, at = "in", w.now - timedelta(minutes=rng.randint(150, 12 * 60))
            msg_rows.append((aid, f, seq, d, aid if d == "out" else f"u{f}", "hey you", "[]", 0, 0, None, None, None,
                             ts(at), ts(at)))
        taken = set(massdm) | set(black) | set(owners) | set(guard)
        free = [f for f in lists[0]["members"] if f not in taken]
        lists.append({"id": OF_LIST_BASE + ci * 10 + 4, "name": "MASSDMEXCLUDE", "members": sorted(
            rng_of.sample(free, min(len(free), max(MASSDM_OF_MIN, round(k * MASSDM_OF_FRAC)))))})
        massdm_rows.append((aid, massdm, ts(w.now - timedelta(days=30))))
        black_rows += [(f, "slop: abusive", ts(w.now - timedelta(days=3))) for f in black]
        vault_rows += [(aid, f, MEDIA_ID, 500, ts(w.now - timedelta(days=rng.randint(1, 60)))) for f in owners]
        out[aid] = {"pool": pool, "no_row": no_row, "lists": lists, "include": [x["id"] for x in lists[:2]],
                    "exclude": [lists[2]["id"]], "massdm_of": lists[3]["id"]}
    con = w.sql()
    with con:
        if fan_rows:
            con.executemany(
                "INSERT INTO fans(account_id, fan_id, of_username, of_display_name, avatar_url, is_name_real, "
                "recent_events, likes_boobs, likes_ass, family_names, pets, communication_style, custom_fields, "
                "lifetime_spend_cents, is_bot, turn_counter, last_message_received_at, last_message_sent_at, "
                "last_online_at, subscribed_at, subscription_expires_at, "
                "subscription_status, is_followed, deep_convo_state, deep_convo_skip_level, "
                "deep_convo_skip_remaining, source, created_at, updated_at, tags) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'[]')", fan_rows)
        for aid, members, at in massdm_rows:
            lid = con.execute("INSERT INTO lists(account_id, of_list_id, name, kind, is_system, created_at) "
                              "VALUES (?,NULL,'MASSdmEXCLUDE','exclude',1,?)", (aid, at)).lastrowid
            con.executemany("INSERT INTO list_members(list_id, fan_id, added_at) VALUES (?,?,?)",
                            [(lid, f, at) for f in members])
        con.executemany("INSERT INTO blacklist(fan_id, reason, added_at) VALUES (?,?,?)", black_rows)
        con.executemany("INSERT INTO vault_sends(account_id, fan_id, media_id, price_cents, sent_at, was_purchased) "
                        "VALUES (?,?,?,?,?,1)", vault_rows)
        con.executemany(
            "INSERT INTO messages(account_id, fan_id, message_id, direction, sender_name, body, media_ids, media_count, "
            "price_cents, is_paid, is_tip, purchased_at, is_unsent, is_promise, sent_by_employee_id, created_at, "
            "ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?,0,?,0,0,?,?,?)", msg_rows)
    con.close()
    w.data["priority_mass_audience"] = out
    return out
