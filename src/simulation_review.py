"""Check saved simulations and export a plain review queue. No API or database calls.

    .venv/bin/python src/simulation_review.py

The CSV has one row per proposed group and empty columns for human notes. Existing
notes are kept by match id. Raw run files are only read, never rewritten.
"""

import csv
import hashlib
import json
from pathlib import Path
import sys
import zipfile


ROOT = Path(__file__).resolve().parent.parent / "simulation_results"
TARGET = 200
FIELDS = ["match_id", "run", "day", "activity", "time", "status", "members",
          "hub_reason_verbatim", "agent_answers_verbatim", "conversation_verbatim", "ai_review_status",
          "ai_verdict", "ai_summary", "source", "same_activity_and_members_seen_in",
          "human_verdict", "human_notes"]


def run_folders(root):
    # accept older exports while new runs stay out of the reviewer's way
    folders = sorted(root.glob("run_*"))
    folders.extend(sorted((root / "runs").glob("run_*")))
    return folders


def metadata_path(root, name):
    if (root / "metadata").is_dir():
        return root / "metadata" / name
    return root / name


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def require(ok, message, errors):
    if not ok:
        errors.append(message)


def inspect_run(folder):
    manifest = read(folder / "run_manifest.json")
    initial = read(folder / "agents_initial.json")
    final = read(folder / "agents_final.json")
    groups = read(folder / "groups_generated.json")
    events = []
    lines = (folder / "full_simulation.jsonl").read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        if lines[i].strip():
            events.append(json.loads(lines[i]))
        i += 1
    by_seq = {}
    prompts = {}
    calls = 0
    failed_calls = 0
    answers = 0
    errors = []
    i = 0
    while i < len(events):
        event = events[i]
        require(event["seq"] not in by_seq, "duplicate event number", errors)
        by_seq[event["seq"]] = event
        if event["type"] == "agent_init":
            prompts[event["person"]] = event["agent_system_prompt"]
        if event["type"] == "model_call":
            calls += 1
            if event.get("error"):
                failed_calls += 1
            require(bool(event.get("request")) and (bool(event.get("response")) or bool(event.get("error"))),
                    "missing request/reply at event " + str(event["seq"]), errors)
        if event["type"] == "agent_to_hub":
            answers += 1
        i += 1
    after = {}
    i = 0
    while i < len(final):
        after[final[i]["id"]] = final[i]
        i += 1
    i = 0
    while i < len(initial):
        person = initial[i]
        require(person["agent_system_prompt"] == prompts.get(person["id"]),
                "initial prompt differs from log: " + person["id"], errors)
        before = dict(person)
        del before["agent_system_prompt"]
        del before["what_the_hub_sees"]
        require(person["id"] in after, "missing final profile: " + person["id"], errors)
        if person["id"] in after:
            actual_change = before != after[person["id"]]["profile_after"]
            require(actual_change == after[person["id"]]["profile_changed"],
                    "incorrect profile-change flag: " + person["id"], errors)
        i += 1
    audits = {}
    if (folder / "audit_ai.json").exists():
        saved = read(folder / "audit_ai.json")
        i = 0
        while i < len(saved["groups"]):
            audits[saved["groups"][i]["group"]] = saved["groups"][i]
            i += 1
    rows = []
    locked = 0
    i = 0
    while i < len(groups):
        group = groups[i]
        if group["status"] == "locked":
            locked += 1
        require(bool(group.get("why_hub_chose_it")), "missing hub reason: " + group["group"], errors)
        evidence = group["evidence"]
        require(evidence.get("plan_call_seq") in by_seq, "missing plan call: " + group["group"], errors)
        require(evidence.get("status_seq") in by_seq, "missing status event: " + group["group"], errors)
        proposal = by_seq.get(evidence.get("proposed_seq"), {})
        status = by_seq.get(evidence.get("status_seq"), {})
        require(proposal.get("why") == group["why_hub_chose_it"],
                "hub reason differs from log: " + group["group"], errors)
        require(status.get("after") == group["status"] and status.get("final", []) == group["final_members"],
                "final group differs from log: " + group["group"], errors)
        replies = []
        exchanges = []
        names = []
        j = 0
        while j < len(group["members"]):
            member = group["members"][j]
            if member["id"] in group["final_members"]:
                names.append(member["id"] + " " + member["name"])
            k = 0
            while k < len(member["answers"]):
                answer = member["answers"][k]
                ask = by_seq.get(answer["ask_seq"], {})
                reply = by_seq.get(answer["reply_seq"], {})
                call = by_seq.get(answer["call_seq"], {})
                require(ask.get("type") == "hub_to_agent" and ask.get("person") == member["id"],
                        "missing or wrong invitation: " + group["group"], errors)
                require(reply.get("text") == answer["said"] and reply.get("person") == member["id"],
                        "reply differs from log: " + group["group"], errors)
                require(call.get("type") == "model_call", "missing agent call: " + group["group"], errors)
                require(call.get("request", {}).get("system") == prompts.get(member["id"]),
                        "delivered agent prompt differs: " + group["group"], errors)
                replies.append(member["id"] + " " + member["name"] + ", round " + str(answer["round"])
                               + " [#" + str(answer["reply_seq"]) + "]: " + answer["answer"] + ". "
                               + answer["said"] + " Counter: " + str(answer.get("counter") or "none"))
                exchanges.append((answer["ask_seq"], "HUB -> " + member["id"] + " " + member["name"]
                                  + " [#" + str(answer["ask_seq"]) + "]: " + str(ask.get("text", ""))))
                exchanges.append((answer["reply_seq"], member["id"] + " " + member["name"] + " -> HUB"
                                  + " [#" + str(answer["reply_seq"]) + "]: " + answer["answer"] + ". "
                                  + answer["said"] + " Counter: " + str(answer.get("counter") or "none")))
                k += 1
            j += 1
        exchanges.sort()
        conversation = []
        j = 0
        while j < len(exchanges):
            conversation.append(exchanges[j][1])
            j += 1
        reviewed = audits.get(group["group"], {})
        review_status = "No separate AI audit saved"
        if reviewed:
            review_status = "Separate AI audit saved"
        rows.append({"match_id": folder.name + "/" + group["group"], "run": folder.name,
                     "day": group["day"], "activity": group["activity_name"], "time": group["time_final"],
                     "status": group["status"], "members": "; ".join(names),
                     "hub_reason_verbatim": group["why_hub_chose_it"],
                     "agent_answers_verbatim": "\n".join(replies),
                     "conversation_verbatim": "\n\n".join(conversation), "ai_review_status": review_status,
                     "ai_verdict": reviewed.get("verdict", ""), "ai_summary": reviewed.get("summary", ""),
                     "source": folder.name + "/run_dump.txt", "same_activity_and_members_seen_in": "",
                     "human_verdict": "", "human_notes": ""})
        i += 1
    require(len(groups) == manifest["groups_proposed"], "manifest proposed count differs", errors)
    require(locked == manifest["groups_locked"], "manifest locked count differs", errors)
    require(len(initial) == manifest["people"], "manifest people count differs", errors)
    digests = {}
    files = ["run_manifest.json", "full_simulation.jsonl", "agents_initial.json",
             "agents_final.json", "groups_generated.json"]
    i = 0
    while i < len(files):
        digests[files[i]] = hashlib.sha256((folder / files[i]).read_bytes()).hexdigest()
        i += 1
    return rows, {"run": folder.name, "replies_from": manifest["replies_from"], "people": len(initial),
                  "groups": len(groups), "locked": locked, "calls": calls, "failed_calls": failed_calls,
                  "answers": answers,
                  "separate_ai_audits": len(audits), "source_sha256": digests, "errors": errors}


