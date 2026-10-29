"""One plain-text file per simulation run: everything that happened, to read or hand to any AI.

No dashboard and no tooling: `run_dump.txt` in a run folder is the whole run, top to bottom,
written for a person scrolling it and for an AI chat it is pasted into.

  1. how to use it, and what the words mean
  2. the people: each one's personality prompt as their agent got it (before), and what
     happened to them (after: profile checked unchanged, every answer, where they were placed)
  3. the conversations: each day's plan (what the hub saw, its reasoning, its plan), every
     hub -> agent message with what code showed the agent, every reply, the resolve step, the
     lock and the final messages
  4. the groups: each one with its activity, time, members, the hub's reason, what the members
     share, every answer and the code checks at the final time
  5. the timeline: every event in order, one line each
  6. what our own checks found, last, so a fresh review can skip it

Every line carries its event number [#n], the same `seq` as full_simulation.jsonl and
full_transcript.txt, so anything here can be traced to the verbatim record.

    .venv/bin/python src/run_dump.py simulation_results/run_...            one run
    .venv/bin/python src/run_dump.py --all simulation_results/ALL_RUNS_DUMP.txt simulation_results/run_...
    .venv/bin/python src/run_dump.py --book simulation_results/RUN_CLAWNLY_FULL_RECORD.md simulation_results/run_...

The --book form is the combined record: the reports (summary, how it works, the audit), a guide
to evaluating it, each person once across all runs, then every run's conversations and groups.
"""

import datetime
import json
import os
import sys

import catalog
import matchmaker
from llm_io import extract_json


RULE = "=" * 100
THIN = "-" * 100


