"""Single source of model ids, effort, thresholds, and the Anthropic client.

Everything that talks to the API pulls its settings from here, so swapping a
model or tuning effort happens in one place.
"""

import os

from anthropic import AsyncAnthropic


# ----- model tiers ------------------------------------------------------------
# two tiers, no cheap one: every call in Clawnly speaks for a real person or
# decides something about them, so none of it goes to a bulk model (no Haiku).
# Reserve the premium tier for the calls where getting it right matters most.
MODEL_REASONING = "claude-sonnet-5"    # real judgment: agents, cards, pairing
MODEL_PREMIUM = "claude-opus-5-5"      # the reasoning-critical call: who should meet

# named per-task aliases -- kept for readability at each call site. Always equal
# to one of the three tiers above; retier a task by moving its alias, never by
# hardcoding a new model id.
# the agents' conversation IS the product -- a shallow agent gives a shallow
# read of a person -- so turns get real judgment, not the cheap tier. The
# verdict ("should these two humans meet?") is the one call whose mistakes cost
# two real people an evening, so it gets the premium tier.
MODEL_DOSSIER = MODEL_REASONING      # pasted AI portrait -> the card an agent carries
MODEL_AGENT_TURN = MODEL_REASONING   # one Claw's message to another Claw
MODEL_HUB_PAIRING = MODEL_REASONING  # the hub choosing which agents talk
MODEL_HUB_VERDICT = MODEL_PREMIUM    # the hub deciding who gets an invitation

# effort for the premium (Opus 5.5) calls. Opus 5.5 has thinking always on (it
# counts toward max_tokens) and rejects `temperature`, so effort is the only
# depth lever. "medium" is also its own default; set explicitly so a model
# change never silently moves it. Bump to "high" for maximum rigor.
HUB_EFFORT = "medium"

# effort for the Sonnet 5 calls. Sonnet 5 also thinks by default (adaptive; it
# counts toward max_tokens) and rejects a non-default `temperature`. "medium" is
# about Sonnet 4.6's best; raise to "high" if agents read shallow.
REASONING_EFFORT = "medium"

# how many residents with an agent a neighborhood needs before the hub runs
# its first round automatically. Each neighborhood snapshots this value when
# it's created, so changing it here only affects neighborhoods created
# afterward -- it never moves the goalposts on a cohort already filling up.
# (the admin dashboard can always run a round sooner.)
MATCH_BATCH_THRESHOLD = 10

# after a neighborhood's first round, the hub runs again every night on its
# own (nightly.py), during this hour of the day in this time zone -- overnight,
# so invitations are waiting in the morning. Override with CLAWNLY_NIGHTLY_HOUR
# (0-23) and CLAWNLY_TIMEZONE (e.g. "Asia/Jerusalem").
NIGHTLY_ROUND_HOUR = 3
NIGHTLY_TIMEZONE = "America/Los_Angeles"


# who can see the admin dashboard. Comma-separated emails in
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
    # 2) a .env file at the project root (so the double-click launcher works
    #    without an export). The file is gitignored; one line per key:
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
            "No Anthropic API key found. Set ANTHROPIC_API_KEY in your environment, "
            "OR add a line ANTHROPIC_API_KEY=sk-ant-... to a file named .env in the project folder."
        )
    # a per-request timeout so a hung call fails instead of freezing the app;
    # generous because the premium model thinks before it answers.
    return AsyncAnthropic(api_key=key, timeout=300.0)
