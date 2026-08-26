"""Tests for the AI persona generator (schema validation + retry)."""

from conftest import FakeClient, json_body, run
import persona_gen
from users import USERS


def person(name="A", **overrides):
    # one valid single-person object (the id is assigned by _reid, not the model).
    base = {"name": name, "age": 27, "gender": "female", "hobbies": ["reading", "yoga"],
            "personality": "introverted", "occupation": "student",
            "availability": ["weekday_evening"], "location": "Shaw",
            "bio": "I like quiet evenings with a book.", "preferred_group_size": [2, 3]}
    base.update(overrides)
    return base


def good_users():
    return {"users": [person("A"), person("B", personality="extroverted"),
                      person("C", personality="mixed")]}


# ----- validation -----------------------------------------------------------

def test_validate_passes_on_the_real_seed_users():
    assert persona_gen.validate_users(USERS) == []


def test_validate_catches_bad_age_hobby_and_size():
    bad = [{
        "id": "u01", "name": "X", "age": 40, "gender": "male",
        "hobbies": ["underwater basket weaving"], "personality": "introverted",
        "occupation": "student", "availability": ["weekday_evening"],
        "location": "Shaw", "bio": "hi", "preferred_group_size": [1, 9],
    }]
    problems = persona_gen.validate_users(bad)
    assert any("age" in p for p in problems)
    assert any("unknown hobby" in p for p in problems)
    assert any("outside 2-8" in p for p in problems)


def test_reid_assigns_sequential_unique_ids():
    out = persona_gen._reid(good_users()["users"])
    assert [u["id"] for u in out] == ["u01", "u02", "u03"]


# ----- slot leans: full coverage, genuinely randomized -----------------------

def test_slot_specs_cover_every_personality_and_occupation():
    # a 12-slot cast must still span all three personalities/occupations and
    # all six hobby-category focuses, regardless of shuffle order.
    specs = persona_gen._slot_specs(12)
    personalities = set(s["personality"] for s in specs)
    occupations = set(s["occupation"] for s in specs)
    focuses = set(s["focus"] for s in specs)
    assert personalities == {"introverted", "extroverted", "mixed"}
    assert occupations == {"student", "working professional", "freelancer"}
    assert len(focuses) == 6


def test_slot_specs_lean_order_is_randomized_across_calls():
    # which slot gets which lean should differ run to run, not follow the
    # same fixed index pattern every time (that was the old, non-random behavior).
    seen = set()
    i = 0
    while i < 20:
        specs = persona_gen._slot_specs(12)
        seen.add(tuple(s["personality"] for s in specs))
        i += 1
    assert len(seen) > 1


def test_cycled_shuffle_covers_all_options_and_matches_requested_count():
    out = persona_gen._cycled_shuffle(["a", "b", "c"], 7)
    assert len(out) == 7
    assert set(out) == {"a", "b", "c"}


# ----- generation (mocked): one concurrent call per person ------------------

def test_generate_users_invents_each_person_in_its_own_call():
    # 3 people -> 3 separate generation calls, fired concurrently.
    fake = FakeClient(generation_queue=[json_body(person("A")), json_body(person("B")),
                                        json_body(person("C"))])
    users = run(persona_gen.generate_users(count=3, client=fake))
    assert len(users) == 3
    assert persona_gen.validate_users(users) == []
    assert [u["id"] for u in users] == ["u01", "u02", "u03"]
    assert len([k for k in fake.kinds() if k == "generation"]) == 3   # one per person


def test_generate_users_retries_only_the_failing_slot():
    # first person comes back with a bad age, then valid; the other two are fine.
    bad = json_body(person("A", age=40))
    fake = FakeClient(generation_queue=[bad, json_body(person("A")),
                                        json_body(person("B")), json_body(person("C"))])
    users = run(persona_gen.generate_users(count=3, client=fake))
    assert persona_gen.validate_users(users) == []
    assert len(users) == 3
    gen_calls = [k for k in fake.kinds() if k == "generation"]
    assert len(gen_calls) == 4          # 3 people + 1 retry on the bad slot


def test_generate_users_accepts_a_wrapped_person_object():
    # tolerant of {"user": {...}} and {"users": [{...}]} wrappers too.
    fake = FakeClient(generation_queue=[json_body({"user": person("A")}),
                                        json_body({"users": [person("B")]}),
                                        json_body(person("C"))])
    users = run(persona_gen.generate_users(count=3, client=fake))
    assert [u["name"] for u in users] == ["A", "B", "C"]
