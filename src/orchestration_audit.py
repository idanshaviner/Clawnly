"""Audit one simulation run: rule checks in code, then an independent model's judgment.

Reads a run folder written by orchestration_sim.py and adds:

  audit_mechanical.json  every rule check in code, with the event numbers behind each finding
  audit_ai.json          the independent auditor's verdict and findings per group and per day
  audit_calls.jsonl      the auditor's calls, verbatim, with usage and cost
  metrics.json           the summary numbers (only ones the logs can support)
  audit_report.md        all of it, readable

Two kinds of check, kept apart:
  - mechanical: reproducible checks over the logs (room membership, double booking,
    consent to the final time, the time inside its day part, each locked person's
    profile against the final plan, agents saying yes to a conflict they were shown,
    unreadable replies, errors, the hub's blocked moves, log completeness, fairness).
  - AI: a model that took no part in the run (AUDITOR) reads each group's evidence
    packet -- profiles, the room it came from, every message with its event number --
    and judges compatibility, agent consistency, the matchmaker's decisions and the
    conversation. Code drops any finding that cites an event the packet didn't contain,
    so the auditor can't lean on evidence it never saw.

    .venv/bin/python src/orchestration_audit.py simulation_results/run_... [--ai] [--sample N]
        [--auditor MODEL] [--ceiling DOLLARS] [--no-days]
    .venv/bin/python src/orchestration_audit.py compare <run before> <run after> [day]
    .venv/bin/python src/orchestration_audit.py probe <run> <agent call seq,seq> <times>
"""

# first: it points CLAWNLY_DB_PATH at the simulation database before db.py is imported
import orchestration_sim

import asyncio
import datetime
import json
import re
import os
import random
import sys

import anthropic

import ai_log
import catalog
import config
import db
import demand
import match_eval
import matchmaker
import run_dump
from llm_io import extract_json, join_text


# the auditor is deliberately not one of the product's own models (Opus 5.5 hub, Sonnet 5
# agents), so the run is judged by a model that had no part in it
AUDITOR = "claude-fable-5-1"
AUDIT_EFFORT = "medium"
# the longest audit reply so far was about 2,800 tokens; a lower cap reserves less of the budget per call
AUDIT_MAX_TOKENS = 8000
AUDIT_CEILING = 6.00
SAMPLE_SEED = 7
ROOM_OTHERS = 8

SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]
# the checks that count as a hard-constraint violation in the summary numbers
HARD_CHECKS = ["double booking", "outside the break room", "locked without a yes", "fixed event moved",
               "time outside its day part", "locked at a time they never agreed to", "group too small"]
KINDS = ["confirmed violation", "quality issue", "subjective concern", "insufficient evidence"]

# what matchmaker.plan_checks says, sorted by how serious it is for someone already locked in
CONFLICTS = [
    ["is busy that", "busy at that time", "critical"],
    ["costs more than", "over their budget", "high"],
    ["is not into", "an activity they dislike", "high"],
    ["never said they like", "no stated interest", "high"],
    ["It involves", "something they avoid", "high"],
    ["starts before 9am", "an early start they avoid", "medium"],
    ["runs to 9pm or later", "a late night they avoid", "medium"],
]


# ----- reading a run -------------------------------------------------------------------

def load(run_dir):
    def read(name):
        with open(os.path.join(run_dir, name), encoding="utf-8") as f:
            return json.loads(f.read())
    events = []
    with open(os.path.join(run_dir, "full_simulation.jsonl"), encoding="utf-8") as f:
        lines = f.read().splitlines()
    i = 0
    while i < len(lines):
        if lines[i].strip():
            events.append(json.loads(lines[i]))
        i += 1
    initial = read("agents_initial.json")
    people = []
    i = 0
    while i < len(initial):
        person = dict(initial[i])
        del person["agent_system_prompt"]
        del person["what_the_hub_sees"]
        people.append(person)
        i += 1
    return {"dir": run_dir, "manifest": read("run_manifest.json"), "events": events, "people": people,
            "by_id": match_eval._index(people), "groups": read("groups_generated.json")}


def _of(events, kind, day=None):
    out = []
    i = 0
    while i < len(events):
        if events[i]["type"] == kind and (day is None or events[i]["day"] == day):
            out.append(events[i])
        i += 1
    return out


def _finding(severity, kind, check, what, why, expected, fix, agents=None, groups=None, evidence=None, source="code"):
    return {"severity": severity, "kind": kind, "check": check, "agents": list(agents or []),
            "groups": list(groups or []), "what": what, "why": why, "expected": expected, "fix": fix,
            "evidence": list(evidence or []), "source": source}


def classify(check_text):
    # (label, severity) for one plan_checks line; None for a mild interest, which is no conflict
    i = 0
    while i < len(CONFLICTS):
        if CONFLICTS[i][0] in check_text:
            return CONFLICTS[i][1], CONFLICTS[i][2]
        i += 1
    return None


def _part_bounds(part):
    return matchmaker.parse_hours(matchmaker.PART_HOURS[part])


def _words(text):
    out = {}
    word = ""
    text = str(text or "") + " "
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isalpha() or ch == "-":
            word = word + ch
        else:
            if len(word) > 0:
                out[word] = True
            word = ""
        i += 1
    return out


# ----- mechanical checks ----------------------------------------------------------------

def mechanical(run):
    events = run["events"]
    by_id = run["by_id"]
    findings = []
    days = run["manifest"]["days"]
    rooms_by_day = {}
    d = 0
    while d < len(days):
        day = datetime.date.fromisoformat(days[d])
        rooms = demand.break_room(run["people"], catalog.ACTIVITIES, day)
        index = {}
        r = 0
        while r < len(rooms):
            ids = {}
            c = 0
            while c < len(rooms[r]["candidates"]):
                ids[rooms[r]["candidates"][c]["id"]] = True
                c += 1
            index[rooms[r]["activity"] + "|" + rooms[r]["part"]] = ids
            r += 1
        rooms_by_day[days[d]] = index
        d += 1

    placed_by_day = {}
    g = 0
    while g < len(run["groups"]):
        group = run["groups"][g]
        g += 1
        findings.extend(_check_group(group, by_id, rooms_by_day.get(group["day"], {})))
        if group["status"] == "locked":
            day_map = placed_by_day.setdefault(group["day"], {})
            f = 0
            while f < len(group["final_members"]):
                day_map.setdefault(group["final_members"][f], []).append(group)
                f += 1

    # one person, one group a day
    day_keys = list(placed_by_day.keys())
    d = 0
    while d < len(day_keys):
        people = list(placed_by_day[day_keys[d]].keys())
        p = 0
        while p < len(people):
            groups = placed_by_day[day_keys[d]][people[p]]
            if len(groups) > 1:
                names = []
                refs = []
                k = 0
                while k < len(groups):
                    names.append(groups[k]["group"])
                    refs.append(groups[k]["evidence"]["status_seq"])
                    k += 1
                findings.append(_finding("critical", "confirmed violation", "double booking",
                                         people[p] + " is locked into " + str(len(groups)) + " groups on " + day_keys[d] + ".",
                                         "One person can't be in two places; each group expects them.",
                                         "Each person is in at most one locked group a day.",
                                         "Have the lock step reject a second group for anyone already locked that day.",
                                         [people[p]], names, refs))
            p += 1
        d += 1

    findings.extend(_check_round_two(events, by_id))
    findings.extend(_check_calls(events))
    findings.extend(_check_hub_blocks(events))
    findings.extend(_check_logs(events))
    return findings


