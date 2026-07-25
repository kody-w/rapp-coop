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
