"""Telemetry exhaust: record a learning lifecycle so it can be replayed exactly.

Schooling is the interesting part of this system, and it is invisible. A twin is
taught, decides what to keep, is examined cold, and graduates -- and all that
survives is a memory file and a pass/fail. The reasoning, the ordering, the
moment a lesson actually landed: gone.

This module records it. Not a summary, not a log line -- the events themselves,
in order, with timing, so the whole lifecycle can be played back.

Three design decisions carry the whole thing:

**One log, many perspectives.** There is no mentor recording and no apprentice
recording. There is one append-only event log, and a *perspective* is a
projection over it (see :mod:`rapp_coop.replay`). Recording per-viewpoint would
force you to decide up front whose story matters, and you would be wrong. Every
event carries ``actor`` and ``subject``, which is enough to reconstruct any
viewpoint after the fact -- including viewpoints nobody has thought of yet.

**Fidelity is additive, never breaking.** Every event carries a schema version
and an open payload. Readers must ignore unknown actions and unknown payload
keys. This is what lets you add richer capture later -- token counts, latency,
the full system prompt, a memory diff -- without invalidating a single existing
recording. Recordings made today must still play in a year.

**Monotonic offsets, not wall clocks.** Wall time is for humans reading a
transcript; it jumps, and it cannot be trusted for pacing. Replay timing uses a
monotonic offset captured at record time, so playback preserves the real rhythm
of a session -- including the long pause while a model was thinking, which is
often the most informative part.

The envelope is a superset of the coop chat record, so a chat message and a
telemetry event are the same shape with more context attached.
"""

from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

SCHEMA_VERSION = 1

# Lifecycle actions emitted by a schooling run. Recorders may emit actions
# outside this set and readers must tolerate them -- this is documentation of
# the core vocabulary, not a closed enum.
ACTIONS = (
    "run.start",
    "run.end",
    "twin.hatch",
    "lesson.deliver",
    "agent.response",
    "memory.inject",
    "memory.write",
    "exam.question",
    "exam.answer",
    "exam.grade",
    "graduate",
    "remediate",
    "promote",
    "chat",
    "claim.acquire",
    "claim.release",
    "note",
)

# Anything matching these is replaced before it reaches disk. A recording is
# meant to be shared -- that is the entire point -- so it must never be the
# thing that leaks a credential. Redaction happens at write time, because a
# secret removed later has still been written to a file.
_SECRET_PATTERNS = (
    re.compile(r"(gh[pousr]_[A-Za-z0-9]{16,})"),
    re.compile(r"(xox[baprs]-[A-Za-z0-9-]{10,})"),
    re.compile(r"(AKIA[0-9A-Z]{16})"),
    # NOTE: no \b before the keyword. Real config keys are compounds --
    # AdminPassword, api_token, CLIENT_SECRET -- and a word boundary would
    # refuse to match exactly those, which are the ones that leak.
    re.compile(r"(?i)[a-z0-9_.-]*(?:password|passwd|secret|token|api[_-]?key)"
               r"\s*[=:]\s*[\"']?([^\s\"',}]{6,})"),
    re.compile(r"(eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,})"),
)
_REDACTED = "[redacted]"


def redact(value: Any) -> Any:
    """Strip anything that looks like a credential, at any depth."""
    if isinstance(value, str):
        out = value
        for pattern in _SECRET_PATTERNS:
            out = pattern.sub(
                lambda m: m.group(0).replace(m.group(m.lastindex or 0), _REDACTED),
                out,
            )
        return out
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class Event:
    """One recorded moment.

    ``seq`` is dense and monotonic so a consumer that restarts can resume
    exactly. ``mono`` is seconds since the run began, which is what replay
    paces on.
    """

    seq: int
    at: str
    mono: float
    action: str
    actor: str = ""
    subject: str = ""
    run: str = ""
    v: int = SCHEMA_VERSION
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Event:
        """Tolerant parse. Unknown keys are preserved inside ``payload``.

        Forward compatibility is a hard requirement: a reader written today
        must not lose data written by a richer recorder tomorrow.
        """
        known = {"seq", "at", "mono", "action", "actor", "subject", "run", "v",
                 "payload"}
        payload = raw.get("payload")
        payload = dict(payload) if isinstance(payload, dict) else {}
        for key, value in raw.items():
            if key not in known:
                payload.setdefault(f"_{key}", value)
        return cls(
            seq=int(raw.get("seq", 0) or 0),
            at=str(raw.get("at", "")),
            mono=float(raw.get("mono", 0.0) or 0.0),
            action=str(raw.get("action", "note")),
            actor=str(raw.get("actor", "")),
            subject=str(raw.get("subject", "")),
            run=str(raw.get("run", "")),
            v=int(raw.get("v", SCHEMA_VERSION) or SCHEMA_VERSION),
            payload=payload,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "at": self.at,
            "mono": round(self.mono, 4),
            "v": self.v,
            "run": self.run,
            "action": self.action,
            "actor": self.actor,
            "subject": self.subject,
            "payload": self.payload,
        }

    @property
    def text(self) -> str:
        """Best-effort human-readable body, whatever the action."""
        for key in ("text", "content", "question", "answer", "message", "summary"):
            value = self.payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""


