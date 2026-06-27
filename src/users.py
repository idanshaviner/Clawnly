"""Simulated user profiles for the Clawly matchmaker PoC.

Defines the 12 seed users plus the two closed vocabularies the rest of the
system validates against (hobby categories and availability windows). Adding
more users later is just adding more dicts -- nothing else has to change.
See SPEC.md section 4 for the data model.
"""

import json


# closed set of time windows a user can actually be free in.
# two users are time-compatible only if their availability lists overlap.
AVAILABILITY_WINDOWS = [
    "weekday_daytime",
    "weekday_evening",
    "weekend_daytime",
    "weekend_evening",
]


# category -> example hobbies. every hobby used below maps to exactly one
# category, so "spans all six categories" is programmatically checkable.
HOBBY_CATEGORIES = {
    "outdoor": ["hiking", "cycling", "kayaking", "camping", "rock climbing"],
    "creative": ["pottery", "painting", "photography", "playing guitar", "creative writing"],
    "social": ["trivia nights", "karaoke", "board games", "dinner parties", "volunteering"],
    "professional": ["startup networking", "investing club", "public speaking", "side projects"],
    "fitness": ["yoga", "running", "weightlifting", "pilates", "bouldering"],
    "intellectual": ["reading", "documentaries", "chess", "book club", "learning languages"],
}


