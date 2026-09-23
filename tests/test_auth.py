"""Tests for auth.py + the /auth and /api/auth/* /api/me routes in app.py.

Real Google OAuth and real Resend calls are never made in tests -- the OAuth
code exchange and the email send are monkeypatched, and Claude calls go
through tests/conftest.py's FakeClient. Also covers the other pilot routes
(consent, bring your agent, my-match, admin) that share this session model.
"""

import os

import pytest
from fastapi.testclient import TestClient

import app as webapp
import auth
import config
import db

client = TestClient(webapp.app)


def reset_state():
    db.reset_all()
    os.environ.pop("CLAWNLY_ADMIN_EMAILS", None)


def clear_env(monkeypatch):
    # config.resolve_env() falls back to reading a real .env file on disk,
    # which may genuinely have real keys in it (e.g. on a dev machine
    # mid-pilot-setup) -- monkeypatch.delenv alone can't hide that. Restrict
    # resolve_env to process env only for the test, so monkeypatch.setenv /
    # delenv fully control what looks "configured" regardless of .env content.
    monkeypatch.setattr(config, "resolve_env", lambda name: os.environ.get(name))


# ----- is_admin ---------------------------------------------------------------

def test_is_admin_reads_the_env_allowlist_freshly(monkeypatch):
    monkeypatch.setenv("CLAWNLY_ADMIN_EMAILS", "founder@example.com, Ops@Example.com")
    assert auth.is_admin("founder@example.com") is True
    assert auth.is_admin("ops@example.com") is True          # case-insensitive
    assert auth.is_admin("stranger@example.com") is False
    assert auth.is_admin(None) is False


def test_is_admin_empty_allowlist_admits_nobody(monkeypatch):
    monkeypatch.delenv("CLAWNLY_ADMIN_EMAILS", raising=False)
    assert auth.is_admin("anyone@example.com") is False


# ----- sessions -----------------------------------------------------------

def test_start_and_read_session():
    reset_state()
    token = auth.start_session("a@example.com", "resident", 3, 1)
    session = db.get_session(token)
    assert session["email"] == "a@example.com"
    assert session["role"] == "resident"
    assert session["resident_id"] == 3


# ----- magic link: request + verify (dev-mode, no Resend key) ---------------

def test_request_magic_link_dev_mode_prints_instead_of_emailing(monkeypatch, capsys):
    reset_state()
    clear_env(monkeypatch)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 100)

    async def run():
        await auth.request_magic_link("a@example.com", nb["id"], "http://testserver/auth/magic-link/verify")
    import asyncio
    asyncio.run(run())

    out = capsys.readouterr().out
    assert "[DEV MODE]" in out
    assert "a@example.com" in out


def test_request_then_verify_magic_link_starts_a_session(monkeypatch):
    reset_state()
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    captured = {}

    async def fake_send(email, link_url):
        captured["link_url"] = link_url
    monkeypatch.setattr(auth, "_send_magic_link_email", fake_send)

    async def run():
        await auth.request_magic_link("a@example.com", nb["id"], "http://testserver/auth/magic-link/verify")
    import asyncio
    asyncio.run(run())

    raw_token = captured["link_url"].split("token=")[1]
    result = auth.verify_magic_link(raw_token)
    assert result["email"] == "a@example.com"
    assert result["role"] == "resident"
    assert db.get_resident(result["resident_id"])["neighborhood_id"] == nb["id"]
    # single-use: verifying again fails.
    assert auth.verify_magic_link(raw_token) is None


def test_verify_magic_link_unknown_token_returns_none():
    reset_state()
    assert auth.verify_magic_link("not-a-real-token") is None


def test_magic_link_without_neighborhood_requires_admin_email(monkeypatch):
    reset_state()
    monkeypatch.setenv("CLAWNLY_ADMIN_EMAILS", "boss@example.com")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    captured = {}

    async def fake_send(email, link_url):
        captured["link_url"] = link_url
    monkeypatch.setattr(auth, "_send_magic_link_email", fake_send)

    async def run():
        await auth.request_magic_link("boss@example.com", None, "http://testserver/auth/magic-link/verify")
    import asyncio
    asyncio.run(run())

    raw_token = captured["link_url"].split("token=")[1]
    result = auth.verify_magic_link(raw_token)
    assert result["role"] == "admin"
    assert result["resident_id"] is None


