"""Single source of model ids, temperatures, and the Anthropic client.

Everything that talks to the API pulls its settings from here, so swapping a
model or tuning a temperature happens in one place (SPEC N4).
"""

import os

from anthropic import AsyncAnthropic


# model per role. the match call is the reasoning-critical one, so it gets the
# strongest model; the bulk interview calls get the cheapest model to control cost
# (SPEC section 2).
MODEL_INTERVIEW = "claude-haiku-4-5"   # cheap + fast: the 12 interview calls
MODEL_CLAW = "claude-sonnet-4-6"        # richer model for free-style chat
MODEL_MATCH = "claude-opus-4-8"         # strongest: the reasoning-critical match
MODEL_POPUP = "claude-sonnet-4-6"


# temperatures for the Sonnet calls: vivid personas, lively popups.
# (the match model is Opus 4.8, which does NOT accept `temperature` -- it returns
#  a 400 -- so the match call omits it; see master_claw._call_match.)
TEMP_PERSONA = 0.8
TEMP_POPUP = 0.7

# effort for the Opus match call (speed/cost lever). "medium" is much faster and
# cheaper than the default "high" and is plenty for choosing a group from 12
# short profiles. Bump to "high" if you want maximum matching rigor.
MATCH_EFFORT = "medium"

# the quality bar for SHIPPING a group. The matcher scores each group it forms
# on four axes (1-5); we only accept a group whose average clears this bar, so we
# ship strong connections -- "your people" -- not merely workable ones. When the
# best group among the people left is below the bar, we form no group and leave
# them unmatched rather than forcing a lukewarm meetup. 3.5 = clearly better than
# "workable" (3) on average. Lower it to match more freely, raise it to be pickier.
MIN_MATCH_QUALITY = 3.5


def resolve_api_key():
    # 1) the environment variable (works when launched from a terminal export).
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    # 2) a .env file at the project root (so the double-click launcher can do
    #    live mode without an export). The file is gitignored; one line:
    #       ANTHROPIC_API_KEY=sk-ant-...
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(root, ".env")
    if os.path.exists(env_path):
        with open(env_path) as handle:
            lines = handle.read().splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                value = line[len("ANTHROPIC_API_KEY="):].strip().strip('"').strip("'")
                if len(value) > 0:
                    return value
            i += 1
    return None


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