# the 12 seed users. diverse across gender, age (24-35), personality,
# occupation, availability, group-size preference, and hobby category.
USERS = [
    {
        "id": "u01",
        "name": "Maya",
        "age": 27,
        "gender": "female",
        "hobbies": ["reading", "pottery", "yoga"],
        "personality": "introverted",
        "occupation": "working professional",
        "availability": ["weekday_evening", "weekend_daytime"],
        "location": "Petworth",
        "bio": "I'm a data analyst who recharges with a good book and a quiet pottery class. "
               "I love deep one-on-one conversations way more than big loud rooms. "
               "Still figuring out my way around DC after moving here last year.",
        "preferred_group_size": [2, 3],
    },
    {
        "id": "u02",
        "name": "Daniel",
        "age": 31,
        "gender": "male",
        "hobbies": ["photography", "trivia nights", "cycling"],
        "personality": "extroverted",
        "occupation": "freelancer",
        "availability": ["weekday_evening", "weekend_evening"],
        "location": "Adams Morgan",
        "bio": "Freelance photographer, which means my schedule is chaos but my evenings are usually free. "
               "I'm the guy who organizes the trivia team and then talks to everyone at the bar. "
               "Always down for a long bike ride to shake off a deadline.",
        "preferred_group_size": [5, 8],
    },
    {
        "id": "u03",
        "name": "Priya",
        "age": 24,
        "gender": "female",
        "hobbies": ["hiking", "documentaries", "volunteering"],
        "personality": "mixed",
        "occupation": "student",
        "availability": ["weekday_daytime", "weekend_daytime"],
        "location": "Columbia Heights",
        "bio": "Public health grad student, so my weeks are packed but I keep my days flexible. "
               "I can be the loudest person on a hike or the quietest one in a documentary night. "
               "I volunteer most weekends and would love to meet people who care about that stuff too.",
        "preferred_group_size": "no preference",
    },
    {
        "id": "u04",
        "name": "Marcus",
        "age": 34,
        "gender": "male",
        "hobbies": ["chess", "weightlifting", "creative writing"],
        "personality": "introverted",
        "occupation": "working professional",
        "availability": ["weekday_evening"],
        "location": "Navy Yard",
        "bio": "Software engineer by day, working on a novel that may never finish by night. "
               "I'm pretty reserved until you get me on a topic I love, then good luck stopping me. "
               "Weekday evenings after the gym are my window for anything social.",
        "preferred_group_size": [2, 3],
    },
    {
        "id": "u05",
        "name": "Sofia",
        "age": 29,
        "gender": "female",
        "hobbies": ["karaoke", "running", "painting"],
        "personality": "extroverted",
        "occupation": "working professional",
        "availability": ["weekday_evening", "weekend_daytime", "weekend_evening"],
        "location": "Logan Circle",
        "bio": "Marketing manager with way too much social energy for one calendar. "
               "I'll drag you to karaoke and then to a morning run to regret it together. "
               "Painting is my one quiet hobby and honestly I'm not very good at it.",
        "preferred_group_size": [5, 8],
    },
    {
        "id": "u06",
        "name": "James",
        "age": 26,
        "gender": "male",
        "hobbies": ["board games", "playing guitar", "cycling"],
        "personality": "mixed",
        "occupation": "freelancer",
        "availability": ["weekday_daytime", "weekend_evening"],
        "location": "Shaw",
        "bio": "Freelance graphic designer who treats board game nights as a competitive sport. "
               "I play guitar badly and bike everywhere because parking in Shaw is a nightmare. "
               "I like small groups where I can actually remember everyone's name.",
        "preferred_group_size": [3, 5],
    },
    {
        "id": "u07",
        "name": "Aisha",
        "age": 32,
        "gender": "female",
        "hobbies": ["book club", "pilates", "kayaking"],
        "personality": "introverted",
        "occupation": "working professional",
        "availability": ["weekend_daytime"],
        "location": "Capitol Hill",
        "bio": "Lawyer with a brutal week, so weekends are sacred and mostly outdoors. "
               "I run a small book club and would happily talk about the same novel for hours. "
               "Kayaking on the Potomac is my reset button.",
        "preferred_group_size": [2, 4],
    },
    {
        "id": "u08",
        "name": "Ethan",
        "age": 35,
        "gender": "male",
        "hobbies": ["startup networking", "trivia nights", "weightlifting"],
        "personality": "extroverted",
        "occupation": "working professional",
        "availability": ["weekday_evening", "weekend_evening"],
        "location": "Dupont Circle",
        "bio": "Sales director who genuinely loves a crowded room full of strangers. "
               "I go to every startup mixer in the city and lift heavy when I need to think. "
               "Honestly the bigger the group the happier I am.",
        "preferred_group_size": [6, 8],
    },
    {
        "id": "u09",
        "name": "Nina",
        "age": 28,
        "gender": "non-binary",
        "hobbies": ["creative writing", "learning languages", "yoga"],
        "personality": "mixed",
        "occupation": "freelancer",
        "availability": ["weekday_daytime", "weekend_daytime"],
        "location": "U Street",
        "bio": "Freelance writer currently butchering my third language with great enthusiasm. "
               "I love a slow morning, a yoga class, and a tiny gathering of interesting people. "
               "Big parties drain me but a thoughtful coffee chat makes my week.",
        "preferred_group_size": [2, 3],
    },
    {
        "id": "u10",
        "name": "Omar",
        "age": 30,
        "gender": "male",
        "hobbies": ["investing club", "chess", "running"],
        "personality": "introverted",
        "occupation": "student",
        "availability": ["weekday_evening", "weekend_daytime"],
        "location": "Georgetown",
        "bio": "MBA student who reads markets for fun and runs to clear my head. "
               "I'm quiet at first but I light up over a chess board or a good debate. "
               "I prefer a handful of sharp people over a packed bar any day.",
        "preferred_group_size": [3, 5],
    },
    {
        "id": "u11",
        "name": "Grace",
        "age": 25,
        "gender": "female",
        "hobbies": ["volunteering", "camping", "painting"],
        "personality": "extroverted",
        "occupation": "working professional",
        "availability": ["weekday_daytime", "weekend_evening"],
        "location": "Brookland",
        "bio": "ER nurse, so my days off land mid-week and I make the most of them. "
               "I love volunteering, weekend camping trips, and painting when it rains. "
               "I'll talk to anyone and I'm happy in a group of any size.",
        "preferred_group_size": "no preference",
    },
    {
        "id": "u12",
        "name": "Leo",
        "age": 33,
        "gender": "male",
        "hobbies": ["playing guitar", "public speaking", "hiking"],
        "personality": "mixed",
        "occupation": "freelancer",
        "availability": ["weekday_daytime", "weekday_evening", "weekend_evening"],
        "location": "H Street",
        "bio": "Working musician who teaches public speaking workshops on the side. "
               "I'm comfortable on a stage but I also disappear into the woods for a long hike alone. "
               "Looking for a medium-sized crew that's up for both shows and trailheads.",
        "preferred_group_size": [4, 6],
    },
]


# print the users as formatted json when run directly.
if __name__ == "__main__":
    print(json.dumps(USERS, indent=2))
