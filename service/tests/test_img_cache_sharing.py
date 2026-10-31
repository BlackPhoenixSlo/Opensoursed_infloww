#!/usr/bin/env python3
"""
Vault-image cache sharing + warmth — CACHING_PLAN.md acceptance.

The plan's whole premise: a vault image has a STABLE identity (host+path);
only OF's signature rotates. The on-disk /img cache keys on host+path with the
signature stripped, so every re-signed URL and every message that reuses the
image resolves to ONE entry — and unsend never has to touch the cache.

Cases:
  case_resigned_url_shares_entry (the headline acceptance):
      two URLs that differ ONLY in the signature query string map to the same
      cache key; bytes written under one are a HIT under the other.
  case_key_is_account_agnostic:
      the cache key depends only on host+path — two accounts fetching the same
      asset share the entry (no per-account duplication).
  case_send_to_many_writes_once:
      the same vault image written N times lands as exactly ONE .bin on disk.
  case_touch_keeps_hot_entry_warm:
      an entry served while aging gets its mtime refreshed, so the TTL evictor
      (which ages by mtime) does NOT reclaim a popular image still in use.
  case_cold_entry_still_evicts:
      an untouched entry past the TTL is still reclaimed (touch didn't pin
      everything forever).
  case_unsend_is_cache_free:
      service/automations/unsend_messages.py contains ZERO cache code — the
      plan explicitly removes the unsend→cache coupling.

Run: ./venv/bin/python service/tests/test_img_cache_sharing.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import os
import tempfile
import uuid
from pathlib import Path

# Point the on-disk image cache at a unique temp dir BEFORE importing server,
# so the module-level _IMG_CACHE_DIR binds to it and we never touch a real cache.
_CACHE_DIR = Path(tempfile.gettempdir()) / f"img_cache_test_{uuid.uuid4().hex}"
os.environ["IMG_CACHE_DIR"] = str(_CACHE_DIR)

import server  # noqa: E402 — after _harness (DB) + IMG_CACHE_DIR are bound
import img_api  # noqa: E402

# Same physical vault asset (identical host+path), three different signatures —
# exactly what OF hands us across re-lists / signature expiry / different accounts.
_HOST_PATH = "https://cdn2.onlyfans.com/files/a/ab/abc123deadbeef/source.jpg"
_URL_SIG_A = _HOST_PATH + "?Policy=AAA&Signature=sig-one&Key-Pair-Id=K1"
_URL_SIG_B = _HOST_PATH + "?Policy=BBB&Signature=sig-two&Key-Pair-Id=K2"
_URL_SIG_C = _HOST_PATH + "?Expires=999&Signature=sig-three"


def case_resigned_url_shares_entry():
    img_api._img_cache_write(_URL_SIG_A, "image/jpeg", b"the-image-bytes")
    # A request bearing a DIFFERENT signature for the same asset must HIT.
    hit = img_api._img_cache_lookup(_URL_SIG_B)
    assert hit is not None, "re-signed URL missed the cache (key not signature-stripped)"
    bin_p, ct = hit
    assert ct == "image/jpeg", f"content-type lost: {ct!r}"
    assert bin_p.read_bytes() == b"the-image-bytes", "served bytes differ from written bytes"
    # And the key is literally identical across all three signatures.
    keys = {img_api._img_cache_key(u) for u in (_URL_SIG_A, _URL_SIG_B, _URL_SIG_C)}
    assert len(keys) == 1, f"signatures produced different keys: {keys}"


def case_key_is_account_agnostic():
    # The key fn takes only the URL — no account dimension — so two accounts
    # that fetch the same asset (each with its own signed URL) share one entry.
    k_a = img_api._img_cache_key(_URL_SIG_A)
    k_b = img_api._img_cache_key(_URL_SIG_B)
    assert k_a == k_b, "cache key must not depend on which account/signature fetched it"
    # Sanity: a genuinely different asset gets a different key.
    other = "https://cdn2.onlyfans.com/files/z/zz/other/source.jpg?Signature=x"
    assert img_api._img_cache_key(other) != k_a, "distinct assets collided on one key"


def case_send_to_many_writes_once():
    url = "https://cdn2.onlyfans.com/files/m/mm/mass-shared/source.jpg?Signature=s0"
    # Simulate the same vault image being cached on 100 separate renders/sends,
    # each arriving with a freshly-signed URL.
    for i in range(100):
        signed = url.replace("s0", f"s{i}")
        img_api._img_cache_write(signed, "image/jpeg", b"shared-bytes")
    h = img_api._img_cache_key(url)
    bin_p, _ = img_api._img_cache_paths(h)
    sub = bin_p.parent
    bins = [p for p in sub.iterdir() if p.name == bin_p.name]
    assert len(bins) == 1, f"expected exactly one .bin for the shared image, found {len(bins)}"
    assert bin_p.read_bytes() == b"shared-bytes"


def case_touch_keeps_hot_entry_warm():
    url = "https://cdn2.onlyfans.com/files/h/hh/hot-asset/source.jpg?Signature=hot"
    img_api._img_cache_write(url, "image/jpeg", b"hot")
    h = img_api._img_cache_key(url)
    bin_p, ct_p = img_api._img_cache_paths(h)
    # Backdate the entry to 1s shy of the TTL but well past the touch throttle —
    # i.e. it's been sitting a long time but is being served right now.
    import time as _t
    aged = _t.time() - (img_api._IMG_CACHE_TTL_S - 1)
    os.utime(bin_p, (aged, aged))
    os.utime(ct_p, (aged, aged))
    # A served hit refreshes the mtime...
    img_api._img_cache_touch(bin_p, ct_p)
    fresh_mtime = bin_p.stat().st_mtime
    assert fresh_mtime > aged + 1000, "touch did not refresh a stale-but-served entry's mtime"
    # ...so the TTL evictor leaves the now-warm entry alone.
    img_api._img_cache_evict_once()
    assert bin_p.is_file(), "evictor reclaimed a freshly-served (touched) entry"


def case_cold_entry_still_evicts():
    url = "https://cdn2.onlyfans.com/files/c/cc/cold-asset/source.jpg?Signature=cold"
    img_api._img_cache_write(url, "image/jpeg", b"cold")
    h = img_api._img_cache_key(url)
    bin_p, ct_p = img_api._img_cache_paths(h)
    import time as _t
    expired = _t.time() - (img_api._IMG_CACHE_TTL_S + 60)
    os.utime(bin_p, (expired, expired))
    os.utime(ct_p, (expired, expired))
    # No touch (nobody served it) → past TTL → evictor reclaims it.
    img_api._img_cache_evict_once()
    assert not bin_p.is_file(), "evictor failed to reclaim a cold, expired entry"


def case_unsend_is_cache_free():
    src = (Path(__file__).resolve().parents[1] / "automations" / "unsend_messages.py").read_text()
    # Strip comments/docstring noise isn't worth it — assert on identifiers that
    # would only appear in actual cache calls, not prose.
    forbidden = ("_img_cache_", "_pin_sent_media", "_pinned_media",
                 "_img_cache_evict", "_pin_prune", "_pinned_keys")
    hits = [tok for tok in forbidden if tok in src]
    assert not hits, f"unsend_messages.py must contain zero cache code; found {hits}"


_harness.run(
    case_resigned_url_shares_entry,
    case_key_is_account_agnostic,
    case_send_to_many_writes_once,
    case_touch_keeps_hot_entry_warm,
    case_cold_entry_still_evicts,
    case_unsend_is_cache_free,
)
