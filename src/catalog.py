"""The things to do in each neighborhood: the menu the orchestrator plans from.

An illustrative catalog for a College Park-area pilot. The places are written
to feel real, but every time, price and group size here is invented for
simulation -- it is not a listing of real events.

Each activity:
  id, name, neighborhood, where
  tags       -- which interests it serves (people's likes use the same words)
  traits     -- what some people avoid about it (crowds, early mornings, ...)
  days       -- weekdays it can run, 0 = Monday .. 6 = Sunday
  parts      -- day parts it can run: morning / afternoon / evening
  min_size, max_size -- the group it needs and the most it can take
  cost       -- "free", "low" or "mid"
  outdoor    -- weather-dependent
"""

NEIGHBORHOODS = ["College Park", "Hyattsville", "Riverdale Park", "Columbia Heights"]

# who can reasonably get where: by bike or car to a neighbor, only by car across town
ADJACENT = {
    "College Park": ["Hyattsville", "Riverdale Park"],
    "Hyattsville": ["College Park", "Riverdale Park"],
    "Riverdale Park": ["College Park", "Hyattsville"],
    "Columbia Heights": [],
}

DAY_PARTS = ["morning", "afternoon", "evening"]

TAGS = [
    "kayaking", "paddleboarding", "hiking", "running", "cycling", "climbing", "yoga",
    "basketball", "soccer", "frisbee", "watch_sports", "trivia", "board_games", "cooking",
    "book_club", "coding", "volunteering", "gardening", "live_music", "museums",
    "photography", "chess", "pottery", "dance", "farmers_market", "dog_walks", "karaoke", "movies",
]

TRAITS = ["crowds", "early_mornings", "late_nights", "loud_places", "competitive", "spending_money"]

WEEKDAYS = [0, 1, 2, 3, 4]
WEEKEND = [5, 6]
EVERY_DAY = [0, 1, 2, 3, 4, 5, 6]


def _a(id, name, neighborhood, where, tags, traits, days, parts, min_size, max_size, cost, outdoor):
    return {"id": id, "name": name, "neighborhood": neighborhood, "where": where, "tags": tags,
            "traits": traits, "days": days, "parts": parts, "min_size": min_size, "max_size": max_size,
            "cost": cost, "outdoor": outdoor}


