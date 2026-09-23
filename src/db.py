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
  match_acceptances -- one row per resident member of a formed match (mutual
                       reveal gate); matches also gains sealed_at/dissolved_at

  -- agent-to-agent orchestration (orchestrator.py / agent_talk.py) --
  events            -- the behind-the-scenes log: every hub thought and decision,
                       every agent message, every code check, every human action
  agent_conversations -- one private Claw-to-Claw conversation + the hub's verdict
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
    conn.execute("""CREATE TABLE IF NOT EXISTS match_acceptances (
        id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER, resident_id INTEGER,
        status TEXT, created_at TEXT, responded_at TEXT,
        UNIQUE(match_id, resident_id)
    )""")

    # ----- agent-to-agent orchestration -----
    conn.execute("""CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, actor TEXT, kind TEXT,
        text TEXT, ref TEXT, created_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS agent_conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, a_id TEXT, b_id TEXT,
        why TEXT, turns TEXT, verdict TEXT, invited INTEGER, created_at TEXT
    )""")

    # runs predates neighborhoods; add the column rather than recreate the table.
    _ensure_column(conn, "runs", "neighborhood_id", "INTEGER")
    # matches predates the mutual-reveal gate (Stage 5): sealed_at is set once
    # every resident member has accepted; dissolved_at once anyone declines.
    # Group-level lifecycle state lives here rather than being inferred solely
    # from match_acceptances rows, so it survives even a match with zero
    # resident members (an all-demo-cast admin-console group).
    _ensure_column(conn, "matches", "sealed_at", "TEXT")
    _ensure_column(conn, "matches", "dissolved_at", "TEXT")
    # per-run API call tally (Stage 6 admin usage visibility) -- reuses the
    # existing CountingClient call-count pattern, JSON {"total":N,"by_model":{}}.
    _ensure_column(conn, "runs", "usage", "TEXT")

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