def test_magic_link_without_neighborhood_rejects_non_admin():
    reset_state()
    nb = None
    with pytest.raises(ValueError):
        auth._resolve_role_and_resident("stranger@example.com", nb, "magic_link")


# ----- Google OAuth (code exchange mocked) -----------------------------------

def test_google_configured_reflects_env(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    assert auth.google_configured() is False
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id-123")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret-123")
    assert auth.google_configured() is True


def test_google_authorize_url_stores_a_consumable_state(monkeypatch):
    reset_state()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id-123")
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    url = auth.google_authorize_url("http://testserver/auth/google/callback", nb["id"])
    assert "accounts.google.com" in url
    assert "state=" in url
    raw_state = url.split("state=")[1].split("&")[0]
    consumed = db.consume_oauth_state(auth._hash_token(raw_state))
    assert consumed["neighborhood_id"] == nb["id"]


def test_google_login_callback_creates_a_session(monkeypatch):
    reset_state()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id-123")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret-123")
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    url = auth.google_authorize_url("http://testserver/auth/google/callback", nb["id"])
    raw_state = url.split("state=")[1].split("&")[0]

    async def fake_fetch_token(self, token_url, code=None):
        return {"access_token": "fake"}

    async def fake_get(self, url):
        class FakeResp:
            def json(inner_self):
                return {"email": "Resident@Example.com", "email_verified": True}
        return FakeResp()

    monkeypatch.setattr("authlib.integrations.httpx_client.AsyncOAuth2Client.fetch_token", fake_fetch_token)
    monkeypatch.setattr("authlib.integrations.httpx_client.AsyncOAuth2Client.get", fake_get)

    async def run():
        return await auth.google_login_callback("fake-code", raw_state, "http://testserver/auth/google/callback")
    import asyncio
    result = asyncio.run(run())
    assert result["email"] == "resident@example.com"          # normalized
    assert db.get_resident(result["resident_id"])["neighborhood_id"] == nb["id"]


def test_google_login_callback_rejects_a_replayed_state(monkeypatch):
    reset_state()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id-123")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret-123")
    with pytest.raises(ValueError):
        import asyncio
        asyncio.run(auth.google_login_callback("code", "not-a-real-state", "http://testserver/x"))


# ----- routes: /api/me, logout ------------------------------------------------

def test_api_me_requires_login():
    reset_state()
    r = client.get("/api/me")
    assert r.status_code == 401


def test_api_me_reflects_the_session_cookie():
    reset_state()
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    token = auth.start_session("a@example.com", "resident", 1, nb["id"])
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        r = client.get("/api/me")
        assert r.status_code == 200
        data = r.json()
        assert data["email"] == "a@example.com"
        assert data["neighborhood_slug"] == "ballard"
    finally:
        client.cookies.clear()


def test_logout_clears_the_session():
    reset_state()
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    token = auth.start_session("a@example.com", "resident", 1, nb["id"])
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        client.post("/api/auth/logout")
        r = client.get("/api/me")
        assert r.status_code == 401
    finally:
        client.cookies.clear()


# ----- routes: magic-link request/verify (end-to-end through the HTTP layer) --

def test_magic_link_request_route_rejects_bad_email():
    reset_state()
    r = client.post("/api/auth/magic-link/request", json={"email": "not-an-email", "neighborhood": "ballard"})
    assert r.status_code == 400


def test_magic_link_request_route_sends_nothing_to_non_admins_without_a_neighborhood(monkeypatch, capsys):
    reset_state()
    clear_env(monkeypatch)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("CLAWNLY_ADMIN_EMAILS", "boss@example.com")
    stranger = client.post("/api/auth/magic-link/request", json={"email": "a@example.com"})
    no_link = capsys.readouterr().out
    boss = client.post("/api/auth/magic-link/request", json={"email": "boss@example.com"})
    # same answer for both, so the form can't be used to find out who the admins are
    assert stranger.status_code == 200 and boss.status_code == 200
    assert stranger.json() == boss.json() == {"sent": True}
    assert "Magic link" not in no_link
    assert "Magic link for boss@example.com" in capsys.readouterr().out


