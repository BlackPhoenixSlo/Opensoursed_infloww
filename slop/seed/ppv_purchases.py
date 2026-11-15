"""PPV purchases the mirror has not seen yet: the Creator's priced outbound copy, still unpaid (`messages`, as the
scrape or a mass send's echo writes it; `mass_run_id` when it is a copy of one), and OnlyFans' notification of the
purchase on the Creator's `type=purchases` feed (lib/of_wire.py `purchases[uid]`, newest first), from which a
purchases poll (service/purchase_notifications.py) flips the copy paid: `MESSAGE_LINK` names the fan and the exact
message bought."""
from __future__ import annotations

from datetime import datetime

from . import World, ts


def unpaid_copies(w: World, rows: list[tuple[str, int, int]], *, price_cents: int, at: datetime, now: datetime,
                  body: str = "set", mass_run_id: int | None = None) -> None:
    """One unpaid priced outbound copy per (Creator, fan, OF message id) in `rows`, sent `at`."""
    con = w.sql()
    with con:
        con.executemany(
            "INSERT INTO messages(account_id, fan_id, message_id, direction, sender_name, body, media_ids, media_count,"
            " price_cents, is_paid, is_tip, purchased_at, is_unsent, is_promise, sent_by_employee_id, mass_run_id,"
            " created_at, ingested_at) VALUES (?,?,?,'out','Creator',?,'[]',1,?,0,0,NULL,0,0,NULL,?,?,?)",
            [(aid, fan, mid, body, price_cents, mass_run_id, ts(at), ts(now)) for aid, fan, mid in rows])
    con.close()


def note(nid: int, fan: int, mid: int, *, cents: int, at: datetime) -> dict:
    """OF's purchases-feed item for `fan` buying message `mid` for `cents` at `at` (naive UTC)."""
    return {"id": nid, "type": "paided_message", "subType": "subscriber_pay_for_chat_message",
            "createdAt": at.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "replacePairs": {"{MESSAGE_LINK}": f"/my/chats/chat/{fan}?firstId={mid}",
                             "{AMOUNT}": f"${cents / 100:.2f}", "{NAME}": f"Fan {fan}"},
            "user": {"id": fan}}
