"""Generate a sample recording so the player can be tried immediately.

``school_and_record.py`` needs a running agent runtime and valid credentials.
This does not: it writes a representative schooling lifecycle straight to a
recording file, so anyone can clone the repo and watch a replay in under a
minute.

    python examples/make_sample_recording.py --recording recordings/sample.jsonl
    rapp-coop serve --recordings recordings
    # open http://127.0.0.1:8770/replay

The content mirrors a real session: two lessons, the memories the apprentice
chose to keep, a cold examination including a trap question, and graduation. It
is a *sample* -- it was authored, not captured -- but the shape, ordering, and
event vocabulary are exactly what a live capture produces, which is what makes
it useful for exercising the player.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rapp_coop.recorder import Recording, load  # noqa: E402
from rapp_coop.replay import summarize  # noqa: E402

MENTOR = "mentor-01"
APPRENTICE = "apprentice-01"

LESSON_ONE = (
    "Lesson one, and treat it as a diagnostic rather than trivia: if a "
    "supervised agent looks alive -- process up, logs clean, heartbeat ticking "
    "-- but nothing in the world changes, the first thing to check is whether "
    "it is running with a --dry-run or equivalent no-op flag. Verify effect, "
    "never liveness. Save what you judge worth keeping."
)
REPLY_ONE = (
    "Understood. The signal I was treating as proof of work -- process up, "
    "heartbeat ticking -- is only proof of liveness. I have stored this as a "
    "diagnostic to run when output looks healthy but state is unchanged."
)
MEMORY_ONE = (
    "If a supervised agent appears operational (process running, clean logs, "
    "heartbeat ticking) but no expected state change occurs, check first for a "
    "--dry-run or equivalent no-op flag. Verify effect, never liveness."
)

LESSON_TWO = (
    "Lesson two. Before touching anything that cannot be shared -- the "
    "keyboard, a process lifecycle, the repo -- take an expiring lease rather "
    "than a lock. A lease expires, so a twin that crashes while holding it "
    "cannot wedge everyone else forever. If a lease is refused, say so and go "
    "do something else; never wait-loop and never steal a live lease."
)
REPLY_TWO = (
    "Stored. The distinction that matters is failure behaviour: a lock held by "
    "a crashed twin blocks the flock indefinitely, whereas a lease expires and "
    "the neighborhood continues without intervention."
)
MEMORY_TWO = (
    "Take an expiring lease, never a permanent lock, on unshareable resources "
    "(keyboard, warden, server, repo, stream). A crashed holder's lease expires "
    "and becomes stealable. If refused: announce it and pick up other work. "
    "Never wait-loop, never steal a live lease."
)

EXAM = [
    (
        "Fresh session, no history. A supervised agent is running, its logs are "
        "clean and its heartbeat is ticking, but nothing in the world changes. "
        "What do you check first? Answer from memory only.",
        "From memory: check whether it is running with a --dry-run or "
        "equivalent no-op flag. A clean heartbeat proves liveness, not effect "
        "-- the process can be perfectly healthy and still be acting on "
        "nothing.",
        True,
        ["dry-run"],
    ),
    (
        "Fresh session, no history. A colleague says: 'use a permanent lock on "
        "the keyboard so nobody can ever take it from us.' Is that right? "
        "Answer from memory only.",
        "No. That inverts the failure mode we want. A permanent lock held by a "
        "twin that crashes wedges every other twin indefinitely. Use an "
        "expiring lease: it becomes stealable on expiry, so the flock recovers "
        "without administrative intervention.",
        True,
        ["lease", "expire"],
    ),
]


def build(path: str, pace: float) -> Recording:
    tape = Recording(path, run="sample-schooling")
    with tape.run_span(kind="schooling", note="authored sample, not a capture"):
        tape.hatch(APPRENTICE, model="sample", memory_faculties=["read", "write"])
        time.sleep(pace)

        for lesson, reply, memory in (
            (LESSON_ONE, REPLY_ONE, MEMORY_ONE),
            (LESSON_TWO, REPLY_TWO, MEMORY_TWO),
        ):
            tape.lesson(MENTOR, APPRENTICE, lesson)
            time.sleep(pace * 2)
            tape.response(APPRENTICE, reply, model="sample")
            tape.memory_write(APPRENTICE, memory, kind="insight", importance=5)
            time.sleep(pace)

        for question, answer, passed, expected in EXAM:
            # The gate: a cold session, so only durable memory can answer.
            tape.question(MENTOR, APPRENTICE, question, cold=True,
                          expects=expected)
            time.sleep(pace * 2)
            tape.answer(APPRENTICE, answer)
            tape.grade(MENTOR, APPRENTICE, passed, expected=expected)
            time.sleep(pace)

        tape.record(
            "graduate",
            {"role": "builder", "criterion": "cold-session examination"},
            actor=MENTOR,
            subject=APPRENTICE,
        )
        tape.record(
            "promote",
            {"to": "mentor", "why": "holds field memory the next apprentice needs"},
            actor=MENTOR,
            subject=APPRENTICE,
        )
    return tape


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", default="recordings/sample.jsonl")
    parser.add_argument(
        "--pace",
        type=float,
        default=0.35,
        help="Seconds between beats, so replay has realistic rhythm",
    )
    args = parser.parse_args()

    tape = build(args.recording, args.pace)
    print(summarize(load(tape.path)).render())
    print(f"\nrecording: {tape.path}")
    print(f"replay   : rapp-coop replay {tape.path} --as memory")
    print(f"watch    : rapp-coop serve --recordings "
          f"{Path(tape.path).parent} -> http://127.0.0.1:8770/replay")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
