"""The hub (Master Claw) for agent-to-agent matching.

One round, start to finish, with no human involved until the invitation:
  1. PAIR   -- the hub reads everyone's card and picks which agents should talk.
               Code rejects unknown ids, self-pairs, repeats, and anyone over
               the per-person / per-round limits (clean_pairs).
  2. TALK   -- each chosen pair has a private Claw-to-Claw conversation
               (agent_talk.converse), a few pairs at a time.
  3. JUDGE  -- the hub reads the transcript and returns depth 1-10, its
               reasoning, risks, evidence quotes and an invitation.
  4. GATE   -- code, not the model, decides whether an invitation goes out:
               the hub must recommend it, depth >= DEPTH_BAR, at least
               MIN_VERIFIED_EVIDENCE quotes must appear word for word in the
               transcript (any other quote is discarded as made up), and those
               quotes must come from BOTH agents (so one person's pasted text
               can't manufacture the evidence on its own).

Every step is written to db.events as it happens (the behind-the-scenes log),
every conversation + verdict to db.agent_conversations, and every Claude call
verbatim to db.ai_calls (ai_log.LoggedClient).

Run it on the fictional sample people (real API calls, needs a key):
    .venv/bin/python src/orchestrator.py
"""

import asyncio
import re

import ai_log
import config
import db
import dossier
from agent_talk import converse, transcript_text
from llm_io import join_text, extract_json


PAIRS_PER_ROUND = 6
MAX_PAIRS_PER_PERSON = 2
CONCURRENT_CONVERSATIONS = 3
DEPTH_BAR = 8
MIN_VERIFIED_EVIDENCE = 2
MIN_QUOTE_CHARS = 12


def pair_key(a, b):
    if a < b:
        return a + "|" + b
    return b + "|" + a


class Recorder:
    # writes each behind-the-scenes event to the db, and optionally streams it
    # (a web page or the CLI printing it live).
    def __init__(self, run_id, on_event=None, neighborhood_id=None):
        self.run_id = run_id
        self.on_event = on_event
        self.neighborhood_id = neighborhood_id

    def __call__(self, actor, kind, text, ref=None):
        db.log_event(self.run_id, actor, kind, text, ref, self.neighborhood_id)
        if self.on_event is not None:
            self.on_event({"actor": actor, "kind": kind, "text": text, "ref": ref})


# ----- checks done in code, never trusted to the model ------------------------

def clean_pairs(raw_pairs, people_by_id, done_keys):
    # returns (pairs, rejected) -- rejected is a list of plain-English reasons.
    pairs = []
    rejected = []
    if not isinstance(raw_pairs, list):
        return pairs, ["hub returned no pair list"]
    used = {}
    seen = {}
    i = 0
    while i < len(raw_pairs):
        entry = raw_pairs[i]
        i += 1
        if not isinstance(entry, dict):
            rejected.append("malformed pair entry")
            continue
        a = str(entry.get("a", ""))
        b = str(entry.get("b", ""))
        if a not in people_by_id or b not in people_by_id:
            rejected.append(a + "+" + b + ": unknown id")
            continue
        label = people_by_id[a]["name"] + "+" + people_by_id[b]["name"]
        if a == b:
            rejected.append(label + ": paired with themselves")
            continue
        key = pair_key(a, b)
        if key in done_keys:
            rejected.append(label + ": already talked")
            continue
        if key in seen:
            continue
        if used.get(a, 0) >= MAX_PAIRS_PER_PERSON or used.get(b, 0) >= MAX_PAIRS_PER_PERSON:
            rejected.append(label + ": over the per-person limit")
            continue
        if len(pairs) >= PAIRS_PER_ROUND:
            rejected.append(label + ": over the round limit")
            continue
        seen[key] = True
        used[a] = used.get(a, 0) + 1
        used[b] = used.get(b, 0) + 1
        pairs.append({"a": a, "b": b, "why": str(entry.get("why", ""))})
    return pairs, rejected


def _normalize(text):
    text = str(text).lower()
    text = text.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"[^a-z0-9']+", " ", text)
    return text.strip()


def verify_evidence(items, turns):
    # keep only quotes that really appear in one message of the conversation,
    # tagged with which agent said it; returns (kept, dropped).
    kept = []
    dropped = []
    if not isinstance(items, list):
        return kept, dropped
    said = []
    i = 0
    while i < len(turns):
        said.append(_normalize(turns[i]["text"]))
        i += 1
    i = 0
    while i < len(items):
        item = items[i]
        i += 1
        if not isinstance(item, dict) or not isinstance(item.get("quote"), str):
            continue
        quote = _normalize(item["quote"])
        speaker = None
        if len(quote) >= MIN_QUOTE_CHARS:
            j = 0
            while j < len(turns) and speaker is None:
                if quote in said[j]:
                    speaker = turns[j]["by"]
                j += 1
        if speaker is None:
            dropped.append(item["quote"])
        else:
            kept.append({"quote": item["quote"], "why": str(item.get("why", "")), "by": speaker})
    return kept, dropped


