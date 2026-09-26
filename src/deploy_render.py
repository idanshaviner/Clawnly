"""Deploy Clawnly to Render and prove it works, in one command.

  .venv/bin/python src/deploy_render.py --admin you@example.com [--first-run] [--free]

Reads RENDER_API_KEY (to talk to Render) and ANTHROPIC_API_KEY (handed to the
service; the server's own key) from the environment. Optional RESEND_API_KEY,
GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are passed on when present. Secret
values are never printed.

What it does, safe to re-run:
  1. finds the Render service by name, or creates it from the public repo
     (Python web service, starter plan, a 1 GB disk at /var/data for SQLite)
  2. sets the env vars, including CLAWNLY_BASE_URL = the service's own address
  3. deploys the branch and waits until it's live, then checks /run answers
  4. with --first-run: signs in as the admin (the sign-in link comes from the
     service's log when email isn't set up), starts a small Run Clawnly day and
     waits for it to finish -- a real run on the real models
"""

import argparse
import os
import sys
import time

import httpx


API = "https://api.render.com/v1"
REPO = "https://github.com/idanshaviner/Clawnly"
SERVICE_NAME = "clawnly-pilot"
BUILD = "pip install -r requirements.txt"
START = "uvicorn app:app --host 0.0.0.0 --port $PORT --app-dir src"
PASSED_ON = ["ANTHROPIC_API_KEY", "RESEND_API_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]
DONE_STATES = ["live", "build_failed", "update_failed", "canceled", "deactivated", "pre_deploy_failed"]


def say(line):
    print(line, flush=True)


def env_vars(admin, base_url, environ, free=False):
    # [{"key", "value"}] for the service; secrets only from the environment
    out = [{"key": "PYTHON_VERSION", "value": "3.12.6"},
           {"key": "CLAWNLY_ADMIN_EMAILS", "value": admin}]
    if not free:
        # the free plan has no disk, so the database stays in the container
        out.append({"key": "CLAWNLY_DB_PATH", "value": "/var/data/clawnly.db"})
    if base_url:
        out.append({"key": "CLAWNLY_BASE_URL", "value": base_url})
    i = 0
    while i < len(PASSED_ON):
        value = environ.get(PASSED_ON[i])
        if value:
            out.append({"key": PASSED_ON[i], "value": value})
        i += 1
    return out


def create_body(owner_id, branch, admin, environ, free=False):
    details = {"runtime": "python", "plan": "starter", "region": "oregon", "healthCheckPath": "/",
               "disk": {"name": "clawnly-pilot-data", "mountPath": "/var/data", "sizeGB": 1},
               "envSpecificDetails": {"buildCommand": BUILD, "startCommand": START}}
    if free:
        # free: no card, but no disk (saved runs vanish on a restart) and it sleeps when idle
        details["plan"] = "free"
        del details["disk"]
    return {"type": "web_service", "name": SERVICE_NAME, "ownerId": owner_id, "repo": REPO,
            "branch": branch, "autoDeploy": "yes", "envVars": env_vars(admin, None, environ, free),
            "serviceDetails": details}


def _check(res, what):
    if res.status_code >= 300:
        # Render's error text never carries our secrets; it's safe to show
        raise SystemExit(what + " failed: HTTP " + str(res.status_code) + " " + res.text[:400])
    return res.json()


def find_service(render):
    listed = _check(render.get("/services", params={"name": SERVICE_NAME, "limit": 20}), "Listing services")
    i = 0
    while i < len(listed):
        service = listed[i].get("service", listed[i])
        if service.get("name") == SERVICE_NAME:
            return service
        i += 1
    return None


def owner_id(render):
    owners = _check(render.get("/owners", params={"limit": 20}), "Listing workspaces")
    if len(owners) == 0:
        raise SystemExit("This Render key sees no workspace.")
    return owners[0].get("owner", owners[0])["id"]


def wait_for_deploy(render, service_id, deploy_id, minutes):
    deadline = time.monotonic() + minutes * 60
    status = "?"
    while time.monotonic() < deadline:
        deploy = _check(render.get("/services/" + service_id + "/deploys/" + deploy_id), "Reading the deploy")
        status = deploy.get("status", "?")
        if status in DONE_STATES:
            return status
        say("  deploy: " + status)
        time.sleep(15)
    return "timed out (" + status + ")"


def set_env(render, service_id, variables):
    # one key at a time, so anything set by hand in Render's dashboard stays
    i = 0
    while i < len(variables):
        path = "/services/" + service_id + "/env-vars/" + variables[i]["key"]
        _check(render.put(path, json={"value": variables[i]["value"]}), "Setting " + variables[i]["key"])
        i += 1


def magic_link_from_logs(render, owner, service_id, since):
    params = {"ownerId": owner, "resource": service_id, "text": "Magic link for", "startTime": since,
              "limit": 20, "direction": "backward"}
    body = _check(render.get("/logs", params=params), "Reading the service log")
    logs = body.get("logs", [])
    i = 0
    while i < len(logs):
        text = logs[i].get("message", "")
        at = text.find("/auth/magic-link/verify?token=")
        if at != -1:
            start = text.rfind("http", 0, at)
            return text[start:].split()[0]
        i += 1
    return None


def first_run(render, owner, service_id, base_url, admin):
    site = httpx.Client(base_url=base_url, timeout=60.0, follow_redirects=False)
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 5))
    _check(site.post("/api/auth/magic-link/request", json={"email": admin}), "Asking for a sign-in link")
    link = None
    tries = 0
    while link is None and tries < 12:
        time.sleep(5)
        link = magic_link_from_logs(render, owner, service_id, since)
        tries += 1
    if link is None:
        raise SystemExit("No sign-in link in the log (with RESEND_API_KEY set it goes by email instead).")
    signed_in = site.get(link[link.index("/auth/"):])
    if signed_in.status_code not in (302, 303):
        raise SystemExit("Signing in failed: HTTP " + str(signed_in.status_code))
    say("Signed in as the admin.")
    day = site.get("/run").text.split('"days": ["')[1].split('"')[0]
    started = _check(site.post("/api/run", json={"day": day, "max_groups": "6"}), "Starting a run")
    say("Run Clawnly #" + str(started["run_id"]) + " started for " + day + " (up to 6 groups).")
    deadline = time.monotonic() + 30 * 60
    last = ""
    while time.monotonic() < deadline:
        latest = _check(site.get("/api/run/latest"), "Reading the run")["run"]
        log = latest["data"].get("log", [])
        if len(log) > 0 and log[-1]["text"] != last:
            last = log[-1]["text"]
            say("  " + last[:160])
        if latest["status"] != "running":
            return latest
        time.sleep(10)
    raise SystemExit("The run didn't finish in 30 minutes.")


