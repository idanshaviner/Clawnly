"""One readable file to evaluate every group the live AI matchmaker made.

simulation_results/CLAWNLY_MATCH_REVIEW.md, built from the saved run folders with no API
calls. It reads top to bottom (or goes into any AI chat):

  1. the short answer, and how to evaluate a group
  2. every group at a glance, in one table
  3. every group as one card: who is in it (age, kind of week, what they like about the
     activity, what they avoid, how their agent answered), the matchmaker's reason and each
     agent's reply word for word, how it ended, factual things to look at, and the
     independent AI review where one was run
  4. where the full records are

Only groups that locked count; failed or interrupted runs are listed, not mixed in. The
matchmaker's pitches and the final messages stay in each run's run_dump.txt, so a card stays
short enough to judge at a glance.

    .venv/bin/python src/match_book.py
"""

# first: it points CLAWNLY_DB_PATH at the simulation database before db.py is imported
import orchestration_sim

import datetime
import json
import os
import sys

import catalog
import match_eval
import orchestration_audit
import run_dump


OUT_NAME = "CLAWNLY_MATCH_REVIEW.md"
LEVEL = {3: "loves", 2: "likes", 1: "is up for"}
STAGE_WORDS = {"smoke": "smoke test", "pilot": "pilot", "town": "whole town", "review": "whole town, one day"}
AGE_GAP = 40


