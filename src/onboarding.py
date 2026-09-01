"""Real-resident onboarding: a persisted, multi-turn conversation with the
resident's own (simulated=False) Claw that gradually fills in their profile.

Two AI calls per user turn:
  1. the conversational reply itself (config.MODEL_ONBOARDING_CHAT, via Claw.chat)
  2. a cheap structured read of the whole transcript so far
     (config.MODEL_ONBOARDING_COMPLETENESS) that reports which of the five
     gating slots are genuinely evidenced, plus best-effort values for the
     rest of the profile columns.

This is a private, authenticated, real-data flow -- always the server's own
client (config.get_client()), never the demo/BYOK toggles the public admin
console uses; a real resident's data should never be tested against scripted
fake replies (see claw.py's REAL_ONBOARDING_STYLE and PILOT_PLAN.md: "no
ChatGPT-history import -- the Claw conversation is the only way the system
learns about someone").
"""

import asyncio

import batch
import config
import db
from claw import Claw
from llm_io import join_text, extract_json
from users import HOBBY_CATEGORIES, AVAILABILITY_WINDOWS


# the five slots PILOT_PLAN.md names as gating profile_complete_at. The extra
# resident columns (name/age/gender/location/occupation/bio) are filled in
# best-effort by the same extraction call but never block completion.
SLOT_NAMES = ["personality_energy", "interests", "availability", "group_size", "seeking"]

# a hard safety valve, same pattern as master_claw.py's MAX_MATCH_ATTEMPTS --
# force-complete with whatever's gathered rather than let a conversation loop
# forever.
MAX_ONBOARDING_TURNS = 20


def _hobby_menu():
    lines = []
    cats = list(HOBBY_CATEGORIES.keys())
    i = 0
    while i < len(cats):
        lines.append("  {}: {}".format(cats[i], ", ".join(HOBBY_CATEGORIES[cats[i]])))
        i += 1
    return "\n".join(lines)


def _hobby_lookup():
    lookup = {}
    cats = list(HOBBY_CATEGORIES.keys())
    i = 0
    while i < len(cats):
        hobbies = HOBBY_CATEGORIES[cats[i]]
        j = 0
        while j < len(hobbies):
            lookup[hobbies[j]] = True
            j += 1
        i += 1
    return lookup


def _extraction_system_prompt():
    # "personality_energy" (a SLOT_NAMES literal) doubles as the marker
    # tests/conftest.py's FakeClient routes this call kind on.
    lines = [
        "You read a real person's onboarding conversation with their own AI companion for a",
        "friendship-matching app, and report ONLY what they have actually said about",
        "themselves so far -- never guess or infer something that was not actually stated.",
        "",
        "Return a JSON object with two keys, \"slots\" and \"fields\".",
        "",
        "\"slots\": an object with exactly these five boolean keys, true ONLY when the",
        "transcript gives genuine, specific evidence for it (a vague hint is NOT enough):",
        "  " + ", ".join(SLOT_NAMES),
        "",
        "\"fields\": best-effort extracted values, null for anything not yet mentioned:",
        "  name (string), age (integer), gender (string), personality (string, their",
        "  energy/personality in their own terms), occupation (string, life stage), bio",
        "  (1-2 sentences summarizing them in their voice), location (string, neighborhood",
        "  if mentioned), hobbies (list, ONLY from the menu below using the exact words),",
        "  availability (list, ONLY from: {}),".format(", ".join(AVAILABILITY_WINDOWS)),
        "  preferred_group_size ([min, max] with 2 <= min <= max <= 8, or the string",
        "  \"no preference\").",
        "",
        "Hobby menu (pick only from here, exact words):",
        _hobby_menu(),
        "",
        "Respond with the JSON object ONLY -- no markdown fences, no text before or after it.",
    ]
    return "\n".join(lines)


def _transcript_text(history):
    lines = []
    i = 0
    while i < len(history):
        turn = history[i]
        speaker = "Resident"
        if turn["role"] == "assistant":
            speaker = "Claw"
        lines.append(speaker + ": " + turn["content"])
        i += 1
    return "\n".join(lines)


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


