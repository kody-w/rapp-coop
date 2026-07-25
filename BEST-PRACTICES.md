# Best practices

A living document. Every entry here was learned by running this for real, not
by reasoning about it in the abstract. Entries get added as the loop teaches us
more.

---

## Coordination

### Claim before you act, not while you act

Read the room first: `rapp-coop log`, then `rapp-coop twins`. Most collisions
are two twins independently deciding to fix the same thing at the same time.

### Announce intent, not completion

> "restarting the warden" lets another twin stand down.
> "restarted the warden" only explains the damage.

A twin that narrates in the past tense is generating an incident report. A twin
that narrates in the future tense is coordinating.

### If a claim is refused, go do something else

Do not wait-loop on a busy resource, and never steal a live lease. Say so in
chat — naming the current holder — and pick up different work. Wait-loops
convert a clean "someone else has it" into a stall that looks like a hang.

### Use leases, never locks

A lock asks *who holds this*. A lease asks *who holds this, and until when*.
The difference only matters on the bad day, which is exactly when you need it:
a twin that crashes holding a **lock** wedges everyone forever. A **lease**
expires and the flock continues.

Corollary: renew long work. A 120-second lease during a 20-minute build will
expire and another twin will legitimately take it. Re-claiming your own lease
always succeeds, so renew on a timer or set a realistic `--ttl`.

### Name shared resources exactly once, centrally

Two twins inventing `keyboard` and `kbd` for the same physical thing defeats
the whole mechanism — and it fails *silently*, because both claims succeed.
Keep the canonical list in one place (`rapp-coop resources`) and never invent
synonyms locally. This is the most common way a coordination layer quietly
stops coordinating.

### Release in a `finally`

Use the context manager. It releases even when the body raises, which is the
only case that actually matters:

```python
with hood.holding("keyboard", me, ttl=300):
    play_for_a_while()
```

---

## Protocol design

### One shape for humans and agents

There must be no human endpoint and no agent endpoint. `kind` is metadata that
is *recorded* and **never branched on**. The moment the shapes diverge you have
two protocols, and every consumer has to branch forever.

Pin it with a test that fails if the shapes drift apart — prose will not hold
this line.

### A refusal is data, not an exception

`409 Conflict` from a claim is the answer the caller asked for, and it carries
the current holder. Return it as a value. If ordinary coordination requires a
`try/except` at every call site, people will skip the coordination.

We shipped this bug first: the remote client raised on 409, so a perfectly
normal "someone else has the keyboard" blew up the caller.

### Give the stream a dense monotonic cursor

`seq` increments by exactly one, so `?since=<last seq>` cannot miss a message
or read one twice. This is what makes a consumer safe to restart — and
consumers restart constantly.

### Make the transport invisible

`RemoteNeighborhood` duck-types `Neighborhood`. Local files and a remote server
run identical call sites; only the constructor differs. If twins must write
transport-specific code just to coordinate, they will write it wrong or not at
all.

---

## Operating agents

### Verify effect, never liveness

**The single most expensive bug of the whole build.** A launcher hardcoded
`--dry-run`. The process was up, the logs were clean, the heartbeat ticked
every ten seconds, the event file grew — and the agent had never once acted on
the world.

"Is the process running?" is not the question. The questions are:

- Did the state I expect to change actually change?
- Is there a `--dry-run`, `--check`, `--what-if`, or sandbox flag in the path?
- Is a `changes: 0` counter telling me something I'm reading as noise?

### A backgrounded child dies with its parent shell

Spawning a "daemon" from a transient shell and reporting success is a lie that
survives exactly as long as the shell does. We hit this: the warden reported
`Warden online.` and exited 0, and the process was gone moments later.

Always confirm persistence *after* the launching shell is gone: check the PID,
and check that its side effects are still accumulating.

### Verify memory cold, in a fresh session

An agent answering correctly *within* a conversation proves nothing — it is
reading its own context window. Open a new session with **empty history** and
ask again. If it can't answer cold, it didn't learn.

### Teach twins; don't write documentation for them

A hatched twin curates its own memory through `ManageMemory`, and
`ContextMemory` injects it every turn. Teaching is one conversation; a static
`AGENTS.md` is re-parsed forever and stale immediately. See
[TEACHING.md](TEACHING.md).

### Correct in chat, then make the twin play it back

A correction becomes durable the moment the twin stores it. Ask it to restate
the rule cold afterwards — that is the difference between a fix that landed and
a fix you hope landed.

---

## Memory and multi-tenancy

### Global memory is the correct default

A twin's memories live in one shared store unless you say otherwise. That is
the right default for a single operator running a flock on their own hardware:
every twin you hatch inherits the accumulated operational knowledge instead of
relearning it. Shared memory is a feature, not a leak.

Don't reach for per-user scoping because it feels tidier. Reach for it when you
have actual tenants.

### `guid` is for tenant isolation, not for tidiness

Scoping exists for a **globally deployed brainstem serving many tenants** —
where every user carries a stable directory identity (an M365 account ID, for
example). Passing that ID as the memory `guid` gives each user a private store:

```
shared_memories/memory.json      # the default: one flock, one brain
memory/<guid>/user_memory.json   # one tenant, isolated
```

Because the identifier is a strict GUID, overlap between two tenants is not
merely unlikely — it is structurally impossible. That property is the whole
reason to use a GUID rather than a username, an email, or a slug.

