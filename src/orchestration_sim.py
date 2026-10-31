"""Run Clawnly end to end with the real matchmaker, and keep a record that rebuilds it.

A simulation runs matchmaker.run_day -- the same code /run uses: the Opus plan,
each agent's answer, the resolve step, the lock and the final messages -- for
emulated neighbors (population.py) over one or more days. Each run gets one
folder under simulation_results/:

  run_manifest.json      what ran: stage, people, days, models, commit, cost, status,
                         and a check that three separate records agree on every call
  full_simulation.jsonl  every event in order: each hub<->agent message, each code
                         check and hub decision, each group and member state change,
                         and each Claude call with its exact request, reply, usage and cost
  full_transcript.txt    the same events, readable
  agents_initial.json    each emulated person and the exact system prompt their agent got
  agents_final.json      what happened to each person, and whether anything about them
                         was saved (nothing is: the product has no memory to write to)
  groups_generated.json  each group: members, answers, negotiation, final status, and
                         the event numbers that decided it
  cost_report.json       tokens and dollars per call, per model and in total
  days/<date>.json       the run dict exactly as run_day returned it
  run_dump.txt           all of the above as one readable text file (run_dump.py)

Nothing is mocked here: `run` needs a real Anthropic key, and it stops before any
call that could push spending past the ceiling. Tests pass their own fake client,
and the manifest then says the replies did not come from Claude. A simulation
never touches the app's database (CLAWNLY_DB_PATH points at its own file).

    .venv/bin/python src/orchestration_sim.py estimate
    .venv/bin/python src/orchestration_sim.py run smoke
"""

import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(_ROOT, "simulation_results")
# its ai_calls go to a simulation database, never the app's clawnly.db (tests set their own first)
os.environ.setdefault("CLAWNLY_DB_PATH", os.path.join(RESULTS, "metadata", "simulation.db"))

import asyncio
import copy
import datetime
import json
import platform
import re
import shutil
import sys
import time

import anthropic

import ai_log
import catalog
import config
import db
import demand
import match_eval
import matchmaker
import population
import run_dump
from llm_io import extract_json, join_text


SEED = 7
# calendars start on the Wednesday of the week the code-only evaluation used (match_eval)
WEEK_START = "2026-10-28"
TOWN_SIZE = 200

# the staged plan: a smoke test, a pilot, then the whole emulated town
STAGES = {
    "smoke": {"people": 8, "days": ["2026-10-31"], "groups": 3, "ceiling": 1.50},
    "pilot": {"people": 30, "days": ["2026-10-28", "2026-10-31"], "groups": 6, "ceiling": 4.00},
    "town": {"people": 200, "days": ["2026-10-28", "2026-10-31", "2026-11-01"], "groups": 10, "ceiling": 8.00},
    # the same neighbors, busier and pickier, three days in a row so plans carry over (the team's fix 5)
    "retest": {"people": 200, "days": ["2026-10-30", "2026-10-31", "2026-11-01"], "groups": 10, "ceiling": 8.00,
               "busier": True, "pickier": True},
}
# how many of a break room's keenest people a small cohort takes, room by room
COHORT_PER_ROOM = 4

# dollars per million tokens (input, output), first-party API, checked 2026-10-29
PRICES = {
    "claude-opus-5-5": [4.00, 20.00],
    "claude-sonnet-5": [2.00, 10.00],
    "claude-sonnet-5-5": [2.00, 10.00],
    "claude-fable-5-1": [10.00, 50.00],
    "claude-haiku-5-5": [0.10, 0.50],
}
CACHE_WRITE = 1.25
CACHE_READ = 0.10
# a conservative token count for a budget check before the call: fewer chars per token = more tokens
CHARS_PER_TOKEN_WORST = 3.0
# transient API failures get this many tries in all, each one logged
ATTEMPTS = 3
RETRY_WAIT = [2, 8]

_KEY = re.compile(r"sk-ant-[A-Za-z0-9_\-]+")
_GROUP_LINE = re.compile(r"^\s+(e\d{3}) ", re.MULTILINE)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def scrub(text):
    # no API key ever lands in a results file, whatever ends up in an error message
    return _KEY.sub("[REDACTED]", text)


def price_of(model):
    if model in PRICES:
        return PRICES[model]
    return None


def call_cost(model, usage):
    # dollars for one reply, from the usage the API reported; None when there's no usage or price
    prices = price_of(model)
    if prices is None or usage is None or usage.get("input_tokens") is None:
        return None
    per_in = prices[0] / 1000000.0
    per_out = prices[1] / 1000000.0
    total = usage["input_tokens"] * per_in + usage["output_tokens"] * per_out
    total += (usage.get("cache_creation_input_tokens") or 0) * per_in * CACHE_WRITE
    total += (usage.get("cache_read_input_tokens") or 0) * per_in * CACHE_READ
    return round(total, 6)


class BudgetStop(Exception):
    pass


# ----- the recorder: every event, in the order it happened -----------------------------

