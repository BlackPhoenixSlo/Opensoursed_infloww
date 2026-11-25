from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import ModuleType

import accounts
import fansly_backend


class Lack(str, Enum):
    FOCUS = "FOCUS"
    REFERRALS = "REFERRALS"
    WALL_MEDIA = "WALL_MEDIA"
    SERVER_SCHEDULE = "SERVER_SCHEDULE"
    NEAR_SCHEDULE_MEDIA = "NEAR_SCHEDULE_MEDIA"
    HISTORY_UNREAD_GATE = "HISTORY_UNREAD_GATE"
    UNREAD_TOTAL = "UNREAD_TOTAL"
    SHARED_REFRESH = "SHARED_REFRESH"


@dataclass(frozen=True)
class Platform:
    key: str
    label: str
    session_file: str
    backend: ModuleType | None
    lacks: frozenset[Lack]
    free_follow: bool = False


ONLYFANS = Platform("onlyfans", "OF", "latest.json", None, frozenset())
FANSLY = Platform("fansly", "Fansly", fansly_backend.SESSION_FILENAME, fansly_backend,
                  frozenset(Lack), free_follow=True)

ALL: tuple[Platform, ...] = (ONLYFANS, FANSLY)
KEYS: tuple[str, ...] = tuple(p.key for p in ALL)
SESSION_FILES: tuple[str, ...] = tuple(p.session_file for p in ALL)

_BY_KEY = {p.key: p for p in ALL}


def get(key: str | None) -> Platform:
    return _BY_KEY.get(key or "", ONLYFANS)


def for_account(aid: str) -> Platform:
    return get(accounts.get_platform(aid))


def backends() -> tuple[ModuleType, ...]:
    return tuple(p.backend for p in ALL if p.backend is not None)
