# Telemetry exhaust

**Record the learning once. Replay it from any perspective, forever.**

Schooling is the interesting part of this system and it is normally invisible.
A twin gets taught, decides what to keep, is examined cold, and graduates — and
all that survives is a memory file and a pass/fail. The ordering, the timing,
the exact moment a lesson landed: gone.

This records it. Not a summary — the events themselves, in order, with timing.

```bash
python examples/school_and_record.py --recording run.jsonl

rapp-coop replay run.jsonl --views
rapp-coop replay run.jsonl --as observer
rapp-coop replay run.jsonl --as memory
rapp-coop replay run.jsonl --as exam
rapp-coop replay run.jsonl --as apprentice-01 --speed 1.0
rapp-coop replay run.jsonl --transcript --as apprentice-01
rapp-coop replay run.jsonl --summary
```

## Three decisions carry the whole design

### 1. One log, many perspectives

There is no mentor recording and no apprentice recording. There is **one
append-only event log**, and a perspective is a *projection* over it.

Recording per-viewpoint would force you to decide, while recording, whose story
matters — and you would be wrong. Every event carries `actor` and `subject`,
which is enough to reconstruct any viewpoint afterwards, **including viewpoints
nobody has thought of yet**.

| Perspective | Shows |
|---|---|
| `observer` | Everything, in order — the neutral account |
| `<twin id>` | What that participant said, was told, and did |
| `memory` | Only what was learned — the curve, talking removed |
| `exam` | Only the graduation gate |

A projection can never invent an event, and every projection keeps the run
boundaries — both are enforced by tests.

### 2. Fidelity is additive, never breaking

Every event carries a schema version and an open payload. Readers **ignore
unknown actions and preserve unknown keys**:

```json
{"seq": 1, "action": "neuron.spike", "v": 99, "gpu_temp": 71,
 "payload": {"text": "hello from later"}}
```

An unrecognised action still loads, still renders, still replays. An unknown
top-level key is preserved as `_gpu_temp` rather than dropped.

This is what lets you add richer capture later — token counts, latency, the
full system prompt, a memory diff, screen frames — **without invalidating a
single existing recording.** Recordings made today must still play in a year.
That property is tested, not merely intended.

### 3. Monotonic offsets, not wall clocks

Wall time is for humans reading a transcript. It jumps, and it cannot be
trusted for pacing. Replay paces on a monotonic offset captured at record time,
so playback preserves the real rhythm of a session — **including the long pause
while a model was thinking**, which is often the most informative part of a run.

```bash
rapp-coop replay run.jsonl --speed 1.0   # real time
rapp-coop replay run.jsonl --speed 4.0   # four times faster
rapp-coop replay run.jsonl               # instant (default)
```

Long gaps are capped by `--max-gap` so one slow call cannot stall a replay.

## Watch it in a browser

The CLI replay is for developers. The player is for everyone else:

```bash
python examples/make_sample_recording.py     # no credentials needed
rapp-coop serve --recordings recordings
# open http://127.0.0.1:8770/replay
```

Pick a recording, pick a perspective, press play. Space toggles play/pause,
arrow keys step one event at a time, and the scrubber seeks anywhere in the
run. Selecting an event shows its **complete, untruncated** payload — including
keys the player has never heard of.

The player is deliberately a *projection client*. The server hands it the raw
event log and all perspective filtering happens in the browser. Two
consequences, both intentional:

- switching perspective is instant and never re-reads the file;
- **the server never has to know what perspectives exist**, so a viewpoint
  invented later is a change to one file, not a protocol change.

| Route | Purpose |
|---|---|
| `GET /replay` | The player page |
| `GET /recordings` | Available recordings, newest first |
| `GET /recording?name=<file>` | One recording's events as JSON |

A recording name arrives from the network, so it is treated as hostile: only a
bare `*.jsonl` filename is accepted. Anything containing a separator or a
parent reference is **refused rather than resolved**, so a crafted name cannot
escape the recordings directory.

## The event envelope

A superset of the coop chat record — a chat message and a telemetry event are
the same shape with more context attached:

```json
{
  "seq": 5, "at": "2026-07-25T19:31:02.114+00:00", "mono": 4.33, "v": 1,
  "run": "school-e08721e2",
  "action": "memory.write",
  "actor": "apprentice-01", "subject": "",
  "payload": {"content": "If a supervised agent appears operational but...",
              "kind": "insight", "lesson_number": 1}
}
```

### Core vocabulary

`run.start` `run.end` `twin.hatch` `lesson.deliver` `agent.response`
`memory.inject` `memory.write` `exam.question` `exam.answer` `exam.grade`
`graduate` `remediate` `promote` `chat` `claim.acquire` `claim.release` `note`

This is documentation, **not a closed enum**. Emit your own; readers tolerate
them.

## Secrets never reach disk

A recording is meant to be shared — that is the entire point — so it must never
be the thing that leaks a credential. Redaction happens at **write** time,
because a secret removed later has still been written to a file.

Tokens, keys, JWTs, and `key = value` credential pairs are stripped before the
line is serialised. Note that the pattern deliberately has **no word boundary**
before the keyword: real config keys are compounds like `AdminPassword`,
`api_token`, `CLIENT_SECRET` — exactly the ones that leak.

```python
Recording(path, redact_secrets=False)   # opt out for a private recording
```

## Recording your own runs

```python
from rapp_coop import Recording

tape = Recording("run.jsonl", run="cohort-7")
with tape.run_span(kind="schooling"):
    tape.hatch("apprentice-01", model="your-model")
    tape.lesson("mentor", "apprentice-01", lesson_text)
    tape.response("apprentice-01", reply)
    tape.memory_write("apprentice-01", what_it_chose_to_keep)
    tape.question("mentor", "apprentice-01", question)
    tape.answer("apprentice-01", answer)
    tape.grade("mentor", "apprentice-01", passed=True)
```

`run_span` records `run.end` even when the body raises — a crashed run is still
a recording, and usually the one you most want to replay.

Sequence numbers resume across process restarts, so appending to an existing
recording continues the numbering rather than colliding.

## Capture what the agent *did*, not what it *said*

The single most valuable event is `memory.write`: what the apprentice actually
chose to keep. Take it from the runtime's tool-call log, never from the agent's
prose.

An agent will happily write *"I've saved that insight"* in its response. That
sentence is not evidence. The tool-call record is.

> **Gotcha, found the hard way.** Some runtimes return their agent-log field as
> a **newline-joined string**, others as a **list**. Iterating the string form
> in Python yields *individual characters* — so every match fails, silently, and
> you get a recording that looks like the agent never learned anything. The
> first live run here reported `memories kept: 0` while the memory store had in
> fact grown from 23 to 25. Normalise the field before parsing it.

## Adding fidelity later

The schema is designed to grow. Candidates, in rough order of value:

| Capture | Why |
|---|---|
| `memory.inject` | What the read faculty actually put in context that turn |
| token counts, latency | Cost and pacing per exchange |
| model id, sampling params | Reproducibility across model changes |
| system prompt snapshot | The single biggest hidden variable |
| memory-store diff | Ground truth vs. what the agent claimed |
| screen frames / audio | Full-fidelity playback for embodied twins |

Add them as new actions or new payload keys. Old recordings keep playing; old
readers keep working. **That is the point of the version field.**

## Licence

Dedicated to the public domain under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/), like the rest of
the pattern. See [`PRIOR-ART.md`](PRIOR-ART.md).
