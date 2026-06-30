"""Tests for the REAL multi-round negotiation (propose -> react -> assess)."""

from conftest import FakeClient, json_body, run
from claw import Claw
from negotiation import negotiate
from users import USERS


def claws_for(ids, client):
    by_id = {u["id"]: u for u in USERS}
    return [Claw(by_id[i], client=client) for i in ids]


def interviews_for(ids):
    by_id = {u["id"]: u for u in USERS}
    out = {}
    for i in ids:
        out[i] = {"profile": by_id[i], "q1": "wants low-key meetups", "q2": "free weekday evenings"}
    return out


def proposal(activity, pitch="let's do it"):
    return json_body({"activity": activity, "pitch": pitch})


def verdict(agreed, concern=""):
    return json_body({"agreed": agreed, "concern": concern})


GROUP = ["u01", "u04", "u10"]


def test_one_round_agreement():
    fake = FakeClient(interview_text="sounds great, I'm in",
                      propose_queue=[proposal("chess night")],
                      assess_queue=[verdict(True)])
    out = run(negotiate(claws_for(GROUP, fake), interviews_for(GROUP), client=fake))
    assert out["agreed"] is True
    assert out["activity"] == "chess night"
    assert out["rounds"] == 1
    kinds = [e["type"] for e in out["transcript"]]
    assert kinds.count("propose") == 1
    assert kinds.count("reaction") == 3      # one per real Claw
    assert kinds.count("assess") == 1


def test_each_claw_actually_reacts():
    fake = FakeClient(propose_queue=[proposal("a")], assess_queue=[verdict(True)])
    run(negotiate(claws_for(GROUP, fake), interviews_for(GROUP), client=fake))
    react_calls = [k for k, _ in fake.calls if k == "interview"]
    assert len(react_calls) == 3             # 3 Claws each made one real reaction call


def test_revises_until_agreed():
    fake = FakeClient(interview_text="hmm not sure",
                      propose_queue=[proposal("loud bar"), proposal("quiet cafe")],
                      assess_queue=[verdict(False, "too loud for this group"), verdict(True)])
    out = run(negotiate(claws_for(GROUP, fake), interviews_for(GROUP), client=fake))
    assert out["rounds"] == 2
    assert out["agreed"] is True
    assert out["activity"] == "quiet cafe"           # the revised plan won
    propose_calls = [k for k, _ in fake.calls if k == "propose"]
    assert len(propose_calls) == 2                   # it really re-proposed


def test_caps_at_max_rounds_without_agreement():
    p = proposal("x")
    no = verdict(False, "nope")
    fake = FakeClient(propose_queue=[p, p, p], assess_queue=[no, no, no])
    out = run(negotiate(claws_for(["u01", "u04"], fake), interviews_for(["u01", "u04"]),
                        client=fake, max_rounds=3))
    assert out["agreed"] is False
    assert out["rounds"] == 3                         # stopped at the cap, didn't loop forever


def test_propose_falls_back_on_bad_json():
    fake = FakeClient(propose_queue=["not valid json"], assess_queue=[verdict(True)])
    out = run(negotiate(claws_for(["u01", "u04"], fake), interviews_for(["u01", "u04"]), client=fake))
    assert out["activity"] == "a casual hangout"      # the safe fallback
