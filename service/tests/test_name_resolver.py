"""Pure-function tests for the shared fan-name resolver (_common.name_token /
resolve_fan_name). No DB needed — run directly: `python test_name_resolver.py`.

Guards the fix for the "Babe instead of {name}" bug: OF message payloads carry no
name, so ~80% of fans have empty of_username/of_display_name; the resolver must fall
back to the team-curated custom_nickname ('John/City/Tag' → 'John')."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from automations._common import is_greetable_name, name_token, resolve_fan_name  # noqa: E402


def _eq(got, exp, label):
    assert got == exp, f"[FAIL] {label}: got {got!r}, expected {exp!r}"
    print(f"[ok] {label}: {got!r}")


def main() -> None:
    # name_token: structured nicknames keep the real-name slot ...
    _eq(name_token("John/Orange City,USA/Horny-Fan", last=True), "John", "structured_name_slot")
    _eq(name_token("Sexy Sofie", last=True), "Sofie", "drop_adjective")
    # ... and reject handles / location-only / number slots
    _eq(name_token("u53569558"), "", "reject_handle")
    _eq(name_token("xx_gamer_99"), "", "reject_lowercase_handle")
    _eq(name_token("Whistler,Canada/Whale", last=True), "", "reject_location_only")
    _eq(name_token("Vancouver Island,Canada/Spender", last=True), "", "reject_location_multiword")
    _eq(name_token(""), "", "reject_empty")
    # A SHOUTED slot is a country code, never a first name ("u around USA?" in prod).
    _eq(name_token("USA/Free", last=True), "", "reject_country_code")
    _eq(name_token("UK/Spender", last=True), "", "reject_country_code_short")

    # resolve_fan_name: precedence preserved for populated cases ...
    _eq(resolve_fan_name({"real_name": "Alex"}), "Alex", "real_name_wins")
    _eq(resolve_fan_name({"generated_nickname": "Sexy John/City"}), "John",
        "generated_label_parsed")
    _eq(resolve_fan_name({"of_display_name": "garrett baydala"}), "garrett baydala",
        "display_chain_raw")

    # The prod bug: gen_info blanks an unusable name slot, so the LOCATION slides
    # into first position and used to be greeted as the fan's name.
    _eq(resolve_fan_name({"generated_nickname": "Kentucky,USA/Musician"}), "",
        "location_label_is_not_a_name")
    _eq(resolve_fan_name({"generated_nickname": "Vancouver,Canada/39"}), "",
        "city_country_label_is_not_a_name")
    # ...and when it does, a real of_display_name must win instead of the label.
    _eq(resolve_fan_name({"generated_nickname": "USA/Free",
                          "of_display_name": "Foxy's Hubby Jeremiah"}),
        "Foxy's Hubby Jeremiah", "display_name_beats_country_label")
    # ... and the new tail: empty OF fields fall back to the curated nickname
    _eq(resolve_fan_name({"custom_nickname": "John/Orange City,USA/Horny-Fan"}), "John",
        "custom_nickname_fallback")
    # the screenshot fan: only custom_nickname set → 'John' (not 'babe')
    _eq(resolve_fan_name({"of_username": "", "of_display_name": "", "real_name": "",
                          "custom_nickname": "John/Orange City,USA/Horny-Fan"}), "John",
        "screenshot_fan")
    # ── A PLACE IS NEVER A NAME ────────────────────────────────────────────────
    # The model fills an unknown Name slot with the country (no comma, Capitalized,
    # too long to be a shouted code — every earlier check passed it), so 132 prod
    # fans greeted as "Canada" and 50 as "Spender" (the derived spend tier, slid up
    # by _clean_nickname when every other slot was empty).
    _eq(name_token("Canada/Canada/office job", last=True), "", "reject_country_name_slot")
    _eq(name_token("Australia/Spender", last=True), "", "reject_country_au")
    _eq(name_token("SLOVEnian/Free", last=True), "", "reject_demonym")
    _eq(name_token("Hawaii/34/Contractor", last=True), "", "reject_us_state")
    _eq(name_token("New Zealand/Whale", last=True), "", "reject_multiword_place")
    _eq(name_token("Spender", last=True), "", "reject_spend_tier")
    # ...but a place that is ALSO a common first name stays a name (a real Chad
    # keeps his): those are caught per-fan against his own home_country instead.
    _eq(name_token("Chad/Toronto,Canada/31", last=True), "Chad", "keep_chad")
    _eq(name_token("Jordan/Texas,USA/28", last=True), "Jordan", "keep_jordan")

    # the reported fan (fanA577 · 800000519): country in BOTH label columns
    _eq(resolve_fan_name({"real_name": "", "generated_nickname": "Canada/Office job/Spender",
                          "custom_nickname": "Canada/Canada/office job",
                          "of_display_name": "", "home_country": "Canada"}), "",
        "country_label_both_columns")
    # his own city/country is not his name, even when no static list holds it
    _eq(resolve_fan_name({"real_name": "Kelowna", "home_city": "Kelowna"}), "",
        "own_city_is_not_a_name")
    _eq(resolve_fan_name({"of_display_name": "Chad", "home_country": "Chad"}), "",
        "own_country_beats_the_name_exception")
    # ...and someone else's city stays a name (Austin from Denver is Austin)
    _eq(resolve_fan_name({"real_name": "Austin", "home_city": "Denver"}), "Austin",
        "city_name_kept_when_not_his_own")

    # ── A HANDLE IS NEVER A NAME ───────────────────────────────────────────────
    # of_display_name reached the senders verbatim, so 551 prod fans were greeted
    # by their handle ("hey u1000001", "hey FanB10", "hey User11111111") and 37
    # by an underscore one ("hey Fan_c"). A digit or '_' ⇒ not a first name.
    _eq(resolve_fan_name({"of_display_name": "u1000001"}), "", "reject_numeric_handle")
    _eq(resolve_fan_name({"of_display_name": "FanB10"}), "", "reject_digit_handle")
    _eq(resolve_fan_name({"of_display_name": "Fan_c"}), "", "reject_underscore_handle")
    # ...and the chain walks ON to the next source rather than stopping there
    _eq(resolve_fan_name({"of_display_name": "Fan_g22",
                          "custom_nickname": "Daryl/Kelowna,Canada/44"}), "Daryl",
        "handle_falls_through_to_nickname")
    _eq(resolve_fan_name({"of_display_name": "garrett baydala"}), "garrett baydala",
        "plain_display_name_still_kept")

    # ── CURATED BEATS RAW ──────────────────────────────────────────────────────
    # What a human typed outranks the AI label and OF's own display name. The chat
    # lane used to prefer of_display_name and greeted 154 prod fans "hey Fan_e"
    # / "hey Sports Stud" while the team had typed 'Tyren' / 'Scott'. send_welcome
    # always had this order; now there is only one order.
    _eq(resolve_fan_name({"custom_nickname": "Tyren", "of_display_name": "Fan_e"}),
        "Tyren", "curated_beats_display_name")
    _eq(resolve_fan_name({"custom_nickname": "Garrett/Delta,Canada/30",
                          "generated_nickname": "Kyle/Delta,Canada/30"}), "Garrett",
        "curated_beats_ai_label")
    _eq(resolve_fan_name({"real_name": "Mike", "custom_nickname": "Garrett"}), "Mike",
        "confirmed_real_name_still_wins")

    # OF stores these fields HTML-ESCAPED and a couple shares one account. Stripping
    # the entity to letters invented 'Chrisamp'; his name is Chris.
    _eq(name_token("Chris&amp;Char"), "Chris", "html_entity_and_ampersand")
    _eq(name_token("Soffy Shine &lt;33"), "Soffy", "html_entity_lt")
    _eq(resolve_fan_name({"custom_nickname": "Chris&amp;Char"}), "Chris",
        "curated_couple_account")

    # A leading '/' is sloppy human input, not "no name" — the empty name slot has
    # an explicit marker now. Read literally, '/Christopher/' resolved to '' and the
    # nickname sweep was about to overwrite him with '_/Christopher'.
    _eq(name_token("/Christopher/"), "Christopher", "leading_slash_is_not_an_empty_name")
    _eq(resolve_fan_name({"custom_nickname": "/Christopher/"}), "Christopher",
        "leading_slash_fan_keeps_his_name")
    _eq(name_token("_/Canada/office job", last=True), "", "marker_is_still_never_a_name")

    # The bare country CODES were only ever caught by name_token's all-caps rule,
    # so is_greetable_name — which is what the senders and the nickname sweep ask —
    # accepted 'USA' as a first name.
    for code in ("USA", "US", "UK", "uae", "NZ"):
        assert not is_greetable_name(code), f"[FAIL] is_greetable_name({code!r})"
    _eq(resolve_fan_name({"of_display_name": "USA"}), "", "country_code_display_name")
    _eq(resolve_fan_name({"custom_nickname": "USA/Buyer"}), "", "country_code_label")
    print("[ok] country codes rejected by the predicate itself")

    # is_greetable_name is THE predicate the whole lane leans on — test it directly.
    for good in ("Garrett", "José", "Kuiokalani Lee", "Chad", "Jordan"):
        assert is_greetable_name(good), f"[FAIL] is_greetable_name({good!r}) should be True"
    for bad in ("", "u1000001", "FanB10", "Fan_c", ".", ",", "Canada",
                "New Zealand", "Spender", "hawaii"):
        assert not is_greetable_name(bad), f"[FAIL] is_greetable_name({bad!r}) should be False"
    assert not is_greetable_name("Kelowna", here=("Canada", "Kelowna")), "[FAIL] own city"
    assert is_greetable_name("Kelowna", here=("Canada", "Delta")), "[FAIL] someone else's city"
    print("[ok] is_greetable_name: 5 names kept, 10 non-names rejected, own-city caught")

    # truly nothing → '' (caller keeps its soft 'babe')
    _eq(resolve_fan_name({}), "", "nothing")
    _eq(resolve_fan_name(None), "", "none")

    print("all cases passed")


if __name__ == "__main__":
    main()
