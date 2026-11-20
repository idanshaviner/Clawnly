"""The judge (judge.py): a second model scores each group of a finished Run Clawnly
day. Offline, via FakeClient -- the judge's reply is canned."""

import datetime
import json

from fastapi.testclient import TestClient

import app as webapp
import auth
import catalog
import config
import db
import demand
import judge
import matchmaker
import run_clawnly
from conftest import FakeClient, reset_db, run

START = "2026-09-27"
DAY = datetime.date(2026, 9, 28)
INSIDE = {"morning": "10am-12pm", "afternoon": "1-3pm", "evening": "6-8pm"}

client = TestClient(webapp.app)


def good_verdict(overall=7):
    out = {}
    for key, _ in judge.CRITERIA:
        out[key] = {"score": 8, "reason": "quotes [2]: 'loves kayaking'"}
    out["overall"] = {"score": overall, "reason": "solid group"}
    out["flags"] = ["side-thing match"]
    return out


def two_group_plan(people):
    rooms = demand.break_room(people, catalog.ACTIVITIES, DAY)
    groups = []
    used = set()
    for room in rooms:
        ids = [c["id"] for c in room["candidates"] if c["id"] not in used
               and matchmaker.keenness(next(p for p in people if p["id"] == c["id"]),
                                       catalog.get(room["activity"])) >= matchmaker.STRONG]
        if len(ids) < 4:
            continue
        used.update(ids[:4])
        groups.append({"activity": room["activity"], "part": room["part"], "time": INSIDE[room["part"]],
                       "members": ids[:3], "alternates": [ids[3]], "why": "they all love it",
                       "proposals": {pid: "Hi, " + room["activity"] + " tomorrow?" for pid in ids[:3]}})
        if len(groups) == 2:
            break
    return {"thoughts": "Two strong rooms today.", "groups": groups}


def saved_run():
    # a real (faked) matchmaker day, saved the way run_clawnly saves one
    people = run_clawnly.town(START)
    plan = two_group_plan(people)
    fake = FakeClient(matchmaker={
        "mm_plan": lambda s, c: json.dumps(plan),
        "mm_agent": lambda s, c: json.dumps({"answer": "yes", "reason": "loves it", "counter": "", "say": "count me in"}),
        "mm_resolve": lambda s, c: json.dumps({"thoughts": "all good", "groups": []}),
        "mm_message": lambda s, c: json.dumps({"headline": "See you there", "messages": {}}),
    })
    data = run(matchmaker.run_day(DAY, 5, people, fake))
    data["townStart"] = START
    run_id = db.claim_matchmaker_run(DAY.isoformat(), "admin@example.com", 900)
    db.save_matchmaker_run(run_id, data)
    return run_id, data


def judge_fake(reply):
    return FakeClient(matchmaker={"judge_group": reply})


def test_the_record_has_the_event_profiles_every_message_and_the_outcome():
    reset_db()
    run_id, data = saved_run()
    stored = db.get_matchmaker_run(run_id)
    people = judge.people_for(stored)
    group = data["groups"][0]
    text = judge.group_record(stored, group, people)
    activity = catalog.get(group["activity"])
    assert activity["name"] in text and activity["where"] in text
    assert "cost: " + activity["cost"] in text
    assert "they all love it" in text
    assert "Two strong rooms today." in text
    for member in group["members"]:
        assert people[member["id"]]["name"] in text
    # the full profile each agent had, and the alternate's too
    assert matchmaker.agent_profile(people[group["members"][0]["id"]]).split("\n")[0] in text
    assert people[group["alternates"][0]]["name"] in text
    # every message numbered, so the judge can quote it
    assert "[1] matchmaker -> " in text
    assert "YES | reason: loves it | says: count me in" in text
    assert "locked: " in text
    assert "headline sent: See you there" in text


