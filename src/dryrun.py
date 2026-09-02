"""Pre-launch dry run: drives N AI-generated personas through the REAL
neighborhood-pilot pipeline end to end, so you can see it actually work
before inviting real residents.

This is a dev/ops tool, not part of the app -- it calls the exact same
functions the live routes call (onboarding.take_turn, batch.force_trigger_
batch, my_match.get_state/respond), so it's a faithful test of the real
pipeline's AI behavior, not just its plumbing (that part's already covered
by pytest). The ONLY thing scripted here is the "resident" side of the
onboarding conversation: each persona is played by its own simulated=True
Claw (persona_gen.generate_users -- the same invented-cast generator the
admin console already uses), answering naturally in character. The Claw on
the OTHER end of that conversation -- the one actually being tested -- is
100% real production code, running simulated=False, learning about each
persona only through what it says, exactly like a real resident's onboarding.

Uses REAL Anthropic API calls (small but nonzero cost: onboarding chat +
extraction per persona turn, plus one real match/negotiation/popup run).
Writes to an ISOLATED database by default (never clawnly.db) -- see DB_PATH
below. Sequential, not concurrent, so the printed transcript stays readable.

Two modes (DRYRUN_MODE):
  chat (default) -- each persona has a full simulated onboarding conversation
    (a second Claw, simulated=True, plays the resident) before the batch
    trigger. Faithful end-to-end test of onboarding INCLUDING the chat/
    extraction loop, but that's O(turns) real calls per persona -- fine for a
    handful of people, not for a realistic-size cohort.
  bulk -- for testing matching QUALITY/DIVERSITY at real scale (e.g. the
    actual 100-person batch threshold). Skips the chat simulation (already
    proven by "chat" mode) and seeds each resident's profile directly from
    its generated persona, then runs ONE real batch. Still 100% the real,
    unmodified run_pipeline/master_claw/negotiation/popup code -- just not
    re-paying for the chat-to-extraction step every time.

Run:              .venv/bin/python src/dryrun.py
Override count:   DRYRUN_COUNT=4 DRYRUN_THEME="..." .venv/bin/python src/dryrun.py
Bulk at scale:     DRYRUN_MODE=bulk DRYRUN_COUNT=100 .venv/bin/python src/dryrun.py
Cheaper matching:  DRYRUN_MATCH_EFFORT=low  (overrides config.MATCH_EFFORT for THIS
                   process only -- never the real deployment; costs some match quality)
"""

import asyncio
import os
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DB = os.path.join(os.path.dirname(_HERE), "clawnly_dryrun.db")
# db.py reads CLAWNLY_DB_PATH at import time -- must be set before `import db`,
# same technique tests/conftest.py uses to isolate the test database.
os.environ.setdefault("CLAWNLY_DB_PATH", _DEFAULT_DB)

import batch
import config
import db
import my_match
import onboarding
from claw import Claw
from persona_gen import generate_users, DEFAULT_THEME

# dry-run-only cost lever: overrides the in-memory config.MATCH_EFFORT value
# for THIS PROCESS ONLY -- never touches config.py or any real deployment.
# Lower effort = cheaper/faster match-forming calls at some quality cost;
# fine for iterating on a throwaway dry run, never for the real launch
# (config.MATCH_EFFORT stays "medium" there, untouched).
_effort_override = os.environ.get("DRYRUN_MATCH_EFFORT")
if _effort_override:
    config.MATCH_EFFORT = _effort_override

PERSONA_COUNT = int(os.environ.get("DRYRUN_COUNT", "3"))
THEME = os.environ.get("DRYRUN_THEME", DEFAULT_THEME)
MODE = os.environ.get("DRYRUN_MODE", "chat")
MAX_ONBOARDING_TURNS = 15   # a safety margin under onboarding.MAX_ONBOARDING_TURNS (20)

_BULK_PROFILE_FIELDS = ["name", "age", "gender", "hobbies", "personality", "occupation",
                         "availability", "location", "bio", "preferred_group_size"]


def _all_slots_true():
    slots = {}
    i = 0
    while i < len(onboarding.SLOT_NAMES):
        slots[onboarding.SLOT_NAMES[i]] = True
        i += 1
    return slots


