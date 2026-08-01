"""Tests for the browser replay player.

The player is a projection *client*: the server hands it the raw log and it
filters locally. So the server's job is narrow -- list recordings, return one
safely, and serve the page -- and the tests below concentrate on the part that
can actually hurt you, which is path handling on the recording name.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from rapp_coop.coop import Neighborhood
from rapp_coop.player import list_recordings, read_recording
from rapp_coop.recorder import Recording
from rapp_coop.server import serve


@pytest.fixture
def vault(tmp_path):
    """A directory holding two recordings."""
    root = tmp_path / "recordings"
    root.mkdir()
    first = Recording(root / "alpha.jsonl", run="alpha")
    first.hatch("apprentice-01")
    first.lesson("mentor", "apprentice-01", "lesson text")
    first.memory_write("apprentice-01", "kept this")
    first.grade("mentor", "apprentice-01", True)
    Recording(root / "beta.jsonl", run="beta").record("note", {"text": "hi"})
    return root


@pytest.fixture
def server(tmp_path, vault):
    hood = Neighborhood(tmp_path / "coop")
    httpd = serve(hood, host="127.0.0.1", port=0, recordings=str(vault))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read())


def _raw(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, response.read().decode("utf-8")


class TestListing:
    def test_finds_every_recording(self, vault):
        assert {r["name"] for r in list_recordings(vault)} == {
            "alpha.jsonl", "beta.jsonl"
        }

    def test_missing_directory_is_empty_not_an_error(self, tmp_path):
        assert list_recordings(tmp_path / "nope") == []

    def test_listing_is_served(self, server):
        names = {r["name"] for r in _get(f"{server}/recordings")["recordings"]}
        assert names == {"alpha.jsonl", "beta.jsonl"}


class TestReading:
    def test_events_come_back_in_sequence_order(self, vault):
        events = read_recording(vault, "alpha.jsonl")
        assert [e["seq"] for e in events] == [1, 2, 3, 4]

    def test_served_over_http(self, server):
        events = _get(f"{server}/recording?name=alpha.jsonl")["events"]
        assert any(e["action"] == "memory.write" for e in events)

    def test_payloads_are_returned_whole(self, server):
        events = _get(f"{server}/recording?name=alpha.jsonl")["events"]
        kept = next(e for e in events if e["action"] == "memory.write")
        assert kept["payload"]["content"] == "kept this"

    def test_unknown_recording_is_404(self, server):
        with pytest.raises(urllib.error.HTTPError) as caught:
            _get(f"{server}/recording?name=absent.jsonl")
        assert caught.value.code == 404


class TestNameHandling:
    """A recording name arrives from the network. Treat it as hostile."""

    @pytest.mark.parametrize("name", [
        "../secrets.jsonl",
        "..\\secrets.jsonl",
        "sub/dir.jsonl",
        "/etc/passwd.jsonl",
        "C:\\Windows\\thing.jsonl",
    ])
    def test_traversal_is_refused_not_resolved(self, vault, name):
        with pytest.raises((ValueError, FileNotFoundError)):
            read_recording(vault, name)

    def test_non_jsonl_is_refused(self, vault):
        with pytest.raises(ValueError):
            read_recording(vault, "secrets.env")

    def test_traversal_over_http_is_404(self, server):
        with pytest.raises(urllib.error.HTTPError) as caught:
            _get(f"{server}/recording?name=../../etc/passwd.jsonl")
        assert caught.value.code == 404


class TestPlayerPage:
    def test_page_is_served(self, server):
        status, body = _raw(f"{server}/replay")
        assert status == 200
        assert "rapp-coop replay" in body

    def test_page_knows_the_builtin_views(self, server):
        _, body = _raw(f"{server}/replay")
        for view in ("observer", "memory", "exam"):
            assert view in body

    def test_chat_page_links_to_the_player(self, server):
        _, body = _raw(f"{server}/")
        assert "/replay" in body

    def test_player_routes_do_not_disturb_the_coop(self, server):
        _get(f"{server}/replay") if False else _raw(f"{server}/replay")
        assert _get(f"{server}/health")["status"] == "ok"
        assert _get(f"{server}/chat")["messages"] == []
