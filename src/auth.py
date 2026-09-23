"""Real-user authentication: Google OAuth + email magic links, one session model.

A session is an opaque token (secrets.token_urlsafe) in an httpOnly cookie,
validated by looking it up in db.py's sessions table -- not a signed/JWT
token. A DB lookup is simpler to reason about and trivially revocable
(delete the row), which matters more than saving one round trip for a pilot
this size. Admin access is a plain email allowlist (config.ADMIN_EMAILS),
not a role/permission system -- this is a single-operator alpha, not a
multi-tenant platform.

Two login paths converge on the same session mechanism:
  - Google OAuth (authlib) -- one click, verified email.
  - Email magic link -- a single-use, hashed, expiring token mailed via Resend
    (a plain httpx call, no email SDK). If RESEND_API_KEY isn't configured,
    the link is printed to the server console instead of emailed, so local
    development and testing work before a real Resend account exists.
"""

import hashlib
import json
import os
import secrets

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client

import config
import db


SESSION_COOKIE_NAME = "clawnly_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30      # 30 days -- a casual social app, not a bank
MAGIC_LINK_TTL_SECONDS = 60 * 15             # 15 minutes
OAUTH_STATE_TTL_SECONDS = 60 * 15            # 15 minutes

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_SCOPE = "openid email profile"

RESEND_URL = "https://api.resend.com/emails"
MAGIC_LINK_FROM = "Clawnly <onboarding@clawnly.app>"


