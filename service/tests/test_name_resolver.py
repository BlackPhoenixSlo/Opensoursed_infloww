import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from automations._common import is_greetable_name, name_token, resolve_fan_name  # noqa: E402


def _eq(got, exp, label):
    assert got == exp, f"[FAIL] {label}: got {got!r}, expected {exp!r}"
    print(f"[ok] {label}: {got!r}")


def main() -> None:
    _eq(name_token("John/Orange City,USA/Horny-Fan", last=True), "John", "structured_name_slot")
    _eq(name_token("Sexy Sofie", last=True), "Sofie", "drop_adjective")
    _eq(name_token("u53569558"), "", "reject_handle")
    _eq(name_token("xx_gamer_99"), "", "reject_lowercase_handle")
    _eq(name_token("Whistler,Canada/Whale", last=True), "", "reject_location_only")
    _eq(name_token("Vancouver Island,Canada/Spender", last=True), "", "reject_location_multiword")
    _eq(name_token(""), "", "reject_empty")
    _eq(name_token("USA/Free", last=True), "", "reject_country_code")
    _eq(name_token("UK/Spender", last=True), "", "reject_country_code_short")

    _eq(resolve_fan_name({"real_name": "Alex"}), "Alex", "real_name_wins")
    _eq(resolve_fan_name({"generated_nickname": "Sexy John/City"}), "John",
        "generated_label_parsed")
    _eq(resolve_fan_name({"of_display_name": "garrett baydala"}), "garrett baydala",
        "display_chain_raw")

    _eq(resolve_fan_name({"generated_nickname": "Kentucky,USA/Musician"}), "",
        "location_label_is_not_a_name")
    _eq(resolve_fan_name({"generated_nickname": "Vancouver,Canada/39"}), "",
        "city_country_label_is_not_a_name")
    _eq(resolve_fan_name({"generated_nickname": "USA/Free",
                          "of_display_name": "Foxy's Hubby Jeremiah"}),
        "Foxy's Hubby Jeremiah", "display_name_beats_country_label")
    _eq(resolve_fan_name({"custom_nickname": "John/Orange City,USA/Horny-Fan"}), "John",
        "custom_nickname_fallback")
    _eq(resolve_fan_name({"of_username": "", "of_display_name": "", "real_name": "",
                          "custom_nickname": "John/Orange City,USA/Horny-Fan"}), "John",
        "screenshot_fan")
    _eq(name_token("Canada/Canada/office job", last=True), "", "reject_country_name_slot")
    _eq(name_token("Australia/Spender", last=True), "", "reject_country_au")
    _eq(name_token("SLOVEnian/Free", last=True), "", "reject_demonym")
    _eq(name_token("Hawaii/34/Contractor", last=True), "", "reject_us_state")
    _eq(name_token("New Zealand/Whale", last=True), "", "reject_multiword_place")
    _eq(name_token("Spender", last=True), "", "reject_spend_tier")
    _eq(name_token("Chad/Toronto,Canada/31", last=True), "Chad", "keep_chad")
    _eq(name_token("Jordan/Texas,USA/28", last=True), "Jordan", "keep_jordan")

    _eq(resolve_fan_name({"real_name": "", "generated_nickname": "Canada/Office job/Spender",
                          "custom_nickname": "Canada/Canada/office job",
                          "of_display_name": "", "home_country": "Canada"}), "",
        "country_label_both_columns")
    _eq(resolve_fan_name({"real_name": "Kelowna", "home_city": "Kelowna"}), "",
        "own_city_is_not_a_name")
    _eq(resolve_fan_name({"of_display_name": "Chad", "home_country": "Chad"}), "",
        "own_country_beats_the_name_exception")
    _eq(resolve_fan_name({"real_name": "Austin", "home_city": "Denver"}), "Austin",
        "city_name_kept_when_not_his_own")

    _eq(resolve_fan_name({"of_display_name": "u1000001"}), "", "reject_numeric_handle")
    _eq(resolve_fan_name({"of_display_name": "FanB10"}), "", "reject_digit_handle")
    _eq(resolve_fan_name({"of_display_name": "Fan_c"}), "", "reject_underscore_handle")
    _eq(resolve_fan_name({"of_display_name": "Fan_g22",
                          "custom_nickname": "Daryl/Kelowna,Canada/44"}), "Daryl",
        "handle_falls_through_to_nickname")
    _eq(resolve_fan_name({"of_display_name": "garrett baydala"}), "garrett baydala",
        "plain_display_name_still_kept")

    _eq(resolve_fan_name({"custom_nickname": "Tyren", "of_display_name": "Fan_e"}),
        "Tyren", "curated_beats_display_name")
    _eq(resolve_fan_name({"custom_nickname": "Garrett/Delta,Canada/30",
                          "generated_nickname": "Kyle/Delta,Canada/30"}), "Garrett",
        "curated_beats_ai_label")
    _eq(resolve_fan_name({"real_name": "Mike", "custom_nickname": "Garrett"}), "Mike",
        "confirmed_real_name_still_wins")

    # OF stores name fields HTML-escaped; stripping the entity to letters invents names (Chrisamp).
    _eq(name_token("Chris&amp;Char"), "Chris", "html_entity_and_ampersand")
    _eq(name_token("Soffy Shine &lt;33"), "Soffy", "html_entity_lt")
    _eq(resolve_fan_name({"custom_nickname": "Chris&amp;Char"}), "Chris",
        "curated_couple_account")

    _eq(name_token("/Christopher/"), "Christopher", "leading_slash_is_not_an_empty_name")
    _eq(resolve_fan_name({"custom_nickname": "/Christopher/"}), "Christopher",
        "leading_slash_fan_keeps_his_name")
    _eq(name_token("_/Canada/office job", last=True), "", "marker_is_still_never_a_name")

    for code in ("USA", "US", "UK", "uae", "NZ"):
        assert not is_greetable_name(code), f"[FAIL] is_greetable_name({code!r})"
    _eq(resolve_fan_name({"of_display_name": "USA"}), "", "country_code_display_name")
    _eq(resolve_fan_name({"custom_nickname": "USA/Buyer"}), "", "country_code_label")
    print("[ok] country codes rejected by the predicate itself")

    for good in ("Garrett", "José", "Kuiokalani Lee", "Chad", "Jordan"):
        assert is_greetable_name(good), f"[FAIL] is_greetable_name({good!r}) should be True"
    for bad in ("", "u1000001", "FanB10", "Fan_c", ".", ",", "Canada",
                "New Zealand", "Spender", "hawaii"):
        assert not is_greetable_name(bad), f"[FAIL] is_greetable_name({bad!r}) should be False"
    assert not is_greetable_name("Kelowna", here=("Canada", "Kelowna")), "[FAIL] own city"
    assert is_greetable_name("Kelowna", here=("Canada", "Delta")), "[FAIL] someone else's city"
    print("[ok] is_greetable_name: 5 names kept, 10 non-names rejected, own-city caught")

    _eq(resolve_fan_name({}), "", "nothing")
    _eq(resolve_fan_name(None), "", "none")

    print("all cases passed")


if __name__ == "__main__":
    main()
