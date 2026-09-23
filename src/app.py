"""Clawnly web app -- the real pilot: invite link -> login -> consent ->
bring your agent -> agents talk (the hub) -> a yes/no invitation, plus the
admin dashboard with every round's behind-the-scenes record.

All state lives in a small SQLite file via db.py. AI calls always use the
server's own key (config.get_client()) -- real residents, real data.

Run:  .venv/bin/python src/app.py   (or double-click Clawnly.command)
"""

import html
import os
import re

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

import admin
import auth
import batch
import bring_agent
import config
import db
import my_match

app = FastAPI(title="Clawnly")

db.init_db()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    # no page may be framed by another site (a hidden yes/no button would be clickjackable)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    # sign-in tokens ride in URLs; never hand them to another site in a Referer
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _public_url(request, route_name):
    # links that leave the site (the emailed sign-in link, Google's redirect)
    # use the configured public address, never the request's Host header -- an
    # attacker-controlled Host would otherwise point a victim's sign-in link at
    # the attacker's server. Without CLAWNLY_BASE_URL (local dev) the request's
    # own address is used.
    base = config.resolve_env("CLAWNLY_BASE_URL")
    if base:
        return base.rstrip("/") + app.url_path_for(route_name)
    return str(request.url_for(route_name))


def _invited_neighborhood(slug, code):
    # public input only ever resolves to an EXISTING neighborhood, with its secret code
    if slug is None or len(str(slug).strip()) == 0:
        return None
    return db.neighborhood_for_invite(str(slug).strip(), str(code or "").strip())


_HERE = os.path.dirname(os.path.abspath(__file__))
_JOIN = os.path.join(_HERE, "web", "join.html")
_CONSENT = os.path.join(_HERE, "web", "consent.html")
_ONBOARDING = os.path.join(_HERE, "web", "onboarding.html")
_MY_MATCH = os.path.join(_HERE, "web", "my-match.html")
_ADMIN = os.path.join(_HERE, "web", "admin.html")
_ADMIN_LOGIN = os.path.join(_HERE, "web", "admin-login.html")
_PRIVACY = os.path.join(_HERE, "web", "privacy.html")


@app.get("/")
async def index():
    # residents always arrive through their neighborhood's invite link
    # (/join/<slug>); the bare root just points the way.
    return HTMLResponse(
        "<html><head><meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Clawnly</title></head>"
        "<body style='font-family:-apple-system,sans-serif;max-width:480px;margin:60px auto;padding:0 20px;line-height:1.5'>"
        "<h2>Clawnly</h2>"
        "<p>Your agent meets your neighbors' agents first. You only say yes or no.</p>"
        "<p>Joining? Use the invite link your neighborhood shared with you.</p>"
        "<p><a href='/my-match'>Check my invitation</a> &middot; <a href='/admin/login'>Admin</a> "
        "&middot; <a href='/privacy'>Privacy</a></p>"
        "</body></html>"
    )


# ============================================================================
# Real-user pilot: authentication (Google OAuth + email magic link).
# One session model for both; residents and the admin allowlist share it.
# See auth.py for the actual OAuth/magic-link/session mechanics.
# ============================================================================

def _login_success_html(result):
    # a login with neither a neighborhood nor admin rights has nowhere to go
    # yet -- confirm the sign-in worked and stop there.
    return (
        "<html><body style='font-family:sans-serif;max-width:480px;margin:60px auto'>"
        "<h2>You're logged in</h2>"
        "<p>Signed in as <b>" + html.escape(result["email"]) + "</b> (" + html.escape(result["role"]) + ").</p>"
        "<p><a href='/api/me'>/api/me</a></p>"
        "</body></html>"
    )


def _post_login_response(result):
    # branch on whether a resident row exists, not on role -- an admin email
    # that signs in through a real invite link (/join/<slug>) still gets a
    # resident row (see auth._resolve_role_and_resident) and should be able to
    # experience the actual resident flow through it, same as anyone else.
    # Only a pure admin login (no neighborhood link at all, so no resident row)
    # skips straight to the dashboard.
    if result["resident_id"] is not None:
        response = RedirectResponse(url="/consent", status_code=302)
    elif result["role"] == "admin":
        response = RedirectResponse(url="/admin", status_code=302)
    else:
        response = HTMLResponse(_login_success_html(result))
    auth.set_session_cookie(response, result["token"])
    return response


@app.get("/join/{slug}")
async def join(slug: str):
    return FileResponse(_JOIN)


