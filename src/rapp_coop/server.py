"""HTTP surface for the coop neighborhood.

Twins do not always share a filesystem: the warden runs on the Windows
battlestation while another stream of work runs on a Mac. This server puts one
``/chat`` in front of :class:`~rapp_coop.coop.Neighborhood` so
every twin -- local or remote, human or model -- reaches the same state.

The endpoint is the whole point. ``GET /`` serves a small page that does
nothing except POST to ``/chat``, which is exactly what a model does. There is
no privileged human path, so anything a person can do in the browser a twin can
do with ``curl``, and the records are indistinguishable afterwards.

Bind it to the tailnet address to include twins on other machines. A shared
token may be required for writes; reads stay open so a twin can orient itself
cheaply.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from .coop import DEFAULT_CHANNEL, Claim, Neighborhood, Twin

DEFAULT_PORT = 8770
_MAX_BODY = 64 * 1024

PAGE = """<!doctype html>
<meta charset="utf-8"><title>rapp-coop</title>
<style>
 body{font:14px/1.5 system-ui;margin:0;background:#0d1117;color:#e6edf3}
 header{padding:10px 14px;border-bottom:1px solid #30363d;font-weight:600}
 #twins{padding:6px 14px;color:#7d8590;border-bottom:1px solid #30363d;font-size:12px}
 #log{padding:12px 14px;height:calc(100vh - 150px);overflow:auto}
 .m{margin:0 0 8px}
 .who{color:#58a6ff;font-weight:600}
 .kind{color:#7d8590;font-size:11px;margin-left:4px}
 form{display:flex;gap:8px;padding:10px 14px;border-top:1px solid #30363d}
 input,button{font:inherit;padding:8px;border-radius:6px;border:1px solid #30363d}
 input{flex:1;background:#0d1117;color:#e6edf3}
 button{background:#238636;color:#fff;border:0;cursor:pointer}
</style>
<header>rapp-coop &mdash; one /chat for humans and twins
  &nbsp;<a href="/replay" style="color:#58a6ff;font-weight:400">watch a replay &rarr;</a>
</header>
<div id="twins">&nbsp;</div>
<div id="log"></div>
<form id="f">
  <input id="who" size="12" placeholder="your name" required>
  <input id="t" placeholder="message" autocomplete="off" required>
  <button>send</button>
</form>
<script>
let since = 0;
const log = document.getElementById('log');
const who = document.getElementById('who');
who.value = localStorage.getItem('coop-who') || '';
who.addEventListener('change', () => localStorage.setItem('coop-who', who.value));

async function poll() {
  try {
    const r = await fetch('/chat?since=' + since);
    const d = await r.json();
    for (const m of d.messages || []) {
      since = Math.max(since, m.seq);
      if (m.action !== 'chat') continue;
      const p = m.payload || {};
      const el = document.createElement('p');
      el.className = 'm';
      el.innerHTML = '<span class="who"></span><span class="kind"></span> <span class="x"></span>';
      el.querySelector('.who').textContent = p.from || '?';
      el.querySelector('.kind').textContent = p.kind || '';
      el.querySelector('.x').textContent = p.text || '';
      log.appendChild(el);
    }
    log.scrollTop = log.scrollHeight;
    const t = await (await fetch('/twins')).json();
    document.getElementById('twins').textContent =
      'present: ' + (t.twins || []).map(x => x.id + '(' + x.kind + ')').join(', ');
  } catch (e) { /* keep polling */ }
  setTimeout(poll, 2000);
}
document.getElementById('f').addEventListener('submit', async ev => {
  ev.preventDefault();
  const t = document.getElementById('t');
  await fetch('/chat', {
    method: 'POST',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify({action: 'chat', payload: {
      from: who.value, kind: 'human', text: t.value}})
  });
  t.value = '';
});
poll();
</script>
"""


class _Handler(BaseHTTPRequestHandler):
    server_version = "rapp-coop/1.0"
    neighborhood: Neighborhood
    token: str = ""
    recordings: str = ""

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        return

    # -- helpers ---------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, value: Any) -> None:
        self._send(
            code,
            json.dumps(value, sort_keys=True).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return {}
        if length <= 0 or length > _MAX_BODY:
            return {}
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _authorized(self) -> bool:
        if not self.token:
            return True
        supplied = self.headers.get("X-Coop-Token", "")
        return bool(supplied) and supplied == self.token

    @staticmethod
    def _unwrap(body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Accept the full envelope or a bare payload, identically."""
        payload = body.get("payload")
        if isinstance(payload, dict):
            return str(body.get("action", "chat")), payload
        return str(body.get("action", "chat")), body

    # -- routes ----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        route = parsed.path.rstrip("/") or "/"
        if route == "/":
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif route == "/chat":
            since = _int(query.get("since", ["0"])[0], 0)
            limit = _int(query.get("limit", ["200"])[0], 200)
            channel = query.get("channel", [None])[0]
            messages = self.neighborhood.messages(
                since, channel=channel, limit=limit
            )
            self._json(200, {"messages": messages})
        elif route == "/twins":
            stale = query.get("all", ["0"])[0] == "1"
            twins = self.neighborhood.twins(include_stale=stale)
            self._json(200, {"twins": [t.__dict__ for t in twins]})
        elif route == "/claims":
            claims = self.neighborhood.claims()
            self._json(200, {"claims": [c.__dict__ for c in claims]})
        elif route == "/health":
            self._json(200, {"status": "ok"})
        elif route == "/replay":
            from .player import PLAYER_HTML

            self._send(200, PLAYER_HTML.encode("utf-8"),
                       "text/html; charset=utf-8")
        elif route == "/recordings":
            from .player import list_recordings

            found = list_recordings(self.recordings) if self.recordings else []
            self._json(200, {"recordings": found, "dir": self.recordings})
        elif route == "/recording":
            from .player import read_recording

            name = query.get("name", [""])[0]
            try:
                events = read_recording(self.recordings, name)
            except (ValueError, FileNotFoundError, OSError) as error:
                self._json(404, {"error": str(error)})
                return
            self._json(200, {"name": name, "events": events})
        else:
            self._json(404, {"error": "not found"})

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path.rstrip("/") or "/"
        if not self._authorized():
            self._json(401, {"error": "bad token"})
            return
        action, payload = self._unwrap(self._body())
        try:
            if route == "/chat":
                record = self.neighborhood.say(
                    str(payload.get("from", "")).strip() or "anonymous",
                    str(payload.get("text", "")),
                    kind=str(payload.get("kind", "agent")),
                    channel=str(payload.get("channel", DEFAULT_CHANNEL)),
                    reply_to=payload.get("reply_to"),
                )
                self._json(201, record)
            elif route == "/twins":
                twin = self.neighborhood.check_in(
                    str(payload.get("id", "")),
                    kind=str(payload.get("kind", "agent")),
                    role=str(payload.get("role", "")),
                    status=str(payload.get("status", "")),
                )
                self._json(201, twin.__dict__)
            elif route == "/claims":
                self._claims(action, payload)
            else:
                self._json(404, {"error": "not found"})
        except ValueError as error:
            self._json(400, {"error": str(error)})

    def _claims(self, action: str, payload: dict[str, Any]) -> None:
        resource = str(payload.get("resource", ""))
        holder = str(payload.get("holder", ""))
        if action == "release":
            ok = self.neighborhood.release(resource, holder)
            self._json(200 if ok else 409, {"released": ok})
            return
        granted, claim = self.neighborhood.claim(
            resource,
            holder,
            ttl=float(payload.get("ttl", 120)),
            note=str(payload.get("note", "")),
        )
        self._json(200 if granted else 409, {"granted": granted, **claim.__dict__})


def _int(raw: str, fallback: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback


def serve(
    neighborhood: Neighborhood,
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    token: str = "",
    recordings: str = "",
) -> ThreadingHTTPServer:
    """Start the coop server. Caller owns the returned instance."""
    handler = type(
        "CoopHandler",
        (_Handler,),
        {
            "neighborhood": neighborhood,
            "token": token or os.environ.get("COOP_TOKEN", ""),
            "recordings": recordings or os.environ.get("COOP_RECORDINGS", ""),
        },
    )
    return ThreadingHTTPServer((host, port), handler)


class RemoteNeighborhood:
    """A neighborhood reached over HTTP.

    Deliberately duck-types :class:`~rapp_coop.coop.Neighborhood`
    so callers never learn whether the state is a local file or another
    machine. A twin on the Mac and a twin on the battlestation run identical
    code paths; only the constructor differs.
    """

    def __init__(self, url: str, token: str = "", timeout: float = 10.0) -> None:
        self.url = url.rstrip("/")
        scheme = urlparse(self.url).scheme
        if scheme not in ("http", "https"):
            raise ValueError(
                f"coop url must be http or https, got {scheme or url!r}"
            )
        self.token = token or os.environ.get("COOP_TOKEN", "")
        self.timeout = timeout

    def _call(
        self, route: str, body: dict[str, Any] | None = None, **query: Any
    ) -> Any:
        target = f"{self.url}{route}"
        if query:
            clean = {k: v for k, v in query.items() if v is not None}
            if clean:
                target = f"{target}?{urlencode(clean)}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        # Scheme is constrained to http(s) in __init__.
        request = Request(  # noqa: S310
            target, data=data, method="POST" if data else "GET"
        )
        if data:
            request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_header("X-Coop-Token", self.token)
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                return json.loads(response.read())
        except HTTPError as error:
            return self._expected(error)

    @staticmethod
    def _expected(error: HTTPError) -> Any:
        """A refused lease is an answer, not a failure.

        The server says 409 when a resource is already held or a release was
        refused. That is exactly the information the caller asked for, so it
        must come back as data rather than an exception -- otherwise every
        call site would need a try/except to do ordinary coordination.
        """
        if error.code != 409:
            raise error
        try:
            return json.loads(error.read())
        except (json.JSONDecodeError, OSError):
            raise error from None

    def say(
        self,
        sender: str,
        text: str,
        *,
        kind: str = "agent",
        channel: str = DEFAULT_CHANNEL,
        reply_to: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "from": sender,
            "kind": kind,
            "channel": channel,
            "text": text,
        }
        if reply_to is not None:
            payload["reply_to"] = int(reply_to)
        return self._call("/chat", {"action": "chat", "payload": payload})

    def messages(
        self,
        since: int = 0,
        *,
        channel: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        got = self._call("/chat", None, since=since, channel=channel, limit=limit)
        return list(got.get("messages", []))

    def check_in(
        self,
        twin_id: str,
        *,
        kind: str = "agent",
        role: str = "",
        status: str = "",
    ) -> Twin:
        got = self._call(
            "/twins",
            {
                "action": "check_in",
                "payload": {
                    "id": twin_id,
                    "kind": kind,
                    "role": role,
                    "status": status,
                },
            },
        )
        return Twin(**{k: got.get(k, "") for k in ("id", "kind", "role",
                                                   "status", "at")})

    def twins(self, *, include_stale: bool = False) -> list[Twin]:
        got = self._call("/twins", None, all="1" if include_stale else None)
        return [
            Twin(**{k: row.get(k, "") for k in ("id", "kind", "role",
                                                "status", "at")})
            for row in got.get("twins", [])
        ]

    def claim(
        self,
        resource: str,
        holder: str,
        *,
        ttl: float = 120.0,
        note: str = "",
    ) -> tuple[bool, Claim]:
        got = self._call(
            "/claims",
            {
                "action": "claim",
                "payload": {
                    "resource": resource,
                    "holder": holder,
                    "ttl": ttl,
                    "note": note,
                },
            },
        )
        return bool(got.get("granted")), _claim_from(got)

    def release(self, resource: str, holder: str) -> bool:
        got = self._call(
            "/claims",
            {
                "action": "release",
                "payload": {"resource": resource, "holder": holder},
            },
        )
        return bool(got.get("released"))

    def claims(self, *, include_expired: bool = False) -> list[Claim]:
        got = self._call("/claims")
        return [_claim_from(row) for row in got.get("claims", [])]


def _claim_from(row: dict[str, Any]) -> Claim:
    return Claim(
        resource=str(row.get("resource", "")),
        holder=str(row.get("holder", "")),
        at=str(row.get("at", "")),
        ttl=float(row.get("ttl", 120.0)),
        note=str(row.get("note", "")),
    )