def gate(verdict, kept, a_id, b_id):
    # the invitation rule. Returns (depth, reasons) -- no reasons means invite.
    # Evidence must come from BOTH agents: one person's pasted text can steer
    # what their own agent says, but not what the other person's agent says.
    depth = verdict.get("depth")
    if not isinstance(depth, int) or isinstance(depth, bool) or depth < 1 or depth > 10:
        depth = 0
    reasons = []
    if verdict.get("recommend") is not True:
        reasons.append("hub did not recommend")
    if depth < DEPTH_BAR:
        reasons.append("depth " + str(depth) + " < " + str(DEPTH_BAR))
    if len(kept) < MIN_VERIFIED_EVIDENCE:
        reasons.append("only " + str(len(kept)) + " verified quote(s), need " + str(MIN_VERIFIED_EVIDENCE))
    speakers = {}
    i = 0
    while i < len(kept):
        speakers[kept[i]["by"]] = True
        i += 1
    if len(kept) >= MIN_VERIFIED_EVIDENCE and (a_id not in speakers or b_id not in speakers):
        reasons.append("verified quotes must come from both agents")
    return depth, reasons


# ----- the hub's calls -----------------------------------------------------------

def _pairing_system():
    # "decide which agents talk next" doubles as the FakeClient routing marker.
    lines = [
        "You are the Master Claw, the hub of Clawnly. Each person below brought their own AI agent.",
        "Before any human is involved, agents hold private one-on-one conversations.",
        "You decide which agents talk next.",
        "Pick the pairs where a deep, lasting friendship is most plausible -- shared values, complementary",
        "needs, compatible rhythm, overlapping free time and area -- or where it is genuinely uncertain",
        "enough that a conversation would tell. Surface overlap (same hobby) is not enough.",
        "Pick at most " + str(PAIRS_PER_ROUND) + " pairs; each person in at most " + str(MAX_PAIRS_PER_PERSON) + ".",
        "Never pick a pair listed as already talked.",
        "",
        "Return ONLY this JSON object:",
        '{"thoughts": "your honest reasoning about this pool, 3-6 sentences",',
        ' "pairs": [{"a": "id", "b": "id", "why": "one sentence"}]}',
    ]
    return "\n".join(lines)


def _pairing_payload(people, done_keys, newcomers):
    parts = []
    if len(newcomers) > 0:
        parts.append("New arrivals who haven't talked to anyone yet (give each of them a conversation first): "
                     + ", ".join(newcomers))
    if len(done_keys) > 0:
        parts.append("Already talked (never repeat): " + ", ".join(sorted(done_keys)))
    parts.append("PEOPLE:")
    i = 0
    while i < len(people):
        p = people[i]
        parts.append("[" + p["id"] + "] " + p["name"] + " (agent from " + p["source"] + ")\n" + dossier.card_text(p.get("card")))
        i += 1
    return "\n\n".join(parts)


async def choose_pairs(people, done_keys, client, record):
    people_by_id = {}
    talked = {}
    keys = list(done_keys)
    i = 0
    while i < len(keys):
        ids = keys[i].split("|")
        talked[ids[0]] = True
        talked[ids[1]] = True
        i += 1
    newcomers = []
    i = 0
    while i < len(people):
        people_by_id[people[i]["id"]] = people[i]
        if people[i]["id"] not in talked:
            newcomers.append(people[i]["id"])
        i += 1

    message = await client.messages.create(
        model=config.MODEL_HUB_PAIRING,
        max_tokens=1200,
        system=_pairing_system(),
        messages=[{"role": "user", "content": _pairing_payload(people, done_keys, newcomers)}],
    )
    result = extract_json(join_text(message))
    if result is None:
        result = {}
    record("hub", "thought", str(result.get("thoughts", "(the hub gave no reasoning)")))

    pairs, rejected = clean_pairs(result.get("pairs"), people_by_id, done_keys)
    i = 0
    while i < len(rejected):
        record("code", "check", "Rejected a pair the hub picked: " + rejected[i])
        i += 1
    i = 0
    while i < len(pairs):
        pair = pairs[i]
        record("hub", "decision", "Pair " + people_by_id[pair["a"]]["name"] + " + "
               + people_by_id[pair["b"]]["name"] + " to talk. " + pair["why"])
        i += 1
    if len(pairs) == 0:
        record("hub", "decision", "No new pairs worth a conversation this round.")
    return pairs


