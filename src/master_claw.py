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


# the two fixed interview questions (SPEC F3). Phrased in the second person so
# they match how the Claw answers (in first person, as the user).
QUESTION_1 = "What kinds of social experiences are you looking for right now?"
QUESTION_2 = "What is your availability like, and what energy do you bring to group settings?"

# how many times to ask the matcher to fix a constraint-violating (or too-weak) group.
MAX_MATCH_ATTEMPTS = 3

# the four group-level score dimensions the matcher must return (SPEC 6a).
SCORE_DIMENSIONS = ["personality", "availability", "interests", "size_fit"]


def _group_quality(scores):
    # the average of the matcher's integer soft-scores, or None if it gave none
    # (so we can only gate on quality when there is a score to judge).
    if not isinstance(scores, dict):
        return None
    values = []
    keys = list(scores.keys())
    i = 0
    while i < len(keys):
        v = scores[keys[i]]
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            values.append(v)
        i += 1
    if len(values) == 0:
        return None
    return sum(values) / len(values)


def _shared_items(list_a, list_b):
    # items common to both lists, in list_a's order, each counted once
    # (index loop, no comprehension -- SPEC 10).
    shared = []
    i = 0
    while i < len(list_a):
        item = list_a[i]
        if item in list_b and item not in shared:
            shared.append(item)
        i += 1
    return shared


