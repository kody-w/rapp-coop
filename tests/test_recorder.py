"""Tests for telemetry recording and replay.

Two properties carry this module, and most of these tests exist to pin them:

1. **One log reconstructs every perspective.** If a viewpoint cannot be
   recovered by projection, the recording was lossy and "replay from any
   perspective" is false.
2. **Fidelity is additive.** A reader must never lose or choke on data written
   by a richer recorder. If that breaks, every recording ever made expires the
   next time the schema grows.
"""

from __future__ import annotations

import json

import pytest

from rapp_coop.recorder import (
    SCHEMA_VERSION,
    Event,
    Recording,
    actors,
    load,
    redact,
)
from rapp_coop.replay import (
    perspective,
    perspectives,
    play,
    render,
    summarize,
    transcript,
)


@pytest.fixture
def tape(tmp_path):
    return Recording(tmp_path / "run.jsonl", run="run-test")


@pytest.fixture
def schooled(tape):
    """A complete lifecycle: hatch, teach, store, examine, graduate."""
    tape.record("run.start", {"schema": SCHEMA_VERSION})
    tape.hatch("apprentice-01", model="test-model")
    tape.lesson("mentor", "apprentice-01", "Check for --dry-run first.")
    tape.response("apprentice-01", "Understood.")
    tape.memory_write("apprentice-01", "If it looks alive but changes nothing, "
                                       "check --dry-run.", importance=5)
    tape.question("mentor", "apprentice-01", "What do you check first?")
    tape.answer("apprentice-01", "The --dry-run flag.")
    tape.grade("mentor", "apprentice-01", True)
    tape.record("graduate", {"role": "builder"}, actor="mentor",
                subject="apprentice-01")
    tape.record("run.end", {"ok": True})
    return tape


class TestRecording:
    def test_sequences_are_dense_and_monotonic(self, schooled):
        events = load(schooled.path)
        assert [e.seq for e in events] == list(range(1, len(events) + 1))

    def test_monotonic_offsets_never_go_backwards(self, schooled):
        offsets = [e.mono for e in load(schooled.path)]
        assert offsets == sorted(offsets)

    def test_resumes_numbering_across_instances(self, tmp_path):
        first = Recording(tmp_path / "r.jsonl")
        first.record("note", {"text": "one"})
        first.record("note", {"text": "two"})
        second = Recording(tmp_path / "r.jsonl")
        third = second.record("note", {"text": "three"})
        assert third.seq == 3
        assert [e.seq for e in load(tmp_path / "r.jsonl")] == [1, 2, 3]

    def test_every_event_carries_a_schema_version(self, schooled):
        assert all(e.v == SCHEMA_VERSION for e in load(schooled.path))

    def test_missing_file_loads_as_empty(self, tmp_path):
        assert load(tmp_path / "nope.jsonl") == []

    def test_malformed_lines_are_skipped_not_fatal(self, tmp_path):
        path = tmp_path / "r.jsonl"
        tape = Recording(path)
        tape.record("note", {"text": "good"})
        with path.open("a", encoding="utf-8") as handle:
            handle.write("{not json at all\n\n")
        tape.record("note", {"text": "also good"})
        assert [e.text for e in load(path)] == ["good", "also good"]

    def test_run_span_closes_even_when_the_body_raises(self, tmp_path):
        tape = Recording(tmp_path / "r.jsonl")
        with pytest.raises(RuntimeError, match="boom"):
            with tape.run_span():
                raise RuntimeError("boom")
        events = load(tmp_path / "r.jsonl")
        assert events[0].action == "run.start"
        assert events[-1].action == "run.end"
        assert "boom" in events[-1].payload["error"]


class TestForwardCompatibility:
    """Fidelity must be additive. Recordings made today must play in a year."""

    def test_unknown_action_survives_a_round_trip(self, tmp_path):
        path = tmp_path / "future.jsonl"
        path.write_text(
            json.dumps({
                "seq": 1, "at": "2027-01-01T00:00:00Z", "mono": 0.5, "v": 99,
                "action": "neuron.spike", "actor": "future-twin",
                "payload": {"text": "hello from later"},
            }) + "\n",
            encoding="utf-8",
        )
        event = load(path)[0]
        assert event.action == "neuron.spike"
        assert event.v == 99
        assert event.text == "hello from later"

    def test_unknown_top_level_keys_are_preserved_not_dropped(self, tmp_path):
        path = tmp_path / "future.jsonl"
        path.write_text(
            json.dumps({
                "seq": 1, "action": "note", "payload": {"text": "x"},
                "gpu_temp": 71, "trace_id": "abc123",
            }) + "\n",
            encoding="utf-8",
        )
        event = load(path)[0]
        assert event.payload["_gpu_temp"] == 71
        assert event.payload["_trace_id"] == "abc123"

    def test_unknown_payload_keys_are_untouched(self, tape):
        tape.record("note", {"text": "hi", "tokens": 42, "nested": {"a": 1}})
        payload = load(tape.path)[0].payload
        assert payload["tokens"] == 42
        assert payload["nested"] == {"a": 1}

    def test_unknown_action_still_renders(self):
        line = render(Event(seq=1, at="", mono=0.0, action="quantum.entangle",
                            actor="x", payload={"text": "still readable"}))
        assert "quantum.entangle" in line
        assert "still readable" in line

    def test_missing_fields_do_not_crash_the_reader(self, tmp_path):
        path = tmp_path / "sparse.jsonl"
        path.write_text(json.dumps({"action": "note"}) + "\n", encoding="utf-8")
        event = load(path)[0]
        assert event.seq == 0
        assert event.actor == ""


