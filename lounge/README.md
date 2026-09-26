# Clawnly Lounge (agent-to-agent prototype)

A single-file prototype of the agent-to-agent version of Clawnly, published as a
claude.ai Artifact: https://claude.ai/artifact/LUqHTUzFhN6JiKNCEmN3Ro

- **Bring your agent:** a person copies one prompt into the AI that already knows
  them (ChatGPT, Claude, Muse, Instinct), pastes the answer back, and the hub turns
  it into the card their agent carries. It also flags answers that read like a
  social-media self (a "real-you" score).
- **Hub picks pairs:** one call. Code rejects unknown ids, self-pairs, repeats, and
  anyone over the per-person or per-round limits.
- **Agents talk:** a 6-message private conversation. Each agent sees only its own
  person's dossier and must say "I don't know" rather than invent.
- **Hub judges:** returns depth (1-10), reasoning, risks and evidence quotes. Code
  discards any quote that isn't verbatim in the transcript. An invitation is sent
  only if the hub recommends it, depth is >= 8, and >= 2 quotes are verified.
- **Humans:** yes or no per invitation. Hit rate = both-yes / decided invitations.
- **Behind the scenes:** every hub thought, agent message, code check and human
  action is logged and readable.

It runs on the viewer's Claude account (the Artifact `sample` capability). The page
stores its own results by republishing itself (the `artifact` capability): the saved
state lives in the `<script id="clawnly-state">` block.

**Who can do what.** Share it by email invite ("Only people invited"), never "Anyone with
the link": a public page has its Claude and saving switched off, and real dossiers would
be readable by anyone.
- The owner (and anyone inside the owner's Claude account): runs the agents, reads, joins,
  answers, clears results.
- A guest invited as an editor from outside the owner's account: Claude can't run in their
  view, but they can bring their agent (the hub writes its card on the owner's next run),
  answer their own invitations, and read everything. The top bar says "Guest view".
- Anyone else: reading only.

**Answering only for yourself.** A person added from a browser gets a random claim token
that stays in that browser's localStorage; the page stores only its SHA-256 hash. Only that
browser (or a signed-in viewer with the same user id) can answer that person's invitations.
Someone added on another person's behalf (no owner, no claim) can only be answered by the
page owner. Only the page owner can clear results. Everything shown is escaped text.

**Simulation lab (no humans in the loop).** For tuning the hub and agents without real
people, per Eitan's direction:
- 16 fictional people (Seattle and a College Park / DC cluster); samples added to `SEED` later
  join an existing lounge automatically.
- After each invitation, each person's yes/no is **emulated** from their dossier (one call per
  side), stored apart from real answers, logged as `emulated`, and shown as "emulated".
  Invitations made before emulation get their answers on the next run.
- "Rounds: up to 3/5" runs several rounds in one click and stops early when the hub finds no
  new pair.
- **Monitor** tab: pipeline counts, why the gate said no, the depth-score histogram, quotes
  discarded, and every Claude call counted by step (calls, average time, failures), plus
  "Copy all results as JSON" for analysis elsewhere. Counted from the saved record, never
  written by the model.
- **Knobs** (owner only): depth bar, messages per chat, pairs per round, emulation on/off.
  Every change is logged.
- Evidence now matches the app: a quote must appear in one agent's message, and verified
  quotes must come from both agents.
- **How it's built** tab: what changed from the previous model and the hub-and-spoke design.

**Two writers at once.** Every save stashes the unsaved state in sessionStorage first. If it
loses the race (`conflict`), the page reloads to the winner and merges the stash back in
(people, conversations and answers by id, log lines by content), then saves again, so a
round never disappears because someone joined mid-run.

**Before republishing this file from a Claude session, read the live artifact first
and carry its `clawnly-state` JSON over.** Otherwise you overwrite every saved
conversation and yes/no answer.

The sample people (`SEED` in the script) are fictional.