def _read(folder, name):
    path = os.path.join(folder, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.loads(f.read())


def _cell(text):
    # a table cell: one line, and no bar that would split the column
    return str(text).replace("|", "/").replace("\n", " ").strip()


def _first(name):
    return name.split(" ")[0]


def _words(tag):
    return tag.replace("_", " ")


def _day(iso):
    day = datetime.date.fromisoformat(iso)
    return day.strftime("%a ") + str(day.day) + day.strftime(" %b")


def _plural(n, one, many):
    if n == 1:
        return one
    return many


def _and(items):
    if len(items) == 0:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


# ----- gathering the runs and their groups ------------------------------------------------------

def gather(root):
    # (runs that made groups, runs that didn't), in folder order
    names = []
    if os.path.isdir(root):
        names = sorted(os.listdir(root))
    usable = []
    skipped = []
    i = 0
    while i < len(names):
        folder = os.path.join(root, names[i])
        i += 1
        if not names[i - 1].startswith("run_") or not os.path.isdir(folder):
            continue
        manifest = _read(folder, "run_manifest.json")
        groups = _read(folder, "groups_generated.json")
        if manifest is None:
            skipped.append({"folder": names[i - 1], "why": "interrupted before it finished (no manifest)"})
            continue
        locked = 0
        g = 0
        while g < len(groups or []):
            if groups[g]["status"] == "locked":
                locked += 1
            g += 1
        if locked == 0:
            why = "made no groups"
            if manifest["days_run"] and not manifest["days_run"][0]["status"].startswith("done"):
                why = "failed: " + _failure(folder)
            skipped.append({"folder": names[i - 1], "why": why})
            continue
        usable.append(folder)
    return usable, skipped


def _failure(folder):
    events = run_dump._events(folder)
    i = 0
    while i < len(events):
        if events[i]["type"] == "system" and events[i].get("text"):
            return events[i]["text"]
        i += 1
    return "see its full_simulation.jsonl"


def _load(folder, alias):
    run = orchestration_audit.load(folder)
    orchestration_audit._add_first_proposals(run)
    run["alias"] = alias
    run["folder"] = os.path.basename(os.path.normpath(folder))
    run["findings"] = orchestration_audit.mechanical(run)
    fable = {}
    ai = _read(folder, "audit_ai.json")
    if ai is not None:
        i = 0
        while i < len(ai["groups"]):
            fable[ai["groups"][i]["group"]] = ai["groups"][i]
            i += 1
    run["fable"] = fable
    initial = _read(folder, "agents_initial.json")
    run["fixed"] = "is a limit they set" in initial[0]["agent_system_prompt"]
    return run


def _run_words(run):
    m = run["manifest"]
    when = "before the fixes"
    if run["fixed"]:
        when = "after the fixes"
    days = []
    i = 0
    while i < len(m["days"]):
        days.append(_day(m["days"][i]))
        i += 1
    return STAGE_WORDS.get(m["stage"], m["stage"]) + ", " + str(m["people"]) + " people, " + ", ".join(days) + ", " + when


# ----- one group ---------------------------------------------------------------------------------

def _liked(person, activity):
    out = []
    i = 0
    while i < len(person["likes"]):
        if person["likes"][i]["tag"] in activity["tags"]:
            out.append(LEVEL[person["likes"][i]["weight"]] + " " + _words(person["likes"][i]["tag"]))
        i += 1
    return out


def _into_main(person, activity):
    return activity["tags"][0] in match_eval._liked(person)


def _answer_summary(member, final):
    # what the agent ended on, and whether the person is in the group
    answers = member["answers"]
    if len(answers) == 0:
        return "not asked"
    words = []
    i = 0
    while i < len(answers):
        words.append(answers[i]["answer"])
        i += 1
    text = words[0]
    if len(words) > 1:
        text = " then ".join(words)
    text = text[0].upper() + text[1:]
    if member["id"] in final:
        return text + " · in the group"
    return text + " · not in the group"


def _flags(run, group, by_id, repeats):
    activity = catalog.get(group["activity"])
    main = _words(activity["tags"][0])
    out = []
    final = group["final_members"]
    i = 0
    while i < len(final):
        p = by_id[final[i]]
        i += 1
        if not _into_main(p, activity):
            tags = []
            k = 0
            while k < len(p["likes"]):
                if p["likes"][k]["tag"] in activity["tags"]:
                    tags.append(_words(p["likes"][k]["tag"]))
                k += 1
            reason = "a side interest"
            if len(tags) > 0:
                reason = _and(tags)
            out.append(_first(p["name"]) + " is here for " + reason + ", not " + main + ".")
    findings = run["findings"]
    i = 0
    while i < len(findings):
        f = findings[i]
        i += 1
        if group["group"] in f["groups"] and f["severity"] != "info":
            out.append("Check (" + f["severity"] + "): " + f["what"])
    ages = []
    i = 0
    while i < len(final):
        ages.append(by_id[final[i]]["age"])
        i += 1
    if len(ages) > 0 and max(ages) - min(ages) >= AGE_GAP:
        out.append("Ages " + str(min(ages)) + " to " + str(max(ages)) + ".")
    if len(final) == 2:
        out.append("Only two people.")
    if group["time_planned"] != group["time_final"]:
        out.append("The time moved from " + group["time_planned"] + " to " + group["time_final"] + ".")
    if len(repeats) > 0:
        out.append("The same activity and people also met in " + _and(repeats) + ".")
    return out


def _card(lines, number, run, group, by_id, repeats):
    activity = catalog.get(group["activity"])
    final = group["final_members"]
    lines.append("#### " + str(number) + ". " + group["activity_name"] + " · " + _day(group["day"]) + " · " + group["time_final"] +
                 " · " + str(len(final)) + " people")
    lines.append("")
    lines.append("Run " + run["alias"] + " · " + group["where"] + " · " + group["cost"] + " cost · about " +
                 _and(_tag_words(activity)) + " · match `" + run["folder"] + "/" + group["group"] + "`")
    lines.append("")
    lines.append("| Person | Age · week | What they like about it | Avoids | Their agent's answer |")
    lines.append("|---|---|---|---|---|")
    m = 0
    while m < len(group["members"]):
        member = group["members"][m]
        m += 1
        p = by_id[member["id"]]
        week = p["archetype"]
        if p["kids_at_home"]:
            week = week + ", kids at home"
        liked = _liked(p, activity)
        likes = ", ".join(liked)
        if not _into_main(p, activity):
            likes = likes + " (side interest)"
        avoid = []
        k = 0
        while k < len(p["avoid"]):
            avoid.append(_words(p["avoid"][k]))
            k += 1
        name = p["name"] + " (" + p["id"] + ")"
        lines.append("| " + _cell(name) + " | " + str(p["age"]) + " · " + _cell(week) + " | " + _cell(likes or "-") + " | " +
                     _cell(", ".join(avoid) or "-") + " | " + _cell(_answer_summary(member, final)) + " |")
    lines.append("")
    lines.append("**Why the matchmaker chose them:**")
    lines.append("> " + str(group["why_hub_chose_it"]).replace("\n", " "))
    lines.append("")
    lines.append("**What each agent said:**")
    m = 0
    while m < len(group["members"]):
        member = group["members"][m]
        m += 1
        first = _first(by_id[member["id"]]["name"])
        k = 0
        while k < len(member["answers"]):
            a = member["answers"][k]
            k += 1
            label = first
            if len(member["answers"]) > 1:
                label = first + ", round " + str(a["round"])
            extra = ""
            if a["counter"]:
                extra = " Asked for: " + a["counter"]
            lines.append("- **" + label + ": " + a["answer"] + ".** " + a["said"] + extra + " `#" + str(a["reply_seq"]) + "`")
    lines.append("")
    lines.append("**How it ended:** " + _ending(group, by_id))
    lines.append("")
    flags = _flags(run, group, by_id, repeats)
    if len(flags) == 0:
        lines.append("**Things to look at:** nothing flagged.")
    else:
        lines.append("**Things to look at:**")
        k = 0
        while k < len(flags):
            lines.append("- " + flags[k])
            k += 1
    review = run["fable"].get(group["group"])
    if review is not None:
        lines.append("")
        lines.append("**Independent AI review (Fable 5.1): " + str(review["verdict"]) + ".** " + str(review["summary"]))
    lines.append("")
    lines.append("**Your verdict:** Good / OK / Bad / Unsure  ·  **Notes:**")
    lines.append("")
    lines.append("---")
    lines.append("")


def _tag_words(activity):
    out = []
    i = 0
    while i < len(activity["tags"]):
        out.append(_words(activity["tags"][i]))
        i += 1
    return out


def _ending(group, by_id):
    tally = {"yes": 0, "no": 0, "counter": 0}
    m = 0
    while m < len(group["members"]):
        k = 0
        while k < len(group["members"][m]["answers"]):
            tally[group["members"][m]["answers"][k]["answer"]] += 1
            k += 1
        m += 1
    asked = len(group["members"])
    text = str(asked) + " asked: " + str(tally["yes"]) + " yes, " + str(tally["no"]) + " no, " + str(tally["counter"]) + " counter. "
    names = []
    i = 0
    while i < len(group["final_members"]):
        names.append(_first(by_id[group["final_members"][i]]["name"]))
        i += 1
    if group["status"] == "locked":
        return text + "Locked by code with " + _and(names) + "."
    return text + "Dropped: " + str(group.get("drop_reason") or "") + "."


# ----- the whole file --------------------------------------------------------------------------

def _glance_flags(run, group, by_id):
    activity = catalog.get(group["activity"])
    out = []
    side = 0
    i = 0
    while i < len(group["final_members"]):
        if not _into_main(by_id[group["final_members"][i]], activity):
            side += 1
        i += 1
    if side > 0:
        out.append(str(side) + " side interest")
    # the most serious check on the group, by name of severity, so a small note doesn't read as a broken rule
    findings = run["findings"]
    worst = None
    order = ["critical", "high", "medium", "low"]
    i = 0
    while i < len(findings):
        f = findings[i]
        i += 1
        if group["group"] in f["groups"] and f["severity"] in order:
            if worst is None or order.index(f["severity"]) < order.index(worst):
                worst = f["severity"]
    if worst is not None:
        out.append("check: " + worst)
    ages = []
    i = 0
    while i < len(group["final_members"]):
        ages.append(by_id[group["final_members"][i]]["age"])
        i += 1
    if len(ages) > 0 and max(ages) - min(ages) >= AGE_GAP:
        out.append("age gap")
    if len(group["final_members"]) == 2:
        out.append("pair")
    return out


def build(root):
    folders, skipped = gather(root)
    manifests = []
    i = 0
    while i < len(folders):
        manifests.append(_read(folders[i], "run_manifest.json"))
        i += 1
    aliases = run_dump._aliases(manifests)
    runs = []
    i = 0
    while i < len(folders):
        runs.append(_load(folders[i], aliases[i]))
        i += 1
    # every group, numbered once, with the same activity and people found again elsewhere
    entries = []
    seen = {}
    r = 0
    while r < len(runs):
        g = 0
        while g < len(runs[r]["groups"]):
            group = runs[r]["groups"][g]
            g += 1
            if group["status"] != "locked":
                continue
            members = list(group["final_members"])
            members.sort()
            key = group["activity"] + "|" + ",".join(members)
            seen.setdefault(key, []).append(len(entries) + 1)
            entries.append({"run": runs[r], "group": group, "key": key})
        r += 1
    lines = []
    _intro(lines, runs, entries, skipped)
    _glance(lines, entries)
    lines.append("## Every group, one by one")
    lines.append("")
    lines.append("Each card: the people, what they like about the activity and what they avoid; the matchmaker's reason")
    lines.append("and every agent's reply, word for word; how it ended; and things worth a look. Numbers like `#560` point")
    lines.append("to that run's full record.")
    lines.append("")
    current = None
    i = 0
    while i < len(entries):
        e = entries[i]
        i += 1
        run = e["run"]
        if run["alias"] != current:
            current = run["alias"]
            lines.append("### Run " + run["alias"] + ": " + _run_words(run))
            lines.append("")
            lines.append("Folder `" + run["folder"] + "`. Its full record, with every prompt, pitch and final message, is")
            lines.append("`run_dump.txt` in that folder.")
            lines.append("")
        others = []
        k = 0
        while k < len(seen[e["key"]]):
            if seen[e["key"]][k] != i:
                others.append("#" + str(seen[e["key"]][k]))
            k += 1
        _card(lines, i, run, e["group"], run["by_id"], others)
    _records(lines, runs, skipped)
    return "\n".join(lines) + "\n"


def _intro(lines, runs, entries, skipped):
    answers = {"yes": 0, "no": 0, "counter": 0}
    hard = 0
    reviewed = {}
    side = 0
    placed = 0
    i = 0
    while i < len(entries):
        e = entries[i]
        i += 1
        activity = catalog.get(e["group"]["activity"])
        m = 0
        while m < len(e["group"]["members"]):
            k = 0
            while k < len(e["group"]["members"][m]["answers"]):
                answers[e["group"]["members"][m]["answers"][k]["answer"]] += 1
                k += 1
            m += 1
        f = 0
        while f < len(e["group"]["final_members"]):
            placed += 1
            if not _into_main(e["run"]["by_id"][e["group"]["final_members"][f]], activity):
                side += 1
            f += 1
        review = e["run"]["fable"].get(e["group"]["group"])
        if review is not None:
            verdict = str(review["verdict"])
            reviewed[verdict] = reviewed.get(verdict, 0) + 1
    r = 0
    while r < len(runs):
        f = 0
        while f < len(runs[r]["findings"]):
            check = runs[r]["findings"][f]["check"]
            kind = runs[r]["findings"][f]["kind"]
            if check in orchestration_audit.HARD_CHECKS or (kind == "confirmed violation" and check.startswith("locked into")):
                hard += 1
            f += 1
        r += 1
    total = len(entries)
    lines.append("# Clawnly match review: " + str(total) + " groups made by the AI matchmaker")
    lines.append("")
    lines.append("Every group the live AI matchmaker made and locked, one at a time, with the reasons behind it. Built from")
    lines.append("the saved runs in `simulation_results/` with no AI calls. Read it top to bottom, or paste it into any AI chat.")
    lines.append("")
    lines.append("## The short answer")
    lines.append("")
    lines.append("- **What ran:** the real matchmaker on 200 emulated Black Diamond neighbors, " + str(len(runs)) + " runs that made groups.")
    lines.append("  Opus 5.5 plans and handles answers, Sonnet 5 plays each person's agent, and code checks the rules and locks")
    lines.append("  groups. " + str(total) + " groups, " + str(answers["yes"] + answers["no"] + answers["counter"]) + " answers from agents: " +
                 str(answers["yes"]) + " yes, " + str(answers["no"]) + " no, " + str(answers["counter"]) + " counter.")
    lines.append("- **The rules held:** " + str(hard) + " hard-rule problems (busy, over budget, double-booked, outside the pool, or")
    lines.append("  at a time someone didn't agree to) across all " + str(total) + " groups.")
    verdicts = []
    count = 0
    keys = []
    order = ["good", "acceptable", "weak", "bad"]
    k = 0
    while k < len(order):
        if order[k] in reviewed:
            keys.append(order[k])
        k += 1
    k = 0
    while k < len(keys):
        verdicts.append(str(reviewed[keys[k]]) + " " + keys[k])
        count += reviewed[keys[k]]
        k += 1
    lines.append("- **An independent AI read " + str(count) + " of the groups** (Fable 5.1, not used in the runs): " +
                 _and(verdicts) + ". The rest are for you.")
    lines.append("- **What to watch for:** " + str(side) + " of " + str(placed) + " places (" + str(int(round(100.0 * side / max(1, placed)))) +
                 "%) went to someone there for a side interest, like the beer at a trivia")
    lines.append("  night. Before the fixes, the matchmaker sometimes described such groups as fans, and two agents accepted")
    lines.append("  a late night their person avoids. Both are fixed; see `AUDIT_REPORT.md`.")
    lines.append("- **Still open for the team:** should liking the main activity be required (Q1), and should the matchmaker")
    lines.append("  favor people placed least this week (Q6)? Parents were asked far less often than retirees.")
    lines.append("")
    lines.append("## How to evaluate a group")
    lines.append("")
    lines.append("1. **Do these people fit together for this activity?** Look at what each likes about it, their ages and weeks.")
    lines.append("2. **Is the matchmaker's reason true?** Compare its words with the people table.")
    lines.append("3. **Did each agent answer like its person would?** A yes should fit their likes and what they avoid.")
    lines.append("4. **Check the things to look at.** They are facts from the data, not verdicts.")
    lines.append("5. **Write your verdict:** Good, OK, Bad or Unsure, in `review_notes.csv` (by match ID) or on the card.")
    lines.append("")
    lines.append("Repeated days are separate runs on the same emulated town, so the same people can meet more than once.")
    lines.append("")


def _glance(lines, entries):
    lines.append("## All groups at a glance")
    lines.append("")
    lines.append("| # | Run | Day | Activity | People | Look at | AI review |")
    lines.append("|---|---|---|---|---|---|---|")
    i = 0
    while i < len(entries):
        e = entries[i]
        i += 1
        group = e["group"]
        names = []
        k = 0
        while k < len(group["final_members"]):
            names.append(_first(e["run"]["by_id"][group["final_members"][k]]["name"]))
            k += 1
        review = e["run"]["fable"].get(group["group"])
        verdict = "-"
        if review is not None:
            verdict = str(review["verdict"])
        flags = _glance_flags(e["run"], group, e["run"]["by_id"])
        lines.append("| " + str(i) + " | " + e["run"]["alias"] + " | " + _day(group["day"]) + " | " + _cell(group["activity_name"]) + " | " +
                     _cell(", ".join(names)) + " | " + _cell(", ".join(flags) or "-") + " | " + verdict + " |")
    lines.append("")


def _records(lines, runs, skipped):
    lines.append("## Where the full records are")
    lines.append("")
    lines.append("| Run | What it was | Folder |")
    lines.append("|---|---|---|")
    i = 0
    while i < len(runs):
        lines.append("| " + runs[i]["alias"] + " | " + _run_words(runs[i]) + " | `" + runs[i]["folder"] + "` |")
        i += 1
    lines.append("")
    lines.append("Each folder has `run_dump.txt` (everything, readable), `full_transcript.txt` and `full_simulation.jsonl`")
    lines.append("(every prompt and reply verbatim). The findings in depth are in `AUDIT_REPORT.md`.")
    if len(skipped) > 0:
        # runs that failed the same way go on one line
        reasons = []
        folders = {}
        i = 0
        while i < len(skipped):
            why = skipped[i]["why"]
            if why not in folders:
                folders[why] = []
                reasons.append(why)
            folders[why].append("`" + skipped[i]["folder"] + "`")
            i += 1
        lines.append("")
        lines.append("Runs that made no groups, left out of every count above:")
        lines.append("")
        i = 0
        while i < len(reasons):
            count = len(folders[reasons[i]])
            lines.append("- " + str(count) + " " + _plural(count, "run", "runs") + ", " + reasons[i] + ": " + ", ".join(folders[reasons[i]]))
            i += 1


def write(root):
    path = os.path.join(root, OUT_NAME)
    with open(path, "w", encoding="utf-8") as f:
        f.write(orchestration_sim.scrub(build(root)))
    return path


def main(argv):
    root = orchestration_sim.RESULTS
    if len(argv) > 1:
        root = argv[1]
    print(write(root))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
