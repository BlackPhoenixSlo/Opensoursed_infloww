from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, replace

import gdrive
import media_prep
from vault_ai_effective import normalize_tags

# Shares vault_upload's logger name on purpose: log routing is unchanged.
log = logging.getLogger("of-relay.vault_upload")

# New files cost carrier posts; a runaway batch is a runaway number of scheduled posts on a real feed.
MAX_FILES = int(os.environ.get("VAULT_UPLOAD_MAX_FILES") or 40)
# No measured size ceiling (a 2.31 GiB .mp4 uploaded; the 443 MB .mov failed on its container): a sanity backstop. The real guard is disk (guard_space + MIN_FREE_BYTES).
MAX_MB = int(os.environ.get("VAULT_UPLOAD_MAX_MB") or 4000)
MAX_BYTES = MAX_MB * 1024 * 1024
# A batch that fills the disk breaks the whole relay, not just itself.
MIN_FREE_BYTES = int(os.environ.get("VAULT_UPLOAD_MIN_FREE_MB") or 2048) * 1024 * 1024
# Ceiling for the compress-hatch-on case only; Limits collapses it into MAX_MB otherwise (remux and pass-through can't shrink a file).
# 2000 was a phantom: the largest file known uploaded is 2368 MiB.
MAX_DOWNLOAD_MB = int(os.environ.get("VAULT_DOWNLOAD_MAX_MB") or 5000)
MAX_DOWNLOAD_BYTES = MAX_DOWNLOAD_MB * 1024 * 1024
# Measured: OF throttles POST /posts to ~1 per 10 s (400 "Please allow 10 seconds"). Standalone backstop only: the route passes pace_s=0 since the write gate already spaces writes.
PACE_S = float(os.environ.get("VAULT_UPLOAD_PACE_S") or 11.0)
CARRIER_BATCH = max(1, int(os.environ.get("VAULT_UPLOAD_CARRIER_BATCH") or 10))


