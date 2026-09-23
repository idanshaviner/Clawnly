"""Persistent storage for Clawnly: one small SQLite file, plain sqlite3.

Pure storage plumbing -- it knows nothing about how agents talk or how the hub
decides; it saves and loads the plain dicts those modules produce.

Tables:
  neighborhoods     -- one invite-link cohort (slug, batch threshold, trigger state)
  residents         -- a real person's account + the dossier they brought
                       (what their own AI wrote about them) + its card
  sessions          -- durable login sessions
  magic_link_tokens -- single-use, hashed, expiring email login tokens
  oauth_states      -- single-use, expiring Google OAuth CSRF state tokens

  runs              -- one row per hub round (mode, neighborhood, API-call usage)
  events            -- the behind-the-scenes log: every hub thought and decision,
                       every agent message, every code check, every human action
                       (signup, join, yes/no, reveal, admin actions)
  ai_calls          -- every call to Claude, verbatim: purpose, model, the exact
                       prompt, the raw reply, tokens, time taken, any error
  agent_conversations -- one private Claw-to-Claw conversation + the hub's verdict
  matches           -- one invitation the hub sent (member ids, the hub's
                       headline, and details: pitches, the proposed meetup, the
                       conversation it came from) + sealed_at / dissolved_at
  match_acceptances -- one row per invited resident (the mutual yes/no gate)

Older databases may still hold tables from before the agent-to-agent pivot
(users, interviews, negotiations, meetups, feedback, onboarding_messages) and
old profile columns on residents; nothing reads them any more.
"""

import datetime
import json
import os
import sqlite3


_HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("CLAWNLY_DB_PATH") or os.path.join(os.path.dirname(_HERE), "clawnly.db")

