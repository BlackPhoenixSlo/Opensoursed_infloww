"""Regression: build_structured_nickname must be a fixed point under its own
output. welcome_chatter_for_info._maybe_push_nickname rebuilds the nickname and mirrors it back
into fans.custom_nickname EVERY convo tick, so feeding the structured string back
in as the Name slot used to compound it ('Donovon/chef/25' →
'Donovon/chef/25/chef/25/chef/nanaimo,canada/25/…') until the 70-char cap. The fix
pulls only the NAME slot out of custom_nickname (via name_token).

Plain-assert, no pytest — run directly: `python tests/test_structured_nickname.py`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from automations._common import build_structured_nickname  # noqa: E402


class _Fan:
    def __init__(self, **kw):
        self.real_name = None
        self.of_display_name = None
        self.custom_nickname = None
        self.his_age = None
        self.home_country = None
        self.home_city = None
        self.occupation = None
        for k, v in kw.items():
            setattr(self, k, v)


def case_stable_under_self_mirror():
    """Three ticks that mirror the output back into custom_nickname must not grow."""
    f = _Fan(of_display_name="Donovon", his_age="25",
             home_city="nanaimo", home_country="canada", occupation="chef")
    seen = []
    for _ in range(3):
        nick = build_structured_nickname(f)
        f.custom_nickname = nick          # what _maybe_push_nickname does each tick
        seen.append(nick)
    assert seen[0] == seen[1] == seen[2], f"nickname drifted across ticks: {seen}"
    assert seen[0] == "Donovon/nanaimo,canada/25/chef", seen[0]
    print("[ok] case_stable_under_self_mirror")


def case_self_heals_corrupted_value():
    """An already-compounded custom_nickname collapses back to one clean record."""
    f = _Fan(of_display_name="Donovon", his_age="25",
             home_city="nanaimo", home_country="canada", occupation="chef",
             custom_nickname="Donovon/chef/25/chef/25/chef/nanaimo,canada/25/chef/")
    assert build_structured_nickname(f) == "Donovon/nanaimo,canada/25/chef"
    print("[ok] case_self_heals_corrupted_value")


def case_real_name_still_wins():
    """A populated real_name keeps precedence over the custom_nickname slot."""
    f = _Fan(real_name="Mike", custom_nickname="Donovon/chef/25", occupation="chef")
    assert build_structured_nickname(f) == "Mike/chef"
    print("[ok] case_real_name_still_wins")


def case_thin_profile_short_nick():
    """Empty segments drop; nothing known → '' (unchanged behaviour)."""
    assert build_structured_nickname(_Fan(of_display_name="Donovon")) == "Donovon"
    assert build_structured_nickname(_Fan()) == ""
    print("[ok] case_thin_profile_short_nick")


def case_unknown_name_keeps_its_slot():
    """No name → the slot is MARKED, not dropped. Dropping it slid the location up
    ('Canada/office job'), which reads as if the fan is called Canada — both to the
    team in the OF chat header and to anything parsing slot 0. And '_' must survive
    the self-mirror without ever becoming a name."""
    f = _Fan(of_display_name="", home_country="Canada", occupation="office job")
    seen = []
    for _ in range(3):
        nick = build_structured_nickname(f)
        f.custom_nickname = nick            # what _maybe_push_nickname does each tick
        seen.append(nick)
    assert seen == ["_/Canada/office job"] * 3, seen
    # a place in the Name slot is dropped, and the slot is marked rather than closed
    g = _Fan(of_display_name="Canada", home_country="Canada", occupation="office job")
    assert build_structured_nickname(g) == "_/Canada/office job"
    # nothing at all known stays '' — no bare '_' record
    assert build_structured_nickname(_Fan()) == ""
    print("[ok] case_unknown_name_keeps_its_slot")


if __name__ == "__main__":
    case_stable_under_self_mirror()
    case_self_heals_corrupted_value()
    case_real_name_still_wins()
    case_thin_profile_short_nick()
    case_unknown_name_keeps_its_slot()
    print("all cases passed")