def _check_round_two(events, by_id):
    # round 2 is for questions: re-asking a yes about an unchanged plan wastes a call, and
    # telling people who declined shares a private answer
    out = []
    replies = _of(events, "agent_to_hub")
    calls = _of(events, "model_call")
    asks = _of(events, "hub_to_agent")
    wasted = {}
    i = 0
    while i < len(asks):
        ask = asks[i]
        i += 1
        key = ask["day"] + "/" + ask["group"]
        if ask["round"] == 2:
            first = _answer_in(replies, ask["day"], ask["group"], ask["person"], 1)
            first_call = _agent_call(calls, ask["day"], ask["group"], ask["person"], 1)
            second_call = _agent_call(calls, ask["day"], ask["group"], ask["person"], 2)
            same_time = first_call is not None and second_call is not None and \
                first_call["group_time_at_ask"] == second_call["group_time_at_ask"]
            if first is not None and first["answer"] == "yes" and same_time:
                entry = wasted.setdefault(key, {"people": [], "refs": []})
                entry["people"].append(ask["person"])
                entry["refs"].append(ask["seq"])
        words = _words(ask["text"])
        j = 0
        while j < len(replies):
            r = replies[j]
            j += 1
            if r["day"] != ask["day"] or r["group"] != ask["group"] or r["answer"] != "no" or r["person"] == ask["person"]:
                continue
            if r["seq"] > ask["seq"]:
                continue
            first_name = by_id[r["person"]]["name"].split(" ")[0]
            if first_name in words:
                out.append(_finding("medium", "quality issue", "hub told others who declined",
                                    "The hub's round-" + str(ask["round"]) + " message to " + ask["person"] + " in " + key +
                                    " names " + r["person"] + " ('" + first_name + "'), who had said no.",
                                    "Whether someone declined is their private answer; the group only needs to know who is coming.",
                                    "Messages before the lock say who is coming, never who said no.",
                                    "Say in the resolve prompt never to name decliners, and check hub messages in code.",
                                    [ask["person"], r["person"]], [key], [r["seq"], ask["seq"]]))
    keys = list(wasted.keys())
    keys.sort()
    i = 0
    while i < len(keys):
        entry = wasted[keys[i]]
        out.append(_finding("low", "quality issue", "re-asked a yes about an unchanged plan",
                            "In round 2 the hub asked " + str(len(entry["people"])) + " people in " + keys[i] + " (" +
                            ", ".join(entry["people"]) + ") again although they had said yes and the time hadn't changed.",
                            "Each is another agent call that can only confirm or, worse, flip a settled yes.",
                            "Round 2 asks only alternates, people who countered, and yeses whose time changed.",
                            "Tell the resolve step that confirmations go out after the lock; have code skip re-asks of "
                            "an unchanged yes.",
                            entry["people"], [keys[i]], entry["refs"]))
        i += 1
    return out


def _answer_in(replies, day, group, person, round_no):
    i = 0
    while i < len(replies):
        r = replies[i]
        if r["day"] == day and r["group"] == group and r["person"] == person and r["round"] == round_no:
            return r
        i += 1
    return None


def _agent_call(calls, day, group, person, round_no):
    i = 0
    while i < len(calls):
        c = calls[i]
        if c["day"] == day and c["group"] == group and c["person"] == person and c["round"] == round_no and \
                c["purpose"] == "matchmaker_agent":
            return c
        i += 1
    return None


def _check_group(group, by_id, rooms):
    out = []
    gid = group["group"]
    ev = group["evidence"]
    day = datetime.date.fromisoformat(group["day"])
    activity = catalog.get(group["activity"])
    members = {}
    m = 0
    while m < len(group["members"]):
        members[group["members"][m]["id"]] = group["members"][m]
        m += 1

    # every answer: did an agent say yes to something code had told it conflicts?
    m = 0
    while m < len(group["members"]):
        member = group["members"][m]
        m += 1
        a = 0
        while a < len(member["answers"]):
            answer = member["answers"][a]
            a += 1
            if answer["answer"] != "yes" or answer["group_time_at_ask"] is None:
                continue
            checks = matchmaker.plan_checks(by_id[member["id"]], activity, group["part"], answer["group_time_at_ask"], day)
            c = 0
            while c < len(checks):
                found = classify(checks[c])
                c += 1
                if found is None:
                    continue
                severity = "medium"
                if found[1] == "critical":
                    severity = "high"
                out.append(_finding(severity, "quality issue", "agent accepted a conflict it was shown",
                                    member["id"] + "'s agent said yes to " + gid + " although code told it: " + checks[c - 1],
                                    "The agent is meant to check the plan against its person's profile; this yes ignores "
                                    "a conflict it was handed.",
                                    "No, or a counter that removes the conflict, unless the agent explains why it doesn't apply.",
                                    "Tighten the agent prompt, or have code refuse a yes that contradicts a hard check.",
                                    [member["id"]], [gid], [answer["call_seq"], answer["reply_seq"]]))

    # proposals that name the other people (the plan prompt says not to yet)
    first_names = {}
    ids = list(members.keys())
    i = 0
    while i < len(ids):
        first_names[ids[i]] = by_id[ids[i]]["name"].split(" ")[0]
        i += 1
    i = 0
    while i < len(ids):
        proposal = _proposal_of(group, ids[i])
        # a greeting addresses the recipient, even if a neighbor shares their first name
        proposal = re.sub(r"^\s*" + re.escape(first_names[ids[i]]) + r"\s*[,!:]\s*", "", proposal, count=1)
        words = _words(proposal)
        j = 0
        while j < len(ids):
            if j != i and first_names[ids[j]] in words:
                out.append(_finding("low", "quality issue", "proposal names another person",
                                    "The hub's proposal to " + ids[i] + " mentions '" + first_names[ids[j]] +
                                    "', a first name of another member of " + gid + ".",
                                    "The plan prompt says not to name the other people before the group is confirmed.",
                                    "Proposals describe the group without names.",
                                    "Check proposals in code for members' names before sending (a human should confirm "
                                    "the word is the name, not an ordinary word).",
                                    [ids[i], ids[j]], [gid], [ev["proposed_seq"]]))
            j += 1
        i += 1

    if group["status"] != "locked":
        return out

    final = group["final_members"]
    room = rooms.get(group["activity"] + "|" + group["part"], {})
    fixed = matchmaker.fixed_time(activity, group["part"])
    if fixed is not None and group["time_final"] != fixed:
        out.append(_finding("critical", "confirmed violation", "fixed event moved",
                            gid + " is a fixed-time event at " + fixed + " but was locked for " + group["time_final"] + ".",
                            "The event happens when it happens; people would turn up at the wrong time.",
                            "The final time equals the event's real time.", "Keep the fixed time in code at lock.",
                            final, [gid], [ev["status_seq"]] + ev["time_change_seqs"]))
    hours = matchmaker.parse_hours(group["time_final"])
    bounds = _part_bounds(group["part"])
    if hours is None:
        out.append(_finding("low", "insufficient evidence", "final time unreadable",
                            gid + "'s final time '" + group["time_final"] + "' can't be read as a start and end.",
                            "Code can't check it against the calendar or the early/late rules.",
                            "A start and an end, e.g. 10am-12pm.", "Ask for a fixed time format in the resolve step.",
                            final, [gid], [ev["status_seq"]]))
    elif fixed is None and (hours[0] < bounds[0] or hours[1] > bounds[1]):
        out.append(_finding("high", "confirmed violation", "time outside its day part",
                            gid + " is a " + group["part"] + " group (" + matchmaker.PART_HOURS[group["part"]] +
                            ") locked for " + group["time_final"] + ".",
                            "Calendars and break rooms are checked per day part, so nobody checked whether people are "
                            "free at this time.",
                            "The final time stays inside the group's day part.",
                            "Reject a resolve-step time that leaves the day part, in code.",
                            final, [gid], [ev["status_seq"]] + ev["time_change_seqs"]))
    if len(final) < catalog.GROUP_MIN:
        out.append(_finding("critical", "confirmed violation", "group too small",
                            gid + " was locked with " + str(len(final)) + " people.", "A group needs at least two.",
                            "Lock only at two or more yes.", "Check the lock rule.", final, [gid], [ev["status_seq"]]))
    if len(final) > catalog.GROUP_MAX:
        out.append(_finding("info", "subjective concern", "group larger than the preview's size",
                            gid + " has " + str(len(final)) + " people; the code-only preview caps groups at " +
                            str(catalog.GROUP_MAX) + ".", "The live matchmaker has no upper limit by design.",
                            "A product decision.", "None needed unless the team wants a cap.", final, [gid],
                            [ev["status_seq"]]))
    i = 0
    while i < len(final):
        pid = final[i]
        i += 1
        member = members.get(pid)
        if pid not in room:
            out.append(_finding("critical", "confirmed violation", "outside the break room",
                                pid + " is locked into " + gid + " but isn't in that activity's break room for the day.",
                                "Break rooms hold only people who are free, interested, can afford it and avoid nothing about it.",
                                "Only people from the room.", "Check the room at lock as well as at plan.",
                                [pid], [gid], [ev["status_seq"]]))
        if member is None or member["final_state"] != "yes":
            out.append(_finding("critical", "confirmed violation", "locked without a yes",
                                pid + " is in " + gid + "'s final group without a yes.", "Nobody goes without agreeing.",
                                "Only people whose agent said yes.", "Check the lock rule.", [pid], [gid], [ev["status_seq"]]))
            continue
        last = None
        a = 0
        while a < len(member["answers"]):
            if last is None or member["answers"][a]["round"] >= last["round"]:
                last = member["answers"][a]
            a += 1
        if last is not None and last["group_time_at_ask"] is not None and last["group_time_at_ask"] != group["time_final"]:
            out.append(_finding("high", "confirmed violation", "locked at a time they never agreed to",
                                pid + "'s agent said yes to " + gid + " at " + last["group_time_at_ask"] +
                                ", but the group was locked for " + group["time_final"] + " and they were not asked again.",
                                "Their yes was for a different time; the new time was never checked with them.",
                                "Anyone whose yes predates a time change is asked again, or isn't counted.",
                                "When the resolve step moves a group's time, code re-asks (or stops counting) the "
                                "people who said yes to the old time.",
                                [pid], [gid], [last["reply_seq"]] + ev["time_change_seqs"] + [ev["status_seq"]]))
        checks = member["code_checks_at_final_time"]
        c = 0
        while c < len(checks):
            found = classify(checks[c])
            c += 1
            if found is None:
                continue
            kind = "confirmed violation"
            if found[1] == "medium":
                kind = "quality issue"
            out.append(_finding(found[1], kind, "locked into " + found[0],
                                pid + " is locked into " + gid + " (" + group["activity_name"] + ", " + group["time_final"] +
                                "): " + checks[c - 1],
                                "The final plan conflicts with what this person told their agent.",
                                "Nobody is locked into a plan their own profile rules out.",
                                "Re-run plan_checks at lock time and refuse members with a hard conflict.",
                                [pid], [gid], [last["reply_seq"], ev["status_seq"]]))

    # the final messages: one per person, and only naming people who are actually coming
    messages = group.get("final_messages") or {}
    if group.get("headline") is not None or len(messages) > 0:
        i = 0
        while i < len(final):
            if final[i] not in messages:
                out.append(_finding("medium", "quality issue", "no final message",
                                    final[i] + " is in " + gid + " but got no confirmation message.",
                                    "They wouldn't know the plan or who's coming.", "A message for every final member.",
                                    "Fill in a plain message in code for anyone the model skipped.",
                                    [final[i]], [gid], [ev["message_call_seq"]]))
            i += 1
        not_coming = []
        i = 0
        while i < len(ids):
            if ids[i] not in final:
                not_coming.append(ids[i])
            i += 1
        keys = list(messages.keys())
        i = 0
        while i < len(keys):
            words = _words(messages[keys[i]])
            j = 0
            while j < len(not_coming):
                if first_names[not_coming[j]] in words:
                    out.append(_finding("medium", "quality issue", "message names someone who isn't coming",
                                        "The message to " + keys[i] + " mentions '" + first_names[not_coming[j]] +
                                        "', who was asked for " + gid + " but isn't in the final group.",
                                        "It tells the person someone is coming who said no (or wasn't asked again).",
                                        "Messages name only final members.",
                                        "Check message text in code against the final members' names.",
                                        [keys[i], not_coming[j]], [gid], [ev["message_call_seq"]]))
                j += 1
            i += 1
    elif group["status"] == "locked":
        out.append(_finding("medium", "quality issue", "no final message",
                            gid + " was locked but no message was written for it.", "Nobody is told the plan.",
                            "A message for every locked group.", "Retry the message call, or send a plain one from code.",
                            final, [gid], [ev["status_seq"]]))
    return out


