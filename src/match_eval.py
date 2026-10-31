"""Evaluate Run Clawnly's code-only matching: reproducible match records + quality checks.

A "match" here is one group demand.propose_groups forms for one day: an activity,
a day part and 2-5 emulated neighbors. That is the deterministic layer of the
matcher -- the break rooms are exactly what the live matchmaker (matchmaker.py)
plans from; the live matchmaker then lets Opus pick the groups and each agent
answer, which needs paid API calls and is NOT simulated here. Nothing below
invents a model reply.

For every group this records who is in it and why (what the implementation
itself computed: slot rank and strength, each member's fit score and rank in the
room, who was skipped because they were already placed), re-checks every hard
rule independently, runs matchmaker.plan_checks (what each member's agent would
be told argues against the plan), and adds plain proxy measures (does the member
like the activity's main thing, how much the group shares, age spread). Proxies
are not ground truth; groups they flag are marked for human review.

Also here: input-order stability, placement fairness by kind of person, and a
fuzz of the live matchmaker's code checks (check_plan) with random bad plans.

Run it (no API key, no cost):
    .venv/bin/python src/match_eval.py evaluation/results
"""

import csv
import datetime
import json
import os
import random
import subprocess
import sys
import time

import catalog
import demand
import matchmaker
import population


SEED = 7
TOWN_SIZE = 200
DAYS = 7
# two full weeks of the same town: late October (what /run plans next) and mid-July
# (summer-only things run: tubing, dock concerts, lawn yoga). Wednesday starts, like /run today.
WEEKS = ["2026-10-28", "2026-07-15"]
SHUFFLE_TRIALS = 5
FUZZ_TRIALS = 300
# a group with members this many years apart is flagged for a human to look at
AGE_SPREAD_FLAG = 40


def week_days(start):
    first = datetime.date.fromisoformat(start)
    out = []
    i = 0
    while i < DAYS:
        out.append(first + datetime.timedelta(days=i))
        i += 1
    return out


def _index(people):
    out = {}
    i = 0
    while i < len(people):
        out[people[i]["id"]] = people[i]
        i += 1
    return out


def _part_hours(activity, part):
    # the real hours when the event is fixed, else the whole day part
    fixed = matchmaker.fixed_time(activity, part)
    if fixed is not None:
        return fixed
    return matchmaker.PART_HOURS[part]


# ----- independent rule checks (not demand.fit: a second reading of the same rules) -----

def hard_violations(person, activity, day, part):
    found = []
    if day.month not in activity["months"]:
        found.append("out of season")
    if day.weekday() not in activity["days"] or part not in activity["parts"]:
        found.append("activity not running then")
    if part not in person["calendar"].get(day.isoformat(), []):
        found.append("busy")
    if activity["cost"] not in demand.BUDGET_OK[person["budget"]]:
        found.append("over budget")
    i = 0
    while i < len(activity["tags"]):
        if activity["tags"][i] in person["dislikes"]:
            found.append("dislikes " + activity["tags"][i])
        i += 1
    i = 0
    while i < len(activity["traits"]):
        if activity["traits"][i] in person["avoid"]:
            found.append("avoids " + activity["traits"][i])
        i += 1
    return found


def _liked(person):
    out = {}
    i = 0
    while i < len(person["likes"]):
        out[person["likes"][i]["tag"]] = person["likes"][i]["weight"]
        i += 1
    return out


def _jaccard(a, b):
    union = {}
    both = 0
    for_keys = list(a.keys()) + list(b.keys())
    i = 0
    while i < len(for_keys):
        union[for_keys[i]] = True
        i += 1
    keys = list(a.keys())
    i = 0
    while i < len(keys):
        if keys[i] in b:
            both += 1
        i += 1
    if len(union) == 0:
        return 0.0
    return both / len(union)


