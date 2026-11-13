#!/usr/bin/env python3
"""vault_harvest_terms: the OF-search harvest's term list (pure, plain-assert).

Run: cd service/tests && PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_vault_harvest_terms.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vault_harvest_terms as h  # noqa: E402


def case_seed_is_bigger_and_unique() -> None:
    assert len(h.SEED) >= 150, len(h.SEED)
    assert len(set(h.SEED)) == len(h.SEED), "duplicate seed term"
    assert h.harvest_terms([])[: len(h.SEED)] == list(h.SEED)


def case_account_terms_rank_and_filter() -> None:
    rows = [
        {"tags": ["Red_Lingerie", "watermark", "mirror selfie"], "clothing_items": ["red lingerie"],
         "setting": "bedroom", "acts": ["posing"], "toys": ["pink wand"]},
        {"tags": ["red lingerie", "a very long phrase of four words"], "setting": "bedroom",
         "toys": ["pink wand"]},
        {"tags": ["red lingerie"], "setting": "bedroom", "toys": ["pink wand"], "position": "other"},
        {"tags": ["red lingerie"]},
        None, "junk", {"tags": "not a list but fine"},
    ]
    got = h.account_terms(rows, min_count=3)
    # one vote per item: "red lingerie" twice on row 0 still counts once there
    assert got[0] == "red lingerie" and set(got) == {"red lingerie", "bedroom", "pink wand"}, got
    assert h.account_terms(rows, min_count=1, top=1) == ["red lingerie"]
    terms = h.harvest_terms(rows)
    assert terms.count("bedroom") == 1, "seed term not repeated"
    assert terms[len(h.SEED):][0] == "red lingerie" and "pink wand" in terms, terms[len(h.SEED):]


if __name__ == "__main__":
    for c in (case_seed_is_bigger_and_unique, case_account_terms_rank_and_filter):
        c()
        print("ok", c.__name__)
