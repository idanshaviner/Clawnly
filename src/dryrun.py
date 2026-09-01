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

Run:  .venv/bin/python src/dryrun.py
Override persona count / theme:  DRYRUN_COUNT=4 DRYRUN_THEME="..." .venv/bin/python src/dryrun.py
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

PERSONA_COUNT = int(os.environ.get("DRYRUN_COUNT", "3"))
THEME = os.environ.get("DRYRUN_THEME", DEFAULT_THEME)
MAX_ONBOARDING_TURNS = 15   # a safety margin under onboarding.MAX_ONBOARDING_TURNS (20)


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


async def main():
    print("Using database: " + db.DB_PATH)
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
