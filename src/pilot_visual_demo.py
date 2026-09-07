"""Free, offline demo of the real pilot flow -- but through the actual
browser UI, not a terminal transcript.

pilot_demo.py proves the DECISION-MAKING is correct (matching, grounding,
the reveal-gate state machine) by printing to a terminal. It never touches
a single web page. This module answers a different question -- "what does
a real resident actually SEE and click through?" -- by running the real,
unmodified app.py server (real routes, real HTML/CSS/JS, real database) and
driving it with an actual browser. Only the AI's replies are scripted (via
the same client-injection point every other module uses), so this is still
zero cost and zero real API calls -- but everything else is production code.

Requires Playwright, which is NOT a project dependency (this is the only
module that needs it, and it pulls down a browser binary -- not worth
imposing on everyone who just wants to run the app or the test suite):
    pip install playwright
    playwright install chromium

Run:  python src/pilot_visual_demo.py
Output: a screen recording (.webm) and three screenshots (pending / waiting
/ sealed) under pilot_visual_demo_output/ at the project root (gitignored).
"""

import json
import os
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_OUT_DIR = os.path.join(_ROOT, "pilot_visual_demo_output")
_DB_PATH = os.path.join(_ROOT, "clawnly_pilot_visual_demo.db")
_PORT = 8010

# db.py reads CLAWNLY_DB_PATH at import time -- must be set before `import
# db` (directly, or transitively through `app`), same technique dryrun.py
# and pilot_demo.py use to isolate the test database.
os.environ.setdefault("CLAWNLY_DB_PATH", _DB_PATH)
os.environ.setdefault("CLAWNLY_ADMIN_EMAILS", "admin@example.com")

sys.path.insert(0, _HERE)

import config  # noqa: E402


def _body(obj):
    return json.dumps(obj)


class _TextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, text):
        self.content = [_TextBlock(text)]


class VisualDemoClient:
    """Scripted stand-in for AsyncAnthropic, tuned to the pilot's own
    prompts -- routes by the same distinctive system-prompt markers
    tests/conftest.py's FakeClient uses. Unlike that fixture, this answers
    WHATEVER a live browser session actually sends, since a real click-
    through isn't a fixed, replayable sequence of calls."""

    def __init__(self):
        self.onboarding_turns = 0
        self.match_ids = None   # set once every resident's id is known

    def set_match_ids(self, my_id, neighbor_ids):
        ids = [my_id]
        i = 0
        while i < len(neighbor_ids):
            ids.append(neighbor_ids[i])
            i += 1
        self.match_ids = ids

    async def _create(self, **kwargs):
        messages = kwargs.get("messages", [])
        system = kwargs.get("system", "")
        low = system.lower()
        content = messages[-1]["content"]

        if "actual human on the other end" in low:
            self.onboarding_turns += 1
            if self.onboarding_turns == 1:
                return _Response(
                    "That's great to hear! What kind of things do you like doing on your days "
                    "off, and when are you usually free to meet up with people?")
            return _Response(
                "Got it, thanks for sharing all that! I've got a good sense of you now -- I'll "
                "let you know once I've found a group that's a real fit.")

        if "personality_energy" in low:
            complete = self.onboarding_turns >= 2
            slots = {"personality_energy": True, "interests": complete, "availability": complete,
                     "group_size": complete, "seeking": complete}
            fields = {
                "name": "Jordan Ellis", "age": 30, "gender": "woman", "personality": "mixed",
                "occupation": "working professional",
                "bio": "Just settling into the neighborhood and looking to meet people nearby.",
                "location": "Ten Trails - The Ridge", "hobbies": ["hiking", "board games"],
                "availability": ["weekend_daytime", "weekday_evening"],
                "preferred_group_size": "no preference",
            }
            return _Response(_body({"slots": slots, "fields": fields}))

        if "form one meetup" in low:
            ids = []
            i = 0
            while i < len(self.match_ids):
                ids.append("r" + str(self.match_ids[i]))
                i += 1
            return _Response(_body({
                "group": ids,
                "reason": ("Jordan, Sam and Priya all keep weekend daytimes free and share a "
                           "genuine hiking interest -- a small, easy-going trio to start with."),
                "scores": {"personality": 4, "availability": 5, "interests": 5, "size_fit": 4},
                "why_not": [],
            }))

        if "joint activity" in low:
            return _Response(_body({
                "activity": "a morning hike on the neighborhood trails",
                "pitch": "You're all early risers who love the outdoors -- let's hit the trails together.",
            }))

        if "on board" in low:
            return _Response(_body({
                "members": [{"name": "Jordan Ellis", "on_board": True, "note": ""},
                            {"name": "Sam Rivera", "on_board": True, "note": ""},
                            {"name": "Priya Nair", "on_board": True, "note": ""}],
                "agreed": True, "concern": "",
            }))

        if "embody this character" in low:
            if "Separate your two answers" in content:
                return _Response("I'd love to meet people around hiking and board games.\n===\n"
                                  "I'm usually free weekend days, and I bring mixed energy to a group.")
            if "React as yourself" in content:
                return _Response("That sounds great -- count me in!")
            return _Response("Sounds good to me.")

        # popup (venue) -- the catch-all, matching the FakeClient convention.
        return _Response(_body({"options": [
            {"event_name": "Ten Trails Trailhead Hike", "activity": "a morning hike",
             "location": "the Ten Trails trailhead off Lawson St, Black Diamond",
             "time": "Saturday morning around 9am",
             "reason": "A trailhead hike puts your shared love of the outdoors front and center, right on your own trails."},
        ]}))


