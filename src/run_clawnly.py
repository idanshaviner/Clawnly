"""Run Clawnly at a real URL: the page at /run and the runs behind it.

The page is the same one published as a claude.ai Artifact (src/web/run-clawnly.*),
served here in server mode: anyone with the link can watch and replay the latest
run, and only a Clawnly admin can start one. A run is matchmaker.run_day with
the server's own key, in the background, saved to db.matchmaker_runs after
every step so the page can follow it live.

The neighborhood is emulated (population.py): no real person's data is in it.
"""

import asyncio
import datetime
import json
import os

import catalog
import config
import db
import matchmaker
import nightly
import population


DAYS_AHEAD = 7
# the page's choices; "all" still has a ceiling, since every group costs agent calls
GROUP_CHOICES = {"6": 6, "10": 10, "15": 15, "all": 40}
# a run that hasn't saved anything for this long died with the app (a restart)
STALE_SECONDS = 900

_HERE = os.path.dirname(os.path.abspath(__file__))
_WEB = os.path.join(_HERE, "web")

# the running task, held so it isn't garbage-collected mid-run
_TASKS = set()


def days():
    # tomorrow and the six days after it, in the neighborhood's time zone
    tomorrow = nightly.local_now().date() + datetime.timedelta(days=1)
    out = []
    i = 0
    while i < DAYS_AHEAD:
        out.append((tomorrow + datetime.timedelta(days=i)).isoformat())
        i += 1
    return out


def town(first_day):
    # the emulated neighbors, with calendars from first_day; the page and the run use the same one
    return population.generate(200, seed=7, start=datetime.date.fromisoformat(first_day), days=DAYS_AHEAD)


def _read(name):
    with open(os.path.join(_WEB, name), encoding="utf-8") as f:
        return f.read()


def _script_json(value):
    # JSON inside a <script> tag: "<" escaped so no value can close the tag
    return json.dumps(value).replace("<", "\\u003c")


def page_html(listed=None, server=True):
    # the Run Clawnly page. server=True is /run on this app; server=False is the standalone
    # claude.ai Artifact (matchmaker/run-clawnly.html), which runs in the owner's browser.
    if listed is None:
        listed = days()
    data = {"neighborhood": catalog.NEIGHBORHOOD, "people": town(listed[0]), "activities": catalog.ACTIVITIES,
            "days": listed, "groupMin": catalog.GROUP_MIN, "groupMax": catalog.GROUP_MAX}
    head = _read("run-clawnly-head.html")
    mode = ""
    if server:
        mode = "<script type=\"application/json\" id=\"mm-mode\">\"server\"</script>"
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">" +
            "<template id=\"mm-head\">" + head + "</template>" + head +
            "<style id=\"mm-css\">" + _read("run-clawnly.css") + "</style></head><body><div id=\"root\"></div>" +
            mode +
            "<script type=\"application/json\" id=\"mm-data\">" + _script_json(data) + "</script>" +
            "<script type=\"application/json\" id=\"mm-state\">{\"run\":null}</script>" +
            "<script id=\"mm-app\">" + _read("run-clawnly.js") + "</script></body></html>")


def write_artifact(path, first_day):
    # rebuild the standalone Artifact copy from the same sources as /run, with no saved run in it
    start = datetime.date.fromisoformat(first_day)
    listed = []
    i = 0
    while i < DAYS_AHEAD:
        listed.append((start + datetime.timedelta(days=i)).isoformat())
        i += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write(page_html(listed, server=False))


def check_request(day, max_groups):
    # (day, how many groups, None) or (None, None, the error)
    listed = days()
    if day not in listed:
        return None, None, "Pick one of the next " + str(DAYS_AHEAD) + " days."
    key = str(max_groups)
    if key not in GROUP_CHOICES:
        return None, None, "Groups to negotiate must be one of " + ", ".join(GROUP_CHOICES.keys()) + "."
    return day, GROUP_CHOICES[key], None


async def _run(run_id, day, how_many, first_day):
    def progress(data):
        db.save_matchmaker_run(run_id, data)

    try:
        data = await matchmaker.run_day(datetime.date.fromisoformat(day), how_many, town(first_day),
                                        config.get_client(), on_progress=progress)
    except Exception as error:
        # e.g. no API key: run_day never started, so the row says why
        data = {"day": day, "status": "failed", "groups": [], "calls": [],
                "log": [{"t": datetime.datetime.now(datetime.timezone.utc).isoformat(), "actor": "system",
                         "kind": "system", "text": "Run stopped: " + str(error)[:200], "group": None}]}
        db.save_matchmaker_run(run_id, data)
    db.log_event(None, "system", "system", "Run Clawnly #" + str(run_id) + " for " + day + " ended: " + data["status"] + ".")


def start(day, max_groups, by):
    # (run id, None) and the run goes on in the background, or (None, the error)
    day, how_many, error = check_request(day, max_groups)
    if error is not None:
        return None, error
    run_id = db.claim_matchmaker_run(day, by, STALE_SECONDS)
    if run_id is None:
        return None, "A run is already going; it's on the page now."
    db.log_event(None, "human", "human", by + " started Run Clawnly #" + str(run_id) + " for " + day +
                 " (up to " + str(how_many) + " groups).")
    task = asyncio.get_running_loop().create_task(_run(run_id, day, how_many, days()[0]))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return run_id, None


def latest():
    return db.latest_matchmaker_run()


if __name__ == "__main__":
    # .venv/bin/python src/run_clawnly.py matchmaker/run-clawnly.html 2026-09-27
    import sys
    write_artifact(sys.argv[1], sys.argv[2])
