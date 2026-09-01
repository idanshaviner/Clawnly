"""Admin dashboard (PILOT_PLAN.md's admin surface, Stage 6): neighborhood
progress, resident status, recent batch runs, and usage visibility -- all
built by reusing data the earlier stages already collect and persist, per
the plan ("reusing existing data rather than building new tracking"). No new
tracking of its own beyond usage.py's call-count wrapper. Read-only; the
one write action (manually triggering a batch) is batch.force_trigger_batch,
called directly from app.py's route.

Gated entirely by auth.is_admin(email) via app.py's _require_admin -- the
same plain email-allowlist pattern login already uses, not a new permission
system.
"""

import db


def neighborhood_progress(neighborhood):
    complete = len(db.list_complete_residents(neighborhood["id"]))
    total = len(db.list_residents(neighborhood["id"]))
    return {
        "id": neighborhood["id"], "slug": neighborhood["slug"], "name": neighborhood["name"],
        "batch_threshold": neighborhood["batch_threshold"], "complete_count": complete,
        "resident_count": total, "batch_triggered_at": neighborhood["batch_triggered_at"],
    }


def list_neighborhood_progress():
    neighborhoods = db.list_neighborhoods()
    out = []
    i = 0
    while i < len(neighborhoods):
        out.append(neighborhood_progress(neighborhoods[i]))
        i += 1
    return out


def _resident_status(resident):
    # a plain, human-readable rollup of state spread across residents.
    # profile_complete_at, match_acceptances, and matches.sealed_at/
    # dissolved_at -- nothing new is tracked to compute this.
    if resident["profile_complete_at"] is None:
        return "onboarding"
    acceptance = db.latest_match_acceptance(resident["id"])
    if acceptance is None:
        return "complete_unmatched"
    match = db.get_match(acceptance["match_id"])
    if match is None:
        return "complete_unmatched"
    if match["dissolved_at"] is not None:
        return "dissolved"
    if match["sealed_at"] is not None:
        return "sealed"
    if acceptance["status"] == "pending":
        return "match_pending"
    return "match_waiting"


def resident_summaries(neighborhood_id):
    residents = db.list_residents(neighborhood_id)
    out = []
    i = 0
    while i < len(residents):
        r = residents[i]
        out.append({
            "id": r["id"], "email": r["email"], "name": r["name"],
            "consent_agreed_at": r["consent_agreed_at"],
            "profile_complete_at": r["profile_complete_at"],
            "slots_status": r["slots_status"], "status": _resident_status(r),
        })
        i += 1
    return out


def recent_run_summaries(neighborhood_id, limit=5):
    # each run's group/unmatched counts + usage tally, plus any interview
    # failures (the existing "error" field db.load_run_result already
    # surfaces) -- exactly the "recent interview/batch failures" the plan
    # calls for, with no new failure-tracking of its own.
    runs = db.list_runs_for_neighborhood(neighborhood_id, limit=limit)
    i = 0
    while i < len(runs):
        run = runs[i]
        result = db.load_run_result(run["id"])
        errors = []
        ids = list(result["interviews"].keys())
        j = 0
        while j < len(ids):
            record = result["interviews"][ids[j]]
            if "error" in record:
                errors.append({"id": ids[j], "error": record["error"]})
            j += 1
        run["interview_errors"] = errors
        i += 1
    return runs
