"""service/vault_import_decide.py — the pure rules of the vault import routes.

No DB, no IO, no FastAPI: what `vault_import_api` hands measured values to and
gets a verdict back; the routes raise the HTTP errors and do the writes.
Table-tested in tests/test_vault_import_decide.py.

  body cap     batch_body_refusal / stage_room — the 411 (no length) / 413
               (over the room both staging copies leave) refusal, before a
               byte is written.
  fan          fan_mismatch — the batch's re-check of the fan it was shown.
  details      metas_for_parts — per-PART details, so a skipped nameless part
               shifts nobody's.
  status       status_body — the status route's run fields for one run (the
               route adds the card's own fields).
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any, Protocol


class Caps(Protocol):
    """The run caps the body cap reads (`vault_upload.Limits` fits)."""
    min_free_bytes: int
    max_files: int
    max_download_bytes: int


def stage_room(free: int, same_device: bool, *, min_free_bytes: int,
               max_files: int, max_download_bytes: int) -> int:
    """Bytes a batch may declare: both copies are live at once on one device
    (the handler streams out of the spooled part while writing the staged
    one), the tighter one otherwise, and never past what one run can take."""
    copies = 2 if same_device else 1
    return min(max(free - min_free_bytes, 0) // copies,
               max_files * max_download_bytes)


def batch_body_refusal(content_length: str | None,
                       measure: Callable[[], tuple[int, bool]],
                       limits: Callable[[], Caps]) -> tuple[int, str] | None:
    """`(status, detail)` to refuse a capped batch upload with, or None.

    `limits()` (the run's caps: `min_free_bytes`, `max_files`,
    `max_download_bytes`) then `measure()` (the disk read: free bytes, one
    device?) are called only once a length was declared, so a 411 touches no
    disk."""
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
    """The 400 detail when the fan looked up now is not the one the card
    checked (or an id came without a name); None when they agree."""
    if fan is not None and str(fan["id"]) != fan_id.strip():
        return (f"@{fan['username']} is not the fan account that was checked "
                f"— check the username again before importing")
    if fan is None and fan_id.strip():
        return "fan_id without fan_username"
    return None


def metas_for_parts(names: Iterable[str | None], metas: Sequence[Any]) -> list:
    """One entry per NAMED part, indexed by the part (not the staged count):
    a skipped nameless part must not shift every later file onto its
    neighbour's details. None past the end of `metas`."""
    return [metas[n] if n < len(metas) else None
            for n, name in enumerate(names) if name]


def status_body(state: dict, statuses: Iterable[str],
                carriers: tuple[int, int]) -> dict:
    """The status route's run fields for one run (`state` = its run.json): the
    run's own fields, a count per item status, the account's carrier roll-up
    (`carriers` = `(undeletable, unrecorded)`), the items."""
    items = state.get("items") or []
    counts = {st: sum(1 for i in items if i.get("status") == st)
              for st in statuses}
    carriers_undeletable, carriers_unrecorded = carriers
    return {
        "running": state.get("status") == "running",
        "run_id": state.get("run_id"),
        "status": state.get("status"),
        "phase": state.get("phase"),
        "error": state.get("error"),
        "filing_error": state.get("filing_error"),
        # `{applied, skipped, why}` for the per-file details, once landed.
        "details_saved": state.get("details_saved"),
        # The linked fan, if any: that path costs one write per file, not two.
        "fan_id": state.get("fan_id"),
        "finished_at": state.get("finished_at"),
        "total": len(items),
        **counts,
        # Across EVERY run for the account and only FINISHED ones: a carrier
        # that could not be deleted must stay on screen until it is actually
        # gone, and one that legitimately exists for the two seconds of a live
        # import must never be reported as an escape. `carriers_unrecorded`
        # counts the worse case — an intent whose create response was lost, so
        # there is no id to name. The names are `vault_upload`'s own: this wire
        # said `carriers_live` long after the module stopped, so the retired
        # name was the one every consumer read.
        "carriers_undeletable": carriers_undeletable,
        "carriers_unrecorded": carriers_unrecorded,
        "items": items,
    }
