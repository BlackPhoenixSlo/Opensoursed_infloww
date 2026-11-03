"""Fan-info history: per Creator `per_creator` fans gen_info has something to mine, as the WS pump and the chat
scrape leave them: a `fans` row, 10-16 inbound lines (each >= 20 chars, so every fan clears gen_info's
40-char language-evidence floor) among a few outbound ones, and the `chats` row. Used by
scenarios/2026-11-02-fan-info-sweep.py.

Every fan has `spend_cents` 0 (no paid message, no ledger row): gen_info's thin-history scrape guard leaves him
alone, and his 10+ inbound lines put him past its 8-new-messages gate and ahead of the profile's threaded fans
(<= 6 lines, never past the gate) in the sweep's order. Three roles, by index:
  manual  `language_source='manual'`: an operator pinned `language`; the fake's extract detects ANOTHER language
          (asserted here, else the pin check would be vacuous).
  keep    a `fan_profiles` row from an earlier generation (a month ago, at 2 messages) with nickname / short_bio /
          bullet_points / original_name set, and an extract that returns all four empty. The fans row's
          `generated_nickname` is NULL (a profile written before that column was), so the kept nickname rests on
          the profile upsert alone.
  plain   never profiled; half carry an earlier AI language observation (`language_source='ai'`).
Each fan's extract carries his own marker (letters, unique in the run) in `occupation` / `hobbies` and, for
non-keep fans, `short_bio` / `bullet_points`: a fact on the wrong fan names the fan it came from.

Display names `fi-<creator>-<fan>` are unique per Creator x fan (the fake DeepSeek's only handle on "which fan":
gen_info's prompt carries the display name, never the id) and never a greetable first name (digits), so
gen_info's name hint adds nothing to a nickname. Message ids from MSG_ID_BASE, below the relay's synthetic bands.
"""
from __future__ import annotations

from datetime import timedelta

from . import World, fans as fans_seed, ts

FAN_OFFSET = 500_000            # within a Creator's fans.FAN_ID_BASE band, past any fans.seed size
MSG_ID_BASE = 9_200_000_000_000
LANGS = ("en", "es", "de", "fr", "it", "pt", "nl")   # all in gen_info_plan.KNOWN_LANGS
EVIDENCE_MIN_CHARS = 40         # gen_info_plan.LANG_EVIDENCE_MIN_CHARS (inbound chars before a language is trusted)
KEEP_FIELDS = ("nickname", "short_bio", "bullet_points", "original_name")
LINES_IN = ["just got back from the gym, so tired", "what are you doing this weekend babe",
            "cant stop thinking about your last post", "work was long today, need a distraction",
            "tell me something nobody else knows", "my dog woke me up at six again lol",
            "do you ever travel for shoots or nah", "had pizza for dinner, living my best life",
            "you have the best smile on this whole site", "going camping with my brother next week"]
LINES_OUT = ["hi babe", "how was your day?", "thinking of you", "check your inbox", "you're sweet"]


def tag(n: int) -> str:
    """n as letters (no digits): 'zq' + base 26."""
    s = ""
    while True:
        n, r = divmod(n, 26)
        s = "abcdefghijklmnopqrstuvwxyz"[r] + s
        if n == 0:
            return "zq" + s


def display_name(account_id: str, fan_id: int) -> str:
    return f"fi-{account_id}-{fan_id}"


def _role(k: int) -> str:
    return ("manual", "keep", "plain", "plain")[k % 4]