def test_judge_scores_every_group_and_saves_it():
    reset_db()
    run_id, data = saved_run()
    fake = judge_fake(lambda s, c: json.dumps(good_verdict()))
    outcome = run(judge.judge_run("latest", fake))
    assert outcome["run_id"] == run_id
    assert len(outcome["results"]) == len(data["groups"]) == 2
    assert outcome["results"][0]["overall"] == 7
    assert outcome["results"][0]["verdict"]["flags"] == ["side-thing match"]
    saved = db.list_judge_scores(run_id)
    assert [s["group_id"] for s in saved] == ["g1", "g2"]
    assert saved[0]["verdict"]["main_thing"]["score"] == 8
    # one call per group, with the skill file in the prompt and the record as the message
    assert fake.kinds() == ["judge_group", "judge_group"]
    kwargs = fake.calls[0][1]
    assert matchmaker.skill()[:80] in kwargs["system"]
    assert "THE NEGOTIATION, IN ORDER" in kwargs["messages"][0]["content"]
    assert "temperature" not in kwargs
    # logged like every other call, and the run gets one line in the log
    purposes = [r["purpose"] for r in db._get_conn().execute("SELECT purpose FROM ai_calls").fetchall()]
    assert purposes.count("judge_group") == 2
    texts = [r["text"] for r in db._get_conn().execute("SELECT text FROM events").fetchall()]
    assert any(t.startswith("Judged Run Clawnly #" + str(run_id)) and "average overall 7" in t for t in texts)


def test_the_judge_is_a_cheaper_model_than_the_matchmaker_and_can_be_changed(monkeypatch):
    reset_db()
    saved_run()
    assert config.MODEL_JUDGE != config.MODEL_PREMIUM
    monkeypatch.setattr(config, "resolve_env", lambda name: None)
    fake = judge_fake(lambda s, c: json.dumps(good_verdict()))
    run(judge.judge_run("latest", fake))
    assert fake.calls[0][1]["model"] == config.MODEL_JUDGE
    monkeypatch.setattr(config, "resolve_env", lambda name: "claude-other" if name == "CLAWNLY_JUDGE_MODEL" else None)
    fake = judge_fake(lambda s, c: json.dumps(good_verdict()))
    outcome = run(judge.judge_run("latest", fake))
    assert fake.calls[0][1]["model"] == "claude-other"
    assert outcome["model"] == "claude-other"
    fake = judge_fake(lambda s, c: json.dumps(good_verdict()))
    run(judge.judge_run("latest", fake, model="claude-third"))
    assert fake.calls[0][1]["model"] == "claude-third"


def test_judging_again_shows_the_latest_score_per_group():
    reset_db()
    run_id, _ = saved_run()
    run(judge.judge_run(run_id, judge_fake(lambda s, c: json.dumps(good_verdict(4)))))
    run(judge.judge_run(run_id, judge_fake(lambda s, c: json.dumps(good_verdict(9)))))
    saved = db.list_judge_scores(run_id)
    assert [s["overall"] for s in saved] == [9, 9]
    total = db._get_conn().execute("SELECT COUNT(*) FROM judge_scores").fetchone()[0]
    assert total == 4


def test_a_bad_reply_or_a_failed_call_is_saved_as_not_scored():
    reset_db()
    run_id, _ = saved_run()

    def flaky(system, content):
        if "group g1" in content:
            return "sorry, I can't"
        raise RuntimeError("overloaded")

    outcome = run(judge.judge_run(run_id, judge_fake(flaky)))
    assert [r["overall"] for r in outcome["results"]] == [None, None]
    assert "not a JSON object" in outcome["results"][0]["error"]
    assert "overloaded" in outcome["results"][1]["error"]
    assert db.list_judge_scores(run_id)[1]["error"].startswith("the judge call failed")


def test_parse_verdict_keeps_scores_in_range_and_fills_a_missing_overall():
    raw = good_verdict()
    raw["main_thing"]["score"] = 14
    raw["event_fit"]["score"] = "0"
    del raw["overall"]
    raw["flags"] = ["", "over budget"]
    verdict, error = judge.parse_verdict(raw)
    assert error is None
    assert verdict["main_thing"]["score"] == 10
    assert verdict["event_fit"]["score"] == 1
    assert verdict["overall"]["score"] == round((10 + 8 + 1 + 8 + 8) / 5)
    assert "average" in verdict["overall"]["reason"]
    assert verdict["flags"] == ["over budget"]
    bad = good_verdict()
    del bad["negotiation"]
    assert judge.parse_verdict(bad) == (None, "no negotiation in the judge's reply")
    assert judge.parse_verdict(None)[0] is None


