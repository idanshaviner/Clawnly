"""The break room: where the orchestrator finds common ground, in code.

Before any agent is asked anything, this looks at every activity in the
neighborhood catalog for a given day and finds who could do it: people who
like it, don't dislike or avoid anything about it, are free in that day part,
and can afford it -- and the activity is running that month and day. Then it proposes groups -- each person in
at most one group that day, every group 2 to 5 people (catalog.GROUP_MIN..MAX).

No AI calls: this is the cheap, deterministic part of the orchestrator. Its
output is what the orchestrator will go and negotiate with each person's agent.

Run it:  .venv/bin/python src/demand.py [YYYY-MM-DD]   (default: tomorrow)
"""

import datetime
import sys

import catalog
import population


BUDGET_OK = {"free": ["free"], "low": ["free", "low"], "any": ["free", "low", "mid"]}


def fit(person, activity, day, part):
    # (score, None) if this person could join this activity in this day part,
    # else (0, the reason they can't). The score says how much they'd want to.
    if day.month not in activity["months"]:
        return 0, "out of season"
    if day.weekday() not in activity["days"] or part not in activity["parts"]:
        return 0, "not running then"
    if part not in person["calendar"].get(day.isoformat(), []):
        return 0, "busy"
    if activity["cost"] not in BUDGET_OK[person["budget"]]:
        return 0, "over budget"
    i = 0
    while i < len(activity["tags"]):
        if activity["tags"][i] in person["dislikes"]:
            return 0, "dislikes " + activity["tags"][i]
        i += 1
    traits = list(activity["traits"])
    if part == "morning" and activity["outdoor"]:
        traits.append("early_mornings")
    j = 0
    while j < len(traits):
        if traits[j] in person["avoid"]:
            return 0, "avoids " + traits[j]
        j += 1
    score = 0
    k = 0
    while k < len(person["likes"]):
        if person["likes"][k]["tag"] in activity["tags"]:
            score += person["likes"][k]["weight"]
        k += 1
    if score == 0:
        return 0, "not interested"
    return score, None


def break_room(people, activities, day):
    # every activity x day part that could run, with everyone who could join, keenest first
    slots = []
    a = 0
    while a < len(activities):
        activity = activities[a]
        p = 0
        while p < len(catalog.DAY_PARTS):
            part = catalog.DAY_PARTS[p]
            interested = []
            n = 0
            while n < len(people):
                score, why_not = fit(people[n], activity, day, part)
                if why_not is None:
                    interested.append({"id": people[n]["id"], "score": score})
                n += 1
            if len(interested) >= catalog.GROUP_MIN:
                interested.sort(key=lambda c: (-c["score"], c["id"]))
                slots.append({"activity": activity["id"], "part": part, "candidates": interested})
            p += 1
        a += 1
    return slots


def _slot_strength(slot):
    # how full and how keen a slot could be at its best
    top = slot["candidates"][:catalog.GROUP_MAX]
    total = 0
    i = 0
    while i < len(top):
        total += top[i]["score"]
        i += 1
    return total


def propose_groups(people, activities, day):
    # greedy: strongest slots first, each person placed at most once per day
    slots = break_room(people, activities, day)
    slots.sort(key=lambda s: (-_slot_strength(s), s["activity"], s["part"]))
    placed = {}
    groups = []
    i = 0
    while i < len(slots):
        slot = slots[i]
        activity = catalog.get(slot["activity"])
        members = []
        j = 0
        while j < len(slot["candidates"]) and len(members) < catalog.GROUP_MAX:
            candidate = slot["candidates"][j]
            if candidate["id"] not in placed:
                members.append(candidate)
            j += 1
        if len(members) >= catalog.GROUP_MIN:
            k = 0
            while k < len(members):
                placed[members[k]["id"]] = activity["id"]
                k += 1
            groups.append({"activity": activity["id"], "part": slot["part"], "members": members})
        i += 1
    unplaced = []
    n = 0
    while n < len(people):
        if people[n]["id"] not in placed:
            unplaced.append(people[n]["id"])
        n += 1
    return {"day": day.isoformat(), "slots_that_could_run": len(slots), "groups": groups, "unplaced": unplaced}


def _names(people):
    out = {}
    i = 0
    while i < len(people):
        out[people[i]["id"]] = people[i]["name"]
        i += 1
    return out


def main():
    day = datetime.date.today() + datetime.timedelta(days=1)
    if len(sys.argv) > 1:
        day = datetime.date.fromisoformat(sys.argv[1])
    people = population.generate(200, seed=7, start=day)
    result = propose_groups(people, catalog.ACTIVITIES, day)
    names = _names(people)
    print("Break room for " + day.strftime("%A %d %B %Y") + ": " + str(len(people)) + " emulated neighbors in " + catalog.NEIGHBORHOOD +
          ", " + str(len(catalog.ACTIVITIES)) + " things to do.")
    print(str(result["slots_that_could_run"]) + " activity slots have enough free, interested people. Proposed groups:\n")
    g = 0
    while g < len(result["groups"]):
        group = result["groups"][g]
        activity = catalog.get(group["activity"])
        who = []
        m = 0
        while m < len(group["members"]):
            who.append(names[group["members"][m]["id"]])
            m += 1
        print("  " + activity["name"] + " (" + group["part"] + ", " + str(len(who)) + " people): " + ", ".join(who))
        g += 1
    placed = len(people) - len(result["unplaced"])
    print("\n" + str(placed) + " of " + str(len(people)) + " people have a plan for that day; " +
          str(len(result["unplaced"])) + " don't (yet).")


if __name__ == "__main__":
    main()
