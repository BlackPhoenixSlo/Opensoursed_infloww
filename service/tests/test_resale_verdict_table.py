#!/usr/bin/env python3
"""
resale_verdict_of — table tests over the re-sale guard's pure half (the shell is
ownership.resale_verdict: loads owned_or_seen_media + the vault mirror's kinds, then calls
this). No DB, no loop:

  case_verdict_table:     owned / seen-not-bought / mixed bundle / empty media, the photo
                          half-fresh boundary, previews (videos still block, photos leave the
                          denominator), unknown or blank kind (no rule), falsy ids dropped,
                          previews outside the send ignored.
  case_owned_media_scope: owned_media lists only the ids the reason is about.
  case_never_mutates:     inputs untouched.

Run: ./venv/bin/python service/tests/test_resale_verdict_table.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

from ownership import (  # noqa: E402
    RESALE_MOSTLY_OWNED_PHOTOS as PHOTOS, RESALE_OWNED_VIDEO as VIDEO, ResaleVerdict,
    resale_verdict_of,
)

V1, V2 = 101, 102                      # videos
P1, P2, P3, P4 = 201, 202, 203, 204    # photos
U1 = 301                               # unknown to the vault mirror
B1 = 401                               # blank kind (VaultItem.kind NULL)
KINDS = {V1: "video", V2: "video", P1: "photo", P2: "photo", P3: "photo", P4: "photo",
         B1: ""}

# (label, owned, media, previews) -> expected
TABLE = [
    ("empty media", {V1}, [], None, ResaleVerdict("", [], [], 0)),
    ("only falsy ids", {V1}, [0, None], None, ResaleVerdict("", [], [], 0)),
    ("owned video", {V1}, [V1], None, ResaleVerdict(VIDEO, [V1], [], 0)),
    ("seen-not-bought video", set(), [V1], None, ResaleVerdict("", [], [], 0)),
    ("seen-not-bought photos", {V2}, [P1, P2], None, ResaleVerdict("", [], [], 2)),
    ("one of two videos owned", {V2}, [V1, V2], None, ResaleVerdict(VIDEO, [V2], [], 0)),
    ("owned video in previews still blocks", {V1}, [V1, P1], [V1],
     ResaleVerdict(VIDEO, [V1], [], 1)),
    ("mixed: owned video + fresh photos", {V1}, [V1, P1, P2], None,
     ResaleVerdict(VIDEO, [V1], [], 2)),
    ("mixed: video outranks stale photos", {V1, P1, P2}, [V1, P1, P2], None,
     ResaleVerdict(VIDEO, [V1], [P1, P2], 2)),
    ("mixed: fresh video + stale photos", {P1, P2}, [V2, P1, P2, P3], None,
     ResaleVerdict(PHOTOS, [], [P1, P2], 3)),
    ("photos: exactly half fresh allowed", {P1}, [P1, P2], None,
     ResaleVerdict("", [], [P1], 2)),
    ("photos: 2 of 4 owned allowed", {P1, P2}, [P1, P2, P3, P4], None,
     ResaleVerdict("", [], [P1, P2], 4)),
    ("photos: 2 of 3 owned blocks", {P1, P2}, [P1, P2, P3], None,
     ResaleVerdict(PHOTOS, [], [P1, P2], 3)),
    ("photos: all owned blocks", {P1}, [P1], None, ResaleVerdict(PHOTOS, [], [P1], 1)),
    ("owned photo in previews leaves the denominator", {P1}, [P1, P2], [P1],
     ResaleVerdict("", [], [], 1)),
    ("all photos previews -> no photo rule", {P1, P2}, [P1, P2], [P1, P2],
     ResaleVerdict("", [], [], 0)),
    ("previews outside the send ignored", {P1, P2}, [P1, P2, P3], [P4],
     ResaleVerdict(PHOTOS, [], [P1, P2], 3)),
    ("owned unknown media: no rule", {U1}, [U1], None, ResaleVerdict("", [], [], 0)),
    ("owned blank-kind media: no rule", {B1}, [B1, P1], None, ResaleVerdict("", [], [], 1)),
    ("unknown not in photo denominator", {P1}, [P1, P2, U1], None,
     ResaleVerdict("", [], [P1], 2)),
    ("falsy ids dropped, rest judged", {V1}, [0, V1], [0], ResaleVerdict(VIDEO, [V1], [], 0)),
]


def case_verdict_table():
    for label, owned, media, previews, want in TABLE:
        got = resale_verdict_of(owned, media, KINDS, previews)
        assert got == want, (label, got, want)
        assert got.blocked is bool(want.reason), (label, got)


def case_owned_media_scope():
    v = resale_verdict_of({V1, P1, P2}, [V1, P1, P2], KINDS)
    assert v.owned_media == [V1], v
    v = resale_verdict_of({P1, P2}, [P1, P2, P3], KINDS)
    assert v.owned_media == [P1, P2], v


def case_never_mutates():
    owned, media, previews, kinds = {V1, P1}, [V1, P1, P2], [P1], dict(KINDS)
    resale_verdict_of(owned, media, kinds, previews)
    assert (owned, media, previews, kinds) == ({V1, P1}, [V1, P1, P2], [P1], KINDS)


_harness.run()
