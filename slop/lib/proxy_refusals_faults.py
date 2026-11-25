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
    import proxy_health

    proxy_health.still_flapping = lambda label: False
    proxy_health.herd_guarded = lambda label: False


def _refusal_window_blind() -> None:
    import proxy_health

    proxy_health._sample = lambda label, refused: None


def register(Fault) -> dict:
    return {
        "flap-knob-ignored": Fault(_flap_knob_ignored,
                                   (C_FLAP_MOVES, C_STANDBY_NO_FAILBACK, C_HYSTERESIS, C_CLEARS)),
        "refusal-window-blind": Fault(_refusal_window_blind,
                                      (C_RATE_SHOWN, C_UI_TEXT, C_FLAP_MOVES, C_STANDBY_NO_FAILBACK, C_HYSTERESIS,
                                       C_CLEARS)),
    }
