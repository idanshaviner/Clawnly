"""Clawnly web app -- run the matchmaker, chat with the people, edit them, and
ask the Master Claw why it did what it did.

A small FastAPI backend that reuses the existing engine and holds simple
in-memory state (an editable copy of the 12 users + the last run). The pipeline
and chat run in either:
  - demo mode : free + offline (scripted AI via DemoClient) -- the default
  - live mode : real Claude (needs ANTHROPIC_API_KEY)

Run:  .venv/bin/python src/app.py   (or double-click Clawnly.command)
"""

import asyncio
import copy
import json
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

import config
from claw import Claw
from demo import DemoClient
from explain import explain_decision, context_summary
from main import run_pipeline
from persona_gen import generate_users, nudge_user, DEFAULT_THEME
from users import USERS, HOBBY_CATEGORIES, AVAILABILITY_WINDOWS

app = FastAPI(title="Clawnly")

_HERE = os.path.dirname(os.path.abspath(__file__))
_INDEX = os.path.join(_HERE, "web", "index.html")
_CAST_PATH = os.path.join(os.path.dirname(_HERE), "cast.json")          # edited cast, gitignored
_FEEDBACK_PATH = os.path.join(os.path.dirname(_HERE), "feedback.json")  # learning feedback, gitignored


def _load_json_list(path):
    if os.path.exists(path):
        try:
            with open(path) as handle:
                data = json.load(handle)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def _save_feedback():
    try:
        with open(_FEEDBACK_PATH, "w") as handle:
            json.dump(STATE["feedback"], handle, indent=2)
    except Exception:
        pass


def _load_cast():
    # restore the saved (edited/generated) cast if there is one, else the default 12.
    if os.path.exists(_CAST_PATH):
        try:
            with open(_CAST_PATH) as handle:
                users = json.load(handle)
            if isinstance(users, list) and len(users) > 0:
                return users
        except Exception:
            pass
    return copy.deepcopy(USERS)


def _save_cast():
    # persist the current cast so edits survive an app restart.
    try:
        with open(_CAST_PATH, "w") as handle:
            json.dump(STATE["users"], handle, indent=2)
    except Exception:
        pass


# in-memory state: an editable cast, the most recent run (for explanations), a
# cache of interviews (reused when the cast hasn't changed), and the learning
# feedback the matcher reads on future runs.
STATE = {"users": _load_cast(), "last_run": None, "interview_cache": None,
         "feedback": _load_json_list(_FEEDBACK_PATH)}


def _users_signature(users):
    # changes whenever any user is edited -> invalidates the interview cache.
    return json.dumps(users, sort_keys=True)


def _client_for(mode):
    # demo -> scripted offline client; live -> None (engine builds the real one).
    if mode == "demo":
        return DemoClient()
    return None


class _CountingMessages:
    def __init__(self, inner, counter):
        self._inner = inner
        self._counter = counter

    async def create(self, **kwargs):
        model = kwargs.get("model", "?")
        self._counter["total"] += 1
        by_model = self._counter["by_model"]
        by_model[model] = by_model.get(model, 0) + 1
        return await self._inner.create(**kwargs)


class CountingClient:
    # wraps any client and tallies how many API calls a run made, by model,
    # so the UI can show a usage/cost meter.
    def __init__(self, inner):
        self.counter = {"total": 0, "by_model": {}}
        self.messages = _CountingMessages(inner.messages, self.counter)


def _counting_client(mode):
    # a real/demo client wrapped so the run reports its call usage.
    if mode == "demo":
        inner = DemoClient()
    else:
        inner = config.get_client()   # raises a clear error if no key (caught upstream)
    return CountingClient(inner)


def _find_user(uid):
    users = STATE["users"]
    i = 0
    while i < len(users):
        if users[i]["id"] == uid:
            return users[i]
        i += 1
    return None


@app.get("/")
async def index():
    return FileResponse(_INDEX)


