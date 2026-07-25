"""rapp-coop: a neighborhood where several twins play one world together.

The play loop assumes it is alone. The moment a second stream of work shows up
-- another AI thread, or the human at the keyboard -- that assumption breaks in
two specific ways:

1. **Collision.** Two twins both grab the keyboard, both restart the warden, or
   both edit the same file. The failure is silent and the run is corrupted.
2. **Blindness.** Neither twin knows what the other just did, so they redo work
   or contradict each other.

This module fixes exactly those two things and nothing else.

*Collision* is solved by **claims**: a named resource can be held by one twin at
a time, under a lease that expires. A twin that crashes cannot deadlock the
neighborhood, because its lease times out and becomes stealable.

*Blindness* is solved by **chat**: one append-only stream that every twin reads
and writes.

The design rule that matters most: **a human and an AI are the same kind of
participant.** There is no human endpoint and no agent endpoint -- there is one
``/chat`` shape. ``kind`` is descriptive metadata, never a branch in the code.
A person typing in the browser and a model POSTing JSON produce byte-identical
records. That is what makes the collaboration composable: a twin never has to
ask "am I talking to a person right now?" and change its behaviour.

The envelope is Rappterbook's ``{"action", "payload"}`` so records stay legible
to anything already fluent in that ecosystem.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

DEFAULT_CHANNEL = "palworld"
# A twin is considered present if it has checked in within this window. Long
# enough to survive one slow model decision, short enough that a dead twin
# stops looking alive.
PRESENCE_TTL = 90.0
# Default lease length. Deliberately short: a lease is cheap to renew and
# expensive to leave stranded.
CLAIM_TTL = 120.0
_LOCK_TIMEOUT = 10.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Twin:
    """One participant. A person and a model are both Twins."""

    id: str
    kind: str = "agent"
    role: str = ""
    status: str = ""
    at: str = ""

    def alive(self, ttl: float = PRESENCE_TTL, now: float | None = None) -> bool:
        try:
            seen = datetime.fromisoformat(self.at).timestamp()
        except (TypeError, ValueError):
            return False
        return ((now if now is not None else time.time()) - seen) <= ttl


@dataclass(frozen=True)
class Claim:
    """An expiring exclusive hold on one named resource."""

    resource: str
    holder: str
    at: str
    ttl: float = CLAIM_TTL
    note: str = ""

    def expires_at(self) -> float:
        try:
            return datetime.fromisoformat(self.at).timestamp() + float(self.ttl)
        except (TypeError, ValueError):
            return 0.0

    def expired(self, now: float | None = None) -> bool:
        return (now if now is not None else time.time()) >= self.expires_at()


class Neighborhood:
    """File-backed coordination shared by every twin on one host.

    Everything is a plain file so the state is inspectable with ``cat`` and
    survives any individual twin dying. Cross-machine twins reach the same
    state through :mod:`rapp_coop.server` over the tailnet.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).expanduser()
        self.chat_path = self.root / "chat.jsonl"
        self.twins_dir = self.root / "twins"
        self.claims_dir = self.root / "claims"
        for directory in (self.root, self.twins_dir, self.claims_dir):
            directory.mkdir(parents=True, exist_ok=True)

    # -- locking ---------------------------------------------------------
    @contextmanager
    def _lock(self, name: str) -> Iterator[None]:
        """Cross-process mutex built on exclusive file creation.

        ``O_CREAT | O_EXCL`` is the one primitive that is atomic on both NTFS
        and POSIX without a dependency, so it is also what backs claims.
        """
        path = self.root / f".{name}.lock"
        deadline = time.time() + _LOCK_TIMEOUT
        while True:
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except (FileExistsError, PermissionError):
                # Windows raises PermissionError (not FileExistsError) when the
                # lock file is mid-deletion by the previous holder, so both
                # mean the same thing here: someone else has it, try again.
                # A lock older than the timeout belonged to a process that
                # died holding it; reclaim it rather than hang forever.
                try:
                    if time.time() - path.stat().st_mtime > _LOCK_TIMEOUT:
                        path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.time() >= deadline:
                    raise TimeoutError(f"could not lock {name}") from None
                time.sleep(0.02)
        try:
            yield
        finally:
            os.close(fd)
            path.unlink(missing_ok=True)

    def _write_json(self, path: Path, value: Any) -> None:
        """Replace a file atomically so readers never see a partial record."""
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)

    # -- chat ------------------------------------------------------------
    def post(
        self,
        action: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Append one envelope to the shared stream and return it."""
        with self._lock("chat"):
            seq = sum(1 for _ in self._raw_lines()) + 1
            record = {
                "seq": seq,
                "at": _now(),
                "action": action,
                "payload": payload,
            }
            with self.chat_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def say(
        self,
        sender: str,
        text: str,
        *,
        kind: str = "agent",
        channel: str = DEFAULT_CHANNEL,
        reply_to: int | None = None,
    ) -> dict[str, Any]:
        """Post a chat message.

        Identical for a person and a model on purpose -- see the module
        docstring. ``kind`` is recorded, never branched on.
        """
        text = str(text).strip()
        if not text:
            raise ValueError("chat text cannot be empty")
        payload: dict[str, Any] = {
            "from": sender,
            "kind": kind,
            "channel": channel,
            "text": text,
        }
        if reply_to is not None:
            payload["reply_to"] = int(reply_to)
        return self.post("chat", payload)

    def _raw_lines(self) -> Iterator[str]:
        try:
            with self.chat_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        yield line
        except FileNotFoundError:
            return

    def messages(
        self,
        since: int = 0,
        *,
        channel: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Read the stream. ``since`` is an exclusive sequence cursor."""
        out: list[dict[str, Any]] = []
        for line in self._raw_lines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict) or record.get("seq", 0) <= since:
                continue
            if channel is not None:
                payload = record.get("payload")
                if not isinstance(payload, dict):
                    continue
                if payload.get("channel", DEFAULT_CHANNEL) != channel:
                    continue
            out.append(record)
        if limit is not None and limit >= 0:
            out = out[-limit:]
        return out

    # -- presence --------------------------------------------------------
    def check_in(
        self,
        twin_id: str,
        *,
        kind: str = "agent",
        role: str = "",
        status: str = "",
    ) -> Twin:
        """Join the neighborhood, or refresh an existing presence."""
        twin_id = str(twin_id).strip()
        if not twin_id:
            raise ValueError("twin id cannot be empty")
        twin = Twin(id=twin_id, kind=kind, role=role, status=status, at=_now())
        self._write_json(self.twins_dir / f"{_safe(twin_id)}.json", asdict(twin))
        return twin

    def twins(self, *, include_stale: bool = False) -> list[Twin]:
        found: list[Twin] = []
        now = time.time()
        for path in sorted(self.twins_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            twin = Twin(
                id=str(data.get("id", path.stem)),
                kind=str(data.get("kind", "agent")),
                role=str(data.get("role", "")),
                status=str(data.get("status", "")),
                at=str(data.get("at", "")),
            )
            if include_stale or twin.alive(now=now):
                found.append(twin)
        return found

    # -- claims ----------------------------------------------------------
    def claim(
        self,
        resource: str,
        holder: str,
        *,
        ttl: float = CLAIM_TTL,
        note: str = "",
    ) -> tuple[bool, Claim]:
        """Take an exclusive lease.

        Returns ``(True, mine)`` when the lease is held by ``holder``. Renewing
        your own lease always succeeds; stealing another twin's lease succeeds
        only once it has expired.
        """
        resource = str(resource).strip()
        if not resource:
            raise ValueError("resource cannot be empty")
        path = self.claims_dir / f"{_safe(resource)}.json"
        with self._lock(f"claim-{_safe(resource)}"):
            current = _read_claim(path)
            if current is not None and current.holder != holder:
                if not current.expired():
                    return False, current
            mine = Claim(
                resource=resource,
                holder=holder,
                at=_now(),
                ttl=float(ttl),
                note=note,
            )
            self._write_json(path, asdict(mine))
        return True, mine

    def release(self, resource: str, holder: str) -> bool:
        """Drop a lease you hold. Releasing someone else's lease is refused."""
        path = self.claims_dir / f"{_safe(str(resource).strip())}.json"
        with self._lock(f"claim-{_safe(str(resource).strip())}"):
            current = _read_claim(path)
            if current is None:
                return False
            if current.holder != holder and not current.expired():
                return False
            path.unlink(missing_ok=True)
        return True

    def claims(self, *, include_expired: bool = False) -> list[Claim]:
        out: list[Claim] = []
        now = time.time()
        for path in sorted(self.claims_dir.glob("*.json")):
            current = _read_claim(path)
            if current is None:
                continue
            if include_expired or not current.expired(now=now):
                out.append(current)
        return out

    @contextmanager
    def holding(
        self,
        resource: str,
        holder: str,
        *,
        ttl: float = CLAIM_TTL,
        note: str = "",
    ) -> Iterator[Claim]:
        """Run a block only while the lease is genuinely held."""
        ok, current = self.claim(resource, holder, ttl=ttl, note=note)
        if not ok:
            raise ResourceBusy(resource, current.holder)
        try:
            yield current
        finally:
            self.release(resource, holder)


class ResourceBusy(RuntimeError):
    """Raised when another live twin holds the lease you asked for."""

    def __init__(self, resource: str, holder: str) -> None:
        super().__init__(f"{resource} is held by {holder}")
        self.resource = resource
        self.holder = holder


def _safe(name: str) -> str:
    """Filesystem-safe key. Keeps resource names readable on disk."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)[:120]


def _read_claim(path: Path) -> Claim | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return Claim(
            resource=str(data["resource"]),
            holder=str(data["holder"]),
            at=str(data["at"]),
            ttl=float(data.get("ttl", CLAIM_TTL)),
            note=str(data.get("note", "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


# Resources worth claiming. Naming them in one place stops two twins inventing
# different strings for the same physical thing -- which would defeat the whole
# mechanism, and would do it silently, because both claims succeed.
#
# Override or extend this for your own world; keep it central either way.
RESOURCES = {
    "keyboard": "Synthetic input to a client. Two twins typing = garbage input.",
    "warden": "A supervised process lifecycle. Two supervisors fight over restarts.",
    "server": "Restart/shutdown of a shared service. Disconnects everyone.",
    "repo": "Git operations in a working tree. Concurrent rebases corrupt state.",
    "stream": "A broadcast encoder. One encoder, one stream key.",
}

