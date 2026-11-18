"""The judge: a second model scores each group from a finished Run Clawnly day.

Start simple (Eitan, Nov 17): no synthetic data and no "what good looks like" set
first -- the judge just reads what happened and scores it. Later its scores get
checked against the team's Keep / Change marks (HITL), and the daily review can
pick the groups the judge scored lowest.

For one group of a run in db.matchmaker_runs, the judge reads the whole record:

  - the event: what, where, cost, the time it was planned for, what some avoid about it
  - why the matchmaker picked this group, and its thinking about the day
  - every person asked and every alternate, with the full profile their agent had
  - every message, in order: the matchmaker's ask, each agent's yes / no / counter
    with its reason, and every code check (a refused yes, an agent that didn't answer)
  - the resolve step's thinking, the group's log lines, and the outcome
  - the team's skill file (src/matchmaker_skill.md), so it judges by our rules

and answers with a score from 1 to 10 and a one-line reason quoting the record for
each of: main-thing fit, stage of life, event fit (time / cost / place), negotiation
quality and would-meet-again likelihood, plus an overall score and a list of flags.

Every call goes through ai_log.LoggedClient (db.ai_calls), every score is saved in
db.judge_scores, and each judged run writes one line to db.events.

    .venv/bin/python src/judge.py --run latest [--model MODEL] [--effort low|medium|high]
    .venv/bin/python src/judge.py --run 12
    .venv/bin/python src/judge.py --list
"""

import asyncio
import datetime
import json
import sys

import ai_log
import catalog
import config
import db
import matchmaker
import nightly
import run_clawnly
from llm_io import extract_json, join_text


# the five things the team cares about in a group, in the order the judge answers them
CRITERIA = [
    ["main_thing", "Main-thing fit"],
    ["stage_of_life", "Stage of life"],
    ["event_fit", "Event fit (time, cost, place)"],
    ["negotiation", "Negotiation quality"],
    ["meet_again", "Would meet again"],
]
# a judge reply is short (six reasons and a few flags); a cap leaves room for its thinking
JUDGE_MAX_TOKENS = 6000
# how many groups are judged at once
JUDGE_CONCURRENCY = 4

# the judging task, held so it isn't garbage-collected mid-run (admin button)
_TASKS = set()
_JUDGING = set()


# ----- the record the judge reads ---------------------------------------------------

def town_start(run):
    # the first day of the town the run used: saved in the run since the judge was added;
    # for older runs, the day after the run was started (in the neighborhood's time zone),
    # which is what run_clawnly.start used
    data = run["data"]
    if data.get("townStart"):
        return data["townStart"]
    created = datetime.datetime.fromisoformat(run["created_at"])
    if created.tzinfo is None:
        created = created.replace(tzinfo=datetime.timezone.utc)
    local = created.astimezone(nightly.timezone()).date()
    return (local + datetime.timedelta(days=1)).isoformat()


def people_for(run):
    # the emulated neighbors the run planned for, by id (the same seed gives the same town)
    people = run_clawnly.town(town_start(run))
    out = {}
    i = 0
    while i < len(people):
        out[people[i]["id"]] = people[i]
        i += 1
    return out


def _name(people, person_id):
    if person_id in people:
        return people[person_id]["name"]
    return person_id


def _person_block(people, member, label):
    # one person: who they are to the run, then the full profile their agent had
    pid = member["id"]
    lines = ["- " + pid + " " + _name(people, pid) + " (" + label + ")"]
    if member.get("state"):
        lines[0] += ", last answer: " + str(member["state"])
    if member.get("refused"):
        lines.append("  code refused their yes: " + str(member["refused"]))
    if member.get("proposal"):
        lines.append("  the matchmaker's first message to their agent: " + str(member["proposal"]))
    if pid in people:
        profile = matchmaker.agent_profile(people[pid])
        parts = profile.split("\n")
        i = 0
        while i < len(parts):
            lines.append("  " + parts[i])
            i += 1
    else:
        lines.append("  (profile not found in the emulated town)")
    return lines


