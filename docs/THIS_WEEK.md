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

## Status

- **Mon: done.** The Claw (`agent_talk.py`), the hub (`orchestrator.py`), cards (`dossier.py`),
  and the behind-the-scenes log (`db.events`, `db.agent_conversations`).
- **Tue: done.** `/onboarding` is "Bring your agent" (`bring_agent.py`): copy a prompt into your
  own AI, paste its answer, check your card, join. Consent and privacy text rewritten.
- **Wed: done.** The hub is wired into the pilot (`batch.py`). Joining triggers a check; when a
  neighborhood reaches its threshold (now 10 for new neighborhoods), the hub runs a round, and
  each invitation lands on `/my-match` as a name-blind yes/no. One invitation per person per
  round, strongest first. The old logic is deleted (preserved on the `pre-agent-pivot` branch):
  the group matcher, negotiation, meetup popups, the onboarding chat, the demo console, and
  their scripts.
- **Thu, pulled forward and done:** `/admin` shows each round's counts and API calls, and a
  "Behind the scenes" view: every conversation word for word, plus the full activity log.
- **Still to do Thu:** a hit-rate tile (both-yes / decided) on the admin page, and deploying to
  Render (needs the keys below).
- **Fri:** real people (you, Eitan, Idan, ~10 friends) through one invite link (create the
  neighborhood in `/admin`; its secret link is shown there); run a round;
  read the conversations together and tune the Claw and hub prompts.

## Day by day

| Day | Build | Status |
|---|---|---|
| **Mon** | Hub + Claw + event log in the real app. | Done |
| **Tue** | Signup becomes "Bring your agent". | Done |
| **Wed** | Hub wired into the pilot; invitations on the yes/no screen; old logic deleted. | Done |
| **Thu** | Admin "behind the scenes" (done), hit-rate tile, deploy to Render. | In progress |
| **Fri** | Real people join; run a round; tune prompts from the real conversations. | Next |
| **Weekend** | Meetings happen. Ask: "Did you meet? Would you meet again?" | Next |

**Meanwhile, today:** the Lounge prototype (https://claude.ai/artifact/LUqHTUzFhN6JiKNCEmN3Ro)
is how you, Eitan and Idan bring your real agents in before the app is deployed.

## Only you can do these (they block Fri)

1. **Anthropic API key**, created inside a workspace in the Anthropic Console (an unscoped key
   is refused on every call), in `.env` locally and in Render's environment.
2. **Email login for real people:** a Resend account with a verified sending domain. Without
   it, magic links only print to the server console. Google login needs its OAuth consent
   screen moved out of "Testing".
3. **Recruit 10-15 people** who agree to paste their AI's portrait of them. Friends first.
4. **Merge the pull request** from `clawnly-lounge` into `main` (you or Idan).

## Deliberately NOT this week

- Groups of 3-5. Pairs first; later, groups get built from strong pairs.
- A live connection to people's own ChatGPT or Claude (their assistant answering in real
  time). Copy-paste proves the idea; connectors come after people ask for them.
- Automatic repeat rounds. After the first automatic round, the admin runs later rounds
  from `/admin` ("Run a hub round now").

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
