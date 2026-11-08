"""ComfyUI Workflow node: ports from placeholders, the stored workflow, and a live run."""

from __future__ import annotations

import os
import threading
from typing import Any

import numpy as np
import pytest

from tests.conftest import add_node

NODE = ("haybale_comfyui.nodes.comfyui_workflow", "ComfyUIWorkflowNode")
LIVE_URL = os.environ.get("COMFYUI_URL")

WORKFLOW = {
    "1": {"class_type": "HaywireParameter", "inputs": {"name": "Gain", "type": "number", "default": "1.5"}},
    "2": {"class_type": "HaywireParameter", "inputs": {"name": "Count", "type": "integer", "default": "3"}},
    "3": {"class_type": "HaywireParameter", "inputs": {"name": "Flip", "type": "toggle", "default": "true"}},
    "4": {"class_type": "HaywireImage", "inputs": {"name": "Source"}},
    "5": {
        "class_type": "ImageScaleBy",
        "inputs": {"image": ["4", 0], "upscale_method": "nearest-exact", "scale_by": ["1", 0]},
    },
    "6": {"class_type": "HaywireOutput", "inputs": {"images": ["5", 0], "name": "Result"}},
}


def port_ids(node: Any) -> set[str]:
    return {p.id for p in node.get_all_ports()}


@pytest.mark.integration
def test_new_node_has_only_the_image_outlet_and_refuses_to_run(graph: Any) -> None:
    """A data node needs an outlet from the start (structural validation)."""
    from haywire.core.execution.execution_context import ExecutionContext

    node = add_node(graph, *NODE)
    assert {pid for pid in port_ids(node) if pid.startswith(("param_", "image_", "out_"))} == {"out_image"}
    assert not node.wrapper.state.error_structural
    with pytest.raises(ValueError, match="pick one"):
        node.worker(ExecutionContext(global_ctx={}, local_ctx={}))


@pytest.mark.integration
def test_apply_builds_ports_and_stores_the_workflow(graph: Any) -> None:
    node = add_node(graph, *NODE)
    interface = node.apply_workflow("test.json", WORKFLOW)
    assert interface.problems == []
    assert {"param_gain", "param_count", "param_flip", "image_source", "out_result"} <= port_ids(node)
    assert node.value("param_gain") == 1.5
    assert node.value("param_count") == 3
    assert node.value("param_flip") is True
    assert node.store.workflow == WORKFLOW
    assert node.store.workflow_name == "test.json"
    assert node.source.workflow == "test.json"


@pytest.mark.integration
def test_reapply_drops_ports_that_are_gone(graph: Any) -> None:
    node = add_node(graph, *NODE)
    node.apply_workflow("test.json", WORKFLOW)
    smaller = {k: v for k, v in WORKFLOW.items() if k not in ("2", "3")}
    node.apply_workflow("test.json", smaller)
    ids = port_ids(node)
    assert "param_count" not in ids
    assert "param_flip" not in ids
    assert "param_gain" in ids


@pytest.mark.integration
def test_problems_show_on_the_card(graph: Any) -> None:
    node = add_node(graph, *NODE)
    node.apply_workflow("broken.json", {"1": WORKFLOW["1"]})
    messages = [w.message for w in node.wrapper.state.warnings]
    assert any("no output placeholder" in m for m in messages)


@pytest.mark.integration
def test_new_version_is_flagged_not_applied(graph: Any) -> None:
    from haybale_comfyui.runtime.directory import Entry

    node = add_node(graph, *NODE)
    node.apply_workflow("test.json", WORKFLOW)
    changed = dict(
        WORKFLOW,
        **{
            "1": {
                "class_type": "HaywireParameter",
                "inputs": {"name": "Gain", "type": "number", "default": "9"},
            }
        },
    )
    node._on_published(Entry("test.json", "page", changed, 0.0))
    assert any("Reload" in w.message for w in node.wrapper.state.warnings)
    assert node.store.workflow == WORKFLOW


