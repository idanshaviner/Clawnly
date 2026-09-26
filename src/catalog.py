"""The things to do in a neighborhood: the menu the orchestrator plans from.

30 things to do in and right around College Park, MD, for the pilot. The places
are written to feel real, but every time and price here is invented for
simulation -- it is not a listing of real events.

Each activity:
  id, name, neighborhood, where
  tags       -- which interests it serves (people's likes use the same words)
  traits     -- what some people avoid about it (crowds, early mornings, ...)
  days       -- weekdays it can run, 0 = Monday .. 6 = Sunday
  parts      -- day parts it can run: morning / afternoon / evening
  cost       -- "free", "low" or "mid"
  outdoor    -- weather-dependent

Every group is 2 to 5 people (GROUP_MIN..GROUP_MAX), whatever the activity:
two neighbors having a beer over the game counts, and five is the most where
everyone still actually meets everyone.
"""

GROUP_MIN = 2
GROUP_MAX = 5

NEIGHBORHOOD = "College Park"

DAY_PARTS = ["morning", "afternoon", "evening"]

TAGS = [
    "watch_sports", "craft_beer", "coffee", "trivia", "board_games", "chess", "karaoke", "live_music",
    "dance", "movies", "museums", "book_club", "coding", "cooking", "farmers_market", "pottery",
    "photography", "gardening", "volunteering", "hiking", "running", "cycling", "dog_walks", "yoga",
    "climbing", "kayaking", "basketball", "soccer", "frisbee", "pickleball",
]

TRAITS = ["crowds", "early_mornings", "late_nights", "loud_places", "competitive", "spending_money"]

WEEKDAYS = [0, 1, 2, 3, 4]
WEEKEND = [5, 6]
EVERY_DAY = [0, 1, 2, 3, 4, 5, 6]


def _a(id, name, where, tags, traits, days, parts, cost, outdoor):
    return {"id": id, "name": name, "neighborhood": NEIGHBORHOOD, "where": where, "tags": tags,
            "traits": traits, "days": days, "parts": parts, "cost": cost, "outdoor": outdoor}


