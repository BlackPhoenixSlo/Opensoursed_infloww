#!/usr/bin/env python3
"""test_rich_note.py — R2: the app-only spend-tiered rich note (build step 2).

Pins the two facts the adversary corrected:
  • The rich note reads the STORED bullet_points (with its Important: section), NOT the
    5-column fan_data rebuild — so nothing is lost.
  • Length scales with spend, and the OF-bound build_facts_note stays capped at 200.

Run:  ./venv/bin/python service/tests/test_rich_note.py
"""
import _harness  # noqa: F401 — MUST be first

from automations._common import build_rich_note, rich_note_cap, build_facts_note  # noqa: E402

# A stored bullet block like gen_info writes — INCLUDING the Important: section that the
# fan_data rebuild drops.
_STORED = (
    "- Recent: moved to Málaga; birthday in May\n"
    "- Intr: fútbol, gaming\n"
    "- Important: hates being ghosted; pay day is the 1st\n"
    "- Job: electrician\n- Rel: single\n- Kinks: feet"
)
_BIO = "A warm fan from Sevilla who spends steadily and writes daily."


def case_tier_caps_scale_with_spend():
    assert rich_note_cap(0) == 400            # free
    assert rich_note_cap(100) == 800          # buyer ($1)
    assert rich_note_cap(5000) == 1500        # spender ($50)
    assert rich_note_cap(50000) == 3000       # whale ($500)
    assert rich_note_cap(999999) == 3000      # above whale still whale


def case_rich_note_keeps_important_section():
    note = build_rich_note(_STORED, short_bio=_BIO, lifetime_spend_cents=60000)
    assert "Important:" in note, "the rich note must keep the Important section"
    assert "Málaga" in note and "electrician" in note
    assert _BIO in note, "bio appended"


def case_rich_note_respects_tier_cap():
    long_bp = "\n".join(f"- Fact {i}: " + ("x" * 60) for i in range(60))  # ~3900 chars
    free = build_rich_note(long_bp, lifetime_spend_cents=0)
    whale = build_rich_note(long_bp, lifetime_spend_cents=60000)
    assert len(free) <= 400, len(free)
    assert len(whale) <= 3000, len(whale)
    assert len(whale) > len(free), "a whale sees more than a free fan"


def case_rich_note_empty_when_nothing_stored():
    assert build_rich_note(None, "", 0) == ""
    assert build_rich_note("", "", 999999) == ""


def case_of_note_still_200():
    """The OF-bound builder is unchanged — a big facts dict + long bio caps at 200."""
    facts = {"hobbies": "x" * 300, "job": "y" * 300, "relationship": "single",
             "fetishes": "feet", "recent_events": '["moved", "new job"]'}
    of_note = build_facts_note(facts, max_len=200, short_bio="z" * 500)
    assert len(of_note) <= 200, len(of_note)


if __name__ == "__main__":
    _harness.run(
        case_tier_caps_scale_with_spend,
        case_rich_note_keeps_important_section,
        case_rich_note_respects_tier_cap,
        case_rich_note_empty_when_nothing_stored,
        case_of_note_still_200,
    )