def test_magic_link_request_and_verify_route_round_trip(monkeypatch, capsys):
    reset_state()
    clear_env(monkeypatch)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    r = client.post("/api/auth/magic-link/request",
                    json={"email": "a@example.com", "neighborhood": "ballard", "code": nb["invite_code"]})
    assert r.status_code == 200
    assert r.json()["sent"] is True
    out = capsys.readouterr().out
    assert "[DEV MODE]" in out
    link = [line for line in out.splitlines() if "[DEV MODE]" in line][0]
    verify_url = link.split(": ", 1)[1]
    path_and_query = verify_url.split("testserver", 1)[1]

    r2 = client.get(path_and_query, follow_redirects=False)
    assert r2.status_code == 302
    assert r2.headers["location"] == "/consent"
    assert auth.SESSION_COOKIE_NAME in r2.cookies


def test_magic_link_verify_route_pure_admin_login_goes_to_dashboard(monkeypatch, capsys):
    # a pure admin login -- no neighborhood, so no resident row exists at
    # all -- lands straight on the dashboard rather than a placeholder page.
    reset_state()
    clear_env(monkeypatch)
    monkeypatch.setenv("CLAWNLY_ADMIN_EMAILS", "boss@example.com")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    r = client.post("/api/auth/magic-link/request", json={"email": "boss@example.com"})
    assert r.status_code == 200
    out = capsys.readouterr().out
    link = [line for line in out.splitlines() if "[DEV MODE]" in line][0]
    verify_url = link.split(": ", 1)[1]
    path_and_query = verify_url.split("testserver", 1)[1]

    r2 = client.get(path_and_query, follow_redirects=False)
    assert r2.status_code == 302
    assert r2.headers["location"] == "/admin"
    assert auth.SESSION_COOKIE_NAME in r2.cookies


def test_magic_link_verify_route_admin_via_invite_link_still_gets_consent_flow(monkeypatch, capsys):
    # an admin email that signs in through a REAL invite link still gets a
    # resident row created (see auth._resolve_role_and_resident) and should
    # be able to experience the actual resident flow through it, same as
    # anyone else -- not silently redirected to the admin dashboard instead.
    reset_state()
    clear_env(monkeypatch)
    monkeypatch.setenv("CLAWNLY_ADMIN_EMAILS", "boss@example.com")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    nb = db.get_or_create_neighborhood("ten-trails", "Ten Trails", 100)
    r = client.post("/api/auth/magic-link/request",
                     json={"email": "boss@example.com", "neighborhood": "ten-trails", "code": nb["invite_code"]})
    assert r.status_code == 200
    out = capsys.readouterr().out
    link = [line for line in out.splitlines() if "[DEV MODE]" in line][0]
    verify_url = link.split(": ", 1)[1]
    path_and_query = verify_url.split("testserver", 1)[1]

    r2 = client.get(path_and_query, follow_redirects=False)
    assert r2.status_code == 302
    assert r2.headers["location"] == "/consent"
    assert auth.SESSION_COOKIE_NAME in r2.cookies


def test_magic_link_verify_route_rejects_unknown_token():
    reset_state()
    r = client.get("/auth/magic-link/verify?token=not-real")
    assert r.status_code == 400


# ----- routes: Google OAuth entry point --------------------------------------

def test_google_login_route_503_when_not_configured(monkeypatch):
    reset_state()
    clear_env(monkeypatch)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    r = client.get("/auth/google/login?neighborhood=ballard", follow_redirects=False)
    assert r.status_code == 503