def create_run(mode, users_signature, neighborhood_id=None):
    # neighborhood_id is None for an admin-console demo/live run on the fixed
    # cast, and set for a real-pilot batch run (Stage 4) -- lets the two kinds
    # of run share one table without a parallel history table.
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO runs (mode, users_signature, unmatched_ids, created_at, neighborhood_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (mode, users_signature, json.dumps([]), _now(), neighborhood_id),
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


def _row_to_match(row):
    return {
        "id": row["id"], "run_id": row["run_id"], "group_index": row["group_index"],
        "member_ids": json.loads(row["member_ids"]), "reason": row["reason"],
        "scores": json.loads(row["scores"]), "why_not": json.loads(row["why_not"]),
        "created_at": row["created_at"], "sealed_at": row["sealed_at"],
        "dissolved_at": row["dissolved_at"],
    }


def get_match(match_id):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    if row is None:
        return None
    return _row_to_match(row)


def get_negotiation(match_id):
    # single-negotiation lookup (load_run_result reconstructs a whole run's
    # worth at once; my_match.py only ever needs one match's).
    conn = _get_conn()
    row = conn.execute("SELECT * FROM negotiations WHERE match_id = ?", (match_id,)).fetchone()
    if row is None:
        return None
    return {"activity": row["activity"], "agreed": bool(row["agreed"]), "concern": row["concern"],
            "rounds": row["rounds"], "transcript": json.loads(row["transcript"])}


def get_meetup(match_id):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM meetups WHERE match_id = ?", (match_id,)).fetchone()
    if row is None:
        return None
    return {"options": json.loads(row["options"]), "event_name": row["event_name"],
            "activity": row["activity"], "location": row["location"], "time": row["time"],
            "reason": row["reason"], "matched_users": json.loads(row["matched_users"])}


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


def _resident_member_ids(member_ids):
    # batch.py always prefixes a resident-sourced member "r" + resident id
    # (e.g. "r17") specifically so it can never collide with the demo cast's
    # "u01"-style ids -- pick those out and recover the real resident id.
    out = []
    i = 0
    while i < len(member_ids):
        mid = member_ids[i]
        if isinstance(mid, str) and mid.startswith("r") and mid[1:].isdigit():
            out.append(int(mid[1:]))
        i += 1
    return out


def persist_run_result(mode, signature, result, neighborhood_id=None):
    # save a completed pipeline run (interviews, every group formed, each
    # group's negotiation + meetup) so it survives a restart. Shared by
    # app.py's admin-console runs (neighborhood_id=None) and batch.py's
    # real-pilot batch runs (Stage 4), so this persistence sequence only
    # lives in one place. Every resident member of a formed group also gets a
    # pending match_acceptances row here (Stage 5's mutual reveal gate) -- a
    # no-op for an admin-console run, since none of its member ids start
    # with "r".
    run_id = create_run(mode, signature, neighborhood_id)
    save_interviews(run_id, result["interviews"])
    groups = result["groups"]
    gi = 0
    while gi < len(groups):
        entry = groups[gi]
        match_id = save_match(run_id, gi, entry["match"])
        if entry.get("negotiation") is not None:
            save_negotiation(match_id, entry["negotiation"])
        if entry.get("popup") is not None:
            save_meetup(match_id, entry["popup"])
        resident_ids = _resident_member_ids(entry["match"].get("group", []))
        if len(resident_ids) > 0:
            create_pending_acceptances(match_id, resident_ids)
        gi += 1
    finish_run(run_id, result["unmatched"])
    if result.get("usage") is not None:
        set_run_usage(run_id, result["usage"])
    return run_id


def set_run_usage(run_id, usage):
    # per-run API call tally (Stage 6 admin dashboard) -- only ever set when
    # the pipeline ran with a CountingClient (see usage.py), so most
    # admin-console demo runs simply never call this.
    conn = _get_conn()
    conn.execute("UPDATE runs SET usage = ? WHERE id = ?", (json.dumps(usage), run_id))
    conn.commit()


def list_runs_for_neighborhood(neighborhood_id, limit=10):
    # newest-first summary of past batch runs for the admin dashboard --
    # group/unmatched counts + the call-usage tally, without reconstructing
    # every interview/match/negotiation/meetup row (load_run_result does that
    # for the one run at a time admin.py actually inspects in detail).
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM runs WHERE neighborhood_id = ? ORDER BY id DESC LIMIT ?",
        (neighborhood_id, limit),
    ).fetchall()
    out = []
    i = 0
    while i < len(rows):
        row = rows[i]
        group_count = conn.execute(
            "SELECT COUNT(*) FROM matches WHERE run_id = ?", (row["id"],)
        ).fetchone()[0]
        usage = None
        if row["usage"] is not None:
            usage = json.loads(row["usage"])
        out.append({
            "id": row["id"], "mode": row["mode"], "created_at": row["created_at"],
            "group_count": group_count,
            "unmatched_count": len(json.loads(row["unmatched_ids"])),
            "usage": usage,
        })
        i += 1
    return out


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


def list_neighborhoods():
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM neighborhoods ORDER BY id").fetchall()
    out = []
    i = 0
    while i < len(rows):
        out.append(_row_to_neighborhood(rows[i]))
        i += 1
    return out


def mark_batch_triggered(neighborhood_id):
    # the admin dashboard's manual "trigger batch now" override (Stage 6) --
    # unlike try_trigger_batch's compare-and-swap (the automatic, one-shot,
    # concurrency-safe guard on a resident completion crossing the
    # threshold), this is a deliberate, single, authenticated admin action
    # that's allowed to fire again even after an earlier automatic or manual
    # trigger -- e.g. to re-match residents a decline released back into the
    # pool, since nothing else currently re-triggers for them (see
    # ROADMAP.md's Stage 5 caveat).
    conn = _get_conn()
    conn.execute("UPDATE neighborhoods SET batch_triggered_at = ? WHERE id = ?", (_now(), neighborhood_id))
    conn.commit()