def build(root=ROOT):
    folders = run_folders(root)
    rows = []
    runs = []
    i = 0
    while i < len(folders):
        if not (folders[i] / "run_manifest.json").exists():
            i += 1
            continue
        found, checked = inspect_run(folders[i])
        j = 0
        while j < len(found):
            found[j]["source"] = str(folders[i].relative_to(root) / "run_dump.txt")
            j += 1
        rows.extend(found)
        runs.append(checked)
        i += 1
    notes_path = root / "review_notes.csv"
    saved = {}
    if notes_path.exists():
        with notes_path.open(encoding="utf-8-sig", newline="") as stream:
            previous = list(csv.DictReader(stream))
        i = 0
        while i < len(previous):
            saved[previous[i]["match_id"]] = previous[i]
            i += 1
    locked = 0
    reviewed = 0
    completed = 0
    combinations = {}
    i = 0
    while i < len(rows):
        row = rows[i]
        if row["status"] == "locked":
            locked += 1
            combination = (row["activity"], tuple(sorted(row["members"].split("; "))))
            if combination in combinations:
                row["same_activity_and_members_seen_in"] = combinations[combination]
            else:
                combinations[combination] = row["match_id"]
        if row["ai_verdict"]:
            reviewed += 1
        if row["match_id"] in saved:
            row["human_verdict"] = saved[row["match_id"]].get("human_verdict", "")
            row["human_notes"] = saved[row["match_id"]].get("human_notes", "")
        if row["human_verdict"].strip():
            completed += 1
        i += 1
    with notes_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    totals = {"target_groups": TARGET, "completed_groups": locked, "additional_groups_needed": max(0, TARGET - locked),
              "separate_ai_reviews": reviewed, "human_verdicts_in_csv": completed,
              "distinct_activity_memberships": len(combinations), "runs": runs}
    totals["evidence_errors"] = 0
    totals["logged_simulation_calls"] = 0
    totals["failed_simulation_calls"] = 0
    totals["agent_replies"] = 0
    i = 0
    while i < len(runs):
        totals["evidence_errors"] += len(runs[i]["errors"])
        totals["logged_simulation_calls"] += runs[i]["calls"]
        totals["failed_simulation_calls"] += runs[i]["failed_calls"]
        totals["agent_replies"] += runs[i]["answers"]
        i += 1
    totals["incomplete_run_folders"] = []
    all_folders = run_folders(root)
    i = 0
    while i < len(all_folders):
        folder = all_folders[i]
        if folder.is_dir() and not (folder / "run_manifest.json").exists():
            totals["incomplete_run_folders"].append(folder.name)
        i += 1
    metadata_path(root, "requirements_check.json").write_text(json.dumps(totals, indent=2) + "\n", encoding="utf-8")
    checks = ["# Does this meet the team's request?", "",
              "A match here means one completed activity group. People and invitations are counted separately.", "",
              "| Requirement | Verified status |", "|---|---|",
              "| Run the actual matchmaker locally | Saved live API runs, with model names and per-run manifests. |",
              "| Provide 200 matches for review | " + str(locked) + " completed groups; "
              + str(totals["additional_groups_needed"]) + " still needed. |",
              "| Explain every decision | Each group has the hub's verbatim reason and each agent's verbatim answers. |",
              "| Log personalities before and after | Exact initial prompts and final profiles are saved per run; comparisons are checked. |",
              "| Save every conversation | Per-run run_dump.txt and full_simulation.jsonl keep hub messages, replies and call inputs/outputs. |",
              "| Start manual notes | review_notes.csv has one row per group with human_verdict and human_notes columns. |",
              "| Independent AI assessment | " + str(reviewed) + " groups have saved separate AI audits. Others remain open for review. |",
              "| Human review completed | " + str(completed) + " verdicts in this CSV; shared or other local files were not checked. |",
              "", "## Files to use", "",
              "- Clawnly_Match_Review.html: the finished reader with embedded profiles and conversations.",
              "- ALL_RUNS_DUMP.txt: the complete plain-text record for all runs.",
              "- review_notes.csv: open in Excel and add a verdict and notes per row.",
              "- runs/run_*/run_dump.txt: the full supporting profiles and conversations, suitable for an AI chat.",
              "- metadata/requirements_check.json: evidence checks and SHA-256 fingerprints of source files.", "",
              "The earlier evaluation/results set contains code-proposed groups and is a separate experiment.", "",
              "## Read the results correctly", "",
              "Evidence consistency errors: " + str(totals["evidence_errors"]) + ". Recorded failed simulation calls: "
              + str(totals["failed_simulation_calls"]) + ". Incomplete run folders: "
              + str(len(totals["incomplete_run_folders"])) + ". Failures do not count as completed groups.", "",
              "Repeated dates are independent runs on the same synthetic town. They are separate model decisions,",
              "not 200 different people or proof of real-life friendship compatibility. Older runs and later runs",
              "may use different prompts; each original manifest and record is preserved.", "",
              "Distinct activity/member combinations so far: " + str(len(combinations))
              + ". The CSV flags repeated combinations for comparison.", "",
              "Failed runs and incomplete folders remain visible in metadata/requirements_check.json. The simulator stores",
              "prompts and replies returned by the API; available thinking summaries are not the model's full hidden reasoning.", "",
              "## Rebuild for free", "", "```bash", ".venv/bin/python src/simulation_review.py", "```", "",
              "This reads saved evidence without API calls and preserves CSV notes by match ID.", ""]
    report = root / "REQUIREMENTS_STATUS.md"
    if (root / "reports").is_dir():
        report = root / "reports" / "REQUIREMENTS_STATUS.md"
    report.write_text("\n".join(checks), encoding="utf-8")
    return totals


