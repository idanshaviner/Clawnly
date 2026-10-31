"""Build one self-contained review file from saved evidence, without API calls."""

import csv
import hashlib
import json
from pathlib import Path
import re

import simulation_review


ROOT = Path(__file__).resolve().parent.parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def collect(root):
    data = {"matches": [], "runs": {}, "notes": {}}
    folders = simulation_review.run_folders(root)
    i = 0
    while i < len(folders):
        folder = folders[i]
        i += 1
        if not (folder / "run_manifest.json").exists():
            continue
        groups = read(folder / "groups_generated.json")
        if not groups:
            continue
        people = {}
        initial = read(folder / "agents_initial.json")
        final = read(folder / "agents_final.json")
        after = {}
        j = 0
        while j < len(final):
            after[final[j]["id"]] = final[j]
            j += 1
        j = 0
        while j < len(initial):
            people[initial[j]["id"]] = initial[j]
            j += 1
        events = {}
        calls = {}
        lines = (folder / "full_simulation.jsonl").read_text(encoding="utf-8").splitlines()
        j = 0
        while j < len(lines):
            if lines[j].strip():
                event = json.loads(lines[j])
                events[event["seq"]] = event
                if event["type"] == "model_call":
                    calls[str(event["seq"])] = event
            j += 1
        audits = {}
        if (folder / "audit_ai.json").exists():
            saved = read(folder / "audit_ai.json")["groups"]
            j = 0
            while j < len(saved):
                audits[saved[j]["group"]] = saved[j]
                j += 1
        findings = []
        if (folder / "audit_mechanical.json").exists():
            findings = read(folder / "audit_mechanical.json")["findings"]
        run = {"manifest": read(folder / "run_manifest.json"), "people": {}, "after": {}, "calls": calls}
        data["runs"][folder.name] = run
        j = 0
        while j < len(groups):
            group = groups[j]
            j += 1
            entry = {"number": len(data["matches"]) + 1, "id": folder.name + "/" + group["group"],
                     "run": folder.name, "group": group, "conversation": [], "findings": [],
                     "audit": audits.get(group["group"]), "raw_calls": [], "repeat_of": None}
            refs = set()
            evidence = list(group["evidence"].values())
            k = 0
            while k < len(evidence):
                value = evidence[k]
                if isinstance(value, int) and str(value) in calls:
                    refs.add(value)
                k += 1
            k = 0
            while k < len(group["members"]):
                member = group["members"][k]
                pid = member["id"]
                run["people"][pid] = people[pid]
                run["after"][pid] = after[pid]
                a = 0
                while a < len(member["answers"]):
                    answer = member["answers"][a]
                    entry["conversation"].append(events[answer["ask_seq"]])
                    entry["conversation"].append(events[answer["reply_seq"]])
                    refs.add(answer["call_seq"])
                    a += 1
                k += 1
            entry["conversation"].sort(key=lambda event: event["seq"])
            entry["raw_calls"] = sorted(refs)
            k = 0
            while k < len(findings):
                if not findings[k].get("groups") or group["group"] in findings[k]["groups"]:
                    entry["findings"].append(findings[k])
                k += 1
            data["matches"].append(entry)
        
    combinations = {}
    i = 0
    while i < len(data["matches"]):
        match = data["matches"][i]
        group = match["group"]
        key = (group["activity"], tuple(sorted(group["final_members"])))
        if group["status"] == "locked":
            if key in combinations:
                match["repeat_of"] = combinations[key]
            else:
                combinations[key] = match["number"]
        i += 1
    data["distinct"] = len(combinations)
    data["version"] = hashlib.sha256(json.dumps(list(combinations.keys())).encode()).hexdigest()[:16]
    notes = root / "review_notes.csv"
    if notes.exists():
        with notes.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        i = 0
        while i < len(rows):
            row = rows[i]
            if row.get("human_verdict") or row.get("human_notes"):
                data["notes"][row["match_id"]] = {"verdict": row.get("human_verdict", ""),
                                                  "text": row.get("human_notes", ""), "updated": 0}
            i += 1
    return data


def script_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def build(root=ROOT / "simulation_results", out=None):
    if out is None:
        out = root / "Clawnly_Match_Review.html"
    data = collect(root)
    state = {"notes": data.pop("notes"), "cursor": 1}
    if out.exists():
        found = re.search(r'<script id="review-state" type="application/json">(.*?)</script>',
                          out.read_text(encoding="utf-8"), re.S)
        if found:
            previous = json.loads(found[1])
            state["notes"].update(previous.get("notes", {}))
            state["cursor"] = previous.get("cursor", 1)
    template = (ROOT / "src" / "web" / "match-review.html").read_text(encoding="utf-8")
    page = template.replace("__REVIEW_DATA__", script_json(data)).replace("__REVIEW_STATE__", script_json(state))
    out.write_text(page, encoding="utf-8")
    return out


if __name__ == "__main__":
    print(build())