def try_trigger_batch(neighborhood_id):
    # compare-and-swap: only the caller that actually flips batch_triggered_at
    # from NULL wins (rowcount 1), so two near-simultaneous onboarding
    # completions crossing the threshold at once can't both trigger a run.
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE neighborhoods SET batch_triggered_at = ? WHERE id = ? AND batch_triggered_at IS NULL",
        (_now(), neighborhood_id),
    )
    conn.commit()
    return cur.rowcount == 1


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


def list_residents(neighborhood_id):
    # EVERY resident in this cohort, complete or not -- the admin dashboard's
    # full roster (list_complete_residents/list_eligible_residents stay
    # scoped to what batch.py actually needs).
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM residents WHERE neighborhood_id = ? ORDER BY id", (neighborhood_id,)
    ).fetchall()
    out = []
    i = 0
    while i < len(rows):
        out.append(_row_to_resident(rows[i]))
        i += 1
    return out


def list_complete_residents(neighborhood_id):
    # every resident in this cohort whose onboarding has crossed the five-slot
    # completeness bar -- the pool batch.py counts against batch_threshold and
    # maps into run_pipeline profiles.
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM residents WHERE neighborhood_id = ? AND profile_complete_at IS NOT NULL "
        "ORDER BY id",
        (neighborhood_id,),
    ).fetchall()
    out = []
    i = 0
    while i < len(rows):
        out.append(_row_to_resident(rows[i]))
        i += 1
    return out


def list_eligible_residents(neighborhood_id):
    # profile-complete AND not currently tied to a LIVE (non-dissolved) match
    # -- either never matched yet, or their last match was dissolved by a
    # decline and they've been released back into the pool without redoing
    # onboarding. A pending/waiting/sealed match's members stay excluded
    # (their match's dissolved_at stays NULL), so nobody is ever double-
    # booked into two matches at once. Builds on list_complete_residents
    # rather than duplicating its row-building.
    complete = list_complete_residents(neighborhood_id)
    conn = _get_conn()
    rows = conn.execute(
        "SELECT DISTINCT ma.resident_id FROM match_acceptances ma "
        "JOIN matches m ON ma.match_id = m.id WHERE m.dissolved_at IS NULL"
    ).fetchall()
    active_ids = set()
    i = 0
    while i < len(rows):
        active_ids.add(rows[i]["resident_id"])
        i += 1
    out = []
    i = 0
    while i < len(complete):
        if complete[i]["id"] not in active_ids:
            out.append(complete[i])
        i += 1
    return out


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


# ----- real-user pilot: match acceptances (mutual reveal gate) -----------------

def create_pending_acceptances(match_id, resident_ids):
    conn = _get_conn()
    now = _now()
    i = 0
    while i < len(resident_ids):
        conn.execute(
            "INSERT INTO match_acceptances (match_id, resident_id, status, created_at, responded_at) "
            "VALUES (?, ?, 'pending', ?, NULL)",
            (match_id, resident_ids[i], now),
        )
        i += 1
    conn.commit()


def _row_to_acceptance(row):
    return {"id": row["id"], "match_id": row["match_id"], "resident_id": row["resident_id"],
            "status": row["status"], "created_at": row["created_at"], "responded_at": row["responded_at"]}


def get_acceptance(match_id, resident_id):
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM match_acceptances WHERE match_id = ? AND resident_id = ?",
        (match_id, resident_id),
    ).fetchone()
    if row is None:
        return None
    return _row_to_acceptance(row)


def list_match_acceptances(match_id):
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM match_acceptances WHERE match_id = ? ORDER BY id", (match_id,)
    ).fetchall()
    out = []
    i = 0
    while i < len(rows):
        out.append(_row_to_acceptance(rows[i]))
        i += 1
    return out


def latest_match_acceptance(resident_id):
    # the resident's own most recent match, whichever state it's in (pending/
    # waiting/sealed/dissolved) -- my_match.py resolves the whole /api/my-match
    # state from this single row plus its match, never a client-supplied id.
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM match_acceptances WHERE resident_id = ? ORDER BY id DESC LIMIT 1",
        (resident_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_acceptance(row)


def respond_to_acceptance(match_id, resident_id, status):
    # first response wins -- same idempotency guard as record_consent, so a
    # double-click can't flip an already-recorded accept/decline.
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE match_acceptances SET status = ?, responded_at = ? "
        "WHERE match_id = ? AND resident_id = ? AND status = 'pending'",
        (status, _now(), match_id, resident_id),
    )
    conn.commit()
    return cur.rowcount == 1