def package(root=ROOT):
    names = ["README.md", "Clawnly_Match_Review.html", "ALL_RUNS_DUMP.txt", "review_notes.csv"]
    files = []
    i = 0
    while i < len(names):
        if (root / names[i]).exists():
            files.append(root / names[i])
        i += 1
    folders = [root / "runs", root / "reports", root / "metadata"]
    i = 0
    while i < len(folders):
        if folders[i].is_dir():
            files.extend(sorted(folders[i].rglob("*")))
        i += 1
    destination = root / "review_package.zip"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        i = 0
        while i < len(files):
            if files[i].is_file() and not files[i].name.startswith("simulation.db"):
                archive.write(files[i], str(files[i].relative_to(root)))
            i += 1
    return destination


def write_dump(root=ROOT):
    import run_dump
    folders = run_folders(root)
    ready = []
    interrupted = []
    i = 0
    while i < len(folders):
        if (folders[i] / "run_manifest.json").exists():
            ready.append(str(folders[i]))
        else:
            interrupted.append(folders[i])
        i += 1
    path = root / "ALL_RUNS_DUMP.txt"
    run_dump.write_all(str(path), ready)
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n\nINTERRUPTED ATTEMPTS NOT COUNTED AS MATCHES\n")
        i = 0
        while i < len(interrupted):
            stream.write("\n" + interrupted[i].name + "\n")
            note = interrupted[i] / "INTERRUPTED.txt"
            if note.exists():
                stream.write(note.read_text(encoding="utf-8"))
            i += 1
    return path


if __name__ == "__main__":
    result = build()
    print(str(result["completed_groups"]) + " completed groups; " + str(result["additional_groups_needed"])
          + " more needed; " + str(result["separate_ai_reviews"]) + " separate AI reviews.")
    write_dump()
    import readable_review
    print("Readable review: " + str(readable_review.build()))
    if sys.argv[1:] == ["--package"]:
        print("Review package: " + str(package()))