@app.get("/privacy")
async def privacy_page():
    # ungated, public -- linked from the Google OAuth consent screen and
    # from join.html's consent framing.
    return FileResponse(_PRIVACY)


@app.get("/consent")
async def consent_page():
    return FileResponse(_CONSENT)


@app.post("/api/consent")
async def api_consent(request: Request):
    session = auth.current_session(request)
    if session is None:
        return JSONResponse(status_code=401, content={"error": "not logged in"})
    if session.get("resident_id") is None:
        return JSONResponse(status_code=400, content={"error": "Only residents need to give consent."})
    resident = db.record_consent(session["resident_id"])
    return {"ok": True, "consent_agreed_at": resident["consent_agreed_at"]}


@app.get("/auth/google/login")
async def google_login(request: Request, neighborhood: str = None, code: str = None):
    if not auth.google_configured():
        return JSONResponse(status_code=503, content={"error": "Google login is not configured yet."})
    neighborhood_id = None
    if neighborhood is not None and len(neighborhood.strip()) > 0:
        nb = _invited_neighborhood(neighborhood, code)
        if nb is None:
            return JSONResponse(status_code=400, content={"error": "This invite link isn't valid. Ask for a fresh one."})
        neighborhood_id = nb["id"]
    redirect_uri = _public_url(request, "google_callback")
    try:
        url = auth.google_authorize_url(redirect_uri, neighborhood_id)
    except ValueError as error:
        return JSONResponse(status_code=503, content={"error": str(error)})
    return RedirectResponse(url)


@app.get("/auth/google/callback")
async def google_callback(request: Request, code: str = None, state: str = None):
    if code is None:
        return JSONResponse(status_code=400, content={"error": "Missing authorization code."})
    redirect_uri = _public_url(request, "google_callback")
    try:
        result = await auth.google_login_callback(code, state, redirect_uri)
    except ValueError as error:
        return JSONResponse(status_code=400, content={"error": str(error)})
    except Exception as error:
        return JSONResponse(status_code=500, content={"error": str(error)})
    return _post_login_response(result)


@app.post("/api/auth/magic-link/request")
async def api_magic_link_request(request: Request, body: dict):
    email = (body.get("email") or "").strip().lower()
    if "@" not in email or len(email) < 5:
        return JSONResponse(status_code=400, content={"error": "Enter a valid email address."})
    neighborhood = body.get("neighborhood")
    neighborhood_id = None
    if neighborhood is not None and len(str(neighborhood).strip()) > 0:
        nb = _invited_neighborhood(neighborhood, body.get("code"))
        if nb is None:
            return JSONResponse(status_code=400, content={"error": "This invite link isn't valid. Ask for a fresh one."})
        neighborhood_id = nb["id"]
    elif not auth.is_admin(email):
        # nothing to sign in to, but answer like a sent link -- a different
        # answer would tell anyone which addresses are admins
        return {"sent": True}
    sent = await auth.request_magic_link(email, neighborhood_id, _public_url(request, "magic_link_verify"))
    if not sent and neighborhood_id is not None:
        db.log_event(None, "system", "check", "Held back a sign-in link: too many requested for one address "
                     "in 15 minutes.", None, neighborhood_id)
    # the same answer either way, so the form never reveals anything about an address
    return {"sent": True}


@app.get("/auth/magic-link/verify")
async def magic_link_verify(token: str = None):
    try:
        result = auth.verify_magic_link(token)
    except ValueError as error:
        return JSONResponse(status_code=400, content={"error": str(error)})
    if result is None:
        return JSONResponse(status_code=400, content={"error": "This link is invalid, expired, or already used."})
    return _post_login_response(result)


@app.post("/api/auth/logout")
async def api_logout(request: Request):
    response = JSONResponse(content={"ok": True})
    auth.logout(request, response)
    return response


@app.get("/api/me")
async def api_me(request: Request):
    session = auth.current_session(request)
    if session is None:
        return JSONResponse(status_code=401, content={"error": "not logged in"})
    result = dict(session)
    if session.get("neighborhood_id") is not None:
        neighborhood = db.get_neighborhood(session["neighborhood_id"])
        if neighborhood is not None:
            result["neighborhood_slug"] = neighborhood["slug"]
            result["neighborhood_name"] = neighborhood["name"]
    if session.get("resident_id") is not None:
        resident = db.get_resident(session["resident_id"])
        if resident is not None:
            result["consent_agreed_at"] = resident["consent_agreed_at"]
    return result


# ============================================================================
# Real-user pilot: bring your agent (the signup). The resident pastes what
# their own AI wrote about them; see bring_agent.py. /onboarding serves it.
# ============================================================================

