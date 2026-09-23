"""Nightly rounds: once a neighborhood's first round has run, the hub runs
again every night on its own, so people who joined late or were released by
a "no" get new conversations without anyone pressing a button.

A small loop inside the app (started by app.py) wakes every few minutes. In
the configured hour (config.NIGHTLY_ROUND_HOUR in config.NIGHTLY_TIMEZONE) it
runs one round per neighborhood, at most once a night (db.claim_nightly_round).
A round that would have nothing to do is skipped before any paid call:
fewer than 2 people free, or every free pair has already talked (the hub
never repeats a pair). Every run, skip and failure goes to the neighborhood's
activity log.
"""

import asyncio
import datetime
import zoneinfo

import batch
import config
import db
import orchestrator


CHECK_EVERY_SECONDS = 300

# the loop's task must stay referenced, or Python may garbage-collect it
_TASK = None


def nightly_hour():
    raw = config.resolve_env("CLAWNLY_NIGHTLY_HOUR")
    if raw is None:
        return config.NIGHTLY_ROUND_HOUR
    try:
        hour = int(raw)
    except ValueError:
        return config.NIGHTLY_ROUND_HOUR
    if hour < 0 or hour > 23:
        return config.NIGHTLY_ROUND_HOUR
    return hour


def timezone():
    name = config.resolve_env("CLAWNLY_TIMEZONE")
    if name is None:
        name = config.NIGHTLY_TIMEZONE
    try:
        return zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return zoneinfo.ZoneInfo(config.NIGHTLY_TIMEZONE)


def local_now():
    return datetime.datetime.now(timezone())


def is_due(now):
    # a one-hour window, not "any time after": a deploy at noon must not set off rounds
    return now.hour == nightly_hour()


def untried_pairs(people):
    # how many pairs among these people have never finished a conversation
    done = set()
    past = db.list_agent_conversations()
    i = 0
    while i < len(past):
        if past[i]["verdict"] is not None:
            done.add(orchestrator.pair_key(past[i]["a"], past[i]["b"]))
        i += 1
    count = 0
    i = 0
    while i < len(people):
        j = i + 1
        while j < len(people):
            if orchestrator.pair_key(people[i]["id"], people[j]["id"]) not in done:
                count += 1
            j += 1
        i += 1
    return count


async def run_nightly_round(neighborhood, night, client=None):
    # returns the run id, or None when tonight's round was already taken or skipped
    neighborhood_id = neighborhood["id"]
    if not db.claim_nightly_round(neighborhood_id, night):
        return None
    people = batch.people_for(neighborhood_id)
    if len(people) < 2:
        db.log_event(None, "system", "system", "Nightly round skipped: fewer than 2 neighbors are free "
                     "(everyone else is holding an invitation).", None, neighborhood_id)
        return None
    fresh = untried_pairs(people)
    if fresh == 0:
        db.log_event(None, "system", "system", "Nightly round skipped: every pair of the " + str(len(people))
                     + " free neighbors has already talked.", None, neighborhood_id)
        return None
    db.log_event(None, "system", "system", "Nightly round: " + str(len(people)) + " neighbors are free, "
                 + str(fresh) + " pair(s) haven't talked yet.", None, neighborhood_id)
    try:
        if client is None:
            client = config.get_client()
        return await batch.run_neighborhood_round(neighborhood_id, people, client)
    except Exception as error:
        db.log_event(None, "system", "system", "The nightly round failed: " + str(error)
                     + ". It runs again tomorrow night, or run it now from the admin dashboard.",
                     None, neighborhood_id)
        print("[nightly] neighborhood {} round failed: {}".format(neighborhood_id, error))
        return None


async def run_due_rounds(now, client=None):
    # every neighborhood past its first round, when `now` is inside the nightly hour
    if not is_due(now):
        return []
    night = now.date().isoformat()
    neighborhoods = db.list_neighborhoods()
    run_ids = []
    i = 0
    while i < len(neighborhoods):
        if neighborhoods[i]["batch_triggered_at"] is not None:
            run_id = await run_nightly_round(neighborhoods[i], night, client)
            if run_id is not None:
                run_ids.append(run_id)
        i += 1
    return run_ids


async def _loop():
    while True:
        try:
            await run_due_rounds(local_now())
        except Exception as error:
            # one bad night must not stop every night after it
            print("[nightly] check failed: {}".format(error))
        await asyncio.sleep(CHECK_EVERY_SECONDS)


def start():
    global _TASK
    if _TASK is None:
        _TASK = asyncio.get_running_loop().create_task(_loop())
    return _TASK
