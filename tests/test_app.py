"""Tests for the web backend. Demo mode runs fully offline (no API calls)."""

import copy
import json

from fastapi.testclient import TestClient

import app as webapp
from users import USERS

client = TestClient(webapp.app)


def reset_state():
    # the backend holds module-global state; reset it for a clean test.
    import os
    webapp.STATE["users"] = copy.deepcopy(USERS)
    webapp.STATE["last_run"] = None
    webapp.STATE["interview_cache"] = None
    webapp.STATE["feedback"] = []
    for path in (webapp._CAST_PATH, webapp._FEEDBACK_PATH):
        if os.path.exists(path):
            os.remove(path)
    webapp.STATE["interview_cache"] = None


def test_interviews_cached_across_runs_until_edited():
    reset_state()
    first = client.post("/api/run?mode=demo").json()
    assert first["interviews_reused"] is False      # first run interviews fresh
    second = client.post("/api/run?mode=demo").json()
    assert second["interviews_reused"] is True       # same cast -> reused (fast)
    client.post("/api/users/u01", json={"personality": "extroverted"})
    third = client.post("/api/run?mode=demo").json()
    assert third["interviews_reused"] is False        # an edit invalidates the cache


def test_index_serves_the_page():
    r = client.get("/")
    assert r.status_code == 200
    assert "Clawnly" in r.text
    assert "Run the matchmaker" in r.text


def test_api_users_returns_twelve():
    r = client.get("/api/users")
    assert r.status_code == 200
    assert len(r.json()["users"]) == 12


def test_api_run_demo_returns_groups():
    reset_state()
    r = client.post("/api/run?mode=demo")
    assert r.status_code == 200
    data = r.json()
    assert len(data["interviews"]) == 12
    # the demo partitions into 2 groups, each with a match + negotiation + popup.
    assert len(data["groups"]) == 2
    g0 = data["groups"][0]
    assert g0["match"]["group"] == ["u01", "u04", "u10"]
    assert g0["negotiation"]["agreed"] is True
    assert g0["popup"]["event_name"]
    kinds = [e["type"] for e in g0["negotiation"]["transcript"]]
    assert "propose" in kinds and "reaction" in kinds and "assess" in kinds


def test_api_run_demo_makes_no_real_calls():
    # demo mode must work with no ANTHROPIC_API_KEY set (offline / free).
    import os
    reset_state()
    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        r = client.post("/api/run?mode=demo")
        assert r.status_code == 200
        assert r.json()["groups"][0]["match"]["group"] == ["u01", "u04", "u10"]
    finally:
        if saved is not None:
            os.environ["ANTHROPIC_API_KEY"] = saved


def test_run_stream_emits_live_sse_events():
    reset_state()
    stages = []
    with client.stream("GET", "/api/run-stream?mode=demo") as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                stages.append(json.loads(line[6:])["stage"])
    assert "interviews" in stages
    assert "group" in stages
    assert "negotiation" in stages          # reactions streamed one by one
    assert "popup" in stages
    assert stages[-1] == "done"


def test_run_reports_api_usage():
    reset_state()
    data = client.post("/api/run?mode=demo").json()
    assert data["usage"]["total"] > 0           # counted the calls
    assert isinstance(data["usage"]["by_model"], dict)


def test_edit_user_updates_trait():
    reset_state()
    r = client.post("/api/users/u01", json={"personality": "extroverted"})
    assert r.status_code == 200
    assert r.json()["personality"] == "extroverted"
    # the change persists in the cast
    users = client.get("/api/users").json()["users"]
    maya = next(u for u in users if u["id"] == "u01")
    assert maya["personality"] == "extroverted"


def test_edit_unknown_user_404():
    assert client.post("/api/users/nope", json={"bio": "x"}).status_code == 404


def test_edit_persists_to_disk():
    import json
    import os
    reset_state()
    client.post("/api/users/u01", json={"personality": "extroverted"})
    assert os.path.exists(webapp._CAST_PATH)
    with open(webapp._CAST_PATH) as handle:
        saved = json.load(handle)
    maya = next(u for u in saved if u["id"] == "u01")
    assert maya["personality"] == "extroverted"
    reset_state()


def test_reset_restores_defaults():
    import os
    reset_state()
    client.post("/api/users/u01", json={"personality": "extroverted"})
    client.post("/api/reset")
    users = client.get("/api/users").json()["users"]
    maya = next(u for u in users if u["id"] == "u01")
    assert maya["personality"] == "introverted"      # back to the default
    assert not os.path.exists(webapp._CAST_PATH)


def test_generate_cast_demo_is_rejected():
    reset_state()
    r = client.post("/api/generate-cast", json={"mode": "demo"})
    assert r.status_code == 400
    assert "Live" in r.json()["error"]