def group_cohesion(members):
    # mean pairwise overlap of the members' likes (0 = nothing in common beyond chance)
    total = 0.0
    pairs = 0
    i = 0
    while i < len(members):
        j = i + 1
        while j < len(members):
            total += _jaccard(_liked(members[i]), _liked(members[j]))
            pairs += 1
            j += 1
        i += 1
    if pairs == 0:
        return 0.0
    return round(total / pairs, 3)


def _age_band(age):
    bands = [[24, "18-24"], [34, "25-34"], [44, "35-44"], [54, "45-54"], [64, "55-64"]]
    i = 0
    while i < len(bands):
        if age <= bands[i][0]:
            return bands[i][1]
        i += 1
    return "65+"


# ----- one day: the groups, with the implementation's own reasons --------------------

def day_records(people, day, run_id):
    by_id = _index(people)
    slots = demand.break_room(people, catalog.ACTIVITIES, day)
    result = demand.propose_groups(people, catalog.ACTIVITIES, day)
    # replay the greedy order to recover each group's slot rank and who was skipped
    ordered = list(slots)
    ordered.sort(key=lambda s: (-demand._slot_strength(s), s["activity"], s["part"]))
    in_room = {}
    i = 0
    while i < len(slots):
        j = 0
        while j < len(slots[i]["candidates"]):
            in_room[slots[i]["candidates"][j]["id"]] = True
            j += 1
        i += 1
    placed = {}
    records = []
    g = 0
    i = 0
    while i < len(ordered):
        slot = ordered[i]
        i += 1
        if g >= len(result["groups"]):
            break
        group = result["groups"][g]
        if group["activity"] != slot["activity"] or group["part"] != slot["part"]:
            continue
        g += 1
        records.append(_record(slot, group, i, len(ordered), placed, by_id, day, run_id, len(records) + 1))
        k = 0
        while k < len(group["members"]):
            placed[group["members"][k]["id"]] = True
            k += 1
    day_summary = {
        "day": day.isoformat(), "weekday": matchmaker.WEEKDAY[day.weekday()], "run_id": run_id,
        "slots": len(slots), "groups": len(records), "placed": TOWN_SIZE - len(result["unplaced"]),
        "in_any_room": len(in_room), "unplaced_with_a_room": _count_unplaced_with_room(result["unplaced"], in_room),
        "unplaced_with_no_room": len(result["unplaced"]) - _count_unplaced_with_room(result["unplaced"], in_room),
    }
    return records, day_summary, result["unplaced"]


def _count_unplaced_with_room(unplaced, in_room):
    count = 0
    i = 0
    while i < len(unplaced):
        if unplaced[i] in in_room:
            count += 1
        i += 1
    return count