def _thread_line(people, number, message):
    # one numbered message, so the judge can quote it
    who = message.get("from")
    round_text = " (round " + str(message.get("round", "?")) + ")"
    if who == "hub":
        return "[" + str(number) + "] matchmaker -> " + _name(people, message.get("to")) + "'s agent" + round_text + ": " + str(message.get("text", ""))
    if who == "agent":
        line = "[" + str(number) + "] " + _name(people, message.get("by")) + "'s agent -> matchmaker" + round_text + ": " + str(message.get("answer", "")).upper()
        if message.get("reason"):
            line += " | reason: " + str(message["reason"])
        if message.get("counter"):
            line += " | counter: " + str(message["counter"])
        if message.get("text"):
            line += " | says: " + str(message["text"])
        return line
    return "[" + str(number) + "] code" + round_text + ": " + str(message.get("text", ""))


def group_record(run, group, people):
    # the whole story of one group, as plain text
    data = run["data"]
    activity = catalog.get(group["activity"])
    day = datetime.date.fromisoformat(data["day"])
    lines = ["RUN #" + str(run["id"]) + ", " + matchmaker.day_label(day) + ", group " + group["id"], "", "THE EVENT:"]
    if activity is None:
        lines.append("  " + str(group["activity"]) + " (not in the catalog)")
    else:
        lines.append("  " + activity["name"] + " at " + activity["where"] + ", " + catalog.NEIGHBORHOOD)
        lines.append("  cost: " + activity["cost"] + "; outdoor: " + str(activity["outdoor"]).lower())
        lines.append("  serves: " + ", ".join(activity["tags"]))
        if len(activity["traits"]) > 0:
            lines.append("  what some people avoid about it: " + ", ".join(activity["traits"]))
    when = "  when: " + str(group.get("part")) + ", " + str(group.get("time"))
    if group.get("fixed"):
        when += " (a real event at a fixed time)"
    if group.get("plannedTime"):
        when += " (the matchmaker first wrote " + str(group["plannedTime"]) + "; code moved it)"
    lines.append(when)
    lines.append("")
    lines.append("WHY THE MATCHMAKER PICKED THIS GROUP: " + str(group.get("why") or "(none given)"))
    plan = data.get("plan")
    if isinstance(plan, dict) and plan.get("thoughts"):
        lines.append("ITS THINKING ABOUT THE WHOLE DAY: " + str(plan["thoughts"]))
    lines.append("")
    lines.append("PEOPLE ASKED:")
    members = group.get("members") or []
    i = 0
    while i < len(members):
        lines += _person_block(people, members[i], "asked")
        i += 1
    lines.append("")
    lines.append("ALTERNATES (backups):")
    alternates = group.get("alternates") or []
    asked = []
    i = 0
    while i < len(members):
        asked.append(members[i]["id"])
        i += 1
    if len(alternates) == 0:
        lines.append("  none")
    i = 0
    while i < len(alternates):
        label = "alternate, never asked"
        if alternates[i] in asked:
            label = "alternate, asked later (see above)"
        lines += _person_block(people, {"id": alternates[i]}, label)
        i += 1
    lines.append("")
    lines.append("THE NEGOTIATION, IN ORDER:")
    thread = group.get("thread") or []
    if len(thread) == 0:
        lines.append("  no messages")
    i = 0
    while i < len(thread):
        lines.append(_thread_line(people, i + 1, thread[i]))
        i += 1
    resolve = data.get("resolve")
    if isinstance(resolve, dict) and isinstance(resolve.get("rounds"), list):
        rounds = resolve["rounds"]
        i = 0
        while i < len(rounds):
            if rounds[i].get("thoughts"):
                lines.append("RESOLVE STEP, round " + str(rounds[i].get("round")) + " (whole day): " + str(rounds[i]["thoughts"]))
            i += 1
    lines.append("")
    lines.append("LOG LINES FOR THIS GROUP:")
    log = data.get("log") or []
    i = 0
    while i < len(log):
        if log[i].get("group") == group["id"]:
            lines.append("  " + str(log[i].get("actor")) + ": " + str(log[i].get("text")))
        i += 1
    lines.append("")
    lines.append("OUTCOME:")
    status = str(group.get("status"))
    if status == "locked":
        names = []
        final = group.get("final") or []
        i = 0
        while i < len(final):
            names.append(_name(people, final[i]))
            i += 1
        lines.append("  locked: " + ", ".join(names) + " meet at " + str(group.get("time")))
    elif status == "dropped":
        lines.append("  dropped: " + str(group.get("dropReason") or "no reason logged"))
    else:
        lines.append("  " + status)
    magic = group.get("magic")
    if isinstance(magic, dict):
        lines.append("  headline sent: " + str(magic.get("headline") or ""))
        messages = magic.get("messages") or {}
        keys = sorted(messages.keys())
        i = 0
        while i < len(keys):
            lines.append("  message to " + _name(people, keys[i]) + ": " + str(messages[keys[i]]))
            i += 1
    return "\n".join(lines)