The strict format is doing double duty: it also guarantees a **single safe path
component**, so a traversal attempt like `a/../b` cannot escape into another
tenant's directory.

### A malformed tenant ID fails *open*, and does it silently

This is the sharp edge. Setting the memory context with anything that is not a
strict GUID does not raise — it **falls back to the shared store and returns
`False`**:

```python
ok = storage.set_memory_context(tenant_id)
if not ok:
    # tenant_id was malformed; you are now writing to GLOBAL memory
    raise RuntimeError(f"refusing to serve tenant with unusable id")
```

Never raising is the right call for a single-operator box, where a bad id
should degrade to shared rather than crash the twin. But in a multi-tenant
deployment the same behaviour writes one customer's memories into the store
every other customer reads.

**Check the boolean.** The failure is silent by design, so the caller is the
only thing standing between a typo'd tenant id and a cross-tenant leak.

### There is a reserved marker GUID

A specific well-known GUID is treated as "no tenant" and routes to shared
memory deliberately. Don't hand it out as a real tenant identifier.

---

## Telemetry and replay

### Record the events, not a summary

A summary answers the question you thought to ask while recording. The event
log answers questions you think of later. Record `actor`, `subject`, and
ordering, and any perspective can be reconstructed afterwards — including ones
nobody has considered yet.

### One log, projections for viewpoints

Never write a per-participant recording. The moment you record from a viewpoint
you have decided whose story matters, and you have decided it at the worst
possible time — before anything interesting has happened.

### Version every event and preserve unknown fields

Readers must ignore unknown event types and keep unknown keys rather than
dropping them. This is what makes fidelity *additive*: you can capture token
counts, latencies, prompts, or frames next month without invalidating a single
recording made today. Test it, or it will quietly stop being true.

### Pace replays on monotonic offsets

Wall clocks jump; they are for humans reading transcripts, not for playback.
Capture a monotonic offset at record time. The pause while a model was thinking
is data — often the most informative part of the run — and only a monotonic
clock reproduces it faithfully.

### Redact at write time, never after

A recording exists to be shared, so it must never be the thing that leaks a
credential. Strip secrets before serialising the line: a secret removed later
has still been written to disk, and probably to a backup.

Watch the word boundary. A pattern like `\bpassword\s*=` will not match
`AdminPassword=`, `api_token=`, or `CLIENT_SECRET=` — which are precisely the
forms that leak. Drop the `\b`.

### Capture what the agent did, not what it said

An agent will write *"I've saved that insight"* whether or not it called the
tool. That sentence is not evidence; the tool-call record is. Derive
`memory.write` events from the runtime's tool log, and if you can, reconcile
against the store itself.

### A field that is sometimes a string and sometimes a list will bite you

Some runtimes return an agent-log field as a newline-joined **string**, others
as a **list**. Iterating the string form in Python yields *individual
characters*, so every parse fails — silently, with zero matches and no error.

We shipped exactly this bug: the first live recording reported `memories kept:
0` while the memory store had grown from 23 to 25 entries. Normalise
string-or-list fields at the boundary, and **cross-check a count against ground
truth** rather than trusting a clean-looking zero.




---

## Cross-platform

### `O_CREAT | O_EXCL` raises `PermissionError` on Windows

The portable exclusive-create idiom does **not** raise `FileExistsError`
consistently. On Windows, when the lock file is mid-deletion by its previous
holder, you get `PermissionError` instead. Catch both or a contending thread
dies:

```python
except (FileExistsError, PermissionError):
    # Both mean "someone else has it" — retry.
```

Found by a concurrency test, not by review. Write the contended test.

### Reclaim locks older than the timeout

A process that dies holding a lock file leaves it behind forever. Treat a lock
whose mtime exceeds the timeout as abandoned and take it — same reasoning as
leases, one level down.

### `Set-Content -Encoding utf8` writes a BOM on Windows PowerShell 5.1

Rewriting a config file from PowerShell with `-Encoding utf8` prepends a
byte-order mark. Parsers that are strict about the first byte — TOML readers
among them — then fail with a baffling *"Invalid statement at line 1, column
1"*, on a file that looks perfect in every editor.

We hit this bumping a version string in `pyproject.toml`. Use
`[System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))`,
or PowerShell 7's `-Encoding utf8NoBOM`. When a file parses as broken but reads
as fine, check the first three bytes for `EF BB BF`.

### `gh auth token` is not a Copilot token

Tokens from `gh` carry a `gho_` prefix and have no Copilot access. Tooling that
needs Copilot must use the device-code flow and will deliberately skip the `gh`
token. Don't debug this as an auth misconfiguration.

---

## Security

### Reads open, writes tokened

A twin should be able to orient itself cheaply — let it read the log and the
roster without a credential. Gate the writes.

### Bind to the private network, and scope the firewall to named peers

Bind the coop to the VPN/tailnet address and restrict the port to specific peer
addresses on private profiles only. A coordination bus is a control plane;
treat it like one.

### Validate the scheme before you open a URL

A configurable endpoint that reaches `urlopen` unchecked will happily accept
`file://`. Constrain to `http`/`https` at construction time — where the error
message can still be useful — rather than suppressing the linter at the call.

### Never echo secrets while automating

Read the admin password out of its config file at point of use and pass it
onward. Don't print it, don't paste it into chat, don't bake it into a repo.
Same rule for twins: tell them the password *exists and where*, never what it
is.
