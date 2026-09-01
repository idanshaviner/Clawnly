"""Persistent storage for Clawnly (Milestone 1: give the app a real memory).

A small SQLite file replaces the old in-memory STATE dict + flat cast.json /
feedback.json files in app.py. This module is pure storage plumbing -- it does
not know anything about matching, negotiation, or interviewing; it just saves
and loads the plain dicts those modules already produce, so nothing about how
the pipeline works had to change.

Tables:
  users             -- the editable demo/admin cast (replaces cast.json)
  runs              -- one row per pipeline run (mode, which cast, when); real-
                       pilot runs also carry a neighborhood_id
  interviews        -- each Claw's answers for a run
  matches           -- each group a run formed (group + reason + scores + why_not)
  negotiations      -- the agreed activity + transcript for a match
  meetups           -- the finalized meetup card for a match
  feedback          -- thumbs up/down + note (replaces feedback.json)

  -- real-user pilot (auth + onboarding) --
  neighborhoods     -- one invite-link cohort (slug, batch threshold, trigger state)
  residents         -- a real person's account + progressively-filled profile
  onboarding_messages -- a resident's persisted chat with their own Claw
  sessions          -- durable login sessions (replaces the in-memory _SESSIONS dict)
  magic_link_tokens -- single-use, hashed, expiring email login tokens
  oauth_states      -- single-use, expiring Google OAuth CSRF state tokens
"""

import datetime
import json
import os
import sqlite3


_HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("CLAWNLY_DB_PATH") or os.path.join(os.path.dirname(_HERE), "clawnly.db")

_CONN = None

EDITABLE_USER_FIELDS = ["name", "age", "gender", "hobbies", "personality",
                         "occupation", "availability", "location", "bio",
                         "preferred_group_size"]


def _get_conn():
    global _CONN
    if _CONN is None:
        _CONN = sqlite3.connect(DB_PATH, check_same_thread=False)
        _CONN.row_factory = sqlite3.Row
    return _CONN


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _ensure_column(conn, table, column, coltype):
    # a tiny, table-scale substitute for a migration framework: add a column to
    # an already-existing table exactly once, safe to call on every startup.
    existing = conn.execute("PRAGMA table_info(" + table + ")").fetchall()
    names = []
    i = 0
    while i < len(existing):
        names.append(existing[i]["name"])
        i += 1
    if column not in names:
        conn.execute("ALTER TABLE " + table + " ADD COLUMN " + column + " " + coltype)


