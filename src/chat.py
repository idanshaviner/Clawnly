"""Free-style chat with the Clawly personas.

Pick one of the 12 people and just talk to them, back and forth, to get a feel
for how convincingly each Claw embodies its persona. This makes live API calls
(a fraction of a cent per message), so it needs ANTHROPIC_API_KEY.

Run: python src/chat.py
"""

import asyncio

import config
from claw import Claw
from users import USERS


def roster():
    # a numbered menu of who you can talk to.
    lines = []
    i = 0
    while i < len(USERS):
        u = USERS[i]
        first_hobbies = ", ".join(u["hobbies"][:2])
        lines.append("  {}. {} ({}, {}, into {})".format(i + 1, u["name"], u["age"], u["personality"], first_hobbies))
        i += 1
    return "\n".join(lines)


def find_persona(choice):
    # accept a 1-based number or a name (case-insensitive); None if no match.
    text = choice.strip()
    if text.isdigit():
        index = int(text) - 1
        if index >= 0 and index < len(USERS):
            return USERS[index]
        return None
    i = 0
    while i < len(USERS):
        if USERS[i]["name"].lower() == text.lower():
            return USERS[i]
        i += 1
    return None


async def _converse(user, client):
    # one chat session with a chosen persona; returns "switch" or "quit".
    claw = Claw(user, client=client)
    history = []
    print("\nNow chatting with {}. ('switch' to change person, 'quit' to exit)\n".format(user["name"]))
    while True:
        try:
            message = input("you > ").strip()
        except EOFError:
            return "quit"
        if message == "":
            continue
        if message.lower() == "quit" or message.lower() == "exit":
            return "quit"
        if message.lower() == "switch":
            return "switch"
        reply = await claw.chat(message, history)
        print("\n{} > {}\n".format(user["name"], reply))
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": reply})


async def main(client=None):
    if client is None:
        client = config.get_client()
    print("=== Chat with the Clawly personas (free-style) ===")
    while True:
        print("\nWho do you want to talk to?")
        print(roster())
        choice = input("\npick a number or name (or 'quit') > ").strip()
        if choice.lower() == "quit" or choice.lower() == "exit":
            print("bye!")
            return
        user = find_persona(choice)
        if user is None:
            print("hmm, didn't recognize that one -- try again.")
            continue
        result = await _converse(user, client)
        if result == "quit":
            print("bye!")
            return


if __name__ == "__main__":
    asyncio.run(main())
