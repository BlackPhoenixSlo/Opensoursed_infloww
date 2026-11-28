from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

STATUSES = frozenset({"none", "unknown", "pending", "active", "former"})
VIEWS = {"none": ("offer", "offer"), "unknown": ("offer", "hidden"), "pending": ("starting", "starting"),
         "active": ("track", "track"), "former": ("past", "past")}
OFFER_VIEWS = frozenset({"offer", "past"})
TRACK_VIEWS = frozenset({"track", "past"})
FRESH_FOR = timedelta(hours=48)
SNOOZE_FOR = timedelta(days=7)
BRAND_MAX = 40
CONTACT_MAX = 512
OFFER_COUNTS = ("visible", "came_back_30d", "cached", "live_30d", "new_7d")
TRACK_COUNTS = ("noticed", "gone_after_notice", "gone_no_notice", "delisted", "live_after_notice")
ANGLES = (("came_back", "came_back_30d"), ("cached", "cached"), ("live_30d", "live_30d"), ("new_week", "new_7d"),
          ("visible", "visible"))
NO_SPACE = re.compile(r"\S+")


def _instant(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def fresh(notices_updated_at: Any, now: datetime) -> bool:
    at = _instant(notices_updated_at)
    return at is not None and now - at <= FRESH_FOR


def removal_view(status: Any, notices_updated_at: Any, now: datetime) -> dict[str, Any]:
    status = status if status in STATUSES else "unknown"
    ok = fresh(notices_updated_at, now)
    on_fresh, on_stale = VIEWS[status]
    return {"status": status, "view": on_fresh if ok else on_stale, "stale": not ok}


def angle(counts: dict[str, int]) -> tuple[str, int]:
    if counts["visible"] == 0:
        return "clean", 0
    return next((name, counts[k]) for name, k in ANGLES if counts[k])


def _brand_ok(brand: Any) -> bool:
    return isinstance(brand, str) and 0 < len(brand) <= BRAND_MAX and bool(brand.strip())


def _contact_ok(url: Any) -> bool:
    if not isinstance(url, str) or len(url) > CONTACT_MAX or not NO_SPACE.fullmatch(url):
        return False
    parts = urlsplit(url)
    return parts.scheme == "https" and bool(parts.hostname)


def removal_offer(view: str, *, owner_or_admin: bool, first_daily_at: Any, snoozed: bool, brand: Any,
                  contact_url: Any, counts: dict[str, int] | None) -> dict[str, Any] | None:
    if view not in OFFER_VIEWS or not owner_or_admin or snoozed or counts is None \
            or not (isinstance(first_daily_at, str) and first_daily_at) \
            or not _brand_ok(brand) or not _contact_ok(contact_url):
        return None
    name, n = angle(counts)
    return {"brand": brand, "contact_url": contact_url, "angle": name, "n": n}


CUE_KINDS = frozenset({"google", "google_images", "mega", "forum", "x", "end"})
CUES_MAX = 12
SCENES = ("google", "google_images", "mega", "forum", "x")
SCENE_MAX = {"google_images": 6}
SCENE_DEFAULT_MAX = 4
VISIBLE = frozenset({"live", "cached"})
X_SITES = frozenset({"x.com", "twitter.com"})
VIDEO_PARTS: dict[str, tuple[str, int]] = {"video": ("video/mp4", 64 * 1024 * 1024),
                                           "poster": ("image/webp", 2 * 1024 * 1024),
                                           "captions": ("text/vtt", 256 * 1024)}
RANGE = re.compile(r"bytes=(\d{0,18})-(\d{0,18})")


def _seconds(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _cues(raw: Any, duration: float) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list) or len(raw) > CUES_MAX:
        return None
    out: list[dict[str, Any]] = []
    for c in raw:
        if not isinstance(c, dict) or c.get("kind") not in CUE_KINDS or not _seconds(c.get("t_s")) \
                or not 0 <= c["t_s"] <= duration or (out and c["t_s"] < out[-1]["t_s"]):
            return None
        out.append({"t_s": c["t_s"], "kind": c["kind"]})
    return out


def video_of(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not _seconds(raw.get("duration_s")) or raw["duration_s"] <= 0 \
            or not isinstance(raw.get("has_poster"), bool):
        return None
    return {"duration_s": raw["duration_s"], "has_poster": raw["has_poster"],
            "cues": _cues(raw.get("cues"), raw["duration_s"])}


def _scene(leak: dict[str, Any]) -> str | None:
    sources = leak.get("sources") or []
    site = (leak.get("leak_site") or "").lower()
    if site in X_SITES:
        return "x"
    if leak.get("kind") == "mega":
        return "mega"
    if leak.get("kind") == "media" and isinstance(leak.get("preview"), dict):
        return "google_images"
    if "google_web" in sources:
        return "google"
    if "site_search" in sources:
        return "forum"
    return None


def _newest_seen(leak: dict[str, Any]) -> str:
    seen = [e["at"] for e in leak.get("events") or [] if e.get("type") == "seen" and isinstance(e.get("at"), str)]
    return max(seen, default=leak.get("first_seen_at") or "")


def overlay_scenes(leaks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {k: [] for k in SCENES}
    ordered = sorted(leaks, key=lambda x: x["leak_id"])
    for leak in sorted(ordered, key=_newest_seen, reverse=True):
        kind = _scene(leak)
        pill = leak.get("pill")
        if pill not in VISIBLE and not (kind == "mega" and pill == "listed"):
            continue
        if kind and len(out[kind]) < SCENE_MAX.get(kind, SCENE_DEFAULT_MAX):
            out[kind].append({k: leak[k] for k in ("leak_id", "leak_site", "kind", "title", "pill")} | {"preview": None})
    return out


def one_range(values: list[str]) -> str | None:
    if not values:
        return None
    if len(values) != 1 or not (m := RANGE.fullmatch(values[0].strip())) or not (m[1] or m[2]) \
            or (m[1] and m[2] and int(m[1]) > int(m[2])):
        raise ValueError("range")
    return values[0].strip()
