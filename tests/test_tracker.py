"""RunTracker against the websocket messages captured in the spike (spike/fixtures)."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from haybale_comfyui.runtime.tracker import Outcome, RunTracker

FIXTURES = Path(__file__).parent.parent / "spike" / "fixtures"


def replay(log_name: str, run: str) -> tuple[str, list[str | bytes]]:
    """The prompt id and the messages of one captured run; binary frames get fake PNG bodies."""
    log = json.loads((FIXTURES / log_name).read_text())
    entries = [e for e in log if e.get("run") == run]
    starts = [e["msg"] for e in entries if e["kind"] == "json" and e["msg"]["type"] == "execution_start"]
    pid = starts[0]["data"]["prompt_id"]
    messages: list[str | bytes] = []
    for i, e in enumerate(entries):
        if e["kind"] == "binary":
            messages.append(struct.pack(">II", *e["header"]) + b"PNG-%d" % i)
        elif e["kind"] == "json":
            messages.append(json.dumps(e["msg"]))
    return pid, messages


def track(pid: str, messages: list[str | bytes]) -> RunTracker:
    tracker = RunTracker(pid)
    for m in messages:
        tracker.feed(m)
        if tracker.done:
            break
    return tracker


def test_save_image_websocket_frame_goes_under_its_node() -> None:
    tracker = track(*replay("ws_log.json", "run1"))
    assert tracker.outcome is Outcome.SUCCESS
    assert list(tracker.images) == ["7"]
    assert len(tracker.images["7"]) == 1
    assert tracker.progress is not None
    assert (tracker.progress.node, tracker.progress.max) == ("7", 1)


def test_sampler_progress_is_reported() -> None:
    pid, messages = replay("ws_log.json", "run1")
    tracker, seen = RunTracker(pid), []
    for m in messages:
        tracker.feed(m)
        if tracker.progress and tracker.progress.node == "5":
            seen.append(tracker.progress.value)
    assert sorted(set(seen)) == [1, 3, 4, 5, 6]


def test_identical_run_of_save_image_websocket_still_sends_the_image() -> None:
    tracker = track(*replay("ws_log.json", "run2_identical"))
    assert tracker.cached_nodes == ["1", "2", "3", "4", "5", "6"]
    assert len(tracker.images["7"]) == 1
    assert tracker.cached_outputs == []


def test_krita_output_frame_is_named_by_its_info() -> None:
    tracker = track(*replay("placeholder_log.json", "rewritten1"))
    assert tracker.outcome is Outcome.SUCCESS
    assert list(tracker.images) == ["Result"]


def test_cached_krita_output_has_no_frame_and_is_reported() -> None:
    tracker = track(*replay("placeholder_log.json", "rewritten2_identical"))
    assert tracker.outcome is Outcome.SUCCESS
    assert tracker.images == {}
    assert tracker.cached_outputs == ["Result"]


def test_interrupt_ends_the_run() -> None:
    data = json.loads((FIXTURES / "errors.json").read_text())["interrupt"]
    msgs = [json.dumps(m) for m in data if isinstance(m, dict) and "type" in m]
    pid = next(json.loads(m)["data"]["prompt_id"] for m in msgs if '"execution_start"' in m)
    tracker = track(pid, msgs)
    assert tracker.outcome is Outcome.INTERRUPTED
    assert tracker.error is not None
    assert tracker.error["node_type"] == "KSampler"


def test_messages_of_other_prompts_are_ignored() -> None:
    pid, messages = replay("ws_log.json", "run1")
    tracker = track("someone-else", messages)
    assert tracker.outcome is Outcome.RUNNING
    assert tracker.images == {}
    assert tracker.progress is None


@pytest.mark.parametrize("frame", [b"", b"\x00\x00\x00\x01", struct.pack(">II", 3, 2) + b"x"])
def test_short_or_foreign_frames_are_dropped(frame: bytes) -> None:
    tracker = RunTracker("p")
    tracker.feed(json.dumps({"type": "executing", "data": {"node": "1", "prompt_id": "p"}}))
    tracker.feed(frame)
    tracker.feed(json.dumps({"type": "execution_success", "data": {"prompt_id": "p"}}))
    assert tracker.images == {}
