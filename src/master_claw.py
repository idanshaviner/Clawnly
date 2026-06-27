"""The Master Claw: interviews every Claw and forms one compatible group.

This is the core of the PoC. It asks each Claw two questions (concurrently,
with per-Claw error isolation), then sends every profile + answer to a single
reasoning call that must form a group, score it, and justify it -- grounded in
real facts, never fabricated. Hard constraints are enforced in code; a bad
group is repaired/retried, never shipped. See SPEC sections 3, 6, 6b, 6c.
"""

import asyncio

import config
from claw import Claw
from llm_io import join_text, extract_json


# the two fixed interview questions (SPEC F3).
QUESTION_1 = "What kinds of social experiences is your user looking for right now?"
QUESTION_2 = "What is your user's availability like and what energy do they bring to group settings?"

# how many times to ask the matcher to fix a constraint-violating group.
MAX_MATCH_ATTEMPTS = 3


class MasterClaw:
    def __init__(self, users, client=None):
        # one shared client for every Claw (injectable for tests).
        if client is None:
            client = config.get_client()
        self.client = client

        # build one Claw per user, plus an id -> profile lookup.
        self.claws = []
        self.users_by_id = {}
        i = 0
        while i < len(users):
            user = users[i]
            self.claws.append(Claw(user, client=self.client))
            self.users_by_id[user["id"]] = user
            i += 1

    # ----- interviews -------------------------------------------------------

    async def _interview_one(self, claw):
        # ask one Claw both questions in a single batched call; isolate failures so
        # one bad call does not abort the whole run (SPEC N3).
        uid = claw.user["id"]
        try:
            q1, q2 = await claw.interview_both(QUESTION_1, QUESTION_2)
            record = {"profile": claw.user, "q1": q1, "q2": q2}
        except Exception as error:
            record = {"profile": claw.user, "q1": None, "q2": None, "error": str(error)}
        return (uid, record)

    async def interview_claws(self):
        # fan out across all Claws (comprehension allowed only for gather, D6).
        tasks = [self._interview_one(self.claws[i]) for i in range(len(self.claws))]
        results = await asyncio.gather(*tasks)

        # collect into a dict keyed by id.
        interviews = {}
        i = 0
        while i < len(results):
            uid, record = results[i]
            interviews[uid] = record
            i += 1
        return interviews

    # ----- matching ---------------------------------------------------------

    def _match_system_prompt(self):
        # the rules the matcher must follow, stated explicitly.
        lines = [
            "You are the Master Claw, a matchmaker. From the people below, form ONE meetup",
            "group of 3 to 5 people who would genuinely click. Reason FIRST, then choose.",
            "",
            "HARD CONSTRAINTS (never violate; if you cannot satisfy them, return an empty group):",
            "- Group size must fall inside EVERY chosen member's preferred size range.",
            "- The group must share at least ONE common availability window (a meetup needs a time).",
            "- Use only ids that appear below; never repeat an id.",
            "- Default size is 3-5; only go smaller if a member's range forces it.",
            "",
            "SOFT PREFERENCES (optimize, trade off, never block):",
            "- Complementary personality energy (not everyone the same, no one overwhelmed).",
            "- Interests that overlap enough to connect but vary enough to stay interesting.",
            "- Light bonus for occupation variety and for living near each other in DC.",
            "- More shared availability windows is better.",
            "",
            "SCORING (group-level integers 1-5): 5 = excellent fit, 3 = workable, 1 = poor.",
            "Score the ACTUAL group you chose, honestly. Do not inflate a score to justify a pick.",
            "",
            "GROUNDING (this is critical): every claim in 'reason' and 'why_not' must be TRUE to the",
            "data shown. Do not invent hobbies, traits, or availability a person does not have. Cite",
            "the specific person and attribute. If evidence is thin, say so and score it low. Prefer an",
            "empty group over fabricating compatibility.",
            "",
            "Return ONLY a JSON object, no prose around it, exactly:",
            '{',
            '  "group": ["u01", "u02", "u03"],',
            '  "reason": "why these people fit, citing names and specific attributes",',
            '  "scores": {"personality": 4, "availability": 5, "interests": 4, "size_fit": 5},',
            '  "why_not": [{"id": "u08", "reason": "specific, grounded reason this strong candidate was left out"}]',
            "}",
            "Use [] for group and [] for why_not when nothing applies. why_not holds at most 3 entries.",
            "Respond with the JSON object ONLY -- no markdown code fences, no text before or after it.",
        ]
        return "\n".join(lines)

    def _match_payload(self, interviews, feedback):
        # render each candidate's profile + interview answers as text.
        candidate_ids = self._candidate_ids(interviews)
        parts = ["People to consider:\n"]
        i = 0
        while i < len(candidate_ids):
            uid = candidate_ids[i]
            record = interviews[uid]
            p = record["profile"]
            hobbies = ", ".join(p["hobbies"])
            availability = ", ".join(p["availability"])
            size = p["preferred_group_size"]
            block = [
                "id: {} | name: {} | age: {} | gender: {}".format(p["id"], p["name"], p["age"], p["gender"]),
                "personality: {} | occupation: {} | neighborhood: {}".format(p["personality"], p["occupation"], p["location"]),
                "availability: {}".format(availability),
                "hobbies: {}".format(hobbies),
                "preferred_group_size: {}".format(size),
                "looking for: {}".format(record["q1"]),
                "availability/energy: {}".format(record["q2"]),
                "",
            ]
            parts.append("\n".join(block))
            i += 1
        text = "\n".join(parts)
        if len(feedback) > 0:
            text = text + "\n" + feedback
        return text

    def _candidate_ids(self, interviews):
        # only users who were interviewed successfully are eligible.
        ids = list(interviews.keys())
        candidates = []
        i = 0
        while i < len(ids):
            uid = ids[i]
            if "error" not in interviews[uid]:
                candidates.append(uid)
            i += 1
        return candidates

    async def _call_match(self, system, payload):
        # one matching call. note: the match model (Opus 4.8) accepts neither
        # `temperature` nor assistant-message prefill (both 400 on that family), so
        # the prompt asks for JSON only and we parse it out. Consistency comes from
        # the structured output + the code-level validator, not a temperature knob.
        message = await self.client.messages.create(
            model=config.MODEL_MATCH,
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": payload}],
        )
        return extract_json(join_text(message))

    async def find_matches(self, interviews):
        system = self._match_system_prompt()
        feedback = ""
        attempt = 0
        while attempt < MAX_MATCH_ATTEMPTS:
            payload = self._match_payload(interviews, feedback)
            result = await self._call_match(system, payload)

            if result is None:
                # not valid json; ask again.
                feedback = "Your previous reply was not valid JSON. Return only the JSON object."
                attempt += 1
                continue

            group = result.get("group", [])
            if len(group) == 0:
                # the matcher declined to force a match -- a valid outcome.
                return self._finalize(result)

            problems = self._validate_group(group)
            if len(problems) == 0:
                return self._finalize(result)

            # repair: tell the matcher exactly what was wrong.
            feedback = "Your group violated hard constraints: " + "; ".join(problems) + ". Return corrected JSON."
            attempt += 1

        # safe fallback: never emit a bad group.
        return {
            "group": [],
            "reason": "No group satisfied all hard constraints after repeated attempts.",
            "scores": {},
            "why_not": [],
        }

    def _finalize(self, result):
        # light normalization of the model's output.
        group = result.get("group", [])
        reason = result.get("reason", "")
        scores = result.get("scores", {})
        why_not = result.get("why_not", [])
        if len(why_not) > 3:
            why_not = why_not[:3]
        return {"group": group, "reason": reason, "scores": scores, "why_not": why_not}

    # ----- hard-constraint validation (SPEC 6b) -----------------------------

    def _validate_group(self, group):
        problems = []

        # H3: every id exists, no duplicates.
        seen = {}
        members = []
        i = 0
        while i < len(group):
            gid = group[i]
            if gid not in self.users_by_id:
                problems.append("unknown id " + str(gid))
            else:
                members.append(self.users_by_id[gid])
            if gid in seen:
                problems.append("duplicate id " + str(gid))
            seen[gid] = True
            i += 1

        n = len(members)

        # H1: group size inside every member's range.
        j = 0
        while j < len(members):
            m = members[j]
            size = m["preferred_group_size"]
            if size != "no preference":
                low = size[0]
                high = size[1]
                if n < low or n > high:
                    problems.append(m["name"] + "'s size range " + str(size) + " excludes a group of " + str(n))
            j += 1

        # H4: size 3-5 unless a member forces it smaller; never larger than 5.
        forced_small = False
        j = 0
        while j < len(members):
            size = members[j]["preferred_group_size"]
            if size != "no preference" and size[1] < 3:
                forced_small = True
            j += 1
        if n > 5:
            problems.append("group of " + str(n) + " is larger than the 5-person maximum")
        if n < 2:
            problems.append("group of " + str(n) + " is too small to be a meetup")
        if n < 3 and not forced_small:
            problems.append("group of " + str(n) + " is under 3 without a member forcing it")

        # H2: at least one shared availability window.
        if len(members) > 0:
            common = set(members[0]["availability"])
            j = 1
            while j < len(members):
                common = common & set(members[j]["availability"])
                j += 1
            if len(common) == 0:
                problems.append("group shares no common availability window")

        return problems
