"""Tests for dossier.py -- bringing your agent: pasted AI portrait -> card."""

import pytest

import dossier
from conftest import FakeClient, json_body, run

LONG_TEXT = "You're 31 and moved to Seattle eight months ago. " * 12


def full_card(**overrides):
    card = {"essence": "a blunt, warm host", "chapter": "new in town", "values": ["honesty"],
            "gives": "remembers birthdays", "needs": "consistency", "energy": "small tables",
            "humor": "dry", "missing": "an 11pm friend", "not_a_fit": ["flakes"],
            "free": "Friday evenings", "area": "Capitol Hill", "unknowns": ["job"],
            "real_vs_public": {"score": 5, "note": "specific and vulnerable"}}
    card.update(overrides)
    return card


def test_short_text_is_rejected_before_any_call():
    client = FakeClient()
    with pytest.raises(ValueError):
        run(dossier.build_card("ChatGPT", "I like hiking.", client))
    assert client.calls == []


def test_build_card_sends_the_whole_text_and_cleans_the_reply():
    client = FakeClient(card_queue=[json_body(full_card())])
    card = run(dossier.build_card("Claude", LONG_TEXT, client))
    assert client.kinds() == ["card"]
    assert "moved to Seattle" in client.calls[0][1]["messages"][0]["content"]
    assert card["essence"] == "a blunt, warm host"
    assert card["real_vs_public"] == {"score": 5, "note": "specific and vulnerable"}


def test_missing_or_malformed_fields_read_as_unknown_not_invented():
    card = dossier.clean_card({"essence": "", "values": ["honesty", 7, ""], "chapter": None,
                               "real_vs_public": {"score": 9, "note": "x"}})
    assert card["essence"] == "unknown"
    assert card["chapter"] == "unknown"
    assert card["values"] == ["honesty"]
    assert card["unknowns"] == []
    assert card["real_vs_public"] is None


def test_unparseable_reply_becomes_an_all_unknown_card():
    client = FakeClient(card_queue=["sorry, I can't do that"])
    card = run(dossier.build_card("Muse", LONG_TEXT, client))
    assert card["needs"] == "unknown"
    assert card["values"] == []


def test_card_text_lists_every_field_for_the_hub():
    text = dossier.card_text(dossier.clean_card(full_card()))
    assert "Needs from friends: consistency" in text
    assert "Unknowns: job" in text
    assert dossier.card_text(None) == "(no card yet)"


def test_import_prompt_asks_for_the_real_person_not_the_public_one():
    assert "social" in dossier.IMPORT_PROMPT
    assert "unknown" in dossier.IMPORT_PROMPT
