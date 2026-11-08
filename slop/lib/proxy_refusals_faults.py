"""A flapping pool proxy's faults (lib/faults.py merges `register(Fault)` into FAULTS): the refusal
window and the flap knob's stay rule in service/proxy_health.py, patched inside the relay. The check
names live here and scenarios/2026-11-05-proxy-refusals.py imports them, so a target never names a
missing check.

  flap-knob-ignored      `still_flapping()` + `herd_guarded()` always False: no hysteresis, no herd guard; FlapBad fires,
                         but any answer or passing recheck brings the proxy straight back
  refusal-window-blind   every attempt's outcome dropped before the window: refusals always 0 of 0
"""
from __future__ import annotations

C_RATE_SHOWN = ("refusing proxies: GET /admin/proxies shows the Agency owner the share alone (no counts), pct within "
                "the share's binomial band over the fake proxy's >= 20 CONNECTs; the clean pool proxies pct 0")
C_UI_TEXT = "Proxies page: the refusing custom proxy's row reads 'refusing N% (M min)'"
C_FLAP_MOVES = ("flap knob on: the refusing pool proxy goes bad and its Creators move to answering pool proxies "
                "within budget; no send lost or duplicated, only proxy_unreachable 502s, interactive p95 in budget")
C_STANDBY_NO_FAILBACK = ("after the move, refusals stop: the moved-away pool proxy comes back as standby within "
                         "budget and nobody moves back (bindings unchanged since the move)")
C_HYSTERESIS = ("custom proxy flap-bad at 30 %, then refusing 16 % through phase B: never back up "
                "meanwhile, still bad at the end (bad_reason flapping, badge 'proxy refusing', pct >= 10)")
C_CLEARS = "custom proxy steadily bad when its refusals stop: it leaves bad within budget, badge gone"


def _flap_knob_ignored() -> None:
    """The stay rule never holds (bug class: hysteresis / herd guard dropped or mis-wired): FlapBad marks the
    proxy bad, the next answer or passing recheck brings it back, so a proxy refusing a third of its calls
    flips bad/up and the two failed rechecks a move needs rarely line up."""
    import proxy_health

    proxy_health.still_flapping = lambda label: False
    proxy_health.herd_guarded = lambda label: False


def _refusal_window_blind() -> None:
    """The window records nothing (bug class: telemetry never fed, e.g. `_attempt` not wired into
    `_proxy_retry`): every refusals read is 0 of 0, so the rate is never shown and never flaps."""
    import proxy_health

    proxy_health._sample = lambda label, refused: None


def register(Fault) -> dict:
    return {
        # slop/run proxy-refusals --break (the scenario's FAULT); targets = what measurably went red
        "flap-knob-ignored": Fault(_flap_knob_ignored,
                                   (C_FLAP_MOVES, C_STANDBY_NO_FAILBACK, C_HYSTERESIS, C_CLEARS)),
        # slop/run proxy-refusals --break --fault=refusal-window-blind
        "refusal-window-blind": Fault(_refusal_window_blind,
                                      (C_RATE_SHOWN, C_UI_TEXT, C_FLAP_MOVES, C_STANDBY_NO_FAILBACK, C_HYSTERESIS,
                                       C_CLEARS)),
    }