@dataclass(frozen=True)
class Limits:
    max_files: int = MAX_FILES
    max_bytes: int = MAX_BYTES
    max_download_bytes: int = MAX_DOWNLOAD_BYTES
    compress_over_bytes: int = media_prep.COMPRESS_OVER_MB * 1024 * 1024
    target_bytes: int = media_prep.TARGET_MB * 1024 * 1024
    min_free_bytes: int = MIN_FREE_BYTES
    pace_s: float = PACE_S
    carrier_batch: int = CARRIER_BATCH

    @property
    def compress_enabled(self) -> bool:
        return self.compress_over_bytes < media_prep.COMPRESS_OFF_MB * 1024 * 1024

    def checked(self) -> "Limits":
        out = self
        if out.carrier_batch < 1:
            out = replace(out, carrier_batch=1)
        if not out.compress_enabled and out.max_download_bytes > out.max_bytes:
            # Nothing between fetch and upload can shrink the file, so a bigger fetch ceiling only buys a wasted download.
            out = replace(out, max_download_bytes=out.max_bytes)
        elif out.max_download_bytes < out.max_bytes:
            out = replace(out, max_download_bytes=out.max_bytes)
        if out.compress_enabled and out.target_bytes >= out.max_bytes:
            target = int(out.max_bytes * 0.95)
            log.error("vault limits: compression target %.0f MB is not below the "
                      "%.0f MB upload ceiling — every large video would be "
                      "re-encoded and then skipped. Clamping the target to %.0f MB; "
                      "fix VAULT_COMPRESS_TARGET_MB / VAULT_UPLOAD_MAX_MB.",
                      out.target_bytes / 1e6, out.max_bytes / 1e6, target / 1e6)
            out = replace(out, target_bytes=target)
        return out

    @property
    def compress_over_mb(self) -> int:
        return max(1, self.compress_over_bytes // (1024 * 1024))

    @property
    def target_mb(self) -> int:
        return max(1, self.target_bytes // (1024 * 1024))


def _item(name, path, source, size, *, status="pending", error=None,
          spooled=False) -> dict:
    return {"name": name, "path": path, "source": source, "size": size,
            "status": status, "error": error, "spooled": spooled,
            "vault_id": None, "carrier_post_id": None, "carrier_deleted": None,
            # carrier_deleted = the post is gone from OF (a 404 on delete proves it); carrier_scan_clear = a completed scan found none: two claims, two fields.
            "carrier_intent": None, "carrier_scan_clear": None,
            "carrier_write_pending": None,
            # Shared by every file on a carrier, so it is counted once and deleted once.
            "carrier_key": None,
            "deduped": None, "hidden": None,
            "still_transcoding": None,
            "compressed_from": None, "claim_retries": 0,
            "drive_id": None, "drive_md5": None, "mime_type": None,
            "drive_resource_key": None,
            "message_id": None,
            # The fan send's gate wait timed out: the message may still go out. Not carrier_write_pending.
            "message_write_pending": None,
            "meta": None}


_FAN_HANDLE_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def fan_handle(raw: str | None) -> str:
    s = (raw or "").strip()
    if m := re.search(r"onlyfans\.com/+([^/?#\s]+)", s, re.I):
        s = m.group(1)
    s = s.strip().strip("/").lstrip("@").strip()
    if s and not _FAN_HANDLE_RE.fullmatch(s):
        raise ValueError(f"{s!r} is not an OnlyFans username")
    return s


def _price_cents(v) -> int | None:
    try:
        return None if v in (None, "") else max(0, int(float(v)))
    except (TypeError, ValueError):
        return None


def parse_meta(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None

    def tags(key: str, prefix: str) -> list[str]:
        v = raw.get(key)
        return normalize_tags([str(t).strip().lstrip(prefix) for t in v]
                              if isinstance(v, (list, tuple)) else [])

    out: dict = {}
    if hashtags := tags("hashtags", "#"):
        out["hashtags"] = hashtags
    if creators := tags("tag_creators", "@"):
        out["tag_creators"] = creators
    if notes := str(raw.get("notes") or "").strip():
        out["notes"] = notes[:2000]
    if (price := _price_cents(raw.get("price_cents"))) is not None:
        out["price_cents"] = price
    try:
        if raw.get("list_id") not in (None, ""):
            out["list_id"] = int(raw["list_id"])
    except (TypeError, ValueError):
        pass
    return out or None


def drive_meta(f: "gdrive.DriveFile") -> dict | None:
    return parse_meta({"hashtags": gdrive.folder_tags(f)})


def parse_metas(raw: str | None) -> list[dict | None]:
    try:
        got = json.loads(raw) if raw else []
    except ValueError:
        return []
    return [parse_meta(m) for m in got] if isinstance(got, list) else []


# The listing isn't filtered yet (docs, dupes, oversized count), so 2:1 headroom; Drive memo hits are already done when caps run, so a re-run can finish with up to max_files * this.
_RESOLVE_HEADROOM = 2


def resolve_budget(limits: Limits) -> int:
    return limits.max_files * _RESOLVE_HEADROOM


def cap_for(name: str, mime: str | None, limits: Limits) -> int:
    return (limits.max_download_bytes
            if media_prep.can_shrink(name, mime) else limits.max_bytes)


def _apply_caps(items: list[dict], limits: Limits, *, already: int = 0) -> int:
    pending = already
    for it in items:
        if it["status"] != "pending":
            continue
        shrinkable = media_prep.can_shrink(it["name"], it.get("mime_type"))
        cap = cap_for(it["name"], it.get("mime_type"), limits)
        if it["size"] is not None and it["size"] > cap:
            it.update(status="skipped",
                      error=f"{it['size'] / 1e6:.0f} MB exceeds the "
                            f"{cap / 1e6:.0f} MB limit"
                            + ("" if shrinkable else " and is not video ffmpeg "
                                                      "can prepare"))
            continue
        if pending >= limits.max_files:
            it.update(status="skipped",
                      error=f"batch cap of {limits.max_files} files reached")
            continue
        pending += 1
    return pending

