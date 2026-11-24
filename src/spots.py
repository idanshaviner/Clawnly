"""Public meetup spots: the places two strangers may meet for the first time.

An admin lists the spots for a neighborhood (/admin); the hub must pick one of
them for an invitation. The pick is checked here in code, because a model asked
for "a public place" will sometimes name a backyard. Pure functions, no I/O.
"""

MAX_SPOTS = 10
MAX_SPOT_CHARS = 80


def _one_line(text):
    # drop control characters and newlines, collapse runs of spaces -- a spot ends up
    # inside a prompt and on a resident's screen, so it must be one plain line
    kept = []
    i = 0
    while i < len(text):
        if text[i].isprintable():
            kept.append(text[i])
        i += 1
    return " ".join("".join(kept).split())


def clean_spots(raw):
    # admin input -> (list of spots, None), or (None, a message for the admin)
    if not isinstance(raw, list):
        return None, "Send the spots as a list."
    spots = []
    seen = set()
    i = 0
    while i < len(raw):
        item = raw[i]
        i += 1
        if not isinstance(item, str):
            return None, "Each spot must be text."
        text = _one_line(item)
        if len(text) == 0:
            continue
        if len(text) > MAX_SPOT_CHARS:
            return None, "Keep each spot to " + str(MAX_SPOT_CHARS) + " characters or fewer."
        if text.lower() in seen:
            continue
        seen.add(text.lower())
        spots.append(text)
    if len(spots) == 0:
        return None, "Add at least one public spot."
    if len(spots) > MAX_SPOTS:
        return None, "Use at most " + str(MAX_SPOTS) + " spots."
    return spots, None


def check_spot(invite, spots):
    # the rule: a first meetup is always in a listed public spot. Returns
    # (invite, note): the invite with its place corrected, and a line for the
    # log (None when nothing needed fixing). The first listed spot is the fallback.
    fixed = dict(invite)
    place = " ".join(str(invite.get("where", "")).split())
    if len(spots) == 0:
        note = ("No public meetup spots are set for this neighborhood, so the place \"" + place
                + "\" was not checked. Set them on /admin.")
        return fixed, note
    i = 0
    while i < len(spots):
        # an exact pick, or a listed spot followed by detail ("The Commons, by the fountain")
        if place.lower() == spots[i].lower() or place.lower().startswith(spots[i].lower() + ","):
            fixed["where"] = spots[i]
            return fixed, None
        i += 1
    fixed["where"] = spots[0]
    if len(place) == 0:
        return fixed, "The hub named no meetup place: used \"" + spots[0] + "\"."
    return fixed, "Meetup place \"" + place + "\" is not a listed public spot: used \"" + spots[0] + "\"."
