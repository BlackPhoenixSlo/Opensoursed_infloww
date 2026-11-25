from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any, Protocol


class Caps(Protocol):
    min_free_bytes: int
    max_files: int
    max_download_bytes: int


def stage_room(free: int, same_device: bool, *, min_free_bytes: int,
               max_files: int, max_download_bytes: int) -> int:
    # Both copies are live at once on one device (the handler streams out of the spooled part while writing the staged one).
    copies = 2 if same_device else 1
    return min(max(free - min_free_bytes, 0) // copies,
               max_files * max_download_bytes)


def batch_body_refusal(content_length: str | None,
                       measure: Callable[[], tuple[int, bool]],
                       limits: Callable[[], Caps]) -> tuple[int, str] | None:
    try:
        declared = int(content_length or 0)
    except ValueError:
        declared = 0
    if declared <= 0:
        return (411, (
            "this upload needs a content-length — the server has to "
            "know how big a batch is before it starts writing it to "
            "disk, and a chunked body cannot be measured until it has "
            "already landed there. Send it as a normal form upload, or "
            "(if a proxy in front of the relay re-encodes the body) "
            "import from Google Drive links instead."))
    lim = limits()
    free, same_device = measure()
    room = stage_room(free, same_device, min_free_bytes=lim.min_free_bytes,
                      max_files=lim.max_files,
                      max_download_bytes=lim.max_download_bytes)
    if declared > room:
        return (413, (
            f"that batch is {declared / 1e9:.1f} GB; this server can "
            f"stage at most {room / 1e9:.1f} GB right now. Import it "
            f"in smaller batches, or from Google Drive links, which "
            f"are fetched one file at a time."))
    return None


def fan_mismatch(fan: dict | None, fan_id: str) -> str | None:
    if fan is not None and str(fan["id"]) != fan_id.strip():
        return (f"@{fan['username']} is not the fan account that was checked "
                f"— check the username again before importing")
    if fan is None and fan_id.strip():
        return "fan_id without fan_username"
    return None


def metas_for_parts(names: Iterable[str | None], metas: Sequence[Any]) -> list:
    return [metas[n] if n < len(metas) else None
            for n, name in enumerate(names) if name]


def status_body(state: dict, statuses: Iterable[str],
                carriers: tuple[int, int]) -> dict:
    items = state.get("items") or []
    counts = {st: sum(1 for i in items if i.get("status") == st)
              for st in statuses}
    # Counted across every account run, finished only: a carrier that could not be deleted stays on screen until gone; unrecorded = an intent whose create response was lost, so there is no id to name.
    carriers_undeletable, carriers_unrecorded = carriers
    return {
        "running": state.get("status") == "running",
        "run_id": state.get("run_id"),
        "status": state.get("status"),
        "phase": state.get("phase"),
        "error": state.get("error"),
        "filing_error": state.get("filing_error"),
        "details_saved": state.get("details_saved"),
        "fan_id": state.get("fan_id"),
        "finished_at": state.get("finished_at"),
        "total": len(items),
        **counts,
        "carriers_undeletable": carriers_undeletable,
        "carriers_unrecorded": carriers_unrecorded,
        "items": items,
    }
