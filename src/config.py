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


def get_client():
    # reads the key from ANTHROPIC_API_KEY in the environment.
    key = os.environ.get("ANTHROPIC_API_KEY")
    return AsyncAnthropic(api_key=key)