def _record(slot, group, slot_rank, slot_count, placed_before, by_id, day, run_id, number):
    activity = catalog.get(group["activity"])
    hours = _part_hours(activity, group["part"])
    members = []
    people = []
    skipped = []
    ranks = {}
    j = 0
    while j < len(slot["candidates"]):
        ranks[slot["candidates"][j]["id"]] = j + 1
        j += 1
    last_score = group["members"][len(group["members"]) - 1]["score"]
    # who was passed over because an earlier, stronger group already had them
    j = 0
    while j < len(slot["candidates"]) and ranks[slot["candidates"][j]["id"]] <= ranks[group["members"][len(group["members"]) - 1]["id"]]:
        if slot["candidates"][j]["id"] in placed_before:
            skipped.append(slot["candidates"][j]["id"])
        j += 1
    # a tie cut: someone left out of this group with the same score as its last member,
    # decided only by id order
    tie_cut = []
    j = 0
    while j < len(slot["candidates"]):
        c = slot["candidates"][j]
        if c["score"] == last_score and ranks[c["id"]] > ranks[group["members"][len(group["members"]) - 1]["id"]] and c["id"] not in placed_before:
            tie_cut.append(c["id"])
        j += 1
    flags = []
    primary = activity["tags"][0]
    k = 0
    while k < len(group["members"]):
        m = group["members"][k]
        p = by_id[m["id"]]
        people.append(p)
        liked = _liked(p)
        matched = []
        t = 0
        while t < len(activity["tags"]):
            if activity["tags"][t] in liked:
                matched.append({"tag": activity["tags"][t], "weight": liked[activity["tags"][t]]})
            t += 1
        violations = hard_violations(p, activity, day, group["part"])
        checks = matchmaker.plan_checks(p, activity, group["part"], hours, day)
        members.append({
            "id": p["id"], "name": p["name"], "age": p["age"], "age_band": _age_band(p["age"]),
            "archetype": p["archetype"], "kids_at_home": p["kids_at_home"], "area": p["area"],
            "budget": p["budget"], "avoid": p["avoid"], "dislikes": p["dislikes"],
            "fit_score": m["score"], "rank_in_room": ranks[m["id"]], "matched_likes": matched,
            "likes_main_thing": primary in liked, "hard_violations": violations, "agent_would_be_told": checks,
        })
        k += 1
    ages = []
    k = 0
    while k < len(people):
        ages.append(people[k]["age"])
        k += 1
    secondary_only = 0
    told = 0
    violations = 0
    scores = []
    k = 0
    while k < len(members):
        if not members[k]["likes_main_thing"]:
            secondary_only += 1
        if len(members[k]["agent_would_be_told"]) > 0:
            told += 1
        violations += len(members[k]["hard_violations"])
        scores.append(members[k]["fit_score"])
        k += 1
    spread = max(ages) - min(ages)
    if violations > 0:
        flags.append("hard rule violated")
    if told > 0:
        flags.append(str(told) + " member(s) would be told it conflicts with their profile")
    if secondary_only > 0:
        flags.append(str(secondary_only) + " member(s) don't like the main thing (" + primary.replace("_", " ") + ")")
    if spread >= AGE_SPREAD_FLAG:
        flags.append("age spread " + str(spread) + " years")
    if len(tie_cut) > 0:
        flags.append("last place decided by tie-break over " + str(len(tie_cut)) + " equal candidate(s)")
    status = "rule-clean"
    if violations > 0:
        status = "rule violation"
    elif told > 0 or secondary_only > 0 or spread >= AGE_SPREAD_FLAG:
        status = "needs human review"
    explanation = (
        activity["name"] + " (" + group["part"] + ", " + hours + ") was the #" + str(slot_rank) + " of " + str(slot_count)
        + " slots by strength " + str(demand._slot_strength(slot)) + " (the sum of its 5 keenest fit scores); "
        + str(len(slot["candidates"])) + " neighbors were free, keen and able. Code took the "
        + str(len(group["members"])) + " keenest not already placed"
    )
    if len(skipped) > 0:
        explanation = explanation + ", skipping " + str(len(skipped)) + " already in a stronger group"
    explanation = explanation + "."
    return {
        "match_id": run_id + "-" + day.isoformat() + "-g" + str(number).zfill(2),
        "run_id": run_id, "day": day.isoformat(), "weekday": matchmaker.WEEKDAY[day.weekday()],
        "activity": activity["id"], "activity_name": activity["name"], "part": group["part"], "time": hours,
        "fixed_time": matchmaker.fixed_time(activity, group["part"]) is not None,
        "cost": activity["cost"], "tags": activity["tags"], "traits": activity["traits"], "outdoor": activity["outdoor"],
        "size": len(members), "members": members,
        "slot_rank": slot_rank, "slot_count": slot_count, "slot_strength": demand._slot_strength(slot),
        "room_size": len(slot["candidates"]), "skipped_already_placed": skipped, "tie_cut": tie_cut,
        "mean_fit": round(sum(scores) / len(scores), 2), "min_fit": min(scores),
        "cohesion": group_cohesion(people), "age_spread": spread,
        "outcome": "proposed by code (not negotiated: the LLM rounds need a paid API run)",
        "explanation_recorded": explanation,
        "flags": flags, "review_status": status,
    }