def _proposal_of(group, person_id):
    # the hub's first message to this person for this group
    m = 0
    while m < len(group["members"]):
        member = group["members"][m]
        if member["id"] == person_id:
            return member.get("first_proposal") or ""
        m += 1
    return ""


def _check_calls(events):
    out = []
    calls = _of(events, "model_call")
    i = 0
    while i < len(calls):
        c = calls[i]
        i += 1
        who = []
        if c["person"]:
            who.append(c["person"])
        groups = []
        if c["group"]:
            groups.append(c["day"] + "/" + c["group"])
        if c["error"]:
            out.append(_finding("high", "confirmed violation", "a Claude call failed",
                                "The " + c["purpose"] + " call failed after " + str(c["attempts"]) + " attempt(s): " + c["error"],
                                "A failed agent call is counted as a no; a failed hub call stops the day.",
                                "Calls succeed, or the failure is visible to the person and retried.",
                                "Look at the error; retry transient ones (the harness already does).",
                                who, groups, [c["seq"]]))
            continue
        response = c["response"] or {}
        if response.get("stop_reason") == "max_tokens":
            out.append(_finding("high", "confirmed violation", "reply cut off",
                                "The " + c["purpose"] + " reply hit max_tokens.", "A cut-off reply can't be read as JSON.",
                                "Replies finish.", "Raise max_tokens for this call.", who, groups, [c["seq"]]))
        if response.get("stop_reason") == "refusal":
            out.append(_finding("high", "confirmed violation", "model refused",
                                "The " + c["purpose"] + " call was refused by the model's safeguards.",
                                "The step had no answer.", "An answer.", "Read the refusal category and adjust the prompt.",
                                who, groups, [c["seq"]]))
        if not response.get("parsed_json"):
            severity = "medium"
            consequence = "Code reads an unreadable agent reply as a no, so this person was dropped silently."
            if c["purpose"] in ["matchmaker_plan", "matchmaker_resolve"]:
                severity = "high"
                consequence = "An unreadable hub reply means no groups (plan) or no round 2 (resolve)."
            out.append(_finding(severity, "confirmed violation", "reply wasn't JSON",
                                "The " + c["purpose"] + " reply couldn't be read as JSON.", consequence,
                                "A reply in the required JSON shape.",
                                "Use structured outputs (output_config.format) for this call.", who, groups, [c["seq"]]))
    retries = _of(events, "model_retry")
    i = 0
    while i < len(retries):
        out.append(_finding("info", "insufficient evidence", "a call was retried",
                            "The " + str(retries[i]["purpose"]) + " call was retried: " + retries[i]["error"],
                            "Only a concern if it keeps happening.", "-", "-", [], [], [retries[i]["seq"]]))
        i += 1
    stops = _of(events, "budget_stop")
    i = 0
    while i < len(stops):
        out.append(_finding("info", "insufficient evidence", "spending ceiling reached",
                            stops[i]["text"], "Everything after this point wasn't run; agents not asked count as no.",
                            "-", "Raise the ceiling or shrink the stage.", [], [], [stops[i]["seq"]]))
        i += 1
    return out


def _check_hub_blocks(events):
    # moves the hub made that code had to block: rule-following, measured
    out = []
    checks = _of(events, "code_check")
    i = 0
    while i < len(checks):
        text = checks[i]["text"]
        if text.startswith("Rejected"):
            group = []
            if checks[i].get("group"):
                group.append(checks[i]["day"] + "/" + checks[i]["group"])
            out.append(_finding("low", "quality issue", "hub tried something the rules forbid",
                                text, "Code blocked it, but the hub proposed it: it shows how often the model "
                                "ignores the rules it was given.", "The hub follows the rules in its prompt.",
                                "Nothing urgent (code holds); a frequent pattern is worth a prompt fix.",
                                [], group, [checks[i]["seq"]]))
        i += 1
    return out


def _check_logs(events):
    out = []
    ends = _of(events, "day_end")
    i = 0
    while i < len(ends):
        check = ends[i]["log_check"]
        if not check["complete"]:
            out.append(_finding("critical", "confirmed violation", "logs disagree",
                                "On " + ends[i]["day"] + " the run recorded " + str(check["run_calls"]) + " calls, the "
                                "harness " + str(check["harness_calls"]) + " (+" + str(check["blocked_by_ceiling"]) +
                                " blocked) and db.ai_calls " + str(check["db_ai_calls"]) + ".",
                                "A call missing from a log can't be audited.", "All three records agree.",
                                "Find the call that escaped a recorder.", [], [], [ends[i]["seq"]]))
        i += 1
    return out


# ----- the numbers -------------------------------------------------------------------------

