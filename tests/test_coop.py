"""Tests for the coop neighborhood.

Two properties carry the whole design, so most of these tests exist to pin them
down:

1. **A lease is genuinely exclusive, and never permanent.** If exclusion leaks,
   two twins corrupt the run; if a lease outlives its holder, one crash wedges
   the neighborhood forever.
2. **A human and a twin produce identical records.** The moment the two diverge
   there are effectively two protocols, and every consumer has to branch.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from rapp_coop.coop import (
    Claim,
    Neighborhood,
    ResourceBusy,
    Twin,
)
from rapp_coop.server import RemoteNeighborhood, serve


@pytest.fixture
def hood(tmp_path) -> Neighborhood:
    return Neighborhood(tmp_path / "coop")


class TestChat:
    def test_sequences_are_dense_and_monotonic(self, hood):
        for i in range(5):
            hood.say("twin-a", f"m{i}")
        assert [m["seq"] for m in hood.messages()] == [1, 2, 3, 4, 5]

    def test_since_is_an_exclusive_cursor(self, hood):
        hood.say("a", "one")
        hood.say("a", "two")
        assert [m["payload"]["text"] for m in hood.messages(since=1)] == ["two"]

    def test_channels_isolate_streams(self, hood):
        hood.say("a", "world", channel="palworld")
        hood.say("a", "meta", channel="build")
        assert len(hood.messages(channel="build")) == 1

    def test_empty_text_is_refused(self, hood):
        with pytest.raises(ValueError):
            hood.say("a", "   ")

    def test_reply_threading_is_recorded(self, hood):
        first = hood.say("a", "question")
        second = hood.say("b", "answer", reply_to=first["seq"])
        assert second["payload"]["reply_to"] == first["seq"]


class TestOneShapeForEveryone:
    """The invariant that makes humans and twins interchangeable."""

    def test_human_and_agent_records_are_structurally_identical(self, hood):
        human = hood.say("kody", "I'll take the keyboard", kind="human")
        agent = hood.say("warden", "ack, staying on REST", kind="agent")
        assert human.keys() == agent.keys()
        assert human["payload"].keys() == agent["payload"].keys()
        assert human["action"] == agent["action"] == "chat"

    def test_kind_is_metadata_not_a_separate_channel(self, hood):
        hood.say("kody", "hi", kind="human")
        hood.say("warden", "hi", kind="agent")
        # Both land in the same default stream; nothing is filtered by kind.
        assert len(hood.messages(channel="palworld")) == 2


class TestPresence:
    def test_check_in_then_visible(self, hood):
        hood.check_in("warden", kind="agent", role="rest")
        assert [t.id for t in hood.twins()] == ["warden"]

    def test_stale_twins_are_hidden_but_recoverable(self, hood):
        hood.check_in("ghost")
        stale = Twin(id="ghost", at="2000-01-01T00:00:00+00:00")
        assert not stale.alive()
        assert hood.twins(include_stale=True)

    def test_unparseable_timestamp_is_not_alive(self):
        assert not Twin(id="x", at="not-a-time").alive()

    def test_empty_id_is_refused(self, hood):
        with pytest.raises(ValueError):
            hood.check_in("  ")


class TestClaims:
    def test_first_twin_wins(self, hood):
        granted, _ = hood.claim("keyboard", "twin-a")
        assert granted

    def test_second_twin_is_refused_and_told_who_holds_it(self, hood):
        hood.claim("keyboard", "twin-a")
        granted, current = hood.claim("keyboard", "twin-b")
        assert not granted
        assert current.holder == "twin-a"

    def test_holder_may_renew_its_own_lease(self, hood):
        hood.claim("keyboard", "twin-a", ttl=1)
        granted, _ = hood.claim("keyboard", "twin-a", ttl=60)
        assert granted

    def test_expired_lease_is_stealable(self, hood):
        hood.claim("keyboard", "dead-twin", ttl=-1)
        granted, current = hood.claim("keyboard", "twin-b")
        assert granted
        assert current.holder == "twin-b"

    def test_release_refuses_a_live_lease_you_do_not_hold(self, hood):
        hood.claim("warden", "twin-a", ttl=60)
        assert hood.release("warden", "twin-b") is False
        assert [c.holder for c in hood.claims()] == ["twin-a"]

    def test_release_frees_the_resource(self, hood):
        hood.claim("warden", "twin-a")
        assert hood.release("warden", "twin-a") is True
        assert hood.claims() == []

    def test_expired_claims_are_hidden_from_the_roster(self, hood):
        hood.claim("stream", "twin-a", ttl=-1)
        assert hood.claims() == []
        assert len(hood.claims(include_expired=True)) == 1

    def test_holding_releases_even_when_the_body_raises(self, hood):
        with pytest.raises(RuntimeError, match="boom"):
            with hood.holding("repo", "twin-a"):
                raise RuntimeError("boom")
        assert hood.claims() == []

    def test_holding_refuses_a_busy_resource(self, hood):
        hood.claim("repo", "twin-a", ttl=60)
        with pytest.raises(ResourceBusy) as caught:
            with hood.holding("repo", "twin-b"):
                pass
        assert caught.value.holder == "twin-a"

    def test_expiry_maths(self):
        assert Claim("r", "h", at="2000-01-01T00:00:00+00:00", ttl=1).expired()

    def test_resource_names_with_separators_do_not_escape_the_directory(
        self, hood
    ):
        granted, _ = hood.claim("../../etc/passwd", "twin-a")
        assert granted
        assert hood.claims_dir.parent == hood.root
        for path in hood.claims_dir.glob("*.json"):
            assert path.parent == hood.claims_dir


class TestConcurrency:
    def test_only_one_thread_wins_the_same_resource(self, hood):
        winners: list[bool] = []
        lock = threading.Lock()

        def grab(name: str) -> None:
            granted, _ = hood.claim("keyboard", name, ttl=60)
            with lock:
                winners.append(granted)

        threads = [
            threading.Thread(target=grab, args=(f"twin-{i}",)) for i in range(8)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert winners.count(True) == 1

    def test_concurrent_chat_does_not_lose_or_duplicate_sequences(self, hood):
        def chatter(name: str) -> None:
            for i in range(5):
                hood.say(name, f"{name}-{i}")

        threads = [
            threading.Thread(target=chatter, args=(f"t{i}",)) for i in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        seqs = [m["seq"] for m in hood.messages()]
        assert sorted(seqs) == list(range(1, 21))


@pytest.fixture
def server(hood):
    httpd = serve(hood, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield hood, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _post(url: str, body: dict, token: str = "") -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if token:
        request.add_header("X-Coop-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read())


class TestHttpSurface:
    def test_browser_and_model_posts_are_indistinguishable(self, server):
        _, base = server
        # A person typing in the page sends a full envelope.
        status_a, _ = _post(
            f"{base}/chat",
            {"action": "chat", "payload": {"from": "kody", "kind": "human",
                                           "text": "taking the keyboard"}},
        )
        # A model may send the bare payload; the server normalises it.
        status_b, _ = _post(
            f"{base}/chat", {"from": "warden", "kind": "agent", "text": "ack"}
        )
        assert (status_a, status_b) == (201, 201)
        messages = _get(f"{base}/chat")["messages"]
        assert [m["payload"]["from"] for m in messages] == ["kody", "warden"]
        assert messages[0]["payload"].keys() == messages[1]["payload"].keys()

    def test_chat_cursor_over_http(self, server):
        _, base = server
        _post(f"{base}/chat", {"from": "a", "text": "one"})
        _post(f"{base}/chat", {"from": "a", "text": "two"})
        assert len(_get(f"{base}/chat?since=1")["messages"]) == 1

    def test_claims_over_http_are_exclusive(self, server):
        _, base = server
        first, _ = _post(
            f"{base}/claims",
            {"action": "claim", "payload": {"resource": "keyboard",
                                            "holder": "a", "ttl": 60}},
        )
        second, body = _post(
            f"{base}/claims",
            {"action": "claim", "payload": {"resource": "keyboard",
                                            "holder": "b", "ttl": 60}},
        )
        assert first == 200
        assert second == 409
        assert body["holder"] == "a"

    def test_release_over_http(self, server):
        _, base = server
        _post(
            f"{base}/claims",
            {"action": "claim", "payload": {"resource": "warden",
                                            "holder": "a"}},
        )
        status, _ = _post(
            f"{base}/claims",
            {"action": "release", "payload": {"resource": "warden",
                                              "holder": "a"}},
        )
        assert status == 200
        assert _get(f"{base}/claims")["claims"] == []

    def test_presence_over_http(self, server):
        _, base = server
        _post(f"{base}/twins", {"id": "warden", "kind": "agent",
                                "role": "rest"})
        assert [t["id"] for t in _get(f"{base}/twins")["twins"]] == ["warden"]

    def test_empty_message_is_a_400_not_a_crash(self, server):
        _, base = server
        status, _ = _post(f"{base}/chat", {"from": "a", "text": "  "})
        assert status == 400

    def test_unknown_route_is_404(self, server):
        _, base = server
        with pytest.raises(urllib.error.HTTPError) as caught:
            _get(f"{base}/nope")
        assert caught.value.code == 404

    def test_health(self, server):
        _, base = server
        assert _get(f"{base}/health")["status"] == "ok"


class TestTokenGuard:
    def test_writes_require_the_token_but_reads_do_not(self, hood):
        httpd = serve(hood, host="127.0.0.1", port=0, token="s3cret")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            assert _post(f"{base}/chat", {"from": "a", "text": "hi"})[0] == 401
            assert _get(f"{base}/chat")["messages"] == []
            status, _ = _post(
                f"{base}/chat", {"from": "a", "text": "hi"}, token="s3cret"
            )
            assert status == 201
        finally:
            httpd.shutdown()
            httpd.server_close()


class TestRemoteIsInterchangeable:
    """A twin must not be able to tell local files from a remote server."""

    def test_remote_and_local_agree_on_every_operation(self, server):
        local, base = server
        remote = RemoteNeighborhood(base)

        remote.check_in("mac-twin", kind="agent", role="builder")
        remote.say("mac-twin", "claiming the keyboard", kind="agent")
        granted, _ = remote.claim("keyboard", "mac-twin", ttl=60)

        assert granted
        # The local view of the very same state matches.
        assert [t.id for t in local.twins()] == ["mac-twin"]
        assert [m["payload"]["text"] for m in local.messages()] == [
            "claiming the keyboard"
        ]
        assert [c.holder for c in local.claims()] == ["mac-twin"]

        # And the remote view matches the local one.
        assert [t.id for t in remote.twins()] == ["mac-twin"]
        assert [c.resource for c in remote.claims()] == ["keyboard"]

    def test_remote_refuses_a_lease_held_locally(self, server):
        local, base = server
        local.claim("warden", "battlestation", ttl=60)
        granted, current = RemoteNeighborhood(base).claim("warden", "mac-twin")
        assert not granted
        assert current.holder == "battlestation"

    def test_remote_release(self, server):
        local, base = server
        remote = RemoteNeighborhood(base)
        remote.claim("stream", "mac-twin", ttl=60)
        assert remote.release("stream", "mac-twin") is True
        assert local.claims() == []

    def test_cursor_is_honoured_remotely(self, server):
        _, base = server
        remote = RemoteNeighborhood(base)
        first = remote.say("a", "one")
        remote.say("a", "two")
        later = remote.messages(since=first["seq"])
        assert [m["payload"]["text"] for m in later] == ["two"]

    @pytest.mark.parametrize("bad", ["file:///etc/passwd", "ftp://h/x", "nope"])
    def test_non_http_urls_are_refused(self, bad):
        with pytest.raises(ValueError, match="http"):
            RemoteNeighborhood(bad)

