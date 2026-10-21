"""service/automations/_customs.py — the owed-custom ledger.

THE PRODUCT, for a creator whose vault is bought out: the fan tips and gets back
a VOICE NOTE made for him. Fulfilment is MANUAL by operator ruling — a human
records it and sends it. So the system has exactly four jobs, and none of them is
delivery:

    notice the money → make it unmissable → stop selling → let a human clear it

WHERE "OWED" LIVES: `fans.customs_owed_at`
------------------------------------------
One nullable timestamp. Set to the moment the qualifying tip landed; NULL means
nothing is owed. `is_owed` reads that column and nothing else, and the operator
sees the queue on /customs.

⚠️ IT USED TO BE A " Custom" SUFFIX ON `custom_nickname`, AND THAT SILENTLY DID
NOT WORK. The reasoning was sound — the operator lives in the OnlyFans app, where
a nickname renders next to the fan's name, so a marker there is seen without
anyone deciding to go and look. The problem is that `custom_nickname` has four
other writers. `welcome_chatter_for_info._maybe_push_nickname`, reached on EVERY chat
tick, rebuilds the name from structured facts via `names.build_structured_nickname`
— which knows nothing about any marker and therefore drops it, then pushes the
shortened name to OnlyFans AND upserts it back into our own row. The chat engine
ran every 60s. customs_watch runs every 900s. So the ledger was erased about a minute
after it was written, on both surfaces, and prod confirms the outcome exactly:
204 watcher runs, zero fans ever marked, in a feature that had been live for days.

A column has no other writers, so none of that is expressible.

WHAT COUNTS AS AN ORDER
-----------------------
A BURST of DM tips (`kind='tip'`, ≤ `BURST_MINUTES` apart) totalling ≥ $50
(`MIN_CENTS`) that actually cleared — fans stack tips to reach a price, so
$30+$30 is one $60 order, and `orders_per_fan` below is the ONE function that
decides. The QUOTED band stays $100-$200 (`ASK_MIN_CENTS`); the watch just also
catches the lowball the chatter never asked for. Not `tip_post` — a $200 tip
on a post is a man being generous about a photo, not a man ordering a voice note.
Not a quantity either: the transcript that priced this feature (2026-07-31, a
male account — $200 tipped at 10:51, one voice note delivered at 14:47) shows
the amount encoding LENGTH, not count — one burst is one custom, however many
rows it took him to pay it.

"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # annotation only — this module stays import-light at runtime
    from db.models import Fan

log = logging.getLogger("of-relay.automation.customs")

# The WATCH floor: the smallest DM tip that counts as a custom ORDER. Operator
# ruling 2026-08-19: track $50 and above. Fans lowball under the quoted opener —
# the burst data in `customs_api` is full of $80/$54/$50 halves — and a tip the
# watch ignores is a man who paid and is silently never delivered. This is the
# TRACKING floor only; the figure the model QUOTES is `ASK_MIN_CENTS` below.
MIN_CENTS = 5_000

# The floor of the band the chatter may QUOTE. Both $100 and $200 appear on the
# live male accounts (7 and 8 times respectively); the transcript shows $100 is
# the opener the chatter counters, but it does get accepted, so it is the ask.
# ⚠️ MUST stay >= `MIN_CENTS`: every figure the model may name has to pass
# `orders_per_fan`, or a fan pays the quoted price and is never marked.
ASK_MIN_CENTS = 10_000

# Enforced at import, not only in a test suite — a violating edit fails the
# process, not the next test run. (The per-account `min_cents` override can
# still breach this at runtime; customs_watch warns loudly when it does.)
assert ASK_MIN_CENTS >= MIN_CENTS, \
    "a quotable price the watch refuses to book is a paid, unmarked custom"

# Only a DM tip. `tip_post`/`tip_stream` are generosity, not an order.
ORDER_KINDS = ("tip",)

# Transaction states that mean the money is REAL. Mirrors
# the removed AI Chatter engine's tip sum deliberately — a tip is either an order everywhere
# or nowhere. 'pending' counts: it is money in flight, and treating it as an
# order is the safe direction, because the fan believes he ordered.
#
# ⚠️ THIS LIVES HERE, BESIDE `ORDER_KINDS`, BECAUSE THE QUEUE AND THE WATCH USED
# TO DISAGREE ABOUT IT. `customs_watch` has always filtered on it; `customs_api`
# never did, so a charged-back tip was excluded from MARKING a fan owed and
# included in the AMOUNT displayed to the operator — work shown as paid for that
# the platform had taken back. Prod carries 8 charged-back tips, three of them at
# or above the order floor. Worse, a refunded $60 stacked onto a real $60 sums
# past the floor in `orders_per_fan` and manufactures a $120 order that was never
# paid at all. One spelling, imported by both, so they cannot drift again.
SETTLED_STATUSES = ("cleared", "pending")


def resolve_floor(min_cents) -> int:
    """The cents floor an account treats as an ORDER: the rule's `min_cents`
    override, else the global `MIN_CENTS`. THE one spelling of that rule —
    the watch, the live tip hook and the /customs queue (via `orders_per_fan`)
    all resolve through it, so they can never disagree about what counts.

    Why the floor is PER ACCOUNT at all: what a $100 DM tip MEANS is an
    account-level fact, not a global one — on the male accounts it demonstrably
    is an order (fan 80000815 said so in as many words), while the female
    accounts took 5 of them last month that were almost certainly generosity.
    One constant cannot be right for both, and getting it wrong in the generous
    direction stops the bot selling to a good fan until a human notices."""
    return MIN_CENTS if min_cents is None else max(1, int(min_cents))


# Fans STACK tips to reach a price. Live example (Amia / 142006425): $200 and
# $100 twenty-five seconds apart, then $150 twenty minutes later — one $450
# order, three rows. Same pattern on 80511815 ($200+$100, 26s apart) and
# 21843747 ($200+$100, 13s).
BURST_MINUTES = 30


def _walk_bursts(rows, min_cents: int | None = None) -> dict[tuple, list[tuple]]:
    """THE burst walk — the ONE definition of "which tips are one order", shared
    by both public functions below so they cannot drift apart.

    (account, fan) → every qualifying burst NEWEST FIRST, as
    (total_cents, anchor_at, anchor_msg_id). `rows` arrive as
    (account_id, fan_id, amount_cents, occurred_at, message_id) ordered
    `occurred_at DESC`, and the walk depends on that ordering.

    A burst is anchored on its NEWEST tip and swallows everything within
    BURST_MINUTES of that anchor. The next row out is not "not an order" — it
    OPENS one, and the walk continues. That last clause is the whole reason this
    is one function: `orders_per_fan` used to DROP the overflow instead of
    opening a burst for it, so on a chain of tips each ≤30 min from the one
    before but spanning more than 30 min end to end, the two functions disagreed
    about how many orders the fan had placed — while a docstring asserted they
    shared a rule. Now they cannot: `orders_per_fan` is this walk's FIRST burst.

    A burst is kept only if its TOTAL clears the floor — see `orders_per_fan`
    for why filtering transactions before summing understates a $60+$60 order.
    A fan with nothing qualifying is absent, not present-and-empty."""
    floor = resolve_floor(min_cents)
    walk: dict[tuple, list[list]] = {}
    for acct, fid, cents, at, msg_id in rows:
        if fid is None or at is None:
            continue
        key = (acct, int(fid))
        cents = int(cents or 0)
        open_burst = walk[key][-1] if key in walk else None
        # Still inside the burst we are accumulating? Add it on. Otherwise this
        # row opens a NEW order rather than being discarded.
        if open_burst is not None and (open_burst[1] - at) <= timedelta(minutes=BURST_MINUTES):
            open_burst[0] += cents
            continue
        walk.setdefault(key, []).append([cents, at, msg_id])
    out: dict[tuple, list[tuple]] = {}
    for key, bursts in walk.items():
        kept = [(int(t), a, m) for t, a, m in bursts if t >= floor]
        if kept:
            out[key] = kept
    return out


def orders_per_fan(rows, min_cents: int | None = None) -> dict[tuple, tuple]:
    """(account, fan) → (total_cents, anchor_at, anchor_msg_id) for the fan's most
    recent ORDER, from rows ordered occurred_at DESC as
    (account_id, fan_id, amount_cents, occurred_at, message_id).

    An ORDER is a BURST of tips, not one tip — see BURST_MINUTES above.

    ⚠️ THE FLOOR IS TESTED ON THE TOTAL, AND THAT IS THE WHOLE POINT. The first
    version filtered each transaction against the floor in SQL and summed what
    survived, which reintroduced the same understatement one layer down: prod is
    full of $200+$80, $200+$50, $150+$80, $100+$54 — the sub-floor half was
    dropped before the sum, so a $280 order displayed as $200. It also made
    $60+$60 invisible entirely, and $120 is a real order.

    So the caller passes EVERY tip in the window and this decides. The floor is a
    question about the ORDER; asking it of each transaction is asking the wrong
    thing about the wrong noun. This is THE definition of "order" — the watch
    (customs_watch.run) marks off it and the /customs queue displays off it, so
    the two can never disagree about whether a fan bought one.

    ⚠️ THE NEWEST BURST ONLY, and a sub-floor newest burst does NOT promote an
    older one into its place. `customs_watch` uses this anchor as the DELIVERY
    CUTOFF, so handing it last week's burst because this week's tip was $20 would
    mark a fan owed off money he was not owed for and clear it against the wrong
    instant. So the walk is asked for UNFILTERED bursts, the newest is taken, and
    the floor is tested on that — which is exactly what this function did before
    the walk was shared with `bursts_per_fan`."""
    floor = resolve_floor(min_cents)
    return {key: bursts[0]
            for key, bursts in _walk_bursts(rows, min_cents=0).items()
            if bursts[0][0] >= floor}


def bursts_per_fan(rows, min_cents: int | None = None) -> dict[tuple, list[tuple]]:
    """(account, fan) → EVERY qualifying order, newest first, as a list of
    (total_cents, anchor_at, anchor_msg_id). `_walk_bursts` unchanged — this IS
    the walk, and `orders_per_fan` is its first element.

    THE BURST RULE IS LITERALLY SHARED NOW, not merely described as shared. It
    used not to be: `orders_per_fan` DROPPED a tip that fell outside the anchor's
    window, while this function let that tip OPEN a new burst, so on a chain of
    tips each ≤30 min from the anchor before it but spanning more than 30 min end
    to end the two disagreed about the fan's order COUNT — with a docstring here
    asserting they agreed. One walk makes the claim true by construction.

    The only difference left is which end of the walk each returns: this one
    keeps every order, `orders_per_fan` keeps the newest.

    ⚠️ THIS IS A SIBLING OF `orders_per_fan`, NOT A REPLACEMENT, AND THAT IS
    DELIBERATE. That function has three callers who want different things, and
    one of them — `customs_watch.run` — uses its anchor as the DELIVERY CUTOFF:
    the newest burst's newest tip, so a second order placed before the first
    shipped extends the wait rather than being cleared by the first delivery.
    Hand the watch a list and it must pick an anchor anyway, and picking the
    oldest reintroduces exactly the false-clear that module was written to end.
    There is also a test pinning the single-burst contract
    (`test_customs_watch.case_an_order_is_the_burst_total_not_the_biggest_tip`).
    So the counting function is a new one, and the marking path is untouched.

    WHY IT EXISTS: `orders_per_fan` returns ONE order per fan, so a man who tips
    $100 on Monday and $100 on Tuesday is shown as owing one $100 voice note.
    The older burst hits neither branch of that loop and is dropped on the floor.
    Worse, it has nowhere else to surface — `customs_api._unmarked` subtracts
    fans who are already owed, so the second order appears on no list at all.
    Measured on the laptop DB: 2 fans, $285 of paid-for work invisible.

    The FLOOR is still tested on each burst TOTAL, for the reason
    `orders_per_fan` documents at length: $60+$60 is a real $120 order, and
    filtering transactions before summing understates it.

    Callers must pass rows ordered `occurred_at DESC` — the burst walk depends
    on it, exactly as `orders_per_fan` does."""
    return _walk_bursts(rows, min_cents)


# ── The ledger. One question and two writes, all over `Fan` ──────────
#
# TYPED, AND THAT IS THE WHOLE GUARD. These took `str | None` when the
# ledger was a nickname suffix. A call site left un-migrated is the failure this
# module most needs to prevent — it would read as "nothing owed" and a man who
# paid would be silently forgotten — so `fan.customs_owed_at` is accessed
# DIRECTLY rather than through `getattr(..., None)`. A stray nickname raises
# AttributeError at the first line it reaches, which is what a broken contract
# should do. There is nothing to remember and no guard to keep in sync.
#
# `mark` and `clear` MUTATE the row and do not commit — the caller owns the
# session, because both callers already have one open for other reasons.


def is_owed(fan: "Fan | None") -> bool:
    """Does this fan have a custom paid for and not yet delivered?

    Reads `fans.customs_owed_at` and nothing else. None → False, so a caller
    holding a fan that may not exist needs no guard of its own."""
    return fan is not None and fan.customs_owed_at is not None


async def owed_fan_ids(account_id) -> set[int]:
    """Every fan on this account with an outstanding custom — the SEND-SIDE brake.

    ⚠️ `is_owed` ABOVE ONLY EVER BOUND THE THREE ENGINES THAT HOLD A `Fan` ROW —
    the removed AI Chatter engine, `welcome_chatter_for_info`, `autoreply`. Those are the engines that TALK. The
    engines that SELL on their own schedule (the removed `ppv_send` and
    `reengage_buyers`) never loaded a Fan before choosing an audience;
    they build an EXCLUDE SET and subtract it. So the brake that stops the chat
    from pitching a second custom did not stop a PPV blast, a tip ask, or a
    re-engagement DM from reaching the same man on the next tick — which is the
    failure this whole feature exists to prevent, arriving by the one door nobody
    had shut.

    Returned as a set for exactly that shape: `excl |= await owed_fan_ids(aid)`.

    THE SET IS TINY AND THAT IS THE POINT. It holds only fans with money taken
    and work outstanding — currently a handful per account, cleared by the
    operator on /customs or by `customs_watch` seeing the voice note go out. It is
    NOT an inferred-state gate: `ppv_send`'s 07-23 ruling bars shrinking a blast
    on CHAT SIGNALS (which cost −86% of sends), and this is not one. It is the
    same distinction that leaves `is_owed` ungated on the seller flag — "we owe
    this man something he paid for" is a fact about money already taken, not a
    selling decision.

    Local imports: this module is deliberately import-light at runtime (see the
    TYPE_CHECKING guard at the top) and every caller already has the DB loaded.
    Mirrors `_common._load_skip_ids`."""
    from sqlalchemy import select

    from db.engine import get_session
    from db.models import Fan

    async with get_session() as s:
        rows = (await s.execute(
            select(Fan.fan_id).where(
                Fan.account_id == str(account_id),
                Fan.customs_owed_at.is_not(None),
            )
        )).all()
    return {int(r[0]) for r in rows}


def mark(fan: "Fan | None", tipped_at: datetime | None = None) -> bool:
    """Record that `fan` is owed a custom, as of `tipped_at`. Returns True when
    this CHANGED something.

    Idempotent: a fan already owed is left exactly as he was, so re-running the
    scanner over a tip it already marked neither moves the "waiting since" clock
    nor reports a second order. The stamp is the TIP's time, not now, because the
    queue sorts and ages by it — stamping `utcnow()` on every sweep would reset
    every fan's wait to zero every 15 minutes.

    ⚠️ THAT IDEMPOTENCE ALSO MEANS THE LEDGER CANNOT COUNT, AND IT IS UNDER-
    REPORTING RIGHT NOW. The module docstring says "Two customs means two
    separate tips", but one nullable timestamp cannot hold two. Verified on prod
    2026-08-18: on one account a fan made THREE qualifying tips ($180 on 08-14,
    $200 on 08-14, $150 on 08-16 — $530 total) and `customs_owed_at` still holds
    only the first; a second fan there likewise ($100 x3). Both men are
    owed three voice notes and the operator queue shows one each, and clearing
    the debt once blanks all three. Counting orders needs its own rows, not a
    second column."""
    if fan is None or is_owed(fan):
        return False
    fan.customs_owed_at = tipped_at or datetime.utcnow()
    return True


def clear(fan: "Fan | None", cleared_at: datetime | None = None) -> bool:
    """Settle `fan`'s owed custom. Returns True when this CHANGED something.

    Stamps `customs_cleared_at` as well as blanking `customs_owed_at`: the second
    is what stops the send-side brake and the queue, the first is what stops
    `customs_watch` re-marking the same tip on its next sweep. Both, or the
    operator's "Sent" click undoes itself in 15 minutes."""
    if fan is None or not is_owed(fan):
        return False
    fan.customs_owed_at = None
    fan.customs_cleared_at = cleared_at or datetime.utcnow()
    return True


