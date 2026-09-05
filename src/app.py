"""Clawnly web app -- run the matchmaker, chat with the people, edit them, and
ask the Master Claw why it did what it did.

A small FastAPI backend that reuses the existing engine. All state (the cast,
past runs/matches, feedback) is persisted in a small SQLite file via db.py
(Milestone 1) instead of an in-memory dict, so it survives a server restart.
The pipeline and chat run in either:
  - demo mode : free + offline (scripted AI via DemoClient) -- the default
  - live mode : real Claude (needs ANTHROPIC_API_KEY)

Run:  .venv/bin/python src/app.py   (or double-click Clawnly.command)
"""

import asyncio
import html
import json
import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

import auth
import config
import db
from claw import Claw
from demo import DemoClient
from explain import explain_decision, context_summary
from main import run_pipeline
import admin
import batch
import my_match
import onboarding
import usage
from persona_gen import generate_users, nudge_user, DEFAULT_THEME
from users import USERS, HOBBY_CATEGORIES, AVAILABILITY_WINDOWS

app = FastAPI(title="Clawnly")

db.init_db()
db.seed_default_users_if_empty(USERS)


def _flag(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


# DEMO-ONLY mode: when set (e.g. on a public cloud deploy), the server ignores any
# request to use Live mode and runs everything as the free offline demo -- so a
# public URL can never spend real API money. Env: CLAWNLY_DEMO_ONLY=1.
DEMO_ONLY = _flag("CLAWNLY_DEMO_ONLY")

# BRING-YOUR-OWN-KEY mode: Live is allowed, but ONLY with a key the visitor
# supplies on each request. The server never has a key of its own and never
# stores a visitor's key, so real runs are billed to whoever brought the key --
# not to the app owner. Env: CLAWNLY_BYOK=1. (DEMO_ONLY wins if both are set.)
BYOK = _flag("CLAWNLY_BYOK") and not DEMO_ONLY


def _effective_mode(mode):
    # force demo when the deploy is locked to demo-only.
    if DEMO_ONLY:
        return "demo"
    return mode


# short-lived, single-use tokens that let the EventSource stream (a GET that
# can't carry a header) fetch a browser-supplied key without ever putting the key
# in a URL. token -> (key, expiry). In-memory only; nothing is persisted.
_SESSIONS = {}
_SESSION_TTL = 120.0   # seconds


def _new_session(key):
    import secrets
    import time
    token = secrets.token_urlsafe(24)
    _SESSIONS[token] = (key, time.time() + _SESSION_TTL)
    return token


def _pop_session_key(token):
    # single-use: consume the token and prune anything expired.
    import time
    now = time.time()
    tokens = list(_SESSIONS.keys())
    i = 0
    while i < len(tokens):
        t = tokens[i]
        entry = _SESSIONS.get(t)
        if entry is not None and entry[1] < now:
            _SESSIONS.pop(t, None)
        i += 1
    entry = _SESSIONS.pop(token or "", None)
    if entry is None:
        return None
    return entry[0]


_HERE = os.path.dirname(os.path.abspath(__file__))
_INDEX = os.path.join(_HERE, "web", "index.html")
_JOIN = os.path.join(_HERE, "web", "join.html")
_CONSENT = os.path.join(_HERE, "web", "consent.html")
_ONBOARDING = os.path.join(_HERE, "web", "onboarding.html")
_MY_MATCH = os.path.join(_HERE, "web", "my-match.html")
_ADMIN = os.path.join(_HERE, "web", "admin.html")
_PRIVACY = os.path.join(_HERE, "web", "privacy.html")


def _users_signature(users):
    # changes whenever any user is edited -> invalidates the interview cache
    # and "forgets" the last run for master-chat (both are signature-scoped).
    return json.dumps(users, sort_keys=True)


def _request_key(request):
    # the visitor's own key, sent per-request in a header (BYOK mode).
    if request is None:
        return None
    return request.headers.get("x-anthropic-key")


def _client_for(mode, key=None):
    # demo -> scripted offline client; live -> the real client. In BYOK mode the
    # live client is built from the caller's own key; otherwise it's None (the
    # engine builds the server's own client).
    if mode == "demo":
        return DemoClient()
    if BYOK:
        return config.client_from_key(key)
    return None


def _counting_client(mode, key=None):
    # a real/demo client wrapped so the run reports its call usage.
    if mode == "demo":
        inner = DemoClient()
    elif BYOK:
        inner = config.client_from_key(key)   # visitor's own key; billed to them
    else:
        inner = config.get_client()           # server's key (raises if none; caught upstream)
    return usage.CountingClient(inner)


@app.get("/")
async def index():
    return FileResponse(_INDEX)


@app.get("/api/config")
async def api_config():
    # lets the front-end adapt: hide Live on a demo-only deploy, or ask for the
    # visitor's own key in bring-your-own-key mode.
    return {"demo_only": DEMO_ONLY, "byok": BYOK}


@app.post("/api/session")
async def api_session(body: dict):
    # BYOK only: exchange a browser-held key for a short-lived, single-use token
    # the EventSource stream can present (so the key never rides in a URL).
    if not BYOK:
        return JSONResponse(status_code=400, content={"error": "not applicable"})
    key = (body.get("key") or "").strip()
    if len(key) < 8:
        return JSONResponse(status_code=400, content={"error": "Enter your Anthropic API key first."})
    return {"token": _new_session(key)}


@app.get("/api/users")
async def api_users():
    # the editable cast, plus the vocab the edit form needs.
    return {
        "users": db.list_users(),
        "availability_windows": AVAILABILITY_WINDOWS,
        "hobby_categories": HOBBY_CATEGORIES,
    }


def _validate_changes(changes):
    # reject edits that would create an impossible/invalid profile. Returns an
    # error message, or None if the changes are fine.
    if "personality" in changes and changes["personality"] not in ["introverted", "extroverted", "mixed"]:
        return "personality must be introverted, extroverted, or mixed"
    if "occupation" in changes and changes["occupation"] not in ["student", "working professional", "freelancer"]:
        return "occupation must be student, working professional, or freelancer"
    if "availability" in changes:
        avail = changes["availability"]
        if not isinstance(avail, list) or len(avail) == 0:
            return "pick at least one availability window"
        i = 0
        while i < len(avail):
            if avail[i] not in AVAILABILITY_WINDOWS:
                return "unknown availability window: " + str(avail[i])
            i += 1
    if "hobbies" in changes:
        if not isinstance(changes["hobbies"], list) or len(changes["hobbies"]) == 0:
            return "add at least one hobby"
    if "preferred_group_size" in changes:
        size = changes["preferred_group_size"]
        if size != "no preference":
            ok = isinstance(size, list) and len(size) == 2
            if not ok:
                return 'group size must be "no preference" or two numbers like 2,3'
            low = size[0]
            high = size[1]
            if not (isinstance(low, int) and isinstance(high, int) and 2 <= low <= high <= 8):
                return "group size range must be between 2 and 8 (min <= max)"
    return None


@app.post("/api/users/{uid}")
async def api_edit_user(uid: str, changes: dict):
    # update editable traits on one user (no AI -- direct edit).
    user = db.get_user(uid)
    if user is None:
        return JSONResponse(status_code=404, content={"error": "no such user"})
    problem = _validate_changes(changes)
    if problem is not None:
        return JSONResponse(status_code=400, content={"error": problem})
    return db.update_user(uid, changes)


@app.post("/api/users/{uid}/nudge")
async def api_nudge_user(uid: str, body: dict, request: Request):
    # AI-assisted edit: "make them more X" rewrites the profile (live mode only).
    user = db.get_user(uid)
    if user is None:
        return JSONResponse(status_code=404, content={"error": "no such user"})
    if DEMO_ONLY:
        return JSONResponse(status_code=403,
                            content={"error": "AI editing is disabled in this public demo. Edit the fields directly."})
    if body.get("mode", "demo") == "demo":
        return JSONResponse(status_code=400,
                            content={"error": "AI editing needs Live mode -- or edit the fields directly."})
    instruction = (body.get("instruction") or "").strip()
    if len(instruction) == 0:
        return JSONResponse(status_code=400, content={"error": "Say how to change them, e.g. 'make her more outgoing'."})
    try:
        changes = await nudge_user(user, instruction,
                                   client=_client_for(body.get("mode"), _request_key(request)))
    except Exception as error:
        return JSONResponse(status_code=500, content={"error": str(error)})
    problem = _validate_changes(changes)
    if problem is not None:
        return JSONResponse(status_code=400, content={"error": "AI produced an invalid change: " + problem})
    return db.update_user(uid, changes)


@app.post("/api/reset")
async def api_reset():
    # restore the original 12 people and forget all edits. Past runs/matches
    # and feedback history are untouched (same as before Milestone 1).
    db.replace_users(USERS)
    return {"users": db.list_users()}


@app.get("/api/feedback")
async def api_get_feedback():
    return {"feedback": db.list_feedback()}


@app.post("/api/feedback")
async def api_add_feedback(body: dict):
    # record a thumbs-up/down on a group so future matches can learn from it.
    rating = body.get("rating")
    if rating not in ["up", "down"]:
        return JSONResponse(status_code=400, content={"error": "rating must be 'up' or 'down'"})
    entry = {
        "members": body.get("members", []),
        "rating": rating,
        "note": (body.get("note") or "").strip(),
    }
    db.add_feedback(entry)
    return {"feedback": db.list_feedback()}


@app.post("/api/feedback/clear")
async def api_clear_feedback():
    db.clear_feedback()
    return {"feedback": []}


def _persist_key(key):
    # set it for this running server, and save it to .env so it survives a restart.
    os.environ["ANTHROPIC_API_KEY"] = key
    root = os.path.dirname(_HERE)
    try:
        with open(os.path.join(root, ".env"), "w") as handle:
            handle.write("ANTHROPIC_API_KEY=" + key + "\n")
    except Exception:
        pass


@app.get("/api/key-status")
async def api_key_status():
    # whether a usable key is configured (never returns the key itself).
    return {"configured": config.resolve_api_key() is not None}


@app.post("/api/key")
async def api_set_key(body: dict):
    if DEMO_ONLY:
        return JSONResponse(status_code=403,
                            content={"error": "Key entry is disabled in this public demo."})
    key = (body.get("key") or "").strip()
    if len(key) < 8:
        return JSONResponse(status_code=400, content={"error": "That doesn't look like an API key."})
    _persist_key(key)
    return {"configured": True}


def _persist_run(mode, signature, result, reused):
    # admin-console runs are never neighborhood-scoped (neighborhood_id=None);
    # the actual save sequence lives in db.persist_run_result, shared with
    # batch.py's real-pilot batch runs so it's written in exactly one place.
    db.persist_run_result(mode, signature, result)
    result["interviews_reused"] = reused


@app.post("/api/run")
async def api_run(request: Request, mode: str = "demo"):
    # run the full pipeline on the (possibly edited) cast; persist the result.
    # Reuse cached interviews when the cast + mode are unchanged (skips 12 calls).
    mode = _effective_mode(mode)
    key = _request_key(request)
    try:
        users = db.list_users()
        signature = _users_signature(users)
        cached = db.find_cached_interviews(signature, mode)
        result = await run_pipeline(users, client=_counting_client(mode, key),
                                    verbose=False, interviews=cached, feedback=db.list_feedback())
        _persist_run(mode, signature, result, cached is not None)
        return result
    except Exception as error:
        return JSONResponse(status_code=500, content={"error": str(error)})


@app.get("/api/run-stream")
async def api_run_stream(mode: str = "demo", session: str = None):
    # same run, but streamed live (Server-Sent Events): each stage and each
    # negotiation step is pushed as it happens, so the UI fills in progressively.
    # In BYOK mode the visitor's key arrives as a one-time session token (a header
    # can't ride on an EventSource GET).
    mode = _effective_mode(mode)
    key = None
    if BYOK and mode == "live":
        key = _pop_session_key(session)
    queue = asyncio.Queue()

    def on_stage(stage, data):
        queue.put_nowait({"stage": stage, "data": data})

    async def run():
        try:
            users = db.list_users()
            signature = _users_signature(users)
            cached = db.find_cached_interviews(signature, mode)
            result = await run_pipeline(users, client=_counting_client(mode, key),
                                        verbose=False, interviews=cached, on_stage=on_stage,
                                        feedback=db.list_feedback())
            _persist_run(mode, signature, result, cached is not None)
        except Exception as error:
            queue.put_nowait({"stage": "error", "data": str(error)})
        finally:
            queue.put_nowait(None)   # sentinel: stream complete

    task = asyncio.create_task(run())

    async def events():
        while True:
            item = await queue.get()
            if item is None:
                break
            yield "data: " + json.dumps(item) + "\n\n"
        await task

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/api/generate-cast")
async def api_generate_cast(request: Request, body: dict):
    # re-roll the 12 people with real AI -- a fresh, random, diverse cast each
    # time (no theme). Uses the API -> live only.
    if DEMO_ONLY:
        return JSONResponse(status_code=403,
                            content={"error": "Generating a fresh cast is disabled in this public demo."})
    mode = body.get("mode", "demo")
    if mode == "demo":
        return JSONResponse(status_code=400,
                            content={"error": "Generating a fresh cast uses real AI -- switch to Live mode."})
    try:
        users = await generate_users(count=12, theme=DEFAULT_THEME,
                                     client=_client_for(mode, _request_key(request)))
    except Exception as error:
        return JSONResponse(status_code=500, content={"error": str(error)})
    # generation fans out one call per person; if too many failed (e.g. rate limits)
    # we get a short cast back. Don't wipe the current cast with a broken one.
    if len(users) < 3:
        return JSONResponse(status_code=502, content={
            "error": "Couldn't invent a full cast (the AI returned {} usable people). "
                     "Your current cast is unchanged -- try again in a moment.".format(len(users))})
    db.replace_users(users)
    warning = None
    if len(users) < 12:
        warning = "Only {} of 12 people came back this time (some AI calls failed).".format(len(users))
    return {"users": db.list_users(), "warning": warning}


@app.post("/api/chat")
async def api_chat(body: dict, request: Request):
    # talk to one persona, in character. history = [{role, content}, ...].
    user = db.get_user(body.get("user_id"))
    if user is None:
        return JSONResponse(status_code=404, content={"error": "no such user"})
    claw = Claw(user, client=_client_for(_effective_mode(body.get("mode", "demo")), _request_key(request)))
    try:
        reply = await claw.chat(body.get("message", ""), body.get("history", []))
        return {"reply": reply}
    except Exception as error:
        return JSONResponse(status_code=500, content={"error": str(error)})


@app.post("/api/master-chat")
async def api_master_chat(body: dict, request: Request):
    # ask the Master Claw why it decided what it did (about the last run for
    # the CURRENT cast -- editing or resetting people "forgets" the last run,
    # same as before Milestone 1).
    signature = _users_signature(db.list_users())
    run_id = db.latest_run_id_for_signature(signature)
    if run_id is None:
        return {"reply": "Run the matchmaker first, then I can explain what I did and why."}
    run_result = db.load_run_result(run_id)
    mode = _effective_mode(body.get("mode", "demo"))
    if mode == "demo":
        # free, offline: a grounded summary built from the actual run (no AI).
        return {"reply": "In demo mode I can't chat freely, but here's the record of what I did:\n\n"
                + context_summary(run_result)}
    try:
        # client is None for the server's own key, or the visitor's key in BYOK.
        reply = await explain_decision(body.get("message", ""), run_result,
                                       body.get("history", []),
                                       client=_client_for("live", _request_key(request)))
        return {"reply": reply}
    except Exception as error:
        return JSONResponse(status_code=500, content={"error": str(error)})


# ============================================================================
# Real-user pilot: authentication (Google OAuth + email magic link).
# One session model for both; residents and the admin allowlist share it.
# See auth.py for the actual OAuth/magic-link/session mechanics.
# ============================================================================

def _login_success_html(result):
    # admins have no onboarding/consent flow yet (admin dashboard is a later
    # stage) -- this just proves the login mechanics work for them.
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
async def google_login(request: Request, neighborhood: str = None):
    if not auth.google_configured():
        return JSONResponse(status_code=503, content={"error": "Google login is not configured yet."})
    neighborhood_id = None
    if neighborhood is not None and len(neighborhood.strip()) > 0:
        nb = db.get_or_create_neighborhood(neighborhood.strip(), neighborhood.strip(), config.MATCH_BATCH_THRESHOLD)
        neighborhood_id = nb["id"]
    redirect_uri = str(request.url_for("google_callback"))
    try:
        url = auth.google_authorize_url(redirect_uri, neighborhood_id)
    except ValueError as error:
        return JSONResponse(status_code=503, content={"error": str(error)})
    return RedirectResponse(url)


@app.get("/auth/google/callback")
async def google_callback(request: Request, code: str = None, state: str = None):
    if code is None:
        return JSONResponse(status_code=400, content={"error": "Missing authorization code."})
    redirect_uri = str(request.url_for("google_callback"))
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
        slug = str(neighborhood).strip()
        nb = db.get_or_create_neighborhood(slug, slug, config.MATCH_BATCH_THRESHOLD)
        neighborhood_id = nb["id"]
    elif not auth.is_admin(email):
        return JSONResponse(status_code=400,
                            content={"error": "This login link is missing a neighborhood invite code."})
    verify_base_url = str(request.url_for("magic_link_verify"))
    await auth.request_magic_link(email, neighborhood_id, verify_base_url)
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
# Real-user pilot: onboarding (the open-ended chat that fills in a profile).
# Private, authenticated, real-data routes -- always live (see onboarding.py's
# module docstring for why demo/BYOK don't apply here).
# ============================================================================

def _require_consented_resident(request):
    # the auth/consent gate both onboarding API routes need. Returns
    # (resident, None) on success, or (None, an error JSONResponse) otherwise.
    session = auth.current_session(request)
    if session is None:
        return None, JSONResponse(status_code=401, content={"error": "not logged in"})
    resident_id = session.get("resident_id")
    if resident_id is None:
        return None, JSONResponse(status_code=400, content={"error": "Only residents onboard."})
    resident = db.get_resident(resident_id)
    if resident is None:
        return None, JSONResponse(status_code=404, content={"error": "resident not found"})
    if resident["consent_agreed_at"] is None:
        return None, JSONResponse(status_code=403, content={"error": "Consent is required before onboarding."})
    return resident, None


@app.get("/onboarding")
async def onboarding_page():
    return FileResponse(_ONBOARDING)


@app.get("/api/onboarding/history")
async def api_onboarding_history(request: Request):
    resident, error_response = _require_consented_resident(request)
    if error_response is not None:
        return error_response
    messages = db.get_onboarding_messages(resident["id"])
    return {"messages": messages, "slots_status": resident["slots_status"],
            "complete": resident["profile_complete_at"] is not None}


@app.post("/api/onboarding/message")
async def api_onboarding_message(body: dict, request: Request):
    resident, error_response = _require_consented_resident(request)
    if error_response is not None:
        return error_response
    message = (body.get("message") or "").strip()
    if len(message) == 0:
        return JSONResponse(status_code=400, content={"error": "Message can't be empty."})
    try:
        return await onboarding.take_turn(resident, message)
    except Exception as error:
        return JSONResponse(status_code=500, content={"error": str(error)})


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


@app.get("/api/admin/neighborhoods")
async def api_admin_neighborhoods(request: Request):
    session, error_response = _require_admin(request)
    if error_response is not None:
        return error_response
    return {"neighborhoods": admin.list_neighborhood_progress()}


@app.get("/api/admin/neighborhoods/{neighborhood_id}")
async def api_admin_neighborhood_detail(neighborhood_id: int, request: Request):
    session, error_response = _require_admin(request)
    if error_response is not None:
        return error_response
    neighborhood = db.get_neighborhood(neighborhood_id)
    if neighborhood is None:
        return JSONResponse(status_code=404, content={"error": "no such neighborhood"})
    return {
        "neighborhood": admin.neighborhood_progress(neighborhood),
        "residents": admin.resident_summaries(neighborhood_id),
        "runs": admin.recent_run_summaries(neighborhood_id),
    }


@app.post("/api/admin/neighborhoods/{neighborhood_id}/trigger")
async def api_admin_trigger(neighborhood_id: int, request: Request):
    session, error_response = _require_admin(request)
    if error_response is not None:
        return error_response
    try:
        run_id, error = await batch.force_trigger_batch(neighborhood_id)
    except Exception as error:
        return JSONResponse(status_code=500, content={"error": str(error)})
    if error is not None:
        return JSONResponse(status_code=400, content={"error": error})
    return {"run_id": run_id}


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