class Recorder:
    def __init__(self, sim_id, people, ceiling, thinking_summaries):
        self.sim_id = sim_id
        self.people = match_eval._index(people)
        self.by_name = {}
        i = 0
        while i < len(people):
            self.by_name[people[i]["name"]] = people[i]["id"]
            i += 1
        self.ceiling = ceiling
        self.thinking_summaries = thinking_summaries
        self.spent = 0.0
        self.in_flight = 0.0
        self.stopped = False
        self.events = []
        self.day = None
        self.data = None
        self.snapshot = {}
        self.blocked = 0
        # replies that carried no usage (a test client): their cost is unknown, not zero
        self.unpriced = 0

    def add(self, kind, t=None, **fields):
        if t is None:
            t = _now()
        event = {"sim": self.sim_id, "t": t, "day": self.day, "type": kind}
        keys = list(fields.keys())
        i = 0
        while i < len(keys):
            event[keys[i]] = fields[keys[i]]
            i += 1
        event["_k"] = len(self.events)
        self.events.append(event)
        return event

    def reserve(self, model, request_chars, max_tokens):
        # refuse a call whose worst case could cross the ceiling; once stopped, stay stopped
        prices = price_of(model)
        worst = 0.0
        if prices is not None:
            worst = (request_chars / CHARS_PER_TOKEN_WORST) * prices[0] / 1000000.0 + max_tokens * prices[1] / 1000000.0
        if self.ceiling is not None and not self.stopped and self.spent + self.in_flight + worst > self.ceiling:
            self.stopped = True
            self.add("budget_stop", text="Spending ceiling reached: $" + str(round(self.spent, 4)) + " spent, $" +
                     str(round(self.in_flight, 4)) + " in flight, next call could cost up to $" + str(round(worst, 4)) +
                     " against a $" + str(self.ceiling) + " ceiling. No further calls are made.")
        if self.stopped:
            self.blocked += 1
            raise BudgetStop("spending ceiling reached; the simulation made no further calls")
        self.in_flight += worst
        return worst

    def release(self, worst, cost):
        self.in_flight -= worst
        if cost is not None:
            self.spent += cost

    # which group, person and round a call belongs to, read from the live run
    def link(self, system, payload):
        purpose = ai_log.purpose_of(system)
        out = {"purpose": purpose, "person": None, "group": None, "round": None, "group_time": None}
        if purpose == "matchmaker_agent":
            first_line = system.split("\n")[0]
            name = first_line[len("You are the personal agent of "):]
            # the name runs up to ". You know", and a name can itself end in a period
            cut = name.find(". You know ")
            if cut != -1:
                name = name[:cut]
            out["person"] = self.by_name.get(name)
            group, entry = self._latest_ask(out["person"])
            if group is not None:
                out["group"] = group["id"]
                out["round"] = entry["round"]
                out["group_time"] = group["time"]
        if purpose == "matchmaker_message":
            ids = _GROUP_LINE.findall(payload)
            group = self._locked_with(ids)
            if group is not None:
                out["group"] = group["id"]
                out["group_time"] = group["time"]
        return out

    def _latest_ask(self, person_id):
        best = None
        best_entry = None
        if self.data is None or person_id is None:
            return None, None
        groups = self.data.get("groups") or []
        g = 0
        while g < len(groups):
            thread = groups[g]["thread"]
            m = 0
            while m < len(thread):
                entry = thread[m]
                if entry.get("from") == "hub" and entry.get("to") == person_id:
                    if best_entry is None or entry["t"] >= best_entry["t"]:
                        best = groups[g]
                        best_entry = entry
                m += 1
            g += 1
        return best, best_entry

    def _locked_with(self, ids):
        if self.data is None:
            return None
        groups = self.data.get("groups") or []
        g = 0
        while g < len(groups):
            if groups[g].get("final") == ids:
                return groups[g]
            g += 1
        return None

    # run_day calls this after every step: record what changed in the groups since last time
    def progress(self, data):
        self.data = data
        groups = data.get("groups") or []
        g = 0
        while g < len(groups):
            self._diff_group(groups[g])
            g += 1

    def _diff_group(self, group):
        key = self.day + "/" + group["id"]
        before = self.snapshot.get(key)
        now = {"status": group["status"], "time": group["time"], "members": {}}
        m = 0
        while m < len(group["members"]):
            member = group["members"][m]
            now["members"][member["id"]] = {"state": member["state"], "counter": member["counter"]}
            m += 1
        if before is None:
            self.add("group_proposed", group=group["id"], frm="hub",
                     activity=group["activity"], part=group["part"], time=group["time"],
                     planned_time=group.get("plannedTime"), fixed=bool(group.get("fixed")),
                     members=list(now["members"].keys()), alternates=list(group["alternates"]),
                     why=group["why"], proposals=_proposals(group))
        else:
            if before["time"] != now["time"]:
                self.add("group_time_changed", group=group["id"], before=before["time"], after=now["time"])
            ids = list(now["members"].keys())
            i = 0
            while i < len(ids):
                pid = ids[i]
                i += 1
                old = before["members"].get(pid)
                new = now["members"][pid]
                if old is None:
                    self.add("member_added", group=group["id"], person=pid, after=new["state"],
                             text="Asked in round 2 (an alternate or a re-ask outside the first plan).")
                    continue
                if old["state"] != new["state"] or old["counter"] != new["counter"]:
                    self.add("member_state", group=group["id"], person=pid, before=old["state"], after=new["state"],
                             counter=new["counter"])
            if before["status"] != now["status"]:
                self.add("group_status", group=group["id"], before=before["status"], after=now["status"],
                         final=list(group.get("final") or []), reason=group.get("dropReason"))
        self.snapshot[key] = now


def _proposals(group):
    out = {}
    m = 0
    while m < len(group["members"]):
        out[group["members"][m]["id"]] = group["members"][m]["proposal"]
        m += 1
    return out


def _blocks(message):
    # every content block the reply carried; thinking is the API's summary, never raw reasoning
    out = []
    content = getattr(message, "content", None) or []
    i = 0
    while i < len(content):
        block = content[i]
        kind = getattr(block, "type", "?")
        item = {"type": kind}
        if kind == "text":
            item["text"] = block.text
        if kind == "thinking":
            item["thinking"] = getattr(block, "thinking", "")
        out.append(item)
        i += 1
    return out


