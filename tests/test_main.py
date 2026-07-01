"""End-to-end pipeline tests with a fully mocked client.

The pipeline always partitions everyone into groups; each group negotiates a
plan and gets a meetup. Result shape: {interviews, groups:[{match, negotiation,
popup}], unmatched}.
"""

from conftest import FakeClient, json_body, run
from main import run_pipeline
from users import USERS


def match_obj(group=None):
    if group is None:
        group = ["u01", "u04", "u10"]
    return {
        "group": group,
        "reason": "All free weekday evenings with a shared calm, intellectual streak.",
        "scores": {"personality": 3, "availability": 4, "interests": 4, "size_fit": 5},
        "why_not": [{"id": "u08", "reason": "wants 6-8 people"}],
    }


def popup_obj():
    return {"options": [
        {"event_name": "Weekday Wind-Down", "activity": "chess and coffee",
         "location": "Compass Coffee, Navy Yard", "time": "Wednesday evening",
         "reason": "A quiet weekday evening over chess suits all three of you perfectly."},
    ]}


def one_group_fake():
    # forms a single group, then "no more" -> 1 group + leftovers.
    g1 = json_body(match_obj(["u01", "u04", "u10"]))
    refuse = json_body({"group": [], "reason": "no more viable groups", "scores": {}, "why_not": []})
    return FakeClient(
        match_queue=[g1, refuse],
        propose_queue=[json_body({"activity": "a low-key chess night over coffee", "pitch": "Chess night?"})],
        assess_queue=[json_body({"agreed": True, "concern": ""})],
        popup_queue=[json_body(popup_obj())],
    )


def no_agreement_fake():
    # forms one group, but the group NEVER agrees on a plan (assess always false).
    g1 = json_body(match_obj(["u01", "u04", "u10"]))
    refuse = json_body({"group": [], "reason": "no more", "scores": {}, "why_not": []})
    p = json_body({"activity": "something", "pitch": "pitch"})
    no = json_body({"agreed": False, "concern": "Omar isn't on board"})
    return FakeClient(
        match_queue=[g1, refuse],
        propose_queue=[p, p, p],          # 3 rounds of proposals
        assess_queue=[no, no, no],        # all rejected
        popup_queue=[json_body(popup_obj())],   # must stay UNUSED
    )


def test_no_meetup_when_group_never_agrees():
    fake = no_agreement_fake()
    result = run(run_pipeline(USERS, client=fake, verbose=False))
    g = result["groups"][0]
    assert g["negotiation"]["agreed"] is False
    assert g["popup"] is None                       # no meetup shipped without agreement
    kinds = [k for k, _ in fake.calls]
    assert "popup" not in kinds                     # the popup call was never made


def test_no_plan_stage_emitted_instead_of_popup():
    fake = no_agreement_fake()
    stages = []
    run(run_pipeline(USERS, client=fake, verbose=False, on_stage=lambda s, d: stages.append(s)))
    assert "no_plan" in stages
    assert "popup" not in stages


def test_full_pipeline_runs_end_to_end(capsys):
    fake = one_group_fake()
    result = run(run_pipeline(USERS, client=fake))

    assert len(result["groups"]) == 1
    g = result["groups"][0]
    assert g["match"]["group"] == ["u01", "u04", "u10"]
    assert g["negotiation"]["activity"] == "a low-key chess night over coffee"
    assert g["negotiation"]["agreed"] is True
    assert g["popup"]["matched_users"] == ["Maya", "Marcus", "Omar"]

    out = capsys.readouterr().out
    assert "INTERVIEWS" in out
    assert "GROUP 1" in out
    assert "NEGOTIATION" in out
    assert "MEETUP" in out
    assert "a low-key chess night over coffee" in out
    assert "Weekday Wind-Down" in out


def test_negotiated_activity_flows_into_popup():
    fake = one_group_fake()
    run(run_pipeline(USERS, client=fake))
    popup_kwargs = [kw for kind, kw in fake.calls if kind == "popup"][0]
    payload = popup_kwargs["messages"][0]["content"]
    assert "a low-key chess night over coffee" in payload    # popup built around it


def test_no_groups_when_nobody_matches():
    empty = json_body({"group": [], "reason": "no shared time across viable sets", "scores": {}, "why_not": []})
    fake = FakeClient(match_queue=[empty])
    result = run(run_pipeline(USERS, client=fake, verbose=False))
    assert result["groups"] == []
    assert len(result["unmatched"]) == 12
    kinds = [k for k, _ in fake.calls]
    assert "propose" not in kinds and "popup" not in kinds   # no group -> no negotiation/popup


def test_partitions_into_multiple_groups():
    a = json_body(match_obj(["u01", "u04", "u10"]))
    b = json_body(match_obj(["u03", "u09", "u11"]))
    refuse = json_body({"group": [], "reason": "none", "scores": {}, "why_not": []})
    p = json_body({"activity": "x", "pitch": "p"})
    v = json_body({"agreed": True, "concern": ""})
    pop = json_body(popup_obj())
    fake = FakeClient(match_queue=[a, b, refuse], propose_queue=[p, p], assess_queue=[v, v], popup_queue=[pop, pop])
    result = run(run_pipeline(USERS, client=fake, verbose=False))
    assert len(result["groups"]) == 2
    assert len(result["unmatched"]) == 6
    assert result["groups"][0]["match"]["group"] == ["u01", "u04", "u10"]
    assert result["groups"][1]["match"]["group"] == ["u03", "u09", "u11"]
    # each group negotiated + got its own meetup
    assert len([k for k, _ in fake.calls if k == "popup"]) == 2


def test_pipeline_uses_single_injected_client():
    fake = one_group_fake()
    run(run_pipeline(USERS, client=fake))
    kinds = [k for k, _ in fake.calls]
    assert "interview" in kinds and "match" in kinds
    assert "propose" in kinds and "assess" in kinds and "popup" in kinds


def test_run_pipeline_emits_per_group_stages():
    fake = one_group_fake()
    stages = []
    run(run_pipeline(USERS, client=fake, verbose=False, on_stage=lambda s, d: stages.append(s)))
    assert stages[0] == "interviews"
    assert "group" in stages
    assert "negotiation" in stages
    assert "negotiation_done" in stages
    assert "popup" in stages
    assert stages[-1] == "done"
