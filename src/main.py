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
    _header("INTERVIEWS")
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
    _header("MATCH + REASONING")
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
    _header("NEGOTIATION (live)")
    transcript = plan["transcript"]
    i = 0
    while i < len(transcript):
        e = transcript[i]
        if e["type"] == "propose":
            print("\n[Round {}] Master Claw proposes: {}".format(e["round"], e["activity"]))
            print('  "{}"'.format(e["pitch"]))
        elif e["type"] == "reaction":
            print("  {} > {}".format(e["name"], e["text"]))
        elif e["type"] == "assess":
            if e["agreed"]:
                print("  -> Master Claw: everyone's on board. Settled.")
            else:
                print("  -> Master Claw: not yet -- {}".format(e["concern"]))
        i += 1
    if plan["agreed"]:
        print("\nAgreed activity: {}".format(plan["activity"]))
    else:
        print("\nNo full agreement after {} rounds; best option: {}".format(plan["rounds"], plan["activity"]))


def _print_no_plan(plan):
    _header("NO MEETUP -- GROUP DIDN'T FULLY AGREE")
    print("")
    print("  The group is a good match, but couldn't settle on a plan everyone loved")
    print("  after {} rounds. No meetup is sent until it's right for all of them.".format(plan.get("rounds")))
    concern = plan.get("concern", "")
    if len(concern) > 0:
        print("  Sticking point: {}".format(concern))


def _print_popup(popup):
    _header("MEETUP")
    print("")
    print("  +" + "-" * 50 + "+")
    print("  | {}".format(popup["event_name"]))
    print("  | activity : {}".format(popup["activity"]))
    print("  | where    : {}".format(popup["location"]))
    print("  | when     : {}".format(popup["time"]))
    print("  | who       : {}".format(", ".join(popup["matched_users"])))
    print("  | why      : {}".format(popup["reason"]))
    print("  +" + "-" * 50 + "+")


async def run_pipeline(users, client=None, verbose=True, interviews=None, on_stage=None, feedback=None):
    # Always partition EVERYONE into compatible groups; then each group negotiates
    # its own plan and gets a meetup. verbose prints to the console (the CLI).
    # `interviews`, if given, is reused (skips the 12 interview calls).
    # `feedback` is past human ratings the matcher learns from.
    # on_stage(stage, data), if given, streams the run live for the web app.
    master = MasterClaw(users, client=client, feedback=feedback)

    def emit(stage, data):
        if on_stage is not None:
            on_stage(stage, data)

    if interviews is None:
        interviews = await master.interview_claws()
    if verbose:
        _print_interviews(interviews)
    emit("interviews", interviews)

    # form every group the pool supports (streamed as each forms).
    counter = [0]

    def group_event(match):
        emit("group", {"index": counter[0], "match": match})
        counter[0] += 1

    partition = await master.find_all_matches(interviews, on_group=group_event)
    groups = partition["groups"]
    unmatched = partition["unmatched"]

    # each group negotiates a plan and gets a meetup.
    group_results = []
    gi = 0
    while gi < len(groups):
        match = groups[gi]
        ids = match["group"]
        matched_users = []
        matched_claws = []
        j = 0
        while j < len(ids):
            matched_users.append(master.users_by_id[ids[j]])
            matched_claws.append(master.claws_by_id[ids[j]])
            j += 1

        if verbose:
            print("\n########## GROUP {} ##########".format(gi + 1))
            _print_match(match, master.users_by_id)

        def neg_event(entry, idx=gi):
            emit("negotiation", {"index": idx, "entry": entry})

        plan = await negotiate(matched_claws, interviews, client=master.client, on_event=neg_event)
        if verbose:
            _print_negotiation(plan)
        emit("negotiation_done", {"index": gi, "plan": plan})

        # Only turn a plan into a real meetup once the WHOLE group is on board. If
        # they couldn't agree, ship no meetup -- show the sticking point instead.
        popup = None
        if plan.get("agreed"):
            popup = await generate_popup(matched_users, match["reason"],
                                         suggested_activity=plan.get("activity"), client=master.client)
            if verbose:
                _print_popup(popup)
            emit("popup", {"index": gi, "popup": popup})
        else:
            if verbose:
                _print_no_plan(plan)
            emit("no_plan", {"index": gi, "concern": plan.get("concern", "")})

        group_results.append({"match": match, "negotiation": plan, "popup": popup})
        gi += 1

    result = {"interviews": interviews, "groups": group_results, "unmatched": unmatched}
    if hasattr(master.client, "counter"):
        result["usage"] = master.client.counter
    emit("done", result)
    return result


if __name__ == "__main__":
    asyncio.run(run_pipeline(USERS))
