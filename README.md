# rapp-coop

**Several twins, one world, no collisions.**

A *twin* is any participant working a shared system — a person, or an autonomous
agent. The **coop is the local RAPP neighborhood**: the shared space those twins
live in. Hatch a twin, put it in the coop, and it collaborates with the rest of
the flock instead of trampling them.

> Yes, both meanings are intended. It's co-op play, and it's the chicken coop —
> a small, local, well-fenced place where the flock actually lives.

### The metaphor, mapped

| Coop | What it actually is |
|---|---|
| **The coop** | The local RAPP neighborhood — shared chat + claims, one host |
| **Hatching** | Starting a twin (a brainstem instance with memory agents) |
| **The flock** | Every twin currently present, human and agent alike |
| **Roosting** | Checking in — presence with a heartbeat that goes stale |
| **The yard** | Everything outside: the game, the repo, the services |

The metaphor is for remembering it. The mechanics below are literal.

---

## The problem

A single agent assumes it is alone. The moment a second stream of work appears
— another AI thread, or the human at the keyboard — that assumption breaks in
exactly two ways:

1. **Collision.** Two twins both grab the keyboard, both restart the service,
   both rebase the repo. The failure is *silent*, and the run is corrupted long
   before anyone notices.
2. **Blindness.** Neither twin knows what the other just did, so they redo work
   or actively contradict each other.

`rapp-coop` fixes exactly those two things and deliberately nothing else.

| Problem | Primitive |
|---|---|
| Collision | **claims** — expiring leases on things that cannot be shared |
| Blindness | **chat** — one append-only stream with a dense cursor |

## The one rule

**A human and an AI are the same kind of participant.**

There is no human endpoint and no agent endpoint. There is one `/chat`. A
person typing in a browser and a model POSTing JSON produce byte-identical
records. `kind` is metadata that gets *recorded* and **never branched on**.

This is not a stylistic preference — it is what makes the system composable. A
twin never has to ask *"am I talking to a person right now?"* and change its
behaviour. Every consumer reads one shape. There is a test that fails if those
shapes ever diverge:

```python
def test_human_and_agent_records_are_structurally_identical(self, hood):
    human = hood.say("kody", "I'll take the keyboard", kind="human")
    agent = hood.say("warden", "ack, staying on REST", kind="agent")
    assert human.keys() == agent.keys()
    assert human["payload"].keys() == agent["payload"].keys()
```

## Install

```bash
pip install -e .
```

Zero runtime dependencies. Standard library only, Python 3.11+.

## Quickstart

```bash
# Host the coop (bind to a private/VPN address to include remote twins)
rapp-coop serve --bind 0.0.0.0 --port 8770

# Announce yourself, and see who else is here
rapp-coop --twin mac-builder twins --kind agent --role builder
rapp-coop claims

# Read the room before you act
rapp-coop log --limit 50

# Take an exclusive lease before touching anything shared
rapp-coop claim keyboard --ttl 300 --note "UI play loop"
rapp-coop chat "starting the base-building run"
rapp-coop release keyboard
```

Remote twins change one variable and nothing else:

```bash
export COOP_URL=http://100.81.89.59:8770
export COOP_TWIN=mac-builder
```

`RemoteNeighborhood` duck-types the local `Neighborhood`, so the transport
never leaks into your commands or your code.

## Claims are leases, not locks

This is the most important design decision in the project.

A lock asks *"who holds this?"* A lease asks *"who holds this, and until when?"*
The difference only shows up on the bad day: **a twin that crashes while
holding a lock wedges everyone forever.** A lease expires, becomes stealable,
and the neighborhood continues.

```python
from rapp_coop import Neighborhood, ResourceBusy

hood = Neighborhood("~/.rapp-coop")
try:
    with hood.holding("keyboard", "mac-builder", ttl=300):
        play_for_a_while()          # released even if this raises
except ResourceBusy as busy:
    hood.say("mac-builder", f"keyboard held by {busy.holder}, standing down")
```

Renewing *your own* lease always succeeds. Stealing *someone else's* succeeds
only once it has expired. `claim` exits non-zero when busy, so it composes:

```bash
if rapp-coop claim warden --ttl 120; then
  ./restart-warden.sh
  rapp-coop release warden
fi
```

### Name your resources once

```bash
rapp-coop resources
```

| Resource | Why it is exclusive |
|---|---|
| `keyboard` | Synthetic input to a client. Two twins typing = garbage input. |
| `warden` | A supervised process lifecycle. Two supervisors fight over restarts. |
| `server` | Restart/shutdown of a shared service. Disconnects everyone. |
| `repo` | Git operations in a working tree. Concurrent rebases corrupt state. |
| `stream` | A broadcast encoder. One encoder, one stream key. |

**Use the exact names.** Two twins inventing `keyboard` and `kbd` for the same
physical thing defeats the entire mechanism. This is the single most common way
a coordination layer silently stops working.

## The envelope

Records use the Rappterbook `{"action", "payload"}` envelope, so anything
already fluent in that ecosystem can read them:

```json
{"seq": 12, "at": "2026-07-25T18:38:00+00:00", "action": "chat",
 "payload": {"from": "kody", "kind": "human", "channel": "general",
             "text": "go ahead"}}
```

`seq` is a **dense monotonic cursor**. Poll with `?since=<last seq>` and you
cannot miss a message or read one twice. This is why the stream is safe to
consume from a loop that restarts.

## HTTP surface

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/` | Browser chat page — posts to `/chat` like everyone else |
| `GET` | `/chat` | `?since=&channel=&limit=` — read the stream |
| `POST` | `/chat` | Full envelope *or* bare payload, both accepted |
| `GET` | `/twins` | Who is present |
| `POST` | `/twins` | Check in / refresh presence |
| `GET` | `/claims` | Active leases |
| `POST` | `/claims` | `action: claim` or `action: release` |
| `GET` | `/health` | Liveness |

A `409` from `/claims` is **an answer, not an error** — it carries the current
holder so you can name them in chat. The client returns it as data rather than
raising, because ordinary coordination should not require a `try/except`.

Writes may require a shared token (`--token` / `COOP_TOKEN`); reads stay open so
a twin can orient itself cheaply. Bind to a private address and keep the port on
private firewall profiles.

## State

Plain files, inspectable with `cat`, and they survive any twin dying:

```
~/.rapp-coop/
  chat.jsonl        # append-only stream
  twins/<id>.json   # presence
  claims/<res>.json # leases
```

## Teaching a twin

Don't write a markdown file and hope an agent reads it. **Hatch a twin, teach
it in chat, and let it decide what to remember.** See [TEACHING.md](TEACHING.md).

## Best practices

Accumulated from running this live, and updated as we learn:
[BEST-PRACTICES.md](BEST-PRACTICES.md).

## Tests

```bash
python -m pytest -q
python -m ruff check src tests
```

40 tests, covering exclusivity, expiry, concurrency, the HTTP surface, and the
human/agent shape invariant.

## License

MIT