def _usage(message):
    usage = getattr(message, "usage", None)
    if usage is None:
        return None
    return {"input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None)}


def _retryable(error):
    if isinstance(error, anthropic.RateLimitError) or isinstance(error, anthropic.APIConnectionError):
        return True
    if isinstance(error, anthropic.APIStatusError) and error.status_code >= 500:
        return True
    return False


class _RecordingMessages:
    def __init__(self, inner, recorder):
        self._inner = inner
        self._recorder = recorder

    async def create(self, **kwargs):
        rec = self._recorder
        request = dict(kwargs)
        added = []
        if rec.thinking_summaries and "thinking" not in request:
            # display only: thinking is on and billed the same either way; this makes it readable
            request["thinking"] = {"type": "adaptive", "display": "summarized"}
            added.append("thinking.display=summarized")
        model = request.get("model", "?")
        system = str(request.get("system") or "")
        payload = ""
        messages = request.get("messages") or []
        if len(messages) > 0:
            payload = str(messages[-1].get("content") or "")
        where = rec.link(system, payload)
        started_at = _now()
        worst = rec.reserve(model, len(system) + len(payload), int(request.get("max_tokens") or 0))
        started = time.monotonic()
        attempt = 1
        message = None
        failure = None
        while message is None:
            try:
                message = await self._inner.create(**request)
            except Exception as error:
                if attempt < ATTEMPTS and _retryable(error):
                    rec.add("model_retry", purpose=where["purpose"], person=where["person"], group=where["group"],
                            attempt=attempt, error=scrub(type(error).__name__ + ": " + str(error))[:400])
                    await asyncio.sleep(RETRY_WAIT[attempt - 1])
                    attempt += 1
                    continue
                failure = error
                break
        ms = int((time.monotonic() - started) * 1000)
        usage = None
        cost = None
        response = None
        if message is not None:
            usage = _usage(message)
            cost = call_cost(getattr(message, "model", None) or model, usage)
            text = join_text(message)
            response = {"id": getattr(message, "id", None), "model": getattr(message, "model", None),
                        "stop_reason": getattr(message, "stop_reason", None), "content": _blocks(message),
                        "text": text, "parsed_json": extract_json(text) is not None}
        rec.release(worst, cost)
        if message is not None and cost is None:
            rec.unpriced += 1
        error_text = None
        if failure is not None:
            error_text = scrub(type(failure).__name__ + ": " + str(failure))[:400]
        rec.add("model_call", t=started_at, purpose=where["purpose"], person=where["person"], group=where["group"],
                round=where["round"], group_time_at_ask=where["group_time"], model=model, attempts=attempt, ms=ms,
                request={"model": model, "max_tokens": request.get("max_tokens"),
                         "output_config": request.get("output_config"), "thinking": request.get("thinking"),
                         "added_by_harness": added, "system": system, "messages": messages},
                response=response, usage=usage, cost=cost, error=error_text)
        if failure is not None:
            raise failure
        return message


class RecordingClient:
    """An Anthropic-shaped client that records each call before handing back the real reply."""

    def __init__(self, inner, recorder):
        self.messages = _RecordingMessages(inner.messages, recorder)


# ----- who takes part ------------------------------------------------------------------

def town(busier=False, pickier=False):
    return population.generate(TOWN_SIZE, seed=SEED, start=datetime.date.fromisoformat(WEEK_START),
                               busier=busier, pickier=pickier)


def town_for(stage):
    return town(stage.get("busier", False), stage.get("pickier", False))


def cohort(people, day, size):
    # a small town that can still form groups: the keenest few from each of the day's
    # strongest break rooms, until there are enough people. Same people as the full town.
    if size >= len(people):
        return list(people)
    rooms = demand.break_room(people, catalog.ACTIVITIES, day)
    rooms.sort(key=matchmaker._room_strength, reverse=True)
    picked = {}
    r = 0
    while r < len(rooms) and len(picked) < size:
        taken = 0
        c = 0
        while c < len(rooms[r]["candidates"]) and taken < COHORT_PER_ROOM and len(picked) < size:
            pid = rooms[r]["candidates"][c]["id"]
            c += 1
            if pid not in picked:
                picked[pid] = True
                taken += 1
        r += 1
    out = []
    i = 0
    while i < len(people):
        if people[i]["id"] in picked:
            out.append(people[i])
        i += 1
    return out


# ----- running it -------------------------------------------------------------------------

def _ai_call_max_id():
    row = db._get_conn().execute("SELECT MAX(id) AS top FROM ai_calls").fetchone()
    if row is None or row["top"] is None:
        return 0
    return row["top"]


def _ai_calls_after(top):
    # ids only grow (AUTOINCREMENT), even after rows are deleted, so count what came after
    return db._get_conn().execute("SELECT COUNT(*) AS n FROM ai_calls WHERE id > ?", (top,)).fetchone()["n"]


def _harvest(rec, data):
    # the run's own record of every message and step, with the times it wrote them
    log = data.get("log") or []
    kinds = {"check": "code_check", "thought": "hub_thought", "decision": "hub_decision", "reply": "agent_reply_noted",
             "system": "system"}
    i = 0
    while i < len(log):
        entry = log[i]
        rec.add(kinds.get(entry["kind"], entry["kind"]), t=entry["t"], frm=entry["actor"], group=entry.get("group"),
                text=entry["text"])
        i += 1
    groups = data.get("groups") or []
    g = 0
    while g < len(groups):
        thread = groups[g]["thread"]
        m = 0
        while m < len(thread):
            entry = thread[m]
            if entry.get("from") == "hub":
                rec.add("hub_to_agent", t=entry["t"], frm="hub", to=entry["to"], person=entry["to"],
                        group=groups[g]["id"], round=entry["round"], text=entry["text"])
            if entry.get("from") == "agent":
                rec.add("agent_to_hub", t=entry["t"], frm=entry["by"], to="hub", person=entry["by"],
                        group=groups[g]["id"], round=entry["round"], answer=entry["answer"],
                        reason=entry.get("reason", ""), counter=entry["counter"], text=entry["text"])
            if entry.get("from") == "system":
                rec.add("system_note", t=entry["t"], frm="system", group=groups[g]["id"], round=entry["round"],
                        text=entry["text"])
            m += 1
        g += 1


def _count_plans(plans, data):
    # everyone in a locked group now has one more plan this week
    groups = data.get("groups") or []
    g = 0
    while g < len(groups):
        if groups[g]["status"] == "locked":
            final = groups[g].get("final") or []
            i = 0
            while i < len(final):
                plans[final[i]] = plans.get(final[i], 0) + 1
                i += 1
        g += 1


def _count(events, day, kind):
    n = 0
    i = 0
    while i < len(events):
        if events[i]["day"] == day and events[i]["type"] == kind:
            n += 1
        i += 1
    return n


async def simulate(people, days, max_groups, client, out_dir, ceiling=None, stage="custom", live=False,
                   thinking_summaries=False, command=None):
    # runs run_day for each day, recording everything, and writes the run folder; returns the manifest
    os.makedirs(os.path.dirname(db.DB_PATH) or ".", exist_ok=True)
    db.init_db()
    os.makedirs(os.path.join(out_dir, "days"), exist_ok=True)
    sim_id = os.path.basename(os.path.normpath(out_dir))
    rec = Recorder(sim_id, people, ceiling, thinking_summaries)
    recording = RecordingClient(client, rec)
    started = _now()
    rec.add("run_start", stage=stage, live=live, people=len(people), days=list(days), max_groups=max_groups,
            ceiling=ceiling, thinking_summaries=thinking_summaries)
    i = 0
    while i < len(people):
        rec.add("agent_init", person=people[i]["id"], name=people[i]["name"],
                agent_system_prompt=matchmaker._agent_system(people[i]))
        i += 1
    day_results = []
    # plans carry over from day to day, so the matchmaker can favor people with fewer
    plans = {}
    d = 0
    while d < len(days):
        day = datetime.date.fromisoformat(days[d])
        d += 1
        rec.day = day.isoformat()
        rec.data = None
        if rec.stopped:
            rec.add("day_skipped", text="Not run: the spending ceiling was reached on an earlier day.")
            day_results.append({"day": rec.day, "status": "skipped (ceiling)"})
            continue
        rec.add("day_start", text="Planning " + matchmaker.day_label(day) + " for " + str(len(people)) +
                " neighbors, up to " + str(max_groups) + " groups. " + str(len(plans)) +
                " of them already have a plan this week.", plans_before=dict(plans))
        before_rows = _ai_call_max_id()
        data = await matchmaker.run_day(day, max_groups, people, recording, on_progress=rec.progress, plans=dict(plans))
        _harvest(rec, data)
        _count_plans(plans, data)
        with open(os.path.join(out_dir, "days", rec.day + ".json"), "w", encoding="utf-8") as f:
            f.write(scrub(json.dumps(data, indent=1)))
        # three separate records of the calls: the run dict, this harness, and db.ai_calls
        harness_calls = _count(rec.events, rec.day, "model_call")
        blocked_today = _count(rec.events, rec.day, "budget_stop")
        check = {"run_calls": len(data.get("calls") or []), "harness_calls": harness_calls,
                 "db_ai_calls": _ai_calls_after(before_rows), "blocked_by_ceiling": rec.blocked}
        check["complete"] = check["run_calls"] == check["db_ai_calls"] and check["run_calls"] == harness_calls + rec.blocked
        rec.blocked = 0
        status = data["status"]
        if blocked_today > 0 or (rec.stopped and status == "done"):
            status = status + " (cut short by the spending ceiling)"
        rec.add("day_end", text="Day finished: " + status + ".", status=status, log_check=check)
        day_results.append({"day": rec.day, "status": status, "log_check": check})
    rec.add("run_end", text="Simulation finished. Spent $" + str(round(rec.spent, 4)) + ".", spent=round(rec.spent, 6))
    events = _ordered(rec.events)
    manifest = _write_outputs(out_dir, events, people, days, max_groups, stage, live, ceiling, rec, day_results,
                              started, thinking_summaries, command)
    return manifest


def _ordered(events):
    # one timeline: by time, then by the order the recorder saw them; numbered from 1
    out = list(events)
    out.sort(key=lambda e: (e["t"], e["_k"]))
    i = 0
    while i < len(out):
        out[i]["seq"] = i + 1
        del out[i]["_k"]
        i += 1
    return out


# ----- writing it down ------------------------------------------------------------------

def _dump(path, value):
    with open(path, "w", encoding="utf-8") as f:
        f.write(scrub(json.dumps(value, indent=1, ensure_ascii=False)))


def _write_outputs(out_dir, events, people, days, max_groups, stage, live, ceiling, rec, day_results, started,
                   thinking_summaries, command):
    with open(os.path.join(out_dir, "full_simulation.jsonl"), "w", encoding="utf-8") as f:
        i = 0
        while i < len(events):
            f.write(scrub(json.dumps(events[i], ensure_ascii=False)) + "\n")
            i += 1
    with open(os.path.join(out_dir, "full_transcript.txt"), "w", encoding="utf-8") as f:
        f.write(scrub(transcript(events, live)))
    _dump(os.path.join(out_dir, "agents_initial.json"), agents_initial(people))
    _dump(os.path.join(out_dir, "agents_final.json"), agents_final(people, events, out_dir))
    groups = groups_generated(events, people, out_dir)
    _dump(os.path.join(out_dir, "groups_generated.json"), groups)
    costs = cost_report(events, ceiling)
    _dump(os.path.join(out_dir, "cost_report.json"), costs)
    summary = os.path.join(RESULTS, "reports", "architecture_summary.md")
    if os.path.exists(summary):
        shutil.copyfile(summary, os.path.join(out_dir, "architecture_summary.md"))
    ids = []
    i = 0
    while i < len(people):
        ids.append(people[i]["id"])
        i += 1
    locked = 0
    i = 0
    while i < len(groups):
        if groups[i]["status"] == "locked":
            locked += 1
        i += 1
    manifest = {
        "sim_id": rec.sim_id, "stage": stage, "started": started, "finished": _now(),
        "replies_from": _replies_from(live),
        "command": command, "seed": SEED, "week_start": WEEK_START, "days": list(days), "max_groups": max_groups,
        "people": len(people), "person_ids": ids,
        "models": {"hub plan and resolve": config.MODEL_PREMIUM, "agents and final messages": config.MODEL_REASONING},
        "effort": {"hub": config.HUB_EFFORT, "agents": config.REASONING_EFFORT},
        "harness_request_changes": _changes(thinking_summaries),
        "ceiling_usd": ceiling, "spent_usd": round(rec.spent, 6), "calls_without_usage": rec.unpriced,
        "stopped_by_ceiling": rec.stopped,
        "days_run": day_results, "groups_proposed": len(groups), "groups_locked": locked,
        "events": len(events),
        "code": {"commit": match_eval._git(["rev-parse", "HEAD"]),
                 "dirty": len(match_eval._git(["status", "--porcelain", "--untracked-files=no"]) or "") > 0},
        "environment": {"python": sys.version.split(" ")[0], "anthropic_sdk": anthropic.__version__,
                        "platform": platform.platform(), "db": db.DB_PATH},
    }
    _dump(os.path.join(out_dir, "run_manifest.json"), manifest)
    # the whole run as one text file, for reading or for any AI chat
    run_dump.write(out_dir)
    return manifest


def _replies_from(live):
    if live:
        return "Claude (live Anthropic API)"
    return "a test client: these replies did NOT come from Claude"


def _changes(thinking_summaries):
    if thinking_summaries:
        return ["thinking={type: adaptive, display: summarized} on every call, so the model's thinking summary is "
                "kept. Thinking is on and billed the same without it; only what is returned differs."]
    return []


def agents_initial(people):
    out = []
    i = 0
    while i < len(people):
        person = copy.deepcopy(people[i])
        person["agent_system_prompt"] = matchmaker._agent_system(people[i])
        person["what_the_hub_sees"] = matchmaker._person_line(people[i]).strip()
        out.append(person)
        i += 1
    return out


def _events_of(events, kind):
    out = []
    i = 0
    while i < len(events):
        if events[i]["type"] == kind:
            out.append(events[i])
        i += 1
    return out


def agents_final(people, events, out_dir):
    # what happened to each person; their saved profile is compared with the one they started with
    replies = _events_of(events, "agent_to_hub")
    statuses = _events_of(events, "group_status")
    out = []
    i = 0
    while i < len(people):
        person = people[i]
        i += 1
        answers = []
        j = 0
        while j < len(replies):
            if replies[j]["person"] == person["id"]:
                answers.append({"seq": replies[j]["seq"], "day": replies[j]["day"], "group": replies[j]["group"],
                                "round": replies[j]["round"], "answer": replies[j]["answer"],
                                "counter": replies[j]["counter"], "said": replies[j]["text"]})
            j += 1
        placed = []
        j = 0
        while j < len(statuses):
            if statuses[j]["after"] == "locked" and person["id"] in statuses[j]["final"]:
                placed.append({"day": statuses[j]["day"], "group": statuses[j]["group"], "seq": statuses[j]["seq"]})
            j += 1
        out.append({"id": person["id"], "name": person["name"], "profile_after": person,
                    "profile_changed": False,
                    "memory": "none: each agent call gets only the profile and the one proposal in front of it, "
                              "and nothing an agent says is written back to the profile or carried to its next call",
                    "answers": answers, "placed_in": placed})
    # prove "unchanged" rather than assume it: compare with what the run started from
    initial_path = os.path.join(out_dir, "agents_initial.json")
    if os.path.exists(initial_path):
        with open(initial_path, encoding="utf-8") as f:
            initial = match_eval._index(json.loads(f.read()))
        i = 0
        while i < len(out):
            before = dict(initial[out[i]["id"]])
            del before["agent_system_prompt"]
            del before["what_the_hub_sees"]
            out[i]["profile_changed"] = json.dumps(before, sort_keys=True) != json.dumps(out[i]["profile_after"], sort_keys=True)
            i += 1
    return out


def _call_for(calls, day, purpose, group=None, person=None, round_no=None):
    # the last matching model call (a re-ask in round 2 is a later call)
    found = None
    i = 0
    while i < len(calls):
        c = calls[i]
        i += 1
        if c["day"] != day or c["purpose"] != purpose:
            continue
        if group is not None and c["group"] != group:
            continue
        if person is not None and c["person"] != person:
            continue
        if round_no is not None and c["round"] != round_no:
            continue
        found = c
    return found


def groups_generated(events, people, out_dir):
    by_id = match_eval._index(people)
    calls = _events_of(events, "model_call")
    proposed = _events_of(events, "group_proposed")
    asks = _events_of(events, "hub_to_agent")
    replies = _events_of(events, "agent_to_hub")
    statuses = _events_of(events, "group_status")
    times = _events_of(events, "group_time_changed")
    out = []
    p = 0
    while p < len(proposed):
        start = proposed[p]
        p += 1
        day = start["day"]
        gid = start["group"]
        with open(os.path.join(out_dir, "days", day + ".json"), encoding="utf-8") as f:
            data = json.loads(f.read())
        group = None
        g = 0
        while g < len(data["groups"]):
            if data["groups"][g]["id"] == gid:
                group = data["groups"][g]
            g += 1
        activity = catalog.get(start["activity"])
        members = []
        m = 0
        while m < len(group["members"]):
            pid = group["members"][m]["id"]
            m += 1
            answers = []
            r = 0
            while r < len(replies):
                if replies[r]["day"] == day and replies[r]["group"] == gid and replies[r]["person"] == pid:
                    ask = _matching_ask(asks, day, gid, pid, replies[r]["round"])
                    call = _call_for(calls, day, "matchmaker_agent", gid, pid, replies[r]["round"])
                    answer = {"round": replies[r]["round"], "answer": replies[r]["answer"],
                              "counter": replies[r]["counter"], "said": replies[r]["text"],
                              "ask_seq": None, "reply_seq": replies[r]["seq"], "call_seq": None,
                              "group_time_at_ask": None}
                    if ask is not None:
                        answer["ask_seq"] = ask["seq"]
                    if call is not None:
                        answer["call_seq"] = call["seq"]
                        answer["group_time_at_ask"] = call["group_time_at_ask"]
                    answers.append(answer)
                r += 1
            members.append({"id": pid, "name": by_id[pid]["name"], "answers": answers,
                            "final_state": group["members"][m - 1]["state"],
                            "code_checks_at_final_time": matchmaker.plan_checks(by_id[pid], activity, group["part"],
                                                                                 group["time"],
                                                                                 datetime.date.fromisoformat(day))})
        final_ids = list(group.get("final") or [])
        final_people = []
        f_i = 0
        while f_i < len(final_ids):
            final_people.append(by_id[final_ids[f_i]])
            f_i += 1
        status_event = None
        s = 0
        while s < len(statuses):
            if statuses[s]["day"] == day and statuses[s]["group"] == gid:
                status_event = statuses[s]
            s += 1
        time_seqs = []
        s = 0
        while s < len(times):
            if times[s]["day"] == day and times[s]["group"] == gid:
                time_seqs.append(times[s]["seq"])
            s += 1
        plan_call = _call_for(calls, day, "matchmaker_plan")
        resolve_call = _call_for(calls, day, "matchmaker_resolve")
        message_call = _call_for(calls, day, "matchmaker_message", gid)
        evidence = {"proposed_seq": start["seq"], "plan_call_seq": None, "resolve_call_seq": None,
                    "status_seq": None, "time_change_seqs": time_seqs, "message_call_seq": None}
        if plan_call is not None:
            evidence["plan_call_seq"] = plan_call["seq"]
        if resolve_call is not None:
            evidence["resolve_call_seq"] = resolve_call["seq"]
        if status_event is not None:
            evidence["status_seq"] = status_event["seq"]
        if message_call is not None:
            evidence["message_call_seq"] = message_call["seq"]
        magic = group.get("magic") or {}
        ages = []
        f_i = 0
        while f_i < len(final_people):
            ages.append(final_people[f_i]["age"])
            f_i += 1
        spread = None
        if len(ages) > 0:
            spread = max(ages) - min(ages)
        out.append({
            "group": day + "/" + gid, "day": day, "id": gid, "activity": activity["id"],
            "activity_name": activity["name"], "where": activity["where"], "cost": activity["cost"],
            "part": group["part"], "time_planned": start["time"], "time_final": group["time"],
            "fixed_event": bool(group.get("fixed")), "why_hub_chose_it": group["why"],
            "proposed_members": start["members"], "alternates": start["alternates"], "members": members,
            "final_members": final_ids, "status": group["status"], "drop_reason": group.get("dropReason"),
            "signals": {"shared_likes_overlap": match_eval.group_cohesion(final_people), "age_spread": spread},
            "headline": magic.get("headline"), "final_messages": magic.get("messages"),
            "evidence": evidence,
        })
    return out


def _matching_ask(asks, day, gid, pid, round_no):
    found = None
    i = 0
    while i < len(asks):
        a = asks[i]
        if a["day"] == day and a["group"] == gid and a["person"] == pid and a["round"] == round_no:
            found = a
        i += 1
    return found


def cost_report(events, ceiling):
    calls = _events_of(events, "model_call")
    rows = []
    by_model = {}
    by_purpose = {}
    total = 0.0
    tokens_in = 0
    tokens_out = 0
    unknown = 0
    i = 0
    while i < len(calls):
        c = calls[i]
        i += 1
        usage = c["usage"] or {}
        rows.append({"seq": c["seq"], "day": c["day"], "purpose": c["purpose"], "model": c["model"],
                     "person": c["person"], "group": c["group"], "input_tokens": usage.get("input_tokens"),
                     "output_tokens": usage.get("output_tokens"), "cost_usd": c["cost"], "ms": c["ms"],
                     "error": c["error"]})
        if c["cost"] is None:
            unknown += 1
            continue
        total += c["cost"]
        tokens_in += usage.get("input_tokens") or 0
        tokens_out += usage.get("output_tokens") or 0
        _bump(by_model, c["model"], c["cost"], usage)
        _bump(by_purpose, c["purpose"], c["cost"], usage)
    return {"ceiling_usd": ceiling, "total_usd": round(total, 6), "input_tokens": tokens_in,
            "output_tokens": tokens_out, "calls": len(calls), "calls_without_usage": unknown,
            "note": "output tokens include thinking, which is billed as output; prices in orchestration_sim.PRICES",
            "by_model": by_model, "by_purpose": by_purpose, "per_call": rows}


def _bump(table, key, cost, usage):
    if key not in table:
        table[key] = {"calls": 0, "usd": 0.0, "input_tokens": 0, "output_tokens": 0}
    table[key]["calls"] += 1
    table[key]["usd"] = round(table[key]["usd"] + cost, 6)
    table[key]["input_tokens"] += usage.get("input_tokens") or 0
    table[key]["output_tokens"] += usage.get("output_tokens") or 0


# ----- the readable transcript ---------------------------------------------------------------

def _indent(text):
    return "    " + str(text).replace("\n", "\n    ")


def _head(e):
    return "[" + str(e["seq"]).zfill(6) + "] " + e["t"][11:23] + " " + str(e["day"] or "") + "  "


def transcript(events, live):
    lines = ["CLAWNLY ORCHESTRATION SIMULATION", "Replies from: " + _replies_from(live),
             "Event numbers [nnnnnn] match `seq` in full_simulation.jsonl. Agents' full system prompts are printed",
             "once under AGENT INIT; every other prompt and reply is printed in full where the call happens.", ""]
    i = 0
    while i < len(events):
        e = events[i]
        i += 1
        kind = e["type"]
        head = _head(e)
        if kind == "agent_init":
            lines.append(head + "AGENT INIT " + e["person"] + " " + e["name"])
            lines.append(_indent(e["agent_system_prompt"]))
        elif kind == "model_call":
            usage = e["usage"] or {}
            who = ""
            if e["person"]:
                who = " for " + e["person"]
            if e["group"]:
                who = who + " in " + e["group"]
            if e["round"]:
                who = who + " (round " + str(e["round"]) + ")"
            lines.append(head + "CLAUDE CALL " + e["purpose"] + who + " | " + e["model"] + " | " +
                         str(usage.get("input_tokens")) + " in / " + str(usage.get("output_tokens")) + " out | $" +
                         str(e["cost"]) + " | " + str(e["ms"]) + " ms | attempts " + str(e["attempts"]))
            if e["purpose"] == "matchmaker_agent":
                lines.append("    SYSTEM: the agent prompt for " + str(e["person"]) + " (AGENT INIT above)")
            else:
                lines.append("    SYSTEM:")
                lines.append(_indent(e["request"]["system"]))
            msgs = e["request"]["messages"]
            j = 0
            while j < len(msgs):
                lines.append("    " + msgs[j]["role"].upper() + ":")
                lines.append(_indent(msgs[j]["content"]))
                j += 1
            if e["response"] is not None:
                blocks = e["response"]["content"]
                j = 0
                while j < len(blocks):
                    if blocks[j]["type"] == "thinking" and blocks[j].get("thinking"):
                        lines.append("    THINKING (summary from the API):")
                        lines.append(_indent(blocks[j]["thinking"]))
                    j += 1
                lines.append("    REPLY (stop: " + str(e["response"]["stop_reason"]) + ", JSON parsed: " +
                             str(e["response"]["parsed_json"]) + "):")
                lines.append(_indent(e["response"]["text"]))
            if e["error"]:
                lines.append("    ERROR: " + e["error"])
        elif kind == "hub_to_agent":
            lines.append(head + "HUB -> " + e["to"] + " (" + e["group"] + ", round " + str(e["round"]) + ")")
            lines.append(_indent(e["text"]))
        elif kind == "agent_to_hub":
            extra = ""
            if e.get("reason"):
                extra = " | reason: " + e["reason"]
            if e["counter"]:
                extra = extra + " | counter: " + e["counter"]
            lines.append(head + e["frm"] + " -> HUB (" + e["group"] + ", round " + str(e["round"]) + "): " +
                         e["answer"].upper() + extra)
            lines.append(_indent(e["text"]))
        elif kind == "group_proposed":
            lines.append(head + "GROUP PROPOSED " + e["group"] + ": " + e["activity"] + " " + e["part"] + " " +
                         e["time"] + " | members " + ", ".join(e["members"]) + " | alternates " +
                         ", ".join(e["alternates"]))
            lines.append(_indent("why: " + e["why"]))
        elif kind == "member_state":
            lines.append(head + "STATE " + e["group"] + " " + e["person"] + ": " + e["before"] + " -> " + e["after"])
        elif kind == "member_added":
            lines.append(head + "STATE " + e["group"] + " " + e["person"] + ": added (" + e["after"] + ")")
        elif kind == "group_status":
            lines.append(head + "GROUP " + e["group"] + ": " + e["before"] + " -> " + e["after"] +
                         " | final " + ", ".join(e["final"]))
        elif kind == "group_time_changed":
            lines.append(head + "TIME " + e["group"] + ": " + e["before"] + " -> " + e["after"])
        elif kind == "model_retry":
            lines.append(head + "RETRY " + str(e["purpose"]) + " attempt " + str(e["attempt"]) + ": " + e["error"])
        elif kind == "run_start":
            lines.append(head + "RUN START stage " + e["stage"] + ", " + str(e["people"]) + " people, days " +
                         ", ".join(e["days"]) + ", up to " + str(e["max_groups"]) + " groups, ceiling $" +
                         str(e["ceiling"]))
        elif kind == "day_end":
            lines.append(head + "DAY END " + e["text"] + " Log check: " + json.dumps(e["log_check"]))
        else:
            label = kind.upper().replace("_", " ")
            if e.get("frm"):
                label = label + " (" + e["frm"] + ")"
            group = ""
            if e.get("group"):
                group = " [" + e["group"] + "]"
            lines.append(head + label + group + ": " + str(e.get("text") or ""))
    return "\n".join(lines) + "\n"


# ----- the cost estimate, before anything is spent ----------------------------------------

# guesses for what each reply costs in output tokens (thinking included): low, high
OUTPUT_GUESS = {"plan": [4000, 12000], "agent": [250, 1500], "resolve": [1500, 6000], "message": [600, 2500]}
# typical chars per token for English prose and JSON on the current tokenizer
CHARS_PER_TOKEN = 3.5
ASSUMED_GROUP_SIZE = 4
REASK_SHARE = 0.3
LOCK_SHARE = 0.8
# a replacement who says no brings a second resolve call and a round 3 (matchmaker.LAST_ROUND):
# the high and worst estimates count it, and its asks
ROUND_THREE_SHARE = 0.1


def estimate(people, days, max_groups):
    # dollars for one stage: exact prompt sizes from the real prompt builders, guessed reply sizes
    by_id = match_eval._index(people)
    opus = PRICES[config.MODEL_PREMIUM]
    sonnet = PRICES[config.MODEL_REASONING]
    agent_chars = 0
    i = 0
    while i < len(people):
        agent_chars += len(matchmaker._agent_system(people[i]))
        i += 1
    agent_in = (agent_chars / max(1, len(people)) + 700) / CHARS_PER_TOKEN
    low = 0.0
    high = 0.0
    worst = 0.0
    calls = 0
    rows = []
    d = 0
    while d < len(days):
        day = datetime.date.fromisoformat(days[d])
        d += 1
        rooms = demand.break_room(people, catalog.ACTIVITIES, day)
        rooms.sort(key=matchmaker._room_strength, reverse=True)
        in_rooms = {}
        r = 0
        while r < len(rooms):
            c = 0
            while c < len(rooms[r]["candidates"]):
                in_rooms[rooms[r]["candidates"][c]["id"]] = True
                c += 1
            r += 1
        groups = min(max_groups, len(rooms), len(in_rooms) // 2)
        asks = min(groups * ASSUMED_GROUP_SIZE, len(in_rooms))
        reasks = int(round(asks * REASK_SHARE))
        third = int(round(asks * ROUND_THREE_SHARE))
        locked = int(round(groups * LOCK_SHARE))
        plan_in = (len(matchmaker._plan_system(day, max_groups)) + len(matchmaker._plan_payload(rooms, by_id))) / CHARS_PER_TOKEN
        resolve_in = (len(matchmaker._resolve_system(day)) + 120 * asks) / CHARS_PER_TOKEN
        message_in = (len(matchmaker._message_system()) + 300 * ASSUMED_GROUP_SIZE) / CHARS_PER_TOKEN
        day_low = 0.0
        day_high = 0.0
        day_worst = 0.0
        k = 0
        while k < 2:
            plan = plan_in * opus[0] / 1e6 + OUTPUT_GUESS["plan"][k] * opus[1] / 1e6
            resolve = resolve_in * opus[0] / 1e6 + OUTPUT_GUESS["resolve"][k] * opus[1] / 1e6
            agents = (asks + reasks) * (agent_in * sonnet[0] / 1e6 + OUTPUT_GUESS["agent"][k] * sonnet[1] / 1e6)
            messages = locked * (message_in * sonnet[0] / 1e6 + OUTPUT_GUESS["message"][k] * sonnet[1] / 1e6)
            if k == 0:
                day_low = plan + resolve + agents + messages
            else:
                again = resolve + third * (agent_in * sonnet[0] / 1e6 + OUTPUT_GUESS["agent"][k] * sonnet[1] / 1e6)
                day_high = plan + resolve + again + agents + messages
            k += 1
        # every reply at its max_tokens: the most the ceiling has to allow for
        day_worst = (plan_in + 2 * resolve_in) * opus[0] / 1e6 + 3 * 16000 * opus[1] / 1e6
        day_worst += (asks + reasks + third) * (agent_in * sonnet[0] / 1e6 + 4000 * sonnet[1] / 1e6)
        day_worst += locked * (message_in * sonnet[0] / 1e6 + 6000 * sonnet[1] / 1e6)
        n = 2 + asks + reasks + locked
        calls += n
        low += day_low
        high += day_high
        worst += day_worst
        rows.append({"day": day.isoformat(), "break_rooms": len(rooms), "people_in_a_room": len(in_rooms),
                     "groups": groups, "agent_asks": asks + reasks, "calls": n,
                     "plan_input_tokens": int(plan_in), "usd_low": round(day_low, 3), "usd_high": round(day_high, 3)})
    return {"people": len(people), "days": rows, "calls": calls, "usd_low": round(low, 2),
            "usd_high": round(high, 2), "usd_worst_case": round(worst, 2)}


def _print_estimates():
    names = list(STAGES.keys())
    total_low = 0.0
    total_high = 0.0
    i = 0
    while i < len(names):
        stage = STAGES[names[i]]
        group = cohort(town_for(stage), datetime.date.fromisoformat(stage["days"][0]), stage["people"])
        est = estimate(group, stage["days"], stage["groups"])
        total_low += est["usd_low"]
        total_high += est["usd_high"]
        print(names[i] + ": " + str(est["people"]) + " people, " + str(len(stage["days"])) + " day(s), up to " +
              str(stage["groups"]) + " groups/day, about " + str(est["calls"]) + " calls, $" + str(est["usd_low"]) +
              " to $" + str(est["usd_high"]) + " (every reply at max_tokens: $" + str(est["usd_worst_case"]) +
              "), ceiling $" + str(stage["ceiling"]))
        j = 0
        while j < len(est["days"]):
            print("    " + json.dumps(est["days"][j]))
            j += 1
        i += 1
    print("all stages: $" + str(round(total_low, 2)) + " to $" + str(round(total_high, 2)))


def _stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


# ----- the total cap, across every run and audit ------------------------------------------

# what all simulations and audits together may spend (authorized by Idan, 2026-10-29)
TOTAL_CAP = 10.00
LEDGER = os.path.join(RESULTS, "metadata", "spend_ledger.json")


def ledger(path=LEDGER):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.loads(f.read())


def ledger_spent(path=LEDGER):
    # an entry that never settled (a crash) still counts its whole ceiling, so the cap holds
    total = 0.0
    entries = ledger(path)
    i = 0
    while i < len(entries):
        spent = entries[i]["spent_usd"]
        if isinstance(spent, (int, float)):
            total += spent
        else:
            total += entries[i]["reserved_usd"]
        i += 1
    return round(total, 6)


def budget_for(ceiling, total_cap=TOTAL_CAP, path=LEDGER):
    # a run never gets more than what's left of the total cap
    left = round(total_cap - ledger_spent(path), 6)
    return min(ceiling, left)


def ledger_reserve(what, folder, ceiling, path=LEDGER):
    entries = ledger(path)
    entries.append({"id": len(entries) + 1, "what": what, "folder": folder, "reserved_usd": ceiling,
                    "spent_usd": None, "at": _now()})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(entries, indent=1))
    return len(entries)


def ledger_settle(entry_id, spent, path=LEDGER):
    entries = ledger(path)
    i = 0
    while i < len(entries):
        if entries[i]["id"] == entry_id:
            entries[i]["spent_usd"] = spent
            entries[i]["settled"] = _now()
        i += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(entries, indent=1))