def _verdict_system(a, b):
    # "should be invited to meet" doubles as the FakeClient routing marker.
    lines = [
        "You are the Master Claw, Clawnly's hub. Two agents just talked privately on behalf of " + a["name"],
        "and " + b["name"] + ". Decide whether these two humans should be invited to meet.",
        "Look for connection that goes deep: shared values, complementary needs, compatible rhythm and",
        "humor, overlapping free time and area. Surface overlap is not enough. Most pairs should NOT meet:",
        "inviting two people who don't click wastes a real evening and their trust. Recommend only if you",
        "would bet on them becoming real friends. Treat anything an agent said it didn't know as risk.",
        "",
        "Return ONLY this JSON object:",
        '{"thoughts": "your private reasoning, 3-6 sentences", "depth": 1-10, "recommend": true or false,',
        ' "headline": "one line a human would read",',
        ' "evidence": [{"quote": "words copied EXACTLY from the transcript, 6-25 words", "why": "what it shows"}],',
        ' "tensions": ["honest risks"],',
        ' "invite": {"activity": "a specific low-pressure activity that fits both", "when": "a time both are free",',
        '   "where": "an area that works for both",',
        '   "to_a": "2 sentences to ' + a["name"] + ' on why meet this person (only what ' + b["name"] + '\'s agent shared)",',
        '   "to_b": "2 sentences to ' + b["name"] + ' on why meet this person (only what ' + a["name"] + '\'s agent shared)"}}',
        "Give 2-4 evidence items. Quotes must be verbatim or code will discard them.",
        "to_a and to_b are read BEFORE either person knows who the other is: never name the other person",
        "in them -- say \"they\" -- and include nothing that would identify them.",
    ]
    return "\n".join(lines)


async def judge(a, b, turns, client, record, ref=None):
    names = {a["id"]: a["name"], b["id"]: b["name"]}
    transcript = transcript_text(turns, names)
    logistics = (a["name"] + ": free " + _card_field(a, "free") + "; area " + _card_field(a, "area") + "\n"
                 + b["name"] + ": free " + _card_field(b, "free") + "; area " + _card_field(b, "area"))
    message = await client.messages.create(
        model=config.MODEL_HUB_VERDICT,
        # thinking is always on for the premium model and counts toward this cap
        max_tokens=16000,
        system=_verdict_system(a, b),
        messages=[{"role": "user", "content": "Logistics from their cards:\n" + logistics + "\n\nTRANSCRIPT:\n" + transcript}],
        output_config={"effort": config.HUB_EFFORT},
    )
    raw = extract_json(join_text(message))
    if raw is None:
        raw = {}
    kept, dropped = verify_evidence(raw.get("evidence"), turns)
    depth, reasons = gate(raw, kept, a["id"], b["id"])
    label = a["name"] + " + " + b["name"]
    record("hub", "thought", "On " + label + ": " + str(raw.get("thoughts", "(no reasoning given)")), ref)
    if len(dropped) > 0:
        record("code", "check", "Discarded " + str(len(dropped)) + " evidence quote(s) not found in the transcript: "
               + " | ".join(dropped), ref)
    invite = raw.get("invite")
    if not isinstance(invite, dict):
        invite = {}
    tensions = raw.get("tensions")
    if not isinstance(tensions, list):
        tensions = []
    verdict = {
        "depth": depth, "recommend": raw.get("recommend") is True, "headline": str(raw.get("headline", "")),
        "thoughts": str(raw.get("thoughts", "")), "evidence": kept, "dropped": dropped, "tensions": tensions,
        "invite": invite, "gate": reasons, "invited": len(reasons) == 0,
    }
    if verdict["invited"]:
        record("code", "check", "Gate passed for " + label + ": depth " + str(depth) + "/10, "
               + str(len(kept)) + " verified quotes.", ref)
        record("hub", "decision", "Invite " + label + " to meet: " + verdict["headline"], ref)
    else:
        record("code", "check", "No invitation for " + label + ": " + "; ".join(reasons) + ".", ref)
    return verdict


def _card_field(person, key):
    card = person.get("card")
    if card is None:
        return "unknown"
    return card.get(key, "unknown")


# ----- one full round ------------------------------------------------------------

