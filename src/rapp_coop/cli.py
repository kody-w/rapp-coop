"""Command line for the coop neighborhood.

Every command works identically whether the neighborhood is local files or a
remote server -- set ``COOP_URL`` and nothing else changes. That symmetry is
the point: a twin should never write transport-specific code just to
coordinate.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from .coop import RESOURCES, Neighborhood

DEFAULT_ROOT = "~/.rapp-coop"


def _twin_id(args: argparse.Namespace) -> str:
    """Explicit flag, then environment, then the machine name."""
    return args.twin or os.environ.get("COOP_TWIN") or socket.gethostname()


def _neighborhood(args: argparse.Namespace) -> Any:
    url = args.url or os.environ.get("COOP_URL")
    if url:
        from .server import RemoteNeighborhood

        return RemoteNeighborhood(url, token=args.token or "")
    root = args.root or os.environ.get("COOP_ROOT", DEFAULT_ROOT)
    return Neighborhood(Path(root).expanduser())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rapp-coop",
        description="Several twins, one world, no collisions",
    )
    parser.add_argument("--twin", help="Identity to act as (default: hostname)")
    parser.add_argument("--url", help="Remote coop server, e.g. http://host:8770")
    parser.add_argument("--token", help="Shared write token")
    parser.add_argument("--root", help=f"Local state dir (default: {DEFAULT_ROOT})")
    sub = parser.add_subparsers(dest="action", required=True)

    serve_cmd = sub.add_parser("serve", help="Host /chat for every twin")
    serve_cmd.add_argument("--bind", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=8770)

    chat = sub.add_parser("chat", help="Say something to the neighborhood")
    chat.add_argument("text", nargs="+")
    chat.add_argument("--kind", default="agent", choices=("agent", "human"))
    chat.add_argument("--channel", default="general")
    chat.add_argument("--reply-to", type=int)

    log = sub.add_parser("log", help="Read the shared stream")
    log.add_argument("--since", type=int, default=0)
    log.add_argument("--channel")
    log.add_argument("--limit", type=int, default=50)
    log.add_argument("--follow", "-f", action="store_true")

    twins = sub.add_parser("twins", help="Check in and list who is present")
    twins.add_argument("--kind", default="agent", choices=("agent", "human"))
    twins.add_argument("--role", default="")
    twins.add_argument("--status", default="")

    claim = sub.add_parser("claim", help="Take an exclusive lease")
    claim.add_argument("resource")
    claim.add_argument("--ttl", type=float, default=120.0)
    claim.add_argument("--note")

    release = sub.add_parser("release", help="Drop a lease you hold")
    release.add_argument("resource")

    sub.add_parser("claims", help="List active leases")
    sub.add_parser("resources", help="List the resources worth claiming")

    replay = sub.add_parser(
        "replay", help="Replay a recorded learning lifecycle"
    )
    replay.add_argument("recording", help="Path to a .jsonl recording")
    replay.add_argument(
        "--as",
        dest="view",
        default="observer",
        help="Perspective: observer, memory, exam, or a participant id",
    )
    replay.add_argument(
        "--speed",
        type=float,
        default=0.0,
        help="0 = instant (default), 1.0 = real time, 2.0 = twice as fast",
    )
    replay.add_argument("--max-gap", type=float, default=3.0)
    replay.add_argument(
        "--transcript", action="store_true", help="Full untruncated text"
    )
    replay.add_argument("--summary", action="store_true", help="Stats only")
    replay.add_argument(
        "--views", action="store_true", help="List available perspectives"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Replay reads a file and touches no neighborhood state.
    if args.action == "replay":
        from .recorder import load
        from .replay import perspectives, play, summarize, transcript

        events = load(args.recording)
        if not events:
            print(f"no events in {args.recording}")
            return 1
        if args.views:
            for view in perspectives(events):
                print(f"  {view}")
            return 0
        if args.summary:
            print(summarize(events).render())
            return 0
        if args.transcript:
            print(transcript(events, args.view))
            return 0
        shown = play(
            events, view=args.view, speed=args.speed, max_gap=args.max_gap
        )
        if not shown:
            print(f"(no events visible from perspective {args.view!r})")
        return 0

    hood = _neighborhood(args)
    me = _twin_id(args)

    if args.action == "serve":
        from .server import serve

        httpd = serve(hood, host=args.bind, port=args.port, token=args.token or "")
        print(f"rapp-coop on http://{args.bind}:{httpd.server_address[1]}")
        print("  one /chat for humans (browser) and twins (POST JSON)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
        finally:
            httpd.server_close()
        return 0

    if args.action == "chat":
        record = hood.say(
            me,
            " ".join(args.text),
            kind=args.kind,
            channel=args.channel,
            reply_to=args.reply_to,
        )
        print(f"#{record['seq']} {me}: {record['payload']['text']}")
        return 0

    if args.action == "log":
        since = args.since
        while True:
            for message in hood.messages(
                since, channel=args.channel, limit=args.limit
            ):
                since = max(since, int(message.get("seq", 0)))
                if message.get("action") != "chat":
                    continue
                payload = message.get("payload", {})
                print(
                    f"#{message['seq']:<4} {payload.get('from', '?'):<16} "
                    f"[{payload.get('kind', '?')}] {payload.get('text', '')}"
                )
            if not args.follow:
                return 0
            time.sleep(2)

    if args.action == "twins":
        hood.check_in(me, kind=args.kind, role=args.role, status=args.status)
        for twin in hood.twins():
            mark = "*" if twin.id == me else " "
            print(f" {mark} {twin.id:<20} {twin.kind:<7} {twin.role:<12} {twin.at}")
        return 0

    if args.action == "claim":
        granted, claim = hood.claim(
            args.resource, me, ttl=args.ttl, note=args.note or ""
        )
        if granted:
            print(f"granted: {args.resource} -> {me} (ttl {args.ttl:g}s)")
            return 0
        print(f"busy: {args.resource} is held by {claim.holder}")
        return 1

    if args.action == "release":
        if hood.release(args.resource, me):
            print(f"released: {args.resource}")
            return 0
        print(f"refused: {args.resource} is not yours to release")
        return 1

    if args.action == "claims":
        current = hood.claims()
        if not current:
            print("no active claims")
        for claim in current:
            print(f"  {claim.resource:<16} {claim.holder:<20} {claim.note}")
        return 0

    if args.action == "resources":
        for name, why in sorted(RESOURCES.items()):
            print(f"  {name:<12} {why}")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
