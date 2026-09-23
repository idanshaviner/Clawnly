"""Single source of model ids, temperatures, and the Anthropic client.

Everything that talks to the API pulls its settings from here, so swapping a
model or tuning a temperature happens in one place (SPEC N4).
"""

import os

from anthropic import AsyncAnthropic


# ----- model tiers (cost/reasoning ladder) ---------------------------------
# three tiers, cheapest to most expensive. Route each AI task to the cheapest
# tier that can reliably do the job -- reserve the premium tier for the one
# call where getting it right matters most (SPEC section 2).
MODEL_CHEAP = "claude-haiku-4-5"       # bulk, mechanical, low-reasoning tasks:
                                        # interview answers, in-character reactions,
                                        # structured fact-extraction (e.g. "is this
                                        # profile complete yet?")
MODEL_REASONING = "claude-sonnet-4-6"  # needs real judgment/quality but isn't the
                                        # single highest-stakes call: free-form chat,
                                        # negotiation, popup/venue suggestions, persona
                                        # generation, explaining a decision
MODEL_PREMIUM = "claude-opus-5-5"      # the reasoning-critical call: forming the
                                        # actual group. Match quality is the whole
                                        # product's bet, so it gets the strongest model

# named per-task aliases -- kept for readability at each call site, and so
# nothing elsewhere has to change. Always equal to one of the three tiers
# above; retier a task by moving its alias, never by hardcoding a new model id.
MODEL_INTERVIEW = MODEL_CHEAP      # the 12 interview calls
MODEL_CLAW = MODEL_REASONING       # free-style chat, negotiation, persona gen, explain
MODEL_MATCH = MODEL_PREMIUM        # the reasoning-critical match
MODEL_POPUP = MODEL_REASONING      # venue/meetup suggestions

# real-user pilot (onboarding): the chat reply itself needs real quality
# (MODEL_REASONING), but checking whether a profile is complete yet is a
# simple structured read of the transcript so far -- it stays on MODEL_CHEAP
# even though it runs after every turn.
MODEL_ONBOARDING_CHAT = MODEL_REASONING
MODEL_ONBOARDING_COMPLETENESS = MODEL_CHEAP

# agent-to-agent orchestration (dossier.py / agent_talk.py / orchestrator.py).
# the agents' conversation IS the product now -- a shallow agent gives a
# shallow read of a person -- so turns get real judgment, not the cheap tier.
# the verdict ("should these two humans meet?") is the one call whose mistakes
# cost two real people an evening, so it gets the premium tier, like the match.
MODEL_DOSSIER = MODEL_REASONING      # pasted AI portrait -> the card an agent carries
MODEL_AGENT_TURN = MODEL_REASONING   # one Claw's message to another Claw
MODEL_HUB_PAIRING = MODEL_REASONING  # the hub choosing which agents talk
MODEL_HUB_VERDICT = MODEL_PREMIUM    # the hub deciding who gets an invitation


# temperatures for the Sonnet calls: vivid personas, lively popups.
# (the premium model -- Opus 5.5 -- does NOT accept `temperature` (400), and its
#  thinking is always on and counts toward max_tokens, so its calls omit
#  temperature and leave generous max_tokens; see master_claw._call_match and
#  orchestrator.judge.)
TEMP_PERSONA = 0.8
TEMP_POPUP = 0.7

# effort for the Opus calls -- the match and the hub verdict (speed/cost lever).
# "medium" is also Opus 5.5's own default; set explicitly so a model change
# never silently moves it. Bump to "high" for maximum rigor.
MATCH_EFFORT = "medium"

# the quality bar for SHIPPING a group. The matcher scores each group it forms
# on four axes (1-5); we only accept a group whose average clears this bar, so we
# ship strong connections -- "your people" -- not merely workable ones. When the
# best group among the people left is below the bar, we form no group and leave
# them unmatched rather than forcing a lukewarm meetup. 3.5 = clearly better than
# "workable" (3) on average. Lower it to match more freely, raise it to be pickier.
MIN_MATCH_QUALITY = 3.5

# how many profile-complete residents a neighborhood needs before a matching
# batch runs automatically (real-user pilot). Bigger pools give the matcher more
# room to find genuinely strong groups instead of settling; lower this if a
# neighborhood is filling too slowly, raise it for stricter pools. Each
# neighborhood snapshots this value when it's created, so changing it here only
# affects neighborhoods created afterward -- it never moves the goalposts on a
# cohort already filling up.
MATCH_BATCH_THRESHOLD = 100

# who can see the admin dashboard (real-user pilot). Comma-separated emails in
# CLAWNLY_ADMIN_EMAILS, e.g. "you@example.com,cofounder@example.com". Plain
# allowlist, not a role/permission system -- this is a single-operator alpha.
# Read fresh (not cached) so tests can change it without reimporting anything.
def parse_admin_emails():
    raw = os.environ.get("CLAWNLY_ADMIN_EMAILS", "")
    emails = []
    parts = raw.split(",")
    i = 0
    while i < len(parts):
        email = parts[i].strip().lower()
        if len(email) > 0:
            emails.append(email)
        i += 1
    return emails


def resolve_env(name):
    # 1) the environment variable (works when launched from a terminal export).
    value = os.environ.get(name)
    if value:
        return value
    # 2) a .env file at the project root (so the double-click launcher can do
    #    live mode without an export). The file is gitignored; one line per key:
    #       NAME=value
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(root, ".env")
    if os.path.exists(env_path):
        with open(env_path) as handle:
            lines = handle.read().splitlines()
        prefix = name + "="
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith(prefix):
                value = line[len(prefix):].strip().strip('"').strip("'")
                if len(value) > 0:
                    return value
            i += 1
    return None


def resolve_api_key():
    return resolve_env("ANTHROPIC_API_KEY")


def get_client():
    key = resolve_api_key()
    if not key:
        raise ValueError(
            "No Anthropic API key found. Switch to Demo mode (free), OR set "
            "ANTHROPIC_API_KEY in your terminal, OR add a line "
            "ANTHROPIC_API_KEY=sk-ant-... to a file named .env in the project folder."
        )
    # a per-request timeout so a hung call fails instead of freezing the app.
    return AsyncAnthropic(api_key=key, timeout=120.0)


def client_from_key(key):
    # build a client from a caller-supplied key (bring-your-own-key deploys),
    # so the server never has to hold a key of its own.
    if not key or len(key.strip()) < 8:
        raise ValueError("A valid Anthropic API key is required for Live mode.")
    return AsyncAnthropic(api_key=key.strip(), timeout=120.0)
