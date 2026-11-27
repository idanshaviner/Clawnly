"""Tests for demand.py -- the break room: common ground found in code."""

import datetime

import catalog
import demand
import population

SUNDAY = datetime.date(2026, 9, 27)


def person(**over):
    p = {"id": "x1", "name": "X", "neighborhood": "Black Diamond, WA", "budget": "any",
         "likes": [{"tag": "kayaking", "weight": 3}], "dislikes": [], "avoid": [],
         "calendar": {SUNDAY.isoformat(): ["morning", "afternoon"]}}
    p.update(over)
    return p


def test_fit_scores_a_keen_free_person():
    kayak = catalog.get("sawyer-paddle")
    score, why_not = demand.fit(person(), kayak, SUNDAY, "afternoon")
    assert why_not is None and score == 3   # loves kayaking


def test_fit_says_why_not():
    kayak = catalog.get("sawyer-paddle")
    assert demand.fit(person(calendar={}), kayak, SUNDAY, "afternoon")[1] == "busy"
    assert demand.fit(person(budget="free"), kayak, SUNDAY, "afternoon")[1] == "over budget"
    assert demand.fit(person(dislikes=["kayaking"]), kayak, SUNDAY, "afternoon")[1] == "dislikes kayaking"
    assert demand.fit(person(avoid=["early_mornings"]), kayak, SUNDAY, "morning")[1] == "avoids early_mornings"
    assert demand.fit(person(), kayak, datetime.date(2027, 1, 10), "afternoon")[1] == "out of season"
    assert demand.fit(person(likes=[{"tag": "chess", "weight": 3}]), kayak, SUNDAY, "afternoon")[1] == "not interested"
    assert demand.fit(person(), kayak, SUNDAY, "evening")[1] == "not running then"


def test_groups_respect_sizes_and_nobody_is_booked_twice():
    people = population.generate(200, seed=7, start=SUNDAY)
    result = demand.propose_groups(people, catalog.ACTIVITIES, SUNDAY)
    assert len(result["groups"]) > 0
    seen = set()
    for g in result["groups"]:
        activity = catalog.get(g["activity"])
        assert 2 <= len(g["members"]) <= 5
        for m in g["members"]:
            assert m["id"] not in seen
            seen.add(m["id"])
            p = next(x for x in people if x["id"] == m["id"])
            assert demand.fit(p, activity, SUNDAY, g["part"])[1] is None
    assert len(seen) + len(result["unplaced"]) == 200


def test_the_break_room_is_deterministic():
    people = population.generate(200, seed=7, start=SUNDAY)
    assert demand.propose_groups(people, catalog.ACTIVITIES, SUNDAY) == demand.propose_groups(people, catalog.ACTIVITIES, SUNDAY)


def test_one_person_is_not_a_group_but_two_are():
    kayak = catalog.get("sawyer-paddle")
    one = [person(id="a")]
    result = demand.propose_groups(one, [kayak], SUNDAY)
    assert result["groups"] == [] and result["slots_that_could_run"] == 0
    two = one + [person(id="b")]
    assert len(demand.propose_groups(two, [kayak], SUNDAY)["groups"]) == 1


def test_a_crowd_is_split_into_small_groups_across_the_day():
    kayak = catalog.get("sawyer-paddle")
    eight = [person(id="p" + str(i)) for i in range(8)]   # all free morning and afternoon
    groups = demand.propose_groups(eight, [kayak], SUNDAY)["groups"]
    assert [len(g["members"]) for g in groups] == [5, 3]
    assert {g["part"] for g in groups} == {"morning", "afternoon"}


def test_equal_keenness_is_not_settled_by_id_order():
    # id order used to give the earliest ids more groups; ties now follow a per-day draw
    kayak = catalog.get("sawyer-paddle")
    six = [person(id="p" + str(i)) for i in range(6)]   # all equally keen and free
    first_pick = set()
    for d in range(10):
        day = SUNDAY + datetime.timedelta(days=d)   # kayaking runs every day through October
        crowd = [dict(p, calendar={day.isoformat(): ["afternoon"]}) for p in six]
        room = demand.break_room(crowd, [kayak], day)[0]
        first_pick.add(room["candidates"][0]["id"])
    assert len(first_pick) > 1


