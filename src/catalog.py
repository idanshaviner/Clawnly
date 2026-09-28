"""The things to do in a neighborhood: the menu the orchestrator plans from.

37 things to do in and around Black Diamond, WA, for the pilot. The places and
recurring events are real (Lake Sawyer Regional Park and its dock concerts, the
Black Diamond Historical Museum, Black Diamond Bakery, Flaming Geyser State
Park, the Green River Gorge, the Franklin ghost town trail, The Vault Taphouse,
Lumber House, Big Block Brewery, Lake Wilderness Golf Course, the Maple Valley
Farmers Market, ...). Exact times, prices and seasons are estimates for
simulation, not a published schedule -- check before telling a real person.

Each activity:
  id, name, neighborhood, where
  tags       -- which interests it serves (people's likes use the same words)
  traits     -- what some people avoid about it (crowds, early mornings, ...)
  days       -- weekdays it can run, 0 = Monday .. 6 = Sunday
  parts      -- day parts it can run: morning / afternoon / evening
  months     -- months of the year it runs, 1..12 (summer-only things are summer-only)
  cost       -- "free", "low" or "mid"
  outdoor    -- weather-dependent

Every group is 2 to 5 people (GROUP_MIN..GROUP_MAX), whatever the activity:
two neighbors having a beer over the game counts, and five is the most where
everyone still actually meets everyone.
"""

GROUP_MIN = 2
GROUP_MAX = 5

NEIGHBORHOOD = "Black Diamond, WA"

# where people live inside Black Diamond
AREAS = ["Ten Trails", "Lawson Hills", "Lake Sawyer", "Morgan Creek", "Downtown", "Black Diamond Ridge"]

DAY_PARTS = ["morning", "afternoon", "evening"]

TAGS = [
    "kayaking", "boating", "fishing", "swimming", "tubing", "picnics", "hiking", "photography",
    "history", "mountain_biking", "bmx", "basketball", "baseball", "golf", "pickleball", "running",
    "dog_walks", "birding", "yoga", "rc_planes", "watch_sports", "craft_beer", "dining", "live_music",
    "trivia", "coffee", "baking", "cooking", "board_games", "cards", "book_club", "crafts",
    "farmers_market", "gardening", "volunteering",
]

TRAITS = ["crowds", "early_mornings", "late_nights", "loud_places", "competitive", "spending_money", "long_drives"]

ALL_YEAR = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
SUMMER = [6, 7, 8, 9]
WARM = [5, 6, 7, 8, 9, 10]
EVERY_DAY = [0, 1, 2, 3, 4, 5, 6]
WEEKEND = [5, 6]


def _a(id, name, where, tags, traits, days, parts, months, cost, outdoor):
    return {"id": id, "name": name, "neighborhood": NEIGHBORHOOD, "where": where, "tags": tags,
            "traits": traits, "days": days, "parts": parts, "months": months, "cost": cost, "outdoor": outdoor}


