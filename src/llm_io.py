"""Helpers for reading JSON out of Anthropic responses.

Shared by master_claw and popup so the parsing logic lives in one place.
Both callers prefill the assistant turn with '{' and prepend it before parsing.
"""

import json


def join_text(message):
    # concatenate the text blocks of a response (index loop, no comprehension).
    parts = []
    i = 0
    while i < len(message.content):
        block = message.content[i]
        if block.type == "text":
            parts.append(block.text)
        i += 1
    return "".join(parts)


def extract_json(text):
    # pull the outermost {...} object and parse it; None if not parseable.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return None
    chunk = text[start:end + 1]
    try:
        return json.loads(chunk)
    except Exception:
        return None
