# Clawnly, live this week: the plan

Goal: by the end of this week, 10-15 real people have brought their agents in,
the agents have talked, and at least a few pairs got an invitation they said
yes or no to. The orchestration (the hub) and the Claw are the core; everything
else serves them.

## The product in one picture

```
 YOU                YOUR AGENT (Claw)                 THE HUB (Master Claw)             YOU
 ───                ─────────────────                 ─────────────────────             ───
 paste what    ──►  carries ONLY that text.   ◄──►    1. reads everyone's card,    ──►  "Meet Noa?
 ChatGPT /          talks privately with              picks who should talk             Yes / No"
 Claude / Muse /    other people's agents.            2. reads each conversation
 Instinct knows     says "I don't know"               3. invites only deep fits,
 about you          instead of inventing.             proving it with quotes

                    everything above is written to the behind-the-scenes log
```

## What's already built (today)

- **Prototype you can share now:** https://claude.ai/artifact/LUqHTUzFhN6JiKNCEmN3Ro
- **The engine inside the real app** (`src/`, 334 tests passing):
  - `dossier.py`: the "bring your agent" prompt, plus turning the pasted answer into a card
    (with a "real you vs social-media you" score).
  - `agent_talk.py`: the Claw. It represents one person from their own text only, talks
    privately with another Claw, and says "I don't know" rather than invent.
  - `orchestrator.py`: the hub. It picks pairs, runs conversations (3 at a time), and judges
    each one. **Code** enforces the rules: no repeats, no invented quotes, and no invitation
    unless depth >= 8/10 with at least 2 real quotes.
  - `db.events`: the behind-the-scenes log. Every hub thought and decision, every agent
    message, every code check. `db.agent_conversations` holds every chat plus its verdict.
- Try the engine on 8 fictional people (needs your API key in `.env`):
  `.venv/bin/python src/orchestrator.py`. It prints every event live and saves all of it.

## Day by day

| Day | Build | Done when |
|---|---|---|
| **Mon (today)** | Hub + Claw + event log in the real app. | Done. Run `src/orchestrator.py` with your key and read the conversations. |
| **Tue** | **Onboarding swap.** `/join/<slug>` -> login -> consent -> "Bring your agent" page (prompt, paste, card preview). Card and text saved on the resident. Remove the 20-turn chat. Rewrite the consent text for pasted AI portraits. | You sign up yourself in under 2 minutes and see your card. |
| **Wed** | **Wire the hub into the pilot.** When enough people have joined, run `orchestrator.run_round` for the neighborhood. Invitations go into the existing yes/no screen, showing the hub's pitch only (this also fixes the name-leak bug). Lower the threshold from 100 to ~10. | A test neighborhood of fake residents gets real invitations on `/my-match`. |
| **Thu** | **Admin "behind the scenes".** Chat reader and event log per round, plus a hit-rate tile (both-yes ÷ decided). Security review of the new routes. Deploy to Render. | You can read every conversation and every hub decision from `/admin`. |
| **Fri** | **Real people.** You, Eitan, Nathan and ~10 friends join through one invite link. Run a round. Read the logs together and tune the Claw and hub prompts. | First real invitations sent. |
| **Weekend** | Meetings happen. Ask each person one question: "Did you meet? Would you meet again?" | First real hit rate. |

## Only you can do these (they block Fri)

1. **Anthropic API key** in `.env` locally and in Render's environment.
2. **Email login for real people:** a Resend account with a verified sending domain. Without
   it, magic links only print to the server console. Google login needs its OAuth consent
   screen moved out of "Testing".
3. **Recruit 10-15 people** who agree to paste their AI's portrait of them. Friends first.
4. **Confirm the pivot.** `docs/PILOT_PLAN.md` said "no ChatGPT-history import". This plan
   reverses that, and the consent and privacy text must say so plainly.

## Deliberately NOT this week

- Groups of 3-5. Pairs first; later, groups get built from strong pairs.
- A live connection to people's own ChatGPT or Claude (their assistant answering in real
  time). Copy-paste proves the idea; connectors come after people ask for them.
- The old matching pipeline (`master_claw.py` and friends) stays as-is for the demo console.
  The pilot moves to the hub.

---

## The note for Eitan (simple version)

> Hey Eitan, thanks for the push. You were right. Here's what Clawnly is now, simply:
>
> 1. **Signup:** you ask the AI you already use (ChatGPT, Claude, Muse...) to describe the
>    *real* you, not your Instagram self. You paste it in. That's it.
> 2. **Your agent** carries that description and talks privately with other people's agents.
>    They ask real questions: what you value, what you need from friends, how you handle being
>    let down. If your agent doesn't know something about you, it says so instead of making it up.
> 3. **A hub agent** decides who should talk, reads every conversation, and only suggests a
>    meeting when it's a deep fit. It has to quote the conversation to prove it.
> 4. **You** get one message: "Meet Noa? Yes / No." That's the only moment you're involved.
>
> Everything behind the scenes is visible: every agent conversation, and why the hub decided
> what it did.
>
> Try it here: https://claude.ai/artifact/LUqHTUzFhN6JiKNCEmN3Ro. The people in it now are
> made-up samples. Add your own agent and tell me if the conversations feel right. We're
> putting 10-15 real people through it this Friday. Want in?