def _require_consented_resident(request):
    # the auth/consent gate every resident API route needs. Returns
    # (resident, None) on success, or (None, an error JSONResponse) otherwise.
    session = auth.current_session(request)
    if session is None:
        return None, JSONResponse(status_code=401, content={"error": "not logged in"})
    resident_id = session.get("resident_id")
    if resident_id is None:
        return None, JSONResponse(status_code=400, content={"error": "Only residents can do this."})
    resident = db.get_resident(resident_id)
    if resident is None:
        return None, JSONResponse(status_code=404, content={"error": "resident not found"})
    if resident["consent_agreed_at"] is None:
        return None, JSONResponse(status_code=403, content={"error": "Consent is required first."})
    return resident, None


@app.get("/onboarding")
async def onboarding_page():
    return FileResponse(_ONBOARDING)


@app.get("/api/agent")
async def api_agent_status(request: Request):
    resident, error_response = _require_consented_resident(request)
    if error_response is not None:
        return error_response
    return bring_agent.status(resident)


@app.post("/api/agent/preview")
async def api_agent_preview(body: dict, request: Request):
    resident, error_response = _require_consented_resident(request)
    if error_response is not None:
        return error_response
    try:
        state, error = await bring_agent.preview(resident, body.get("name"), body.get("source"), body.get("text"))
    except Exception as error:
        # the details are in the AI call log (ai_log); the person gets a plain message
        print("[agent preview] resident {} failed: {}".format(resident["id"], error))
        return JSONResponse(status_code=500, content={"error": "Couldn't read that just now. Try again in a minute."})
    if error is not None:
        return JSONResponse(status_code=400, content={"error": error})
    return state


@app.post("/api/agent/confirm")
async def api_agent_confirm(request: Request):
    resident, error_response = _require_consented_resident(request)
    if error_response is not None:
        return error_response
    already_in = resident["profile_complete_at"] is not None
    state, error = bring_agent.confirm(resident)
    if error is not None:
        return JSONResponse(status_code=400, content={"error": error})
    if not already_in:
        # this join may be the one that fills the neighborhood -- let the hub
        # check, without making the resident wait on a whole round
        batch.schedule_check(resident["neighborhood_id"])
    return state


# ============================================================================
# Real-user pilot: match acceptance (mutual reveal gate). See my_match.py's
# module docstring for the pending/waiting/sealed/dissolved state machine.
# ============================================================================

@app.get("/my-match")
async def my_match_page():
    return FileResponse(_MY_MATCH)


@app.get("/api/my-match")
async def api_my_match(request: Request):
    resident, error_response = _require_consented_resident(request)
    if error_response is not None:
        return error_response
    return my_match.get_state(resident)


@app.post("/api/my-match/respond")
async def api_my_match_respond(body: dict, request: Request):
    resident, error_response = _require_consented_resident(request)
    if error_response is not None:
        return error_response
    match_id = body.get("match_id")
    try:
        match_id = int(match_id)
    except (TypeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "match_id is required."})
    response = body.get("response")
    state, error = my_match.respond(resident, match_id, response)
    if error is not None:
        return JSONResponse(status_code=400, content={"error": error})
    return state


@app.post("/api/my-match/meetup")
async def api_my_match_meetup(body: dict, request: Request):
    resident, error_response = _require_consented_resident(request)
    if error_response is not None:
        return error_response
    try:
        match_id = int(body.get("match_id"))
    except (TypeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "match_id is required."})
    result, error = my_match.meetup_reply(resident, match_id, body.get("answer"))
    if error is not None:
        return JSONResponse(status_code=400, content={"error": error})
    return result


# ============================================================================
# Real-user pilot: admin dashboard (Stage 6). Neighborhood progress, resident
# status, recent batch runs + usage, and a manual "trigger batch now"
# override -- read-only aggregation of data earlier stages already persist
# (see admin.py's module docstring). Plain/functional styling -- an internal
# tool, not resident-facing.
# ============================================================================

def _require_admin(request):
    session = auth.current_session(request)
    if session is None:
        return None, JSONResponse(status_code=401, content={"error": "not logged in"})
    if session.get("role") != "admin":
        return None, JSONResponse(status_code=403, content={"error": "Admin access required."})
    return session, None


@app.get("/admin")
async def admin_page():
    return FileResponse(_ADMIN)


