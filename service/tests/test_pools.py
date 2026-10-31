#!/usr/bin/env python3
"""automations._pools — characterisation tables for the send-time text/media
randomisers shared by auto_posts + mass_premade (int_list / pick_text /
has_media_source / pick_media). Pins today's behaviour; no DB, no OF.

Randomness is pinned by seeding the module-level `random` and comparing with
an independently seeded `random.Random(seed)` doing the documented operation
(choice over the trimmed pool / sample of the clamped count), so a change to
the pool, its order or the count shows as a mismatch.

Run: ./venv/bin/python service/tests/test_pools.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import random  # noqa: E402

from automations._pools import has_media_source, int_list, pick_media, pick_text  # noqa: E402

SEEDS = (0, 1, 7, 42, 1234)


def case_int_list():
    rows = [
        (None, [], "None -> []"),
        ("1,2", [], "string is not a list"),
        ((1, 2), [], "tuple is not a list"),
        ({"a": 1}, [], "dict is not a list"),
        ([], [], "empty list"),
        ([1, 2, 3], [1, 2, 3], "ints kept in order"),
        (["4", " 5 ", "x", None, 6.9], [4, 5, 6], "numeric strs, float truncates, junk dropped"),
        ([True, False], [1, 0], "bools coerce to 1/0"),
        (["1.5"], [], "float string is not an int"),
        ([[1], {"id": 2}], [], "nested containers dropped"),
        ([3, 3, "3"], [3, 3, 3], "duplicates kept"),
    ]
    for raw, exp, label in rows:
        got = int_list(raw)
        assert got == exp, f"int_list[{label}]: got {got!r}, expected {exp!r}"


def case_pick_text_no_pool():
    rows = [
        ({}, "", "empty item"),
        ({"text": None}, "", "text None"),
        ({"text": "  hi  "}, "hi", "text trimmed"),
        ({"texts": None, "text": "x"}, "x", "texts None -> text"),
        ({"texts": [], "text": "x"}, "x", "empty pool -> text"),
        ({"texts": ["  ", "", None, 5], "text": "fb"}, "fb", "all-blank/non-str pool -> text"),
        ({"texts": "abc", "text": "fb"}, "fb", "texts as str is not a pool"),
        ({"texts": ["   "]}, "", "blank pool, no text -> ''"),
    ]
    for item, exp, label in rows:
        got = pick_text(item)
        assert got == exp, f"pick_text[{label}]: got {got!r}, expected {exp!r}"


def case_pick_text_seeded_pool():
    rows = [
        ({"texts": ["only"], "text": "fb"}, ["only"], "single entry beats text"),
        ({"texts": [" a ", "b", "", None, "  c"]}, ["a", "b", "c"], "trimmed non-blank opts"),
        ({"texts": ["x", "y", "z", "w"], "text": "ignored"}, ["x", "y", "z", "w"], "4-pool"),
    ]
    for item, opts, label in rows:
        for seed in SEEDS:
            random.seed(seed)
            got = pick_text(item)
            exp = random.Random(seed).choice(opts)
            assert got == exp, f"pick_text[{label} seed={seed}]: got {got!r}, expected {exp!r}"
            assert got in opts, f"pick_text[{label} seed={seed}]: {got!r} not in {opts!r}"


def case_has_media_source():
    rows = [
        ({}, False, "nothing"),
        ({"media_files": []}, False, "empty files"),
        ({"media_files": ["x", None]}, False, "only junk files"),
        ({"media_files": ["7"]}, True, "numeric str file"),
        ({"media_files": [7]}, True, "int file"),
        ({"media_folder_id": 0}, True, "folder id 0 counts (is not None)"),
        ({"media_folder_id": "abc"}, True, "any non-None folder counts"),
        ({"media_folder_id": None, "media_files": None}, False, "explicit Nones"),
        ({"media_files": "1,2"}, False, "files as str is not a pool"),
    ]
    for item, exp, label in rows:
        got = has_media_source(item)
        assert got is exp, f"has_media_source[{label}]: got {got!r}, expected {exp!r}"


def case_pick_media_no_client_deterministic():
    rows = [
        ({}, [], "no pool"),
        ({"media_files": []}, [], "empty pool"),
        ({"media_files": ["x"]}, [], "junk-only pool"),
        ({"media_folder_id": 5}, [], "folder without client -> no pull"),
        ({"media_files": [9]}, [9], "single id"),
        ({"media_files": [9], "media_count": 5}, [9], "count clamped to pool"),
        ({"media_files": ["9"], "media_count": 0}, [9], "count 0 -> 1"),
        ({"media_files": [9], "media_count": -3}, [9], "negative count -> 1"),
        ({"media_files": [9], "media_count": "abc"}, [9], "bad count -> 1"),
    ]
    for item, exp, label in rows:
        got = pick_media(item)
        assert got == exp, f"pick_media[{label}]: got {got!r}, expected {exp!r}"


def case_pick_media_seeded_sample():
    # (item, pool after int_list, effective count, label)
    rows = [
        ({"media_files": [1, 2, 3, 4, 5]}, [1, 2, 3, 4, 5], 1, "default count 1"),
        ({"media_files": [1, 2, 3, 4, 5], "media_count": 3}, [1, 2, 3, 4, 5], 3, "count 3"),
        ({"media_files": [1, 2, 3], "media_count": "2"}, [1, 2, 3], 2, "count as str"),
        ({"media_files": [1, 2, 3], "media_count": 99}, [1, 2, 3], 3, "count clamped"),
        ({"media_files": [1, "x", 3, None]}, [1, 3], 1, "junk dropped before sample"),
        ({"media_files": [4, 4, 5], "media_count": 3}, [4, 4, 5], 3, "explicit dupes kept"),
    ]
    for item, pool, n, label in rows:
        for seed in SEEDS:
            random.seed(seed)
            got = pick_media(item)
            exp = random.Random(seed).sample(pool, n)
            assert got == exp, f"pick_media[{label} seed={seed}]: got {got!r}, expected {exp!r}"
            assert len(got) == n, f"pick_media[{label} seed={seed}]: len {len(got)} != {n}"


class _FakeVault:
    """Returns `page` verbatim from vault_media (or raises when `boom`)."""

    def __init__(self, page=None, boom=False):
        self.page = page if page is not None else {}
        self.boom = boom
        self.calls = []

    def vault_media(self, **kw):
        self.calls.append(kw)
        if self.boom:
            raise RuntimeError("vault down")
        return self.page


def _photo(i, url="u", drm=None):
    return {"id": i, "files": {"full": {"url": url, "drm": drm}}}


def case_pick_media_with_client():
    """Folder pull: non-DRM photos with a url join the pool (deduped against the
    explicit ids, explicit ids first); a failing pull is swallowed."""
    items = [_photo(10), _photo(11, drm={"x": 1}), _photo(12, url=""), _photo(2),
             {"id": "bad", "files": {"full": {"url": "u"}}}, {"id": 13}, _photo("14")]
    rows = [
        ({"media_folder_id": "5", "media_files": [1, 2], "media_count": 9},
         _FakeVault({"list": items}), [1, 2, 10, 14], "union, dedup, drm/no-url/bad-id dropped"),
        ({"media_folder_id": 5, "media_count": 9},
         _FakeVault({"list": items}), [10, 2, 14], "folder only, OF order"),
        ({"media_folder_id": 5, "media_files": [1], "media_count": 9},
         _FakeVault(boom=True), [1], "pull failure swallowed"),
        ({"media_folder_id": 5, "media_count": 9},
         _FakeVault(boom=True), [], "pull failure + no files -> []"),
        ({"media_folder_id": "nope", "media_files": [1], "media_count": 9},
         _FakeVault({"list": items}), [1], "non-int folder id swallowed"),
    ]
    for item, fake, pool, label in rows:
        random.seed(3)
        got = pick_media(item, client=fake)
        exp = random.Random(3).sample(pool, len(pool)) if pool else []
        assert got == exp, f"pick_media+client[{label}]: got {got!r}, expected {exp!r}"
    fake = _FakeVault({"list": items})
    pick_media({"media_folder_id": "5"}, client=fake)
    assert fake.calls == [{"type": "photo", "list_id": 5, "limit": 48,
                           "field": "recent", "sort": "desc"}], \
        f"pick_media+client[vault call shape]: got {fake.calls!r}"


def case_pick_media_vault_page_shapes():
    """The vault page envelope, driven through pick_media's folder pull."""
    rows = [
        ({"list": [_photo(1)]}, [1], "list envelope"),
        ({"items": [_photo(2)]}, [2], "items envelope"),
        ({}, [], "empty page"),
        ({"list": [], "items": [_photo(3)]}, [3], "empty list falls to items"),
        ({"list": [{"id": 4, "files": None}]}, [], "files None"),
        ({"list": [_photo(5), _photo(6)], "items": [_photo(7)]}, [5, 6], "list wins over items"),
    ]
    for page, pool, label in rows:
        random.seed(3)
        got = pick_media({"media_folder_id": 1, "media_count": 9}, client=_FakeVault(page))
        exp = random.Random(3).sample(pool, len(pool)) if pool else []
        assert got == exp, f"pick_media+page[{label}]: got {got!r}, expected {exp!r}"


_harness.run(
    case_int_list,
    case_pick_text_no_pool,
    case_pick_text_seeded_pool,
    case_has_media_source,
    case_pick_media_no_client_deterministic,
    case_pick_media_seeded_sample,
    case_pick_media_with_client,
    case_pick_media_vault_page_shapes,
)