def _read(run_dir, name):
    path = os.path.join(run_dir, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.loads(f.read())


def _events(run_dir):
    out = []
    with open(os.path.join(run_dir, "full_simulation.jsonl"), encoding="utf-8") as f:
        lines = f.read().splitlines()
    i = 0
    while i < len(lines):
        if lines[i].strip():
            out.append(json.loads(lines[i]))
        i += 1
    return out


def _of(events, kind, day=None):
    out = []
    i = 0
    while i < len(events):
        if events[i]["type"] == kind and (day is None or events[i]["day"] == day):
            out.append(events[i])
        i += 1
    return out


def _indent(text, pad="    "):
    return pad + str(text).replace("\n", "\n" + pad)


def _ref(seq):
    if seq is None:
        return "[#?]"
    return "[#" + str(seq) + "]"


def _banner(lines, title):
    lines.append("")
    lines.append(RULE)
    lines.append(title)
    lines.append(RULE)
    lines.append("")


def _thinking(call):
    # the API's summary of the model's reasoning, when the run asked for it
    out = []
    blocks = (call.get("response") or {}).get("content") or []
    i = 0
    while i < len(blocks):
        if blocks[i].get("type") == "thinking" and blocks[i].get("thinking"):
            out.append(blocks[i]["thinking"].strip())
        i += 1
    return "\n".join(out)


def _name(people, pid):
    if pid in people:
        return pid + " " + people[pid]["name"]
    return str(pid)


# ----- the agent prompt: printed in full once, then each person's own part -----------------------

def _told_block(prompt):
    # the part of an agent's prompt that is about the person: between "TOLD YOU:" and the rules
    start = prompt.find("TOLD YOU:\n")
    end = prompt.find("\n\nCheck the plan")
    if start == -1 or end == -1:
        return None
    return prompt[start + len("TOLD YOU:\n"):end]


def _shape(prompt, person):
    # the prompt with everything personal swapped for placeholders: equal shapes mean equal wording
    block = _told_block(prompt)
    if block is None:
        return None
    first = person["name"].split(" ")[0]
    out = prompt.replace(block, "<PROFILE>")
    out = out.replace(person["name"], "<NAME>")
    out = out.replace(first.upper(), "<FIRST UPPER>")
    out = out.replace(first, "<FIRST>")
    return out


# ----- 1. the header ---------------------------------------------------------------------------

def _header(lines, manifest):
    lines.append(RULE)
    lines.append("CLAWNLY ORCHESTRATION RUN: " + manifest["sim_id"])
    lines.append(RULE)
    lines.append("")
    lines.append("Replies came from: " + manifest["replies_from"])
    lines.append("Stage: " + manifest["stage"] + " | people: " + str(manifest["people"]) + " | days: " +
                 ", ".join(manifest["days"]) + " | up to " + str(manifest["max_groups"]) + " groups a day")
    lines.append("Groups proposed / locked: " + str(manifest["groups_proposed"]) + " / " + str(manifest["groups_locked"]) +
                 " | spent: $" + str(manifest["spent_usd"]) + " | events: " + str(manifest["events"]))
    lines.append("Models: hub (plan and resolve) " + manifest["models"]["hub plan and resolve"] + ", agents and final messages " +
                 manifest["models"]["agents and final messages"] + " | effort: hub " + manifest["effort"]["hub"] +
                 ", agents " + manifest["effort"]["agents"])
    lines.append("Code: commit " + str(manifest["code"]["commit"]) + ", uncommitted changes: " + str(manifest["code"]["dirty"]) +
                 " | seed " + str(manifest["seed"]) + ", calendars from " + manifest["week_start"])
    lines.append("")
    lines.append("HOW TO USE THIS FILE")
    lines.append("  Read it top to bottom, or paste or upload it into any AI chat and ask questions, for example:")
    lines.append("    - What is group 2026-10-31/g1, and does it make sense for these people?")
    lines.append("    - Who said what to whom about it, and why did each person's agent answer the way it did?")
    lines.append("    - What is e117's personality, and did their agent stay true to it all run?")
    lines.append("    - Was anyone placed into something their profile rules out? Who was left out, and why?")
    lines.append("    - Did the hub claim things about people that their profiles don't support?")
    lines.append("  Ask the AI to cite event numbers like [#560]: every one points to the verbatim record in")
    lines.append("  full_simulation.jsonl and full_transcript.txt in this run's folder.")
    lines.append("")
    lines.append("WHAT THE WORDS MEAN")
    lines.append("  hub          the Clawnly matchmaker (orchestrator), " + manifest["models"]["hub plan and resolve"] +
                 ". It plans groups and talks to each agent one to one.")
    lines.append("  agent        one emulated person's own AI, " + manifest["models"]["agents and final messages"] +
                 ". It knows only that person's profile and answers for them.")
    lines.append("               Agents never talk to each other. Each agent call is a fresh conversation: no memory.")
    lines.append("  break room   a pool code builds per activity and time of day: everyone free, interested, within")
    lines.append("               budget and not avoiding anything about it. The hub may only invite from it.")
    lines.append("  keenness     how much a person likes the activity's tags (likes are weighted 1-3).")
    lines.append("  round 1 / 2  round 1 asks everyone the plan proposed; round 2 asks only who the hub re-asks after")
    lines.append("               the resolve step (alternates for a no, people whose time changed).")
    lines.append("  yes/no/counter  an agent's answer; a counter proposes one change.")
    lines.append("  locked       code confirms a group once 2+ people said yes; dropped otherwise.")
    lines.append("  code showed the agent   what matchmaker.plan_checks found in the profile against the plan.")
    lines.append("")
    lines.append("SECTIONS")
    lines.append("  1. PEOPLE: personality prompts, before and after")
    lines.append("  2. CONVERSATIONS: every message, day by day and group by group")
    lines.append("  3. GROUPS: each group and its logic")
    lines.append("  4. TIMELINE: every event, one line each")
    lines.append("  5. WHAT OUR CHECKS FOUND (read last; skip it for an independent review)")


# ----- 2. the people ---------------------------------------------------------------------------

def _people(lines, initial, events, groups, final):
    _banner(lines, "1. PEOPLE: each emulated person's personality prompt (before) and what happened to them (after)")
    by_id = {}
    i = 0
    while i < len(initial):
        by_id[initial[i]["id"]] = initial[i]
        i += 1
    replies = _of(events, "agent_to_hub")
    placed = {}
    g = 0
    while g < len(groups):
        if groups[g]["status"] == "locked":
            f = 0
            while f < len(groups[g]["final_members"]):
                placed.setdefault(groups[g]["final_members"][f], []).append(groups[g])
                f += 1
        g += 1
    # the full prompt once; for everyone else only the part that is about them, when the rest matches
    first_shape = None
    if len(initial) > 0:
        lines.append("THE AGENT PROMPT IN FULL, exactly as " + initial[0]["id"] + "'s agent got it as its system prompt.")
        lines.append("Everyone's prompt has this exact wording; only the name and the part under 'TOLD YOU' differ.")
        lines.append("Code checked this for every person below; anyone whose prompt differs has it printed in full.")
        lines.append(THIN)
        lines.append(_indent(initial[0]["agent_system_prompt"]))
        lines.append(THIN)
        first_shape = _shape(initial[0]["agent_system_prompt"], initial[0])
    lines.append("")
    lines.append("BEFORE AND AFTER: nothing in Clawnly writes to a profile, and each agent call starts with no memory,")
    lines.append("so 'after' is the same profile, checked against the start for every person. What an agent says is")
    lines.append("conversation, not a saved change: each person's answers are listed under them, with event numbers.")
    lines.append("")
    i = 0
    while i < len(initial):
        p = initial[i]
        i += 1
        kids = "no kids at home"
        if p["kids_at_home"]:
            kids = "kids at home"
        lines.append(p["id"] + " | " + p["name"] + " | " + str(p["age"]) + " | " + p["archetype"] + " | " + p["area"] +
                     " | " + kids + " | budget " + p["budget"])
        lines.append("  BEFORE: what their agent was told (the personality prompt)")
        shape = _shape(p["agent_system_prompt"], p)
        if shape is not None and shape == first_shape:
            lines.append(_indent(_told_block(p["agent_system_prompt"]), "    "))
        else:
            lines.append("    (this prompt's wording differs from the one above, so here it is in full)")
            lines.append(_indent(p["agent_system_prompt"], "    "))
        lines.append("  WHAT THE HUB SAW WHEN PLANNING (likes only, plus avoids in runs after the fixes):")
        lines.append("    " + p["what_the_hub_sees"])
        if final.get(p["id"], {}).get("profile_changed") is False:
            lines.append("  AFTER: profile unchanged (checked against the start)")
        else:
            lines.append("  AFTER: profile CHANGED or unchecked; compare agents_initial.json with agents_final.json")
        mine = []
        r = 0
        while r < len(replies):
            if replies[r]["person"] == p["id"]:
                mine.append(replies[r])
            r += 1
        if len(mine) == 0:
            lines.append("    Never asked in this run, so placed nowhere.")
        k = 0
        while k < len(mine):
            e = mine[k]
            k += 1
            extra = ""
            if e["counter"]:
                extra = " (counter: " + e["counter"] + ")"
            lines.append("    " + _ref(e["seq"]) + " " + e["day"] + " " + e["group"] + " round " + str(e["round"]) + ": " +
                         e["answer"].upper() + extra + ' "' + e["text"] + '"')
        mine_placed = placed.get(p["id"], [])
        if len(mine_placed) == 0 and len(mine) > 0:
            lines.append("    Placed: nowhere.")
        k = 0
        while k < len(mine_placed):
            lines.append("    Placed: " + mine_placed[k]["group"] + " " + mine_placed[k]["activity_name"] + ", " +
                         mine_placed[k]["time_final"] + " " + _ref(mine_placed[k]["evidence"]["status_seq"]))
            k += 1
        lines.append("")


# ----- 3. the conversations --------------------------------------------------------------------

def _plan_lines(lines, call, people, compact=False):
    plan = extract_json((call.get("response") or {}).get("text") or "")
    seen = call["request"]["messages"][-1]["content"]
    if compact and "\nPEOPLE:" in seen:
        # the combined record prints each person's line once, in its people part, not once per day
        lines.append("  WHAT THE HUB SAW WHEN PLANNING (its exact input, built by code) " + _ref(call["seq"]) + ". Its PEOPLE")
        lines.append("  lines are left out here: each person's appears in the people part, under 'what the hub saw'.")
        lines.append(_indent(seen[:seen.index("\nPEOPLE:")], "    "))
    else:
        lines.append("  WHAT THE HUB SAW WHEN PLANNING (its exact input, built by code) " + _ref(call["seq"]))
        lines.append(_indent(seen, "    "))
    lines.append("")
    reasoning = _thinking(call)
    if reasoning:
        lines.append("  THE HUB'S REASONING (the API's summary of its thinking) " + _ref(call["seq"]))
        lines.append(_indent(reasoning, "    "))
        lines.append("")
    lines.append("  THE HUB'S PLAN " + _ref(call["seq"]))
    if not isinstance(plan, dict):
        lines.append("    (the reply couldn't be read as JSON; raw reply:)")
        lines.append(_indent((call.get("response") or {}).get("text"), "    "))
        return
    lines.append("    thoughts: " + str(plan.get("thoughts") or ""))
    planned = plan.get("groups") or []
    j = 0
    while j < len(planned):
        g = planned[j]
        j += 1
        if not isinstance(g, dict):
            continue
        members = []
        m = 0
        while m < len(g.get("members") or []):
            members.append(_name(people, str(g["members"][m])))
            m += 1
        alternates = []
        m = 0
        while m < len(g.get("alternates") or []):
            alternates.append(_name(people, str(g["alternates"][m])))
            m += 1
        lines.append("    - " + str(g.get("activity")) + ", " + str(g.get("part")) + ", " + str(g.get("time")) +
                     " | members: " + ", ".join(members) + " | alternates: " + (", ".join(alternates) or "none"))
        lines.append("      why: " + str(g.get("why") or ""))


def _resolve_lines(lines, call):
    res = extract_json((call.get("response") or {}).get("text") or "")
    lines.append("  RESOLVE STEP: the hub after every round-1 answer " + _ref(call["seq"]) + ". Its round-2 asks appear")
    lines.append("  inside each group above, marked round 2.")
    lines.append("    What it saw:")
    lines.append(_indent(call["request"]["messages"][-1]["content"], "      "))
    reasoning = _thinking(call)
    if reasoning:
        lines.append("    Its reasoning (thinking summary):")
        lines.append(_indent(reasoning, "      "))
    if not isinstance(res, dict):
        lines.append("    (the reply couldn't be read as JSON; raw reply:)")
        lines.append(_indent((call.get("response") or {}).get("text"), "      "))
        return
    lines.append("    thoughts: " + str(res.get("thoughts") or ""))
    decisions = res.get("groups") or []
    j = 0
    while j < len(decisions):
        d = decisions[j]
        j += 1
        if not isinstance(d, dict):
            continue
        asks = []
        a = 0
        while a < len(d.get("ask") or []):
            ask = d["ask"][a]
            a += 1
            if isinstance(ask, dict):
                asks.append(str(ask.get("id")) + ': "' + str(ask.get("message") or "") + '"')
        keep = "keep"
        if d.get("keep") is False:
            keep = "DROP"
        line = "    - " + str(d.get("id")) + ": " + keep + ", time " + str(d.get("time"))
        if len(asks) == 0:
            line = line + ", asks nobody"
        lines.append(line)
        a = 0
        while a < len(asks):
            lines.append("        asks " + asks[a])
            a += 1


def _code_found(call):
    # what code put in front of the agent, from the exact request
    content = call["request"]["messages"][-1]["content"]
    cut = content.find("What code found")
    if cut == -1:
        return ""
    text = content[cut:]
    nl = text.find("\n")
    return text[nl + 1:].strip()


def _conversations(lines, events, groups, people, days, compact=False):
    if not compact:
        _banner(lines, "2. CONVERSATIONS: every message between the hub and each agent, day by day")
    calls = _of(events, "model_call")
    d = 0
    while d < len(days):
        day = days[d]
        d += 1
        label = matchmaker.day_label(datetime.date.fromisoformat(day))
        lines.append(THIN)
        lines.append("DAY " + day + " (" + label + ")")
        lines.append(THIN)
        day_events = []
        i = 0
        while i < len(events):
            if events[i]["day"] == day:
                day_events.append(events[i])
            i += 1
        i = 0
        while i < len(day_events):
            e = day_events[i]
            i += 1
            if e["type"] in ["day_start", "day_skipped", "budget_stop"]:
                lines.append("  " + _ref(e["seq"]) + " " + str(e.get("text")))
            if e["type"] == "code_check" and e.get("group") is None:
                lines.append("  " + _ref(e["seq"]) + " CODE: " + e["text"])
        lines.append("")
        plan_call = None
        resolve_call = None
        i = 0
        while i < len(calls):
            if calls[i]["day"] == day and calls[i]["purpose"] == "matchmaker_plan":
                plan_call = calls[i]
            if calls[i]["day"] == day and calls[i]["purpose"] == "matchmaker_resolve":
                resolve_call = calls[i]
            i += 1
        if plan_call is not None:
            _plan_lines(lines, plan_call, people, compact)
            lines.append("")
        g = 0
        while g < len(groups):
            group = groups[g]
            g += 1
            if group["day"] != day:
                continue
            _group_conversation(lines, group, day_events, calls, people)
        if resolve_call is not None:
            _resolve_lines(lines, resolve_call)
            lines.append("")
        i = 0
        while i < len(day_events):
            e = day_events[i]
            i += 1
            if e["type"] == "day_end":
                lines.append("  " + _ref(e["seq"]) + " " + e["text"] + " Log check (three records of every call agree): " +
                             str(e["log_check"]["complete"]))
        lines.append("")


def _group_conversation(lines, group, day_events, calls, people):
    activity = catalog.get(group["activity"])
    lines.append("  GROUP " + group["id"] + ": " + activity["name"] + " at " + activity["where"] + ", " + group["part"] +
                 ", " + group["time_planned"] + " -> final " + group["time_final"] + " | outcome: " + group["status"].upper())
    i = 0
    while i < len(day_events):
        e = day_events[i]
        i += 1
        if e.get("group") != group["id"]:
            continue
        kind = e["type"]
        if kind == "hub_to_agent":
            lines.append("    " + _ref(e["seq"]) + " HUB -> " + _name(people, e["person"]) + " (round " + str(e["round"]) + "):")
            lines.append('        "' + e["text"] + '"')
            call = _agent_call(calls, e["day"], e["group"], e["person"], e["round"])
            if call is not None:
                lines.append("        code showed the agent " + _ref(call["seq"]) + ": " +
                             _code_found(call).replace("\n", " ").replace("  ", " "))
        elif kind == "agent_to_hub":
            extra = ""
            if e["counter"]:
                extra = " | counter: " + e["counter"]
            lines.append("    " + _ref(e["seq"]) + " " + _name(people, e["person"]) + "'s agent -> HUB: " + e["answer"].upper() + extra)
            lines.append('        "' + e["text"] + '"')
        elif kind == "system_note":
            lines.append("    " + _ref(e["seq"]) + " SYSTEM: " + e["text"])
        elif kind in ["code_check", "hub_decision"]:
            who = "CODE"
            if kind == "hub_decision":
                who = "HUB"
            lines.append("    " + _ref(e["seq"]) + " " + who + ": " + e["text"])
        elif kind == "group_time_changed":
            lines.append("    " + _ref(e["seq"]) + " TIME CHANGED: " + e["before"] + " -> " + e["after"])
    if group.get("headline") or group.get("final_messages"):
        lines.append("    FINAL MESSAGES " + _ref(group["evidence"]["message_call_seq"]) + " headline: " + str(group.get("headline")))
        messages = group.get("final_messages") or {}
        keys = list(messages.keys())
        k = 0
        while k < len(keys):
            lines.append("      to " + _name(people, keys[k]) + ': "' + str(messages[keys[k]]) + '"')
            k += 1
    lines.append("")


def _agent_call(calls, day, group, person, round_no):
    i = 0
    while i < len(calls):
        c = calls[i]
        if c["day"] == day and c["group"] == group and c["person"] == person and c["round"] == round_no and \
                c["purpose"] == "matchmaker_agent":
            return c
        i += 1
    return None


# ----- 4. the groups ---------------------------------------------------------------------------

def _shared(ids, people):
    holders = {}
    order = []
    i = 0
    while i < len(ids):
        person = people[ids[i]]
        j = 0
        while j < len(person["likes"]):
            tag = person["likes"][j]["tag"]
            if tag not in holders:
                holders[tag] = []
                order.append(tag)
            holders[tag].append(person["name"].split(" ")[0] + " " + str(person["likes"][j]["weight"]))
            j += 1
        i += 1
    out = []
    k = 0
    while k < len(order):
        if len(holders[order[k]]) >= 2:
            out.append(order[k].replace("_", " ") + " (" + ", ".join(holders[order[k]]) + ")")
        k += 1
    return out


def _groups(lines, groups, people, compact=False):
    if not compact:
        _banner(lines, "3. GROUPS: each group, who is in it, why, and how every person answered")
    g = 0
    while g < len(groups):
        group = groups[g]
        g += 1
        activity = catalog.get(group["activity"])
        lines.append(group["group"] + " | " + group["status"].upper() + _drop(group))
        lines.append("  Activity: " + group["activity_name"] + " at " + group["where"] + " | cost " + group["cost"] + " | " +
                     group["part"] + " | final time " + group["time_final"] + " (planned " + group["time_planned"] + ")" +
                     _fixed(group))
        lines.append("  The activity is about: " + ", ".join(_tag_words(activity)))
        lines.append("  The hub's reason " + _ref(group["evidence"]["proposed_seq"]) + ": " + group["why_hub_chose_it"])
        alternates = []
        a = 0
        while a < len(group["alternates"]):
            alternates.append(_name(people, group["alternates"][a]))
            a += 1
        lines.append("  Alternates named: " + (", ".join(alternates) or "none"))
        lines.append("  Final members:")
        f = 0
        while f < len(group["final_members"]):
            p = people[group["final_members"][f]]
            f += 1
            likes = []
            k = 0
            while k < len(p["likes"]):
                likes.append(p["likes"][k]["tag"].replace("_", " ") + " " + str(p["likes"][k]["weight"]))
                k += 1
            lines.append("    " + p["id"] + " " + p["name"] + ", " + str(p["age"]) + ", " + p["archetype"] + ", " + p["area"] +
                         " | likes " + ", ".join(likes))
        shared = _shared(group["final_members"], people)
        lines.append("  Likes the final members share: " + ("; ".join(shared) or "none"))
        lines.append("  Overlap of likes (0-1): " + str(group["signals"]["shared_likes_overlap"]) + " | age spread: " +
                     str(group["signals"]["age_spread"]) + " years")
        if compact:
            lines.append("  Everyone asked, and how they answered (each reply in full is under CONVERSATIONS):")
        else:
            lines.append("  Everyone asked, and how they answered:")
        m = 0
        while m < len(group["members"]):
            member = group["members"][m]
            m += 1
            k = 0
            while k < len(member["answers"]):
                ans = member["answers"][k]
                k += 1
                extra = ""
                if ans["counter"]:
                    extra = " (counter: " + ans["counter"] + ")"
                said = ' "' + ans["said"] + '"'
                if compact:
                    # the combined record already has every reply in full, in the conversations
                    said = ""
                lines.append("    " + _ref(ans["reply_seq"]) + " " + _name(people, member["id"]) + ", round " + str(ans["round"]) +
                             " at " + str(ans["group_time_at_ask"]) + ": " + ans["answer"].upper() + extra + said)
            checks = member["code_checks_at_final_time"]
            if len(checks) > 0:
                lines.append("        code checks at the final time: " + " ".join(checks))
        lines.append("")


def _drop(group):
    if group["status"] == "dropped" and group.get("drop_reason"):
        return " (" + group["drop_reason"] + ")"
    return ""


def _fixed(group):
    if group["fixed_event"]:
        return ", a fixed-time event"
    return ""


def _tag_words(activity):
    out = []
    i = 0
    while i < len(activity["tags"]):
        out.append(activity["tags"][i].replace("_", " "))
        i += 1
    return out


# ----- 5. the timeline -------------------------------------------------------------------------

# the timeline cuts messages short: section 2 has every one in full under the same event number
SNIPPET = 100


def _short(text):
    text = str(text or "").replace("\n", " ")
    if len(text) <= SNIPPET:
        return text
    return text[:SNIPPET].rstrip() + "..."


def _timeline_line(e, people):
    kind = e["type"]
    head = _ref(e["seq"]) + " " + e["t"][11:19] + " " + str(e["day"] or "")
    if kind == "model_call":
        usage = e.get("usage") or {}
        who = ""
        if e.get("person"):
            who = " for " + _name(people, e["person"])
        if e.get("group"):
            who = who + " in " + e["group"]
        line = head + " CLAUDE CALL " + str(e["purpose"]) + who + " | " + str(e["model"]) + " | " + \
            str(usage.get("input_tokens")) + " in, " + str(usage.get("output_tokens")) + " out | $" + str(e.get("cost")) + \
            " | " + str(e.get("ms")) + " ms"
        if e.get("error"):
            line = line + " | ERROR " + e["error"]
        return line
    if kind == "agent_init":
        return head + " AGENT READY " + _name(people, e["person"])
    if kind == "hub_to_agent":
        return head + " HUB -> " + _name(people, e["person"]) + " (" + e["group"] + ", round " + str(e["round"]) + "): " + _short(e["text"])
    if kind == "agent_to_hub":
        return head + " " + _name(people, e["person"]) + " -> HUB (" + e["group"] + "): " + e["answer"].upper() + ". " + _short(e["text"])
    if kind == "group_proposed":
        return head + " GROUP PROPOSED " + e["group"] + ": " + e["activity"] + " " + e["part"] + " " + e["time"] + \
            " | members " + ", ".join(e["members"]) + " | alternates " + (", ".join(e["alternates"]) or "none")
    if kind == "member_state":
        return head + " STATE " + e["group"] + " " + _name(people, e["person"]) + ": " + e["before"] + " -> " + e["after"]
    if kind == "member_added":
        return head + " STATE " + e["group"] + " " + _name(people, e["person"]) + " added (" + e["after"] + ")"
    if kind == "group_status":
        return head + " GROUP " + e["group"] + ": " + e["before"] + " -> " + e["after"] + " | final " + ", ".join(e["final"])
    if kind == "group_time_changed":
        return head + " TIME " + e["group"] + ": " + e["before"] + " -> " + e["after"]
    if kind == "model_retry":
        return head + " RETRY " + str(e["purpose"]) + " attempt " + str(e["attempt"]) + ": " + e["error"]
    if kind == "day_end":
        return head + " DAY END " + e["text"] + " Log check complete: " + str(e["log_check"]["complete"])
    if kind == "run_start":
        return head + " RUN START stage " + e["stage"] + ", " + str(e["people"]) + " people, days " + ", ".join(e["days"])
    label = kind.upper().replace("_", " ")
    if e.get("frm"):
        label = label + " (" + e["frm"] + ")"
    group = ""
    if e.get("group"):
        group = " [" + e["group"] + "]"
    return head + " " + label + group + ": " + _short(e.get("text"))


def _timeline(lines, events, people):
    _banner(lines, "4. TIMELINE: every event in order, one line each (messages cut short; section 2 has them in full)")
    i = 0
    while i < len(events):
        lines.append(_timeline_line(events[i], people))
        i += 1


# ----- 6. what our checks found ------------------------------------------------------------------

def _checks(lines, run_dir, compact=False):
    if not compact:
        _banner(lines, "5. WHAT OUR CHECKS FOUND (read last; skip it if you want a fresh, independent review)")
    mech = _read(run_dir, "audit_mechanical.json")
    ai = _read(run_dir, "audit_ai.json")
    if mech is None and ai is None:
        lines.append("This run hasn't been audited yet (orchestration_audit.py).")
        return
    if mech is not None:
        lines.append("RULE CHECKS IN CODE (reproducible): " + str(len(mech["findings"])) + " findings")
        i = 0
        while i < len(mech["findings"]):
            f = mech["findings"][i]
            i += 1
            refs = []
            k = 0
            while k < len(f["evidence"]):
                if f["evidence"][k] is not None:
                    refs.append(_ref(f["evidence"][k]))
                k += 1
            lines.append("  - " + f["severity"].upper() + ", " + f["check"] + ": " + f["what"] + " " + " ".join(refs))
        if len(mech["findings"]) == 0:
            lines.append("  none")
        lines.append("")
    if ai is not None:
        lines.append("INDEPENDENT AI AUDIT by " + ai["auditor"] + " (" + ai["sampling"] + ")")
        i = 0
        while i < len(ai["days"]):
            lines.append("  DAY " + ai["days"][i]["day"] + " verdict " + str(ai["days"][i]["verdict"]) + ": " + str(ai["days"][i]["summary"]))
            i += 1
        i = 0
        while i < len(ai["groups"]):
            lines.append("  " + ai["groups"][i]["group"] + " verdict " + str(ai["groups"][i]["verdict"]) + ": " + str(ai["groups"][i]["summary"]))
            i += 1
        lines.append("  Findings it backed with evidence:")
        i = 0
        while i < len(ai["kept"]):
            f = ai["kept"][i]
            i += 1
            refs = []
            k = 0
            while k < len(f["evidence"]):
                refs.append(_ref(f["evidence"][k]))
                k += 1
            lines.append("  - " + f["severity"].upper() + ", " + f["kind"] + ", " + ", ".join(_strings(f["groups"])) + ": " +
                         f["what"] + " " + " ".join(refs))
        if len(ai["failures"]) > 0:
            lines.append("  Not audited: " + "; ".join(ai["failures"]))


def _strings(items):
    out = []
    i = 0
    while i < len(items):
        out.append(str(items[i]))
        i += 1
    return out


# ----- putting it together ---------------------------------------------------------------------

def dump(run_dir):
    # the whole run as one readable text; returns it
    manifest = _read(run_dir, "run_manifest.json")
    initial = _read(run_dir, "agents_initial.json")
    groups = _read(run_dir, "groups_generated.json")
    events = _events(run_dir)
    people = {}
    i = 0
    while i < len(initial):
        people[initial[i]["id"]] = initial[i]
        i += 1
    lines = []
    final = {}
    after = _read(run_dir, "agents_final.json") or []
    i = 0
    while i < len(after):
        final[after[i]["id"]] = after[i]
        i += 1
    _header(lines, manifest)
    _people(lines, initial, events, groups, final)
    _conversations(lines, events, groups, people, manifest["days"])
    _groups(lines, groups, people)
    _timeline(lines, events, people)
    _checks(lines, run_dir)
    lines.append("")
    lines.append(RULE)
    lines.append("END OF " + manifest["sim_id"])
    lines.append(RULE)
    return "\n".join(lines) + "\n"


def write(run_dir):
    path = os.path.join(run_dir, "run_dump.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(dump(run_dir))
    return path


def write_all(out_path, run_dirs):
    # several runs in one file, each complete, behind a short index
    parts = []
    index = ["CLAWNLY ORCHESTRATION RUNS: " + str(len(run_dirs)) + " runs in one file", "",
             "Each run below is complete on its own (people, conversations, groups, timeline, checks).", ""]
    i = 0
    while i < len(run_dirs):
        manifest = _read(run_dirs[i], "run_manifest.json")
        index.append("  " + str(i + 1) + ". " + manifest["sim_id"] + ": " + str(manifest["people"]) + " people, " +
                     ", ".join(manifest["days"]) + ", " + str(manifest["groups_locked"]) + " groups locked")
        parts.append(dump(run_dirs[i]))
        i += 1
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(index) + "\n\n" + "\n".join(parts))
    return out_path


# ----- the combined record: the reports and every run in one readable file ------------------------

STAGE_LETTER = {"smoke": "S", "pilot": "P", "town": "T"}
STAGE_WORDS = {"smoke": "smoke test", "pilot": "pilot", "town": "whole town"}


def _aliases(manifests):
    # S, P1, P2, T1, T2...: a letter per stage, numbered when a stage ran more than once
    counts = {}
    i = 0
    while i < len(manifests):
        stage = manifests[i]["stage"]
        counts[stage] = counts.get(stage, 0) + 1
        i += 1
    seen = {}
    out = []
    i = 0
    while i < len(manifests):
        stage = manifests[i]["stage"]
        seen[stage] = seen.get(stage, 0) + 1
        letter = STAGE_LETTER.get(stage, stage[:1].upper())
        if counts[stage] > 1:
            letter = letter + str(seen[stage])
        out.append(letter)
        i += 1
    return out


def _load_run(run_dir, alias):
    manifest = _read(run_dir, "run_manifest.json")
    initial = _read(run_dir, "agents_initial.json")
    people = {}
    i = 0
    while i < len(initial):
        people[initial[i]["id"]] = initial[i]
        i += 1
    final = {}
    after = _read(run_dir, "agents_final.json") or []
    i = 0
    while i < len(after):
        final[after[i]["id"]] = after[i]
        i += 1
    return {"alias": alias, "dir": run_dir, "manifest": manifest, "initial": initial, "people": people,
            "final": final, "events": _events(run_dir), "groups": _read(run_dir, "groups_generated.json")}


def _demote(markdown, levels):
    # a report's own headings sit under the record's part headings; its title line goes
    out = []
    rows = markdown.splitlines()
    i = 0
    while i < len(rows):
        row = rows[i]
        i += 1
        if i == 1 and row.startswith("# "):
            continue
        if row.startswith("#"):
            row = "#" * levels + row
        out.append(row)
    return "\n".join(out).strip()


def _fence(lines, text):
    lines.append("```text")
    lines.append(text.rstrip("\n"))
    lines.append("```")


def _distinct(runs, value_of):
    # [(value, [aliases])] in first-seen order, so a difference between runs shows up once
    values = []
    owners = []
    i = 0
    while i < len(runs):
        value = value_of(runs[i])
        i += 1
        if value is None:
            continue
        k = 0
        found = -1
        while k < len(values):
            if values[k] == value:
                found = k
            k += 1
        if found == -1:
            values.append(value)
            owners.append([runs[i - 1]["alias"]])
        else:
            owners[found].append(runs[i - 1]["alias"])
    out = []
    k = 0
    while k < len(values):
        out.append((values[k], owners[k]))
        k += 1
    return out


def _book_intro(lines, runs):
    lines.append("# Run Clawnly with real AI: the full record")
    lines.append("")
    lines.append("This one file holds everything from the live tests of Clawnly's AI matchmaker on 29 Oct 2026: the plain answer,")
    lines.append("how the system works, what the audit found, a guide to checking it yourself, and then the raw evidence:")
    lines.append("every person's personality, every message between the matchmaker and each person's AI agent, and every group.")
    lines.append("")
    lines.append("**To understand it**, read Parts 1 to 3. **To evaluate it yourself**, start with Part 4. For a review that isn't")
    lines.append("steered by our conclusions, skip Parts 1 and 3 and work from Parts 5 to 7.")
    lines.append("")
    lines.append("**How to cite.** Every event has a run and a number: **T1 #560** is event 560 of run T1. Run letters are in Part 5.")
    lines.append("Inside a run's part, `[#560]` means that run's event 560. The same numbers are `seq` in each run's")
    lines.append("`full_simulation.jsonl` and `[000560]` in its `full_transcript.txt`, which hold every prompt and reply verbatim.")
    lines.append("")
    lines.append("## Contents")
    lines.append("")
    lines.append("- Part 1. The short answer")
    lines.append("- Part 2. How Run Clawnly works")
    lines.append("- Part 3. What the audit found")
    lines.append("- Part 4. How to evaluate this yourself")
    lines.append("- Part 5. The runs at a glance")
    lines.append("- Part 6. The people: every personality, and what happened to each person in every run")
    i = 0
    while i < len(runs):
        lines.append("- Part 7." + str(i + 1) + ". Run " + runs[i]["alias"] + ": " + _run_title(runs[i]))
        i += 1
    lines.append("- Part 8. Where the raw records are")


def _run_title(run):
    manifest = run["manifest"]
    days = []
    i = 0
    while i < len(manifest["days"]):
        days.append(matchmaker.day_label(datetime.date.fromisoformat(manifest["days"][i])))
        i += 1
    # the agent's limit line came with the audit fixes, so the run's own prompt says which code it ran
    when = "before the fixes"
    if "is a limit they set" in run["initial"][0]["agent_system_prompt"]:
        when = "after the fixes"
    return STAGE_WORDS.get(manifest["stage"], manifest["stage"]) + ", " + str(manifest["people"]) + " people, " + \
        ", ".join(days) + ", " + when


def _guide(lines):
    lines.append("## Part 4. How to evaluate this yourself")
    lines.append("")
    lines.append("Paste or upload this file into any AI chat, or read it, and work through the questions. Ask for event numbers")
    lines.append("with every answer, and check a few against Part 7.")
    lines.append("")
    lines.append("**One group** (Part 7, under GROUPS, and the group's messages under CONVERSATIONS)")
    lines.append("- What is this group, and does it make sense for these people? Do they share more than the activity?")
    lines.append("- Was anyone placed who doesn't care about the main activity? Was a better-fitting person left out?")
    lines.append("- Does the hub's stated reason match the members' profiles? Do the final messages claim only true things?")
    lines.append("")
    lines.append("**One person** (Part 6)")
    lines.append("- What is this person like, from the prompt their agent got?")
    lines.append("- Did their agent stay true to it in every answer, across days and runs? Did it invent anything about them?")
    lines.append("- Did they get a fair chance to be invited?")
    lines.append("")
    lines.append("**The matchmaker** (Part 7, the plan and resolve steps)")
    lines.append("- Did the plan follow what it was shown? Did it handle declines and counter-offers well?")
    lines.append("- Did it spread invitations across people, or keep choosing the same ones?")
    lines.append("")
    lines.append("**The rules** (code enforces these; check they held)")
    lines.append("- Nobody placed while busy, over budget, into something they dislike or avoid, twice in a day, or at a time")
    lines.append("  they didn't agree to. A group locks only with 2 or more yes.")
    lines.append("")
    lines.append("**Before and after the fixes**: compare P1 with P2 (the same 30 people and days) and T1 with T2 (Saturday).")


def _glance(lines, runs):
    lines.append("## Part 5. The runs at a glance")
    lines.append("")
    lines.append("All five runs use the same seeded town of 200 emulated Black Diamond neighbors; the smaller runs use a subset.")
    lines.append("The people, calendars and activity pools are identical every run. Only the models' replies vary.")
    lines.append("")
    lines.append("| Run | Folder | Stage | People | Days | Groups locked | Invitations | Yes / no / counter | Cost |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    i = 0
    while i < len(runs):
        run = runs[i]
        i += 1
        m = run["manifest"]
        replies = _of(run["events"], "agent_to_hub")
        tally = {"yes": 0, "no": 0, "counter": 0}
        k = 0
        while k < len(replies):
            tally[replies[k]["answer"]] = tally.get(replies[k]["answer"], 0) + 1
            k += 1
        lines.append("| " + run["alias"] + " | `" + m["sim_id"] + "` | " + _run_title(run).split(",")[0] + " | " + str(m["people"]) +
                     " | " + ", ".join(m["days"]) + " | " + str(m["groups_locked"]) + " / " + str(m["groups_proposed"]) + " | " +
                     str(len(_of(run["events"], "hub_to_agent"))) + " | " + str(tally["yes"]) + " / " + str(tally["no"]) + " / " +
                     str(tally["counter"]) + " | $" + str(round(m["spent_usd"], 2)) + " |")


def _people_book(lines, runs):
    lines.append("## Part 6. The people")
    lines.append("")
    lines.append("Each emulated person once: what their agent was told (their personality prompt), what the matchmaker saw")
    lines.append("about them, and then what happened to them in every run they were part of.")
    lines.append("")
    lines.append("**Before and after.** Nothing in Clawnly writes to a profile, and each agent call starts with no memory, so a")
    lines.append("person's profile after a run is the one they started with. Code checked that for every person in every run;")
    lines.append("any exception is marked. What an agent says is conversation, not a saved change.")
    lines.append("")
    lines.append("### The agent prompt, in full")
    lines.append("")
    lines.append("Every agent got the same wording around its own person's profile. The wording changed once, with the fixes.")
    lines.append("Placeholders stand for the person's name and profile.")
    lines.append("")
    versions = _distinct(runs, lambda run: _shape(run["initial"][0]["agent_system_prompt"], run["initial"][0]))
    v = 0
    while v < len(versions):
        lines.append("**Wording used in runs " + ", ".join(versions[v][1]) + ":**")
        lines.append("")
        _fence(lines, versions[v][0])
        lines.append("")
        v += 1
    if len(versions) == 2:
        old = versions[0][0].splitlines()
        new = versions[1][0].splitlines()
        added = []
        k = 0
        while k < len(new):
            if new[k] not in old:
                added.append(new[k])
            k += 1
        lines.append("The difference: runs " + ", ".join(versions[1][1]) + " add the line")
        k = 0
        while k < len(added):
            lines.append("> " + added[k])
            k += 1
        lines.append("")
    ids = []
    known = {}
    i = 0
    while i < len(runs):
        k = 0
        while k < len(runs[i]["initial"]):
            pid = runs[i]["initial"][k]["id"]
            if pid not in known:
                known[pid] = True
                ids.append(pid)
            k += 1
        i += 1
    ids.sort()
    lines.append("### Every person (" + str(len(ids)) + ")")
    lines.append("")
    i = 0
    while i < len(ids):
        _person_book(lines, ids[i], runs)
        i += 1


def _person_book(lines, pid, runs):
    mine = []
    i = 0
    while i < len(runs):
        if pid in runs[i]["people"]:
            mine.append(runs[i])
        i += 1
    p = mine[0]["people"][pid]
    kids = "no kids at home"
    if p["kids_at_home"]:
        kids = "kids at home"
    lines.append("#### " + pid + " " + p["name"] + " · " + str(p["age"]) + " · " + p["archetype"] + " · " + p["area"] + " · " + kids +
                 " · budget " + p["budget"])
    lines.append("")
    body = []
    profiles = _distinct(mine, lambda run: _told_block(run["people"][pid]["agent_system_prompt"]))
    k = 0
    while k < len(profiles):
        label = "What their agent was told"
        if len(profiles) > 1:
            label = label + " in runs " + ", ".join(profiles[k][1])
        body.append(label + ":")
        body.append(_indent(profiles[k][0], "  "))
        k += 1
    hub = _distinct(mine, lambda run: run["people"][pid]["what_the_hub_sees"])
    if len(hub) == 2 and hub[1][0].startswith(hub[0][0]):
        # after the fixes the hub's line only gained what the person avoids
        body.append("What the matchmaker saw, runs " + ", ".join(hub[1][1]) + ": " + hub[1][0])
        body.append("  (runs " + ", ".join(hub[0][1]) + ": the same, without '" + hub[1][0][len(hub[0][0]):].strip("; ") + "')")
    else:
        k = 0
        while k < len(hub):
            body.append("What the matchmaker saw, runs " + ", ".join(hub[k][1]) + ": " + hub[k][0])
            k += 1
    k = 0
    while k < len(mine):
        run = mine[k]
        k += 1
        changed = run["final"].get(pid, {}).get("profile_changed")
        mark = ""
        if changed is not False:
            mark = " (profile CHANGED or unchecked)"
        replies = []
        events = run["events"]
        e = 0
        while e < len(events):
            if events[e]["type"] == "agent_to_hub" and events[e]["person"] == pid:
                replies.append(events[e])
            e += 1
        if len(replies) == 0:
            body.append(run["alias"] + ": in the run, never asked" + mark)
            continue
        body.append(run["alias"] + ":" + mark)
        r = 0
        while r < len(replies):
            x = replies[r]
            r += 1
            extra = ""
            if x["counter"]:
                extra = " (counter: " + x["counter"] + ")"
            body.append("  " + run["alias"] + " #" + str(x["seq"]) + " " + x["day"] + " " + x["group"] + " round " + str(x["round"]) + ": " +
                        x["answer"].upper() + extra + ' "' + x["text"] + '"')
        placed = 0
        g = 0
        while g < len(run["groups"]):
            group = run["groups"][g]
            g += 1
            if group["status"] == "locked" and pid in group["final_members"]:
                placed += 1
                body.append("  placed: " + group["group"] + " " + group["activity_name"] + ", " + group["time_final"] +
                            " (" + run["alias"] + " #" + str(group["evidence"]["status_seq"]) + ")")
        if placed == 0:
            body.append("  placed: nowhere")
    _fence(lines, "\n".join(body))
    lines.append("")


def _run_book(lines, number, run):
    m = run["manifest"]
    lines.append("## Part 7." + str(number) + ". Run " + run["alias"] + ": " + _run_title(run))
    lines.append("")
    lines.append("Folder `" + m["sim_id"] + "`. " + str(m["groups_locked"]) + " of " + str(m["groups_proposed"]) + " groups locked, $" +
                 str(round(m["spent_usd"], 2)) + ". Event numbers below are this run's, so `[#n]` here is **" + run["alias"] + " #n**.")
    lines.append("Replies came from: " + m["replies_from"] + ".")
    lines.append("")
    lines.append("### Conversations, day by day")
    lines.append("")
    body = []
    _conversations(body, run["events"], run["groups"], run["people"], m["days"], True)
    _fence(lines, "\n".join(body))
    lines.append("")
    lines.append("### Groups, with their logic")
    lines.append("")
    body = []
    _groups(body, run["groups"], run["people"], True)
    _fence(lines, "\n".join(body))
    lines.append("")
    lines.append("### What our checks found for this run")
    lines.append("")
    body = []
    _checks(body, run["dir"], True)
    _fence(lines, "\n".join(body))
    lines.append("")


def _records(lines, runs):
    lines.append("## Part 8. Where the raw records are")
    lines.append("")
    lines.append("Everything above is drawn from these files in `simulation_results/`, which keep every prompt and reply verbatim.")
    lines.append("")
    lines.append("| Run | Folder | Verbatim log | Readable transcript | One-run text |")
    lines.append("|---|---|---|---|---|")
    i = 0
    while i < len(runs):
        lines.append("| " + runs[i]["alias"] + " | `" + runs[i]["manifest"]["sim_id"] + "` | `full_simulation.jsonl` | "
                     "`full_transcript.txt` | `run_dump.txt` |")
        i += 1
    lines.append("")
    lines.append("Also there: `AUDIT_REPORT.md`, `EXECUTIVE_SUMMARY.md`, `architecture_summary.md`, `README.md` (how to reproduce),")
    lines.append("`spend_ledger.json` (every paid step) and `REPORT.html` (a one-page visual summary).")


def book(run_dirs, docs_dir):
    # the reports and every run, deduplicated where runs share people, as one Markdown text
    manifests = []
    i = 0
    while i < len(run_dirs):
        manifests.append(_read(run_dirs[i], "run_manifest.json"))
        i += 1
    aliases = _aliases(manifests)
    runs = []
    i = 0
    while i < len(run_dirs):
        runs.append(_load_run(run_dirs[i], aliases[i]))
        i += 1
    lines = []
    _book_intro(lines, runs)
    parts = [["Part 1. The short answer", "EXECUTIVE_SUMMARY.md"], ["Part 2. How Run Clawnly works", "architecture_summary.md"],
             ["Part 3. What the audit found", "AUDIT_REPORT.md"]]
    k = 0
    while k < len(parts):
        lines.append("")
        lines.append("## " + parts[k][0])
        lines.append("")
        path = os.path.join(docs_dir, parts[k][1])
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                lines.append(_demote(f.read(), 1))
        else:
            lines.append("(" + parts[k][1] + " isn't there yet.)")
        k += 1
    lines.append("")
    _guide(lines)
    lines.append("")
    _glance(lines, runs)
    lines.append("")
    _people_book(lines, runs)
    i = 0
    while i < len(runs):
        _run_book(lines, i + 1, runs[i])
        i += 1
    _records(lines, runs)
    return "\n".join(lines) + "\n"


def write_book(out_path, run_dirs, docs_dir):
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(book(run_dirs, docs_dir))
    return out_path


def main(argv):
    if len(argv) >= 4 and argv[1] == "--book":
        # --book <out file> <run folder> ...: the reports next to the out file, then every run
        print(write_book(argv[2], argv[3:], os.path.dirname(os.path.abspath(argv[2]))))
        return 0
    if len(argv) < 2:
        print("usage: run_dump.py <run folder> [<run folder> ...] | --all <out file> <run folder> ...")
        return 2
    if argv[1] == "--all":
        print(write_all(argv[2], argv[3:]))
        return 0
    i = 1
    while i < len(argv):
        print(write(argv[i]))
        i += 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