def test_google_login_route_redirects_when_configured(monkeypatch):
    reset_state()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id-123")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret-123")
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    r = client.get("/auth/google/login?neighborhood=ballard&code=" + nb["invite_code"], follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "accounts.google.com" in r.headers["location"]


# ----- routes: invite-link landing page + consent capture ---------------------

def test_join_page_serves_regardless_of_slug():
    reset_state()
    r = client.get("/join/ballard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_consent_page_serves():
    reset_state()
    r = client.get("/consent")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_privacy_page_serves_and_is_public():
    reset_state()
    r = client.get("/privacy")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_api_consent_requires_login():
    reset_state()
    r = client.post("/api/consent")
    assert r.status_code == 401


def test_api_consent_rejects_admin_without_a_resident_row():
    reset_state()
    token = auth.start_session("boss@example.com", "admin", None, None)
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        r = client.post("/api/consent")
        assert r.status_code == 400
    finally:
        client.cookies.clear()


def test_api_consent_records_agreement_and_api_me_reflects_it():
    reset_state()
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    resident = db.get_or_create_resident(nb["id"], "a@example.com", "magic_link")
    assert resident["consent_agreed_at"] is None
    token = auth.start_session("a@example.com", "resident", resident["id"], nb["id"])
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        r = client.get("/api/me")
        assert r.json()["consent_agreed_at"] is None

        r = client.post("/api/consent")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["consent_agreed_at"] is not None

        r = client.get("/api/me")
        assert r.json()["consent_agreed_at"] is not None
    finally:
        client.cookies.clear()


# ----- routes: the resident signup page ------------------------------------------

def _consented_resident_session():
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    resident = db.get_or_create_resident(nb["id"], "a@example.com", "magic_link")
    db.record_consent(resident["id"])
    token = auth.start_session("a@example.com", "resident", resident["id"], nb["id"])
    return resident, token


def test_onboarding_page_serves():
    reset_state()
    r = client.get("/onboarding")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


# ----- routes: my-match (mutual reveal gate) ---------------------------------

def test_my_match_page_serves():
    reset_state()
    r = client.get("/my-match")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_api_my_match_requires_login():
    reset_state()
    r = client.get("/api/my-match")
    assert r.status_code == 401


def test_api_my_match_requires_consent():
    reset_state()
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    resident = db.get_or_create_resident(nb["id"], "a@example.com", "magic_link")
    token = auth.start_session("a@example.com", "resident", resident["id"], nb["id"])
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        r = client.get("/api/my-match")
        assert r.status_code == 403
    finally:
        client.cookies.clear()


def test_api_my_match_reflects_pending_state():
    reset_state()
    resident, token = _consented_resident_session()
    other = db.get_or_create_resident(resident["neighborhood_id"], "other@example.com", "magic_link")
    run_id = db.create_run(resident["neighborhood_id"])
    match_id = db.create_invitation(run_id, ["r" + str(resident["id"]), "r" + str(other["id"])], "headline", 9, {"invite": {}, "pitches": {}})
    db.create_pending_acceptances(match_id, [resident["id"], other["id"]])
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        r = client.get("/api/my-match")
        assert r.status_code == 200
        data = r.json()
        assert data["state"] == "pending"
        assert data["group_size"] == 2
        assert "other_first_names" not in data
    finally:
        client.cookies.clear()


def test_api_my_match_respond_requires_login():
    reset_state()
    r = client.post("/api/my-match/respond", json={"match_id": 1, "response": "accept"})
    assert r.status_code == 401


def test_api_my_match_respond_rejects_a_non_member_match_id():
    reset_state()
    resident, token = _consented_resident_session()
    other_nb = db.get_or_create_neighborhood("fremont", "Fremont", 100)
    other = db.get_or_create_resident(other_nb["id"], "other@example.com", "magic_link")
    run_id = db.create_run(other_nb["id"])
    match_id = db.create_invitation(run_id, ["r" + str(other["id"])], "headline", 9, {"invite": {}, "pitches": {}})
    db.create_pending_acceptances(match_id, [other["id"]])
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        r = client.post("/api/my-match/respond", json={"match_id": match_id, "response": "accept"})
        assert r.status_code == 400
        assert db.get_acceptance(match_id, other["id"])["status"] == "pending"
    finally:
        client.cookies.clear()


def test_api_my_match_respond_accept_round_trip():
    reset_state()
    resident, token = _consented_resident_session()
    other = db.get_or_create_resident(resident["neighborhood_id"], "other@example.com", "magic_link")
    run_id = db.create_run(resident["neighborhood_id"])
    match_id = db.create_invitation(run_id, ["r" + str(resident["id"]), "r" + str(other["id"])], "headline", 9, {"invite": {}, "pitches": {}})
    db.create_pending_acceptances(match_id, [resident["id"], other["id"]])
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        r = client.post("/api/my-match/respond", json={"match_id": match_id, "response": "accept"})
        assert r.status_code == 200
        assert r.json()["state"] == "waiting"
    finally:
        client.cookies.clear()


def test_api_my_match_meetup_records_the_answer_after_the_reveal():
    reset_state()
    resident, token = _consented_resident_session()
    other = db.get_or_create_resident(resident["neighborhood_id"], "other@example.com", "magic_link")
    run_id = db.create_run(resident["neighborhood_id"])
    match_id = db.create_invitation(run_id, ["r" + str(resident["id"]), "r" + str(other["id"])], "headline", 9,
                                    {"invite": {"activity": "tea", "when": "Sunday", "where": "here"}, "pitches": {}})
    db.create_pending_acceptances(match_id, [resident["id"], other["id"]])
    assert client.post("/api/my-match/meetup", json={"match_id": match_id, "answer": "coming"}).status_code == 401
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        # before both say yes there's nothing to answer
        r = client.post("/api/my-match/meetup", json={"match_id": match_id, "answer": "coming"})
        assert r.status_code == 400
        db.respond_to_acceptance(match_id, resident["id"], "accepted")
        db.respond_to_acceptance(match_id, other["id"], "accepted")
        db.mark_match_sealed(match_id)
        assert client.post("/api/my-match/meetup", json={"match_id": "x", "answer": "coming"}).status_code == 400
        r = client.post("/api/my-match/meetup", json={"match_id": match_id, "answer": "different_time"})
        assert r.status_code == 200 and r.json() == {"ok": True, "answer": "different_time"}
        texts = [e["text"] for e in db.list_neighborhood_events(resident["neighborhood_id"])]
        assert any("needs a different time for invitation #" + str(match_id) in t for t in texts)
    finally:
        client.cookies.clear()


# ----- routes: admin dashboard ---------------------------------------------

def _admin_session():
    os.environ["CLAWNLY_ADMIN_EMAILS"] = "boss@example.com"
    token = auth.start_session("boss@example.com", "admin", None, None)
    return token


def test_admin_page_serves():
    reset_state()
    r = client.get("/admin")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_api_admin_neighborhoods_requires_login():
    reset_state()
    r = client.get("/api/admin/neighborhoods")
    assert r.status_code == 401


def test_api_admin_neighborhoods_requires_admin_role():
    reset_state()
    resident, token = _consented_resident_session()
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        r = client.get("/api/admin/neighborhoods")
        assert r.status_code == 403
    finally:
        client.cookies.clear()


def test_api_admin_neighborhoods_lists_progress():
    reset_state()
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 10)
    db.get_or_create_resident(nb["id"], "a@example.com", "google")
    token = _admin_session()
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        r = client.get("/api/admin/neighborhoods")
        assert r.status_code == 200
        rows = r.json()["neighborhoods"]
        assert any(row["slug"] == "ballard" and row["resident_count"] == 1 for row in rows)
    finally:
        client.cookies.clear()


def test_api_admin_neighborhood_detail_unknown_id():
    reset_state()
    token = _admin_session()
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        r = client.get("/api/admin/neighborhoods/999999")
        assert r.status_code == 404
    finally:
        client.cookies.clear()


def test_api_admin_neighborhood_detail_includes_residents_and_runs():
    reset_state()
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 10)
    from conftest import make_joined_resident
    make_joined_resident(nb, "a@example.com", "Alex")
    token = _admin_session()
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        r = client.get("/api/admin/neighborhoods/" + str(nb["id"]))
        assert r.status_code == 200
        data = r.json()
        assert data["neighborhood"]["complete_count"] == 1
        assert data["residents"][0]["email"] == "a@example.com"
        assert data["residents"][0]["status"] == "in_pool"
        assert data["runs"] == []
    finally:
        client.cookies.clear()