def test_the_tie_order_is_reproducible_and_ignores_input_order():
    people = population.generate(200, seed=7, start=SUNDAY)
    shuffled = list(reversed(people))
    assert demand.break_room(people, catalog.ACTIVITIES, SUNDAY) == demand.break_room(shuffled, catalog.ACTIVITIES, SUNDAY)
    assert demand.tie_order(SUNDAY, "e001") == demand.tie_order(SUNDAY, "e001")
    # the same FNV-1a value src/web/run-clawnly.js computes for this day and id
    assert demand.tie_order(datetime.date(2026, 10, 28), "e001") == 1893869886


def test_a_late_real_event_keeps_late_night_avoiders_out_of_the_break_room():
    # trivia runs 7pm-9pm and the Kraken night 7pm-9:30pm: both late, even though neither is tagged late
    wednesday = datetime.date(2026, 11, 11)
    trivia = catalog.get("trivia")
    assert "late_nights" not in trivia["traits"]
    fan = person(likes=[{"tag": "trivia", "weight": 2}], calendar={wednesday.isoformat(): ["evening"]})
    assert demand.fit(fan, trivia, wednesday, "evening")[1] is None
    stranger = person(likes=[], avoid=["late_nights"], calendar={wednesday.isoformat(): ["evening"]})
    assert demand.fit(stranger, trivia, wednesday, "evening")[1] == "avoids late_nights"
    # Nov 13 review (Example #19, Idan): someone only up for it is asked about the late end too
    fan["likes"] = [{"tag": "trivia", "weight": 1}]
    fan["avoid"] = ["late_nights"]
    assert demand.fit(fan, trivia, wednesday, "evening")[1] is None
    assert demand.time_traits(catalog.get("kraken"), "evening") == ["late_nights"]


def test_time_traits_read_only_a_fixed_time():
    assert demand.time_traits(catalog.get("book-club"), "evening") == []        # no fixed time
    assert demand.time_traits(catalog.get("little-league"), "evening") == []    # 6pm-8pm ends before 9pm
    assert demand.time_traits(catalog.get("trail-cleanup"), "morning") == []    # 9am start is not early
    early = dict(catalog.get("trail-cleanup"), fixed={"morning": "8am-11am"})
    assert demand.time_traits(early, "morning") == ["early_mornings"]


def test_someone_who_loves_it_stays_in_the_room_for_a_late_real_event():
    # Nov 12 review (Example #13): a hockey lover who usually avoids late nights is asked, not counted out
    wednesday = datetime.date(2026, 11, 11)
    trivia = catalog.get("trivia")
    lover = person(likes=[{"tag": "trivia", "weight": 3}], avoid=["late_nights"],
                   calendar={wednesday.isoformat(): ["evening"]})
    assert demand.fit(lover, trivia, wednesday, "evening")[1] is None
    # a tagged trait or the outdoor-morning guess is still a hard no, even for a lover
    kayak = catalog.get("sawyer-paddle")
    assert demand.fit(person(avoid=["early_mornings"]), kayak, SUNDAY, "morning")[1] == "avoids early_mornings"


def test_a_family_outing_costs_a_parent_a_ticket_per_kid():
    # Nov 16 review (Example #31): $65 a head was read as one ticket for a parent and a child.
    # A family outing priced per person costs a parent with kids at home more than one ticket.
    swim = catalog.get("family-swim")
    assert swim["family"] and swim["cost"] == "low"
    swimmer = person(likes=[{"tag": "swimming", "weight": 3}])
    parent = dict(swimmer, kids_at_home=True)
    assert demand.cost_for(swimmer, swim) == "low"
    assert demand.cost_for(parent, swim) == "mid"
    assert demand.fit(dict(parent, budget="low"), swim, SUNDAY, "afternoon")[1] == "over budget"
    assert demand.fit(dict(swimmer, budget="low"), swim, SUNDAY, "afternoon")[1] is None
    assert demand.fit(dict(parent, budget="any"), swim, SUNDAY, "afternoon")[1] is None
    # a free family event stays free, and a grown-ups' outing isn't priced for the kids
    assert demand.cost_for(parent, dict(swim, cost="free")) == "free"
    assert demand.cost_for(parent, catalog.get("cribbage")) == "low"