def _rule(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


async def _persona_opener(persona_claw):
    prompt = ("Write a brief, natural opening message (1-2 sentences) to start a "
              "conversation with your neighborhood's onboarding assistant, introducing "
              "yourself casually the way you actually would.")
    return await persona_claw.chat(prompt, [])


async def _run_onboarding_for(resident, persona_profile, client):
    # persona_claw is the FAKE human -- an invented, simulated=True Claw playing
    # the persona so it answers in character rather than dumping its profile.
    persona_claw = Claw(persona_profile, client=client, simulated=True)
    persona_history = []
    message = await _persona_opener(persona_claw)
    persona_history.append({"role": "assistant", "content": message})

    turn = 0
    while turn < MAX_ONBOARDING_TURNS:
        result = await onboarding.take_turn(resident, message, client=client)
        turn += 1
        print("  [{}] resident: {}".format(turn, message))
        print("  [{}] claw:     {}".format(turn, result["reply"]))
        if result["complete"]:
            print("  -> profile complete after {} turn(s).".format(turn))
            return
        persona_history.append({"role": "user", "content": result["reply"]})
        message = await persona_claw.chat(result["reply"], persona_history[:-1])
        persona_history.append({"role": "assistant", "content": message})

    print("  -> hit the dry-run turn cap ({}) without completing.".format(MAX_ONBOARDING_TURNS))


def _profile_diff_lines(persona_profile, resident):
    fields = ["name", "age", "gender", "hobbies", "personality", "occupation",
              "availability", "location", "bio", "preferred_group_size"]
    lines = []
    i = 0
    while i < len(fields):
        key = fields[i]
        lines.append("    {:<20} generated={!r:<40} extracted={!r}".format(
            key, persona_profile.get(key), resident.get(key)))
        i += 1
    return lines


def _bulk_seed_resident(resident, persona):
    # skips the onboarding conversation entirely -- directly writes the
    # generated persona's fields onto the resident row, same field names
    # throughout, and marks the profile complete. Only for bulk-mode
    # scale-testing; a real resident always goes through the real chat.
    fields = {}
    i = 0
    while i < len(_BULK_PROFILE_FIELDS):
        key = _BULK_PROFILE_FIELDS[i]
        fields[key] = persona[key]
        i += 1
    fields["slots_status"] = _all_slots_true()
    db.update_resident_profile(resident["id"], fields)
    db.mark_profile_complete(resident["id"])


def _lookup_by_rid(residents):
    lookup = {}
    i = 0
    while i < len(residents):
        persona, resident = residents[i]
        lookup["r" + str(resident["id"])] = (persona, resident)
        i += 1
    return lookup


def _print_bulk_summary(run_id, lookup):
    result = db.load_run_result(run_id)
    groups = result["groups"]
    unmatched = result["unmatched"]
    _rule("{} group(s) formed, {} unmatched (of {})".format(
        len(groups), len(unmatched), len(lookup)))

    i = 0
    while i < len(groups):
        match = groups[i]["match"]
        names = []
        j = 0
        while j < len(match["group"]):
            member = lookup.get(match["group"][j])
            if member is not None:
                names.append(member[0]["name"])
            j += 1
        print("\nGroup {}: {}".format(i + 1, ", ".join(names)))
        print("  Reason: " + match["reason"])
        negotiation = groups[i]["negotiation"]
        if negotiation is not None:
            print("  Negotiation: agreed={} activity={}".format(
                negotiation["agreed"], negotiation.get("activity")))
        popup = groups[i]["popup"]
        if popup is not None:
            print("  Meetup: {} -- {} @ {}".format(
                popup.get("event_name"), popup.get("time"), popup.get("location")))
        i += 1

    if len(unmatched) > 0:
        names = []
        i = 0
        while i < len(unmatched):
            member = lookup.get(unmatched[i])
            if member is not None:
                names.append(member[0]["name"])
            i += 1
        print("\nUnmatched ({}): {}".format(len(names), ", ".join(names)))


def _accept_all_pending(lookup):
    # cheap (no AI calls) -- exercises the real accept/seal DB path for
    # every resident in every formed group, not just a sample.
    keys = list(lookup.keys())
    accepted = 0
    sealed_sample = None
    i = 0
    while i < len(keys):
        persona, resident = lookup[keys[i]]
        resident_row = db.get_resident(resident["id"])
        state = my_match.get_state(resident_row)
        if state["state"] == "pending":
            state, error = my_match.respond(resident_row, state["match_id"], "accept")
            if error is None:
                accepted += 1
                if state["state"] == "sealed" and sealed_sample is None:
                    sealed_sample = (persona, state)
        i += 1
    print("\nAccepted {} pending response(s).".format(accepted))
    if sealed_sample is not None:
        persona, state = sealed_sample
        _rule("Example sealed match, from {}'s perspective".format(persona["name"]))
        print("  Reason: " + state["reason"])
        print("  Other members: " + ", ".join(state["other_first_names"]))
        if state["meetup"] is not None:
            meetup = state["meetup"]
            print("  Meetup: {} -- {} @ {} ({})".format(
                meetup.get("event_name"), meetup.get("time"),
                meetup.get("location"), meetup.get("reason")))


async def main():
    print("Using database: " + db.DB_PATH)
    print("Mode: {}  |  match effort: {}".format(MODE, config.MATCH_EFFORT))
    if db.DB_PATH == os.path.join(os.path.dirname(_HERE), "clawnly.db"):
        print("REFUSING to run against the real clawnly.db -- set CLAWNLY_DB_PATH "
              "explicitly if you really mean to (not recommended).")
        return
    db.init_db()

    client = config.get_client()   # the real key -- this run costs real money

    slug = "dryrun-" + str(int(time.time()))
    neighborhood = db.get_or_create_neighborhood(slug, "Dry Run", PERSONA_COUNT)
    print("Neighborhood: {} (id={}, threshold={})".format(slug, neighborhood["id"], PERSONA_COUNT))

    _rule("Generating {} AI personas (theme: {})".format(PERSONA_COUNT, THEME))
    personas = await generate_users(count=PERSONA_COUNT, theme=THEME, client=client)
    residents = []
    i = 0
    while i < len(personas):
        persona = personas[i]
        email = "dryrun-{}-{}@example.com".format(slug, i)
        resident = db.get_or_create_resident(neighborhood["id"], email, "magic_link")
        db.record_consent(resident["id"])
        print("  {} -- {}, {}, {}".format(persona["name"], persona["age"],
                                           persona["personality"], persona["occupation"]))
        residents.append((persona, resident))
        i += 1

    if MODE == "bulk":
        _rule("Bulk-seeding {} profiles directly (skipping the chat simulation)".format(len(residents)))
        i = 0
        while i < len(residents):
            persona, resident = residents[i]
            _bulk_seed_resident(resident, persona)
            i += 1
        print("All {} profiles marked complete.".format(len(residents)))
    else:
        i = 0
        while i < len(residents):
            persona, resident = residents[i]
            _rule("Onboarding: {}".format(persona["name"]))
            await _run_onboarding_for(resident, persona, client)
            i += 1

    _rule("Triggering the batch run for real (match + negotiation + popup)")
    run_id, error = await batch.force_trigger_batch(neighborhood["id"], client=client)
    if error is not None:
        print("Batch did not run: " + error)
        return
    print("Batch run id: " + str(run_id))

    if MODE == "bulk":
        lookup = _lookup_by_rid(residents)
        _print_bulk_summary(run_id, lookup)
        _accept_all_pending(lookup)
        return

    _rule("Everyone accepts their match")
    i = 0
    while i < len(residents):
        _, resident = residents[i]
        resident_row = db.get_resident(resident["id"])
        state = my_match.get_state(resident_row)
        print("  {}: {}".format(resident_row["name"] or resident_row["email"], state["state"]))
        if state["state"] == "pending":
            state, error = my_match.respond(resident_row, state["match_id"], "accept")
            if error is not None:
                print("    accept failed: " + error)
        i += 1

    _rule("Final state")
    i = 0
    while i < len(residents):
        persona, resident = residents[i]
        resident_row = db.get_resident(resident["id"])
        state = my_match.get_state(resident_row)
        print("\n{} ({}):".format(resident_row["name"] or resident_row["email"], state["state"]))
        print("  Extracted vs. generated profile:")
        for line in _profile_diff_lines(persona, resident_row):
            print(line)
        if state["state"] == "sealed":
            print("  Reason: " + state["reason"])
            print("  Other members: " + ", ".join(state["other_first_names"]))
            if state["meetup"] is not None:
                meetup = state["meetup"]
                print("  Meetup: {} -- {} @ {} ({})".format(
                    meetup.get("event_name"), meetup.get("time"),
                    meetup.get("location"), meetup.get("reason")))
            else:
                print("  Meetup: " + str(state.get("note")))
        i += 1


if __name__ == "__main__":
    asyncio.run(main())