# ----- the whole evaluation ---------------------------------------------------------

def generate(weeks=None):
    if weeks is None:
        weeks = WEEKS
    records = []
    days = []
    unplaced_by_run = {}
    towns = {}
    w = 0
    while w < len(weeks):
        start = datetime.date.fromisoformat(weeks[w])
        town = population.generate(TOWN_SIZE, seed=SEED, start=start, days=DAYS)
        run_id = "wk" + weeks[w].replace("-", "")
        towns[run_id] = town
        unplaced_by_run[run_id] = []
        listed = week_days(weeks[w])
        d = 0
        while d < len(listed):
            day_recs, summary, unplaced = day_records(town, listed[d], run_id)
            records = records + day_recs
            days.append(summary)
            unplaced_by_run[run_id].append({"day": listed[d].isoformat(), "ids": unplaced})
            d += 1
        w += 1
    return records, days, towns, unplaced_by_run


def placement_fairness(towns, days):
    # per kind of person: how many of the week's days they got a group, averaged
    out = {}
    run_ids = list(towns.keys())
    r = 0
    while r < len(run_ids):
        town = towns[run_ids[r]]
        placed_days = {}
        d = 0
        while d < len(days):
            if days[d]["run_id"] == run_ids[r]:
                placed = days[d]["placed_ids"]
                k = 0
                while k < len(placed):
                    placed_days[placed[k]] = placed_days.get(placed[k], 0) + 1
                    k += 1
            d += 1
        dims = {}
        i = 0
        while i < len(town):
            p = town[i]
            keys = [
                ["archetype", p["archetype"]], ["age_band", _age_band(p["age"])], ["budget", p["budget"]],
                ["kids_at_home", str(p["kids_at_home"])], ["avoid_count", str(len(p["avoid"]))],
                ["likes_count", str(len(p["likes"]))], ["area", p["area"]],
                ["id_quartile", "Q" + str(int((int(p["id"][1:]) - 1) // (TOWN_SIZE // 4)) + 1)],
            ]
            k = 0
            while k < len(keys):
                dim = keys[k][0]
                value = keys[k][1]
                if dim not in dims:
                    dims[dim] = {}
                if value not in dims[dim]:
                    dims[dim][value] = {"people": 0, "placed_days": 0, "never_placed": 0}
                cell = dims[dim][value]
                cell["people"] += 1
                cell["placed_days"] += placed_days.get(p["id"], 0)
                if placed_days.get(p["id"], 0) == 0:
                    cell["never_placed"] += 1
                k += 1
            i += 1
        names = list(dims.keys())
        k = 0
        while k < len(names):
            values = list(dims[names[k]].keys())
            v = 0
            while v < len(values):
                cell = dims[names[k]][values[v]]
                cell["days_placed_per_person"] = round(cell["placed_days"] / cell["people"], 2)
                v += 1
            k += 1
        out[run_ids[r]] = dims
        r += 1
    return out


def order_stability(trials=SHUFFLE_TRIALS):
    # the same people in a different order must give the same groups
    start = datetime.date.fromisoformat(WEEKS[0])
    town = population.generate(TOWN_SIZE, seed=SEED, start=start, days=DAYS)
    listed = week_days(WEEKS[0])
    differing = 0
    checked = 0
    t = 0
    while t < trials:
        shuffled = list(town)
        random.Random(1000 + t).shuffle(shuffled)
        d = 0
        while d < len(listed):
            a = demand.propose_groups(town, catalog.ACTIVITIES, listed[d])["groups"]
            b = demand.propose_groups(shuffled, catalog.ACTIVITIES, listed[d])["groups"]
            if _group_keys(a) != _group_keys(b):
                differing += 1
            checked += 1
            d += 1
        t += 1
    return {"day_runs_checked": checked, "day_runs_that_differed": differing}


def _group_keys(groups):
    keys = []
    i = 0
    while i < len(groups):
        ids = []
        j = 0
        while j < len(groups[i]["members"]):
            ids.append(groups[i]["members"][j]["id"])
            j += 1
        ids.sort()
        keys.append(groups[i]["activity"] + "|" + groups[i]["part"] + "|" + ",".join(ids))
        i += 1
    keys.sort()
    return keys


def repeat_pairs(records):
    # within one week, how often the same two people land in a group together again
    seen = {}
    i = 0
    while i < len(records):
        ids = []
        j = 0
        while j < len(records[i]["members"]):
            ids.append(records[i]["members"][j]["id"])
            j += 1
        ids.sort()
        a = 0
        while a < len(ids):
            b = a + 1
            while b < len(ids):
                key = records[i]["run_id"] + "|" + ids[a] + "|" + ids[b]
                seen[key] = seen.get(key, 0) + 1
                b += 1
            a += 1
        i += 1
    pairs = list(seen.values())
    again = 0
    most = 0
    i = 0
    while i < len(pairs):
        if pairs[i] > 1:
            again += 1
        if pairs[i] > most:
            most = pairs[i]
        i += 1
    return {"distinct_pairs": len(pairs), "pairs_together_more_than_once": again, "most_times_together": most}


def fuzz_check_plan(trials=FUZZ_TRIALS):
    # random, rule-breaking plans fed to the live matchmaker's code check: what survives must obey every rule
    day = datetime.date.fromisoformat(WEEKS[0]) + datetime.timedelta(days=3)
    town = population.generate(TOWN_SIZE, seed=SEED, start=datetime.date.fromisoformat(WEEKS[0]), days=DAYS)
    people = _index(town)
    rooms = demand.break_room(town, catalog.ACTIVITIES, day)
    rng = random.Random(42)
    ids = list(people.keys())
    broken = []
    groups_kept = 0
    t = 0
    while t < trials:
        raw_groups = []
        n = rng.randint(1, 12)
        g = 0
        while g < n:
            room = rooms[rng.randrange(len(rooms))]
            activity = room["activity"]
            part = room["part"]
            if rng.random() < 0.15:
                activity = catalog.ACTIVITIES[rng.randrange(len(catalog.ACTIVITIES))]["id"]
            if rng.random() < 0.15:
                part = catalog.DAY_PARTS[rng.randrange(3)]
            members = []
            m = rng.randint(0, 7)
            while len(members) < m:
                if rng.random() < 0.6:
                    members.append(room["candidates"][rng.randrange(len(room["candidates"]))]["id"])
                else:
                    members.append(ids[rng.randrange(len(ids))])
            raw_groups.append({"activity": activity, "part": part, "members": members,
                               "alternates": [ids[rng.randrange(len(ids))]], "time": "7am-11pm"})
            g += 1
        groups, rejected = matchmaker.check_plan({"groups": raw_groups}, rooms, 10, people)
        groups_kept += len(groups)
        booked = {}
        i = 0
        while i < len(groups):
            room = None
            r = 0
            while r < len(rooms):
                if rooms[r]["activity"] == groups[i]["activity"] and rooms[r]["part"] == groups[i]["part"]:
                    room = rooms[r]
                r += 1
            room_ids = {}
            if room is not None:
                r = 0
                while r < len(room["candidates"]):
                    room_ids[room["candidates"][r]["id"]] = True
                    r += 1
            if room is None:
                broken.append("trial " + str(t) + ": group outside any break room")
            if len(groups[i]["members"]) < catalog.GROUP_MIN:
                broken.append("trial " + str(t) + ": group under the minimum size")
            j = 0
            while j < len(groups[i]["members"]):
                pid = groups[i]["members"][j]["id"]
                if pid not in room_ids:
                    broken.append("trial " + str(t) + ": " + pid + " not in the room")
                if pid in booked:
                    broken.append("trial " + str(t) + ": " + pid + " booked twice")
                booked[pid] = True
                j += 1
            i += 1
        if len(groups) > 10:
            broken.append("trial " + str(t) + ": over max_groups")
        t += 1
    return {"trials": trials, "groups_kept": groups_kept, "rule_breaks_that_got_through": broken[:20],
            "rule_break_count": len(broken)}


def summarize(records, days):
    total_members = 0
    status = {}
    flags = {}
    sizes = {}
    told = 0
    secondary = 0
    tie_groups = 0
    violations = 0
    told_reasons = {}
    by_activity = {}
    i = 0
    while i < len(records):
        rec = records[i]
        status[rec["review_status"]] = status.get(rec["review_status"], 0) + 1
        sizes[str(rec["size"])] = sizes.get(str(rec["size"]), 0) + 1
        by_activity[rec["activity"]] = by_activity.get(rec["activity"], 0) + 1
        if len(rec["tie_cut"]) > 0:
            tie_groups += 1
        j = 0
        while j < len(rec["flags"]):
            kind = rec["flags"][j].split(" (")[0]
            if kind[0].isdigit():
                kind = kind.split(" ", 1)[1]
            if kind.startswith("age spread"):
                kind = "age spread >= " + str(AGE_SPREAD_FLAG) + " years"
            if kind.startswith("last place decided by tie-break"):
                kind = "last place decided by tie-break"
            flags[kind] = flags.get(kind, 0) + 1
            j += 1
        j = 0
        while j < len(rec["members"]):
            m = rec["members"][j]
            total_members += 1
            if len(m["agent_would_be_told"]) > 0:
                told += 1
                k = 0
                while k < len(m["agent_would_be_told"]):
                    reason = _reason_kind(m["agent_would_be_told"][k])
                    told_reasons[reason] = told_reasons.get(reason, 0) + 1
                    k += 1
            if not m["likes_main_thing"]:
                secondary += 1
            violations += len(m["hard_violations"])
            j += 1
        i += 1
    placed = 0
    could = 0
    no_room = 0
    i = 0
    while i < len(days):
        placed += days[i]["placed"]
        could += days[i]["unplaced_with_a_room"]
        no_room += days[i]["unplaced_with_no_room"]
        i += 1
    return {
        "matches": len(records), "member_placements": total_members, "review_status": status, "flags": flags,
        "group_sizes": sizes, "groups_by_activity": by_activity,
        "hard_rule_violations": violations,
        "members_agent_would_be_told_a_conflict": told, "conflict_reasons": told_reasons,
        "members_not_liking_the_main_thing": secondary,
        "groups_with_a_tie_cut": tie_groups,
        "person_days": len(days) * TOWN_SIZE, "person_days_placed": placed,
        "person_days_unplaced_but_in_a_room": could, "person_days_with_no_room": no_room,
        "mean_cohesion": _mean(records, "cohesion"), "mean_fit": _mean(records, "mean_fit"),
        "mean_age_spread": _mean(records, "age_spread"),
    }


def _reason_kind(text):
    low = text.lower()
    if "late nights" in low:
        return "runs to 9pm+ and they avoid late nights"
    if "early mornings" in low or "before 9am" in low:
        return "early start and they avoid early mornings"
    if "only up for it" in low:
        return "mild interest (weight 1)"
    if "never said they like" in low:
        return "never said they like it"
    if "busy" in low:
        return "busy"
    return text


def _mean(records, key):
    if len(records) == 0:
        return 0
    total = 0.0
    i = 0
    while i < len(records):
        total += records[i][key]
        i += 1
    return round(total / len(records), 2)


def _git(args):
    try:
        out = subprocess.run(["git"] + args, capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
        return out.stdout.strip()
    except Exception:
        return None


CSV_FIELDS = ["match_id", "run_id", "day", "weekday", "activity", "activity_name", "part", "time", "cost", "size",
              "member_ids", "member_ages", "member_scores", "mean_fit", "min_fit", "cohesion", "age_spread",
              "slot_rank", "slot_strength", "room_size", "tie_cut", "review_status", "flags", "explanation_recorded"]


def _csv_row(rec):
    ids = []
    ages = []
    scores = []
    i = 0
    while i < len(rec["members"]):
        ids.append(rec["members"][i]["id"])
        ages.append(str(rec["members"][i]["age"]))
        scores.append(str(rec["members"][i]["fit_score"]))
        i += 1
    row = dict(rec)
    row["member_ids"] = " ".join(ids)
    row["member_ages"] = " ".join(ages)
    row["member_scores"] = " ".join(scores)
    row["tie_cut"] = " ".join(rec["tie_cut"])
    row["flags"] = "; ".join(rec["flags"])
    out = {}
    i = 0
    while i < len(CSV_FIELDS):
        out[CSV_FIELDS[i]] = row[CSV_FIELDS[i]]
        i += 1
    return out


def run(out_dir):
    started = time.monotonic()
    records, days, towns, unplaced_by_run = generate()
    # placed ids per day, for the fairness table
    i = 0
    while i < len(days):
        placed = []
        j = 0
        while j < len(records):
            if records[j]["run_id"] == days[i]["run_id"] and records[j]["day"] == days[i]["day"]:
                k = 0
                while k < len(records[j]["members"]):
                    placed.append(records[j]["members"][k]["id"])
                    k += 1
            j += 1
        days[i]["placed_ids"] = placed
        i += 1
    gen_ms = int((time.monotonic() - started) * 1000)
    fairness = placement_fairness(towns, days)
    stability = order_stability()
    fuzz = fuzz_check_plan()
    summary = summarize(records, days)
    summary["repeat_pairs"] = repeat_pairs(records)
    summary["order_stability"] = stability
    summary["check_plan_fuzz"] = fuzz
    summary["days"] = []
    i = 0
    while i < len(days):
        day = dict(days[i])
        day.pop("placed_ids")
        summary["days"].append(day)
        i += 1
    summary["fairness"] = fairness
    metadata = {
        "what_a_match_is": "one group demand.propose_groups forms for one day (activity, day part, 2-5 emulated neighbors)",
        "not_simulated": "the LLM steps of matchmaker.run_day (Opus plan, agent replies, resolve, final message): no API key or budget was authorized",
        "git_commit": _git(["rev-parse", "HEAD"]), "git_dirty": len(_git(["status", "--porcelain"]) or "") > 0,
        "python": sys.version.split()[0], "seed": SEED, "town_size": TOWN_SIZE, "weeks": WEEKS, "days_per_week": DAYS,
        "group_min": catalog.GROUP_MIN, "group_max": catalog.GROUP_MAX, "activities": len(catalog.ACTIVITIES),
        "api_calls": 0, "generation_ms": gen_ms, "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "command": ".venv/bin/python src/match_eval.py " + out_dir,
    }
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "matches.json"), "w", encoding="utf-8") as f:
        json.dump(records, f, indent=1)
    with open(os.path.join(out_dir, "matches.csv"), "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        i = 0
        while i < len(records):
            writer.writerow(_csv_row(records[i]))
            i += 1
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    with open(os.path.join(out_dir, "simulation_metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=1)
    with open(os.path.join(out_dir, "unplaced.json"), "w", encoding="utf-8") as f:
        json.dump(unplaced_by_run, f, indent=1)
    return summary, metadata


if __name__ == "__main__":
    target = "evaluation/results"
    if len(sys.argv) > 1:
        target = sys.argv[1]
    s, meta = run(target)
    print(str(s["matches"]) + " matches, " + str(s["member_placements"]) + " placements, generated in "
          + str(meta["generation_ms"]) + "ms; written to " + target)