ACTIVITIES = [
    # out and social
    _a("sports-bar", "Beers and the game at a sports bar", "a sports bar on Route 1",
       ["watch_sports", "craft_beer"], ["crowds", "loud_places"], [0, 3, 5, 6], ["afternoon", "evening"], "low", False),
    _a("brewery", "Tasting flight at a local brewery", "a brewery taproom in the Hollywood area",
       ["craft_beer"], ["loud_places"], [3, 4, 5, 6], ["afternoon", "evening"], "mid", False),
    _a("trivia", "Trivia night as one team", "a Route 1 pub",
       ["trivia", "craft_beer"], ["loud_places", "competitive", "late_nights"], [1, 3], ["evening"], "low", False),
    _a("karaoke", "Karaoke room", "a private karaoke room off Route 1",
       ["karaoke"], ["loud_places", "late_nights"], [4, 5], ["evening"], "mid", False),
    _a("live-music", "Live music at a small venue", "a listening room nearby",
       ["live_music"], ["loud_places", "late_nights"], [3, 4, 5], ["evening"], "mid", False),
    _a("salsa", "Beginner salsa social", "a dance studio near downtown College Park",
       ["dance", "live_music"], ["loud_places", "late_nights"], [2, 5], ["evening"], "low", False),
    _a("movie", "Indie movie night", "the campus cinema",
       ["movies"], [], [3, 4, 5, 6], ["evening"], "low", False),
    _a("aviation-museum", "College Park Aviation Museum visit", "the aviation museum by the airport",
       ["museums", "photography"], [], [2, 3, 4, 5, 6], ["morning", "afternoon"], "low", False),

    # tables and talk
    _a("coffee-walk", "Coffee and a walk", "a Route 1 coffee shop, then the trolley trail",
       ["coffee", "dog_walks"], [], EVERY_DAY, ["morning", "afternoon"], "low", True),
    _a("board-games", "Board game table", "a board game cafe on Route 1",
       ["board_games", "chess"], [], [2, 4, 5, 6], ["afternoon", "evening"], "low", False),
    _a("chess", "Chess and coffee", "a cafe with outdoor tables",
       ["chess", "coffee"], [], [0, 2, 6], ["afternoon", "evening"], "low", False),
    _a("book-club", "Book club over coffee", "a coffee shop near the Metro",
       ["book_club", "coffee"], [], [0, 3, 6], ["afternoon", "evening"], "low", False),
    _a("build-night", "Build night: bring a side project", "a library study room",
       ["coding"], [], [0, 2, 4], ["evening"], "free", False),

    # making things
    _a("cooking", "Dumpling-making class", "a community teaching kitchen",
       ["cooking"], ["spending_money"], [2, 4, 5], ["evening"], "mid", False),
    _a("farmers-market", "Farmers market stroll and brunch", "the Saturday farmers market",
       ["farmers_market", "cooking", "coffee"], [], [5], ["morning"], "low", True),
    _a("pottery", "Open studio pottery", "a community clay studio",
       ["pottery"], ["spending_money"], [1, 3, 6], ["afternoon", "evening"], "mid", False),
    _a("photo-walk", "Golden-hour photo walk", "McKeldin Mall and the campus gardens",
       ["photography", "hiking"], [], EVERY_DAY, ["evening"], "free", True),
    _a("garden", "Community garden workday", "the neighborhood community garden",
       ["gardening", "volunteering"], ["early_mornings"], [5, 6], ["morning"], "free", True),
    _a("food-bank", "Food bank packing shift", "a food pantry near campus",
       ["volunteering"], [], [2, 5], ["morning", "afternoon"], "free", False),

    # moving outdoors
    _a("lake-loop", "Sunrise loop around Lake Artemesia", "Lake Artemesia trailhead",
       ["hiking", "running", "dog_walks"], ["early_mornings"], EVERY_DAY, ["morning"], "free", True),
    _a("5k", "Easy 5K together", "the trolley trail",
       ["running"], ["early_mornings"], [1, 3, 5], ["morning", "evening"], "free", True),
    _a("bike-ride", "Easy ride on the Paint Branch Trail", "the Paint Branch trailhead",
       ["cycling"], [], [5, 6], ["morning", "afternoon"], "free", True),
    _a("dog-walk", "Dog walk meetup", "the Paint Branch trail",
       ["dog_walks", "hiking"], [], EVERY_DAY, ["morning", "evening"], "free", True),
    _a("yoga", "Yoga in the park", "a park lawn near the Metro",
       ["yoga"], ["early_mornings"], [5, 6], ["morning"], "free", True),
    _a("kayak", "Kayaking on the Anacostia", "Bladensburg Waterfront boat rentals (10 min drive)",
       ["kayaking"], ["early_mornings"], [5, 6], ["morning", "afternoon"], "mid", True),
    _a("climbing", "Bouldering session", "a bouldering gym",
       ["climbing"], ["spending_money"], EVERY_DAY, ["afternoon", "evening"], "mid", False),

    # games and sport
    _a("pickleball", "Pickleball doubles", "the public courts by the rec center",
       ["pickleball"], ["competitive"], EVERY_DAY, ["morning", "evening"], "free", True),
    _a("shootaround", "Shootaround and a game of HORSE", "the campus rec courts",
       ["basketball"], ["competitive"], EVERY_DAY, ["afternoon", "evening"], "free", False),
    _a("kickaround", "Soccer kick-around", "the intramural fields",
       ["soccer"], [], [5, 6], ["morning", "afternoon"], "free", True),
    _a("frisbee", "Frisbee toss", "McKeldin Mall lawn",
       ["frisbee"], [], [5, 6], ["afternoon"], "free", True),
]


def get(activity_id):
    i = 0
    while i < len(ACTIVITIES):
        if ACTIVITIES[i]["id"] == activity_id:
            return ACTIVITIES[i]
        i += 1
    return None
