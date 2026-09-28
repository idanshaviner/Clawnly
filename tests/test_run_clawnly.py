"""Run Clawnly at a real URL (run_clawnly.py + the /run routes): anyone can watch,
only an admin can start a run, and a run is saved as it goes."""

import asyncio
import json

from fastapi.testclient import TestClient

import app as webapp
import auth
import config
import db
import run_clawnly
from conftest import FakeClient, reset_db, run

client = TestClient(webapp.app)


def sign_in(role):
    token = auth.start_session(role + "@example.com", role, None, None)
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)


def sign_out():
    client.cookies.clear()


def page_data(html):
    start = html.index('id="mm-data">') + len('id="mm-data">')
    return json.loads(html[start:html.index("</script>", start)])


def test_the_page_is_public_in_server_mode_with_the_next_seven_days():
    reset_db()
    sign_out()
    res = client.get("/run")
    assert res.status_code == 200
    assert res.headers["x-frame-options"] == "DENY"
    assert '<script type="application/json" id="mm-mode">"server"</script>' in res.text
    data = page_data(res.text)
    assert data["days"] == run_clawnly.days()
    assert len(data["days"]) == 7
    assert len(data["people"]) == 200
    assert data["people"][0]["emulated"] is True
    # the page and a run see the same town
    assert data["people"] == json.loads(json.dumps(run_clawnly.town(data["days"][0])))


def test_json_in_the_page_cannot_close_its_script_tag():
    assert run_clawnly._script_json({"x": "</script><script>alert(1)</script>"}) == '{"x": "\\u003c/script>\\u003cscript>alert(1)\\u003c/script>"}'


def test_starting_a_run_needs_an_admin(monkeypatch):
    reset_db()
    monkeypatch.setattr(run_clawnly, "start", lambda day, max_groups, by: (_ for _ in ()).throw(AssertionError("must not start")))
    sign_out()
    assert client.post("/api/run", json={"day": run_clawnly.days()[0], "max_groups": "6"}).status_code == 401
    sign_in("resident")
    assert client.post("/api/run", json={"day": run_clawnly.days()[0], "max_groups": "6"}).status_code == 403
    sign_out()


def test_an_admin_starts_a_run(monkeypatch):
    reset_db()
    started = []
    monkeypatch.setattr(run_clawnly, "start", lambda day, max_groups, by: (started.append((day, max_groups, by)), (7, None))[1])
    sign_in("admin")
    res = client.post("/api/run", json={"day": run_clawnly.days()[1], "max_groups": "10"})
    sign_out()
    assert res.status_code == 200
    assert res.json() == {"run_id": 7}
    assert started == [(run_clawnly.days()[1], "10", "admin@example.com")]


def test_bad_requests_are_refused_before_anything_runs():
    reset_db()
    sign_in("admin")
    res = client.post("/api/run", json={"day": "2020-01-01", "max_groups": "6"})
    assert res.status_code == 400
    res = client.post("/api/run", json={"day": run_clawnly.days()[0], "max_groups": "5000"})
    assert res.status_code == 400
    sign_out()
    assert db.latest_matchmaker_run() is None


def test_latest_is_public_but_never_says_who_started_it():
    reset_db()
    run_id = db.claim_matchmaker_run(run_clawnly.days()[0], "founder@example.com", 900)
    db.save_matchmaker_run(run_id, {"status": "done", "day": run_clawnly.days()[0], "groups": [], "log": [], "calls": []})
    sign_out()
    body = client.get("/api/run/latest").json()
    assert body["can_run"] is False
    assert body["run"]["status"] == "done"
    assert "founder@example.com" not in json.dumps(body)
    sign_in("admin")
    assert client.get("/api/run/latest").json()["can_run"] is True
    sign_out()


def test_a_run_goes_in_the_background_is_saved_as_it_goes_and_logged(monkeypatch):
    reset_db()
    fake = FakeClient(matchmaker={
        "mm_plan": lambda s, c: json.dumps({"thoughts": "a quiet day", "groups": []}),
        "mm_resolve": lambda s, c: json.dumps({"thoughts": "nothing to fix", "groups": []}),
    })
    monkeypatch.setattr(config, "get_client", lambda: fake)
    saves = []
    real_save = db.save_matchmaker_run
    monkeypatch.setattr(db, "save_matchmaker_run", lambda run_id, data: (saves.append(data["status"]), real_save(run_id, data)))

    async def go():
        run_id, error = run_clawnly.start(run_clawnly.days()[0], "6", "admin@example.com")
        assert error is None
        # one run at a time
        again, busy = run_clawnly.start(run_clawnly.days()[0], "6", "admin@example.com")
        assert again is None
        assert "already going" in busy
        await asyncio.gather(*list(run_clawnly._TASKS))
        return run_id

    run_id = run(go())
    saved = db.get_matchmaker_run(run_id)
    assert saved["status"] == "done"
    assert saved["data"]["plan"]["thoughts"] == "a quiet day"
    assert len(saves) > 2
    texts = [e["text"] for e in db.list_neighborhood_events(None)] + [
        r["text"] for r in db._get_conn().execute("SELECT text FROM events").fetchall()]
    assert any("started Run Clawnly #" + str(run_id) in t for t in texts)
    assert any("Run Clawnly #" + str(run_id) + " for" in t and "ended: done" in t for t in texts)


def test_a_run_without_an_api_key_fails_and_says_why(monkeypatch):
    reset_db()

    def no_key():
        raise ValueError("No Anthropic API key found.")

    monkeypatch.setattr(config, "get_client", no_key)

    async def go():
        run_id, error = run_clawnly.start(run_clawnly.days()[0], "6", "admin@example.com")
        await asyncio.gather(*list(run_clawnly._TASKS))
        return run_id

    saved = db.get_matchmaker_run(run(go()))
    assert saved["status"] == "failed"
    assert "No Anthropic API key" in saved["data"]["log"][-1]["text"]


def test_a_restart_releases_a_run_that_was_going():
    reset_db()
    run_id = db.claim_matchmaker_run(run_clawnly.days()[0], "admin@example.com", 900)
    with TestClient(webapp.app):
        pass
    assert db.get_matchmaker_run(run_id)["status"] == "failed"
    assert db.claim_matchmaker_run(run_clawnly.days()[0], "admin@example.com", 900) is not None
