"""Entry point: run the full matchmaker pipeline and print each stage.

interview -> match -> popup, with clear section headers (SPEC F5, section 7).
The work lives in run_pipeline(users, client) so it can be tested with an
injected client; __main__ runs it for real.
"""

import asyncio

from master_claw import MasterClaw
from negotiation import negotiate
from popup import generate_popup
from users import USERS


def _header(title):
    print("")
    print("=" * 60)
    print(title)
    print("=" * 60)


def _print_interviews(interviews):
    _header("STEP 1 - INTERVIEWS")
    ids = list(interviews.keys())
    i = 0
    while i < len(ids):
        record = interviews[ids[i]]
        name = record["profile"]["name"]
        if "error" in record:
            print("\n[{}] {} - interview failed: {}".format(ids[i], name, record["error"]))
        else:
            print("\n[{}] {}".format(ids[i], name))
            print("  looking for : {}".format(record["q1"]))
            print("  availability: {}".format(record["q2"]))
        i += 1


def _print_match(matches, users_by_id):
    _header("STEP 2 - MATCH + REASONING")
    group = matches["group"]
    if len(group) == 0:
        print("\nNo viable group this round (a correct outcome, not a failure):")
        print("  {}".format(matches["reason"]))
        return

    print("\nChosen group:")
    i = 0
    while i < len(group):
        member = users_by_id[group[i]]
        print("  - {} ({}, {})".format(member["name"], member["personality"], member["location"]))
        i += 1

    print("\nScores (1-5):")
    scores = matches["scores"]
    keys = list(scores.keys())
    i = 0
    while i < len(keys):
        print("  {:<12}: {}".format(keys[i], scores[keys[i]]))
        i += 1

    print("\nWhy this group:")
    print("  {}".format(matches["reason"]))

    why_not = matches["why_not"]
    if len(why_not) > 0:
        print("\nWhy not others:")
        i = 0
        while i < len(why_not):
            entry = why_not[i]
            name = users_by_id.get(entry.get("id"), {}).get("name", entry.get("id"))
            print("  - {}: {}".format(name, entry.get("reason", "")))
            i += 1


def _print_negotiation(plan):
    _header("STEP 3 - NEGOTIATION (common ground + joint plan)")
    common = plan.get("common_ground", [])
    if len(common) > 0:
        print("\nCommon ground:")
        i = 0
        while i < len(common):
            print("  - {}".format(common[i]))
            i += 1
    print("\nProposed activity:")
    print("  {}".format(plan.get("activity", "")))
    if len(plan.get("rationale", "")) > 0:
        print("\nWhy it works:")
        print("  {}".format(plan["rationale"]))
    reactions = plan.get("reactions", [])
    if len(reactions) > 0:
        print("\nThe group reacts:")
        i = 0
        while i < len(reactions):
            r = reactions[i]
            print("  {} > {}".format(r.get("name", ""), r.get("reaction", "")))
            i += 1


def _print_popup(popup):
    _header("STEP 4 - MEETUP POPUP")
    print("")
    print("  +" + "-" * 50 + "+")
    print("  | {}".format(popup["event_name"]))
    print("  | activity : {}".format(popup["activity"]))
    print("  | where    : {}".format(popup["location"]))
    print("  | when     : {}".format(popup["time"]))
    print("  | who       : {}".format(", ".join(popup["matched_users"])))
    print("  | why      : {}".format(popup["reason"]))
    print("  +" + "-" * 50 + "+")


async def run_pipeline(users, client=None):
    master = MasterClaw(users, client=client)

    interviews = await master.interview_claws()
    _print_interviews(interviews)

    matches = await master.find_matches(interviews)
    _print_match(matches, master.users_by_id)

    # no viable group -> print the reason and stop cleanly (no popup).
    if len(matches["group"]) == 0:
        return {"interviews": interviews, "matches": matches, "popup": None}

    # map matched ids to full profiles for negotiation + popup.
    matched_users = []
    i = 0
    while i < len(matches["group"]):
        matched_users.append(master.users_by_id[matches["group"][i]])
        i += 1

    # the parent agent brokers common ground + a joint activity.
    plan = await negotiate(matched_users, interviews, client=master.client)
    _print_negotiation(plan)

    # the popup is built around the agreed activity.
    popup = await generate_popup(matched_users, matches["reason"],
                                 suggested_activity=plan.get("activity"), client=master.client)
    _print_popup(popup)

    return {"interviews": interviews, "matches": matches, "negotiation": plan, "popup": popup}


if __name__ == "__main__":
    asyncio.run(run_pipeline(USERS))