def fairness(run):
    # who was in a room, asked and placed, by kind of person (over all days of the run)
    events = run["events"]
    in_room = {}
    days = run["manifest"]["days"]
    d = 0
    while d < len(days):
        rooms = demand.break_room(run["people"], catalog.ACTIVITIES, datetime.date.fromisoformat(days[d]))
        r = 0
        while r < len(rooms):
            c = 0
            while c < len(rooms[r]["candidates"]):
                in_room[rooms[r]["candidates"][c]["id"]] = True
                c += 1
            r += 1
        d += 1
    asked = {}
    asks = _of(events, "hub_to_agent")
    i = 0
    while i < len(asks):
        asked[asks[i]["person"]] = True
        i += 1
    placed = {}
    g = 0
    while g < len(run["groups"]):
        if run["groups"][g]["status"] == "locked":
            f = 0
            while f < len(run["groups"][g]["final_members"]):
                pid = run["groups"][g]["final_members"][f]
                placed[pid] = placed.get(pid, 0) + 1
                f += 1
        g += 1
    table = {}
    i = 0
    while i < len(run["people"]):
        p = run["people"][i]
        i += 1
        keys = ["all", "archetype: " + p["archetype"], "budget: " + p["budget"]]
        if p["kids_at_home"]:
            keys.append("kids at home")
        k = 0
        while k < len(keys):
            row = table.setdefault(keys[k], {"people": 0, "in_a_room": 0, "asked": 0, "placed": 0, "placements": 0})
            row["people"] += 1
            if p["id"] in in_room:
                row["in_a_room"] += 1
            if p["id"] in asked:
                row["asked"] += 1
            if p["id"] in placed:
                row["placed"] += 1
                row["placements"] += placed[p["id"]]
            k += 1
    # in a break room on some day of the run, yet never asked: the people the hub passed over
    never = []
    ids = list(in_room.keys())
    ids.sort()
    i = 0
    while i < len(ids):
        if ids[i] not in asked:
            never.append(ids[i])
        i += 1
    return {"by_kind": table, "in_a_room_but_never_asked": never}


def metrics(run, findings, ai):
    events = run["events"]
    replies = _of(events, "agent_to_hub")
    answers = {"yes": 0, "no": 0, "counter": 0}
    i = 0
    while i < len(replies):
        answers[replies[i]["answer"]] = answers.get(replies[i]["answer"], 0) + 1
        i += 1
    groups = run["groups"]
    locked = 0
    dropped = 0
    i = 0
    while i < len(groups):
        if groups[i]["status"] == "locked":
            locked += 1
        if groups[i]["status"] == "dropped":
            dropped += 1
        i += 1
    by_check = {}
    hard = 0
    agent_conflicts = 0
    failures = 0
    i = 0
    while i < len(findings):
        f = findings[i]
        i += 1
        by_check[f["check"]] = by_check.get(f["check"], 0) + 1
        locked_conflict = f["kind"] == "confirmed violation" and f["check"].startswith("locked into")
        if locked_conflict or f["check"] in HARD_CHECKS:
            hard += 1
        if f["check"] == "agent accepted a conflict it was shown":
            agent_conflicts += 1
        if f["check"] in ["a Claude call failed", "reply cut off", "model refused", "reply wasn't JSON", "logs disagree"]:
            failures += 1
    total_replies = len(replies)
    rate = None
    if total_replies > 0:
        rate = round(answers["yes"] / total_replies, 3)
    days = _of(events, "day_end")
    failed_days = 0
    i = 0
    while i < len(days):
        if not days[i]["status"].startswith("done"):
            failed_days += 1
        i += 1
    sim_cost = run["manifest"]["spent_usd"]
    if run["manifest"].get("calls_without_usage"):
        sim_cost = "unknown: " + str(run["manifest"]["calls_without_usage"]) + " replies reported no usage"
    out = {
        "replies_from": run["manifest"]["replies_from"],
        "agents": run["manifest"]["people"],
        "days": len(run["manifest"]["days"]),
        "groups_proposed": len(groups), "groups_locked": locked, "groups_dropped": dropped,
        "invitations_sent": len(_of(events, "hub_to_agent")), "agent_replies": total_replies,
        "answers": answers, "acceptance_rate": rate,
        "hard_constraint_violations": hard,
        "agents_accepting_a_conflict_they_were_shown": agent_conflicts,
        "orchestration_failures": failures, "days_not_done": failed_days,
        "findings_by_check": by_check,
        "simulation_cost_usd": sim_cost,
        "audit_cost_usd": None, "ai_audit_coverage": None, "ai_inconsistent_agents": None,
    }
    if ai is not None:
        out["audit_cost_usd"] = ai["cost_usd"]
        out["ai_audit_coverage"] = str(ai["groups_audited"]) + " of " + str(len(groups)) + " groups, " + \
            str(ai["days_audited"]) + " of " + str(len(run["manifest"]["days"])) + " days"
        out["ai_inconsistent_agents"] = ai["inconsistent_agents"]
    return out


# ----- the independent AI audit ---------------------------------------------------------------

def _audit_group_system():
    return "\n".join([
        "You are an independent auditor of Clawnly. Its matchmaker (one AI model) plans small neighborhood activity groups by messaging each person's personal agent (another AI model) one to one; agents never talk to each other, and code enforces the hard rules. Task: audit one negotiated group from the logs below. You took no part in any of it.",
        "",
        "Judge only what the log shows. Every event has a number in brackets: cite those numbers as evidence, and only numbers that appear below. Never explain a decision with reasons the log doesn't contain; if the log can't show why something happened, say the evidence is insufficient. Code's rule checks are listed; don't repeat them, but do judge behavior around them (for example an agent agreeing despite a conflict it was shown).",
        "",
        "Assess:",
        "1. Social compatibility: do these people make sense together for this activity (shared interests, stage of life, anything that would clash)? Would someone listed from the same break room clearly have fit better?",
        "2. Each agent: did its answers follow its person's profile (likes, dislikes, what they avoid, budget, calendar)? Contradictions, an unjustified yes or no, invented facts about the person?",
        "3. The matchmaker: did the proposal, the alternates, the handling of declines and counters, and the final group follow the evidence? Unsupported assumptions? Do the final messages use only facts from the profiles and name only people who are coming?",
        "4. The conversation: clear and natural, consistent, no misunderstandings or wasted asks.",
        "",
        "Severity: critical (a hard rule broken or a person harmed), high (a wrong or indefensible decision), medium (a clear quality problem), low (minor). Kind: \"confirmed violation\" (the log proves a rule was broken), \"quality issue\" (strongly supported by the log), \"subjective concern\" (a judgment call), \"insufficient evidence\" (the log can't tell). Don't invent problems: an empty findings list is a good answer when nothing is wrong.",
        "",
        "Reply with only this JSON object:",
        '{"verdict": "good" or "acceptable" or "weak" or "bad", "summary": "2-4 sentences", "compatibility": "2-3 sentences", "agents": [{"id": "person id", "consistent": true or false, "note": "one sentence"}], "matchmaker": "2-3 sentences", "conversation": "1-2 sentences", "findings": [{"severity": "critical|high|medium|low", "kind": "confirmed violation|quality issue|subjective concern|insufficient evidence", "agents": ["person id"], "what": "what happened", "why": "why it is a problem", "expected": "what should have happened", "fix": "the smallest correction", "evidence": [event numbers]}]}',
    ])


def _audit_day_system():
    return "\n".join([
        "You are an independent auditor of Clawnly. Its matchmaker (one AI model) plans small neighborhood activity groups from break rooms that code builds, then asks each person's agent one to one. Task: audit the matchmaker's whole day from the logs below. You took no part in any of it.",
        "",
        "Judge only what the log shows, and cite the event numbers in brackets (only numbers that appear below). Don't explain decisions with reasons the log doesn't contain.",
        "",
        "Assess the matchmaker's decisions for the day: did the plan follow the evidence in the break rooms and profiles? Did it spread invitations fairly, or pass over people who clearly fit? Did it make unsupported assumptions, ignore preferences, or plan groups that were likely to fail? How did it adapt to declines and counters? Is the day's outcome defensible?",
        "",
        "Severity: critical, high, medium, low. Kind: \"confirmed violation\", \"quality issue\", \"subjective concern\", \"insufficient evidence\". An empty findings list is a good answer when nothing is wrong.",
        "",
        "Reply with only this JSON object:",
        '{"verdict": "good" or "acceptable" or "weak" or "bad", "summary": "3-5 sentences", "findings": [{"severity": "...", "kind": "...", "agents": ["person id"], "groups": ["group id"], "what": "...", "why": "...", "expected": "...", "fix": "...", "evidence": [event numbers]}]}',
    ])


