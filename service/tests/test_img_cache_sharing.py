#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

import os
import tempfile
import uuid
from pathlib import Path

_CACHE_DIR = Path(tempfile.gettempdir()) / f"img_cache_test_{uuid.uuid4().hex}"
os.environ["IMG_CACHE_DIR"] = str(_CACHE_DIR)

import server  # noqa: E402 — after _harness (DB) + IMG_CACHE_DIR are bound
import img_api  # noqa: E402

_HOST_PATH = "https://cdn2.onlyfans.com/files/a/ab/abc123deadbeef/source.jpg"
_URL_SIG_A = _HOST_PATH + "?Policy=AAA&Signature=sig-one&Key-Pair-Id=K1"
_URL_SIG_B = _HOST_PATH + "?Policy=BBB&Signature=sig-two&Key-Pair-Id=K2"
_URL_SIG_C = _HOST_PATH + "?Expires=999&Signature=sig-three"


def case_resigned_url_shares_entry():
    img_api._img_cache_write(_URL_SIG_A, "image/jpeg", b"the-image-bytes")
    hit = img_api._img_cache_lookup(_URL_SIG_B)
    assert hit is not None, "re-signed URL missed the cache (key not signature-stripped)"
    bin_p, ct = hit
    assert ct == "image/jpeg", f"content-type lost: {ct!r}"
    assert bin_p.read_bytes() == b"the-image-bytes", "served bytes differ from written bytes"
    keys = {img_api._img_cache_key(u) for u in (_URL_SIG_A, _URL_SIG_B, _URL_SIG_C)}
    assert len(keys) == 1, f"signatures produced different keys: {keys}"


def case_key_is_account_agnostic():
    k_a = img_api._img_cache_key(_URL_SIG_A)
    k_b = img_api._img_cache_key(_URL_SIG_B)
    assert k_a == k_b, "cache key must not depend on which account/signature fetched it"
    other = "https://cdn2.onlyfans.com/files/z/zz/other/source.jpg?Signature=x"
    assert img_api._img_cache_key(other) != k_a, "distinct assets collided on one key"


def case_send_to_many_writes_once():
    url = "https://cdn2.onlyfans.com/files/m/mm/mass-shared/source.jpg?Signature=s0"
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
    import time as _t
    aged = _t.time() - (img_api._IMG_CACHE_TTL_S - 1)
    os.utime(bin_p, (aged, aged))
    os.utime(ct_p, (aged, aged))
    img_api._img_cache_touch(bin_p, ct_p)
    fresh_mtime = bin_p.stat().st_mtime
    assert fresh_mtime > aged + 1000, "touch did not refresh a stale-but-served entry's mtime"
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
    img_api._img_cache_evict_once()
    assert not bin_p.is_file(), "evictor failed to reclaim a cold, expired entry"


def case_over_budget_evicts_the_oldest():
    import time as _t
    now = _t.time()
    urls = [f"https://cdn2.onlyfans.com/files/b/bb/budget-{i}/clip.mp4?Signature=b" for i in range(3)]
    paths = []
    for i, url in enumerate(urls):
        img_api._img_cache_write(url, "video/mp4", b"x" * 1000)
        bin_p, ct_p = img_api._img_cache_paths(img_api._img_cache_key(url))
        os.utime(bin_p, (now - 3000 + i, now - 3000 + i))
        paths.append((bin_p, ct_p))
    total = sum(p.stat().st_size for p in _CACHE_DIR.rglob("*.bin"))
    real = img_api._IMG_CACHE_BUDGET_BYTES
    img_api._IMG_CACHE_BUDGET_BYTES = total - 1500
    try:
        assert img_api._img_cache_evict_once() == 2
    finally:
        img_api._IMG_CACHE_BUDGET_BYTES = real
    assert [b.is_file() or c.is_file() for b, c in paths] == [False, False, True], paths
    assert sum(p.stat().st_size for p in _CACHE_DIR.rglob("*.bin")) == total - 2000


def case_unsend_is_cache_free():
    src = (Path(__file__).resolve().parents[1] / "automations" / "unsend_messages.py").read_text()
    forbidden = ("_img_cache_", "_pin_sent_media", "_pinned_media",
                 "_img_cache_evict", "_pin_prune", "_pinned_keys")
    hits = [tok for tok in forbidden if tok in src]
    assert not hits, f"unsend_messages.py must contain zero cache code; found {hits}"


def case_a_served_image_is_private_so_no_cdn_keeps_it():
    url = "https://cdn2.onlyfans.com/files/p/pp/private-asset/source.jpg?Signature=p"
    img_api._img_cache_write(url, "image/jpeg", b"mine")
    cc = img_api._serve_if_cached(url, "HIT").headers["cache-control"]
    assert cc.startswith("private, max-age=604800"), cc
    assert "public" not in cc, cc


_harness.run(
    case_a_served_image_is_private_so_no_cdn_keeps_it,
    case_resigned_url_shares_entry,
    case_key_is_account_agnostic,
    case_send_to_many_writes_once,
    case_touch_keeps_hot_entry_warm,
    case_cold_entry_still_evicts,
    case_over_budget_evicts_the_oldest,
    case_unsend_is_cache_free,
)