def test_api_admin_trigger_requires_admin_role():
    reset_state()
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 10)
    resident, token = _consented_resident_session()
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        r = client.post("/api/admin/neighborhoods/" + str(nb["id"]) + "/trigger")
        assert r.status_code == 403
    finally:
        client.cookies.clear()


def test_api_admin_trigger_reports_not_enough_residents(monkeypatch):
    reset_state()
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    from conftest import FakeClient
    monkeypatch.setattr(config, "get_client", lambda: FakeClient())
    token = _admin_session()
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        r = client.post("/api/admin/neighborhoods/" + str(nb["id"]) + "/trigger")
        assert r.status_code == 400
        assert "at least 2" in r.json()["error"]
    finally:
        client.cookies.clear()


def test_full_magic_link_login_redirects_a_resident_into_the_consent_flow(monkeypatch, capsys):
    reset_state()
    clear_env(monkeypatch)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    r = client.post("/api/auth/magic-link/request",
                    json={"email": "a@example.com", "neighborhood": "ballard", "code": nb["invite_code"]})
    out = capsys.readouterr().out
    link = [line for line in out.splitlines() if "[DEV MODE]" in line][0]
    verify_url = link.split(": ", 1)[1]
    path_and_query = verify_url.split("testserver", 1)[1]
    r2 = client.get(path_and_query, follow_redirects=False)
    client.cookies.set(auth.SESSION_COOKIE_NAME, r2.cookies[auth.SESSION_COOKIE_NAME])
    try:
        r3 = client.get("/consent")
        assert r3.status_code == 200
        r4 = client.post("/api/consent")
        assert r4.status_code == 200
        assert r4.json()["consent_agreed_at"] is not None
    finally:
        client.cookies.clear()