def _line(seq, text):
    return "[" + str(seq) + "] " + text


def group_packet(run, group, mech):
    # everything the auditor may cite, each line carrying its event number; returns (text, cited-ok set)
    events = run["events"]
    by_id = run["by_id"]
    valid = {}
    lines = []
    day = group["day"]
    gid = group["id"]
    ev = group["evidence"]

    def cite(seq):
        if seq is not None:
            valid[seq] = True
        return seq

    lines.append("GROUP " + group["group"] + ": " + group["activity_name"] + " at " + group["where"] + ", " +
                 matchmaker.day_label(datetime.date.fromisoformat(day)) + ", " + group["part"] + ", planned " +
                 group["time_planned"] + ", final " + group["time_final"] + ", cost " + group["cost"] +
                 ", fixed-time event: " + str(group["fixed_event"]) + ". Outcome: " + group["status"] +
                 _drop(group) + ".")
    lines.append(_line(cite(ev["proposed_seq"]), "The matchmaker's reason for this group: " + group["why_hub_chose_it"]))
    lines.append("")
    lines.append("PEOPLE ASKED, OR NAMED AS ALTERNATES (each profile exactly as their own agent knew it):")
    ids = []
    m = 0
    while m < len(group["members"]):
        ids.append(group["members"][m]["id"])
        m += 1
    a = 0
    while a < len(group["alternates"]):
        if group["alternates"][a] not in ids:
            ids.append(group["alternates"][a])
        a += 1
    i = 0
    while i < len(ids):
        role = "member"
        if ids[i] not in group["proposed_members"]:
            role = "alternate"
        lines.append("- " + ids[i] + " (" + role + "):")
        lines.append("    " + matchmaker.agent_profile(by_id[ids[i]]).replace("\n", "\n    "))
        i += 1
    lines.append("")
    lines.append("OTHERS IN THE SAME BREAK ROOM THAT DAY (not asked for this group), keenest first:")
    rooms = demand.break_room(run["people"], catalog.ACTIVITIES, datetime.date.fromisoformat(day))
    shown = 0
    r = 0
    while r < len(rooms):
        if rooms[r]["activity"] == group["activity"] and rooms[r]["part"] == group["part"]:
            c = 0
            while c < len(rooms[r]["candidates"]) and shown < ROOM_OTHERS:
                cand = rooms[r]["candidates"][c]
                c += 1
                if cand["id"] in ids:
                    continue
                lines.append("  " + matchmaker._person_line(by_id[cand["id"]]).strip() + " (keenness " + str(cand["score"]) + ")")
                shown += 1
        r += 1
    if shown == 0:
        lines.append("  (none)")
    lines.append("")
    lines.append("TIMELINE (event numbers in brackets):")
    i = 0
    while i < len(events):
        e = events[i]
        i += 1
        if e["day"] != day:
            continue
        if e["type"] == "model_call" and e["purpose"] == "matchmaker_agent" and e["group"] == gid:
            lines.append(_line(cite(e["seq"]), "What " + str(e["person"]) + "'s agent was shown (round " +
                               str(e["round"]) + "):\n    " + e["request"]["messages"][-1]["content"].replace("\n", "\n    ")))
        elif e["type"] == "hub_to_agent" and e["group"] == gid:
            lines.append(_line(cite(e["seq"]), "HUB -> " + e["person"] + " (round " + str(e["round"]) + "): " + e["text"]))
        elif e["type"] == "agent_to_hub" and e["group"] == gid:
            extra = ""
            if e["counter"]:
                extra = " (counter: " + e["counter"] + ")"
            lines.append(_line(cite(e["seq"]), e["person"] + "'s agent -> HUB: " + e["answer"].upper() + extra + ". " + e["text"]))
        elif e["type"] in ["group_time_changed"] and e["group"] == gid:
            lines.append(_line(cite(e["seq"]), "Time changed: " + e["before"] + " -> " + e["after"]))
        elif e["type"] == "group_status" and e["group"] == gid:
            lines.append(_line(cite(e["seq"]), "Group " + e["after"] + ". Final: " + ", ".join(e["final"]) + _reason(e)))
        elif e["type"] in ["code_check", "hub_decision", "system_note"] and e.get("group") == gid:
            lines.append(_line(cite(e["seq"]), e["frm"].upper() + ": " + e["text"]))
        elif e["type"] == "model_call" and e["purpose"] == "matchmaker_resolve":
            lines.append(_line(cite(e["seq"]), "The matchmaker's resolve step (its reply for the whole day):\n    " +
                               str((e["response"] or {}).get("text")).replace("\n", "\n    ")))
        elif e["type"] == "model_call" and e["purpose"] == "matchmaker_message" and e["group"] == gid:
            lines.append(_line(cite(e["seq"]), "Final messages:\n    " +
                               str((e["response"] or {}).get("text")).replace("\n", "\n    ")))
    lines.append("")
    lines.append("THE SAME AGENTS ELSEWHERE IN THE RUN:")
    others = 0
    replies = _of(events, "agent_to_hub")
    i = 0
    while i < len(replies):
        e = replies[i]
        i += 1
        if e["person"] in ids and not (e["day"] == day and e["group"] == gid):
            group_name = e["group"]
            j = 0
            while j < len(run["groups"]):
                if run["groups"][j]["day"] == e["day"] and run["groups"][j]["id"] == e["group"]:
                    group_name = run["groups"][j]["activity_name"] + " (" + run["groups"][j]["time_final"] + ")"
                j += 1
            lines.append(_line(cite(e["seq"]), e["person"] + " on " + e["day"] + ", " + group_name + ": " +
                               e["answer"].upper() + ". " + e["text"]))
            others += 1
    if others == 0:
        lines.append("  (none)")
    lines.append("")
    lines.append("RULE CHECKS ALREADY DONE BY CODE FOR THIS GROUP:")
    shown = 0
    i = 0
    while i < len(mech):
        if group["group"] in mech[i]["groups"]:
            lines.append("  - " + mech[i]["severity"] + ", " + mech[i]["check"] + ": " + mech[i]["what"])
            shown += 1
        i += 1
    if shown == 0:
        lines.append("  (none flagged)")
    return "\n".join(lines), valid


def _drop(group):
    if group["status"] == "dropped" and group.get("drop_reason"):
        return " (" + group["drop_reason"] + ")"
    return ""


def _reason(e):
    if e.get("reason"):
        return " (" + e["reason"] + ")"
    return ""


def day_packet(run, day):
    events = run["events"]
    valid = {}
    lines = ["DAY " + day + " for " + str(run["manifest"]["people"]) + " emulated neighbors."]
    i = 0
    while i < len(events):
        e = events[i]
        i += 1
        if e["day"] != day:
            continue
        if e["type"] == "model_call" and e["purpose"] == "matchmaker_plan":
            valid[e["seq"]] = True
            lines.append(_line(e["seq"], "What the matchmaker saw when planning (code-built break rooms and people):\n    " +
                               e["request"]["messages"][-1]["content"].replace("\n", "\n    ")))
            lines.append(_line(e["seq"], "The matchmaker's plan:\n    " + str((e["response"] or {}).get("text")).replace("\n", "\n    ")))
        elif e["type"] == "model_call" and e["purpose"] == "matchmaker_resolve":
            valid[e["seq"]] = True
            lines.append(_line(e["seq"], "What the matchmaker saw after round 1:\n    " +
                               e["request"]["messages"][-1]["content"].replace("\n", "\n    ")))
            lines.append(_line(e["seq"], "Its resolve reply:\n    " + str((e["response"] or {}).get("text")).replace("\n", "\n    ")))
        elif e["type"] == "agent_to_hub":
            valid[e["seq"]] = True
            lines.append(_line(e["seq"], e["person"] + " (" + e["group"] + ", round " + str(e["round"]) + "): " +
                               e["answer"].upper() + ". " + e["text"]))
        elif e["type"] in ["code_check", "group_status", "budget_stop", "system", "system_note"]:
            valid[e["seq"]] = True
            text = e.get("text")
            if e["type"] == "group_status":
                text = "Group " + e["group"] + " " + e["after"] + ", final: " + ", ".join(e["final"]) + _reason(e)
            lines.append(_line(e["seq"], str(text)))
    # the plan only lists likes; the auditor also needs what each person avoids and dislikes
    asked = {}
    asks = _of(events, "hub_to_agent", day)
    i = 0
    while i < len(asks):
        asked[asks[i]["person"]] = True
        i += 1
    ids = list(asked.keys())
    ids.sort()
    lines.append("")
    lines.append("FULL PROFILES OF EVERYONE ASKED TODAY (exactly as their own agents knew them):")
    i = 0
    while i < len(ids):
        lines.append("- " + ids[i] + ": " + matchmaker.agent_profile(run["by_id"][ids[i]]).replace("\n", " "))
        i += 1
    fair = fairness_for_day(run, day)
    lines.append("")
    lines.append("CODE'S COUNT FOR THE DAY: " + json.dumps(fair))
    return "\n".join(lines), valid


