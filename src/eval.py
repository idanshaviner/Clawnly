"""Evaluation harness: prove the matcher is legit, not just demo it (SPEC 13).

Runs find_matches across many pools -- including deliberately impossible ones --
compares each result to a random baseline, checks hard constraints in code, and
reports the automatable pass bars (zero violations, 100% correct refusal). The
beat-random and grounding bars need a human rater, so this also emits a
label-blinded review set. Run deliberately: one match call per pool.
"""

import asyncio
import random

import config
from master_claw import MasterClaw
from users import USERS


def _by_id():
    lookup = {}
    i = 0
    while i < len(USERS):
        lookup[USERS[i]["id"]] = USERS[i]
        i += 1
    return lookup


def synthetic_interviews(users):
    # build interview records from profiles, no API call -- the harness focuses
    # on matching, so interview prose is derived rather than generated.
    interviews = {}
    i = 0
    while i < len(users):
        u = users[i]
        q1 = "Into {}; wants to meet people around that.".format(", ".join(u["hobbies"]))
        q2 = "Free {}; {} energy in groups.".format(", ".join(u["availability"]), u["personality"])
        interviews[u["id"]] = {"profile": u, "q1": q1, "q2": q2}
        i += 1
    return interviews


def random_group(users, size, rng):
    # a baseline group chosen at random, for head-to-head comparison.
    ids = []
    i = 0
    while i < len(users):
        ids.append(users[i]["id"])
        i += 1
    if size > len(ids):
        size = len(ids)
    if size < 1:
        size = 1
    return rng.sample(ids, size)


def _copy_with(user, availability, size):
    # shallow copy of a profile with overridden availability + size (new lists).
    clone = dict(user)
    clone["availability"] = list(availability)
    clone["preferred_group_size"] = size
    return clone


def _impossible_pool(pool_id, size_pref):
    # four people, four distinct single windows -> no group can share a time.
    by_id = _by_id()
    base_ids = ["u01", "u04", "u07", "u10"]
    windows = ["weekday_daytime", "weekday_evening", "weekend_daytime", "weekend_evening"]
    users = []
    i = 0
    while i < len(base_ids):
        users.append(_copy_with(by_id[base_ids[i]], [windows[i]], size_pref))
        i += 1
    return {"id": pool_id, "kind": "impossible", "users": users}


def make_pools(seed=7):
    # at least 10 pools: the full set, random subsets, and impossible cases.
    rng = random.Random(seed)
    pools = []

    pools.append({"id": "pool_full", "kind": "normal", "users": list(USERS)})

    # several random subsets of varying size.
    n = 0
    while n < 7:
        size = rng.randint(8, 11)
        subset = rng.sample(USERS, size)
        pools.append({"id": "pool_subset_{}".format(n + 1), "kind": "normal", "users": subset})
        n += 1

    # two deliberately impossible pools (the refusal test).
    pools.append(_impossible_pool("pool_impossible_a", [3, 5]))
    pools.append(_impossible_pool("pool_impossible_b", [2, 3]))

    return pools


async def evaluate(pools, client, seed=13):
    rng = random.Random(seed)
    records = []
    i = 0
    while i < len(pools):
        pool = pools[i]
        users = pool["users"]
        master = MasterClaw(users, client=client)
        interviews = synthetic_interviews(users)
        matches = await master.find_matches(interviews)
        group = matches["group"]

        if len(group) > 0:
            violations = master._validate_group(group)
        else:
            violations = []

        baseline_size = len(group)
        if baseline_size == 0:
            baseline_size = 3
        baseline = random_group(users, baseline_size, rng)
        baseline_violations = master._validate_group(baseline)

        refused = len(group) == 0
        records.append({
            "pool_id": pool["id"],
            "kind": pool["kind"],
            "matched": group,
            "reason": matches["reason"],
            "scores": matches["scores"],
            "violations": violations,
            "baseline": baseline,
            "baseline_violations": baseline_violations,
            "refused": refused,
        })
        i += 1
    return records


def build_blind_review(records, seed=99):
    # present matcher vs random as A/B in random order, with a hidden key,
    # so a human can rate "would these click?" without bias.
    rng = random.Random(seed)
    items = []
    i = 0
    while i < len(records):
        r = records[i]
        if len(r["matched"]) > 0:
            if rng.random() < 0.5:
                option_a = r["matched"]
                option_b = r["baseline"]
                key = "A=matcher, B=random"
            else:
                option_a = r["baseline"]
                option_b = r["matched"]
                key = "A=random, B=matcher"
            items.append({
                "pool_id": r["pool_id"],
                "option_A": option_a,
                "option_B": option_b,
                "answer_key": key,
            })
        i += 1
    return items


def aggregate(records):
    total = len(records)

    impossible = []
    i = 0
    while i < len(records):
        if records[i]["kind"] == "impossible":
            impossible.append(records[i])
        i += 1

    matcher_violations = 0
    baseline_violations = 0
    i = 0
    while i < len(records):
        matcher_violations += len(records[i]["violations"])
        baseline_violations += len(records[i]["baseline_violations"])
        i += 1

    correct_refusals = 0
    i = 0
    while i < len(impossible):
        if impossible[i]["refused"]:
            correct_refusals += 1
        i += 1

    refusal_rate = None
    full_refusal = None
    if len(impossible) > 0:
        refusal_rate = correct_refusals / len(impossible)
        full_refusal = refusal_rate == 1.0

    return {
        "pools": total,
        "impossible_pools": len(impossible),
        "matcher_hard_violations": matcher_violations,
        "baseline_hard_violations": baseline_violations,
        "correct_refusals": correct_refusals,
        "refusal_rate": refusal_rate,
        # automatable pass bars (PRD 6a):
        "pass_zero_violations": matcher_violations == 0,
        "pass_full_refusal": full_refusal,
        # these bars need a human rater on the blind review set:
        "pass_beats_random": "pending human rating",
        "pass_grounding": "pending human rating",
    }


async def main(client=None):
    if client is None:
        client = config.get_client()
    pools = make_pools()
    records = await evaluate(pools, client)
    report = aggregate(records)

    print("=" * 60)
    print("EVALUATION REPORT")
    print("=" * 60)
    keys = list(report.keys())
    i = 0
    while i < len(keys):
        print("  {:<26}: {}".format(keys[i], report[keys[i]]))
        i += 1

    print("\nBlind review set (rate each A/B for 'would these click?'):")
    review = build_blind_review(records)
    i = 0
    while i < len(review):
        item = review[i]
        print("  {} | A={} | B={}".format(item["pool_id"], item["option_A"], item["option_B"]))
        i += 1

    return report


if __name__ == "__main__":
    asyncio.run(main())