class MasterClaw:
    def __init__(self, users, client=None, feedback=None):
        # one shared client for every Claw (injectable for tests).
        if client is None:
            client = config.get_client()
        self.client = client
        # past human feedback on earlier matches; fed into the prompt so the
        # matcher learns from thumbs-up/down over time (in-context learning).
        if feedback is None:
            feedback = []
        self.feedback = feedback

        # build one Claw per user, plus id -> profile and id -> Claw lookups.
        self.claws = []
        self.users_by_id = {}
        self.claws_by_id = {}
        i = 0
        while i < len(users):
            user = users[i]
            claw = Claw(user, client=self.client)
            self.claws.append(claw)
            self.users_by_id[user["id"]] = user
            self.claws_by_id[user["id"]] = claw
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
            "group of 3 to 5 people who would form a GENUINELY STRONG connection -- the kind",
            "of people who would become real friends, not just tolerate an evening together.",
            "Reason FIRST, then choose. Your goal is to find each person THEIR people.",
            "",
            "Quality over coverage: only form a group if the fit is strong. It is far better to",
            "leave someone unmatched (return an empty group) than to place them in a lukewarm",
            "group. Do not force a match just to include everyone.",
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
            "- Light bonus for occupation variety and for living near each other in Seattle.",
            "- More shared availability windows is better.",
            "",
            "USE THE COMPUTED COMPATIBILITY SIGNALS below the people list -- they are exact",
            "shared-hobby pairs and availability-overlap strength, computed in code from the",
            "profiles (not your inference), so they are the most reliable evidence you have.",
            "The STRONGEST groups have an interest 'anchor': at least one specific hobby that",
            "genuinely connects most or all members (directly, or through a couple of overlapping",
            "pairs), not just a vague shared vibe. A group where nobody shares any concrete hobby",
            "with anybody else is a weak pick even if personalities seem to fit -- prefer a",
            "different combination, or an empty group, over that.",
            "",
            "SCORING (group-level integers 1-5): 5 = excellent fit, 3 = workable, 1 = poor.",
            "Score the ACTUAL group you chose, honestly. Do not inflate a score to justify a pick.",
            "STRENGTH BAR: only propose a group whose four scores average 3.5 or higher. If the",
            "best group you can form is merely 'workable' (averaging below 3.5), return an empty",
            "group instead -- those people are better left for another round than badly matched.",
            "",
            "GROUNDING (this is critical): every claim in 'reason' and 'why_not' must be TRUE to the",
            "data shown. Do not invent hobbies, traits, or availability a person does not have. Cite",
            "the specific person and attribute -- prefer citing the computed signals directly (e.g.",
            "\"Maya & Aisha both do puzzles\") since those are pre-verified. If evidence is thin, say",
            "so and score it low. Prefer an empty group over fabricating compatibility.",
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
        hints = self._compatibility_hints(candidate_ids)
        if len(hints) > 0:
            parts.append(hints)
        text = "\n".join(parts)
        lessons = self._feedback_text()
        if len(lessons) > 0:
            text = text + "\n" + lessons
        if len(feedback) > 0:
            text = text + "\n" + feedback
        return text

    def _compatibility_hints(self, candidate_ids):
        # compute REAL pairwise signals in code -- exact shared hobbies, and how
        # strongly two people's availability overlaps -- so the match call reasons
        # over verified ground truth instead of having to eyeball up to a dozen
        # profiles itself. This directly strengthens both match quality (the model
        # no longer has to spot every overlap by hand) and grounding (SPEC 6c):
        # every pair listed here is a fact the model can cite and a reviewer can
        # re-derive from the profiles above.
        hobby_lines = []
        availability_lines = []
        i = 0
        while i < len(candidate_ids):
            a = self.users_by_id[candidate_ids[i]]
            j = i + 1
            while j < len(candidate_ids):
                b = self.users_by_id[candidate_ids[j]]

                shared_hobbies = _shared_items(a["hobbies"], b["hobbies"])
                if len(shared_hobbies) > 0:
                    hobby_lines.append("  {} & {}: {}".format(a["name"], b["name"], ", ".join(shared_hobbies)))

                # only surface STRONG overlap (2+ windows); a bare 1-window
                # overlap is common and already visible on each person's own
                # availability line above, so listing every such pair is noise.
                shared_windows = _shared_items(a["availability"], b["availability"])
                if len(shared_windows) >= 2:
                    availability_lines.append("  {} & {}: {} shared windows -- {}".format(
                        a["name"], b["name"], len(shared_windows), ", ".join(shared_windows)))
                j += 1
            i += 1

        lines = []
        if len(hobby_lines) > 0:
            lines.append("Pairs with an EXACT shared hobby (the strongest grounded evidence for the")
            lines.append("'interests' score -- a group where everyone connects to at least one other")
            lines.append("member this way is a much stronger pick than one where nobody overlaps):")
            lines.extend(hobby_lines)
        if len(availability_lines) > 0:
            if len(lines) > 0:
                lines.append("")
            lines.append("Pairs with STRONG shared availability (2+ windows -- worth a 5 on the")
            lines.append("'availability' rubric; H2 only requires 1, so these pairs clear it easily):")
            lines.extend(availability_lines)
        if len(lines) == 0:
            return ""
        return "COMPUTED COMPATIBILITY SIGNALS (ground truth computed from the profiles above --\n" \
               "use these, do not recompute or contradict them):\n" + "\n".join(lines)

    def _feedback_text(self):
        # turn past thumbs-up/down + notes into guidance the matcher should weigh.
        if len(self.feedback) == 0:
            return ""
        lines = ["LESSONS FROM PAST FEEDBACK (a human rated earlier groups -- learn from these:",
                 "favor what worked, avoid what didn't):"]
        i = 0
        while i < len(self.feedback):
            fb = self.feedback[i]
            mark = "GOOD"
            if fb.get("rating") == "down":
                mark = "BAD"
            who = ", ".join(fb.get("members", []))
            note = fb.get("note", "")
            line = "- [" + mark + "] group of " + who
            if len(note) > 0:
                line = line + " -- \"" + note + "\""
            lines.append(line)
            i += 1
        return "\n".join(lines)

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
            output_config={"effort": config.MATCH_EFFORT},
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
            why_not_problems = self._validate_why_not(result.get("why_not", []))

            if len(group) == 0:
                # the matcher declined to force a match -- a valid outcome, as long
                # as it didn't also cite a made-up person in why_not.
                if len(why_not_problems) > 0:
                    feedback = "Problems in your reply: " + "; ".join(why_not_problems) + ". Return corrected JSON."
                    attempt += 1
                    continue
                return self._finalize(result)

            problems = self._validate_group(group) + why_not_problems + self._validate_scores(result.get("scores", {}))
            if len(problems) > 0:
                # repair: tell the matcher exactly what was wrong.
                feedback = "Your group violated hard constraints: " + "; ".join(problems) + ". Return corrected JSON."
                attempt += 1
                continue

            # quality gate: ship only genuinely strong groups. A merely-workable
            # group is sent back to be strengthened, or declined (empty) if none exists.
            # (scores are already validated as ints 1-5 above, so quality is never None here.)
            quality = _group_quality(result.get("scores", {}))
            if quality is not None and quality < config.MIN_MATCH_QUALITY:
                feedback = ("That group only averages {:.1f}/5 -- workable, not a STRONG connection. "
                            "Propose a genuinely strong group (average >= {}), or return an EMPTY "
                            "group if no strong group exists among these people.").format(
                                quality, config.MIN_MATCH_QUALITY)
                attempt += 1
                continue

            return self._finalize(result)

        # safe fallback: never emit a bad or lukewarm group.
        return {
            "group": [],
            "reason": "No group here both satisfied the hard constraints and was a strong enough connection to ship.",
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

    # ----- multi-group: partition the whole pool ----------------------------

    async def find_all_matches(self, interviews, max_groups=6, on_group=None):
        # form as many non-overlapping 3-5 person groups as the pool supports:
        # match -> remove those people -> match the rest -> stop when no viable
        # group remains. Each group still passes the hard-constraint validator.
        remaining = self._candidate_ids(interviews)
        groups = []
        formed = 0
        while formed < max_groups and len(remaining) >= 3:
            # build a sub-pool of just the people still available.
            sub = {}
            i = 0
            while i < len(remaining):
                sub[remaining[i]] = interviews[remaining[i]]
                i += 1

            result = await self.find_matches(sub)
            group = result["group"]
            if len(group) == 0:
                break   # nobody left forms a viable group

            groups.append(result)
            if on_group is not None:
                on_group(result)

            # drop the matched people from the remaining pool.
            matched = {}
            i = 0
            while i < len(group):
                matched[group[i]] = True
                i += 1
            next_remaining = []
            i = 0
            while i < len(remaining):
                if remaining[i] not in matched:
                    next_remaining.append(remaining[i])
                i += 1
            if len(next_remaining) == len(remaining):
                break   # no progress (group wasn't from the pool) -> stop
            remaining = next_remaining
            formed += 1

        return {"groups": groups, "unmatched": remaining}

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

    def _validate_why_not(self, why_not):
        # H3 also covers why_not (SPEC 6c): every cited id must be a real person,
        # never an invented one.
        problems = []
        if not isinstance(why_not, list):
            problems.append("why_not must be a list")
            return problems
        i = 0
        while i < len(why_not):
            entry = why_not[i]
            wid = None
            if isinstance(entry, dict):
                wid = entry.get("id")
            if wid not in self.users_by_id:
                problems.append("why_not references unknown id " + str(wid))
            i += 1
        return problems

    def _validate_scores(self, scores):
        # scores must be exactly the four group-level dimensions, each an
        # integer 1-5 (SPEC 6a, section 9 acceptance criteria). A malformed or
        # missing score must not be able to sneak past the quality gate.
        problems = []
        if not isinstance(scores, dict):
            problems.append("scores must be an object with personality/availability/interests/size_fit")
            return problems
        j = 0
        while j < len(SCORE_DIMENSIONS):
            key = SCORE_DIMENSIONS[j]
            if key not in scores:
                problems.append("scores missing '" + key + "'")
            else:
                value = scores[key]
                is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
                if not is_number or value < 1 or value > 5:
                    problems.append("scores['" + key + "'] must be an integer 1-5, got " + str(value))
            j += 1
        return problems