def _valid_group_size(value):
    if value == "no preference":
        return value
    if isinstance(value, list) and len(value) == 2:
        low = value[0]
        high = value[1]
        if isinstance(low, int) and isinstance(high, int) and 2 <= low <= high <= 8:
            return [low, high]
    return None


_TEXT_FIELDS = ["name", "gender", "personality", "occupation", "bio", "location"]


def _clean_fields(raw):
    # only keep values that are present, non-empty, and (for the closed-
    # vocabulary fields) actually valid -- never persist something the model
    # made up outside the allowed lists.
    if not isinstance(raw, dict):
        return {}
    out = {}
    i = 0
    while i < len(_TEXT_FIELDS):
        key = _TEXT_FIELDS[i]
        value = raw.get(key)
        if isinstance(value, str) and len(value.strip()) > 0:
            out[key] = value.strip()
        i += 1
    age = raw.get("age")
    if isinstance(age, int) and not isinstance(age, bool) and 13 <= age <= 100:
        out["age"] = age
    availability = _valid_availability(raw.get("availability"))
    if availability is not None:
        out["availability"] = availability
    hobbies = _valid_hobbies(raw.get("hobbies"))
    if hobbies is not None:
        out["hobbies"] = hobbies
    size = _valid_group_size(raw.get("preferred_group_size"))
    if size is not None:
        out["preferred_group_size"] = size
    return out


def _clean_slots(raw):
    if not isinstance(raw, dict):
        raw = {}
    slots = {}
    i = 0
    while i < len(SLOT_NAMES):
        name = SLOT_NAMES[i]
        slots[name] = raw.get(name) is True
        i += 1
    return slots


def _count_user_turns(history):
    count = 0
    i = 0
    while i < len(history):
        if history[i]["role"] == "user":
            count += 1
        i += 1
    return count


async def _extract(history, client):
    prompt = "Onboarding conversation so far:\n\n" + _transcript_text(history)
    message = await client.messages.create(
        model=config.MODEL_ONBOARDING_COMPLETENESS,
        max_tokens=700,
        system=_extraction_system_prompt(),
        messages=[{"role": "user", "content": prompt}],
    )
    parsed = extract_json(join_text(message))
    if parsed is None:
        parsed = {}
    fields = _clean_fields(parsed.get("fields"))
    slots = _clean_slots(parsed.get("slots"))
    return fields, slots


async def take_turn(resident, message, client=None):
    # one full onboarding turn: the resident's own Claw replies, both sides of
    # the exchange are persisted, then a cheap structured pass over the whole
    # transcript so far updates the profile and checks completeness.
    if client is None:
        client = config.get_client()
    resident_id = resident["id"]
    history = db.get_onboarding_messages(resident_id)
    claw = Claw(resident, client=client, simulated=False)
    reply = await claw.chat(message, history)

    db.save_onboarding_message(resident_id, "user", message)
    db.save_onboarding_message(resident_id, "assistant", reply)
    full_history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ]

    # the conversational reply above is the part the resident is waiting on;
    # both sides of it are already persisted. A hiccup in this second, cheap,
    # best-effort bookkeeping call must not turn an otherwise-successful turn
    # into a visible error -- worst case, this turn's profile update /
    # completeness check is just picked up on the next turn instead.
    slots = _clean_slots(resident.get("slots_status"))
    updated = resident
    try:
        fields, slots = await _extract(full_history, client)
        updates = dict(fields)
        updates["slots_status"] = slots
        updated = db.update_resident_profile(resident_id, updates)
    except Exception as error:
        print("[onboarding] extraction call failed for resident {}: {}".format(resident_id, error))

    turn_count = _count_user_turns(full_history)
    complete = all(slots.values()) or turn_count >= MAX_ONBOARDING_TURNS
    if complete:
        updated = db.mark_profile_complete(resident_id)
        # fire-and-forget, same pattern /api/run-stream already uses -- the
        # resident's reply above must not wait on (or fail because of) a
        # neighborhood-wide batch run that this one completion might trigger.
        asyncio.create_task(batch.check_and_trigger_batch(resident["neighborhood_id"]))

    return {
        "reply": reply,
        "complete": updated["profile_complete_at"] is not None,
        "slots_status": slots,
    }