def init_db():
    conn = _get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY, name TEXT, age INTEGER, gender TEXT, hobbies TEXT,
        personality TEXT, occupation TEXT, availability TEXT, location TEXT,
        bio TEXT, preferred_group_size TEXT, position INTEGER
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, mode TEXT, users_signature TEXT,
        unmatched_ids TEXT, created_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS interviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, user_id TEXT,
        profile TEXT, q1 TEXT, q2 TEXT, error TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, group_index INTEGER,
        member_ids TEXT, reason TEXT, scores TEXT, why_not TEXT, created_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS negotiations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER, activity TEXT,
        agreed INTEGER, concern TEXT, rounds INTEGER, transcript TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS meetups (
        id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER, options TEXT,
        event_name TEXT, activity TEXT, location TEXT, time TEXT, reason TEXT,
        matched_users TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER, members TEXT,
        rating TEXT, note TEXT, created_at TEXT
    )""")

    # ----- real-user pilot: auth + onboarding -----
    conn.execute("""CREATE TABLE IF NOT EXISTS neighborhoods (
        id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT UNIQUE, name TEXT,
        invite_code TEXT, batch_threshold INTEGER, batch_triggered_at TEXT,
        created_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS residents (
        id INTEGER PRIMARY KEY AUTOINCREMENT, neighborhood_id INTEGER, email TEXT,
        auth_method TEXT, consent_agreed_at TEXT,
        name TEXT, age INTEGER, gender TEXT, hobbies TEXT, personality TEXT,
        occupation TEXT, availability TEXT, location TEXT, bio TEXT,
        preferred_group_size TEXT, slots_status TEXT, profile_complete_at TEXT,
        created_at TEXT,
        UNIQUE(neighborhood_id, email)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS onboarding_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, resident_id INTEGER, role TEXT,
        content TEXT, created_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY, email TEXT, role TEXT, resident_id INTEGER,
        neighborhood_id INTEGER, created_at TEXT, expires_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS magic_link_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT, token_hash TEXT, email TEXT,
        neighborhood_id INTEGER, created_at TEXT, expires_at TEXT, used_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS oauth_states (
        id INTEGER PRIMARY KEY AUTOINCREMENT, token_hash TEXT, neighborhood_id INTEGER,
        created_at TEXT, expires_at TEXT, used_at TEXT
    )""")

    # runs predates neighborhoods; add the column rather than recreate the table.
    _ensure_column(conn, "runs", "neighborhood_id", "INTEGER")

    conn.commit()


# ----- users -----------------------------------------------------------------

def _user_to_row(user, position):
    return (
        user["id"], user["name"], user["age"], user["gender"],
        json.dumps(user["hobbies"]), user["personality"], user["occupation"],
        json.dumps(user["availability"]), user["location"], user["bio"],
        json.dumps(user["preferred_group_size"]), position,
    )


def _row_to_user(row):
    return {
        "id": row["id"], "name": row["name"], "age": row["age"], "gender": row["gender"],
        "hobbies": json.loads(row["hobbies"]), "personality": row["personality"],
        "occupation": row["occupation"], "availability": json.loads(row["availability"]),
        "location": row["location"], "bio": row["bio"],
        "preferred_group_size": json.loads(row["preferred_group_size"]),
    }


def list_users():
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM users ORDER BY position").fetchall()
    users = []
    i = 0
    while i < len(rows):
        users.append(_row_to_user(rows[i]))
        i += 1
    return users


def get_user(uid):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if row is None:
        return None
    return _row_to_user(row)


def replace_users(users):
    # swap the whole cast in one go (used by reset-to-defaults and by a fresh
    # AI-generated cast). Does not touch run/match/feedback history.
    conn = _get_conn()
    conn.execute("DELETE FROM users")
    i = 0
    while i < len(users):
        conn.execute(
            "INSERT INTO users (id, name, age, gender, hobbies, personality, occupation, "
            "availability, location, bio, preferred_group_size, position) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _user_to_row(users[i], i),
        )
        i += 1
    conn.commit()


def seed_default_users_if_empty(default_users):
    conn = _get_conn()
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count == 0:
        replace_users(default_users)


def update_user(uid, changes):
    # apply only whitelisted, already-validated fields; persist immediately;
    # return the merged user dict for the API response.
    user = get_user(uid)
    if user is None:
        return None
    conn = _get_conn()
    keys = list(changes.keys())
    i = 0
    while i < len(keys):
        key = keys[i]
        if key in EDITABLE_USER_FIELDS:
            user[key] = changes[key]
            value = changes[key]
            if key in ("hobbies", "availability", "preferred_group_size"):
                value = json.dumps(value)
            # safe: `key` is checked against the EDITABLE_USER_FIELDS whitelist
            # above, never taken from the raw request, so this cannot inject SQL.
            conn.execute("UPDATE users SET " + key + " = ? WHERE id = ?", (value, uid))
        i += 1
    conn.commit()
    return user


# ----- runs + interviews -------------------------------------------------------

def create_run(mode, users_signature):
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO runs (mode, users_signature, unmatched_ids, created_at) VALUES (?, ?, ?, ?)",
        (mode, users_signature, json.dumps([]), _now()),
    )
    conn.commit()
    return cur.lastrowid


def finish_run(run_id, unmatched_ids):
    conn = _get_conn()
    conn.execute("UPDATE runs SET unmatched_ids = ? WHERE id = ?", (json.dumps(unmatched_ids), run_id))
    conn.commit()


def save_interviews(run_id, interviews):
    conn = _get_conn()
    ids = list(interviews.keys())
    i = 0
    while i < len(ids):
        uid = ids[i]
        record = interviews[uid]
        conn.execute(
            "INSERT INTO interviews (run_id, user_id, profile, q1, q2, error) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, uid, json.dumps(record.get("profile")), record.get("q1"),
             record.get("q2"), record.get("error")),
        )
        i += 1
    conn.commit()


def load_interviews(run_id):
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM interviews WHERE run_id = ?", (run_id,)).fetchall()
    interviews = {}
    i = 0
    while i < len(rows):
        row = rows[i]
        record = {"profile": json.loads(row["profile"]), "q1": row["q1"], "q2": row["q2"]}
        if row["error"] is not None:
            record["error"] = row["error"]
        interviews[row["user_id"]] = record
        i += 1
    return interviews


def find_cached_interviews(users_signature, mode):
    # the most recent run with an identical cast + mode -> reuse its interviews
    # (skips re-asking the interview questions when nothing changed).
    conn = _get_conn()
    row = conn.execute(
        "SELECT id FROM runs WHERE users_signature = ? AND mode = ? ORDER BY id DESC LIMIT 1",
        (users_signature, mode),
    ).fetchone()
    if row is None:
        return None
    return load_interviews(row["id"])


# ----- matches, negotiations, meetups ------------------------------------------

def save_match(run_id, group_index, match):
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO matches (run_id, group_index, member_ids, reason, scores, why_not, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, group_index, json.dumps(match.get("group", [])), match.get("reason", ""),
         json.dumps(match.get("scores", {})), json.dumps(match.get("why_not", [])), _now()),
    )
    conn.commit()
    return cur.lastrowid


def save_negotiation(match_id, plan):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO negotiations (match_id, activity, agreed, concern, rounds, transcript) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (match_id, plan.get("activity", ""), 1 if plan.get("agreed") else 0,
         plan.get("concern", ""), plan.get("rounds", 0), json.dumps(plan.get("transcript", []))),
    )
    conn.commit()


def save_meetup(match_id, popup):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO meetups (match_id, options, event_name, activity, location, time, reason, matched_users) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (match_id, json.dumps(popup.get("options", [])), popup.get("event_name", ""),
         popup.get("activity", ""), popup.get("location", ""), popup.get("time", ""),
         popup.get("reason", ""), json.dumps(popup.get("matched_users", []))),
    )
    conn.commit()


def load_run_result(run_id):
    # reconstruct the exact shape run_pipeline() returns, so explain.py and the
    # /api/master-chat route work unchanged whether the run just happened or the
    # server restarted since.
    conn = _get_conn()
    run_row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if run_row is None:
        return None
    interviews = load_interviews(run_id)
    match_rows = conn.execute(
        "SELECT * FROM matches WHERE run_id = ? ORDER BY group_index", (run_id,)
    ).fetchall()
    groups = []
    i = 0
    while i < len(match_rows):
        mrow = match_rows[i]
        match = {"group": json.loads(mrow["member_ids"]), "reason": mrow["reason"],
                 "scores": json.loads(mrow["scores"]), "why_not": json.loads(mrow["why_not"])}

        neg_row = conn.execute("SELECT * FROM negotiations WHERE match_id = ?", (mrow["id"],)).fetchone()
        negotiation = None
        if neg_row is not None:
            negotiation = {"activity": neg_row["activity"], "final_activity": neg_row["activity"],
                            "agreed": bool(neg_row["agreed"]), "concern": neg_row["concern"],
                            "rounds": neg_row["rounds"], "transcript": json.loads(neg_row["transcript"])}

        pop_row = conn.execute("SELECT * FROM meetups WHERE match_id = ?", (mrow["id"],)).fetchone()
        popup = None
        if pop_row is not None:
            popup = {"options": json.loads(pop_row["options"]), "event_name": pop_row["event_name"],
                     "activity": pop_row["activity"], "location": pop_row["location"],
                     "time": pop_row["time"], "reason": pop_row["reason"],
                     "matched_users": json.loads(pop_row["matched_users"])}

        groups.append({"match": match, "negotiation": negotiation, "popup": popup})
        i += 1

    unmatched = json.loads(run_row["unmatched_ids"])
    return {"interviews": interviews, "groups": groups, "unmatched": unmatched}


def latest_run_id_for_signature(users_signature):
    # scoped to the CURRENT cast, so editing/resetting the people naturally
    # "forgets" the last run the same way the old in-memory STATE did.
    conn = _get_conn()
    row = conn.execute(
        "SELECT id FROM runs WHERE users_signature = ? ORDER BY id DESC LIMIT 1",
        (users_signature,),
    ).fetchone()
    if row is None:
        return None
    return row["id"]


# ----- feedback ----------------------------------------------------------------

def add_feedback(entry):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO feedback (match_id, members, rating, note, created_at) VALUES (?, ?, ?, ?, ?)",
        (entry.get("match_id"), json.dumps(entry.get("members", [])), entry.get("rating"),
         entry.get("note", ""), _now()),
    )
    conn.commit()


def list_feedback():
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM feedback ORDER BY id").fetchall()
    out = []
    i = 0
    while i < len(rows):
        row = rows[i]
        out.append({"members": json.loads(row["members"]), "rating": row["rating"], "note": row["note"]})
        i += 1
    return out


def clear_feedback():
    conn = _get_conn()
    conn.execute("DELETE FROM feedback")
    conn.commit()


# ----- real-user pilot: neighborhoods -------------------------------------------

def _row_to_neighborhood(row):
    return {
        "id": row["id"], "slug": row["slug"], "name": row["name"],
        "invite_code": row["invite_code"], "batch_threshold": row["batch_threshold"],
        "batch_triggered_at": row["batch_triggered_at"], "created_at": row["created_at"],
    }


def get_neighborhood(neighborhood_id):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM neighborhoods WHERE id = ?", (neighborhood_id,)).fetchone()
    if row is None:
        return None
    return _row_to_neighborhood(row)


def get_neighborhood_by_slug(slug):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM neighborhoods WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        return None
    return _row_to_neighborhood(row)


def get_or_create_neighborhood(slug, name, batch_threshold):
    # self-provisioning: the first visit to an invite link creates the
    # neighborhood row. batch_threshold is SNAPSHOTTED here, so a later change
    # to config.MATCH_BATCH_THRESHOLD never retroactively moves the goalposts
    # on a cohort that's already filling up.
    existing = get_neighborhood_by_slug(slug)
    if existing is not None:
        return existing
    conn = _get_conn()
    conn.execute(
        "INSERT INTO neighborhoods (slug, name, invite_code, batch_threshold, batch_triggered_at, created_at) "
        "VALUES (?, ?, ?, ?, NULL, ?)",
        (slug, name, slug, batch_threshold, _now()),
    )
    conn.commit()
    return get_neighborhood_by_slug(slug)


# ----- real-user pilot: residents -----------------------------------------------

def _row_to_resident(row):
    hobbies = None
    if row["hobbies"] is not None:
        hobbies = json.loads(row["hobbies"])
    availability = None
    if row["availability"] is not None:
        availability = json.loads(row["availability"])
    size = None
    if row["preferred_group_size"] is not None:
        size = json.loads(row["preferred_group_size"])
    slots = {}
    if row["slots_status"] is not None:
        slots = json.loads(row["slots_status"])
    return {
        "id": row["id"], "neighborhood_id": row["neighborhood_id"], "email": row["email"],
        "auth_method": row["auth_method"], "consent_agreed_at": row["consent_agreed_at"],
        "name": row["name"], "age": row["age"], "gender": row["gender"], "hobbies": hobbies,
        "personality": row["personality"], "occupation": row["occupation"],
        "availability": availability, "location": row["location"], "bio": row["bio"],
        "preferred_group_size": size, "slots_status": slots,
        "profile_complete_at": row["profile_complete_at"], "created_at": row["created_at"],
    }


def get_resident(resident_id):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM residents WHERE id = ?", (resident_id,)).fetchone()
    if row is None:
        return None
    return _row_to_resident(row)


def get_or_create_resident(neighborhood_id, email, auth_method):
    # a login always resolves to exactly one resident row per (neighborhood, email);
    # a brand-new resident starts with every profile field empty -- the
    # onboarding conversation fills them in over time (Milestone stage 3).
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM residents WHERE neighborhood_id = ? AND email = ?",
        (neighborhood_id, email),
    ).fetchone()
    if row is not None:
        return _row_to_resident(row)
    conn.execute(
        "INSERT INTO residents (neighborhood_id, email, auth_method, consent_agreed_at, "
        "name, age, gender, hobbies, personality, occupation, availability, location, bio, "
        "preferred_group_size, slots_status, profile_complete_at, created_at) "
        "VALUES (?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, NULL, ?)",
        (neighborhood_id, email, auth_method, json.dumps({}), _now()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM residents WHERE neighborhood_id = ? AND email = ?",
        (neighborhood_id, email),
    ).fetchone()
    return _row_to_resident(row)


def record_consent(resident_id):
    # first agreement wins -- a repeat call (e.g. a double-click) is a no-op,
    # not a timestamp bump.
    conn = _get_conn()
    conn.execute(
        "UPDATE residents SET consent_agreed_at = ? WHERE id = ? AND consent_agreed_at IS NULL",
        (_now(), resident_id),
    )
    conn.commit()
    return get_resident(resident_id)


# fields onboarding is allowed to fill in over the course of a conversation --
# the same profile columns EDITABLE_USER_FIELDS already whitelists for the
# demo cast, plus slots_status (which tracks the five gating slots, not a
# profile fact itself).
RESIDENT_PROFILE_FIELDS = EDITABLE_USER_FIELDS + ["slots_status"]
_RESIDENT_JSON_FIELDS = ("hobbies", "availability", "preferred_group_size", "slots_status")


def update_resident_profile(resident_id, fields):
    # partial update -- onboarding fills fields in gradually, one turn's worth
    # of extraction at a time, so only whitelisted keys actually present in
    # `fields` are touched (same whitelist-then-string-build pattern as
    # update_user).
    conn = _get_conn()
    keys = list(fields.keys())
    i = 0
    while i < len(keys):
        key = keys[i]
        if key in RESIDENT_PROFILE_FIELDS:
            value = fields[key]
            if key in _RESIDENT_JSON_FIELDS:
                value = json.dumps(value)
            # safe: `key` is checked against RESIDENT_PROFILE_FIELDS above,
            # never taken directly from the raw request, so this cannot inject SQL.
            conn.execute("UPDATE residents SET " + key + " = ? WHERE id = ?", (value, resident_id))
        i += 1
    conn.commit()
    return get_resident(resident_id)


def mark_profile_complete(resident_id):
    # idempotent -- same first-write-wins guard as record_consent.
    conn = _get_conn()
    conn.execute(
        "UPDATE residents SET profile_complete_at = ? WHERE id = ? AND profile_complete_at IS NULL",
        (_now(), resident_id),
    )
    conn.commit()
    return get_resident(resident_id)


# ----- real-user pilot: onboarding messages --------------------------------------

def save_onboarding_message(resident_id, role, content):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO onboarding_messages (resident_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (resident_id, role, content, _now()),
    )
    conn.commit()


def get_onboarding_messages(resident_id):
    # ordered transcript, shaped exactly like the history list Claw.chat expects.
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content FROM onboarding_messages WHERE resident_id = ? ORDER BY id ASC",
        (resident_id,),
    ).fetchall()
    messages = []
    i = 0
    while i < len(rows):
        messages.append({"role": rows[i]["role"], "content": rows[i]["content"]})
        i += 1
    return messages


# ----- real-user pilot: sessions ------------------------------------------------

def create_session(token, email, role, resident_id, neighborhood_id, ttl_seconds):
    conn = _get_conn()
    now = datetime.datetime.now(datetime.timezone.utc)
    expires = (now + datetime.timedelta(seconds=ttl_seconds)).isoformat()
    conn.execute(
        "INSERT INTO sessions (id, email, role, resident_id, neighborhood_id, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (token, email, role, resident_id, neighborhood_id, now.isoformat(), expires),
    )
    conn.commit()


def get_session(token):
    # a session is a plain DB lookup (not a signed/JWT token) -- trivially
    # revocable, and expiry is enforced here rather than trusted to the client.
    conn = _get_conn()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (token,)).fetchone()
    if row is None:
        return None
    if row["expires_at"] < _now():
        conn.execute("DELETE FROM sessions WHERE id = ?", (token,))
        conn.commit()
        return None
    return {"email": row["email"], "role": row["role"], "resident_id": row["resident_id"],
            "neighborhood_id": row["neighborhood_id"]}


def delete_session(token):
    conn = _get_conn()
    conn.execute("DELETE FROM sessions WHERE id = ?", (token,))
    conn.commit()


# ----- real-user pilot: magic links ---------------------------------------------

def create_magic_link_token(token_hash, email, neighborhood_id, ttl_seconds):
    # only the HASH is stored -- the raw token (which is what's actually emailed)
    # is never written to disk, so a copy of the database can't be used to log in.
    conn = _get_conn()
    now = datetime.datetime.now(datetime.timezone.utc)
    expires = (now + datetime.timedelta(seconds=ttl_seconds)).isoformat()
    conn.execute(
        "INSERT INTO magic_link_tokens (token_hash, email, neighborhood_id, created_at, expires_at, used_at) "
        "VALUES (?, ?, ?, ?, ?, NULL)",
        (token_hash, email, neighborhood_id, now.isoformat(), expires),
    )
    conn.commit()


def consume_magic_link_token(token_hash):
    # single-use: only an unexpired, not-yet-used row can be consumed.
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM magic_link_tokens WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?",
        (token_hash, _now()),
    ).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE magic_link_tokens SET used_at = ? WHERE id = ?", (_now(), row["id"]))
    conn.commit()
    return {"email": row["email"], "neighborhood_id": row["neighborhood_id"]}


# ----- real-user pilot: Google OAuth CSRF state ---------------------------------

def create_oauth_state(token_hash, neighborhood_id, ttl_seconds):
    conn = _get_conn()
    now = datetime.datetime.now(datetime.timezone.utc)
    expires = (now + datetime.timedelta(seconds=ttl_seconds)).isoformat()
    conn.execute(
        "INSERT INTO oauth_states (token_hash, neighborhood_id, created_at, expires_at, used_at) "
        "VALUES (?, ?, ?, ?, NULL)",
        (token_hash, neighborhood_id, now.isoformat(), expires),
    )
    conn.commit()


def consume_oauth_state(token_hash):
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM oauth_states WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?",
        (token_hash, _now()),
    ).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE oauth_states SET used_at = ? WHERE id = ?", (_now(), row["id"]))
    conn.commit()
    return {"neighborhood_id": row["neighborhood_id"]}


# ----- full reset (ops / tests) -------------------------------------------------

def reset_all(default_users):
    # wipe every table and restore the default cast -- used by tests and
    # available for manual ops resets.
    conn = _get_conn()
    tables = ["runs", "interviews", "matches", "negotiations", "meetups", "feedback",
              "neighborhoods", "residents", "onboarding_messages", "sessions",
              "magic_link_tokens", "oauth_states"]
    i = 0
    while i < len(tables):
        conn.execute("DELETE FROM " + tables[i])
        i += 1
    conn.commit()
    replace_users(default_users)
