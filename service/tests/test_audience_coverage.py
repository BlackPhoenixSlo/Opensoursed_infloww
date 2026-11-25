#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

from pathlib import Path  # noqa: E402

from audience_include import AUDIENCE_SENDER_CLASSIFICATION  # noqa: E402

AUTOMATIONS_DIR = Path(__file__).resolve().parents[1] / "automations"

# A file touching any of these can reach a fan and must be classified; extend the send layer, extend this tuple.
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


_KINDS_IN_ANOTHER_FILE = {
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
            continue
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
    assert set(buckets["not_fan_dm"]) == {"auto_posts", "auto_stories", "smart_list_sync", "s4s_post"}, \
        buckets["not_fan_dm"]
    # The gated set may only grow; a sender leaving it must be re-justified.
    assert len(buckets["gated"]) >= 15, buckets["gated"]
    assert len(buckets["exempt"]) == 5, buckets["exempt"]


def case_mass_premade_delegates():
    src = (AUTOMATIONS_DIR / "mass_premade.py").read_text(encoding="utf-8")
    assert "send_mass_run(" in src, "mass_premade no longer delegates?"
    assert "client.send_mass_message" not in src, (
        "mass_premade grew its own OF broadcast call — its 'fenced' "
        "classification rests on delegation into send_mass_message")
    assert "client.send_message" not in src, (
        "mass_premade grew a direct fan DM — reclassify and gate it")


_harness.run()