def fairness_for_day(run, day):
    rooms = demand.break_room(run["people"], catalog.ACTIVITIES, datetime.date.fromisoformat(day))
    in_room = {}
    r = 0
    while r < len(rooms):
        c = 0
        while c < len(rooms[r]["candidates"]):
            in_room[rooms[r]["candidates"][c]["id"]] = True
            c += 1
        r += 1
    asked = {}
    asks = _of(run["events"], "hub_to_agent", day)
    i = 0
    while i < len(asks):
        asked[asks[i]["person"]] = True
        i += 1
    placed = 0
    g = 0
    while g < len(run["groups"]):
        if run["groups"][g]["day"] == day and run["groups"][g]["status"] == "locked":
            placed += len(run["groups"][g]["final_members"])
        g += 1
    return {"break_rooms": len(rooms), "people_in_a_room": len(in_room), "people_asked": len(asked),
            "people_placed": placed}


def _full_ids(groups, day):
    # a day's auditor says "g1"; findings everywhere else say "2026-10-31/g1"
    out = []
    i = 0
    while i < len(groups):
        name = str(groups[i])
        if day is not None and "/" not in name:
            name = day + "/" + name
        out.append(name)
        i += 1
    return out


def _validate(raw, valid, source, where, day=None):
    # keep the auditor's findings, but only trust the ones whose evidence is in what it was shown
    kept = []
    dropped = []
    findings = []
    if isinstance(raw, dict) and isinstance(raw.get("findings"), list):
        findings = raw["findings"]
    i = 0
    while i < len(findings):
        f = findings[i]
        i += 1
        if not isinstance(f, dict):
            continue
        refs = f.get("evidence")
        if not isinstance(refs, list):
            refs = []
        good = []
        bad = []
        j = 0
        while j < len(refs):
            ref = refs[j]
            j += 1
            if isinstance(ref, int) and ref in valid:
                good.append(ref)
            else:
                bad.append(ref)
        severity = str(f.get("severity") or "low").lower()
        if severity not in SEVERITY_ORDER:
            severity = "low"
        kind = str(f.get("kind") or "subjective concern").lower()
        if kind not in KINDS:
            kind = "subjective concern"
        groups = f.get("groups")
        if not isinstance(groups, list):
            groups = where
        groups = _full_ids(groups, day)
        agents = f.get("agents")
        if not isinstance(agents, list):
            agents = []
        item = _finding(severity, kind, "AI audit", str(f.get("what") or ""), str(f.get("why") or ""),
                        str(f.get("expected") or ""), str(f.get("fix") or ""), agents, groups, good,
                        source=source)
        if len(good) == 0 or len(bad) > 0:
            item["unsupported_refs"] = bad
            dropped.append(item)
        else:
            kept.append(item)
    return kept, dropped


def _sample(run, mech, size):
    # every group code flagged and every dropped group, then a seeded draw from the rest
    flagged = {}
    i = 0
    while i < len(mech):
        if mech[i]["severity"] != "info":
            j = 0
            while j < len(mech[i]["groups"]):
                flagged[mech[i]["groups"][j]] = True
                j += 1
        i += 1
    must = []
    rest = []
    g = 0
    while g < len(run["groups"]):
        group = run["groups"][g]
        g += 1
        if group["group"] in flagged or group["status"] != "locked":
            must.append(group)
        else:
            rest.append(group)
    if size is None or len(must) + len(rest) <= size:
        return must + rest, "every group"
    rng = random.Random(SAMPLE_SEED)
    rng.shuffle(rest)
    room = max(0, size - len(must))
    picked = must + rest[:room]
    return picked, ("all " + str(len(must)) + " groups code flagged or that didn't lock, plus " + str(min(room, len(rest))) +
                    " of the other " + str(len(rest)) + " drawn with seed " + str(SAMPLE_SEED))


async def ai_audit(run, mech, client, model=AUDITOR, effort=AUDIT_EFFORT, size=None, ceiling=AUDIT_CEILING, with_days=True):
    db.init_db()
    rec = orchestration_sim.Recorder(run["manifest"]["sim_id"] + "-audit", run["people"], ceiling, True)
    logged = ai_log.LoggedClient(orchestration_sim.RecordingClient(client, rec))
    picked, how = _sample(run, mech, size)
    results = {"auditor": model, "effort": effort, "sampling": how, "groups": [], "days": [], "kept": [],
               "unsupported": [], "failures": []}

    async def ask(system, packet, label):
        try:
            message = await logged.messages.create(model=model, max_tokens=AUDIT_MAX_TOKENS, system=system,
                                                   output_config={"effort": effort},
                                                   messages=[{"role": "user", "content": packet}])
        except Exception as error:
            results["failures"].append(label + ": " + orchestration_sim.scrub(str(error))[:300])
            return None
        raw = extract_json(join_text(message))
        if raw is None:
            results["failures"].append(label + ": the auditor's reply wasn't JSON")
        return raw

    # days first: if the ceiling bites, it cuts sampled groups, not the review of the hub's whole day
    days = run["manifest"]["days"]
    if not with_days:
        days = []
    d = 0
    while d < len(days):
        rec.day = days[d]
        packet, valid = day_packet(run, days[d])
        raw = await ask(_audit_day_system(), packet, "day " + days[d])
        d += 1
        if raw is None:
            continue
        kept, dropped = _validate(raw, valid, "AI audit of day " + days[d - 1], [], days[d - 1])
        results["kept"].extend(kept)
        results["unsupported"].extend(dropped)
        results["days"].append({"day": days[d - 1], "verdict": raw.get("verdict"), "summary": raw.get("summary")})
    i = 0
    while i < len(picked):
        group = picked[i]
        i += 1
        rec.day = group["day"]
        packet, valid = group_packet(run, group, mech)
        raw = await ask(_audit_group_system(), packet, group["group"])
        if raw is None:
            continue
        kept, dropped = _validate(raw, valid, "AI audit of " + group["group"], [group["group"]])
        results["kept"].extend(kept)
        results["unsupported"].extend(dropped)
        results["groups"].append({"group": group["group"], "verdict": raw.get("verdict"), "summary": raw.get("summary"),
                                  "compatibility": raw.get("compatibility"), "agents": raw.get("agents"),
                                  "matchmaker": raw.get("matchmaker"), "conversation": raw.get("conversation")})
    results["events"] = orchestration_sim._ordered(rec.events)
    results["cost_usd"] = round(rec.spent, 6)
    if rec.unpriced > 0:
        results["cost_usd"] = "unknown: " + str(rec.unpriced) + " replies reported no usage"
    results["groups_audited"] = len(results["groups"])
    results["days_audited"] = len(results["days"])
    inconsistent = []
    g = 0
    while g < len(results["groups"]):
        agents = results["groups"][g].get("agents") or []
        a = 0
        while a < len(agents):
            if isinstance(agents[a], dict) and agents[a].get("consistent") is False:
                inconsistent.append({"group": results["groups"][g]["group"], "id": agents[a].get("id"),
                                     "note": agents[a].get("note")})
            a += 1
        g += 1
    results["inconsistent_agents"] = len(inconsistent)
    results["inconsistent_agent_notes"] = inconsistent
    return results


# ----- the report ------------------------------------------------------------------------------