@app.get("/api/users")
async def api_users():
    # the editable cast, plus the vocab the edit form needs.
    return {
        "users": STATE["users"],
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


def _apply_changes(user, changes):
    # copy only the editable, valid fields onto the user in place.
    editable = ["name", "age", "gender", "hobbies", "personality",
                "occupation", "availability", "location", "bio", "preferred_group_size"]
    keys = list(changes.keys())
    i = 0
    while i < len(keys):
        key = keys[i]
        if key in editable:
            user[key] = changes[key]
        i += 1


@app.post("/api/users/{uid}")
async def api_edit_user(uid: str, changes: dict):
    # update editable traits on one user (no AI -- direct edit).
    user = _find_user(uid)
    if user is None:
        return JSONResponse(status_code=404, content={"error": "no such user"})
    problem = _validate_changes(changes)
    if problem is not None:
        return JSONResponse(status_code=400, content={"error": problem})
    _apply_changes(user, changes)
    _save_cast()
    return user


@app.post("/api/users/{uid}/nudge")
async def api_nudge_user(uid: str, body: dict):
    # AI-assisted edit: "make them more X" rewrites the profile (live mode only).
    user = _find_user(uid)
    if user is None:
        return JSONResponse(status_code=404, content={"error": "no such user"})
    if body.get("mode", "demo") == "demo":
        return JSONResponse(status_code=400,
                            content={"error": "AI editing needs Live mode -- or edit the fields directly."})
    instruction = (body.get("instruction") or "").strip()
    if len(instruction) == 0:
        return JSONResponse(status_code=400, content={"error": "Say how to change them, e.g. 'make her more outgoing'."})
    try:
        changes = await nudge_user(user, instruction, client=_client_for(body.get("mode")))
    except Exception as error:
        return JSONResponse(status_code=500, content={"error": str(error)})
    problem = _validate_changes(changes)
    if problem is not None:
        return JSONResponse(status_code=400, content={"error": "AI produced an invalid change: " + problem})
    _apply_changes(user, changes)
    _save_cast()
    return user


@app.post("/api/reset")
async def api_reset():
    # restore the original 12 people and forget all edits.
    STATE["users"] = copy.deepcopy(USERS)
    STATE["interview_cache"] = None
    STATE["last_run"] = None
    try:
        if os.path.exists(_CAST_PATH):
            os.remove(_CAST_PATH)
    except Exception:
        pass
    return {"users": STATE["users"]}


@app.get("/api/feedback")
async def api_get_feedback():
    return {"feedback": STATE["feedback"]}


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
    STATE["feedback"].append(entry)
    _save_feedback()
    return {"feedback": STATE["feedback"]}


@app.post("/api/feedback/clear")
async def api_clear_feedback():
    STATE["feedback"] = []
    try:
        if os.path.exists(_FEEDBACK_PATH):
            os.remove(_FEEDBACK_PATH)
    except Exception:
        pass
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
    key = (body.get("key") or "").strip()
    if len(key) < 8:
        return JSONResponse(status_code=400, content={"error": "That doesn't look like an API key."})
    _persist_key(key)
    return {"configured": True}


@app.post("/api/run")
async def api_run(mode: str = "demo"):
    # run the full pipeline on the (possibly edited) cast; remember the result.
    # Reuse cached interviews when the cast + mode are unchanged (skips 12 calls).
    try:
        signature = _users_signature(STATE["users"])
        cache = STATE["interview_cache"]
        reuse = None
        if cache is not None and cache["signature"] == signature and cache["mode"] == mode:
            reuse = cache["interviews"]
        result = await run_pipeline(STATE["users"], client=_counting_client(mode),
                                    verbose=False, interviews=reuse, feedback=STATE["feedback"])
        STATE["interview_cache"] = {"signature": signature, "mode": mode,
                                    "interviews": result["interviews"]}
        STATE["last_run"] = result
        result["interviews_reused"] = reuse is not None
        return result
    except Exception as error:
        return JSONResponse(status_code=500, content={"error": str(error)})


@app.get("/api/run-stream")
async def api_run_stream(mode: str = "demo"):
    # same run, but streamed live (Server-Sent Events): each stage and each
    # negotiation step is pushed as it happens, so the UI fills in progressively.
    queue = asyncio.Queue()

    def on_stage(stage, data):
        queue.put_nowait({"stage": stage, "data": data})

    async def run():
        try:
            signature = _users_signature(STATE["users"])
            cache = STATE["interview_cache"]
            reuse = None
            if cache is not None and cache["signature"] == signature and cache["mode"] == mode:
                reuse = cache["interviews"]
            result = await run_pipeline(STATE["users"], client=_counting_client(mode),
                                        verbose=False, interviews=reuse, on_stage=on_stage,
                                        feedback=STATE["feedback"])
            STATE["interview_cache"] = {"signature": signature, "mode": mode,
                                        "interviews": result["interviews"]}
            STATE["last_run"] = result
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
async def api_generate_cast(body: dict):
    # re-roll the 12 people with real AI -- a fresh, random, diverse cast each
    # time (no theme). Uses the API -> live only.
    mode = body.get("mode", "demo")
    if mode == "demo":
        return JSONResponse(status_code=400,
                            content={"error": "Generating a fresh cast uses real AI -- switch to Live mode."})
    try:
        users = await generate_users(count=12, theme=DEFAULT_THEME, client=_client_for(mode))
    except Exception as error:
        return JSONResponse(status_code=500, content={"error": str(error)})
    # generation fans out one call per person; if too many failed (e.g. rate limits)
    # we get a short cast back. Don't wipe the current cast with a broken one.
    if len(users) < 3:
        return JSONResponse(status_code=502, content={
            "error": "Couldn't invent a full cast (the AI returned {} usable people). "
                     "Your current cast is unchanged -- try again in a moment.".format(len(users))})
    STATE["users"] = users
    STATE["interview_cache"] = None     # new people -> old interviews are stale
    STATE["last_run"] = None
    _save_cast()
    warning = None
    if len(users) < 12:
        warning = "Only {} of 12 people came back this time (some AI calls failed).".format(len(users))
    return {"users": users, "warning": warning}


@app.post("/api/chat")
async def api_chat(body: dict):
    # talk to one persona, in character. history = [{role, content}, ...].
    user = _find_user(body.get("user_id"))
    if user is None:
        return JSONResponse(status_code=404, content={"error": "no such user"})
    claw = Claw(user, client=_client_for(body.get("mode", "demo")))
    try:
        reply = await claw.chat(body.get("message", ""), body.get("history", []))
        return {"reply": reply}
    except Exception as error:
        return JSONResponse(status_code=500, content={"error": str(error)})


@app.post("/api/master-chat")
async def api_master_chat(body: dict):
    # ask the Master Claw why it decided what it did (about the last run).
    run_result = STATE["last_run"]
    if run_result is None:
        return {"reply": "Run the matchmaker first, then I can explain what I did and why."}
    mode = body.get("mode", "demo")
    if mode == "demo":
        # free, offline: a grounded summary built from the actual run (no AI).
        return {"reply": "In demo mode I can't chat freely, but here's the record of what I did:\n\n"
                + context_summary(run_result)}
    try:
        reply = await explain_decision(body.get("message", ""), run_result,
                                       body.get("history", []), client=None)
        return {"reply": reply}
    except Exception as error:
        return JSONResponse(status_code=500, content={"error": str(error)})


if __name__ == "__main__":
    import threading
    import webbrowser
    import uvicorn
    url = "http://127.0.0.1:8000"
    print("Clawnly is running at  " + url + "   (press Ctrl+C to stop)")
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=8000)
