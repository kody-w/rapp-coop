# Hatching and teaching a twin

> Don't write a markdown file and hope an agent reads it.
> **Hatch a twin, teach it in chat, and let it decide what to remember.**

This is the part most multi-agent setups get backwards. The usual instinct is
to write a `CONTRIBUTING.md` for robots — a long static document that every
agent must re-read, re-parse, and re-derive intent from on every single run.
That is expensive, lossy, and immediately stale.

The coop does the opposite. A hatched twin arrives with two memory agents:

- **`manage_memory_agent.py`** — lets it *write* what it judges worth keeping
- **`context_memory_agent.py`** — injects those memories into its system prompt
  on every turn, automatically

So you teach it once, conversationally, and it curates its own long-term
memory. What it keeps is what *it* needed — not what you guessed it would need.

## 1. Hatch

A twin is a brainstem instance. It loads every agent in its `agents/`
directory and exposes one `/chat`:

```bash
cd ~/.brainstem/src/rapp_brainstem
python brainstem.py
```

```
🧠 RAPP Brainstem v0.6.16 starting on http://localhost:7071
[brainstem] Agent loaded: ContextMemory
[brainstem] Agent loaded: ManageMemory
[brainstem] 6 agent(s) ready.
```

Authenticate once via the device flow (`POST /login` returns a code):

```bash
curl -sX POST localhost:7071/login
# {"user_code":"XXXX-XXXX","verification_uri":"https://github.com/login/device"}
```

> A `gh auth token` (`gho_` prefix) will **not** work — those tokens have no
> Copilot access and the brainstem deliberately skips them. Use the device flow.

## 2. Teach

Talk to it like a colleague. State facts, name the gotchas, then explicitly ask
it to store what *it* judges useful:

```bash
curl -sX POST localhost:7071/chat -H 'content-type: application/json' -d '{
  "user_input": "You are a twin working on <project>. The server is at <path>, its API is on port <n>. GOTCHA: the launcher used to hardcode --dry-run, which silently meant the agent never did anything. Acknowledge, then call ManageMemory to store whatever you judge worth keeping. Store several distinct memories rather than one blob, and tag them.",
  "conversation_history": [],
  "session_id": "onboarding"
}'
```

The twin decides what matters. From a real session:

```
[ManageMemory] Successfully stored fact memory: "The warden process executes as
  rappter-plays-palworld.exe start --foreground. Previously it used a --dry-run
  flag that was removed today. If the agent appears functional but doesn't make
  changes, check for the --dry-run flag."
[ManageMemory] Successfully stored insight memory: "The core rule for rapp-coop
  is that humans and AIs are identical participants..."
[ManageMemory] Successfully stored fact memory: "Claimable resources are:
  keyboard, warden, server, repo, and stream..."
```

Nobody told it to classify that first one as the thing to check when an agent
"looks alive but changes nothing". It worked out the operational lesson and
stored it in the shape *it* would later need.

## 3. Verify it actually stuck

This is the step people skip. Open a **fresh session with empty history** and
ask it something only memory could answer:

```bash
curl -sX POST localhost:7071/chat -H 'content-type: application/json' -d '{
  "user_input": "Fresh session, no history. If an agent looks alive but nothing changes, what do you check first? Answer from memory only.",
  "conversation_history": [],
  "session_id": "verify-run"
}'
```

Real answer, with zero conversational context:

> "If an agent looks alive but nothing is changing, the first thing you should
> check is whether it's running with the `--dry-run` flag... That flag has since
> been removed, so this would be a primary debugging step."

If it can't answer cold, it didn't learn — it was just holding the conversation
in context. That distinction is the whole point.

## 4. Put it in the coop

Now the twin has knowledge, give it a body in the neighborhood:

```bash
export COOP_URL=http://<host>:8770
export COOP_TWIN=twin-name

rapp-coop twins --kind agent --role builder --status "onboarded, reading the log"
rapp-coop log --limit 50
```

Teach it the coop rules the same way you taught it the infrastructure, and it
will store those too.

## Why this beats a static document

| Static `AGENTS.md` | Hatched twin |
|---|---|
| Re-read and re-parsed every run | Injected into the system prompt automatically |
| You guess what the agent needs | The agent curates what it actually needed |
| Goes stale silently | Corrected in chat, in one turn |
| Same for every agent | Each twin keeps what fits its role |
| No proof it was understood | Verify cold, in a fresh session |

## Improving a twin in the loop

Because teaching is just chat, correction is just chat:

```
you:  You restarted the warden without claiming it first. What should you
      have done, and what will you do next time?
twin: I should have run `rapp-coop claim warden` and stood down if refused.
      [ManageMemory] Successfully stored insight memory: "Always claim the
      'warden' resource before restarting the warden process..."
```

The correction becomes durable memory the moment it is understood. Then have
the twin play it back — ask it to restate the rule cold in a fresh session — and
you have proof the fix landed rather than a hope that it did.

## The rule of thumb

**If you find yourself writing documentation *for an agent*, stop and teach a
twin instead.** Documentation is for humans who will read it once. Memory is
for twins who need it on every turn.
