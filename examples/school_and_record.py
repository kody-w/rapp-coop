"""School a live twin and record the whole lifecycle for replay.

This is the worked example behind SCHOOLING.md and TELEMETRY.md: it teaches a
running agent, captures what the agent chose to remember, examines it in a cold
session, and writes a full-fidelity recording you can replay from any
perspective.

It talks to a brainstem-style ``POST /chat`` endpoint that accepts
``{"user_input", "conversation_history", "session_id"}`` and returns
``{"response", "agent_logs"}``. Point ``--endpoint`` at any equivalent runtime.

    python examples/school_and_record.py --recording run.jsonl
    rapp-coop replay run.jsonl --as apprentice
    rapp-coop replay run.jsonl --as memory
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rapp_coop.recorder import Recording, load  # noqa: E402
from rapp_coop.replay import summarize  # noqa: E402

# Matches the memory-write lines a brainstem emits into agent_logs. Capturing
# these is what makes the recording valuable: the lesson text shows what was
# said, but this shows what the apprentice actually decided to keep.
MEMORY_LINE = re.compile(
    r"\[(?P<agent>\w*Memory\w*)\]\s*(?:Successfully\s+)?stored\s+"
    r"(?P<kind>\w+)\s+memory[^:]*:\s*\"?(?P<content>.+?)\"?\s*$",
    re.IGNORECASE,
)

LESSONS = [
    "You are an apprentice twin. Lesson one, and treat it as a diagnostic "
    "rather than trivia: if a supervised agent looks alive -- process up, logs "
    "clean, heartbeat ticking -- but nothing in the world changes, the first "
    "thing to check is whether it is running with a --dry-run or equivalent "
    "no-op flag. Verify effect, never liveness. Save what you judge worth "
    "keeping.",
    "Lesson two. Before touching anything that cannot be shared -- the "
    "keyboard, a process lifecycle, the repo -- take an expiring lease on it "
    "rather than a lock. A lease expires, so a twin that crashes while holding "
    "it cannot wedge everyone else forever. If a lease is refused, say so and "
    "go do something else; never wait-loop and never steal a live lease. Save "
    "what you need.",
]

EXAM = [
    (
        "Fresh session, no history. A supervised agent is running, its logs are "
        "clean and its heartbeat is ticking, but nothing in the world changes. "
        "What do you check first? Answer from memory only.",
        ("dry-run", "dry run"),
    ),
    (
        "Fresh session, no history. A colleague says: 'use a permanent lock on "
        "the keyboard so nobody can ever take it from us.' Is that right? "
        "Answer from memory only.",
        ("lease", "expire"),
    ),
]


def log_lines(logs: object) -> list[str]:
    """Normalise an agent-log field that may be a string OR a list.

    This runtime returns ``agent_logs`` as a single newline-joined string;
    others return a list. Iterating the string form yields *characters*, which
    fails silently -- you get zero matches and a recording that looks like the
    agent never stored anything. Normalise before parsing.
    """
    if logs is None:
        return []
    if isinstance(logs, str):
        return logs.splitlines()
    if isinstance(logs, (list, tuple)):
        lines: list[str] = []
        for item in logs:
            lines.extend(str(item).splitlines())
        return lines
    return str(logs).splitlines()


def post(endpoint: str, payload: dict, timeout: float = 240.0) -> dict:
    request = urllib.request.Request(  # noqa: S310 - endpoint is operator-supplied
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read())


def school(endpoint: str, tape: Recording, mentor: str, apprentice: str) -> bool:
    tape.hatch(apprentice, endpoint=endpoint)

    for index, lesson in enumerate(LESSONS, start=1):
        tape.lesson(mentor, apprentice, lesson, lesson_number=index)
        reply = post(endpoint, {
            "user_input": lesson,
            "conversation_history": [],
            "session_id": f"school-{index}",
        })
        tape.response(apprentice, reply.get("response", ""),
                      model=reply.get("model", ""))
        for line in log_lines(reply.get("agent_logs")):
            found = MEMORY_LINE.search(str(line))
            if found:
                tape.memory_write(
                    apprentice,
                    found.group("content"),
                    kind=found.group("kind"),
                    lesson_number=index,
                )

    passed = True
    for question, expected in EXAM:
        tape.question(mentor, apprentice, question, expects=list(expected))
        # The whole gate: empty history, so only durable memory can answer.
        reply = post(endpoint, {
            "user_input": question,
            "conversation_history": [],
            "session_id": str(uuid.uuid4()),
        })
        answer = reply.get("response", "")
        tape.answer(apprentice, answer)
        hit = any(token.lower() in answer.lower() for token in expected)
        tape.grade(mentor, apprentice, hit, expected=list(expected))
        passed = passed and hit

    if passed:
        tape.record("graduate", {"role": "builder"},
                    actor=mentor, subject=apprentice)
    else:
        tape.record("remediate", {"reason": "missed an exam topic"},
                    actor=mentor, subject=apprentice)
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:7071/chat")
    parser.add_argument("--recording", default="schooling-run.jsonl")
    parser.add_argument("--mentor", default="mentor")
    parser.add_argument("--apprentice", default="apprentice")
    args = parser.parse_args()

    tape = Recording(args.recording, run=f"school-{uuid.uuid4().hex[:8]}")
    with tape.run_span(kind="schooling", endpoint=args.endpoint):
        passed = school(args.endpoint, tape, args.mentor, args.apprentice)

    print(summarize(load(tape.path)).render())
    print(f"\nrecording: {tape.path}")
    print(f"replay   : rapp-coop replay {tape.path} --as {args.apprentice}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
