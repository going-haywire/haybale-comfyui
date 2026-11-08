"""ComfyClient: pure helpers here; a live run when COMFYUI_URL points at a server."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from haybale_comfyui.runtime.placeholders import ETN, HAYWIRE, Pack
from haybale_comfyui.runtime.client import (
    ComfyClient,
    PromptRejected,
    describe_rejection,
    websocket_url,
)

FIXTURES = Path(__file__).parent.parent / "spike" / "fixtures"
LIVE_URL = os.environ.get("COMFYUI_URL")
live = pytest.mark.skipif(not LIVE_URL, reason="set COMFYUI_URL to run against a ComfyUI server")


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("http://127.0.0.1:8188", "ws://127.0.0.1:8188/ws?clientId=c"),
        ("https://comfy.example/", "wss://comfy.example/ws?clientId=c"),
        ("127.0.0.1:8188", "ws://127.0.0.1:8188/ws?clientId=c"),
    ],
)
def test_websocket_url(base: str, expected: str) -> None:
    assert websocket_url(base, "c") == expected


def test_rejection_names_node_and_input() -> None:
    body = json.loads((FIXTURES / "errors.json").read_text())["bad_ckpt"]["body"]
    text = describe_rejection(body["error"], body["node_errors"])
    assert text.splitlines()[0] == "Prompt outputs failed validation"
    assert "node 1 (CheckpointLoaderSimple): Value not in list: ckpt_name: 'missing.safetensors'" in text


@live
def test_live_bad_workflow_is_rejected() -> None:
    with ComfyClient(str(LIVE_URL)) as client, pytest.raises(PromptRejected) as info:
        client.submit(
            {
                "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "nope"}},
                "2": {"class_type": "SaveImageWebsocket", "inputs": {"images": ["1", 0]}},
            }
        )
    assert info.value.node_errors
    assert "SaveImageWebsocket" in str(info.value)


@live
def test_live_run_returns_the_image_and_reports_progress() -> None:
    workflow = {
        "1": {
            "class_type": "EmptyImage",
            "inputs": {"width": 64, "height": 32, "batch_size": 1, "color": 255},
        },
        "2": {"class_type": "SaveImageWebsocket", "inputs": {"images": ["1", 0]}},
    }
    seen = []
    with ComfyClient(str(LIVE_URL)) as client:
        tracker = client.run(workflow, on_progress=lambda t: seen.append(t.progress))
    assert list(tracker.images) == ["2"]
    png = tracker.images["2"][0]
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert int.from_bytes(png[16:20], "big") == 64
    assert seen


@live
@pytest.mark.parametrize("pack", [HAYWIRE, ETN], ids=["haywire", "etn"])
def test_live_exchange_replays_to_a_new_subscriber(pack: Pack) -> None:
    workflow = {"1": {"class_type": "Any", "inputs": {"name": "p"}}}
    with ComfyClient(str(LIVE_URL)) as publisher, ComfyClient(str(LIVE_URL)) as subscriber:
        if pack is HAYWIRE and publisher.protocol() is None:
            pytest.skip("comfyui-haywire is not installed on the server")
        publisher.publish("haybale-comfyui test", workflow, pack)
        subscriber.subscribe(pack)
        try:
            found = subscriber.wait_published(timeout=2.0, pack=pack)
        finally:
            subscriber.unsubscribe(pack)
            if pack is HAYWIRE:
                publisher.withdraw(pack)
    mine = [p for p in found if p.publisher_id == publisher.client_id]
    assert mine
    assert mine[-1].workflow == workflow


@live
def test_live_cancel_interrupts_the_run() -> None:
    from haybale_comfyui.runtime.client import Cancelled

    workflow = json.loads((FIXTURES / "rewritten_wf_without_image.json").read_text())
    workflow["20"] = {
        "class_type": "EmptyImage",
        "inputs": {"width": 512, "height": 512, "batch_size": 1, "color": 0},
    }
    workflow["5"]["inputs"]["steps"] = 30
    workflow["5"]["inputs"]["seed"] = int.from_bytes(os.urandom(4), "big")
    with ComfyClient(str(LIVE_URL)) as client:
        state = {"steps": 0}

        def progressed(tracker: object) -> None:
            state["steps"] += 1

        with pytest.raises(Cancelled):
            client.run(workflow, on_progress=progressed, cancel=lambda: state["steps"] >= 2)
        queue = client._json("GET", "/queue")
    assert queue["queue_running"] == []
