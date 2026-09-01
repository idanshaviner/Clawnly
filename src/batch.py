"""Batch trigger: fires the existing matching pipeline once a neighborhood's
profile-complete resident count crosses its snapshotted batch_threshold.

No scheduler or poller -- see docs/PILOT_PLAN.md's "Background trigger": the
only event that can ever cross the threshold is a resident's own onboarding
completing, so check_and_trigger_batch(neighborhood_id) is called
synchronously right after that (src/onboarding.py's take_turn, fire-and-forget
via asyncio.create_task -- the same pattern /api/run-stream already uses).

Complete residents are mapped into the exact profile-dict shape run_pipeline /
MasterClaw / Claw(simulated=True) already expect -- every field is REQUIRED
there (Claw._system_prompt indexes u["field"] directly, no .get), so anything
onboarding never captured gets a plain, honest-sounding default rather than
crashing or blocking the run (see resident_to_profile). run_pipeline() itself
is called completely unmodified.
"""

import json

import config
import db
from main import run_pipeline
from users import AVAILABILITY_WINDOWS, HOBBY_CATEGORIES


_VALID_PERSONALITY = ["introverted", "extroverted", "mixed"]
_VALID_OCCUPATION = ["student", "working professional", "freelancer"]
# broad, always-valid fallbacks (both exist in users.HOBBY_CATEGORIES /
# AVAILABILITY_WINDOWS) for a resident who is complete on the five gating
# slots but whose best-effort extraction never caught one of the OTHER
# profile columns (see onboarding.py's SLOT_NAMES vs RESIDENT_PROFILE_FIELDS).
_DEFAULT_HOBBIES = ["reading", "hiking"]
_DEFAULT_AVAILABILITY = ["weekday_evening", "weekend_daytime"]
_DEFAULT_AGE = 30


def _hobby_lookup():
    lookup = {}
    categories = list(HOBBY_CATEGORIES.keys())
    i = 0
    while i < len(categories):
        hobbies = HOBBY_CATEGORIES[categories[i]]
        j = 0
        while j < len(hobbies):
            lookup[hobbies[j]] = True
            j += 1
        i += 1
    return lookup


def _valid_hobbies(values):
    if not isinstance(values, list):
        return None
    lookup = _hobby_lookup()
    out = []
    i = 0
    while i < len(values):
        if values[i] in lookup and values[i] not in out:
            out.append(values[i])
        i += 1
    if len(out) == 0:
        return None
    return out


def _valid_availability(values):
    if not isinstance(values, list):
        return None
    out = []
    i = 0
    while i < len(values):
        if values[i] in AVAILABILITY_WINDOWS and values[i] not in out:
            out.append(values[i])
        i += 1
    if len(out) == 0:
        return None
    return out


def _valid_group_size(value):
    if value == "no preference":
        return value
    if isinstance(value, list) and len(value) == 2:
        low = value[0]
        high = value[1]
        if isinstance(low, int) and isinstance(high, int) and 2 <= low <= high <= 8:
            return [low, high]
    return None


def resident_to_profile(resident, neighborhood):
    # "r" + resident id -- so there's no possible collision with the demo
    # cast's "u01"-style ids in the same run.
    name = resident.get("name")
    if not name:
        name = "Neighbor"
    age = resident.get("age")
    if not isinstance(age, int) or isinstance(age, bool):
        age = _DEFAULT_AGE
    gender = resident.get("gender")
    if not gender:
        gender = "unspecified"
    personality = resident.get("personality")
    if personality not in _VALID_PERSONALITY:
        personality = "mixed"
    occupation = resident.get("occupation")
    if occupation not in _VALID_OCCUPATION:
        occupation = "working professional"
    hobbies = _valid_hobbies(resident.get("hobbies"))
    if hobbies is None:
        hobbies = list(_DEFAULT_HOBBIES)
    availability = _valid_availability(resident.get("availability"))
    if availability is None:
        availability = list(_DEFAULT_AVAILABILITY)
    location = resident.get("location")
    if not location:
        location = neighborhood["name"]
    bio = resident.get("bio")
    if not bio:
        bio = "A " + neighborhood["name"] + " neighbor getting to know the group."
    size = _valid_group_size(resident.get("preferred_group_size"))
    if size is None:
        size = "no preference"

    return {
        "id": "r" + str(resident["id"]),
        "name": name, "age": age, "gender": gender, "hobbies": hobbies,
        "personality": personality, "occupation": occupation,
        "availability": availability, "location": location, "bio": bio,
        "preferred_group_size": size,
    }


async def check_and_trigger_batch(neighborhood_id, client=None):
    # called right after a resident's profile completes. Cheap early-outs
    # (unknown neighborhood, below threshold) never touch the CAS, so almost
    # every call is a single fast SELECT.
    neighborhood = db.get_neighborhood(neighborhood_id)
    if neighborhood is None:
        return

    complete = db.list_complete_residents(neighborhood_id)
    if len(complete) < neighborhood["batch_threshold"]:
        return

    won = db.try_trigger_batch(neighborhood_id)
    if not won:
        return   # another near-simultaneous completion already triggered this batch

    profiles = []
    i = 0
    while i < len(complete):
        profiles.append(resident_to_profile(complete[i], neighborhood))
        i += 1

    if client is None:
        client = config.get_client()

    # real resident data is always run live (same reasoning as onboarding.py:
    # this is private, authenticated, real conversation data, never the
    # demo/BYOK toggles the public admin console uses).
    try:
        result = await run_pipeline(profiles, client=client, verbose=False)
    except Exception as error:
        # the CAS already fired, so this neighborhood's one-shot trigger is
        # spent -- an operator has to intervene (Stage 6's admin surface) if
        # this happens. Not swallowing it silently, but not crashing the
        # fire-and-forget task's caller either (same failure-isolation
        # philosophy as onboarding.py's extraction-call try/except).
        print("[batch] neighborhood {} pipeline run failed: {}".format(neighborhood_id, error))
        return

    signature = json.dumps(profiles, sort_keys=True)
    db.persist_run_result("live", signature, result, neighborhood_id=neighborhood_id)