# ----- asking the judge -------------------------------------------------------------

def judge_system(skill_text):
    keys = []
    i = 0
    while i < len(CRITERIA):
        keys.append('"' + CRITERIA[i][0] + '": {"score": 1-10, "reason": "one line"}')
        i += 1
    return "\n".join([
        "You are the judge for Clawnly. Task: judge one planned activity group from a finished day of the matchmaker, using only the record below.",
        "Clawnly plans small activity groups (2-5 people) for neighbors. A matchmaker model picks each group from people who are free and keen, with alternates, then asks each person's agent one to one; an agent says yes, no or counter; code enforces the hard rules and locks a group once at least 2 said yes. The people are emulated neighbors, not real ones.",
        "Score each of these from 1 (bad) to 10 (excellent), each with ONE line that quotes or cites the record (a profile line or a message number like [3]):",
        "- main_thing: does the group share the main thing the activity is about, rather than a side thing (someone who loves coffee is not a match for a hike that ends at a cafe)?",
        "- stage_of_life: would these people feel like peers (age, kids at home, life stage), as the skill file describes? Use judgment, not an age rule.",
        "- event_fit: does the event itself fit each person: the time against their calendar and what they avoid, the cost against their budget, the place?",
        "- negotiation: did the matchmaker ask well and repair well: honest, personal messages, counters handled, no's replaced sensibly, no one pushed past a stated limit?",
        "- meet_again: how likely is it that this group enjoys it and wants to meet again?",
        "For a dropped group, judge what was attempted and how the negotiation went; score meet_again for the group the matchmaker proposed.",
        "overall: your overall score for this group, 1-10, with one line. flags: short labels for anything the team should look at (e.g. \"side-thing match\", \"over budget\", \"agent ignored an avoid\", \"pushy message\", \"repair missed an alternate\"); an empty list when nothing stands out.",
        "Be strict and specific. Never invent facts that are not in the record.",
        "",
        "THE TEAM'S SKILL FILE (the rules and examples the matchmaker was given; judge by them):",
        skill_text,
        "",
        "Reply with only this JSON object: {" + ", ".join(keys) + ', "overall": {"score": 1-10, "reason": "one line"}, "flags": ["short label"]}',
    ])


def _score(value):
    # an integer 1-10, or None when the judge didn't give one
    if isinstance(value, bool):
        return None
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    if number < 1:
        return 1
    if number > 10:
        return 10
    return number


