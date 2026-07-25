"""Replay a recorded lifecycle from any perspective.

A *perspective* is a projection over the one true log -- never a separate
recording. This is what makes "any perspective" achievable rather than
aspirational: you do not have to know whose viewpoint mattered while you were
recording, and you can invent a new viewpoint years later and apply it to
recordings made today.

Four projections ship here, and they are only functions over events:

``observer``    everything, in order -- the neutral account
``<twin id>``   what that participant said, was told, and did
``memory``      only what was learned -- the curve, with the talking removed
``exam``        only the graduation gate -- questions, answers, verdicts

Pacing replays on the recorded monotonic offsets, so the rhythm of a session is
preserved: the pause while a model was thinking is data, not dead air. Long
gaps are capped so a replay stays watchable.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Sequence

from .recorder import Event, actors, load

# Events that describe the run itself belong in every perspective -- without
# them an actor's view has no beginning or end.
_GLOBAL = {"run.start", "run.end", "note"}
_MEMORY = {"memory.write", "memory.inject", "twin.hatch", "graduate", "promote"}
_EXAM = {"exam.question", "exam.answer", "exam.grade", "graduate", "remediate"}


def perspective(
    events: Sequence[Event],
    view: str = "observer",
) -> list[Event]:
    """Project the log into one viewpoint.

    ``view`` is ``observer``, ``memory``, ``exam``, or a participant id.
    An unknown participant yields only the global run events rather than
    raising -- an empty perspective is a valid answer to "what did X see".
    """
    view = (view or "observer").strip()
    if view == "observer":
        return list(events)
    if view == "memory":
        return [e for e in events if e.action in _MEMORY or e.action in _GLOBAL]
    if view == "exam":
        return [e for e in events if e.action in _EXAM or e.action in _GLOBAL]
    return [
        e for e in events
        if e.actor == view or e.subject == view or e.action in _GLOBAL
    ]


def perspectives(events: Sequence[Event]) -> list[str]:
    """Every viewpoint this recording supports."""
    return ["observer", "memory", "exam", *actors(events)]


@dataclass
class Summary:
    run: str
    events: int
    duration: float
    participants: list[str]
    lessons: int
    memories: int
    questions: int
    passed: int
    failed: int

    def render(self) -> str:
        verdict = "PASSED" if self.passed and not self.failed else (
            "FAILED" if self.failed else "no verdict"
        )
        return (
            f"run {self.run}\n"
            f"  {self.events} events over {self.duration:.1f}s\n"
            f"  participants : {', '.join(self.participants) or '(none)'}\n"
            f"  lessons      : {self.lessons}\n"
            f"  memories kept: {self.memories}\n"
            f"  exam         : {self.questions} question(s) -> {verdict}"
        )


def summarize(events: Sequence[Event]) -> Summary:
    counted: dict[str, int] = {}
    for event in events:
        counted[event.action] = counted.get(event.action, 0) + 1
    grades = [e for e in events if e.action == "exam.grade"]
    return Summary(
        run=next((e.run for e in events if e.run), ""),
        events=len(events),
        duration=max((e.mono for e in events), default=0.0),
        participants=actors(events),
        lessons=counted.get("lesson.deliver", 0),
        memories=counted.get("memory.write", 0),
        questions=counted.get("exam.question", 0),
        passed=sum(1 for e in grades if e.payload.get("passed") is True),
        failed=sum(1 for e in grades if e.payload.get("passed") is False),
    )


_GLYPH = {
    "run.start": "|>",
    "run.end": "|.",
    "twin.hatch": "()",
    "lesson.deliver": "->",
    "agent.response": "<-",
    "memory.write": "[+]",
    "memory.inject": "[:]",
    "exam.question": "??",
    "exam.answer": "!!",
    "exam.grade": "==",
    "graduate": "**",
    "remediate": "~~",
    "promote": "^^",
    "chat": "..",
    "claim.acquire": "#",
    "claim.release": "#/",
}


def render(event: Event, width: int = 96) -> str:
    """One readable line. Unknown actions still render -- never assume a set."""
    glyph = _GLYPH.get(event.action, "*")
    who = event.actor or "-"
    if event.subject and event.subject != event.actor:
        who = f"{who}>{event.subject}"
    body = event.text
    if not body:
        extra = {k: v for k, v in event.payload.items() if not k.startswith("_")}
        body = ", ".join(f"{k}={v}" for k, v in sorted(extra.items())) or ""
    body = " ".join(str(body).split())
    prefix = f"{event.mono:7.2f}s {glyph:>3} {who:<22} {event.action:<15} "
    room = max(20, width - len(prefix))
    if len(body) > room:
        body = body[: room - 1] + "\u2026"
    return prefix + body


def play(
    events: Sequence[Event],
    *,
    view: str = "observer",
    speed: float = 0.0,
    max_gap: float = 3.0,
    width: int = 96,
    out: Callable[[str], Any] | None = None,
) -> int:
    """Print a projection, optionally paced like the original run.

    ``speed`` of 0 prints immediately; 1.0 is real time; 2.0 is twice as fast.
    ``max_gap`` caps any single wait so one long model call cannot stall the
    whole replay.
    """
    write = out or (lambda line: print(line, flush=True))
    chosen = perspective(events, view)
    previous = None
    for event in chosen:
        if speed > 0 and previous is not None:
            delay = (event.mono - previous) / speed
            if delay > 0:
                time.sleep(min(delay, max_gap))
        previous = event.mono
        write(render(event, width=width))
    return len(chosen)


def transcript(events: Sequence[Event], view: str = "observer") -> str:
    """Full-fidelity text, untruncated -- for reading rather than watching."""
    lines: list[str] = []
    for event in perspective(events, view):
        who = event.actor or "-"
        target = f" -> {event.subject}" if event.subject else ""
        lines.append(f"\n=== [{event.seq}] {event.action} :: {who}{target} "
                     f"(+{event.mono:.2f}s) ===")
        body = event.text
        if body:
            lines.append(body)
        rest = {
            key: value
            for key, value in sorted(event.payload.items())
            if key not in ("text", "content", "question", "answer", "message")
        }
        if rest:
            lines.append(f"  {rest}")
    return "\n".join(lines).strip()


def iter_recording(path: str, view: str = "observer") -> Iterator[Event]:
    """Convenience: load a file and project it in one call."""
    yield from perspective(load(path), view)


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - CLI glue
    from .cli import main as cli_main

    return cli_main(["replay", *(argv or sys.argv[1:])])