# ----- routes: bring your agent (the signup that replaced the onboarding chat) -----

AGENT_TEXT = "You're 31 and new in town. You miss long Friday dinners with real arguments. " * 8


def test_agent_routes_require_login_and_consent():
    reset_state()
    assert client.get("/api/agent").status_code == 401
    assert client.post("/api/agent/preview", json={}).status_code == 401
    assert client.post("/api/agent/confirm").status_code == 401
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    resident = db.get_or_create_resident(nb["id"], "a@example.com", "magic_link")
    token = auth.start_session("a@example.com", "resident", resident["id"], nb["id"])
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        assert client.get("/api/agent").status_code == 403
        assert client.post("/api/agent/preview", json={}).status_code == 403
    finally:
        client.cookies.clear()


def test_agent_preview_then_confirm_over_http(monkeypatch):
    from conftest import FakeClient, json_body
    reset_state()
    fake = FakeClient(card_queue=[json_body({"essence": "a warm host", "real_vs_public": {"score": 4, "note": "ok"}})])
    monkeypatch.setattr(config, "get_client", lambda: fake)
    resident, token = _consented_resident_session()
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        status = client.get("/api/agent").json()
        assert status["joined"] is False and "ChatGPT" in status["sources"]

        bad = client.post("/api/agent/preview", json={"name": "Noa", "source": "ChatGPT", "text": "short"})
        assert bad.status_code == 400

        r = client.post("/api/agent/preview", json={"name": "Noa", "source": "ChatGPT", "text": AGENT_TEXT})
        assert r.status_code == 200
        assert r.json()["card"]["essence"] == "a warm host"

        # a card sent by the browser is ignored -- confirm joins the stored draft
        r = client.post("/api/agent/confirm", json={"card": {"essence": "forged"}})
        assert r.status_code == 200 and r.json()["joined"] is True
        saved = db.get_resident(resident["id"])
        assert saved["card"]["essence"] == "a warm host"
        assert saved["profile_complete_at"] is not None
    finally:
        client.cookies.clear()


def test_agent_confirm_without_a_card_is_rejected():
    reset_state()
    resident, token = _consented_resident_session()
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        r = client.post("/api/agent/confirm")
        assert r.status_code == 400
    finally:
        client.cookies.clear()


def test_onboarding_page_is_now_bring_your_agent():
    reset_state()
    r = client.get("/onboarding")
    assert r.status_code == 200
    assert "Bring your agent" in r.text
    assert "/api/agent/preview" in r.text


