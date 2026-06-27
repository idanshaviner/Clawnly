"""Tests for the AI persona generator (schema validation + retry)."""

from conftest import FakeClient, json_body, run
import persona_gen
from users import USERS


def good_users():
    return {"users": [
        {"name": "A", "age": 27, "gender": "female", "hobbies": ["reading", "yoga"],
         "personality": "introverted", "occupation": "student",
         "availability": ["weekday_evening"], "location": "Shaw",
         "bio": "I like quiet evenings with a book.", "preferred_group_size": [2, 3]},
        {"name": "B", "age": 31, "gender": "male", "hobbies": ["cycling", "trivia nights"],
         "personality": "extroverted", "occupation": "freelancer",
         "availability": ["weekend_evening"], "location": "Adams Morgan",
         "bio": "Always up for a ride and a pub quiz.", "preferred_group_size": [5, 8]},
        {"name": "C", "age": 29, "gender": "non-binary", "hobbies": ["painting", "running"],
         "personality": "mixed", "occupation": "working professional",
         "availability": ["weekday_evening", "weekend_daytime"], "location": "Petworth",
         "bio": "Paint by night, run by morning.", "preferred_group_size": "no preference"},
    ]}


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


# ----- generation (mocked) --------------------------------------------------

def test_generate_users_returns_valid_cast():
    fake = FakeClient(generation_queue=[json_body(good_users())])
    users = run(persona_gen.generate_users(count=3, client=fake))
    assert len(users) == 3
    assert persona_gen.validate_users(users) == []
    assert [u["id"] for u in users] == ["u01", "u02", "u03"]


def test_generate_users_retries_on_invalid_schema():
    invalid = {"users": [dict(good_users()["users"][0], age=40)]}   # bad age
    fake = FakeClient(generation_queue=[json_body(invalid), json_body(good_users())])
    users = run(persona_gen.generate_users(count=3, client=fake))
    assert persona_gen.validate_users(users) == []
    gen_calls = [k for k in fake.kinds() if k == "generation"]
    assert len(gen_calls) == 2          # retried once after the bad attempt
