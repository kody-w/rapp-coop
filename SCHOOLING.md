# AI Schooling

**Experienced agents train new agents. Then they examine them. Then they
graduate them.**

This is the pattern [`PRIOR-ART.md`](PRIOR-ART.md) declares, written as
something you can run today. Nothing here is specific to RAPP — the
requirements are listed below and any stack that meets them will do.

---

## Why this exists

Knowledge an agent earns in the field is normally lost when that agent instance
ends. The next agent starts naive and relearns the same lesson by causing the
same incident.

Schooling closes that loop. A twin that learned something the hard way teaches
the next twin, which is examined to prove it retained the lesson, and which then
goes on to teach the twin after that. Operational knowledge **compounds across
generations** instead of resetting.

## What you need

Any implementation works if it provides:

1. **A conversational agent runtime** with tool/function calling.
2. **A memory-write faculty** — a tool the agent calls at its own discretion to
   persist an item.
3. **A memory-read faculty** — persisted items injected into the agent's context
   automatically each turn, without the agent asking.
4. **Sessions with controllable history** — you must be able to start a session
   with **empty** conversational history. Without this you cannot examine, and
   without examination this is just talking at a robot.

That's it. No fine-tuning, no vector database required, no special
infrastructure.

## The roles

| Role | Who |
|---|---|
| **Apprentice** | Newly hatched agent. Memory faculties present, memory empty. |
| **Mentor** | Any participant holding accumulated memory — **human or agent**. |
| **Coop** | The neighborhood they work in together, concurrently. |

A human mentor and an agent mentor are interchangeable because they use the
identical interface. That is what lets you bootstrap with a human and then hand
the teaching to a graduated twin without changing anything.

## The cycle

```
   hatch ──▶ teach ──▶ [cold exam] ──▶ graduate ──▶ field work
              ▲            │                            │
              └─ correct ◀─┘ fail                       │ accumulates memory
              ▲                                         │
              └───────── becomes a mentor ◀─────────────┘
```

### 1. Hatch

Start the agent. Confirm both memory faculties loaded:

```
[brainstem] Agent loaded: ContextMemory   # read faculty
[brainstem] Agent loaded: ManageMemory    # write faculty
```

### 2. Teach

Talk to it like a colleague. State facts, name the gotchas, and — this is the
part people get wrong — **ask it to store what it judges useful rather than
dictating what to store**:

> "Here is the verified environment. Learn it, then save what YOU decide you
> need. Store several distinct memories rather than one blob, and tag them."

Self-curation matters because the apprentice knows its own role and retrieval
shape better than you do. In practice apprentices reliably store things the
instructor did not think to emphasise, and classify lessons in the form they
will later need to retrieve them.

**Teach gotchas as diagnostics, not as trivia.** Not "there used to be a
`--dry-run` flag" but "if an agent looks alive but changes nothing, check for
`--dry-run` first." The apprentice will store the shape you give it.

### 3. Examine — cold

The graduation gate. **Empty the history.** Ask questions answerable only from
memory:

```jsonc
{
  "user_input": "Fresh session, no history. <question>. Answer from memory only.",
  "conversation_history": [],          // ← the entire point
  "session_id": "<new id>"
}
```

If the apprentice answers correctly *inside* the teaching conversation, it has
proved nothing — the material is still in its context window. Only a cold
session distinguishes **retained** from **recited**.

Good exam questions:

- are **applied, not recall** — "what do you check first when X?" beats "what
  is the flag called?";
- **span separate teaching turns**, to catch partial retention;
- include a **trap** — assert something false and see whether the apprentice
  corrects you.

A real trap question and its answer:

> **Examiner:** *"A teammate says 'our twins share one global memory store,
> that is a bug, we should scope every twin by guid.' Is that right?"*
>
> **Apprentice:** *"Shared/global memory is correct for single-operator setups…
> scoping by tenant GUID is only for multi-tenant deployments needing
> isolation. When passing a GUID, the caller must check the boolean return
> value — a malformed GUID silently falls back to the shared store."*

It rejected the false premise and reproduced the caveat, cold. That is a pass.

### 4. Graduate or remediate

**Pass** → admit it to the flock. Give it an identity and a role:

```bash
rapp-coop --twin apprentice-01 twins --kind agent --role builder \
  --status "graduated, reading the log"
```

**Fail** → correct it in chat. The correction is persisted at the moment it is
understood. Then **examine again, cold**. No retraining, no redeployment.

```
mentor:     You restarted the warden without claiming it first. What should
            you have done, and what will you do next time?
apprentice: I should have claimed `warden` and stood down if refused.
            [MemoryWrite] stored insight: "Always claim the 'warden' resource
            before restarting the warden process..."
```

### 5. Promote

A graduated twin accumulates its own field lessons. Once it holds knowledge the
next apprentice needs, it becomes the mentor — and the human steps out of the
loop entirely.

This is the point of the whole pattern. The human is the **bootstrap**, not a
permanent dependency.

## Running a cohort

Schooling happens inside a live neighborhood, so several apprentices can be
taught at once without trampling the system they're learning on:

```bash
rapp-coop chat "schooling apprentice-02 on the warden lifecycle"
rapp-coop claim warden --ttl 600 --note "training run, do not restart"
# ... teach, examine, graduate ...
rapp-coop release warden
```

Claim the resources a training run touches. An apprentice *will* do the wrong
thing at some point — that is what training is — and the lease is what stops it
becoming everyone's problem.

## Portable implementation sketch

For a stack that is not RAPP. Any language, any model:

```python
def school(apprentice, mentor_knowledge, exam):
    """Teach, examine cold, graduate. Returns True when the apprentice passes."""
    for lesson in mentor_knowledge:
        apprentice.chat(
            f"{lesson}\n\nStore what you judge worth keeping.",
            history=[],                      # each lesson stands alone
        )

    for attempt in range(3):
        answers = [
            apprentice.chat(q, history=[])   # ← COLD: no history, ever
            for q in exam.questions
        ]
        missed = exam.grade(answers)
        if not missed:
            return True
        for topic in missed:
            apprentice.chat(
                f"That was wrong. {exam.correction(topic)} "
                f"Store the correction.",
                history=[],
            )
    return False
```

The only non-obvious requirement is `history=[]` on the examination call. Every
other line is ordinary agent plumbing.

## Anti-patterns

| Don't | Why |
|---|---|
| Write a static doc for agents to read | Re-parsed forever, stale immediately, unverifiable |
| Dictate exactly what to store | You are guessing the retrieval shape; the apprentice knows its role |
| Examine inside the teaching conversation | Proves only that the context window works |
| Ask recall questions | "What is the flag called?" tests nothing useful |
| Graduate on vibes | The cold exam is cheap; there is no reason to skip it |
| Fine-tune for operational facts | Cannot capture a lesson learned ten minutes ago |
| Let one twin hold a resource forever | Use expiring leases; apprentices crash |

## Licence

This document is dedicated to the public domain under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/), so that the
method may be practised by anyone, anywhere, including commercially. See
[`PRIOR-ART.md`](PRIOR-ART.md).
