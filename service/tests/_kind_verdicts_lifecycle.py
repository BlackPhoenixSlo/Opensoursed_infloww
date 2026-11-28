from __future__ import annotations

from _kind_verdict_seeds import FAN, LAPSED, SEEDS as _BASE_SEEDS

VERDICTS = {
    "fansly": {
        "birthday_message": {"run": "same"},
        "expired_message": {"run": "gated:platform_lacks:lapse_detection",
                            "forced": "gated:platform_lacks:lapse_detection",
                            "dry": "gated:platform_lacks:lapse_detection"},
        "expiry_message": {"run": "gated:platform_lacks:renewal_state",
                           "forced": "gated:platform_lacks:renewal_state",
                           "dry": "gated:platform_lacks:renewal_state"},
        "resubscribe_message": {"run": "gated:platform_lacks:return_detection",
                                "forced": "gated:platform_lacks:return_detection",
                                "dry": "gated:platform_lacks:return_detection"},
    },
    "onlyfans": {
        "birthday_message": {"run": "same"},
        "expired_message": {"run": "same", "forced": "same", "dry": "same"},
        "expiry_message": {"run": "same", "forced": "same", "dry": "same"},
        "resubscribe_message": {"run": "same", "forced": "same", "dry": "same"},
    },
}


def _paths(fan: int) -> dict:
    return {"run": {}, "forced": {"force_ids": [fan]}, "dry": {"dry_run": True}}


PAYLOADS = {
    "birthday_message": {"run": {}},
    "expired_message": _paths(LAPSED),
    "expiry_message": _paths(int(FAN)),
    "resubscribe_message": _paths(int(FAN)),
}

_SENT = ("table:chats", "table:fans", "table:lifecycle_message_claims", "table:messages")
_FOLLOWED = ("follow_user", "table:follow_log", "table:follow_ping_state")
_CRAWLED = ("table:subscriber_crawl", "table:subscriber_snapshot")


def _effects(*parts: str) -> tuple[str, ...]:
    return tuple(sorted(parts))


_SENT_OF = _effects("send_message", *_SENT)
ONE_SEND = {"fansly": _effects("POST /message", *_SENT), "onlyfans": _SENT_OF}

SAME_EFFECTS = {
    "fansly": {"birthday_message": {"run": ONE_SEND["fansly"]}},
    "onlyfans": {
        "birthday_message": {"run": _SENT_OF},
        "expired_message": {"run": _effects(*_SENT_OF, *_FOLLOWED, *_CRAWLED),
                            "forced": _effects(*_SENT_OF, *_FOLLOWED),
                            "dry": _CRAWLED},
        **{kind: {"run": _effects(*_SENT_OF, *_CRAWLED), "forced": _SENT_OF,
                  "dry": _CRAWLED}
           for kind in ("expiry_message", "resubscribe_message")},
    },
}


SEEDS = {(kind, branch): _BASE_SEEDS[(kind, "run")] for kind, branches in PAYLOADS.items() for branch in branches}
