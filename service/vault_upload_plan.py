"""The pure half of a vault import: limits, per-file details off the wire,
the caps, and the item schema. No run state, no I/O of its own, no locks —
those live in `vault_upload`, which re-exports the names its callers use."""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, replace

import gdrive
import media_prep
from vault_ai_effective import normalize_tags

# Shares `vault_upload`'s logger name on purpose: log routing is unchanged.
log = logging.getLogger("of-relay.vault_upload")

# Caps. Per-file size is the one an operator actually tunes; the batch cap
# exists because new files cost carrier posts (one per `Limits.carrier_batch`),
# and a runaway batch is a runaway number of scheduled posts on a real feed.
MAX_FILES = int(os.environ.get("VAULT_UPLOAD_MAX_FILES") or 40)
# THERE IS NO MEASURED SIZE CEILING. This used to sit at 200 MB, recorded as a
# "MEASURED CEILING" because a 443 MB object drew 504s out of
# `convert.onlyfans.com`. A HAR capture of the real OnlyFans web client says
# that reading was a misattribution: a 2.31 GiB .mp4 in it went up and was
# registered without complaint, while the 443 MB .mov failed at convert ALONE,
# with all 89 of its S3 parts already stored. (The figures behind that — the
# timings, the part counts, the twelve 504s and their durations — live in ONE
# place, the `_CONVERT_TIMEOUT_S` comment in `of_client.py`. Cite it; do not
# copy it here, which is how eight copies of a wrong number came to be written.)
# The variable was the CONTAINER, not the byte count. (Honestly: one .mov
# failing twice against one large .mp4 succeeding once. That is enough to retire
# the size theory and to make the container the prime suspect; it is not a proof
# that every .mov fails.) `media_prep` now normalises the container instead of
# shrinking the file.
#
# So this number is a sanity backstop on a single item, not a protocol limit.
# THE REAL GUARD IS DISK, and it is already in place and already correct:
# `vault_upload.guard_space` + `MIN_FREE_BYTES` refuse a file that would eat
# the free-space floor, which is the constraint that genuinely exists on this
# box.
MAX_MB = int(os.environ.get("VAULT_UPLOAD_MAX_MB") or 4000)
MAX_BYTES = MAX_MB * 1024 * 1024
# Free space we refuse to drop below while spooling. A batch that fills the
# disk breaks the whole relay, not just itself.
MIN_FREE_BYTES = int(os.environ.get("VAULT_UPLOAD_MIN_FREE_MB") or 2048) * 1024 * 1024
# How large a source we are willing to FETCH, as opposed to upload. A ceiling
# ABOVE the upload ceiling is only ever worth having when the step in between
# can make the file smaller — which is now only the opt-in compress hatch. A
# remux and a pass-through do not shrink anything, so under the default
# settings a file that fetches under this number and cannot be uploaded under
# MAX_MB is a multi-gigabyte download spent for nothing: exactly the bug
# `can_shrink` exists to prevent, one step further down the pipeline. `Limits`
# therefore collapses the two into one ceiling unless the hatch is on — see
# `Limits.checked`. This constant is the ceiling for the hatch-on case only.
# 2000 was the old value and it was itself a phantom: the largest file we have
# direct evidence of uploading is 2368 MiB, so that ceiling would have refused
# the very file that proves the point (see MAX_MB above).
MAX_DOWNLOAD_MB = int(os.environ.get("VAULT_DOWNLOAD_MAX_MB") or 5000)
MAX_DOWNLOAD_BYTES = MAX_DOWNLOAD_MB * 1024 * 1024
# Minimum gap between CARRIER posts. MEASURED, not guessed: OnlyFans throttles
# POST /posts to roughly one per ten seconds and 400s with "Please allow 10
# seconds" when a batch of small files outruns it. Counted from the end of the
# previous carrier, so time spent uploading the next batch's bytes is part of
# the gap rather than added to it. This is the STANDALONE backstop only: the
# relay's own write gate already spaces every write for the account, so the
# route passes `Limits(pace_s=0)` and sleeping here on top of it would double
# the cost of every carrier. That is a stated policy, not something inferred
# from whether a gate was injected (see `vault_upload.start()`).
PACE_S = float(os.environ.get("VAULT_UPLOAD_PACE_S") or 11.0)
# How many new files ride on one carrier post. See `vault_upload`'s docstring;
# 1 is the old one-carrier-per-file behaviour.
CARRIER_BATCH = max(1, int(os.environ.get("VAULT_UPLOAD_CARRIER_BATCH") or 10))