def test_a_pause_keeps_someone_out_of_every_room_until_the_date():
    # Nov 20 review (Example #59): "swamped with work until January" is a pause, not a no and not
    # a maybe, so code offers nothing before then, and the person is back in play on the date
    kayak = catalog.get("sawyer-paddle")
    paused = person(paused_until="2026-10-01")
    assert demand.fit(paused, kayak, SUNDAY, "afternoon") == (0, "paused until 2026-10-01")
    assert demand.paused_until(paused, SUNDAY) == "2026-10-01"
    back = datetime.date(2026, 10, 4)
    paused["calendar"] = {back.isoformat(): ["afternoon"]}
    assert demand.paused_until(paused, back) is None
    assert demand.fit(paused, kayak, back, "afternoon")[1] is None
    assert demand.fit(person(paused_until=""), kayak, SUNDAY, "afternoon")[1] is None


def test_a_paused_neighbor_is_never_proposed_while_the_rest_of_the_town_is_unchanged():
    people = population.generate(200, seed=7, start=SUNDAY)
    before = demand.propose_groups(people, catalog.ACTIVITIES, SUNDAY)
    busiest = before["groups"][0]["members"][0]["id"]
    for p in people:
        if p["id"] == busiest:
            p["paused_until"] = "2027-01-04"
    after = demand.propose_groups(people, catalog.ACTIVITIES, SUNDAY)
    placed = [m["id"] for g in after["groups"] for m in g["members"]]
    assert busiest not in placed and busiest in after["unplaced"]
    rooms = demand.break_room(people, catalog.ACTIVITIES, SUNDAY)
    assert not any(c["id"] == busiest for r in rooms for c in r["candidates"])


# Nov 24 review (Idan): each of these crashed the whole run; now each is no pause, logged once
BAD_PAUSES = ["January", "2027-1-4", "01/04/2027", "2027-02-30", "2027-01-04 junk", 20270104,
              ["2027-01-04"], True, ""]


def test_a_bad_pause_is_no_pause_and_never_stops_the_run(caplog):
    kayak = catalog.get("sawyer-paddle")
    i = 0
    while i < len(BAD_PAUSES):
        bad = person(id="bad" + str(i), paused_until=BAD_PAUSES[i])
        assert demand.pause_date(bad) is None
        assert demand.paused_until(bad, SUNDAY) is None
        assert demand.fit(bad, kayak, SUNDAY, "afternoon") == (3, None)
        i += 1
    # one warning per bad value, naming the person, however many activities fit checks
    messages = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(messages) == len(BAD_PAUSES) - 1   # an empty value is simply no pause, no warning
    assert "bad0" in messages[0] and "'January'" in messages[0]
    people = population.generate(40, seed=7, start=SUNDAY)
    people[0]["paused_until"] = "January"
    caplog.clear()
    demand.propose_groups(people, catalog.ACTIVITIES, SUNDAY)
    warned = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warned) == 1 and people[0]["id"] in warned[0].getMessage()


def test_a_clean_date_or_date_time_still_pauses_and_a_past_one_does_not():
    kayak = catalog.get("sawyer-paddle")
    future = person(paused_until="2027-01-04")
    assert demand.fit(future, kayak, SUNDAY, "afternoon") == (0, "paused until 2027-01-04")
    timed = person(paused_until="2027-01-04T09:00")
    assert demand.pause_date(timed) == datetime.date(2027, 1, 4)
    assert demand.fit(timed, kayak, SUNDAY, "afternoon") == (0, "paused until 2027-01-04")
    assert demand.pause_date(person(paused_until="2027-01-04T09:00:30")) == datetime.date(2027, 1, 4)
    past = person(paused_until="2026-09-01")
    assert demand.paused_until(past, SUNDAY) is None
    assert demand.fit(past, kayak, SUNDAY, "afternoon") == (3, None)


