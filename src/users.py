"""Simulated user profiles for the Clawnly matchmaker PoC.

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
# each category is deliberately large (~20 items) and kept broad/varied so
# generated + edited profiles draw from a wide, effectively-random pool
# instead of colliding on the same handful of hobbies.
HOBBY_CATEGORIES = {
    "outdoor": [
        "hiking", "cycling", "kayaking", "camping", "rock climbing",
        "trail running", "birdwatching", "fishing", "skiing", "snowboarding",
        "gardening", "paddleboarding", "sailing", "mountain biking", "backpacking",
        "geocaching", "foraging", "surfing", "canoeing", "beach volleyball",
        "disc golf", "stargazing", "urban exploring",
    ],
    "creative": [
        "pottery", "painting", "photography", "playing guitar", "creative writing",
        "drawing", "sculpting", "calligraphy", "woodworking", "knitting",
        "sewing", "filmmaking", "singing", "DJing", "playing piano",
        "playing violin", "songwriting", "screenwriting", "graphic design",
        "jewelry making", "ceramics", "collage art", "animation",
    ],
    "social": [
        "trivia nights", "karaoke", "board games", "dinner parties", "volunteering",
        "game nights", "wine tasting", "cooking classes", "potlucks", "salsa dancing",
        "swing dancing", "improv comedy", "book swaps", "language exchange meetups",
        "community theater", "storytelling nights", "murder mystery nights",
        "tabletop RPGs", "food tours", "cultural festivals", "house shows",
    ],
    "professional": [
        "startup networking", "investing club", "public speaking", "side projects",
        "mentoring", "angel investing", "hackathons", "podcasting", "consulting gigs",
        "personal branding", "career coaching", "industry conferences",
        "entrepreneurship meetups", "negotiation workshops", "portfolio building",
        "freelance pitching", "toastmasters", "nonprofit board work",
    ],
    "fitness": [
        "yoga", "running", "weightlifting", "pilates", "bouldering",
        "crossfit", "spin class", "swimming", "martial arts", "boxing",
        "dance fitness", "triathlon training", "powerlifting", "barre",
        "obstacle course racing", "calisthenics", "tennis", "rowing", "climbing gyms",
    ],
    "intellectual": [
        "reading", "documentaries", "chess", "book club", "learning languages",
        "podcasts", "philosophy discussions", "trivia leagues", "puzzles",
        "coding for fun", "astronomy", "history deep-dives", "debate clubs",
        "museum visits", "science lectures", "crossword puzzles", "strategy games",
        "memoir writing", "genealogy research", "meditation study",
    ],
}


# the 12 seed users. diverse across gender, age (24-35), personality,
# occupation, availability, group-size preference, and hobby category.
USERS = [
    {
        "id": "u01",
        "name": "Maya",
        "age": 27,
        "gender": "female",
        "hobbies": ["reading", "pottery", "yoga", "puzzles", "museum visits", "knitting"],
        "personality": "introverted",
        "occupation": "working professional",
        "availability": ["weekday_evening", "weekend_daytime"],
        "location": "Ballard",
        "bio": "I'm a data analyst who recharges with a good book and a quiet pottery class. "
               "I love deep one-on-one conversations way more than big loud rooms. "
               "Still figuring out my way around Seattle after moving here last year.",
        "preferred_group_size": [2, 3],
    },
    {
        "id": "u02",
        "name": "Daniel",
        "age": 31,
        "gender": "male",
        "hobbies": ["photography", "trivia nights", "cycling", "cooking classes", "salsa dancing", "trail running"],
        "personality": "extroverted",
        "occupation": "freelancer",
        "availability": ["weekday_evening", "weekend_evening"],
        "location": "Capitol Hill",
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
        "hobbies": ["hiking", "documentaries", "volunteering", "cooking classes", "language exchange meetups", "birdwatching"],
        "personality": "mixed",
        "occupation": "student",
        "availability": ["weekday_daytime", "weekend_daytime"],
        "location": "Beacon Hill",
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
        "hobbies": ["chess", "weightlifting", "creative writing", "coding for fun", "podcasts", "powerlifting"],
        "personality": "introverted",
        "occupation": "working professional",
        "availability": ["weekday_evening"],
        "location": "Fremont",
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
        "hobbies": ["karaoke", "running", "painting", "wine tasting", "dance fitness", "swing dancing"],
        "personality": "extroverted",
        "occupation": "working professional",
        "availability": ["weekday_evening", "weekend_daytime", "weekend_evening"],
        "location": "Queen Anne",
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
        "hobbies": ["board games", "playing guitar", "cycling", "tabletop RPGs", "songwriting", "trivia leagues"],
        "personality": "mixed",
        "occupation": "freelancer",
        "availability": ["weekday_daytime", "weekend_evening"],
        "location": "Wallingford",
        "bio": "Freelance graphic designer who treats board game nights as a competitive sport. "
               "I play guitar badly and bike everywhere because parking in Wallingford is a nightmare. "
               "I like small groups where I can actually remember everyone's name.",
        "preferred_group_size": [3, 5],
    },
    {
        "id": "u07",
        "name": "Aisha",
        "age": 32,
        "gender": "female",
        "hobbies": ["book club", "pilates", "kayaking", "museum visits", "puzzles", "sailing"],
        "personality": "introverted",
        "occupation": "working professional",
        "availability": ["weekend_daytime"],
        "location": "West Seattle",
        "bio": "Lawyer with a brutal week, so weekends are sacred and mostly outdoors. "
               "I run a small book club and would happily talk about the same novel for hours. "
               "Kayaking on Lake Union is my reset button.",
        "preferred_group_size": [2, 4],
    },
    {
        "id": "u08",
        "name": "Ethan",
        "age": 35,
        "gender": "male",
        "hobbies": ["startup networking", "trivia nights", "weightlifting", "hackathons", "boxing", "podcasting"],
        "personality": "extroverted",
        "occupation": "working professional",
        "availability": ["weekday_evening", "weekend_evening"],
        "location": "South Lake Union",
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
        "hobbies": ["creative writing", "learning languages", "yoga", "calligraphy", "meditation study", "language exchange meetups"],
        "personality": "mixed",
        "occupation": "freelancer",
        "availability": ["weekday_daytime", "weekend_daytime"],
        "location": "Greenwood",
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
        "hobbies": ["investing club", "chess", "running", "podcasts", "triathlon training", "debate clubs"],
        "personality": "introverted",
        "occupation": "student",
        "availability": ["weekday_evening", "weekend_daytime"],
        "location": "Green Lake",
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
        "hobbies": ["volunteering", "camping", "painting", "board games", "beach volleyball", "cooking classes"],
        "personality": "extroverted",
        "occupation": "working professional",
        "availability": ["weekday_daytime", "weekend_evening"],
        "location": "Columbia City",
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
        "hobbies": ["playing guitar", "public speaking", "hiking", "songwriting", "toastmasters", "backpacking"],
        "personality": "mixed",
        "occupation": "freelancer",
        "availability": ["weekday_daytime", "weekday_evening", "weekend_evening"],
        "location": "Ravenna",
        "bio": "Working musician who teaches public speaking workshops on the side. "
               "I'm comfortable on a stage but I also disappear into the woods for a long hike alone. "
               "Looking for a medium-sized crew that's up for both shows and trailheads.",
        "preferred_group_size": [4, 6],
    },
]


# print the users as formatted json when run directly.
if __name__ == "__main__":
    print(json.dumps(USERS, indent=2))
