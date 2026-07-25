# Prior Art Declaration — Memory-Mediated Agent Apprenticeship

**Defensive publication.**

| | |
|---|---|
| **Title** | Memory-Mediated Agent Apprenticeship with Cold-Session Graduation ("AI schooling") |
| **Author** | Kody Wildfeuer (GitHub: [@kody-w](https://github.com/kody-w)) |
| **First public disclosure** | 2026-07-25 |
| **Canonical location** | https://github.com/kody-w/rapp-coop |
| **Reference implementation** | This repository (MIT) |
| **This document** | Dedicated to the public domain under [CC0 1.0](#public-domain-dedication) |

> **Purpose.** This document exists to place the described system and method
> into the public record so that it remains freely practicable by anyone. It is
> published defensively: to establish prior art, not to reserve rights.
>
> This is a technical disclosure, not legal advice.

---

## Abstract

A method for training autonomous software agents using other autonomous
software agents, in which an experienced agent that has accumulated durable
memory from prior operational use instructs a newly instantiated agent through
ordinary conversational exchange; the newly instantiated agent decides for
itself which portions of the instruction to persist to long-term memory; and
the instructing agent thereafter **examines the new agent in a session
containing no conversational history**, so that only durably persisted memory
can supply an answer. Passing that examination is the objective criterion for
admitting the new agent to productive work. Failure produces a corrective
exchange which itself becomes durable memory, followed by re-examination.

The distinguishing element is the **cold-session examination as a graduation
gate**: an empirical, automatable test that separates knowledge an agent has
genuinely retained from text merely present in its context window.

## Technical field

Multi-agent software systems; large language model agents; agent memory and
retrieval; agent onboarding, evaluation, and orchestration; concurrent
human–agent collaboration.

## Background and problem

Two approaches dominate the practice of giving an agent operational knowledge,
and both are deficient:

1. **Static instruction documents.** Knowledge is written into files the agent
   re-reads on every run. The knowledge is authored by a human guessing what
   the agent will need; it is re-parsed at every invocation at recurring cost;
   it goes stale silently; it is identical for every agent regardless of role;
   and there is **no way to confirm the agent understood it.**

2. **Fine-tuning or weight modification.** Expensive, slow, requires
   specialized infrastructure, is difficult to correct incrementally, and
   cannot capture an operational lesson learned minutes earlier.

Neither approach lets knowledge earned by one agent *in the field* propagate to
the next agent. Each new agent starts naive. Operational lessons — the kind
learned only by an incident — are lost at the boundary between agent instances.

Separately, when several agents and humans work one shared system at once, they
collide (simultaneously mutating a shared resource) and act blindly (unaware of
each other's actions).

## Summary of the disclosure

A system comprising:

- a **neighborhood**: a shared coordination substrate providing (a) an
  append-only message stream addressed by a dense monotonic cursor, and (b)
  expiring exclusive leases over named shared resources;
- **participants** ("twins"), each being either a human or an autonomous agent,
  which interact with the neighborhood through **one interface of identical
  shape**, such that records produced by a human and by an agent are
  structurally indistinguishable;
- **agents possessing two memory faculties**: a *write* faculty invoked at the
  agent's own discretion to persist a selected item to durable storage, and a
  *read* faculty that injects persisted items into the agent's operative
  context automatically on each turn;

and a method comprising:

1. **Instantiating** ("hatching") a new agent possessing both memory faculties
   and an empty or minimal memory store;
2. **Instructing** the new agent conversationally, by a mentor that is either a
   human or an agent already holding accumulated memory, over the same
   interface used for all other participation;
3. **Self-curation**: the new agent selecting, of its own determination, which
   items to persist and in what form, rather than being loaded with a corpus
   fixed by the instructor;
4. **Cold-session examination**: initiating a session with the new agent
   containing no conversational history, and posing questions answerable only
   from persisted memory;
5. **Graduating** the new agent to productive participation on a satisfactory
   response, or, on an unsatisfactory response, delivering a correction which
   the agent persists and then repeating step 4;
6. **Field accumulation**: the graduated agent persisting further items learned
   during operation, thereby becoming eligible to act as mentor in step 2 for a
   subsequent agent — so that operational knowledge compounds across
   generations of agents rather than resetting.
7. **Recording**: capturing the foregoing as an ordered append-only event
   sequence bearing actor, subject, monotonic offset, and schema version, from
   which any viewpoint may afterwards be obtained by projection, and which
   remains readable as recorded detail increases over time.

## Detailed description

### Roles

- **Apprentice** — a newly instantiated agent, memory faculties present, memory
  store empty.
- **Mentor** — any participant holding accumulated memory. **A human mentor and
  an agent mentor are interchangeable**, because the interface shape is
  identical for both. This interchangeability is a deliberate property, not an
  incidental one: it permits a bootstrapping human to be replaced by a
  graduated agent without altering any mechanism.
- **Neighborhood** — the shared substrate in which mentors, apprentices, and
  working participants coexist concurrently.

### The cycle

```
   hatch ──▶ teach ──▶ [cold examination] ──▶ graduate ──▶ field work
              ▲                │                               │
              │                │ fail                          │ accumulates
              └── correct ◀────┘                               │ memory
              ▲                                                │
              └────────────── becomes a mentor ◀───────────────┘
```

### The graduation gate, stated precisely

An agent answering correctly *during* an instructional conversation demonstrates
nothing about retention: the instruction is still present in its context. The
examination is therefore performed under the condition:

> **conversational history = ∅**

Any correct answer must then have originated from the durable store by way of
the automatic read faculty. This yields a criterion that is:

- **objective** — it does not depend on the mentor's impression;
- **automatable** — it is an ordinary request with an empty history field;
- **falsifiable** — an agent that has not retained the material cannot pass;
- **cheap** — one additional exchange per subject.

A worked example from the reference implementation, in which an apprentice was
taught operational facts and then examined cold:

> **Examiner:** *"Fresh session, no history. If an agent looks alive but nothing
> changes, what do you check first? Answer from memory only."*
>
> **Apprentice:** *"…the first thing you should check is whether it's running
> with the `--dry-run` flag… That flag has since been removed, so this would be
> a primary debugging step."*

The apprentice had not been told to treat that fact as a diagnostic procedure.
It classified the lesson, stored it in the form it would later need, and
retrieved it with no conversational context — demonstrating retention rather
than recital.

### Correction as curriculum

Because instruction is ordinary conversation, correction is ordinary
conversation. A mentor's correction is persisted by the apprentice at the moment
it is understood, and is then re-verified cold. The remediation loop therefore
requires no separate mechanism, no retraining, and no redeployment.

### Concurrency

Schooling occurs inside a live neighborhood rather than in isolation. Apprentice
and mentor may work the same system during instruction because the substrate
provides expiring leases over shared resources. Leases rather than locks are
used specifically so that an agent failing mid-instruction cannot render a
resource permanently unavailable.

## Disclosed aspects

Enumerated for clarity of the record. These are descriptions of the disclosed
system and method, published to establish prior art. **They are not assertions
of any proprietary right.**

1. A method of training a software agent wherein a second software agent
   holding durable memory accumulated from prior operation acts as instructor.
2. The method of aspect 1, wherein instruction is conducted through natural
   conversational exchange over the same interface used by human participants.
3. The method of aspect 1, wherein the instructed agent determines for itself
   which portions of the instruction to persist, and in what form.
4. The method of aspect 1, further comprising examining the instructed agent in
   a session containing no conversational history, such that only persisted
   memory can supply a response.
5. The method of aspect 4, wherein the outcome of said examination is the
   criterion for admitting the agent to productive work.
6. The method of aspect 4, wherein an unsatisfactory response results in a
   corrective conversational exchange that is itself persisted, followed by
   repetition of the examination.
7. The method of aspect 1, wherein an agent having been admitted to productive
   work subsequently serves as instructor for a further agent, such that
   operational knowledge compounds across successive agent instances.
8. A system wherein human and agent participants transmit structurally
   identical records through a single interface, such that a participant need
   not determine whether its counterpart is human, and a human instructor may be
   substituted by an agent instructor without mechanism change.
9. The system of aspect 8, further comprising expiring exclusive leases over
   named shared resources, wherein a lease held by a failed participant becomes
   available upon expiry without administrative intervention.
10. The system of aspect 8, wherein the shared message stream is addressed by a
    dense monotonic cursor such that a restarting consumer can neither omit nor
    duplicate a record.
11. The system of aspect 8, wherein persisted memory is injected into the
    agent's operative context automatically on each turn, without the agent
    issuing a retrieval request.
12. The system of aspect 11, wherein memory is held in a shared store by
    default such that a newly instantiated agent inherits the accumulated
    knowledge of prior agents, and optionally partitioned by a globally unique
    tenant identifier where isolation between tenants is required.
13. A method of recording the training lifecycle of aspect 1 as an ordered
    append-only sequence of events, each event bearing an actor identifier, a
    subject identifier, a monotonic time offset, and a schema version, such
    that the lifecycle may afterwards be reproduced.
14. The method of aspect 13, wherein a viewpoint of the recorded lifecycle is
    obtained by projection over the single recorded sequence rather than by
    recording separately per viewpoint, such that viewpoints not contemplated
    at recording time may be derived subsequently.
15. The method of aspect 13, wherein a reader disregards event types it does
    not recognise and preserves record fields it does not recognise, such that
    later increases in recorded detail do not invalidate previously made
    recordings.
16. The method of aspect 13, wherein reproduction is paced by the recorded
    monotonic offsets, thereby preserving the original temporal structure of
    the session including intervals during which an agent was deliberating.
17. The method of aspect 13, wherein an event denoting an item committed to
    durable memory is derived from the agent runtime's record of tool
    invocation rather than from the agent's own natural-language assertion that
    it has done so.

## Alternative embodiments

The disclosure is not limited to the reference implementation. It is
independent of:

- **the model** — any conversational language model, local or hosted, any
  vendor;
- **the runtime** — any agent framework providing tool or function invocation;
- **the memory store** — file, embedded database, object store, vector store,
  or managed service; keyword, recency, or embedding retrieval;
- **the transport** — HTTP, message queue, shared filesystem, version control
  system, or peer-to-peer;
- **the coordination substrate** — any mechanism providing an ordered shared
  log and expiring exclusive leases;
- **the participants** — the mentor may be human or agent; the apprentice may
  be any agent possessing write and read memory faculties;
- **the domain** — the reference implementation governs a game server; the
  method is domain-independent and applies to any system on which multiple
  agents and humans operate concurrently.

Nothing in this disclosure depends on the RAPP or OpenRappter ecosystems. Those
are one embodiment. The method is intended to be implemented by anyone, on any
stack.

## Reference implementation

This repository. See [`README.md`](README.md) for the coordination substrate,
[`TEACHING.md`](TEACHING.md) for the instruction and examination procedure, and
[`BEST-PRACTICES.md`](BEST-PRACTICES.md) for operational findings. The
substrate is implemented in `src/rapp_coop/` with no runtime dependencies
beyond the Python standard library, and is covered by tests including an
invariant asserting that human-originated and agent-originated records remain
structurally identical.

## Public domain dedication

**To the extent possible under law, the author has dedicated all copyright and
related and neighboring rights in this document (`PRIOR-ART.md`) to the public
domain worldwide under [CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/).**

This document may be copied, modified, distributed, and republished, including
for commercial purposes, without permission.

The accompanying source code is licensed under the MIT License (see
[`LICENSE`](LICENSE)), which likewise permits unrestricted commercial use,
modification, and redistribution.

**The purpose of both dedications is identical: to ensure this method cannot be
enclosed by any party, including its author.**

## Establishing the disclosure date

The disclosure date is evidenced by the public commit history of this
repository, which is independently timestamped by GitHub and mirrored by anyone
who clones it. Parties wishing to strengthen the record are encouraged to
archive this document independently — for example via the Internet Archive, a
public defensive-publication registry, or a timestamping authority — and to
redistribute it freely.

## Citation

```
Wildfeuer, K. (2026). Memory-Mediated Agent Apprenticeship with Cold-Session
Graduation ("AI schooling"). Defensive publication.
https://github.com/kody-w/rapp-coop/blob/main/PRIOR-ART.md
```
