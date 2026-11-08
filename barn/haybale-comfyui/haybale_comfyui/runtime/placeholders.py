"""Placeholder nodes in an API-format ComfyUI workflow: find them, check them, replace them.

Pure functions over plain dicts. The only place that knows the server pack's node names is
the mapping table below, so moving from comfyui-tooling-nodes (Option A) to our own pack
(Option B, design note §5) changes the table and nothing else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Kind(Enum):
    """What a placeholder becomes on the haywire node."""

    PARAMETER = "parameter"
    IMAGE = "image"
    OUTPUT = "output"


#: Placeholder class → kind (Option A: comfyui-tooling-nodes).
PLACEHOLDERS: dict[str, Kind] = {
    "ETN_Parameter": Kind.PARAMETER,
    "ETN_KritaImageLayer": Kind.IMAGE,
    "ETN_KritaOutput": Kind.OUTPUT,
}

#: Placeholders the pack has but this library does not drive yet.
UNSUPPORTED: frozenset[str] = frozenset(
    {
        "ETN_KritaCanvas",
        "ETN_KritaSelection",
        "ETN_KritaMaskLayer",
        "ETN_KritaStyle",
        "ETN_KritaStyleAndPrompt",
        "ETN_KritaSendText",
    }
)

#: The node an image placeholder is replaced by; input ``image`` takes a base64 PNG and its
#: outputs (image, mask) line up with the placeholder's.
IMAGE_LOADER = "ETN_LoadImageBase64"

#: Parameter types of ``ETN_Parameter``.
PARAMETER_TYPES = (
    "auto",
    "number",
    "number (integer)",
    "toggle",
    "choice",
    "text",
    "prompt (positive)",
    "prompt (negative)",
)


@dataclass(frozen=True)
class Placeholder:
    """One placeholder node, read from the workflow."""

    node_id: str
    kind: Kind
    name: str
    #: ``ETN_Parameter`` type; empty for images and outputs.
    type: str = ""
    default: Any = None
    min: float | None = None
    max: float | None = None
    #: The inputs fed by this placeholder, as (node id, input name).
    consumers: tuple[tuple[str, str], ...] = ()

    @property
    def port_id(self) -> str:
        prefix = {Kind.PARAMETER: "param", Kind.IMAGE: "image", Kind.OUTPUT: "out"}[self.kind]
        return f"{prefix}_{slug(self.name)}"


@dataclass
class Interface:
    """Everything the haywire node needs to build its ports, and what is wrong with the workflow."""

    parameters: list[Placeholder] = field(default_factory=list)
    images: list[Placeholder] = field(default_factory=list)
    outputs: list[Placeholder] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return bool(self.outputs) and not self.problems


def slug(name: str) -> str:
    """A port-id-safe form of a placeholder name: lower case, ``_`` between words."""
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_") or "unnamed"


def parse_default(param_type: str, text: Any) -> Any:
    """The typed default of a parameter; ``ETN_Parameter`` stores every default as text."""
    raw = "" if text is None else str(text).strip()
    if param_type == "number":
        return float(raw) if raw else 0.0
    if param_type == "number (integer)":
        return int(float(raw)) if raw else 0
    if param_type == "toggle":
        return raw.lower() in ("true", "1", "yes", "on")
    return "" if text is None else str(text)


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def consumers_of(workflow: dict[str, Any], node_id: str) -> tuple[tuple[str, str], ...]:
    """The (node id, input name) pairs linked to any output of *node_id*."""
    found = []
    for nid, node in workflow.items():
        for key, value in (node.get("inputs") or {}).items():
            if isinstance(value, list) and len(value) == 2 and str(value[0]) == node_id:
                found.append((nid, key))
    return tuple(found)


def read_interface(workflow: dict[str, Any]) -> Interface:
    """Find the placeholders of an API-format *workflow* and report what stops it being used."""
    result = Interface()
    for node_id, node in workflow.items():
        cls, inputs = node.get("class_type", ""), node.get("inputs") or {}
        if cls in UNSUPPORTED:
            result.problems.append(f"{cls} (node {node_id}) is not supported yet")
            continue
        kind = PLACEHOLDERS.get(cls)
        if kind is None:
            continue
        name = str(inputs.get("name") or "").strip()
        if kind is Kind.OUTPUT:
            result.outputs.append(Placeholder(node_id, kind, name or node_id))
        elif kind is Kind.IMAGE:
            result.images.append(
                Placeholder(node_id, kind, name or node_id, consumers=consumers_of(workflow, node_id))
            )
        else:
            ptype = str(inputs.get("type") or "auto")
            if ptype not in PARAMETER_TYPES:
                result.problems.append(f"parameter {name!r} (node {node_id}) has unknown type {ptype!r}")
                continue
            try:
                default = parse_default(ptype, inputs.get("default"))
            except ValueError:
                result.problems.append(
                    f"parameter {name!r}: default {inputs.get('default')!r} is not a {ptype}"
                )
                continue
            result.parameters.append(
                Placeholder(
                    node_id,
                    kind,
                    name or node_id,
                    type=ptype,
                    default=default,
                    min=_number(inputs.get("min")),
                    max=_number(inputs.get("max")),
                    consumers=consumers_of(workflow, node_id),
                )
            )
    if not result.outputs:
        result.problems.append("no output placeholder: add a Krita Output node")
    for group in (result.parameters + result.images, result.outputs):
        seen: dict[str, str] = {}
        for p in group:
            if p.port_id in seen:
                result.problems.append(
                    f"two placeholders named {p.name!r} (nodes {seen[p.port_id]} and {p.node_id})"
                )
            seen[p.port_id] = p.node_id
    return result


def missing_inputs(workflow: dict[str, Any], object_info: dict[str, Any]) -> list[str]:
    """Problems ComfyUI would reject the workflow for: unknown nodes, required inputs not set.

    A published workflow can be half-built (design note §3.3); check before offering it.
    """
    problems = []
    for node_id, node in workflow.items():
        cls = node.get("class_type", "")
        info = object_info.get(cls)
        if info is None:
            problems.append(f"node {node_id}: {cls or '?'} is not installed on the server")
            continue
        given = node.get("inputs") or {}
        for key in (info.get("input") or {}).get("required", {}):
            if key not in given:
                problems.append(f"node {node_id} ({cls}): required input {key!r} is not connected")
    return problems


def rewrite(
    workflow: dict[str, Any],
    values: dict[str, Any],
    images: dict[str, str],
) -> dict[str, Any]:
    """The workflow to submit: placeholders replaced by the haywire node's values.

    Args:
        workflow: API-format workflow holding placeholders.
        values: parameter name → value; a missing name uses the placeholder's default.
        images: image placeholder name → base64-encoded PNG.

    Raises:
        KeyError: an image placeholder has no image.
    """
    interface = read_interface(workflow)
    literal: dict[str, Any] = {}
    for p in interface.parameters:
        literal[p.node_id] = values.get(p.name, p.default)
    loaders: dict[str, dict[str, Any]] = {}
    for p in interface.images:
        if p.name not in images:
            raise KeyError(f"no image for {p.name!r}")
        loaders[p.node_id] = {"class_type": IMAGE_LOADER, "inputs": {"image": images[p.name]}}

    out: dict[str, Any] = {}
    for node_id, node in workflow.items():
        if node_id in literal:
            continue
        if node_id in loaders:
            out[node_id] = loaders[node_id]
            continue
        inputs = {}
        for key, value in (node.get("inputs") or {}).items():
            linked = isinstance(value, list) and len(value) == 2 and str(value[0]) in literal
            inputs[key] = literal[str(value[0])] if linked else value
        copy = {"class_type": node["class_type"], "inputs": inputs}
        if "_meta" in node:
            copy["_meta"] = node["_meta"]
        out[node_id] = copy
    return out
