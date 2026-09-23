"""Tests for agent_talk.py -- two Claws talking privately, each representing
one person from that person's own dossier only."""

import agent_talk
from conftest import FakeClient, run

NOA = {"id": "s1", "name": "Noa", "source": "ChatGPT", "dossier": "NOA-ONLY: misses Friday dinners."}
MARCUS = {"id": "s2", "name": "Marcus", "source": "Claude", "dossier": "MARCUS-ONLY: wants a Sunday table."}


def speaker_fn(system, content):
    name = system.split("Clawnly agent of ")[1].split(".")[0]
    return name + " needs friends who show up."


def test_conversation_alternates_for_six_turns():
    client = FakeClient(agent_fn=speaker_fn)
    turns = run(agent_talk.converse(NOA, MARCUS, client))
    assert len(turns) == agent_talk.TURNS
    by = [t["by"] for t in turns]
    assert by == ["s1", "s2", "s1", "s2", "s1", "s2"]
    assert turns[1]["text"] == "Marcus needs friends who show up."


def test_each_agent_sees_only_its_own_persons_dossier():
    client = FakeClient(agent_fn=speaker_fn)
    run(agent_talk.converse(NOA, MARCUS, client))
    i = 0
    for _, kwargs in client.calls:
        system = kwargs["system"]
        if i % 2 == 0:
            assert "NOA-ONLY" in system and "MARCUS-ONLY" not in system
        else:
            assert "MARCUS-ONLY" in system and "NOA-ONLY" not in system
        i += 1


def test_agents_must_say_i_dont_know_instead_of_inventing():
    client = FakeClient(agent_fn=speaker_fn)
    run(agent_talk.converse(NOA, MARCUS, client))
    system = client.calls[0][1]["system"]
    assert "don't know" in system
    assert "Never invent" in system
    assert "Never pretend to be Noa" in system


def test_prompts_carry_the_transcript_and_the_last_two_messages_close():
    client = FakeClient(agent_fn=speaker_fn)
    run(agent_talk.converse(NOA, MARCUS, client))
    first = client.calls[0][1]
    second = client.calls[1][1]
    assert "you speak first" in first["messages"][0]["content"]
    assert "Noa's agent: Noa needs friends who show up." in second["messages"][0]["content"]
    assert "LAST message" in client.calls[4][1]["system"]
    assert "LAST message" in client.calls[5][1]["system"]
    assert "LAST message" not in client.calls[3][1]["system"]


def test_every_message_is_recorded_as_it_happens():
    events = []
    client = FakeClient(agent_fn=speaker_fn)
    run(agent_talk.converse(NOA, MARCUS, client,
                            record=lambda actor, kind, text, ref: events.append((actor, kind, text, ref)), ref="7"))
    assert len(events) == 6
    assert events[0] == ("agent", "message", "Noa's agent: Noa needs friends who show up.", "7")