def test_a_running_or_missing_run_is_not_judged():
    reset_db()
    try:
        run(judge.judge_run("latest", judge_fake(lambda s, c: "{}")))
        assert False
    except ValueError as error:
        assert "No Run Clawnly run" in str(error)
    db.claim_matchmaker_run(DAY.isoformat(), "admin@example.com", 900)
    try:
        run(judge.judge_run("latest", judge_fake(lambda s, c: "{}")))
        assert False
    except ValueError as error:
        assert "still going" in str(error)


def test_an_older_run_finds_its_town_from_when_it_started():
    stored = {"data": {}, "created_at": "2026-09-27T01:30:00+00:00"}
    # 1:30 UTC on the 27th is still the 26th in Los Angeles; the town starts the next day
    assert judge.town_start(stored) == "2026-09-27"
    assert judge.town_start({"data": {"townStart": "2026-10-01"}, "created_at": "x"}) == "2026-10-01"


def test_a_new_run_saves_its_town_start(monkeypatch):
    reset_db()
    fake = FakeClient(matchmaker={"mm_plan": lambda s, c: json.dumps({"thoughts": "quiet", "groups": []})})
    monkeypatch.setattr(config, "get_client", lambda: fake)
    first = run_clawnly.days()[0]
    run_id = db.claim_matchmaker_run(first, "admin@example.com", 900)
    run(run_clawnly._run(run_id, first, 6, first))
    assert db.get_matchmaker_run(run_id)["data"]["townStart"] == first


def test_the_command_line_prints_scores_and_reasons(monkeypatch, capsys):
    reset_db()
    run_id, _ = saved_run()
    monkeypatch.setattr(config, "get_client", lambda: judge_fake(lambda s, c: json.dumps(good_verdict())))
    assert judge.main(["--run", str(run_id)]) == 0
    out = capsys.readouterr().out
    assert "Run #" + str(run_id) in out
    assert "overall 7/10: solid group" in out
    assert "Main-thing fit: 8 -- quotes [2]" in out
    assert "flags: side-thing match" in out
    assert judge.main(["--list"]) == 0
    assert "#" + str(run_id) in capsys.readouterr().out
    assert judge.main(["--bogus"]) == 2


def sign_in(role):
    token = auth.start_session(role + "@example.com", role, None, None)
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)


def test_admin_sees_scores_per_run_and_only_admins_can(monkeypatch):
    reset_db()
    run_id, _ = saved_run()
    client.cookies.clear()
    assert client.get("/api/admin/judge").status_code in (401, 403)
    assert client.post("/api/admin/judge", json={"run_id": run_id}).status_code in (401, 403)
    sign_in("admin")
    body = client.get("/api/admin/judge").json()
    assert body["runs"][0]["id"] == run_id
    assert body["view"]["run"]["id"] == run_id
    assert [g["score"] for g in body["view"]["groups"]] == [None, None]
    run(judge.judge_run(run_id, judge_fake(lambda s, c: json.dumps(good_verdict()))))
    body = client.get("/api/admin/judge?run_id=" + str(run_id)).json()
    assert body["view"]["groups"][0]["score"]["overall"] == 7
    assert body["view"]["groups"][0]["status"] == "locked"
    assert client.get("/api/admin/judge?run_id=999").status_code == 404
    assert client.post("/api/admin/judge", json={"run_id": "x"}).status_code == 400
    assert client.post("/api/admin/judge", json={"run_id": 999}).status_code == 400
    client.cookies.clear()


def test_the_admin_button_judges_in_the_background(monkeypatch):
    reset_db()
    run_id, _ = saved_run()
    monkeypatch.setattr(config, "get_client", lambda: judge_fake(lambda s, c: json.dumps(good_verdict())))

    async def go():
        started, error = judge.start(run_id, "admin@example.com")
        assert started and error is None
        again, error = judge.start(run_id, "admin@example.com")
        assert not again and "being judged" in error
        while len(judge._TASKS) > 0:
            await __import__("asyncio").sleep(0.01)

    run(go())
    assert [s["overall"] for s in db.list_judge_scores(run_id)] == [7, 7]
    assert run_id not in judge._JUDGING
