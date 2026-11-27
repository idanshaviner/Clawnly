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
import logging
import re
import sys

import catalog
import population


log = logging.getLogger(__name__)

BUDGET_OK = {"free": ["free"], "low": ["free", "low"], "any": ["free", "low", "mid"]}


def tie_order(day, person_id):
    # equally keen people are ordered by a per-day draw, not by id: id order used
    # to hand the earliest ids ~15% more groups (evaluation/MATCH_QUALITY_REPORT.md).
    # FNV-1a, so it's the same every run and in src/web/run-clawnly.js.
    value = 2166136261
    text = day.isoformat() + "|" + person_id
    i = 0
    while i < len(text):
        value = value ^ ord(text[i])
        value = (value * 16777619) % 4294967296
        i += 1
    return value


COST_LEVELS = ["free", "low", "mid"]


def cost_for(person, activity):
    # what this plan really costs this person: at a family outing priced per person, a parent
    # with kids at home pays for each of them too, so a low-cost ticket is not a low-cost outing
    # (Nov 16 review, Example #31: $65 a head was read as one ticket for a parent and a child)
    cost = activity["cost"]
    if activity.get("family") and person.get("kids_at_home") and cost != "free":
        i = COST_LEVELS.index(cost)
        cost = COST_LEVELS[min(i + 1, len(COST_LEVELS) - 1)]
    return cost


def time_traits(activity, part):
    # a real event's fixed time says what it involves, even when its tags forget to: ending at 9pm
    # or later is a late night, starting before 9am is an early morning (the same lines
    # matchmaker.conflicts draws), so an avoider never gets into the break room for it
    import matchmaker
    out = []
    hours = matchmaker.parse_hours(matchmaker.fixed_time(activity, part))
    if hours is None:
        return out
    if hours[1] >= 21:
        out.append("late_nights")
    if hours[0] < 9:
        out.append("early_mornings")
    return out


def wants(person, activity):
    # they said they like one of the activity's tags at any strength (love, like, or up for it).
    # Nov 13 review (Example #19, Idan): Jason, only up for a jog, should still be asked about an
    # early start, not just the people who love running
    i = 0
    while i < len(person["likes"]):
        if person["likes"][i]["tag"] in activity["tags"] and person["likes"][i]["weight"] >= 1:
            return True
        i += 1
    return False


# a full ISO date, or an ISO date-time whose date part we take ("2027-01-04T09:00");
# src/web/run-clawnly.js uses the same pattern so both copies agree on what counts
PAUSE_PATTERN = re.compile(r"^([0-9]{4}-[0-9]{2}-[0-9]{2})(T[0-9]{2}:[0-9]{2}(:[0-9]{2})?)?$")
_warned = set()


def pause_date(person):
    # the day someone's break ends, or None. A bad value ("January", "01/04/2027", a number) is
    # treated as no pause and logged once, so one bad profile never stops matching for everyone
    # (Nov 24 review, Idan: a malformed date crashed the whole run)
    until = person.get("paused_until")
    if until is None or until == "":
        return None
    if isinstance(until, str):
        found = PAUSE_PATTERN.match(until)
        if found is not None:
            try:
                return datetime.date.fromisoformat(found.group(1))
            except ValueError:
                pass
    key = (person.get("id"), repr(until))
    if key not in _warned:
        _warned.add(key)
        log.warning("ignoring bad paused_until %r for person %s: treated as no pause", until, person.get("id"))
    return None


MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
          "sep": 9, "oct": 10, "nov": 11, "dec": 12}
# a month only counts after a word that sets an end ("until", "through", "after", "end of"), so
# "I may be busy" is not May. Month names may be full or short ("January", "Jan", "Sept").
PAUSE_WORDS = re.compile(
    r"\b(until|till|til|through|thru|after|end of)\s+(?:the\s+)?(early|mid|late|end of)?[\s-]*"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
    r"(?:\s+([0-9]{1,2})(?:st|nd|rd|th)?\b)?(?:,?\s+([0-9]{4}))?",
    re.IGNORECASE)