def _js_pause_dates(values):
    # run the browser copy's pauseDate on each value in node, so both copies are held to one rule
    import json
    import os
    import shutil
    import subprocess
    import pytest
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    here = os.path.dirname(os.path.abspath(__file__))
    js = open(os.path.join(here, "..", "src", "web", "run-clawnly.js")).read()
    start = js.index("  var PAUSE_PATTERN")
    end = js.index("  var COST_LEVELS")
    script = (js[start:end] + "\nvar values = " + json.dumps(values) + ";\n" +
              "var out = []; for (var i = 0; i < values.length; i++) {\n" +
              "  var p = { id: 'p' + i, paused_until: values[i] };\n" +
              "  out.push([pauseDate(p), pausedUntil(p, '2026-09-27')]); }\n" +
              "process.stdout.write(JSON.stringify(out));\n")
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


def test_the_browser_copy_reads_every_pause_the_same_way():
    values = BAD_PAUSES + [None, "2027-01-04", "2027-01-04T09:00", "2027-01-04T09:00:30", "2026-09-01"]
    found = _js_pause_dates(values)
    i = 0
    while i < len(values):
        p = person(paused_until=values[i])
        date = demand.pause_date(p)
        expected = None
        if date is not None:
            expected = date.isoformat()
        assert found[i] == [expected, demand.paused_until(p, SUNDAY)], values[i]
        i += 1


# Nov 25: what writes the pause date (Review #17, from Idan's question on PR #17). The agent turns
# what someone said into a date; anything unclear is None, so the agent asks instead of guessing.
NOV20 = datetime.date(2026, 11, 20)


def test_a_month_with_no_day_means_the_first_of_that_month():
    assert demand.pause_from_words("I'm swamped with work until January", NOV20) == "2027-01-01"
    assert demand.pause_from_words("busy till Feb", NOV20) == "2027-02-01"
    assert demand.pause_from_words("until early January", NOV20) == "2027-01-01"
    assert demand.pause_from_words("until December", NOV20) == "2026-12-01"


def test_a_day_is_kept_and_a_past_day_means_next_year():
    assert demand.pause_from_words("travelling until Jan 15", NOV20) == "2027-01-15"
    assert demand.pause_from_words("out until December 3rd", NOV20) == "2026-12-03"
    assert demand.pause_from_words("out until November 10", NOV20) == "2027-11-10"
    assert demand.pause_from_words("until January 4, 2027", NOV20) == "2027-01-04"
    assert demand.pause_from_words("until mid-January", NOV20) == "2027-01-15"


def test_through_after_or_late_in_a_month_means_the_whole_month():
    assert demand.pause_from_words("slammed through January", NOV20) == "2027-02-01"
    assert demand.pause_from_words("let's talk after January", NOV20) == "2027-02-01"
    assert demand.pause_from_words("until late January", NOV20) == "2027-02-01"
    assert demand.pause_from_words("until the end of December", NOV20) == "2027-01-01"
    assert demand.pause_from_words("through November", NOV20) == "2026-12-01"


def test_vague_or_unreadable_words_set_no_pause_so_the_agent_asks():
    for words in ["after the holidays", "for a while", "until next month", "I may be busy",
                  "until November", "until February 30", "until January 4, 2025", "", None, 42]:
        assert demand.pause_from_words(words, NOV20) is None, words


def test_an_iso_date_in_the_words_is_used_when_it_is_still_ahead():
    assert demand.pause_from_words("paused until 2027-01-04", NOV20) == "2027-01-04"
    assert demand.pause_from_words("until 2026-11-01", NOV20) is None
    assert demand.pause_from_words("until 2027-13-01", NOV20) is None


def test_the_written_date_is_what_keeps_ben_out_until_january():
    # Example #59: Ben K. tells his agent on Nov 20 he's swamped until January
    ben = {"id": "ben", "paused_until": demand.pause_from_words("swamped with work until January", NOV20)}
    assert demand.paused_until(ben, datetime.date(2026, 12, 15)) == "2027-01-01"
    assert demand.paused_until(ben, datetime.date(2027, 1, 1)) is None
