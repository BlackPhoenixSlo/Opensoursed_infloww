from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import ModuleType

import accounts
import fansly_backend
from side_effect_gate import refusal


class Lack(str, Enum):
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
    login: str
    free_follow: bool = False
    bind_login_proxy: bool = True


ONLYFANS = Platform("onlyfans", "OF", "latest.json", None, frozenset(), login="remote_login_onlyfans")
FANSLY = Platform("fansly", "Fansly", fansly_backend.SESSION_FILENAME, fansly_backend,
                  frozenset(Lack), login="remote_login_fansly", free_follow=True, bind_login_proxy=False)

ALL: tuple[Platform, ...] = (ONLYFANS, FANSLY)
KEYS: tuple[str, ...] = tuple(p.key for p in ALL)
SESSION_FILES: tuple[str, ...] = tuple(p.session_file for p in ALL)

_BY_KEY = {p.key: p for p in ALL}


def get(key: object) -> Platform:
    return _BY_KEY.get(key, ONLYFANS) if isinstance(key, str) else ONLYFANS


def for_account(aid: str) -> Platform:
    return get(accounts.get_platform(aid))


def refusal_for_account(aid: str, name: str) -> str | None:
    backend = for_account(aid).backend
    return None if backend is None else refusal(backend.Shim, name)


def backends() -> tuple[ModuleType, ...]:
    return tuple(p.backend for p in ALL if p.backend is not None)