@app.get("/admin/login")
async def admin_login_page():
    # a plain login entry point that never attaches a neighborhood, so an
    # admin email resolves with resident_id=None and _post_login_response
    # sends them straight to /admin -- /join/<slug> always attaches a
    # neighborhood (even for an admin email), which is the intentional path
    # for an admin to experience the real resident flow, not a way to reach
    # the dashboard.
    return FileResponse(_ADMIN_LOGIN)


@app.get("/api/admin/neighborhoods")
async def api_admin_neighborhoods(request: Request):
    session, error_response = _require_admin(request)
    if error_response is not None:
        return error_response
    return {"neighborhoods": admin.list_neighborhood_progress()}


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")


def _invite_link(request, neighborhood):
    base = config.resolve_env("CLAWNLY_BASE_URL")
    if not base:
        base = str(request.base_url)
    return base.rstrip("/") + "/join/" + neighborhood["slug"] + "?code=" + neighborhood["invite_code"]


@app.post("/api/admin/neighborhoods")
async def api_admin_create_neighborhood(body: dict, request: Request):
    # the only way a neighborhood comes into existence: an admin creates it and
    # gets back its secret invite link
    session, error_response = _require_admin(request)
    if error_response is not None:
        return error_response
    slug = str(body.get("slug") or "").strip().lower()
    name = str(body.get("name") or "").strip()[:60]
    if not _SLUG_RE.match(slug):
        return JSONResponse(status_code=400, content={"error": "Use 2-40 lowercase letters, digits or hyphens for the link name."})
    if len(name) == 0:
        name = slug
    existed = db.get_neighborhood_by_slug(slug) is not None
    neighborhood = db.get_or_create_neighborhood(slug, name, config.MATCH_BATCH_THRESHOLD)
    if not existed:
        db.log_event(None, "human", "human", "Admin " + str(session.get("email")) + " created the neighborhood.",
                     None, neighborhood["id"])
    return {"neighborhood": admin.neighborhood_progress(neighborhood), "invite_link": _invite_link(request, neighborhood)}


@app.get("/api/admin/neighborhoods/{neighborhood_id}")
async def api_admin_neighborhood_detail(neighborhood_id: int, request: Request):
    session, error_response = _require_admin(request)
    if error_response is not None:
        return error_response
    neighborhood = db.get_neighborhood(neighborhood_id)
    if neighborhood is None:
        return JSONResponse(status_code=404, content={"error": "no such neighborhood"})
    neighborhood = db.ensure_invite_code(neighborhood_id)
    return {
        "invite_link": _invite_link(request, neighborhood),
        "neighborhood": admin.neighborhood_progress(neighborhood),
        "residents": admin.resident_summaries(neighborhood_id),
        "runs": admin.recent_run_summaries(neighborhood_id),
        "activity": admin.neighborhood_activity(neighborhood_id),
    }


@app.post("/api/admin/neighborhoods/{neighborhood_id}/trigger")
async def api_admin_trigger(neighborhood_id: int, request: Request):
    session, error_response = _require_admin(request)
    if error_response is not None:
        return error_response
    try:
        run_id, error = await batch.force_trigger_batch(neighborhood_id, by=session.get("email"))
    except Exception as error:
        return JSONResponse(status_code=500, content={"error": str(error)})
    if error is not None:
        return JSONResponse(status_code=400, content={"error": error})
    return {"run_id": run_id}


@app.get("/api/admin/runs/{run_id}")
async def api_admin_run(run_id: int, request: Request):
    # one hub round behind the scenes: every event and every agent conversation
    session, error_response = _require_admin(request)
    if error_response is not None:
        return error_response
    detail = admin.run_detail(run_id)
    if detail is None:
        return JSONResponse(status_code=404, content={"error": "no such round"})
    return detail


if __name__ == "__main__":
    import uvicorn
    # cloud hosts (Render, etc.) set PORT and expect the app to bind 0.0.0.0.
    # locally there is no PORT, so we bind localhost and pop open the browser.
    port = int(os.environ.get("PORT", "8000"))
    on_cloud = os.environ.get("PORT") is not None
    if on_cloud:
        print("Clawnly running in the cloud on port " + str(port))
        # trust the platform's proxy headers so request.url_for() (used by the
        # Google OAuth redirect_uri) reports https:// instead of http://.
        uvicorn.run(app, host="0.0.0.0", port=port, proxy_headers=True, forwarded_allow_ips="*")
    else:
        import threading
        import webbrowser
        url = "http://127.0.0.1:" + str(port)
        print("Clawnly is running at  " + url + "   (press Ctrl+C to stop)")
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        uvicorn.run(app, host="127.0.0.1", port=port)