def parse_verdict(raw):
    # (verdict, None) or (None, what was wrong). verdict: {criterion: {score, reason}, overall, flags}
    if not isinstance(raw, dict):
        return None, "the judge's reply was not a JSON object"
    verdict = {}
    total = 0
    i = 0
    while i < len(CRITERIA):
        key = CRITERIA[i][0]
        item = raw.get(key)
        if not isinstance(item, dict):
            return None, "no " + key + " in the judge's reply"
        score = _score(item.get("score"))
        if score is None:
            return None, "no score for " + key + " in the judge's reply"
        verdict[key] = {"score": score, "reason": str(item.get("reason") or "").strip()}
        total += score
        i += 1
    overall = raw.get("overall")
    score = None
    reason = ""
    if isinstance(overall, dict):
        score = _score(overall.get("score"))
        reason = str(overall.get("reason") or "").strip()
    if score is None:
        # no overall from the judge: the plain average, said so
        score = int(round(total / len(CRITERIA)))
        reason = "average of the five scores (the judge gave no overall)"
    verdict["overall"] = {"score": score, "reason": reason}
    flags = []
    listed = raw.get("flags")
    if isinstance(listed, list):
        i = 0
        while i < len(listed):
            text = str(listed[i]).strip()
            if len(text) > 0:
                flags.append(text)
            i += 1
    verdict["flags"] = flags
    return verdict, None


async def judge_group(client, run, group, people, skill_text, model, effort):
    # one judge call for one group, saved to db.judge_scores; returns the saved result
    record = group_record(run, group, people)
    verdict = None
    error = None
    try:
        message = await client.messages.create(
            model=model, max_tokens=JUDGE_MAX_TOKENS, system=judge_system(skill_text),
            output_config={"effort": effort},
            messages=[{"role": "user", "content": record}],
        )
        verdict, error = parse_verdict(extract_json(join_text(message)))
    except Exception as failure:
        error = "the judge call failed: " + str(failure)[:200]
    overall = None
    if verdict is not None:
        overall = verdict["overall"]["score"]
    db.save_judge_score(run["id"], group["id"], model, overall, verdict, error)
    return {"group_id": group["id"], "activity": group.get("activity"), "status": group.get("status"),
            "overall": overall, "verdict": verdict, "error": error}


def find_run(which):
    # "latest", None or a run id -> the run, or None
    if which is None or str(which) == "latest":
        return db.latest_matchmaker_run()
    try:
        run_id = int(which)
    except (TypeError, ValueError):
        return None
    return db.get_matchmaker_run(run_id)


async def judge_run(which, client, model=None, effort=None):
    # judge every group of one run; returns {run_id, day, model, results}
    run = find_run(which)
    if run is None:
        raise ValueError("No Run Clawnly run " + str(which) + ".")
    if run["status"] == "running":
        raise ValueError("Run #" + str(run["id"]) + " is still going; judge it when it's done.")
    if model is None:
        model = config.judge_model()
    if effort is None:
        effort = config.JUDGE_EFFORT
    groups = run["data"].get("groups") or []
    people = people_for(run)
    skill_text = matchmaker.skill()
    logged = ai_log.LoggedClient(client)
    gate = asyncio.Semaphore(JUDGE_CONCURRENCY)

    async def one(group):
        async with gate:
            return await judge_group(logged, run, group, people, skill_text, model, effort)

    results = await asyncio.gather(*[one(g) for g in groups])
    results = list(results)
    db.log_event(None, "system", "system", summary_line(run["id"], model, results))
    return {"run_id": run["id"], "day": run["day"], "model": model, "results": results}


def summary_line(run_id, model, results):
    scored = 0
    total = 0
    failed = 0
    i = 0
    while i < len(results):
        if results[i]["overall"] is None:
            failed += 1
        else:
            scored += 1
            total += results[i]["overall"]
        i += 1
    line = "Judged Run Clawnly #" + str(run_id) + " with " + model + ": " + str(scored) + " groups scored"
    if scored > 0:
        line += ", average overall " + str(round(total / scored, 1))
    if failed > 0:
        line += ", " + str(failed) + " not scored"
    return line + "."


# ----- the admin page ---------------------------------------------------------------