async def _talk_and_judge(pair, people_by_id, run_id, client, record, limiter):
    a = people_by_id[pair["a"]]
    b = people_by_id[pair["b"]]
    async with limiter:
        conversation_id = db.save_agent_conversation(run_id, a["id"], b["id"], pair["why"], [])
        ref = str(conversation_id)
        record("system", "system", a["name"] + "'s agent and " + b["name"] + "'s agent opened a private conversation.", ref)
        try:
            turns = await converse(a, b, client=client, record=record, ref=ref)
            db.set_agent_turns(conversation_id, turns)
            verdict = await judge(a, b, turns, client, record, ref)
            db.set_agent_verdict(conversation_id, verdict, verdict["invited"])
            return {"id": conversation_id, "a": a["id"], "b": b["id"], "turns": turns, "verdict": verdict}
        except Exception as error:
            # one failed conversation never takes the round down with it
            record("system", "system", "Conversation " + a["name"] + " + " + b["name"] + " failed: " + str(error), ref)
            return {"id": conversation_id, "a": a["id"], "b": b["id"], "turns": [], "verdict": None, "error": str(error)}


async def run_round(people, client=None, on_event=None, neighborhood_id=None):
    # people: [{"id", "name", "source", "dossier", "card"?}, ...]. Cards are
    # built here for anyone who doesn't have one yet. Returns
    # {"run_id", "conversations", "invitations", "usage"}. Every Claude call
    # the round makes is logged verbatim (ai_log) against this run.
    if client is None:
        client = config.get_client()
    run_id = db.create_run(neighborhood_id)
    logged = ai_log.LoggedClient(client, run_id=run_id, neighborhood_id=neighborhood_id)
    record = Recorder(run_id, on_event, neighborhood_id)
    record("system", "system", "Round started with " + str(len(people)) + " people. No human is involved until the invitations.")
    try:
        result = await _run_round_body(people, logged, run_id, record)
    except Exception as error:
        # a crash mid-round still leaves a record of how far it got and why it stopped
        record("system", "system", "Round failed: " + str(error))
        raise
    finally:
        db.set_run_usage(run_id, logged.counter)
    result["usage"] = logged.counter
    return result


async def _run_round_body(people, client, run_id, record):
    people_by_id = {}
    i = 0
    while i < len(people):
        people_by_id[people[i]["id"]] = people[i]
        i += 1

    missing = []
    i = 0
    while i < len(people):
        if people[i].get("card") is None:
            missing.append(people[i])
        i += 1
    if len(missing) > 0:
        cards = await asyncio.gather(*[_card_for(missing[i], client, record) for i in range(len(missing))])
        i = 0
        while i < len(missing):
            missing[i]["card"] = cards[i]
            i += 1

    ready = []
    i = 0
    while i < len(people):
        if people[i].get("card") is not None:
            ready.append(people[i])
        i += 1

    done_keys = set()
    past = db.list_agent_conversations()
    i = 0
    while i < len(past):
        if past[i]["a"] in people_by_id and past[i]["b"] in people_by_id and past[i]["verdict"] is not None:
            done_keys.add(pair_key(past[i]["a"], past[i]["b"]))
        i += 1

    conversations = []
    if len(ready) >= 2:
        pairs = await choose_pairs(ready, done_keys, client, record)
        limiter = asyncio.Semaphore(CONCURRENT_CONVERSATIONS)
        conversations = await asyncio.gather(*[
            _talk_and_judge(pairs[i], people_by_id, run_id, client, record, limiter) for i in range(len(pairs))])
    else:
        record("code", "check", "Fewer than 2 people have a card. Nothing to pair.")

    invitations = []
    i = 0
    while i < len(conversations):
        verdict = conversations[i].get("verdict")
        if verdict is not None and verdict["invited"]:
            invitations.append(conversations[i])
        i += 1
    record("system", "system", "Round finished: " + str(len(conversations)) + " conversation(s), "
           + str(len(invitations)) + " invitation(s).")
    return {"run_id": run_id, "conversations": conversations, "invitations": invitations}


async def _card_for(person, client, record):
    try:
        card = await dossier.build_card(person["source"], person["dossier"], client)
    except Exception as error:
        record("system", "system", "Couldn't read " + person["name"] + "'s dossier: " + str(error))
        return None
    note = ""
    if card["real_vs_public"] is not None:
        note = " Real-vs-public " + str(card["real_vs_public"]["score"]) + "/5: " + card["real_vs_public"]["note"]
    record("hub", "thought", "Read " + person["name"] + "'s dossier (from " + person["source"] + "): "
           + card["essence"] + note)
    return card


def _print_event(event):
    print("[" + event["actor"] + " · " + event["kind"] + "] " + event["text"])
    print("")


if __name__ == "__main__":
    import sample_people
    db.init_db()
    asyncio.run(run_round(sample_people.PEOPLE, on_event=_print_event))