def main():
    parser = argparse.ArgumentParser(description="Deploy Clawnly to Render.")
    parser.add_argument("--admin", required=True, help="the admin email(s), comma-separated")
    parser.add_argument("--branch", default="clawnly-lounge")
    parser.add_argument("--first-run", action="store_true", help="sign in and run one real day")
    parser.add_argument("--free", action="store_true", help="Render's free plan: no disk, sleeps when idle")
    args = parser.parse_args()
    key = os.environ.get("RENDER_API_KEY")
    if not key:
        raise SystemExit("Set RENDER_API_KEY first.")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY first (the service's own key).")
    render = httpx.Client(base_url=API, timeout=60.0,
                          headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
    owner = owner_id(render)
    service = find_service(render)
    if service is None:
        say("Creating " + SERVICE_NAME + " from " + REPO + " (" + args.branch + ")...")
        created = _check(render.post("/services", json=create_body(owner, args.branch, args.admin, os.environ, args.free)),
                         "Creating the service")
        service = created.get("service", created)
    else:
        say("Found " + SERVICE_NAME + " (" + service["id"] + ").")
    base_url = service.get("serviceDetails", {}).get("url")
    if not base_url:
        base_url = "https://" + SERVICE_NAME + ".onrender.com"
    set_env(render, service["id"], env_vars(args.admin, base_url, os.environ, args.free))
    say("Env vars set (values not shown). Deploying...")
    deploy = _check(render.post("/services/" + service["id"] + "/deploys", json={"clearCache": "do_not_clear"}),
                    "Starting a deploy")
    status = wait_for_deploy(render, service["id"], deploy["id"], 20)
    if status != "live":
        raise SystemExit("Deploy ended " + status + ". Render's dashboard has the build log.")
    page = httpx.get(base_url + "/run", timeout=60.0)
    say("Live: " + base_url + "/run (HTTP " + str(page.status_code) + ")")
    if page.status_code != 200:
        sys.exit(1)
    if args.first_run:
        latest = first_run(render, owner, service["id"], base_url, args.admin)
        locked = 0
        people = 0
        groups = latest["data"].get("groups", [])
        g = 0
        while g < len(groups):
            if groups[g].get("status") == "locked":
                locked += 1
                people += len(groups[g].get("final", []))
            g += 1
        say("Run " + latest["status"] + ": " + str(locked) + " groups locked, " + str(people) +
            " neighbors with a plan. Watch it: " + base_url + "/run")


if __name__ == "__main__":
    main()