def test_confirm_schedules_the_hub_check_once(monkeypatch):
    from conftest import FakeClient, json_body
    import batch
    reset_state()
    scheduled = []
    monkeypatch.setattr(batch, "schedule_check", lambda neighborhood_id: scheduled.append(neighborhood_id))
    fake = FakeClient(card_queue=[json_body({"essence": "a warm host"})])
    monkeypatch.setattr(config, "get_client", lambda: fake)
    resident, token = _consented_resident_session()
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        client.post("/api/agent/preview", json={"name": "Noa", "source": "Claude", "text": AGENT_TEXT})
        assert client.post("/api/agent/confirm").status_code == 200
        assert client.post("/api/agent/confirm").status_code == 200     # already in: no second check
        assert scheduled == [resident["neighborhood_id"]]
    finally:
        client.cookies.clear()


def test_api_admin_run_detail_is_admin_only_and_complete():
    reset_state()
    run_id = db.create_run()
    db.log_event(run_id, "hub", "thought", "why I paired them")
    assert client.get("/api/admin/runs/" + str(run_id)).status_code == 401
    resident, token = _consented_resident_session()
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        assert client.get("/api/admin/runs/" + str(run_id)).status_code == 403
    finally:
        client.cookies.clear()
    client.cookies.set(auth.SESSION_COOKIE_NAME, _admin_session())
    try:
        r = client.get("/api/admin/runs/" + str(run_id))
        assert r.status_code == 200
        assert r.json()["events"][0]["text"] == "why I paired them"
        assert client.get("/api/admin/runs/999999").status_code == 404
    finally:
        client.cookies.clear()


def test_root_points_residents_to_their_invite_link():
    reset_state()
    r = client.get("/")
    assert r.status_code == 200
    assert "invite link" in r.text



# ----- security: the holes found by the loophole test, locked shut --------------------

def _dev_links(capsys):
    return [line for line in capsys.readouterr().out.splitlines() if "[DEV MODE]" in line]


def test_nobody_joins_or_creates_a_neighborhood_without_its_invite_code(monkeypatch, capsys):
    reset_state()
    clear_env(monkeypatch)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    nb = db.get_or_create_neighborhood("ten-trails", "Ten Trails", 10)
    attempts = [
        {"email": "x@evil.example", "neighborhood": "ten-trails"},                       # no code
        {"email": "x@evil.example", "neighborhood": "ten-trails", "code": "guess"},      # wrong code
        {"email": "x@evil.example", "neighborhood": "ten-trails", "code": "ten-trails"},  # slug as code
        {"email": "x@evil.example", "neighborhood": "made-up-place", "code": nb["invite_code"]},
        {"email": "x@evil.example", "neighborhood": "<img src=x onerror=alert(1)>"},
    ]
    for body in attempts:
        r = client.post("/api/auth/magic-link/request", json=body)
        assert r.status_code == 400, body
    assert _dev_links(capsys) == []                     # no link was ever sent
    assert [n["slug"] for n in db.list_neighborhoods()] == ["ten-trails"]   # nothing was created


def test_google_login_also_needs_the_invite_code(monkeypatch):
    reset_state()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id-123")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret-123")
    db.get_or_create_neighborhood("ballard", "Ballard", 100)
    assert client.get("/auth/google/login?neighborhood=ballard", follow_redirects=False).status_code == 400
    assert client.get("/auth/google/login?neighborhood=ballard&code=nope", follow_redirects=False).status_code == 400
    assert client.get("/auth/google/login?neighborhood=new-place&code=x", follow_redirects=False).status_code == 400
    assert db.get_neighborhood_by_slug("new-place") is None