def test_generate_cast_live_replaces_the_cast(monkeypatch):
    reset_state()
    from conftest import FakeClient, json_body
    cast = {"users": [
        {"name": "A", "age": 27, "gender": "female", "hobbies": ["reading", "yoga"],
         "personality": "introverted", "occupation": "student", "availability": ["weekday_evening"],
         "location": "Shaw", "bio": "I like quiet book nights.", "preferred_group_size": [2, 3]},
        {"name": "B", "age": 31, "gender": "male", "hobbies": ["cycling", "trivia nights"],
         "personality": "extroverted", "occupation": "freelancer", "availability": ["weekend_evening"],
         "location": "Shaw", "bio": "Rides and pub quizzes.", "preferred_group_size": [5, 8]},
    ]}
    fake = FakeClient(generation_queue=[json_body(cast)])
    monkeypatch.setattr(webapp, "_client_for", lambda mode: fake)
    r = client.post("/api/generate-cast", json={"mode": "live", "theme": "anything"})
    assert r.status_code == 200
    users = client.get("/api/users").json()["users"]
    assert len(users) == 2 and users[0]["id"] == "u01"      # cast replaced + re-id'd


def test_edit_rejects_invalid_personality():
    reset_state()
    r = client.post("/api/users/u01", json={"personality": "grumpy"})
    assert r.status_code == 400
    assert "personality" in r.json()["error"]


def test_edit_rejects_impossible_group_size():
    reset_state()
    r = client.post("/api/users/u01", json={"preferred_group_size": [9, 10]})
    assert r.status_code == 400


def test_edit_rejects_unknown_availability():
    reset_state()
    r = client.post("/api/users/u01", json={"availability": ["whenever"]})
    assert r.status_code == 400


def test_nudge_demo_is_rejected():
    reset_state()
    r = client.post("/api/users/u01/nudge", json={"instruction": "make her bold", "mode": "demo"})
    assert r.status_code == 400
    assert "Live" in r.json()["error"]


def test_nudge_live_applies_ai_changes(monkeypatch):
    reset_state()
    from conftest import FakeClient, json_body
    fake = FakeClient(nudge_queue=[json_body({"personality": "extroverted", "bio": "I love a crowd now."})])
    monkeypatch.setattr(webapp, "_client_for", lambda mode: fake)
    r = client.post("/api/users/u01/nudge", json={"instruction": "make her outgoing", "mode": "live"})
    assert r.status_code == 200
    assert r.json()["personality"] == "extroverted"      # Maya was introverted
    users = client.get("/api/users").json()["users"]
    assert next(u for u in users if u["id"] == "u01")["personality"] == "extroverted"


def test_chat_demo_returns_a_reply():
    reset_state()
    r = client.post("/api/chat", json={"user_id": "u01", "message": "what's up?", "history": [], "mode": "demo"})
    assert r.status_code == 200
    assert len(r.json()["reply"]) > 0


def test_demo_chat_reflects_edits_and_message():
    reset_state()
    client.post("/api/users/u01", json={"personality": "extroverted"})   # Maya was introverted
    r = client.post("/api/chat", json={"user_id": "u01", "message": "weekend plans?", "history": [], "mode": "demo"})
    reply = r.json()["reply"]
    assert "extroverted" in reply        # reflects the edit, not the original trait
    assert "weekend plans?" in reply     # varies with the actual message


def test_feedback_add_get_and_clear():
    reset_state()
    r = client.post("/api/feedback", json={"members": ["Maya", "Marcus"], "rating": "up", "note": "great"})
    assert r.status_code == 200
    assert len(r.json()["feedback"]) == 1
    got = client.get("/api/feedback").json()["feedback"]
    assert got[0]["rating"] == "up" and got[0]["note"] == "great"
    client.post("/api/feedback/clear")
    assert client.get("/api/feedback").json()["feedback"] == []


def test_feedback_rejects_bad_rating():
    reset_state()
    assert client.post("/api/feedback", json={"members": [], "rating": "meh"}).status_code == 400


def test_run_works_with_feedback_present():
    reset_state()
    client.post("/api/feedback", json={"members": ["Ethan"], "rating": "down", "note": "too loud"})
    r = client.post("/api/run?mode=demo")
    assert r.status_code == 200
    assert len(r.json()["groups"]) >= 1


def test_master_chat_requires_a_run_first():
    reset_state()
    r = client.post("/api/master-chat", json={"message": "why?", "history": [], "mode": "demo"})
    assert r.status_code == 200
    assert "Run the matchmaker first" in r.json()["reply"]


def test_master_chat_after_run_demo_explains_grounded():
    reset_state()
    client.post("/api/run?mode=demo")             # sets last_run
    r = client.post("/api/master-chat", json={"message": "why these three?", "history": [], "mode": "demo"})
    assert r.status_code == 200
    reply = r.json()["reply"]
    assert "Maya" in reply and "Ethan" in reply    # grounded in the actual run record


def test_set_key_configures_live():
    # paste a key in the app -> Live becomes possible. Backs up/restores any .env.
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(webapp.__file__)))
    env_path = os.path.join(root, ".env")
    backup = None
    if os.path.exists(env_path):
        with open(env_path) as f:
            backup = f.read()
    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        r = client.post("/api/key", json={"key": "sk-ant-test-abcdefg"})
        assert r.status_code == 200 and r.json()["configured"] is True
        assert client.get("/api/key-status").json()["configured"] is True
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)
        if saved is not None:
            os.environ["ANTHROPIC_API_KEY"] = saved
        if backup is not None:
            with open(env_path, "w") as f:
                f.write(backup)
        elif os.path.exists(env_path):
            os.remove(env_path)


def test_set_key_rejects_garbage():
    r = client.post("/api/key", json={"key": "x"})
    assert r.status_code == 400