def test_combo_options_both_formats() -> None:
    from haybale_comfyui.nodes.comfyui_workflow import combo_options

    info = {
        "A": {"input": {"required": {"s": [["euler", "dpm"]]}}},
        "B": {"input": {"optional": {"s": ["COMBO", {"options": ["x", "y"]}]}}},
        "C": {"input": {"required": {"s": ["INT", {}]}}},
    }
    assert combo_options(info, "A", "s") == ["euler", "dpm"]
    assert combo_options(info, "B", "s") == ["x", "y"]
    assert combo_options(info, "C", "s") == []
    assert combo_options(info, "D", "s") == []


@pytest.mark.integration
@pytest.mark.skipif(not LIVE_URL, reason="set COMFYUI_URL to run against a ComfyUI server")
def test_live_worker_returns_the_image(graph: Any) -> None:
    from haybale_image.value import ImageValue
    from haywire.core.execution.execution_context import ExecutionContext

    from haybale_comfyui.runtime.client import ComfyClient
    from haybale_comfyui.settings.comfyui_settings import ComfyUISettings

    with ComfyClient(str(LIVE_URL)) as probe:
        if probe.protocol() is None:
            pytest.skip("comfyui-haywire is not installed on the server")
    ComfyUISettings().server_url = str(LIVE_URL)
    node = add_node(graph, *NODE)
    node.apply_workflow("test.json", WORKFLOW)
    pixels = np.zeros((10, 30, 4), dtype=np.uint8)
    pixels[..., 0], pixels[..., 3] = 255, 200
    node.ports["image_source"].set_value(ImageValue.from_array(pixels))
    node.ports["param_gain"].set_value(2.0)
    node.worker(ExecutionContext(global_ctx={}, local_ctx={}, cancel=threading.Event()))
    result = node.value("out_result")
    assert (result.width, result.height) == (60, 20)
    assert result.array(np.uint8)[0, 0, 0] == 255
    node.on_shutdown(ExecutionContext(global_ctx={}, local_ctx={}))


@pytest.mark.integration
@pytest.mark.skipif(not LIVE_URL, reason="set COMFYUI_URL to run against a ComfyUI server")
def test_live_pick_from_the_directory(graph: Any) -> None:
    import time

    from haybale_comfyui.runtime.client import ComfyClient
    from haybale_comfyui.runtime.directory import directory_for
    from haybale_comfyui.settings.comfyui_settings import ComfyUISettings

    ComfyUISettings().server_url = str(LIVE_URL)
    name = f"haybale-comfyui pick test {time.time():.0f}"
    with ComfyClient(str(LIVE_URL)) as publisher:
        if publisher.protocol() is None:
            pytest.skip("comfyui-haywire is not installed on the server")
        directory = directory_for(str(LIVE_URL))
        try:
            publisher.publish(name, WORKFLOW)
            deadline = time.monotonic() + 10
            while directory.get(name) is None and time.monotonic() < deadline:
                time.sleep(0.1)
            assert directory.get(name) is not None, directory.error
            node = add_node(graph, *NODE)
            node.source.workflow = name  # what the picker does
            assert "param_gain" in port_ids(node)
            assert node.store.workflow_name == name
        finally:
            publisher.withdraw()


def test_run_progress_labels_and_share() -> None:
    from haybale_comfyui.nodes.comfyui_workflow import node_titles, run_progress
    from haybale_comfyui.runtime.tracker import RunTracker
    from tests.test_tracker import replay

    pid, messages = replay("ws_log.json", "run1")
    prompt = {
        "1": {"class_type": "CheckpointLoaderSimple", "_meta": {"title": "Load Checkpoint"}},
        "2": {"class_type": "CLIPTextEncode"},
        "3": {"class_type": "CLIPTextEncode"},
        "4": {"class_type": "EmptyLatentImage"},
        "5": {"class_type": "KSampler", "_meta": {"title": "KSampler"}},
        "6": {"class_type": "VAEDecode"},
        "7": {"class_type": "SaveImageWebsocket"},
    }
    titles = node_titles(prompt)
    tracker = RunTracker(pid)
    labels, shares = [], []
    assert run_progress(tracker, titles) == (0.0, "queued")
    for m in messages:
        tracker.feed(m)
        share, label = run_progress(tracker, titles)
        labels.append(label)
        shares.append(share)
    assert "Load Checkpoint" in labels
    assert "KSampler 3/6" in labels
    assert "VAEDecode" in labels
    assert shares == sorted(shares)
    assert shares[-1] == 1.0