@dataclass(frozen=True)
class Limits:
    """Every size/count policy for one run, in one object.

    These used to be four module constants read from four places, with one of
    them (`MAX_BYTES`) read as a global by the very function a `--max-mb`
    override was supposed to reach — so `--max-mb 50` capped collection at 50
    MB and then admitted a 200 MB compressed file. One object, built once in
    `vault_upload.start()` and threaded through, is what makes an override
    actually mean something end to end.

    `target_bytes < max_bytes` is the cross-module invariant: `media_prep`'s
    opt-in `compress` pass aims a re-encode at the target, and a target above
    the upload ceiling means every large video pays a full ffmpeg pass and is
    then skipped. It was asserted in a comment and enforced nowhere; it is
    enforced in `checked()` — and only when the escape hatch is actually ON,
    because a rule that fires loudly for a run in which `compress()` can never
    execute is a rule people learn to scroll past.

    `max_download_bytes` is DERIVED in `checked()`, not independent. Two
    ceilings only pay for themselves when the step between them can shrink the
    file; with the hatch off nothing does, so they collapse to one and an
    oversized video is refused before its bytes are fetched instead of after.
    That derivation is also what makes a `--max-mb` override mean the same
    thing in the cap pass, the fetch pass and the upload pass — the CLI sets
    only `max_bytes`, and without it `--max-mb 500` still downloaded every
    video up to 5 GB before skipping it at 500 MB.

    Build it, then call `checked()`. The raw dataclass is the operator's
    stated intent; `checked()` is the coherent version of it.
    """
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
        """Did the operator switch `media_prep`'s size-targeted pass on?

        It is the only step in the pipeline that makes a file SMALLER, so it is
        the only reason to fetch something bigger than we can upload, and the
        only reason the compression target has to sit under the upload ceiling.
        """
        return self.compress_over_bytes < media_prep.COMPRESS_OFF_MB * 1024 * 1024

    def checked(self) -> "Limits":
        """The same limits, made coherent — loudly where an operator set them."""
        out = self
        if out.carrier_batch < 1:
            out = replace(out, carrier_batch=1)
        if not out.compress_enabled and out.max_download_bytes > out.max_bytes:
            # Nothing between the fetch and the upload can shrink this file, so
            # a bigger fetch ceiling can only ever buy a wasted download.
            out = replace(out, max_download_bytes=out.max_bytes)
        elif out.max_download_bytes < out.max_bytes:
            # An explicit --max-mb ABOVE the fetch ceiling would refuse to
            # download a file it is willing to upload. Follow the override.
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
    """The item schema. EVERY key an item can carry is declared here — the
    dashboard's row type is written against this and nothing else."""
    return {"name": name, "path": path, "source": source, "size": size,
            "status": status, "error": error, "spooled": spooled,
            "vault_id": None, "carrier_post_id": None, "carrier_deleted": None,
            # Two different claims, deliberately two fields. `carrier_deleted`
            # means "the post whose id is above is gone from OnlyFans" — and a
            # 404 on the delete proves that as well as a 200 does.
            # `carrier_scan_clear` means "a marker scan that ran to completion
            # found no post for this intent". Saying the second with the first
            # asserted a deletion that never happened, on a field the CLI and
            # the dashboard both read.
            "carrier_intent": None, "carrier_scan_clear": None,
            "carrier_write_pending": None,
            # Which carrier this file rode, shared by every file on it and
            # stamped with its intent (`vault_upload._carrier_hooks`):
            # `vault_upload._carriers` groups by it, so a shared carrier is
            # counted once and deleted once.
            "carrier_key": None,
            "deduped": None, "hidden": None,
            "still_transcoding": None,
            "compressed_from": None, "claim_retries": 0,
            "drive_id": None, "drive_md5": None, "mime_type": None,
            "drive_resource_key": None,
            # The fan message that carried the file into the vault, when the
            # run sends to a fan instead of minting a carrier post.
            "message_id": None,
            # The fan send's gate wait timed out: the message may still go out.
            # NOT `carrier_write_pending` — no carrier exists on this path.
            "message_write_pending": None,
            # The operator's details for this file — `{hashtags, notes,
            # price_cents, tag_creators, list_id}`, any subset — or None.
            "meta": None}


