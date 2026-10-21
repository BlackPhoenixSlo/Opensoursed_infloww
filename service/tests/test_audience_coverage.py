#!/usr/bin/env python3
"""
Audience-coverage manifest — every send-capable automation file is classified.

The include-only audience mode is an AUDITED INVARIANT, not a promise: this test
rebuilds the send-capable inventory mechanically (registered kinds + a scan of
service/automations/*.py for the four send primitives — NOT a hand-maintained
grep) and fails on any file the classification in audiences.py doesn't cover.
The R1 drafts' hand tables were all short (grep folklore missed 8 senders);
this is the guard against the next one.

  case_every_send_capable_file_is_classified:
      scan finds a file → AUDIENCE_SENDER_CLASSIFICATION must name it.
  case_no_stale_classifications:
      every classified name exists on disk (a renamed sender can't ghost).
  case_every_registered_kind_with_sends_is_classified:
      the live plugin registry side of the same invariant.
  case_bucket_shapes:
      classification values are only gated / fenced / not_fan_dm /
      exempt:<non-empty reason> — and the fenced set is exactly the four
      broadcast paths.
  case_mass_premade_delegates:
      mass_premade's "fenced" claim is delegation into send_mass_message —
      assert it never grew its own OF broadcast call.

Run: ./venv/bin/python service/tests/test_audience_coverage.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

from pathlib import Path  # noqa: E402

from audience_include import AUDIENCE_SENDER_CLASSIFICATION  # noqa: E402

AUTOMATIONS_DIR = Path(__file__).resolve().parents[1] / "automations"

# The shared outbound primitives. A file that touches ANY of these can put a
# message in front of a fan and must be classified. Fixed list, scanned
# mechanically — extending the send layer means extending this tuple.
_SEND_PRIMITIVES = (
    "send_message",
    "send_mass_message",
    "of_write_paced",
    "send_dropping_bad_media",
)


def _send_capable_files() -> set[str]:
    out: set[str] = set()
    for p in sorted(AUTOMATIONS_DIR.glob("*.py")):
        if p.name == "__init__.py" or p.name.startswith(("_drive_", "_verify_")):
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        if any(tok in src for tok in _SEND_PRIMITIVES):
            out.add(p.stem)
    return out


def case_every_send_capable_file_is_classified():
    found = _send_capable_files()
    assert found, "scan found no send-capable files — the scan itself broke"
    unclassified = sorted(found - set(AUDIENCE_SENDER_CLASSIFICATION))
    assert not unclassified, (
        f"send-capable but UNCLASSIFIED for the audience fence: {unclassified} — "
        "add each to audience_include.AUDIENCE_SENDER_CLASSIFICATION as gated / fenced / "
        "exempt:<reason> / not_fan_dm AND wire the gate if gated")


# Kinds that are REGISTERED but do not own a file: a second `@register` inside
# another automation's module, so the lane gets its own executor queue without
# becoming its own automation. The map records WHERE each one lives, so the
# staleness check below still has a real file to look for — a renamed sender
# cannot ghost just by being co-located.
_KINDS_IN_ANOTHER_FILE = {
    # Smart Messages' lifecycle Triggers: four kinds, one sweep.
    "expiry_message": "lifecycle_messages",
    "expired_message": "lifecycle_messages",
    "resubscribe_message": "lifecycle_messages",
    "birthday_message": "lifecycle_messages",
}


def case_no_stale_classifications():
    missing = sorted(
        name for name in AUDIENCE_SENDER_CLASSIFICATION
        if not (AUTOMATIONS_DIR /
                f"{_KINDS_IN_ANOTHER_FILE.get(name, name)}.py").exists()
    )
    assert not missing, f"classified but no such automation file: {missing}"

    # A co-located kind must still actually BE registered in the file it claims,
    # or this map is just a way to silence the check above.
    from automation_registry import load_automation_plugins, registered_kinds
    load_automation_plugins()
    live = set(registered_kinds())
    for kind, home in _KINDS_IN_ANOTHER_FILE.items():
        assert kind in live, f"{kind} claims to live in {home}.py but is not registered"
        src = (AUTOMATIONS_DIR / f"{home}.py").read_text(encoding="utf-8")
        assert f'@register("{kind}")' in src, \
            f"{kind} is classified as living in {home}.py but registers elsewhere"


def case_every_registered_kind_with_sends_is_classified():
    from automation_registry import load_automation_plugins, registered_kinds
    load_automation_plugins()
    kinds = registered_kinds()
    assert kinds, "plugin registry is empty — load failed"
    holes = []
    for kind in kinds:
        p = AUTOMATIONS_DIR / f"{kind}.py"
        if not p.exists():
            continue  # registered elsewhere (scrape_chats) or aliased kind
        src = p.read_text(encoding="utf-8", errors="replace")
        if any(tok in src for tok in _SEND_PRIMITIVES):
            if kind not in AUDIENCE_SENDER_CLASSIFICATION:
                holes.append(kind)
    assert not holes, f"registered send-capable kinds missing a classification: {holes}"


def case_bucket_shapes():
    buckets = {"gated": [], "fenced": [], "not_fan_dm": [], "exempt": []}
    for name, cls in AUDIENCE_SENDER_CLASSIFICATION.items():
        base = cls.split(":", 1)[0]
        assert base in buckets, f"{name}: unknown classification {cls!r}"
        if base == "exempt":
            reason = cls.split(":", 1)[1] if ":" in cls else ""
            assert reason.strip(), f"{name}: exempt needs a NAMED reason"
        buckets[base].append(name)
    assert set(buckets["fenced"]) == {
        "send_mass_message", "mass_premade",
    }, buckets["fenced"]
    # + smart_list_sync (W7 7.2): OF list membership writes, never a message.
    # + s4s_post (W7 7.6): uploads the partner's S4S media for a wall post.
    assert set(buckets["not_fan_dm"]) == {"auto_posts", "auto_stories", "smart_list_sync", "s4s_post"}, \
        buckets["not_fan_dm"]
    # The gated set may only GROW (a sender leaving it must be re-justified).
    # 16 → 15 on 2026-08-19: the deep_convo engine was REMOVED outright — the
    # sender no longer exists to classify, which is the one valid way out.
    assert len(buckets["gated"]) >= 15, buckets["gated"]
    # 5 → 6 on 2026-09-06: `image_reply` split out of tip_reward as its own KIND.
    # 6 → 3: tip_reward, image_reply and make_right were REMOVED outright — the
    # senders no longer exist to classify.
    assert len(buckets["exempt"]) == 3, buckets["exempt"]


def case_mass_premade_delegates():
    src = (AUTOMATIONS_DIR / "mass_premade.py").read_text(encoding="utf-8")
    assert "send_mass_run(" in src, "mass_premade no longer delegates?"
    assert "client.send_mass_message" not in src, (
        "mass_premade grew its own OF broadcast call — its 'fenced' "
        "classification rests on delegation into send_mass_message")
    assert "client.send_message" not in src, (
        "mass_premade grew a direct fan DM — reclassify and gate it")


_harness.run()
