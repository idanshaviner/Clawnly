"""Tests for auth.py + the /auth and /api/auth/* /api/me routes in app.py.

Real Google OAuth and real Resend calls are never made in tests -- the OAuth
code exchange and the email send are monkeypatched, the same way _client_for
is already mocked for Anthropic calls in test_app.py.
"""

import os

import pytest
from fastapi.testclient import TestClient

import app as webapp
import auth
import config
import db
from users import USERS

client = TestClient(webapp.app)


def reset_state():
    db.reset_all(USERS)
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

def test_magic_link_configured_reflects_env(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert auth.magic_link_configured() is False
    monkeypatch.setenv("RESEND_API_KEY", "re_test_123")
    assert auth.magic_link_configured() is True


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
                return {"email": "resident@example.com"}
        return FakeResp()

    monkeypatch.setattr("authlib.integrations.httpx_client.AsyncOAuth2Client.fetch_token", fake_fetch_token)
    monkeypatch.setattr("authlib.integrations.httpx_client.AsyncOAuth2Client.get", fake_get)

    async def run():
        return await auth.google_login_callback("fake-code", raw_state, "http://testserver/auth/google/callback")
    import asyncio
    result = asyncio.run(run())
    assert result["email"] == "resident@example.com"
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


def test_magic_link_request_route_requires_a_neighborhood_for_non_admins():
    reset_state()
    r = client.post("/api/auth/magic-link/request", json={"email": "a@example.com"})
    assert r.status_code == 400


def test_magic_link_request_and_verify_route_round_trip(monkeypatch, capsys):
    reset_state()
    clear_env(monkeypatch)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    r = client.post("/api/auth/magic-link/request", json={"email": "a@example.com", "neighborhood": "ballard"})
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


def test_magic_link_verify_route_admin_gets_the_plain_success_page(monkeypatch, capsys):
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
    assert r2.status_code == 200
    assert "boss@example.com" in r2.text
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
    r = client.get("/auth/google/login?neighborhood=ballard", follow_redirects=False)
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


def test_full_magic_link_login_redirects_a_resident_into_the_consent_flow(monkeypatch, capsys):
    reset_state()
    clear_env(monkeypatch)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    r = client.post("/api/auth/magic-link/request", json={"email": "a@example.com", "neighborhood": "ballard"})
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
