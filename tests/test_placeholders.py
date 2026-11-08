"""Placeholder parsing, checking and rewriting, on the workflows captured in the spike."""

from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path

import pytest

from haybale_comfyui.runtime.placeholders import (
    IMAGE_LOADER,
    Kind,
    missing_inputs,
    parse_default,
    read_interface,
    rewrite,
    slug,
)

FIXTURES = Path(__file__).parent.parent / "spike" / "fixtures"
LIVE_URL = os.environ.get("COMFYUI_URL")


def published(log_name: str) -> list[dict]:
    """The workflows of every ``etn_workflow_published`` message in a fixture."""
    log = json.loads((FIXTURES / log_name).read_text())
    msgs = [e.get("msg", e) for e in log]
    return [m["data"]["workflow"] for m in msgs if m.get("type") == "etn_workflow_published"]


@pytest.fixture
def img2img() -> dict:
    return published("placeholder_log.json")[0]


def test_img2img_interface(img2img: dict) -> None:
    interface = read_interface(img2img)
    assert interface.usable
    params = {p.name: p for p in interface.parameters}
    assert set(params) == {"Prompt", "Strength", "Seed"}
    assert params["Strength"].default == 0.6
    assert (params["Strength"].min, params["Strength"].max) == (0.0, 1.0)
    assert params["Seed"].default == 1
    assert isinstance(params["Seed"].default, int)
    assert params["Prompt"].consumers == (("2", "text"),)
    assert [p.port_id for p in interface.images] == ["image_source"]
    assert [(p.name, p.kind) for p in interface.outputs] == [("Result", Kind.OUTPUT)]


def test_rewrite_replaces_placeholders(img2img: dict) -> None:
    out = rewrite(img2img, {"Prompt": "a pear", "Seed": 9}, {"Source": "QUJD"})
    assert not {"10", "11", "12"} & set(out)
    assert out["2"]["inputs"]["text"] == "a pear"
    assert out["5"]["inputs"]["seed"] == 9
    assert out["5"]["inputs"]["denoise"] == 0.6  # default
    assert out["20"] == {"class_type": IMAGE_LOADER, "inputs": {"image": "QUJD"}}
    assert out["4"]["inputs"]["pixels"] == ["20", 0]
    assert img2img["2"]["inputs"]["text"] == ["10", 0]  # input left untouched


def test_rewrite_needs_every_image(img2img: dict) -> None:
    with pytest.raises(KeyError, match="Source"):
        rewrite(img2img, {}, {})


def test_browser_publish_without_link_is_flagged() -> None:
    workflows = published("browser_publish.json")
    browser = [w for w in workflows if "72" in w]
    first = browser[0]
    interface = read_interface(first)
    assert [p.name for p in interface.outputs] == ["72"]  # unnamed output → its node id
    info = {"ETN_KritaOutput": {"input": {"required": {"images": [], "x": [], "y": [], "name": []}}}}
    assert missing_inputs(first, info) == [
        "node 72 (ETN_KritaOutput): required input 'images' is not connected"
    ]


def test_flattened_subgraph_ids_stay_strings() -> None:
    with_subgraph = next(w for w in published("browser_publish.json") if "74:62" in w)
    out = rewrite(with_subgraph, {}, {})
    assert "74:62" in out
    assert out["74:64"]["inputs"]["conditioning"] == ["74:67", 0]


def test_unknown_nodes_are_reported() -> None:
    assert missing_inputs({"1": {"class_type": "Nope", "inputs": {}}}, {}) == [
        "node 1: Nope is not installed on the server"
    ]


def test_problems_make_it_unusable() -> None:
    wf = {
        "1": {"class_type": "ETN_Parameter", "inputs": {"name": "A b", "type": "text", "default": ""}},
        "2": {"class_type": "ETN_Parameter", "inputs": {"name": "a-B", "type": "text", "default": ""}},
        "3": {"class_type": "ETN_KritaSelection", "inputs": {}},
    }
    interface = read_interface(wf)
    assert not interface.usable
    assert any("two placeholders" in p for p in interface.problems)
    assert any("ETN_KritaSelection" in p for p in interface.problems)
    assert any("no output placeholder" in p for p in interface.problems)


@pytest.mark.parametrize(
    ("ptype", "text", "expected"),
    [
        ("number", "0.5", 0.5),
        ("number", "", 0.0),
        ("number (integer)", "3", 3),
        ("number (integer)", "3.0", 3),
        ("toggle", "true", True),
        ("toggle", "False", False),
        ("text", "hi ", "hi "),
        ("choice", "euler", "euler"),
    ],
)
def test_parse_default(ptype: str, text: str, expected: object) -> None:
    assert parse_default(ptype, text) == expected


def test_slug() -> None:
    assert slug("  Prompt (positive) ") == "prompt_positive"
    assert slug("!!") == "unnamed"


@pytest.mark.skipif(not LIVE_URL, reason="set COMFYUI_URL to run against a ComfyUI server")
def test_live_rewritten_img2img_runs(img2img: dict) -> None:
    from PIL import Image

    from haybale_comfyui.runtime.client import ComfyClient

    buf = io.BytesIO()
    Image.new("RGB", (256, 256), (200, 30, 30)).save(buf, format="PNG")
    seed = int.from_bytes(os.urandom(4), "big")
    wf = rewrite(img2img, {"Seed": seed}, {"Source": base64.b64encode(buf.getvalue()).decode()})
    with ComfyClient(str(LIVE_URL)) as client:
        assert missing_inputs(wf, client.object_info()) == []
        tracker = client.run(wf)
    assert list(tracker.images) == ["Result"]
    png = tracker.images["Result"][0]
    assert int.from_bytes(png[16:20], "big") == 256