# (`qualifies`, the old single-transaction order test, is gone: the ORDER is a
# burst, and `orders_per_fan` above is the one function that books it. The
# per-account-floor rationale lives on `resolve_floor`.)


# ── Delivery ─────────────────────────────────────────────────────────
# The operator clears the debt by hand on /customs, and that stays the authority.
# But a hand-clear that is FORGOTTEN leaves the account permanently unable to sell
# to its best fan — the brake below has no timeout, deliberately, because a
# timeout would resume selling to a man who never got what he paid for. So
# delivery is also detected, and the two paths agree: whichever happens first wins.
#
# AUDIO ONLY. The product is a voice note (operator ruling 2026-08-05: *"we should
# sell only voice messages"*), so a voice note is the only thing that can be it.
# That is also rare and deliberate enough to be a trustworthy signal: 9 outbound
# audio messages across the whole platform, ever.
#
# ⚠️ A FREE VIDEO USED TO COUNT TOO, for a "later, short video" product that is not
# being built. It was a live false-clear: `customs_watch`'s clear loop falls back
# to the sweep window when the originating tip has aged out, so ANY free outbound
# video in the last 72 hours settled a debt incurred days earlier — a mass send, a
# tip_reward freebie, or a chatter being nice. Narrowing the product narrows the
# discriminator, and both get safer at once.
#
# A photo never counts. If the product ever grows past audio this needs a
# discriminator that is not price: free photos and free videos are both common,
# so a second type here would have to arrive with a predicate, not alone.
#
# There is deliberately NO `is_delivery()` helper beside this tuple. There was
# one, and once the product narrowed to audio it had decayed into
# `media_type == "audio"` carrying two parameters it ignored — while its only
# caller ALREADY filtered `MessageMedia.type.in_(DELIVERY_TYPES)` in SQL. The
# Python re-test could not answer anything the query had not already decided.
# One expression of the rule, in the query that reads the rows.
DELIVERY_TYPES = ("audio",)
