"""Sales attribution's break-it-once faults: lib/faults.py merges `register(Fault)` into FAULTS.

Each patches a real product function inside the throwaway relay (lib/relay.py applies it in
`_wire`, before the app's startup installs the credit triggers). The check names are defined
here and imported by scenarios/2026-10-27-sales-attribution-tips-ppv.py, so a target can never
name a check that does not exist.
"""
from __future__ import annotations

TIP_LEDGER = ("every standalone chat tip (ledger only, no message) credited to the last human chatter within "
              "the window (Sales records)")
TIP_AFTER = "a chatter whose only reply came after the tip or purchase never takes its credit (Sales records)"
TIP_WS = "every WS chat tip credited to the last human chatter within the window (Sales records)"
PPV = ("every PPV purchase (WS unlock and ledger 'Payment for message') credited to the last human chatter "
       "within the window, not its sender (A's PPV bought after B chatted: B)")
TOTALS = ("Employee reports: each Employee's revenue == its expected credits summed to the cent, "
          "Unattributed included")
STAMP = "every chatter reply is one outbound row stamped with its own chatter's Employee (thread read)"
WINDOW = ("Converters window 1 h (saved through the route): a tip 59 min after the last chatter credits them, "
          "61 min after credits nobody (window specials)")
AUTO = ("Automation and mass sends are never a touch: A then Automation or a mass send credits A, Automation "
        "alone credits nobody (specials)")
WINDOW330 = ("Converters window changed to 3 h 30 min through the route (read back): every sale credited to the "
             "last human chatter within it (Sales records and Employee reports)")
SENDER = ("Messages by Message sender: a linked sale credits its message's sender (A's PPV bought after B "
          "chatted: A; a WS tip: nobody), a ledger tip keeps Converters (Sales records and Employee reports)")


def _patch_triggers(name: str, old: str, new: str) -> None:
    import tx_rollup as tr

    hit = 0
    for k, body in list(tr.TRIGGERS.items()):
        if old in body:
            tr.TRIGGERS[k] = body.replace(old, new)
            hit += 1
    if not hit:
        raise SystemExit(f"slop: {name} matched no trigger (tx_rollup.converter_lookback changed?)")


def _converters_first_chatter() -> None:
    """The Converters lookback picks the FIRST human chatter's send of its span instead of the
    last (bug class: a flipped ORDER BY). Only `tx_rollup.converter_lookback`'s text in the
    credit triggers changes (installed at startup by `tx_rollup.ensure`, which replaces a
    trigger whose text changed); the linked sender and the rollups are the product's own."""
    _patch_triggers("converters-first-chatter", "ORDER BY m.created_at DESC, m.message_id DESC LIMIT 1",
                    "ORDER BY m.created_at ASC, m.message_id ASC LIMIT 1")


def _converters_counts_automation() -> None:
    """Every outbound send with an Employee is a touch (bug class: the human-chatter filter
    dropped): Automation's sends and mass sends can be the last touch. Only the lookback's
    `tx_rollup.human_send` text in the credit triggers changes."""
    import tx_rollup as tr

    full = tr.human_send("m", planner_hint=True)
    keep = "+m.direction = 'out' AND m.sent_by_employee_id IS NOT NULL"
    assert full.startswith(keep), full
    _patch_triggers("converters-counts-automation", full, keep)


def _converters_window_ignored() -> None:
    """The read path ignores the Agency's Converters window and keeps the default 1 h (bug
    class: the saved setting never reaches the per-sale test): `tx_rollup.within_window`
    answers for CONVERTERS_WINDOW_DEFAULT_S whatever window it is given."""
    import tx_rollup as tr

    real = tr.within_window
    tr.within_window = lambda occurred_at, converter_at, window_s: real(
        occurred_at, converter_at, tr.CONVERTERS_WINDOW_DEFAULT_S)


def _chatter_send_unstamped() -> None:
    """A chatter's send loses its Employee (bug class: the X-Employee-Id / chatter-mirror
    resolution dropped): `employees.resolve_outbound_employee_id` answers None for a
    chatter session, so `attribution.write_outbound_attribution` writes the row with
    `sent_by_employee_id` NULL (its chatter branch). Owner and automation sends are the
    product's own."""
    import employees

    real = employees.resolve_outbound_employee_id

    async def unstamped(request, account_id):
        from chatters import get_request_chatter
        if employees.get_request_user() is None and get_request_chatter() is not None:
            return None
        return await real(request, account_id)

    employees.resolve_outbound_employee_id = unstamped


def register(Fault) -> dict:
    return {
        # slop/run sales-attribution --break (the scenario's FAULT)
        "converters-first-chatter": Fault(_converters_first_chatter, (TIP_LEDGER, TIP_WS, PPV, TOTALS, WINDOW330)),
        # slop/run sales-attribution --break --fault=<name>
        "converters-counts-automation": Fault(_converters_counts_automation, (AUTO, TOTALS, WINDOW330)),
        "converters-window-ignored": Fault(_converters_window_ignored, (WINDOW330,)),
        "chatter-send-unstamped": Fault(_chatter_send_unstamped,
                                        (STAMP, PPV, TIP_LEDGER, TIP_WS, TOTALS, WINDOW330, SENDER)),
    }
