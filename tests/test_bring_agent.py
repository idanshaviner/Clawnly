"""Tests for bring_agent.py -- the bring-your-agent signup (preview + confirm)."""

import json

import bring_agent
import db
import dossier
from conftest import FakeClient, json_body, run

TEXT = "You're 31 and moved here eight months ago. You miss long Friday dinners. " * 8


def card_reply():
    return json_body({"essence": "a blunt, warm host", "needs": "consistency",
                      "unknowns": ["job"], "real_vs_public": {"score": 5, "note": "real"}})


def resident():
    db.init_db()
    db.reset_all()
    nb = db.get_or_create_neighborhood("ten-trails", "Ten Trails", 10)
    r = db.get_or_create_resident(nb["id"], "noa@example.com", "magic_link")
    db.record_consent(r["id"])
    return db.get_resident(r["id"])


def test_status_offers_the_prompt_and_sources_before_joining():
    s = bring_agent.status(resident())
    assert s["joined"] is False
    assert s["card"] is None
    assert s["import_prompt"] == dossier.IMPORT_PROMPT
    assert "ChatGPT" in s["sources"]
    assert s["previews_left"] == bring_agent.MAX_PREVIEWS


def test_preview_builds_a_card_and_stores_the_draft_server_side():
    r = resident()
    client = FakeClient(card_queue=[card_reply()])
    state, error = run(bring_agent.preview(r, "  Noa Levi ", "ChatGPT", TEXT, client))
    assert error is None
    assert state["card"]["essence"] == "a blunt, warm host"
    assert state["name"] == "Noa"          # first name only
    assert state["previews_left"] == bring_agent.MAX_PREVIEWS - 1
    saved = db.get_resident(r["id"])
    assert saved["dossier_text"] == TEXT.strip()
    assert saved["dossier_source"] == "ChatGPT"
    assert saved["card"]["needs"] == "consistency"
    assert saved["profile_complete_at"] is None


def test_preview_rejects_bad_input_without_calling_the_ai():
    r = resident()
    client = FakeClient()
    cases = [("", "ChatGPT", TEXT), ("Noa", "MySpace", TEXT), ("Noa", "ChatGPT", "too short")]
    for name, source, text in cases:
        state, error = run(bring_agent.preview(r, name, source, text, client))
        assert state is None and error
    assert client.calls == []


def test_preview_limit_stops_runaway_calls():
    r = resident()
    client = FakeClient(card_queue=[card_reply()] * bring_agent.MAX_PREVIEWS)
    i = 0
    while i < bring_agent.MAX_PREVIEWS:
        r = db.get_resident(r["id"])
        state, error = run(bring_agent.preview(r, "Noa", "Claude", TEXT, client))
        assert error is None
        i += 1
    state, error = run(bring_agent.preview(db.get_resident(r["id"]), "Noa", "Claude", TEXT, client))
    assert state is None and "previews" in error
    assert len(client.calls) == bring_agent.MAX_PREVIEWS


def test_confirm_needs_a_card_first():
    state, error = bring_agent.confirm(resident())
    assert state is None and "card" in error


def test_confirm_joins_with_the_stored_draft_and_locks_it():
    r = resident()
    run(bring_agent.preview(r, "Noa", "Muse", TEXT, FakeClient(card_queue=[card_reply()])))
    state, error = bring_agent.confirm(db.get_resident(r["id"]))
    assert error is None and state["joined"] is True
    joined = db.get_resident(r["id"])
    assert joined["profile_complete_at"] is not None
    # once joined, previews can't overwrite the dossier the agent carries
    client = FakeClient()
    state, error = run(bring_agent.preview(joined, "Other", "Claude", TEXT + " extra", client))
    assert state is None and "already in" in error
    assert client.calls == []
    assert db.get_resident(r["id"])["dossier_source"] == "Muse"
    # confirming again is harmless
    state, error = bring_agent.confirm(joined)
    assert error is None and state["joined"] is True


def test_signup_is_in_the_neighborhood_log_including_the_ai_call():
    r = resident()
    run(bring_agent.preview(r, "Noa", "ChatGPT", TEXT, FakeClient(card_queue=[card_reply()])))
    bring_agent.confirm(db.get_resident(r["id"]))
    texts = [e["text"] for e in db.list_neighborhood_events(r["neighborhood_id"])]
    assert texts[0] == "Noa built their agent's card from ChatGPT (real-you score 5/5)."
    assert texts[1] == "Noa joined with their agent from ChatGPT. 1 of 10 needed for the first round."
    calls = db.list_signup_ai_calls(r["neighborhood_id"])
    assert len(calls) == 1
    assert calls[0]["purpose"] == "card" and calls[0]["resident_id"] == r["id"]
    assert "moved here eight months ago" in calls[0]["messages"][0]["content"]