ISO_IN_TEXT = re.compile(r"\b([0-9]{4}-[0-9]{2}-[0-9]{2})\b")


def _first_of_next_month(d):
    if d.month == 12:
        return datetime.date(d.year + 1, 1, 1)
    return datetime.date(d.year, d.month + 1, 1)


def pause_from_words(text, today):
    # what the person's agent writes into paused_until when someone says they need a break
    # (Nov 24 Review #17, from Idan's question on PR #17: nothing set the date). Returns an ISO
    # date, or None when the words don't give a clear end date: then the agent asks for one
    # instead of guessing, and no pause is set.
    #   "swamped until January"   -> the 1st of the next January
    #   "busy until Jan 15"       -> that day
    #   "through January", "until late January", "until the end of January" -> Feb 1
    #   "until mid-January"       -> Jan 15
    #   "after the holidays", "for a while", "until next month" -> None (ask)
    # A day that has already passed this year means next year. A month equal to this month with
    # no day ("until November", said in November) is unclear, so the agent asks.
    if not isinstance(text, str) or not isinstance(today, datetime.date):
        return None
    iso = ISO_IN_TEXT.search(text)
    if iso is not None:
        try:
            found = datetime.date.fromisoformat(iso.group(1))
        except ValueError:
            return None
        return found.isoformat() if found > today else None
    m = PAUSE_WORDS.search(text)
    if m is None:
        return None
    word = m.group(1).lower()
    part = (m.group(2) or "").lower()
    month = MONTHS[m.group(3).lower()[:3]]
    day_of = int(m.group(4)) if m.group(4) else None
    year = int(m.group(5)) if m.group(5) else None
    whole_month = day_of is None and (word in ("through", "thru", "after", "end of") or part in ("late", "end of"))
    if day_of is None:
        day_of = 15 if part == "mid" else 1
    if year is None:
        year = today.year
        if month < today.month or (month == today.month and m.group(4) is None and not whole_month):
            if month == today.month:
                return None
            year += 1
    try:
        found = datetime.date(year, month, day_of)
    except ValueError:
        return None
    if whole_month:
        found = _first_of_next_month(found)
    if found <= today:
        if m.group(5):
            return None
        try:
            found = found.replace(year=found.year + 1)
        except ValueError:
            return None
    return found.isoformat()


def paused_until(person, day):
    # the date someone asked for a break until ("swamped with work until January"), when that break
    # still covers this day, else None. A pause is not a no and not a maybe: no offers at all until
    # then, and code keeps them out of every break room (Nov 20 review, Example #59)
    until = pause_date(person)
    if until is not None and day < until:
        return until.isoformat()
    return None


def fit(person, activity, day, part):
    # (score, None) if this person could join this activity in this day part,
    # else (0, the reason they can't). The score says how much they'd want to.
    if day.month not in activity["months"]:
        return 0, "out of season"
    if day.weekday() not in activity["days"] or part not in activity["parts"]:
        return 0, "not running then"
    until = paused_until(person, day)
    if until is not None:
        return 0, "paused until " + until
    if part not in person["calendar"].get(day.isoformat(), []):
        return 0, "busy"
    if cost_for(person, activity) not in BUDGET_OK[person["budget"]]:
        return 0, "over budget"
    i = 0
    while i < len(activity["tags"]):
        if activity["tags"][i] in person["dislikes"]:
            return 0, "dislikes " + activity["tags"][i]
        i += 1
    traits = list(activity["traits"])
    if not wants(person, activity):
        # someone who likes the activity stays in the room for a late or early real event: their
        # agent asks them first instead of code counting them out (Nov 12 review, Example #13;
        # widened from lovers to anyone who likes it on Nov 13, Example #19)
        traits += time_traits(activity, part)
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
                interested.sort(key=lambda c: (-c["score"], tie_order(day, c["id"]), c["id"]))
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