class TestRedaction:
    """A recording is meant to be shared, so it must never leak a credential."""

    @pytest.mark.parametrize("secret", [
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "gho_abcdefghijklmnopqrstuvwxyz0123456789",
        "AKIAIOSFODNN7EXAMPLE",
        "eyJhbGciOiJIUzI1NiIs.eyJzdWIiOiIxMjM0NTY.SflKxwRJSMeKKF2QT4",
    ])
    def test_credentials_never_reach_disk(self, tape, secret):
        tape.record("note", {"text": f"the token is {secret}"})
        raw = tape.path.read_text(encoding="utf-8")
        assert secret not in raw
        assert "[redacted]" in raw

    def test_labelled_password_is_redacted(self, tape):
        tape.record("note", {"text": "AdminPassword=hunter2supersecret"})
        assert "hunter2supersecret" not in tape.path.read_text(encoding="utf-8")

    def test_redaction_reaches_nested_structures(self):
        cleaned = redact({"a": [{"b": "ghp_abcdefghijklmnopqrstuvwxyz0123456789"}]})
        assert "ghp_" not in json.dumps(cleaned)

    def test_ordinary_text_is_left_alone(self, tape):
        tape.record("note", {"text": "the warden restarts cleanly"})
        assert "the warden restarts cleanly" in tape.path.read_text(encoding="utf-8")

    def test_redaction_can_be_disabled_for_a_private_recording(self, tmp_path):
        tape = Recording(tmp_path / "r.jsonl", redact_secrets=False)
        tape.record("note", {"text": "ghp_abcdefghijklmnopqrstuvwxyz0123456789"})
        assert "ghp_" in tape.path.read_text(encoding="utf-8")


class TestPerspectives:
    """One log, many viewpoints -- reconstructed after the fact."""

    def test_observer_sees_everything(self, schooled):
        events = load(schooled.path)
        assert len(perspective(events, "observer")) == len(events)

    def test_apprentice_sees_what_it_did_and_what_was_done_to_it(self, schooled):
        events = load(schooled.path)
        seen = perspective(events, "apprentice-01")
        actions = {e.action for e in seen}
        assert "lesson.deliver" in actions      # addressed to it
        assert "memory.write" in actions        # performed by it
        assert "exam.question" in actions       # addressed to it
        assert all(
            e.actor == "apprentice-01"
            or e.subject == "apprentice-01"
            or e.action in ("run.start", "run.end", "note")
            for e in seen
        )

    def test_memory_view_strips_the_talking(self, schooled):
        seen = perspective(load(schooled.path), "memory")
        actions = {e.action for e in seen}
        assert "memory.write" in actions
        assert "lesson.deliver" not in actions
        assert "agent.response" not in actions

    def test_exam_view_is_only_the_graduation_gate(self, schooled):
        seen = perspective(load(schooled.path), "exam")
        actions = {e.action for e in seen}
        assert actions >= {"exam.question", "exam.answer", "exam.grade"}
        assert "lesson.deliver" not in actions

    def test_run_events_appear_in_every_perspective(self, schooled):
        events = load(schooled.path)
        for view in perspectives(events):
            actions = {e.action for e in perspective(events, view)}
            assert "run.start" in actions, f"{view} lost the run boundary"

    def test_unknown_participant_yields_only_globals_not_an_error(self, schooled):
        seen = perspective(load(schooled.path), "nobody-here")
        assert {e.action for e in seen} <= {"run.start", "run.end", "note"}

    def test_available_perspectives_include_every_participant(self, schooled):
        views = perspectives(load(schooled.path))
        assert {"observer", "memory", "exam"} <= set(views)
        assert "mentor" in views
        assert "apprentice-01" in views

    def test_actors_are_listed_in_first_seen_order(self, schooled):
        assert actors(load(schooled.path))[0] == "apprentice-01"

    def test_no_perspective_invents_events(self, schooled):
        events = load(schooled.path)
        every = {e.seq for e in events}
        for view in perspectives(events):
            assert {e.seq for e in perspective(events, view)} <= every


class TestSummaryAndPlayback:
    def test_summary_counts_the_lifecycle(self, schooled):
        summary = summarize(load(schooled.path))
        assert summary.lessons == 1
        assert summary.memories == 1
        assert summary.questions == 1
        assert summary.passed == 1
        assert summary.failed == 0
        assert "PASSED" in summary.render()

    def test_summary_of_an_empty_recording_does_not_crash(self):
        assert summarize([]).events == 0

    def test_play_is_instant_at_speed_zero(self, schooled):
        lines: list[str] = []
        count = play(load(schooled.path), speed=0.0, out=lines.append)
        assert count == len(lines) > 0

    def test_play_respects_the_perspective(self, schooled):
        lines: list[str] = []
        play(load(schooled.path), view="exam", speed=0.0, out=lines.append)
        assert any("exam.grade" in line for line in lines)
        assert not any("lesson.deliver" in line for line in lines)

    def test_transcript_is_untruncated(self, tape):
        long_text = "x" * 4000
        tape.lesson("mentor", "apprentice", long_text)
        assert long_text in transcript(load(tape.path))

    def test_render_truncates_for_watching(self, tape):
        tape.lesson("mentor", "apprentice", "y" * 4000)
        line = render(load(tape.path)[0], width=96)
        assert len(line) <= 100
        assert "\u2026" in line