def _by_severity(findings):
    out = list(findings)
    out.sort(key=lambda f: SEVERITY_ORDER.index(f["severity"]))
    return out


def _refs(f):
    parts = []
    i = 0
    while i < len(f["evidence"]):
        if f["evidence"][i] is not None:
            parts.append(str(f["evidence"][i]))
        i += 1
    return ", ".join(parts)


def report(run, mech, ai, numbers, fair):
    lines = ["# Audit: " + run["manifest"]["sim_id"], "",
             "Replies came from: **" + run["manifest"]["replies_from"] + "**.", "",
             "Event numbers are `seq` in `full_simulation.jsonl` and `[nnnnnn]` in `full_transcript.txt`.", "",
             "## Numbers", "", "| | |", "|---|---|"]
    keys = ["agents", "days", "groups_proposed", "groups_locked", "groups_dropped", "invitations_sent", "agent_replies",
            "answers", "acceptance_rate", "hard_constraint_violations", "agents_accepting_a_conflict_they_were_shown",
            "ai_inconsistent_agents", "orchestration_failures", "days_not_done", "simulation_cost_usd", "audit_cost_usd",
            "ai_audit_coverage"]
    i = 0
    while i < len(keys):
        lines.append("| " + keys[i].replace("_", " ") + " | " + str(numbers[keys[i]]).replace("|", "/") + " |")
        i += 1
    lines.append("")
    lines.append("## Rule checks in code (" + str(len(mech)) + " findings)")
    lines.append("")
    lines.extend(_finding_lines(_by_severity(mech)))
    if ai is not None:
        lines.append("")
        lines.append("## Independent AI audit (" + ai["auditor"] + ", effort " + ai["effort"] + ")")
        lines.append("")
        lines.append("Sampling: " + ai["sampling"] + ". Failures: " + str(len(ai["failures"])) + ".")
        lines.append("")
        lines.append("| Group | Verdict | Summary |")
        lines.append("|---|---|---|")
        g = 0
        while g < len(ai["groups"]):
            row = ai["groups"][g]
            lines.append("| " + row["group"] + " | " + str(row["verdict"]) + " | " + str(row["summary"]).replace("|", "/").replace("\n", " ") + " |")
            g += 1
        d = 0
        while d < len(ai["days"]):
            lines.append("")
            lines.append("**Day " + ai["days"][d]["day"] + " (" + str(ai["days"][d]["verdict"]) + "):** " + str(ai["days"][d]["summary"]))
            d += 1
        lines.append("")
        lines.append("### Findings with evidence (" + str(len(ai["kept"])) + ")")
        lines.append("")
        lines.extend(_finding_lines(_by_severity(ai["kept"])))
        lines.append("")
        lines.append("### Findings dropped: no valid evidence cited (" + str(len(ai["unsupported"])) + ")")
        lines.append("")
        lines.extend(_finding_lines(_by_severity(ai["unsupported"])))
        if len(ai["failures"]) > 0:
            lines.append("")
            lines.append("Audit failures: " + "; ".join(ai["failures"]))
    lines.append("")
    lines.append("## Who got a chance (all days)")
    lines.append("")
    lines.append("| Kind | People | In a room | Asked | Placed | Placements |")
    lines.append("|---|---|---|---|---|---|")
    kinds = list(fair["by_kind"].keys())
    kinds.sort()
    i = 0
    while i < len(kinds):
        row = fair["by_kind"][kinds[i]]
        lines.append("| " + kinds[i] + " | " + str(row["people"]) + " | " + str(row["in_a_room"]) + " | " +
                     str(row["asked"]) + " | " + str(row["placed"]) + " | " + str(row["placements"]) + " |")
        i += 1
    lines.append("")
    lines.append("In a break room on some day but never asked: " + str(len(fair["in_a_room_but_never_asked"])) + " people.")
    return "\n".join(lines) + "\n"


def _finding_lines(findings):
    if len(findings) == 0:
        return ["None."]
    out = []
    i = 0
    while i < len(findings):
        f = findings[i]
        i += 1
        who = ""
        if len(f["agents"]) > 0:
            who = " Agents: " + ", ".join(_strings(f["agents"])) + "."
        where = ""
        if len(f["groups"]) > 0:
            where = " Groups: " + ", ".join(_strings(f["groups"])) + "."
        out.append("- **" + f["severity"] + "** · " + f["kind"] + " · " + f["check"] + ": " + f["what"] + who + where +
                   " Events: " + _refs(f) + ".")
        out.append("  - Why: " + f["why"] + " Expected: " + f["expected"] + " Fix: " + f["fix"])
    return out


def _strings(items):
    out = []
    i = 0
    while i < len(items):
        out.append(str(items[i]))
        i += 1
    return out


def audit(run_dir, client=None, use_ai=False, model=AUDITOR, effort=AUDIT_EFFORT, size=None, ceiling=AUDIT_CEILING,
          days=True):
    run = load(run_dir)
    _add_first_proposals(run)
    mech = mechanical(run)
    ai = None
    if use_ai:
        ai = asyncio.run(ai_audit(run, mech, client, model, effort, size, ceiling, days))
        with open(os.path.join(run_dir, "audit_calls.jsonl"), "w", encoding="utf-8") as f:
            i = 0
            while i < len(ai["events"]):
                f.write(orchestration_sim.scrub(json.dumps(ai["events"][i], ensure_ascii=False)) + "\n")
                i += 1
        saved = dict(ai)
        del saved["events"]
        orchestration_sim._dump(os.path.join(run_dir, "audit_ai.json"), saved)
    elif os.path.exists(os.path.join(run_dir, "audit_ai.json")):
        # rule checks rerun on their own keep the AI audit already paid for
        with open(os.path.join(run_dir, "audit_ai.json"), encoding="utf-8") as f:
            ai = json.loads(f.read())
    fair = fairness(run)
    numbers = metrics(run, mech, ai)
    orchestration_sim._dump(os.path.join(run_dir, "audit_mechanical.json"), {"findings": _by_severity(mech), "fairness": fair})
    orchestration_sim._dump(os.path.join(run_dir, "metrics.json"), numbers)
    with open(os.path.join(run_dir, "audit_report.md"), "w", encoding="utf-8") as f:
        f.write(orchestration_sim.scrub(report(run, mech, ai, numbers, fair)))
    # the one-file dump now carries what the checks found, at its end
    run_dump.write(run_dir)
    return {"mechanical": mech, "ai": ai, "metrics": numbers, "fairness": fair}


def _add_first_proposals(run):
    # the hub's first message to each member, from the plan, for the name check
    proposed = _of(run["events"], "group_proposed")
    i = 0
    while i < len(proposed):
        e = proposed[i]
        i += 1
        g = 0
        while g < len(run["groups"]):
            group = run["groups"][g]
            g += 1
            if group["day"] != e["day"] or group["id"] != e["group"]:
                continue
            m = 0
            while m < len(group["members"]):
                group["members"][m]["first_proposal"] = e["proposals"].get(group["members"][m]["id"], "")
                m += 1


# ----- replaying one agent decision, to test a prompt fix on the exact case ---------------------

async def probe(run, seqs, times, client, ceiling):
    # each agent call in `seqs` is sent again `times` times with the prompt it ran with and `times`
    # times with the current code's prompt: same person, same proposal, same code findings
    by_seq = {}
    i = 0
    while i < len(run["events"]):
        by_seq[run["events"][i]["seq"]] = run["events"][i]
        i += 1
    rec = orchestration_sim.Recorder(run["manifest"]["sim_id"] + "-probe", run["people"], ceiling, True)
    logged = ai_log.LoggedClient(orchestration_sim.RecordingClient(client, rec))
    rows = []
    s = 0
    while s < len(seqs):
        call = by_seq[seqs[s]]
        s += 1
        rec.day = call["day"]
        person = run["by_id"][call["person"]]
        versions = [["as run", call["request"]["system"]], ["current code", matchmaker._agent_system(person)]]
        v = 0
        while v < len(versions):
            k = 0
            while k < times:
                k += 1
                answer = None
                said = None
                try:
                    message = await logged.messages.create(
                        model=call["request"]["model"], max_tokens=call["request"]["max_tokens"],
                        system=versions[v][1], output_config=call["request"]["output_config"],
                        messages=[{"role": "user", "content": call["request"]["messages"][-1]["content"]}])
                    raw = extract_json(join_text(message))
                    if isinstance(raw, dict):
                        answer = raw.get("answer")
                        said = raw.get("say")
                except Exception as error:
                    said = "failed: " + orchestration_sim.scrub(str(error))[:200]
                rows.append({"seq": call["seq"], "person": call["person"], "prompt": versions[v][0],
                             "answer": answer, "said": said})
            v += 1
    return {"rows": rows, "events": orchestration_sim._ordered(rec.events), "cost_usd": round(rec.spent, 6)}


