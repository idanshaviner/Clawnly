"""Tests for the web backend. Demo mode runs fully offline (no API calls)."""

import json

from fastapi.testclient import TestClient

import app as webapp
import db
from users import USERS

client = TestClient(webapp.app)


def reset_state():
    # the backend's state now lives in SQLite (db.py, Milestone 1); wipe every
    # table and restore the default 12 people for a clean test.
    db.reset_all(USERS)


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
    assert "Black Diamond" in r.text
    assert "/join" in r.text


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


def test_edit_persists_across_a_restart():
    # simulate a server restart: open a totally fresh sqlite3 connection to the
    # same db file (not the app's cached one) and confirm the edit is really there.
    import sqlite3
    reset_state()
    client.post("/api/users/u01", json={"personality": "extroverted"})
    fresh = sqlite3.connect(db.DB_PATH)
    row = fresh.execute("SELECT personality FROM users WHERE id = ?", ("u01",)).fetchone()
    fresh.close()
    assert row[0] == "extroverted"
    reset_state()


def test_reset_restores_defaults():
    reset_state()
    client.post("/api/users/u01", json={"personality": "extroverted"})
    client.post("/api/reset")
    users = client.get("/api/users").json()["users"]
    maya = next(u for u in users if u["id"] == "u01")
    assert maya["personality"] == "introverted"      # back to the default


def test_generate_cast_demo_builds_a_synthetic_cast():
    # Demo generate is offline (no Anthropic) so the 100-person sim is playable.
    reset_state()
    r = client.post("/api/generate-cast", json={
        "mode": "demo", "count": 20,
        "theme": "neighbors in Black Diamond, Washington (platonic)",
    })
    assert r.status_code == 200
    data = r.json()
    assert len(data["users"]) == 20
    assert data["users"][0]["id"] == "u01"
    assert data["warning"] is None
    assert "Black Diamond" in data["theme"]


def test_generate_cast_live_replaces_the_cast(monkeypatch):
    reset_state()
    from conftest import FakeClient, json_body
    # the app invents 12 people, one concurrent call each -> queue 12 person objects.
    def person(name):
        return {"name": name, "age": 27, "gender": "female", "hobbies": ["reading", "yoga"],
                "personality": "introverted", "occupation": "student", "availability": ["weekday_evening"],
                "location": "Shaw", "bio": "I like quiet book nights.", "preferred_group_size": [2, 3]}
    queue = [json_body(person("P" + str(i))) for i in range(12)]
    fake = FakeClient(generation_queue=queue)
    monkeypatch.setattr(webapp, "_client_for", lambda mode, key=None: fake)
    r = client.post("/api/generate-cast", json={"mode": "live", "theme": "anything"})
    assert r.status_code == 200
    users = client.get("/api/users").json()["users"]
    assert len(users) == 12 and users[0]["id"] == "u01"     # fresh cast, re-id'd
    assert len([k for k in fake.kinds() if k == "generation"]) == 12   # one call per person


def test_generate_cast_live_honors_count_and_theme(monkeypatch):
    reset_state()
    from conftest import FakeClient, json_body
    def person(name):
        return {"name": name, "age": 27, "gender": "female", "hobbies": ["reading", "yoga"],
                "personality": "introverted", "occupation": "student", "availability": ["weekday_evening"],
                "location": "Ten Trails", "bio": "I like quiet book nights.", "preferred_group_size": [2, 3]}
    queue = [json_body(person("P" + str(i))) for i in range(4)]
    fake = FakeClient(generation_queue=queue)
    monkeypatch.setattr(webapp, "_client_for", lambda mode, key=None: fake)
    r = client.post("/api/generate-cast", json={
        "mode": "live", "count": 4, "theme": "Black Diamond, Washington neighbors",
    })
    assert r.status_code == 200
    users = r.json()["users"]
    assert len(users) == 4
    gen = [kw for k, kw in fake.calls if k == "generation"]
    assert len(gen) == 4
    assert "Black Diamond, Washington neighbors" in gen[0]["system"]


def test_generate_cast_clamps_count_and_does_not_wipe_on_too_few(monkeypatch):
    reset_state()
    before = client.get("/api/users").json()["users"]
    assert len(before) == 12

    async def fake_gen(count=12, theme=None, client=None, attempts=3):
        assert count == 100   # 500 clamped
        return []             # too few to accept

    monkeypatch.setattr(webapp, "generate_users", fake_gen)
    r = client.post("/api/generate-cast", json={"mode": "live", "count": 500, "theme": "x"})
    assert r.status_code == 502
    after = client.get("/api/users").json()["users"]
    assert len(after) == 12
    assert after[0]["id"] == before[0]["id"]


def test_generate_cast_partial_cast_warns_without_failing(monkeypatch):
    reset_state()
    from conftest import FakeClient, json_body
    def person(name):
        return {"name": name, "age": 27, "gender": "female", "hobbies": ["reading", "yoga"],
                "personality": "introverted", "occupation": "student", "availability": ["weekday_evening"],
                "location": "Ten Trails", "bio": "I like quiet book nights.", "preferred_group_size": [2, 3]}
    # 5 requested, only 3 valid replies then empty/invalid leftovers would fail slots
    queue = [json_body(person("A")), json_body(person("B")), json_body(person("C")),
             json_body({"nope": True}), json_body({"nope": True}),
             json_body({"nope": True}), json_body({"nope": True}), json_body({"nope": True}),
             json_body({"nope": True})]
    fake = FakeClient(generation_queue=queue)
    monkeypatch.setattr(webapp, "_client_for", lambda mode, key=None: fake)
    r = client.post("/api/generate-cast", json={"mode": "live", "count": 5, "theme": "Black Diamond"})
    assert r.status_code == 200
    data = r.json()
    assert len(data["users"]) == 3
    assert data["warning"] is not None
    assert "3 of 5" in data["warning"]


def test_api_run_demo_is_not_hardcoded_to_twelve():
    reset_state()
    import persona_gen
    import db
    people = persona_gen.build_demo_cast(count=24, theme="Black Diamond neighbors")
    db.replace_users(people)
    r = client.post("/api/run?mode=demo")
    assert r.status_code == 200
    data = r.json()
    assert len(data["interviews"]) == 24
    assert len(data["groups"]) >= 2
    assert "unmatched" in data
    # groups actually came from the 24-person pool, not the seed 12
    g0 = data["groups"][0]["match"]["group"]
    assert len(g0) >= 3


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
    monkeypatch.setattr(webapp, "_client_for", lambda mode, key=None: fake)
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


def test_api_run_demo_completes_for_one_hundred():
    reset_state()
    r = client.post("/api/generate-cast", json={
        "mode": "demo", "count": 100,
        "theme": "neighbors in Black Diamond, Washington (platonic)",
    })
    assert r.status_code == 200
    assert len(r.json()["users"]) == 100
    r2 = client.post("/api/run?mode=demo")
    assert r2.status_code == 200
    data = r2.json()
    assert len(data["interviews"]) == 100
    assert len(data["groups"]) >= 2
    assert "unmatched" in data
    g0 = data["groups"][0]["match"]
    assert g0["reason"]
    assert g0["scores"]
    assert "why_not" in g0
