from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import ModuleType

import accounts
import fansly_backend
from side_effect_gate import PLATFORM_LACKS_PREFIX, PLATFORM_UNKNOWN_PREFIX, refusal


class Lack(str, Enum):
    REFERRALS = "REFERRALS"
    WALL_MEDIA = "WALL_MEDIA"
    SERVER_SCHEDULE = "SERVER_SCHEDULE"
    NEAR_SCHEDULE_MEDIA = "NEAR_SCHEDULE_MEDIA"
    HISTORY_UNREAD_GATE = "HISTORY_UNREAD_GATE"
    UNREAD_TOTAL = "UNREAD_TOTAL"
    SHARED_REFRESH = "SHARED_REFRESH"
    TIP_LEDGER = "TIP_LEDGER"
    PURCHASE_LINKAGE = "PURCHASE_LINKAGE"
    RENEWAL_STATE = "RENEWAL_STATE"
    LAPSE_DETECTION = "LAPSE_DETECTION"
    RETURN_DETECTION = "RETURN_DETECTION"
    PROMOTION_TYPE = "PROMOTION_TYPE"


def lack_reason(lack: Lack) -> str:
    return f"{PLATFORM_LACKS_PREFIX}{lack.value.lower()}"


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
    list_page: int | None = None
    confirms_empty_active_roster: bool = False
    retry_unconfirmed_list_adds: bool = False

    @property
    def list_member_limit(self) -> int | None:
        return self.list_page - 1 if self.list_page is not None else None


@dataclass(frozen=True)
class UnknownPlatform(Platform):
    label: str = "Unknown platform"
    session_file: str = ""
    backend: ModuleType | None = None
    lacks: frozenset[Lack] = frozenset(Lack)
    login: str = ""


class UnknownPlatformKey(ValueError):
    def __init__(self, key: str):
        self.key = key
        self.reason = unknown_reason(key)
        super().__init__(self.reason)


def unknown_reason(key: str) -> str:
    return f"{PLATFORM_UNKNOWN_PREFIX}{key}"


ONLYFANS = Platform("onlyfans", "OF", "latest.json", None, frozenset(), login="remote_login_onlyfans")
FANSLY = Platform("fansly", "Fansly", fansly_backend.SESSION_FILENAME, fansly_backend,
                  frozenset(Lack), login="remote_login_fansly", free_follow=True, bind_login_proxy=False,
                  list_page=fansly_backend.Shim.LIST_PAGE, confirms_empty_active_roster=True,
                  retry_unconfirmed_list_adds=True)

ALL: tuple[Platform, ...] = (ONLYFANS, FANSLY)
KEYS: tuple[str, ...] = tuple(p.key for p in ALL)
SESSION_FILES: tuple[str, ...] = tuple(p.session_file for p in ALL)

_BY_KEY = {p.key: p for p in ALL}


def get(key: object) -> Platform:
    if not isinstance(key, str) or not (norm := key.strip().lower()):
        return ONLYFANS
    return _BY_KEY.get(norm) or UnknownPlatform(key)


def _known(p: Platform) -> Platform:
    if isinstance(p, UnknownPlatform):
        raise UnknownPlatformKey(p.key)
    return p


def require(key: object) -> Platform:
    return _known(get(key))


def for_account(aid: str) -> Platform:
    return get(accounts.get_platform(aid))


def require_account(aid: str) -> Platform:
    return _known(for_account(aid))


def lack_refusal(aid: str, lack: Lack) -> str | None:
    return lack_reason(lack) if lack in for_account(aid).lacks else None


def unknown_refusal(aid: str) -> str | None:
    p = for_account(aid)
    return unknown_reason(p.key) if isinstance(p, UnknownPlatform) else None


def lacks_for_account(aid: str, lack: Lack) -> bool:
    return lack in for_account(aid).lacks


def refusal_for_account(aid: str, name: str) -> str | None:
    if reason := unknown_refusal(aid):
        return reason
    p = for_account(aid)
    return None if p.backend is None else refusal(p.backend.Shim, name)


def backends() -> tuple[ModuleType, ...]:
    return tuple(p.backend for p in ALL if p.backend is not None)