def scores_view(run_id):
    # one run's latest scores, with each group's event and outcome, for /admin
    run = db.get_matchmaker_run(run_id)
    if run is None:
        return None
    scores = db.list_judge_scores(run_id)
    by_group = {}
    i = 0
    while i < len(scores):
        by_group[scores[i]["group_id"]] = scores[i]
        i += 1
    rows = []
    groups = run["data"].get("groups") or []
    i = 0
    while i < len(groups):
        group = groups[i]
        activity = catalog.get(group["activity"])
        name = str(group["activity"])
        if activity is not None:
            name = activity["name"]
        score = by_group.get(group["id"])
        rows.append({"group_id": group["id"], "activity": name, "time": group.get("time"),
                     "status": group.get("status"), "size": len(group.get("final") or []), "score": score})
        i += 1
    return {"run": {"id": run["id"], "day": run["day"], "status": run["status"]},
            "judging": run_id in _JUDGING, "groups": rows}


async def _judge_in_background(run_id):
    try:
        await judge_run(run_id, config.get_client())
    except Exception as error:
        db.log_event(None, "system", "system", "Judging Run Clawnly #" + str(run_id) + " stopped: " + str(error)[:200])
    finally:
        _JUDGING.discard(run_id)


def start(run_id, by):
    # (True, None) and judging goes on in the background, or (False, the error)
    run = db.get_matchmaker_run(run_id)
    if run is None:
        return False, "No such run."
    if run["status"] == "running":
        return False, "That run is still going; judge it when it's done."
    if run_id in _JUDGING:
        return False, "That run is being judged now."
    _JUDGING.add(run_id)
    db.log_event(None, "human", "human", by + " asked the judge to score Run Clawnly #" + str(run_id) + ".")
    task = asyncio.get_running_loop().create_task(_judge_in_background(run_id))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return True, None


# ----- the command line -------------------------------------------------------------

def report_lines(outcome):
    lines = ["Run #" + str(outcome["run_id"]) + " (" + str(outcome["day"]) + "), judged by " + outcome["model"], ""]
    results = outcome["results"]
    if len(results) == 0:
        lines.append("No groups in this run.")
    i = 0
    while i < len(results):
        r = results[i]
        activity = catalog.get(r["activity"])
        name = str(r["activity"])
        if activity is not None:
            name = activity["name"]
        head = r["group_id"] + "  " + name + "  [" + str(r["status"]) + "]"
        if r["verdict"] is None:
            lines.append(head + "  NOT SCORED: " + str(r["error"]))
            lines.append("")
            i += 1
            continue
        v = r["verdict"]
        lines.append(head + "  overall " + str(v["overall"]["score"]) + "/10: " + v["overall"]["reason"])
        k = 0
        while k < len(CRITERIA):
            item = v[CRITERIA[k][0]]
            lines.append("    " + CRITERIA[k][1] + ": " + str(item["score"]) + " -- " + item["reason"])
            k += 1
        if len(v["flags"]) > 0:
            lines.append("    flags: " + "; ".join(v["flags"]))
        lines.append("")
        i += 1
    return lines


def main(argv):
    which = "latest"
    model = None
    effort = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--list":
            runs = db.list_matchmaker_runs()
            k = 0
            while k < len(runs):
                print("#" + str(runs[k]["id"]) + "  " + str(runs[k]["day"]) + "  " + str(runs[k]["status"]) + "  started " + str(runs[k]["created_at"]))
                k += 1
            if len(runs) == 0:
                print("No Run Clawnly runs in this database.")
            return 0
        if arg in ("--run", "--model", "--effort") and i + 1 < len(argv):
            if arg == "--run":
                which = argv[i + 1]
            elif arg == "--model":
                model = argv[i + 1]
            else:
                effort = argv[i + 1]
            i += 2
            continue
        print("usage: judge.py [--run latest|ID] [--model MODEL] [--effort low|medium|high] | --list")
        return 2
    db.init_db()
    outcome = asyncio.run(judge_run(which, config.get_client(), model=model, effort=effort))
    print("\n".join(report_lines(outcome)))
    return 0


if __name__ == "__main__":
    db.init_db()
    sys.exit(main(sys.argv[1:]))