def probe_table(rows):
    counts = {}
    order = []
    i = 0
    while i < len(rows):
        key = str(rows[i]["seq"]) + " " + rows[i]["person"] + " | " + rows[i]["prompt"]
        if key not in counts:
            counts[key] = {}
            order.append(key)
        counts[key][str(rows[i]["answer"])] = counts[key].get(str(rows[i]["answer"]), 0) + 1
        i += 1
    lines = ["| Call, person, prompt | Answers |", "|---|---|"]
    i = 0
    while i < len(order):
        lines.append("| " + order[i] + " | " + json.dumps(counts[order[i]]) + " |")
        i += 1
    return "\n".join(lines) + "\n"


# ----- before and after a fix -----------------------------------------------------------------

def side_interest_share(run):
    # placed people who don't like the activity's first tag: in for the beer at a trivia night.
    # A proxy, the same one match_eval uses, not a verdict
    placed = 0
    side = 0
    g = 0
    while g < len(run["groups"]):
        group = run["groups"][g]
        g += 1
        if group["status"] != "locked":
            continue
        main = catalog.get(group["activity"])["tags"][0]
        f = 0
        while f < len(group["final_members"]):
            placed += 1
            likes = match_eval._liked(run["by_id"][group["final_members"][f]])
            if main not in likes:
                side += 1
            f += 1
    if placed == 0:
        return None
    return round(side / placed, 3)


def only_day(run, day):
    # the same run, cut down to one day, so a one-day rerun compares like with like
    groups = []
    g = 0
    while g < len(run["groups"]):
        if run["groups"][g]["day"] == day:
            groups.append(run["groups"][g])
        g += 1
    events = []
    i = 0
    while i < len(run["events"]):
        if run["events"][i]["day"] == day:
            events.append(run["events"][i])
        i += 1
    run["groups"] = groups
    run["events"] = events
    run["manifest"] = dict(run["manifest"])
    run["manifest"]["days"] = [day]
    run["manifest"]["spent_usd"] = None
    return run


def numbers_for(run_dir, day=None):
    run = load(run_dir)
    if day is not None:
        run = only_day(run, day)
    _add_first_proposals(run)
    mech = mechanical(run)
    m = metrics(run, mech, None)
    calls = _of(run["events"], "model_call")
    agent_calls = 0
    i = 0
    while i < len(calls):
        if calls[i]["purpose"] == "matchmaker_agent":
            agent_calls += 1
        i += 1
    return {"run": os.path.basename(os.path.normpath(run_dir)), "days": ", ".join(run["manifest"]["days"]),
            "groups locked / proposed": str(m["groups_locked"]) + " / " + str(m["groups_proposed"]),
            "people placed": _placed_count(run), "agent calls": agent_calls, "answers": m["answers"],
            "acceptance rate": m["acceptance_rate"], "hard-constraint violations": m["hard_constraint_violations"],
            "agents saying yes to a conflict they were shown": m["agents_accepting_a_conflict_they_were_shown"],
            "re-asks of an unchanged yes": m["findings_by_check"].get("re-asked a yes about an unchanged plan", 0),
            "messages naming a decliner": m["findings_by_check"].get("hub told others who declined", 0),
            "placed for a side interest only": side_interest_share(run),
            "orchestration failures": m["orchestration_failures"], "cost (USD)": _day_cost(run)}


def _day_cost(run):
    total = 0.0
    calls = _of(run["events"], "model_call")
    i = 0
    while i < len(calls):
        if calls[i]["cost"] is None:
            return None
        total += calls[i]["cost"]
        i += 1
    return round(total, 4)


def _placed_count(run):
    total = 0
    g = 0
    while g < len(run["groups"]):
        if run["groups"][g]["status"] == "locked":
            total += len(run["groups"][g]["final_members"])
        g += 1
    return total


def compare(before_dir, after_dir, day=None):
    before = numbers_for(before_dir, day)
    after = numbers_for(after_dir, day)
    lines = ["| | Before | After |", "|---|---|---|"]
    keys = list(before.keys())
    i = 0
    while i < len(keys):
        lines.append("| " + keys[i] + " | " + str(before[keys[i]]) + " | " + str(after[keys[i]]) + " |")
        i += 1
    return "\n".join(lines) + "\n"


def main(argv):
    if len(argv) >= 5 and argv[1] == "probe":
        # probe <run> <seq,seq> <times>: replay agent calls with the old and current prompt
        key = config.resolve_api_key()
        if not key:
            print("No Anthropic API key.")
            return 1
        ceiling = orchestration_sim.budget_for(0.25)
        if ceiling <= 0:
            print("The total cap is used up.")
            return 1
        seqs = []
        parts = argv[3].split(",")
        i = 0
        while i < len(parts):
            seqs.append(int(parts[i]))
            i += 1
        client = anthropic.AsyncAnthropic(api_key=key, base_url="https://api.anthropic.com", timeout=300.0, max_retries=0)
        entry = orchestration_sim.ledger_reserve("probe", os.path.basename(os.path.normpath(argv[2])), ceiling)
        result = asyncio.run(probe(load(argv[2]), seqs, int(argv[4]), client, ceiling))
        orchestration_sim.ledger_settle(entry, result["cost_usd"])
        with open(os.path.join(argv[2], "probe_calls.jsonl"), "w", encoding="utf-8") as f:
            i = 0
            while i < len(result["events"]):
                f.write(orchestration_sim.scrub(json.dumps(result["events"][i], ensure_ascii=False)) + "\n")
                i += 1
        orchestration_sim._dump(os.path.join(argv[2], "probe_results.json"), result["rows"])
        print(probe_table(result["rows"]))
        print("cost $" + str(result["cost_usd"]) + ", total spent $" + str(orchestration_sim.ledger_spent()))
        return 0
    if len(argv) >= 4 and argv[1] == "compare":
        # rule checks only, no API calls; an optional day compares just that day of both runs
        day = None
        if len(argv) == 5:
            day = argv[4]
        print(compare(argv[2], argv[3], day))
        return 0
    if len(argv) < 2:
        print("usage: orchestration_audit.py <run folder> [--ai] [--sample N] [--auditor MODEL] [--ceiling DOLLARS]")
        return 2
    use_ai = False
    size = None
    model = AUDITOR
    ceiling = AUDIT_CEILING
    days = True
    i = 2
    while i < len(argv):
        if argv[i] == "--ai":
            use_ai = True
        if argv[i] == "--sample" and i + 1 < len(argv):
            size = int(argv[i + 1])
            i += 1
        elif argv[i] == "--auditor" and i + 1 < len(argv):
            model = argv[i + 1]
            i += 1
        elif argv[i] == "--ceiling" and i + 1 < len(argv):
            ceiling = float(argv[i + 1])
            i += 1
        elif argv[i] == "--no-days":
            days = False
        i += 1
    client = None
    entry = None
    if use_ai:
        key = config.resolve_api_key()
        if not key:
            print("No Anthropic API key: the AI audit needs one. Run without --ai for the rule checks only.")
            return 1
        ceiling = orchestration_sim.budget_for(ceiling)
        if ceiling <= 0:
            print("The $" + str(orchestration_sim.TOTAL_CAP) + " total cap is used up. Run without --ai for the rule checks only.")
            return 1
        client = anthropic.AsyncAnthropic(api_key=key, base_url="https://api.anthropic.com", timeout=600.0, max_retries=0)
        entry = orchestration_sim.ledger_reserve("audit " + model, os.path.basename(os.path.normpath(argv[1])), ceiling)
    result = audit(argv[1], client, use_ai, model, AUDIT_EFFORT, size, ceiling, days)
    if entry is not None:
        orchestration_sim.ledger_settle(entry, result["ai"]["cost_usd"])
    numbers = dict(result["metrics"])
    numbers["total_spent_usd"] = orchestration_sim.ledger_spent()
    print(json.dumps(numbers, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