ACTIVITIES = [
    # the lake
    _a("sawyer-paddle", "Paddle Lake Sawyer", "Lake Sawyer Regional Park boat launch",
       ["kayaking", "boating"], [], EVERY_DAY, ["morning", "afternoon"], WARM, "low", True),
    _a("sawyer-fishing", "Early fishing on Lake Sawyer", "Lake Sawyer Regional Park",
       ["fishing"], ["early_mornings"], EVERY_DAY, ["morning"], ALL_YEAR, "free", True),
    _a("sawyer-swim", "Swim and picnic at Lake Sawyer", "Lake Sawyer Regional Park beach",
       ["swimming", "picnics"], ["crowds"], EVERY_DAY, ["afternoon"], SUMMER, "free", True),
    _a("dock-concert", "Lake Sawyer Dock Concert", "Lake Sawyer (the summer dock concert series)",
       ["live_music", "boating", "picnics"], ["crowds"], [5], ["evening"], [7, 8], "free", True),
    _a("sawyer-birding", "Birding walk at Lake Sawyer", "Lake Sawyer Regional Park",
       ["birding", "photography"], ["early_mornings"], EVERY_DAY, ["morning"], ALL_YEAR, "free", True),
    _a("sawyer-dogs", "Dog walk around the park", "Lake Sawyer Regional Park",
       ["dog_walks"], [], EVERY_DAY, ["morning", "evening"], ALL_YEAR, "free", True),

    # history and town
    _a("museum", "Black Diamond Museum visit", "Black Diamond Historical Society & Museum, Railroad Ave (free)",
       ["history", "photography"], [], [3, 5, 6], ["morning", "afternoon"], ALL_YEAR, "free", False),
    _a("bakery", "Coffee and pastries at the Black Diamond Bakery", "Black Diamond Bakery",
       ["coffee", "baking"], [], EVERY_DAY, ["morning"], ALL_YEAR, "low", False),
    _a("cribbage", "Cribbage and coffee", "Black Diamond Bakery",
       ["cards", "coffee"], [], [0, 2, 4, 6], ["afternoon"], ALL_YEAR, "low", False),
    _a("book-club", "Book club", "the Black Diamond Library (KCLS)",
       ["book_club"], [], [1, 3], ["evening"], ALL_YEAR, "free", False),
    _a("potluck", "Potluck picnic", "Black Diamond Civic Park",
       ["picnics", "cooking"], [], WEEKEND, ["afternoon"], WARM, "low", True),
    _a("farmers-market", "Maple Valley Farmers Market and coffee", "Maple Valley Farmers Market (Saturdays 9-2)",
       ["farmers_market", "coffee", "cooking"], ["crowds"], [5], ["morning"], [5, 6, 7, 8, 9], "low", True),

    # trails
    _a("franklin", "Franklin ghost town hike", "Franklin ghost town trail, Green River Gorge Rd",
       ["hiking", "history", "photography"], [], EVERY_DAY, ["morning", "afternoon"], ALL_YEAR, "free", True),
    _a("gorge", "Green River Gorge hike", "Green River Gorge Conservation Area",
       ["hiking", "photography", "fishing"], [], WEEKEND, ["morning", "afternoon"], ALL_YEAR, "free", True),
    _a("ten-trails-walk", "Evening walk on the Ten Trails paths", "Ten Trails trail network",
       ["dog_walks", "hiking", "running"], [], EVERY_DAY, ["evening"], ALL_YEAR, "free", True),
    _a("easy-run", "Easy 5K together", "Ten Trails trail network",
       ["running"], ["early_mornings"], [1, 3, 5], ["morning"], ALL_YEAR, "free", True),
    _a("rainier", "Mount Rainier day hike", "Mount Rainier National Park (about an hour's drive)",
       ["hiking", "photography"], ["long_drives", "early_mornings"], WEEKEND, ["morning"], [7, 8, 9], "low", True),

    # wheels and sport
    _a("mtb", "Mountain bike the Black Diamond Open Space", "Black Diamond Open Space singletrack",
       ["mountain_biking"], ["competitive"], EVERY_DAY, ["afternoon", "evening"], WARM, "free", True),
    _a("bmx", "BMX track session", "the BMX track by the Black Diamond Community Gym",
       ["bmx"], ["competitive"], EVERY_DAY, ["afternoon", "evening"], WARM, "free", True),
    _a("hoops", "Pickup basketball", "the court on Bruckners Way",
       ["basketball"], ["competitive"], EVERY_DAY, ["afternoon", "evening"], ALL_YEAR, "free", True),
    _a("little-league", "Catch a Little League game", "the ballfield by Black Diamond Elementary",
       ["baseball", "watch_sports"], [], [0, 2, 5], ["evening"], [4, 5, 6], "free", True),
    _a("pickleball", "Pickleball doubles", "public courts in Maple Valley",
       ["pickleball"], ["competitive"], EVERY_DAY, ["morning", "evening"], ALL_YEAR, "free", True),
    _a("golf", "Nine holes at Lake Wilderness", "Lake Wilderness Golf Course, Maple Valley",
       ["golf"], ["spending_money"], EVERY_DAY, ["morning", "afternoon"], WARM, "mid", True),
    _a("rc-planes", "Fly RC planes at Flaming Geyser", "Flaming Geyser State Park model airfield",
       ["rc_planes"], [], WEEKEND, ["morning"], ALL_YEAR, "free", True),
    _a("tubing", "Tube the Green River", "Flaming Geyser State Park",
       ["tubing", "swimming"], ["crowds"], WEEKEND, ["afternoon"], [7, 8], "low", True),
    _a("geyser-hike", "Short hike and picnic at Flaming Geyser", "Flaming Geyser State Park",
       ["hiking", "picnics"], [], WEEKEND, ["afternoon"], ALL_YEAR, "free", True),
    _a("yoga", "Yoga on the lawn", "Lake Sawyer Regional Park lawn",
       ["yoga"], ["early_mornings"], WEEKEND, ["morning"], SUMMER, "free", True),

    # pubs, games and music
    _a("seahawks", "Watch the Seahawks over beers", "The Vault Taphouse & Beer Garden",
       ["watch_sports", "craft_beer"], ["crowds", "loud_places"], [0, 3, 6], ["afternoon", "evening"], [9, 10, 11, 12, 1], "low", False),
    _a("kraken", "Kraken hockey night", "Black Diamond Grill",
       ["watch_sports", "craft_beer", "dining"], ["loud_places"], [1, 3, 5], ["evening"], [10, 11, 12, 1, 2, 3, 4], "low", False),
    _a("vault-music", "Live music in the beer garden", "The Vault Taphouse & Beer Garden",
       ["live_music", "craft_beer"], ["loud_places", "late_nights"], [4, 5], ["evening"], ALL_YEAR, "low", False),
    _a("lumber-house", "Pints at Lumber House", "Lumber House brewery",
       ["craft_beer"], [], [3, 4, 5, 6], ["afternoon", "evening"], ALL_YEAR, "low", False),
    _a("big-block", "Brewpub dinner at Big Block", "Big Block Brewery, Black Diamond",
       ["craft_beer", "dining"], ["spending_money"], [3, 4, 5, 6], ["evening"], ALL_YEAR, "mid", False),
    _a("trivia", "Trivia night as one team", "a Black Diamond taproom",
       ["trivia", "craft_beer"], ["loud_places", "competitive"], [2], ["evening"], ALL_YEAR, "low", False),
    _a("game-night", "Board game night", "a neighbor's table (the host rotates)",
       ["board_games", "cards"], [], [4, 5], ["evening"], ALL_YEAR, "free", False),

    # making and giving back
    _a("crafts", "Crafts and woodworking night", "a neighbor's garage workshop",
       ["crafts"], [], [2, 6], ["evening", "afternoon"], ALL_YEAR, "free", False),
    _a("garden-swap", "Garden workday and plant swap", "a Lawson Hills backyard (the host rotates)",
       ["gardening", "volunteering"], ["early_mornings"], WEEKEND, ["morning"], [3, 4, 5, 6, 7, 8, 9, 10], "free", True),
    _a("trail-cleanup", "Trail cleanup work party", "Green River Gorge Conservation Area",
       ["volunteering", "hiking"], ["early_mornings"], [5], ["morning"], ALL_YEAR, "free", True),
]


def get(activity_id):
    i = 0
    while i < len(ACTIVITIES):
        if ACTIVITIES[i]["id"] == activity_id:
            return ACTIVITIES[i]
        i += 1
    return None