# What `fan_handle` accepts once the `@` and any profile link are gone: what an
# OnlyFans username can contain. Anything else is a typo, not a name to look up.
_FAN_HANDLE_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def fan_handle(raw: str | None) -> str:
    """The OnlyFans username in whatever the operator pasted — `name`,
    `@name`, or a profile link — or "" for nothing (the carrier path).

    The ONE parser: the resolve route and the batch route both go through it,
    and the card sends back the username the resolve route answered with.
    Raises ValueError for something that cannot be a username."""
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
    """One file's details off the wire, kept to the keys and shapes the run
    understands: `{hashtags, tag_creators, notes, price_cents, list_id}`.
    Anything else is dropped; an empty result is None.

    The two tag fields are LISTS — the card splits on commas, so a multi-word
    hashtag survives as one tag, and nothing here splits again. They go through
    the vault's own tag normaliser, so what is stored is what the vault would
    have stored for the same tag typed in its editor. Downstream
    (`vault_ai_api._import_edits`) trusts this shape."""
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
    """A Drive file's details: its folder names as hashtags (`folder_tags`),
    through the same `parse_meta` a typed row goes through."""
    return parse_meta({"hashtags": gdrive.folder_tags(f)})


def parse_metas(raw: str | None) -> list[dict | None]:
    """The batch route's `meta` form field: a JSON list, one entry per file in
    the order the files were sent. Malformed JSON is no details, not an error —
    the files themselves are still worth importing."""
    try:
        got = json.loads(raw) if raw else []
    except ValueError:
        return []
    return [parse_meta(m) for m in got] if isinstance(got, list) else []


# How many Drive entries to LIST for a batch of `max_files`. The listing has
# not been filtered yet — Google-native docs, duplicates and oversized files all
# still count — so resolving exactly the cap would let a folder of shared
# spreadsheets consume every slot the operator meant for media. Two-to-one is
# headroom, not a second cap: `_apply_caps` enforces the batch.
#
# With one exception, and it is worth stating because a reader reasonably
# assumes `max_files` bounds the whole run: `_apply_caps` counts only `pending`
# items, and a Drive MEMO HIT is already `done` when caps run
# (`vault_upload._plan` recognises the file by Drive's md5 and skips the
# download entirely). So a re-run of a Drive folder whose every file is already
# in the vault can finish with up to `max_files * _RESOLVE_HEADROOM` done
# items. That is correct — nothing was uploaded, no carrier was posted, no cap
# was meant to stop it — but it IS the real bound on how many ids a post-run
# consumer (`vault_upload.landed_ids`, and the mirror write behind it) has to
# deal with.
_RESOLVE_HEADROOM = 2


def resolve_budget(limits: Limits) -> int:
    return limits.max_files * _RESOLVE_HEADROOM


def cap_for(name: str, mime: str | None, limits: Limits) -> int:
    """The largest this file may be — the ONE place that rule is decided.

    Video ffmpeg can take a pass at is allowed up to the (much larger) DOWNLOAD
    ceiling: the container-normalising pass runs later and cannot judge a file
    it was never allowed to fetch, and `vault_upload._upload_one` re-checks the
    real upload cap once the prepared size is known. Everything else is capped
    at the per-file backstop, since nothing downstream will change its size.

    It lived in three places — the cap pass, the Drive fetch, and the HTTP
    staging loop, which applied the DOWNLOAD ceiling to everything and so
    streamed a 1.5 GB dragged-in JPEG to disk in full before skipping it at
    200 MB. Callers ask here instead.
    """
    return (limits.max_download_bytes
            if media_prep.can_shrink(name, mime) else limits.max_bytes)


def _apply_caps(items: list[dict], limits: Limits, *, already: int = 0) -> int:
    """The size and batch caps, in ONE pass over the plan. Returns how many
    files the batch cap has now admitted, `already` included.

    There were two implementations of this rule with the same error string, on
    either side of the Drive download, and they disagreed about oversized
    video: one let it through to be compressed without ever counting it against
    the batch cap, so 40 small files plus 20 large videos processed 60. A third
    grew for files `vault_upload.append()` hands an open run, counting only
    local files — so a run's Drive files did not count and it could take twice
    the cap. An appended file comes through here too, with `already` = the
    run's tally (`state["admitted"]`), so local, Drive and appended files are
    one count.
    """
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