ACTIVITIES = [
    # College Park
    _a("cp-lake-walk", "Sunrise loop around Lake Artemesia", "College Park", "Lake Artemesia trailhead",
       ["hiking", "running", "photography", "dog_walks"], ["early_mornings"], EVERY_DAY, ["morning"], 3, 8, "free", True),
    _a("cp-pickup", "Pickup basketball", "College Park", "campus rec center courts",
       ["basketball"], ["competitive"], EVERY_DAY, ["afternoon", "evening"], 6, 10, "free", False),
    _a("cp-trivia", "Trivia night team", "College Park", "a Route 1 pub",
       ["trivia"], ["loud_places", "competitive", "late_nights"], [1, 3], ["evening"], 4, 6, "low", False),
    _a("cp-code", "Build night: bring a side project", "College Park", "a library study room",
       ["coding"], [], [0, 2, 4], ["evening"], 3, 8, "free", False),
    _a("cp-boardgames", "Board game table", "College Park", "a board game cafe on Route 1",
       ["board_games", "chess"], [], [2, 4, 5, 6], ["afternoon", "evening"], 3, 6, "low", False),
    _a("cp-soccer", "Casual 5-a-side soccer", "College Park", "the intramural fields",
       ["soccer"], ["competitive"], [5, 6], ["morning", "afternoon"], 8, 12, "free", True),
    _a("cp-frisbee", "Ultimate frisbee pickup", "College Park", "McKeldin Mall lawn",
       ["frisbee", "running"], [], [5, 6], ["afternoon"], 6, 14, "free", True),
    _a("cp-watch", "Watch the game together", "College Park", "a sports bar with big screens",
       ["watch_sports"], ["crowds", "loud_places"], [5, 6], ["afternoon", "evening"], 4, 10, "low", False),
    _a("cp-movie", "Indie movie night", "College Park", "the campus cinema",
       ["movies"], [], [3, 4, 5], ["evening"], 2, 6, "low", False),

    # Hyattsville
    _a("hy-kayak", "Kayaking on the Anacostia", "Hyattsville", "Bladensburg Waterfront boat rentals",
       ["kayaking", "paddleboarding"], ["early_mornings"], [5, 6], ["morning", "afternoon"], 4, 6, "mid", True),
    _a("hy-bike", "Easy trail ride on the Anacostia Tributary Trails", "Hyattsville", "the trailhead by the arts district",
       ["cycling"], [], [5, 6], ["morning", "afternoon"], 3, 8, "free", True),
    _a("hy-cook", "Community cooking class", "Hyattsville", "a teaching kitchen in the arts district",
       ["cooking"], ["spending_money"], [2, 4, 5], ["evening"], 4, 8, "mid", False),
    _a("hy-garden", "Community garden workday", "Hyattsville", "the neighborhood community garden",
       ["gardening", "volunteering"], ["early_mornings"], [5, 6], ["morning"], 3, 10, "free", True),
    _a("hy-market", "Farmers market stroll + coffee", "Hyattsville", "the Saturday farmers market",
       ["farmers_market", "cooking", "photography"], [], [5], ["morning"], 3, 8, "low", True),
    _a("hy-music", "Live music at a small venue", "Hyattsville", "a listening room on Baltimore Ave",
       ["live_music", "dance"], ["loud_places", "late_nights"], [3, 4, 5], ["evening"], 3, 8, "mid", False),
    _a("hy-pottery", "Open studio pottery", "Hyattsville", "a community clay studio",
       ["pottery"], ["spending_money"], [1, 3, 6], ["evening", "afternoon"], 3, 6, "mid", False),
    _a("hy-karaoke", "Karaoke room", "Hyattsville", "a private karaoke room",
       ["karaoke"], ["loud_places", "late_nights"], [4, 5], ["evening"], 4, 8, "mid", False),

    # Riverdale Park
    _a("rp-yoga", "Park yoga", "Riverdale Park", "Riverdale Park town green",
       ["yoga"], ["early_mornings"], [5, 6], ["morning"], 3, 12, "free", True),
    _a("rp-run", "Social 5K run club", "Riverdale Park", "Riverdale Park station plaza",
       ["running"], ["early_mornings"], [1, 3, 5], ["morning", "evening"], 4, 15, "free", True),
    _a("rp-books", "Book club over coffee", "Riverdale Park", "a coffee shop near the town center",
       ["book_club"], [], [0, 3, 6], ["evening", "afternoon"], 3, 8, "low", False),
    _a("rp-volunteer", "Food bank packing shift", "Riverdale Park", "the local food bank",
       ["volunteering"], [], [2, 5], ["morning", "afternoon"], 4, 12, "free", False),
    _a("rp-dogs", "Dog walk meetup", "Riverdale Park", "the Northeast Branch trail",
       ["dog_walks", "hiking"], [], EVERY_DAY, ["morning", "evening"], 3, 10, "free", True),
    _a("rp-chess", "Chess and coffee", "Riverdale Park", "a cafe with outdoor tables",
       ["chess", "board_games"], [], [0, 2, 6], ["afternoon", "evening"], 2, 6, "low", False),

    # Columbia Heights (DC)
    _a("ch-climb", "Bouldering session", "Columbia Heights", "a bouldering gym",
       ["climbing"], ["spending_money"], EVERY_DAY, ["afternoon", "evening"], 3, 6, "mid", False),
    _a("ch-museum", "Late-night museum visit", "Columbia Heights", "a Smithsonian museum downtown",
       ["museums", "photography"], ["crowds"], [3, 4], ["evening"], 3, 8, "free", False),
    _a("ch-dance", "Salsa social (beginners welcome)", "Columbia Heights", "a dance studio on 14th St",
       ["dance", "live_music"], ["loud_places", "late_nights"], [2, 5], ["evening"], 4, 12, "low", False),
    _a("ch-watch", "Watch the match at a soccer bar", "Columbia Heights", "a soccer bar on 14th St",
       ["watch_sports", "soccer"], ["crowds", "loud_places"], [5, 6], ["morning", "afternoon"], 4, 10, "low", False),
    _a("ch-hike", "Rock Creek Park hike", "Columbia Heights", "Rock Creek Park trailhead",
       ["hiking", "photography", "dog_walks"], [], [5, 6], ["morning", "afternoon"], 3, 8, "free", True),
]


def get(activity_id):
    i = 0
    while i < len(ACTIVITIES):
        if ACTIVITIES[i]["id"] == activity_id:
            return ACTIVITIES[i]
        i += 1
    return None


def reachable(home, neighborhood, travel):
    # walkers stay home; bikes reach the next neighborhood; a car goes anywhere
    if home == neighborhood:
        return True
    if travel == "car":
        return True
    if travel == "bike":
        return neighborhood in ADJACENT.get(home, [])
    return False
