"""Fictional sample people for trying the agent-to-agent round (orchestrator.py).

Each dossier is written the way a person's own AI (ChatGPT, Claude, Muse,
Instinct) would describe them when given dossier.IMPORT_PROMPT. None of these
people are real. The same eight appear in the Clawnly Lounge prototype
(lounge/clawnly-lounge.html).
"""


PEOPLE = [
    {
        "id": "s1", "name": "Noa", "source": "ChatGPT",
        "dossier": "\n\n".join([
            "You're 31 and moved to Seattle (Capitol Hill) from Tel Aviv eight months ago for a UX research job. You're warm but blunt: you'd rather hear a hard truth on day one than find out in month six that someone was being polite. Honesty is the one thing you won't bend on.",
            "The hard part of this chapter is Friday nights. At home, Friday dinner was sacred: a long table, too much food, arguing about politics until midnight. Here, Fridays are the loneliest night of your week, and you've told me more than once that you miss being 'expected' somewhere.",
            "With friends you're the one who remembers birthdays and notices when someone's gone quiet. What you need back is consistency: people who show up when they say they will. Flaking hurts you more than you admit; you usually go cold rather than say so, which you know isn't great.",
            "Loud bars and networking events drain you. A small table of four to six people, real food and a real argument fills you up.",
            "Your humor is dry. You once described a date as 'a LinkedIn post with a pulse.'",
            "You're missing the kind of friend you can call at 11pm without apologizing.",
            "Bad fit: people who are always 'so busy', and people who can't handle disagreement.",
            "You're free Friday evenings and Sunday mornings. Capitol Hill, Seattle.",
        ]),
    },
    {
        "id": "s2", "name": "Marcus", "source": "Claude",
        "dossier": "\n\n".join([
            "You're 34, an ICU nurse on night shifts, living in Beacon Hill. You got divorced a year ago and you've been rebuilding quietly. You value steadiness and people who mean what they say. Cruelty dressed up as 'just joking' is a hard no for you.",
            "Right now you're figuring out who you are outside a marriage and outside the hospital. Cooking has become your therapy: you've talked about wanting a real 'Sunday table', people around your food who stay for hours, but you haven't had anyone to cook for.",
            "With friends you listen far more than you talk. You're the calm one in a crisis, which means people lean on you and rarely ask how you're doing. You need at least one friend who does ask. When you're let down, you don't make a scene; you just quietly stop investing.",
            "Crowds and small talk drain you, especially after a run of night shifts. Cooking for a few people and a long, honest conversation fills you up.",
            "Your humor is dark (ICU dark) but gentle. You told me the unit's unofficial motto is 'Everyone's fine until the coffee runs out.'",
            "You're missing friends who feel like family, the kind you don't have to perform for.",
            "Bad fit: people who flake, and people who treat every conversation as a stage.",
            "Free Sunday daytime into the evening, and Thursday evenings. Beacon Hill, Seattle.",
        ]),
    },
    {
        "id": "s3", "name": "Priya", "source": "Muse",
        "dossier": "\n\n".join([
            "You're 27, a public-health grad student in Fremont. You care about fairness and about actually doing things, not just talking about them. You start five projects a month and finish maybe one, and you know it.",
            "This chapter is a lot: thesis deadlines, a part-time job, and a sense that all your friends are 'grad school friends' who'll scatter in a year. You want people who'll still be around after.",
            "With friends you're the spark: you text the group chat with a plan at 6pm for 7pm. You need people who say yes to spontaneous things, and who'll gently hold you to the things you said you'd do. Conflict makes you talk too fast; you get over it quickly.",
            "Being alone too long drains you. Big, noisy, mixed groups fill you up: festivals, dance nights, potlucks where you know two people.",
            "Your humor is silly and physical; you do voices.",
            "You're missing an accountability friend who's also fun.",
            "Bad fit: people who need two weeks' notice for everything, and very reserved people who find you 'a lot'.",
            "Free most weekday evenings. Fremont, Seattle.",
        ]),
    },
    {
        "id": "s4", "name": "Jonah", "source": "Instinct",
        "dossier": "\n\n".join([
            "You're 29, a software engineer in Ballard, coming out of a real burnout. You care about craft: doing a few things slowly and well. You've been deliberately trying to be less online, and you took up wheel-throwing pottery because it's the one place your phone can't follow you.",
            "This chapter is about rebuilding a life that isn't just work. You've admitted that most of your friendships were really work friendships and they evaporated when you stepped back.",
            "With friends you're loyal and a good listener, slow to open up. It takes you a few meetings before you say anything real. You need patience for that, and people who are fine with comfortable silence. When let down, you withdraw and overthink.",
            "Networking energy, 'so what do you do', and packed schedules drain you. Long walks, early mornings, and making something with your hands fill you up.",
            "Your humor is understated and self-deprecating: 'I finally found a hobby where being slow is a feature.'",
            "You're missing a friend for slow Saturday mornings: a walk, coffee, no agenda.",
            "Bad fit: hustle-culture people and anyone who treats friendship as networking.",
            "Free weekend mornings, sometimes weekday evenings. Ballard, Seattle.",
        ]),
    },
    {
        "id": "s5", "name": "Elena", "source": "ChatGPT",
        "dossier": "\n\n".join([
            "You're 38, a social worker and a single mom to a six-year-old, living in Columbia City. You're fierce about fairness and about your kid, and you have zero patience for people who are unkind to service workers.",
            "This chapter is tiring and good. You've built a solid life, but nearly every adult you talk to is either a colleague or another parent at pickup. You want friendships that are about you, not your roles.",
            "With friends you're generous and funny and you'll show up with soup. You need friends who don't flinch when your kid is around sometimes, and who understand plans might move. You handle conflict head-on, sometimes too fast.",
            "Being 'on' for work all day drains you; you have little left for performing at social events. A relaxed daytime thing where your kid can come, or one grown-up evening a week, fills you up.",
            "Your humor is quick and a little wicked. You describe your calendar as 'a hostage situation with stickers.'",
            "You're missing one or two adult friends who are in it for the long haul.",
            "Bad fit: people who are precious about kids being around, and people who only do late nights.",
            "Free Saturday daytime (often with your kid) and Wednesday evenings. Columbia City, Seattle.",
        ]),
    },
    {
        "id": "s6", "name": "Theo", "source": "Claude",
        "dossier": "\n\n".join([
            "You're 26 and running an early-stage startup from Capitol Hill. You say you want deep friendships, but you've admitted to me that you schedule friends like meetings and often cancel when work spikes. Ambition is the thing you won't compromise on.",
            "This chapter is all-in on the company. You're lonelier than you let on, and you tend to turn every coffee into a pitch without meaning to.",
            "With friends you're generous with introductions and advice. You need people who don't take it personally when you go quiet for two weeks. When conflict comes, you try to 'solve' it like a product problem.",
            "Unstructured time drains you; you get restless. High-energy events with interesting people fill you up.",
            "Your humor is fast and a bit performative.",
            "You're missing friends who knew you before the startup, and you don't really have time to make new ones.",
            "Bad fit: people who need a lot of consistency or slow time.",
            "Free late weekday evenings, unpredictably. Capitol Hill, Seattle.",
        ]),
    },
    {
        "id": "s7", "name": "Sam", "source": "Muse",
        "dossier": "\n\n".join([
            "You're 33, nonbinary, a librarian in Beacon Hill. You care about gentleness and about people being allowed to be complicated. You lost your dad last year and you're still in it; grief comes in waves.",
            "This chapter is about learning to let people in while you're not okay. You've noticed most people change the subject when you mention your dad, and you've stopped mentioning him.",
            "With friends you're a deep listener and you remember everything. You need friends who can sit with heavy things without trying to fix them, and who'll also play a ridiculous board game with you afterwards. You avoid conflict and need people who'll name it kindly.",
            "Parties and forced cheerfulness drain you. Long talks, cooking together, and board games fill you up.",
            "Your humor is gentle and absurd; you name your houseplants after minor Victorian poets.",
            "You're missing a friend you don't have to be 'fine' around.",
            "Bad fit: relentlessly upbeat people, and people who treat feelings as a problem to solve.",
            "Free weekday evenings and Sunday afternoons. Beacon Hill, Seattle.",
        ]),
    },
    {
        "id": "s8", "name": "Aiko", "source": "Instinct",
        "dossier": "\n\n".join([
            "You're 30, a route setter at a climbing gym in Ballard. You're direct, physical, and allergic to drama. You've been sober for a year, which quietly rearranged your social life: bars are out, and a lot of old friends turned out to be drinking friends.",
            "This chapter is building a sober social life that isn't lonely. Early mornings are your best hours.",
            "With friends you're dependable and blunt. You'll help anyone move. You need people who say what they mean and don't need alcohol to relax. When let down, you say so once, clearly, and then it's done.",
            "Late nights and people who need a drink to open up drain you. Early hikes, coffee after a climb, and making things fill you up.",
            "Your humor is deadpan: 'I set routes for a living. I know exactly how people fall.'",
            "You're missing a friend for sunrise plans who won't flake at 6am.",
            "Bad fit: drama, night owls, and people whose social life runs through bars.",
            "Free early weekday mornings and weekend mornings. Ballard, Seattle.",
        ]),
    },
]
