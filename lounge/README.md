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

**Before republishing this file from a Claude session, read the live artifact first
and carry its `clawnly-state` JSON over.** Otherwise you overwrite every saved
conversation and yes/no answer.

The sample people (`SEED` in the script) are fictional.
