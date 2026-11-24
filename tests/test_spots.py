"""Tests for spots.py -- the public meetup spots rule (admin input + the hub's pick)."""

import spots


# ----- clean_spots: what an admin types ---------------------------------------

def test_clean_spots_trims_dedupes_and_keeps_order():
    cleaned, problem = spots.clean_spots(["  The Commons ", "the commons", "Trail   loop", "", "   "])
    assert problem is None
    assert cleaned == ["The Commons", "Trail loop"]


def test_clean_spots_drops_control_characters_and_newlines():
    cleaned, problem = spots.clean_spots(["Cafe\x07 Row", "Library\nreading room"])
    assert problem is None
    assert cleaned == ["Cafe Row", "Libraryreading room"]


def test_clean_spots_rejects_bad_input_with_a_message():
    assert spots.clean_spots("The Commons")[1] == "Send the spots as a list."
    assert spots.clean_spots(None)[1] == "Send the spots as a list."
    assert spots.clean_spots(["ok", 5])[1] == "Each spot must be text."
    assert spots.clean_spots([])[1] == "Add at least one public spot."
    assert spots.clean_spots(["", "  "])[1] == "Add at least one public spot."
    assert spots.clean_spots(["x" * 81])[1] == "Keep each spot to 80 characters or fewer."
    too_many = []
    i = 0
    while i < 11:
        too_many.append("Spot " + str(i))
        i += 1
    assert spots.clean_spots(too_many)[1] == "Use at most 10 spots."


def test_clean_spots_allows_exactly_the_limits():
    ten = []
    i = 0
    while i < 10:
        ten.append("Spot " + str(i))
        i += 1
    assert spots.clean_spots(ten) == (ten, None)
    assert spots.clean_spots(["x" * 80])[1] is None


# ----- check_spot: the hub's pick ---------------------------------------------

LISTED = ["The Commons", "Trail loop"]


def test_a_listed_spot_passes_untouched():
    invite = {"activity": "walk", "when": "Tue 8am", "where": "Trail loop"}
    fixed, note = spots.check_spot(invite, LISTED)
    assert fixed == invite and note is None


def test_spelling_is_normalised_to_the_listed_spot_without_a_note():
    fixed, note = spots.check_spot({"where": "  the   commons "}, LISTED)
    assert fixed["where"] == "The Commons" and note is None


def test_a_listed_spot_with_detail_after_a_comma_is_accepted():
    fixed, note = spots.check_spot({"where": "The Commons, by the fountain"}, LISTED)
    assert fixed["where"] == "The Commons" and note is None


def test_an_unlisted_place_is_swapped_for_the_first_listed_spot_and_noted():
    invite = {"activity": "dinner", "when": "Sunday", "where": "Sam's backyard"}
    fixed, note = spots.check_spot(invite, LISTED)
    assert fixed["where"] == "The Commons"
    assert note == "Meetup place \"Sam's backyard\" is not a listed public spot: used \"The Commons\"."
    # everything else on the invite is kept, and the caller's dict is not changed
    assert fixed["activity"] == "dinner" and fixed["when"] == "Sunday"
    assert invite["where"] == "Sam's backyard"


def test_a_place_that_only_starts_like_a_spot_is_not_that_spot():
    # "The Commons Cafe" is a different place from "The Commons"
    fixed, note = spots.check_spot({"where": "The Commons Cafe"}, LISTED)
    assert fixed["where"] == "The Commons" and note is not None


def test_a_missing_place_gets_the_first_listed_spot():
    fixed, note = spots.check_spot({"activity": "walk"}, LISTED)
    assert fixed["where"] == "The Commons"
    assert note == "The hub named no meetup place: used \"The Commons\"."


def test_with_no_spots_the_place_is_kept_and_the_log_says_it_was_not_checked():
    fixed, note = spots.check_spot({"where": "Seattle"}, [])
    assert fixed["where"] == "Seattle"
    assert "No public meetup spots are set" in note and "\"Seattle\" was not checked" in note