class Recording:
    """Append-only telemetry for one run.

    Plain JSONL: greppable, streamable, diffable, and readable by anything.
    A recording that needs a special tool to inspect will not get inspected.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        run: str = "",
        redact_secrets: bool = True,
    ) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run = run or f"run-{int(time.time())}"
        self.redact_secrets = redact_secrets
        self._t0 = time.monotonic()
        self._seq = self._resume_seq()

    def _resume_seq(self) -> int:
        """Continue numbering if the file already exists."""
        last = 0
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        last = max(last, int(json.loads(line).get("seq", 0)))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
        except FileNotFoundError:
            pass
        return last

    def record(
        self,
        action: str,
        payload: dict[str, Any] | None = None,
        *,
        actor: str = "",
        subject: str = "",
    ) -> Event:
        body = dict(payload or {})
        if self.redact_secrets:
            body = redact(body)
        self._seq += 1
        event = Event(
            seq=self._seq,
            at=_now(),
            mono=time.monotonic() - self._t0,
            action=str(action),
            actor=actor,
            subject=subject,
            run=self.run,
            payload=body,
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
        return event

    # -- lifecycle shorthands -------------------------------------------
    def hatch(self, twin: str, **detail: Any) -> Event:
        return self.record("twin.hatch", detail, actor=twin, subject=twin)

    def lesson(self, mentor: str, apprentice: str, text: str, **d: Any) -> Event:
        return self.record(
            "lesson.deliver", {"text": text, **d}, actor=mentor, subject=apprentice
        )

    def response(self, twin: str, text: str, **detail: Any) -> Event:
        return self.record(
            "agent.response", {"text": text, **detail}, actor=twin
        )

    def memory_write(self, twin: str, content: str, **detail: Any) -> Event:
        """The single most valuable event: what the apprentice chose to keep."""
        return self.record(
            "memory.write", {"content": content, **detail}, actor=twin
        )

    def question(self, mentor: str, apprentice: str, text: str, **d: Any) -> Event:
        return self.record(
            "exam.question",
            {"question": text, "cold": True, **d},
            actor=mentor,
            subject=apprentice,
        )

    def answer(self, apprentice: str, text: str, **detail: Any) -> Event:
        return self.record(
            "exam.answer", {"answer": text, **detail}, actor=apprentice
        )

    def grade(self, mentor: str, apprentice: str, passed: bool, **d: Any) -> Event:
        return self.record(
            "exam.grade",
            {"passed": bool(passed), **d},
            actor=mentor,
            subject=apprentice,
        )

    @contextmanager
    def run_span(self, **detail: Any) -> Iterator[Recording]:
        """Bracket a run so it is closed even when the body raises."""
        self.record("run.start", {"schema": SCHEMA_VERSION, **detail})
        failure: str | None = None
        try:
            yield self
        except Exception as error:  # noqa: BLE001 - recorded, then re-raised
            failure = f"{type(error).__name__}: {error}"
            raise
        finally:
            self.record("run.end", {"error": failure} if failure else {"ok": True})


def load(path: str | os.PathLike[str]) -> list[Event]:
    """Read a recording. Malformed lines are skipped, never fatal."""
    events: list[Event] = []
    try:
        with Path(path).expanduser().open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(raw, dict):
                    events.append(Event.from_dict(raw))
    except FileNotFoundError:
        return []
    return sorted(events, key=lambda e: e.seq)


def actors(events: Sequence[Event]) -> list[str]:
    """Every participant that appears, in first-seen order."""
    seen: list[str] = []
    for event in events:
        for name in (event.actor, event.subject):
            if name and name not in seen:
                seen.append(name)
    return seen