def main(argv):
    if len(argv) < 2 or argv[1] not in ["estimate", "run"]:
        print("usage: orchestration_sim.py estimate | run <smoke|pilot|town|retest> [--ceiling DOLLARS] [--days D1,D2] [--no-thinking-summaries] [--total-cap DOLLARS]")
        return 2
    if argv[1] == "estimate":
        _print_estimates()
        return 0
    if len(argv) < 3 or argv[2] not in STAGES:
        print("pick a stage: " + ", ".join(STAGES.keys()))
        return 2
    stage = dict(STAGES[argv[2]])
    ceiling = stage["ceiling"]
    summaries = True
    total_cap = TOTAL_CAP
    i = 3
    while i < len(argv):
        if argv[i] == "--ceiling" and i + 1 < len(argv):
            ceiling = float(argv[i + 1])
            i += 1
        elif argv[i] == "--days" and i + 1 < len(argv):
            # rerun some of a stage's days with the same people, e.g. after a fix
            stage["days"] = argv[i + 1].split(",")
            i += 1
        elif argv[i] == "--no-thinking-summaries":
            summaries = False
        elif argv[i] == "--total-cap" and i + 1 < len(argv):
            # a new total only Idan can authorize; it stays on the command line in the manifest
            total_cap = float(argv[i + 1])
            i += 1
        i += 1
    key = config.resolve_api_key()
    if not key:
        print("No Anthropic API key (ANTHROPIC_API_KEY or .env). Nothing was run and nothing was spent.")
        return 1
    ceiling = budget_for(ceiling, total_cap)
    if ceiling <= 0:
        print("The $" + str(total_cap) + " total cap is used up (" + LEDGER + "). Nothing was run.")
        return 1
    # the SDK's own silent retries are off, so every retry is ours and is logged
    client = anthropic.AsyncAnthropic(api_key=key, base_url="https://api.anthropic.com", timeout=300.0, max_retries=0)
    people = cohort(town_for(stage), datetime.date.fromisoformat(STAGES[argv[2]]["days"][0]), stage["people"])
    out_dir = os.path.join(RESULTS, "runs", "run_" + _stamp() + "_" + argv[2])
    entry = ledger_reserve("simulation " + argv[2], os.path.basename(out_dir), ceiling)
    manifest = asyncio.run(simulate(people, stage["days"], stage["groups"], client, out_dir, ceiling, argv[2],
                                    live=True, thinking_summaries=summaries, command=" ".join(argv)))
    ledger_settle(entry, manifest["spent_usd"])
    print(json.dumps({"out": out_dir, "ceiling_usd": ceiling, "spent_usd": manifest["spent_usd"],
                      "total_spent_usd": ledger_spent(), "days": manifest["days_run"],
                      "groups_proposed": manifest["groups_proposed"], "groups_locked": manifest["groups_locked"]},
                     indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