def test_an_unverified_google_email_never_signs_in(monkeypatch):
    reset_state()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id-123")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret-123")
    monkeypatch.setenv("CLAWNLY_ADMIN_EMAILS", "boss@example.com")
    url = auth.google_authorize_url("http://testserver/auth/google/callback", None)
    raw_state = url.split("state=")[1].split("&")[0]

    async def fake_fetch_token(self, token_url, code=None):
        return {"access_token": "fake"}

    async def fake_get(self, url):
        class FakeResp:
            def json(inner_self):
                return {"email": "boss@example.com", "email_verified": False}    # someone else's address
        return FakeResp()

    monkeypatch.setattr("authlib.integrations.httpx_client.AsyncOAuth2Client.fetch_token", fake_fetch_token)
    monkeypatch.setattr("authlib.integrations.httpx_client.AsyncOAuth2Client.get", fake_get)
    import asyncio
    with pytest.raises(ValueError):
        asyncio.run(auth.google_login_callback("fake-code", raw_state, "http://testserver/auth/google/callback"))


def test_sign_in_links_ignore_a_forged_host_header(monkeypatch, capsys):
    reset_state()
    monkeypatch.setattr(config, "resolve_env",
                        lambda name: "https://clawnly.example" if name == "CLAWNLY_BASE_URL" else os.environ.get(name))
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    client.post("/api/auth/magic-link/request", headers={"host": "evil.example"},
                json={"email": "victim@example.com", "neighborhood": "ballard", "code": nb["invite_code"]})
    links = _dev_links(capsys)
    assert len(links) == 1
    assert "https://clawnly.example/auth/magic-link/verify?token=" in links[0]
    assert "evil.example" not in links[0]


def test_sign_in_links_are_throttled_per_address_without_revealing_it(monkeypatch, capsys):
    reset_state()
    clear_env(monkeypatch)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    body = {"email": "victim@example.com", "neighborhood": "ballard", "code": nb["invite_code"]}
    answers = [client.post("/api/auth/magic-link/request", json=body).json() for _ in range(5)]
    assert answers == [{"sent": True}] * 5              # the form answers the same every time
    assert len(_dev_links(capsys)) == auth.MAX_MAGIC_LINKS_PER_WINDOW
    texts = [e["text"] for e in db.list_neighborhood_events(nb["id"])]
    assert texts.count("Held back a sign-in link: too many requested for one address in 15 minutes.") == 2


def test_every_page_refuses_to_be_framed_and_hides_its_url():
    reset_state()
    for path in ["/", "/my-match", "/onboarding", "/admin", "/join/x"]:
        headers = client.get(path).headers
        assert headers["x-frame-options"] == "DENY", path
        assert "frame-ancestors 'none'" in headers["content-security-policy"], path
        assert headers["referrer-policy"] == "no-referrer", path
        assert headers["x-content-type-options"] == "nosniff", path


def test_only_an_admin_creates_neighborhoods_and_gets_the_secret_link():
    reset_state()
    body = {"slug": "ten-trails", "name": "Ten Trails"}
    assert client.post("/api/admin/neighborhoods", json=body).status_code == 401
    resident, token = _consented_resident_session()
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        assert client.post("/api/admin/neighborhoods", json=body).status_code == 403
    finally:
        client.cookies.clear()
    client.cookies.set(auth.SESSION_COOKIE_NAME, _admin_session())
    try:
        assert client.post("/api/admin/neighborhoods", json={"slug": "Bad Slug!"}).status_code == 400
        r = client.post("/api/admin/neighborhoods", json=body)
        assert r.status_code == 200
        nb = db.get_neighborhood_by_slug("ten-trails")
        assert r.json()["invite_link"].endswith("/join/ten-trails?code=" + nb["invite_code"])
        detail = client.get("/api/admin/neighborhoods/" + str(nb["id"])).json()
        assert detail["invite_link"] == r.json()["invite_link"]
        assert "created the neighborhood" in detail["activity"]["events"][0]["text"]
    finally:
        client.cookies.clear()


def test_a_preview_failure_shows_a_plain_message_not_internals(monkeypatch):
    reset_state()

    def broken():
        raise RuntimeError("secret internal detail sk-ant-xyz")
    monkeypatch.setattr(config, "get_client", broken)
    resident, token = _consented_resident_session()
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    try:
        r = client.post("/api/agent/preview", json={"name": "Noa", "source": "Claude", "text": AGENT_TEXT})
        assert r.status_code == 500
        assert "secret internal detail" not in r.text and "sk-ant" not in r.text
    finally:
        client.cookies.clear()