_CONN = None

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
    conn.execute("""CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, mode TEXT, created_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, group_index INTEGER,
        member_ids TEXT, reason TEXT, scores TEXT, why_not TEXT, created_at TEXT
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
    conn.execute("""CREATE TABLE IF NOT EXISTS ai_calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, neighborhood_id INTEGER,
        resident_id INTEGER, purpose TEXT, model TEXT, system TEXT, messages TEXT,
        reply TEXT, input_tokens INTEGER, output_tokens INTEGER, ms INTEGER, error TEXT,
        created_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS agent_conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, a_id TEXT, b_id TEXT,
        why TEXT, turns TEXT, verdict TEXT, invited INTEGER, created_at TEXT
    )""")

    # runs predates neighborhoods; add the column rather than recreate the table.
    _ensure_column(conn, "runs", "neighborhood_id", "INTEGER")
    # sealed_at is set once every invited resident has said yes; dissolved_at
    # once anyone says no.
    _ensure_column(conn, "matches", "sealed_at", "TEXT")
    _ensure_column(conn, "matches", "dissolved_at", "TEXT")
    # per-round API call tally (ai_log.LoggedClient), JSON {"total":N,"by_model":{}}.
    _ensure_column(conn, "runs", "usage", "TEXT")
    # bring-your-agent signup (replaces the onboarding chat): what the
    # resident's own AI wrote about them, where it came from, the card the
    # hub builds from it, and how many previews they've used (each costs a call).
    _ensure_column(conn, "residents", "dossier_source", "TEXT")
    _ensure_column(conn, "residents", "dossier_text", "TEXT")
    _ensure_column(conn, "residents", "card", "TEXT")
    _ensure_column(conn, "residents", "dossier_previews", "INTEGER")
    # an invitation's pitches, proposed meetup and source conversation (JSON)
    _ensure_column(conn, "matches", "details", "TEXT")
    # so a neighborhood's whole story (signups, rounds, answers) reads as one feed
    _ensure_column(conn, "events", "neighborhood_id", "INTEGER")

    conn.commit()


# ----- runs ----------------------------------------------------------------------

def create_run(neighborhood_id=None):
    # one hub round. neighborhood_id is None for a round run outside the pilot
    # (e.g. the orchestrator CLI on the sample people).
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO runs (mode, created_at, neighborhood_id) VALUES (?, ?, ?)",
        ("agents", _now(), neighborhood_id),
    )
    conn.commit()
    return cur.lastrowid


def get_run(run_id):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    usage = None
    if row["usage"] is not None:
        usage = json.loads(row["usage"])
    return {"id": row["id"], "mode": row["mode"], "neighborhood_id": row["neighborhood_id"],
            "created_at": row["created_at"], "usage": usage}


# ----- invitations (stored as matches) -------------------------------------------

def create_invitation(run_id, index, member_ids, headline, depth, details):
    # one hub invitation. member_ids are "r"-prefixed resident ids; details is
    # {"conversation_id", "invite": {activity, when, where}, "pitches": {member_id: text}}.
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO matches (run_id, group_index, member_ids, reason, scores, why_not, created_at, details) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, index, json.dumps(member_ids), headline, json.dumps({"depth": depth}),
         json.dumps([]), _now(), json.dumps(details)),
    )
    conn.commit()
    return cur.lastrowid


def _row_to_match(row):
    details = {}
    if row["details"] is not None:
        details = json.loads(row["details"])
    return {
        "id": row["id"], "run_id": row["run_id"], "group_index": row["group_index"],
        "member_ids": json.loads(row["member_ids"]), "reason": row["reason"],
        "scores": json.loads(row["scores"]), "details": details,
        "created_at": row["created_at"], "sealed_at": row["sealed_at"],
        "dissolved_at": row["dissolved_at"],
    }


def get_match(match_id):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    if row is None:
        return None
    return _row_to_match(row)


def set_run_usage(run_id, usage):
    # per-round API call tally from ai_log.LoggedClient
    conn = _get_conn()
    conn.execute("UPDATE runs SET usage = ? WHERE id = ?", (json.dumps(usage), run_id))
    conn.commit()


def list_runs_for_neighborhood(neighborhood_id, limit=10):
    # newest-first summary of past hub rounds for the admin dashboard --
    # conversation / invitation / failure counts + the call-usage tally.
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM runs WHERE neighborhood_id = ? ORDER BY id DESC LIMIT ?",
        (neighborhood_id, limit),
    ).fetchall()
    out = []
    i = 0
    while i < len(rows):
        row = rows[i]
        invitation_count = conn.execute(
            "SELECT COUNT(*) FROM matches WHERE run_id = ?", (row["id"],)
        ).fetchone()[0]
        conversation_count = conn.execute(
            "SELECT COUNT(*) FROM agent_conversations WHERE run_id = ?", (row["id"],)
        ).fetchone()[0]
        # a conversation that never got a verdict failed partway
        failed_count = conn.execute(
            "SELECT COUNT(*) FROM agent_conversations WHERE run_id = ? AND verdict IS NULL", (row["id"],)
        ).fetchone()[0]
        usage = None
        if row["usage"] is not None:
            usage = json.loads(row["usage"])
        out.append({
            "id": row["id"], "mode": row["mode"], "created_at": row["created_at"],
            "conversation_count": conversation_count, "invitation_count": invitation_count,
            "failed_count": failed_count, "usage": usage,
        })
        i += 1
    return out


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
    card = None
    if row["card"] is not None:
        card = json.loads(row["card"])
    previews = row["dossier_previews"]
    if previews is None:
        previews = 0
    return {
        "id": row["id"], "neighborhood_id": row["neighborhood_id"], "email": row["email"],
        "auth_method": row["auth_method"], "consent_agreed_at": row["consent_agreed_at"],
        "name": row["name"], "profile_complete_at": row["profile_complete_at"], "created_at": row["created_at"],
        "dossier_source": row["dossier_source"], "dossier_text": row["dossier_text"],
        "card": card, "dossier_previews": previews,
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
    # every resident in this cohort who has joined with their agent: signed up
    # AND brought a dossier (a leftover profile from the old onboarding chat
    # has no dossier, so its agent would have nothing to say -- never counted).
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM residents WHERE neighborhood_id = ? AND profile_complete_at IS NOT NULL "
        "AND dossier_text IS NOT NULL AND card IS NOT NULL ORDER BY id",
        (neighborhood_id,),
    ).fetchall()
    out = []
    i = 0
    while i < len(rows):
        out.append(_row_to_resident(rows[i]))
        i += 1
    return out


def list_eligible_residents(neighborhood_id):
    # joined AND not currently tied to a LIVE (non-dissolved) invitation --
    # either never invited yet, or their last invitation was dissolved by a
    # "no" and they're back in the pool. A pending/waiting/sealed invitation's
    # members stay excluded, so nobody is ever holding two invitations at once.
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


def save_dossier_draft(resident_id, name, source, text, card):
    # the latest "build my agent's card" preview -- stored server-side so the
    # confirm step joins exactly what was previewed, never a card the browser
    # sent back. Only allowed before joining (profile_complete_at IS NULL).
    conn = _get_conn()
    conn.execute(
        "UPDATE residents SET name = ?, dossier_source = ?, dossier_text = ?, card = ?, "
        "dossier_previews = COALESCE(dossier_previews, 0) + 1 "
        "WHERE id = ? AND profile_complete_at IS NULL",
        (name, source, text, json.dumps(card), resident_id),
    )
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


# ----- agent-to-agent orchestration: events + conversations ------------------------

def log_event(run_id, actor, kind, text, ref=None, neighborhood_id=None):
    # one line of the behind-the-scenes log. actor is who acted (hub / agent /
    # code / human / system); kind is what it was (thought / decision / message /
    # check / human / system). ref points at the conversation it belongs to.
    # run_id is None for things that happen outside a hub round (a signup, a yes/no).
    conn = _get_conn()
    conn.execute(
        "INSERT INTO events (run_id, actor, kind, text, ref, created_at, neighborhood_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, actor, kind, text, ref, _now(), neighborhood_id),
    )
    conn.commit()


def _row_to_event(row):
    return {"id": row["id"], "run_id": row["run_id"], "neighborhood_id": row["neighborhood_id"],
            "actor": row["actor"], "kind": row["kind"], "text": row["text"], "ref": row["ref"],
            "created_at": row["created_at"]}


def list_events(run_id):
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM events WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
    out = []
    i = 0
    while i < len(rows):
        out.append(_row_to_event(rows[i]))
        i += 1
    return out


def list_neighborhood_events(neighborhood_id, limit=500):
    # the neighborhood's whole story, oldest first: the most recent `limit` events
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM (SELECT * FROM events WHERE neighborhood_id = ? ORDER BY id DESC LIMIT ?) ORDER BY id",
        (neighborhood_id, limit),
    ).fetchall()
    out = []
    i = 0
    while i < len(rows):
        out.append(_row_to_event(rows[i]))
        i += 1
    return out


def log_ai_call(run_id, neighborhood_id, resident_id, purpose, model, system, messages, reply,
                input_tokens, output_tokens, ms, error):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO ai_calls (run_id, neighborhood_id, resident_id, purpose, model, system, messages, "
        "reply, input_tokens, output_tokens, ms, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, neighborhood_id, resident_id, purpose, model, system, json.dumps(messages), reply,
         input_tokens, output_tokens, ms, error, _now()),
    )
    conn.commit()


def _row_to_ai_call(row):
    return {"id": row["id"], "run_id": row["run_id"], "neighborhood_id": row["neighborhood_id"],
            "resident_id": row["resident_id"], "purpose": row["purpose"], "model": row["model"],
            "system": row["system"], "messages": json.loads(row["messages"]), "reply": row["reply"],
            "input_tokens": row["input_tokens"], "output_tokens": row["output_tokens"],
            "ms": row["ms"], "error": row["error"], "created_at": row["created_at"]}


def list_ai_calls(run_id):
    # every Claude call a hub round made, in order
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM ai_calls WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
    out = []
    i = 0
    while i < len(rows):
        out.append(_row_to_ai_call(rows[i]))
        i += 1
    return out


def list_signup_ai_calls(neighborhood_id, limit=100):
    # Claude calls made outside a round (building people's cards at signup), newest last
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM (SELECT * FROM ai_calls WHERE neighborhood_id = ? AND run_id IS NULL "
        "ORDER BY id DESC LIMIT ?) ORDER BY id",
        (neighborhood_id, limit),
    ).fetchall()
    out = []
    i = 0
    while i < len(rows):
        out.append(_row_to_ai_call(rows[i]))
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


# ----- full reset (ops / tests) -------------------------------------------------

def reset_all():
    # wipe every table -- used by tests and available for manual ops resets.
    conn = _get_conn()
    tables = ["runs", "matches", "neighborhoods", "residents", "sessions",
              "magic_link_tokens", "oauth_states", "match_acceptances",
              "events", "agent_conversations", "ai_calls"]
    i = 0
    while i < len(tables):
        conn.execute("DELETE FROM " + tables[i])
        i += 1
    conn.commit()