def seed(w: World, creators: list[dict], per_creator: int) -> dict:
    """Returns {"fans": [{account_id, fan_id, name, role, marker, in_chars, lang_before, source_before, detected,
    extract, kept}], "extracts": {display name: extract}}; also w.data["fan_info_history"]."""
    rng = w.rng("fan_info_history")
    out: list[dict] = []
    frows, mrows, crows, prows = [], [], [], []
    seq = MSG_ID_BASE
    n = 0
    for ci, c in enumerate(creators):
        aid = c["id"]
        for k in range(int(per_creator)):
            fid = fans_seed.FAN_ID_BASE + ci * 1_000_000 + FAN_OFFSET + k
            role, marker = _role(k), tag(n)
            n += 1
            name = display_name(aid, fid)
            detected = rng.choice(LANGS)
            if role == "manual":
                before, source = rng.choice([x for x in LANGS if x != detected]), "manual"
            elif role == "plain" and rng.random() < 0.5:
                before, source = rng.choice(LANGS), "ai"
            else:
                before, source = None, None
            sub_at = w.now - timedelta(days=rng.randint(10, 400))
            frows.append((aid, fid, f"u{fid}", name, None, 0, "[]", 0, 0, "[]", "[]", "[]", "{}", 0, 0, 0, None, None,
                          ts(w.now - timedelta(minutes=rng.randint(1, 5000))), ts(sub_at),
                          ts(w.now + timedelta(days=30)), "active", 0, "idle", 0, 0, "slop", ts(sub_at), ts(w.now),
                          before, source))
            n_in, n_out = rng.randint(10, 16), rng.randint(2, 5)
            dirs = ["in"] * n_in + ["out"] * n_out
            rng.shuffle(dirs)
            t0 = w.now - timedelta(days=rng.randint(2, 30))
            in_chars = 0
            last = None
            for j, d in enumerate(dirs):
                seq += 1
                at = t0 + timedelta(minutes=9 * j)
                body = rng.choice(LINES_IN if d == "in" else LINES_OUT)
                if d == "in":
                    in_chars += len(body)
                mrows.append((aid, fid, seq, d, name if d == "in" else aid, body, "[]", 0, 0, None, None, None,
                              ts(at), ts(at)))
                last = (seq, at, body)
            unread = len(dirs) - max((i + 1 for i, d in enumerate(dirs) if d == "out"), default=0)
            crows.append((aid, fid, last[0], ts(last[1]), last[2], unread))
            kept = None
            if role == "keep":
                kept = {"nickname": f"Rob/Kept {marker}", "short_bio": f"slop kept bio {marker}",
                        "bullet_points": f"- Recent: slop kept {marker}", "original_name": "Rob"}
                gen_at = w.now - timedelta(days=30)
                prows.append((aid, fid, kept["original_name"], 2, 0, kept["nickname"], kept["short_bio"],
                              kept["bullet_points"], ts(gen_at)))
            empty = role == "keep"
            extract = {
                "nickname": "" if empty else f"Sam/{marker}",
                "short_bio": "" if empty else f"slop bio {marker}",
                "bullet_points": "" if empty else f"- Recent: slop {marker}",
                "original_name": "", "real_name": "", "his_age": "", "home_country": "", "home_city": "",
                "occupation": f"slop job {marker}", "hobbies": f"slop hobby {marker}",
                "relationship_status": "", "fetishes": "", "recent_events": [],
                "language": detected,
            }
            if role == "manual":
                # The pin check is vacuous unless gen_info WOULD write this fan's language: past the evidence
                # floor, and a detected language other than the pinned one.
                assert in_chars >= EVIDENCE_MIN_CHARS, (aid, fid, in_chars)
                assert detected != before and detected in LANGS, (aid, fid, before, detected)
            out.append({"account_id": aid, "fan_id": fid, "name": name, "role": role, "marker": marker,
                        "in_chars": in_chars, "n_in": n_in, "lang_before": before, "source_before": source,
                        "detected": detected, "extract": extract, "kept": kept})
    assert any(f["role"] == "manual" for f in out) and any(f["role"] == "keep" for f in out), "no manual/keep fan"
    con = w.sql()
    with con:
        con.executemany(
            "INSERT INTO fans(account_id, fan_id, of_username, of_display_name, avatar_url, is_name_real, recent_events, "
            "likes_boobs, likes_ass, family_names, pets, communication_style, custom_fields, lifetime_spend_cents, is_bot, "
            "turn_counter, last_message_received_at, last_message_sent_at, last_online_at, subscribed_at, "
            "subscription_expires_at, subscription_status, is_followed, "
            "deep_convo_state, deep_convo_skip_level, deep_convo_skip_remaining, source, created_at, updated_at, "
            "language, language_source, tags) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'[]')", frows)
        con.executemany(
            "INSERT INTO messages(account_id, fan_id, message_id, direction, sender_name, body, media_ids, media_count, "
            "price_cents, is_paid, is_tip, purchased_at, is_unsent, is_promise, sent_by_employee_id, created_at, "
            "ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?,0,?,0,0,?,?,?)", mrows)
        con.executemany(
            "INSERT INTO chats(account_id, fan_id, last_message_id, last_message_at, last_message_preview, unread_count, "
            "is_pinned, is_priority, hidden_locally, list_ids) VALUES (?,?,?,?,?,?,0,0,0,'[]')", crows)
        con.executemany(
            "INSERT INTO fan_profiles(account_id, fan_id, original_name, message_count_at_gen, total_spend_at_gen_cents, "
            "nickname, short_bio, bullet_points, last_generated_at, notes_applied_successfully) "
            "VALUES (?,?,?,?,?,?,?,?,?,0)", prows)
    con.close()
    res = {"fans": out, "extracts": {f["name"]: f["extract"] for f in out}}
    w.data["fan_info_history"] = res
    return res
