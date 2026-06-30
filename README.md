# Clawnly — Matchmaker Prototype (PoC)

Multi-agent matchmaking that fights loneliness by finding people "their people."
Each user has a **Claw** (an AI agent that embodies them); a **Master Claw**
interviews every Claw and forms one compatible group meetup, with visible,
grounded reasoning. This PoC's job is to prove the **matching is legit** before
real user data is ever connected. See [docs/SPEC.md](docs/SPEC.md) and
[docs/PRD.md](docs/PRD.md).

## Project layout

```
Clawnly/
├── README.md            ← you are here
├── requirements.txt
├── pyproject.toml        ← project + test config
├── docs/                 ← the written specs (descriptions)
│   ├── SPEC.md           ← technical spec for this build
│   └── PRD.md            ← product vision, roadmap, metrics
├── src/                  ← all the code
│   ├── config.py         ← model ids, temperatures, API client    (settings)
│   ├── users.py          ← 12 users + hobby/availability vocab     (data)
│   ├── llm_io.py          ← parse JSON out of Claude replies        (shared)
│   ├── claw.py           ← Claw: one agent per user                (worker agent)
│   ├── master_claw.py    ← interviews + matching + validator        (orchestrator)
│   ├── negotiation.py    ← parent agent brokers common ground + plan (negotiation)
│   ├── popup.py          ← group → concrete meetup card            (output)
│   ├── app.py            ← web app backend (FastAPI)               (browser UI)
│   ├── web/index.html    ← the single-page front end (chat, edit, run, ask)
│   ├── explain.py        ← Master Claw explains its decisions      (explainability)
│   ├── main.py           ← runs the full pipeline, prints stages   (entry point)
│   ├── persona_gen.py    ← AI-generate a fresh cast of users       (generator)
│   ├── eval.py           ← quality harness: prove it's "legit"     (evaluation)
│   └── demo.py           ← free offline run, scripted AI           (demo)
└── tests/                ← the test suite (run: python -m pytest)
```

## Setup

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
```

## Run

```bash
.venv/bin/python src/app.py         # the app (or double-click Clawnly.command) — http://127.0.0.1:8000
.venv/bin/python src/demo.py        # FREE: full pipeline offline with scripted AI (no API, no cost)
.venv/bin/python src/users.py       # FREE: print the 12 simulated users as JSON
.venv/bin/python src/main.py        # COSTS ~cents: interview -> match -> negotiate -> popup, real Claude
.venv/bin/python src/eval.py        # COSTS ~cents: evaluation harness across many pools
```

The app's **Demo mode** is free; chatting with people and editing them live needs
`ANTHROPIC_API_KEY` (paste it into the app, or use a `.env` file).

## Test

```bash
.venv/bin/python -m pytest -q
```

The full suite runs offline with a mocked client (zero API calls).

## How the code is layered

| Layer | Files | Responsibility |
|---|---|---|
| Settings | `config.py` | one place for model ids, temperatures, the API client |
| Data | `users.py` | the 12 people and the closed vocabularies they use |
| Worker agent | `claw.py` | be one user; answer questions in first person |
| Orchestrator | `master_claw.py` | interview all Claws, form + validate a group |
| Output | `popup.py` | turn the chosen group into a real meetup card |
| Shared | `llm_io.py` | read JSON safely out of model replies |
| Entry points | `main.py`, `demo.py`, `eval.py` | wire it together / demo / evaluate |

Each file does one job, so the matching logic (`master_claw.py`) can be read,
tested, and trusted on its own.