def mark_match_sealed(match_id):
    conn = _get_conn()
    conn.execute("UPDATE matches SET sealed_at = ? WHERE id = ? AND sealed_at IS NULL", (_now(), match_id))
    conn.commit()


def mark_match_dissolved(match_id):
    conn = _get_conn()
    conn.execute("UPDATE matches SET dissolved_at = ? WHERE id = ? AND dissolved_at IS NULL", (_now(), match_id))
    conn.commit()


# ----- full reset (ops / tests) -------------------------------------------------

# ----- agent-to-agent orchestration: events + conversations ------------------------

def log_event(run_id, actor, kind, text, ref=None):
    # one line of the behind-the-scenes log. actor is who acted (hub / agent /
    # code / human / system); kind is what it was (thought / decision / message /
    # check / human / system). ref points at the conversation it belongs to.
    conn = _get_conn()
    conn.execute(
        "INSERT INTO events (run_id, actor, kind, text, ref, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, actor, kind, text, ref, _now()),
    )
    conn.commit()


def list_events(run_id):
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM events WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
    out = []
    i = 0
    while i < len(rows):
        row = rows[i]
        out.append({"id": row["id"], "actor": row["actor"], "kind": row["kind"], "text": row["text"],
                    "ref": row["ref"], "created_at": row["created_at"]})
        i += 1
    return out


def save_agent_conversation(run_id, a_id, b_id, why, turns):
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO agent_conversations (run_id, a_id, b_id, why, turns, verdict, invited, created_at) "
        "VALUES (?, ?, ?, ?, ?, NULL, 0, ?)",
        (run_id, a_id, b_id, why, json.dumps(turns), _now()),
    )
    conn.commit()
    return cur.lastrowid


def set_agent_turns(conversation_id, turns):
    conn = _get_conn()
    conn.execute("UPDATE agent_conversations SET turns = ? WHERE id = ?", (json.dumps(turns), conversation_id))
    conn.commit()


def set_agent_verdict(conversation_id, verdict, invited):
    conn = _get_conn()
    invited_flag = 0
    if invited:
        invited_flag = 1
    conn.execute("UPDATE agent_conversations SET verdict = ?, invited = ? WHERE id = ?",
                 (json.dumps(verdict), invited_flag, conversation_id))
    conn.commit()


def _row_to_agent_conversation(row):
    verdict = None
    if row["verdict"] is not None:
        verdict = json.loads(row["verdict"])
    return {"id": row["id"], "run_id": row["run_id"], "a": row["a_id"], "b": row["b_id"],
            "why": row["why"], "turns": json.loads(row["turns"]), "verdict": verdict,
            "invited": bool(row["invited"]), "created_at": row["created_at"]}


def list_agent_conversations(run_id=None):
    # every conversation of one run, or of all runs (so the hub never pairs
    # the same two agents twice).
    conn = _get_conn()
    if run_id is None:
        rows = conn.execute("SELECT * FROM agent_conversations ORDER BY id").fetchall()
    else:
        rows = conn.execute("SELECT * FROM agent_conversations WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
    out = []
    i = 0
    while i < len(rows):
        out.append(_row_to_agent_conversation(rows[i]))
        i += 1
    return out


def reset_all(default_users):
    # wipe every table and restore the default cast -- used by tests and
    # available for manual ops resets.
    conn = _get_conn()
    tables = ["runs", "interviews", "matches", "negotiations", "meetups", "feedback",
              "neighborhoods", "residents", "onboarding_messages", "sessions",
              "magic_link_tokens", "oauth_states", "match_acceptances",
              "events", "agent_conversations"]
    i = 0
    while i < len(tables):
        conn.execute("DELETE FROM " + tables[i])
        i += 1
    conn.commit()
    replace_users(default_users)