class _Messages:
    def __init__(self, client):
        self.client = client

    async def create(self, **kwargs):
        return await self.client._create(**kwargs)


def _seed_neighbor(db, neighborhood_id, email, fields):
    resident = db.get_or_create_resident(neighborhood_id, email, "magic_link")
    db.record_consent(resident["id"])
    full_fields = dict(fields)
    full_fields["slots_status"] = {"personality_energy": True, "interests": True,
                                    "availability": True, "group_size": True, "seeking": True}
    db.update_resident_profile(resident["id"], full_fields)
    db.mark_profile_complete(resident["id"])
    return resident


def _run_server(app_module):
    import uvicorn
    uvicorn.run(app_module.app, host="127.0.0.1", port=_PORT, log_level="warning")


def main():
    if os.path.exists(_DB_PATH):
        os.remove(_DB_PATH)
    os.makedirs(_OUT_DIR, exist_ok=True)

    client = VisualDemoClient()
    client.messages = _Messages(client)
    config.get_client = lambda: client

    import auth
    magic_links = {}

    async def fake_send_magic_link_email(email, link_url):
        magic_links[email] = link_url

    auth._send_magic_link_email = fake_send_magic_link_email

    import db
    import app as app_module

    db.init_db()
    # batch_threshold=3: the matcher's own partition loop needs at least 3
    # people in a pool before it will attempt a group at all, regardless of
    # anyone's individual size preference -- a 2-person pool never matches.
    neighborhood = db.get_or_create_neighborhood("ten-trails", "Ten Trails", 3)

    # two neighbors, already onboarded -- so the browser-driven resident
    # below is the THIRD completion, which fires the real batch trigger.
    neighbor_sam = _seed_neighbor(db, neighborhood["id"], "sam@example.com", {
        "name": "Sam Rivera", "age": 32, "gender": "man", "personality": "extroverted",
        "occupation": "working professional", "hobbies": ["hiking", "trail running"],
        "availability": ["weekend_daytime"], "location": "Ten Trails - Foothills",
        "bio": "Been here a year, loves the trails.", "preferred_group_size": "no preference",
    })
    neighbor_priya = _seed_neighbor(db, neighborhood["id"], "priya@example.com", {
        "name": "Priya Nair", "age": 29, "gender": "woman", "personality": "extroverted",
        "occupation": "working professional", "hobbies": ["hiking", "board games"],
        "availability": ["weekend_daytime"], "location": "Ten Trails - The Ridge",
        "bio": "New to the neighborhood, eager to meet active neighbors.",
        "preferred_group_size": [3, 5],
    })
    print("Seeded background neighbors: Sam (id={}), Priya (id={})".format(
        neighbor_sam["id"], neighbor_priya["id"]))

    thread = threading.Thread(target=_run_server, args=(app_module,), daemon=True)
    thread.start()
    time.sleep(2)
    base_url = "http://127.0.0.1:{}".format(_PORT)
    print("Server up on " + base_url)

    from playwright.sync_api import sync_playwright

    def wait_for_magic_link(email, timeout_seconds=6):
        waited = 0.0
        while email not in magic_links and waited < timeout_seconds:
            time.sleep(0.3)
            waited += 0.3
        return magic_links.get(email)

    with sync_playwright() as p:
        # --no-sandbox: needed in most containerized/CI environments (this
        # tool has no elevated privileges to give up), harmless elsewhere.
        # CLAWNLY_CHROMIUM_PATH lets a specific pre-installed browser binary
        # be pointed at directly (some sandboxes pre-provision one under a
        # path Playwright's own version resolution doesn't expect); leave
        # unset for the normal `playwright install chromium` setup.
        chromium_path = os.environ.get("CLAWNLY_CHROMIUM_PATH")
        if chromium_path:
            browser = p.chromium.launch(executable_path=chromium_path, args=["--no-sandbox"])
        else:
            browser = p.chromium.launch(args=["--no-sandbox"])
        context = browser.new_context(
            viewport={"width": 480, "height": 820},
            record_video_dir=_OUT_DIR,
            record_video_size={"width": 480, "height": 820},
        )
        page = context.new_page()
        # keep the recording fast and deterministic regardless of the local
        # network -- these are decorative webfont/telemetry requests only,
        # every page already declares a system-font fallback.
        page.route("**://fonts.googleapis.com/**", lambda route: route.abort())
        page.route("**://fonts.gstatic.com/**", lambda route: route.abort())
        page.route("**://accounts.google.com/**", lambda route: route.abort())

        page.goto(base_url + "/join/ten-trails")
        page.wait_for_timeout(1200)
        page.locator("input[type=checkbox]").check()
        page.wait_for_timeout(400)
        page.locator("#email-input").fill("jordan@example.com")
        page.wait_for_timeout(400)
        page.locator("#email-btn").click()

        link = wait_for_magic_link("jordan@example.com")
        print("Magic link: " + str(link))
        page.goto(link)
        page.wait_for_timeout(1500)

        if "/consent" in page.url:
            page.wait_for_timeout(800)
            page.locator("#agree-btn").click()
            waited = 0.0
            while "/onboarding" not in page.url and waited < 10:
                time.sleep(0.4)
                waited += 0.4
        page.wait_for_timeout(1000)

        row = db._get_conn().execute(
            "SELECT id FROM residents WHERE neighborhood_id=? AND email=?",
            (neighborhood["id"], "jordan@example.com")).fetchone()
        my_resident_id = row["id"]
        client.set_match_ids(my_resident_id, [neighbor_sam["id"], neighbor_priya["id"]])
        print("My resident id: {}, neighbor ids: {}, {}".format(
            my_resident_id, neighbor_sam["id"], neighbor_priya["id"]))

        page.locator("textarea, input[type=text]").first.fill(
            "Hi! I'm Jordan, just moved into Ten Trails. Excited to meet some neighbors.")
        page.get_by_role("button", name="Send").click()
        page.wait_for_timeout(3500)

        page.locator("textarea, input[type=text]").first.fill(
            "I love hiking and board games, usually free weekend mornings and some weeknights. "
            "I'd love to meet 2 or 3 people, and I'm just hoping to make some real friends nearby.")
        page.get_by_role("button", name="Send").click()
        page.wait_for_timeout(4500)

        page.goto(base_url + "/my-match")
        page.wait_for_timeout(2500)
        page.screenshot(path=os.path.join(_OUT_DIR, "1_pending.png"))
        print("State: pending -- " + page.inner_text("body")[:200])

        accept_btn = page.get_by_role("button", name="Yes, I'm in")
        if accept_btn.count() > 0:
            accept_btn.first.click()
            page.wait_for_timeout(1500)
        page.screenshot(path=os.path.join(_OUT_DIR, "2_waiting.png"))
        print("State: waiting -- " + page.inner_text("body")[:200])

        # the other two neighbors accept too (background, not in the
        # browser) -- via the same real my_match module their own browser
        # session would call through the API.
        import my_match
        neighbor_ids = [neighbor_sam["id"], neighbor_priya["id"]]
        i = 0
        while i < len(neighbor_ids):
            neighbor_row = db.get_resident(neighbor_ids[i])
            state = my_match.get_state(neighbor_row)
            if state["state"] == "pending":
                my_match.respond(neighbor_row, state["match_id"], "accept")
            i += 1

        page.reload()
        page.wait_for_timeout(2500)
        page.screenshot(path=os.path.join(_OUT_DIR, "3_sealed.png"), full_page=True)
        print("State: sealed -- " + page.inner_text("body")[:400])
        page.wait_for_timeout(1000)

        video_path = page.video.path()
        context.close()
        browser.close()

    print("\nSaved to " + _OUT_DIR + ":")
    print("  1_pending.png, 2_waiting.png, 3_sealed.png")
    print("  " + os.path.basename(video_path) + " (screen recording)")


if __name__ == "__main__":
    main()
