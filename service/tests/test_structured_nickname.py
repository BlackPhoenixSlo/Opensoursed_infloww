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
    f = _Fan(of_display_name="Donovon", his_age="25",
             home_city="nanaimo", home_country="canada", occupation="chef")
    seen = []
    for _ in range(3):
        nick = build_structured_nickname(f)
        f.custom_nickname = nick
        seen.append(nick)
    assert seen[0] == seen[1] == seen[2], f"nickname drifted across ticks: {seen}"
    assert seen[0] == "Donovon/nanaimo,canada/25/chef", seen[0]
    print("[ok] case_stable_under_self_mirror")


def case_self_heals_corrupted_value():
    f = _Fan(of_display_name="Donovon", his_age="25",
             home_city="nanaimo", home_country="canada", occupation="chef",
             custom_nickname="Donovon/chef/25/chef/25/chef/nanaimo,canada/25/chef/")
    assert build_structured_nickname(f) == "Donovon/nanaimo,canada/25/chef"
    print("[ok] case_self_heals_corrupted_value")


def case_real_name_still_wins():
    f = _Fan(real_name="Mike", custom_nickname="Donovon/chef/25", occupation="chef")
    assert build_structured_nickname(f) == "Mike/chef"
    print("[ok] case_real_name_still_wins")


def case_thin_profile_short_nick():
    assert build_structured_nickname(_Fan(of_display_name="Donovon")) == "Donovon"
    assert build_structured_nickname(_Fan()) == ""
    print("[ok] case_thin_profile_short_nick")


def case_unknown_name_keeps_its_slot():
    f = _Fan(of_display_name="", home_country="Canada", occupation="office job")
    seen = []
    for _ in range(3):
        nick = build_structured_nickname(f)
        f.custom_nickname = nick
        seen.append(nick)
    assert seen == ["_/Canada/office job"] * 3, seen
    g = _Fan(of_display_name="Canada", home_country="Canada", occupation="office job")
    assert build_structured_nickname(g) == "_/Canada/office job"
    assert build_structured_nickname(_Fan()) == ""
    print("[ok] case_unknown_name_keeps_its_slot")


if __name__ == "__main__":
    case_stable_under_self_mirror()
    case_self_heals_corrupted_value()
    case_real_name_still_wins()
    case_thin_profile_short_nick()
    case_unknown_name_keeps_its_slot()
    print("all cases passed")