def _hash_token(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_admin(email):
    if email is None:
        return False
    return email.strip().lower() in config.parse_admin_emails()


def _on_cloud():
    # same signal app.py's __main__ block already uses to tell a local run
    # from a Render (or similar) deploy.
    return os.environ.get("PORT") is not None


def set_session_cookie(response, token):
    response.set_cookie(
        SESSION_COOKIE_NAME, token, max_age=SESSION_TTL_SECONDS,
        httponly=True, secure=_on_cloud(), samesite="lax",
    )


def clear_session_cookie(response):
    response.delete_cookie(SESSION_COOKIE_NAME)


def start_session(email, role, resident_id, neighborhood_id):
    token = secrets.token_urlsafe(32)
    db.create_session(token, email, role, resident_id, neighborhood_id, SESSION_TTL_SECONDS)
    return token


def current_session(request):
    # request is a starlette/FastAPI Request; returns the session dict or None.
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token is None:
        return None
    return db.get_session(token)


def logout(request, response):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token is not None:
        db.delete_session(token)
    clear_session_cookie(response)


def _resolve_role_and_resident(email, neighborhood_id, auth_method):
    # an admin email always gets role "admin"; everyone else is a resident of
    # whichever neighborhood they logged in through. A neighborhood is
    # required for a non-admin login -- there's nothing else for them to do.
    admin = is_admin(email)
    if neighborhood_id is None:
        if admin:
            return ("admin", None)
        raise ValueError("This login link is missing a neighborhood invite code.")
    resident = db.get_or_create_resident(neighborhood_id, email, auth_method)
    role = "resident"
    if admin:
        role = "admin"
    return (role, resident["id"])


# ----- Google OAuth --------------------------------------------------------

def google_configured():
    client_id = config.resolve_env("GOOGLE_CLIENT_ID")
    client_secret = config.resolve_env("GOOGLE_CLIENT_SECRET")
    return client_id is not None and client_secret is not None


def _google_client(redirect_uri, client_secret=None):
    client_id = config.resolve_env("GOOGLE_CLIENT_ID")
    if client_id is None:
        raise ValueError("Google login is not configured (set GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET).")
    return AsyncOAuth2Client(
        client_id=client_id, client_secret=client_secret,
        redirect_uri=redirect_uri, scope=GOOGLE_SCOPE,
    )


def google_authorize_url(redirect_uri, neighborhood_id):
    # a random state, stored HASHED and single-use, ties the callback back to
    # which neighborhood this login was for and guards against CSRF.
    raw_state = secrets.token_urlsafe(24)
    db.create_oauth_state(_hash_token(raw_state), neighborhood_id, OAUTH_STATE_TTL_SECONDS)
    client = _google_client(redirect_uri)
    url, _ = client.create_authorization_url(GOOGLE_AUTH_URL, state=raw_state)
    return url


async def google_login_callback(code, state, redirect_uri):
    # exchanges the callback code for a token, fetches the verified email,
    # resolves the state back to a neighborhood, and returns a started session.
    consumed = db.consume_oauth_state(_hash_token(state or ""))
    if consumed is None:
        raise ValueError("This login link has expired or was already used. Try logging in again.")
    client_secret = config.resolve_env("GOOGLE_CLIENT_SECRET")
    if client_secret is None:
        raise ValueError("Google login is not configured (set GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET).")
    client = _google_client(redirect_uri, client_secret=client_secret)
    await client.fetch_token(GOOGLE_TOKEN_URL, code=code)
    resp = await client.get(GOOGLE_USERINFO_URL)
    info = resp.json()
    email = info.get("email")
    if not email:
        raise ValueError("Google did not return an email address.")
    # an unverified address could be anyone's -- including an admin's -- so it never signs in
    if info.get("email_verified") is not True:
        raise ValueError("Google says this email address isn't verified. Verify it with Google, or use the email link.")
    email = email.strip().lower()
    role, resident_id = _resolve_role_and_resident(email, consumed["neighborhood_id"], "google")
    token = start_session(email, role, resident_id, consumed["neighborhood_id"])
    return {"token": token, "email": email, "role": role, "resident_id": resident_id,
            "neighborhood_id": consumed["neighborhood_id"]}


# ----- email magic link -----------------------------------------------------

async def _send_magic_link_email(email, link_url):
    api_key = config.resolve_env("RESEND_API_KEY")
    if api_key is None:
        # dev mode: nothing is actually emailed -- print it so the flow is
        # still testable end-to-end before a real Resend account exists.
        print("[DEV MODE] Magic link for " + email + ": " + link_url)
        return
    body = {"from": MAGIC_LINK_FROM, "to": [email], "subject": "Your Clawnly sign-in link",
            "html": "<p>Tap to sign in: <a href=\"" + link_url + "\">" + link_url + "</a></p>"
                    "<p>This link expires in 15 minutes.</p>"}
    headers = {"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(RESEND_URL, headers=headers, content=json.dumps(body))
        response.raise_for_status()


# at most this many sign-in links per email address per MAGIC_LINK_TTL_SECONDS --
# stops anyone from flooding an inbox (or burning the email quota) through the form
MAX_MAGIC_LINKS_PER_WINDOW = 3


async def request_magic_link(email, neighborhood_id, verify_base_url):
    # returns False (and sends nothing) when this address hit the throttle. The
    # caller answers the same either way, so the form never reveals who's who.
    if db.count_recent_magic_links(email, MAGIC_LINK_TTL_SECONDS) >= MAX_MAGIC_LINKS_PER_WINDOW:
        return False
    raw_token = secrets.token_urlsafe(32)
    db.create_magic_link_token(_hash_token(raw_token), email, neighborhood_id, MAGIC_LINK_TTL_SECONDS)
    link_url = verify_base_url + "?token=" + raw_token
    await _send_magic_link_email(email, link_url)
    return True


def verify_magic_link(raw_token):
    # returns a started session dict, or None if the token is invalid/expired/used.
    consumed = db.consume_magic_link_token(_hash_token(raw_token or ""))
    if consumed is None:
        return None
    email = consumed["email"]
    role, resident_id = _resolve_role_and_resident(email, consumed["neighborhood_id"], "magic_link")
    token = start_session(email, role, resident_id, consumed["neighborhood_id"])
    return {"token": token, "email": email, "role": role, "resident_id": resident_id,
            "neighborhood_id": consumed["neighborhood_id"]}
